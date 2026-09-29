# -*- coding: utf-8 -*-
"""O macro (Entrada, /painel) diz o mesmo que a tabela de strings do Monitoramento (29/09/2026).

Dois defeitos medidos no servidor às 11:39 de 29/09, os dois do mesmo tipo do "É INADMISSÍVEL" da Rodrigues 2.1 — a regra
chega à tabela e não chega ao macro:

1. **A diferença.** Desde 29/09 a coluna Diferença é a soma das FALTAS de cada inversor (`_dif_por_inversor`), e o
   macro seguia recontando ativas − esperadas: a Poconé 1, com 202/202 e −6 na tabela (6 strings paradas num inversor, 6
   a mais no cadastro de outro), ficava "ok · Normal" no macro, com 0 faltando.
2. **A 2C.** A tabela 2C tem UMA linha por usina (`_2c_unifica_rows`: a da API PV onde ela vê, a do e-mail no resto). O
   rollup punha as duas e deixava disputar: no servidor, onde o e-mail não chega, a linha do e-mail sem dado vencia e a
   Entrada dizia "4 sem comunicação" com Araputanga, Sete Lagoas e Tupi Paulista lendo às 11:29 pela API; no PC, as duas
   eram SOMADAS como fatias da mesma usina (Araputanga 472 ativas de 236, Tupi Paulista 800 de 400).

E a Entrada contava as strings da usina que a tabela deixa neutra (pouca luz, sem sol): ela lia a diferença crua, não o
`strings_faltando` que o macro já silenciou.
"""
import app


# ── 1. a diferença do macro é a da tabela ──────────────────────────────────────────────────────────────────────────
def test_macro_dif_e_a_diferenca_da_tabela():
    assert app._macro_dif({"strings_ativas": 202, "str_esp": 202, "diferenca": -6}) == -6     # Poconé 1, 29/09
    assert app._macro_dif({"strings_ativas": 93, "str_esp": 103, "diferenca": -12}) == -12    # Fernandópolis 1: esperada sem inversor
    assert app._macro_dif({"strings_ativas": 138, "str_esp": 136, "diferenca": 0}) == 0       # Ouro Branco 2: a sobra não é déficit


def test_sem_a_diferenca_vale_a_conta_pelo_total():
    assert app._macro_dif({"strings_ativas": 210, "str_esp": 216}) == -6                      # linha antiga, sem o campo
    assert app._macro_dif({"strings_ativas": 210, "str_esp": 216, "diferenca": None}) == -6
    assert app._macro_dif({"strings_ativas": 0, "str_esp": None, "diferenca": None}) is None


def _pocone(**kw):
    r = {"usina": "Poconé 1", "plant_id": 1, "strings_ativas": 202, "str_esp": 202, "diferenca": -6,
         "strings_acima_cadastro": 6, "qtd_inversores": 10, "inv_esp": 10, "inv_off": 0, "pot_med": 180.0,
         "ultima_leitura": "2026-09-29 11:29:00"}
    r.update(kw)
    return r


def test_pocone_fica_critica_no_macro_como_na_tabela(freeze_now):
    freeze_now("2026-09-29 11:39:00")
    it = app._macro_item("API PV", _pocone())
    assert it["status"] == "critico" and it["strings_faltando"] == 6 and it["diferenca"] == -6
    assert it["causa"] == "6 string(s) abaixo do esperado"


def test_o_card_da_entrada_conta_as_seis(freeze_now):
    freeze_now("2026-09-29 11:39:00")
    assert app._entrada_tr_strings_de(app._macro_item("API PV", _pocone()))["strings_faltando"] == 6


# ── a Entrada não conta o que a tabela deixa neutro ─────────────────────────────────────────────────────────────────
def test_entrada_nao_conta_a_usina_em_pouca_luz(freeze_now):
    """Diamantino às 08:42 de 29/09: 0 de 57 ativas, "Baixa irradiância" na tabela, com a Diferença em "—"."""
    freeze_now("2026-09-29 08:42:00")
    it = app._macro_item("API PV", _pocone(strings_ativas=0, diferenca=-202, rampa=True, pot_med=0.6,
                                           pouca_luz={"por": "estacao", "texto": "estação a 3,5 W/m²"}))
    assert it["strings_faltando"] == 0
    assert app._entrada_tr_strings_de(it)["strings_faltando"] == 0


def test_entrada_nao_conta_a_usina_sem_sol(freeze_now, monkeypatch):
    """17:40 em setembro: o sol já passou abaixo de 8° no estado, a tabela diz "Sem sol", a Entrada só vira noite às 19 h."""
    freeze_now("2026-09-29 17:40:00")
    monkeypatch.setattr(app, "_macro_sol_baixo", lambda r, agora=None: True)
    it = app._macro_item("API PV", _pocone(strings_ativas=12, diferenca=-190))
    assert it["strings_faltando"] == 0
    assert app._entrada_tr_strings_de(it)["strings_faltando"] == 0


