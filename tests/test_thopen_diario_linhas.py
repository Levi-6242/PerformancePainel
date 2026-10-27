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


def test_de_outubro_em_diante_so_o_ipoa_medido():
    # 27/10/2026 (Levi: "tira o possível pelo POA e deixa só o POA medido mesmo!"): a linha da possível saiu do gráfico
    f = _funcao("_desenhaDiario")
    assert "Possível pelo IPOA" not in f and "p.possivel" not in f and "'IPOA medido (kWh/m²)'" in f
    # o IPOA medido é o mesmo que gera a possível (ETM ou GHI), no eixo da direita, com a fonte no mouse
    assert "p.ipoa_med" in f and "p.fonte_ipoa" in f and re.search(r"yaxis:\s*'y2'", f)


def test_o_zero_do_ipoa_casa_com_o_zero_da_energia():
    f = _funcao("_desenhaDiario")
    assert "range:[0," in f and "rangemode:'nonnegative'" in f


def test_sem_botoes_em_cima_so_a_legenda():
    # 27/10/2026 (Levi: "tire esses botões de cima também, deixe só a legenda!")
    h = _html()
    assert 'id="glSel"' not in h and "gl-chip" not in h and "plotly_legendclick" in h


def test_a_escolha_fica_guardada_e_vale_para_o_pdf():
    h = _html()
    # guardada no navegador (try/catch: aba anônima ou bloqueio), relida em cada usina do PDF Carteira
    assert "localStorage.getItem('thopen_linhas')" in h and "localStorage.setItem('thopen_linhas'" in h
    f = _funcao("_desenhaDiario")
    assert "_LINHAS" in f
    # a linha tirada sai do gráfico (e da legenda), não fica cinza na folha
    # na tela a linha tirada fica cinza na legenda (para voltar); na folha (body.printing) ela sai de vez
    assert "legendonly" in f and "classList.contains('printing')" in f


def test_clicar_na_legenda_tambem_tira_a_linha():
    assert "plotly_legendclick" in _html()


def test_metodologia_fala_das_duas_linhas_e_do_seletor():
    h = _html()
    met = h[h.index('id="pageMetodologia"'):h.index('id="pageRegistros"')]
    assert "IPOA medido (linha" in met and "escolhe" in met


def test_linha_do_ipoa_preta_e_solida():
    f = _funcao("_desenhaDiario")
    assert "line:{color:'#222',width:esp?2:1.5}" in f and "dash" not in f
