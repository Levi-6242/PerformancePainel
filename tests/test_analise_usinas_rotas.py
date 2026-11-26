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


_CURVA_FONTE = app._au_curva_fonte          # a de verdade (a fixture `diag` a troca por "sem curva")


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


def test_a_athon_no_scada_da_grid_le_as_curvas_de_la_e_a_da_sunop_diz_a_cota(diag, monkeypatch):
    # Levi, 26/11/2026: "fui nas da Athon e está dizendo que é uma fonte paga, sendo que é a própria [SCADA] da Grid"
    monkeypatch.setattr(app, "_au_curva_fonte", _CURVA_FONTE)
    monkeypatch.setattr(app, "INFO_GERAL", {"cpp100": {"usina": "CPP100", "cliente": "Athon"}, "jcd100": {"usina": "JCD100", "cliente": "Athon"},
                                            "tucano 2": {"usina": "Tucano 2", "cliente": "SEMP"}})
    monkeypatch.setattr(app, "_athon_sg_cfg", lambda u, inst="gridco": {"id": "cpp_100", "usina": "CPP100"} if u == "CPP100" else None)
    pedidos = []
    monkeypatch.setattr(app, "_pa_dia", lambda fam, fonte, pid, dia, agora=None: pedidos.append((fam, fonte, pid, dia.isoformat()))
                        or {"inversores": [{"nome": "Inversor 1.1", "pontos": [[600, 50.0], [610, 52.0]]}]})
    monkeypatch.setattr(app._sg, "usina_cfg", lambda fonte, pid: {"id": pid, "usina": "CPP100"})
    monkeypatch.setattr(app, "_sg_equips", lambda fonte, cfg: ["1"])
    monkeypatch.setattr(app, "_sg_curva_inversor", lambda fonte, cfg, eq, dia: {
        "nome": "Inversor 1.1", "curva": {"7": {"x": ["10:00", "10:10"], "y": [8.1, 8.3]}}, "strings": [{"nome": "7", "ativa": True}]})
    j = diag.get("/api/analise/curvas?usina=CPP100&dia=2026-11-06").get_json()
    assert pedidos == [("scadagridco", "athonscada", "cpp_100", "2026-11-06")] and j["fonte"] == "athonscada" and not j["sem_curva"]
    assert j["pot"]["Inversor 1.1"] == [[600, 50.0], [610, 52.0]] and j["poa"] == []
    assert j["str"]["Inversor 1.1"]["s"] == {"ST 07": [8.1, 8.3]} and j["str"]["Inversor 1.1"]["info"] == {"ST 07": [None, True]}
    assert j["motivo"] is None
    monkeypatch.setattr(app, "_pa_dia", lambda fam, fonte, pid, dia, agora=None: {"inversores": []})   # antes de a Athon entrar no SCADA
    v = diag.get("/api/analise/curvas?usina=CPP100&dia=2026-11-06").get_json()
    assert v["sem_curva"] and "a Athon entrou no SCADA" in v["motivo"]
    m = diag.get("/api/analise/curvas?usina=JCD100&dia=2026-11-06").get_json()
    assert m["sem_curva"] and "SCADA da Grid" in m["motivo"] and "SunOp" in m["motivo"]
    assert "API PV" in diag.get("/api/analise/curvas?usina=Tucano 2&dia=2026-11-06").get_json()["motivo"]


def test_a_poa_zerada_e_falta_de_dado_e_o_dia_vazio_do_fim_sai(diag, monkeypatch):
    d = dict(DIARIO, pontos=DIARIO["pontos"] + [{"dia": 3, "realizado": None, "geracao": 25.0, "poa": 0},
                                                 {"dia": 4, "realizado": 11.7, "geracao": 15.0, "poa": 0.38},
                                                 {"dia": 5, "realizado": None, "geracao": 0, "poa": 0}])
    monkeypatch.setitem(VIEWS, "/api/g/diario", d)
    j = diag.get("/api/analise/usina?usina=Usina A&mes=2026-11").get_json()
    assert [(x["d"], x["poa"], x["pr"]) for x in j["dias"][2:]] == [(3, None, None), (4, 0.38, None)]   # 5 saiu; PR de 1.170% não é dado


