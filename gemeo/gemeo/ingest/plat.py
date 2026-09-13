# gemeo/gemeo/ingest/plat.py
"""Fonte `plat`: trackers das usinas da API PV (as tres da 2C) pela PV Plataforma — apiplataforma.pvoperation.com.

Por que uma fonte a parte: a API PV Operation (fonte apipv) nega os trackers para a conta oem@; a PV Plataforma, do mesmo
fornecedor, entrega — com OUTRO token (x-auth-token-update), colado a mao no gemeo.env (`PV_PLAT_TOKEN_OEM`), que vale 7 dias
(Levi, 12/09/2026: "Segue token separado"). E a mesma API que a plataforma de performance ja usa para a regua de trackers.

O que a API da (sondado ao vivo em 12/09/2026, Araputanga 18771898):
- `/v2/usinas/trackers?idusina=` — o estado: um item por INVERSOR (`idinversor` = o mesmo idefinversor da API PV, que e o
  `codigo_fonte` do inversor no cadastro) com a lista dos SEUS trackers (`nome` TRK1.., `idmodbus`, `ultimaleitura.posAg/posAl`).
  O de-para tracker -> inversor vem dai, pronto; a BD_Trackers nao tem as 2C. Araputanga 59, Sete Lagoas 59, Tupi 100.
- `/v2/usinas/trackerschart?idusina=&dataleitura=dd/mm/aaaa` — o angulo minuto a minuto do dia (1310 pontos/tracker em 10/09).
  Carimbos "Fri, 11 Sep 2026 12:50:00 GMT": o GMT e sufixo falso, a hora e de BRASILIA para toda usina (a mediana da frota
  da Araputanga, MT, cruza 0 grau as 12:50 — o meio-dia solar de lon -58,3 em hora de Brasilia; na Tupi, SP, as 12:23).
  Formato ISO no parametro devolve erro U065; mm/dd devolve vazio.
Guarda-se UM angulo por bloco de 15 min (a grade do modelo), como o p_ac da fonte apipv; o alvo (`posAl`) so existe no estado,
e entra como o instante do ciclo. A marca d'agua e a dos proprios trackers (`tipos`): a usina e dividida com a fonte apipv."""
from __future__ import annotations
import base64
import datetime as dt
import json

import requests

from gemeo.core.modelos import UsinaRef
from gemeo.ingest.apipv import FUSO_API
from gemeo.ingest.base import Busca, Ingestor

PLAT_BASE = "https://apiplataforma.pvoperation.com"
BLOCO_MIN = 15
_FORMATOS = ("%a, %d %b %Y %H:%M:%S GMT", "%Y-%m-%d %H:%M:%S")


def cabecalhos(token: str) -> dict:
    """Os mesmos que a plataforma de performance manda (o servico confere origin/referer do site)."""
    return {"accept": "application/json", "origin": "https://plataforma.pvoperation.com", "referer": "https://plataforma.pvoperation.com/",
            "user-agent": "Mozilla/5.0", "x-auth-token-update": token}


def ts_utc(texto) -> dt.datetime:
    """'Fri, 11 Sep 2026 12:50:00 GMT' (grafico) ou '2026-09-11 13:16:00' (estado): hora de Brasilia -> UTC."""
    s = str(texto or "").strip()
    for f in _FORMATOS:
        try:
            naive = dt.datetime.strptime(s, f)
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"carimbo da PV Plataforma fora do formato: {s!r}")
    return naive.replace(tzinfo=FUSO_API).astimezone(dt.timezone.utc)


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def trackers_do_estado(payload) -> list[tuple[str, str, int | None, int | None]]:
    """(nome do tracker, idinversor, idmodbus, id na plataforma) para cada tracker de cada inversor."""
    out = []
    if not isinstance(payload, dict):
        return out
    for item in payload.get("dados") or []:
        if not isinstance(item, dict):
            continue
        idinv = str(item.get("idinversor") or "").strip()
        for t in item.get("trackers") or []:
            nome = str((t or {}).get("nome") or "").strip()
            if nome:
                out.append((nome, idinv, _int(t.get("idmodbus")), _int(t.get("id"))))
    return out


