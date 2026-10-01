# -*- coding: utf-8 -*-
"""Relatório Semanal de Performance — Thopen (29/09/2026): as contas.

Pedido da Ana Patrícia e do Levi na reunião de 28/09 (mockup R00): o relatório da carteira Thopen para o CLIENTE, toda
segunda até as 12h, do período que o analista escolher. Aqui só mora conta que não depende de rede nem de arquivo: o
app lê o BD_Thopen, o índice de disponibilidade e as OS do Fracttal que o worker já deixou em disco, e este módulo
devolve os blocos. É o que os testes travam (tests/test_relatorio_semanal.py).

Desenho: docs/superpowers/specs/2026-09-29-relatorio-semanal-thopen-design.md.
"""
import calendar
from datetime import date, datetime, time, timedelta

# A régua do Histórico PR (api_g_diario): o dia com IPOA <= 0,3 kWh/m² não tem PR — sem irradiação medida, a conta
# daria qualquer coisa. O semanal de uma usina tem de bater com o Histórico no mesmo período.
IPOA_MIN = 0.3
# "Tolerância: PR ≥ 97% da meta" (mockup R00): abaixo disso a usina está fora da meta e entra no bloco 05.
TOL_META = 0.97
# PR de um dia acima de 130% = IPOA subestimada (o alerta do Criador de Relatório de hoje).
PR_TETO_DIA = 1.30
# Janela solar do índice de disponibilidade (módulo disponibilidade): 06–18h, 12 h por dia.
JANELA = (6, 18)
JANELA_H = 12.0
# Assunção dos ativos pela Grid (bloco 02). Levi, 30/09/2026: "começa por 01/01/2026 e aí tem usinas que entraram depois
# disso, elas vão entrando no cálculo" — a usina entra no mês em que passa a ter dia válido no BD_Thopen.
ASSUNCAO = date(2026, 1, 1)


def dias(ini, fim):
    """Os dias de [ini, fim], inclusivos."""
    return [ini + timedelta(days=i) for i in range((fim - ini).days + 1)]


def _frac(pr):
    """Meta de PR como fração: a planilha às vezes traz em porcentagem (78,4 em vez de 0,784)."""
    if pr is None:
        return None
    return pr / 100.0 if pr > 2 else pr


def _vazio():
    return {"ger_kwh": 0.0, "den_mwh": 0.0, "num_meta": 0.0, "den_meta": 0.0, "ger_total_kwh": 0.0,
            "meta_kwh": 0.0, "ipoa_pot": 0.0, "ipoa_meta_pot": 0.0, "pot_mwp": 0.0, "dias_validos": 0,
            "dias_sem_ipoa": 0, "dias_pr_alto": 0, "dias": 0}


def _fecha(r):
    """As razões a partir das somas: PR, meta de PR, IPOA real e meta (ponderadas pela potência)."""
    r["pr"] = (r["ger_kwh"] / 1000.0 / r["den_mwh"]) if r["den_mwh"] else None
    r["pr_meta"] = (r["num_meta"] / r["den_meta"]) if r["den_meta"] else None
    pot = r["pot_mwp"] or None
    r["ipoa"] = (r["ipoa_pot"] / pot) if pot else None
    r["ipoa_meta"] = (r["ipoa_meta_pot"] / pot) if pot else None
    return r


def pr_unidade(diario, pot_mwp, metas, ini, fim):
    """PR, meta e produção de uma usina (uma aba do BD_Thopen) no período.

    diario = [{data: date, ger: kWh, ipoa: kWh/m²}] (dashboard_thopen._daily_records); pot_mwp = potência da usina;
    metas = {mês: {meta: kWh, metairr: kWh/m², pr: fração}} (dashboard_thopen._meta2026, a lista do cliente).

    - PR = Σ geração ÷ Σ (IPOA × potência), só nos dias com geração e IPOA > IPOA_MIN;
    - meta de PR = a meta do mês ponderada pelo denominador do dia — a semana de 28/09 a 04/10 pesa setembro e outubro
      pelo sol que cada dia teve, não pela contagem de dias;
    - meta de geração = a mensal ÷ dias do mês, nos dias com geração registrada; a de irradiação, nos dias com IPOA
      medida (o dia sem leitura não pode derrubar o "IPOA real × meta").
    """
    r = _vazio()
    ok = set(dias(ini, fim))
    por_dia = {x["data"]: x for x in diario or [] if x.get("data") in ok}
    for d in sorted(ok):
        r["dias"] += 1
        x = por_dia.get(d)
        if not x:
            continue
        mt = metas.get(d.month) or {}
        nd = calendar.monthrange(d.year, d.month)[1]
        g, i = x.get("ger"), x.get("ipoa")
        if g is not None and g > 0:
            r["ger_total_kwh"] += g
            if mt.get("meta"):
                r["meta_kwh"] += mt["meta"] / nd
        valido = g is not None and g > 0 and i is not None and i > IPOA_MIN and pot_mwp
        if not valido:
            if g is not None and g > 0:
                r["dias_sem_ipoa"] += 1
            continue
        den = i * pot_mwp                                    # MWh por unidade de PR
        r["ger_kwh"] += g
        r["den_mwh"] += den
        r["dias_validos"] += 1
        r["ipoa_pot"] += i * pot_mwp
        if mt.get("metairr"):
            r["ipoa_meta_pot"] += mt["metairr"] / nd * pot_mwp
        prm = _frac(mt.get("pr"))
        if prm is not None:
            r["num_meta"] += prm * den
            r["den_meta"] += den
        if g / 1000.0 / den > PR_TETO_DIA:
            r["dias_pr_alto"] += 1
    r["pot_mwp"] = pot_mwp or 0.0
    return _fecha(r)


