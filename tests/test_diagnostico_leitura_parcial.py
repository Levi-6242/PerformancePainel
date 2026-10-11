# -*- coding: utf-8 -*-
"""Diagnóstico de usina: a leitura que veio PELA METADE também não vira zero (revisão de 11/10/2026).

Continuação de tests/test_diagnostico_fonte_fora.py (mesmos dublês e o mesmo harness da página no node). A revisão
adversarial do conserto de 10/10/2026 achou os caminhos em que uma parte da leitura falhava e a tela seguia afirmando:
1. a fonte dos inversores fora: as OS POR INVERSOR nem eram pedidas (o POST ia com a lista vazia), e o cartão
   "Fracttal · OS abertas" dizia 0 — exatamente o print da prova da porta única;
2. o PR do dia do PG/SolarEdge fora com o snapshot dos inversores ainda servido: todo eday None, "30 sem produção" e
   "Hoje 0 kWh" às 10:00;
3. a SunOp sem ler (pausa de domingo, teto, borda, sem credencial): /api/sunop/plant 200 com a lista vazia;
4. o de-para do Fracttal (índice de code-base, mapa "Usina Fractall") que parou num 429 virava "usina fora do Fracttal";
5. o PR do mês por inversor (BD_Performance travado) sumia, e a lista dizia "Sem anomalias — usina dentro do esperado";
6. o PDF de strings quebrava (500) com uma usina da API PV em erro;
7. o PR do dia que não respondeu deixava "0 abaixo dos pares" em verde;
8. o motor de diagnóstico com os trackers fora dizia "sem tracker travado associado".
Cada um com o zero DE VERDADE ao lado. Nenhum teste fala com fonte de verdade (a trava do conftest.py recusa SunOp e PV).
"""
import io
import json
import time

import pytest
import requests

import app
from test_diagnostico_fonte_fora import (PID, _504, _SELO, _Resp, _Sessao, _casc, _frac_get_dublado, _inv, _pagina,
                                         _rede, _rotas, _sem, cli)  # noqa: F401 — cli é fixture


# ── 1. OS por inversor com a fonte dos inversores fora ──────────────────────────────────────────────────────────────
# O Fracttal responde só pelo que foi pedido: 1 corretiva aberta em cada inversor da lista do POST.
_FRAC_POR_PEDIDO = r"""
R["/api/fracttal/os"] = (b) => [200, {ok: true, usina_os: [], total: (b.inversores || []).length,
  por_inversor: Object.fromEntries((b.inversores || []).map((n, i) => [n, {os: [{folio: 15000 + i, tipo: "Corretiva",
    aberta: true, criada: "2026-10-09", ativo: n, descricao: "[" + n + "] - Parado"}]}]))}];
"""


def test_tela_os_por_inversor_com_a_planta_fora_nao_vira_os_abertas_zero(tmp_path):
    rot = "v2Render(); out({ c: cartoes(), os: ELS.osList.innerHTML, corpos });"
    ok = _pagina(_rotas(), rot, tmp_path, antes=_FRAC_POR_PEDIDO)
    assert ok["c"]["Fracttal · OS abertas"]["v"] == "2", ok["c"]["Fracttal · OS abertas"]
    assert [b["inversores"] for k, b in ok["corpos"] if k == "/api/fracttal/os"] == [["Inversor 1", "Inversor 2"]]
    fora = _pagina(_rotas(plant=_504, diag=_504), rot, tmp_path, antes=_FRAC_POR_PEDIDO)
    fr = fora["c"]["Fracttal · OS abertas"]
    assert _sem(fr["v"]), fr
    assert "OS por inversor sem leitura" in fr["s"] and "Fonte API PV não respondeu (HTTP 504)" in fr["s"], fr["s"]
    assert "Nenhuma OS" not in fora["os"] and "OS por inversor sem leitura" in fora["os"], fora["os"]


def test_tela_planta_irma_fora_tira_as_os_da_conta_e_a_irma_que_veio_entra_nas_os(tmp_path):
    """Nova Londrina (duas plantas). A irmã que não respondeu: o cartão de OS fica "—" como os de inversores. A irmã que
    respondeu: as OS dos inversores dela também são pedidas (antes só os da planta clicada iam no POST)."""
    grupo = [200, {"membros": [{"id": PID, "nome": "Usina Teste 1"}, {"id": 4243, "nome": "Usina Teste 2"}]}]
    rot = "v2Render(); out({ c: cartoes(), os: ELS.osList.innerHTML, corpos });"
    caiu = _pagina(_rotas(grupo=grupo, irma=_504), rot, tmp_path, antes=_FRAC_POR_PEDIDO)
    fr = caiu["c"]["Fracttal · OS abertas"]
    assert _sem(fr["v"]) and "Usina Teste 2" in fr["s"], fr
    assert "OS por inversor sem leitura" in caiu["os"]
    veio = _pagina(_rotas(grupo=grupo, irma=[200, {"plant_id": 4243, "inversores": [_inv(3)]}]), rot, tmp_path,
                   antes=_FRAC_POR_PEDIDO)
    pedidos = [b["inversores"] for k, b in veio["corpos"] if k == "/api/fracttal/os"]
    assert pedidos[-1] == ["Inversor 1", "Inversor 2", "Inversor 3"], pedidos
    assert veio["c"]["Fracttal · OS abertas"]["v"] == "3", veio["c"]["Fracttal · OS abertas"]


