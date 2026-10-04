# -*- coding: utf-8 -*-
"""A chave de leitura do Nexus (04/10/2026): o Nexus mostra a Entrada e o Monitoramento da plataforma por uma ponte, só
leitura. Esta lista diz o que a chave alcança; todo o resto, com ela, é 403."""
import pathlib
import re

import pytest

import app
import leitura_nexus as ln


def test_paginas_do_tempo_real_passam():
    for c in ("/tempo-real", "/tempo-real/athon", "/monitor"):
        assert ln.permitido("GET", c), c
    assert not ln.permitido("GET", "/")              # a Entrada nível 1 leva a Painel, OS, Gerencial: fora deste passo
    assert not ln.permitido("GET", "/painel")


def test_estaticos_passam():
    # já são públicos sem a chave; a ponte manda a chave em todo pedido, inclusive o notif.js e os estilos
    assert ln.permitido("GET", "/static/notif.js")
    assert ln.permitido("HEAD", "/static/logos/grid.png")
    assert not ln.permitido("POST", "/static/notif.js")
    assert not ln.permitido("GET", "/staticx/notif.js")       # prefixo sem barra não vaza para rota vizinha


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


# ── o portão (`_auth_gate`) aceita a chave ────────────────────────────────────────────────────────────────────────
CHAVE = "chave-de-teste-nexus"


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "senha-qualquer")
    monkeypatch.setattr(app, "NEXUS_LEITURA_TOKEN", CHAVE)
    return app.app.test_client()


def test_chave_certa_le(cli):
    r = cli.get("/api/state", headers={"X-Nexus-Leitura": CHAVE})
    assert r.status_code == 200


def test_chave_certa_le_os_estaticos(cli):
    r = cli.get("/static/notif.js", headers={"X-Nexus-Leitura": CHAVE})
    assert r.status_code == 200


def test_chave_certa_nao_grava(cli):
    r = cli.post("/api/state/tracking", json={"key": "pv:1", "value": 3}, headers={"X-Nexus-Leitura": CHAVE})
    assert r.status_code == 403 and r.get_json()["error"] == "somente leitura (Nexus)"


def test_chave_certa_nao_sai_da_lista(cli):
    assert cli.get("/api/tokens", headers={"X-Nexus-Leitura": CHAVE}).status_code == 403


def test_chave_certa_com_parametro_que_dispara_trabalho_e_403(cli):
    # `?force=1` faz o GET virar rebuild/coleta: a lista fechada recusa mesmo com a chave certa
    r = cli.get("/api/state?force=1", headers={"X-Nexus-Leitura": CHAVE})
    assert r.status_code == 403


def test_chave_errada_e_recusada(cli):
    r = cli.get("/api/state", headers={"X-Nexus-Leitura": "outra"})
    assert r.status_code == 401 and "chave" in r.get_json()["error"]


def test_sem_cabecalho_com_a_chave_configurada_segue_o_fluxo_de_sempre(cli):
    # a chave configurada não abre a plataforma para quem não a manda: sem sessão e sem cabeçalho, 401 como hoje
    assert cli.get("/api/state").status_code == 401


def test_chave_errada_nao_volta_no_corpo_da_resposta(cli):
    # o 401 não pode devolver o valor recebido: seria um canal para ler a chave de volta ou refletir texto de quem pede
    enviado = "valor-enviado-errado-123"
    r = cli.get("/api/state", headers={"X-Nexus-Leitura": enviado})
    assert r.status_code == 401
    assert enviado not in r.get_data(as_text=True) and CHAVE not in r.get_data(as_text=True)
    assert enviado not in str(r.headers)


# `X-Nexus-Leitura-Ok: 1` é como a plataforma diz ao Nexus "esta resposta passou pela chave de leitura". Sem ele a
# ponte do Nexus se recusa a mostrar (uma plataforma aberta, sem NEXUS_LEITURA_TOKEN, ignoraria a chave e deixaria passar
# tudo). Por isso só pode existir quando o portão ACEITOU a chave.
OK = "X-Nexus-Leitura-Ok"


