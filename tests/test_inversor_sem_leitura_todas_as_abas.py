# -*- coding: utf-8 -*-
"""Inversor SEM LEITURA HOJE, com a usina gerando, é DESLIGADO em todas as abas — a regra da Colorado 2 (Levi,
25/09/2026: "o inversor 1.3 de Colorado 2 está desligado, a plataforma não conta como desligado"), que a API PV ganhou
de manhã (tests/test_inversor_sem_leitura_desligado.py). Melhoria vale para todas as abas que suportam a mudança.

As outras fontes tinham o mesmo defeito, cada uma do seu jeito, e o drill de duas delas já dizia "desligado" enquanto a
linha da usina cobrava as strings dele como faltando:
- RenoGrid (SolarEdge): Crateus, 25/09 11:34 — as cabines 1 a 4 (40 de 50 inversores) sem potência NENHUMA hoje. A
  SolarEdge devolveu as 286 strings deles SEM valor, espalhadas pelos 8 lotes (não é corte de lote nem throttling, que
  responde 200 vazio), e o render-chart deu 0 kWh no dia para os 40. A linha dizia 75/362, −287, "Falha de string"; o
  drill, "desligado" nos 40.
- Athon/Axis (SunOp): o inversor da metadata sem corrente nenhuma era pulado das ativas e seguia nas esperadas; o drill
  já o marcava desligado (n_real == 0). Leitura de outro dia (o last_values devolve o último valor, de quando for) conta
  como sem leitura hoje, como na API PV, que só enxerga o dia.
- Banco: a tabela guarda a última leitura de 30 dias (de propósito, para a usina muda alarmar). O inversor que parou
  ontem ficava com as correntes velhas e, sem potência (a analógica é de 6 h), as strings contavam como faltando.
- 2C do e-mail: o inversor do cadastro que não vem no e-mail do dia contava todas as esperadas (o drill o lista como
  "não reportou" desde 22/07 — continua listado, agora fora da conta).
Os portões da régua da Athon continuam: sem sol, ninguém; usina inteira sem leitura ou parada, ninguém (é ocorrência da
usina); leitura que não veio por FALHA (lote falho, string ausente da resposta) não é desligado.
"""
from datetime import datetime

import pytest

import app


# ── a régua, pura ─────────────────────────────────────────────────────────────

def test_regua_sem_leitura_com_os_outros_gerando_e_desligado():
    assert app._inv_desligados_por_potencia([50.0, None, 49.0], True, [False, True, False]) == [False, True, False]


def test_regua_sem_a_marca_sem_leitura_de_potencia_segue_nao_sendo_desligado():
    """Potência que não veio, com corrente vindo, não é inversor mudo — a régua de 22/09 continua."""
    assert app._inv_desligados_por_potencia([50.0, None, 49.0], True) == [False, False, False]


def test_regua_usina_inteira_sem_leitura_ninguem_e_desligado():
    assert app._inv_desligados_por_potencia([None, None, None], True, [True, True, True]) == [False, False, False]


def test_regua_sem_sol_ninguem_e_desligado():
    assert app._inv_desligados_por_potencia([50.0, None], False, [False, True]) == [False, False]


# ── RenoGrid (SolarEdge) ──────────────────────────────────────────────────────

@pytest.fixture
def site_se(monkeypatch):
    nome = "UFV Teste SE Sem Leitura"
    devs = [{"deviceType": "INVERTER", "deviceSerial": f"I{i}", "deviceName": f"Inverter {i}"} for i in (1, 2, 3)]
    devs += [{"deviceType": "STRING", "deviceSerial": f"S{i}.{s}", "deviceName": f"String {i}.{s}", "partOfSerial": f"I{i}"}
             for i in (1, 2, 3) for s in (1, 2, 3, 4)]
    estado = {"falhos": 0,       # o 3 veio na resposta, SEM potência hoje (a Crateus)
              "pw": {f"S{i}.{s}": (2500.0 if i != 3 else None) for i in (1, 2, 3) for s in (1, 2, 3, 4)}}
    site = {"id": 777011, "nome": nome, "timezone": "America/Sao_Paulo", "inv": 3}
    monkeypatch.setattr(app, "se_devices", lambda sid: devs)
    monkeypatch.setattr(app, "se_string_power", lambda sid, uuids, tz: (estado["pw"], "2026-09-25T14:30:00Z", estado["falhos"]))
    monkeypatch.setattr(app, "se_sites", lambda: [site])
    monkeypatch.setattr(app, "_se_pr_get", lambda dia, force=False: ([], {}))
    monkeypatch.setitem(app.ESPERADO_INV, nome, {"Inverter 1": 4, "Inverter 2": 4, "Inverter 3": 4})
    monkeypatch.setitem(app.EQUIP_NAMES, nome, {f"Inverter {i}": f"Inversor {i}" for i in (1, 2, 3)})
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    return site, estado


