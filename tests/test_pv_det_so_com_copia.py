# -*- coding: utf-8 -*-
"""O detalhe por inversor da API PV que o ciclo guarda (Levi, 19/11/2026: "Guardar o detalhe por inversor da API PV e
salvar esse cache em disco, recarregando na inicialização, para que um reinício não deixe a tabela vazia por 19 a 65 min").

O que estava medido: abrir uma usina da API PV levava de 22 a 60 s (a rota baixa o dia inteiro da fonte), e em 17/11 a
1ª tentativa de guardar o detalhe no ciclo foi desligada 21 min depois de subir, porque pedia o `plant_devices` de cada
usina dentro da volta da tabela, com a API lenta. As regras que este arquivo prova:

- o detalhe do ciclo NUNCA vai à API: leituras da volta, lista de usinas, dispositivos e combiner do que está em memória;
  faltou os dispositivos ou a lista, a usina fica sem detalhe nesta volta (a rota dela segue ao vivo) e entra na fila;
- o resultado é o MESMO da rota ao vivo com as mesmas leituras;
- há um orçamento por volta: a tabela não atrasa mais que ele por causa do detalhe;
- os dispositivos vão para o disco com as tabelas e voltam na subida;
- o detalhe vale enquanto for da tabela que está na tela (depois de um reinício o web segue servindo os dois, com a hora).
"""
import copy
import json
import threading
import time

import pytest

import app

PID, NOME = 987771, "Usina Teste Detalhe Do Ciclo"
DEVS = [{"device_id": i, "device_name": f"INVERSOR 0{i}", "device_type": "INVERTER"} for i in (1, 2)]


def _rec(inv_id, pac, correntes, ts="2026-09-24 12:00:00"):
    cj = {"Pac": pac, "Eday": 100.0, "Temp": 30.0}
    cj.update({f"Ipv{i + 1}": c for i, c in enumerate(correntes)})
    return {"idefinversor": inv_id, "tsleitura_new": ts, "conteudojson": json.dumps(cj)}


class _Resp:
    def __init__(self, d, status=200):
        self._d, self.status_code, self.headers = d, status, {}

    def json(self):
        return self._d


@pytest.fixture
def api(monkeypatch, freeze_now):
    """API PV falsa que CONTA cada ida: o detalhe do ciclo tem de terminar com a conta em zero."""
    freeze_now("2026-09-24 12:05:00")
    estado = {"recs": [_rec(i, 100.0, [8.0] * 4) for i in (1, 2)], "idas": {}}
    lock = threading.Lock()

    def _conta(nome):
        with lock:
            estado["idas"][nome] = estado["idas"].get(nome, 0) + 1

    class _Http:
        def post(self, url, **k):
            _conta("combiner" if "custom_query" in url else "day_inverter")
            return _Resp([] if "custom_query" in url else estado["recs"], 429 if "custom_query" in url else 200)

        def get(self, url, **k):
            _conta("plant_devices")
            return _Resp(copy.deepcopy(DEVS))

    def _plants(token, force=False):
        _conta("plants")
        return [{"id": PID, "nome": NOME}]
    monkeypatch.setattr(app, "_http", lambda: _Http())
    monkeypatch.setattr(app, "get_plants", _plants)
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: _conta("token") or "")
    monkeypatch.setattr(app, "_os_atribuidas_map", lambda: {})
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    monkeypatch.setattr(app, "_pv_devs_cache", {})
    monkeypatch.setattr(app, "_pv_comb_cache", {})
    monkeypatch.setattr(app, "_pv_comb_falhou", {})
    monkeypatch.setattr(app, "_plat_view_cache", {})
    monkeypatch.setattr(app, "_pv_cota", {"dia": None, "hora": None, "ts": 0.0, "zerada_ate": 0.0})
    monkeypatch.setattr(app, "_plat_combiner_strings", lambda idinv: _conta("plataforma"))
    monkeypatch.setattr(app, "_plants_cache", {"data": [{"id": PID, "nome": NOME}], "ts": 0.0})     # velha de propósito
    monkeypatch.setattr(app, "_pv_det_cache", {"ts": 0.0, "payload": None})
    monkeypatch.setattr(app, "_pv_det_faltam", set())
    monkeypatch.setattr(app, "_pv_det_prioridade", set())
    monkeypatch.setattr(app, "_pv_det_adiadas", set())
    monkeypatch.setattr(app, "_persist_mark", lambda: None)
    monkeypatch.setattr(app, "PV_DET_CICLO", True)
    monkeypatch.setitem(app.EQUIP_NAMES, NOME, {"INVERSOR 01": "Inversor 1.1", "INVERSOR 02": "Inversor 1.2"})
    monkeypatch.setitem(app.ESPERADO_INV, NOME, {"INVERSOR 01": 4, "INVERSOR 02": 4})
    app._pv_det_nova_volta()
    return estado


