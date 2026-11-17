# -*- coding: utf-8 -*-
"""Recoleta pela API PV, 2ª conta (oem@), no formato do contrato da Coletas do Nexus (comum.py). Vai para o
BD_Performance: SEMP (Tucano 1 e 2), Alves Lima (Morada Nova) e 2C (Araputanga, Sete Lagoas, Tupi Paulista, União e
Ipixuna do Pará, que são três plantas, uma por UG).

A REGRA é a do coletor que roda toda noite (4b, 4c e 4d do `coletor.py`), portada de
`coleta API PV/src/coletar_semp.py` e `coleta_2c.py` como estavam em 17/11/2026 — o servidor não tem o coletor, e a
planilha que sai daqui é colada no mesmo BD que ele grava, então o número tem de ser o dele:
- a conta oem@ recebe "Invalid permission" no /plant_devices (medido em 31/07/2026), então o nome do inversor NÃO vem da
  API: o `custom_query` energy devolve só o `idinversor`, e o de-para por id (`USINAS`, fechado POR VALOR contra o BD,
  nunca pela ordem dos ids: na Morada Nova a ordem erra 6 de 8) é a única ponte. O decidido na tela De-para de
  equipamentos vence (`com_a_tela`), e o de-para por id da plataforma (`_pv_inv_nomes_de`) confere: se os dois
  traduzem o mesmo id para colunas diferentes, o inversor vira aviso — não se adivinha;
- dois ids na MESMA coluna somam (Morada Nova, INVERSOR08: o 388164 saiu e o 402513 entrou em 11/10/2026);
- meteo parcial não se integra (`meteo_cobre_o_dia`: a Araputanga entrou na API em 08/09/2026 só das 16:15 em diante
  e daria IPOA 1,27 no lugar de 8,65); IPOA e GHI só entram > 0; a Temperatura (só Tucano) é a média do módulo das 6h
  às 18h, com pelo menos 8 h de leitura (`temp_modulo_solar`);
- usina sem NENHUMA leitura no dia é queda da fonte (ou usina parada), não de nome: aviso, nada sugerido.
Duas diferenças, de propósito: Eday nulo NÃO vira 0 (o coletor faz `float(eday or 0)`; Levi, 06/11/2026: "sem dado não
se inventa") e usina declarada fora de operação vem do ambiente (`RECOLETA_OEM_FORA`), não do config.ini do coletor.

Custo (a cota histórica, por CONTA: 800 por dia e 200 por hora): cada planta × dia custa 1 `custom_query` energy e
cada ABA × dia com ETM custa 1 meteo — a Ipixuna é uma estação só, repetida nas três plantas (plataforma/CLAUDE.md,
"Fonte 2capi"), então a ETM dela sai da primeira planta pedida, não das três. Chuva não há: o coletor desta conta não
grava chuva no BD_Performance (a chuva é do BD_Thopen, fonte "chuva"). Sem plant_devices, que nem gasta cota e que
esta conta nem pode chamar.
"""
import datetime as dt
import json
import math
import os
import re
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor

import recoleta_apipv as _rc
from recoleta_fontes import comum

FONTE = "oem"
PAGA = True
# 5 plantas × 7 dias × 2 consultas = 70 por pedido no pior caso: cabe no teto do dia (100) e na hora da conta (200,
# dividida com a combiner das 9 plantas desta conta e os trackers da 2C). Cabe a Ipixuna inteira (3) com mais duas.
MAX_PLANTAS = 5
# Teto próprio desta recoleta, somando todos os pedidos do dia (comum.gastar). Menor que os 150 da conta principal: a
# oem@ não tem leitura de cota própria na plataforma (ver `permite`) e já paga a combiner e os trackers da 2C.
TETO = int(os.environ.get("RECOLETA_OEM_TETO_DIA") or 100)
TRABALHADORES = 4
FONTES_DEPARA = ("semp", "alveslima", "2capi")          # as fontes da conta oem@ no livro da tela De-para

# Usina declarada desligada: aviso e nenhuma consulta. É o `[coleta] usinas_fora` do config.ini do coletor
# (`config.fora_de_operacao`): sem ele, a Morada Nova de 01/09/2026 fazia o coletor refazer dias já completos todo dia.
# Nome do supervisório ou id, separados por ";". Vazio por padrão: a Morada Nova VOLTOU a gerar (o config.ini do fonte
# não a tem mais; só o do .exe instalado, que não a achava pelo nome novo — coleta API PV/CLAUDE.md).
FORA = {comum.chave_nome(x) for x in re.split(r"[;,]", os.environ.get("RECOLETA_OEM_FORA", "")) if x.strip()}

