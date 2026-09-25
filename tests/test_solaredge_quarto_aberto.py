# -*- coding: utf-8 -*-
"""A tabela da RenoGrid julga o último quarto de hora FECHADO, não o que está em andamento (25/09/2026).

O generate-chart devolve o quarto de hora aberto PARCIAL: medido na Xavantina 2, o das 12:00, recém-aberto, com 0,6–2,7
kW em strings de 13,6 kW. A tabela (se_string_power) usava o último ponto — ele. Enquanto a régua era "qualquer W > 0 é
ativa" isso não mudava a conta; com a régua de inversor desligado da Athon (24/09, potência < 5% da mediana), mudou:
às 14:48, 3 min depois de abrir o quarto, a linha dava 21 inversores desligados na Colíder 1 (30/30 strings) e 8 na
Colíder 2, contra 0 e 0 com o último quarto fechado (164/166 e 144/146). Alarme falso por uns minutos de cada quarto.
"""
import pytest

import app

TZ = "America/Cuiaba"


class _Resp:
    def __init__(self, code, payload=None):
        self.status_code = code
        self._p = payload or {}

    def json(self):
        return self._p


@pytest.fixture
def se(monkeypatch, freeze_now):
    freeze_now("2026-09-25 14:48:00")                       # 17:48Z — o quarto das 17:45Z abriu há 3 min
    # 3 inversores de 4 strings, todos gerando ~2,5 kW por string no quarto FECHADO (17:30Z). No quarto ABERTO (17:45Z)
    # só o 3 já mandou alguma coisa — parcial, 50 W por string. Os outros dois ainda não têm ponto no aberto.
    devs = [{"deviceType": "INVERTER", "deviceSerial": f"I{i}", "deviceName": f"Inverter {i}"} for i in (1, 2, 3)]
    devs += [{"deviceType": "STRING", "deviceSerial": f"S{i}.{s}", "deviceName": f"String {i}.{s}", "partOfSerial": f"I{i}"}
             for i in (1, 2, 3) for s in (1, 2, 3, 4)]

    def _serie(u):
        rows = [["2026-09-25T17:15:00Z", 600.0, 2450.0], ["2026-09-25T17:30:00Z", 620.0, 2500.0]]
        if u.startswith("S3."):
            rows.append(["2026-09-25T17:45:00Z", 12.0, 50.0])
        return rows

    class _H:
        def post(self, url, json=None, **k):
            uu = json["datasources"][0]["datasourcePopulation"]["deviceSerials"]
            return _Resp(200, {"meta": {"datasetsMeta": [{"reportObject": {"entityId": u}} for u in uu]},
                               "data": [_serie(u) for u in uu]})
    monkeypatch.setattr(app, "_http", lambda: _H())
    monkeypatch.setattr(app, "_se_headers", lambda: {})
    monkeypatch.setattr(app, "se_devices", lambda sid: devs)
    nome = "UFV Teste SE Quarto Aberto"
    monkeypatch.setitem(app.ESPERADO_INV, nome, {f"Inverter {i}": 4 for i in (1, 2, 3)})
    monkeypatch.setitem(app.EQUIP_NAMES, nome, {f"Inverter {i}": f"Inversor {i}" for i in (1, 2, 3)})
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    return {"id": 777021, "nome": nome, "timezone": TZ, "inv": 3}


def test_o_valor_da_tabela_e_o_do_ultimo_quarto_fechado(se):
    power, ts_max, falhos = app.se_string_power(se["id"], ["S3.1", "S1.1"], TZ)
    assert power["S3.1"] == 2500.0, "era 50 W: o quarto das 17:45Z ainda aberto, parcial"
    assert power["S1.1"] == 2500.0 and falhos == 0
    assert ts_max == "2026-09-25T17:30:00Z", "a última leitura é a do quarto fechado"


def test_quarto_aberto_nao_desliga_inversor_gerando(se):
    r = app.process_site_solaredge(se)
    assert r["inv_desligados"] == 0, "o inversor 3 estava gerando 10 kW; os 50 W por string eram o quarto parcial"
    assert r["strings_ativas"] == 12 and r["str_esp"] == 12 and r["diferenca"] == 0
