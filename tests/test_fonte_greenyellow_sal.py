# -*- coding: utf-8 -*-
"""GreenYellow e Sal Energia pelo scadaGridco, como as outras fontes (06/10/2026, Levi: "separe green yellow e sal
energia"; tempo real "Igual às outras fontes"; histórico "só até 45 dias tá bom").

Tabela de strings, drill por inversor, curva de hoje e de até 45 dias atrás, card na Entrada e o rollup do macro. Os
pacotes têm o formato que a API devolveu em 06/10/2026, cortados; o cadastro é o da aba Equipamentos (14 strings por
inversor nas duas da GreenYellow; a Demerval Lobão tem 20 inversores e só a UG 01, 12, no scadaGridco)."""
import re
import time
from pathlib import Path

import pytest

import app
import scadagridco as sg

RAIZ = Path(app.__file__).resolve().parents[1]
MON = (RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")
ENT = (RAIZ / "docs" / "redesign" / "Entrada.html").read_text(encoding="utf-8")
TS = time.time() - 120


def _eq(n, correntes=None, pot=190.0, fault=192):
    m = {"active_power": pot, "total_daily_energy": 1200.0 + n, "temperature_current": 60.0 + n,
         "serial_number": f"SN{n}"}
    cs = correntes if correntes is not None else [9.0] * 14
    for i in range(1, 29):
        m[f"string_current_{i:02d}"] = cs[i - 1] if i <= len(cs) else 0.0      # Huawei: 28 entradas, 14 ligadas
    return {"equipamento": str(n), "indice": n, "tipo": "inverter", "communication_fault": fault,
            "falha_comunicacao": fault != 192, "stale": False, "ts": TS, "measurements": m}


def _mqtt(n_inv, mexe=None):
    eqs = [_eq(i) for i in range(1, n_inv + 1)]
    for i, kw in (mexe or {}).items():
        eqs[i - 1] = _eq(i, **kw)
    return {"usina": "x", "gateway": {"online": True}, "equipamentos": eqs}


def _modbus_fora(n):
    return {"units": [{"label": f"INV {i:02d}", "slave_id": i, "read_error": "TimeoutError: timed out",
                       "stale": True, "updated_at": 0.0, "measurements": {}} for i in range(1, n + 1)]}


def _cadastro():
    irece = {f"Inversor 1.{i}": 14 for i in range(1, 11)}
    dem = {f"Inversor 1.{i}": 14 for i in range(1, 13)} | {f"Inversor 2.{i}": 14 for i in range(1, 9)}
    sal = {f"Inversor 1.{i}": 22 for i in range(1, 11)}
    cad = {app._nrm("Irece 2"): irece, app._nrm("Demerval Lobao"): dem}
    for u in ("Aquiraz 1 (Salvales)", "Aquiraz 2 (Carosa)", "Quixadá 1 (Hortina)", "Quixadá 2 (Vitesse)"):
        cad[app._nrm(u)] = dict(sal)
    cad[app._nrm("Cascavel (Sunpower)")] = {"Inversor 1.1": 5, "Inversor 1.2": 11, "Inversor 2.1": 9}
    return cad


@pytest.fixture
def api(monkeypatch):
    """A API falsa: a Irecê 2 com o equipamento 4 (= Inversor 1.8) com a string 3 sem corrente; a Sal Energia toda em
    timeout. Conta os pedidos."""
    pedidos = []
    resp = {"/api/mqtt/irece_2": _mqtt(10, {4: {"correntes": [9.0, 9.0, 0.0] + [9.0] * 11}}),
            "/api/mqtt/dermeval_lobao": _mqtt(12)}
    for u, n in (("salvales", 10), ("carosa", 10), ("sunpower", 11), ("hortina", 10), ("vitesse", 10)):
        resp[f"/api/inversores/{u}"] = _modbus_fora(n)

    def get(rota, params=None, timeout=None):
        pedidos.append((rota, dict(params or {})))
        if rota == "/api/telemetria":
            eq = str(params["indice"])
            return {"registros": [{"communication_fault": 192, "data_hora": f"{params['desde']} 10:00:00",
                                   "ts": 1.0, "equipamento": eq,
                                   "pontos": {"string_current_01": 9.0, "string_current_02": 8.5,
                                              "string_current_15": 0.0, "active_power": 190.0}}],
                    "proximo_apos_ts": None}
        return resp[rota]
    monkeypatch.setattr(sg, "get", get)
    monkeypatch.setattr(app, "ESPERADO_INV_DISP", _cadastro(), raising=False)
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    monkeypatch.setattr(app, "_macro_sol_baixo", lambda r, agora=None: False)
    monkeypatch.setattr(app, "DASH_PASSWORD", "", raising=False)
    monkeypatch.setattr(app, "_sg_curvas", sg.CurvasDoDia())
    for c in (app._gy_cache, app._sal_cache):
        monkeypatch.setitem(c, "payload", None)
        monkeypatch.setitem(c, "ts", 0.0)
    app.app.config["TESTING"] = True
    with app.app.test_client() as cli:
        cli.pedidos = pedidos
        yield cli


def _linha(d, usina):
    return next(r for r in d["rows"] if r["usina"] == usina)


def test_tabela_da_greenyellow(api):
    d = api.get("/api/greenyellow/data").get_json()
    assert sorted(r["usina"] for r in d["rows"]) == ["Demerval Lobao", "Irece 2"]
    ir = _linha(d, "Irece 2")
    assert ir["plant_id"] == "irece_2" and ir["qtd_inversores"] == 10 and not ir["sem_dados"]
    # 10 × 14 esperadas; as entradas 15 a 28 do Huawei (sem string ligada) não contam como falta
    assert ir["str_esp"] == 140 and ir["strings_ativas"] == 139 and ir["diferenca"] == -1
    assert ir["ultima_leitura"] and ir["temp_media"] is not None and ir["pot_inv_med"] == pytest.approx(190.0)
    assert "sol_baixo" in ir                                       # passou pelo _servir_tabela_strings


def test_demerval_conta_so_a_ug_que_a_fonte_tem(api):
    """12 de 20 inversores no scadaGridco: esperadas da usina = as dos 12 (168), não as 280 do cadastro inteiro."""
    dm = _linha(api.get("/api/greenyellow/data").get_json(), "Demerval Lobao")
    assert dm["inv_esp"] == 12 and dm["str_esp"] == 168 and dm["diferenca"] == 0


def test_sal_energia_sem_leitura_e_sem_comunicacao(api):
    d = api.get("/api/salenergia/data").get_json()
    assert sorted(r["usina"] for r in d["rows"]) == sorted(u["usina"] for u in sg.FONTES["salenergia"]["usinas"])
    for r in d["rows"]:
        assert r["sem_dados"] and r["falha_comunicacao"] and r["strings_ativas"] is None
    assert d["summary"]["alertas_comm"] == 5


def test_sem_token_a_tabela_diz_e_nao_quebra(api, monkeypatch):
    def recusa(*a, **k):
        raise sg.SemAcesso("scadaGridco sem SCADAGRIDCO_URL/SCADAGRIDCO_TOKEN no tokens.txt")
    monkeypatch.setattr(sg, "get", recusa)
    d = api.get("/api/greenyellow/data?force=1").get_json()
    assert all(r["sem_dados"] for r in d["rows"]) and "token" in (d.get("aviso") or "")


def test_uma_usina_por_vez_e_um_pedido_por_usina(api):
    api.get("/api/greenyellow/data")
    assert [r for r, _p in api.pedidos] == ["/api/mqtt/dermeval_lobao", "/api/mqtt/irece_2"]


def test_drill_nomeia_pelo_de_para_e_mostra_so_as_ligadas(api):
    d = api.get("/api/greenyellow/plant/irece_2").get_json()
    inv = {i["nome"]: i for i in d["inversores"]}
    assert len(inv) == 10 and [i["nome"] for i in d["inversores"]][:3] == ["Inversor 1.1", "Inversor 1.2", "Inversor 1.3"]
    i18 = inv["Inversor 1.8"]                                     # o equipamento 4 do scadaGridco
    assert i18["id"] == "4" and i18["str_esp"] == 14 and i18["strings_ativas"] == 13 and i18["diferenca"] == -1
    assert [s["id"] for s in i18["strings"]] == [str(k) for k in range(1, 15)]
    assert i18["strings"][2]["status"] == "sem_corrente" and i18["eday"] == 1204.0


def test_curva_do_inversor_de_dia_passado(api):
    d = api.get("/api/greenyellow/curva/irece_2?inv=4&data=2026-10-01").get_json()
    assert d["unidade"] == "A" and len(d["inversores"]) == 1
    iv = d["inversores"][0]
    assert iv["nome"] == "Inversor 1.8" and iv["id"] == "4"
    assert iv["curva"]["1"] == {"x": ["10:00"], "y": [9.0]} and "15" not in iv["curva"]
    assert ("/api/telemetria", {"usina": "irece_2", "desde": "2026-10-01", "ate": "2026-10-01", "tipo": "inverter",
                                "indice": 4, "limit": sg.LIMITE}) in api.pedidos


def test_curva_da_usina_inteira_vai_inversor_por_inversor(api):
    d = api.get("/api/greenyellow/curva/irece_2?data=2026-10-01").get_json()
    assert [iv["nome"] for iv in d["inversores"]] == [f"Inversor 1.{i}" for i in range(1, 11)]
    assert sum(1 for r, _p in api.pedidos if r == "/api/telemetria") == 10


def test_curva_alem_dos_45_dias_nao_vai_a_rede(api):
    d = api.get("/api/greenyellow/curva/irece_2?inv=1&data=2026-01-01").get_json()
    assert d["inversores"] == [] and d["motivo"] == "fora_do_historico"
    assert not any(r == "/api/telemetria" for r, _p in api.pedidos)


def test_entrada_e_rollup_tem_as_duas_fontes(api):
    assert ("Greenyellow", "GreenYellow", "greenyellow") in app._ENTRADA_GRUPOS
    assert ("Sal Energia", "Sal Energia", "salenergia") in app._ENTRADA_GRUPOS
    api.get("/api/greenyellow/data")
    api.get("/api/salenergia/data")
    fontes = {u["usina"]: u["fonte"] for u in app._portfolio_rollup()}
    assert fontes.get("Irece 2") == "GreenYellow" and fontes.get("Quixadá 1 (Hortina)") == "Sal Energia"


def test_tela_conhece_as_duas_fontes():
    for fid in ("greenyellow", "salenergia"):
        assert f"'{fid}':'{fid}'" in MON                                        # SKEY
        assert f"{fid}:'/api/{fid}/data'" in MON                                # EP.strings
        assert f"{fid}:'/api/{fid}/plant/'" in MON                              # PLANT
        assert f"id:'{fid}'" in MON                                             # chip da fonte
        assert f'"{fid}"' in ENT                                                # FONTE_ID da Entrada
    assert re.search(r"_CURVA_FONTES=\[[^\]]*'greenyellow'[^\]]*'salenergia'", MON)


def test_ponte_do_nexus_le_as_duas():
    import leitura_nexus
    assert {"greenyellow", "salenergia"} <= set(leitura_nexus.FONTES_API)


def test_aba_de_falhas_recebe_a_curva_do_dia(api, monkeypatch):
    """O worker registra a régua nova sobre a curva de hoje de cada inversor; usina sem leitura não é perguntada."""
    from datetime import datetime
    api.get("/api/greenyellow/data")
    api.get("/api/salenergia/data")
    reg = []
    monkeypatch.setattr(app, "_falhas_registra", lambda fonte, dia, pid, usina, curvas, **k: reg.append(
        (fonte, pid, usina, sorted(curvas), k.get("ids"))))
    monkeypatch.setattr(app, "_falhas_sg_ult", {"final": None})
    n = app._falhas_sg_varre(datetime(2026, 10, 6, 10, 0))
    assert n == 2 and [r[1] for r in reg] == ["dermeval_lobao", "irece_2"] and {r[0] for r in reg} == {"greenyellow"}
    ir = next(r for r in reg if r[1] == "irece_2")
    assert ir[2] == "Irece 2" and len(ir[3]) == 10 and ir[4]["Inversor 1.8"] == "4"
    assert app._falhas_sg_varre(datetime(2026, 10, 6, 5, 0)) == 0            # de madrugada não pergunta


def test_drill_de_noite_nao_pinta_falta(api, monkeypatch):
    """Às 22h o inversor manda pacote com tudo em zero: no drill é "desligado" sem diferença, como na RenoGrid e na
    Athon (a 1ª bancada pintava os 10 da Irecê 2 de vermelho com −14)."""
    noite = _mqtt(10)
    for e in noite["equipamentos"]:
        for k in list(e["measurements"]):
            if k.startswith("string_current_") or k == "active_power":
                e["measurements"][k] = 0.0
    monkeypatch.setattr(sg, "get", lambda rota, params=None, timeout=None: noite)
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: False)
    invs = api.get("/api/greenyellow/plant/irece_2").get_json()["inversores"]
    assert all(i["desligado"] and i["diferenca"] is None and not i["fora_da_conta"] for i in invs)


def test_csv_da_curva(api):
    r = api.get("/api/greenyellow/strings/curva.csv?usina=irece_2&data=2026-10-01")
    linhas = r.get_data(as_text=True).strip().splitlines()
    assert r.status_code == 200 and linhas[0] == "inversor,string,hora,corrente_A"
    assert "Inversor 1.8,1,10:00,9.0" in linhas and len(linhas) == 1 + 10 * 2