# ── velocidade e nome do BD (26/11/2026, Levi: "está demorando muito para calcular os expurgos") ───────────────────────
def test_o_nome_do_gerencial_vira_o_da_aba_do_bd_thopen_so_quando_difere(monkeypatch):
    import dashboard_thopen as dth
    monkeypatch.setattr(dth, "_CARTEIRA_DE", {"Piracicaba 1": "Thopen", "Marajoara 1": "Thopen", "Santarém 2": "Thopen"})
    # o Gerencial escreve 'Piracicaba I' (o PG); a aba do BD_Thopen é 'Piracicaba 1' e por aquele nome vinha 0 dia
    assert app._au_nome_bd("Thopen", "Piracicaba I") == "Piracicaba 1"
    assert app._au_nome_bd("Thopen", "Marajoara I") == "Marajoara 1"
    assert app._au_nome_bd("Thopen", "Santarém 2") == "Santarém 2"
    assert app._au_nome_bd("Athon", "Piracicaba I") == "Piracicaba I"     # fora do BD_Thopen, o nome fica


def _cascata_dublada(monkeypatch, chamadas):
    class _R:
        def get_json(self):
            return {"pot": 6.94, "meta": 0.698, "meta_ger": 32.19, "meta_poa": 6.6,
                    "pontos": [{"dia": 1, "geracao": 30.0, "poa": 6.0}, {"dia": 2, "geracao": 28.0, "poa": 5.5}]}
    monkeypatch.setattr(app, "api_g_diario", lambda: _R())
    monkeypatch.setattr(app, "_fonte_da_usina", lambda u: "sunop")
    monkeypatch.setattr(app, "_paradas_book_get", lambda f, force=False: {"rows": []})
    monkeypatch.setattr(app, "_trk_frota_total", lambda f, u, sel=(): 0)
    monkeypatch.setattr(app, "_frac_usina_ent", lambda u: None)
    monkeypatch.setattr(app, "_frac_depara_falha", lambda u: None)
    monkeypatch.setattr(app, "_strings_problema_rows", lambda f, force=False: chamadas.append(f) or [])


def test_a_cascata_da_analise_nao_monta_a_lista_de_strings_abertas(monkeypatch):
    # a lista pode baixar a curva de string do dia da SunOp (cota) ou da API PV (paga) dentro da página: a MRO100 levou
    # 95,7 s fria; a Análise não a usa. O Gerencial (/api/cascata) segue com ela
    chamadas = []
    _cascata_dublada(monkeypatch, chamadas)
    c = app._cascata_usina("Athon", "MRO100", 2026, 11, com_abertos=False)
    assert c["ok"] and chamadas == [] and set(c["tempos"]) == {"serie", "trackers", "fracttal", "abertos"}
    assert c["geracao"] == 58.0 and c["possivel"] == pytest.approx(11.5 * 6.94 * 0.698, abs=.1)
    app._cascata_usina("Athon", "MRO100", 2026, 11)
    assert chamadas == ["sunop"]
    pedidos = []
    monkeypatch.setattr(app, "_cascata_usina", lambda cli, u, a, m, com_abertos=True: pedidos.append(com_abertos) or {"ok": True})
    app._au_cascata("Athon", "MRO100", 2026, 11)
    assert pedidos == [False]


def test_a_energia_pega_o_cliente_do_gerencial_e_o_nome_da_aba_do_bd(cli, monkeypatch):
    import dashboard_thopen as dth
    monkeypatch.setattr(dth, "_CARTEIRA_DE", {"Piracicaba 1": "Thopen"})
    ger = {"usinas": [{"usina": "Piracicaba I", "cliente": "Thopen"}]}
    monkeypatch.setattr(app, "_gerencial_payload", lambda **k: ger)
    pedidos = []
    monkeypatch.setattr(app, "_cascata_usina", lambda c, u, a, m, com_abertos=True: pedidos.append((c, u, m, com_abertos)) or {"ok": True, "geracao": 1})
    app._AU_ENERGIA.clear()
    j = cli.get("/api/analise/usina/energia?usina=Piracicaba I&mes=2026-11").get_json()
    # antes o cliente vinha do Info Geral pelo nome ('Piracicaba I' não casa) e o nome ia cru: "sem série diária"
    assert pedidos == [("Thopen", "Piracicaba 1", 11, False)] and j["usina"] == "Piracicaba I" and j["cascata"]["ok"]


def test_o_diagnostico_diz_o_tempo_de_cada_etapa(diag):
    j = diag.get("/api/analise/usina?usina=usina a&mes=2026-11").get_json()
    assert set(j["tempos"]) == {"gerencial", "bd", "cos", "inversores_dia", "fonte_curva", "perdas", "disp_inversor", "falhas",
                                "ronda", "gemeo"} and j["nome_bd"] is None
