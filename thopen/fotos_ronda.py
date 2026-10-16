# -*- coding: utf-8 -*-
"""Fotos da ronda para o cliente (rodada 3, 09/10/2026): os anexos da OS de ronda no Fracttal. O App sobe cada foto
com a descrição "<item do checklist> — <resposta>" ("Sujidade dos módulos — 2"); a 1ª vira a capa ("Ronda <dia> —
<usina> · qualidade N%"). O mesmo caminho do Nexus (nexus/campo/ronda_fotos.py, 06/10): a LISTA vem da API REST, 1
pedido por OS guardado 20 min (o link vem assinado e vale 24 h); o ARQUIVO vem do S3 pelo link — não é pedido à API. O
link nunca sai para o navegador: o 5080 baixa e entrega.

Cota: o Fracttal limita 200 pedidos/min por EMPRESA, somando App de Campo, PCM, OS Creator e as duas plataformas, e
vive no limite — aqui é 1 pedido por OS aberta. Recusa por cota vira `Ocupado` na hora (esperar prenderia uma linha do
waitress). Credencial: FRACTTAL_CLIENT_ID / FRACTTAL_CLIENT_SECRET, a da plataforma (fonte_api.segredo). Sem ela, a
janela mostra a ronda e diz que as fotos não estão disponíveis. Nada roda no import.
"""
import io
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict

import fonte_api

BASE = (os.environ.get("FRACTTAL_BASE_URL") or "https://app.fracttal.com").rstrip("/")
LISTA_S = 1200               # a lista de anexos de uma OS, 20 min sem pedir de novo
LISTAS_MAX = 500
FOTOS_EM_MEMORIA = 40        # as últimas fotos inteiras (182 a 690 kB cada, medido em 06/10)
MINIS_EM_MEMORIA = 600       # as últimas miniaturas (7 a 14 kB)
FOTO_MAX = 10 * 1024 * 1024
MINI_PX = 240                # a janela mostra 46 px; 240 fica nítido em tela de alta densidade e na grade de 96 px
PAGINA = 100
TIMEOUT = 30
MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
# A Cloudflare na frente do Fracttal recusa o agente padrão do urllib ("Python-urllib/3.x": 403, "error code: 1010",
# medido em 09/10 no 1º ensaio com o Fracttal real — a plataforma não via isso porque usa o `requests`)
AGENTE = {"User-Agent": "gridco-dashboard-thopen/1.0 (+https://gridco.com.br)"}


class SemCredencial(RuntimeError):
    """FRACTTAL_CLIENT_ID/SECRET não configurados neste servidor."""


class Ocupado(RuntimeError):
    """O Fracttal recusou por cota (429; 406 era o limite antigo, por IP)."""


class SemFoto(LookupError):
    """O índice pedido não está nos anexos de imagem da OS."""


_trava = threading.Lock()
_tok = {"v": "", "exp": 0.0}
_listas = {}
_fotos = OrderedDict()
_minis = OrderedDict()


def _abrir(req, timeout=TIMEOUT):
    return urllib.request.urlopen(req, timeout=timeout)


def _token():
    with _trava:
        if _tok["v"] and time.time() < _tok["exp"]:
            return _tok["v"]
    cid, sec = fonte_api.segredo("FRACTTAL_CLIENT_ID"), fonte_api.segredo("FRACTTAL_CLIENT_SECRET")
    if not (cid and sec):
        raise SemCredencial("FRACTTAL_CLIENT_ID/FRACTTAL_CLIENT_SECRET não configurados")
    corpo = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": cid,
                                    "client_secret": sec}).encode()
    with _abrir(urllib.request.Request(BASE + "/oauth/token", data=corpo, method="POST", headers=AGENTE)) as r:
        d = json.loads(r.read().decode("utf-8"))
    with _trava:
        _tok.update(v=d["access_token"], exp=time.time() + int(d.get("expires_in", 3600)) - 60)
        return _tok["v"]


def _get(ep, params):
    url = "%s/api/%s?%s" % (BASE, ep, urllib.parse.urlencode(params))
    for tentativa in (1, 2):
        req = urllib.request.Request(url, headers=dict(AGENTE, Authorization="Bearer " + _token(),
                                                       Accept="application/json"))
        try:
            with _abrir(req) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 401 and tentativa == 1:
                with _trava:
                    _tok["v"] = ""                     # token venceu: pede outro uma vez
                continue
            if e.code in (406, 429):
                raise Ocupado("Fracttal recusou por cota (%d)" % e.code) from None
            raise
    raise RuntimeError("Fracttal recusou o token duas vezes")


def anexos(os_):
    """As imagens anexadas na OS, na ordem do Fracttal: [{desc, url, mime}]. O índice desta lista é o da rota."""
    chave = str(int(os_))
    with _trava:
        g = _listas.get(chave)
        if g and time.time() - g[0] < LISTA_S:
            return g[1]
    brutos, ini = [], 0
    while True:
        d = _get("work_orders_attachments", {"folio": chave, "limit": PAGINA, "start": ini})
        linhas = (d.get("data") if isinstance(d, dict) else d) or []
        brutos += linhas
        if len(linhas) < PAGINA:
            break
        ini += PAGINA
    out = []
    for a in brutos:
        url = str(a.get("value") or "")
        mime = MIME.get(url.split("?", 1)[0].rsplit(".", 1)[-1].lower())
        if url and mime:
            out.append({"desc": str(a.get("description") or "").strip(), "url": url, "mime": mime})
    with _trava:
        if len(_listas) >= LISTAS_MAX:
            _listas.clear()
        _listas[chave] = (time.time(), out)
    return out


def _baixar(url):
    with _abrir(urllib.request.Request(url, headers=AGENTE)) as r:
        corpo = r.read(FOTO_MAX + 1)
    if len(corpo) > FOTO_MAX:
        raise SemFoto("a foto no Fracttal é grande demais")
    return corpo


def _guardado(cache, limite, chave, fazer):
    with _trava:
        if chave in cache:
            cache.move_to_end(chave)
            return cache[chave]
    item = fazer()
    with _trava:
        cache[chave] = item
        while len(cache) > limite:
            cache.popitem(last=False)
    return item


def foto(os_, i):
    """(bytes, mime) da i-ésima imagem da OS. As últimas ficam em memória: abrir de novo não baixa de novo."""
    def fazer():
        lista = anexos(os_)
        if not 0 <= int(i) < len(lista):
            raise SemFoto("a OS %s não tem a foto %s" % (os_, i))
        return _baixar(lista[int(i)]["url"]), lista[int(i)]["mime"]
    return _guardado(_fotos, FOTOS_EM_MEMORIA, (str(os_), int(i)), fazer)


def _reduzir(corpo, mime):
    try:
        from PIL import Image, ImageOps
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(corpo))).convert("RGB")
        im.thumbnail((MINI_PX, MINI_PX))
        saida = io.BytesIO()
        im.save(saida, "JPEG", quality=80, optimize=True)
        return saida.getvalue(), "image/jpeg"
    except Exception:       # noqa: BLE001 — sem Pillow ou imagem que ele não abre: vai a foto inteira
        return corpo, mime


def miniatura(os_, i):
    """A foto reduzida para a janela (a do App vem com 1280x1700: 182 a 690 kB a inteira, 7 a 14 kB a miniatura).
    Sem o Pillow, a inteira."""
    return _guardado(_minis, MINIS_EM_MEMORIA, (str(os_), int(i)), lambda: _reduzir(*foto(os_, i)))