# ── USINAS: o `coletar_semp.USINAS` do coletor, como está em 17/11/2026 ─────────────────────────────────────────────────
# A chave é o nome do supervisório (a "Usina Supervisório" da aba Equipamentos), não o da API: a API renomeia planta (a
# Tucano em 26/08/2026; em 11/10 "Santa Cecilia 1/2/3" viraram "Ipixuna do Pará 1/2/3" e "MORADA NOVA" virou "Morada
# Nova"), e o coletor acha a planta pelo `plant_id`, que não muda. O id das Tucanos é o do PV_FONTES da plataforma (o
# coletor as acha pelo nome). `inversores`: idinversor -> nome que o coletor usa, fechado POR VALOR:
#   Tucano 1 (04/08/2026, contra a tela da plataforma); Tucano 2 (05/09, contra o dia 31/08 digitado pelo SCADA, os
#   quatro iguais e sem empate); Morada Nova (19/08, 64 casamentos em 8 dias; o 402513 é o INVERSOR08 desde 11/10, por
#   eliminação); Tupi 20/20 em 4 dias, Araputanga 10/10 em 2, Sete Lagoa 10/10 em 1 (11/09); União grupo 2 pela razão
#   entre os trios (28/09) e grupo 1 PELA ORDEM (11/10, provisório: o BD não tinha o 1.x para fechar); Ipixuna 18 ids
#   unânimes em 6 dias (29/09; a Santa Cecilia 1 PULA 400841 e 400842).
# `coluna_direta`: o nome já é a COLUNA do BD ("Inversor 1.1"), sem passar pela aba Equipamentos — as abas da 2C não
# tinham linha de inversor lá quando o e-mail as preenchia. `aba`: a do BD; nas de coluna direta é ela que vale ("Sete
# Lagoa" na API, "Sete Lagoas" na aba); nas outras vale a da aba Equipamentos e esta fica de reserva. `cobertura_parcial`
# (União, Ipixuna): a planta cobre só parte das colunas da aba — no coletor isso evita 0 vermelho nas colunas dos outros;
# aqui nada vira 0, então só serve para saber que a aba tem mais de uma planta.
USINAS = {
    "UFV Tucano 1": {"cliente": "SEMP", "plant_id": 18758732, "aba": "Tucano 1", "temperatura": True,
                     "inversores": {378310: "INVERSOR01", 378311: "INVERSOR02", 378312: "INVERSOR03",
                                    378313: "INVERSOR04"}},
    "UFV Tucano 2": {"cliente": "SEMP", "plant_id": 18768694, "aba": "Tucano 2", "temperatura": True,
                     "inversores": {391067: "INVERSOR01", 391068: "INVERSOR02", 391069: "INVERSOR03",
                                    391070: "INVERSOR04"}},
    "MORADA NOVA": {"cliente": "Alves Lima", "plant_id": 18766373, "aba": "Morada Nova",
                    "inversores": {388162: "INVERSOR01", 388159: "INVERSOR02", 388158: "INVERSOR03",
                                   388165: "INVERSOR04", 388161: "INVERSOR05", 388163: "INVERSOR06",
                                   388160: "INVERSOR07", 388164: "INVERSOR08", 402513: "INVERSOR08"}},
    "Araputanga": {"cliente": "2C", "plant_id": 18771898, "aba": "Araputanga", "coluna_direta": True,
                   "inversores": {400771 + i: f"Inversor 1.{i + 1}" for i in range(10)}},
    "Sete Lagoa": {"cliente": "2C", "plant_id": 18771901, "aba": "Sete Lagoas", "coluna_direta": True,
                   "inversores": {400784 + i: f"Inversor 1.{i + 1}" for i in range(10)}},
    "Tupi Paulista": {"cliente": "2C", "plant_id": 18750925, "aba": "Tupi Paulista", "coluna_direta": True,
                      "inversores": {**{367506 + i: f"Inversor 1.{i + 1}" for i in range(10)},
                                     **{367516 + i: f"Inversor 2.{i + 1}" for i in range(10)}}},
    "União": {"cliente": "2C", "plant_id": 18772125, "aba": "União 1 e 2", "coluna_direta": True,
              "cobertura_parcial": True,
              "inversores": {**{401313 + i: f"Inversor 2.{i + 1}" for i in range(6)},
                             **{401322 + i: f"Inversor 1.{i + 1}" for i in range(6)}}},
    "Santa Cecilia 1": {"cliente": "2C", "plant_id": 18771915, "aba": "Ipixuna do Pará", "coluna_direta": True,
                        "cobertura_parcial": True,
                        "inversores": {400840: "Inversor 1.1", **{400843 + i: f"Inversor 1.{i + 2}" for i in range(7)}}},
    "Santa Cecilia 2": {"cliente": "2C", "plant_id": 18771929, "aba": "Ipixuna do Pará", "coluna_direta": True,
                        "cobertura_parcial": True,
                        "inversores": {400882 + i: f"Inversor 2.{i + 1}" for i in range(6)}},
    "Santa Cecilia 3": {"cliente": "2C", "plant_id": 18771930, "aba": "Ipixuna do Pará", "coluna_direta": True,
                        "cobertura_parcial": True,
                        "inversores": {400888 + i: f"Inversor 3.{i + 1}" for i in range(6)}},
}
POR_ID = {cfg["plant_id"]: (nome, cfg) for nome, cfg in USINAS.items()}

