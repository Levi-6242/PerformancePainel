# -*- coding: utf-8 -*-
"""Relay de escrita dos tickets: o OS Creator manda a alteração para cá, e a plataforma grava.

POR QUE EXISTE (Levi, 07/09/2026: "manda uma mensagem para um canto seguro onde tem o token")
O GRIDCO_SQL_TOKEN grava no banco INTEIRO — os três workbooks. Distribuí-lo por máquina era
frágil e perigoso: a máquina do próprio Levi ficou uma semana sem ele (o arquivo "existia" só
na camada virtualizada de um agente) e toda gravação de ticket falhou em silêncio; e o
instalador do GitHub, que o auto-update baixa, não pode carregá-lo — o repositório é público.
Aqui o token fica num lugar só: esta máquina, no `tokens.txt` da raiz (`estado_backup._token`).

QUEM ESTÁ GRAVANDO
O app manda o JWT do login do Fracttal — o mesmo que já usa para criar OS — no header
`X-Fracttal-JWT`. A plataforma confere esse JWT numa chamada barata ao RPC do Fracttal (se o
Fracttal aceita, a pessoa está logada) e tira o e-mail das claims. Nenhum segredo novo para
distribuir: a identidade é a que a pessoa já tem. O JWT NUNCA é logado nem guardado — é
conferido e descartado; o cache de identidade guarda um hash dele, não ele.

O QUE PODE GRAVAR
Só as abas de `ABAS`. A trava que no app era `SHEETS_LIBERADAS` passa a valer AQUI, onde
ninguém edita por engano: sheet_id fora da lista é recusado com o token intacto.

O NOME DE QUEM MUDOU
Quando a linha tem uma coluna `quem` (o diário de edições), o valor é SUBSTITUÍDO pelo nome
verificado — o app mandava o usuário do Windows, que qualquer um escreve. E toda gravação vira
uma linha em `plataforma/logs/tickets_relay.log`: quando, quem, operação, aba, linha, resumo.
Apagar ocorrência e trocar usina não entram no diário (ele guarda edição de campos); o log
daqui é o único rastro delas.

ONDE O APP ACHA A PLATAFORMA
Ela não tem endereço fixo: é um quick tunnel do Cloudflare, URL aleatória a cada subida. Então
a plataforma PUBLICA a URL atual no banco — workbook `os_creator`, aba `plataforma`, chave/valor
— sempre que ela muda (`publicar_url_tunel`), e o app a lê de lá, aberto, antes de gravar. No
workbook `os_creator` e não no `plataforma_estado`: aquele é substituído inteiro pelo backup
(`estado_backup.publicar`), e uma aba a mais lá sumiria no ciclo seguinte.
"""
import base64
import datetime as _dt
import hashlib
import io
import json
import os
import threading
import time
import uuid

import requests

API = os.environ.get("GRIDCO_DB_API", "https://app.gridco.com.br/db_performace").rstrip("/")
RPC_PROXY_URL = "https://app.fracttal.com/rpc/proxy"
RPC_PERSONNEL = "personnel.personnel_list"
TIMEOUT = 30

# sheet_id → apelido. Só o que estiver aqui aceita escrita. 374 é a aba descartável de teste.
ABAS = {123: "tickets_performance/Trackers",
        128: "tickets_performance/Strings indisp",
        387: "tickets_performance/Edicoes do app",
        # AS TRÊS GERAÇÕES DO DIÁRIO (14/09/2026). O app não usa mais a 387: o `garantir_aba` do
        # `tickets_diario` procura a aba PELO NOME e, quando o formato ganha coluna, cria a
        # seguinte — "Edicoes do app v2", depois "v3". Hoje ele grava na 399.
        #
        # ISSO QUEBROU O VÍNCULO OS↔OCORRÊNCIA POR UMA SEMANA, sem ninguém ver. Desde 07/09 a
        # escrita sai por aqui, e aqui só a 387 era aceita: a linha da ocorrência entrava (123 e
        # 128 estão na lista) e o registro do diário era recusado logo na entrada, ANTES do log —
        # por isso nem rastro ficou. O erro voltava como "linha criada, mas a OS não ficou
        # vinculada", uma frase no fim de uma caixa que ninguém lê. Medido em 14/09: 34 OS de
        # String e Tracker criadas em dez dias, ZERO com vínculo no diário.
        #
        # QUANDO NASCER A v4, ELA PRECISA ENTRAR AQUI. Enquanto a lista for de números, o app
        # cria a aba sozinho e o relay não fica sabendo.
        398: "tickets_performance/Edicoes do app v2",
        399: "tickets_performance/Edicoes do app v3",
        374: "teste/FASE2_Trackers"}
