# -*- coding: utf-8 -*-
"""Comentários das usinas (03/11/2026): quem escreve, quem apaga e a lista da tela Comentários.

Levi, 03/11/2026: "Gostaria de um sistema mais sofisticado de comentários! Ao comentar em tempo real não precisar
digitar o nome, já puxa automático. Ter um campo na performance de Comentários."

O dado continua onde sempre esteve: o `comments_thread` do `ufv_state.json` ({chave: [{nick, texto, ts}]}), que o
`estado_backup` copia ao banco (aba `comentarios`: chave, autor, quando, texto). Nada novo vai ao banco. O que muda:

- **o autor**: com identidade na sessão (o passe do Nexus, ou o login Microsoft), quem diz o nome é o SERVIDOR, e o
  e-mail fica no item (`email`) para saber de quem é. O e-mail mora só no arquivo: não vai à cópia do banco (o extrator
  dela leva nick, ts e texto) nem às telas (`para_tela` tira). Sem identidade (a senha compartilhada, ou a senha de
  administrador do Nexus, que não é uma pessoa), o nick digitado, como sempre foi;
- **o apagar**: com identidade, só o próprio comentário (pelo e-mail) ou o administrador do Nexus; sem identidade, como
  antes (a equipe confia na equipe);
- **a tela Comentários** (`/painel/comentarios`): todos os comentários, mais novos primeiro, com a usina pelo nome.

Este módulo é PURO (não importa Flask nem o app), como o `porta_nexus`: o `app.py` só o liga às rotas e às caches.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime

# A chave de um comentário é `<prefixo>:<plant_id>`: o prefixo diz a fonte da TELA em que ele foi escrito (o `VKEY` do
# Monitoramento, o `KEYPFX` do Painel NOC e do Diagnóstico), o plant_id é o id da usina NAQUELA fonte. A mesma usina em
# duas abas (API PV e Thopen pelo banco) tem duas conversas. Cada prefixo com o nome da fonte para a tela e o `?fonte=`
# do Monitoramento que abre a aba dela. `so` é o SunOp: o Painel NOC grava com ele a Athon E a Axis (o `KEYPFX` dele),
# o Monitoramento grava a Axis como `ax`; quem é Axis se acha pela cache (`usinas_conhecidas` no app).
FONTES = {
    "pv": ("API PV", "thopen-pv"),
    "pg": ("Thopen (banco)", "thopen-db"),
    "so": ("Athon", "athon"),
    "ax": ("Axis", "axis"),
    "se": ("RenoGrid", "renogrid"),
    "owen": ("2C", "2c"),
    "semp": ("SEMP", "semp"),
    "al": ("Alves Lima", "alveslima"),
    "c2": ("2C · API PV", "2capi"),
    "gy": ("GreenYellow", "greenyellow"),
    "sal": ("Sal Energia", "salenergia"),
    "apo": ("Apolo", "apolo"),
}
# o ?fonte= do Monitoramento -> o nome da fonte (o `so` da Axis acha a fonte dela pela cache)
_NOME_DO_MONITOR = {fm: nome for nome, fm in FONTES.values()}

# O comentário automático da OS criada (03/11/2026, Levi: "quando eu crio uma OS de performance já vira um comentário
# automático: '<Levi> criou uma OS de <String> para o <inversor X>' + 'Observação da OS'"): `origem = "os"`, com o nº
# (`folio`) e o link da OS no OS Creator do Nexus. Um por OS: o nº já comentado não grava de novo (`folios_comentados`).
ORIGEM_OS = "os"
LINK_DA_OS = "/os/os/folio/{folio}"
OS_POR_PEDIDO = 50
NICK_MAX = 40            # o nick digitado (como sempre foi)
NOME_MAX = 80            # o nome que vem do Nexus: nome completo, maior que um apelido
TEXTO_MAX = 2000
USINA_MAX = 120


def identidade(sessao, pela_chave_de_leitura: bool = False) -> dict | None:
    """{nome, email, admin} de quem está na sessão, ou None quando a plataforma não sabe quem é.

    Sabe quem é: a sessão do passe do Nexus (`auth_kind = "nexus"`, com o e-mail e o nome do login do Fracttal) e a do
    Microsoft (`"ms"`, só o e-mail; desligado no servidor). Não sabe: a senha compartilhada, o pedido pela chave de leitura
    da ponte (sem sessão) e a senha de administrador do Nexus, que chega com `admin@nexus.invalid` (um domínio que não
    existe, `porta.EMAIL_DA_SENHA_DE_ADMIN` do Nexus): é uma senha de várias pessoas, não uma pessoa, e o nome dela
    ("Administrador do Nexus (senha)") não diria quem escreveu."""
    if pela_chave_de_leitura or not sessao or not sessao.get("auth"):
        return None
    tipo = sessao.get("auth_kind")
    if tipo not in ("nexus", "ms"):
        return None
    email = str(sessao.get("user") or "").strip().lower()
    if "@" not in email or email.endswith(".invalid"):
        return None
    nome = " ".join(str(sessao.get("nome") or "").split())[:NOME_MAX] or email
    return {"nome": nome, "email": email, "admin": tipo == "nexus" and bool(sessao.get("admin_nexus"))}


def autor(ident: dict | None, nick_digitado) -> tuple[str, str | None]:
    """(nick, email) do comentário novo. Com identidade, o nick do navegador é ignorado: quem diz é a sessão."""
    if ident:
        return ident["nome"], ident["email"]
    return " ".join(str(nick_digitado or "").split())[:NICK_MAX], None


def pode_apagar(item: dict, ident: dict | None) -> bool:
    """Sem identidade, como sempre foi (qualquer um apaga). Com ela, só o próprio, pelo e-mail, ou o admin do Nexus. O
    comentário sem e-mail (escrito pela senha, ou antes de 03/11/2026) é de ninguém conhecido: só o admin apaga.
    O automático da OS criada (`origem = "os"`) é registro, não conversa: só o admin do Nexus apaga, nem o autor nem a
    senha (o Levi, 03/11/2026: "não pode ser editado como comentário comum")."""
    if item.get("origem") == ORIGEM_OS:
        return bool(ident and ident.get("admin"))
    if not ident:
        return True
    if ident.get("admin"):
        return True
    return bool(item.get("email")) and str(item.get("email")).strip().lower() == ident["email"]


def para_tela(lista, ident: dict | None) -> list:
    """A conversa como as telas a recebem: sem o e-mail de ninguém, com `pode_apagar` e `meu` de cada comentário (a tela
    só mostra o "x" de quem pode; o servidor confere de novo)."""
    out = []
    for c in lista or []:
        if not isinstance(c, dict):
            continue
        d = {k: v for k, v in c.items() if k != "email"}
        d["pode_apagar"] = pode_apagar(c, ident)
        d["meu"] = bool(ident) and bool(c.get("email")) and str(c.get("email")).strip().lower() == ident["email"]
        out.append(d)
    return out


def folios_comentados(threads) -> set:
    """Os nº de OS que já têm o comentário automático, em qualquer conversa: a mesma OS não vira dois comentários, nem
    com a tela e o OS Creator avisando juntos, nem com o pedido repetido."""
    return {str(c.get("folio")) for lista in (threads or {}).values() for c in (lista or [])
            if isinstance(c, dict) and c.get("origem") == ORIGEM_OS and c.get("folio") not in (None, "")}


def texto_da_os(nome, folio, tipo, ativo, observacao) -> str:
    """"<Nome> criou a OS <nº> de <tipo> para o <ativo>" e, na linha de baixo, "Observação: <a da OS>"."""
    t = f"{nome} criou a OS {folio}" + (f" de {tipo}" if tipo else "") + (f" para o {ativo}" if ativo else "")
    obs = " ".join(str(observacao or "").split())
    return (t + (f"\nObservação: {obs}" if obs else ""))[:TEXTO_MAX]


_RX_CHAVE = re.compile(r"^[a-z0-9]{1,8}:[A-Za-z0-9_.\-]{1,64}$")


def chave_valida(chave) -> str:
    c = str(chave or "").strip()
    return c if _RX_CHAVE.match(c) else ""


def chave_da_usina_sem_tela(usina) -> str:
    """A OS criada direto no OS Creator (sem a tela que a abriu) não sabe a conversa da usina no tempo real: vai para
    `os:<usina sem acento>`, que a tela Comentários mostra pelo nome e nenhuma aba do tempo real abre (nada de adivinhar
    a fonte pelo nome do Fracttal)."""
    n = re.sub(r"[^a-z0-9]+", "-", _sem_acento(usina)).strip("-")[:64]
    return f"{ORIGEM_OS}:{n}" if n else ""


def separar_chave(chave) -> tuple[str, str]:
    """`pv:22854` -> ("pv", "22854"). Sem dois-pontos, o prefixo fica vazio."""
    c = str(chave or "")
    if ":" not in c:
        return "", c
    p, pid = c.split(":", 1)
    return p, pid


def _quando(ts) -> str:
    """`2026-11-03 14:05:09.123456` -> `03/11/2026 14:05`."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})", str(ts or ""))
    return f"{m[3]}/{m[2]}/{m[1]} {m[4]}:{m[5]}" if m else ""


