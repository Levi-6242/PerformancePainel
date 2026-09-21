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
    """17/09/2026: a invariante passou de QUATRO para CINCO parcelas — entrou `clipping`, que
    reclassifica a fatia do residuo em que o inversor esta no proprio teto. Neste cenario o 1001
    esta cravado em 120 kW, que e exatamente um teto, entao parte do delta dele sai como clipping
    e a soma antiga (sem a parcela) nao fecha mais."""
    g = grade_sintetica()
    g.inv_p[1001] = 120.0; g.trk_ang[2002] = 50.0; g.str_i[3104] = 0.0
    g.inv_p.iloc[3, 1] = np.nan
    d = dc.decompor(g, _esp(g), MAPA, P)
    soma = d.parado + d.tracker + d.string + d.clipping + d.residuo
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


def test_excesso_usa_a_mediana_do_grupo_do_inversor_quando_ha_tres_ou_mais_trackers():
    """Tupi Paulista (11/09/2026): dois blocos de 50 trackers com backtracking diferente ao amanhecer e ao entardecer
    (bloco 1 a 41,5 graus e bloco 2 a 33,8 as 17h) — a mediana da FROTA punia um bloco inteiro por 6 a 8 graus. A referencia
    passa a ser a mediana dos trackers do MESMO inversor quando ha pelo menos tres com dado e ela esta perto da frota; com
    menos, ou sem inversor, a frota, como antes."""
    g = grade_sintetica()
    for t, inv, ang in ((2004, 1001, 27.0), (2005, 1001, 27.0), (2006, 1001, 27.0), (2007, 1002, 20.0), (2008, 1002, 20.0), (2009, 1002, 20.0)):
        g.trk_ang[t] = ang; g.pai[t] = inv; g.tipo[t] = "tracker"
    g.trk_ang[2001] = 27.0; g.trk_ang[2002] = 20.0; g.trk_ang[2003] = 70.0        # bloco 1 a 7 graus do bloco 2; 2003 sem inversor
    mapa = {2001: 1001, 2002: 1002, 2004: 1001, 2005: 1001, 2006: 1001, 2007: 1002, 2008: 1002, 2009: 1002}
    exc = dc.excesso_trackers(g.trk_ang, P, grupos=mapa)
    assert exc[2004].abs().max() < 1e-6 and exc[2007].abs().max() < 1e-6 and exc[2001].abs().max() < 1e-6   # blocos alinhados: zero
    assert (exc[2003] > 0).all()                                                    # sem grupo: contra a frota
    g.trk_ang[2006] = 0.0                                                           # um tracker do bloco 1 fora dos pares
    exc = dc.excesso_trackers(g.trk_ang, P, grupos=mapa)
    assert (exc[2006] - 27.0).abs().max() < 1e-6 and exc[2004].abs().max() < 1e-6  # so ele, contra a mediana do SEU grupo (27)
    # grupo com menos de tres trackers cai na frota: o comportamento de sempre (MAPA tem um tracker por inversor)
    exc_frota = dc.excesso_trackers(g.trk_ang, P, grupos={2001: 1001, 2002: 1002})
    assert (exc_frota[2001] - 7.0).abs().max() < 1e-6                               # mediana da frota = 20 -> 27 fica 7 fora


