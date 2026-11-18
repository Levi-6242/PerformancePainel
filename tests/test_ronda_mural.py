# -*- coding: utf-8 -*-
"""O mural da ronda de trackers do App de Campo (18/11/2026). Levi: "Refaça a página Ronda de trackers da performance como
um mural de acompanhamento da ronda de trackers do app de campo"; sobre os cartões do mockup, "isso tem que ser clicável
e filtrável"."""
import os

import pytest

import app
import ronda_mural as rm

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = open(os.path.join(RAIZ, "plataforma", "templates", "ronda_mural.html"), encoding="utf-8").read()


def _linha(data, usina, tec, ap, rs, ini="T10:00:00.000Z", fim="T10:40:00.000Z", **mais):
    return {"Data": data, "Usina": usina, "Região": "SP Oeste 01", "Técnico": tec, "Técnico (HMAC)": "h-" + tec, "Tipo": "curta", "Nota da ronda": 95,
            "Falhas": None, "Trackers apontados": ap, "Trackers respondidos": rs, "Início": data + ini, "Fim": data + fim, **mais}


LIVRO = [_linha("2026-11-05", "Thopen - Usina A - SP", "Ana", 19, 4, Falhas="ronda longa pendente"),
         _linha("2026-11-17", "Thopen - Usina A - SP", "Ana", 5, 0),
         _linha("2026-11-10", "Thopen - Usina B - SP", "Beto", 0, 0),                      # ronda sem tracker apontado
         _linha("2026-11-12", "Athon - Usina C - PA", "Caio", 8, 8, fim="T09:00:00.000Z"),  # fim antes do início: sem duração
         _linha("2026-10-30", "Thopen - Usina A - SP", "Ana", 3, 3)]                        # outro mês
PACOTE = {"gerado_em": "2026-11-17 14:32",
          "disponibilidade": {"usinas": [{"usina": "Usina A", "fracttal": "Thopen - Usina A - SP"}, {"usina": "Usina B", "fracttal": "Thopen - Usina B - SP"},
                                         {"usina": "Usina D", "fracttal": "Thopen - Usina D - SP"}]},
          "trackers": {"rows": [{"usina": "Usina A", "cliente": "Thopen", "fonte": "pg", "tracker": "Tracker 2", "inicio": "2026-11-13 09:00", "fim": None, "cronico": False},
                                {"usina": "Usina A", "cliente": "Thopen", "fonte": "pg", "tracker": "Tracker 1", "inicio": "2026-11-05 09:00", "fim": None, "cronico": True},
                                {"usina": "Usina A", "cliente": "Thopen", "fonte": "pg", "tracker": "Tracker 7", "inicio": "2026-11-02 09:00", "fim": "2026-11-03"},
                                {"usina": "Usina D", "cliente": "Thopen", "fonte": "pv", "tracker": "TRK9", "inicio": "2026-11-09 08:00", "fim": None},
                                {"usina": "Usina Sem Nome", "cliente": "Thopen", "fonte": "pv", "tracker": "TRK1", "inicio": "2026-11-09 08:00", "fim": None}]}}


