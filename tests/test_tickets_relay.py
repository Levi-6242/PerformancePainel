# -*- coding: utf-8 -*-
"""O relay de escrita dos tickets (plataforma/tickets_relay.py), sem rede.

O que se tranca aqui é o que faz o arranjo valer: quem grava é identificado pelo Fracttal (e não
pelo que o app diz), só as abas da lista aceitam escrita, o nome carimbado no diário é o
VERIFICADO, cada gravação deixa rastro, e a URL do túnel é publicada de forma idempotente.

Importa o módulo direto, sem o `app.py`: são funções puras com a rede injetável.
"""
import base64
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "plataforma"))
import tickets_relay as tr  # noqa: E402


def _jwt(email="levi@gridco.com.br", exp=None):
    """Um JWT de mentira com as claims que o relay lê. A assinatura não importa aqui: quem prova
    a assinatura é o Fracttal, e o Fracttal está dublado."""
    payload = {"email": email, "exp": exp if exp is not None else time.time() + 3600}
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return "%s.%s.assinatura" % (b({"alg": "HS256"}), b(payload))


def _fracttal(pessoas=(), recusa=None):
    """Dublê do rpc/proxy: `recusa` = status HTTP para recusar; senão devolve o personnel."""
    def chamar(method, params):
        if recusa:
            return recusa, None
        assert method == tr.RPC_PERSONNEL
        start = int(params.get("start") or 0)
        lim = int(params.get("limit") or 100)
        return 200, [{"result": {"data": list(pessoas)[start:start + lim]}}]
    return chamar


@pytest.fixture(autouse=True)
def limpa_caches():
    tr._ident_cache.clear()
    tr._nome_cache.clear()
    yield
    tr._ident_cache.clear()
    tr._nome_cache.clear()


@pytest.fixture
def log(tmp_path, monkeypatch):
    p = tmp_path / "tickets_relay.log"
    monkeypatch.setattr(tr, "LOG", str(p))
    return p


# ── identificar ───────────────────────────────────────────────────────────────────────────
def test_identifica_pelo_fracttal_e_acha_o_nome():
    pessoas = [{"account_email": "outro@x.com", "full_name": "Outro"},
               {"account_email": "Levi@gridco.com.br", "full_name": "Levi Maia"}]
    email, nome = tr.identificar(_jwt(), chamar=_fracttal(pessoas))
    assert (email, nome) == ("levi@gridco.com.br", "Levi Maia")


def test_sem_jwt_nao_entra():
    with pytest.raises(tr.NaoAutenticado):
        tr.identificar("", chamar=_fracttal())
    with pytest.raises(tr.NaoAutenticado):
        tr.identificar("nao.e.jwt.de.verdade", chamar=_fracttal())


def test_jwt_vencido_nao_entra_mesmo_sem_perguntar_ao_fracttal():
    perguntou = []
    with pytest.raises(tr.NaoAutenticado) as e:
        tr.identificar(_jwt(exp=time.time() - 10),
                       chamar=lambda m, p: perguntou.append(1) or (200, [{"result": {}}]))
    assert "expirou" in str(e.value) and perguntou == []


def test_fracttal_recusando_nao_entra():
    with pytest.raises(tr.NaoAutenticado):
        tr.identificar(_jwt(), chamar=_fracttal(recusa=401))


def test_sessao_morta_com_http_200_nao_entra():
    """O Fracttal responde 200 com success:false quando a sessão foi encerrada — o app já tinha
    aprendido isso; o relay não pode aceitar."""
    def chamar(method, params):
        return 200, [{"result": {"success": False, "message": "USER_NOT_LOGIN"}}]
    with pytest.raises(tr.NaoAutenticado):
        tr.identificar(_jwt(), chamar=chamar)


