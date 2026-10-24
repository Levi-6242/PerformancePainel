# -*- coding: utf-8 -*-
"""O trip das OS no comentário do dia (Levi, 23/10/2026: "Desligamento Usina Trip 27/86 de 13/10 às 17:02h a 14/10 às
07:29h; religamento, OS 16249"; "VOCÊ BUSCARÁ PRIMEIROS NAS SUBTAREFAS Categoria e proteção, CASO NÃO TENHA VAI PROCURAR
NA NOTA DA OS. GOSTARIA QUE O BOTÃO ATUALIZAR PUXASSE DIRETAMENTE").

De onde vem: o COS do Nexus abre a OS de religamento com a subtarefa "Categoria e proteção" ("Proteção atuou — 27 e
86") e a nota "UFV: ... | Proteção: 27/86 | Ação: ... | Falha: ...". A subtarefa pode vir sem código (a OS 16249, em
23/10: "Religamento ", com o 27/86 só na nota); então vale a nota. "Sem proteção/trip ativo" na subtarefa decide: sem
trip, e a nota não é lida. Na nota só o campo Proteção conta: a Falha repete os códigos e pode citar outro número.

Como: 1 pedido por OS (work_orders_subtasks) e, sem código nela, mais 1 (work_orders), pela mesma credencial e o mesmo
cuidado de cota das fotos da ronda (fotos_ronda._get: 200 pedidos/min por EMPRESA, somando App, PCM e plataformas). O
que achou fica guardado TTL (6 h) em memória e em disco, com o "sem trip" também. A rota da tela nunca espera o
Fracttal: o que falta vai a uma linha em segundo plano e a tela relê; o botão Atualizar busca de novo, direto, as OS da
usina na tela. Recusa por cota (429): para tudo por ESPERA_COTA e o comentário sai sem o trip, nunca com erro. Nada
roda no import. `THOPEN_TRIP=0` desliga (a frase volta a ser a de antes).
"""
import json
import os
import re
import threading
import time
import unicodedata

import fotos_ronda

TTL = int(os.environ.get("THOPEN_TRIP_TTL") or 6 * 3600)
CACHE = os.environ.get("THOPEN_TRIP_CACHE") or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                            "cache_trip_os.json")
ESPERA_COTA = 120            # s sem pedir nada depois de um 429
PAUSA = 0.5                  # s entre um pedido e outro: no máximo ~120/min, e só enquanto houver OS a buscar
LIMITE_ATUALIZAR = 25        # s que o botão Atualizar espera; o que sobrar vai para o segundo plano
VERSAO = 1

# os códigos ANSI da lista do COS (nexus/torres/oscreator/os_creator/cos_spec.PROTECOES)
_COD = re.compile(r"(?<![0-9A-Za-z])(50N|51N|59N|67N|27|32|46|47|50|51|59|67|78|81|86)(?![0-9A-Za-z])", re.I)
_PROT = re.compile(r"prote[cç][aã]o\s*:\s*([^|\n]*)", re.I)

_trava = threading.Lock()
_mem = {}                    # "16249" -> (quando, "27/86" ou None)
_estado = {"disco": False, "cota_ate": 0.0, "fila": set(), "linha": None}


def _agora():
    return time.time()


def _relogio():
    return time.monotonic()


def _get(ep, params):
    return fotos_ronda._get(ep, params)


def ligado():
    return os.environ.get("THOPEN_TRIP", "1").strip() != "0"


def _sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s or "")) if unicodedata.category(c) != "Mn").lower()


def _sem_trip(txt):
    t = _sem_acento(txt)
    return "sem protecao" in t or "sem trip" in t


def codigos(txt):
    """"Proteção atuou — 27 e 86" → ["27", "86"]; número de ativo ou ano não casa (o código é palavra inteira)."""
    out = []
    for c in _COD.findall(str(txt or "")):
        c = c.upper()
        if c not in out:
            out.append(c)
    return out


def _da_subtarefa(subtarefas):
    """(decidiu, trip): a subtarefa "Categoria e proteção" com código, ou com "Sem proteção/trip ativo", decide."""
    for s in subtarefas or []:
        if _sem_acento(s.get("description")).strip() == "categoria e protecao":
            v = s.get("value")
            if _sem_trip(v):
                return True, None
            cs = codigos(v)
            if cs:
                return True, "/".join(cs)
    return False, None


def _da_nota(nota):
    """O campo Proteção da nota ("Proteção: 27/86"); "--/--" ou "Sem proteção/trip ativo" = sem trip."""
    m = _PROT.search(str(nota or ""))
    if not m or _sem_trip(m.group(1)):
        return None
    return "/".join(codigos(m.group(1))) or None


