# -*- coding: utf-8 -*-
"""A geração possível pelo IPOA nas rotas e na tela (Levi, 20/10/2026): a Visão Geral de outubro em diante pela regra,
setembro como era, o GHI lido da aba diária, a linha Total do portfólio no servidor e a linha preta do Diário. Dados,
meta e disponibilidade falsos, nada de rede. Spec: docs/superpowers/specs/2026-10-20-thopen-geracao-possivel-design.md.
"""
import datetime as dt
import os
import sys

import pytest

AQUI = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(AQUI, "..", "thopen"))
import dashboard_thopen as dth  # noqa: E402
import fonte_operacao  # noqa: E402
import geracao_possivel as gp  # noqa: E402
import operacao_mes  # noqa: E402

OUT = [{"data": dt.date(2026, 10, 1), "ger": 900.0, "ipoa": 6.0, "disp": None, "com": None},
       {"data": dt.date(2026, 10, 2), "ger": 800.0, "ipoa": 0.1, "disp": None, "com": None},
       {"data": dt.date(2026, 10, 3), "ger": None, "ipoa": None, "disp": None, "com": None},
       {"data": dt.date(2026, 10, 4), "ger": 0.0, "ipoa": None, "disp": None, "com": None},
       {"data": dt.date(2026, 10, 5), "ger": 700.0, "ipoa": None, "disp": None, "com": None}]
SET = [{"data": dt.date(2026, 9, d), "ger": 1000.0, "ipoa": 5.0, "disp": 99.0, "com": None} for d in range(1, 11)]
GHI = {dt.date(2026, 10, 2): 5.5}
META = {9: {"meta": 30000.0, "metairr": 150.0}, 10: {"meta": 31000.0, "metairr": 155.0}}
DISP = {dt.date(2026, 10, 1): 100.0, dt.date(2026, 10, 2): 80.0, dt.date(2026, 10, 5): 90.0}


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.delenv("THOPEN_LOGIN", raising=False)
    monkeypatch.delenv("THOPEN_OPERACAO", raising=False)
    monkeypatch.setattr(dth, "_daily_records", lambda u: OUT + SET)
    monkeypatch.setattr(dth, "_ghi_por_dia", lambda u: dict(GHI))
    monkeypatch.setattr(dth, "_meta2026", lambda u: META)
    monkeypatch.setattr(dth, "_registro", lambda: {"Altair": {"pot_mwp": 1.0}, "Assis": {"pot_mwp": 3.0}})
    monkeypatch.setattr(fonte_operacao, "dados", lambda *a, **k: {"disponibilidade_dia": [1]})
    monkeypatch.setattr(operacao_mes, "disp_por_dia", lambda dados, u, a, m: dict(DISP) if (a, m) == (2026, 10) else {})
    monkeypatch.setattr(dth, "_wb", lambda: None)
    monkeypatch.setattr(dth, "_state", dict(dth._state, daily={"Altair": ("x", "A1"), "Assis": ("y", "A1")}))
    monkeypatch.setattr(dth, "_polaris_records", lambda: {})
    monkeypatch.setattr(dth, "_sheet_records", lambda: {})
    monkeypatch.setattr(dth, "CARTEIRAS", dict(dth.CARTEIRAS, Thopen=["Altair", "Assis"]))
    return dth.app.test_client()


def _esperado():
    return gp.periodo(OUT, GHI, 31000.0, 155.0, 31, DISP)


def test_geral_de_outubro_pela_regra(cli):
    r = cli.get("/api/t/geral?carteira=Thopen&ano=2026&mes=10").get_json()
    assert r["regra"] == "possivel"
    alt = next(l for l in r["linhas"] if l["usina"] == "Altair")
    e = _esperado()
    assert alt["meta"] == pytest.approx(e["meta"]) == pytest.approx(3000)        # 3 dias × 1.000, não o mês inteiro
    assert alt["irr_esp"] == pytest.approx(e["meta_ipoa"]) and alt["irr_med"] == pytest.approx(e["ipoa_ajustado"])
    assert alt["dif_irr"] == pytest.approx(e["dif_ipoa"]) and alt["possivel"] == pytest.approx(e["possivel"])
    assert alt["possivel_exp"] == pytest.approx(e["possivel_exp"])
    assert alt["dif_prod"] == pytest.approx(2400 / 3000 - 1)
    assert alt["furos"] == ["03/10", "04/10"] and alt["sem_etm"] is False and alt["cobertura"] == pytest.approx(2 / 3)
    assert r["total"]["possivel"] == pytest.approx(2 * e["possivel"])               # as duas usinas com os mesmos dias
    assert r["total"]["meta"] == pytest.approx(6000)


def test_geral_de_setembro_igual_ao_de_antes(cli):
    r = cli.get("/api/t/geral?carteira=Thopen&ano=2026&mes=9").get_json()
    assert "regra" not in r and "total" not in r
    alt = next(l for l in r["linhas"] if l["usina"] == "Altair")
    assert alt["meta"] == 30000.0 and alt["irr_esp"] == 150.0 and alt["irr_med"] == pytest.approx(50.0)
    assert "possivel" not in alt


def test_operacao_carregando_sem_expurgo(cli, monkeypatch):
    monkeypatch.setattr(fonte_operacao, "dados", lambda *a, **k: None)
    alt = next(l for l in cli.get("/api/t/geral?carteira=Thopen&ano=2026&mes=10").get_json()["linhas"]
               if l["usina"] == "Altair")
    assert alt["possivel_exp"] is None and alt["possivel"] == pytest.approx(_esperado()["possivel"])


def test_ghi_le_a_coluna_da_aba():
    hdr = ["Usina", "Data", "IPOA (kWh/m²)", "GHI (kWh/m²)", "Energia Produzida (kWh)"]
    rows = [["Altair", dt.datetime(2026, 10, 1), 5.0, 4.2, 900], ["Altair", "x", 1, 2, 3],
            ["Altair", dt.date(2026, 10, 2), None, None, 800]]
    assert dth._ghi_das_linhas(hdr, rows) == {dt.date(2026, 10, 1): 4.2}
    assert dth._ghi_das_linhas(hdr[:3] + hdr[4:], [r[:3] + r[4:] for r in rows]) == {}
