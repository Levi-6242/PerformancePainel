# -*- coding: utf-8 -*-
"""Quando o espelho das planilhas se refaz — e por que os tickets são exceção.

Levi, 08/09: "atualize os dados do PG de Tickets trackers e strings". O banco estava em dia; o
ESPELHO da plataforma é que estava parado no dia 30/08, nove dias atrás, e a tela servia isso sem
avisar.

A causa, medida contra a API real: **gravar uma LINHA não mexe no `updated_at` do workbook** — só
operação de workbook (o `sync-xlsx` do coletor) mexe. O `sincronizar` usa o `updated_at` como
gatilho, então toda edição do OS Creator passava invisível. E desde o corte do pipeline (06/09) o
app é a ÚNICA origem das abas Trackers e Strings indisp, ou seja, a fonte que mais muda é
justamente a que o gatilho não enxerga.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "plataforma"))
import bd_api  # noqa: E402


@pytest.fixture
def espelho(monkeypatch, tmp_path):
    """Isola o diretório e a marca; `gerar_xlsx` vira um contador."""
    feitos = []
    monkeypatch.setattr(bd_api, "_BASES_DIR", str(tmp_path))
    monkeypatch.setattr(bd_api, "_MARCA", str(tmp_path / "_bd_api_sync.json"))

    def gerar(chave, destino):
        feitos.append(chave)
        open(destino, "w").close()
        return {"abas": 1, "linhas": 1, "segundos": 0.1}
    monkeypatch.setattr(bd_api, "gerar_xlsx", gerar)
    monkeypatch.setattr(bd_api, "workbooks", lambda: [
        {"key": k, "updated_at": "2026-08-30T01:42:36-03:00"} for k in bd_api.ESPELHO])
    return feitos


def test_primeira_rodada_gera_todos(espelho):
    bd_api.sincronizar()
    assert sorted(espelho) == sorted(bd_api.ESPELHO)


def test_sem_mudanca_o_normal_nao_refaz_mas_os_tickets_sim(espelho):
    """O ponto do conserto: com o MESMO `updated_at`, os tickets se refazem assim mesmo, porque
    o carimbo não acompanha as edições linha a linha do app."""
    bd_api.sincronizar()
    espelho.clear()
    r = bd_api.sincronizar()
    assert espelho == ["tickets_performance"], espelho
    assert r["bd_performance"] == "sem mudança"
    assert r["bd_thopen"] == "sem mudança"
    assert isinstance(r["tickets_performance"], dict), "os tickets não foram refeitos"


def test_os_tickets_estao_na_lista_de_sempre_refazer():
    """Se alguém tirar daqui, o espelho volta a envelhecer em silêncio — que é o defeito."""
    assert "tickets_performance" in bd_api.SEMPRE_REFAZ
    assert bd_api.SEMPRE_REFAZ <= set(bd_api.ESPELHO), "chave que não é espelho não faz sentido"


def test_updated_at_novo_refaz_o_que_mudou(espelho, monkeypatch):
    bd_api.sincronizar()
    espelho.clear()
    monkeypatch.setattr(bd_api, "workbooks", lambda: [
        {"key": k, "updated_at": ("2026-09-08T11:00:00-03:00" if k == "bd_thopen"
                                  else "2026-08-30T01:42:36-03:00")} for k in bd_api.ESPELHO])
    bd_api.sincronizar()
    assert sorted(espelho) == ["bd_thopen", "tickets_performance"]


def test_falha_num_workbook_nao_derruba_os_outros(espelho, monkeypatch):
    def gerar(chave, destino):
        if chave == "bd_thopen":
            raise RuntimeError("PermissionError: arquivo aberto no Excel")
        espelho.append(chave)
        open(destino, "w").close()
        return {"abas": 1, "linhas": 1, "segundos": 0.1}
    monkeypatch.setattr(bd_api, "gerar_xlsx", gerar)
    r = bd_api.sincronizar()
    assert "falhou" in r["bd_thopen"]
    assert "bd_performance" in espelho and "tickets_performance" in espelho
    # a marca do que falhou NÃO avança: a rodada seguinte tenta de novo
    assert "bd_thopen" not in bd_api._marca_ler()


def test_api_fora_do_ar_nao_apaga_marca_nem_espelho(espelho, monkeypatch):
    bd_api.sincronizar()
    antes = bd_api._marca_ler()
    monkeypatch.setattr(bd_api, "workbooks", lambda: (_ for _ in ()).throw(RuntimeError("sem rede")))
    r = bd_api.sincronizar()
    assert "erro" in r
    assert bd_api._marca_ler() == antes
