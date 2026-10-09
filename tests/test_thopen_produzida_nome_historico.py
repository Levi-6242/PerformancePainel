# -*- coding: utf-8 -*-
"""Produzida dos anos anteriores no 5080: o nome da usina na aba `Historico` (09/10/2026).

POR QUE ESTE TESTE EXISTE
Levi, 09/10: "O dado de Produzida 2025 sumiu do dash do cliente". Era a Nova Londrina: a aba `Historico` guarda a
produção de 2025 como "Nova Londrina 1", enquanto 2024, as metas, o FC e o PR estão como "Nova Londrina". O 5080
procurava o nome exato e o ano sumia, calado. O mesmo em Rondonópolis ("Rondonopolis"), Monte Aprazível (2023/2024
como "Monte APrazivel"/"Monte Aprazivel"), Poconé 1 ("Poconé"), Vargem Grande 1 ("Vargem Grande") e Araçoiaba da Serra
1/2 ("A"/"B").

As réguas que este teste tranca:
  1. o ano gravado com o outro nome APARECE (mensal e anual);
  2. o ano que existe no nome do 5080 VENCE o outro nome — nunca soma os dois (seria o ano em dobro);
  3. o de-para é explícito: usina que não está nele não pega linha de nome parecido ("Nova Londrina 2" não vira a
     Nova Londrina, nem "Primavera 1" a Primavera).
"""
import dashboard_thopen as dt

HDR = ["Usina", "Ano", "Mês", "Tipo", "Valor"]


def _m(ano, mes):
    return dt.dt.datetime(ano, mes, 1)


def _liga(monkeypatch, linhas):
    monkeypatch.setattr(dt, "_table", lambda nome: (HDR, linhas) if nome == "Historico" else (None, []))


def test_ano_com_outro_nome_aparece_no_mensal_e_no_anual(monkeypatch):
    _liga(monkeypatch, [
        ["Nova Londrina", 2024, _m(2024, 1), "Produzida (2024)", 325740.0],
        ["Nova Londrina 1", 2025, _m(2025, 1), "Produzida (2025)", 877950.0],
        ["Nova Londrina 1", 2025, _m(2025, 2), "Produzida (2025)", 811043.0],
        ["Nova Londrina", 2025, _m(2025, 1), "Meta (2025)", 895868.0],
    ])
    assert dt._produzida_mensal("Nova Londrina", 2025) == {1: 877950.0, 2: 811043.0}
    assert dt._produzida_mensal("Nova Londrina", 2024) == {1: 325740.0}
    assert dt._produzida_anual("Nova Londrina") == {"2024": 325740.0, "2025": 1688993.0}


def test_nome_do_5080_vence_e_nunca_soma(monkeypatch):
    _liga(monkeypatch, [
        ["Rondonópolis", 2025, _m(2025, 3), "Produzida (2025)", 100.0],
        ["Rondonopolis", 2025, _m(2025, 3), "Produzida (2025)", 100.0],
        ["Rondonopolis", 2024, _m(2024, 3), "Produzida (2024)", 70.0],
    ])
    assert dt._produzida_mensal("Rondonópolis", 2025) == {3: 100.0}
    assert dt._produzida_mensal("Rondonópolis", 2024) == {3: 70.0}
    assert dt._produzida_anual("Rondonópolis") == {"2025": 100.0, "2024": 70.0}


def test_um_ano_em_cada_grafia(monkeypatch):
    # Monte Aprazível: 2023 como "Monte APrazivel", 2024 como "Monte Aprazivel", 2025 com o nome certo
    _liga(monkeypatch, [
        ["Monte APrazivel", 2023, _m(2023, 5), "Produzida (2023)", 10.0],
        ["Monte Aprazivel", 2024, _m(2024, 5), "Produzida (2024)", 20.0],
        ["Monte Aprazível", 2025, _m(2025, 5), "Produzida (2025)", 30.0],
    ])
    assert [dt._produzida_mensal("Monte Aprazível", a) for a in (2023, 2024, 2025)] == [{5: 10.0}, {5: 20.0}, {5: 30.0}]


def test_de_para_explicito_nao_pega_nome_parecido(monkeypatch):
    _liga(monkeypatch, [
        ["Nova Londrina 2", 2025, _m(2025, 1), "Produzida (2025)", 5.0],
        ["Primavera 1", 2025, _m(2025, 1), "Produzida (2025)", 7.0],
        ["Araçoiaba da Serra A", 2025, _m(2025, 1), "Produzida (2025)", 11.0],
        ["Araçoiaba da Serra B", 2025, _m(2025, 1), "Produzida (2025)", 13.0],
    ])
    assert dt._produzida_mensal("Nova Londrina", 2025) == {}
    assert dt._produzida_mensal("Primavera", 2025) == {}
    # Levi, 09/10: A = Araçoiaba da Serra 1 (THPN-ADS100), B = 2 (THPN-ADS200)
    assert dt._produzida_mensal("Araçoiaba da Serra 1", 2025) == {1: 11.0}
    assert dt._produzida_mensal("Araçoiaba da Serra 2", 2025) == {1: 13.0}
