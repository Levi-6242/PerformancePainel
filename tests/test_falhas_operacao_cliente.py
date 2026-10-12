# -*- coding: utf-8 -*-
"""Operação no Mês do Dashboard Thopen (Levi, 08/10/2026): o que a aba de falhas publica para o 5080 contar strings e
trackers DISTINTOS por usina, sem zero falso.

- "quando fica parado sem comunicação essa ocorrência é ignorada; se a usina comunicou inversor ou string então aí
  conta" → `dias_comunicou` em cada episódio de tracker (comunicou = a régua de strings leu produção da usina no dia,
  em qualquer fonte e cadastro dela, ou a geração do dia é > 0);
- usina sem linha nos episódios não é "usina sem falha": a aba `cobertura` (mês × fonte × plant_id) diz quem foi medido;
- Brodowski são dois cadastros na API PV → `plant_id` nas abas de episódio (sem ele, 52 em vez de 103).

Revisão de 08/10, à tarde (retorno da análise de performance, decisões do Levi): "Strings é OS" — a aba `strings_os` lista as OS de
recomposição de string do Fracttal pela DATA DO EVENTO, com a quantidade da linha "Strings sem corrente: N (...)" que o
OS Creator vai escrever, das strings citadas ou, em outubro, estimada pela régua; e a aba `trackers_dia` dá, por usina e
dia, os trackers parados com a usina comunicando (ou no dia corrente, ainda sem prova).
"""
import json
from datetime import datetime

import pytest

import app
import falhas_job
import falhas_publicar as pub
import sol

PID = "18748739"          # Inhapi na API PV (cadastro real, como no test_falhas_job)


def trk(**por_dia):
    """trk(d01=(status, desvio), ...) → o formato do trk_eventos.json, um tracker só."""
    out = {}
    for k, (status, desvio) in por_dia.items():
        evs = [{"tracker": "TRK1", "parada": "08:00", "retorno": None, "desvio": desvio}] if status == "parado" else []
        out[f"2026-09-{k[1:]}"] = {PID: {"nome": "Inhapi", "cobertura": 1.0, "classes": {"TRK1": {"status": status}},
                                          "eventos": evs}}
    return out


def registro(*dias, vivas=24, usina="Inhapi", pid=PID, fonte="pv"):
    """falhas_strings.json: a régua de strings leu a usina nesses dias (com produção quando há vivas)."""
    return {f"2026-09-{d}": {fonte: {pid: {"usina": usina, "ts": 0, "mortas": [],
                                           "vivas": {"Inversor 3.3": vivas} if vivas else {}}}} for d in dias}


def monta(trk_store, mortas=None, geracao=None, fim="2026-09-03", agora=datetime(2026, 9, 30, 12, 0), desc=None,
          pv_dev=None, antes=None, ini="2026-09-01"):
    return falhas_job.montar(app, sol, ini, fim, geracao=geracao or {}, str_store={}, trk_store=trk_store,
                             book={}, hist_2c=lambda dia: {}, mortas_curva=mortas or {}, log=lambda m: None,
                             agora=agora, desconsideradas=desc, pv_dev=pv_dev, abertos_antes=antes)


def test_tracker_parado_com_a_usina_lendo_strings_conta_os_dias_em_que_ela_comunicou():
    (r,) = monta(trk(d01=("parado", 35.0), d02=("parado", 35.0)), mortas=registro("01", "02"))["trackers"]["rows"]
    assert r["dias_comunicou"] == 2


def test_tracker_parado_com_a_usina_muda_tem_zero_dias_de_comunicacao():
    (r,) = monta(trk(d01=("parado", 35.0), d02=("parado", 35.0)))["trackers"]["rows"]
    assert r["dias_comunicou"] == 0


def test_registro_de_madrugada_sem_producao_nao_e_comunicacao():
    (r,) = monta(trk(d01=("parado", 35.0)), mortas=registro("01", vivas=None))["trackers"]["rows"]
    assert r["dias_comunicou"] == 0


def test_geracao_do_dia_tambem_prova_que_a_usina_comunicou():
    u = app._macro_usina_nome("Inhapi") or "Inhapi"
    ger = {u: {"kwp": 1000.0, "dias": {"2026-09-01": 4500.0}}}
    (r,) = monta(trk(d01=("parado", 35.0), d02=("parado", 35.0)), geracao=ger)["trackers"]["rows"]
    assert r["dias_comunicou"] == 1


def test_outro_cadastro_da_mesma_usina_prova_a_comunicacao():
    # Brodowski, out/2026: a metade 297381 não tem registro de strings, a 297378 (mesma usina) tem todo dia
    (r,) = monta(trk(d01=("parado", 35.0)), mortas=registro("01", pid="999", fonte="pvsb"))["trackers"]["rows"]
    assert r["dias_comunicou"] == 1


def test_usina_sem_regua_de_strings_que_para_hoje_fica_sem_prova_e_nao_sem_comunicacao():
    # Barretos, Céu Azul, Ceilândia 1 e Cidade Gaucha (out/2026) não têm string lida: o registro passa por elas com
    # vivas e mortas vazias, e a única prova é a geração, que o BD_Thopen grava 0 no dia corrente até o fechamento. Em
    # 08/10 às 15:00, 72 episódios Thopen do dia (69 da Barretos, 3 da Matão 2) saíam com dias_comunicou = 0 e o 5080
    # mostrava "0" na Matão 2 com 1 tracker parado (zero falso). O dia que ainda não fechou não prova nem desmente:
    # vai à parte, em dias_sem_prova — contar ou avisar é decisão do 5080 (Levi)
    u = app._macro_usina_nome("Inhapi") or "Inhapi"
    sem_strings = registro("01", "02", vivas=None)
    aberto = {u: {"kwp": 1000.0, "dias": {"2026-09-01": 4500.0, "2026-09-02": 0.0}}}
    (r,) = monta(trk(d02=("parado", 35.0)), mortas=sem_strings, geracao=aberto, fim="2026-09-02",
                 agora=datetime(2026, 9, 2, 15, 0))["trackers"]["rows"]
    assert (r["dias_comunicou"], r["dias_sem_prova"]) == (0, 1)
    # o fechamento gravou a geração do dia: o mesmo episódio passa a ter a prova, e nada fica sem veredito
    fechado = {u: {"kwp": 1000.0, "dias": {"2026-09-01": 4500.0, "2026-09-02": 32373.7}}}
    (r,) = monta(trk(d02=("parado", 35.0)), mortas=sem_strings, geracao=fechado, fim="2026-09-02",
                 agora=datetime(2026, 9, 3, 1, 0))["trackers"]["rows"]
    assert (r["dias_comunicou"], r["dias_sem_prova"]) == (1, 0)
    # no dia corrente com a régua de strings lendo produção (a Matão 2 em 06 e 07/10), a prova vale na hora
    (r,) = monta(trk(d02=("parado", 35.0)), mortas=registro("02"), fim="2026-09-02",
                 agora=datetime(2026, 9, 2, 15, 0))["trackers"]["rows"]
    assert (r["dias_comunicou"], r["dias_sem_prova"]) == (1, 0)


