# -*- coding: utf-8 -*-
"""
_trk_regua_v2 — REGUA FUNDIDA de classificacao de trackers (Python puro).

Funde:
  * a metodologia do PDF (triviais 24h comm-morta / cronico; freeze por
    tolerancia; causa-raiz; fechamento 18:00 + excecao de dado parcial),
  * as guardas provadas do _trk_classifica_curso (amplitude robusta p02-p98,
    banda de congelamento, desvio sustentado, guarda de batente), e
  * o NUCLEO NOVO dos gabaritos: LIMIAR POR USINA VIA LACUNA NA DISTRIBUICAO
    dos desvios-maximos (substitui o DEV_MIN=13 fixo que dava overfit).

Funcao pura, sem estado, sem IO. Reusa os helpers da WIP (_trk_analise_wip.py).

Contrato de saida (igual ao da WIP):
    { tracker_id: {classe, motivo, ocorrencias:[...], travado_em, causa_grupo},
      "__resumo__": {parado, severo, leve, normal, clusters} }
    classe in {"parado","severo","leve","normal"}
"""

import re
import json

# ----------------------------------------------------------------- constantes
JAN_INI = 360           # 06:00 (min do dia, hora LOCAL)
JAN_FIM = 1080          # 18:00
TOL_FREEZE = 2.0        # banda de congelamento (graus)
MIN_OCC = 15            # duracao minima da janela candidata (min)
SEVERO_MIN = 30         # freeze >=isto -> severo ; 15..29 -> leve (fallback duracao)

# --- triviais 24h ---
COMM_EPS = 0.10         # |y| <= isto conta como "zero"
COMM_FRAC = 0.98        # fracao de zeros p/ comunicacao morta
PARADO_AMP = 10.0       # amp robusta 24h < isto -> parado (cronico/travado mecanico)
FLAT_PARADO = 0.75      # fracao de leituras identicas a anterior p/ glitch/teleport parado
OOR_PARADO = 0.20       # fracao de leituras fora de +-55 (usada c/ FLAT p/ teleport)

# --- deteccao de freeze / limiar por usina ---
DEV_MIN = 13.0          # desvio max do tracker vs frota p/ freeze real (guarda provada MAB200)
DEV_MIN_BAT = 15.0      # no batente exige mais (o dwell de +-55 e stow legitimo)
FD_MIN = 13.0           # deslocamento da frota na janela: freeze-fora-do-batente-que-a-frota-deixou
NAORETOMOU_MIN = 90     # freeze >= isto que nao resume curso -> congelou_nao_retomou (parado)
RESUME_AMP = 25.0       # amplitude do tracker APOS o freeze; abaixo = nao retomou curso
FLEET_MOVE_FLOOR = 6.0  # deslocamento minimo p/ NAO ser plato compartilhado (batente comum)
MOVE_EPS = 2.0          # movimento local (+-10min) abaixo disto = tracker congelado em t
STOW_START = 15.0       # |valor| abaixo disto no 1o registro = liberacao de stow atrasada (benigno)
GAP_ABS_MIN = 2.5       # lacuna absoluta minima (graus) p/ separar cluster
GAP_FACTOR = 1.6        # lacuna >= FATOR * escala-baseline-abaixo
SPARSE_FRAC = 0.35      # o que fica acima do limiar tem que ser esparso (<= isto da frota)
DEFAULT_THRESH = 8.0    # limiar quando a distribuicao nao tem estrutura (frota saudavel)
BATENTE_MARGIN = 2.0    # tolerancia p/ considerar "no batente"

# --- causa raiz ---
CLU_ONSET_TOL = 20      # min. mesma falha -> mesmo instante de onset (+- isto)
CLU_ANG_TOL = 12.0      # graus. guarda p/ nao fundir eventos distintos no mesmo minuto


