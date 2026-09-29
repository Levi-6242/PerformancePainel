# -*- coding: utf-8 -*-
"""Falhas de strings e trackers — a montagem do mês (falhas_job.montar), sobre stores sintéticos (24/09/2026).

Cada teste trava uma regra que o Levi pediu ao ver o estudo:
- "se passou o dia com string nula e o dia acabou, então continua em aberto, teremos mais informações no outro
  dia" — sem notícia depois, o episódio segue EM ABERTO (antes virava "sem registro depois" e saía do filtro);
- a string que amanhece zerada continua o episódio da véspera (saiu / voltou atravessando a noite);
- só entra quem fica 2 h seguidas sem corrente;
- tracker que começa parado e vira atraso severo sai da visão; "parado" no alvo o episódio todo não é falha.
A usina é a Inhapi de verdade (cadastro local), para a perda sair com kWp e estado do sol reais.
"""
import pytest

import app
import falhas_job
import sol

PID = "18748739"          # Inhapi na API PV


def ev(st, caiu, voltou=None, inv="Inversor 3.3"):
    return {"inversor": inv, "string": st, "caiu": caiu, "voltou": voltou, "dur_min": 0, "gerando_agora": False}


def store(**por_dia):
    """store(d01=[eventos], d02=[...]) → o formato do perdas_strings.json, fonte API PV."""
    return {f"2026-09-{k[1:]}": {"pv": {PID: {"usina": "Inhapi", "ts": 0, "eventos": evs}}} for k, evs in por_dia.items()}


def monta(str_store, trk_store=None, fim="2026-09-03", pv_dev=None, agora=None, mortas=None):
    return falhas_job.montar(app, sol, "2026-09-01", fim, geracao={}, str_store=str_store, trk_store=trk_store or {},
                             book={}, hist_2c=lambda dia: {}, pv_dev=pv_dev, agora=agora, mortas_curva=mortas,
                             log=lambda m: None)


def morta(st, saiu="07:00", voltou=None, sempre_zero=True, inv="Inversor 3.3", ini="07:00"):
    """Uma string da régua nova sobre a curva (falhas.avaliar_dia)."""
    return {"inversor": inv, "string": st, "saiu": saiu, "voltou": voltou, "min_morta": 600, "trechos": [[saiu, voltou]],
            "criterio": {"zerada": 600, "abaixo_das_vizinhas": 0}, "ini_producao": ini, "fim_producao": "17:00",
            "sempre_zero": sempre_zero}


def curva(dia, mortas, vivas=24, inv="Inversor 3.3"):
    """O falhas_strings.json de um dia: a régua nova rodou na curva da usina (a Inhapi tem 24 strings por inversor)."""
    return {f"2026-09-{dia}": {"pv": {PID: {"usina": "Inhapi", "ts": 0, "mortas": mortas,
                                            "vivas": {inv: vivas} if vivas is not None else {}}}}}


def episodios(p, string="Ipv1"):
    return [e for e in p["strings"]["episodios"] if e["string"] == string]


def test_string_que_termina_o_dia_zerada_e_some_do_registro_segue_em_aberto():
    st = store(d01=[ev("Ipv1", "08:00")])
    # o registro seguiu nos dias 02 e 03 (outra usina), mas esta não apareceu mais
    for d in ("2026-09-02", "2026-09-03"):
        st[d] = {"pv": {"999": {"usina": "Outra", "ts": 0, "eventos": [ev("Ipv9", "10:00", "13:00")]}}}
    (e,) = episodios(monta(st))
    assert e["fim"] is None and e["fim_motivo"] == "em aberto"
    assert "sem registro desde 01/09" in e["flags"]


def test_string_trancada_sai_mesmo_com_o_nome_do_dispositivo_em_outra_caixa(monkeypatch):
    # Indaiatuba, 25/09: trava 21480|378276|Ipv18; o plant_devices chama o 378276 de "INVERSOR 1.10" e a queda gravada
    # diz "Inversor 1.10". Comparando o nome exato, a trava não era conferida e 16 episódios da string trancada
    # apareciam na aba (o Levi viu). O nome vale normalizado, como no resto da plataforma.
    monkeypatch.setattr(app, "_trancadas", {f"{PID}|378276|Ipv1"})
    monkeypatch.setattr(app, "_TRANC_INV", {("378276", "Ipv1")})
    dev = {PID: {"names": {"378276": "INVERSOR 3.3"}, "nome_api": None, "usina": "Inhapi"}}
    p = monta(store(d01=[ev("Ipv1", "08:00", "12:00"), ev("Ipv2", "08:00", "12:00")]), pv_dev=dev)
    assert [e["string"] for e in p["strings"]["episodios"]] == ["Ipv2"]
    assert p["strings"]["qualidade"]["trancada: fora"] == 1


def test_trava_que_nao_da_para_conferir_fica_avisada_na_linha(monkeypatch):
    monkeypatch.setattr(app, "_trancadas", {f"{PID}|999|Ipv1"})
    (e,) = episodios(monta(store(d01=[ev("Ipv1", "08:00", "12:00")]), pv_dev={}))      # sem de-para da usina
    assert "trava não conferida (sem de-para)" in e["flags"]


def test_athon_inversor_sem_trava_nao_fica_como_trava_nao_conferida(monkeypatch):
    # MAB100 Inv 3.9, 25/09: a usina tem uma trava (no Inversor 2.3) e por isso toda queda dela ficava "trava não
    # conferida". Na Athon o nome da trava sai da mesma função que nomeia a queda: fora do mapa = sem trava.
    monkeypatch.setattr(app, "_trancadas", {"TIM100|INV_35|I_PV2"})
    st = {"2026-09-01": {"sunop": {"TIM100": {"usina": "TIM100", "ts": 0,
                                                "eventos": [ev("ST 01", "08:00", "12:00", inv="Inversor 3.5")]}}}}
    (e,) = monta(st)["strings"]["episodios"]
    assert not any("trava" in f for f in e["flags"])


def test_string_aberta_hoje_conta_ate_agora_e_nao_ate_as_18h():
    from datetime import datetime
    # às 10:00 de hoje, a string que caiu às 08:00 e não voltou soma 2 h — não as 10 h até as 18:00
    (e,) = episodios(monta(store(d03=[ev("Ipv1", "08:00")]), agora=datetime(2026, 9, 3, 10, 0)))
    assert e["fim"] is None and e["h_sol"] == pytest.approx(2.0, abs=0.2)


