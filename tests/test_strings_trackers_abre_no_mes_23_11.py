# -*- coding: utf-8 -*-
"""A tela Strings e trackers abre com o mês inteiro (23/11/2026). A Performance, na Rodrigues 2: "strings e tracker não
mostra o histórico, só o que está em aberto no momento. É necessário que haja essa visualização"; o histórico do mês
existia, mas a tela abria com o "Só parados agora" ligado. O Levi escolheu abrir com todas as ocorrências do mês (as que
voltaram e as abertas); o botão continua, para filtrar."""
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = open(os.path.join(RAIZ, "plataforma", "templates", "strings_trackers.html"), encoding="utf-8").read()


def test_a_tela_abre_com_todas_as_ocorrencias_do_mes():
    assert 'let ABA = "s", SO_AB = false,' in HTML
    assert 'data-soab="1">${ag("Só parados agora", "Só em aberto no fim do mês")}</button>' in HTML   # o filtro segue
