# -*- coding: utf-8 -*-
"""A Marialva (Axis) pelo scadaGridco no tempo real da Axis (11/11/2026).

Levi: "Foi incluída Marialva no ScadaGridCo, pode inserir em Axis do tempo real". A SunOp da Axis está sem token desde
julho; a Marialva chega pelo gateway MQTT do supervisório. Ela entra na MESMA aba e no MESMO card da Axis: as rotas
/api/axis/* juntam a fonte `axisscada`, o drill e a curva vão ao scadaGridco, e o rollup a conta como Axis.
"""
import time

import pytest

import app
import scadagridco as sg

TS = time.time() - 120


def _eq(n, vivas=17):
    m = {"active_power": 120.0, "daily_active_energy": 900.0 + n, "temperature_internal": 41.0}
    for i in range(1, 29):
        m[f"string_{i}_current"] = 9.5 if i <= vivas else 0.0
    return {"equipamento": str(n), "indice": n, "tipo": "inverter", "communication_fault": 192,
            "falha_comunicacao": False, "stale": False, "ts": TS, "measurements": m}


@pytest.fixture
def cli(monkeypatch):
    def get(rota, params=None, timeout=None):
        if rota == "/api/mqtt/marialva":
            return {"usina": "marialva", "gateway": {"online": True}, "equipamentos": [_eq(i) for i in range(1, 9)]}
        raise AssertionError(rota)
    monkeypatch.setattr(sg, "get", get)
    monkeypatch.setattr(sg, "EXTRAS", {})
    monkeypatch.setattr(app, "_cob_filtra", lambda fonte, itens, chave, nome: list(itens))
    monkeypatch.setattr(app, "_sg_descobre_se_preciso", lambda agora=None: None)
    monkeypatch.setattr(app, "ESPERADO_INV_DISP", {app._nrm("Marialva"): {f"Inversor 1.{i}": 17 for i in range(1, 9)}},
                        raising=False)
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    monkeypatch.setattr(app, "_macro_sol_baixo", lambda r, agora=None: False)
    monkeypatch.setattr(app, "DASH_PASSWORD", "", raising=False)
    monkeypatch.setitem(app._axs_cache, "payload", None)
    monkeypatch.setitem(app._axs_cache, "ts", 0.0)
    monkeypatch.setitem(app._axis_cache, "payload", {"rows": [], "summary": {"total_usinas": 0}, "cache_ts": "10:00:00"})
    monkeypatch.setitem(app._axis_cache, "ts", time.time())
    app.app.config["TESTING"] = True
    with app.app.test_client() as c:
        yield c


def test_a_marialva_entra_na_aba_da_axis(cli):
    d = cli.get("/api/axis/data").get_json()
    assert [r["usina"] for r in d["rows"]] == ["Marialva"]
    r = d["rows"][0]
    assert r["plant_id"] == "marialva" and r["qtd_inversores"] == 8 and not r["sem_dados"]
    assert r["str_esp"] == 136 and r["strings_ativas"] == 136 and r["diferenca"] == 0
    assert d["summary"]["total_usinas"] == 1


def test_o_drill_da_axis_vai_ao_scadagridco(cli):
    invs = cli.get("/api/axis/plant/marialva").get_json()["inversores"]
    assert len(invs) == 8 and {i.get("nome") or i.get("inv") for i in invs} >= {"Inversor 1.1", "Inversor 1.8"}


def test_o_card_da_axis_conta_a_marialva(cli):
    cli.get("/api/axis/data")
    linhas = [r for r in app._portfolio_rollup() if r.get("usina") == "Marialva"]
    assert linhas and linhas[0].get("fonte") == "Axis"


def test_a_descoberta_classifica_o_cliente_axis():
    assert app._SG_FONTE_DO_CLIENTE["axis"] == "axisscada" and sg.FONTES["axisscada"]["rotulo"] == "Axis"
