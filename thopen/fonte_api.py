# -*- coding: utf-8 -*-
"""Fonte de dados do dashboard Thopen: a Gridco Performance API (PostgreSQL).

OBJETIVO (Levi, 28/08/2026): o BD_Thopen.xlsx continua sendo onde a COLETA ESCREVE; o
dashboard passa a LER tudo do PostgreSQL. Um `sync_gridco_api.py` leva o arquivo para o
banco; daqui para a frente o 5080 só conversa com o banco.

COMO, SEM REESCREVER O DASHBOARD: em vez de trocar os ~20 pontos de leitura, monta-se um
`openpyxl.Workbook` EM MEMORIA com o conteudo que a API devolve. `_range_rows`, `_header`,
`_cols` e `_ref_da_aba` continuam operando sobre worksheets, exatamente como antes — nenhuma
regra de negocio muda de lugar. Nao ha arquivo intermediario.

A POSICAO DA LINHA E' SAGRADA: a API devolve `row_number`, a posicao ORIGINAL no Excel, e a
celula e' escrita nela. E' isso que mantem cabecalho na linha 2 ou 3 (Historico, Clientes,
Info Mensal tem a linha 1 vazia) e o `_ref_da_aba` achando a linha certa. Escrever "da linha 1
em diante" quebraria os leitores em silencio.

DATA VOLTA A SER DATA: o banco guarda a data como TEXTO ISO ("2026-08-26") desde a migracao de
25/08. O dashboard compara `dt.date`, entao o texto e' reconvertido aqui. Sem isso, todo
filtro de periodo passa a nao casar — e sem erro nenhum.

DESEMPENHO: 99 abas / 41 mil linhas em ~4 s com 16 threads (contra 67 s em serie). Fica em
cache por TTL; o `/api/t/reload` derruba o cache, como sempre fez com o arquivo.

SE A API CAIR: (1) o workbook que ja' esta' na memoria; (2) o CACHE EM DISCO da ultima leitura
boa (gzip, 1,7 MB). Nao ha' terceiro degrau — o dashboard nao abre arquivo nenhum. A tela mostra
a idade REAL do dado nos dois casos: mentir sobre frescor e' pior do que ficar sem dado.
"""
import datetime as dt
import gzip
import io
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import openpyxl

_AQUI = os.path.dirname(os.path.abspath(__file__))

BASE = os.environ.get("GRIDCO_API_BASE", "https://app.gridco.com.br/db_performace").rstrip("/")
WORKBOOK = os.environ.get("GRIDCO_API_WORKBOOK", "bd_thopen")
TTL = int(os.environ.get("GRIDCO_API_TTL", "600"))          # s
THREADS = 16
# timeout CURTO + retry, e nao um timeout longo: com 116 requisicoes em paralelo, uma conexao
# que trava sozinha (ja' aconteceu na primeira carga) segurava a carga inteira por 3 min. Melhor
# desistir em 30 s e tentar de novo — as 116 juntas levam ~5 s quando esta' tudo bem.
TIMEOUT = 30
TENTATIVAS = 3
# Ultima leitura boa em disco. Em container efemero some no re-deploy (e tudo bem: o proximo
# boot busca a API). Aponte GRIDCO_API_CACHE para um volume persistente se quiser que sobreviva.
CACHE = os.environ.get("GRIDCO_API_CACHE") or os.path.join(_AQUI, "cache_bd_thopen.json.gz")

_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$")
_lock = threading.Lock()
COOLDOWN = 60      # s sem bater na API depois de uma falha
_cache = {"ts": 0.0, "wb": None, "erro": None, "origem": None, "proxima": 0.0}


def _token():
    """Bearer do tokens.txt da raiz. Sem ele a API recusa a escrita; a leitura ainda e'
    aberta, mas mandamos assim mesmo — se um dia fechar, o dashboard nao para."""
    v = os.environ.get("GRIDCO_SQL_TOKEN")
    if v:
        return v.strip()
    aqui = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(aqui, "..", "tokens.txt"),
                 os.path.join(aqui, "tokens.txt")):
        try:
            for l in io.open(cand, encoding="utf-8", errors="surrogateescape"):
                m = re.match(r"\s*GRIDCO_SQL_TOKEN\s*=\s*(.+)", l)
                if m:
                    return m.group(1).strip()
        except OSError:
            continue
    return ""


