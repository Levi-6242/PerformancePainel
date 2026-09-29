# -*- coding: utf-8 -*-
"""Piso de cobertura com a regra do dia anterior (29/09/2026, Levi: subir o piso "com a regra do dia anterior").

O piso (`_trk_piso_cobertura`) rebaixa o "parado" de quem tem curva curta — e de manhã toda curva é curta. Medido na
foto de 28/09: às 07:00 a API PV adiava 218 paradas verdadeiras (Guatambu 4, Primavera 1 e 2, Brodowski, frota
travada havia dias) e o Banco 40 da Aparecida 3, até ~10 h; a ronda das 08:25 deixaria de citá-las. Quem estava
parado no último dia CLASSIFICADO do registro não é rebaixado: a curva curta não prova que ele voltou."""
import json
from datetime import datetime

import pytest

import app


def _hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def _manha_imovel(n=6, ate=8 * 60):
    """A frota inteira parada desde a madrugada (−0,2°), leitura de 5 em 5 min das 05:30 até `ate`."""
    return {f"TRK{i}": [{"x": f"2026-09-29T{_hhmm(m)}:00", "y": -0.2} for m in range(5 * 60 + 30, ate + 1, 5)]
            for i in range(1, n + 1)}


def _status(res):
    return {t: (v if isinstance(v, str) else (v or {}).get("status")) for t, v in (res or {}).items()}


@pytest.fixture(params=["v2", "legacy"])
def regua(request, monkeypatch):
    if request.param == "v2":
        if app._regua_v2 is None:
            pytest.skip("trk_regua_v2 indisponível")
        monkeypatch.setattr(app, "TRK_REGUA_V2", True)
    else:
        monkeypatch.setattr(app, "TRK_REGUA_V2", False)
    return request.param


@pytest.fixture
def registro(monkeypatch, tmp_path):
    """Registro do dia (trk_eventos) em memória e o índice do fim do dia num arquivo à parte."""
    monkeypatch.setattr(app, "_trk_eventos", {})
    monkeypatch.setattr(app, "_TRK_FIM_DIA_PATH", str(tmp_path / "trk_parados_fim_dia.json"))
    monkeypatch.setattr(app, "_trk_fim_dia_mem", {"mtime": None, "dados": {}})
    monkeypatch.setattr(app, "_TRK_EV_PATH", str(tmp_path / "trk_eventos.json"))
    return app._trk_eventos


def _classes(**st):
    return {t: {"status": s, "dur_min": None, "ini_min": None, "fim_min": None} for t, s in st.items()}


DISPATCHERS = pytest.mark.parametrize("classifica", [app._trk_classifica_curso, app._trk_classifica_curso_perdas],
                                      ids=["curso", "perdas"])


@DISPATCHERS
def test_parado_no_dia_anterior_nao_e_rebaixado_pela_curva_curta(regua, classifica):
    g = _manha_imovel()
    sem = _status(classifica(g))
    assert "parado" not in sem.values(), sem          # o piso sozinho: frota imóvel de manhã não prova nada
    com = _status(classifica(g, manter={"TRK2", "TRK5"}))
    assert {t for t, s in com.items() if s == "parado"} == {"TRK2", "TRK5"}, com


def test_parados_antes_pega_o_ultimo_dia_classificado(registro):
    registro["2026-09-26"] = {"8": {"classes": _classes(TRK1="parado", TRK2="parado")}}
    registro["2026-09-27"] = {"8": {"classes": _classes(TRK1="parado", TRK3="severo")}}
    registro["2026-09-28"] = {"8": {"cobertura": 0.3, "eventos": []}}      # não classificado: não conta
    assert app._trk_parados_antes("8", "2026-09-29") == {"TRK1"}
    assert app._trk_parados_antes(8, "29/09/2026") == {"TRK1"}             # id numérico e data do registro
    assert app._trk_parados_antes("8", "2026-09-27") == {"TRK1", "TRK2"}   # dia passado olha para trás dele
    assert app._trk_parados_antes("9", "2026-09-29") == set()


def test_mais_de_uma_semana_atras_nao_vale(registro):
    registro["2026-09-20"] = {"8": {"classes": _classes(TRK1="parado")}}
    assert app._trk_parados_antes("8", "2026-09-29") == set()


def test_o_web_le_o_indice_que_o_worker_grava(registro, monkeypatch, freeze_now):
    # o web carrega o registro (26 MB) só no boot; o worker grava junto um índice pequeno do fim de cada dia
    freeze_now("2026-09-29 08:00:00")
    registro["2026-09-28"] = {"8": {"classes": _classes(TRK4="parado")}}
    monkeypatch.setattr(app, "_MODO_WEB", False, raising=False)
    app._trk_ev_save()
    idx = json.load(open(app._TRK_FIM_DIA_PATH, encoding="utf-8"))
    assert idx["8"]["2026-09-28"] == ["TRK4"]
    registro.clear()                                                        # o web não tem o dia em memória
    assert app._trk_parados_antes("8", "2026-09-29") == {"TRK4"}


