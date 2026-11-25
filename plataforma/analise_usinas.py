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