_SOMAVEIS = ("ger_kwh", "den_mwh", "num_meta", "den_meta", "ger_total_kwh", "meta_kwh", "ipoa_pot", "ipoa_meta_pot",
             "pot_mwp", "dias_validos", "dias_sem_ipoa", "dias_pr_alto")


def soma(partes):
    """Várias usinas (as abas de uma unidade, ou o portfólio) numa só: soma numeradores e denominadores. A média dos
    PRs daria o mesmo peso a uma usina de 1 MWp e a uma de 20."""
    r = _vazio()
    for p in partes:
        for k in _SOMAVEIS:
            r[k] += p.get(k) or 0
        r["dias"] = max(r["dias"], p.get("dias") or 0)
    return _fecha(r)


def fora_da_meta(r):
    """PR abaixo de 97% da meta. Sem PR ou sem meta não se afirma."""
    return bool(r.get("pr") is not None and r.get("pr_meta") and r["pr"] < TOL_META * r["pr_meta"])


def perda_estimada_mwh(r):
    """O que a usina teria gerado a mais na meta de PR, com o sol que veio: (meta − PR) × Σ (IPOA × potência)."""
    if r.get("pr") is None or not r.get("pr_meta"):
        return 0.0
    return max(0.0, (r["pr_meta"] - r["pr"]) * (r.get("den_mwh") or 0.0))


def meses_desde(inicio, fim):
    """[(ano, mês)] do mês de `inicio` ao de `fim`, inclusive — atravessa a virada do ano."""
    out, a, m = [], inicio.year, inicio.month
    while (a, m) <= (fim.year, fim.month):
        out.append((a, m))
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    return out


def pr_mensal(unidades, meses):
    """PR e meta do portfólio mês a mês (bloco 02). unidades = [(diario, pot_mwp, metas)]; meses = [(ano, mês)]. A usina
    que ainda não existia no mês não tem dia válido nele e não pesa — entra quando o BD_Thopen passa a ter dia dela."""
    out = []
    for ano, m in meses:
        ini = date(ano, m, 1)
        fim = date(ano, m, calendar.monthrange(ano, m)[1])
        partes = [pr_unidade(d, p, mt, ini, fim) for d, p, mt in unidades]
        t = soma(partes)
        out.append({"ano": ano, "mes": m, "pr": t["pr"], "pr_meta": t["pr_meta"], "dias_validos": t["dias_validos"],
                    "usinas": sum(1 for x in partes if x["dias_validos"])})
    return out


# ── bloco 04: disponibilidade e desligamentos ─────────────────────────────────────────────────────────────────
def disponibilidade(diario_disp, ini, fim):
    """Disponibilidade da usina no período a partir do diário do índice (`diario[usina]`: {"AAAA-MM-DD": {h_eq, h_q,
    h_e}}). h_eq = horas equivalentes de usina inteira parada na janela solar; dia fora do diário = 100%."""
    ds = dias(ini, fim)
    h_eq = h_q = h_e = 0.0
    for d in ds:
        x = (diario_disp or {}).get(d.isoformat()) or {}
        h_eq += x.get("h_eq") or 0.0
        h_q += x.get("h_q") or 0.0
        h_e += x.get("h_e") or 0.0
    tot = JANELA_H * len(ds)
    return {"disp": (100.0 * (1 - h_eq / tot)) if tot else None, "h_eq": h_eq, "h_q": h_q, "h_e": h_e,
            "dias": len(ds)}


def disponibilidade_portfolio(itens):
    """[(disponibilidade(), kWp)] → a do portfólio, ponderada pela potência, e a indisponibilidade decomposta em
    externa (queda de rede, h_q) e atribuível à Grid (equipamento, h_e). As duas famílias podem se sobrepor no mesmo
    horário e não somam exatamente o total (a regra do módulo disponibilidade)."""
    num = den = q = e = 0.0
    for r, kwp in itens:
        if r.get("disp") is None or not kwp:
            continue
        tot = JANELA_H * r["dias"]
        num += r["disp"] * kwp
        den += kwp
        q += r["h_q"] / tot * kwp
        e += r["h_e"] / tot * kwp
    if not den:
        return {"disp": None, "indisp_ext": None, "indisp_grid": None}
    return {"disp": num / den, "indisp_ext": 100.0 * q / den, "indisp_grid": 100.0 * e / den}


def _dt(s):
    try:
        return datetime.fromisoformat(str(s)[:19]) if s else None
    except ValueError:
        return None


def _horas_janela(a, b):
    """Horas de [a, b) dentro da janela solar de cada dia."""
    h, d = 0.0, a.date()
    while datetime.combine(d, time(0)) < b:
        j0, j1 = datetime.combine(d, time(JANELA[0])), datetime.combine(d, time(JANELA[1]))
        x, y = max(a, j0), min(b, j1)
        if y > x:
            h += (y - x).total_seconds() / 3600.0
        d += timedelta(days=1)
    return h


