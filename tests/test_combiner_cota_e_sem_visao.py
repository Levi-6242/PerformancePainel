# -*- coding: utf-8 -*-
"""Cota de consultas históricas da API PV e o falso "1 string por inversor" (Levi, 25/09/2026: "Você limitou Tanabi,
Cambé, Assis e Ouro Branco 4 a 1 string por inversor"; "também restringiu as strings de Altair, Brodowski, Ceilândia...").

A API PV tem cota por conta: 800 consultas HISTÓRICAS por dia e 200 por hora (cabeçalhos X-RateLimit-Limit-Day/-Hour,
X-RateLimit-Remaining-*, Retry-After), e a combiner sai do custom_query, que conta nela. A plataforma pedia a combiner
de ~35 usinas a cada 5 min, em dobro com a cópia local: ~840 por hora, cota zerada de manhã. Sem combiner:
  - usina marcada String Box (Altair, Ceilândia, Sarandi...) → "sem visão" (honesto, mas sem strings);
  - usina NÃO marcada (Cambé, Assis, Tanabi, Ouro Branco 4) → a corrente única do day_inverter virava "1 de 11": −191.
Duas travas:
  1. inversor gerando com UMA corrente, sem combiner, e o cadastro esperando mais de 1 string = "sem visão", marcado ou
     não (Pharma III/IV, 1 string por inversor no cadastro, continua contando);
  2. a combiner lê a cota a cada resposta e para antes de gastar a reserva do coletor e do fechamento da noite.
"""
import json
import time

import pytest

import app

PID, NOME = 987671, "Usina Teste Cota Combiner"


def _rec(inv_id, pac, correntes, ts="2026-09-25 10:00:00"):
    cj = {"Pac": pac, "Eday": 100.0, "Temp": 30.0}
    cj.update({f"Ipv{i + 1}": c for i, c in enumerate(correntes)})
    return {"idefinversor": inv_id, "tsleitura_new": ts, "conteudojson": json.dumps(cj)}


@pytest.fixture
def usina(monkeypatch, freeze_now):
    freeze_now("2026-09-25 10:05:00")
    monkeypatch.setitem(app.ESPERADO, NOME, {"inv_esp": 2, "str_esp": 22})
    monkeypatch.setitem(app.ESPERADO_INV, NOME, {"INVERSOR 01": 11, "INVERSOR 02": 11})
    monkeypatch.setitem(app.EQUIP_NAMES, NOME, {"INVERSOR 01": "Inversor 1.1", "INVERSOR 02": "Inversor 1.2"})
    monkeypatch.setattr(app, "STRING_BOX", set(app.STRING_BOX) - {NOME})      # NÃO marcada, como a Cambé
    monkeypatch.setattr(app, "_pv_plant_devices", lambda pid: [{"device_id": i, "device_name": f"INVERSOR 0{i}", "device_type": "INVERTER"} for i in (1, 2)])
    monkeypatch.setattr(app, "_pv_dev_names", lambda pid, token: {i: f"INVERSOR 0{i}" for i in (1, 2)})
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "")
    monkeypatch.setattr(app, "_combiner_strings", lambda pid, inv: None)      # combiner não veio (cota zerada)
    monkeypatch.setattr(app, "_os_atribuidas_map", lambda: {})
    monkeypatch.setattr(app, "_os_fracttal_inv_abertas", lambda: {})
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    return {"id": PID, "nome": NOME}


def test_uma_corrente_sem_combiner_e_sem_visao_e_nao_1_de_11(usina):
    r = app.build_summary(usina, [_rec(i, 100.0, [11.5]) for i in (1, 2)])
    assert r["diferenca"] == 0, "era −20: a corrente única do day_inverter contava como 1 string de 11"
    assert r["sem_visao"] is True and r["strings_ativas"] == 0 and r["str_esp"] == 0