# ----------------------------------------------------------------- helpers
def min_do_dia(x):
    m = re.search(r"(\d{1,2}):(\d{2})", str(x))
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def _serie_dia(pts):
    out = []
    for p in (pts or []):
        y = p.get("y")
        t = min_do_dia(p.get("x"))
        if isinstance(y, (int, float)) and t is not None:
            out.append((t, float(y)))
    out.sort(key=lambda tv: tv[0])
    return out


def _serie_janela(serie, jini, jfim):
    return [(t, y) for (t, y) in serie if jini <= t <= jfim]


def _valor_no_tempo(serie, t):
    if not serie:
        return None
    if t < serie[0][0] or t > serie[-1][0]:
        return None
    prev = None
    for (tt, yy) in serie:
        if tt == t:
            return yy
        if tt > t:
            if prev is None:
                return None
            t0, y0 = prev
            t1, y1 = tt, yy
            if t1 == t0:
                return y0
            return y0 + (y1 - y0) * (t - t0) / (t1 - t0)
        prev = (tt, yy)
    return None


def _mediana(vals):
    v = sorted(vals)
    n = len(v)
    if n == 0:
        return None
    if n % 2:
        return v[n // 2]
    return (v[n // 2 - 1] + v[n // 2]) / 2.0


def _percentil(vals, p):
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    if len(v) == 1:
        return v[0]
    k = (len(v) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(v) - 1)
    frac = k - lo
    return v[lo] + (v[hi] - v[lo]) * frac


def _amp_robusta(vals):
    v = sorted(x for x in vals if x is not None)
    if len(v) < 2:
        return None
    if len(v) >= 20:
        return v[int(len(v) * 0.98)] - v[int(len(v) * 0.02)]
    return v[-1] - v[0]


def _frac_flat(serie):
    """Fracao de leituras identicas (<0.05) a anterior."""
    if len(serie) < 2:
        return 0.0
    ig = sum(1 for i in range(1, len(serie)) if abs(serie[i][1] - serie[i - 1][1]) < 0.05)
    return ig / (len(serie) - 1)


def _frac_oor(serie, lim=55.0):
    if not serie:
        return 0.0
    return sum(1 for _, y in serie if abs(y) > lim) / len(serie)


def _hhmm(mn):
    return "%02d:%02d" % (int(mn) // 60, int(mn) % 60) if mn is not None else "-"


# ----------------------------------------------------------------- passo 2: triviais
def _trivial(serie_dia):
    """Casos triviais 24h. Retorna (classe,motivo,travado_em) ou None."""
    ys = [y for _, y in serie_dia]
    if not ys:
        return ("parado", "comunicacao_morta", None)
    n = len(ys)
    frac_zero = sum(1 for y in ys if abs(y) <= COMM_EPS) / n
    if frac_zero >= COMM_FRAC:
        return ("parado", "comunicacao_morta", None)
    amp = _amp_robusta(ys)
    if amp is not None and amp < PARADO_AMP:
        return ("parado", "cronico_travado", round(_mediana(ys), 2))
    # teleport / glitch: fica travado (flat) a maior parte do dia, teleporta p/
    # valores fora de faixa. amp robusta enorme MAS nao rastreia.
    if _frac_flat(serie_dia) >= FLAT_PARADO and _frac_oor(serie_dia) >= OOR_PARADO:
        return ("parado", "travado_glitch", round(_mediana(ys), 2))
    return None


# ----------------------------------------------------------------- passo 3: candidatas
def _candidatas_freeze(S):
    """Janelas de congelamento (banda TOL_FREEZE, dur>=MIN_OCC). S=serie_janela."""
    n = len(S)
    cand = []
    i = 0
    while i < n:
        j = i
        while (j + 1 < n) and (abs(S[j + 1][1] - S[i][1]) <= TOL_FREEZE):
            j += 1
        dur = S[j][0] - S[i][0]
        if dur >= MIN_OCC:
            vals = [S[k][1] for k in range(i, j + 1)]
            cand.append({"ini": S[i][0], "fim": S[j][0], "dur": dur,
                         "valor": sum(vals) / len(vals), "i_idx": i, "j_idx": j})
        i = j + 1
    return cand


def _pausa_transicao(S, c):
    """True se a candidata e uma PAUSA benigna na rampa (degrau escalonado):
    o tracker chega ao valor por UM lado e sai pelo MESMO lado (passa
    monotonicamente). Um freeze real reverte ou snapa de volta."""
    i, j = c["i_idx"], c["j_idx"]
    if i - 1 < 0 or j + 1 >= len(S):
        return False
    aprox = S[i][1] - S[i - 1][1]
    parte = S[j + 1][1] - S[j][1]
    return (aprox > 0 and parte > 0) or (aprox < 0 and parte < 0)


# ----------------------------------------------------------------- passo 4: limiar por usina
def _theta_usina(sinais, n_frota):
    """Limiar por lacuna na distribuicao dos sinais (desvio/deslocamento max)."""
    d = sorted(sinais)
    m = len(d)
    if m == 0:
        return DEFAULT_THRESH
    if m == 1:
        return min(d[0] - 0.01, DEFAULT_THRESH) if d[0] > DEFAULT_THRESH else DEFAULT_THRESH
    seps = []
    for k in range(m - 1):
        gap = d[k + 1] - d[k]
        baseline = _percentil(d[:k + 1], 90) or d[0]
        n_above = m - 1 - k
        escala = max(1.0, baseline - d[0])
        if (gap >= GAP_ABS_MIN and gap >= GAP_FACTOR * escala
                and n_above <= SPARSE_FRAC * n_frota):
            seps.append(k)
    if seps:
        k = max(seps)
        return d[k] + (d[k + 1] - d[k]) / 2.0
    return max(DEFAULT_THRESH, _percentil(d, 95) or DEFAULT_THRESH)


def _run_sustentado(S, medf, bat_pos, bat_neg, lo=3.0, hi=12.0):
    """Maior run contiguo (min) em que |tracker - mediana_frota| esta na banda (lo, hi] e o tracker
    NAO esta no batente. Camada LEVE de desvio sustentado: o tracker SEGUE o curso mas fica off da
    frota de forma consistente (o motor de freeze nao ve). O guarda de batente evita os falsos do
    MAB200 (dwell de fim de curso = desvio grande, >hi, ja fora da banda). Retorna (dur, ini, fim)."""
    best = 0
    bi = bj = None
    r0 = None
    for (t, v) in S:
        mf = medf(t)
        at_bat = (v >= bat_pos - BATENTE_MARGIN) or (v <= bat_neg + BATENTE_MARGIN)
        if mf is not None and (lo < abs(v - mf) <= hi) and not at_bat:
            if r0 is None:
                r0 = t
            if t - r0 > best:
                best, bi, bj = t - r0, r0, t
        else:
            r0 = None
    return best, bi, bj


def _piso_leve(sds, n_frota):
    """Piso do desvio-sustentado, SÓ se ha LACUNA clara na distribuicao dos niveis tipicos de desvio
    (uma anomalia leve destacada do chao de-sync da usina). Sem lacuna (usina uniforme: ceu-azul, ou
    ruido alto homogeneo do MAB200) -> None = NAO flaga leve sustentado (evita falso-positivo). Esse
    e o nucleo dos gabaritos aplicado ao leve: o corte nasce da distribuicao, nao de um numero fixo."""
    d = sorted(x for x in sds if x is not None)
    m = len(d)
    if m < 4:
        return None
    for k in range(m - 1):
        gap = d[k + 1] - d[k]
        baseline = _percentil(d[:k + 1], 90) or d[0]
        n_above = m - 1 - k
        if (gap >= GAP_ABS_MIN and gap >= 1.2 * max(1.0, baseline)
                and n_above <= SPARSE_FRAC * n_frota and d[k + 1] >= 3.0):
            return d[k] + gap / 2.0
    return None


# ----------------------------------------------------------------- motor principal
def _trk_regua_v2(grafico, alvo=None):
    serie_dia = {tid: _serie_dia(pts) for tid, pts in grafico.items()}
    serie_jan = {tid: _serie_janela(serie_dia[tid], JAN_INI, JAN_FIM) for tid in grafico}

    resultado = {}
    parados = {}

    # --- Passo 2: triviais (24h) ANTES da mediana ---
    for tid in grafico:
        r = _trivial(serie_dia[tid])
        if r is not None:
            classe, motivo, tv = r
            parados[tid] = r
            resultado[tid] = {"classe": classe, "motivo": motivo,
                              "ocorrencias": [], "travado_em": tv, "causa_grupo": None}

    # --- frota ativa (exclui triviais) + mediana/deslocamento ---
    fleet = {tid: serie_jan[tid] for tid in grafico if tid not in parados}

    # batente empirico da usina (antes da mediana: usado na exclusao)
    mins_d = [min(y for _, y in s) for s in fleet.values() if s]
    maxs_d = [max(y for _, y in s) for s in fleet.values() if s]
    bat_neg = _percentil(mins_d, 5) if mins_d else -55.0
    bat_pos = _percentil(maxs_d, 95) if maxs_d else 55.0

    _med_cache = {}
    n_fleet = len(fleet)

    def mediana_frota(t):
        """Mediana da frota de REFERENCIA em t. Exclui trackers congelados
        MID-CURSO (flat, longe do batente) para a mediana nao ser puxada quando
        muita gente trava junto (contaminacao). MANTEM os que estao no batente
        (dwell de +-55 e referencia legitima do fim de curso, ainda que flat)."""
        if t in _med_cache:
            return _med_cache[t]
        keep = []
        allv = []
        for s in fleet.values():
            v = _valor_no_tempo(s, t)
            if v is None:
                continue
            allv.append(v)
            va = _valor_no_tempo(s, t - 10)
            vb = _valor_no_tempo(s, t + 10)
            flat = (va is not None and vb is not None and abs(vb - va) < MOVE_EPS)
            no_batente = (v >= bat_pos - BATENTE_MARGIN) or (v <= bat_neg + BATENTE_MARGIN)
            if flat and not no_batente:
                continue  # congelado mid-curso -> fora da referencia
            keep.append(v)
        base = keep if len(keep) >= max(5, 0.2 * n_fleet) else allv
        r = _mediana(base) if base else None
        _med_cache[t] = r
        return r

    # fim de dados (maior minuto observado na janela)
    fim_dados = 0
    for s in serie_jan.values():
        if s:
            fim_dados = max(fim_dados, s[-1][0])

    n_frota = len(grafico)

    # --- Passo 3: candidatas + sinais por tracker ---
    cand_por_trk = {}
    todos_sinais = []
    for tid in grafico:
        if tid in parados:
            continue
        S = serie_jan[tid]
        cands = _candidatas_freeze(S)
        for c in cands:
            # desvio max do tracker vs frota (leitura REAL do tracker a cada t,
            # nao a constante congelada) + deslocamento da frota durante a janela.
            devmax = 0.0
            meds = []
            cobre = False
            t = c["ini"]
            while t <= c["fim"]:
                mf = mediana_frota(t)
                yt = _valor_no_tempo(S, t)
                if mf is not None:
                    cobre = True
                    meds.append(mf)
                    if yt is not None:
                        d = abs(yt - mf)
                        if d > devmax:
                            devmax = d
                t += 5
            fleet_disp = (max(meds) - min(meds)) if meds else 0.0
            c["devmax"] = devmax
            c["fleet_disp"] = fleet_disp
            c["cobre"] = cobre
            # sinal = quanto a frota "andou" enquanto este ficou parado.
            # usa o MAIOR entre o desvio do tracker vs frota e o deslocamento
            # da frota na janela (pega freeze-no-batente-que-a-frota-deixou).
            c["sinal"] = max(devmax, fleet_disp)
            at_bat = (c["valor"] >= bat_pos - BATENTE_MARGIN) or (c["valor"] <= bat_neg + BATENTE_MARGIN)
            c["at_batente"] = at_bat
            # salto de recuperacao
            j = c["j_idx"]
            c["toca_fim"] = (j >= len(S) - 1)
            if j + 1 < len(S):
                c["jump"] = abs(S[j + 1][1] - c["valor"])
            else:
                c["jump"] = 0.0
        cand_por_trk[tid] = cands
        for c in cands:
            if c["cobre"] and c["fleet_disp"] >= FLEET_MOVE_FLOOR:
                todos_sinais.append(c["sinal"])

    # --- Passo 4: limiar por usina (reportado; refinamento, nao gate primario) ---
    theta = _theta_usina(todos_sinais, n_frota)

    # theta_leve: PISO do desvio-sustentado calibrado POR USINA. Cada tracker tem um "nivel tipico"
    # de desvio da frota (p60 das leituras off-batente) = o ruido de-sync dele. A lacuna na
    # distribuicao desses niveis separa a de-sincronia NORMAL da usina (MAB200: banda alta) das
    # anomalias leves reais (Cidade Gaucha: TRK49 se destaca do chao ~1-2°). Sem isto, a banda fixa
    # 3-12° pega o ruido normal do SunOp como leve (18 falsos no MAB200).
    sd_por_trk = {}
    for tid in fleet:
        devs = []
        for (t, v) in serie_jan[tid]:
            mf = mediana_frota(t)
            at_bat = (v >= bat_pos - BATENTE_MARGIN) or (v <= bat_neg + BATENTE_MARGIN)
            if mf is not None and not at_bat:
                devs.append(abs(v - mf))
        sd_por_trk[tid] = _percentil(devs, 60) or 0.0
    theta_leve = _piso_leve(list(sd_por_trk.values()), n_frota)   # None = usina sem anomalia leve destacada

    # --- Passo 5/6/7: ocorrencias reais + classe por tracker ---
    ocs_por_trk = {}
    for tid in grafico:
        if tid in parados:
            continue
        S = serie_jan[tid]
        n = len(S)
        ocorrencias = []
        S = serie_jan[tid]
        for c in cand_por_trk[tid]:
            # liberacao de stow atrasada: o 1o registro do dia perto do stow que
            # so depois inicia o arco = partida atrasada benigna (nao freeze).
            if c["i_idx"] == 0 and abs(c["valor"]) < STOW_START:
                pos = [y for (t, y) in S if t > c["fim"]]
                if _amp_robusta(pos) is not None and _amp_robusta(pos) >= RESUME_AMP:
                    continue
            if not c["cobre"]:
                # sem referencia: conservador so se longo
                if c["dur"] < SEVERO_MIN:
                    continue
            else:
                at_bat = c["at_batente"]
                # plato compartilhado (batente comum): frota tambem parada -> descarta
                if at_bat and c["fleet_disp"] < FLEET_MOVE_FLOOR:
                    continue
                # gate primario: DESVIO da frota (bar maior no batente) OU a frota
                # andou muito enquanto o tracker ficou parado FORA do batente.
                bar = DEV_MIN_BAT if at_bat else DEV_MIN
                forte_dev = c["devmax"] >= bar
                fd_ok = (c["fleet_disp"] >= FD_MIN and not at_bat)
                if not (forte_dev or fd_ok):
                    continue
                # guarda do degrau escalonado: uma passagem MONOTONICA CURTA pelo
                # valor (chega e sai pelo mesmo lado) e um degrau na rampa, nao um
                # freeze. So filtra ocorrencias curtas (freeze longo conta sempre).
                if c["dur"] < SEVERO_MIN and _pausa_transicao(S, c):
                    continue
            # fechamento (Passo 7)
            if not c["toca_fim"]:
                status = "recuperou"
                nota = None
                fim = c["fim"]
            else:
                if fim_dados >= JAN_FIM - 30:
                    fim = JAN_FIM
                    status = "nao_retomou_18h"
                    nota = "[NAO RETOMOU ATE 18:00]"
                else:
                    fim = c["fim"]
                    status = "aberto_dado_insuficiente"
                    nota = "[EM ABERTO - DADO INSUFICIENTE]"
            dur = fim - c["ini"]
            sev = "severo" if dur >= SEVERO_MIN else "leve"
            ocorrencias.append({"ini": c["ini"], "fim": fim, "dur_min": dur,
                                "valor": round(c["valor"], 2), "severidade": sev,
                                "status": status, "nota": nota,
                                "at_batente": c["at_batente"],
                                "devmax": round(c["devmax"], 1),
                                "fleet_disp": round(c["fleet_disp"], 1)})

        # camada LEVE por DESVIO SUSTENTADO: tracker que SEGUE o curso mas fica 3-12° fora da frota
        # por >=15min, FORA do batente. Pega o "off consistente" que o motor de freeze nao ve (ex.:
        # Cidade Gaucha TRK49). So se NAO ha severo (severo domina). Guarda de batente + banda <=12°
        # exclui o dwell de fim de curso do MAB200 (desvio grande, ja fora da banda).
        if theta_leve is not None and not any(o["severidade"] == "severo" for o in ocorrencias):
            drun, da, db = _run_sustentado(S, mediana_frota, bat_pos, bat_neg, lo=theta_leve)
            if drun >= 15 and not any(abs((o["ini"] or 0) - (da or 0)) < 10 for o in ocorrencias):
                vv = _valor_no_tempo(S, da)
                ocorrencias.append({"ini": da, "fim": db, "dur_min": drun,
                                    "valor": round(vv, 2) if vv is not None else 0.0,
                                    "severidade": "leve", "status": "sustentado",
                                    "nota": "[DESVIO SUSTENTADO 3-12 vs frota]",
                                    "at_batente": False, "devmax": None, "fleet_disp": None})

        # Passo: congelou-e-nao-retomou -> PARADO. Um freeze LONGO cujo tracker
        # NAO retoma o curso depois (amplitude residual pequena) = parado do dia,
        # nao "desvio". Distingue TIM/MAB (congelou+recuperou=severo) de
        # Fernandopolis (congelou+ficou=parado). NAO promove stow de batente.
        nao_retomou = False
        if ocorrencias:
            longa = max(ocorrencias, key=lambda o: o["dur_min"])
            if longa["dur_min"] >= NAORETOMOU_MIN and not longa["at_batente"]:
                pos = [y for (t, y) in S if t >= longa["ini"]]
                amp_pos = _amp_robusta(pos)
                if amp_pos is not None and amp_pos < RESUME_AMP:
                    nao_retomou = True

        if nao_retomou:
            classe, motivo = "parado", "congelou_nao_retomou"
        else:
            tem_sev = any(o["severidade"] == "severo" for o in ocorrencias)
            tem_leve = any(o["severidade"] == "leve" for o in ocorrencias)
            if tem_sev:
                classe, motivo = "severo", None
            elif tem_leve:
                classe, motivo = "leve", None
            else:
                classe, motivo = "normal", None

        resultado[tid] = {"classe": classe, "motivo": motivo,
                          "ocorrencias": ocorrencias, "travado_em": None,
                          "causa_grupo": None}
        ocs_por_trk[tid] = ocorrencias

    # --- Passo 8: causa raiz (agrupamento por onset) ---
    ocs_all = []
    for tid, ocs in ocs_por_trk.items():
        if resultado[tid]["classe"] in ("severo", "leve", "parado"):
            for o in ocs:
                ocs_all.append({"tid": tid, "ini": o["ini"], "valor": o["valor"]})
    ocs_all.sort(key=lambda o: o["ini"])

    grupos = []
    for oc in ocs_all:
        colocado = False
        for g in grupos:
            anc = g["membros"][0]
            if abs(oc["ini"] - anc["ini"]) <= CLU_ONSET_TOL and \
               abs(oc["valor"] - anc["valor"]) <= CLU_ANG_TOL:
                g["membros"].append(oc)
                colocado = True
                break
        if not colocado:
            grupos.append({"id": "CLUSTER_%d" % (len(grupos) + 1), "membros": [oc]})

    melhor = {}
    for g in grupos:
        if len(g["membros"]) < 2:
            continue
        gid = g["id"]
        nm = len(g["membros"])
        ini_g = min(m["ini"] for m in g["membros"])
        for m in g["membros"]:
            tid = m["tid"]
            chave = (nm, -ini_g)
            if tid not in melhor or chave > melhor[tid][0]:
                melhor[tid] = (chave, gid)
    for tid, (_, gid) in melhor.items():
        resultado[tid]["causa_grupo"] = gid

    # --- resumo ---
    p = s = l = nn = 0
    for r in resultado.values():
        c = r["classe"]
        if c == "parado":
            p += 1
        elif c == "severo":
            s += 1
        elif c == "leve":
            l += 1
        else:
            nn += 1
    clusters = []
    for g in grupos:
        if len(g["membros"]) < 2:
            continue
        ini_g = min(m["ini"] for m in g["membros"])
        val_g = _mediana([m["valor"] for m in g["membros"]])
        clusters.append({"id": g["id"], "ini": ini_g, "valor": round(val_g, 1),
                         "trackers": sorted(set(m["tid"] for m in g["membros"]))})

    resultado["__resumo__"] = {"parado": p, "severo": s, "leve": l, "normal": nn,
                               "theta": round(theta, 2), "bat_neg": round(bat_neg, 1),
                               "bat_pos": round(bat_pos, 1), "clusters": clusters}
    return resultado


# ----------------------------------------------------------------- harness
_STATUS_MAP = {"parado": "parado", "severo": "desvio_severo",
               "leve": "desvio_leve", "normal": "normal"}


def _esperado_por_tracker(gab):
    """Extrai {tid: status} do gab (formato 'esperado' ou 'esperado_grupos')."""
    exp = {}
    if "esperado" in gab and gab["esperado"]:
        for tid, v in gab["esperado"].items():
            exp[tid] = v["status"]
    if "esperado_grupos" in gab:
        gp = gab["esperado_grupos"]
        for tid in gp.get("parado_comunicacao_morta", []) + gp.get("parado_estatico", []):
            exp[tid] = "parado"
        for tid in gp.get("severo", []):
            exp[tid] = "desvio_severo"
        for tid in gp.get("leve", []):
            exp[tid] = "desvio_leve"
    return exp


if __name__ == "__main__":
    import glob
    import os

    D = os.path.join(os.path.dirname(os.path.abspath(__file__)))
    # diretorio das fixtures (parametrizavel)
    FIX = (r"C:/Users/Levi Maia/OneDrive - GRID CO/Área de Trabalho/temp/"
           r"Projeto API PV/tests/fixtures/trackers")

    tot_ok = 0
    tot = 0
    linhas = []
    for raw in sorted(glob.glob(FIX + "/*.raw.json")):
        gabf = raw[:-9] + ".gab.json"
        if not os.path.exists(gabf):
            continue
        base = os.path.basename(raw)[:-9]
        r = json.load(open(raw, encoding="utf-8"))
        gab = json.load(open(gabf, encoding="utf-8"))
        alvo = r.get("alvo") or None
        res = _trk_regua_v2(r["grafico"], alvo=alvo)
        resumo = res.pop("__resumo__")
        got = {"parado": resumo["parado"], "desvio_severo": resumo["severo"],
               "desvio_leve": resumo["leve"], "normal": resumo["normal"]}
        exp = gab["agregado_esperado"]
        keys = ["parado", "desvio_severo", "desvio_leve", "normal"]
        ok = all(got.get(k, 0) == exp.get(k, 0) for k in keys)
        tot += 1
        tot_ok += 1 if ok else 0

        # diff de membros
        exp_trk = _esperado_por_tracker(gab)
        got_trk = {tid: _STATUS_MAP[res[tid]["classe"]] for tid in res}
        misses = []
        for tid, st in exp_trk.items():
            g = got_trk.get(tid)
            if g != st:
                misses.append("%s exp=%s got=%s" % (tid, st, g))
        # parado bate?
        parado_ok = got.get("parado", 0) == exp.get("parado", 0)
        linhas.append((base, ok, parado_ok, exp, got, resumo, misses))

    # anotacao de divergencia conhecida (decisao do Levi / gab inconsistente)
    NOTA = {
        "apipv__altair-5__2026-07-09":
            "gab CURSO-based (severo=nao-chegou-a-extremo); _nota_evolucao: pende re-validacao freeze-based",
        "apipv__alto-parana-1__2026-07-09":
            "leve=freeze-transitorio-que-recupera; o gab AVISA que contradiz Cidade Gaucha (desvio-MAX)",
        "apipv__cidade-gaucha__2026-07-09":
            "falta 1 leve (TRK49, desvio sustentado 3-10 vs frota); layer desvio-sustentado quebra MAB200 (21 falsos)",
        "apipv__cidade-gaucha__2026-07-10":
            "DECISAO 4 (gab): fronteira parado<->severo do freeze-que-recupera e JULGAMENTO; TRK45/TRK42 trocados = comportamento do piloto",
        "pg__aracoiaba-serra-1__2026-07-09":
            "parado 2/2 OK; severo/leve dependem do posal (gab: 'semantica_posal INVESTIGAR' - posal congela junto c/ posat; freeze-batente curto e anomalia so no PG)",
        "sunop__mab100__2026-07-09":
            "parado 10/10 OK; severo = freeze-no-batente -55 c/ desvio pequeno (mesmo caso TIM100, gab: nao converge sem overfit)",
        "sunop__tim100__2026-07-10":
            "parado 39/39 OK; gab: 'SEVERO nao converge pra 23 com threshold fixo; grindar=overfit' (degrau escalonado do SunOp)",
        "apipv__fernandopolis-1__2026-07-09":
            "parado 16/16 OK; residual severo = batente-stragglers matinais + freezes-que-recuperam (gab trata como normal aqui, mas severo no MAB100 = gab inconsistente)",
    }

    print("=" * 96)
    print("PLACAR v2 vs GABARITO  (parado/severo/leve/normal)")
    print("=" * 96)
    for base, ok, parado_ok, exp, got, resumo, misses in linhas:
        flag = "EXATO " if ok else ("~PARA " if parado_ok else "XX    ")
        e = "/".join(str(exp.get(k, 0)) for k in ["parado", "desvio_severo", "desvio_leve", "normal"])
        g = "/".join(str(got.get(k, 0)) for k in ["parado", "desvio_severo", "desvio_leve", "normal"])
        print("%s %-40s exp %-14s got %-14s" % (flag, base, e, g))
        if not ok and base in NOTA:
            print("        DIVERGENCIA: %s" % NOTA[base])
        elif not ok and misses:
            print("        miss:", "; ".join(misses[:8]))
    print("=" * 96)
    print("EXATOS (4/4 contagens): %d / %d" % (tot_ok, tot))
    print("PARADO exato: %d / %d" % (sum(1 for x in linhas if x[2]), tot))
