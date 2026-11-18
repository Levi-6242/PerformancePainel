# -*- coding: utf-8 -*-
"""Recoleta da SolarEdge (RenoGrid) para a Coletas do Nexus (17/11/2026). A regra é a do coletor da noite
(`coleta API PV/src/coletar_solaredge.py`): energia AC do dia por inversor no fuso da usina, IPOA pelo render-chart do
mês com Colider 2 e Xavantina 2 espelhando a 1, tradução pela aba Equipamentos. A SolarEdge não é chamada: os clientes
da plataforma são dublados e a rede fica cortada no teste inteiro."""
import datetime as dt
import types

import pytest
import requests

import app
import recoleta_apipv as rc
import recoleta_fontes
from recoleta_fontes import comum, solaredge as se

HOJE = dt.date(2026, 11, 17)
D10, D11 = dt.date(2026, 11, 10), dt.date(2026, 11, 11)
# trechos da aba Equipamentos real (espelho do BD_Performance de 17/11): a SolarEdge chama "Inverter N" e o BD
# "Inversor U.N"; na Nobres a coluna é "Inversor N"
EQUIP = ([{"Usina Supervisório": "UFV Xavantina 2", "Equipamento Supervisório": "Inverter %d" % n,
           "Usina": "Xavantina 2", "Equipamento": "Inversor 1.%d" % n} for n in (1, 2, 3)]
         + [{"Usina Supervisório": "UFV Colider 1", "Equipamento Supervisório": "Inverter 1", "Usina": "Colider 1",
             "Equipamento": "Inversor 1.1"},
            {"Usina Supervisório": "UFV Colider 2", "Equipamento Supervisório": "Inverter 1", "Usina": "Colider 2",
             "Equipamento": "Inversor 1.1"},
            {"Usina Supervisório": "UFV Nobres", "Equipamento Supervisório": "Inverter 1", "Usina": "Nobres",
             "Equipamento": "Inversor 1"}])
SITES = [{"id": 4425864, "nome": "UFV Colider 1", "timezone": "America/Cuiaba"},
         {"id": 4425870, "nome": "UFV Colider 2", "timezone": "America/Cuiaba"},
         {"id": 4400002, "nome": "UFV Xavantina 2", "timezone": "America/Cuiaba"},
         {"id": 4400005, "nome": "UFV Nobres", "timezone": None},
         {"id": 4499999, "nome": "UFV Fora do Cadastro", "timezone": "America/Sao_Paulo"}]


def _inv(serial, nome):
    return {"deviceType": "INVERTER", "deviceSerial": serial, "deviceName": nome}


DEVS = {4400002: [_inv("7E0001", "Inverter 1"), _inv("7E0002", "inverter  2"), _inv("7E0003", "Inverter 3"),
                  _inv("7E0099", "Inverter 99"),
                  {"deviceType": "STRING", "deviceSerial": "uuid-1", "deviceName": "String 1.1"}],
        4425864: [_inv("C10001", "Inverter 1")],
        4425870: [_inv("C20001", "Inverter 1")],
        4400005: [_inv("NB0001", "Inverter 1")]}


@pytest.fixture(autouse=True)
def _sem_rede(monkeypatch):
    """Nenhum pedido sai da máquina: o dublê errado quebra o teste em vez de ir à SolarEdge de verdade."""
    def _recusa(self, request, *a, **k):
        raise AssertionError("pedido de rede no teste da SolarEdge: %s" % request.url)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", _recusa)
    monkeypatch.setattr(comum, "_CONTA", {})


class Resp:
    def __init__(self, status=200, corpo=None, sem_corpo=False):
        self.status_code, self._c, self._sem = status, corpo, sem_corpo

    def json(self):
        if self._sem:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._c


def energia(por_serial):
    """Resposta do generate-chart: um dataset por serial, linhas [instante, Wh]."""
    return Resp(200, {"meta": {"datasetsMeta": [{"reportObject": {"entityId": s}} for s in por_serial]},
                      "data": [por_serial[s] for s in por_serial]})