# ── a cota da conta oem@ ─────────────────────────────────────────────────────────────────────────────────────────────
# A plataforma tem UMA leitura de cota (`app._pv_cota`, preenchida pelo `_pv_cota_le`), e ela não diz de qual conta é:
# a combiner e o dia passado das usinas da oem@ passam pelo `_pv_token_for` e gravam ali a cota da oem@, e o resto grava
# a da principal — vale a última resposta. Esta recoleta lê os cabeçalhos das SUAS respostas (que são todas da oem@) e
# guarda aqui, sem escrever no `_pv_cota`: escrever a cota folgada da oem@ lá deixaria a combiner da conta principal
# gastar abaixo da reserva da coleta do BD_Thopen. Sem leitura própria (antes da 1ª consulta do processo, ou com mais de
# 1 h), vale a da plataforma, na dúvida contra: pode ser da principal e recusar à toa, nunca o contrário.
_COTA = {"dia": None, "hora": None, "ts": 0.0, "zerada_ate": 0.0}
_COTA_LOCK = threading.Lock()
_COTA_VALIDADE_S = 3600


def _cota_le(r):
    """Guarda a cota histórica que a API PV diz nos cabeçalhos (a mesma leitura do `_pv_cota_le`, só que desta conta)."""
    try:
        h = getattr(r, "headers", None) or {}
        d, hr = h.get("X-RateLimit-Remaining-Day"), h.get("X-RateLimit-Remaining-Hour")
        with _COTA_LOCK:
            if d is not None:
                _COTA["dia"] = int(d)
            if hr is not None:
                _COTA["hora"] = int(hr)
            if d is not None or hr is not None:
                _COTA["ts"] = time.time()
            if getattr(r, "status_code", 200) == 429:
                ra = str(h.get("Retry-After") or "")
                _COTA["zerada_ate"] = time.time() + (int(ra) if ra.isdigit() else 300)     # sem Retry-After: 5 min
    except (TypeError, ValueError):                       # cabeçalho estranho não derruba a recoleta
        pass


def _fresca(c, agora):
    return bool(c and c.get("ts")) and agora - c["ts"] < _COTA_VALIDADE_S


def permite(ctx, n):
    """None ou o texto da recusa. A reserva é a da plataforma (`PV_COTA_RESERVA_DIA` 300 e `_HORA` 20: o que a coleta da
    noite precisa), e o pedido não pode deixar a cota abaixo dela — conta-se o `n`, não só o saldo de agora."""
    if not n:
        return None
    if ctx.disjuntor():
        return "a API PV está fora do ar agora (disjuntor aberto); tente em alguns minutos"
    if not ctx.configurada:
        return "a conta oem@ da API PV não está configurada neste servidor (PV_OEM_USERNAME e PV_OEM_PASSWORD)"
    agora = time.time()
    if agora < _COTA["zerada_ate"]:
        return ("a cota histórica da conta oem@ zerou (429 da API PV); volta em uns %d min"
                % max(1, round((_COTA["zerada_ate"] - agora) / 60)))
    app_c = ctx.cota_app or {}
    if agora < (app_c.get("zerada_ate") or 0):
        return ("a API PV respondeu 429 há pouco e a plataforma não guarda de qual conta; na dúvida a recoleta da oem@ "
                "espera uns %d min" % max(1, round((app_c["zerada_ate"] - agora) / 60)))
    if _fresca(_COTA, agora):
        leitura, de_quem = _COTA, "da conta oem@"
    elif _fresca(app_c, agora):
        leitura, de_quem = app_c, "lida pela plataforma (que não diz de qual conta é)"
    else:
        return None                                       # sem leitura de 1 h para cá: a 1ª resposta traz a de agora
    for chave, reserva, rot in (("dia", ctx.reserva_dia, "hoje"), ("hora", ctx.reserva_hora, "nesta hora")):
        v = leitura.get(chave)
        if v is not None and v - n < reserva:
            return ("a cota histórica %s tem %d consulta(s) %s e o pedido gasta %d: ficaria abaixo da reserva de %d da "
                    "coleta da noite; tente mais tarde ou peça menos" % (de_quem, v, rot, n, reserva))
    return None


# ── o de-para (o `com_a_tela` e o `_traduz` do coletor, sobre o Mapa da plataforma) ────────────────────────────────────
def _aba(ctx, nome, cfg):
    """A aba do BD: nas de coluna direta, a do USINAS; nas outras, a da aba Equipamentos (o `usina_map` do coletor)."""
    if cfg.get("coluna_direta"):
        return cfg["aba"]
    return ctx.mapa.usina_de(nome) or cfg["aba"]


