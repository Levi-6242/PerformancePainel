# -*- coding: utf-8 -*-
"""Falhas de strings e trackers — monta o pacote da aba "Falhas" do Diagnóstico de performance (24/09/2026).

É o código do estudo de 24/09 ("Falhas de strings e trackers, com a perda em kWh"), trazido para a plataforma para
o estudo e a aba usarem a MESMA conta. O worker chama `montar()` e grava o pacote; a tela só lê.

Entradas (o chamador entrega; aqui nada vai à rede):
- quedas de string gravadas (`perdas_strings.json`) e, onde houver, a régua nova sobre a curva (`falhas_strings.json`,
  de 24/09 em diante) — por usina-dia, a régua nova vence;
- curva do 2C (API PV pelo app._2c_hist_api; até 03/10/2026, o 2C_historico do e-mail) com a régua nova para todos os dias;
- episódios de tracker (`trk_eventos.json`) e o book de paradas (crônicos);
- cadastro: Equipamentos e Info Geral (kWp, strings ativas, cliente), BD_Trackers (tracker → inversor);
- travas de string (ufv_state), o de-para de inversor da API PV e a geração diária do mês (o juiz do kWh/kWp).

Réguas (pedidos do Levi, 24/09):
- strings: 06–18h, 2 h SEGUIDAS sem corrente (ver falhas.py); trancada não entra; episódio que atravessa o dia
  continua se a string amanhece zerada; sem notícia depois, segue EM ABERTO — "teremos mais informação no outro dia";
- trackers: a régua de parado da plataforma; parado que vira severo/médio/leve sai da visão; "parado" no alvo o
  episódio todo (desvio < 2°) não é falha — menos em dia com a maioria da frota parada, em que o desvio (medido contra a
  mediana da frota) não tem referência; dia que o registro não classificou não fecha nada (28/09);
- perda: kWp do equipamento × kWh/kWp real do dia × fração da energia do dia no episódio (strings, pela altura do
  sol) ou das horas solares (trackers, × 1 − cos do desvio de pico).
"""
import hashlib
import json
import math
import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import falhas as _regua

YIELD_PADRAO = 4.5            # kWh/kWp de usina plena (o piso da disponibilidade.py) — só quando falta a geração
FATOR_TRK_PADRAO = 0.25       # perda de tracker sem ângulo conhecido
# frota parada junto (28/09/2026, Levi: "as ocorrências de trackers parados em aberto hoje batem com o tempo real?" — 359
# de 738). O desvio do registro é medido contra a MEDIANA DA FROTA; com metade ou mais dela parada, a mediana é a própria
# frota parada e o desvio dá ~0 — Brodowski 52 de 52 a 0,6° desde 24/09, Guatambu 4, Primavera 1 e 2, Santa Bárbara I.
# Das 1.692 paradas descartadas como "no alvo" em setembro, 1.671 eram de dia assim. Metade é onde a mediana quebra.
FRAC_FROTA_PARADA = 0.5
JAN_INI, JAN_FIM = 6 * 60, 18 * 60
STR_MIN_MIN = 120             # "mais que 2 horas" seguidas (a curva já vem assim da régua nova; nas quedas gravadas é aqui)
DESPERTAR = 7 * 60 + 30       # caiu até 07:30 = amanheceu zerada (a régua do "zerada desde" da plataforma)
# volta falsa da manhã (27/09/2026): SMP100 5.2 ST15 lia um pouco de corrente com pouca luz e a régua das quedas contava
# como volta — a OS 13297 (09/09 → 21/09, MPPT em curto) virou 11 episódios de ~10h às ~8h do dia seguinte. Volta antes
# das 9h que morre de novo antes do meio-dia, viva no máximo 2h30, é o mesmo episódio.
MANHA_VOLTA_ATE = 9 * 60
MANHA_MORRE_ATE = 12 * 60
MANHA_VIVA_MAX = 150
# e a que pisca: no dado real a ST15 voltou 50 min (08:20–09:10) e 20 min (09:40–10:00) antes de morrer de vez às 10:00 —
# volta de até 1 h que morre de novo no mesmo dia também é o mesmo episódio, a qualquer hora. Até 28/09 valia só até o
# meio-dia: a MTS100 3.7 ST11 passou o 23/09 inteiro sem uma leitura acima de 0,5 A na curva, e as quedas gravadas
# "voltavam" 30 min às 12:40 e às 14:30 — o episódio fechava às 12:40 e outro abria às 15:00. Só junta episódio que JÁ
# tem 2 h seguidas: somar pedaços curtos seria a régua que o Levi recusou ("2 h SEGUIDAS", 24/09).
PISCA_VIVA_MAX = 60
# volta só com prova (28/09/2026, Levi: "as strings 3 e 4 não voltaram e caíram de novo dia 25, estiveram sempre sem
# corrente nesse dia!"). A queda do dia seguinte que começa depois das 07:30 fechava o episódio como "voltou de
# madrugada" — e começava tarde porque a PRODUÇÃO começou tarde (MAB100 25/09, 08:30, dia fechado) ou a 1ª leitura
# chegou tarde. Em setembro, 262 voltas "sem hora" seguidas de queda nova no mesmo dia. Continua o mesmo episódio a
# string morta desde a hora em que o inversor começou a gerar (tolerância de 20 min) ou, sem essa hora (quedas gravadas
# e curvas de antes de 27/09), a que caiu até as 10:30 — antes disso não há prova de que ela gerou.
MORTA_DESDE_PRODUCAO = 20
MANHA_SEM_HORA_ATE = 10 * 60 + 30
FLAG_MANHA = "volta curta ignorada (morreu de novo no mesmo dia)"
# sombra (29/09/2026, falhas.avaliar_dia): o trecho que entrou em rampa e terminou o dia morto vira falha se a string
# amanhece morta no dia registrado seguinte — sombra de verdade não atravessa a noite. Na 1ª versão da régua (só o
# relógio) MTS100 3.7 ST11 a ST13 (22/09) e SMP100 6.1 (18/09) passavam por sombra e só esta volta os salvava; eram
# buraco de dado, e a rampa já os deixa nas mortas. Fica como rede.
FLAG_DEVAGAR = "começou devagar (a queda levou 40 min ou mais)"
FONTE_VARRE_TUDO = {"sunop", "axis", "owen"}
# Queda gravada da API PV DEPOIS do fim do dia não vale (29/09/2026, Levi, com print da Rodrigues 2.1: "As strings
# citadas estão trancadas, veja se ocorre com mais usinas da Thopen e resolva"). Não era trava: o motor de ocorrências
# avalia o dia passado da API PV pela POTÊNCIA por string da PV Plataforma (trygenerate), não pela corrente, e é ele que
# grava o dia que a plataforma não viu (_perdas_str_backfill, depois da meia-noite). Na corrente da API PV do mesmo dia
# (custom_query v2), essa potência errava a string: Rodrigues 2.1, 10/09, Ipv13/16/17/18/21/22/23 "zeradas" o dia todo
# nos 8 inversores, gerando 9 a 14 A ao meio-dia; Ouro Branco, 15/09, 432 strings acusadas e nenhuma morta; Sorocaba e
# Guatambu 4, Ipv29 a Ipv32 num inversor de 28 entradas. Das 1.151 quedas gravadas da API PV na aba em 29/09 (107 MWh),
# ~95% eram string gerando. A gravada NO dia (corrente de hoje) segue valendo onde a usina-dia não tem a régua sobre a
# curva — e o backfill da curva da API PV (app._falhas_backfill_pv) dá a curva a quem ficou sem.
FONTE_POTENCIA_DEPOIS_DO_DIA = {"pv"}
# O dia que o backfill da API PV registrou não prova nem desmente entrada vazia (29/09/2026, 14h): a curva de dia
# passado pelo custom_query nem traz a entrada fantasma (Sorocaba Ipv29-32 num inversor de 28 entradas), e o dia
# passava por "dia de curva em que ela gerou" — no servidor, as entradas vazias caíram de 656 para 377 em uma hora e
# 279 fantasmas viraram falha com dias estimados (+70 MWh). Fica fora dos dias E das vivas da prova: só os dias, e uma
# string real que gerava nos dias do backfill e morreu no dia ao vivo levaria as vivas cheias de lá e passaria por vazia.
FONTE_BACKFILL_FORA_DA_VAZIA = {"pv"}
# Fontes cujo registro do dia ao vivo diz quantas entradas cada inversor manda (`entradas`, da curva da API PV — ver
# app.PV_ENTRADA_MIN_FRAC): string de número acima disso é entrada que o inversor não tem (Fazenda Limão, 01/10/2026).
FONTE_ENTRADAS_DO_REGISTRO = {"pv"}


def _fim_do_dia(dia):
    """Epoch da meia-noite que fecha DIA, em Brasília (o servidor roda em UTC)."""
    d = datetime.strptime(dia, "%Y-%m-%d") + timedelta(days=1)
    try:
        from zoneinfo import ZoneInfo
        return d.replace(tzinfo=ZoneInfo("America/Sao_Paulo")).timestamp()
    except Exception:                  # noqa: BLE001 — sem base de fusos, vale a hora do processo
        return d.timestamp()
FONTE_ROT = {"pv": "API PV", "pvsb": "API PV · String Box", "pg": "Banco", "sunop": "Athon", "axis": "Axis", "owen": "2C",
             "solaredge": "RenoGrid"}
_CACHE_2C = {}                # dia fechado → (marca das travas, [(cod, usina, strings sem corrente)])
_CACHE_2C_ARQ = {"path": None}  # de qual arquivo (app._FALHAS_2C_PATH) o _CACHE_2C foi carregado
CACHE_2C_DIAS = 70              # o mês e o anterior (remontado até o dia 2), com folga


def _marca_trancadas(tranc) -> str:
    """Marca das travas que vale entre processos: o hash() de um frozenset muda a cada processo (PYTHONHASHSEED)."""
    return hashlib.sha1("\n".join(sorted(map(str, tranc))).encode("utf-8")).hexdigest()


