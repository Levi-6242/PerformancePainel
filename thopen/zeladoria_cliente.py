# -*- coding: utf-8 -*-
"""A aba Zeladoria do dashboard do cliente (Levi, 26/10/2026: a mesma tela do Nexus > Campo · App > Zeladoria, "agora
faz a mesma tela no dashboard do cliente"). Puro: sem rede e sem Flask.

De onde vem: o NEXUS publica a visão pronta no banco (decisão do Levi, 26/10/2026: a conta fica num lugar só e os
números batem com a tela do Nexus), o livro `nexus_zeladoria` (commit d6f37d7 do Nexus, 27/10/2026): uma linha por usina
× semana COM leitura (segunda a domingo), 12 semanas até a corrente, com os níveis da última leitura da semana, a
recomendação e a situação da limpeza e da supressão sobre a leitura daquela semana. O estado atual de uma usina é a linha
da semana mais recente dela. Aqui só se escolhe a semana, filtra pelas carteiras da conta e monta a tela. As regras (acima
de 3 pede ação, a última leitura da semana, nível 5 imediato e 4 em até 7 dias) são as do Nexus (nexus/campo/zeladoria.py)
e não se refazem aqui.

O que o cliente não vê: nome de técnico, texto livre da OS e "sem OS no Fracttal"; a situação vem com palavras dele
("a programar", "programada para 28/10", "feita em 23/10"). "Aprovar recomendação" e "Solicitar orçamento" ficam fora
(Levi, 26/10/2026)."""
import datetime as dt
from collections import defaultdict

# O livro do Nexus (nomes finais de 27/10/2026, nexus/dados/CLAUDE.md: datas em data_id AAAAMMDD)
WORKBOOK = "nexus_zeladoria"
ABA = "zeladoria_semana"
ABA_ATUALIZACAO = "atualizacao"
CAMPOS = ("semana", "data_id_semana", "usina_id", "vegetacao_nivel", "sujidade_nivel", "vala", "data_id_leitura", "os",
          "leituras_qtd", "recomendacao", "data_id_prazo_vegetacao", "data_id_prazo_sujidade", "situacao_vegetacao",
          "situacao_sujidade", "data_id_situacao_vegetacao", "data_id_situacao_sujidade", "os_zeladoria_vegetacao",
          "os_zeladoria_sujidade", "data_id_ultima_supressao", "data_id_ultima_limpeza")
CAMPOS_ATUALIZACAO = ("atualizado_em", "semana_corrente", "linhas_qtd", "semanas_qtd", "usinas_qtd", "checklist_ate")
SEMANAS_EVOLUCAO = 8              # as 8 semanas até a escolhida, como o modelo e o Nexus
SEMANAS_NO_FILTRO = 5             # a corrente e as 4 anteriores, como o Nexus
ACIMA = 3                         # acima de 3 pede ação (níveis 4 e 5), a régua do App
SITUACOES = ("a programar", "programada", "feita", "sem dado")


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def data_iso(v):
    """data_id (20261021, ou "20261021") ou ISO → "2026-10-21"; o resto → None."""
    s = str(v or "").strip()
    if s.endswith(".0"):
        s = s[:-2]
    if len(s) == 8 and s.isdigit():
        return "%s-%s-%s" % (s[:4], s[4:6], s[6:])
    return s[:10] if len(s) >= 10 and s[4] == "-" and s[7] == "-" else None


def segunda(semana):
    """"2026-W43" → a segunda-feira (ISO)."""
    try:
        a, w = str(semana).split("-W")
        return dt.date.fromisocalendar(int(a), int(w), 1).isoformat()
    except (ValueError, TypeError):
        return None


def semana_de(d):
    """date → "2026-W43" (ISO, segunda a domingo; a do PCM)."""
    a, w, _ = d.isocalendar()
    return "%d-W%02d" % (a, w)


def ultima_atualizacao(dados):
    atu = dados.get("atualizacao") or []
    return sorted(atu, key=lambda a: str(a.get("atualizado_em") or ""))[-1] if atu else None


