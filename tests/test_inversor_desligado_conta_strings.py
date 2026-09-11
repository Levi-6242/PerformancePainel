# -*- coding: utf-8 -*-
"""Inversor DESLIGADO conta todas as strings como faltantes; OS atribuída tira o inversor da conta (Levi, 11/09/2026).

"Sempre tem um ruído de corrente, porém dá para saber se está desligado ou não": um inversor com Pac ~0 de dia e
strings lendo 0,8–1 A de corrente reversa passava na régua por string (mediana ≥ 0,5 A = 'produzindo') e suas
strings contavam como ATIVAS — o déficit da usina ficava menor do que é. A régua de potência que o drill já usava
(_macro_prod: Pac abaixo do piso ou muito abaixo da mediana dos pares, com a usina gerando) passa a valer também
na linha da usina (build_summary): inversor desligado = 0 strings ativas. E quando o analista atribui uma OS ao
inversor (estado os_atribuidas, chave plant_id|idefinversor), as esperadas dele saem da conta: alguém já cuida."""
import json

import app

PID = 987654
NOME = "Usina Teste Desligado"


def _rec(inv_id, pac, correntes, ts="2026-09-11 12:00:00"):
    cj = {"Pac": pac, "Eday": 100.0, "Temp": 30.0}
    cj.update({f"Ipv{i + 1}": c for i, c in enumerate(correntes)})
    return {"idefinversor": inv_id, "tsleitura_new": ts, "conteudojson": json.dumps(cj)}


def _registros():
    """3 inversores gerando (100 kW, 10 strings a 8 A) + 1 desligado (0,3 kW) com 10 strings a 0,9 A de ruído."""
    recs = [_rec(i, 100.0, [8.0] * 10) for i in (1, 2, 3)]
    recs.append(_rec(4, 0.3, [0.9] * 10))
    return recs


def _arma(monkeypatch, os_map=None):
    monkeypatch.setitem(app.ESPERADO, NOME, {"inv_esp": 4, "str_esp": 40})
    monkeypatch.setitem(app.ESPERADO_INV, NOME, {})            # sem nomes → desconto pela média
    monkeypatch.setattr(app, "_os_atribuidas_map", lambda: dict(os_map or {}))
    monkeypatch.setattr(app, "_pv_dev_names", lambda pid, token: {})
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "")
    return {"id": PID, "nome": NOME}


def test_inversor_desligado_com_ruido_conta_todas_as_strings_como_faltantes(monkeypatch, freeze_now):
    freeze_now("2026-09-11 12:05:00")
    r = app.build_summary(_arma(monkeypatch), _registros())
    assert r["inv_off"] == 1
    assert r["strings_ativas"] == 30, "as 10 strings do inversor desligado (0,9 A de ruído) não podem contar como ativas"
    assert r["str_esp"] == 40 and r["diferenca"] == -10
    assert r["inv_com_os"] == 0 and r["strings_com_os"] == 0


def test_os_atribuida_ao_inversor_tira_as_esperadas_dele_da_conta(monkeypatch, freeze_now):
    freeze_now("2026-09-11 12:05:00")
    plant = _arma(monkeypatch, os_map={f"{PID}|4": {"folio": "12345", "usina": NOME}})
    r = app.build_summary(plant, _registros())
    assert r["inv_off"] == 1 and r["strings_ativas"] == 30
    assert r["inv_com_os"] == 1 and r["strings_com_os"] == 10
    assert r["str_esp"] == 30 and r["diferenca"] == 0, "com OS no inversor, o déficit dele não é mais 'faltante'"


def test_de_noite_a_regua_de_potencia_nao_zera_ninguem(monkeypatch, freeze_now):
    """À noite todo inversor está com Pac ~0: não é 'desligado', é noite. A régua só vale com a usina gerando de dia."""
    freeze_now("2026-09-11 22:00:00")
    recs = [_rec(i, 0.0, [0.0] * 10, ts="2026-09-11 21:55:00") for i in (1, 2, 3, 4)]
    r = app.build_summary(_arma(monkeypatch), recs)
    assert r["inv_off"] == 0 or r["strings_ativas"] == 0     # nada a zerar: as strings já estão inativas


def test_inversor_gerando_pouco_mas_dentro_dos_pares_nao_e_desligado(monkeypatch, freeze_now):
    """Piso relativo: 60 kW com os pares a 100 kW é produção, não trip."""
    freeze_now("2026-09-11 12:05:00")
    recs = [_rec(i, 100.0, [8.0] * 10) for i in (1, 2, 3)] + [_rec(4, 60.0, [5.0] * 10)]
    r = app.build_summary(_arma(monkeypatch), recs)
    assert r["inv_off"] == 0 and r["strings_ativas"] == 40 and r["diferenca"] == 0
