# -*- coding: utf-8 -*-
"""Réguas da disponibilidade Fracttal × BD (plataforma/disponibilidade.py).

Cada teste trava uma decisão fechada com o Levi na análise de 25-26/08/26 — se um refactor
mudar o comportamento, é regressão de régua, não detalhe de implementação.
Datas das fixtures em UTC (+00:00), como o Fracttal manda; o módulo converte p/ local (-3).
"""
import json
import os
from datetime import datetime

import pytest

from disponibilidade import calcular

# período de teste: julho/2026 inteiro, visto de meados de agosto (mês fechado)
PER_INI = datetime(2026, 7, 1)
PER_FIM = datetime(2026, 8, 1)
AGORA = datetime(2026, 8, 15, 12, 0)
DIAS = 31
TOT_H = 12.0 * DIAS

# catálogo sintético: Alfa (1000 kWp, UG1=600/UG2=400, inv 1.1=300/2.1=200) + Beta 1 e 2
# (site Fracttal agrupado, 500 kWp cada)
EQUIP = [
    {"cliente": "TesteCo", "usina": "Alfa", "usina_fracttal": "TesteCo - Alfa 1 - SP",
     "equipamento": "UFV", "pot_kwp": 1000.0, "n_inv": 2, "full_om": "Sim"},
    {"cliente": "TesteCo", "usina": "Alfa", "usina_fracttal": "TesteCo - Alfa 1 - SP",
     "equipamento": "UG 01", "pot_kwp": 600.0},
    {"cliente": "TesteCo", "usina": "Alfa", "usina_fracttal": "TesteCo - Alfa 1 - SP",
     "equipamento": "UG 02", "pot_kwp": 400.0},
    {"cliente": "TesteCo", "usina": "Alfa", "usina_fracttal": "TesteCo - Alfa 1 - SP",
     "equipamento": "Inversor 1.1", "parente": "UG 01", "pot_kwp": 300.0},
    {"cliente": "TesteCo", "usina": "Alfa", "usina_fracttal": "TesteCo - Alfa 1 - SP",
     "equipamento": "Inversor 2.1", "parente": "UG 02", "pot_kwp": 200.0},
    {"cliente": "TesteCo", "usina": "Beta 1", "usina_fracttal": "TesteCo - Beta 1 e 2 - RN",
     "equipamento": "UFV", "pot_kwp": 500.0, "n_inv": 4, "full_om": "Sim"},
    {"cliente": "TesteCo", "usina": "Beta 2", "usina_fracttal": "TesteCo - Beta 1 e 2 - RN",
     "equipamento": "UFV", "pot_kwp": 500.0, "n_inv": 4, "full_om": "Sim"},
]


def task(**kw):
    """task do Fracttal com defaults de religamento concluído na usina Alfa."""
    base = {"tasks_log_task_type_main": "Religamento", "id_status_work_order": 3,
            "event_date": None, "date_maintenance": None,
            "final_date": None, "wo_final_date": None, "creation_date": None,
            "code": "TC-ALF100", "items_log_description": "TesteCo - Alfa 1 - SP  Endereço",
            "groups_1_description": "TesteCo - Alfa 1 - SP", "description": "Religamento da Usina"}
    base.update(kw)
    return base


def roda(wos):
    return calcular(wos, EQUIP, PER_INI, PER_FIM, agora=AGORA)


def so_alfa(r):
    return next(u for u in r["usinas"] if u["usina"] == "Alfa")


def a_os(r, folio):
    return next(o for o in r["oss"] if o["folio"] == folio)


# ── janela solar ─────────────────────────────────────────────────────────────
def test_usina_inteira_seis_horas_solares():
    # 10/07 09:00→15:00 local (12:00Z→18:00Z) = 6 h dentro da janela 06–18
    r = roda({"1": [task(event_date="2026-07-10T12:00:00+00:00",
                         final_date="2026-07-10T18:00:00+00:00")]})
    o = a_os(r, 1)
    assert o["h_solar"] == pytest.approx(6.0)
    assert o["kwh"] == pytest.approx(6000, rel=1e-3)
    assert so_alfa(r)["disp"] == pytest.approx(100 * (1 - 6.0 / TOT_H), abs=0.01)


def test_parada_noturna_nao_conta():
    # 20:00→23:00 local = fora da janela → 0 h, mas a OS segue listada
    r = roda({"2": [task(event_date="2026-07-10T23:00:00+00:00",
                         final_date="2026-07-11T02:00:00+00:00")]})
    assert a_os(r, 2)["h_solar"] == 0.0
    assert so_alfa(r)["disp"] == 100.0


def test_parada_atravessa_a_noite():
    # 17:00 local dia 10 → 07:00 local dia 11 = 1 h + 1 h
    r = roda({"3": [task(event_date="2026-07-10T20:00:00+00:00",
                         final_date="2026-07-11T10:00:00+00:00")]})
    assert a_os(r, 3)["h_solar"] == pytest.approx(2.0)