def test_identidade_conferida_nao_bate_no_fracttal_a_cada_linha():
    """Um renomear de 147 linhas são 147 gravações: reconferir cada uma seria 147 idas ao
    Fracttal. A identidade vale `_IDENT_TTL`."""
    vezes = []
    pessoas = [{"account_email": "levi@gridco.com.br", "full_name": "Levi Maia"}]
    base = _fracttal(pessoas)

    def chamar(m, p):
        vezes.append(1)
        return base(m, p)
    j = _jwt()
    tr.identificar(j, chamar=chamar, agora=1000.0)
    n = len(vezes)
    for _ in range(146):
        tr.identificar(j, chamar=chamar, agora=1000.0 + 5)
    assert len(vezes) == n, "reconferiu no Fracttal dentro do prazo"
    tr.identificar(j, chamar=chamar, agora=1000.0 + tr._IDENT_TTL + 1)
    assert len(vezes) > n, "passou o prazo e não reconferiu"


def test_sem_nome_no_cadastro_vale_o_email():
    email, nome = tr.identificar(_jwt("ninguem@x.com"), chamar=_fracttal([]))
    assert nome == "ninguem@x.com"


# ── encaminhar ────────────────────────────────────────────────────────────────────────────
QUEM = ("levi@gridco.com.br", "Levi Maia")


def test_aba_fora_da_lista_nao_chega_ao_banco(log):
    chamadas = []
    with pytest.raises(tr.AbaForaDaLista):
        tr.encaminhar("PUT", 999, 1, {"headers": ["Usina"], "values": ["X"]}, QUEM, "tok",
                      enviar=lambda *a: chamadas.append(a) or (200, "{}"))
    assert chamadas == []


def test_put_vai_para_a_linha_certa_e_devolve_a_resposta_do_banco(log):
    vistas = []

    def enviar(metodo, url, corpo):
        vistas.append((metodo, url, corpo))
        return 200, '{"row_number": 154}'
    st, txt = tr.encaminhar("PUT", 128, 154, {"headers": ["Usina"], "values": ["PTL200"]},
                            QUEM, "tok", enviar=enviar)
    assert (st, txt) == (200, '{"row_number": 154}')
    assert vistas[0][0] == "PUT" and vistas[0][1].endswith("/api/sheets/128/rows/154")


def test_delete_sem_corpo_e_post_sem_linha(log):
    vistas = []
    enviar = lambda m, u, c: vistas.append((m, u, c)) or (200, "")
    tr.encaminhar("DELETE", 123, 7, None, QUEM, "tok", enviar=enviar)
    tr.encaminhar("POST", 387, None, {"headers": ["quando"], "values": ["x"]}, QUEM, "tok",
                  enviar=enviar)
    assert vistas[0][:2] == ("DELETE", tr.API + "/api/sheets/123/rows/7")
    assert vistas[1][:2] == ("POST", tr.API + "/api/sheets/387/rows")
    with pytest.raises(ValueError):
        tr.encaminhar("POST", 387, 5, {}, QUEM, "tok", enviar=enviar)


def test_o_quem_do_diario_e_o_nome_VERIFICADO_e_nao_o_que_o_app_mandou(log):
    """O app mandava o usuário do Windows. Qualquer um escreve qualquer coisa ali."""
    vistas = []
    corpo = {"headers": ["quando", "quem", "aba"], "values": ["2026-09-07", "LEVIMA", "Strings"]}
    tr.encaminhar("POST", 387, None, corpo, QUEM, "tok",
                  enviar=lambda m, u, c: vistas.append(c) or (200, "{}"))
    assert vistas[0]["values"][1] == "Levi Maia"
    assert corpo["values"][1] == "LEVIMA", "mexeu no dicionário de quem chamou"


def test_linha_sem_coluna_quem_passa_intacta(log):
    corpo = {"headers": ["Usina", "Causa raiz"], "values": ["PTL200", "x"]}
    vistas = []
    tr.encaminhar("PUT", 128, 1, corpo, QUEM, "tok", enviar=lambda m, u, c: vistas.append(c) or (200, ""))
    assert vistas[0] == corpo


