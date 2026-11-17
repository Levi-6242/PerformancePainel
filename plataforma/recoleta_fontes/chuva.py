# -*- coding: utf-8 -*-
"""Recoleta da CHUVA (meteo da API PV, conta principal) para a coluna Chuva do BD_Thopen.

É a mesma consulta meteo da ETM na fonte "apipv" (com chuva=True lá, a chuva sai junto, sem gastar outra consulta); esta
fonte existe para quem quer só a chuva. Regra do coletor (`_chuva_hoje.analisa`): max - min do acumulado chuTotal; sensor
com viés = LARANJA no BD; sem leitura é nulo, não 0 (Levi, 13/11/2026: a retroativa "pega o que tá nulo e recoleta").
"""
from recoleta_fontes import apipv

FONTE = "chuva"
PAGA = True
MAX_PLANTAS = apipv.MAX_PLANTAS
TETO = apipv.TETO                 # o mesmo teto da apipv: comum.CONTA_DE junta as duas no mesmo contador

contexto = apipv.contexto
plantas = apipv.plantas
permite = apipv.permite


def custo(ids, dias, geracao, etm, chuva):
    return len(ids) * len(dias)


def buscar(ctx, ids, dias, geracao, etm, chuva):
    return apipv.buscar(ctx, ids, dias, False, False, True)