def test_renogrid_inversor_sem_potencia_hoje_sai_da_conta(site_se):
    site, _ = site_se
    r = app.process_site_solaredge(site)
    assert r["inv_desligados"] == 1 and r["strings_fora"] == 4 and r["inv_desligados_nomes"] == ["Inversor 3"]
    assert r["str_esp"] == 8 and r["strings_ativas"] == 8 and r["diferenca"] == 0, "era −4: as esperadas dele faltando"


def test_renogrid_drill_concorda_com_a_linha(site_se):
    site, _ = site_se
    invs = {i["nome"]: i for i in app._se_plant_inversores(site["id"])}
    assert invs["Inversor 3"]["fora_da_conta"] is True and invs["Inversor 3"]["diferenca"] is None
    assert invs["Inversor 3"]["desligado"] is True
    assert invs["Inversor 1"]["fora_da_conta"] is False and invs["Inversor 1"]["diferenca"] == 0


def test_renogrid_string_que_nem_voltou_na_resposta_nao_e_desligado(site_se):
    """Ausente do mapa não é "sem potência": é leitura que não veio (o throttling da SolarEdge responde 200 vazio)."""
    site, estado = site_se
    estado["pw"] = {k: v for k, v in estado["pw"].items() if not k.startswith("S3.")}
    r = app.process_site_solaredge(site)
    assert r["inv_desligados"] == 0 and r["str_esp"] == 12


def test_renogrid_drill_com_lote_falho_segue_sem_comunicacao(site_se):
    site, estado = site_se
    estado["pw"] = {k: v for k, v in estado["pw"].items() if not k.startswith("S3.")}
    estado["falhos"] = 1
    invs = {i["nome"]: i for i in app._se_plant_inversores(site["id"])}
    assert invs["Inversor 3"]["fora_da_conta"] is False and invs["Inversor 3"]["falha_comunicacao"] is True


def test_renogrid_usina_toda_sem_potencia_nao_esconde_nada(site_se):
    site, estado = site_se
    estado["pw"] = {k: None for k in estado["pw"]}
    r = app.process_site_solaredge(site)
    assert r["inv_desligados"] == 0 and r["str_esp"] == 12 and r["strings_ativas"] == 0


def test_renogrid_sem_sol_nada_muda(site_se, monkeypatch):
    site, _ = site_se
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: False)
    r = app.process_site_solaredge(site)
    assert r["inv_desligados"] == 0 and r["str_esp"] == 12


# ── Athon / Axis (SunOp) ──────────────────────────────────────────────────────

@pytest.fixture
def athon(monkeypatch, freeze_now):
    """TST300 com 3 inversores de 4 strings: INV_1 e INV_2 gerando; o INV_3 muda (estado['inv3'])."""
    freeze_now("2026-09-25 11:05:00")
    nome = "TST300"
    meta = {"inv_strings": {f"INV_{i}": [f"{nome}.INV_{i}.MEDIDAS.STR.I_PV{s}" for s in range(1, 5)] for i in (1, 2, 3)},
            "inv_other": {f"INV_{i}": {"P": f"{nome}.INV_{i}.MEDIDAS.P"} for i in (1, 2, 3)},
            "plant_paths": {}}
    estado = {"inv3": {"corrente": None, "p": None, "ts": "2026-09-25T11:00:00"}}

    def _valores():
        v = []
        for i in (1, 2, 3):
            c, p, ts = ((8.0, 52.0, "2026-09-25T11:00:00") if i != 3 else
                        (estado["inv3"]["corrente"], estado["inv3"]["p"], estado["inv3"]["ts"]))
            v += [{"pathname": x, "value": c, "timestamp": ts} for x in meta["inv_strings"][f"INV_{i}"]]
            v.append({"pathname": f"{nome}.INV_{i}.MEDIDAS.P", "value": p, "timestamp": ts})
        return v

    class _R:
        status_code = 200

        def json(self):
            return _valores()
    monkeypatch.setitem(app._si("gridco")["meta"], nome, meta)
    monkeypatch.setitem(app.ESPERADO_INV, nome, {"INV_1": 4, "INV_2": 4, "INV_3": 4})
    monkeypatch.setattr(app, "_sunop_req", lambda *a, **k: _R())
    monkeypatch.setattr(app, "ensure_sunop_meta", lambda *a, **k: None)
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    return nome, estado


def test_athon_inversor_sem_corrente_nenhuma_sai_da_conta(athon):
    nome, _ = athon
    r = app.process_plant_sunop(nome, "gridco")
    assert r["inv_desligados"] == 1 and r["strings_fora"] == 4 and len(r["inv_desligados_nomes"]) == 1
    assert r["str_esp"] == 8 and r["strings_ativas"] == 8 and r["diferenca"] == 0, "era −4"