# ── datas: as pegadinhas do Fracttal ─────────────────────────────────────────
# Evento DEPOIS do fim (Levi, 15/10/2026: "no caso de OSs com diferenças negativas (evento foi depois do fim da OS) será
# considerado a data de criação como data do evento"). Substitui as duas réguas de antes: o "relâmpago" (até 1 h antes
# = duração 0) e o "fim muito antes do início" (fim descartado).
def alinhar(r, folio):
    return [a for a in r["alinhar"] if a["folio"] == folio]


def test_evento_depois_do_fim_usa_a_criacao_como_evento():
    # evento 10/07 09:00:40 local, fim 09:00:00, criada 08:00 → de 08:00 a 09:00 = 1 h
    r = roda({"4": [task(event_date="2026-07-10T12:00:40+00:00", final_date="2026-07-10T12:00:00+00:00",
                         creation_date="2026-07-10T11:00:00+00:00")]})
    o = a_os(r, 4)
    assert o["excl"] is None and o["ini"] == "2026-07-10T08:00:00"
    assert o["h_solar"] == pytest.approx(1.0)
    assert so_alfa(r)["h_perdidas"] == pytest.approx(1.0)
    (a,) = alinhar(r, 4)
    assert "criação" in a["motivo"]


def test_evento_dias_depois_do_fim_tambem_usa_a_criacao():
    # evento 20/07, fim 10/07 15:00 local, criada 10/07 09:00 local → 6 h no dia 10 (antes, o fim era descartado)
    r = roda({"8": [task(event_date="2026-07-20T12:00:00+00:00", final_date="2026-07-10T18:00:00+00:00",
                         creation_date="2026-07-10T12:00:00+00:00")]})
    assert a_os(r, 8)["h_solar"] == pytest.approx(6.0)
    assert r["diario"]["Alfa"]["2026-07-10"]["h_eq"] == pytest.approx(6.0)


def test_fim_antes_ate_da_criacao_conta_zero_e_vai_para_alinhar():
    r = roda({"10": [task(event_date="2026-07-10T15:00:00+00:00", final_date="2026-07-10T12:00:00+00:00",
                          creation_date="2026-07-11T12:00:00+00:00")]})
    o = a_os(r, 10)
    assert o["excl"] is None and o["h_solar"] == 0.0
    assert so_alfa(r)["disp"] == 100.0
    (a,) = alinhar(r, 10)
    assert "antes" in a["motivo"] and "criação" in a["motivo"]


def test_fim_antes_do_evento_sem_criacao_conta_zero_e_vai_para_alinhar():
    r = roda({"11": [task(event_date="2026-07-10T15:00:00+00:00", final_date="2026-07-10T12:00:00+00:00")]})
    assert a_os(r, 11)["h_solar"] == 0.0
    assert alinhar(r, 11)


def test_wo_final_date_nao_estica_a_parada():
    # final_date 1 h depois; wo_final_date (carimbo da WO) 10 dias depois → vale o final_date
    r = roda({"5": [task(event_date="2026-07-10T12:00:00+00:00",
                         final_date="2026-07-10T13:00:00+00:00",
                         wo_final_date="2026-07-20T14:00:00+00:00")]})
    o = a_os(r, 5)
    assert o["h_solar"] == pytest.approx(1.0)
    assert not any("wo_final_date" in f for f in o["flags"])


def test_sem_final_date_cai_no_wo_final_com_flag():
    r = roda({"6": [task(event_date="2026-07-10T12:00:00+00:00",
                         wo_final_date="2026-07-10T14:00:00+00:00")]})
    o = a_os(r, 6)
    assert o["h_solar"] == pytest.approx(2.0)
    assert any("wo_final_date" in f for f in o["flags"])


def test_em_janeiro_o_dezembro_ainda_conta_as_os_concluidas_nele():
    # revisão adversarial de 11/10/2026: o fim só valia no ano de AGORA, e o índice do Gerencial é refeito com o relógio
    # de agora. A partir de 01/01, toda OS concluída em dezembro virava "OS concluída sem data final válida" e o
    # dezembro saía 100% em todos os dias — no Gerencial e na aba disponibilidade_dia do workbook de falhas
    wos = {"7": [task(event_date="2026-12-15T12:00:00+00:00", final_date="2026-12-15T15:00:00+00:00")]}
    ini, fim = datetime(2026, 12, 1), datetime(2027, 1, 1)
    em_dezembro = calcular(wos, EQUIP, ini, fim, agora=datetime(2026, 12, 31, 12, 0))
    em_janeiro = calcular(wos, EQUIP, ini, fim, agora=datetime(2027, 1, 5, 12, 0))
    for r in (em_dezembro, em_janeiro):
        assert a_os(r, 7)["excl"] is None
        assert r["diario"]["Alfa"]["2026-12-15"]["h_eq"] == pytest.approx(3.0)
        assert r["diario"]["Alfa"]["2026-12-15"]["disp"] == 75.0
        assert so_alfa(r)["disp"] == pytest.approx(99.19, abs=0.005)       # 3 h de 12 h × 31 dias
    assert em_janeiro == em_dezembro


