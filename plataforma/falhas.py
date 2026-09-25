# -*- coding: utf-8 -*-
"""Falhas de strings e trackers — régua e contas puras (24/09/2026).

Nasceu do estudo "Falhas de strings e trackers, com a perda em kWh" (pedido do Levi em 24/09): mapear no mês
cada string sem corrente e cada tracker parado, de quando saiu a quando voltou, e quanto deixou de gerar. Aqui
só mora conta que não depende de rede nem de disco — o app entrega as curvas e o cadastro, este módulo devolve
os achados. É o que os testes travam.

Régua de strings (Levi, 24/09): "se a string em período solar (de 6 às 18) ficou mais que 2 horas sem corrente
ou com variação mínima em relação aos demais (às vezes pode haver ruído)". A régua antiga das ocorrências
(corrente <= 0,1 A por 30 min) não via a string morta que lê 0,3 A de ruído, e contava como falha a sombra de
meia hora. Esta compara cada string com as vizinhas do mesmo inversor, célula a célula, e só aponta quem fica
2 h SEGUIDAS sem corrente com o inversor gerando de verdade. Somar o dia não serve: no 2C, em setembro, a sombra do
amanhecer somada à do fim da tarde dava 60 string-dias "sem corrente" em strings que produziam normal o dia todo.
"""
import re

JANELA = (6 * 60, 18 * 60)   # período solar das strings (min do dia)
PASSO = 10                   # grade de 10 min — a mesma das ocorrências da plataforma
FRAC_VIZINHAS = 0.10         # abaixo de 10% da mediana das vizinhas = sem corrente de fato (ruído de string morta)
FRAC_PICO = 0.12             # período útil: inversor a >= 12% do próprio pico do dia (a régua de potência da plataforma)
MIN_TRECHO = 120             # "mais que 2 horas" SEGUIDAS de string morta no período útil
TOLERANCIA = 20              # leitura boa isolada no meio da queda (até 20 min) não parte a queda em duas


def _min(ts):
    try:
        return ts.hour * 60 + ts.minute
    except AttributeError:
        m = re.match(r"(\d{1,2}):(\d{2})", str(ts))
        if not m:
            m = re.search(r"[T ](\d{2}):(\d{2})", str(ts))
        return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def _mediana(vals):
    """Mediana "de cima", a mesma da plataforma (sorted[n // 2])."""
    return sorted(vals)[len(vals) // 2] if vals else None


def _grade(serie, janela, passo):
    """[(ts|hhmm, valor)] → grade de células de `passo` min na janela (última leitura da célula vence;
    None = sem leitura; valor None lido = 0, como na plataforma)."""
    ini, fim = janela
    n = (fim - ini) // passo + 1
    g = [None] * n
    for ts, v in serie or []:
        m = _min(ts)
        if m is None or m < ini or m > fim:
            continue
        g[(m - ini) // passo] = float(v) if v is not None else 0.0
    return g


def strings_sem_corrente(curvas_inv, *, zero, piso_inv, frac_vizinhas=FRAC_VIZINHAS, janela=JANELA, passo=PASSO,
                         min_trecho=MIN_TRECHO, tolerancia=TOLERANCIA, frac_pico=FRAC_PICO):
    """Strings sem corrente do dia pela régua de 24/09.

    curvas_inv = {inversor: {string: [(ts|hhmm, valor)]}} — corrente (A) ou potência (W); `zero` e `piso_inv`
    vão na mesma unidade. Uma célula conta como morta só com o inversor GERANDO (mediana das strings vivas >=
    piso e >= frac_pico do pico do dia, o que corta o sol baixo do amanhecer e do fim da tarde) e se a string lê
    <= zero, não lê nada, ou lê menos que frac_vizinhas da mediana das OUTRAS strings vivas do inversor. Trechos
    mortos se juntam através de leitura boa curta (tolerancia); só entra o trecho com min_trecho de morte seguida.

    Devolve [{inversor, string, saiu, voltou, min_morta, trechos, criterio, fim_producao}] — `voltou` None =
    ficou morta até o inversor parar de gerar (o episódio continua no dia seguinte se ela amanhecer morta)."""
    ini = janela[0]
    n = (janela[1] - janela[0]) // passo + 1
    out = []
    for inv, strings in (curvas_inv or {}).items():
        grades = {sid: _grade(s, janela, passo) for sid, s in (strings or {}).items()}
        grades = {sid: g for sid, g in grades.items() if any(v is not None for v in g)}   # sem leitura: não afirma
        if len(grades) < 2:
            continue                                   # sem vizinhas não há com quem comparar
        # referência = mediana das strings VIVAS (> zero), como no classificador ao vivo: com metade das strings
        # mortas a mediana de todas vira zero e o inversor parecia parado (SMP100 Inversor 3.1, 24/09: 10 de 17
        # zeradas). Uma string viva sozinha não basta para dizer que o inversor está gerando.
        vivas = [[g[i] for g in grades.values() if g[i] is not None and g[i] > zero] for i in range(n)]
        meds = [_mediana(v) if len(v) >= 2 else None for v in vivas]
        pico = max((m for m in meds if m is not None), default=0.0)
        piso = max(piso_inv, pico * frac_pico)
        prod = [m is not None and m >= piso for m in meds]
        if not any(prod):
            continue                                   # inversor não gerou: o problema é dele, não das strings
        ult_prod = max(i for i in range(n) if prod[i])
        for sid, g in grades.items():
            morta, crit = [None] * n, [None] * n
            for i in range(n):
                if not prod[i]:
                    continue
                v = g[i]
                if v is None or v <= zero:
                    morta[i], crit[i] = True, "zerada"
                    continue
                viz = _mediana([grades[o][i] for o in grades if o != sid and grades[o][i] is not None and grades[o][i] > zero])
                if viz is not None and v < frac_vizinhas * viz:
                    morta[i], crit[i] = True, "abaixo_das_vizinhas"
                else:
                    morta[i] = False
            # trechos: célula sem produção do inversor é neutra (nuvem forte não parte nem estende a queda)
            trechos, cur, folga = [], None, 0
            for i in range(n):
                if morta[i] is None:
                    continue
                if morta[i]:
                    if cur is not None and folga <= tolerancia:
                        cur["cells"].append(i)
                    else:
                        if cur is not None:
                            trechos.append(cur)
                        cur = {"cells": [i]}
                    folga = 0
                elif cur is not None:
                    folga += passo
                    if folga > tolerancia:
                        trechos.append(cur)
                        cur, folga = None, 0
            if cur is not None:
                trechos.append(cur)
            trechos = [t for t in trechos if len(t["cells"]) * passo >= min_trecho]
            if not trechos:
                continue
            mins = sum(len(t["cells"]) for t in trechos) * passo
            spans = []
            for t in trechos:
                ult = t["cells"][-1]
                volta = next((i for i in range(ult + 1, n) if morta[i] is False), None)
                spans.append([_hhmm(ini + t["cells"][0] * passo), _hhmm(ini + volta * passo) if volta is not None else None])
            cells = [i for t in trechos for i in t["cells"]]
            out.append({"inversor": inv, "string": sid, "saiu": spans[0][0], "voltou": spans[-1][1],
                        "min_morta": mins, "trechos": spans,
                        "criterio": {"zerada": sum(1 for i in cells if crit[i] == "zerada") * passo,
                                     "abaixo_das_vizinhas": sum(1 for i in cells if crit[i] == "abaixo_das_vizinhas") * passo},
                        "fim_producao": _hhmm(ini + ult_prod * passo)})
    return out
