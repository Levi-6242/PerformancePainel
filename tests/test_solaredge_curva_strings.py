# -*- coding: utf-8 -*-
"""Curva do dia por string na RenoGrid (Levi, 25/09/2026: "é dessa forma que eu gero a curva das strings na plataforma
da RenoGrid ... veja se consegue identificar o caminho para que possamos ver as strings a partir de agora").

O caminho é o generate-chart do portal da SolarEdge (Análise > gráfico personalizado) — o MESMO que a tabela já chama
em se_string_power, com o login automático da plataforma (Cognito), sem o token de ninguém. A tabela fica só com o
ÚLTIMO ponto de cada string; a curva guarda o dia inteiro. É POTÊNCIA (W) por string, de 15 em 15 min: a SolarEdge não
dá corrente por string, só por otimizador. Até aqui o drill da RenoGrid nem pedia curva ("solaredge: sem curva") e dizia
"a usina pode não ter reportado", e a aba "Curva das strings" dava a fonte por indisponível.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
MON = (RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")
NODE = shutil.which("node")

SID, NOME, TZ = 4425838, "UFV Teste SE Curva", "America/Cuiaba"      # Mato Grosso, UTC−4 (a do print do Levi)


class _Resp:
    def __init__(self, code, payload=None):
        self.status_code = code
        self._p = payload or {}

    def json(self):
        return self._p


def _serie(uuid, dia="2026-09-25"):
    """row = [ts ISO-Z, energia Wh, potência W] — o formato do generate-chart. Hoje, o último é o quarto de hora EM
    ANDAMENTO (15:00Z, e agora são 15:10Z): chega parcial — no real, 648 W numa string de 13,6 kW."""
    if uuid == "S2.3":                                                    # veio na resposta, sem potência hoje
        return [[f"{dia}T10:00:00Z", None, None], [f"{dia}T10:15:00Z", None, None]]
    return [[f"{dia}T10:00:00Z", 0.0, 0.0], [f"{dia}T13:00:00Z", 600.0, 2400.0],
            [f"{dia}T14:45:00Z", 775.0, 3100.0], [f"{dia}T15:00:00Z", 55.0, 661.0]]


@pytest.fixture
def se(monkeypatch, freeze_now):
    freeze_now("2026-09-25 12:10:00")                                     # 12:10 em Brasília = 11:10 em Cuiabá
    devs = [{"deviceType": "INVERTER", "deviceSerial": f"I{i}", "deviceName": f"Inverter {i}"} for i in (1, 2)]
    devs += [{"deviceType": "STRING", "deviceSerial": f"S{i}.{s}", "deviceName": f"String {i}.{s}", "partOfSerial": f"I{i}"}
             for i in (1, 2) for s in (1, 2, 3)]
    estado = {"pedidos": [], "resp": None}

    class _H:
        def post(self, url, json=None, **k):
            estado["pedidos"].append({"url": url, "json": json})
            if estado["resp"] is not None:
                return estado["resp"]
            uu = json["datasources"][0]["datasourcePopulation"]["deviceSerials"]
            dia = json["reportPeriod"]["from"][:10]                       # 04:00Z do dia pedido, em Cuiabá
            return _Resp(200, {"meta": {"datasetsMeta": [{"reportObject": {"entityId": u}} for u in uu]},
                               "data": [_serie(u, dia) for u in uu]})
    monkeypatch.setattr(app, "_http", lambda: _H())
    monkeypatch.setattr(app, "_se_headers", lambda: {})
    monkeypatch.setattr(app, "se_devices", lambda sid: devs)
    monkeypatch.setattr(app, "se_sites", lambda: [{"id": SID, "nome": NOME, "timezone": TZ, "inv": 2}])
    monkeypatch.setitem(app.EQUIP_NAMES, NOME, {"Inverter 1": "Inversor 1.1", "Inverter 2": "Inversor 1.2"})
    monkeypatch.setattr(app, "_se_curva_cache", {})
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    return estado


# ── o pedido: o mesmo do portal ───────────────────────────────────────────────

def test_o_pedido_e_o_generate_chart_do_portal(se):
    app._se_strings_curva(SID, "2026-09-25")
    p = se["pedidos"][0]
    assert p["url"].endswith(f"/services/cni/ui-api/pages/site/analysis/custom/site/{SID}/generate-chart")
    ds = p["json"]["datasources"][0]
    assert {m["calculationMetricUri"] for m in ds["metrics"]} == {"energy", "power"}
    assert all(m["periodType"] == "FIVE_MINUTES" for m in ds["metrics"]) and ds["alignmentGranularity"] == "QUARTER_HOUR"
    assert ds["datasourcePopulation"]["deviceType"] == "STRING"
    # hoje: da meia-noite DA USINA (00:00 em Cuiabá = 04:00Z) até agora (12:10 em Brasília = 15:10Z)
    assert p["json"]["reportPeriod"] == {"from": "2026-09-25T04:00:00.000Z", "to": "2026-09-25T15:10:00.999Z"}


def test_dia_passado_pede_o_dia_inteiro_da_usina(se):
    """Exatamente o intervalo que o portal pediu no print: 04:00Z até 03:59:59.999Z do dia seguinte."""
    app._se_strings_curva(SID, "2026-09-20")
    assert se["pedidos"][0]["json"]["reportPeriod"] == {"from": "2026-09-20T04:00:00.000Z", "to": "2026-09-21T03:59:59.999Z"}


def test_um_inversor_so_pede_as_strings_dele(se):
    d = app._se_strings_curva(SID, "2026-09-25", inv="I2")
    assert len(se["pedidos"]) == 1
    assert se["pedidos"][0]["json"]["datasources"][0]["datasourcePopulation"]["deviceSerials"] == ["S2.1", "S2.2", "S2.3"]
    assert [i["id"] for i in d["inversores"]] == ["I2"]


# ── a resposta: o formato da Athon, em W e na hora da usina ───────────────────

def test_curva_por_inversor_em_watt_na_hora_local_da_usina(se):
    d = app._se_strings_curva(SID, "2026-09-25")
    assert d["unidade"] == "W"
    por = {i["nome"]: i for i in d["inversores"]}
    assert list(por) == ["Inversor 1.1", "Inversor 1.2"], "o nome do cadastro, como no drill"
    c = por["Inversor 1.1"]["curva"]
    assert list(c) == ["1.1", "1.2", "1.3"], "a string com o MESMO nome do chip do drill"
    assert c["1.1"] == {"x": ["06:00", "09:00", "10:45"], "y": [0.0, 2400.0, 3100.0]}, "10:00Z = 06:00 em Cuiabá"


def test_quarto_de_hora_em_andamento_nao_entra_na_curva(se):
    """Medido em 25/09 na Xavantina 2: o ponto das 11:45 veio com 10,5–13,5 kW e, 20 min depois, com 13,3–14,9 kW; o
    das 12:00, recém-aberto, com 0,6–2,7 kW. Os outros 27 pontos não mudaram. Desenhado, o quarto aberto parece a usina
    inteira caindo agora — então a curva de hoje vai até o último quarto FECHADO."""
    d = app._se_strings_curva(SID, "2026-09-25", inv="I1")
    assert all(cur["x"][-1] == "10:45" for cur in d["inversores"][0]["curva"].values())


def test_dia_passado_mantem_todos_os_pontos(se):
    d = app._se_strings_curva(SID, "2026-09-24", inv="I1")
    assert d["inversores"][0]["curva"]["1.1"]["x"][-1] == "11:00"


def test_string_sem_potencia_hoje_nao_vira_linha_no_grafico(se):
    """A S2.3 veio na resposta sem nenhum valor: sem ponto, não há linha (o chip dela segue no drill, em 0 W)."""
    d = app._se_strings_curva(SID, "2026-09-25", inv="I2")
    assert list(d["inversores"][0]["curva"]) == ["2.1", "2.2"]


def test_lote_falho_e_dito_e_nao_fica_no_cache(se):
    se["resp"] = _Resp(500)
    c = app.app.test_client()
    d = c.get(f"/api/solaredge/curva/{SID}?inv=I1").get_json()
    assert d["inversores"] == [] and d["lotes_falhos"] == 1
    se["resp"] = None
    d = c.get(f"/api/solaredge/curva/{SID}?inv=I1").get_json()
    assert d["inversores"] and len(se["pedidos"]) == 2, "a falha não pode grudar no cache"


def test_rota_guarda_a_curva_boa_no_cache(se):
    c = app.app.test_client()
    a = c.get(f"/api/solaredge/curva/{SID}?inv=I1").get_json()
    b = c.get(f"/api/solaredge/curva/{SID}?inv=I1").get_json()
    assert a == b and len(se["pedidos"]) == 1


def test_rota_recusa_data_invalida(se):
    assert app.app.test_client().get(f"/api/solaredge/curva/{SID}?data=ontem").status_code == 400


def test_csv_da_curva_da_renogrid(se):
    r = app.app.test_client().get(f"/api/solaredge/strings/curva.csv?usina={SID}&data=2026-09-25")
    assert r.status_code == 200
    linhas = r.get_data(as_text=True).splitlines()
    assert linhas[0] == "inversor,string,hora,potencia_W"
    assert "Inversor 1.1,1.1,09:00,2400.0" in linhas


# ── a tela ────────────────────────────────────────────────────────────────────

def _func(nome, fim="\n}\n"):
    i = MON.index(f"function {nome}(")
    return MON[i:MON.index(fim, i) + len(fim)]


def test_drill_da_renogrid_pede_a_curva():
    js = _func("loadCurva")
    assert "sk==='solaredge'" in js and "/api/solaredge/curva/" in js
    assert "solaredge: sem curva" not in js


def test_aba_curva_das_strings_inclui_a_renogrid():
    m = re.search(r"const _CURVA_FONTES=\[([^\]]*)\]", MON)
    assert "'solaredge'" in m.group(1)
    assert "f==='solaredge'" in _func("loadCurvaView") and "/api/solaredge/curva/" in _func("loadCurvaView")


def test_grafico_da_renogrid_em_watt():
    if not NODE:
        pytest.skip("node não instalado")
    js = _func("curvaSVG") + (
        "const esc=s=>String(s);const _snum=s=>{const d=String(s).replace(/\\D/g,'');return d?parseInt(d,10):null;};"
        "const c={'1.1':{x:['06:00','09:00'],y:[0,2400]}};"
        "process.stdout.write(JSON.stringify([curvaSVG(c,{},false,'W'),curvaSVG(c,{},false)]));")
    p = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    w, a = json.loads(p.stdout)
    assert 'data-unit="W"' in w and 'data-unit="A"' in a, "as outras fontes seguem em ampère"


def test_titulo_do_drill_diz_potencia_na_renogrid():
    assert "potência por string (W)" in _func("_curvaBlock")
