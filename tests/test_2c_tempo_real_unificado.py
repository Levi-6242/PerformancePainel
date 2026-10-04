# -*- coding: utf-8 -*-
"""Tempo Real da 2C pela API PV, sem e-mail (Levi, 29/09/2026: "Ipixuna do Pará passar a puxar da API PV matando de vez
o e-mail no tempo real!").

A Ipixuna do Pará entrou na conta oem@ como TRÊS plantas, uma por UG — Santa Cecilia 1 (18771915), 2 (18771929) e 3
(18771930) —, e com ela a 2C inteira está na API. A fonte `2c` do Monitoramento (rotas /api/owen/...) deixa de ler o
acervo do e-mail na tabela de strings, na ETM e na aba de trackers; o drill de uma usina delega ao motor da API PV.
De 11/09 a 29/09 a aba misturava as duas (`sub_fonte` "api" onde a API via, "email" no resto)."""
import pathlib

import pytest

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
SC1, SC2, SC3 = 18771915, 18771929, 18771930


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    return app.app.test_client()


def _email_proibido(*a, **k):
    raise AssertionError("o tempo real da 2C leu o acervo do e-mail")


def _api(u, pid, **kw):
    r = {"usina": u, "plant_id": pid, "qtd_inversores": 8, "strings_ativas": 136, "str_esp": 136, "diferenca": 0,
         "ultima_leitura": "2026-09-29 12:05", "sem_dados": False, "falha_comunicacao": False}
    r.update(kw)
    return r


def test_ipixuna_esta_na_fonte_da_api():
    assert {SC1, SC2, SC3} <= app.PV_FONTES["2capi"]
    assert {18771898, 18771901, 18750925, 18772125} <= app.PV_FONTES["2capi"]      # as quatro de antes seguem
    assert app._pv_fonte_de(SC2) == "2capi" and app._pv_trk_fora(SC3)


def test_de_para_dos_inversores_da_ipixuna_fechado_por_valor():
    """Eday de cada id × coluna da aba "Ipixuna do Pará" do BD, 26 a 28/09: 20 de 20 ao centésimo de kWh. A UG 01 pula
    400841 e 400842; os nomes são os do supervisório no Equipamentos, que o EQUIP_NAMES traduz."""
    assert app._pv_nome_2c(SC1, 400840) == "INVERSOR0 1.1"
    assert app._pv_nome_2c(SC1, 400843) == "INVERSOR0 1.2" and app._pv_nome_2c(SC1, 400849) == "INVERSOR0 1.8"
    assert app._pv_nome_2c(SC1, 400841) is None and app._pv_nome_2c(SC1, 400842) is None
    assert [app._pv_nome_2c(SC2, 400882 + i) for i in range(6)] == [f"INVERSOR0{i}" for i in range(1, 7)]
    assert [app._pv_nome_2c(SC3, 400888 + i) for i in range(6)] == [f"INVERSOR0{i}" for i in range(1, 7)]
    assert sum(len(app.PV_INV_NOMES[p]) for p in (SC1, SC2, SC3)) == 20


def test_de_para_casa_com_a_grafia_do_cadastro():
    """Os nomes do de-para chaveiam as esperadas: se o Equipamentos mudar a grafia ("INVERSOR0 1.1"), o inversor perde
    nome e esperada sem erro nenhum — este teste é o aviso. Só roda com o cadastro carregado."""
    if not app.EQUIP_NAMES.get("Santa Cecilia 1"):
        pytest.skip("cadastro sem as Santa Cecilia (espelho do BD_Performance ausente)")
    for pid, sup, ug in ((SC1, "Santa Cecilia 1", 1), (SC2, "Santa Cecilia 2", 2), (SC3, "Santa Cecilia 3", 3)):
        nomes = app.EQUIP_NAMES[sup]
        for inv_id, nome_api in app.PV_INV_NOMES[pid].items():
            assert nome_api in nomes, f"{sup}: {nome_api} (id {inv_id}) não está no Equipamentos"
            assert nomes[nome_api].startswith(f"Inversor {ug}."), (sup, nome_api, nomes[nome_api])
            assert app.ESPERADO_INV.get(sup, {}).get(nome_api), f"{sup}: {nome_api} sem esperadas"
    assert app.USINA_GRUPO.get("Santa Cecilia 2") == "Ipixuna do Pará"               # o macro junta as três


