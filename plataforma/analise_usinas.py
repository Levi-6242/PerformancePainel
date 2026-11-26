# -*- coding: utf-8 -*-
"""Análise das usinas (25/11/2026): as regras puras da tela que substitui o Painel NOC, o Histórico de PR e a
Disponibilidade. Sem Flask nem rede: o app.py junta o Gerencial, a régua do COS e o estado e chama daqui.

O desenho, as decisões do Levi e o que falta estão em docs/analise-das-usinas.md (leia antes de mexer). As réguas:
- o semáforo é o do mockup aprovado: a razão ≥ 95% do esperado verde, 85 a 95% amarelo, abaixo vermelho; a
  disponibilidade ≥ 98% verde, 95 a 98% amarela, abaixo vermelha; a cor da usina é o PIOR dos três sinais;
- os números do topo são os do Gerencial nas duas visões (decisão de 25/11): geração × P50, PR e meta;
- a disponibilidade é a da régua do COS (o índice da Disponibilidade do Gerencial, o mesmo que vai para
  `falhas_performance · disponibilidade_dia`): o índice só guarda os dias com perda, e o dia sem perda vale 100%."""
import re
import unicodedata
from datetime import date, timedelta

LIM_OK, LIM_ALERTA = 0.95, 0.85
DISP_OK, DISP_ALERTA = 98.0, 95.0
ORDEM = {"critico": 0, "alerta": 1, "ok": 2, "neutro": 3}


def nrm(s) -> str:
    """O nome sem acento, sem caixa e sem espaço sobrando: a chave que casa o Gerencial com a régua do COS."""
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(t.split())


def mes_valido(mes):
    """'AAAA-MM' → (ano, mês), ou None fora do formato."""
    m = re.fullmatch(r"(\d{4})-(\d{2})", str(mes or ""))
    if not m or not 1 <= int(m.group(2)) <= 12:
        return None
    return int(m.group(1)), int(m.group(2))


def sinal(r):
    """A cor de uma razão contra o esperado (geração ÷ P50, PR ÷ meta)."""
    if r is None:
        return "neutro"
    return "ok" if r >= LIM_OK else "alerta" if r >= LIM_ALERTA else "critico"


def sinal_disp(v):
    """A cor da disponibilidade (%)."""
    if v is None:
        return "neutro"
    return "ok" if v >= DISP_OK else "alerta" if v >= DISP_ALERTA else "critico"


def sinal_usina(u) -> str:
    """A cor do card: o pior dos três sinais (geração × P50, PR × meta, disponibilidade); sem nenhum, neutro."""
    s = [sinal(u["at"] / 100) if u.get("at") is not None else "neutro",
         sinal(u["pr"] / u["meta"]) if u.get("pr") is not None and u.get("meta") else "neutro",
         sinal_disp(u.get("disp"))]
    s = [x for x in s if x != "neutro"]
    return min(s, key=ORDEM.get) if s else "neutro"


def agrega(us) -> dict:
    """Geração × P50, PR, meta e disponibilidade de um grupo (o cliente, o filtro) pela conta do Gerencial: o PR é Σ a
    geração dos dias com POA ÷ Σ (POA × potência), não a média das usinas (as de sensor ruim, PR de 300 a 900%, puxavam
    a média simples para 83% em 24/11, contra os 74,1% do Gerencial); a meta pelo mesmo peso; a disponibilidade pela
    potência."""
    cg = [u for u in us if u.get("prod") is not None and u.get("p50")]
    cp = [u for u in us if u.get("ipoa") and u.get("mwp") and u.get("prod_pr") is not None]
    cm = [u for u in cp if u.get("meta")]
    cd = [u for u in us if u.get("disp") is not None and u.get("mwp")]
    s50, sip, sim, sd = (sum(u["p50"] for u in cg), sum(u["ipoa"] * u["mwp"] for u in cp),
                         sum(u["ipoa"] * u["mwp"] for u in cm), sum(u["mwp"] for u in cd))
    return {"at": sum(u["prod"] for u in cg) / s50 if s50 else None,
            "pr": sum(u["prod_pr"] for u in cp) / sip * 100 if sip else None,
            "meta": sum(u["meta"] * u["ipoa"] * u["mwp"] for u in cm) / sim if sim else None,
            "disp": sum(u["disp"] * u["mwp"] for u in cd) / sd if sd else None}


