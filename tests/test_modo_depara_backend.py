# -*- coding: utf-8 -*-
"""O Modo de-para do Tempo real, o lado da plataforma (Levi, 20/10/2026: "Boa, é isso mesmo. Implementa no tempo real e
adapta na base o de-para para ficar nesse padrão de tabela"). Quem grava a estrutura é o Nexus; aqui, o que a plataforma
LÊ e os leitores do cadastro que passam a seguir o que o Nexus grava:

- fase 0: as Falhas leem o cadastro pelo `_equipamentos_df` (a aba com a estrutura do Nexus por cima), e com a visão vazia
  o cadastro delas é o da aba, valor a valor;
- o código do Fracttal gravado no Nexus (a coluna "Código Fracttal" da visão) vence o derivado do nome no `_frac_inv_code`;
- a árvore do Fracttal pela foto (a Itajá: CABN1 com INVR1.1 a 1.4, subindo pelo pai) e pelo código (a THPN-PHS100, fora
  da foto de 22/09), e pelo próprio Fracttal em fundo;
- o Registro mestre: sem a potência real (vazia ou o "0,,643" da Rodrigues II), a contratual; sem as duas, kWp vazio;
- o resumo por inversor na linha da API PV (sem chamada nova) e o nome do Fracttal e a cabine no drill.
Nada vai à rede: o banco, o Fracttal e a API PV são dublados (o conftest recusa a fonte paga)."""
import json
import threading

import pandas as pd
import pytest

import app
import depara_fracttal as dpf
import estrutura_nexus as en
import falhas_job
import sol
from test_drill_api_pv_rapido import NOME, PID, api  # noqa: F401  (o drill da API PV dublado)
from test_estrutura_nexus import ABA, COLS, _visao, cadastro  # noqa: F401  (a aba e a visão dubladas)
from test_falhas_job import episodios, ev, monta, store
from test_porta_nexus import _sem_rede, cli, entrar, entrar_com_senha  # noqa: F401  (fixtures e passos da porta)
from test_depara_equipamentos import ligado  # noqa: F401  (o livro do de-para dublado)


def _igual(a, b):
    """Valor a valor, com NaN igual a NaN (as chaves em texto: o CAD_INV é chaveado por tupla)."""
    def txt(d):
        return json.dumps({str(k): v for k, v in d.items()}, sort_keys=True, default=str)
    return txt(a) == txt(b)


# ── fase 0: as Falhas pelo _equipamentos_df ──────────────────────────────────────────────────────────────────────────
def test_com_a_visao_vazia_o_cadastro_das_falhas_e_o_da_aba_real():
    """A aba REAL que o `import app` leu (o BD_Performance do banco): o cadastro das Falhas lido direto, como até 20/10, e
    pelo `_equipamentos_df` (o conftest desliga a estrutura do Nexus: a visão vazia, que é a do banco hoje)."""
    antes = falhas_job.cadastro_da_aba(pd.read_excel(app._bd_readable(), sheet_name="Equipamentos", header=2), app._nrm)
    agora = falhas_job.cadastro_da_aba(app._equipamentos_df(), app._nrm)
    assert len(antes[0]) > 100                                   # a aba de verdade, não uma vazia
    for nome, a, b in zip(("CAD_INV", "CAD_UFV", "CLIENTE_DE", "CAD_INV_DISP"), antes, agora):
        assert _igual(a, b), nome


def test_com_a_visao_igual_a_aba_o_cadastro_das_falhas_nao_muda_e_o_nexus_muda():
    aba = pd.DataFrame(ABA, columns=COLS)
    so_aba = falhas_job.cadastro_da_aba(aba, app._nrm)
    igual, saiu = en.sobrepor_df(aba, _visao())
    assert saiu == 7
    for a, b in zip(so_aba, falhas_job.cadastro_da_aba(igual, app._nrm)):
        assert _igual(a, b)
    mudou, _ = en.sobrepor_df(aba, _visao(**{"Inversor 2.1": 22}))
    cad_inv = falhas_job.cadastro_da_aba(mudou, app._nrm)[0]
    assert cad_inv[("brodowski", "inversor2.1")]["strings"] == 22 and so_aba[0][("brodowski", "inversor2.1")]["strings"] == 18