def test_athon_sem_corrente_com_potencia_zero_e_desligado_pela_potencia(athon):
    """Pulado das ativas, ele também ficava fora da régua de potência — P = 0 com os vizinhos gerando."""
    nome, estado = athon
    estado["inv3"].update(p=0.0)
    r = app.process_plant_sunop(nome, "gridco")
    assert r["inv_desligados"] == 1 and r["str_esp"] == 8 and r["diferenca"] == 0


def test_athon_leitura_de_ontem_e_sem_leitura_hoje(athon):
    """O last_values devolve o último valor, de quando for: 8 A de ontem não são strings ativas hoje."""
    nome, estado = athon
    estado["inv3"].update(corrente=8.0, p=52.0, ts="2026-09-24T15:00:00")
    r = app.process_plant_sunop(nome, "gridco")
    assert r["inv_desligados"] == 1 and r["strings_ativas"] == 8 and r["str_esp"] == 8


def test_athon_drill_concorda_com_a_linha(athon):
    nome, _ = athon
    por = {i["id"]: i for i in app._sunop_plant_build(nome, "gridco")}
    assert por["INV_3"]["fora_da_conta"] is True and por["INV_3"]["desligado"] is True
    assert por["INV_3"]["diferenca"] is None
    assert por["INV_1"]["fora_da_conta"] is False


def test_athon_sem_sol_nada_muda(athon, monkeypatch):
    nome, _ = athon
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: False)
    r = app.process_plant_sunop(nome, "gridco")
    assert r["inv_desligados"] == 0 and r["str_esp"] == 12


# ── Banco (Thopen, _pg_build_snapshot) ────────────────────────────────────────

@pytest.fixture
def banco(monkeypatch, freeze_now):
    freeze_now("2026-09-25 11:05:00")
    sup, pid = "Usina PG Sem Leitura", 900011
    estado = {"ts3": datetime(2026, 9, 24, 17, 50), "c3": 0.0, "p3": None}   # o 3 parou ontem no fim da tarde

    def _recs():
        out = []
        for d in (1, 2, 3):
            c, ts = (8.0, datetime(2026, 9, 25, 11, 0)) if d != 3 else (estado["c3"], estado["ts3"])
            out += [(pid, sup, d, f"INV {d}", s, c, ts) for s in range(1, 5)]
        return out

    class _Cur:
        def execute(self, sql):
            pass

        def fetchall(self):
            return _recs()

    class _Conn:
        def cursor(self):
            return _Cur()

        def close(self):
            pass
    monkeypatch.setattr(app, "_pg_conn", lambda: _Conn())
    monkeypatch.setattr(app, "_pg_analogic_snapshot", lambda force=False: {
        pid: [{"device_id": d, "active_power": p} for d, p in ((1, 52.0), (2, 50.5), (3, estado["p3"])) if p is not None]})
    monkeypatch.setitem(app.ESPERADO_INV, sup, {"INV 1": 4, "INV 2": 4, "INV 3": 4})
    monkeypatch.setitem(app.EQUIP_NAMES, sup, {"INV 1": "Inversor 1.1", "INV 2": "Inversor 1.2", "INV 3": "Inversor 1.3"})
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    return pid, estado


def test_banco_inversor_sem_leitura_hoje_sai_da_conta(banco):
    pid, _ = banco
    summary, detail = app._pg_build_snapshot()
    r = next(x for x in summary if x["plant_id"] == pid)
    assert r["inv_desligados"] == 1 and r["strings_fora"] == 4 and r["inv_desligados_nomes"] == ["Inversor 1.3"]
    assert r["str_esp"] == 8 and r["strings_ativas"] == 8 and r["diferenca"] == 0, "era −4: as correntes de ontem"
    d = {i["nome"]: i for i in detail[pid]}["Inversor 1.3"]
    assert d["fora_da_conta"] is True and d["diferenca"] is None


def test_banco_leitura_de_ontem_gerando_tambem_nao_vale_hoje(banco):
    """Parou ontem ao meio-dia, a 8 A: sem isto, as 4 strings dele seguiam 'ativas' com a leitura de ontem."""
    pid, estado = banco
    estado.update(ts3=datetime(2026, 9, 24, 12, 0), c3=8.0)
    summary, _detail = app._pg_build_snapshot()
    r = next(x for x in summary if x["plant_id"] == pid)
    assert r["inv_desligados"] == 1 and r["strings_ativas"] == 8 and r["str_esp"] == 8