def _dias(periodo):
    ini, fim = (date.fromisoformat(str(x)[:10]) for x in periodo)
    return [(ini + timedelta(d)).isoformat() for d in range((fim - ini).days + 1)]


def disp_mes(diario, periodo):
    """(disponibilidade média do período em %, horas equivalentes perdidas) de uma usina pela régua do COS. O índice só
    guarda os dias com perda: o dia que não está lá vale 100%. Sem o diário da usina, (None, None): a usina que a régua
    não cobre fica SEM disponibilidade, nunca 100%."""
    if diario is None or not periodo:
        return None, None
    dias = _dias(periodo)
    vals = [(diario.get(d) or {}).get("disp") for d in dias]
    vals = [100.0 if v is None else float(v) for v in vals]
    h = sum(float((diario.get(d) or {}).get("h_eq") or 0) for d in dias)
    return (sum(vals) / len(vals) if vals else None), h


def ocorrencias(oss, usina) -> int:
    """Quantas OS (ocorrências) a régua do COS contou na usina no mês: cada OS uma vez, mesmo que cubra várias usinas."""
    alvo = nrm(usina)
    return len({str(o.get("folio")) for o in oss or [] if any(nrm(u) == alvo for u in o.get("usinas") or [])})


def visao(ger: dict, disp, ocultas: dict, mobil: dict) -> dict:
    """A visão inicial: uma linha por usina do Gerencial, com a disponibilidade e as ocorrências da régua do COS, a data
    de mobilização (a Info Geral do BD_Performance) e quem a ocultou (para a equipe). `disp` = o mês do índice da
    Disponibilidade (`_falhas_disp_mes`), ou None quando o índice não tem o mês."""
    cobre = {nrm(u.get("usina")) for u in (disp or {}).get("usinas") or []}
    diario = {nrm(k): v for k, v in ((disp or {}).get("diario") or {}).items()}
    oc = {nrm(k): v for k, v in (ocultas or {}).items()}
    periodo = (disp or {}).get("periodo")
    out = []
    for g in ger.get("usinas") or []:
        k = nrm(g.get("usina"))
        d, h = disp_mes(diario.get(k, {}), periodo) if k in cobre else (None, None)
        u = {"u": g.get("usina"), "c": g.get("cliente"), "at": g.get("atingimento"), "pr": g.get("pr"), "meta": g.get("pr_meta"),
             "prod": g.get("prod"), "prod_pr": g.get("prod_pr"), "ipoa": g.get("ipoa"), "p50": g.get("p50"), "mwp": g.get("pot_mwp"),
             "dias": g.get("dias_cob"), "motivo": g.get("pr_motivo") or g.get("anomalia_txt"),
             "disp": round(d, 1) if d is not None else None, "h_perdidas": round(h, 3) if h is not None else None,
             "nos": ocorrencias((disp or {}).get("oss"), g.get("usina")) if k in cobre else None,
             "mob": (mobil or {}).get(k), "oculta": oc.get(k)}
        u["sinal"] = sinal_usina(u)
        out.append(u)
    return {"mes": ger.get("mes"), "lido": ger.get("cache_ts"), "periodo_disp": periodo, "usinas": out}


# ══ o diagnóstico da usina (entrega 2, 26/11/2026) ════════════════════════════════════════════════════════════════════
# Levi, 25/11/2026: "Quanto que essa usina geraria se não fosse essa queda"; "a disponibilidade vai ser calculada pela
# ocorrência do COS"; os ofensores "inversor parado, tracker parado, string sem corrente", cada um com o que o cobre
# (desligamento = a ocorrência do COS; string = a OS de recomposição ou verificação de string do inversor; tracker = o
# chamado de tracker da usina); a vegetação da última ronda (26/11: "essa informação tem nas rondas, a última ronda
# feita"); e os dias sem explicação ("85% tá ok": o PR do dia, somadas as perdas das ocorrências, abaixo de 85% da meta).
import math
import statistics

LIM_SEM_EXPL = 0.85          # o dia sem explicação: PR + perdas das ocorrências < 85% da meta (Levi, 25/11/2026)
NASCER, POR = 360, 1080      # 06:00 a 18:00: a janela de sol do dia típico sem curva
VEG_ACIMA = 3                # vegetação acima de 3 pede ação (a régua do App e da Zeladoria do Nexus)
RX_JANELA = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")