def test_a_montagem_das_falhas_le_o_cadastro_pelo_equipamentos_df(monkeypatch):
    """O kWp da string (kWp do inversor ÷ strings) segue o que o `_equipamentos_df` entrega: com a Inhapi 3.3 em 999 kWp e
    9 strings no Nexus, a string vale 111 kWp. Antes as Falhas liam a aba direto e o Nexus não chegava a elas."""
    original = app._equipamentos_df
    chamadas = []
    (base,) = episodios(monta(store(d01=[ev("Ipv1", "08:00", "15:00")])))

    def com_o_nexus(registrar=False):
        chamadas.append(1)
        df = original(registrar)
        sel = (df["Usina"] == "Inhapi") & (df["Equipamento"] == "Inversor 3.3")
        assert sel.any(), "a Inhapi 3.3 sumiu do cadastro de teste"
        df.loc[sel, "Potência (kWp)"] = 999.0
        df.loc[sel, "Strings Ativas"] = 9
        return df
    monkeypatch.setattr(app, "_equipamentos_df", com_o_nexus)
    (e,) = episodios(monta(store(d01=[ev("Ipv1", "08:00", "15:00")])))
    assert chamadas and e["kwp_string"] == 111.0 and base["kwp_string"] not in (0, 111.0)


# ── o código do Fracttal gravado no Nexus ────────────────────────────────────────────────────────────────────────────
def _visao_com_codigos():
    v = _visao()
    for x in v:
        if x["Equipamento"] == "UG 02":
            x["Código Fracttal"] = "BRD100-CABN2"
        if x["Equipamento"] == "Inversor 2.1":
            x["Código Fracttal"] = "brd100-invr2.1"                 # o leitor canoniza (maiúsculo, sem espaço)
    return v


def test_o_codigo_gravado_no_nexus_monta_os_mapas_e_vence_o_derivado(cadastro, monkeypatch):
    so_aba = cadastro([])
    assert so_aba["FRAC_COD_INV"] == {} and so_aba["FRAC_COD_CAB"] == {}       # a aba não tem a coluna: nada muda
    assert so_aba["EQUIP_PARENTE"]["Brodowski 2 (91)"] == {"INVERSOR01": "UG 02", "INVERSOR02": "UG 02"}
    m = cadastro(_visao_com_codigos())
    assert m["FRAC_COD_INV"] == {"Brodowski 2 (91)": {"inversor01": "BRD100-INVR2.1", "inversor2.1": "BRD100-INVR2.1"}}
    assert m["FRAC_COD_INV_DISP"] == {"brodowski": {"inversor2.1": "BRD100-INVR2.1"}}
    assert m["FRAC_COD_CAB"] == {"Brodowski": {2: "BRD100-CABN2"}}
    for k in ("ESPERADO_INV", "POWER_INV", "EQUIP_NAMES", "EQUIP_PARENTE"):
        assert m[k] == so_aba[k], k                              # o código não mexe em mais nada do cadastro
    monkeypatch.setattr(app, "_frac_codebase", lambda usina: "XXX100")   # o derivado, se alguém chegar nele
    assert app._frac_inv_code("Brodowski", "Inversor 2.1") == "BRD100-INVR2.1"           # pelo nome de exibição
    assert app._frac_inv_code("Brodowski 2 (91)", "INVERSOR01") == "BRD100-INVR2.1"      # pela chave e pelo supervisório
    assert app._frac_inv_code("Brodowski", "Inversor 1.1") == "XXX100-INVR1.1"           # sem código gravado: derivado
    assert app._frac_inv_code("Brodowski", "") is None


# ── a árvore do Fracttal ─────────────────────────────────────────────────────────────────────────────────────────────
def _m(eid, codigo, familia, pai=None, desc=None, usina_id=None, na_foto=1, foto_em="2026-09-22"):
    return {"equipamento_id": eid, "codigo": codigo, "descricao": desc, "usina_id": usina_id, "familia": familia,
            "pai_id": pai, "na_foto": na_foto, "foto_em": foto_em if na_foto else None}


def _foto_linhas():
    """A Itajá como a dimensão a tem (INVR → QGBT → SKID → CABN → USINA), a Pharmas antiga na foto (PHS200) e a de hoje
    fora dela (THPN-PHS100, só os códigos que o PCM gravou: sem pai, sem descrição)."""
    ls = [_m(1, "THOPEN-ITA100", "USINA", desc="Thopen - Itajá 1 e 2 - RN Fazenda Pricila Alves de Macedo, km 18",
             usina_id=93)]
    for n in (1, 2):
        ls += [_m(10 + n, f"ITA100-CABN{n}", "CABN", 1, f"Cabine {n} Fazenda Pricila", 93),
               _m(20 + n, f"ITA100-SKID{n}", "SKID", 10 + n, f"SKID {n}", 93),
               _m(30 + n, f"ITA100-QGBT{n}", "QGBT", 20 + n, f"QGBT {n}", 93)]
        ls += [_m(100 + 10 * n + m, f"ITA100-INVR{n}.{m}", "INVR", 30 + n, f"Inversor {n}.{m} Sungrow SG125HV", 93)
               for m in (1, 2, 3, 4)]
    # a descrição que mente (o MAB100-INVR1.8 descrito como "Inversor 1.3"): o nome sai do CÓDIGO
    ls[[x["codigo"] for x in ls].index("ITA100-INVR1.1")]["descricao"] = "Inversor 1.3 Huawei SUN2000-250KTL-H1"
    ls += [_m(200, "THPN-PHS200", "USINA", desc="Thopen - Pharmas 2 - PR Rua X", usina_id=108),
           _m(201, "THPN-PHS200-CABN1", "CABN", 200, "Cabine 1", 108),
           _m(202, "THPN-PHS200-INVR1.1", "INVR", 201, "Inversor 1.1 Sungrow", 108)]
    ls += [_m(300 + i, c, f, na_foto=0) for i, (c, f) in enumerate((
        ("THPN-PHS100-CABN2", "CABN"), ("THPN-PHS100-CABN3", "CABN"), ("THPN-PHS100-INVR2.1", "INVR"),
        ("THPN-PHS100-INVR2.2", "INVR"), ("THPN-PHS100-INVR3.1", "INVR"), ("THPN-PHS100-INVR9.1", "INVR")))]
    return [[x[c] for c in dpf.CAB_EQUIP] for x in ls]          # como o cobertura.Decisoes devolve (listas na ordem)


