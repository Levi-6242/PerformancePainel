# -*- coding: utf-8 -*-
"""O que a chave de leitura do Nexus alcança (04/10/2026).

O Nexus mostra a Entrada e o Monitoramento desta plataforma por uma ponte, só leitura (Levi: "tudo da plataforma, só
leitura", "em paralelo por enquanto"). A ponte manda `X-Nexus-Leitura: <NEXUS_LEITURA_TOKEN>`; com ela, o `_auth_gate`
deixa passar só o que `permitido` aceita e devolve 403 para o resto. A lista é FECHADA de propósito: a chave não
alcança `/api/tokens`, a ronda, a coleta nem nada que dispare trabalho pesado. O teste
`test_a_lista_cobre_as_rotas_das_paginas` confere esta lista contra as rotas citadas nas duas páginas: rota nova numa
página quebra o teste, em vez de a aba do Nexus ficar em branco calada.
"""
import re
import threading

# as fontes do Monitoramento (o `/api/'+f+'/...` dinâmico das páginas)
FONTES_API = ("pv", "pg", "sunop", "axis", "solaredge", "owen", "2capi", "semp", "alveslima", "greenyellow", "salenergia")

# páginas: o nível 2 e 3 da Entrada e o Monitoramento embutido; "/static" (notif.js, fontes, logos) já é público sem
# a chave, e a ponte manda a chave em todo pedido — sem isto as páginas chegariam ao Nexus sem script nem estilo
_PAGINAS = ("/tempo-real", "/monitor", "/static")

# leituras que as páginas fazem (GET/HEAD); "x" casa "x" e "x/..."
_GET = tuple(f"/api/{f}" for f in FONTES_API) + (
    "/api/state", "/api/entrada/tempo-real", "/api/notificacoes", "/api/data", "/api/plant", "/api/spv", "/api/etm",
    "/api/perdas", "/api/trackers", "/api/strings", "/api/fracttal/ultima-os", "/api/os-abertas", "/api/os-performance",
)

# POSTs que só consultam (corpo com a lista de usinas): contagem de OS, de-para do Fracttal, OS da ETM
# ESPELHADA no Nexus (`nexus/performance/ponte.py`): mudou aqui, muda lá; divergência falha fechada (403 da plataforma).
POSTS_DE_CONSULTA = frozenset({"/api/os-performance/counts", "/api/os-creator/fractall-usinas", "/api/etm/os"})

# o que as páginas gravam (documentação e teste): com a chave, tudo isto é 403
GRAVACOES = (
    "/api/state/string-trancada", "/api/state/comment/add", "/api/state/comment/del", "/api/state/os-atribuir",
    "/api/state/os-desatribuir", "/api/state/usina-desligada", "/api/state/usina-religada", "/api/state/tracking",
    "/api/strings/tickets/", "/api/entrada/tempo-real/atualizar", "/api/notificacoes/ler-agora",
)

# parâmetros de query que disparam trabalho pesado (rebuild/coleta/backfill): a ponte do Nexus os remove,
# e a chave recusa como segunda camada de defesa — com eles, mesmo GET passa a ser operação cara
# ESPELHADA no Nexus (`nexus/performance/ponte.py`): mudou aqui, muda lá; divergência falha fechada (403 da plataforma).
PARAMETROS_QUE_DISPARAM = frozenset({"force", "forcar", "run", "backfill"})

# rotas que são sempre negadas, mesmo sem parâmetros perigosos (ex: o fechamento de perdas dispara trabalho
# indetectável por parâmetro, então veta a rota inteira)
_NEGADOS = ("/api/perdas/fechamento",)

