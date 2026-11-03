# -*- coding: utf-8 -*-
"""O Atualizar das normalizações do COS (Levi, 03/11/2026: "sinto falta do botão 'Atualizar' para puxar os dados da API ou
do PG para a plataforma, fiz umas alterações nas normalizações e precisava trazer"). A correção feita no Andamento passava
por quatro esperas até a tela (o Nexus de hora em hora, o índice de 30 em 30 min, o workbook de hora em hora, a leitura
do 5080 de 10 em 10 min). Agora: o ícone da Grid grava o pedido, o Nexus grava na hora, o worker vê a versão nova do livro
e refaz a conta com a última varredura do Fracttal, a aba Falhas publica sem a hora de espera e o 5080 relê. Dados
fictícios."""
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "thopen"))
import dashboard_thopen as dth  # noqa: E402
import fonte_operacao  # noqa: E402
import app  # noqa: E402
import falhas_publicar as fp  # noqa: E402

PEDIDO = "2026-11-03T16:00:00-03:00"


# ── o 5080: as etapas, o pedido e a releitura ─────────────────────────────────────────────────────────────────────────
def test_as_etapas_pelas_horas_que_cada_lado_deixou_no_banco():
    e = dth.etapa_do_atualizar
    assert e(PEDIDO, "2026-11-03T15:29:32-03:00", "", "") == "nexus"                   # a gravação é de antes do pedido
    assert e(PEDIDO, "2026-11-03T16:01:10-03:00", "2026-11-03T15:29:32-03:00", "") == "plataforma"
    assert e(PEDIDO, "2026-11-03T16:01:10-03:00", "2026-11-03T16:01:10-03:00",
             "2026-11-03T15:29:32-03:00") == "carregando"
    assert e(PEDIDO, "2026-11-03T16:01:10-03:00", "2026-11-03T16:01:10-03:00", "2026-11-03T16:01:10-03:00") == "pronto"
    assert e("", "2026-11-03T16:01:10-03:00", "", "") == "nexus" and e(PEDIDO, "", "", "") == "nexus"
    # a hora em UTC do servidor e a de Brasília são o mesmo instante
    assert e(PEDIDO, "2026-11-03T19:01:10+00:00", "", "") == "plataforma"


def test_o_pedido_grava_uma_linha_so_com_a_hora_e_junta_os_cliques(monkeypatch):
    monkeypatch.delenv("THOPEN_LOGIN", raising=False)
    gravados = []
    monkeypatch.setattr(dth.livro_banco, "acrescentar",
                        lambda livro, nome, aba, cab, novas, tok: gravados.append((livro, aba, cab, novas)) or 1)
    monkeypatch.setattr(dth.fonte_api, "_token", lambda: "tok")
    monkeypatch.setitem(dth._pedido, "em", None)
    c = dth.app.test_client()
    r = c.post("/api/t/atualizar_normalizacoes").get_json()
    assert r["ok"] and r["pedido_em"].endswith("-03:00")
    (livro, aba, cab, novas), = gravados
    assert (livro, aba) == ("thopen_pedidos", "atualizacao") and cab == ("pedido_em", "alvo", "origem")
    assert novas == [{"pedido_em": r["pedido_em"], "alvo": "disponibilidade_thopen", "origem": "dashboard_thopen"}]
    r2 = c.post("/api/t/atualizar_normalizacoes").get_json()                          # dois cliques num minuto
    assert r2["juntou"] and r2["pedido_em"] == r["pedido_em"] and len(gravados) == 1


def test_o_pedido_que_nao_grava_diz_que_nao_foi(monkeypatch):
    monkeypatch.delenv("THOPEN_LOGIN", raising=False)
    monkeypatch.setitem(dth._pedido, "em", None)

    def falha(*a, **k):
        raise dth.livro_banco.GravacaoErro("a API respondeu 500")
    monkeypatch.setattr(dth.livro_banco, "acrescentar", falha)
    r = dth.app.test_client().post("/api/t/atualizar_normalizacoes")
    assert r.status_code == 502 and "não foi gravado" in r.get_json()["erro"] and dth._pedido["em"] is None


