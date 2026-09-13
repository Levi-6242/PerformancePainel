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
    parado_slots_min: int = 4
    abaixo_razao: float = 0.90
    abaixo_dias: int = 3
    trk_excesso_min: float = 10.0
    trk_slots_min: int = 4
    trk_congelado_graus: float = 1.0        # angulo bruto com amplitude <= isto no dia = congelado (travado ou mudo)
    trk_frota_amplitude_min: float = 30.0   # ...desde que a FROTA tenha se mexido pelo menos isto (dia de stow nao conta)
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


def _finito(v) -> float | None:
    """NaN nao vai para o banco: o tipo json do PostgreSQL rejeita 'NaN' (a CI achou na razao POA/GHI de um dia sem GHI)."""
    return float(v) if v is not None and np.isfinite(v) else None


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
    diurno = ((grade.estacao["ghi"] > p.ghi_diurno) | (grade.estacao["poa"] > p.ghi_diurno)).fillna(False)
    evs: list[Evento] = []
    # sensor e cobertura: um evento por dia reprovado, sempre grave — e um dia inteiro sem modelo
    for dd, motivo in gate_res.motivo_dia.items():
        if motivo in ("poa_ghi", "cobertura"):
            sl = idx[(dia == dd).values]
            if len(sl):
                evs.append(Evento("sensor_em_falha" if motivo == "poa_ghi" else "sem_cobertura", None, sl[0], sl[-1] + PASSO, 0.0, "grave",
                                  {"motivo": motivo, "razao_poa_ghi": _finito(gate_res.razao_dia.get(dd))}))
    # inversor parado: CORRIDA de slots com sol parados, de pelo menos 1 h. A regra antiga pedia >= 90 % dos slots
    # com sol do dia e so enxergava apagao de dia inteiro: em 03/09/2026 a CPP100 desligou 8 dos 12 inversores das
    # 10h as 14h locais — 4.962 kWh na cascata — e a tela nao mostrou assinatura nenhuma. Por corrida o ini/fim
    # tambem passa a ser a janela real da parada, que e o que a curva do dia marca em vermelho.
    # (A noite nao quebra nada: sem sol a mascara e falsa, entao corrida nenhuma atravessa a madrugada.)
    for eid in d.parado_flag.columns:
        sol = (esp[eid] > p.parado_esperado_min).fillna(False)
        sol_dia = sol.groupby(dia).sum()
        for a, b in _corridas((d.parado_flag[eid].fillna(False) & sol)):
            n = b - a + 1
            if n < p.parado_slots_min:
                continue
            dd = dia.iloc[a]
            kwh = float(d.parado[eid].iloc[a:b + 1].sum() * H)
            evs.append(Evento("inversor_parado", eid, idx[a], idx[b] + PASSO, kwh, severidade(kwh, float(e_dia.get(dd, 0.0))),
                              {"dia": str(dd), "slots": int(n), "slots_sol": int(sol_dia.get(dd, 0)),
                               "dia_inteiro": bool(sol_dia.get(dd, 0) >= p.min_slots_sol and n >= p.parado_frac_min * float(sol_dia.get(dd, 0)))}))
    # so quem passou o dia parado sai da regra dos pares: uma parada de 1 h nao invalida a comparacao do dia
    parados = {ev.equipamento_id for ev in evs if ev.tipo == "inversor_parado" and ev.detalhe.get("dia_inteiro")}
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
    # tracker CONGELADO: angulo bruto constante o dia inteiro enquanto a frota se mexe. Sete Lagoas, 11/09/2026: TRK51 em
    # 25,8 graus das 9h as 17h com a frota indo de -46 a +55 — TRAVADO (comunica, nao mexe): UM evento no dia, com a perda do
    # dia, em vez de varias corridas de 'fora do alvo'. Araputanga TRK5: 0,0 fixo e aComm=1 na PV Plataforma — sensor MUDO,
    # o zero nao e angulo e a perda e incerta. A amplitude da FROTA e a guarda: dia de stow (vento/nuvem) nao tem travado.
    congelados: set = set()
    if not grade.trk_ang.empty:
        frota_bruta = grade.trk_ang.median(axis=1)
        dias_de_sol = dia[diurno].groupby(dia[diurno]).groups
        for t in d.excesso.columns:
            if t not in grade.trk_ang.columns:
                continue
            for dd, ind in dias_de_sol.items():
                v = grade.trk_ang.loc[ind, t].dropna()
                fr = frota_bruta.loc[ind].dropna()
                if len(v) < p.trk_slots_min or fr.empty or (fr.max() - fr.min()) < p.trk_frota_amplitude_min:
                    continue
                if (v.max() - v.min()) > p.trk_congelado_graus:
                    continue
                ang = float(v.median())
                mudo = abs(ang) < 1e-9
                kwh = float(d.perda_trk[t].loc[ind].sum() * H) if t in d.perda_trk.columns else 0.0
                det = {"angulo": round(ang, 2), "slots": int(len(v))}
                if mudo:
                    det["estimativa"] = "incerta"
                evs.append(Evento("tracker_sem_comunicacao" if mudo else "tracker_travado", t, ind[0], ind[-1] + PASSO, kwh,
                                  severidade(kwh, float(e_dia.get(dd, 0.0))), det))
                congelados.add((t, dd))
    # tracker fora do alvo: excesso > 10 graus por >= 1 h seguida, de dia; NaN (mudo ha mais de 4 h de sol) nao e desvio;
    # o dia em que o tracker esta congelado ja saiu acima e nao se repete aqui
    for t in d.excesso.columns:
        mask = (d.excesso[t] > p.trk_excesso_min) & diurno
        for a, b in _corridas(mask):
            if b - a + 1 < p.trk_slots_min or (t, dia.iloc[a]) in congelados:
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
