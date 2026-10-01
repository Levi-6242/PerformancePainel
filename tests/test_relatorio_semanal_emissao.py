# -*- coding: utf-8 -*-
"""Relatório Semanal Thopen — direcionamentos e emissão (29/09/2026).

O analista escreve na própria página a leitura da semana, o responsável e, em cada usina fora da meta, a causa, a ação
da Grid e a previsão. Isso salva sozinho em `relatorio_semanal.json`, por período. "Emitir PDF" só libera com a leitura,
o responsável e todas as linhas com causa e ação, e cada emissão do período ganha uma versão (R00, R01…) com o que foi
ao cliente — o texto e os números que a página mostrava.

Cada teste trava uma regra que protege o que o cliente recebe:
- a causa "Sem ofensor medido…" é o convite para o analista escrever a causa, não uma causa;
- campo trocado (leitura com usina, causa sem usina) é recusado — senão some da tela sem aviso;
- arquivo ilegível não é regravado: gravar por cima apagaria o que os analistas já escreveram;
- a régua do que falta é a mesma na página (JS) e no servidor.
"""
import copy
import json
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

import app
import relatorio_semanal as rs

INI, FIM = date(2026, 9, 21), date(2026, 9, 27)
K = "2026-09-21|2026-09-27"


def _snap(**k):
    s = {"leitura": "O portfólio fechou abaixo da meta por trackers parados em duas usinas.",
         "responsavel": "Analista Teste", "contato": "Analista Teste · analista@exemplo.com",
         "linhas": [{"usina": "Usina A", "causa": "Trackers parados", "acao": "OS 101 · Corretiva · aberta desde 22/09",
                     "previsao": "03/10", "pr": 0.70, "pr_meta": 0.80, "perda_mwh": 12.4},
                    {"usina": "Usina B", "causa": "Desligamento por equipamento", "acao": "Religada em 23/09",
                     "previsao": "", "pr": 0.71, "pr_meta": 0.79, "perda_mwh": 3.0}],
         "resumo": {"pr": 0.76, "pr_meta": 0.8, "disp": 98.2, "fora": 2, "total": 40, "texto": "não é número"}}
    s.update(k)
    return s


# ── o que falta para emitir ──────────────────────────────────────────────────────────────────────────────────────

def test_falta_leitura_responsavel_e_a_causa_que_so_convida():
    s = _snap(leitura="  ", responsavel="",
              linhas=[{"usina": "Usina A", "causa": rs.SEM_OFENSOR, "acao": ""},
                      {"usina": "Usina B", "causa": "Sujidade", "acao": "Lavagem programada"}])
    f = rs.faltando(s)
    assert [(x["campo"], x.get("usina")) for x in f] == [
        ("leitura", None), ("responsavel", None), ("causa", "Usina A"), ("acao", "Usina A")]
    assert f[2]["texto"] == "a causa de Usina A"


def test_nada_falta_com_tudo_preenchido_e_previsao_e_opcional():
    assert rs.faltando(_snap()) == []


# ── direcionamento: um campo por vez ─────────────────────────────────────────────────────────────────────────────

def test_grava_campo_geral_e_de_linha():
    e = {}
    rs.grava_campo(e, INI, FIM, "leitura", "Semana com chuva.", em="2026-09-29T09:00:00", por="x")
    rs.grava_campo(e, INI, FIM, "causa", "Trackers parados", usina="Usina A", em="2026-09-29T09:01:00", por="y")
    d = rs.direcionamentos(e, INI, FIM)
    assert d["leitura"] == "Semana com chuva."
    assert d["linhas"]["Usina A"] == {"causa": "Trackers parados", "em": "2026-09-29T09:01:00", "por": "y"}
    assert d["emissoes"] == [] and d["proxima_versao"] == "R00"


@pytest.mark.parametrize("campo,usina", [("leitura", "Usina A"), ("responsavel", "Usina A"), ("causa", None),
                                         ("acao", ""), ("xyz", None), ("xyz", "Usina A"), (None, None)])
def test_campo_trocado_e_recusado(campo, usina):
    e = {}
    with pytest.raises(rs.Recusado):
        rs.grava_campo(e, INI, FIM, campo, "valor", usina=usina)
    assert e == {}


