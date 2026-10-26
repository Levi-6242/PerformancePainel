# -*- coding: utf-8 -*-
"""O "Investigar ativo" do Tempo real (26/10/2026). Levi: "Gostaria de poder clicar com botão direito do mouse em cima do
inversor e ter a opção 'Investigar ativo'. Vai aproveitar o pré carregamento de histórico de OS do OS Creator filtrando
esse ativo, deve mostrar o período filtrado e eu devo conseguir fazer novos filtros e pesquisas pela visão. Vai abrir uma
sub janela sobrepondo a tela dando um blur de fundo que nem quando vamos criar OS."

A plataforma faz duas coisas: o menu do botão direito na linha do inversor (Monitoramento), e o código do Fracttal do
inversor (`/api/fracttal/ativo-do-inversor`: o gravado no de-para ou o derivado do nome, SEM ir ao Fracttal). O histórico
mora no OS Creator do Nexus (`/os/historico/ativo`), que abre na mesma janela do Criar OS."""
import json
import pathlib
import shutil
import subprocess

import pytest

import app
import leitura_nexus as ln

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
MON = (RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")
ENT = (RAIZ / "docs" / "redesign" / "Entrada.html").read_text(encoding="utf-8")


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")

    def sem_fracttal(*a, **k):                 # a cota do Fracttal é da empresa: o clique não pode ir lá
        raise AssertionError("o Investigar ativo foi ao Fracttal")
    monkeypatch.setattr(app, "_frac_get", sem_fracttal)
    monkeypatch.setattr(app, "_frac_codebase_index", sem_fracttal)
    monkeypatch.setattr(app, "_frac_fractall_map", lambda: {"usina teste": "Thopen - Usina Teste - PA"})
    monkeypatch.setattr(app, "FRAC_COD_INV", {})
    monkeypatch.setattr(app, "FRAC_COD_INV_DISP", {})
    monkeypatch.setattr(app, "_frac_cb_index", {})
    monkeypatch.setattr(app, "_FRAC_INDEX_FILE", str(RAIZ / "nao-existe" / "indice.json"))
    return app.app.test_client()


def _ativo(cli, usina="Usina Teste", inv="Inversor 1.1"):
    r = cli.get("/api/fracttal/ativo-do-inversor", query_string={"usina": usina, "inv": inv})
    return r.status_code, r.get_json()


def test_o_codigo_gravado_no_de_para_vale_primeiro(cli, monkeypatch):
    monkeypatch.setattr(app, "FRAC_COD_INV", {"Usina Teste": {app._nrm("Inversor 1.1"): "THPN-CGH100-INVR2.1"}})
    monkeypatch.setattr(app, "_frac_cb_index", {"thopen - usina teste - pa": {"cb": "CGH200", "site": 1}})
    st, j = _ativo(cli)
    assert st == 200 and j == {"ok": True, "codigo": "THPN-CGH100-INVR2.1", "origem": "de-para",
                               "usina_fracttal": "Thopen - Usina Teste - PA"}


def test_sem_o_gravado_o_derivado_do_nome_pelo_indice_que_ja_existe(cli, monkeypatch):
    monkeypatch.setattr(app, "_frac_cb_index", {"thopen - usina teste - pa": {"cb": "CGH100", "site": 1}})
    st, j = _ativo(cli, inv="Inversor 1.10")
    assert st == 200 and j["codigo"] == "CGH100-INVR1.10" and j["origem"] == "derivado"


def test_o_indice_do_disco_serve_quando_a_memoria_esta_fria(cli, monkeypatch, tmp_path):
    arq = tmp_path / "indice.json"
    arq.write_text(json.dumps({"ts": 0, "idx": {"thopen - usina teste - pa": {"cb": "CGH100", "site": 1}}}),
                   encoding="utf-8")
    monkeypatch.setattr(app, "_FRAC_INDEX_FILE", str(arq))
    assert _ativo(cli)[1]["codigo"] == "CGH100-INVR1.1"          # vencido também serve: nada de varrer o parque


def test_sem_indice_nenhum_vai_sem_codigo_e_o_os_creator_acha_pelo_nome(cli):
    st, j = _ativo(cli)
    assert st == 200 and j["codigo"] == "" and j["origem"] == "" and j["usina_fracttal"] == "Thopen - Usina Teste - PA"
    st, j = _ativo(cli, usina="Usina Que Nao Tem De Para")
    assert st == 200 and j["codigo"] == "" and j["usina_fracttal"] == ""


def test_sem_a_usina_ou_o_inversor_400(cli):
    assert _ativo(cli, usina="")[0] == 400 and _ativo(cli, inv="")[0] == 400


def test_a_rota_e_leitura_para_a_ponte_e_para_o_gestor():
    """Classificada (leitura_nexus._GET): a ponte e o gestor leem; não é gravação nem abre a API PV."""
    assert ln.permitido("GET", "/api/fracttal/ativo-do-inversor", ("usina", "inv"))
    assert ln.permitido_gestor("GET", "/api/fracttal/ativo-do-inversor", ("usina", "inv"))
    assert not ln.permitido("POST", "/api/fracttal/ativo-do-inversor")


# ── a tela ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_o_botao_direito_so_na_linha_do_inversor_e_nas_fontes_do_criar_os():
    assert "const _OS_FONTES=['pv','pg','sunop','owen','semp','2capi'];" in MON
    assert "function _osBtn(){ if(!_OS_FONTES.includes(SKEY[state.source])) return '';" in MON
    i = MON.index("document.addEventListener('contextmenu',")
    f = MON[i:MON.index("\n});", i)]
    assert "closest('.gc-chip[data-inv-usina]')" in f and "_OS_FONTES.includes(SKEY[state.source])" in f
    assert "ev.preventDefault(); gcMenuAtivo(ev,chip);" in f
    # só a linha de um inversor de verdade, com a usina, ganha as marcas (o protótipo não)
    assert '${(inv.isReal&&inv.usina)?` data-inv-usina="${_he(inv.usina)}" data-inv-nome="${_he(inv.name||\'\')}"' in MON
    # o menu: sem emoji, com as cores do tema
    i = MON.index("function gcMenuAtivo(ev,chip){")
    f = MON[i:MON.index("\n}\n", i)]
    assert "Investigar ativo" in f and "var(--color-surface" in f and "ph-magnifying-glass" in f


def test_a_entrada_abre_so_a_tela_do_os_creator_que_investiga():
    assert ("d.gc==='investigar'&&typeof d.href==='string'&&d.href.indexOf('/os/historico/ativo?')===0) "
            "gcDeparaJanela(d.href,'Investigar ativo')") in ENT
    i = MON.index("function gcAbrirInvestigar(href){")
    f = MON[i:MON.index("\n}\n", i)]
    assert "parent.postMessage({gc:'investigar',href:href},location.origin)" in f and "if(EMBED)" in f
    assert "gcDeparaJanela(href,'Investigar ativo')" in f


def _rodar(embed, resposta):
    node = shutil.which("node")
    if not node:
        pytest.skip("node não instalado")
    ini = MON.index("const OS_WEB_INVESTIGAR=")
    fim = MON.index("function _dpSem(", ini)
    codigo = MON[ini:fim]
    pre = r"""
    const abertos = [], postados = [], pedidos = [];
    globalThis.document = {addEventListener(){}, getElementById(){ return null; }};
    globalThis.window = {addEventListener(){}};
    globalThis.location = {origin: 'https://app.gridco.com.br'};
    globalThis.parent = {postMessage(m, o){ postados.push([m, o]); }};
    const EMBED = %s, SKEY = {}, state = {}, _OS_FONTES = [];
    function _he(s){ return String(s); }
    function gcDeparaJanela(href, rotulo){ abertos.push([href, rotulo]); }
    globalThis.fetch = async (u, o) => { pedidos.push(u); const r = %s;
      if (r === 'rede') throw new Error('rede'); return {ok: r.ok, json: async () => r.corpo}; };
    """ % ("true" if embed else "false", json.dumps(resposta))
    fim_js = r"""
    gcInvestigarAtivo('Usina Teste', 'Inversor 1.1', 'Inversor 2.1').then(() => {
      process.stdout.write(JSON.stringify({abertos, postados, pedidos}));
    });
    """
    p = subprocess.run([node, "-e", pre + codigo + fim_js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_investigar_pede_o_codigo_e_abre_a_janela_com_ele():
    out = _rodar(False, {"ok": True, "corpo": {"ok": True, "codigo": "THPN-CGH100-INVR2.1", "origem": "de-para",
                                                "usina_fracttal": "Thopen - Usina Teste - PA"}})
    assert out["pedidos"] == ["/api/fracttal/ativo-do-inversor?usina=Usina+Teste&inv=Inversor+1.1"]
    assert out["abertos"] == [["/os/historico/ativo?codigo=THPN-CGH100-INVR2.1&usina=Thopen+-+Usina+Teste+-+PA"
                               "&nome=Inversor+1.1&rotulo=Inversor+2.1", "Investigar ativo"]]


def test_sem_o_codigo_a_janela_abre_igual_e_no_embutido_quem_abre_e_a_entrada():
    out = _rodar(True, "rede")
    assert out["abertos"] == []
    m, origem = out["postados"][0]
    assert origem == "https://app.gridco.com.br" and m["gc"] == "investigar"
    assert m["href"] == "/os/historico/ativo?codigo=&usina=Usina+Teste&nome=Inversor+1.1&rotulo=Inversor+2.1"
