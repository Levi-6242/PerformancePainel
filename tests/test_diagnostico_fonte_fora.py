# -*- coding: utf-8 -*-
"""Diagnóstico de usina com a fonte fora do ar: leitura que não veio não vira zero (10/10/2026).

O caso: na prova da porta única com o Nexus, o Diagnóstico de uma usina da API PV (/painel/usina/<id>?fonte=pv) com a
fonte respondendo 504 mostrava "Inversores 0 · 0 sem produção · 0 sem com.", "Strings 0 / 0 ativas", "Hoje 0 kWh · PR
mediana 0%" e "A fonte não devolveu inversores para esta usina." — a tela de uma usina parada, sem nada dela estar
parado. O defeito é anterior à porta única (a tela lia `fetch(...).then(r => r.json())` e desenhava o corpo do erro como
dado) e é do mesmo tipo do conserto do Painel NOC no mesmo dia (sessão vencida, PG fora): só resposta 2xx com dado vira
número.

Duas metades, como pede a regra:
1. o BACKEND diz que falhou, em vez de engolir a falha e responder 200 com vazio: o trackers da API PV (e da 2C pela API
   PV), o do PG, o motor de diagnóstico da API PV, as OS do Fracttal, os inversores e a curva das strings da API PV
   quando ela responde um dict de erro. Cada um com o caso de zero DE VERDADE ao lado (a fonte respondeu, e é zero);
2. a TELA (o script inteiro da página rodando no node, com a rede dublada): cada cartão e cada aba falha por conta própria
   — "—" e o selo "Fonte X não respondeu (HTTP 504) às HH:MM: sem leitura", e o que respondeu segue com o número dele,
   inclusive o zero.

Nenhum teste fala com fonte de verdade: a sessão HTTP é dublada (e a trava do conftest.py recusaria a SunOp e a PV).
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest
import requests

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
TPL = RAIZ / "plataforma" / "templates" / "painel_usina_v2.html"
NODE = shutil.which("node")
PID = 4242


# ── dublês da rede ──────────────────────────────────────────────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, status=200, corpo=None):
        self.status_code, self._corpo, self.headers = status, corpo, {}

    def json(self):
        return self._corpo

    @property
    def text(self):
        return json.dumps(self._corpo)


class _Sessao:
    """requests.Session de mentira: cada pedido casa com o primeiro trecho de URL da lista; o que não casa é rede fora."""

    def __init__(self, rotas):
        self.rotas, self.chamadas = list(rotas), []

    def _pede(self, metodo, url, **kw):
        self.chamadas.append((metodo, url))
        for trecho, resp in self.rotas:
            if trecho in url:
                if isinstance(resp, BaseException):
                    raise resp
                return resp
        raise requests.exceptions.ConnectionError("rota não dublada no teste: " + url)

    def post(self, url, **kw):
        return self._pede("POST", url, **kw)

    def get(self, url, **kw):
        return self._pede("GET", url, **kw)


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    monkeypatch.setattr(app, "NEXUS_SSO_CHAVE", "")
    monkeypatch.setattr(app, "_MODO_WEB", True)
    monkeypatch.setitem(app.app.config, "PROPAGATE_EXCEPTIONS", False)
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "token-de-teste")
    monkeypatch.setattr(app, "get_token", lambda force=False: "token-de-teste")
    monkeypatch.setattr(app, "get_plants", lambda token, force=False: [{"id": PID, "nome": "Usina Teste"}])
    return app.app.test_client()


def _rede(monkeypatch, rotas):
    s = _Sessao(rotas)
    monkeypatch.setattr(app, "_http", lambda: s)
    return s


# ── 1. backend ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _plant_limpo(monkeypatch):
    monkeypatch.setattr(app, "_PV_PLANT_MEMO", {})
    monkeypatch.setattr(app, "_pv_plant_falha", {})
    monkeypatch.setattr(app, "_pv_plant_devices", lambda pid: [{"device_id": 1, "device_name": "Inversor 1"},
                                                                {"device_id": 2, "device_name": "Inversor 2"}])


def test_plant_com_dict_de_erro_da_api_pv_e_504_e_nao_inversores_desligados(cli, monkeypatch):
    """A API PV responde erro com um DICT ({"error": ...}, 429 da cota, conta sem permissão). O drill tratava como "sem
    leitura" e montava a usina pelo cadastro de dispositivos com TODOS os inversores desligados e sem comunicação: a tela
    de uma usina parada."""
    _plant_limpo(monkeypatch)
    _rede(monkeypatch, [("/day_inverter", _Resp(429, {"error": "Too many requests"}))])
    r = cli.get(f"/api/plant/{PID}")
    assert r.status_code == 504, (r.status_code, r.get_json())
    j = r.get_json()
    assert "429" in j["detalhe"] and "Too many requests" in j["detalhe"]
    assert "inversores" not in j or not j["inversores"]


def test_plant_sem_leitura_de_verdade_segue_200(cli, monkeypatch):
    """Zero de verdade: a API respondeu lista vazia (a usina não leu nada hoje). Os inversores vêm do cadastro."""
    _plant_limpo(monkeypatch)
    _rede(monkeypatch, [("/day_inverter", _Resp(200, []))])
    r = cli.get(f"/api/plant/{PID}")
    assert r.status_code == 200
    assert [i["nome"] for i in r.get_json()["inversores"]] == ["Inversor 1", "Inversor 2"]


def _trk_limpo(monkeypatch):
    for nome in ("_pv_trk_plant_det", "_pv_trk_plant", "_pv_trk_dia_cache"):
        monkeypatch.setattr(app, nome, {})


def test_trackers_da_api_pv_fora_do_ar_e_502_e_nao_usina_sem_trackers(cli, monkeypatch):
    _trk_limpo(monkeypatch)
    _rede(monkeypatch, [("/trackers", requests.exceptions.ReadTimeout("simulado: a API PV não respondeu em 180 s"))])
    r = cli.get(f"/api/pv/trackers/{PID}")
    assert r.status_code == 502, (r.status_code, r.get_json())
    j = r.get_json()
    assert j["fonte"] == "API PV" and j["fonte_ok"] is False
    assert "ReadTimeout" in j["erro"] or "não respondeu" in j["erro"]
    assert j["trackers"] == [], "o corpo segue no formato de sempre (a tela antiga lê o JSON sem olhar o status)"
    assert not app._pv_trk_plant_det and not app._pv_trk_plant, "a falha não pode ficar no cache como 'sem trackers'"
    # a 2C pela API PV usa a mesma rota
    monkeypatch.setitem(app.PV_FONTES, "2capi", set(app.PV_FONTES.get("2capi") or ()) | {PID})
    assert cli.get(f"/api/owen/trackers/{PID}").status_code == 502


def test_trackers_da_api_pv_com_resposta_vazia_e_usina_sem_tracker(cli, monkeypatch):
    """Zero de verdade: a API PV respondeu 200 sem tracker nenhum (e a reserva, com o token vencido, 401)."""
    _trk_limpo(monkeypatch)
    _rede(monkeypatch, [("/v2/usinas/trackers", _Resp(401, {"message": "token"})), ("/trackers", _Resp(200, []))])
    r = cli.get(f"/api/pv/trackers/{PID}")
    assert r.status_code == 200
    j = r.get_json()
    assert j["total"] == 0 and j["trackers"] == [] and j.get("fonte_ok") is not False


def _pg_fora(*a, **k):
    raise RuntimeError("PG fora do ar (simulado)")


class _CursorVazio:
    def execute(self, *a, **k):
        pass

    def fetchall(self):
        return []


class _ConnVazia:
    def cursor(self):
        return _CursorVazio()

    def close(self):
        pass


def test_trackers_do_pg_fora_do_ar_e_503(cli, monkeypatch):
    monkeypatch.setattr(app, "_pg_trk_curva_cache", {})
    monkeypatch.setattr(app, "_pg_conn", _pg_fora)
    r = cli.get("/api/pg/trackers/321?date=2026-10-10")
    assert r.status_code == 503, (r.status_code, r.get_json())
    j = r.get_json()
    assert "PG fora do ar" in j["erro"] and j["fonte"] == "PG" and j["trackers"] == []
    # o PG voltou e a usina não tem tracker: zero de verdade, 200 (a falha não ficou presa no cache)
    monkeypatch.setattr(app, "_pg_conn", lambda: _ConnVazia())
    monkeypatch.setattr(app, "_PG_TRK_FALHA_S", 0)
    r = cli.get("/api/pg/trackers/321?date=2026-10-10")
    assert r.status_code == 200 and r.get_json()["total"] == 0


def test_motor_de_diagnostico_da_api_pv_fora_do_ar_e_504_e_nao_usina_sem_anomalia(cli, monkeypatch):
    def _plant_fora(pid, force=False):
        raise RuntimeError("API PV: ReadTimeout (simulado)")
    monkeypatch.setattr(app, "_pv_plant_inversores", _plant_fora)
    r = cli.get(f"/api/diagnostico/pv/{PID}")
    assert r.status_code == 504, (r.status_code, r.get_json())
    j = r.get_json()
    assert "ReadTimeout" in j["erro"] and j["fonte"] == "API PV" and j["diagnosticos"] == []
    # zero de verdade: a fonte respondeu e a usina não tem inversor
    monkeypatch.setattr(app, "_pv_plant_inversores", lambda pid, force=False: [])
    r = cli.get(f"/api/diagnostico/pv/{PID}")
    assert r.status_code == 200 and r.get_json()["diagnosticos"] == []


def _frac_limpo(monkeypatch):
    monkeypatch.setattr(app, "FRACTTAL_ON", True)
    monkeypatch.setattr(app, "_frac_wos_cache", {})
    monkeypatch.setattr(app, "_frac_code_cache", {})
    monkeypatch.setattr(app, "_frac_usina_ent", lambda u: {"cb": "TST100", "site": 900})
    monkeypatch.setattr(app, "_frac_inv_code", lambda u, n: "TST100-INVR1.1")


def _frac_get_dublado(estado):
    def _get(ep, *, _motivo=None, **params):
        mot = _motivo if _motivo is not None else {}
        estado["pedidos"].append(ep)
        if estado["fora"]:
            mot.update(status=429, erro="cota da empresa", reset="20")
            return None
        if ep.startswith("items/"):
            return {"data": [{"id": 77, "description": "Inversor 1.1  Huawei"}]} if estado["ativo"] else {"data": []}
        if ep.startswith("work_orders/"):
            return {"data": estado["os"]}
        return None
    return _get


_OS_ABERTA = {"wo_folio": 15001, "tasks_log_task_type_main": "Corretiva", "id_status_work_order": 1,
              "creation_date": "2026-10-09T12:00:00+00:00", "event_date": "2026-10-09T11:00:00+00:00",
              "description": "[Inversor 1.1] - Parado", "items_log_description": "Inversor 1.1 Huawei { TST100-INVR1.1 }"}


def test_os_do_fracttal_fora_do_ar_e_502_e_nao_usina_sem_os(cli, monkeypatch):
    """O Fracttal vive com a cota esgotada (429). O _frac_get devolvia None, o _frac_wos_raw guardava [] por 10 min e o
    _frac_ativo_exato guardava "ativo não existe" por 12 h: "Fracttal · OS abertas 0" por horas depois de um soluço."""
    _frac_limpo(monkeypatch)
    est = {"fora": True, "ativo": True, "os": [_OS_ABERTA], "pedidos": []}
    monkeypatch.setattr(app, "_frac_get", _frac_get_dublado(est))
    corpo = {"usina": "Usina Teste", "mes": "2026-10", "inversores": ["Inversor 1.1"]}
    r = cli.post("/api/fracttal/os", json=corpo)
    assert r.status_code == 502, (r.status_code, r.get_json())
    j = r.get_json()
    assert j["fonte"] == "Fracttal" and j["fonte_ok"] is False and "429" in j["erro"]
    assert not app._frac_wos_cache, "a falha virou 'sem OS' no cache"
    assert "TST100-INVR1.1" not in app._frac_code_cache, "a falha virou 'ativo não existe' por 12 h no cache"
    # o Fracttal voltou: a OS aparece na hora, sem esperar cache nenhum vencer
    est["fora"] = False
    r = cli.post("/api/fracttal/os", json=corpo)
    assert r.status_code == 200
    j = r.get_json()
    assert j["total"] == 2 and j["por_inversor"]["Inversor 1.1"]["os"][0]["aberta"] is True


def test_os_do_fracttal_sem_os_de_verdade_e_200_zero(cli, monkeypatch):
    _frac_limpo(monkeypatch)
    est = {"fora": False, "ativo": True, "os": [], "pedidos": []}
    monkeypatch.setattr(app, "_frac_get", _frac_get_dublado(est))
    r = cli.post("/api/fracttal/os", json={"usina": "Usina Teste", "mes": "2026-10", "inversores": ["Inversor 1.1"]})
    assert r.status_code == 200 and r.get_json()["total"] == 0
    # ativo que não existe no Fracttal (respondeu, sem item): esse sim fica no cache, e não é falha
    est["ativo"] = False
    monkeypatch.setattr(app, "_frac_code_cache", {})
    r = cli.post("/api/fracttal/os", json={"usina": "Usina Teste", "mes": "2026-10", "inversores": ["Inversor 1.1"]})
    assert r.status_code == 200 and r.get_json()["total"] == 0
    assert app._frac_code_cache["TST100-INVR1.1"]["ativo"] is None


def test_curva_das_strings_com_dict_de_erro_e_502_e_nao_sem_dados(cli, monkeypatch):
    monkeypatch.setattr(app, "_spv_cache", {})
    _rede(monkeypatch, [("/day_inverter", _Resp(401, {"error": "Invalid id, incident will be reported 2"}))])
    r = cli.get(f"/api/spv/usina/{PID}?full=1")
    assert r.status_code == 502, (r.status_code, r.get_json())
    j = r.get_json()
    assert "Invalid id" in j["erro"] and j["fonte"] == "API PV" and j["inversores"] == []
    assert "Sem dados de inversores" not in (j.get("msg") or "")
    # zero de verdade: a API respondeu lista vazia
    _rede(monkeypatch, [("/day_inverter", _Resp(200, []))])
    r = cli.get(f"/api/spv/usina/{PID}?full=1")
    assert r.status_code == 200 and "Sem dados de inversores" in r.get_json()["msg"]


def _graf_limpo(monkeypatch):
    for nome in ("_pv_trk_chart_cache", "_pv_trk_graf_cache", "_pv_trk_dia_cache"):
        monkeypatch.setattr(app, nome, {})


def test_grafico_de_trackers_da_api_pv_fora_e_502_e_nao_tracker_sem_curva(cli, monkeypatch):
    """A curva ângulo × alvo (aba Curvas, drill do tracker): a API PV em timeout e a reserva com o token vencido davam
    200 com a lista vazia, guardada 5 min — "a fonte não retornou este tracker no dia"."""
    _graf_limpo(monkeypatch)
    # "/trackerschart" antes de "/trackers": o trecho do segundo está dentro do primeiro
    _rede(monkeypatch, [("/trackerschart", _Resp(401, {"message": "token"})),
                        ("/trackers", requests.exceptions.ReadTimeout("simulado: a API PV não respondeu em 180 s"))])
    r = cli.get(f"/api/pv/trackers/{PID}/chart")
    assert r.status_code == 502, (r.status_code, r.get_json())
    j = r.get_json()
    assert j["fonte"] == "API PV" and j["fonte_ok"] is False and "ReadTimeout" in j["erro"] and "401" in j["erro"]
    assert j["trackers"] == [] and not app._pv_trk_chart_cache, "a falha não pode ficar 5 min no cache como 'sem curva'"
    # zero de verdade: a API PV respondeu o dia sem tracker e a reserva também não tem curva
    _rede(monkeypatch, [("/trackerschart", _Resp(200, {"grafico": {}})), ("/trackers", _Resp(200, []))])
    r = cli.get(f"/api/pv/trackers/{PID}/chart")
    assert r.status_code == 200 and r.get_json()["trackers"] == [] and "erro" not in r.get_json()
    # a reserva supre a API PV fora: é curva de verdade, 200
    _graf_limpo(monkeypatch)
    pts = [{"x": f"2026-10-10T{h:02d}:00:00", "y": float(h - 12) * 4} for h in range(7, 18)]
    _rede(monkeypatch, [("/trackerschart", _Resp(200, {"grafico": {"Tracker 1": pts}})),
                        ("/trackers", _Resp(504, {"error": "gateway"}))])
    r = cli.get(f"/api/pv/trackers/{PID}/chart")
    assert r.status_code == 200 and [t["id"] for t in r.get_json()["trackers"]] == ["Tracker 1"]


def test_grafico_de_trackers_do_pg_fora_e_503(cli, monkeypatch):
    monkeypatch.setattr(app, "_pg_trk_curva_cache", {})
    monkeypatch.setattr(app, "_pg_conn", _pg_fora)
    r = cli.get("/api/pg/trackers/321/chart?date=2026-10-10")
    assert r.status_code == 503, (r.status_code, r.get_json())
    j = r.get_json()
    assert j["fonte"] == "PG" and "PG fora do ar" in j["erro"] and j["trackers"] == []
    monkeypatch.setattr(app, "_pg_conn", lambda: _ConnVazia())
    monkeypatch.setattr(app, "_PG_TRK_FALHA_S", 0)
    r = cli.get("/api/pg/trackers/321/chart?date=2026-10-10")
    assert r.status_code == 200 and r.get_json()["trackers"] == []


def test_plant_da_solaredge_fora_e_502_e_nao_usina_sem_inversor(cli, monkeypatch):
    """RenoGrid: a lista de dispositivos que não veio virava 200 com inversores [] ("Inversores 0", "Hoje 0 kWh")."""
    monkeypatch.setattr(app, "se_sites", lambda: [])
    monkeypatch.setattr(app, "_se_headers", lambda: {})
    _rede(monkeypatch, [("/devices", _Resp(503, {"message": "indisponível"}))])
    r = cli.get("/api/solaredge/plant/777")
    assert r.status_code == 502, (r.status_code, r.get_json())
    j = r.get_json()
    assert j["fonte"] == "SolarEdge" and "503" in j["erro"] and j["inversores"] == []
    _rede(monkeypatch, [("/devices", requests.exceptions.ConnectionError("simulado: sem rota"))])
    assert cli.get("/api/solaredge/plant/777").status_code == 502
    # zero de verdade: a SolarEdge respondeu o site sem dispositivo
    _rede(monkeypatch, [("/devices", _Resp(200, []))])
    r = cli.get("/api/solaredge/plant/777")
    assert r.status_code == 200 and r.get_json()["inversores"] == []


def test_plant_do_pg_com_o_snapshot_frio_e_503(cli, monkeypatch):
    """O pedido do Nexus só lê o snapshot que já existe; frio, recebia {} e o drill dizia que a usina não tem inversor."""
    monkeypatch.setattr(app, "_pg_get_snapshot", lambda force=False: ([], {}))
    r = cli.get("/api/pg/plant/20")
    assert r.status_code == 503, (r.status_code, r.get_json())
    assert r.get_json()["fonte"] == "PG" and r.get_json()["inversores"] == []
    # snapshot montado e a usina fora dele: o drill responde 200 sem inversor (a fonte leu, e não tem)
    monkeypatch.setattr(app, "_pg_get_snapshot", lambda force=False: ([{"plant_id": 21}], {21: []}))
    monkeypatch.setattr(app, "_pg_pr_get", lambda dia, force=False: ([], {}))
    r = cli.get("/api/pg/plant/20")
    assert r.status_code == 200 and r.get_json()["inversores"] == []


def _osperf_limpo(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "FRACTTAL_ON", True)
    monkeypatch.setattr(app, "_frac_fractall_map", lambda: {"usina teste": "UFV Teste Fractall"})
    monkeypatch.setattr(app, "_os_atribuidas_de", lambda u: [])
    monkeypatch.setattr(app, "_frac_osperf_idx", {})
    monkeypatch.setattr(app, "_frac_openwo_idx", {})
    monkeypatch.setattr(app, "_frac_osperf_ts", 0.0)
    monkeypatch.setattr(app, "_frac_osperf_falha", None)
    monkeypatch.setattr(app, "_FRAC_OSPERF_FILE", str(tmp_path / "frac_osperf_index.json"))


def _wo_perf(folio):
    return {"wo_folio": folio, "groups_1_description": "UFV Teste Fractall", "id_status_work_order": 1,
            "labels": [{"id": app.FRAC_OS_PERF_LABEL}], "description": "[Inversor 1.1] - Abaixo",
            "items_log_description": "Inversor 1.1 { TST100-INVR1.1 }", "creation_date": "2026-10-09T12:00:00+00:00"}


def test_os_de_performance_com_o_fracttal_fora_e_sem_indice_e_502(cli, monkeypatch, tmp_path):
    """Boot frio com a cota do Fracttal esgotada: a varredura lia o None como "acabaram as OS", gravava o índice VAZIO
    por 30 min e a rota respondia 200 com os: [] — o cartão "Fracttal · OS abertas" somava 0."""
    _osperf_limpo(monkeypatch, tmp_path)
    est = {"fora": True, "ativo": True, "os": [], "pedidos": []}
    monkeypatch.setattr(app, "_frac_get", _frac_get_dublado(est))
    r = cli.get("/api/os-performance?usina=Usina Teste")
    assert r.status_code == 502, (r.status_code, r.get_json())
    j = r.get_json()
    assert j["fonte"] == "Fracttal" and "429" in j["erro"] and j["os"] == []
    assert not (tmp_path / "frac_osperf_index.json").exists(), "a falha gravou o índice vazio no disco"
    n = len(est["pedidos"])
    assert cli.get("/api/os-performance?usina=Usina Teste").status_code == 502
    assert len(est["pedidos"]) == n, "logo depois da falha a rota não varre de novo (a cota é da empresa inteira)"
    # o Fracttal voltou e a usina não tem OS de Performance aberta: zero de verdade, 200
    est["fora"] = False
    monkeypatch.setattr(app, "FRAC_OSPERF_FALHA_S", 0)
    r = cli.get("/api/os-performance?usina=Usina Teste")
    assert r.status_code == 200 and r.get_json()["os"] == [] and app._frac_osperf_falha is None


def test_os_de_performance_falha_no_meio_da_varredura_mantem_o_indice_anterior(cli, monkeypatch, tmp_path):
    """A 2a página que não veio encerrava a varredura como fim de lista e gravava só a 1a: as OS das outras páginas
    sumiam por 30 min. Agora o índice anterior fica, e a rota segue servindo a última leitura boa."""
    _osperf_limpo(monkeypatch, tmp_path)
    anterior = {"ufv teste fractall": [{"os": 999, "categoria": "Performance", "status": "Em andamento", "nota": "x",
                                        "sub": "Inversor 1.1", "data": "2026-10-01", "aberta": True}]}
    monkeypatch.setattr(app, "_frac_osperf_idx", anterior)
    pedidos = []

    def _get(ep, *, _motivo=None, **p):
        pedidos.append(p.get("start"))
        if p.get("start", 0) == 0:
            return {"data": [_wo_perf(15001)] * 200, "total": 400}
        _motivo.update(status=429, erro="cota", reset="9")
        return None
    monkeypatch.setattr(app, "_frac_get", _get)
    r = cli.get("/api/os-performance?usina=Usina Teste")
    assert r.status_code == 200 and [o["os"] for o in r.get_json()["os"]] == [999], r.get_json()
    assert pedidos == [0, 200] and app._frac_osperf_idx is anterior and app._frac_osperf_falha


def _cascata_dublada(monkeypatch, livro_fora=False):
    class _J:
        def __init__(self, d):
            self.d = d

        def get_json(self):
            return self.d

    def _livro_fora(f, force=False):
        raise RuntimeError("livro de paradas fora (simulado)")
    serie = {"usina": "Usina Teste", "pot": 5.0, "meta": 0.8, "meta_ger": 20.0, "meta_poa": 5.5,
             "pontos": [{"geracao": 19.0, "poa": 5.2}, {"geracao": 18.0, "poa": 5.0}]}
    monkeypatch.setattr(app, "api_g_diario", lambda: _J(serie))
    monkeypatch.setattr(app, "_fonte_da_usina", lambda u: "pg")
    monkeypatch.setattr(app, "_paradas_book_get", _livro_fora if livro_fora else (lambda f, force=False: {"rows": []}))
    monkeypatch.setattr(app, "_trk_frota_total", lambda *a, **k: 60)
    _frac_limpo(monkeypatch)


def test_cascata_com_o_fracttal_fora_marca_os_degraus_de_os_sem_leitura(cli, monkeypatch):
    """A queda de energia e o equipamento vêm das OS do Fracttal. Com ele em 429 os dois degraus saíam 0 e o "não
    explicado" ficava com tudo, sem nada dizer que era falta de leitura. O mesmo com o livro de paradas (tracker)."""
    _cascata_dublada(monkeypatch)
    est = {"fora": True, "ativo": True, "os": [], "pedidos": []}
    monkeypatch.setattr(app, "_frac_get", _frac_get_dublado(est))
    j = cli.get("/api/cascata?usina=Usina Teste&ano=2026&mes=10").get_json()
    assert j["ok"] is True and j["fracttal_ok"] is False and "429" in j["fracttal_erro"], j
    assert j["trk_ok"] is True
    est["fora"] = False                 # o Fracttal respondeu, sem OS no mês: zero de verdade
    j = cli.get("/api/cascata?usina=Usina Teste&ano=2026&mes=10").get_json()
    assert j["fracttal_ok"] is True and j["fracttal_erro"] is None and j["perda_deslig"] == 0
    _cascata_dublada(monkeypatch, livro_fora=True)
    monkeypatch.setattr(app, "_frac_get", _frac_get_dublado(est))
    j = cli.get("/api/cascata?usina=Usina Teste&ano=2026&mes=10").get_json()
    assert j["trk_ok"] is False and "livro de paradas" in j["trk_erro"] and j["fracttal_ok"] is True


