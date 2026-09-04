# -*- coding: utf-8 -*-
"""Corte "Histórico Carteira" x aba diária no dashboard Thopen (5080).

POR QUE ESTES TESTES EXISTEM (04/09/2026): o cliente avisou que junho e julho dos Pharmas
sumiram do gráfico. O dado estava na aba de histórico o tempo todo — quem descartava era uma
régua de DATA FIXA (01/06) que mandava usar a aba diária a partir dali. Nos Pharmas a aba
diária só começa em 01/08, 27/08 ou nunca, então os dois meses caíam num vão.

A régua virou POR USINA. O que estes testes travam é justamente a promessa que ela carrega:
usina nova entra sozinha, sem ninguém mexer em código. Cada teste abaixo é um caso real que
existe hoje na aba "Histórico Carteira".
"""
import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "thopen"))

import dashboard_thopen as D  # noqa: E402

ANO = D.ANO


def _bd(*pares):
    """Monta o dict {data: registro} que _corte_da_usina recebe. `pares` = (dia_do_ano, ger)."""
    return {d: {"data": d, "ger": g} for d, g in
            ((dt.date(ANO, m, dd), g) for m, dd, g in pares)}


def test_emenda_perfeita_continua_na_data_fixa():
    """Santo Antonio / Sarandi / Segredo: histórico até 31/05, aba diária começa em 01/06.
    A data fixa vence e o comportamento tem de ficar IDÊNTICO ao de antes da mudança."""
    bd = _bd((6, 1, 1000.0), (6, 2, 1100.0), (7, 1, 1200.0))
    assert D._corte_da_usina(bd) == dt.date(ANO, 6, 1)


def test_aba_que_comeca_depois_usa_o_historico_ate_la():
    """Pharma II: aba diária só começa em 01/08. Sem isto, junho e julho somem do gráfico."""
    bd = _bd((8, 1, 3000.0), (8, 2, 3100.0), (9, 1, 2500.0))
    assert D._corte_da_usina(bd) == dt.date(ANO, 8, 1)


def test_aba_sem_geracao_nenhuma_deixa_o_historico_valer_o_ano_todo():
    """Pharma III: a aba existe (linhas criadas) mas não tem geração alguma.
    `date.max` faz todo dia do ano cair no ramo do histórico."""
    bd = _bd((8, 1, None), (8, 2, 0.0), (9, 1, None))
    assert D._corte_da_usina(bd) == dt.date.max


def test_linha_vazia_nao_conta_como_inicio():
    """As abas nascem com o mês inteiro em branco (rotina mensal de criar linhas). Se linha
    nula ou zero contasse como início, o corte voltaria para 01/08 e o buraco reapareceria —
    era exatamente o caso do Pharma IV, cuja aba tem linhas desde 01/08 mas só gera em 27/08."""
    bd = _bd((8, 1, None), (8, 15, 0.0), (8, 27, 900.0), (8, 28, 950.0))
    assert D._corte_da_usina(bd) == dt.date(ANO, 8, 27)


def test_usina_nova_so_com_historico_nao_precisa_de_codigo():
    """A promessa: usina que entra hoje, com o cliente mandando o mensal e sem aba diária
    ainda, aparece inteira sem ninguém tocar em código."""
    assert D._corte_da_usina({}) == dt.date.max


def test_aba_anterior_a_data_fixa_nao_puxa_o_corte_para_tras():
    """Belo Jardim / Inhapi / Vertentes têm aba diária ANTES de 01/06 e ainda assim o
    histórico manda até lá. O max() protege isso: a data fixa é piso, não teto."""
    bd = _bd((1, 14, 800.0), (5, 1, 900.0), (6, 1, 1000.0))
    assert D._corte_da_usina(bd) == dt.date(ANO, 6, 1)


def test_ignora_dado_de_outro_ano():
    """A aba diária guarda anos anteriores. Só o ano do relatório decide o corte."""
    bd = {dt.date(ANO - 1, 3, 1): {"data": dt.date(ANO - 1, 3, 1), "ger": 5000.0},
          dt.date(ANO, 8, 1): {"data": dt.date(ANO, 8, 1), "ger": 3000.0}}
    assert D._corte_da_usina(bd) == dt.date(ANO, 8, 1)


@pytest.mark.parametrize("usina", ["Pharma II", "Pharma III", "Pharma IV"])
def test_pharmas_tem_junho_e_julho_de_ponta_a_ponta(usina):
    """Teste de integração contra o BD real: é o sintoma que o cliente relatou.
    Pulado se o BD_Thopen não estiver acessível (CI sem OneDrive/API)."""
    try:
        recs = D._daily_records_todos(usina)
    except Exception as e:                       # noqa: BLE001
        pytest.skip("BD_Thopen indisponível: %s" % str(e)[:60])
    if not recs:
        pytest.skip("sem registros para %s" % usina)
    meses = {r["data"].month for r in recs
             if r["data"].year == ANO and isinstance(r.get("ger"), (int, float)) and r["ger"] > 0}
    assert 6 in meses, "junho vazio em %s — o vão do corte voltou" % usina
    assert 7 in meses, "julho vazio em %s — o vão do corte voltou" % usina