def test_fim_digitado_num_ano_antes_do_evento_segue_fora_e_vale_o_wo_final():
    # "houve fim digitado como 2027 e 2025 na fase RDO" (docs/disponibilidade-por-os.md): o fim de um ano ANTES do
    # evento não é fim. Sem final_date válido vale o carimbo da WO, como antes — aceitar todo fim do ano anterior (e não
    # só o da OS cujo evento é do ano anterior) trocaria este caso por "fim muito antes do início" e tiraria a OS
    r = roda({"9": [task(event_date="2026-07-10T12:00:00+00:00", final_date="2025-07-10T14:00:00+00:00",
                         wo_final_date="2026-07-10T14:00:00+00:00")]})
    o = a_os(r, 9)
    assert o["excl"] is None and o["h_solar"] == pytest.approx(2.0)
    assert any("wo_final_date" in f for f in o["flags"])


# OS aberta CONTA (Levi, 15/10/2026: "Será considerado OSs fechadas e abertas"). Desde 26/08 ela valia 0 h e ia para um
# "cenário" à parte; e no mês seguinte sumia de tudo (o fim = início a tirava do período): a 16338, Inversor 2.2 de
# Ipixuna 2, aberta desde 16/09, não aparecia em outubro. Agora conta do evento até o fim do período (no mês corrente,
# até ontem) em todo mês em que seguir aberta, e vai para a lista "alinhar" com os dias em aberto.
def test_aberta_sem_fim_conta_ate_o_fim_do_periodo():
    r = roda({"7": [task(id_status_work_order=1, event_date="2026-07-20T12:00:00+00:00")]})
    o = a_os(r, 7)
    assert o["excl"] is None and o["aberta"] is True
    # 20/07 09:00 local até 31/07 → 9 h do dia 20 + 11 dias × 12 h = 141 h
    assert o["h_solar"] == pytest.approx(141.0, abs=0.01)
    assert so_alfa(r)["disp"] == pytest.approx(100 * (1 - 141.0 / TOT_H), abs=0.01)
    (a,) = alinhar(r, 7)
    assert "aberta" in a["motivo"] and a["dias_aberta"] == 26      # 20/07 09:00 → 15/08 12:00
    assert "cenario_abertas" not in r


def test_aberta_do_mes_anterior_conta_no_mes_seguinte():
    # agosto até ontem (agora = 15/08 12:00 → período 01/08 a 15/08 00:00): 14 dias × 12 h
    wos = {"7": [task(id_status_work_order=1, event_date="2026-07-20T12:00:00+00:00")]}
    r = calcular(wos, EQUIP, datetime(2026, 8, 1), datetime(2026, 8, 15), agora=AGORA)
    assert a_os(r, 7)["h_solar"] == pytest.approx(168.0, abs=0.01)
    assert so_alfa(r)["disp"] == 0.0
    assert alinhar(r, 7)


def test_aberta_com_fim_na_tarefa_vale_o_fim():
    # a WO segue aberta, mas a tarefa tem data final: vale a data final (a usina voltou), sem ir para "alinhar"
    r = roda({"12": [task(id_status_work_order=1, event_date="2026-07-10T12:00:00+00:00",
                          final_date="2026-07-10T14:00:00+00:00")]})
    assert a_os(r, 12)["h_solar"] == pytest.approx(2.0)
    assert not alinhar(r, 12)


def test_cancelada_fica_fora_mas_listada():
    r = roda({"8": [task(id_status_work_order=4,
                         event_date="2026-07-10T12:00:00+00:00",
                         final_date="2026-07-10T18:00:00+00:00")]})
    o = a_os(r, 8)
    assert o["excl"] == "OS cancelada"
    assert so_alfa(r)["disp"] == 100.0


def test_tipo_fora_do_escopo_nem_entra_no_universo():
    r = roda({"9": [task(tasks_log_task_type_main="Preventiva",
                         event_date="2026-07-10T12:00:00+00:00",
                         final_date="2026-07-15T18:00:00+00:00")]})
    assert all(o["folio"] != 9 for o in r["oss"])
    assert so_alfa(r)["disp"] == 100.0


# ── escopo pelo ativo ────────────────────────────────────────────────────────
def test_cabine_pesa_pela_ug():
    # CABN2 → UG 02 = 400 kWp → 6 h × 400 = 2.400 kWh
    r = roda({"10": [task(code="TC-ALF100-CABN2", items_log_description="Cabine 2   { TC-ALF100-CABN2 }",
                          event_date="2026-07-10T12:00:00+00:00",
                          final_date="2026-07-10T18:00:00+00:00")]})
    o = a_os(r, 10)
    assert o["kwh"] == pytest.approx(2400, rel=1e-3)
    assert so_alfa(r)["h_perdidas"] == pytest.approx(6 * 0.4, rel=1e-3)


def test_inversor_pesa_pelo_proprio_kwp():
    r = roda({"11": [task(code="TC-ALF100-INVR1.1",
                          items_log_description="Inversor 1.1   { TC-ALF100-INVR1.1 }",
                          event_date="2026-07-10T12:00:00+00:00",
                          final_date="2026-07-10T18:00:00+00:00")]})
    assert a_os(r, 11)["kwh"] == pytest.approx(1800, rel=1e-3)   # 6 h × 300 kWp


