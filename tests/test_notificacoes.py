# -*- coding: utf-8 -*-
"""Notificador de strings que zeraram (_notif_ciclo) — regras que ja custaram ruido em 05/09/2026.

Tudo mockado: fontes, estado e relogio. O que se prova aqui:
  1. a 1a leitura do dia so estabelece a base (nada e avisado);
  2. string nova sem corrente na leitura seguinte vira UM evento, e `fontes` registra quem foi lido;
  3. fonte que levanta excecao mantem as chaves da leitura anterior (nao "recupera" tudo para reavisar depois);
  4. fonte que devolve lista VAZIA tendo zeradas antes mantem a anterior (cache frio pos-restart);
  5. leitura anterior ha mais de _NOTIF_REBASE_H horas (PC suspenso) → rebase, sem avisar;
  6. de noite, sem `forcar`, nao le nem grava.
"""
import pytest

import app


@pytest.fixture
def estado(monkeypatch):
    """Estado em memoria no lugar do ufv_state.json."""
    box = {"st": {}}
    monkeypatch.setattr(app, "_load_state", lambda: box["st"])

    def _save(st):
        box["st"] = st
    monkeypatch.setattr(app, "_save_state", _save)
    return box


@pytest.fixture
def fontes(monkeypatch):
    """Resposta por fonte: lista de rows, ou uma excecao para levantar."""
    resp = {}

    def _rows(fonte, force=False):
        v = resp.get(fonte, [])
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.setattr(app, "_strings_problema_rows", _rows)
    monkeypatch.setattr(app, "_NOTIF_FONTES", (("pv", "Thopen · API PV"), ("sunop", "Athon")))
    return resp


def _row(usina, pid, inv, st):
    return {"usina": usina, "plant_id": pid, "inversor": inv, "string": st, "cliente": "Thopen"}


def _notif(estado):
    return estado["st"].get("notif") or {}


def test_primeira_leitura_do_dia_so_cria_base(estado, fontes, freeze_now):
    freeze_now("2026-09-05 08:00:00")
    fontes["pv"] = [_row("Guatambu", 1, "Inversor 1.1", "3")]
    assert app._notif_ciclo() == 0
    n = _notif(estado)
    assert n["dia"] == "2026-09-05" and n["eventos"] == []
    assert set(n["snapshot"]) == {"pv|1|Inversor 1.1|3"}
    assert n["fontes"]["pv"] == {"rotulo": "Thopen · API PV", "ok": True, "n": 1}
    assert n["fontes"]["sunop"]["n"] == 0


def test_string_nova_vira_um_evento_com_deep_link_completo(estado, fontes, freeze_now):
    freeze_now("2026-09-05 08:00:00")
    fontes["pv"] = [_row("Guatambu", 1, "Inversor 1.1", "3")]
    app._notif_ciclo()
    freeze_now("2026-09-05 08:30:00")
    fontes["pv"] = [_row("Guatambu", 1, "Inversor 1.1", "3"), _row("Ipixuna 2", 33, "Inversor 2.7", "17")]
    assert app._notif_ciclo() == 1
    ev = _notif(estado)["eventos"]
    assert len(ev) == 1
    e = ev[0]
    # o sino monta /tempo-real/<fonte>?usina=<plant_id>&inversor=<nome>&dia=<quando> com estes campos
    assert (e["fonte"], e["plant_id"], e["inversor"], e["string"]) == ("pv", 33, "Inversor 2.7", "17")
    assert e["quando"] == "2026-09-05T08:30:00" and e["tipo"] == "string_zerou"


def test_fonte_que_falha_mantem_a_leitura_anterior(estado, fontes, freeze_now):
    freeze_now("2026-09-05 08:00:00")
    fontes["pv"] = [_row("Guatambu", 1, "Inversor 1.1", "3")]
    fontes["sunop"] = [_row("CPP100", "cpp", "INV 1", "7")]
    app._notif_ciclo()
    freeze_now("2026-09-05 08:30:00")
    fontes["sunop"] = RuntimeError("SunOp 401")
    assert app._notif_ciclo() == 0
    n = _notif(estado)
    assert "sunop|cpp|INV 1|7" in n["snapshot"]           # nao sumiu: se sumisse, a proxima leitura reavisaria
    assert n["fontes"]["sunop"]["ok"] is False and "401" in n["fontes"]["sunop"]["erro"]
    # e a volta da fonte com a MESMA string nao avisa de novo
    freeze_now("2026-09-05 09:00:00")
    fontes["sunop"] = [_row("CPP100", "cpp", "INV 1", "7")]
    assert app._notif_ciclo() == 0


def test_lista_vazia_com_zeradas_antes_e_cache_frio_nao_cura(estado, fontes, freeze_now):
    freeze_now("2026-09-05 08:00:00")
    fontes["pv"] = [_row("Guatambu", 1, "Inversor 1.1", str(i)) for i in range(40)]
    app._notif_ciclo()
    freeze_now("2026-09-05 08:30:00")
    fontes["pv"] = []                                       # payload da aba ainda nao existe → lista vazia
    assert app._notif_ciclo() == 0
    n = _notif(estado)
    assert len([k for k in n["snapshot"] if k.startswith("pv|")]) == 40
    assert n["fontes"]["pv"]["ok"] is True and n["fontes"]["pv"]["n"] == 40
    freeze_now("2026-09-05 09:00:00")                       # cache aqueceu: as mesmas 40 voltam → nada novo
    fontes["pv"] = [_row("Guatambu", 1, "Inversor 1.1", str(i)) for i in range(40)]
    assert app._notif_ciclo() == 0


def test_intervalo_longo_rebaseia_sem_avisar(estado, fontes, freeze_now):
    freeze_now("2026-09-05 08:00:00")
    fontes["pv"] = [_row("Guatambu", 1, "Inversor 1.1", "3")]
    app._notif_ciclo()
    freeze_now("2026-09-05 12:45:00")
    app._notif_ciclo()
    # o PC dormiu (caso real de 05/09: 12:56 → 22:20); a leitura das 13:00 nao existiu, a proxima e 3h15 depois.
    # Horarios com SOL de proposito: desde 10/09 uma string que zera com o sol baixo na usina (sol.py) e
    # descartada como anoitecer — o cenario original (17:50 → 18:15) hoje cai nessa peneira, e isso e testado em
    # test_sol_macro_sino.py. Aqui o que se prova e o rebase por intervalo longo.
    freeze_now("2026-09-05 16:00:00")
    fontes["pv"] = [_row("Guatambu", 1, "Inversor 1.1", str(i)) for i in range(30)]
    assert app._notif_ciclo() == 0                          # 29 strings novas, mas 3h15 depois: e base, nao aviso
    n = _notif(estado)
    assert n["ultima"] == "2026-09-05T16:00:00" and len(n["snapshot"]) == 30
    freeze_now("2026-09-05 16:30:00")                       # a partir dai volta a comparar normalmente
    fontes["pv"].append(_row("Guatambu", 1, "Inversor 1.2", "1"))
    assert app._notif_ciclo() == 1


def test_de_noite_nao_le_nem_grava(estado, fontes, freeze_now):
    freeze_now("2026-09-05 22:40:00")
    fontes["pv"] = [_row("Guatambu", 1, "Inversor 1.1", "3")]
    assert app._notif_ciclo() == 0
    assert _notif(estado) == {}                             # nada gravado
    assert app._notif_ciclo(forcar=True) == 0               # forcado grava, mas e base
    assert _notif(estado)["dia"] == "2026-09-05"