# ── 2. a 2C do macro é a da tabela ─────────────────────────────────────────────────────────────────────────────────
def _rollup_2c(monkeypatch, email, api):
    vazio = {"payload": {"rows": []}}
    for nome in ("_cache", "_sunop_cache", "_axis_cache", "_se_cache", "_semp_cache"):
        monkeypatch.setattr(app, nome, dict(vazio))
    monkeypatch.setattr(app, "_pg_get_snapshot", lambda force=False: ([], None))
    monkeypatch.setattr(app, "_macro_sol_baixo", lambda r, agora=None: False)
    monkeypatch.setattr(app, "_usinas_desligadas_marcas", lambda: {})
    monkeypatch.setattr(app, "_religamentos_abertos_usina", lambda: {})
    monkeypatch.setattr(app, "_etm_leitura_por_pid", lambda: {})
    monkeypatch.setattr(app, "_poa_atual_por_pid", lambda: {})
    monkeypatch.setattr(app, "_owen_strings_rows", lambda: email)
    monkeypatch.setattr(app, "_2capi_cache", {"payload": {"rows": api}})
    return {u["usina"]: u for u in app._portfolio_rollup()}


ARA_API = {"usina": "Araputanga", "plant_id": 18771898, "strings_ativas": 236, "str_esp": 236, "diferenca": 0,
           "qtd_inversores": 10, "inv_esp": 10, "pot_med": 180.0, "ultima_leitura": "2026-09-29 11:29:00"}
ARA_EMAIL = {"usina": "Araputanga", "plant_id": "ARA", "strings_ativas": 236, "str_esp": None, "diferenca": None,
             "qtd_inversores": 10, "ultima_leitura": "2026-09-29 08:59"}


def test_email_sem_dado_nao_derruba_a_usina_que_a_api_ve(monkeypatch, freeze_now):
    freeze_now("2026-09-29 11:39:00")
    us = _rollup_2c(monkeypatch, [{"usina": "Araputanga", "plant_id": "ARA", "sem_dados": True,
                                   "strings_ativas": None, "str_esp": None, "qtd_inversores": 0}], [ARA_API])
    u = us["Araputanga"]
    assert u["status"] == "ok" and u["sub_fonte"] == "api" and u["plant_id"] == 18771898


def test_email_e_api_da_mesma_usina_nao_se_somam(monkeypatch, freeze_now):
    freeze_now("2026-09-29 12:18:00")
    u = _rollup_2c(monkeypatch, [ARA_EMAIL], [ARA_API])["Araputanga"]
    assert (u["strings_ativas"], u["str_esp"], u["qtd_inversores"]) == (236, 236, 10)
    assert not u.get("n_partes")


def test_usina_que_so_o_email_ve_segue_pelo_email(monkeypatch, freeze_now):
    freeze_now("2026-09-29 12:18:00")
    ipx = {"usina": "Ipixuna do Pará", "plant_id": "IPX", "strings_ativas": 348, "str_esp": 348, "diferenca": 0,
           "qtd_inversores": 20, "ultima_leitura": "2026-09-29 11:59"}
    us = _rollup_2c(monkeypatch, [ARA_EMAIL, ipx], [ARA_API])
    assert us["Ipixuna do Pará"]["sub_fonte"] == "email" and us["Ipixuna do Pará"]["status"] == "ok"
    assert us["Araputanga"]["sub_fonte"] == "api"


def test_sem_a_api_a_2c_segue_inteira_pelo_email(monkeypatch, freeze_now):
    freeze_now("2026-09-29 12:18:00")
    u = _rollup_2c(monkeypatch, [dict(ARA_EMAIL, str_esp=236, diferenca=0)], [])["Araputanga"]
    assert u["plant_id"] == "ARA" and u["sub_fonte"] == "email" and u["status"] == "ok"


# ── 3. quem a régua de strings cala não entra no ranking como "sem geração" ────────────────────────────────────────
def _rollup_pv(monkeypatch, rows, grupo):
    vazio = {"payload": {"rows": []}}
    for nome in ("_sunop_cache", "_axis_cache", "_se_cache", "_semp_cache", "_2capi_cache"):
        monkeypatch.setattr(app, nome, dict(vazio))
    monkeypatch.setattr(app, "_cache", {"payload": {"rows": rows}})
    monkeypatch.setattr(app, "INV_PADRAO_PLANTAS", set())
    monkeypatch.setattr(app, "USINA_GRUPO", grupo)
    monkeypatch.setattr(app, "_pg_get_snapshot", lambda force=False: ([], None))
    monkeypatch.setattr(app, "_owen_strings_rows", lambda: [])
    monkeypatch.setattr(app, "_usinas_desligadas_marcas", lambda: {})
    monkeypatch.setattr(app, "_religamentos_abertos_usina", lambda: {})
    monkeypatch.setattr(app, "_etm_leitura_por_pid", lambda: {})
    monkeypatch.setattr(app, "_poa_atual_por_pid", lambda: {})
    return {u["usina"]: u for u in app._portfolio_rollup()}


