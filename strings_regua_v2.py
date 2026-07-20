# -*- coding: utf-8 -*-
"""Régua de STRINGS — classifica a corrente por string em Parado / Ocorrência / Normal a partir da
curva crua. Metodologia dos gabaritos SMP100 + TUP (docs/metodologia-analise-strings.md):

  * referência = MEDIANA das strings-IRMÃS do MESMO inversor no mesmo instante;
  * janela de queda = corrente < 0,5A enquanto a mediana das irmãs > 2,0A, agrupada >= 30 min;
  * Parado (sem recuperação, ~toda a janela de produção) × Ocorrência (queda >=30min COM recuperação);
  * sub do Parado: desconexão TOTAL (zero até em baixa irradiância) × MAU CONTATO (corrente só no
    amanhecer, cai a zero sob carga);
  * Ocorrência: rampa saudável antes/depois -> AMBIENTAL (nuvem), senão FALHA;
  * causa COMPARTILHADA: strings do mesmo inversor com janelas coincidentes.

Função pura, sem estado/IO. Entrada: {inv: {string: [(t_min, corrente_A)]}} (t_min = minuto do dia).
Saída: {(inv,string): {classe, sub, janelas, causa_grupo}, "__resumo__": {...}}."""

CORR_MIN   = 0.5     # corrente abaixo disto = "sem corrente"
IRMA_MIN   = 2.0     # mediana das irmãs acima disto = inversor produzindo (janela de geração)
JAN_MIN    = 30      # duração mínima da janela de queda (min)
GAP_TOL    = 10      # tolera 1 amostra faltando dentro de uma janela (min)
FRAC_PARADO = 0.55   # >= isto da janela de produção em queda -> Parado (senão Ocorrência)
JAN_SOL    = (360, 1080)   # 06:00-18:00
BAIXA_IRR  = (0.4, 3.0)    # mediana das irmãs nesta faixa = baixa irradiância (amanhecer/entardecer)
MAU_CONT_A = 0.15    # corrente real acima disto SÓ em baixa irradiância = mau contato
SADIA_FRAC = 0.5     # fora da queda, corrente >= isto × mediana das irmãs = produção saudável (ambiental)
ONSET_TOL  = 20      # min: janelas com início/fim coincidentes -> mesma causa física
EDGE_TOL   = 15      # min: queda que toca o INÍCIO/FIM da produção do inversor -> assinatura de tracker


def _mediana(v):
    v = sorted(x for x in v if x is not None)
    n = len(v)
    if not n:
        return None
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def _janelas(ts, minlen=JAN_MIN, gap=GAP_TOL):
    """Agrupa minutos contíguos (gap<=isto) em [(ini,fim)] com fim-ini >= minlen."""
    ts = sorted(ts)
    out, i = [], 0
    while i < len(ts):
        j = i
        while j + 1 < len(ts) and ts[j + 1] - ts[j] <= gap:
            j += 1
        if ts[j] - ts[i] >= minlen:
            out.append((ts[i], ts[j]))
        i = j + 1
    return out


def _sub_parado(vs, med, times):
    """desconexao_total × mau_contato: procura corrente real (>MAU_CONT_A) da string em BAIXA
    irradiância (mediana das irmãs na faixa BAIXA_IRR). Achou -> mau contato; nunca -> total."""
    for t in times:
        m = med.get(t)
        if m is not None and BAIXA_IRR[0] <= m <= BAIXA_IRR[1] and (vs.get(t) or 0) > MAU_CONT_A:
            return "mau_contato"
    return "desconexao_total"


def _sub_ocorrencia(vs, med, jan, times):
    """ambiental × falha: se FORA das janelas de queda a string produz saudável (>=SADIA_FRAC da
    mediana das irmãs) na maior parte do tempo -> rampa saudável -> ambiental (nuvem)."""
    dentro = set()
    for (a, b) in jan:
        dentro |= {t for t in times if a <= t <= b}
    ok = tot = 0
    for t in times:
        m = med.get(t)
        if t in dentro or m is None or m <= IRMA_MIN:
            continue
        tot += 1
        if (vs.get(t) or 0) >= SADIA_FRAC * m:
            ok += 1
    return "ambiental" if (tot and ok / tot >= 0.8) else "falha"


def _causa_compartilhada(res):
    """Agrupa strings NÃO-normais do mesmo inversor com janelas coincidentes (mesma causa física)."""
    porinv = {}
    for (inv, sid), r in res.items():
        if inv == "__resumo__" or r["classe"] == "normal" or not r["janelas"]:
            continue
        porinv.setdefault(inv, []).append((sid, r))
    gid = 0
    for inv, itens in porinv.items():
        usado = set()
        for i in range(len(itens)):
            si, ri = itens[i]
            if si in usado:
                continue
            grupo = [(si, ri)]
            ai, bi = ri["janelas"][0][0], ri["janelas"][-1][1]
            for k in range(i + 1, len(itens)):
                sk, rk = itens[k]
                ak, bk = rk["janelas"][0][0], rk["janelas"][-1][1]
                if abs(ai - ak) <= ONSET_TOL and abs(bi - bk) <= ONSET_TOL:
                    grupo.append((sk, rk)); usado.add(sk)
            if len(grupo) >= 2:
                gid += 1
                for s, r in grupo:
                    r["causa_grupo"] = "CAUSA_%d" % gid
                    usado.add(s)


