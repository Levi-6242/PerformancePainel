# -*- coding: utf-8 -*-
"""Comunicação: o book de status da UFV no Tempo real (11/11/2026).

Levi, 11/11/2026: "Ao clicar em comunicação quero os checks que te pedi daquela vez strings, POA, GHI, POA RI,
PLUVIÔMETRO, TRACKERS. Tem que mostrar uma tabelinha mostrando o que tem e o que não tem!" e "criar um book de status
da UFV, se está funcionando, problema de string, inversor desligado, usina desligada, usina sem comunicação".

Prova aqui: a régua do status (a do macro, sem nada novo), o tem / não tem / sem leitura de cada coluna, a fonte sem
leitura virando "sem" (nunca "não tem" chutado) e que a rota só lê memória: não monta a Entrada nem chama fonte.
"""
import os
import time

import pytest

import app

AGORA = "2026-11-11 12:00:00"


def _item(**extra):
    """Uma linha do rollup (o que o `_macro_item` devolve) de uma usina da API PV, saudável, às 11:55."""
    r = {"fonte": "API PV", "cliente": "Thopen", "usina": "Usina Teste", "plant_id": 101, "status": "ok", "sev": 5,
         "causa": "Normal", "sem_visao": False, "inv_padrao": None, "strings_ativas": 80, "str_esp": 80,
         "diferenca": 0, "strings_faltando": 0, "inv_off": 0, "qtd_inversores": 4,
         "ultima_leitura": "2026-11-11 11:55:00"}
    r.update(extra)
    return r


# ── a régua do status ──────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("extra,chave", [
    ({"status": "sem_comm", "causa": "Sem comunicação"}, "sem_comm"),
    ({"status": "desligada", "causa": "Usina desligada · OS 123 de religamento aberta"}, "desligada"),
    ({"status": "sem_producao", "causa": "Sem produção · 4/4 inversores parados"}, "desligada"),
    ({"status": "critico", "inv_off": 2, "causa": "2 inversor(es) parado(s)"}, "inversor"),
    ({"status": "atencao", "strings_faltando": 3, "causa": "3 string(s) abaixo do esperado"}, "string"),
    ({"status": "critico", "strings_faltando": 12, "causa": "12 string(s) abaixo do esperado"}, "string"),
    # inversor fora do padrão D-1 (usina sem visão por string): o macro põe no degrau da falha de string
    ({"status": "critico", "inv_off": 1, "inv_padrao": {"status": "critico"}, "causa": "INV 3 a 70 % do padrão"}, "string"),
    ({"status": "ok"}, "funcionando"),
])
def test_regua_do_status(freeze_now, extra, chave):
    freeze_now(AGORA)
    st = app._comm_status_ufv(_item(**extra))
    assert st["chave"] == chave
    assert st["rotulo"] == dict(app.COMM_STATUS)[chave]


def test_os_cinco_rotulos_do_levi_e_o_sem_sol():
    assert [r for _k, r in app.COMM_STATUS] == ["Usina sem comunicação", "Usina desligada", "Inversor desligado",
                                               "Problema de string", "Funcionando", "Sem sol"]


def test_baixa_irradiancia_e_funcionando_com_a_causa(freeze_now):
    freeze_now(AGORA)
    st = app._comm_status_ufv(_item(causa="Baixa irradiância"))
    assert st["chave"] == "funcionando" and st["detalhe"] == "Baixa irradiância"


def test_de_noite_ok_e_sem_sol_nao_funcionando(freeze_now):
    freeze_now("2026-11-11 21:00:00")
    assert app._comm_status_ufv(_item())["chave"] == "sem_sol"


