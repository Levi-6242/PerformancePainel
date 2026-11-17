# -*- coding: utf-8 -*-
"""Sala de controle da Performance (16/11/2026).

O desenho foi aprovado pelo Levi num mockup com dado real (docs/mockups/sala-de-controle) e as regras estão em
docs/sala-de-controle.md. Entrega 1: a tela lê pelas rotas que a plataforma já tinha. Entrega 2: as ações gravam pelas
rotas do Tempo real (trancar com confirmação, acompanhamento, comentários) e a OS nasce na tela do OS Creator. Entrega 3:
o abaixo dos demais (lido do Nexus), Geração e PR, Potência, a inspeção do inversor pelo cálculo oficial da
Disponibilidade, Conferir fontes, o De-para, a idade real das strings e o novo por pessoa, com as rotas /api/sala/*.
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
    assert len(html) < 300_000                     # o mockup, com o dado dentro, passava de 1 MB


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


def test_trancar_escolhe_varias_e_pergunta_uma_vez_so():
    """Levi, 16/11/2026: "é importante que confirma antes de salvar para não ter perigo de alguém clicar sem querer" e,
    depois de usar, "É melhor eu selecionar várias de uma vez e clicar trancar só na última. Que aí tranca tudo de uma
    vez". O clique na string só ESCOLHE; a barra tem Trancar/Destrancar, que perguntam uma vez e gravam um POST por
    inversor, na rota que o Tempo real já usa."""
    html = _html()
    clique = html[html.index('if ((x = q(".st[data-st]")))'):]
    clique = clique[:clique.index('if ((x = q("[data-stacao]")))')]
    assert "SELS.set(k, {inv: sinv, sid, trancada:" in clique and "/api/state/string-trancada" not in clique
    assert 'role="alertdialog"' not in clique                                  # escolher não pergunta nada
    barra = html[html.index('if ((x = q("[data-stacao]")))'):]
    barra = barra[:barra.index('if ((x = q(".dchip")))')]
    assert 'role="alertdialog"' in barra and "/api/strings/trava-aviso?usina=" in barra   # UMA pergunta, com o aviso de OS/ticket
    assert "/api/state/string-trancada" not in barra                           # a barra só pergunta
    botao = html[html.index('if ((x = q("[data-tranca]")))'):]
    botao = botao[:botao.index('if ((x = q("[data-delc]")))')]
    assert 'grava("/api/state/string-trancada", {plant_id: String(u.pid), inv_id: String(iv.id), strings: ss, trancada: !era' in botao
    assert "for (const [n, ss] of Object.entries(por))" in botao               # um POST por inversor, com todas as strings dele
    assert "lerUsina(u, true)" in botao                                        # relê a usina depois de gravar
    assert "SELS.clear();" in html[html.index("const abrirUsina ="):html.index("function desenhar() {")]   # trocar de usina limpa a escolha


def test_as_strings_nao_esperam_os_trackers_nem_a_estacao():
    """Levi, 16/11/2026: "por que as usinas da Thopen em banco de dados demoram tanto para carregar as strings?". Medido:
    a usina responde em 0,1 a 1,5 s; a tela esperava a leitura dos trackers (9 a 30 s). Agora desenha quando a usina
    chega, e cada aba diz "lendo" até a parte dela chegar."""
    html = _html()
    ler = html[html.index("async function lerUsina(u, calada) {"):html.index("const SCL = {};")]
    # desde 17/11 os trackers e a estação saem JUNTO com as strings; o que não muda: a usina desenha (pinta) assim que
    # as strings chegam, antes de esperar o resto
    assert ler.index("D.drill[u.u] = dr;") < ler.index("    pinta();") < ler.index("await Promise.all(extras);")
    assert "pinta();" in ler and '.finally(() => pinta("trk"))' in ler and 'dr.etmLendo = false; pinta("etm");' in ler
    assert "Lendo os trackers desta usina…" in html and "Lendo a estação desta usina…" in html


def test_a_seta_da_fonte_so_abre_e_recolhe():
    """Levi, 16/11/2026: "quando eu vou clicar para recolher o cliente e ver outro, ele sai da tela da usina"."""
    html = _html()
    g = html[html.index('if ((x = q(".g"))) { const id = x.dataset.g;'):]
    g = g[:g.index("if (id) { CLICADAS.add")]
    # 16/11, noite: "Só aparece a visão da fonte caso eu clique no nome da fonte, se eu clicar no quadrado só expande"
    assert 'if (id && !q(".gn")) { if (ABERTOS.has(id)) ABERTOS.delete(id); else ABERTOS.add(id);' in g and "arvore(); return; }" in g
    assert "SEL =" not in g                                                    # o cartão e a seta não mexem no que está aberto
    assert 'if (id) { CLICADAS.add("g|" + id); ABERTOS.add(id); SEL = {g: id, u: null};' in html      # só o nome recorta a tela
    assert '<span class="gn" title="Ver só esta fonte na tela">' in html


def test_o_prontuario_da_usina_abre_no_nexus_pelo_nome():
    html = _html()
    assert 'href="/t/comando/usinas/abrir?nome=${encodeURIComponent(u.u)}"' in html and 'target="_blank" rel="noopener"' in html


def test_o_que_o_scada_tem_aparece_quando_a_fonte_nao_traz():
    """Levi, 16/11/2026: "Não pode ter informação na API que a gente não tem aqui no tempo real". A leitura do SCADA só é
    pedida quando a aba Trackers ou a ETM não têm o dado da fonte (ou a fonte da usina está fora), e a falha fica marcada."""
    html = _html()
    assert 'pega("/api/sala/scada?usina=" + encodeURIComponent(u.u) + "&fonte="' in html
    assert 'scadaBloco(u, "trk")' in html and 'scadaBloco(u, "etm")' in html
    ler = html[html.index("async function lerScada(u) {"):html.index("function scadaBloco(u, qual) {")]
    assert "if (u.u in D.scada || SCL[u.u]) return;" in ler and "D.scada[u.u] = {erro:" in ler      # sem laço de pedidos
    assert 'pega("/api/sala/scada/raiox", 60000)' in html and "Raio-x do SCADA da Grid" in html
    assert "O histórico de hoje dos trackers não respondeu no supervisório" in html              # a usina que só tem o agora


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
    assert '<input class="aci" type="text" inputmode="numeric"' in html      # desde 16/11 (23h30) o campo mora na lateral
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


def test_nada_mais_fica_escondido_nem_de_mentira():
    """Entrega 3 (16/11/2026): o sino, as abas Abaixo dos demais, Geração e PR, Potência, Conferir fontes e De-para e o
    cartão do Novo deixam de ser escondidos, e nenhum botão responde "no mockup"."""
    html = _html()
    assert "display:none !important}" not in html[html.index("/* quem só lê") - 400:html.index("/* quem só lê")]
    assert ".prio .pc:first-child{display:none}" not in html and '<div class="nota">' not in html
    assert "data-mock" not in html and "Neste mockup" not in html and "no mockup" not in html
    for aba in ('aba("bx", "Abaixo dos demais"', 'aba("gp", "Geração e PR")', 'aba("pot", "Potência")',
                'aba("dp", "De-para")'):
        assert aba in html, aba


def test_o_abaixo_dos_demais_vem_do_nexus_e_diz_quando_nao_leu():
    """A conta é do dono (a Baixa performance da Coletas, no Nexus): a tela lê de lá, pela mesma origem, sem refazer."""
    html = _html()
    assert 'fetch("/t/performance/sala-de-controle/abaixo?mes=" + HOJE.slice(0, 7)' in html
    assert "abra a Sala de controle pela Performance do Nexus" in html      # aberta direto pela senha, sem sessão do Nexus
    assert 'data-denovo2="abx"' in html and "lerAbaixo.indo" in html
    assert "if (!ABX || Date.now() - ABX_EM > 18e5) lerAbaixo();" in html    # não a cada 5 min: a conta muda com os BDs


def test_a_idade_real_e_o_novo_por_pessoa_entram_na_montagem():
    html = _html()
    assert 'pega("/api/sala/idade", 60000).catch(() => null), pega("/api/sala/visto", 20000).catch(() => null)' in html
    montar = html[html.index("function montar(ent, fal, idr, vis, arr) {"):html.index("let ABX = null")]
    assert "real[e.usina + \"|\" + e.inversor + \"|\" + e.string]" in montar     # quem vinha parado no dia 1 ganha a data real
    assert 'k: "s|" + e.usina + "|" + e.inversor + "|" + e.string + "|" + r.d0' in montar   # a chave do visto é a parada real
    assert "if (e.aberta && String(e.ini) >= desde && !meu(e.k))" in montar     # novo = parou depois da 1ª vez, segue parado, não vi
    assert "if (r.fim) return;" in montar                                        # tracker que já voltou não é novidade
    assert 'fetch("/api/sala/visto", {method: "POST"' in html                   # ver = gravar, para todos saberem quem viu
    assert "const quemViu = (u, i) =>" in html


def test_o_sino_agrupa_por_usina():
    html = _html()
    sino = html[html.index("function sino() {"):html.index("// ver = marcar como visto por mim")]
    assert "por[x.u] = por[x.u] ||" in sino and 'data-nu="${esc(o.u)}"' in sino
    assert "por usina</h4>" in sino


def test_geracao_potencia_e_disponibilidade_leem_as_rotas_que_ja_existem():
    html = _html()
    assert '"/inversores/historico/" + encodeURIComponent(u.pid) + "?usina="' in html
    assert 'pega("/api/relatorio/potencia-ativa?fonte=" + f + "&usina="' in html
    assert 'pega("/api/gerencial/disponibilidade?mes=" + HOJE.slice(0, 7), 120000)' in html   # o cálculo OFICIAL
    insp = html[html.index("function inspecao(u, n, idx) {"):html.index("function kpis(us, bx) {")]
    assert "pelo cálculo oficial da Disponibilidade por OS" in insp and "(dp.U.inversores || []).find(x => x.inversor === n)" in insp
    assert "if (!G.pr) lerPr(u);" in html                    # o PR de hoje só quando a pessoa pede (na API PV custa)
    # a falha de cada leitura fica marcada e só o clique tenta de novo (nada de pedir sem parar dentro do desenho)
    for marca in ("GERF[u.u]", "POTF[u.u]", "DISP_ERRO", 'D.conf.usinas[u.u] = o'):
        assert marca in html, marca
    assert "if (lerDisp.indo || DISP_ERRO ||" in html


def test_exportar_e_excel_de_verdade_e_o_de_para_e_o_editor_de_sempre():
    html = _html()
    assert 'fetch("/api/sala/exportar", {method: "POST"' in html and ".csv" not in html[html.index("async function exportar(qual)"):html.index("// criar OS pela tela")]
    assert 'cabecalho: ["Data"].concat(ns)' in html and 'nome: "Irradiação"' in html     # datas na 1ª coluna, inversores em colunas
    assert 'src="/admin/de-para?editar=${encodeURIComponent(f + "|" + u.pid)}&janela=1"' in html
    assert 'cp.dataset.dp === u.g + "|" + u.u && cp.querySelector("iframe.dpj")' in html   # a releitura não recarrega o editor
    assert "function redesenhar() { if (digitando())" in html                              # nem atropela quem está digitando


# ── as rotas /api/sala/* ─────────────────────────────────────────────────────────────────────────────────────────
import json  # noqa: E402

import pytest  # noqa: E402

import sala_controle as S  # noqa: E402


@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "_SALA_VISTOS", S.Vistos(str(tmp_path / "sala_visto.json")))
    app.app.config["TESTING"] = True
    with app.app.test_client() as c:
        yield c


def test_rota_do_visto_grava_para_quem_esta_na_sessao(cli):
    r = cli.get("/api/sala/visto").get_json()
    assert r["ok"] and r["eu"]["desde"] and r["vistos"] == {}
    k = "s|Usina A|Inversor 1.2|ST 04|2026-11-16"
    assert cli.post("/api/sala/visto", json={"chaves": [k, "lixo"]}).get_json() == {"ok": True, "marcadas": 1}
    assert cli.get("/api/sala/visto").get_json()["vistos"][k][0]["eu"] is True
    assert cli.post("/api/sala/visto", json={"chaves": "x"}).status_code == 400


def test_rota_do_excel_devolve_xlsx_e_recusa_o_que_esta_fora(cli):
    r = cli.post("/api/sala/exportar", json={"arquivo": "Geração Usina A", "abas": [
        {"nome": "Geração (kWh)", "cabecalho": ["Data", "Inversor 1.1"], "linhas": [["01/11/2026", 611.7]]}]})
    assert r.status_code == 200 and r.data[:2] == b"PK" and "spreadsheetml" in r.mimetype
    assert cli.post("/api/sala/exportar", json={"abas": []}).status_code == 400


def test_rota_da_idade_segue_os_pacotes_publicados_e_guarda_o_resultado(cli, tmp_path, monkeypatch):
    def pac(ini, fim, eps):
        return json.dumps({"periodo": [ini, fim], "strings": {"episodios": eps}}).encode()
    ep = {"usina": "Usina A", "inversor": "Inversor 1.2", "string": "ST 04"}
    pacotes = {"2026-11": pac("2026-11-01", "2026-11-16", [{**ep, "d0": "2026-11-01", "d1": "2026-11-15", "inicio": "2026-11-01 07:10"}]),
               "2026-10": pac("2026-10-01", "2026-10-31", [{**ep, "d0": "2026-10-17", "d1": "2026-10-31", "inicio": "2026-10-17 09:40"}])}
    arqs = {}
    for m in pacotes:
        arqs[m] = tmp_path / (m + ".json")
        arqs[m].write_bytes(pacotes[m])
    lidos = []
    monkeypatch.setattr(app, "_falhas_meses", lambda hoje=None: ["2026-09", "2026-10", "2026-11"])
    monkeypatch.setattr(app, "_falhas_arquivo", lambda m: str(arqs.get(m, tmp_path / "nao-existe.json")))
    monkeypatch.setattr(app, "_falhas_bytes", lambda m: lidos.append(m) or pacotes.get(m))
    monkeypatch.setitem(app._sala_idade_mem, "marca", None)
    d = cli.get("/api/sala/idade").get_json()
    assert d["ok"] and d["meses"] == ["2026-11", "2026-10"] and d["ate"] == "2026-10-01"
    assert d["strings"]["Usina A|Inversor 1.2|ST 04"] == {"d0": "2026-10-17", "inicio": "2026-10-17 09:40", "antes": False}
    n = len(lidos)
    assert cli.get("/api/sala/idade").get_json() == d and len(lidos) == n        # arquivos iguais: não relê os meses


def test_rota_de_conferir_le_o_scada_uma_vez_e_diz_o_que_nao_da(cli, monkeypatch):
    pedidos = []

    class Sg:
        FONTES = {"greenyellow": {}}

        @staticmethod
        def configurado():
            return True

        @staticmethod
        def get(rota):
            pedidos.append(rota)
            if rota == "/api/usinas":
                return {"usina_dupla": {"inv_total": 2}}
            if rota == "/api/mqtt":
                return {"usinas": [{"usina": "usina_dupla", "nome": "Usina Dupla 1 e 2",
                                    "equipamentos": [{"tipo": "inverter", "equipamento": "inv-01"}, {"tipo": "inverter", "equipamento": "inv-02"}]}]}
            return {"equipamentos": [{"tipo": "inverter", "equipamento": "inv-02"}, {"tipo": "inverter", "equipamento": "inv-01"},
                                     {"tipo": "weather", "equipamento": "est"}]}

        @staticmethod
        def leitura_mqtt(e):
            return {"equip": e["equipamento"], "ok": True, "pot_kw": 10.0, "eday": 50.0, "strings": {1: 6.0, 2: 0.0}, "serial": "S"}

    monkeypatch.setattr(app, "_sg", Sg)
    monkeypatch.setitem(app._sala_scada_mem, "lista", None)
    assert cli.get("/api/sala/conferir?usina=Qualquer&fonte=greenyellow").get_json()["situacao"] == "ja_e_scada"
    assert pedidos == []                                             # a usina que já é do SCADA não gasta chamada
    r = cli.get("/api/sala/conferir?usina=Usina Dupla 2&fonte=pg").get_json()
    assert r["situacao"] == "conferir" and r["duas"] and r["cobre"] == ["usina dupla 1", "usina dupla 2"]
    assert [x["eq"] for x in r["leituras"]] == ["inv-01", "inv-02"] and r["leituras"][0]["com_corrente"] == 1
    assert pedidos == ["/api/usinas", "/api/mqtt", "/api/mqtt/usina_dupla"]
    fora = cli.get("/api/sala/conferir?usina=Outra&fonte=pg").get_json()
    assert fora["situacao"] == "fora_do_scada" and fora["scada_nomes"] == ["Usina Dupla 1 e 2"]
    assert pedidos == ["/api/usinas", "/api/mqtt", "/api/mqtt/usina_dupla"]   # a lista vale 10 min; usina fora não chama o SCADA
    assert cli.get("/api/sala/conferir").status_code == 400


def test_o_gestor_le_as_rotas_da_sala_marca_o_visto_e_baixa_o_excel():
    import leitura_nexus as L
    for rota in ("/api/sala/visto", "/api/sala/idade", "/api/sala/conferir"):
        assert L.permitido_gestor("GET", rota), rota
    assert L.permitido_gestor("POST", "/api/sala/visto") and L.permitido_gestor("POST", "/api/sala/exportar")
    assert not L.permitido_gestor("POST", "/api/state/string-trancada")      # gravar dado da Performance segue fora


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


def _sg_de_mentira(pedidos):
    class Sg:
        FONTES = {"greenyellow": {}, "axisscada": {}}
        COM_OK = 192

        @staticmethod
        def configurado():
            return True

        @staticmethod
        def usinas(fonte):
            return [{"id": "usina_x", "usina": "Usina X"}] if fonte == "greenyellow" else []

        @staticmethod
        def usina_cfg(fonte, pid):
            return {"id": "usina_x", "usina": "Usina X"} if (fonte, pid) == ("greenyellow", "usina_x") else None

        @staticmethod
        def scada_id(fonte, pid):
            return "usina_xis"                                   # o nome de lá não é o do cadastro

        @staticmethod
        def get(rota):
            pedidos.append(rota)
            if rota == "/api/usinas":
                return {"usina_xis": {"inv_total": 2}, "outra_2c": {"inv_total": 1}, "so_inversor": {"inv_total": 3}}
            if rota == "/api/mqtt":
                return {"usinas": [
                    {"usina": "usina_xis", "nome": "Usina Xis GY", "equipamentos": [{"tipo": "inverter", "equipamento": "1"},
                                                                                 {"tipo": "weather", "equipamento": "est-1"}]},
                    {"usina": "outra_2c", "nome": "Outra do para 2C", "equipamentos": [{"tipo": "tracker_ncu", "equipamento": "2"},
                                                                                     {"tipo": "tracker_ncu", "equipamento": "10"}]},
                    {"usina": "so_inversor", "nome": "So Inversor", "equipamentos": [{"tipo": "inverter", "equipamento": "1"}]}]}
            if rota == "/api/trackers/outra_2c":
                return {"trackers": [{"equipamento": "10", "posicao_atual": 10.0, "posicao_alvo": 30.0, "desvio": 20.0, "fora_do_alvo": True},
                                     {"equipamento": "2", "posicao_atual": 5.0, "posicao_alvo": 5.5, "desvio": 0.5, "stale": True}]}
            if rota == "/api/mqtt/usina_xis":
                return {"equipamentos": [{"tipo": "weather", "equipamento": "est-1", "communication_fault": 192,
                                          "measurements": {"irradiance_ghi": 46.59, "wind_speed": 0, "qualquer": "x"}}]}
            raise AssertionError("chamada inesperada ao SCADA: " + rota)
    return Sg


def test_rota_do_raio_x_e_a_leitura_de_agora_do_scada(cli, monkeypatch):
    pedidos = []
    monkeypatch.setattr(app, "_sg", _sg_de_mentira(pedidos))
    monkeypatch.setitem(app._sala_scada_mem, "lista", None)
    rx = cli.get("/api/sala/scada/raiox").get_json()
    assert rx["ok"] and [(x["id"], x["trackers"], x["estacoes"]) for x in rx["usinas"]] == [
        ("outra_2c", 2, 0), ("so_inversor", 0, 0), ("usina_xis", 0, 1)]
    assert pedidos == ["/api/usinas", "/api/mqtt"]
    # a usina de outra fonte acha o SCADA pelo nome (o cliente no fim do nome de lá não atrapalha): os trackers de agora
    r = cli.get("/api/sala/scada?usina=Outra do Pará&fonte=owen&id=123").get_json()
    assert r["situacao"] == "tem" and r["trackers"]["total"] == 2 and r["estacoes"] == []
    assert [x["eq"] for x in r["trackers"]["lista"]] == ["2", "10"]             # ordem natural
    assert r["trackers"]["fora_do_alvo"] == 1 and r["trackers"]["sem_comunicacao"] == 1
    assert r["trackers"]["lista"][0]["atual"] is None                            # leitura velha: sem ângulo de agora
    # a usina que já é lida do supervisório se acha pela CHAVE dela (o nome de lá é outro): a estação de agora
    r = cli.get("/api/sala/scada?usina=Usina X&fonte=greenyellow&id=usina_x").get_json()
    assert r["situacao"] == "tem" and r["trackers"] is None
    assert r["estacoes"] == [{"eq": "est-1", "ok": True, "ts": None,
                              "medidas": [{"nome": "GHI", "valor": 46.59, "unidade": "W/m²"}, {"nome": "Vento", "valor": 0.0, "unidade": "m/s"}]}]
    # sem tracker nem estação lá, ou fora do SCADA: nenhuma chamada a mais
    n = len(pedidos)
    assert cli.get("/api/sala/scada?usina=So Inversor&fonte=pg&id=9").get_json()["trackers"] is None
    assert cli.get("/api/sala/scada?usina=Nao Existe&fonte=pg&id=9").get_json()["situacao"] == "fora_do_scada"
    assert len(pedidos) == n and cli.get("/api/sala/scada").status_code == 400


def test_a_usina_de_tracker_aparece_so_com_o_agora_quando_o_historico_falha(monkeypatch):
    """16/11/2026: o /historico da Castelo do Piauí (128 trackers) devolvia 502 depois de 57 s e a usina sumia inteira
    da aba de trackers. Com o agora respondendo, ela aparece com a leitura de agora, marcada, e ninguém sai parado."""
    cfg = {"id": "usina_t", "usina": "Usina T"}
    agora = [{"equip": str(i), "atual": 20.0 + i, "alvo": 21.0, "sem_comunicacao": i == 3, "alarmes": [], "ts": 1.0} for i in range(1, 6)]
    monkeypatch.setattr(app._sg, "hoje", lambda: "2026-11-16")
    monkeypatch.setattr(app._sg, "trackers_agora", lambda fonte, pid, getter=None: list(agora))
    monkeypatch.setattr(app._sg, "scada_id", lambda fonte, pid: "usina_t")
    monkeypatch.setattr(app, "_sg_trk_nome", lambda fonte, c: c["usina"])

    def falha(*a, **k):
        raise RuntimeError("502 Server Error")
    monkeypatch.setattr(app._sg_trk_hist, "curvas", falha)
    app._sg_trk_sem_hist.clear()
    a = app._sg_trackers_analise("greenyellow", cfg)
    assert a["tem_trackers"] and a["total"] == 5 and a["sem_historico"] is True
    assert a["parados"] == 0                                                     # curva de um ponto não acusa parado
    assert [t["id"] for t in a["trackers"] if t.get("sem_comunicacao")] == ["3"]
    # falhou há pouco: o histórico NÃO é pedido de novo a cada volta (o pesado que não responde ocupa o supervisório e as
    # chamadas seguintes também falham); até a pausa vencer, vale o agora
    pedidos = []
    monkeypatch.setattr(app._sg_trk_hist, "curvas", lambda *a, **k: pedidos.append(1) or {})
    assert app._sg_trackers_analise("greenyellow", cfg)["sem_historico"] is True and pedidos == []
    # a pausa venceu e o histórico voltou: a marca sai
    app._sg_trk_sem_hist[("greenyellow", "usina_t")]["ts"] -= app.SG_TRK_HIST_PAUSA_S + 1
    assert "sem_historico" not in app._sg_trackers_analise("greenyellow", cfg) and pedidos == [1]
    # sem o agora também, a falha segue sendo falha (a usina não vira "sem tracker")
    monkeypatch.setattr(app._sg_trk_hist, "curvas", falha)
    monkeypatch.setattr(app._sg, "trackers_agora", lambda fonte, pid, getter=None: [])
    assert app._sg_trackers_analise("greenyellow", cfg)["tem_trackers"] is False


def test_a_etm_da_axis_junta_as_estacoes_do_supervisorio(monkeypatch):
    sunop = {"rows": [{"usina": "Usina da SunOp", "plant_id": "S1"}], "summary": {"total": 1}}
    monkeypatch.setattr(app, "_swr", lambda cache, build, force=False: {"rows": [{"usina": "PE Teste", "plant_id": "pe_t"},
                                                                                {"usina": "Usina da SunOp", "plant_id": "dup"}]})
    d = app._axis_etm_com_scada(sunop)
    assert [r["usina"] for r in d["rows"]] == ["Usina da SunOp", "PE Teste"] and d["summary"]["total"] == 2
    assert sunop["rows"] == [{"usina": "Usina da SunOp", "plant_id": "S1"}]      # a resposta guardada da SunOp não é mexida

    def fora(cache, build, force=False):
        raise RuntimeError("supervisório fora")
    monkeypatch.setattr(app, "_swr", fora)
    assert app._axis_etm_com_scada(sunop) is sunop                               # o supervisório fora não derruba a aba


def test_rota_do_novo_para_o_sino_do_nexus(cli, monkeypatch):
    """O sino do topo do Nexus pergunta o novo de uma pessoa, por usina. Quem nunca abriu a Sala não tem "desde": nada."""
    pac = {"strings": {"rows": [{"dia": "2026-11-15"}, {"dia": "2026-11-16"}],
                       "episodios": [{"usina": "Usina A", "inversor": "Inversor 1.2", "string": "ST 04", "d0": "2026-11-16", "d1": "2026-11-16", "inicio": "2026-11-16 09:10"},
                                     {"usina": "Usina A", "inversor": "Inversor 1.3", "string": "ST 01", "d0": "2026-11-15", "d1": "2026-11-15", "inicio": "2026-11-15 08:00"}]},
           "trackers": {"rows": [{"usina": "Usina B", "tracker": "Tracker 09", "inicio": "2026-11-16 10:00", "fim": ""}]}}
    monkeypatch.setattr(app, "_sala_pacote_do_mes", lambda: pac)
    monkeypatch.setattr(app, "_falhas_meses", lambda hoje=None: [])
    monkeypatch.setitem(app._sala_idade_mem, "marca", None)
    assert cli.get("/api/sala/novas").get_json() == {"ok": True, "desde": None, "total": 0, "usinas": []}   # nunca abriu a Sala
    app._SALA_VISTOS.da_pessoa(S.SEM_IDENTIDADE, "", app.datetime(2026, 11, 16, 8, 0))
    hoje = app.datetime.now().strftime("%Y-%m-%d")
    d = cli.get("/api/sala/novas").get_json()
    assert d["ok"] and d["desde"] == "2026-11-16 08:00"
    if hoje > "2026-11-16":                      # com o dia 16 fechado, a string aberta nele e o tracker são o novo
        assert d["usinas"] == [{"usina": "Usina A", "strings": 1, "inversores": 1, "trackers": 0},
                               {"usina": "Usina B", "strings": 0, "inversores": 0, "trackers": 1}] and d["total"] == 2


def test_a_ponte_do_nexus_le_o_novo_e_nao_marca_visto():
    import leitura_nexus as L
    assert L.permitido("GET", "/api/sala/novas")
    assert not L.permitido("POST", "/api/sala/visto") and not L.permitido("GET", "/api/sala/visto")


def test_a_sala_le_o_que_o_monitoramento_do_cos_le():
    """Levi, 16/11/2026: "A lista de usinas do Monitoramento do COS [...] puxe a lista". Não é a API do SCADA da
    Automação: é a Ronda COS, que só o Nexus alcança. A tela lê do Nexus (mesma origem): a lista no raio-x e os inversores
    do logger no Conferir fontes, quando a API do SCADA não tem a usina."""
    html = _html()
    assert 'nexusPega("/t/performance/sala-de-controle/cos/usinas")' in html
    assert 'nexusPega("/t/performance/sala-de-controle/cos/inversores")' in html
    assert "raioxHtml() + cosHtml()" in html and "O que o Monitoramento do COS lê" in html
    cf = html[html.index('} else if (ABA === "cf") {'):html.index('} else if (ABA === "dp") {')]
    assert cf.count("cosConf(u, dr)") == 3                     # sem a usina na API do SCADA, sem como ligar, ou com erro
    assert "if (COSI && !COSI.erro && Date.now() - COSI_EM < 30000) return Promise.resolve();" in html   # sem laço: uma leitura a cada 30 s no máximo
    assert "return lerCosInv.p || (lerCosInv.p = " in html and "return lerCos.p || (lerCos.p = " in html   # e um pedido só no ar
    assert "function lerCos() { if (COS) return Promise.resolve();" in html


def test_o_cos_so_entra_onde_o_scada_da_grid_nao_serve(cli, monkeypatch):
    """Levi, 16/11/2026: "a API do COS só substitui o que não temos ou o que é por uma API diferente da API do SCADA
    Grid". A usina que o Tempo real já lê da API do SCADA da Grid (GreenYellow, Sal, Apolo e a Axis pelo supervisório) não
    é conferida: nem com o COS, nem com o próprio SCADA. Na lista do COS só aparece o que ele acrescenta."""
    chamadas = []

    class Sg:
        FONTES = {"greenyellow": {}, "axisscada": {}}

        @staticmethod
        def configurado():
            chamadas.append("configurado")
            return True

        @staticmethod
        def usina_cfg(fonte, pid):
            return {"id": pid} if (fonte, pid) == ("axisscada", "pe_ii") else None
    monkeypatch.setattr(app, "_sg", Sg)
    assert cli.get("/api/sala/conferir?usina=PEII&fonte=axis&id=pe_ii").get_json() == {"ok": True, "situacao": "ja_e_scada"}
    assert cli.get("/api/sala/conferir?usina=Castelo&fonte=greenyellow&id=castelo").get_json()["situacao"] == "ja_e_scada"
    assert chamadas == []                                    # nem pergunta ao SCADA
    html = _html()
    assert '"&id=" + encodeURIComponent(u.pid), 90000), dr = D.drill[u.u];' in html      # a tela diz a chave da usina
    cos = html[html.index("function cosHtml() {"):html.index("// Conferir fontes pelo logger do COS")]
    assert "const doScadaGrid = u => /scadaGridco/.test(NOME[u.g] || \"\");" in html
    assert "mesmas = com.filter(c => c.ms.length && c.ms.every(doScadaGrid))" in cos and "uteis = com.filter(c => !mesmas.includes(c))" in cos
    assert "segunda leitura" in cos and "única leitura" in cos
    cf = html[html.index('} else if (ABA === "cf") {'):html.index('} else if (ABA === "dp") {')]
    ja = cf[cf.index('c.sit === "ja"'):cf.index('c.sit === "fora"')]
    assert "cosConf" not in ja                               # a usina do SCADA da Grid não vai ao COS


# --- os retornos de 16/11/2026 (noite): a lista de inversores, a curva, os sinais da estação, a engrenagem ------------
def test_os_inversores_em_lista_com_ativas_esperadas_e_o_botao_das_strings():
    """Levi: "Quero que os inversores apareçam em formato de lista como era no anterior e aí ter um botão de expandir para
    ver as strings"; "tem que ter a contagem de ativas/esperadas e a diferença! que nem no tempo real"."""
    html = _html()
    assert 'at: i.strings_ativas, dif: i.diferenca, fora: !!i.fora_da_conta' in html          # o que o Tempo real diz
    assert '<div class="ilista"><div class="il cab">' in html and "Ativas / esperadas" in html and "Diferença" in html and "+2 h hoje" in html
    assert 'class="expb" data-expi="${esc(i.n)}"' in html and 'data-expi="*"' in html          # um inversor, ou todos
    assert '(gr || ab ? `<div class="ilx" data-hlbox="1">${gr ? graf(i) : ""}${chips(i)}${osBox(i)}</div>` : "")' in html   # só abertas
    assert 'class="inv ' not in html                                                           # os cartões saíram
    assert 'if ((x = q(".il[data-inv]"))) { const n = x.dataset.inv, k = SEL.u + "|" + n;' in html   # a linha abre a curva
    # dentro da usina não há os números do alto
    assert '$("kpis").hidden = !!SEL.u;' in html and ".kpis[hidden]{display:none}" in html