def _get(caminho, tok, tentativas=TENTATIVAS):
    erro = None
    for i in range(tentativas):
        req = urllib.request.Request(BASE + caminho,
                                     headers={"Authorization": "Bearer " + tok} if tok else {})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code < 500:                 # 401/404 nao melhora tentando de novo
                raise
            erro = e
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            erro = e
        time.sleep(0.5 * (i + 1))
    raise erro


def _valor(v):
    """Texto ISO volta a ser date/datetime; o resto passa como veio."""
    if isinstance(v, str):
        m = _ISO.match(v.strip())
        if m:
            a, mes, d, hh, mm, ss = m.groups()
            try:
                if hh is None:
                    return dt.date(int(a), int(mes), int(d))
                return dt.datetime(int(a), int(mes), int(d), int(hh), int(mm), int(ss or 0))
            except ValueError:
                return v
    return v


def _ignorar(nome):
    """Aba APOSENTADA: existe no banco mas nao existe mais no BD_Thopen.xlsx.

    A API nao tem DELETE de aba (so' de linha) e o sync so' escreve — entao aba removida do
    arquivo ficaria orfa' no banco para sempre, e sem este filtro a migracao para o PostgreSQL
    faria NASCER usina no seletor do CLIENTE. Aconteceu com duas: "Rodrigues" (contador travado
    em 12.298,3 kWh desde nov/2025, substituida por Rodrigues 1 e 2) e "Caroa - Cliente"
    (absorvida pelo "Historico Carteira").

    A convencao e' RENOMEAR com o prefixo "zz", nunca apagar: o dado fica guardado e volta com
    outro rename. As duas ja' foram renomeadas no banco em 28/08 — por isso aqui nao ha' mais
    lista de nomes, so' a regra. GRIDCO_API_IGNORA acrescenta nomes avulsos, se um dia precisar.
    """
    n = nome.strip().lower()
    return n.startswith("zz") or n in _IGNORA


_IGNORA = {s.strip().lower() for s in
           os.environ.get("GRIDCO_API_IGNORA", "").split(";") if s.strip()}


def _baixa(tok):
    """Pacote cru da API: [{aba, header_row, headers, linhas: [[row_number, valores...]]}].

    Separado da montagem do workbook porque e' ele que vai para o cache em disco — JSON puro,
    sem openpyxl no meio."""
    sheets = [s for s in _get("/api/sheets", tok)
              if s["workbook_key"] == WORKBOOK and not _ignorar(s["sheet_name"])]
    if not sheets:
        raise RuntimeError("workbook %r sem abas na API" % WORKBOOK)
    tarefas = []
    for s in sheets:
        off = 0
        while off < max(s["row_count"], 1):
            tarefas.append((s["id"], off))
            off += 1000

    def baixa(t):
        return t[0], _get("/api/sheets/%d/rows?offset=%d&limit=1000" % t, tok)

    blocos = {}
    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        for sid, d in ex.map(baixa, tarefas):
            blocos.setdefault(sid, []).extend(d.get("rows") or [])

    pacote = []
    for s in sheets:
        linhas, hdr = [], None
        for r in blocos.get(s["id"]) or []:
            n = r.get("row_number")
            if not isinstance(n, int) or n < 1:
                continue
            hdr = hdr or r.get("headers")
            linhas.append([n] + list(r.get("values") or []))
        pacote.append({"aba": s["sheet_name"], "header_row": s.get("header_row") or 1,
                       "headers": hdr, "linhas": linhas})
    return pacote


def _workbook_de(pacote):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for s in pacote:
        ws = wb.create_sheet(s["aba"][:31])
        for linha in s["linhas"]:
            n = linha[0]
            for c, v in enumerate(linha[1:], start=1):
                if v is not None and v != "":
                    ws.cell(row=n, column=c, value=_valor(v))
        # A API guarda o cabecalho A' PARTE (campo `headers`), fora das linhas de dado — entao
        # ele precisa ser materializado, e NA LINHA CERTA: `header_row`, nao a 1. Sete abas do
        # BD_Thopen tem uma linha de titulo acima do cabecalho (Historico, Clientes, Dados
        # Gerais Usinas, Dados Mensais 2026, Santana, Sapopema, Saturnino, header_row=2).
        # Escrever na linha 1 fazia o `_ref_da_aba` fechar o intervalo uma linha acima e a
        # primeira linha de dado virava cabecalho — 119 celulas fora do lugar na conferencia.
        hdr, hr = s.get("headers"), s.get("header_row") or 1
        if hdr and not any(ws.cell(row=hr, column=c).value for c in range(1, len(hdr) + 1)):
            for c, h in enumerate(hdr, start=1):
                if h not in (None, ""):
                    ws.cell(row=hr, column=c, value=h)
    return wb


