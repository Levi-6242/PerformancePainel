# -*- coding: utf-8 -*-
"""Strings e trackers — quem é "parado agora" na aba de trackers (Levi, 20/10/2026: "Se a usina inteira ficou sem dado
então sai da conta, se for só aquele tracker é bem possível que esteja parado então segue").

Até 20/10 a tela tirava o tracker que perdeu a comunicação sozinho (`sem_com_desde`) e deixava o da usina calada. No pacote
de 20/10 11:03 a regra nova tira 63 (Mandaguaçu 40, Salto Pirapora 3 16...) e põe 36 (Barretos 9, Aparecida 3 8...). A
conta roda no node com o código extraído da própria página, como test_falhas_tela_filtros."""
import json
import os
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


def _parados(rows):
    js = (_funcao("usinaSemDado") + "\n" + _funcao("trkAberto") + "\n"
          f"console.log(JSON.stringify({json.dumps(rows)}.filter(trkAberto).map(r => r.id)));")
    return json.loads(subprocess.run([NODE, "-e", js], capture_output=True, text=True, check=True).stdout)


@pytest.mark.skipif(NODE is None, reason="sem node")
def test_so_o_tracker_sem_comunicacao_segue_parado_e_a_usina_calada_sai():
    rows = [
        {"id": 1, "fim": None, "flags": []},                                                      # parado, comunicando
        {"id": 2, "fim": None, "sem_com_desde": "2026-10-11", "flags": ["sem comunicação do tracker desde 11/10"]},
        {"id": 3, "fim": None, "flags": ["sem dado da usina desde 15/10"]},                      # a usina inteira calou
        {"id": 4, "fim": None, "flags": ["leitura incompleta da usina desde 12/10"]},            # leitura parcial: segue
        {"id": 5, "fim": "2026-10-05 09:10", "flags": []},                                       # voltou
        {"id": 6, "fim": "2026-10-05", "flags": ["voltou em 05/10 (hora não registrada)"]},      # voltou, sem a hora
    ]
    assert _parados(rows) == [1, 2, 4]


def test_a_coluna_voltou_diz_qual_dos_dois_casos():
    assert "usina sem dado desde" in HTML and "Só este tracker perdeu a comunicação" in HTML
