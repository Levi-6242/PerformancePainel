# -*- coding: utf-8 -*-
"""Diagnóstico de performance (painel_usina_v2): a linha do inversor não pode quebrar em nenhuma coluna — só
"Ocorrências · OS" (Levi, 14/09/2026: "a única que pode quebrar é a coluna ocorrências - OS"). Antes o nome
("Inversor 1.10") e a coluna "Agora" quebravam quando a tabela apertava."""
import pathlib

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
HTML = (RAIZ / "plataforma" / "templates" / "painel_usina_v2.html").read_text(encoding="utf-8")


def test_a_linha_do_inversor_trava_a_quebra_e_libera_so_ocorrencias():
    # nowrap em toda a linha de inversor; a penúltima coluna (Ocorrências · OS) volta a poder quebrar.
    # Escopo em #v2InvBody + :not(.v2h) para não pegar as tabelas de trackers e de histórico, que também usam tr.l.
    assert "#v2InvBody table.v2t:not(.v2h)>tbody>tr.l>td{white-space:nowrap}" in HTML
    assert "#v2InvBody table.v2t:not(.v2h)>tbody>tr.l>td:nth-last-child(2){white-space:normal}" in HTML


def test_ocorrencias_e_a_penultima_coluna():
    # o :nth-last-child(2) só solta a coluna certa se Ocorrências for a penúltima (antes de Leitura).
    assert '<th>Strings</th><th>Ocorrências · OS</th><th class="v2n">Leitura</th>' in HTML, \
        "Ocorrências · OS precisa ser a penúltima coluna (antes de Leitura) para o nth-last-child(2) valer"
