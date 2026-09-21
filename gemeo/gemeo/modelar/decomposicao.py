# gemeo/gemeo/modelar/decomposicao.py
"""Decomposicao do delta (esperado - medido) por inversor e instante em quatro parcelas com nome:
parado | tracker | string | residuo. Invariantes que os testes cobram: as parcelas somam o delta onde ha
dado; parado exclui as outras; NaN nunca vira perda; tracker sem inversor no alias vai para a usina."""
from __future__ import annotations
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pvlib

from gemeo.modelar.grade import Grade


@dataclass(frozen=True)
class ParamsDecomp:
    parado_medido_max: float = 1.0      # kW: abaixo disto o inversor esta parado...
    parado_esperado_min: float = 20.0   # ...desde que o modelo esperasse mais do que isto
    excesso_min_graus: float = 5.0      # abaixo disto o desvio do tracker e ruido (TRK_DISP_LEVE da plataforma)
    trk_mudo_slots: int = 16            # tracker mudo fica no ultimo angulo por ate 4 h DE SOL (Levi, 12/09/2026); alem disso e dado ausente
    trk_grupo_min: int = 3              # referencia = mediana do grupo do inversor quando ha pelo menos este tanto de trackers com dado no slot
    trk_grupo_desvio_max: float = 12.0  # ...e so se essa mediana esta a ate isto da frota: grupo inteiro longe da frota e anomalia, nao backtracking
    str_zero_a: float = 0.1
    str_viva_a: float = 0.5
    str_instalada_a: float = 1.0
    ghi_min_fdir: float = 50.0
    f_direta_fixa: float | None = None  # testes e usinas sem lat/lon: fracao direta constante em vez de Erbs
    # CLIPPING (17/09/2026): o esperado sai do PVWatts sobre a POA medida, e o PVWatts nao sabe do
    # limite AC do inversor. Em usina sobredimensionada o modelo espera mais do que o equipamento
    # entrega e isso caia todo no RESIDUO, como perda inexplicada. Nao e perda nova — e a parte do
    # residuo em que o inversor esta no proprio teto. Decisao do Levi: NAO conta como perda evitavel
    # (e de projeto, nao de operacao), por isso e parcela propria e separada.
    clipping_ligado: bool = True
    clip_teto_tol: float = 0.02      # esta "no teto" quem chega a 98% do maior medido do periodo
    clip_min_slots: int = 4          # menos que isto no teto e ruido, nao patamar
    clip_teto_min_kw: float = 5.0    # teto irrisorio = inversor morto ou quase; nao e clipping


@dataclass
class Decomposicao:
    delta: pd.DataFrame
    parado: pd.DataFrame
    tracker: pd.DataFrame
    string: pd.DataFrame
    clipping: pd.DataFrame
    residuo: pd.DataFrame
    ok: pd.DataFrame
    parado_flag: pd.DataFrame
    viva: pd.DataFrame
    zeradas: pd.DataFrame
    excesso: pd.DataFrame
    perda_trk: pd.DataFrame
    instaladas: dict[int, list[int]] = field(default_factory=dict)
    trk_sem_inversor: list[int] = field(default_factory=list)


def f_direta(estacao: pd.DataFrame, indice: pd.DatetimeIndex, lat, lon, p: ParamsDecomp) -> pd.Series:
    """Fracao direta da irradiancia (Erbs sobre o GHI com a posicao solar): e o quanto o desalinhamento de
    um tracker custa. Sem coordenadas nao ha posicao solar — usa 0,6 (ceu claro tipico) ate o cadastro
    (Info Geral) trazer lat/lon."""
    ghi = estacao["ghi"].fillna(0.0)
    if p.f_direta_fixa is not None or lat is None or lon is None:
        fixa = p.f_direta_fixa if p.f_direta_fixa is not None else 0.6
        return pd.Series(fixa, index=indice).where(ghi > p.ghi_min_fdir, 0.0)
    solpos = pvlib.solarposition.get_solarposition(indice, lat, lon)
    erbs = pvlib.irradiance.erbs(ghi.values, solpos["zenith"].values, indice)
    fd = 1.0 - np.asarray(erbs["dhi"], dtype=float) / np.maximum(ghi.values, 1.0)
    return pd.Series(np.clip(fd, 0.0, 1.0), index=indice).where(ghi > p.ghi_min_fdir, 0.0)


