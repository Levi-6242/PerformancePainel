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
     "equipamento": "UFV", "pot_kwp": 1000.0, "n_inv": 2},
    {"cliente": "TesteCo", "usina": "Alfa", "usina_fracttal": "TesteCo - Alfa 1 - SP",
     "equipamento": "UG 01", "pot_kwp": 600.0},
    {"cliente": "TesteCo", "usina": "Alfa", "usina_fracttal": "TesteCo - Alfa 1 - SP",
     "equipamento": "UG 02", "pot_kwp": 400.0},
    {"cliente": "TesteCo", "usina": "Alfa", "usina_fracttal": "TesteCo - Alfa 1 - SP",
     "equipamento": "Inversor 1.1", "parente": "UG 01", "pot_kwp": 300.0},
    {"cliente": "TesteCo", "usina": "Alfa", "usina_fracttal": "TesteCo - Alfa 1 - SP",
     "equipamento": "Inversor 2.1", "parente": "UG 02", "pot_kwp": 200.0},
    {"cliente": "TesteCo", "usina": "Beta 1", "usina_fracttal": "TesteCo - Beta 1 e 2 - RN",
     "equipamento": "UFV", "pot_kwp": 500.0, "n_inv": 4},
    {"cliente": "TesteCo", "usina": "Beta 2", "usina_fracttal": "TesteCo - Beta 1 e 2 - RN",
     "equipamento": "UFV", "pot_kwp": 500.0, "n_inv": 4},
]


def task(**kw):
    """task do Fracttal com defaults de religamento concluído na usina Alfa."""
    base = {"tasks_log_task_type_main": "Religamento", "id_status_work_order": 3,
            "event_date": None, "date_maintenance": None,
            "final_date": None, "wo_final_date": None,
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
def test_relampago_final_antes_do_evento_dura_zero():
    # final_date carimbado 40 s ANTES do event_date → duração 0, não exclusão
    r = roda({"4": [task(event_date="2026-07-10T12:00:40+00:00",
                         final_date="2026-07-10T12:00:00+00:00")]})
    o = a_os(r, 4)
    assert o["excl"] is None
    assert o["h_solar"] == 0.0


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


def test_aberta_sem_fim_zero_no_calculo_e_cenario():
    r = roda({"7": [task(id_status_work_order=1,
                         event_date="2026-07-20T12:00:00+00:00")]})
    o = a_os(r, 7)
    assert o["excl"] is None
    assert o["h_solar"] == 0.0
    assert so_alfa(r)["disp"] == 100.0
    cen = r["cenario_abertas"]
    assert len(cen) == 1 and cen[0]["folio"] == 7
    # cenário: 20/07 09:00 local até 31/07 → 9 h do dia 20 + 11 dias × 12 h = 141 h
    assert cen[0]["h_cenario"] == pytest.approx(141.0, abs=0.1)
    assert cen[0]["kwh_cenario"] == pytest.approx(141000, rel=1e-3)


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


# ── célula vazia do pandas (NaN) não pode virar vínculo falso ────────────────
def test_nan_do_pandas_nao_vira_usina_fractall():
    # o pandas devolve float('nan') p/ célula vazia, e NaN é TRUTHY: `str(v or "")` dava "nan".
    # 7 usinas sem 'Usina Fractall' entraram no parque assim, com 100% eterno.
    nan = float("nan")
    equip = [
        {"cliente": "TesteCo", "usina": "Orfã", "usina_fracttal": nan,
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