def test_a_curva_das_strings_em_cinza_com_o_destaque_no_mouse_e_o_dia_inteiro():
    """Levi: "todas as strings em cinza, quando eu passo o mouse na string destaca em azul no gráfico, quando tiver abaixo
    fica laranja e se for string que está sem corrente é vermelho"; "tira esse percentual"; "mostrar todas as horas do dia,
    e se a pessoa quiser ver ela clica em período solar"; "Nos trackers também tem que destacar em branco"."""
    html = _html()
    assert "let SOLAR = false;" in html
    assert 'cor: e === "sem_corrente" ? "var(--critico)" : e === "baixa_perf" ? "var(--severo)" : "var(--neutro)"' in html
    assert '<div class="lin">${ser.map(s => `<span data-hl="${esc(s.sn)}"' not in html         # nem percentual, nem a legenda das strings
    assert '<path data-sn="${esc(s.sn ?? s.nome)}"' in html                                     # a linha sabe de quem é
    assert 'const cor = x.dataset.hlc || "var(--c-ger)";' in html and 'document.addEventListener("mouseover"' in html
    assert 'data-hl="${esc(x.id)}" data-hlc="var(--tinta)"' in html                            # o tracker: branco no escuro, tinta no claro


def test_as_strings_com_mais_de_duas_horas_sem_corrente_hoje_aparecem_de_noite():
    """Levi: "é importante contar quantas ficaram mais que 2 horas nulas em período solar para quando não tiver sol mesmo
    assim conseguirmos ver". Sai das falhas do dia: a que começou hoje, pelas horas de sol dela; a que já vinha, quando o
    inversor tem mais de 2 h de parada hoje com ela."""
    html = _html()
    assert "const conta = e.d0 === hoje ? (e.h_sol || 0) >= 2 : !!(r && (r.dur_h || 0) >= 2 &&" in html
    assert "u.sd = sdU[u.u] || 0;" in html and 'D.sdI[u.u + "|" + i.n] || 0' in html
    assert 'c("Strings", sd, "+2 h",' in html                                                  # a lateral, sem string fora agora
    assert '"com mais de 2 h sem corrente hoje"' in html                                        # o número do alto
    assert "(u.sf || u.sd)}</span>" in html                                                     # a linha da usina (todas, desde 17/11)


