# -*- coding: utf-8 -*-
"""Ocorrência desconsiderada pelo analista na aba de falhas (Levi, 30/09/2026).

MAB200, 22/09 07:10–09:40: cinco strings abaixo de 1 A com os trackers parados de manhã, normais depois — "teria como ter
um botão de desconsiderar ocorrência para não somar no cálculo nem aparecer?". A tela grava pela rota, o worker lê na
montagem (falhas_job, testado em test_falhas_job.py) e a lista guarda quem e quando, para poder voltar.
"""
import json
from pathlib import Path

import pytest

import app

CH_STR = "sunop|MAB200|Inversor 4.5|ST 11|2026-09-22"
CH_TRK = "pv|18748739|TRK1|2026-09-03"


@pytest.fixture
def cli(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    monkeypatch.setattr(app, "FALHAS_DESC_PATH", str(tmp_path / "falhas_desconsideradas.json"))
    return app.app.test_client()


def test_desconsiderar_grava_com_quem_e_quando_e_a_lista_devolve(cli):
    r = cli.post("/api/painel/falhas/desconsiderar", json={"tipo": "strings", "chave": CH_STR, "desconsiderar": True,
                                                            "resumo": {"usina": "MAB200", "string": "ST 11",
                                                                       "perda_kwh": 11.8, "lixo": "x" * 500}})
    assert r.status_code == 200 and r.get_json() == {"ok": True, "n": 1}
    j = cli.get("/api/painel/falhas/desconsideradas").get_json()
    info = j["strings"][CH_STR]
    assert info["usina"] == "MAB200" and info["perda_kwh"] == 11.8 and "lixo" not in info
    assert info["por"] == "senha compartilhada" and len(info["em"]) == 16
    assert app._falhas_desc_chaves() == {"strings": {CH_STR}, "trackers": set()}


def test_voltar_para_a_conta_tira_da_lista(cli):
    cli.post("/api/painel/falhas/desconsiderar", json={"tipo": "trackers", "chave": CH_TRK})
    assert CH_TRK in cli.get("/api/painel/falhas/desconsideradas").get_json()["trackers"]
    r = cli.post("/api/painel/falhas/desconsiderar", json={"tipo": "trackers", "chave": CH_TRK, "desconsiderar": False})
    assert r.get_json() == {"ok": True, "n": 0}
    assert cli.get("/api/painel/falhas/desconsideradas").get_json()["trackers"] == {}


@pytest.mark.parametrize("corpo", [{"tipo": "outro", "chave": CH_STR}, {"tipo": "strings", "chave": ""},
                                   {"tipo": "strings", "chave": CH_TRK}, {"tipo": "trackers", "chave": CH_STR}])
def test_tipo_ou_chave_errada_e_recusada(cli, corpo):
    r = cli.post("/api/painel/falhas/desconsiderar", json=corpo)
    assert r.status_code == 400 and not Path(app.FALHAS_DESC_PATH).exists()


def test_aba_deixa_desmarcar_o_que_marcou_e_tem_a_duracao_por_inversor_e_dia(cli):
    # Levi, 05/10/2026: "O CheckBox só marca e não desmarca" — no servidor, Inhapi TRK13 e TRK52 gravaram (12:15) e as
    # linhas ficaram com a caixa marcada e travada esperando a resposta. A linha marcada fica na tabela, apagada e fora
    # das contas, desmarcar devolve, e a caixa não trava; "em strings por inversor e dia quero uma coluna para a duração"
    html = cli.get("/painel/falhas").get_data(as_text=True)
    assert "DESC_VIS" in html and "desmarque para voltar" in html
    assert "c.disabled = true" not in html
    assert "['dur_h', 'Duração'" in html


def test_arquivo_ilegivel_nao_e_regravado(cli):
    Path(app.FALHAS_DESC_PATH).write_text('{"strings": {"a|b|c|d|e": ', encoding="utf-8")
    r = cli.post("/api/painel/falhas/desconsiderar", json={"tipo": "strings", "chave": CH_STR})
    assert r.status_code == 500
    assert Path(app.FALHAS_DESC_PATH).read_text(encoding="utf-8").endswith('": ')
    assert app._falhas_desc_chaves() == {}                     # o worker monta sem elas e avisa