def test_tabela_de_strings_so_le_a_api(cli, monkeypatch):
    monkeypatch.setattr(app, "_2capi_cache", {"payload": {"rows": [
        _api("Santa Cecilia 1", SC1), _api("Santa Cecilia 2", SC2, qtd_inversores=6, strings_ativas=105, str_esp=105),
        _api("Araputanga", 18771898, qtd_inversores=10, strings_ativas=236, str_esp=236)]}, "ts": 0.0})
    d = cli.get("/api/owen/strings/data").get_json()
    assert [(r["plant_id"], r["sub_fonte"]) for r in d["rows"]] == [(SC1, "api"), (SC2, "api"), (18771898, "api")]
    assert d["summary"]["total_usinas"] == 3 and d["summary"]["total_strings"] == 136 + 105 + 236


def test_tabela_de_strings_da_2c_diz_a_hora_do_pacote_e_se_venceu(cli, monkeypatch):
    """30/09/2026, 16:20 no servidor: a tabela mostrava as leituras de 13:40 com `cache_ts` de agora e sem `stale` — a
    rota lê o pacote da 2capi desde 29/09 e continuava dizendo a hora da requisição."""
    import time as _t
    monkeypatch.setattr(app, "_2capi_cache", {"payload": {"rows": [_api("Araputanga", 18771898)],
                                                          "cache_ts": "13:46:15"}, "ts": _t.time() - 3600})
    d = cli.get("/api/owen/strings/data").get_json()
    assert d["cache_ts"] == "13:46:15" and d["stale"] is True
    monkeypatch.setattr(app, "_2capi_cache", {"payload": {"rows": [_api("Araputanga", 18771898)],
                                                          "cache_ts": "16:19:00"}, "ts": _t.time() - 60})
    d = cli.get("/api/owen/strings/data").get_json()
    assert d["cache_ts"] == "16:19:00" and d["stale"] is False


def test_sem_cache_da_api_a_tabela_fica_vazia_e_nao_cai_no_email(cli, monkeypatch):
    monkeypatch.setattr(app, "_2capi_cache", {"payload": None, "ts": 0.0})
    d = cli.get("/api/owen/strings/data").get_json()
    assert d["rows"] == [] and d["summary"]["total_usinas"] == 0


def test_drill_de_usina_da_api_delega_ao_motor_da_api_pv(cli, monkeypatch):
    invs = [{"id": 400840, "nome": "Inversor 1.1", "strings_ativas": 17, "str_esp": 17, "diferenca": 0, "strings": []}]
    monkeypatch.setattr(app, "_pv_plant_inversores", lambda pid, force=False: invs if pid == SC1 else [])
    d = cli.get(f"/api/owen/strings/plant/{SC1}").get_json()
    assert d["plant_id"] == SC1 and d["inversores"][0]["nome"] == "Inversor 1.1" and d["sub_fonte"] == "api"


def test_etm_so_da_estacao_da_api(cli, monkeypatch):
    linha = lambda u, pid, sev: {"usina": u, "plant_id": pid, "severidade": sev, "flags": [], "sensores": {},
                                 "spark": {"labels": [], "poa": [], "ghi": []}, "sem_dados": False, "sem_curva": False}
    monkeypatch.setattr(app, "_2capi_etm_analise_cache", {"payload": {"rows": [
        linha("Santa Cecilia 1", SC1, 1), linha("Araputanga", 18771898, 3)]}, "ts": 0.0})
    d = cli.get("/api/owen/etm/analise").get_json()
    assert [(r["plant_id"], r["sub_fonte"]) for r in d["rows"]] == [(SC1, "api"), (18771898, "api")]   # pior primeiro
    assert d["summary"]["total"] == 2 and d["summary"]["atencao"] == 1


# ── trackers: o dado da API com o nome do e-mail (30/09/2026) ─────────────────────────────────────────────────────
def _dia_api(monkeypatch, curvas, alvos=None):
    """_pv_trk_dia falso: {pid: {"TRKk": [("HH:MM", ângulo)]}} no formato do cache da API fixa (com o alvo da 2C)."""
    def falso(pid, data_br, fetch=True):
        dd = f"{data_br[6:]}-{data_br[3:5]}-{data_br[:2]}"
        pts = lambda m: {trk: [{"x": f"{dd} {h}", "y": v} for h, v in ser] for trk, ser in (m.get(pid) or {}).items()}
        return {"curva": pts(curvas), "alvo": pts(alvos or {}), "ultima": {}, "ultima_ts": None}
    monkeypatch.setattr(app, "_pv_trk_dia", falso)
    app._2c_trk_api_memo.clear()


