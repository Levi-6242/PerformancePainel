# -*- coding: utf-8 -*-
"""Análise das usinas, entrega 2 (26/11/2026, docs/analise-das-usinas.md): as contas puras do diagnóstico da usina — as
ocorrências do COS da usina, a perda de cada uma (inversor pelos outros, queda pela POA, estimativa sem curva), o dia a
dia dos inversores contra os outros, o inversor zerado sem ocorrência, os dias sem explicação (85% da meta), a vegetação
da última ronda e os ofensores com o que os cobre. Usinas e números de mentira; o caso real (Santarém 2, novembro) onde
serve de régua."""
from datetime import date

import pytest

import analise_usinas as A


def test_os_trechos_de_uma_ocorrencia_viram_janelas_em_minutos():
    assert A.janelas("12:24-13:30; 14:00-14:10") == [(744, 810), (840, 850)]
    assert A.janelas("07:30-17:30") == [(450, 1050)]
    assert A.janelas("") == [] and A.minuto("07:30") == 450


DISP = {"periodo": ["2026-11-01", "2026-11-03"],
        "diario": {"Santarém 2": {"2026-11-02": {"disp": 89.7, "h_eq": 1.03, "os": [{"folio": 16958, "h": 1.03, "trechos": "07:30-17:30"}]},
                                  "2026-11-03": {"disp": 80.0, "h_eq": 2.0, "os": [{"folio": "16958", "h": 1.03, "trechos": "07:30-17:30"},
                                                                                   {"folio": 18501, "h": 0.97, "trechos": "16:33-17:30"}]}}},
        "oss": [{"folio": 16958, "tipos": ["desligamento de inversor"], "origem": "equipamento", "aberta": True,
                 "ini": "2026-07-12T06:00:00", "fim": None, "protecoes": [],
                 "escopo": [{"usina": "Santarém 2", "rotulo": "Inversor 2.7", "kwp": 361.3}]},
                {"folio": 18501, "tipos": ["desligamento de cabine"], "origem": "queda", "aberta": False,
                 "ini": "2026-11-03T16:33:00", "fim": "2026-11-03T17:30:00", "protecoes": ["81", "47"],
                 "escopo": [{"usina": "Santarém 2", "rotulo": "Usina inteira", "kwp": 3510}]}]}


def test_as_ocorrencias_da_usina_saem_uma_por_os_e_dia_com_o_escopo_dela():
    l = A.ocorrencias_usina(DISP, "santarem 2", hoje=date(2026, 11, 26))
    assert [(o["dia"], o["os"], o["escopo"]) for o in l] == [("2026-11-02", "16958", "Inversor 2.7"), ("2026-11-03", "16958", "Inversor 2.7"),
                                                             ("2026-11-03", "18501", "Usina inteira")]
    inv, queda = l[0], l[2]
    assert inv["aberta"] and inv["dias_aberta"] == 137 and inv["tipo"] == "desligamento de inversor"
    assert queda["prot"] == "81; 47" and queda["origem"] == "queda" and not queda["aberta"] and queda["dias_aberta"] is None
    assert A.ocorrencias_usina(None, "Santarém 2") == [] and A.ocorrencias_usina(DISP, "Outra") == []


def test_o_inversor_parado_geraria_a_mediana_dos_outros_no_dia():
    # Santarém 2 em 01/11/2026 (BD_Thopen): o 2.7 zerado e os outros nove entre 2.195 e 2.320 kWh
    dia = {"Inversor 2.1": 2260.87, "Inversor 2.10": 2235.45, "Inversor 2.2": 2232.27, "Inversor 2.3": 2195.72, "Inversor 2.4": 2201.16,
           "Inversor 2.5": 2217.05, "Inversor 2.6": 2320.85, "Inversor 2.7": 0.0, "Inversor 2.8": 2298.87, "Inversor 2.9": 2308.86}
    assert A.perda_inversor(dia, "inversor 2.7") == {"geraria": 2235, "gerou": 0, "perda": 2235, "metodo": "inversor"}
    assert A.perda_inversor(dia, "Inversor 2.6")["perda"] == 0          # acima dos outros: perda nunca negativa
    assert A.perda_inversor(dia, "Inversor 9.9") is None and A.perda_inversor({"Inversor 2.7": 0}, "Inversor 2.7") is None