class Sessao:
    def __init__(self, responder):
        self.responder, self.pedidos = responder, []

    def post(self, url, headers=None, json=None, timeout=None, **_):
        self.pedidos.append({"url": url, "json": json, "headers": headers})
        return self.responder(url, json)


def ms(iso):
    return int(dt.datetime.fromisoformat(iso).timestamp() * 1000)


def irr_serie(pontos, nome="Global Irradiance"):
    return [{"name": "Energy Produced (C10001)", "data": [[ms("2026-11-10T04:00:00+00:00"), 612000.0]]},
            {"name": nome, "data": pontos}]


def ctx_de(responder=None, render=None, devs=None, falha=None, sites=None):
    se._SITES.update(v=None, t=0.0)          # cada contexto é uma SolarEdge nova: nada dos sites guardado (6 h no módulo)
    sessao = Sessao(responder or (lambda url, corpo: Resp(500)))
    renders = []

    def _render(sid, serials):
        renders.append((sid, list(serials)))
        return render(sid) if render else None

    ctx = types.SimpleNamespace(mapa=comum.Mapa(EQUIP), sites=lambda: list(SITES if sites is None else sites),
                                devices=lambda sid: list((DEVS if devs is None else devs).get(int(sid), [])),
                                dev_falha=falha or {}, render_mes=_render, http=lambda: sessao,
                                headers=lambda: {"cookie": "se_monitoring_auth=teste"}, base="https://se.teste")
    return ctx, sessao, renders


# ---------------------------------------------------------------- a energia do dia por inversor e a tradução
def test_energia_do_dia_por_inversor_traduzida_pela_aba_equipamentos():
    def responder(url, corpo):
        assert url == "https://se.teste/services/cni/ui-api/pages/site/analysis/custom/site/4400002/generate-chart"
        return energia({"7E0001": [["2026-11-10T04:00:00Z", 600000.0], ["2026-11-11T00:00:00Z", 12345.0]],
                        "7E0002": [["2026-11-10T04:00:00Z", 0.0]],              # a fonte disse 0: é 0
                        "7E0003": [["2026-11-10T04:00:00Z", None]]})            # sem leitura: nulo, não 0
    ctx, sessao, _ = ctx_de(responder)
    r = se.buscar(ctx, ["4400002"], [D10], True, False, False)

    assert r["geracao"] == [
        {"usina": "Xavantina 2", "inversor": "Inversor 1.1", "data": "2026-11-10", "kwh": 612.35},   # soma das linhas
        {"usina": "Xavantina 2", "inversor": "Inversor 1.2", "data": "2026-11-10", "kwh": 0.0},
        {"usina": "Xavantina 2", "inversor": "Inversor 1.3", "data": "2026-11-10", "kwh": None}]
    corpo = sessao.pedidos[0]["json"]
    ds = corpo["datasources"][0]
    assert ds["metrics"] == [{"metricType": "measurement", "metricsCategoryName": "pv_measurements",
                              "uri": "energy_since_last_telemetry"}]                 # a métrica do coletor
    assert ds["alignmentGranularity"] == "DAY" and ds["datasourcePopulation"]["deviceType"] == "INVERTER"
    assert ds["datasourcePopulation"]["siteId"] == 4400002
    # só os inversores com de-para vão no pedido; a string e o "Inverter 99" não
    assert ds["datasourcePopulation"]["deviceSerials"] == ["7E0001", "7E0002", "7E0003"]
    txt = " | ".join(r["avisos"])
    assert "UFV Xavantina 2 · Inverter 99" in txt and "sem de-para" in txt
    assert "Inversor 1.3" in txt and "nulos, não 0" in txt
    assert r["escalares"] == []


