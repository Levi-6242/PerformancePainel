# -*- coding: utf-8 -*-
"""Login por pessoa no Dashboard Thopen (Levi, 14/10/2026: "É possível implementarmos uma visão de login e senha para o
dashboard thopen?" — contas por pessoa, ligada a um cliente; administradas no Nexus, em Contratos e clientes). Spec:
docs/superpowers/specs/2026-10-14-thopen-login-por-pessoa-design.md.

De onde vem:
- As CONTAS, o Nexus grava: livro `nexus_acessos_clientes` · `contas` (1 linha = 1 conta, o estado atual). Nome e e-mail
  vêm em `dados_5080`, selados para a chave PÚBLICA do 5080 (X25519 + HKDF-SHA256 + AES-256-GCM, prefixo `cx1:`, presos à
  conta). O link de definir senha vem como `convite_hash` (sha256 do token) e `convite_expira`.
- As SENHAS, o 5080 grava: livro `thopen_acessos` · `senhas` (1 linha = 1 senha definida; vale a mais nova da conta).
  O hash (scrypt, do werkzeug) vai cifrado com AES-GCM numa chave derivada da PRIVADA do 5080, preso à linha.

Nenhum segredo é compartilhado entre os dois sistemas: a privada (`THOPEN_ACESSOS_CHAVE_PRIVADA`) só existe no servidor
do 5080; o Nexus só conhece a pública. O banco tem leitura aberta: nada de nome, e-mail ou hash em claro.

As contas são relidas a cada 2 min (desativar no Nexus vale em até 2 min); só em memória — sem disco. Sem a chave
privada ninguém entra (nunca abre sem senha), e a tela diz que o login não está configurado.
"""
import base64
import hashlib
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from werkzeug.security import check_password_hash, generate_password_hash

import fonte_api
import livro_banco

LIVRO_CONTAS, ABA_CONTAS = "nexus_acessos_clientes", "dim_conta_cliente"
LIVRO_SENHAS, NOME_SENHAS, ABA_SENHAS = "thopen_acessos", "Dashboard Thopen · senhas do login", "senhas"
CAB_SENHAS = ("id", "conta_id", "definida_em", "convite_hash", "senha_cifrada")
# as carteiras do 5080 (dashboard_thopen.CARTEIRA_ORDEM; o teste confere): o papel "grid" vê todas
CARTEIRAS = ("Thopen", "Copel", "Matrix", "Polaris")
VAR_PRIVADA = "THOPEN_ACESSOS_CHAVE_PRIVADA"
# 6 (era 10 até 15/10/2026): o cliente segue com a senha de hoje (Levi: "Mesmo usuário e senha de hoje"), definida
# uma vez pelo link; o limite de tentativas (5 em 15 min por endereço e por conta) segura a força bruta
SENHA_MIN = 6
TTL = 120                      # s: desativada no Nexus = fora em até 2 min
PREFIXO_SELO, PREFIXO_SENHA = "cx1:", "cs1:"
_INFO_SELO = b"thopen-acessos/v1"
_INFO_SENHA = b"thopen-acessos-senha/v1"
_TRAVA = threading.Lock()
_CACHE = {"dados": None, "lido": 0.0, "erro": None}
MOTIVOS = {"invalido": "Este link não é válido.",
           "vencido": "Este link venceu. Peça um novo à Grid Co.",
           "usado": "Este link já foi usado. Se precisar de uma senha nova, peça um novo link à Grid Co.",
           "desativada": "Este acesso foi desativado. Fale com a Grid Co."}


class CifraErro(RuntimeError):
    """Chave ausente ou inválida, cifra adulterada ou de outra conta. Nunca traz o dado nem a chave."""


class Recusada(ValueError):
    """A senha não foi gravada: o texto diz por quê (para a tela)."""


def _b64e(b):
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64d(s):
    s = str(s or "").strip()
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def gerar_par():
    """(privada, pública) em base64: a privada vai no servidor do 5080; a pública, no Nexus (tela Chaves do Nexus)."""
    k = X25519PrivateKey.generate()
    priv = k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    return _b64e(priv), _b64e(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


def ctx_conta(conta_id):
    return "%s/%s/dados_5080" % (LIVRO_CONTAS, conta_id)


def ctx_senha(linha_id):
    return "%s/%s/senha" % (LIVRO_SENHAS, linha_id)


def _derivar(segredo, sal, info):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=sal, info=info).derive(segredo)


def selar(texto, ctx, publica_b64):
    """A receita do Nexus (nexus/contratos/acessos_clientes.py repete): aqui serve aos testes."""
    try:
        destino = X25519PublicKey.from_public_bytes(_b64d(publica_b64))
    except Exception:              # noqa: BLE001
        raise CifraErro("chave pública ausente ou inválida") from None
    ef = X25519PrivateKey.generate()
    pub_ef = ef.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    nonce = os.urandom(12)
    corpo = AESGCM(_derivar(ef.exchange(destino), pub_ef, _INFO_SELO)).encrypt(nonce, texto.encode("utf-8"),
                                                                              ctx.encode("utf-8"))
    return PREFIXO_SELO + _b64e(pub_ef + nonce + corpo)


