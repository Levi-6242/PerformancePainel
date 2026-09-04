# gemeo/tests/test_modelar_eventos.py
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from golden import G, esperado_de_placa, sem_gate, trk_inv_mro100, veredito  # noqa: E402
from sintetico import grade_sintetica  # noqa: E402
from gemeo.modelar import decomposicao as dc  # noqa: E402
from gemeo.modelar import esperado, eventos, gate  # noqa: E402

P = dc.ParamsDecomp(f_direta_fixa=0.6)
MAPA = {2001: 1001, 2002: 1002}
UNIVERSO = {1001: [3101, 3102, 3103, 3104], 1002: []}   # strings instaladas, como o job traz dos 30 dias
H = 0.25


def _tudo(g):
    params = {i: esperado.ParamsModelo(kwp=277.68, pac0_kw=200.0) for i in g.inv_p.columns}
    r = sem_gate(g)
    esp = esperado.esperado_por_inversor(g, r, params)
    return r, esp, dc.decompor(g, esp, MAPA, P, instaladas=UNIVERSO)


def _do_tipo(evs, tipo):
    return [e for e in evs if e.tipo == tipo]


def test_severidade_pelo_kwh_sobre_o_esperado():
    assert eventos.severidade(5.0, 1000.0) == "leve" and eventos.severidade(30.0, 1000.0) == "media"
    assert eventos.severidade(60.0, 1000.0) == "grave" and eventos.severidade(0.0, 0.0) == "leve"


def test_sensor_e_cobertura_viram_evento_grave_de_dia_inteiro():
    g = grade_sintetica(); r, esp, d = _tudo(g)
    dia = g.indice[0].tz_convert("America/Belem").date()
    r.motivo_dia = {dia: "poa_ghi"}; r.razao_dia = {dia: 0.12}
    evs = eventos.detectar(g, r, esp, d)
    ev = _do_tipo(evs, "sensor_em_falha")
    assert len(ev) == 1 and ev[0].severidade == "grave" and ev[0].equipamento_id is None and ev[0].ini == g.indice[0]
    assert ev[0].fim == g.indice[-1] + pd.Timedelta(minutes=15) and ev[0].detalhe["razao_poa_ghi"] == 0.12
    r.motivo_dia = {dia: "cobertura"}
    assert len(_do_tipo(eventos.detectar(g, r, esp, d), "sem_cobertura")) == 1


def test_inversor_parado_o_dia_inteiro():
    g = grade_sintetica(); g.inv_p[1001] = 0.0
    r, esp, d = _tudo(g)
    ev = _do_tipo(eventos.detectar(g, r, esp, d), "inversor_parado")
    assert [e.equipamento_id for e in ev] == [1001]
    assert ev[0].kwh == pytest.approx(float(d.parado[1001].sum() * H), rel=1e-6) and ev[0].severidade == "grave"
    assert ev[0].ini == g.indice[0] and ev[0].fim == g.indice[-1] + pd.Timedelta(minutes=15)


def test_inversor_parado_de_meia_hora_nao_e_evento_o_de_uma_hora_e():
    """A regra virou CORRIDA de slots (04/09/2026): a CPP100 desligou 8 de 12 inversores por 4 h em 03/09 e a regra
    antiga, de >= 90 % dos slots com sol do dia, nao emitia assinatura nenhuma. Abaixo de 1 h continua sendo ruido."""
    g = grade_sintetica(); g.inv_p.iloc[:2, 0] = 0.0                  # 30 min parado
    r, esp, d = _tudo(g)
    assert not _do_tipo(eventos.detectar(g, r, esp, d), "inversor_parado")
    g = grade_sintetica(); g.inv_p.iloc[2:6, 0] = 0.0                 # 1 h parado no meio do dia
    r, esp, d = _tudo(g)
    ev = _do_tipo(eventos.detectar(g, r, esp, d), "inversor_parado")
    assert len(ev) == 1 and ev[0].equipamento_id == 1001
    assert ev[0].ini == g.indice[2] and ev[0].fim == g.indice[5] + pd.Timedelta(minutes=15)   # a janela REAL da parada
    assert ev[0].detalhe["slots"] == 4 and ev[0].detalhe["dia_inteiro"] is False
    assert ev[0].kwh == pytest.approx(float(d.parado[1001].iloc[2:6].sum() * H), rel=1e-6)