def _colunas_da_aba(mapa, aba):
    ca = comum.chave_nome(aba)
    for u, cols in (mapa.inv_por_usina or {}).items():
        if comum.chave_nome(u) == ca:
            return cols
    return set()


def _coluna_no_mapa(mapa, aba, nomes_sup, equip):
    """A coluna de um Equipamento Supervisório, só DENTRO da aba da usina, preferindo a linha da própria planta: a
    Ipixuna é uma aba de três plantas e "INVERSOR01" existe na Santa Cecilia 2 e na 3 (o `com_a_tela` do coletor).
    None se não cair numa coluna só."""
    ce, ca = comum.chave_nome(equip), comum.chave_nome(aba)
    proprias = {comum.chave_nome(n) for n in nomes_sup}
    cands = [(cus, col) for (cus, ces), (ab, col) in (mapa.inv or {}).items()
             if ces == ce and comum.chave_nome(ab) == ca and col]
    achadas = {col for cus, col in cands if cus in proprias} or {col for _cus, col in cands}
    return achadas.pop() if len(achadas) == 1 else None


def com_a_tela(devs, cfg, nome, aba, decididos, mapa, avisos):
    """O de-para do USINAS com o decidido na tela por cima (`coletar_semp.com_a_tela`). Na usina pela aba Equipamentos
    o nome da tela entra como está; na de coluna direta ele vira a coluna pela aba Equipamentos, se cair numa só."""
    out = dict(devs)
    colunas = set(devs.values())
    for idi, eq in (decididos or {}).items():
        if not eq:
            continue                                      # vazio = vale o do coletor
        if not cfg.get("coluna_direta") or eq in colunas:
            out[idi] = eq
            continue
        col = _coluna_no_mapa(mapa, aba, (nome,), eq)
        if col:
            out[idi] = col
        else:
            avisos.append("%s: o de-para da tela diz %s -> %r, que não vira uma coluna da aba %s; vale o do coletor"
                          % (nome, idi, eq, aba))
    return out


def _traduz(cfg, nome, aba, rotulo, mapa):
    """(aba, coluna) pelo nome do coletor (`coletar_semp._traduz`): direto nas de coluna direta, pela aba Equipamentos
    nas outras. None quando o Equipamentos não conhece o par."""
    if cfg.get("coluna_direta"):
        return (aba, rotulo)
    return mapa.inversor_de(nome, rotulo)


def _traduz_plataforma(mapa, nome, aba, eq):
    """(aba, coluna) pelo nome do `_pv_inv_nomes_de` (o da plataforma, que é o do supervisório: "INVERSOR0 1.1" na
    Santa Cecilia 1) ou None. Já sendo uma coluna da aba (o "Inversor 1.1" da Araputanga), é ela."""
    t = mapa.inversor_de(nome, eq)
    if t and comum.chave_nome(t[0]) == comum.chave_nome(aba):
        return t
    col = _coluna_no_mapa(mapa, aba, (nome, aba), eq)
    if col:
        return (aba, col)
    if eq in _colunas_da_aba(mapa, aba):
        return (aba, eq)
    return None


def _ids(d):
    out = {}
    for k, v in (d or {}).items():
        try:
            out[int(k)] = str(v or "").strip()
        except (TypeError, ValueError):
            continue
    return out


def depara(ctx, nome, cfg):
    """{"col": {idinversor: (aba, coluna)}, "sem_trad": {idinversor: nome}, "conflito": {ids}, "avisos": [...]}."""
    pid, aba, avisos = cfg["plant_id"], _aba(ctx, nome, cfg), []
    try:
        tela = _ids(ctx.tela(pid))
    except Exception:                                     # noqa: BLE001 — livro ilegível = só o código, como no coletor
        tela = {}
    devs = com_a_tela(dict(cfg["inversores"]), cfg, nome, aba, tela, ctx.mapa, avisos)
    try:
        plat = _ids(ctx.inv_nomes(pid))
    except Exception:                                     # noqa: BLE001
        plat = {}
    col, sem_trad, conflito = {}, {}, set()
    for idi in sorted(set(devs) | set(plat)):
        c = _traduz(cfg, nome, aba, devs[idi], ctx.mapa) if devs.get(idi) else None
        p = _traduz_plataforma(ctx.mapa, nome, aba, plat[idi]) if plat.get(idi) else None
        if c and p and tuple(c) != tuple(p):
            # os dois de-paras por id divergem (alguém mexeu num e não no outro): o inversor iria para a coluna errada
            # sem sintoma nenhum — o coletor e a plataforma têm de concordar antes de sugerir
            avisos.append("%s: o idinversor %s vai para %s pelo coletor e para %s pela plataforma; não sugerido até os "
                          "dois de-paras concordarem" % (nome, idi, c[1], p[1]))
            conflito.add(idi)
        elif c or p:
            col[idi] = tuple(c or p)
        else:
            sem_trad[idi] = devs.get(idi) or plat.get(idi)
    return {"col": col, "sem_trad": sem_trad, "conflito": conflito, "avisos": avisos}