def _grava_cache(pacote, ts):
    """Ultima leitura boa, em disco. E' o UNICO plano B: o dashboard nao abre planilha nenhuma,
    entao sem isto API fora do ar + processo reiniciado = tela muda. Com o cache, sobe com o dado
    da ultima leitura e DIZ a idade dele."""
    try:
        tmp = CACHE + ".tmp"
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump({"ts": ts, "workbook": WORKBOOK, "pacote": pacote}, f)
        os.replace(tmp, CACHE)                       # troca atomica: nunca um cache pela metade
    except OSError as e:
        print("[fonte_api] nao consegui gravar o cache (%s)" % e, flush=True)


def _le_cache():
    try:
        with gzip.open(CACHE, "rt", encoding="utf-8") as f:
            d = json.load(f)
        if d.get("workbook") != WORKBOOK:
            return None
        return d
    except (OSError, ValueError, EOFError):
        return None


def workbook(forcar=False):
    """Workbook em memoria vindo da API. Se ela nao responder, devolve a ultima leitura boa —
    da memoria, ou do cache em disco quando o processo acabou de subir. None so' quando nao ha'
    nem uma coisa nem outra — e ai' o dashboard nao tem o que servir, e diz isso na cara."""
    with _lock:
        agora = time.time()
        if not forcar and _cache["wb"] is not None and (agora - _cache["ts"]) < TTL:
            return _cache["wb"]
        # CARENCIA depois de uma falha: sem ela, com a API PENDURADA (nao recusando, pendurada)
        # cada acesso do usuario pagaria 3 tentativas x 30 s = 90 s antes de mostrar a tela. Com
        # a carencia, a primeira falha custa isso e as seguintes sao instantaneas pelo cache.
        if not forcar and _cache["wb"] is not None and agora < _cache["proxima"]:
            return _cache["wb"]
        tok = _token()
        try:
            t0 = time.time()
            pacote = _baixa(tok)
            wb = _workbook_de(pacote)
            _cache.update(ts=agora, wb=wb, erro=None, origem="api", proxima=0.0)
            print("[fonte_api] %s: %d aba(s) em %.1fs"
                  % (WORKBOOK, len(wb.sheetnames), time.time() - t0), flush=True)
            _grava_cache(pacote, agora)
            return wb
        except Exception as e:
            _cache["erro"] = "%s: %s" % (type(e).__name__, e)
            _cache["proxima"] = time.time() + COOLDOWN
            print("[fonte_api] FALHOU (%s)" % _cache["erro"], flush=True)
            if _cache["wb"] is not None:
                return _cache["wb"]      # segue com o que ja' estava carregado
            d = _le_cache()
            if d:
                wb = _workbook_de(d["pacote"])
                # ts do CACHE, nao de agora: a tela mostra a idade real do dado. Mentir sobre
                # frescor e' pior do que ficar sem dado.
                _cache.update(ts=d["ts"], wb=wb, origem="cache")
                print("[fonte_api] subiu pelo CACHE EM DISCO de %s"
                      % time.strftime("%d/%m %H:%M", time.localtime(d["ts"])), flush=True)
                return wb
            return None


def invalidar():
    with _lock:
        _cache.update(ts=0.0, proxima=0.0)   # o botao Atualizar ignora a carencia


def estado():
    return {"ttl": TTL, "carregado_em": _cache["ts"], "origem": _cache["origem"],
            "idade": (time.time() - _cache["ts"]) if _cache["ts"] else None,
            "abas": len(_cache["wb"].sheetnames) if _cache["wb"] is not None else 0,
            "erro": _cache["erro"], "base": BASE, "workbook": WORKBOOK,
            "cache": CACHE if os.path.exists(CACHE) else None}