def test_grupo_inteiro_fora_da_frota_nao_se_esconde_atras_da_propria_mediana():
    """Tupi Paulista, 11/09/2026: os cinco trackers do Inversor 2.10 acordaram 2-3 h atrasados JUNTOS (todos em -9 e depois em 0
    com a frota em -55). Com a referencia so do grupo, os cinco concordavam entre si e o excesso sumia — a mediana do grupo so vale
    quando o grupo esta perto da frota (backtracking de bloco, poucos graus); grupo inteiro longe da frota e medido contra a frota."""
    g = grade_sintetica()
    for t, inv, ang in ((2004, 1001, 60.0), (2005, 1001, 60.0), (2006, 1001, 60.0), (2007, 1002, 20.0), (2008, 1002, 20.0), (2009, 1002, 20.0)):
        g.trk_ang[t] = ang; g.pai[t] = inv; g.tipo[t] = "tracker"
    g.trk_ang[2001] = 60.0; g.trk_ang[2002] = 20.0; g.trk_ang[2003] = 20.0
    mapa = {2001: 1001, 2002: 1002, 2004: 1001, 2005: 1001, 2006: 1001, 2007: 1002, 2008: 1002, 2009: 1002}
    exc = dc.excesso_trackers(g.trk_ang, P, grupos=mapa)
    assert (exc[2004] - 40.0).abs().max() < 1e-6 and (exc[2001] - 40.0).abs().max() < 1e-6   # grupo todo a 40 da frota: aparece
    assert exc[2007].abs().max() < 1e-6                                                          # o grupo alinhado com a frota: zero
    g.trk_ang[[2001, 2004, 2005, 2006]] = 27.0                                                    # grupo 7 graus fora: backtracking de bloco
    exc = dc.excesso_trackers(g.trk_ang, P, grupos=mapa)
    assert exc[2004].abs().max() < 1e-6                                                          # dentro da tolerancia: vale o grupo


# ── CLIPPING: parcela nova (Levi, 17/09/2026) ──────────────────────────────────────────────────
# O esperado sai do PVWatts sobre a POA medida, e o PVWatts NAO sabe do limite AC do inversor. Em
# usina sobredimensionada o modelo espera mais do que o equipamento entrega e a diferenca caia toda
# no RESIDUO, como perda inexplicada. O clipping nao cria perda nova: ele RECLASSIFICA a parte do
# residuo em que o inversor esta no proprio teto. Decisao do Levi: clipping NAO conta como perda
# evitavel (e de projeto, nao de operacao) — por isso e parcela propria, separada.

def test_clipping_reclassifica_o_residuo_e_nao_cria_perda_nova():
    g = grade_sintetica()
    esp = _esp(g)
    # inversor 1001 cravado num teto abaixo do que o modelo espera = clipping
    teto = float(esp[1001].max()) * 0.6
    g.inv_p[1001] = teto
    d = dc.decompor(g, esp, MAPA, P)
    soma = d.parado + d.tracker + d.string + d.clipping + d.residuo
    assert (soma - d.delta).abs().where(d.ok, 0.0).max().max() < 1e-6, "as 5 parcelas somam o delta"
    assert d.clipping[1001].sum() > 0, "o teto tinha de virar clipping"
    # e saiu do residuo: sem a reclassificacao, tudo isso seria 'nao sei explicar'
    sem_clip = dc.decompor(g, esp, MAPA, dc.ParamsDecomp(f_direta_fixa=0.6, clipping_ligado=False))
    assert sem_clip.residuo[1001].sum() > d.residuo[1001].sum() + 1e-6


def test_clipping_nao_marca_inversor_que_segue_a_curva():
    """Inversor saudavel acompanha o esperado — nao ha teto, nao ha clipping."""
    g = grade_sintetica()
    d = dc.decompor(g, _esp(g), MAPA, P)
    assert d.clipping.abs().max().max() < 1e-9


def test_clipping_nao_marca_inversor_parado():
    """Parado leva o delta inteiro e exclui as outras parcelas — inclusive o clipping, senao um
    inversor morto (medido constante em ~0) seria lido como 'no teto'."""
    g = grade_sintetica()
    g.inv_p[1001] = 0.0
    d = dc.decompor(g, _esp(g), MAPA, P)
    assert d.clipping[1001].abs().max() < 1e-9
    assert d.parado[1001].sum() > 0


def test_clipping_desligado_mantem_o_comportamento_antigo():
    """Trava de compatibilidade: com a parcela desligada, as 4 de sempre continuam somando o delta."""
    g = grade_sintetica()
    g.inv_p[1001] = float(_esp(g)[1001].max()) * 0.6
    d = dc.decompor(g, _esp(g), MAPA, dc.ParamsDecomp(f_direta_fixa=0.6, clipping_ligado=False))
    soma = d.parado + d.tracker + d.string + d.residuo
    assert (soma - d.delta).abs().where(d.ok, 0.0).max().max() < 1e-6
    assert d.clipping.abs().max().max() < 1e-9