def test_a_aba_etm_mostra_os_sinais_que_a_entrada_conta():
    """16/11/2026, a Gravatá II com 1 na lateral e "Sem análise de estação" na aba: o alarme vem da irradiação gravada no
    mês (a lista `etm` da Entrada), não da leitura de agora da fonte. A aba mostra os dois, e a OS leva os sinais."""
    html = _html()
    assert "etmL: Array.isArray(u.etm) ? u.etm.map(String) : [], etmA: Array.isArray(u.etm_alarmes) ? u.etm_alarmes.map(String) : []" in html
    assert "Sinais da estação no mês" in html and 'u.etmA.includes(x) ? "c" : "a"' in html
    assert 'Math.max(dr && dr.etm ? dr.etm.flags.filter(f => f.tipo === "crit").length : 0, u.etmA.length)' in html
    assert ": (u.etmA.length ? u.etmA : u.etmL).slice(0, 4);" in html


def test_a_engrenagem_abre_as_fontes_do_tempo_real_so_para_quem_administra():
    html = _html()
    assert '<button class="eng" id="eng"' in html and 'if ((x = q("#eng"))) { abrirConfig(); return; }' in html
    cfg = html[html.index("function pintaConfig() {"):html.index("function filtraConfig() {")]
    assert "const fontes = ADM && ADM.abre_admin" in cfg and 'src="/admin/tempo-real?janela=1"' in cfg
    assert '${fontes ? `<button class="btnl ${CFG_ABA === "fontes" ? "on" : ""}" data-cfgaba="fontes">' in cfg   # só quem administra vê a aba
    assert "if (cfg) ligar(false);" in html                                                    # fechar relê a lateral
    with app.app.test_client() as c:
        pagina = c.get("/admin/tempo-real?janela=1").get_data(as_text=True)
    assert "html.janela [data-casca]{display:none}" in pagina and "classList.add('janela')" in pagina


