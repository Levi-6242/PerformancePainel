# -*- coding: utf-8 -*-
"""O dashboard não para mais (25/11/2026: no servidor, com 1 processo e 8 threads, o /performance ficava minutos sem
responder, até o login). Os livros da exceção e do mês fechado são relidos por trás; a disponibilidade da plataforma, a
exceção e o fechamento são indexados uma vez por leitura (o mesmo resultado de antes); o BD novo é pré-aquecido numa
thread. Dados fictícios, nada de rede."""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "thopen"))
import dashboard_thopen as d  # noqa: E402
import disp_excecao  # noqa: E402
import disp_fechamento  # noqa: E402
import operacao_mes  # noqa: E402


class _ThreadFalsa:
    criadas = []

    def __init__(self, target=None, name=None, daemon=None):
        self.target, self.name = target, name
        _ThreadFalsa.criadas.append(self)

    def start(self):
        pass


def test_o_livro_vencido_volta_na_hora_e_e_relido_por_tras(monkeypatch):
    lidas = []
    monkeypatch.setattr(disp_excecao, "_CACHE", {"linhas": [{"usina": "U", "kwp": 1, "dia": "2026-10-01",
                                                             "disp_pct": 50}], "lido": 0.0, "falhou": 0.0})
    monkeypatch.setattr(disp_excecao.livro_banco, "ler", lambda *a: lidas.append(a) or [])
    monkeypatch.setattr(disp_excecao.fonte_api, "_token", lambda: "tok")
    _ThreadFalsa.criadas = []
    monkeypatch.setattr(disp_excecao.threading, "Thread", _ThreadFalsa)
    # vencido: o pedido leva a leitura de antes, sem esperar o banco; a releitura vai para a thread (uma só)
    assert disp_excecao.por_dia("U", 2026, 10) == {dt.date(2026, 10, 1): 50.0}
    assert disp_excecao.por_dia("U", 2026, 10) == {dt.date(2026, 10, 1): 50.0}
    assert lidas == [] and len(_ThreadFalsa.criadas) == 1
    # a thread relê e troca
    monkeypatch.setattr(disp_excecao.livro_banco, "ler", lambda *a: [{"usina": "U", "kwp": 1, "dia": "2026-10-01",
                                                                      "disp_pct": 80}])
    _ThreadFalsa.criadas[0].target()
    assert disp_excecao.por_dia("U", 2026, 10) == {dt.date(2026, 10, 1): 80.0}


def test_sem_nada_em_memoria_le_na_hora(monkeypatch):
    monkeypatch.setenv("THOPEN_FECHAMENTO", "1")
    monkeypatch.setattr(disp_fechamento, "_CACHE", {"linhas": None, "lido": 0.0, "falhou": 0.0})
    monkeypatch.setattr(disp_fechamento.fonte_api, "_token", lambda: "tok")
    monkeypatch.setattr(disp_fechamento.livro_banco, "ler", lambda *a: [
        {"mes": "2026-10", "usina": "U", "dia": "2026-10-02", "disp_pct": 90, "fechado_em": "2026-11-13T11:40:00"}])
    assert disp_fechamento.por_dia("U", 2026, 10) == {dt.date(2026, 10, 2): 90.0}
    assert disp_fechamento.por_dia("V", 2026, 10) == {} and disp_fechamento.por_dia("U", 2026, 11) is None


def test_o_indice_da_plataforma_e_refeito_na_leitura_nova():
    def dados(v):
        return {"de_para": [], "disponibilidade_dia": [{"dia": "2026-10-01", "usina": "Usina X", "usina_ids": [],
                                                        "pot_kwp": 100, "h_perdidas": v, "disp": None}]}
    a, b = dados(1), dados(5)
    assert operacao_mes.disp_por_dia(a, "Usina X", 2026, 10) == {dt.date(2026, 10, 1): 90.0}
    assert operacao_mes.disp_por_dia(b, "Usina X", 2026, 10) == {dt.date(2026, 10, 1): 50.0}
    assert operacao_mes.disp_por_dia(b, "Usina X", 2026, 11) == {}


def test_o_bd_novo_e_preaquecido_por_tras_so_quando_ligado(monkeypatch):
    _ThreadFalsa.criadas = []
    monkeypatch.setattr(d.threading, "Thread", _ThreadFalsa)
    monkeypatch.setenv("THOPEN_PREAQUECE", "0")
    d._preaquece()
    assert _ThreadFalsa.criadas == []
    monkeypatch.setenv("THOPEN_PREAQUECE", "1")
    lidas = []
    monkeypatch.setattr(d, "_usinas_do_5080", lambda: ["A", "B"])
    monkeypatch.setattr(d, "_daily_records", lambda u: lidas.append(u))
    d._preaquece()
    assert [t.name for t in _ThreadFalsa.criadas] == ["thopen_preaquece"]
    _ThreadFalsa.criadas[0].target()
    assert lidas == ["A", "B"]
