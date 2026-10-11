# -*- coding: utf-8 -*-
"""De-para de equipamentos, fatia 1 (Levi, 11/10/2026: "quero que o de-para da equipamentos seja feito na plataforma de
forma intuitiva"): o diagnóstico, só leitura. A regra pura (`depara_diag.py`) e a tela, só de administrador.

Os casos são os do mesmo dia: a API renomeou a Ipixuna e a Morada Nova e as duas ficaram sem esperadas (string morta não
acusava); a União tinha 6 dos 12 inversores no cadastro da ponte; e a conta oem@ nomeia inversor pela ordem dos ids quando
não há de-para (na Morada Nova a ordem errava 6 de 8)."""
import depara_diag as dd

CTX = {"nome_api": {18771915: "Ipixuna do Pará 1"}, "ponte_ids": {18771915: "Santa Cecilia 1"},
       "apelidos": {"Sete Lagoa": "Sete Lagoas"}, "inv_nomes": {18771915: {}, 18772125: {}},
       "provisorios": {18772125: "União: o grupo 1 pela ordem"}, "oem": {18771915, 18772125, 99},
       "sg_por_ordem": {("salenergia", "boa"): True}}


def _r(pid, usina, str_esp=100, inv_esp=6, inv=6):
    return {"plant_id": pid, "usina": usina, "str_esp": str_esp, "inv_esp": inv_esp, "qtd_inversores": inv}


def test_a_planta_renomeada_liga_pelo_id_e_diz_o_nome_que_a_api_escreve():
    u = dd.linha("2capi", _r(18771915, "Santa Cecilia 1", 138, 8, 8), CTX)
    assert u["liga"] == "pelo id (ponte): a API escreve “Ipixuna do Pará 1”"
    assert u["nomes_inversor"] == "de-para no código" and u["alertas"] == [] and u["pior"] == "ok"


def test_sem_esperadas_e_critico_porque_string_morta_nao_acusa():
    u = dd.linha("pv", _r(5, "Usina X", str_esp=None), CTX)
    assert u["pior"] == "critico" and "string morta não acusa" in u["alertas"][0]["texto"]
    assert dd.linha("pv", _r(5, "Usina X", str_esp=0), CTX)["pior"] == "critico"


def test_vale_o_cadastro_nao_o_desconto_da_leitura():
    """1ª prova no PC (11/10, 19h): 20 usinas da Thopen "sem esperadas" que tinham cadastro. Eram String Box à noite: o
    `str_esp` da linha vem com os inversores sem visão descontados e fica 0."""
    noite = {**_r(60061, "Altair 2 (74)", 0, 8, 8), "stringbox": True, "sem_visao": True, "str_esp_cadastro": 152}
    u = dd.linha("pv", noite, CTX)
    assert u["str_esp"] == 152 and u["alertas"] == []
    # cadastro vazio de verdade: crítico; com a régua por inversor vigiando, atenção
    assert dd.linha("pv", {**noite, "str_esp_cadastro": None}, CTX)["pior"] == "critico"
    barretos = {**noite, "str_esp_cadastro": None, "inv_padrao": {"status": "ok"}}
    assert dd.linha("pv", barretos, CTX)["alertas"][0]["texto"].endswith("régua por inversor (padrão 30 dias)")
    # fonte sem o total do cadastro na linha: zero de leitura sem visão ou sem dados não acusa nada
    sem = {"plant_id": "MRO100", "usina": "Morro", "sem_dados": True}
    assert dd.linha("sunop", sem, CTX)["pior"] == "info"
    # o nome que a API escreve vem da própria linha
    assert dd.linha("2capi", {**_r(18771915, "Santa Cecilia 1"), "nome_api": "Ipixuna do Pará 1"},
                    {**CTX, "nome_api": {}})["liga"] == "pelo id (ponte): a API escreve “Ipixuna do Pará 1”"


def test_inversores_na_fonte_diferente_do_cadastro_e_o_provisorio_vem_junto():
    u = dd.linha("2capi", _r(18772125, "União 1 e 2", 108, 6, 12), CTX)
    assert [(a["nivel"], a["texto"]) for a in u["alertas"]] == \
        [("atencao", "12 inversor(es) na fonte, 6 no cadastro"), ("info", "União: o grupo 1 pela ordem")]
    assert u["pior"] == "atencao"
    # só o provisório: aparece na fonte, mas não vai para "Precisa de você"
    assert dd.linha("2capi", _r(18772125, "União 1 e 2", 216, 12, 12), CTX)["pior"] == "info"


def test_nome_de_inversor_pela_ordem_e_aviso():
    u = dd.linha("2capi", _r(99, "Nova da oem"), CTX)
    assert u["nomes_inversor"] == "pela ordem do cadastro" and u["pior"] == "atencao"
    assert dd.linha("pv", _r(7, "Altair 1"), CTX)["nomes_inversor"] == "o nome que a fonte manda"
    s = dd.linha("salenergia", _r("boa", "Boa Esperança do Sul"), CTX)               # scadaGridco sem de-para por valor
    assert s["nomes_inversor"] == "pela ordem do cadastro" and s["pior"] == "atencao"
    assert dd.linha("greenyellow", _r("irece2", "Irecê 2"), CTX)["nomes_inversor"] == "o nome que a fonte manda"


