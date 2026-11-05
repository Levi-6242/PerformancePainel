# -*- coding: utf-8 -*-
"""O backfill dos eventos de tracker tem teto de tentativas (auditoria do worker, 02/11/2026, achado 5).

O caso: o backfill da hora (`_perdas_trk_backfill` → `_trk_ev_pv_mes(force=True)`) reenfileirava, de hora em hora, todo
par (usina, dia) desde 01/07 sem `classes`. Os ~1.263 pares que nunca classificam (sem curva, cobertura 0) voltavam em
toda passada: ~2,4 h por volta, pedidos pagos à API PV, o `_trk_ev_hoje_loop` parado enquanto ela rodava e ~320 MB de dia
passado presos no cache para servir a releitura. O CLAUDE.md da plataforma já anotava "Ainda aberto". A regra é a de
sempre: laço que refaz dia passado tem teto de tentativas por boot (`_TRK_EV_BF_MAX_ATT`). E o dia de hoje antes da
janela (06:00) só pode dar cobertura 0: não vira pedido.
"""
from datetime import datetime, timedelta

import pytest

import app


def _backfill_pv(monkeypatch, classes):
    """O backfill da API PV com uma usina de tracker e a régua de mentira; devolve a lista dos pedidos feitos."""
    feitos = []
    monkeypatch.setattr(app, "_trk_eventos", {})
    monkeypatch.setattr(app, "_trk_ev_bf_att", {})
    monkeypatch.setattr(app, "_trk_ev_prog", dict(app._trk_ev_prog, running=False))
    monkeypatch.setattr(app, "_swr", lambda *a, **k: None)
    monkeypatch.setattr(app, "_trk_ev_save", lambda: None)
    monkeypatch.setattr(app, "_pv_trk_itens", lambda: [(101, {"payload": {"total": 3, "usina": "U101"}})])
    monkeypatch.setattr(app, "_trk_eventos_do_dia",
                        lambda pid, nome, d_br: feitos.append((pid, d_br)) or {"cobertura": 0.0, "eventos": [],
                                                                               "classes": classes})
    return feitos


def _iso(dias_atras):
    return (datetime.now() - timedelta(days=dias_atras)).strftime("%Y-%m-%d")


def test_o_par_que_nunca_classifica_para_no_teto(monkeypatch):
    feitos, dia = _backfill_pv(monkeypatch, classes=None), _iso(5)
    for _volta in range(5):                                           # cinco horas do backfill da hora
        app._trk_ev_backfill(dia, dia, force=True)
    assert len(feitos) == app._TRK_EV_BF_MAX_ATT, f"{len(feitos)} pedidos do mesmo par que nunca classifica"


def test_o_par_que_classifica_nao_volta(monkeypatch):
    feitos, dia = _backfill_pv(monkeypatch, classes={}), _iso(5)
    for _volta in range(3):
        app._trk_ev_backfill(dia, dia, force=True)
    assert len(feitos) == 1


@pytest.mark.parametrize("hora, pedidos_esperados", [(4, 0), (10, 1)])
def test_hoje_antes_da_janela_nao_vira_pedido(monkeypatch, hora, pedidos_esperados):
    real = datetime

    class _Agora(real):
        @classmethod
        def now(cls, tz=None):
            return real.now(tz).replace(hour=hora, minute=0)

    monkeypatch.setattr(app, "datetime", _Agora)
    feitos = _backfill_pv(monkeypatch, classes=None)
    hoje = _Agora.now().strftime("%Y-%m-%d")
    app._trk_ev_backfill(hoje, hoje)
    assert len(feitos) == pedidos_esperados


def test_o_dia_de_outra_fonte_que_nunca_classifica_para_no_teto(monkeypatch):
    calculos = []
    monkeypatch.setattr(app, "_trk_ev_bf_att", {})
    monkeypatch.setattr(app, "_TRK_EV_BF_FONTES", (("pg", lambda d: calculos.append(d), {}),))
    monkeypatch.setattr(app, "_trk_ev_pids", lambda fonte: {"1"})
    monkeypatch.setattr(app, "_trk_ev_fonte_total", lambda fonte: 1)
    monkeypatch.setattr(app, "_trk_ev_dia_classes", lambda fonte, dia, pids=None: 0)
    monkeypatch.setattr(app, "_trk_ev_dia_cob", lambda fonte, dia, pids=None: 0)
    dia = _iso(5)
    for _volta in range(5):
        app._trk_ev_backfill_fontes(dia, dia, force=True)
    assert len(calculos) == app._TRK_EV_BF_MAX_ATT, f"{len(calculos)} recálculos do mesmo dia sem classificação"
