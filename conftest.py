# conftest.py — fixtures compartilhadas dos testes (Fase 1: funções puras de app.py).
#
# Fica na RAIZ do projeto de propósito: o pytest insere o diretório de cada
# conftest.py no sys.path, então `import app` funciona sem instalar nada.
#
# GOTCHA (ver memória testes-automatizados-plano): `import app` NÃO é limpo — no
# topo do módulo ele roda load_equipamentos()/load_metas()/load_tickets_trackers(),
# que leem BD_Performance.xlsx. Local funciona (o xlsx está na pasta). Para CI seria
# preciso esconder essas cargas atrás de função ou commitar um xlsx-fixture pequeno.
import os
import socket
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime as _real_datetime
from urllib.parse import urlsplit

import pytest
import requests

# o código da plataforma vive em plataforma/ desde a separação por projeto
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "plataforma"))


# ── Trava das fontes PAGAS (10/10/2026) ──────────────────────────────────────────────────────────────────────────────
# Medido em 10/10 com um plugin que recusava a rede: cada rodada da suíte fazia 9 chamadas REAIS — 7 à API PV (que é
# paga; uma delas o /authenticate com a credencial do .env) e 2 POST à SunOp, cuja cota já estourou (323 mil pedidos em
# setembro, para 100 mil/mês) — e os testes passavam mesmo assim, porque o código engole a falha de rede e cai no
# padrão. Ninguém via. Daqui em diante todo pedido de `requests` ou `urllib` a host da SunOp ou da PV Operation
# (apipv.pvoperation.com.br, apiplataforma.pvoperation.com…) é recusado com ConnectionError ANTES de sair da máquina,
# fica anotado com o teste que tentou, e esse teste QUEBRA no fim — a recusa sozinha não basta, foi justamente o
# código engolindo a falha que escondeu as 9.
#
# Fica no `HTTPAdapter.send` (e no `do_open` do urllib), não no `socket.getaddrinfo`: o adaptador vê a URL inteira,
# então pega também o pedido por proxy e a conexão reaproveitada do pool, que nunca passam pela resolução do nome. É o
# fundo de todo `requests`: a `Session.send` (onde está a trava do pedido do Nexus, leitura_nexus) e o disjuntor da API
# PV (`_PvDisjuntor.send`, via super()) chegam todos aqui. Instalada ANTES do `import app`, vale também para o que a
# importação fizer.
HOSTS_PAGOS = ("sunop.net", "pvoperation.com")
MARCA_REDE_CORTADA = "rede_cortada_pelo_teste"
FONTE_PAGA_TENTATIVAS = []                  # {"teste", "metodo", "url" (sem a query: pode levar chave), "thread"}
_fonte_paga = {"teste": "(importação/coleta, fora de teste)", "liberado": False}
_GETADDRINFO_REAL = socket.getaddrinfo


class FontePagaNoTeste(requests.exceptions.ConnectionError, ConnectionError):
    """Pedido a fonte paga barrado pela trava dos testes. É ConnectionError do `requests` E do Python: quem chama
    trata como trataria a rede fora, que é o que a suíte já simulava sem saber."""


class FontePagaNoTesteUrllib(urllib.error.URLError, ConnectionError):
    """O mesmo para o `urllib`, que só conhece URLError."""


def _host_pago(url) -> str:
    # só o HOST decide: a mesma palavra num parâmetro da query (um ?volta=…pvoperation.com) não é pedido à fonte
    h = (urlsplit(str(url or "")).hostname or "").lower()
    return h if any(p in h for p in HOSTS_PAGOS) else ""


def _liberado() -> bool:
    """tests/test_nexus_sem_api_pv.py CONTA as tentativas de falar com a API PV trocando o `socket.getaddrinfo`; com a
    trava na frente, o pedido morria antes de chegar à contagem, e o teste da trava do Nexus passaria sem provar nada
    (nenhuma tentativa vista = "nenhuma rota fala com a API PV"). O teste com a marca segue até a resolução do nome —
    mas só se a resolução estiver de fato trocada: com a marca e a rede real, recusa do mesmo jeito."""
    return _fonte_paga["liberado"] and socket.getaddrinfo is not _GETADDRINFO_REAL


def _anota(metodo, url):
    p = urlsplit(str(url))
    FONTE_PAGA_TENTATIVAS.append({"teste": _fonte_paga["teste"], "metodo": (metodo or "?").upper(),
                                  "url": f"{p.scheme}://{p.hostname}{p.path}", "thread": threading.current_thread().name})


_send_real = requests.adapters.HTTPAdapter.send


def _send_travado(self, request, *a, **kw):
    host = _host_pago(request.url)
    if host and not _liberado():
        _anota(request.method, request.url)
        raise FontePagaNoTeste(f"trava dos testes: {host} é fonte paga — dubla a chamada no teste", request=request)
    return _send_real(self, request, *a, **kw)


_do_open_real = urllib.request.AbstractHTTPHandler.do_open


