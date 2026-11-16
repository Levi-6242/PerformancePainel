# -*- coding: utf-8 -*-
"""Sala de controle da Performance, entrega 1 (16/11/2026): a tela de LEITURA.

O desenho foi aprovado pelo Levi num mockup com dado real (docs/mockups/sala-de-controle) e as regras estão em
docs/sala-de-controle.md. Nesta entrega a tela só lê, pelas rotas que a plataforma já tinha: nada de rota de dado nova,
nada que grave, e o que é das entregas 2 e 3 não aparece (botão ou número de mentira seria pior do que a falta).
"""
import re

import app

HTML = None


def _html():
    global HTML
    if HTML is None:
        app.app.config["TESTING"] = True
        with app.app.test_client() as c:
            r = c.get("/painel/sala-de-controle")
            assert r.status_code == 200
            HTML = r.get_data(as_text=True)
    return HTML


def test_a_tela_abre_debaixo_do_painel_sem_o_raw_do_jinja():
    html = _html()
    assert "<title>Sala de controle</title>" in html
    assert "{% raw %}" not in html and "{% endraw %}" not in html


def test_le_pelas_rotas_que_ja_existem():
    html = _html()
    for rota in ("/api/entrada/tempo-real", "/api/painel/falhas?mes=", "/api/state", "/api/os-performance?usina=",
                 "/api/pg/plant/", "/api/pg/trackers", "/api/pg/etm/analise", "/api/pg/curva/", "/chart?ini="):
        assert rota in html, rota
    # as doze fontes do tempo real, com as mesmas chaves do Monitoramento
    for fonte in ("thopen-pv", "thopen-db", "athon", "axis", "renogrid", "2c", "semp", "alveslima", "2capi",
                  "greenyellow", "salenergia", "apolo"):
        assert f'"{fonte}":' in html, fonte


def test_o_dado_nao_vem_embutido_nem_com_a_data_do_mockup():
    html = _html()
    assert "let D = null;" in html and "/*DADOS*/" not in html
    assert 'const HOJE = isoDe(new Date())' in html
    assert "Date.UTC(2026" not in html and '"2026-11-16"' not in html
    assert len(html) < 200_000                     # o mockup, com o dado dentro, passava de 1 MB


def test_nesta_entrega_nada_grava():
    html = _html()
    assert "const ACOES = false;" in html                                    # a string não tranca no clique
    assert not re.search(r'method:\s*"(POST|PUT|DELETE)"', html)
    assert 'id="acomp" type="text" readonly' in html                         # o acompanhamento só mostra o que há


def test_o_que_e_das_proximas_entregas_fica_escondido():
    html = _html()
    regra = html[html.index("/* ENTREGA 1 (só leitura)"):]
    regra = regra[:regra.index("}")]
    for sel in (".perfil", "#sino", ".selinv", "div.acao", "#novoComent", '[data-aba="bx"]', '[data-aba="gp"]',
                '[data-aba="pot"]', '[data-aba="cf"]', '[data-aba="dp"]', '[data-vg="ger"]', '[data-kpi="bx"]'):
        assert sel in regra, sel
    assert "display:none !important" in regra
    # o cartão dos números (classe "acao" da cor) NÃO pode cair na regra que esconde a barra de Criar OS
    assert ",.acao," not in regra


def test_espera_limitada_e_a_falha_dita_na_tela():
    html = _html()
    assert "new AbortController()" in html                 # a fonte que não responde não deixa a tela girando
    assert "Não consegui ler o tempo real." in html and "Não consegui ler esta usina." in html
    assert "Tentar de novo" in html


def test_a_rota_de_estacoes_que_falha_nao_e_pedida_sem_parar():
    """Achado na prova de 16/11: com a rota de ETM de uma fonte fora, a aba ETM da visão geral redesenhava, pedia de novo
    e travava o navegador. A falha fica marcada (3) e só a releitura de 5 min tenta outra vez."""
    html = _html()
    assert "ETMG_LIDO[g] = 3" in html
    assert "if (ETMG_LIDO[g] === 3) delete ETMG_LIDO[g]" in html
    assert "delete ETMG_LIDO[g]; delete ETMS" not in html