# ── 2. a tela: o script inteiro da página no node, com a rede dublada ──────────────────────────────────────────────
_PAGINA = r"""
const __CFG = %(cfg)s;
const ELS = {}, avisos = [], pedidos = [], corpos = [];
function mkEl(id) { return { id, innerHTML: "", textContent: "", hidden: false, value: "", style: {}, dataset: {},
  className: "", title: "", disabled: false, parentNode: null, nextSibling: null,
  classList: { toggle() {}, add() {}, remove() {}, contains() { return false; } },
  querySelectorAll() { return []; }, querySelector() { return null; }, insertAdjacentHTML() {}, scrollIntoView() {},
  appendChild(c) { return c; }, insertBefore(c) { return c; }, setAttribute() {}, focus() {}, getContext() { return {}; } }; }
globalThis.window = globalThis;
globalThis.document = { getElementById: id => ELS[id] || (ELS[id] = mkEl(id)), querySelectorAll: () => [],
  querySelector: () => null, body: mkEl("body"), createElement: t => mkEl(t) };
globalThis.location = { search: __CFG.search, pathname: "/painel/usina/%(pid)s", origin: "https://app.exemplo.com",
  href: "https://app.exemplo.com/painel/usina/%(pid)s" + __CFG.search };
globalThis.localStorage = { getItem() { return null; }, setItem() {} };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => "#888" });
globalThis.Chart = class { constructor() { this.data = { datasets: [] }; this.options = { scales: { y2: { title: {} } }, plugins: {} }; }
  destroy() {} update() {} };
globalThis.setTimeout = () => 0; globalThis.clearTimeout = () => {};
window.gcSessaoDaPlataforma = { falhou(m, q, f) { avisos.push(["falhou", m, q, f]); }, voltou() { avisos.push(["voltou"]); },
  tokens: t => t, semAdmin: false, estado: () => "" };
let R = __CFG.rotas;
globalThis.fetch = async (u, o) => {
  const k = String(u).split("?")[0];
  let x = R[k];
  pedidos.push(k);
  if (o && o.body) corpos.push([k, JSON.parse(o.body)]);
  if (typeof x === "function") x = x(o && o.body ? JSON.parse(o.body) : null);   // rota que responde conforme o pedido
  if (!x) throw new TypeError("Failed to fetch");
  if (x === "rede") throw new TypeError("Failed to fetch");
  return { ok: x[0] >= 200 && x[0] < 300, status: x[0], json: async () => x[1] };
};
const espera = () => new Promise(r => setImmediate(r));
async function assenta() { for (let i = 0; i < 40; i++) await espera(); }
function out(o) { process.stdout.write("\n" + JSON.stringify(o)); }
function cartoes() {   // os 5 cartões de cima: rótulo -> {v, s}
  const m = {}, h = ELS.below ? ELS.below.innerHTML : "";
  const rx = /<div class="l">([^<]*)<\/div><div class="v num">([\s\S]*?)<\/div><div class="s">([\s\S]*?)<\/div><\/div>/g;
  let a; while ((a = rx.exec(h))) m[a[1]] = { v: a[2], s: a[3] };
  return m;
}
"""


