# -*- coding: utf-8 -*-
"""A usina sem conta pelas OS segue o Disp do Histórico Carteira (Levi, 12/11/2026: a equipe "adicionou disponibilidade
de Caroá na parte de histórico de carteira e não está subindo"). Dados fictícios, nada de rede."""
import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "thopen"))
import dashboard_thopen as d  # noqa: E402

D1, D2, D3 = dt.date(2026, 10, 1), dt.date(2026, 10, 2), dt.date(2026, 10, 3)
HIST = {"Usina M": {D1: {"disp": 1}, D2: {"disp": 0.875, "com": "Substituição do inversor 07" + chr(10) + "Religada às 15h"},
                   D3: {"disp": None}, dt.date(2026, 9, 30): {"disp": 0.5, "com": "de outro mês"}}}


@pytest.fixture
def dash(monkeypatch):
    monkeypatch.delenv("THOPEN_OPERACAO", raising=False)
    monkeypatch.setattr(d, "_sheet_records", lambda: HIST)
    monkeypatch.setattr(d, "_disp_excecao", lambda *a: None)
    monkeypatch.setattr(d, "_pelo_bd", lambda *a: False)
    return d


def test_o_disp_do_historico_em_porcento_so_do_mes(dash):
    assert dash._disp_hist_carteira("Usina M", 2026, 10) == {D1: 100.0, D2: 87.5}
    assert dash._disp_hist_carteira("Usina X", 2026, 10) == {}


def test_sem_conta_pelas_os_vale_o_historico(dash, monkeypatch):
    monkeypatch.setattr(dash, "_op_dados", lambda: {"x": 1})
    monkeypatch.setattr(dash.operacao_mes, "disp_por_dia", lambda *a, **k: {})
    assert dash._disp_dias("Usina M", 2026, 10) == {D1: 100.0, D2: 87.5}


def test_com_conta_pelas_os_o_historico_nao_entra(dash, monkeypatch):
    monkeypatch.setattr(dash, "_op_dados", lambda: {"x": 1})
    monkeypatch.setattr(dash.operacao_mes, "disp_por_dia", lambda *a, **k: {D1: 90.0})
    assert dash._disp_dias("Usina M", 2026, 10) == {D1: 90.0}


def test_carregando_nao_vira_historico(dash, monkeypatch):
    monkeypatch.setattr(dash, "_op_dados", lambda: None)
    assert dash._disp_dias("Usina M", 2026, 10) is None


def test_o_card_leva_o_historico_sem_conta_pelas_os(dash, monkeypatch):
    chamou = {}

    def resposta(dados, usina, ano, mes, hoje, trips=None, bd=None, disp=None, **k):
        chamou.update(disp=disp, bd=bd)
        return {"disponivel": False}
    monkeypatch.setattr(dash, "_op_dados", lambda: {"x": 1})
    monkeypatch.setattr(dash.operacao_mes, "disp_por_dia", lambda *a, **k: {})
    monkeypatch.setattr(dash.operacao_mes, "resposta", resposta)
    monkeypatch.setattr(dash, "_trips_da_tela", lambda *a: ({}, False))
    monkeypatch.setattr(dash, "_canais_da_contestacao", lambda: None)
    monkeypatch.setattr(dash, "_CARTEIRA_DE", dict(dash._CARTEIRA_DE, **{"Usina M": "Matrix"}))
    monkeypatch.setattr(dash, "_pode", lambda u: True)
    dash.app.test_client().get("/api/t/operacao?usina=Usina M&ano=2026&mes=10")
    # tudo do Histórico Carteira (12/11/2026, "puxa tudo de lá"): o número e o comentário, no modo do BD
    assert chamou["bd"] == ({D1: 100.0, D2: 87.5}, {D2: ["Substituição do inversor 07", "Religada às 15h"]})
    assert chamou["disp"] is None


def test_o_comentario_do_historico_so_do_mes(dash):
    assert dash._com_hist_carteira("Usina M", 2026, 10) == {D2: ["Substituição do inversor 07", "Religada às 15h"]}
    assert dash._com_hist_carteira("Usina M", 2026, 9) == {dt.date(2026, 9, 30): ["de outro mês"]}
