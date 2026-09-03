# gemeo/tests/test_modelar_rollup.py
"""Invariantes da cascata na grade sintetica e os vereditos dos spikes (Santarem 1: inversor 106 parado e os
saos entre 0,90 e 1,05; MRO100 31/08: parado ~1,6 MWh e trackers ~0,1 MWh, como o spike registrou)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from golden import G, esperado_de_placa, sem_gate, trk_inv_mro100, veredito  # noqa: E402
from sintetico import grade_sintetica  # noqa: E402
from gemeo.modelar import decomposicao as dc  # noqa: E402
from gemeo.modelar import esperado, rollup  # noqa: E402

P = dc.ParamsDecomp(f_direta_fixa=0.6)
MAPA = {2001: 1001, 2002: 1002}
UNIVERSO = {1001: [3101, 3102, 3103, 3104], 1002: []}
H = 0.25


def _tudo(g):
    params = {i: esperado.ParamsModelo(kwp=277.68, pac0_kw=200.0) for i in g.inv_p.columns}
    r = sem_gate(g)
    esp = esperado.esperado_por_inversor(g, r, params)
    return r, esp, dc.decompor(g, esp, MAPA, P, instaladas=UNIVERSO)


def test_cascata_fecha_por_dia_e_perda_dia_bate_com_a_cascata():
    g = grade_sintetica(dias=2)
    g.inv_p[1001] = 120.0; g.trk_ang[2002] = 50.0; g.str_i[3104] = 0.0
    g.trk_ang[2003] = -10.0   # -10 e nao 50: com dois em 50 a MEDIANA da frota viraria 50 e o 2001 e que ficaria 'fora'
    r, esp, d = _tudo(g)
    c = rollup.cascata(g, r, esp, d)
    assert len(c.por_dia) == 2 and (c.por_dia.delta - (c.por_dia.e_esperado - c.por_dia.e_medido)).abs().max() < 1e-6
    soma = c.por_dia[list(rollup.PARCELAS)].sum(axis=1)
    assert (soma - c.por_dia.delta).abs().max() < 1e-6
    assert c.por_dia.cobertura_gate.between(0, 1).all() and (c.por_dia.trackers_sem_inversor == 1).all()
    inv = c.perda_dia[c.perda_dia.equipamento_id.isin(esp.columns)]
    for parcela in rollup.PARCELAS:
        por_dia = inv[inv.parcela == parcela].groupby("dia").kwh.sum().reindex(c.por_dia.index).fillna(0.0)
        assert (por_dia - c.por_dia[parcela]).abs().max() < 1e-6, parcela
    trk = c.perda_dia[c.perda_dia.equipamento_id == 2003]
    assert len(trk) == 2 and (trk.parcela == "tracker").all() and (trk.kwh > 0).all()
    strs = c.perda_dia[c.perda_dia.equipamento_id == 3104]
    assert (strs.kwh.values - c.por_dia.string.values < 1e-6).all() and (strs.parcela == "string").all()


def test_cascata_nao_inventa_energia_onde_nao_ha_dado():
    g = grade_sintetica(); g.inv_p[1001] = np.nan
    r, esp, d = _tudo(g)
    c = rollup.cascata(g, r, esp, d)
    assert c.por_dia.e_esperado.iloc[0] == pytest.approx(float(esp[1002].sum() * H), rel=1e-6)
    assert c.razao_inv_dia[1001].isna().all() and c.razao_inv_dia[1002].notna().all()


@pytest.mark.parametrize("arq", ["santarem1_2026-08-26.json", "santarem1_2026-09-01.json"])
def test_golden_santarem_inversor_106_parado_e_saos_dentro_da_faixa(arq):
    g, r, esp = esperado_de_placa(G / arq); v = veredito(G / arq)
    d = dc.decompor(g, esp, {}, dc.ParamsDecomp())
    c = rollup.cascata(g, r, esp, d)
    parados = {1000 + int(n) for n in v["inv_parado"]}
    dia = c.por_dia.index[0]
    for eid in parados:
        assert c.perda_dia[(c.perda_dia.equipamento_id == eid) & (c.perda_dia.parcela == "inv_parado")].kwh.sum() > 0
    saos = c.razao_inv_dia.loc[dia].drop(list(parados))
    assert saos.between(v["razao_saos_min"], v["razao_saos_max"]).all(), saos.round(3).to_dict()


def test_golden_mro100_31_08_reproduz_a_cascata_do_spike():
    g, r, esp = esperado_de_placa(G / "mro100_2026-08-31.json")
    d = dc.decompor(g, esp, trk_inv_mro100(g), dc.ParamsDecomp())
    c = rollup.cascata(g, r, esp, d)
    x = c.por_dia.iloc[0]
    # resultado.json do spike 2 em 31/08: inv_parado 1634,9 | tracker 102,6 | string 0,3 | esperado 41068 | medido 38971
    assert x.inv_parado == pytest.approx(1634.9, rel=0.05) and x.tracker == pytest.approx(102.6, rel=0.10)
    assert x.e_medido == pytest.approx(38971.0, rel=0.02) and x.e_esperado == pytest.approx(41068.0, rel=0.03)
    assert x.string < 5.0 and x.cobertura_gate > 0.9
