# -*- coding: utf-8 -*-
"""A rota pública do token da Plataforma só grava com a CHAVE do userscript (10/10/2026).

O caso: a revisão adversarial da "porta única" achou que `POST /api/pv/trackers/token` — aberta no portão porque o
userscript (antes, o bookmarklet) roda na origem da PV Plataforma, sem a sessão daqui — gravava QUALQUER coisa com
cara de JWT. Sem assinatura nem login, qualquer um na internet podia:

  - trocar o token: um JWT forjado com `exp` em 2099 vence o verdadeiro em `_plat_token()` (vence o de validade maior),
    a reserva da curva de strings para e a tela /tokens passa a dizer "ok", escondendo o vencimento real;
  - zerar o cache de trackers a cada pedido, e o próximo `/api/pv/trackers` reconstruía tudo na API PV na hora.

A correção escolhida pelo Levi (opção a): o servidor gera uma chave, mostra em /tokens (atrás do login) e o userscript
a manda no cabeçalho `X-Gridco-Chave`. Sem ela, 401 e nada muda — nem o token, nem o cache.
"""
import base64
import json
import time

import pytest

import app

ROTA = "/api/pv/trackers/token"


def _jwt(exp_epoch: float) -> str:
    """JWT de mentira com `exp` — a rota só lê o payload (não há como conferir a assinatura da PV)."""
    p = base64.urlsafe_b64encode(json.dumps({"sub": "t", "exp": int(exp_epoch)}).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJIUzI1NiJ9.{p}.assinatura"


SENTINELA = {"rows": ["cache montado antes do pedido"]}


@pytest.fixture
def servidor(monkeypatch):
    """Plataforma com senha (o servidor de verdade) e um cache de trackers já montado."""
    monkeypatch.setattr(app, "DASH_PASSWORD", "senha-de-teste")
    monkeypatch.setattr(app, "NEXUS_LEITURA_TOKEN", "", raising=False)
    monkeypatch.setitem(app._pv_trk_cache, "payload", SENTINELA)
    app._tokens_rt_set(app.PLAT_RT_KEY, "token-que-estava-la")
    return app.app.test_client()


def _chave_pelo_tokens(cli) -> str:
    """O caminho do Levi: logado, abre /tokens e copia a chave."""
    with cli.session_transaction() as s:
        s["auth"] = True
    r = cli.get("/api/tokens/plat/chave")
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()["chave"]


def _intocado():
    assert app._tokens_rt_get(app.PLAT_RT_KEY) == "token-que-estava-la", "o token gravado não pode mudar"
    assert app._pv_trk_cache["payload"] is SENTINELA, "o cache de trackers não pode ser zerado"


def test_sem_chave_e_recusado_e_nada_muda(servidor):
    """O ataque do achado: JWT forjado, sem credencial nenhuma."""
    r = servidor.post(ROTA, json={"token": _jwt(time.time() + 80 * 365 * 86400)})
    assert r.status_code == 401
    assert r.get_json()["ok"] is False
    # o userscript lê a resposta de outra origem: sem o cabeçalho de CORS ele não saberia o motivo
    assert r.headers.get("Access-Control-Allow-Origin") == "*"
    _intocado()


def test_chave_errada_e_recusada_e_nada_muda(servidor):
    _chave_pelo_tokens(servidor)                       # a chave existe no servidor
    r = servidor.post(ROTA, json={"token": _jwt(time.time() + 7 * 86400)},
                      headers={"X-Gridco-Chave": "chute"})
    assert r.status_code == 401
    _intocado()


def test_servidor_sem_chave_gerada_recusa_ate_chave_vazia(servidor):
    """Antes de alguém abrir /tokens não há chave; cabeçalho vazio não pode casar com "nada"."""
    assert app._tokens_rt_get(app.PLAT_CHAVE_RT_KEY) == ""
    r = servidor.post(ROTA, json={"token": _jwt(time.time() + 7 * 86400)}, headers={"X-Gridco-Chave": ""})
    assert r.status_code == 401
    _intocado()
    assert app._tokens_rt_get(app.PLAT_CHAVE_RT_KEY) == "", "pedido de fora não pode gerar a chave"


def test_com_a_chave_o_userscript_segue_renovando(servidor):
    """O que não pode quebrar: com a chave, grava na hora e zera o cache, como sempre fez."""
    chave = _chave_pelo_tokens(servidor)
    novo = _jwt(time.time() + 7 * 86400)
    r = servidor.post(ROTA, json={"token": novo}, headers={"X-Gridco-Chave": chave})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["ok"] is True
    assert app._tokens_rt_get(app.PLAT_RT_KEY) == novo
    assert app._pv_trk_cache["payload"] is None


def test_chave_e_estavel_e_so_sai_com_login(servidor):
    """A chave não muda a cada visita a /tokens (o userscript ficaria velho), e sem sessão a rota é fechada."""
    assert servidor.get("/api/tokens/plat/chave").status_code == 401
    c1 = _chave_pelo_tokens(servidor)
    c2 = servidor.get("/api/tokens/plat/chave").get_json()["chave"]
    assert c1 == c2 and len(c1) >= 32


def test_pelo_nexus_a_chave_e_so_de_admin():
    """Quem entra pelo passe do Nexus como gestor só lê; com a chave ele gravaria o token pela rota pública. A rota da
    chave fica no prefixo /api/tokens, que a porta única já reserva ao admin do Nexus — estreitar essa lista quebra aqui."""
    import porta_nexus
    assert porta_nexus.so_admin("/api/tokens/plat/chave")


def test_preflight_libera_o_cabecalho_da_chave(servidor):
    """Bookmarklet na página da PV (fetch de outra origem) precisa do cabeçalho liberado no preflight."""
    r = servidor.open(ROTA, method="OPTIONS")
    assert r.status_code == 204
    assert "x-gridco-chave" in r.headers.get("Access-Control-Allow-Headers", "").lower()


def test_dev_local_sem_senha_segue_aberto(monkeypatch):
    """Sem DASH_PASSWORD o app inteiro é aberto (dev local) — /api/tokens/plat grava sem nada; exigir a chave só
    aqui não protegeria coisa alguma e quebraria o destino localhost do userscript."""
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    monkeypatch.setattr(app, "NEXUS_LEITURA_TOKEN", "", raising=False)
    monkeypatch.setitem(app._pv_trk_cache, "payload", SENTINELA)
    novo = _jwt(time.time() + 7 * 86400)
    r = app.app.test_client().post(ROTA, json={"token": novo})
    assert r.status_code == 200
    assert app._tokens_rt_get(app.PLAT_RT_KEY) == novo