def test_mes_fechado_nao_tem_dia_sem_prova():
    (r,) = monta(trk(d01=("parado", 35.0), d02=("parado", 35.0)))["trackers"]["rows"]
    assert (r["dias_comunicou"], r["dias_sem_prova"]) == (0, 0)


def test_dia_que_a_geracao_ainda_nao_cobre_fica_sem_prova_mesmo_ja_passado():
    # revisão adversarial de 11/10/2026: às 00:05 a geração em uso é a que a Disponibilidade buscou às 23:50 — cortada no
    # D-1 do relógio DELA, vai só até anteontem. Pelo relógio, ontem já tinha "fechado": a usina sem string lida (Céu
    # Azul e Ceilândia 1 não têm leitura de string em outubro) saía com 0 dia de comunicação E 0 sem prova, o dia sumia
    # do trackers_dia e o 5080 tirava o tracker do card — toda noite, até a 1ª volta da Disponibilidade depois da
    # meia-noite (até 3 h com a varredura do Fracttal falhando). Fechado é o dia que a geração JÁ cobre
    u = app._macro_usina_nome("Inhapi") or "Inhapi"
    sem_strings = registro("01", "02", vivas=None)
    as_23_50 = {u: {"kwp": 1000.0, "dias": {"2026-09-01": 4500.0}}}
    p = monta(trk(d02=("parado", 35.0)), mortas=sem_strings, geracao=as_23_50, fim="2026-09-03",
              agora=datetime(2026, 9, 3, 0, 5))
    (r,) = p["trackers"]["rows"]
    assert (r["dias_comunicou"], r["dias_sem_prova"]) == (0, 1)
    assert _td(p) == [("2026-09-02", "pv", PID, "TRK1", 1, "sem prova")]
    # a geração do dia chega (a volta da Disponibilidade depois da meia-noite): o dia ganha o veredito
    com_o_dia = {u: {"kwp": 1000.0, "dias": {"2026-09-01": 4500.0, "2026-09-02": 4400.0}}}
    p = monta(trk(d02=("parado", 35.0)), mortas=sem_strings, geracao=com_o_dia, fim="2026-09-03",
              agora=datetime(2026, 9, 3, 0, 35))
    (r,) = p["trackers"]["rows"]
    assert (r["dias_comunicou"], r["dias_sem_prova"]) == (1, 0)
    assert _td(p) == [("2026-09-02", "pv", PID, "TRK1", 1, "sim")]
    # a geração já cobre o dia (outra usina gerou nele) e esta não gerou: não comunicou, e a ocorrência é ignorada
    parada = {u: {"kwp": 1000.0, "dias": {"2026-09-01": 4500.0, "2026-09-02": 0.0}},
              "Matão 2": {"kwp": 1000.0, "dias": {"2026-09-01": 4000.0, "2026-09-02": 4100.0}}}
    p = monta(trk(d02=("parado", 35.0)), mortas=sem_strings, geracao=parada, fim="2026-09-03",
              agora=datetime(2026, 9, 3, 0, 35))
    (r,) = p["trackers"]["rows"]
    assert (r["dias_comunicou"], r["dias_sem_prova"]) == (0, 0)
    assert _td(p) == []


def test_cobertura_diz_quem_foi_medido_no_mes_mesmo_sem_falha():
    p = monta(trk(d01=("normal", None), d02=("parado", 35.0)), mortas=registro("01", "02", "03"))
    (c,) = [x for x in p["cobertura"] if x["plant_id"] == PID]
    assert (c["fonte"], c["dias_strings"], c["dias_trackers"], c["dias_comunicou"]) == ("pv", 3, 2, 3)
    assert c["usina"] and c["cliente"] == p["trackers"]["rows"][0]["cliente"]
    assert c["primeiro_dia"] == "2026-09-01"


def test_so_entra_na_cobertura_quem_foi_medido_no_periodo():
    # o "0" do dashboard tem de ser medido. Não são "medida sem falha": o registro de madrugada sem nada gerando, o
    # dia fora do período, o tracker lido sem classificar, o tracker sem cobertura e a usina que só aparece na geração
    m = registro("01")                                                                       # Inhapi: medida
    m["2026-09-01"]["pv"]["111"] = {"usina": "Altair", "ts": 0, "mortas": [], "vivas": {}}
    m["2026-08-31"] = {"pv": {"222": {"usina": "Assis", "ts": 0, "mortas": [], "vivas": {"Inversor 1.1": 24}}}}
    t = {"2026-09-01": {"333": {"nome": "Brodowski", "cobertura": 1.0, "classes": None, "eventos": []},
                        "444": {"nome": "Barretos", "cobertura": 0.0, "classes": {}, "eventos": []}}}
    ger = {"Matão 2": {"kwp": 1000.0, "dias": {"2026-09-01": 4500.0}}}
    p = monta(t, mortas=m, geracao=ger)
    assert {x["plant_id"] for x in p["cobertura"]} == {PID}


def test_a_2c_le_a_curva_pela_api_pv_e_ela_tambem_prova_a_comunicacao_e_a_cobertura():
    # a 2C não passa pelo registro de strings (falhas_strings.json): a curva dela vem do hist_2c (dias_2c). No registro
    # real de outubro os trackers da 2C usam o MESMO código das strings (ARA, IPX, STL, TUP) — sem a curva dela, todo
    # tracker parado da 2C no dia corrente (a geração é D-1) sairia "usina muda" e as strings dela, sem cobertura
    serie = [(f"{h:02d}:{m:02d}", 8.0) for h in range(7, 17) for m in (0, 10, 20, 30, 40, 50)]
    t = {"2026-09-01": {"TUP": {"nome": "Tupi Paulista", "cobertura": 1.0, "classes": {"TRK1": {"status": "parado"}},
                                "eventos": [{"tracker": "TRK1", "parada": "08:00", "retorno": None, "desvio": 35.0}]}}}
    p = falhas_job.montar(app, sol, "2026-09-01", "2026-09-01", geracao={}, str_store={}, trk_store=t, book={},
                          hist_2c=lambda dia: {"strings": {"TUP": {"1.1": {f"{i}": serie for i in range(1, 5)}}}},
                          mortas_curva={}, log=lambda m: None, agora=datetime(2026, 9, 30, 12, 0))
    (r,) = p["trackers"]["rows"]
    assert r["dias_comunicou"] == 1
    (c,) = p["cobertura"]
    assert (c["fonte"], c["plant_id"], c["dias_strings"], c["dias_trackers"], c["dias_comunicou"]) == \
        ("owen", "TUP", 1, 1, 1)