def _val_at(series, t):
    """Interpolação linear da série [(t,v)] em t; None se t está FORA do range observado (dado ausente)."""
    if not series or t < series[0][0] or t > series[-1][0]:
        return None
    lo = None
    for (tt, vv) in series:
        if tt == t:
            return vv
        if tt > t:
            if lo is None:
                return None
            t0, v0 = lo
            return v0 + (vv - v0) * (t - t0) / (tt - t0)
        lo = (tt, vv)
    return None


GRID = 10   # grade de reamostragem (min) — alinha dados ESCALONADOS (SunOp reporta cada string em minuto diferente)


def _strings_regua(curva):
    res = {}
    grid = list(range(JAN_SOL[0], JAN_SOL[1] + 1, GRID))
    for inv, strs in curva.items():
        ser = {sid: sorted(pts) for sid, pts in strs.items()}
        g = {sid: {t: _val_at(ser[sid], t) for t in grid} for sid in strs}     # reamostrado na grade
        med = {t: _mediana([g[sid][t] for sid in strs if g[sid][t] is not None]) for t in grid}
        gen = [t for t in grid if (med.get(t) or 0) > IRMA_MIN]                 # inversor produzindo
        gen_span = (gen[-1] - gen[0]) if len(gen) >= 2 else 0
        for sid in strs:
            # queda = a string TEM leitura (interp) < CORR_MIN enquanto as irmãs produzem. Sem leitura
            # (None, fora do range) NÃO conta como queda — dado ausente ≠ corrente zero (bug do escalonado).
            drop = [t for t in gen if g[sid][t] is not None and g[sid][t] < CORR_MIN]
            jan = _janelas(drop, gap=GRID + 5)
            drop_min = sum(b - a for a, b in jan)
            frac = (drop_min / gen_span) if gen_span else 0.0
            if not jan:
                classe, sub = "normal", None
            elif frac >= FRAC_PARADO:
                classe, sub = "parado", _sub_parado(g[sid], med, grid)
            elif gen and jan[-1][1] >= gen[-1] - EDGE_TOL and jan[0][0] > gen[0] + EDGE_TOL:
                # cai a 0 ANTES das irmãs e NÃO volta (parada precoce, entardecer) enquanto produziu de
                # manhã -> declínio cosseno de ângulo travado. Assinatura de TRACKER, não falha elétrica.
                # (Confirmação DEFINITIVA = cruzar c/ a régua de trackers — o gabarito Sete Lagoas pede isso.)
                classe, sub = "tracker", "vespertino"
            else:
                # queda no MEIO com recuperação -> ambiental (nuvem) / falha elétrica temporária.
                # A "partida atrasada" matinal (Sete Lagoas ST_11) cai aqui como ambiental: da string só
                # não dá p/ separar de um dip de nuvem no amanhecer — precisa do ângulo do tracker.
                classe, sub = "ocorrencia", _sub_ocorrencia(g[sid], med, jan, grid)
            res[(inv, sid)] = {"inv": inv, "string": sid, "classe": classe, "sub": sub,
                               "janelas": jan, "drop_min": drop_min, "causa_grupo": None}
    _causa_compartilhada(res)
    p = o = t = n = 0
    for r in res.values():
        p += r["classe"] == "parado"; o += r["classe"] == "ocorrencia"
        t += r["classe"] == "tracker"; n += r["classe"] == "normal"
    res["__resumo__"] = {"parado": p, "ocorrencia": o, "tracker": t, "normal": n}
    return res


# ----------------------------------------------------------------- harness
def _min(hhmm):
    import re
    m = re.search(r"(\d{1,2}):(\d{2})", str(hhmm))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _parse_csv(path):
    import csv
    curva = {}
    with open(path, encoding="utf-8") as f:
        r = csv.reader(f); next(r, None)
        for row in r:
            if len(row) < 4:
                continue
            inv, sid, hhmm, v = row
            t = _min(hhmm)
            try:
                v = float(v)
            except Exception:
                continue
            if t is not None:
                curva.setdefault(inv, {}).setdefault(sid, []).append((t, v))
    return curva


if __name__ == "__main__":
    import glob
    import os
    FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "fixtures", "strings")
    for raw in sorted(glob.glob(FIX + "/*.raw.csv")):
        base = os.path.basename(raw)[:-8]
        res = _strings_regua(_parse_csv(raw))
        resumo = res.pop("__resumo__")
        print("=" * 90)
        print(base, "->", resumo)
        for (inv, sid), r in sorted(res.items()):
            if r["classe"] != "normal":
                jj = ", ".join("%02d:%02d-%02d:%02d" % (a // 60, a % 60, b // 60, b % 60) for a, b in r["janelas"])
                print("   %-14s %-8s %-11s %-16s causa=%s  [%s]" %
                      (inv, sid, r["classe"], r["sub"] or "", r["causa_grupo"], jj))