def _sem_acento(s) -> str:
    n = unicodedata.normalize("NFKD", str(s or ""))
    return " ".join("".join(ch for ch in n if not unicodedata.combining(ch)).lower().split())


def listar(threads: dict, conhecidas: dict | None, ident: dict | None) -> list:
    """Todos os comentários do `comments_thread`, um por linha, mais novos primeiro.

    `conhecidas` = {chave: {"usina", "fonte"}} das caches das fontes (o nome de agora e o `?fonte=` do Monitoramento).
    O nome da usina: o da cache; sem ela (fonte fora, usina que saiu do tempo real), o que a tela mandou no comentário
    mais novo da mesma chave (`usina`, desde 03/11/2026); sem os dois, a própria chave, para não inventar nome."""
    conhecidas = conhecidas or {}
    out = []
    for chave, lista in (threads or {}).items():
        lista = [c for c in (lista or []) if isinstance(c, dict)]
        if not lista:
            continue
        prefixo, pid = separar_chave(chave)
        rotulo, fonte_monitor = FONTES.get(prefixo, ("", ""))
        conh = conhecidas.get(chave) or {}
        if conh.get("fonte"):
            fonte_monitor = conh["fonte"]
            rotulo = _NOME_DO_MONITOR.get(fonte_monitor, rotulo)
        usina = conh.get("usina") or next((str(c["usina"]) for c in reversed(lista) if c.get("usina")), "")
        link = (f"/monitor?fonte={fonte_monitor}&usina={pid}&comentarios=1"
                if fonte_monitor and pid and re.fullmatch(r"[A-Za-z0-9_.\-]+", pid) else "")
        for c in para_tela(lista, ident):
            out.append({"chave": chave, "fonte": rotulo, "plant_id": pid, "usina": usina or chave,
                        "usina_conhecida": bool(usina), "nick": str(c.get("nick") or ""),
                        "texto": str(c.get("texto") or ""), "ts": str(c.get("ts") or ""), "quando": _quando(c.get("ts")),
                        "pode_apagar": c["pode_apagar"], "meu": c["meu"], "link": link,
                        "origem": str(c.get("origem") or ""), "folio": str(c.get("folio") or ""),
                        "link_os": str(c.get("link_os") or "")})
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out


