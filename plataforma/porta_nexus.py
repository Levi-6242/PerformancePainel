# -*- coding: utf-8 -*-
"""A porta única com o Nexus (09/10/2026): o mapa das telas, o passe e os perfis.

Levi, 09/10/2026: "a partir de segunda quero o Nexus como link principal; o Nexus será o centro de tudo, precisamos
trazer o tempo real de performance painel para o Nexus". Desenho aprovado: "uma porta, dois motores"
(docs/superpowers/specs/2026-10-09-performance-no-nexus-design.md, no repositório do Nexus). O Nexus é a porta (menu,
login, endereço); esta plataforma continua o motor e desenha as próprias telas, dentro de uma moldura do Nexus.

Este módulo é PURO (não importa Flask nem o app): o `app.py` só o liga às rotas. Três partes:

1. O MAPA das telas (spec 5.6). Fonte única: o Nexus é o dono e esta é a cópia. Ele diz o destino que o passe pode
   pedir (nada de redirecionamento aberto), a tela de cada caminho e o que o gestor lê. `test_porta_nexus.py` confere a
   cópia pela `assinatura_do_mapa()` (o mesmo texto canônico existe no teste do Nexus) e quebra se uma rota de página
   da plataforma ficar sem lugar no mapa nem em `FORA_DO_MAPA`.

2. O PASSE (spec 5.2): `base64url(json) + "." + base64url(HMAC-SHA256(json))` com a chave `NEXUS_SSO_CHAVE`. O JSON:
       {"v": 1, "email": "...", "nome": "...", "admin": false, "destino": "/tempo-real",
        "vence": <epoch em segundos, no máximo 60 s à frente>, "numero": "<aleatório, 16 a 128 de [A-Za-z0-9_-]>"}
   A assinatura é sobre os BYTES do primeiro segmento já decodificado (o JSON exatamente como o Nexus o escreveu), e o
   base64url vai sem `=` (aceito com ou sem). Chega por POST no campo `passe` de `/painel/nexus/entrar`, nunca na URL:
   ele leva o e-mail e não pode ficar em log de proxy nem no histórico do navegador.

3. Os PERFIS (spec 5.3): analista (tudo o que a senha faz) e gestor (só leitura), pelas listas `PLATAFORMA_ANALISTAS` e
   `PLATAFORMA_GESTORES` (e-mails separados por vírgula, ou `*`).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import threading
from collections import namedtuple

# ── 1. O mapa das telas ──────────────────────────────────────────────────────────────────────────────────────────────
# torre e tela = o id no Nexus (`/t/<torre>/<tela>`); caminho = a entrada da tela na plataforma; tambem = outros
# caminhos que são a MESMA tela (o Nexus acende o item por eles quando a moldura avisa onde está); so_admin = só quem é
# admin do Nexus abre (as chaves das fontes). Padrão: `<x>` é um segmento; `<path:x>` é o resto do caminho.
Tela = namedtuple("Tela", "torre tela nome caminho tambem so_admin")

MAPA = (
    # O Tempo real é a Entrada nível 2 (cards por fonte); o nível 3 é /tempo-real/<fonte>, que embute
    # /monitor?fonte=…&embed=1. O /monitor sem moldura (os deep links do Painel NOC) é a mesma tela.
    Tela("performance", "tempo-real", "Tempo real", "/tempo-real", ("/tempo-real/<fonte>", "/monitor"), False),
    Tela("performance", "noc", "Painel NOC", "/painel", (), False),
    # Diagnóstico = o diagnóstico da usina, aberto pelo seletor de usina do Nexus (Levi, 09/10: "OK, cuida!")
    Tela("performance", "diagnostico", "Diagnóstico", "/painel/usina/<id>", (), False),
    Tela("performance", "strings-trackers", "Strings e trackers", "/painel/falhas", (), False),
    Tela("performance", "gerencial", "Visão gerencial", "/gerencial", (), False),
    Tela("performance", "disponibilidade", "Disponibilidade", "/gerencial/disponibilidade", (), False),
    Tela("performance", "relatorio", "Criador de relatório", "/relatorio", (), False),
    Tela("performance", "relatorio-semanal", "Relatório semanal", "/relatorio/semanal", (), False),
    # O gêmeo é outro processo, servido pelo proxy /gemeo/*: tudo debaixo dele é a mesma tela (o Painel NOC abre
    # /gemeo/usina/<id>).
    Tela("performance", "gemeo", "Gêmeo digital", "/gemeo/", ("/gemeo/<path:resto>",), False),
    Tela("performance", "historico-plataforma", "Histórico da plataforma", "/historico-plataforma", (), False),
    Tela("performance", "monitor-ronda", "Monitor da ronda", "/ronda/monitor", (), False),
    Tela("cos", "acompanhamento", "Acompanhamento COS", "/cos", (), False),
    # /tokens grava as chaves das fontes (SunOp, Axis, Plataforma): administração, só admin do Nexus (spec 5.3)
    Tela("base", "chaves-fontes", "Chaves das fontes", "/tokens", (), True),
)

# Rotas de página da plataforma que NÃO são tela do Nexus, cada uma com o porquê. Rota de página nova tem de entrar no
# MAPA ou aqui (test_toda_rota_de_pagina_tem_lugar_no_mapa): sem isso ela some do Nexus calada.
FORA_DO_MAPA = {
    "/": "a Entrada: no Nexus o menu faz o papel dela; dentro da moldura leva a /tempo-real (fase 3: leva ao Nexus)",
    "/login": "login da plataforma (a senha fica de reserva)",
    "/logout": "sair da sessão por senha",
    "/auth/login": "login Microsoft (desligado no servidor)",
    "/auth/callback": "volta do login Microsoft",
    "/healthz": "saúde do processo, sem tela",
    "/versao": "qual commit está no ar, sem tela",
    "/teste": "endereço antigo da Entrada (redireciona)",
    "/teste/<nivel>": "endereço antigo da Entrada (redireciona)",
    "/monitoramento": "o mesmo Monitoramento do /monitor; no servidor o Caddy responde sozinho neste caminho",
    "/v2": "endereço antigo do Monitoramento",
    "/os/": "OS Creator Web: no Nexus, Criar OS é o OS Creator do próprio Nexus (spec 5.6; sai na fase 4)",
    "/os/<path:sub>": "OS Creator Web (idem)",
    "/painel/nexus/entrar": "o passe do Nexus (esta porta), não é tela",
    "/painel/nexus/sair": "o Sair do Nexus passa por aqui, não é tela",
}


def _rx(padrao: str) -> "re.Pattern":
    partes = re.split(r"(<[^>]+>)", padrao)
    rx = ""
    for p in partes:
        if p.startswith("<path:"):
            rx += r"[^?#]+"
        elif p.startswith("<"):
            rx += r"[^/?#]+"
        else:
            rx += re.escape(p)
    return re.compile("^" + rx + "$")


_PADROES = tuple((t, _rx(p)) for t in MAPA for p in (t.caminho,) + tuple(t.tambem))


def tela_do_caminho(caminho: str):
    """A tela do mapa a que o caminho (sem query) pertence, ou None."""
    c = (caminho or "").split("?", 1)[0]
    for t, rx in _PADROES:
        if rx.match(c):
            return t
    return None


# Só admin do Nexus, em qualquer perfil (spec 5.3: "administração só admin_nexus"): as páginas `so_admin` do mapa e a
# API delas (a validade e o colar), e a administração da plataforma que não tem tela no mapa. Revisão de 10/10/2026: só
# o /tokens estava aqui, e com PLATAFORMA_ANALISTAS=* qualquer conta do Fracttal podia:
# - trocar o BD_Performance, o BD_Thopen ou os Tickets do espelho que o servidor sem OneDrive lê (/api/admin/base/...)
#   e ver os caminhos do servidor (/api/admin/bases);
# - mandar a ronda NA HORA pelo chip da empresa, aos grupos do COS ou a QUALQUER número (/api/ronda/whats/testar; a
#   conta já foi restringida por spam), listar os grupos do chip (/grupos) e derrubar o serviço do WhatsApp
#   (/reiniciar, o botão do Monitor da ronda quando o chip cai).
# A sessão da senha não passa por aqui: segue como hoje.
ROTAS_SO_ADMIN = tuple(t.caminho for t in MAPA if t.so_admin) + (
    "/api/tokens", "/api/admin", "/api/ronda/whats/testar", "/api/ronda/whats/reiniciar", "/api/ronda/whats/grupos")


def so_admin(caminho: str) -> bool:
    c = (caminho or "").split("?", 1)[0].rstrip("/") or "/"
    return any(c == b or c.startswith(b + "/") for b in ROTAS_SO_ADMIN)


def texto_canonico_do_mapa() -> str:
    """Uma linha por tela, na ordem do mapa: `torre|tela|caminho|tambem separados por espaço|admin ou vazio`. O mesmo
    texto existe no teste do Nexus: os dois lados comparam a assinatura dele (o nome de exibição fica de fora de
    propósito: cada lado pode acertar a grafia sem quebrar o outro)."""
    return "\n".join(f"{t.torre}|{t.tela}|{t.caminho}|{' '.join(t.tambem)}|{'admin' if t.so_admin else ''}"
                     for t in MAPA)


def assinatura_do_mapa() -> str:
    return hashlib.sha256(texto_canonico_do_mapa().encode("utf-8")).hexdigest()[:16]


_RX_CONTROLE = re.compile(r"[\x00-\x20\x7f\\#<>\"'`]")


def destino_permitido(destino) -> str | None:
    """O destino do passe, se for uma tela do mapa; None senão. Só caminho local (uma barra, sem esquema nem host), sem
    espaço, controle, barra invertida nem fragmento; a query passa (o Nexus devolve o `?p=` do favorito, como
    `/monitor?fonte=pv&embed=1`). Nada de redirecionamento aberto: `//outro.site` e `/\\outro.site` caem aqui."""
    if not isinstance(destino, str) or not destino or len(destino) > 2048:
        return None
    if not destino.startswith("/") or destino.startswith("//") or _RX_CONTROLE.search(destino):
        return None
    caminho = destino.split("?", 1)[0]
    if ".." in caminho.split("/"):
        return None
    return destino if tela_do_caminho(caminho) else None


# ── 2. O passe ───────────────────────────────────────────────────────────────────────────────────────────────────────
VALIDADE_S = 60                  # o passe vale 60 s (spec 5.2)
FOLGA_RELOGIO_S = 5              # o Nexus e a plataforma rodam no mesmo servidor; 5 s cobrem o arredondamento
GUARDA_NUMEROS_S = 120           # os números usados ficam 2 min (spec 5.2): mais que a vida do passe
TAMANHO_MAXIMO = 4096            # passe maior que isto não é do Nexus
CHAVE_MINIMA = 32                # NEXUS_SSO_CHAVE: 32 caracteres ou mais, aleatória (spec 5.2)
_RX_NUMERO = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


class PasseRecusado(Exception):
    """O passe não abre sessão. `motivo` é texto fixo, para a página "Abra de novo pelo Nexus"."""

    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


def _b64(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).decode("ascii").rstrip("=")


def _deb64(texto: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]*={0,2}", texto or ""):
        raise ValueError("fora do base64url")
    texto = texto.rstrip("=")
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def _assinatura(corpo: bytes, chave: str) -> bytes:
    return hmac.new(chave.encode("utf-8"), corpo, hashlib.sha256).digest()


def assinar_passe(dados: dict, chave: str) -> str:
    """Monta um passe (o Nexus tem o seu; este serve aos testes e à prova local)."""
    corpo = json.dumps(dados, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return _b64(corpo) + "." + _b64(_assinatura(corpo, chave))


class NumerosUsados:
    """Os números de passe já usados nos últimos `GUARDA_NUMEROS_S` (spec 5.2: uso único). Em memória, por processo: o
    web do servidor é um processo só (waitress com threads). Reiniciar esquece a lista, e um passe ainda vivo (60 s)
    poderia ser usado de novo nessa janela; risco aceito."""

    def __init__(self):
        self._vistos = {}
        self._trava = threading.Lock()

    def marcar(self, numero: str, agora: float) -> bool:
        """True se o número era novo (e fica marcado); False se já tinha sido usado."""
        with self._trava:
            for n, quando in list(self._vistos.items()):
                if agora - quando > GUARDA_NUMEROS_S:
                    del self._vistos[n]
            if numero in self._vistos:
                return False
            self._vistos[numero] = agora
            return True


def ler_passe(passe, chave: str, agora: float, usados: NumerosUsados) -> dict:
    """Confere o passe e devolve {email, nome, admin, destino}. PasseRecusado com o motivo em qualquer falha.

    Ordem: formato, assinatura (compare_digest), conteúdo, vencimento, destino e, por último, o número (só passe
    autêntico entra na lista dos usados: sem a chave ninguém a enche)."""
    if not chave:
        raise PasseRecusado("a porta do Nexus está desligada nesta plataforma")
    if not passe or not isinstance(passe, str):
        raise PasseRecusado("o passe não chegou")
    if len(passe) > TAMANHO_MAXIMO or passe.count(".") != 1:
        raise PasseRecusado("o passe está fora do formato")
    seg_corpo, seg_assin = passe.split(".")
    try:
        corpo, assin = _deb64(seg_corpo), _deb64(seg_assin)
    except (ValueError, TypeError):
        raise PasseRecusado("o passe está fora do formato") from None
    if not hmac.compare_digest(assin, _assinatura(corpo, chave)):
        raise PasseRecusado("a assinatura do passe não confere: passe alterado no caminho, ou a chave do Nexus e a "
                            "da plataforma são diferentes")
    try:
        dados = json.loads(corpo.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise PasseRecusado("o passe está fora do formato") from None
    if not isinstance(dados, dict) or dados.get("v") != 1:
        raise PasseRecusado("versão do passe desconhecida")
    vence = dados.get("vence")
    if isinstance(vence, bool) or not isinstance(vence, (int, float)):
        raise PasseRecusado("o passe não diz quando vence")
    if agora > vence:
        raise PasseRecusado(f"o passe venceu (vale {VALIDADE_S} s)")
    if vence - agora > VALIDADE_S + FOLGA_RELOGIO_S:
        raise PasseRecusado(f"o passe vale mais que {VALIDADE_S} s")
    email = dados.get("email")
    if not isinstance(email, str) or "@" not in email or len(email) > 254 or _RX_CONTROLE.search(email):
        raise PasseRecusado("o passe não diz quem é a pessoa")
    destino = destino_permitido(dados.get("destino"))
    if destino is None:
        raise PasseRecusado("o destino não é uma tela da Performance no Nexus")
    numero = dados.get("numero")
    if not isinstance(numero, str) or not _RX_NUMERO.match(numero):
        raise PasseRecusado("o passe está fora do formato")
    if not usados.marcar(numero, agora):
        raise PasseRecusado("este passe já foi usado (cada abertura pelo Nexus gera um novo)")
    nome = dados.get("nome")
    return {"email": email.strip().lower(), "nome": nome.strip()[:120] if isinstance(nome, str) else "",
            "admin": dados.get("admin") is True, "destino": destino}


def marca_da_chave(chave: str) -> str:
    """Marca da chave guardada na sessão do passe: trocar a NEXUS_SSO_CHAVE derruba as sessões abertas por ela, não as
    da senha (spec 8). É um HMAC, não um pedaço da chave: o cookie é legível (só assinado)."""
    return hmac.new(chave.encode("utf-8"), b"sessao-da-plataforma", hashlib.sha256).hexdigest()[:16]


# ── 3. Os perfis ─────────────────────────────────────────────────────────────────────────────────────────────────────
ANALISTA, GESTOR = "analista", "gestor"


def ler_lista(texto) -> frozenset:
    """`PLATAFORMA_ANALISTAS`/`PLATAFORMA_GESTORES`: e-mails separados por vírgula (ou ponto e vírgula, ou espaço), ou
    `*` = todos. Caixa não importa."""
    return frozenset(e.lower() for e in re.split(r"[,;\s]+", texto or "") if e)


def perfil_de(email, analistas: frozenset, gestores: frozenset):
    """'analista', 'gestor' ou None (fora das duas listas: "sem acesso à Performance").

    O e-mail escrito vence o `*` (ANALISTAS=* com GESTORES=fulano: fulano é gestor, o resto analista); escrito nas
    duas, ou `*` nas duas, vence o mais restrito (gestor)."""
    e = (email or "").strip().lower()
    if not e:
        return None
    if e in gestores:
        return GESTOR
    if e in analistas:
        return ANALISTA
    if "*" in gestores:
        return GESTOR
    if "*" in analistas:
        return ANALISTA
    return None
