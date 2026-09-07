# -*- coding: utf-8 -*-
"""Diagnóstico por DATA (07/09/2026) — "seria muito importante poder selecionar a data em todas as fontes".

O snapshot das fontes só fala do AGORA, mas o histórico existe espalhado. Estas são as duas portas que faltavam
para o seletor de data funcionar nas cinco fontes:

  1. `?dia=YYYY-MM-DD` em /api/<fonte>/inversores/energia-mes/<pid> devolve a energia POR INVERSOR daquele dia
     (banco no PG, acumulador nas demais) — sem isso a coluna de energia não tinha como voltar no tempo;
  2. a análise de trackers do SunOp/Axis passou a aceitar um dia passado (PG, 2C e API PV já aceitavam).
"""
import pytest

import app


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    return app.app.test_client()


def test_energia_de_um_dia_pelo_acumulador(cliente, tmp_path, monkeypatch):
    monkeypatch.setattr(app, "_INV_ENERGIA_PATH", str(tmp_path / "e.json"))
    app._inv_energia_registrar("sunop", "CPP100", "2026-09-05", {"Inversor 1.1": 1200.0, "Inversor 1.2": 0.0})
    app._inv_energia_registrar("sunop", "CPP100", "2026-09-06", {"Inversor 1.1": 1135.7, "Inversor 1.2": None})

    d = cliente.get("/api/athon/inversores/energia-mes/CPP100?dia=2026-09-06").get_json()
    assert d["dia"] == "2026-09-06" and d["origem"] == "acumulador" and d["tem_dado"] is True
    assert d["inversores"] == {"Inversor 1.1": 1135.7}          # None não vira zero: é ausência de leitura
    assert cliente.get("/api/athon/inversores/energia-mes/CPP100?dia=2026-09-05").get_json()["inversores"] == \
        {"Inversor 1.1": 1200.0, "Inversor 1.2": 0.0}           # zero medido é dado, e continua aparecendo
    # dia sem fotografia: responde vazio e DIZ que está vazio (a tela precisa distinguir de "zero gerado")
    vazio = cliente.get("/api/athon/inversores/energia-mes/CPP100?dia=2026-01-01").get_json()
    assert vazio["inversores"] == {} and vazio["tem_dado"] is False
    assert cliente.get("/api/athon/inversores/energia-mes/CPP100?dia=06-09-2026").status_code == 400
    # e o mês continua funcionando como antes
    assert cliente.get("/api/athon/inversores/energia-mes/CPP100?mes=2026-09").get_json()["dias"] == 2


def test_energia_de_um_dia_no_pg_vem_do_banco(cliente, monkeypatch):
    chamadas = []

    def _pivo(ini, fim):
        chamadas.append((ini, fim))
        return [{"plant_id": 27, "dias": [{"data": "2026-09-06", "ger": {"Inversor 1.1": 402.5, "Inversor 1.2": None}}]}]
    monkeypatch.setattr(app, "_pg_gerpivo_get", _pivo)
    d = cliente.get("/api/pg/inversores/energia-mes/27?dia=2026-09-06").get_json()
    assert chamadas == [("2026-09-06", "2026-09-06")], "pediu um intervalo em vez do dia pedido"
    assert d["origem"] == "banco" and d["inversores"] == {"Inversor 1.1": 402.5} and d["tem_dado"] is True
    monkeypatch.setattr(app, "_pg_gerpivo_get", lambda *a: [])
    assert cliente.get("/api/pg/inversores/energia-mes/27?dia=2026-09-06").get_json()["tem_dado"] is False


def test_trackers_do_sunop_aceitam_dia_passado(monkeypatch):
    """A curva histórica sempre existiu (o gráfico usa); só a ANÁLISE estava presa em hoje."""
    import inspect
    src = inspect.getsource(app._sunop_trackers_plant_curva)
    assert "data: str = None" in src, "a análise voltou a não aceitar data"
    assert "datetime.now().strftime(\"%Y-%m-%d\")" in src and "_dia = data or" in src   # hoje segue sendo o padrão
    pedidos = []
    monkeypatch.setattr(app, "_sunop_trk_curvas", lambda p, d, i: pedidos.append(d) or {"posat": {}, "posal": {}})
    monkeypatch.setattr(app, "_si", lambda inst: {"meta": {"CPP100": {"trackers": {"TRK_1": {}}}}})
    app._sunop_trackers_plant_curva("CPP100", "gridco", data="2026-09-05")
    app._sunop_trackers_plant_curva("CPP100", "gridco")
    assert pedidos[0] == "2026-09-05", "ignorou o dia pedido"
    assert pedidos[1] != "2026-09-05" and len(pedidos[1]) == 10, "sem data deveria usar hoje"


def test_todas_as_fontes_tem_porta_de_data():
    """As 5 rotas de tracker por usina leem ?date= — é o que sustenta "a data em todas as fontes"."""
    import inspect
    for fn in (app.api_pg_trackers_plant, app.api_owen_trackers_plant,
               app.api_sunop_trackers_plant, app.api_pv_trackers_plant):
        src = inspect.getsource(fn)
        assert 'args.get("date")' in src, f"{fn.__name__} não aceita ?date="