def test_a_arvore_da_itaja_pela_foto_sobe_pelo_pai_e_o_nome_vem_do_codigo():
    f = dpf.Foto(_foto_linhas())
    a = f.arvore(f.achar("ITA100"))                              # o código do Registro acha a raiz THOPEN-ITA100
    assert a["codigo"] == "THOPEN-ITA100" and a["nome"] == "Thopen - Itajá 1 e 2 - RN" and a["cliente"] == "Thopen"
    assert a["fora_da_foto"] is False and a["sem_cabine"] == [] and a["usina_id"] == 93
    assert [(c["codigo"], c["nome"]) for c in a["cabines"]] == [("ITA100-CABN1", "Cabine 1"), ("ITA100-CABN2", "Cabine 2")]
    c1 = a["cabines"][0]["inversores"]
    assert [(i["codigo"], i["nome"], i["cabine_por"]) for i in c1] == [
        (f"ITA100-INVR1.{m}", f"Inversor 1.{m}", "pai") for m in (1, 2, 3, 4)]
    assert c1[0]["descricao"] == "Inversor 1.3 Huawei SUN2000-250KTL-H1"     # a descrição vai junto, só para ler


def test_a_pharmas_fora_da_foto_cai_na_cabine_pelo_codigo():
    f = dpf.Foto(_foto_linhas())
    assert f.achar("PHS100") == "THPN-PHS100" and "THPN-PHS100" in f.virtuais
    a = f.arvore("THPN-PHS100")
    assert a["fora_da_foto"] is True and a["cliente"] == "Thopen"            # o THPN das raízes da foto diz Thopen
    assert {c["codigo"]: [(i["codigo"], i["cabine_por"]) for i in c["inversores"]] for c in a["cabines"]} == {
        "THPN-PHS100-CABN2": [("THPN-PHS100-INVR2.1", "codigo"), ("THPN-PHS100-INVR2.2", "codigo")],
        "THPN-PHS100-CABN3": [("THPN-PHS100-INVR3.1", "codigo")]}
    assert [i["codigo"] for i in a["sem_cabine"]] == ["THPN-PHS100-INVR9.1"]  # sem CABN9: não chuta
    assert f.arvore("THPN-PHS200")["fora_da_foto"] is False
    us = {u["codigo"]: u for u in f.usinas()}
    assert [c["nome"] for c in us["THPN-PHS100"]["cabines"]] == ["Cabine 2", "Cabine 3"]
    assert us["THOPEN-ITA100"]["usina_id"] == 93 and f.arvore("XYZ999") is None


def test_rotulos_pelo_codigo():
    assert dpf.nome_inversor("THPN-APR100-INVR1.10") == "Inversor 1.10" and dpf.nome_inversor("ITA100-CABN1") is None
    assert dpf.nome_cabine("THPN-PHS100-CABN02") == "Cabine 2" and dpf.cabine_da_ug("UG 02") == "Cabine 2"
    assert dpf.cabine_da_ug("UFV") is None and dpf.cabine_da_ug(None) is None
    assert dpf.site("2C-IPX100-INVR1.1") == "2C-IPX100" and dpf.codigo_base("THOPEN-ITA100") == "ITA100"


