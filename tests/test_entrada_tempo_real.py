# -*- coding: utf-8 -*-
"""Tela de tempo real (_entrada_tempo_real_build) — a regra que custou caro em 05/09/2026.

O banco (PG) passou de 15 minutos numa consulta. Como as fontes de trackers eram lidas em sequencia e sem prazo, o
build ficou pendurado e /api/entrada/tempo-real respondeu `aquecendo` a noite inteira: a tela mostrava tres esqueletos
e nada mais. Consulta lenta NAO levanta excecao, entao o try/except existente nao ajudava.

Prova aqui: fonte lenta estoura o prazo, o build TERMINA assim mesmo, as outras fontes entram, e o grupo da lenta fica
com trk_fonte_ok=False — que e como a tela escreve "fonte nao respondeu".
"""
import time

import pytest

import app


@pytest.fixture
def entrada(monkeypatch):
    """Zera as dependencias do build: sem macro, sem ETM, e cada fonte de trackers controlada pelo teste."""
    monkeypatch.setattr(app, "_macro_cache", {"ts": 0.0, "data": {"usinas": [
        {"usina": "Ipixuna 2", "plant_id": 33, "status": "critico", "strings_faltando": 14,
         "cliente": "Thopen", "fonte": "Thopen", "ultima_leitura": "2026-09-05T12:45"},
        {"usina": "CPP100", "plant_id": "cpp", "status": "ok", "strings_faltando": 0,
         "cliente": "Athon", "fonte": "Athon", "ultima_leitura": "2026-09-05T12:50"},
    ]}, "warming": False})
    monkeypatch.setattr(app, "_etm_prob_cache", {"ts": 0.0, "data": {"itens": [], "mes": "09/2026"}})
    monkeypatch.setattr(app, "_trk_geo_annotate", lambda rows: rows)
    monkeypatch.setattr(app, "_ENTRADA_TRK_PRAZO_S", 1)          # o teste nao espera 30 s
    chamadas = {}

    def _fonte(nome, rows=(), demora=0.0):
        def _fn(*a, **k):
            chamadas[nome] = chamadas.get(nome, 0) + 1
            if demora:
                time.sleep(demora)
            return list(rows)
        return _fn
    return {"fonte": _fonte, "chamadas": chamadas}


def _grupo(saida, cliente, fonte):
    return [g for g in saida["grupos"] if g["cliente"] == cliente and g["fonte"] == fonte][0]


def test_fonte_lenta_nao_segura_a_tela(entrada, monkeypatch):
    f = entrada["fonte"]
    monkeypatch.setattr(app, "_pg_parados_rows", f("pg", demora=6))        # o banco pendurado de 05/09
    monkeypatch.setattr(app, "_sunop_parados_rows", lambda inst=None: [
        {"usina": "CPP100", "cliente": "Athon", "ticket_status": "Aberto"}] if inst == "gridco" else [])
    monkeypatch.setattr(app, "_pv_parados_rows", f("pv"))
    monkeypatch.setattr(app, "_owen_parados_rows", f("owen"))
    t0 = time.time()
    d = app._entrada_tempo_real_build()
    gasto = time.time() - t0
    assert gasto < 5, f"o build esperou a fonte lenta ({gasto:.1f}s) em vez de publicar sem ela"
    assert len(d["grupos"]) == 8                                   # os 8 pares existem sempre
    lento = _grupo(d, "Thopen", "Thopen")
    assert lento["trk_fonte_ok"] is False and lento["trk_parados"] == 0   # a tela escreve "fonte nao respondeu"
    assert d["fontes_pendentes"] == ["Thopen"]                            # e o cache sabe que deve tentar de novo em 5 min
    assert lento["n_usinas"] == 1 and lento["strings_faltando"] == 14     # o resto do card continua valendo
    athon = _grupo(d, "Athon", "Athon")
    assert athon["trk_fonte_ok"] is True and athon["trk_parados"] == 1 and athon["trk_com_os"] == 1


