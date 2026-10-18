# -*- coding: utf-8 -*-
"""O valor ESTOURADO da Ibirapuã II fora do Gerencial (Levi, 18/10/2026: "faça um filtro que filtre apenas esse valor
estourado em Ibirapuã, faça especificamente para essa usina").

Em 13/10/2026 a aba da Ibirapuã II no BD_Performance veio com os contadores acumulados dos medidores no lugar da geração
do dia (multimedidor do SKID 1 = 4.351.190 kWh, inversores de 372 mil a 1,36 milhão; a linha estava VALIDADA, então a
trava de 14/09, que só pega dia não validado, deixou passar): o Gerencial de outubro foi a 7.209%. Só nesta usina, o dia
acima da potência × 12 h vira "sem leitura". Uma régua geral (PR do dia acima de 150%) foi medida no mesmo dia e
derrubava geração verdadeira onde a irradiação lê baixo (Aparecida do Taboado 1 e 2: 13 de 15 dias de outubro)."""
from datetime import datetime

import pytest

import app

POT = 3.396                                   # MWp da Ibirapuã II no cadastro


def test_so_a_ibirapua_ii_e_so_o_impossivel():
    est = app._ger_dia_estourado("Ibirapuã II", 13, 10620888.0, POT)
    assert est == {"dia": 13, "ger_kwh": 10620888.0, "kwh_kwp": 3127.5}
    assert app._ger_dia_estourado("Ibirapuã II", 9, 16632.0, POT) is None          # o dia normal (~5 kWh/kWp)
    assert app._ger_dia_estourado("Ibirapuã II", 9, 12.0 * POT * 1000, POT) is None  # a potência o dia inteiro: no limite
    assert app._ger_dia_estourado("Ibirapuã I", 13, 10620888.0, POT) is None        # outra usina: nunca
    assert app._ger_dia_estourado("Ibirapuã II", 13, 10620888.0, None) is None      # sem potência: não julga


def _aba(ws, nome, linhas):
    ws.title = nome
    ws.append(["Usina", "Data", "Multimedidor SKID 1", "Inversor 1.1", "Inversor 1.2", "Validação", "IPOA DEF"])
    for dia, inv1, inv2, ipoa in linhas:
        ws.append([nome, datetime(2026, 10, dia), inv1 + inv2, inv1, inv2, 1, ipoa])


@pytest.fixture
def bd(tmp_path, monkeypatch):
    """Um BD_Performance com a Ibirapuã II (o dia 13 com os contadores acumulados) e a Ibirapuã I com a MESMA linha."""
    from openpyxl import Workbook
    wb = Workbook()
    dias = [(8, 8000.0, 8500.0, 5.0), (9, 8100.0, 8532.0, 5.0), (13, 4351190.0, 6269700.0, 5.1)]
    _aba(wb.active, "Ibirapuã II", dias)
    _aba(wb.create_sheet(), "Ibirapuã I", dias)
    arq = tmp_path / "bdp.xlsx"
    wb.save(arq)
    monkeypatch.setattr(app, "_bd_readable", lambda *a, **k: str(arq))
    monkeypatch.setattr(app, "INFO_GERAL", {
        "ibirapuaii": {"usina": "Ibirapuã II", "cliente": "Ultragaz", "potencia_mwp": POT},
        "ibirapuai": {"usina": "Ibirapuã I", "cliente": "Ultragaz", "potencia_mwp": POT}})
    monkeypatch.setattr(app, "pr_previsto", lambda *a, **k: None)
    return arq


def test_o_motor_do_bd_performance_tira_o_dia_estourado_de_tudo(bd):
    out = app._bdperf_prod_build(2026, 10)
    ii = out["ibirapuaii"]
    assert ii["prod_mwh"] == pytest.approx((16500.0 + 16632.0) / 1000)      # só 08 e 09/10
    assert ii["dias_cob"] == 2 and set(ii["ger_dia"]) == {8, 9}
    assert ii["dias_sem_leitura"] == [{"dia": 13, "ger_kwh": 10620890.0, "kwh_kwp": 3127.5}]
    assert ii["pr"] == pytest.approx(33132.0 / (POT * 1000 * 10.0) * 100, abs=0.01)   # o PR também sem o 13
    # a Ibirapuã I com a mesma linha NÃO é filtrada: o filtro é só da Ibirapuã II (pedido do Levi)
    i = out["ibirapuai"]
    assert i["dias_cob"] == 3 and i["dias_sem_leitura"] == []


def test_a_serie_diaria_do_nexus_fica_sem_geracao_e_sem_pr_no_dia_estourado(monkeypatch):
    # o PR diário do Painel NOC ainda tem o dia 13 (305%): no fato_desempenho_usina_dia ele sai sem geração e sem PR
    monkeypatch.setattr(app, "_ger_diario", lambda cli, usina, ano, mes: {"pontos": [
        {"dia": 9, "realizado": 0.75, "poa": 5.0}, {"dia": 13, "realizado": 3.05, "poa": 5.1}]})
    g = {"usinas": [{"usina": "Ibirapuã II", "cliente": "Ultragaz", "src": "bdperf", "ger_dia": {9: 16632.0},
                     "dias_sem_leitura": [{"dia": 13, "ger_kwh": 10620890.0, "kwh_kwp": 3127.5}],
                     "meta_dia_kwh": 4816.0}]}
    pts = {p["dia"]: p for p in app._ger_series_diarias(g, 2026, 10)["Ibirapuã II"]["pontos"]}
    assert pts[9]["geracao_kwh"] == 16632.0 and pts[9]["realizado"] == 0.75
    assert pts[13]["geracao_kwh"] is None and pts[13]["realizado"] is None and pts[13]["poa"] == 5.1


def test_a_tela_mostra_o_dia_sem_leitura_na_celula_da_geracao():
    src = (app._AQUI and open(app.os.path.join(app._AQUI, "templates", "gerencial.html"), encoding="utf-8").read())
    assert "dias_sem_leitura" in src and "sem leitura</span>" in src