class _Fracttal:
    """O Fracttal dublado: a THPN-PHS100 de hoje (a raiz, as CABN2/3 debaixo dela, um QGBT em cada e os inversores)."""

    ARVORE = {"THPN-PHS100": [("THPN-PHS100-CABN2", 1, "Cabine 2"), ("THPN-PHS100-CABN3", 1, "Cabine 3"),
                              ("THPN-PHS100-ESTM1", 2, "Estação")],
              "THPN-PHS100-CABN2": [("THPN-PHS100-QGBT2", 1, "QGBT 2")],
              "THPN-PHS100-CABN3": [("THPN-PHS100-QGBT3", 1, "QGBT 3")],
              "THPN-PHS100-QGBT2": [("THPN-PHS100-INVR2.1", 2, "Inversor 2.1"), ("THPN-PHS100-INVR2.2", 2, "Inversor 2.2")],
              "THPN-PHS100-QGBT3": [("THPN-PHS100-INVR3.1", 2, "Inversor 3.1")]}

    def __init__(self, total_falso=None):
        self.pedidos, self.total_falso = [], total_falso

    def __call__(self, ep, **params):
        self.pedidos.append((ep, params.get("location_code")))
        if ep == "items/THPN-PHS100":
            return {"data": [{"code": "THPN-PHS100", "field_1": "Thopen - Pharmas 2, 3 e 4 - PR", "id_type_item": 1,
                              "description": "Thopen - Pharmas 2, 3 e 4 - PR Rua X { THPN-PHS100 }",
                              "parent_description": "// Thopen/ "}]}
        if ep.startswith("items/") and ep != "items/":
            return {}                                            # o Fracttal: "não existe"
        filhos = self.ARVORE.get(params.get("location_code"), [])
        data = [{"code": c, "location_code": params["location_code"], "id_type_item": t, "field_1": n,
                 "description": f"{n} Sungrow SG125HV {{ {c} }}" if "INVR" in c else n} for c, t, n in filhos]
        return {"data": data, "total": self.total_falso or len(data)}


def test_a_busca_no_fracttal_desce_pelos_locais_e_guarda_7_dias(tmp_path):
    fr = _Fracttal()
    agora = [1_000_000.0]
    b = dpf.BuscaFracttal(str(tmp_path / "arvores.json"), fr, espaco_s=0, relogio=lambda: agora[0], dormir=lambda s: None)
    ent = b.ler_agora("THPN-PHS100")
    # a raiz e um pedido por LOCAL (o inversor e a estação são equipamento: não se desce neles)
    assert [p for p in fr.pedidos] == [("items/THPN-PHS100", None), ("items/", "THPN-PHS100"),
                                       ("items/", "THPN-PHS100-CABN2"), ("items/", "THPN-PHS100-CABN3"),
                                       ("items/", "THPN-PHS100-QGBT2"), ("items/", "THPN-PHS100-QGBT3")]
    a = dpf.arvore_do_fracttal("THPN-PHS100", ent)
    assert a["nome"] == "Thopen - Pharmas 2, 3 e 4 - PR" and a["cliente"] == "Thopen" and a["fonte"] == "fracttal"
    assert {c["codigo"]: [(i["nome"], i["cabine_por"]) for i in c["inversores"]] for c in a["cabines"]} == {
        "THPN-PHS100-CABN2": [("Inversor 2.1", "pai"), ("Inversor 2.2", "pai")],
        "THPN-PHS100-CABN3": [("Inversor 3.1", "pai")]}
    assert a["cabines"][0]["inversores"][0]["descricao"] == "Inversor 2.1 Sungrow SG125HV"
    # o disco guarda: outra instância (o reinício) acha sem pedir; depois de 7 dias, não vale mais
    b2 = dpf.BuscaFracttal(str(tmp_path / "arvores.json"), fr, relogio=lambda: agora[0])
    assert b2.entrada("THPN-PHS100")["existe"] is True
    agora[0] += 7 * 86400 + 1
    assert b2.entrada("THPN-PHS100") is None
    # o Fracttal que ignora o filtro devolve o catálogo inteiro: falha alto, não vira árvore
    with pytest.raises(RuntimeError, match="ignorou o filtro"):
        dpf.BuscaFracttal(str(tmp_path / "x.json"), _Fracttal(total_falso=23018), espaco_s=0).ler_agora("THPN-PHS100")
    assert dpf.BuscaFracttal(str(tmp_path / "y.json"), fr, espaco_s=0).ler_agora("XYZ999")["existe"] is False


class _Livro:
    """Um `LivroEmFundo` dublado: as linhas que o teste mandar, sem banco."""

    def __init__(self, linhas, lido="2026-10-20T12:39:00Z"):
        self._l, self._lido = linhas, lido

    def linhas(self):
        return self._l, False, self._lido


@pytest.fixture
def livros(monkeypatch, tmp_path):
    """Os livros do banco e o Fracttal dublados; volta {nome: linhas} para o teste mexer."""
    d = {"foto": _foto_linhas(), "usinas": [], "clientes": []}
    monkeypatch.setattr(app, "_DPF", {"leitores": {}, "foto": (None, None), "busca": {}})
    monkeypatch.setattr(app, "_dpf_livro", lambda nome: _Livro(d[nome]))
    fr = _Fracttal()
    busca = dpf.BuscaFracttal(str(tmp_path / "arvores.json"), fr, ligado=lambda: True, espaco_s=0)
    monkeypatch.setattr(app, "_dpf_busca", lambda: busca)
    d["_busca"], d["_fracttal"] = busca, fr
    return d


