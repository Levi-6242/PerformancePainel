# -*- coding: utf-8 -*-
"""O card Operação no Mês na tela do 5080 (mockup aprovado pelo Levi em 08/10/2026).

Trava o que não pode escapar ao cliente: o card no lugar aprovado (coluna da direita, abaixo da Disponibilidade), só de
10/2026 em diante e pela rota nova, as frases da régua numa cópia só (a do Python), o PDF esperando o Diário inteiro,
o Diário cabendo na folha A4 com o card (sem mexer na impressão de antes de 10/2026) e nada de emoji.

Rodada 2 (08/10, tarde — Ana e Levi): a tabela de Comentários do Diário vira uma linha por dia de 10/2026 em diante
(antes, EXATAMENTE a de sempre), os avisos da rota na nota do card e a aba Metodologia, fora da impressão.

Os testes olham DENTRO da função ou da regra certa (revisão de 08/10: procurar no arquivo inteiro passava com o trecho
em qualquer lugar). A prova de que o Diário cabe na folha é o PDF de verdade (Edge, Ctrl+P e PDF Carteira); aqui fica
a trava de que as regras da folha só valem com o card na tela."""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "thopen"))
import dashboard_thopen as dth  # noqa: E402
import operacao_mes  # noqa: E402

T = open(os.path.join(os.path.dirname(__file__), "..", "thopen", "templates", "dashboard_thopen.html"),
         encoding="utf-8").read()
CSS = T[T.index("<style>"):T.index("</style>")]
EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")


def corpo(nome):
    """O corpo da função JS `nome`, do { ao } que fecha (as chaves dos ${...} se equilibram)."""
    i = T.index("{", re.search(r"function\s+%s\s*\(" % nome, T).end())
    n = 0
    for j in range(i, len(T)):
        n += {"{": 1, "}": -1}.get(T[j], 0)
        if n == 0:
            return T[i:j + 1]
    raise AssertionError("função %s sem fim" % nome)


