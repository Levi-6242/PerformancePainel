# -*- coding: utf-8 -*-
"""O painel do sino (alertas de strings e inversores) cabe sempre na tela (12/11/2026).

O relato, pelo Início > Sugestões do Nexus (um analista da Performance, 10/11/2026): "Notificação com problemas de
visualização. Segue imagem anexa da guia de notificações e como ela aparece na minha visualização, não sendo possível ler
as informações." Com a Performance > Tempo real aberta no Nexus, o painel do sino (contador 99+) abria como uma tira
estreita, com barra de rolagem, por cima da tela.

A causa: dentro do Nexus a marca da plataforma some do cabeçalho da Entrada (`data-casca`), o cabeçalho é
`justify-content:space-between` e o grupo do sino e do relógio, sozinho, ia para a ESQUERDA; o painel é ancorado à borda
direita do sino, com 390 px, e abria para fora da tela. Medido no navegador a 1440 px: o sino em x 28 a 62 e o painel de
-328 a 62, 62 px à vista (a barra de rolagem). Dois consertos: o grupo fica à direita no modo Nexus (Entrada.html) e o
painel calcula onde abre para caber em qualquer lugar em que o sino esteja (`_gcNotifPosicao`, notif.js).
"""
import json
import pathlib
import shutil
import subprocess

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
NOTIF = (RAIZ / "plataforma" / "static" / "notif.js").read_text(encoding="utf-8")
ENTRADA = (RAIZ / "docs" / "redesign" / "Entrada.html").read_text(encoding="utf-8")
NODE = shutil.which("node")


def _posicoes(casos):
    """[(borda esquerda do sino, borda direita, largura da tela)] -> [{largura, left}], pela função da página, no node."""
    if not NODE:
        pytest.skip("node não instalado")
    i = NOTIF.index("  function _gcNotifPosicao(")
    f = NOTIF[i:NOTIF.index("\n  }\n", i) + 5]
    js = f + "\nconsole.log(JSON.stringify(" + json.dumps(casos) + ".map(function (c) { return _gcNotifPosicao(c[0], c[1], c[2]); })))"
    p = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def _bordas(sino_esq, pos):
    return sino_esq + pos["left"], sino_esq + pos["left"] + pos["largura"]


def test_o_normal_segue_igual_a_borda_direita_do_painel_com_a_do_sino():
    (p,) = _posicoes([(1144, 1178, 1425)])
    assert p["largura"] == 390 and _bordas(1144, p) == (788, 1178)


def test_com_o_sino_a_esquerda_o_painel_abre_para_dentro_da_tela():
    """O caso do relato: o sino em x 28 a 62 numa tela de 1440. Antes o painel ia de -328 a 62."""
    (p,) = _posicoes([(28, 62, 1440)])
    assert _bordas(28, p) == (28, 418)


def test_em_tela_estreita_o_painel_encolhe_e_fica_a_8_px_das_bordas():
    (p,) = _posicoes([(223, 257, 375)])
    assert p["largura"] == 359 and _bordas(223, p) == (8, 367)


def test_o_painel_nunca_sai_da_tela_esteja_o_sino_onde_estiver():
    casos = [(x, x + 34, tela) for tela in (320, 375, 500, 768, 1024, 1440, 1920) for x in range(0, tela - 33, 37)]
    for (esq, _dir, tela), p in zip(casos, _posicoes(casos)):
        ini, fim = _bordas(esq, p)
        assert 0 <= ini and fim <= tela, (esq, tela, p)
        assert p["largura"] == min(390, tela - 16)


def test_o_grupo_do_sino_fica_a_direita_do_cabecalho_mesmo_sozinho():
    """A marca some dentro do Nexus (`data-casca`); o que sobra não pode ir para a esquerda pelo space-between. A regra
    não cita o modo do Nexus: sem a chave da porta única a página não fala dele (tests/test_porta_nexus.py)."""
    assert ".topo > :last-child{margin-left:auto}" in ENTRADA and "modo-nexus" not in ENTRADA
    cab = ENTRADA.split('<header class="topo">', 1)[1].split("</header>", 1)[0]
    assert 'class="marca" href="/" data-casca' in cab
    # o grupo do sino é o ÚLTIMO filho do cabeçalho (é a ele que a regra vale)
    assert cab.strip().endswith("</div></div>") and cab.index("data-casca") < cab.index('<span id="gc-sino"></span>')


def test_o_painel_usa_a_funcao_ao_abrir_e_tem_a_barra_de_rolagem_escura():
    assert "posicionar();\n        render();" in NOTIF                      # ao abrir, antes de desenhar
    assert 'window.addEventListener("resize", function () { if (aberto) posicionar(); });' in NOTIF
    caixa = NOTIF.split('".gc-notif-caixa{', 1)[1].split('text-align:left', 1)[1].split('}"', 1)[0]
    assert "color-scheme:dark" in caixa and "max-width:calc(100vw - 16px)" in NOTIF