@pytest.fixture
def cli():
    app.app.config["TESTING"] = True
    with app.app.test_client() as c:
        yield c


def _do_ciclo(api):
    return app._pv_plant_inversores_busca(PID, force=True, records=api["recs"], so_cache=True)


def test_o_detalhe_do_ciclo_e_o_mesmo_da_rota_e_nao_vai_a_api(api):
    vivo = copy.deepcopy(app._pv_plant_inversores(PID, force=True))          # a rota: day_inverter + plants + plant_devices
    assert api["idas"].get("plant_devices") == 1 and api["idas"].get("day_inverter") == 1 and len(vivo) == 2
    api["idas"].clear()
    copia = _do_ciclo(api)
    assert api["idas"] == {}, "o detalhe do ciclo foi à API: %s" % api["idas"]
    assert copia == vivo                                                    # mesmas leituras, mesmo detalhe


def test_sem_os_dispositivos_ou_a_lista_em_memoria_o_detalhe_do_ciclo_desiste(api, monkeypatch):
    with pytest.raises(app._PvSemCopia, match="dispositivos"):
        _do_ciclo(api)
    app._pv_devs_cache[PID] = {"ts": 0.0, "devs": copy.deepcopy(DEVS)}       # de qualquer idade: nome de inversor não muda
    assert len(_do_ciclo(api)) == 2
    monkeypatch.setattr(app, "_plants_cache", {"data": None, "ts": 0.0})
    with pytest.raises(app._PvSemCopia, match="lista de usinas"):
        _do_ciclo(api)
    # a conta que não lê o plant_devices: a cópia existe e é vazia, e o detalhe sai pelo id das leituras (como na rota)
    monkeypatch.setattr(app, "_plants_cache", {"data": [{"id": PID, "nome": NOME}], "ts": 0.0})
    app._pv_devs_cache[PID] = {"ts": 0.0, "devs": []}
    assert sorted(i["id"] for i in _do_ciclo(api)) == [1, 2]
    assert api["idas"] == {}


def test_a_combiner_do_detalhe_do_ciclo_e_a_que_a_linha_acabou_de_ler(api, monkeypatch):
    monkeypatch.setattr(app, "STRING_BOX", set(app.STRING_BOX) | {NOME})
    api["recs"] = [_rec(1, 100.0, [8.0]), _rec(2, 100.0, [8.0])]             # 1 Ipv por inversor: a corrente real está na combiner
    app._pv_devs_cache[PID] = {"ts": 0.0, "devs": copy.deepcopy(DEVS)}
    assert all(i["sem_visao"] for i in _do_ciclo(api))                       # a linha também não leu: sem visão, e nenhuma chamada
    app._pv_comb_cache[PID] = {"ts": time.time(), "por_inv": {1: {"strings": [("Ipv1", 8.0), ("Ipv2", 8.1), ("Ipv3", 0.0)],
                                                                  "ts": "2026-09-24 12:00:00", "idcombiner": 9}}}
    invs = {i["id"]: i for i in _do_ciclo(api)}
    assert invs[1]["combiner"] is True and invs[1]["total_strings"] == 3 and invs[2]["sem_visao"] is True
    app._plat_view_cache[2] = {"ts": time.time(), "dados": {"strings": [("Ipv1", 7.0), ("Ipv2", 7.1)], "ts": "2026-09-24 12:00:00"}}
    invs = {i["id"]: i for i in _do_ciclo(api)}
    assert invs[2]["combiner"] is True and invs[2]["total_strings"] == 2    # sem a da API PV, a da PV Plataforma que ficou em memória
    assert api["idas"] == {}