def test_sobreposicao_nao_passa_de_100_por_cento():
    # usina 09→11 local + cabine 1 (600) 10→12 local: h_eq = 1 + 1 + 0,6 = 2,6 (não 3,2)
    r = roda({"12": [task(event_date="2026-07-10T12:00:00+00:00",
                          final_date="2026-07-10T14:00:00+00:00")],
              "13": [task(code="TC-ALF100-CABN1", items_log_description="Cabine 1",
                          event_date="2026-07-10T13:00:00+00:00",
                          final_date="2026-07-10T15:00:00+00:00")]})
    assert so_alfa(r)["h_perdidas"] == pytest.approx(2.6, rel=1e-3)
    assert so_alfa(r)["kwh"] == pytest.approx(2600, rel=1e-3)


# ── sites agrupados ──────────────────────────────────────────────────────────
def test_site_agrupado_com_pista_na_descricao():
    r = roda({"14": [task(code="TC-BET100", groups_1_description="TesteCo - Beta 1 e 2 - RN",
                          items_log_description="TesteCo - Beta 1 e 2 - RN  Endereço",
                          description="Usina desligada — Beta 2, trip 27",
                          event_date="2026-07-10T12:00:00+00:00",
                          final_date="2026-07-10T18:00:00+00:00")]})
    o = a_os(r, 14)
    assert o["usinas"] == ["Beta 2"]
    beta1 = next(u for u in r["usinas"] if u["usina"] == "Beta 1")
    assert beta1["disp"] == 100.0


def test_site_agrupado_sem_pista_vale_para_o_grupo():
    r = roda({"15": [task(code="TC-BET100", groups_1_description="TesteCo - Beta 1 e 2 - RN",
                          items_log_description="TesteCo - Beta 1 e 2 - RN  Endereço",
                          description="Religamento da Usina",
                          event_date="2026-07-10T12:00:00+00:00",
                          final_date="2026-07-10T18:00:00+00:00")]})
    o = a_os(r, 15)
    assert o["usinas"] == ["Beta 1", "Beta 2"]
    assert any("sem pista" in f for f in o["flags"])


# ── agregação por cliente ────────────────────────────────────────────────────
def test_cliente_pondera_por_kwp():
    # 6 h de Alfa (1000 kWp) num parque TesteCo de 2000 kWp → ponderada
    r = roda({"16": [task(event_date="2026-07-10T12:00:00+00:00",
                          final_date="2026-07-10T18:00:00+00:00")]})
    cli = next(c for c in r["clientes"] if c["cliente"] == "TesteCo")
    esperado = 100 * (1 - (1000 * 6.0) / (2000 * TOT_H))
    assert cli["disp"] == pytest.approx(esperado, abs=0.01)
    assert cli["n_usinas"] == 3


def test_cabine_em_site_agrupado_identifica_a_usina():
    # Régua do Levi (27/08, OS 11461): site que agrupa usinas de 1 cabine cada — o Nº da
    # cabine É a usina ('CABN2' no site Beta 1 e 2 → usina Beta 2 INTEIRA, 500 kWp)
    r = roda({"17": [task(code="TC-BET100-CABN2", groups_1_description="TesteCo - Beta 1 e 2 - RN",
                          items_log_description="Cabine 2   { TC-BET100-CABN2 }",
                          description="Religamento da Cabine 2",
                          event_date="2026-07-10T12:00:00+00:00",
                          final_date="2026-07-10T18:00:00+00:00")]})
    o = a_os(r, 17)
    assert o["usinas"] == ["Beta 2"]
    assert o["kwh"] == pytest.approx(3000, rel=1e-3)          # 6 h × 500 kWp (usina inteira)
    beta1 = next(u for u in r["usinas"] if u["usina"] == "Beta 1")
    assert beta1["disp"] == 100.0
    beta2 = next(u for u in r["usinas"] if u["usina"] == "Beta 2")
    assert beta2["disp"] == pytest.approx(100 * (1 - 6.0 / TOT_H), abs=0.01)


# ── card do dia: quem criou + discriminação do escopo no payload ─────────────
def test_payload_traz_criador_e_escopo_discriminado():
    r = roda({"20": [task(code="TC-ALF100-CABN2", items_log_description="Cabine 2",
                          created_by="Juliana Cândido", personnel_description="Cláudio Silva",
                          event_date="2026-07-10T12:00:00+00:00",
                          final_date="2026-07-10T18:00:00+00:00")]})
    o = a_os(r, 20)
    assert o["criado_por"] == "Juliana Cândido"
    assert o["responsavel"] == "Cláudio Silva"
    assert o["escopo"] == [{"usina": "Alfa", "nivel": "cabine", "rotulo": "Cabine 2", "kwp": 400.0}]


