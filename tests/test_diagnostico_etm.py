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


# ── GHI zerado (Levi 27/08, caso Canarana 1) ─────────────────────────────────
def _serie_dia(poa_fn, ghi_fn, freeze_now):
    from datetime import datetime, timedelta
    freeze_now("2026-08-27 14:00:00")
    base = datetime(2026, 8, 27, 6, 0)
    return [(base + timedelta(minutes=10 * i), poa_fn(i), ghi_fn(i)) for i in range(60)]


def test_ghi_zerado_com_poa_medindo_vira_alarme(freeze_now):
    """Até 09/09 era 'atenção' (âmbar). Régua do Levi em 10/09: "alarmar apenas GHI e IPOA zerados" — GHI medido em
    zero com o POA medindo é crítico igual ao POA zerado, e a flag diz o sensor (caso MTS100: POA 1.143, GHI 0)."""
    s = _serie_dia(lambda i: 400 + i, lambda i: 0.0, freeze_now)
    d = app._diagnostico_etm(s)
    f = {x["t"]: x for x in d["flags"]}
    assert f["GHI zerado"]["tipo"] == "crit" and f["GHI zerado"]["sensor"] == "GHI"
    assert d["severidade"] == 0


def test_estacao_sem_sensor_ghi_nao_e_flagada(freeze_now):
    """GHI = None em tudo → o sensor NÃO EXISTE; zero medido é diferente de nada reportado."""
    s = _serie_dia(lambda i: 400 + i, lambda i: None, freeze_now)
    d = app._diagnostico_etm(s)
    assert "GHI zerado" not in [f["t"] for f in d["flags"]]


def test_ghi_normal_nao_flagra(freeze_now):
    s = _serie_dia(lambda i: 400 + i, lambda i: 380 + i, freeze_now)
    assert "GHI zerado" not in [f["t"] for f in app._diagnostico_etm(s)["flags"]]


def test_ghi_ausente_com_poa_medindo_vira_nota(freeze_now):
    """Canarana 1 (27/08): GHI = None o dia todo com POA normal — flag própria, distinta de 'GHI zerado' (zero
    MEDIDO). Em 27/08 era 'warn'; em 10/09 o Levi viu 8 cards da Athon alarmados por estações AIML que NÃO TÊM
    sensor de GHI e mandou: só zero medido alarma. Ausência vira NOTA (cinza), sem severidade; o sensor que
    existia e sumiu aparece no diagnóstico do mês (BD_Performance), que é onde se notifica."""
    s = _serie_dia(lambda i: 400 + i, lambda i: None, freeze_now)
    d = app._diagnostico_etm(s)
    f = {x["t"]: x for x in d["flags"]}
    assert "Sem leitura de GHI" in f and "GHI zerado" not in f
    assert f["Sem leitura de GHI"]["tipo"] == "nota" and f["Sem leitura de GHI"]["sensor"] == "GHI"
    assert d["severidade"] == 3
    assert d["sensores"]["ghi"]["status"] == "sem_leitura"


def test_poa_tambem_fora_nao_acusa_ghi(freeze_now):
    """POA sem medir (usina/estação fora) → o problema é maior e já tem flag própria; não empilha
    'Sem leitura de GHI' em cima."""
    s = _serie_dia(lambda i: 0.0, lambda i: None, freeze_now)
    ts = [f["t"] for f in app._diagnostico_etm(s)["flags"]]
    assert "Sem leitura de GHI" not in ts


# ── POA-RI: informativo em AZUL, fora da régua (Levi 27/08) ──────────────────
def test_poari_zerado_e_info_e_nao_mexe_na_severidade(freeze_now):
    s = _serie_dia(lambda i: 400 + i, lambda i: 380 + i, freeze_now)
    ri = [(t, 0.0) for (t, _, _) in s]
    d = app._diagnostico_etm(s, poari=ri)
    f = next((f for f in d["flags"] if f["t"] == "POA-RI zerado"), None)
    assert f and f["tipo"] == "info"
    assert d["severidade"] == 3                    # NÃO entra na régua


def test_poari_ausente_vira_info_leve(freeze_now):
    s = _serie_dia(lambda i: 400 + i, lambda i: 380 + i, freeze_now)
    ri = [(t, None) for (t, _, _) in s]
    d = app._diagnostico_etm(s, poari=ri)
    assert any(f["t"] == "Sem leitura de POA-RI" and f["tipo"] == "info" for f in d["flags"])
    assert d["severidade"] == 3


def test_fonte_sem_poari_nao_ganha_flag(freeze_now):
    s = _serie_dia(lambda i: 400 + i, lambda i: 380 + i, freeze_now)
    d = app._diagnostico_etm(s)                    # sem a lista → nada de POA-RI
    assert not any("POA-RI" in f["t"] for f in d["flags"])