# ── Strings ────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_strings(freeze_now):
    freeze_now(AGORA)
    assert app._comm_strings(_item())["v"] == "tem"
    assert app._comm_strings(_item(sem_visao=True))["v"] == "nao"                        # combiner não exposta
    assert app._comm_strings(_item(status="sem_comm"))["v"] == "sem"
    velha = app._comm_strings(_item(ultima_leitura="2026-11-11 08:10:00"))
    assert velha["v"] == "sem" and "08:10" in velha["obs"]                               # sem leitura agora, nunca ✗
    assert app._comm_strings(_item(ultima_leitura=None))["v"] == "sem"


# ── POA, GHI, POA RI e pluviômetro ──────────────────────────────────────────────────────────────────────────────────
def _etm(**extra):
    r = {"usina": "Usina Teste", "plant_id": 101, "poa": 812.0, "ghi": None, "poari": 95.0, "poa_status": "ok",
         "ghi_status": "sem", "poari_status": "ok", "chuva": 0.0, "chuva_status": "ok", "sem_dados": False,
         "ultima_leitura": "2026-11-11 11:58:00"}
    r.update(extra)
    return r


def test_etm_tem_e_nao_tem(freeze_now):
    freeze_now(AGORA)
    ck = app._comm_etm("API PV", [_etm()], [])
    assert (ck["poa"]["v"], ck["ghi"]["v"], ck["poari"]["v"], ck["chuva"]["v"]) == ("tem", "nao", "tem", "tem")
    assert "sem este sensor" in ck["ghi"]["obs"]
    sem_chuva = app._comm_etm("API PV", [_etm(chuva=None, chuva_status="sem")], [])["chuva"]
    assert sem_chuva["v"] == "nao"


def test_etm_sem_leitura_vira_sem_nunca_nao(freeze_now):
    freeze_now(AGORA)
    # day_meteo vazio (a API PV responde igual para usina sem estação e para estação calada)
    vazio = app._comm_etm("API PV", [{"usina": "Usina Teste", "plant_id": 101, "sem_dados": True}], [])
    assert {c["v"] for c in vazio.values()} == {"sem"}
    # a tabela de ETM da fonte ainda não foi montada
    assert {c["v"] for c in app._comm_etm("API PV", None, None).values()} == {"sem"}
    # a fonte não lista estação para a usina
    assert {c["v"] for c in app._comm_etm("API PV", [], []).values()} == {"sem"}


def test_etm_velha_sem_leitura_agora_mas_o_que_nao_existe_continua_nao(freeze_now):
    freeze_now(AGORA)
    ck = app._comm_etm("API PV", [_etm(ultima_leitura="2026-11-11 07:30:00")], [])
    assert ck["poa"]["v"] == "sem" and "07:30" in ck["poa"]["obs"]
    assert ck["ghi"]["v"] == "nao"                       # a estação nunca mandou o GHI: isso continua sabido


def test_etm_zerado_com_sol_e_tem_com_alerta(freeze_now):
    freeze_now(AGORA)
    an = [{"usina": "Usina Teste", "plant_id": 101, "sem_dados": False, "ultima_leitura": "2026-11-11 11:58",
           "spark": {"poa": [0.0, 0.0], "ghi": []},
           "sensores": {"poa": {"pico": 0.0, "status": "zerado"}, "ghi": {"pico": None, "status": "sem_leitura"},
                        "poari": {"pico": None, "status": "sem_leitura"}}}]
    ck = app._comm_etm("API PV", [_etm(poa=0.0)], an)
    assert ck["poa"]["v"] == "tem" and ck["poa"]["alerta"] == "medindo zero com sol"


def test_etm_a_curva_do_dia_prova_o_sensor_que_a_ultima_leitura_nao_trouxe(freeze_now):
    freeze_now(AGORA)
    an = [{"usina": "Usina Teste", "plant_id": 101, "sem_dados": False, "ultima_leitura": "2026-11-11 11:58",
           "spark": {"poa": [500.0], "ghi": [None, 430.0]}, "sensores": {}}]
    assert app._comm_etm("API PV", [_etm()], an)["ghi"]["v"] == "tem"