# ══ a fonte do tracker pelo cadastro, não pelo tamanho do id (revisão adversarial de 11/10/2026) ═══════════════════════
# O registro de trackers (trk_eventos.json) é um store só das quatro fontes, chaveado pelo plant_id, e não dizia de qual
# fonte cada usina era: a montagem chutava pelo tamanho do id (até 5 dígitos = Banco). A API PV tem cadastro de 5
# dígitos — no PC (01 a 11/10), 29: Indaiatuba 1 a 4 (21480–21483), Embu Guaçu, Nova Londrina, Altair, Ceilândia II e 1,
# Céu Azul, Tanabi, Mandaguaçu e Canarana — e eles saíam "Thopen · Banco" nos trackers; a cobertura de outubro tinha 32
# plant_ids em duas linhas, cada uma com um 0 falso. O Banco vai de 1 a 34.
INDAIATUBA_1 = "21480"     # Indaiatuba 1 na API PV (está no falhas_pv_dev.json do PC)


def trk_de(pid, nome, *dias, fonte=None, status="parado"):
    """O registro de trackers de um cadastro, um tracker parado nos dias de setembro dados; `fonte` = o campo que os
    gravadores do app passam a escrever em 11/10/2026 (None = registro de antes)."""
    out = {}
    for d in dias:
        e = {"nome": nome, "cobertura": 1.0, "classes": {"TRK1": {"status": status}},
             "eventos": [{"tracker": "TRK1", "parada": "08:00", "retorno": None, "desvio": 35.0}]
             if status == "parado" else []}
        if fonte:
            e["fonte"] = fonte
        out[f"2026-09-{d}"] = {pid: e}
    return out


def test_cadastro_da_api_pv_de_5_digitos_e_api_pv_nos_trackers_e_numa_linha_so_da_cobertura():
    # o caso medido: Indaiatuba 1 em outubro saía ('Thopen · Banco', 21480) com 0 dia de strings e 3 de trackers e
    # ('Thopen · API PV', 21480) com 10 e 0 — o Banco nem tem esse cadastro
    p = monta(trk_de(INDAIATUBA_1, "Indaiatuba 1 (131)", "01", "02"),
              mortas=registro("01", "02", "03", usina="Indaiatuba 1", pid=INDAIATUBA_1))
    (r,) = p["trackers"]["rows"]
    assert r["fonte"] == "pv"
    assert [(x["fonte"], x["plant_id"]) for x in p["trackers_dia"]] == [("pv", INDAIATUBA_1)] * 2
    (c,) = [x for x in p["cobertura"] if x["plant_id"] == INDAIATUBA_1]
    assert (c["fonte"], c["dias_strings"], c["dias_trackers"]) == ("pv", 3, 2)


def test_a_fonte_vem_do_de_para_da_api_pv_ou_da_que_o_registro_gravou():
    # sem leitura de string nenhuma: o de-para da API PV (plant_devices) diz que o 21480 é dela
    p = monta(trk_de(INDAIATUBA_1, "Indaiatuba 1 (131)", "01"), pv_dev={INDAIATUBA_1: {"usina": "Indaiatuba 1"}})
    assert p["trackers"]["rows"][0]["fonte"] == "pv"
    # sem de-para e sem string: o registro de trackers grava a fonte desde 11/10/2026 (os gravadores do app)
    p = monta(trk_de("60006", "Céu Azul I (102)", "01", fonte="pv"))
    assert p["trackers"]["rows"][0]["fonte"] == "pv"
    # o Banco segue Banco: Guaratinguetá V é o 26 do Banco, e o registro de strings o lê em "pg"
    p = monta(trk_de("26", "Guaratinguetá V", "01"), mortas=registro("01", usina="Guaratinguetá V", pid="26", fonte="pg"))
    assert p["trackers"]["rows"][0]["fonte"] == "pg"
    (c,) = [x for x in p["cobertura"] if x["plant_id"] == "26"]
    assert c["fonte"] == "pg"
    # e sem prova nenhuma vale o tamanho do id, como antes
    assert monta(trk_de("21999", "Sem Cadastro", "01"))["trackers"]["rows"][0]["fonte"] == "pg"


def test_a_chave_da_ocorrencia_continua_a_de_antes_e_a_desconsiderada_segue_fora():
    # a chave é o que o analista desconsidera (falhas_desconsideradas.json) e o que a tela devolve: o 21480 entrou nela
    # como "pg|21480|...". Mudar a chave junto com a fonte devolveria à aba as ocorrências que ele já tirou
    desc = {"trackers": {falhas_job.chave_trk("pg", INDAIATUBA_1, "TRK1", "2026-09-01")}}
    p = monta(trk_de(INDAIATUBA_1, "Indaiatuba 1 (131)", "01"), desc=desc,
              mortas=registro("01", usina="Indaiatuba 1", pid=INDAIATUBA_1))
    assert p["trackers"]["rows"] == [] and p["trackers_dia"] == []
    (d,) = p["trackers"]["desconsideradas"]
    assert (d["chave"], d["fonte"]) == (falhas_job.chave_trk("pg", INDAIATUBA_1, "TRK1", "2026-09-01"), "pv")


def test_o_parado_que_vem_do_mes_anterior_montado_com_a_fonte_antiga_leva_o_desde():
    # setembro foi montado com o 21480 como Banco e não é remontado: o "desde" de outubro casa pelo plant_id e o tracker
    antes = {"strings": {}, "trackers": {("pg", INDAIATUBA_1, "TRK1"): "2026-09-25 14:00"}}
    t = {"2026-10-01": {INDAIATUBA_1: {"nome": "Indaiatuba 1 (131)", "cobertura": 1.0,
                                       "classes": {"TRK1": {"status": "parado"}},
                                       "eventos": [{"tracker": "TRK1", "parada": "06:30", "retorno": None,
                                                    "desvio": 35.0}]}}}
    p = monta(t, ini="2026-10-01", fim="2026-10-01", agora=datetime(2026, 10, 1, 12, 0), antes=antes,
              pv_dev={INDAIATUBA_1: {"usina": "Indaiatuba 1"}})
    (r,) = p["trackers"]["rows"]
    assert (r["fonte"], r["desde"]) == ("pv", "2026-09-25 14:00")


def test_string_box_e_a_mesma_usina_da_api_pv_e_a_cobertura_e_uma_linha():
    # Brodowski 297378: strings pela String Box (pvsb — a mesma usina da API PV, guardada em outra chave só para um
    # registro não apagar o outro) e trackers pela API PV. Eram duas linhas: (pvsb, 11 de strings, 0 de trackers) e
    # (pv, 0, 11) — os dois zeros sem medição nenhuma
    m = registro("01", "02", "03", usina="Brodowski", pid="297378", fonte="pvsb")
    m["2026-09-02"]["pv"] = {"297378": {"usina": "Brodowski", "ts": 0, "mortas": [], "vivas": {"Inversor 1.1": 20}}}
    p = monta(trk_de("297378", "Brodowski", "01", "02"), mortas=m)
    (c,) = [x for x in p["cobertura"] if x["plant_id"] == "297378"]
    assert (c["fonte"], c["dias_strings"], c["dias_trackers"]) == ("pv", 3, 2)


