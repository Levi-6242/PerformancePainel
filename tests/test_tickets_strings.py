# -*- coding: utf-8 -*-
"""Tickets de STRINGS na tabela do Tempo Real (Levi, 23/09/2026).

O pedido: *"mostrasse o total de strings com ticket aberto por usina, e quando abre a usina mostra
qual string que está com esse ticket"*, no molde da coluna "Tickets" dos trackers.

A fonte é a aba "Strings indisp" (sheet 128) da planilha de tickets, a mesma que a tela de Tickets do
OS Creator lê e grava. A estrutura dela é outra que a de trackers, e é daí que vem cada regra abaixo:

  - uma linha por ticket de INVERSOR, com a QUANTIDADE de strings afetadas. Aberto = "Fim da
    ocorrência" vazio (em 23/09: 82 abertos, 616 strings);
  - QUAL string só aparece no texto dos comentários, quando o ticket nasce de OS do OS Creator
    ("Ipv11 e Ipv12 com corrente nula em 01/09/2026"). Em 23/09, 19 dos 82. Os outros 63 dizem só o
    inversor, e aí a string zerada do inversor fica "coberta pelo ticket do inversor";
  - a coluna Usina mistura nome e CÓDIGO (ALT100, ADS100, EBG100). O de-para está na própria
    planilha, aba "Base de dados - Usinas" (THPN-ALT100 = Altair);
  - "X 1 e 2" é uma linha para duas usinas da plataforma. O 1º número do inversor diz de qual é
    ("Inversor 2.5" → X 2).
"""
import io
import json

import openpyxl
import pytest

import app

COLS_STR = ["", "Usina", "Código da usina", "Cliente", "UF", "Supervisor", "Responsável", "Inversor",
            "Quantidade de strings no inversor", "Quantidade de strings no afetadas", "Causa raiz",
            "Responsabilidade da Grid Co.?", "Início da ocorrência", "Início do chamado pela Grid Co.",
            "Fim da ocorrência", "Indisponibilidade (horas)", "Indisponibilidade da Grid Co. (horas)",
            "Comentários para os clientes", "Comentários gerais"]
# (usina, inversor, no inversor, afetadas, causa, início, fim, comentário geral)
LINHAS_STR = [
    ("ALT100", "Inversor 1.7", 20, None, None, "2026-09-01 06:00", None, "Ipv11 e Ipv12 com corrente nula em 01/09/2026 06:00"),
    ("ALT100", "Inversor 5.6", 20, None, None, "2026-09-01 06:00", "2026-09-10 12:00", "Ipv7 com corrente nula"),  # FECHADO
    ("Crateus", "Inversor 1.1", 9, 9, "Furto", "2026-08-25 05:00", None, "28/08: Usina foi furtada no dia 25/08."),
    ("Santarem 1 e 2", "Inversor 2.5", 20, 1, None, "2026-07-11 06:00", None, "22/07: aguardando cabos CC"),
    ("Santarém 1", "Inversor 1.1", 20, 1, "Cabo rompido", "2026-05-04 06:00", None, "13/08: OS 9876."),
    ("Sitio dos Nogueiras", "Inversor 2.3", 18, 2, None, "2026-09-10 08:00", None, "Strings Ipv3 e Ipv4 zeradas"),
    ("Sitio dos Nogueiras", "Geral", 18, 1, None, "2026-09-12 08:00", None, "a verificar"),
    ("Demerval Lobao", "Inversor 1.2", 10, 3, None, "2026-08-01 06:00", None, ""),   # usina fora da plataforma
    ("Brodowski", "Todos", 209, 209, "Furto de Cabos", "2026-09-02 06:00", None, "UFV off após furto de cabos"),
    ("Embu Guaçu", "Inversor 1.1", 20, 1, None, "2026-09-15 06:00", None, "String 3 com corrente nula"),  # NOME, não código
]
COLS_USINAS = ["", "Usina", "Código da usina", "Código curto da usina", "Cliente", "UF", "Status", "Supervisor(a)"]
USINAS = [("Altair", "THPN-ALT100", None, "Thopen", "Sao Paulo", "OPERAÇÃO", "Camila Viana"),
          ("Embu Guaçu", "THPN-EBG100 ", None, "Thopen", "Sao Paulo", "OPERAÇÃO", "Danuth Fernandes")]


COLS_DIARIO = ["quando", "quem", "aba", "linha", "impressao", "Causa raiz", "Responsabilidade da Grid Co.?",
               "Início da ocorrência", "Início do chamado pela Grid Co.", "Fim da ocorrência", "Comentários gerais", "OS",
               "Ativo", "Status do ticket"]


def _reg(linha, impressao, quando="2026-09-20 10:00:00", **campos):
    """Um registro do diário do OS Creator ("Edicoes do app v3"). Campo que não vem fica vazio (= não registrado)."""
    return [quando, "Levi Maia", "Strings", linha, impressao] + [campos.get(c, "") for c in COLS_DIARIO[5:]]


def _data(v, reais):
    """Como o espelho grava (bd_api._valor): texto ISO vira DATA de verdade no .xlsx, e a coluna chega ao pandas como
    datetime, com a célula vazia em NaT (não NaN). 23/09/2026: o leitor novo tratava o NaT como texto "NaT", dava TODO
    ticket por fechado e a bancada leu 0 abertos de 82. A fixture em texto não pegava."""
    import datetime as _d
    import re as _re
    if not reais or not isinstance(v, str) or not _re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", v.strip()):
        return v
    return _d.datetime.strptime(v.strip()[:16], "%Y-%m-%d %H:%M")


def _planilha(diario=None, datas_reais=False, diario_com_cabecalho=False) -> io.BytesIO:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Strings indisp"
    for _ in range(3):
        ws.append(["rascunho"])            # cabeçalho na linha 4, como na real (header=3)
    ws.append(COLS_STR)
    for u, inv, n_inv, afet, causa, ini, fim, com in LINHAS_STR:
        ini, fim = _data(ini, datas_reais), _data(fim, datas_reais)
        ws.append(["", u, 0, "", "", "", "", inv, n_inv, afet, causa, None, ini, ini, fim, None, None, "", com])
    wu = wb.create_sheet("Base de dados - Usinas")
    for _ in range(3):
        wu.append(["rascunho"])
    wu.append(COLS_USINAS)
    for linha in USINAS:
        wu.append([""] + list(linha))
    if diario is not None:
        # Como o ESPELHO real materializa a aba que o OS Creator criou pela API (medido em 23/09/2026): a API declara o
        # cabeçalho na linha 1 e devolve o 1º registro TAMBÉM com row_number 1. O bd_api grava cada linha na sua
        # posição e só escreve o cabeçalho se a linha dele estiver livre — então a aba chega SEM cabeçalho, com o 1º
        # registro na linha 1. Ler com header=0 fazia desse registro o cabeçalho, e nenhum campo casava.
        wd = wb.create_sheet("Edicoes do app v3")
        if diario_com_cabecalho:
            wd.append(COLS_DIARIO)
        for r in diario:
            wd.append([_data(v, datas_reais) if i >= 5 else v for i, v in enumerate(r)])
    b = io.BytesIO()
    wb.save(b)
    b.seek(0)
    return b


