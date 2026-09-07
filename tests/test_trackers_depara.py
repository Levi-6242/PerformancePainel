# -*- coding: utf-8 -*-
"""De-para de trackers supervisório ↔ Fracttal (06/09/2026): a planilha vira dado da plataforma.

O que se prova, sobre uma planilha pequena montada aqui:
  1. o nome da usina é comparável nos dois lados: sem o código entre parênteses, sem acento, minúsculo;
  2. o número do tracker é a chave ('TRK1', 'Tracker 01', 'TRK_7' → 1, 1, 7);
  3. casamento exato, por substring única e por união de prefixo (a plataforma agrupa 'Altair' = Altair 1..5);
  4. as situações: casado / a confirmar (casou por ordem, bloco, limite) / sem par (a planilha explica por quê);
  5. o arquivo é relido quando muda (mtime), sem reiniciar.
"""
import os
import time

import openpyxl
import pytest

import app

HDR = ["Fonte", "UFV Supervisório", "UFV Fracttal", "Tracker Supervisório", "Tracker Fracttal", "Code Fracttal",
       "Cabine (Fracttal)", "Como casou", "Observação"]
LINHAS = [
    ["API PV", "Altair 1 (73)", "Thopen - Altair 1 - SP", "TRK1", "Tracker 01.100", "ALT100-ETKR1.101", "101", "direto", None],
    ["API PV", "Altair 1 (73)", "Thopen - Altair 1 - SP", "TRK2", "Tracker 02.100", "ALT100-ETKR2.101", "101", "direto", None],
    ["API PV", "Altair 1 (73)", "Thopen - Altair 1 - SP", "TRK3", None, None, None, None, "excedente do supervisorio - este tracker nao existe no Fracttal"],
    ["API PV", "Altair 2 (74)", "Thopen - Altair 1 - SP", "TRK1", "Tracker 01.200", "ALT100-ETKR1.201", "201", "por limite dos skids (CONFIRMAR)", None],
    ["API PV", "Caicó 1.1 (224)", "Thopen - Caicó - RN", "TRK7", "Tracker 07.100", "CAI100-ETKR7.101", "101", "direto", None],
    ["Banco de Dados", "(327) Santo Inácio XII", "Thopen - Santo Inácio 1 e 2 - SP", "Tracker 01", "Tracker 1.1.101", "STI100-ETKR1.101", "101", "por ordem da sub-usina (CONFIRMAR)", None],
    ["Athon (SunOp)", "CPP100", "Athon - Capitão Poço 1 - PA", "TRK_5", "Tracker 05.101", "CPP100-ETKR5.101", "101", "direto", None],
    ["API PV", "Corrego Sapucaia 1 (113)", "Thopen - Córrego do Sapucaia 1 - ES", "TRK4", None, None, None, None, "cabine indefinida"],
    ["API PV", "Corrego Sapucaia 2 (114)", "Thopen - Córrego do Sapucaia 1 - ES", "TRK9", None, None, None, None, "cabine indefinida"],
    ["Banco de Dados", "(310) Salto Pirapora III", "Thopen - Salto de Pirapora - SP", "Tracker 06", "Tracker 1.6.100", "SPI100-ETKR6.100", "100", "direto", None],
]


def _planilha(caminho, linhas=LINHAS):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "De-Para Trackers"
    ws.append(HDR)
    for r in linhas:
        ws.append(r)
    wp = wb.create_sheet("Pendências")
    wp.append(["UFV Fracttal", "Sub-usinas no supervisório", "Trackers sem par", "Por que não casou", "O que resolve"])
    wp.append(["Thopen - Córrego do Sapucaia 1 - ES", "Corrego Sapucaia 1 (113), Corrego Sapucaia 2 (114)", 67, "contagens nao fecham", "dizer qual sub-usina e cada cabine"])
    wb.save(caminho)


@pytest.fixture
def depara(tmp_path, monkeypatch):
    arq = tmp_path / "trackers_depara.xlsx"
    _planilha(arq)
    monkeypatch.setattr(app, "_TRK_DEPARA_PATH", str(arq))
    monkeypatch.setattr(app, "_TRK_DEPARA_LOCAL", str(tmp_path / "nao-existe.local.xlsx"))
    app._trk_depara_carregar._c = None
    yield arq
    app._trk_depara_carregar._c = None


def test_nome_normalizado_iguala_planilha_e_plataforma():
    assert app._trk_depara_nrm("Altair 1 (73)") == "altair 1"
    assert app._trk_depara_nrm("(327) Santo Inácio XII") == "santo inacio 12"
    assert app._trk_depara_nrm("PE III") == "pe 3" == app._trk_depara_nrm("PEIII")      # romano separado ou colado
    assert app._trk_depara_nrm("Brodowski - Skid 2 (86)") == "brodowski skid 2"
    assert app._trk_depara_nrm("  CPP100 ") == "cpp100" and app._trk_depara_nrm(None) == ""
    # conectivos e algarismo romano (os dois casos reais de 06/09: Córrego do Sapucaia e Salto Pirapora III)
    assert app._trk_depara_nrm("Córrego do Sapucaia") == "corrego sapucaia" == app._trk_depara_nrm("Corrego Sapucaia")
    assert app._trk_depara_nrm("Salto Pirapora 3") == "salto pirapora 3" == app._trk_depara_nrm("(310) Salto Pirapora III")
    assert app._trk_depara_nrm("Santo Inácio XII") == "santo inacio 12" and app._trk_depara_nrm("Santo Inácio 1 e 2") == "santo inacio 1 2"


