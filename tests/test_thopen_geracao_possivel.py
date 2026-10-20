# -*- coding: utf-8 -*-
"""A regra da geração possível pelo IPOA (Levi, 20/10/2026), em números feitos à mão.

POR QUE ESTE TESTE EXISTE
A Visão Geral comparava a produção até o corte com a meta do MÊS INTEIRO (no meio do mês toda usina aparecia abaixo da
meta) e não dizia quanto a usina deveria ter gerado com o sol que fez. A regra do Levi: só os dias com geração, meta e
meta de IPOA proporcionais a esses dias, IPOA da ETM (≥ 0,3) ou o GHI (≥ 1,0), cobertura mínima de 50%, IPOA ajustado
pela cobertura, geração possível = meta × (1 + Dif. IPOA), expurgo pela disponibilidade das OS ponderada pelo IPOA e o
portfólio só com as usinas com ETM. Spec: docs/superpowers/specs/2026-10-20-thopen-geracao-possivel-design.md.

O mês de exemplo: 30 dias, meta 30.000 kWh e 150 kWh/m² (1.000 kWh e 5 kWh/m² por dia).
"""
import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "thopen"))
import geracao_possivel as gp  # noqa: E402

D = [dt.date(2026, 10, n) for n in range(1, 7)]
REGS = [{"data": D[0], "ger": 900.0, "ipoa": 6.0},
        {"data": D[1], "ger": 800.0, "ipoa": 0.1},     # ETM abaixo de 0,3: vale o GHI
        {"data": D[2], "ger": None, "ipoa": None},     # sem dado: furo
        {"data": D[3], "ger": 0.0, "ipoa": None},      # 0 sem medição antes do último coletado: furo
        {"data": D[4], "ger": 700.0, "ipoa": None},    # entra sem medição (GHI abaixo de 1,0)
        {"data": D[5], "ger": 0.0, "ipoa": None}]      # linha pré-criada depois do último coletado: nem entra nem é furo
GHI = {D[1]: 5.5, D[4]: 0.5}
DISP = {D[0]: 100.0, D[1]: 80.0, D[4]: 90.0}     # como o operacao_mes.disp_por_dia: pela data


def _p(**k):
    a = dict(registros=REGS, ghi=GHI, meta_mes=30000.0, meta_ipoa_mes=150.0, dias_mes=30, disp=DISP)
    a.update(k)
    return gp.periodo(**a)


def test_dia_que_entra_e_furo():
    p = _p()
    assert p["dias"] == 3 and p["furos"] == [D[2], D[3]]


def test_dia_parado_com_sol_entra():
    # a usina parada o dia todo com sol medido é dado ruim de verdade: tem de pesar (não é linha pré-criada)
    regs = REGS[:5] + [{"data": D[5], "ger": 0.0, "ipoa": 5.0}]
    p = _p(registros=regs)
    assert p["dias"] == 4 and p["furos"] == [D[2], D[3]] and p["real"] == 2400


def test_meta_e_ipoa_do_periodo():
    p = _p()
    assert p["meta"] == pytest.approx(3000) and p["meta_ipoa"] == pytest.approx(15)
    assert p["dias_medidos"] == 2 and p["cobertura"] == pytest.approx(2 / 3)
    assert p["ipoa_ajustado"] == pytest.approx(17.25) and p["dif_ipoa"] == pytest.approx(0.15)
    assert p["possivel"] == pytest.approx(3450) and p["real"] == pytest.approx(2400)
    assert p["dif_possivel"] == pytest.approx(-0.304348, abs=1e-6)
    assert p["sem_etm"] is False and p["motivo"] is None


def test_expurgo_ponderado_pelo_ipoa():
    p = _p()
    # pesos: o IPOA medido (6,0 e 5,5) e, no dia sem medição, a meta de IPOA do dia (5,0)
    assert p["disp_efetiva"] == pytest.approx((100 * 6 + 80 * 5.5 + 90 * 5) / 16.5 / 100)
    assert p["possivel_exp"] == pytest.approx(3450 * p["disp_efetiva"])
    assert p["dif_possivel_exp"] == pytest.approx(-0.229647, abs=1e-6)
    dif_ger_exp = (2400 / p["disp_efetiva"]) / 3000 - 1
    assert p["dif_possivel_exp"] == pytest.approx((1 + dif_ger_exp) / (1 + 0.15) - 1)


