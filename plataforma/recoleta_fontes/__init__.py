# -*- coding: utf-8 -*-
"""Recoleta por fonte para a Coletas do Nexus (Levi, 17/11/2026: "quero formas de coletar os dados novamente pelas
nossas fontes de dados e gerar uma planilha para colar nos BDs"; "Sim, todas"; acesso só do setor Performance, que o
Nexus confere). Uma rota por fonte, o mesmo contrato para todas (comum.py); nada é gravado em BD nenhum.

Cada módulo de fonte expõe:
    FONTE, PAGA, MAX_PLANTAS
    contexto(app)  -> o que ele precisa do app.py (clientes e credenciais que a plataforma já tem), sem import circular
    plantas(ctx)   -> [{"id", "usina" (aba do BD), "destino": "BD_Thopen"|"BD_Performance"}]
    custo(ids, dias, geracao, etm, chuva) -> consultas pagas que a busca gasta (0 nas fontes sem cota)
    buscar(ctx, ids, dias, geracao, etm, chuva) -> {"geracao": [...], "escalares": [...], "avisos": [...]}
"""
import importlib

FONTES = ("pg", "scada", "apipv", "solaredge", "oem", "sunop", "chuva")


def modulo(fonte):
    if fonte not in FONTES:
        return None
    try:
        return importlib.import_module("recoleta_fontes." + fonte)
    except ModuleNotFoundError:
        return None