def test_tracker_parado_hoje_conta_ate_agora_e_nao_ate_as_18h():
    from datetime import datetime
    # 25/09, 10:21: os 405 trackers parados desde a manhã contavam até as 18:00 (~11 h cada) — 45 MWh a mais no dia
    t = trk(d03=("parado", 40.0))
    t["2026-09-03"][PID]["eventos"][0]["parada"] = "07:00"
    (r,) = monta({}, t, agora=datetime(2026, 9, 3, 10, 20))["trackers"]["rows"]
    assert r["fim"] is None and r["h_sol"] == pytest.approx(3.33, abs=0.1)


def test_episodio_leva_o_id_da_usina_na_fonte():
    # Guatambu 1 a 4 são quatro cadastros na API PV com um TRK1 cada, e todos aparecem como "Guatambu": contando
    # por usina + tracker, a tela dizia "306 seguem parados agora" com 354 episódios em aberto (25/09)
    (e,) = episodios(monta(store(d01=[ev("Ipv1", "08:00", "12:00")])))
    (r,) = monta({}, trk(d01=("parado", 35.0), d02=("severo", None)))["trackers"]["rows"]
    assert e["plant_id"] == PID and r["plant_id"] == PID


def test_amanheceu_zerada_continua_o_mesmo_episodio():
    (e,) = episodios(monta(store(d01=[ev("Ipv1", "10:00")], d02=[ev("Ipv1", "06:10", "11:00")])))
    assert (e["inicio"], e["fim"], e["dias"]) == ("2026-09-01 10:00", "2026-09-02 11:00", 2)


def test_voltou_de_madrugada_quando_a_usina_aparece_sem_a_string_zerada():
    # no dia 02 a usina está no registro (outra string caiu), mas a Ipv1 não amanheceu zerada
    (e,) = episodios(monta(store(d01=[ev("Ipv1", "10:00")], d02=[ev("Ipv2", "12:00", "15:00")])))
    assert e["fim_motivo"] == "voltou de madrugada" and e["fim"].startswith("2026-09-02 ")


# ── volta falsa da manhã (27/09/2026) ────────────────────────────────────────────────────────────────────────────
# SMP100 5.2 ST15: a OS 13297 foi aberta em 09/09 e executada em 21/09 (MPPT em curto). Com pouca luz a string lia um
# pouco de corrente de manhã e a régua das quedas contava como volta: um defeito só virou 11 episódios, de ~10h às
# ~8h do dia seguinte. Volta antes das 9h que morre de novo antes do meio-dia (viva no máximo 2h30) não é volta.
FLAG_MANHA = "volta curta ignorada (morreu de novo no mesmo dia)"


def test_volta_de_manha_que_morre_de_novo_antes_do_meio_dia_e_o_mesmo_episodio():
    st = store(d01=[ev("Ipv1", "10:40")], d02=[ev("Ipv1", "06:30", "08:10"), ev("Ipv1", "10:00")],
               d03=[ev("Ipv1", "06:30", "08:10"), ev("Ipv1", "10:40", "15:00")])
    (e,) = episodios(monta(st))
    assert (e["inicio"], e["fim"], e["fim_motivo"]) == ("2026-09-01 10:40", "2026-09-03 15:00", "voltou")
    assert FLAG_MANHA in e["flags"]


def test_volta_de_manha_com_queda_nova_so_a_tarde_sao_dois_episodios():
    st = store(d01=[ev("Ipv1", "10:40")], d02=[ev("Ipv1", "06:30", "08:10"), ev("Ipv1", "14:00", "17:00")])
    assert len(episodios(monta(st))) == 2


def test_volta_de_horas_no_meio_do_dia_e_volta_de_verdade():
    # SMP100 5.2 ST17 morre ~07:40 e volta ~10:20 todo dia; se morrer de novo só à tarde, horas depois, são dois episódios
    st = store(d01=[ev("Ipv1", "07:40", "10:20"), ev("Ipv1", "13:30", "16:00")])
    assert len(episodios(monta(st))) == 2


def test_string_que_pisca_ate_as_10h_e_morre_e_o_mesmo_episodio():
    # SMP100 5.2 ST15, 14/09 no dado real: zerada da véspera, 06:30–08:20, 09:10–09:40 e de novo às 10:00 — volta de
    # 50 min e de 20 min. Com a regra só das 9h, o episódio fechava às 09:40 e abria outro às 10:00 (11 viravam 7).
    st = store(d01=[ev("Ipv1", "10:40")], d02=[ev("Ipv1", "06:30", "08:20"), ev("Ipv1", "09:10", "09:40"), ev("Ipv1", "10:00")])
    (e,) = episodios(monta(st))
    assert e["inicio"] == "2026-09-01 10:40" and e["fim"] is None


def test_string_que_pisca_a_tarde_num_dia_morto_e_o_mesmo_episodio():
    # MTS100 3.7 ST11, 23/09 (Levi: "está acontecendo o mesmo em MTS100"): a curva do dia não tem uma leitura acima de
    # 0,5 A, e a régua das quedas registrou 06:50–08:50, 09:00–09:30, 09:40–10:40, 10:50–12:40, 13:10–14:30 e 15:00 em
    # diante. A pisca só valia até o meio-dia: a volta de 30 min das 12:40 fechava o episódio e abria outro às 15:00
    st = store(d01=[ev("Ipv1", "15:40")],
               d02=[ev("Ipv1", "06:50", "08:50"), ev("Ipv1", "09:00", "09:30"), ev("Ipv1", "09:40", "10:40"),
                    ev("Ipv1", "10:50", "12:40"), ev("Ipv1", "13:10", "14:30"), ev("Ipv1", "15:00")])
    (e,) = episodios(monta(st, fim="2026-09-02"))
    assert e["inicio"] == "2026-09-01 15:40" and e["fim"] is None


def test_volta_de_mais_de_uma_hora_a_tarde_e_volta_de_verdade():
    st = store(d01=[ev("Ipv1", "08:00", "12:40"), ev("Ipv1", "14:00", "17:30")])
    assert len(episodios(monta(st, fim="2026-09-01"))) == 2


def test_pedacos_curtos_nao_viram_falha_somados():
    # "2 h SEGUIDAS" (Levi, 24/09): 1h10 + volta de 20 min + 1h10 não vira um episódio de 2h20
    st = store(d01=[ev("Ipv1", "10:00", "11:10"), ev("Ipv1", "11:30", "12:40")])
    assert episodios(monta(st)) == []


def test_curva_volta_curta_de_manha_depois_de_dia_morto_continua_o_episodio():
    # na régua nova a volta falsa vira "voltou de madrugada": a string gera das 08:00 às 10:00 e morre de novo
    mortas = {**curva("01", [morta("Ipv1", saiu="10:00", sempre_zero=False, ini="08:00")], vivas=21),
              **curva("02", [morta("Ipv1", saiu="10:00", sempre_zero=False, ini="08:00")], vivas=21)}
    (e,) = episodios(monta({}, mortas=mortas))
    assert e["inicio"] == "2026-09-01 10:00" and e["fim"] is None
    assert FLAG_MANHA in e["flags"]


