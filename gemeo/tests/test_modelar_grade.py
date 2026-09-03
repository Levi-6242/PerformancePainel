# gemeo/tests/test_modelar_grade.py
from pathlib import Path
import pandas as pd
from gemeo.modelar import grade

G = Path(__file__).parent / "fixtures" / "golden"


def test_fixture_mro100_vira_grade_de_15_min():
    g = grade.grade_de_fixture(G / "mro100_2026-08-31.json")
    assert g.usina.codigo == "MRO100" and g.indice.freq == pd.Timedelta("15min") and g.indice.tz is not None
    assert g.inv_p.shape[1] == 25 and g.trk_ang.shape[1] == 120 and g.str_i.shape[1] == 36
    # ids sinteticos da fixture: inversor n -> 1000+n, tracker n -> 2000+n, string "inv.k" -> 3000 + inv*100 + k
    assert g.estacao.poa.max() > 900 and g.tipo[2017] == "tracker" and g.pai[3101] == 1001


def test_fixture_santarem_sem_trackers():
    g = grade.grade_de_fixture(G / "santarem1_2026-08-26.json")
    assert g.inv_p.shape[1] == 10 and g.trk_ang.shape[1] == 0 and g.str_i.shape[1] == 0


def test_ts_da_fixture_e_hora_local_convertida_para_utc():
    g = grade.grade_de_fixture(G / "mro100_2026-08-26.json")
    # 12:00 local (Belem, UTC-3) = 15:00 UTC; o pico de POA da MRO100 fica entre 12h e 14h locais
    assert g.estacao.poa.idxmax().tz_convert("America/Belem").hour in (11, 12, 13, 14)
