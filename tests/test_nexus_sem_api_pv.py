# -*- coding: utf-8 -*-
"""A chave de leitura do Nexus não faz a plataforma falar com a API PV (Levi, 05/10/2026: "por hora não puxa nada da
API da thopen, estou tentando economizar requests e tenho medo que duplique as chamadas").

A API PV (`*.pvoperation.com*`) atende a Thopen e também a SEMP, a Alves Lima e a 2C-API. O pedido que chega pela
ponte do Nexus só pode servir o que a plataforma já tem (cache e acervo): nem chamada na hora, nem reconstrução em fundo
disparada por ele. Prova: a rede inteira cortada, toda rota GET que a chave alcança chamada com a chave, e nenhuma
tentativa de falar com a API PV — nem no pedido, nem nas threads que ele abriu.
"""
import re
import socket
import threading
import time

import pytest

import app
import leitura_nexus as ln

CHAVE = "chave-de-teste-nexus"
_SLEEP = time.sleep

# Este arquivo CONTA as tentativas de falar com a API PV na resolução do nome (`rede_cortada`). A trava das fontes pagas
# do conftest.py recusa antes disso, e a contagem daria zero sempre — o teste da trava do Nexus passaria sem provar
# nada. Com a marca, o pedido segue até a resolução, que aqui está cortada; sem ela trocada, a trava recusa igual.
pytestmark = pytest.mark.rede_cortada_pelo_teste


def _e_api_pv(host: str) -> bool:
    return "pvoperation.com" in host


@pytest.fixture
def rede_cortada(monkeypatch):
    """Toda conexão de saída falha na resolução do nome, e fica anotada (host, thread). O psycopg2 (libpq, em C) não
    passa pelo socket do Python: cortado à parte."""
    tentativas = []

    def resolver(host, *a, **k):
        tentativas.append((str(host), threading.current_thread().name))
        raise socket.gaierror("rede cortada no teste")

    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    try:
        import psycopg2

        def _sem_banco(*a, **k):
            tentativas.append(("postgresql", threading.current_thread().name))
            raise psycopg2.OperationalError("rede cortada no teste")
        monkeypatch.setattr(psycopg2, "connect", _sem_banco)
    except ImportError:
        pass
    # nova tentativa com espera não pode alongar o teste
    monkeypatch.setattr(time, "sleep", lambda s: _SLEEP(min(s, 0.01)))
    return tentativas


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(app, "NEXUS_LEITURA_TOKEN", CHAVE)
    monkeypatch.setattr(app, "_MODO_WEB", True)           # como o processo web do servidor
    # erro de rota vira 500, como no servidor: na suíte inteira outro teste liga o TESTING e o erro subia até aqui
    monkeypatch.setitem(app.app.config, "PROPAGATE_EXCEPTIONS", False)
    return app.app.test_client()


def _exemplos(regra: str):
    """Um endereço de exemplo por rota; `<fonte>` vira cada fonte do Monitoramento."""
    fontes = ln.FONTES_API if "<fonte>" in regra else ("",)
    for f in fontes:
        u = regra.replace("<fonte>", f)
        u = re.sub(r"<int:[^>]+>", "297410", u)          # Barretos 1: usina de verdade da API PV
        u = re.sub(r"<[^>]+>", "x", u)
        yield u


def _rotas_da_chave():
    vistos = set()
    for r in app.app.url_map.iter_rules():
        if "GET" not in r.methods:
            continue
        for u in _exemplos(r.rule):
            if u not in vistos and ln.permitido("GET", u):
                vistos.add(u)
                yield u


def _esperar_threads(antes, teto_s=8.0):
    fim = time.time() + teto_s
    for t in [t for t in threading.enumerate() if t not in antes]:
        t.join(max(0.0, fim - time.time()))


def test_nenhuma_rota_da_chave_fala_com_a_api_pv(cli, rede_cortada):
    culpadas = {}
    rotas = list(_rotas_da_chave())
    assert len(rotas) > 50                                   # a lista não encolheu sem querer
    for url in rotas:
        rede_cortada.clear()
        antes = set(threading.enumerate())
        cli.get(url, headers={"X-Nexus-Leitura": CHAVE})
        _esperar_threads(antes)
        pv = sorted({f"{h} ({t})" for h, t in rede_cortada if _e_api_pv(h)})
        if pv:
            culpadas[url] = pv
    assert not culpadas, "rotas que a chave do Nexus alcança e falam com a API PV:\n" + "\n".join(
        f"  {u}: {', '.join(v)}" for u, v in sorted(culpadas.items()))


def test_sem_a_chave_tudo_segue_como_antes(cli, rede_cortada, monkeypatch):
    """A trava é do pedido do Nexus: o analista na plataforma continua abrindo a usina na API PV, inclusive na mesma
    thread logo depois de um pedido do Nexus."""
    monkeypatch.setattr(app, "DASH_PASSWORD", "")          # plataforma aberta: o pedido sem a chave entra sem login
    cli.get("/api/data", headers={"X-Nexus-Leitura": CHAVE})
    rede_cortada.clear()
    cli.get("/api/plant/297410")
    assert any(_e_api_pv(h) for h, _t in rede_cortada)


def test_thread_e_tarefa_abertas_pelo_pedido_herdam_a_trava(rede_cortada):
    import requests
    from concurrent.futures import ThreadPoolExecutor
    from flask import g

    url = "https://apipv.pvoperation.com.br/api/v1/plants"
    res = {}

    def chama(nome):
        try:
            requests.get(url, timeout=1)
        except Exception as e:                               # noqa: BLE001
            res[nome] = type(e)
    pool = ThreadPoolExecutor(max_workers=1)                 # criado ANTES: o operário é de todo mundo
    with app.app.test_request_context("/api/data"):
        g.nexus_leitura_ok = True
        t = threading.Thread(target=chama, args=("thread",))
        t.start()
        t.join()
        pool.submit(chama, "tarefa").result()
    pool.submit(chama, "depois").result()                    # mesmo operário, pedido de outra pessoa
    pool.shutdown()
    assert res["thread"] is app.PVForaDoAr and res["tarefa"] is app.PVForaDoAr
    assert res["depois"] is not app.PVForaDoAr               # foi à rede (cortada no teste): a marca não ficou no operário
    assert sum(1 for h, _t in rede_cortada if _e_api_pv(h)) == 1
