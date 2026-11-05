# -*- coding: utf-8 -*-
"""À noite, a usina que calou COM o sol não é "sem comunicação" (05/11/2026; o Levi disse "sim" à proposta).

Às 18:45 de 05/11 a Entrada e a Visão do cliente do Nexus diziam "Sem comunicação" em 44 das 81 usinas da Thopen, quase
todas com a última leitura entre 17h e 18h: no fim do dia o registrador da API PV atrasa e para, e a régua dos 30 min
(`COMM_ALERT_MINUTES`) dispara; às 19:05 eram 12. A régua nova: com o sol baixo, a usina que mandou dado até 2 h antes de
o sol baixar no estado dela é "Sem sol" (nada a julgar ao vivo). A que calou de dia, a sem leitura há dias e a que não
manda nada seguem "Sem comunicação" (às 19:05: uma da GreenYellow calada desde 11:05, uma da API PV sem leitura há 17
dias, as 5 da Sal Energia sem nenhuma)."""
from datetime import datetime

import app


def _pv(**extra):
    # Junco (Piauí): em novembro o sol fica abaixo de 8° por volta das 17:15 de Brasília
    r = {"usina": "Junco 2.1 (134)", "plant_id": 60560, "qtd_inversores": 4, "inv_off": 0, "strings_ativas": 0,
         "str_esp": 82, "pot_med": 0.0, "sem_visao": False, "falha_comunicacao": True,
         "ultima_leitura": "2026-11-05 17:40:00"}
    r.update(extra)
    return r


def test_calou_ao_entardecer_de_noite_e_sem_sol(freeze_now):
    freeze_now("2026-11-05 18:45:00")
    r = _pv()
    assert app._macro_status(r) == "ok"
    assert "sem sol" in app._macro_causa(r, "ok").lower()
    item = app._macro_item("API PV", r)
    assert item["status"] == "ok" and item["sev"] == 5 and "sem sol" in item["causa"].lower()


def test_o_atraso_do_fim_do_dia_tambem(freeze_now):
    """A última leitura uma hora antes de o sol baixar (o registrador atrasado) também é o fim do dia."""
    freeze_now("2026-11-05 18:45:00")
    assert app._macro_status(_pv(ultima_leitura="2026-11-05 16:20:00")) == "ok"


def test_calou_de_dia_segue_sem_comunicacao(freeze_now):
    freeze_now("2026-11-05 19:05:00")
    assert app._macro_status(_pv(ultima_leitura="2026-11-05 11:05:00")) == "sem_comm"


def test_sem_leitura_nenhuma_ou_velha_segue_sem_comunicacao(freeze_now):
    freeze_now("2026-11-05 19:05:00")
    assert app._macro_status(_pv(ultima_leitura=None, sem_dados=True, falha_comunicacao=False)) == "sem_comm"
    assert app._macro_status(_pv(ultima_leitura="2026-10-19 12:00:00")) == "sem_comm"       # 17 dias
    assert app._macro_status(_pv(ultima_leitura="2026-11-04 17:40:00")) == "sem_comm"       # o fim do dia de ONTEM


def test_de_madrugada_a_que_calou_ao_entardecer_segue_sem_sol(freeze_now):
    freeze_now("2026-11-06 05:00:00")
    assert app._macro_status(_pv()) == "ok"


def test_de_dia_a_falha_vale(freeze_now):
    freeze_now("2026-11-05 14:00:00")
    assert app._macro_status(_pv(ultima_leitura="2026-11-05 13:00:00")) == "sem_comm"


def test_leitura_em_utc_e_convertida(freeze_now):
    """RenoGrid/SolarEdge mandam o carimbo com "Z" (UTC): 20:40Z = 17:40 de Brasília."""
    freeze_now("2026-11-05 18:45:00")
    assert app._macro_status(_pv(ultima_leitura="2026-11-05T20:40:00Z")) == "ok"


def test_o_guarda_da_telemetria_parada_respeita_a_noite(freeze_now):
    """O guarda que reclassifica a leitura velha (> 2 h) como "Telemetria parada" quando a frota lê fresco: à noite
    ele também não pode pegar quem calou com o sol (às 20:15 a que parou às 17:40 já passa de 2 h)."""
    freeze_now("2026-11-05 20:15:00")
    fresca = {"usina": "Junco 2.2 (135)", "status": "ok", "sev": 5, "ultima_leitura": "2026-11-05 20:10:00",
              "strings_faltando": 0, "causa": "Sem sol"}
    calou = {"usina": "Junco 2.1 (134)", "status": "ok", "sev": 5, "ultima_leitura": "2026-11-05 17:40:00",
             "strings_faltando": 0, "causa": "Sem sol"}
    de_dia = {"usina": "Junco 2.3 (136)", "status": "ok", "sev": 5, "ultima_leitura": "2026-11-05 11:05:00",
              "strings_faltando": 0, "causa": "Sem sol"}
    app._guarda_telemetria_parada([fresca, calou, de_dia])
    assert calou["status"] == "ok" and fresca["status"] == "ok"
    assert de_dia["status"] == "sem_comm" and de_dia["causa"].startswith("Telemetria parada")


def test_o_guarda_de_dia_continua(freeze_now):
    freeze_now("2026-11-05 14:00:00")
    fresca = {"usina": "A", "status": "ok", "sev": 5, "ultima_leitura": "2026-11-05 13:55:00", "strings_faltando": 0}
    velha = {"usina": "B", "status": "ok", "sev": 5, "ultima_leitura": "2026-11-05 10:00:00", "strings_faltando": 0}
    app._guarda_telemetria_parada([fresca, velha])
    assert velha["status"] == "sem_comm"


def test_a_hora_em_que_o_sol_baixou():
    """No Piauí (Teresina) em novembro o sol passa de 8° para baixo entre 17:00 e 17:20 de Brasília."""
    baixou = app._sol_baixou_em({"usina": "Junco 2.1 (134)"}, datetime(2026, 11, 5, 19, 5))
    assert datetime(2026, 11, 5, 16, 50) <= baixou <= datetime(2026, 11, 5, 17, 30)
    # sem estado no cadastro: a janela fixa (18h)
    assert app._sol_baixou_em({"usina": "Usina Sem Cadastro"}, datetime(2026, 11, 5, 19, 5)) == \
        datetime(2026, 11, 5, 18, 0)