def test_regua_que_nao_registrou_o_cadastro_no_mes_e_vazio_e_nao_zero():
    # 0 na cobertura é "olhou e não houve leitura". A usina que a régua de trackers nem registrou no mês (sem tracker
    # monitorado) tem os trackers NÃO MEDIDOS — vazio; a que a régua de strings registra sem produção (Céu Azul e
    # Ceilândia 1: o registro passa por elas com vivas e mortas vazias) tem 0 de verdade
    so_strings = monta({}, mortas=registro("01", "02"))
    (c,) = so_strings["cobertura"]
    assert (c["dias_strings"], c["dias_trackers"]) == (2, None)
    so_trackers = monta(trk_de("60006", "Céu Azul I (102)", "01", "02", fonte="pv"))
    (c,) = so_trackers["cobertura"]
    assert (c["fonte"], c["dias_strings"], c["dias_trackers"]) == ("pv", None, 2)
    sem_producao = monta(trk_de("60006", "Céu Azul I (102)", "01", "02", fonte="pv"),
                         mortas=registro("01", "02", usina="Céu Azul I", pid="60006", vivas=None))
    (c,) = sem_producao["cobertura"]
    assert (c["fonte"], c["dias_strings"], c["dias_trackers"]) == ("pv", 0, 2)
    # o tracker lido sem classificar (cobertura < 0,5) também foi olhado: 0, não vazio
    lido = {"2026-09-01": {"60006": {"nome": "Céu Azul I (102)", "cobertura": 0.3, "classes": None, "eventos": [],
                                      "fonte": "pv"}}}
    p = monta(lido, mortas=registro("01", usina="Céu Azul I", pid="60006"))
    (c,) = p["cobertura"]
    assert (c["dias_strings"], c["dias_trackers"]) == (1, 0)


def test_os_quatro_gravadores_do_registro_de_trackers_dizem_a_fonte(monkeypatch):
    # "o registro de trackers passar a gravar a fonte" (revisão de 11/10): o store é um só para as quatro fontes e o
    # plant_id sozinho não diz de quem é
    dia = "2026-09-29"
    store = {}
    monkeypatch.setattr(app, "_trk_eventos", store)
    monkeypatch.setattr(app, "_trk_ev_save", lambda: None)
    monkeypatch.setattr(app, "_trk_eventos_do_dia", lambda *a, **k: {"eventos": [], "classes": {}, "cobertura": 1.0})
    # Banco da Thopen
    monkeypatch.setattr(app, "_pg_curve_for", lambda *a, **k: {})
    monkeypatch.setattr(app, "_pg_ev_cache", {})
    app._pg_eventos_calc(dia, ov_rows=[{"plant_id": 26, "usina": "Guaratinguetá V"}])
    # 2C
    monkeypatch.setattr(app, "_2c_codigos", lambda: ["TUP"])
    monkeypatch.setattr(app, "_owen_curve_for", lambda *a, **k: {})
    monkeypatch.setattr(app, "_owen_ev_cache", {})
    app._owen_eventos_calc(dia)
    # Athon e Axis (SunOp)
    monkeypatch.setattr(app, "ensure_sunop_meta", lambda inst="gridco": None)
    monkeypatch.setattr(app, "_sunop_meta_monitorada", lambda inst="gridco": {
        ("MAB100" if inst == "gridco" else "AXS100"): {"trackers": {"TRK_1": {}}}})
    monkeypatch.setattr(app, "_sunop_trk_curvas_varias", lambda *a, **k: None)
    monkeypatch.setattr(app, "_sunop_curve_for", lambda *a, **k: {})
    monkeypatch.setattr(app, "_sunop_ev_cache", {"gridco": {}, "axis": {}})
    app._sunop_eventos_calc("gridco", dia)
    app._sunop_eventos_calc("axis", dia)
    # API PV
    monkeypatch.setattr(app, "_swr", lambda *a, **k: {})
    monkeypatch.setattr(app, "_pv_trk_itens", lambda: [("18748739", {"payload": {"total": 3, "usina": "Inhapi"}})])
    monkeypatch.setattr(app, "_trk_ev_prog", {"running": False})
    app._trk_ev_backfill(dia, dia)
    assert {pid: e.get("fonte") for pid, e in store[dia].items()} == {
        "26": "pg", "TUP": "owen", "MAB100": "sunop", "AXS100": "axis", "18748739": "pv"}


# ══ trackers_dia: a ocorrência de tracker por usina e dia (análise de performance, 08/10: "esperam algo sobre dias") ══
def _td(p):
    return [(t["dia"], t["fonte"], t["plant_id"], t["trackers"], t["qtd"], t["comunicou"]) for t in p["trackers_dia"]]


def test_tracker_dia_so_entra_no_dia_em_que_a_usina_comunicou():
    # parado nos dias 01 e 02; a usina só leu string no dia 01. No 02 ela ficou muda (mês fechado: não é "sem prova"),
    # e o Levi: "quando fica parado sem comunicação essa ocorrência é ignorada"
    p = monta(trk(d01=("parado", 35.0), d02=("parado", 35.0)), mortas=registro("01"))
    assert _td(p) == [("2026-09-01", "pv", PID, "TRK1", 1, "sim")]


def test_tracker_dia_no_dia_corrente_sem_prova_entra_como_sem_prova():
    # a usina sem string lida que para hoje: a geração do dia corrente é 0 até o fechamento (Barretos, 08/10) — o dia
    # entra, avisado, e não some como "usina muda" (decisão do orquestrador: o dia sem prova conta)
    u = app._macro_usina_nome("Inhapi") or "Inhapi"
    aberto = {u: {"kwp": 1000.0, "dias": {"2026-09-01": 4500.0, "2026-09-02": 0.0}}}
    p = monta(trk(d02=("parado", 35.0)), mortas=registro("01", "02", vivas=None), geracao=aberto, fim="2026-09-02",
              agora=datetime(2026, 9, 2, 15, 0))
    assert _td(p) == [("2026-09-02", "pv", PID, "TRK1", 1, "sem prova")]


def test_tracker_desconsiderado_nao_entra_no_tracker_dia():
    desc = {"trackers": {falhas_job.chave_trk("pv", PID, "TRK1", "2026-09-01")}}
    p = monta(trk(d01=("parado", 35.0)), mortas=registro("01"), desc=desc)
    assert p["trackers"]["rows"] == [] and p["trackers_dia"] == []


def test_tracker_dia_junta_os_trackers_da_mesma_usina_no_dia():
    t = trk(d01=("parado", 35.0))
    t["2026-09-01"][PID]["classes"]["TRK12"] = {"status": "parado"}
    t["2026-09-01"][PID]["eventos"].append({"tracker": "TRK12", "parada": "09:00", "retorno": None, "desvio": 40.0})
    t["2026-09-01"][PID]["classes"]["TRK3"] = {"status": "parado"}
    t["2026-09-01"][PID]["eventos"].append({"tracker": "TRK3", "parada": "10:00", "retorno": None, "desvio": 40.0})
    p = monta(t, mortas=registro("01"), fim="2026-09-01")
    assert _td(p) == [("2026-09-01", "pv", PID, "TRK1, TRK3, TRK12", 3, "sim")]       # ordem natural (3 antes de 12)