# ── decomposição por ORIGEM (metodologia da Ana Patrícia, 29/08) ─────────────
def test_separa_disponibilidade_por_origem():
    # queda: usina inteira 6 h (dia 10) | equipamento: inversor 1.1 (300 kWp) 6 h (dia 12)
    r = roda({"30": [task(event_date="2026-07-10T12:00:00+00:00",
                          final_date="2026-07-10T18:00:00+00:00")],
              "31": [task(tasks_log_task_type_main="Corretiva Emergencial",
                          code="TC-ALF100-INVR1.1", items_log_description="Inversor 1.1",
                          event_date="2026-07-12T12:00:00+00:00",
                          final_date="2026-07-12T18:00:00+00:00")]})
    assert a_os(r, 30)["origem"] == "queda"
    assert a_os(r, 31)["origem"] == "equipamento"
    u = so_alfa(r)
    assert u["h_queda"] == pytest.approx(6.0)            # usina inteira
    assert u["h_equip"] == pytest.approx(1.8)            # 6 h × 300/1000
    assert u["h_perdidas"] == pytest.approx(7.8)
    assert u["disp_queda"] == pytest.approx(100 * (1 - 6.0 / TOT_H), abs=0.01)
    assert u["disp_equip"] == pytest.approx(100 * (1 - 1.8 / TOT_H), abs=0.01)
    assert u["kwh_queda"] == pytest.approx(6000, rel=1e-3)
    assert u["kwh_equip"] == pytest.approx(1800, rel=1e-3)
    cli = next(c for c in r["clientes"] if c["cliente"] == "TesteCo")
    assert cli["disp_queda"] > cli["disp"] and cli["disp_equip"] > cli["disp"]


def test_origem_sobreposta_nao_soma_no_total():
    # queda (usina) 09→11 e equipamento (inv 1.1) 10→12, local. O total capa em 100% da usina
    # na hora sobreposta; cada família conta a SUA hora inteira — por isso queda+equip > total.
    r = roda({"32": [task(event_date="2026-07-10T12:00:00+00:00",
                          final_date="2026-07-10T14:00:00+00:00")],
              "33": [task(tasks_log_task_type_main="Corretiva Emergencial",
                          code="TC-ALF100-INVR1.1", items_log_description="Inversor 1.1",
                          event_date="2026-07-10T13:00:00+00:00",
                          final_date="2026-07-10T15:00:00+00:00")]})
    u = so_alfa(r)
    assert u["h_queda"] == pytest.approx(2.0)
    assert u["h_equip"] == pytest.approx(0.6)            # 2 h × 0,3
    assert u["h_perdidas"] == pytest.approx(2.3)         # 2 h usina + 1 h × 0,3 do inversor
    assert u["h_queda"] + u["h_equip"] > u["h_perdidas"]


def test_os_com_os_dois_tipos_conta_como_queda():
    r = roda({"34": [task(event_date="2026-07-10T12:00:00+00:00",
                          final_date="2026-07-10T18:00:00+00:00"),
                     task(tasks_log_task_type_main="Corretiva Emergencial",
                          event_date="2026-07-10T12:00:00+00:00",
                          final_date="2026-07-10T18:00:00+00:00")]})
    assert a_os(r, 34)["origem"] == "queda"


# ── perda de cada OS em cada usina (drill-down por cliente da tela, Levi 13/10/2026) ──
def test_perda_da_os_em_cada_usina_de_site_agrupado():
    # site agrupado sem pista (Beta 1 e 2, 500 kWp cada), de 10/07 06 h a 11/07 18 h: as duas perdem os dois dias
    # (24 h × 500 = 12.000 cada). Até 15/10/2026 a geração podia desmentir o dia numa usina só, e o kwh_usina seguia isso;
    # o juiz saiu, a conta é pelas datas da OS
    r = calcular({"20": [task(code="TC-BET100", groups_1_description="TesteCo - Beta 1 e 2 - RN",
                              items_log_description="TesteCo - Beta 1 e 2 - RN  Endereço",
                              description="Religamento da Usina",
                              event_date="2026-07-10T09:00:00+00:00", final_date="2026-07-11T21:00:00+00:00")]},
                 EQUIP, PER_INI, PER_FIM, agora=AGORA)
    o = a_os(r, 20)
    assert o["kwh"] == 24000
    assert o["kwh_usina"] == {"Beta 1": 12000, "Beta 2": 12000}


def test_perda_por_usina_reparte_a_hora_sobreposta_como_o_total():
    # usina 09→11 local + cabine 1 (600) 10→12: a hora sobreposta é da OS de usina (o teto de 100%) → 2.000 e 600,
    # que somam os 2.600 da usina
    r = roda({"12": [task(event_date="2026-07-10T12:00:00+00:00",
                          final_date="2026-07-10T14:00:00+00:00")],
              "13": [task(code="TC-ALF100-CABN1", items_log_description="Cabine 1",
                          event_date="2026-07-10T13:00:00+00:00",
                          final_date="2026-07-10T15:00:00+00:00")]})
    assert a_os(r, 12)["kwh_usina"] == {"Alfa": 2000}
    assert a_os(r, 13)["kwh_usina"] == {"Alfa": 600}
    assert so_alfa(r)["kwh"] == 2600


