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


def test_nada_mais_fica_escondido_nem_de_mentira():
    """Entrega 3 (16/11/2026): o sino, as abas Abaixo dos demais, Geração e PR, Potência, Conferir fontes e De-para e o
    cartão do Novo deixam de ser escondidos, e nenhum botão responde "no mockup"."""
    html = _html()
    assert "display:none !important}" not in html[html.index("/* quem só lê") - 400:html.index("/* quem só lê")]
    assert ".prio .pc:first-child{display:none}" not in html and '<div class="nota">' not in html
    assert "data-mock" not in html and "Neste mockup" not in html and "no mockup" not in html
    for aba in ('aba("bx", "Abaixo dos demais"', 'aba("gp", "Geração e PR")', 'aba("pot", "Potência")',
                'aba("cf", "Conferir fontes")', 'aba("dp", "De-para")'):
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
    montar = html[html.index("function montar(ent, fal, idr, vis) {"):html.index("let ABX = null")]
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
        def descobrir():
            pedidos.append("lista")
            return [{"id": "usina_dupla", "nome": "Usina Dupla 1 e 2", "via": "mqtt", "inv_total": 2}]

        @staticmethod
        def get(rota):
            pedidos.append(rota)
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
    assert pedidos == ["lista", "/api/mqtt/usina_dupla"]
    fora = cli.get("/api/sala/conferir?usina=Outra&fonte=pg").get_json()
    assert fora["situacao"] == "fora_do_scada" and fora["scada_nomes"] == ["Usina Dupla 1 e 2"]
    assert pedidos == ["lista", "/api/mqtt/usina_dupla"]             # a lista vale 10 min; usina fora não chama o SCADA
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
