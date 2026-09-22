# -*- coding: utf-8 -*-
"""Strings do tempo real sem depender do caminho /monitoramento (Levi, 22/09/2026).

O sintoma: no servidor, em qualquer fonte (Thopen, Athon, 2C), o tempo real não carregava as
strings. O iframe `monitoramento?fonte=thopen-pv&embed=1&view=strings` voltava **502 em 26 ms, com
corpo vazio** — rápido e pequeno demais para ser fonte de dado lenta.

A causa não está no código. Medido de fora, sem login:

  /monitoramento…     502  `Server: Caddy`, SEM `Via`        ← o próprio Caddy respondeu
  /tempo-real          302  `Server: waitress`, `Via: 1.1 Caddy` ← a plataforma, repassada

Sem login a plataforma responde 302 para o login em qualquer página — então o 502 prova que o
pedido nunca chegou nela. E o formato do caminho entrega a regra: `/monitoramento`,
`/monitoramento/` e `/monitoramento/x` caem; `/monitoramentoX` passa; `/Monitoramento` cai também
(o casamento de caminho do Caddy ignora maiúscula). O Caddyfile do servidor — que hospeda vários
apps no mesmo domínio, cada um num caminho — tem uma rota própria para `/monitoramento` apontando
para um serviço que não está de pé, e ela sequestra a tela da plataforma.

O conserto de verdade é no Caddy (tirar ou renomear essa rota). Enquanto isso, a plataforma para de
depender do caminho: a mesma tela responde em `/monitor`, e todo link interno aponta para lá ou
direto para `/tempo-real`. `/monitoramento` segue funcionando — na máquina local e no dia em que o
Caddy for corrigido, links antigos e favoritos voltam sozinhos.
"""
import pathlib
import re

import pytest

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "", raising=False)
    app.app.config["TESTING"] = True
    with app.app.test_client() as c:
        yield c


def test_monitor_serve_a_MESMA_tela(cliente):
    a = cliente.get("/monitor?fonte=thopen-pv&embed=1&view=strings")
    b = cliente.get("/monitoramento?fonte=thopen-pv&embed=1&view=strings")
    assert a.status_code == 200 and b.status_code == 200
    assert a.data == b.data, "o alias tem de ser a mesma tela, não uma cópia que envelhece"


def test_monitor_sem_parametro_segue_a_mesma_regra(cliente):
    """Sem `fonte` nem `embed` a tela pelada passava por visão antiga (21/09) — redireciona."""
    r = cliente.get("/monitor")
    assert r.status_code in (301, 302) and r.headers["Location"].endswith("/tempo-real")


def test_monitoramento_CONTINUA_funcionando(cliente):
    """Favoritos, mensagens antigas e a máquina local usam o caminho antigo."""
    assert cliente.get("/monitoramento?fonte=thopen-pv&embed=1").status_code == 200


def _arquivos_com_link():
    base = [RAIZ / "docs" / "redesign" / "Entrada.html", RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html"]
    base += sorted((RAIZ / "plataforma" / "templates").glob("*.html"))
    base += sorted((RAIZ / "plataforma" / "static").glob("*.js"))
    return [p for p in base if p.exists()]


def test_nenhum_link_interno_aponta_para_o_caminho_sequestrado():
    """O coração do conserto. Um único `href="/monitoramento"` esquecido é uma tela que no servidor
    abre em 502 — e em 502 sem corpo, que não diz nada a quem clicou."""
    achados = []
    for p in _arquivos_com_link():
        for n, linha in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"""["'`]/monitoramento\b""", linha):
                achados.append(f"{p.name}:{n}: {linha.strip()[:90]}")
    assert not achados, "links que ainda dependem de /monitoramento:\n" + "\n".join(achados)


def test_o_iframe_das_strings_usa_o_caminho_novo():
    s = (RAIZ / "docs" / "redesign" / "Entrada.html").read_text(encoding="utf-8")
    assert s.count('"/monitor?fonte="') >= 2, "o iframe do tempo real não usa /monitor"
