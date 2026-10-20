# -*- coding: utf-8 -*-
"""A linha do gráfico Energia × Irradiação do Diário vira a geração esperada pelo IPOA (20/10/2026).

POR QUE ESTE TESTE EXISTE
Levi, 20/10/2026: "linha de POA que está no gráfico das colunas de geração diária. quero que faça um cálculo
proporcional a kwp para a linha mostrar qual seria a geração com aquele IPOA ao invés de só medir IPOA"; na escolha da
conta, "kWp × IPOA × PR da meta". Altair em 03/10/2026: 6.898 kWp × 4,6517 kWh/m² × 0,748 (PR da meta de outubro) =
24.014 kWh esperados contra 21.760 gerados.

As réguas: a conta é a do servidor (a tela só desenha); dia sem IPOA não ganha número; sem kWp ou sem PR na meta não há
linha esperada e a tela mantém a de irradiação (nada some calado); PR escrito em % (74,8) vale o mesmo que 0,748.
"""
import datetime as dt
import os
import sys

import pytest

AQUI = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(AQUI, "..", "thopen"))
import dashboard_thopen as dth  # noqa: E402

RECS = [{"data": dt.date(2026, 10, 3), "ger": 21759.5, "ipoa": 4.6517, "disp": None, "com": None},
        {"data": dt.date(2026, 10, 4), "ger": 5000.0, "ipoa": None, "disp": None, "com": None}]
URL = "/api/t/diario?usina=Altair&ano=2026&mes=10"


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.delenv("THOPEN_LOGIN", raising=False)
    monkeypatch.setattr(dth, "_daily_records", lambda u: list(RECS))
    monkeypatch.setattr(dth, "_registro", lambda: {"Altair": {"pot_mwp": 6.898}})
    monkeypatch.setattr(dth, "_meta2026", lambda u: {10: {"meta": 744000.0, "pr": 0.748411191, "metairr": 220.3}})
    return dth.app.test_client()


def test_esperada_e_kwp_vezes_ipoa_vezes_pr_da_meta(cli):
    r = cli.get(URL).get_json()
    d3, d4 = r["pontos"]
    assert d3["esperada"] == round(6898 * 4.6517 * 0.748411191, 1) == 24014.6
    assert d4["esperada"] is None                                   # dia sem IPOA não ganha número
    assert r["esperada_base"] == {"pot_kwp": 6898.0, "pr": 0.748411191}
    assert d3["ipoa"] == 4.6517                                     # o IPOA segue na resposta (vai no mouse)


def test_sem_kwp_ou_sem_pr_nao_ha_linha_esperada(cli, monkeypatch):
    monkeypatch.setattr(dth, "_registro", lambda: {})
    r = cli.get(URL).get_json()
    assert r["esperada_base"] is None and all(p["esperada"] is None for p in r["pontos"])
    monkeypatch.setattr(dth, "_registro", lambda: {"Altair": {"pot_mwp": 6.898}})
    monkeypatch.setattr(dth, "_meta2026", lambda u: {10: {"meta": 744000.0, "pr": None}})
    r = cli.get(URL).get_json()
    assert r["esperada_base"] is None and all(p["esperada"] is None for p in r["pontos"])


def test_pr_em_porcento_vale_o_mesmo(cli, monkeypatch):
    monkeypatch.setattr(dth, "_meta2026", lambda u: {10: {"meta": 744000.0, "pr": 74.8411191}})
    r = cli.get(URL).get_json()
    assert r["pontos"][0]["esperada"] == 24014.6 and r["esperada_base"]["pr"] == pytest.approx(0.748411191)


def test_a_tela_desenha_a_esperada_no_eixo_da_energia_e_guarda_a_irradiacao_sem_ela():
    html = open(os.path.join(AQUI, "..", "thopen", "templates", "dashboard_thopen.html"), encoding="utf-8").read()
    i = html.index("async function renderDiario(")
    corpo = html[i:html.index("Plotly.react('chDiario'", i)]
    assert "p.esperada" in corpo and "Esperada pelo IPOA" in corpo
    assert "d.esperada_base" in corpo                               # com a base, a linha nova; sem ela, a de antes
    assert "Irradiação (kWh/m²)" in corpo and "yaxis2" in corpo
    assert 'id="grafTit"' in html                                    # o título troca junto com a linha
    m = html.index("Meta diária (linha azul do Diário)")             # a Metodologia diz a fórmula ao cliente
    assert "Geração esperada pelo IPOA" in html[m:m + 1500] and "PR da meta" in html[m:m + 1500]
