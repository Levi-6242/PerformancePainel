# -*- coding: utf-8 -*-
"""Sala de controle da Performance (16/11/2026).

O desenho foi aprovado pelo Levi num mockup com dado real (docs/mockups/sala-de-controle) e as regras estão em
docs/sala-de-controle.md. Entrega 1: a tela lê pelas rotas que a plataforma já tinha. Entrega 2: as ações gravam pelas
rotas do Tempo real (trancar com confirmação, acompanhamento, comentários) e a OS nasce na tela do OS Creator. O que
ainda não chegou não aparece (botão ou número de mentira seria pior do que a falta).
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


def test_quem_grava_e_quem_a_plataforma_diz_e_o_gestor_so_le():
    """Entrega 2 (16/11/2026). Levi: "só pessoas da performance podem trancar e destrancar!". A tela usa o `gcEu.grava`
    das outras telas (o perfil de gestor e a chave de leitura só leem); o portão do servidor recusa o POST de qualquer jeito."""
    html = _html()
    assert "const EU = window.gcEu || {}, PODE = !!EU.grava, ACOES = PODE;" in html
    assert 'document.documentElement.classList.toggle("soleitura", !PODE);' in html
    regra = html[html.index("/* quem só lê"):]
    regra = regra[:regra.index("}")]
    for sel in (".soleitura .selinv", ".soleitura div.acao", ".soleitura #novoComent"):
        assert sel in regra, sel
    assert 'if (!PODE) { toast("Só a Performance tranca e destranca strings' in html
    assert "window.gcEu" in html                                             # a plataforma põe em toda página


def test_trancar_pede_confirmacao_e_grava_pela_rota_de_sempre():
    """Levi: "é importante que confirma antes de salvar para não ter perigo de alguém clicar sem querer". O clique na
    string só abre a pergunta; quem grava é o botão dela, na rota que o Tempo real já usa."""
    html = _html()
    clique = html[html.index('if ((x = q(".st[data-st]")))'):]
    clique = clique[:clique.index('if ((x = q(".dchip")))')]
    assert 'role="alertdialog"' in clique and "/api/state/string-trancada" not in clique      # só pergunta
    assert "/api/strings/trava-aviso?usina=" in clique                         # a OS ou o ticket aberto que cita a string
    botao = html[html.index('if ((x = q("[data-tranca]")))'):]
    botao = botao[:botao.index('if ((x = q("[data-delc]")))')]
    assert 'grava("/api/state/string-trancada", {plant_id: String(u.pid), inv_id: String(iv.id), strings: [sid], trancada: !era' in botao
    assert "lerUsina(u, true)" in botao                                        # relê a usina depois de gravar


def test_quem_trancou_fica_no_log(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "_TRANCA_LOG", str(tmp_path / "logs" / "strings_trancadas.log"))
    with app.app.test_request_context("/api/state/string-trancada", method="POST"):
        app._tranca_log("33", "195", ["6", "8"], True, {"usina": "Usina  de Teste", "inversor": "Inversor 2.13",
                                                       "origem": "sala-de-controle"})
        app._tranca_log("33", "195", ["6"], False, {})
    linhas = (tmp_path / "logs" / "strings_trancadas.log").read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 2
    assert "trancou  33|195|6,8  Usina de Teste · Inversor 2.13 · sala-de-controle" in linhas[0]
    assert "destrancou  33|195|6" in linhas[1]


def test_acompanhamento_e_comentario_gravam_nas_rotas_do_tempo_real():
    html = _html()
    assert 'grava("/api/state/tracking", {key: VKEY[u.g] + ":" + u.pid, value: v || null})' in html
    assert 'id="acomp" type="text" inputmode="numeric"' in html
    assert "x.sn = Math.max(0, x.sf - v)" in html              # sem acompanhamento = fora - acompanhadas, como a Entrada
    assert 'grava("/api/state/comment/add", {key: VKEY[u.g] + ":" + u.pid, nick, texto, usina: u.u})' in html
    assert 'grava("/api/state/comment/del", {key: VKEY[u.g] + ":" + u.pid, ts: x.dataset.delc})' in html
    assert 'localStorage.getItem("gcAnalistaNick")' in html    # o mesmo nome guardado do Tempo real, para quem entra pela senha


def test_criar_os_consulta_so_no_clique_e_cria_uma_os_no_os_creator():
    """Levi: "1 OS só para todos [...] E a data do evento foi quando aconteceu"; o aviso da OS de recomposição dos
    últimos 60 dias. A consulta ao Fracttal é só no clique de Criar OS e só dos inversores marcados (em 16/11/2026, 22
    seguidas bateram o teto de 200 por minuto da empresa); a criação é a da tela do OS Creator, aberta por cima."""
    html = _html()
    assert "JANELA = 60" in html
    consulta = html[html.index("async function consultarOS(u, nomes)"):]
    consulta = consulta[:consulta.index("async function abrirCriarOS()")]
    assert "/api/painel/falhas/os?tipo=strings&usina=" in consulta and "if (D.osHist[k]) continue;" in consulta
    assert "if (parou) return;" in consulta                    # o Fracttal fora não é perguntado de novo
    assert html.count("consultarOS(") == 2                     # a definição e a chamada do clique: mais ninguém consulta
    assert 'else if (a === "criar") { if (PODE) abrirCriarOS(); return; }' in html
    janela = html[html.index("function janelaOS()"):]
    janela = janela[:janela.index("function fecharJanela()")]
    assert 'p.append("ativo", i.n); p.append("obs"' in janela  # todos os marcados no MESMO link = uma OS só
    assert 'p.set("obs_os"' in janela and 'p.set("evento"' in janela and 'p.set("comentario", VKEY[u.g] + ":" + u.pid)' in janela
    assert 'OS_CRIAR = "/os/performance/criar"' in html and 'd.gc !== "os-criada"' in html
    assert "ev.origin !== location.origin" in html             # só a ponte do Nexus, na mesma origem, fecha a janela
    assert not re.search(r'method:\s*"(PUT|DELETE)"', html)
    assert "/os/api/performance/criar" not in html             # a tela não cria OS sozinha


def test_nada_de_mockup_a_vista():
    html = _html()
    assert "no mockup não grava" not in html and "(mockup)" not in html
    assert 'data-perfil="' not in html                         # o "Vendo como" era só do mockup


def test_o_que_e_da_entrega_3_fica_escondido():
    html = _html()
    regra = html[html.index("/* O que é da entrega 3"):]
    regra = regra[:regra.index("}")]
    for sel in ("#sino", '[data-aba="bx"]', '[data-aba="gp"]', '[data-aba="pot"]', '[data-aba="cf"]',
                '[data-aba="dp"]', '[data-vg="ger"]', '[data-kpi="bx"]'):
        assert sel in regra, sel
    assert "display:none !important" in regra
    # o cartão dos números (classe "acao" da cor) NÃO pode cair numa regra que esconde a barra de Criar OS
    assert ",.acao," not in html[html.index("/* quem só lê"):html.index("/* quem só lê") + 400]


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