def test_a_usina_que_o_fracttal_junta_com_a_vizinha():
    """Levi, 18/11/2026: "SE EXISTIR CORAÇÃO NO FRACTTAL COM DUAS CABINES PODE CONTAR COMO CORAÇÃO 2". O livro chama de
    "Thopen - Coração 1 e 2 - SC"; o cadastro tem a 1 como "Thopen - Coração 1 - SC" e a 2 sem nome do Fracttal."""
    livro = {"Thopen - Coração 1 e 2 - SC", "Thopen - Usina A - SP", "2C - Tupi Paulista 1 e 2 - SP", "Apolo - Rio do Peixe I e II - PB",
             "Thopen - Guatambu 1 e 2 - SP", "Thopen - Guatambu 1 e 2 e 3 - SP"}
    assert rm.nome_no_livro("Coração 1", "Thopen - Coração 1 - SC", "Thopen", livro) == "Thopen - Coração 1 e 2 - SC"
    assert rm.nome_no_livro("Coração 2", "", "Thopen", livro) == "Thopen - Coração 1 e 2 - SC"
    assert rm.nome_no_livro("Usina A", "Thopen - Usina A - SP", "Thopen", livro) == "Thopen - Usina A - SP"       # o cadastro manda quando está no livro
    assert rm.nome_no_livro("Rio do Peixe II", "", "Apolo", livro) == "Apolo - Rio do Peixe I e II - PB"         # romano também
    assert rm.nome_no_livro("Coração 3", "", "Thopen", livro) == ""                                              # o 3 não está no "1 e 2"
    assert rm.nome_no_livro("Coração 2", "", "Athon", livro) == ""                                               # outro cliente não casa
    assert rm.nome_no_livro("Guatambu 1", "", "Thopen", livro) == ""                                             # dois candidatos: não adivinha
    assert rm.nome_no_livro("Usina Nova", "Thopen - Usina Nova - SP", "Thopen", livro) == "Thopen - Usina Nova - SP"   # sem ronda no livro: o do cadastro
    # no mural: os parados da Coração 1 e da 2 e a ronda caem na MESMA linha, e a 2 deixa de ficar de fora
    pac = {"disponibilidade": {"usinas": [{"usina": "Coração 1", "fracttal": "Thopen - Coração 1 - SC", "cliente": "Thopen"}, {"usina": "Coração 2", "fracttal": "", "cliente": "Thopen"}]},
           "trackers": {"rows": [{"usina": "Coração 1", "cliente": "Thopen", "fonte": "pv", "tracker": "TRK1", "inicio": "2026-11-10 08:00", "fim": None},
                                 {"usina": "Coração 2", "cliente": "Thopen", "fonte": "pv", "tracker": "TRK9", "inicio": "2026-11-11 08:00", "fim": None}]}}
    m = rm.montar([_linha("2026-11-12", "Thopen - Coração 1 e 2 - SC", "Ana", 2, 2)], pac, "2026-11", "2026-11-18")
    assert [(u["u"], u["par"], u["nT"], u["ap"], u["rs"]) for u in m["usinas"]] == [("Thopen - Coração 1 e 2 - SC", 2, 1, 2, 2)] and m["semPar"] == []


def test_a_conta_do_mural():
    m = rm.montar(LIVRO, PACOTE, "2026-11", "2026-11-18")
    us = {u["u"]: u for u in m["usinas"]}
    a = us["Thopen - Usina A - SP"]
    # os parados são as paradas EM ABERTO do pacote, pela usina do Fracttal; a que já voltou não entra
    assert a["par"] == 2 and a["trk"] == [["Tracker 1", "2026-11-05", True], ["Tracker 2", "2026-11-13", False]] and a["fonte"] == "Thopen · Banco de dados"
    assert (a["n"], a["nT"], a["ap"], a["rs"]) == (2, 2, 24, 4) and a["ultT"]["d"] == "2026-11-17" and a["ultT"]["rs"] == 0
    # parado e sem ronda de trackers no mês; e a ronda sem tracker apontado não conta como ronda de trackers
    d, b = us["Thopen - Usina D - SP"], us["Thopen - Usina B - SP"]
    assert (d["par"], d["n"], d["nT"], d["ultT"]) == (1, 0, 0, None) and (b["par"], b["n"], b["nT"]) == (0, 1, 0)
    # só as rondas com tracker apontado, da mais nova para a mais velha; o outro mês fica fora
    assert [(r["d"], r["u"][:5], r["ap"], r["rs"]) for r in m["rondas"]] == [("2026-11-17", "Thope", 5, 0), ("2026-11-12", "Athon", 8, 8), ("2026-11-05", "Thope", 19, 4)]
    assert m["rondas"][0]["min"] == 40 and m["rondas"][1]["min"] is None                   # duração impossível não vira número
    assert m["nRondas"] == 4 and m["nTec"] == 3 and m["pacote"] == "2026-11-17 14:32"
    assert m["semPar"] == ["Usina Sem Nome"]                                               # sem o nome do Fracttal no cadastro: dito, não escondido
    assert rm.meses_do_livro(LIVRO) == ["2026-10", "2026-11"]
    # sem o pacote do mês, as rondas saem do mesmo jeito (sem parados)
    s = rm.montar(LIVRO, None, "2026-11", "2026-11-18")
    assert s["pacote"] == "" and all(u["par"] == 0 for u in s["usinas"]) and len(s["rondas"]) == 3