def test_a_volta_guarda_o_detalhe_dentro_do_orcamento_e_poe_na_fila_quem_nao_tem_dispositivos(api, monkeypatch):
    app._pv_det_guarda(PID, api["recs"])                                     # sem os dispositivos em memória
    assert not (app._pv_det_cache["payload"] or {}).get("plantas") and app._pv_det_faltam == {PID}
    assert app._pv_det_volta["sem_copia"] == 1 and api["idas"] == {}
    app._pv_devs_cache[PID] = {"ts": 0.0, "devs": copy.deepcopy(DEVS)}
    app._pv_det_guarda(PID, api["recs"])
    d = app._pv_det_cache["payload"]["plantas"][str(PID)]
    assert len(d["inversores"]) == 2 and time.time() - d["ts"] < 5 and app._pv_det_volta["feitos"] == 1 and api["idas"] == {}
    assert app._pv_det_guarda(PID, []) is None and app._pv_det_guarda(PID, None) is None   # leitura vazia não gera detalhe
    # o orçamento da volta acabou: a usina fica para a seguinte, e a seguinte começa por ela
    chamadas = []
    monkeypatch.setattr(app, "_pv_plant_inversores_busca",
                        lambda pid, force=False, records=None, so_cache=False: chamadas.append((pid, force, so_cache)) or [{"id": 1}])
    monkeypatch.setitem(app._pv_det_volta, "gasto", app.PV_DET_ORCAMENTO_S)
    app._pv_det_guarda(PID + 1, api["recs"])
    assert chamadas == [] and app._pv_det_volta["adiados"] == 1
    ant = app._pv_det_nova_volta()
    assert ant["adiados"] == 1 and app._pv_det_volta["gasto"] == 0.0 and app._pv_det_volta["adiados"] == 0
    monkeypatch.setitem(app._pv_det_volta, "gasto", app.PV_DET_ORCAMENTO_S)   # estourou de novo: quem ficou para trás passa na frente
    app._pv_det_guarda(PID + 2, api["recs"])
    app._pv_det_guarda(PID + 1, api["recs"])
    assert chamadas == [(PID + 1, True, True)]
    # o detalhe que falha não derruba a linha; desligado no ambiente, o ciclo não faz nada a mais
    app._pv_det_nova_volta()

    def explode(pid, force=False, records=None, so_cache=False):
        raise RuntimeError("erro qualquer")
    monkeypatch.setattr(app, "_pv_plant_inversores_busca", explode)
    app._pv_det_guarda(PID + 3, api["recs"])
    assert str(PID + 3) not in app._pv_det_cache["payload"]["plantas"] and app._pv_det_volta["falhas"] == 1
    monkeypatch.setattr(app, "PV_DET_CICLO", False)
    app._pv_det_guarda(PID + 4, api["recs"])
    assert app._pv_det_volta["falhas"] == 1                                  # nem tentou
    assert app._persist_registry()["pv_det"] is app._pv_det_cache            # vai para o disco com as tabelas


def test_ligado_por_padrao_e_o_ambiente_desliga():
    fonte = open(app.__file__, encoding="utf-8-sig").read()
    assert 'PV_DET_CICLO = os.environ.get("PV_DET_CICLO", "1") == "1"' in fonte
    # a volta da tabela zera a conta do detalhe e não espera mais 10 min depois da subida (os dispositivos voltam do disco)
    assert "_pv_det_nova_volta()" in fonte[fonte.index("def fetch_all(fonte: str = None) -> list:"):fonte.index("# ── Drill-down: detalhe de uma usina")]
    assert "PV_DET_ESPERA_BOOT_S" not in fonte


