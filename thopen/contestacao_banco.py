# -*- coding: utf-8 -*-
"""As contestações do cliente no banco, para o Nexus (rodada 5, Levi 13/10/2026: "contestação ligada ao Nexus: em
contratos e clientes no Nexus pode ter um lugar para essas contestações separando setores!"; "ficaria na API do PG, pode
aplicar e construir!"). Até aqui a contestação só existia como mensagem no Teams.

O 5080 é a FONTE: livro `thopen_contestacoes` · aba `contestacoes`, no catálogo do Nexus (fato `contestacao_cliente`,
nexus/dados/catalogo.py). Grão: 1 linha = 1 contestação × 1 setor — as mesmas mensagens do Teams (ronda → Zeladoria, o
resto → Performance), com o mesmo `contestacao_id` nas duas quando o cliente marca dos dois lados. O livro é trocado
inteiro a cada contestação (`sync-xlsx?replace=true`, como os livros do Nexus), sob a trava, com o que já estava lá
relido antes — e a leitura tem de bater com a contagem da API: regravar a partir de uma leitura parcial apagaria
contestações (a API não apaga livro, mas a troca integral apaga linha).

A API do banco tem LEITURA ABERTA (nexus/dados/CLAUDE.md, regra 8): nome, contato, mensagem e o que estava na tela vão só
CIFRADOS, numa coluna (`dados_cifrados`). A cifra é ASSIMÉTRICA (X25519 + HKDF-SHA256 + AES-256-GCM, a chave de cada
cifra é efêmera): o 5080, público, tem só a chave PÚBLICA (`THOPEN_CONTESTACAO_CHAVE_PUBLICA`) e não abre nada, nem o
que ele mesmo gravou; só o Nexus abre, com a privada (`NEXUS_CONTESTACAO_CHAVE_PRIVADA`). A cifra é presa à linha
(o contexto `thopen_contestacoes/<id>/dados` vai como dado associado): copiada para outra linha, não abre.

Desde 19/10/2026 o banco é o DESTINO de toda contestação (Levi: "vai direto para contestações do Nexus e a gente resolve
lá, esquece teams"): a rota grava na hora e só diz "enviada" depois de o livro conferir; o Teams, onde há fluxo, é um
aviso a mais. Sem a chave pública ou sem o token de escrita (GRIDCO_SQL_TOKEN), não grava (`configurado()` = falso) e
o item sem Teams não aparece na tela.
"""
import base64
import io
import json
import os
import threading
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

import contestacao
import fonte_api

LIVRO, NOME_LIVRO, ABA = "thopen_contestacoes", "Dashboard Thopen · contestações do cliente", "contestacoes"
# coluna nova só no FIM: o Nexus lê pelo nome, mas quem lê por posição não se perde
CAB = ("id", "contestacao_id", "recebida_em", "data_id_recebida", "data_id_contestada_ini", "data_id_contestada_fim",
       "usina", "usina_id", "setor", "itens", "avisado_teams", "origem", "dados_cifrados")
PREFIXO = "cx1:"
VAR_PUBLICA = "THOPEN_CONTESTACAO_CHAVE_PUBLICA"
ORIGEM = "dashboard_thopen"
_BRT = timezone(timedelta(hours=-3))
_TRAVA = threading.Lock()          # o livro é trocado inteiro: duas contestações juntas não se apagam
_INFO = b"thopen-contestacao/v1"


class CifraErro(RuntimeError):
    """Chave ausente ou inválida, cifra adulterada ou de outra linha. Nunca traz o dado nem a chave."""


class GravacaoErro(RuntimeError):
    """A gravação não aconteceu (ou não confere): o livro do banco ficou como estava."""


def _b64e(b):
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64d(s):
    s = str(s or "").strip()
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def gerar_par():
    """(privada, pública) em base64: a privada vai no .env do Nexus, a pública no do 5080."""
    k = X25519PrivateKey.generate()
    priv = k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return _b64e(priv), _b64e(pub)


def _chave(segredo_comum, pub_efemera):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=pub_efemera, info=_INFO).derive(segredo_comum)