def _carregar(monkeypatch, diario=None, datas_reais=False, diario_com_cabecalho=False):
    monkeypatch.setattr(app, "_bd_readable",
                        lambda chave=None, fallback=None: _planilha(diario, datas_reais, diario_com_cabecalho))
    monkeypatch.setattr(app, "_tickets_marca", lambda: 1.0)
    monkeypatch.setattr(app, "TICKETS_STR", {})
    app.load_tickets_strings()
    return app.TICKETS_STR


@pytest.fixture
def tickets(monkeypatch):
    return _carregar(monkeypatch)


# ── o leitor ──────────────────────────────────────────────────────────────────

def test_so_ticket_aberto_entra(tickets):
    alt = tickets["altair"]
    assert [t["inversor"] for t in alt] == ["Inversor 1.7"], "o ticket fechado (Fim preenchido) não cobre nada"


def test_codigo_vira_nome_pela_aba_de_usinas(tickets):
    """ALT100 é o Altair: a própria planilha diz (THPN-ALT100). Sem isto, 13 tickets do Altair sumiam."""
    assert "altair" in tickets and "alt100" not in tickets
    assert tickets["altair"][0]["usina_planilha"] == "ALT100"


def test_as_strings_citadas_no_comentario_viram_numeros(tickets):
    t = tickets["altair"][0]
    assert t["strings"] == [11, 12] and t["qtd"] == 2, "sem quantidade na planilha, vale o que o comentário cita"


def test_ticket_que_nao_diz_a_string_fica_no_inversor(tickets):
    t = tickets["crateus"][0]
    assert t["strings"] == [] and t["qtd"] == 9 and t["inv"] == "1.1"


def test_x_1_e_2_vai_para_a_usina_do_inversor(tickets):
    """'Santarem 1 e 2' + 'Inversor 2.5' é da Santarém 2. Contar nas duas inflaria o total da usina."""
    assert [t["inversor"] for t in tickets["santarem 2"]] == ["Inversor 2.5"]
    assert [t["inversor"] for t in tickets["santarem 1"]] == ["Inversor 1.1"], "a Santarém 1 fica só com o dela"


def test_usina_que_a_tabela_nao_tem_continua_no_indice(tickets):
    """Demerval Lobão tem ticket aberto e nenhuma aba de strings a mostra. O índice guarda assim mesmo:
    quem decide se ela aparece é a linha da tabela, não o leitor."""
    assert "demerval lobao" in tickets


# ── o diário do OS Creator por cima (23/09/2026) ──────────────────────────────
# A aba "Edicoes do app v3" é onde moram a OS vinculada e o Status do ticket (a planilha não tem coluna para os dois),
# e é o que mantém fechado o ticket finalizado pelo app ou por esta tela quando um sync do Excel (replace=true) o reabre.
# A linha 5 do Excel é o 1º ticket da fixture (ALT100, Inversor 1.7); a 7 é o da Crateús.

def test_diario_fecha_o_ticket_que_a_planilha_ainda_mostra_aberto(monkeypatch):
    t = _carregar(monkeypatch, [_reg(5, "alt100|inversor 1.7", **{"Fim da ocorrência": "2026-09-22 10:00:00"})])
    assert "altair" not in t, "a coluna tem de concordar com a tela de Tickets do OS Creator"


def test_diario_traz_a_os_e_o_status_do_ticket(monkeypatch):
    t = _carregar(monkeypatch, [_reg(7, "crateus|inversor 1.1", OS="13000", **{"Status do ticket": "OS Programada"})])
    assert (t["crateus"][0]["os"], t["crateus"][0]["status_ticket"]) == ("13000", "OS Programada")


def test_registro_do_diario_de_outra_ocorrencia_nao_fecha_nada(monkeypatch):
    """Linha apagada no Excel desce as de baixo: o registro da linha 5 era de outro inversor e não se aplica."""
    t = _carregar(monkeypatch, [_reg(5, "alt100|inversor 9.9", **{"Fim da ocorrência": "2026-09-22 10:00:00"})])
    assert [x["inversor"] for x in t["altair"]] == ["Inversor 1.7"]


def test_datas_de_verdade_no_espelho_nao_fecham_os_abertos(monkeypatch, tickets):
    """O espelho real tem data de verdade nas colunas de data, e a célula vazia chega como NaT."""
    em_texto = {k: [t["linha"] for t in v] for k, v in tickets.items()}
    reais = _carregar(monkeypatch, datas_reais=True)
    assert {k: [t["linha"] for t in v] for k, v in reais.items()} == em_texto
    assert reais["altair"][0]["inicio"] == "2026-09-01 06:00:00" and reais["altair"][0]["desde"] == "01/09/2026"


def test_diario_com_datas_de_verdade(monkeypatch):
    """No diário a coluna Fim também vira data: o registro sem Fim chega como NaT e não pode fechar o ticket."""
    diario = [_reg(7, "crateus|inversor 1.1", OS="13000"),
              _reg(9, "santarém 1|inversor 1.1", **{"Fim da ocorrência": "2026-09-22 10:00"})]
    t = _carregar(monkeypatch, diario, datas_reais=True)
    assert t["crateus"][0]["os"] == "13000", "registro sem Fim não fecha"
    assert [x["inversor"] for x in t.get("santarem 1", [])] == [], "registro com Fim fecha"


def test_o_primeiro_registro_do_diario_tambem_vale(monkeypatch):
    """Sem cabeçalho no espelho, o 1º registro está na linha 1. Ele não pode sumir nem virar nome de coluna."""
    t = _carregar(monkeypatch, [_reg(7, "crateus|inversor 1.1", OS="13000"), _reg(10, "x|y", OS="1")])
    assert t["crateus"][0]["os"] == "13000"


def test_diario_com_cabecalho_tambem_funciona(monkeypatch):
    """Se um dia o espelho passar a escrever o cabeçalho, a linha dele não pode virar registro nem atrapalhar."""
    t = _carregar(monkeypatch, [_reg(7, "crateus|inversor 1.1", OS="13000")], diario_com_cabecalho=True)
    assert t["crateus"][0]["os"] == "13000"


def test_sem_a_aba_do_diario_o_leitor_segue_como_antes(tickets):
    assert (tickets["altair"][0]["os"], tickets["altair"][0]["status_ticket"]) == ("", "")


def test_o_card_recebe_o_inicio_com_hora(tickets):
    t = tickets["altair"][0]
    assert (t["inicio"], t["desde"]) == ("2026-09-01 06:00:00", "01/09/2026")


def test_lista_de_strings_no_plural():
    """BES100, linha 309 em 23/09: "Strings 16, 17, 18, 21, 22, 23, 25, 26 e 27 com corrente nula". O marcador colado
    ao número não pega o plural, e o ticket aparecia como "não diz quais"."""
    assert app._tk_str_ids("Strings 16, 17, 18, 21, 22, 23, 25, 26 e 27 com corrente nula, verificar e normalizar "
                           "— em 16/09/2026 09:00") == [16, 17, 18, 21, 22, 23, 25, 26, 27]
    assert app._tk_str_ids("Após rompimento de alguns cabo cc dos inversores 5, 6 e 7 houve princípio de incêndio") == [], \
        "Petrolina 2: número de INVERSOR não é string"
    assert app._tk_str_ids("Strings Ipv10, Ipv11 e Ipv12 com corrente nula") == [10, 11, 12]
    assert app._tk_str_ids("String 4 com corrente nula") == [4]
    assert app._tk_str_ids("3 strings sem corrente") == []


