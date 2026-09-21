# -*- coding: utf-8 -*-
"""Réguas de qualidade de dado sobre o pvanalytics (17/09/2026).

Duas primeiras do estudo do dia, escolhidas por NÃO dependerem de coordenada — então valem para a
frota inteira desde o primeiro dia:

**Dado congelado** (`quality.gaps.stale_values_diff`). É a régua geral do caso achado em 16/09: o
combiner do INVERSOR02 da Tanabi 2 repetindo 13 zeros desde **28/05**, quase quatro meses, enquanto
o inversor gerava 92 kW. A guarda que ficou lá no `app.py` olha a IDADE DO CARIMBO; esta olha o
VALOR, e por isso pega o sensor que repete a mesma leitura com carimbo novo — que é a falha mais
traiçoeira, porque parece saudável.

**Clipping** (`features.clipping.geometric`). Patamar achatado na curva de potência. Não tínhamos
nada, e isso importa além da curiosidade: inversor no teto derruba o PR **sem ser defeito**, e hoje
a plataforma lê como perda. É insumo direto para a pergunta "por que esta usina está abaixo da meta".

**O ajuste de domínio que a biblioteca não faz.** À noite toda série é zero e, para qualquer
detector de valor repetido, TODA usina parece congelada todas as madrugadas. Aqui a regra é:
zero repetido só acusa dentro da janela solar (quem chama passa `mascara_dia`), enquanto valor
NÃO-zero repetido acusa a qualquer hora — um sensor travado em 5,2 A às 3h continua travado.

**Onde isto pode rodar:** no `worker.py`, nunca no caminho de uma requisição. É pandas, e o
CLAUDE.md do projeto é explícito sobre o GIL (um rebuild já degradou os outros usuários em 1000×).

Módulo PURO: sem rede, sem Flask, sem estado global. Teste: `tests/test_qualidade.py`.
"""
from __future__ import annotations

try:
    import pandas as pd
    from pvanalytics.features import clipping as _clipping
    from pvanalytics.quality import gaps as _gaps
    _PVA = True
except Exception:                      # pragma: no cover - ambiente sem a lib
    _PVA = False
    try:
        import pandas as pd
    except Exception:
        pd = None


# Janela padrão: 6 leituras iguais seguidas. Numa fonte de 15 min isso é 1h30 parado; numa de 2 min
# (combiner) é 12 min. Quem chama ajusta pela cadência da sua fonte.
JANELA_PADRAO = 6
RTOL_PADRAO = 1e-5

# PISO DO CLIPPING — medido, não chutado (17/09/2026). O `geometric` marca o topo da curva de sino
# como platô, porque perto do meio-dia a inclinação é naturalmente baixa. Medição em curvas
# sintéticas de 05h–19h:
#     sino liso SEM teto ........ 0,053   <- o artefato, e só aparece na curva PERFEITA
#     idem com ruído de 2% ou 5% . 0,000   <- com qualquer ruído real ele some
#     idem a 5 min ou tracking ... 0,000
#     teto leve .................. 0,193
#     teto médio ................. 0,368
#     teto forte ................. 0,544
#     teto severo ................ 0,649
# Sem este piso, usina de céu limpo com dado suavizado acusaria clipping todo meio-dia. 0,10 fica
# com folga dos dois lados: quase o dobro do pior artefato e metade do clipping mais fraco.
FRACAO_MINIMA = 0.10


def _vazio_congelado(indisponivel=False):
    return {"congelado": False, "desde": None, "ate": None, "n": 0, "valor": None,
            "horas": 0.0, "indisponivel": indisponivel}