def test_ipoa_etm_ghi_e_teto():
    assert gp.ipoa_do_dia(6.0, 9.0) == (6.0, "ETM")
    assert gp.ipoa_do_dia(0.2, 5.5) == (5.5, "GHI")
    assert gp.ipoa_do_dia(0.2, 0.9) == (None, None)
    assert gp.ipoa_do_dia(12.5, 7.0) == (7.0, "GHI")       # IPOA acima do teto físico: cai para o GHI
    assert gp.ipoa_do_dia(None, 25.7) == (None, None)       # GHI acima do teto (parece MJ/m²): sem medição
    assert gp.ipoa_do_dia(11.6, None) == (11.6, "ETM")      # tracker: plausível


def test_cobertura_minima():
    dois = [{"data": D[0], "ger": 500.0, "ipoa": 5.0}, {"data": D[1], "ger": 500.0, "ipoa": None}]
    assert gp.periodo(dois, {}, 30000.0, 150.0, 30, None)["sem_etm"] is False      # 50%: vale
    tres = dois + [{"data": D[2], "ger": 500.0, "ipoa": None}]
    p = gp.periodo(tres, {}, 30000.0, 150.0, 30, None)                               # 33%: sem ETM
    assert p["sem_etm"] is True and p["motivo"] == "cobertura"
    assert p["possivel"] is None and p["dif_ipoa"] is None and p["ipoa_ajustado"] is None
    assert p["meta"] == pytest.approx(3000) and p["real"] == 1500                     # a meta e o real seguem


def test_sem_meta_de_ipoa():
    for m in (None, 0.0):
        p = _p(meta_ipoa_mes=m)
        assert p["sem_etm"] is True and p["motivo"] == "sem_meta_ipoa" and p["possivel"] is None


def test_sem_disp():
    p = _p(disp=None)
    assert p["disp_efetiva"] is None and p["possivel_exp"] is None and p["dif_possivel_exp"] is None
    assert p["possivel"] == pytest.approx(3450)


def test_sem_meta_de_geracao():
    p = _p(meta_mes=None)
    assert p["meta"] is None and p["possivel"] is None and p["real"] == 2400


def test_possivel_do_dia():
    assert gp.possivel_do_dia(30000.0, 150.0, 6.0) == pytest.approx(1200)
    assert gp.possivel_do_dia(30000.0, 150.0, None) is None
    assert gp.possivel_do_dia(30000.0, 0.0, 6.0) is None
    assert gp.possivel_do_dia(None, 150.0, 6.0) is None


def test_portfolio():
    a = dict(_p(), pot_kwp=1000.0, produzida=2400.0)
    b = dict(gp.periodo([{"data": D[0], "ger": 4000.0, "ipoa": None}] * 3, {}, 50000.0, 150.0, 30, None),
             pot_kwp=3000.0, produzida=4000.0)
    c = dict(gp.periodo([{"data": D[0], "ger": 100.0, "ipoa": None}], {}, None, None, 30, None),
             pot_kwp=500.0, produzida=100.0)
    t = gp.portfolio([a, b, c])
    assert t["meta"] == pytest.approx(3000 + 5000) and t["produzida"] == pytest.approx(2400 + 4000)
    assert t["dif_prod"] == pytest.approx(-0.2)
    assert t["possivel"] == pytest.approx(3450) and t["real_etm"] == pytest.approx(2400)
    assert t["dif_possivel"] == pytest.approx(-0.304348, abs=1e-6)
    assert t["ipoa_ajustado"] == pytest.approx(17.25) and t["meta_ipoa"] == pytest.approx(15)
    assert t["dif_ipoa"] == pytest.approx(0.15)
    assert t["possivel_exp"] == pytest.approx(a["possivel_exp"]) and t["real_exp"] == pytest.approx(2400)


def test_portfolio_ipoa_ponderado_pela_potencia():
    a = dict(_p(), pot_kwp=1000.0, produzida=2400.0)
    b = dict(_p(), pot_kwp=3000.0, produzida=2400.0)
    b["ipoa_ajustado"], b["meta_ipoa"] = 13.25, 15.0
    t = gp.portfolio([a, b])
    assert t["ipoa_ajustado"] == pytest.approx((17.25 * 1000 + 13.25 * 3000) / 4000)
