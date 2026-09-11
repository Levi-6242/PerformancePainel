# -*- coding: utf-8 -*-
"""Histórico/energia por inversor: usina do cliente THOPEN lê do BD_Thopen, seja qual for a fonte (Levi, 11/09/2026).

Antes a base era escolhida pela FONTE (só `pg` ia ao BD_Thopen). Colorado 2, Barretos, Ceilândia, Ouro Branco… são
API PV e caíam no BD_Performance, que não tem aba por inversor para elas → o Diagnóstico v2 dizia "a usina não tem
aba com colunas de inversor no BD_Performance — a coleta precisa criá-las". O BD_Thopen tem a aba diária dessas
usinas (colunas 'Inversor 1.1'…). A régua agora é por CLIENTE: Thopen → BD_Thopen primeiro (aba da usina; se não
houver, a da usina física — 'Barretos 2' cai em 'Barretos'), BD_Performance como reserva; demais → BD_Performance."""
import pytest

import app


@pytest.fixture
def cadastro(monkeypatch):
    monkeypatch.setattr(app, "INFO_GERAL", {app._nrm("Colorado 2"): {"cliente": "Thopen"},
                                            app._nrm("Barretos 2"): {"cliente": "Thopen"},
                                            app._nrm("Xavantina 1"): {"cliente": "RenoGrid"}})
    monkeypatch.setattr(app, "_carteira_de", lambda u: None)          # o mapa do 5080 fica fora do teste


def _leitores(monkeypatch, bdt, bdp):
    chamadas = []

    def _t(usina, ano, mes):
        chamadas.append(("bd_thopen", usina))
        return bdt.get(usina, {})

    def _p(usina, ano, mes):
        chamadas.append(("bd_performance", usina))
        return bdp.get(usina, {})
    monkeypatch.setattr(app, "_bdthopen_inv_dias", _t)
    monkeypatch.setattr(app, "_bdperf_inv_dias", _p)
    return chamadas


DIA = {"2026-09-09": {"ipoa": 5.1, "inv": {"Inversor 1.1": 900.0, "Inversor 1.2": 880.0}}}


def test_usina_thopen_da_api_pv_usa_o_bd_thopen(cadastro):
    assert app._inv_usina_thopen("pv", "Colorado 2") is True         # cliente Thopen na Info Geral, fonte API PV
    assert app._inv_usina_thopen("pg", "Ibaté 1") is True            # fonte Thopen (banco) sempre foi
    assert app._inv_usina_thopen("thopen", "Ibaté 1") is True        # apelido da rota
    assert app._inv_usina_thopen("solaredge", "Xavantina 1") is False  # RenoGrid


def test_carteira_do_5080_tambem_vale_como_thopen(cadastro, monkeypatch):
    """Usina que a Info Geral não conhece mas o BD_Thopen tem em carteira (Polaris/Copel/Matrix são carteiras Thopen)."""
    monkeypatch.setattr(app, "_carteira_de", lambda u: "Polaris" if u == "Guaratingueta V" else None)
    assert app._inv_usina_thopen("pv", "Guaratingueta V") is True


def test_thopen_le_bd_thopen_primeiro_e_bd_performance_como_reserva(cadastro, monkeypatch):
    ch = _leitores(monkeypatch, {"Colorado 2": DIA}, {})
    bases = app._inv_dias_por_base("pv", "Colorado 2", 2026, 9)
    assert [b[0] for b in bases] == ["bd_thopen", "bd_performance"]
    assert bases[0][1] == DIA
    assert ("bd_thopen", "Colorado 2") in ch


def test_sub_usina_cai_na_aba_da_usina_fisica(cadastro, monkeypatch):
    """'Barretos 2' não tem aba própria; a aba 'Barretos' (usina física) tem os inversores 1.x e 2.x."""
    ch = _leitores(monkeypatch, {"Barretos": DIA}, {})
    bases = app._inv_dias_por_base("pv", "Barretos 2", 2026, 9)
    assert bases[0] == ("bd_thopen", DIA)
    assert [c for c in ch if c[0] == "bd_thopen"] == [("bd_thopen", "Barretos 2"), ("bd_thopen", "Barretos")]


def test_usina_de_outro_cliente_so_le_bd_performance(cadastro, monkeypatch):
    ch = _leitores(monkeypatch, {"Xavantina 1": DIA}, {"Xavantina 1": DIA})
    bases = app._inv_dias_por_base("solaredge", "Xavantina 1", 2026, 9)
    assert [b[0] for b in bases] == ["bd_performance"]
    assert all(c[0] == "bd_performance" for c in ch)


def test_motivo_do_vazio_aponta_o_bd_thopen_para_usina_thopen(cadastro):
    assert "BD_Thopen" in app._inv_sem_base("pv", "Colorado 2")
    assert "BD_Performance" in app._inv_sem_base("solaredge", "Xavantina 1")


def test_aba_fisica_filtra_o_bloco_da_sub_usina(cadastro, monkeypatch):
    """A aba 'Barretos' traz 1.x e 2.x juntos; o Diagnóstico da Barretos 2 só quer os 2.x. Sem inversor do bloco, fica tudo."""
    aba = {"2026-09-09": {"ipoa": 5.1, "inv": {"Inversor 1.1": 900.0, "Inversor 2.1": 870.0, "Inversor 2.2": 860.0}}}
    _leitores(monkeypatch, {"Barretos": aba}, {})
    bases = app._inv_dias_por_base("pv", "Barretos 2", 2026, 9)
    assert bases[0][1]["2026-09-09"]["inv"] == {"Inversor 2.1": 870.0, "Inversor 2.2": 860.0}
    assert bases[0][1]["2026-09-09"]["ipoa"] == 5.1