def test_lote_de_50_serials_por_pedido():
    devs = {4400002: [_inv("S%02d" % i, "Inverter %d" % i) for i in range(1, 61)]}
    mapa = comum.Mapa([{"Usina Supervisório": "UFV Xavantina 2", "Equipamento Supervisório": "Inverter %d" % i,
                        "Usina": "Xavantina 2", "Equipamento": "Inversor %d" % i} for i in range(1, 61)])
    ctx, sessao, _ = ctx_de(lambda url, c: energia({s: [["t", 1000.0]]
                                                    for s in c["datasources"][0]["datasourcePopulation"]
                                                    ["deviceSerials"]}), devs=devs)
    ctx.mapa = mapa
    r = se.buscar(ctx, ["4400002"], [D10], True, False, False)
    assert [len(p["json"]["datasources"][0]["datasourcePopulation"]["deviceSerials"]) for p in sessao.pedidos] == [50, 10]
    assert len(r["geracao"]) == 60 and all(g["kwh"] == 1.0 for g in r["geracao"])


# ---------------------------------------------------------------- o fuso da usina
def test_dia_cortado_no_fuso_da_usina():
    agora = dt.datetime(2026, 11, 17, 15, 0, tzinfo=dt.timezone.utc)
    assert se.dia_utc("America/Cuiaba", D10, agora) == ("2026-11-10T04:00:00.000Z", "2026-11-11T03:59:59.999Z")
    assert se.dia_utc("America/Fortaleza", D10, agora) == ("2026-11-10T03:00:00.000Z", "2026-11-11T02:59:59.999Z")
    assert se.dia_utc("America/Sao_Paulo", "2026-11-10", agora)[0] == "2026-11-10T03:00:00.000Z"
    # sem fuso (ou nome inválido): Brasília, nunca UTC (o servidor roda em UTC: seriam 3 h fora)
    assert se.dia_utc(None, D10, agora)[0] == "2026-11-10T03:00:00.000Z"
    assert se.dia_utc("Marte/Olympus", D10, agora)[0] == "2026-11-10T03:00:00.000Z"
    # 00:30 de Brasília do dia 11 = 23:30 de Cuiabá do dia 10: o dia de lá ainda não fechou, o pedido vai até agora
    meia_noite_e_meia = dt.datetime(2026, 11, 11, 3, 30, tzinfo=dt.timezone.utc)
    assert se.dia_utc("America/Cuiaba", D10, meia_noite_e_meia) == ("2026-11-10T04:00:00.000Z",
                                                                     "2026-11-11T03:30:00.999Z")


def test_pedido_leva_o_dia_da_usina_e_avisa_sem_fuso():
    ctx, sessao, _ = ctx_de(lambda url, c: energia({"NB0001": [["t", 700000.0]]}))
    r = se.buscar(ctx, ["4400005"], [D10], True, False, False)                          # Nobres veio sem timeZone
    assert sessao.pedidos[0]["json"]["reportPeriod"] == {"from": "2026-11-10T03:00:00.000Z",
                                                        "to": "2026-11-11T02:59:59.999Z"}
    assert r["geracao"] == [{"usina": "Nobres", "inversor": "Inversor 1", "data": "2026-11-10", "kwh": 700.0}]
    assert any("fuso" in a and "Brasília" in a for a in r["avisos"])

    ctx, sessao, _ = ctx_de(lambda url, c: energia({"7E0001": [["t", 1.0]], "7E0002": [["t", 1.0]],
                                                    "7E0003": [["t", 1.0]]}))
    r = se.buscar(ctx, ["4400002"], [D10, D11], True, False, False)                     # Xavantina 2, Cuiabá
    assert [p["json"]["reportPeriod"]["from"] for p in sessao.pedidos] == ["2026-11-10T04:00:00.000Z",
                                                                          "2026-11-11T04:00:00.000Z"]
    assert not any("fuso" in a for a in r["avisos"])


