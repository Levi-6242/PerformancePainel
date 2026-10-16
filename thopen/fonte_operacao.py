# -*- coding: utf-8 -*-
"""Leitura da Operação no Mês (Dashboard Thopen, 08/10/2026): falhas, rondas e de-para, pela mesma API do BD_Thopen.

Por que um leitor à parte, e não dentro do `fonte_api.workbook()`:
- a recarga do BD_Thopen segura o 1º acesso do cliente depois do TTL por ~130 s (medido em 08/10), DENTRO da
  requisição e sob o `_lock` do `_wb()`. Aqui a requisição NUNCA espera a rede: serve o que tem e recarrega em
  segundo plano (e a 1ª carga depois do boot vem do disco);
- abas de outro workbook no do BD_Thopen poderiam confundir o `_indexa`, que acha aba por assinatura de colunas.
LISTA BRANCA: das rondas (livro do App `rondas_app_campo`, desde 09/10) ficam usina_id, dia, horas, os níveis, o número
da OS, a unidade e os itens do checklist (rondas_cliente.da_app) — o técnico (nome e HMAC), a nota da ronda, as falhas
internas e qualquer texto livre não entram na memória nem no disco (o 5080 é público, sem senha). Das OS de string (rodada 2) fica o número da OS, só para não contar a mesma OS duas vezes — a resposta do
card nunca o leva (operacao_mes.CHAVES).
Nada aqui roda no import (sem thread, sem rede): a plataforma importa o `dashboard_thopen`, que importa este módulo.
"""
import gzip
import json
import os
import threading
import time

import fonte_api
import operacao_mes
import rondas_cliente

TTL = int(os.environ.get("THOPEN_OPERACAO_TTL", "600"))      # s — o mesmo ritmo do BD_Thopen
COOLDOWN = 60                                                 # s sem tentar de novo depois de uma falha
CACHE = os.environ.get("THOPEN_OPERACAO_CACHE") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "cache_operacao.json.gz")
SISTEMA_5080 = "BD_Thopen · Dados Gerais Usinas"
VERSAO_CACHE = 9        # 15/10, tarde: o nº da OS na disponibilidade_os_dia (o comentário curto)
# (workbook, aba) → (chave em `dados`, campos que ficam)
ABAS = {
    ("falhas_performance", "strings_episodios"): ("strings_episodios",
                                                  ("mes", "fonte", "cliente", "usina", "inversor", "string", "plant_id")),
    ("falhas_performance", "trackers_episodios"): ("trackers_episodios",
                                                   ("mes", "fonte", "cliente", "usina", "tracker", "plant_id",
                                                    "dias_comunicou", "dias_sem_prova")),
    ("falhas_performance", "cobertura"): ("cobertura",
                                          ("mes", "fonte", "cliente", "usina", "plant_id", "dias_strings",
                                           "dias_trackers")),
    # Rodada 2 (08/10, tarde — Ana e Levi): strings vêm das OS de recomposição de string do Fracttal ("Strings é OS"),
    # pela data do evento; trackers por dia, das ocorrências da plataforma com a usina comunicando. O status da OS fica
    # para tirar a cancelada; o texto da OS (observações) nunca é lido.
    ("falhas_performance", "strings_os"): ("strings_os",
                                           ("mes", "data_evento", "cliente", "usina", "plant_id", "inversor", "os",
                                            "status", "strings", "qtd", "origem")),
    ("falhas_performance", "trackers_dia"): ("trackers_dia",
                                             ("mes", "dia", "fonte", "cliente", "usina", "plant_id", "trackers",
                                              "qtd", "comunicou")),
    # rodada 4 (Levi, 09/10): a disponibilidade de cada usina por dia fechado, pela régua do Gerencial (Fracttal); o
    # usina_id sai do de-para do Nexus pelo nome do Fracttal (usina_ids, na leitura)
    ("falhas_performance", "disponibilidade_dia"): ("disponibilidade_dia",
                                                    ("mes", "dia", "usina", "usina_fracttal", "pot_kwp", "disp",
                                                     "h_perdidas")),
    # O comentário do dia (Levi, 14/10/2026: "A partir de outubro quero os comentários 100% OS Fracttal. Comentários e
    # disponibilidade!"): a parcela de cada OS em cada dia, que a plataforma tira da MESMA conta da disponibilidade_dia
    # (somadas, dão o h_perdidas do dia). Até 14/10 o 5080 lia as OS do mês (disponibilidade_os) e refazia a conta, e a
    # frase não batia com o número: "usina parada o dia todo" ao lado de 87,5% (Canarana 1, 08 a 12/10, na régua de
    # então, que tirava o dia pela geração; desde 15/10/2026 a geração não entra na disponibilidade). O 5080 é
    # público: o nº da OS fica de fora; o kWp afetado entra ("Cabine 2 parada o dia todo, 20% da potência da usina")
    # o nº da OS entra desde 15/10/2026, à tarde (Levi: "invés de OS do fracttal quero o número desse OS")
    ("falhas_performance", "disponibilidade_os_dia"): ("disponibilidade_os_dia",
                                                       ("mes", "dia", "usina", "usina_fracttal", "os", "tipo", "escopo", "kwp",
                                                        "inicio", "fim", "aberta", "trechos", "h_perdidas")),
    ("falhas_performance", "atualizacao"): ("atualizacao",
                                            ("mes", "periodo_fim", "atualizado_em", "strings_episodios",
                                             "trackers_episodios", "cobertura", "strings_os", "trackers_dia",
                                             "disponibilidade_dia", "disponibilidade_os_dia")),
    # rondas: o livro do App, regravado de hora em hora (Levi, 09/10: "tem que ser dinâmico"). Substituiu o
    # campo_nexus · rondas (parado em 02/10) e a carga única das rondas sem OS (06/10) — ver rondas_cliente
    ("rondas_app_campo", "OS de ronda"): ("rondas_com_os", rondas_cliente.CAMPOS_APP),
    ("cadastro_nexus", "de_para"): ("de_para", ("usina_id", "sistema", "chave_externa")),
}
_lock = threading.Lock()
_estado = {"dados": None, "ts": 0.0, "erro": None, "carregando": False, "proxima": 0.0, "disco_lido": False}


