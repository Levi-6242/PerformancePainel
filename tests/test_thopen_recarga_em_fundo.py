# -*- coding: utf-8 -*-
"""A recarga vencida do BD_Thopen em segundo plano (Levi, 11/11/2026: "quando fica muito tempo aberto para de ler os
dados, fica tudo branco"): a requisição depois do TTL leva a leitura de antes na hora e a nova entra quando fica pronta;
só a subida e o Atualizar esperam a rede. E a tela não fica em branco calada quando um pedido falha."""
import os
import sys
import threading
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "thopen"))
import fonte_api  # noqa: E402


@pytest.fixture
def api(monkeypatch):
    chamadas, libera = [], threading.Event()
    libera.set()

    def baixa(tok):
        chamadas.append(threading.current_thread().name)
        libera.wait(5)
        return {"n": len(chamadas)}
    monkeypatch.setattr(fonte_api, "_baixa", baixa)
    monkeypatch.setattr(fonte_api, "_workbook_de", lambda p: SimpleNamespace(sheetnames=["aba"], n=p["n"]))
    monkeypatch.setattr(fonte_api, "_grava_cache", lambda *a: None)
    monkeypatch.setattr(fonte_api, "_token", lambda: "tok")
    monkeypatch.setattr(fonte_api, "_cache", {"ts": 0.0, "wb": None, "erro": None, "origem": None, "proxima": 0.0,
                                              "recarregando": False})
    return chamadas, libera


def _espera_fundo():
    for t in threading.enumerate():
        if t.name == "bd_thopen_recarga":
            t.join(5)


def test_a_subida_espera_a_rede(api):
    chamadas, _ = api
    assert fonte_api.workbook().n == 1 and chamadas == [threading.current_thread().name]


def test_vencido_leva_o_de_antes_e_recarrega_em_fundo(api):
    chamadas, libera = api
    fonte_api.workbook()
    fonte_api._cache["ts"] -= fonte_api.TTL + 1                 # venceu
    libera.clear()                                              # a rede "demora"
    t0 = time.time()
    assert fonte_api.workbook().n == 1                    # na hora, o de antes
    assert time.time() - t0 < 1
    assert fonte_api.workbook().n == 1                    # uma recarga só, mesmo com dois pedidos
    libera.set()
    _espera_fundo()
    assert chamadas[1:] == ["bd_thopen_recarga"]
    assert fonte_api.workbook().n == 2 and fonte_api._cache["recarregando"] is False


def test_falha_em_fundo_segue_com_o_de_antes(api, monkeypatch):
    fonte_api.workbook()
    fonte_api._cache["ts"] -= fonte_api.TTL + 1

    def cai(tok):
        raise OSError("sem rede")
    monkeypatch.setattr(fonte_api, "_baixa", cai)
    assert fonte_api.workbook().n == 1
    _espera_fundo()
    assert fonte_api._cache["wb"].n == 1 and fonte_api._cache["proxima"] > time.time()
    assert fonte_api._cache["recarregando"] is False and "sem rede" in fonte_api._cache["erro"]
    assert fonte_api.workbook().n == 1                    # na carência, nem tenta


def test_o_atualizar_espera_a_rede(api):
    chamadas, _ = api
    fonte_api.workbook()
    assert fonte_api.workbook(forcar=True).n == 2 and len(chamadas) == 2
    assert chamadas[1] == threading.current_thread().name


T = open(os.path.join(os.path.dirname(__file__), "..", "thopen", "templates", "dashboard_thopen.html"),
         encoding="utf-8").read()


def test_a_tela_avisa_o_pedido_que_falhou():
    assert "if(r.status>=500) throw new Error('servidor '+r.status);" in T
    assert "addEventListener('unhandledrejection'" in T and 'id="avisoFalha"' in T and "tentarDeNovo()" in T
