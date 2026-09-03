# gemeo/tests/test_modelar_gate.py
"""As duas portas. Caso real 1 (Santarem, 02/09): POA leu 0,12 do GHI com inversores normais — sensor
em falha, e um gate por faixa deixaria passar. Caso real 2 (MRO100, 21–24/08): ETM sem dado — sai
por cobertura, nao por plausibilidade."""
import datetime as dt
import numpy as np
import pandas as pd
from pathlib import Path
from gemeo.modelar import gate, grade

G = Path(__file__).parent / "fixtures" / "golden"
P = gate.ParamsGate()


def _dia_limpo():
    g = grade.grade_de_fixture(G / "mro100_2026-08-26.json")
    return g.estacao, g.usina.tz


def test_dia_limpo_passa_inteiro():
    est, tz = _dia_limpo()
    r = gate.avaliar(est, referencia_razao=None, params=P, tz=tz)
    assert r.motivo_dia[dt.date(2026, 8, 26)] == "ok"
    diurno = est.ghi > 50
    assert (r.gate[diurno] == "ok").mean() > 0.95


def test_sensor_de_poa_em_falha_reprova_por_poa_ghi():
    est, tz = _dia_limpo()
    est = est.copy(); est["poa"] = est["poa"] * 0.12            # o caso de Santarem em 02/09
    r = gate.avaliar(est, referencia_razao=1.23, params=P, tz=tz)
    assert r.motivo_dia[dt.date(2026, 8, 26)] == "poa_ghi"
    assert (r.gate[est.ghi > 100] == "poa_ghi").all()


def test_sem_poa_reprova_por_cobertura():
    est, tz = _dia_limpo()
    est = est.copy(); est["poa"] = np.nan                       # ETM muda o dia inteiro (MRO100 21–24/08)
    r = gate.avaliar(est, referencia_razao=1.23, params=P, tz=tz)
    assert r.motivo_dia[dt.date(2026, 8, 26)] == "cobertura"
    assert (r.gate == "cobertura").all()


def test_valor_fora_de_faixa_e_plausibilidade():
    est, tz = _dia_limpo()
    est = est.copy(); i = est.poa.idxmax(); est.loc[i, "poa"] = 2500.0
    r = gate.avaliar(est, referencia_razao=1.23, params=P, tz=tz)
    assert r.gate[i] == "plausibilidade" and r.motivo_dia[dt.date(2026, 8, 26)] == "ok"