def test_curva_manha_inteira_viva_e_volta_de_verdade():
    mortas = {**curva("01", [morta("Ipv1", saiu="10:00", sempre_zero=False, ini="07:00")], vivas=21),
              **curva("02", [morta("Ipv1", saiu="11:00", sempre_zero=False, ini="07:00")], vivas=21)}
    assert len(episodios(monta({}, mortas=mortas))) == 2


def test_queda_de_menos_de_duas_horas_seguidas_nao_entra():
    p = monta(store(d01=[ev("Ipv1", "10:00", "11:30")]))
    assert episodios(p) == []
    assert p["strings"]["qualidade"]["descartado: menos de 2 h seguidas sem corrente"] == 1


def test_as_duas_visoes_de_strings_somam_o_mesmo_kwh():
    p = monta(store(d01=[ev("Ipv1", "10:00"), ev("Ipv2", "09:00", "13:00")], d02=[ev("Ipv1", "06:10", "11:00")]))
    kwh_ep = sum(e["perda_kwh"] for e in p["strings"]["episodios"])
    assert kwh_ep > 0
    assert sum(r["perda_kwh"] for r in p["strings"]["rows"]) == pytest.approx(kwh_ep, abs=0.2)


# ── entrada vazia (27/09/2026) ───────────────────────────────────────────────────────────────────────────────────
# O cruzamento com as OS mostrou que Ipv29 a Ipv32 eram 41% dos episódios e 55% do kWh de setembro: entradas SEM
# string ligada, em 0 A cravado (Santana do Ipanema 1.13, Guatambu 4.6), nunca citadas em OS. Entrada vazia é a que
# nunca deu sinal de vida — nenhuma volta de verdade no histórico gravado, zero em toda curva do dia — num inversor
# que já tem, vivas, as strings do cadastro. Sai do mês inteiro, como a trava. O cadastro sozinho não serve: SMP100
# 5.2 tem 17 strings no cadastro e ST19 a ST25 são reais (a OS 13297 cita).

def test_entrada_que_nunca_teve_corrente_com_o_inversor_cheio_sai_do_mes_inteiro():
    st = store(d01=[ev("Ipv29", "07:00"), ev("Ipv5", "08:00", "12:00")])
    p = monta(st, mortas=curva("02", [morta("Ipv29")], vivas=24))
    assert [e["string"] for e in p["strings"]["episodios"]] == ["Ipv5"]      # nem o dia 01 (quedas) nem o 02 (curva)
    assert p["strings"]["qualidade"]["entrada vazia: fora"] == 2
    (v,) = p["strings"]["entradas_vazias"]
    assert (v["usina"], v["inversor"], v["string"], v["esperadas"], v["vivas"]) == ("Inhapi", "Inversor 3.3", "Ipv29", 24, 24)


def test_entrada_zerada_com_o_inversor_abaixo_do_cadastro_continua_falha():
    # com 21 vivas de 24 no cadastro, faltam 3 strings de verdade: a zerada pode ser uma delas
    p = monta(store(d01=[ev("Ipv29", "07:00")]), mortas=curva("02", [morta("Ipv29")], vivas=21))
    assert {e["string"] for e in p["strings"]["episodios"]} == {"Ipv29"}
    assert p["strings"]["entradas_vazias"] == []


def test_string_que_ja_voltou_no_historico_nao_vira_entrada_vazia():
    # SMP100 5.2 ST19 (OS 13297, MPPT em curto): morta em todas as curvas desde 25/09, mas voltou em 08/09 12:40
    p = monta(store(d01=[ev("Ipv29", "08:00", "12:30")]), mortas=curva("02", [morta("Ipv29")], vivas=24))
    assert {e["string"] for e in p["strings"]["episodios"]} == {"Ipv29"}
    assert p["strings"]["entradas_vazias"] == []


def test_entrada_que_leu_corrente_num_dia_de_curva_nao_e_vazia():
    p = monta(store(d01=[ev("Ipv29", "07:00")]), mortas=curva("02", [morta("Ipv29", sempre_zero=False)], vivas=24))
    assert p["strings"]["entradas_vazias"] == []


def test_entrada_zerada_num_dia_e_viva_no_outro_nao_e_vazia():
    # dia 03: o inversor gerou (tem vivas) e a Ipv29 não aparece nas mortas — ela gerou nesse dia
    mortas = {**curva("02", [morta("Ipv29")], vivas=24), **curva("03", [], vivas=24)}
    p = monta(store(d01=[ev("Ipv29", "07:00")]), mortas=mortas)
    assert p["strings"]["entradas_vazias"] == []


def _curva_constante(vivas=4, zeradas=("Ipv29",)):
    serie = [(f"{h:02d}:{m:02d}", 8.0) for h in range(7, 17) for m in (0, 10, 20, 30, 40, 50)]
    strs = {f"Ipv{i}": serie for i in range(1, vivas + 1)}
    strs.update({z: [(t, 0.0) for t, _ in serie] for z in zeradas})
    return {"Inversor 3.3": strs}


def test_registro_da_regua_nova_guarda_as_vivas_e_a_marca_de_sempre_zero(monkeypatch):
    # sem isso o mês não tem como separar a entrada vazia da string morta: a curva do dia não fica guardada
    monkeypatch.setattr(app, "_FALHAS_MORTAS", {})
    app._falhas_registra("pv", "2026-09-02", PID, "Inhapi", _curva_constante())
    ent = app._FALHAS_MORTAS[("pv", "2026-09-02")][PID]
    assert ent["vivas"] == {"Inversor 3.3": 4}
    (m,) = ent["mortas"]
    assert m["string"] == "Ipv29" and m["sempre_zero"] is True


def test_registro_em_memoria_segura_dois_dias_de_todas_as_fontes(monkeypatch):
    # com a String Box, o Banco e a RenoGrid entrando, são 7 fontes: o teto antigo (12 chaves) guardava menos de 2 dias
    monkeypatch.setattr(app, "_FALHAS_MORTAS", {})
    fontes = ("pv", "pvsb", "sunop", "axis", "pg", "solaredge", "owen")
    for dia in ("2026-09-01", "2026-09-02"):
        for f in fontes:
            app._falhas_registra(f, dia, PID, "Inhapi", _curva_constante())
    assert len(app._FALHAS_MORTAS) == 14


