# -*- coding: utf-8 -*-
"""O gestor que entra pelo passe do Nexus não faz a plataforma falar com a API PV (porta única, 09/10/2026; spec 5.3:
"sem abrir a API PV na hora").

É a prova do `test_nexus_sem_api_pv.py` (a ponte de 04/10) para a sessão de GESTOR: a rede inteira cortada, TODA rota
GET que o gestor alcança chamada com a sessão dele, e nenhuma tentativa de falar com a API PV, nem nas threads que o
pedido abriu. As rotas que abrem a usina na API PV na hora são 403 (`NEGADOS_API_PV_GESTOR`); o resto serve o que a
plataforma já tem, porque o pedido do gestor leva `nexus_so_leitura` e o `pedido_do_nexus` trava a API PV para ele.
"""
import re
import socket
import threading
import time

import pytest

import app
import leitura_nexus as ln
import porta_nexus as pn

CHAVE = "chave-de-teste-do-passe-" + "x" * 20
_SLEEP = time.sleep

# Como o test_nexus_sem_api_pv.py, este arquivo CONTA as tentativas de falar com a API PV na resolução do nome
# (`rede_cortada`). A trava das fontes pagas do conftest.py recusaria antes, e a contagem daria zero sempre: o teste
# passaria sem provar nada. Com a marca, o pedido segue até a resolução, que aqui está cortada.
pytestmark = pytest.mark.rede_cortada_pelo_teste


def _e_api_pv(host: str) -> bool:
    return "pvoperation.com" in host


@pytest.fixture
def rede_cortada(monkeypatch):
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
    monkeypatch.setattr(time, "sleep", lambda s: _SLEEP(min(s, 0.01)))
    return tentativas


@pytest.fixture
def cli_gestor(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "senha-de-teste")
    monkeypatch.setattr(app, "NEXUS_SSO_CHAVE", CHAVE)
    monkeypatch.setattr(app, "PLATAFORMA_ANALISTAS", pn.ler_lista(""))
    monkeypatch.setattr(app, "PLATAFORMA_GESTORES", pn.ler_lista("*"))
    monkeypatch.setattr(app, "_PASSES_USADOS", pn.NumerosUsados())
    monkeypatch.setattr(app, "_MODO_WEB", True)
    monkeypatch.setitem(app.app.config, "PROPAGATE_EXCEPTIONS", False)
    cli = app.app.test_client()
    p = pn.assinar_passe({"v": 1, "email": "gestor@exemplo.com", "nome": "Gestor", "admin": True,
                          "destino": "/tempo-real", "vence": time.time() + 60, "numero": "numero-do-gestor-0001"}, CHAVE)
    assert cli.post("/painel/nexus/entrar", data={"passe": p}).status_code == 303
    return cli


def _exemplos(regra: str):
    fontes = ln.FONTES_API if "<fonte>" in regra else ("",)
    for f in fontes:
        u = regra.replace("<fonte>", f)
        u = re.sub(r"<int:[^>]+>", "297410", u)          # Barretos 1: usina de verdade da API PV
        u = re.sub(r"<[^>]+>", "x", u)
        yield u


def _rotas_do_gestor():
    vistos = set()
    for r in app.app.url_map.iter_rules():
        if "GET" not in r.methods or r.rule.startswith("/painel/nexus/") or r.rule == "/logout":
            continue                                         # o /logout encerraria a sessão no meio da varredura
        for u in _exemplos(r.rule):
            if u not in vistos and ln.permitido_gestor("GET", u):
                vistos.add(u)
                yield u


def _esperar_threads(antes, teto_s=8.0):
    fim = time.time() + teto_s
    for t in [t for t in threading.enumerate() if t not in antes]:
        t.join(max(0.0, fim - time.time()))


def test_nenhuma_rota_do_gestor_fala_com_a_api_pv(cli_gestor, rede_cortada):
    culpadas, barradas = {}, []
    rotas = list(_rotas_do_gestor())
    assert len(rotas) > 80                                   # a lista não encolheu sem querer
    for url in rotas:
        rede_cortada.clear()
        antes = set(threading.enumerate())
        r = cli_gestor.get(url)
        _esperar_threads(antes)
        if r.status_code in (401, 403):
            barradas.append(f"{url}: {r.status_code}")
        pv = sorted({f"{h} ({t})" for h, t in rede_cortada if _e_api_pv(h)})
        if pv:
            culpadas[url] = pv
    assert not culpadas, "rotas que o gestor alcança e falam com a API PV:\n" + "\n".join(
        f"  {u}: {', '.join(v)}" for u, v in sorted(culpadas.items()))
    assert not barradas, f"rotas que a lista do gestor deixa passar e o portão barrou: {barradas}"
