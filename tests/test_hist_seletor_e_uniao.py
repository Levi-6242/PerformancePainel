# -*- coding: utf-8 -*-
"""28/09/2026 — o seletor do Histórico PR, o cadastro da União e os nomes da curva da 2C.

1) Ana: "córrego de sapucaia não aparece na parte do painel - histórico"; Levi: "vejo quais usinas também não aparecem
   e faça aparecer!". O seletor mostrava só Full O&M, casando o nome da carteira do banco com o do cadastro por
   `_nrm` (tira espaço, não tira acento): 38 das 116 usinas sumiam — 6 delas Full O&M por diferença de grafia
   (Córrego × Corrego, Marajoara 1 × Marajoara I, Primavera × Primavera 1 e 2, Santo Antonio da × do Platina…) e as
   outras sem dizer por quê. Agora a chave é tolerante e as que não são Full O&M aparecem num grupo à parte.
2) Levi: "faltou o de-para para união, já está na aba equipamentos porém não apareceu na plataforma". O cadastro dela
   está sob o supervisório "UNI" (UNI_Inv_1.1…2.6, 12 inversores), a API tem a "União" com 6 (só a UG 01).
3) De quebra: a curva do drill nas usinas da 2C pela API PV nomeava os inversores "INV-400771" enquanto o drill
   pedia "Inversor 1.1" — e desenhava a curva do PRIMEIRO inversor em todos os outros.
"""
import json as _json
import shutil as _sh
import subprocess as _sp
from pathlib import Path

import pytest as _pt

import app
import dashboard_thopen

_PAINEL = (Path(__file__).resolve().parent.parent / "plataforma" / "templates" / "painel_portfolio.html").read_text(encoding="utf-8")


# ── 1) seletor do Histórico ──────────────────────────────────────────────────────────────────────────────────────

@_pt.mark.parametrize("a,b", [
    ("Córrego do Sapucaia", "Corrego do Sapucaia"),
    ("Marajoara 1", "Marajoara I"),
    ("Piracicaba 1", "Piracicaba I"),
    ("Santo Antonio da Platina", "Santo Antonio do Platina"),
    ("Ouro Branco IV", "Ouro Branco 4"),
])
def test_a_chave_solta_casa_grafias_da_mesma_usina(a, b):
    assert app._usina_chave_solta(a) == app._usina_chave_solta(b)


@_pt.mark.parametrize("a,b", [("Vargem Grande 1", "Vargem Grande IB"), ("Goytacazes 4 2", "Goytacazes 1"),
                              ("Marajoara 2 1", "Marajoara I")])
def test_a_chave_solta_nao_inventa_casamento(a, b):
    assert app._usina_chave_solta(a) != app._usina_chave_solta(b)


@_pt.fixture
def _cadastro(monkeypatch):
    carteiras = {"Córrego do Sapucaia": "Thopen", "Marajoara 1": "Polaris", "Primavera": "Thopen", "Lyon": "Thopen",
                 "Ouro Branco I": "Matrix", "Nova Londrina": "Thopen", "Caxambu": "Thopen"}
    monkeypatch.setattr(dashboard_thopen, "_CARTEIRA_DE", carteiras)
    monkeypatch.setattr(app, "FULL_OM_DISP_NOMES", {"Corrego do Sapucaia", "Marajoara I", "Primavera 1", "Primavera 2",
                                                     "Nova Londrina 1", "Caxambu"})
    monkeypatch.setattr(app, "USINA_DISPLAY", {"Corrego Sapucaia 1 (113)": "Corrego do Sapucaia", "(321) Marajoara I": "Marajoara I",
                                               "Primavera 1 (115)": "Primavera 1", "Primavera 2 (116)": "Primavera 2",
                                               "Sol Maior GD I (184)": "Lyon", "Nova Londrina 1 (152)": "Nova Londrina 1",
                                               "Nova Londrina 2 (153)": "Nova Londrina 2", "(292) Caxambu": "Caxambu"})
    monkeypatch.setattr(app, "_g_th_carteiras", lambda: ["Copel", "Matrix", "Polaris", "Thopen"])


