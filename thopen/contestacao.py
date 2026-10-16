# -*- coding: utf-8 -*-
"""Contestação do cliente sobre um dia do Diário (rodada 4, Levi 09/10/2026: "o cliente poderá contestar um ou mais
números, podendo contestar disponibilidade, desligamento, string, tracker ou ronda. Ronda notificará o time de
zeladoria do teams"). Substituiu a "Dúvida sobre esta ronda" da janela das rondas (rodada 3). Rodada 5 (13/10): a
contestação abre pelo clique no dia do gráfico Energia × Irradiação (não mais pelo "!" da tabela) e ganha a Geração
("adiciona geração na contestação, será direcionado a performance").

O aviso vai para canais do Teams por fluxos do app Workflows ("Enviar alertas de webhook para um canal"): geração,
string e tracker → O&M › Performance (THOPEN_TEAMS_PERFORMANCE); disponibilidade e desligamento → COS
(THOPEN_TEAMS_COS; Levi, 15/10/2026: "Disponibilidade e desligamento vão para o setor de COS"); ronda → O&M ›
Zeladoria (THOPEN_TEAMS_ZELADORIA). As URLs dos fluxos são segredo (quem as tem posta no canal) e vêm do ambiente ou do
.env da raiz (fonte_api.segredo). Item cujo canal não está configurado não aparece na tela: nunca dizer "enviada" sem
ter avisado ninguém. E-mail não serve: o envio do servidor está barrado no tenant desde 23/09.

A resposta ao cliente é por fora: o formulário pede nome e e-mail ou telefone. Nada é guardado aqui — o registro é a
mensagem no canal; se o Teams recusar, o cliente vê o erro e tenta de novo.

O 5080 é público, sem senha: limite por endereço (3 por hora) e no total (40 por dia), campo-isca contra robô, texto
curto. O endereço vem do CF-Connecting-IP (o túnel da Cloudflare põe; atrás dele o remote_addr é sempre 127.0.0.1).
"""
import json
import re
import threading
import time
import urllib.request

import fonte_api

VARIAVEIS = {"performance": "THOPEN_TEAMS_PERFORMANCE", "cos": "THOPEN_TEAMS_COS", "zeladoria": "THOPEN_TEAMS_ZELADORIA"}
CANAL = {"performance": "Performance", "cos": "COS", "zeladoria": "Zeladoria"}
# item da tela → canal. A ordem é a dos checkboxes
ITENS = {"geracao": "performance", "disponibilidade": "cos", "desligamento": "cos",
         "string": "performance", "tracker": "performance", "ronda": "zeladoria"}
ROTULO = {"geracao": "Geração", "disponibilidade": "Disponibilidade", "desligamento": "Desligamento",
          "string": "String", "tracker": "Tracker", "ronda": "Ronda"}
# o que o cliente via naquele dia (gráfico e tabelas): só contexto do cartão, na ordem em que vai
TELA = (("geracao", "Geração"), ("irradiacao", "Irradiação"), ("disp", "Disp"), ("tracker", "Tracker parado"),
        ("string", "String sem corrente"), ("comentario", "Comentário"), ("ronda", "Ronda"))
MAX = {"nome": 80, "contato": 120, "mensagem": 1000}
NOMES = {"nome": "nome", "contato": "contato", "mensagem": "mensagem"}
TELA_MAX = 400                    # cada campo do que estava na tela (TELA): só contexto do cartão
POR_IP = (3, 3600)
POR_DIA = 40
TIMEOUT = 15
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def url(destino):
    return fonte_api.segredo(VARIAVEIS[destino])


def canais():
    """{performance: bool, cos: bool, zeladoria: bool} — o que a tela pode oferecer."""
    return {k: bool(url(k)) for k in VARIAVEIS}


def destinos(itens):
    """Os canais dos itens marcados, na ordem fixa (Performance, COS, Zeladoria)."""
    alvo = {ITENS[i] for i in itens}
    return [k for k in VARIAVEIS if k in alvo]