# onde o app pode CRIAR aba (o diário v4, quando precisar de coluna nova — a API não alarga aba)
WORKBOOKS_ABA_NOVA = {"tickets_performance"}

WORKBOOK_APP = "os_creator"       # onde a URL do túnel é publicada
ABA_PLATAFORMA = "plataforma"     # chave/valor: tunnel_url, quando

_AQUI = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(_AQUI, "logs", "tickets_relay.log")

_IDENT_TTL = 600            # s: uma identidade conferida vale isto sem reconferir no Fracttal
_ident_cache = {}           # sha256(jwt) → (vale_ate, email, nome)
_nome_cache = {}            # email → nome de exibição
_lock = threading.Lock()


class NaoAutenticado(RuntimeError):
    """O JWT não veio, está vencido, ou o Fracttal não o aceitou."""


class AbaForaDaLista(RuntimeError):
    """sheet_id (ou workbook) que o relay não toca."""


# ── quem é ────────────────────────────────────────────────────────────────────────────────
def _claims(jwt: str) -> dict:
    p = jwt.split(".")[1]
    p += "=" * (-len(p) % 4)
    return json.loads(base64.urlsafe_b64decode(p.encode()))


def _rpc_headers(jwt: str) -> dict:
    # os mesmos headers que o app manda: sem `Origin` e `x-version` o proxy do Fracttal recusa
    return {"Authorization": "Bearer " + jwt, "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://app.fracttal.com", "x-version": "Fracttal/5.7.02 web"}


def _rpc(jwt: str, method: str, params: dict, chamar=None):
    """Uma chamada ao rpc/proxy com o JWT da PESSOA. Devolve o `result`; `NaoAutenticado` quando
    o Fracttal recusa (401/403, ou `success:false` de sessão — que vem com HTTP 200)."""
    if chamar is not None:
        status, j = chamar(method, params)
    else:
        body = [{"id": str(uuid.uuid4()), "jsonrpc": "2.0", "method": method, "params": params}]
        r = requests.post(RPC_PROXY_URL, headers=_rpc_headers(jwt), json=body, timeout=TIMEOUT)
        status = r.status_code
        try:
            j = r.json()
        except ValueError:
            j = None
    if status in (401, 403):
        raise NaoAutenticado("o Fracttal recusou o login (HTTP %d) — faça login de novo no app"
                             % status)
    if status >= 400 or j is None:
        raise RuntimeError("Fracttal RPC %s: HTTP %s" % (method, status))
    rec = j[0] if isinstance(j, list) and j else j
    if isinstance(rec, dict) and rec.get("error"):
        err = rec["error"]
        raise RuntimeError("Fracttal RPC %s: %s" % (
            method, str(err.get("message") if isinstance(err, dict) else err)[:160]))
    result = rec.get("result") if isinstance(rec, dict) else rec
    if isinstance(result, dict) and result.get("success") is False:
        msg = str(result.get("message") or "").upper()
        if any(k in msg for k in ("NOT_LOGIN", "INVALID_TOKEN", "SESSION", "TOKEN_EXPIRED",
                                  "UNAUTHORIZED", "NOT_AUTH")):
            raise NaoAutenticado("a sessão do Fracttal expirou ou foi encerrada — faça login "
                                 "de novo no app")
    return result


