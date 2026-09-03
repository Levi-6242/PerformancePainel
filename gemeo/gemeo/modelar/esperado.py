# gemeo/gemeo/modelar/esperado.py
"""Esperado fisico por inversor: PVWatts (pvlib) sobre a POA MEDIDA. Sem transposicao e sem geometria —
o sensor esta no plano dos modulos (POA/GHI ~1,2 nas usinas de tracker, verificado). O esperado tem de
ser fisico: os modelos aprendidos da saida (POT.ESP, AIML da SunOp) igualam o medido e nao veem perda."""
from __future__ import annotations
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pvlib


@dataclass(frozen=True)
class ParamsModelo:
    kwp: float
    pac0_kw: float
    gamma: float = -0.0035
    perdas_fixas: float = 0.14
    eta_inv: float = 0.96
    pac0_inferido: bool = False


def temp_celula(temp_modulo: pd.Series, temp_ar: pd.Series, poa: pd.Series) -> pd.Series:
    """Temperatura de modulo medida; sem ela, ar + 0,03 x POA (NOCT simplificado); sem nada, 25 C."""
    return temp_modulo.where(temp_modulo.notna(), (temp_ar + 0.03 * poa.fillna(0))).fillna(25.0)


def inferir_pac0(p_ac: pd.Series, kw_ac_placa: float | None, kwp: float) -> tuple[float, bool]:
    if kw_ac_placa and kw_ac_placa > 0:
        return float(kw_ac_placa), False
    obs = float(np.nanquantile(p_ac.dropna().values, 0.999)) if p_ac.notna().any() else 0.0
    return (obs, True) if obs > 0 else (float(kwp), True)


def esperado_inversor(poa: pd.Series, temp_cel: pd.Series, p: ParamsModelo) -> pd.Series:
    pdc = pvlib.pvsystem.pvwatts_dc(poa.fillna(0).values, temp_cel.fillna(25).values, p.kwp, p.gamma) * (1 - p.perdas_fixas)
    # pdc0 do PVWatts e a entrada DC em que o inversor atinge a placa (pac0 = eta_nom x pdc0): passar a placa
    # direto limitaria em 0,96 x 200 = 192 kW. E a curva de eficiencia tem um termo -0,0059/zeta, entao um
    # "teto infinito" leva zeta a zero e o AC a ZERO - o teto tem de ser realista, nunca 1e9.
    pac = pvlib.inverter.pvwatts(pdc, p.pac0_kw / p.eta_inv, eta_inv_nom=p.eta_inv)
    return pd.Series(np.asarray(pac, dtype=float), index=poa.index)


def esperado_por_inversor(grade, gate_res, params_por_inv: dict[int, ParamsModelo]) -> pd.DataFrame:
    est = grade.estacao
    tcel = temp_celula(est["temp_modulo"], est["temp_ar"], est["poa"])
    ok = gate_res.gate == "ok"
    cols = {}
    for eid, p in params_por_inv.items():
        cols[eid] = esperado_inversor(est["poa"], tcel, p).where(ok)
    return pd.DataFrame(cols, index=grade.indice)