def test_de_para_de_tracker_fechado_pela_curva():
    """Posição de cada tracker do e-mail × cada um da API, minuto a minuto, em 28/09 (e 27/09 na ARA e na STL): os 340
    pares da regra com diferença média ≤ 0,5°, e os parados no mesmo ângulo. O prefixo não é a UG: na Ipixuna o grupo 2
    atravessa a UG 02 (Santa Cecilia 2) e a UG 03 (Santa Cecilia 3)."""
    assert app._2c_trk_para_api("IPX", "Tracker 1.49") == (SC1, 49)
    assert app._2c_trk_para_api("IPX", "Tracker 2.35") == (SC2, 35) and app._2c_trk_para_api("IPX", "2.36") == (SC3, 1)
    assert app._2c_trk_para_api("IPX", "Tracker 2.73") == (SC3, 38)          # o do ticket no inversor 3.06
    assert app._2c_trk_para_api("IPX", "Tracker 1.50") is None and app._2c_trk_para_api("IPX", "TRK5") is None
    assert app._2c_trk_para_api("TUP", "Tracker 2.19") == (18750925, 49) and app._2c_trk_para_api("TUP", "3.22") == (18750925, 82)
    assert app._2c_trk_para_api("ARA", "Tracker 1.44") == (18771898, 44) and app._2c_trk_para_api("STL", "1.59") == (18771901, 59)
    assert app._2c_trk_da_api(SC3, "TRK38") == ("IPX", "2.73") and app._2c_trk_da_api(18750925, "TRK49") == ("TUP", "2.19")
    assert app._2c_trk_da_api(SC1, "TRK50") is None
    nomes = [(c, f"{g}.{n}") for c, g, a, b, _p, _d in app._2C_TRK_FAIXAS for n in range(a, b + 1)]
    ida = {x: app._2c_trk_para_api(*x) for x in nomes}
    assert len(nomes) == 340 and len(set(ida.values())) == 340                 # um para um
    assert all(app._2c_trk_da_api(p, f"TRK{k}") == x for x, (p, k) in ida.items())


def test_trackers_de_hoje_vem_da_api_com_o_nome_do_email(monkeypatch, freeze_now):
    freeze_now("2026-09-30 11:00:00")
    _dia_api(monkeypatch, {SC3: {"TRK38": [("10:00", 12.0), ("10:05", 12.0)], "TRK1": [("10:00", 30.5)]},
                           18750925: {"TRK49": [("10:00", 28.0)]}, SC1: {"TRK50": [("10:00", 1.0)]}},
             alvos={SC3: {"TRK38": [("10:00", 31.0), ("10:05", 32.5)]}})
    t = app._owen_trackers_build()
    assert set(t) == {"IPX", "TUP"} and set(t["IPX"]) == {"2.73", "2.36"} and set(t["TUP"]) == {"2.19"}
    assert [v for _t, v in t["IPX"]["2.73"]["atual"]] == [12.0, 12.0] and t["IPX"]["2.73"]["alvo"][1][1] == 32.5
    assert t["IPX"]["2.73"]["atual"][0][0].strftime("%Y-%m-%d %H:%M") == "2026-09-30 10:00"
    assert t["IPX"]["2.36"]["alvo"] == []                                  # sem alvo na leitura: lista vazia, não inventa


