# -*- coding: utf-8 -*-
"""Análise das usinas (25/11/2026): a tela e as rotas da entrega 1 (a visão inicial), com o Gerencial e a régua do COS
dublados. O estado (as ocultas) vai para um arquivo de teste."""
import json

import pytest

import app

GER = {"cache_ts": "16:47:32", "mes": "11/2026",
       "usinas": [{"usina": "Usina A", "cliente": "Cliente X", "atingimento": 96.6, "pr": 69.8, "pr_meta": 83.3, "prod": 349.4,
                   "prod_pr": 349.4, "ipoa": 153.7, "p50": 361.7, "pot_mwp": 3.256, "dias_cob": 20},
                  {"usina": "Usina B", "cliente": "Cliente Y", "atingimento": 101.0, "pr": 80.0, "pr_meta": 80.0, "prod": 50,
                   "prod_pr": 50, "ipoa": 150, "p50": 49.5, "pot_mwp": 0.4, "dias_cob": 20}]}
DISP = {"periodo": ["2026-11-01", "2026-11-02"], "usinas": [{"usina": "Usina A"}],
        "diario": {"Usina A": {"2026-11-01": {"disp": 89.7, "h_eq": 1.029}}}, "oss": [{"folio": "1", "usinas": ["Usina A"]}]}


@pytest.fixture
def cli(tmp_path, monkeypatch):
    estado = tmp_path / "estado.json"
    estado.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(app, "STATE_PATH", str(estado))
    monkeypatch.setattr(app, "_AU_LOG", str(tmp_path / "analise.log"))
    pedidos = []
    monkeypatch.setattr(app, "_gerencial_payload", lambda **k: pedidos.append(k) or GER)
    monkeypatch.setattr(app, "_falhas_disp_mes", lambda mes: DISP if mes == "2026-11" else None)
    monkeypatch.setattr(app, "INFO_GERAL", {"usina a": {"usina": "Usina A", "mobilizacao": "2025-10-20"}})
    app.app.config["TESTING"] = True
    with app.app.test_client() as c:
        c.pedidos = pedidos
        yield c


def test_a_tela_abre_debaixo_do_painel_sem_o_raw_do_jinja_e_sem_lista_do_navegador(cli):
    r = cli.get("/painel/analise-das-usinas")
    h = r.get_data(as_text=True)
    assert r.status_code == 200 and "{% raw %}" not in h and "Análise das usinas" in h
    # todo seletor no estilo do Nexus (Levi, 25/11/2026): nada de <select> nem <datalist> do navegador
    assert "<select" not in h and "<datalist" not in h and "/api/analise/usinas" in h


def test_a_visao_do_mes_junta_o_gerencial_e_a_regua_do_cos(cli):
    j = cli.get("/api/analise/usinas?mes=2026-11").get_json()
    a, b = j["usinas"]
    assert a["u"] == "Usina A" and a["disp"] == pytest.approx((89.7 + 100) / 2, abs=.05) and a["nos"] == 1 and a["mob"] == "2025-10-20"
    assert b["disp"] is None and b["nos"] is None and b["sinal"] == "ok"
    assert j["mes_pedido"] == "2026-11"
    # o mês corrente vai ao Gerencial sem ano e mês (o snapshot de agora); o passado, com eles
    cli.get("/api/analise/usinas?mes=2025-03")
    assert cli.pedidos[-1] == {"ano": 2025, "mes": 3}
    cli.get("/api/analise/usinas")
    assert cli.pedidos[-1] == {"ano": None, "mes": None}


def test_mes_fora_do_formato_e_recusado_e_o_gerencial_fora_e_503(cli, monkeypatch):
    assert cli.get("/api/analise/usinas?mes=11-2026").status_code == 400
    monkeypatch.setattr(app, "_gerencial_payload", lambda **k: {"erro": "PG fora", "usinas": []})
    r = cli.get("/api/analise/usinas?mes=2026-11")
    assert r.status_code == 503 and "PG fora" in r.get_json()["erro"]


def test_ocultar_vale_para_a_equipe_com_quem_e_quando_e_mostrar_tira(cli):
    r = cli.post("/api/analise/ocultas", json={"usina": "Usina B", "oculta": True, "nick": "Ana"}).get_json()
    assert r["ok"] and r["ocultas"]["Usina B"]["quem"] == "Ana"
    j = cli.get("/api/analise/usinas?mes=2026-11").get_json()
    assert j["usinas"][1]["oculta"]["quem"] == "Ana" and j["usinas"][0]["oculta"] is None
    r = cli.post("/api/analise/ocultas", json={"usina": "usina b", "oculta": False}).get_json()   # o nome sem caixa casa
    assert r["ocultas"] == {}
    assert cli.post("/api/analise/ocultas", json={"oculta": True}).status_code == 400


def test_a_data_de_mobilizacao_da_info_geral_vira_iso():
    assert app._data_iso("2025-10-20 00:00:00") == "2025-10-20"
    assert app._data_iso("20/10/2025") == "2025-10-20"
    assert app._data_iso(None) is None and app._data_iso("sem data") is None


# ── entregas 2 e 3 (26/11/2026): o diagnóstico da usina, com as fontes dubladas ──────────────────────────────────────
DIARIO = {"meta": 0.833, "pot": 3.256, "meta_ger": 18.0, "meta_poa": 7.4,
          "pontos": [{"dia": 1, "realizado": 0.70, "geracao": 18.0, "poa": 7.9}, {"dia": 2, "realizado": 0.50, "geracao": 12.0, "poa": 7.4}]}