def test_a_curva_vem_do_logger_do_cos_so_onde_a_fonte_e_lenta():
    """Levi: "a leitura das strings e inversores na API COS > MONITORAMENTO é super rápida, veja como é feito e se dá para
    aplicar". Na usina da API PV com logger, a curva vem do histórico gravado no COS; a do SCADA da Grid nunca passa por
    ele (a regra do dono), e o banco da Thopen fica com a curva dele. A usina do Tempo real que são vários loggers no COS
    (a Guatambu = Guatambú 1 a 4) casa pelo nome sem o número, só quando não há o nome inteiro."""
    html = _html()
    assert "if (ehApiPv(sk, pid) && !doScadaGrid(u) && !SEM_COS[k]) { const c = await curvaCos(u, dr, invNome, dia);" in html
    cc = html[html.index("async function curvaCos(u, dr, invNome, dia) {"):]
    cc = cc[:cc.index("\n}\n")]
    assert 'nexusPega("/t/performance/sala-de-controle/cos/entradas?inv=" + encodeURIComponent(p.s.id) + "&dia=" + dia)' in cc
    assert "if (!pr.porNome && !(p.s.strings && p.s.strings === p.iv.s.length)) return null;" in cc     # par pela ordem só com as mesmas strings
    assert "pt.s[k] / 100" in cc and "buraco" in cc                                               # centésimos de A; o buraco não se liga
    assert "} catch (e) { return null; }" in cc                                                   # qualquer falha: vale a fonte
    assert 'const n = normN(x.nome), b = n.replace(/\\s+(\\d+|i{1,3}|iv|v)$/, ""); return b !== n ? tr.filter(u => normN(u.u) === b) : [];' in html
    assert "if (ex.length) return ex;" in html                                                    # com o nome inteiro, nunca pelo nome curto
    assert 'data-curvafonte="${esc(i.n)}"' in html and "SEM_COS[k] = 1; delete D.curvas[k];" in html        # e dá para ver pela fonte


def test_a_curva_do_banco_tem_copia_e_um_pedido_so_no_ar(cli, monkeypatch):
    """O padrão do Monitoramento do COS na curva do banco da Thopen: 5 min de cópia para hoje, 1 h para o dia que passou, e
    a tranca de uma string da usina faz a próxima leitura ser nova. A tela pede a usina inteira de uma vez."""
    lidas = []
    monkeypatch.setattr(app, "_pg_strings_curva", lambda pid, dia, inv=None: lidas.append((pid, dia, inv)) or {"plant_id": pid, "data": dia, "inversores": [{"id": inv}]})
    monkeypatch.setattr(app, "_pg_curva_copia", {})
    monkeypatch.setattr(app, "_trancadas", set())
    hoje = app.datetime.now().strftime("%Y-%m-%d")
    for _ in range(3):
        assert cli.get(f"/api/pg/curva/33?data={hoje}&inv=181").get_json()["inversores"] == [{"id": 181}]
    assert lidas == [(33, hoje, 181)]                                    # três pedidos, uma consulta
    cli.get(f"/api/pg/curva/33?data={hoje}&inv=182")
    cli.get("/api/pg/curva/33?data=2026-11-01&inv=181")
    assert len(lidas) == 3                                               # outro inversor e outro dia são outras leituras
    relogio = [app.time.time()]
    monkeypatch.setattr(app.time, "time", lambda: relogio[0])
    relogio[0] += 290
    cli.get(f"/api/pg/curva/33?data={hoje}&inv=181")
    assert len(lidas) == 3                                               # dentro dos 5 min, a cópia
    relogio[0] += 11
    cli.get(f"/api/pg/curva/33?data={hoje}&inv=181")
    cli.get("/api/pg/curva/33?data=2026-11-01&inv=181")
    assert len(lidas) == 4 and lidas[-1] == (33, hoje, 181)              # hoje venceu em 5 min; o dia que passou, não
    monkeypatch.setattr(app, "_trancadas", {"33|181|4", "99|1|1"})
    cli.get("/api/pg/curva/33?data=2026-11-01&inv=181")
    assert len(lidas) == 5                                               # trancou uma string da usina: leitura nova

    def falha(pid, dia, inv=None):
        raise RuntimeError("banco fora")
    monkeypatch.setattr(app, "_pg_strings_curva", falha)
    r = cli.get("/api/pg/curva/34?data=2026-11-01")
    assert r.status_code == 500 and app._pg_curva_no_ar == {}            # a falha não fica guardada nem trava o próximo
    assert 'url = "/api/pg/curva/" + encodeURIComponent(pid) + "?data=" + dia;' in _html()      # a usina inteira, uma vez


