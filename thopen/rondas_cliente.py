# -*- coding: utf-8 -*-
"""Rondas do mês para o cliente (Dashboard Thopen, rodada 3 — Levi, 09/10/2026: "um ícone de imagem ... carregando a
imagem das rondas em uma estrutura parecida com" o detalhe de ronda do painel do App).

O QUE VAI AO CLIENTE (Levi, 09/10: "Checklist + fotos, sem nome"): os itens do checklist com a resposta, os níveis de
sujidade e vegetação com a frase da régua, os ACHADOS estruturados do App (praga, dejeto, sombreamento, módulo
trincado), as fotos, o número da OS e o horário. NUNCA: o técnico; a observação escrita — o `pendencias_e_achados`
mistura os achados com texto livre ("Sujeira nos módulos, falta de água para banheiro, falta de um cadeado", Caicó
02/10); as PENDÊNCIAS (marcas internas: "ronda longa pendente"); a qualidade da ronda (nota interna do App, que também
vai na capa da foto); o GPS. Foto que não casa com item do checklist sai como "Foto da ronda": a descrição dela pode ser
texto do técnico ("Zona valetas critica"). O 5080 é público, sem senha. Nada aqui faz rede.

A FONTE (Levi, 09/10: "as rondas já foram atualizadas até hoje porém no server não está atualizando, tem que ser
dinâmico"): o livro do App `rondas_app_campo · OS de ronda`, que o servidor do App regrava de hora em hora (aos :50) e
que desde a v249 (09/10) traz o checklist da ronda. Ele substituiu o `campo_nexus · rondas` (coletor do Nexus, parado
em 02/10) e a carga única das rondas sem OS (06/10): tem as 125 sem OS e 580 das 584 rondas do `campo_nexus` (as OS "a
mais" de lá eram a mesma ronda em 2–3 OS). O livro não tem `usina_id`: ele sai do de-para do cadastro do Nexus pelo
código do ativo (BD_Performance/Tickets) ou, sem ele, pelo nome da usina no Fracttal ("Thopen - Guaratingueta 5 - SP").
Também não tem os ACHADOS (praga, dejeto, sombreamento, trincado): eles vêm das fotos, que o App descreve como
"Pragas — pontual".
"""
import datetime as dt
import re

import operacao_mes as om

# chave do App → (seção da janela, nome na tela). Pragas, dejeto e sombreamento aparecem sempre ("Nenhum" quando o App
# não achou); trincado só quando achou — como no detalhe de ronda do painel do App
ACHADOS = (("praga", "pragas", "Pragas"), ("dejeto", "pragas", "Dejeto de pássaro nos módulos"),
           ("sombreamento", "pragas", "Sombreamento por vegetação"), ("trincado", "ocorrencias", "Módulo trincado"))
_ACHADOS_RE = re.compile(r"ACHADOS\s*\W+\s*([^|]+)")
_NIVEL = (("sujidade dos modulos", "sujidade"), ("altura da vegetacao", "vegetacao"))
VALOR_MAX = 40                    # o valor de um achado é curto ("Pontual", "1 ponto", "Até 5"); mais que isso é texto
_COLCHETE = re.compile(r"^(.*?)\s*\[([^\]]*)\]\s*$")    # "2 [Poeira / areia]": o nível e o tipo de sujidade
# o livro do App: coluna → o que é. O resto (Técnico, Técnico (HMAC), Nota da ronda, Falhas, Situação, Região, Tipo,
# IDs) nunca passa da leitura
APP = {"os": "OS", "usina": "Usina", "ativo": "Ativo da usina no Fracttal", "inicio": "Início", "fim": "Fim",
       "sujidade": "Sujidade dos módulos (1 a 5)", "vegetacao": "Altura da vegetação (1 a 5)",
       "checklist": "Checklist da ronda"}
CAMPOS_APP = tuple(APP.values())
# de-para do cadastro do Nexus que liga o livro do App ao usina_id: o código do ativo e o nome no Fracttal
SISTEMAS_CODIGO = ("BD_Performance · Base UFV", "Tickets · Base de dados - Usinas")
SISTEMA_NOME = "Fracttal · Classificação 1"


