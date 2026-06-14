"""Acumulador diário de trackers (SunOp/Athon) — _trk_accum_feed / _desvio / _parados.

GOTCHA (memória testes-automatizados-plano): _trk_accum_feed só amostra dentro de
[TRK_DIA_INI=9, TRK_DIA_FIM=15) hora LOCAL. Para teste determinístico, congela-se o
relógio com o fixture freeze_now. Os leitores (_desvio/_parados) são puros sobre o
estado, então parte dos testes monta app._trk_accum direto via o fixture trk_accum.
"""
import app


def _trk(amin, amax, n=8, soma=0.0):
    return {"n": n, "sum": soma, "amin": amin, "amax": amax}


# ── Leitores puros sobre o estado ─────────────────────────────────────────────

def test_parados_caso_validado(trk_accum):
    # 8 amostras; TRK10-15 com amplitude 80°, TRK16 travado (amplitude 0).
    trk = {f"TRK{i}": _trk(-40.0, 40.0) for i in range(10, 16)}
    trk["TRK16"] = _trk(0.0, 0.0)
    trk_accum["plants"]["1"] = {"last_ts": "x", "samples": 8, "trk": trk}
    assert app._trk_accum_parados(1) == {"TRK16"}


def test_parados_poucas_amostras_nao_julga(trk_accum):
    # < 6 amostras (começo do dia): não acusa ninguém.
    trk = {f"TRK{i}": _trk(-40.0, 40.0) for i in range(10, 16)}
    trk["TRK16"] = _trk(0.0, 0.0)
    trk_accum["plants"]["1"] = {"last_ts": "x", "samples": 5, "trk": trk}
    assert app._trk_accum_parados(1) == set()


def test_parados_usina_nao_girou(trk_accum):
    # Mediana das amplitudes < TRK_ALVO_MOVE_MIN: a usina toda parou (ex.: nublado),
    # não dá para apontar tracker travado.
    trk = {f"TRK{i}": _trk(0.0, 5.0) for i in range(10, 16)}  # todos amplitude 5
    trk_accum["plants"]["1"] = {"last_ts": "x", "samples": 8, "trk": trk}
    assert app._trk_accum_parados(1) == set()


def test_parados_usina_inexistente(trk_accum):
    assert app._trk_accum_parados(999) == set()


def test_desvio_medio(trk_accum):
    # desvio = média (entre trackers) da disparidade média de cada tracker.
    trk = {"TRK1": _trk(0.0, 80.0, n=10, soma=20.0),   # média 2.0
           "TRK2": _trk(0.0, 80.0, n=10, soma=40.0)}   # média 4.0
    trk_accum["plants"]["1"] = {"last_ts": "x", "samples": 8, "trk": trk}
    assert app._trk_accum_desvio(1) == 3.0


def test_desvio_sem_amostras(trk_accum):
    assert app._trk_accum_desvio(999) is None


# ── Caminho completo via o feed (com relógio congelado) ───────────────────────

def test_feed_acumula_e_detecta_travado(trk_accum, freeze_now):
    freeze_now("2026-06-14 12:00:00")          # dentro de [9, 15)
    for s in range(8):
        ang = -40.0 if s % 2 == 0 else 40.0    # extremos alternados -> amplitude 80
        trios = [(f"TRK{i}", 5.0, ang) for i in range(10, 16)]
        trios.append(("TRK16", 5.0, 0.0))      # travado: ângulo constante
        app._trk_accum_feed(1, f"2026-06-14T12:{s:02d}:00", trios)

    ent = app._trk_accum["plants"]["1"]
    assert ent["samples"] == 8
    assert app._trk_accum_parados(1) == {"TRK16"}


def test_feed_fora_da_janela_nao_amostra(trk_accum, freeze_now):
    freeze_now("2026-06-14 08:00:00")          # antes das 9h
    app._trk_accum_feed(2, "2026-06-14T08:00:00", [("TRK1", 5.0, 10.0)])
    assert app._trk_accum["plants"].get("2") is None


def test_feed_dedup_mesmo_ts(trk_accum, freeze_now):
    freeze_now("2026-06-14 12:00:00")
    app._trk_accum_feed(3, "ts-A", [("TRK1", 5.0, 0.0)])
    app._trk_accum_feed(3, "ts-A", [("TRK1", 5.0, 50.0)])  # mesmo ts -> ignora
    ent = app._trk_accum["plants"]["3"]
    assert ent["samples"] == 1
    # o segundo ângulo (50.0) não entrou: amplitude segue 0
    assert ent["trk"]["TRK1"]["amax"] == ent["trk"]["TRK1"]["amin"] == 0.0


def test_feed_vira_o_dia(trk_accum, freeze_now):
    # Amostra num dia; ao "virar" para outra data, o acumulador zera.
    freeze_now("2026-06-13 12:00:00")
    app._trk_accum_feed(4, "ts-1", [("TRK1", 5.0, 10.0)])
    assert "4" in app._trk_accum["plants"]
    freeze_now("2026-06-14 12:00:00")
    app._trk_accum_feed(5, "ts-2", [("TRK1", 5.0, 10.0)])
    assert app._trk_accum["date"] == "2026-06-14"
    assert "4" not in app._trk_accum["plants"]   # estado do dia anterior foi descartado
    assert "5" in app._trk_accum["plants"]