def test_os_sem_hora_de_sol_conta_na_usina_com_zero_e_a_aberta_sem_fim_tambem_conta():
    # a noturna (20→23 h local) tem evento na usina: entra no n_os, com 0 kWh. A aberta sem data final CONTA desde
    # 15/10/2026 (até o fim do período): 141 h × 1000 kWp
    r = roda({"2": [task(event_date="2026-07-10T23:00:00+00:00", final_date="2026-07-11T02:00:00+00:00")],
              "7": [task(id_status_work_order=1, event_date="2026-07-20T12:00:00+00:00")]})
    assert a_os(r, 2)["kwh_usina"] == {"Alfa": 0}
    assert a_os(r, 7)["kwh_usina"] == {"Alfa": 141000}
    assert so_alfa(r)["n_os"] == 2


# ── hierarquia: coluna "Equipamento Parente" manda no nome ───────────────────
def test_cabine_derivada_usa_equipamento_parente():
    # usina SEM linhas UG: os inversores se chamam "2.1/2.2" mas o BD diz que são da UG 01
    # (caso real de Tucano 2). A cabine derivada tem de ser a 1, não a 2.
    equip = [
        {"cliente": "TesteCo", "usina": "Gama", "usina_fracttal": "TesteCo - Gama 1 - SP",
         "equipamento": "UFV", "pot_kwp": 400.0, "n_inv": 2},
        {"cliente": "TesteCo", "usina": "Gama", "usina_fracttal": "TesteCo - Gama 1 - SP",
         "equipamento": "Inversor 2.1", "parente": "UG 01", "pot_kwp": 200.0},
        {"cliente": "TesteCo", "usina": "Gama", "usina_fracttal": "TesteCo - Gama 1 - SP",
         "equipamento": "Inversor 2.2", "parente": "UG 01", "pot_kwp": 200.0},
    ]
    from disponibilidade import montar_catalogo
    cat, _lac = montar_catalogo(equip)
    assert sorted(cat["Gama"].ugs) == [1]
    assert cat["Gama"].ugs[1] == pytest.approx(400.0)


def test_cabine_derivada_cai_no_nome_sem_parente():
    equip = [
        {"cliente": "TesteCo", "usina": "Delta", "usina_fracttal": "TesteCo - Delta 1 - SP",
         "equipamento": "UFV", "pot_kwp": 400.0, "n_inv": 2},
        {"cliente": "TesteCo", "usina": "Delta", "usina_fracttal": "TesteCo - Delta 1 - SP",
         "equipamento": "Inversor 1.1", "pot_kwp": 200.0},
        {"cliente": "TesteCo", "usina": "Delta", "usina_fracttal": "TesteCo - Delta 1 - SP",
         "equipamento": "Inversor 2.1", "pot_kwp": 200.0},
    ]
    from disponibilidade import montar_catalogo
    cat, _lac = montar_catalogo(equip)
    assert sorted(cat["Delta"].ugs) == [1, 2]


# ── a geração não entra na disponibilidade (Levi, 15/10/2026) ───────────────────────────────────────────────────────
# "Não quero que olhe a geração, precisamos que você foque nos dados do Fracttal (...) não quero que cruze dados de
# geração pois são objetivos diferentes." Até aqui, o juiz da geração desmentia a OS em usina que gerou (Parelhas, 30/08).
# Saiu de vez: a OS conta pelas datas dela, e o que estiver estranho vai para a lista "alinhar".
def _os_longa(folio="50", ini="2026-07-05T12:00:00+00:00", fim="2026-07-20T21:00:00+00:00"):
    return {folio: [task(event_date=ini, final_date=fim)]}


def test_os_longa_conta_pelas_datas_dela_sem_olhar_geracao():
    # 05/07 09:00 local até 20/07 18:00 local: 9 h + 14 dias × 12 h + 12 h = 189 h, a usina inteira
    r = calcular(_os_longa(), EQUIP, PER_INI, PER_FIM, agora=AGORA)
    assert so_alfa(r)["h_perdidas"] == pytest.approx(189.0, abs=0.01)
    assert "dias_exonerados" not in a_os(r, 50)


def test_calculo_nao_aceita_geracao():
    with pytest.raises(TypeError):
        calcular(_os_longa(), EQUIP, PER_INI, PER_FIM, agora=AGORA, geracao={"Alfa": {}})


# ── só Full O&M entra no parque ──────────────────────────────────────────────
def test_so_full_om_entra_no_parque():
    equip = list(EQUIP) + [
        {"cliente": "TesteCo", "usina": "Terceirizada", "usina_fracttal": "TesteCo - Terc 1 - SP",
         "equipamento": "UFV", "pot_kwp": 800.0, "n_inv": 2, "full_om": "Não"},
    ]
    r = calcular({"40": [task(code="TC-TRC100", groups_1_description="TesteCo - Terc 1 - SP",
                              items_log_description="TesteCo - Terc 1 - SP",
                              event_date="2026-07-10T12:00:00+00:00",
                              final_date="2026-07-10T18:00:00+00:00")]},
                 equip, PER_INI, PER_FIM, agora=AGORA)
    assert all(u["usina"] != "Terceirizada" for u in r["usinas"])
    assert all("Terceirizada" not in (c["cliente"] or "") for c in r["clientes"])
    # e o Alfa (Full O&M = Sim) continua entrando
    assert any(u["usina"] == "Alfa" for u in r["usinas"])


