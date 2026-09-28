# -*- coding: utf-8 -*-
"""Aba de falhas — filtro por inversor e por string/tracker (Levi, 28/09/2026: "quero poder filtrar qual o inversor,
qual é a string"). A conta roda no node com o código extraído da própria página, como os outros testes de tela."""
import json
import os
import re
import shutil
import subprocess

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = open(os.path.join(RAIZ, "plataforma", "templates", "falhas.html"), encoding="utf-8").read()
NODE = shutil.which("node")


def _funcao(nome):
    i = HTML.index(f"function {nome}(")
    prof, j = 0, HTML.index("{", i)
    for k in range(j, len(HTML)):
        prof += {"{": 1, "}": -1}.get(HTML[k], 0)
        if prof == 0:
            return HTML[i:k + 1]
    raise AssertionError(nome)


def _roda(estado, aba, rows):
    js = ("const CONF_STR = [], CONF_TRK = [];\n" + _funcao("filtra") + "\n"
          f"const S = Object.assign({{cli:'',fonte:'',q:'',conf:false,cron:false,aberto:false,usina:null,inv:null,str:null}}, {json.dumps(estado)});\n"
          f"S.aba = {json.dumps(aba)};\n"
          f"console.log(JSON.stringify(filtra({json.dumps(rows)}, true).map(r => r.id)));")
    return json.loads(subprocess.run([NODE, "-e", js], capture_output=True, text=True, check=True).stdout)


EPISODIOS = [{"id": 1, "usina": "MAB100", "inversor": "Inversor 3.1", "string": "ST 03", "flags": []},
             {"id": 2, "usina": "MAB100", "inversor": "Inversor 3.1", "string": "ST 04", "flags": []},
             {"id": 3, "usina": "MAB100", "inversor": "Inversor 3.10", "string": "ST 03", "flags": []}]


@pytest.mark.skipif(NODE is None, reason="sem node")
def test_filtra_por_inversor_sem_confundir_3_1_com_3_10():
    # "Inversor 3.10" contém "Inversor 3.1": o filtro é pelo nome inteiro
    assert _roda({"usina": "MAB100", "inv": "Inversor 3.1"}, "str", EPISODIOS) == [1, 2]


@pytest.mark.skipif(NODE is None, reason="sem node")
def test_filtra_por_string_no_inversor():
    assert _roda({"usina": "MAB100", "inv": "Inversor 3.1", "str": "ST 03"}, "str", EPISODIOS) == [1]


@pytest.mark.skipif(NODE is None, reason="sem node")
def test_filtro_de_string_vale_na_visao_por_inversor_e_dia():
    # na visão por inversor e dia a linha lista as strings ("ST 03, ST 04"): a do filtro tem de estar na lista
    rows = [{"id": 1, "usina": "MAB100", "inversor": "Inversor 3.9", "strings": "ST 03, ST 04", "flags": []},
            {"id": 2, "usina": "MAB100", "inversor": "Inversor 3.9", "strings": "ST 13", "flags": []}]
    assert _roda({"str": "ST 03"}, "str", rows) == [1]


@pytest.mark.skipif(NODE is None, reason="sem node")
def test_filtro_de_tracker_na_aba_de_trackers():
    rows = [{"id": 1, "usina": "MAB200", "inversor": "Inversor 1.1", "tracker": "103", "flags": []},
            {"id": 2, "usina": "MAB200", "inversor": "Inversor 1.1", "tracker": "104", "flags": []}]
    assert _roda({"str": "103"}, "trk", rows) == [1]


def test_os_seletores_de_inversor_e_string_estao_na_tela():
    assert 'id="f-inv"' in HTML and 'id="f-str"' in HTML
    assert re.search(r"\$\('f-inv'\)\.addEventListener\('change'", HTML) and re.search(r"\$\('f-str'\)\.addEventListener\('change'", HTML)