def test_resposta_permitida_pela_chave_confirma_a_chave(cli):
    r = cli.get("/api/state", headers={"X-Nexus-Leitura": CHAVE})
    assert r.status_code == 200 and r.headers.get(OK) == "1"


def test_resposta_de_pagina_estatica_tambem_confirma(cli):
    assert cli.get("/static/notif.js", headers={"X-Nexus-Leitura": CHAVE}).headers.get(OK) == "1"


def test_sem_a_chave_a_confirmacao_nao_aparece(cli, monkeypatch):
    assert OK not in cli.get("/api/state").headers                       # 401 sem sessão
    monkeypatch.setattr(app, "DASH_PASSWORD", "")                        # plataforma aberta, sem cabeçalho nenhum
    r = cli.get("/api/state")
    assert r.status_code == 200 and OK not in r.headers


def test_recusa_da_chave_nao_confirma(cli):
    r403 = cli.post("/api/state/tracking", json={"key": "pv:1", "value": 3}, headers={"X-Nexus-Leitura": CHAVE})
    assert r403.status_code == 403 and OK not in r403.headers            # gravação com a chave certa
    r403b = cli.get("/api/state?force=1", headers={"X-Nexus-Leitura": CHAVE})
    assert r403b.status_code == 403 and OK not in r403b.headers          # parâmetro que dispara trabalho
    r401 = cli.get("/api/state", headers={"X-Nexus-Leitura": "outra"})
    assert r401.status_code == 401 and OK not in r401.headers            # chave errada


def test_chave_nao_configurada_nunca_confirma(cli, monkeypatch):
    # cabeçalho presente mas chave desligada na plataforma: o portão ignora a chave, e a confirmação não pode vir
    monkeypatch.setattr(app, "NEXUS_LEITURA_TOKEN", "")
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    r = cli.get("/api/state", headers={"X-Nexus-Leitura": "qualquer"})
    assert r.status_code == 200 and OK not in r.headers


def test_sem_chave_configurada_o_cabecalho_nao_abre_nada(cli, monkeypatch):
    monkeypatch.setattr(app, "NEXUS_LEITURA_TOKEN", "")
    assert cli.get("/api/state", headers={"X-Nexus-Leitura": ""}).status_code == 401   # sem sessão: como hoje


def test_plataforma_aberta_tambem_recusa_gravacao_pela_chave(cli, monkeypatch):
    # DASH_PASSWORD vazia = plataforma aberta (uso local); mesmo assim, quem chega pela chave do Nexus só lê
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    r = cli.post("/api/state/tracking", json={}, headers={"X-Nexus-Leitura": CHAVE})
    assert r.status_code == 403


# ── a lista cobre as rotas que as páginas chamam ──────────────────────────────────────────────────────────────────
RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
PAGINAS = [RAIZ / "docs" / "redesign" / "Entrada.html", RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html",
           RAIZ / "plataforma" / "static" / "notif.js"]


def test_a_lista_cobre_as_rotas_das_paginas():
    """Rota nova numa página do tempo real precisa ser classificada aqui: leitura (entra na lista), consulta por POST
    ou gravação. Sem isso, a aba do Nexus quebra calada."""
    soltas = set()
    for p in PAGINAS:
        # o lookbehind descarta `/os/api/...` (proxy do OS Creator, que a chave já recusa e não é rota desta plataforma)
        for rota in re.findall(r"(?<![\w])/api/[A-Za-z0-9_\-/]+", p.read_text(encoding="utf-8")):
            rota = rota.rstrip("/")
            if rota == "/api":
                continue                                     # '/api/'+f+... : coberto pelas FONTES_API
            if ln.permitido("GET", rota) or ln.permitido("POST", rota):
                continue
            if any(rota == g.rstrip("/") or rota.startswith(g) for g in ln.GRAVACOES):
                continue
            soltas.add(rota)
    assert not soltas, f"rotas das páginas fora da lista do Nexus: {sorted(soltas)}"
