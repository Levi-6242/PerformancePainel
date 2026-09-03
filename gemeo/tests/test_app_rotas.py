# gemeo/tests/test_app_rotas.py
"""Rotas, login e render das telas SEM banco: as consultas sao substituidas por dicts fixos (a forma que a
Tarefa 18 devolve), entao o que se testa aqui e o gate, os templates e o JSON. Roda em qualquer maquina."""
import datetime as dt
import types

import pytest

from gemeo.app import consultas, server

UTC = dt.timezone.utc
AGORA = dt.datetime(2026, 8, 31, 20, 0, tzinfo=UTC)
CFG = types.SimpleNamespace(senha_app="s3nh4-teste", db_dsn="", porta_app=5075, sunop_token="", teto_sunop_dia=600)
CASC = {"e_esperado": 41636.0, "e_medido": 38971.0, "delta": 2665.0, "inv_parado": 1658.0, "tracker": 104.0, "string": 0.0,
        "residuo": 903.0, "cobertura_gate": 0.95, "trackers_sem_inversor": 1}
USINA = {"id": 1, "codigo": "MRO100", "nome": "MRO100", "fonte": "sunop", "tz": "America/Belem", "kwp": 6942.0, "kw_ac": 5000.0,
         "cliente": "Athon", "n_equip": 182, "ultimo_ingest_ok": AGORA, "ultima_leitura": AGORA, "modelo_id": 1, "modelo_versao": "placa",
         "tolerancia": 0.08, "calibrado": False, "hoje": "2026-08-31", "slot": AGORA, "esperado_kw": 3100.0, "medido_kw": 2700.0,
         "delta": -0.129, "gate_agora": "ok", "gate_hoje": "ok", "cascata": CASC, "preco_mwh": None, "perda_kwh": 2665.0, "perda_brl": None,
         "causa": "inversor parado", "faixa": "grave", "idade_leitura_min": 5, "idade_esperado_min": 5, "frio": False, "motivo": None}
FROTA = {"agora": AGORA.isoformat(), "ciclo": {"em": "2026-08-31T19:50:00+00:00"}, "usinas": [USINA],
         "nao_modeladas": [{"id": 2, "codigo": "Santarem 1", "fonte": "pg", "motivo": "sem ingestão nas últimas 24 h"}],
         "totais": {"esperado_kw": 3100.0, "medido_kw": 2700.0, "delta": -0.129, "perda_kwh": 2665.0, "perda_brl": None, "confianca": 0.5,
                    "n_modeladas": 1, "n_usinas": 2},
         "regua": {"tolerancia": 0.08, "faixas": {"dentro": 0, "moderado": 0, "grave": 1, "sem_dado": 0}, "calibradas": 0,
                   "barras": [{"id": 1, "codigo": "MRO100", "faixa": "grave", "frio": False}]}}
CAB = {k: USINA[k] for k in ("id", "codigo", "nome", "fonte", "cliente", "tz", "kwp", "kw_ac", "hoje", "slot", "esperado_kw", "medido_kw",
                             "delta", "faixa", "gate_agora", "idade_leitura_min", "idade_esperado_min", "frio")}
CAB.update({"n_inversores": 25, "n_trackers": 120, "n_strings": 36, "modelo_versao": "placa", "calibrado": False, "tolerancia": 0.08})
US = {"agora": AGORA.isoformat(), "ciclo": {}, "cabecalho": CAB,
      "curva": [{"ts": "2026-08-31T09:00:00+00:00", "hora": "06:00", "esperado_kw": 10.0, "medido_kw": 8.0},
                {"ts": "2026-08-31T15:00:00+00:00", "hora": "12:00", "esperado_kw": 4000.0, "medido_kw": 3500.0}],
      "cascata": CASC, "preco_mwh": None, "perda_brl": None,
      "eventos": [{"id": 1, "tipo": "inversor_parado", "equipamento_id": 22, "equipamento": "INV_22", "ini": "2026-08-31T09:00:00+00:00",
                   "hora_ini": "06:00", "fim": None, "severidade": "media", "kwh": 1658.0, "detalhe": {"dia": "2026-08-31"}}],
      "inversores": [{"id": 22, "nome": "INV_22", "kwp": 277.68, "medido_kwh": 0.0, "esperado_kwh": 1658.0, "razao": 0.0, "inv_parado": 1658.0,
                      "tracker": 0.0, "string": 0.0, "residuo": 0.0, "status": "parado"},
                     {"id": 1, "nome": "INV_1", "kwp": 277.68, "medido_kwh": 1600.0, "esperado_kwh": 1650.0, "razao": 0.97, "inv_parado": 0.0,
                      "tracker": 4.0, "string": 0.0, "residuo": 46.0, "status": "ok"}],
      "trackers": [{"id": 4, "nome": "TRK_4", "pai_id": 1, "kwh": 65.0}, {"id": 64, "nome": "TRK_64", "pai_id": None, "kwh": 3.0}], "strings": [],
      "sensor": {"razao_poa_ghi": 1.31, "cobertura_gate": 0.95, "gate_hoje": "ok", "trackers_sem_inversor": 1}}


