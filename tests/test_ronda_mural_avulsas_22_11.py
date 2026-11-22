# -*- coding: utf-8 -*-
"""O mural da ronda de trackers conta as respostas SEM RONDA (22/11/2026). Desde a v368 do App o técnico responde os
trackers parados pela Ronda › "Ver trackers", sem começar ronda; essas respostas chegam no livro
`rondas_trackers_app_campo` com "Origem" = avulsa (o "ID da linha" começa por "av|"; OS e "Início da ronda" vazios). O
mural só lia o livro de rondas: a usina respondida assim seguia como "parado e sem ronda de trackers". Levi, 22/11/2026:
"pode fazer as duas e subir"."""
import json
import os
import shutil
import subprocess

import pytest

import app
import ronda_mural as rm
from test_ronda_mural import HTML, LIVRO, PACOTE, RAIZ


def _trk(data, usina, tec, tracker, veredito, origem="avulsa", id_=None, **mais):
    avulsa = origem == "avulsa" or (id_ or "").startswith("av|")
    return {"Data": data, "OS": "" if avulsa else "19860", "Usina": usina, "Início da ronda": "" if avulsa else data + "T10:00:00Z",
            "Pessoa (HMAC)": "h-" + tec, "ID da linha": id_ or (f"av|{usina}|{data}|{tracker}" if avulsa else f"{usina}|{data}|curta|{tracker}"),
            "Tracker": tracker, "Veredito": veredito, "Origem": origem, "Respondido em": data + "T13:00:00Z", **mais}


D, A = "Thopen - Usina D - SP", "Thopen - Usina A - SP"
TRK = [_trk("2026-11-20", D, "Ana", "3.1", "nao"), _trk("2026-11-20", D, "Ana", "3.2", "ok"),
       _trk("2026-11-21", D, "Caio", "3.1", "ok"),
       _trk("2026-11-21", D, "Caio", "3.4", "", ),                                   # pulado: não é resposta
       _trk("2026-11-21", D, "Caio", "3.5", "na", origem="", id_="av|x|3.5"),       # sem a coluna Origem: o "av|" basta
       _trk("2026-11-21", D, "Caio", "3.5", "na", origem="", id_="av|x|3.5"),       # a mesma linha duas vezes conta uma
       _trk("2026-11-18", A, "Ana", "2.1", "ok", origem="ronda"),                   # da ronda: já está no livro de rondas
       _trk("2026-10-30", D, "Ana", "3.9", "ok"),                                   # outro mês
       _trk("2026-11-19", "Thopen - Usina E - SP", "Zeca", "1.1", "nao")]           # usina sem parado e sem ronda


def test_a_resposta_sem_ronda_entra_na_conta_da_usina():
    m = rm.montar(LIVRO, PACOTE, "2026-11", "2026-11-22", trackers=TRK)
    us = {u["u"]: u for u in m["usinas"]}
    d = us[D]
    assert (d["par"], d["nT"], d["av"], d["avNao"]) == (1, 0, 4, 1)
    # o nome do técnico sai do livro de rondas pelo mesmo código; quem não tem ronda no livro fica sem nome
    assert d["ultAv"] == {"d": "2026-11-21", "tec": "Caio", "n": 2, "nao": 0}
    assert [(x["d"], x["tec"], x["n"], x["nao"]) for x in d["avDias"]] == [("2026-11-21", "Caio", 2, 0), ("2026-11-20", "Ana", 2, 1)]
    assert us[A]["av"] == 0 and us[A]["ultAv"] is None                              # a da ronda não vira avulsa
    e = us["Thopen - Usina E - SP"]
    assert (e["par"], e["n"], e["av"], e["ultAv"]["tec"]) == (0, 0, 1, "")           # aparece mesmo sem parado e sem ronda
    assert m["avulsas"] == 5 and m["nAvUs"] == 2
    # as rondas e o resto da conta não mudam
    assert [r["d"] for r in m["rondas"]] == ["2026-11-17", "2026-11-12", "2026-11-05"]


