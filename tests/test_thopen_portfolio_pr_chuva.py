# -*- coding: utf-8 -*-
"""Três pedidos do Levi para o Dashboard Thopen (11/11/2026): o botão Portfólio (todas as usinas de todas as carteiras,
na ordem das carteiras), o PR na Visão Geral (energia ÷ potência × IPOA medido, nos dias com geração e medição) e a
chuva do mês no canto do gráfico do Diário. Dados falsos, nada de rede."""
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

D = [dt.date(2026, 10, d) for d in range(1, 6)]
OUT = [{"data": D[0], "ger": 900.0, "ipoa": 6.0, "disp": None, "com": None},
       {"data": D[1], "ger": 800.0, "ipoa": 0.1, "disp": None, "com": None},   # vale o GHI 5,5
       {"data": D[2], "ger": None, "ipoa": None, "disp": None, "com": None},
       {"data": D[3], "ger": 0.0, "ipoa": None, "disp": None, "com": None},
       {"data": D[4], "ger": 700.0, "ipoa": None, "disp": None, "com": None}]   # sem medição: fora do PR
SET = [{"data": dt.date(2026, 9, d), "ger": 1000.0, "ipoa": 5.0, "disp": 99.0, "com": None} for d in range(1, 11)]
META = {9: {"meta": 30000.0, "metairr": 150.0}, 10: {"meta": 31000.0, "metairr": 155.0}}


def test_o_periodo_da_a_geracao_e_o_ipoa_dos_mesmos_dias():
    p = gp.periodo(OUT, {D[1]: 5.5}, 31000.0, 155.0, 31, None)
    assert p["real_medido"] == pytest.approx(1700) and p["ipoa_medido"] == pytest.approx(11.5)


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.delenv("THOPEN_LOGIN", raising=False)
    monkeypatch.delenv("THOPEN_OPERACAO", raising=False)
    monkeypatch.setattr(dth, "_daily_records", lambda u: OUT + SET)
    monkeypatch.setattr(dth, "_ghi_por_dia", lambda u: {D[1]: 5.5})
    monkeypatch.setattr(dth, "_meta2026", lambda u: META)
    monkeypatch.setattr(dth, "_registro", lambda: {"Altair": {"pot_mwp": 1.0}, "Pharma II": {"pot_mwp": 2.0}})
    monkeypatch.setattr(fonte_operacao, "dados", lambda *a, **k: {"disponibilidade_dia": [1]})
    monkeypatch.setattr(operacao_mes, "disp_por_dia", lambda *a, **k: {})
    monkeypatch.setattr(dth, "_wb", lambda: None)
    monkeypatch.setattr(dth, "_state", dict(dth._state, daily={"Altair": ("x", "A1"), "Pharma II": ("y", "A1")}))
    monkeypatch.setattr(dth, "_polaris_records", lambda: {})
    monkeypatch.setattr(dth, "_sheet_records", lambda: {})
    monkeypatch.setattr(dth, "CARTEIRAS", dict(dth.CARTEIRAS, Thopen=["Altair"], Copel=["Pharma II"]))
    monkeypatch.setattr(dth, "_chuva_por_dia", lambda u: {D[0]: 12.5, D[1]: 0.0, D[4]: 3.0, dt.date(2026, 10, 9): 40.0})
    return dth.app.test_client()


def test_o_pr_da_linha_e_do_total(cli):
    r = cli.get("/api/t/geral?carteira=Thopen&ano=2026&mes=10").get_json()
    alt = r["linhas"][0]
    # 1.700 kWh nos dias medidos ÷ (1.000 kWp × 11,5 kWh/m²)
    assert alt["pr"] == pytest.approx(1700 / 11500) and r["total"]["pr"] == pytest.approx(1700 / 11500)
    assert "pr_real" not in alt and "pr_ipoa" not in r["total"]       # as contas de dentro não saem


def test_o_pr_antes_de_outubro_e_o_do_mes(cli):
    alt = cli.get("/api/t/geral?carteira=Thopen&ano=2026&mes=9").get_json()["linhas"][0]
    assert alt["pr"] == pytest.approx(10000 / (1000 * 50))


def test_o_portfolio_junta_as_carteiras_na_ordem(cli):
    r = cli.get("/api/t/geral?carteira=Portfólio&ano=2026&mes=10").get_json()
    assert r["carteira"] == "Portfólio"
    assert [(l["carteira"], l["usina"]) for l in r["linhas"]] == [("Thopen", "Altair"), ("Copel", "Pharma II")]
    assert r["total"]["meta"] == pytest.approx(2 * 5000)


def test_o_portfolio_vale_nos_registros_e_carteira_inventada_nao(cli):
    r = cli.get("/api/t/registros?carteira=Portfólio&ano=2026&mes=10").get_json()
    assert [u["usina"] for u in r["usinas"]] == ["Altair", "Pharma II"]
    assert cli.get("/api/t/registros?carteira=Outra&ano=2026&mes=10").status_code == 400


def test_a_chuva_so_dos_dias_coletados(cli):
    c = cli.get("/api/t/diario?usina=Altair&ano=2026&mes=10").get_json()["chuva"]
    # 09/10 não tem geração nem IPOA (o BD pré-cria o mês): a chuva dele não conta
    assert c == {"total_mm": 15.5, "dias_chuva": 2, "dias": 3, "maior_dia": 1, "maior_mm": 12.5}


def test_sem_a_coluna_da_chuva_o_diario_segue(cli, monkeypatch):
    def cai(u):
        raise KeyError("sem aba")
    monkeypatch.setattr(dth, "_chuva_por_dia", cai)
    r = cli.get("/api/t/diario?usina=Altair&ano=2026&mes=10")
    assert r.status_code == 200 and r.get_json()["chuva"] is None


T = open(os.path.join(AQUI, "..", "thopen", "templates", "dashboard_thopen.html"), encoding="utf-8").read()


def test_a_tela():
    # o PR logo depois da Diferença Produção (Levi, 11/11/2026: "bote a coluna de PR depois de Diferença Produção")
    assert "<th>Diferença Produção (%)</th><th>PR (%)</th><th>Irradiação Esperada (kWh/m²)</th>" in T
    assert "const PORT='Portfólio';" in T and "CARTS.length>1?" in T and 'class="grupo"' in T
    # a chuva no card ao lado da Irradiação no Mês (11/11/2026, "corta a largura pela metade"), não embaixo do gráfico
    assert 'id="irrChuva"' in T and 'id="chuvaCard"' in T and "_chuvaCard(d);" in T
    assert "🌧" not in T                       # o emoji saiu (Levi, 11/11/2026: "tira esse emoji de chuva")
    assert 'id="chuvaMm"' in T and 'id="chuvaDias"' in T and "Dias de chuva" in T and "chuvaSelo" not in T
    assert ".com-op #irrChuva{ grid-area:irr; }" in T
    # sempre à vista, com "—" sem dado ou com o mês todo em 0 ("deixa sempre aparecendo [...] aparece só com '-'")
    assert '<div class="card" id="chuvaCard">' in T and "$('chuvaMm').textContent='—'" in T
    assert "d.chuva.total_mm>0" in T          # o mês todo em 0 (sem pluviômetro) não vira "0,0 mm"