# ---------------------------------------------------------------- o IPOA e o espelho de irradiância
def test_ipoa_pela_regra_do_coletor_e_o_espelho_da_irmã():
    def render(sid):
        if sid == 4425864:                                                  # Colider 1: tem a estação
            return irr_serie([[ms("2026-11-10T04:00:00+00:00"), 22000.0],   # 22000 × 0,25 / 1000 = 5,5
                              [ms("2026-11-11T04:00:00+00:00"), 25320.0],   # 6,33
                              [ms("2026-11-12T04:00:00+00:00"), None]])
        return irr_serie([[ms("2026-11-10T04:00:00+00:00"), 99999.0]])     # a da Colider 2 nunca vale
    ctx, sessao, renders = ctx_de(render=render)
    r = se.buscar(ctx, ["4425870", "4425864"], [D10, D11], False, True, False)

    assert r["escalares"] == [
        {"usina": "Colider 2", "data": "2026-11-10", "coluna": "IPOA (kWh/m²)", "valor": 5.5},
        {"usina": "Colider 2", "data": "2026-11-11", "coluna": "IPOA (kWh/m²)", "valor": 6.33},
        {"usina": "Colider 1", "data": "2026-11-10", "coluna": "IPOA (kWh/m²)", "valor": 5.5},
        {"usina": "Colider 1", "data": "2026-11-11", "coluna": "IPOA (kWh/m²)", "valor": 6.33}]
    assert renders == [(4425864, ["C10001"])]          # um render-chart só, o da 1, pelo 1º inversor (como o coletor)
    assert sessao.pedidos == [] and r["geracao"] == []                   # sem Geração pedida, nenhum generate-chart
    assert se.COLUNA_IPOA == "IPOA (kWh/m²)"                             # o cabeçalho exato das 7 abas


def test_ipoa_que_nao_veio_e_aviso_e_nao_zero():
    ctx, _, _ = ctx_de(render=lambda sid: [])                            # 200 vazio: limite de consultas
    r = se.buscar(ctx, ["4425870"], [D10], False, True, False)
    assert r["escalares"] == []
    assert any("Colider 2" in a and "da Colider 1" in a and "vazio" in a for a in r["avisos"])

    ctx, _, _ = ctx_de(render=lambda sid: irr_serie([[ms("2026-11-03T04:00:00+00:00"), 20000.0]]))
    r = se.buscar(ctx, ["4425864"], [D10], False, True, False)          # o dia não está na série do mês
    assert r["escalares"] == [] and any("2026-11-10" in a and "série do mês" in a for a in r["avisos"])

    ctx, _, _ = ctx_de(render=lambda sid: irr_serie([[ms("2026-11-10T04:00:00+00:00"), 20000.0]], nome="Power"))
    r = se.buscar(ctx, ["4425864"], [D10], False, True, False)          # sem sensor
    assert r["escalares"] == [] and any("Global Irradiance" in a for a in r["avisos"])

    sem_irma = [s for s in SITES if s["nome"] != "UFV Colider 1"]
    ctx, _, renders = ctx_de(render=lambda sid: irr_serie([]), sites=sem_irma)
    r = se.buscar(ctx, ["4425870"], [D10], False, True, False)
    assert renders == [] and any("Colider 1" in a and "não veio" in a for a in r["avisos"])


# ---------------------------------------------------------------- throttling: resposta vazia é aviso, nunca 0
@pytest.mark.parametrize("resp, trecho", [
    (Resp(200, {}), "200 vazia"),                                        # o 200 vazio da SolarEdge sob limite
    (Resp(200, sem_corpo=True), "sem corpo"),
    (Resp(500), "HTTP 500"),
])
def test_resposta_vazia_ou_falha_vira_aviso_e_nulo_nunca_zero(resp, trecho):
    ctx, _, _ = ctx_de(lambda url, c: resp)
    r = se.buscar(ctx, ["4400002"], [D10], True, False, False)
    assert [g["kwh"] for g in r["geracao"]] == [None, None, None]
    assert not any(g["kwh"] == 0 for g in r["geracao"])
    assert any("3 inversor(es) fora da resposta" in a and trecho in a and "não 0" in a for a in r["avisos"])
    # e o contrato marca o dia como fonte fora: a Coletas não sugere
    out = comum.montar_resposta(r, ctx.mapa, 0, None, None)
    assert out["dias_fora"] == [{"usina": "Xavantina 2", "data": "2026-11-10"}]