def _do_open_travado(self, http_class, req, **kw):
    host = _host_pago(req.full_url)
    if host and not _liberado():
        _anota(req.get_method(), req.full_url)
        raise FontePagaNoTesteUrllib(f"trava dos testes: {host} é fonte paga — dubla a chamada no teste")
    return _do_open_real(self, http_class, req, **kw)


requests.adapters.HTTPAdapter.send = _send_travado
urllib.request.AbstractHTTPHandler.do_open = _do_open_travado


import app  # noqa: E402  (carga pesada única; roda as cargas do BD_Performance local)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", f"{MARCA_REDE_CORTADA}: o teste corta a rede no socket.getaddrinfo para CONTAR as tentativas; a trava "
                   "das fontes pagas deixa o pedido seguir até lá (e só enquanto a resolução estiver trocada)")


@pytest.fixture(autouse=True)
def _fonte_paga_travada(request):
    """Quem tentou falar com a SunOp ou a PV Operation quebra, com a lista do que tentou (ver a trava acima)."""
    antes = len(FONTE_PAGA_TENTATIVAS)
    _fonte_paga.update(teste=request.node.nodeid, liberado=request.node.get_closest_marker(MARCA_REDE_CORTADA) is not None)
    try:
        yield
    finally:
        _fonte_paga.update(teste="(entre testes: thread que sobrou de um teste anterior)", liberado=False)
    tentou = FONTE_PAGA_TENTATIVAS[antes:]
    if tentou:
        # a recusa é ConnectionError e o disjuntor da API PV a conta como falha de rede: seis seguidas o abririam
        # por 2 min e os testes seguintes veriam "API PV fora" sem ter feito nada
        if isinstance(getattr(app, "_pv_disj", None), dict):
            app._pv_disj.update(falhas=0, ate=0.0, desde=0.0)
        pytest.fail("chamou fonte paga (recusada pela trava do conftest.py) — dubla a chamada no teste:\n" + "\n".join(
            f"  {t['metodo']} {t['url']}  (thread {t['thread']})" for t in tentou), pytrace=False)


def pytest_terminal_summary(terminalreporter):
    """A contagem que o Levi pediu (10/10/2026): quantas chamadas a fonte paga a rodada tentou. Tem de ser 0."""
    n = len(FONTE_PAGA_TENTATIVAS)
    terminalreporter.write_line(f"fonte paga (SunOp/PV Operation): {n} chamada(s) tentada(s) e recusada(s)",
                                red=bool(n), green=not n)
    for t in FONTE_PAGA_TENTATIVAS:
        terminalreporter.write_line(f"  {t['teste']}: {t['metodo']} {t['url']} (thread {t['thread']})")


# Arquivos que a plataforma GRAVA (01/10/2026). Às 09:51 de 01/10 o test_os_tres_chamadores_pre_carregam_as_usinas_juntas
# chamou o _sunop_eventos_calc de verdade, e ele salva o acervo: o trk_eventos.json do PC (11,7 MB, 93 dias de
# eventos de tracker de todas as fontes) virou 388 bytes com as duas usinas falsas do teste, até o worker regravar da
# memória 4 min depois — um reinício nessa janela apagava o histórico. Num reinício de 30/09 o worker já tinha
# carregado o arquivo com a AAA100 e a BBB100 do teste. Cada teste grava agora num diretório só dele; a lista é
# conferida contra o app.py (tests/test_isolamento_estado.py), para arquivo novo não ficar de fora.
ARQUIVOS_DE_ESTADO = (
    # _p_dado / _p_cache
    "PV_RELOGIO_PATH", "_TRK_FIM_DIA_PATH", "_TRK_EV_PATH", "STATE_PATH", "SPV_NOTAS_PATH",
    "_PERSIST_PATH", "_FRAC_INDEX_FILE", "_FRAC_OSPERF_FILE", "_FRAC_DISP_FILE", "_FRAC_DISP_STATUS", "_FRAC_MTTA_FILE",
    "_FRAC_MTTA_BASE", "_FALHAS_STR_PATH", "_FALHAS_PV_DEV", "_FALHAS_IMPORTA_PATH", "_FALHAS_TRK_SEMCOM_PATH",
    "_FALHAS_OS_PATH", "_FALHAS_2C_PATH", "FALHAS_BF_ESTADO", "FALHAS_BF_PV_ESTADO", "FALHAS_DESC_PATH", "_WHATS_CFG_PATH",
    "_TRK_GARANTIA_PATH", "_TRK_GARANTIA_LOCAL", "_TRK_DEPARA_LOCAL", "_TRK_HIST_PATH", "_NOTAS_TRK_PATH",
    "_NOTAS_TRK_LOCAL", "_PERDAS_STR_PATH", "_PARADAS_PATH", "_REL_SEM_PATH",
    # gravados direto em plataforma/
    "_TOKENS_RT_PATH", "_ENTRADA_TRK_ULTIMO", "_SUNOP_PLANTS_ARQ", "_TUNNEL_URL_FILE", "_WHATS_SENT_PATH",
    "_WHATS_LOG_PATH",
)


