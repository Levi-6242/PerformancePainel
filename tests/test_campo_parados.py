# -*- coding: utf-8 -*-
"""Os trackers parados de todas as usinas para a ronda do App de Campo (/api/campo/parados, 05/11/2026).

O pedido (Levi, pela sessão do App de Campo): "A ideia é o técnico ver todos os trackers parados das UFVs que estão
para eles". Uma chamada traz todas as usinas; a lista sai da montagem da Entrada do tempo real (a mesma régua e o mesmo
número do card), sem chamada a mais às fontes. Regra de dado: fonte que não respondeu = "falhou", nunca "0 parados".
"""
import time

import pytest

import app

CHAVE = "chave-de-teste-campo"


@pytest.fixture
def entrada(monkeypatch):
    monkeypatch.setattr(app, "_macro_cache", {"ts": 0.0, "data": {"usinas": [
        {"usina": "Ipixuna 2", "plant_id": 33, "status": "ok", "strings_faltando": 0,
         "cliente": "Thopen", "fonte": "Thopen", "ultima_leitura": "2026-11-05T09:45"},
        {"usina": "Altair 3", "plant_id": 34, "status": "ok", "strings_faltando": 0,
         "cliente": "Thopen", "fonte": "Thopen", "ultima_leitura": "2026-11-05T09:45"},
        {"usina": "CPP100", "plant_id": "cpp", "status": "ok", "strings_faltando": 0,
         "cliente": "Athon", "fonte": "Athon", "ultima_leitura": "2026-11-05T09:50"},
    ]}, "warming": False})
    monkeypatch.setattr(app, "_etm_prob_cache", {"ts": 0.0, "data": {"itens": [], "mes": "11/2026"}})
    monkeypatch.setattr(app, "_trk_geo_annotate", lambda rows: rows)
    monkeypatch.setattr(app, "_ENTRADA_TRK_PRAZO_S", 1)
    monkeypatch.setattr(app._sg, "configurado", lambda: False)
    monkeypatch.setattr(app, "_entrada_trk_ultimo_gravar", lambda grupos: None)
    monkeypatch.setattr(app, "_entrada_trk_anterior", lambda ant, c, f: None)
    monkeypatch.setattr(app, "_CAMPO_PARADOS", {"data": None, "por_fonte": {}})
    # a aba Equipamentos (o nome do Fracttal) nunca é lida de verdade aqui; quem precisa dela usa _aba()
    import pandas as pd
    monkeypatch.setattr(app, "_CAMPO_FRACTTAL", {"ts": 0.0, "mapa": {}})
    monkeypatch.setattr(app, "_equipamentos_df", lambda: pd.DataFrame(columns=["Usina", "Usina Supervisório", "Usina Fractall"]))
    monkeypatch.setattr(app, "_pv_parados_rows", lambda *a, **k: [])
    monkeypatch.setattr(app, "_owen_parados_rows", lambda *a, **k: [])
    monkeypatch.setattr(app, "_sunop_parados_rows", lambda inst=None, *a, **k: [])
    monkeypatch.setattr(app, "_pg_parados_rows", lambda *a, **k: [
        {"plant_id": 33, "usina": "Ipixuna 2", "tracker": "TRK-12", "atual": 3.0, "alvo": 41.0, "disparidade": 38.0,
         "sem_comunicacao": False, "parado_desde": "2026-11-04T10:00:00", "inversor": "1.3", "ticket_status": "Aberto"},
        {"plant_id": 33, "usina": "Ipixuna 2", "tracker": "TRK-2", "atual": None, "alvo": 41.0,
         "sem_comunicacao": True, "parado_desde": "2026-11-05T07:10:00", "inversor": ""}])
    return monkeypatch


def _usina(d, nome):
    return next(u for u in d["usinas"] if u["usina"] == nome)


def test_a_lista_de_cada_usina_bate_com_o_card_da_entrada(entrada):
    saida = app._entrada_tempo_real_build()
    d = app._CAMPO_PARADOS["data"]
    ipx = _usina(d, "Ipixuna 2")
    assert ipx["falhou"] is False and ipx["n_parados"] == 2 and ipx["fonte"] == "Thopen"
    assert [t["tracker"] for t in ipx["parados"]] == [2, 12]                # pelo nº, como no /api/campo/ronda
    assert ipx["parados"][0]["status"] == "sem_comunicacao" and ipx["parados"][1]["status"] == "parado"
    assert ipx["parados"][1]["inversor"] == "1.3" and ipx["parados"][1]["com_os"] is True
    card = next(g for g in saida["grupos"] if g["fonte"] == "Thopen")
    assert sum(u["trk_parados"] for u in card["usinas"]) == ipx["n_parados"]
    # a usina lida sem parado é zero DE VERDADE (a fonte respondeu)
    alt = _usina(d, "Altair 3")
    assert alt["falhou"] is False and alt["n_parados"] == 0 and alt["parados"] == []


