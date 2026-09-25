# -*- coding: utf-8 -*-
"""As colunas da tabela de strings em tempo real (Levi, 25/09/2026).

1. "pode tirar a coluna de disponibilidade das strings em tempo real". Era ativas ÷ esperadas em %, o mesmo número da
   Diferença dito de outro jeito — e com o cadastro errado passava de 100% (Xavantina 2, 25/09: 102,1%). A tabela é um
   componente só para as 9 fontes, então sai de todas: o cabeçalho, a célula e os campos da linha. As linhas que ocupam
   a largura toda (carregando, filtro sem resultado, a usina aberta) passam de 10 para 9 colunas. A "Disponibilidade"
   da tabela de TRACKERS é outra coisa (por tempo) e fica.
2. "quero a coluna de STATUS antes do nome da USINA". O status vira a 1ª coluna — no cabeçalho e na linha.
"""
import pathlib
import re

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
MON = (RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")

ORDEM = ["Status", "Usina", "Inv.", "Ativas", "Esperadas", "Diferença", "Acomp.", "Tickets", "Última leitura"]


def _cabecalho():
    i = MON.index('<th style="text-align:right">Esperadas</th>')
    return MON[MON.rindex("<thead><tr>", 0, i):MON.index("</tr></thead>", i)]


def _linha():
    i = MON.index('<tr class="gc-urow')
    return MON[i:MON.index("</tr>", i)]


def test_as_colunas_na_ordem_nova():
    assert re.findall(r"<th[^>]*>([^<]*)</th>", _cabecalho()) == ORDEM


def test_a_linha_segue_o_cabecalho():
    tds = re.split(r"<td\b", _linha())[1:]
    assert len(tds) == len(ORDEM)
    assert "${u.status}" in tds[0], "o status é a 1ª célula"
    assert "${u.name}" in tds[1] and "ph-caret-right" in tds[1], "a usina (com a seta de abrir) é a 2ª"
    assert "${u.lastRead}" in tds[-1], "a última leitura fecha a linha"


def test_a_linha_nao_calcula_nem_desenha_a_disponibilidade():
    assert "u.avail" not in MON and "availColor" not in MON
    m = MON[MON.index("usinas=pv.rows.filter("):]
    assert "avail:" not in m[:m.index("}).sort(")]


def test_as_linhas_de_largura_toda_tem_9_colunas():
    assert '<tr><td colspan="9" style="padding:44px;text-align:center" class="text-muted"><i class="ph ph-circle-notch gc-spin"></i> Coletando dados da fonte' in MON
    sem = MON[MON.index("function _semLinhas("):]
    assert 'colspan="9"' in sem[:sem.index("\n}\n")]
    assert '${u.expanded?`<tr><td colspan="9" style="padding:0;border:0">' in MON


def test_a_disponibilidade_dos_trackers_continua():
    assert '<th style="text-align:right">Disponibilidade</th>' in MON
