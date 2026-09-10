# -*- coding: utf-8 -*-
"""Inversor MORTO tem de aparecer com PR 0 — sumir da lista é o pior resultado possível (varredura 09/09/2026).

`_g_th_inversores` (PR por inversor das usinas Thopen, aba do BD_Thopen) descartava com
`if not (ger > 0 and poa > 0): continue` — o mesmo `continue` para dois casos que NÃO são a mesma
coisa: "não tenho visão deste inversor" (sem leitura nenhuma) e "este inversor gerou zero com sol no
período". O segundo é justamente o que o analista abre a tela para achar, e ele saía calado.

Além de esconder, discordava da própria casa: no caminho do BD_Performance (mesma rota, cliente que
não é Thopen) o inversor zerado aparece com PR 0. Régua da casa (BD_Performance): zero é VERMELHO,
nulo é amarelo — nunca invisível.
"""
import pandas as pd

import app


def _folha():
    return pd.DataFrame({
        "Data":        pd.to_datetime(["2026-09-01", "2026-09-02", "2026-09-03"]),
        "IPOA":        [5.0, 5.0, 0.0],          # o dia sem irradiância não entra no denominador
        "Inversor 1":  [500.0, 500.0, 0.0],
        "Inversor 2":  [0.0, 0.0, 0.0],          # morto o período inteiro, com sol
        "Inversor 3":  [None, None, None],       # sem leitura nenhuma: sem visão
        "Inversor 4":  [400.0, 400.0, 0.0],      # sem potência cadastrada
    })


def _prep(monkeypatch):
    monkeypatch.setattr(app, "_g_th_folha", lambda u: _folha())
    monkeypatch.setattr(app, "POWER_INV_DISP", {app._nrm("Usina Teste"): {
        app._nrm("Inversor 1"): 1000.0, app._nrm("Inversor 2"): 1000.0, app._nrm("Inversor 3"): 1000.0}})


def test_inversor_zerado_aparece_com_pr_zero(monkeypatch):
    _prep(monkeypatch)
    rows, _ = app._g_th_inversores("Usina Teste")
    por = {r["inversor"]: r for r in rows}
    assert "Inversor 2" in por, "o inversor morto sumiu da lista de PR por inversor"
    assert por["Inversor 2"]["pr"] == 0.0
    assert por["Inversor 2"]["dias"] == 2, "conta os dias COM sol em que ele reportou (o dia sem IPOA sai antes)"


def test_inversor_sem_leitura_continua_fora(monkeypatch):
    """'Sem visão' não é 'PR zero' — inventar 0 aqui encheria a tela de vermelho falso."""
    _prep(monkeypatch)
    rows, _ = app._g_th_inversores("Usina Teste")
    assert "Inversor 3" not in {r["inversor"] for r in rows}


def test_inversor_sem_potencia_cadastrada_continua_fora(monkeypatch):
    """Sem kWp não há denominador — PR seria chute."""
    _prep(monkeypatch)
    rows, _ = app._g_th_inversores("Usina Teste")
    assert "Inversor 4" not in {r["inversor"] for r in rows}


def test_o_pr_de_quem_gera_nao_muda(monkeypatch):
    """Régua intacta: Σgeração ÷ (ΣIPOA dos dias lidos × MWp). 1000 kWh ÷ (10 × 1 MWp) = 0,10."""
    _prep(monkeypatch)
    rows, d0 = app._g_th_inversores("Usina Teste")
    por = {r["inversor"]: r for r in rows}
    assert round(por["Inversor 1"]["pr"], 6) == 0.1
    assert d0 == pd.Timestamp("2026-09-01"), "a 1ª data volta para achar a meta do mês"
