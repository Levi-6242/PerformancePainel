# -*- coding: utf-8 -*-
"""A parcela de cada OS em cada dia (14/10/2026, Dashboard Thopen, Levi: "A partir de outubro quero os comentários 100% OS
Fracttal. Comentários e disponibilidade!"): sai da MESMA varredura do Gerencial (`_varrer`), e somadas as parcelas dão o
h_eq do dia. A hierarquia vale: a OS de cabine coberta por uma de usina inteira só é dona fora dela."""
from collections import defaultdict
from datetime import date, datetime

import disponibilidade as D


class U:
    def __init__(self, pot):
        self.pot = pot


def ev(folio, nivel, kwp, ini, fim, usina="Alfa", origem="queda"):
    return {"usina": usina, "nivel": nivel, "chave": "", "kwp": kwp, "ini": datetime.fromisoformat(ini),
            "fim": datetime.fromisoformat(fim), "o": {"folio": folio, "origem": origem}}


def test_parcelas_somam_o_dia_e_seguem_a_hierarquia():
    usinas = {"Alfa": U(1000.0)}
    eventos = [ev(1, "usina", 1000.0, "2026-10-02T08:00:00", "2026-10-02T10:00:00"),
               ev(2, "cabine", 200.0, "2026-10-02T06:00:00", "2026-10-02T12:00:00", origem="equipamento"),
               ev(3, "usina", 1000.0, "2026-10-02T09:00:00", "2026-10-02T10:00:00")]
    det = {}
    h_eq, _, _ = D._varrer(eventos, usinas, datetime(2026, 10, 3), defaultdict(float), det)
    dia = date(2026, 10, 2)
    por = {r["folio"]: r for r in D._os_do_dia(det)[("Alfa", dia)]}
    # a cabine é dona das 06–08 e 10–12 (0,2 × 4 h = 0,8 h); as duas de usina dividem 09–10 (0,5 h cada)
    assert por[2]["trechos"] == "06:00-08:00; 10:00-12:00" and por[2]["h"] == 0.8
    assert por[1]["trechos"] == "08:00-10:00" and por[1]["h"] == 1.5
    assert por[3]["trechos"] == "09:00-10:00" and por[3]["h"] == 0.5
    assert abs(sum(r["h"] for r in por.values()) - h_eq["Alfa"][dia]) < 1e-9 and h_eq["Alfa"][dia] == 2.8
    assert [r["folio"] for r in D._os_do_dia(det)[("Alfa", dia)]] == [2, 1, 3]       # pela ordem do 1º trecho


def test_os_fora_das_06_18_nao_tem_parcela():
    det = {}
    D._varrer([ev(9, "usina", 1000.0, "2026-10-02T19:00:00", "2026-10-03T05:00:00")], {"Alfa": U(1000.0)},
              datetime(2026, 10, 4), None, det)
    assert D._os_do_dia(det) == {}