def cifrar(texto, contexto, publica_b64):
    try:
        destino = X25519PublicKey.from_public_bytes(_b64d(publica_b64))
    except Exception:              # noqa: BLE001 — vazia, base64 quebrado, tamanho errado
        raise CifraErro("%s ausente ou inválida" % VAR_PUBLICA) from None
    efemera = X25519PrivateKey.generate()
    pub_ef = efemera.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    nonce = os.urandom(12)
    corpo = AESGCM(_chave(efemera.exchange(destino), pub_ef)).encrypt(nonce, texto.encode("utf-8"),
                                                                       contexto.encode("utf-8"))
    return PREFIXO + _b64e(pub_ef + nonce + corpo)


def decifrar(valor, contexto, privada_b64):
    """O caminho do Nexus (nexus/contratos/contestacoes.py repete esta conta). Aqui serve aos testes."""
    if not (isinstance(valor, str) and valor.startswith(PREFIXO)):
        raise CifraErro("valor não está cifrado")
    try:
        bruto = _b64d(valor[len(PREFIXO):])
        pub_ef, nonce, corpo = bruto[:32], bruto[32:44], bruto[44:]
        priv = X25519PrivateKey.from_private_bytes(_b64d(privada_b64))
        segredo = priv.exchange(X25519PublicKey.from_public_bytes(pub_ef))
        return AESGCM(_chave(segredo, pub_ef)).decrypt(nonce, corpo, contexto.encode("utf-8")).decode("utf-8")
    except Exception:              # noqa: BLE001 — InvalidTag, chave errada, base64 quebrado: tudo "não confere"
        raise CifraErro("cifra não confere: adulterada, de outra linha ou de outra chave") from None


def contexto(linha_id):
    return "%s/%s/dados" % (LIVRO, linha_id)


def linhas(d, usina, usina_id, ano, mes, dia_ini, dia_fim, avisos, publica, agora=None):
    """As linhas de uma contestação: uma por setor de `avisos` ({setor: o Teams recebeu? — None = sem fluxo}), cada uma
    com só os itens
    daquele setor. `d` = o que contestacao.validar devolveu. Sem a chave pública levanta (nada vai em claro)."""
    agora = agora or datetime.now(timezone.utc)
    cid = uuid.uuid4().hex[:12]
    out = []
    for setor, avisado in avisos.items():
        itens = [i for i in d["itens"] if contestacao.ITENS.get(i) == setor]
        lid = uuid.uuid4().hex[:12]
        dados = {"nome": d["nome"], "contato": d["contato"], "mensagem": d.get("mensagem") or "",
                 "tela": d.get("tela") or {}, "itens": itens}
        out.append({
            "id": lid, "contestacao_id": cid, "recebida_em": agora.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data_id_recebida": int(agora.astimezone(_BRT).strftime("%Y%m%d")),
            "data_id_contestada_ini": ano * 10000 + mes * 100 + dia_ini,
            "data_id_contestada_fim": ano * 10000 + mes * 100 + dia_fim,
            "usina": usina, "usina_id": usina_id, "setor": setor, "itens": ";".join(itens),
            # None = o setor não tem fluxo do Teams (o COS, 19/10/2026): "sem canal", não "não" (= o Teams recusou)
            "avisado_teams": "sim" if avisado else ("sem canal" if avisado is None else "não"), "origem": ORIGEM,
            "dados_cifrados": cifrar(json.dumps(dados, ensure_ascii=False), contexto(lid), publica)})
    return out


# ── a API do banco (os três pedaços que a gravação usa; os testes trocam por uma API falsa) ──────────────────────────
def _get(caminho, tok):
    return fonte_api._get(caminho, tok)


def _post(caminho, corpo, tipo, tok):
    req = urllib.request.Request(fonte_api.BASE + caminho, data=corpo, method="POST",
                                 headers={"Content-Type": tipo, "Authorization": "Bearer " + tok})
    with urllib.request.urlopen(req, timeout=120) as r:
        st = getattr(r, "status", 200)
    if not 200 <= st < 300:
        raise GravacaoErro("a API respondeu %s" % st)