def minuto(hhmm) -> int:
    """'07:30' → 450."""
    h, m = str(hhmm).strip()[:5].split(":")
    return int(h) * 60 + int(m)


def janelas(trechos) -> list:
    """'12:24-13:30; 14:00-14:10' → [(744, 810), (840, 850)]: os trechos de uma ocorrência no dia, em minutos."""
    return [(int(a) * 60 + int(b), int(c) * 60 + int(d)) for a, b, c, d in RX_JANELA.findall(str(trechos or ""))]


def e_inversor(escopo) -> bool:
    return str(escopo or "").strip().lower().startswith("inversor")


def ocorrencias_usina(disp, usina, hoje=None) -> list:
    """As ocorrências da régua do COS de uma usina no mês, uma por OS e dia: {dia, os, tipo, origem, escopo, trechos, h,
    prot, aberta, ini, fim, dias_aberta}. `disp` = o mês do índice da Disponibilidade (`_falhas_disp_mes`): o diário
    (`os` de cada dia: folio, horas e trechos) junto com a OS (tipo, origem, o rótulo do escopo nesta usina, proteções)."""
    if not disp:
        return []
    k = nrm(usina)
    dias = next((v for u, v in (disp.get("diario") or {}).items() if nrm(u) == k), None) or {}
    oss = {str(o.get("folio")): o for o in disp.get("oss") or []}
    hoje = hoje or date.today()
    out = []
    for dia in sorted(dias):
        for x in (dias[dia] or {}).get("os") or []:
            f = str(x.get("folio"))
            o = oss.get(f) or {}
            rot = next((e.get("rotulo") for e in o.get("escopo") or [] if nrm(e.get("usina")) == k), None)
            ini = str(o.get("ini") or "")[:19] or None
            aberta = bool(o.get("aberta"))
            dias_ab = None
            if aberta and ini:
                try:
                    dias_ab = (hoje - date.fromisoformat(ini[:10])).days
                except ValueError:
                    pass
            out.append({"dia": dia, "os": f, "tipo": (o.get("tipos") or [""])[0], "origem": o.get("origem") or "",
                        "escopo": rot or "Usina inteira", "trechos": x.get("trechos") or "", "h": x.get("h"),
                        "prot": "; ".join(str(p) for p in o.get("protecoes") or []) or None, "aberta": aberta,
                        "ini": ini, "fim": str(o.get("fim") or "")[:19] or None, "dias_aberta": dias_ab})
    return out


def perda_inversor(inv_dia: dict, nome):
    """O inversor parado (Levi, 25/11/2026): o que ele geraria é a geração mediana dos OUTROS inversores no dia (o BD por
    inversor); a perda, isso menos o que ele gerou. None quando o dia não tem o inversor ou os outros."""
    alvo = nrm(nome)
    meu = next((v for n, v in (inv_dia or {}).items() if nrm(n) == alvo), None)
    outros = [float(v) for n, v in (inv_dia or {}).items() if nrm(n) != alvo and v is not None]
    if meu is None or not outros:
        return None
    esp = statistics.median(outros)
    return {"geraria": round(esp), "gerou": round(float(meu)), "perda": round(max(0.0, esp - float(meu))),
            "metodo": "inversor"}


def perda_queda(pot: dict, poa: dict, jans, passo=5):
    """A queda da usina ou da cabine: a razão potência ÷ POA da hora antes e da hora depois de cada janela, vezes a POA de
    cada passo da janela, é o que a usina geraria; menos o que ela gerou na janela. `pot` = {minuto: kW da usina}, `poa` =
    {minuto: W/m²}. None quando a hora em volta não tem sol (POA > 30) para tirar a razão."""
    if not jans:
        return None
    esp = med = 0.0
    for ini, fim in jans:
        fora = [m for m in poa if (ini - 60 <= m < ini or fim < m <= fim + 60) and (poa[m] or 0) > 30]
        sp = sum(poa[m] for m in fora)
        if not fora or not sp:
            return None
        k = sum(pot.get(m, 0) or 0 for m in fora) / sp
        dentro = [m for m in sorted(poa) if ini <= m < fim]
        esp += sum(k * (poa[m] or 0) for m in dentro) * passo / 60
        med += sum(pot.get(m, 0) or 0 for m in dentro) * passo / 60
    return {"geraria": round(esp), "gerou": round(med), "perda": round(max(0.0, esp - med)), "metodo": "queda"}