DISP2 = {"periodo": ["2026-11-01", "2026-11-02"], "usinas": [{"usina": "Usina A"}],
         "diario": {"Usina A": {"2026-11-02": {"disp": 90.0, "h_eq": 1.0, "os": [{"folio": 7, "h": 1.0, "trechos": "07:30-17:30"}]}}},
         "oss": [{"folio": 7, "tipos": ["desligamento de inversor"], "origem": "equipamento", "aberta": True, "ini": "2026-11-02T07:30:00",
                  "escopo": [{"usina": "Usina A", "rotulo": "Inversor 1.2"}], "protecoes": []}]}
VIEWS = {"/api/g/diario": DIARIO, "/api/g/mensal": {"pontos": []}, "/api/g/tickets-trackers": {"trackers": []},
         "/api/g/inversores": {"alvo": 0.833, "inversores": [{"inversor": "Inversor 1.1", "pr": 0.72, "alvo": 0.833, "ger_mwh": 9},
                                                             {"inversor": "Inversor 1.2", "pr": 0.40, "alvo": 0.833, "ger_mwh": 5}]}}


@pytest.fixture
def diag(cli, monkeypatch):
    monkeypatch.setattr(app, "_au_view", lambda fn, rota, **q: VIEWS[rota])
    monkeypatch.setattr(app, "_falhas_disp_mes", lambda mes: DISP2)
    monkeypatch.setattr(app, "_frac_disp_dados", lambda: {"meses": {}})
    monkeypatch.setattr(app, "_au_inv_dias", lambda u, a, m: {"2026-11-01": {"Inversor 1.1": 9000, "Inversor 1.2": 9000, "Inversor 1.3": 9000},
                                                            "2026-11-02": {"Inversor 1.1": 6000, "Inversor 1.2": 0.0, "Inversor 1.3": 6200}})
    monkeypatch.setattr(app, "_au_curva_fonte", lambda u: None)          # só fonte paga: sem curva, nada na rede
    monkeypatch.setattr(app, "_au_gemeo_id", lambda u, completo=False: None)
    monkeypatch.setattr(app, "_au_falhas", lambda mes: {"strings": {"episodios": []}, "trackers": {"rows": []}, "strings_os": []})
    monkeypatch.setattr(app, "_au_zeladoria", lambda: [])
    monkeypatch.setattr(app, "_au_uid", lambda u: None)
    app._AU_DIAG.clear()
    return cli


def test_o_diagnostico_junta_o_gerencial_o_bd_a_regua_do_cos_e_a_perda_de_cada_ocorrencia(diag):
    j = diag.get("/api/analise/usina?usina=usina a&mes=2026-11").get_json()
    assert j["usina"] == "Usina A" and j["ger"]["at"] == 96.6 and j["ger"]["meta"] == 83.3 and j["mob"] == "2025-10-20"
    assert [d["d"] for d in j["dias"]] == [1, 2] and j["dias"][0]["disp"] == 100.0 and j["dias"][1]["disp"] == 90.0
    oc, = j["ocorr"]
    assert oc["os"] == "7" and oc["escopo"] == "Inversor 1.2" and oc["perda"] == 6100 and oc["metodo"] == "inversor"
    # o limite é 85% de 83,3% = 70,8%. Dia 1: PR 70%, sem ocorrência nenhuma = sem explicação. Dia 2: PR 50% + 6,1 MWh ÷
    # (7,4 × 3,256) = 75,3%: o inversor parado explica
    assert j["sem_expl"] == [1] and j["dias"][0]["sem_expl"] and not j["dias"][1]["sem_expl"]
    assert j["ofensores"][0]["t"] == "Inversor parado" and j["curva"] is None
    assert [o["t"] for o in j["observacoes"]] == ["Dias sem explicação"]
    assert [i["n"] for i in j["invs"]] == ["Inversor 1.1", "Inversor 1.2", "Inversor 1.3"] and j["invs"][1]["os"] == ["7"]


def test_o_diagnostico_recusa_o_pedido_torto_e_diz_a_usina_que_nao_esta_no_gerencial(diag):
    assert diag.get("/api/analise/usina?mes=2026-11").status_code == 400
    assert diag.get("/api/analise/usina?usina=Usina A&mes=11-2026").status_code == 400
    r = diag.get("/api/analise/usina?usina=Nenhuma&mes=2026-11")
    assert r.status_code == 404 and "Nenhuma" in r.get_json()["erro"]
    assert diag.get("/api/analise/curvas?usina=Usina A&dia=2026-11-02").get_json()["sem_curva"] is True
    assert diag.get("/api/analise/gemeo?usina=Usina A&dia=2026-11-02").get_json()["sem_gemeo"] is True


def test_a_observacao_do_inversor_grava_para_a_equipe_e_texto_vazio_apaga(diag):
    r = diag.post("/api/analise/observacao", json={"usina": "Usina A", "inversor": "Inversor 1.2", "texto": "Aguardando peça"})
    assert r.get_json()["obs"]["Inversor 1.2"]["txt"] == "Aguardando peça"
    j = diag.get("/api/analise/usina?usina=Usina A&mes=2026-11").get_json()
    assert j["invs"][1]["obs"]["txt"] == "Aguardando peça"
    diag.post("/api/analise/observacao", json={"usina": "usina a", "inversor": "Inversor 1.2", "texto": ""})
    assert json.load(open(app.STATE_PATH, encoding="utf-8"))["analise_obs"]["Usina A"] == {}
    assert diag.post("/api/analise/observacao", json={"usina": "Usina A"}).status_code == 400
