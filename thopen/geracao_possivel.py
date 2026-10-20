# -*- coding: utf-8 -*-
"""Geração possível pelo IPOA (Levi, 20/10/2026) — a conta da Visão Geral e da linha preta do Diário, de 10/2026 em
diante. Puro: sem rede, sem Flask, nada no import (a plataforma importa o dashboard_thopen, que importa este módulo).

Por quê: a Visão Geral comparava a produção até o corte com a meta do MÊS INTEIRO — no meio do mês toda usina aparecia
"abaixo da meta" — e não dizia quanto a usina deveria ter gerado com o sol que de fato fez. A regra do Levi, em ordem:
  1. Só os dias com geração; meta de geração e de IPOA proporcionais a esses dias (meta mensal ÷ dias do mês, somada).
  2. IPOA do dia = o da ETM se ≥ 0,3 kWh/m²; senão o GHI se ≥ 1,0; senão sem medição. Cobertura < 50% = sem ETM.
     IPOA medido ajustado = Σ IPOA medido ÷ cobertura.
  3. Dif. IPOA = ajustado ÷ meta de IPOA − 1; geração possível = meta × (1 + Dif. IPOA) (o PR já está na meta).
  4. Com expurgos = possível × disponibilidade efetiva (a das OS, ponderada pelo IPOA de cada dia).
  5. Dif. = real ÷ possível − 1 (com e sem expurgos).
  6. Portfólio: possível só das usinas com ETM, contra o real delas; meta e produzida das usinas com meta; IPOA
     ponderado pela potência.
Spec: docs/superpowers/specs/2026-10-20-thopen-geracao-possivel-design.md.
"""

IPOA_MIN = 0.3          # kWh/m²: abaixo disso a ETM não mediu (a régua do Histórico PR)
GHI_MIN = 1.0           # kWh/m²: o GHI só substitui a ETM com um dia de sol de verdade
# Teto físico (20/10/2026, medido no BD_Thopen): uma usina tinha GHI de 10 a 25,7 "kWh/m²" em 45 de 47 dias — parece
# MJ/m² — e 41 dias de outubro tinham IPOA entre 10 e 11,6, plausível em usina com tracker. Acima do teto a leitura não
# conta; nada é convertido (unidade suspeita vira aviso, não número).
IPOA_MAX = 12.0
GHI_MAX = 10.0
COBERTURA_MIN = 0.5


def ipoa_do_dia(ipoa, ghi):
    """(valor, "ETM"|"GHI"|None): o IPOA medido do dia pela regra 2, com o teto físico."""
    if ipoa is not None and IPOA_MIN <= ipoa <= IPOA_MAX:
        return ipoa, "ETM"
    if ghi is not None and GHI_MIN <= ghi <= GHI_MAX:
        return ghi, "GHI"
    return None, None


def possivel_do_dia(meta_mes, meta_ipoa_mes, ipoa_medido):
    """A geração possível de um dia = meta do dia × (IPOA do dia ÷ meta de IPOA do dia) = meta mensal × IPOA ÷ meta
    mensal de IPOA. Sem algum dos três, None."""
    if not meta_mes or not meta_ipoa_mes or ipoa_medido is None:
        return None
    return meta_mes * ipoa_medido / meta_ipoa_mes


def _razao(a, b):
    return (a / b - 1) if (a is not None and b) else None


