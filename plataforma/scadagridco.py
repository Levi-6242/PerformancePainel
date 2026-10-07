# -*- coding: utf-8 -*-
"""scadaGridco — o supervisório da Automação Grid Co. como fonte de strings (06/10/2026).

Levi: "OS para tempo real e histórico das UFVs da Green Yellow", com as usinas "separe green yellow e sal energia",
"igual às outras fontes" e histórico "só até 45 dias" (é o que a API guarda). Documento da Automação: "API do
scadaGridco — como puxar os dados". Só GET, cabeçalho `X-API-Key`, JSON; sem token ou com token errado ela responde
302 para o login.

Duas famílias, uma por cliente:
- **GreenYellow** chega por gateway MQTT: `/api/mqtt/<usina>` (último pacote de cada inversor) e `/api/telemetria`
  (histórico, ~1 registro por minuto por inversor). Ponto de string no gateway antigo `string_current_NN`, no novo
  `string_N_current`.
- **Sal Energia** é Modbus: `/api/inversores/<usina>` (leitura atual) e `/api/dados/string` (histórico de 5 min, uma
  linha por string). Em 06/10/2026 as cinco estavam com `read_error: TimeoutError` desde pelo menos 17/09 — o
  supervisório não lê os inversores, e a usina aparece sem comunicação, que é o que ela está para ele. O nome dos campos
  Modbus foi conferido na Boa Esperança do Sul, Modbus e lendo (`string_NN_i`, `active_power_w`, `daily_energy_kwh`).

Regras da Automação que este módulo segura: uma chamada por vez (o mesmo servidor opera as usinas, lendo relés e
inversores em tempo real — `_LOCK`), busca incremental (`apos_ts`), `communication_fault` 192 = leitura boa, nulo não é
zero e lacuna é sem comunicação. `data_hora` é a hora local das usinas (UTC−3, o Nordeste não tem horário de verão) e
`ts` é epoch. O token mora no tokens.txt (`SCADAGRIDCO_URL`, `SCADAGRIDCO_TOKEN`), nunca no código.

Puro onde dá (leitura dos pacotes, curva, de-para): a rede entra só por `get()`.
"""
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

TZ = timezone(timedelta(hours=-3))
COM_OK = 192                     # communication_fault da leitura boa (28 = ruim)
TIMEOUT_S = 60
LIMITE = 5000                    # registros por página (a doc pede 5.000 a 20.000)

# ── Usinas e de-para dos inversores ─────────────────────────────────────────────────────────────────────────────────
# id = a chave da usina no scadaGridco; usina = o nome do cadastro (aba Equipamentos/Info Geral do BD_Performance).
# `inversores` = {equipamento do scadaGridco: inversor do cadastro}. Na GreenYellow ele foi fechado POR VALOR, a energia do
# dia de cada equipamento contra o kWh diário da aba de 27 a 30/09/2026: na Irecê 2 a ordem NÃO é a do cadastro (o 4 é
# o Inversor 1.8, o 7 é o 1.4); o 7 bateu em 3 dos 4 dias ao centésimo, e no 29/09 o contador dele amanheceu com o
# valor da véspera. A Demerval Lobão tem só a UG 01 no scadaGridco (12 de 20 inversores, 3.246 de 5.410 kWp): o 1 a 12
# batem com o Inversor 1.1 a 1.12, e a UG 02 fica fora da conta da usina (como a União na 2C).
# Sal Energia: `None` = pela ORDEM do cadastro (slave 1 = o 1º inversor). PROVISÓRIO: sem uma leitura sequer não há
# como fechar por valor — confirmar quando o supervisório voltar a ler os inversores.
FONTES = {
    "greenyellow": {
        "rotulo": "GreenYellow",
        "via": "mqtt",
        "usinas": [
            {"id": "dermeval_lobao", "usina": "Demerval Lobao",
             "inversores": {str(i): f"Inversor 1.{i}" for i in range(1, 13)}},
            {"id": "irece_2", "usina": "Irece 2",
             "inversores": {"1": "Inversor 1.1", "2": "Inversor 1.2", "3": "Inversor 1.3", "4": "Inversor 1.8",
                            "5": "Inversor 1.9", "6": "Inversor 1.10", "7": "Inversor 1.4", "8": "Inversor 1.5",
                            "9": "Inversor 1.6", "10": "Inversor 1.7"}},
        ],
    },
    "salenergia": {
        "rotulo": "Sal Energia",
        "via": "modbus",
        "usinas": [
            {"id": "salvales", "usina": "Aquiraz 1 (Salvales)", "inversores": None},
            {"id": "carosa", "usina": "Aquiraz 2 (Carosa)", "inversores": None},
            {"id": "sunpower", "usina": "Cascavel (Sunpower)", "inversores": None},
            {"id": "hortina", "usina": "Quixadá 1 (Hortina)", "inversores": None},
            {"id": "vitesse", "usina": "Quixadá 2 (Vitesse)", "inversores": None},
        ],
    },
}