def _inv(n, eday=120.0):
    return {"id": n, "nome": f"Inversor {n}", "nome_api": f"INV{n}", "desligado": False, "falha_comunicacao": False,
            "active_power": 50.0, "strings_ativas": 2, "str_esp": 2, "eday": eday, "ultima_leitura": "2026-10-10 14:30:00",
            "strings": [{"id": "Ipv1", "corrente": 8.1, "status": "ativa", "ativa": True},
                        {"id": "Ipv2", "corrente": 8.0, "status": "ativa", "ativa": True}]}


def _trks(n=60):
    return {"total": n, "parados": 0, "severos": 0, "medios": 0, "leves": 0, "desvio_medio": 1.2,
            "trackers": [{"id": f"TRK{i}", "status": "normal", "atual": 10.0, "alvo": 10.0, "disparidade": 0.5}
                         for i in range(1, n + 1)]}


def _rotas(**troca):
    p = f"/api/plant/{PID}"
    base = {
        "/api/state": [200, {"comments_thread": {}, "comments": {}}],
        "/api/os-performance": [200, {"os": []}],
        p: [200, {"plant_id": PID, "inversores": [_inv(1), _inv(2)]}],
        f"/api/pv/trackers/{PID}": [200, _trks()],
        f"/api/diagnostico/pv/{PID}": [200, {"diagnosticos": [], "trackers_por_inversor": {}, "resumo": {}}],
        "/api/fracttal/os": [200, {"ok": True, "usina_os": [], "por_inversor": {}, "total": 0}],
        "/api/cascata": [200, {"ok": False, "motivo": "sem dado (teste)"}],
        f"/api/pv/grupo/{PID}": [200, {"membros": []}],
        "/api/inv/pr-mes": [200, {"inversores": {}, "pr_meta": None}],
        f"/api/pv/pr/{PID}": [200, {"inversores": [{"nome": "Inversor 1", "pr": 0.81}, {"nome": "Inversor 2", "pr": 0.79}],
                                    "pr_mediana": 0.8}],
        "/api/trackers/de-para": [200, {"sem_depara": True}],
        "/api/perdas/pv/trackers/paradas-hist": [200, {"rows": []}],
        "/api/ronda/recorrentes": [200, {"recorrentes": []}],
        "/api/trackers/os-sugeridas": [200, {"rows": []}],
        "/api/notificacoes": [200, {"eventos": []}],
        f"/api/pv/inversores/energia-mes/{PID}": [200, {"inversores": {}}],
        f"/api/pv/inv-padrao/{PID}": [200, {"na_regua": False}],
        f"/api/pv/inversores/historico/{PID}": [200, {"dias": [], "inversores": {}}],
        f"/api/spv/usina/{PID}": [200, {"inversores": []}],
        f"/api/pv/trackers/{PID}/chart": [200, {"trackers": []}],
    }
    for k, v in troca.items():
        base[{"plant": p, "trk": f"/api/pv/trackers/{PID}", "diag": f"/api/diagnostico/pv/{PID}",
              "fracttal": "/api/fracttal/os", "osperf": "/api/os-performance", "pr": f"/api/pv/pr/{PID}",
              "grupo": f"/api/pv/grupo/{PID}", "spv": f"/api/spv/usina/{PID}",
              "irma": "/api/plant/4243"}[k]] = v
    return base