def test_seletor_do_thopen_acha_as_full_om_e_mostra_as_outras_com_o_motivo(_cadastro):
    full, outras = app._g_th_usinas_grupos("Thopen")
    assert full == ["Caxambu", "Córrego do Sapucaia", "Marajoara 1", "Primavera"], "Primavera = Primavera 1 e 2, as duas Full O&M"
    mot = {o["usina"]: o["motivo"] for o in outras}
    assert "Não" in mot["Lyon"], "Lyon está no cadastro com Full O&M = Não"
    assert "fora da aba Equipamentos" in mot["Ouro Branco I"]
    assert "Não" in mot["Nova Londrina"], "Nova Londrina 2 não é Full O&M: a usina inteira não é"
    assert app._g_th_usinas("Thopen") == full, "quem só quer as Full O&M continua recebendo só elas"


def test_rota_devolve_os_grupos_e_a_lista_simples_com_todas(monkeypatch, _cadastro):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    c = app.app.test_client()
    g = c.get("/api/g/usinas?cliente=Thopen&grupos=1").get_json()
    assert g["full_om"][1] == "Córrego do Sapucaia" and len(g["outras"]) == 3 and g["rotulos"][0] == "Full O&M"
    simples = c.get("/api/g/usinas?cliente=Thopen").get_json()
    assert len(simples) == 7 and simples[:4] == g["full_om"], "nenhuma some da lista simples (a página de redesign)"