@pytest.fixture
def cli(monkeypatch):
    chamadas: dict = {}

    def frota_fake(conn, agora):
        chamadas["agora"] = agora
        return FROTA

    monkeypatch.setattr(consultas, "frota", frota_fake)
    monkeypatch.setattr(consultas, "usina", lambda conn, uid, agora: US if uid == 1 else None)
    monkeypatch.setattr(consultas, "saude", lambda conn, cfg, agora: {"ok": True, "banco": True, "problemas": []})
    app = server.criar_app(CFG, conectar=lambda: object())
    app.config["TESTING"] = True
    c = app.test_client()
    c.chamadas = chamadas
    return c


def _entra(c):
    r = c.post("/gemeo/login", data={"senha": "s3nh4-teste"})
    assert r.status_code == 302
    return c


def test_sem_login_redireciona_e_api_devolve_401(cli):
    assert cli.get("/gemeo/").status_code == 302 and cli.get("/gemeo/api/frota").status_code == 401
    assert cli.get("/gemeo/healthz").status_code == 200        # saude e publica: e o que o monitor externo bate
    assert cli.post("/gemeo/login", data={"senha": "errada"}).status_code == 401


def test_frota_renderiza_regua_cards_e_nao_modeladas(cli):
    r = _entra(cli).get("/gemeo/?agora=2026-08-31T20:00:00Z")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "A frota contra a física" in html and "MRO100" in html and "inversor parado" in html
    assert "Santarem 1 — sem ingestão nas" in html and "−12,9%" in html and "não calibrado" in html
    assert cli.chamadas["agora"] == AGORA


def test_usina_renderiza_curva_cascata_e_eventos(cli):
    r = _entra(cli).get("/gemeo/usina/1")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Cascata de perdas" in html and "curva-dados" in html and "INV_22" in html and "Inversor parado" in html
    assert "trackers sem inversor" in html and "(sem inversor)" in html
    assert cli.get("/gemeo/usina/99").status_code == 404


def test_header_da_plataforma_dispensa_sessao_e_api_e_json(cli):
    r = cli.get("/gemeo/api/frota", headers={"X-Gemeo-Senha": "s3nh4-teste"})
    assert r.status_code == 200 and r.get_json()["usinas"][0]["codigo"] == "MRO100"
    assert cli.get("/gemeo/api/usina/1", headers={"X-Gemeo-Senha": "s3nh4-teste"}).get_json()["cabecalho"]["n_trackers"] == 120
    assert cli.get("/gemeo/api/frota", headers={"X-Gemeo-Senha": "errada"}).status_code == 401


def test_healthz_503_quando_ha_problema(cli, monkeypatch):
    monkeypatch.setattr(consultas, "saude", lambda conn, cfg, agora: {"ok": False, "banco": True, "problemas": ["modelar nunca rodou"]})
    r = cli.get("/gemeo/healthz")
    assert r.status_code == 503 and r.get_json()["problemas"] == ["modelar nunca rodou"]


def test_fora_do_prefixo_vai_para_a_frota(cli):
    assert _entra(cli).get("/").status_code == 302


def test_dia_escolhido_congela_o_agora_e_desliga_o_auto_refresh(cli):
    r = _entra(cli).get("/gemeo/?dia=2026-09-01")
    html = r.get_data(as_text=True)
    assert cli.chamadas["agora"] == dt.datetime(2026, 9, 2, 2, 59, 59, tzinfo=UTC)          # fim do dia em UTC-3
    assert 'http-equiv="refresh"' not in html and "Diagnóstico ›" in html and 'value="2026-09-01"' in html
    html_vivo = cli.get("/gemeo/").get_data(as_text=True)
    assert 'http-equiv="refresh" content="300"' in html_vivo and 'class="lk"' in html_vivo
    html_usina = cli.get("/gemeo/usina/1?dia=2026-09-01").get_data(as_text=True)
    assert "‹ Frota" in html_usina and "/gemeo/api/usina/1?dia=2026-09-01" in html_usina
