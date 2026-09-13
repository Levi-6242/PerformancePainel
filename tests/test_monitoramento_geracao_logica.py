# -*- coding: utf-8 -*-
"""A conta da visão Geração do drill-down (Monitoramento) roda no navegador; aqui ela roda no node, com o MESMO código
extraído do HTML, para a régua do desvio ser testável: mediana da usina como referência, participação vs. esperado,
dias com dado, e a queda para os nomes da base quando a lista ao vivo não casa por nome."""
import json
import pathlib
import shutil
import subprocess

import pytest

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
MON = (RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")
NODE = shutil.which("node")


def _trecho(ini, fim):
    i = MON.index(ini)
    return MON[i:MON.index(fim, i) + len(fim)]


def _roda(expr):
    if not NODE:
        pytest.skip("node não instalado")
    js = "\n".join([
        _trecho("function _nrmU(", "\n"),
        _trecho("function _gerFaixa(", "/* fim _gerFaixa */"),
        _trecho("function _gerAgrega(", "/* fim _gerAgrega */"),
        "process.stdout.write(JSON.stringify(" + expr + "));",
    ])
    r = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


HIST = {"rateio": "igual", "inversores": {"Inversor 1.1": {"ger": 300, "dias": 2}, "Inversor 1.2": {"ger": 200, "dias": 2}, "Inversor 1.3": {"ger": 100, "dias": 1}},
        "dias": [{"data": "2026-09-01", "origem": "bd_thopen", "inv": {"Inversor 1.1": {"ger": 150}, "Inversor 1.2": {"ger": 100}, "Inversor 1.3": {"ger": 100}}},
                 {"data": "2026-09-02", "origem": "bd_thopen", "inv": {"Inversor 1.1": {"ger": 150}, "Inversor 1.2": {"ger": 100}}},
                 {"data": "2026-09-03", "origem": "bd_thopen", "inv": {"Inversor 1.1": {"ger": 999}}}]}   # fora do período


def test_desvio_e_contra_a_mediana_da_usina_no_periodo_e_conta_so_os_dias_do_recorte():
    invs = [{"name": "Inversor 1.1", "cabine": "cabine 1"}, {"name": "Inversor 1.2"}, {"name": "Inversor 1.3"}]
    a = _roda("_gerAgrega([%s], %s, '2026-09-01', '2026-09-02')" % (json.dumps(HIST), json.dumps(invs)))
    por = {l["name"]: l for l in a["linhas"]}
    assert a["total"] == 600 and a["mediana"] == 200 and a["nDias"] == 2 and a["nComBase"] == 3
    assert por["Inversor 1.1"]["kwh"] == 300 and por["Inversor 1.1"]["n"] == 2
    assert round(por["Inversor 1.1"]["dev"], 1) == 50.0                       # 300 / mediana 200 − 1
    assert round(por["Inversor 1.3"]["dev"], 1) == -50.0 and por["Inversor 1.3"]["n"] == 1   # 100 kWh num dia só
    assert round(por["Inversor 1.2"]["part"], 2) == 33.33 and round(por["Inversor 1.2"]["esp"], 2) == 33.33
    assert a["abaixo"] == 1                                                     # só o 1.3 está abaixo de −10 %
    assert a["origens"] == ["bd_thopen"]


def test_inversor_da_lista_ao_vivo_sem_coluna_na_base_fica_sem_dado_e_nao_derruba_a_mediana():
    invs = [{"name": "Inversor 1.1"}, {"name": "Inversor 1.2"}, {"name": "Inversor 1.9"}]
    a = _roda("_gerAgrega([%s], %s, '2026-09-01', '2026-09-02')" % (json.dumps(HIST), json.dumps(invs)))
    por = {l["name"]: l for l in a["linhas"]}
    assert por["Inversor 1.9"]["kwh"] is None and por["Inversor 1.9"]["dev"] is None
    assert a["nComBase"] == 2 and a["mediana"] == 250                          # (300 + 200) / 2


def test_sem_nenhum_nome_casando_mostra_os_inversores_da_base():
    invs = [{"name": "INV-A"}, {"name": "INV-B"}]
    a = _roda("_gerAgrega([%s], %s, '2026-09-01', '2026-09-02')" % (json.dumps(HIST), json.dumps(invs)))
    assert [l["name"] for l in a["linhas"]] == ["Inversor 1.1", "Inversor 1.2", "Inversor 1.3"]


def test_com_kwp_por_inversor_o_esperado_e_proporcional_a_potencia():
    h = json.loads(json.dumps(HIST))
    h["rateio"] = "potencia"
    h["inversores"]["Inversor 1.1"]["pot_kwp"] = 300
    h["inversores"]["Inversor 1.2"]["pot_kwp"] = 200
    h["inversores"]["Inversor 1.3"]["pot_kwp"] = 100
    invs = [{"name": "Inversor 1.1"}, {"name": "Inversor 1.2"}, {"name": "Inversor 1.3"}]
    a = _roda("_gerAgrega([%s], %s, '2026-09-01', '2026-09-02')" % (json.dumps(h), json.dumps(invs)))
    por = {l["name"]: l for l in a["linhas"]}
    assert a["rateio"] == "potencia" and por["Inversor 1.1"]["esp"] == 50.0 and round(por["Inversor 1.3"]["esp"], 6) == round(100 / 6, 6)
    # rendimento específico igual (1 kWh/kWp) nos três → ninguém desvia
    assert all(round(l["dev"], 6) == 0 for l in a["linhas"])


def test_faixas_do_desvio():
    f = _roda("[_gerFaixa(-25).k, _gerFaixa(-12).k, _gerFaixa(-7).k, _gerFaixa(-3).k, _gerFaixa(4).k, _gerFaixa(null).k]")
    assert f == ["critico", "atencao", "observar", "normal", "normal", "sem"]