# ── 2. energia do dia (PR do dia) do PG / SolarEdge fora ───────────────────────────────────────────────────────────
def _pg_inv(n):
    return {"id": n, "nome": f"Inversor {n}", "nome_api": f"INV{n}", "produzindo": True, "str_esp": 2,
            "strings": [{"id": "ST1", "corrente": 8.0}, {"id": "ST2", "corrente": 8.1}]}


def test_plant_do_pg_com_o_pr_do_dia_fora_marca_a_energia_sem_leitura(cli, monkeypatch):
    monkeypatch.setattr(app, "_pg_get_snapshot", lambda force=False: ([{"plant_id": 20}], {20: [_pg_inv(1), _pg_inv(2)]}))

    def _pr_fora(dia, force=False):
        raise RuntimeError("PG fora do ar (simulado)")
    monkeypatch.setattr(app, "_pg_pr_get", _pr_fora)
    monkeypatch.setitem(app._pg_cache, "ts", time.time() - 95 * 60)
    r = cli.get("/api/pg/plant/20")
    assert r.status_code == 200, "os inversores vieram (o snapshot): só a energia do dia não"
    j = r.get_json()
    assert j["eday_ok"] is False and "PG fora do ar" in j["eday_erro"], j
    assert len(j["inversores"]) == 2 and all(i.get("eday") is None for i in j["inversores"])
    assert j["snapshot_velho"] is True and j["snapshot_idade_s"] >= 95 * 60 and j["cache_ts"]
    # zero de verdade: o PR do dia respondeu, e a geração é 0 (de madrugada)
    monkeypatch.setattr(app, "_pg_pr_get", lambda dia, force=False: (
        [], {20: [{"id": 1, "geracao_kwh": 0.0}, {"id": 2, "geracao_kwh": 0.0}]}))
    monkeypatch.setitem(app._pg_cache, "ts", time.time())
    j = cli.get("/api/pg/plant/20").get_json()
    assert "eday_ok" not in j and [i["eday"] for i in j["inversores"]] == [0.0, 0.0] and j["snapshot_velho"] is False


def test_plant_da_solaredge_com_o_pr_do_dia_fora_marca_a_energia_sem_leitura(cli, monkeypatch):
    monkeypatch.setattr(app, "se_sites", lambda: [])
    monkeypatch.setattr(app, "_se_eday_falha", {}, raising=False)
    monkeypatch.setattr(app, "se_devices", lambda sid: [
        {"deviceType": "INVERTER", "deviceSerial": "INV1", "deviceName": "Inversor 1"},
        {"deviceType": "STRING", "deviceSerial": "S1", "deviceName": "String 1.1", "partOfSerial": "INV1",
         "pluggedTo": "INV1"}])
    monkeypatch.setattr(app, "se_string_power", lambda sid, uuids, tz: ({"S1": 900.0}, None, 0))

    def _pr_fora(dia, force=False):
        raise RuntimeError("render-chart da SolarEdge: 503 (simulado)")
    monkeypatch.setattr(app, "_se_pr_get", _pr_fora)
    r = cli.get("/api/solaredge/plant/777")
    assert r.status_code == 200
    j = r.get_json()
    assert j["inversores"] and j["eday_ok"] is False and "render-chart" in j["eday_erro"], j
    monkeypatch.setattr(app, "_se_pr_get", lambda dia, force=False: ([], {777: []}))
    j = cli.get("/api/solaredge/plant/777").get_json()
    assert j["inversores"] and "eday_ok" not in j, "o PR respondeu (sem geração do inversor): não é falha"


_DEZ_DA_MANHA = r"""
{ const _D = Date, _T = new _D(2026, 9, 10, 10, 0, 0).getTime();
  globalThis.Date = class extends _D { constructor(...a) { if (a.length) super(...a); else super(_T); }
    static now() { return _T; } }; }
"""


