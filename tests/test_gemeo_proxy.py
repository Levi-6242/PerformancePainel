# tests/test_gemeo_proxy.py
"""Proxy /gemeo/* da plataforma para o gemeo (Tarefa 20 do plano do gemeo): manda a senha no header,
preserva query string, status, content-type e Location; gemeo fora do ar vira 503, nunca 500."""
import pytest
import requests
import app as plataforma


class _Resp:
    def __init__(self, status=200, content=b"<html>ok</html>", ctype="text/html; charset=utf-8", extra=None):
        self.status_code, self.content = status, content
        self.headers = {"Content-Type": ctype, **(extra or {})}


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(plataforma, "DASH_PASSWORD", "")      # gate da plataforma aberto: aqui se testa so o proxy
    monkeypatch.setattr(plataforma, "GEMEO_SENHA", "segredo")
    plataforma.app.config["TESTING"] = True
    return plataforma.app.test_client()


def test_proxy_repassa_header_query_status_e_tipo(cli, monkeypatch):
    visto = {}

    def fake(method, url, **kw):
        visto.update(method=method, url=url, **kw)
        return _Resp(status=200, content=b'{"ok":true}', ctype="application/json")

    monkeypatch.setattr(plataforma.requests, "request", fake)
    r = cli.get("/gemeo/api/frota?agora=2026-08-31T20:00:00Z")
    assert r.status_code == 200 and r.content_type == "application/json" and r.get_json() == {"ok": True}
    assert visto["url"] == "http://127.0.0.1:5075/gemeo/api/frota" and visto["method"] == "GET"
    assert visto["headers"]["X-Gemeo-Senha"] == "segredo" and visto["params"] == {"agora": ["2026-08-31T20:00:00Z"]}
    assert visto["allow_redirects"] is False


def test_raiz_e_subcaminhos_vao_para_o_mesmo_prefixo(cli, monkeypatch):
    urls = []
    monkeypatch.setattr(plataforma.requests, "request", lambda m, u, **kw: urls.append(u) or _Resp())
    cli.get("/gemeo/"); cli.get("/gemeo/usina/7"); cli.get("/gemeo/static/gemeo.css")
    assert urls == ["http://127.0.0.1:5075/gemeo/", "http://127.0.0.1:5075/gemeo/usina/7", "http://127.0.0.1:5075/gemeo/static/gemeo.css"]


def test_gemeo_fora_do_ar_da_503_e_nao_500(cli, monkeypatch):
    def fora(*a, **kw):
        raise requests.ConnectionError("recusada")

    monkeypatch.setattr(plataforma.requests, "request", fora)
    r = cli.get("/gemeo/")
    assert r.status_code == 503 and "fora do ar" in r.get_data(as_text=True)


def test_status_e_location_do_gemeo_sao_preservados(cli, monkeypatch):
    monkeypatch.setattr(plataforma.requests, "request",
                        lambda m, u, **kw: _Resp(status=302, content=b"", extra={"Location": "/gemeo/login?next=/gemeo/"}))
    r = cli.get("/gemeo/")
    assert r.status_code == 302 and r.headers["Location"] == "/gemeo/login?next=/gemeo/"