def test_a_queda_geraria_a_razao_da_hora_em_volta_vezes_a_poa_da_janela():
    poa = {m: 800.0 for m in range(600, 905, 5)}
    pot = {m: (0.0 if 720 <= m < 780 else 2.0 * poa[m]) for m in poa}   # parou das 12:00 às 13:00
    p = A.perda_queda(pot, poa, [(720, 780)])
    assert p == {"geraria": 1600, "gerou": 0, "perda": 1600, "metodo": "queda"}      # 12 passos × 1.600 kW × 5 min
    assert A.perda_queda(pot, {m: 10.0 for m in poa}, [(720, 780)]) is None        # sem sol em volta: sem razão
    assert A.perda_queda(pot, poa, []) is None


def test_sem_curva_a_queda_e_estimada_pela_fatia_do_sol_do_dia():
    assert A.fracao_do_sol([(360, 1080)]) == pytest.approx(1.0)
    assert A.fracao_do_sol([(360, 720)]) == pytest.approx(0.5)                     # céu limpo: o seno é simétrico
    # com a POA de outros dias, a média da fatia deles (a régua do mockup aprovado)
    dia = {m: (1000.0 if 600 <= m < 840 else 0.0) for m in range(300, 1200, 5)}
    assert A.fracao_do_sol([(600, 720)], [dia, dia]) == pytest.approx(0.5)
    assert A.perda_estimada(20.0, 0.04) == {"geraria": 800, "gerou": None, "perda": 800, "metodo": "dia_tipico"}
    assert A.perda_estimada(None, 0.04) is None


def test_o_dia_a_dia_de_cada_inversor_e_contra_a_mediana_dos_outros():
    m = A.matriz_inversores({"2026-11-01": {"I1": 100, "I2": 100, "I3": 50}, "2026-11-02": {"I1": 100, "I2": 100}})
    assert m["I3"] == [0.5, None] and m["I1"] == [1.333, 1.0]       # 3 casas: 100 ÷ a mediana de 100 e 50
    # com o kWp, pela energia por kWp: o inversor de metade do tamanho que gera metade está junto dos outros
    k = A.matriz_inversores({"d": {"G": 200, "P": 100, "H": 200}}, {"G": 100, "P": 50, "H": 100})
    assert k["P"] == [1.0]


def test_o_inversor_zerado_sem_ocorrencia_do_cos_e_achado():
    dias = {"2026-11-02": {"I1": 2000, "I2": 2100, "I3": 0.0}, "2026-11-03": {"I1": 2000, "I2": 2100, "I3": 1.0},
            "2026-11-04": {"I1": 20, "I2": 21, "I3": 0.0}}                      # 04/11: os outros quase sem sol
    oc = [{"dia": "2026-11-03", "escopo": "I3"}]
    assert A.parados_sem_ocorrencia(dias, [dict(oc[0], escopo="Inversor I3")]) == [("2026-11-02", "I3"), ("2026-11-03", "I3")]
    assert A.parados_sem_ocorrencia({"2026-11-03": {"Inversor 1.1": 0, "Inversor 1.2": 900, "Inversor 1.3": 900}},
                                    [{"dia": "2026-11-03", "escopo": "Inversor 1.1"}]) == []


def test_o_dia_sem_explicacao_e_o_pr_mais_as_ocorrencias_abaixo_de_85_por_cento_da_meta():
    dias = [{"d": 1, "pr": 0.60, "poa": 5.0}, {"d": 2, "pr": 0.60, "poa": 5.0}, {"d": 3, "pr": 0.75, "poa": 5.0},
            {"d": 4, "pr": None, "poa": 5.0}, {"d": 5, "pr": 0.10, "poa": 0.1}]
    # meta 83,3%: o limite é 70,8%. No dia 2 as ocorrências tiraram 2 MWh = 2 ÷ (5 × 3,256) = 12,3 p.p. → 72,3%, explicado
    assert A.dias_sem_explicacao(dias, {2: 2.0}, 3.256, 0.833) == [1]
    assert A.dias_sem_explicacao(dias, {}, None, 0.833) == [] and A.dias_sem_explicacao(dias, {}, 3.256, None) == []


ZEL = [{"semana": "2026-W47", "usina_id": 122.0, "vegetacao_nivel": 3, "sujidade_nivel": 2, "data_id_leitura": 20261119,
        "os": 20100, "situacao_vegetacao": "feita", "data_id_situacao_vegetacao": 20261120},
       {"semana": "2026-W48", "usina_id": 122, "vegetacao_nivel": 4.0, "sujidade_nivel": 4, "data_id_leitura": 20261125.0,
        "os": 20363.0, "recomendacao": "supressao_vegetal;limpeza_modulos", "situacao_vegetacao": "a_programar",
        "data_id_prazo_vegetacao": 20261202, "data_id_ultima_supressao": None, "data_id_ultima_limpeza": 20261010},
       {"semana": "2026-W48", "usina_id": 66, "vegetacao_nivel": 1}]


