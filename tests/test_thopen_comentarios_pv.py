# -*- coding: utf-8 -*-
"""Os comentários escritos à mão para os dias de outubro/2026 sem comentário (26/11/2026, `comentarios_pv`): os 42 dias
de perda menor que 1 ponto, pela PV Operation, mais Santo Antônio da Platina em 01/10. Só entram no dia sem comentário;
o relato do COS, a frase das OS e o comentário do BD_Thopen vencem sempre."""
import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "thopen"))

import comentarios_pv  # noqa: E402
import operacao_mes  # noqa: E402

OS42 = {
    "Santana do Ipanema": [6, 11, 18, 27, 28, 29],
    "Lyon": [2, 16, 21, 22, 24, 29], "Santo Anastacio": [3, 9, 15], "Cambé": [21, 23], "Pharma IV": [13, 15],
    "Sitio dos Nogueiras": [4, 24], "Pharma II": [29], "Santo Antonio da Platina": [29], "Alvares Machado": [14],
    "Itajá": [14], "Ouro Branco III": [18], "Ouro Branco V": [26], "Ceilândia 1": [8], "Céu Azul": [1],
    "Guatambu": [5], "Junco": [23], "Nova Londrina": [27], "Primavera": [25], "Tanabi": [5], "São Bento do Una": [27],
}


def test_os_dias_da_obs_sem_ocorrencia_e_santo_antonio_da_platina_em_01_10_pelos_nomes_do_5080():
    for nome, dias in OS42.items():
        tem = comentarios_pv.por_dia(nome, 2026, 10)
        assert set(dias) <= {d.day for d in tem}, nome
    assert sum(len(v) for v in OS42.values()) == 35            # os 42 menos os 7 da Segredo, cadastrados na Ronda COS
    assert len(comentarios_pv.COMENTARIOS) == 36
    assert comentarios_pv.por_dia("Segredo", 2026, 10) == {}
    assert dt.date(2026, 10, 1) in comentarios_pv.por_dia("Santo Antonio da Platina", 2026, 10)
    assert comentarios_pv.por_dia("Santo Antonio do Platina", 2026, 10) == comentarios_pv.por_dia(
        "Santo Antônio da Platina", 2026, 10)
    assert all(linhas and all(x.strip() for x in linhas) for linhas in comentarios_pv.COMENTARIOS.values())


def test_so_outubro_e_so_a_usina():
    assert comentarios_pv.por_dia("Lyon", 2026, 11) == {}
    assert comentarios_pv.por_dia("Usina Nenhuma", 2026, 10) == {}
    a = comentarios_pv.por_dia("Itajá", 2026, 10)
    a[dt.date(2026, 10, 14)].append("mexido")                      # a cópia não muda o texto guardado
    assert comentarios_pv.por_dia("Itajá", 2026, 10)[dt.date(2026, 10, 14)] == [
        "Inversor 2.1 parado das 10:34 às 11:19 (45 min)."]


D14, D15, D16 = dt.date(2026, 10, 14), dt.date(2026, 10, 15), dt.date(2026, 10, 16)


@pytest.fixture
def _card(monkeypatch):
    monkeypatch.setattr(operacao_mes, "_da_usina", lambda *a: lambda x: False)
    monkeypatch.setattr(operacao_mes, "_e_da_usina", lambda *a: lambda x: False)
    monkeypatch.setattr(operacao_mes, "contar", lambda *a: {"por_dia": [], "strings": 0, "trackers": 0})
    monkeypatch.setattr(operacao_mes, "_mes_info", lambda *a: (None, None))
    monkeypatch.setattr(operacao_mes, "disp_por_dia", lambda *a, **k: {D14: 99.1, D15: 98.0, D16: 99.2})
    monkeypatch.setattr(operacao_mes, "os_por_dia", lambda *a, **k: {D15: ["OS 9 - linha seca"]})
    monkeypatch.setattr(comentarios_pv, "_POR_USINA", {"usina a": {D14: ["Inversor 1.1 parado das 10:00 às 10:10."],
                                                                    D15: ["texto da PV que não deve aparecer"]}})
    return {"trackers_episodios": [], "trackers_dia": [], "de_para": [], "comentario_cos_dia": [], "rondas_com_os": []}


def test_o_dia_sem_comentario_leva_o_texto_e_o_dia_com_comentario_fica_com_o_dele(_card):
    r = operacao_mes.resposta(_card, "Usina A", 2026, 10, dt.date(2026, 11, 26))
    dia = {p["dia"]: p for p in r["por_dia"]}
    assert dia["14/10"]["os"] == ["Inversor 1.1 parado das 10:00 às 10:10."]
    assert dia["15/10"]["os"] == ["OS 9 - linha seca"]
    assert dia["16/10"]["os"] == []
    assert set(r) == set(operacao_mes.CHAVES)


def test_com_o_bd_tambem_so_no_dia_sem_comentario(_card):
    bd = ({D14: 99.1, D15: 98.0}, {D15: ["Comentário da equipe no BD"]})
    r = operacao_mes.resposta(_card, "Usina A", 2026, 10, dt.date(2026, 11, 26), bd=bd)
    dia = {p["dia"]: p for p in r["por_dia"]}
    assert dia["14/10"]["os"] == ["Inversor 1.1 parado das 10:00 às 10:10."]
    assert dia["15/10"]["os"] == ["Comentário da equipe no BD"]