def _criar_livro(chave, nome, tok):
    _post("/api/workbooks", json.dumps({"key": chave, "display_name": nome}).encode("utf-8"), "application/json", tok)


def _trocar_livro(xlsx, tok):
    fronteira = "----thopen" + uuid.uuid4().hex
    corpo = (("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s.xlsx\"\r\n"
              "Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n")
             % (fronteira, LIVRO)).encode("utf-8") + xlsx + ("\r\n--%s--\r\n" % fronteira).encode("utf-8")
    _post("/api/workbooks/%s/sync-xlsx?replace=true" % LIVRO, corpo, "multipart/form-data; boundary=" + fronteira, tok)


def _ler(tok):
    """As linhas que já estão no livro. A leitura tem de bater com a contagem da API: senão levanta (nunca regravar o
    livro a partir de uma leitura parcial)."""
    aba = next((s for s in _get("/api/sheets", tok) or []
                if s.get("workbook_key") == LIVRO and s.get("sheet_name") == ABA), None)
    if not aba:
        return []
    out, off = [], 0
    while True:
        r = _get("/api/sheets/%d/rows?offset=%d&limit=1000" % (int(aba["id"]), off), tok)
        rows = r.get("rows", []) if isinstance(r, dict) else (r or [])
        out += [dict(zip(x.get("headers") or [], x.get("values") or [])) for x in rows]
        if len(rows) < 1000:
            break
        off += 1000
    esperado = aba.get("row_count")
    if esperado is not None and int(esperado) != len(out):
        raise GravacaoErro("li %d linhas e a API diz %s: não regravo o livro" % (len(out), esperado))
    return out


def _xlsx(todas):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = ABA
    ws.append(list(CAB))
    for l in todas:
        ws.append([l.get(c) for c in CAB])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def registrar(novas, token=None):
    """Soma as linhas novas ao livro e confere. Devolve quantas linhas o livro tem depois. Levanta GravacaoErro sem
    token, com leitura parcial ou se a contagem não bater depois de gravar."""
    tok = fonte_api._token() if token is None else token
    if not tok:
        raise GravacaoErro("sem o token de escrita do banco (GRIDCO_SQL_TOKEN)")
    with _TRAVA:
        atuais = _ler(tok)
        if LIVRO not in {w.get("key") for w in _get("/api/workbooks", tok) or []}:
            _criar_livro(LIVRO, NOME_LIVRO, tok)        # a 1ª contestação cria o livro (o nome é para sempre)
        todas = atuais + list(novas)
        _trocar_livro(_xlsx(todas), tok)
        depois = _ler(tok)
        if len(depois) != len(todas):
            raise GravacaoErro("enviei %d linhas e o banco tem %d" % (len(todas), len(depois)))
        return len(depois)


def configurado():
    """O banco pode receber contestação: a chave pública (nada vai em claro) e o token de escrita. É o que libera na tela
    o item sem Teams (Disponibilidade e Desligamento, do COS, desde 19/10/2026)."""
    return bool(fonte_api.segredo(VAR_PUBLICA) and fonte_api._token())


def registrar_contestacao(d, usina, usina_id, ano, mes, dia_ini, dia_fim, avisos):
    """Grava NA HORA e devolve quantas linhas o livro tem (Levi, 19/10/2026: "vai direto para contestações do Nexus e a
    gente resolve lá, esquece teams"). O banco é o destino de todo item: o cliente só lê "enviada" depois de o livro
    conferir — até 19/10 a gravação era em segundo plano porque o Teams era o registro. Levanta GravacaoErro sem a
    chave pública ou sem o token; o erro vai ao log só com o tipo (nada do cliente no log)."""
    publica = fonte_api.segredo(VAR_PUBLICA)
    if not publica:
        raise GravacaoErro("falta a %s" % VAR_PUBLICA)
    n = registrar(linhas(d, usina, usina_id, ano, mes, dia_ini, dia_fim, avisos, publica))
    print("[contestacao] gravada no banco (%s: %d linhas)" % (LIVRO, n), flush=True)
    return n
