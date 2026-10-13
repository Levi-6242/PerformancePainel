# -*- coding: utf-8 -*-
"""O Painel NOC e a Visão gerencial sem o botão de tema dentro do Nexus (Levi, 13/10/2026: "tira o botão de tema das telas
da plataforma também", depois de o 2º cabeçalho sair de dentro do Nexus). No modo Nexus o botão de cada tela some
(`data-casca`) e vale o tema do Nexus, como na aba de Falhas: o cookie `nexus_tema` (ou o localStorage `nexus.tema`) antes
da 1ª pintura, e o botão do Nexus troca a tela na hora pelo evento `storage`. Fora do Nexus, cada tela segue com o botão e
a escolha dela (`painelDark`, `ger.tema`)."""
import json
import pathlib
import shutil
import subprocess

import pytest

TPL = pathlib.Path(__file__).resolve().parents[1] / "plataforma" / "templates"
NOC = (TPL / "painel_portfolio.html").read_text(encoding="utf-8")
GER = (TPL / "gerencial.html").read_text(encoding="utf-8")


def _trecho(html: str, inicio: str) -> str:
    i = html.index(inicio)
    return html[i:html.index("})();", i) + len("})();")]


def _node(js: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node não instalado")
    p = subprocess.run([node, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def _dom(nexus: bool, cookie: str, local: dict) -> str:
    return ("const attrs={'data-theme':'dark'}; const ouvintes={}; const botao={textContent:'Tema claro'};"
            "global.document={cookie:%s, getElementById:()=>botao, documentElement:{"
            "setAttribute:(k,v)=>{attrs[k]=v;}, removeAttribute:k=>{delete attrs[k];}, getAttribute:k=>attrs[k]}};"
            "global.localStorage={getItem:k=>(%s)[k]||null};"
            "global.window={gcModoNexus:%s, addEventListener:(t,f)=>{ouvintes[t]=f;}};"
            % (json.dumps(cookie), json.dumps(local), "true" if nexus else "undefined"))


# ── os botões somem no modo Nexus ──────────────────────────────────────────────────────────────────────────────────────
def test_os_dois_botoes_de_tema_sao_da_casca_e_o_teste_do_nexus_e_o_calco():
    # "no Nexus" = o window.gcModoNexus do calço (app.py), nunca o nome da classe: fora do Nexus a página não leva
    # nenhuma menção a ela (tests/test_porta_nexus.py procura o nome em toda resposta sem a chave)
    assert "modo-" + "nexus" not in NOC and "modo-" + "nexus" not in GER
    assert '<button class="darkbtn" id="darkBtn" onclick="toggleDark()" data-casca>' in NOC
    assert 'id="tema" onclick="alternaTema()"' in GER and 'title="alternar tema claro/escuro (fica salvo neste navegador)" data-casca>' in GER


# ── Painel NOC: o body.dark segue o Nexus ─────────────────────────────────────────────────────────────────────────────
def _noc(nexus, cookie="", local=None, evento=None, hist=False):
    js = (_dom(nexus, cookie, local or {}) +
          "const feito=[]; let builtHist=%s; function applyDark(on){feito.push(['dark',on]);}"
          "function buildHist(r){feito.push(['hist',r]);}" % ("true" if hist else "false") +
          _trecho(NOC, "(function(){\n  if(window.gcModoNexus!==true)") +
          (";ouvintes.storage(%s);" % json.dumps(evento) if evento else "") +
          "process.stdout.write(JSON.stringify({feito, ouve: Object.keys(ouvintes)}));")
    return _node(js)


def test_noc_fora_do_nexus_segue_com_a_escolha_dele():
    assert _noc(False) == {"feito": [["dark", True]], "ouve": []}                      # escuro é o padrão
    assert _noc(False, local={"painelDark": "0"})["feito"] == [["dark", False]]
    assert _noc(False, cookie="nexus_tema=claro")["feito"] == [["dark", True]]          # fora do Nexus o Nexus não manda


def test_noc_no_nexus_segue_o_tema_do_nexus_e_troca_na_hora():
    assert _noc(True, cookie="a=1; nexus_tema=claro")["feito"] == [["dark", False]]
    assert _noc(True, cookie="nexus_tema=escuro", local={"painelDark": "0"})["feito"] == [["dark", True]]
    assert _noc(True, local={"nexus.tema": "claro"})["feito"] == [["dark", False]]      # sem o cookie, o localStorage
    assert _noc(True)["feito"] == [["dark", True]]                                       # nada: o escuro do Nexus
    # o botão do Nexus troca: a tela e, com o histórico montado, os gráficos dele (as cores do tema)
    r = _noc(True, cookie="nexus_tema=escuro", evento={"key": "nexus.tema", "newValue": "claro"}, hist=True)
    assert r["feito"] == [["dark", True], ["dark", False], ["hist", True]]
    assert _noc(True, evento={"key": "outra", "newValue": "claro"})["feito"] == [["dark", True]]


# ── Visão gerencial: o data-theme segue o Nexus ──────────────────────────────────────────────────────────────────────
def _ger(nexus, cookie="", local=None, evento=None):
    js = (_dom(nexus, cookie, local or {}) + _trecho(GER, "(function(){\n  var raiz=document.documentElement;") +
          (";ouvintes.storage(%s);" % json.dumps(evento) if evento else "") +
          "process.stdout.write(JSON.stringify({tema: attrs['data-theme'] || 'claro', botao: botao.textContent}));")
    return _node(js)


def test_gerencial_fora_do_nexus_segue_com_a_escolha_dela():
    assert _ger(False) == {"tema": "dark", "botao": "Tema claro"}
    assert _ger(False, local={"ger.tema": "claro"}) == {"tema": "claro", "botao": "Tema escuro"}
    assert _ger(False, cookie="nexus_tema=claro")["tema"] == "dark"


def test_gerencial_no_nexus_segue_o_tema_do_nexus_e_troca_na_hora():
    assert _ger(True, cookie="nexus_tema=claro")["tema"] == "claro"
    assert _ger(True, cookie="nexus_tema=escuro", local={"ger.tema": "claro"})["tema"] == "dark"
    assert _ger(True, local={"nexus.tema": "claro"})["tema"] == "claro"
    assert _ger(True)["tema"] == "dark"
    assert _ger(True, cookie="nexus_tema=escuro", evento={"key": "nexus.tema", "newValue": "claro"})["tema"] == "claro"
    assert _ger(True, cookie="nexus_tema=claro", evento={"key": "nexus.tema", "newValue": "escuro"})["tema"] == "dark"
    assert _ger(True, cookie="nexus_tema=claro", evento={"key": "outra", "newValue": "escuro"})["tema"] == "claro"
