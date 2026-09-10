# -*- coding: utf-8 -*-
"""O painel de ETM tem de achar a IPOA com a MESMA régua do motor de PR (varredura de 09/09/2026).

Achado: `_etm_problemas_build` exigia as palavras IPOA **e ETM** no cabeçalho da aba. Medido no espelho
real (plataforma/bases/BD_Performance.xlsx, 09/09/2026): das 63 abas, 51 têm "IPOA (kWh/m²) DEF", 41 têm
"IPOA (kWh/m²)" e só 10 têm alguma com "ETM" no título. Resultado: 11 usinas apareciam no painel com
"IPOA (ETM) sem leitura/zerada no mês inteiro — PR não calculável" enquanto a coluna DEF tinha os 8 dias
do mês, com pico perto de 9 kWh/m² (Tupi Paulista, Araputanga, Sete Lagoas, Ipixuna do Pará, União 1 e 2,
Demerval Lobão, Macaiba 1, Cedro 1 e 2, Tucano 1 e 2).

O motor de PR (`_g_build`) já usava a cadeia certa — DEF → ETM → qualquer IPOA — o que prova que a coluna
sem "ETM" é a norma da planilha, não a exceção.
"""
from datetime import datetime, timedelta

import openpyxl
import pytest

import app


def _planilha(tmp_path, titulo_ipoa, valores):
    """Uma aba com 3 dias FECHADOS do mês corrente e as colunas na ordem da planilha real."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Usina Teste"
    ws.append(["Usina", "Data", titulo_ipoa, "GHI (kWh/m²)"])
    hoje = datetime.now()
    for i, v in enumerate(valores, start=1):
        d = hoje - timedelta(days=len(valores) - i + 1)
        if d.month != hoje.month:                      # início de mês: não há dia fechado para testar
            pytest.skip("mês recém-virado — sem dias fechados suficientes na janela")
        ws.append(["Usina Teste", d, v, 5.0])
    p = tmp_path / "BD_Performance.xlsx"
    wb.save(p)
    return str(p)


def _roda(monkeypatch, caminho):
    monkeypatch.setattr(app, "_bd_readable", lambda: caminho)
    monkeypatch.setattr(app, "INFO_GERAL", {app._nrm("Usina Teste"): {"usina": "Usina Teste",
                                                                     "cliente": "Cliente X"}})
    monkeypatch.setattr(app, "_gerencial_payload", lambda *a, **k: {"usinas": []})
    itens = app._etm_problemas_build()["itens"]
    return [p for it in itens for p in it["problemas"]]


def test_coluna_def_sem_a_palavra_etm_e_lida(tmp_path, monkeypatch):
    """O caso das 11 usinas: IPOA cheia na coluna DEF, e o painel dizia que não havia leitura."""
    probs = _roda(monkeypatch, _planilha(tmp_path, "IPOA (kWh/m²) DEF", [6.1, 6.4, 5.9]))
    assert not any("sem leitura" in p for p in probs), f"alarme falso de IPOA: {probs}"


def test_coluna_ipoa_pelada_tambem_e_lida(tmp_path, monkeypatch):
    probs = _roda(monkeypatch, _planilha(tmp_path, "IPOA (kWh/m²)", [6.1, 6.4, 5.9]))
    assert not any("sem leitura" in p for p in probs), f"alarme falso de IPOA: {probs}"


def test_ipoa_de_verdade_zerada_continua_acusando(tmp_path, monkeypatch):
    """O painel não pode ficar cego do outro lado: sensor morto segue sendo problema."""
    probs = _roda(monkeypatch, _planilha(tmp_path, "IPOA (kWh/m²) DEF", [0.0, 0.0, 0.0]))
    assert any("sem leitura" in p for p in probs), f"sensor morto deixou de acusar: {probs}"


def test_sensor_travado_continua_sendo_pego(tmp_path, monkeypatch):
    """Valor constante por 3 dias seguidos é a outra régua do painel — não pode se perder na troca."""
    probs = _roda(monkeypatch, _planilha(tmp_path, "IPOA (kWh/m²) DEF", [6.2, 6.2, 6.2]))
    assert any("constante" in p for p in probs), f"sensor travado deixou de acusar: {probs}"