@pytest.fixture(autouse=True)
def _estado_de_runtime_isolado(tmp_path, monkeypatch):
    """Nenhum teste grava estado de runtime DE VERDADE em plataforma/ (22/09/2026; todos os arquivos desde 01/10/2026).

    A montagem do tempo real passou a guardar a última contagem boa de trackers em
    `plataforma/entrada_trk_ultimo.json`, para sobreviver ao restart do deploy. Na primeira rodada, os
    testes da montagem — com fontes SIMULADAS — gravaram zeros falsos no arquivo real, e o teste seguinte,
    que espera "sem leitura anterior", achou o arquivo e reaproveitou a contagem. Além de vazar estado
    entre testes, sujava a plataforma local com dado inventado. Cada teste agora tem os seus arquivos — e o
    contador da SunOp não despeja (o padrão, 25 chamadas, gravava no `logs/sunop_uso_worker.json` do PC, o
    contador que mede a cota); quem testa o despejo liga e aponta o `_AQUI` para o tmp_path."""
    for nome in ARQUIVOS_DE_ESTADO:
        atual = getattr(app, nome, None)
        if isinstance(atual, str):
            monkeypatch.setattr(app, nome, str(tmp_path / os.path.basename(atual)))
    monkeypatch.setattr(app, "_SUNOP_USO_FLUSH", 10 ** 9, raising=False)


@pytest.fixture(autouse=True)
def _sunop_sem_pausa_por_padrao(monkeypatch):
    """A pausa da SunOp (domingo e teto do dia, 04/10/2026) depende do dia e do contador: rodada num domingo, a suíte
    inteira veria a SunOp fechada. Desligada por padrão; tests/test_sunop_teto_domingo.py liga."""
    monkeypatch.setattr(app, "SUNOP_PAUSA_LIGADA", False, raising=False)


@pytest.fixture
def freeze_now(monkeypatch):
    """Congela app.datetime.now() num instante fixo, sem mexer no resto da classe.

    Várias funções puras (curva ETM, acumulador de trackers, janela de sol) leem
    datetime.now(). Como app.py faz `from datetime import datetime`, basta trocar o
    nome `datetime` DO MÓDULO app por uma subclasse que sobrescreve só o now() —
    strptime/strftime continuam reais. Devolve o datetime congelado.
    """
    def _apply(when):
        if isinstance(when, str):
            when = _real_datetime.strptime(when, "%Y-%m-%d %H:%M:%S")

        class _Frozen(_real_datetime):
            @classmethod
            def now(cls, tz=None):
                return when

        monkeypatch.setattr(app, "datetime", _Frozen)
        return when

    return _apply


@pytest.fixture
def set_trancadas(monkeypatch):
    """Define o global app._trancadas (set de chaves "pid|inv|Ipv") só para o teste.

    _classifica_strings lê esse global por nome no momento da chamada, então trocar
    o atributo do módulo basta. O monkeypatch reverte ao fim de cada teste.
    """
    def _apply(keys):
        s = set(keys)
        monkeypatch.setattr(app, "_trancadas", s)
        return s

    return _apply


@pytest.fixture
def trk_accum(monkeypatch):
    """Zera o acumulador de trackers (app._trk_accum) num estado limpo e isolado."""
    state = {"date": "", "plants": {}}
    monkeypatch.setattr(app, "_trk_accum", state)
    return state


@pytest.fixture(autouse=True)
def _fase4_desligada_por_padrao(monkeypatch):
    """A Fase 4 (curva lida do acervo do gêmeo) fala pela REDE com o serviço em 127.0.0.1:5075.

    Sem esta trava, todo teste que passa por `_sunop_analog_history` passaria ou falharia conforme
    o gêmeo estivesse no ar na máquina de quem roda — e na CI ele nunca está. Quem testa a Fase 4
    liga explicitamente (`monkeypatch.setattr(app, "GEMEO_CURVA_ATIVO", True)`) e dubla o
    `_gemeo_curva`; todo o resto da suíte segue offline e determinístico.
    """
    monkeypatch.setattr(app, "GEMEO_CURVA_ATIVO", False, raising=False)


@pytest.fixture(autouse=True)
def _sunop_coleta_completa_por_padrao(monkeypatch):
    """`SUNOP_COLETA` vem do tokens.txt da MÁQUINA (o PC do Levi roda em `ronda` desde 29/09/2026). Sem esta trava, a
    suíte testaria o modo da máquina de quem roda — foi assim que os testes do ciclo noturno e da Entrada quebraram no
    PC. Quem testa o modo ronda liga explicitamente (`monkeypatch.setattr(app, "SUNOP_COLETA", "ronda")`)."""
    monkeypatch.setattr(app, "SUNOP_COLETA", "completa", raising=False)
    if isinstance(getattr(app, "_sunop_trk_cache", None), dict):
        monkeypatch.setitem(app._sunop_trk_cache, "_ttl", app.SUNOP_TTL)