def test_inversor_de_1_string_no_cadastro_continua_contando(usina, monkeypatch):
    """Pharma III/IV: o cadastro diz 1 string por inversor, e a corrente única É a string."""
    monkeypatch.setitem(app.ESPERADO, NOME, {"inv_esp": 2, "str_esp": 2})
    monkeypatch.setitem(app.ESPERADO_INV, NOME, {"INVERSOR 01": 1, "INVERSOR 02": 1})
    r = app.build_summary(usina, [_rec(i, 100.0, [11.5]) for i in (1, 2)])
    assert r["sem_visao"] is False and r["strings_ativas"] == 2 and r["str_esp"] == 2 and r["diferenca"] == 0


def test_no_drill_a_corrente_unica_sem_combiner_fica_sem_visao(usina, monkeypatch):
    class _Resp:
        def __init__(self, d):
            self._d = d

        def json(self):
            return self._d

    class _Http:
        def post(self, url, **k):
            return _Resp([_rec(i, 100.0, [11.5]) for i in (1, 2)])

        def get(self, url, **k):
            return _Resp([{"device_id": i, "device_name": f"INVERSOR 0{i}"} for i in (1, 2)])
    monkeypatch.setattr(app, "_http", lambda: _Http())
    monkeypatch.setattr(app, "get_plants", lambda token, force=False: [{"id": PID, "nome": NOME}])
    invs = app._pv_plant_inversores(PID, force=True)
    assert all(i["sem_visao"] and i["strings"] == [] and i["diferenca"] is None for i in invs), invs[0]


# ── a cota ────────────────────────────────────────────────────────────────────

class _R:
    def __init__(self, status=200, headers=None):
        self.status_code, self.headers = status, headers or {}

    def json(self):
        return []


@pytest.fixture
def rede(monkeypatch):
    estado = {"idas": 0, "resp": _R()}

    class _H:
        def post(self, url, **k):
            estado["idas"] += 1
            return estado["resp"]
    monkeypatch.setattr(app, "_http", lambda: _H())
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "")
    monkeypatch.setattr(app, "_pv_plant_devices", lambda pid: [])
    monkeypatch.setattr(app, "_pv_comb_cache", {})
    monkeypatch.setattr(app, "_pv_comb_falhou", {})
    monkeypatch.setattr(app, "_pv_cota", {"dia": None, "hora": None, "ts": 0.0, "zerada_ate": 0.0})
    return estado


def test_com_a_cota_do_dia_na_reserva_a_combiner_para(rede, freeze_now):
    freeze_now("2026-09-25 10:00:00")
    rede["resp"] = _R(headers={"X-RateLimit-Remaining-Day": str(app.PV_COTA_RESERVA_DIA - 1), "X-RateLimit-Remaining-Hour": "150"})
    app._pv_combiner_usina(1)
    assert rede["idas"] == 1
    app._pv_comb_cache.clear()
    app._pv_combiner_usina(2)
    assert rede["idas"] == 1, "abaixo da reserva do dia, não pede mais combiner — a cota da noite é do coletor"


def test_429_da_cota_para_tudo_ate_o_retry_after(rede, freeze_now):
    freeze_now("2026-09-25 10:00:00")
    rede["resp"] = _R(status=429, headers={"Retry-After": "50713", "X-RateLimit-Remaining-Day": "0"})
    app._pv_combiner_usina(1)
    app._pv_comb_falhou.clear()
    app._pv_combiner_usina(2)
    app._pv_combiner_usina(3)
    assert rede["idas"] == 1, "com a cota zerada até a meia-noite, cada pedido é um 429 a mais"
    assert app._pv_cota["zerada_ate"] > time.time() + 50000


def test_de_dia_a_combiner_vale_1_hora(rede, freeze_now):
    freeze_now("2026-09-25 12:00:00")
    app._pv_comb_cache[1] = {"ts": time.time() - 50 * 60, "por_inv": {}}
    app._pv_combiner_usina(1)
    assert rede["idas"] == 0
    app._pv_comb_cache[1] = {"ts": time.time() - 61 * 60, "por_inv": {}}
    app._pv_combiner_usina(1)
    assert rede["idas"] == 1


def test_a_noite_nao_renova(rede, freeze_now):
    freeze_now("2026-09-25 23:00:00")
    app._pv_comb_cache[1] = {"ts": time.time() - 5 * 3600, "por_inv": {}}
    app._pv_combiner_usina(1)
    assert rede["idas"] == 0
