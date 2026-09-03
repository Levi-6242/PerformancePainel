# gemeo/gemeo/modelar/rollup.py
"""Do instante ao dia: `cascata_dia` (usina) e `perda_dia` (equipamento), em kWh, por dia LOCAL. O medido
que entra no delta e o MASCARADO pelos mesmos instantes do esperado (maca com maca — sem isso a razao
saia 1,47 no spike); o contador do dia fica para a meta, que nao tem gate. So DataFrames: quem persiste
e o job."""
from __future__ import annotations
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from gemeo.modelar.decomposicao import Decomposicao
from gemeo.modelar.gate import Resultado
from gemeo.modelar.grade import Grade

H = 0.25
PARCELAS = ("inv_parado", "tracker", "string", "residuo")


@dataclass
class Cascata:
    por_dia: pd.DataFrame        # index dia local; e_esperado, e_medido, delta, 4 parcelas, cobertura_gate, trackers_sem_inversor
    perda_dia: pd.DataFrame      # equipamento_id, dia, parcela, kwh — so kwh != 0
    razao_inv_dia: pd.DataFrame  # index dia, coluna por inversor: medido/esperado nos mesmos instantes


def cascata(grade: Grade, gate_res: Resultado, esp: pd.DataFrame, d: Decomposicao,
            ghi_diurno: float = 50.0, str_zero_a: float = 0.1) -> Cascata:
    idx = grade.indice
    dia = pd.Series(idx.tz_convert(ZoneInfo(grade.usina.tz)).date, index=idx)
    med = grade.inv_p.reindex(columns=esp.columns)
    e_ok, m_ok = esp.where(d.ok), med.where(d.ok)
    e_esp = (e_ok.sum(axis=1, min_count=1).fillna(0.0) * H).groupby(dia).sum()
    e_med = (m_ok.sum(axis=1, min_count=1).fillna(0.0) * H).groupby(dia).sum()
    por_dia = pd.DataFrame({"e_esperado": e_esp, "e_medido": e_med, "delta": e_esp - e_med})
    frames = {"inv_parado": d.parado, "tracker": d.tracker, "string": d.string, "residuo": d.residuo}
    for nome, df in frames.items():
        por_dia[nome] = (df.sum(axis=1) * H).groupby(dia).sum()
    est = grade.estacao
    diurno = ((est["ghi"] > ghi_diurno) | (est["poa"] > ghi_diurno)).fillna(False)   # GHI morto (MTS100, max 0,0) nao zera a cobertura
    ok_diurno = ((gate_res.gate == "ok") & diurno).groupby(dia).sum()
    por_dia["cobertura_gate"] = (ok_diurno / diurno.groupby(dia).sum().replace(0, np.nan)).fillna(0.0)
    por_dia["trackers_sem_inversor"] = len(d.trk_sem_inversor)
    linhas: list[tuple] = []

    def junta(eid, serie_kw, parcela):
        for dd, v in (serie_kw * H).groupby(dia).sum().items():
            if abs(v) > 1e-9:
                linhas.append((int(eid), dd, parcela, float(v)))

    for eid in esp.columns:
        for nome, df in frames.items():
            junta(eid, df[eid], nome)
    for t in d.perda_trk.columns:            # mapeados e sem inversor: a perda e do proprio tracker
        junta(t, d.perda_trk[t], "tracker")
    for eid, cols in d.instaladas.items():   # a parcela do inversor dividida entre as zeradas de cada slot
        if not cols:
            continue
        quota = (d.string[eid] / d.zeradas[eid].replace(0, np.nan)).fillna(0.0)
        for s in cols:
            junta(s, quota.where((grade.str_i[s] < str_zero_a) & d.viva[eid], 0.0), "string")
    perda = pd.DataFrame(linhas, columns=["equipamento_id", "dia", "parcela", "kwh"])
    razao = ((m_ok * H).groupby(dia).sum(min_count=1)) / ((e_ok * H).groupby(dia).sum(min_count=1))
    return Cascata(por_dia, perda, razao)