def test_string_box_entra_no_mes_e_a_trava_vale_pelo_id_do_inversor(monkeypatch):
    # a curva da combiner chega com o id de cada inversor (a trava da API PV é plant|idefinversor|IpvN)
    monkeypatch.setattr(app, "_trancadas", {"555|11|Ipv5"})
    mortas = {"2026-09-02": {"pvsb": {"555": {"usina": "Inhapi", "ts": 0, "ids": {"Inversor 3.3": "11"},
                                               "vivas": {"Inversor 3.3": 21},
                                               "mortas": [morta("Ipv4", sempre_zero=False), morta("Ipv5", sempre_zero=False)]}}}}
    p = monta({}, mortas=mortas)
    assert [(e["fonte"], e["string"]) for e in p["strings"]["episodios"]] == [("pvsb", "Ipv4")]


def test_entrada_vazia_com_o_inversor_gravado_pelo_id_usa_o_de_para(monkeypatch):
    # Santana do Ipanema, 27/09 23:41: o plant_devices falhou no processo recém-subido e a régua gravou os inversores
    # pelo id ("INV-367159"). Sem traduzir pelo de-para, o inversor não casava com o cadastro e nada era decidido.
    dev = {PID: {"names": {"378276": "INVERSOR 3.3"}, "nome_api": None, "usina": "Inhapi"}}
    p = monta(store(d01=[ev("Ipv29", "07:00")]), pv_dev=dev,
              mortas=curva("02", [morta("Ipv29", inv="INV-378276")], vivas=24, inv="INV-378276"))
    assert p["strings"]["episodios"] == []
    (v,) = p["strings"]["entradas_vazias"]
    assert (v["inversor"], v["string"], v["esperadas"]) == ("Inversor 3.3", "Ipv29", 24)


def test_inversor_sem_strings_no_cadastro_nao_decide_entrada_vazia():
    p = monta(store(d01=[ev("Ipv29", "07:00", inv="Inversor 9.9")]),
              mortas=curva("02", [morta("Ipv29", inv="Inversor 9.9")], vivas=30, inv="Inversor 9.9"))
    assert p["strings"]["entradas_vazias"] == []


def test_retorno_em_massa_nao_conta_como_sinal_de_vida():
    # 100+ strings "voltando" no mesmo minuto é a telemetria que voltou, não a string
    massa = [ev(f"Ipv{s}", "07:00", "14:40", inv=f"Inversor 1.{k}") for k in range(1, 7) for s in range(1, 21)]
    p = monta(store(d01=[ev("Ipv29", "07:00", "14:40")] + massa), mortas=curva("02", [morta("Ipv29")], vivas=24))
    assert [v["string"] for v in p["strings"]["entradas_vazias"]] == ["Ipv29"]


def trk(**por_dia):
    """trk(d01=(status, desvio), ...) → o formato do trk_eventos.json, um tracker só."""
    out = {}
    for k, (status, desvio) in por_dia.items():
        evs = [{"tracker": "TRK1", "parada": "08:00", "retorno": None, "desvio": desvio}] if status == "parado" else []
        out[f"2026-09-{k[1:]}"] = {PID: {"nome": "Inhapi", "cobertura": 1.0, "classes": {"TRK1": {"status": status}},
                                          "eventos": evs}}
    return out


def test_tracker_parado_que_vira_atraso_severo_sai_da_visao():
    # saiu do parado no dia 02, em hora que o registro não guarda: o "voltou" é o DIA 02, sem hora inventada
    (r,) = monta({}, trk(d01=("parado", 35.0), d02=("severo", None)))["trackers"]["rows"]
    assert r["fim"] == "2026-09-02"
    assert "saiu: severo" in r["flags"]


def test_tracker_que_some_das_classes_com_a_usina_lendo_voltou_nesse_dia():
    # MAB200 Tracker 103 (Levi, 25/09): parado de 05 a 08/09; em 09/09 a usina lia e o tracker não estava em
    # classe nenhuma — a régua não o viu parado. A tela dizia "voltou 08/09 17:38 · gap fechado no fim do dia";
    # na curva ele voltou em 09/09 entre 16:45 e 17:00. Voltou no dia 09; a hora o registro não guarda.
    t = trk(d01=("parado", 35.0), d02=("parado", 35.0))
    t["2026-09-03"] = {PID: {"nome": "Inhapi", "cobertura": 1.0, "classes": {"TRK2": {"status": "leve"}}, "eventos": []}}
    (r,) = [x for x in monta({}, t)["trackers"]["rows"] if x["tracker"] == "TRK1"]
    assert r["fim"] == "2026-09-03"
    assert "voltou em 03/09 (hora não registrada)" in r["flags"]
    assert not any("gap" in f for f in r["flags"])


def test_tracker_sem_dado_da_usina_depois_segue_em_aberto():
    # sem notícia da usina depois do último dia parado: segue em aberto (a mesma regra das strings)
    t = trk(d01=("parado", 35.0))
    t["2026-09-03"] = {"999": {"nome": "Outra", "cobertura": 1.0, "classes": {}, "eventos": []}}
    (r,) = [x for x in monta({}, t)["trackers"]["rows"] if x["tracker"] == "TRK1"]
    assert r["fim"] is None
    assert "sem dado da usina desde 01/09" in r["flags"]


def test_depois_da_meia_noite_o_parado_de_ontem_segue_em_aberto():
    # 25/09, 00:33 no servidor: o período já ia até "hoje" (25/09, ainda sem dado) e todo tracker parado em 24/09
    # fechou como "sem dado depois" — 0 em aberto. O em aberto conta pelo último dia COM dado.
    (r,) = monta({}, trk(d01=("parado", 35.0), d02=("parado", 35.0)), fim="2026-09-03")["trackers"]["rows"]
    assert r["fim"] is None and "em aberto" in r["flags"]


def test_depois_da_meia_noite_a_string_zerada_de_ontem_segue_em_aberto_sem_aviso_de_sumico():
    (e,) = episodios(monta(store(d01=[ev("Ipv1", "08:00")], d02=[ev("Ipv1", "06:10")]), fim="2026-09-03"))
    assert e["fim"] is None and not any(f.startswith("sem registro desde") for f in e["flags"])


@pytest.fixture
def frota20(monkeypatch):
    """A usina do teste com 20 trackers no cadastro (BD_Trackers): o registro só guarda tracker com anomalia, e é o
    cadastro que diz o tamanho da frota."""
    monkeypatch.setitem(app.BD_TRK_INV, app._nome_base("Inhapi"), {i: "Inversor 3.3" for i in range(1, 21)})


def test_tracker_parado_no_alvo_o_episodio_todo_nao_e_falha(frota20):
    p = monta({}, trk(d01=("parado", 0.4)))
    assert p["trackers"]["rows"] == []
    assert p["trackers"]["qualidade"]["descartado: no alvo o episódio todo (desvio < 2°)"] == 1