def campos(respostas, pendencias, usina):
    """Da linha do `campo_nexus · rondas`, só o que pode ir ao cliente — roda na LEITURA (fonte_operacao), antes da
    memória e do disco: o texto livre nunca fica guardado."""
    itens = []
    for parte in str(respostas or "").split(";"):
        item, sep, resp = parte.rpartition(":")
        if sep and item.strip() and resp.strip():
            m = _COLCHETE.match(resp.strip())
            # "Sujidade dos módulos: 2 [Poeira / areia]" → o nível e, à parte, o tipo (opção do App, não texto livre)
            itens.append([item.strip(), m.group(1).strip(), m.group(2).strip()] if m and m.group(2).strip()
                         else [item.strip(), (m.group(1) if m else resp).strip()])
    achados = {}
    m = _ACHADOS_RE.search(str(pendencias or ""))
    for parte in (m.group(1).split(";") if m else []):
        k, sep, v = parte.partition(":")
        k, v = om.chave(k), v.strip()
        if sep and v and len(v) <= VALOR_MAX and k in {a for a, _s, _n in ACHADOS}:
            achados[k] = v
    partes = [p.strip() for p in str(usina or "").split(" - ")]
    # "Thopen - Guaratingueta 5 - SP" → "Guaratingueta 5"; "Thopen - Itajá 1 e 2 - RN" → "Itajá 1 e 2"
    unidade = " - ".join(partes[1:-1]) if len(partes) >= 3 else partes[-1]
    return {"itens": itens, "achados": achados, "unidade": unidade}


def mapa_usinas(de_para):
    """{("codigo"|"nome", chave): {usina_id}} das linhas do de-para do Nexus que ligam o livro do App ao usina_id."""
    mapa = {}
    for x in de_para or []:
        tipo = "codigo" if x.get("sistema") in SISTEMAS_CODIGO else "nome" if x.get("sistema") == SISTEMA_NOME else None
        u = om._int(x.get("usina_id"))
        if tipo and u is not None and str(x.get("chave_externa") or "").strip():
            mapa.setdefault((tipo, om.chave(x["chave_externa"])), set()).add(u)
    return mapa


def _iso_utc(v):
    try:
        return dt.datetime.strptime(str(v or "").replace(" ", "T")[:16], "%Y-%m-%dT%H:%M")
    except ValueError:
        return None


def da_app(linha, mapa):
    """Uma linha do livro do App → as linhas internas (uma por usina_id; a forma do `campo_nexus` de antes: dia e hora
    em UTC, convertidos para Brasília só na conta). Usina sem ligação no de-para ou sem hora de início = nada (nunca
    chutar a usina nem o dia). OS não criada fica (os=None): vale para a zeladoria, não para a janela."""
    g = {k: linha.get(c) for k, c in APP.items()}
    ids = (mapa.get(("codigo", om.chave(g["ativo"]))) if g["ativo"] else None) or \
        mapa.get(("nome", om.chave(g["usina"]))) or set()
    ini, fim = _iso_utc(g["inicio"]), _iso_utc(g["fim"])
    if not ids or ini is None:
        return []
    c = campos(g["checklist"], "", g["usina"])
    os_ = om._int(g["os"])
    base = {"os": str(os_) if os_ is not None else None, "dia": ini.strftime("%Y-%m-%d"),
            "hora_inicio": ini.strftime("%H:%M"), "hora_fim": fim.strftime("%H:%M") if fim else "",
            "sujidade": om.nivel(g["sujidade"]), "vegetacao": om.nivel(g["vegetacao"]), **c}
    return [dict(base, usina_id=u) for u in sorted(ids)]


