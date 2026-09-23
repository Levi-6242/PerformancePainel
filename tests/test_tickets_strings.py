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
]
COLS_USINAS = ["", "Usina", "Código da usina", "Código curto da usina", "Cliente", "UF", "Status", "Supervisor(a)"]
USINAS = [("Altair", "THPN-ALT100", None, "Thopen", "Sao Paulo", "OPERAÇÃO", "Camila Viana"),
          ("Embu Guaçu", "THPN-EBG100 ", None, "Thopen", "Sao Paulo", "OPERAÇÃO", "Danuth Fernandes")]


def _planilha() -> io.BytesIO:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Strings indisp"
    for _ in range(3):
        ws.append(["rascunho"])            # cabeçalho na linha 4, como na real (header=3)
    ws.append(COLS_STR)
    for u, inv, n_inv, afet, causa, ini, fim, com in LINHAS_STR:
        ws.append(["", u, 0, "", "", "", "", inv, n_inv, afet, causa, None, ini, ini, fim, None, None, "", com])
    wu = wb.create_sheet("Base de dados - Usinas")
    for _ in range(3):
        wu.append(["rascunho"])
    wu.append(COLS_USINAS)
    for linha in USINAS:
        wu.append([""] + list(linha))
    b = io.BytesIO()
    wb.save(b)
    b.seek(0)
    return b


@pytest.fixture
def tickets(monkeypatch):
    monkeypatch.setattr(app, "_bd_readable", lambda chave=None, fallback=None: _planilha())
    monkeypatch.setattr(app, "_tickets_marca", lambda: 1.0)
    monkeypatch.setattr(app, "TICKETS_STR", {})
    app.load_tickets_strings()
    return app.TICKETS_STR


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


def test_a_noite_mostra_so_o_total_sem_julgar_o_deficit():
    html = _js("_tkStrCel(%s,true)" % _linha_js(12, -599))
    assert ">12<" in html and "/599" not in html and "#ff5b6e" not in html


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
