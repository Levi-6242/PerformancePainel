# -*- coding: utf-8 -*-
"""O cabeçalho do Dashboard Thopen em duas faixas (Levi, 26/10/2026: "estou achando esse cabeçalho meio bagunçado";
"Proposta A com certeza!"). Em cima, as páginas numa linha só, com a Metodologia (consulta) à direita; embaixo, carteira,
usina e mês com o rótulo ao lado, a hora dos dados numa linha e as ações da mesma altura (Atualizar em ícone, PDF da
carteira e PDF da usina). No celular as abas rolam na faixa delas e as ações descem para uma linha própria."""
import os
import re

AQUI = os.path.dirname(__file__)
T = open(os.path.join(AQUI, "..", "thopen", "templates", "dashboard_thopen.html"), encoding="utf-8").read()


def _faixa(ini, fim):
    return T[T.index(ini):T.index(fim, T.index(ini))]


def test_paginas_numa_faixa_com_a_metodologia_a_direita():
    nav = _faixa('<nav class="nav"', "</nav>")
    ordem = [m for m in re.findall(r'data-page="(\w+)"', nav)]
    assert ordem == ["capa", "geral", "mensal", "diario", "registros", "zeladoria", "metodologia"]
    assert nav.index('class="nav-sep"') < nav.index('data-page="metodologia"')
    assert 'role="tablist"' in nav and nav.count('role="tab"') == 7


def test_filtros_e_acoes_na_segunda_faixa():
    bar = _faixa('<div class="toolbar">', '<!-- ───────────── PÁGINA MENSAL')
    for i in ("fldCarteira", "fldUsina", "fldMes", "subinfo", "btnRefresh", "btnPdfAll", "btnPdf"):
        assert 'id="%s"' % i in bar, i
    assert bar.index('id="btnPdfAll"') < bar.index('id="btnPdf"')              # o principal por último, à direita
    assert ">PDF da carteira<" in bar and ">PDF da usina<" in bar
    assert 'aria-label="Atualizar"' in bar
    assert "🔄" not in bar and "⤓" not in bar                                    # sem emoji: ícone em SVG


def test_rotulo_dos_botoes_muda_sem_apagar_o_icone():
    # o PDF da carteira diz "Montando 3/59…" no rótulo (.rb); trocar o textContent do botão apagava o SVG
    assert "btn.textContent=" not in T
    assert "querySelector('.rb')" in T and "classList.add('girando')" in T


def test_a_faixa_das_paginas_some_na_impressao():
    i = T.index("@page{ size:A4 landscape")
    assert ".nav, .toolbar{ display:none !important; }" in T[i:i + 600]


def test_mes_e_hora_dos_dados_curtos():
    assert "MESCURTO[mm]" in T and "' às '" in T
    assert "Dados de: " not in T


def test_no_celular_a_faixa_vira_grade():
    assert re.search(r"@media \(max-width:760px\)\{[^@]*\.toolbar\{ display:grid;", T)