def test_toda_gravacao_deixa_rastro_com_quem_e_o_que(log):
    corpo = {"headers": ["Usina", "Causa raiz", "Comentários gerais"],
             "values": ["PTL200", "Cabo rompido", "x" * 500]}
    tr.encaminhar("PUT", 128, 154, corpo, QUEM, "tok", enviar=lambda *a: (200, ""))
    linha = log.read_text(encoding="utf-8").strip()
    assert "Levi Maia <levi@gridco.com.br>" in linha
    assert "PUT tickets_performance/Strings indisp linha 154" in linha
    assert "Usina=PTL200" in linha and "Causa=Cabo rompido" in linha
    assert "x" * 100 not in linha, "o comentário inteiro foi para o log"


def test_o_token_nao_vai_para_o_log_nem_para_o_app(log):
    st, txt = tr.encaminhar("PUT", 128, 1, {"headers": ["Usina"], "values": ["A"]}, QUEM,
                            "TOKEN-SECRETO", enviar=lambda *a: (200, "ok"))
    assert "TOKEN-SECRETO" not in log.read_text(encoding="utf-8")
    assert "TOKEN-SECRETO" not in txt


def test_criar_aba_so_no_workbook_permitido(log):
    with pytest.raises(tr.AbaForaDaLista):
        tr.criar_aba("plataforma_estado", {"sheet_name": "x"}, QUEM, "tok", enviar=lambda *a: (200, ""))
    st, _ = tr.criar_aba("tickets_performance", {"sheet_name": "Edicoes do app v4"}, QUEM, "tok",
                         enviar=lambda *a: (201, "{}"))
    assert st == 201


# ── publicar a URL do túnel ───────────────────────────────────────────────────────────────
class _Banco:
    """Dublê do banco para a publicação: guarda abas e linhas em memória."""

    def __init__(self, com_aba=True, linhas=()):
        self.abas = ([{"id": 500, "workbook_key": "os_creator", "sheet_name": "plataforma"}]
                     if com_aba else []) + [{"id": 415, "workbook_key": "os_creator", "sheet_name": "temas"}]
        self.linhas = [{"row_number": i + 1, "values": list(v)} for i, v in enumerate(linhas)]
        self.escritas = []

    def __call__(self, metodo, url, corpo=None, token=None):
        if metodo == "GET" and url.endswith("/api/sheets"):
            return 200, self.abas
        if metodo == "GET" and "/rows" in url:
            return 200, {"rows": self.linhas}
        if metodo == "POST" and url.endswith("/workbooks/os_creator/sheets"):
            self.abas.append({"id": 501, "workbook_key": "os_creator", "sheet_name": corpo["sheet_name"]})
            self.escritas.append(("CRIAR", corpo))
            return 201, {"id": 501}
        self.escritas.append((metodo, url.rsplit("/", 1)[-1], corpo["values"], token))
        return 200, {}


def test_publica_criando_a_aba_quando_nao_existe(log):
    b = _Banco(com_aba=False)
    out = tr.publicar_url_tunel("https://abc.trycloudflare.com/", "tok", http=b)
    assert out["sheet"] == 501 and out["url"] == "https://abc.trycloudflare.com"
    assert b.escritas[0][0] == "CRIAR"
    assert [e[2][0] for e in b.escritas[1:]] == ["tunnel_url", "quando"]


def test_publica_atualizando_a_chave_que_ja_existe(log):
    b = _Banco(linhas=[("tunnel_url", "https://velha.trycloudflare.com"), ("quando", "ontem")])
    tr.publicar_url_tunel("https://nova.trycloudflare.com", "tok", http=b)
    metodos = [(e[0], e[1]) for e in b.escritas]
    assert metodos == [("PUT", "1"), ("PUT", "2")], "deveria atualizar as duas linhas, não duplicar"
    assert b.escritas[0][2] == ["tunnel_url", "https://nova.trycloudflare.com"]


def test_publicacao_usa_o_token_do_servidor(log):
    b = _Banco(linhas=[("tunnel_url", "x"), ("quando", "y")])
    tr.publicar_url_tunel("https://n.trycloudflare.com", "tok-servidor", http=b)
    assert all(e[3] == "tok-servidor" for e in b.escritas)


def test_url_invalida_nao_publica(log):
    b = _Banco()
    with pytest.raises(ValueError):
        tr.publicar_url_tunel("", "tok", http=b)
    assert b.escritas == []
