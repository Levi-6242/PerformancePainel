# gemeo/tests/test_app_formato.py
import datetime as dt
from gemeo.app import formato as f


def test_numeros_em_pt_br():
    assert f.num(1234.5, 1) == "1.234,5" and f.num(0.0, 0) == "0" and f.num(None) == "—"
    assert f.mw(148200.0) == "148,2" and f.mw(950.0) == "0,95" and f.pct(-0.044) == "−4,4%" and f.pct(None) == "—"
    assert f.brl(1400.0) == "R$ 1,4 mil" and f.brl(390.0) == "R$ 390" and f.brl(None) == "—"


def test_idade_em_minutos_e_horas():
    ref = dt.datetime(2026, 9, 3, 15, 0, tzinfo=dt.timezone.utc)
    assert f.idade(ref - dt.timedelta(minutes=7), ref) == "7 min" and f.idade(ref - dt.timedelta(hours=26), ref) == "26 h"
    assert f.idade(None, ref) == "nunca"