def test_fonte_que_nao_respondeu_sai_como_falhou_nunca_zero(entrada):
    def _explode(*a, **k):
        raise RuntimeError("Athon fora")
    entrada.setattr(app, "_sunop_parados_rows", _explode)
    app._entrada_tempo_real_build()
    d = app._CAMPO_PARADOS["data"]
    cpp = _usina(d, "CPP100")
    assert cpp["falhou"] is True and "parados" not in cpp and "n_parados" not in cpp
    assert next(f for f in d["fontes"] if f["fonte"] == "Athon")["lida"] is False


def test_fonte_atrasada_usa_a_lista_anterior_com_a_hora_dela(entrada):
    app._entrada_tempo_real_build()                                          # 1ª montagem: tudo lido
    hora_boa = _usina(app._CAMPO_PARADOS["data"], "Ipixuna 2")["atualizado"]

    def _explode(*a, **k):
        raise RuntimeError("banco lento")
    entrada.setattr(app, "_pg_parados_rows", _explode)
    app._entrada_tempo_real_build()
    ipx = _usina(app._CAMPO_PARADOS["data"], "Ipixuna 2")
    assert ipx["falhou"] is False and ipx["atrasado"] is True and ipx["atualizado"] == hora_boa
    assert ipx["n_parados"] == 2
    # passou do teto (3 h): aí é "falhou", não a lista velha
    app._CAMPO_PARADOS["por_fonte"]["Thopen"]["ts"] = time.time() - app._ENTRADA_TRK_ULTIMO_MAX_S - 10
    app._entrada_tempo_real_build()
    assert _usina(app._CAMPO_PARADOS["data"], "Ipixuna 2")["falhou"] is True


def test_a_rota_pede_a_chave_e_nao_le_aquecendo_como_zero(entrada, monkeypatch):
    monkeypatch.setattr(app, "CAMPO_API_KEY", CHAVE)
    monkeypatch.setattr(app, "_entrada_tr_disparar", lambda forcar=False: False)
    c = app.app.test_client()
    assert c.get("/api/campo/parados").status_code == 401
    assert c.get("/api/campo/parados", headers={"x-api-key": "outra"}).status_code == 401
    r = c.get("/api/campo/parados", headers={"x-api-key": CHAVE})
    assert r.status_code == 503 and r.get_json()["aquecendo"] is True
    app._entrada_tempo_real_build()
    monkeypatch.setattr(app, "_ENTRADA_TR_CACHE", {"ts": time.time(), "data": {"grupos": []}, "building": False})
    j = c.get("/api/campo/parados", headers={"x-api-key": CHAVE}).get_json()
    assert _usina(j, "Ipixuna 2")["n_parados"] == 2 and 0 < j["proxima_em_s"] <= app._ENTRADA_TR_TTL
    assert {f["fonte"] for f in j["fontes"]} >= {"Thopen", "Athon", "API PV", "2C", "Axis"}



# ── o nome da usina no Fracttal (05/11/2026): o App guarda a usina por ele, e o nome do tempo real só casava em 29 de 95 ──
def _aba(monkeypatch, linhas):
    import pandas as pd
    monkeypatch.setattr(app, "_CAMPO_FRACTTAL", {"ts": 0.0, "mapa": {}})
    monkeypatch.setattr(app, "_equipamentos_df", lambda: pd.DataFrame(
        linhas, columns=["Usina", "Usina Supervisório", "Usina Fractall"]))


def test_cada_usina_e_cada_tracker_levam_o_nome_do_fracttal(entrada):
    _aba(entrada, [("Ipixuna 2", "Ipixuna 2 (33)", "Thopen - Ipixuna 2 - PA"),
                   ("Altair 3", "Altair 3", "Thopen - Altair 3 - SP"),
                   ("CPP100", "CPP100", "Athon - Capim Grosso 1 - BA")])
    app._entrada_tempo_real_build()
    d = app._CAMPO_PARADOS["data"]
    ipx = _usina(d, "Ipixuna 2")
    assert ipx["usina_fracttal"] == "Thopen - Ipixuna 2 - PA"
    assert {t["usina_fracttal"] for t in ipx["parados"]} == {"Thopen - Ipixuna 2 - PA"}
    assert _usina(d, "Altair 3")["usina_fracttal"] == "Thopen - Altair 3 - SP"     # sem parado: pelo nome da usina