def fracao_do_sol(jans, poas=()) -> float:
    """Que fatia do sol de um dia a janela leva. Com curvas de POA de outros dias ({minuto: W/m²}, as de mais de 120
    leituras), a média delas; sem nenhuma, o dia de céu limpo (o seno das 06 às 18 h). É a perda "estimativa" do dia sem
    curva no banco: na Santarém 2 de 01 a 04/11 (a média por hora de sol exagerava: 1,69 MWh contra uns 0,8)."""
    fr = []
    for pz in poas or ():
        tot = sum(v or 0 for v in pz.values())
        if tot > 0 and len(pz) > 120:
            fr.append(sum(v or 0 for m, v in pz.items() if any(a <= m < z for a, z in jans)) / tot)
    if fr:
        return sum(fr) / len(fr)
    ang = lambda m: math.pi * (min(max(m, NASCER), POR) - NASCER) / (POR - NASCER)
    return sum((math.cos(ang(a)) - math.cos(ang(z))) / 2 for a, z in jans)


def perda_estimada(ger_dia_mwh, fracao):
    """Sem curva: a geração do dia (BD) vezes a fatia da janela, marcada como estimativa (a usina não gerou na queda)."""
    if not ger_dia_mwh or not fracao:
        return None
    esp = float(ger_dia_mwh) * 1000 * fracao
    return {"geraria": round(esp), "gerou": None, "perda": round(esp), "metodo": "dia_tipico"}


def matriz_inversores(inv_dias: dict, kwp=None) -> dict:
    """{inversor: [razão contra a mediana dos outros no dia, por dia]} (o "dia a dia × os outros" da tabela). Com a
    potência de cada um, a razão é pela energia por kWp (inversores de tamanhos diferentes); sem ela, pela energia."""
    nomes = sorted({n for v in inv_dias.values() for n in v})
    out = {n: [] for n in nomes}
    for dia in sorted(inv_dias):
        v = inv_dias[dia] or {}
        y = {n: (float(v[n]) / kwp[n] if kwp and kwp.get(n) else float(v[n])) for n in nomes if v.get(n) is not None}
        for n in nomes:
            outros = [x for m, x in y.items() if m != n]
            med = statistics.median(outros) if outros else None
            out[n].append(round(y[n] / med, 3) if n in y and med else None)
    return out


def parados_sem_ocorrencia(inv_dias: dict, ocorr, minimo_kwh=50.0) -> list:
    """[(dia, inversor)] em que o inversor gerou menos de 2% da mediana dos outros (com os outros gerando ao menos
    `minimo_kwh`) e o COS não tem ocorrência dele no dia: o inversor parado que ninguém registrou."""
    cobertos = {(o["dia"], nrm(o["escopo"])) for o in ocorr or () if e_inversor(o.get("escopo"))}
    out = []
    for dia in sorted(inv_dias):
        v = {n: float(x) for n, x in (inv_dias[dia] or {}).items() if x is not None}
        for n, x in v.items():
            outros = [y for m, y in v.items() if m != n]
            med = statistics.median(outros) if outros else 0
            if med >= minimo_kwh and x < 0.02 * med and (dia, nrm(n)) not in cobertos:
                out.append((dia, n))
    return out


def dias_sem_explicacao(dias, perda_mwh: dict, pot_mwp, meta) -> list:
    """Os dias de baixa performance sem explicação (Levi, 25/11/2026: "85% tá ok"): o PR do dia, devolvidas as perdas
    das ocorrências do COS (MWh ÷ POA × potência), ainda abaixo de 85% da meta. Dia sem POA ou sem PR fica de fora."""
    if not pot_mwp or not meta:
        return []
    out = []
    for d in dias:
        pr, poa = d.get("pr"), d.get("poa")
        if pr is None or not poa or poa < 0.3:
            continue
        aj = pr + (perda_mwh.get(d["d"]) or 0) / (poa * pot_mwp)
        if aj < LIM_SEM_EXPL * meta:
            out.append(d["d"])
    return out


def _br(iso):
    s = str(iso or "")[:10]
    return f"{s[8:10]}/{s[5:7]}" if len(s) == 10 else ""


def _virg(v, c=1):
    return f"{v:.{c}f}".replace(".", ",")