# ── as regras do dia (portadas do coletar_semp) ────────────────────────────────────────────────────────────────────────
def meteo_cobre_o_dia(leituras, ini=(7, 0), fim=(17, 0)):
    """(True, "") se a meteo cobre a janela solar — primeira até `ini`, última a partir de `fim`; senão (False, motivo)."""
    ts = []
    for rec in leituras or []:
        s = rec.get("tsleitura_new")
        if not s:
            continue
        try:
            ts.append(dt.datetime.fromisoformat(str(s)[:19]))
        except ValueError:
            continue
    if not ts:
        return False, "sem leitura de meteo"
    a, b = min(ts), max(ts)
    if (a.hour, a.minute) <= ini and (b.hour, b.minute) >= fim:
        return True, ""
    return False, "cobre só %s-%s" % (a.strftime("%H:%M"), b.strftime("%H:%M"))


_TEMP_CAMPOS = ("tempMod", "tempCell1", "tempCell2")
HORA_INI, HORA_FIM, HORAS_MIN = 6, 18, 8


def temp_modulo_solar(leituras):
    """Média da temperatura do MÓDULO (não a do ar: em 03/08/2026 deu 27,25 °C no ar e 36,31 °C no módulo) das 6h às
    18h (Levi, 04/08/2026), ou None com menos de 8 das 12 horas com leitura: sensor que morre às 9h não é o dia."""
    vals, horas = [], set()
    for rec in leituras or []:
        s = rec.get("tsleitura_new")
        if not s:
            continue
        try:
            ts = dt.datetime.fromisoformat(str(s)[:19])
        except ValueError:
            continue
        if not (HORA_INI <= ts.hour < HORA_FIM):
            continue
        c = rec.get("conteudojson") or {}
        if isinstance(c, str):
            try:
                c = json.loads(c)
            except ValueError:
                continue
        for campo in _TEMP_CAMPOS:
            try:
                fv = float(c.get(campo))
            except (TypeError, ValueError):
                continue
            if -20.0 <= fv <= 90.0:                       # fora disso é sentinela de erro (99999, -666)
                vals.append(fv)
                horas.add(ts.hour)
                break
    if len(horas) < HORAS_MIN:
        return None
    return round(sum(vals) / len(vals), 2)