def test_a_vegetacao_e_a_da_ultima_ronda_da_usina_na_zeladoria_do_nexus():
    v = A.vegetacao(ZEL, 122)
    assert v["semana"] == "2026-W48" and v["leitura"] == "2026-11-25" and v["os"] == "20363"
    assert v["vegetacao"] == 4 and v["sujidade"] == 4 and v["sit_veg"] == "a programar" and v["prazo_veg"] == "2026-12-02"
    assert v["ult_supressao"] is None and v["ult_limpeza"] == "2026-10-10"
    assert A.vegetacao(ZEL, "122") == v and A.vegetacao(ZEL, 999) is None and A.vegetacao(ZEL, None) is None


def _ocorr():
    return [{"dia": "2026-11-02", "os": "16958", "escopo": "Inversor 2.7", "aberta": True, "ini": "2026-07-12T06:00:00",
             "dias_aberta": 137, "perda": 2235},
            {"dia": "2026-11-03", "os": "16958", "escopo": "Inversor 2.7", "aberta": True, "ini": "2026-07-12T06:00:00",
             "dias_aberta": 137, "perda": 2100},
            {"dia": "2026-11-03", "os": "18501", "escopo": "Usina inteira", "aberta": False, "perda": 830}]


def test_os_ofensores_trazem_o_que_os_cobre_e_vem_do_que_tira_mais_energia():
    ep = [{"inversor": "Inversor 2.10", "string": "ST 05", "perda_kwh": 900, "fim": None},
          {"inversor": "Inversor 2.5", "string": "ST 15", "perda_kwh": 300, "fim": "2026-11-20 10:00"}]
    sos = [{"inversor": "inversor 2.5", "os": "19001", "status": "Em andamento"}, {"inversor": "Inversor 2.10", "os": "1", "status": "Cancelada"}]
    trk = [{"tracker": "Tracker 51", "perda_kwh": 5000, "h_sol": 80, "fim": None}, {"tracker": "Tracker 7", "perda_kwh": 1000, "h_sol": 10, "fim": "x"}]
    ch = [{"tracker": "51", "desde": "20/04/2026"}]
    of = A.ofensores(_ocorr(), ep, sos, trk, ch, A.vegetacao(ZEL, 122))
    assert [o["t"] for o in of] == ["Tracker parado", "Inversor parado", "String sem corrente", "Vegetação alta"]
    trk_o, inv_o, str_o, veg_o = of
    assert trk_o["cob"]["tom"] == "alerta" and "Tracker 7" in trk_o["cob"]["txt"] and trk_o["kwh"] == 6000
    # o inversor parado é coberto pela ocorrência do COS (a queda não entra aqui): 4.335 kWh, 2 dias
    assert inv_o["cob"] == {"tom": "ok", "txt": "Ocorrência do COS: OS 16958 aberta"} and inv_o["kwh"] == 4335
    assert inv_o["p"] == "Cobrar a OS 16958 (Inversor 2.7)." and "há 137 dias" in inv_o["s"]
    # a OS cancelada do 2.10 não cobre: só o 2.5 tem OS de string
    assert str_o["cob"]["tom"] == "alerta" and str_o["cob"]["txt"].endswith("para 2.10")
    assert veg_o["sev"] == "alerta" and veg_o["cob"] == {"tom": "critico", "txt": "Supressão a programar (prazo 02/12)"}


def test_o_inversor_zerado_sem_ocorrencia_descobre_o_ofensor():
    of = A.ofensores(_ocorr(), [], [], [], [], None, [("2026-11-05", "Inversor 2.3")])
    assert len(of) == 1 and of[0]["cob"]["tom"] == "critico" and "Inversor 2.3" in of[0]["cob"]["txt"]
    assert of[0]["p"] == "Abrir a ocorrência no COS para Inversor 2.3."
    assert A.ofensores([], [], [], [], [], None) == []


def test_vegetacao_ate_3_ou_com_a_supressao_programada_nao_pede_acao():
    assert A.ofensores([], [], [], [], [], {"vegetacao": 3, "leitura": "2026-11-25"}) == []
    v = A.ofensores([], [], [], [], [], {"vegetacao": 5, "leitura": "2026-11-25", "sit_veg": "programada", "data_sit_veg": "2026-11-28"})[0]
    assert v["sev"] == "critico" and v["cob"] == {"tom": "ok", "txt": "Supressão programada em 28/11"}