def test_texto_limpo_e_cortado():
    e = {}
    assert rs.grava_campo(e, INI, FIM, "leitura", "  a   b \n\n  c  d  ") == "a b\nc d"
    assert len(rs.grava_campo(e, INI, FIM, "leitura", "x" * (rs.TAM_MAX + 50))) == rs.TAM_MAX


def test_responsavel_e_contato_valem_de_padrao_para_o_proximo_periodo():
    e = {}
    rs.grava_campo(e, INI, FIM, "responsavel", "Analista Teste")
    rs.grava_campo(e, INI, FIM, "contato", "analista@exemplo.com")
    d = rs.direcionamentos(e, date(2026, 9, 28), date(2026, 10, 4))
    assert d["responsavel"] is None
    assert d["padrao"] == {"responsavel": "Analista Teste", "contato": "analista@exemplo.com"}


# ── emissão ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_emissao_versiona_por_periodo_e_guarda_o_que_foi_ao_cliente():
    e = {}
    assert rs.registra_emissao(e, INI, FIM, _snap(), "2026-09-29T10:12", "a") == "R00"
    assert rs.registra_emissao(e, INI, FIM, _snap(leitura="Correção."), "2026-09-29T11:00", "b") == "R01"
    assert rs.registra_emissao(e, date(2026, 9, 28), date(2026, 10, 4), _snap(), "2026-10-05T09:00", "a") == "R00"
    em = e[K]["emissoes"]
    assert [x["versao"] for x in em] == ["R00", "R01"]
    assert em[0]["linhas"][0] == {"usina": "Usina A", "causa": "Trackers parados",
                                  "acao": "OS 101 · Corretiva · aberta desde 22/09", "previsao": "03/10",
                                  "pr": 0.70, "pr_meta": 0.80, "perda_mwh": 12.4}
    assert em[0]["resumo"] == {"pr": 0.76, "pr_meta": 0.8, "disp": 98.2, "fora": 2, "total": 40}
    assert em[1]["leitura"] == "Correção."
    # o que foi emitido vira o direcionamento salvo: a página reaberta mostra o mesmo que o PDF
    d = rs.direcionamentos(e, INI, FIM)
    assert d["leitura"] == "Correção." and d["linhas"]["Usina B"]["acao"] == "Religada em 23/09"
    assert d["emissoes"] == [{"versao": "R00", "em": "2026-09-29T10:12", "por": "a"},
                             {"versao": "R01", "em": "2026-09-29T11:00", "por": "b"}]
    assert d["proxima_versao"] == "R02"


def test_emissao_incompleta_nao_toca_no_estado():
    e = {}
    with pytest.raises(rs.Recusado):
        rs.registra_emissao(e, INI, FIM, _snap(leitura=""), "2026-09-29T10:12", "a")
    assert e == {}


# ── rotas ────────────────────────────────────────────────────────────────────────────────────────────────────────

PAYLOAD = {"periodo": {"ini": "2026-09-21", "fim": "2026-09-27", "dias": 7, "semana": 39},
           "resumo": {"pr": 0.76, "pr_meta": 0.8}, "fora_da_meta": [{"nome": "Usina A"}], "avisos": [], "fontes": []}