def _rotas_pg(plant):
    return {"/api/state": [200, {"comments_thread": {}, "comments": {}}], "/api/os-performance": [200, {"os": []}],
            f"/api/pg/plant/{PID}": plant,
            f"/api/pg/trackers/{PID}": [200, {"total": 0, "parados": 0, "trackers": [], "tem_trackers": False}],
            f"/api/diagnostico/{PID}": [200, {"diagnosticos": []}],
            "/api/fracttal/os": [200, {"ok": True, "usina_os": [], "por_inversor": {}, "total": 0}],
            "/api/cascata": [200, {"ok": False, "motivo": "sem dado (teste)"}],
            "/api/inv/pr-mes": [200, {"inversores": {}, "pr_meta": None}],
            f"/api/pg/pr/{PID}": [200, {"inversores": [{"nome": "Inversor 1", "pr": 0.8}, {"nome": "Inversor 2",
                                                                                          "pr": 0.8}]}]}


def test_tela_pg_com_a_energia_do_dia_fora_nao_vira_usina_parada_as_10h(tmp_path):
    invs = [dict(_inv(1), eday=None), dict(_inv(2), eday=None)]
    rot = "v2Render(); out({ c: cartoes(), inv: ELS.v2InvBody.innerHTML, nota: ELS.v2InvNota.innerHTML, avisos });"
    busca = "?fonte=pg&nome=Usina%20Teste"
    r = _pagina(_rotas_pg([200, {"plant_id": PID, "inversores": invs, "eday_ok": False,
                                 "eday_erro": "PR do dia (PG): OperationalError"}]), rot, tmp_path, search=busca,
                antes=_DEZ_DA_MANHA)
    c = r["c"]
    assert c["Inversores"]["v"].startswith("2 <small>· 0 sem produção"), c["Inversores"]
    assert _sem(c["Hoje"]["v"]) and "Energia do dia (Thopen/PG) não respondeu" in c["Hoje"]["s"], c["Hoje"]
    assert "sem produção" not in r["inv"].split("<tbody>")[1], "a linha do inversor virou 'sem produção' sem a energia"
    assert "o kWh de hoje fica —" in r["nota"]
    assert [a for a in r["avisos"] if a[0] == "falhou" and "Energia do dia" in a[1]], r["avisos"]
    # contraprova às 10h: a energia FOI lida e é nula → aí sim "sem produção" (a régua de sempre)
    r = _pagina(_rotas_pg([200, {"plant_id": PID, "inversores": invs}]), rot, tmp_path, search=busca,
                antes=_DEZ_DA_MANHA)
    assert r["c"]["Inversores"]["v"].startswith("2 <small>· 2 sem produção"), r["c"]["Inversores"]
    assert r["c"]["Hoje"]["v"].startswith("0 <small>kWh")


def test_tela_snapshot_velho_e_drill_retido_mostram_a_hora_da_leitura(tmp_path):
    busca = "?fonte=pg&nome=Usina%20Teste"
    r = _pagina(_rotas_pg([200, {"plant_id": PID, "inversores": [_inv(1), _inv(2)], "cache_ts": "08:25:00",
                                 "snapshot_idade_s": 95 * 60, "snapshot_velho": True}]),
                "v2Render(); out({ c: cartoes(), upd: ELS.upd.textContent });", tmp_path, search=busca)
    s = r["c"]["Inversores"]["s"]
    assert "não atualizou (snapshot de 95 min)" in s and "números da leitura das 08:25" in s, s
    assert r["c"]["Inversores"]["v"].startswith("2 <small>"), "os números ficam (é a última leitura boa)"
    assert "08:25" in r["upd"]


# ── 3. SunOp sem ler: /api/sunop/plant e /api/sunop/trackers/<usina> ─────────────────────────────────────────────────
def _sunop_dublada(monkeypatch, meta, sem_rede=None):
    chamadas = []

    def _req(*a, **k):
        chamadas.append(a)
        return None                         # o disjuntor/pausa/rede: nada sai
    monkeypatch.setattr(app, "_sunop_req", _req)
    monkeypatch.setattr(app, "ensure_sunop_meta", lambda inst="gridco": None)
    monkeypatch.setattr(app, "_load_sunop_plant_meta", lambda p, inst="gridco": {})
    monkeypatch.setattr(app, "_sunop_sem_rede", lambda inst="gridco": sem_rede)
    monkeypatch.setattr(app, "_sunop_meta", meta)
    monkeypatch.setattr(app, "_so_plant_cache", {})
    monkeypatch.setattr(app, "_so_plant_falha", {}, raising=False)
    return chamadas