def _linhas(sid, get, tok):
    out, off = [], 0
    while True:
        rows = (get("/api/sheets/%d/rows?offset=%d&limit=1000" % (sid, off), tok) or {}).get("rows") or []
        out.extend(rows)
        if len(rows) < 1000:
            return out
        off += 1000


def _pid(v):
    """plant_id (e o número da OS) sempre texto: "297378" e 297378.0 (se a API um dia devolver número) têm de ser o
    mesmo cadastro — e a mesma OS."""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v)


def baixar(tok="", get=None):
    """Uma leitura completa → dados, com a lista branca aplicada. Levanta se a API falhar."""
    get = get or fonte_api._get
    sheets = {(s["workbook_key"], s["sheet_name"]): s for s in get("/api/sheets", tok)}
    dados = {k: [] for k, _ in ABAS.values()}
    rondas_app, de_para_todo = [], []        # convertidas no fim: o usina_id das rondas sai do de-para
    for (wb, aba), (k, campos) in ABAS.items():
        s = sheets.get((wb, aba))
        if not s:
            continue                          # aba ainda não publicada (a cobertura antes do deploy da plataforma)
        for r in _linhas(s["id"], get, tok):
            linha = dict(zip(r.get("headers") or [], r.get("values") or []))
            item = {c: linha.get(c) for c in campos}
            if k == "rondas_com_os":
                rondas_app.append(item)          # só as colunas de rondas_cliente.APP: o técnico nem chega aqui
                continue
            elif k == "de_para":
                de_para_todo.append(dict(item))
                if item.pop("sistema") != SISTEMA_5080:
                    continue
            for c in ("plant_id", "os"):
                if item.get(c) not in (None, ""):
                    item[c] = _pid(item[c])
            dados[k].append(item)
    mapa = rondas_cliente.mapa_usinas(de_para_todo)
    dados["rondas_com_os"] = [x for linha in rondas_app for x in rondas_cliente.da_app(linha, mapa)]
    for r in dados["disponibilidade_dia"] + dados["disponibilidade_os_dia"]:
        r["usina_ids"] = sorted(mapa.get(("nome", operacao_mes.chave(r.get("usina_fracttal"))), set()))
    return dados


