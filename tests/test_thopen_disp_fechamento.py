# -*- coding: utf-8 -*-
"""O fechamento do mês (13/11/2026; o cliente: "estamos no dia 13/11 e os dados de Outubro estão sendo alterados ainda?
quando podemos confiar no valor correto da disponibilidade?"): o mês com linha no livro thopen_disp_fechamento não muda
mais, cada mês fecha sozinho no dia 10 do seguinte e, até lá, a tela diz "em apuração". Usinas fictícias, nada de rede."""
import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "thopen"))
import dashboard_thopen as d  # noqa: E402
import disp_fechamento as F  # noqa: E402

D1, D2 = dt.date(2026, 10, 1), dt.date(2026, 10, 2)
OUTUBRO = [{"mes": "2026-10", "usina": "Usina A", "dia": "2026-10-01", "disp_pct": "91.72",
            "fechado_em": "2026-11-13T11:40:00-03:00", "origem": "teste"},
           {"mes": "2026-10", "usina": "Usina A", "dia": "2026-10-02", "disp_pct": 100,
            "fechado_em": "2026-11-13T11:40:00-03:00", "origem": "teste"}]


@pytest.fixture
def livro(monkeypatch):
    """O livro falso: `linhas` é o que o banco tem; `acrescentar` e `regravar` mexem nela."""
    estado = {"linhas": list(OUTUBRO), "gravou": []}
    monkeypatch.setenv("THOPEN_FECHAMENTO", "1")
    monkeypatch.setattr(F, "_CACHE", {"linhas": None, "lido": 0.0, "falhou": 0.0})
    monkeypatch.setattr(F.fonte_api, "_token", lambda: "tok")
    monkeypatch.setattr(F.livro_banco, "ler", lambda livro, aba, tok: list(estado["linhas"]))

    def acrescentar(livro, nome, aba, cab, novas, tok):
        estado["gravou"].append((livro, aba, len(novas)))
        estado["linhas"] += list(novas)
        return len(estado["linhas"])

    def regravar(livro, nome, aba, cab, linhas, antes, tok):
        assert antes == len(estado["linhas"])
        estado["linhas"] = list(linhas)
        return len(linhas)
    monkeypatch.setattr(F.livro_banco, "acrescentar", acrescentar)
    monkeypatch.setattr(F.livro_banco, "regravar", regravar)
    return estado


def test_o_mes_fecha_no_dia_10_do_seguinte():
    assert F.fecha_em(2026, 10) == dt.date(2026, 11, 10)
    assert F.fecha_em(2026, 12) == dt.date(2027, 1, 10)


def test_o_mes_fechado_le_o_livro_e_o_aberto_segue_a_conta(livro):
    assert F.por_dia("Usina A", 2026, 10) == {D1: 91.72, D2: 100.0}
    # a usina sem linha no mês fechado fica sem número: não volta para a conta
    assert F.por_dia("Usina B", 2026, 10) == {}
    assert F.por_dia("Usina A", 2026, 11) is None


def test_desligado_nao_le_nada(livro, monkeypatch):
    monkeypatch.setenv("THOPEN_FECHAMENTO", "0")
    assert F.por_dia("Usina A", 2026, 10) is None


def test_o_que_a_tela_diz(livro):
    assert F.situacao(2026, 10) == {"fechado": True, "fechado_em": "13/11/2026"}
    assert F.situacao(2026, 11) == {"fechado": False, "fecha_em": "10/12/2026"}
    assert F.situacao(2026, 9) is None                 # antes de outubro, a base da Grid: sem selo


def test_quais_meses_fecham_sozinhos(livro):
    assert F.a_fechar(dt.date(2026, 12, 9)) == []      # outubro já fechado, novembro só no dia 10/12
    assert F.a_fechar(dt.date(2026, 12, 10)) == [(2026, 11)]
    assert F.a_fechar(dt.date(2026, 11, 10), linhas=[]) == [(2026, 10)]
    assert F.a_fechar(dt.date(2026, 11, 9), linhas=[]) == []


def test_as_linhas_do_mes_sao_o_que_o_dashboard_mostra():
    contas = {"Usina A": {D1: 91.723456, D2: None, dt.date(2026, 11, 1): 50.0}, "Usina B": None}
    agora = dt.datetime(2026, 11, 13, 11, 40, tzinfo=dt.timezone(dt.timedelta(hours=-3)))
    linhas = F.linhas_do_mes(2026, 10, ["Usina B", "Usina A"], lambda u, a, m: contas.get(u), agora, "teste")
    assert linhas == [{"mes": "2026-10", "usina": "Usina A", "dia": "2026-10-01", "disp_pct": 91.7235,
                       "fechado_em": "2026-11-13T11:40:00-03:00", "origem": "teste"}]


