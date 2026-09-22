# gemeo/gemeo/ingest/sunop.py
"""Fonte SunOp (Athon; Axis e a mesma classe com outra instancia). Tres regras que custaram caro:
metadata em DISCO (e a chamada que derruba a borda quando refeita), lote de pathnames atravessando
usinas (o que corta a CONTAGEM — o period so corta payload), e teto diario proprio (a cota e
compartilhada com a plataforma)."""
from __future__ import annotations
import datetime as dt
import json
import re
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from gemeo.core import db as _db
from gemeo.core import tempo
from gemeo.core.modelos import UsinaRef
from gemeo.ingest.base import Busca, Ingestor, avaliar, valor_valido

_RX = [
    (re.compile(r"^\w+\.ESTM[^.]*\.POA\.IRAD$"), lambda m: ("estacao", "ESTM", "poa", {})),
    (re.compile(r"^\w+\.ESTM[^.]*\.GHI\.IRAD$"), lambda m: ("estacao", "ESTM", "ghi", {})),
    (re.compile(r"^\w+\.ESTM[^.]*\.PNL\.TEMP$"), lambda m: ("estacao", "ESTM", "temp_modulo", {})),
    (re.compile(r"^\w+\.ESTM[^.]*\.AR\.TEMP$"), lambda m: ("estacao", "ESTM", "temp_ar", {})),
    (re.compile(r"^\w+\.ESTM[^.]*\.AR\.VEL$"), lambda m: ("estacao", "ESTM", "vento", {})),
    (re.compile(r"^\w+\.INV_(\d+)\.MEDIDAS\.P$"), lambda m: ("inversor", f"INV_{m.group(1)}", "p_ac", {"numero": int(m.group(1))})),
    (re.compile(r"^\w+\.INV_(\d+)\.MEDIDAS\.EPD$"), lambda m: ("inversor", f"INV_{m.group(1)}", "e_dia", {"numero": int(m.group(1))})),
    (re.compile(r"^\w+\.INV_(\d+)\.MEDIDAS\.Workstate$"), lambda m: ("inversor", f"INV_{m.group(1)}", "estado", {"numero": int(m.group(1))})),
    (re.compile(r"^\w+\.INV_(\d+)\.MEDIDAS\.STR\.I_PV(\d+)$"), lambda m: ("string", f"INV_{m.group(1)}.I_PV{m.group(2)}", "i_string", {"numero": int(m.group(2)), "inversor": f"INV_{m.group(1)}"})),
    (re.compile(r"^\w+\.TRK_(\d+)\.MEDIDAS\.POSAT$"), lambda m: ("tracker", f"TRK_{m.group(1)}", "angulo", {"numero": int(m.group(1))})),
    (re.compile(r"^\w+\.TRK_(\d+)\.MEDIDAS\.POSAL$"), lambda m: ("tracker", f"TRK_{m.group(1)}", "angulo_alvo", {"numero": int(m.group(1))})),
    (re.compile(r"^\w+\.TRK_(\d+)\.STATUS\.WORKSTATE$"), lambda m: ("tracker", f"TRK_{m.group(1)}", "estado", {"numero": int(m.group(1))})),
]
GRUPOS = {"fino": {"estacao", "inversor"}, "lento": {"tracker", "string"}}
PERIOD = {"fino": None, "lento": "15m"}


def classificar(pathname: str):
    for rx, f in _RX:
        m = rx.match(pathname)
        if m:
            return f(m)
    return None


def equipamentos_de(metadata: list[dict]) -> list[tuple[str, str, dict]]:
    vistos, out = set(), []
    for it in metadata:
        c = classificar(str(it.get("pathname") or ""))
        if c and (c[0], c[1]) not in vistos:
            vistos.add((c[0], c[1])); out.append((c[0], c[1], c[3]))
    return out


def pedacos_de_um_dia(ini: dt.datetime, fim: dt.datetime) -> list[tuple[dt.datetime, dt.datetime]]:
    """[ini, fim) em pedacos de ate 24 h — uma requisicao por pedaco e lote."""
    out, a = [], ini
    while a < fim:
        b = min(fim, a + dt.timedelta(hours=24))
        out.append((a, b))
        a = b
    return out


def lotear(pathnames: list[str], tamanho: int) -> list[list[str]]:
    return [pathnames[i:i + tamanho] for i in range(0, len(pathnames), tamanho)]


def ts_utc(texto: str, tz: str) -> dt.datetime:
    return dt.datetime.fromisoformat(texto).replace(tzinfo=ZoneInfo(tz)).astimezone(dt.timezone.utc)