# ══ strings_os: as OS de recomposição de string do Fracttal, pela data do evento ══════════════════════════════════════
COD = "INP100"            # o Código Fractal da Inhapi (Info Geral); fixado no teste para não depender do cadastro


@pytest.fixture
def cod_inhapi(monkeypatch):
    monkeypatch.setattr(app, "USINA_COD", {**app.USINA_COD, "inhapi": COD})


def os_str(folio, evento, inv="3.3", qtd=None, lista=(), cit=(), prefixo="THPN", status="Em andamento"):
    """Uma OS do índice que a varredura da Disponibilidade publica (app._falhas_os_string)."""
    code = f"{prefixo}-{COD}-INVR{inv}" if prefixo else f"{COD}-INVR{inv}"
    return {"os": folio, "code": code, "prefixo": prefixo, "cb": COD, "inv": inv, "evento": evento, "status": status,
            "qtd_texto": qtd, "strings_texto": list(lista), "cit": list(cit)}


def morta(st, saiu="07:00", inv="Inversor 3.3"):
    """Uma string da régua nova sobre a curva (falhas.avaliar_dia), que já leu corrente antes (não é entrada vazia)."""
    return {"inversor": inv, "string": st, "saiu": saiu, "voltou": None, "min_morta": 600, "trechos": [[saiu, None]],
            "criterio": {"zerada": 600, "abaixo_das_vizinhas": 0}, "ini_producao": "06:30", "fim_producao": "17:30",
            "sempre_zero": False}


def regua(dia, *mortas, vivas=22):
    return {dia: {"pv": {PID: {"usina": "Inhapi", "ts": 0, "mortas": list(mortas), "vivas": {"Inversor 3.3": vivas}}}}}


def monta_os(oss, ini="2026-10-01", fim="2026-10-08", mortas=None, agora=datetime(2026, 10, 8, 20, 0)):
    return falhas_job.montar(app, sol, ini, fim, geracao={}, str_store={}, trk_store={}, book={},
                             hist_2c=lambda dia: {}, mortas_curva=mortas or {}, log=lambda m: None, agora=agora,
                             os_string=oss)


def _so(p):
    return {o["os"]: o for o in p["strings_os"]}


def test_os_com_a_linha_strings_sem_corrente_vale_o_que_ela_diz(cod_inhapi):
    # o contrato com o OS Creator (Levi, 08/10): "Strings sem corrente: 4 (Ipv3, Ipv7, Ipv11, Ipv12)"
    (o,) = monta_os([os_str("15150", "2026-10-02", qtd=4, lista=(3, 7, 11, 12), cit=(3, 7, 11, 12))])["strings_os"]
    assert (o["data_evento"], o["usina"], o["inversor"], o["os"], o["qtd"], o["strings"], o["origem"]) == \
        ("2026-10-02", app._macro_usina_nome("Inhapi") or "Inhapi", "Inversor 3.3", "15150", 4,
         "Ipv3, Ipv7, Ipv11, Ipv12", "texto")
    assert o["cliente"] == "Thopen" and o["status"] == "Em andamento"


def test_a_quantidade_da_linha_vale_mesmo_sem_a_lista(cod_inhapi):
    (o,) = monta_os([os_str("1", "2026-10-02", qtd=3)])["strings_os"]
    assert (o["qtd"], o["strings"], o["origem"]) == (3, None, "texto")


def test_os_so_com_strings_citadas_conta_as_citadas(cod_inhapi):
    # "[Inversor 3.3] - Recomposição de String" + "Strings Ipv11 e Ipv12 sem corrente" no texto, sem a linha nova
    (o,) = monta_os([os_str("2", "2026-10-03", cit=(11, 12))])["strings_os"]
    assert (o["qtd"], o["strings"], o["origem"]) == (2, "Ipv11, Ipv12", "citadas")


def test_os_de_outubro_sem_nada_leva_as_strings_que_a_regua_viu_no_dia_do_evento(cod_inhapi):
    # Levi, 08/10: "adapte todas desse mês, do nosso lado, sem tocar no Fracttal". A régua da aba (2 h seguidas sem
    # corrente) viu a Ipv13 e a Ipv16 do Inversor 3.3 no dia 06; o dia 05 (outra string) não é o do evento
    m = {**regua("2026-10-05", morta("Ipv20")), **regua("2026-10-06", morta("Ipv16"), morta("Ipv13"))}
    (o,) = monta_os([os_str("3", "2026-10-06")], mortas=m)["strings_os"]
    assert (o["qtd"], o["strings"], o["origem"], o["plant_id"]) == (2, "Ipv13, Ipv16", "estimado", PID)


def test_estimativa_sem_string_vista_no_dia_fica_sem_quantidade_e_nunca_zero(cod_inhapi):
    (o,) = monta_os([os_str("4", "2026-10-07")], mortas=regua("2026-10-07"))["strings_os"]
    assert (o["qtd"], o["strings"], o["origem"]) == (None, None, "sem_quantidade")


def test_estimativa_so_olha_o_inversor_da_os(cod_inhapi):
    m = regua("2026-10-06", morta("Ipv13", inv="Inversor 3.4"))
    m["2026-10-06"]["pv"][PID]["vivas"]["Inversor 3.4"] = 22
    (o,) = monta_os([os_str("5", "2026-10-06")], mortas=m)["strings_os"]
    assert (o["qtd"], o["origem"]) == (None, "sem_quantidade")


def test_os_de_novembro_sem_quantidade_fica_vazia_mesmo_com_a_regua_vendo_strings(cod_inhapi):
    # a estimativa é só para outubro, aberto antes de o OS Creator escrever a linha: depois, quem não escreve fica sem
    # número — a tela avisa, nunca soma 0
    m = regua("2026-11-03", morta("Ipv13"))
    (o,) = monta_os([os_str("6", "2026-11-03")], ini="2026-11-01", fim="2026-11-05", mortas=m,
                    agora=datetime(2026, 11, 5, 20, 0))["strings_os"]
    assert (o["qtd"], o["strings"], o["origem"]) == (None, None, "sem_quantidade")


def test_os_com_evento_fora_do_mes_nao_entra(cod_inhapi):
    oss = [os_str("7", "2026-09-30", qtd=2), os_str("8", "2026-10-01", qtd=1), os_str("9", "2026-11-01", qtd=1)]
    assert set(_so(monta_os(oss))) == {"8"}


def test_os_da_2c_nao_vira_usina_da_thopen_com_o_mesmo_codigo(cod_inhapi):
    # a Ipixuna é IPX100 na Thopen e 2CIPX100 na 2C ("2C-IPX100-INVR1.1"): pelo código solto, a OS da 2C cairia na
    # usina da Thopen e entraria no dashboard do cliente errado
    (o,) = monta_os([os_str("10", "2026-10-02", qtd=2, prefixo="2C")])["strings_os"]
    assert o["usina"] is None and o["cliente"] is None


