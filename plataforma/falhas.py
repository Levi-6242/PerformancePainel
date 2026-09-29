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
# String VIVA (para contar contra o cadastro): gerando pelo menos metade das vizinhas, em 2+ células com o inversor a
# 30% do pico. Mais estrito que o "não morta" de propósito: string morta que lê 0,3 A de ruído passa dos 10% das
# vizinhas na borda do dia, e contá-la como viva inflaria a conta que decide o que é entrada vazia.
FRAC_PICO_VIVA = 0.30
FRAC_VIZINHAS_VIVA = 0.50
CELULAS_VIVA = 2
# Sombra não é falha (29/09/2026, Levi: "alarme falsos nessas strings ... o Fusion mostra essas strings funcionando
# normalmente"). MAB100 Inversor 4.2 ST07 (02/09) e 5.1 ST07 (12/09), e MTS200 2.15 ST04 (19/09): com o inversor a
# 95-100% do pico, a string sai de 50% da mediana das vizinhas e desce em RAMPA — uns 4 pontos a cada 10 min, sem
# voltar e sem zerar — até ficar abaixo de 10% (0,64/0,44 A com as vizinhas a 7,5 A): sombra crescendo. String que
# abre (fusível, conector, MPPT) cai num degrau, de uma leitura para a outra. O trecho morto que ENTRA por uma rampa
# (da última leitura a >= 50% das vizinhas até o começo dele) ou SAI por uma (do fim dele até a 1ª leitura de novo a
# >= 50%) de QUEDA_GRADUAL_MIN ou mais é sombra: vai para `sombras`, não para `mortas`. Rampa é célula a célula: o
# inversor forte (>= 30% do pico — sombra precisa de sol direto) e a razão para as vizinhas andando num sentido só,
# com RAMPA_FOLGA de ruído. Medir só o relógio desde a última leitura boa chamava de sombra o que era falha: buraco
# de dado no meio da "queda" (MTS100 3.7 ST11-13 em 22/09 e SMP100 6.1 em 18/09 — amanheceram mortas) e dia no
# patamar de 20% do pico (CPP100 4.1, 14/09) não têm sol forte; a string que pisca entre 0 e 0,4 A (SMP100 3.1 ST03)
# não anda num sentido só. Morta desde a partida do inversor que volta em degrau (ou não volta) continua falha.
QUEDA_GRADUAL_MIN = 40
RAMPA_FOLGA = 0.05


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


def _rampa(razao, forte, de, ate, desce):
    """As células entre `de` e `ate` (exclusive) desenham a rampa de uma sombra? Em todas, o inversor forte e a razão
    para as vizinhas andando num sentido só — caindo (desce) ou subindo, com RAMPA_FOLGA de ruído; a string que zera
    no meio e volta quebra o sentido. Janela vazia (degrau) passa: quem decide aí é a duração."""
    ant = None
    for i in range(de + 1, ate):
        if not forte[i] or razao[i] is None:
            return False
        if ant is not None and (razao[i] > ant + RAMPA_FOLGA if desce else razao[i] < ant - RAMPA_FOLGA):
            return False
        ant = razao[i]
    return True


def strings_sem_corrente(curvas_inv, **kw):
    """Strings sem corrente do dia pela régua de 24/09 — só a lista (ver avaliar_dia)."""
    return avaliar_dia(curvas_inv, **kw)["mortas"]