def test_banco_leitura_de_hoje_segue_valendo(banco):
    """Só o dia muda a régua: inversor com leitura de hoje é julgado pela leitura (aqui, gerando normal)."""
    pid, estado = banco
    estado.update(ts3=datetime(2026, 9, 25, 10, 55), c3=8.0, p3=51.0)
    summary, _detail = app._pg_build_snapshot()
    r = next(x for x in summary if x["plant_id"] == pid)
    assert r["inv_desligados"] == 0 and r["strings_ativas"] == 12 and r["str_esp"] == 12


def test_banco_drill_nao_recalcula_a_diferenca_de_quem_esta_fora_da_conta(banco, monkeypatch):
    """A rota do drill reclassifica as strings no ato e recalculava a diferença de TODO inversor — o desligado fora da
    conta voltava com −4 na tela, contra o '—' da linha e das outras abas."""
    pid, estado = banco
    estado.update(ts3=datetime(2026, 9, 25, 11, 0), c3=0.9, p3=0.0)              # desligado pela potência, hoje
    monkeypatch.setattr(app, "_pg_cache", {"summary": None, "detail": {}, "ts": 0.0})
    monkeypatch.setattr(app, "_pg_pr_get", lambda dia, force=False: ([], {}))
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    _s, detail = app._pg_build_snapshot()
    monkeypatch.setattr(app, "_pg_get_snapshot", lambda force=False: (_s, detail))
    invs = {i["nome"]: i for i in app.app.test_client().get(f"/api/pg/plant/{pid}").get_json()["inversores"]}
    assert invs["Inversor 1.3"]["fora_da_conta"] is True and invs["Inversor 1.3"]["diferenca"] is None
    assert all(s["status"] == "desligado" for s in invs["Inversor 1.3"]["strings"])
    assert invs["Inversor 1.1"]["diferenca"] == 0


def test_banco_sem_sol_nada_muda(banco, monkeypatch):
    pid, _ = banco
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: False)
    summary, _detail = app._pg_build_snapshot()
    r = next(x for x in summary if x["plant_id"] == pid)
    assert r["inv_desligados"] == 0 and r["str_esp"] == 12


# ── 2C do e-mail ──────────────────────────────────────────────────────────────

@pytest.fixture
def ufv_2c(monkeypatch):
    u, ts = "TSTSL", datetime(2026, 9, 25, 11, 0)
    data = {u: {inv: {str(s): (ts, 8.0) for s in range(1, 5)} for inv in ("1.1", "1.2")}}      # o 1.3 não veio
    monkeypatch.setattr(app, "_owen_strings_build", lambda force=False: data)
    monkeypatch.setattr(app, "OWEN_UFVS", {u: "Usina 2C Sem Leitura"})
    monkeypatch.setitem(app.ESPERADO_INV, u, {app._owen_inv_tag(u, i): 4 for i in ("1.1", "1.2", "1.3")})
    monkeypatch.setitem(app.EQUIP_NAMES, u, {app._owen_inv_tag(u, i): f"Inversor {i}" for i in ("1.1", "1.2", "1.3")})
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    return u


def test_2c_email_inversor_do_cadastro_que_nao_veio_sai_da_conta(ufv_2c):
    r = next(x for x in app._owen_strings_rows() if x["plant_id"] == ufv_2c)
    assert r["inv_desligados"] == 1 and r["strings_fora"] == 4 and r["inv_desligados_nomes"] == ["Inversor 1.3"]
    assert r["str_esp"] == 8 and r["strings_ativas"] == 8 and r["diferenca"] == 0, "era −4"


def test_2c_email_drill_continua_listando_o_que_nao_reportou_fora_da_conta(ufv_2c):
    """A ausência continua aparecendo (Ipixuna, 22/07), agora como na linha: fora da conta, sem diferença."""
    invs = {i["nome"]: i for i in app.app.test_client().get(f"/api/owen/strings/plant/{ufv_2c}").get_json()["inversores"]}
    assert invs["Inversor 1.3"]["fora_da_conta"] is True and invs["Inversor 1.3"]["diferenca"] is None
    assert invs["Inversor 1.3"]["desligado"] is True


def test_2c_email_nome_que_nao_casa_nao_vira_desligado(ufv_2c, monkeypatch):
    """Cadastro com outra grafia: a conta não fecha (faltariam 3, só 1 não veio) e ninguém é dado por desligado."""
    monkeypatch.setitem(app.ESPERADO_INV, ufv_2c, {f"{ufv_2c}-INV{i}": 4 for i in (1, 2, 3)})
    r = next(x for x in app._owen_strings_rows() if x["plant_id"] == ufv_2c)
    assert r["inv_desligados"] == 0 and r["str_esp"] == 12


def test_2c_email_sem_sol_nada_muda(ufv_2c, monkeypatch):
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: False)
    r = next(x for x in app._owen_strings_rows() if x["plant_id"] == ufv_2c)
    assert r["inv_desligados"] == 0 and r["str_esp"] == 12