def test_inversor_ausente_da_resposta_parcial_e_nulo_com_aviso():
    ctx, _, _ = ctx_de(lambda url, c: energia({"7E0001": [["t", 500000.0]], "7E0003": [["t", 480000.0]]}))
    r = se.buscar(ctx, ["4400002"], [D10], True, False, False)
    assert {g["inversor"]: g["kwh"] for g in r["geracao"]} == {"Inversor 1.1": 500.0, "Inversor 1.2": None,
                                                               "Inversor 1.3": 480.0}
    assert any("1 inversor(es) fora da resposta" in a and "Inversor 1.2" in a for a in r["avisos"])


def test_sem_dispositivos_avisa_o_motivo_da_plataforma():
    ctx, sessao, _ = ctx_de(devs={}, falha={4400002: (0.0, "SolarEdge respondeu HTTP 429")})
    r = se.buscar(ctx, ["4400002"], [D10], True, False, False)
    assert r["geracao"] == [] and sessao.pedidos == []
    assert any("HTTP 429" in a for a in r["avisos"])


# ---------------------------------------------------------------- plantas, custo, ritmo, chuva
def test_plantas_custo_e_constantes():
    ctx, _, _ = ctx_de()
    assert se.plantas(ctx) == [
        {"id": "4425864", "usina": "Colider 1", "destino": "BD_Performance", "planta": "UFV Colider 1"},
        {"id": "4425870", "usina": "Colider 2", "destino": "BD_Performance", "planta": "UFV Colider 2"},
        {"id": "4400005", "usina": "Nobres", "destino": "BD_Performance", "planta": "UFV Nobres"},
        {"id": "4400002", "usina": "Xavantina 2", "destino": "BD_Performance", "planta": "UFV Xavantina 2"}]
    assert se.custo(["1"], [D10], True, True, True) == 0
    assert (se.FONTE, se.PAGA, se.TETO) == ("solaredge", False, None) and se.MAX_PLANTAS >= 1
    with pytest.raises(comum.Recusa) as e:
        se.plantas(ctx_de(sites=[])[0])                                  # lista vazia = SolarEdge fora, não "nenhuma"
    assert e.value.status == 502


def test_uma_recoleta_por_vez():
    ctx, _, _ = ctx_de()
    assert se._UMA_POR_VEZ.acquire(blocking=False)
    try:
        with pytest.raises(comum.Recusa) as e:
            se.buscar(ctx, ["4400002"], [D10], True, False, False)
        assert e.value.status == 429
    finally:
        se._UMA_POR_VEZ.release()
    se.buscar(ctx, ["4400002"], [D10], False, False, True)              # solto, passa de novo


def test_chuva_nao_se_aplica():
    ctx, sessao, renders = ctx_de()
    r = se.buscar(ctx, ["4400002"], [D10], False, False, True)
    assert r["geracao"] == [] and r["escalares"] == [] and sessao.pedidos == [] and renders == []
    assert any("chuva" in a.lower() for a in r["avisos"])


# ---------------------------------------------------------------- o contexto e a rota genérica, de ponta a ponta
def test_contexto_pega_os_clientes_da_plataforma(monkeypatch):
    mapa = comum.Mapa(EQUIP)
    monkeypatch.setattr(app, "_recoleta_mapa", lambda: mapa)
    ctx = se.contexto(app)
    assert ctx.mapa is mapa and ctx.sites is app.se_sites and ctx.devices is app.se_devices
    assert ctx.headers is app._se_headers and ctx.render_mes is app._se_render_month and ctx.http is app._http
    assert ctx.dev_falha is app._se_dev_falha and ctx.base == app.SE_BASE


