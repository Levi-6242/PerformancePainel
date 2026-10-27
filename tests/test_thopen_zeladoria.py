# -*- coding: utf-8 -*-
"""A aba Zeladoria do dashboard do cliente (Levi, 26/10/2026: "agora faz a mesma tela no dashboard do cliente"). O Nexus
publica a visão pronta (usina × semana); o 5080 escolhe a semana, filtra pelas carteiras da conta e monta a tela. Dado
falso, nada de rede."""
import os
import sys

import pytest

AQUI = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(AQUI, "..", "thopen"))
import acessos  # noqa: E402
import dashboard_thopen as dth  # noqa: E402
import fonte_operacao  # noqa: E402
import fonte_zeladoria  # noqa: E402
import zeladoria_cliente as zc  # noqa: E402

DE_PARA = [{"usina_id": 1, "chave_externa": "Altair"}, {"usina_id": 2, "chave_externa": "Assis"},
           {"usina_id": 3, "chave_externa": "Guaratinguetá V"}]


def did(iso):
    return int(iso.replace("-", "")) if iso else None


def lin(uid, sem, ini, veg=None, suj=None, dia=None, **kw):
    """Uma linha do livro nexus_zeladoria (nomes finais de 27/10/2026, datas em data_id AAAAMMDD)."""
    r = dict.fromkeys(zc.CAMPOS)
    r.update(usina_id=uid, semana=sem, data_id_semana=did(ini), vegetacao_nivel=veg, sujidade_nivel=suj,
             data_id_leitura=did(dia), leituras_qtd=1 if dia else 0)
    for k, v in kw.items():
        r[k] = did(v) if k.startswith("data_id_") else v
    return r


SEMANAS = [("2026-W%02d" % w, "2026-%s" % d) for w, d in
           ((36, "08-31"), (37, "09-07"), (38, "09-14"), (39, "09-21"), (40, "09-28"), (41, "10-05"), (42, "10-12"),
            (43, "10-19"))]
LINHAS = (
    [lin(1, s, d, veg=2, suj=2, dia=d) for s, d in SEMANAS[:-1]]
    + [lin(1, "2026-W43", "2026-10-19", veg=5, suj=3, dia="2026-10-21", os=16249, vala="Parcial",
           recomendacao="supressao_vegetal", situacao_vegetacao="a_programar", data_id_prazo_vegetacao="2026-10-21",
           data_id_ultima_supressao="2026-09-02", data_id_ultima_limpeza="2026-08-20")]
    + [lin(2, "2026-W42", "2026-10-12", veg=3, suj=2, dia="2026-10-14"),
       lin(2, "2026-W43", "2026-10-19", veg=4, suj=4, dia="2026-10-22", recomendacao="supressao_vegetal;limpeza_modulos",
           situacao_vegetacao="programada", data_id_situacao_vegetacao="2026-10-28", os_zeladoria_vegetacao=17500,
           situacao_sujidade="feita", data_id_situacao_sujidade="2026-10-23", data_id_prazo_vegetacao="2026-10-29",
           data_id_prazo_sujidade="2026-10-29")]
    + [lin(3, "2026-W43", "2026-10-19", veg=5, suj=5, dia="2026-10-20", situacao_vegetacao="a_programar",
           situacao_sujidade="a_programar")]                                 # Guaratinguetá V é da Polaris
    + [lin(99, "2026-W43", "2026-10-19", veg=1, suj=1, dia="2026-10-20")]   # sem nome no 5080: fora
)
ATU = [{"atualizado_em": "2026-10-27T08:37:00-03:00", "semana_corrente": "2026-W44", "linhas_qtd": len(LINHAS),
        "semanas_qtd": 12, "usinas_qtd": 4, "checklist_ate": 20261027}]
NOMES = zc.nomes_por_id(DE_PARA)