def frota_parada(n, desvio, dias=("01",), parada="06:00"):
    """n trackers parados juntos na mesma usina, com o desvio medido contra a mediana da frota."""
    out = {}
    for d in dias:
        out[f"2026-09-{d}"] = {PID: {
            "nome": "Inhapi", "cobertura": 1.0,
            "classes": {f"TRK{i}": {"status": "parado"} for i in range(1, n + 1)},
            "eventos": [{"tracker": f"TRK{i}", "parada": parada, "retorno": None, "desvio": desvio} for i in range(1, n + 1)]}}
    return out


def test_usina_com_a_maioria_da_frota_parada_nao_e_descartada_como_no_alvo(frota20):
    # Levi, 28/09: "as ocorrências de trackers parados em aberto hoje batem com o tempo real?" — não batiam: 359 de 738.
    # O desvio do registro é medido contra a MEDIANA DA FROTA; com a frota parada junto, a mediana é a própria frota
    # parada e o desvio dá 0 — Brodowski (52 de 52 a 0,6° desde 24/09), Guatambu 4, Primavera 1 e 2, Santa Bárbara I.
    # Das 1.692 paradas descartadas como "no alvo" em setembro, 1.671 eram de dia com a maioria da frota parada.
    p = monta({}, frota_parada(12, 0.0), fim="2026-09-01")
    rows = p["trackers"]["rows"]
    assert len(rows) == 12
    assert all(r["fim"] is None and r["fator"] == 0.25 for r in rows)
    assert all("maioria da frota parada (sem referência de ângulo)" in r["flags"] for r in rows)
    assert not p["trackers"]["qualidade"].get("descartado: no alvo o episódio todo (desvio < 2°)")


def test_minoria_parada_no_alvo_continua_descartada(frota20):
    # 8 de 20: a mediana é dos que giram, e o desvio contra ela vale — parado em cima dela não é falha
    p = monta({}, frota_parada(8, 0.5), fim="2026-09-01")
    assert p["trackers"]["rows"] == []
    assert p["trackers"]["qualidade"]["descartado: no alvo o episódio todo (desvio < 2°)"] == 8


def test_desvio_de_dia_com_a_frota_parada_nao_entra_na_perda(frota20):
    # parado sozinho no dia 01 (desvio de 40° contra a frota girando) e com a frota inteira no dia 02 (desvio 0 contra
    # ela): a perda usa só o desvio que tem referência
    t = trk(d01=("parado", 40.0))
    t.update(frota_parada(15, 0.0, dias=("02",)))
    (r,) = [x for x in monta({}, t, fim="2026-09-02")["trackers"]["rows"] if x["tracker"] == "TRK1"]
    assert r["desvio_pico"] == 40.0
    assert "maioria da frota parada (sem referência de ângulo)" in r["flags"]


def test_parado_que_entra_na_parada_da_frota_nao_e_descartado_pelo_desvio_de_antes(frota20):
    # dia 01: só ele parado, a 1° da mediana dos que giram (seria "no alvo"); dia 02: a frota para junto — é falha
    t = trk(d01=("parado", 1.0))
    t.update(frota_parada(15, 0.0, dias=("02",)))
    (r,) = [x for x in monta({}, t, fim="2026-09-02")["trackers"]["rows"] if x["tracker"] == "TRK1"]
    assert r["fim"] is None and r["inicio"].startswith("2026-09-01")


def test_dia_sem_classificacao_nao_fecha_o_episodio(frota20):
    # MAB100, 28/09: o registro do dia tinha cobertura 0,43 (< 0,5) e não classificou ninguém — era lido como "a usina
    # leu e o tracker não estava parado", e o episódio fechava "voltou (hora não registrada)". Nove parados no tempo
    # real, nenhum na aba.
    t = trk(d01=("parado", 35.0))
    t["2026-09-02"] = {PID: {"nome": "Inhapi", "cobertura": 0.43, "eventos": []},
                       "999": {"nome": "Outra", "cobertura": 1.0, "classes": {}, "eventos": []}}
    (r,) = [x for x in monta({}, t, fim="2026-09-02")["trackers"]["rows"] if x["tracker"] == "TRK1"]
    assert r["fim"] is None
    assert "leitura incompleta da usina desde 01/09" in r["flags"]
    assert not any(f.startswith("voltou") for f in r["flags"])


def test_manha_sem_nenhuma_usina_classificada_nao_acende_aviso(frota20):
    # 06:40: ninguém tem leitura suficiente ainda — o parado de ontem segue em aberto, sem aviso de leitura incompleta
    t = trk(d01=("parado", 35.0))
    t["2026-09-02"] = {PID: {"nome": "Inhapi", "cobertura": 0.2, "eventos": []}}
    (r,) = monta({}, t, fim="2026-09-02")["trackers"]["rows"]
    assert r["fim"] is None
    assert not any("desde" in f for f in r["flags"])


def test_classe_parado_com_volta_no_ultimo_evento_nao_fecha(frota20):
    # Barretos 2, 28/09: 21 trackers parados no tempo real e fechados na aba "voltou a girar 09:10" — leitura que
    # teleporta (172°, 8·10¹¹°) faz o evento "voltar", e a classe do dia, a mesma do tempo real, diz parado
    t = trk(d01=("parado", 35.0))
    t["2026-09-02"] = {PID: {"nome": "Inhapi", "cobertura": 1.0, "classes": {"TRK1": {"status": "parado"}},
                             "eventos": [{"tracker": "TRK1", "parada": "06:40", "retorno": "09:10", "desvio": 35.0}]}}
    (r,) = monta({}, t, fim="2026-09-02")["trackers"]["rows"]
    assert r["fim"] is None
    assert r["h_sol"] > 15          # o dia 02 conta até o fim da janela, não até as 09:10


def test_volta_no_meio_do_dia_com_nova_parada_continua_sendo_dois_episodios(frota20):
    # a regra acima é só para o ÚLTIMO evento: parou 07:00–10:00, voltou, parou de novo às 13:00 → dois episódios
    t = {"2026-09-01": {PID: {"nome": "Inhapi", "cobertura": 1.0, "classes": {"TRK1": {"status": "parado"}},
                              "eventos": [{"tracker": "TRK1", "parada": "07:00", "retorno": "10:00", "desvio": 30.0},
                                          {"tracker": "TRK1", "parada": "13:00", "retorno": None, "desvio": 30.0}]}}}
    rows = sorted(monta({}, t, fim="2026-09-01")["trackers"]["rows"], key=lambda x: x["inicio"])
    assert [(r["inicio"][11:], r["fim"]) for r in rows] == [("07:00", "2026-09-01 10:00"), ("13:00", None)]