def test_apelido_vale_so_nas_contas_da_api_pv():
    assert dd.linha("2capi", _r(18771901, "Sete Lagoas"), CTX)["liga"] == "por apelido no código"
    assert dd.linha("sunop", _r("STL", "Sete Lagoas"), CTX)["liga"] == "pelo nome"
    assert dd.linha("pv", _r(1, "Altair 1"), CTX)["liga"] == "pelo nome"


def test_o_diagnostico_junta_por_fonte_poe_o_pior_na_frente_e_diz_quem_nao_foi_lido():
    tabelas = {"2capi": [_r(18772125, "União 1 e 2", 108, 6, 12), _r(18771915, "Santa Cecilia 1", 138, 8, 8),
                         _r(18766373, "MORADA NOVA", None, None, 8), {"usina": "sem id"}],
               "pg": []}
    d = dd.diagnostico(tabelas, CTX)
    por = {f["id"]: f for f in d["fontes"]}
    assert list(por) == list(dd.ROTULOS)                         # toda fonte do tempo real aparece, na mesma ordem
    assert por["sunop"]["lida"] is False and por["pg"]["lida"] is True and por["pg"]["usinas"] == []
    assert [u["usina"] for u in por["2capi"]["usinas"]] == ["MORADA NOVA", "União 1 e 2", "Santa Cecilia 1"]
    assert [(u["usina"], u["pior"]) for u in d["precisa"]] == [("MORADA NOVA", "critico"), ("União 1 e 2", "atencao")]
    assert d["contagem"] == {"usinas": 3, "criticos": 1, "atencao": 1}


# ── a tela ───────────────────────────────────────────────────────────────────────────────────────────────────────────
import app  # noqa: E402
from test_porta_nexus import _sem_rede, cli, entrar, entrar_com_senha  # noqa: E402,F401  (fixtures e passos da porta)


def test_todo_provisorio_e_de_um_de_para_que_existe():
    assert set(app.PV_INV_PROVISORIOS) <= set(app.PV_INV_NOMES)


def test_a_linha_da_api_pv_leva_o_cadastro_antes_dos_descontos_e_o_nome_da_api(monkeypatch):
    monkeypatch.setattr(app, "ESPERADO", {"Santa Cecilia 1": {"inv_esp": 8, "str_esp": 138}})
    planta = {"id": 18771915, "nome": "Santa Cecilia 1", "nome_api": "Ipixuna do Pará 1"}
    assert app._pv_cadastro_da_linha(planta) == {"str_esp_cadastro": 138, "nome_api": "Ipixuna do Pará 1"}
    assert app._pv_cadastro_da_linha({"id": 1, "nome": "Sem Cadastro "}) == {"str_esp_cadastro": None}


def test_a_rota_le_so_o_que_a_plataforma_ja_tem_em_cache(cli, monkeypatch):
    entrar_com_senha(cli)
    monkeypatch.setattr(app, "_2capi_cache", {"payload": {"rows": [_r(18766373, "MORADA NOVA", 128, 8, 8)]}})
    monkeypatch.setattr(app, "_pg_cache", {"summary": [_r(21480, "Indaiatuba", 400, 20, 20)], "detail": {}, "ts": 0.0})
    monkeypatch.setattr(app, "_plants_cache", {"ts": 0.0, "data": [{"id": 18766373, "nome": "MORADA NOVA",
                                                                    "nome_api": "Morada Nova"}]})
    monkeypatch.setattr(app, "_se_cache", {})                                         # não montada: "não lida"
    d = cli.get("/api/admin/de-para").get_json()
    por = {f["id"]: f for f in d["fontes"]}
    mn = por["2capi"]["usinas"][0]
    assert mn["liga"] == "pelo id (ponte): a API escreve “Morada Nova”" and mn["nomes_inversor"] == "de-para no código"
    assert [a["nivel"] for a in mn["alertas"]] == ["info"]                             # o INVERSOR08 por eliminação
    assert por["pg"]["usinas"][0]["liga"] == "pelo nome" and por["solaredge"]["lida"] is False
    assert d["rotulos"]["2capi"] == "2C"


def test_a_tela_e_so_de_administrador_do_nexus(cli):
    entrar(cli, "analista@exemplo.com", destino="/admin/de-para", admin=False)
    assert cli.get("/admin/de-para").status_code == 403
    assert cli.get("/api/admin/de-para").status_code == 403
    entrar(cli, "admin@exemplo.com", destino="/admin/de-para", admin=True)
    h = cli.get("/admin/de-para").get_data(as_text=True)
    assert "<h1>De-para de equipamentos</h1>" in h and 'href="/" data-casca' in h
    assert cli.get("/api/admin/de-para").status_code == 200