def test_cliente_fora_do_banco_mostra_as_do_cadastro_sem_aba(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    monkeypatch.setattr(app, "_g_th_carteiras", lambda: ["Thopen"])
    monkeypatch.setattr(app, "_g_registry", lambda: ({}, {"Axis": ["Lajedo 2"]}))
    monkeypatch.setattr(app, "INFO_GERAL", {"lajedo2": {"usina": "Lajedo 2", "cliente": "Axis"},
                                           "novavenecia1": {"usina": "Nova Venécia 1", "cliente": "Axis"},
                                           "caxambu": {"usina": "Caxambu", "cliente": "Thopen"}})
    g = app.app.test_client().get("/api/g/usinas?cliente=Axis&grupos=1").get_json()
    assert g["full_om"] == ["Lajedo 2"] and [o["usina"] for o in g["outras"]] == ["Nova Venécia 1"]
    assert "sem aba no BD_Performance" in g["outras"][0]["motivo"]


@_pt.mark.parametrize("dias,motivo", [
    ([], "sem dia no BD_Thopen"),                                                     # Delmiro Gouvea 1…4 e mais 11
    ([{"ger": 33139.7, "ipoa": 0.0}, {"ger": 20256.8, "ipoa": None}], "IPOA zerado"), # Guatambu: geração desde julho
    ([{"ger": None, "ipoa": 5.1}], "sem geração"),
])
def test_grafico_vazio_diz_o_porque(monkeypatch, dias, motivo):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    monkeypatch.setattr(app, "_g_th_carteiras", lambda: ["Thopen"])
    monkeypatch.setattr(app, "_g_th_pot", lambda u: 6.1)
    monkeypatch.setattr(app, "_g_th_daily", lambda u: [])
    monkeypatch.setattr(dashboard_thopen, "_daily_records", lambda u: dias)
    d = app.app.test_client().get("/api/g/mensal?cliente=Thopen&usina=Guatambu").get_json()
    assert d["pontos"] == [] and motivo in (d.get("motivo") or "")


def test_grafico_com_pr_nao_leva_motivo_e_sem_potencia_leva(monkeypatch):
    import datetime as _dt
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    monkeypatch.setattr(app, "_g_th_carteiras", lambda: ["Thopen"])
    monkeypatch.setattr(app, "_g_th_meta", lambda u, a, m: 0.8)
    monkeypatch.setattr(app, "_g_th_daily", lambda u: [{"data": _dt.date(2026, 9, 1), "ger": 12000.0, "ipoa": 5.0}])
    c = app.app.test_client()
    monkeypatch.setattr(app, "_g_th_pot", lambda u: 3.0)
    assert c.get("/api/g/mensal?cliente=Thopen&usina=X").get_json().get("motivo") is None
    monkeypatch.setattr(app, "_g_th_pot", lambda u: None)
    assert "potência" in c.get("/api/g/mensal?cliente=Thopen&usina=X").get_json()["motivo"]


def test_grafico_vazio_fora_do_banco_diz_o_porque(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    monkeypatch.setattr(app, "_g_th_carteiras", lambda: ["Thopen"])
    monkeypatch.setattr(app, "_g_get", lambda cli: (app.pd.DataFrame(), app.pd.DataFrame()))
    d = app.app.test_client().get("/api/g/mensal?cliente=Axis&usina=Nova%20Ven%C3%A9cia%201").get_json()
    assert d["pontos"] == [] and "BD_Performance" in d["motivo"]


def _node(js, nome="gUsiOpcoes"):
    node = _sh.which("node")
    if not node:
        _pt.skip("node não instalado")
    i = _PAINEL.index(f"function {nome}(")
    fn = _PAINEL[i:_PAINEL.index("\n}\n", i) + 3]
    p = _sp.run([node, "-e", fn + js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return _json.loads(p.stdout)


def test_o_painel_separa_os_grupos_e_explica_cada_uma():
    h = _node("process.stdout.write(JSON.stringify(gUsiOpcoes({full_om:['Córrego do Sapucaia'],outras:[{usina:'Lyon',"
              "motivo:'Full O&M = Não no cadastro (aba Equipamentos)'}],rotulos:['Full O&M','Sem Full O&M no cadastro']})))")
    assert '<optgroup label="Full O&amp;M"><option>Córrego do Sapucaia</option></optgroup>' in h
    assert '<optgroup label="Sem Full O&amp;M no cadastro"><option title="Full O&amp;M = Não no cadastro (aba Equipamentos)">Lyon</option>' in h
    assert _node("process.stdout.write(JSON.stringify(gUsiOpcoes(['A','B'])))") == "<option>A</option><option>B</option>"


def test_o_card_mensal_vazio_mostra_o_motivo_e_o_cheio_volta_ao_texto_de_sempre():
    s = _node("process.stdout.write(JSON.stringify([gMensalSubTxt({pontos:[],motivo:'sem dia no BD_Thopen para esta usina'},"
              "'Barras = PR'), gMensalSubTxt({pontos:[{mes:9}],motivo:null},'Barras = PR')]))", "gMensalSubTxt")
    assert "sem dia no BD_Thopen para esta usina" in s[0] and s[1] == "Barras = PR"
    assert "gMensalSubTxt(d," in _PAINEL, "o gMensal usa o texto (senão o motivo nunca aparece)"


# ── 2) cadastro da União ─────────────────────────────────────────────────────────────────────────────────────────

def test_o_cadastro_da_uniao_sob_o_codigo_uni_chega_a_usina_da_api_so_com_a_ug01(monkeypatch):
    esp = {"UNI": {**{f"UNI_Inv_1.{i}": 18 for i in range(1, 7)}, **{f"UNI_Inv_2.{i}": 18 for i in range(1, 7)}}}
    nomes = {"UNI": {f"UNI_Inv_{u}.{i}": f"Inversor {u}.{i}" for u in (1, 2) for i in range(1, 7)}}
    monkeypatch.setattr(app, "ESPERADO_INV", esp)
    monkeypatch.setattr(app, "EQUIP_NAMES", nomes)
    monkeypatch.setattr(app, "ESPERADO", {"UNI": {"inv_esp": 12, "str_esp": 216}})
    # como o load_equipamentos grava: pelo _nrm do supervisório E do nome de exibição de cada inversor
    monkeypatch.setattr(app, "POWER_INV", {"UNI": {app._nrm(n): 360.36 for u in (1, 2) for i in range(1, 7)
                                                   for n in (f"UNI_Inv_{u}.{i}", f"Inversor {u}.{i}")}})
    monkeypatch.setattr(app, "USINA_DISPLAY", {"UNI": "União 1 e 2", "União 1 e 2": "União 1 e 2"})
    monkeypatch.setattr(app, "FULL_OM", {"UNI", "União 1 e 2"})
    monkeypatch.setattr(app, "STRING_BOX", set())
    app._aplica_alias_api_cadastro()
    assert sorted(app.ESPERADO_INV["União"]) == [f"UNI_Inv_1.{i}" for i in range(1, 7)], "só a UG 01 — é o que a API tem"
    assert app.ESPERADO["União"] == {"inv_esp": 6, "str_esp": 108}, "não 216: seriam 108 strings 'faltando' que não existem"
    assert app.EQUIP_NAMES["União"]["UNI_Inv_1.1"] == "Inversor 1.1"
    assert app._pot_inv("União", "UNI_Inv_1.6", "Inversor 1.6") == 360.36, "sem o kWp o PR por inversor sai nulo"
    assert len(app.POWER_INV["União"]) == 12 and app._pot_inv("União", "UNI_Inv_2.1", "Inversor 2.1") is None
    assert "União" in app.FULL_OM and app.USINA_DISPLAY["União"] == "União 1 e 2"


def test_os_seis_inversores_da_uniao_tem_nome_de_cadastro():
    assert [app._pv_nome_2c(18772125, 401313 + i) for i in range(6)] == [f"UNI_Inv_1.{i}" for i in range(1, 7)]


# ── 3) a curva da 2C com os nomes do drill ───────────────────────────────────────────────────────────────────────

class _SemPlantDevices:
    def get(self, *a, **k):
        raise ConnectionError("conta oem@: plant_devices negado")


def _rec(inv, hhmm, ipvs):
    return {"idefinversor": inv, "tsleitura_new": f"2026-09-28 {hhmm}:00", "conteudojson": _json.dumps(ipvs)}


class _Resp:
    def __init__(self, d):
        self._d, self.status_code = d, 200

    def json(self):
        return self._d


def test_drill_e_curva_dao_o_mesmo_nome_com_cadastro_de_10_inversores(monkeypatch, freeze_now):
    """Se a usina da conta oem@ ganhar cadastro (a União ganhou em 28/09), o drill casava os ids com o cadastro POR
    ORDEM DE TEXTO — "1.10" antes de "1.2" — antes do de-para por valor: o 2º id virava o Inversor 1.10."""
    freeze_now("2026-09-28 12:05:00")
    pid, nome = 987771, "Usina Teste OEM 10"
    ids = [500001 + i for i in range(10)]
    recs = [_rec(i, "12:00", {"Pac": 80.0, "Ipv1": 8.0, "Ipv2": 8.2}) for i in ids]

    class _Http:
        def post(self, url, **k):
            return _Resp([] if "custom_query" in url else recs)

        def get(self, url, **k):
            return _Resp({"message": "Invalid permission"})       # a conta oem@ não lista dispositivos
    monkeypatch.setattr(app, "_http", lambda: _Http())
    monkeypatch.setattr(app, "get_plants", lambda token, force=False: [{"id": pid, "nome": nome}])
    monkeypatch.setattr(app, "get_token", lambda: "tok")
    monkeypatch.setattr(app, "_pv_token_for", lambda p: "tok")
    monkeypatch.setattr(app, "_os_atribuidas_map", lambda: {})
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    monkeypatch.setattr(app, "_pv_devs_cache", {})
    monkeypatch.setattr(app, "_pv_comb_cache", {})
    monkeypatch.setattr(app, "_pv_comb_falhou", {})
    monkeypatch.setattr(app, "_plat_combiner_strings", lambda idinv: None)
    monkeypatch.setattr(app, "_spv_load_notas", lambda: {})
    monkeypatch.setitem(app.PV_INV_NOMES, pid, {i: f"T10_Inv_1.{n + 1}" for n, i in enumerate(ids)})
    monkeypatch.setitem(app.EQUIP_NAMES, nome, {f"T10_Inv_1.{n}": f"Inversor 1.{n}" for n in range(1, 11)})
    monkeypatch.setitem(app.ESPERADO_INV, nome, {f"T10_Inv_1.{n}": 2 for n in range(1, 11)})
    drill = {i["id"]: i["nome"] for i in app._pv_plant_inversores(pid, force=True)}
    assert drill[ids[1]] == "Inversor 1.2" and drill[ids[9]] == "Inversor 1.10", drill
    curva = {i["id"]: i["nome"] for i in app._spv_payload_corrente(pid, "tok", "28/09/2026", recs, True)["inversores"]}
    assert curva == drill, "a tela casa a curva pelo NOME do drill: nome diferente desenha a curva no inversor errado"


def test_a_curva_da_araputanga_tem_os_nomes_do_drill(monkeypatch):
    monkeypatch.setattr(app, "get_token", lambda: "tok")
    monkeypatch.setattr(app, "get_plants", lambda tok: [{"id": 18771898, "nome": "Araputanga"}])
    monkeypatch.setattr(app, "_http", lambda: _SemPlantDevices())
    monkeypatch.setattr(app, "_spv_load_notas", lambda: {})
    monkeypatch.setattr(app, "_trancadas", set())
    recs = [_rec(inv, f"{h:02d}:00", {"Ipv1": 9.0 * max(0, 1 - abs(h - 12) / 6), "Ipv2": 9.5 * max(0, 1 - abs(h - 12) / 6)})
            for inv in (400771, 400772) for h in range(6, 19)]
    d = app._spv_payload_corrente(18771898, "tok", "28/09/2026", recs, True)
    assert sorted(i["nome"] for i in d["inversores"]) == ["Inversor 1.1", "Inversor 1.2"], \
        "sem isto a curva saía INV-400771 e o drill desenhava a do 1º inversor em todos"
