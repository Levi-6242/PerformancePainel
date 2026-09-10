# -*- coding: utf-8 -*-
"""A aba Curvas do Diagnóstico tem de NASCER em Strings e ficar lá até alguém clicar (Levi, 08/09/2026).

Achado da varredura de 09/09: o guard `mostrar!==false` foi acrescentado no topo de `drawCurveById`, mas a linha
antiga — um `setCurvaVista('corr')` incondicional — sobreviveu logo abaixo e anulava o guard. A auto-carga do pior
tracker (renderTrackers) continuava arrastando a tela para a Correlação um segundo depois de abrir.

Passou despercebido na verificação manual porque a usina usada na prévia (Ipixuna 1) não tinha tracker anormal —
a auto-carga nunca disparou. Estes testes são de ESTRUTURA do template: não dependem de qual usina abre.
"""
import pathlib
import re

V = pathlib.Path(__file__).resolve().parents[1] / "plataforma" / "templates" / "painel_usina_v2.html"


def _fonte():
    return V.read_text(encoding="utf-8")


def _corpo(nome):
    """Corpo da função JS `nome` até a próxima declaração de função no mesmo nível (heurística boa o bastante
    para este arquivo, onde as funções de topo começam na coluna 0)."""
    src = _fonte()
    i = src.index(f"function {nome}(")
    j = src.find("\nfunction ", i + 1)
    k = src.find("\nasync function ", i + 1)
    fim = min(x for x in (j, k, len(src)) if x > 0)
    return src[i:fim]


def test_drawcurvebyid_so_troca_a_vista_quando_mandam_mostrar():
    """UMA chamada a setCurvaVista('corr'), e guardada. Duas = a auto-carga volta a roubar a tela."""
    corpo = _corpo("drawCurveById")
    chamadas = re.findall(r"setCurvaVista\('corr'\)", corpo)
    assert len(chamadas) == 1, f"{len(chamadas)} trocas de vista em drawCurveById — o guard vira decoração"
    linha = next(l for l in corpo.splitlines() if "setCurvaVista('corr')" in l)
    assert "mostrar!==false" in linha, f"a troca de vista ficou sem guard: {linha.strip()}"


def test_auto_carga_do_pior_tracker_desenha_em_silencio():
    """renderTrackers desenha o pior tracker sozinho; tem de passar mostrar=false."""
    src = _fonte()
    m = re.search(r"drawCurveById\(ts\[0\]\.id[^)]*\)", src)
    assert m, "a auto-carga do pior tracker sumiu do renderTrackers"
    assert "false" in m.group(0), f"a auto-carga voltou a trazer a vista para a frente: {m.group(0)}"


def test_a_vista_padrao_e_strings_nos_tres_lugares_que_precisam_concordar():
    """O estado inicial mora em três lugares; se um discordar, o botão aceso não é o bloco visível."""
    src = _fonte()
    assert "let _curvaVista='str'" in src, "a vista padrão saiu de Strings"
    assert re.search(r"icModo='str'", src), "o modo da curva por inversor saiu de Strings"
    assert 'id="invBlock">' in src, "o bloco do inversor/strings nasceu escondido"
    assert 'id="corrBlock" style="display:none"' in src, "o bloco da correlação nasceu visível"


def test_botao_correlacao_saiu_do_seletor_mas_a_vista_continua_alcancavel():
    """O pedido foi tirar o BOTÃO, não a funcionalidade: o clique num tracker ainda leva à Correlação."""
    src = _fonte()
    assert 'id="vsCorr"' not in src, "o botão Correlação voltou ao seletor"
    v2trk = next((l for l in src.splitlines() if l.startswith("window.v2Trk=")), "")
    assert "setCurvaVista('corr')" in v2trk, f"o clique no tracker perdeu a Correlação: {v2trk[:120]}"
    assert "['vsInv','inv'],['vsStr','str']" in src, "o laço dos botões não bate com os botões existentes"