# --- nomes e grupos das UFVs só na Sala (16/11/2026, noite) -----------------------------------------------------------
def test_o_arranjo_guarda_so_o_que_esta_no_formato(tmp_path):
    """Levi: "eu deverei também conseguir editar o nome e agrupar UFVs"; "Só sala!"; "cada usina diferente!"."""
    a = S.Arranjo(str(tmp_path / "sala_arranjo.json"))
    assert a.ler() == {"nomes": {}, "grupos": {}, "por": "", "em": ""}                     # sem arquivo, nada mudou
    d = a.gravar({"thopen-pv|18747508": "  Guatambu   Sul ", "thopen-db|20": ""}, {"thopen-pv|18747508": "Complexo G", "apolo|gravata_ii": "Complexo G"},
                 "Pessoa de Teste", S.datetime(2026, 11, 16, 22, 30))
    assert d["nomes"] == {"thopen-pv|18747508": "Guatambu Sul"}                             # espaço sobrando sai; vazio some
    assert d["grupos"] == {"thopen-pv|18747508": "Complexo G", "apolo|gravata_ii": "Complexo G"}
    assert a.ler() == {**d, "por": "Pessoa de Teste", "em": "2026-11-16 22:30"}
    a.gravar({}, {}, "Outra", S.datetime(2026, 11, 17, 8, 0))                               # gravar troca o quadro inteiro
    assert a.ler()["nomes"] == {} and a.ler()["grupos"] == {}
    for ruim in ({"sem barra": "x"}, {"thopen-pv|1": 5}, {"thopen-pv|1": "x" * 61}, {"A|1": "x"}, ["lista"], {"thopen-pv|1": "a\x07b"}):
        with pytest.raises(ValueError):
            S.arranjo_limpo(ruim)
    assert S.arranjo_limpo(None) == {}


def test_a_rota_do_arranjo_le_para_todos_e_grava_so_para_quem_administra(cli, monkeypatch, tmp_path):
    monkeypatch.setattr(app, "_SALA_ARRANJO", S.Arranjo(str(tmp_path / "sala_arranjo.json")))
    assert cli.get("/api/sala/arranjo").get_json() == {"ok": True, "nomes": {}, "grupos": {}, "por": "", "em": ""}
    monkeypatch.setattr(app, "_eu_abre_grava", lambda: (True, False))                        # o gestor admin abre, mas não grava
    r = cli.post("/api/sala/arranjo", json={"nomes": {"thopen-pv|1": "X"}, "grupos": {}})
    assert r.status_code == 403 and cli.get("/api/sala/arranjo").get_json()["nomes"] == {}
    monkeypatch.setattr(app, "_eu_abre_grava", lambda: (True, True))
    r = cli.post("/api/sala/arranjo", json={"nomes": {"thopen-pv|1": "Usina Um"}, "grupos": {"thopen-pv|1": "Grupo A"}})
    assert r.status_code == 200 and r.get_json()["nomes"] == {"thopen-pv|1": "Usina Um"}
    d = cli.get("/api/sala/arranjo").get_json()
    assert d["grupos"] == {"thopen-pv|1": "Grupo A"} and d["em"]
    assert cli.post("/api/sala/arranjo", json={"nomes": {"sem barra": "x"}}).status_code == 400
    assert cli.get("/api/sala/arranjo").get_json()["nomes"] == {"thopen-pv|1": "Usina Um"}   # o pedido torto não apagou nada
    # o gestor (passe do Nexus) lê e não grava; a ponte de leitura não ganhou a rota
    import leitura_nexus as LN
    assert "/api/sala/arranjo" not in LN.POSTS_DE_CONSULTA_GESTOR and "/api/sala/arranjo" not in LN._GET


def test_a_tela_mostra_o_nome_da_sala_e_junta_os_grupos_sem_somar():
    html = _html()
    assert 'rot: (arr && arr.nomes[g.fonte_id + "|" + u.plant_id]) || u.usina, gr: (arr && arr.grupos[g.fonte_id + "|" + u.plant_id]) || "",' in html
    assert "return {u: u.usina, pid: u.plant_id," in html                                    # a chave da usina segue a da fonte
    assert 'pega("/api/sala/arranjo", 20000).catch(() => null)' in html and "if (arrL && arrL.nomes) ARR_LIDO.v = arrL;" in html
    assert '<div class="ug">${u.gr ? esc(u.gr) : "Sem grupo"}' in html and "(a.gr ? 0 : 1) - (b.gr ? 0 : 1) || natural(a.gr, b.gr)" in html
    assert 'data-u="${esc(u.u)}" title="${esc(u.rot)}${u.rot !== u.u ? " (na fonte: " + esc(u.u) + ")" : ""}' in html
    assert 'r.innerHTML = (SEL.u ? "· " + esc(rotN(SEL.u, SEL.g))' in html
    cfg = html[html.index("function pintaConfig() {"):html.index("function filtraConfig() {")]
    assert "só na Sala de controle" in cfg and 'data-cfgn="${esc(k)}"' in cfg and 'data-cfgg="${esc(k)}" list="cfggr"' in cfg
    assert '${gravaC ? "" : "disabled"}' in cfg and "gravaC ? '<button class=\"btn\" data-cfgsalvar=\"1\">Salvar</button>' : \"\"" in cfg
    assert 'await grava("/api/sala/arranjo", {nomes: limpa(ARRED.nomes), grupos: limpa(ARRED.grupos)});' in html


def test_a_curva_abre_embaixo_do_inversor_e_varios_ficam_abertos():
    """Levi, 16/11/2026 (noite): "O gráfico abrisse em Drill [...] clicando no inversor. E aí dá para clicar em vários
    inversores de uma vez e carregar o gráfico". O clique abre ou fecha a curva DAQUELE inversor; os outros ficam."""
    html = _html()
    assert "const GRAF = new Set();" in html
    assert "if (GRAF.has(k)) GRAF.delete(k); else { GRAF.add(k); INV = n; verS(SEL.u, n); }" in html
    assert 'const graf = i => { const bruta = D.curvas[u.u + "|" + i.n + "|" + dia];' in html and "if (bruta === undefined) lerCurva(u, i.n, dia);" in html
    assert "<h3>Curva por string · ${esc(INV)}" not in html                                    # o painel fixo do alto saiu
    assert 'data-grafx="1">Fechar as ${nG} curvas' in html and 'if ((x = q("[data-grafx]"))) { GRAF.clear();' in html
    assert "if (INV) GRAF.add(u.u + \"|\" + INV); }" not in html                               # nada abre sozinho: a curva só no clique (17/11)
    assert "INV = null; GRAF.clear();" in html                                                 # outra usina começa do zero
    # abrir vários inversores da mesma usina não repete a leitura da usina inteira: um pedido no ar por endereço
    assert "await (CURVAP[url] || (CURVAP[url] = pega(url, 90000).finally(() => { delete CURVAP[url]; })))" in html
    # o destaque no mouse fica no gráfico do inversor da string
    assert '(x.closest("[data-hlbox]") || document).querySelectorAll("svg[data-ch] path[data-sn]")' in html
    assert 'data-curvafonte="${esc(i.n)}"' in html and 'SEL.u + "|" + x.dataset.curvafonte + "|" + (DIA || HOJE)' in html


def test_o_servidor_aquecendo_nao_abre_a_sala_vazia():
    """16/11/2026: depois de uma subida a Entrada responde "aquecendo" por 2 a 7 min, e a Sala abria sem fonte nenhuma até
    a volta de 5 min. A tela diz o que é, tenta de novo em 15 s e não troca a tela cheia de quem já estava nela."""
    html = _html()
    assert "if (ent && ent.aquecendo && !(ent.grupos || []).length) {" in html
    assert "ligar.t = setTimeout(() => ligar(!D), 15000); return; }" in html and "if (!D) $(\"corpo\").innerHTML = " in html


# --- os retornos de 16/11/2026 (23h30) ---------------------------------------------------------------------------------
def test_a_visao_de_strings_limpa_e_o_acompanhamento_na_lateral():
    """Levi: "Strings em acompanhamento vão para barra lateral, depois da coluna strings"; "pode remover esse número de
    strings do gráfico"; "Mostrar a corrente da string quando clicar no inversor"; a legenda das cores "deve ficar no
    gráfico"; "o botão de data e período solar fica na mesma linha de abrir todas as strings"."""
    html = _html()
    assert '<div class="faixa"><label>Strings em acompanhamento' not in html
    assert "<span>Usina</span><span title=\"Todas as strings sem corrente" in html and ">Str.</span><span title=\"Strings em acompanhamento" in html
    assert 'if ((x = q(".ac.ed[data-ac]")))' in html and 'if (x.classList.contains("aci")) {' in html
    grava = html[html.index('if (x.classList.contains("aci")) {'):]
    assert 'grava("/api/state/tracking", {key: VKEY[u.g] + ":" + u.pid, value: v || null})' in grava[:900]     # a mesma chave do Tempo real
    assert 'document.activeElement.classList.contains("aci")) return;' in html                                    # a releitura não tira o campo de quem digita
    graf = html[html.index("const graf = i => { const bruta"):html.index("// os inversores por cabine")]
    assert '<div class="lin">' not in graf and "Cinza = gerando" in graf                                          # a legenda das cores no gráfico
    assert '<small>${s[1] == null ? "—" : nf(s[1], 2) + " A"}</small></button>' in html                          # a corrente sempre, até na trancada
    barra = html[html.index('<span>Dia</span><input type="date"'):]
    barra = barra[:barra.index('data-expi="*"')]
    assert 'data-solar="1"' in barra and "OS de performance" in barra and 'data-grafx="1"' in barra            # uma linha só