def test_rota_generica_com_a_solaredge(monkeypatch):
    sessao = Sessao(lambda url, c: energia({"7E0001": [["t", 600000.0]], "7E0002": [["t", 550000.0]],
                                            "7E0003": [["t", 610000.0]]}))
    monkeypatch.setattr(app, "PASSWORD", "senha-pv-de-teste")
    monkeypatch.delenv("RECOLETA_CHAVE", raising=False)
    monkeypatch.setattr(comum, "hoje_br", lambda agora_utc=None: HOJE)
    monkeypatch.setattr(app, "_recoleta_mapa", lambda: comum.Mapa(EQUIP))
    monkeypatch.setattr(app, "se_sites", lambda: list(SITES))
    monkeypatch.setattr(app, "se_devices", lambda sid: list(DEVS.get(int(sid), [])))
    monkeypatch.setattr(app, "_se_render_month",
                        lambda sid, serials: irr_serie([[ms("2026-11-10T04:00:00+00:00"), 22000.0]]))
    monkeypatch.setattr(app, "_se_headers", lambda: {"cookie": "se_monitoring_auth=teste"})
    monkeypatch.setattr(app, "_http", lambda: sessao)
    assert recoleta_fontes.modulo("solaredge") is se
    cli, cab = app.app.test_client(), {"X-Recoleta-Chave": rc.chave_esperada("", "senha-pv-de-teste")}

    pl = cli.get("/api/recoleta/solaredge/plantas", headers=cab).get_json()
    assert pl["paga"] is False and pl["teto"] is None and pl["max_plantas"] == se.MAX_PLANTAS
    assert {p["usina"] for p in pl["plantas"]} == {"Colider 1", "Colider 2", "Nobres", "Xavantina 2"}

    r = cli.post("/api/recoleta/solaredge", headers=cab,
                 json={"ids": ["4400002"], "ini": "2026-11-10", "fim": "2026-11-10", "geracao": True, "etm": True})
    assert r.status_code == 200
    j = r.get_json()
    assert [(g["inversor"], g["kwh"]) for g in j["geracao"]] == [("Inversor 1.1", 600.0), ("Inversor 1.2", 550.0),
                                                                 ("Inversor 1.3", 610.0)]
    # Xavantina 2 não tem a estação e a Xavantina 1 não está na conta dublada: aviso, nenhum IPOA inventado
    assert j["escalares"] == [] and any("Xavantina 1" in a for a in j["avisos"])
    assert j["consultas"] == 0 and j["teto"] is None and j["cota_restante"] is None and j["dias_fora"] == []


def test_lista_rapida_pela_tabela_e_sites_guardados(monkeypatch):
    """18/11/2026 (Levi: "a leitura de usinas da fonte demora muito"): a 1ª lista levou 44 s indo à SolarEdge. Sem os
    sites guardados, a lista sai da tabela do tempo real; depois de uma leitura boa, os sites ficam 6 h guardados."""
    import types as _t
    from recoleta_fontes import comum as _c, solaredge as se
    monkeypatch.setattr(se, "_SITES", {"t": 0.0, "v": None})
    mapa = _c.Mapa([{"Usina Supervisório": "UFV Nobres", "Equipamento Supervisório": "Inverter 1", "Usina": "Nobres",
                     "Equipamento": "Inversor 1"}])
    chamou = []
    ctx = _t.SimpleNamespace(mapa=mapa, sites=lambda: chamou.append(1) or [{"id": 4425866, "nome": "UFV Nobres"}],
                             tabela=lambda: [{"plant_id": 4425866, "usina": "Nobres"}, {"plant_id": 9, "usina": "Outra"}])
    assert se.plantas(ctx) == [{"id": "4425866", "usina": "Nobres", "destino": "BD_Performance", "planta": None}]
    assert chamou == []                                                    # não foi à SolarEdge
    ctx2 = _t.SimpleNamespace(mapa=mapa, sites=ctx.sites, tabela=lambda: [])
    assert [p["usina"] for p in se.plantas(ctx2)] == ["Nobres"] and chamou == [1]
    ctx3 = _t.SimpleNamespace(mapa=mapa, sites=ctx.sites, tabela=lambda: [])
    se.plantas(ctx3)
    assert chamou == [1]                                                   # guardado: a 2ª lista não vai à fonte


@pytest.fixture(autouse=True)
def _sites_sem_cache(monkeypatch):
    """Os sites ficam guardados no módulo (6 h): cada teste começa sem nada guardado."""
    from recoleta_fontes import solaredge as _se
    monkeypatch.setattr(_se, "_SITES", {"t": 0.0, "v": None})
