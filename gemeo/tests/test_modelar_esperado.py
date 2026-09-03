# gemeo/tests/test_modelar_esperado.py
"""Numeros de referencia: a 1000 W/m2 e 25 C, 277,68 kWp com perdas 14% e eta 0,96 dao 229,2 kW de AC
(277,68 x 0,86 x 0,96) com teto folgado (300 kW); a curva de carga parcial do PVWatts desvia ~0,2%, por isso
rel=1e-2. Teto 1e9 NAO serve: zeta -> 0 zera o AC. Com teto de 200 kW, 200. Zero POA da zero."""
import numpy as np
import pandas as pd
import pytest
from pathlib import Path
from gemeo.modelar import esperado, gate, grade

G = Path(__file__).parent / "fixtures" / "golden"


def test_ponto_de_referencia_stc():
    p = esperado.ParamsModelo(kwp=277.68, pac0_kw=300.0)
    s = esperado.esperado_inversor(pd.Series([1000.0, 0.0]), pd.Series([25.0, 25.0]), p)
    assert s.iloc[0] == pytest.approx(277.68 * 0.86 * 0.96, rel=1e-2) and s.iloc[1] == 0.0


def test_teto_ac_limita():
    p = esperado.ParamsModelo(kwp=277.68, pac0_kw=200.0)
    assert esperado.esperado_inversor(pd.Series([1000.0]), pd.Series([25.0]), p).iloc[0] == pytest.approx(200.0, rel=1e-3)


def test_temperatura_alta_reduz():
    p = esperado.ParamsModelo(kwp=277.68, pac0_kw=300.0)
    frio, quente = esperado.esperado_inversor(pd.Series([800.0, 800.0]), pd.Series([25.0, 55.0]), p)
    assert quente < frio and quente / frio == pytest.approx(1 - 0.0035 * 30, rel=1e-3)


def test_inferir_pac0_prefere_a_placa_e_marca_quando_infere():
    obs = pd.Series([150.0, 200.0, 199.0, 0.0])
    assert esperado.inferir_pac0(obs, kw_ac_placa=214.0, kwp=277.68) == (214.0, False)
    v, inf = esperado.inferir_pac0(obs, kw_ac_placa=None, kwp=277.68)
    assert v == pytest.approx(200.0, abs=0.1) and inf is True  # quantil 0,999 de 4 pontos = 199,997


def test_esperado_por_inversor_respeita_o_gate():
    g = grade.grade_de_fixture(G / "mro100_2026-08-26.json")
    r = gate.avaliar(g.estacao, None, gate.ParamsGate(), g.usina.tz)
    params = {i: esperado.ParamsModelo(kwp=277.68, pac0_kw=200.0) for i in g.inv_p.columns}
    e = esperado.esperado_por_inversor(g, r, params)
    assert e.shape == g.inv_p.shape
    assert e[r.gate != "ok"].isna().all().all() and e[r.gate == "ok"].notna().all().all()
    assert 0 < e.max().max() <= 200.0