def test_sunop_sem_metadata_da_usina_e_502_e_nao_usina_sem_inversor(cli, monkeypatch):
    _sunop_dublada(monkeypatch, {}, sem_rede="domingo")
    r = cli.get("/api/sunop/plant/TST100")
    assert r.status_code == 502, (r.status_code, r.get_json())
    j = r.get_json()
    assert j["fonte"] == "SunOp" and j["fonte_ok"] is False and j["inversores"] == []
    assert "metadados da usina não vieram" in j["erro"] and "domingo" in j["erro"], j["erro"]
    # pedido logo depois (o vazio ficou 30 s no cache): segue 502, não vira 200 vazio
    assert cli.get("/api/sunop/plant/TST100").status_code == 502


def test_sunop_lote_sem_resposta_e_502_e_o_drill_retido_diz_a_hora_dele(cli, monkeypatch):
    meta = {"TST100": {"inv_strings": {"INV_1": ["TST100.INV_1.I_PV1"]}, "inv_other": {}, "trackers": {}}}
    chamadas = _sunop_dublada(monkeypatch, meta)
    r = cli.get("/api/sunop/plant/TST100")
    assert r.status_code == 502 and "lote(s) do last_values sem resposta" in r.get_json()["erro"], r.get_json()
    assert chamadas, "o last_values foi pedido (ao dublê)"
    # com um drill bom guardado: a rota serve o retido, com a hora da leitura e o porquê de não ter atualizado
    lido = time.time() - 3600
    bom = [{"id": "INV_1", "nome": "Inversor 1", "strings": [], "eday": 10.0}]
    app._so_plant_cache[("gridco", "TST100")] = {"ts": lido, "inversores": bom, "lido": lido}
    r = cli.get("/api/sunop/plant/TST100?force=1")
    assert r.status_code == 200
    j = r.get_json()
    assert j["inversores"] == bom and j["retido"] is True and "last_values" in j["erro_releitura"]
    assert j["cache_ts"] == time.strftime("%H:%M:%S", time.localtime(lido)), "a hora é a da leitura, não a de agora"


def test_sunop_respondeu_e_a_usina_nao_tem_inversor_e_200_vazio(cli, monkeypatch):
    _sunop_dublada(monkeypatch, {"TST100": {"inv_strings": {}, "inv_other": {}, "trackers": {}}})
    r = cli.get("/api/sunop/plant/TST100")
    assert r.status_code == 200 and r.get_json()["inversores"] == [] and "erro" not in r.get_json()


def test_trackers_da_sunop_sem_metadata_e_503_e_com_metadata_sem_tracker_e_200(cli, monkeypatch):
    _sunop_dublada(monkeypatch, {}, sem_rede="teto")
    r = cli.get("/api/sunop/trackers/TST100")
    assert r.status_code == 503, (r.status_code, r.get_json())
    j = r.get_json()
    assert j["fonte_ok"] is False and j["fonte"] == "SunOp" and "teto" in j["erro"] and j["trackers"] == []
    # zero de verdade: a usina está no metadata e não tem tracker
    monkeypatch.setattr(app, "_sunop_meta", {"TST100": {"inv_strings": {}, "inv_other": {}, "trackers": {}}})
    r = cli.get("/api/sunop/trackers/TST100")
    assert r.status_code == 200 and r.get_json()["tem_trackers"] is False and r.get_json()["total"] == 0


def test_tela_athon_com_a_sunop_sem_ler_mostra_sem_leitura(tmp_path):
    so = {"/api/state": [200, {"comments_thread": {}, "comments": {}}], "/api/os-performance": [200, {"os": []}],
          f"/api/sunop/plant/{PID}": [502, {"erro": "metadados da usina não vieram: SunOp pausada (domingo)",
                                            "fonte": "SunOp", "fonte_ok": False, "inversores": []}],
          f"/api/sunop/trackers/{PID}": [503, {"erro": "metadados da usina não vieram", "fonte": "SunOp",
                                               "fonte_ok": False, "trackers": [], "total": 0}],
          "/api/fracttal/os": [200, {"ok": True, "usina_os": [], "por_inversor": {}, "total": 0}],
          "/api/cascata": [200, {"ok": False, "motivo": "sem dado (teste)"}],
          "/api/inv/pr-mes": [200, {"inversores": {}, "pr_meta": None}]}
    r = _pagina(so, "v2Render(); const c = cartoes(); v2Tab('trk'); out({ c, inv: ELS.v2InvBody.innerHTML, "
                    "trk: ELS.v2TrkBody.innerHTML });", tmp_path, search="?fonte=athon&nome=Usina%20Teste")
    for rot in ("Inversores", "Strings", "Hoje", "Trackers"):
        assert _sem(r["c"][rot]["v"]) and "Athon não respondeu (HTTP 50" in r["c"][rot]["s"], (rot, r["c"][rot])
    assert "A fonte não devolveu inversores" not in r["inv"] and "não tem trackers cadastrados" not in r["trk"]