def conferir(dados):
    """A leitura bate com a contagem da aba de atualização (linhas_qtd)? Leitura no meio da troca não vai para a tela."""
    a = ultima_atualizacao(dados)
    esperado = _int(a.get("linhas_qtd")) if a else None
    return esperado is not None and esperado == len(dados.get("linhas") or [])


def nomes_por_id(de_para):
    """{usina_id: nome da usina no 5080} pelo de-para do sistema do 5080 (o mesmo que o fonte_operacao já lê)."""
    out = {}
    for r in de_para or []:
        uid, nome = _int(r.get("usina_id")), str(r.get("chave_externa") or "").strip()
        if uid is not None and nome:
            out.setdefault(uid, nome)
    return out


def _nivel(v):
    n = _int(v)
    return n if n is not None and 1 <= n <= 5 else None


def _situacao(codigo, data):
    t = str(codigo or "").strip().lower().replace("_", " ")
    if t not in SITUACOES:
        t = "sem dado"
    d = data_iso(data)
    rot = {"a programar": "a programar", "sem dado": "sem dado",
           "programada": "programada" + (" para %s/%s" % (d[8:10], d[5:7]) if d else ""),
           "feita": "feita" + (" em %s/%s" % (d[8:10], d[5:7]) if d else "")}[t]
    return {"situacao": t, "texto": rot}


def _semanas_ate(corrente, n):
    seg = segunda(corrente)
    if not seg:
        return []
    d = dt.date.fromisoformat(seg)
    return [semana_de(d - dt.timedelta(weeks=k)) for k in range(n - 1, -1, -1)]