# ── a aba na plataforma: a tela abre e a API só LÊ o pacote que o worker publicou ─────────────
@pytest.fixture
def cliente(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "DASH_PASSWORD", "", raising=False)   # sem senha, o gate libera
    monkeypatch.setattr(app, "_falhas_arquivo", lambda mes: str(tmp_path / f"falhas_{mes}.json"))
    monkeypatch.setattr(app, "_falhas_mem", {})
    app.app.config["TESTING"] = True
    with app.app.test_client() as c:
        yield c, tmp_path


def test_a_tela_abre_debaixo_do_painel(cliente):
    c, _ = cliente
    r = c.get("/painel/falhas")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "/api/painel/falhas" in html and "{% raw %}" not in html     # o bloco raw do Jinja não vaza para a tela


def test_mes_sem_pacote_publicado_responde_frio_sem_calcular(cliente):
    c, _ = cliente
    j = c.get("/api/painel/falhas?mes=2026-09").get_json()
    assert j["quente"] is False and j["mes"] == "2026-09" and "2026-09" in j["meses"]


def test_mes_publicado_pelo_worker_e_servido_como_esta(cliente):
    c, pasta = cliente
    pacote = monta(store(d01=[ev("Ipv1", "08:00")]))
    app._falhas_publicar("2026-09", pacote)            # como o worker publica (o arquivo já é a resposta)
    j = c.get("/api/painel/falhas?mes=2026-09").get_json()
    assert j["quente"] is True
    assert j["strings"]["episodios"] == pacote["strings"]["episodios"]


def test_mes_invalido_e_recusado(cliente):
    c, _ = cliente
    assert c.get("/api/painel/falhas?mes=../../etc").status_code == 400


# ── o workbook falhas_performance: só o servidor grava, de hora em hora, e só quando o dado mudou ──────
import falhas_publicar


@pytest.fixture
def worker_wb(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "_falhas_arquivo", lambda mes: str(tmp_path / f"falhas_{mes}.json"))
    monkeypatch.setattr(app, "_falhas_wb", {"ts": 0.0, "marca": None})
    monkeypatch.setenv("GRIDCO_SQL_TOKEN", "tok-teste")
    chamadas = []
    monkeypatch.setattr(falhas_publicar, "sincronizar", lambda conteudo, **kw: chamadas.append(kw) or {"sheets": 4})
    app._falhas_publicar("2026-09", monta(store(d01=[ev("Ipv1", "08:00")]), mortas=curva("02", [], vivas=24)), ["2026-09"])
    return chamadas


def test_workbook_sobe_uma_vez_por_hora_e_so_quando_o_dado_muda(monkeypatch, worker_wb):
    monkeypatch.setenv("FALHAS_WORKBOOK", "1")
    app._falhas_publicar_workbook(["2026-09"])
    assert len(worker_wb) == 1 and worker_wb[0]["token"] == "tok-teste"
    app._falhas_publicar_workbook(["2026-09"])                  # mesma hora: não sobe de novo
    assert len(worker_wb) == 1
    app._falhas_wb["ts"] = 0.0                                   # passou a hora, mas o dado é o mesmo
    app._falhas_publicar_workbook(["2026-09"])
    assert len(worker_wb) == 1


def test_workbook_desligado_nao_sobe(monkeypatch, worker_wb):
    monkeypatch.setenv("FALHAS_WORKBOOK", "0")
    app._falhas_publicar_workbook(["2026-09"])
    assert worker_wb == []


# ── histórico do PC para o servidor e o workbook (passo 6, 27/09/2026) ─────────────────────────────────────────────
# O servidor só gravou strings desde 22/09 (Athon) e 24/09 (API PV); para 01–21/09 a varredura dele achou nada e gravou
# a fonte VAZIA. Não há acesso ao disco do servidor e o backup plataforma_series só restaura quando o arquivo some. A
# importação é pela própria plataforma: o PC manda, o worker de lá junta só o dia-fonte que ele não tem.
def test_workbook_liga_sozinho_so_no_servidor_e_a_chave_manda_nos_dois_sentidos(monkeypatch):
    monkeypatch.delenv("FALHAS_WORKBOOK", raising=False)
    monkeypatch.setattr(app.os, "name", "posix")
    assert app._falhas_workbook_ligado() is True           # o servidor (Linux) é quem grava
    monkeypatch.setattr(app.os, "name", "nt")
    assert app._falhas_workbook_ligado() is False          # a ponte local e o PC dedicado (Windows) não
    monkeypatch.setenv("FALHAS_WORKBOOK", "1")
    assert app._falhas_workbook_ligado() is True
    monkeypatch.setattr(app.os, "name", "posix")
    monkeypatch.setenv("FALHAS_WORKBOOK", "0")
    assert app._falhas_workbook_ligado() is False


def test_pacote_diz_os_dias_em_que_houve_registro_de_strings():
    p = monta(store(d01=[ev("Ipv1", "08:00", "12:00")], d03=[ev("Ipv2", "08:00", "12:00")]))
    assert p["strings"]["dias_registrados"] == ["2026-09-01", "2026-09-03"]


def test_workbook_nao_sobe_mes_cujo_registro_comeca_tarde(monkeypatch, worker_wb):
    # 25/09, 00:45: o registro do servidor começava em 22/09 e o replace=true trocou setembro inteiro pela parte dele
    monkeypatch.setenv("FALHAS_WORKBOOK", "1")
    p = monta(store(d22=[ev("Ipv1", "08:00", "12:00")]), fim="2026-09-27")
    app._falhas_publicar("2026-09", p, ["2026-09"])
    app._falhas_publicar_workbook(["2026-09"])
    assert worker_wb == []


def test_importacao_do_historico_so_preenche_dia_fonte_vazio_no_servidor(monkeypatch, tmp_path):
    from datetime import datetime
    e1 = {"usina": "Inhapi", "ts": 0, "eventos": [ev("Ipv1", "08:00", "12:00")]}
    hoje = datetime.now().strftime("%Y-%m-%d")
    monkeypatch.setattr(app, "_perdas_str", {"2026-09-01": {"pv": {}}, "2026-09-22": {"pv": {"1": e1}}})
    monkeypatch.setattr(app, "_perdas_str_save", lambda: None)
    staging = tmp_path / "importar.json"
    monkeypatch.setattr(app, "_FALHAS_IMPORTA_PATH", str(staging))
    staging.write_text(__import__("json").dumps({
        "2026-09-01": {"pv": {"5": e1}}, "2026-09-02": {"sunop": {"SMP100": e1}},
        "2026-09-22": {"pv": {"9": e1}}, hoje: {"pv": {"7": e1}}}), encoding="utf-8")
    n = app._falhas_importa_historico()
    assert set(app._perdas_str["2026-09-01"]["pv"]) == {"5"}          # o servidor tinha a fonte vazia: entra
    assert set(app._perdas_str["2026-09-02"]["sunop"]) == {"SMP100"}  # o servidor não tinha o dia: entra
    assert set(app._perdas_str["2026-09-22"]["pv"]) == {"1"}          # o servidor gravou esse dia: vale o dele
    assert hoje not in app._perdas_str                                 # hoje é do servidor
    assert n == 2 and not staging.exists()                             # a carga não é aplicada duas vezes


