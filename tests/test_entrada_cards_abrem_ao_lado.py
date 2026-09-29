# -*- coding: utf-8 -*-
"""Os cards da Entrada abrem numa aba ao lado (Levi, 29/09/2026: "quando clicar em algum desses cards deve abrir uma aba
ao lado, não mudar a atual").

A aba tem nome por destino, a convenção do menu do Monitoramento (target="gridco-painel"): clicar de novo no mesmo card
volta para a aba que já está aberta, em vez de empilhar abas.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

import app

ENT = (pathlib.Path(app.__file__).resolve().parents[1] / "docs" / "redesign" / "Entrada.html").read_text(encoding="utf-8")


def _aba(hrefs):
    node = shutil.which("node")
    if not node:
        pytest.skip("node não instalado")
    i = ENT.index("function _abaDe(")
    fn = ENT[i:ENT.index("\n  }\n", i) + 4]
    js = fn + "\nprocess.stdout.write(JSON.stringify(%s.map(_abaDe)));" % json.dumps(hrefs)
    p = subprocess.run([node, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_cada_destino_tem_a_sua_aba_com_o_nome_do_menu_do_monitoramento():
    assert _aba(["/painel", "/gerencial", "/relatorio", "/gemeo/", "/tempo-real", "/os/", "/os/historico",
                 "/painel/falhas", "/cos", "/painel?x=1"]) == [
        "gridco-painel", "gridco-gerencial", "gridco-relatorio", "gridco-gemeo", "gridco-tempo-real", "gridco-os",
        "gridco-os-historico", "gridco-painel-falhas", "gridco-cos", "gridco-painel"]


def test_o_card_nao_troca_a_pagina_atual():
    i = ENT.index('document.querySelectorAll(".card[data-href]")')
    bloco = ENT[i:ENT.index("});", ENT.index("auxclick", i)) + 3]
    assert "window.location.href = alvo" not in bloco and "abreAoLado(alvo)" in bloco
    assert 'a.target = _abaDe(' in bloco, "os links de dentro do card também abrem ao lado"