def test_o_detalhe_vale_enquanto_for_da_tabela_que_esta_na_tela(cli, monkeypatch):
    agora = time.time()
    monkeypatch.setattr(app, "_pv_det_cache", {"ts": agora, "payload": {"plantas": {"777": {"ts": agora - 2400, "inversores": [{"id": 1}]}}}})
    monkeypatch.setattr(app, "_pv_plant_inversores", lambda pid, force=False: [{"id": 9}])
    # depois de um reinício: a tabela servida é a de 40 min atrás (a volta começou 42 min atrás) e o detalhe é dessa volta
    monkeypatch.setitem(app._cache, "ts", agora - 2380)
    monkeypatch.setitem(app._cache, "volta_ini", agora - 2520)
    r = cli.get("/api/plant/777?tabela=1").get_json()
    assert r["da_tabela"] is True and r["inversores"] == [{"id": 1}] and 2395 <= r["idade_s"] <= 2405 and len(r["lido_em"]) == 5
    # a tabela andou (outra volta começou há 4 min) e o detalhe desta usina ficou duas voltas para trás: ao vivo
    monkeypatch.setitem(app._cache, "ts", agora - 60)
    monkeypatch.setitem(app._cache, "volta_ini", agora - 240)
    assert cli.get("/api/plant/777?tabela=1").get_json() == {"plant_id": 777, "inversores": [{"id": 9}]}
    # no dia a dia: o detalhe é da volta que está na tela
    app._pv_det_cache["payload"]["plantas"]["777"]["ts"] = agora - 200
    assert cli.get("/api/plant/777?tabela=1").get_json()["da_tabela"] is True
    # ... ou da volta anterior (a usina que ficou para a seguinte por causa do orçamento)
    app._pv_det_cache["payload"]["plantas"]["777"]["ts"] = agora - 240 - app.PV_DET_FOLGA_S + 5
    assert cli.get("/api/plant/777?tabela=1").get_json()["da_tabela"] is True
    # nunca com mais de 2 h, mesmo com a tabela parada esse tempo todo
    velho = agora - app.PV_DET_TETO_S - 5
    app._pv_det_cache["payload"]["plantas"]["777"]["ts"] = velho
    monkeypatch.setitem(app._cache, "ts", velho)
    monkeypatch.setitem(app._cache, "volta_ini", velho - 100)
    assert "da_tabela" not in cli.get("/api/plant/777?tabela=1").get_json()
    # cópia de antes desta versão (sem o começo da volta): vale a hora da tabela
    app._pv_det_cache["payload"]["plantas"]["777"]["ts"] = agora - 200
    monkeypatch.setitem(app._cache, "ts", agora - 60)
    monkeypatch.delitem(app._cache, "volta_ini")
    assert cli.get("/api/plant/777?tabela=1").get_json()["da_tabela"] is True
    # sem ?tabela=1 (o Tempo real, o Diagnóstico) e com force=1, a rota segue ao vivo
    assert cli.get("/api/plant/777").get_json() == {"plant_id": 777, "inversores": [{"id": 9}]}
    assert cli.get("/api/plant/777?tabela=1&force=1").get_json() == {"plant_id": 777, "inversores": [{"id": 9}]}
    assert cli.get("/api/plant/778?tabela=1").get_json() == {"plant_id": 778, "inversores": [{"id": 9}]}


def test_os_dispositivos_vao_para_o_disco_e_voltam_na_subida(monkeypatch):
    monkeypatch.setattr(app, "_pv_devs_cache", {PID: {"ts": 1000.0, "devs": copy.deepcopy(DEVS)}, PID + 1: {"ts": 2000.0, "devs": []}})
    app._cache_save()
    salvo = json.load(open(app._PERSIST_PATH, encoding="utf-8"))["extras"]["pv_devs"]
    assert salvo[str(PID)] == {"ts": 1000.0, "devs": DEVS} and salvo[str(PID + 1)] == {"ts": 2000.0, "devs": []}
    # o processo subiu de novo, com a memória vazia (e uma usina que ele já leu mais novo)
    novo = [{"device_id": 5, "device_name": "novo", "device_type": "INVERTER"}]
    monkeypatch.setattr(app, "_pv_devs_cache", {PID + 1: {"ts": 3000.0, "devs": novo}})
    app._cache_load()
    assert app._pv_devs_cache[PID] == {"ts": 1000.0, "devs": DEVS}           # voltou, com a idade de quando foi lido (a rota ao vivo relê depois de 30 min)
    assert app._pv_devs_cache[PID + 1] == {"ts": 3000.0, "devs": novo}       # o que a memória tem de mais novo fica
    # e com eles o detalhe do ciclo já pode ser montado na 1ª volta, sem ir à API
    assert app._pv_devs_guardados(PID) == DEVS and app._pv_devs_guardados(PID + 9) is None


