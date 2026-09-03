# gemeo/gemeo/modelar/eventos.py
"""As seis assinaturas viram `evento` (ini, fim, kWh, severidade). Regras da spec §8.5: as de inversor e de
string sao por DIA LOCAL, a de tracker por corrida de slots, as de sensor pelo motivo do gate. Tudo e
recomputavel: a Tarefa 16 grava por (usina, equipamento, tipo, ini) e o mesmo dia rodado duas vezes da o mesmo."""
from __future__ import annotations
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from gemeo.modelar.decomposicao import Decomposicao
from gemeo.modelar.gate import Resultado
from gemeo.modelar.grade import Grade

H = 0.25  # horas por slot da grade de 15 min
PASSO = pd.Timedelta(minutes=15)


@dataclass(frozen=True)
class ParamsEventos:
    parado_frac_min: float = 0.90
    parado_esperado_min: float = 20.0
    min_slots_sol: int = 4
    abaixo_razao: float = 0.90
    abaixo_dias: int = 3
    trk_excesso_min: float = 10.0
    trk_slots_min: int = 4
    ghi_diurno: float = 50.0
    str_zero_a: float = 0.1
    str_slots_min: int = 4


@dataclass
class Evento:
    tipo: str
    equipamento_id: int | None
    ini: pd.Timestamp
    fim: pd.Timestamp | None
    kwh: float
    severidade: str
    detalhe: dict = field(default_factory=dict)


def severidade(kwh: float, e_ref: float) -> str:
    """< 1 % do esperado do periodo = leve; ate 5 % = media; acima = grave. Sem esperado nao ha regua: leve."""
    if e_ref <= 0:
        return "leve"
    f = kwh / e_ref
    return "leve" if f < 0.01 else "media" if f <= 0.05 else "grave"


def _corridas(mask: pd.Series) -> list[tuple[int, int]]:
    """Sequencias contiguas de True, como (posicao inicial, posicao final) inclusivas."""
    out, ini = [], None
    for i, v in enumerate(mask.fillna(False).values):
        if v and ini is None:
            ini = i
        if not v and ini is not None:
            out.append((ini, i - 1)); ini = None
    if ini is not None:
        out.append((ini, len(mask) - 1))
    return out


def detectar(grade: Grade, gate_res: Resultado, esp: pd.DataFrame, d: Decomposicao, p: ParamsEventos = ParamsEventos()) -> list[Evento]:
    idx = grade.indice
    dia = pd.Series(idx.tz_convert(ZoneInfo(grade.usina.tz)).date, index=idx)
    grupos = dia.groupby(dia).groups
    e_dia = (esp.sum(axis=1, min_count=1).fillna(0.0) * H).groupby(dia).sum()
    diurno = (grade.estacao["ghi"] > p.ghi_diurno).fillna(False)
    evs: list[Evento] = []
    # sensor e cobertura: um evento por dia reprovado, sempre grave — e um dia inteiro sem modelo
    for dd, motivo in gate_res.motivo_dia.items():
        if motivo in ("poa_ghi", "cobertura"):
            sl = idx[(dia == dd).values]
            if len(sl):
                evs.append(Evento("sensor_em_falha" if motivo == "poa_ghi" else "sem_cobertura", None, sl[0], sl[-1] + PASSO, 0.0, "grave",
                                  {"motivo": motivo, "razao_poa_ghi": gate_res.razao_dia.get(dd)}))
    # inversor parado: >= 90 % dos slots COM SOL parados. Sobre as 96 celulas do dia a fracao nunca passava
    # de 0,4 (a noite entra no denominador) — foi o erro do primeiro ensaio na MRO100
    for eid in d.parado_flag.columns:
        sol = (esp[eid] > p.parado_esperado_min).fillna(False)
        for dd, rot in grupos.items():
            s, f = sol.loc[rot], d.parado_flag[eid].loc[rot]
            if s.sum() >= p.min_slots_sol and f[s].mean() >= p.parado_frac_min:
                sl = f[f].index
                kwh = float(d.parado[eid].loc[rot].sum() * H)
                evs.append(Evento("inversor_parado", eid, sl[0], sl[-1] + PASSO, kwh, severidade(kwh, float(e_dia.get(dd, 0.0))),
                                  {"dia": str(dd), "slots_sol": int(s.sum())}))
    parados = {ev.equipamento_id for ev in evs if ev.tipo == "inversor_parado"}
    # inversor abaixo dos pares: razao do dia < 0,90 x mediana dos pares, 3 dias seguidos; medido e esperado
    # mascarados pelos MESMOS instantes (sem isso a razao saia 1,47 no spike: maca com laranja)
    med = grade.inv_p.reindex(columns=esp.columns)
    e_ok, m_ok = esp.where(d.ok), med.where(d.ok)
    r_dia = (m_ok * H).groupby(dia).sum(min_count=1) / (e_ok * H).groupby(dia).sum(min_count=1)
    if len(r_dia) >= p.abaixo_dias:
        ult = list(r_dia.index[-p.abaixo_dias:])
        rel = r_dia.div(r_dia.median(axis=1), axis=0)
        for eid in r_dia.columns:
            v = rel.loc[ult, eid]
            if eid in parados or not v.notna().all() or not (v < p.abaixo_razao).all():
                continue
            falta = (e_ok[eid] - m_ok[eid]).clip(lower=0.0)
            kwh = float(falta[dia.isin(ult).values].sum() * H)
            evs.append(Evento("inversor_abaixo", eid, idx[(dia == ult[0]).values][0], None, kwh, severidade(kwh, float(e_dia.reindex(ult).sum())),
                              {"razoes": [round(float(x), 3) for x in v]}))
    # tracker fora do alvo: excesso > 10 graus por >= 1 h seguida, de dia; NaN (mudo ha mais de 6 h) nao e desvio
    for t in d.excesso.columns:
        mask = (d.excesso[t] > p.trk_excesso_min) & diurno
        for a, b in _corridas(mask):
            if b - a + 1 < p.trk_slots_min:
                continue
            kwh = float(d.perda_trk[t].iloc[a:b + 1].sum() * H)
            evs.append(Evento("tracker_fora_alvo", t, idx[a], idx[b] + PASSO, kwh, severidade(kwh, float(e_dia.get(dia.iloc[a], 0.0))),
                              {"excesso_max": float(d.excesso[t].iloc[a:b + 1].max())}))
    # string sem corrente: zerada em TODOS os slots em que o inversor estava vivo — a regua da plataforma;
    # o kWh e a parcela 'string' do inversor dividida entre as zeradas
    for eid, cols in d.instaladas.items():
        if not cols:
            continue
        cur = grade.str_i[cols]
        for dd, rot in grupos.items():
            viva = d.viva[eid].loc[rot]
            if viva.sum() < p.str_slots_min:
                continue
            n_zer = d.zeradas[eid].loc[rot].replace(0, np.nan)
            for s in cols:
                zer = cur[s].loc[rot] < p.str_zero_a
                if zer[viva].all():
                    sl = zer[viva].index
                    kwh = float((d.string[eid].loc[rot] / n_zer).fillna(0.0).sum() * H)
                    evs.append(Evento("string_sem_corrente", s, sl[0], sl[-1] + PASSO, kwh, severidade(kwh, float(e_dia.get(dd, 0.0))),
                                      {"dia": str(dd), "inversor_id": eid}))
    return evs
