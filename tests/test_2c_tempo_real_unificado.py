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
    monkeypatch.setattr(app, "_owen_strings_rows", _email_proibido)
    monkeypatch.setattr(app, "_owen_strings_build", _email_proibido)
    monkeypatch.setattr(app, "_2capi_cache", {"payload": {"rows": [
        _api("Santa Cecilia 1", SC1), _api("Santa Cecilia 2", SC2, qtd_inversores=6, strings_ativas=105, str_esp=105),
        _api("Araputanga", 18771898, qtd_inversores=10, strings_ativas=236, str_esp=236)]}, "ts": 0.0})
    d = cli.get("/api/owen/strings/data").get_json()
    assert [(r["plant_id"], r["sub_fonte"]) for r in d["rows"]] == [(SC1, "api"), (SC2, "api"), (18771898, "api")]
    assert d["summary"]["total_usinas"] == 3 and d["summary"]["total_strings"] == 136 + 105 + 236


def test_sem_cache_da_api_a_tabela_fica_vazia_e_nao_cai_no_email(cli, monkeypatch):
    monkeypatch.setattr(app, "_owen_strings_rows", _email_proibido)
    monkeypatch.setattr(app, "_2capi_cache", {"payload": None, "ts": 0.0})
    d = cli.get("/api/owen/strings/data").get_json()
    assert d["rows"] == [] and d["summary"]["total_usinas"] == 0


def test_drill_de_usina_da_api_delega_ao_motor_da_api_pv(cli, monkeypatch):
    invs = [{"id": 400840, "nome": "Inversor 1.1", "strings_ativas": 17, "str_esp": 17, "diferenca": 0, "strings": []}]
    monkeypatch.setattr(app, "_pv_plant_inversores", lambda pid, force=False: invs if pid == SC1 else [])
    d = cli.get(f"/api/owen/strings/plant/{SC1}").get_json()
    assert d["plant_id"] == SC1 and d["inversores"][0]["nome"] == "Inversor 1.1" and d["sub_fonte"] == "api"


def test_etm_so_da_estacao_da_api(cli, monkeypatch):
    monkeypatch.setattr(app, "_owen_etm_build", _email_proibido)
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


def _email_de_tracker_proibido(monkeypatch):
    monkeypatch.setattr(app, "_owen_refresh", _email_proibido)       # o acervo do dia (CSV do e-mail)
    monkeypatch.setattr(app, "_hist_build", _email_proibido)         # o banco-por-dia do e-mail (2C_historico)


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
    _email_de_tracker_proibido(monkeypatch)
    _dia_api(monkeypatch, {SC3: {"TRK38": [("10:00", 12.0), ("10:05", 12.0)], "TRK1": [("10:00", 30.5)]},
                           18750925: {"TRK49": [("10:00", 28.0)]}, SC1: {"TRK50": [("10:00", 1.0)]}},
             alvos={SC3: {"TRK38": [("10:00", 31.0), ("10:05", 32.5)]}})
    t = app._owen_trackers_build()
    assert set(t) == {"IPX", "TUP"} and set(t["IPX"]) == {"2.73", "2.36"} and set(t["TUP"]) == {"2.19"}
    assert [v for _t, v in t["IPX"]["2.73"]["atual"]] == [12.0, 12.0] and t["IPX"]["2.73"]["alvo"][1][1] == 32.5
    assert t["IPX"]["2.73"]["atual"][0][0].strftime("%Y-%m-%d %H:%M") == "2026-09-30 10:00"
    assert t["IPX"]["2.36"]["alvo"] == []                                  # sem alvo na leitura: lista vazia, não inventa


def test_dia_antes_da_troca_segue_o_historico_do_email(monkeypatch, freeze_now):
    """O registro dos dias até 29/09 é o do e-mail: refazer um dia antigo não pode trocar a fonte do histórico."""
    freeze_now("2026-09-30 11:00:00")
    monkeypatch.setattr(app, "_pv_trk_dia", _email_proibido)
    monkeypatch.setattr(app, "_hist_build", lambda date: {"trackers": {"ARA": {"1.5": {"atual": [], "alvo": []}}}})
    assert app._owen_trackers_build(date="2026-09-28") == {"ARA": {"1.5": {"atual": [], "alvo": []}}}


def test_aba_de_trackers_da_2c_pela_api(cli, monkeypatch, freeze_now):
    freeze_now("2026-09-30 11:00:00")
    _email_de_tracker_proibido(monkeypatch)
    monkeypatch.setattr(app, "_owen_disp_hoje", lambda: {"IPX": 99.0})     # não grava o registro de verdade
    gira = [(f"{h:02d}:{m:02d}", -40.0 + (h - 6) * 7 + m / 10) for h in range(6, 11) for m in (0, 30)]
    _dia_api(monkeypatch, {SC1: {"TRK1": gira, "TRK2": gira}, SC2: {"TRK1": gira}})
    monkeypatch.setattr(app, "_pv_trk_payload_da_fonte", lambda fonte, force=False: {"rows": [
        {"plant_id": 18772125, "usina": "União 1 e 2", "total": 12, "parados": 0, "trackers": [{"id": "TRK1"}]},
        {"plant_id": SC1, "usina": "Santa Cecilia 1", "total": 49, "parados": 0}]})
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