# ── "para fechar": 0 faltando com ticket aberto (23/09/2026) ─────────────────
# Levi: "Se tem 0 strings inativas e tem 1 ticket aberto, então sei que devo fechar a string".

def _row(nome, **kw):
    return dict({"usina": nome, "plant_id": 1, "str_esp": 100, "strings_ativas": 100, "diferenca": 0,
                 "sol_baixo": False, "falha_comunicacao": False}, **kw)


def _ts(*rows):
    return [r.get("tickets_str") for r in app._com_tickets_str({"rows": list(rows), "summary": {}})["rows"]]


def test_zero_faltando_com_ticket_aberto_e_para_fechar(tickets):
    ts, = _ts(_row("Altair"))
    assert ts["para_fechar"] == 1 and ts["lista"][0]["normalizado"] is True


def test_com_string_faltando_nada_e_para_fechar(tickets):
    ts, = _ts(_row("Altair", strings_ativas=98, diferenca=-2))
    assert ts["para_fechar"] == 0 and ts["lista"][0]["normalizado"] is False


@pytest.mark.parametrize("kw,motivo", [({"sol_baixo": True}, "sem sol"),
                                       ({"falha_comunicacao": True}, "sem comunicação"),
                                       ({"str_esp": 0, "strings_ativas": 0}, "sem strings esperadas"),
                                       ({"rampa": True}, "irradiância baixa"),
                                       ({"sem_visao": True}, "sem visão")])
def test_sem_como_julgar_nao_diz_que_voltou(tickets, kw, motivo):
    """Altair 5 em 23/09: "0 faltando" com 0 de 0, porque a usina não tem strings esperadas cadastradas."""
    ts, = _ts(_row("Altair", **kw))
    assert ts["para_fechar"] == 0 and motivo in ts["motivo"]


def test_ticket_no_inversor_desligado_fora_da_conta_nao_e_para_fechar(tickets):
    """Athon (22/09): o inversor desligado sai das esperadas, e a usina dá 0 faltando com as strings dele paradas."""
    ts, = _ts(_row("Altair", inv_desligados=1, strings_fora=20, inv_desligados_nomes=["Inversor 1.7"]))
    assert ts["para_fechar"] == 0
    ts, = _ts(_row("Altair", inv_desligados=1, strings_fora=20, inv_desligados_nomes=["Inversor 3.1"]))
    assert ts["para_fechar"] == 1, "o desligado é outro inversor"
    ts, = _ts(_row("Altair", inv_desligados=1, strings_fora=20))
    assert ts["para_fechar"] == 0 and "inversor desligado" in ts["motivo"], "sem saber qual, não arrisca"


def test_ticket_da_usina_inteira_so_e_para_fechar_com_todas_as_partes_normais(tickets):
    """Brodowski em 23/09: Skid 2 com 195 de 195 e a Skid 1 sem leitura de strings. O ticket 'Todos' é da usina."""
    s2 = _row("Brodowski - Skid 2 (86)", plant_id=2, str_esp=105, strings_ativas=105)
    s1 = _row("Brodowski - Skid 1 (86)", str_esp=None, strings_ativas=None, diferenca=None)
    assert [t["para_fechar"] for t in _ts(s1, s2)] == [0, 0]
    s1 = _row("Brodowski - Skid 1 (86)", str_esp=104, strings_ativas=104)
    assert [t["para_fechar"] for t in _ts(s1, s2)] == [1, 1]


# ── o cruzamento com a linha da tabela ────────────────────────────────────────

def _pay(*nomes):
    return {"rows": [{"usina": n, "plant_id": i} for i, n in enumerate(nomes)], "summary": {}}


def test_a_linha_leva_o_total_de_strings_com_ticket(tickets):
    p = app._com_tickets_str(_pay("Altair", "Crateus"))
    alt, cra = p["rows"]
    assert alt["tickets_str"]["strings"] == 2 and alt["tickets_str"]["tickets"] == 1
    assert cra["tickets_str"]["strings"] == 9
    assert alt["tickets_str"]["lista"][0]["strings"] == [11, 12]


def test_acento_e_numero_da_api_nao_atrapalham(tickets):
    p = app._com_tickets_str(_pay("Crateús", "(318) Santarém 2"))
    assert p["rows"][0]["tickets_str"]["strings"] == 9
    assert p["rows"][1]["tickets_str"]["strings"] == 1


def test_sub_usina_da_api_pv_fica_so_com_os_tickets_do_seu_bloco(tickets):
    """'Sitio dos Nogueiras 1 (35)' e '2 (36)' têm o MESMO nome canônico. O ticket do 'Inversor 2.3' é da
    2; o que não diz inversor ('Geral') não tem como ser atribuído e aparece nas duas."""
    p = app._com_tickets_str(_pay("Sitio dos Nogueiras 1 (35)", "Sitio dos Nogueiras 2 (36)"))
    um, dois = (r["tickets_str"] for r in p["rows"])
    assert [t["inversor"] for t in dois["lista"]] == ["Inversor 2.3", "Geral"]
    assert [t["inversor"] for t in um["lista"]] == ["Geral"]


def test_usina_sem_ticket_nao_ganha_campo(tickets):
    p = app._com_tickets_str(_pay("Guatambu"))
    assert "tickets_str" not in p["rows"][0]


def test_nao_mexe_no_payload_do_cache(tickets):
    original = _pay("Altair")
    antes = json.dumps(original, sort_keys=True)
    app._com_tickets_str(original)
    assert json.dumps(original, sort_keys=True) == antes


def test_ticket_da_usina_inteira_nao_dobra_nas_partes(tickets):
    """Brodowski, 23/09: UM ticket 'Todos' de 209 strings (furto de cabos) para a usina, que na API PV são duas
    linhas (Skid 1 e Skid 2). Mostrar 209 nas duas fazia quem somasse ler 418. Ticket sem inversor cobre a PARTE
    inteira: em cada linha conta até as esperadas dela, e vai marcado como da usina."""
    rows = [{"usina": "Brodowski - Skid 1 (86)", "plant_id": 1, "str_esp": 104},
            {"usina": "Brodowski - Skid 2 (86)", "plant_id": 2, "str_esp": 105}]
    p = app._com_tickets_str({"rows": rows, "summary": {}})
    s1, s2 = (r["tickets_str"] for r in p["rows"])
    assert (s1["strings"], s2["strings"]) == (104, 105)
    assert s1["lista"][0]["usina_inteira"] is True
    sem_esp = app._com_tickets_str({"rows": [{"usina": "Brodowski - Skid 1 (86)", "plant_id": 1}], "summary": {}})
    assert sem_esp["rows"][0]["tickets_str"]["strings"] == 209, "sem esperadas no cadastro, vale a quantidade da planilha"


