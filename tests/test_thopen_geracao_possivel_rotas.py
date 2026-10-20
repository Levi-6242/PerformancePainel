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


def _html():
    return open(os.path.join(AQUI, "..", "thopen", "templates", "dashboard_thopen.html"), encoding="utf-8").read()


def _corpo(nome):
    h = _html()
    i = h.index("async function %s(" % nome)
    return h[i:h.index("\n}\n", i)]


def test_visao_geral_de_outubro_com_as_14_colunas_e_o_total_do_servidor():
    h = _html()   # o desenho da regra nova mora num auxiliar (_geralPossivel) chamado pelo renderGeral
    g = h[h.index("const _GERAL_CAB="):h.index("\n}\n", h.index("async function renderGeral("))]
    assert "d.regra==='possivel'" in g and "d.total" in g
    for cab in ("Geração Possível (kWh)", "Dif. Possível (%)", "Possível c/ Expurgos (kWh)", "Dif. c/ Expurgos (%)"):
        assert cab in g, cab
    assert "sem ETM" in g and "dias sem dado" in g and "medição de irradiação em" in g
    assert 'id="geralHead"' in _html()
    # antes de outubro, o cabeçalho e o Total de antes (somado no navegador)
    assert "Diferença Irradiação (%)" in g and "const sMeta=" in g


def test_visao_geral_de_outubro_cabe_na_folha():
    h = _html()
    assert "#tblGeral.possivel" in h       # a fonte encolhe só com a regra nova


def test_diario_de_outubro_com_a_possivel_do_dia(cli):
    r = cli.get("/api/t/diario?usina=Altair&ano=2026&mes=10").get_json()
    p1, p2 = r["pontos"][0], r["pontos"][1]
    assert p1["possivel"] == pytest.approx(gp.possivel_do_dia(31000.0, 155.0, 6.0)) and p1["fonte_ipoa"] == "ETM"
    assert p2["possivel"] == pytest.approx(gp.possivel_do_dia(31000.0, 155.0, 5.5)) and p2["fonte_ipoa"] == "GHI"
    assert p2["ipoa_med"] == 5.5 and r["pontos"][4]["possivel"] is None            # dia sem medição: sem ponto
    assert r["possivel_info"] == {"sem_etm": False, "motivo": None, "dias": 3, "dias_medidos": 2}
    assert "esperada" not in p1 and "esperada_base" not in r                         # a conta kWp × IPOA × PR saiu


def test_diario_sem_cobertura_nao_tem_linha(cli, monkeypatch):
    poucos = [dict(x, ipoa=None) for x in OUT]
    monkeypatch.setattr(dth, "_daily_records", lambda u: poucos)
    monkeypatch.setattr(dth, "_ghi_por_dia", lambda u: {})
    r = cli.get("/api/t/diario?usina=Altair&ano=2026&mes=10").get_json()
    assert r["possivel_info"]["sem_etm"] is True and r["possivel_info"]["motivo"] == "cobertura"
    assert all(p["possivel"] is None for p in r["pontos"])


def test_diario_de_setembro_como_antes(cli):
    r = cli.get("/api/t/diario?usina=Altair&ano=2026&mes=9").get_json()
    assert "possivel_info" not in r and "possivel" not in r["pontos"][0] and "esperada" not in r["pontos"][0]


def test_tela_do_diario_desenha_a_possivel_e_a_metodologia():
    d = _corpo("renderDiario")
    assert "d.possivel_info" in d and "p.possivel" in d and "Possível pelo IPOA" in d
    assert "medição de irradiação em" in d                                           # a nota sem cobertura
    assert "Irradiação (kWh/m²)" in d and "yaxis2" in d                               # antes de outubro, como era
    assert "esperada_base" not in d
    h = _html()
    m = h.index("Meta diária (linha azul do Diário)")
    assert "Geração possível pelo IPOA" in h[m:m + 3000] and "PR da meta" not in h
