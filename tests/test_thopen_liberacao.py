# -*- coding: utf-8 -*-
"""O que o cliente já pode ver (Levi, 27/10/2026: "vamos subir as atualizações primeiro para o usuário de performance, o
usuário thopen que é o do cliente só vê se eu liberar"; "zeladoria pode tirar da visualização do cliente thopen"). A
novidade sobe fechada em LIBERADO_AO_CLIENTE: o papel grid vê, a conta de cliente não (nem a aba, nem a rota)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "thopen"))
import acessos  # noqa: E402
import dashboard_thopen as dth  # noqa: E402

CONTAS = {"c1": {"conta_id": "c1", "nome": "Cliente Teste", "email": "cliente@exemplo.com", "usuario": "cliente",
                 "carteiras": list(acessos.CARTEIRAS), "papel": "cliente"},
          "c3": {"conta_id": "c3", "nome": "Conta Grid", "email": "grid@exemplo.com", "usuario": "grid@exemplo.com",
                 "carteiras": list(acessos.CARTEIRAS), "papel": "grid"}}
ABA = 'data-page="zeladoria"'


@pytest.fixture
def entra(monkeypatch):
    monkeypatch.setenv("THOPEN_LOGIN", "1")
    monkeypatch.setitem(dth.app.config, "SESSION_COOKIE_SECURE", False)
    monkeypatch.setattr(acessos, "conta", lambda cid: CONTAS.get(cid))
    monkeypatch.setattr(dth, "_usinas_disponiveis", lambda: ["Altair"])

    def _cli(cid):
        c = dth.app.test_client()
        with c.session_transaction() as s:
            s["conta_id"] = cid
        return c
    return _cli


def test_zeladoria_fechada_ao_cliente():
    assert dth.LIBERADO_AO_CLIENTE.get("zeladoria") is False


def test_cliente_nao_ve_a_aba_nem_a_rota(entra):
    c = entra("c1")
    assert ABA not in c.get("/").get_data(as_text=True)
    r = c.get("/api/t/zeladoria?carteira=Thopen")
    assert r.status_code == 403 and "liberada" in r.get_json()["erro"]


def test_grid_ve_a_aba_e_passa_do_portao(entra, monkeypatch):
    import fonte_zeladoria
    monkeypatch.setattr(fonte_zeladoria, "ligada", lambda: False)        # passa do portão sem ler o banco
    c = entra("c3")
    assert ABA in c.get("/").get_data(as_text=True)
    assert c.get("/api/t/zeladoria?carteira=Thopen").status_code == 200


def test_liberada_o_cliente_ve(entra, monkeypatch):
    monkeypatch.setitem(dth.LIBERADO_AO_CLIENTE, "zeladoria", True)
    c = entra("c1")
    assert ABA in c.get("/").get_data(as_text=True)


def test_login_desligado_ve_tudo(monkeypatch):
    # o painel sem login (as cópias de prova) segue o _e_grid de sempre; no ar, o 5080 e o servidor têm o login ligado
    monkeypatch.delenv("THOPEN_LOGIN", raising=False)
    assert ABA in dth.app.test_client().get("/").get_data(as_text=True)