# ── A API PV fica de fora do Nexus (Levi, 05/10/2026: "por hora não puxa nada da API da thopen, estou tentando
# economizar requests e tenho medo que duplique as chamadas") ─────────────────────────────────────────────────────
# A API PV (`*.pvoperation.com*`) atende a Thopen e também a SEMP, a Alves Lima e a 2C-API. Pelo Nexus vale só o que a
# plataforma já tem guardado. Duas travas:
# 1) estas rotas, que abrem a usina na API PV na hora (medido com a rede cortada em tests/test_nexus_sem_api_pv.py),
#    são negadas pela chave: rodariam, falhariam e poderiam guardar a falha no cache de todo mundo;
# 2) `instalar_trava_api_pv`: o pedido que entrou pela chave não fala com a API PV, nem nas threads e tarefas que ele
#    abrir — é a garantia para o que a lista não previu.
HOSTS_API_PV = ("pvoperation.com",)          # apipv.pvoperation.com.br e apiplataforma.pvoperation.com
_FONTES_API_PV = "pv|2capi|semp|alveslima"
NEGADOS_API_PV = tuple(re.compile(r) for r in (
    r"^/api/plant/",                                        # inversores da usina (_pv_plant_inversores)
    r"^/api/pv/grupo/",
    r"^/api/pv/pr/",                                        # PR de uma usina, coletado na hora
    rf"^/api/({_FONTES_API_PV})/trackers/\d+",              # drill, curva e CSV de trackers de uma usina
    r"^/api/(2capi|semp|alveslima)/trackers$",              # a lista dessas três monta usina por usina na hora
    r"^/api/spv/(usina/|pdf)",                              # strings de uma usina, na hora (a lista /usinas é cache)
    r"^/api/etm/(chart|export)",                            # curva da estação, na hora
    r"^/api/owen/strings/plant/",
))
_marca = threading.local()


def _casa(caminho: str, base: str) -> bool:
    return caminho == base or caminho.startswith(base + "/")


def pedido_do_nexus() -> bool:
    """Este código roda por causa de um pedido que entrou pela chave do Nexus: no próprio pedido ou numa thread ou tarefa
    que ele abriu."""
    if getattr(_marca, "nexus", False):
        return True
    from flask import g, has_request_context
    return has_request_context() and bool(getattr(g, "nexus_leitura_ok", False))


def _marcado(fn):
    def corre(*a, **k):
        antes = getattr(_marca, "nexus", False)
        _marca.nexus = True
        try:
            return fn(*a, **k)
        finally:
            _marca.nexus = antes
    return corre


def instalar_trava_api_pv(excecao) -> None:
    """Pedido do Nexus não fala com a API PV: `requests` recusa o host com `excecao` (a `PVForaDoAr` da plataforma, que
    quem chama já trata como API fora), e a marca do pedido segue para a thread e para a tarefa de pool que ele abrir.
    Sem pedido do Nexus no caminho, tudo segue como antes. Idempotente."""
    import requests
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import thread as _cft

    if getattr(requests.Session.send, "_trava_nexus", False):
        return
    enviar = requests.Session.send

    def send(self, request, **kw):
        if pedido_do_nexus() and any(h in (request.url or "") for h in HOSTS_API_PV):
            raise excecao("pedido do Nexus: a API PV fica de fora (vale só o que a plataforma já tem)", request=request)
        return enviar(self, request, **kw)
    send._trava_nexus = True
    requests.Session.send = send

    iniciar = threading.Thread.start

    def start(self):
        # o operário de um pool é reaproveitado por pedidos de todo mundo: quem leva a marca é a TAREFA (submit)
        if pedido_do_nexus() and getattr(self, "_target", None) is not _cft._worker:
            self.run = _marcado(self.run)
        return iniciar(self)
    threading.Thread.start = start

    submeter = ThreadPoolExecutor.submit

    def submit(self, fn, /, *a, **k):
        return submeter(self, _marcado(fn) if pedido_do_nexus() else fn, *a, **k)
    ThreadPoolExecutor.submit = submit


def permitido(metodo: str, caminho: str, parametros=()) -> bool:
    m = (metodo or "").upper()
    c = (caminho or "").split("?", 1)[0].rstrip("/") or "/"
    p = parametros or ()

    # parâmetros perigosos negam a requisição em qualquer método
    if any(param in PARAMETROS_QUE_DISPARAM for param in p):
        return False

    # rotas totalmente negadas
    if any(_casa(c, neg) for neg in _NEGADOS):
        return False
    if any(r.match(c) for r in NEGADOS_API_PV):
        return False

    if m == "POST":
        return c in POSTS_DE_CONSULTA
    if m not in ("GET", "HEAD"):
        return False
    return any(_casa(c, b) for b in _PAGINAS + _GET)