def _bloco(ts: dt.datetime, minutos: int) -> dt.datetime:
    return ts.replace(minute=ts.minute - ts.minute % minutos, second=0, microsecond=0)


def leituras_grafico(payload, mapa_trk: dict[str, int], ini: dt.datetime, fim: dt.datetime) -> list[tuple]:
    """Um angulo por tracker por bloco de 15 min, dentro de (ini, fim]. 1 ponto/min x 59 trackers seriam 85 mil linhas/dia
    so na Araputanga — o modelo trabalha em blocos de 15 min. Tracker fora do cadastro e ponto sem numero ficam fora."""
    out: list[tuple] = []
    g = payload.get("grafico") if isinstance(payload, dict) else None
    if not isinstance(g, dict):
        return out
    for nome, pts in g.items():
        eid = mapa_trk.get(str(nome))
        if eid is None or not isinstance(pts, list):
            continue
        serie = []
        for p in pts:
            try:
                ts, v = ts_utc(p["x"]), p.get("y")
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            if isinstance(v, (int, float)) and not isinstance(v, bool) and ini < ts <= fim:
                serie.append((ts, float(v)))
        vistos: set = set()
        for ts, v in sorted(serie):
            b = _bloco(ts, BLOCO_MIN)
            if b in vistos:
                continue
            vistos.add(b)
            out.append((eid, "angulo", ts, v))
    return out


def leituras_estado(payload, mapa_trk: dict[str, int], ini: dt.datetime, fim: dt.datetime) -> list[tuple]:
    """Angulo, alvo e alarme de comunicacao do instante (`ultimaleitura`), carimbados com o `tsleitura` do inversor: e o
    'agora' dos trackers, o unico lugar de onde vem o alvo, e o que separa um tracker MUDO de um desalinhado — a Araputanga
    TRK5 (13/09/2026) vinha 0,0 grau fixo no grafico com aComm=1: o zero nao e angulo, e um sensor sem comunicacao."""
    out: list[tuple] = []
    if not isinstance(payload, dict):
        return out
    for item in payload.get("dados") or []:
        if not isinstance(item, dict):
            continue
        try:
            ts = ts_utc((item.get("dadosGerais") or {}).get("tsleitura") or payload.get("ultimaLeitura"))
        except ValueError:
            continue
        if not (ini < ts <= fim):
            continue
        for t in item.get("trackers") or []:
            eid = mapa_trk.get(str((t or {}).get("nome") or ""))
            if eid is None:
                continue
            ul = t.get("ultimaleitura") or {}
            for medida, chave in (("angulo", "posAg"), ("angulo_alvo", "posAl"), ("alarme_com", "aComm")):
                v = ul.get(chave)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    out.append((eid, medida, ts, float(v)))
    return out


def dias_da_janela(ini: dt.datetime, fim: dt.datetime) -> list[dt.date]:
    """Dias de Brasilia que a janela toca — um grafico por dia."""
    d, ultimo = ini.astimezone(FUSO_API).date(), fim.astimezone(FUSO_API).date()
    out = []
    while d <= ultimo:
        out.append(d)
        d += dt.timedelta(days=1)
    return out


def validade_token(token: str) -> dt.datetime | None:
    """`exp` do JWT da PV Plataforma (7 dias a partir do login), em UTC; None para token opaco."""
    try:
        pl = token.split(".")[1]
        pl += "=" * (-len(pl) % 4)
        exp = json.loads(base64.urlsafe_b64decode(pl)).get("exp")
        return dt.datetime.fromtimestamp(float(exp), tz=dt.timezone.utc) if exp else None
    except Exception:                                      # noqa: BLE001 — token opaco ou fora do formato
        return None


