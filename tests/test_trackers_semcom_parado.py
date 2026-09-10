# -*- coding: utf-8 -*-
"""Tracker SEM COMUNICAÇÃO travado em ângulo fixo conta como PARADO (Levi, 08/09/2026).

Até aqui `_trk_semcom_set` só rotulava: quem emudecia no MEIO do dia tinha rastreado horas antes de congelar,
a amplitude do dia era grande e o classificador devolvia 'normal' — ficava com a etiqueta de sem comunicação e
FORA da contagem de parados, da disponibilidade e da ronda. A promoção vale nos DOIS dispatchers (curso e
perdas), senão overview e disponibilidade divergem.
"""
import inspect

import app


def _serie(ini, fim, y0, y1, passo=10):
    """Pontos de `ini` a `fim` (minutos do dia) varrendo de y0 a y1."""
    n = max(1, (fim - ini) // passo)
    return [{"x": f"2026-09-08T{(ini + k * passo) // 60:02d}:{(ini + k * passo) % 60:02d}:00",
             "y": round(y0 + (y1 - y0) * k / n, 2)} for k in range(n + 1)]


def _frota(n=8):
    return {f"Tracker {i}": _serie(6 * 60, 18 * 60, -50, 50) for i in range(1, n + 1)}


def test_mudo_no_meio_do_dia_vira_parado():
    """Rastreou até 11h, emudeceu e ficou no ângulo daquela hora: está travado, e agora conta."""
    g = _frota()
    g["Tracker 9"] = _serie(6 * 60, 11 * 60, -50, -8)          # some às 11h, com a frota seguindo até 18h
    cls = {n: "normal" for n in g}
    app._trk_promove_semcom(g, cls)
    assert cls["Tracker 9"] == "parado", "mudo desde as 11h continuou fora da contagem"
    assert all(cls[f"Tracker {i}"] == "normal" for i in range(1, 9)), "a frota que rastreou foi promovida junto"


def test_sensor_morto_em_angulo_fixo_tambem():
    g = _frota()
    g["Tracker 9"] = [{"x": p["x"], "y": 0.0} for p in _serie(6 * 60, 18 * 60, 0, 0)]
    cls = {n: "normal" for n in g}
    app._trk_promove_semcom(g, cls)
    assert cls["Tracker 9"] == "parado"


def test_um_tracker_reportando_tarde_nao_derruba_a_frota():
    """A trava: `_trk_semcom_set` rotula pelo MÁXIMO da frota, então um único ponto tardio marcaria todo mundo
    como defasado — antes isso só errava a cor; com a promoção erraria o CONTADOR. Aqui vale a MEDIANA."""
    g = _frota()
    g["Tracker 9"] = _serie(6 * 60, 18 * 60, -50, 50) + [{"x": "2026-09-08T23:50:00", "y": 50.0}]
    cls = {n: "normal" for n in g}
    app._trk_promove_semcom(g, cls)
    assert all(v == "normal" for v in cls.values()), f"promoveu a frota inteira: {cls}"


def test_contrato_de_perdas_ganha_o_episodio():
    g = _frota()
    g["Tracker 9"] = _serie(6 * 60, 11 * 60, -50, -8)
    cls = {n: {"status": "normal", "dur_min": None, "ini_min": None, "fim_min": None} for n in g}
    app._trk_promove_semcom(g, cls)
    r = cls["Tracker 9"]
    assert r["status"] == "parado" and r["ini_min"] == 11 * 60 and r["fim_min"] == 18 * 60
    assert r["dur_min"] == 7 * 60, "a janela do episódio é do silêncio ao fim do dia"


def test_promocao_vale_nos_dois_dispatchers():
    """Curso alimenta o status das 5 fontes e o gráfico; perdas alimenta a disponibilidade. Os dois ou nenhum."""
    for fn in (app._trk_classifica_curso, app._trk_classifica_curso_perdas):
        assert "_trk_promove_semcom" in inspect.getsource(fn), f"{fn.__name__} não promove"