def test_o_estado_publicado_derruba_a_leitura_e_recarrega(monkeypatch):
    monkeypatch.delenv("THOPEN_LOGIN", raising=False)
    horas = {("nexus_cos_normalizacoes", "atualizado_em"): "2026-11-03T16:01:10-03:00",
             ("falhas_performance", "normalizacoes_em"): "2026-11-03T16:01:10-03:00"}
    monkeypatch.setattr(dth, "_ultima_hora", lambda livro, aba, col: horas[(livro, col)])
    monkeypatch.setattr(fonte_operacao, "normalizacoes_em", lambda: "2026-11-03T15:29:32-03:00")
    chamadas = []
    monkeypatch.setattr(fonte_operacao, "invalidar", lambda: chamadas.append("invalidar"))
    monkeypatch.setattr(fonte_operacao, "dados", lambda *a, **k: chamadas.append("dados"))
    monkeypatch.setattr(dth, "_agora", lambda: dth._instante("2026-11-03T16:02:00-03:00"))
    j = dth.app.test_client().get("/api/t/atualizar_normalizacoes?desde=" + PEDIDO).get_json()
    assert j["etapa"] == "carregando" and not j["demorou"] and chamadas == ["invalidar", "dados"]
    monkeypatch.setattr(fonte_operacao, "normalizacoes_em", lambda: "2026-11-03T16:01:10-03:00")
    chamadas.clear()
    j = dth.app.test_client().get("/api/t/atualizar_normalizacoes?desde=" + PEDIDO).get_json()
    assert j["etapa"] == "pronto" and j["nexus_em"] == "2026-11-03T16:01:10-03:00" and not chamadas


def test_passado_o_prazo_a_tela_diz_onde_parou(monkeypatch):
    monkeypatch.delenv("THOPEN_LOGIN", raising=False)
    monkeypatch.setattr(dth, "_ultima_hora", lambda livro, aba, col: "2026-11-03T15:29:32-03:00")
    monkeypatch.setattr(fonte_operacao, "normalizacoes_em", lambda: "")
    monkeypatch.setattr(dth, "_agora", lambda: dth._instante("2026-11-03T16:14:00-03:00"))
    assert not dth.app.test_client().get("/api/t/atualizar_normalizacoes?desde=" + PEDIDO).get_json()["demorou"]
    monkeypatch.setattr(dth, "_agora", lambda: dth._instante("2026-11-03T16:16:00-03:00"))
    j = dth.app.test_client().get("/api/t/atualizar_normalizacoes?desde=" + PEDIDO).get_json()
    assert j["etapa"] == "nexus" and j["demorou"]                                       # 16 min depois do pedido


def test_so_a_grid_pede(monkeypatch):
    assert {"atualizar_normalizacoes_pedir", "atualizar_normalizacoes_estado"} <= dth._SO_GRID


def test_a_leitura_do_5080_guarda_a_hora_das_normalizacoes_e_se_derruba(monkeypatch):
    assert "normalizacoes_em" in fonte_operacao.ABAS[("falhas_performance", "atualizacao")][1]
    monkeypatch.setattr(fonte_operacao, "_estado", dict(fonte_operacao._estado, ts=999.0, proxima=50.0, dados={
        "atualizacao": [{"mes": "2026-10", "normalizacoes_em": "2026-11-03T15:29:32-03:00"},
                        {"mes": "2026-11", "normalizacoes_em": "2026-11-03T16:01:10-03:00"},
                        {"mes": "2026-09", "normalizacoes_em": None}]}))
    assert fonte_operacao.normalizacoes_em() == "2026-11-03T16:01:10-03:00"
    fonte_operacao.invalidar()
    assert fonte_operacao._estado["ts"] == 0.0 and fonte_operacao._estado["proxima"] == 0.0


def test_o_workbook_leva_a_hora_das_normalizacoes_na_atualizacao():
    assert fp.CABECALHOS["atualizacao"][-1] == "normalizacoes_em"
    pac = {"mes": "2026-11", "periodo": ["2026-11-01", "2026-11-02"], "gerado_em": "2026-11-03 16:02",
           "disponibilidade": {"periodo": ["2026-11-01", "2026-11-03"], "usinas": [], "diario": {}, "oss": [],
                               "normalizacoes_em": "2026-11-03T16:01:10-03:00"}}
    linha = fp.tabelas([pac])["atualizacao"][0]
    assert dict(zip(fp.CABECALHOS["atualizacao"], linha))["normalizacoes_em"] == "2026-11-03T16:01:10-03:00"