def test_sem_o_livro_de_trackers_o_mural_e_o_de_antes():
    m = rm.montar(LIVRO, PACOTE, "2026-11", "2026-11-22")
    assert m["avulsas"] == 0 and all(u["av"] == 0 and u["ultAv"] is None and u["avDias"] == [] for u in m["usinas"])
    assert {u["u"] for u in m["usinas"]} == {u["u"] for u in rm.montar(LIVRO, PACOTE, "2026-11", "2026-11-22", trackers=[])["usinas"]}


@pytest.fixture
def cli(monkeypatch):
    app.app.config["TESTING"] = True
    monkeypatch.setattr(app, "_rel_sem_rondas_linhas", lambda: (LIVRO, None, 1794970000.0))
    monkeypatch.setattr(app, "_ronda_trackers_linhas", lambda: (TRK, None, 1794970100.0))
    monkeypatch.setattr(app, "_falhas_arquivo", lambda mes: os.path.join(RAIZ, "nao-existe-%s.json" % mes))
    app._ronda_mural_memo.update(chave=None, dados=None)
    with app.app.test_client() as c:
        yield c


def test_a_rota_le_o_livro_de_trackers_e_sem_ele_segue(cli, monkeypatch):
    j = cli.get("/api/ronda/mural?mes=2026-11").get_json()
    assert j["ok"] and j["avulsas"] == 5 and j["erro_trackers"] is None
    assert {u["u"]: u["av"] for u in j["usinas"]}["Thopen - Usina E - SP"] == 1
    # o livro de trackers fora do ar não derruba o mural: sai sem as respostas avulsas e diz por quê
    monkeypatch.setattr(app, "_ronda_trackers_linhas", lambda: (None, "RuntimeError: fora do ar", None))
    app._ronda_mural_memo.update(chave=None, dados=None)
    j = cli.get("/api/ronda/mural?mes=2026-11").get_json()
    assert j["ok"] and j["avulsas"] == 0 and "fora do ar" in j["erro_trackers"]


def _sit(u, hoje="2026-11-22"):
    """Roda o `sit()` da página no node, com a usina dada."""
    corpo = HTML.split("function sit(u) {", 1)[1].split("\n}\n", 1)[0]
    js = (f"const D = {{hoje: {json.dumps(hoje)}}}; const dias = d => Math.round((Date.parse(D.hoje) - Date.parse(d)) / 86400000);"
          f"function sit(u) {{{corpo}\n}} console.log(JSON.stringify(sit({json.dumps(u)})));")
    return json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True, encoding="utf-8").stdout)


@pytest.mark.skipif(not shutil.which("node"), reason="sem node")
def test_a_situacao_da_usina_respondida_sem_ronda():
    base = {"par": 3, "nT": 0, "av": 0, "ultT": None, "ultAv": None}
    assert _sit(base)[1] == "sem"
    assert _sit({**base, "av": 2, "ultAv": {"d": "2026-11-21", "tec": "Caio", "n": 2}}) == ["o", "ok", "Respondido sem ronda"]
    assert _sit({**base, "av": 2, "ultAv": {"d": "2026-11-10", "tec": "Caio", "n": 2}}) == ["a", "velha", "Última resposta há 12 dias"]
    # a ronda velha com resposta avulsa recente: vale a mais nova
    velha = {"d": "2026-11-05", "tec": "Ana", "ap": 4, "rs": 4}
    assert _sit({**base, "nT": 1, "ultT": velha, "av": 1, "ultAv": {"d": "2026-11-21", "tec": "Caio", "n": 1}})[1] == "ok"
    assert _sit({**base, "nT": 1, "ultT": velha}) == ["a", "velha", "Última ronda há 17 dias"]
    assert _sit({"par": 0, "nT": 0, "av": 1, "ultT": None, "ultAv": {"d": "2026-11-21", "tec": "", "n": 1}})[1] == "ok"


def test_a_pagina_mostra_as_respostas_sem_ronda():
    assert "D.usinas.filter(u => u.par || u.nT || u.av)" in HTML                      # a usina só com resposta avulsa entra
    assert "sem = comPar.filter(u => !u.nT && !u.av)" in HTML                         # e sai do "Parado e sem ronda"
    assert "Respondidos sem ronda, pelo Ver trackers" in HTML                         # o detalhe da usina
    assert "trackers respondidos\")} sem ronda" in HTML                               # a coluna da última ronda
    assert "D.erro_trackers" in HTML                                                  # o livro fora do ar é dito