def _cache_2c_carrega(app):
    """O achado dos dias fechados da 2C sai do disco (04/10/2026). Desde que o e-mail saiu do código, o dia passado da 2C
    é ~25 consultas da cota histórica da API PV (1 por planta, 20 só da Tupi Paulista) e o cache vivia na memória do
    worker: cada reinício — cada deploy — pediria o mês inteiro de novo (no fim do mês, ~750, contra 800 por dia)."""
    path = getattr(app, "_FALHAS_2C_PATH", None)
    if not path or _CACHE_2C_ARQ["path"] == path:
        return
    _CACHE_2C_ARQ["path"] = path
    try:
        with open(path, encoding="utf-8") as f:
            disco = json.load(f) or {}
    except Exception:                  # noqa: BLE001 — sem arquivo: o normal na primeira vez
        disco = {}
    _CACHE_2C.clear()
    for dia, ent in disco.items():
        try:
            marca, lst = ent
            _CACHE_2C[dia] = (marca, [tuple(x) for x in lst])
        except (TypeError, ValueError):
            continue


def _cache_2c_grava(app, log=print):
    path = getattr(app, "_FALHAS_2C_PATH", None)
    if not path:
        return
    for dia in sorted(_CACHE_2C)[:-CACHE_2C_DIAS]:
        _CACHE_2C.pop(dia, None)
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({d: [m, lst] for d, (m, lst) in _CACHE_2C.items()}, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:             # noqa: BLE001 — sem gravar, o dia volta a ser pedido no próximo reinício
        log(f"[falhas] 2C: não gravei o achado dos dias fechados ({type(e).__name__}: {e})")


def _hm(s):
    try:
        h, m = str(s).split(":")[:2]
        return int(h) * 60 + int(m)
    except Exception:
        return None


def _fmt(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def _prox(dia, n=1):
    return (datetime.strptime(dia, "%Y-%m-%d") + timedelta(days=n)).strftime("%Y-%m-%d")


def _dias_entre(a, z):
    while a <= z:
        yield a
        a = _prox(a)


def chave_str(fonte, pid, inversor, string, dia):
    """A ocorrência de string que o analista desconsidera: fonte, usina, inversor, string e o DIA em que saiu. O dia, não
    a hora: o backfill refaz o dia e a hora da saída pode andar alguns minutos (07:10 → 07:20) sem ser outra ocorrência."""
    return f"{fonte}|{pid}|{inversor}|{string}|{dia}"


def chave_trk(fonte, pid, tracker, dia):
    return f"{fonte}|{pid}|{tracker}|{dia}"


def _nrm_semcom(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\s*\(\d+\)\s*$", "", s.strip())           # "Barretos 1 (83)": o id da API que o registro carrega
    return re.sub(r"\s+", " ", s).strip()


def chave_semcom(usina, tracker):
    """Chave do tracker na marca de sem comunicação das rondas (trackers_parados_hist.jsonl, app._falhas_trk_semcom_hist):
    a usina como a ronda escreve e o rótulo do tracker, sem acento, caixa e o "(id)" da API."""
    return f"{_nrm_semcom(usina)}|{_nrm_semcom(tracker)}"


def montar(app, sol, ini, fim, *, geracao, pv_dev=None, mortas_curva=None, str_store=None, trk_store=None,
           book=None, hist_2c=None, agora=None, abertos_antes=None, desconsideradas=None, trk_semcom=None, log=print):
    """Pacote {periodo, gerado_em, strings, trackers, regua} de [ini, fim] (AAAA-MM-DD, fim incluso).
    hist_2c(dia) → {"strings": {cod: {inv: {string: serie}}}} (padrão: app._2c_hist_api, a API PV com as chaves do
    antigo acervo do e-mail — o e-mail da 2C saiu do código em 03/10/2026).
    desconsideradas = {"strings": {chave_str}, "trackers": {chave_trk}}: ocorrência que o analista tirou da conta
    (Levi, 30/09/2026 — strings da MAB200 que caíram com os trackers parados): sai dos episódios, da visão por inversor
    × dia e dos totais, e vai para `desconsideradas`, para a tela poder devolver.
    trk_semcom = {dia: {chave_semcom(usina, tracker)}}: tracker sem comunicação pela ronda, para o dia cujo registro
    ainda não traz a marca `sem_comunicacao` (antes de 01/10/2026)."""
    desc = desconsideradas or {}
    desc_str, desc_trk = set(desc.get("strings") or ()), set(desc.get("trackers") or ())
    str_desc, trk_desc = [], []
    import pandas as pd

    t0 = time.time()
    # episódio aberto de HOJE termina em "agora", não às 18:00: às 10:21 de 25/09 os 405 trackers parados desde a manhã
    # contavam até as 18:00 (~11 h cada, em vez de ~3 h) — 45 MWh a mais só no dia corrente
    agora = agora or datetime.now()
    hoje, agora_min = agora.strftime("%Y-%m-%d"), agora.hour * 60 + agora.minute

    def fim_janela(dia):
        return min(JAN_FIM, agora_min) if dia == hoje else JAN_FIM

    pv_dev = pv_dev or {}
    mortas_curva = mortas_curva or {}
    if str_store is None:
        with open(app._PERDAS_STR_PATH, encoding="utf-8") as f:
            str_store = json.load(f)
    if trk_store is None:
        with open(os.path.join(os.path.dirname(app._PERDAS_STR_PATH), "trk_eventos.json"), encoding="utf-8") as f:
            trk_store = json.load(f)
    if book is None:
        try:
            with open(os.path.join(os.path.dirname(app._PERDAS_STR_PATH), "paradas_book.json"), encoding="utf-8") as f:
                book = json.load(f)
        except Exception:
            book = {}
    nrm = app._nrm
    SOL_MIN = sol.SOL_BAIXO_GRAUS

    # ── cadastro por NOME DE EXIBIÇÃO (é o que os stores guardam) ─────────────────────────────
    df = pd.read_excel(app._bd_readable(), sheet_name="Equipamentos", header=2)
    CAD_INV, CAD_UFV, CLIENTE_DE, CAD_INV_DISP = {}, {}, {}, {}
    for _, r in df.iterrows():
        us, eq = r.get("Usina"), r.get("Equipamento")
        if pd.isna(us) or pd.isna(eq):
            continue
        usn, eqs = nrm(us), str(eq).strip()
        pot = r.get("Potência (kWp)")
        pot = float(pot) if pd.notna(pot) else None
        if pd.notna(r.get("Cliente")):
            CLIENTE_DE.setdefault(usn, str(r["Cliente"]).strip())
        if eqs.upper() == "UFV":
            CAD_UFV[usn] = {"kwp": pot, "n_inv": int(r["N de Inversores"]) if pd.notna(r.get("N de Inversores")) else None}
        elif eqs.lower().startswith("inversor"):
            sa = r.get("Strings Ativas")
            CAD_INV[(usn, nrm(eqs))] = {"kwp": pot, "strings": int(round(float(sa))) if pd.notna(sa) else None,
                                        "sup": str(r.get("Equipamento Supervisório") or "").strip()}
            CAD_INV_DISP[(usn, eqs)] = CAD_INV[(usn, nrm(eqs))]
    # Info Geral: kWp e nº de trackers — fallback de quem não está no BD_Trackers nem tem linha UFV com kWp
    IG_TRK, IG_KWP, IG_NINV = {}, {}, {}
    try:
        ig = pd.read_excel(app._bd_readable(), sheet_name="Info Geral", header=None)
        hdr = next(i for i in range(6) if any("usina" in str(v).lower() for v in ig.iloc[i].values))
        ig.columns = [str(c).strip() for c in ig.iloc[hdr].values]
        ig = ig.iloc[hdr + 1:]
        c_us = next(c for c in ig.columns if c.lower().startswith("usina"))
        c_tr = next((c for c in ig.columns if "tracker" in c.lower()), None)
        c_kw = next((c for c in ig.columns if "kwp" in c.lower()), None)
        c_ni = next((c for c in ig.columns if "inversor" in c.lower()), None)
        for _, r in ig.iterrows():
            u = nrm(r[c_us]) if pd.notna(r[c_us]) else ""
            if not u:
                continue
            for c, dst in ((c_tr, IG_TRK), (c_kw, IG_KWP), (c_ni, IG_NINV)):
                if c is not None and pd.notna(r[c]):
                    try:
                        dst[u] = float(r[c])
                    except (TypeError, ValueError):
                        pass
    except Exception as e:
        log(f"[falhas] Info Geral não lida: {e}")

    def canon(usina):
        return app._macro_usina_nome(str(usina or "")) or str(usina or "")

    def cliente(usina):
        c = canon(usina)
        ig_ = app.INFO_GERAL.get(nrm(c)) or {}
        return ig_.get("cliente") or CLIENTE_DE.get(nrm(c)) or CLIENTE_DE.get(nrm(usina)) or ""

    def inv_nome(s):
        s = str(s or "").strip()
        return f"Inversor {s}" if re.fullmatch(r"\d+\.\d+", s) else s

    def cad_inv(usina, inversor):
        """(kWp do inversor, strings esperadas, origem) — pelo nome de exibição; fallback = UFV ÷ N inversores."""
        for u in (usina, canon(usina)):
            c = CAD_INV.get((nrm(u), nrm(inversor)))
            if c:
                return c["kwp"], c["strings"], "inversor"
        for u in (usina, canon(usina)):
            ufv = CAD_UFV.get(nrm(u))
            if ufv and ufv.get("kwp") and ufv.get("n_inv"):
                return ufv["kwp"] / ufv["n_inv"], None, "ufv/n"
            k = nrm(u)
            if IG_KWP.get(k) and IG_NINV.get(k):
                return IG_KWP[k] / IG_NINV[k], None, "ufv/n"
        return None, None, "sem_kwp"

    # ── sol por estado ────────────────────────────────────────────────────────────────────────
    _jan_cache, _perfil_cache = {}, {}

    def janela_sol(usina, dia):
        est = app._estado_da_usina(usina) or app._estado_da_usina(canon(usina))
        key = (est, dia)
        if key in _jan_cache:
            return _jan_cache[key]
        if not est or sol.coordenadas(est) is None:
            _jan_cache[key] = (None, None, est)
            return _jan_cache[key]
        d0 = datetime.strptime(dia, "%Y-%m-%d")
        a = b = None
        for m in range(4 * 60, 20 * 60, 2):
            e = sol.elevacao_estado(est, d0 + timedelta(minutes=m))
            if e is not None and e >= SOL_MIN:
                a = m if a is None else a
                b = m
        _jan_cache[key] = (a, b, est)
        return _jan_cache[key]

    def intersec(a, b, usina, dia):
        """[a,b) em minutos ∩ 06–18h ∩ sol ≥ 8° no estado. → (ini, fim, minutos, sem_estado)."""
        si, sf, est = janela_sol(usina, dia)
        lo, hi = JAN_INI, JAN_FIM
        if si is not None:
            lo, hi = max(lo, si), min(hi, sf)
        x, y = max(a, lo), min(b, hi)
        return x, y, max(0, y - x), est is None

    def h_sol_dia(usina, dia):
        return intersec(0, 24 * 60, usina, dia)[2] / 60.0

    def perfil_sol(usina, dia):
        """Peso da energia minuto a minuto = sin(elevação), o proxy de céu limpo: a perda de um episódio é a FRAÇÃO
        DA ENERGIA DO DIA que cabe nele — uma string zerada das 09:00 às 16:30 perde ~80% do dia, não 100%."""
        est = app._estado_da_usina(usina) or app._estado_da_usina(canon(usina))
        key = (est, dia)
        if key in _perfil_cache:
            return _perfil_cache[key]
        if not est or sol.coordenadas(est) is None:
            _perfil_cache[key] = None
            return None
        d0 = datetime.strptime(dia, "%Y-%m-%d")
        acc, s = [0.0], 0.0
        for m in range(0, 24 * 60, 2):
            e = sol.elevacao_estado(est, d0 + timedelta(minutes=m))
            s += max(0.0, math.sin(math.radians(e))) if e is not None else 0.0
            acc.append(s)
        _perfil_cache[key] = acc
        return acc

    def share_energia(usina, dia, x, y):
        if y <= x:
            return 0.0
        acc = perfil_sol(usina, dia)
        if not acc or acc[-1] <= 0:
            return (y - x) / (12 * 60.0)
        i, j = min(len(acc) - 1, x // 2), min(len(acc) - 1, y // 2)
        return (acc[j] - acc[i]) / acc[-1]

    # ── geração diária por usina (juiz do kWh/kWp) ────────────────────────────────────────────
    GER_N = {nrm(u): v for u, v in (geracao or {}).items()}

    def yield_dia(usina, dia):
        for u in (canon(usina), usina, re.sub(r"\s+\d+$", "", canon(usina))):
            g = GER_N.get(nrm(u))
            if g and g.get("kwp") and dia in g["dias"] and g["dias"][dia] > 0:
                return g["dias"][dia] / g["kwp"]
        return None

    # ══ STRINGS ══════════════════════════════════════════════════════════════════════════════
    # a queda da API PV gravada depois do fim do dia veio da potência da PV Plataforma (FONTE_POTENCIA_DEPOIS_DO_DIA):
    # sai do store aqui, antes de tudo — nem episódio, nem dia visto, nem "voltou" para a entrada vazia
    pot_fora, fim_dia, filtrado = Counter(), {}, {}
    for dia_s, fontes_s in str_store.items():
        for fonte_s, usinas_s in (fontes_s or {}).items():
            if fonte_s in FONTE_POTENCIA_DEPOIS_DO_DIA and usinas_s:
                fim_dia.setdefault(dia_s, _fim_do_dia(dia_s))
                ficam = {}
                for pid_s, ent_s in usinas_s.items():
                    if float((ent_s or {}).get("ts") or 0) >= fim_dia[dia_s]:
                        if ini <= dia_s <= fim:
                            pot_fora["usinas-dia"] += 1
                            pot_fora["quedas"] += len(ent_s.get("eventos") or [])
                        continue
                    ficam[pid_s] = ent_s
                usinas_s = ficam
            filtrado.setdefault(dia_s, {})[fonte_s] = usinas_s
    str_store = filtrado
    dias = [x for x in sorted(str_store) if ini <= x <= fim]
    # "em aberto" conta pelo último dia COM dado, não pela data de hoje: logo depois da meia-noite o período já vai
    # até um dia vazio, e tudo que estava aberto ontem fechava (25/09, 00:33 no servidor: 0 trackers em aberto)
    ult_str = max((x for x in dias if any((str_store[x] or {}).values())), default=fim)
    str_q = Counter()
    if pot_fora:
        str_q["API PV: queda gravada depois do dia (potência da PV Plataforma): fora"] = pot_fora["quedas"]
    parcial, massa = set(), {}
    registro = defaultdict(set)          # (fonte, pid) → dias com a usina no store (varrida e com queda)
    dias_fonte = defaultdict(set)        # fonte → dias em que ela gravou
    wake_depois = set()                  # (chave da string, dia > fim) em que ela ainda amanheceu zerada
    for dia in [x for x in sorted(str_store) if x >= ini]:
        for fonte, usinas in str_store[dia].items():
            if fonte == "owen":
                continue                 # 2C vem da curva (abaixo)
            dias_fonte[fonte].add(dia)
            for pid, ent in usinas.items():
                registro[(fonte, pid)].add(dia)
                if dia > fim:
                    for e in ent.get("eventos") or []:
                        a = _hm(e.get("caiu"))
                        if a is not None and a <= DESPERTAR:
                            wake_depois.add(((fonte, pid, canon(ent.get("usina") or pid), inv_nome(e.get("inversor")),
                                              str(e.get("string"))), dia))
    for dia, fontes in mortas_curva.items():             # usina varrida pela régua nova conta como registrada
        for fonte, usinas in fontes.items():
            if dia >= ini:
                for pid, ent_r in usinas.items():
                    # ...se a leitura teve produção: o worker lê a usina de madrugada também, e o registro sem nada gerando
                    # contava como "a usina apareceu e a string não estava zerada" (Assis 5.1, 28/09: fechava tudo como
                    # "voltou 28/09 06:40, de madrugada"). Registro antigo, sem as vivas, segue valendo como antes.
                    if "vivas" in ent_r and not ent_r.get("vivas") and not ent_r.get("mortas"):
                        continue
                    dias_fonte[fonte].add(dia)
                    registro[(fonte, pid)].add(dia)
    for dia in dias:
        for fonte, usinas in str_store[dia].items():
            ult, n, volt = 0, 0, Counter()
            for pid, ent in usinas.items():
                for e in ent.get("eventos") or []:
                    n += 1
                    for k in ("caiu", "voltou"):
                        v = _hm(e.get(k)) if e.get(k) else None
                        if v:
                            ult = max(ult, v)
                    if e.get("voltou"):
                        volt[str(e["voltou"])] += 1
            # retorno em massa: 100+ strings "voltando" no mesmo minuto = a telemetria voltou, não a string
            if volt and max(volt.values()) >= 100:
                massa[(dia, fonte)] = max(volt.items(), key=lambda kv: kv[1])[0]
                str_q["dia-fonte com retorno em massa (buraco de telemetria)"] += 1
            # captura parcial: o dia fechou no store com o último instante visto antes das 16:00 → foto pela metade
            if n >= 20 and ult < 16 * 60:
                parcial.add((dia, fonte))
                str_q["dia-fonte com captura parcial"] += 1

    def perda_seg(usina, inv, dia, x, y, flags):
        """(kWp da string, kWh/kWp do dia, perda, perda nominal) do trecho [x, y) do dia."""
        mins = max(0, y - x)
        kwp_inv, n_str, orig = cad_inv(usina, inv)
        if kwp_inv is None:
            flags.add("sem kWp")
            if mins > 0:
                str_q["evento sem kWp"] += 1
            return None, None, 0.0, 0.0
        if mins <= 0:
            return None, None, 0.0, 0.0
        if not n_str:
            flags.add("strings esperadas ausentes (20)")
        if orig == "ufv/n":
            flags.add("kWp da UFV ÷ N inversores")
        kwp_str = kwp_inv / (n_str or 20)
        y_ = yield_dia(usina, dia)
        if y_ is None:
            y_ = YIELD_PADRAO
            flags.add("sem geração no dia (4,5 kWh/kWp)")
        return kwp_str, y_, kwp_str * y_ * share_energia(usina, dia, x, y), kwp_str * (mins / 60.0)

    # travas: marcada à mão = MPPT sem string. O detector já as tira na hora, mas o store guarda dias de antes da
    # trava; aqui a trava de HOJE vale para o mês inteiro. Chaves do ufv_state por fonte: pv plant|idefinversor|IpvN;
    # sunop/axis plant|INV_n|I_PVn; owen cod|inv|n.
    TRANC = app._trancadas
    str_q["strings trancadas no estado (ufv_state.json)"] = len(TRANC)
    # nome de inversor comparado NORMALIZADO (sem espaço, minúsculo — o _nrm da plataforma): em 25/09 o plant_devices
    # chamava o 378276 de Indaiatuba de "INVERSOR 1.10" e a queda gravada dizia "Inversor 1.10"; pelo nome exato a
    # trava 21480|378276|Ipv18 não era conferida e 16 episódios da string trancada apareciam na aba
    SUNOP_INV_KEY = {}
    TEM_TRAVA = {k.split("|")[0] for k in TRANC}
    for k in TRANC:
        p = k.split("|")
        if len(p) == 3 and "I_PV" in p[2]:
            SUNOP_INV_KEY[(p[0], nrm(app._sunop_inv_display(p[0], p[1])))] = p[1]
    PV_INV_ID, PV_INV_NOME = {}, {}
    for pid, ent in pv_dev.items():
        nome_api = ent.get("nome_api")
        usn = nrm(ent.get("usina") or "")
        for inv_id, dev_name in (ent.get("names") or {}).items():
            disp = app.EQUIP_NAMES.get(nome_api, {}).get(dev_name) if nome_api else None
            if disp is None:
                disp = next((eq for (u, eq), c in CAD_INV_DISP.items() if u == usn and nrm(c["sup"]) == nrm(dev_name)), dev_name)
            for nome in (disp, dev_name):
                PV_INV_ID.setdefault((str(pid), nrm(nome)), str(inv_id))
            PV_INV_NOME[(str(pid), str(inv_id))] = disp

    IDS = {}                          # (fonte, pid, inversor) → id do inversor na fonte, como a curva registrou
    for _dia, _fontes in mortas_curva.items():
        for _fonte, _usinas in _fontes.items():
            for _pid, _ent in _usinas.items():
                for _inv, _id in (_ent.get("ids") or {}).items():
                    IDS[(_fonte, str(_pid), nrm(_inv))] = str(_id)

    def trancada(fonte, pid, inv_raw, string):
        """True = trancada; False = livre; None = sem de-para (não dá para conferir)."""
        id_curva = IDS.get((fonte, str(pid), nrm(inv_raw)))
        if fonte == "pg":                 # Banco da Thopen: power_plant_id|tb_devices.id|N (ST 07 → 7)
            m = re.search(r"\d+", str(string))
            return bool(id_curva and m) and f"{pid}|{id_curva}|{int(m.group())}" in TRANC
        if fonte in ("pv", "pvsb"):
            m = re.fullmatch(r"(?:INV-)?(\d{4,})", str(inv_raw))       # o próprio id no lugar do nome
            inv_id = id_curva or (m.group(1) if m else PV_INV_ID.get((str(pid), nrm(inv_raw))))
            if inv_id is None:          # sem de-para: só é dúvida se a usina tem alguma trava
                return None if str(pid) in TEM_TRAVA else False
            return app._str_trancada(str(pid), inv_id, str(string))
        if fonte in ("sunop", "axis"):
            key = SUNOP_INV_KEY.get((str(pid), nrm(inv_raw)))
            m = re.search(r"\d+", str(string))
            if key is None or not m:
                # o nome da trava sai da mesma função que nomeia a queda: inversor fora do mapa não tem trava (MAB100
                # Inv 3.9, 25/09: a usina tem UMA trava, no 2.3, e toda queda dela ficava "trava não conferida")
                return False if key is None else None
            return app._str_key(pid, key, f"I_PV{int(m.group())}") in TRANC
        if fonte == "owen":
            return app._str_key(pid, inv_raw, string) in TRANC
        return False

    # 2C: a curva vem da API PV (app._2c_hist_api, as chaves do antigo e-mail) — régua nova em todos os dias. Dia
    # fechado não muda: guarda o achado (com a marca das travas, que podem mudar) e o ciclo seguinte do worker não
    # pede o mês de novo. API fora levanta: o dia não é guardado e volta no ciclo seguinte.
    _cache_2c_carrega(app)
    marca = _marca_trancadas(TRANC)
    dias_2c, novos_2c = {}, False
    for dia in _dias_entre(ini, fim):
        ach = _CACHE_2C.get(dia)
        if ach is None or ach[0] != marca or dia >= hoje:
            try:
                data = (hist_2c or app._2c_hist_api)(dia).get("strings", {})
            except Exception as e:
                log(f"[falhas] 2C {dia}: {e}")
                continue
            lst = []
            for u, invs in data.items():
                usina = app._macro_usina_nome(app._owen_nome(u)) or app._owen_nome(u)
                curvas = {inv: {sid: s for sid, s in strs.items() if app._str_key(u, inv, sid) not in TRANC}
                          for inv, strs in invs.items()}
                if any(curvas.values()):
                    lst.append((u, usina, _regua.avaliar_dia(curvas, zero=app.STRING_SEM_CORRENTE_A,
                                                             piso_inv=app.STR_EV_INV_MIN_MED)))
            ach = (marca, lst)
            if dia < hoje:
                _CACHE_2C[dia] = ach
                novos_2c = True
        dias_2c[dia] = ach[1]
    if novos_2c:
        _cache_2c_grava(app, log)

    # ENTRADA VAZIA (27/09/2026). O cruzamento com as OS mostrou que Ipv29 a Ipv32 eram 41% dos episódios e 55% do kWh
    # de setembro: entradas sem string ligada (0 A cravado o dia inteiro: Santana do Ipanema 1.13, Guatambu 4.6),
    # nunca citadas em OS. Entrada vazia = nenhum sinal de vida — nenhuma volta de verdade no histórico gravado, zero em
    # toda curva do dia — num inversor que já tem, vivas, as strings do cadastro. O cadastro sozinho não serve: SMP100
    # 5.2 tem 17 strings no cadastro e ST19 a ST25 são reais (a OS 13297 cita); elas voltaram em 08/09 e 17/09. Sai do
    # mês inteiro, como a trava. Queda "no meio do dia" não prova vida: aparece em 172 entradas vazias por buraco de
    # captura (a primeira foto do dia chega tarde).
    # nome de exibição do cadastro por (usina, inversor normalizado): "INVERSOR 3.3" (plant_devices), "INV-378276" (o id,
    # quando o plant_devices falha — Santana do Ipanema, 27/09 23:41) e "Inversor 3.3" (a queda gravada) são o mesmo
    # inversor; sem isso a entrada vazia não casava com o cadastro e a curva não emendava com as quedas
    CAD_NOME = {}
    for (u_, eqs_) in CAD_INV_DISP:
        CAD_NOME.setdefault((u_, nrm(eqs_)), eqs_)

    def inv_cadastro(usina, inv):
        for u in (usina, canon(usina)):
            n_ = CAD_NOME.get((nrm(u), nrm(inv)))
            if n_:
                return n_
        return inv

    def inv_canon(fonte, pid, inv_raw, usina=None):
        m_id = re.fullmatch(r"(?:INV-)?(\d{4,})", str(inv_raw)) if fonte in ("pv", "pvsb") else None
        nome = inv_nome(PV_INV_NOME.get((str(pid), m_id.group(1)), str(inv_raw)) if m_id else str(inv_raw))
        return inv_cadastro(usina, nome) if usina else nome

    def chave_ch(fonte, pid, inv, string):
        return (fonte, str(pid), nrm(inv), nrm(string))

    # ENTRADA QUE O INVERSOR NÃO MANDA (01/10/2026, Levi: "pra mim fazenda limão não aparece essas strings 29 a 32").
    # Em 30/09 o INVERSOR06 da Fazenda Limão mandou Ipv1 a Ipv28 em 1.436 registros e Ipv29 a Ipv32 = 0 num registro
    # solto das 09:00; a régua leu célula sem leitura como sem corrente e a entrada que ele nem tem "morreu" o dia
    # inteiro. A curva da API PV já não deixa o solto entrar, mas os dias gravados antes disso e as quedas do detector
    # das ocorrências têm a fantasma — e a prova da entrada vazia (abaixo) não a pegava: no dia em que o solto não vem,
    # ela nem está na curva, e esse dia contava como dia em que ela gerou (9 dos 19 inversores da Fazenda Limão ficavam
    # como falha). O registro do dia AO VIVO guarda quantas entradas cada inversor manda; string de número acima do maior
    # visto não existe e sai do mês inteiro. A curva de dia passado (backfill, custom_query) não é o pacote do inversor
    # e não ensina; na dúvida entre dias, vale o maior número (a string fica).
    N_ENT, inexist = {}, {}
    for dia_h, fontes_h in mortas_curva.items():
        for fonte_h in FONTE_ENTRADAS_DO_REGISTRO:
            for pid_h, ent_h in ((fontes_h or {}).get(fonte_h) or {}).items():
                if ent_h.get("origem") == "backfill":
                    continue
                for inv_h, n_h in (ent_h.get("entradas") or {}).items():
                    k_ = (fonte_h, str(pid_h), nrm(inv_canon(fonte_h, pid_h, inv_h, ent_h.get("usina") or pid_h)))
                    N_ENT[k_] = max(N_ENT.get(k_, 0), int(n_h))

    def inexistente(fonte, pid, inv, string):
        """O número da string passa das entradas que o inversor manda (inv = o nome do cadastro)."""
        n_ = N_ENT.get((fonte, str(pid), nrm(inv)))
        m_ = re.search(r"\d+", str(string))
        return bool(n_ and m_ and int(m_.group()) > n_)

    vida, massa_hist = set(), {}
    for dia_h, fontes_h in str_store.items():
        for fonte_h, usinas_h in fontes_h.items():
            c_ = Counter(e.get("voltou") for u_ in usinas_h.values() for e in u_.get("eventos") or [] if e.get("voltou"))
            if c_ and max(c_.values()) >= 100:
                massa_hist[(dia_h, fonte_h)] = max(c_.items(), key=lambda kv: kv[1])[0]
    for dia_h, fontes_h in str_store.items():
        for fonte_h, usinas_h in fontes_h.items():
            for pid_h, ent_h in usinas_h.items():
                for e in ent_h.get("eventos") or []:
                    if e.get("voltou") and massa_hist.get((dia_h, fonte_h)) != e["voltou"]:
                        vida.add(chave_ch(fonte_h, pid_h, inv_canon(fonte_h, pid_h, e.get("inversor"), ent_h.get("usina") or pid_h),
                                          e.get("string")))
    curva_inv, zero_dias, nome_ch = {}, Counter(), {}   # (fonte, pid, inv) → {dias de curva, máx de vivas}; canal → dias zerado

    def le_curva(fonte, pid, usina, res):
        for inv, n in (res.get("vivas") or {}).items():
            inv = inv_canon(fonte, pid, inv, usina)
            c_ = curva_inv.setdefault((fonte, str(pid), nrm(inv)), {"dias": 0, "vivas": 0, "usina": usina, "inv": inv})
            c_["dias"] += 1
            c_["vivas"] = max(c_["vivas"], n)
        for r in res.get("mortas") or []:
            k = chave_ch(fonte, pid, inv_canon(fonte, pid, r["inversor"], usina), r["string"])
            nome_ch.setdefault(k, str(r["string"]))
            if r.get("sempre_zero") is True:
                zero_dias[k] += 1
            elif r.get("sempre_zero") is False:
                vida.add(k)                      # leu alguma coisa: é string (morta, talvez), não entrada vazia

    dias_vivas = set()                   # dia com alguma curva avaliada com as vivas: sem isso a entrada vazia não saiu
    for dia_h, fontes_h in mortas_curva.items():
        for fonte_h, usinas_h in fontes_h.items():
            for pid_h, ent_h in usinas_h.items():
                if ent_h.get("vivas"):
                    dias_vivas.add(dia_h)
                if fonte_h in FONTE_BACKFILL_FORA_DA_VAZIA and ent_h.get("origem") == "backfill":
                    continue                     # ver FONTE_BACKFILL_FORA_DA_VAZIA
                le_curva(fonte_h, pid_h, ent_h.get("usina") or pid_h, ent_h)
    for dia_h, lst in dias_2c.items():
        for u, usina, res in lst:
            le_curva("owen", u, usina, res)       # o 2C sempre tem as vivas (a curva do dia inteiro): não conta nos dias
    VAZIAS, vazias_info = set(), []
    for k, n_zero in zero_dias.items():
        ci = curva_inv.get(k[:3])
        if not ci or n_zero < ci["dias"] or k in vida:
            continue
        if inexistente(k[0], k[1], ci["inv"], nome_ch.get(k, k[3])):
            continue                             # vai para as inexistentes (add_seg): uma lista só
        esp = cad_inv(ci["usina"], ci["inv"])[1]
        if esp and ci["vivas"] >= esp:
            VAZIAS.add(k)
            vazias_info.append({"fonte": k[0], "plant_id": k[1], "usina": canon(ci["usina"]), "inversor": ci["inv"],
                                "string": nome_ch.get(k, k[3]), "esperadas": esp, "vivas": ci["vivas"],
                                "dias_curva": ci["dias"]})
    vazias_info.sort(key=lambda v: (v["usina"], v["inversor"], v["string"]))

    # 1) SEGMENTOS de dia por string — da régua nova (curva) quando a usina-dia tem, senão das quedas gravadas
    segs = defaultdict(list)          # (fonte, pid, usina, inversor, string) → [segmento]

    def add_seg(fonte, pid, usina, dia, inv_raw, string, a, voltou, metodo, ini_prod=None, flag=None):
        b = voltou if voltou is not None else fim_janela(dia)
        x, y, mins, sem_estado = intersec(a, b, usina, dia)
        if sem_estado:
            str_q["usina sem estado (janela fixa)"] += 1
        m_id = re.fullmatch(r"(?:INV-)?(\d{4,})", str(inv_raw)) if fonte == "pv" else None
        inv_disp = str(inv_raw)
        if m_id:              # o detector gravou o idefinversor no lugar do nome (plant_devices falhou na hora)
            inv_disp = PV_INV_NOME.get((str(pid), m_id.group(1)), inv_disp)
            str_q["inversor gravado pelo id → nome pelo de-para" if inv_disp != str(inv_raw) else
                  "inversor gravado pelo id sem nome no de-para"] += 1
        tv = trancada(fonte, pid, inv_raw, string)
        if tv:
            str_q["trancada: fora"] += 1
            return
        inv = inv_cadastro(usina, inv_nome(inv_disp))
        if fonte in FONTE_ENTRADAS_DO_REGISTRO and inexistente(fonte, pid, inv, string):
            str_q["entrada que o inversor não manda: fora"] += 1
            inexist.setdefault(chave_ch(fonte, pid, inv, string), {
                "fonte": fonte, "plant_id": str(pid), "usina": canon(usina), "inversor": inv, "string": str(string),
                "entradas": N_ENT.get((fonte, str(pid), nrm(inv)))})
            return
        if chave_ch(fonte, pid, inv, string) in VAZIAS:
            str_q["entrada vazia: fora"] += 1
            return
        flags = {flag} if flag else set()
        if tv is None:                # a usina tem trava e o de-para não diz qual inversor é: fica, mas avisada
            str_q["trava não conferida (sem de-para)"] += 1
            flags.add("trava não conferida (sem de-para)")
        if metodo == "store" and (dia, fonte) in parcial and voltou is None:
            flags.add("captura parcial")          # a queda "aberta" pode ser só a foto que parou
        if metodo == "store" and voltou is not None and massa.get((dia, fonte)) == _fmt(voltou):
            flags.add("retorno em massa (buraco de telemetria)")
        kwp_str, y_, perda, perda_nom = perda_seg(usina, inv, dia, x, y, flags)
        segs[(fonte, str(pid), canon(usina), inv, str(string))].append(
            {"dia": dia, "a": a, "voltou": voltou, "x": x, "y": y, "mins": mins, "kwp_str": kwp_str, "yield": y_,
             "perda": perda, "perda_nom": perda_nom, "flags": flags, "metodo": metodo, "ini_prod": ini_prod})

    for dia in dias:
        for fonte, usinas in str_store[dia].items():
            if fonte == "owen":
                continue
            curva_dia = (mortas_curva.get(dia) or {}).get(fonte) or {}
            for pid, ent in usinas.items():
                if pid in curva_dia:
                    continue              # esta usina-dia tem a régua nova sobre a curva
                usina = ent.get("usina") or pid
                for e in ent.get("eventos") or []:
                    str_q["quedas gravadas lidas"] += 1
                    a = _hm(e.get("caiu"))
                    if a is None:
                        continue
                    add_seg(fonte, pid, usina, dia, e.get("inversor"), e.get("string"), a,
                            _hm(e.get("voltou")) if e.get("voltou") else None, "store")
    def sombra_amanheceu(fonte, pid, dia, x):
        """A sombra que terminou o dia morta (voltou None) e cuja string amanhece morta no dia registrado seguinte."""
        if x.get("voltou") is not None:
            return False
        pr = min((d for d in registro[(fonte, pid)] if d > dia), default=None)
        nx = ((mortas_curva.get(pr) or {}).get(fonte) or {}).get(pid) if pr else None
        for m in (nx or {}).get("mortas") or []:
            if m.get("inversor") == x.get("inversor") and m.get("string") == x.get("string"):
                a, ip = _hm(m.get("saiu")), _hm(m.get("ini_producao"))
                if a is not None and (a <= DESPERTAR or (ip is not None and a - ip <= MORTA_DESDE_PRODUCAO)):
                    return True
        return False

    sombra_falha = set()
    for dia, fontes in mortas_curva.items():
        if not (ini <= dia <= fim):
            continue
        for fonte, usinas in fontes.items():
            for pid, ent in usinas.items():
                for r in ent.get("mortas") or []:
                    for sa, sv in r.get("trechos") or []:
                        str_q["trechos da régua nova (curva)"] += 1
                        add_seg(fonte, pid, ent.get("usina") or pid, dia, r["inversor"], r["string"], _hm(sa),
                                _hm(sv) if sv else None, "curva", ini_prod=_hm(r.get("ini_producao")))
                for x in ent.get("sombras") or []:
                    if sombra_amanheceu(fonte, pid, dia, x):
                        str_q["sombra que amanheceu morta: é falha"] += 1
                        sombra_falha.add((fonte, str(pid), dia, x.get("inversor"), x.get("string"), x.get("saiu")))
                        add_seg(fonte, pid, ent.get("usina") or pid, dia, x["inversor"], x["string"], _hm(x["saiu"]),
                                None, "curva", flag=FLAG_DEVAGAR)
    # 2C: a régua nova já rodou acima (dias_2c), com a curva da API PV
    for dia, lst in dias_2c.items():
        for u, usina, res in lst:
            dias_fonte["owen"].add(dia)
            registro[("owen", u)].add(dia)
            for r in res["mortas"]:
                for sa, sv in r["trechos"]:
                    str_q["trechos da régua nova (curva)"] += 1
                    add_seg("owen", u, usina, dia, r["inversor"], r["string"], _hm(sa), _hm(sv) if sv else None, "curva",
                            ini_prod=_hm(r.get("ini_producao")))

    # 2) EPISÓDIOS por string: aberto no fim do dia continua na próxima varredura da usina se a string amanhece
    #    zerada (caiu até 07:30). Na varredura seguinte sem ela zerada ao amanhecer = voltou de madrugada; com a usina
    #    dias fora do store = voltou entre as varreduras. Sem nenhuma notícia depois = EM ABERTO (pedido de 24/09: o dia
    #    acabou com a string nula, então continua aberta até vir informação). Dias sem varredura com a string zerada
    #    dos dois lados entram como zerados, estimados e avisados.
    def prox_registro(fonte, pid, d_ant):
        return min((x for x in registro[(fonte, pid)] if x > d_ant), default=None)

    def seg_inferido(key, g):
        fonte, pid, usina, inv, string = key
        x, y, mins, _ = intersec(JAN_INI, fim_janela(g), usina, g)
        flags = {"dias sem varredura estimados"}
        kwp_str, y_, perda, perda_nom = perda_seg(usina, inv, g, x, y, flags)
        return {"dia": g, "a": x, "voltou": None, "x": x, "y": y, "mins": mins, "kwp_str": kwp_str, "yield": y_,
                "perda": perda, "perda_nom": perda_nom, "flags": flags, "inferido": True, "metodo": "inferido"}

    str_ep, aceitos = [], []

    def fecha_str(ep, fim_txt, motivo, extra=None):
        fonte, pid, usina, inv, string = ep["key"]
        mins = sum(s_["mins"] for s_ in ep["segs"])
        if mins <= 0:
            str_q["descartado: fora do período solar"] += 1
            return
        if mins < STR_MIN_MIN:
            str_q["descartado: menos de 2 h seguidas sem corrente"] += 1
            return
        str_q["episódio: " + motivo] += 1
        flags = set().union(*(s_["flags"] for s_ in ep["segs"]))
        if extra:
            flags.add(extra)
        s0 = ep["segs"][0]
        inf = [s_ for s_ in ep["segs"] if s_.get("inferido")]
        metodos = {s_["metodo"] for s_ in ep["segs"] if s_["metodo"] != "inferido"}
        chave = chave_str(fonte, pid, inv, string, s0["dia"])
        destino = str_desc if chave in desc_str else str_ep
        destino.append({"chave": chave, "fonte": fonte, "plant_id": pid, "cliente": cliente(usina), "usina": usina,
                       "inversor": inv, "string": string,
                       "inicio": f"{s0['dia']} {_fmt(s0['a'])}", "fim": fim_txt, "fim_motivo": motivo,
                       "d0": s0["dia"], "d1": ep["segs"][-1]["dia"], "dias": len(ep["segs"]), "dias_inferidos": len(inf),
                       "h_sol": round(mins / 60, 2),
                       "perda_kwh": round(sum(s_["perda"] for s_ in ep["segs"]), 1),
                       "perda_inferida_kwh": round(sum(s_["perda"] for s_ in inf), 1),
                       "perda_nominal_kwh": round(sum(s_["perda_nom"] for s_ in ep["segs"]), 1),
                       "kwp_string": round(next((s_["kwp_str"] for s_ in ep["segs"] if s_["kwp_str"]), 0) or 0, 2),
                       "metodo": "curva" if metodos == {"curva"} else ("quedas gravadas" if metodos == {"store"} else "misto"),
                       "flags": sorted(flags)})
        if destino is str_desc:
            str_q["desconsiderada pelo analista"] += 1
            return                                   # fora da visão por inversor × dia e dos totais
        aceitos.append(ep)

    def encerra_str(ep):
        """Como termina um episódio aberto que não continuou no segmento seguinte (ou não tem segmento seguinte)."""
        fonte, pid, usina, inv, string = ep["key"]
        d_ant = ep["segs"][-1]["dia"]
        prox = _prox(d_ant)
        pr = prox_registro(fonte, pid, d_ant)            # pode ser dia depois do período: só diz se voltou
        if pr is None:
            fecha_str(ep, None, "em aberto", None if d_ant >= ult_str else f"sem registro desde {d_ant[8:10]}/{d_ant[5:7]}")
            return
        if pr > fim and (ep["key"], pr) in wake_depois:
            fecha_str(ep, None, "em aberto")             # seguia zerada na varredura seguinte, já fora do período
            return

        def nascer(dia):
            si, _sf, _est = janela_sol(usina, dia)
            return f"{dia} {_fmt(max(JAN_INI, si or JAN_INI))}"

        if pr == prox:
            fecha_str(ep, nascer(prox), "voltou de madrugada")
        elif fonte in FONTE_VARRE_TUDO and prox in dias_fonte[fonte]:
            fecha_str(ep, nascer(prox), "voltou de madrugada", "retorno inferido (usina sem queda no dia seguinte)")
        else:
            fecha_str(ep, nascer(pr), "voltou entre varreduras",
                      f"usina fora do store de {prox[8:10]}/{prox[5:7]} a {_prox(pr, -1)[8:10]}/{_prox(pr, -1)[5:7]}: "
                      "voltou em algum momento nesse meio")

    def volta_falsa(s_, nx, ep_segs):
        """Voltou e morreu de novo no mesmo dia: antes das 9h com até 2h30 viva e morta de novo antes do meio-dia (pouca
        luz), ou a qualquer hora com até 1 h viva (pisca). Só num episódio que já tem 2 h seguidas (quedas gravadas)."""
        if s_["voltou"] is None or nx is None or nx["dia"] != s_["dia"]:
            return False
        viva = nx["a"] - s_["voltou"]
        manha = s_["voltou"] < MANHA_VOLTA_ATE and viva <= MANHA_VIVA_MAX and nx["a"] <= MANHA_MORRE_ATE
        if not (manha or viva <= PISCA_VIVA_MAX):
            return False
        return max(x["mins"] for x in ep_segs) >= STR_MIN_MIN or nx.get("voltou") is None

    def continua_morta(aberto, s_, pr):
        """Amanheceu sem corrente: o episódio que terminou o dia morto continua no dia registrado seguinte — caiu até
        07:30; ou morta desde que o inversor começou a gerar; ou, sem essa hora, caiu até as 10:30."""
        if s_["dia"] != pr or aberto["segs"][-1]["voltou"] is not None:
            return False
        if s_["a"] <= DESPERTAR:
            return True
        if s_.get("ini_prod") is not None:
            return s_["a"] - s_["ini_prod"] <= MORTA_DESDE_PRODUCAO
        return s_["a"] <= MANHA_SEM_HORA_ATE

    def manha_curta(aberto, s_, pr):
        """Na régua nova a volta da manhã não tem hora: a string gerou do começo da produção até morrer de novo. Dia
        seguinte ao episódio aberto, morreu antes do meio-dia depois de no máximo 2h30 viva = mesmo episódio."""
        return (s_["metodo"] == "curva" and s_["dia"] == pr and s_.get("ini_prod") is not None
                and aberto["segs"][-1]["voltou"] is None and s_["a"] <= MANHA_MORRE_ATE
                and s_["a"] - s_["ini_prod"] <= MANHA_VIVA_MAX)

    for key, lst in segs.items():
        fonte, pid = key[0], key[1]
        lst.sort(key=lambda s_: (s_["dia"], s_["a"]))
        aberto = None
        for i, s_ in enumerate(lst):
            dia = s_["dia"]
            nx = lst[i + 1] if i + 1 < len(lst) else None
            if aberto is not None:
                d_ant = aberto["segs"][-1]["dia"]
                pr = prox_registro(fonte, pid, d_ant)
                amanheceu = dia != d_ant and continua_morta(aberto, s_, pr)
                curta = dia != d_ant and not amanheceu and manha_curta(aberto, s_, pr)
                if dia == d_ant or amanheceu or curta:
                    if dia != d_ant and dia != _prox(d_ant):
                        for g in _dias_entre(_prox(d_ant), _prox(dia, -1)):   # dias sem varredura no meio
                            aberto["segs"].append(seg_inferido(key, g))
                    if curta:
                        s_["flags"].add(FLAG_MANHA)
                    aberto["segs"].append(s_)                  # amanheceu zerada: mesmo episódio
                    if s_["voltou"] is not None:
                        if volta_falsa(s_, nx, aberto["segs"]):
                            s_["flags"].add(FLAG_MANHA)        # segue aberto: o próximo trecho é do mesmo dia
                            continue
                        fecha_str(aberto, f"{dia} {_fmt(s_['voltou'])}", "voltou")
                        aberto = None
                    continue
                encerra_str(aberto)                            # o anterior terminou antes deste segmento
                aberto = None
            ep = {"key": key, "segs": [s_]}
            if s_["voltou"] is not None and volta_falsa(s_, nx, [s_]):
                s_["flags"].add(FLAG_MANHA)
                aberto = ep
            elif s_["voltou"] is not None:
                fecha_str(ep, f"{dia} {_fmt(s_['voltou'])}", "voltou")
            else:
                aberto = ep
        if aberto is not None:
            encerra_str(aberto)

    # 3) visão por INVERSOR × DIA (quantidade + strings em texto) — dos mesmos episódios: as duas somam o mesmo kWh
    por_inv = defaultdict(lambda: {"strings": set(), "min": 0, "perda": 0.0, "perda_nom": 0.0, "flags": set(),
                                   "kwp_str": None, "yield": None})
    for ep in aceitos:
        fonte, pid, usina, inv, string = ep["key"]
        for s_ in ep["segs"]:
            if s_["mins"] <= 0:
                continue
            r = por_inv[(s_["dia"], fonte, usina, inv)]
            r["strings"].add(string)
            r["min"] += s_["mins"]
            r["perda"] += s_["perda"]
            r["perda_nom"] += s_["perda_nom"]
            r["flags"] |= s_["flags"]
            r["kwp_str"] = r["kwp_str"] or s_["kwp_str"]
            r["yield"] = r["yield"] or s_["yield"]

    def _ord(s_):
        m = re.search(r"\d+", s_)
        return (int(m.group()) if m else 0, s_)

    str_rows = []
    for (dia, fonte, usina, inv), r in por_inv.items():
        strs = sorted(r["strings"], key=_ord)
        str_rows.append({"dia": dia, "fonte": fonte, "cliente": cliente(usina), "usina": usina, "inversor": inv,
                         "qtd": len(strs), "strings": ", ".join(strs), "h_sol": round(r["min"] / 60, 2),
                         "perda_kwh": round(r["perda"], 1), "perda_nominal_kwh": round(r["perda_nom"], 1),
                         "kwp_string": round(r.get("kwp_str") or 0, 2), "yield": round(r.get("yield") or 0, 2),
                         "flags": sorted(r["flags"])})
    # virada de mês (27/09/2026): o pacote de outubro começa em 01/10, e a string zerada desde 20/09 apareceria como
    # "saiu 01/10 06:10". Quem amanhece zerado no 1º dia e estava em aberto no fim do mês anterior leva o "desde" de lá
    # (abertos_antes, do pacote anterior). A perda segue dentro do mês — o "desde" só conta a história.
    ant_s = {(f_, str(p_), nrm(i_), nrm(s_)): v for (f_, p_, i_, s_), v in ((abertos_antes or {}).get("strings") or {}).items()}
    for e in str_ep:
        a = _hm(e["inicio"][11:16])
        v = ant_s.get((e["fonte"], str(e["plant_id"]), nrm(e["inversor"]), nrm(e["string"])))
        if v and e["d0"] == ini and a is not None and a <= DESPERTAR:
            e["desde"] = v
            e["flags"] = sorted(set(e["flags"]) | {f"vem do mês anterior (desde {v[8:10]}/{v[5:7]} {v[11:16]})"})
    log(f"[falhas] strings: {len(str_ep)} episódios, {len(str_rows)} linhas inversor-dia ({time.time()-t0:.0f}s)")

    # ══ TRACKERS ═════════════════════════════════════════════════════════════════════════════
    dias_t = [x for x in sorted(trk_store) if ini <= x <= fim]
    # o último dia que o registro CLASSIFICOU: às 06:40 ninguém tem leitura suficiente e o parado de ontem segue em
    # aberto sem aviso; às 10h, a usina que ainda não foi classificada hoje leva o aviso de leitura incompleta
    ult_trk = max((x for x in dias_t if any((e or {}).get("classes") is not None for e in (trk_store[x] or {}).values())),
                  default=fim)
    trk_q = Counter()
    serie, nomes = defaultdict(dict), {}
    # SEM COMUNICAÇÃO não é parado (Levi, 01/10/2026: "alguns trackers estão como 'parados' porém ficaram sem
    # comunicação, não quero esses trackers no relatório"). Desde 08/09 o tempo real conta o tracker sem comunicação
    # travado num ângulo como parado (app._trk_promove_semcom) e o registro só guardava "parado". Setembro no PC: 5.597
    # tracker-dias parados de 559 trackers eram sem comunicação (Santa Bárbara I 1.456, TIM100 901, Barretos 710) —
    # 1.065 → 738 MWh. No dia em que ele está sem comunicação o registro não sabe dele: não é parado nem
    # volta — atravessa, como a usina que não leu. A marca vem do registro (`sem_comunicacao`, de 01/10 em diante) ou,
    # antes disso, das fotos da ronda (trk_semcom; ver app._falhas_trk_semcom_hist).
    SC, sc_fora = {}, {}

    def sem_com(dia, pid, ent):
        if ent.get("sem_comunicacao") is not None:
            return {str(t) for t in ent["sem_comunicacao"]}
        hist = (trk_semcom or {}).get(dia)
        if not hist:
            return set()
        us_ = {ent.get("nome") or pid, canon(ent.get("nome") or pid)}
        cand = set(ent.get("classes") or {}) | {str(e.get("tracker")) for e in ent.get("eventos") or []}
        return {t for t in cand if any(chave_semcom(u, t) in hist for u in us_)}

    for dia in dias_t:
        for pid, ent in trk_store[dia].items():
            nomes[pid] = ent.get("nome") or pid
            SC[(pid, dia)] = sem_com(dia, pid, ent)
            cls = ent.get("classes") or {}
            evs = defaultdict(list)
            for ev in ent.get("eventos") or []:
                evs[str(ev["tracker"])].append(ev)
            for trk in set(cls) | set(evs):
                serie[(pid, trk)][dia] = {"cls": (cls.get(trk) or {}).get("status"), "evs": evs.get(trk, []),
                                         "cob": ent.get("cobertura", 0)}
    # frota vista pela plataforma no store inteiro — só para saber se a usina tem trackers (o nº dela NÃO serve de
    # divisor: o store só lista tracker com anomalia; ver o kWp típico abaixo)
    frota_store = defaultdict(set)
    for _dia, _ents in trk_store.items():
        for _pid, _e in _ents.items():
            frota_store[_pid].update((_e.get("classes") or {}).keys())
            frota_store[_pid].update(str(x["tracker"]) for x in (_e.get("eventos") or []))

    def fonte_de(pid):
        if pid.isdigit():
            return "pv" if len(pid) > 5 else "pg"
        return "owen" if len(pid) <= 3 else "sunop"

    def inversor_de(pid, trk):
        return app._bd_trk_lookup(nomes.get(pid, ""), app._trk_id_num(trk))

    def trk_cadastro(usina):
        """Trackers da usina no cadastro: BD_Trackers, senão a Info Geral (0 = não cadastrada)."""
        uc = nrm(canon(usina))
        return len(app.BD_TRK_INV.get(app._nome_base(usina)) or {}) or IG_TRK.get(uc) or IG_TRK.get(nrm(usina)) or 0

    def kwp_cadastro(pid, trk, inversor):
        usina = nomes.get(pid, "")
        usn = app._nome_base(usina)
        kwp_inv, _, _orig = cad_inv(canon(usina), inversor or "")
        n = len((app.INV_TRK.get(usn) or {}).get(nrm(inversor or ""), []) or [])
        if kwp_inv and inversor and n:
            return kwp_inv / n, "inversor ÷ trackers do inversor"
        uc = nrm(canon(usina))
        tot = trk_cadastro(usina)
        origem = "UFV ÷ trackers da usina"
        if not tot and len(frota_store.get(pid) or ()) >= 5:
            tot, origem = len(frota_store[pid]), "UFV ÷ frota vista no store"
        ufv = CAD_UFV.get(uc) or {}
        kwp_u = ufv.get("kwp") or IG_KWP.get(uc) or IG_KWP.get(nrm(usina))
        if kwp_u and tot:
            return kwp_u / tot, origem
        return None, "sem kWp"

    # kWp típico de um tracker MEDIDO no cadastro (kWp do inversor ÷ trackers do inversor). Achado de 24/09: dividir a
    # UFV pelos trackers "vistos no store" inflava ~10× (Guatambu TRK1: 678 kWp e 27 MWh num episódio). Sem contagem
    # de frota no cadastro vale o típico, e kWp acima do teto (P95 medido, no mínimo 2× o típico) também.
    med = sorted(k for k, o in (kwp_cadastro(p_, t_, inversor_de(p_, t_)) for (p_, t_) in serie)
                 if k and o == "inversor ÷ trackers do inversor")
    KWP_TIPICO = med[len(med) // 2] if med else 50.0
    KWP_TETO = max(2 * KWP_TIPICO, med[int(len(med) * 0.95)] if med else 0)

    def kwp_tracker(pid, trk, inversor):
        k, o = kwp_cadastro(pid, trk, inversor)
        if k is None:
            return None, o
        if o == "UFV ÷ frota vista no store":
            trk_q["kWp: frota vista no store → tracker típico"] += 1
            return KWP_TIPICO, f"tracker típico da carteira ({KWP_TIPICO:.0f} kWp)"
        if k > KWP_TETO:
            trk_q["kWp acima do teto → tracker típico"] += 1
            return KWP_TIPICO, f"kWp implausível ({k:.0f}) → típico ({KWP_TIPICO:.0f} kWp)"
        return k, o

    # dia em que a maioria da frota ficou parada (FRAC_FROTA_PARADA): o desvio desse dia não diz se o tracker está no
    # alvo. A frota é o cadastro ou, se maior, a vista no mês — o registro só guarda tracker com anomalia.
    coletiva = set()
    for dia in dias_t:
        for pid, ent in trk_store[dia].items():
            n_par = sum(1 for t_, c in (ent.get("classes") or {}).items()
                        if (c or {}).get("status") == "parado" and t_ not in SC.get((pid, dia), ()))   # sem comunicação não
            if n_par and n_par >= FRAC_FROTA_PARADA * max(trk_cadastro(nomes.get(pid, "")), len(frota_store.get(pid) or ())):
                coletiva.add((pid, dia))

    # crônico = o book da plataforma diz que o tracker já estava parado ANTES do período
    antes = set()
    for _f, _ent in (book or {}).items():
        for r in _ent.get("rows") or []:
            if str(r.get("inicio") or "") < ini and (r.get("aberta") or str(r.get("fim") or "") >= ini):
                antes.add((r.get("usina"), str(r.get("tracker"))))

    trk_rows = []
    for (pid, trk), por_dia in serie.items():
        usina = nomes.get(pid, "")
        usina_c = canon(usina)
        fonte = fonte_de(pid)
        aberto = None

        def fecha(ep, fim_dia, fim_min, motivo, fim_txt=None, extra=None, pid=pid, trk=trk, usina_c=usina_c, fonte=fonte):
            """fim_txt = só a DATA da volta, quando o registro não guarda a hora (voltou num dia que a régua não viu)."""
            inversor = inversor_de(pid, trk)
            kwp_t, orig = kwp_tracker(pid, trk, inversor)
            desv = max([v for v in ep["desvios"] if v is not None], default=None)   # dia de frota parada entra como None
            if desv is not None and desv < 2.0 and not ep.get("coletiva"):
                # "parado" na posição certa o episódio todo, com a frota girando: não é falha e não perde energia.
                # A regra nasceu da Santa Bárbara I (24/09 16:50, 52 trackers com desvio 0,0°) lida como "não se moveram
                # no fim da tarde" — e estava errada: ela tem os 52 parados em 0,0° todo dia desde pelo menos 19/09 (sem
                # comunicação no tempo real); o desvio era 0 porque a frota inteira parou junto. Dia assim não descarta.
                trk_q["descartado: no alvo o episódio todo (desvio < 2°)"] += 1
                return
            fator = (1 - math.cos(math.radians(min(desv, 90)))) if desv is not None else FATOR_TRK_PADRAO
            perda, hs = 0.0, 0.0
            flags = {motivo} if motivo else set()
            if extra:
                flags.add(extra)
            if kwp_t is None:
                flags.add("sem kWp")
            elif orig != "inversor ÷ trackers do inversor":
                flags.add("kWp: " + orig)
            if desv is None:
                flags.add("sem ângulo (fator 25%)")
            if not inversor:
                flags.add("sem inversor no BD_Trackers")
            if ep.get("coletiva"):
                flags.add("maioria da frota parada (sem referência de ângulo)")
            if ep.get("sc_meio") or ep.get("sc_desde"):
                flags.add("sem comunicação em parte do episódio")       # esses dias não contam perda
            for dd, x, y in ep["dias"]:
                mins = max(0, y - x)
                hs += mins / 60
                if kwp_t:
                    y_ = yield_dia(usina_c, dd)
                    if y_ is None:
                        y_ = YIELD_PADRAO
                        flags.add("sem geração no dia (4,5 kWh/kWp)")
                    perda += kwp_t * y_ * (mins / 60) / (h_sol_dia(usina_c, dd) or 12.0) * fator
            if hs * 60 < 30:
                trk_q["descartado: < 30 min na janela solar"] += 1
                return
            chave = chave_trk(fonte, pid, trk, ep["ini_dia"])
            if chave in desc_trk:
                trk_q["desconsiderado pelo analista"] += 1
            (trk_desc if chave in desc_trk else trk_rows).append({
                             "chave": chave, "fonte": fonte, "plant_id": pid, "cliente": cliente(usina_c), "usina": usina_c,
                             "tracker": trk,
                             "inversor": inversor or "", "inicio": f"{ep['ini_dia']} {_fmt(ep['ini_min'])}",
                             "fim": fim_txt or (f"{fim_dia} {_fmt(fim_min)}" if fim_min is not None else None),
                             "h_sol": round(hs, 2), "desvio_pico": desv, "fator": round(fator, 3),
                             "kwp_tracker": round(kwp_t or 0, 2), "perda_kwh": round(perda, 1),
                             "cronico": (usina_c, trk) in antes and ep["ini_dia"] <= ini,
                             "visto_ate": ep["dias"][-1][0], "sem_com_desde": ep.get("sc_fim"),
                             "flags": sorted(flags)})

        def ddmm(d):
            return f"{d[8:10]}/{d[5:7]}"

        for dia in dias_t:
            if ((trk_store.get(dia) or {}).get(pid) or {"classes": {}}).get("classes") is None:
                # o registro leu a usina mas não a classificou (cobertura < 0,5 da janela, ou a régua falhou): não diz
                # nada sobre o tracker — atravessa. MAB100, 28/09, cobertura 0,43: fechava tudo "voltou (hora não
                # registrada)" com 9 parados no tempo real
                continue
            info = por_dia.get(dia)
            if trk in SC.get((pid, dia), ()):
                if info is not None and info["cls"] == "parado":
                    trk_q["sem comunicação no dia: fora"] += 1
                    a_ = sc_fora.setdefault((fonte, pid, trk), {"fonte": fonte, "plant_id": pid, "usina": usina_c,
                                                                 "tracker": trk, "dias": 0, "de": dia, "ate": dia})
                    a_["dias"] += 1
                    a_["ate"] = dia
                if aberto is not None and not aberto.get("sc_desde"):
                    aberto["sc_desde"] = dia
                continue
            col = (pid, dia) in coletiva
            if info is None:
                # a usina tem leitura no dia e o tracker não entrou em classe nenhuma: a régua não o viu parado — ele
                # voltou nesse dia, numa hora que o registro não guarda (MAB200 Tracker 103, 25/09: parado de 05 a
                # 08/09, a tela dizia "voltou 08/09 17:38"; na curva ele voltou em 09/09, entre 16:45 e 17:00)
                u = (trk_store.get(dia) or {}).get(pid) or {}
                if aberto is not None and (u.get("cobertura") or 0) > 0:
                    trk_q["fechado: voltou num dia sem parada (hora não registrada)"] += 1
                    fecha(aberto, None, None, f"voltou em {ddmm(dia)} (hora não registrada)", fim_txt=dia)
                    aberto = None
                continue
            if info["cob"] == 0:
                continue                                  # a usina não leu nada no dia: atravessa (regra da base)
            parado = info["cls"] == "parado"
            evs = sorted(info["evs"], key=lambda e: _hm(e.get("parada")) or 0)
            if aberto is not None and not parado:
                # A RÉGUA DO LEVI: começou parado e no dia seguinte a plataforma o classifica como severo/médio/leve
                # (ou normal) → saiu da visão de parados, nesse dia, em hora que o registro não guarda
                trk_q["fechado: virou " + str(info["cls"] or "normal")] += 1
                fecha(aberto, None, None, "saiu: " + str(info["cls"] or "normal"), fim_txt=dia)
                aberto = None
            if not parado:
                continue
            if not evs:
                # classe "parado" sem evento no dia (amplitude baixa, sem onset achado): o dia inteiro conta parado
                evs = [{"parada": _fmt(JAN_INI), "retorno": None, "desvio": None}]
            evs = [e for e in evs if _hm(e.get("parada")) is not None]
            for i_ev, ev in enumerate(evs):
                a = _hm(ev.get("parada"))
                b = _hm(ev.get("retorno")) if ev.get("retorno") else None
                if b is not None and i_ev == len(evs) - 1:
                    # a classe do DIA é "parado" — a régua do tempo real — e ela só fica assim se o tracker não retomou o
                    # curso: a "volta" do último evento não é volta. Barretos 2, 28/09: leitura que teleporta (172°,
                    # 8·10¹¹°) fechava 21 trackers "voltou a girar 09:10", parados no tempo real
                    trk_q["volta do último evento ignorada: a classe do dia é parado"] += 1
                    b = None
                dv = None if col else ev.get("desvio")
                if aberto is not None:
                    # episódio vindo de trás: a parada da manhã (≤ 09:00) é continuação; se voltou hoje, fecha no retorno
                    if a <= 9 * 60 and b is None:
                        x, y, _m, _ = intersec(a, fim_janela(dia), usina_c, dia)
                        aberto["dias"].append((dia, x, y))
                        aberto["desvios"].append(dv)
                        aberto["coletiva"] = aberto.get("coletiva") or col
                        if aberto.pop("sc_desde", None):         # voltou a comunicar parado: o meio não conta
                            aberto["sc_meio"] = True
                        continue
                    if a <= 9 * 60 and b is not None:
                        x, y, _m, _ = intersec(a, b, usina_c, dia)
                        aberto["dias"].append((dia, x, y))
                        aberto["desvios"].append(dv)
                        aberto["coletiva"] = aberto.get("coletiva") or col
                        if aberto.pop("sc_desde", None):         # voltou a comunicar parado: o meio não conta
                            aberto["sc_meio"] = True
                        trk_q["fechado: voltou a girar"] += 1
                        fecha(aberto, dia, y, None)
                        aberto = None
                        continue
                    # parada nova depois das 09:00: ele se mexeu de manhã (hora não registrada) e parou de novo
                    trk_q["fechado: voltou e parou de novo no mesmo dia"] += 1
                    fecha(aberto, None, None, f"voltou em {ddmm(dia)} e parou de novo às {_fmt(a)}", fim_txt=dia)
                    aberto = None
                x, y, _m, _ = intersec(a, b if b is not None else fim_janela(dia), usina_c, dia)
                ep = {"ini_dia": dia, "ini_min": x, "dias": [(dia, x, y)], "desvios": [dv], "coletiva": col}
                if b is None:
                    aberto = ep
                else:
                    trk_q["fechado: voltou a girar"] += 1
                    fecha(ep, dia, y, None)
        if aberto is not None:
            sc_d = aberto.pop("sc_desde", None)
            if sc_d:
                # parado de verdade até ficar sem comunicação: não voltou (não há notícia) e também não "segue parado" —
                # ninguém sabe; a perda é só a dos dias em que ele comunicava. Sai das contas de em aberto (aba e
                # semanal) pelo `sem_com_desde`; o `visto_ate` é o último dia em que o viram parado (Santa Bárbara I,
                # 21–27/09: 52 trackers sem comunicação a semana toda contavam como parados no relatório semanal)
                trk_q["em aberto: sem comunicação do tracker depois"] += 1
                aberto["sc_fim"] = sc_d
                fecha(aberto, None, None, "em aberto", extra=f"sem comunicação do tracker desde {ddmm(sc_d)}")
            elif aberto["dias"][-1][0] >= ult_trk:
                trk_q["em aberto no fim do período"] += 1
                fecha(aberto, None, None, "em aberto")
            else:
                # a usina não foi classificada depois do último dia parado: sem notícia, segue em aberto (a regra das
                # strings). Leu e não deu para classificar = leitura incompleta; não leu nada = sem dado
                d_ult = aberto["dias"][-1][0]
                leu = any(((trk_store.get(d) or {}).get(pid) or {}).get("cobertura") for d in dias_t if d > d_ult)
                txt = "leitura incompleta da usina" if leu else "sem dado da usina"
                trk_q[f"em aberto: {txt} depois"] += 1
                fecha(aberto, None, None, "em aberto", extra=f"{txt} desde {ddmm(d_ult)}")
    ant_t = {(f_, str(p_), str(t_)): v for (f_, p_, t_), v in ((abertos_antes or {}).get("trackers") or {}).items()}
    for r in trk_rows:
        a = _hm(r["inicio"][11:16])
        v = ant_t.get((r["fonte"], str(r["plant_id"]), str(r["tracker"])))
        if v and r["inicio"][:10] == ini and a is not None and a <= 9 * 60:     # a parada da manhã é continuação
            r["desde"] = v
            r["flags"] = sorted(set(r["flags"]) | {f"vem do mês anterior (desde {v[8:10]}/{v[5:7]} {v[11:16]})"})
    log(f"[falhas] trackers: {len(trk_rows)} episódios ({time.time()-t0:.0f}s)")

    def resumo(rows, chave):
        agg = defaultdict(lambda: {"n": 0, "kwh": 0.0, "h": 0.0})
        for r in rows:
            a = agg[r[chave] or "—"]
            a["n"] += 1
            a["kwh"] += r["perda_kwh"]
            a["h"] += r["h_sol"]
        return sorted(({"k": k, **v} for k, v in agg.items()), key=lambda x: -x["kwh"])

    # SOMBRA (29/09/2026): o trecho que entrou ou saiu em rampa não é falha (falhas.avaliar_dia, MAB100 ST07 em 02 e
    # 12/09, o Fusion mostrava a string boa) — fica listado para quem quiser conferir, fora dos episódios e do kWh
    sombras_info = []
    for dia_s, fontes_s in sorted(mortas_curva.items()):
        if ini <= dia_s <= fim:
            for fonte_s, usinas_s in fontes_s.items():
                for pid_s, ent_s in usinas_s.items():
                    for x in ent_s.get("sombras") or []:
                        if (fonte_s, str(pid_s), dia_s, x.get("inversor"), x.get("string"), x.get("saiu")) in sombra_falha:
                            continue
                        sombras_info.append({"fonte": fonte_s, "plant_id": pid_s, "usina": canon(ent_s.get("usina") or pid_s),
                                             "dia": dia_s, **x})
    for dia_s, lst_s in sorted(dias_2c.items()):
        for u_s, usina_s, res_s in lst_s:
            for x in res_s.get("sombras") or []:
                sombras_info.append({"fonte": "owen", "plant_id": u_s, "usina": canon(usina_s), "dia": dia_s, **x})
    if sombras_info:
        str_q["sombra (entrou ou saiu em rampa): fora"] = len(sombras_info)
    return {"periodo": [ini, fim], "gerado_em": agora.strftime("%Y-%m-%d %H:%M"),
            "strings": {"rows": str_rows, "episodios": str_ep, "desconsideradas": str_desc, "qualidade": dict(str_q),
                        "entradas_vazias": vazias_info,
                        "entradas_inexistentes": sorted(inexist.values(),
                                                        key=lambda v: (v["usina"], v["inversor"], v["string"])),
                        "pv_potencia_fora": pot_fora["usinas-dia"],
                        "sombras": sombras_info,
                        "por_cliente": resumo(str_rows, "cliente")[:12], "por_usina": resumo(str_rows, "usina")[:25],
                        "parcial": sorted(list(x) for x in parcial), "massa": {f"{d_}|{f_}": v for (d_, f_), v in massa.items()},
                        "dias_registrados": sorted(d_ for d_ in set().union(*dias_fonte.values()) if ini <= d_ <= fim)
                        if dias_fonte else [],
                        "dias_com_vivas": sorted(d_ for d_ in dias_vivas if ini <= d_ <= fim)},
            "trackers": {"rows": trk_rows, "desconsideradas": trk_desc, "qualidade": dict(trk_q),
                         "sem_comunicacao": sorted(sc_fora.values(), key=lambda v: (v["usina"], str(v["tracker"]))),
                         "por_cliente": resumo(trk_rows, "cliente")[:12],
                         "por_usina": resumo(trk_rows, "usina")[:25]},
            "regua": {"sol_min_graus": SOL_MIN, "janela": "06–18h ∩ sol ≥ 8° no estado",
                      "janela_strings": "06–18h, 2 h seguidas sem corrente com o inversor gerando (≥ 12% do pico); "
                                        "perda ponderada pela altura do sol",
                      "min_minutos": STR_MIN_MIN, "kwp_trk_tipico": round(KWP_TIPICO, 1), "yield_padrao": YIELD_PADRAO,
                      "fator_tracker": "1 − cos(desvio de pico ao alvo); 25% sem ângulo"}}