def test_as_observacoes_dizem_a_meta_que_mudou_a_ultima_ronda_e_os_dias_sem_explicacao():
    mensal = {"pontos": [{"ano": 2026, "mes": 10, "meta": 0.774}, {"ano": 2026, "mes": 11, "meta": 0.833}]}
    ob = A.observacoes(mensal, 2026, 11, {"nao_explicado": -126.6}, A.vegetacao(ZEL, 122), [3, 18])
    assert [o["t"] for o in ob] == ["A meta de PR subiu", "A conta dos expurgos estourou", "Última ronda", "Dias sem explicação"]
    assert ob[0]["s"] == "77,4% no mês anterior, 83,3% neste"
    assert ob[2]["s"].startswith("25/11 (OS 20363): vegetação 4, sujidade 4") and "última limpeza 10/10" in ob[2]["s"]
    assert ob[3]["s"].startswith("03, 18:")
    assert A.observacoes({"pontos": []}, 2026, 1, None, None, []) == []


def test_a_perda_estimada_das_quedas_do_dia_nunca_passa_do_que_faltou_na_geracao():
    # Colider 1 (26/11/2026): OS de religamento abertas contando a usina inteira parada o dia todo, e a usina gerando
    dias = [{"iso": "2026-11-01", "ger": 12.7, "poa": 7.3, "pr": 0.515}, {"iso": "2026-11-02", "ger": 15.3, "poa": 7.25, "pr": 0.624},
            {"iso": "2026-11-03", "ger": 17.3, "poa": 7.2, "pr": 0.710}, {"iso": "2026-11-04", "ger": 16.0, "poa": 7.0, "pr": 0.676},
            {"iso": "2026-11-06", "ger": 15.0, "poa": 0, "pr": None}]
    est = dict(escopo="Usina inteira", metodo="dia_tipico")
    oc = [dict(est, dia="2026-11-01", perda=12700), dict(est, dia="2026-11-01", perda=12700),
          {"dia": "2026-11-01", "escopo": "Inversor 1.1", "perda": 900, "metodo": "inversor"}, dict(est, dia="2026-11-03", perda=500),
          {"dia": "2026-11-03", "escopo": "Usina inteira", "perda": 191, "metodo": "queda"}, dict(est, dia="2026-11-06", perda=15000)]
    A.teto_das_quedas(oc, dias, 3.3825)
    # o PR típico = a mediana dos dias SEM ocorrência (02 e 04): 0,650; no dia 01 faltou (7,3 × 3,3825 × 0,650 − 12,7) MWh
    falta = (7.3 * 3.3825 * 0.65 - 12.7) * 1000
    assert oc[0]["perda"] + oc[1]["perda"] == pytest.approx(falta, abs=2) and oc[0]["limitada"]
    assert oc[2]["perda"] == 900 and "limitada" not in oc[2]                           # o inversor parado é dado real
    assert oc[3]["perda"] == 0 and oc[3]["limitada"]                                   # 03/11 acima do típico: não faltou nada
    assert oc[4]["perda"] == 191 and "limitada" not in oc[4]                           # a queda medida pela curva fica
    # 06/11 sem POA: o teto é a geração típica do mês (a mediana dos dias que geraram, 15,3 MWh) menos a do dia
    assert oc[5]["perda"] == 300 and oc[5]["limitada"]


def test_a_ocorrencia_que_nao_bate_com_a_geracao_vira_observacao():
    oc = [{"os": "17740", "limitada": True, "perda": 0}, {"os": "17732", "limitada": True, "perda": 0},
          {"os": "18501", "limitada": True, "perda": 300}, {"os": "16958", "perda": 2000}]
    ob = A.observacoes({"pontos": []}, 2026, 11, None, None, [], oc)
    assert [o["t"] for o in ob] == ["Ocorrência que não bate com a geração"] and ob[0]["s"].startswith("OS 17732, 17740:")


def test_o_pr_expurgado_devolve_a_energia_das_quedas_da_rede():
    # Levi, 26/11/2026: "Tem a geração com expurgos, mas e o PR com expurgos". PR 70% com 100 MWh e 5 MWh de queda da rede
    # = 70 × 105 ÷ 100 = 73,5%; sem queda, igual ao PR; sem PR ou sem geração, não há conta
    assert A.pr_expurgado(70.0, 100.0, 5.0) == {"pr": 73.5, "delta": 3.5, "mwh": 5.0}
    assert A.pr_expurgado(70.0, 100.0, 0) == {"pr": 70.0, "delta": 0.0, "mwh": 0.0}
    assert A.pr_expurgado(None, 100.0, 5.0) is None and A.pr_expurgado(70.0, 0, 5.0) is None
