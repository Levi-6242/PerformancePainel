# -*- coding: utf-8 -*-
"""Entrada que o inversor não manda não é string (Levi, 01/10/2026, com print da aba de falhas: "pra mim fazenda limão
não aparece essas strings 29 a 32" — o drill do Inversor 1.3 mostra 28 entradas, Ipv1 a Ipv28).

Em 30/09 o INVERSOR06 da Fazenda Limão mandou 1.437 registros com Ipv1 a Ipv28 e UM, às 09:00, com 92 campos — Ipv29 a
Ipv32 = 0, Upv29, Pac1 a Pac3, Ri, TempDis. A régua lê a célula sem leitura como sem corrente, então esse registro solto
fazia a entrada fantasma "morrer" o dia inteiro. Aqui, a curva (a da API PV, que alimenta as ocorrências, a régua da aba
e o drill) e o registro da régua; a montagem do mês está em test_falhas_job.py.
"""
import json
from pathlib import Path

import pytest

import app

FIX = Path(__file__).parent / "fixtures" / "falhas_fantasma" / "apipv__fazenda-limao__2026-09-30__inversor06.json"
PID = 18746249
FANTASMAS = {"Ipv29", "Ipv30", "Ipv31", "Ipv32"}


@pytest.fixture
def regs(monkeypatch):
    monkeypatch.setattr(app, "_pv_dev_names", lambda pid, tok: {357484: "INVERSOR06", "357484": "INVERSOR06"})
    monkeypatch.setattr(app, "_trancadas", set())
    monkeypatch.setattr(app, "_TRANC_INV", set())
    return json.loads(FIX.read_text(encoding="utf-8"))["registros"]


def test_o_dado_real_tem_o_registro_solto(regs):
    soltos = [r["tsleitura_new"] for r in regs if "Ipv29" in r["conteudojson"]]
    assert soltos == ["2026-09-30 09:00:00"] and len(regs) == 90


def test_curva_da_api_pv_deixa_fora_a_entrada_que_so_veio_no_registro_solto(regs):
    curvas = app._pv_curvas_strings_de(regs, PID, None, "tok")
    assert sorted(curvas["INVERSOR06"], key=lambda k: int(k[3:])) == [f"Ipv{i}" for i in range(1, 29)]
    ent = app._falhas_entrada("Fazenda Limão", curvas)
    assert not {m["string"] for m in ent["mortas"]} & FANTASMAS
    assert ent["vivas"] == {"INVERSOR06": 18}             # Ipv1 a Ipv18 gerando; Ipv19 a Ipv28 em 0 A (trancadas lá)


def test_curva_diz_quantas_entradas_o_inversor_manda_contando_a_trancada(regs, monkeypatch):
    # a trava tira a string da curva, não do inversor: sem contar a trancada, a Ipv19 a Ipv28 da Fazenda Limão (dez
    # trancadas no drill) baixariam o número para 18 e uma string real destrancada depois pareceria inexistente
    monkeypatch.setattr(app, "_trancadas", {f"{PID}|357484|Ipv{i}" for i in range(19, 29)})
    entradas = {}
    curvas = app._pv_curvas_strings_de(regs, PID, None, "tok", entradas=entradas)
    assert "Ipv28" not in curvas["INVERSOR06"] and "Ipv18" in curvas["INVERSOR06"]
    assert entradas == {"INVERSOR06": 28}


def test_entrada_presente_em_boa_parte_dos_registros_fica():
    # inversor que alterna dois formatos de pacote (metade com Ipv1-2, metade com Ipv3-4): todas as entradas são reais
    a = {"idefinversor": 1, "conteudojson": {"Ipv1": 8.0, "Ipv2": 8.1}}
    b = {"idefinversor": 1, "conteudojson": {"Ipv3": 7.9, "Ipv4": 8.2}}
    recs = [{**(a if i % 2 else b), "tsleitura_new": f"2026-10-01 {10 + i // 60:02d}:{i % 60:02d}:00"} for i in range(40)]
    entradas = {}
    curvas = app._pv_curvas_strings_de(recs, 1, None, "tok", entradas=entradas)
    assert sorted(curvas["INV-1"]) == ["Ipv1", "Ipv2", "Ipv3", "Ipv4"] and entradas == {"INV-1": 4}


def test_string_que_vem_como_null_quase_o_dia_todo_continua_na_curva():
    # a presença é do campo: a Ipv4 está em todo registro (null em 36 de 40, 0 A em 4) e segue com as leituras que tem,
    # como antes da regra — contando só o valor numérico ela cairia abaixo dos 25% e uma string morta sumiria
    recs = [{"idefinversor": 1, "tsleitura_new": f"2026-10-01 {10 + i // 60:02d}:{i % 60:02d}:00",
             "conteudojson": {"Ipv1": 8.0, "Ipv2": 8.1, "Ipv3": 7.9, "Ipv4": 0.0 if i % 10 == 0 else None}} for i in range(40)]
    curvas = app._pv_curvas_strings_de(recs, 1, None, "tok")
    assert len(curvas["INV-1"]["Ipv4"]) == 4 and len(curvas["INV-1"]["Ipv1"]) == 40


def test_registro_da_regua_guarda_as_entradas_so_do_inversor_que_gerou(monkeypatch):
    # de madrugada o inversor tem meia dúzia de registros e um solto pesaria demais: só vale quem gerou 2 h no dia
    monkeypatch.setattr(app, "_FALHAS_MORTAS", {})
    serie = [(f"{h:02d}:{m:02d}", 8.0) for h in range(7, 17) for m in (0, 10, 20, 30, 40, 50)]
    curvas = {"Inversor 3.3": {f"Ipv{i}": serie for i in range(1, 5)}}
    app._falhas_registra("pv", "2026-10-01", "1", "Inhapi", curvas, entradas={"Inversor 3.3": 4, "Inversor 9.9": 28})
    assert app._FALHAS_MORTAS[("pv", "2026-10-01")]["1"]["entradas"] == {"Inversor 3.3": 4}


def test_aba_lista_a_entrada_que_o_inversor_nao_manda(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "", raising=False)
    app.app.config["TESTING"] = True
    with app.app.test_client() as c:
        html = c.get("/painel/falhas").get_data(as_text=True)
    assert "D.strings.entradas_inexistentes" in html and "entrada que o inversor não manda: fora" in html
