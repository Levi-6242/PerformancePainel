# -*- coding: utf-8 -*-
"""Card "Criar OS" na Entrada + proxy /os/* para o OS Creator web (serviço do repositório oem, porta 5090) — Levi,
12/09/2026: "traga toda a estrutura do OS Creator para a plataforma, de forma que para entrar no card tenha que logar
no Fracttal". Mesmo desenho do proxy do Gêmeo, com UMA diferença: a sessão do Fracttal de cada pessoa vive num cookie
do serviço (os_sessao, Path=/os), então o proxy repassa esse cookie nos dois sentidos."""
import pathlib

import pytest
import requests

import app as plataforma

RAIZ = pathlib.Path(plataforma.__file__).resolve().parents[1]


class _Resp:
    def __init__(self, status=200, content=b"<html>ok</html>", ctype="text/html; charset=utf-8", extra=None, set_cookies=()):
        self.status_code, self.content = status, content
        self.headers = {"Content-Type": ctype, **(extra or {})}
        self.raw = type("Raw", (), {"headers": type("H", (), {"getlist": lambda self, k: list(set_cookies) if k.lower() == "set-cookie" else []})()})()


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(plataforma, "DASH_PASSWORD", "")
    plataforma.app.config["TESTING"] = True
    return plataforma.app.test_client()


def test_proxy_repassa_metodo_query_corpo_e_o_cookie_da_sessao_do_fracttal(cli, monkeypatch):
    visto = {}

    def fake(method, url, **kw):
        visto.update(method=method, url=url, **kw)
        return _Resp(status=200, content=b'{"ok":true}', ctype="application/json")
    monkeypatch.setattr(plataforma.requests, "request", fake)
    cli.set_cookie("os_sessao", "abc.def", path="/os")
    cli.set_cookie("session", "da-plataforma", path="/")
    r = cli.post("/os/api/performance/criar?x=1", data=b'{"a":1}', content_type="application/json")
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    assert visto["method"] == "POST" and visto["url"] == "http://127.0.0.1:5090/os/api/performance/criar"
    assert visto["params"] == {"x": ["1"]} and visto["data"] == b'{"a":1}' and visto["allow_redirects"] is False
    assert visto["headers"]["Content-Type"] == "application/json"
    assert visto["headers"]["Cookie"] == "os_sessao=abc.def"            # so o cookie do servico; o da plataforma nao vaza


def test_proxy_devolve_os_set_cookie_do_servico_e_o_location(cli, monkeypatch):
    monkeypatch.setattr(plataforma.requests, "request", lambda m, u, **kw: _Resp(
        status=302, content=b"", extra={"Location": "/os/"},
        set_cookies=["os_sessao=novo; HttpOnly; Path=/os; SameSite=Lax"]))
    r = cli.post("/os/login", data={"email": "x", "senha": "y"})
    assert r.status_code == 302 and r.headers["Location"] == "/os/"
    assert "os_sessao=novo" in r.headers.get("Set-Cookie", "") and "Path=/os" in r.headers.get("Set-Cookie", "")


def test_raiz_e_subcaminhos_vao_para_o_mesmo_prefixo(cli, monkeypatch):
    urls = []
    monkeypatch.setattr(plataforma.requests, "request", lambda m, u, **kw: urls.append(u) or _Resp())
    cli.get("/os/"); cli.get("/os/historico"); cli.get("/os/static/os.css")
    assert urls == ["http://127.0.0.1:5090/os/", "http://127.0.0.1:5090/os/historico", "http://127.0.0.1:5090/os/static/os.css"]


def test_servico_fora_do_ar_da_503_e_nao_500(cli, monkeypatch):
    def fora(*a, **kw):
        raise requests.ConnectionError("recusada")
    monkeypatch.setattr(plataforma.requests, "request", fora)
    r = cli.get("/os/")
    assert r.status_code == 503 and "fora do ar" in r.get_data(as_text=True)


def test_a_area_exige_o_login_da_plataforma_antes_do_fracttal(monkeypatch):
    monkeypatch.setattr(plataforma, "DASH_PASSWORD", "x")
    plataforma.app.config["TESTING"] = True
    r = plataforma.app.test_client().get("/os/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_entrada_tem_o_quarto_card_criar_os():
    ent = (RAIZ / "docs/redesign/Entrada.html").read_text(encoding="utf-8")
    assert 'data-href="/os/"' in ent and ">Criar OS</a>" in ent
    assert "Para quem <b>executa</b>" in ent and "login Fracttal" in ent
    assert "grid-template-columns:repeat(4,1fr)" in ent           # 3 leituras + a acao, lado a lado
    assert ent.index('data-href="/gerencial"') < ent.index('data-href="/os/"')   # a acao vem depois das tres leituras


def test_proxy_repassa_download_e_o_cabecalho_do_fetch(cli, monkeypatch):
    """As telas portadas em 13/09 exportam CSV (Content-Disposition) e pedem fragmentos com X-Requested-With: fetch —
    sem repassar os dois, o CSV abria inline e o card de detalhe vinha com a pagina inteira."""
    visto = {}

    def fake(method, url, **kw):
        visto.update(**kw)
        return _Resp(status=200, content=b"a;b", ctype="text/csv; charset=utf-8",
                     extra={"Content-Disposition": 'attachment; filename="solicitacoes.csv"'})
    monkeypatch.setattr(plataforma.requests, "request", fake)
    r = cli.get("/os/solicitacao/historico.csv", headers={"X-Requested-With": "fetch"})
    assert r.status_code == 200 and r.headers["Content-Disposition"] == 'attachment; filename="solicitacoes.csv"'
    assert visto["headers"]["X-Requested-With"] == "fetch"
