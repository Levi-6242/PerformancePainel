# tests/test_prefixo_subcaminho.py
# -*- coding: utf-8 -*-
"""A plataforma debaixo de um caminho (X-Forwarded-Prefix): a ponte do Nexus (04/10/2026) e o sub-caminho da T.I.

Até aqui o calço (`_SHIM_PREFIXO`) corrigia fetch, XHR e os <a> presentes na carga. Ficavam de fora o
<script src="/static/notif.js">, o logo e os links escritos no HTML (a raiz do domínio, debaixo do Nexus, é o
Nexus), o link que o JavaScript cria depois da carga e o window.open."""
import json
import pathlib
import shutil
import subprocess

import pytest

import app

P = "/t/performance/plataforma"


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    return app.app.test_client()


def test_atributos_absolutos_ganham_o_prefixo(cli):
    html = cli.get("/tempo-real", headers={"X-Forwarded-Prefix": P}).get_data(as_text=True)
    assert f'src="{P}/static/notif.js"' in html
    assert 'src="/static/' not in html and 'href="/tempo-real"' not in html
    assert f'{P}{P}/' not in html                           # nada em dobro


def test_sem_prefixo_o_html_sai_como_hoje(cli):
    html = cli.get("/tempo-real").get_data(as_text=True)
    # "window.__pfx=fix" é a atribuição DO CALÇO; a própria Entrada cita `window.__pfx` ao ler a função (Task 5), então
    # o nome sozinho não prova mais que o calço ficou de fora.
    assert 'src="/static/notif.js"' in html and "window.__pfx=fix" not in html


def test_calco_corrige_link_no_clique_e_window_open(cli):
    html = cli.get("/tempo-real", headers={"X-Forwarded-Prefix": P}).get_data(as_text=True)
    assert "addEventListener('click'" in html and "window.open=function" in html


def _passa_pelo_filtro(html, prefixo=P):
    """Roda só o `_injeta_prefixo` sobre um HTML escrito à mão, como se a rota o tivesse devolvido."""
    from flask import Response
    with app.app.test_request_context("/", base_url="http://localhost" + prefixo if prefixo else "http://localhost"):
        return app._injeta_prefixo(Response(html, mimetype="text/html")).get_data(as_text=True)


def test_nao_dobra_o_que_ja_tem_prefixo_nem_toca_em_protocolo_relativo():
    html = _passa_pelo_filtro(
        '<head></head><body>'
        f'<a href="{P}/tempo-real">a</a><a href="{P}">b</a>'
        '<script src="//cdn.exemplo.com/x.js"></script><a href="https://exemplo.com/y">c</a>'
        '<a href="relativo/z">d</a><a href="#topo">e</a><a data-url="/nao-e-atributo-de-link">f</a>'
        "</body>")
    assert f'href="{P}/tempo-real"' in html and f'href="{P}"' in html           # já estavam certos: ficam como estão
    assert f'{P}{P}' not in html
    assert 'src="//cdn.exemplo.com/x.js"' in html and f'{P}//cdn' not in html
    assert 'href="https://exemplo.com/y"' in html and 'href="relativo/z"' in html and 'href="#topo"' in html
    assert 'data-url="/nao-e-atributo-de-link"' in html                       # só src, href, action e data-href


def test_data_href_do_card_da_entrada_tambem_ganha_o_prefixo():
    """O card abre o destino numa aba com nome tirado do `data-href` (`_abaDe`): sem o prefixo ali, o card e o link de
    dentro dele (que já vem prefixado) abririam em abas de nomes diferentes."""
    html = _passa_pelo_filtro('<head></head><article class="card" data-href="/os/"><a href="/os/">Criar</a></article>')
    assert f'data-href="{P}/os/"' in html and f'href="{P}/os/"' in html and f'{P}{P}' not in html


def test_aspas_simples_action_e_raiz_tambem_ganham_o_prefixo():
    html = _passa_pelo_filtro(
        "<head></head><body><img src='/static/logo.png'><form action=\"/login\"></form>"
        '<a href="/">inicio</a><a\n href="/ronda?x=1">r</a></body>')
    assert f"src='{P}/static/logo.png'" in html
    assert f'action="{P}/login"' in html and f'href="{P}/"' in html and f'href="{P}/ronda?x=1"' in html
    assert f'{P}{P}' not in html


def test_prefixo_com_caractere_de_regex_nao_quebra_a_substituicao():
    html = _passa_pelo_filtro('<head></head><a href="/x">x</a><a href="/a.b/y">y</a>', prefixo="/a.b")
    assert 'href="/a.b/x"' in html and 'href="/a.b/y"' in html and "/a.b/a.b" not in html


ENTRADA = (pathlib.Path(app.__file__).resolve().parents[1] / "docs" / "redesign" / "Entrada.html").read_text(
    encoding="utf-8")


def _roda_js(expr):
    node = shutil.which("node")
    if not node:
        pytest.skip("node não instalado")
    i = ENTRADA.index("function _partesDoCaminho(")
    fim = "/* fim _partesDoCaminho */"
    js = ENTRADA[i:ENTRADA.index(fim, i) + len(fim)] + "\nprocess.stdout.write(JSON.stringify(" + expr + "));"
    r = subprocess.run([node, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_entrada_le_o_nivel_sem_o_prefixo():
    assert _roda_js(f"_partesDoCaminho('{P}/tempo-real/athon/', '{P}')") == ["tempo-real", "athon"]
    assert _roda_js("_partesDoCaminho('/tempo-real', '')") == ["tempo-real"]
    assert _roda_js(f"_partesDoCaminho('/tempo-real', '{P}')") == ["tempo-real"]     # sem o prefixo no caminho


def test_moldura_do_monitoramento_passa_pelo_calco():
    assert ENTRADA.count('fr.src = "/monitor?') == 0
    assert ENTRADA.count('_pfxUrl("/monitor?') == 2
