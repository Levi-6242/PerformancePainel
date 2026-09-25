# -*- coding: utf-8 -*-
"""Card "Sem cliente" no /tempo-real (Levi, 13/09/2026: "é só uma cópia da antiga visão da 2C, não faz sentido aparecer").

Era a Sete Lagoas do e-mail da 2C. O fallback `OWEN_UFVS` chamava a STL de "Sete Lagoas 2" (nome do Fracttal); o cadastro
(Info Geral) e a API PV dizem "Sete Lagoas". Sem casar o nome, a linha do e-mail não recebia cliente no `_trk_geo_annotate`
e virava um 9º grupo — com 1 usina, os 2 trackers parados dela e link para a antiga visão /tempo-real/2c.
"""
import app


def test_nome_do_email_da_stl_e_o_do_cadastro(monkeypatch):
    monkeypatch.setattr(app, "USINA_DISPLAY", {})          # Equipamentos sem a linha STL: vale o fallback fixo
    assert app._owen_nome("STL") == "Sete Lagoas"
    assert app._owen_nome("ARA") == "Araputanga" and app._owen_nome("TUP") == "Tupi Paulista"


def test_sete_lagoas_do_email_entra_no_card_da_2c_e_nao_cria_sem_cliente(monkeypatch):
    monkeypatch.setattr(app, "USINA_DISPLAY", {})
    monkeypatch.setattr(app, "INFO_GERAL", {"setelagoas": {"cliente": "2C", "estado": "MG", "regiao": "Sudeste"}})
    monkeypatch.setattr(app, "_carteira_de", lambda nome: None)
    linha_email = {"usina": app._owen_nome("STL"), "plant_id": "STL", "status": "ok", "strings_faltando": 0,
                   "fonte": "2C", "sub_fonte": "email", "ultima_leitura": "2026-09-13 08:59"}
    monkeypatch.setattr(app, "_macro_cache", {"ts": 0.0, "warming": False, "data": {"usinas": [linha_email]}})
    monkeypatch.setattr(app, "_etm_prob_cache", {"ts": 0.0, "data": {"itens": [], "mes": "09/2026"}})
    monkeypatch.setattr(app, "_ENTRADA_TRK_PRAZO_S", 3)
    for f in ("_sunop_parados_rows", "_pv_parados_rows", "_pg_parados_rows"):
        monkeypatch.setattr(app, f, lambda *a, **k: [])
    monkeypatch.setattr(app, "_owen_parados_rows", lambda *a, **k: [{"usina": app._owen_nome("STL")}, {"usina": app._owen_nome("STL")}])
    d = app._entrada_tempo_real_build()
    assert not [g for g in d["grupos"] if g["cliente"] == "Sem cliente"], "a Sete Lagoas do e-mail virou um card 'Sem cliente'"
    assert len(d["grupos"]) == 7                                             # só os 7 cards da lista (25/09/2026)
    por = {g["fonte"]: g for g in d["grupos"]}
    assert por["2C"]["trk_parados"] == 2                                     # os trackers dela contam no card da 2C
