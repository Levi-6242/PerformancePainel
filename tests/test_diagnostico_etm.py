"""_diagnostico_etm(series) — diagnóstico da curva intradiária de irradiância (PV/PG).

series = [(datetime, poa, ghi), ...]. A função usa datetime.now(), então todos os
testes congelam o relógio às 14:00 (dentro da janela de sol). Cada teste isola UM
flag, construindo a curva mínima que dispara só ele.

Régua (ver app.py): 0=crítico, 1=atenção, 3=normal.
"""
from datetime import datetime, timedelta

import app

DIA = "2026-06-14"
AGORA = f"{DIA} 14:00:00"


def _curva(poa, ghi, ini="09:00", fim="13:50", passo_min=10):
    """Gera uma série constante de (t, poa, ghi) de `ini` a `fim` (passo em min)."""
    t = datetime.strptime(f"{DIA} {ini}:00", "%Y-%m-%d %H:%M:%S")
    t_fim = datetime.strptime(f"{DIA} {fim}:00", "%Y-%m-%d %H:%M:%S")
    serie = []
    while t <= t_fim:
        serie.append((t, poa, ghi))
        t += timedelta(minutes=passo_min)
    return serie


def _tipos(res):
    return {f["t"] for f in res["flags"]}


def test_curva_saudavel(freeze_now):
    freeze_now(AGORA)
    res = app._diagnostico_etm(_curva(800, 700))
    assert res["severidade"] == 3
    assert res["flags"] == []
    # sparkline preenchida e última leitura formatada
    assert res["spark"]["labels"]
    assert res["ultima_leitura"] == f"{DIA} 13:50"


def test_sem_comunicacao(freeze_now):
    # Última leitura às 11:00, agora 14:00 -> diff 180 min > 30 -> crítico.
    freeze_now(AGORA)
    res = app._diagnostico_etm(_curva(800, 700, fim="11:00"))
    assert "Sem comunicação" in _tipos(res)
    assert res["severidade"] == 0


def test_poa_zerado(freeze_now):
    # POA sempre < 20 em horário de sol (agora.hour >= 10) -> crítico.
    freeze_now(AGORA)
    res = app._diagnostico_etm(_curva(5, 5))
    assert "POA zerado" in _tipos(res)
    assert res["severidade"] == 0


def test_ghi_maior_que_poa(freeze_now):
    # GHI > POA+5 em >60% do tempo -> atenção (sensor POA suspeito).
    freeze_now(AGORA)
    res = app._diagnostico_etm(_curva(300, 400))
    assert "GHI > POA" in _tipos(res)
    assert res["severidade"] == 1


def test_queda_de_poa(freeze_now):
    # Curva sadia com um dropout curto (cai a zero e volta) -> "Quedas de POA".
    freeze_now(AGORA)
    serie = _curva(800, 700)
    # zera POA e GHI em dois pontos no meio (para o dropout não virar GHI>POA)
    i = len(serie) // 2
    serie[i] = (serie[i][0], 0, 0)
    serie[i + 1] = (serie[i + 1][0], 0, 0)
    res = app._diagnostico_etm(serie)
    tipos = _tipos(res)
    assert any(t.startswith("Quedas de POA") for t in tipos)
    assert "POA zerado" not in tipos  # o pico da janela continua alto
    assert res["severidade"] == 1


def test_possivel_falta_atraso_de_dia(freeze_now):
    # De dia, última leitura há 20 min (entre 15 e o crítico de 30) -> possível falta (atenção).
    freeze_now(AGORA)
    res = app._diagnostico_etm(_curva(800, 700, fim="13:40"))
    assert "Possível falta de dados" in _tipos(res)
    assert res["severidade"] == 1
    assert "Sem comunicação" not in _tipos(res)


def test_possivel_falta_buraco_no_dia(freeze_now):
    # Última leitura recente, mas há um buraco > 30 min no meio do dia -> possível falta.
    freeze_now(AGORA)
    serie = _curva(800, 700)
    ci = datetime.strptime(f"{DIA} 11:00:00", "%Y-%m-%d %H:%M:%S")
    cf = datetime.strptime(f"{DIA} 12:00:00", "%Y-%m-%d %H:%M:%S")
    serie = [(t, p, g) for (t, p, g) in serie if not (ci <= t < cf)]   # buraco ~70 min
    res = app._diagnostico_etm(serie)
    assert "Possível falta de dados" in _tipos(res)
    assert res["severidade"] == 1


def test_atraso_a_noite_nao_sinaliza(freeze_now):
    # À noite (fora de 6h-18h), atraso de 20 min NÃO vira "possível falta" (gap noturno é normal).
    freeze_now(f"{DIA} 22:00:00")
    res = app._diagnostico_etm(_curva(0, 0, ini="20:00", fim="21:40"))
    assert "Possível falta de dados" not in _tipos(res)
    assert res["severidade"] == 3


def test_serie_vazia(freeze_now):
    freeze_now(AGORA)
    res = app._diagnostico_etm([])
    assert res["severidade"] == 3
    assert res["flags"] == []
    assert res["ultima_leitura"] is None


def test_ignora_timestamps_nulos(freeze_now):
    freeze_now(AGORA)
    res = app._diagnostico_etm([(None, 800, 700), (None, 500, 400)])
    assert res["severidade"] == 3
    assert res["flags"] == []
