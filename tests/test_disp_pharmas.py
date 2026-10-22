# -*- coding: utf-8 -*-
"""As Pharma II, III e IV na disponibilidade pelas OS do Fracttal (Levi, 22/10/2026: "Pharmas mudou o nome no fracttal,
esse mês vai pegar as OSs no nome antigo e no novo. No novo se diferencia por cabine, nos antigo é nome mesmo, consegue
diferenciar?").

POR QUE ESTE TESTE EXISTE
1. Em 22/10/2026 as três ficavam fora da conta: a aba Equipamentos do BD_Performance tem as 24 linhas delas (UFV, UG 01 e
   os inversores 1.1 a 1.6 de cada) com a Potência (kWp) VAZIA, e toda OS saía com "nenhuma usina do site 'Thopen -
   Pharmas N - PR' tem potência no BD" — a disponibilidade delas no Dashboard Thopen era "—". A reserva é o kWp do
   Registro mestre do Nexus (0,99 MWp real cada; a regra do kWp de 20/10/2026: a real, sem ela a contratual), só para a
   usina sem potência nenhuma na aba: o que estiver na aba vence.
2. O Fracttal refez as Pharmas depois de 22/09: os sites "Thopen - Pharmas 2/3/4 - PR" (PHS200/300/400) viraram UM site,
   "Thopen - Pharmas - PR" (THPN-PHS100), com a CABN2, CABN3 e CABN4 e os inversores INVR2.x, INVR3.x e INVR4.x. A cabine
   N é a Pharma N; o inversor N.M do Fracttal é o inversor 1.M da Pharma N no BD (cada Pharma tem uma UG só). O nome antigo
   segue casando pela "Usina Fractall" da aba, como sempre.
"""
from datetime import datetime

import pytest

from disponibilidade import calcular

PER_INI = datetime(2026, 10, 1)
PER_FIM = datetime(2026, 11, 1)
AGORA = datetime(2026, 11, 15, 12, 0)
TOT_H = 12.0 * 31

ROM = {2: "II", 3: "III", 4: "IV"}
EQUIP = []
for n, r in ROM.items():
    u, fr = "Pharma " + r, "Thopen - Pharmas %d - PR" % n
    EQUIP.append({"cliente": "Thopen", "usina": u, "usina_fracttal": fr, "equipamento": "UFV", "pot_kwp": None,
                  "n_inv": 6, "full_om": "Sim"})
    EQUIP.append({"cliente": "Thopen", "usina": u, "usina_fracttal": fr, "equipamento": "UG 01", "parente": "UFV",
                  "pot_kwp": None})
    for k in range(1, 7):
        EQUIP.append({"cliente": "Thopen", "usina": u, "usina_fracttal": fr, "equipamento": "Inversor 1.%d" % k,
                      "parente": "UG 01", "pot_kwp": None})
RESERVA = {"Pharma II": 990.0, "Pharma III": 990.0, "Pharma IV": 990.0}


def task(**kw):
    base = {"tasks_log_task_type_main": "Religamento", "id_status_work_order": 3,
            "event_date": "2026-10-10T12:00:00+00:00", "final_date": "2026-10-10T18:00:00+00:00",
            "date_maintenance": None, "wo_final_date": None, "creation_date": None,
            "description": "Religamento da usina"}
    base.update(kw)
    return base


def roda(wos, reserva=RESERVA):
    return calcular(wos, EQUIP, PER_INI, PER_FIM, agora=AGORA, pot_reserva=reserva)


def a_os(r, folio):
    return next(o for o in r["oss"] if o["folio"] == folio)


def disp(r, usina):
    return next(u for u in r["usinas"] if u["usina"] == usina)["disp"]


def test_sem_potencia_no_bd_a_os_fica_fora_e_com_a_reserva_entra():
    os_antiga = {"1": [task(code="THPN-PHS300", groups_1_description="Thopen - Pharmas 3 - PR",
                            items_log_description="Thopen - Pharmas 3 - PR Rodovia")]}
    sem = roda(os_antiga, reserva=None)
    assert "tem potência no BD" in (a_os(sem, 1)["excl"] or "")
    com = roda(os_antiga)
    o = a_os(com, 1)
    assert not o["excl"] and o["usinas"] == ["Pharma III"]
    assert o["kwh"] == pytest.approx(6 * 990, rel=1e-3)
    assert disp(com, "Pharma III") == pytest.approx(100 * (1 - 6.0 / TOT_H), abs=0.01)
    assert disp(com, "Pharma II") == 100.0