def test_os_dispositivos_que_faltam_sao_lidos_depois_da_tabela_poucos_por_volta(api, monkeypatch):
    fila = {PID + k for k in range(app.PV_DEVS_POR_VOLTA + 3)}
    monkeypatch.setattr(app, "_pv_det_faltam", set(fila))
    lidos = []
    monkeypatch.setattr(app, "_pv_plant_devices", lambda pid: lidos.append(pid) or [])
    monkeypatch.setattr(app, "_pv_disj_aberto", lambda: False)
    assert app._pv_devs_completa(40.0) == app.PV_DEVS_POR_VOLTA
    assert len(lidos) == app.PV_DEVS_POR_VOLTA and set(lidos) <= fila and len(app._pv_det_faltam) == 3
    # a volta da tabela foi lenta (a API PV está lenta) ou o disjuntor está aberto: nenhuma chamada a mais
    lidos.clear()
    assert app._pv_devs_completa(app.PV_DEVS_VOLTA_MAX_S + 1) == 0 and lidos == []
    monkeypatch.setattr(app, "_pv_disj_aberto", lambda: True)
    assert app._pv_devs_completa(40.0) == 0 and lidos == [] and len(app._pv_det_faltam) == 3
    # quem já está em memória sai da fila sem chamada
    monkeypatch.setattr(app, "_pv_disj_aberto", lambda: False)
    for p in list(app._pv_det_faltam):
        app._pv_devs_cache[p] = {"ts": 1.0, "devs": []}
    assert app._pv_devs_completa(40.0) == 0 and lidos == [] and app._pv_det_faltam == set()


def test_o_diario_da_largada_guarda_os_marcos_e_as_voltas(cli, monkeypatch):
    """Depois de um reinício a 1ª tabela nova levou 19, 51 e 65 min em 18/11, e de fora não dá para ver onde o tempo vai.
    O worker passa a anotar os marcos da largada e as últimas voltas da tabela; o web serve em /api/sala/largada."""
    monkeypatch.setattr(app, "_largada_cache", {"ts": 0.0, "payload": None})
    monkeypatch.setattr(app, "_persist_mark", lambda: None)
    app._largada_marca("o laço de aquecimento começou")
    app._largada_marca("tabela da API PV", saiu=True, s=118)
    p = app._largada_cache["payload"]
    assert [m["o"] for m in p["marcos"]] == ["o laço de aquecimento começou", "tabela da API PV"]
    assert all(isinstance(m["aos_s"], int) and m["aos_s"] >= 0 and len(m["as"]) == 8 for m in p["marcos"]) and p["marcos"][1]["saiu"] is True
    assert len(p["subiu_em"]) == 14 and app._largada_cache["ts"] > 0
    for k in range(15):
        app._largada_volta({"dur_s": 60 + k, "usinas": 131, "sem_dados": k})
    assert len(p["voltas"]) == 12 and p["voltas"][-1]["dur_s"] == 74 and p["voltas"][0]["dur_s"] == 63 and len(p["voltas"][-1]["fim"]) == 8
    assert app._persist_registry()["largada"] is app._largada_cache
    r = cli.get("/api/sala/largada").get_json()
    assert r["ok"] is True and r["largada"]["marcos"][0]["o"] == "o laço de aquecimento começou" and len(r["largada"]["voltas"]) == 12
    monkeypatch.setattr(app, "_largada_cache", {"ts": 0.0, "payload": None})
    assert cli.get("/api/sala/largada").get_json() == {"ok": True, "largada": None}


def test_a_volta_da_tabela_anota_o_comeco_dela_e_o_que_custou(monkeypatch):
    monkeypatch.setattr(app, "_largada_cache", {"ts": 0.0, "payload": None})
    monkeypatch.setattr(app, "_persist_mark", lambda: None)
    monkeypatch.setattr(app, "_cache", {"payload": None, "ts": 0.0})
    monkeypatch.setattr(app, "_data_refreshing", {"on": False})
    monkeypatch.setattr(app, "_build_data_payload", lambda: {"rows": [{"plant_id": 1}, {"plant_id": 2, "sem_dados": True}, {"plant_id": 3, "falha_comunicacao": True}]})
    t0 = time.time()
    app._refresh_data_cache()
    assert t0 <= app._cache["volta_ini"] <= app._cache["ts"] <= time.time()
    v = app._largada_cache["payload"]["voltas"][-1]
    assert v["usinas"] == 3 and v["sem_dados"] == 1 and v["sem_comunicacao"] == 1 and v["dur_s"] >= 0 and set(v["detalhe"]) >= {"feitos", "sem_copia", "adiados", "falhas", "gasto"}