def montar(linhas, nomes, usinas, semana=None, semana_corrente=None):
    """A tela da semana escolhida para as usinas da conta (`usinas`: os nomes do 5080 que ela vê, na carteira escolhida).

    linhas: as do livro do Nexus (CAMPOS); nomes: {usina_id: nome no 5080}; semana_corrente: a da aba de atualização (a
    semana em andamento pode ainda não ter linha). Usina do Nexus sem nome no 5080, ou fora de `usinas`, fica fora."""
    alvo = set(usinas)
    por_usina = defaultdict(dict)
    vistas = set()
    for r in linhas or []:
        nome = nomes.get(_int(r.get("usina_id")))
        sem = str(r.get("semana") or "").strip()
        if not sem:
            continue
        vistas.add(sem)
        if nome and nome in alvo:
            por_usina[nome][sem] = r
    corrente = semana_corrente or (max(vistas) if vistas else None)
    if not corrente:
        return {"semana": None, "semanas": [], "evolucao": {"semanas": [], "usinas": [], "grupo": {}}, "tabela": [],
                "recomendacoes": [], "kpis": None, "usinas_sem_leitura": sorted(alvo)}
    filtro = _semanas_ate(corrente, SEMANAS_NO_FILTRO)
    escolhida = semana if semana in filtro else corrente
    janela = _semanas_ate(escolhida, SEMANAS_EVOLUCAO)

    def nivel_da(nome, sem, campo):
        r = por_usina[nome].get(sem)
        return _nivel(r.get(campo)) if r else None

    evolucao = {"semanas": [{"semana": s, "ini": segunda(s), "em_andamento": s == corrente} for s in janela],
                "usinas": [], "grupo": {"vegetacao": [], "sujidade": []}}
    tabela, recs = [], []
    for nome in sorted(por_usina):
        evolucao["usinas"].append({"usina": nome,
                                   "vegetacao": [nivel_da(nome, s, "vegetacao_nivel") for s in janela],
                                   "sujidade": [nivel_da(nome, s, "sujidade_nivel") for s in janela]})
        com_leitura = [s for s in sorted(por_usina[nome]) if s <= escolhida and data_iso(por_usina[nome][s].get("data_id_leitura"))]
        if not com_leitura:
            continue
        r = por_usina[nome][com_leitura[-1]]
        ant = por_usina[nome][com_leitura[-2]] if len(com_leitura) > 1 else None
        veg, suj = _nivel(r.get("vegetacao_nivel")), _nivel(r.get("sujidade_nivel"))
        linha = {"usina": nome, "semana": com_leitura[-1], "data_leitura": data_iso(r.get("data_id_leitura")),
                 "vegetacao": veg, "sujidade": suj,
                 "vegetacao_antes": _nivel(ant.get("vegetacao_nivel")) if ant else None,
                 "sujidade_antes": _nivel(ant.get("sujidade_nivel")) if ant else None,
                 "vala": str(r.get("vala") or "").strip() or None, "os_ronda": _int(r.get("os")),
                 "leituras": _int(r.get("leituras_qtd")),
                 "ultima_supressao": data_iso(r.get("data_id_ultima_supressao")),
                 "ultima_limpeza": data_iso(r.get("data_id_ultima_limpeza")), "recomendacoes": []}
        for campo, nivel, tipo in (("vegetacao", veg, "Supressão vegetal"), ("sujidade", suj, "Limpeza de módulos")):
            if nivel is not None and nivel > ACIMA:
                rec = dict(_situacao(r.get("situacao_" + campo), r.get("data_id_situacao_" + campo)), tipo=tipo,
                           campo=campo, nivel=nivel, usina=nome, data_leitura=linha["data_leitura"],
                           prazo=data_iso(r.get("data_id_prazo_" + campo)))
                linha["recomendacoes"].append(rec)
                recs.append(rec)
        tabela.append(linha)
    for campo in ("vegetacao", "sujidade"):
        for i in range(len(janela)):
            vals = [u[campo][i] for u in evolucao["usinas"] if u[campo][i] is not None]
            evolucao["grupo"][campo].append({"acima": sum(1 for v in vals if v > ACIMA), "com_leitura": len(vals)})
    # a mais grave primeiro: o nível, depois quem ainda não tem nada programado, depois a leitura mais antiga
    ordem_sit = {"a programar": 0, "sem dado": 1, "programada": 2, "feita": 3}
    recs.sort(key=lambda x: (-x["nivel"], ordem_sit[x["situacao"]], x["data_leitura"] or "", x["usina"]))
    # a tabela: a usina mais crítica primeiro (o maior nível dos dois campos), depois o nome
    tabela.sort(key=lambda x: (-max(x["vegetacao"] or 0, x["sujidade"] or 0), x["usina"]))

    def media(campo):
        v = [t[campo] for t in tabela if t[campo] is not None]
        return round(sum(v) / len(v), 1) if v else None

    na_semana = sum(1 for n in por_usina if escolhida in por_usina[n]
                    and data_iso(por_usina[n][escolhida].get("data_id_leitura")))
    kpis = {"com_leitura": na_semana, "usinas": len(alvo),
            "vegetacao_acima": sum(1 for t in tabela if (t["vegetacao"] or 0) > ACIMA),
            "vegetacao_5": sum(1 for t in tabela if t["vegetacao"] == 5), "vegetacao_media": media("vegetacao"),
            "sujidade_acima": sum(1 for t in tabela if (t["sujidade"] or 0) > ACIMA),
            "sujidade_5": sum(1 for t in tabela if t["sujidade"] == 5), "sujidade_media": media("sujidade"),
            "a_programar": sum(1 for r in recs if r["situacao"] == "a programar"), "recomendacoes": len(recs),
            "programadas": sum(1 for r in recs if r["situacao"] == "programada"),
            "feitas": sum(1 for r in recs if r["situacao"] == "feita"), "com_leitura_total": len(tabela)}
    return {"semana": escolhida, "semanas": [{"semana": s, "ini": segunda(s), "em_andamento": s == corrente}
                                             for s in filtro][::-1],
            "evolucao": evolucao, "tabela": tabela, "recomendacoes": [r for r in recs if r["situacao"] != "feita"],
            "kpis": kpis, "usinas_sem_leitura": sorted(alvo - {t["usina"] for t in tabela})}