def test_duas_paradas_no_mesmo_dia_viram_dois_eventos():
    g = grade_sintetica(); g.inv_p.iloc[0:4, 0] = 0.0; g.inv_p.iloc[5:8, 0] = 0.0   # 1 h, volta 15 min, para de novo
    r, esp, d = _tudo(g)
    ev = sorted(_do_tipo(eventos.detectar(g, r, esp, d), "inversor_parado"), key=lambda e: e.ini)
    assert len(ev) == 1 and ev[0].ini == g.indice[0]        # a 2a corrida tem 3 slots (45 min): fica de fora


def test_inversor_abaixo_dos_pares_por_tres_dias():
    g = grade_sintetica(dias=3); g.inv_p[1002] = 100.0
    r, esp, d = _tudo(g)
    ev = _do_tipo(eventos.detectar(g, r, esp, d), "inversor_abaixo")
    assert [e.equipamento_id for e in ev] == [1002] and ev[0].fim is None and ev[0].ini == g.indice[0]
    assert ev[0].kwh == pytest.approx(float((esp[1002] - 100.0).sum() * H), rel=1e-6) and len(ev[0].detalhe["razoes"]) == 3
    g = grade_sintetica(dias=3); g.inv_p.iloc[8:, 1] = 100.0          # so 2 dias abaixo
    r, esp, d = _tudo(g)
    assert not _do_tipo(eventos.detectar(g, r, esp, d), "inversor_abaixo")


def test_tracker_fora_do_alvo_exige_uma_hora_seguida():
    g = grade_sintetica(); g.trk_ang[2002] = [50.0] * 6 + [20.0] * 2
    r, esp, d = _tudo(g)
    ev = _do_tipo(eventos.detectar(g, r, esp, d), "tracker_fora_alvo")
    assert [e.equipamento_id for e in ev] == [2002] and ev[0].fim == g.indice[5] + pd.Timedelta(minutes=15)
    assert ev[0].kwh == pytest.approx(float(d.perda_trk[2002].iloc[:6].sum() * H), rel=1e-6) and ev[0].detalhe["excesso_max"] == pytest.approx(30.0, abs=1e-6)
    g = grade_sintetica(); g.trk_ang[2002] = [50.0] * 2 + [20.0] * 6
    r, esp, d = _tudo(g)
    assert not _do_tipo(eventos.detectar(g, r, esp, d), "tracker_fora_alvo")


def test_string_sem_corrente_o_dia_inteiro():
    g = grade_sintetica(); g.str_i[3104] = 0.0
    r, esp, d = _tudo(g)
    ev = _do_tipo(eventos.detectar(g, r, esp, d), "string_sem_corrente")
    assert [e.equipamento_id for e in ev] == [3104] and ev[0].detalhe["inversor_id"] == 1001
    assert ev[0].kwh == pytest.approx(float(d.string[1001].sum() * H), rel=1e-6)
    g = grade_sintetica(); g.str_i.iloc[:4, 3] = 0.0                     # metade do dia nao e 'sem corrente'
    r, esp, d = _tudo(g)
    assert not _do_tipo(eventos.detectar(g, r, esp, d), "string_sem_corrente")


@pytest.mark.parametrize("arq", ["mro100_2026-08-26.json", "mro100_2026-08-31.json", "mro100_2026-09-01.json"])
def test_golden_mro100_eventos(arq):
    g, r, esp = esperado_de_placa(G / arq)
    v = veredito(G / arq)
    d = dc.decompor(g, esp, trk_inv_mro100(g), dc.ParamsDecomp())
    evs = eventos.detectar(g, r, esp, d)
    assert {e.equipamento_id for e in _do_tipo(evs, "inversor_parado")} == {1000 + int(n) for n in v["inv_parado"]}
    assert {2000 + t for t in v["trackers"]} <= {e.equipamento_id for e in _do_tipo(evs, "tracker_fora_alvo")}
    assert len(_do_tipo(evs, "string_sem_corrente")) == v["strings_sem_corrente"]
    assert not _do_tipo(evs, "sensor_em_falha") and not _do_tipo(evs, "sem_cobertura")
