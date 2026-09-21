# -*- coding: utf-8 -*-
"""Quatro ajustes do painel/gerencial (Levi, 14/09/2026), verificados ao vivo em 14/09:
1) parede só mostra usina com ABA (sem_dado fica de fora);
2) linha-lixo do BD_Performance (inversor com valor fisicamente impossível e não validado) não soma
   no prod — Ibirapuã II caiu de 10.246 p/ ~95 MWh, mas Marialva/Ponto Belo (geram, mês não validado)
   CONTINUAM aparecendo;
3) "Vargem Grande IB" (Info Geral) = aba "Vargem Grande 1" do BD_Thopen (de-para);
4) meta do BD_Thopen no formato LONGO (Historico Tipo/Valor) complementa quem falta no LARGO
   (Santo Anastácio, Álvares Machado)."""
import pathlib

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
APP = (RAIZ / "plataforma" / "app.py").read_text(encoding="utf-8")
PORT = (RAIZ / "plataforma" / "templates" / "painel_portfolio.html").read_text(encoding="utf-8")


def test_1_parede_so_usina_com_aba():
    # a parede só recebe a usina só-gerencial se ela tiver aba (não for sem_dado)
    assert "if(u.sem_dado) return;" in PORT


def test_2_linha_lixo_fora_do_prod():
    # teto físico por inversor/dia + o gate só rejeita LIXO (não validado E impossível)
    assert "_INV_DIA_MAX_KWH = 100000.0" in APP
    assert "_lixo = (not validado) and any(v > _INV_DIA_MAX_KWH for v in _vals)" in APP
    assert "rowgen = 0.0 if _lixo else sum(_vals)" in APP


def test_3_vargem_grande_ib_de_para():
    assert '_nrm("Vargem Grande IB"): "Vargem Grande 1"' in APP


def test_4_meta_thopen_formato_longo():
    # o load_thopen_meta complementa o THOPEN_META com a aba LONGO "Historico" (Tipo/Valor)
    assert "suplemento LONGO" in APP.lower() or "SUPLEMENTO do formato LONGO" in APP
    assert 'str(_ws.title).strip().lower() != "historico"' in APP
    assert '_slot["meta_mwh"]' in APP


def test_2_gate_da_validacao_no_pr_mantido():
    # o PR do BI continua só em dia COMPLETO e VALIDADO
    assert "if d.date() < hoje_d and validado:" in APP
