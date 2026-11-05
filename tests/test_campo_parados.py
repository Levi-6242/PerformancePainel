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

