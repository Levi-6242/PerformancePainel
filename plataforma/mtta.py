# -*- coding: utf-8 -*-
"""Acompanhamento COS — MTTA: quanto tempo o COS leva do EVENTO até a OS aparecer no Fracttal.

Módulo PURO (sem Flask, sem rede, sem arquivo): o app.py varre o `work_orders/` e injeta as tarefas;
os testes injetam linhas fabricadas. Régua fechada na sondagem de 22/09/2026 (histórico inteiro do
Fracttal: 34.832 tarefas, 4.643 OSs dos três tipos desde 08/12/2025) — cada decisão abaixo veio de
um caso que apareceu nela:

- Contam as OSs de Religamento, Religamento Remoto e Corretiva Emergencial, os MESMOS tipos da
  Disponibilidade (importados de lá). Canceladas nunca contam, nem as da planta de teste.
- Tempo = `creation_date` − `event_date`, os dois em UTC no Fracttal. OS com várias tarefas-alvo
  usa o evento mais antigo (o começo da falha).
- Operador = quem CRIOU a OS (`created_by`). O Fracttal grafa a mesma conta com e sem espaço
  ("LuelySantos" / "Luely  Santos"), e várias contas vêm com `code_create_by` nulo: a chave é o
  nome sem espaço nenhum, e a tela mostra a grafia com espaço.
- Não é reconhecimento: evento DEPOIS da criação (OS programada — 21 no histórico) e evento
  carimbado no segundo da criação (89 OSs, 73 delas em ago/26: o app gravou "agora" porque o
  `create_os_rpc` cai no `datetime.now()` sem `event_date`). Contadas, dariam "0 min" a quem não
  informou a hora — a mediana de um operador cairia de 52 para 40 min.
- O número mede evento → REGISTRO. No COS a OS nasce concluída, então inclui o tempo de religar.
  Ponto cego que o dado não resolve: a tela do COS abre com o evento em "agora − 10 min", e o campo
  guarda os segundos mesmo quando o operador edita a hora (testado no QDateTimeEdit) — não há como
  saber se a hora foi corrigida.
"""
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from disponibilidade import TIPOS_ALVO as TIPOS

BRT = timezone(timedelta(hours=-3))

# Rótulo de tela de cada tipo, na ordem em que a tela os lista.
ROTULO = {"religamento remoto": "Religamento Remoto", "religamento": "Religamento",
          "corretiva emergencial": "Corretiva Emergencial"}
ORDEM_TIPOS = ["Religamento Remoto", "Religamento", "Corretiva Emergencial"]

# O que a varredura guarda de cada tarefa. O resto da linha do work_orders/ não serve à régua e
# multiplicaria a base em disco (a linha inteira tem ~80 chaves).
CAMPOS = ("wo_folio", "id_work_orders_tasks", "id_task", "creation_date", "event_date",
          "id_status_work_order", "tasks_log_task_type_main", "created_by", "code",
          "groups_1_description", "parent_description", "items_log_description")

CARIMBO_S = 10            # evento até 10 s antes da criação = carimbo do app (o real vai de 0,1 a 5 s)
STATUS_CANCELADA = 4
# Rajada = o mesmo operador registrando 3+ ocorrências DIFERENTES em 30 min (±15). É o registro
# acumulado do fim de turno — 05h e 16–17h concentram quase todas —, que infla o tempo sem ser
# demora de reconhecer. Lote (um evento, vários ativos) não conta como ocorrências diferentes.
RAJADA_JANELA_MIN = 15
RAJADA_MIN_OCORRENCIAS = 3