def test_semana_escolhida_e_janela_de_8():
    r = zc.montar(LINHAS, NOMES, ["Altair", "Assis"], semana="2026-W43", semana_corrente="2026-W44")
    assert r["semana"] == "2026-W43"
    assert [s["semana"] for s in r["evolucao"]["semanas"]] == ["2026-W%02d" % w for w in range(36, 44)]
    assert r["evolucao"]["semanas"][0]["ini"] == "2026-08-31"
    alt = next(u for u in r["evolucao"]["usinas"] if u["usina"] == "Altair")
    assert alt["vegetacao"] == [2, 2, 2, 2, 2, 2, 2, 5]
    # sem escolha: a corrente da aba de atualização, em andamento mesmo sem linha nenhuma ainda
    r = zc.montar(LINHAS, NOMES, ["Altair", "Assis"], semana_corrente="2026-W44")
    assert r["semana"] == "2026-W44" and r["evolucao"]["semanas"][-1] == {"semana": "2026-W44", "ini": "2026-10-26",
                                                                            "em_andamento": True}
    assert [s["semana"] for s in r["semanas"]] == ["2026-W44", "2026-W43", "2026-W42", "2026-W41", "2026-W40"]
    # na semana em andamento sem leitura, a tabela traz a última de cada usina (a da W43)
    assert {t["semana"] for t in r["tabela"]} == {"2026-W43"} and r["kpis"]["com_leitura"] == 0


def test_so_as_usinas_da_conta_e_da_carteira():
    r = zc.montar(LINHAS, NOMES, ["Altair", "Assis"], semana="2026-W43")
    assert {t["usina"] for t in r["tabela"]} == {"Altair", "Assis"}            # sem a Guaratinguetá V (Polaris)


def test_numeros_de_cima():
    k = zc.montar(LINHAS, NOMES, ["Altair", "Assis"], semana="2026-W43")["kpis"]
    assert k["com_leitura"] == 2 and k["usinas"] == 2
    assert k["vegetacao_acima"] == 2 and k["vegetacao_5"] == 1 and k["vegetacao_media"] == 4.5
    assert k["sujidade_acima"] == 1 and k["sujidade_media"] == 3.5
    assert k["recomendacoes"] == 3 and k["a_programar"] == 1 and k["programadas"] == 1 and k["feitas"] == 1


def test_recomendacoes_a_mais_grave_primeiro_e_com_palavras_do_cliente():
    r = zc.montar(LINHAS, NOMES, ["Altair", "Assis"], semana="2026-W43")
    recs = r["recomendacoes"]                                                 # a feita não entra na fila
    assert [(x["usina"], x["tipo"], x["texto"]) for x in recs] == [
        ("Altair", "Supressão vegetal", "a programar"), ("Assis", "Supressão vegetal", "programada para 28/10")]
    assist = next(t for t in r["tabela"] if t["usina"] == "Assis")
    assert [x["texto"] for x in assist["recomendacoes"]] == ["programada para 28/10", "feita em 23/10"]
    assert assist["vegetacao_antes"] == 3 and assist["sujidade_antes"] == 2   # a seta para a leitura anterior


def test_nivel_3_nao_pede_acao():
    r = zc.montar(LINHAS, NOMES, ["Altair"], semana="2026-W43")
    alt = r["tabela"][0]
    assert alt["sujidade"] == 3 and [x["campo"] for x in alt["recomendacoes"]] == ["vegetacao"]


def test_evolucao_conta_a_carteira_por_semana():
    r = zc.montar(LINHAS, NOMES, ["Altair", "Assis"], semana="2026-W43")
    assert r["evolucao"]["grupo"]["vegetacao"][-1] == {"acima": 2, "com_leitura": 2}
    assert r["evolucao"]["grupo"]["vegetacao"][-2] == {"acima": 0, "com_leitura": 2}


def test_conferir_pela_contagem_da_atualizacao():
    assert zc.conferir({"linhas": LINHAS, "atualizacao": ATU})
    assert not zc.conferir({"linhas": LINHAS[:-1], "atualizacao": ATU})
    assert not zc.conferir({"linhas": LINHAS, "atualizacao": []})


def test_datas_em_data_id():
    assert zc.data_iso(20261021) == zc.data_iso("20261021") == zc.data_iso(20261021.0) == "2026-10-21"
    assert zc.data_iso(None) is None and zc.data_iso("x") is None
    alt = zc.montar(LINHAS, NOMES, ["Altair"], semana="2026-W43")["tabela"][0]
    assert alt["data_leitura"] == "2026-10-21" and alt["ultima_supressao"] == "2026-09-02" and alt["os_ronda"] == 16249