def test_etm_o_que_a_plataforma_nao_le_e_sem(freeze_now):
    freeze_now(AGORA)
    th = app._comm_etm("Thopen", [_etm()], [])
    assert th["poa"]["v"] == "tem"
    assert th["poari"]["v"] == "sem" and "temperatura do módulo" in th["poari"]["obs"]   # a 3ª coluna do banco
    assert th["chuva"]["v"] == "sem"
    assert app._comm_etm("Athon", [_etm()], [])["chuva"]["v"] == "sem"                    # SunOp: não lido
    for f in ("RenoGrid", "GreenYellow", "Sal Energia", "Apolo"):
        assert {c["v"] for c in app._comm_etm(f, None, None).values()} == {"sem"}, f


def test_etm_do_scadagridco_pela_estacao_do_supervisorio(freeze_now):
    """11/11/2026 (b1e802a): a estação `weather` do scadaGridco entrou no tempo real. A GreenYellow com estação tem POA,
    GHI e POA RI pela análise do dia; o pluviômetro vazio ("-") é ✗; a usina que não está na análise montada não tem
    estação no supervisório (✗ com prova, a Apolo)."""
    freeze_now(AGORA)
    an = [{"usina": "Usina Teste", "plant_id": 101, "sem_dados": False, "ultima_leitura": "2026-11-11 11:58",
           "spark": {"poa": [800.0], "ghi": [600.0], "poari": [40.0]}, "pluviometro": False,
           "sensores": {"poa": {"status": "ok"}, "ghi": {"status": "ok"}, "poari": {"status": "ok"}}}]
    gy = app._comm_etm("GreenYellow", an, an)
    assert [gy[k]["v"] for k in ("poa", "ghi", "poari", "chuva")] == ["tem", "tem", "tem", "nao"]
    assert app._comm_etm("GreenYellow", [dict(an[0], pluviometro=True)], [dict(an[0], pluviometro=True)])["chuva"]["v"] == "tem"
    assert {c["v"] for c in app._comm_etm("Apolo", [], []).values()} == {"nao"}


def test_etm_montada_antes_do_pluviometro_e_sem(freeze_now):
    freeze_now(AGORA)
    r = _etm()
    r.pop("chuva"), r.pop("chuva_status")
    assert app._comm_etm("API PV", [r], [])["chuva"]["v"] == "sem"


def test_fetch_etm_plant_le_o_pluviometro_da_mesma_resposta(monkeypatch):
    """O `chuva` sai do mesmo day_meteo da tabela de ETM: nenhuma chamada a mais."""
    pedidos = []

    class _Resp:
        def __init__(self, recs):
            self._r = recs

        def json(self):
            return self._r

    class _Sessao:
        def __init__(self, recs):
            self.recs = recs

        def post(self, url, **kw):
            pedidos.append(url)
            return _Resp(self.recs)

    monkeypatch.setattr(app, "nome_usina", lambda pid, nome: nome)
    monkeypatch.setattr(app, "_http", lambda: _Sessao([{"tsleitura_new": "2026-11-11 11:58:00",
                                                         "conteudojson": '{"IrPOA": 800, "chuTotal": 2.4}'}]))
    r = app.fetch_etm_plant("tok", {"id": 1, "nome": "U"})
    assert r["chuva"] == 2.4 and r["chuva_status"] == "ok" and len(pedidos) == 1
    monkeypatch.setattr(app, "_http", lambda: _Sessao([{"tsleitura_new": "2026-11-11 11:58:00",
                                                         "conteudojson": '{"IrPOA": 800}'}]))
    r = app.fetch_etm_plant("tok", {"id": 1, "nome": "U"})
    assert r["chuva"] is None and r["chuva_status"] == "sem"


