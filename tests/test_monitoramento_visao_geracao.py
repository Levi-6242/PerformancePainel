# -*- coding: utf-8 -*-
"""Monitoramento · botão "Geração" no drill-down da usina (Levi, 13/09/2026; mockup aprovado no mesmo dia).

"Quando eu clico na usina e dá o drill down ainda aparece uma visão de strings, estava pensando em incluir uma visão
alternativa nesses casos. Um botão de 'Geração' e aí aparecerá os inversores em barras de geração, eu poderei filtrar
os dias para analisar, e ao lado dessas barras deve ter a especificação de desvios!"

A página é o HTML do redesign (relido a cada requisição, sem restart); as decisões de tela ficam pinadas aqui.
"""
import pathlib

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
MON = (RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")


def test_drill_down_tem_o_seletor_strings_geracao_e_guarda_a_escolha_entre_usinas():
    assert "invView:'strings'" in MON, "a visão padrão do drill-down continua sendo Strings"
    assert "setInvView('strings')" in MON and "setInvView('geracao')" in MON
    assert "ativas <b" in MON, "a visão Strings (ativas · esp · dif) não pode sumir"


def test_geracao_le_o_historico_por_inversor_do_banco_e_nao_a_api_ao_vivo():
    assert "/inversores/historico/" in MON.split("function loadInvHist")[1].split("\n")[0:6].__str__(), \
        "as barras vêm do histórico por inversor (BD_Thopen/BD_Performance, dias fechados)"
    assert "sem base por inversor" in MON, "usina sem coluna por inversor na BD avisa em vez de mostrar barras vazias"


def test_filtro_de_dias_ontem_7_dias_mes_e_de_ate():
    for ficha in ("q('ontem','Ontem')", "q('7d','7 dias')", "q('mes','Mês')"):
        assert ficha in MON, ficha
    assert "setInvGerModo(" in MON and "window.setInvGerIni=" in MON and "window.setInvGerFim=" in MON


def test_padrao_30d_do_drill_down_e_buscado_pela_fonte_e_nao_pelo_nome_do_chip():
    """A coluna Padrão 30d (e os spans 'ontem · padrão · Δ' da visão Strings) dependem de RD.invPadrao, buscado em
    buildInversores. A guarda comparava state.source com 'pv', mas a fonte da API PV se chama 'thopen-pv' (SKEY→'pv'):
    a busca nunca rodava e o drill-down da Céu Azul III mostrava 'ativas — esp — dif —' em vez do padrão (print do Levi,
    13/09/2026)."""
    assert "SKEY[state.source]==='pv'&&_urow&&(_urow.sem_visao||_urow.inv_padrao)" in MON
    assert "state.source==='pv'&&_urow" not in MON


def test_desvio_tem_as_faixas_do_mockup():
    bloco = MON.split("function _gerFaixa")[1].split("}")[0]
    for lim in ("-5", "-10", "-20"):
        assert lim in bloco, f"faixa {lim} % sumiu da régua do desvio"
    assert "vs. mediana" in MON or "mediana" in MON
