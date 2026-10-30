# -*- coding: utf-8 -*-
"""A disponibilidade pelos comentários do BD_Thopen (Levi, 30/10/2026: "A disponibilidade dessas UFVs devem ser
calculados de acordo com os comentários do BD_Thopen e os comentários também"), para as usinas que a Ronda COS não
cobre. O período escrito no comentário conta na janela de sol (06–18 h); falha de comunicação não conta; cabine conta
1 ÷ nº de cabines (sem cadastro, a usina inteira). Comentários fictícios, no molde que a equipe escreve."""
import os
import sys
from datetime import date, datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "thopen"))
import disp_comentarios as dc  # noqa: E402
import operacao_mes as om  # noqa: E402

D = date(2026, 10, 10)


@pytest.mark.parametrize("texto,ini,fim", [
    ("Desligamento usina - prot 59ABC - 30/09 às 06:03 ao 09/10 às 06:05", (9, 30, 6, 3), (10, 9, 6, 5)),
    ("Desligamento usina - temporal - 04/10 às 09:35h ao 09/10 às 07:14h", (10, 4, 9, 35), (10, 9, 7, 14)),
    ("Desligamento de usina, Trip ativo 47 - (Religada remotamente) - 21/10 as 17:01 ao 22/10 as 18:19",
     (10, 21, 17, 1), (10, 22, 18, 19)),
    ("Desligamento de cabine, relé sem alimentação - 08/10 08:38 às 09:55", (10, 8, 8, 38), (10, 8, 9, 55)),
    ("Falha de comunicação com a cabine - 04/10 ás 10:50 às 15:45", (10, 4, 10, 50), (10, 4, 15, 45)),
])
def test_le_o_periodo_no_molde_da_equipe(texto, ini, fim):
    (tipo, a, b, _l), = dc.periodos(texto, D)
    assert a == datetime(2026, *ini) and b == datetime(2026, *fim)


def test_tipo_da_linha():
    assert dc.tipo_da_linha("Falha de comunicção inversores - 08/10 ás 09:55 ao 09/10 às 06:00") == "comunicacao"
    assert dc.tipo_da_linha("Desligamento de cabine - x") == "cabine"
    assert dc.tipo_da_linha("Desligamento usina - x") == "usina"
    assert dc.tipo_da_linha("Limpeza de módulos - 08/10 08:00 às 10:00") is None


def _regs(*pares):
    return [{"data": d, "com": c} for d, c in pares]


def test_usina_inteira_conta_a_janela_de_sol_e_o_evento_repetido_conta_uma_vez():
    c = "Desligamento usina - prot 59ABC - 30/09 às 06:03 ao 02/10 às 09:00"
    disp, com = dc.por_dia(_regs((date(2026, 9, 30), c), (date(2026, 10, 1), c), (date(2026, 10, 2), c)),
                           2026, 10, date(2026, 10, 3))
    assert disp == {date(2026, 10, 1): 0.0, date(2026, 10, 2): 75.0, date(2026, 10, 3): 100.0}
    assert com[date(2026, 10, 2)] == [c]


def test_comunicacao_nao_conta_mas_o_comentario_vai_para_a_tela():
    c = "Falha de comunicação  - 04/10 ás 10:00 às 16:00"
    disp, com = dc.por_dia(_regs((date(2026, 10, 4), c)), 2026, 10, date(2026, 10, 4))
    assert set(disp.values()) == {100.0} and len(disp) == 4 and com[date(2026, 10, 4)] == [c]


def test_cabine_conta_a_fracao_ou_a_usina_inteira_sem_cadastro():
    c = "Desligamento de cabine - relé - 08/10 08:00 às 11:00"
    assert dc.por_dia(_regs((date(2026, 10, 8), c)), 2026, 10, date(2026, 10, 8), n_cabines=2)[0][date(2026, 10, 8)] \
        == pytest.approx(100 * (1 - 1.5 / 12), abs=0.001)
    assert dc.por_dia(_regs((date(2026, 10, 8), c)), 2026, 10, date(2026, 10, 8))[0][date(2026, 10, 8)] == 75.0


def test_dia_do_evento_sem_comentario_escrito_leva_a_linha_do_evento():
    c = "Desligamento de usina - trip - 21/10 as 17:00 ao 22/10 as 18:00"
    disp, com = dc.por_dia(_regs((date(2026, 10, 21), c)), 2026, 10, date(2026, 10, 22))
    assert disp[date(2026, 10, 22)] == 0.0 and com[date(2026, 10, 22)] == [c]


def test_a_resposta_do_card_usa_os_comentarios_do_bd():
    from test_thopen_operacao_mes import dados           # noqa: E402 — os dados de teste do card
    disp = {date(2026, 10, 1): 0.0, date(2026, 10, 2): 100.0}
    com = {date(2026, 10, 1): ["Desligamento usina - x"], date(2026, 10, 2): ["Falha de comunicação - y"]}
    r = om.resposta(dados(), "Altair", 2026, 10, date(2026, 10, 15), bd=(disp, com))
    pd = {p["dia"]: p for p in r["por_dia"]}
    assert r["fonte_disp"] == "bd_comentarios" and r["disponibilidade"] == 50.0
    assert pd["01/10"]["os"] == ["Desligamento usina - x"] and pd["02/10"]["os"] == ["Falha de comunicação - y"]
    assert tuple(r) == om.CHAVES


def test_a_lista_das_usinas_pelo_bd():
    assert {"Nova Iguaçu", "AP. do Taboado", "Cambé"} <= dc.USINAS
    # Aruanã, Sapopema e Segredo passaram para o COS (30/10/2026)
    assert not {"Aruanã", "Sapopema", "Segredo"} & dc.USINAS


def test_inversor_conta_os_citados_sobre_os_da_usina_e_a_cabine_vence():
    # 30/10/2026: o de-para da aba do BD (cabines e inversores); "Desligamento de inversor" não é a usina inteira
    assert dc.tipo_da_linha("Desligamento de inversor 1.3 - 08/10 08:00 às 10:00") == "inversor"
    assert dc.tipo_da_linha("Desligamento de cabine 2, inversores sem tensão - 08/10 08:00 às 10:00") == "cabine"
    assert dc.inversores_citados("Desligamento dos inversores 1.3 e 1.4 - 08/10 08:00 às 10:00") == 2
    assert dc.inversores_citados("Desligamento de inversor - 08/10 08:00 às 10:00") == 1
    assert dc.fracao("inversor", "inversores 1.3 e 1.4", n_cabines=2, n_inversores=20) == pytest.approx(0.1)
    assert dc.fracao("inversor", "inversor", n_cabines=2) == 0.5 and dc.fracao("inversor", "inversor") == 1.0
    assert dc.fracao("cabine", "cabine", n_cabines=5, n_inversores=40) == 0.2


def test_desligamento_de_inversor_no_dia():
    c = "Desligamento dos inversores 1.3 e 1.4 - 08/10 06:00 às 18:00"
    disp, _ = dc.por_dia(_regs((date(2026, 10, 8), c)), 2026, 10, date(2026, 10, 8), n_cabines=1, n_inversores=10)
    assert disp[date(2026, 10, 8)] == pytest.approx(80.0)