def test_os_sem_prefixo_no_codigo_acha_a_usina_pelo_codigo(cod_inhapi):
    # Guaratinguetá V: "GTA500-INVR1.3" (OS 15150), sem o THPN- na frente
    (o,) = monta_os([os_str("11", "2026-10-02", qtd=1, prefixo=None)])["strings_os"]
    assert o["usina"] == (app._macro_usina_nome("Inhapi") or "Inhapi")


def test_os_de_dois_inversores_sai_em_duas_linhas_com_a_mesma_os(cod_inhapi):
    # a OS 13585 da Altair (seis inversores numa OS): uma linha por inversor, cada uma com as strings dele
    oss = [os_str("13585", "2026-10-02", inv="3.4", cit=(5,)), os_str("13585", "2026-10-02", inv="3.3", cit=(3, 11, 12))]
    l = monta_os(oss)["strings_os"]
    assert [(o["os"], o["inversor"], o["qtd"], o["strings"]) for o in l] == [
        ("13585", "Inversor 3.3", 3, "Ipv3, Ipv11, Ipv12"), ("13585", "Inversor 3.4", 1, "Ipv5")]


def test_sem_o_indice_do_fracttal_o_pacote_nao_tem_a_aba(cod_inhapi):
    # índice ainda não publicado (logo depois do deploy) ≠ "nenhuma OS no mês": sem a chave, a contagem fica vazia
    assert "strings_os" not in monta_os(None)
    assert monta_os([])["strings_os"] == []


# ── o índice das OS de string, tirado da varredura que a Disponibilidade já faz (app._falhas_os_string) ───────────────
def _tarefa(desc, note="", code="THPN-GTA500-INVR1.3", evento="2026-10-01T12:00:00+00:00", st=1, task_note=""):
    return {"description": desc, "note": note, "task_note": task_note, "code": code, "event_date": evento,
            "id_status_work_order": st, "creation_date": "2026-10-01T19:44:00+00:00"}


def test_indice_le_a_linha_das_observacoes_e_o_dia_do_evento_em_brasilia():
    wos = {"15150": [_tarefa("[Inversor 1.3] - Recomposição de String",
                             note="Strings sem corrente: 4 (Ipv3, Ipv7, Ipv11, Ipv12)",
                             evento="2026-10-01T02:30:00+00:00")],          # 23:30 de 30/09 em Brasília
           "15151": [_tarefa("[Inversor 1.4] - Recomposição de String", note="Strings Ipv11 e Ipv12 sem corrente",
                             code="GTA500-INVR1.4", st=2)],
           "15152": [_tarefa("[Inversor 1.5] - Recomposição de String", st=4)],                  # cancelada
           "15153": [_tarefa("Religamento da usina", code="THPN-GTA500-CABN1")]}                 # não é de string
    idx = {o["os"]: o for o in app._falhas_os_string(wos)}
    assert set(idx) == {"15150", "15151"}
    a, b = idx["15150"], idx["15151"]
    assert (a["evento"], a["cb"], a["inv"], a["prefixo"], a["qtd_texto"], a["strings_texto"]) == \
        ("2026-09-30", "GTA500", "1.3", "THPN", 4, [3, 7, 11, 12])
    assert (b["evento"], b["prefixo"], b["inv"], b["qtd_texto"], b["cit"], b["status"]) == \
        ("2026-10-01", None, "1.4", None, [11, 12], "Concluída")
    assert not any(k in a for k in ("note", "task_note", "description", "tecnico"))   # texto livre não vai ao índice


def test_os_de_varios_inversores_vira_uma_linha_por_inversor_com_as_strings_de_cada_um():
    # OS 13585 (Altair, evento 01/09): uma OS, seis tarefas, uma por inversor, e cada task_note cita as strings do SEU
    # inversor ("Investigar strings PV3, PV11 e PV12" no 2.8, "Investigar string PV5" no 2.6). Numa linha só, as
    # citações se misturavam e o inversor ficava o da 1ª tarefa. A nota da OS é a mesma em todas e não diz de qual
    # inversor fala: numa OS de vários inversores ela não entra na conta de nenhum (o N seria somado uma vez por inversor)
    nota = "Strings sem corrente: 9 (Ipv1, Ipv2)"
    wos = {"13585": [_tarefa("Recomposição de String", note=nota, code="ALT100-INVR2.8",
                             task_note="Investigar strings PV3, PV11 e PV12"),
                     _tarefa("Recomposição de String", note=nota, code="ALT100-INVR2.6",
                             task_note="Investigar string PV5")]}
    idx = {o["inv"]: o for o in app._falhas_os_string(wos)}
    assert set(idx) == {"2.8", "2.6"} and {o["os"] for o in idx.values()} == {"13585"}
    assert (idx["2.8"]["cit"], idx["2.6"]["cit"]) == ([3, 11, 12], [5])
    assert idx["2.8"]["qtd_texto"] is None and idx["2.6"]["qtd_texto"] is None


def test_os_de_um_inversor_le_a_linha_na_nota_da_os():
    (o,) = app._falhas_os_string({"1": [_tarefa("[Inversor 1.3] - Recomposição de String",
                                                note="Strings sem corrente: 2 (Ipv5, Ipv6)",
                                                task_note="Verificar strings sem corrente. Realizar recomposição.")]})
    assert (o["qtd_texto"], o["strings_texto"], o["cit"]) == (2, [5, 6], [5, 6])


def test_frase_solta_strings_sem_corrente_nao_e_quantidade():
    # OS 15087 (Castelo do Piauí): "Verificar strings sem corrente. Realizar recomposição." — sem o número, não é a linha
    (o,) = app._falhas_os_string({"15087": [_tarefa("[Inversor 2.7] - Recomposição de String", code="GY-CDP100-INVR2.7",
                                                    note="Verificar strings sem corrente. Realizar recomposição.")]})
    assert (o["qtd_texto"], o["cit"], o["prefixo"]) == (None, [], "GY")


def test_recomposicao_que_nao_e_de_string_fica_fora():
    # "[INHAPI] Recomposição da alimentação da ETM" (OS 15308) e "Inspeção e recomposição de cabos CC": o índice das OS
    # abertas (só "recomposi") as pegaria
    wos = {"15308": [_tarefa("[INHAPI] Recomposição da alimentação da ETM", code="THPN-INP100-ESTM1")],
           "2": [_tarefa("Inspeção e recomposição de cabos CC")]}
    assert app._falhas_os_string(wos) == []


def test_indice_le_a_linha_em_qualquer_texto_da_os_e_sem_acento():
    wos = {"1": [_tarefa("[Inversor 2.1] - Recomposicao de String", task_note="STRINGS SEM CORRENTE: 2",
                         code="2C-IPX100-INVR2.1")]}
    (o,) = app._falhas_os_string(wos)
    assert (o["qtd_texto"], o["strings_texto"], o["prefixo"], o["cb"], o["inv"]) == (2, [], "2C", "IPX100", "2.1")