def test_rota_da_arvore_pela_foto_e_pelo_fracttal_em_fundo(cli, livros):
    entrar_com_senha(cli)
    j = cli.get("/api/admin/de-para/fracttal/arvore?codigo=ITA100").get_json()
    assert j["codigo"] == "THOPEN-ITA100" and j["fonte"] == "foto" and j["pendente"] is False
    assert [len(c["inversores"]) for c in j["cabines"]] == [4, 4] and livros["_fracttal"].pedidos == []
    # fora da foto: sai a da foto JÁ, com pendente, e a leitura no Fracttal vai em fundo
    j = cli.get("/api/admin/de-para/fracttal/arvore?codigo=THPN-PHS100").get_json()
    assert j["fonte"] == "foto" and j["pendente"] is True and j["fora_da_foto"] is True
    livros["_busca"]._t.join(5)
    j = cli.get("/api/admin/de-para/fracttal/arvore?codigo=THPN-PHS100").get_json()
    assert j["fonte"] == "fracttal" and j["pendente"] is False and j["nome"] == "Thopen - Pharmas 2, 3 e 4 - PR"
    assert [i["codigo"] for c in j["cabines"] for i in c["inversores"]] == [
        "THPN-PHS100-INVR2.1", "THPN-PHS100-INVR2.2", "THPN-PHS100-INVR3.1"]
    # a lista de usinas leva a lida no Fracttal por cima da foto
    us = {u["codigo"]: u for u in cli.get("/api/admin/de-para/fracttal/usinas").get_json()["usinas"]}
    assert us["THPN-PHS100"]["fonte"] == "fracttal" and us["THPN-PHS100"]["nome"] == "Thopen - Pharmas 2, 3 e 4 - PR"
    assert us["THOPEN-ITA100"]["cabines"] == [{"codigo": "ITA100-CABN1", "nome": "Cabine 1"},
                                              {"codigo": "ITA100-CABN2", "nome": "Cabine 2"}]
    assert cli.get("/api/admin/de-para/fracttal/arvore").status_code == 400


def test_rota_da_arvore_sem_credencial_do_fracttal_diz_o_motivo(cli, livros, monkeypatch):
    entrar_com_senha(cli)
    livros["_busca"].ligado = lambda: False
    j = cli.get("/api/admin/de-para/fracttal/arvore?codigo=THPN-PHS100").get_json()
    assert j["pendente"] is False and "credencial do Fracttal" in j["aviso"] and len(j["cabines"]) == 2
    r = cli.get("/api/admin/de-para/fracttal/arvore?codigo=XYZ999")
    assert r.status_code == 404 and "credencial" in r.get_json()["error"]
    assert livros["_fracttal"].pedidos == []


# ── o Registro mestre ────────────────────────────────────────────────────────────────────────────────────────────────
def test_kwp_do_registro_real_senao_contratual_senao_vazio():
    assert dpf.kwp_do_registro(2.596, 2.6) == (2596.0, "real")              # Itajá
    assert dpf.kwp_do_registro("0,,643", 2.57) == (2570.0, "contratual")    # Rodrigues II: a real digitada torta
    assert dpf.kwp_do_registro(None, 1) == (1000.0, "contratual")
    assert dpf.kwp_do_registro("", "0,99") == (990.0, "contratual")
    assert dpf.kwp_do_registro("2,596", None) == (2596.0, "real")
    assert dpf.kwp_do_registro(None, None) == (None, None)
    assert dpf.kwp_do_registro(0, "") == (None, None)                      # zero não é potência


def test_rota_do_registro(cli, livros):
    livros["usinas"] += [
        [93, "ITA100", "Itajá 1 e 2", "OPERAÇÃO", 1, 2.596, 2.6, "não"],
        [118, "THPN-RDR200", "Rodrigues II", "OPERAÇÃO", 1, "0,,643", 2.57, "não"],
        [200, None, "Sem Potência", "A MOBILIZAR", 9, None, None, "não"],
        [201, "XX100", "Excluída", "OPERAÇÃO", 1, 1.0, 1.0, "sim"]]
    livros["clientes"] += [[1, "Thopen", "não"]]
    entrar_com_senha(cli)
    us = {u["usina_id"]: u for u in cli.get("/api/admin/de-para/registro").get_json()["usinas"]}
    assert us[93] == {"usina_id": 93, "codigo": "ITA100", "nome": "Itajá 1 e 2", "status": "OPERAÇÃO", "kwp": 2596.0,
                      "kwp_de": "real", "cliente": "Thopen"}
    assert (us[118]["kwp"], us[118]["kwp_de"]) == (2570.0, "contratual")
    assert (us[200]["kwp"], us[200]["kwp_de"], us[200]["cliente"]) == (None, None, None)
    assert 201 not in us


