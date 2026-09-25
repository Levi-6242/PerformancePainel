# -*- coding: utf-8 -*-
"""A Entrada ("Operação em tempo real") mostra SÓ os cards escolhidos (Levi, 25/09/2026: "não quero que sem cliente
apareça, quero que apareça apenas o que eu quero que apareça! Thopen, Athon, Axis, 2C e RenoGrid!").

O "Sem cliente" do print era a Sete Lagoas da 2C de novo (em 13/09 foi a do e-mail, test_entrada_sem_cliente_stl): nos
trackers parados da API PV ela se chama "Sete Lagoa", o nome não casava com o do cadastro ("Sete Lagoas"), os 2 trackers
dela ficavam sem cliente e viravam um card novo — com o link da Thopen PV, parecendo uma cópia dela. Três travas:
  1. o tracker casa com a usina do card também pelo plant_id (18771901 é a Sete Lagoas nos dois lados);
  2. nenhum card nasce fora da lista (_ENTRADA_GRUPOS): o que ainda ficar sem dono não vira "Sem cliente";
  3. SEMP e Alves Lima saíram da lista.
"""
import pytest

import app

CARDS = [("Thopen", "API PV"), ("Thopen", "Thopen"), ("Athon", "Athon"), ("Axis", "Axis"),
         ("Renogrid", "RenoGrid"), ("2C", "2C")]


@pytest.fixture
def entrada(monkeypatch):
    monkeypatch.setattr(app, "_portfolio_rollup", lambda: [])
    monkeypatch.setattr(app, "_ENTRADA_TR_VIVO", {"ts": 0.0, "epoch": None, "data": None})
    monkeypatch.setattr(app, "USINA_DISPLAY", {})
    monkeypatch.setattr(app, "INFO_GERAL", {"setelagoas": {"cliente": "2C", "estado": "MG", "regiao": "Sudeste"}})
    monkeypatch.setattr(app, "_carteira_de", lambda nome: None)
    monkeypatch.setattr(app, "_etm_prob_cache", {"ts": 0.0, "data": {"itens": [], "mes": "09/2026"}})
    monkeypatch.setattr(app, "_ENTRADA_TRK_PRAZO_S", 3)
    monkeypatch.setattr(app, "_entrada_trk_ultimo_gravar", lambda saida: None)
    linhas = [{"usina": "Sete Lagoas", "plant_id": 18771901, "status": "ok", "strings_faltando": 0, "fonte": "2C"},
              {"usina": "UFV Tucano 1", "plant_id": 18758732, "status": "ok", "strings_faltando": 0, "fonte": "SEMP"},
              {"usina": "Usina Sem Cadastro", "plant_id": 555, "status": "ok", "strings_faltando": 0, "fonte": "API PV"}]
    monkeypatch.setattr(app, "_macro_cache", {"ts": 0.0, "warming": False, "data": {"usinas": linhas}})
    for f in ("_sunop_parados_rows", "_pg_parados_rows", "_owen_parados_rows"):
        monkeypatch.setattr(app, f, lambda *a, **k: [])
    monkeypatch.setattr(app, "_pv_parados_rows", lambda errout=None: [
        {"usina": "Sete Lagoa", "plant_id": 18771901, "cliente": None, "ticket_status": "Parado"},
        {"usina": "Sete Lagoa", "plant_id": 18771901, "cliente": None, "ticket_status": "Parado"},
        {"usina": "Outra Sem Dono", "plant_id": 999, "cliente": None, "ticket_status": None}])


def test_so_os_cards_escolhidos_na_ordem(entrada):
    d = app._entrada_tempo_real_build()
    assert [(g["cliente"], g["fonte"]) for g in d["grupos"]] == CARDS


def test_ninguem_vira_sem_cliente_nem_card_fora_da_lista(entrada):
    d = app._entrada_tempo_real_build()
    assert not [g for g in d["grupos"] if g["cliente"] in ("Sem cliente", "SEMP", "Alves Lima")]


def test_os_trackers_da_sete_lagoa_contam_no_card_da_2c_pelo_plant_id(entrada):
    d = app._entrada_tempo_real_build()
    dois_c = next(g for g in d["grupos"] if g["cliente"] == "2C")
    assert dois_c["trk_parados"] == 2 and dois_c["trk_com_os"] == 2
    stl = next(u for u in dois_c["usinas"] if u["usina"] == "Sete Lagoas")
    assert stl["trk_parados"] == 2, "o card soma, mas a usina da 2C não recebia os trackers dela (nome diferente)"