def regras(css):
    """[(seletor, declarações)] das regras mais internas (as de dentro do @media print também)."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)                  # comentário antes da regra não é seletor
    return [(s.strip(), d) for s, d in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]


def test_layout_da_rodada_4_anual_abaixo_da_disponibilidade_e_card_ao_lado_da_tabela():
    # Levi, 09/10: "Produção de Energia Anual ficará abaixo de disponibilidade e ao lado direito de Energia × Irradiação, e
    # Operação no Mês e Zeladoria ficarão ao lado da tabela de comentários" — só com o card na tela (.com-op). Com o
    # anual em cima também em setembro, a folha saiu com a tabela partida e o gráfico cortado: sem o card, o HTML de
    # antes (o anual ao lado da tabela)
    i_grid2, i_cmt, i_rp, i_anual, i_card = (T.index(x) for x in ('<div class="grid2">', 'id="tblCmt"', 'id="rpCard"',
                                                                  'id="anualCard"', 'id="opCard"'))
    assert i_grid2 < i_cmt < i_rp < i_anual < i_card
    a = corpo("_anualLugar")
    assert "com-op" in a and "$('colDiario').appendChild(card)" in a and "$('opCard').before(card)" in a
    assert "_anualLugar()" in corpo("_opAjusta")
    # rodada 5 (13/10, "lado a lado") e 14/10 ("limita [o gráfico] ao tamanho de Energia Acumulada até Disponibilidade.
    # O resto sobe!"): uma grade só, com o gráfico na altura dos três cards e as tabelas embaixo dele — só com o card
    (dg,) = [d for s, d in regras(CSS) if s == ".com-op .dg"]
    # 15/10/2026: a Zeladoria acima da Produção Anual
    assert ('"graf graf acum" "graf graf irr" "graf graf disp" "cmt rp op" "cmt rp anual" "cmt rp ."' in dg
            and "auto auto auto auto auto 1fr" in dg)                        # a sobra da tabela fica na última linha
    contents = [s for s, d in regras(CSS) if "display:contents" in d.replace(" ", "")]
    assert contents and all("com-op" in x for s in contents for x in s.split(","))
    i_dg, i_graf, i_cx = T.index('<div class="dg">'), T.index('id="grafCard"'), T.index('class="card cx-card"')
    assert i_dg < i_graf < T.index('id="opCard"') < T.index("</div><!-- /.dg -->") < i_cx
    # na folha com o card, barras do anual mais finas: a Altair mandava "Comentários adicionais" sozinho para a 3ª folha
    h = corpo("_anualAltura")
    assert "printing" in h and "com-op" in h and "_anualAltura(a.length)" in corpo("renderAnual")
    ouvintes = re.findall(r"window\.addEventListener\('(?:before|after)print',\(\)=>\{(.*?)\n\}\);", T, re.S)
    assert sum("_anualLugar()" in o for o in ouvintes) == 2           # vai para a folha e volta para a tela


def test_so_a_partir_de_outubro_e_pela_rota_nova():
    r = corpo("renderOperacao")
    assert "ano*100+mes<202610" in r and "/api/t/operacao?" in r


def test_frases_da_regua_nao_sao_repetidas_na_tela():
    # moram só no operacao_mes.REGUA (a rota manda): duas cópias divergem
    assert "Vidro limpo" not in T and "Mato na altura" not in T


def test_pdf_espera_o_diario_inteiro():
    # o PDF Carteira fotografa logo depois do loadUsina: o Diário e o card têm de estar prontos
    assert "await renderDiario(" in corpo("loadUsina")
    assert "await opP" in corpo("renderDiario")


def test_usina_sem_cadastro_nao_vira_sem_leitura_no_mes():
    # revisão de 08/10: a Ouro Branco teve ronda em 09/2026, mas não tem ligação no de-para do Nexus
    r = corpo("renderOperacao")
    assert "sem_cadastro" in r and "sem leitura no mês" in r and "sem leitura nesta ronda" in r


def test_regras_da_folha_so_valem_com_o_card_na_tela():
    # o Diário de antes de 10/2026 (sem o card) imprime exatamente como antes: zoom e flex do gráfico só com .com-op
    r = corpo("renderOperacao")
    assert "classList.add('com-op')" in r and "classList.remove('com-op')" in r
    zooms = [s for s, d in regras(CSS) if re.search(r"(^|;)\s*zoom\s*:", d)]     # a propriedade, não cursor:zoom-in
    assert zooms and all("com-op" in s for s in zooms if s != "body"), zooms
    graf = [s for s, d in regras(CSS) if "#chDiario" in s and "cursor" not in d]   # o cursor do clique é da tela
    assert graf and all("com-op" in s for s in graf), graf
    # o card compacto da folha só existe na impressão (body.printing) — a tela fica a do mockup
    assert [s for s, d in regras(CSS) if s.startswith("body.printing") and ("op-" in s or "zpill" in s)]


def test_impressao_refaz_o_grafico_diario_na_hora():
    # o Plotly.Plots.resize do beforeprint roda 100 ms depois e a folha já saiu: com o card, o relayout é síncrono
    ouvintes = re.findall(r"window\.addEventListener\('beforeprint',\(\)=>\{(.*?)\n\}\);", T, re.S)
    assert any("com-op" in o and "Plotly.relayout" in o for o in ouvintes)


def test_sem_emoji_no_card():
    card = T[T.index('id="opCard"'):T.index('<div class="grid2">')]
    assert not EMOJI.search(card) and not EMOJI.search(corpo("renderOperacao"))


# ── rodada 2: Comentários por dia, avisos e Metodologia ────────────────────────────────────────────────────────────
# As três linhas da tabela de comentários como estavam no HEAD (3d8bd7c) — antes de 10/2026 nada muda nelas.
ANTIGO_THEAD = "<thead><tr><th>Usina</th><th>Data</th><th>Comentário</th></tr></thead>"
ANTIGO_VAZIO = "if(!d.comentarios.length){ tb.innerHTML='<tr><td colspan=3 class=muted>Sem comentários no mês</td></tr>'; }"
ANTIGO_LINHAS = ("else tb.innerHTML=d.comentarios.map(c=>`<tr><td>${OV.nome||usina}</td><td>${c.data}</td>"
                 "<td>${c.com||''}</td></tr>`).join('');")


def test_tabela_de_antes_de_outubro_e_a_de_sempre():
    assert ANTIGO_THEAD in T                                    # o cabeçalho estático do HTML não mudou
    antigo = corpo("_cmtAntigo")
    assert ANTIGO_VAZIO in antigo and ANTIGO_LINHAS in antigo
    # a escolha: antes de 10/2026 → a tabela de sempre. De 10/2026 em diante, sem o card na tela (desligado, erro da
    # rota), a tabela diz que as OS estão indisponíveis — nunca volta ao comentário da equipe (Levi, 14/10/2026: "A
    # partir de outubro quero os comentários 100% OS Fracttal. Antes deixe como estava!")
    r = corpo("renderCmt")
    assert "if(ano*100+mes<202610){ _cmtAntigo(tbl, usina, d);" in r and r.count("_cmtAntigo(") == 1
    assert "if(!op){ _cmtAviso(tbl, 'Comentários pelas OS do Fracttal indisponíveis no momento.')" in r
    # e a volta para ela devolve o cabeçalho de 3 colunas guardado do próprio HTML, sem class="" sobrando
    assert "_CMT_THEAD=$('tblCmt').tHead.innerHTML" in T
    assert "tHead.innerHTML=_CMT_THEAD" in antigo and "removeAttribute('class')" in antigo
    assert "renderCmt()" in corpo("renderOperacao")


def test_tabela_por_dia_de_outubro_em_diante():
    n = corpo("_cmtPorDia")
    # rodada 5 (Levi, 13/10): Comentários = Usina | Data | Comentário | Disponibilidade
    assert ("'<tr><th>Usina</th><th>Data</th><th>Comentário</th><th class=\"op-n\">Disponibilidade</th></tr>'"
            in corpo("_cmtCabeca")) and "_cmtCabeca(tbl)" in n and "colspan=4" in n and "_opFrase" not in T
    # a disponibilidade sai com "%" no valor (Levi: "poderia botar um % no final")
    assert "+'%'" in n
    # entra o dia abaixo de 100%, com as OS dele; o comentário da equipe (pontos[].com) nem é lido (14/10, noite)
    assert "if(r.disp==null||r.disp>=100) return;" in n and "Object.keys(com)" in n and "p.com" not in n
    assert "d.pontos" not in n
    assert "Ronda realizada" not in n and "pd[n].ronda" not in n and "op.trackers" not in n   # foram para a outra tabela
    assert "_cmtGrupos(dias, com, val)" in n                             # dias iguais e seguidos viram "01 a 05/10"
    assert "_opEsc(x)" in n and "g.c.split(" in n                        # texto do BD escapado, linha a linha
    # a tabela espera o card no Diário (o PDF Carteira fotografa a tabela pronta)
    d = corpo("renderDiario")
    assert d.index("await opP") < d.index("renderCmt()")


def test_ronda_e_performance_ao_lado_dos_comentarios():
    r = corpo("_rpPorDia")
    # Data | Vegetação | Sujidade | Trackers | Strings — o dia com ronda, tracker parado ou string sem corrente
    assert "'<tr><th>Data</th><th>Vegetação</th><th>Sujidade</th>'" in r
    assert '<th class="op-n">Trackers<span class="op-sub">Parados</span></th>' in r
    assert '<th class="op-n">Strings<span class="op-sub">Sem corrente</span></th>' in r
    assert "(r.strings||0)>0||(r.trackers||0)>0||r.ronda" in r and "colspan=5" in r
    # o nível na cor da régua, com a frase dela no título; "—" sem ronda
    assert 'class="rp-n z${+v}"' in r and "op.regua" in r and "rp-sem" in r
    # dia fora do por_dia: 0 quando o mês tem número no card, "—" quando não tem (nunca o zero falso)
    assert "op[k]!=null?0:null" in r and "_cmtNada(dias, pd, op, ano, mes, 'rp')" in r
    # a tabela só existe com o card: antes de 10/2026, sem o card ou com erro, some (o Diário de antes)
    c = corpo("renderCmt")
    assert "$('rpCard').classList.remove('hidden')" in c and c.count("$('rpCard').classList.add('hidden')") == 3
    assert "$('rpCard').classList.add('hidden')" in corpo("renderOperacao")


def test_avisos_da_rota_na_nota_da_tabela_ronda_e_performance():
    # 15/10/2026 (o card é só a Zeladoria): os avisos das strings e a origem de strings e trackers foram para a nota da
    # tabela que mostra os números
    r = corpo("_rpPorDia")
    assert "op.avisos" in r and "op-aviso" in r and "_opEsc(" in r
    # rodada 2: as strings vêm das OS — a nota não pode mais dizer que é a régua de 2 h
    assert "2 h seguidas" not in r and "OS de recomposição de string" in r
    o = corpo("renderOperacao")
    assert "d.avisos" not in o and "op-aviso" not in o and "Strings:" not in o


def _metodologia(html):
    return html[html.index('id="pageMetodologia"'):html.index("PÁGINA VISÃO GERAL")]


def test_metodologia_e_a_aba_depois_do_diario_sem_o_seletor_de_usina():
    assert T.index('data-page="diario"') < T.index('data-page="metodologia"') < T.index('id="fldCarteira"')
    assert 'id="pageMetodologia"' in T
    nav = T[T.index("document.querySelectorAll('.tab').forEach(t=>t.onclick"):T.index("async function init(")]
    assert "$('pageMetodologia').classList.toggle('hidden',p!=='metodologia')" in nav
    (linha,) = [x for x in nav.splitlines() if "$('fldUsina')" in x]
    assert "p==='metodologia'" in linha


def test_metodologia_fica_fora_do_ctrl_p_e_do_pdf_carteira():
    # a folha do cliente não muda: a Metodologia é tela de consulta
    prints = [(sel, dec) for sel, dec in regras(CSS) if "#pageMetodologia" in sel]
    assert ("#pageMetodologia", " display:none !important; ") in prints
    for f in ("printRelatorioCarteira", "_snapPage", "_capUsinaPDF", "printAllUsinas"):
        assert "pageMetodologia" not in corpo(f), f
    for sel, dec in regras(CSS):
        if "display:block" in dec:
            assert "Metodologia" not in sel, sel


def test_frases_da_regua_na_metodologia_vem_do_python():
    # uma cópia só (operacao_mes.REGUA): o template não tem frase de nível, o render_template as põe
    html = dth.app.test_client().get("/").data.decode("utf-8")
    met = _metodologia(html)
    for k, niveis in operacao_mes.REGUA.items():
        for n, frase in niveis.items():
            # duas vezes desde 26/10/2026: a régua da Metodologia e a "Como classificamos" da aba Zeladoria, as duas
            # vindas do Python
            assert frase not in T and html.count(frase) == 2 and frase in met, (k, n)
    assert met.index(operacao_mes.REGUA["sujidade"][5]) < met.index(operacao_mes.REGUA["sujidade"][1])   # 5 no topo
    assert "regua.sujidade[n]" in T and "regua.vegetacao[n]" in T


def test_texto_da_metodologia_da_rodada_2():
    met = _metodologia(T)
    for trecho in ("OS de recomposição de string", "data do evento", "Strings sem corrente: N", "strings citadas",
                   "outubro de 2026", "completadas pela Grid", "a usina comunicou", "A CONFIRMAR"):
        assert trecho in met, trecho
    assert "2 horas seguidas sem corrente" not in met              # a régua antiga das strings saiu do texto
    assert not EMOJI.search(met)


def test_metodologia_disponibilidade_so_das_os_sem_geracao():
    # Levi, 15/10/2026: "disponibilidade é full Fracttal, isolada da geração". Até então o bloco dizia ao cliente que o
    # dia em que a geração mostrava a usina funcionando não contava, mesmo com a OS aberta — a regra que saiu
    met = _metodologia(T)
    bloco = met[met.index("<h3>Disponibilidade</h3>"):met.index("<dt>Antes de 10/2026")]
    for trecho in ("religamento remoto", "corretiva emergencial", "de 06h a 18h", "as OS fechadas e as abertas",
                   "a OS ainda aberta, sem data final, conta até o último dia fechado", "data de criação",
                   "anterior até à criação, a OS não conta", "a geração não entra nela", "Dia sem OS = 100%",
                   "falta de comunicação não é usina parada"):
        assert trecho in bloco, trecho
    assert "geração mostra" not in bloco and "não é parada" not in bloco
    assert "anterior ao evento" not in bloco, "'evento' é jargão do Fracttal: o cliente lê 'início da parada'"


def test_sem_emoji_na_tabela_por_dia():
    for f in ("_cmtPorDia", "_cmtAntigo", "renderCmt"):
        assert not EMOJI.search(corpo(f)), f


def test_folha_a4_da_tabela_por_dia_so_com_o_card():
    # 31 dias não cabem numa folha com o Diário: a linha fica compacta só na impressão e só com o card (.com-op), sem
    # partir linha; a tela e o Diário de antes de 10/2026 não mudam
    i = CSS.index(".com-op #tblCmt.por-dia th, .com-op #tblCmt.por-dia td")
    assert CSS.rfind("@media print{", 0, i) > CSS.rfind("}\n  }", 0, i)          # dentro de um @media print
    folha = [(s, d) for s, d in regras(CSS) if "por-dia" in s and ("padding:2px" in d or "break-inside" in d
                                                                      or "box-decoration-break" in d)]
    assert len(folha) == 3 and all(s.startswith(".com-op") for s, d in folha), folha


def test_impressao_refaz_os_tres_graficos_do_diario_com_o_card():
    # o Plotly.Plots.resize do beforeprint roda 100 ms depois: no PDF, "Energia acumulada" saiu sem a barra da Meta
    ouvintes = re.findall(r"window\.addEventListener\('beforeprint',\(\)=>\{(.*?)\n\}\);", T, re.S)
    (o,) = [x for x in ouvintes if "Plotly.relayout" in x]
    assert "com-op" in o and all(g in o for g in ("'chDiario'", "'chAcum'", "'chAnual'"))


# ── Dias iguais e seguidos numa linha só (Levi, 08/10/2026: "quando for o mesmo valor para vários dias só irá repetir
# tipo 'Dia 1 a 5' 1 string sem corrente, 5 trackers parados"). A conta roda no node com o MESMO código do HTML.
import json  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402

import pytest  # noqa: E402

NODE = shutil.which("node")


def _grupos(dias, com, vals):
    """vals = {dia: (strings, trackers)} já como texto da célula, como o `cel` da tabela devolve."""
    if not NODE:
        pytest.skip("node não instalado")
    fn = T[T.index("function _cmtGrupos("):T.index("/* fim _cmtGrupos */")]
    # vals[dia] = (strings, trackers[, disp[, ronda]]) — a rodada 4 compara também a disponibilidade e a ronda
    js = (fn + "\nconst V=%s;\nconst I={strings:0,trackers:1,disp:2,ronda:3};\n"
          "process.stdout.write(JSON.stringify(_cmtGrupos(%s, %s, (n,k)=>I[k]<V[n].length?V[n][I[k]]:'')));"
          % (json.dumps(vals), json.dumps(dias), json.dumps(com)))
    r = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return [(g["ini"], g["fim"], g["c"], g["s"], g["t"], g["cont"]) for g in json.loads(r.stdout)]


def test_dias_seguidos_com_os_mesmos_numeros_viram_uma_linha():
    v = {n: ("1", "5") for n in range(1, 6)}
    assert _grupos([1, 2, 3, 4, 5], {}, v) == [(1, 5, "", "1", "5", False)]


def test_numero_diferente_ou_dia_faltando_quebra_a_sequencia():
    v = {1: ("1", "5"), 2: ("1", "5"), 3: ("1", "6"), 5: ("1", "6")}
    assert _grupos([1, 2, 3, 5], {}, v) == [(1, 2, "", "1", "5", False), (3, 3, "", "1", "6", False),
                                            (5, 5, "", "1", "6", False)]


def test_mesmo_comentario_agrupa_e_comentario_diferente_separa():
    v = {n: ("0", "2") for n in range(1, 5)}
    com = {"1": "Desligamento UG 2", "2": "Desligamento UG 2", "3": "Outro evento"}
    com = {int(k): t for k, t in com.items()}
    assert _grupos([1, 2, 3, 4], com, v) == [(1, 2, "Desligamento UG 2", "0", "2", False),
                                            (3, 3, "Outro evento", "0", "2", False), (4, 4, "", "0", "2", False)]


def test_mesmo_comentario_com_numeros_diferentes_vira_continua():
    v = {1: ("4", "3"), 2: ("0", "0")}
    com = {1: "Furto de cabos", 2: "Furto de cabos"}
    assert _grupos([1, 2], com, v) == [(1, 1, "Furto de cabos", "4", "3", False),
                                       (2, 2, "Furto de cabos", "0", "0", True)]


def test_card_e_so_a_zeladoria():
    # Levi, 15/10/2026: "Desse card tire OPERAÇÃO DO MÊS, deixe só zeladoria!" — strings e trackers ficam na tabela
    card = T[T.index('id="opCard"'):T.index('id="opNota"')]
    assert "Operação no Mês" not in card and "Strings sem corrente" not in card and "Trackers parados" not in card
    assert 'id="opZt">Zeladoria<' in card and 'id="opZel"' in card and 'id="opFotos"' in card
    assert "opStr" not in T and "opTrk" not in T


def test_o_valor_do_grafico_diario_vem_com_a_unidade_e_sem_o_dia():
    # Levi, 15/10/2026: "ao passar o mouse na coluna não precisa mostrar o dia mas precisamos da unidade de medida
    # certa" — o Plotly dizia "(9, 31.2495k)"; agora "31.249,5 kWh". Desde 26/10/2026 o desenho mora no _desenhaDiario
    d = corpo("_desenhaDiario")
    # 4 = barras, a linha esperada pelo IPOA (20/10/2026), a da irradiação (sem kWp ou PR na meta) e a meta
    assert d.count("hovertemplate:'%{customdata}<extra></extra>'") == 4 or d.count("hovertemplate:_HOV") == 5
    assert "fmt(p.ger,1,'kWh')" in d and "fmt(p.ipoa,2,'kWh/m²')" in d and "'Meta '+fmt(d.meta_dia,0,'kWh')" in d
    assert "const fmt=_fmtU;" in d and "const _fmtU=(v,c,u)=>v==null?'—':v.toLocaleString('pt-BR'" in T


def test_o_valor_com_a_unidade_em_todos_os_graficos():
    # Levi, 15/10/2026: "Precisa ajustar o valor e unidade de medida nessas colunas também ao passar o mouse!" — a
    # Produção Anual dizia "(3.343983M, Meta 2026)" e a Energia Acumulada "(Meta, 379.7882k)"
    assert "customdata:a.map(d=>_fmtU(d.valor,0,'kWh')), hovertemplate:_HOV" in corpo("renderAnual") or         "customdata:a.map(d=>_fmtU(d.valor,0,'kWh')), hovertemplate:_HOV" in T
    assert "customdata:[_fmtU(k.acum_prod,0,'kWh'),_fmtU(k.acum_meta,0,'kWh')], hovertemplate:_HOV" in T
    m = corpo("renderMensal")
    assert "nome+': '+_fmtU(v,1,'MWh')" in m and m.count("hov('") == 5
    # os quatro gráficos com o valor e a unidade: o Diário (três séries) e Mensal, Anual e Acumulada pelo _HOV
    assert T.count("Plotly.react(") == 4 and T.count("hovertemplate:_HOV") == 3 and T.count("const _HOV=") == 1


def test_disponibilidade_e_ronda_tambem_separam_os_dias():
    # dias seguidos só viram uma linha com a MESMA disponibilidade; dia com ronda é evento do dia e não junta
    v = {1: ("0", "1", "100,0%"), 2: ("0", "1", "100,0%"), 3: ("0", "1", "95,8%"),
         4: ("0", "1", "95,8%", "Ronda realizada: vegetação nível 3"), 5: ("0", "1", "95,8%")}
    assert [(a, b) for a, b, *_ in _grupos([1, 2, 3, 4, 5], {}, v)] == [(1, 2), (3, 3), (4, 4), (5, 5)]


def test_disponibilidade_do_mes_pela_regua_do_gerencial_so_de_outubro():
    d = corpo("renderDiario")
    assert "ano*100+mes>=202610" in d and "op.disponibilidade" in d
    assert d.index("await opP") < d.index("op.disponibilidade")


def test_zeladoria_e_titulo_com_a_letra_do_card():
    zt = [d for s, d in regras(CSS) if s == ".op-zt"][0]
    assert "font-size:12px" in zt and "font-weight:700" in zt and "color:#555" in zt
    assert "op-zsub" in corpo("renderOperacao") and "Zeladoria · ronda" not in corpo("renderOperacao")


def test_icone_das_rondas_no_card_e_fora_de_todo_pdf():
    card = T[T.index('id="opCard"'):T.index('id="opNota"')]
    assert 'id="opFotos"' in card and 'aria-label="Fotos das rondas do mês"' in card
    fora = " | ".join(s for s, d in regras(CSS) if "display:none" in d.replace(" ", ""))
    # Baixar PDF é html2canvas (não lê @media print): o body.printing também esconde
    assert "body.printing .op-fotos" in fora and "#printArea .op-fotos" in fora and ".rd-fundo" in fora


def test_janela_so_mostra_o_que_a_rota_manda_e_escapa_tudo():
    j = corpo("_rdDesenha") + corpo("_rdLinha") + corpo("_rdFotos")
    assert j.count("_opEsc(") >= 6 and "fotos_erro" in j and "it.obs" in j          # o tipo de sujidade junto do nível
    # nenhuma foto fica inalcançável: as além da 2ª ficam atrás do "+N" (OS 15910: 39 fotos, 21 apareciam)
    assert "rd-mais" in corpo("_rdFotos") and ".slice(0,2)" not in corpo("_rdFotos")
    for proibido in ("tecnico", "qualidade", "pendencia", "gps", "observa"):
        assert proibido not in j.lower(), proibido


def test_rondas_pela_lista_e_detalhe_pelas_rotas():
    assert "/api/t/rondas?" in corpo("abrirRondas") and "/api/t/ronda/" in corpo("_rdAbre")
    assert "seq!==_rd.seq" in corpo("_rdAbre")              # trocar de ronda no meio não desenha a antiga


def test_contestacao_pelo_dia_do_grafico():
    # rodada 5 (Levi, 13/10): "ao invés de ficar pelas tabelas bote para contestar no gráfico de geração e
    # irradiação"; ronda → Zeladoria, o resto (geração desde a rodada 5) → Performance
    assert 'id="rdDuv"' not in T and "enviarDuvida" not in T and "/api/t/duvida" not in T
    assert "cmt-ct" not in T and "_cmtLinhas" not in T                  # o "!" das tabelas saiu
    assert "ch.on('plotly_click',_ctClique)" in corpo("renderDiario")
    assert "abrirContestacao(n)" in corpo("_ctClique")
    a = corpo("abrirContestacao")
    assert "i.disabled=!on" in a and "_CT_CANAL" in a                  # item sem canal configurado fica desligado
    assert "o.ano*100+o.mes<202610" in a and ">hoje" in a               # de 10/2026 em diante e nunca dia futuro
    assert "geracao:" in a and "irradiacao:" in a and "pt.ger" in a     # o que o gráfico mostrava naquele dia
    assert '<input type="checkbox" value="geracao">Geração' in T and "geracao:'performance'" in T
    e = corpo("enviarContestacao")
    assert "/api/t/contestar" in e and "dia_ini:_ct.dia" in e and "site:" in e and "tela:_ct.tela" in e
    assert 'id="ctSite"' in T and "rd-isca" in T                      # campo-isca contra robô
    # a dica e o cursor só com o card e com canal; fora de todo PDF
    c = corpo("renderCmt")
    assert "$('ctDica').classList.toggle('hidden',!pode)" in c and "ano*100+mes>=202610" in c
    fora = " | ".join(s for s, d in regras(CSS) if "display:none" in d.replace(" ", ""))
    assert "body.printing .ct-dica" in fora and "#printArea .ct-dica" in fora and "#ctFundo" in fora


def test_sem_emoji_na_janela():
    assert not EMOJI.search(T[T.index('id="rdFundo"'):])


# ── 13/10 (Levi): dia abaixo de 100% sem comentário "não pode acontecer"; e a nota dos dias que não aparecem ─────────
def test_comentario_de_outubro_em_diante_e_so_das_os_do_fracttal():
    # 14/10/2026, noite (Levi: "A partir de outubro quero os comentários 100% OS Fracttal. Comentários e
    # disponibilidade!"): o dia abaixo de 100% leva só as OS que formaram a disponibilidade dele (por_dia[].os, a
    # parcela de cada OS na conta do Gerencial); a linha da OS não tem mais estilo próprio
    n = corpo("_cmtPorDia")
    assert "com[n]=r.os==null?_CMT_SEM_PUB:(r.os.length?r.os.join(" in n
    assert "doOS" not in T and "cmt-os" not in T and '<div class="cmt-an">${_opEsc(x)}</div>' in n
    assert "O registro das OS do Fracttal deste dia ainda não foi publicado." in T      # os null: a parcela não chegou
    # a usina sem a disponibilidade do Gerencial não ganha um "100%" inventado; o card carregando também não
    assert "Sem a disponibilidade pelas OS do Fracttal para esta usina no mês." in n
    assert "Atualizando os dados de operação." in n
    assert "_cmtNada(dias, pd, op, ano, mes, 'cmt')" in n and 'class="cmt-nada"' in n
    # as bolinhas do gráfico Energia × Irradiação seguem a tabela (os dias com OS), e a contestação leva só as OS
    assert "_cmtBolinhas(_cmtPorDia(" in corpo("renderCmt") and "'xaxis.ticktext'" in corpo("_cmtBolinhas")
    assert "comentario:(r.os||[]).join(" in corpo("abrirContestacao") and "pt.com" not in T


def _nada(dias, pd, op, tipo="cmt", ano=2026, mes=10):
    if not NODE:
        pytest.skip("node não instalado")
    fn = T[T.index("function _cmtNada("):T.index("function _cmtGrupos(")]
    js = (fn + "\nprocess.stdout.write(JSON.stringify(_cmtNada(%s, %s, %s, %d, %d, %s)));"
          % (json.dumps(dias), json.dumps(pd), json.dumps(op), ano, mes, json.dumps(tipo)))
    r = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_nota_dos_dias_sem_ocorrencia_so_ate_o_ultimo_dia_fechado():
    # Álvares Machado, 01 a 12/10: 04 a 07 nos Comentários; o 13 (hoje), ainda sem a disponibilidade fechada, não entra
    pd = {str(n): {"disp": 100.0} for n in range(1, 13)}
    pd.update({"4": {"disp": 94.2}, "5": {"disp": 22.2}, "6": {"disp": 25.9}, "7": {"disp": 99.7}, "13": {"disp": None}})
    op = {"strings": 0, "trackers": None, "parcial_ate": "13/10", "zeladoria": {"sem_cadastro": True}}
    assert _nada([4, 5, 6, 7], pd, op) == ("Os dias 01 a 03 e 08 a 12/10 não aparecem na tabela porque não tiveram "
                                           "OS de desligamento no Fracttal (disponibilidade de 100%).")
    # Ronda e Performance: só o que foi medido — sem cadastro das rondas e sem tracker monitorado, só a string
    assert _nada([], pd, op, "rp") == ("Os dias 01 a 12/10 não aparecem na tabela porque não tiveram string sem "
                                       "corrente.")
    assert _nada([2], pd, dict(op, trackers=3, zeladoria={}), "rp") == (
        "Os dias 01, 03 a 12/10 não aparecem na tabela porque não tiveram ronda, tracker parado nem string sem corrente."
    ).replace("01, 03 a 12", "01 e 03 a 12")


def test_nota_sem_a_disponibilidade_nao_diz_100_e_dia_isolado():
    op = {"strings": 0, "trackers": 0, "parcial_ate": "06/10", "zeladoria": {}}
    assert _nada([1, 2, 3, 4], {}, op) == ("O dia 05/10 não aparece na tabela porque não teve OS de desligamento no "
                                           "Fracttal.")
    assert _nada([1, 2, 3, 4], {}, op, "rp") == ("O dia 05/10 não aparece na tabela porque não teve ronda, tracker "
                                                 "parado nem string sem corrente.")
    assert _nada([1, 2], {}, {"strings": None, "trackers": None, "parcial_ate": "04/10",
                              "zeladoria": {"sem_cadastro": True}}, "rp") == (
        "O dia 03/10 não aparece na tabela porque não teve ocorrência registrada.")
    assert _nada([1, 2, 3], {}, dict(op, parcial_ate="04/10")) == ""


def test_unidade_do_titulo_fica_como_se_escreve():
    # Levi, 13/10: "está em caps lock, troque por kWh e kWh/m²" — o .card h3 é caixa alta; a unidade fica fora
    assert [d for s, d in regras(CSS) if s == ".card h3 .un"] == [" text-transform:none; "]
    for h3 in re.findall(r"<h3>([^<]*(?:<span[^>]*>[^<]*</span>[^<]*)*)</h3>", T):
        if "kWh" in h3:
            assert re.sub(r'<span class="un">\([^)]*\)</span>', "", h3).count("kWh") == 0, h3


def test_a_linha_sempre_diz_o_motivo_sem_continua():
    # Levi, 14/10: "Como assim continua? preciso de um motivo que faça sentido esse valor de 80%"
    n = corpo("_cmtPorDia")
    assert ">continua<" not in n and "cmt-cont" not in n and "g.cont" not in n and "g.c.split(" in n


def test_linha_da_nota_quebra_o_texto_e_nao_estica_a_tabela():
    # 14/10 (Levi: "o comentário de Álvares Machado está passando da caixa de ronda e performance"): o nowrap da 1ª
    # coluna pegava a linha única da nota; a linha com colspan quebra o texto
    regra = [d for s, d in regras(CSS) if "td[colspan]" in s]
    assert regra and "white-space:normal" in regra[0].replace(" ", "")


def test_zero_da_irradiacao_casa_com_o_zero_da_geracao():
    # 14/10: "o zero do IPOA deve sempre casar com o zero de geração" (Assis, IPOA 0 o mês todo: eixo de -1 a 1)
    d = corpo("_desenhaDiario")
    assert "rangemode:'nonnegative'" in d and "autorange:false" in d and "range:[0,(Math.max(0,...d.pontos" in d
    assert "rangemode:'nonnegative'" in corpo("renderMensal")


def test_sair_na_faixa_do_topo_e_contestacao_so_com_o_nome():
    # Levi, 15/10/2026: "não tem um botão de sair da conta no dashboard thopen" — no fim da barra de botões ele saía da
    # tela nas janelas estreitas; agora fica na faixa do topo, ao lado da marca (e a faixa some na impressão)
    topo = T[T.index('id="topHeader"'):T.index('<div class="toolbar">')]
    assert 'id="usuarioBox"' in topo and 'id="usuarioSair">Sair</a>' in topo and 'class="topo-dir"' in topo
    assert T.count('id="usuarioBox"') == 1
    # "com a pessoa conectada, na contestação a pessoa não precisa preencher o e-mail, só o nome!"
    a = corpo("abrirContestacao")
    assert "$('ctCont').closest('label').style.display=USUARIO?'none':''" in a and "$('ctNome').readOnly=false" in a