def identificar(jwt: str, chamar=None, agora=None) -> tuple:
    """(email, nome) de quem mandou o JWT — ou `NaoAutenticado`.

    Três provas, nesta ordem: forma (3 partes e claims legíveis), validade (`exp`) e o Fracttal
    (uma página de 1 do personnel — a chamada mais barata que exige sessão). A identidade
    conferida vale `_IDENT_TTL` sem reconferir, para um renomear de 147 linhas não bater 147
    vezes no Fracttal."""
    jwt = (jwt or "").strip()
    if jwt.count(".") != 2:
        raise NaoAutenticado("sem login do Fracttal: o app precisa estar logado para gravar")
    chave = hashlib.sha256(jwt.encode()).hexdigest()
    t = time.time() if agora is None else agora
    with _lock:
        c = _ident_cache.get(chave)
        if c and c[0] > t:
            return c[1], c[2]
    try:
        claims = _claims(jwt)
    except Exception:
        raise NaoAutenticado("o login do Fracttal veio ilegível — faça login de novo no app")
    email = str(claims.get("email") or "").strip().lower()
    exp = claims.get("exp")
    if exp and float(exp) < t:
        raise NaoAutenticado("o login do Fracttal expirou — faça login de novo no app")
    if not email:
        raise NaoAutenticado("o login do Fracttal não traz o e-mail")
    _rpc(jwt, RPC_PERSONNEL, {"page": 1, "limit": 1, "start": 0, "append": True,
                              "filter": [], "sort": []}, chamar=chamar)     # a prova de vida
    nome = _nome(jwt, email, chamar=chamar)
    with _lock:
        _ident_cache[chave] = (t + _IDENT_TTL, email, nome)
    return email, nome


def _nome(jwt: str, email: str, chamar=None) -> str:
    """Nome de exibição pelo personnel — a mesma varredura que o app faz —, cacheado por e-mail.
    Sem nome no cadastro, vale o e-mail: melhor que um nome inventado."""
    if email in _nome_cache:
        return _nome_cache[email]
    nome, start = "", 0
    while True:
        res = _rpc(jwt, RPC_PERSONNEL, {"page": start // 100 + 1, "limit": 100, "start": start,
                                        "append": True, "filter": [], "sort": []}, chamar=chamar)
        data = res.get("data") if isinstance(res, dict) else res
        data = data if isinstance(data, list) else []
        for p in data:
            if str(p.get("account_email") or p.get("email") or "").strip().lower() == email:
                nome = str(p.get("full_name") or p.get("name") or "").strip()
                break
        start += 100
        if nome or len(data) < 100:
            break
    nome = nome or email
    _nome_cache[email] = nome
    return nome


# ── gravar em nome de alguém ──────────────────────────────────────────────────────────────
def _resumo(corpo) -> str:
    """Um pedaço legível da linha para o log: usina, ativo, status, causa. Nunca a linha inteira
    — os comentários são longos e o log serve para achar, não para reler."""
    try:
        h, v = corpo.get("headers") or [], corpo.get("values") or []
        d = {str(c): v[i] for i, c in enumerate(h) if i < len(v) and str(c or "").strip()}
    except Exception:
        return ""
    partes = []
    for c in ("Usina", "Nº do tracker / Identificação", "Inversor", "Status do ticket",
              "Causa raiz", "aba", "linha", "quem"):
        if d.get(c) not in (None, ""):
            partes.append("%s=%s" % (c.split(" ")[0], str(d[c])[:40]))
    return " · ".join(partes)


