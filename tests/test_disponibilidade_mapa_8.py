# -*- coding: utf-8 -*-
"""/gerencial/disponibilidade — pedidos do Levi em 13/09/2026:

3. "melhore o design desse scroll tanto em Disponibilidade por usina quanto em Mapa diário · usina × dia";
4. "Em Mapa diário limite uma visão de 8 em 8 usinas, ordenado por ordem alfabética, a pessoa vai passando por seta.
   Deixe o tamanho perfeito para mostrar 8 usinas";
5. "quero que seja possível filtrar a usina".

O template é autocontido (CSS + JS na própria página); as decisões de tela ficam pinadas aqui, como nos outros testes de
front do repositório.
"""
import pathlib
import re

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
DISP = (RAIZ / "plataforma" / "templates" / "disponibilidade.html").read_text(encoding="utf-8")


def _css(seletor):
    m = re.search(re.escape(seletor) + r"\{([^}]*)\}", DISP)
    assert m, f"sem regra CSS para {seletor}"
    return m.group(1)


def test_scroll_das_barras_e_do_mapa_tem_barra_fina_no_tema():
    for sel in (".barras", ".heat-scroll"):
        assert "scrollbar-width:thin" in _css(sel), f"{sel} ainda usa a barra de rolagem nativa"
        assert f"{sel}::-webkit-scrollbar" in DISP and f"{sel}::-webkit-scrollbar-thumb" in DISP, sel
    assert "max-height" not in _css(".heat-scroll"), "o mapa não rola mais na vertical: são 8 usinas por página"


def test_mapa_diario_mostra_8_usinas_por_pagina_em_ordem_alfabetica_com_setas():
    assert "POR_PAG: 8" in DISP
    assert "localeCompare(b.usina, 'pt-BR'" in DISP, "a ordem do mapa tem que ser alfabética (o resto da página é pior→melhor)"
    assert 'id="heatAnt"' in DISP and 'id="heatProx"' in DISP and 'id="heatPos"' in DISP
    assert "function heatPagina(" in DISP
    # altura fixa: linha de 30 px, sem aspect-ratio (variava com a largura da janela)
    assert "grid-auto-rows:30px" in _css(".heat")
    assert "aspect-ratio" not in _css(".cel")


def test_mapa_diario_filtra_por_usina():
    assert 'id="heatFiltro"' in DISP and "function heatFiltrar(" in DISP
    assert 'list="heatUsinas"' in DISP and 'id="heatUsinas"' in DISP    # sugestões com os nomes do recorte atual
