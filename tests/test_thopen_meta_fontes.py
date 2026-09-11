# -*- coding: utf-8 -*-
"""Meta 2026 do 5080: a aba `Historico` manda, a `Historico_2026` é reserva (10/09/2026).

POR QUE ESTE TESTE EXISTE
A Cipó Guaçu apareceu "sem meta" no dashboard do cliente enquanto os 12 meses dela estavam na aba
`Historico` desde sempre. A causa: o `_meta2026` lia SÓ a `Historico_2026`, que é **saída de Power
Query** ("Consulta - Historico") e só se refaz quando um humano abre o Excel e manda atualizar.
Nada falhava — a usina simplesmente vinha sem meta, calada.

As quatro réguas que este teste tranca:
  1. meta que está na `Historico` e não na tabela derivada APARECE (o caso Cipó Guaçu);
  2. usina que existe SÓ na tabela derivada continua com meta (Caicó, Diamantino, Itajá) — foi por
     isso que a reserva ficou, em vez de trocar de fonte;
  3. a mesclagem é CAMPO A CAMPO: campo vazio na `Historico` não apaga o da tabela (caso Lyon, com
     PR preenchido num lado e vazio no outro);
  4. o de-para de nome casa cadastro × meta sem renomear nada (caso Boa Viagem I 1).
"""
import pytest

import dashboard_thopen as dt


HDR_LONGO = ["Usina", "Ano", "Mês", "Tipo", "Valor"]
HDR_LARGO = ["Usina", "Ano", "Mês", "FC (2026)", "Meta (2026)",
             "Meta Irradiação (2026)", "PR (2026)"]


def _mes(m):
    return dt.dt.datetime(2026, m, 1)


def _liga(monkeypatch, longo, largo):
    """Troca o `_table` pelas duas tabelas sintéticas e limpa o cache do pivô."""
    def fake(nome):
        if nome == "Historico":
            return HDR_LONGO, longo
        if nome == "Historico_2026":
            return HDR_LARGO, largo
        return None, []
    monkeypatch.setattr(dt, "_table", fake)
    dt._state["df"].pop(("hist_piv",), None)
    dt._state["df"].pop(("meta_tbl",), None)


def test_meta_da_aba_historico_aparece_sem_a_tabela_derivada(monkeypatch):
    """Caso Cipó Guaçu: a consulta nunca foi atualizada, mas a meta está na `Historico`."""
    longo = [
        ["Cipó Guaçu", 2026, _mes(4), "Meta (2026)", 54797.06],
        ["Cipó Guaçu", 2026, _mes(4), "Meta Irradiação (2026)", 132.8],
        ["Cipó Guaçu", 2026, _mes(4), "PR (2026)", 0.794],
        ["Cipó Guaçu", 2026, _mes(4), "FC (2026)", 0.0],
        # tipo de outro ano tem de ser ignorado
        ["Cipó Guaçu", 2025, _mes(4), "Meta (2025)", 999999.0],
        # o Tipo chega com espaço sobrando em parte das linhas do arquivo real
        ["Cipó Guaçu", 2026, _mes(5), " Meta (2026) ", 208103.75],
    ]
    _liga(monkeypatch, longo, largo=[])
    m = dt._meta2026("Cipó Guaçu")
    assert m[4]["meta"] == pytest.approx(54797.06)
    assert m[4]["metairr"] == pytest.approx(132.8)
    assert m[4]["pr"] == pytest.approx(0.794)
    assert m[5]["meta"] == pytest.approx(208103.75)      # sobreviveu ao espaço no Tipo
    assert 2025 not in m and 999999.0 not in [e["meta"] for e in m.values()]


def test_usina_so_na_tabela_derivada_mantem_a_meta(monkeypatch):
    """Caso Caicó/Diamantino/Itajá: não estão na `Historico`. Trocar de fonte apagaria a meta."""
    largo = [["Caicó", 2026, _mes(7), 0.19, 241590.0, 150.9, 0.86]]
    _liga(monkeypatch, longo=[], largo=largo)
    m = dt._meta2026("Caicó")
    assert m[7]["meta"] == pytest.approx(241590.0)
    assert m[7]["pr"] == pytest.approx(0.86)


def test_mesclagem_e_campo_a_campo_e_historico_ganha(monkeypatch):
    """Caso Lyon: PR só na `Historico`; a tabela derivada tem o resto e um valor desatualizado."""
    longo = [
        ["Lyon", 2026, _mes(1), "PR (2026)", 0.724],
        ["Lyon", 2026, _mes(1), "Meta (2026)", 820278.25],
    ]
    largo = [["Lyon", 2026, _mes(1), 0.1575, 820000.0, 164.6, None]]
    _liga(monkeypatch, longo, largo)
    m = dt._meta2026("Lyon")
    assert m[1]["pr"] == pytest.approx(0.724)            # veio só da Historico
    assert m[1]["metairr"] == pytest.approx(164.6)       # veio só da tabela
    assert m[1]["fc"] == pytest.approx(0.1575)           # a Historico não tem FC: não apagou
    assert m[1]["meta"] == pytest.approx(820278.25)      # a Historico é mais nova e ganha


def test_de_para_de_nome_acha_a_meta_sem_renomear(monkeypatch):
    """Caso Boa Viagem: cadastro diz "Boa Viagem I 1", a meta veio como "Boa Viagem 1"."""
    longo = [["Boa Viagem 1", 2026, _mes(7), "Meta (2026)", 516952.5]]
    _liga(monkeypatch, longo, largo=[])
    assert dt._meta2026("Boa Viagem I 1")[7]["meta"] == pytest.approx(516952.5)
    # e sem o de-para não pode casar por acidente: nome de outra usina segue sem meta
    assert dt._meta2026("Ouro Branco 1") == {}


def test_nome_casa_ignorando_acento_e_caixa(monkeypatch):
    longo = [["CIPO  GUACU", 2026, _mes(3), "Meta (2026)", 123.0]]
    _liga(monkeypatch, longo, largo=[])
    assert dt._meta2026("Cipó Guaçu")[3]["meta"] == pytest.approx(123.0)


def test_usina_sem_meta_em_lugar_nenhum_volta_vazio(monkeypatch):
    _liga(monkeypatch, longo=[], largo=[])
    assert dt._meta2026("Alvares Machado") == {}