def avaliar_dia(curvas_inv, *, zero, piso_inv, frac_vizinhas=FRAC_VIZINHAS, janela=JANELA, passo=PASSO,
                min_trecho=MIN_TRECHO, tolerancia=TOLERANCIA, frac_pico=FRAC_PICO):
    """Régua do dia: as strings sem corrente e quantas estavam vivas em cada inversor.

    curvas_inv = {inversor: {string: [(ts|hhmm, valor)]}} — corrente (A) ou potência (W); `zero` e `piso_inv`
    vão na mesma unidade. Uma célula conta como morta só com o inversor GERANDO (mediana das strings vivas >=
    piso e >= frac_pico do pico do dia, o que corta o sol baixo do amanhecer e do fim da tarde) e se a string lê
    <= zero, não lê nada, ou lê menos que frac_vizinhas da mediana das OUTRAS strings vivas do inversor. Trechos
    mortos se juntam através de leitura boa curta (tolerancia); só entra o trecho com min_trecho de morte seguida.

    → {"mortas": [{inversor, string, saiu, voltou, min_morta, trechos, criterio, ini_producao, fim_producao,
    sempre_zero}], "vivas": {inversor: n}, "sombras": [{inversor, string, saiu, voltou, min, entrada_min,
    saida_min}]} — sombra = trecho que entrou ou saiu por uma rampa de QUEDA_GRADUAL_MIN ou mais, fora das mortas
    (entrada_min/saida_min None = não houve rampa daquele lado). `voltou` None = ficou morta até o inversor parar de
    gerar (o episódio continua no dia seguinte se ela amanhecer morta). `sempre_zero` = leu zero (ou nada) em toda a
    produção do dia: a assinatura da entrada sem string. `vivas` só tem o inversor que gerou min_trecho no dia — com
    menos, a conta não prova nada."""
    ini = janela[0]
    n = (janela[1] - janela[0]) // passo + 1
    out, vivas_inv, sombras = [], {}, []
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
        pri_prod = min(i for i in range(n) if prod[i])
        ult_prod = max(i for i in range(n) if prod[i])
        forte = [m is not None and prod[i] and m >= pico * FRAC_PICO_VIVA for i, m in enumerate(meds)]
        n_vivas = 0
        for sid, g in grades.items():
            morta, crit, razao = [None] * n, [None] * n, [None] * n
            celulas_vivas = 0
            for i in range(n):
                if not prod[i]:
                    continue
                v = g[i]
                if v is None or v <= zero:
                    morta[i], crit[i], razao[i] = True, "zerada", 0.0
                    continue
                viz = _mediana([grades[o][i] for o in grades if o != sid and grades[o][i] is not None and grades[o][i] > zero])
                razao[i] = (v / viz) if viz else None
                if viz is not None and v < frac_vizinhas * viz:
                    morta[i], crit[i] = True, "abaixo_das_vizinhas"
                else:
                    morta[i] = False
                if forte[i] and viz is not None and v >= FRAC_VIZINHAS_VIVA * viz:
                    celulas_vivas += 1
            if celulas_vivas >= CELULAS_VIVA:
                n_vivas += 1
            sempre_zero = all(crit[i] == "zerada" for i in range(n) if prod[i])
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
            reais = []
            for t in trechos:
                a, b = t["cells"][0], t["cells"][-1]
                # a leitura boa de referência vale com qualquer luz (a string acompanhar as vizinhas no nublado prova que
                # ela está inteira); o sol forte é exigido na janela entre ela e o trecho, que é onde a sombra se desenha
                ok_antes = [i for i in range(a) if prod[i] and razao[i] is not None and razao[i] >= FRAC_VIZINHAS_VIVA]
                ok_depois = [i for i in range(b + 1, n) if prod[i] and razao[i] is not None and razao[i] >= FRAC_VIZINHAS_VIVA]
                entrada = ((a - ok_antes[-1]) * passo if ok_antes and _rampa(razao, forte, ok_antes[-1], a, True)
                           else None)
                saida = ((ok_depois[0] - b) * passo if ok_depois and _rampa(razao, forte, b, ok_depois[0], False)
                         else None)
                if (entrada or 0) >= QUEDA_GRADUAL_MIN or (saida or 0) >= QUEDA_GRADUAL_MIN:
                    sombras.append({"inversor": inv, "string": sid, "saiu": _hhmm(ini + a * passo),
                                    "voltou": _hhmm(ini + ok_depois[0] * passo) if ok_depois else None,
                                    "min": len(t["cells"]) * passo, "entrada_min": entrada, "saida_min": saida})
                else:
                    reais.append(t)
            trechos = reais
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
                        "ini_producao": _hhmm(ini + pri_prod * passo), "fim_producao": _hhmm(ini + ult_prod * passo),
                        "sempre_zero": sempre_zero})
        if sum(prod) * passo >= min_trecho:
            vivas_inv[inv] = n_vivas
    return {"mortas": out, "vivas": vivas_inv, "sombras": sombras}
