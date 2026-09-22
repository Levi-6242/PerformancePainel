# gemeo/gemeo/modelar/qualidade.py
"""Checagens de qualidade do dado da IEC 61724-1:2021 §12.2.1 (21/09/2026).

A norma lista dez metodos recomendados para identificar dado invalido. O comparativo de 21/09
mostrou que ja tinhamos quatro — limites fisicos no gate POA x GHI, valor travado
(`sensor_congelado`), dado faltante (cobertura do gate) e relatorios de disponibilidade — e que
tres dependiam so de software:

  1. limites fisicos de maximo e minimo, explicitos por medida;
  2. limites de taxa maxima de variacao;
  3. carimbos duplicados e lacunas.

Ficam de fora dois, e por motivo, nao por esquecimento: "comparar medicoes de sensores multiplos"
e impossivel com UM piranometro por usina (a norma pede DOIS na Classe A, e e o buraco de hardware
que o comparativo apontou), e "codigos de erro do sensor" exigiria que a fonte os exponha.

O CALIBRE DOS LIMIARES VEIO DO DADO REAL. Em 17/09 medi a Sete Lagoas num dia de nuvem quebrada:
salto MEDIANO de 68,8 W/m2 por minuto, pico de 836, e irradiancia chegando a 1.238 W/m2 — acima do
ceu claro, por realce de borda de nuvem. Tudo legitimo. Um limiar tirado da estatistica do dia
transformaria meteorologia em alarme; por isso o corte de irradiancia e o LIMITE FISICO DO SENSOR
(1.500 W/m2, a faixa que a Tabela 4 da norma exige), e a taxa maxima so vale onde a fisica
proibe mesmo — temperatura, que nao salta.
"""
from __future__ import annotations

# (minimo, maximo) fisicamente possiveis por medida. Irradiancia: a faixa do sensor pela Tabela 4.
# O negativo pequeno e tolerado de proposito — piranometro marca uns poucos W negativos a noite por
# offset termico, e a propria norma manda tratar isso no §12.1 em vez de chamar de defeito.
FAIXA = {
    "ghi": (-20.0, 1500.0),
    "poa": (-20.0, 1500.0),
    "temp_modulo": (-20.0, 110.0),
    "temp_ar": (-30.0, 60.0),
    "vento": (0.0, 90.0),
}

# Variacao maxima por MINUTO que a fisica admite. Irradiancia NAO entra: nuvem quebrada salta
# centenas de W/m2 por minuto e isso e real (medido). Temperatura entra: massa termica nao permite.
TAXA_MAX_POR_MIN = {
    "temp_modulo": 10.0,
    "temp_ar": 5.0,
}


def _vazio(extra: dict | None = None) -> dict:
    return {"n": 0, "exemplo": None, **(extra or {})}


def fora_da_faixa(serie, medida: str) -> dict:
    """Leituras fora do que o sensor consegue medir (§12.2.1, limites fisicos).

    Medida sem faixa definida devolve zero em vez de aplicar um limiar qualquer — inventar limite
    para grandeza que ninguem calibrou produziria alarme sem significado."""
    faixa = FAIXA.get(medida)
    if not faixa or not serie:
        return _vazio()
    lo, hi = faixa
    ruins = [(t, v) for t, v in serie if v is not None and (v < lo or v > hi)]
    return {"n": len(ruins), "exemplo": ruins[0] if ruins else None, "faixa": faixa}


def salto_impossivel(serie, medida: str) -> dict:
    """Variacao entre leituras consecutivas acima do que a fisica admite (§12.2.1, taxa maxima).

    So se aplica onde a grandeza tem inercia. Irradiancia de proposito nao tem limiar aqui: a
    Sete Lagoas foi de 1225 a 372 e de volta a 1202 em minutos, em 17/09, e era nuvem."""
    taxa = TAXA_MAX_POR_MIN.get(medida)
    if not taxa or len(serie or []) < 3:
        return _vazio()
    ruins = []
    for (t0, v0), (t1, v1) in zip(serie, serie[1:]):
        if v0 is None or v1 is None:
            continue
        dtmin = (t1 - t0).total_seconds() / 60.0
        if dtmin <= 0:
            continue
        d = abs(v1 - v0)
        if d / dtmin > taxa:
            ruins.append((t1, round(d, 2)))
    return {"n": len(ruins), "exemplo": ruins[0] if ruins else None, "taxa_max": taxa}


def carimbos(serie, passo_esperado_min: float) -> dict:
    """Carimbos duplicados e lacunas (§12.2.1, "gaps or duplicates in data").

    Lacuna = intervalo maior que o DOBRO do passo esperado; um passo perdido e ruido de ingestao,
    dois ja e buraco. Devolve tambem a maior lacuna em minutos, que e o que diz se foi um soluco
    ou a usina ter ficado muda."""
    if len(serie or []) < 2 or not passo_esperado_min:
        return {"duplicados": 0, "lacunas": 0, "maior_lacuna_min": 0}
    ts = [t for t, _ in serie]
    dup = len(ts) - len(set(ts))
    limite = passo_esperado_min * 2
    lac, maior = 0, 0.0
    for a, b in zip(ts, ts[1:]):
        d = (b - a).total_seconds() / 60.0
        if d > limite:
            lac += 1
            maior = max(maior, d - passo_esperado_min)
    return {"duplicados": dup, "lacunas": lac, "maior_lacuna_min": int(round(maior))}


def resumo(series_por_medida: dict, passo_esperado_min: float = 1.0) -> dict:
    """Junta as tres checagens num veredito por usina/dia, para a tela e para as acoes.

    `series_por_medida` = {medida: [(ts, valor)]}. Devolve o total por tipo de problema e a lista
    do que apareceu, para o texto poder dizer QUAL medida falhou — "dado suspeito" sem dizer onde
    nao faz ninguem agir."""
    fora, saltos, dup, lac = 0, 0, 0, 0
    detalhes = []
    for medida, serie in (series_por_medida or {}).items():
        f = fora_da_faixa(serie, medida)
        s = salto_impossivel(serie, medida)
        c = carimbos(serie, passo_esperado_min)
        fora += f["n"]; saltos += s["n"]; dup += c["duplicados"]; lac += c["lacunas"]
        if f["n"]:
            detalhes.append(f"{medida}: {f['n']} leitura(s) fora da faixa {f['faixa']}")
        if s["n"]:
            detalhes.append(f"{medida}: {s['n']} salto(s) acima de {s['taxa_max']}/min")
        if c["duplicados"]:
            detalhes.append(f"{medida}: {c['duplicados']} carimbo(s) duplicado(s)")
        if c["lacunas"]:
            detalhes.append(f"{medida}: {c['lacunas']} lacuna(s), maior de {c['maior_lacuna_min']} min")
    return {"fora_da_faixa": fora, "saltos": saltos, "duplicados": dup, "lacunas": lac,
            "total": fora + saltos + dup + lac, "detalhes": detalhes}
