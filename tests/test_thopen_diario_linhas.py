# -*- coding: utf-8 -*-
"""As linhas do gráfico do Diário (Levi, 26/10/2026: "Tem como dar para ver duas linhas? a linha do POA e a linha da
projeção? para comparativo mesmo! (...) Quero que no gráfico também dê para escolher qual quer mostrar, se quer tirar
algum e não vai sair no pdf claro"). A conta continua no servidor (/api/t/diario: possivel, ipoa_med, fonte_ipoa); aqui
só a tela: a linha do IPOA medido no eixo da direita ao lado da geração possível, o seletor das linhas fora da folha e a
escolha valendo para o PDF."""
import os
import re

AQUI = os.path.dirname(__file__)


def _html():
    return open(os.path.join(AQUI, "..", "thopen", "templates", "dashboard_thopen.html"), encoding="utf-8").read()


def _funcao(nome):
    h = _html()
    i = h.index("function %s(" % nome)
    return h[i:h.index("\n}\n", i)]


def test_de_outubro_em_diante_a_possivel_e_o_ipoa_medido_juntos():
    f = _funcao("_desenhaDiario")
    assert "'Possível pelo IPOA (kWh)'" in f and "'IPOA medido (kWh/m²)'" in f
    # o IPOA medido é o mesmo que gera a possível (ETM ou GHI), no eixo da direita, com a fonte no mouse
    assert "p.ipoa_med" in f and "p.fonte_ipoa" in f and re.search(r"yaxis:\s*'y2'", f)


def test_o_zero_do_ipoa_casa_com_o_zero_da_energia():
    f = _funcao("_desenhaDiario")
    assert "range:[0," in f and "rangemode:'nonnegative'" in f


def test_seletor_das_linhas_no_card_e_fora_da_folha():
    h = _html()
    card = h[h.index('id="grafCard"'):h.index('id="chDiario"')]
    assert 'id="glSel"' in card
    assert "body.printing .gl-sel, #printArea .gl-sel{ display:none !important; }" in h
    assert re.search(r"@media print\{[^}]*\.gl-sel", h)


def test_a_escolha_fica_guardada_e_vale_para_o_pdf():
    h = _html()
    # guardada no navegador (try/catch: aba anônima ou bloqueio), relida em cada usina do PDF Carteira
    assert "localStorage.getItem('thopen_linhas')" in h and "localStorage.setItem('thopen_linhas'" in h
    f = _funcao("_desenhaDiario")
    assert "_LINHAS" in f
    # a linha tirada sai do gráfico (e da legenda), não fica cinza na folha
    assert "legendonly" not in f


def test_clicar_na_legenda_tambem_tira_a_linha():
    assert "plotly_legendclick" in _html()


def test_metodologia_fala_das_duas_linhas_e_do_seletor():
    h = _html()
    met = h[h.index('id="pageMetodologia"'):h.index('id="pageRegistros"')]
    assert "IPOA medido (linha" in met and "escolhe" in met