# ── 4. o de-para do Fracttal sem leitura não é "usina fora do Fracttal" ──────────────────────────────────────────────
def _indice_dublado(monkeypatch, tmp_path, estado):
    monkeypatch.setattr(app, "FRACTTAL_ON", True)
    monkeypatch.setattr(app, "_frac_fractall_map", lambda: {"usina teste": "UFV Teste Fractall"})
    monkeypatch.setattr(app, "_frac_cb_index", {})
    monkeypatch.setattr(app, "_frac_cb_ts", 0.0)
    monkeypatch.setattr(app, "_frac_cb_falha", None, raising=False)
    monkeypatch.setattr(app, "_FRAC_INDEX_FILE", str(tmp_path / "fracttal_index.json"))
    monkeypatch.setattr(app, "_frac_wos_cache", {})
    monkeypatch.setattr(app, "_frac_code_cache", {})

    def _get(ep, *, _motivo=None, **p):
        mot = _motivo if _motivo is not None else {}
        estado["pedidos"].append((ep, p.get("start")))
        if ep == "items/":
            if p.get("start", 0) == 0:
                return {"data": [{"id": 1, "code": "UFV-OUT100", "groups_1_description": "UFV Outra"}],
                        "total": estado["total"]}
            if estado["fora"]:
                mot.update(status=429, erro="cota da empresa", reset="20")
                return None
            return {"data": [{"id": 2, "code": "UFV-TST100", "groups_1_description": "UFV Teste Fractall"}],
                    "total": estado["total"]}
        if ep.startswith("work_orders/"):
            return {"data": []}
        if ep.startswith("items/"):
            return {"data": []}
        return None
    monkeypatch.setattr(app, "_frac_get", _get)


def test_indice_do_fracttal_que_parou_num_429_nao_e_usina_fora_do_fracttal(cli, monkeypatch, tmp_path):
    est = {"fora": True, "total": 2, "pedidos": []}
    _indice_dublado(monkeypatch, tmp_path, est)
    idx = app._frac_codebase_index()
    assert idx == {} and app._frac_cb_falha and "429" in app._frac_cb_falha[1]
    assert not (tmp_path / "fracttal_index.json").exists(), "o índice parcial (só a página 1) foi gravado por 12 h"
    assert "índice de ativos sem leitura" in app._frac_depara_falha("Usina Teste")
    corpo = {"usina": "Usina Teste", "mes": "2026-10", "inversores": ["Inversor 1.1"]}
    r = cli.post("/api/fracttal/os", json=corpo)
    assert r.status_code == 502 and "índice de ativos sem leitura" in r.get_json()["erro"], r.get_json()
    n = len(est["pedidos"])
    cli.post("/api/fracttal/os", json=corpo)
    assert len(est["pedidos"]) == n, "logo depois da falha o índice não é varrido de novo (a cota é da empresa)"
    # o Fracttal voltou: a usina entra no índice, que é gravado, e sem OS no mês a rota responde 200 com 0 (zero de verdade)
    est["fora"] = False
    monkeypatch.setattr(app, "FRAC_CB_FALHA_S", 0)
    idx = app._frac_codebase_index()
    assert "ufv teste fractall" in idx and app._frac_cb_falha is None and (tmp_path / "fracttal_index.json").exists()
    assert app._frac_depara_falha("Usina Teste") is None
    r = cli.post("/api/fracttal/os", json=corpo)
    assert r.status_code == 200 and r.get_json()["total"] == 0


def test_indice_do_fracttal_que_falha_mantem_o_anterior(monkeypatch, tmp_path):
    est = {"fora": True, "total": 2, "pedidos": []}
    _indice_dublado(monkeypatch, tmp_path, est)
    anterior = {"ufv teste fractall": {"cb": "TST100", "site": 2}}
    monkeypatch.setattr(app, "_frac_cb_index", anterior)
    monkeypatch.setattr(app, "_frac_cb_ts", time.time() - app.FRAC_CODE_TTL - 1)   # venceu: vai varrer
    assert app._frac_codebase_index() is anterior and app._frac_cb_falha
    assert app._frac_depara_falha("Usina Teste") is None, "a usina está no índice anterior: não é falta de leitura"


