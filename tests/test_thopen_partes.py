# -*- coding: utf-8 -*-
"""As usinas do 5080 que são PARTES de uma usina do Gerencial (Levi, 04/11/2026: "Sim, liga"). A Ouro Branco é uma usina
na régua (o site do Fracttal, com as UG 01 a 05) e cinco no 5080: cada parte pega do site a parada da usina inteira e o
que leva o número dela (cabine, UG, SKID, QGBT n; o inversor n.x pela potência dele sobre a da parte). Caso: em 11, 13 e
27/10/2026 a QGBT 4, o SKID 4 e a cabine 4 pararam, só a Ouro Branco IV perdeu geração, e ela não tinha ocorrência nem
comentário. Dados fictícios."""
import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "thopen"))
import operacao_mes as om  # noqa: E402

D11, D12 = dt.date(2026, 10, 11), dt.date(2026, 10, 12)


def _os(dia="2026-10-11", **kw):
    o = {"mes": "2026-10", "dia": dia, "usina": "Ouro Branco", "usina_fracttal": "Thopen - Ouro Branco 1 - AL",
         "os": "16066", "tipo": "desligamento de QGBT", "escopo": "Cabine 4", "kwp": 1016.6,
         "inicio": f"{dia}T06:00:00", "fim": f"{dia}T10:25:00", "aberta": "não", "trechos": "07:30-10:25",
         "h_perdidas": 1.01, "fonte": "cos", "protecoes": None}
    o.update(kw)
    return o


H = om.HORAS_SOL         # o período solar da Thopen, 07:30–17:30 (05/11/2026): os trechos publicados ficam dentro dele


def _dados(*oss):
    return {"atualizacao": [{"mes": "2026-10", "disponibilidade_dia": 2, "disponibilidade_os_dia": len(oss)}],
            "de_para": [],
            "disponibilidade_dia": [{"mes": "2026-10", "dia": d, "usina": "Ouro Branco", "pot_kwp": 4450.6,
                                     "disp": 90.0, "h_perdidas": 1.2} for d in ("2026-10-11", "2026-10-12")],
            "disponibilidade_os_dia": list(oss),
            # o resto da leitura do 5080, vazio (a resposta inteira passa por estas abas)
            "trackers_episodios": [], "trackers_dia": [], "strings_episodios": [], "strings_os": [], "cobertura": [],
            "rondas_com_os": []}


def test_as_cinco_ouro_branco_sao_as_ug_da_ouro_branco_do_gerencial():
    assert om.parte("Ouro Branco IV") == ({"ouro branco"}, 4) and om.parte("ouro branco i") == ({"ouro branco"}, 1)
    assert om.parte("Ouro Branco") is None and om.parte("Altair") is None


def test_a_cabine_4_e_so_da_ouro_branco_iv():
    d = _dados(_os())
    iv = om.disp_por_dia(d, "Ouro Branco IV", 2026, 10, 600)
    assert iv[D11] == pytest.approx(100 * (1 - (2 + 55 / 60) / H)) and iv[D12] == 100.0      # 07:30 a 10:25 de 10 h
    assert om.disp_por_dia(d, "Ouro Branco I", 2026, 10, 1307) == {D11: 100.0, D12: 100.0}
    assert om.os_por_dia(d, "Ouro Branco IV", 2026, 10, pot_kwp=600)[D11][0].startswith(
        "Desligamento Cabine 4 de 11/10 às 06:00h a 11/10 às 10:25h")
    assert om.os_por_dia(d, "Ouro Branco I", 2026, 10, pot_kwp=1307) == {}


def test_a_usina_inteira_vale_para_as_cinco_e_nao_conta_duas_vezes():
    d = _dados(_os(), _os(os="17001", tipo="desligamento de usina", escopo="Usina inteira", trechos="10:00-12:00"))
    assert om.disp_por_dia(d, "Ouro Branco I", 2026, 10, 1307)[D11] == pytest.approx(100 * (1 - 2 / H))
    # na IV a cabine (07:30-10:25) e a usina (10:00-12:00) se cruzam: 07:30 a 12:00, 4,5 h
    assert om.disp_por_dia(d, "Ouro Branco IV", 2026, 10, 600)[D11] == pytest.approx(100 * (1 - 4.5 / H))


def test_o_inversor_da_parte_pesa_sobre_a_potencia_dela():
    inv = _os(os="17537", tipo="desligamento de inversor", escopo="Inversor 3.2", kwp=102.5, trechos="07:30-17:30")
    d = _dados(inv)
    assert om.disp_por_dia(d, "Ouro Branco III", 2026, 10, 410)[D11] == pytest.approx(75.0)
    assert om.disp_por_dia(d, "Ouro Branco IV", 2026, 10, 600)[D11] == 100.0
    assert om.disp_por_dia(d, "Ouro Branco III", 2026, 10, None)[D11] == 100.0      # sem a potência, não chuta
    # o inversor fora das horas em que a parte já estava inteira parada
    d = _dados(inv, _os(escopo="Cabine 3", trechos="07:30-12:00"))
    assert om.disp_por_dia(d, "Ouro Branco III", 2026, 10, 410)[D11] == pytest.approx(100 * (1 - (4.5 + 5.5 * 0.25) / H))


def test_a_os_de_duas_cabines_e_das_duas_partes_e_a_sem_identificacao_de_nenhuma():
    d = _dados(_os(escopo="Cabine 3; Cabine 4", trechos="16:20-17:30"), _os(escopo="Inversor ?", kwp=200))
    for parte in ("Ouro Branco III", "Ouro Branco IV"):
        assert om.disp_por_dia(d, parte, 2026, 10, 600)[D11] == pytest.approx(100 * (1 - (70 / 60) / H))
    assert om.disp_por_dia(d, "Ouro Branco V", 2026, 10, 410)[D11] == 100.0


def test_a_resposta_da_parte_leva_a_disponibilidade_e_o_comentario():
    r = om.resposta(_dados(_os()), "Ouro Branco IV", 2026, 10, dt.date(2026, 10, 13), pot_kwp=600)
    dia = next(p for p in r["por_dia"] if p["dia"] == "11/10")
    assert dia["disp"] == round(100 * (1 - (2 + 55 / 60) / H), 1) and dia["os"][0].endswith("OS 16066")