def test_fechar_grava_uma_vez_e_reabrir_tira_o_mes(livro):
    nov = [dict(OUTUBRO[0], mes="2026-11", dia="2026-11-01")]
    assert F.fechar(2026, 11, nov, "tok") == 3 and livro["gravou"] == [("thopen_disp_fechamento", "disp_dia", 1)]
    with pytest.raises(F.livro_banco.GravacaoErro, match="já está fechado"):
        F.fechar(2026, 11, nov, "tok")
    with pytest.raises(F.livro_banco.GravacaoErro, match="nenhum número"):
        F.fechar(2026, 12, [], "tok")
    with pytest.raises(F.livro_banco.GravacaoErro, match="outro mês"):
        F.fechar(2026, 12, nov, "tok")
    assert F.reabrir(2026, 10, "tok") == 2 and [l["mes"] for l in livro["linhas"]] == ["2026-11"]
    assert F.por_dia("Usina A", 2026, 10) is None      # reaberto: volta para a conta
    assert F.reabrir(2026, 10, "tok") == 0


# ── no dashboard ───────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def dash(livro, monkeypatch):
    monkeypatch.delenv("THOPEN_OPERACAO", raising=False)
    monkeypatch.setattr(d, "_disp_excecao", lambda *a: {D1: 50.0})
    monkeypatch.setattr(d, "_pelo_bd", lambda *a: False)
    monkeypatch.setattr(d, "_op_dados", lambda: {"x": 1})
    monkeypatch.setattr(d.operacao_mes, "disp_por_dia", lambda *a, **k: {D1: 10.0})
    return d


def test_o_mes_fechado_vence_a_excecao_e_a_conta(dash):
    assert dash._disp_dias("Usina A", 2026, 10) == {D1: 91.72, D2: 100.0}
    assert dash._disp_dias("Usina B", 2026, 10) is None
    # o mês aberto segue a ordem de sempre (a exceção primeiro)
    assert dash._disp_dias("Usina A", 2026, 11) == {D1: 50.0}


def test_o_card_leva_o_numero_fechado_e_o_selo(dash, monkeypatch):
    chamou = {}

    def resposta(dados, usina, ano, mes, hoje, trips=None, bd=None, disp=None, **k):
        chamou.update(disp=disp)
        return {"disponivel": False}
    monkeypatch.setattr(dash.operacao_mes, "resposta", resposta)
    monkeypatch.setattr(dash, "_trips_da_tela", lambda *a: ({}, False))
    monkeypatch.setattr(dash, "_canais_da_contestacao", lambda: None)
    monkeypatch.setattr(dash, "_pode", lambda u: True)
    monkeypatch.setattr(dash, "_FECHAMENTO", {"iniciado": True})       # o laço não sobe no teste
    j = dash.app.test_client().get("/api/t/operacao?usina=Usina A&ano=2026&mes=10").get_json()
    assert chamou["disp"] == {D1: 91.72, D2: 100.0}
    assert j["apuracao"] == {"fechado": True, "fechado_em": "13/11/2026"}


def test_fechar_o_mes_recusa_sem_a_plataforma_e_grava_o_que_o_dashboard_mostra(dash, livro, monkeypatch):
    monkeypatch.setattr(dash, "_wb", lambda: None)
    monkeypatch.setattr(dash, "CARTEIRAS", {"Polaris": ["Usina A", "Usina C"], "Thopen": ["Usina C"]})
    monkeypatch.setattr(dash, "_op_dados", lambda: None)
    with pytest.raises(F.livro_banco.GravacaoErro, match="não carregou"):
        dash.fechar_mes(2026, 11, "teste")
    monkeypatch.setattr(dash, "_op_dados", lambda: {"x": 1})
    monkeypatch.setattr(dash, "_disp_excecao", lambda u, a, m: {dt.date(a, m, 1): 50.0} if u == "Usina A" else None)
    monkeypatch.setattr(dash.operacao_mes, "disp_por_dia", lambda dados, u, a, m, **k: {dt.date(a, m, 2): 10.0})
    n, linhas = dash.fechar_mes(2026, 11, "teste", agora=dt.datetime(2026, 12, 10, 1, 0).astimezone())
    # Usina A: a exceção; Usina C: a conta das ocorrências; cada usina uma vez, mesmo em duas carteiras
    assert [(l["usina"], l["dia"], l["disp_pct"]) for l in linhas] == [("Usina A", "2026-11-01", 50.0),
                                                                        ("Usina C", "2026-11-02", 10.0)]
    assert n == 4 and F.situacao(2026, 11)["fechado"] is True


def test_o_laco_so_liga_com_o_fechamento_ligado(monkeypatch):
    subiu = []
    monkeypatch.setattr(d, "_FECHAMENTO", {"iniciado": False})
    monkeypatch.setattr(d.threading, "Thread", lambda **k: type("T", (), {"start": lambda s: subiu.append(k["name"])})())
    monkeypatch.setenv("THOPEN_FECHAMENTO", "0")
    d._fechamento_automatico()
    assert subiu == []
    monkeypatch.setenv("THOPEN_FECHAMENTO", "1")
    d._fechamento_automatico()
    d._fechamento_automatico()
    assert subiu == ["thopen_fechamento"]