def _ffill_de_sol(trk_ang: pd.DataFrame, sol: pd.Series | None, limite: int) -> pd.DataFrame:
    """ffill cujo limite so conta os slots COM sol. Levi (12/09/2026): "a partir de 4 horas sem dados de trackers ja e de se
    alarmar (em horario solar, claro)" — a noite ninguem perde nada, e um tracker que cala as 17 h ainda tem as primeiras
    horas da manha seguinte antes de virar 'dado ausente'. Sem `sol` (testes de unidade) vale o ffill simples."""
    if sol is None:
        return trk_ang.ffill(limit=limite)
    s = sol.reindex(trk_ang.index).fillna(False).astype(int).cumsum()
    marca = pd.DataFrame(np.where(trk_ang.notna(), s.values[:, None], np.nan), index=trk_ang.index, columns=trk_ang.columns).ffill()
    decorrido = marca.rsub(s, axis=0)              # slots de sol desde a ultima leitura; NaN antes da primeira
    return trk_ang.ffill().where(decorrido <= limite)


def excesso_trackers(trk_ang: pd.DataFrame, p: ParamsDecomp, sol: pd.Series | None = None,
                     grupos: dict[int, int] | None = None) -> pd.DataFrame:
    """|angulo - referencia|: zero abaixo do limiar, NaN onde nao ha angulo conhecido. A referencia e a FROTA, nao o alvo do
    proprio tracker — o Tracker 17 da MRO100 (31/08) estava a 0,9 graus do alvo dele e a 35 da frota: o alvo e que estava
    errado (mesma regua 'deteccao por alvo' que matou 119 falsos na plataforma). Quando `grupos` (tracker -> inversor) da
    um grupo com pelo menos `trk_grupo_min` trackers com dado no slot, a referencia e a mediana DESSE grupo: na Tupi Paulista
    (11/09/2026) os dois blocos de 50 trackers fazem backtracking diferente e a frota punia um bloco inteiro por 6 a 8 graus
    ao amanhecer e ao entardecer. Grupo pequeno ou tracker sem inversor continuam contra a frota."""
    if trk_ang.empty:
        return pd.DataFrame(index=trk_ang.index)
    ang = _ffill_de_sol(trk_ang, sol, p.trk_mudo_slots)
    frota = ang.median(axis=1)
    ref = pd.DataFrame({c: frota for c in ang.columns}, index=ang.index)
    por_grupo: dict[int, list] = {}
    for t, g in (grupos or {}).items():
        if t in ang.columns:
            por_grupo.setdefault(g, []).append(t)
    for ts in por_grupo.values():
        if len(ts) < p.trk_grupo_min:
            continue
        bloco = ang[ts]
        med = bloco.median(axis=1)
        # o grupo so e referencia quando esta PERTO da frota (backtracking de bloco: 4 a 8 graus na Tupi). Os cinco trackers
        # do Inversor 2.10 acordaram atrasados JUNTOS em 11/09 e concordavam entre si — medidos contra o proprio grupo, sumiam.
        vale = (bloco.notna().sum(axis=1) >= p.trk_grupo_min) & ((med - frota).abs() <= p.trk_grupo_desvio_max)
        med = med.where(vale, frota)
        for t in ts:
            ref[t] = med
    exc = ang.sub(ref).abs()
    return exc.where((exc > p.excesso_min_graus) | exc.isna(), 0.0)


def trk_inv_da_grade(grade: Grade) -> dict[int, int]:
    """De-para tracker -> inversor pelo `pai_id` do cadastro (alias bd_trackers resolvido no ingest)."""
    return {e: grade.pai[e] for e, t in grade.tipo.items() if t == "tracker" and e in grade.pai}