def test_comentario_na_ordem_data_nome_texto_e_a_os_criada_rele_a_conversa():
    html = _html()
    assert '`<div class="coment"><small>${esc((c.ts || "agora")' in html and '</small><b>${esc(c.nick || "—")}</b><span style="flex:1;white-space:pre-line">${esc(c.texto)}</span>' in html
    os = html[html.index('d.gc !== "os-criada"'):]
    os = os[:os.index("// O que aconteceu com o inversor")]
    assert "ESTADO = null;" in os and "setTimeout(() => { ESTADO = null; if (SEL.u === u.u) lerUsina(u, true); }, 5000)" in os
    assert html.count('p.set("comentario", VKEY[u.g] + ":" + u.pid)') >= 3                                         # a chave da conversa vai no link da OS


def test_a_potencia_por_dia_com_ate_cinco_dias_as_cores_e_a_correlacao():
    """Levi: "Dados do dia todo"; "selecionar para ver mais que um dia"; "o filtro só vai caber 5 dias"; "um botão de
    correlação que abre abaixo os gráficos de trackers"; "geração azul, POA laranja e GHI amarelo"; a Athon não é "a fonte
    não guarda"."""
    html = _html()
    assert "for (let k = 0, d0 = POT.ini; k < 5 && d0 <= POT.fim; k++, d0 = addDia(d0, 1)) { dias.push(d0); lerPotDia(u, d0); }" in html
    assert 'if (addDia(POT.ini, 4) < POT.fim) POT.fim = addDia(POT.ini, 4);' in html and 'if (addDia(POT.fim, -4) > POT.ini) POT.ini = addDia(POT.fim, -4);' in html
    assert '"&ini=" + dia + "&fim=" + dia, 150000)' in html                                                       # um pedido por dia (o servidor guarda cada um)
    pot = html[html.index('} else if (ABA === "pot") {'):html.index('} else if (ABA === "oc") {')]
    assert "opt = SOLAR ? {x0: 360, x1: 1080} : {x0: 0, x1: 1440}" in pot                                           # o dia inteiro; o período solar é o botão
    assert 'cor: "var(--c-ger)", forte: true}' in pot and 'cor: "var(--c-poa)", dash: "6 4"' in pot and 'cor: "var(--c-ghi)", dash: "6 4"' in pot
    assert "CORES[" not in pot                                                                                     # sem a paleta de doze cores por inversor
    assert 'data-potcorr="1"' in pot and "if (POT.corr && temTrk) dias.forEach(d0 => lerTrk(u, d0));" in pot
    assert "--c-ger:#5aa9f5;--c-poa:#f59a4a;--c-ghi:#e6c84f" in html and "--c-ger:#1f6fd0;--c-poa:#c8640f;--c-ghi:#a8860a" in html
    etm = html[html.index('} else if (ABA === "etm") {'):html.index('} else if (ABA === "gp") {')]
    assert 'cor: "var(--c-poa)", forte: true}' in etm and 'cor: "var(--c-ghi)", forte: true}' in etm and 'data-solar="1"' in etm
    assert "POT_FORA[u.g] ||" in html and "pega(\"/api/pg/etm/chart?plant_id=\"" in html
    assert 'athon: "sunop"' in html and "const POT_FORA = {axis:" in html                                          # a Athon ligada (17/11); a Axis, fora


def test_as_fontes_que_nao_batem_viram_aviso_ao_lado_da_usina():
    """Levi: "Não faz sentido esse botão conferir fonte [...] O mínimo seria ter algum símbolo de aviso ao lado da UFV"."""
    html = _html()
    assert 'aba("cf", "Conferir fontes")' not in html
    dv = html[html.index("function calcDvg() {"):html.index("const divergeCos = u =>")]
    assert 'if (x.fonte !== "SCADA Grid") return;' in dv and "if (doScadaGrid(u)) return;" in dv                    # a regra do COS
    assert "if (tot && u.inv && tot !== u.inv)" in dv and 'const semC = ms.every(m => m.grupo === "sem_comunicacao"), euSem = u.st === "sem_comm";' in dv
    assert '<span class="dvg" data-dvg="1"' in html and 'ABA = "cf"; desenhar(); scrollTo(0, 0); return; }' in html   # o clique abre o lado a lado
    assert "atualizaCos();" in html and "calcDvg();" in html


def test_as_ocorrencias_juntam_o_que_caiu_em_dez_minutos_do_primeiro():
    """Levi: "Caso seja trackers ou strings caindo ao mesmo tempo aparecerão juntos, tolerância de 10 minutos". A regra
    roda de verdade (no node): o grupo conta do PRIMEIRO, não em cadeia."""
    import json
    import shutil
    import subprocess
    html = _html()
    assert 'const temOc = doScadaGrid(u) || SKEY[u.g] === "pg"' in html                                             # só SCADA da Grid e banco
    assert 'p.set("frase", "verificacao de tracker parado")' in html and "MARC.clear(); o.invs.forEach(n => MARC.add(n)); abrirCriarOS(); return; }" in html
    assert 'data-ocos="s"' in html and 'data-ocos="t"' in html and "grafOc(o)" in html
    if not shutil.which("node"):
        pytest.skip("sem o node nesta máquina")
    js = html[html.index("const OC_TOL_MIN = 10"):html.index("// a OS dos trackers de uma ocorrência")]
    D = {"eps": {"U|Inversor 1.1": [{"s": "ST 04", "ini": "2026-11-16 08:00", "fim": "2026-11-16 12:10", "aberta": False, "kwh": 10},
                                    {"s": "ST 05", "ini": "2026-11-16 08:11", "fim": "", "aberta": True, "kwh": 5}],
                 "U|Inversor 1.2": [{"s": "ST 01", "ini": "2026-11-16 08:20", "fim": "", "aberta": True, "kwh": 7}],
                 "OUTRA|Inversor 9": [{"s": "ST 01", "ini": "2026-11-16 08:01", "fim": "", "aberta": True, "kwh": 1}]},
         "trkRows": [{"usina": "U", "tracker": "TR-03", "inicio": "2026-11-16 08:09", "fim": "", "perda_kwh": 20},
                     {"usina": "OUTRA", "tracker": "TR-99", "inicio": "2026-11-16 08:00", "fim": ""}]}
    script = ('const natural = (a, b) => String(a).localeCompare(String(b), "pt-BR", {numeric: true}); const D = ' + json.dumps(D) + ";\n" + js +
              '\nconsole.log(JSON.stringify(ocorrenciasDe({u: "U"}).map(o => [o.t, o.ss.length, o.ts.length, o.aberta, o.kwh, o.invs])));')
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [
        ["2026-11-16 08:11", 2, 0, True, 12, ["Inversor 1.1", "Inversor 1.2"]],      # 08:11 e 08:20 (9 min do primeiro DESTE grupo)
        ["2026-11-16 08:00", 1, 1, True, 30, ["Inversor 1.1"]]]                      # a string das 08:00 e o tracker das 08:09, juntos


def test_o_de_para_real_sai_do_cadastro(cli):
    """Levi: "O de-para não faz sentido! Tem que vir o de-para real!". A rota devolve o que o cadastro diz de cada
    inversor da usina (como a fonte chama, como a plataforma chama, as esperadas, o kWp), só leitura."""
    assert cli.get("/api/sala/depara").status_code == 400
    chave = next((c for c, m in app.EQUIP_NAMES.items() if m and c not in set(app._dp_aliases())), None)
    if not chave:
        pytest.skip("cadastro vazio nesta máquina")
    usina = app.USINA_DISPLAY.get(chave) or chave
    d = cli.get("/api/sala/depara", query_string={"usina": usina}).get_json()
    assert d["ok"] and chave in [c["chave"] for c in d["chaves"]]
    inv = next(c for c in d["chaves"] if c["chave"] == chave)["inversores"]
    assert inv and set(inv[0]) == {"esup", "nome", "esp", "kwp", "ug", "cod_fracttal", "nome_fracttal", "cabine"}
    assert {i["esup"] for i in inv} >= set(app.EQUIP_NAMES[chave])
    assert cli.get("/api/sala/depara", query_string={"usina": "Usina Que Não Existe 999"}).get_json()["chaves"] == []
    html = _html()
    assert 'pega("/api/sala/depara?usina=" + encodeURIComponent(u.u), 30000)' in html and "que a fonte manda e o cadastro não conhece" in html
    assert 'data-dped="1"' in html                                                                                 # o editor fica atrás do botão


def test_o_pr_do_mes_da_usina_e_a_soma_dos_inversores_pela_mesma_conta(monkeypatch):
    """Levi: "Ao lado do nome da UFV seria interessante mostrar PR do mês e acompanhamento da meta do mês". O cabeçalho
    usa o que a aba Geração e PR já calcula; a usina é a soma dos inversores (o PR pondera pela energia)."""
    class _Base:
        @staticmethod
        def get_json():
            return {"pontos": [], "pot": 0.2, "meta": 0.8, "meta_ger": 0.9, "meta_poa": 5.0}
    monkeypatch.setattr(app, "api_g_diario", lambda: _Base())
    monkeypatch.setattr(app, "_inv_hist_pr_detail", lambda fonte, pid: [{"nome": "Inversor 1", "pot_kwp": 100.0}, {"nome": "Inversor 2", "pot_kwp": 100.0}])
    monkeypatch.setattr(app, "_inv_dias_por_base", lambda fonte, usina, ano, mes: [
        ("bd_performance", {"2026-11-10": {"ipoa": 5.0, "inv": {"Inversor 1": 500.0, "Inversor 2": 300.0}}})])
    d = app._inv_historico("pg", 1, "Usina De Teste", 2026, 11, agora=app.datetime(2026, 11, 20, 12, 0))
    assert d["da_usina"] == {"ger": 800.0, "dias": 1, "pr": 0.8, "meta": 900.0, "pct_meta": 88.9}
    assert d["inversores"]["Inversor 1"]["pr"] == 1.0 and d["inversores"]["Inversor 2"]["pr"] == 0.6           # 0,8 é a média ponderada dos dois
    html = _html()
    assert "tot: g.da_usina || null, prMeta: g.pr_meta ?? null" in html and "function prDoMes() {" in html
    assert "if (!calada && D.ger.usina !== u.u) lerGer(u);" in html                                                # a geração lida quando a usina abre


