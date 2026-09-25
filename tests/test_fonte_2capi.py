# -*- coding: utf-8 -*-
"""Fonte `2capi` — as três usinas da 2C que a API PV enxerga (conta oem@), na plataforma (Levi, 11/09/2026:
"quero que rode na plataforma primeiro, a gravação eu resolvo após").

Mesmo padrão da SEMP/Alves Lima (`PV_FONTES` + bloco da fonte), com três coisas que só estas três precisam:
  - a API escreve "Sete Lagoa" (singular) e o cadastro "Sete Lagoas" → `nome_usina` traduz pelo alias;
  - "Sete Lagoa" não está no FULL_OM (que é por nome de supervisório) → fonte explícita filtra por ID, não por FULL_OM;
  - a conta oem@ não devolve nome de inversor e as abas da 2C não têm linha no Equipamentos → de-para id→nome
    fechado POR VALOR contra o BD (Tupi 20/20 em 4 dias, Araputanga 10/10 em 2, Sete Lagoa 10/10 no dia que havia)."""
import pathlib

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
IDS = {18771898, 18771901, 18750925, 18772125}     # + a União, em 25/09/2026 ("adicione a usina União em 2C!")


def test_fonte_2capi_tem_as_quatro_usinas_e_e_conta_oem():
    assert app.PV_FONTES["2capi"] == IDS
    assert all(app._pv_fonte_de(i) == "2capi" and app._pv_is_oem(i) for i in IDS)
    assert app._pv_fonte_de(18748888) is None                      # Colorado 2 segue na principal (Thopen)
    assert app._pv_fonte_de(18766373) == "alveslima"               # Morada Nova onde estava


def test_fonte_explicita_filtra_por_id_e_nao_pelo_full_om(monkeypatch):
    plantas = [{"id": 18771901, "nome": "Sete Lagoa"}, {"id": 1, "nome": "X"},
               {"id": 18758732, "nome": "UFV Tucano 1"}, {"id": 2, "nome": "Y"}]
    monkeypatch.setattr(app, "FULL_OM", {"X", "UFV Tucano 1"})
    assert [p["id"] for p in app._pv_plantas_da_fonte(plantas, "2capi")] == [18771901]   # fora do FULL_OM e mesmo assim entra
    assert [p["id"] for p in app._pv_plantas_da_fonte(plantas, None)] == [1]             # principal: FULL_OM e sem as OEM
    assert [p["id"] for p in app._pv_plantas_da_fonte(plantas, "semp")] == [18758732]


def test_nome_da_api_no_singular_vira_o_do_cadastro(monkeypatch):
    monkeypatch.setattr(app, "USINA_DISPLAY", {"Sete Lagoas": "Sete Lagoas", "Araputanga": "Araputanga"})
    assert app.nome_usina(18771901, "Sete Lagoa") == "Sete Lagoas"
    assert app.nome_usina(18771898, "Araputanga ") == "Araputanga"
    assert app.nome_usina(1, "Qualquer") == "Qualquer"


def test_de_para_de_inversor_das_tres_fechado_por_valor():
    assert app.PV_INV_NOMES[18771898] == {400771 + i: f"Inversor 1.{i + 1}" for i in range(10)}
    assert app.PV_INV_NOMES[18771901] == {400784 + i: f"Inversor 1.{i + 1}" for i in range(10)}
    tup = app.PV_INV_NOMES[18750925]
    assert len(tup) == 20 and tup[367506] == "Inversor 1.1" and tup[367520] == "Inversor 2.5" and tup[367525] == "Inversor 2.10"


def test_rotas_entrada_notificacao_e_snapshot():
    regras = {str(r) for r in app.app.url_map.iter_rules()}
    assert {"/api/2capi/data", "/api/2capi/etm", "/api/2capi/etm/analise"} <= regras
    assert not any(fid == "2capi" for _c, _f, fid in app._ENTRADA_GRUPOS)   # UM card "2C" (Levi): a API entra nele
    assert app._ENTRADA_VKEY["2capi"] == "c2"
    assert ("2capi", "2C · API PV") in app._NOTIF_FONTES
    assert {"2capi", "2capi_etm", "2capi_analise"} <= set(app._persist_registry())   # o worker publica, o web instala


def test_strings_problema_conhece_a_fonte(monkeypatch):
    monkeypatch.setattr(app, "_2capi_cache", {"payload": {"rows": []}, "ts": 0.0})
    monkeypatch.setattr(app, "get_plants", lambda tok, force=False: [])
    monkeypatch.setattr(app, "get_token", lambda force=False: "t")
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    assert app._strings_problema_rows("2capi", force=True) == []
    assert app.app.test_client().get("/api/2capi/strings/problema").get_json().get("indisponivel") is not True