def test_cascata_com_o_indice_do_fracttal_sem_leitura_marca_sem_leitura(cli, monkeypatch, tmp_path):
    from test_diagnostico_fonte_fora import _cascata_dublada
    _cascata_dublada(monkeypatch)
    est = {"fora": True, "total": 2, "pedidos": []}
    _indice_dublado(monkeypatch, tmp_path, est)
    monkeypatch.setattr(app, "_frac_usina_ent", _FRAC_USINA_ENT)    # o _cascata_dublada dubla este; aqui vale o de verdade
    j = cli.get("/api/cascata?usina=Usina Teste&ano=2026&mes=10").get_json()
    assert j["fracttal_ok"] is False and "índice de ativos sem leitura" in j["fracttal_erro"], j


_FRAC_USINA_ENT = app._frac_usina_ent


def test_mapa_usina_fractall_com_o_bd_travado_nao_e_usina_sem_os(cli, monkeypatch):
    monkeypatch.setattr(app, "FRACTTAL_ON", True)
    monkeypatch.setattr(app, "_frac_bd_map", {})
    monkeypatch.setattr(app, "_frac_bd_ts", 0.0)
    monkeypatch.setattr(app, "_frac_bd_falha", None, raising=False)

    def _travado():
        raise PermissionError("BD_Performance.xlsx em uso pelo OneDrive (simulado)")
    monkeypatch.setattr(app, "_bd_readable", _travado)
    monkeypatch.setattr(app, "_os_atribuidas_de", lambda u: [])
    r = cli.get("/api/os-performance?usina=Usina Teste")
    assert r.status_code == 502 and "BD_Performance" in r.get_json()["erro"], (r.status_code, r.get_json())
    r = cli.post("/api/fracttal/os", json={"usina": "Usina Teste", "mes": "2026-10", "inversores": ["Inversor 1"]})
    assert r.status_code == 502 and "Equipamentos" in r.get_json()["erro"], r.get_json()
    # o BD lido e a usina sem "Usina Fractall": fora do Fracttal de verdade, 200
    monkeypatch.setattr(app, "_frac_fractall_map", lambda: {"outra usina": "UFV Outra"})
    assert cli.get("/api/os-performance?usina=Usina Teste").status_code == 200
    r = cli.post("/api/fracttal/os", json={"usina": "Usina Teste", "mes": "2026-10", "inversores": ["Inversor 1"]})
    assert r.status_code == 200 and r.get_json()["total"] == 0


# ── 5. PR do mês por inversor (BD_Performance) ────────────────────────────────────────────────────────────────────
def test_pr_do_mes_com_o_bd_performance_travado_e_503_e_nao_fica_no_cache(cli, monkeypatch, tmp_path):
    monkeypatch.setattr(app, "_bdperf_pr_cache", {})

    def _travado():
        raise PermissionError("BD_Performance.xlsx em uso pelo OneDrive (simulado)")
    monkeypatch.setattr(app, "_bd_readable", _travado)
    r = cli.get("/api/inv/pr-mes?usina=Usina Teste")
    assert r.status_code == 503, (r.status_code, r.get_json())
    j = r.get_json()
    assert j["fonte"] == "BD_Performance" and j["fonte_ok"] is False and "PermissionError" in j["erro"]
    assert j["inversores"] == {} and not app._bdperf_pr_cache, "a falha ficou 30 min no cache"
    # zero de verdade: o BD abriu e a usina não tem aba de PR por inversor
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.title = "Outra Usina"
    arq = tmp_path / "bd.xlsx"
    wb.save(arq)
    monkeypatch.setattr(app, "_bd_readable", lambda: str(arq))
    r = cli.get("/api/inv/pr-mes?usina=Usina Teste")
    assert r.status_code == 200 and r.get_json()["inversores"] == {} and "erro" not in r.get_json()


def test_tela_pr_do_mes_fora_nao_diz_sem_anomalias(tmp_path):
    fora = [503, {"inversores": {}, "erro": "BD_Performance: PermissionError", "fonte": "BD_Performance",
                  "fonte_ok": False}]
    r = _pagina(dict(_rotas(), **{"/api/inv/pr-mes": fora}),
                "v2Render(); out({ diags: ELS.diags.innerHTML, sub: ELS.hmSub.innerHTML, avisos });", tmp_path)
    assert "Sem anomalias" not in r["diags"] and "PR do mês por inversor (BD_Performance) não respondeu (HTTP 503)" \
        in r["diags"], r["diags"]
    assert "não respondeu (HTTP 503)" in r["sub"], r["sub"]
    assert [a for a in r["avisos"] if a[0] == "falhou" and "BD_Performance" in a[1]]
    ok = _pagina(_rotas(), "v2Render(); out({ diags: ELS.diags.innerHTML });", tmp_path)
    assert "Sem anomalias" in ok["diags"], "o zero de verdade (o PR veio, nada abaixo) continua 'sem anomalias'"