# ── célula vazia do pandas (NaN) não pode virar vínculo falso ────────────────
def test_nan_do_pandas_nao_vira_usina_fractall():
    # o pandas devolve float('nan') p/ célula vazia, e NaN é TRUTHY: `str(v or "")` dava "nan".
    # 7 usinas sem 'Usina Fractall' entraram no parque assim, com 100% eterno.
    nan = float("nan")
    equip = [
        {"cliente": "TesteCo", "usina": "Orfã", "usina_fracttal": nan, "full_om": "Sim",
         "equipamento": "UFV", "pot_kwp": 900.0, "n_inv": 3},
        {"cliente": nan, "usina": "Orfã", "usina_fracttal": nan,
         "equipamento": "Inversor 1.1", "parente": nan, "pot_kwp": 300.0},
    ]
    from disponibilidade import montar_catalogo
    cat, lac = montar_catalogo(equip)
    assert cat["Orfã"].fracttal == ""          # e NÃO "nan"
    assert cat["Orfã"].cliente == "TesteCo"
    assert any("sem 'Usina Fractall'" in l for l in lac), "a lacuna tem de ser reportada"
    # e a usina não pode entrar no parque
    r = calcular({}, equip, PER_INI, PER_FIM, agora=AGORA)
    assert all(u["usina"] != "Orfã" for u in r["usinas"])


def test_linha_ufv_vazia_nao_apaga_vinculo_ja_lido():
    # 2ª linha UFV sem Fractall (caso Ribeirão Cascalheiras) não pode zerar o vínculo bom
    equip = [
        {"cliente": "TesteCo", "usina": "Dupla", "usina_fracttal": "TesteCo - Dupla 1 - SP",
         "equipamento": "UFV", "pot_kwp": 500.0},
        {"cliente": "TesteCo", "usina": "Dupla", "usina_fracttal": None,
         "equipamento": "UFV", "pot_kwp": 500.0},
    ]
    from disponibilidade import montar_catalogo
    cat, _lac = montar_catalogo(equip)
    assert cat["Dupla"].fracttal == "TesteCo - Dupla 1 - SP"


# ── regressão com dado real (OS 10758 — SMP100, agosto/26) ───────────────────
def test_regressao_os_10758_smp100():
    fx = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures",
                                     "frac_smp100_os10758.json"), encoding="utf-8"))
    r = calcular({"10758": fx["tasks"]}, fx["equip"],
                 datetime(2026, 8, 1), datetime(2026, 8, 25),
                 agora=datetime(2026, 8, 25, 23, 59))
    o = a_os(r, 10758)
    # gabarito da análise de 25/08: 41,17 h solares e ~285.275 kWh (usina de 6.930 kWp)
    assert o["h_solar"] == pytest.approx(41.17, abs=0.05)
    assert o["kwh"] == pytest.approx(285275, rel=0.005)


# ── "alinhar": o que o Fracttal mostra de estranho, só com o dado do Fracttal (Levi, 15/10/2026) ───────────────────────
# "pode até apontar possíveis erros em criação de OS porém não quero que cruze dados de geração". A lista substitui o
# cenário das abertas na tela Disponibilidade: cada OS que toca o período e precisa de um olho humano, com o motivo.
def test_alinhar_aponta_wo_final_date_grupo_sem_pista_e_concluida_sem_fim():
    wos = {
        "20": [task(event_date="2026-07-10T12:00:00+00:00", wo_final_date="2026-07-10T14:00:00+00:00")],
        "21": [task(code="TC-BET100", groups_1_description="TesteCo - Beta 1 e 2 - RN",
                    items_log_description="TesteCo - Beta 1 e 2 - RN", description="Religamento da usina",
                    event_date="2026-07-11T12:00:00+00:00", final_date="2026-07-11T13:00:00+00:00")],
        "22": [task(event_date="2026-07-12T12:00:00+00:00")],                     # concluída (status 3) sem fim
        "23": [task(id_status_work_order=4, event_date="2026-07-13T12:00:00+00:00")],   # cancelada: não é erro
    }
    r = roda(wos)
    assert "data final da WO" in alinhar(r, 20)[0]["motivo"]
    assert "grupo" in alinhar(r, 21)[0]["motivo"]
    assert "sem data final" in alinhar(r, 22)[0]["motivo"]
    assert not alinhar(r, 23)


def test_alinhar_nao_lista_a_os_bem_preenchida():
    r = roda({"1": [task(event_date="2026-07-10T12:00:00+00:00", final_date="2026-07-10T18:00:00+00:00")]})
    assert r["alinhar"] == []


# ── setembro para trás, só a Thopen, pelo BD_Thopen (Levi, 15/10/2026) ───────────────────────────────────────────────
# "A disponibilidade será calculada somente pelo Fracttal a partir de outubro; setembro para trás vamos considerar o que
# está no BD_Thopen"; fora da Thopen, "só a partir de outubro!". O BD_Thopen tem a "Disponibilidade Usina (%)" de cada
# dia por usina; o BD_Performance não tem disponibilidade.
from disponibilidade import calcular_pelo_bd   # noqa: E402