def test_o_tema_claro_tem_as_cores_do_grafico_e_da_janela():
    html = _html()
    assert 'stroke="var(--grade)"' in html and "--grade:rgba(15,23,42,.10);--janela:#ffffff" in html
    assert ".modal>div{background:var(--janela);" in html and 'html[data-tema="claro"] .st.sem_corrente{background:#be123c;color:#fff}' in html
    assert 'cor: "var(--tinta)", larg: 1.8, dash: "7 5"' in html                                                   # o alvo aparece nos dois temas


def test_o_de_para_da_usina_que_o_cadastro_guarda_pelo_nome_de_exibicao(cli, monkeypatch):
    """17/11/2026, em produção: a Castelo do Piauí (GreenYellow) veio "sem chave", com esperadas no Tempo real. A
    GreenYellow e a Sal não têm "Equipamento Supervisório": o cadastro delas é pelo nome de exibição."""
    monkeypatch.setattr(app, "ESPERADO_INV_DISP", {app._nrm("Usina Só De Exibição"): {"Inversor 1.1": 12, "Inversor 1.2": 13}})
    monkeypatch.setattr(app, "POWER_INV_DISP", {app._nrm("Usina Só De Exibição"): {app._nrm("Inversor 1.1"): 137.5}})
    monkeypatch.setattr(app, "FRAC_COD_INV_DISP", {})
    d = cli.get("/api/sala/depara", query_string={"usina": "Usina Só De Exibição"}).get_json()
    assert [c["chave"] for c in d["chaves"]] == ["Usina Só De Exibição"] and d["chaves"][0]["por_exibicao"] is True
    assert d["chaves"][0]["inversores"] == [
        {"esup": None, "nome": "Inversor 1.1", "esp": 12, "kwp": 137.5, "ug": None, "cod_fracttal": None, "nome_fracttal": None, "cabine": None},
        {"esup": None, "nome": "Inversor 1.2", "esp": 13, "kwp": None, "ug": None, "cod_fracttal": None, "nome_fracttal": None, "cabine": None}]
    assert "i.esup == null ? (v && v.id != null ? esc(v.id)" in _html()


def test_a_athon_le_a_potencia_pela_medida_p_da_sunop_e_nao_esconde_a_pausa(cli, monkeypatch):
    """Levi, 17/11/2026: "pode ligar a Athon na potência". Um pedido por usina e dia (a medida P de cada inversor); a
    SunOp pausada ou sem resposta é "não respondeu", com o motivo, e não "sem dado" (a leitura que falhou não vira zero)."""
    from datetime import date
    pedidos = []
    monkeypatch.setitem(app._sunop_meta, "USINA_T", {"inv_other": {"INV_1": {"P": "USINA_T.INV_1.P", "EPD": "USINA_T.INV_1.EPD"},
                                                                   "INV_2": {"P": "USINA_T.INV_2.P"}, "INV_3": {"EPD": "x"}}})
    monkeypatch.setattr(app, "_sunop_analog_history", lambda paths, ini, fim, inst="gridco", period=None: pedidos.append((sorted(paths), ini, fim, inst)) or {
        "USINA_T.INV_1.P": [("2026-11-15T08:00:00", 50.0), ("2026-11-15T08:05:00", 60.0)]})
    d = app._pa_ler_sunop("USINA_T", date(2026, 11, 15))
    assert pedidos == [(["USINA_T.INV_1.P", "USINA_T.INV_2.P"], "2026-11-15T00:00:00", "2026-11-15T23:59:59", "gridco")]   # um pedido, só as medidas P
    assert [(i["id"], i["pontos"]) for i in d["inversores"]] == [("INV_1", [("2026-11-15T08:00:00", 50.0), ("2026-11-15T08:05:00", 60.0)]), ("INV_2", [])]
    dia = app._pa.monta_dia(date(2026, 11, 15), d, date(2026, 11, 17))
    assert dia["situacao"] == "ok" and dia["inversores"][0]["pontos"] == [[480, 50.0], [485, 60.0]] and len(dia["sem_leitura"]) == 1
    # vazio com a SunOp pausada: não respondeu, com o motivo
    monkeypatch.setattr(app, "_sunop_analog_history", lambda *a, **k: {})
    monkeypatch.setattr(app, "_sunop_edge_aberto", lambda: False)
    monkeypatch.setattr(app, "_sunop_sem_rede", lambda inst="gridco": "teto")
    with pytest.raises(app._pa.FonteNaoRespondeu, match="pausada"):
        app._pa_ler_sunop("USINA_T", date(2026, 11, 15))
    # vazio sem trava: hoje é "ainda não tem"; dia passado é "não devolveu" (pode tentar de novo)
    monkeypatch.setattr(app, "_sunop_sem_rede", lambda inst="gridco": None)
    assert "ainda não tem" in app._pa_ler_sunop("USINA_T", app.datetime.now().date())["motivo"]
    with pytest.raises(app._pa.FonteNaoRespondeu, match="não devolveu"):
        app._pa_ler_sunop("USINA_T", date(2026, 11, 15))
    with pytest.raises(app._pa.FonteNaoRespondeu, match="catálogo"):
        app._pa_ler_sunop("USINA_QUE_NAO_EXISTE", date(2026, 11, 15))                    # sem catálogo: nem pergunta
    assert app._pa.fonte("sunop")["familia"] == "sunop"
    with pytest.raises(app._pa.Recusado):
        app._pa.fonte("axis")                                                            # a Axis segue fora


def test_as_strings_em_cartao_com_a_corrente_ate_das_trancadas():
    """Levi, 17/11/2026: "trancadas azul, mostrando a corrente [...] não precisa ter esse cadeado mas o tracejado gostei! é
    importante mostrar a corrente até das trancadas pq caso o técnico ligue a string numa trancada saberemos"."""
    html = _html()
    assert "button.st.trancada{border:1px dashed var(--c-ger);" in html and "color:var(--c-ger)}" in html           # azul, tracejada
    chips = html[html.index("const chips = i =>"):html.index("const osBox = i =>")]
    assert 'e === "trancada" ? "tranc."' not in chips and "cadeado" not in chips                                    # a corrente no lugar do "tranc."
    assert '(e === "trancada" ? "trancada · " : "") + (s[1] == null ? "sem leitura" : nf(s[1], 2) + " A")' in chips


def test_a_lateral_mostra_todas_as_strings_sem_corrente_na_cor_do_tempo_real():
    """Levi, 17/11/2026: "mostrasse todas as linhas que estão sem corrente. Eu acho que está fazendo a diferença. [...] Se
    acompanhamento está igual com o que tem de string zerada, fica em azul [...] Se está diferente [...] O laranja"."""
    html = _html()
    assert '(tot => tot ? `<b class="${u.sa === tot ? "az" : ""}">${tot}</b>`' in html and "(u.sf || u.sd)}</span><span class=\"ac" in html
    assert "<span>${v(u.sf ? u.sn : u.sd)}</span>" not in html                                  # não é mais a diferença
    assert ".tela .lado .f .u b.az,.tela .lado .tri b.az{color:var(--info)}" in html and 'c("Strings", sf, sf ? (sa ? "ac. " + nf(sa) : "sem ac.") : ""' in html
    assert ".tela .lado{font-size:14.3px}" in html and ".tela .lado .f .u{font-size:13.2px}" in html   # a lateral 10% maior


def test_a_usina_le_strings_trackers_e_estacao_ao_mesmo_tempo():
    """Levi, 17/11/2026: "as vezes só quero ver a string primeiro, poderia dar prioridade a aba que cliquei e carrega o
    resto em segundo plano". Os trackers e a estação eram pedidos só DEPOIS de as strings voltarem; agora os três saem
    juntos e as abas Trackers e ETM desenham com o que já chegou."""
    html = _html()
    ler = html[html.index("async function lerUsina(u, calada) {"):html.index("// (g) O que o SCADA da Grid tem desta usina AGORA")]
    assert ler.index("if (EPT[sk]) extras.push(pega(EPT[sk]") < ler.index("try { pl = await pega(urlPl, 90000); }")           # os trackers saem antes de esperar as strings
    assert ler.index("if (EPE[sk]) extras.push((ETMS[sk]") < ler.index("try { pl = await pega(urlPl, 90000); }")              # e a estação também
    assert "if (!manter) PRE[u.u] = dr;" in ler and "D.drill[u.u] = dr; delete PRE[u.u];" in ler and "dr.inv = inv; dr.em = Date.now()" in ler
    assert "} catch (e) { delete PRE[u.u];" in ler                                                                    # a usina que falhou não deixa resto
    assert 'const dr = D.drill[u.u] || ((ABA === "trk" || ABA === "etm") && !FALHOU[u.u] ? PRE[u.u] : undefined), cp = $("corpo");' in html
    # os cartões de string: valores no centro e 20% mais estreitos (62 → 50 px)
    assert "button.st{width:auto;min-width:50px;" in html and "align-items:center;justify-content:flex-start;gap:2px;text-align:center;" in html