def test_tela_pr_do_mes_com_o_drill_fora_ainda_e_pedido(tmp_path):
    """Thopen/PG com o /api/pg/plant em 503 e o motor analógico respondendo: o mapa de strings saía cedo e o PR do mês
    (que vem do BD_Performance, não da fonte ao vivo) nunca era pedido."""
    rotas = _rotas_pg([503, {"erro": "snapshot do PG ainda não montado", "fonte": "PG", "fonte_ok": False,
                             "inversores": []}])
    rotas["/api/inv/pr-mes"] = [200, {"inversores": {"Inversor 1": {"pr": 60.0, "gen_mwh": 10.0},
                                                     "Inversor 2": {"pr": 80.0, "gen_mwh": 12.0}},
                                      "pr_meta": 78.0, "pr_usina": 70.0}]
    r = _pagina(rotas, "v2Render(); out({ pedidos, diags: ELS.diags.innerHTML });", tmp_path,
                search="?fonte=pg&nome=Usina%20Teste")
    assert "/api/inv/pr-mes" in r["pedidos"]
    assert "Inversor 1" in r["diags"] and "Sem anomalias" not in r["diags"], r["diags"]


def test_tela_trocar_o_mes_do_pr_que_falha_nao_deixa_o_mes_anterior(tmp_path):
    bom = [200, {"inversores": {"Inversor 1": {"pr": 60.0, "gen_mwh": 10.0}}, "pr_meta": 78.0}]
    r = _pagina(dict(_rotas(), **{"/api/inv/pr-mes": bom}), """
      const antes = JSON.stringify(INVPR);
      R["/api/inv/pr-mes"] = [500, {"error": "boom"}];
      await loadInvPR("2026-09"); await assenta();
      out({ antes, depois: INVPR, diags: ELS.diags.innerHTML });""", tmp_path)
    assert "Inversor 1" in r["antes"] and r["depois"] is None, r
    assert "não respondeu (HTTP 500)" in r["diags"]


# ── 6. PDF de strings com uma usina da API PV em erro ────────────────────────────────────────────────────────────────
def test_pdf_de_strings_com_uma_usina_em_erro_nao_quebra_e_cita_a_usina(cli, monkeypatch):
    pytest.importorskip("matplotlib")
    hoje = time.strftime("%d/%m/%Y")
    monkeypatch.setattr(app, "get_plants", lambda token, force=False: [{"id": 111, "nome": "Usina Fora"},
                                                                       {"id": 222, "nome": "Usina Boa"}])
    curva = {"Ipv1": {"x": ["10:00", "11:00"], "y": [8.0, 8.2]}, "Ipv2": {"x": ["10:00", "11:00"], "y": [8.1, 8.0]}}
    boa = {"inversores": [{"nome": "Inversor 1", "abaixo": 0, "nota": None, "curva": curva,
                           "strings": [{"nome": "Ipv1", "sub": False}, {"nome": "Ipv2", "sub": False}]}],
           "total_abaixo": 0}
    monkeypatch.setattr(app, "_spv_cache", {(222, hoje): {"ts": time.time(), "payload": boa}})
    _rede(monkeypatch, [("/day_inverter", _Resp(429, {"error": "Too many requests"}))])
    r = cli.get(f"/api/spv/pdf?data={hoje}&usinas=111,222")
    assert r.status_code == 200 and r.mimetype == "application/pdf", (r.status_code, r.data[:300])
    # só a usina em erro: não há o que exportar, e a resposta diz por quê (não é 500 nem "Todas as strings OK")
    r = cli.get(f"/api/spv/pdf?data={hoje}&usinas=111")
    assert r.status_code == 502, (r.status_code, r.get_json())
    j = r.get_json()
    assert j["fonte_ok"] is False and j["sem_leitura"][0]["usina"] and "429" in j["sem_leitura"][0]["motivo"]


# ── 7. PR do dia que não respondeu ──────────────────────────────────────────────────────────────────────────────────
def _pv_pr_rede(monkeypatch, inversor, meteo):
    recs = [{"idefinversor": 1, "tsleitura_new": "2026-10-10 12:00:00",
             "conteudojson": json.dumps({"Eday": 120.0, "Ipv1": 8.0, "Ipv2": 8.1})}]
    _rede(monkeypatch, [("/day_inverter", inversor if inversor is not None else _Resp(200, recs)),
                        ("/plant_devices", _Resp(200, [{"device_id": 1, "device_name": "INV 1"}])),
                        ("/day_meteo", meteo)])
    monkeypatch.setitem(app._pv_pr_cache, "detail", {})


