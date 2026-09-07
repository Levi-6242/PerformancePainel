# -*- coding: utf-8 -*-
"""Cobertura de tickets por tracker (06/09/2026, "quero ver de forma visual o que não está sendo coberto"):
  1. só ocorrência ABERTA (sem "Fim da ocorrência") conta como ticket — fechada não cobre nada;
  2. "1.2" na planilha é skid 1 / tracker 2 (antes int(float("1.2")) virava tracker 1) e o skid do id manda sobre a coluna;
  3. "X 1 e 2" ganha as chaves "X 1" e "X 2", cada uma com os tickets do seu skid;
  4. ticket de usina inteira (RSU, NCU, "Todos") cobre todos os parados dela;
  5. _trk_cruza_tickets entrega parados_com/parados_sem/normalizados e marca cada tracker.
"""
import io

import openpyxl
import pytest

import app

COLS = ["", "Usina", "Cliente", "Equipamento", "Status", "Nº do SKID", "Quantidade de trackers parados",
        "Nº do tracker / Identificação", "Início da ocorrência", "Fim da ocorrência"]
LINHAS = [
    ("Barretos", "Thopen", "Tracker", "Parado", 1, 1, 57, "2026-07-29", None),          # aberto
    ("Barretos", "Thopen", "Tracker", "Parado", 1, 1, 58, "2026-07-01", "2026-08-01"),  # FECHADO: não cobre
    ("Boa Esperança do Sul 1 e 2", "Thopen", "Tracker", "Parado", 1, 1, "1.2", "2026-04-29", None),
    ("Boa Esperança do Sul 1 e 2", "Thopen", "NCU", "Parado", 2, 30, "Todos", "2026-08-10", None),   # usina inteira, skid 2
    ("Araputanga", "2C", "Tracker", "Parado", 1, 1, "2.10", "2026-08-20", None),        # id diz skid 2
    ("Santa Bárbara I", "Thopen", "RSU", "Parado", 1, 52, "-", "2026-06-23", None),     # usina inteira
    ("CPP100", "Athon", "Tracker", "Com problemas", None, 1, 12, "2026-09-01", None),
    ("CPP100", "Athon", "Tracker", "Em conformidade", None, 1, 13, "2026-09-01", None),  # ignorado
]


def _planilha() -> io.BytesIO:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Trackers"
    for _ in range(3):
        ws.append(["rascunho"])            # a planilha real tem cabeçalho na linha 4 (header=3)
    ws.append(COLS)
    for l in LINHAS:
        ws.append([""] + list(l))
    b = io.BytesIO()
    wb.save(b)
    b.seek(0)
    return b


@pytest.fixture
def tickets(monkeypatch):
    monkeypatch.setattr(app, "_bd_readable", lambda chave=None, fallback=None: _planilha())
    monkeypatch.setattr(app, "_tickets_marca", lambda: 1.0)
    app.load_tickets_trackers()
    return app.TICKETS_TRK


def test_planilha_so_aberto_skid_no_id_e_apelidos(tickets):
    assert tickets["barretos"]["1"]["nums"] == {57: "Parado"}                      # 58 fechado ficou de fora
    assert tickets["barretos"]["1"]["desde"] == {57: "29/07/2026"}
    assert tickets["boa esperança do sul 1 e 2"]["1"]["nums"] == {2: "Parado"}     # "1.2" = skid 1, tracker 2
    assert tickets["boa esperança do sul 1"][""]["nums"] == {2: "Parado"}          # apelido da sub-usina 1
    assert "boa esperança do sul 2" not in tickets                                 # a 2 só tem o ticket de usina
    assert tickets["araputanga"]["2"]["nums"] == {10: "Parado"} and "1" not in tickets["araputanga"]
    assert tickets["cpp100"][""]["nums"] == {12: "Com problemas"}                   # "Em conformidade" ignorado
    assert app.TICKETS_USINA["santa bárbara i"]["1"]["equip"] == "RSU"
    assert app.TICKETS_USINA["boa esperança do sul 2"][""]["equip"] == "NCU"       # apelido também para o de usina
    assert app.TICKETS_PARADO_ABERTO["barretos"] == {57}                            # a ronda segue igual


def test_cruzamento_marca_cada_tracker_e_conta_parados(tickets):
    lst = [{"id": "TRK57", "status": "parado"}, {"id": "TRK58", "status": "parado"}, {"id": "TRK1", "status": "normal"}]
    r = app._trk_cruza_tickets("Barretos 1 (83)", lst)            # API PV: skid pelo nome
    assert (r["parados_com"], r["parados_sem"], r["normalizados"], r["tem_ticket"]) == (1, 1, 0, True)
    assert lst[0]["na_planilha"] and lst[0]["ticket_desde"] == "29/07/2026" and not lst[1]["na_planilha"]

    lst = [{"id": "Tracker 02", "status": "normal"}, {"id": "Tracker 03", "status": "parado"}]
    r = app._trk_cruza_tickets("(289) Boa Esperança do Sul 1", lst)   # banco: sub-usina pelo apelido
    assert (r["normalizados"], r["parados_sem"], r["parados_com"]) == (1, 1, 0)
    assert lst[0]["normalizado"] is True and r["ticket_usina"] is None   # o NCU é do skid 2, não deste

    lst = [{"id": "Tracker 2.10", "status": "parado"}, {"id": "Tracker 1.6", "status": "parado"}]
    r = app._trk_cruza_tickets("Araputanga", lst)                    # 2C: skid no nome do tracker
    assert (r["parados_com"], r["parados_sem"]) == (1, 1) and lst[0]["na_planilha"] and not lst[1]["na_planilha"]

    lst = [{"id": "Tracker 01", "status": "parado"}, {"id": "Tracker 02", "status": "normal"}]
    r = app._trk_cruza_tickets("(311) Santa Bárbara I", lst)         # RSU da usina inteira cobre os parados
    assert (r["parados_com"], r["parados_sem"]) == (1, 0) and lst[0]["ticket_usina"] and not lst[0]["na_planilha"]
    assert r["ticket_usina"]["equip"] == "RSU" and r["tem_ticket"] is True

    lst = [{"id": "Tracker 12", "status": "parado"}, {"id": "Tracker 13", "status": "parado"}]
    r = app._trk_cruza_tickets("CPP100", lst)
    assert (r["parados_com"], r["parados_sem"]) == (1, 1) and lst[0]["ticket_status"] == "Com problemas"

    r = app._trk_cruza_tickets("Usina Inexistente", [{"id": "TRK1", "status": "parado"}])
    assert r["tem_ticket"] is False and r["parados_sem"] == 1