def _grava_cache(dados, ts):
    try:
        # tmp por processo: com 2 workers do gunicorn (deploy/Procfile), os dois gravariam o MESMO .tmp ao mesmo tempo
        tmp = "%s.%d.tmp" % (CACHE, os.getpid())
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump({"versao": VERSAO_CACHE, "ts": ts, "dados": dados}, f, default=str)
        os.replace(tmp, CACHE)                            # troca atômica: nunca um cache pela metade
    except OSError as e:
        print("[operacao] não gravei o cache (%s)" % e, flush=True)


def _le_cache():
    """A última leitura boa em disco — só se tiver TODAS as chaves de hoje. Um cache gravado antes de uma aba nova
    entrar em ABAS faria a rota cair em KeyError até a 1ª recarga; sem ele, a tela diz "carregando" e a recarga vem."""
    try:
        with gzip.open(CACHE, "rt", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError, EOFError):
        return None
    if not isinstance(d, dict) or d.get("versao") != VERSAO_CACHE:
        return None                                       # de outra rodada: os campos guardados são outros
    dados = d.get("dados")
    if not isinstance(dados, dict) or any(not isinstance(dados.get(k), list) for k, _ in ABAS.values()):
        return None
    return d


def _recarrega(get=None, espera=5.0):
    """Roda em segundo plano. Duas tentativas: a leitura tem de bater com a aba `atualizacao`."""
    try:
        tok = fonte_api._token()
        for tentativa in (1, 2):
            dados = baixar(tok, get)
            if operacao_mes.conferir(dados):
                agora = time.time()
                with _lock:
                    _estado.update(dados=dados, ts=agora, erro=None)
                _grava_cache(dados, agora)
                return
            if tentativa == 1:
                time.sleep(espera)
        raise RuntimeError("a leitura não bateu com a aba atualizacao duas vezes (sync em andamento?)")
    except Exception as e:                                # noqa: BLE001 — fica a última leitura boa
        with _lock:
            _estado.update(erro="%s: %s" % (type(e).__name__, e), proxima=time.time() + COOLDOWN)
        print("[operacao] recarga falhou: %s" % _estado["erro"], flush=True)
    finally:
        with _lock:
            _estado["carregando"] = False


def _em_fundo(f):
    threading.Thread(target=f, name="thopen-operacao", daemon=True).start()


def dados(agora=None, iniciar=None):
    """O que houver agora — nunca espera a rede. Vencido ou vazio: dispara a recarga em segundo plano (uma só)."""
    agora = time.time() if agora is None else agora
    with _lock:
        if _estado["dados"] is None and not _estado["disco_lido"]:
            _estado["disco_lido"] = True
            d = _le_cache()
            if d:
                _estado.update(dados=d["dados"], ts=d.get("ts") or 0.0)
        disparar = (agora - _estado["ts"] >= TTL and not _estado["carregando"] and agora >= _estado["proxima"])
        if disparar:
            _estado["carregando"] = True
        atual = _estado["dados"]
    if disparar:
        try:
            (iniciar or _em_fundo)(_recarrega)
        except Exception as e:                            # noqa: BLE001 — sem thread, a próxima requisição tenta
            with _lock:
                _estado.update(carregando=False, erro="%s: %s" % (type(e).__name__, e),
                               proxima=time.time() + COOLDOWN)
    return atual


def estado():
    return {"carregado_em": _estado["ts"], "erro": _estado["erro"], "carregando": _estado["carregando"],
            "ttl": TTL, "cache": CACHE if os.path.exists(CACHE) else None}