def _num_trk(nome) -> str:
    """'Tracker 51' e '51' → '51'; 'Tracker 2.3' → '2.3': a chave do tracker entre a Falhas e os chamados."""
    m = re.search(r"\d+(?:\.\d+)?", str(nome or ""))
    return (m.group().lstrip("0") or "0") if m else ""


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def vegetacao(linhas, uid):
    """A última leitura de campo da usina na Zeladoria que o Nexus publica (`nexus_zeladoria · zeladoria_semana`, a
    semana mais recente dela): o nível da vegetação e da sujidade na última ronda, a OS da ronda, a recomendação, a
    situação da supressão e a última supressão e limpeza. None sem a usina no livro."""
    l = [r for r in linhas or () if uid is not None and str(_int(r.get("usina_id"))) == str(uid) and r.get("semana")]
    if not l:
        return None
    r = max(l, key=lambda x: (str(x.get("semana")), str(x.get("data_id_leitura") or "")))
    di = lambda v: (lambda s: f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else None)(str(v or "").split(".")[0])
    nv = lambda v: (lambda n: n if n is not None and 1 <= n <= 5 else None)(_int(v))
    tx = lambda v: str(v).split(".")[0] if v not in (None, "") else None
    return {"semana": r.get("semana"), "leitura": di(r.get("data_id_leitura")), "os": tx(r.get("os")),
            "vegetacao": nv(r.get("vegetacao_nivel")), "sujidade": nv(r.get("sujidade_nivel")), "vala": r.get("vala") or None,
            "recomendacao": r.get("recomendacao") or None,
            "sit_veg": str(r.get("situacao_vegetacao") or "").replace("_", " ") or None,
            "prazo_veg": di(r.get("data_id_prazo_vegetacao")), "data_sit_veg": di(r.get("data_id_situacao_vegetacao")),
            "os_veg": tx(r.get("os_zeladoria_vegetacao")),
            "ult_supressao": di(r.get("data_id_ultima_supressao")), "ult_limpeza": di(r.get("data_id_ultima_limpeza"))}


def _ofensor_inversor(ocorr, parados_sem_ocorr):
    grupos = {}
    for o in ocorr or ():
        if e_inversor(o.get("escopo")):
            g = grupos.setdefault((o["os"], o["escopo"]), {"os": o["os"], "eq": o["escopo"], "dias": 0, "perda": 0.0,
                                                            "aberta": o.get("aberta"), "ini": o.get("ini"),
                                                            "dias_aberta": o.get("dias_aberta")})
            g["dias"] += 1
            g["perda"] += o.get("perda") or 0
    sem = {}
    for d, n in parados_sem_ocorr or ():
        sem.setdefault(n, []).append(d)
    if not grupos and not sem:
        return None
    l = sorted(grupos.values(), key=lambda g: -g["perda"])
    kwh = sum(g["perda"] for g in l)
    partes = ([g["eq"] + (f" há {g['dias_aberta']} dias" if g.get("dias_aberta") is not None else f", {g['dias']} dias") for g in l]
              + [f"{n} zerou {len(ds)} dia{'s' if len(ds) > 1 else ''} sem ocorrência" for n, ds in sorted(sem.items())])
    abertas = [g for g in l if g["aberta"]]
    if sem:
        cob = {"tom": "critico", "txt": "Zerou sem ocorrência do COS: " + ", ".join(sorted(sem))}
        passo = f"Abrir a ocorrência no COS para {', '.join(sorted(sem))}."
    else:
        cob = {"tom": "ok", "txt": "Ocorrência do COS: " + ", ".join(f"OS {g['os']}" + (" aberta" if g["aberta"] else " fechada") for g in l)}
        passo = f"Cobrar a OS {abertas[0]['os']} ({abertas[0]['eq']})." if abertas else "Conferir se voltou de vez."
    return {"sev": "critico", "t": "Inversor parado", "s": " · ".join(partes) + (f" · {_virg(kwh / 1000)} MWh no mês" if kwh else ""),
            "cob": cob, "p": passo, "kwh": kwh, "eq": [g["eq"] for g in l] + sorted(sem),
            "c": [["Ocorrência do COS", f"OS {g['os']} · {g['eq']} desde {_br(g['ini'])} · {g['dias']} dias no mês · {_virg(g['perda'] / 1000)} MWh"] for g in l]
                 + [["Sem ocorrência", f"{n}: zerou em {', '.join(_br(d) for d in ds)} com os outros gerando"] for n, ds in sorted(sem.items())]}