class IngestorSunOp(Ingestor):
    def __init__(self, cfg, conn, usinas: list[UsinaRef], grupo: str = "fino", http=None):
        super().__init__(cfg, conn, usinas)
        self.grupo, self.http = grupo, http or requests.Session()
        self.fonte = "axis" if usinas and usinas[0].fonte == "axis" else "sunop"

    # Esquema de autenticacao do servico de DADOS da SunOp (/data/v2/*): 'Bearer API <token de API>'. 'Bearer <token>' puro
    # e 'JWT <token web>' levam 401 'Invalid credentials' — medido em 03/09/2026 (o token web e so para /api/*).
    # ── metadata em disco ────────────────────────────────────────────────────
    def metadata(self, usina: UsinaRef) -> list[dict]:
        cache = Path(self.cfg.cache_dir) / f"sunop_meta_{usina.codigo}.json"
        if cache.exists() and time.time() - cache.stat().st_mtime < 86400:
            return json.load(open(cache, encoding="utf-8"))
        r = self.http.get(f"{self.cfg.sunop_base}/data/v2/metadata", params={"plant": usina.fonte_ref, "size": 6000},
                          headers={"Authorization": f"Bearer API {self.cfg.sunop_token}"}, timeout=60)
        if r.status_code == 403:
            self.disjuntor.abrir("403 da borda no metadata")
            raise RuntimeError("403 da borda no metadata")
        r.raise_for_status()
        itens = r.json().get("data", [])
        cache.parent.mkdir(parents=True, exist_ok=True)
        json.dump(itens, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
        return itens

    def descobrir(self, usina: UsinaRef) -> None:
        eqs = equipamentos_de(self.metadata(usina))
        with self.conn.cursor() as cur:
            for tipo, codigo, atr in eqs:
                if tipo == "string":
                    continue
                cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte, atributos) VALUES (%s,%s,%s,%s) "
                            "ON CONFLICT (usina_id, tipo, codigo_fonte) DO NOTHING", (usina.id, tipo, codigo, json.dumps(atr)))
            for tipo, codigo, atr in eqs:
                if tipo != "string":
                    continue
                cur.execute("SELECT id FROM equipamento WHERE usina_id=%s AND tipo='inversor' AND codigo_fonte=%s", (usina.id, atr["inversor"]))
                pai = cur.fetchone()
                cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte, pai_id, atributos) VALUES (%s,'string',%s,%s,%s) "
                            "ON CONFLICT (usina_id, tipo, codigo_fonte) DO NOTHING", (usina.id, codigo, pai[0] if pai else None, json.dumps({"numero": atr["numero"]})))
        self.conn.commit()

    # ── busca ─────────────────────────────────────────────────────────────────
    def _pathnames(self, usina: UsinaRef) -> dict[str, tuple[int, str]]:
        """pathname -> (equipamento_id, medida) para o grupo deste ingestor."""
        with self.conn.cursor() as cur:
            cur.execute("SELECT tipo, codigo_fonte, id FROM equipamento WHERE usina_id=%s AND ativo", (usina.id,))
            ids = {(t, c): i for t, c, i in cur.fetchall()}
        out = {}
        for it in self.metadata(usina):
            p = str(it.get("pathname") or ""); c = classificar(p)
            if c and c[0] in GRUPOS[self.grupo] and (c[0], c[1]) in ids:
                out[p] = (ids[(c[0], c[1])], c[2])
        return out

    def _analog(self, pathnames: list[str], ini: str, fim: str, period: str | None) -> dict:
        params = {"fill_missing": "false", "source": "Historical", "start_time": ini, "end_time": fim, "use_plant_timezone": "true"}
        if period:
            params["period"] = period
        r = self.http.post(f"{self.cfg.sunop_base}/data/v2/analog_values", params=params, json={"pathnames": pathnames},
                           headers={"Authorization": f"Bearer API {self.cfg.sunop_token}"}, timeout=180)
        if r.status_code == 403:
            self.disjuntor.abrir(f"403 da borda: {r.text[:80]}")
            return {}
        if r.status_code != 200:
            return {}
        out: dict[str, list] = {}
        for rec in r.json() or []:
            v = rec.get("value")
            if isinstance(v, (int, float)):
                out.setdefault(rec["pathname"], []).append((rec["timestamp"], float(v)))
        return out

    def buscar(self, usina: UsinaRef, ini: dt.datetime, fim: dt.datetime) -> Busca:
        """Uma usina so — usado quando o ciclo conjunto nao se aplica (testes, reprocesso)."""
        return self._buscar_varias([usina], ini, fim)[usina.id]

    def _buscar_varias(self, usinas: list[UsinaRef], ini: dt.datetime, fim: dt.datetime) -> dict[int, Busca]:
        mapa = {u.id: self._pathnames(u) for u in usinas}
        todos = [p for m in mapa.values() for p in m]
        tz0 = usinas[0].tz
        bruto: dict[str, list] = {}; n = 0
        # janela em pedacos de ate 24 h: 600 pathnames x 3 dias a 5 min numa chamada so estourava o timeout (primeira subida, 03/09)
        for p_ini, p_fim in pedacos_de_um_dia(ini, fim):
            ini_l = p_ini.astimezone(ZoneInfo(tz0)).strftime("%Y-%m-%dT%H:%M:%S"); fim_l = p_fim.astimezone(ZoneInfo(tz0)).strftime("%Y-%m-%dT%H:%M:%S")
            for lote in lotear(todos, self.cfg.lote_pathnames):
                hoje = dt.datetime.now(dt.timezone.utc).date()
                if self._db.requisicoes_hoje(self.conn, self.fonte, hoje) + n >= self.cfg.teto_sunop_dia:
                    self.disjuntor.abrir("teto diario de requisicoes")
                    break
                for path, pts in self._analog(lote, ini_l, fim_l, PERIOD[self.grupo]).items():
                    bruto.setdefault(path, []).extend(pts)
                n += 1
        passo = 15 if PERIOD[self.grupo] else 5
        out = {}
        for u in usinas:
            ls = [(eid, med, ts_utc(t, u.tz), v) for p, (eid, med) in mapa[u.id].items() for t, v in bruto.get(p, []) if valor_valido(med, v)]
            out[u.id] = Busca(leituras=ls, n_requisicoes=n if u is usinas[0] else 0)
        return out

    def ciclo(self, agora: dt.datetime | None = None, reconciliar: bool = False) -> list[int]:
        """Sobrescreve o ciclo base: UMA baixa para todas as usinas do grupo (lotes atravessam usinas),
        janela comum = a mais antiga entre as marcas d'agua. Fora da janela solar, nao busca."""
        agora = agora or dt.datetime.now(dt.timezone.utc)
        ids = []
        ativas = [u for u in self.usinas if tempo.dentro_janela_solar(agora, u.tz, self.cfg.janela_solar)]
        # Fora da janela solar NAO se registra ingest_run: na noite de 03/09 cada ciclo gravava uma linha 'falha' com
        # erro "fora da janela solar" e o /healthz passou a noite em "sunop: falha ha 0 min" (503) sem nada errado.
        if not ativas:
            return ids
        if self.disjuntor.aberto():
            return ids + [self._db.registrar_ingest_run(self.conn, fonte=self.fonte, usina_id=u.id, ini=agora, fim=agora, status="falha", cobertura=0.0, erro=f"disjuntor aberto: {self.disjuntor.motivo}") for u in ativas]
        janelas = [tempo.janela(agora, self._db.marca_dagua(self.conn, u.id), self.cfg.sobreposicao_min, reconciliar=reconciliar) for u in ativas]
        ini, fim = min(j[0] for j in janelas), agora
        t0 = time.time()
        try:
            buscas = self._buscar_varias(ativas, ini, fim)
        except Exception as e:                       # noqa: BLE001
            return ids + [self._db.registrar_ingest_run(self.conn, fonte=self.fonte, usina_id=u.id, ini=ini, fim=fim, status="falha", cobertura=0.0, duracao_s=time.time() - t0, erro=f"{type(e).__name__}: {e}"[:400]) for u in ativas]
        for u in ativas:
            b = buscas[u.id]
            if not b.leituras:
                ids.append(self._db.registrar_ingest_run(self.conn, fonte=self.fonte, usina_id=u.id, ini=ini, fim=fim, status="falha", n_requisicoes=b.n_requisicoes, cobertura=0.0, erro="fonte devolveu vazio")); continue
            n = self._db.upsert_leituras(self.conn, b.leituras)
            # MESMA funcao do laco padrao, nao uma copia da regra: quando eram duas, so uma foi
            # corrigida e as fontes passaram a medir saude de jeitos diferentes sem ninguem ver.
            status, cob = avaliar(b.leituras, fim, self.atraso_ok_min)
            ids.append(self._db.registrar_ingest_run(self.conn, fonte=self.fonte, usina_id=u.id, ini=ini, fim=fim, status=status, n_linhas=n, n_requisicoes=b.n_requisicoes, duracao_s=time.time() - t0, cobertura=cob))
        return ids