def test_aba_de_trackers_da_2c_pela_api(cli, monkeypatch, freeze_now):
    freeze_now("2026-09-30 11:00:00")
    monkeypatch.setattr(app, "_owen_disp_hoje", lambda: {"IPX": 99.0})     # não grava o registro de verdade
    gira = [(f"{h:02d}:{m:02d}", -40.0 + (h - 6) * 7 + m / 10) for h in range(6, 11) for m in (0, 30)]
    _dia_api(monkeypatch, {SC1: {"TRK1": gira, "TRK2": gira}, SC2: {"TRK1": gira}})
    monkeypatch.setattr(app, "_2c_trk_cache", {"payload": None, "ts": 0.0})
    monkeypatch.setattr(app, "_2c_disp_memo", {"ts": 0.0, "disp": {}})
    monkeypatch.setattr(app, "get_token", lambda *a, **k: "t")
    monkeypatch.setattr(app, "get_plants", lambda *a, **k: [{"id": 18772125, "nome": "União "}])
    monkeypatch.setattr(app, "_pv_trackers_analise", lambda pid, nome, **kw: {
        "plant_id": pid, "usina": nome, "total": 12, "parados": 0, "tem_trackers": True, "trackers": [{"id": "TRK1"}]})
    monkeypatch.setattr(app, "_pv_trk_payload_da_fonte", _email_proibido)   # não monta a 2capi inteira p/ usar a União
    monkeypatch.setattr(app, "_trk_eventos_disp_by_id", lambda ini, fim: {})
    d = cli.get("/api/owen/trackers").get_json()
    por = {r["plant_id"]: r for r in d["rows"]}
    assert set(por) == {"ARA", "IPX", "STL", "TUP", 18772125}               # a Ipixuna é UMA; a Santa Cecilia não repete
    assert por["IPX"]["total"] == 3 and por["IPX"]["usina"] == "Ipixuna do Pará" and por["IPX"]["sub_fonte"] == "api"
    assert por["IPX"]["disponibilidade_tempo"] == 99.0 and por["ARA"]["total"] == 0
    assert all("trackers" not in r for r in d["rows"])
    drill = cli.get("/api/owen/trackers/IPX").get_json()
    assert sorted(t["id"] for t in drill["trackers"]) == ["Tracker 1.1", "Tracker 1.2", "Tracker 2.1"]


def test_parados_da_2c_levam_o_ticket_e_dizem_quando_a_api_esta_fora(monkeypatch, freeze_now):
    freeze_now("2026-09-30 11:00:00")
    base = {"usina": "Ipixuna do Pará", "plant_id": "IPX", "total": 122, "ultima_leitura": "2026-09-30 10:58",
            "trackers": [{"id": "Tracker 2.73", "status": "parado", "na_planilha": True, "ticket_status": "Parado"},
                         {"id": "Tracker 1.1", "status": "normal"}]}
    monkeypatch.setattr(app, "OWEN_UFVS", {"IPX": "Ipixuna do Pará"})
    monkeypatch.setattr(app, "_owen_trackers_analise", lambda code, date=None: dict(base))
    monkeypatch.setattr(app, "_trk_parado_desde_hist", lambda *a, **k: None)
    monkeypatch.setattr(app, "_trk_geo_annotate", lambda rows: rows)
    err = {}
    rows = app._owen_parados_rows(errout=err)
    assert [(r["tracker"], r["ticket_status"], r["na_planilha"]) for r in rows] == [("Tracker 2.73", "Parado", True)]
    assert not err
    monkeypatch.setattr(app, "_owen_trackers_analise", lambda code, date=None: dict(base, total=0, trackers=[]))
    err = {}
    assert app._owen_parados_rows(errout=err) == [] and err.get("erro")      # de dia, vazio é a fonte fora
    freeze_now("2026-09-30 22:00:00")
    err = {}
    assert app._owen_parados_rows(errout=err) == [] and not err              # de noite, vazio é a noite


def test_o_dia_da_api_so_guarda_o_alvo_quando_pedem():
    reg = [{"tsleitura": "2026-09-30 10:00:00",
            "conteudojson": {"Trackers": [{"TRK1": {"posAg": 10.0, "posAl": 12.5}}]}}]
    assert "alvo" not in app._pv_trk_parse_dia(reg)                         # a Thopen não carrega o alvo furado
    d = app._pv_trk_parse_dia(reg, com_alvo=True)
    assert d["alvo"]["TRK1"] == [{"x": "2026-09-30 10:00", "y": 12.5}] and d["curva"]["TRK1"][0]["y"] == 10.0


def test_front_tem_uma_aba_so_para_a_2c():
    mon = (RAIZ / "docs/redesign/Monitoramento (novo design).html").read_text(encoding="utf-8")
    assert "id:'2capi'" not in mon                                         # o seletor não oferece a aba separada
    assert "'2c':'2C (API PV Operation)'" in mon
    assert "{id:'2c',icon:'ph ph-solar-panel',name:'2C',sub:'API PV Operation'}" in mon     # o chip não diz mais "Email"
    assert "_ehApiPv(" in mon                                             # linha numérica da 2C → curva/ETM pela API PV
    ent = (RAIZ / "docs/redesign/Entrada.html").read_text(encoding="utf-8")
    assert '"2C · API PV"' not in ent


