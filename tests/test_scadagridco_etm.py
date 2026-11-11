# -*- coding: utf-8 -*-
"""A ETM das fontes do scadaGridco (11/11/2026).

Levi: "GreenYellow e Apolo não estão mostrando ETM, tá certo isso??". Não estava: o supervisório manda a estação como o
equipamento `weather` do gateway MQTT e a plataforma não lia. Aqui: a série do dia sai do /api/telemetria (tipo weather),
o "-" do ponto sem sensor é sem leitura (nunca zero), a leitura ruim do gateway é lacuna, a usina sem estação fica fora da
aba e a análise é a mesma das outras fontes.
"""
import time
from datetime import datetime

import pytest

import app
import scadagridco as sg

HOJE = sg.hoje()


def _reg(hh_mm, poa, ghi, rear=40.0, chuva="-", fault=192, equip="1"):
    h = datetime.strptime(f"{HOJE} {hh_mm}", "%Y-%m-%d %H:%M")
    return {"equipamento": equip, "tipo": "weather", "communication_fault": fault, "ts": h.timestamp(),
            "data_hora": h.strftime("%Y-%m-%d %H:%M:%S"),
            "pontos": {"irradiance_poa": poa, "irradiance_ghi": ghi, "irradiance_poa_rear": rear,
                       "accumulated_rain": chuva, "hourly_accumulated_rain": "-"}}


def test_serie_da_estacao_sem_leitura_nao_vira_zero():
    s = sg.serie_estacao([_reg("10:01", 800.0, 600.0), _reg("10:00", 790.0, 590.0),
                          _reg("10:02", "-", "-"),                       # sem sensor: fora, não zero
                          _reg("10:03", 810.0, 610.0, fault=28)])        # leitura ruim do gateway: lacuna
    assert [(h.strftime("%H:%M"), poa, ghi) for h, poa, ghi in s["serie"]] == [("10:00", 790.0, 590.0),
                                                                              ("10:01", 800.0, 600.0)]
    assert [v for _h, v in s["poari"]] == [40.0, 40.0] and s["chuva"] is False
    assert sg.serie_estacao([_reg("10:00", 1.0, 1.0, chuva=0.2)])["chuva"] is True


@pytest.fixture
def api(monkeypatch):
    pedidos = []
    regs = [_reg(f"{h:02d}:{m:02d}", 900.0 * (1 - abs(12 - h) / 7), 600.0 * (1 - abs(12 - h) / 7))
            for h in range(6, 18) for m in range(0, 60, 5)]

    def get(rota, params=None, timeout=None):
        pedidos.append((rota, dict(params or {})))
        if rota == "/api/mqtt/dermeval_lobao":
            return {"equipamentos": [{"equipamento": "1", "tipo": "inverter"}, {"equipamento": "1", "tipo": "weather"}]}
        if rota.startswith("/api/mqtt/"):
            return {"equipamentos": [{"equipamento": "1", "tipo": "inverter"}]}          # sem estação
        if rota == "/api/telemetria":
            assert params["tipo"] == "weather" and params["desde"] == params["ate"] == HOJE
            return {"registros": regs if params["usina"] == "dermeval_lobao" else [], "proximo_apos_ts": None}
        raise AssertionError(rota)
    monkeypatch.setattr(sg, "get", get)
    monkeypatch.setattr(sg, "EXTRAS", {})
    monkeypatch.setattr(app, "_cob_entra", lambda fonte, chave: True)
    return pedidos


def test_a_aba_etm_da_greenyellow_le_a_estacao(api):
    d = app._sg_etm_build("greenyellow")
    assert [r["usina"] for r in d["rows"]] == ["Demerval Lobao"]          # Irecê 2 e Macaíba sem estação aqui: fora
    r = d["rows"][0]
    assert r["sem_dados"] is False and r["estacao"] == "1" and r["estacoes"] == 1 and r["pluviometro"] is False
    assert r["ultima_leitura"] and r["spark"]["poa"]
    assert ("/api/telemetria", {"usina": "dermeval_lobao", "desde": HOJE, "ate": HOJE, "tipo": "weather",
                                "equipamento": "1", "limit": sg.LIMITE}) in api


def test_a_apolo_sem_estacao_fica_com_a_aba_vazia(api):
    assert app._sg_etm_build("apolo")["rows"] == []


def test_a_rota_e_o_monitoramento_apontam_para_a_etm(api):
    app.app.config["TESTING"] = True
    with app.app.test_client() as c:
        app._gy_etm_cache.update(payload=None, ts=0.0)
        j = c.get("/api/greenyellow/etm/analise").get_json()
    assert [r["usina"] for r in j["rows"]] == ["Demerval Lobao"]
    mon = (app._AQUI and open(app.os.path.join(app._RAIZ, "docs", "redesign", "Monitoramento (novo design).html"),
                              encoding="utf-8").read())
    assert "greenyellow:'/api/greenyellow/etm/analise'" in mon and "apolo:'/api/apolo/etm/analise'" in mon