def congelado(serie, janela: int = JANELA_PADRAO, rtol: float = RTOL_PADRAO, mascara_dia=None) -> dict:
    """A série está repetindo o mesmo valor? → dict com `congelado`, `desde`, `valor`, `n`, `horas`.

    `mascara_dia` é uma Series booleana alinhada ao índice dizendo onde há sol. Sem ela a régua é
    conservadora DO LADO DE ACUSAR (zero repetido conta), porque quem conhece o sol da usina é quem
    chama — o `sol.py` já sabe fazer isso por estado.

    `n` conta a sequência INTEIRA, não só a cauda que o pvanalytics marca com `mark='tail'`: para
    quem lê o alerta, "13 leituras iguais" é a informação, não "12 depois da primeira".
    """
    if not _PVA:
        return _vazio_congelado(indisponivel=True)
    if serie is None or len(serie) < max(2, janela):
        return _vazio_congelado()
    s = pd.Series(serie).dropna()
    if len(s) < janela:
        return _vazio_congelado()
    try:
        marca = _gaps.stale_values_diff(s, window=janela, rtol=rtol, mark="tail")
    except Exception:
        return _vazio_congelado()
    if not bool(marca.any()):
        return _vazio_congelado()

    # O dia tem MAIS DE UMA sequência constante — a madrugada em zero e, se houver, o platô de
    # clipping. Agrupar os marcados em blocos CONTÍGUOS é o que impede o relato absurdo que o campo
    # pegou em 17/09 (Sorocaba: "250 kW travado desde 23:58 por 9,8 h", que era o início da
    # madrugada com o valor do meio-dia, cobrindo a série inteira). Reporta a sequência MAIS LONGA.
    idx = list(s.index)
    marcados = [i for i, m in enumerate(marca.tolist()) if m]
    blocos, atual = [], [marcados[0]]
    for i in marcados[1:]:
        if i == atual[-1] + 1:
            atual.append(i)
        else:
            blocos.append(atual); atual = [i]
    blocos.append(atual)

    # o início real é o ponto ANTERIOR ao primeiro marcado (o `mark='tail'` pula o valor original
    # que travou); sem recuar, o "desde" mente em uma leitura.
    def _estende(b):
        ini = b[0]
        while ini > 0 and _proximo(s.iloc[ini - 1], s.iloc[ini], rtol):
            ini -= 1
        return ini, b[-1]

    ini_i, fim_i = max((_estende(b) for b in blocos), key=lambda t: t[1] - t[0])

    # zero repetido só vale dentro da janela solar (senão toda madrugada vira alarme)
    valor = float(s.iloc[fim_i])
    if valor == 0.0 and mascara_dia is not None:
        try:
            m = pd.Series(mascara_dia).reindex(s.index).fillna(False)
            if not bool(m.iloc[ini_i:fim_i + 1].any()):
                return _vazio_congelado()
        except Exception:
            pass

    try:
        horas = (idx[fim_i] - idx[ini_i]).total_seconds() / 3600.0
    except Exception:
        horas = 0.0
    return {"congelado": True, "desde": idx[ini_i], "ate": idx[fim_i],
            "n": fim_i - ini_i + 1, "valor": valor, "horas": round(horas, 2),
            "indisponivel": False}


def _proximo(a, b, rtol):
    try:
        a, b = float(a), float(b)
    except Exception:
        return False
    return abs(a - b) <= max(abs(b) * rtol, 1e-8)


def clipping_dia(pac, tracking: bool = False, piso: float = FRACAO_MINIMA) -> dict:
    """Quanto do dia o inversor passou no teto? → `clipping` (bool), `fracao`, `inicio`, `fim`, `teto`.

    `fracao` é sobre os pontos COM GERAÇÃO, não sobre as 24 h — senão a madrugada dilui tudo e um
    clipping de 3 h vira "12% do dia", que não diz nada a quem lê.

    `clipping` só fica True acima do `piso` (ver FRACAO_MINIMA): o detector marca o topo da curva de
    sino mesmo sem teto nenhum, e sem o piso toda usina de céu limpo acusaria clipping ao meio-dia.
    A `fracao` bruta continua no retorno para quem quiser inspecionar o caso de fronteira.
    """
    vazio = {"clipping": False, "fracao": 0.0, "inicio": None, "fim": None, "teto": None,
             "pontos": 0, "indisponivel": not _PVA}
    if not _PVA or pac is None or len(pac) < 4:
        return vazio
    s = pd.Series(pac).dropna()
    if len(s) < 4:
        return vazio
    try:
        marca = _clipping.geometric(ac_power=s, tracking=tracking)
    except Exception:
        return vazio
    n = int(marca.sum())
    if not n:
        return vazio
    gerando = int((s > 0).sum()) or len(s)
    frac = round(n / gerando, 3)
    if frac < piso:                       # dentro do ruído do detector — não é teto, é a curva
        return dict(vazio, fracao=frac, pontos=n)
    janela = s.index[marca]
    return {"clipping": True, "fracao": frac, "inicio": janela.min(), "fim": janela.max(),
            "teto": round(float(s[marca].max()), 2), "pontos": n, "indisponivel": False}