def _num(v):
    """kWh ou None. NÃO é o `float(eday or 0)` do coletor: nulo é nulo."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _ordem(txt):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", str(txt))]


# ── as chamadas ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _post(ctx, url, corpo, timeout):
    """POST na API PV com o token da oem@; 401 renova o token uma vez. Lê a cota da conta em toda resposta."""
    r = None
    for tentativa in (0, 1):
        tok = ctx.token(force=bool(tentativa))
        if not tok:
            raise RuntimeError("sem token da conta oem@")
        r = ctx.http().post(url, headers={"x-access-token": tok, "Content-Type": "application/json"}, json=corpo,
                            timeout=timeout)
        _cota_le(r)
        if r.status_code == 401 and not tentativa:
            continue
        break
    return r


def _lista(r):
    """(lista, None) ou (None, motivo). Erro da API vem como dict ({"error": "Invalid id"}, limite do dia)."""
    if r.status_code != 200:
        return None, "HTTP %d %s" % (r.status_code, str(getattr(r, "text", "") or "")[:120])
    try:
        x = r.json()
    except ValueError:
        return None, "resposta inválida"
    if x is None:
        return [], None
    if not isinstance(x, list):
        return None, "a API respondeu %s" % str(x)[:120]
    return [e for e in x if isinstance(e, dict)], None


def _do_dia(linhas, campo, iso):
    return [x for x in linhas if str(x.get(campo) or "")[:10] in ("", iso)]


def _energia(ctx, pid, ids, d):
    """(linhas, motivo, extra) do Eday do dia: a usina inteira numa consulta (como o coletor) e, se a API disser que é
    grande demais, um inversor por vez. `extra` = consultas a mais que o por inversor gastou."""
    iso = d.isoformat()
    r = _post(ctx, ctx.base + "/custom_query",
              {"id": pid, "data_type": "energy", "period": d.strftime("%Y-%m"), "day": d.day}, 60)
    if r.status_code == 400 and "grande demais" in str(getattr(r, "text", "") or "").lower():
        return _energia_por_inversor(ctx, pid, ids, d)
    lin, erro = _lista(r)
    if erro:
        return None, erro, 0
    return _do_dia(lin, "dataleitura_new", iso), None, 0


def _energia_por_inversor(ctx, pid, ids, d):
    """A Tupi Paulista (20 inversores) responde `400 "Resposta grande demais"` no `custom_query` da usina inteira (o
    dia passado da curva de strings, 04/10/2026) e a API pede "um único dispositivo (idinverter ou device_id)". O
    energy da usina inteira passou todas as noites no coletor até aqui, então isto é a rede de segurança: o pedido vai
    pela v2 com `idinverter`, a mesma do `_spv_day_records_por_inversor`, e o registro vem sem o id, que é carimbado.
    Custa 1 consulta por inversor, que sai do teto e passa pela reserva ANTES de começar; um inversor que falha derruba o
    dia (dia pela metade não vale, a regra do `_spv_day_records_por_inversor`)."""
    extra = len(ids)
    motivo = permite(ctx, extra)
    if motivo:
        return None, "a usina inteira deu 'Resposta grande demais' e um inversor por vez gastaria %d consultas: %s" % (
            extra, motivo), 0
    try:
        comum.gastar(FONTE, extra, TETO)
    except comum.Recusa as e:
        return None, "a usina inteira deu 'Resposta grande demais' e um inversor por vez gastaria %d consultas: %s" % (
            extra, e), 0
    iso, out = d.isoformat(), []
    for inv in ids:
        if permite(ctx, 1):
            return None, "a cota chegou na reserva no meio do pedido por inversor (dia pela metade não vale)", extra
        r = _post(ctx, ctx.base_v2 + "/custom_query",
                  {"id": pid, "data_type": "energy", "period": d.strftime("%Y%m"), "day": d.day, "idinverter": inv}, 60)
        lin, erro = _lista(r)
        if erro:
            return None, "inversor %s: %s (dia pela metade não vale)" % (inv, erro), extra
        for x in _do_dia(lin, "dataleitura_new", iso):
            if x.get("idinversor") is None:
                x["idinversor"] = inv
            out.append(x)
    return out, None, extra


def _tarefa_ger(ctx, pid, nome, dp, d):
    iso, res = d.isoformat(), {"partes": [], "avisos": [], "desc": set(), "sem_trad": set()}
    motivo = permite(ctx, 1)
    if motivo:
        res["avisos"].append("%s %s: geração não pedida — %s" % (nome, iso, motivo))
        return res
    ids = sorted(set(dp["col"]) | set(dp["sem_trad"]) | set(dp["conflito"]))
    linhas, erro, extra = _energia(ctx, pid, ids, d)
    if extra:
        res["avisos"].append("%s %s: a usina inteira é grande demais para uma consulta; foi um inversor por vez "
                             "(%d consulta(s) a mais, já contadas no teto)" % (nome, iso, extra))
    if erro:
        res["avisos"].append("%s %s: geração não veio (%s)" % (nome, iso, erro))
        return res
    vistas = set()
    for x in linhas:
        try:
            idi = int(x.get("idinversor"))
        except (TypeError, ValueError):
            continue
        alvo = dp["col"].get(idi)
        if idi in dp["conflito"]:
            continue                                      # já avisado no de-para
        if alvo is None:
            # idinversor novo = inversor trocado ou acrescentado: gravar sem saber de quem é iria para a coluna errada
            (res["sem_trad"] if idi in dp["sem_trad"] else res["desc"]).add(idi)
            continue
        res["partes"].append((alvo[0], alvo[1], iso, _num(x.get("eday")), pid))
        vistas.add(alvo[1])
    if not linhas:
        # duas causas bem diferentes (coletor, 05/09/2026): de 01 a 04/09 o de-para da Morada Nova estava perfeito e a
        # API é que devolvia zero linha — a usina parou de reportar. Quem lesse "nenhum casou" iria mexer na planilha
        res["avisos"].append("%s %s: a API não devolveu NENHUMA leitura (o de-para tem %d inversores e está intacto): "
                             "queda da fonte ou usina fora de operação, não de nome; confira no portal"
                             % (nome, iso, len(dp["col"])))
    elif not res["partes"]:
        res["avisos"].append("%s %s: nenhum dos %d inversores da API casou com o de-para; nada sugerido (zero aqui "
                             "seria invenção, não medição)" % (nome, iso, len(linhas)))
    else:
        faltam = sorted({c for _a, c in dp["col"].values()} - vistas, key=_ordem)
        if faltam:
            res["avisos"].append("%s %s: %d inversor(es) do de-para sem leitura na API (fica vazio, não 0): %s"
                                 % (nome, iso, len(faltam), ", ".join(faltam)))
    return res


def _tarefa_met(ctx, pid, nome, cfg, aba, d):
    iso, res = d.isoformat(), {"escalares": [], "avisos": []}
    motivo = permite(ctx, 1)
    if motivo:
        res["avisos"].append("%s %s: ETM não pedida — %s" % (aba, iso, motivo))
        return res
    r = _post(ctx, ctx.base + "/custom_query",
              {"id": pid, "data_type": "meteo", "period": d.strftime("%Y-%m"), "day": d.day}, 120)
    lin, erro = _lista(r)
    if erro:
        res["avisos"].append("%s %s: meteo não veio (%s)" % (aba, iso, erro))
        return res
    lin = _do_dia(lin, "tsleitura_new", iso)
    if not lin:
        res["avisos"].append("%s %s: a API não devolveu leitura de meteo; ETM vazia" % (aba, iso))
        return res
    cobre, porque = meteo_cobre_o_dia(lin)
    if cobre:
        poa, ghi = _rc.integrar(lin)                      # o trapézio e os campos de POA/GHI do coletor
        for col, v in (("IPOA", poa), ("GHI", ghi)):
            if isinstance(v, (int, float)) and v > 0:
                res["escalares"].append({"usina": aba, "data": iso, "coluna": col, "valor": round(v, 3)})
            else:                                         # a Ipixuna: o piranômetro inclinado manda -1 (não mede)
                res["avisos"].append("%s %s: %s sem valor na estação; não sugerido" % (aba, iso, col))
    else:
        res["avisos"].append("%s %s: a meteo %s; IPOA e GHI não sugeridos (dia parcial integrado é um número errado "
                             "com cara de certo)" % (aba, iso, porque))
    if cfg.get("temperatura"):                            # no coletor, a temperatura não depende da janela da ETM
        t = temp_modulo_solar(lin)
        if t is None:
            res["avisos"].append("%s %s: temperatura do módulo com menos de %d h da janela solar; não sugerida"
                                 % (aba, iso, HORAS_MIN))
        else:
            res["escalares"].append({"usina": aba, "data": iso, "coluna": "Temperatura", "valor": t})
    return res


# ── o contrato ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def _fora(nome, pid):
    return bool(FORA) and (comum.chave_nome(nome) in FORA or str(pid) in FORA)


def contexto(app):
    return types.SimpleNamespace(
        mapa=app._recoleta_mapa(),
        token=app.get_token_oem,                          # get_token_oem(force=False): "" sem credencial
        http=app._http,                                   # a sessão por thread, com o disjuntor da API PV
        base=app.BASE_URL,                                # v1: o custom_query do coletor (period "AAAA-MM")
        base_v2=app.PV_V2_BASE,                           # v2: o pedido por inversor (period "AAAAMM", idinverter)
        inv_nomes=app._pv_inv_nomes_de,                   # o de-para por id da plataforma, com a tela por cima
        tela=lambda pid: app._dp.inversores(app._dp_estado(), FONTES_DEPARA, pid),   # só o decidido na tela
        cota_app=app._pv_cota,                            # a leitura única da plataforma (não diz a conta)
        reserva_dia=app.PV_COTA_RESERVA_DIA,
        reserva_hora=app.PV_COTA_RESERVA_HORA,
        disjuntor=app._pv_disj_aberto,
        configurada=bool(app.PV_OEM_USERNAME and app.PV_OEM_PASSWORD),
    )


def plantas(ctx):
    """A lista é a do coletor, sem perguntar à API: a planta é achada pelo id, que não muda, e a lista não gasta nada."""
    if not ctx.configurada:
        raise comum.Recusa(503, "a conta oem@ da API PV não está configurada neste servidor "
                                "(PV_OEM_USERNAME e PV_OEM_PASSWORD)")
    out = []
    for nome, cfg in USINAS.items():
        p = {"id": str(cfg["plant_id"]), "usina": _aba(ctx, nome, cfg), "destino": "BD_Performance", "planta": nome,
             "cliente": cfg["cliente"]}
        if _fora(nome, cfg["plant_id"]):
            p["fora_de_operacao"] = True
        out.append(p)
    return out


def _pedidas(ids):
    out = []
    for i in ids:
        try:
            pid = int(i)
        except (TypeError, ValueError):
            continue
        if pid in POR_ID:
            out.append((pid,) + POR_ID[pid])
    return out


def custo(ids, dias, geracao, etm, chuva):
    """1 energy por planta × dia; 1 meteo por ABA × dia (a Ipixuna é uma estação nas três plantas); chuva não há.
    O pedido por inversor (só se a API disser "grande demais") é contado à parte, na hora (`_energia_por_inversor`)."""
    vivas = [(pid, nome, cfg) for pid, nome, cfg in _pedidas(ids) if not _fora(nome, pid)]
    n_ger = len(vivas) if geracao else 0
    n_met = len({cfg["aba"] for _p, _n, cfg in vivas}) if etm else 0
    return len(dias) * (n_ger + n_met)


def buscar(ctx, ids, dias, geracao, etm, chuva):
    avisos, pedidas = [], []
    for pid, nome, cfg in _pedidas(ids):
        if _fora(nome, pid):
            avisos.append("%s: declarada fora de operação (RECOLETA_OEM_FORA); nada pedido" % nome)
        else:
            pedidas.append((pid, nome, cfg))
    if chuva:
        avisos.append("Chuva: a conta oem@ não tem chuva no BD_Performance (o coletor desta conta não a coleta); "
                      "nada pedido")
    por_aba = {}
    for pid, nome, cfg in pedidas:
        por_aba.setdefault(cfg["aba"], []).append((pid, nome, cfg))
    for aba, pl in por_aba.items():
        todas = [c["plant_id"] for c in USINAS.values() if c["aba"] == aba]
        if geracao and len(todas) > 1 and len(pl) < len(todas):
            # o comum.dias_fora conta os inversores da ABA inteira: com uma UG só da Ipixuna (6 de 20), todo dia sairia
            # "fonte fora do ar" sem estar
            avisos.append("%s: pedido de %d das %d plantas da aba; o aviso de fonte fora do ar conta a aba inteira e "
                          "pode acusar à toa — peça as %d juntas" % (aba, len(pl), len(todas), len(todas)))

    tarefas = []
    if geracao:
        dps = {}
        for pid, nome, cfg in pedidas:
            dps[pid] = depara(ctx, nome, cfg)
            avisos.extend(dps[pid]["avisos"])
        tarefas += [("ger", pid, nome, cfg, dps[pid], d) for pid, nome, cfg in pedidas for d in dias]
    if etm:
        for aba, pl in por_aba.items():
            pid, nome, cfg = pl[0]                        # a 1ª planta pedida da aba, na ordem do USINAS
            tarefas += [("met", pid, nome, cfg, _aba(ctx, nome, cfg), d) for d in dias]

    def roda(t):
        tipo, pid, nome, cfg, extra, d = t
        try:
            if tipo == "ger":
                return t, _tarefa_ger(ctx, pid, nome, extra, d)
            return t, _tarefa_met(ctx, pid, nome, cfg, extra, d)
        except Exception as e:                            # noqa: BLE001 — um dia que falha não derruba o pedido
            return t, {"avisos": ["%s %s: a API PV não respondeu (%s: %s)" % (nome, d.isoformat(), type(e).__name__,
                                                                                str(e)[:160])]}

    with ThreadPoolExecutor(max_workers=max(1, TRABALHADORES)) as ex:
        resultados = list(ex.map(roda, tarefas))

    soma, escalares, desc, sem_trad = {}, [], {}, {}
    for (tipo, pid, nome, *_r), res in resultados:
        avisos.extend(res.get("avisos") or [])
        escalares.extend(res.get("escalares") or [])
        if res.get("desc"):
            desc.setdefault(nome, set()).update(res["desc"])
        if res.get("sem_trad"):
            sem_trad.setdefault(nome, set()).update(res["sem_trad"])
        for aba, col, iso, v, p in res.get("partes") or []:
            ent = soma.setdefault((aba, col, iso), [None, set()])
            ent[1].add(p)
            if v is not None:                             # dois ids na mesma coluna somam; nulo + nulo segue nulo
                ent[0] = (ent[0] or 0.0) + v
    for nome, s in sorted(desc.items()):
        avisos.append("%s: %d idinversor(es) fora do de-para (%s); refazer o casamento por valor antes de confiar — "
                      "não sugeridos" % (nome, len(s), ", ".join(map(str, sorted(s)))))
    for nome, s in sorted(sem_trad.items()):
        avisos.append("%s: %d inversor(es) sem coluna na aba Equipamentos (%s); não sugeridos"
                      % (nome, len(s), ", ".join(map(str, sorted(s)))))
    geracao_out, nulos = [], {}
    for (aba, col, iso), (v, pids) in sorted(soma.items(), key=lambda kv: (kv[0][0], kv[0][2], _ordem(kv[0][1]))):
        if len(pids) > 1:                                 # duas plantas na mesma coluna: de-para errado, não se soma
            avisos.append("%s %s: a coluna %s recebe de %d plantas (%s); não sugerida"
                          % (aba, iso, col, len(pids), ", ".join(POR_ID[p][0] for p in sorted(pids))))
            continue
        geracao_out.append({"usina": aba, "inversor": col, "data": iso, "kwh": None if v is None else round(v, 3)})
        if v is None:
            nulos.setdefault((aba, iso), []).append(col)
    for (aba, iso), cols in sorted(nulos.items()):
        avisos.append("%s %s: %d inversor(es) com a geração nula na API (fica nulo, não 0): %s"
                      % (aba, iso, len(cols), ", ".join(cols)))
    escalares.sort(key=lambda e: (e["usina"], e["data"], e["coluna"]))
    return {"geracao": geracao_out, "escalares": escalares, "avisos": avisos}