def test_as_rotas_novas_sao_so_de_administrador(cli, livros):
    entrar(cli, "analista@exemplo.com", admin=False)
    for u in ("/api/admin/de-para/fracttal/usinas", "/api/admin/de-para/fracttal/arvore?codigo=ITA100",
              "/api/admin/de-para/registro"):
        assert cli.get(u).status_code == 403, u
    entrar(cli, "admin@exemplo.com", admin=True)
    for u in ("/api/admin/de-para/fracttal/usinas", "/api/admin/de-para/fracttal/arvore?codigo=ITA100",
              "/api/admin/de-para/registro"):
        assert cli.get(u).status_code == 200, u


def test_o_leitor_em_fundo_nao_prende_o_pedido_com_copia_e_espera_so_a_primeira(tmp_path):
    """Com a cópia (memória ou disco), o pedido sai na hora e a leitura nova vai numa thread; sem cópia nenhuma, espera a
    1ª leitura um pouco; com o banco fora e sem cópia, não prende os pedidos seguintes."""
    import cobertura

    solta = threading.Event()

    class Lento(cobertura.Decisoes):
        def _ler_banco(self):
            solta.wait(5)
            return [["x"]]
    caminho = str(tmp_path / "c.json")
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump({"lido_em": "antes", "linhas": [["disco"]]}, f)
    lf = dpf.LivroEmFundo(Lento("http://127.0.0.1:9", "", caminho, ttl=60, cab=["a"]), espera_s=0.2)
    linhas, carregando, lido = lf.linhas()
    assert linhas == [["disco"]] and carregando is True and lido == "antes"    # a cópia do disco, sem esperar o banco
    solta.set()
    lf._t.join(5)
    assert lf.linhas()[0] == [["x"]]

    class Fora(cobertura.Decisoes):
        def _ler_banco(self):
            raise ConnectionError("banco fora")
    lf2 = dpf.LivroEmFundo(Fora("http://127.0.0.1:9", "", str(tmp_path / "nada.json"), ttl=60, cab=["a"]), espera_s=1)
    assert lf2.linhas()[0] is None
    t = lf2._t
    assert lf2.linhas()[0] is None and lf2._t is t                # a 2ª não dispara outra leitura nem espera


# ── o resumo por inversor na linha e o drill ─────────────────────────────────────────────────────────────────────────
def _rec(inv_id, pac, correntes, ts="2026-10-20 10:20:00"):
    cj = {"Pac": pac, "Eday": 100.0, "Temp": 30.0, **{f"Ipv{i + 1}": c for i, c in enumerate(correntes)}}
    return {"idefinversor": inv_id, "tsleitura_new": ts, "conteudojson": json.dumps(cj)}


def test_a_linha_da_api_pv_leva_o_resumo_por_inversor_sem_chamada_nova(monkeypatch, freeze_now, tmp_path):
    freeze_now("2026-10-20 10:25:00")
    usina, pid = "Itaja Teste", 18758999
    monkeypatch.setitem(app.ESPERADO_INV, usina, {"INVERSOR01": 19, "INVERSOR02": 19, "INVERSOR03": 19})
    monkeypatch.setitem(app.EQUIP_NAMES, usina, {"INVERSOR01": "Inversor 1.1", "INVERSOR02": "Inversor 1.2",
                                                 "INVERSOR03": "Inversor 1.3"})
    monkeypatch.setitem(app.ESPERADO, usina, {"inv_esp": 3, "str_esp": 57})
    monkeypatch.setattr(app, "PV_OEM_PLANTS", set())
    monkeypatch.setattr(app, "_pv_devs_cache", {pid: {"ts": 0, "devs": [
        {"device_id": i, "device_name": f"INVERSOR0{n}"} for n, i in ((1, 11), (2, 12), (3, 13))]}})
    monkeypatch.setattr(app, "_pv_inv_da_tela", lambda p: {})
    monkeypatch.setattr(app, "_FALHAS_PV_DEV", str(tmp_path / "falhas_pv_dev.json"))
    monkeypatch.setattr(app, "_pv_plant_devices", lambda p: [])
    monkeypatch.setattr(app, "_pv_dev_names", lambda p, token: {})
    monkeypatch.setattr(app, "_pv_token_for", lambda p: "")
    monkeypatch.setattr(app, "_os_atribuidas_map", lambda: {})
    monkeypatch.setattr(app, "_os_fracttal_inv_abertas", lambda: {})
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    monkeypatch.setattr(app, "_combiner_strings", lambda p, i: None)         # o 13 gera com 1 corrente só: sem visão
    monkeypatch.setattr(app, "_pv_ger_relativa", lambda *a, **k: {})

    def _sem_api(*a, **k):
        raise AssertionError("o resumo não pode chamar a API PV")
    monkeypatch.setattr(app, "_http", _sem_api)
    recs = [_rec(11, 60.0, [5.4] * 19), _rec(12, 60.0, [5.4] * 17 + [0.0, 0.0]), _rec(13, 60.0, [5.4])]
    r = app.build_summary({"id": pid, "nome": usina}, recs)
    assert r["inv_resumo"] == [
        {"id": 11, "nome_api": "INVERSOR01", "nome": "Inversor 1.1", "ativas": 19, "total": 19, "esp": 19,
         "sem_visao": False},
        {"id": 12, "nome_api": "INVERSOR02", "nome": "Inversor 1.2", "ativas": 17, "total": 19, "esp": 19,
         "sem_visao": False},
        {"id": 13, "nome_api": "INVERSOR03", "nome": "Inversor 1.3", "ativas": None, "total": 0, "esp": 19,
         "sem_visao": True}]
    assert r["inv_ids_hoje"] == [11, 12, 13]                     # o que já existia segue igual