def usina_cfg(fonte, pid):
    return next((u for u in FONTES[fonte]["usinas"] if u["id"] == str(pid)), None)


def ordem_par(nome):
    """"Inversor 1.10" → (1, 10), depois do 1.9; "INV 03" → (3, 0)."""
    m = re.search(r"(\d+)\.(\d+)", str(nome or ""))
    if m:
        return (int(m.group(1)), int(m.group(2)))
    n = re.search(r"(\d+)", str(nome or ""))
    return (int(n.group(1)), 0) if n else (9999, 0)


def nome_inversor(cfg, equip, cadastro_ordem=()):
    """O inversor do cadastro para o equipamento do scadaGridco. Sem de-para fechado (Sal Energia), o N-ésimo do
    cadastro em ordem natural; sem cadastro, o rótulo da fonte."""
    mapa = cfg.get("inversores")
    if mapa:
        return mapa.get(str(equip))
    try:
        n = int(re.search(r"(\d+)", str(equip)).group(1))
    except (AttributeError, ValueError):
        return None
    ordem = sorted(cadastro_ordem, key=ordem_par)
    return ordem[n - 1] if 0 < n <= len(ordem) else None


# ── Cliente ─────────────────────────────────────────────────────────────────────────────────────────────────────────
class SemAcesso(RuntimeError):
    """Sem token, token recusado (302 para o login) ou endereço não configurado."""


_LOCK = threading.Lock()         # uma chamada por vez, a regra da Automação (o servidor também opera as usinas)
_SESSAO = requests.Session()


def configurado() -> bool:
    return bool(os.environ.get("SCADAGRIDCO_URL", "").strip() and os.environ.get("SCADAGRIDCO_TOKEN", "").strip())


def get(rota, params=None, timeout=TIMEOUT_S):
    """GET na API, em série com as outras chamadas do processo. 302 = token recusado (a API manda para o login)."""
    base = os.environ.get("SCADAGRIDCO_URL", "").strip().rstrip("/")
    token = os.environ.get("SCADAGRIDCO_TOKEN", "").strip()
    if not base or not token:
        raise SemAcesso("scadaGridco sem SCADAGRIDCO_URL/SCADAGRIDCO_TOKEN no tokens.txt")
    with _LOCK:
        r = _SESSAO.get(base + rota, headers={"X-API-Key": token}, params=params or {}, timeout=timeout,
                        allow_redirects=False)
    if r.status_code in (301, 302, 303, 401, 403):
        raise SemAcesso(f"scadaGridco recusou o token (HTTP {r.status_code})")
    r.raise_for_status()
    return r.json()


# ── Leitura atual ───────────────────────────────────────────────────────────────────────────────────────────────────
_RX_STRING = (re.compile(r"^string_current_(\d+)$"), re.compile(r"^string_(\d+)_current$"),
              re.compile(r"^string_(\d+)_i$"))


