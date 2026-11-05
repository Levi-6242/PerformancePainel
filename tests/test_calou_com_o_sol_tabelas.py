# -*- coding: utf-8 -*-
"""A régua da usina que calou com o sol (05/11/2026, tests/test_calou_com_o_sol.py) também nas tabelas de strings de cada
fonte (Monitoramento), a pedido do Levi no mesmo dia ("quando ficar pronto sobe"): a linha diz "Sem sol" e o card "Usinas
sem comunicação" desconta quem calou com o sol, como a Entrada. A marca `calou_com_o_sol` é posta na HORA DE SERVIR, junto
da `sol_baixo` (`_servir_com_sol`), e a tela só a lê."""
import re
from datetime import datetime

import app
from test_strings_sem_sol_a_noite import MON, _linha, _payload, _status

NOITE = datetime(2026, 11, 5, 20, 15)


def test_a_marca_vai_na_linha_e_o_card_desconta(monkeypatch):
    monkeypatch.setattr(app, "_estado_da_usina", lambda nome: "Piaui")
    calou = _linha("Junco 2.1 (134)", falha_comunicacao=True, ultima_leitura="2026-11-05 17:40:00")
    de_dia = _linha("Irece 2", falha_comunicacao=True, ultima_leitura="2026-11-05 11:04:29")
    nada = _linha("Aquiraz 1", sem_dados=True, ultima_leitura=None)
    p = app._servir_com_sol(_payload(calou, de_dia, nada, alertas_comm=3), app._sem_geracao_padrao, agora=NOITE)
    assert [r["calou_com_o_sol"] for r in p["rows"]] == [True, False, False]
    assert p["summary"]["alertas_comm"] == 2                        # a que calou de dia e a sem leitura seguem
    assert "calou_com_o_sol" not in calou                           # o payload do cache não muda


def test_de_dia_nada_muda(monkeypatch):
    monkeypatch.setattr(app, "_estado_da_usina", lambda nome: "Piaui")
    r = _linha("Junco 2.1 (134)", falha_comunicacao=True, ultima_leitura="2026-11-05 13:00:00", strings_ativas=500,
               diferenca=-99)
    p = app._servir_com_sol(_payload(r, alertas_comm=1), app._sem_geracao_padrao, agora=datetime(2026, 11, 5, 14, 0))
    assert p["rows"][0]["calou_com_o_sol"] is False and p["summary"]["alertas_comm"] == 1


def test_a_linha_que_calou_com_o_sol_diz_sem_sol():
    assert _status(_linha("Junco", sol_baixo=True, falha_comunicacao=True, calou_com_o_sol=True)) == "Sem sol"
    assert _status(_linha("Junco", sol_baixo=True, calou_com_o_sol=True), velho=True) == "Sem sol"
    # sem a marca, ou calada de dia, segue sem comunicação; desligada com motivo segue desligada
    assert _status(_linha("Irece 2", sol_baixo=True, falha_comunicacao=True, calou_com_o_sol=False)) == \
        "Usina sem comunicação"
    assert _status(_linha("X", sol_baixo=True, falha_comunicacao=True)) == "Usina sem comunicação"
    assert _status(_linha("X", sol_baixo=True, falha_comunicacao=True, calou_com_o_sol=True,
                          desligada={"por": "os", "folio": 1})) == "Usina desligada"


def test_os_outros_pontos_da_tabela_tambem_leem_a_marca():
    """O status não basta: a coluna de ativas e a nota do padrão (o `semCom` da linha), a "calada" da linha e o aviso dos
    tickets no detalhe do inversor (`semComU`) também julgam a comunicação."""
    m = MON[MON.index("usinas=pv.rows.filter("):]
    m = m[:m.index("}).sort(")]
    assert re.search(r"semCom=\(\(_velho\|\|!!r\.falha_comunicacao\)&&!r\.calou_com_o_sol\)\|\|!!r\.desligada", m)
    assert "calada:((_velho||!!r.falha_comunicacao)&&!r.calou_com_o_sol)||!!r.sem_dados" in m
    assert "semComU:!!(_urow&&_urow.falha_comunicacao&&!_urow.calou_com_o_sol)" in MON