class IngestorPlatTrackers(Ingestor):
    fonte = "plat"
    tipos = ("tracker",)          # marca d'agua so dos trackers: a usina e a mesma da fonte apipv (inversores a cada 15 min)

    def __init__(self, cfg, conn, usinas: list[UsinaRef], http=None):
        super().__init__(cfg, conn, usinas)
        self.http = http or requests.Session()

    def _get(self, caminho: str, params: dict, timeout: int) -> dict:
        token = (getattr(self.cfg, "pv_plat_token_oem", "") or "").strip()
        if not token:
            raise RuntimeError("falta PV_PLAT_TOKEN_OEM no gemeo.env (token da PV Plataforma, conta oem@)")
        base = (getattr(self.cfg, "plat_base", "") or PLAT_BASE).rstrip("/")
        r = self.http.get(f"{base}{caminho}", headers=cabecalhos(token), params=params, timeout=timeout)
        if r.status_code in (401, 403):
            # o token e colado a mao e vence em 7 dias: o ciclo tem de dizer ONDE renovar, e parar de bater ate la
            self.disjuntor.abrir(f"HTTP {r.status_code} em {caminho}: token recusado")
            raise RuntimeError(f"PV Plataforma recusou o token (HTTP {r.status_code}): renovar PV_PLAT_TOKEN_OEM no gemeo.env "
                               "(login na plataforma.pvoperation.com com a conta oem@; vale 7 dias)")
        if r.status_code == 429 or r.status_code >= 500:
            self.disjuntor.abrir(f"HTTP {r.status_code} em {caminho}")
            raise RuntimeError(f"PV Plataforma {caminho}: HTTP {r.status_code}")
        j = r.json()
        if not isinstance(j, dict) or j.get("success") is False:
            raise RuntimeError(f"PV Plataforma {caminho}: {json.dumps(j, ensure_ascii=False)[:160]}")
        return j

    def _estado(self, usina: UsinaRef) -> dict:
        return self._get("/v2/usinas/trackers", {"idusina": usina.fonte_ref}, timeout=60)

    def _gravar_trackers(self, usina: UsinaRef, estado: dict) -> None:
        """Trackers do estado viram `equipamento` com o inversor da API como pai. Idempotente; um tracker que nasceu sem pai
        (a descoberta da fonte apipv corre em outra thread) ganha o pai na passada seguinte."""
        trks = trackers_do_estado(estado)
        if not trks:
            return

        def _grava():
            with self.conn.cursor() as cur:
                cur.execute("SELECT codigo_fonte, id FROM equipamento WHERE usina_id=%s AND tipo='inversor'", (usina.id,))
                inv = dict(cur.fetchall())
                for nome, idinv, modbus, pid in trks:
                    pai = inv.get(idinv)
                    cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte, nome_exibicao, pai_id, atributos) VALUES (%s,'tracker',%s,%s,%s,%s) "
                                "ON CONFLICT (usina_id, tipo, codigo_fonte) DO NOTHING",
                                (usina.id, nome, nome, pai, json.dumps({"numero": modbus, "plat_id": pid})))
                    if pai is not None:
                        cur.execute("UPDATE equipamento SET pai_id=%s WHERE usina_id=%s AND tipo='tracker' AND codigo_fonte=%s AND pai_id IS NULL",
                                    (pai, usina.id, nome))
            self.conn.commit()
        self._db.com_retentativa_de_lock(self.conn, _grava)

    def _mapa(self, usina: UsinaRef) -> dict[str, int]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT codigo_fonte, id FROM equipamento WHERE usina_id=%s AND tipo='tracker' AND ativo", (usina.id,))
            return dict(cur.fetchall())

    def descobrir(self, usina: UsinaRef) -> None:
        self._gravar_trackers(usina, self._estado(usina))

    def buscar(self, usina: UsinaRef, ini: dt.datetime, fim: dt.datetime) -> Busca:
        estado = self._estado(usina)
        n = 1
        self._gravar_trackers(usina, estado)               # tracker novo ou pai que faltava entram aqui, sem esperar reinicio
        mapa = self._mapa(usina)
        leituras = leituras_estado(estado, mapa, ini, fim)
        for dia in dias_da_janela(ini, fim):
            n += 1
            g = self._get("/v2/usinas/trackerschart", {"idusina": usina.fonte_ref, "dataleitura": dia.strftime("%d/%m/%Y")}, timeout=120)
            leituras += leituras_grafico(g, mapa, ini, fim)
        minutos = max(1.0, (fim - ini).total_seconds() / 60)
        return Busca(leituras=leituras, n_requisicoes=n, esperadas=int(len(mapa) * (minutos // BLOCO_MIN)))