# ── o worker: a conta pela gravação nova do Nexus, com a última varredura ────────────────────────────────────────────
MESES = [("2026-11", datetime(2026, 11, 1), datetime(2026, 11, 3)), ("2026-10", datetime(2026, 10, 1), datetime(2026, 11, 1))]


@pytest.fixture
def volta(monkeypatch):
    """O worker com uma volta inteira guardada (a varredura das 15:30) e o índice numa pasta temporária."""
    v = {"wos": {"1": [{"code": "X"}]}, "vereditos": {}, "resumo": {"paginas": 3}, "ts": 1.0,
         "rotulos": [m[0] for m in MESES], "dia": datetime.now().date(), "versao": "v1"}
    monkeypatch.setattr(app, "_FRAC_DISP_VOLTA", v)
    monkeypatch.setattr(app, "_disp_meses_alvo", lambda hoje=None: MESES)
    monkeypatch.setattr(app, "_disp_equip_linhas", lambda: [{"usina": "Alfa"}])
    montadas, registros = [], []
    monkeypatch.setattr(app, "_frac_disp_montar", lambda meses, wos, ver, res, equip, ts, versao: montadas.append(
        (wos, ts, versao)) or True)
    monkeypatch.setattr(app, "_frac_disp_registrar", lambda ok, msg, resumo=None: registros.append((ok, msg)))
    monkeypatch.setattr(app, "_disp_cos_atualizado_em", lambda: "2026-11-03T16:01:10-03:00")
    return {"v": v, "montadas": montadas, "registros": registros}


def test_a_versao_nova_do_livro_refaz_o_indice_sem_varrer_o_fracttal(volta, monkeypatch):
    monkeypatch.setattr(app, "_frac_disp_sweep", lambda *a, **k: pytest.fail("não varre o Fracttal de novo"))
    assert app._frac_disp_pelas_normalizacoes("v1") is False and not volta["montadas"]     # a mesma versão: nada
    assert app._frac_disp_pelas_normalizacoes("v2") is True
    (wos, ts, versao), = volta["montadas"]
    assert wos is volta["v"]["wos"] and ts == 1.0 and versao == "v2"                     # a varredura e a hora dela
    ok, msg = volta["registros"][-1]
    assert ok and "normalizações do COS gravadas em 16:01" in msg
    assert app._frac_disp_pelas_normalizacoes(None) is False                             # o banco fora: espera


def test_dia_novo_ou_sem_varredura_guardada_faz_a_volta_inteira(volta, monkeypatch):
    inteiras = []
    monkeypatch.setattr(app, "_frac_disp_recalcular", lambda: inteiras.append(1))
    volta["v"]["dia"] = datetime(2026, 11, 2).date()
    assert app._frac_disp_pelas_normalizacoes("v2") is True and inteiras == [1] and not volta["montadas"]
    monkeypatch.setattr(app, "_FRAC_DISP_VOLTA", {})
    assert app._frac_disp_pelas_normalizacoes("v3") is False                             # o boot: a volta do laço leva


def test_a_conta_que_nao_publica_tenta_tres_minutos_e_para(volta, monkeypatch):
    # a leitura no meio da gravação do Nexus sai "pela metade": o minuto seguinte lê a gravação inteira
    tentativas = []
    monkeypatch.setattr(app, "_frac_disp_montar", lambda *a, **k: tentativas.append(1) and False)
    for _ in range(3):
        assert app._frac_disp_pelas_normalizacoes("v2") is False
    assert len(tentativas) == 3 and volta["v"]["versao"] == "v2"
    assert app._frac_disp_pelas_normalizacoes("v2") is False and len(tentativas) == 3     # a volta inteira leva


