# -*- coding: utf-8 -*-
"""O e-mail da 2C saiu do código (Levi, 03/10/2026: "remova do código pegar os dados por e-mail pelo Owen do Azure,
agora está tudo via API do PV Operation").

Quem lia o acervo do e-mail — a aba de falhas, Perdas → strings, a correlação, a curva por código, a frota de trackers —
passa a ler a API PV pelo `_2c_strings_dia_api`, no MESMO formato ({código: {"U.N": {"k": [(datetime, A)]}}}), para o
que já foi gravado com essas chaves continuar casando. De-para: inversor "U.N" do e-mail = "Inversor U.N" do cadastro da
planta (Ipixuna: UG 1 = Santa Cecilia 1, 2 = 2, 3 = 3) e string k = Ipvk."""
import pathlib
from datetime import datetime as _dt

import pytest

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
SC1, SC2, SC3 = 18771915, 18771929, 18771930


@pytest.fixture
def api_falsa(monkeypatch):
    """API PV de mentira: hoje pelo day_inverter, dia passado pelo histórico. Conta as idas."""
    estado = {"hoje": {}, "hist": {}, "motivo": {}, "idas": []}
    monkeypatch.setattr(app, "_2c_str_dia_cache", {})
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "t")
    monkeypatch.setattr(app, "_pv_curvas_strings", lambda pid, nome, tok, entradas=None: (
        estado["idas"].append(("hoje", pid)) or estado["hoje"].get(pid, {})))
    monkeypatch.setattr(app, "_spv_day_records_hist", lambda pid, tok, data: (
        estado["idas"].append(("hist", pid)) or (([{"x": 1}] if pid in estado["hist"] else []),
                                                 estado["motivo"].get(pid))))
    monkeypatch.setattr(app, "_pv_curvas_strings_de", lambda recs, pid, nome, tok, entradas=None: estado["hist"].get(pid, {}))
    return estado


def test_dia_passado_vem_da_api_com_as_chaves_do_email(api_falsa, freeze_now):
    freeze_now("2026-10-03 12:00:00")
    api_falsa["hist"] = {18771898: {"Inversor 1.10": {"Ipv3": [("10:00", 5.0), ("09:55", 4.0)]}},
                         SC2: {"Inversor 2.4": {"Ipv1": [("10:00", 7.5)], "Ipv12": [("10:00", 0.0)]}},
                         SC3: {"Inversor 3.6": {"Ipv28": [("11:30", 6.0)]}}}
    d = app._2c_strings_dia_api("2026-10-02")
    assert d["ARA"]["1.10"]["3"] == [(_dt(2026, 10, 2, 9, 55), 4.0), (_dt(2026, 10, 2, 10, 0), 5.0)]
    assert d["IPX"]["2.4"] == {"1": [(_dt(2026, 10, 2, 10, 0), 7.5)], "12": [(_dt(2026, 10, 2, 10, 0), 0.0)]}
    assert d["IPX"]["3.6"]["28"] == [(_dt(2026, 10, 2, 11, 30), 6.0)]
    assert "STL" not in d and "TUP" not in d                 # a API respondeu sem dado: só ficam de fora


def test_hoje_vem_do_day_inverter(api_falsa, freeze_now):
    freeze_now("2026-10-03 12:00:00")
    api_falsa["hoje"] = {18750925: {"Inversor 2.10": {"Ipv27": [("11:55", 8.1)]}}}
    d = app._2c_strings_dia_api("2026-10-03")
    assert d == {"TUP": {"2.10": {"27": [(_dt(2026, 10, 3, 11, 55), 8.1)]}}}
    assert all(tipo == "hoje" for tipo, _p in api_falsa["idas"])


def test_api_fora_levanta_e_nao_guarda_o_dia(api_falsa, freeze_now):
    """A aba de falhas guarda dia fechado: vazio por falha de rede viraria um dia sem falha nenhuma na 2C."""
    freeze_now("2026-10-03 12:00:00")
    api_falsa["motivo"] = {18771901: "erro_rede"}
    with pytest.raises(RuntimeError, match="18771901 erro_rede"):
        app._2c_strings_dia_api("2026-10-02")
    assert "2026-10-02" not in app._2c_str_dia_cache


