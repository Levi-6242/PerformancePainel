# -*- coding: utf-8 -*-
"""Strings sem as sub-abas "Strings sem corrente" e "Ocorrências (caiu → voltou)" (Levi, 25/09/2026, item 3 da lista:
"em strings remover os botões e o código relacionado a eles").

Saem os botões, as telas, os carregadores e as 4 rotas que só elas usavam (/api/<fonte>/strings/problema e
/strings/eventos, com os exports .xlsx). O MOTOR fica: a mesma leitura de "sem corrente" e de "caiu → voltou" alimenta a
aba Falhas (que está sendo montada em paralelo), a aba Perdas ("Strings · Zeradas"), o sino de notificações e as
linhas "em aberto" da cascata e do relatório — mapeado em 25/09. Tirar o motor é outra decisão.
"""
import pathlib

import app

MON = (pathlib.Path(app.__file__).resolve().parents[1] / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")


def test_a_tela_de_strings_nao_tem_mais_as_subabas():
    for peca in ("Strings sem corrente'", "Ocorrências (caiu → voltou)'", "window.setSub=", "function loadStrProblema(",
                 "function loadStrEventos(", "function renderStrProblema(", "function renderStrEventos(",
                 "_STR_SUB_FONTES", "strProb:", "strEv:", "subfilter", "/strings/problema", "/strings/eventos"):
        assert peca not in MON, f"{peca!r} ficou na tela"


def test_as_rotas_das_subabas_sairam():
    regras = {str(r) for r in app.app.url_map.iter_rules()}
    for rota in ("/api/<fonte>/strings/problema", "/api/<fonte>/strings/problema/export.xlsx",
                 "/api/<fonte>/strings/eventos", "/api/<fonte>/strings/eventos/export.xlsx"):
        assert rota not in regras, f"{rota} ainda existe"


def test_o_motor_que_alimenta_falhas_perdas_e_o_sino_fica():
    for f in ("_strings_problema_rows", "_strings_eventos_rows", "_str_ev_rows_range", "_pv_strings_eventos",
              "_sunop_strings_eventos", "_notif_ciclo", "_falhas_registra"):
        assert callable(getattr(app, f, None)), f"{f} saiu junto — ele alimenta outras abas"
    regras = {str(r) for r in app.app.url_map.iter_rules()}
    assert "/api/<fonte>/strings/curva.csv" in regras, "o CSV da curva é da aba Curva, não das sub-abas"


def test_as_subabas_de_trackers_continuam_compilando():
    """_loadSub e _evReload perderam só o ramo de strings; o de trackers segue."""
    assert "function _loadSub(){ if(state.view==='trackers')" in MON
    assert "function _evReload(){ if(state.view==='trackers'" in MON
