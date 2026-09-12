# gemeo/tests/test_modelar_decomposicao.py
"""Invariantes (spec §11.1) sobre a grade sintetica e os vereditos dos spikes sobre os golden da MRO100."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent))  # sintetico.py e golden.py moram ao lado dos testes
from golden import G, esperado_de_placa, sem_gate, trk_inv_mro100, veredito  # noqa: E402
from sintetico import grade_sintetica  # noqa: E402
from gemeo.modelar import decomposicao as dc  # noqa: E402
from gemeo.modelar import esperado  # noqa: E402

P = dc.ParamsDecomp(f_direta_fixa=0.6)
MAPA = {2001: 1001, 2002: 1002}
UNIVERSO = {1001: [3101, 3102, 3103, 3104], 1002: []}   # strings instaladas, como o job traz dos 30 dias
H = 0.25


def _esp(g):
    params = {i: esperado.ParamsModelo(kwp=277.68, pac0_kw=200.0) for i in g.inv_p.columns}
    return esperado.esperado_por_inversor(g, sem_gate(g), params)


def test_parcelas_somam_o_delta_onde_ha_dado_e_zeram_onde_nao_ha():
    g = grade_sintetica()
    g.inv_p[1001] = 120.0; g.trk_ang[2002] = 50.0; g.str_i[3104] = 0.0
    g.inv_p.iloc[3, 1] = np.nan
    d = dc.decompor(g, _esp(g), MAPA, P)
    soma = d.parado + d.tracker + d.string + d.residuo
    assert (soma - d.delta).abs().where(d.ok, 0.0).max().max() < 1e-6
    assert soma.where(~d.ok, 0.0).abs().max().max() < 1e-6 and d.delta[1002].isna().sum() == 1


def test_parado_leva_o_delta_inteiro_e_exclui_tracker_e_string():
    g = grade_sintetica()
    g.inv_p[1001] = 0.0; g.trk_ang[2001] = 50.0; g.str_i[3104] = 0.0
    d = dc.decompor(g, _esp(g), MAPA, P)
    assert d.parado_flag[1001].all() and (d.parado[1001] - d.delta[1001]).abs().max() < 1e-6
    assert d.tracker[1001].abs().max() < 1e-6 and d.string[1001].abs().max() < 1e-6 and d.residuo[1001].abs().max() < 1e-6


def test_nan_nunca_vira_perda():
    g = grade_sintetica()
    g.inv_p[1001] = np.nan
    esp = _esp(g); esp[1002] = np.nan
    d = dc.decompor(g, esp, MAPA, P)
    for eid in (1001, 1002):
        assert d.delta[eid].isna().all() and not d.ok[eid].any()
        assert (d.parado[eid].abs() + d.tracker[eid].abs() + d.string[eid].abs() + d.residuo[eid].abs()).max() < 1e-6


def test_tracker_so_conta_acima_de_5_graus_e_vale_cosseno_vezes_fracao_direta():
    g = grade_sintetica()
    g.trk_ang[2002] = 24.0
    assert dc.decompor(g, _esp(g), MAPA, P).tracker[1002].abs().max() < 1e-6
    g.trk_ang[2002] = 50.0
    esp = _esp(g); d = dc.decompor(g, esp, MAPA, P)
    alvo = esp[1002] * 0.6 * (1 - np.cos(np.radians(30.0)))
    assert (d.tracker[1002] - alvo).abs().max() < 1e-6 and (d.excesso[2002] - 30.0).abs().max() < 1e-6


def test_tracker_sem_inversor_vai_para_a_usina():
    g = grade_sintetica()
    g.trk_ang[2003] = 50.0
    d = dc.decompor(g, _esp(g), MAPA, P)
    assert d.trk_sem_inversor == [2003] and d.perda_trk[2003].sum() > 0
    assert d.tracker.abs().max().max() < 1e-6 and d.perda_trk[2001].abs().max() < 1e-6


def test_tracker_mudo_fica_no_ultimo_angulo_por_um_limite_e_depois_e_dado_ausente():
    g = grade_sintetica()
    g.trk_ang[2002] = [50.0, 50.0] + [np.nan] * 6
    d = dc.decompor(g, _esp(g), MAPA, P)
    assert (d.tracker[1002] > 0).all()                       # 4 h de sol (16 slots) cobrem os 8 slots
    d2 = dc.decompor(g, _esp(g), MAPA, dc.ParamsDecomp(f_direta_fixa=0.6, trk_mudo_slots=2))
    assert (d2.tracker[1002].iloc[:4] > 0).all() and d2.tracker[1002].iloc[4:].abs().max() < 1e-6
    assert d2.excesso[2002].iloc[4:].isna().all()             # ausente, nao zero: os eventos precisam saber


def test_string_zerada_com_inversor_vivo_e_a_fracao_das_instaladas():
    g = grade_sintetica()
    g.str_i[3104] = 0.0; g.trk_ang[2001] = 50.0
    esp = _esp(g); d = dc.decompor(g, esp, MAPA, P, instaladas=UNIVERSO)
    assert (d.zeradas[1001] == 1).all() and d.instaladas[1001] == [3101, 3102, 3103, 3104]
    assert (d.string[1001] - (esp[1001] - d.tracker[1001]) / 4).abs().max() < 1e-6


def test_string_nao_conta_com_inversor_morto_nem_fora_do_universo_instalado():
    g = grade_sintetica()
    g.str_i[[3101, 3102, 3103]] = 0.3; g.str_i[3104] = 0.0; g.str_i.iloc[0] = 5.0
    d = dc.decompor(g, _esp(g), MAPA, P, instaladas=UNIVERSO)
    assert d.string[1001].abs().max() < 1e-6 and not d.viva[1001].iloc[1:].any()
    g = grade_sintetica()
    g.str_i[3104] = 0.0
    esp = _esp(g); d = dc.decompor(g, esp, MAPA, P, instaladas={1001: [3101, 3102, 3104]})
    assert d.instaladas[1001] == [3101, 3102, 3104] and (d.string[1001] - esp[1001] / 3).abs().max() < 1e-6


def test_universo_instalado_vem_do_historico_ou_da_propria_janela():
    g = grade_sintetica(); g.str_i[3104] = 0.0
    assert dc.decompor(g, _esp(g), MAPA, P).instaladas[1001] == [3101, 3102, 3103]   # so a janela: 3104 nunca passou de 1 A
    assert dc.decompor(g, _esp(g), MAPA, P, instaladas=UNIVERSO).instaladas[1001] == [3101, 3102, 3103, 3104]


@pytest.mark.parametrize("arq", ["mro100_2026-08-26.json", "mro100_2026-08-31.json", "mro100_2026-09-01.json"])
def test_golden_mro100_reproduz_o_veredito_do_spike(arq):
    g, r, esp = esperado_de_placa(G / arq)
    v = veredito(G / arq)
    d = dc.decompor(g, esp, trk_inv_mro100(g), dc.ParamsDecomp())
    for n in v["inv_parado"]:
        sol = (esp[1000 + int(n)] > 20).fillna(False)
        assert d.parado_flag[1000 + int(n)][sol].mean() > 0.9
    top = list((d.perda_trk.sum() * H).sort_values(ascending=False).index[:5])
    assert {2000 + t for t in v["trackers"]} <= set(top), top
    e_dia = float(esp.sum().sum() * H)
    assert abs(float(d.residuo.sum().sum() * H)) / e_dia < v["residuo_max_pct"] / 100
    assert float(d.string.sum().sum() * H) / e_dia < 0.01
    assert len(d.trk_sem_inversor) < 10


def test_tracker_mudo_so_gasta_o_limite_em_horario_solar_a_noite_nao_conta():
    """Levi (12/09/2026): "a partir de 4 horas sem dados de trackers ja e de se alarmar (em horario solar, claro)". O relogio
    do mudo so anda quando ha sol: um tracker que cala as 17h nao vira 'dado ausente' de madrugada, e ainda tem as primeiras
    horas da manha seguinte antes de expirar. Aqui a 'noite' e o meio da grade (ghi = 0 nos slots 2..5)."""
    g = grade_sintetica()
    g.estacao.iloc[2:6, g.estacao.columns.get_loc("ghi")] = 0.0
    g.trk_ang[2002] = [50.0, 50.0] + [np.nan] * 6
    d = dc.decompor(g, _esp(g), MAPA, dc.ParamsDecomp(f_direta_fixa=0.6, trk_mudo_slots=2))
    assert d.tracker[1002].iloc[2:6].abs().max() < 1e-6                 # noite: sem fracao direta, nada a perder
    assert (d.tracker[1002].iloc[6:] > 0).all()                         # manha: 2 slots de sol desde a ultima leitura, ainda vale
    d1 = dc.decompor(g, _esp(g), MAPA, dc.ParamsDecomp(f_direta_fixa=0.6, trk_mudo_slots=1))
    assert d1.tracker[1002].iloc[6] > 0 and abs(d1.tracker[1002].iloc[7]) < 1e-6 and np.isnan(d1.excesso[2002].iloc[7])


def test_limite_padrao_do_tracker_mudo_e_de_4_horas_solares():
    assert dc.ParamsDecomp().trk_mudo_slots == 16