@pytest.fixture
def cliente_import(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "DASH_PASSWORD", "", raising=False)
    monkeypatch.setattr(app, "_FALHAS_IMPORTA_PATH", str(tmp_path / "importar.json"))
    app.app.config["TESTING"] = True
    with app.app.test_client() as c:
        yield c, tmp_path


def test_rota_de_importacao_guarda_a_carga_para_o_worker(cliente_import):
    c, pasta = cliente_import
    carga = {"2026-09-01": {"pv": {"5": {"usina": "Inhapi", "ts": 0, "eventos": [ev("Ipv1", "08:00", "12:00")]}}}}
    j = c.post("/api/painel/falhas/historico", json=carga).get_json()
    assert j["ok"] is True and j["dias"] == 1 and j["usinas"] == 1
    assert __import__("json").loads((pasta / "importar.json").read_text(encoding="utf-8")) == carga


def test_rota_de_importacao_recusa_carga_fora_do_formato(cliente_import):
    c, _ = cliente_import
    assert c.post("/api/painel/falhas/historico", json={"ontem": {"pv": []}}).status_code == 400
    assert c.post("/api/painel/falhas/historico", json=[1, 2]).status_code == 400


# ── virada de mês (passo 7, 27/09/2026): setembro fecha, outubro começa, nada some nem se duplica ─────────────────────
def test_meses_da_aba_na_virada_para_outubro():
    from datetime import date
    assert app._falhas_meses(date(2026, 10, 1)) == ["2026-09", "2026-10"]
    assert app._falhas_meses(date(2026, 9, 27)) == ["2026-09"]


def test_setembro_ainda_e_refeito_nos_dias_1_e_2_e_depois_congela():
    from datetime import date
    existe = lambda mes: True
    meses = ["2026-09", "2026-10"]
    assert app._falhas_meses_a_montar(date(2026, 10, 1), meses, existe) == ["2026-09", "2026-10"]
    assert app._falhas_meses_a_montar(date(2026, 10, 2), meses, existe) == ["2026-09", "2026-10"]
    assert app._falhas_meses_a_montar(date(2026, 10, 3), meses, existe) == ["2026-10"]
    assert app._falhas_meses_a_montar(date(2026, 10, 3), meses, lambda m: m != "2026-09") == ["2026-09", "2026-10"]


def test_string_zerada_no_fim_de_setembro_fica_em_aberto_no_pacote_de_setembro():
    # o pacote de setembro, refeito em 01/10, termina em 30/09: a string que seguia zerada em 01/10 fica em aberto
    ent = lambda evs: {"pv": {PID: {"usina": "Inhapi", "ts": 0, "eventos": evs}}}
    st = {"2026-09-30": ent([ev("Ipv1", "10:00")]), "2026-10-01": ent([ev("Ipv1", "06:10")])}
    (e,) = episodios(monta(st, fim="2026-09-30"))
    assert e["fim"] is None and not any(f.startswith("sem registro") for f in e["flags"])


def test_episodio_que_vem_de_setembro_diz_desde_quando_no_pacote_de_outubro():
    # o mês de outubro começa em 01/10: sem isso, a string zerada desde 20/09 apareceria como "saiu 01/10 06:10"
    ent = lambda evs: {"pv": {PID: {"usina": "Inhapi", "ts": 0, "eventos": evs}}}
    st = {"2026-10-01": ent([ev("Ipv1", "06:10", "11:00"), ev("Ipv2", "09:00", "12:00")])}
    antes = {"strings": {("pv", PID, "Inversor 3.3", "Ipv1"): "2026-09-20 10:40"}, "trackers": {}}
    p = falhas_job.montar(app, sol, "2026-10-01", "2026-10-01", geracao={}, str_store=st, trk_store={}, book={},
                          hist_2c=lambda dia: {}, abertos_antes=antes, log=lambda m: None)
    e1 = next(e for e in p["strings"]["episodios"] if e["string"] == "Ipv1")
    e2 = next(e for e in p["strings"]["episodios"] if e["string"] == "Ipv2")
    assert e1["desde"] == "2026-09-20 10:40" and "vem do mês anterior (desde 20/09 10:40)" in e1["flags"]
    assert "desde" not in e2                                # caiu às 09:00 de 01/10: começou em outubro


def test_tracker_parado_que_vem_de_setembro_diz_desde_quando():
    t = {"2026-10-01": {PID: {"nome": "Inhapi", "cobertura": 1.0, "classes": {"TRK1": {"status": "parado"}},
                              "eventos": [{"tracker": "TRK1", "parada": "06:30", "retorno": None, "desvio": 35.0}]}}}
    antes = {"strings": {}, "trackers": {("pv", PID, "TRK1"): "2026-09-25 14:00"}}
    p = falhas_job.montar(app, sol, "2026-10-01", "2026-10-01", geracao={}, str_store={}, trk_store=t, book={},
                          hist_2c=lambda dia: {}, abertos_antes=antes, log=lambda m: None)
    (r,) = p["trackers"]["rows"]
    assert r["desde"] == "2026-09-25 14:00"


def test_workbook_espera_o_mes_ter_curva_avaliada_com_as_vivas(monkeypatch, worker_wb):
    # sem nenhum dia de curva com as vivas, a entrada vazia ainda não foi separada: o servidor subiria Ipv29–32 inflado
    # logo depois do deploy (as vivas só começam a ser gravadas no dia seguinte)
    monkeypatch.setenv("FALHAS_WORKBOOK", "1")
    app._falhas_publicar("2026-09", monta(store(d01=[ev("Ipv1", "08:00")])), ["2026-09"])
    app._falhas_publicar_workbook(["2026-09"])
    assert worker_wb == []


def test_pacote_diz_os_dias_de_curva_com_as_vivas():
    p = monta(store(d01=[ev("Ipv1", "08:00")]), mortas={**curva("02", [], vivas=24), **curva("03", [], vivas=None)})
    assert p["strings"]["dias_com_vivas"] == ["2026-09-02"]