def abrir(valor, ctx, privada_b64):
    if not (isinstance(valor, str) and valor.startswith(PREFIXO_SELO)):
        raise CifraErro("valor não está selado")
    try:
        bruto = _b64d(valor[len(PREFIXO_SELO):])
        pub_ef, nonce, corpo = bruto[:32], bruto[32:44], bruto[44:]
        segredo = X25519PrivateKey.from_private_bytes(_b64d(privada_b64)).exchange(
            X25519PublicKey.from_public_bytes(pub_ef))
        return AESGCM(_derivar(segredo, pub_ef, _INFO_SELO)).decrypt(nonce, corpo, ctx.encode("utf-8")).decode("utf-8")
    except Exception:              # noqa: BLE001 — InvalidTag, chave errada, base64 quebrado: tudo "não confere"
        raise CifraErro("selo não confere: adulterado, de outra conta ou de outra chave") from None


def _aead_senha(privada_b64):
    return AESGCM(_derivar(_b64d(privada_b64), None, _INFO_SENHA))


def cifrar_senha(hash_txt, ctx, privada_b64):
    nonce = os.urandom(12)
    return PREFIXO_SENHA + _b64e(nonce + _aead_senha(privada_b64).encrypt(nonce, hash_txt.encode("utf-8"),
                                                                           ctx.encode("utf-8")))


def decifrar_senha(valor, ctx, privada_b64):
    if not (isinstance(valor, str) and valor.startswith(PREFIXO_SENHA)):
        raise CifraErro("senha não está cifrada")
    try:
        bruto = _b64d(valor[len(PREFIXO_SENHA):])
        return _aead_senha(privada_b64).decrypt(bruto[:12], bruto[12:], ctx.encode("utf-8")).decode("utf-8")
    except Exception:              # noqa: BLE001
        raise CifraErro("senha cifrada não confere") from None


def _privada():
    return fonte_api.segredo(VAR_PRIVADA)


def _token():
    return fonte_api._token()


def _email(v):
    return str(v or "").strip().lower()