def _parte(nome, pid, **kw):
    r = {"usina": nome, "plant_id": pid, "strings_ativas": 100, "str_esp": 100, "diferenca": 0, "qtd_inversores": 8,
         "inv_esp": 8, "inv_off": 0, "pot_med": 90.0, "ultima_leitura": "2026-09-29 12:30:00"}
    r.update(kw)
    return r


def test_fatia_sem_visao_nao_esconde_a_fatia_com_falha(monkeypatch, freeze_now):
    """Ceilândia 1 às 12:40 de 29/09: "ok · Sem visão por string" com a 1.1 e a 1.3 críticas. A fatia sem visão tem 0
    ativas, a severidade da linha diz "sem geração" (0) e ela vencia a disputa da usina física."""
    freeze_now("2026-09-29 12:40:00")
    grupo = {"Ceilandia 1.1 (89)": "Ceilândia 1", "Ceilandia 1.2 (90)": "Ceilândia 1"}
    us = _rollup_pv(monkeypatch, [
        _parte("Ceilandia 1.1 (89)", 53241, strings_ativas=92, diferenca=-8),
        _parte("Ceilandia 1.2 (90)", 53243, strings_ativas=0, str_esp=None, diferenca=None, sem_visao=True)], grupo)
    u = us["Ceilândia 1"]
    assert u["status"] == "critico" and u["strings_faltando"] == 8 and u["plant_id"] == 53241


def test_pouca_luz_e_sem_visao_nao_sobem_no_ranking(freeze_now):
    """Poconé 1 e Diamantino, em pouca luz ("Baixa irradiância" na tabela), estavam entre as 8 primeiras do NOC, com a
    pílula verde."""
    freeze_now("2026-09-29 12:40:00")
    assert app._macro_item("API PV", _pocone(strings_ativas=0, diferenca=-202, rampa=True))["sev"] == 5
    assert app._macro_item("API PV", _parte("Céu Azul I (102)", 60006, strings_ativas=0, str_esp=None,
                                            diferenca=None, sem_visao=True))["sev"] == 5
    assert app._macro_item("API PV", _pocone(strings_ativas=0, diferenca=-202, rampa=True,
                                             inv_desligados=1))["sev"] == 1       # o desligado de verdade: degrau da falha


def test_usina_fatiada_em_pouca_luz_nao_diz_strings_abaixo(monkeypatch, freeze_now):
    """Diamantino às 12:38 de 29/09: "ok" com a causa "204 string(s) abaixo do esperado" — a soma das fatias recontava
    a diferença crua da fatia em pouca luz."""
    freeze_now("2026-09-29 12:38:00")
    grupo = {"Diamantino 1 (117)": "Diamantino", "Diamantino 2 (118)": "Diamantino"}
    us = _rollup_pv(monkeypatch, [
        _parte("Diamantino 1 (117)", 18751455, strings_ativas=0, str_esp=204, diferenca=-204, rampa=True, pot_med=0.8,
               pouca_luz={"por": "estacao", "texto": "estação a 40 W/m²"}),
        _parte("Diamantino 2 (118)", 18751454, strings_ativas=204, str_esp=204)], grupo)
    u = us["Diamantino"]
    assert u["status"] == "ok" and u["strings_faltando"] == 0 and u["diferenca"] == 0
    assert "abaixo do esperado" not in u["causa"]


def test_email_quebrado_nao_derruba_a_api(monkeypatch, freeze_now):
    freeze_now("2026-09-29 12:18:00")

    def _quebra():
        raise OSError("pasta do e-mail fora")

    vazio = {"payload": {"rows": []}}
    for nome in ("_cache", "_sunop_cache", "_axis_cache", "_se_cache", "_semp_cache"):
        monkeypatch.setattr(app, nome, dict(vazio))
    monkeypatch.setattr(app, "_pg_get_snapshot", lambda force=False: ([], None))
    monkeypatch.setattr(app, "_macro_sol_baixo", lambda r, agora=None: False)
    monkeypatch.setattr(app, "_usinas_desligadas_marcas", lambda: {})
    monkeypatch.setattr(app, "_religamentos_abertos_usina", lambda: {})
    monkeypatch.setattr(app, "_etm_leitura_por_pid", lambda: {})
    monkeypatch.setattr(app, "_poa_atual_por_pid", lambda: {})
    monkeypatch.setattr(app, "_owen_strings_rows", _quebra)
    monkeypatch.setattr(app, "_2capi_cache", {"payload": {"rows": [ARA_API]}})
    us = {u["usina"]: u for u in app._portfolio_rollup()}
    assert us["Araputanga"]["sub_fonte"] == "api" and us["Araputanga"]["status"] == "ok"