def test_parados_da_api_pv_nao_listam_as_usinas_da_2c(monkeypatch):
    """Com a aba de trackers da 2C aberta, as usinas dela entram no _pv_trk_plant; os parados delas já chegam pela fonte
    2C, e a lista da API PV os repetia — o mesmo tracker duas vezes na Entrada e na ronda (docs/tempo-real.md, 15.2)."""
    t = {"id": "TRK5", "status": "parado", "atual": 0.0, "alvo": 30.0}
    monkeypatch.setattr(app, "_pv_trk_plant", {
        111: {"ts": 0, "payload": {"tem_trackers": True, "usina": "Colorado 2", "trackers": [dict(t)]}},
        SC1: {"ts": 0, "payload": {"tem_trackers": True, "usina": "Santa Cecilia 1", "trackers": [dict(t)]}}})
    monkeypatch.setattr(app, "get_token", lambda *a, **k: "t")
    monkeypatch.setattr(app, "get_plants", lambda *a, **k: [{"id": 111, "nome": "Colorado 2"},
                                                             {"id": SC1, "nome": "Santa Cecilia 1"}])
    monkeypatch.setattr(app, "_TRACKER_WATCH_OK", False)
    monkeypatch.setattr(app, "_trk_parado_desde_hist", lambda *a, **k: None)
    monkeypatch.setattr(app, "_bd_trk_lookup", lambda *a, **k: "")
    monkeypatch.setattr(app, "_trk_geo_annotate", lambda rows: rows)
    assert [r["plant_id"] for r in app._pv_parados_rows()] == [111]


# ── o dia de tracker da 2C fica quente no worker (_2c_trk_loop, 30/09/2026) ───────────────────────────────────────
def test_o_laco_renova_o_dia_antes_de_vencer(monkeypatch):
    """Frio, os parados da 2C levavam 51 s e a Entrada dá 30 s a cada fonte: o laço renova 2 min antes de vencer."""
    import time as _t
    from datetime import datetime as _dt
    agora = _dt(2026, 9, 30, 10, 0)
    br = "30/09/2026"
    cache = {(SC1, br): {"ts": _t.time(), "d": {"curva": {"TRK1": []}}},
             (SC2, br): {"ts": _t.time() - (app.TRK_DIA_TTL - 60), "d": {"curva": {"TRK1": []}}}}
    monkeypatch.setattr(app, "_pv_trk_dia_cache", cache)
    monkeypatch.setattr(app, "_2c_trk_vazio", {})
    pedidos = []
    monkeypatch.setattr(app, "_pv_trk_dia", lambda pid, data, fetch=True: pedidos.append(pid) or {"curva": {"TRK1": []}})
    ren = app._2c_trk_renova_dias(agora)
    assert SC1 not in ren and SC2 in ren and SC3 in ren and 18771898 in ren          # a fresca fica, as outras renovam
    assert cache[(SC2, br)]["ts"] == 0.0                                             # venceu sem ser apagada
    assert sorted(ren) == sorted(pedidos)


def test_renovar_nao_troca_o_dia_bom_por_vazio_quando_a_api_falha(monkeypatch):
    import time as _t
    from datetime import datetime as _dt
    hoje = _dt.now().strftime("%d/%m/%Y")
    bom = {"curva": {"TRK1": [{"x": "10:00", "y": 12.0}]}, "ultima": {}, "ultima_ts": None}
    monkeypatch.setattr(app, "_pv_trk_dia_cache", {(SC1, hoje): {"ts": _t.time(), "d": bom}})

    class _Fora:
        def post(self, *a, **k):
            raise ConnectionError("API PV fora")
    monkeypatch.setattr(app, "_http", lambda: _Fora())
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "t")
    app._2c_trk_vence(SC1, hoje)
    assert app._pv_trk_dia(SC1, hoje, fetch=True) is bom                            # a busca falhou: fica o de antes


