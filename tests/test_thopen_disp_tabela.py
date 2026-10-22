# -*- coding: utf-8 -*-
"""A tabelinha da Disponibilidade Usina (Levi, 22/10/2026: "um ícone de tabelinha no canto superior direito; ao clicar
mostra os dias do período e a disponibilidade! os que é abaixo de 100% mostra o comentário").

As réguas: o ícone fica no card da Disponibilidade, só de 10/2026 em diante e só com a disponibilidade pelas OS na
resposta do card (a mesma do valor do card); a janela lista os dias do mês até o último com disponibilidade, o comentário
só no dia abaixo de 100% (as mesmas frases das OS da tabela de Comentários) e a média do mês no fim; o ícone e a janela
ficam fora do PDF, como o das fotos das rondas. Texto do HTML, sem navegador.
"""
import os

AQUI = os.path.dirname(__file__)
H = open(os.path.join(AQUI, "..", "thopen", "templates", "dashboard_thopen.html"), encoding="utf-8").read()


def _corpo(nome):
    i = H.index("function %s(" % nome)
    return H[i:H.index("\n}\n", i)]


def test_icone_no_card_da_disponibilidade_e_fora_do_pdf():
    i = H.index('id="dispCard"')
    card = H[i:H.index("</div>", H.index('id="disp"', i))]
    assert 'id="dispTab"' in card and 'class="op-fotos hidden"' in card    # o botão das fotos: fora da folha
    assert ".disp-card{" in H


def test_a_janela_lista_os_dias_e_o_comentario_so_abaixo_de_100():
    j = _corpo("abrirDisponibilidade")
    assert "_opPorDia(" in j and "disponibilidade" in j
    assert "<100" in j and "r.os" in j                                     # o comentário só no dia abaixo de 100%
    assert "Média do mês" in j
    assert 'id="dpFundo"' in H and "rd-fundo" in H[H.index('id="dpFundo"') - 40:H.index('id="dpFundo"')]


def test_o_icone_so_aparece_de_outubro_em_diante_com_a_disponibilidade_das_os():
    d = H[H.index("async function renderDiario("):]
    d = d[:d.index("\n}\n")]
    assert "dispTab" in d and "202610" in d
