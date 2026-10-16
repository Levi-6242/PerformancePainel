# -*- coding: utf-8 -*-
"""O portão do login no 5080 (14/10/2026, spec docs/superpowers/specs/2026-10-14-thopen-login-por-pessoa-design.md): com
THOPEN_LOGIN=1 tudo pede sessão, cada conta vê só as usinas das carteiras dela, só o papel Grid grava; o convite define a
senha e já entra; o limite de tentativas; o caminho /performance. As contas são falsas (o acessos.py tem os testes dele)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "thopen"))
import acessos  # noqa: E402
import dashboard_thopen as dth  # noqa: E402

CONTAS = {"c1": {"conta_id": "c1", "nome": "Ana Souza", "email": "ana@thopen.com.br", "carteiras": ["Thopen"],
                 "papel": "cliente"},
          "c2": {"conta_id": "c2", "nome": "Paula", "email": "paula@polaris.com", "carteiras": ["Polaris", "Matrix"],
                 "papel": "cliente"},
          "c3": {"conta_id": "c3", "nome": "Levi", "email": "levi@gridco.com.br", "carteiras": list(acessos.CARTEIRAS),
                 "papel": "grid"}}
SENHAS = {"ana@thopen.com.br": "senha-da-ana-1", "paula@polaris.com": "senha-da-paula", "levi@gridco.com.br": "grid-123456"}
USINAS = ["Altair", "Guaratinguetá V", "Belo Jardim"]         # Thopen, Polaris, Matrix


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setenv("THOPEN_LOGIN", "1")
    monkeypatch.setitem(dth.app.config, "SESSION_COOKIE_SECURE", False)      # o cliente de teste é http
    ativas = dict(CONTAS)
    monkeypatch.setattr(acessos, "conta", lambda cid: ativas.get(cid))
    monkeypatch.setattr(acessos, "verificar",
                        lambda e, s: next((c for c in ativas.values() if c["email"] == e and SENHAS.get(e) == s), None))
    monkeypatch.setattr(acessos, "estado", lambda: {"erro": None, "contas": len(ativas)})
    definidas = []
    monkeypatch.setattr(acessos, "convite", lambda tk: (CONTAS["c1"], "ok") if tk == "T-OK" else (None, "vencido"))
    monkeypatch.setattr(acessos, "definir_senha", lambda tk, s: definidas.append((tk, s)) or CONTAS["c1"])
    monkeypatch.setattr(dth, "_usinas_disponiveis", lambda: list(USINAS))
    monkeypatch.setattr(dth, "_TENTATIVAS", acessos.Limite(tentativas=5, janela=900))
    c = dth.app.test_client()
    c.ativas, c.definidas = ativas, definidas
    return c


def _entra(c, email):
    return c.post("/login", data={"usuario": email, "senha": SENHAS[email]})


def test_sem_sessao_a_pagina_vai_para_a_entrada_e_a_api_responde_401(cli):
    r = cli.get("/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/login")
    assert cli.get("/api/t/usinas").status_code == 401
    assert cli.get("/login").status_code == 200 and "Entrar" in cli.get("/login").get_data(as_text=True)


def test_entra_e_ve_so_as_usinas_das_carteiras_dela(cli):
    r = _entra(cli, "ana@thopen.com.br")
    assert r.status_code == 302 and r.headers["Location"].endswith("/")
    u = cli.get("/api/t/usinas").get_json()
    assert u["usinas"] == ["Altair"] and u["carteiras"] == ["Thopen"]
    for rota in ("/api/t/overview", "/api/t/diario", "/api/t/operacao", "/api/t/rondas"):
        assert cli.get(rota + "?usina=Guaratinguet%C3%A1%20V&ano=2026&mes=10").status_code == 403, rota
    assert cli.get("/api/t/geral?carteira=Polaris&ano=2026&mes=10").status_code == 403
    r = cli.post("/api/t/contestar", json={"usina": "Belo Jardim", "ano": 2026, "mes": 10, "dia_ini": 1, "dia_fim": 1})
    assert r.status_code == 403
    html = cli.get("/").get_data(as_text=True)
    assert '"nome": "Ana Souza"' in html and '"papel": "cliente"' in html


def test_cliente_nao_grava_comentario_nem_forca_a_releitura_e_a_grid_sim(cli, monkeypatch):
    _entra(cli, "ana@thopen.com.br")
    assert cli.post("/api/t/comentario_extra", json={"usina": "Altair", "texto": "x"}).status_code == 403
    assert cli.get("/api/t/reload").status_code == 403
    grid = dth.app.test_client()
    _entra(grid, "levi@gridco.com.br")
    assert grid.get("/api/t/usinas").get_json()["usinas"] == USINAS                 # a Grid vê todas
    # a Grid passa do portão: sem a usina a rota responde 400 (e nada é gravado no arquivo de verdade)
    assert grid.post("/api/t/comentario_extra", json={"texto": "x"}).status_code == 400


def test_conta_desativada_sai_no_pedido_seguinte(cli):
    _entra(cli, "paula@polaris.com")
    assert cli.get("/api/t/usinas").status_code == 200
    cli.ativas.pop("c2")                                                            # desativada no Nexus
    assert cli.get("/api/t/usinas").status_code == 401
    assert cli.get("/").status_code == 302


def test_senha_errada_e_limite_de_tentativas(cli):
    for _ in range(5):
        r = cli.post("/login", data={"usuario": "ana@thopen.com.br", "senha": "errada"})
        assert "não conferem" in r.get_data(as_text=True)
    r = cli.post("/login", data={"usuario": "ana@thopen.com.br", "senha": SENHAS["ana@thopen.com.br"]})
    assert r.status_code == 200 and "Muitas tentativas" in r.get_data(as_text=True)


def test_convite_define_a_senha_e_ja_entra(cli):
    assert "Definir senha" in cli.get("/convite/T-OK").get_data(as_text=True)
    r = cli.post("/convite/T-OK", data={"senha": "uma-senha-boa", "senha2": "outra-senha-x"})
    assert "não são iguais" in r.get_data(as_text=True) and cli.definidas == []
    r = cli.post("/convite/T-OK", data={"senha": "uma-senha-boa", "senha2": "uma-senha-boa"})
    assert r.status_code == 302 and cli.definidas == [("T-OK", "uma-senha-boa")]
    assert cli.get("/api/t/usinas").get_json()["usinas"] == ["Altair"]
    assert "venceu" in cli.get("/convite/OUTRO").get_data(as_text=True)


def test_sair_encerra_a_sessao(cli):
    _entra(cli, "ana@thopen.com.br")
    assert cli.get("/logout").status_code == 302
    assert cli.get("/api/t/usinas").status_code == 401


def test_login_desligado_e_o_painel_de_antes(monkeypatch):
    monkeypatch.delenv("THOPEN_LOGIN", raising=False)
    monkeypatch.setattr(dth, "_usinas_disponiveis", lambda: list(USINAS))
    c = dth.app.test_client()
    assert c.get("/api/t/usinas").get_json()["usinas"] == USINAS


def test_cookie_proprio_e_o_caminho_do_prefixo():
    assert dth.app.config["SESSION_COOKIE_NAME"] == "thopen_sessao"
    vistos = []

    def app_wsgi(environ, start_response):
        vistos.append((environ["SCRIPT_NAME"], environ["PATH_INFO"]))
        return []
    p = dth._Prefixo(app_wsgi, "/performance")
    p({"PATH_INFO": "/performance/login"}, None)           # o Caddy passou o caminho inteiro
    p({"PATH_INFO": "/login"}, None)                       # o Caddy tirou o prefixo
    p({"PATH_INFO": "/performance"}, None)
    assert vistos == [("/performance", "/login"), ("/performance", "/login"), ("/performance", "/")]


def test_link_usado_com_a_pessoa_ja_conectada_vai_ao_painel(cli, monkeypatch):
    # 15/10/2026: o "Salvar e entrar" clicado três vezes — o 1º gravou a senha e entrou, o 2º mostrou "já foi usado"
    _entra(cli, "ana@thopen.com.br")
    monkeypatch.setattr(acessos, "convite", lambda tk: (None, "usado"))
    r = cli.post("/convite/T-USADO", data={"senha": "x", "senha2": "x"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/")
    anonimo = dth.app.test_client()                                   # sem sessão: a mensagem de sempre
    assert "já foi usado" in anonimo.get("/convite/T-USADO").get_data(as_text=True)
    assert "f.dataset.enviando" in anonimo.get("/login").get_data(as_text=True)      # um envio só