def _quando(r, campo="hora_inicio"):
    """A hora do livro é UTC (conferido em 08/10: +180 min contra o App em 594 de 594 rondas) → Brasília."""
    try:
        utc = dt.datetime.strptime("%s %s" % (str(r.get("dia") or "")[:10], str(r.get(campo) or "")[:5]),
                                   "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return om._brt(utc)


def cabecalho(r):
    q, f = _quando(r), _quando(r, "hora_fim")
    return {"os": str(om._int(r.get("os"))), "dia": q.strftime("%Y-%m-%d"), "inicio": q.strftime("%H:%M"),
            "fim": f.strftime("%H:%M") if f else "", "unidade": r.get("unidade") or ""}


def do_mes(dados, nome, ano, mes):
    """As rondas com OS da usina do 5080 no mês (o dia em Brasília), da mais recente para a mais antiga. A mesma ronda
    vem em 2–3 OS (188 de 598 rondas em 09/10, cada OS com as suas fotos): fica a de mais fotos, e no empate a de menor
    número."""
    ids = om.ids_da_usina((dados or {}).get("de_para"), nome)
    grupos = {}
    for r in (dados or {}).get("rondas_com_os") or []:
        uid, q = om._int(r.get("usina_id")), _quando(r)
        if uid not in ids or q is None or (q.year, q.month) != (ano, mes) or om._int(r.get("os")) is None:
            continue
        grupos.setdefault((uid, str(r.get("dia"))[:10], str(r.get("hora_inicio"))[:5], str(r.get("hora_fim"))[:5]),
                          []).append(r)
    out = [cabecalho(min(rs, key=lambda x: (-(om._int(x.get("n_fotos")) or 0), om._int(x.get("os")))))
           for rs in grupos.values()]
    return sorted(out, key=lambda x: (x["dia"], x["inicio"]), reverse=True)


def da_os(dados, os_):
    """A linha da OS de ronda — só se for de usina ligada no de-para do 5080 e de 10/2026 em diante. É a trava das rotas
    de foto e de dúvida: o 5080 é público, e sem ela qualquer número de OS do Fracttal (de qualquer cliente) viraria
    foto na tela."""
    alvo = om._int(os_)
    if alvo is None or not dados:
        return None
    ids = {om._int(x.get("usina_id")) for x in dados.get("de_para") or []}
    for r in dados.get("rondas_com_os") or []:
        if om._int(r.get("os")) == alvo and om._int(r.get("usina_id")) in ids:
            q = _quando(r)
            if q is not None and (q.year, q.month) >= om.DESDE:
                return r
    return None


def _foto(i, desc):
    d = str(desc or "").strip()
    if om.chave(d).startswith("ronda "):
        return {"i": i, "item": "Capa da ronda", "resposta": "", "chave": None}
    item, sep, resp = d.partition(" — ")
    return {"i": i, "item": item.strip(), "resposta": resp.strip() if sep else "", "chave": om.chave(item)}


def detalhe(r, descricoes):
    """A ronda montada para a janela: `descricoes` são as descrições dos anexos de imagem da OS, na ordem do Fracttal (o
    índice é o da rota de foto). Cada foto vai para o item do checklist ou o achado que ela mostra; a que sobra vai para
    "outras", com nome genérico."""
    fotos = [_foto(i, d) for i, d in enumerate(descricoes or [])]
    livres = {}
    for f in fotos:
        if f["chave"]:
            livres.setdefault(f["chave"], []).append(f["i"])

    def pega(*rotulos):
        for rot in rotulos:
            achou = livres.pop(om.chave(rot), None)
            if achou:
                return achou
        return []

    itens = []
    for item, resp, *obs in r.get("itens") or []:
        k = next((k for p, k in _NIVEL if om.chave(item).startswith(p)), None)
        n = om.nivel(resp) if k else None
        itens.append({"item": item, "resposta": resp, "nivel": n, "frase": om.REGUA[k][n] if n else None,
                      "obs": obs[0] if obs else None, "fotos": pega(item)})
    ach, secoes = r.get("achados") or {}, {"pragas": [], "ocorrencias": []}
    for k, sec, rot in ACHADOS:
        fs = pega(rot, rot.split()[0])
        # o livro do App não traz os achados: a foto traz ("Pragas — pontual"); o valor é a opção marcada no App
        v = ach.get(k) or next((fotos[i]["resposta"] for i in fs if fotos[i]["resposta"]), None)
        v = v[:1].upper() + v[1:] if v else v
        if sec == "pragas" or v or fs:
            secoes[sec].append({"item": rot, "resposta": v or ("Registrado" if fs else "Nenhum"), "nivel": None,
                                "frase": None, "obs": None, "fotos": fs})
    outras = sorted(i for v in livres.values() for i in v) + [f["i"] for f in fotos if f["chave"] is None]
    for i in outras:
        if fotos[i]["chave"] is not None:
            fotos[i].update(item="Foto da ronda", resposta="")
    out = cabecalho(r)
    out.update(itens=itens, pragas=secoes["pragas"], ocorrencias=secoes["ocorrencias"], outras=sorted(outras),
               fotos=[{"i": f["i"], "item": f["item"], "resposta": f["resposta"]} for f in fotos])
    return out
