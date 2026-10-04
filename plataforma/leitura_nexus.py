# -*- coding: utf-8 -*-
"""O que a chave de leitura do Nexus alcança (04/10/2026).

O Nexus mostra a Entrada e o Monitoramento desta plataforma por uma ponte, só leitura (Levi: "tudo da plataforma, só
leitura", "em paralelo por enquanto"). A ponte manda `X-Nexus-Leitura: <NEXUS_LEITURA_TOKEN>`; com ela, o `_auth_gate`
deixa passar só o que `permitido` aceita e devolve 403 para o resto. A lista é FECHADA de propósito: a chave não
alcança `/api/tokens`, a ronda, a coleta nem nada que dispare trabalho pesado. O teste
`test_a_lista_cobre_as_rotas_das_paginas` confere esta lista contra as rotas citadas nas duas páginas: rota nova numa
página quebra o teste, em vez de a aba do Nexus ficar em branco calada.
"""

# as fontes do Monitoramento (o `/api/'+f+'/...` dinâmico das páginas)
FONTES_API = ("pv", "pg", "sunop", "axis", "solaredge", "owen", "2capi", "semp", "alveslima")

# páginas: o nível 2 e 3 da Entrada e o Monitoramento embutido
_PAGINAS = ("/tempo-real", "/monitor")

# leituras que as páginas fazem (GET/HEAD); "x" casa "x" e "x/..."
_GET = tuple(f"/api/{f}" for f in FONTES_API) + (
    "/api/state", "/api/entrada/tempo-real", "/api/notificacoes", "/api/data", "/api/plant", "/api/spv", "/api/etm",
    "/api/perdas", "/api/trackers", "/api/strings", "/api/fracttal/ultima-os", "/api/os-abertas", "/api/os-performance",
)

# POSTs que só consultam (corpo com a lista de usinas): contagem de OS, de-para do Fracttal, OS da ETM
POSTS_DE_CONSULTA = frozenset({"/api/os-performance/counts", "/api/os-creator/fractall-usinas", "/api/etm/os"})

# o que as páginas gravam (documentação e teste): com a chave, tudo isto é 403
GRAVACOES = (
    "/api/state/string-trancada", "/api/state/comment/add", "/api/state/comment/del", "/api/state/os-atribuir",
    "/api/state/os-desatribuir", "/api/state/usina-desligada", "/api/state/usina-religada", "/api/state/tracking",
    "/api/strings/tickets/", "/api/entrada/tempo-real/atualizar", "/api/notificacoes/ler-agora",
)

# parâmetros de query que disparam trabalho pesado (rebuild/coleta/backfill): a ponte do Nexus os remove,
# e a chave recusa como segunda camada de defesa — com eles, mesmo GET passa a ser operação cara
PARAMETROS_QUE_DISPARAM = frozenset({"force", "forcar", "run", "backfill"})

# rotas que são sempre negadas, mesmo sem parâmetros perigosos (ex: o fechamento de perdas dispara trabalho
# indetectável por parâmetro, então veta a rota inteira)
_NEGADOS = ("/api/perdas/fechamento",)


def _casa(caminho: str, base: str) -> bool:
    return caminho == base or caminho.startswith(base + "/")


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

    if m == "POST":
        return c in POSTS_DE_CONSULTA
    if m not in ("GET", "HEAD"):
        return False
    return any(_casa(c, b) for b in _PAGINAS + _GET)
