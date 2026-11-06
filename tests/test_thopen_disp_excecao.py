# -*- coding: utf-8 -*-
"""A disponibilidade por exceção (Levi, 06/11/2026: "pegue a disponibilidade dessas UFVs e coloque como disponibilidade
de outubro segundo a lista, será uma exceção para outubro!"): o número do dia vem do livro thopen_disp_excecao, ponderado
pelo kWp das partes, e vence as duas contas (OS e comentários do BD) só no mês que tem linha. Usinas fictícias."""
import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "thopen"))

import disp_excecao  # noqa: E402
import operacao_mes  # noqa: E402

D1, D2 = dt.date(2026, 10, 1), dt.date(2026, 10, 2)
LINHAS = [
    {"usina": "Usina A", "parte": "A 1.1 (1)", "kwp": 100, "dia": "2026-10-01", "disp_pct": 100},
    {"usina": "Usina A", "parte": "A 1.2 (2)", "kwp": 300, "dia": "2026-10-01", "disp_pct": 0},
    {"usina": "Usina A", "parte": "A 1.1 (1)", "kwp": 100, "dia": "2026-10-02", "disp_pct": 50},
    {"usina": "Usina A", "parte": "A 1.2 (2)", "kwp": 300, "dia": "2026-10-02", "disp_pct": 100},
    {"usina": "Usina B", "parte": "B (3)", "kwp": "500.0", "dia": "2026-10-01", "disp_pct": "80.5"},
]


def test_o_dia_pondera_as_partes_pelo_kwp():
    assert disp_excecao.combinar(LINHAS, "Usina A", 2026, 10) == {D1: 25.0, D2: 87.5}
    # o banco devolve texto: número em texto também vale
    assert disp_excecao.combinar(LINHAS, "Usina B", 2026, 10) == {D1: 80.5}


def test_so_o_mes_e_a_usina_que_tem_linha():
    assert disp_excecao.combinar(LINHAS, "Usina A", 2026, 11) == {}
    assert disp_excecao.combinar(LINHAS, "Usina C", 2026, 10) == {}
    sujas = [{"usina": "Usina A", "kwp": 0, "dia": "2026-10-01", "disp_pct": 10},
             {"usina": "Usina A", "kwp": 10, "dia": "", "disp_pct": 10},
             {"usina": "Usina A", "kwp": 10, "dia": "2026-10-01", "disp_pct": None}]
    assert disp_excecao.combinar(sujas, "Usina A", 2026, 10) == {}


@pytest.fixture
def _livro(monkeypatch):
    lidas = []
    monkeypatch.setattr(disp_excecao, "_CACHE", {"linhas": None, "lido": 0.0, "falhou": 0.0})
    monkeypatch.setattr(disp_excecao.fonte_api, "_token", lambda: "tok")

    def ler(livro, aba, tok):
        lidas.append((livro, aba))
        return LINHAS
    monkeypatch.setattr(disp_excecao.livro_banco, "ler", ler)
    return lidas


def test_le_o_livro_uma_vez_por_ttl_e_o_atualizar_rele(_livro):
    assert disp_excecao.por_dia("Usina A", 2026, 10) == {D1: 25.0, D2: 87.5}
    assert disp_excecao.por_dia("Usina C", 2026, 10) is None
    assert _livro == [("thopen_disp_excecao", "disp_dia")]
    disp_excecao.invalidar()
    disp_excecao.por_dia("Usina A", 2026, 10)
    assert len(_livro) == 2


def test_banco_fora_vale_a_ultima_leitura_boa(monkeypatch, _livro):
    assert disp_excecao.por_dia("Usina A", 2026, 10)
    disp_excecao.invalidar()

    def cai(*a):
        raise OSError("sem rede")
    monkeypatch.setattr(disp_excecao.livro_banco, "ler", cai)
    assert disp_excecao.por_dia("Usina A", 2026, 10) == {D1: 25.0, D2: 87.5}


def test_sem_leitura_boa_nenhuma_segue_a_conta_de_sempre(monkeypatch, _livro):
    def cai(*a):
        raise OSError("sem rede")
    monkeypatch.setattr(disp_excecao.livro_banco, "ler", cai)
    assert disp_excecao.por_dia("Usina A", 2026, 10) is None


@pytest.fixture
def dash(monkeypatch):
    import dashboard_thopen as d
    monkeypatch.delenv("THOPEN_OPERACAO", raising=False)
    monkeypatch.setattr(d.disp_excecao, "por_dia",
                        lambda u, a, m: {D1: 25.0, D2: 87.5} if (u, a, m) == ("Usina A", 2026, 10) else None)
    return d


def test_a_excecao_vence_as_duas_contas(monkeypatch, dash):
    monkeypatch.setattr(dash, "_pelo_bd", lambda *a: pytest.fail("a exceção vem antes dos comentários"))
    monkeypatch.setattr(dash, "_op_dados", lambda: pytest.fail("a exceção vem antes das OS"))
    assert dash._disp_dias("Usina A", 2026, 10) == {D1: 25.0, D2: 87.5}
    assert dash._disp_gerencial("Usina A", 2026, 10) == pytest.approx(0.5625)


def test_sem_excecao_a_conta_de_sempre(monkeypatch, dash):
    monkeypatch.setattr(dash, "_pelo_bd", lambda *a: False)
    monkeypatch.setattr(dash, "_op_dados", lambda: {"x": 1})
    monkeypatch.setattr(dash.operacao_mes, "disp_por_dia", lambda dados, u, a, m, **k: {D1: 90.0})
    assert dash._disp_dias("Usina B", 2026, 10) == {D1: 90.0}
    assert dash._disp_dias("Usina A", 2026, 11) == {D1: 90.0}


def test_antes_de_outubro_nao_ha_excecao(dash):
    assert dash._disp_excecao("Usina A", 2026, 9) is None


def test_o_card_do_diario_leva_o_numero_da_excecao_e_o_comentario_de_antes(monkeypatch):
    chamou = {}

    def os_dia(dados, nome, ano, mes, trips, pot):
        chamou["os"] = True
        return {D1: ["OS 1 - inversor"]}
    monkeypatch.setattr(operacao_mes, "_da_usina", lambda *a: lambda x: False)
    monkeypatch.setattr(operacao_mes, "_e_da_usina", lambda *a: lambda x: False)
    monkeypatch.setattr(operacao_mes, "contar", lambda *a: {"por_dia": [], "strings": 0, "trackers": 0})
    monkeypatch.setattr(operacao_mes, "ids_da_usina", lambda *a: [])
    monkeypatch.setattr(operacao_mes, "disp_por_dia", lambda *a, **k: pytest.fail("a exceção troca a conta das OS"))
    monkeypatch.setattr(operacao_mes, "os_por_dia", os_dia)
    monkeypatch.setattr(operacao_mes, "_mes_info", lambda *a: (None, None))
    dados = {"trackers_episodios": [], "trackers_dia": [], "de_para": []}
    r = operacao_mes.resposta(dados, "Usina A", 2026, 10, dt.date(2026, 11, 6), disp={D1: 25.0, D2: 87.5})
    assert r["disponibilidade"] == 56.25 and chamou["os"]
    dia1 = next(p for p in r["por_dia"] if p["dia"] == "01/10")
    assert dia1["disp"] == 25.0 and dia1["os"] == ["OS 1 - inversor"]
    assert set(r) == set(operacao_mes.CHAVES)
