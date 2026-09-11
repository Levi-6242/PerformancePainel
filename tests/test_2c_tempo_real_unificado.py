# -*- coding: utf-8 -*-
"""Tempo Real da 2C, tudo junto (Levi, 11/09/2026: "Eu quero no tempo real, tudo junto!"): a fonte `2c` do Monitoramento
(rotas /api/owen/...) passa a misturar as usinas que a API PV enxerga (Araputanga, Sete Lagoas, Tupi — linha ao vivo da
conta oem@, `sub_fonte="api"`) com as que só o e-mail tem (Ipixuna do Pará, `sub_fonte="email"`). O drill de uma usina
da API delega ao motor da API PV e a ETM dessas usinas vem da estação da API. A aba separada "2C · API PV" sai do seletor."""
import pathlib

import pytest

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    return app.app.test_client()


def _email(u, pid):
    return {"usina": u, "plant_id": pid, "qtd_inversores": 10, "strings_ativas": 236, "str_esp": 236, "diferenca": 0,
            "temp_media": None, "ultima_leitura": "2026-09-11 11:59", "sem_dados": False, "falha_comunicacao": True}


def test_data_mistura_api_e_email_por_usina(cli, monkeypatch):
    monkeypatch.setattr(app, "_owen_strings_rows", lambda force=False: [_email("Araputanga", "ARA"), _email("Ipixuna do Pará", "IPX"),
                                                                         _email("Sete Lagoas", "STL"), _email("Tupi Paulista", "TUP")])
    api = {"usina": "Sete Lagoas", "plant_id": 18771901, "qtd_inversores": 10, "strings_ativas": 240, "str_esp": None,
           "diferenca": None, "ultima_leitura": "2026-09-11 14:20", "sem_dados": False, "falha_comunicacao": False}
    monkeypatch.setattr(app, "_2capi_cache", {"payload": {"rows": [api, dict(api, usina="Araputanga", plant_id=18771898)]}})
    d = cli.get("/api/owen/strings/data").get_json()
    por = {r["usina"]: r for r in d["rows"]}
    assert set(por) == {"Araputanga", "Ipixuna do Pará", "Sete Lagoas", "Tupi Paulista"}       # uma linha por usina
    assert por["Sete Lagoas"]["plant_id"] == 18771901 and por["Sete Lagoas"]["sub_fonte"] == "api"
    assert por["Sete Lagoas"]["strings_ativas"] == 240 and por["Sete Lagoas"]["falha_comunicacao"] is False   # a linha viva
    assert por["Ipixuna do Pará"]["plant_id"] == "IPX" and por["Ipixuna do Pará"]["sub_fonte"] == "email"
    assert por["Tupi Paulista"]["sub_fonte"] == "email"                                        # sem linha da API → e-mail
    assert d["summary"]["total_usinas"] == 4


def test_sem_cache_da_api_a_aba_continua_pelo_email(cli, monkeypatch):
    monkeypatch.setattr(app, "_owen_strings_rows", lambda force=False: [_email("Araputanga", "ARA")])
    monkeypatch.setattr(app, "_2capi_cache", {"payload": None, "ts": 0.0})
    d = cli.get("/api/owen/strings/data").get_json()
    assert d["rows"][0]["plant_id"] == "ARA" and d["rows"][0]["sub_fonte"] == "email"


def test_drill_de_usina_da_api_delega_ao_motor_da_api_pv(cli, monkeypatch):
    invs = [{"id": 400771, "nome": "Inversor 1.1", "strings_ativas": 24, "str_esp": None, "diferenca": None, "strings": []}]
    monkeypatch.setattr(app, "_pv_plant_inversores", lambda pid, force=False: invs if pid == 18771898 else [])
    d = cli.get("/api/owen/strings/plant/18771898").get_json()
    assert d["plant_id"] == 18771898 and d["inversores"][0]["nome"] == "Inversor 1.1" and d["sub_fonte"] == "api"