def periodo(registros, ghi, meta_mes, meta_ipoa_mes, dias_mes, disp):
    """A regra sobre um período (o mês até o corte). `registros` = [{data, ger, ipoa}]; `ghi` = {data: GHI}; `disp` =
    {data: disponibilidade %} (o `operacao_mes.disp_por_dia`, as OS do Fracttal) ou None. Devolve as chaves que a Visão Geral mostra.

    Dia que entra: geração > 0, ou 0 com irradiação medida (a usina parada com sol). O 0 sem medição é a linha que o
    BD cria de antemão para o mês inteiro (em 20/10/2026, hoje e ontem estavam assim em 93 e 92 de 98 usinas): não
    entra, e só é furo de coleta quando vem antes do último dia que entrou."""
    ghi = ghi or {}
    marcados = []
    for r in sorted(registros, key=lambda x: x["data"]):
        med, _ = ipoa_do_dia(r.get("ipoa"), ghi.get(r["data"]))
        g = r.get("ger")
        marcados.append((r["data"], g is not None and (g > 0 or (g == 0 and med is not None)), g, med))
    ultimo = max((d for d, ok, _, _ in marcados if ok), default=None)
    furos = [d for d, ok, _, _ in marcados if not ok and ultimo is not None and d < ultimo]
    entram = [(d, g, med) for d, ok, g, med in marcados if ok]
    n = len(entram)

    meta = (meta_mes / dias_mes * n) if meta_mes else None
    meta_ipoa = (meta_ipoa_mes / dias_mes * n) if meta_ipoa_mes else None
    real = sum(g for _, g, _ in entram)
    medidos = [med for _, _, med in entram if med is not None]
    cobertura = (len(medidos) / n) if n else None
    if not meta_ipoa:
        motivo = "sem_meta_ipoa"
    elif cobertura is None or cobertura < COBERTURA_MIN:
        motivo = "cobertura"
    else:
        motivo = None
    sem_etm = motivo is not None

    ipoa_aj = (sum(medidos) / cobertura) if not sem_etm else None
    dif_ipoa = _razao(ipoa_aj, meta_ipoa) if not sem_etm else None
    possivel = (meta * (1 + dif_ipoa)) if (meta and dif_ipoa is not None) else None

    # disponibilidade efetiva: ponderada pelo IPOA do dia (um dia de sol pesa mais que um nublado); sem medição, a meta
    # de IPOA do dia; o dia sem disponibilidade publicada (o de hoje, ainda não fechado) fica fora da média
    disp_ef = None
    if disp is not None:
        num = den = 0.0
        for d, _, med in entram:
            w = med if med is not None else ((meta_ipoa_mes / dias_mes) if meta_ipoa_mes else None)
            v = disp.get(d)
            if w is None or v is None:
                continue
            num += v * w
            den += w
        disp_ef = (num / den / 100.0) if den > 0 else None
    possivel_exp = (possivel * disp_ef) if (possivel is not None and disp_ef is not None) else None

    return {"dias": n, "furos": furos, "meta": meta, "meta_ipoa": meta_ipoa, "real": real,
            "dias_medidos": len(medidos), "cobertura": cobertura, "ipoa_ajustado": ipoa_aj, "dif_ipoa": dif_ipoa,
            "possivel": possivel, "disp_efetiva": disp_ef, "possivel_exp": possivel_exp,
            "dif_possivel": _razao(real, possivel), "dif_possivel_exp": _razao(real, possivel_exp),
            "sem_etm": sem_etm, "motivo": motivo}


def portfolio(linhas):
    """A linha Total pela regra 6. Cada linha tem `pot_kwp`, `meta`, `produzida` e as chaves do `periodo`."""
    com_meta = [l for l in linhas if l.get("meta")]
    meta = sum(l["meta"] for l in com_meta) if com_meta else None
    produzida = sum(l.get("produzida") or 0 for l in com_meta) if com_meta else None

    etm = [l for l in linhas if not l.get("sem_etm") and l.get("possivel") is not None]
    possivel = sum(l["possivel"] for l in etm) if etm else None
    real_etm = sum(l.get("real") or 0 for l in etm) if etm else None
    pot = [l for l in etm if l.get("pot_kwp") and l.get("ipoa_ajustado") is not None and l.get("meta_ipoa")]
    pw = sum(l["pot_kwp"] for l in pot)
    ipoa_aj = (sum(l["ipoa_ajustado"] * l["pot_kwp"] for l in pot) / pw) if pw else None
    meta_ipoa = (sum(l["meta_ipoa"] * l["pot_kwp"] for l in pot) / pw) if pw else None

    exp = [l for l in etm if l.get("possivel_exp") is not None]
    possivel_exp = sum(l["possivel_exp"] for l in exp) if exp else None
    real_exp = sum(l.get("real") or 0 for l in exp) if exp else None

    return {"meta": meta, "produzida": produzida, "dif_prod": _razao(produzida, meta),
            "ipoa_ajustado": ipoa_aj, "meta_ipoa": meta_ipoa, "dif_ipoa": _razao(ipoa_aj, meta_ipoa),
            "possivel": possivel, "real_etm": real_etm, "dif_possivel": _razao(real_etm, possivel),
            "possivel_exp": possivel_exp, "real_exp": real_exp, "dif_possivel_exp": _razao(real_exp, possivel_exp)}
