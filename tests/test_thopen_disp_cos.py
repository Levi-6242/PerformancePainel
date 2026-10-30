# -*- coding: utf-8 -*-
"""O Dashboard Thopen com a disponibilidade pelas normalizações do COS (Levi, 29/10/2026: "Nos comentários tem que vir as
proteções atuadas"; e, de 27/10, "o usuário thopen que é o do cliente só vê se eu liberar"). O comentário da OS do COS
leva as proteções e diz a falha de comunicação com a geração parada; a OS do COS não vai buscar o trip no Fracttal; o
cliente vê a conta de antes (as abas `_fracttal`) e o papel grid a nova. Dados fictícios."""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "thopen"))
import dashboard_thopen as dth  # noqa: E402
import fonte_operacao  # noqa: E402
import operacao_mes as om  # noqa: E402

DIA = date(2026, 10, 10)


def _os(**kw):
    o = {"mes": "2026-10", "dia": "2026-10-10", "usina": "Alfa", "os": "17001", "tipo": "desligamento de usina",
         "escopo": "Usina inteira", "kwp": 1000, "inicio": "2026-10-10T09:00:00", "fim": "2026-10-10T15:00:00",
         "aberta": "não", "trechos": "09:00-15:00", "h_perdidas": 6.0, "fonte": "cos", "protecoes": "27ABC; 86"}
    o.update(kw)
    return o


def test_comentario_do_cos_com_as_protecoes():
    assert om._frase_os(_os(), DIA, 1000) == "Desligamento Usina Trip 27ABC/86 de 10/10 às 09:00h a 10/10 às 15:00h; OS 17001"


def test_comentario_da_comunicacao_com_a_geracao_parada_e_sem_os():
    f = om._frase_os(_os(tipo="falha de comunicação com a geração parada", protecoes=None, os=None), DIA, 1000)
    assert f == "Falha de comunicação com a geração parada, Usina de 10/10 às 09:00h a 10/10 às 15:00h; sem OS"


def test_cabine_do_cos_e_a_os_do_fracttal_como_era():
    f = om._frase_os(_os(escopo="Cabine 2", tipo="desligamento de cabine", protecoes="59C"), DIA, 1000)
    assert f.startswith("Desligamento Cabine 2 Trip 59C de 10/10")
    fr = om._frase_os(_os(fonte="fracttal", tipo="Religamento", protecoes=None), DIA, 1000, trip="27/86")
    assert fr == "Desligamento Usina Trip 27/86 de 10/10 às 09:00h a 10/10 às 15:00h; religamento, OS 17001"


def _dados():
    atu = {"mes": "2026-10", "disponibilidade_dia": 2, "disponibilidade_os_dia": 2, "disponibilidade_dia_fracttal": 1,
           "disponibilidade_os_dia_fracttal": 1}
    return {"atualizacao": [atu], "de_para": [],
            "disponibilidade_dia": [{"mes": "2026-10", "dia": "2026-10-10", "usina": "Alfa", "pot_kwp": 1000,
                                     "disp": 50.0, "h_perdidas": 6.0},
                                    {"mes": "2026-10", "dia": "2026-10-10", "usina": "Gama", "pot_kwp": 500,
                                     "disp": 75.0, "h_perdidas": 3.0}],
            "disponibilidade_os_dia": [_os(), _os(usina="Gama", os="600", fonte="fracttal", protecoes=None)],
            "disponibilidade_dia_fracttal": [{"mes": "2026-10", "dia": "2026-10-10", "usina": "Alfa", "pot_kwp": 1000,
                                              "disp": 100.0, "h_perdidas": 0.0}],
            "disponibilidade_os_dia_fracttal": [_os(os="500", fonte="fracttal", protecoes=None, trechos="10:00-11:00")]}


def test_a_de_antes_so_troca_a_usina_da_thopen_no_mes():
    d = om.disp_de_antes(_dados())
    assert [(r["usina"], r["h_perdidas"]) for r in d["disponibilidade_dia"]] == [("Gama", 3.0), ("Alfa", 0.0)]
    assert sorted(r["os"] for r in d["disponibilidade_os_dia"]) == ["500", "600"]
    assert om.conferir(_dados())
    sem = {k: v for k, v in _dados().items() if not k.endswith("_fracttal")}
    assert om.disp_de_antes(sem) is sem


def test_a_os_do_cos_nao_vai_buscar_o_trip_no_fracttal():
    assert om.os_desligamento_do_mes(_dados(), "Alfa", 2026, 10) == []
    assert om.os_desligamento_do_mes(om.disp_de_antes(_dados()), "Alfa", 2026, 10) == ["500"]


def test_o_cliente_ve_a_de_antes_e_a_grid_a_nova(monkeypatch):
    d = _dados()
    monkeypatch.setattr(fonte_operacao, "dados", lambda *a, **k: d)
    assert dth.LIBERADO_AO_CLIENTE["disponibilidade_cos"] is True            # liberada em 30/10/2026
    monkeypatch.setitem(dth.LIBERADO_AO_CLIENTE, "disponibilidade_cos", False)
    monkeypatch.setattr(dth, "_e_grid", lambda: False)
    alfa = lambda x: [r["h_perdidas"] for r in x["disponibilidade_dia"] if r["usina"] == "Alfa"]   # noqa: E731
    assert alfa(dth._op_dados()) == [0.0]
    monkeypatch.setattr(dth, "_e_grid", lambda: True)
    assert alfa(dth._op_dados()) == [6.0]
    monkeypatch.setattr(dth, "_e_grid", lambda: False)
    monkeypatch.setitem(dth.LIBERADO_AO_CLIENTE, "disponibilidade_cos", True)
    assert alfa(dth._op_dados()) == [6.0]