def strings_de(pontos) -> dict:
    """{nº da string: corrente (A) ou None} dos pontos de um inversor, nos três jeitos de escrever."""
    out = {}
    for k, v in (pontos or {}).items():
        for rx in _RX_STRING:
            m = rx.match(str(k))
            if m:
                out[int(m.group(1))] = float(v) if isinstance(v, (int, float)) else None
                break
    return out


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def leitura_mqtt(eq) -> dict:
    """Um equipamento de `/api/mqtt/<usina>` → leitura normalizada. Leitura ruim (communication_fault ≠ 192, `stale`
    ou `falha_comunicacao`) não traz valor: lacuna é sem comunicação, não zero."""
    m = eq.get("measurements") or {}
    ok = eq.get("communication_fault") == COM_OK and not eq.get("stale") and not eq.get("falha_comunicacao")
    eday = _num(m.get("total_daily_energy"))
    if eday is None:
        eday = _num(m.get("daily_active_energy"))
    return {"equip": str(eq.get("equipamento") or eq.get("indice")), "ts": _num(eq.get("ts")), "ok": ok,
            "pot_kw": _num(m.get("active_power")) if ok else None,
            "eday": eday if ok else None,
            "temp": _num(m.get("temperature_current")) if ok else None,
            "serial": m.get("serial_number"),
            "strings": strings_de(m) if ok else {}}


def leitura_modbus(unit) -> dict:
    """Um inversor de `/api/inversores/<usina>` → leitura normalizada (potência em W na fonte, kW aqui)."""
    m = unit.get("measurements") or {}
    ok = not unit.get("read_error") and not unit.get("stale") and bool(m)
    pw = _num(m.get("active_power_w"))
    ts = _num(unit.get("updated_at"))
    return {"equip": str(unit.get("slave_id")), "ts": ts if ts else None, "ok": ok,
            "pot_kw": pw / 1000.0 if ok and pw is not None else None,
            "eday": _num(m.get("daily_energy_kwh")) if ok else None,
            "temp": _num(m.get("internal_temperature_c")) if ok else None,
            "serial": m.get("serial_number"),
            "strings": strings_de(m) if ok else {}}


def leituras(fonte, pid) -> list:
    """A leitura atual de todos os inversores da usina (1 chamada)."""
    if FONTES[fonte]["via"] == "mqtt":
        d = get(f"/api/mqtt/{pid}")
        return [leitura_mqtt(e) for e in (d.get("equipamentos") or []) if e.get("tipo") == "inverter"]
    d = get(f"/api/inversores/{pid}")
    return [leitura_modbus(u) for u in (d.get("units") or [])]


def ts_local(ts) -> str:
    """epoch → 'AAAA-MM-DD HH:MM:SS' na hora das usinas (a da `ultima_leitura` das outras fontes)."""
    return datetime.fromtimestamp(ts, TZ).strftime("%Y-%m-%d %H:%M:%S") if ts else None


def hoje() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


# ── Curva do dia ────────────────────────────────────────────────────────────────────────────────────────────────────
def curva_mqtt(registros) -> dict:
    """Registros de `/api/telemetria` de UM inversor → {"strings": {n: [(HH:MM, A)]}, "pot": [(HH:MM, kW)],
    "ultimo_ts": ts}. Só leitura boa (192); ponto nulo fica fora (nulo não é zero)."""
    strings, pot, ultimo = {}, [], None
    for x in registros or []:
        ts = _num(x.get("ts"))
        if ts is not None:
            ultimo = ts if ultimo is None else max(ultimo, ts)
        if x.get("communication_fault") != COM_OK:
            continue
        hhmm = str(x.get("data_hora") or "")[11:16]
        if not hhmm:
            continue
        p = x.get("pontos") or {}
        for n, v in strings_de(p).items():
            if v is not None:
                strings.setdefault(n, []).append((hhmm, v))
        pk = _num(p.get("active_power"))
        if pk is not None:
            pot.append((hhmm, pk))
    return {"strings": strings, "pot": pot, "ultimo_ts": ultimo}


