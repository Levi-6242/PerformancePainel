# gemeo/gemeo/ingest/apipv.py
"""Fonte API PV Operation, conta oem@: Araputanga, Sete Lagoa(s) e Tupi Paulista da 2C — as tres que essa conta enxerga
(Levi, 11/09/2026: "comece com as usinas da 2C que estao na API PV"). Tres fatos MEDIDOS em 11/09 que o codigo assume:

- `tsleitura_new` vem em horario de BRASILIA para toda usina, inclusive a Araputanga (MT, UTC-4): as 19:26 de Brasilia a
  ultima leitura dela era 19:20 e a da Tupi (SP) 19:22 — se fosse hora local de MT, a Araputanga estaria em 18:2x.
  Fuso fixo FUSO_API na conversao, independente do tz da usina (que segue valendo para o dia local e a janela solar);
- `day_inverter`/`day_meteo` so entregam o DIA ATUAL (1 leitura/min, ~7 s por usina); dia passado e `custom_query`
  (inverter ~146 s por usina de 10 inversores, meteo ~4 s) — so vale a pena quando a janela cobre o dia de verdade;
- a estacao mente por chave: na Tupi piraPOA1 = 4921 W/m2 e piraGHI1 = '-' o dia todo; na Araputanga IrGHI = 41 milhoes.
  A ordem de campos e a do coletor (`coletar_pvoperation._POA_FIELDS/_GHI_FIELDS`) e |valor| >= 2000 W/m2 nao e medida.

A conta oem@ nao devolve nome de inversor e `plant_devices` e negado: o nome de exibicao vem do de-para
`[usinas.detalhe.<codigo>.inversores]` do config (idefinversor -> "Inversor X.Y"), fechado POR VALOR contra o
BD_Performance (Tupi 20/20 em 4 dias, Araputanga 10/10, Sete Lagoa 10/10)."""
from __future__ import annotations
import base64
import datetime as dt
import json
import re
import time
from zoneinfo import ZoneInfo

import requests

from gemeo.core.modelos import UsinaRef
from gemeo.ingest.base import Busca, Ingestor, valor_valido

FUSO_API = ZoneInfo("America/Sao_Paulo")
CAMPOS_POA = ("IrPOA", "Ir", "Ir1", "piraPOA1")
CAMPOS_GHI = ("piraGHI1", "IrGHI", "piraGHI2", "IrGHITotal")
CAMPOS_ESTACAO = {"temp_modulo": "tempMod", "temp_ar": "tempAmb", "vento": "velVento"}
TETO_IRRADIANCIA = 2000.0                 # acima disso e codigo/lixo do sensor, nao sol (IrGHI = 41 milhoes na Araputanga)
# Cadencia gravada por medida (minutos). A API entrega 1 leitura/min: 40 inversores x 2 medidas seriam 115 mil linhas/dia
# so nas tres usinas. O modelo trabalha em blocos de 15 min e o PostgreSQL do Thopen entrega 5 min — mesma cadencia aqui
# para o inversor; corrente de string a 15 min como no pg.GROSSAS; a estacao fica em 1 min (e a fisica do esperado).
BLOCO_MIN = {"p_ac": 5, "e_dia": 5, "i_string": 15}
MINIMO_DIA_PASSADO = dt.timedelta(hours=2)   # menos que isso de um dia passado nao paga os ~146 s do custom_query
_STR = re.compile(r"^Ipv(\d+)$")


def _num(v) -> float | None:
    """'-' e None nao sao numero (Ipv2 = '-' na Araputanga, piraGHI1 = '-' na Tupi); bool tambem nao."""
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def coord(texto) -> float | None:
    """/plants escreve '-15,479992' (virgula) e ' -44.203342\\xa0 ' (espaco duro) — 11/09/2026."""
    if texto is None:
        return None
    s = str(texto).replace("\xa0", " ").strip().replace(",", ".")
    return _num(s) if s else None


def ts_utc(texto: str) -> dt.datetime:
    return dt.datetime.fromisoformat(texto).replace(tzinfo=FUSO_API).astimezone(dt.timezone.utc)


def conteudo(rec: dict) -> dict:
    c = rec.get("conteudojson")
    if isinstance(c, str):
        try:
            return json.loads(c)
        except ValueError:
            return {}
    return c or {}


def irradiancia(cj: dict, campos: tuple[str, ...]) -> float | None:
    """Primeiro campo numerico com |valor| < TETO — a ordem e a do coletor, que ja levou os tombos (GHI de julho/2026)."""
    for c in campos:
        v = _num(cj.get(c))
        if v is not None and abs(v) < TETO_IRRADIANCIA:
            return v
    return None