def _log(linha: str):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with io.open(LOG, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except OSError:
        pass


def carimbar_quem(corpo, nome: str):
    """Se a linha tem coluna `quem`, o valor passa a ser o nome VERIFICADO — o que o app mandou
    (usuário do Windows) não vale como identidade."""
    if not isinstance(corpo, dict):
        return corpo
    h = list(corpo.get("headers") or [])
    if "quem" not in h:
        return corpo
    vals = list(corpo.get("values") or [])
    i = h.index("quem")
    while len(vals) <= i:
        vals.append("")
    vals[i] = nome
    return dict(corpo, values=vals)


def _headers_banco(token: str) -> dict:
    return {"Authorization": "Bearer " + token, "Content-Type": "application/json"}


def encaminhar(metodo: str, sheet_id: int, row, corpo, quem: tuple, token: str,
               enviar=None, agora=None) -> tuple:
    """Grava no banco em nome de `quem` = (email, nome). → (status HTTP, texto da resposta).

    A resposta do banco volta INTEIRA para o app: é ela que ele confere (o eco da linha gravada)
    — o relay não reinterpreta nem esconde erro."""
    if sheet_id not in ABAS:
        raise AbaForaDaLista("a aba %s não está na lista de escrita do relay" % sheet_id)
    metodo = (metodo or "").upper()
    if metodo not in ("PUT", "POST", "DELETE"):
        raise ValueError("método %r" % metodo)
    if (metodo == "POST") != (row is None):
        raise ValueError("POST é sem linha; PUT e DELETE, com linha")
    email, nome = quem
    if corpo is not None:
        corpo = carimbar_quem(corpo, nome)
    url = "%s/api/sheets/%s/rows" % (API, sheet_id) + ("" if row is None else "/%s" % row)
    if enviar is not None:
        status, texto = enviar(metodo, url, corpo)
    else:
        r = requests.request(metodo, url, headers=_headers_banco(token), json=corpo,
                             timeout=TIMEOUT)
        status, texto = r.status_code, r.text
    quando = (agora or _dt.datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    _log("%s | %s <%s> | %s %s linha %s | HTTP %s | %s" % (
        quando, nome, email, metodo, ABAS[sheet_id], "nova" if row is None else row, status,
        _resumo(corpo) if corpo else ""))
    return status, texto


def criar_aba(workbook: str, corpo, quem: tuple, token: str, enviar=None, agora=None) -> tuple:
    """Cria uma aba nova num workbook permitido (o diário v4, um dia). → (status, texto)."""
    if workbook not in WORKBOOKS_ABA_NOVA:
        raise AbaForaDaLista("o relay não cria aba no workbook %r" % workbook)
    email, nome = quem
    url = "%s/api/workbooks/%s/sheets" % (API, workbook)
    if enviar is not None:
        status, texto = enviar("POST", url, corpo)
    else:
        r = requests.post(url, headers=_headers_banco(token), json=corpo, timeout=TIMEOUT)
        status, texto = r.status_code, r.text
    quando = (agora or _dt.datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    _log("%s | %s <%s> | CRIAR ABA %s/%s | HTTP %s" % (
        quando, nome, email, workbook, (corpo or {}).get("sheet_name"), status))
    return status, texto


# ── onde o app acha a plataforma ──────────────────────────────────────────────────────────
def _http(metodo, url, corpo=None, token=None):
    h = _headers_banco(token) if token else {}
    r = requests.request(metodo, url, headers=h, json=corpo, timeout=TIMEOUT)
    try:
        j = r.json()
    except ValueError:
        j = None
    return r.status_code, j


def publicar_url_tunel(url: str, token: str, http=None, agora=None) -> dict:
    """Grava a URL atual do túnel em `os_creator/plataforma` (chave/valor), criando a aba se não
    existir. Idempotente: chave existente é atualizada (PUT), nova é acrescentada (POST).

    `http(metodo, url, corpo, token) -> (status, json)` é injetável para o teste não sair para
    a rede."""
    http = http or _http
    url = (url or "").strip().rstrip("/")
    if not url.startswith("http"):
        raise ValueError("URL do túnel inválida: %r" % url)
    st, abas = http("GET", API + "/api/sheets")
    if st != 200 or not isinstance(abas, list):
        raise RuntimeError("não consegui listar as abas do banco (HTTP %s)" % st)
    sid = None
    for a in abas:
        if a.get("workbook_key") == WORKBOOK_APP and a.get("sheet_name") == ABA_PLATAFORMA:
            sid = a.get("id")
            break
    if sid is None:
        st, nova = http("POST", "%s/api/workbooks/%s/sheets" % (API, WORKBOOK_APP),
                        {"sheet_name": ABA_PLATAFORMA, "headers": ["chave", "valor"]}, token)
        if st not in (200, 201) or not isinstance(nova, dict):
            raise RuntimeError("não consegui criar a aba %s (HTTP %s)" % (ABA_PLATAFORMA, st))
        sid = nova.get("id")
    st, pag = http("GET", "%s/api/sheets/%s/rows?limit=100" % (API, sid))
    linhas = (pag.get("rows") if isinstance(pag, dict) else pag) or []
    onde = {}
    for r in linhas:
        v = r.get("values") or []
        if v:
            onde[str(v[0])] = r.get("row_number")
    quando = (agora or _dt.datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    for chave, valor in (("tunnel_url", url), ("quando", quando)):
        corpo = {"values": [chave, valor], "headers": ["chave", "valor"]}
        if chave in onde:
            st, _ = http("PUT", "%s/api/sheets/%s/rows/%s" % (API, sid, onde[chave]), corpo, token)
        else:
            st, _ = http("POST", "%s/api/sheets/%s/rows" % (API, sid), corpo, token)
        if st not in (200, 201):
            raise RuntimeError("não consegui gravar %s (HTTP %s)" % (chave, st))
    _log("%s | plataforma | URL do túnel publicada: %s" % (quando, url))
    return {"sheet": sid, "url": url, "quando": quando}
