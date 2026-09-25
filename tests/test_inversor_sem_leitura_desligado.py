# -*- coding: utf-8 -*-
"""Inversor do cadastro SEM LEITURA HOJE conta como desligado (Levi, 25/09/2026: "o inversor 1.3 de Colorado 2 está
desligado, a plataforma não conta como desligado").

Colorado 2, 11h: 3 de 4 inversores reportando; o 1.3 nem aparece no day_inverter. A régua de desligado da Athon
(_inv_desligados_por_potencia) olha a POTÊNCIA — e sem leitura ela diz "sem comunicação", não "desligado". As 22
esperadas dele viravam strings faltando (−30, "Falha de string"). Agora, com sol e os outros inversores gerando, o
inversor do cadastro sem leitura sai da conta como o de potência zero, com o aviso. Só casando pelo nome do cadastro e
só se a conta fecha (faltam exatamente inv_esp − os que reportam): nome que não casa não vira "desligado" por engano.
"""
import json

import pytest

import app

PID, NOME = 987681, "Usina Teste Sem Leitura"


def _rec(inv_id, pac, correntes, ts="2026-09-25 11:00:00"):
    cj = {"Pac": pac, "Eday": 100.0, "Temp": 30.0}
    cj.update({f"Ipv{i + 1}": c for i, c in enumerate(correntes)})
    return {"idefinversor": inv_id, "tsleitura_new": ts, "conteudojson": json.dumps(cj)}


@pytest.fixture
def usina(monkeypatch, freeze_now):
    freeze_now("2026-09-25 11:05:00")
    monkeypatch.setitem(app.ESPERADO, NOME, {"inv_esp": 4, "str_esp": 88})
    monkeypatch.setitem(app.ESPERADO_INV, NOME, {f"INVERSOR 0{i}": 22 for i in (1, 2, 3, 4)})
    monkeypatch.setitem(app.EQUIP_NAMES, NOME, {f"INVERSOR 0{i}": f"Inversor 1.{i}" for i in (1, 2, 3, 4)})
    monkeypatch.setattr(app, "STRING_BOX", set(app.STRING_BOX) - {NOME})
    devs = [{"device_id": i, "device_name": f"INVERSOR 0{i}", "device_type": "INVERTER"} for i in (1, 2, 3, 4)]
    monkeypatch.setattr(app, "_pv_plant_devices", lambda pid: devs)
    monkeypatch.setattr(app, "_pv_dev_names", lambda pid, token: {d["device_id"]: d["device_name"] for d in devs})
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "")
    monkeypatch.setattr(app, "_os_atribuidas_map", lambda: {})
    monkeypatch.setattr(app, "_os_fracttal_inv_abertas", lambda: {})
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    return {"id": PID, "nome": NOME}


def _tres_de_quatro():
    return [_rec(i, 100.0, [8.0] * 22) for i in (1, 2, 4)]            # o 1.3 não manda nada hoje


def test_inversor_sem_leitura_com_os_outros_gerando_sai_da_conta(usina):
    r = app.build_summary(usina, _tres_de_quatro())
    assert r["inv_desligados"] == 1 and r["strings_fora"] == 22 and r["inv_desligados_nomes"] == ["Inversor 1.3"]
    assert r["str_esp"] == 66 and r["strings_ativas"] == 66 and r["diferenca"] == 0, "era −22: as esperadas dele faltando"


def test_sem_sol_nada_muda(usina, monkeypatch):
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: False)
    r = app.build_summary(usina, _tres_de_quatro())
    assert r["inv_desligados"] == 0 and r["str_esp"] == 88


def test_nome_que_nao_casa_nao_vira_desligado(usina, monkeypatch):
    """Cadastro com outra grafia (não casa com o plant_devices): a conta não fecha, e ninguém é dado por desligado."""
    monkeypatch.setitem(app.ESPERADO_INV, NOME, {f"INV-{i}": 22 for i in (1, 2, 3, 4)})
    r = app.build_summary(usina, _tres_de_quatro())
    assert r["inv_desligados"] == 0 and r["str_esp"] == 88


def test_a_falha_de_string_de_verdade_continua(usina):
    """O 1.2 da Colorado 2 com 9 strings zeradas continua cobrando: só o inversor sem leitura sai da conta."""
    recs = [_rec(1, 100.0, [8.0] * 22), _rec(2, 90.0, [8.0] * 13 + [0.0] * 9), _rec(4, 100.0, [8.0] * 22)]
    r = app.build_summary(usina, recs)
    assert r["inv_desligados"] == 1 and r["str_esp"] == 66 and r["diferenca"] == -9