def test_fonte_que_levanta_excecao_tambem_nao_derruba(entrada, monkeypatch):
    f = entrada["fonte"]

    def _explode(*a, **k):
        raise RuntimeError("sem token da Plataforma")
    monkeypatch.setattr(app, "_pv_parados_rows", _explode)
    monkeypatch.setattr(app, "_pg_parados_rows", f("pg"))
    monkeypatch.setattr(app, "_sunop_parados_rows", lambda inst=None: [])
    monkeypatch.setattr(app, "_owen_parados_rows", f("owen"))
    d = app._entrada_tempo_real_build()
    assert _grupo(d, "Thopen", "API PV")["trk_fonte_ok"] is False       # levantou → "fonte nao respondeu"
    assert _grupo(d, "Thopen", "Thopen")["trk_fonte_ok"] is True
    assert _grupo(d, "Renogrid", "RenoGrid")["trk_fonte_ok"] is True    # respondeu vazio: zero parados ≠ sem leitura


def test_todas_as_fontes_sao_consultadas_em_paralelo(entrada, monkeypatch):
    """Cada fonte demora 0,6 s; em sequencia seriam ~3 s. Em paralelo, bem menos — e nenhuma fica de fora."""
    f = entrada["fonte"]
    monkeypatch.setattr(app, "_ENTRADA_TRK_PRAZO_S", 5)
    monkeypatch.setattr(app, "_pg_parados_rows", f("pg", demora=0.6))
    monkeypatch.setattr(app, "_pv_parados_rows", f("pv", demora=0.6))
    monkeypatch.setattr(app, "_owen_parados_rows", f("owen", demora=0.6))
    monkeypatch.setattr(app, "_sunop_parados_rows", lambda inst=None: time.sleep(0.6) or [])
    t0 = time.time()
    d = app._entrada_tempo_real_build()
    gasto = time.time() - t0
    assert gasto < 2.0, f"as fontes foram lidas em sequencia ({gasto:.1f}s)"
    for cliente, fonte in (("Thopen", "API PV"), ("Thopen", "Thopen"), ("Athon", "Athon"),
                           ("Axis", "Axis"), ("Renogrid", "RenoGrid")):
        assert _grupo(d, cliente, fonte)["trk_fonte_ok"] is True, f"{cliente}/{fonte} ficou de fora"


# ── 06/09/2026: cadencia de 30 min + botao Atualizar; strings "nao reconhecidas / total" ─────────────────────────
def _espera_build(cache, seg=5.0):
    t0 = time.time()
    while time.time() - t0 < seg:
        if cache["data"] is not None and not cache["building"]:
            return
        time.sleep(0.05)
    raise AssertionError("a construcao em fundo nao terminou")


def test_disparar_respeita_o_ttl_e_o_botao(monkeypatch):
    cache = {"ts": 0.0, "data": None, "building": False}
    monkeypatch.setattr(app, "_ENTRADA_TR_CACHE", cache)
    monkeypatch.setattr(app, "_entrada_tempo_real_build", lambda: {"grupos": [], "cache_ts": "10:00:00"})
    assert app._ENTRADA_TR_TTL == 1800                                  # 30 min (Levi, 06/09) — era 120
    assert app._entrada_tr_disparar() is True                           # sem dado: constroi
    _espera_build(cache)
    assert cache["data"]["cache_ts"] == "10:00:00"
    assert app._entrada_tr_disparar() is False                          # fresco: a tela nao dispara nada
    assert app._entrada_tr_disparar(forcar=True) is False               # botao logo depois: menos de 1 min = nao repete
    cache["ts"] = time.time() - app._ENTRADA_TR_MIN_FORCA_S - 1
    assert app._entrada_tr_disparar(forcar=True) is True                # botao passado o intervalo: constroi
    _espera_build(cache)
    cache["ts"] = time.time() - app._ENTRADA_TR_TTL - 1
    assert app._entrada_tr_disparar() is True                           # vencido: constroi sozinho
    _espera_build(cache)
    cache["building"] = True
    assert app._entrada_tr_disparar(forcar=True) is False               # ja construindo: nunca duas ao mesmo tempo
    cache["building"] = False
    cache["data"]["fontes_pendentes"] = ["Thopen"]                      # o banco estourou o prazo na ultima construcao
    cache["ts"] = time.time() - app._ENTRADA_TR_TTL_PENDENTE - 1
    assert app._entrada_tr_payload()["ttl_s"] == app._ENTRADA_TR_TTL_PENDENTE
    assert app._entrada_tr_disparar() is True                           # ...entao tenta de novo em 5 min, nao em 30
    _espera_build(cache)
    assert cache["data"].get("fontes_pendentes") is None and app._entrada_tr_payload()["ttl_s"] == 1800   # completo: volta aos 30