@pytest.fixture
def cli(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    monkeypatch.setattr(app, "_REL_SEM_PATH", str(tmp_path / "relatorio_semanal.json"))
    monkeypatch.setattr(app, "_rel_sem_build", lambda ini, fim, leitores=None: copy.deepcopy(PAYLOAD))
    return app.app.test_client()


def _estado():
    with open(app._REL_SEM_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_rota_salva_o_campo_e_o_get_devolve(cli):
    r = cli.post("/api/relatorio/semanal/direcionamento",
                 json={"ini": "2026-09-21", "fim": "2026-09-27", "usina": "Usina A", "campo": "causa",
                       "valor": "Trackers parados"})
    assert r.status_code == 200 and r.get_json()["ok"]
    j = cli.get("/api/relatorio/semanal?ini=2026-09-21&fim=2026-09-27").get_json()
    assert j["ok"] and j["direcionamentos"]["linhas"]["Usina A"]["causa"] == "Trackers parados"
    assert j["direcionamentos"]["linhas"]["Usina A"]["por"] == "senha compartilhada"
    assert j["sem_ofensor"] == rs.SEM_OFENSOR


@pytest.mark.parametrize("corpo", [
    {"ini": "2026-09-21", "fim": "2026-09-27", "campo": "xyz", "valor": "v"},
    {"ini": "2026-09-21", "fim": "2026-09-27", "campo": "leitura", "usina": "Usina A", "valor": "v"},
    {"ini": "2026-09-21", "fim": "2026-09-27", "campo": "causa", "valor": "v"},
    {"ini": "21/09/2026", "fim": "2026-09-27", "campo": "leitura", "valor": "v"},
    {"ini": "2026-09-27", "fim": "2026-09-21", "campo": "leitura", "valor": "v"},
])
def test_rota_recusa_campo_trocado_e_data_ruim(cli, corpo):
    r = cli.post("/api/relatorio/semanal/direcionamento", json=corpo)
    assert r.status_code == 400 and r.get_json()["ok"] is False and r.get_json()["motivo"]
    assert not Path(app._REL_SEM_PATH).exists()


def test_rota_nao_regrava_arquivo_ilegivel(cli):
    Path(app._REL_SEM_PATH).write_text('{"2026-09-21|2026-09-27": {"leitura": "texto do anal', encoding="utf-8")
    r = cli.post("/api/relatorio/semanal/direcionamento",
                 json={"ini": "2026-09-21", "fim": "2026-09-27", "campo": "leitura", "valor": "novo"})
    assert r.status_code == 500 and r.get_json()["ok"] is False
    assert Path(app._REL_SEM_PATH).read_text(encoding="utf-8").endswith("texto do anal")
    j = cli.get("/api/relatorio/semanal?ini=2026-09-21&fim=2026-09-27").get_json()
    assert j["ok"] and j["direcionamentos"] is None
    assert any("direcionamentos" in a for a in j["avisos"])


def test_rota_emitir_incompleto_diz_o_que_falta(cli):
    r = cli.post("/api/relatorio/semanal/emitir", json={"ini": "2026-09-21", "fim": "2026-09-27",
                                                        **_snap(responsavel="")})
    j = r.get_json()
    assert r.status_code == 422 and j["ok"] is False
    assert [x["campo"] for x in j["faltando"]] == ["responsavel"]
    assert not Path(app._REL_SEM_PATH).exists()


def test_rota_emitir_versiona_e_grava_quem_emitiu(cli):
    with cli.session_transaction() as s:
        s["user"], s["auth_kind"] = "analista@exemplo.com", "ms"
    corpo = {"ini": "2026-09-21", "fim": "2026-09-27", **_snap()}
    r0 = cli.post("/api/relatorio/semanal/emitir", json=corpo).get_json()
    r1 = cli.post("/api/relatorio/semanal/emitir", json=corpo).get_json()
    assert (r0["ok"], r0["versao"], r1["versao"]) == (True, "R00", "R01")
    assert r0["por"] == "analista@exemplo.com"
    em = _estado()[K]["emissoes"]
    assert [x["versao"] for x in em] == ["R00", "R01"] and em[0]["por"] == "analista@exemplo.com"
    j = cli.get("/api/relatorio/semanal?ini=2026-09-21&fim=2026-09-27").get_json()
    assert j["direcionamentos"]["proxima_versao"] == "R02"


# ── a página: a mesma régua do que falta ─────────────────────────────────────────────────────────────────────────

_TPL = (Path(__file__).resolve().parent.parent / "plataforma" / "templates" / "relatorio_semanal.html").read_text(
    encoding="utf-8").replace("\r\n", "\n")


def _js(ini, fim):
    i = _TPL.index(ini)
    return _TPL[i:_TPL.index(fim, i) + len(fim)]


def test_a_pagina_e_o_servidor_dizem_o_mesmo_que_falta():
    node = shutil.which("node")
    if not node:
        pytest.skip("node não instalado")
    casos = [_snap(), _snap(leitura=" \n "), _snap(responsavel="", linhas=[]),
             _snap(linhas=[{"usina": "Usina A", "causa": f"  {rs.SEM_OFENSOR} ", "acao": "x"},
                           {"usina": "Usina B", "causa": "", "acao": " "},
                           {"usina": "", "causa": "Sujidade", "acao": ""}])]
    js = (_js("const txt = ", ";\n") + _js("function faltando(", "\n}\n")
          + f"process.stdout.write(JSON.stringify({json.dumps(casos)}.map((s) => faltando(s, {json.dumps(rs.SEM_OFENSOR)}))));")
    p = subprocess.run([node, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout) == [rs.faltando(s) for s in casos]
    assert json.loads(p.stdout)[3] != []