def desligamentos(oss, ini, fim, usinas=None):
    """Quedas de rede e desligamentos por equipamento que cruzam o período (a lista `oss` do índice, datas locais):
    quantidade e horas de sol dentro do período. A duração vai do evento ao fim da tarefa (Levi, 30/09/2026: "vai da
    data do evento até a data do fim da tarefa, esse é o tempo que ficou desligado") — é o `ini`/`fim` que o módulo
    disponibilidade já dá a cada OS. OS aberta sem fim = 0 h (Mandaguaçu e Céu Azul geravam com OS esquecida aberta)."""
    out = {"queda": {"n": 0, "h": 0.0}, "equip": {"n": 0, "h": 0.0}}
    lim_a, lim_b = datetime.combine(ini, time(0)), datetime.combine(fim + timedelta(days=1), time(0))
    for o in oss or []:
        fam = {"queda": "queda", "equipamento": "equip"}.get(o.get("origem"))
        if not fam or (usinas is not None and not (set(o.get("usinas") or []) & set(usinas))):
            continue
        a, b = _dt(o.get("ini")), _dt(o.get("fim"))
        if a is None:
            continue
        fim_ef = b if (b is not None and b >= a) else a
        if fim_ef < lim_a or a >= lim_b:
            continue
        out[fam]["n"] += 1
        out[fam]["h"] += _horas_janela(max(a, lim_a), min(fim_ef, lim_b))
    return out


# ── bloco 03: o que a Grid executou ───────────────────────────────────────────────────────────────────────────
CORRETIVAS = {"Corretiva", "Corretiva Emergencial"}
PREVENTIVAS = {"Preventiva"}
CONCLUIDA = {2, 3}          # id_status_work_order do Fracttal: 2/3 concluída, 4 cancelada, 0/1/5/6 aberta
CANCELADA = {4}


REL_TIPOS = {"religamento", "religamento remoto"}


def _dt_br(iso):
    """Carimbo do Fracttal em Brasília: vem em UTC (+00:00) — 01:00 UTC do dia 28 é 22:00 do dia 27."""
    t = _dt(iso)
    if t is None:
        return None
    return t - timedelta(hours=3) if str(iso)[19:].startswith(("+00", "Z")) else t


def _dia_br(iso):
    t = _dt_br(iso)
    return t.date() if t else None


def com_fim_da_tarefa(linhas):
    """A base de OS guarda o fim de cada tarefa desde 30/09/2026 (mtta.CAMPOS). A de antes não tem a chave, e as linhas
    dela voltam com o fim só quando o worker as varre de novo (10 dias a cada 30 min; a base inteira 1×/dia)."""
    return any("final_date" in x for x in linhas or [])


def os_executadas(linhas, sites, ini, fim):
    """Corretivas e preventivas POR TAREFA (Levi, 30/09/2026: "quero que conte por tarefa"), com evento no período: a
    preventiva de 12 tarefas conta 12. Finalizada = a tarefa tem data de fim; na linha de antes do fim da tarefa (sem a
    chave), a OS concluída. É por LINHA: logo depois do deploy só as tarefas criadas nos últimos 10 dias voltam com o
    fim, e a régua da base inteira deu 0 de 78 preventivas no servidor (30/09, 21:40) — as da semana eram mais antigas.
    Cancelada não conta. Em 21–27/09, na Thopen, por OS davam 41 de 67 corretivas e 1 de 6 preventivas."""
    out = {"corretivas": {"concluidas": 0, "total": 0}, "preventivas": {"realizadas": 0, "planejadas": 0}}
    vistas = set()
    for x in linhas or []:
        if x.get("groups_1_description") not in sites or x.get("id_status_work_order") in CANCELADA:
            continue
        d = _dia_br(x.get("event_date") or x.get("creation_date"))
        if d is None or not (ini <= d <= fim):
            continue
        k = x.get("id_work_orders_tasks") or (x.get("wo_folio"), x.get("id_task"), x.get("tasks_log_task_type_main"))
        if k in vistas:
            continue
        vistas.add(k)
        feita = bool(x.get("final_date")) if "final_date" in x else x.get("id_status_work_order") in CONCLUIDA
        tipo = x.get("tasks_log_task_type_main")
        if tipo in CORRETIVAS:
            out["corretivas"]["total"] += 1
            out["corretivas"]["concluidas"] += feita
        elif tipo in PREVENTIVAS:
            out["preventivas"]["planejadas"] += 1
            out["preventivas"]["realizadas"] += feita
    return out