def test_fronts_conhecem_a_fonte():
    mon = (RAIZ / "docs/redesign/Monitoramento (novo design).html").read_text(encoding="utf-8")
    assert "'2capi':'/api/2capi/data'" in mon and "'2capi':'c2'" in mon and "id:'2capi'" not in mon   # rotas sim, aba separada não
    assert "sk==='2capi'" in mon and "s==='2capi'" in mon and "'2C (API PV Operation)'" in mon
    ent = (RAIZ / "docs/redesign/Entrada.html").read_text(encoding="utf-8")
    assert '"2C · API PV"' not in ent                                    # a 2C é UM card/uma aba
    por = (RAIZ / "plataforma/templates/painel_portfolio.html").read_text(encoding="utf-8")
    assert "'2C · API PV':'2capi'" in por and "'/api/2capi/etm/analise'" in por
    nj = (RAIZ / "plataforma/static/notif.js").read_text(encoding="utf-8")
    assert '"2capi": "2capi"' in nj
    v2 = (RAIZ / "plataforma/templates/painel_usina_v2.html").read_text(encoding="utf-8")
    assert v2.count("FONTE==='2capi'") == 2


def _rollup_so_com(monkeypatch, owen_rows, api_rows):
    vazio = {"payload": {"rows": []}}
    for nome in ("_cache", "_sunop_cache", "_axis_cache", "_se_cache", "_semp_cache"):
        monkeypatch.setattr(app, nome, dict(vazio))
    monkeypatch.setattr(app, "_pg_get_snapshot", lambda force=False: ([], None))
    monkeypatch.setattr(app, "_macro_sol_baixo", lambda r: False)          # de dia: string a zero conta
    monkeypatch.setattr(app, "_owen_strings_rows", lambda: owen_rows)
    monkeypatch.setattr(app, "_2capi_cache", {"payload": {"rows": api_rows}})
    us = {u["usina"]: u for u in app._portfolio_rollup()}
    return us["Araputanga"]


def test_no_rollup_a_api_vence_o_email_em_empate(monkeypatch):
    """A mesma usina entra pelo e-mail ("2C") e pela API ("2C · API PV"). Em empate de severidade fica quem entrou
    primeiro — e a API entra primeiro: é a fonte viva (strings ao vivo, ETM completa); o e-mail só cobre o que ela não vê."""
    ok = {"usina": "Araputanga", "strings_ativas": 236, "str_esp": 236, "ultima_leitura": "2026-09-11 10:00"}
    u = _rollup_so_com(monkeypatch, [dict(ok, plant_id="ARA")], [dict(ok, plant_id=18771898)])
    assert u["fonte"] == "2C" and u["plant_id"] == 18771898 and u["sub_fonte"] == "api"   # mesmo card, linha da API


def test_no_rollup_um_estado_pior_no_email_ainda_prevalece(monkeypatch):
    """A régua do Painel é 'o pior vence': se o e-mail vê 36 strings faltando e a API não, o card fica com o e-mail."""
    ok = {"usina": "Araputanga", "strings_ativas": 236, "str_esp": 236, "ultima_leitura": "2026-09-11 10:00"}
    pior = dict(ok, strings_ativas=200, plant_id="ARA")
    u = _rollup_so_com(monkeypatch, [pior], [dict(ok, plant_id=18771898)])
    assert u["fonte"] == "2C" and u["strings_faltando"] == 36 and u["plant_id"] == "ARA" and not u.get("sub_fonte")


def test_alias_da_api_vale_em_todos_os_mapas_do_cadastro(monkeypatch):
    """O cadastro diz "Sete Lagoas", a API "Sete Lagoa": esperadas, nomes, Full O&M e display têm de responder pelos dois."""
    monkeypatch.setattr(app, "ESPERADO_INV", {"Sete Lagoas": {"INVERSOR01": 24}})
    monkeypatch.setattr(app, "EQUIP_NAMES", {"Sete Lagoas": {"INVERSOR01": "Inversor 1.1"}})
    monkeypatch.setattr(app, "ESPERADO", {"Sete Lagoas": {"inv_esp": 1, "str_esp": 24}})
    monkeypatch.setattr(app, "USINA_DISPLAY", {"Sete Lagoas": "Sete Lagoas"})
    monkeypatch.setattr(app, "FULL_OM", {"Sete Lagoas"})
    monkeypatch.setattr(app, "STRING_BOX", set())
    monkeypatch.setattr(app, "POWER_INV", {"Sete Lagoas": {"INVERSOR01": 250.0}})
    app._aplica_alias_api_cadastro()
    assert app.ESPERADO_INV["Sete Lagoa"] == {"INVERSOR01": 24} and app.EQUIP_NAMES["Sete Lagoa"]["INVERSOR01"] == "Inversor 1.1"
    assert app.ESPERADO["Sete Lagoa"]["str_esp"] == 24 and app.USINA_DISPLAY["Sete Lagoa"] == "Sete Lagoas"
    assert "Sete Lagoa" in app.FULL_OM and app.POWER_INV["Sete Lagoa"]["INVERSOR01"] == 250.0
    assert "Sete Lagoa" not in app.STRING_BOX                                 # só copia o que o cadastro tem