# ── Trackers ───────────────────────────────────────────────────────────────────────────────────────────────────────
def test_trackers():
    u = _item()
    idx = app._comm_indice([{"usina": "Usina Teste", "plant_id": 101, "total": 40, "sem_comunicacao": False,
                             "ultima_leitura": "2026-11-11 11:50:00"}])
    tem = app._comm_trackers("API PV", u, idx)
    assert tem["v"] == "tem" and "40 trackers" in tem["obs"]
    assert app._comm_trackers("API PV", _item(plant_id=999, usina="Outra"), idx)["v"] == "nao"   # a lista não tem
    assert app._comm_trackers("API PV", u, None)["v"] == "sem"                                   # aba não montada
    calado = app._comm_indice([{"usina": "Usina Teste", "plant_id": 101, "total": 40, "sem_comunicacao": True}])
    assert app._comm_trackers("API PV", u, calado)["v"] == "sem"
    assert app._comm_trackers("Sal Energia", u, None)["v"] == "nao"                               # Modbus, sem tracker
    assert app._comm_trackers("RenoGrid", u, None)["v"] == "sem"                                  # não lido
    # a leitura da usina falhou na última montagem (scadaGridco): não é "não tem"
    assert app._comm_trackers("GreenYellow", _item(plant_id="cedro"), app._comm_indice([]),
                              frozenset({"cedro"}))["v"] == "sem"


def test_trackers_casam_pela_fatia_e_pelo_nome():
    idx = app._comm_indice([{"usina": "Indaiatuba 3", "plant_id": 21482, "total": 30, "sem_comunicacao": False}])
    u = _item(usina="Indaiatuba", plant_id=21480, partes=[{"plant_id": 21480}, {"plant_id": 21482}])
    assert app._comm_trackers("API PV", u, idx)["v"] == "tem"


# ── a rota ─────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def rota(monkeypatch, freeze_now):
    freeze_now(AGORA)
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    monkeypatch.setattr(app, "_trk_geo_annotate", lambda rows: rows)
    rollup = [_item(),
              _item(usina="Usina Calada", plant_id=102, status="sem_comm", causa="Sem comunicação",
                    ultima_leitura="2026-11-11 06:40:00"),
              _item(usina="Usina Inversor", plant_id=103, status="critico", inv_off=1,
                    causa="1 inversor(es) parado(s)"),
              _item(fonte="Athon", cliente="Athon", usina="CPP100", plant_id="CPP100", status="atencao",
                    strings_faltando=2, causa="2 string(s) abaixo do esperado")]
    monkeypatch.setattr(app, "_portfolio_rollup", lambda: [dict(r) for r in rollup])
    monkeypatch.setattr(app, "_ENTRADA_TR_VIVO", {"ts": 0.0, "epoch": None, "data": None})
    grupos = [{"cliente": "Thopen", "fonte": "API PV", "fonte_id": "thopen-pv",
               "usinas": [{"usina": r["usina"], "plant_id": r["plant_id"], "status": "ok"} for r in rollup[:3]]},
              {"cliente": "Athon", "fonte": "Athon", "fonte_id": "athon",
               "usinas": [{"usina": "CPP100", "plant_id": "CPP100", "status": "ok"}]}]
    monkeypatch.setattr(app, "_ENTRADA_TR_CACHE", {"ts": time.time(), "building": False,
                                                   "data": {"grupos": grupos, "cache_ts": "11:40:00"}})
    monkeypatch.setattr(app, "_etm_cache", {"payload": {"rows": [_etm()]}, "ts": time.time()})
    monkeypatch.setattr(app, "_etm_analise_cache", {"payload": None, "ts": 0.0})
    monkeypatch.setattr(app, "_pv_trk_cache", {"payload": {"rows": [
        {"usina": "Usina Teste", "plant_id": 101, "total": 40, "sem_comunicacao": False}]}, "ts": time.time()})
    monkeypatch.setattr(app, "_sunop_etm_cache", {"payload": None, "ts": 0.0})
    monkeypatch.setattr(app, "_sunop_analise_cache", {"payload": None, "ts": 0.0})
    monkeypatch.setattr(app, "_sunop_trk_cache", {"payload": None, "ts": 0.0})

    def _proibido(*a, **k):
        raise AssertionError("a Comunicação só lê memória: não monta a Entrada nem chama fonte")
    for nome in ("_entrada_tr_disparar", "_entrada_tempo_real_build", "get_token", "get_plants", "_http",
                 "_sunop_req", "_sunop_last_values_multi", "ensure_sunop_meta", "_pg_conn"):
        monkeypatch.setattr(app, nome, _proibido)
    return app.app.test_client()