def _ofensor_tracker(trk_rows, trk_chamados):
    if not trk_rows:
        return None
    por = {}
    for r in trk_rows:
        x = por.setdefault(_num_trk(r.get("tracker")), {"nome": r.get("tracker"), "kwh": 0.0, "h": 0.0, "aberta": False})
        x["kwh"] += r.get("perda_kwh") or 0
        x["h"] += r.get("h_sol") or 0
        x["aberta"] = x["aberta"] or not r.get("fim")
    ch = {_num_trk(c.get("tracker")): c for c in trk_chamados or ()}
    l = sorted(por.items(), key=lambda kv: -kv[1]["kwh"])
    com = [k for k, _ in l if k in ch]
    semc = [v["nome"] for k, v in l if k not in ch]
    kwh = sum(v["kwh"] for _, v in l)
    if not semc:
        cob = {"tom": "ok", "txt": "Chamado aberto para todos"}
    elif com:
        cob = {"tom": "alerta", "txt": f"Chamado para {len(com)} de {len(l)}; sem chamado: " + ", ".join(semc[:4]) + (" e mais" if len(semc) > 4 else "")}
    else:
        cob = {"tom": "critico", "txt": "Nenhum chamado de tracker aberto para eles"}
    return {"sev": "severo", "t": "Tracker parado", "s": (f"{len(l)} trackers pararam" if len(l) > 1 else "1 tracker parou") + f" no mês · {_virg(kwh / 1000)} MWh",
            "cob": cob, "p": f"Abrir chamado para {', '.join(semc[:4])}." if semc else "Acompanhar os chamados.", "kwh": kwh,
            "eq": [v["nome"] for _, v in l],
            "c": [["O que mais perde", ", ".join(f"{v['nome']} ({_virg(v['kwh'] / 1000, 2)} MWh{', ainda parado' if v['aberta'] else ''})" for _, v in l[:5])],
                  ["Chamados", ", ".join(f"Tracker {k} desde {ch[k].get('desde') or '—'}" for k in com) or "nenhum para estes trackers"]]}


def _ordem_str(s):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", str(s))]


def _ofensor_string(strings_ep, strings_os):
    if not strings_ep:
        return None
    por = {}
    for e in strings_ep:
        x = por.setdefault(e.get("inversor") or "?", {"strings": set(), "kwh": 0.0, "aberta": False})
        x["strings"].add(str(e.get("string")))
        x["kwh"] += e.get("perda_kwh") or 0
        x["aberta"] = x["aberta"] or not e.get("fim")
    oss = {}
    for o in strings_os or ():
        if not re.search(r"cancel", str(o.get("status") or ""), re.I):
            oss.setdefault(nrm(o.get("inversor")), []).append(o)
    l = sorted(por.items(), key=lambda kv: -kv[1]["kwh"])
    semos = [inv for inv, _ in l if not oss.get(nrm(inv))]
    kwh = sum(v["kwh"] for _, v in l)
    if not semos:
        cob = {"tom": "ok", "txt": "OS de string no Fracttal para todos"}
    else:
        cob = {"tom": "critico" if len(semos) == len(l) else "alerta",
               "txt": "Sem OS de recomposição ou verificação de string para " + ", ".join(i.replace("Inversor ", "") for i in semos[:5]) + (" e mais" if len(semos) > 5 else "")}
    lista = ", ".join(f"{inv.replace('Inversor ', '')} · {', '.join(sorted(v['strings'], key=_ordem_str))}" for inv, v in l[:4])
    return {"sev": "alerta", "t": "String sem corrente", "s": lista + (" e mais" if len(l) > 4 else "") + f" · {_virg(kwh / 1000)} MWh",
            "cob": cob, "p": "Abrir OS de verificação de string (fusível, conector)." if semos else "Acompanhar as OS de string.",
            "kwh": kwh, "eq": [inv for inv, _ in l],
            "c": [["Falhas", f"{inv}: {', '.join(sorted(v['strings'], key=_ordem_str))} · {_virg(v['kwh'] / 1000, 2)} MWh{' · ainda sem corrente' if v['aberta'] else ''}"] for inv, v in l[:6]]
                 + [["OS no Fracttal", ", ".join(f"{o.get('os')} ({o.get('inversor')}, {o.get('status')})" for v in oss.values() for o in v[:2]) or "nenhuma destes inversores"]]}


