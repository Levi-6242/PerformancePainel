# -*- coding: utf-8 -*-
"""Energia de HOJE por inversor no detalhe do Thopen (PG) e da SolarEdge (07/09/2026).

"Ipixuna 1, Ibaté 1 ou Colider 1 [...] não estão mostrando a energia do dia mesmo mostrando o PR" — o detalhe por
inversor dessas duas fontes gravava eday=None fixo, enquanto o cache de PR do dia já tinha a geração de cada inversor
(banco no PG, render-chart na SolarEdge). Agora o detalhe casa os dois: por id, depois nome da fonte, depois nome de
exibição. De quebra a RenoGrid deixou de ler o balde do 2C no energia-mes (era traduzida para 'owen')."""
import copy

import pytest

import app


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    return app.app.test_client()


def test_casa_por_id_depois_por_nome():
    invs = [{"id": 171, "nome": "Inversor 1.1", "nome_api": "INV 1", "eday": None},
            {"id": 172, "nome": "Inversor 1.2", "nome_api": "INV 2", "eday": None},
            {"id": 999, "nome": "Inversor 1.3", "nome_api": "INV 3", "eday": None},
            {"id": 998, "nome": "Inversor 1.4", "nome_api": "x",     "eday": None},
            {"id": 997, "nome": "Inversor 1.5", "nome_api": "INV 5", "eday": None}]
    pr = [{"id": 171,   "nome": "Inversor 1.1", "nome_api": "INV 1", "geracao_kwh": 631.4},
          {"id": "172", "nome": "Inversor 1.2", "nome_api": "INV 2", "geracao_kwh": 0.0},    # id vira texto dos dois lados
          {"id": 3,     "nome": "outro",        "nome_api": "INV 3", "geracao_kwh": 666.7},  # só o nome da fonte bate
          {"id": 4,     "nome": "Inversor 1.4", "nome_api": "y",     "geracao_kwh": 581.3},  # só o nome de exibição bate
          {"id": 997,   "nome": "Inversor 1.5", "nome_api": "INV 5", "geracao_kwh": None}]   # PR sem geração: não inventa
    assert app._inv_eday_do_pr(invs, pr) == 4
    assert [i["eday"] for i in invs] == [631.4, 0.0, 666.7, 581.3, None]   # zero medido é dado (inversor parado), não ausência
    assert app._inv_eday_do_pr(invs, []) == 0 and app._inv_eday_do_pr([], pr) == 0


def test_pg_detalhe_traz_a_energia_do_dia(cliente, monkeypatch):
    snap = {20: [{"id": 171, "nome": "Inversor 1.1", "nome_api": "INV 1", "strings": [], "strings_ativas": 0,
                  "str_esp": 12, "produzindo": None, "eday": None},
                 {"id": 175, "nome": "Inversor 1.5", "nome_api": "INV 5", "strings": [], "strings_ativas": 0,
                  "str_esp": 12, "produzindo": None, "eday": None}]}
    monkeypatch.setattr(app, "_pg_get_snapshot", lambda force=False: ([], copy.deepcopy(snap)))
    pedidos = []

    def _pr(dia, force=False):
        pedidos.append(dia)
        return [], {20: [{"id": 171, "nome": "Inversor 1.1", "nome_api": "INV 1", "geracao_kwh": 631.4, "pr": None}]}
    monkeypatch.setattr(app, "_pg_pr_get", _pr)
    d = cliente.get("/api/pg/plant/20?date=2026-01-01").get_json()
    assert pedidos == [app.datetime.now().date().isoformat()], "o detalhe é de agora: pede o PR de HOJE, não o ?date="
    assert {i["nome"]: i["eday"] for i in d["inversores"]} == {"Inversor 1.1": 631.4, "Inversor 1.5": None}
    # banco fora do ar no PR: o detalhe continua respondendo, só sem energia
    def _cai(dia, force=False):
        raise RuntimeError("sem banco")
    monkeypatch.setattr(app, "_pg_pr_get", _cai)
    r = cliente.get("/api/pg/plant/20")
    assert r.status_code == 200 and [i["eday"] for i in r.get_json()["inversores"]] == [None, None]


def test_solaredge_detalhe_traz_a_energia_do_dia(cliente, monkeypatch):
    monkeypatch.setattr(app, "EQUIP_NAMES", {})
    monkeypatch.setattr(app, "ESPERADO_INV", {})
    monkeypatch.setattr(app, "se_sites", lambda: [{"id": 4425864, "nome": "UFV Colider 1", "timezone": "America/Cuiaba"}])
    monkeypatch.setattr(app, "se_devices", lambda sid: [
        {"deviceType": "INVERTER", "deviceSerial": "7B0C4F8D", "deviceName": "Inverter 1"},
        {"deviceType": "INVERTER", "deviceSerial": "7E05ABED", "deviceName": "Inverter 3"},
        {"deviceType": "STRING", "deviceSerial": "s1", "deviceName": "String 1.1", "partOfSerial": "7B0C4F8D"},
        {"deviceType": "STRING", "deviceSerial": "s3", "deviceName": "String 3.1", "partOfSerial": "7E05ABED"}])
    # 3º valor = lotes que falharam (desde 09/09/2026): lote falho não pode virar string morta
    monkeypatch.setattr(app, "se_string_power", lambda sid, uuids, tz: ({"s1": 900.0, "s3": 0.0}, None, 0))
    monkeypatch.setattr(app, "_se_pr_get", lambda dia, force=False: ([], {4425864: [
        {"id": "7B0C4F8D", "nome": "Inverter 1", "nome_api": "Inverter 1", "geracao_kwh": 572.2, "pr": 0.824},
        {"id": "7E05ABED", "nome": "Inverter 3", "nome_api": "Inverter 3", "geracao_kwh": 399.9, "pr": 0.576}]}))
    d = cliente.get("/api/solaredge/plant/4425864").get_json()
    assert {i["nome_api"]: i["eday"] for i in d["inversores"]} == {"Inverter 1": 572.2, "Inverter 3": 399.9}
    assert d["inversores"][0]["strings"][0]["ativa"] is True          # o resto do detalhe segue igual
    assert app._se_plant_inversores(4425864)[0]["eday"] == 572.2      # o detalhe também é montado fora da rota
    monkeypatch.setattr(app, "_se_cache", {"payload": {"rows": [{"plant_id": 4425864, "usina": "Colider 1"}]}, "ts": 0.0})
    assert app._nome_da_planta("solaredge", 4425864) == "Colider 1"   # nome = chave da aba do BD_Performance


def test_energia_mes_da_solaredge_le_a_aba_da_usina(cliente, monkeypatch):
    """Antes, 'solaredge' era traduzido para 'owen' (2C) e o ?dia=/?mes= da RenoGrid vinham sempre vazios."""
    vistos = []
    monkeypatch.setattr(app, "_bdperf_inv_dias", lambda u, a, m: vistos.append(u) or (
        {"2026-09-06": {"ipoa": 5.7, "inv": {"Inversor 1.1": 572.2}}} if u == "Colider 1" else {}))
    d = cliente.get("/api/solaredge/inversores/energia-mes/4425864?usina=Colider%201&mes=2026-09").get_json()
    assert d["origem"] == "bd_performance" and d["inversores"] == {"Inversor 1.1": 572.2} and vistos == ["Colider 1"]
    assert cliente.get("/api/solaredge/inversores/energia-mes/4425864?usina=Colider%201&dia=2026-09-06").get_json()["tem_dado"] is True
