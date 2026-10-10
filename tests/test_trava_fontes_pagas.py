# -*- coding: utf-8 -*-
"""A trava das fontes pagas do conftest.py (10/10/2026) recusa de verdade.

Medido em 10/10: cada rodada da suíte fazia 9 chamadas REAIS à API PV (paga) e à SunOp (cota estourada em setembro,
323 mil pedidos) e os testes passavam, porque o código engole a falha de rede. A trava só vale se recusar pelos dois
caminhos de HTTP (requests e urllib), por qualquer host das duas fontes, e se a marca do teste que conta pelo
`getaddrinfo` não virar porta aberta. Cada teste aqui apaga a própria tentativa, senão o fixture da trava o quebraria
— que é justamente o comportamento que se quer para os outros.
"""
import socket
import sys
import urllib.error
import urllib.request

import pytest
import requests

TRAVA = sys.modules["conftest"]


@pytest.fixture
def tentativas():
    """Devolve a posição de onde começam as tentativas deste teste e as apaga no fim (ver o docstring do arquivo)."""
    antes = len(TRAVA.FONTE_PAGA_TENTATIVAS)
    yield antes
    del TRAVA.FONTE_PAGA_TENTATIVAS[antes:]


@pytest.mark.parametrize("url", [
    "https://apipv.pvoperation.com.br/api/v1/plants?token=segredo",      # API PV
    "https://apiplataforma.pvoperation.com/v2/usinas/trackers",          # PV Plataforma (reserva)
    "https://gridco-api.sunop.net/data/v2/analog_values",                # SunOp
])
def test_requests_e_urllib_sao_recusados_e_anotados_sem_a_query(url, tentativas):
    with pytest.raises(requests.exceptions.ConnectionError) as e:
        requests.get(url, timeout=1)
    assert isinstance(e.value, ConnectionError), "quem trata o ConnectionError do Python também pega"
    with pytest.raises(urllib.error.URLError) as e2:
        urllib.request.urlopen(url, timeout=1)
    assert isinstance(e2.value, ConnectionError)
    feitas = TRAVA.FONTE_PAGA_TENTATIVAS[tentativas:]
    assert [t["metodo"] for t in feitas] == ["GET", "GET"]
    assert all("test_requests_e_urllib_sao_recusados" in t["teste"] for t in feitas), "anota QUEM tentou"
    assert all("?" not in t["url"] and "segredo" not in t["url"] for t in feitas), "a query pode levar chave"


def test_a_sessao_da_plataforma_passa_pela_trava(tentativas):
    """O `_http()` da plataforma monta o disjuntor da API PV (`_PvDisjuntor`), que chama o adaptador por `super()`."""
    import app
    with pytest.raises(requests.exceptions.ConnectionError):
        app._http().post(f"{app.BASE_URL}/day_inverter", json={"id": 1}, timeout=1)
    assert [t["url"] for t in TRAVA.FONTE_PAGA_TENTATIVAS[tentativas:]] == [f"{app.BASE_URL}/day_inverter"]
    app._pv_disj.update(falhas=0, ate=0.0, desde=0.0)


def test_host_que_nao_e_fonte_paga_segue(monkeypatch, tentativas):
    """Só o HOST decide: o nome da fonte num parâmetro não é pedido a ela."""
    seguiu = []

    def _real(self, request, *a, **kw):
        seguiu.append(request.url)
        r = requests.Response()
        r.status_code, r._content, r.request = 200, b"{}", request
        return r
    monkeypatch.setattr(TRAVA, "_send_real", _real)
    url = "https://exemplo.invalid/x?volta=apipv.pvoperation.com.br"
    assert requests.get(url, timeout=1).status_code == 200
    assert seguiu == [url] and TRAVA.FONTE_PAGA_TENTATIVAS[tentativas:] == []


@pytest.mark.rede_cortada_pelo_teste
def test_a_marca_com_a_rede_real_continua_recusando(tentativas):
    """A marca só abre o caminho até a resolução do nome se ela estiver TROCADA pelo teste (rede cortada)."""
    assert socket.getaddrinfo is TRAVA._GETADDRINFO_REAL
    with pytest.raises(TRAVA.FontePagaNoTeste):
        requests.get("https://gridco-api.sunop.net/api/check_token", timeout=1)


@pytest.mark.rede_cortada_pelo_teste
def test_a_marca_com_a_rede_cortada_deixa_chegar_a_resolucao(monkeypatch, tentativas):
    """É o que o tests/test_nexus_sem_api_pv.py precisa para contar: o pedido morre no getaddrinfo dele, não na trava."""
    resolvidos = []

    def _cortada(host, *a, **k):
        resolvidos.append(host)
        raise socket.gaierror("rede cortada no teste")
    monkeypatch.setattr(socket, "getaddrinfo", _cortada)
    with pytest.raises(requests.exceptions.ConnectionError) as e:
        requests.get("https://apipv.pvoperation.com.br/api/v1/plants", timeout=1)
    assert not isinstance(e.value, TRAVA.FontePagaNoTeste)
    assert resolvidos == ["apipv.pvoperation.com.br"]
