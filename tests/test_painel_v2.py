# -*- coding: utf-8 -*-
"""Diagnóstico de usina v2 (inversor no centro, 06/09/2026):
  1. /painel/usina/<id> serve a versão nova; ?antigo=1 serve a anterior intacta (a reserva que o Levi pediu);
  2. a energia por inversor vem SÓ das bases aprovadas — banco (PG) e BD_Performance (08/09/2026). O acumulador
     noturno, que fotografava o eday de ~70 usinas pela API todo dia, foi removido: gastava requisição e era uma
     quarta base que ninguém auditava. Usina sem aba responde vazio COM motivo, para a lacuna virar tarefa da coleta.
"""
import pathlib

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


def test_energia_mes_le_a_aba_do_bd_performance(cliente, monkeypatch):
    """Fonte que não é PG: aba da usina no BD_Performance, só dias fechados. Sem aba, vazio com o motivo."""
    chamadas = []

    def _dias(usina, ano, mes):
        chamadas.append((usina, ano, mes))
        if usina != "CPP100":
            return {}
        return {"2026-09-05": {"ipoa": 6.0, "inv": {"Inversor 1.1": 1200.0, "Inversor 1.2": 1100.0}},
                "2026-09-06": {"ipoa": None, "inv": {"Inversor 1.1": 1135.7}},
                "2026-09-07": {"ipoa": 5.0, "inv": {}}}          # dia com IPOA mas sem inversor: não entra na soma
    monkeypatch.setattr(app, "_bdperf_inv_dias", _dias)
    d = cliente.get("/api/athon/inversores/energia-mes/CPP100?usina=CPP100&mes=2026-09").get_json()
    assert chamadas == [("CPP100", 2026, 9)], "'athon' tem de virar a aba da usina, não outro balde"
    assert d["origem"] == "bd_performance" and d["motivo"] is None
    assert d["inversores"] == {"Inversor 1.1": 2335.7, "Inversor 1.2": 1100.0}
    assert d["dias"] == 2 and d["dias_lista"] == ["2026-09-05", "2026-09-06"]
    um = cliente.get("/api/athon/inversores/energia-mes/CPP100?usina=CPP100&dia=2026-09-06").get_json()
    assert um["inversores"] == {"Inversor 1.1": 1135.7} and um["tem_dado"] is True and um["origem"] == "bd_performance"
    # usina sem aba: vazio E com o motivo — é assim que a lacuna aparece, em vez de um número que só a plataforma tinha.
    # Coração 2 é do cliente Thopen: desde 11/09 vai ao BD_Thopen primeiro (qualquer fonte), e o motivo aponta para lá.
    monkeypatch.setattr(app, "_bdthopen_inv_dias", lambda u, a, m: {})
    sem = cliente.get("/api/pv/inversores/energia-mes/18747863?usina=Cora%C3%A7%C3%A3o%202&mes=2026-09").get_json()
    assert sem["inversores"] == {} and sem["dias"] == 0 and "BD_Thopen" in sem["motivo"]
    outra = cliente.get("/api/solaredge/inversores/energia-mes/1?usina=Xavantina%201&mes=2026-09").get_json()   # RenoGrid
    assert outra["inversores"] == {} and outra["dias"] == 0 and "BD_Performance" in outra["motivo"]
    assert cliente.get("/api/pv/inversores/energia-mes/1?mes=x").status_code == 400


def test_nome_da_usina_sai_do_overview_em_cache(monkeypatch):
    """A aba do BD_Performance é achada pelo NOME; as telas mandam ?usina=, e sem ele o id é resolvido no cache."""
    monkeypatch.setattr(app, "_cache", {"payload": {"rows": [{"plant_id": 18747567, "usina": "Coração 2 (312)"}]}})
    assert app._nome_da_planta("pv", "18747567") == "Coração 2"      # o "(312)" do overview não existe na planilha
    assert app._nome_da_planta("pv", 99) == "" and app._nome_da_planta("inexistente", 1) == ""


def test_acumulador_noturno_foi_removido():
    """Economia de requisição: a varredura das 19:30 chamava a API de cada usina todo dia só para gravar um arquivo."""
    src = pathlib.Path(app.__file__).read_text(encoding="utf-8")
    for morto in ("_inv_energia_ler", "_inv_energia_registrar", "_inv_energia_loop", "_inv_energia_snapshot",
                  "_INV_ENERGIA_PATH", "inv_energia_dia.json", "_se_mes_get"):
        assert morto not in src, f"{morto} voltou ao app.py"        # api_inv_energia_mes é a ROTA, e continua
    for n in ("_inv_energia_loop", "_inv_energia_ler", "_inv_energia_registrar", "_se_mes_get"):
        assert not hasattr(app, n), f"{n} voltou"


def test_historico_do_mes_tem_drill_down_disp_e_sem_botao_antigo(cliente):
    """Lote de 11/09 (Levi): sem o botão "versão anterior"; a linha do dia abre o drill-down com a curva (correlação
    inversor × irradiância × temperatura, séries ligáveis, e strings); coluna "% disp" pela régua do Gerencial; a coluna
    "fonte" saiu da tabela e virou legenda; de madrugada a aba Curvas recua para ontem em vez de ficar vazia."""
    html = cliente.get("/painel/usina/18747567?fonte=pv&nome=Colorado%202").get_data(as_text=True)
    assert "v2Antigo" not in html and "versão anterior" not in html
    assert "v2HistToggle(" in html and "function v2HistDrawDia" in html and "v2CorrTog(" in html
    assert "% disp" in html and "function _dispDia" in html
    assert "DISP_TIPOS=new Set(['religamento','religamento remoto','corretiva emergencial'])" in html
    assert "<th>fonte</th>" not in html and "fonte da geração:" in html
    assert "_icRecuou" in html and "mostrando ontem" in html
    # a antiga (reserva) continua servida por ?antigo=1 — só o botão que levava a ela saiu
    assert 'id="v2-inv"' not in cliente.get("/painel/usina/18747567?fonte=pv&antigo=1").get_data(as_text=True)