def test_curva_do_2c_nao_conta_como_dia_com_vivas(monkeypatch):
    # a curva do 2C vem do disco e sempre tem as vivas: contando ela, a trava do workbook nunca segurava nada
    monkeypatch.setattr(falhas_job, "_CACHE_2C", {})          # o cache do módulo guarda o 2C dos testes anteriores
    serie = [(f"{h:02d}:{m:02d}", 8.0) for h in range(7, 17) for m in (0, 10, 20, 30, 40, 50)]
    hist = lambda dia: {"strings": {"TUP": {"1.1": {f"{i}": serie for i in range(1, 5)}}}}
    p = falhas_job.montar(app, sol, "2026-09-01", "2026-09-02", geracao={}, str_store={}, trk_store={}, book={},
                          hist_2c=hist, mortas_curva={}, log=lambda m: None)
    assert p["strings"]["dias_com_vivas"] == []



# ── volta só com prova (28/09/2026, pedido do Levi sobre a MAB100 3.9 e a MTS100) ──────────────────────────────────
# "As strings 3 e 4 não voltaram e caíram de novo dia 25, estiveram sempre sem corrente nesse dia!" A régua fechava o
# episódio como "voltou de madrugada" sempre que a queda do dia seguinte começava depois das 07:30 — e começava tarde
# porque a PRODUÇÃO do inversor começou tarde (dia fechado: MAB100 25/09, 08:30) ou a 1ª leitura chegou tarde. Em
# setembro eram 262 voltas "sem hora" seguidas de queda nova no mesmo dia. Volta só com prova de corrente.

def test_producao_que_comeca_tarde_nao_inventa_volta_de_madrugada():
    mortas = {**curva("01", [morta("ST 03", saiu="07:00", sempre_zero=False, ini="07:00")], vivas=21),
              **curva("02", [morta("ST 03", saiu="08:30", sempre_zero=False, ini="08:30")], vivas=21)}
    (e,) = episodios(monta({}, mortas=mortas), string="ST 03")
    assert e["inicio"] == "2026-09-01 07:00" and e["fim"] is None
    assert not any("volta de manhã" in f for f in e["flags"])          # não houve volta nenhuma


def test_curva_sem_hora_de_producao_continua_se_caiu_de_manha():
    # as curvas de 24 a 26/09 foram gravadas antes de a régua guardar a hora em que o inversor começou a gerar
    velha = {"inversor": "Inversor 3.3", "string": "ST 03", "saiu": "08:30", "voltou": None, "min_morta": 500,
             "trechos": [["08:30", None]], "criterio": {"zerada": 500, "abaixo_das_vizinhas": 0}, "fim_producao": "17:00"}
    st = store(d01=[ev("ST 03", "06:30")])
    mortas = {"2026-09-02": {"pv": {PID: {"usina": "Inhapi", "ts": 0, "mortas": [velha]}}}}
    (e,) = episodios(monta(st, mortas=mortas), string="ST 03")
    assert e["inicio"] == "2026-09-01 06:30" and e["fim"] is None


def test_quedas_gravadas_que_caem_de_manha_continuam_o_episodio():
    (e,) = episodios(monta(store(d01=[ev("Ipv1", "10:40")], d02=[ev("Ipv1", "08:10", "15:00")])))
    assert (e["inicio"], e["fim"]) == ("2026-09-01 10:40", "2026-09-02 15:00")


def test_queda_nova_a_tarde_no_dia_seguinte_e_outro_episodio():
    # a string gerou a manhã inteira e morreu de novo às 16h: essa volta tem prova
    assert len(episodios(monta(store(d01=[ev("Ipv1", "14:00")], d02=[ev("Ipv1", "14:00", "17:30")])))) == 2


def test_registro_da_madrugada_sem_producao_nao_fecha_o_episodio():
    # Assis 5.1, 28/09: o worker leu a usina à meia-noite (nada gerando) e o registro valia como "a usina apareceu e a
    # string não estava zerada" — fechava tudo como "voltou 28/09 06:40, de madrugada"
    mortas = curva("02", [], vivas=None)
    (e,) = episodios(monta(store(d01=[ev("Ipv1", "07:00")]), mortas=mortas))
    assert e["fim"] is None and e["fim_motivo"] == "em aberto"


def test_sombra_do_registro_nao_vira_episodio_e_fica_listada():
    # 29/09: a régua sobre a curva separa a sombra que cresce devagar (MAB100 ST07) — ela vem em `sombras`, não em
    # `mortas`, e a montagem só lista
    c = curva("02", [], vivas=24)
    c["2026-09-02"]["pv"][PID]["sombras"] = [{"inversor": "Inversor 3.3", "string": "Ipv7", "saiu": "14:20",
                                               "voltou": None, "min": 140, "entrada_min": 110, "saida_min": None}]
    p = monta({}, mortas=c, fim="2026-09-02")
    assert episodios(p, "Ipv7") == []
    (s,) = p["strings"]["sombras"]
    assert (s["dia"], s["string"], s["entrada_min"]) == ("2026-09-02", "Ipv7", 110)
    assert p["strings"]["qualidade"]["sombra (entrou ou saiu em rampa): fora"] == 1


def _sombra(st, saiu="14:20", voltou=None, inv="Inversor 3.3"):
    return {"inversor": inv, "string": st, "saiu": saiu, "voltou": voltou, "min": 140, "entrada_min": 110,
            "saida_min": None}


def test_sombra_que_amanhece_morta_e_falha_que_comecou_devagar():
    # MTS100 3.7 ST11 a ST13: caíram devagar em 22/09 à tarde e passaram o 23 inteiro sem corrente
    c = curva("01", [], vivas=24)
    c["2026-09-01"]["pv"][PID]["sombras"] = [_sombra("Ipv7")]
    c.update(curva("02", [morta("Ipv7", saiu="06:30", ini="06:30")], vivas=24))
    (e,) = episodios(monta({}, mortas=c, fim="2026-09-02"), "Ipv7")
    assert e["inicio"] == "2026-09-01 14:20" and e["fim"] is None
    assert falhas_job.FLAG_DEVAGAR in e["flags"]
    assert monta({}, mortas=c, fim="2026-09-02")["strings"]["sombras"] == []


def test_sombra_que_volta_no_mesmo_dia_nao_vira_falha_nem_com_queda_no_dia_seguinte():
    c = curva("01", [], vivas=24)
    c["2026-09-01"]["pv"][PID]["sombras"] = [_sombra("Ipv7", voltou="16:40")]
    c.update(curva("02", [morta("Ipv7", saiu="06:30", ini="06:30")], vivas=24))
    (e,) = episodios(monta({}, mortas=c, fim="2026-09-02"), "Ipv7")
    assert e["inicio"].startswith("2026-09-02")          # só a queda do dia 02
