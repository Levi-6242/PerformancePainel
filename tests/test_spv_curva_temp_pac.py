# -*- coding: utf-8 -*-
"""Curva do inversor (API PV, hoje): além das strings, a análise devolve a TEMPERATURA e a POTÊNCIA do inversor
(Temp/Pac do day_inverter) na mesma grade da curva — é o que a visão de correlação do drill-down do dia usa
(Levi, 11/09/2026: "curva do inversor, temperatura se tiver, irradiação"). Só existe em HOJE: o histórico vem do
trygenerate, que não traz Temp — e aí o campo vem None, não lista vazia, para o front dizer "sem temperatura"."""
import json

import app


def _recs(pontos, extra):
    return [{"tsleitura_new": f"2026-09-11 {h:02d}:{m:02d}:00",
             "conteudojson": json.dumps({"Ipv1": 8.0, "Ipv2": 7.8, **extra(i)})}
            for i, (h, m) in enumerate(pontos)]


def test_analise_inversor_traz_temp_e_pac_na_grade_da_curva():
    recs = _recs([(10, 0), (10, 5), (10, 10), (10, 15)], lambda i: {"Temp": 40 + i, "Pac": 50.0 + i})
    r = app._spv_analise_inversor(1, "Inversor 1.1", recs, "11/09/2026", {}, full=False, plant_id=999)
    assert r["temp"]["x"] == ["10:00", "10:05", "10:10", "10:15"] and r["temp"]["y"] == [40.0, 41.0, 42.0, 43.0]
    assert r["pac"]["x"] == r["temp"]["x"] and r["pac"]["y"] == [50.0, 51.0, 52.0, 53.0]
    assert r["n_strings"] == 2                                          # as strings continuam iguais


def test_sem_temp_nem_pac_vem_none():
    recs = _recs([(10, 0), (10, 5), (10, 10)], lambda i: {})
    r = app._spv_analise_inversor(1, "Inversor 1.1", recs, "11/09/2026", {}, plant_id=999)
    assert r["temp"] is None and r["pac"] is None


def test_temperatura_absurda_fica_de_fora():
    """Sensor solto manda -273/999: não entra na série (a curva das strings segue normal)."""
    recs = _recs([(10, 0), (10, 5)], lambda i: {"Temp": 999 if i else 38.5, "Pac": 12.0})
    r = app._spv_analise_inversor(1, "Inversor 1.1", recs, "11/09/2026", {}, plant_id=999)
    assert r["temp"] == {"x": ["10:00"], "y": [38.5]} and len(r["pac"]["x"]) == 2