def test_dia_ainda_vazio_nao_e_pedido_a_cada_minuto(monkeypatch):
    from datetime import datetime as _dt
    monkeypatch.setattr(app, "_pv_trk_dia_cache", {})
    monkeypatch.setattr(app, "_2c_trk_vazio", {})
    pedidos = []
    monkeypatch.setattr(app, "_pv_trk_dia", lambda pid, data, fetch=True: pedidos.append(pid) or {"curva": {}})
    agora = _dt(2026, 9, 30, 6, 5)
    primeira = app._2c_trk_renova_dias(agora)
    assert len(primeira) == 6 and len(pedidos) == 6
    assert app._2c_trk_renova_dias(agora) == [] and len(pedidos) == 6                # vazio: espera 5 min


# ── a aba de trackers da 2C é montada no worker e servida pronta (30/09/2026, 14:42: a tela desistia aos 90 s) ─────
def test_a_aba_da_2c_e_servida_pronta_pelo_web(cli, monkeypatch):
    import time as _t
    monkeypatch.setattr(app, "_owen_trackers_analise", _email_proibido)       # o web não monta
    monkeypatch.setattr(app, "_2c_trk_build_api", _email_proibido)
    ipx = {"usina": "Ipixuna do Pará", "plant_id": "IPX", "total": 122, "parados": 5,
           "trackers": [{"id": "Tracker 2.73", "status": "parado"}]}
    monkeypatch.setattr(app, "_2c_trk_cache", {"ts": _t.time(), "payload": {
        "rows": [dict(ipx, trackers=None)], "summary": {"trackers": 122, "parados": 5}, "cache_ts": "14:40:00",
        "por_codigo": {"IPX": ipx}}})
    d = cli.get("/api/owen/trackers").get_json()
    assert "por_codigo" not in d and d["summary"]["parados"] == 5 and d["stale"] is False
    drill = cli.get("/api/owen/trackers/IPX").get_json()
    assert drill["trackers"][0]["id"] == "Tracker 2.73"


def test_disponibilidade_da_2c_no_maximo_a_cada_30_min(monkeypatch):
    """Recalcular a disponibilidade refaz as ocorrências do dia e grava o trk_eventos.json (26 MB, no OneDrive)."""
    chamadas = []
    monkeypatch.setattr(app, "_2c_disp_memo", {"ts": 0.0, "disp": {}})
    monkeypatch.setattr(app, "OWEN_UFVS", {"IPX": "Ipixuna do Pará"})
    monkeypatch.setattr(app, "_owen_trackers_analise", lambda code, date=None: {"usina": "Ipixuna do Pará", "plant_id": code,
                                                                                "total": 1, "trackers": []})
    monkeypatch.setattr(app, "_owen_disp_hoje", lambda: chamadas.append(1) or {"IPX": 98.0})
    monkeypatch.setattr(app, "PV_FONTES", dict(app.PV_FONTES, **{"2capi": {f[4] for f in app._2C_TRK_FAIXAS}}))
    a = app._build_2c_trk_payload()
    b = app._build_2c_trk_payload()
    assert len(chamadas) == 1 and a["rows"][0]["disponibilidade_tempo"] == b["rows"][0]["disponibilidade_tempo"] == 98.0


