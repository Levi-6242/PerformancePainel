# -*- coding: utf-8 -*-
"""O macro (Entrada, /painel) diz o mesmo que a tabela de strings do Monitoramento (29/09/2026).

Dois defeitos medidos no servidor às 11:39 de 29/09, os dois do mesmo tipo do "É INADMISSÍVEL" da Rodrigues 2.1 — a regra
chega à tabela e não chega ao macro:

1. **A diferença.** Desde 29/09 a coluna Diferença é a soma das FALTAS de cada inversor (`_dif_por_inversor`), e o
   macro seguia recontando ativas − esperadas: a Poconé 1, com 202/202 e −6 na tabela (6 strings paradas num inversor, 6
   a mais no cadastro de outro), ficava "ok · Normal" no macro, com 0 faltando.
2. **A 2C.** A tabela 2C tem UMA linha por usina — desde 29/09 à noite, só a da API PV (`_2c_linhas_api`; a Ipixuna
   entrou na API como Santa Cecilia 1/2/3 e o e-mail saiu do tempo real). Com o e-mail no meio, o rollup punha as duas e
   deixava disputar: no servidor, onde o e-mail não chega, a linha do e-mail sem dado vencia e a
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
def _email_proibido(*a, **k):
    raise AssertionError("o macro leu o acervo do e-mail da 2C")


def _rollup_2c(monkeypatch, api, grupo=None):
    vazio = {"payload": {"rows": []}}
    for nome in ("_cache", "_sunop_cache", "_axis_cache", "_se_cache", "_semp_cache"):
        monkeypatch.setattr(app, nome, dict(vazio))
    monkeypatch.setattr(app, "_pg_get_snapshot", lambda force=False: ([], None))
    monkeypatch.setattr(app, "_macro_sol_baixo", lambda r, agora=None: False)
    monkeypatch.setattr(app, "_usinas_desligadas_marcas", lambda: {})
    monkeypatch.setattr(app, "_religamentos_abertos_usina", lambda: {})
    monkeypatch.setattr(app, "_etm_leitura_por_pid", lambda: {})
    monkeypatch.setattr(app, "_poa_atual_por_pid", lambda: {})
    monkeypatch.setattr(app, "_owen_strings_rows", _email_proibido)       # 29/09/2026: o e-mail saiu do tempo real
    monkeypatch.setattr(app, "_2capi_cache", {"payload": {"rows": api}})
    if grupo is not None:
        monkeypatch.setattr(app, "USINA_GRUPO", grupo)
    return {u["usina"]: u for u in app._portfolio_rollup()}


ARA_API = {"usina": "Araputanga", "plant_id": 18771898, "strings_ativas": 236, "str_esp": 236, "diferenca": 0,
           "qtd_inversores": 10, "inv_esp": 10, "pot_med": 180.0, "ultima_leitura": "2026-09-29 11:29:00"}


def test_a_2c_do_macro_e_a_linha_da_api(monkeypatch, freeze_now):
    freeze_now("2026-09-29 11:39:00")
    u = _rollup_2c(monkeypatch, [ARA_API])["Araputanga"]
    assert u["status"] == "ok" and u["sub_fonte"] == "api" and u["plant_id"] == 18771898
    assert (u["strings_ativas"], u["str_esp"], u["qtd_inversores"]) == (236, 236, 10) and not u.get("n_partes")


def test_ipixuna_e_a_soma_das_tres_ugs(monkeypatch, freeze_now):
    """A Ipixuna do Pará chega em três plantas da API (Santa Cecilia 1, 2 e 3, uma por UG) e o cadastro liga as três à
    mesma usina: o card mostra UMA Ipixuna, somada, e a falta de uma UG aparece nela."""
    freeze_now("2026-09-29 12:18:00")
    ug = lambda n, pid, inv, esp, **kw: dict({"usina": f"Santa Cecilia {n}", "plant_id": pid, "strings_ativas": esp,
                                              "str_esp": esp, "diferenca": 0, "qtd_inversores": inv, "inv_esp": inv,
                                              "pot_med": 250.0, "ultima_leitura": "2026-09-29 12:10:00"}, **kw)
    grupo = {"Santa Cecilia 1": "Ipixuna do Pará", "Santa Cecilia 2": "Ipixuna do Pará", "Santa Cecilia 3": "Ipixuna do Pará"}
    us = _rollup_2c(monkeypatch, [ug(1, 18771915, 8, 138), ug(2, 18771929, 6, 105, strings_ativas=102, diferenca=-3),
                                  ug(3, 18771930, 6, 105)], grupo)
    assert "Santa Cecilia 1" not in us
    u = us["Ipixuna do Pará"]
    assert u["n_partes"] == 3 and u["qtd_inversores"] == 20 and u["str_esp"] == 348 and u["strings_ativas"] == 345
    assert u["strings_faltando"] == 3 and u["status"] == "atencao" and u["sub_fonte"] == "api"


def test_sem_a_api_a_2c_fica_fora_do_macro(monkeypatch, freeze_now):
    """Sem a tabela da API (worker frio), a 2C não entra: o e-mail de 3 h atrás não é reserva do agora."""
    freeze_now("2026-09-29 12:18:00")
    us = _rollup_2c(monkeypatch, [])
    assert not any(u.get("fonte") == "2C" for u in us.values())


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
