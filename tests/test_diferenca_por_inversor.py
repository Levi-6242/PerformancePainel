# -*- coding: utf-8 -*-
"""A diferença da usina é a soma das FALTAS de cada inversor (Levi, 29/09/2026, sobre o print da Rodrigues 2.1 (233):
"String PV10 em vermelho, corrente nula, acusando que não tem 1 ticket, com diferença -1 no inversor e mesmo assim não
acusou na linha principal da usina! É INADMISSÍVEL ESSE ERRO").

O Inversor 1.2 tinha 13 de 14 (a Ipv10 a 0,05 A) e outro inversor 1 string ACIMA do cadastro. A linha fazia a conta pelo
TOTAL — 43 ativas, 43 esperadas, diferença 0, "Normal" —, e a sobra de um inversor pagava a falta do outro. Sobra é
cadastro que conta a menos; falta é string parada. Uma não anula a outra.
"""
import json

import pytest

import app

PID, NOME = 987801, "Usina Teste Diferenca Por Inversor"


def test_a_sobra_de_um_inversor_nao_paga_a_falta_de_outro():
    assert app._dif_por_inversor([(15, 15), (13, 14), (8, 7), (7, 7)], 43) == (-1, 1)


def test_inversor_do_cadastro_que_nao_reportou_continua_faltando():
    """Esperadas que nenhum inversor na conta explica (o que não mandou nada) seguem como falta."""
    assert app._dif_por_inversor([(15, 15), (14, 14)], 43) == (-14, 0)


def test_sem_as_esperadas_de_cada_inversor_vale_a_conta_de_antes():
    assert app._dif_por_inversor([(15, 15), (13, None)], 29) is None
    assert app._dif_por_inversor([], 29) is None


def _rec(inv_id, pac, correntes, ts="2026-09-29 09:20:00"):
    cj = {"Pac": pac, "Eday": 100.0, "Temp": 30.0}
    cj.update({f"Ipv{i + 1}": c for i, c in enumerate(correntes)})
    return {"idefinversor": inv_id, "tsleitura_new": ts, "conteudojson": json.dumps(cj)}


@pytest.fixture
def rodrigues(monkeypatch, freeze_now):
    freeze_now("2026-09-29 09:25:00")
    esp = {"INVERSOR 01": 15, "INVERSOR 02": 14, "INVERSOR 03": 7, "INVERSOR 04": 7}
    monkeypatch.setitem(app.ESPERADO, NOME, {"inv_esp": 4, "str_esp": 43})
    monkeypatch.setitem(app.ESPERADO_INV, NOME, esp)
    monkeypatch.setitem(app.EQUIP_NAMES, NOME, {f"INVERSOR 0{i}": f"Inversor 1.{i}" for i in (1, 2, 3, 4)})
    monkeypatch.setattr(app, "_pv_plant_devices", lambda pid: [{"device_id": i, "device_name": f"INVERSOR 0{i}"} for i in (1, 2, 3, 4)])
    monkeypatch.setattr(app, "_pv_dev_names", lambda pid, token: {i: f"INVERSOR 0{i}" for i in (1, 2, 3, 4)})
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "")
    monkeypatch.setattr(app, "_os_atribuidas_map", lambda: {})
    monkeypatch.setattr(app, "_os_fracttal_inv_abertas", lambda: {})
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    return {"id": PID, "nome": NOME}


def test_linha_da_usina_acusa_a_string_parada_mesmo_com_a_sobra_de_outro_inversor(rodrigues):
    recs = [_rec(1, 60.0, [5.4] * 15), _rec(2, 55.0, [5.4] * 13 + [0.05]), _rec(3, 30.0, [5.4] * 8), _rec(4, 28.0, [5.4] * 7)]
    r = app.build_summary(rodrigues, recs)
    assert r["strings_ativas"] == 43 and r["str_esp"] == 43
    assert r["diferenca"] == -1, "a Ipv10 do 1.2 parada; antes a linha dizia 0 e 'Normal'"
    assert r["strings_acima_cadastro"] == 1


def test_os_atribuida_nao_esconde_a_string_parada_de_inversor_que_gera(rodrigues, monkeypatch):
    """A causa do print: a OS 12093 (recomposição, em andamento desde 24/08) atribuída ao INVERSOR02 em 25/08 tirava da
    linha o inversor INTEIRO — 14 esperadas e 13 ativas —, e a Ipv10 parada nele sumia: 43/43, 'Normal'."""
    monkeypatch.setattr(app, "_os_atribuidas_map", lambda: {f"{PID}|2": {"folio": "12093", "usina": NOME}})
    recs = [_rec(1, 60.0, [5.4] * 15), _rec(2, 55.0, [5.4] * 13 + [0.05]), _rec(3, 58.0, [5.4] * 14), _rec(4, 57.0, [5.4] * 14)]
    monkeypatch.setitem(app.ESPERADO_INV, NOME, {"INVERSOR 01": 15, "INVERSOR 02": 14, "INVERSOR 03": 14, "INVERSOR 04": 14})
    monkeypatch.setitem(app.ESPERADO, NOME, {"inv_esp": 4, "str_esp": 57})
    r = app.build_summary(rodrigues, recs)
    assert r["diferenca"] == -1 and r["str_esp"] == 57 and r["strings_ativas"] == 56
    assert r["inv_com_os"] == 0 and r["os_na_conta"] == ["12093"], "a OS aparece, mas não esconde a falta"


def test_os_atribuida_em_inversor_desligado_continua_desculpando(rodrigues, monkeypatch):
    """A regra de 11/09 que continua: desligado com OS é 'tudo OK' — alguém já cuida."""
    monkeypatch.setattr(app, "_os_atribuidas_map", lambda: {f"{PID}|2": {"folio": "12093", "usina": NOME}})
    recs = [_rec(1, 60.0, [5.4] * 15), _rec(2, 0.0, [0.0] * 14), _rec(3, 30.0, [5.4] * 7), _rec(4, 28.0, [5.4] * 7)]
    r = app.build_summary(rodrigues, recs)
    assert r["inv_com_os"] == 1 and r["inv_desligados"] == 0 and r["diferenca"] == 0


def test_sem_falta_nenhuma_a_diferenca_segue_zero(rodrigues):
    recs = [_rec(1, 60.0, [5.4] * 15), _rec(2, 55.0, [5.4] * 14), _rec(3, 30.0, [5.4] * 7), _rec(4, 28.0, [5.4] * 7)]
    r = app.build_summary(rodrigues, recs)
    assert r["diferenca"] == 0 and r["strings_acima_cadastro"] == 0


def test_a_tela_explica_a_sobra_no_titulo_da_diferenca():
    import pathlib
    mon = (pathlib.Path(app.__file__).resolve().parents[1] / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")
    assert "r.strings_acima_cadastro" in mon, "o −1 com 43/43 precisa dizer por quê"
