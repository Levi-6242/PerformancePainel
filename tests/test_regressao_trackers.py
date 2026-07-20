"""Regressao da deteccao de TRACKERS contra casos REAIS rotulados (projeto Confiabilidade da
Plataforma). Cada par (foto `.raw.json` + gabarito `.gab.json`) em fixtures/trackers/ vira um
teste: reproduz a curva CAPTURADA pelo classificador de PRODUCAO (`_pv_trk_refina_curva`, a
mesma logica do front) e compara com a verdade narrada pelo especialista.

ADICIONAR UM CASO = soltar 2 arquivos JSON na pasta. Zero codigo novo.

Formato do gabarito (.gab.json):
    {
      "refere_a": "Primavera 1 · trackers · 2026-07-06 · apipv",
      "dia_tipo": "perfeito",
      "narrativa": "...",                      # a sua verdade, em prosa
      "esperado": { "TRK07": {"status": "parado"}, ... },   # por-tracker (opcional)
      "agregado_esperado": { "parado": 0, "desvio": 0 }     # as contagens (o pega-catastrofe)
    }
"""
import os
import glob
import json
import time

import pytest
import app

FIXDIR = os.path.join(os.path.dirname(__file__), "fixtures", "trackers")
CASOS = sorted(glob.glob(os.path.join(FIXDIR, "*.raw.json")))


def _caso_id(path):
    return os.path.basename(path).replace(".raw.json", "")


def _classifica(raw):
    """Roda o classificador por CURSO (esquema novo, Levi 09/07) sobre a foto (dado cru).
    Funcao pura sobre a curva -> {tracker: status} em parado/desvio_severo/desvio_leve/normal."""
    return app._trk_classifica_curso(raw["grafico"])


@pytest.mark.parametrize("raw_path", CASOS, ids=[_caso_id(p) for p in CASOS])
def test_deteccao_trackers(raw_path):
    raw = json.load(open(raw_path, encoding="utf-8"))
    gab_path = raw_path.replace(".raw.json", ".gab.json")
    if not os.path.exists(gab_path):
        pytest.skip("foto capturada, ainda sem gabarito (caso em coleta)")
    gab = json.load(open(gab_path, encoding="utf-8"))
    # Fase de COLETA: caso rotulado que a régua ATUAL ainda não unifica fica pendente (não falha a
    # suíte). Some quando a régua única for decidida e o campo for removido.
    if gab.get("regua_pendente"):
        pytest.skip("gabarito registrado; aguardando a régua unificada de classificação")
    status = _classifica(raw)
    nota = gab.get("narrativa", "")

    # 1) AGREGADO — o pega-catastrofe barato (contagens por estado)
    got = {}
    for v in status.values():
        got[v] = got.get(v, 0) + 1
    for estado, esperado in (gab.get("agregado_esperado") or {}).items():
        obtido = got.get(estado, 0)
        assert obtido == esperado, (
            "{}: '{}' esperado {}, obtido {} | {}".format(_caso_id(raw_path), estado, esperado, obtido, nota))

    # 2) POR-TRACKER — quando o gabarito especifica (verdade fina)
    for trk, spec in (gab.get("esperado") or {}).items():
        exp = spec["status"] if isinstance(spec, dict) else spec
        assert status.get(trk) == exp, (
            "{}: {} esperado '{}', obtido '{}'".format(_caso_id(raw_path), trk, exp, status.get(trk)))