def _pagina(rotas, roteiro, tmp_path, search="?fonte=pv&nome=Usina%20Teste", antes=""):
    """`antes` = JS que roda antes do script da página (relógio fixo, rota que responde conforme o pedido)."""
    if not NODE:
        pytest.skip("node não instalado")
    h = TPL.read_text(encoding="utf-8")
    i = h.index("<script>\nconst PLANT_ID=")
    script = h[i + len("<script>"):h.index("</script>", i)].replace("{{ plant_id|tojson }}", str(PID))
    js = (_PAGINA % {"cfg": json.dumps({"search": search, "rotas": rotas}), "pid": PID} + antes + "\n" + script
          + "\n(async () => {\n await assenta();\n" + roteiro + "\n})().catch(e => { console.error(e); process.exit(3); });")
    arq = tmp_path / "pagina.js"
    arq.write_text(js, encoding="utf-8")
    p = subprocess.run([NODE, str(arq)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr[-3000:]
    return json.loads(p.stdout.strip().splitlines()[-1])


def _sem(v):
    """O cartão sem leitura: o valor é só o travessão (o span cinza em volta é estilo)."""
    return re.sub(r"<[^>]+>", "", v).strip() == "—"


_SELO = re.compile(r"não respondeu \(HTTP (\d{3})\) às \d{2}:\d{2}: sem leitura")
_504 = [504, {"error": "falha", "detalhe": "ReadTimeout: a API PV não respondeu em 60 s"}]


def test_tela_inversores_da_fonte_fora_nao_vira_usina_parada(tmp_path):
    """O print da prova da porta única: /api/plant 504 e o motor de diagnóstico 504 (é a mesma leitura na API PV)."""
    r = _pagina(_rotas(plant=_504, diag=_504), """
      v2Render();
      out({ c: cartoes(), inv: ELS.v2InvBody.innerHTML, heat: ELS.heatmap.innerHTML, diags: ELS.diags.innerHTML,
            avisos, nInv: ELS.v2nInv.textContent });""", tmp_path)
    c = r["c"]
    for rot in ("Inversores", "Strings", "Hoje"):
        assert _sem(c[rot]["v"]), (rot, c[rot])
        m = _SELO.search(c[rot]["s"])
        assert m and m.group(1) == "504", (rot, c[rot]["s"])
        assert "Fonte API PV" in c[rot]["s"]
    assert "0 sem produção" not in c["Inversores"]["v"] and "kWh" not in c["Hoje"]["v"].split("<small>")[0]
    assert "PR mediana 80%" in c["Hoje"]["s"], "o PR veio da rota dele e não some com os inversores"
    # o que respondeu segue com o número dele, inclusive o zero de verdade
    assert c["Trackers"]["v"].startswith("0 <small>/ 60 parados"), c["Trackers"]
    # ...e as OS por inversor, que dependem da lista de inversores, não: "OS abertas 0" era o print (revisão de 11/10/2026)
    fr = c["Fracttal · OS abertas"]
    assert _sem(fr["v"]) and "OS por inversor sem leitura" in fr["s"] and "HTTP 504" in fr["s"], fr
    assert "A fonte não devolveu inversores" not in r["inv"] and _SELO.search(r["inv"]), r["inv"]
    assert "Sem strings hoje" not in r["heat"] and _SELO.search(r["heat"]), r["heat"]
    assert "Sem anomalias" not in r["diags"] and "não respondeu" in r["diags"], r["diags"]
    assert r["nInv"] == ""
    falhou = [a for a in r["avisos"] if a[0] == "falhou"]
    assert falhou and "API PV" in falhou[-1][1] and "504" in falhou[-1][1], r["avisos"]


def test_tela_tudo_respondeu_mostra_os_numeros_e_nao_liga_a_faixa(tmp_path):
    r = _pagina(_rotas(), "v2Render(); out({ c: cartoes(), avisos });", tmp_path)
    c = r["c"]
    assert c["Inversores"]["v"].startswith("2 <small>· 0 sem produção"), c["Inversores"]
    assert c["Strings"]["v"].startswith("4 <small>/ 4 ativas")
    assert c["Hoje"]["v"].startswith("240 <small>kWh") and "PR mediana 81%" in c["Hoje"]["s"]   # a dos inversores
    assert c["Trackers"]["v"].startswith("0 <small>/ 60 parados") and c["Fracttal · OS abertas"]["v"] == "0"
    assert not [a for a in r["avisos"] if a[0] == "falhou"]


def test_tela_zero_de_verdade_continua_zero(tmp_path):
    """À noite, com a usina sem tracker: a fonte respondeu, e o que ela disse é zero. Nada de "—"."""
    noite = {"plant_id": PID, "inversores": [_inv(1, eday=0), _inv(2, eday=0)]}
    sem_trk = {"total": 0, "parados": 0, "severos": 0, "medios": 0, "leves": 0, "trackers": [], "tem_trackers": False}
    r = _pagina(_rotas(plant=[200, noite], trk=[200, sem_trk]), """
      v2Render(); const c = cartoes(); v2Tab('trk');
      out({ c, trk: ELS.v2TrkBody.innerHTML, cards: ELS.trackers.innerHTML });""", tmp_path)
    assert r["c"]["Hoje"]["v"].startswith("0 <small>kWh"), r["c"]["Hoje"]
    assert r["c"]["Trackers"]["v"].startswith("0 <small>/ 0 parados")
    assert "Esta usina não tem trackers cadastrados." in r["trk"] and "não respondeu" not in r["trk"]


def test_tela_trackers_fora_so_os_trackers_ficam_sem_leitura(tmp_path):
    for trk in ([502, {"erro": "API PV: ReadTimeout", "fonte": "API PV", "fonte_ok": False, "trackers": [], "total": 0}],
                [200, {"erro": "API PV: ReadTimeout", "fonte": "API PV", "fonte_ok": False, "trackers": [], "total": 0}]):
        r = _pagina(_rotas(trk=trk), """
          v2Render(); const c = cartoes(); v2Tab('trk');
          out({ c, trk: ELS.v2TrkBody.innerHTML, cards: ELS.trackers.innerHTML, avisos });""", tmp_path)
        c = r["c"]
        assert _sem(c["Trackers"]["v"]), c["Trackers"]
        assert "não respondeu" in c["Trackers"]["s"] and "sem leitura" in c["Trackers"]["s"]
        assert "0 parados sem ticket" not in c["Trackers"]["s"]
        assert c["Inversores"]["v"].startswith("2 <small>"), "os inversores responderam e seguem com o número deles"
        assert "Esta usina não tem trackers" not in r["trk"] and "não respondeu" in r["trk"], r["trk"]
        assert "Esta usina não tem trackers" not in r["cards"] and "não respondeu" in r["cards"], r["cards"]


def test_tela_fracttal_fora_so_as_os_ficam_sem_leitura(tmp_path):
    parcial = {"ok": False, "fonte_ok": False, "fonte": "Fracttal", "erro": "o Fracttal não respondeu (HTTP 429)",
               "usina_os": [], "por_inversor": {}, "total": 0}
    for frac, osperf in (([502, parcial], None), (None, [500, {"error": "x"}]), (None, "rede")):
        tr = {}
        if frac:
            tr["fracttal"] = frac
        if osperf:
            tr["osperf"] = osperf
        r = _pagina(_rotas(**tr), "v2Render(); out({ c: cartoes(), os: ELS.osList.innerHTML });", tmp_path)
        c = r["c"]
        assert _sem(c["Fracttal · OS abertas"]["v"]), (tr, c["Fracttal · OS abertas"])
        assert "não respondeu" in c["Fracttal · OS abertas"]["s"] and "sem leitura" in c["Fracttal · OS abertas"]["s"]
        assert c["Inversores"]["v"].startswith("2 <small>") and c["Trackers"]["v"].startswith("0 <small>/ 60")
        if frac:
            assert "não respondeu" in r["os"] and "Nenhuma OS" not in r["os"], r["os"]


def test_tela_pr_fora_nao_vira_pr_mediana_zero(tmp_path):
    r = _pagina(_rotas(pr=[500, {"error": "boom", "inversores": []}]), "v2Render(); out({ c: cartoes() });", tmp_path)
    s = r["c"]["Hoje"]["s"]
    assert "PR mediana 0%" not in s and "PR mediana —" in s, s
    assert r["c"]["Hoje"]["v"].startswith("240 <small>kWh")


def test_tela_sessao_vencida_e_sem_leitura_e_a_faixa_e_a_da_sessao(tmp_path):
    r = _pagina(_rotas(plant=[401, {"error": "não autenticado"}]), "v2Render(); out({ c: cartoes(), avisos });", tmp_path)
    c = r["c"]["Inversores"]
    assert _sem(c["v"]) and "sessão vencida" in c["s"], c
    assert not [a for a in r["avisos"] if a[0] == "falhou" and "sessão" in (a[1] or "")], \
        "o 401 é do aviso de sessão (ele mesmo liga a faixa dele); a faixa de fonte não cobre a explicação"


def test_tela_troca_de_dia_com_trackers_fora_guarda_o_ultimo_bom_do_mesmo_dia(tmp_path):
    """O dia escolhido no cabeçalho relê os trackers. Falhou a releitura de um dia que a tela já tinha: fica o último
    bom com a hora dele. Falhou um dia que a tela nunca leu: "—", nunca os de outro dia sob o rótulo deste."""
    r = _pagina(_rotas(), """
      const hoje = v2HojeISO();
      R["/api/pv/trackers/%(pid)s"] = [504, {"erro": "API PV: ReadTimeout", "fonte": "API PV", "fonte_ok": false}];
      v2SetDia("2026-10-01"); await assenta(); v2Render(); const outro = cartoes().Trackers;
      v2SetDia(hoje); await assenta(); v2Render(); const mesmo = cartoes().Trackers;
      out({ outro, mesmo });""" % {"pid": PID}, tmp_path)
    assert _sem(r["outro"]["v"]) and "não respondeu" in r["outro"]["s"], r["outro"]
    assert r["mesmo"]["v"].startswith("0 <small>/ 60 parados"), r["mesmo"]
    assert "não atualizou" in r["mesmo"]["s"] and re.search(r"leitura das \d{2}:\d{2}", r["mesmo"]["s"]), r["mesmo"]


def test_tela_curvas_com_a_fonte_fora_dizem_que_nao_respondeu_e_nao_recuam_para_ontem(tmp_path):
    r = _pagina(_rotas(spv=[502, {"erro": "API PV respondeu 401: Invalid id", "fonte": "API PV", "inversores": []}]), """
      await selInvCurva("Inversor 1"); await assenta();
      out({ sub: ELS.invCurvaSub.textContent, n: pedidos.filter(p => p === "/api/spv/usina/%(pid)s").length,
            dia: ELS.icData.value, hoje: v2HojeISO() });""" % {"pid": PID}, tmp_path)
    assert _SELO.search(r["sub"]) and "502" in r["sub"], r["sub"]
    assert r["n"] == 1 and r["dia"] == r["hoje"], "a falha de hoje não é 'ainda sem curva': não recua para ontem"


def test_tela_planta_irma_fora_nao_vira_usina_menor(tmp_path):
    """Nova Londrina é uma usina em duas plantas na API PV. A irmã que não respondeu deixava a tela com os inversores de
    uma só, como se a usina inteira fosse aquela."""
    grupo = [200, {"membros": [{"id": PID, "nome": "Usina Teste 1"}, {"id": 4243, "nome": "Usina Teste 2"}]}]
    r = _pagina(_rotas(grupo=grupo, irma=_504), "v2Render(); out({ c: cartoes(), inv: ELS.v2InvNota.innerHTML });",
                tmp_path)
    c = r["c"]
    assert _sem(c["Inversores"]["v"]) and "Usina Teste 2" in c["Inversores"]["s"], c["Inversores"]
    assert "504" in c["Inversores"]["s"]
    ok = _pagina(_rotas(grupo=grupo, irma=[200, {"plant_id": 4243, "inversores": [_inv(3)]}]),
                 "v2Render(); out({ c: cartoes() });", tmp_path)
    assert ok["c"]["Inversores"]["v"].startswith("3 <small>"), ok["c"]["Inversores"]


def _casc(**troca):
    d = {"ok": True, "usina": "Usina Teste", "ano": 2026, "mes": 10, "dias": 10, "pot": 5.0, "pr_meta": 0.8,
         "pr_real": 0.74, "p50": 200.0, "poa": 52.0, "poa_prev": 55.0, "possivel": 208.0, "geracao": 192.4,
         "perda_ipoa": 12.0, "perda_trk": 3.0, "perda_deslig": 0.0, "perda_rede": 0.0, "perda_equip": 0.0,
         "nao_explicado": 12.6, "disponibilidade_ufv": 1.0,
         "trk": {"paradas": 2, "trackers": 2, "frota": 60, "horas_solares": 9.0},
         "os": {"qtd": 0, "rede": {"qtd": 0}, "equip": {"qtd": 0}}, "abertos": [], "externo": 12.0, "om": 3.0,
         "fracttal_ok": True, "fracttal_erro": None, "trk_ok": True, "trk_erro": None}
    d.update(troca)
    return d


def test_tela_mes_cascata_com_o_fracttal_fora_diz_sem_leitura_e_nao_desligamento_zero(tmp_path):
    """Aba Mês · gerencial: a vista padrão da cascata (PR) mostrava "− Desligamento −0,00" com o Fracttal em 429."""
    fora = _casc(fracttal_ok=False, fracttal_erro="o Fracttal não respondeu (HTTP 429)")
    r = _pagina(dict(_rotas(), **{"/api/cascata": [200, fora]}),
                "out({ sub: ELS.cascSub.innerHTML, body: ELS.cascBody.innerHTML });", tmp_path)
    assert "o Fracttal não respondeu (HTTP 429)" in r["sub"] and "sem leitura (não é zero)" in r["sub"], r["sub"]
    assert ">sem leitura</text>" in r["body"], "o degrau de desligamento não diz que é sem leitura"
    assert ">0,00</text>" not in r["body"] and ">—</text>" in r["body"], "o degrau sem leitura ainda mostra o zero"
    assert "(sem queda de energia e equipamento, que não responderam)" in r["body"]
    ok = _pagina(dict(_rotas(), **{"/api/cascata": [200, _casc()]}),
                 "out({ sub: ELS.cascSub.innerHTML, body: ELS.cascBody.innerHTML });", tmp_path)
    assert "não respondeu" not in ok["sub"] and ">0,00</text>" in ok["body"], "o zero de verdade continua zero"
    assert ">sem leitura</text>" not in ok["body"]


def test_tela_mes_cascata_que_nao_respondeu_diz_por_que(tmp_path):
    r = _pagina(dict(_rotas(), **{"/api/cascata": [500, {"ok": False, "motivo": "boom"}]}),
                "out({ body: ELS.cascBody.innerHTML });", tmp_path)
    assert "A cascata não respondeu (HTTP 500" in r["body"] and "não é perda zero" in r["body"], r["body"]


def test_tela_curva_do_tracker_com_a_fonte_fora_nao_diz_que_o_tracker_nao_tem_curva(tmp_path):
    """Aba Curvas (correlação): o 502 do gráfico de trackers era "Sem curva para TRK1 (a fonte não retornou este tracker
    no dia)" — e o mesmo no drill da aba Trackers, que ainda guardava a falha até trocar o dia."""
    chart = f"/api/pv/trackers/{PID}/chart"
    r = _pagina(dict(_rotas(), **{chart: [502, {"erro": "API PV: ReadTimeout", "fonte": "API PV", "fonte_ok": False,
                                               "trackers": []}]}), """
      await drawCurveById("TRK1", false); await assenta();
      out({ sub: ELS.curveSub.textContent });""", tmp_path)
    assert _SELO.search(r["sub"]) and "502" in r["sub"] and "a fonte não retornou" not in r["sub"], r["sub"]


def test_tela_inversor_aberto_com_o_fracttal_fora_nao_diz_sem_os(tmp_path):
    parcial = {"ok": False, "fonte_ok": False, "fonte": "Fracttal", "erro": "o Fracttal não respondeu (HTTP 429)",
               "usina_os": [], "por_inversor": {}, "total": 0}
    r = _pagina(_rotas(fracttal=[502, parcial]), """
      V2.sel = "Inversor 1"; v2Render(); out({ inv: ELS.v2InvBody.innerHTML });""", tmp_path)
    assert "sem OS aberta neste inversor" not in r["inv"] and "não é inversor sem OS" in r["inv"], r["inv"]
    ok = _pagina(_rotas(), 'V2.sel = "Inversor 1"; v2Render(); out({ inv: ELS.v2InvBody.innerHTML });', tmp_path)
    assert "sem OS aberta neste inversor" in ok["inv"]


def test_tela_thopen_pg_fora_mostra_sem_leitura_nos_cartoes(tmp_path):
    """Outra fonte, a mesma régua: o drill do PG com o banco fora (500) e os trackers do PG em 503."""
    pg = {"/api/state": [200, {"comments_thread": {}, "comments": {}}], "/api/os-performance": [200, {"os": []}],
          f"/api/pg/plant/{PID}": [500, {"error": "PG fora", "inversores": []}],
          f"/api/pg/trackers/{PID}": [503, {"erro": "PG: OperationalError", "fonte": "PG", "fonte_ok": False,
                                            "trackers": [], "total": 0}],
          f"/api/diagnostico/{PID}": [500, {"error": "PG fora", "diagnosticos": []}],
          "/api/fracttal/os": [200, {"ok": True, "usina_os": [], "por_inversor": {}, "total": 0}],
          "/api/cascata": [200, {"ok": False, "motivo": "sem dado (teste)"}],
          f"/api/pg/pr/{PID}": [500, {"error": "PG fora"}]}
    r = _pagina(pg, "v2Render(); out({ c: cartoes(), inv: ELS.v2InvBody.innerHTML });", tmp_path,
                search="?fonte=pg&nome=Usina%20Teste")
    c = r["c"]
    for rot in ("Inversores", "Strings", "Hoje", "Trackers"):
        assert _sem(c[rot]["v"]), (rot, c[rot])
        assert "Fonte Thopen/PG não respondeu (HTTP 50" in c[rot]["s"], (rot, c[rot]["s"])
    assert "PR mediana —" in c["Hoje"]["s"]
    fr = c["Fracttal · OS abertas"]   # sem a lista de inversores, as OS por inversor nem foram pedidas: não é "0"
    assert _sem(fr["v"]) and "OS por inversor sem leitura" in fr["s"] and "Thopen/PG não respondeu (HTTP 500)" in fr["s"]
    assert "A fonte não devolveu inversores" not in r["inv"]


def _rotas_hist(**troca):
    pts = [{"dia": d, "geracao": 18.0, "poa": 5.1, "realizado": 0.78} for d in range(1, 11)]
    base = {"/api/state": [200, {"comments_thread": {}, "comments": {}}],
            "/api/g/inversores": [200, {"usina": "Usina Teste", "alvo": 0.8, "inversores": [
                {"inversor": "Inversor 1", "pr": 0.79, "alvo": 0.8, "dif": -0.01, "ger": 90.0},
                {"inversor": "Inversor 2", "pr": 0.82, "alvo": 0.8, "dif": 0.02, "ger": 92.0}]}],
            "/api/gerencial/disponibilidade": [200, {"quente": True, "usinas": [
                {"usina": "Usina Teste", "disp": 99.1, "disp_equip": 99.5, "disp_queda": 99.6, "h_perdidas": 1.2,
                 "n_os": 1, "kwh": 300, "inversores": []}], "oss": []}],
            "/api/g/mensal": [200, {"pontos": [{"ano": 2026, "mes": 10, "realizado": 0.78, "meta": 0.8}]}],
            "/api/g/tickets-trackers": [200, {"tem_ticket": False}],
            "/api/g/diario": [200, {"meta": 0.8, "meta_ger": 19.0, "pontos": pts}]}
    for k, v in troca.items():
        base[{"inv": "/api/g/inversores", "disp": "/api/gerencial/disponibilidade", "men": "/api/g/mensal",
              "dia": "/api/g/diario"}[k]] = v
    return base


def test_tela_modo_historico_mes_gerencial_com_leitura_fora_nao_vira_usina_vazia(tmp_path):
    """Usina sem fonte ao vivo (?hist=1): o Mês · gerencial lia o corpo do 500 como dado — "todos no alvo", "ainda não
    tem quebra por inversor" e "fora do Fracttal ou não Full O&M" com o BD e o índice de disponibilidade fora."""
    busca = "?hist=1&nome=Usina%20Teste&cliente=Cliente%20X"
    r = _pagina(_rotas_hist(inv=[500, {"error": "boom"}], disp=[503, {"erro": "índice fora", "usinas": []}]), """
      await assenta();
      out({ kpis: ELS.below.innerHTML, inv: ELS.v2InvBody.innerHTML, mes: ELS["v2-mes"].innerHTML, avisos });""",
                tmp_path, search=busca)
    assert "todos no alvo" not in r["kpis"] and "não é usina sem inversor" in r["kpis"], r["kpis"]
    assert "ainda não tem quebra por inversor" not in r["inv"] and "não respondeu (HTTP 500)" in r["inv"], r["inv"]
    assert "fora do Fracttal" not in r["mes"] and "Disponibilidade (Fracttal) não respondeu (HTTP 503)" in r["mes"]
    assert "Sem quebra por inversor no BD_Performance ainda" not in r["mes"]
    assert "PR do mês" in r["kpis"] and "78,0%" in r["kpis"], "o que respondeu segue com o número dele"
    assert [a for a in r["avisos"] if a[0] == "falhou"], "a faixa do topo não acendeu"
    ok = _pagina(_rotas_hist(), "await assenta(); out({ kpis: ELS.below.innerHTML, mes: ELS['v2-mes'].innerHTML });",
                 tmp_path, search=busca)
    assert "1 abaixo da meta" in ok["kpis"] and "não respondeu" not in ok["kpis"] + ok["mes"]
    # índice de disponibilidade ainda frio: não é "fora do Fracttal"
    frio = _pagina(_rotas_hist(disp=[200, {"quente": False, "meses": []}]),
                   "await assenta(); out({ mes: ELS['v2-mes'].innerHTML });", tmp_path, search=busca)
    assert "fora do Fracttal" not in frio["mes"] and "índice ainda não montado" in frio["mes"], frio["mes"]


# ── 3. o aviso de sessão ganhou o fim do texto para a tela que lê uma vez ───────────────────────────────────────────
def test_falhou_com_fim_proprio_nao_promete_tentar_de_novo(tmp_path):
    from test_sessao_vencida_sem_numero_falso import _aviso
    r = _aviso({}, """
      const S = window.gcSessaoDaPlataforma;
      S.falhou("Fonte API PV: HTTP 504 às 14:32", "", "sem leitura nos cartões com —, não é usina parada.");
      const f1 = faixa(); S.falhou("HTTP 502", "de 14:32"); out({ f1, f2: faixa() });""", tmp_path)
    assert "Não atualizou</b> (Fonte API PV: HTTP 504 às 14:32): sem leitura nos cartões com —" in r["f1"]["html"]
    assert "Tento de novo" not in r["f1"]["html"]
    assert "os números na tela são de 14:32. Tento de novo sozinho." in r["f2"]["html"], "o texto de sempre não muda"
