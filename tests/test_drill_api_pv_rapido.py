# -*- coding: utf-8 -*-
"""Abrir uma usina da API PV (o drill, _pv_plant_inversores) mais rápido (Levi, 24/09/2026: "pra mim sem cache está
demorando uns 2 minutos"; depois "trabalhe em reduzir!").

Medido na Santana do Ipanema (24 inversores) às 22h, com a API PV lenta, cronometrando cada chamada: 74 s no total —
login 24 s, day_inverter 18,5 s, lista de usinas 17,5 s, plant_devices 10,6 s, UMA DEPOIS DA OUTRA, e mais 24 consultas
de combiner (uma por inversor), todas respondidas 429 ("limite de requisições"). Três mudanças:

  1. day_inverter, lista de usinas e plant_devices em PARALELO: a espera é a da mais lenta, não a soma;
  2. dispositivos do cache de 30 min (_pv_plant_devices), que só guarda resposta boa;
  3. combiner só onde pode haver combiner: usina String Box no cadastro OU inversor gerando (a mesma porta do
     build_summary). À noite, com tudo a zero, eram 24 consultas inúteis por abertura, gastando o limite da API PV.
     E combiner que falhou (429, 5xx, rede) não é perguntado de novo por PV_COMB_ESPERA_FALHA_S.
"""
import json
import threading
import time

import pytest

import app

PID, NOME = 987661, "Usina Teste Drill Rapido"


def _rec(inv_id, pac, correntes, ts="2026-09-24 12:00:00"):
    cj = {"Pac": pac, "Eday": 100.0, "Temp": 30.0}
    cj.update({f"Ipv{i + 1}": c for i, c in enumerate(correntes)})
    return {"idefinversor": inv_id, "tsleitura_new": ts, "conteudojson": json.dumps(cj)}


class _Resp:
    def __init__(self, d, status=200):
        self._d, self.status_code = d, status

    def json(self):
        return self._d


@pytest.fixture
def api(monkeypatch, freeze_now):
    """API PV falsa: cada chamada demora `espera` s e é contada; o combiner responde o que o teste mandar."""
    freeze_now("2026-09-24 12:05:00")
    estado = {"espera": 0.0, "recs": [_rec(i, 100.0, [8.0] * 4) for i in (1, 2)], "idas": {}, "comb_status": 429}
    lock = threading.Lock()

    def _conta(nome):
        with lock:
            estado["idas"][nome] = estado["idas"].get(nome, 0) + 1

    class _Http:
        def post(self, url, **k):
            if "custom_query" in url:
                _conta("combiner")
                return _Resp([], estado["comb_status"])
            _conta("day_inverter")
            time.sleep(estado["espera"])
            return _Resp(estado["recs"])

        def get(self, url, **k):
            _conta("plant_devices")
            time.sleep(estado["espera"])
            return _Resp([{"device_id": i, "device_name": f"INVERSOR 0{i}"} for i in (1, 2)])

    def _plants(token, force=False):
        _conta("plants")
        time.sleep(estado["espera"])
        return [{"id": PID, "nome": NOME}]
    monkeypatch.setattr(app, "_http", lambda: _Http())
    monkeypatch.setattr(app, "get_plants", _plants)
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "")
    monkeypatch.setattr(app, "_os_atribuidas_map", lambda: {})
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    monkeypatch.setattr(app, "_pv_devs_cache", {})
    monkeypatch.setattr(app, "_pv_comb_cache", {})
    monkeypatch.setattr(app, "_pv_comb_falhou", {})
    monkeypatch.setattr(app, "_plat_combiner_strings", lambda idinv: None)
    monkeypatch.setitem(app.EQUIP_NAMES, NOME, {"INVERSOR 01": "Inversor 1.1", "INVERSOR 02": "Inversor 1.2"})
    monkeypatch.setitem(app.ESPERADO_INV, NOME, {"INVERSOR 01": 4, "INVERSOR 02": 4})
    return estado


def test_as_tres_chamadas_da_abertura_vao_em_paralelo(api):
    api["espera"] = 0.6
    t0 = time.time()
    invs = app._pv_plant_inversores(PID, force=True)
    gasto = time.time() - t0
    assert len(invs) == 2
    assert gasto < 1.3, f"{gasto:.1f}s: day_inverter, plants e plant_devices uma depois da outra (1,8 s)"


def test_dispositivos_vem_do_cache_de_30_min(api):
    app._pv_plant_inversores(PID, force=True)
    app._pv_plant_inversores(PID, force=True)
    assert api["idas"]["plant_devices"] == 1 and api["idas"]["day_inverter"] == 2


def test_a_noite_nao_consulta_combiner_de_usina_que_nao_e_string_box(api):
    api["recs"] = [_rec(i, 0.0, [0.0] * 4, ts="2026-09-24 21:55:00") for i in (1, 2)]
    app._pv_plant_inversores(PID, force=True)
    assert api["idas"].get("combiner", 0) == 0, "24 consultas inúteis por abertura, à noite, na Santana do Ipanema"


def test_inversor_gerando_sem_corrente_por_string_ainda_consulta_combiner(api):
    """A assinatura do String Box fora do cadastro (Sarandi, 05/08): gera, mas o day_inverter não traz as strings."""
    api["recs"] = [_rec(i, 100.0, [0.0] * 4) for i in (1, 2)]
    app._pv_plant_inversores(PID, force=True)
    assert api["idas"].get("combiner", 0) >= 1


def test_string_box_do_cadastro_consulta_combiner_mesmo_a_noite(api, monkeypatch):
    monkeypatch.setattr(app, "STRING_BOX", set(app.STRING_BOX) | {NOME})
    api["recs"] = [_rec(i, 0.0, [0.0] * 4, ts="2026-09-24 21:55:00") for i in (1, 2)]
    app._pv_plant_inversores(PID, force=True)
    assert api["idas"].get("combiner", 0) >= 1


def test_combiner_que_falhou_nao_e_perguntado_de_novo_logo_em_seguida(api):
    """429 da API PV: 24 inversores = 24 consultas seguidas, e cada uma gastava mais do limite."""
    api["recs"] = [_rec(i, 100.0, [0.0] * 4) for i in (1, 2)]
    app._pv_plant_inversores(PID, force=True)
    assert api["idas"]["combiner"] == 1, "o 2º inversor perguntou de novo, com a 1ª resposta 429 de agora há pouco"
    api["comb_status"] = 200
    app._pv_comb_falhou[PID] = time.time() - app.PV_COMB_ESPERA_FALHA_S - 1
    app._pv_plant_inversores(PID, force=True)
    assert api["idas"]["combiner"] == 2, "passado o tempo, pergunta de novo"
