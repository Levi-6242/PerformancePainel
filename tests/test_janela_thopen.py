# -*- coding: utf-8 -*-
"""O período solar da Thopen: 07:30 às 17:30, 10 h por dia (Levi, 05/11/2026: "para o cliente Thopen, a disponibilidade
será calculada com o período solar de 7 as 17 para melhor confiabilidade"; logo depois: "na verdade será das 07:30 as
17:30"). Os outros clientes seguem nas 06–18 h. A régua, a tela da plataforma, o 5080 e os comentários do BD_Thopen usam
a mesma janela. Dados fictícios."""
import os
import sys
from datetime import date, datetime

import pytest

AQUI = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(AQUI, "..", "thopen"))
import disponibilidade as dm  # noqa: E402
import disp_comentarios as dc  # noqa: E402
import operacao_mes as om  # noqa: E402

PER_INI, PER_FIM, AGORA = datetime(2026, 10, 1), datetime(2026, 10, 3), datetime(2026, 10, 3, 12)
EQUIP = [{"cliente": c, "usina": u, "usina_fracttal": f"{c} - {u} - SP", "equipamento": "UFV", "pot_kwp": 1000.0,
          "n_inv": 2, "full_om": "Sim"} for c, u in (("Thopen", "Alfa"), ("OutraCo", "Gama"))]
POR_ID = {11: ["Alfa"]}


def _norm(**kw):
    n = {"registro": "r1", "os": "17001", "os_relacionadas": "", "cliente": "THOPEN", "usina_codigo": "THPN-ALF100",
         "usina_id": "11", "usina_ligada_por": "codigo", "equipamentos_codigos": "", "equipamentos_qtd": 0,
         "tipo_falha": "DESLIGAMENTO_USINA", "severidade": "CRITICO", "estado": "NORMALIZADO", "normalizada": "1",
         "hora_real": "1", "fim_corrigido": "0", "declarada_por": "pessoa", "inicio": "2026-10-01T06:00:00-03:00",
         "normalizado_em": "2026-10-01T09:00:00-03:00", "data_id_inicio": 20261001, "data_id_volta": 20261001,
         "fora_min": 180, "geracao_parou": "", "protecoes": "", "fora_do_escopo_oem": "0", "mudou_em": ""}
    n.update(kw)
    return n


def test_a_janela_e_do_cliente():
    assert dm.janela("Thopen") == (7.5, 17.5) and dm.horas_dia("THOPEN Energia") == 10.0
    assert dm.janela("OutraCo") == (6, 18) and dm.horas_dia("") == 12.0
    assert dm.horas_solares_por_dia(datetime(2026, 10, 1, 6), datetime(2026, 10, 1, 9), datetime(2026, 10, 2),
                                    (7.5, 17.5)) == {date(2026, 10, 1): 1.5}


def test_a_thopen_conta_das_07_30_as_17_30():
    # a usina da Thopen caiu às 06:00 e voltou às 09:00: conta 07:30 a 09:00, 1,5 h de 10
    r = dm.calcular({}, EQUIP, PER_INI, PER_FIM, agora=AGORA, normalizacoes=[_norm()], usinas_por_id=POR_ID)
    alfa = next(u for u in r["usinas"] if u["usina"] == "Alfa")
    assert alfa["janela_h"] == [7.5, 17.5] and alfa["h_perdidas"] == pytest.approx(1.5)
    assert alfa["disp"] == pytest.approx(100 * (1 - 1.5 / 20), abs=0.01)                     # dois dias de 10 h
    dia = r["diario"]["Alfa"]["2026-10-01"]
    assert dia["disp"] == 85.0 and dia["os"][0]["trechos"] == "07:30-09:00"
    gama = next(u for u in r["usinas"] if u["usina"] == "Gama")
    assert gama["janela_h"] == [6, 18]
    thopen = next(c for c in r["clientes"] if c["cliente"] == "Thopen")
    assert thopen["disp"] == pytest.approx(100 * (1 - 1.5 / 20), abs=0.01)


def test_o_5080_e_os_comentarios_usam_as_mesmas_10_h():
    a, b = dm.JANELA_POR_CLIENTE["THOPEN"]
    assert om.HORAS_SOL == b - a == 10.0 and (dc.SOL_INI_H, dc.SOL_FIM_H) == (a, b)
    c = "Desligamento usina - 08/10 às 06:00 às 08:30"
    assert dc.por_dia([{"data": date(2026, 10, 8), "com": c}], 2026, 10, date(2026, 10, 8))[0][date(2026, 10, 8)] == 90.0


def test_a_tela_da_plataforma_pondera_pelas_horas_de_cada_usina():
    h = open(os.path.join(AQUI, "..", "plataforma", "templates", "disponibilidade.html"), encoding="utf-8").read()
    i = h.index("function dispPonderada(")
    assert "horasSol(u)" in h[i:i + 300] and "12 * dias" not in h[i:i + 300]
    j = h.index("function hSolarDia(")
    assert "jan || [6, 18]" in h[j:j + 400] and "Math.round(hi * 60)" in h[j:j + 600]
    assert "de ${jan[1] - jan[0]}h solares" in h and "Thopen 07h30–17h30" in h