def test_o_drill_mostra_o_nome_do_fracttal_e_a_cabine_do_cadastro(api, monkeypatch):
    monkeypatch.setitem(app.FRAC_COD_INV, NOME, {app._nrm("INVERSOR 01"): "THPN-PHS100-INVR2.1"})
    monkeypatch.setitem(app.EQUIP_PARENTE, NOME, {"INVERSOR 01": "UG 02", "INVERSOR 02": "UFV"})
    monkeypatch.setitem(app.FRAC_COD_CAB, NOME, {2: "THPN-PHS100-CABN2"})          # a UG 02 com a CABN gravada
    invs = {i["nome_api"]: i for i in app._pv_plant_inversores(PID, force=True)}
    um, dois = invs["INVERSOR 01"], invs["INVERSOR 02"]
    assert um["nome_fracttal"] == "Inversor 2.1" and um["cabine"] == "Cabine 2"
    assert um["nome"] == "Inversor 1.1"                          # a chave dos tickets, das OS e do BD não muda
    assert "nome_fracttal" not in dois and "cabine" not in dois   # "UFV" não é cabine; sem código, sem rótulo


def test_o_drill_so_chama_de_cabine_a_ug_com_a_cabn_gravada(monkeypatch):
    """P-h (20/10): a etiqueta de cabine vinha do "Equipamento Parente" da aba para a frota INTEIRA, sem ninguém usar o modo.
    Na Altair a aba tem UG 01 a UG 05, que são os SKIDs debaixo de uma CABN1 só no Fracttal: o drill do "Inversor 1.8"
    passava a dizer "Cabine 3". Só a UG com o código da CABN gravado (a visão do Nexus, FRAC_COD_CAB) vira "Cabine N"; sem
    ele, o drill fica como era (a cabine do nome). A UG mora na chave da UFV (pelo nome de exibição da usina)."""
    monkeypatch.setitem(app.EQUIP_PARENTE, "Altair 1", {"INVERSOR08": "UG 03"})
    monkeypatch.setitem(app.USINA_GRUPO, "Altair 1", "Altair")
    assert app._dp_rotulos_fracttal("Altair 1", "INVERSOR08", "Inversor 1.8") == {}             # o SKID da aba: nada
    monkeypatch.setitem(app.FRAC_COD_CAB, "Altair", {3: "ALT100-CABN3"})                       # na chave da UFV
    assert app._dp_rotulos_fracttal("Altair 1", "INVERSOR08", "Inversor 1.8") == {"cabine": "Cabine 3"}


# ── a 1ª revisão (20/10): quem grava, a ponte que relê a visão, o cadastro para a tela ────────────────────────────────
def test_o_eu_diz_quem_grava_e_o_gestor_admin_do_nexus_so_le(cli):
    """P-a: o gestor que é admin do Nexus ABRE a administração (lê o de-para) e não grava: no Modo de-para, o Nexus gravava
    a estrutura (ele confere só o admin) e a ponte levava 403 do `permitido_gestor`, gravação pela metade. O `grava_admin`
    é o que o botão do Tempo real e o Salvar pedem."""
    entrar_com_senha(cli)
    assert cli.get("/api/eu").get_json() == {"abre_admin": True, "grava_admin": True}
    entrar(cli, "admin@exemplo.com", admin=True)
    assert cli.get("/api/eu").get_json() == {"abre_admin": True, "grava_admin": True}
    entrar(cli, "gestor.admin@exemplo.com", admin=True)
    assert cli.get("/api/eu").get_json() == {"abre_admin": True, "grava_admin": False}
    assert cli.post("/api/admin/de-para/decidir", json={"fonte": "pv", "id": "1", "usina_supervisorio": ""}).status_code == 403
    entrar(cli, "analista@exemplo.com", admin=False)
    assert cli.get("/api/eu").get_json() == {"abre_admin": False, "grava_admin": False}


