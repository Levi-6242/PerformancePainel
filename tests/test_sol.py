# -*- coding: utf-8 -*-
"""Sensor de sol por ESTADO (sol.py, 10/09/2026): elevação solar pelo centroide da UF, para separar "usina parada"
de "anoiteceu". Motivação medida em 10/09 às 17:52: 89 de 102 usinas 'críticas' no macro e 300 eventos 'string zerou'
numa leitura só do sino — era o pôr do sol (setembro, ~17:50 em SP) entrando numa janela fixa 07–18h / até 18:20.

Valores de referência (NOAA): São Paulo 10/09/2026 — nascer ~06:10, pôr ~17:56 (hora de Brasília, sem horário de
verão). Belém (PA) fica ~1.500 km a norte/oeste: pôr ~18:20. Cuiabá (MT) está 10° a oeste de SP: o sol se põe
~40 min depois em hora de Brasília."""
from datetime import datetime

import sol


def test_meio_dia_em_sao_paulo_tem_sol_alto():
    e = sol.elevacao_estado("Sao Paulo", datetime(2026, 9, 10, 11, 50))
    assert 55 <= e <= 65, e                     # 90 − |lat − declinação| ≈ 62°


def test_por_do_sol_de_setembro_em_sao_paulo_e_sol_baixo():
    assert sol.sol_baixo("Sao Paulo", datetime(2026, 9, 10, 18, 10)) is True      # já abaixo do horizonte
    assert sol.sol_baixo("Sao Paulo", datetime(2026, 9, 10, 17, 30)) is True      # < 8° — rampa de fim de dia
    assert sol.sol_baixo("Sao Paulo", datetime(2026, 9, 10, 16, 30)) is False     # ~20°, ainda gera


def test_madrugada_e_amanhecer_sao_sol_baixo():
    assert sol.sol_baixo("Sao Paulo", datetime(2026, 9, 10, 3, 0)) is True
    assert sol.sol_baixo("Sao Paulo", datetime(2026, 9, 10, 6, 20)) is True       # nasceu há 10 min, < 8°
    assert sol.sol_baixo("Sao Paulo", datetime(2026, 9, 10, 7, 30)) is False


def test_o_oeste_ainda_tem_sol_quando_sao_paulo_ja_anoiteceu():
    """Mato Grosso (10° a oeste) e Pará (norte, dia mais longo em setembro) ainda geram às 18:10 de Brasília."""
    quando = datetime(2026, 9, 10, 18, 10)
    assert sol.elevacao_estado("Mato Grosso", quando) > sol.elevacao_estado("Sao Paulo", quando)
    assert sol.elevacao_estado("Para", quando) > sol.elevacao_estado("Sao Paulo", quando)
    assert sol.sol_baixo("Mato Grosso", datetime(2026, 9, 10, 17, 30)) is False


def test_inverno_anoitece_mais_cedo_que_verao():
    """Em junho o sol se põe ~17:30 em SP; em dezembro ~18:55. A janela fixa 07–18h errava para os dois lados:
    em junho 17:20 já é rampa (e a janela dizia 'dia'); em dezembro 17:50 ainda tem 12° de sol."""
    assert sol.sol_baixo("Sao Paulo", datetime(2026, 6, 20, 17, 20)) is True
    assert sol.sol_baixo("Sao Paulo", datetime(2026, 12, 20, 17, 50)) is False


def test_aceita_sigla_nome_e_grafia_sem_acento():
    q = datetime(2026, 9, 10, 12, 0)
    e = sol.elevacao_estado("Ceará", q)
    assert e == sol.elevacao_estado("Ceara", q) == sol.elevacao_estado("CE", q) == sol.elevacao_estado(" ceara ", q)


def test_estado_desconhecido_nao_e_sol_baixo():
    """Sem estado não há como saber a hora solar: a régua antiga (janela fixa) continua valendo lá — aqui é False."""
    assert sol.elevacao_estado(None, datetime(2026, 9, 10, 18, 10)) is None
    assert sol.sol_baixo(None, datetime(2026, 9, 10, 18, 10)) is False
    assert sol.sol_baixo("Atlântida", datetime(2026, 9, 10, 18, 10)) is False
