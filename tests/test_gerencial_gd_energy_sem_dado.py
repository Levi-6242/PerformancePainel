# -*- coding: utf-8 -*-
"""GD Energy sumia do /gerencial (Levi, 13/09/2026: "tem geração, só não tem ETM").

Causa medida: as abas Sol do Norte 1, Sol do Norte 2 e Guajirú 1 da BD_Performance estão SEM geração em setembro (junho,
julho e agosto cheios), então `_bdperf_prod_build` não as emite (`tot > 0`), elas entram só pelo cadastro com `prod=None`
e a tela filtrava a lista por `atingimento != null` — a usina desaparecia em silêncio, em vez de aparecer como "sem dado".
Lacuna de dado tem que ficar VISÍVEL: quem tem meta no mês entra na lista, com o atingimento em "—".
"""
import pathlib

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
GER = (RAIZ / "plataforma" / "templates" / "gerencial.html").read_text(encoding="utf-8")


def test_usina_com_meta_e_sem_geracao_entra_na_lista_como_sem_dado():
    assert "const _temGer = u => u.atingimento != null || u.p50 != null;" in GER, \
        "a visão Geração × Meta P50 voltou a esconder a usina que tem meta mas ficou sem geração no mês"
    assert "sem dado" in GER.split("function renderTodas")[1].split("function renderQualidade")[0], \
        "a linha sem geração precisa dizer 'sem dado' na coluna do atingimento"


def test_lista_ordena_com_os_sem_dado_por_ultimo():
    bloco = GER.split("function renderTodas")[1].split("function renderQualidade")[0]
    assert "(b.atingimento ?? -1) - (a.atingimento ?? -1)" in bloco, "ordenar por atingimento com null vira NaN e embaralha a lista"