def test_site_novo_a_cabine_e_a_pharma():
    r = roda({"2": [task(code="THPN-PHS100-CABN4", groups_1_description="Thopen - Pharmas - PR",
                         items_log_description="Cabine 4   { THPN-PHS100-CABN4 }",
                         description="Religamento da Cabine 4")]})
    o = a_os(r, 2)
    assert not o["excl"] and o["usinas"] == ["Pharma IV"]
    assert o["escopo"] == [{"usina": "Pharma IV", "nivel": "usina", "rotulo": "Usina inteira", "kwp": 990.0}]


def test_site_novo_o_inversor_n_m_e_o_inversor_1_m_da_pharma_n():
    r = roda({"3": [task(code="THPN-PHS100-INVR2.3", groups_1_description="Thopen - Pharmas - PR",
                         items_log_description="Inversor 2.3   { THPN-PHS100-INVR2.3 }")]})
    o = a_os(r, 3)
    assert not o["excl"] and o["usinas"] == ["Pharma II"]
    assert o["escopo"] == [{"usina": "Pharma II", "nivel": "inversor", "rotulo": "Inversor 1.3", "kwp": 165.0}]


def test_site_novo_na_raiz_vale_para_as_tres():
    r = roda({"4": [task(code="THPN-PHS100", groups_1_description="Thopen - Pharmas - PR",
                         items_log_description="Thopen - Pharmas - PR Rodovia")]})
    assert sorted(a_os(r, 4)["usinas"]) == ["Pharma II", "Pharma III", "Pharma IV"]


def test_site_novo_fora_da_geracao_continua_fora():
    # a estação meteorológica e a infraestrutura do site novo não são ativo de geração: fora, como em qualquer usina
    r = roda({"5": [task(code="THPN-PHS100-ESTM1", groups_1_description="Thopen - Pharmas - PR",
                         items_log_description="Estação   { THPN-PHS100-ESTM1 }")]})
    assert "não é de geração" in (a_os(r, 5)["excl"] or "")


def test_a_potencia_da_aba_vence_a_reserva():
    equip = [dict(e, pot_kwp=1000.0) if (e["usina"] == "Pharma II" and e["equipamento"] == "UFV") else e for e in EQUIP]
    r = calcular({"6": [task(code="THPN-PHS200", groups_1_description="Thopen - Pharmas 2 - PR",
                             items_log_description="Thopen - Pharmas 2 - PR Rodovia")]},
                 equip, PER_INI, PER_FIM, agora=AGORA, pot_reserva=RESERVA)
    assert a_os(r, 6)["kwh"] == pytest.approx(6 * 1000, rel=1e-3)


def test_kwp_da_reserva_sai_do_registro_pelo_de_para():
    # a usina da aba ("Pharma II") liga ao Registro mestre pelo de-para do Nexus (usina_id 108 ↔ "Pharma II" do
    # BD_Thopen); o kWp é o do Registro (0,99 MWp real → 990). Nome que casa com duas usinas não ganha reserva
    import depara_fracttal as dpf
    reg = [{"usina_id": 108, "codigo": "THPN-PHS200", "nome": "Pharmas 2", "potencia_real": 0.99, "potencia_contratual": 1,
            "excluido": "não"},
           {"usina_id": 109, "codigo": "THPN-PHS300", "nome": "Pharmas 3", "potencia_real": None, "potencia_contratual": 1,
            "excluido": "não"},
           {"usina_id": 7, "codigo": "AAA100", "nome": "Gêmea", "potencia_real": 2.0, "excluido": "não"},
           {"usina_id": 8, "codigo": "AAA200", "nome": "Gêmea", "potencia_real": 3.0, "excluido": "não"}]
    dp = [{"usina_id": 108, "sistema": "BD_Thopen · Dados Gerais Usinas", "chave_externa": "Pharma II"},
          {"usina_id": 108, "sistema": "BD_Performance · Base UFV", "chave_externa": "THPN-PHS200"},
          {"usina_id": 109, "sistema": "BD_Thopen · Dados Gerais Usinas", "chave_externa": "Pharma III"}]
    r = dpf.kwp_por_nome(reg, dp, {"Pharma II", "Pharma III", "Gêmea", "Sem cadastro"})
    assert r == {"Pharma II": 990.0, "Pharma III": 1000.0}     # a 109 sem a real: a contratual (1 MWp)
