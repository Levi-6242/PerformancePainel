# -*- coding: utf-8 -*-
"""Painel > Diagnóstico v2, lote de 11/09/2026 (manhã), palavras do Levi:
  1. "Tira esse AO VIVO"  2. "Tire a temperatura da tabela"
  3. "O gráfico abaixo do dia em drill-down são dois; eu só quero UM, no estilo do card Curvas, escolhendo curva
     (strings), inversor ou correlação"
  4. "Quero que tracker também faça drill-down e carregue a curva do tracker"."""
import pytest

import app


@pytest.fixture
def html(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    return app.app.test_client().get("/painel/usina/18748888?fonte=pv&nome=Colorado%202").get_data(as_text=True)


def test_sem_pill_ao_vivo(html):
    assert "v2Pill" not in html and "AO VIVO" not in html
    assert 'id="v2Dia"' in html and 'id="v2Hoje"' in html           # o seletor de dia e o "hoje" continuam


def test_sem_temperatura_na_coluna_agora(html):
    assert "nf(i.temp)+'°C'" not in html and "i.temp!=null" not in html
    assert "nf(i.active_power)} kW" in html or "nf(i.active_power)+' kW'" in html   # a potência fica


def test_drill_down_do_dia_e_um_grafico_so_com_seletor(html):
    assert "v2HdVista(" in html and "hdVista:'str'" in html
    assert html.count("-ch\"") >= 1 and '${id}-corr' not in html and '${id}-str' not in html   # um canvas, não dois
    assert "[['str','Strings'],['inv','Inversor'],['corr','Correlação']]" in html   # os três rótulos do seletor
    assert "function _hdDesenha" in html and "abrir na aba Curvas" in html


def test_tracker_tem_drill_down_com_a_curva(html):
    assert "v2TrkToggle(" in html and "function v2TrkDrawDia" in html and "trkAberto:null" in html
    assert "function _trkDesenha" in html
    assert "overlayCorrelacao(t, ch=null, els=null)" in html            # a correlação tracker × inversor serve aos dois lugares