def test_rota_uma_linha_por_ufv_com_status_e_colunas(rota):
    d = rota.get("/api/entrada/tempo-real/comunicacao").get_json()
    assert d["aquecendo"] is False and [c[0] for c in d["colunas"]] == ["strings", "poa", "ghi", "poari", "chuva",
                                                                        "trackers"]
    pv = [g for g in d["grupos"] if g["fonte_id"] == "thopen-pv"][0]
    por = {u["usina"]: u for u in pv["usinas"]}
    # o status vem da linha VIVA do rollup, não do "ok" congelado no cache de 30 min
    assert por["Usina Calada"]["status"]["chave"] == "sem_comm"
    assert por["Usina Inversor"]["status"]["chave"] == "inversor"
    assert por["Usina Teste"]["status"]["chave"] == "funcionando"
    assert [u["usina"] for u in pv["usinas"]][0] == "Usina Calada"           # o mais grave primeiro
    ck = por["Usina Teste"]["checks"]
    assert {k: v["v"] for k, v in ck.items()} == {"strings": "tem", "poa": "tem", "ghi": "nao", "poari": "tem",
                                                  "chuva": "tem", "trackers": "tem"}
    assert por["Usina Calada"]["checks"]["strings"]["v"] == "sem"
    assert por["Usina Inversor"]["checks"]["trackers"]["v"] == "nao"          # a aba de trackers não tem a usina
    assert pv["contagem"]["sem_comm"] == 1 and d["contagem"]["string"] == 1   # a CPP100 da Athon
    # a Athon sem nenhuma tabela montada: tudo "sem leitura", nada de ✗ chutado (o Strings vem da linha do rollup)
    cpp = [g for g in d["grupos"] if g["fonte_id"] == "athon"][0]["usinas"][0]["checks"]
    assert {k: v["v"] for k, v in cpp.items() if k != "strings"} == {k: "sem" for k in ("poa", "ghi", "poari",
                                                                                       "chuva", "trackers")}


def test_rota_filtra_pelo_card(rota):
    d = rota.get("/api/entrada/tempo-real/comunicacao?fonte=athon").get_json()
    assert [g["fonte_id"] for g in d["grupos"]] == ["athon"]


def test_rota_aquecendo_sem_montar_nada(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    monkeypatch.setattr(app, "_ENTRADA_TR_CACHE", {"ts": 0.0, "data": None, "building": False})
    monkeypatch.setattr(app, "_entrada_tr_disparar", lambda *a, **k: (_ for _ in ()).throw(AssertionError("montou")))
    d = app.app.test_client().get("/api/entrada/tempo-real/comunicacao").get_json()
    assert d["aquecendo"] is True and d["grupos"] == []


def test_a_chave_do_nexus_alcanca_a_rota():
    """No Nexus a Entrada abre numa moldura com a chave de leitura: a rota nova tem de passar por ela."""
    import leitura_nexus as ln
    assert ln.permitido("GET", "/api/entrada/tempo-real/comunicacao", {})


def test_a_tela_abre_a_comunicacao_pelas_tres_portas():
    html = open(os.path.join(app._RAIZ, "docs", "redesign", "Entrada.html"), encoding="utf-8").read()
    assert "/api/entrada/tempo-real/comunicacao" in html
    assert "class='g-comm" in html and "data-comm='\" + idF" in html          # o rodapé do card do nível 2
    assert "atualiza comm' data-comm=" in html                                # o botão do cabeçalho
    assert "m comm-abre" in html                                              # o card "Sem comunicação" do nível 3