# ── a rota ──────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def cli(monkeypatch):
    monkeypatch.delenv("THOPEN_LOGIN", raising=False)
    monkeypatch.delenv("THOPEN_ZELADORIA", raising=False)
    monkeypatch.setattr(fonte_zeladoria, "dados", lambda *a, **k: {"linhas": LINHAS, "atualizacao": ATU})
    monkeypatch.setattr(fonte_operacao, "dados", lambda *a, **k: {"de_para": DE_PARA})
    monkeypatch.setattr(dth, "_usinas_disponiveis", lambda: ["Altair", "Assis", "Guaratinguetá V"])
    monkeypatch.setattr(dth, "CARTEIRAS", dict(dth.CARTEIRAS, Thopen=["Altair", "Assis"]))
    monkeypatch.setattr(dth, "_CARTEIRA_DE", dict(dth._CARTEIRA_DE, Altair="Thopen", Assis="Thopen"))
    return dth.app.test_client()


def test_rota_da_carteira(cli):
    r = cli.get("/api/t/zeladoria?carteira=Thopen&semana=2026-W43").get_json()
    assert r["disponivel"] is True and r["carteira"] == "Thopen" and r["kpis"]["vegetacao_acima"] == 2
    assert r["atualizado_em"] == "2026-10-27T08:37" and r["semanas"][0]["semana"] == "2026-W44"
    assert "Guaratinguetá V" not in {t["usina"] for t in r["tabela"]}


def test_rota_sem_publicacao_diz_que_esta_carregando(cli, monkeypatch):
    monkeypatch.setattr(fonte_zeladoria, "dados", lambda *a, **k: None)
    r = cli.get("/api/t/zeladoria?carteira=Thopen").get_json()
    assert r["disponivel"] is False and r["motivo"] == "carregando"


def test_rota_desligada(cli, monkeypatch):
    monkeypatch.setenv("THOPEN_ZELADORIA", "0")
    assert cli.get("/api/t/zeladoria?carteira=Thopen").get_json()["motivo"] == "desligado"


def test_carteira_invalida_e_400(cli):
    assert cli.get("/api/t/zeladoria?carteira=Nada").status_code == 400


def test_cliente_so_ve_as_carteiras_dele(cli, monkeypatch):
    monkeypatch.setenv("THOPEN_LOGIN", "1")
    monkeypatch.setitem(dth.app.config, "SESSION_COOKIE_SECURE", False)
    conta = {"conta_id": "c1", "nome": "Cliente Teste", "email": "cliente@exemplo.com", "carteiras": ["Thopen"],
             "papel": "cliente"}
    monkeypatch.setattr(acessos, "conta", lambda cid: conta if cid == "c1" else None)
    with cli.session_transaction() as s:
        s["conta_id"] = "c1"
    assert cli.get("/api/t/zeladoria?carteira=Thopen").status_code == 200
    assert cli.get("/api/t/zeladoria?carteira=Polaris").status_code == 403


# ── a tela ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def _html():
    return open(os.path.join(AQUI, "..", "thopen", "templates", "dashboard_thopen.html"), encoding="utf-8").read()


def test_aba_zeladoria_depois_de_registros_e_fora_do_pdf():
    h = _html()
    nav = h[h.index('<nav class="nav"'):h.index("</nav>")]
    assert nav.index('data-page="registros"') < nav.index('data-page="zeladoria"') < nav.index('data-page="metodologia"')
    assert 'id="pageZeladoria"' in h and "#pageZeladoria, .zl-fundo{ display:none !important; }" in h
    assert "/api/t/zeladoria?" in h


def test_tela_sem_nome_de_tecnico_e_sem_os_do_fracttal():
    h = _html()
    z = h[h.index("// ---------- Zeladoria"):h.index("// ---------- fim da Zeladoria")]
    assert "tecnico" not in z.lower() and "sem OS" not in z