def test_a_aba_falhas_publica_na_hora_so_com_outra_gravacao(monkeypatch):
    idx = {"cos": {"atualizado_em": "2026-11-03T15:29:32-03:00"}}
    monkeypatch.setattr(app, "_frac_disp_dados", lambda: idx)
    monkeypatch.setattr(app, "_falhas_cos_visto", {"em": None})
    feitos = []
    monkeypatch.setattr(app, "_falhas_disp_fora_da_volta", lambda montados: feitos.append(("pacotes", set(montados))))
    monkeypatch.setattr(app, "_falhas_publicar_workbook", lambda meses, agora=False: feitos.append(("workbook", agora)))
    monkeypatch.setattr(app, "_falhas_meses", lambda hoje=None: ["2026-10", "2026-11"])
    assert app._falhas_disp_pelas_normalizacoes() is False and not feitos      # o 1º índice depois de subir: a volta leva
    assert app._falhas_disp_pelas_normalizacoes() is False and not feitos      # a mesma gravação
    idx["cos"]["atualizado_em"] = "2026-11-03T16:01:10-03:00"
    assert app._falhas_disp_pelas_normalizacoes() is True
    assert feitos == [("pacotes", set()), ("workbook", True)]
    assert app._falhas_disp_pelas_normalizacoes() is False                     # já publicada: nada de novo


def test_a_publicacao_dentro_do_minuto_tenta_de_novo(monkeypatch):
    # a volta normal do workbook acabou de subir: a pedida espera o minuto e tenta de novo, não se perde
    idx = {"cos": {"atualizado_em": "2026-11-03T16:01:10-03:00"}}
    monkeypatch.setattr(app, "_frac_disp_dados", lambda: idx)
    monkeypatch.setattr(app, "_falhas_cos_visto", {"em": "2026-11-03T15:29:32-03:00"})
    monkeypatch.setattr(app, "_falhas_disp_fora_da_volta", lambda montados: None)
    monkeypatch.setattr(app, "_falhas_meses", lambda hoje=None: ["2026-11"])
    resposta = ["espera"]
    monkeypatch.setattr(app, "_falhas_publicar_workbook", lambda meses, agora=False: resposta[0])
    assert app._falhas_disp_pelas_normalizacoes() is False and app._falhas_cos_visto["em"].startswith("2026-11-03T15")
    resposta[0] = None
    assert app._falhas_disp_pelas_normalizacoes() is True and app._falhas_cos_visto["em"] == idx["cos"]["atualizado_em"]


def test_o_workbook_pedido_sobe_sem_a_hora_de_espera(monkeypatch):
    monkeypatch.setenv("GRIDCO_SQL_TOKEN", "tok")
    monkeypatch.setattr(app, "_falhas_workbook_ligado", lambda: True)
    monkeypatch.setattr(app, "_falhas_wb", {"ts": __import__("time").time() - 120, "marca": None})
    lidos = []
    monkeypatch.setattr(app, "_falhas_ler", lambda arq: lidos.append(arq) or None)
    assert app._falhas_publicar_workbook(["2026-11"]) == "espera"
    assert not lidos                                                           # na volta normal: dentro da hora, nada
    app._falhas_publicar_workbook(["2026-11"], agora=True)
    assert lidos                                                               # pedida: passou do minuto, monta


class _Parou(BaseException):
    pass


def test_o_laco_confere_trinta_vezes_por_volta_mesmo_com_o_sono_que_volta_na_hora(monkeypatch):
    # 03/11/2026: o laço contado pelo relógio, com o sono falso dos testes, girou 30 min e comeu a memória da máquina
    import threading
    principal, sono = threading.current_thread(), app.time.sleep
    voltas, conferidas = [], []

    def _recalcula():
        voltas.append(1)
        if len(voltas) == 2:
            raise _Parou
    monkeypatch.setattr(app, "_frac_disp_recalcular", _recalcula)
    monkeypatch.setattr(app, "_frac_disp_pelas_normalizacoes", lambda: conferidas.append(1))
    monkeypatch.setattr(app.time, "sleep", lambda s: None if threading.current_thread() is principal else sono(s))
    with pytest.raises(_Parou):
        app._frac_disp_loop()
    assert len(conferidas) == app.FRAC_DISP_TTL // app.FRAC_DISP_COS_CHECA_S == 30