def test_usina_macro_que_cobre_varias_do_fracttal_vai_tracker_a_tracker(entrada):
    # "Altair" no tempo real = Altair 1 a 5 no Fracttal: a linha da usina fica vazia e cada tracker leva a dele
    _aba(entrada, [("Altair 1", "Altair 1", "Thopen - Altair 1 - SP"), ("Altair 2", "Altair 2", "Thopen - Altair 2 - SP"),
                   ("Altair", "Altair", "Thopen - Altair 1 - SP"), ("Altair", "Altair", "Thopen - Altair 2 - SP")])
    entrada.setattr(app, "_macro_usina_nome", lambda n: "Altair" if str(n).startswith("Altair") else n)
    entrada.setattr(app, "_pg_parados_rows", lambda *a, **k: [
        {"plant_id": 1, "usina": "Altair 1", "tracker": "TRK-1", "sem_comunicacao": False},
        {"plant_id": 2, "usina": "Altair 2", "tracker": "TRK-9", "sem_comunicacao": False}])
    app._entrada_tempo_real_build()
    alt = next(u for u in app._CAMPO_PARADOS["data"]["usinas"] if u["usina"].startswith("Altair") and u.get("n_parados"))
    assert alt["usina_fracttal"] == ""
    assert {t["tracker"]: t["usina_fracttal"] for t in alt["parados"]} == {1: "Thopen - Altair 1 - SP",
                                                                           9: "Thopen - Altair 2 - SP"}
    assert app._campo_fracttal("Altair") == ""                     # o nome que cobre duas não resolve: nunca adivinha


def test_sem_o_nome_exato_nao_adivinha_pelo_trecho(entrada):
    _aba(entrada, [("Ipixuna 2 Norte", "Ipixuna 2 Norte", "Thopen - Ipixuna 2 Norte - PA")])
    app._entrada_tempo_real_build()
    ipx = _usina(app._CAMPO_PARADOS["data"], "Ipixuna 2")
    assert ipx["usina_fracttal"] == "" and all(t["usina_fracttal"] == "" for t in ipx["parados"])


# ── 05/11/2026, o retorno do App de Campo com o dado do dia ──────────────────────────────────────────────────────────
def test_assis_cada_trk1_leva_o_skid_dele(entrada):
    """A Assis vem como "Assis" nos parados da API PV, mas são quatro usinas na fonte, cada uma com o seu TRK1, e sem o
    inversor: o App juntava os TRK1 num item só. A parte (o nome na fonte) separa, e casa o nome do Fracttal."""
    _aba(entrada, [("Assis", "Assis Chateaubriand  Skid 1 (79)", "Thopen - Assis Chateaubriand - PR"),
                   ("Assis", "Assis Chateaubriand Skid 2 (80)", "Thopen - Assis Chateaubriand - PR")])
    entrada.setattr(app, "_macro_cache", {"ts": 0.0, "data": {"usinas": [
        {"usina": "Assis", "plant_id": 18747433, "status": "ok", "cliente": "Thopen", "fonte": "API PV"}]}, "warming": False})
    entrada.setattr(app, "_pv_trk_cache", {"ts": 0.0, "payload": {"rows": [
        {"plant_id": 18747433, "usina": "Assis Chateaubriand  Skid 1 (79)"},
        {"plant_id": 18747548, "usina": "Assis Chateaubriand Skid 2 (80)"}]}})
    entrada.setattr(app, "_pg_parados_rows", lambda *a, **k: [])
    entrada.setattr(app, "_pv_parados_rows", lambda *a, **k: [
        {"plant_id": 18747433, "usina": "Assis", "tracker": "TRK1", "inversor": "", "sem_comunicacao": False},
        {"plant_id": 18747548, "usina": "Assis", "tracker": "TRK1", "inversor": "", "sem_comunicacao": False}])
    app._entrada_tempo_real_build()
    assis = _usina(app._CAMPO_PARADOS["data"], "Assis")
    assert sorted(t["parte"] for t in assis["parados"]) == ["Assis Chateaubriand  Skid 1 (79)",
                                                            "Assis Chateaubriand Skid 2 (80)"]
    assert {t["usina_fracttal"] for t in assis["parados"]} == {"Thopen - Assis Chateaubriand - PR"}