def test_a_varredura_da_disponibilidade_guarda_as_observacoes_da_os():
    assert {"note", "task_note", "description", "event_date", "code"} <= set(app._DISP_CAMPOS_TASK)


def test_o_mes_le_o_indice_publicado_pela_disponibilidade(monkeypatch, tmp_path):
    arq = tmp_path / "frac_disp_index.json"
    monkeypatch.setattr(app, "_FRAC_DISP_FILE", str(arq))
    monkeypatch.setattr(app, "_frac_disp_mem", {"mtime": 0.0, "dados": {}})
    assert app._falhas_os_string_indice() is None                       # sem índice: não publicado
    arq.write_text(json.dumps({"ts": 1, "meses": {}, "os_string": [{"os": "1"}]}), encoding="utf-8")
    assert app._falhas_os_string_indice() == [{"os": "1"}]


# ══ o workbook falhas_performance (falhas_publicar): colunas novas só no FIM; abas `cobertura`, `strings_os`, `trackers_dia`
ANTES = {"strings_episodios": ["mes", "fonte", "cliente", "usina", "inversor", "string", "saiu", "voltou", "situacao",
                               "dias", "horas_sol", "perda_kwh", "perda_inferida_kwh", "kwp_string", "metodo", "avisos"],
         "trackers_episodios": ["mes", "fonte", "cliente", "usina", "tracker", "inversor", "parou", "voltou", "situacao",
                                "horas_sol", "desvio_pico_graus", "fator_perda", "kwp_tracker", "perda_kwh", "cronico",
                                "avisos"],
         "atualizacao": ["mes", "periodo_inicio", "periodo_fim", "atualizado_em", "strings_inversor_dia",
                         "strings_episodios", "trackers_episodios", "regua_strings", "regua_trackers"]}


def _pac():
    return {"mes": "2026-10", "gerado_em": "2026-10-08 10:05", "periodo": ["2026-10-01", "2026-10-08"], "regua": {},
            "strings": {"rows": [], "episodios": [
                {"fonte": "pv", "plant_id": "297378", "cliente": "Thopen", "usina": "Brodowski",
                 "inversor": "Inversor 2.1", "string": "Ipv3", "inicio": "2026-10-02 07:00", "fim": None, "flags": []}]},
            "trackers": {"rows": [
                {"fonte": "pv", "plant_id": "297381", "cliente": "Thopen", "usina": "Brodowski", "tracker": "TRK1",
                 "inicio": "2026-10-01 08:00", "fim": None, "dias_comunicou": 3, "dias_sem_prova": 1, "flags": []}]},
            "cobertura": [{"fonte": "pv", "plant_id": "297378", "usina": "Brodowski", "cliente": "Thopen",
                           "dias_strings": 8, "dias_trackers": 8, "dias_comunicou": 8, "primeiro_dia": "2026-10-01"}],
            "strings_os": [
                {"data_evento": "2026-10-06", "cliente": "Thopen", "usina": "Guaratinguetá V", "plant_id": "18750000",
                 "inversor": "Inversor 1.3", "os": "15700", "status": "Pendente", "strings": None, "qtd": None,
                 "origem": "sem_quantidade"},
                {"data_evento": "2026-10-01", "cliente": "Thopen", "usina": "Guaratinguetá V", "plant_id": None,
                 "inversor": "Inversor 1.4", "os": "15151", "status": "Em andamento",
                 "strings": "Ipv1, Ipv2", "qtd": 2, "origem": "citadas"}],
            "trackers_dia": [
                {"dia": "2026-10-02", "fonte": "pv", "plant_id": "297381", "cliente": "Thopen", "usina": "Brodowski",
                 "trackers": "TRK1, TRK3", "qtd": 2, "comunicou": "sem prova"},
                {"dia": "2026-10-01", "fonte": "pv", "plant_id": "297381", "cliente": "Thopen", "usina": "Brodowski",
                 "trackers": "TRK1", "qtd": 1, "comunicou": "sim"}]}


def _linhas(tabs, aba):
    return [dict(zip(pub.CABECALHOS[aba], lin)) for lin in tabs[aba]]


def test_colunas_novas_entram_so_no_fim_das_abas():
    for aba, cab in ANTES.items():
        assert pub.CABECALHOS[aba][:len(cab)] == cab                  # BI e Nexus leem por posição: nada se mexe
    assert pub.CABECALHOS["strings_episodios"][len(ANTES["strings_episodios"]):] == ["plant_id"]
    assert pub.CABECALHOS["trackers_episodios"][len(ANTES["trackers_episodios"]):] == ["plant_id", "dias_comunicou",
                                                                                         "dias_sem_prova"]
    # rodada 4 (09/10/2026): a disponibilidade do dia (Gerencial) entra no fim, depois das da rodada 2
    assert pub.CABECALHOS["atualizacao"][len(ANTES["atualizacao"]):] == ["cobertura", "strings_os", "trackers_dia",
                                                                          "disponibilidade_dia"]
    assert pub.CABECALHOS["cobertura"] == ["mes", "fonte", "cliente", "usina", "plant_id", "dias_strings",
                                           "dias_trackers", "dias_comunicou"]
    assert pub.CABECALHOS["strings_os"] == ["mes", "data_evento", "cliente", "usina", "plant_id", "inversor", "os",
                                            "status", "strings", "qtd", "origem"]
    assert pub.CABECALHOS["trackers_dia"] == ["mes", "dia", "fonte", "cliente", "usina", "plant_id", "trackers", "qtd",
                                              "comunicou"]


def test_episodios_levam_o_plant_id_e_o_tracker_os_dias_em_que_a_usina_comunicou():
    tabs = pub.tabelas([_pac()])
    (s,) = _linhas(tabs, "strings_episodios")
    (t,) = _linhas(tabs, "trackers_episodios")
    assert (s["plant_id"], t["plant_id"], t["dias_comunicou"], t["dias_sem_prova"]) == ("297378", "297381", 3, 1)


def test_plant_id_numerico_no_pacote_sai_como_texto():
    # o trk_store da API PV guarda o id como texto, mas o pacote de um mês antigo (ou outra fonte) pode trazer número:
    # na planilha "297378" e 297378 viram células diferentes, e o 5080 junta os cadastros pelo texto
    p = _pac()
    p["trackers"]["rows"][0]["plant_id"] = 297381
    (t,) = _linhas(pub.tabelas([p]), "trackers_episodios")
    assert t["plant_id"] == "297381"


def test_aba_cobertura_e_a_contagem_na_atualizacao():
    tabs = pub.tabelas([_pac()])
    (c,) = _linhas(tabs, "cobertura")
    assert (c["mes"], c["fonte"], c["usina"], c["plant_id"], c["dias_strings"], c["dias_comunicou"]) == \
        ("2026-10", "Thopen · API PV", "Brodowski", "297378", 8, 8)
    (a,) = _linhas(tabs, "atualizacao")
    assert (a["cobertura"], a["strings_os"], a["trackers_dia"]) == (1, 2, 2)