def _ofensor_vegetacao(veg):
    if not veg or (veg.get("vegetacao") or 0) <= VEG_ACIMA:
        return None
    sit = veg.get("sit_veg") or "sem dado"
    if sit in ("programada", "feita"):
        cob = {"tom": "ok", "txt": f"Supressão {sit}" + (f" em {_br(veg.get('data_sit_veg'))}" if veg.get("data_sit_veg") else "")}
    else:
        cob = {"tom": "critico", "txt": "Supressão a programar" + (f" (prazo {_br(veg.get('prazo_veg'))})" if veg.get("prazo_veg") else "")}
    return {"sev": "critico" if veg["vegetacao"] >= 5 else "alerta", "t": "Vegetação alta",
            "s": f"nível {veg['vegetacao']} de 5 na ronda de {_br(veg.get('leitura'))}" + (f" (OS {veg['os']})" if veg.get("os") else ""),
            "cob": cob, "p": "Programar a supressão vegetal." if cob["tom"] != "ok" else "Conferir na próxima ronda.", "kwh": None, "eq": [],
            "c": [["Última ronda", f"{_br(veg.get('leitura'))}: vegetação {veg.get('vegetacao')}, sujidade {veg.get('sujidade') or '—'}"],
                  ["Última supressão", _br(veg.get("ult_supressao")) or "sem registro no Nexus"]]}


def ofensores(ocorr, strings_ep, strings_os, trk_rows, trk_chamados, veg, parados_sem_ocorr=()) -> list:
    """Os ofensores da usina no mês, cada um com o que já o cobre (a regra do Levi, 25/11/2026) e o próximo passo:
    - inversor parado: as ocorrências do COS de inversor (a OS cobre); o inversor que zerou num dia sem ocorrência do
      COS também entra, descoberto;
    - tracker parado: as paradas da Falhas do mês (a régua da plataforma) contra os chamados de tracker da usina;
    - string sem corrente: os episódios da Falhas do mês contra a OS de recomposição ou verificação de string do
      inversor (o índice que a varredura da Disponibilidade publica: a tela não chama o Fracttal);
    - vegetação acima de 3 na última ronda contra a situação da supressão.
    {sev, t, s, cob: {tom, txt}, p, c: [[rótulo, texto]], kwh, eq}; o que tira mais energia primeiro, a vegetação no fim."""
    out = [x for x in (_ofensor_inversor(ocorr, parados_sem_ocorr), _ofensor_tracker(trk_rows, trk_chamados),
                       _ofensor_string(strings_ep, strings_os)) if x]
    out.sort(key=lambda o: -(o["kwh"] or 0))
    v = _ofensor_vegetacao(veg)
    return out + ([v] if v else [])


