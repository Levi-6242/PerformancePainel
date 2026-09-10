# -*- coding: utf-8 -*-
"""Diagnóstico por DATA (07/09/2026) — "seria muito importante poder selecionar a data em todas as fontes".

O snapshot das fontes só fala do AGORA, mas o histórico existe espalhado. Estas são as duas portas que faltavam
para o seletor de data funcionar nas cinco fontes:

  1. `?dia=YYYY-MM-DD` em /api/<fonte>/inversores/energia-mes/<pid> devolve a energia POR INVERSOR daquele dia
     (banco no PG, aba do BD_Performance nas demais desde 08/09) — sem isso a coluna de energia não voltava no tempo;
  2. a análise de trackers do SunOp/Axis passou a aceitar um dia passado (PG, 2C e API PV já aceitavam).
"""
import pytest

import app


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    return app.app.test_client()


def test_energia_de_um_dia_pela_aba_do_bd_performance(cliente, monkeypatch):
    monkeypatch.setattr(app, "_bdperf_inv_dias", lambda u, a, m: {
        "2026-09-05": {"ipoa": 6.0, "inv": {"Inversor 1.1": 1200.0, "Inversor 1.2": 0.0}},
        "2026-09-06": {"ipoa": 5.5, "inv": {"Inversor 1.1": 1135.7}}} if (u == "CPP100" and (a, m) == (2026, 9)) else {})

    d = cliente.get("/api/athon/inversores/energia-mes/CPP100?usina=CPP100&dia=2026-09-06").get_json()
    assert d["dia"] == "2026-09-06" and d["origem"] == "bd_performance" and d["tem_dado"] is True
    assert d["inversores"] == {"Inversor 1.1": 1135.7}          # inversor sem número na linha não vira zero
    assert cliente.get("/api/athon/inversores/energia-mes/CPP100?usina=CPP100&dia=2026-09-05").get_json()["inversores"] == \
        {"Inversor 1.1": 1200.0, "Inversor 1.2": 0.0}           # zero medido é dado, e continua aparecendo
    # dia que a aba não fechou: responde vazio e DIZ que está vazio (a tela precisa distinguir de "zero gerado")
    vazio = cliente.get("/api/athon/inversores/energia-mes/CPP100?usina=CPP100&dia=2026-01-01").get_json()
    assert vazio["inversores"] == {} and vazio["tem_dado"] is False
    assert cliente.get("/api/athon/inversores/energia-mes/CPP100?dia=06-09-2026").status_code == 400
    # e o mês continua funcionando como antes
    assert cliente.get("/api/athon/inversores/energia-mes/CPP100?usina=CPP100&mes=2026-09").get_json()["dias"] == 2


def test_energia_de_um_dia_no_thopen_vem_do_bd_thopen(cliente, monkeypatch):
    """Usina Thopen: a aba diária do BD_Thopen (Levi, 08/09), com os nomes da aba traduzidos pelo PR de hoje."""
    chamadas = []

    def _dias(usina, ano, mes):
        chamadas.append((usina, ano, mes))
        return {"2026-09-06": {"ipoa": 4.2, "inv": {"inversor 10": 402.5}}} if usina == "Ibaté 1" else {}
    monkeypatch.setattr(app, "_bdthopen_inv_dias", _dias)
    monkeypatch.setattr(app, "_pg_pr_get", lambda dia, force=False: ([], {27: [{"id": 10, "nome": "Inversor 1.10", "nome_api": "inversor 10", "pot_kwp": 250.0}]}))
    d = cliente.get("/api/pg/inversores/energia-mes/27?usina=Ibat%C3%A9%201&dia=2026-09-06").get_json()
    assert chamadas == [("Ibaté 1", 2026, 9)]
    assert d["origem"] == "bd_thopen" and d["inversores"] == {"Inversor 1.10": 402.5} and d["tem_dado"] is True
    vazio = cliente.get("/api/pg/inversores/energia-mes/27?usina=Outra&dia=2026-09-06").get_json()
    assert vazio["tem_dado"] is False and "BD_Thopen" in vazio["motivo"]
    m = cliente.get("/api/pg/inversores/energia-mes/27?usina=Ibat%C3%A9%201&mes=2026-09").get_json()
    assert m["origem"] == "bd_thopen" and m["inversores"] == {"Inversor 1.10": 402.5} and m["dias"] == 1


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