def test_carrega_indexa_e_classifica(depara):
    d = app._trk_depara_carregar()
    assert d["n"] == 10 and d["arquivo"] == "trackers_depara.xlsx"
    u = d["por_usina"][("pv", "altair 1")]
    assert [x["num"] for x in u["trackers"]] == [1, 2, 3] and u["usina_fracttal"] == "Thopen - Altair 1 - SP"
    assert u["resumo"] == {"casado": 2, "a_confirmar": 0, "sem_par": 1, "n": 3}
    assert d["por_usina"][("pg", "santo inacio 12")]["trackers"][0]["situacao"] == "a_confirmar"
    assert d["por_usina"][("sunop", "cpp100")]["por_num"][5]["code"] == "CPP100-ETKR5.101"
    assert d["pendencias"][0]["UFV Fracttal"].startswith("Thopen - Córrego") and d["pendencias"][0]["Trackers sem par"] == "67"
    # ordem: fonte (pg < pv < sunop) e depois o nome normalizado
    assert [r["usina"] for r in d["resumo"]] == ["(310) Salto Pirapora III", "(327) Santo Inácio XII", "Altair 1 (73)", "Altair 2 (74)", "Caicó 1.1 (224)", "Corrego Sapucaia 1 (113)", "Corrego Sapucaia 2 (114)", "CPP100"]


def test_casamento_exato_substring_e_uniao_por_prefixo(depara):
    exato = app._trk_depara_usina("pv", "Altair 1 (73)")
    assert exato["n"] == 3 and exato["usinas"] == ["Altair 1 (73)"] and exato["por_num"]["1"]["fracttal"] == "Tracker 01.100"
    # a plataforma chama a usina de 'Caicó' e o de-para de 'Caicó 1.1 (224)': substring única
    sub = app._trk_depara_usina("API PV", "Caicó")
    assert sub and sub["n"] == 1 and sub["por_num"]["7"]["code"] == "CAI100-ETKR7.101"
    # 'Altair' na plataforma = Altair 1 + Altair 2 no de-para: união, contagens somadas
    uniao = app._trk_depara_usina("pv", "Altair")
    assert uniao["usinas"] == ["Altair 1 (73)", "Altair 2 (74)"] and uniao["n"] == 4
    assert (uniao["casados"], uniao["a_confirmar"], uniao["sem_par"]) == (2, 1, 1)
    # apelidos de fonte: 'Thopen' e 'Banco de Dados' são o pg; nome da plataforma sem o '(327)'
    assert app._trk_depara_usina("Thopen", "Santo Inácio XII")["por_num"]["1"]["situacao"] == "a_confirmar"
    assert app._trk_depara_usina("sunop", "CPP100")["por_num"]["5"]["tracker"] == "TRK_5"
    assert app._trk_depara_usina("pv", "Inexistente") is None and app._trk_depara_usina("pv", "") is None
    # os dois nomes que não casavam em 06/09
    sap = app._trk_depara_usina("pv", "Córrego do Sapucaia")          # plataforma agrupa as duas sub-usinas
    assert sap["usinas"] == ["Corrego Sapucaia 1 (113)", "Corrego Sapucaia 2 (114)"] and sap["sem_par"] == 2
    assert app._trk_depara_usina("Thopen", "Salto Pirapora 3")["por_num"]["6"]["code"] == "SPI100-ETKR6.100"


def test_rele_quando_a_planilha_muda(depara):
    assert app._trk_depara_carregar()["n"] == 10
    _planilha(depara, LINHAS + [["Axis", "PEIII", "Axis - Ponto Belo", "Tracker 9", "Tracker 1.9", "PTL300-ETKR9.100", "100", "direto", None]])
    os.utime(depara, (time.time() + 5, time.time() + 5))         # mtime novo mesmo que a gravação caiba no mesmo segundo
    d = app._trk_depara_carregar()
    assert d["n"] == 11 and app._trk_depara_usina("axis", "PE III")["por_num"]["9"]["code"] == "PTL300-ETKR9.100"


def test_sem_planilha_nao_quebra(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "_TRK_DEPARA_PATH", str(tmp_path / "nao-ha.xlsx"))
    monkeypatch.setattr(app, "_TRK_DEPARA_LOCAL", str(tmp_path / "nem.local.xlsx"))
    app._trk_depara_carregar._c = None
    assert app._trk_depara_carregar()["n"] == 0 and app._trk_depara_usina("pv", "Altair") is None
