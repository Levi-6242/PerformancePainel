# -*- coding: utf-8 -*-
"""Gerencial (08/09/2026): dia com geração ZERO só conta como dia coberto se a IPOA medida confirmar o zero.

Em 05–07/09 as 93 usinas do BD_Thopen vieram zeradas (lacuna da coleta) e a meta prorrateada cobrava 3 dias que ninguém
mediu: Coração 2 marcava 64% com 112% nos 4 dias reais, enquanto os inversores (acumulador) mostravam ~88% — "quer ser
coerente!" (Levi). Zero COM sol medido continua contando: aí a usina de fato não gerou."""
import inspect

import app


def test_zero_sem_ipoa_e_lacuna_zero_com_ipoa_e_usina_parada():
    assert app._thopen_dia_coberto({"ger": 0, "ipoa": 0}) is False            # coleta não veio: não conta
    assert app._thopen_dia_coberto({"ger": 0, "ipoa": None}) is False
    assert app._thopen_dia_coberto({"ger": 0, "ipoa": 4.1}) is True            # sol medido e nada gerado: usina parada, conta
    assert app._thopen_dia_coberto({"ger": 512.0, "ipoa": None}) is True       # gerou: conta mesmo sem IPOA
    assert app._thopen_dia_coberto({"ger": None, "ipoa": 5.0}) is False        # sem registro de geração


def test_gerencial_usa_a_regra_no_denominador():
    src = inspect.getsource(app._thopen_prod_build)
    assert "_thopen_dia_coberto(r)" in src, "o denominador da meta voltou a contar zero sem IPOA"