def validar(corpo, contato_da_conta=None):
    """(dados limpos, None) ou (None, mensagem para o cliente). "isca" = o campo escondido veio preenchido (robô).
    `contato_da_conta` (login ligado, 15/10/2026: "com a pessoa conectada, na contestação a pessoa não precisa preencher
    o e-mail, só o nome!"): o contato é o da conta — o e-mail dela ou o usuário — e a pessoa só escreve o nome."""
    b = corpo or {}
    if str(b.get("site") or "").strip():
        return None, "isca"
    itens = [i for i in ITENS if i in (b.get("itens") or [])]
    if not itens:
        return None, "Marque ao menos um item para contestar."
    d = {"nome": " ".join(str(b.get("nome") or "").split()),
         "contato": " ".join(str(contato_da_conta or b.get("contato") or "").split()),
         "mensagem": str(b.get("mensagem") or "").strip(), "itens": itens}
    if contato_da_conta and not d["nome"]:
        return None, "Preencha o seu nome."
    if not d["nome"] or not d["contato"]:
        return None, "Preencha o nome e um contato."
    for k, n in MAX.items():
        if len(d[k]) > n:
            return None, "O campo %s passa de %d caracteres." % (NOMES[k], n)
    if not contato_da_conta and not (_EMAIL.match(d["contato"]) or len(re.sub(r"\D", "", d["contato"])) >= 10):
        return None, "Informe um e-mail ou um telefone com DDD."
    tela = b.get("tela") if isinstance(b.get("tela"), dict) else {}
    d["tela"] = {k: " ".join(str(tela.get(k) or "").split())[:TELA_MAX]
                 for k, _ in TELA if tela.get(k) not in (None, "")}
    return d, None


class Limite:
    """Quantas contestações cada endereço manda por janela, e quantas o painel aceita por dia no total."""

    def __init__(self, por_ip=POR_IP, por_dia=POR_DIA):
        self.n_ip, self.janela = por_ip
        self.n_dia = por_dia
        self._ip, self._dia, self._trava = {}, [], threading.Lock()

    def tenta(self, ip, agora=None):
        agora = time.time() if agora is None else agora
        with self._trava:
            self._dia = [t for t in self._dia if agora - t < 86400]
            vistos = [t for t in self._ip.get(ip, []) if agora - t < self.janela]
            if len(vistos) >= self.n_ip or len(self._dia) >= self.n_dia:
                self._ip[ip] = vistos
                return False
            self._ip[ip] = vistos + [agora]
            self._dia.append(agora)
            return True


def cartao(d, usina, data_txt, destino):
    """A mensagem do canal: um Adaptive Card (o formato que o fluxo do Workflows posta). Cada canal recebe só os itens
    dele, e o que o cliente viu na linha vai junto como contexto."""
    meus = [ROTULO[i] for i in d["itens"] if ITENS[i] == destino]
    t = d.get("tela") or {}
    fatos = [{"title": "Usina", "value": usina}, {"title": "Dia", "value": data_txt},
             {"title": "Contesta", "value": ", ".join(meus)}]
    tela = [(rot, t.get(k)) for k, rot in TELA if t.get(k)]
    fatos += [{"title": "Na tela: " + k, "value": v} for k, v in tela]
    fatos += [{"title": "Nome", "value": d["nome"]}, {"title": "Contato", "value": d["contato"]}]
    corpo = [{"type": "TextBlock", "size": "Medium", "weight": "Bolder", "wrap": True,
              "text": "Contestação do cliente — Dashboard Thopen"},
             {"type": "FactSet", "facts": fatos}]
    if d.get("mensagem"):
        corpo.append({"type": "TextBlock", "wrap": True, "text": d["mensagem"]})
    return {"type": "message", "attachments": [{
        "contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None,
        "content": {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard",
                    "version": "1.4", "body": corpo}}]}


def _abrir(req, timeout=TIMEOUT):
    return urllib.request.urlopen(req, timeout=timeout)


def enviar(payload, destino_url):
    """POST do cartão no fluxo. Levanta se o Teams não aceitar (o fluxo do Workflows responde 202)."""
    req = urllib.request.Request(destino_url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    with _abrir(req) as r:
        st = getattr(r, "status", 200)
    if not 200 <= st < 300:
        raise RuntimeError("o Teams respondeu %s" % st)
