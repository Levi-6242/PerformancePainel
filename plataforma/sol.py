# -*- coding: utf-8 -*-
"""Sensor de sol por ESTADO — elevação solar pelo centroide da UF (capital), sem dependência externa.

Por que existe: em 10/09/2026 às 17:52 o /api/macro mostrava 89 de 102 usinas "críticas" ("N inversores
parados · N strings abaixo") e o sino despejou 300 eventos "string zerou" numa leitura só (17:43). Era o
pôr do sol (setembro, ~17:50 em SP) caindo dentro de janelas FIXAS — "dia" até 18h no macro, sino até 18:20.
Uma janela fixa erra para os dois lados ao longo do ano (junho anoitece ~17:30, dezembro ~18:55) e entre
regiões (Mato Grosso está 10° a oeste de SP: 40 min a mais de sol em hora de Brasília).

O cadastro (Info Geral) TEM LATITUDE/LONGITUDE, mas só em 117 das 157 usinas (medido 17/09/2026) —
e quando este módulo nasceu ninguém as lia. A capital da UF como proxy vale para a frota inteira e erra o
horário solar em até ~15 min dentro do estado — irrelevante para a pergunta "o sol já está baixo?", que
usa um limite de elevação (SOL_BAIXO_GRAUS), não o instante exato do pôr do sol.

Algoritmo: aproximação da NOAA (equação do tempo + declinação por série de Fourier), erro < 0,5° — o
mesmo que a planilha NOAA_Solar_Calculations usa. Horários de entrada são hora de Brasília (UTC-3, sem
horário de verão), a hora local do servidor e das leituras.
"""
import math
import unicodedata
from datetime import datetime, timedelta

SOL_BAIXO_GRAUS = 8.0      # abaixo disto o inversor está entrando/saindo de operação — não se julga produção
FUSO_BRASILIA_H = -3       # hora do servidor e das leituras; a conta solar é feita em UTC

# capital de cada UF (lat, lon) — proxy do centroide
UF = {
    "AC": (-9.97, -67.81), "AL": (-9.67, -35.74), "AP": (0.03, -51.07), "AM": (-3.12, -60.02),
    "BA": (-12.97, -38.51), "CE": (-3.72, -38.54), "DF": (-15.79, -47.88), "ES": (-20.32, -40.34),
    "GO": (-16.68, -49.25), "MA": (-2.53, -44.30), "MT": (-15.60, -56.10), "MS": (-20.44, -54.65),
    "MG": (-19.92, -43.94), "PA": (-1.46, -48.50), "PB": (-7.12, -34.86), "PR": (-25.43, -49.27),
    "PE": (-8.05, -34.88), "PI": (-5.09, -42.80), "RJ": (-22.91, -43.17), "RN": (-5.79, -35.21),
    "RS": (-30.03, -51.23), "RO": (-8.76, -63.90), "RR": (2.82, -60.67), "SC": (-27.60, -48.55),
    "SP": (-23.55, -46.63), "SE": (-10.91, -37.07), "TO": (-10.25, -48.32),
}
_NOMES = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA", "ceara": "CE",
    "distritofederal": "DF", "espiritosanto": "ES", "goias": "GO", "maranhao": "MA", "matogrosso": "MT",
    "matogrossodosul": "MS", "minasgerais": "MG", "para": "PA", "paraiba": "PB", "parana": "PR",
    "pernambuco": "PE", "piaui": "PI", "riodejaneiro": "RJ", "riograndedonorte": "RN",
    "riograndedosul": "RS", "rondonia": "RO", "roraima": "RR", "santacatarina": "SC", "saopaulo": "SP",
    "sergipe": "SE", "tocantins": "TO",
}


def _nrm(s) -> str:
    """'São Paulo' / 'Sao Paulo' / ' SP ' → chave sem acento, sem espaço, minúscula."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return "".join(s.split()).lower()


def coordenadas(estado):
    """(lat, lon) da UF a partir do nome ou da sigla; None se não reconhecer."""
    k = _nrm(estado)
    if not k:
        return None
    if k.upper() in UF:
        return UF[k.upper()]
    uf = _NOMES.get(k)
    return UF.get(uf) if uf else None


def elevacao_solar(lat: float, lon: float, quando_utc: datetime) -> float:
    """Elevação do sol em graus (negativa = abaixo do horizonte). NOAA simplificada."""
    doy = quando_utc.timetuple().tm_yday
    h = quando_utc.hour + quando_utc.minute / 60.0 + quando_utc.second / 3600.0
    g = 2 * math.pi / 365.0 * (doy - 1 + (h - 12) / 24.0)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    tst = h * 60.0 + eqtime + 4.0 * lon                      # tempo solar verdadeiro, em minutos (UTC)
    ha = math.radians(tst / 4.0 - 180.0)                     # ângulo horário
    latr = math.radians(lat)
    cosz = math.sin(latr) * math.sin(decl) + math.cos(latr) * math.cos(decl) * math.cos(ha)
    cosz = max(-1.0, min(1.0, cosz))
    return 90.0 - math.degrees(math.acos(cosz))


def elevacao_estado(estado, agora_local: datetime, fuso_h: int = FUSO_BRASILIA_H):
    """Elevação do sol (graus, 1 casa) na capital do estado, na hora LOCAL dada. None se o estado não é conhecido."""
    c = coordenadas(estado)
    if not c:
        return None
    utc = agora_local - timedelta(hours=fuso_h)
    return round(elevacao_solar(c[0], c[1], utc), 1)


def sol_baixo(estado, agora_local: datetime, limite: float = SOL_BAIXO_GRAUS) -> bool:
    """True quando o sol está abaixo de `limite` graus no estado — anoitecer, amanhecer ou noite.
    Estado desconhecido → False: quem chama fica com a régua que já tinha (janela fixa)."""
    e = elevacao_estado(estado, agora_local)
    return e is not None and e < limite