def _bloco(ts: dt.datetime, minutos: int) -> dt.datetime:
    return ts.replace(minute=(ts.minute // minutos) * minutos, second=0, microsecond=0)


def _repetida(vistos: set | None, eid: int, medida: str, ts: dt.datetime) -> bool:
    """True quando a medida tem cadencia propria e o bloco dela ja foi gravado nesta busca (fica a primeira amostra)."""
    if vistos is None or medida not in BLOCO_MIN:
        return False
    chave = (eid, medida, _bloco(ts, BLOCO_MIN[medida]))
    if chave in vistos:
        return True
    vistos.add(chave)
    return False


def _na_janela(ts: dt.datetime, ini: dt.datetime, fim: dt.datetime) -> bool:
    return ini < ts <= fim


def leituras_inversor(recs: list[dict], mapa_eq: dict, ini: dt.datetime, fim: dt.datetime, vistos: set | None) -> list[tuple]:
    """(equipamento_id, medida, ts UTC, valor) dos registros de day_inverter/custom_query inverter dentro de (ini, fim].
    Pac em kW (teto AC de 250 kW medido nos 40 inversores), Eday em kWh, Ipv<n> em A. Status da API nao vira medida."""
    out: list[tuple] = []
    for r in sorted(recs, key=lambda r: str(r.get("tsleitura_new") or "")):
        idef, texto = r.get("idefinversor"), r.get("tsleitura_new")
        if idef is None or not texto:
            continue
        ts = ts_utc(str(texto))
        if not _na_janela(ts, ini, fim):
            continue
        cj = conteudo(r)
        eid = mapa_eq.get(("inversor", str(idef)))
        if eid is not None:
            for chave, medida in (("Pac", "p_ac"), ("Eday", "e_dia")):
                v = _num(cj.get(chave))
                if v is not None and not _repetida(vistos, eid, medida, ts):
                    out.append((eid, medida, ts, v))
        for chave, val in cj.items():
            m = _STR.match(chave)
            if not m:
                continue
            sid = mapa_eq.get(("string", f"{idef}.Ipv{m.group(1)}"))
            v = _num(val)
            if sid is not None and v is not None and not _repetida(vistos, sid, "i_string", ts):
                out.append((sid, "i_string", ts, v))
    return out


def leituras_estacao(recs: list[dict], estacao_id: int | None, ini: dt.datetime, fim: dt.datetime) -> list[tuple]:
    if estacao_id is None:
        return []
    out: list[tuple] = []
    for r in recs:
        texto = r.get("tsleitura_new")
        if not texto:
            continue
        ts = ts_utc(str(texto))
        if not _na_janela(ts, ini, fim):
            continue
        cj = conteudo(r)
        valores = {"poa": irradiancia(cj, CAMPOS_POA), "ghi": irradiancia(cj, CAMPOS_GHI)}
        valores.update({medida: _num(cj.get(chave)) for medida, chave in CAMPOS_ESTACAO.items()})
        out.extend((estacao_id, medida, ts, v) for medida, v in valores.items() if valor_valido(medida, v))
    return out


def dias_passados(ini: dt.datetime, fim: dt.datetime, hoje: dt.date) -> list[dt.date]:
    """Dias de Brasilia anteriores a `hoje` que a janela (ini, fim] cobre por pelo menos MINIMO_DIA_PASSADO. A marca d'agua
    logo depois da meia-noite arrasta 30 min de ontem para a janela — nao vale 146 s de custom_query por 17 min de noite;
    o primeiro ciclo (3 dias) e a reconciliacao (24 h) cobrem o dia inteiro e entram."""
    out = []
    d = ini.astimezone(FUSO_API).date()
    while d < hoje:
        d0 = dt.datetime.combine(d, dt.time.min, tzinfo=FUSO_API)
        d1 = d0 + dt.timedelta(days=1)
        if min(fim, d1) - max(ini, d0) >= MINIMO_DIA_PASSADO:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


class IngestorAPIPV(Ingestor):
    fonte = "apipv"

    def __init__(self, cfg, conn, usinas: list[UsinaRef], http=None):
        super().__init__(cfg, conn, usinas)
        self.http = http or requests.Session()
        self._tok, self._tok_exp = "", 0.0
        self._hoje_cache: dict[int, tuple[float, list, list]] = {}
        self._plantas_cache: tuple[float, list] = (0.0, [])

    # ── autenticacao ──────────────────────────────────────────────────────────
    def _token(self) -> str:
        if self._tok and time.time() < self._tok_exp:
            return self._tok
        usuario, senha = getattr(self.cfg, "pv_oem_usuario", ""), getattr(self.cfg, "pv_oem_senha", "")
        if not (usuario and senha):
            raise RuntimeError("faltam PV_OEM_USERNAME e PV_OEM_PASSWORD no gemeo.env (conta oem@ da API PV Operation)")
        r = self.http.post(f"{self.cfg.apipv_base}/authenticate", json={"username": usuario, "password": senha}, timeout=30)
        j = r.json() if r.status_code == 200 else {}
        tok = j.get("token") if isinstance(j, dict) else None
        if not tok:
            raise RuntimeError(f"API PV /authenticate falhou (HTTP {r.status_code})")
        exp = time.time() + 2700                          # 45 min quando o JWT nao diz
        try:
            pl = tok.split(".")[1]
            pl += "=" * (-len(pl) % 4)
            jexp = json.loads(base64.urlsafe_b64decode(pl)).get("exp")
            if jexp:
                exp = float(jexp) - 60
        except Exception:                                  # noqa: BLE001 — token opaco: vale o padrao
            pass
        self._tok, self._tok_exp = tok, exp
        return tok

    def _post(self, caminho: str, corpo: dict, timeout: int) -> list:
        r = None
        for tentativa in (1, 2):
            r = self.http.post(f"{self.cfg.apipv_base}/{caminho}", json=corpo, headers={"x-access-token": self._token()}, timeout=timeout)
            if r.status_code == 401 and tentativa == 1:   # token venceu no meio: renova uma vez
                self._tok = ""
                continue
            break
        if r.status_code == 429 or r.status_code >= 500:
            self.disjuntor.abrir(f"HTTP {r.status_code} em {caminho}")
            raise RuntimeError(f"API PV {caminho}: HTTP {r.status_code}")
        j = r.json()
        # erro vem como DICT ({"error": "Invalid id"} para id de outra conta) — iterar as chaves como registros ja derrubou
        # rota da plataforma (Tucano/SEMP, 06/08). Aqui e excecao: o ciclo registra 'falha' com o texto.
        if isinstance(j, dict):
            raise RuntimeError(f"API PV {caminho}: {json.dumps(j, ensure_ascii=False)[:160]}")
        return j if isinstance(j, list) else []

    # ── o dia de hoje, baixado uma vez por ciclo ──────────────────────────────
    def _hoje(self, usina: UsinaRef) -> tuple[list, list]:
        """day_inverter + day_meteo de hoje. A descoberta e a busca do mesmo ciclo dividem a baixa (Tupi: 23 mil registros)."""
        agora = time.time()
        c = self._hoje_cache.get(usina.id)
        if c and agora - c[0] < 60:
            return c[1], c[2]
        pid = int(usina.fonte_ref)
        inv = self._post("day_inverter", {"id": pid}, timeout=90)
        met = self._post("day_meteo", {"id": pid}, timeout=60)
        self._hoje_cache[usina.id] = (agora, inv, met)
        return inv, met

    def _plantas(self) -> list[dict]:
        if time.time() - self._plantas_cache[0] < 3600:
            return self._plantas_cache[1]
        r = self.http.get(f"{self.cfg.apipv_base}/plants", headers={"x-access-token": self._token()}, timeout=30)
        j = r.json() if r.status_code == 200 else []
        pl = j if isinstance(j, list) else []
        self._plantas_cache = (time.time(), pl)
        return pl

    def _placa_e_coordenadas(self, usina: UsinaRef) -> None:
        """lat/lon e kWp de /plants — so preenche o que esta vazio: o cadastro (Info Geral) continua mandando na placa e
        e o unico lugar de onde vem lat/lon destas tres (a Info Geral so tem o Estado). Falha aqui e aviso, nao erro."""
        try:
            p = next((p for p in self._plantas() if str(p.get("id")) == str(usina.fonte_ref)), None)
            if not p:
                return
            lat, lon, kwp = coord(p.get("latitude")), coord(p.get("longitude")), _num(p.get("capacidade"))

            def _grava():
                with self.conn.cursor() as cur:
                    cur.execute("UPDATE usina SET lat=coalesce(lat, %s), lon=coalesce(lon, %s), kwp_dc=coalesce(kwp_dc, %s) WHERE id=%s",
                                (lat, lon, kwp, usina.id))
                self.conn.commit()
            self._db.com_retentativa_de_lock(self.conn, _grava)
        except Exception as e:                            # noqa: BLE001 — coordenada nao pode parar a descoberta
            self.conn.rollback()
            print(f"[apipv] {usina.codigo}: placa/coordenadas nao vieram ({e})")

    # ── descoberta ────────────────────────────────────────────────────────────
    def descobrir(self, usina: UsinaRef) -> None:
        """Inversores que reportaram hoje viram `equipamento` com o nome do de-para do config; as strings nascem das chaves
        Ipv<n> dos registros; a estacao e uma so por usina ('ESTM', como na SunOp). Idempotente."""
        self._placa_e_coordenadas(usina)
        inv, met = self._hoje(usina)
        nomes = (getattr(self.cfg, "usinas_detalhe", {}).get(usina.codigo, {}) or {}).get("inversores") or {}
        chaves: dict[int, set[str]] = {}
        for r in inv:
            idef = r.get("idefinversor")
            if idef is None:
                continue
            chaves.setdefault(int(idef), set()).update(k for k in conteudo(r) if _STR.match(k))

        def _grava():
            with self.conn.cursor() as cur:
                if met:
                    cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte, atributos) VALUES (%s,'estacao','ESTM','{}') "
                                "ON CONFLICT (usina_id, tipo, codigo_fonte) DO NOTHING", (usina.id,))
                for n, idef in enumerate(sorted(chaves), 1):      # ids sequenciais na API = ordem 1.1..1.10, 2.1..2.10 do cadastro
                    nome = nomes.get(str(idef))
                    cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte, nome_exibicao, atributos) VALUES (%s,'inversor',%s,%s,%s) "
                                "ON CONFLICT (usina_id, tipo, codigo_fonte) DO NOTHING", (usina.id, str(idef), nome, json.dumps({"numero": n})))
                    if nome:                                       # de-para que entrou no config depois da primeira descoberta
                        cur.execute("UPDATE equipamento SET nome_exibicao=%s WHERE usina_id=%s AND tipo='inversor' AND codigo_fonte=%s "
                                    "AND (nome_exibicao IS NULL OR nome_exibicao='')", (nome, usina.id, str(idef)))
                    cur.execute("SELECT id FROM equipamento WHERE usina_id=%s AND tipo='inversor' AND codigo_fonte=%s", (usina.id, str(idef)))
                    inv_id = cur.fetchone()[0]
                    for chave in sorted(chaves[idef], key=lambda k: int(_STR.match(k).group(1))):
                        num = int(_STR.match(chave).group(1))
                        cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte, pai_id, atributos) VALUES (%s,'string',%s,%s,%s) "
                                    "ON CONFLICT (usina_id, tipo, codigo_fonte) DO NOTHING",
                                    (usina.id, f"{idef}.Ipv{num}", inv_id, json.dumps({"numero": num})))
            self.conn.commit()
        # o primeiro INSERT da vida desta fonte levou "database is locked" na largada de 11/09 (quatro threads no mesmo arquivo)
        self._db.com_retentativa_de_lock(self.conn, _grava)

    # ── busca ─────────────────────────────────────────────────────────────────
    def _mapa(self, usina: UsinaRef) -> dict:
        with self.conn.cursor() as cur:
            cur.execute("SELECT tipo, codigo_fonte, id FROM equipamento WHERE usina_id=%s AND ativo", (usina.id,))
            return {(t, c): i for t, c, i in cur.fetchall()}

    def buscar(self, usina: UsinaRef, ini: dt.datetime, fim: dt.datetime) -> Busca:
        mapa = self._mapa(usina)
        est = mapa.get(("estacao", "ESTM"))
        vistos: set = set()
        inv, met = self._hoje(usina)
        n = 2
        leituras = leituras_inversor(inv, mapa, ini, fim, vistos) + leituras_estacao(met, est, ini, fim)
        pid = int(usina.fonte_ref)
        for dia in dias_passados(ini, fim, fim.astimezone(FUSO_API).date()):
            for tipo in ("inverter", "meteo"):
                n += 1
                try:
                    recs = self._post("custom_query", {"id": pid, "data_type": tipo, "period": dia.strftime("%Y-%m"), "day": dia.day}, timeout=300)
                except Exception as e:                    # noqa: BLE001 — dia passado que nao veio fica para a reconciliacao
                    print(f"[apipv] {usina.codigo} {dia} {tipo}: {e}")
                    continue
                leituras += leituras_inversor(recs, mapa, ini, fim, vistos) if tipo == "inverter" else leituras_estacao(recs, est, ini, fim)
        n_inv = sum(1 for t, _ in mapa if t == "inversor")
        n_str = sum(1 for t, _ in mapa if t == "string")
        return Busca(leituras=leituras, n_requisicoes=n)