def _quando(v):
    try:
        return datetime.fromisoformat(str(v or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def _hash_token(token):
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _carregar(priv):
    """{contas: {id: conta}, por_login: {usuário: id}, senhas: {id: (definida_em, hash)}, usados: {convite_hash}}.
    O usuário de entrar é o "usuario" da conta (desde 15/10/2026: o de hoje do cliente, ou um e-mail) e, nas contas de
    antes, o e-mail."""
    tok = _token()
    contas, por_login = {}, {}
    for l in livro_banco.ler(LIVRO_CONTAS, ABA_CONTAS, tok):
        cid = str(l.get("conta_id") or "").strip()
        if not cid:
            continue
        try:
            d = json.loads(abrir(l.get("dados_5080"), ctx_conta(cid), priv))
        except Exception:          # noqa: BLE001 — selada para outra chave ou adulterada: a conta não entra
            continue
        papel = "grid" if str(l.get("papel") or "").strip().lower() == "grid" else "cliente"
        carteiras = (list(CARTEIRAS) if papel == "grid" else
                     [c for c in CARTEIRAS if c.lower() in {x.strip().lower() for x in str(l.get("carteiras") or "")
                                                            .split(";")}])
        email = _email(d.get("email"))
        c = {"conta_id": cid, "nome": str(d.get("nome") or "").strip(), "email": email if "@" in email else "",
             "usuario": _email(d.get("usuario") or d.get("email")),
             "carteiras": carteiras, "papel": papel,
             "ativa": str(l.get("status") or "").strip().lower() == "ativa",
             "convite_hash": str(l.get("convite_hash") or "").strip(), "convite_expira": _quando(l.get("convite_expira"))}
        contas[cid] = c
        if c["usuario"]:
            por_login[c["usuario"]] = cid
    senhas, usados = {}, set()
    for l in livro_banco.ler(LIVRO_SENHAS, ABA_SENHAS, tok):
        cid, quando = str(l.get("conta_id") or ""), _quando(l.get("definida_em"))
        if l.get("convite_hash"):
            usados.add(str(l.get("convite_hash")))
        try:
            h = decifrar_senha(l.get("senha_cifrada"), ctx_senha(l.get("id")), priv)
        except Exception:          # noqa: BLE001 — linha adulterada ou de outra chave: não vale
            continue
        if quando and (cid not in senhas or quando > senhas[cid][0]):
            senhas[cid] = (quando, h)
    return {"contas": contas, "por_login": por_login, "senhas": senhas, "usados": usados}


def limpar():
    with _TRAVA:
        _CACHE.update(dados=None, lido=0.0, erro=None)


def _dados():
    """As contas em memória; relidas quando passam de 2 min. Banco fora: ficam as últimas lidas (e o erro é guardado)."""
    priv = _privada()
    if not priv:
        with _TRAVA:
            _CACHE.update(dados=None, erro="o login não está configurado (falta a %s)" % VAR_PRIVADA)
        return None
    agora = time.time()
    with _TRAVA:
        if _CACHE["dados"] is not None and agora - _CACHE["lido"] < TTL:
            return _CACHE["dados"]
    try:
        d = _carregar(priv)
        with _TRAVA:
            _CACHE.update(dados=d, lido=agora, erro=None)
        return d
    except Exception as e:         # noqa: BLE001 — banco fora: as últimas lidas valem
        print("[acessos] não consegui ler as contas: %s" % type(e).__name__, flush=True)
        with _TRAVA:
            _CACHE["erro"] = "não consegui ler as contas (%s)" % type(e).__name__
            return _CACHE["dados"]


def estado():
    return {"erro": _CACHE["erro"], "lido_em": _CACHE["lido"],
            "contas": len((_CACHE["dados"] or {}).get("contas") or {})}


def _publica(c):
    return {k: c[k] for k in ("conta_id", "nome", "email", "usuario", "carteiras", "papel")}


def conta(conta_id):
    """A conta ATIVA (para o portão de cada pedido), ou None."""
    d = _dados()
    c = (d or {}).get("contas", {}).get(str(conta_id or ""))
    return _publica(c) if c and c["ativa"] else None


def verificar(login, senha, agora=None):
    """A conta, se o usuário (ou o e-mail) e a senha conferem e ela está ativa; senão None (nunca diz qual dos dois
    errou)."""
    d = _dados()
    if not d:
        return None
    cid = d["por_login"].get(_email(login))
    c = d["contas"].get(cid) if cid else None
    s = d["senhas"].get(cid) if cid else None
    if not c or not c["ativa"] or not s:
        return None
    try:
        return _publica(c) if check_password_hash(s[1], str(senha or "")) else None
    except Exception:              # noqa: BLE001 — hash estranho: não entra
        return None


def convite(token, agora=None):
    """(conta, motivo): motivo "ok", "invalido", "vencido", "usado" ou "desativada"."""
    agora = agora or datetime.now(timezone.utc)
    d = _dados()
    if not d or not token:
        return None, "invalido"
    h = _hash_token(token)
    c = next((x for x in d["contas"].values() if x["convite_hash"] and x["convite_hash"] == h), None)
    if not c:
        return None, "invalido"
    if not c["ativa"]:
        return None, "desativada"
    if h in d["usados"]:
        return None, "usado"
    if not c["convite_expira"] or c["convite_expira"] < agora:
        return None, "vencido"
    return _publica(c), "ok"


def definir_senha(token, senha, agora=None):
    """Grava a senha do link (uso único) e devolve a conta. Recusada: o texto diz por quê."""
    agora = agora or datetime.now(timezone.utc)
    senha = str(senha or "")
    if len(senha) < SENHA_MIN:
        raise Recusada("A senha precisa ter pelo menos %d caracteres." % SENHA_MIN)
    c, motivo = convite(token, agora)
    if motivo != "ok":
        raise Recusada(MOTIVOS.get(motivo, MOTIVOS["invalido"]))
    priv = _privada()
    lid = uuid.uuid4().hex[:12]
    linha = {"id": lid, "conta_id": c["conta_id"], "definida_em": agora.strftime("%Y-%m-%dT%H:%M:%SZ"),
             "convite_hash": _hash_token(token),
             "senha_cifrada": cifrar_senha(generate_password_hash(senha), ctx_senha(lid), priv)}
    livro_banco.acrescentar(LIVRO_SENHAS, NOME_SENHAS, ABA_SENHAS, CAB_SENHAS, [linha], _token())
    limpar()
    return c


class Limite:
    """Erros de senha por chave ("ip:…" e "conta:…"): N erros na janela = bloqueado até a janela passar."""

    def __init__(self, tentativas=5, janela=900):
        self.n, self.janela = tentativas, janela
        self._erros, self._trava = {}, threading.Lock()

    def _vivos(self, chave, agora):
        return [t for t in self._erros.get(chave, []) if agora - t < self.janela]

    def erro(self, chave, agora=None):
        agora = time.time() if agora is None else agora
        with self._trava:
            self._erros[chave] = self._vivos(chave, agora) + [agora]

    def bloqueado(self, chave, agora=None):
        agora = time.time() if agora is None else agora
        with self._trava:
            return len(self._vivos(chave, agora)) >= self.n

    def zerar(self, chave):
        with self._trava:
            self._erros.pop(chave, None)
