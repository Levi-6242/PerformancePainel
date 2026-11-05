# -*- coding: utf-8 -*-
"""O registro de eventos de tracker gravado sem colisão e sem regravar à toa (auditoria do worker, 02/11/2026, achado 3).

O caso: todo recálculo das ocorrências de hoje (banco, Athon, 2C, backfill) terminava no `_trk_ev_save()`, que regrava o
`trk_eventos.json` inteiro (26 MB, de 01/07 até hoje): 20 a 30 vezes por hora, ~0,5–0,8 GB/h de disco no worker. E as
threads (a ETAPA 1 do prewarm roda PG, Athon e 2C em paralelo) e o web gravavam pelo MESMO `trk_eventos.json.tmp`, com o
lock só na montagem do texto: duas gravações cruzadas publicavam um arquivo quebrado, que as Falhas leem como "sem
trackers". No mesmo padrão, o `_trk_parada_reconcilia` sujava o snapshot todo minuto, mudasse ou não.
"""
import os
import time

import pytest

import app


@pytest.fixture
def registro(monkeypatch, tmp_path):
    trocas = []
    real = app._replace_atomico
    monkeypatch.setattr(app, "_TRK_EV_PATH", str(tmp_path / "trk_eventos.json"))
    monkeypatch.setattr(app, "_TRK_FIM_DIA_PATH", str(tmp_path / "trk_parados_fim_dia.json"))
    monkeypatch.setattr(app, "_trk_eventos", {"2026-11-02": {"1": {"eventos": []}}})
    monkeypatch.setattr(app, "_MODO_WEB", False)
    monkeypatch.setattr(app, "_trk_ev_gravacao", {"ultima": 0.0, "pendente": False})
    monkeypatch.setattr(app, "_replace_atomico", lambda o, d, *a, **k: trocas.append((o, d)) or real(o, d))
    return trocas


def _do_registro(trocas):
    return [o for o, d in trocas if d == app._TRK_EV_PATH]


def test_cada_gravacao_usa_o_seu_temporario(registro):
    app._trk_ev_save(forcar=True)
    app._trk_ev_save(forcar=True)
    tmps = _do_registro(registro)
    assert len(tmps) == 2 and tmps[0] != tmps[1], "duas gravações pelo mesmo .tmp: as threads se cruzam"
    assert not [n for n in os.listdir(os.path.dirname(app._TRK_EV_PATH)) if n.endswith(".tmp")]


def test_o_recalculo_de_hoje_grava_no_maximo_a_cada_10_min(registro):
    app._trk_ev_save()                                                # a 1ª grava
    app._trk_ev_save()                                                # 2 min depois: fica pendente
    assert len(_do_registro(registro)) == 1
    app._trk_ev_grava_pendente()                                      # o laço do snapshot, antes dos 10 min
    assert len(_do_registro(registro)) == 1
    app._trk_ev_gravacao["ultima"] = time.time() - 601
    app._trk_ev_grava_pendente()                                      # passados os 10 min, o pendente vai ao disco
    assert len(_do_registro(registro)) == 2
    app._trk_ev_grava_pendente()                                      # nada mais pendente
    assert len(_do_registro(registro)) == 2


def test_no_web_grava_na_hora(registro, monkeypatch):
    monkeypatch.setattr(app, "_MODO_WEB", True)                       # o web não tem o laço do snapshot
    app._trk_ev_save()
    app._trk_ev_save()
    assert len(_do_registro(registro)) == 2


def test_a_parada_sem_mudanca_nao_suja_o_snapshot(monkeypatch):
    monkeypatch.setattr(app, "_trk_parada_total", {"date": None, "plants": {}})
    monkeypatch.setattr(app, "_pv_trk_itens",
                        lambda: [(7, {"payload": {"total": 4, "parados": 4, "desvios": 0, "usina": "U7"}})])
    monkeypatch.setattr(app, "_persist_flag", {"dirty": False})
    app._trk_parada_reconcilia()
    assert app._persist_flag["dirty"], "a usina que parou tem de ir ao snapshot"
    app._persist_flag["dirty"] = False
    app._trk_parada_reconcilia()                                      # um minuto depois, nada mudou
    assert not app._persist_flag["dirty"], "sujou o snapshot sem mudança: ele é regravado todo minuto"