def test_o_azul_e_so_quando_o_acompanhamento_e_igual_as_zeradas_como_no_tempo_real():
    """Levi, 17/11/2026: "se as duas são iguais, vai ficar em azul, que nem é no tempo real. Usa a mesma lógica". O
    Monitoramento usa `bate = dif === -tCount` (igual, não "pelo menos")."""
    html = _html()
    mon = (app.Path(app._RAIZ) / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8-sig") if hasattr(app, "Path") else open(app.os.path.join(app._RAIZ, "docs", "redesign", "Monitoramento (novo design).html"), encoding="utf-8-sig").read()
    assert "const bate=(dif!=null&&tCount!=null&&dif===-tCount);" in mon                         # a regra de lá
    assert "ok = l.every(u => !(u.sf || u.sa) || u.sa === u.sf);" in html and 'u.sa >= tot ? "az"' not in html


def test_a_linha_de_botoes_das_strings_fica_fixa_e_tem_o_criar_os():
    """Levi, 17/11/2026: "gostaria que essa linha em string ficasse fixa, mesmo dando scroll ela fica no topo! tem que ter
    um botão de criar OS aqui também"."""
    html = _html()
    assert ".barrafix{position:sticky;top:0;z-index:18;" in html and '<div class="diasel barrafix" style="gap:8px"><span>Dia</span>' in html
    barra = html[html.index('<div class="diasel barrafix"'):]
    barra = barra[:barra.index("Object.keys(cab)")]
    assert 'data-criaros="1"' in barra and "${PODE ? `<button class=\"btn\" data-criaros" in barra            # só para quem grava
    assert 'if ((x = q("[data-criaros]"))) { if (!PODE) return; if (MARC.size) abrirCriarOS(); else toast(' in html   # sem marcar, não escolhe por ninguém


def test_strings_fora_e_a_conta_do_tempo_real_e_a_usina_aberta_reconta():
    """Levi, 17/11/2026, a SMP100: "2 inversores e 12 strings fora não faz sentido pois tem que levar em conta a string
    ativa"; "diz 3 strings fora, quando abri só tinha 2, no tempo real assim que carregava a usina ele recontava". A
    regra roda de verdade (no node): a falta é esperadas − ativas, só de quem está na conta, sem a sobra pagar a falta."""
    import json
    import shutil
    import subprocess
    html = _html()
    assert "fora = l.reduce((a, i) => a + faltaDe(i), 0)" in html and "const r = faltaDe(i), bx1 = " in html
    assert "recontaStrings(u.u, u.g, inv);" in html and "if (dr && dr.em && dr.g && dr.em > tRes) recontaStrings(nome, dr.g, dr.inv);" in html
    mon = open(app.os.path.join(app._RAIZ, "docs", "redesign", "Monitoramento (novo design).html"), encoding="utf-8-sig").read()
    assert "const dif=conta.reduce((t,i)=>t+Math.min(0,i.diferenca),0);" in mon                    # a régua de lá
    if not shutil.which("node"):
        pytest.skip("sem o node nesta máquina")
    js = html[html.index("const naConta = i =>"):html.index("const PRE = {};")]
    D = {"grupos": [{"id": "athon", "usinas": [{"u": "SMP100", "sf": 3, "sa": 1, "sn": 2}, {"u": "OUTRA", "sf": 9, "sa": 0, "sn": 9}]}]}
    inv = [{"n": "6.1", "dif": 0, "esp": 18, "at": 18}, {"n": "5.2", "dif": -2, "esp": 17, "at": 15}, {"n": "1.1", "dif": 3, "esp": 10, "at": 13},
           {"n": "desligado", "dif": -17, "esp": 17, "at": 0, "desl": True}, {"n": "fora", "dif": -5, "esp": 5, "at": 0, "fora": True}, {"n": "sem conta", "dif": None}]
    script = ("const D = " + json.dumps(D) + ";\n" + js + "\nconst inv = " + json.dumps(inv) + ";\nrecontaStrings('SMP100', 'athon', inv);\n"
              "const semNumero = [{dif: -1, esp: null, at: 3}]; recontaStrings('OUTRA', 'athon', semNumero);\n"
              "console.log(JSON.stringify([inv.map(faltaDe), D.grupos[0].usinas]));")
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    faltas, usinas = json.loads(r.stdout)
    assert faltas == [0, 2, 0, 0, 0, 0]                      # 18/18 não tem string fora; a sobra de +3 não paga; desligado e fora da conta ficam fora
    assert usinas[0] == {"u": "SMP100", "sf": 2, "sa": 1, "sn": 1, "sfResumo": 3, "rec": True}       # o resumo dizia 3; os inversores dizem 2
    assert usinas[1] == {"u": "OUTRA", "sf": 9, "sa": 0, "sn": 9}                                    # sem esperadas na conta: fica o resumo


def test_os_inversores_da_api_pv_saem_da_leitura_que_o_ciclo_ja_fez(cli, monkeypatch):
    """Levi, 17/11/2026: "ainda demora 1 século para abrir [...] investigue o motivo dos inversores da API PV demorarem
    tanto e corrija". Cada abertura baixava de novo o dia inteiro da fonte paga; o ciclo já baixa de 5 em 5 min."""
    chamadas = []
    monkeypatch.setattr(app, "_PV_DET_BOOT", 0.0)
    monkeypatch.setattr(app, "_pv_det_cache", {"ts": 0.0, "payload": None})
    # DESLIGADO por padrão desde 17/11 11:36 (a API PV lenta: a chamada a mais do detalhe pesava no disjuntor)
    assert app.os.environ.get("PV_DET_CICLO") == "1" or app.PV_DET_CICLO is False
    monkeypatch.setattr(app, "PV_DET_CICLO", False)
    monkeypatch.setattr(app, "_pv_plant_inversores_busca", lambda pid, force=False, records=None: chamadas.append("nao devia"))
    app._pv_det_guarda(776, [{"idefinversor": 1}])
    assert chamadas == [] and not app._pv_det_cache["payload"]            # desligado: o ciclo não faz nada a mais
    monkeypatch.setattr(app, "PV_DET_CICLO", True)
    monkeypatch.setattr(app, "_pv_plant_inversores_busca", lambda pid, force=False, records=None: chamadas.append((pid, force, len(records))) or [{"id": 1, "nome": "Inversor 1.1"}])
    app._pv_det_guarda(777, [{"idefinversor": 1}])
    assert chamadas == [(777, True, 1)]                                   # monta com as leituras que o ciclo já tem
    r = cli.get("/api/plant/777?tabela=1").get_json()
    assert r["da_tabela"] is True and r["inversores"] == [{"id": 1, "nome": "Inversor 1.1"}] and r["idade_s"] < 5 and len(r["lido_em"]) == 5
    # sem ?tabela=1 a rota segue ao vivo (o Tempo real e o Diagnóstico não mudam); force=1 também
    monkeypatch.setattr(app, "_pv_plant_inversores", lambda pid, force=False: [{"id": 9}])
    assert cli.get("/api/plant/777").get_json() == {"plant_id": 777, "inversores": [{"id": 9}]}
    assert cli.get("/api/plant/777?tabela=1&force=1").get_json() == {"plant_id": 777, "inversores": [{"id": 9}]}
    assert cli.get("/api/plant/778?tabela=1").get_json() == {"plant_id": 778, "inversores": [{"id": 9}]}     # usina sem detalhe: ao vivo
    app._pv_det_cache["payload"]["plantas"]["777"]["ts"] -= app.PV_DET_VALE_S + 1
    assert "da_tabela" not in cli.get("/api/plant/777?tabela=1").get_json()                                # detalhe velho: ao vivo
    # nos primeiros minutos depois da subida o ciclo não calcula o detalhe (a 1ª tabela sai no tempo de sempre)
    monkeypatch.setattr(app, "_PV_DET_BOOT", app.time.time())
    chamadas.clear()
    app._pv_det_guarda(779, [{"idefinversor": 1}])
    assert chamadas == []
    # o detalhe que falha não derruba a linha, e leitura vazia não gera detalhe
    monkeypatch.setattr(app, "_PV_DET_BOOT", 0.0)

    def explode(pid, force=False, records=None):
        raise RuntimeError("combiner fora")
    monkeypatch.setattr(app, "_pv_plant_inversores_busca", explode)
    app._pv_det_guarda(780, [{"idefinversor": 1}])
    app._pv_det_guarda(781, [])
    assert "780" not in app._pv_det_cache["payload"]["plantas"] and "781" not in app._pv_det_cache["payload"]["plantas"]
    assert app._persist_registry()["pv_det"] is app._pv_det_cache                                          # vai junto com as tabelas para o web
    html = _html()
    assert '(PLANT[sk] === "/api/plant/" ? (AOVIVO[u.u] ? "?force=1" : "?tabela=1") : "")' in html and 'data-aovivo="1"' in html
    assert '"2c":"2C · API PV"' in html and "Owen e API PV" not in html


def test_o_detalhe_com_as_leituras_dadas_nao_chama_o_day_inverter(monkeypatch):
    """A montagem do detalhe com `records` usa as leituras do chamador: nenhum POST à API PV."""
    class _SemRede:
        def post(self, *a, **k):
            raise AssertionError("o day_inverter não pode ser chamado de novo")
    monkeypatch.setattr(app, "_http", lambda: _SemRede())
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "t")
    monkeypatch.setattr(app, "get_plants", lambda token: [])
    monkeypatch.setattr(app, "_pv_plant_devices", lambda pid: [])
    assert app._pv_plant_inversores_busca(999001, force=True, records=[]) == []      # sem leitura e sem cadastro: vazio, sem rede


def test_a_leitura_tenta_de_novo_os_trackers_novos_ficam_marcados_e_a_dica_tem_quatro_colunas():
    """Levi, 17/11/2026: a Athon "recusa e depois carrega"; "tem 11 parados [...] citou 2. Quais são os 2?"; e a dica do
    gráfico dos trackers "separado em 4 colunas"."""
    html = _html()
    ler = html[html.index("async function lerUsina(u, calada) {"):html.index("// (g) O que o SCADA da Grid tem desta usina AGORA")]
    assert 'catch (e1) { if (PLANT[sk] === "/api/plant/") throw e1; await new Promise(r => setTimeout(r, 1500)); pl = await pega(urlPl, 90000); }' in ler
    assert "const NOVT = {};" in html and "NOVT[u] = (NOVT[u] || [])" in html                       # os novos guardados ANTES de marcar como vistos
    assert "desde a sua última visita</b>" in html and "nvSet.has(String(x[0])) ? '<span class=\"nv\">novo</span>'" in html
    assert 'nvSet.has(String(x.id)) ? " nvt" : ""' in html and ".tc.nvt{box-shadow:0 0 0 2px var(--critico)}" in html
    assert 'its.length > 60 ? "c4" :' in html and "#dica .cols.c4{columns:4;" in html
