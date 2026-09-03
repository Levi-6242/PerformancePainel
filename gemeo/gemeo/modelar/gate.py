# gemeo/gemeo/modelar/gate.py
"""Gate de sensor com DUAS portas. Plausibilidade: faixa e razao POA/GHI (instante e dia). Cobertura:
o instante exige POA; o dia exige horas minimas. O modelo so roda onde o gate diz 'ok'."""
from __future__ import annotations
import datetime as dt
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ParamsGate:
    poa_max: float = 1400.0
    ghi_max: float = 1400.0
    razao_min: float = 0.3
    razao_max: float = 3.0
    ghi_min_razao: float = 100.0
    tolerancia_dia: float = 0.30
    horas_min_dia: float = 8.0
    ghi_dia: float = 50.0


@dataclass
class Resultado:
    gate: pd.Series
    motivo_dia: dict[dt.date, str] = field(default_factory=dict)
    razao_dia: dict[dt.date, float] = field(default_factory=dict)


def avaliar(estacao: pd.DataFrame, referencia_razao: float | None, params: ParamsGate, tz: str) -> Resultado:
    poa, ghi = estacao["poa"], estacao["ghi"]
    dia = pd.Series(estacao.index.tz_convert(ZoneInfo(tz)).date, index=estacao.index)
    gate = pd.Series("ok", index=estacao.index, dtype=object)
    # porta 1a: faixa
    fora = (poa < 0) | (poa > params.poa_max) | (ghi < 0) | (ghi > params.ghi_max)
    gate[fora.fillna(False)] = "plausibilidade"
    # porta 1b: razao POA/GHI no instante e no dia
    razao = (poa / ghi).where(ghi > params.ghi_min_razao)
    ruim_inst = razao.notna() & ~razao.between(params.razao_min, params.razao_max)
    gate[ruim_inst & (gate == "ok")] = "poa_ghi"
    razao_dia = razao.groupby(dia).median()
    ref = referencia_razao if referencia_razao else float(np.nanmedian(razao_dia.values)) if razao_dia.notna().any() else None
    dias_ruins = set(razao_dia[(razao_dia / ref - 1).abs() > params.tolerancia_dia].index) if ref else set()
    gate[dia.isin(dias_ruins) & (gate == "ok")] = "poa_ghi"
    # porta 2: cobertura — instante sem POA nao roda; dia com poucas horas validas nao conta
    gate[poa.isna()] = "cobertura"
    motivo: dict[dt.date, str] = {}
    slots_min = params.horas_min_dia * 4
    for d, idx in dia.groupby(dia).groups.items():
        g = gate.loc[idx]; diurno = (ghi.loc[idx] > params.ghi_dia).sum()
        if d in dias_ruins:
            motivo[d] = "poa_ghi"
        elif (g == "ok").sum() < min(slots_min, max(diurno, 1)) and (g == "ok").sum() < slots_min:
            motivo[d] = "cobertura"
        else:
            motivo[d] = "ok"
        if motivo[d] == "cobertura":
            gate.loc[idx] = gate.loc[idx].where(gate.loc[idx] != "ok", "cobertura")
    return Resultado(gate=gate, motivo_dia=motivo, razao_dia={d: (float(v) if pd.notna(v) else float("nan")) for d, v in razao_dia.items()})