def test_etm_das_tres_vem_da_estacao_da_api(cli, monkeypatch):
    monkeypatch.setattr(app, "_owen_etm_build", lambda force=False: {})              # e-mail sem ETM hoje
    linha_api = {"usina": "Araputanga", "plant_id": 18771898, "severidade": 1, "flags": [], "sensores": {"poa": {"status": "ok"}},
                 "spark": {"labels": ["10:00"], "poa": [900], "ghi": [800]}, "sem_dados": False, "sem_curva": False}
    monkeypatch.setattr(app, "_2capi_etm_analise_cache", {"payload": {"rows": [linha_api]}})
    d = cli.get("/api/owen/etm/analise").get_json()
    por = {r["usina"]: r for r in d["rows"]}
    assert por["Araputanga"]["plant_id"] == 18771898 and por["Araputanga"]["sub_fonte"] == "api"
    assert por["Ipixuna do Pará"]["sem_dados"] is True and por["Ipixuna do Pará"].get("sub_fonte") == "email"


def test_front_tem_uma_aba_so_para_a_2c():
    mon = (RAIZ / "docs/redesign/Monitoramento (novo design).html").read_text(encoding="utf-8")
    assert "id:'2capi'" not in mon                                         # o seletor não oferece a aba separada
    assert "'2c':'2C (API PV + Email)'" in mon
    assert "_ehApiPv(" in mon                                             # linha numérica da 2C → curva/ETM pela API PV
    ent = (RAIZ / "docs/redesign/Entrada.html").read_text(encoding="utf-8")
    assert '"2C · API PV"' not in ent


def test_casa_pelo_codigo_do_email_mesmo_com_nome_diferente(cli, monkeypatch):
    """Depois do cadastro novo o e-mail passou a chamar a STL de 'Sete Lagoas 2' e a API de 'Sete Lagoas': por nome não
    casava e a usina aparecia duas vezes. O par é pelo CÓDIGO do e-mail → id da API (ARA/STL/TUP), não pelo nome."""
    monkeypatch.setattr(app, "_owen_strings_rows", lambda force=False: [_email("Sete Lagoas 2", "STL"), _email("Ipixuna do Pará", "IPX")])
    api = {"usina": "Sete Lagoas", "plant_id": 18771901, "qtd_inversores": 10, "strings_ativas": 240, "str_esp": None,
           "diferenca": None, "ultima_leitura": "2026-09-11 14:20", "sem_dados": False, "falha_comunicacao": False}
    monkeypatch.setattr(app, "_2capi_cache", {"payload": {"rows": [api]}})
    d = cli.get("/api/owen/strings/data").get_json()
    assert [(r["usina"], r["plant_id"], r["sub_fonte"]) for r in d["rows"]] == [("Sete Lagoas", 18771901, "api"), ("Ipixuna do Pará", "IPX", "email")]
    assert app._2C_EMAIL_PARA_API == {"ARA": 18771898, "STL": 18771901, "TUP": 18750925}


def test_etm_da_api_sem_par_no_email_entra_tambem(cli, monkeypatch):
    monkeypatch.setattr(app, "_owen_etm_build", lambda force=False: {})
    linha = lambda u, pid: {"usina": u, "plant_id": pid, "severidade": 1, "flags": [], "sensores": {}, "spark": {"labels": [], "poa": [], "ghi": []}, "sem_dados": False, "sem_curva": False}
    monkeypatch.setattr(app, "_2capi_etm_analise_cache", {"payload": {"rows": [linha("Sete Lagoas", 18771901), linha("Araputanga", 18771898)]}})
    monkeypatch.setattr(app, "OWEN_UFVS", {"ARA": "Araputanga", "IPX": "Ipixuna do Pará", "STL": "Sete Lagoas 2"})
    d = cli.get("/api/owen/etm/analise").get_json()
    por = {r["plant_id"]: r for r in d["rows"]}
    assert set(por) == {18771901, 18771898, "IPX"}                    # STL do e-mail virou a Sete Lagoas da API; Ipixuna segue
    assert por[18771901]["sub_fonte"] == "api" and por["IPX"]["sub_fonte"] == "email"