def dt(s):
    """ISO do Fracttal → datetime com fuso. Sem fuso declarado, trata como Brasília."""
    if not s:
        return None
    try:
        x = datetime.fromisoformat(str(s).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return x if x.tzinfo else x.replace(tzinfo=BRT)


def nome(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def chave(s):
    return re.sub(r"\s", "", str(s or "")).casefold()


def eh_teste(w):
    # planta "TESTE - PA" (TESTE100-CABN1, TESTE100-INVR1.x, THPN-TESTE): OSs criadas para testar
    # o OS Creator, com eventos em horas redondas e registro dias depois
    cod = str(w.get("code") or "").upper()
    return cod.startswith("TESTE") or cod == "THPN-TESTE" or "TESTE - PA" in str(w.get("parent_description") or "")


def site_de(w):
    """Nome do site. `groups_1_description` vem vazio em OSs reais (THPN-MRJ100, JCD100-CABN1…):
    então vale o caminho do ativo ("// Athon/ Athon - Jacundá 1 - PA/ ") ou o próprio ativo."""
    s = nome(w.get("groups_1_description"))
    if s:
        return s
    segs = [p.strip() for p in str(w.get("parent_description") or "").strip("/ ").split("/") if p.strip()]
    if len(segs) >= 2:
        return nome(segs[1])
    ild = re.sub(r"\s*\{[^}]*\}\s*$", "", str(w.get("items_log_description") or ""))
    return nome(re.split(r"\s{2,}", ild, maxsplit=1)[0])


def usina_curta(site):
    """'Athon - Capitão Poço 1 - PA' → 'Capitão Poço 1' (sem cliente e sem UF)."""
    partes = [p.strip() for p in str(site or "").split(" - ") if p.strip()]
    util = [p for p in partes if not re.fullmatch(r"[A-Z]{2}", p)]
    if len(util) > 1:
        return util[1]
    return util[0] if util else str(site or "")


def reduzir(w):
    return {c: w.get(c) for c in CAMPOS}


def _tipo(w):
    return nome(w.get("tasks_log_task_type_main")).lower()


def montar(linhas):
    """Tarefas do work_orders/ → OSs com a régua aplicada.
    → {'oss': [...], 'canceladas': n, 'teste': n, 'total_tarefas': n}. Cada OS leva `cls`:
    'ok' (entra na conta), 'evento_depois' ou 'evento_eh_criacao' (fora, contadas na tela)."""
    por_os, cancel, teste = {}, set(), set()
    for w in linhas:
        if _tipo(w) not in TIPOS:
            continue
        f = str(w.get("wo_folio") or "")
        if not f:
            continue
        if w.get("id_status_work_order") == STATUS_CANCELADA:
            cancel.add(f)
            continue
        if eh_teste(w):
            teste.add(f)
            continue
        e = dt(w.get("event_date"))
        if e is None:
            continue
        atual = por_os.get(f)
        if atual is None or e < dt(atual.get("event_date")):
            por_os[f] = w
    grafias = defaultdict(Counter)
    oss = []
    for f, w in por_os.items():
        c, e = dt(w.get("creation_date")), dt(w.get("event_date"))
        if c is None:
            continue
        k = chave(w.get("created_by"))
        grafias[k][nome(w.get("created_by"))] += 1
        site = site_de(w)
        seg = (c - e).total_seconds()
        oss.append({"folio": int(f) if f.isdigit() else f, "op": k, "cri": c, "ev": e, "mtta": seg / 60,
                    "cls": "evento_depois" if seg < 0 else ("evento_eh_criacao" if seg < CARIMBO_S else "ok"),
                    "tipo": ROTULO[_tipo(w)], "site": site, "usina": usina_curta(site),
                    # "Grid Co." (ativo genérico de usina de terceiros) não tem " - ": é o próprio cliente
                    "cliente": site.split(" - ")[0].strip(),
                    "h_ev": e.astimezone(BRT).hour, "h_cri": c.astimezone(BRT).hour})
    exib = {}
    for k, cont in grafias.items():
        com_espaco = [(n, q) for n, q in cont.items() if " " in n]
        exib[k] = max(com_espaco or cont.items(), key=lambda x: x[1])[0]
    for o in oss:
        o["nome"] = exib[o["op"]] or "(sem nome)"
    oss.sort(key=lambda o: o["cri"])
    _marca_lotes(oss)
    _marca_rajadas(oss)
    return {"oss": oss, "canceladas": len(cancel - set(por_os)),
            "teste": len(teste - set(por_os) - cancel), "total_tarefas": len(linhas)}


def _episodio(o):
    return (o["op"], o["site"], o["ev"].replace(second=0, microsecond=0))


def _marca_lotes(oss):
    """Lote = o mesmo operador, a mesma usina e o mesmo minuto de evento em várias OSs (vários ativos
    de uma queda só). A 1ª criada fica marcada para a tela poder contar cada evento uma vez.
    Só entre as OSs que ENTRAM na conta: se a 1ª do lote fosse uma de evento carimbado (fora),
    "lote conta 1 vez" apagaria o evento inteiro — nenhuma da conta seria a 1ª."""
    grupos = defaultdict(list)
    for o in oss:
        o["lote_n"], o["lote_1o"] = 1, True
        if o["cls"] == "ok":
            grupos[_episodio(o)].append(o)
    for lst in grupos.values():
        lst.sort(key=lambda o: o["cri"])
        for i, o in enumerate(lst):
            o["lote_n"], o["lote_1o"] = len(lst), i == 0


def _marca_rajadas(oss):
    por_op = defaultdict(list)
    for o in oss:
        if o["cls"] == "ok":
            por_op[o["op"]].append(o)
    jan = RAJADA_JANELA_MIN * 60
    for lst in por_op.values():
        lst.sort(key=lambda o: o["cri"])
        for o in lst:
            viz = {_episodio(x) for x in lst if abs((x["cri"] - o["cri"]).total_seconds()) <= jan}
            o["rajada"] = len(viz) >= RAJADA_MIN_OCORRENCIAS
    for o in oss:
        o.setdefault("rajada", False)


_CLS = {"ok": 0, "evento_depois": 1, "evento_eh_criacao": 2}


def payload(linhas, varrido_em=None):
    """Pacote compacto da tela: listas de nomes + uma linha por OS com índices nelas.
    Linha: [folio, i_operador, i_tipo, i_usina, evento (epoch s), tempo (min), cls (0 ok / 1 evento
    depois / 2 evento = criação), lote_n, lote_1o, i_cliente, hora do evento, hora da criação, rajada]
    — todas as horas em Brasília."""
    r = montar(linhas)
    oss = r["oss"]
    ops = sorted({o["nome"] for o in oss})
    usinas = sorted({o["usina"] for o in oss})
    clientes = sorted({o["cliente"] for o in oss})
    i_op = {n: i for i, n in enumerate(ops)}
    i_us = {n: i for i, n in enumerate(usinas)}
    i_cli = {n: i for i, n in enumerate(clientes)}
    return {
        "varrido_em": varrido_em, "total_tarefas": r["total_tarefas"],
        "canceladas": r["canceladas"], "teste": r["teste"],
        "ops": ops, "tipos": list(ORDEM_TIPOS), "usinas": usinas, "clientes": clientes,
        "os": [[o["folio"], i_op[o["nome"]], ORDEM_TIPOS.index(o["tipo"]), i_us[o["usina"]],
                int(o["ev"].timestamp()), round(o["mtta"], 2), _CLS[o["cls"]],
                o["lote_n"], int(o["lote_1o"]), i_cli[o["cliente"]], o["h_ev"], o["h_cri"], int(o["rajada"])]
               for o in oss],
    }


def _chave_tarefa(w):
    return w.get("id_work_orders_tasks") or (w.get("wo_folio"), w.get("id_task"), w.get("code"))


def fundir(guardadas, novas, desde):
    """Base acumulada + varredura recente. `novas` cobre tudo criado desde `desde` (ISO); da base
    antiga fica só o que é mais velho que isso. Assim OS cancelada ou apagada na janela recente
    reflete na hora; a mais velha é revista pela varredura cheia diária."""
    corte = dt(desde)
    base = {}
    for w in guardadas:
        c = dt(w.get("creation_date"))
        if c is not None and c < corte:
            base[_chave_tarefa(w)] = w
    for w in novas:
        base[_chave_tarefa(w)] = w
    return list(base.values())
