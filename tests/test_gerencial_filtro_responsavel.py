# -*- coding: utf-8 -*-
"""O filtro de responsável da Visão gerencial (Levi, 12/10/2026: "Quero um filtro de responsável -> Visão gerencial").
O responsável O&M e o gestor de contrato de cada usina vêm do cadastro do Nexus, pela moldura (o nome da pessoa só existe
decifrado lá): a tela pede `nexus:pede-responsaveis` à janela de cima e recebe `nexus:responsaveis` com o mapa {chave do
nome da usina: {"om", "gestor"}}. A chave é a MESMA do `chave` do Nexus (nexus/performance/responsaveis.py)."""
import json
import pathlib
import shutil
import subprocess

import pytest

HTML = (pathlib.Path(__file__).resolve().parents[1] / "plataforma" / "templates" / "gerencial.html").read_text(encoding="utf-8")


def _func(nome):
    i = HTML.index("function " + nome + "(")
    return HTML[i:HTML.index("\n}\n", i) + 3]


def _node(js):
    node = shutil.which("node")
    if not node:
        pytest.skip("node não instalado")
    i = HTML.index("const _ROM=")
    base = (HTML[i:HTML.index(";", i) + 1] + _func("_chaveUsina") + _func("_respDe") + _func("_passaResp") + _func("deriva")
            + "let fCli='', fResp='', RESP=null;")
    p = subprocess.run([node, "-e", base + js], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_a_chave_e_a_mesma_do_nexus():
    r = _node("process.stdout.write(JSON.stringify(['Piracicaba I','Céu Azul II (103)','  AP. do   Taboado ',null].map(_chaveUsina)));")
    assert r == ["piracicaba 1", "ceu azul 2 103", "ap do taboado", ""]          # os casos do teste do Nexus


RAW = {"usinas": [{"usina": "Altair", "cliente": "Thopen", "prod": 100, "p50": 100, "atingimento": 100},
                  {"usina": "Piracicaba I", "cliente": "Thopen", "prod": 80, "p50": 100, "atingimento": 80},
                  {"usina": "Tupi Paulista", "cliente": "2C", "prod": 50, "p50": 100, "atingimento": 50},
                  {"usina": "Sem Ligação", "cliente": "Thopen", "prod": 10, "p50": 10, "atingimento": 100}],
       "portfolio": {}}
MAPA = {"altair": {"om": "Ana", "gestor": "Bruno"}, "piracicaba 1": {"om": "Carla", "gestor": "Bruno"},
        "tupi paulista": {"om": "Ana", "gestor": "Davi"}}


def _filtra(cli, resp):
    return _node("RESP=%s; fCli=%s; fResp=%s; const d=deriva(%s);"
                 "process.stdout.write(JSON.stringify({us:d.usinas.map(u=>u.usina), n:d.portfolio.n||null, at:d.portfolio.atingimento||null}));"
                 % (json.dumps(MAPA), json.dumps(cli), json.dumps(resp), json.dumps(RAW)))


def test_o_filtro_recorta_pelo_responsavel_om_ou_pelo_gestor_e_junta_com_o_cliente():
    assert _filtra("", "om|Ana")["us"] == ["Altair", "Tupi Paulista"]
    r = _filtra("", "gestor|Bruno")
    assert r["us"] == ["Altair", "Piracicaba I"] and r["n"] == 2 and r["at"] == 90.0   # o portfólio é refeito no recorte
    assert _filtra("Thopen", "om|Ana")["us"] == ["Altair"]
    assert _filtra("", "")["us"] == [u["usina"] for u in RAW["usinas"]]                # sem filtro, tudo
    assert "Sem Ligação" not in _filtra("Thopen", "om|Carla")["us"]                    # sem ligação fica fora do recorte


def test_so_aceita_a_resposta_da_janela_de_cima_na_mesma_origem_e_pede_ao_abrir():
    assert "ev.origin!==location.origin||ev.source!==window.parent" in HTML
    assert "window.parent.postMessage({tipo:'nexus:pede-responsaveis'},location.origin)" in HTML
    assert 'id="fRespLbl" hidden' in HTML                                              # fora do Nexus não aparece