def test_pr_do_dia_da_api_pv_sem_irradiancia_e_502_e_nao_pr_vazio(cli, monkeypatch):
    _pv_pr_rede(monkeypatch, None, _Resp(500, {"error": "day_meteo indisponível"}))
    r = cli.get(f"/api/pv/pr/{PID}")
    assert r.status_code == 502, (r.status_code, r.get_json())
    j = r.get_json()
    assert j["fonte_ok"] is False and "day_meteo" in j["erro"] and j["inversores"], "a energia dos inversores segue no corpo"
    _pv_pr_rede(monkeypatch, _Resp(429, {"error": "Too many requests"}), _Resp(200, []))
    r = cli.get(f"/api/pv/pr/{PID}")
    assert r.status_code == 502 and "day_inverter" in r.get_json()["erro"], (r.status_code, r.get_json())
    # zero de verdade: a irradiância do dia respondeu vazia (de madrugada): PR nulo, 200
    _pv_pr_rede(monkeypatch, None, _Resp(200, []))
    r = cli.get(f"/api/pv/pr/{PID}")
    assert r.status_code == 200 and r.get_json().get("fonte_ok") is not False and r.get_json()["pr"] is None


def test_tela_pr_do_dia_fora_nao_vira_zero_abaixo_dos_pares_em_verde(tmp_path):
    r = _pagina(_rotas(pr=[502, {"erro": "API PV (day_meteo): HTTP 500", "fonte": "API PV", "fonte_ok": False,
                                 "inversores": []}]),
                "v2Render(); out({ below: ELS.below.innerHTML, c: cartoes(), inv: ELS.v2InvBody.innerHTML });",
                tmp_path)
    c = r["c"]["Inversores"]
    assert "0 abaixo dos pares" not in c["s"] and "PR do dia (API PV) não respondeu (HTTP 502)" in c["s"], c
    assert '<div class="bc "><div class="l">Inversores' not in r["below"], "o cartão segue pintado de ok sem o PR"
    assert "PR sem leitura" in r["inv"] and 'v2chip ok"' not in r["inv"], "a linha virou 'ok' só porque o PR faltou"
    ok = _pagina(_rotas(), "v2Render(); out({ c: cartoes() });", tmp_path)
    assert "0 abaixo dos pares" in ok["c"]["Inversores"]["s"], "o zero de verdade (o PR veio, ninguém abaixo) segue 0"


# ── 8. motor de diagnóstico com os trackers fora ─────────────────────────────────────────────────────────────────────
def test_motor_com_os_trackers_fora_nao_diz_sem_tracker_travado(cli, monkeypatch):
    def _iv(n, sa):
        return {"nome": f"Inversor {n}", "strings_ativas": sa, "str_esp": 10, "desligado": False, "strings": []}
    monkeypatch.setattr(app, "_pv_plant_inversores", lambda pid, force=False: [_iv(1, 10), _iv(2, 10), _iv(3, 10),
                                                                                 _iv(4, 2)])
    monkeypatch.setattr(app, "_pv_trackers_analise", lambda *a, **k: {
        "fonte_ok": False, "erro": "API PV: ReadTimeout (simulado)", "trackers": []})
    r = cli.get(f"/api/diagnostico/pv/{PID}")
    assert r.status_code == 200
    j = r.get_json()
    assert j["trk_ok"] is False and "ReadTimeout" in j["trk_erro"]
    ev = " ".join(e for d in j["diagnosticos"] for e in d["evidencia"])
    assert "sem tracker travado associado" not in ev and "não dá para descartar tracker" in ev, j["diagnosticos"]
    # os trackers responderam e nenhum está travado: aí sim "sem tracker travado associado"
    monkeypatch.setattr(app, "_pv_trackers_analise", lambda *a, **k: {"trackers": []})
    j = cli.get(f"/api/diagnostico/pv/{PID}").get_json()
    assert j["trk_ok"] is True
    assert "sem tracker travado associado" in " ".join(e for d in j["diagnosticos"] for e in d["evidencia"])


def test_tela_motor_sem_trackers_diz_que_nao_descarta_tracker(tmp_path):
    diag = {"diagnosticos": [{"causa": "Subperformance de inversor", "escopo": "Inversor 2", "severidade": "atencao",
                              "confianca": "baixa", "acao": "Conferir os trackers",
                              "evidencia": ["Trackers sem leitura (a fonte não respondeu): não dá para descartar."]}],
            "trackers_por_inversor": {}, "resumo": {}, "trk_ok": False, "trk_erro": "API PV: ReadTimeout"}
    r = _pagina(_rotas(diag=[200, diag]), "v2Render(); out({ diags: ELS.diags.innerHTML });", tmp_path)
    assert "Trackers sem leitura no motor" in r["diags"] and "ReadTimeout" in r["diags"], r["diags"]