def test_a_ponte_para_a_chave_que_so_o_nexus_tem_rele_a_visao_antes_de_recusar(cli, ligado, monkeypatch):
    """P-b e D-g: a ponte vai segundos depois do Nexus; a chave que só existe no Nexus entra no ESPERADO quando a plataforma
    relê a visão (60 s + a recarga). Antes de recusar, o decidir relê AGORA (o leitor com `forcar` e a recarga do cadastro).
    E a chave na grafia do Nexus ("Assis Chateaubriand Skid 1 (79)", espaço único) grava a do cadastro (a da aba e da API,
    espaço duplo), que é a que a fonte procura, sem reler nada."""
    entrar_com_senha(cli)
    monkeypatch.setattr(app, "ESPERADO", {"Assis Chateaubriand  Skid 1 (79)": {"inv_esp": 4, "str_esp": 84}})
    monkeypatch.setattr(app, "ESTRUTURA_NEXUS", True)
    forcou = []

    class Leitor:
        def linhas(self, forcar=False):
            forcou.append(forcar)
            return []
    monkeypatch.setattr(app, "_en_leitor", lambda: Leitor())
    monkeypatch.setattr(app, "maybe_reload_equipamentos",
                        lambda: app.ESPERADO.setdefault("Itaja 1 (551)", {"inv_esp": 4, "str_esp": 76}))
    decide = lambda alvo: cli.post("/api/admin/de-para/decidir", json={"fonte": "pv", "id": "18749574", "usina_supervisorio": alvo})  # noqa: E731
    r = decide("Itaja 1 (551)")
    assert r.status_code == 200 and forcou == [True]
    assert ligado.linhas[-1][5] == "Itaja 1 (551)"
    forcou.clear()
    r = decide("Assis Chateaubriand Skid 1 (79)")
    assert r.status_code == 200 and forcou == []
    assert ligado.linhas[-1][5] == "Assis Chateaubriand  Skid 1 (79)"
    r = decide("Não Existe")                                       # nem a visão relida tem: 400, como antes
    assert r.status_code == 400 and "não está no cadastro" in r.get_json()["error"] and forcou == [True]


def test_o_cadastro_da_plataforma_para_o_modo(cli, monkeypatch):
    """P-j, P-m e P-i: as chaves do cadastro desta plataforma com os inversores de cada uma (o nome, as strings, o kWp de antes
    e a UG), do que já está na memória. A Coração 2 (112) da aba, que o Nexus não tem; o apelido do nome da API ("Sete
    Lagoa") não é chave do cadastro e fica de fora. Só admin."""
    # o INVERSOR03 com o kWp NaN (célula vazia da aba): no servidor, em 21/10/2026, 37 "kwp": NaN deixavam o JSON inválido
    monkeypatch.setattr(app, "ESPERADO_INV", {"Coração 2 (112)": {"INVERSOR01": 20, "INVERSOR02": 20, "INVERSOR03": float("nan")},
                                              "Sete Lagoa": {"INV1": 10}})
    monkeypatch.setattr(app, "EQUIP_NAMES", {"Coração 2 (112)": {"INVERSOR01": "Inversor 1.1", "INVERSOR02": "Inversor 1.2",
                                                                 "INVERSOR03": "Inversor 1.3"},
                                              "Sete Lagoa": {"INV1": "Inversor 1.1"}})
    monkeypatch.setattr(app, "POWER_INV", {"Coração 2 (112)": {app._nrm("INVERSOR01"): 250.0, app._nrm("Inversor 1.2"): 250.0,
                                                               app._nrm("INVERSOR03"): float("nan")}})
    monkeypatch.setattr(app, "EQUIP_PARENTE", {"Coração 2 (112)": {"INVERSOR01": "UG 01"}})
    monkeypatch.setattr(app, "USINA_GRUPO", {"Coração 2 (112)": "Coração 2"})
    monkeypatch.setattr(app, "PV_NOME_API_ALIAS", {"Sete Lagoa": "Sete Lagoas"})
    monkeypatch.setattr(app, "_dp_apelidos_da_tela", lambda: {})
    entrar(cli, "analista@exemplo.com", admin=False)
    assert cli.get("/api/admin/de-para/cadastro").status_code == 403
    entrar(cli, "admin@exemplo.com", admin=True)
    r = cli.get("/api/admin/de-para/cadastro")
    assert "NaN" not in r.get_data(as_text=True)
    j = json.loads(r.get_data(as_text=True))                 # o parse estrito, como o do navegador
    assert j["chaves"] == [{"chave": "Coração 2 (112)", "exibicao": "Coração 2", "inversores": [
        {"esup": "INVERSOR01", "nome": "Inversor 1.1", "esp": 20, "kwp": 250.0, "ug": "UG 01"},
        {"esup": "INVERSOR02", "nome": "Inversor 1.2", "esp": 20, "kwp": 250.0, "ug": None},
        {"esup": "INVERSOR03", "nome": "Inversor 1.3", "esp": None, "kwp": None, "ug": None}]}]