def test_sem_comunicacao_o_angulo_e_null(entrada):
    app._entrada_tempo_real_build()
    sc = next(t for t in _usina(app._CAMPO_PARADOS["data"], "Ipixuna 2")["parados"] if t["status"] == "sem_comunicacao")
    assert sc["atual"] is None and sc["alvo"] is None and sc["disparidade"] is None
    parado = next(t for t in _usina(app._CAMPO_PARADOS["data"], "Ipixuna 2")["parados"] if t["status"] == "parado")
    assert parado["atual"] == 3.0 and parado["alvo"] == 41.0 and parado["parte"] == ""


# ── 21/11/2026: o ativo do Fracttal de cada tracker, para o App conferir o chamado aberto ────────────────────────────
# Levi, pelo chat do App: "eu queria que a gente linkasse tudo que está com chamado aberto com os dados que vêm da API
# daquelas usinas". O quadro de chamados do Nexus é chaveado pelo código do ativo; sem ele, o App pedia a plaqueta ao
# técnico e o tracker já em chamado aparecia como pendência. A regra é a do Criar OS de tracker (sem chute); o par "a
# confirmar" do de-para vai marcado (Levi, aqui: "a confirmar vai marcado").
def _depara(entrada, trackers, usinas=("Ipixuna 2",), so_fonte="pg"):
    vistos = []

    def _dp(fonte, nome):
        vistos.append((fonte, nome))
        if fonte != so_fonte:
            return None
        return {"usinas": list(usinas), "trackers": [dict(x, usina=usinas[0]) for x in trackers]}
    entrada.setattr(app, "_trk_depara_usina", _dp)
    entrada.setattr(app, "_falhas_trk_nome_cadastro", lambda pid: None)
    return vistos


def _trk(nome):
    return next(t for t in _usina(app._CAMPO_PARADOS["data"], "Ipixuna 2")["parados"] if t["nome"] == nome)


def test_cada_tracker_leva_o_ativo_do_fracttal_e_o_a_confirmar_vai_marcado(entrada):
    vistos = _depara(entrada, [{"num": 12, "tracker": "TRK-12", "code": "IPX200-ETKR1.12", "situacao": "casado"},
                               {"num": 2, "tracker": "TRK-2", "code": "IPX200-ETKR1.2", "situacao": "a_confirmar"}])
    app._entrada_tempo_real_build()
    t12, t2 = _trk("TRK-12"), _trk("TRK-2")
    assert (t12["cod_fracttal"], t12["cod_a_confirmar"], t12["cod_motivo"]) == ("IPX200-ETKR1.12", False, None)
    assert (t2["cod_fracttal"], t2["cod_a_confirmar"], t2["cod_motivo"]) == ("IPX200-ETKR1.2", True, None)
    assert ("pg", "Ipixuna 2") in vistos                      # a Thopen do tempo real é a fonte "pg" do de-para


def test_sem_de_para_nao_chuta_e_diz_o_motivo(entrada):
    _depara(entrada, [], so_fonte="nenhuma")
    app._entrada_tempo_real_build()
    t = _trk("TRK-12")
    assert t["cod_fracttal"] is None and t["cod_a_confirmar"] is False
    assert "não está no de-para de trackers" in t["cod_motivo"]


def test_numero_repetido_com_ativos_diferentes_nao_escolhe(entrada):
    _depara(entrada, [{"num": 12, "tracker": "TRK 12 A", "code": "IPX200-ETKR1.12", "situacao": "casado"},
                      {"num": 12, "tracker": "TRK 12 B", "code": "IPX200-ETKR2.12", "situacao": "casado"}])
    app._entrada_tempo_real_build()
    t = _trk("TRK-12")
    assert t["cod_fracttal"] is None and "se repete" in t["cod_motivo"]


def test_de_para_quebrado_nao_derruba_a_lista(entrada):
    def _quebra(fonte, nome):
        raise ValueError("planilha ilegível")
    entrada.setattr(app, "_trk_depara_usina", _quebra)
    app._entrada_tempo_real_build()
    t = _trk("TRK-12")
    assert t["cod_fracttal"] is None and "não respondeu" in t["cod_motivo"]
    assert _usina(app._CAMPO_PARADOS["data"], "Ipixuna 2")["n_parados"] == 2


def test_o_criar_os_de_tracker_segue_com_o_mesmo_codigo(entrada):
    _depara(entrada, [{"num": 12, "tracker": "TRK-12", "code": "IPX200-ETKR1.12", "situacao": "a_confirmar"}])
    assert app._falhas_os_code_tracker("pg", 33, "Ipixuna 2", "TRK-12") == ("IPX200-ETKR1.12", None)