def test_rotas_do_tempo_real_e_do_botao(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    cache = {"ts": time.time(), "data": {"grupos": [], "cache_ts": "10:00:00"}, "building": False}
    monkeypatch.setattr(app, "_ENTRADA_TR_CACHE", cache)
    monkeypatch.setattr(app, "_entrada_tempo_real_build", lambda: {"grupos": [], "cache_ts": "10:05:00"})
    c = app.app.test_client()
    d = c.get("/api/entrada/tempo-real").get_json()
    assert d["ttl_s"] == 1800 and d["cache_epoch"] == int(cache["ts"]) and d["stale"] is False and d["renovando"] is False
    r = c.post("/api/entrada/tempo-real/atualizar").get_json()
    assert r["ok"] is True and r["disparou"] is False and r["cache_ts"] == "10:00:00"   # fresco demais para repetir
    cache["ts"] = time.time() - 61
    r = c.post("/api/entrada/tempo-real/atualizar").get_json()
    assert r["disparou"] is True
    _espera_build(cache)
    assert c.get("/api/entrada/tempo-real").get_json()["cache_ts"] == "10:05:00"


def test_strings_nao_reconhecidas_descontam_o_acompanhamento(entrada, monkeypatch):
    """MRO100 falta 34 e o analista acompanha 17 → 17 nao reconhecidas; SMP100 falta 8 sem acompanhamento → 8;
    CPP100 falta 35 com 35 acompanhadas → 0. O total do card segue sendo esperadas − ativas (77)."""
    f = entrada["fonte"]
    monkeypatch.setattr(app, "_macro_cache", {"ts": 0.0, "data": {"usinas": [
        {"usina": "MRO100", "plant_id": "MRO100", "status": "critico", "strings_faltando": 34, "cliente": "Athon", "fonte": "Athon"},
        {"usina": "SMP100", "plant_id": "SMP100", "status": "critico", "strings_faltando": 8, "cliente": "Athon", "fonte": "Athon"},
        {"usina": "CPP100", "plant_id": "CPP100", "status": "critico", "strings_faltando": 35, "cliente": "Athon", "fonte": "Athon"},
        {"usina": "Altair", "plant_id": 22860, "status": "critico", "strings_faltando": 5, "cliente": "Thopen", "fonte": "API PV"},
    ]}, "warming": False})
    monkeypatch.setattr(app, "_load_state", lambda: {"tracking": {"so:MRO100": 17, "so:CPP100": 35, "pv:22860": 9}})
    for nome in ("_pg_parados_rows", "_pv_parados_rows", "_owen_parados_rows"):
        monkeypatch.setattr(app, nome, f(nome))
    monkeypatch.setattr(app, "_sunop_parados_rows", lambda inst=None: [])
    d = app._entrada_tempo_real_build()
    athon = _grupo(d, "Athon", "Athon")
    assert athon["strings_faltando"] == 77 and athon["strings_nao_rec"] == 25
    por = {u["usina"]: u for u in athon["usinas"]}
    assert (por["MRO100"]["strings_nao_rec"], por["MRO100"]["strings_acomp"]) == (17, 17)
    assert (por["SMP100"]["strings_nao_rec"], por["CPP100"]["strings_nao_rec"]) == (8, 0)
    pv = _grupo(d, "Thopen", "API PV")
    assert pv["strings_faltando"] == 5 and pv["strings_nao_rec"] == 0          # acompanha mais do que falta: nada pendente