def decompor(grade: Grade, esp: pd.DataFrame, trk_inv: dict[int, int], p: ParamsDecomp = ParamsDecomp(),
             instaladas: dict[int, list[int]] | None = None) -> Decomposicao:
    idx = grade.indice
    fd = f_direta(grade.estacao, idx, grade.usina.lat, grade.usina.lon, p)
    exc = excesso_trackers(grade.trk_ang, p, sol=fd > 0, grupos=trk_inv)   # 'com sol' = onde ha fracao direta; grupo = inversor
    frac = (1.0 - np.cos(np.radians(exc))).mul(fd, axis=0) if not exc.empty else exc
    invs = list(esp.columns)

    def zeros(cols):
        return pd.DataFrame(0.0, index=idx, columns=list(cols))

    delta = pd.DataFrame(np.nan, index=idx, columns=invs)
    A, B, C, R, zer = zeros(invs), zeros(invs), zeros(invs), zeros(invs), zeros(invs)
    K = zeros(invs)                      # clipping: a fatia do residuo em que o inversor esta no teto
    ok = pd.DataFrame(False, index=idx, columns=invs); par = ok.copy(); viva = ok.copy()
    perda_trk = zeros(frac.columns)
    universo: dict[int, list[int]] = {}
    for eid in invs:
        e = esp[eid]
        m = grade.inv_p[eid] if eid in grade.inv_p.columns else pd.Series(np.nan, index=idx)
        ok_i = e.notna() & m.notna()
        d_i = (e - m).where(ok_i)
        par_i = ok_i & (m < p.parado_medido_max) & (e > p.parado_esperado_min)
        ativo = ok_i & ~par_i
        a = d_i.where(par_i, 0.0)
        meus = [t for t, i in trk_inv.items() if i == eid and t in frac.columns]
        if meus:
            b = (e * frac[meus].mean(axis=1).fillna(0.0)).where(ativo, 0.0)
            for t in meus:
                perda_trk[t] = (e * frac[t] / len(meus)).where(ativo, 0.0).fillna(0.0)
        else:
            b = pd.Series(0.0, index=idx)
        # universo instalado: o job traz os canais com > 1 A nos ultimos 30 dias (uma string morta a janela
        # inteira CONTINUA instalada — e justamente a que interessa); sem esse historico (fixtures), vale a janela
        if instaladas is not None:
            cols = [s for s in instaladas.get(eid, []) if s in grade.str_i.columns]
        else:
            cols = [s for s in grade.str_i.columns if grade.pai.get(s) == eid and grade.str_i[s].max() > p.str_instalada_a]
        universo[eid] = cols
        if cols:
            cur = grade.str_i[cols]
            viva_i = cur.median(axis=1) > p.str_viva_a
            n_zero = (cur < p.str_zero_a).sum(axis=1).where(viva_i, 0)
            c = ((e - b) * n_zero / len(cols)).where(ativo, 0.0)
        else:
            viva_i, n_zero, c = pd.Series(False, index=idx), pd.Series(0, index=idx), pd.Series(0.0, index=idx)
        delta[eid], A[eid], B[eid], C[eid] = d_i, a, b, c
        resto = (d_i - a - b - c).where(ok_i, 0.0)
        # CLIPPING: nao cria perda, RECLASSIFICA o resto. "No teto" = o medido encostou no maior valor
        # que ESTE inversor entregou no periodo, com o modelo esperando mais. Exclui o parado (medido
        # constante em ~0 tambem "encosta no proprio maximo", e seria lido como teto) e exige um
        # patamar de verdade, nao um pico solto.
        if p.clipping_ligado:
            teto = float(m.where(ativo).max()) if ativo.any() else float("nan")
            if np.isfinite(teto) and teto >= p.clip_teto_min_kw:
                no_teto = ativo & (m >= teto * (1.0 - p.clip_teto_tol)) & (resto > 0)
                if int(no_teto.sum()) >= p.clip_min_slots:
                    K[eid] = resto.where(no_teto, 0.0)
        R[eid] = resto - K[eid]
        ok[eid], par[eid], viva[eid], zer[eid] = ok_i, par_i, viva_i, n_zero.astype(float)
    # tracker sem inversor: perda estimada com o esperado MEDIO por inversor e a densidade media de
    # trackers por inversor; nao entra na cascata de nenhum inversor (quebraria 'parcelas somam o delta'),
    # entra em perda_dia do proprio tracker e no contador trackers_sem_inversor da usina
    sem = [t for t in frac.columns if trk_inv.get(t) not in invs]
    if sem:
        e_ref = esp.mean(axis=1)
        n_por_inv = max(1.0, len(frac.columns) / max(1, len(invs)))
        for t in sem:
            perda_trk[t] = (e_ref * frac[t] / n_por_inv).where(e_ref.notna(), 0.0).fillna(0.0)
    return Decomposicao(delta, A, B, C, K, R, ok, par, viva, zer, exc, perda_trk, universo, sem)