def test_dia_fechado_nao_volta_a_api_e_o_cache_tem_teto(api_falsa, freeze_now):
    freeze_now("2026-10-03 12:00:00")
    app._2c_strings_dia_api("2026-10-02")
    n = len(api_falsa["idas"])
    app._2c_strings_dia_api("2026-10-02")
    assert len(api_falsa["idas"]) == n, "dia fechado buscou de novo"
    for d in ("2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01"):
        app._2c_strings_dia_api(d)
    assert len(app._2c_str_dia_cache) <= app._2C_STR_DIA_MAX, "o dia inteiro de 1.600 strings não pode acumular"


def test_ultima_leitura_de_cada_string_para_a_tabela_de_problemas(api_falsa, freeze_now):
    freeze_now("2026-10-03 12:00:00")
    api_falsa["hoje"] = {18771898: {"Inversor 1.1": {"Ipv2": [("11:50", 3.0), ("11:55", 0.0)]}}}
    assert app._2c_strings_ultimos() == {"ARA": {"1.1": {"2": (_dt(2026, 10, 3, 11, 55), 0.0)}}}


def test_os_consumidores_leem_a_api(api_falsa, freeze_now, monkeypatch):
    freeze_now("2026-10-03 12:00:00")
    api_falsa["hist"] = {18771898: {"Inversor 1.1": {"Ipv1": [(f"{h:02d}:{m:02d}", 8.0) for h in range(8, 17)
                                                             for m in (0, 30)]}}}
    assert app._2c_hist_api("2026-10-02")["strings"]["ARA"]["1.1"]["1"][0][1] == 8.0     # a aba de falhas
    monkeypatch.setattr(app, "_trk_geo_annotate", lambda rows: rows)
    assert app._owen_strings_eventos("2026-10-02") == []                                # uma string viva o dia todo
    rows, unidade = app._strings_curva_longo("owen", "ARA", "2026-10-02")
    assert rows[0] == ("Inversor 1.1", "ST 01", "08:00", 8.0) and unidade == "corrente_A"


def test_o_codigo_de_email_nao_existe_mais(cli):
    for nome in ("_hist_build", "_owen_refresh", "_owen_loop", "_owen_strings_build", "_owen_etm_build",
                 "OWEN_ROOT", "_owen_accum", "_2C_TRK_API_DESDE"):
        assert not hasattr(app, nome), f"{nome} ainda está no app.py"
    regras = {r.rule for r in app.app.url_map.iter_rules()}
    assert not any(r.startswith("/api/2c/") for r in regras) and "/historico2c" not in regras
    assert "/api/owen/etm/chart" not in regras
    assert not (RAIZ / "plataforma" / "templates" / "historico2c.html").exists()
    import inspect
    assert "_owen_loop" not in inspect.getsource(app._iniciar_loops_de_fundo)
    falhas = (RAIZ / "plataforma" / "falhas_job.py").read_text(encoding="utf-8")
    assert "app._hist_build" not in falhas and "app._2c_hist_api" in falhas
    mon = (RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")
    assert "/api/2c/" not in mon and "/historico2c" not in mon and "/api/owen/etm/chart" not in mon


def test_frota_de_trackers_da_2c_vem_da_aba_publicada(monkeypatch):
    monkeypatch.setattr(app, "_2c_trk_cache", {"ts": 0.0, "payload": {"rows": [
        {"usina": "Ipixuna do Pará", "total": 122}, {"usina": "União 1 e 2", "total": 76}]}})
    assert app._trk_frota_linhas("owen") == [{"usina": "Ipixuna do Pará", "total": 122}, {"usina": "União 1 e 2", "total": 76}]


def test_trackers_de_dia_antigo_tambem_pela_api(monkeypatch):
    pedidos = []
    monkeypatch.setattr(app, "_2c_trk_build_api", lambda date_iso, force=False: pedidos.append(date_iso) or {"ARA": {}})
    assert app._owen_trackers_build(date="2026-09-15") == {"ARA": {}} and pedidos == ["2026-09-15"]


def test_drill_por_codigo_do_email_responde_que_nao_existe(cli):
    r = cli.get("/api/owen/strings/plant/ARA")
    assert r.status_code == 404 and r.get_json()["inversores"] == []


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    return app.app.test_client()
