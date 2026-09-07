# -*- coding: utf-8 -*-
"""Diagnóstico de usina v2 (inversor no centro, 06/09/2026):
  1. /painel/usina/<id> serve a versão nova; ?antigo=1 serve a anterior intacta (a reserva que o Levi pediu);
  2. o acumulador diário de energia por inversor soma só os dias do mês pedido, sobrescreve o dia refotografado
     e não quebra sem arquivo.
"""
import json

import pytest

import app


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")          # app aberto no teste
    return app.app.test_client()


def test_rota_serve_a_nova_e_guarda_a_antiga(cliente, monkeypatch):
    novo = cliente.get("/painel/usina/CPP100?fonte=athon&nome=CPP100").get_data(as_text=True)
    assert 'id="v2-inv"' in novo and "V2_SK" in novo                      # marcador só da v2
    assert "Inversores × strings" in novo                                  # o mapa antigo continua lá, na aba Mês
    antigo = cliente.get("/painel/usina/CPP100?fonte=athon&nome=CPP100&antigo=1").get_data(as_text=True)
    assert 'id="v2-inv"' not in antigo and "Inversores × strings" in antigo
    monkeypatch.setattr(app, "_PAINEL_USINA_PADRAO", "antigo")           # inverte o padrão sem código
    assert 'id="v2-inv"' not in cliente.get("/painel/usina/18747567?fonte=pv").get_data(as_text=True)
    assert 'id="v2-inv"' in cliente.get("/painel/usina/18747567?fonte=pv&novo=1").get_data(as_text=True)


def test_acumulador_soma_o_mes_e_sobrescreve_o_dia(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "_INV_ENERGIA_PATH", str(tmp_path / "inv_energia_dia.json"))
    assert app._inv_energia_ler() == {}                                    # sem arquivo = vazio, sem erro
    assert app._inv_energia_registrar("pv", 18747567, "2026-09-06", {"Inversor 1.1": 212.55, "Inversor 1.2": None}) == 1
    app._inv_energia_registrar("pv", 18747567, "2026-09-05", {"Inversor 1.1": 1400.0, "Inversor 1.2": 1380.2})
    app._inv_energia_registrar("pv", 18747567, "2026-08-31", {"Inversor 1.1": 999.0})       # outro mês: fora da soma
    app._inv_energia_registrar("pv", 18747567, "2026-09-06", {"Inversor 1.1": 1500.0, "Inversor 1.2": 1490.0})   # refoto do dia
    store = json.loads((tmp_path / "inv_energia_dia.json").read_text(encoding="utf-8"))
    assert store["pv"]["18747567"]["2026-09-06"] == {"Inversor 1.1": 1500.0, "Inversor 1.2": 1490.0}
    m = app._inv_energia_mes(store, "pv", 18747567, 2026, 9)
    assert m["dias"] == 2 and m["dias_lista"] == ["2026-09-05", "2026-09-06"]
    assert m["inversores"] == {"Inversor 1.1": 2900.0, "Inversor 1.2": 2870.2} and m["origem"] == "acumulador"
    assert app._inv_energia_mes(store, "pv", 18747567, 2026, 8)["inversores"] == {"Inversor 1.1": 999.0}
    assert app._inv_energia_mes(store, "sunop", "CPP100", 2026, 9) == {"mes": "09/2026", "dias": 0, "dias_lista": [], "inversores": {}, "origem": "acumulador"}
    assert app._inv_energia_registrar("pv", 1, "2026-09-06", {}) == 0


def test_energia_mes_endpoint_le_o_acumulador(cliente, tmp_path, monkeypatch):
    monkeypatch.setattr(app, "_INV_ENERGIA_PATH", str(tmp_path / "e.json"))
    app._inv_energia_registrar("sunop", "CPP100", "2026-09-06", {"Inversor 1.1": 1135.7})
    d = cliente.get("/api/athon/inversores/energia-mes/CPP100?mes=2026-09").get_json()   # 'athon' vira 'sunop'
    assert d["inversores"] == {"Inversor 1.1": 1135.7} and d["dias"] == 1
    assert cliente.get("/api/pv/inversores/energia-mes/1?mes=x").status_code == 400