@pytest.fixture
def cli(monkeypatch):
    app.app.config["TESTING"] = True
    monkeypatch.setattr(app, "_rel_sem_rondas_linhas", lambda: (LIVRO, None, 1794970000.0))
    monkeypatch.setattr(app, "_falhas_arquivo", lambda mes: os.path.join(RAIZ, "nao-existe-%s.json" % mes))
    app._ronda_mural_memo.update(chave=None, dados=None)
    with app.app.test_client() as c:
        yield c


def test_a_rota_do_mural(cli, monkeypatch):
    j = cli.get("/api/ronda/mural?mes=2026-11").get_json()
    assert j["ok"] and j["mes"] == "2026-11" and len(j["rondas"]) == 3 and j["meses"] == ["2026-10", "2026-11"] and j["livro_em"]
    assert cli.get("/api/ronda/mural?mes=novembro").status_code == 400
    monkeypatch.setattr(app, "_rel_sem_rondas_linhas", lambda: (None, "RuntimeError: fora do ar", None))
    r = cli.get("/api/ronda/mural")
    assert r.status_code == 503 and "livro de rondas" in r.get_json()["motivo"]            # sem o livro não se inventa mural


def test_a_pagina_e_o_mural_e_a_de_antes_segue_na_aba(cli):
    html = cli.get("/ronda/monitor").get_data(as_text=True)
    assert "<title>Ronda de trackers</title>" in html and "{% raw %}" not in html and "{{ sala_css" not in html
    assert ".tela{display:grid" in html and "--fundo:#090d18" in html                      # a folha da Sala
    antiga = cli.get("/ronda/monitor?antiga=1").get_data(as_text=True)
    assert "/api/ronda/whats/status" in antiga and 'src="/ronda/monitor?antiga=1"' in HTML   # a tela do WhatsApp, inteira, dentro da aba
    assert "/ronda/monitor/antiga" not in [r.rule for r in app.app.url_map.iter_rules()]   # sem rota nova: o mapa do Nexus não muda


def test_os_cartoes_sao_clicaveis_e_as_listas_filtraveis():
    """Levi, 18/11/2026: "isso tem que ser clicável e filtrável"."""
    assert '<button class="kn ${cls}" data-kpi="${id}"' in HTML
    for k in ('k("rondas"', 'k("devol"', 'k("sem"', 'k("inc"'):
        assert k in HTML
    assert 'if (k === "sem") { const ja = ABA === "m" && SIT === "sem"; ABA = "m"; SIT = ja ? null : "sem"; }' in HTML
    assert 'else if (k === "inc") { const ja = ABA === "r" && F.inc; ABA = "r"; F.inc = !ja; SIT = null; }' in HTML
    assert 'data-f="${id}"' in HTML and 'data-sitf="${id}"' in HTML and 'data-inc="1"' in HTML and 'data-limpa="1"' in HTML
    assert 'pega("/api/ronda/mural"' in HTML and "Mockup" not in HTML
    # quem só lê (o gestor do Nexus) também abre o mural
    assert '"/api/ronda/mural",' in open(os.path.join(RAIZ, "plataforma", "leitura_nexus.py"), encoding="utf-8-sig").read()
