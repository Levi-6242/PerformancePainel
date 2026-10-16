# -*- coding: utf-8 -*-
"""Ler e acrescentar linhas num livro da API do banco (db_performace), com a conferência antes e depois de gravar — o
caminho do 5080 para os livros que ELE grava (as senhas do login, 14/10/2026). A gravação troca o livro inteiro
(`sync-xlsx?replace=true`, como os livros do Nexus): por isso relê o que já está lá, e uma leitura que não bate com a
contagem da API NUNCA regrava (apagaria linhas). Depois de gravar, relê e confere a contagem.

O `contestacao_banco.py` (13/10) faz a mesma conta para o livro dele; este é o genérico. Os três pedaços de rede
(`_get`, `_criar_livro`, `_trocar_livro`) são os que os testes trocam por uma API falsa.
"""
import io
import json
import threading
import urllib.request
import uuid

import fonte_api


class GravacaoErro(RuntimeError):
    """A gravação não aconteceu (ou não confere): o livro do banco ficou como estava."""


_TRAVAS: dict = {}
_TRAVA_GERAL = threading.Lock()


def _trava(livro):
    with _TRAVA_GERAL:
        return _TRAVAS.setdefault(livro, threading.Lock())


def _get(caminho, tok):
    return fonte_api._get(caminho, tok)


def _post(caminho, corpo, tipo, tok):
    req = urllib.request.Request(fonte_api.BASE + caminho, data=corpo, method="POST",
                                 headers={"Content-Type": tipo, "Authorization": "Bearer " + tok})
    with urllib.request.urlopen(req, timeout=120) as r:
        st = getattr(r, "status", 200)
    if not 200 <= st < 300:
        raise GravacaoErro("a API respondeu %s" % st)


def _criar_livro(livro, nome, tok):
    _post("/api/workbooks", json.dumps({"key": livro, "display_name": nome}).encode("utf-8"), "application/json", tok)


def _trocar_livro(livro, xlsx, tok):
    fronteira = "----thopen" + uuid.uuid4().hex
    corpo = (("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s.xlsx\"\r\n"
              "Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n")
             % (fronteira, livro)).encode("utf-8") + xlsx + ("\r\n--%s--\r\n" % fronteira).encode("utf-8")
    _post("/api/workbooks/%s/sync-xlsx?replace=true" % livro, corpo, "multipart/form-data; boundary=" + fronteira, tok)


def ler(livro, aba, tok):
    """As linhas da aba. Livro ou aba que não existe = []. A leitura tem de bater com a contagem da API: senão levanta."""
    s = next((x for x in _get("/api/sheets", tok) or []
              if x.get("workbook_key") == livro and x.get("sheet_name") == aba), None)
    if not s:
        return []
    out, off = [], 0
    while True:
        r = _get("/api/sheets/%d/rows?offset=%d&limit=1000" % (int(s["id"]), off), tok)
        rows = r.get("rows", []) if isinstance(r, dict) else (r or [])
        out += [dict(zip(x.get("headers") or [], x.get("values") or [])) for x in rows]
        if len(rows) < 1000:
            break
        off += 1000
    esperado = s.get("row_count")
    if esperado is not None and int(esperado) != len(out):
        raise GravacaoErro("li %d linhas de %s e a API diz %s" % (len(out), livro, esperado))
    return out


def xlsx(aba, cab, linhas):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = aba
    ws.append(list(cab))
    for l in linhas:
        ws.append([l.get(c) for c in cab])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def acrescentar(livro, nome, aba, cab, novas, tok):
    """Soma as linhas novas ao livro (só uma aba) e confere. Devolve quantas linhas a aba tem depois."""
    if not tok:
        raise GravacaoErro("sem o token de escrita do banco (GRIDCO_SQL_TOKEN)")
    with _trava(livro):
        atuais = ler(livro, aba, tok)
        if livro not in {w.get("key") for w in _get("/api/workbooks", tok) or []}:
            _criar_livro(livro, nome, tok)          # o 1º registro cria o livro (o nome é para sempre)
        todas = atuais + list(novas)
        _trocar_livro(livro, xlsx(aba, cab, todas), tok)
        depois = ler(livro, aba, tok)
        if len(depois) != len(todas):
            raise GravacaoErro("enviei %d linhas e o banco tem %d" % (len(todas), len(depois)))
        return len(depois)