def test_cobertura_com_zero_dias_publica_zero_e_nao_celula_vazia():
    # 0 dias de tracker = a plataforma olhou e não havia leitura; vazio seria "coluna não publicada" para o 5080
    p = _pac()
    p["cobertura"][0]["dias_trackers"] = 0
    (c,) = _linhas(pub.tabelas([p]), "cobertura")
    assert c["dias_trackers"] == 0


def test_pacote_antigo_sem_os_campos_novos_sai_com_celula_vazia():
    # revisão do Nexus (08/10): a contagem da `atualizacao` gravava 0 para a aba que o pacote nem montou — e o 5080
    # leria "nenhuma OS" / "nenhuma usina medida" onde só não houve publicação. Sem a chave = vazio
    p = _pac()
    for k in ("cobertura", "strings_os", "trackers_dia"):
        del p[k]
    p["trackers"]["rows"][0].pop("dias_comunicou")
    p["trackers"]["rows"][0].pop("dias_sem_prova")
    tabs = pub.tabelas([p])
    assert _linhas(tabs, "cobertura") == _linhas(tabs, "strings_os") == _linhas(tabs, "trackers_dia") == []
    (t,) = _linhas(tabs, "trackers_episodios")
    assert (t["dias_comunicou"], t["dias_sem_prova"]) == (None, None)
    (a,) = _linhas(tabs, "atualizacao")
    assert (a["cobertura"], a["strings_os"], a["trackers_dia"]) == (None, None, None)


def test_aba_montada_e_vazia_conta_zero_na_atualizacao():
    # montou e não houve nada (nenhuma OS de string no mês, nenhum tracker parado com a usina comunicando) = 0 medido
    p = {**_pac(), "cobertura": [], "strings_os": [], "trackers_dia": []}
    (a,) = _linhas(pub.tabelas([p]), "atualizacao")
    assert (a["cobertura"], a["strings_os"], a["trackers_dia"]) == (0, 0, 0)


def test_strings_os_vai_pela_data_do_evento_e_a_os_sem_quantidade_fica_vazia():
    l = _linhas(pub.tabelas([_pac()]), "strings_os")
    assert [x["os"] for x in l] == ["15151", "15700"]                  # pela data do evento: a nova entra no fim
    a, b = l
    assert (a["mes"], a["data_evento"], a["usina"], a["inversor"], a["strings"], a["qtd"], a["origem"]) == \
        ("2026-10", "2026-10-01", "Guaratinguetá V", "Inversor 1.4", "Ipv1, Ipv2", 2, "citadas")
    assert (b["qtd"], b["strings"], b["plant_id"], b["origem"]) == (None, None, "18750000", "sem_quantidade")
    assert a["plant_id"] is None


def test_os_e_plant_id_saem_como_texto_na_strings_os():
    p = _pac()
    p["strings_os"][0].update(os=15700, plant_id=18750000)
    b = _linhas(pub.tabelas([p]), "strings_os")[1]
    assert (b["os"], b["plant_id"]) == ("15700", "18750000")


def test_trackers_dia_vai_pelo_dia_com_o_rotulo_da_fonte():
    l = _linhas(pub.tabelas([_pac()]), "trackers_dia")
    assert [(x["dia"], x["fonte"], x["usina"], x["plant_id"], x["trackers"], x["qtd"], x["comunicou"]) for x in l] == [
        ("2026-10-01", "Thopen · API PV", "Brodowski", "297381", "TRK1", 1, "sim"),
        ("2026-10-02", "Thopen · API PV", "Brodowski", "297381", "TRK1, TRK3", 2, "sem prova")]


def test_cobertura_vai_pelo_primeiro_dia_medido_para_o_cadastro_novo_entrar_no_fim():
    # a API guarda histórico por linha (row_number): pela ordem do nome, o cadastro que aparece no meio do mês entraria
    # no meio da aba e empurraria as linhas de baixo — o mesmo motivo de os episódios irem pela data de início
    p = _pac()
    p["cobertura"].append({"fonte": "pv", "plant_id": "1", "usina": "Altair", "cliente": "Thopen", "dias_strings": 2,
                           "dias_trackers": 2, "dias_comunicou": 2, "primeiro_dia": "2026-10-07"})
    assert [c["usina"] for c in _linhas(pub.tabelas([p]), "cobertura")] == ["Brodowski", "Altair"]


def test_as_abas_novas_vao_no_xlsx_antes_da_atualizacao():
    import io
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(pub.xlsx_bytes(pub.tabelas([_pac()]))))
    assert wb.sheetnames[-5:] == ["cobertura", "strings_os", "trackers_dia", "disponibilidade_dia", "atualizacao"]
    assert [c.value for c in wb["cobertura"][2]] == ["2026-10", "Thopen · API PV", "Thopen", "Brodowski", "297378",
                                                     8, 8, 8]
    assert [c.value for c in wb["strings_os"][3]] == ["2026-10", "2026-10-06", "Thopen", "Guaratinguetá V", "18750000",
                                                      "Inversor 1.3", "15700", "Pendente", None, None, "sem_quantidade"]


# ── Rodada 4 (Levi, 09/10/2026): a disponibilidade do dia vai no pacote do mês, da aba Disponibilidade do Gerencial ──
def test_disponibilidade_do_mes_sai_do_indice_do_gerencial(monkeypatch):
    idx = {"meses": {"2026-10": {
        "periodo": {"ini": "2026-10-01T00:00:00", "fim": "2026-10-09T00:00:00", "dias": 8},
        "usinas": [{"usina": "Guaratinguetá V", "fracttal": "Thopen - Guaratingueta 5 - SP", "cliente": "Thopen",
                    "pot_kwp": 2700.0, "disp": 99.5, "inversores": []}],
        "diario": {"Guaratinguetá V": {"2026-10-04": {"h_eq": 0.509, "disp": 95.8, "kwh": 1628, "h_q": 0, "h_e": 0.5}}},
        "oss": [{"folio": 1}]}}}
    monkeypatch.setattr(app, "_frac_disp_dados", lambda: idx)
    d = app._falhas_disp_mes("2026-10")
    assert d["periodo"] == ["2026-10-01", "2026-10-09"]
    assert d["usinas"] == [{"usina": "Guaratinguetá V", "fracttal": "Thopen - Guaratingueta 5 - SP", "cliente": "Thopen",
                            "pot_kwp": 2700.0}]
    assert d["diario"] == {"Guaratinguetá V": {"2026-10-04": {"disp": 95.8, "h_eq": 0.509}}}
    assert app._falhas_disp_mes("2026-08") is None
    (a,) = [dict(zip(pub.CABECALHOS["atualizacao"], x)) for x in pub.tabelas([{"mes": "2026-10", "disponibilidade": d}])["atualizacao"]]
    assert a["disponibilidade_dia"] == 8