# ── a tela (o MESMO código do HTML, rodado no node) ───────────────────────────
import pathlib
import shutil
import subprocess

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
MON = (RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")
NODE = shutil.which("node")


def _trecho(ini, fim):
    i = MON.index(ini)
    return MON[i:MON.index(fim, i) + len(fim)]


def _js(expr):
    if not NODE:
        pytest.skip("node não instalado")
    js = "\n".join([
        _trecho("const _he=", "\n"), _trecho("function _snum(", "\n"),
        _trecho("function _tkInvChave(", "/* fim _tkStr */"),
        "process.stdout.write(JSON.stringify(" + expr + "));",
    ])
    p = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def _linha_js(tk, dif):
    r = {"diferenca": dif}
    if tk is not None:
        r["tickets_str"] = {"strings": tk, "tickets": 2, "lista": []}
    return json.dumps(r)


def test_coluna_vermelha_quando_sobra_string_faltando_sem_ticket():
    html = _js("_tkStrCel(%s,false)" % _linha_js(12, -40))
    assert ">12<" in html and "/40" in html and "#ff5b6e" in html and "28 sem ticket" in html


def test_coluna_verde_quando_tudo_que_falta_tem_ticket():
    html = _js("_tkStrCel(%s,false)" % _linha_js(40, -40))
    assert "#3fb950" in html and "todas com ticket" in html


def test_sem_ticket_e_com_deficit_mostra_zero_em_vermelho():
    html = _js("_tkStrCel(%s,false)" % _linha_js(None, -5))
    assert ">0<" in html and "/5" in html and "#ff5b6e" in html


def test_sem_ticket_e_sem_deficit_e_traco():
    assert "—" in _js("_tkStrCel(%s,false)" % _linha_js(None, 0))


def test_a_noite_mostra_o_ticket_sem_julgar_o_deficit():
    """Sem sol a coluna não cobra o déficit: mostra quantos tickets estão abertos, neutro (era o total em azul)."""
    html = _js("_tkStrCel(%s,true)" % _linha_js(12, -599))
    assert "2 abertos" in html and "12 strings" in html and "/599" not in html and "#ff5b6e" not in html
    assert "para fechar" not in html


def _cel_zero(para_fechar, motivo=""):
    return json.dumps({"diferenca": 0, "tickets_str": {"strings": 1, "tickets": 1, "para_fechar": para_fechar,
                       "motivo": motivo, "lista": [{"inversor": "Inversor 1.6", "strings": [15], "desde": "17/09/2026",
                                                    "normalizado": bool(para_fechar), "usina_inteira": False}]}})


def test_zero_faltando_com_ticket_normalizado_diz_para_fechar():
    """MTS200 em 23/09: 400 de 400 strings e o ticket da PV15 (desde 17/09) ainda aberto. É o sinal para fechar."""
    html = _js("_tkStrCel(%s,false)" % _cel_zero(1))
    assert "1 para fechar" in html and "gc-tkfechar" in html and "Inversor 1.6 · PV15, desde 17/09" in html


def test_zero_faltando_sem_como_julgar_mostra_o_ticket_neutro():
    """Altair 5 em 23/09: "0 faltando" com 0 de 0 strings. Mostra o ticket e diz por que não dá para julgar."""
    html = _js("_tkStrCel(%s,false)" % _cel_zero(0, "usina sem strings esperadas cadastradas"))
    assert "1 aberto" in html and "sem strings esperadas cadastradas" in html and "para fechar" not in html


def test_ticket_casa_com_o_inversor_pelo_numero():
    lista = [{"inv": "1.7", "strings": [11, 12], "usina_inteira": False},
             {"inv": "2.2", "strings": [], "usina_inteira": False},
             {"inv": "todos", "strings": [], "usina_inteira": True}]
    r = _js("_tkStrInv(%s,'Inversor 1.7').map(t=>t.inv)" % json.dumps(lista))
    assert r == ["1.7", "todos"], "o do 1.7 e o da usina inteira; o do 2.2 não"
    assert _js("_tkInvChave('INV 01.07')") == "1.7"


def test_marca_de_cada_string():
    tks = [{"inv": "1.7", "strings": [11, 12], "usina_inteira": False}]
    marca = lambda nome, ativa, morta: _js("_tkStrMarca(%s,{name:%s,dead:%s},%s)" % (
        json.dumps(tks), json.dumps(nome), json.dumps(morta), json.dumps(ativa)))
    assert marca("Ipv11", False, True) == "ticket"
    assert marca("Ipv12", True, False) == "voltou", "ticket aberto e a string produzindo = candidata a fechar"
    assert marca("Ipv3", False, True) is None, "string zerada que o ticket não cita não é dele"
    so_inv = [{"inv": "2.2", "strings": [], "usina_inteira": False}]
    assert _js("_tkStrMarca(%s,{name:'Ipv3',dead:true},false,true)" % json.dumps(so_inv)) == "coberta", \
        "ticket que não diz a string cobre as zeradas do inversor quando a quantidade dele alcança todas"
    assert _js("_tkStrMarca(%s,{name:'Ipv3',dead:true},false,false)" % json.dumps(so_inv)) is None, \
        "2 strings no ticket e 5 zeradas: não dá para dizer quais 2 são — nenhuma leva a marca"
    assert _js("_tkStrMarca(%s,{name:'Ipv4',dead:false},true,true)" % json.dumps(so_inv)) is None


def test_inversor_com_mais_zeradas_que_o_ticket_cobre():
    """Ticket de 2 strings sem dizer quais, 5 zeradas no inversor: 3 ficam sem ticket, e a etiqueta diz."""
    tks = [{"inv": "2.2", "strings": [], "usina_inteira": False, "qtd_na_linha": 2}]
    mortas = [{"id": f"Ipv{i}", "status": "sem_corrente"} for i in range(1, 6)]
    r = _js("_tkStrCobertura(%s,%s)" % (json.dumps(tks), json.dumps(mortas)))
    assert r == {"cobreTudo": False, "semTicket": 3}
    r = _js("_tkStrCobertura(%s,%s)" % (json.dumps(tks), json.dumps(mortas[:2])))
    assert r == {"cobreTudo": True, "semTicket": 0}
    nomeado = [{"inv": "2.2", "strings": [1, 2], "usina_inteira": False, "qtd_na_linha": 2}]
    assert _js("_tkStrCobertura(%s,%s)" % (json.dumps(nomeado), json.dumps(mortas))) == {"cobreTudo": False, "semTicket": 3}


# ── finalizar pela tela de strings: a PLATAFORMA grava (23/09/2026) ─────────────
# O Levi escolheu a gravação direta, pelo relay que já grava os tickets do OS Creator de mesa. As regras (relê, confere,
# linha inteira, diário) estão em tickets_str_fechar.py e nos testes dele; aqui é o encaixe no Flask.

class _BancoFalso:
    """A aba 128 com a linha do ALT100 (Inversor 1.7) e o diário vazio. O PUT troca a linha inteira, como a API."""

    def __init__(self, n, recusa=None):
        self.linha = {"row_number": n, "headers": list(COLS_STR), "values": [
            "", "ALT100", 0, "", "", "", "", "Inversor 1.7", 20, None, None, None, "2026-09-01 06:00:00",
            "2026-09-01 06:00:00", None, None, None, "", "Ipv11 e Ipv12 com corrente nula em 01/09/2026 06:00"]}
        self.recusa, self.chamadas = recusa, []

    def ler(self, sid):
        return [dict(self.linha)] if sid == 128 else []

    def encaminhar(self, metodo, sid, row, corpo, quem, token, **kw):
        self.chamadas.append((metodo, sid, row, quem, token))
        if self.recusa:
            return self.recusa, '{"error":"recusado"}'
        if metodo == "PUT":
            self.linha = {"row_number": row, "headers": corpo["headers"], "values": corpo["values"]}
        return 200, "{}"


@pytest.fixture
def cliente(tickets, monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "", raising=False)
    monkeypatch.setattr(app, "_TICKETS_STR_FECHADOS", {})
    app.app.config["TESTING"] = True
    with app.app.test_client() as c:
        yield c


def _linha_do_altair():
    return app.TICKETS_STR["altair"][0]["linha"]


def _finalizar(cliente, monkeypatch, banco, linha=None, token="tok", **corpo):
    monkeypatch.setattr(app, "_tkf_ler_aba", banco.ler)
    monkeypatch.setattr(app._relay, "encaminhar", banco.encaminhar)
    monkeypatch.setattr(app._estado_backup, "_token", lambda: token)
    body = dict({"fim": "2026-09-23T10:00", "quem": "Levi Maia", "usina_planilha": "ALT100", "causa": "Falha no equipamento",
                 "inversor": "Inversor 1.7", "desde": "01/09/2026"}, **corpo)
    acao = body.pop("_acao", "finalizar")
    return cliente.post("/api/strings/tickets/%s/%s" % (linha or _linha_do_altair(), acao), json=body)


def test_finalizar_sem_causa_raiz_e_recusado(cliente, monkeypatch):
    """Levi, 23/09: "nunca finalizar um ticket com causa raiz nula pela plataforma"."""
    b = _BancoFalso(_linha_do_altair())
    r = _finalizar(cliente, monkeypatch, b, causa="")
    assert r.status_code == 400 and not b.chamadas and "causa raiz" in r.get_json()["erro"]


def test_salvar_o_status_pelo_card_vai_ao_diario_e_aparece_na_hora(cliente, monkeypatch):
    b = _BancoFalso(_linha_do_altair())
    r = _finalizar(cliente, monkeypatch, b, _acao="salvar", causa="", status="Aguardando Garantia", fim=None)
    assert r.status_code == 200 and r.get_json()["confirmado"] is True
    assert [(m, s) for m, s, *_ in b.chamadas] == [("POST", 399)], "status não tem coluna: só o diário"
    t = app._com_tickets_str(_pay("Altair"))["rows"][0]["tickets_str"]["lista"][0]
    assert t["status_ticket"] == "Aguardando Garantia", "o card mostra o gravado sem esperar o espelho"
    assert dict(zip(COLS_STR, b.linha["values"]))["Fim da ocorrência"] is None, "salvar não fecha"


def test_salvar_a_causa_pelo_card(cliente, monkeypatch):
    b = _BancoFalso(_linha_do_altair())
    r = _finalizar(cliente, monkeypatch, b, _acao="salvar", causa="Furto", fim=None, originais={"causa": ""})
    assert r.status_code == 200 and [(m, s) for m, s, *_ in b.chamadas] == [("PUT", 128), ("POST", 399)]
    assert app._com_tickets_str(_pay("Altair"))["rows"][0]["tickets_str"]["lista"][0]["causa"] == "Furto"


def test_finalizar_pela_tela_grava_na_base_e_tira_da_coluna(cliente, monkeypatch):
    b = _BancoFalso(_linha_do_altair())
    r = _finalizar(cliente, monkeypatch, b)
    assert r.status_code == 200 and r.get_json()["ok"] is True and r.get_json()["confirmado"] is True
    assert [(m, s) for m, s, *_ in b.chamadas] == [("PUT", 128), ("POST", 399)]
    assert b.chamadas[0][3] == ("senha compartilhada", "Levi Maia (plataforma)") and b.chamadas[0][4] == "tok"
    assert dict(zip(COLS_STR, b.linha["values"]))["Fim da ocorrência"] == "2026-09-23 10:00:00"
    assert "tickets_str" not in app._com_tickets_str(_pay("Altair"))["rows"][0], "sai da coluna sem esperar o espelho"


def test_linha_que_nao_e_ticket_aberto_de_strings_e_recusada(cliente, monkeypatch):
    b = _BancoFalso(99999)
    assert _finalizar(cliente, monkeypatch, b, linha=99999).status_code == 404 and not b.chamadas


def test_sem_o_token_de_escrita_nada_e_gravado(cliente, monkeypatch):
    b = _BancoFalso(_linha_do_altair())
    r = _finalizar(cliente, monkeypatch, b, token="")
    assert r.status_code == 503 and not b.chamadas and "Nada foi gravado" in r.get_json()["erro"]


def test_a_recusa_do_gravador_volta_para_a_tela_e_o_ticket_fica(cliente, monkeypatch):
    """A tela viu ALT100, e a linha agora é de outra usina: 409, nada gravado, o ticket continua na coluna."""
    b = _BancoFalso(_linha_do_altair())
    r = _finalizar(cliente, monkeypatch, b, usina_planilha="MTS200")
    assert r.status_code == 409 and not b.chamadas and "Nada foi gravado" in r.get_json()["erro"]
    assert app._com_tickets_str(_pay("Altair"))["rows"][0]["tickets_str"]["tickets"] == 1


def test_base_que_recusa_o_put_nao_esconde(cliente, monkeypatch):
    b = _BancoFalso(_linha_do_altair(), recusa=500)
    r = _finalizar(cliente, monkeypatch, b)
    assert r.status_code == 502 and [c[0] for c in b.chamadas] == ["PUT"]
    assert app._com_tickets_str(_pay("Altair"))["rows"][0]["tickets_str"]["tickets"] == 1


def test_o_esconder_expira(cliente, monkeypatch):
    """Esconder é provisório: cobre o atraso do espelho, não pode virar 'fechado para sempre' na tela."""
    n = _linha_do_altair()
    monkeypatch.setitem(app._TICKETS_STR_FECHADOS, n, app.time.time() - app._TICKETS_STR_FECHADOS_TTL - 1)
    assert app._com_tickets_str(_pay("Altair"))["rows"][0]["tickets_str"]["tickets"] == 1


def test_ticket_fechado_sai_da_copia_da_tela_na_hora():
    """Depois de fechar, a tela tira o ticket da própria cópia (sem ir ao servidor: o botão Atualizar da página manda
    force=1, e isso reconstruiria a aba inteira no processo web)."""
    rows = [{"usina": "Altair 2 (74)", "tickets_str": {"strings": 3, "tickets": 2, "lista": [
                {"linha": 10, "qtd_na_linha": 2}, {"linha": 11, "qtd_na_linha": 1}]}},
            {"usina": "Crateus", "tickets_str": {"strings": 9, "tickets": 1, "lista": [{"linha": 12, "qtd_na_linha": 9}]}}]
    r = _js("_tkStrSemLinha(%s,10)" % json.dumps(rows))
    assert r[0]["tickets_str"] == {"strings": 1, "tickets": 1, "lista": [{"linha": 11, "qtd_na_linha": 1}]}
    r = _js("_tkStrSemLinha(%s,12)" % json.dumps(rows))
    assert "tickets_str" not in r[1], "usina sem ticket nenhum volta ao '—'"


# ── o card do ticket no inversor aberto (23/09/2026) ──────────────────────────
# Strings REAIS do drill às 13:16: MTS200 Inversor 1.6 (PV15 de volta a 12,7 A, 8 trancadas) e MAB100 Inversor 3.9
# (PV3 e PV4 em 0,0 A, ticket de 2 strings que não diz quais).

def _chips(*lst):
    return [{"name": n, "st": st, "amp": "%.2f" % a, "dead": st == "sem_corrente", "trancada": st == "trancada"}
            for n, st, a in lst]


MTS200_16 = _chips(("I_PV1", "ativa", 12.7), ("I_PV3", "trancada", 0.1), ("I_PV14", "trancada", 0.0),
                   ("I_PV15", "ativa", 12.7), ("I_PV17", "ativa", 12.7))
MAB100_39 = _chips(("I_PV1", "ativa", 8.15), ("I_PV3", "sem_corrente", 0.0), ("I_PV4", "sem_corrente", 0.0),
                   ("I_PV5", "ativa", 8.07))


def _estado(t, inv):
    return _js("_tkEstado(%s,%s)" % (json.dumps(t), json.dumps(inv)))


def test_ticket_que_diz_a_string_e_julgado_por_ela():
    t = {"strings": [15], "usina_inteira": False}
    e = _estado(t, {"strings": MTS200_16, "diff": 0})
    assert e["k"] == "voltou" and "PV15 12,70 A" in e["txt"]
    morta = _chips(("I_PV15", "sem_corrente", 0.0), ("I_PV1", "ativa", 12.7))
    assert _estado(t, {"strings": morta, "diff": -1})["k"] == "morta"
    assert _estado({"strings": [14]}, {"strings": MTS200_16, "diff": 0})["k"] == "mudo",         "string trancada é MPPT sem string: não dá para dizer que voltou"


def test_ticket_que_nao_diz_a_string_e_julgado_pelo_inversor():
    e = _estado({"strings": []}, {"strings": MAB100_39, "diff": -2})
    assert e["k"] == "morta" and "PV3 0,00 A" in e["txt"] and "PV4 0,00 A" in e["txt"]
    assert _estado({"strings": []}, {"strings": MTS200_16, "diff": 0})["k"] == "voltou"


def test_sem_sol_ou_sem_comunicacao_o_inversor_nao_julga():
    assert _estado({"strings": [15]}, {"strings": MTS200_16, "diff": 0, "semSolU": True})["k"] == "mudo"
    assert _estado({"strings": [15]}, {"strings": MTS200_16, "diff": 0, "semComU": True})["k"] == "mudo"


def _card(t, est, f=None, na_usina=False, os_=None):
    if not NODE:
        pytest.skip("node não instalado")
    js = "\n".join([
        "const state={}; const localStorage={getItem:()=>'Levi Maia',setItem(){}};",
        _trecho("const _he=", "\n"), _trecho("function _snum(", "\n"),
        _trecho("function _tkInvChave(", "/* fim _tkStr */"), _trecho("const TK_CAUSAS=", "/* fim _tkCard */"),
        "process.stdout.write(JSON.stringify(_tkCardHtml(%s,%s,%s,%s,%s)));" % (
            json.dumps(t), json.dumps(est), json.dumps(f), json.dumps(na_usina), json.dumps(os_)),
    ])
    p = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


T312 = {"linha": 312, "inversor": "Inversor 1.6", "strings": [15], "qtd": 1, "qtd_na_linha": 1, "desde": "17/09/2026",
        "inicio": "2026-09-17 06:00:02", "causa": "", "os": "13762", "status_ticket": "OS Programada",
        "usina_planilha": "MTS200", "comentario": "PV15 com corrente nula em 17/09/2026 06:00", "usina_inteira": False}


def test_o_card_mostra_o_que_a_planilha_e_o_diario_sabem_do_ticket():
    html = _card(T312, {"k": "voltou", "txt": "Produzindo agora · PV15 12,70 A"})
    for trecho in ("linha 312 da planilha de tickets", "PV15", "17/09/2026 06:00", "OS 13762", "OS Programada",
                   "MTS200", "PV15 com corrente nula", "Finalizar ticket", "Quem está fechando", "Levi Maia",
                   "gc-tkc voltou"):
        assert trecho in html, trecho
    assert "Finalizar mesmo assim" not in html


def test_string_ainda_morta_pede_confirmacao_antes_de_finalizar():
    est = {"k": "morta", "txt": "Ainda sem corrente · PV3 0,00 A"}
    html = _card(T312, est)
    assert "Finalizar mesmo assim" in html and "tkStrConfirmar(312)" in html and "tkStrFinalizar" not in html
    html = _card(T312, est, {"fase": "confirmar"})
    assert "Sim, finalizar" in html and "tkStrFinalizar(312,0)" in html and "Cancelar" in html


def test_a_recusa_da_plataforma_aparece_no_card():
    html = _card(T312, {"k": "voltou", "txt": "x"}, {"fase": "erro", "msg": "A linha 312 agora é de \"MTS100\"."})
    assert "A linha 312 agora é de &quot;MTS100&quot;." in html


def test_a_tela_grava_pela_rota_da_plataforma_e_manda_o_que_viu():
    i = MON.index("async function _tkGravar(")
    corpo = MON[i:MON.index("\n}", i)]
    assert "'/api/strings/tickets/'+linha+'/'+(finalizar?'finalizar':'salvar')" in corpo
    assert "usina_planilha:a.t.usina_planilha" in corpo and "inversor:a.t.inversor" in corpo and "desde:a.t.desde" in corpo
    assert "/os/api/tickets" not in MON and "TK_FECHAR" not in MON, "o caminho pelo OS Creator web saiu"


def test_o_card_entra_no_inversor_aberto_e_os_da_usina_no_alto():
    i = MON.index("function renderInversor(")
    assert "${_tkCards(inv)}" in MON[i:MON.index("\nfunction ", i + 10)]
    assert "_tkCardsUsina(u)" in MON


# ── a última OS de RECOMPOSIÇÃO do inversor, do Fracttal (23/09/2026) ─────────
# Levi, sobre o card: "mostrasse os dados da última OS de recomposição para esse inversor ao invés de só comentário (...)
# A data de conclusão seria quando o técnico fechou a OS, quando ele fez a tarefa! e o fim da ocorrência já fica
# sugerido como essa data". As linhas abaixo são as REAIS de work_orders/?id_item= em 23/09 (uma por TAREFA, UTC).

W13762 = {"wo_folio": "13762", "description": "[Inversor 1.6] - Recomposição de String", "tasks_log_task_type_main": "Corretiva",
          "id_status_work_order": 2, "done": True, "creation_date": "2026-09-17T14:00:34.404671+00:00",
          "event_date": "2026-09-17T09:00:02.245+00:00", "initial_date": "2026-09-18T16:58:23.972+00:00",
          "final_date": "2026-09-18T18:34:56.742572+00:00", "wo_final_date": None, "personnel_description": "Francisco  Santos",
          "note": "String I_PV15 com corrente nula, verificar e normalizar",
          "task_note": "String I_PV15 com corrente nula, verificar e normalizar"}
W7051 = {"wo_folio": "7051", "description": "[Inversor 6][MTS200] Verificação de tracker parado ou sombreamento",
         "tasks_log_task_type_main": "Corretiva", "id_status_work_order": 3, "done": True,
         "creation_date": "2026-05-25T20:15:54.978801+00:00", "final_date": "2026-05-26T16:35:30.886574+00:00",
         "wo_final_date": "2026-06-16T13:31:59.419552+00:00", "personnel_description": "Francisco  Santos"}
W2138 = {"wo_folio": "2138", "description": "Manutenção Preventiva Mensal GRID CO. – Inversores",
         "tasks_log_task_type_main": "Preventiva", "id_status_work_order": 4, "done": False,
         "creation_date": "2026-01-26T12:11:36.603275+00:00", "final_date": None}
W13005 = {"wo_folio": "13005", "description": "[Inversor 3.9] - Recomposição de String", "tasks_log_task_type_main": "Corretiva",
          "id_status_work_order": 2, "done": True, "creation_date": "2026-09-04T13:50:25.895332+00:00",
          "final_date": "2026-09-04T18:43:49.91102+00:00", "personnel_description": "James Chaves ",
          "note": "O PROBLEMA ESTA NAS ENTRADAS 03 E 04 DO INVESOR, AS STRINGS ESTÃO NORMAL.",
          "task_note": "Strings I_PV3 e I_PV4 com corrente nula, verificar e normalizar"}
W14326 = {"wo_folio": "14326", "description": "[Inversor 3.5] - Recomposição de String", "tasks_log_task_type_main": "Corretiva",
          "id_status_work_order": 1, "done": False, "creation_date": "2026-09-22T13:49:29.096332+00:00", "final_date": None,
          "personnel_description": "Luiz  Silva", "note": "String I_PV7 com corrente nula", "task_note": "String I_PV7 com corrente nula"}


def test_ultima_recomposicao_e_a_mais_nova_e_a_conclusao_e_a_da_tarefa():
    """MTS200 Inversor 1.6: a 13762 foi executada em 18/09 18:34 UTC = 15:34 aqui. A OS de tracker (7051) e a
    preventiva cancelada (2138) do mesmo ativo não são de recomposição."""
    o = app._tk_str_ultima_recomposicao([W7051, W13762, W2138])
    assert (o["folio"], o["conclusao"], o["concluida"], o["tecnico"]) == \
        ("13762", "2026-09-18 15:34:56", True, "Francisco Santos")
    assert o["status"] == "Concluída" and o["descricao"] == "[Inversor 1.6] - Recomposição de String"


def test_os_em_andamento_nao_tem_data_de_conclusao():
    o = app._tk_str_ultima_recomposicao([W14326])
    assert (o["folio"], o["concluida"], o["conclusao"], o["status"]) == ("14326", False, "", "Em andamento")


def test_relato_do_tecnico_vem_quando_difere_da_instrucao():
    """MAB100 3.9 (OS 13005): o técnico escreveu o que achou, e é isso que ajuda a decidir o fechamento."""
    assert app._tk_str_ultima_recomposicao([W13005])["relato"].startswith("O PROBLEMA ESTA NAS ENTRADAS 03 E 04")
    assert app._tk_str_ultima_recomposicao([W13762])["relato"] == "", "nota igual à instrução não é relato"


def test_recomposicao_cancelada_fica_fora():
    cancelada = dict(W13762, wo_folio="14000", id_status_work_order=4, creation_date="2026-09-20T10:00:00+00:00")
    assert app._tk_str_ultima_recomposicao([W13762, cancelada])["folio"] == "13762"


def test_os_com_duas_tarefas_conclui_na_ultima():
    """work_orders/?id_item= volta UMA LINHA POR TAREFA; a OS termina quando a última tarefa termina."""
    segunda = dict(W13762, final_date="2026-09-19T12:00:00+00:00")
    assert app._tk_str_ultima_recomposicao([W13762, segunda])["conclusao"] == "2026-09-19 09:00:00"


def test_sem_os_de_recomposicao():
    assert app._tk_str_ultima_recomposicao([W7051, W2138]) is None


def _rota_os(cliente, monkeypatch, rows, linha=None, on=True, usina="Altair"):
    monkeypatch.setattr(app, "FRACTTAL_ON", on)
    monkeypatch.setattr(app, "_frac_ativo", lambda code: {"id": 7, "desc": "Inversor 1.7"})
    monkeypatch.setattr(app, "_frac_wos_raw", lambda iid: rows)
    return cliente.get("/api/strings/tickets/%s/os" % (linha or _linha_do_altair()), query_string={"usina": usina})


def test_rota_sugere_o_fim_pela_conclusao_da_os(cliente, monkeypatch):
    """O ticket do Altair começa em 01/09 06:00; a OS foi executada depois, então o Fim já vem sugerido."""
    d = _rota_os(cliente, monkeypatch, [W13762]).get_json()
    assert d["ok"] is True and d["os"]["folio"] == "13762" and d["sugere_fim"] == "2026-09-18T15:34"


def test_os_anterior_ao_ticket_nao_sugere_o_fim(cliente, monkeypatch):
    velha = dict(W13762, creation_date="2026-08-10T10:00:00+00:00", final_date="2026-08-12T12:00:00+00:00")
    d = _rota_os(cliente, monkeypatch, [velha]).get_json()
    assert d["ok"] is True and d["os"]["anterior"] is True and d["sugere_fim"] is None


def test_ticket_da_usina_inteira_nao_procura_os(cliente, monkeypatch):
    n = app.TICKETS_STR["brodowski"][0]["linha"]
    d = _rota_os(cliente, monkeypatch, [W13762], linha=n).get_json()
    assert d["ok"] is False and "usina inteira" in d["motivo"]


def test_ticket_escrito_com_o_nome_da_usina_acha_o_codigo_pela_planilha(tickets):
    """Boa Esperança do Sul, linha 241 em 23/09: a planilha escreve o NOME ("... 1 e 2") e o Fracttal só se acha pelo
    código (BES100). O de-para é o mesmo da aba "Base de dados - Usinas", ao contrário."""
    assert tickets["embu guacu"][0]["cod"] == "EBG100" and tickets["altair"][0]["cod"] == "ALT100"


def test_rota_da_os_procura_o_inversor_pelo_codigo_da_usina(cliente, monkeypatch):
    n = app.TICKETS_STR["embu guacu"][0]["linha"]
    d = _rota_os(cliente, monkeypatch, [W13762], linha=n, usina="Embu Guaçu 1").get_json()
    assert d["ok"] is True and d["code"] == "EBG100-INVR1.1"


def test_rota_da_os_recusa_linha_que_nao_e_ticket_e_sem_credencial(cliente, monkeypatch):
    assert _rota_os(cliente, monkeypatch, [W13762], linha=99999).status_code == 404
    d = _rota_os(cliente, monkeypatch, [W13762], on=False).get_json()
    assert d["ok"] is False and "Fracttal" in d["motivo"]


def _o_concluida():
    return {"ok": True, "sugere_fim": "2026-09-18T15:34", "os": {
        "folio": "13762", "descricao": "[Inversor 1.6] - Recomposição de String", "status": "Concluída", "concluida": True,
        "conclusao": "2026-09-18 15:34:56", "tecnico": "Francisco Santos", "relato": "", "anterior": False}}


def test_o_card_mostra_a_observacao_e_a_data_de_conclusao():
    html = _card(T312, {"k": "voltou", "txt": "x"}, None, False, _o_concluida())
    for trecho in ("Observação", "PV15 com corrente nula", "Data de conclusão", "18/09/2026 15:34",
                   "OS 13762 · Recomposição de String · Concluída · Francisco Santos", 'value="2026-09-18T15:34"',
                   "sugerido pela conclusão da OS 13762"):
        assert trecho in html, trecho
    assert "Comentários" not in html


def test_o_fim_digitado_vence_a_sugestao():
    html = _card(T312, {"k": "voltou", "txt": "x"}, {"fim": "2026-09-20T08:00"}, False, _o_concluida())
    assert 'value="2026-09-20T08:00"' in html and "sugerido pela conclusão" not in html


def test_os_em_andamento_e_carregando_no_card():
    anda = {"ok": True, "sugere_fim": None, "os": {"folio": "14326", "descricao": "[Inversor 3.5] - Recomposição de String",
            "status": "Em andamento", "concluida": False, "conclusao": "", "tecnico": "Luiz Silva", "relato": "",
            "anterior": False}}
    assert "OS 14326 em andamento" in _card(T312, {"k": "morta", "txt": "x"}, None, False, anda)
    assert "buscando a OS no Fracttal" in _card(T312, {"k": "voltou", "txt": "x"}, None, False, "loading")
    sem = {"ok": True, "sugere_fim": None, "os": None}
    assert "nenhuma OS de recomposição" in _card(T312, {"k": "voltou", "txt": "x"}, None, False, sem)


def test_causa_e_status_sao_escolhas_da_lista_do_levi():
    html = _card(T312, {"k": "voltou", "txt": "x"})
    for op in ("Falha no equipamento", "Furto", "Garantia", "OS Programada", "Aguardando Material",
               "Aguardando Garantia", "Aguardando Cliente"):
        assert "<option>%s</option>" % op in html or "<option selected>%s</option>" % op in html, op
    assert 'id="gc-tkcausa-312"' in html and 'id="gc-tkstatus-312"' in html


def test_sem_causa_raiz_o_finalizar_fica_travado():
    """Levi, 23/09: "nunca finalizar um ticket com causa raiz nula pela plataforma"."""
    html = _card(T312, {"k": "voltou", "txt": "x"})
    i = html.index("tkStrFinalizar(312,0)")
    assert " disabled" in html[html.rindex("<button", 0, i):i] and "Escolha a causa raiz para finalizar" in html
    html = _card(T312, {"k": "voltou", "txt": "x"}, {"causa": "Furto"})
    i = html.index("tkStrFinalizar(312,0)")
    assert " disabled" not in html[html.rindex("<button", 0, i):i] and "Escolha a causa raiz" not in html


def test_causa_antiga_escrita_a_mao_continua_escolhida():
    html = _card(dict(T312, causa="Problema no MPPT"), {"k": "morta", "txt": "x"})
    assert "<option selected>Problema no MPPT</option>" in html and "Escolha a causa raiz" not in html


def test_os_aberta_sugere_os_programada_no_status():
    anda = {"ok": True, "sugere_fim": None, "os": {"folio": "14326", "descricao": "[Inversor 3.5] - Recomposição de String",
            "status": "Em andamento", "concluida": False, "aberta": True, "conclusao": "", "tecnico": "Luiz Silva",
            "relato": "", "anterior": False}}
    html = _card(dict(T312, status_ticket=""), {"k": "morta", "txt": "x"}, None, False, anda)
    assert "<option selected>OS Programada</option>" in html
    assert "tkStrSalvar(312,0)" in html and " disabled" not in html[html.rindex("<button", 0, html.index("tkStrSalvar")):
                                                                     html.index("tkStrSalvar")], "a sugestão é mudança"
    html = _card(dict(T312, status_ticket=""), {"k": "morta", "txt": "x"}, {"status": "OS Programada"}, False, _o_concluida())
    assert "A OS 13762 de recomposição já foi concluída" in html, "MTS200 em 23/09: status OS Programada com a OS fechada"
    sem = {"ok": True, "sugere_fim": None, "os": None}
    html = _card(dict(T312, status_ticket=""), {"k": "morta", "txt": "x"}, {"status": "OS Programada"}, False, sem)
    assert "Nenhuma OS de recomposição aberta" in html


def test_salvar_so_liga_quando_algo_muda():
    html = _card(T312, {"k": "voltou", "txt": "x"})
    j = html.index("tkStrSalvar(312,0)")
    assert " disabled" in html[html.rindex("<button", 0, j):j]


def test_a_tela_salva_e_finaliza_pelas_rotas_da_plataforma():
    i = MON.index("async function _tkGravar(")
    corpo = MON[i:MON.index("\n}", i)]
    assert "(finalizar?'finalizar':'salvar')" in corpo and "originais:{causa:" in corpo and "corpo.causa=" in corpo
    assert "window.tkStrSalvar=" in MON and "window.tkStrFinalizar=" in MON


def test_relato_do_tecnico_aparece_no_card():
    o = _o_concluida()
    o["os"]["relato"] = "O PROBLEMA ESTA NAS ENTRADAS 03 E 04 DO INVESOR"
    assert "Relato do técnico" in _card(T312, {"k": "morta", "txt": "x"}, None, False, o)


def test_botao_travado_nao_mostra_cursor_de_carregando():
    """Levi, 23/09: sem causa raiz (e depois de salvar), o mouse em cima do Salvar mostrava o cursor de carregando,
    "dando a falsa sensação de que algo está carregando". Travado é travado; carregando só enquanto grava."""
    import re as _re
    regra = _re.search(r"\.btn\[disabled\]\{([^}]*)\}", MON).group(1)
    assert "cursor:not-allowed" in regra and "wait" not in regra and "progress" not in regra
    assert _re.search(r"\.btn\.gravando\{[^}]*cursor:progress", MON)


def test_so_o_botao_clicado_diz_que_esta_gravando():
    html = _card(dict(T312, causa="Furto"), {"k": "voltou", "txt": "x"}, {"fase": "gravando", "acao": "salvar", "causa": "Garantia"})
    assert "Salvando…" in html and "Gravando…" not in html
    i = html.index("tkStrSalvar(312,0)")
    assert "gravando" in html[html.rindex("<button", 0, i):i]
    html = _card(dict(T312, causa="Furto"), {"k": "voltou", "txt": "x"}, {"fase": "gravando", "acao": "finalizar"})
    assert "Gravando…" in html and "Salvando…" not in html


def test_o_aviso_de_finalizado_diz_a_causa_e_o_status():
    """Levi, 23/09: "quando eu clicar em finalizar o status automaticamente atualiza para finalizado". Atualiza: o
    registro do diário foi com "Concluído" (o status final do OS Creator). O aviso passa a dizer isso."""
    if not NODE:
        pytest.skip("node não instalado")
    js = "\n".join([_trecho("const _he=", "\n"), _trecho("function _tkOkHtml(", "\n}"),
                    "process.stdout.write(JSON.stringify(_tkOkHtml({linha:312,fimTxt:'18/09/2026 15:34',quem:'Levi',"
                    "causa:'Falha no equipamento',status:'Concluído'})));"])
    p = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    html = json.loads(p.stdout)
    assert "causa Falha no equipamento" in html and "status Concluído" in html and "18/09/2026 15:34" in html
