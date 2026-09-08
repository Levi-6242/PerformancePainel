# -*- coding: utf-8 -*-
"""As rotas do relay de tickets no Flask (/api/tickets/...): o encaixe entre o portão de login, a
identificação pelo Fracttal e o `tickets_relay`. A lógica em si está em test_tickets_relay.py;
aqui se prova que a rota chama a lógica com o que chegou e devolve o que ela devolveu.

`identificar` e o envio ao banco são dublados: nada aqui sai para a rede.
"""
import pytest

import app as plataforma
import tickets_relay as tr


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(plataforma, "DASH_PASSWORD", "senha-de-teste")   # o portão FECHADO
    monkeypatch.setattr(plataforma._estado_backup, "_token", lambda: "tok-servidor")
    plataforma.app.config["TESTING"] = True
    return plataforma.app.test_client()


@pytest.fixture
def levi(monkeypatch):
    monkeypatch.setattr(tr, "identificar", lambda jwt, **k: ("levi@gridco.com.br", "Levi Maia")
                        if jwt == "bom.jwt.aqui" else (_ for _ in ()).throw(tr.NaoAutenticado("sem login")))


@pytest.fixture
def banco(monkeypatch):
    """O banco atrás do relay: registra o que recebeu e responde 200 com o eco."""
    vistos = []

    def request(metodo, url, headers=None, json=None, timeout=None):
        vistos.append((metodo, url, headers, json))

        class R:
            status_code = 200
            text = '{"row_number": 154, "values": ["", "PTL200"]}'
        return R()
    monkeypatch.setattr(tr.requests, "request", request)
    monkeypatch.setattr(tr, "LOG", str(__import__("tempfile").mkdtemp()) + "/relay.log")
    return vistos


def test_o_portao_deixa_passar_e_o_handler_e_que_recusa(cli, levi):
    """Sem sessão humana, /api/* dá 401 pelo portão. O relay precisa passar pelo portão e ser
    recusado pelo PRÓPRIO handler — com a mensagem do Fracttal, não 'não autenticado' genérico."""
    r = cli.get("/api/tickets/quem")
    assert r.status_code == 401 and r.get_json()["error"] == "sem login"
    r = cli.get("/api/notificacoes")           # uma rota comum continua atrás do portão
    assert r.status_code == 401 and r.get_json()["error"] == "não autenticado"


def test_quem_sou_eu(cli, levi):
    r = cli.get("/api/tickets/quem", headers={"X-Fracttal-JWT": "bom.jwt.aqui"})
    assert r.status_code == 200 and r.get_json() == {"email": "levi@gridco.com.br", "nome": "Levi Maia"}


def test_put_chega_ao_banco_com_o_token_do_servidor_e_volta_o_eco(cli, levi, banco):
    r = cli.put("/api/tickets/128/rows/154", headers={"X-Fracttal-JWT": "bom.jwt.aqui"},
                json={"headers": ["", "Usina"], "values": ["", "PTL200"]})
    assert r.status_code == 200
    assert r.get_json()["row_number"] == 154, "o eco do banco tem de voltar inteiro para o app"
    metodo, url, cab, corpo = banco[0]
    assert (metodo, url) == ("PUT", tr.API + "/api/sheets/128/rows/154")
    assert cab["Authorization"] == "Bearer tok-servidor"
    assert corpo["values"] == ["", "PTL200"]


def test_post_no_diario_carimba_quem(cli, levi, banco):
    r = cli.post("/api/tickets/387/rows", headers={"X-Fracttal-JWT": "bom.jwt.aqui"},
                 json={"headers": ["quando", "quem"], "values": ["2026-09-07", "LEVIMA"]})
    assert r.status_code == 200
    assert banco[0][3]["values"] == ["2026-09-07", "Levi Maia"]


def test_delete_vai_sem_corpo(cli, levi, banco):
    r = cli.delete("/api/tickets/123/rows/7", headers={"X-Fracttal-JWT": "bom.jwt.aqui"})
    assert r.status_code == 200
    assert banco[0][0] == "DELETE" and banco[0][3] is None


def test_aba_fora_da_lista_e_403_sem_tocar_no_banco(cli, levi, banco):
    r = cli.put("/api/tickets/999/rows/1", headers={"X-Fracttal-JWT": "bom.jwt.aqui"}, json={})
    assert r.status_code == 403 and banco == []


def test_sem_jwt_nada_chega_ao_banco(cli, levi, banco):
    r = cli.put("/api/tickets/128/rows/1", json={"headers": ["Usina"], "values": ["X"]})
    assert r.status_code == 401 and banco == []


def test_plataforma_sem_token_diz_isso_com_503(cli, levi, banco, monkeypatch):
    monkeypatch.setattr(plataforma._estado_backup, "_token", lambda: "")
    r = cli.put("/api/tickets/128/rows/1", headers={"X-Fracttal-JWT": "bom.jwt.aqui"}, json={})
    assert r.status_code == 503 and "GRIDCO_SQL_TOKEN" in r.get_json()["error"]
    assert banco == []


def test_fracttal_fora_do_ar_e_502_e_nao_pede_login(cli, monkeypatch):
    """Fracttal indisponível não é culpa de quem clicou: 502, e não 401 (que faria o app pedir
    login de novo para nada)."""
    monkeypatch.setattr(tr, "identificar", lambda jwt, **k: (_ for _ in ()).throw(RuntimeError("HTTP 500")))
    r = cli.get("/api/tickets/quem", headers={"X-Fracttal-JWT": "x.y.z"})
    assert r.status_code == 502


def test_banco_fora_do_ar_e_503(cli, levi, monkeypatch):
    def fora(*a, **k):
        raise tr.requests.ConnectionError("recusada")
    monkeypatch.setattr(tr.requests, "request", fora)
    monkeypatch.setattr(tr, "LOG", str(__import__("tempfile").mkdtemp()) + "/relay.log")
    r = cli.put("/api/tickets/128/rows/1", headers={"X-Fracttal-JWT": "bom.jwt.aqui"},
                json={"headers": ["Usina"], "values": ["X"]})
    assert r.status_code == 503 and "fora do ar" in r.get_json()["error"]


def test_criar_aba_so_no_workbook_permitido(cli, levi, monkeypatch):
    vistos = []

    def post(url, headers=None, json=None, timeout=None):
        vistos.append(url)

        class R:
            status_code = 201
            text = '{"id": 900}'
        return R()
    monkeypatch.setattr(tr.requests, "post", post)
    monkeypatch.setattr(tr, "LOG", str(__import__("tempfile").mkdtemp()) + "/relay.log")
    r = cli.post("/api/tickets/workbooks/tickets_performance/sheets",
                 headers={"X-Fracttal-JWT": "bom.jwt.aqui"}, json={"sheet_name": "Edicoes do app v4"})
    assert r.status_code == 201 and r.get_json() == {"id": 900}
    r = cli.post("/api/tickets/workbooks/plataforma_estado/sheets",
                 headers={"X-Fracttal-JWT": "bom.jwt.aqui"}, json={"sheet_name": "x"})
    assert r.status_code == 403 and len(vistos) == 1