def test_o_motor_do_banco_mantem_o_parado_de_ontem_de_manha(registro, monkeypatch, freeze_now):
    monkeypatch.setattr(app, "TRK_REGUA_V2", True)
    freeze_now("2026-09-29 08:00:00")
    registro["2026-09-28"] = {"8": {"classes": _classes(TRK3="parado")}}
    g = _manha_imovel()
    trks = {n: {"atual": [(datetime.strptime(p["x"], "%Y-%m-%dT%H:%M:%S"), p["y"]) for p in pts], "alvo": []}
            for n, pts in g.items()}
    monkeypatch.setattr(app, "_pg_trk_plant_curvas", lambda plant_id, date, date_fim=None: trks)
    a = app._pg_trackers_analise("8", "2026-09-29")
    assert [t["id"] for t in a["trackers"] if t["status"] == "parado"] == ["TRK3"], a["trackers"]
    assert a["parados"] == 1


def test_o_grafico_mantem_o_parado_de_ontem(registro, monkeypatch, freeze_now):
    monkeypatch.setattr(app, "TRK_REGUA_V2", True)
    freeze_now("2026-09-29 08:00:00")
    registro["2026-09-28"] = {"8": {"classes": _classes(TRK3="parado")}}
    g = _manha_imovel()
    trackers = [{"id": n, "x": [p["x"] for p in pts], "y": [p["y"] for p in pts]} for n, pts in g.items()]
    payload = {"fim": "2026-09-29"}
    app._trk_chart_aplica_status(trackers, g, payload, pid="8")
    assert {t["id"] for t in trackers if t["status"] == "parado"} == {"TRK3"}


def test_o_registro_do_dia_mantem_o_parado_de_ontem(registro, monkeypatch, freeze_now):
    # a aba de falhas lê o registro: sem isto o tracker travado havia dias "voltava" toda manhã até ~10 h
    monkeypatch.setattr(app, "TRK_REGUA_V2", True)
    freeze_now("2026-09-29 08:00:00")
    registro["2026-09-28"] = {"8": {"classes": _classes(TRK3="parado")}}
    res = app._trk_eventos_do_dia("8", "Aparecida 3", "29/09/2026", curve=_manha_imovel())
    assert {t for t, c in (res["classes"] or {}).items() if c.get("status") == "parado"} == {"TRK3"}


def test_o_refino_da_api_pv_mantem_o_parado_de_ontem(registro, monkeypatch, freeze_now):
    # Guatambu 4, Primavera 1 e 2 e Brodowski são da API PV: é o refino dela que a ronda das 08:25 lê
    monkeypatch.setattr(app, "TRK_REGUA_V2", True)
    freeze_now("2026-09-29 08:00:00")
    registro["2026-09-28"] = {"18745000": {"classes": _classes(TRK3="parado")}}
    g = _manha_imovel()
    monkeypatch.setattr(app, "_pv_trk_grafico", lambda idusina, data, fetch=True: g)
    lst = [{"id": n, "alvo": None, "atual": None, "disparidade": None, "amplitude": None, "max_disp": None,
            "status": "normal"} for n in g]
    app._pv_trk_refina_curva(18745000, lst, "29/09/2026", fetch=False)
    assert [t["id"] for t in lst if t["status"] == "parado"] == ["TRK3"]


def test_o_motor_da_sunop_mantem_o_parado_de_ontem(registro, monkeypatch, freeze_now):
    monkeypatch.setattr(app, "TRK_REGUA_V2", True)
    freeze_now("2026-09-29 08:00:00")
    registro["2026-09-28"] = {"XYZ100": {"classes": _classes(**{"Tracker 3": "parado"})}}
    g = _manha_imovel()
    posat = {f"TRK_{i}": [(p["x"], p["y"]) for p in g[f"TRK{i}"]] for i in range(1, 7)}
    monkeypatch.setattr(app, "_sunop_meta", {"XYZ100": {"trackers": {k: {} for k in posat}, "inv_strings": {}}})
    monkeypatch.setattr(app, "_sunop_trk_curvas", lambda plant, dia, inst="gridco": {"posat": posat, "posal": {}})
    a = app._sunop_trackers_plant_curva("XYZ100", "gridco", "2026-09-29")
    assert [t["id"] for t in a["trackers"] if t["status"] == "parado"] == ["Tracker 3"], a["trackers"]
