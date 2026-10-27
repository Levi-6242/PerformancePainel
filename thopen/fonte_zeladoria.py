# -*- coding: utf-8 -*-
"""Leitura da Zeladoria que o Nexus publica no banco (26/10/2026; a conta é do Nexus, ver zeladoria_cliente.py).

O mesmo cuidado do fonte_operacao: a requisição nunca espera a rede (serve o que tem e relê em segundo plano a cada TTL),
a leitura tem de bater com a contagem da aba de atualização (leitura no meio da troca não vai para a tela) e a última
leitura boa fica em disco para o reinício. Nada roda no import. `THOPEN_ZELADORIA=0` desliga a aba."""
import gzip
import json
import os
import threading
import time

import fonte_api
import fonte_operacao
import zeladoria_cliente as zc

TTL = int(os.environ.get("THOPEN_ZELADORIA_TTL", "600"))
COOLDOWN = 60
CACHE = os.environ.get("THOPEN_ZELADORIA_CACHE") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "cache_zeladoria.json.gz")
VERSAO_CACHE = 1

_lock = threading.Lock()
_estado = {"dados": None, "ts": 0.0, "carregando": False, "proxima": 0.0, "erro": None, "disco_lido": False}


def ligada():
    return os.environ.get("THOPEN_ZELADORIA", "1").strip() != "0"


def baixar(tok="", get=None):
    """Uma leitura completa: {"linhas": [...], "atualizacao": [...]}. Livro ainda não publicado = listas vazias."""
    get = get or fonte_api._get
    sheets = {(s["workbook_key"], s["sheet_name"]): s for s in get("/api/sheets", tok)}
    out = {"linhas": [], "atualizacao": []}
    for aba, chave, campos in ((zc.ABA, "linhas", zc.CAMPOS), (zc.ABA_ATUALIZACAO, "atualizacao", zc.CAMPOS_ATUALIZACAO)):
        s = sheets.get((zc.WORKBOOK, aba))
        if not s:
            continue
        for r in fonte_operacao._linhas(s["id"], get, tok):
            linha = dict(zip(r.get("headers") or [], r.get("values") or []))
            out[chave].append({c: linha.get(c) for c in campos})
    return out


def _grava_cache(dados, ts):
    try:
        tmp = "%s.%d.tmp" % (CACHE, os.getpid())
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump({"versao": VERSAO_CACHE, "ts": ts, "dados": dados}, f, default=str)
        os.replace(tmp, CACHE)
    except OSError as e:
        print("[zeladoria] não gravei o cache (%s)" % e, flush=True)


def _le_cache():
    try:
        with gzip.open(CACHE, "rt", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError, EOFError):
        return None
    if not isinstance(d, dict) or d.get("versao") != VERSAO_CACHE or not isinstance((d.get("dados") or {}).get("linhas"), list):
        return None
    return d


def _recarrega(get=None, espera=5.0):
    try:
        tok = fonte_api._token()
        for tentativa in (1, 2):
            dados = baixar(tok, get)
            if not dados["linhas"] and not dados["atualizacao"]:
                raise RuntimeError("a Zeladoria ainda não foi publicada pelo Nexus")
            if zc.conferir(dados):
                agora = time.time()
                with _lock:
                    _estado.update(dados=dados, ts=agora, erro=None)
                _grava_cache(dados, agora)
                return
            if tentativa == 1:
                time.sleep(espera)
        raise RuntimeError("a leitura não bateu com a aba de atualização duas vezes (publicação em andamento?)")
    except Exception as e:                                # noqa: BLE001 — fica a última leitura boa
        with _lock:
            _estado.update(erro="%s: %s" % (type(e).__name__, e), proxima=time.time() + COOLDOWN)
        print("[zeladoria] recarga falhou: %s" % _estado["erro"], flush=True)
    finally:
        with _lock:
            _estado["carregando"] = False


def _em_fundo(f):
    threading.Thread(target=f, name="thopen-zeladoria", daemon=True).start()


def dados(agora=None, iniciar=None):
    """O que houver agora — nunca espera a rede. Vencido ou vazio: dispara a recarga em segundo plano (uma só)."""
    agora = time.time() if agora is None else agora
    with _lock:
        if _estado["dados"] is None and not _estado["disco_lido"]:
            _estado["disco_lido"] = True
            d = _le_cache()
            if d:
                _estado.update(dados=d["dados"], ts=d.get("ts") or 0.0)
        disparar = agora - _estado["ts"] >= TTL and not _estado["carregando"] and agora >= _estado["proxima"]
        if disparar:
            _estado["carregando"] = True
        atual = _estado["dados"]
    if disparar:
        try:
            (iniciar or _em_fundo)(_recarrega)
        except Exception as e:                            # noqa: BLE001
            with _lock:
                _estado.update(carregando=False, erro="%s: %s" % (type(e).__name__, e), proxima=time.time() + COOLDOWN)
    return atual


def estado():
    return {"carregado_em": _estado["ts"], "erro": _estado["erro"], "carregando": _estado["carregando"]}