def curva_modbus(registros) -> dict:
    """Registros de `/api/dados/string` de UM inversor (uma linha por string a cada 5 min) → o formato da curva_mqtt."""
    strings, ultimo = {}, None
    for x in registros or []:
        ts = _num(x.get("ts"))
        if ts is not None:
            ultimo = ts if ultimo is None else max(ultimo, ts)
        v = _num(x.get("current_a"))
        hhmm = str(x.get("data_hora") or "")[11:16]
        if v is None or not hhmm or x.get("string_num") is None:
            continue
        strings.setdefault(int(x["string_num"]), []).append((hhmm, v))
    return {"strings": strings, "pot": [], "ultimo_ts": ultimo}


def junta(antes, novo) -> dict:
    """Curva guardada + o pedaço incremental (apos_ts): só acrescenta, o pedaço é todo depois do último ponto."""
    if not antes:
        return novo
    s = {n: list(v) for n, v in (antes.get("strings") or {}).items()}
    for n, v in (novo.get("strings") or {}).items():
        s.setdefault(n, []).extend(v)
    ult = [t for t in (antes.get("ultimo_ts"), novo.get("ultimo_ts")) if t is not None]
    return {"strings": s, "pot": list(antes.get("pot") or []) + list(novo.get("pot") or []),
            "ultimo_ts": max(ult) if ult else None}


def _paginas(rota, params, getter):
    regs, apos = [], params.get("apos_ts")
    base = {k: v for k, v in params.items() if k != "apos_ts"}
    for _ in range(50):                                      # teto: 50 × 5.000 = um mês de um inversor, nunca chega
        p = dict(base, limit=LIMITE)
        if apos is not None:
            p["apos_ts"] = apos
        d = getter(rota, p)
        regs.extend(d.get("registros") or [])
        apos = d.get("proximo_apos_ts")
        if not apos:
            break
    return regs


def curva_inversor(fonte, pid, equip, dia, apos_ts=None, getter=None) -> dict:
    """A curva de UM inversor num dia (≤ 45 dias atrás: é o que a API guarda). Um inversor por pedido: a usina inteira
    de uma vez são 19 MB e 22 s (Irecê 2, 06/10/2026); um inversor, 2,5 MB e 0,5 s."""
    getter = getter or get
    if FONTES[fonte]["via"] == "mqtt":
        regs = _paginas("/api/telemetria", {"usina": pid, "desde": dia, "ate": dia, "tipo": "inverter",
                                            "indice": int(equip), "apos_ts": apos_ts}, getter)
        return curva_mqtt([r for r in regs if str(r.get("equipamento")) == str(equip)])
    regs = _paginas(f"/api/dados/string", {"usina": pid, "desde": dia, "ate": dia, "slave_id": int(equip),
                                           "apos_ts": apos_ts}, getter)
    return curva_modbus([r for r in regs if str(r.get("slave_id")) == str(equip)])


class CurvasDoDia:
    """A curva de hoje de cada inversor, buscada aos pedaços (`apos_ts`): a 1ª busca traz o dia até agora, as
    seguintes só o que chegou depois. Dia passado é fixo: guardado inteiro por `TTL_PASSADO`."""
    TTL_HOJE = 300
    TTL_PASSADO = 6 * 3600

    def __init__(self):
        self._d = {}                                         # (fonte, pid, equip, dia) → {"ts", "curva"}
        self._lock = threading.Lock()

    def curva(self, fonte, pid, equip, dia, getter=None, agora=None):
        agora = time.time() if agora is None else agora
        k = (fonte, str(pid), str(equip), dia)
        with self._lock:
            ent = self._d.get(k)
        e_hoje = dia >= hoje()
        if ent and agora - ent["ts"] < (self.TTL_HOJE if e_hoje else self.TTL_PASSADO):
            return ent["curva"]
        apos = ent["curva"].get("ultimo_ts") if (ent and e_hoje) else None
        novo = curva_inversor(fonte, pid, equip, dia, apos_ts=apos, getter=getter)
        cur = junta(ent["curva"], novo) if apos is not None else novo
        with self._lock:
            self._d[k] = {"ts": agora, "curva": cur}
            for kk in [kk for kk, v in self._d.items() if kk[3] != hoje() and agora - v["ts"] > self.TTL_PASSADO]:
                self._d.pop(kk, None)
        return cur