def _mediana(xs):
    ds = sorted(xs)
    if not ds:
        return None
    return ds[len(ds) // 2] if len(ds) % 2 else (ds[len(ds) // 2 - 1] + ds[len(ds) // 2]) / 2


def religamento(linhas, sites, ini, fim):
    """Tempo de religamento (Levi, 30/09/2026): da CRIAÇÃO da OS ao FIM da tarefa de religamento (Religamento ou
    Religamento Remoto), nas OS em que essa tarefa terminou no período; com mais de uma, vale a última. A OS registrada
    depois do religamento (fim da tarefa antes da criação da OS) não tem esse tempo: fica fora e é contada à parte.
    A mediana é o número do cliente — uma queda longa da concessionária puxa a média para horas."""
    por_os = {}
    for x in linhas or []:
        if x.get("groups_1_description") in sites:
            por_os.setdefault(str(x.get("wo_folio")), []).append(x)
    durs, retro = [], 0
    for ts in por_os.values():
        if any(t.get("id_status_work_order") in CANCELADA for t in ts):
            continue
        fins = [f for f in (_dt_br(t.get("final_date")) for t in ts
                            if str(t.get("tasks_log_task_type_main") or "").strip().lower() in REL_TIPOS) if f]
        crs = [c for c in (_dt_br(t.get("creation_date")) for t in ts) if c]
        if not fins or not crs:
            continue
        fr = max(fins)
        if not (ini <= fr.date() <= fim):
            continue
        m = (fr - min(crs)).total_seconds() / 60.0
        if m < 0:
            retro += 1
            continue
        durs.append(m)
    return {"n": len(durs), "medio_min": (sum(durs) / len(durs)) if durs else None, "mediano_min": _mediana(durs),
            "retroativas": retro}


def rondas(linhas, sites, ini, fim):
    """Rondas do App de Campo no período (workbook `rondas_app_campo`, Levi, 30/09/2026), nos sites da carteira: a
    coluna Usina é o site do Fracttal, o mesmo `groups_1_description` das OS."""
    out = {"total": 0, "curtas": 0, "longas": 0, "usinas": 0}
    us = set()
    for r in linhas or []:
        if r.get("Usina") not in sites:
            continue
        d = _data(r.get("Data"))
        if d is None or not (ini <= d <= fim):
            continue
        tipo = str(r.get("Tipo") or "").strip().lower()
        out["total"] += 1
        out["curtas"] += tipo == "curta"
        out["longas"] += tipo == "longa"
        us.add(r["Usina"])
    out["usinas"] = len(us)
    return out


def _data(s):
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def strings_voltaram(episodios, ini, fim, usinas=None):
    """Strings cujo episódio da aba de falhas terminou no período (voltaram a gerar)."""
    vistos = set()
    for e in episodios or []:
        if usinas is not None and e.get("usina") not in usinas:
            continue
        d = _data(e.get("fim"))
        if d is not None and ini <= d <= fim:
            vistos.add((e.get("usina"), e.get("inversor"), e.get("string")))
    return len(vistos)


# ── aviso: a geração do dia tem de casar com a disponibilidade do dia ─────────────────────────────────────────────
# Levi, 30/09/2026: "tem que casar com a disponibilidade, se a disponibilidade for 0 então a geração também será 0 e assim
# por diante". Disponibilidade do dia = 1 − h_eq/12 do índice (dia fora dele = 100%).
AVISO_DISP_MIN = 0.3         # com pelo menos 30% da usina disponível, geração zero é falta no BD (ou parada sem OS)
AVISO_GER_FOLGA = 0.4        # gerou 40 pontos acima do que a disponibilidade permite: a OS diz parada e a usina gerava
AVISO_DISP_MAX = 0.6         # acima disto o clima já explica a diferença
TIPICO_DIAS = 30             # o típico da usina: P75 dos dias 100% disponíveis nos 30 dias até o fim do período
TIPICO_MIN_DIAS = 5


def _p75(vs):
    vs = sorted(vs)
    return vs[min(int(len(vs) * 0.75), len(vs) - 1)] if len(vs) >= TIPICO_MIN_DIAS else None


def _dias_txt(ds):
    """[date] → "21 a 23/09 e 25/09": sequência de dias vira intervalo."""
    ds, partes, i = sorted(ds), [], 0
    while i < len(ds):
        j = i
        while j + 1 < len(ds) and ds[j + 1] - ds[j] == timedelta(days=1):
            j += 1
        if i == j:
            partes.append(f"{ds[i]:%d/%m}")
        else:
            partes.append(f"{ds[i]:%d} a {ds[j]:%d/%m}" if ds[i].month == ds[j].month else f"{ds[i]:%d/%m} a {ds[j]:%d/%m}")
        i = j + 1
    return partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " e " + partes[-1]


def _faixa(vs):
    a, b = min(vs), max(vs)
    return f"{a:.0%}" if round(a, 2) == round(b, 2) else f"{a:.0%} a {b:.0%}"


def geracao_x_disponibilidade(nome, ger_dia, disp_dia, ini, fim):
    """ger_dia = {date: kWh} (a soma das abas da unidade; dia sem linha fica fora); disp_dia = {date: fração 0–1}.
    → avisos de conferência, um por usina e por tipo: dia sem geração com a usina disponível, e dia gerando com a
    usina indisponível pelas OS. Em 21–27/09 foram 36 dias em 17 usinas — um por dia enchia a caixa."""
    base = [ger_dia[d] for d in dias(fim - timedelta(days=TIPICO_DIAS - 1), fim)
            if (ger_dia.get(d) or 0) > 0 and disp_dia.get(d, 1.0) >= 0.999]
    tipico = _p75(base)
    sem, gerou = [], []
    # antes da 1ª linha no BD a usina ainda não existia (entrou depois): não é dia faltando
    desde = max([ini] + [min(ger_dia)] if ger_dia else [ini])
    for d in dias(desde, fim):
        g, disp = ger_dia.get(d), disp_dia.get(d, 1.0)
        if (g is None or g <= 0 or (tipico and g < 0.05 * tipico)) and disp >= AVISO_DISP_MIN:
            sem.append((d, disp))
        elif tipico and g and disp <= AVISO_DISP_MAX and g / tipico >= disp + AVISO_GER_FOLGA:
            gerou.append((d, disp, g / tipico))
    out = []
    if sem:
        out.append(f"{nome}: sem geração no BD_Thopen em {_dias_txt([d for d, _ in sem])}, com "
                   f"{_faixa([x for _, x in sem])} de disponibilidade pelas OS")
    if gerou:
        out.append(f"{nome}: gerou {_faixa([r for _, _, r in gerou])} do típico em {_dias_txt([d for d, _, _ in gerou])}, "
                   f"com {_faixa([x for _, x, _ in gerou])} de disponibilidade pelas OS")
    return out


# ── bloco 05: ofensores medidos e causa sugerida ────────────────────────────────────────────────────────────────
SEM_OFENSOR = "Sem ofensor medido — verificar sujidade, vegetação ou limitação"


def _n1(x):
    return f"{x:.1f}".replace(".", ",")


def _kwh_no_periodo(e, ini, fim):
    """A perda do episódio que cai no período, pelos dias: um episódio de 14 dias com 7 no período conta metade."""
    d0 = _data(e.get("d0") or e.get("inicio"))
    d1 = _data(e.get("d1") or e.get("fim")) or fim
    if d0 is None or d1 < ini or d0 > fim:
        return 0.0
    tot = e.get("dias") or ((d1 - d0).days + 1)
    dentro = (min(d1, fim) - max(d0, ini)).days + 1
    return (e.get("perda_kwh") or 0.0) * max(0, dentro) / max(1, tot)


def ofensores(desl, trk, strs, pr, kwh_indisp, ini, fim):
    """O pré-diagnóstico da usina fora da meta, com número: [{tipo, texto, kwh}], o de maior energia primeiro. A
    irradiância não confiável vem antes de tudo — com o sensor sem medir, o PR da semana não se sustenta."""
    out = []
    dv, ds = pr.get("dias_validos") or 0, pr.get("dias_sem_ipoa") or 0
    if ds > dv:
        out.append({"tipo": "ipoa", "kwh": None,
                    "texto": f"Irradiância não confiável (sensor): {ds} de {ds + dv} dias sem medição"})
    elif pr.get("dias_pr_alto"):
        k = pr["dias_pr_alto"]
        out.append({"tipo": "ipoa", "kwh": None,
                    "texto": f"Irradiância não confiável (sensor): PR acima de 130% em {k} dia{'s' if k > 1 else ''}"})
    resto = []
    q, e = (desl or {}).get("queda") or {}, (desl or {}).get("equip") or {}
    partes = []
    if q.get("n"):
        partes.append(f"{q['n']} queda{'s' if q['n'] > 1 else ''} de rede ({_n1(q.get('h') or 0)} h)")
    if e.get("n"):
        partes.append(f"{e['n']} desligamento{'s' if e['n'] > 1 else ''} por equipamento ({_n1(e.get('h') or 0)} h)")
    if partes or kwh_indisp:
        resto.append({"tipo": "desligamento", "kwh": kwh_indisp or 0.0,
                      "texto": "Desligamentos: " + " e ".join(partes) if partes else "Indisponibilidade registrada"})
    kt = sum(_kwh_no_periodo(x, ini, fim) for x in trk or [])
    nt = len({x.get("tracker") for x in trk or [] if _kwh_no_periodo(x, ini, fim) > 0 or x.get("perda_kwh") == 0})
    if trk:
        resto.append({"tipo": "tracker", "kwh": kt, "texto": f"Trackers parados ({nt or len(trk)})"})
    ks = sum(_kwh_no_periodo(x, ini, fim) for x in strs or [])
    if strs:
        n = len({(x.get("inversor"), x.get("string")) for x in strs})
        resto.append({"tipo": "string", "kwh": ks, "texto": f"Strings indisponíveis ({n})"})
    resto.sort(key=lambda o: -(o["kwh"] or 0))
    return out + resto


def causa_sugerida(ofs):
    return ofs[0]["texto"] if ofs else SEM_OFENSOR


# ── unidades e montagem ─────────────────────────────────────────────────────────────────────────────────────────
DISP_META = 97.0            # meta de disponibilidade do mockup R00


def unidades(indice, bd_nomes, chave, grupos, alias):
    """As usinas do relatório: as do índice de disponibilidade (cadastro, Full O&M da Thopen) casadas com as abas do
    BD_Thopen, onde moram geração, IPOA e meta. O casamento pelo nome falha de três jeitos, todos reais: grafia
    (Corrego × Córrego — `chave`, a chave solta da plataforma), a usina que o BD junta ou separa diferente do cadastro
    (Nova Londrina 1+2 = uma aba; Ouro Branco = abas I a V — `grupos`, o _GER_GRUPOS) e o alias que não é grafia
    (Vargem Grande IB = Vargem Grande 1 — `alias`). → ([{nome, bd, disp, disp_kwp, sites, kwp}], avisos)."""
    bd_por_chave = {}
    for n in sorted(bd_nomes):
        bd_por_chave.setdefault(chave(n), n)
    em_grupo = {chave(v): g for g in grupos for v in g["vivo"]}
    out, avisos, por_nome = [], [], {}
    for x in indice:
        nome = x["usina"]
        g = em_grupo.get(chave(nome))
        chave_u = g["nome"] if g else nome
        u = por_nome.get(chave_u)
        if u is None:
            if g:
                bd = [b for b in g["ger"] if b in bd_nomes] or [bd_por_chave[chave(b)] for b in g["ger"]
                                                                 if chave(b) in bd_por_chave]
            elif alias.get(nome) in bd_nomes:
                bd = [alias[nome]]
            elif nome in bd_nomes:
                bd = [nome]
            else:
                bd = [bd_por_chave[chave(nome)]] if chave(nome) in bd_por_chave else []
            u = {"nome": chave_u, "bd": bd, "disp": [], "disp_kwp": {}, "sites": [], "kwp": 0.0}
            por_nome[chave_u] = u
            out.append(u)
            if not bd:
                avisos.append(f"{chave_u}: sem aba no BD_Thopen — fora do PR (a disponibilidade conta)")
        u["disp"].append(nome)
        u["disp_kwp"][nome] = x.get("pot_kwp") or 0.0
        if x.get("fracttal") and x["fracttal"] not in u["sites"]:
            u["sites"].append(x["fracttal"])
        u["kwp"] += x.get("pot_kwp") or 0.0
    return out, avisos


def _cruza(e, ini, fim):
    d0 = _data(e.get("d0") or e.get("inicio"))
    d1 = _data(e.get("d1") or e.get("fim")) or fim
    return d0 is not None and d0 <= fim and d1 >= ini


ABERTA = {0, 1, 5, 6}
TIPOS_ACAO = CORRETIVAS | {"Religamento", "Religamento Remoto"}


def acao_sugerida(linhas, sites, ini, fim):
    """A OS aberta mais nova da usina (corretiva ou religamento) até o fim do período, como "OS 12345 · Corretiva ·
    aberta desde 29/09". É sugestão: quem confirma a ação da Grid é o analista."""
    melhor = None
    for x in linhas or []:
        if x.get("groups_1_description") not in sites or x.get("id_status_work_order") not in ABERTA:
            continue
        if x.get("tasks_log_task_type_main") not in TIPOS_ACAO:
            continue
        d = _dia_br(x.get("event_date") or x.get("creation_date"))
        if d is None or d > fim:
            continue
        if melhor is None or d > melhor[0]:
            melhor = (d, x)
    if not melhor:
        return None
    d, x = melhor
    return f"OS {x.get('wo_folio')} · {x.get('tasks_log_task_type_main')} · aberta desde {d:%d/%m}"


def _disp_por_dia(L, u, ini, fim):
    """{date: disponibilidade 0–1} da unidade no período e nos 30 dias antes (o típico), pelas partes do índice
    ponderadas pelo kWp — sem kWp no cadastro, partes iguais."""
    partes = [(L.disp_diario(x) or {}, (u.get("disp_kwp") or {}).get(x) or 0.0) for x in u["disp"]]
    pesos = [k for _, k in partes] if any(k for _, k in partes) else [1.0] * len(partes)
    out = {}
    for d in dias(fim - timedelta(days=TIPICO_DIAS - 1), fim):
        h = sum(((dd.get(d.isoformat()) or {}).get("h_eq") or 0.0) * p for (dd, _), p in zip(partes, pesos)) / sum(pesos)
        out[d] = max(0.0, 1.0 - h / JANELA_H)
    return out


def montar(ini, fim, unids, L):
    """O relatório inteiro do período. `L` são os leitores (o app passa os reais; o teste, stubs): diario(aba),
    pot(aba), metas(aba), disp_diario(usina do índice), oss(), linhas_os(), falhas() → {strings, trackers} e, se tiver,
    rondas() → linhas do workbook de rondas."""
    avisos, linhas, partes_port, disp_itens, avisos_disp = [], [], [], [], []
    oss, los, fal = L.oss() or [], L.linhas_os() or [], L.falhas() or {}
    series = []
    for u in unids:
        partes = []
        ger_dia = {}
        for aba in u["bd"]:
            for x in L.diario(aba) or []:
                if x.get("data") is not None and x.get("ger") is not None:
                    ger_dia[x["data"]] = ger_dia.get(x["data"], 0.0) + x["ger"]
        for aba in u["bd"]:
            pot, metas = L.pot(aba), L.metas(aba)
            if not pot:
                avisos.append(f"{aba}: sem potência no cadastro — fora do PR")
                continue
            if not metas:
                avisos.append(f"{aba}: sem meta do cliente — fora do PR")
                continue
            diario = L.diario(aba)
            series.append((diario, pot, metas))
            partes.append(pr_unidade(diario, pot, metas, ini, fim))
        pr = soma(partes) if partes else None
        dd = [(disponibilidade(L.disp_diario(x), ini, fim), (u.get("disp_kwp") or {}).get(x) or 0.0) for x in u["disp"]]
        disp_itens += dd
        dp = disponibilidade_portfolio(dd)
        if u["disp"] and ger_dia:
            avisos_disp += geracao_x_disponibilidade(u["nome"], ger_dia, _disp_por_dia(L, u, ini, fim), ini, fim)
        # a perda do desligamento na régua dos outros ofensores: horas equivalentes de usina inteira parada × a geração
        # média da usina por hora de sol no período. O kWh do índice é potência nominal × horas e inflava o desligamento
        # contra trackers e strings, que já vêm na irradiância real (Altair 21–27/09: 1,6 h de queda na frente de 56
        # trackers parados)
        pesos = [k for _, k in dd] if any(k for _, k in dd) else [1.0] * len(dd)   # sem kWp no cadastro: partes iguais
        h_eq_u = sum(r_["h_eq"] * k for (r_, _), k in zip(dd, pesos)) / sum(pesos) if pesos else 0.0
        dias_ger = (pr["dias_validos"] + pr["dias_sem_ipoa"]) if pr else 0
        kwh_indisp = h_eq_u * (pr["ger_total_kwh"] / (JANELA_H * dias_ger)) if (pr and dias_ger) else 0.0
        desl = desligamentos(oss, ini, fim, set(u["disp"]))
        nomes = {u["nome"], *u["disp"]}
        trk = [e for e in fal.get("trackers") or [] if e.get("usina") in nomes and _cruza(e, ini, fim)]
        strs = [e for e in fal.get("strings") or [] if e.get("usina") in nomes and _cruza(e, ini, fim)]
        ln = {"nome": u["nome"], "pr": pr["pr"] if pr else None, "pr_meta": pr["pr_meta"] if pr else None,
              "disp": dp["disp"], "kwp": u["kwp"], "desligamentos": desl, "fora": False,
              "dias_sem_ipoa": pr["dias_sem_ipoa"] if pr else None}
        if pr and pr["pr"] is not None:
            partes_port.append(pr)
            if pr["dias_sem_ipoa"]:
                avisos.append(f"{u['nome']}: {pr['dias_sem_ipoa']} dia(s) sem IPOA, fora do PR")
        elif pr:                                         # sem geração nenhuma não é falta de IPOA (Ribeirão Cascalheiras)
            avisos.append(f"{u['nome']}: " + ("nenhum dia com IPOA no período" if pr["ger_total_kwh"] else
                                              "sem geração no BD_Thopen no período") + " — fora do PR")
        if pr and fora_da_meta(pr):
            ofs = ofensores(desl, trk, strs, pr, kwh_indisp, ini, fim)
            ln.update(fora=True, perda_mwh=perda_estimada_mwh(pr), ofensores=ofs, causa_sugerida=causa_sugerida(ofs),
                      acao_sugerida=acao_sugerida(los, set(u["sites"]), ini, fim))
        linhas.append(ln)
    port, dport = soma(partes_port), disponibilidade_portfolio(disp_itens)
    fora = sorted((l for l in linhas if l["fora"]), key=lambda l: -l["perda_mwh"])
    todos = {n for u in unids for n in u["disp"]}
    desl_port = desligamentos(oss, ini, fim, todos)
    ev = pr_mensal(series, meses_desde(ASSUNCAO, fim))
    comp = [m for m in ev if m["pr"] is not None]
    sites = {s for u in unids for s in u["sites"]}
    executado = os_executadas(los, sites, ini, fim)
    executado["strings_voltaram"] = strings_voltaram(fal.get("strings"), ini, fim, todos | {u["nome"] for u in unids})
    rel = religamento(los, sites, ini, fim)
    executado.update(religamento_medio_min=rel["medio_min"], religamento_mediano_min=rel["mediano_min"],
                     religamentos=rel["n"], religamentos_retroativos=rel["retroativas"])
    executado["rondas"] = rondas(L.rondas(), sites, ini, fim) if hasattr(L, "rondas") else None
    if los and not com_fim_da_tarefa(los):
        avisos.append("a base de OS ainda não tem o fim de cada tarefa: tempo de religamento vazio e \"finalizada\" = OS "
                      "concluída até o worker varrer as OS de novo")
    avisos += avisos_disp
    return {
        "periodo": {"ini": ini.isoformat(), "fim": fim.isoformat(), "dias": len(dias(ini, fim)),
                    "semana": ini.isocalendar()[1]},
        "resumo": {"pr": port["pr"], "pr_meta": port["pr_meta"], "disp": dport["disp"], "disp_meta": DISP_META,
                   "ger_x_meta": (port["ger_total_kwh"] / port["meta_kwh"]) if port["meta_kwh"] else None,
                   "ipoa_x_meta": (port["ipoa"] / port["ipoa_meta"]) if port["ipoa_meta"] else None,
                   "fora": len(fora), "total": len(partes_port), "tol": TOL_META},
        "evolucao": {"meses": ev, "desde": ASSUNCAO.isoformat()[:7],
                     "pr_primeiro": comp[0]["pr"] if comp else None, "pr_atual": comp[-1]["pr"] if comp else None,
                     "ganho_pp": ((comp[-1]["pr"] - comp[0]["pr"]) * 100) if len(comp) > 1 else None},
        "executado": executado,
        "disponibilidade": {"disp": dport["disp"], "meta": DISP_META, "queda": desl_port["queda"],
                            "equip": desl_port["equip"], "indisp_grid": dport["indisp_grid"],
                            "indisp_ext": dport["indisp_ext"],
                            "abaixo": sorted(({"nome": l["nome"], "disp": l["disp"]} for l in linhas
                                              if l["disp"] is not None and l["disp"] < DISP_META),
                                             key=lambda x: x["disp"])},
        "fora_da_meta": fora,
        "usinas": linhas,
        "avisos": avisos,
    }


# ── direcionamentos e emissão ───────────────────────────────────────────────────────────────────────────────────
# O analista confirma ou corrige na página a causa, a ação e a previsão de cada usina fora da meta, e escreve a leitura
# da semana (spec, seção 5). O app guarda isto em relatorio_semanal.json, por período; aqui só a regra, sem arquivo.
CAMPOS_LINHA = ("causa", "acao", "previsao")
CAMPOS_GERAIS = ("leitura", "responsavel", "contato")
TAM_MAX = 2000                  # um campo de texto: acima disso é cola por engano, não direcionamento
TAM_USINA = 120


class Recusado(ValueError):
    """O que a página mandou não entra: campo trocado ou emissão incompleta. A rota devolve o motivo, não um 500."""


def chave(ini, fim):
    return f"{ini.isoformat()}|{fim.isoformat()}"


def versao(n):
    return f"R{n:02d}"


def _txt(s):
    """O texto como vai ao PDF: espaço repetido vira um (o contenteditable manda &nbsp;), linha vazia some."""
    linhas = (" ".join(l.split()) for l in str(s if s is not None else "").replace("\r\n", "\n").replace("\r", "\n")
              .split("\n"))
    return "\n".join(l for l in linhas if l)


def faltando(snap):
    """O que impede a emissão: a leitura da semana, o responsável e, em cada usina do bloco 05, a causa e a ação. A
    causa "Sem ofensor medido…" é o convite para o analista escrever a causa, não uma causa. A página tem a mesma
    régua em JS (faltando, em relatorio_semanal.html); o teste trava as duas iguais."""
    f = []
    if not _txt(snap.get("leitura")):
        f.append({"campo": "leitura", "texto": "a leitura da semana"})
    if not _txt(snap.get("responsavel")):
        f.append({"campo": "responsavel", "texto": "o responsável"})
    for l in snap.get("linhas") or []:
        u = _txt(l.get("usina")) or "?"
        c = _txt(l.get("causa"))
        if not c or c == SEM_OFENSOR:
            f.append({"campo": "causa", "usina": u, "texto": f"a causa de {u}"})
        if not _txt(l.get("acao")):
            f.append({"campo": "acao", "usina": u, "texto": f"a ação de {u}"})
    return f


def direcionamentos(estado, ini, fim):
    """O que já foi escrito no período, para a página preencher os campos. `padrao` = o responsável e o contato da
    última vez que alguém os preencheu, para não redigitar toda segunda."""
    p = (estado or {}).get(chave(ini, fim)) or {}
    emis = p.get("emissoes") or []
    return {"leitura": p.get("leitura"), "responsavel": p.get("responsavel"), "contato": p.get("contato"),
            "linhas": p.get("linhas") or {},
            "emissoes": [{"versao": e.get("versao"), "em": e.get("em"), "por": e.get("por")} for e in emis],
            "proxima_versao": versao(len(emis)),
            "padrao": (estado or {}).get("_padrao") or {}}


def _padrao(estado, campo, v):
    if campo in ("responsavel", "contato") and v:
        estado.setdefault("_padrao", {})[campo] = v


def grava_campo(estado, ini, fim, campo, valor, usina=None, em=None, por=None):
    """Um campo do analista → o estado (muda no lugar); devolve o texto como ficou. Campo de linha (causa, ação,
    previsão) vem com a usina; leitura, responsável e contato vêm sem. O contrário é recusado: gravado no lugar
    errado, o texto sumiria da tela sem aviso."""
    u = _txt(usina)[:TAM_USINA] or None
    if not (campo in CAMPOS_LINHA and u or campo in CAMPOS_GERAIS and not u):
        raise Recusado(f"campo {campo!r} {'com' if u else 'sem'} usina: causa, acao e previsao vão com a usina; "
                       "leitura, responsavel e contato, sem")
    v = _txt(valor)[:TAM_MAX]
    p = estado.setdefault(chave(ini, fim), {})
    if u:
        p.setdefault("linhas", {}).setdefault(u, {}).update({campo: v, "em": em, "por": por})
    else:
        p[campo] = v
        _padrao(estado, campo, v)
    p["em"] = em
    return v


def registra_emissao(estado, ini, fim, snap, em, por):
    """A emissão do período → a versão (R00 na primeira, R01 na correção…). Guarda o que foi ao cliente: os campos do
    analista e os números que a página mostrava. E o que foi emitido vira o direcionamento salvo do período — a página
    reaberta e o PDF não podem divergir."""
    if faltando(snap):
        raise Recusado("emissão incompleta")
    gerais = {c: _txt(snap.get(c))[:TAM_MAX] for c in CAMPOS_GERAIS}
    linhas = []
    for l in snap.get("linhas") or []:
        u = _txt(l.get("usina"))[:TAM_USINA]
        if not u:
            continue
        item = {"usina": u, **{c: _txt(l.get(c))[:TAM_MAX] for c in CAMPOS_LINHA}}
        item.update({k: l[k] for k in ("pr", "pr_meta", "perda_mwh") if _numero(l.get(k))})
        linhas.append(item)
    p = estado.setdefault(chave(ini, fim), {})
    emis = p.setdefault("emissoes", [])
    v = versao(len(emis))
    for item in linhas:
        p.setdefault("linhas", {}).setdefault(item["usina"], {}).update(
            {c: item[c] for c in CAMPOS_LINHA}, em=em, por=por)
    p.update(gerais)
    for c, x in gerais.items():
        _padrao(estado, c, x)
    resumo = {k: x for k, x in (snap.get("resumo") or {}).items() if _numero(x)}
    emis.append({"versao": v, "em": em, "por": por, **gerais, "linhas": linhas, "resumo": resumo})
    p["em"] = em
    return v


def _numero(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)