def test_mes_pelo_bd_usa_a_disponibilidade_diaria_da_planilha():
    dias = {"Alfa": {"2026-07-10": 0.75, "2026-07-11": 1.0, "2026-08-01": 0.0}}   # 01/08 fora do período
    r = calcular_pelo_bd(dias, EQUIP, PER_INI, PER_FIM)
    assert r["fonte"] == "BD_Thopen"
    (u,) = r["usinas"]                                          # Beta 1 e 2 sem dado no BD: fora
    assert u["usina"] == "Alfa"
    assert u["disp"] == pytest.approx(87.5)                     # 3 h perdidas em 2 dias com dado (24 h)
    assert u["h_perdidas"] == pytest.approx(3.0)
    assert u["kwh"] == 3000                                     # 1000 kWp × 3 h, a mesma régua nominal do Fracttal
    assert r["diario"]["Alfa"]["2026-07-10"]["disp"] == 75.0
    assert "2026-08-01" not in r["diario"]["Alfa"]
    assert r["oss"] == [] and r["alinhar"] == []
    (c,) = r["clientes"]
    assert c["cliente"] == "TesteCo" and c["disp"] == pytest.approx(87.5)


def test_mes_pelo_bd_aceita_fracao_ou_porcentagem():
    a = calcular_pelo_bd({"Alfa": {"2026-07-10": 0.75}}, EQUIP, PER_INI, PER_FIM)
    b = calcular_pelo_bd({"Alfa": {"2026-07-10": 75}}, EQUIP, PER_INI, PER_FIM)
    assert a["usinas"] == b["usinas"] and a["diario"] == b["diario"]


def test_mes_pelo_bd_pondera_o_cliente_pelo_kwp():
    dias = {"Alfa": {"2026-07-10": 0.5}, "Beta 1": {"2026-07-10": 1.0}}
    r = calcular_pelo_bd(dias, EQUIP, PER_INI, PER_FIM)
    (c,) = r["clientes"]
    assert c["disp"] == pytest.approx((1000 * 50 + 500 * 100) / 1500, abs=0.01)


# Dois sinais só do Fracttal que a prova de 15/10/2026 mostrou pesando no mês (a OS CONTINUA contando; só vai para
# "alinhar"): Religamento com descrição de "Verificação de comunicação" ou de inspeção (TIM200 15488, 06 a 13/10; Brodowski
# 12693, aberta desde 02/09) e religamento que dura dias (Canarana 1 14924, 29/09 a 13/10).
def test_alinhar_aponta_religamento_com_descricao_de_verificacao_de_comunicacao():
    r = roda({"30": [task(description="[ATHN-TIM200] - Verificação de comunicação do ATHN-TIM200",
                          event_date="2026-07-10T12:00:00+00:00", final_date="2026-07-10T14:00:00+00:00")]})
    assert a_os(r, 30)["h_solar"] == pytest.approx(2.0)                   # conta
    assert "comunicação" in alinhar(r, 30)[0]["motivo"]


def test_alinhar_aponta_religamento_que_dura_mais_de_um_dia():
    r = roda({"31": [task(event_date="2026-07-10T12:00:00+00:00", final_date="2026-07-13T12:00:00+00:00")]})
    assert a_os(r, 31)["h_solar"] > 24                                    # conta
    assert "3 dias" in alinhar(r, 31)[0]["motivo"]
    r = roda({"33": [task(event_date="2026-07-10T12:00:00+00:00", final_date="2026-07-11T22:00:00+00:00")]})
    assert "religamento de 34 h" in alinhar(r, 33)[0]["motivo"]          # abaixo de 2 dias, em horas


def test_corretiva_longa_nao_e_apontada():
    # troca de inversor leva dias de verdade: só o religamento longo é estranho
    r = roda({"32": [task(tasks_log_task_type_main="Corretiva Emergencial", code="TC-ALF100-INVR1.1",
                          description="Troca do inversor 1.1",
                          event_date="2026-07-10T12:00:00+00:00", final_date="2026-07-15T12:00:00+00:00")]})
    assert not alinhar(r, 32)


# ── revisão adversarial de 15/10/2026 ──────────────────────────────────────────────────────────────────────────────
def test_alinhar_pega_a_os_fora_da_conta_que_comecou_antes_do_periodo():
    # Santo Antônio da Platina, OS 13489 (12/09 a 06/10): o site do Fracttal não casa com o cadastro, ela fica fora da
    # conta, e outubro não a mostrava (o evento é de setembro, e setembro agora vem do BD, sem lista)
    wos = {"40": [task(code="TC-XYZ100", groups_1_description="TesteCo - Xyz - SP", items_log_description="TesteCo - Xyz",
                       event_date="2026-06-25T12:00:00+00:00", final_date="2026-07-05T12:00:00+00:00")]}
    r = roda(wos)
    assert "sem correspondência" in alinhar(r, 40)[0]["motivo"]


def test_aberta_no_mes_ja_fechado_nao_diz_ate_ontem():
    r = roda({"7": [task(id_status_work_order=1, event_date="2026-07-20T12:00:00+00:00")]})
    assert "até ontem" not in alinhar(r, 7)[0]["motivo"] and "enquanto estiver aberta" in alinhar(r, 7)[0]["motivo"]