def observacoes(mensal, ano, mes, cascata, veg, sem_expl, ocorr=()) -> list:
    """As observações (Levi, 25/11/2026: a meta "pode ficar como observação"; "a conta dos expurgos também"): a meta de
    PR que mudou de um mês para o outro, a cascata que estourou (não explicado negativo), a última ronda e os dias sem
    explicação. [{t, s, p}]."""
    out = []
    pts = {(p.get("ano"), p.get("mes")): p for p in (mensal or {}).get("pontos") or []}
    ant = (ano, mes - 1) if mes > 1 else (ano - 1, 12)
    m0, m1 = (pts.get(ant) or {}).get("meta"), (pts.get((ano, mes)) or {}).get("meta")
    if m0 and m1 and abs(m1 - m0) >= 0.005:
        out.append({"t": "A meta de PR " + ("subiu" if m1 > m0 else "caiu"), "s": f"{_virg(m0 * 100)}% no mês anterior, {_virg(m1 * 100)}% neste",
                    "p": "Conferir a meta antes de cobrar a usina."})
    if cascata and isinstance(cascata.get("nao_explicado"), (int, float)) and cascata["nao_explicado"] < 0:
        out.append({"t": "A conta dos expurgos estourou", "s": f"não explicado de {_virg(cascata['nao_explicado'])} MWh: a cascata pôs mais perda em equipamento do que a usina perdeu",
                    "p": "Corrigir a cascata antes de usar como nota (entrega à parte)."})
    if veg:
        out.append({"t": "Última ronda", "s": _br(veg.get("leitura")) + (f" (OS {veg['os']})" if veg.get("os") else "")
                    + f": vegetação {veg.get('vegetacao') or '—'}, sujidade {veg.get('sujidade') or '—'}"
                    + (f" · última supressão {_br(veg['ult_supressao'])}" if veg.get("ult_supressao") else "")
                    + (f" · última limpeza {_br(veg['ult_limpeza'])}" if veg.get("ult_limpeza") else ""),
                    "p": "Acima de 3 pede ação."})
    # a ocorrência que conta a usina parada num dia em que ela gerou o típico (o teto zerou a perda): a OS não bate com a
    # geração e a disponibilidade sai errada (Colider 1, 26/11/2026: 9 OS de religamento abertas, disponibilidade de 4%)
    nao_bate = sorted({o["os"] for o in ocorr or () if o.get("limitada") and not o.get("perda")}, key=lambda s: int(s) if str(s).isdigit() else 0)
    if nao_bate:
        out.append({"t": "Ocorrência que não bate com a geração", "s": "OS " + ", ".join(nao_bate[:8]) + (" e mais" if len(nao_bate) > 8 else "")
                    + ": contam a usina parada em dias em que ela gerou o típico; a disponibilidade sai baixa por causa delas",
                    "p": "Conferir se essas OS já deviam estar fechadas no Fracttal."})
    if sem_expl:
        out.append({"t": "Dias sem explicação", "s": ", ".join(str(d).zfill(2) for d in sem_expl) + ": PR baixo mesmo devolvendo as ocorrências do COS",
                    "p": "Abrir o dia no gráfico e olhar a curva dos inversores."})
    return out


def teto_das_quedas(ocorr, dias, pot_mwp) -> list:
    """A perda ESTIMADA das quedas de um dia (a do dia típico, sem curva) nunca passa do que faltou na geração do dia:
    com a POA, a POA × a potência × o PR típico da usina no mês (a mediana dos dias sem ocorrência; sem eles, a de todos)
    menos o que ela gerou; sem a POA, a geração típica do mês (a mediana dos dias que geraram) menos o que ela gerou.
    Caso que criou a regra (26/11/2026, na bancada): a Colider 1 com 9 OS de religamento do Fracttal abertas, cada uma
    contando a usina inteira parada das 06 às 18 h, e a usina gerando 83% do P50; sem curva, a estimativa somava 1.899
    MWh de "perda" num mês de 302 MWh gerados. Acima do teto, as perdas do dia são reduzidas na mesma proporção e
    marcadas `limitada`. A perda MEDIDA pela curva (a queda de 0,19 MWh da Santarém 2 em 18/11) e a do inversor parado
    (a mediana dos outros) são dado real e não entram. Muda as ocorrências no lugar e as devolve."""
    com_oc = {o["dia"] for o in ocorr or ()}
    ok_pr = lambda d: d.get("pr") is not None and (d.get("poa") or 0) >= 0.3 and 0 < d["pr"] < 1.5
    pr_l = [d["pr"] for d in dias if ok_pr(d)]
    limpos = [d["pr"] for d in dias if ok_pr(d) and d.get("iso") not in com_oc]
    pr_t = statistics.median(limpos or pr_l) if pr_l and pot_mwp else None
    gers = [d["ger"] for d in dias if (d.get("ger") or 0) > 0]
    ger_t = statistics.median(gers) if gers else None
    por_dia = {d.get("iso"): d for d in dias}
    for dia in sorted({o["dia"] for o in ocorr or ()}):
        d = por_dia.get(dia)
        qs = [o for o in ocorr if o["dia"] == dia and not e_inversor(o.get("escopo")) and o.get("perda")
              and o.get("metodo") == "dia_tipico"]
        if not d or d.get("ger") is None or not qs:
            continue
        if d.get("poa") and pr_t is not None:
            falta = max(0.0, (d["poa"] * pot_mwp * pr_t - d["ger"]) * 1000)
        elif ger_t is not None:
            falta = max(0.0, (ger_t - d["ger"]) * 1000)
        else:
            continue
        soma = sum(o["perda"] for o in qs)
        if soma > falta:
            f = falta / soma if soma else 0
            for o in qs:
                o["perda"] = round(o["perda"] * f)
                o["limitada"] = True
    return ocorr
