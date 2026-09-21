# -*- coding: utf-8 -*-
"""Disponibilidade POR INVERSOR com a cascata da cabine (Levi, 14/09/2026).

Régua: se a CABINE cai, TODOS os inversores dela perdem disponibilidade; se a OS é da usina
inteira, todos os inversores caem; se é de um inversor, só ele. O mapa inversor -> cabine vem da
coluna "Equipamento Parente" da aba Equipamentos do BD_Performance. Feito para a v2 em modo
histórico (usina sem fonte ao vivo). Datas em UTC como o Fracttal manda.
"""
from datetime import datetime

import pytest

from disponibilidade import calcular

PER_INI = datetime(2026, 7, 1)
PER_FIM = datetime(2026, 8, 1)
AGORA = datetime(2026, 8, 15, 12, 0)
TOT_H = 12.0 * 31

# Alfa: UFV 1000 kWp; UG 01 = 600 (Inversor 1.1 = 300), UG 02 = 400 (Inversor 2.1 = 200).
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
]


def task(**kw):
    base = {"tasks_log_task_type_main": "Religamento", "id_status_work_order": 3,
            "event_date": None, "date_maintenance": None, "final_date": None, "wo_final_date": None,
            "code": "TC-ALF100", "items_log_description": "TesteCo - Alfa 1 - SP  Endereço",
            "groups_1_description": "TesteCo - Alfa 1 - SP", "description": "Religamento"}
    base.update(kw)
    return base


def roda(wos):
    return calcular(wos, EQUIP, PER_INI, PER_FIM, agora=AGORA)


def alfa(r):
    return next(u for u in r["usinas"] if u["usina"] == "Alfa")


def inv(r, nome):
    return next(i for i in alfa(r)["inversores"] if i["inversor"] == nome)


def _disp6():
    return pytest.approx(100 * (1 - 6.0 / TOT_H), abs=0.01)


def test_usina_tem_lista_de_inversores():
    r = roda({"1": [task(event_date="2026-07-10T12:00:00+00:00",
                         final_date="2026-07-10T18:00:00+00:00")]})
    nomes = {i["inversor"] for i in alfa(r)["inversores"]}
    assert nomes == {"Inversor 1.1", "Inversor 2.1"}


def test_os_de_cabine_derruba_so_os_inversores_da_cabine():
    # OS na CABINE 1 (UG 01) por 6 h solares -> só o Inversor 1.1 (filho da UG 01) perde; 2.1 fica 100%.
    r = roda({"7": [task(code="TC-ALF-CABN1",
                         event_date="2026-07-10T12:00:00+00:00",
                         final_date="2026-07-10T18:00:00+00:00")]})
    assert inv(r, "Inversor 1.1")["disp"] == _disp6()
    assert inv(r, "Inversor 1.1")["h_perdidas"] == pytest.approx(6.0, abs=0.01)
    assert inv(r, "Inversor 1.1")["cabine"] == 1        # o mapa inversor->cabine vem do Equipamento Parente
    assert inv(r, "Inversor 2.1")["disp"] == pytest.approx(100.0, abs=0.01)
    assert inv(r, "Inversor 2.1")["h_perdidas"] == pytest.approx(0.0, abs=0.01)
    assert inv(r, "Inversor 2.1")["cabine"] == 2


def test_os_de_usina_derruba_todos_os_inversores():
    # OS da USINA inteira -> os dois inversores caem juntos.
    r = roda({"8": [task(event_date="2026-07-10T12:00:00+00:00",
                         final_date="2026-07-10T18:00:00+00:00")]})
    assert inv(r, "Inversor 1.1")["disp"] == _disp6()
    assert inv(r, "Inversor 2.1")["disp"] == _disp6()


def test_os_de_inversor_derruba_so_ele():
    # OS do Inversor 2.1 -> só ele; 1.1 fica 100%.
    r = roda({"9": [task(code="TC-ALF-INVR2.1",
                         event_date="2026-07-10T12:00:00+00:00",
                         final_date="2026-07-10T18:00:00+00:00")]})
    assert inv(r, "Inversor 2.1")["disp"] == _disp6()
    assert inv(r, "Inversor 1.1")["disp"] == pytest.approx(100.0, abs=0.01)


def test_overlap_de_os_nao_passa_de_100():
    # Duas OS no mesmo inversor no mesmo horário não somam além do período coberto (união, não soma).
    r = roda({"10": [task(code="TC-ALF-INVR1.1",
                          event_date="2026-07-10T12:00:00+00:00",
                          final_date="2026-07-10T18:00:00+00:00")],
              "11": [task(code="TC-ALF-INVR1.1",
                          event_date="2026-07-10T13:00:00+00:00",
                          final_date="2026-07-10T17:00:00+00:00")]})
    # 6 h (12-18Z = 09-15 local) cobrindo a de dentro -> continua 6 h, não 10.
    assert inv(r, "Inversor 1.1")["h_perdidas"] == pytest.approx(6.0, abs=0.01)
