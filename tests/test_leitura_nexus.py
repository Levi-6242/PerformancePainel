# -*- coding: utf-8 -*-
"""A chave de leitura do Nexus (04/10/2026): o Nexus mostra a Entrada e o Monitoramento da plataforma por uma ponte, só
leitura. Esta lista diz o que a chave alcança; todo o resto, com ela, é 403."""
import leitura_nexus as ln


def test_paginas_do_tempo_real_passam():
    for c in ("/tempo-real", "/tempo-real/athon", "/monitor"):
        assert ln.permitido("GET", c), c
    assert not ln.permitido("GET", "/")              # a Entrada nível 1 leva a Painel, OS, Gerencial: fora deste passo
    assert not ln.permitido("GET", "/painel")


def test_leitura_das_fontes_passa():
    for f in ln.FONTES_API:
        assert ln.permitido("GET", f"/api/{f}/trackers/parados"), f
    for c in ("/api/state", "/api/entrada/tempo-real", "/api/spv/usina/123", "/api/etm/chart", "/api/notificacoes",
              "/api/strings/tickets/12/os", "/api/plant/MAB100", "/api/os-performance", "/api/data"):
        assert ln.permitido("GET", c), c
    assert ln.permitido("HEAD", "/api/state")


def test_so_os_tres_posts_de_consulta_passam():
    for c in ("/api/os-performance/counts", "/api/os-creator/fractall-usinas", "/api/etm/os"):
        assert ln.permitido("POST", c), c
    for c in ln.GRAVACOES:
        assert not ln.permitido("POST", c.rstrip("/") + ("/1/salvar" if c.endswith("/") else "")), c


def test_o_que_nao_e_do_tempo_real_fica_fora():
    for c in ("/api/tokens", "/api/ronda/whats/preview", "/api/tracker-watch/update", "/login", "/api/macro"):
        assert not ln.permitido("GET", c), c
    assert not ln.permitido("DELETE", "/api/state")
    assert not ln.permitido("PUT", "/api/state")
    assert not ln.permitido("GET", "/api/datax")      # prefixo sem barra não vaza para rota vizinha


def test_fechamento_de_perdas_e_negado():
    # rota inteira é negada, independentemente de parâmetros (dispara trabalho indetectável)
    assert not ln.permitido("GET", "/api/perdas/fechamento")
    assert not ln.permitido("GET", "/api/perdas/fechamento", ["run", "dia"])


def test_parametros_perigosos_negam():
    # todos os parâmetros perigosos negam, em qualquer método
    for param in ["force", "forcar", "run", "backfill"]:
        assert not ln.permitido("GET", "/api/pv/trackers/parados", [param]), f"GET com {param}"
        assert not ln.permitido("POST", "/api/etm/os", [param]), f"POST com {param}"

    # parâmetro seguro passa (se a rota é permitida)
    assert ln.permitido("GET", "/api/pv/trackers/parados", ["data"])
    assert ln.permitido("POST", "/api/etm/os", ["usinas"])
