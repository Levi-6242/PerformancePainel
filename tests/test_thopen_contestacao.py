# -*- coding: utf-8 -*-
"""Contestação do cliente sobre um dia da tabela (rodada 4, Levi 09/10/2026): os itens, o canal de cada um (ronda →
Zeladoria, o resto → Performance), a validação, o limite (o 5080 é público), o cartão do Teams e o envio — com o Teams
falso, nada de rede."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "thopen"))
import contestacao as ct  # noqa: E402

OK = {"itens": ["disponibilidade", "desligamento"], "nome": " Ana  Souza ", "contato": "ana@cliente.com.br",
      "mensagem": "O inversor 3 voltou às 08h.", "tela": {"disp": "95,8%", "tracker": "0", "string": "0",
                                                         "comentario": "Desligamento inversor nº 3"}}


def test_valida_itens_contato_e_tamanho():
    d, e = ct.validar(OK)
    assert e is None and d["nome"] == "Ana Souza" and d["itens"] == ["disponibilidade", "desligamento"]
    assert ct.validar(dict(OK, itens=[]))[1] == "Marque ao menos um item para contestar."
    assert ct.validar(dict(OK, itens=["qualquer"]))[1] == "Marque ao menos um item para contestar."
    assert ct.validar(dict(OK, mensagem=""))[1] is None                 # a mensagem é opcional
    assert ct.validar(dict(OK, contato="amanhã"))[1].startswith("Informe um e-mail")
    assert ct.validar(dict(OK, nome=""))[1] == "Preencha o nome e um contato."
    assert "1000" in ct.validar(dict(OK, mensagem="x" * 1001))[1]
    assert ct.validar(dict(OK, site="http://spam"))[1] == "isca"
    assert len(ct.validar(dict(OK, tela={"comentario": "x" * 999}))[0]["tela"]["comentario"]) == ct.TELA_MAX


def test_ronda_vai_para_a_zeladoria_disponibilidade_e_desligamento_para_o_cos_e_o_resto_para_a_performance():
    # Levi, 15/10/2026: "Disponibilidade e desligamento vão para o setor de COS"
    assert ct.destinos(["ronda"]) == ["zeladoria"]
    assert ct.destinos(["string", "tracker", "geracao"]) == ["performance"]
    assert ct.destinos(["disponibilidade", "desligamento"]) == ["cos"]
    assert ct.destinos(["ronda", "disponibilidade", "geracao"]) == ["performance", "cos", "zeladoria"]


def test_cartao_leva_so_os_itens_do_canal_e_o_que_estava_na_tela():
    d, _ = ct.validar(dict(OK, itens=["disponibilidade", "ronda"], tela=dict(OK["tela"], ronda="vegetação 3")))
    perf = ct.cartao(d, "Guaratinguetá V", "04/10/2026", "cos")["attachments"][0]["content"]
    fatos = {f["title"]: f["value"] for f in perf["body"][1]["facts"]}
    assert fatos["Contesta"] == "Disponibilidade" and fatos["Dia"] == "04/10/2026"
    assert fatos["Na tela: Disp"] == "95,8%" and fatos["Contato"] == "ana@cliente.com.br"
    assert perf["body"][2]["text"] == OK["mensagem"]
    zel = ct.cartao(d, "Guaratinguetá V", "04/10/2026", "zeladoria")["attachments"][0]["content"]
    assert {f["title"]: f["value"] for f in zel["body"][1]["facts"]}["Contesta"] == "Ronda"


def test_limite_por_endereco_e_por_dia():
    lim = ct.Limite(por_ip=(3, 3600), por_dia=5)
    assert [lim.tenta("a", agora=100) for _ in range(4)] == [True, True, True, False]
    assert lim.tenta("a", agora=100 + 3601)
    assert lim.tenta("b", agora=200) and not lim.tenta("c", agora=201)
    assert lim.tenta("c", agora=100 + 86401)


def test_canais_e_url_vem_do_segredo(monkeypatch):
    monkeypatch.setattr(ct.fonte_api, "segredo", lambda n: "https://fluxo" if n == "THOPEN_TEAMS_PERFORMANCE" else "")
    assert ct.canais() == {"performance": True, "cos": False, "zeladoria": False}
    assert ct.url("performance") == "https://fluxo"


def test_enviar_posta_json_e_recusa_levanta(monkeypatch):
    vistos = []

    class R:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(ct, "_abrir", lambda req, timeout=None: (vistos.append(req), R())[1])
    ct.enviar({"a": 1}, "https://exemplo/fluxo")
    assert vistos[0].get_method() == "POST" and json.loads(vistos[0].data) == {"a": 1}
    R.status = 400
    with pytest.raises(RuntimeError):
        ct.enviar({"a": 1}, "https://exemplo/fluxo")


def test_geracao_e_item_da_performance_com_o_que_o_grafico_mostrava():
    # rodada 5 (Levi, 13/10): a contestação sai da tabela e vai para o gráfico Energia × Irradiação; "adiciona geração
    # na contestação, será direcionado a performance"
    assert list(ct.ITENS)[0] == "geracao" and ct.destinos(["geracao"]) == ["performance"]
    d, e = ct.validar(dict(OK, itens=["geracao"], tela={"geracao": "7.051 kWh", "irradiacao": "2,2 kWh/m²"}))
    assert e is None and d["tela"] == {"geracao": "7.051 kWh", "irradiacao": "2,2 kWh/m²"}
    perf = ct.cartao(d, "Alvares Machado", "06/10/2026", "performance")["attachments"][0]["content"]
    fatos = {f["title"]: f["value"] for f in perf["body"][1]["facts"]}
    assert fatos["Contesta"] == "Geração" and fatos["Na tela: Geração"] == "7.051 kWh"
    assert fatos["Na tela: Irradiação"] == "2,2 kWh/m²"


def test_com_a_pessoa_conectada_so_o_nome():
    # Levi, 15/10/2026: "com a pessoa conectada, na contestação a pessoa não precisa preencher o e-mail, só o nome!" —
    # o contato é o da conta (o e-mail dela ou o usuário), sem conferir formato
    d, erro = ct.validar(dict(OK, contato=""), contato_da_conta="usuário thopen.operacao (conta do painel)")
    assert erro is None and d["contato"] == "usuário thopen.operacao (conta do painel)" and d["nome"] == "Ana Souza"
    assert ct.validar(dict(OK, nome="", contato=""), contato_da_conta="ana@x.com.br")[1] == "Preencha o seu nome."
    # o contato digitado não vale com a conta: o da conta vence
    assert ct.validar(dict(OK, contato="outro@x.com"), contato_da_conta="ana@x.com.br")[0]["contato"] == "ana@x.com.br"
    # sem conta, como antes: nome e um contato válido
    assert ct.validar(dict(OK, contato=""))[1] == "Preencha o nome e um contato."
