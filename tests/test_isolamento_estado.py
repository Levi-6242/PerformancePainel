# -*- coding: utf-8 -*-
"""Nenhum teste grava os arquivos de estado de verdade (01/10/2026).

Às 09:51 de 01/10 um teste da cota da SunOp chamou o `_sunop_eventos_calc` de verdade, que salva o acervo de eventos:
o `plataforma/trk_eventos.json` do PC (11,7 MB, 93 dias de eventos de tracker de todas as fontes) virou 388 bytes com
as duas usinas falsas do teste, até o worker regravar da memória 4 min depois. O conftest isola cada arquivo que a
plataforma grava; este teste confere a lista contra o app.py, para um arquivo de estado novo não ficar de fora."""
import json
import os
import re
from pathlib import Path

import app
import conftest

APP = Path(app.__file__).read_text(encoding="utf-8")


def test_todo_arquivo_de_estado_do_app_esta_isolado_nos_testes():
    no_app = set(re.findall(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*_p_(?:dado|cache)\(", APP, re.M))
    assert no_app, "o padrão dos caminhos mudou: atualize este teste"
    faltam = sorted(no_app - set(conftest.ARQUIVOS_DE_ESTADO))
    assert not faltam, f"arquivo de estado novo sem isolamento no conftest.ARQUIVOS_DE_ESTADO: {faltam}"


def test_o_acervo_de_eventos_do_teste_nao_e_o_da_plataforma(tmp_path):
    real = os.path.join(os.path.dirname(app.__file__), "trk_eventos.json")
    assert os.path.normcase(app._TRK_EV_PATH) != os.path.normcase(real)
    antes = os.path.getmtime(real) if os.path.exists(real) else None
    app._trk_ev_save()                                  # o que o _sunop_eventos_calc faz no fim
    assert json.loads(Path(app._TRK_EV_PATH).read_text(encoding="utf-8")) is not None
    assert (os.path.getmtime(real) if os.path.exists(real) else None) == antes, "o teste gravou o acervo do PC"


def test_o_contador_da_sunop_nao_despeja_no_arquivo_do_pc():
    assert app._SUNOP_USO_FLUSH >= 10 ** 9