def _dia(s) -> str | None:
    s = str(s or "").strip()
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%Y-%m-%d") if s else None
    except ValueError:
        return None


def filtrar(itens: list, q="", chave="", autor_="", de="", ate="", origem="") -> list:
    """Os filtros da tela, e só eles: a busca (no texto, no autor e na usina, sem acento nem caixa), a usina (pela chave),
    o autor (o nick, exato), o período (`de` e `ate` em AAAA-MM-DD, os dois inclusive; data inválida não filtra) e o tipo
    (`origem`: "os" = as OS criadas, "comentario" = os escritos; vazio = todos)."""
    q, d0, d1 = _sem_acento(q), _dia(de), _dia(ate)
    out = []
    for x in itens:
        if chave and x["chave"] != chave:
            continue
        if origem == ORIGEM_OS and x.get("origem") != ORIGEM_OS:
            continue
        if origem == "comentario" and x.get("origem") == ORIGEM_OS:
            continue
        if autor_ and x["nick"] != autor_:
            continue
        dia = x["ts"][:10]
        if d0 and dia < d0:
            continue
        if d1 and dia > d1:
            continue
        if q and q not in _sem_acento(" ".join((x["texto"], x["nick"], x["usina"]))):
            continue
        out.append(x)
    return out


def opcoes(itens: list) -> dict:
    """As opções dos seletores: cada usina e cada autor que tem comentário, com quantos."""
    usinas, autores = {}, {}
    for x in itens:
        u = usinas.setdefault(x["chave"], {"chave": x["chave"], "usina": x["usina"], "fonte": x["fonte"], "qtd": 0})
        u["qtd"] += 1
        a = autores.setdefault(x["nick"], {"nome": x["nick"], "qtd": 0})
        a["qtd"] += 1
    return {"usinas": sorted(usinas.values(), key=lambda u: (_sem_acento(u["usina"]), u["fonte"])),
            "autores": sorted(autores.values(), key=lambda a: _sem_acento(a["nome"]))}