def trip_de(subtarefas, nota):
    """O trip da OS ("27/86") ou None: a subtarefa primeiro; sem código nela, a nota."""
    decidiu, t = _da_subtarefa(subtarefas)
    return t if decidiu else _da_nota(nota)


def _linhas(d):
    return (d.get("data") if isinstance(d, dict) else d) or []


def _ler(n):
    decidiu, t = _da_subtarefa(_linhas(_get("work_orders_subtasks/", {"folio": n})))
    if decidiu:
        return t
    notas = [str(w.get("task_note") or "") for w in _linhas(_get("work_orders/", {"folio": n}))]
    return _da_nota("\n".join(notas))


def _carregar():
    """Lê o disco uma vez por processo (fora do import)."""
    if _estado["disco"]:
        return
    _estado["disco"] = True
    try:
        with open(CACHE, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return
    if isinstance(d, dict) and d.get("versao") == VERSAO:
        for n, (q, t) in (d.get("itens") or {}).items():
            _mem.setdefault(str(n), (float(q), t))


def _gravar():
    with _trava:
        itens = {n: list(v) for n, v in _mem.items() if _agora() - v[0] < TTL}
    tmp = "%s.%d.tmp" % (CACHE, os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"versao": VERSAO, "itens": itens}, f)
        os.replace(tmp, CACHE)                 # troca atômica: nunca um arquivo pela metade
    except OSError:
        pass                                   # sem disco, fica a memória


def guardados(oss):
    """({OS: trip ou None} das guardadas e dentro do TTL, [OS que faltam])."""
    with _trava:
        _carregar()
        achou, falta = {}, []
        for n in (str(x) for x in oss):
            v = _mem.get(n)
            if v and _agora() - v[0] < TTL:
                achou[n] = v[1]
            elif n not in falta:
                falta.append(n)
        return achou, falta


def buscar(oss, forcar=False, limite_s=None):
    """Busca no Fracttal as OS que faltam (todas, com `forcar`) e devolve {OS: trip ou None} do que se sabe. Para no
    429 (e não pede nada por ESPERA_COTA), sem credencial ou no fim de `limite_s`; o que não leu fica para depois."""
    oss = [str(x) for x in oss]
    achou, falta = guardados(oss)
    alvo = oss if forcar else falta
    ini, leu = _relogio(), False
    for n in alvo:
        if _agora() < _estado["cota_ate"]:
            break
        if limite_s is not None and _relogio() - ini > limite_s:
            break
        if leu and PAUSA:
            time.sleep(PAUSA)
        try:
            t = _ler(n)
        except fotos_ronda.Ocupado:
            _estado["cota_ate"] = _agora() + ESPERA_COTA
            break
        except fotos_ronda.SemCredencial:
            _estado["cota_ate"] = _agora() + ESPERA_COTA      # sem credencial não adianta tentar a cada tela
            break
        except Exception:                                     # noqa: BLE001 — rede caída: o comentário sai sem o trip
            break
        leu = True
        with _trava:
            _mem[n] = (_agora(), t)
        achou[n] = t
    if leu:
        _gravar()
    return achou


def _trabalhar():
    while True:
        with _trava:
            fila = sorted(_estado["fila"])
            if not fila or _agora() < _estado["cota_ate"]:
                _estado["fila"].clear()
                _estado["linha"] = None
                return
        buscar(fila)
        _, falta = guardados(fila)
        with _trava:
            _estado["fila"] -= set(fila)
            if set(falta) >= set(fila):                       # não andou (cota, rede): desiste até a próxima tela
                _estado["fila"].clear()
                _estado["linha"] = None
                return


def em_segundo_plano(oss):
    """Põe as OS na fila da linha de busca (uma só, para não somar pedidos). True = há o que esperar: a tela relê."""
    _, falta = guardados(oss)
    if not falta or _agora() < _estado["cota_ate"]:
        return False
    with _trava:
        _estado["fila"].update(falta)
        if _estado["linha"] is None:
            _estado["linha"] = threading.Thread(target=_trabalhar, name="thopen-trip", daemon=True)
            _estado["linha"].start()
    return True


def _zerar(disco=True):
    """Para os testes: esquece a memória (e o arquivo, com `disco`)."""
    with _trava:
        _mem.clear()
        _estado.update(disco=False, cota_ate=0.0, fila=set(), linha=None)
    if disco:
        try:
            os.remove(CACHE)
        except OSError:
            pass
