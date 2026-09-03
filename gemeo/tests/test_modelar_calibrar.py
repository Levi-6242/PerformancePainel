# gemeo/tests/test_modelar_calibrar.py
import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from golden import G, esperado_de_placa, sem_gate  # noqa: E402
from sintetico import grade_sintetica  # noqa: E402
from gemeo.modelar import calibrar, esperado  # noqa: E402

D = dt.date(2026, 8, 31)


def test_cv_da_poa_entre_10_e_14_estavel_e_instavel():
    g = grade_sintetica()                       # 09:00-10:45 de Belem: so os 4 slots das 10 h entram
    cv = calibrar.cv_poa_dia(g.estacao["poa"], g.usina.tz)
    assert list(cv) == [D] and cv[D] == pytest.approx(0.0, abs=1e-9)
    g.estacao["poa"] = [800.0, 800.0, 800.0, 800.0, 200.0, 900.0, 200.0, 900.0]
    assert calibrar.cv_poa_dia(g.estacao["poa"], g.usina.tz)[D] > 0.25


def test_dias_limpos_filtra_evento_cobertura_e_instabilidade():
    d1, d2, d3, d4 = (dt.date(2026, 8, k) for k in (28, 29, 30, 31))
    cob = {d1: 0.95, d2: 0.95, d3: 0.5, d4: 0.95}
    cv = {d1: 0.1, d2: 0.1, d3: 0.1, d4: 0.4}
    assert calibrar.dias_limpos(cob, {d2}, cv, calibrar.ParamsCalib()) == [d1]


def test_ajustar_perdas_leva_a_razao_dos_saos_a_um():
    g = grade_sintetica(dias=3)
    params = {i: esperado.ParamsModelo(kwp=277.68, pac0_kw=200.0) for i in g.inv_p.columns}
    r = sem_gate(g)
    esp = esperado.esperado_por_inversor(g, r, params)
    g.inv_p[1001] = esp[1001] * 0.9; g.inv_p[1002] = esp[1002] * 0.9
    dias = sorted(set(g.indice.tz_convert(g.usina.tz).date))
    perdas, m = calibrar.ajustar_perdas(g, r, params, dias, calibrar.ParamsCalib())
    assert perdas == pytest.approx(1 - 0.86 * 0.9, abs=2e-3)      # DC linear em (1 - perdas); o clipping AC nao entra aqui
    assert m["razao_mediana"] == pytest.approx(1.0, abs=1e-3) and m["n_dias"] == 3 and m["desvio"] < 1e-6


def test_ajustar_perdas_sem_dias_e_erro():
    g = grade_sintetica()
    params = {i: esperado.ParamsModelo(kwp=277.68, pac0_kw=200.0) for i in g.inv_p.columns}
    with pytest.raises(ValueError):
        calibrar.ajustar_perdas(g, sem_gate(g), params, [], calibrar.ParamsCalib())


def test_golden_mro100_31_08_calibra_entre_10_e_25_por_cento():
    g, r, esp = esperado_de_placa(G / "mro100_2026-08-31.json")
    params = {i: esperado.ParamsModelo(kwp=g.atributos[i]["kwp"], pac0_kw=g.atributos[i]["kw_ac"]) for i in g.inv_p.columns}
    perdas, m = calibrar.ajustar_perdas(g, r, params, [D], calibrar.ParamsCalib())
    assert 0.10 < perdas < 0.25 and m["razao_mediana"] == pytest.approx(1.0, abs=2e-3) and m["n_dias"] == 1


def test_calibrar_no_banco_recusa_dia_com_evento(conn):
    import json
    from semear import semear_fixture
    from gemeo.modelar import job
    trk_inv = json.load(open(G / "mro100_trk_inv.json", encoding="utf-8"))
    usina, _ = semear_fixture(conn, G / "mro100_2026-08-31.json", trk_inv)
    try:
        UTC = dt.timezone.utc
        job.modelar(conn, usina, dt.datetime(2026, 8, 31, 3, tzinfo=UTC), dt.datetime(2026, 9, 1, 3, tzinfo=UTC))
        res = calibrar.calibrar(conn, usina, dias=3, agora=dt.datetime(2026, 9, 1, 2, tzinfo=UTC))
        assert res["erro"] == "sem dias limpos" and res["com_evento"] == 1      # 31/08 tem inversor 22 parado: nao calibra
        with conn.cursor() as cur:
            cur.execute("SELECT versao FROM modelo"); assert [r[0] for r in cur.fetchall()] == ["placa"]
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM evento; DELETE FROM perda_dia; DELETE FROM cascata_dia; DELETE FROM esperado; "
                        "DELETE FROM modelo; DELETE FROM leitura; DELETE FROM equipamento; DELETE FROM usina; DELETE FROM estado")
        conn.commit()