# ── a curva das strings da 2C pela API PV (30/09/2026, Levi: "as UFVs da 2C não carregam a curva em curva das strings") ──
def _node_curva(js):
    import json as _json
    import shutil as _sh
    import subprocess as _sp
    node = _sh.which("node")
    if not node:
        pytest.skip("node não instalado")
    mon = (RAIZ / "docs/redesign/Monitoramento (novo design).html").read_text(encoding="utf-8")

    def _linha(nome):
        i = mon.index(f"function {nome}(")
        return mon[i:mon.index("\n", i) + 1]
    i = mon.index("async function loadCurvaView(")
    base = (_linha("_ehApiPv") + _linha("_brData") + mon[i:mon.index("\n}\n", i) + 3]
            + "const state={curvaData:'2026-09-30'}; const RD={curvaView:{}}; let _f='owen'; const _fonte=()=>_f;"
              "const render=()=>{}; const _todayISO=()=>'2026-09-30'; const _abaixoMeta=()=>({abaixo:new Set()});"
              "const urls=[]; async function fetchJSON(u){ urls.push(u);"
              " if(u.startsWith('/api/spv/')) return {inversores:[{id:400840,nome:'INVERSOR0 1.1',"
              "curva:{'ST 01':{x:['10:00'],y:[5]}},strings:[]}]};"
              " return {inversores:[{inv:'1.1',labels:['10:00'],strings:[{id:'1',y:[5]}]}]}; }")
    p = _sp.run([node, "-e", base + js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return _json.loads(p.stdout)


def test_curva_das_strings_da_2c_com_id_da_api_vem_da_api_pv():
    """Desde 30/09 as usinas da 2C chegam à Curva das strings com o id da API (Santa Cecilia 1 = 18771915); a rota do
    e-mail só conhece ARA/STL/TUP/IPX e devolvia 0 inversores — "Sem curva de strings para esta usina"."""
    r = _node_curva("(async()=>{ await loadCurvaView('18771915'); await loadCurvaView('ARA'); _f='semp';"
                    " await loadCurvaView('18750001');"
                    " process.stdout.write(JSON.stringify({urls,"
                    " sc1:RD.curvaView['owen|18771915|2026-09-30'].map(i=>[i.nome,Object.keys(i.curva)]),"
                    " ara:RD.curvaView['owen|ARA|2026-09-30'].map(i=>i.nome)})); })();")
    assert r["urls"] == ["/api/spv/usina/18771915?full=1&data=30/09/2026",
                         "/api/spv/usina/18750001?full=1&data=30/09/2026"]    # a SEMP nem tinha ramo
    # o código do e-mail (ARA) não tem mais curva: o e-mail da 2C saiu do código em 03/10/2026
    assert r["sc1"] == [["INVERSOR0 1.1", ["ST 01"]]]
    assert r["ara"] == []


def test_csv_da_curva_da_2c_com_id_da_api(monkeypatch):
    hoje = app.datetime.now().strftime("%Y-%m-%d")
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "t")
    monkeypatch.setattr(app, "get_token", lambda *a, **k: "t")
    monkeypatch.setattr(app, "get_plants", lambda *a, **k: [{"id": SC1, "nome": "Santa Cecilia 1"}])
    monkeypatch.setattr(app, "_pv_curvas_strings", lambda pid, nome, tok: {"INVERSOR0 1.1": {"Ipv1": [("10:00", 5.0)]}})
    rows, unidade = app._strings_curva_longo("owen", str(SC1), hoje)
    assert rows == [("INVERSOR0 1.1", "Ipv1", "10:00", 5.0)] and unidade == "corrente_A"


# ── os parados da 2C saem do pacote do worker (30/09/2026: a Entrada ficou "de 14:48" a tarde inteira) ─────────────
# A régua de parado sobre o dia inteiro da API (leitura a cada minuto, 340 trackers) leva de 25 a 45 s por chamada; a
# Entrada dá 30 s a cada fonte. O worker já faz essa conta para a aba (_build_2c_trk_payload) e publica a análise.
def _pacote(monkeypatch, dia="2026-09-30", idade_s=60):
    import time as _t
    ipx = {"usina": "Ipixuna do Pará", "plant_id": "IPX", "total": 122, "ultima_leitura": "2026-09-30 10:58",
           "trackers": [{"id": "Tracker 2.73", "status": "parado", "na_planilha": True, "ticket_status": "Parado"},
                        {"id": "Tracker 1.1", "status": "normal"}]}
    monkeypatch.setattr(app, "_2c_trk_cache", {"ts": _t.time() - idade_s, "payload": {
        "rows": [dict(ipx, trackers=None)], "summary": {}, "cache_ts": "10:59:00", "dia": dia,
        "por_codigo": {"IPX": ipx}}})
    monkeypatch.setattr(app, "OWEN_UFVS", {"IPX": "Ipixuna do Pará"})
    monkeypatch.setattr(app, "_trk_parado_desde_hist", lambda *a, **k: None)
    monkeypatch.setattr(app, "_trk_geo_annotate", lambda rows: rows)


def test_parados_da_2c_saem_do_pacote_do_worker(cli, monkeypatch, freeze_now):
    freeze_now("2026-09-30 11:00:00")
    _pacote(monkeypatch)
    monkeypatch.setattr(app, "_owen_trackers_analise", _email_proibido)      # não refaz a régua
    err = {}
    rows = app._owen_parados_rows(errout=err)
    assert [(r["tracker"], r["ticket_status"], r["na_planilha"]) for r in rows] == [("Tracker 2.73", "Parado", True)]
    assert not err
    d = cli.get("/api/owen/trackers/parados").get_json()
    assert d["total"] == 1 and d["rows"][0]["tracker"] == "Tracker 2.73"


def test_pacote_velho_ou_de_outro_dia_refaz_a_analise(monkeypatch, freeze_now):
    freeze_now("2026-09-30 11:00:00")
    feitas = []
    for kw in ({"idade_s": 31 * 60}, {"dia": "2026-09-29"}):
        _pacote(monkeypatch, **kw)
        monkeypatch.setattr(app, "_owen_trackers_analise", lambda code, date=None: feitas.append(code) or {
            "usina": "Ipixuna do Pará", "plant_id": code, "total": 1, "trackers": []})
        assert app._owen_parados_rows() == []
    assert feitas == ["IPX", "IPX"]


def test_ronda_com_force_refaz_a_analise_mesmo_com_pacote(monkeypatch, freeze_now):
    freeze_now("2026-09-30 11:00:00")
    _pacote(monkeypatch)
    feitas = []
    monkeypatch.setattr(app, "_2c_trk_build_api", lambda date_iso, force=False: {})
    monkeypatch.setattr(app, "_owen_trackers_analise", lambda code, date=None: feitas.append(code) or {
        "usina": "Ipixuna do Pará", "plant_id": code, "total": 1, "trackers": []})
    app._owen_parados_rows(force=True)
    assert feitas == ["IPX"], "a ronda quer a leitura de agora"


def test_pacote_da_aba_diz_o_dia(monkeypatch, freeze_now):
    freeze_now("2026-09-30 11:00:00")
    monkeypatch.setattr(app, "OWEN_UFVS", {})
    monkeypatch.setattr(app, "_2c_disp_memo", {"ts": 9e18, "disp": {}})
    monkeypatch.setattr(app, "PV_FONTES", dict(app.PV_FONTES, **{"2capi": {f[4] for f in app._2C_TRK_FAIXAS}}))
    assert app._build_2c_trk_payload()["dia"] == "2026-09-30"


# ── o web não monta a aba da 2C (30/09/2026, 15:07: montou sozinho em 104 s e publicou tudo zerado) ──────────────────
def test_web_sem_pacote_da_aba_da_2c_responde_carregando(cli, monkeypatch):
    monkeypatch.setattr(app, "_MODO_WEB", True)
    monkeypatch.setattr(app, "_2c_trk_cache", {"payload": None, "ts": 0.0})
    monkeypatch.setattr(app, "_build_2c_trk_payload", _email_proibido)
    for url in ("/api/owen/trackers", "/api/owen/trackers?force=1"):
        d = cli.get(url).get_json()
        assert d["carregando"] is True and d["rows"] == []
    assert app._2c_trk_cache["payload"] is None, "o carregando não vira pacote"


def test_web_com_pacote_serve_o_pacote_mesmo_no_atualizar(cli, monkeypatch):
    import time as _t
    monkeypatch.setattr(app, "_MODO_WEB", True)
    monkeypatch.setattr(app, "_build_2c_trk_payload", _email_proibido)
    monkeypatch.setattr(app, "_2c_trk_cache", {"ts": _t.time() - 400, "payload": {
        "rows": [{"plant_id": "IPX", "total": 122}], "summary": {"trackers": 122}, "cache_ts": "10:00:00",
        "por_codigo": {"IPX": {}}}})
    d = cli.get("/api/owen/trackers?force=1").get_json()
    assert d["summary"]["trackers"] == 122 and d["stale"] is True and "por_codigo" not in d


def test_dia_vazio_da_api_nao_fica_no_memo(monkeypatch, freeze_now):
    """A API sem resposta devolve o dia vazio; guardado no memo, os 4 códigos da aba saíam zerados no mesmo minuto."""
    freeze_now("2026-09-30 11:00:00")
    monkeypatch.setattr(app, "_2c_trk_api_memo", {})
    dias = iter([{}] * 6 + [{"curva": {"TRK1": [{"x": "2026-09-30 10:00", "y": 12.0}]}}] * 6)
    monkeypatch.setattr(app, "_pv_trk_dia", lambda pid, data, fetch=True: next(dias))
    assert app._2c_trk_build_api("2026-09-30") == {}
    assert app._2c_trk_build_api("2026-09-30")["ARA"]["1.1"]["atual"][0][1] == 12.0
