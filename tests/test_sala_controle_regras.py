# -*- coding: utf-8 -*-
"""As regras da entrega 3 da Sala de controle (`plataforma/sala_controle.py`, 16/11/2026): a idade real da string parada
além do mês, o visto por pessoa e a usina do SCADA da Grid que serve de segunda fonte. Regra pura: sem Flask, sem rede.
Usinas e pessoas de mentira."""
import json
from datetime import datetime

import pytest

import sala_controle as S


def _ep(usina, inv, st, d0, d1, inicio=None):
    return {"usina": usina, "inversor": inv, "string": st, "d0": d0, "d1": d1, "inicio": inicio or (d0 + " 07:10")}


def _pac(ini, fim, eps):
    return {"periodo": [ini, fim], "strings": {"episodios": eps}}


# ── 1. a idade real ─────────────────────────────────────────────────────────────────────────────────────────────
def test_a_string_que_ja_vinha_parada_ganha_a_data_em_que_parou():
    nov = _pac("2026-11-01", "2026-11-16", [_ep("Usina A", "Inversor 1.2", "ST 04", "2026-11-01", "2026-11-15"),
                                           _ep("Usina A", "Inversor 1.3", "ST 01", "2026-11-09", "2026-11-15")])
    out = _pac("2026-10-01", "2026-10-31", [_ep("Usina A", "Inversor 1.2", "ST 04", "2026-10-17", "2026-10-31",
                                                "2026-10-17 09:40")])
    r = S.idade_real([nov, out])
    assert r["strings"] == {"Usina A|Inversor 1.2|ST 04": {"d0": "2026-10-17", "inicio": "2026-10-17 09:40", "antes": False}}
    assert r["ate"] == "2026-10-01"                 # quem parou no dia 9 não entra: o pacote do mês já data certo


def test_segue_de_mes_em_mes_e_diz_quando_chegou_ao_fim_do_que_ha():
    nov = _pac("2026-11-01", "2026-11-16", [_ep("Usina A", "Inversor 1.2", "ST 04", "2026-11-01", "2026-11-15")])
    out = _pac("2026-10-01", "2026-10-31", [_ep("Usina A", "Inversor 1.2", "ST 04", "2026-10-01", "2026-10-31")])
    sete = _pac("2026-09-01", "2026-09-30", [_ep("Usina A", "Inversor 1.2", "ST 04", "2026-09-12", "2026-09-30")])
    assert S.idade_real([nov, out, sete])["strings"]["Usina A|Inversor 1.2|ST 04"] == {
        "d0": "2026-09-12", "inicio": "2026-09-12 07:10", "antes": False}
    # sem setembro publicado: a cadeia chega ao dia 1 de outubro e a tela diz "desde antes de 01/10", sem inventar data
    r = S.idade_real([nov, out])
    assert r["strings"]["Usina A|Inversor 1.2|ST 04"] == {"d0": "2026-10-01", "inicio": "2026-10-01 07:10", "antes": True}
    assert r["ate"] == "2026-10-01"


def test_voltou_no_fim_do_mes_e_parou_de_novo_no_dia_1_sao_paradas_diferentes():
    nov = _pac("2026-11-01", "2026-11-16", [_ep("Usina A", "Inversor 1.2", "ST 04", "2026-11-01", "2026-11-15")])
    out = _pac("2026-10-01", "2026-10-31", [_ep("Usina A", "Inversor 1.2", "ST 04", "2026-10-17", "2026-10-29")])
    assert S.idade_real([nov, out])["strings"]["Usina A|Inversor 1.2|ST 04"] == {
        "d0": "2026-11-01", "inicio": "2026-11-01 07:10", "antes": False}


def test_mes_faltando_no_meio_para_a_cadeia():
    nov = _pac("2026-11-01", "2026-11-16", [_ep("Usina A", "Inversor 1.2", "ST 04", "2026-11-01", "2026-11-15")])
    sete = _pac("2026-09-01", "2026-09-30", [_ep("Usina A", "Inversor 1.2", "ST 04", "2026-09-12", "2026-09-30")])
    r = S.idade_real([nov, sete])                   # outubro não foi publicado: nada de pular para setembro
    assert r["strings"]["Usina A|Inversor 1.2|ST 04"]["d0"] == "2026-11-01"
    assert r["strings"]["Usina A|Inversor 1.2|ST 04"]["antes"] is True and r["ate"] == "2026-11-01"
    assert S.idade_real([]) == {"strings": {}, "ate": None}


# ── 2. o visto por pessoa ────────────────────────────────────────────────────────────────────────────────────────
K1, K2 = "s|Usina A|Inversor 1.2|ST 04|2026-11-16", "t|Usina A|Tracker 09|2026-11-16"


def test_a_primeira_abertura_grava_o_desde_e_ele_nao_anda(tmp_path):
    v = S.Vistos(str(tmp_path / "sala_visto.json"))
    a = v.da_pessoa("ana@exemplo.invalid", "Ana Teste", datetime(2026, 11, 16, 15, 40))
    assert a["eu"] == {"id": "ana@exemplo.invalid", "nome": "Ana Teste", "desde": "2026-11-16 15:40"} and a["vistos"] == {}
    b = v.da_pessoa("ana@exemplo.invalid", "Ana Teste", datetime(2026, 11, 17, 8, 0))
    assert b["eu"]["desde"] == "2026-11-16 15:40"   # o que parou depois da 1ª vez segue novo até ela abrir


def test_todos_veem_quem_ja_viu_e_cada_um_tem_o_seu(tmp_path):
    v = S.Vistos(str(tmp_path / "sala_visto.json"))
    v.da_pessoa("ana@exemplo.invalid", "Ana Teste", datetime(2026, 11, 16, 8, 0))
    v.da_pessoa("bia@exemplo.invalid", "Bia Teste", datetime(2026, 11, 16, 8, 5))
    assert v.marcar("ana@exemplo.invalid", "Ana Teste", [K1, K2, "lixo", K1], datetime(2026, 11, 16, 15, 41)) == 2
    assert v.marcar("ana@exemplo.invalid", "Ana Teste", [K1], datetime(2026, 11, 16, 16, 0)) == 0    # a 1ª vez fica
    da_bia = v.da_pessoa("bia@exemplo.invalid", "Bia Teste", datetime(2026, 11, 16, 16, 1))
    assert da_bia["vistos"][K1] == [{"nome": "Ana Teste", "quando": "2026-11-16 15:41", "eu": False}]
    v.marcar("bia@exemplo.invalid", "Bia Teste", [K1], datetime(2026, 11, 16, 16, 2))
    da_ana = v.da_pessoa("ana@exemplo.invalid", "Ana Teste", datetime(2026, 11, 16, 16, 3))
    assert [(x["nome"], x["eu"]) for x in da_ana["vistos"][K1]] == [("Ana Teste", True), ("Bia Teste", False)]
    assert "exemplo.invalid" not in json.dumps(da_ana["vistos"])       # o e-mail de ninguém vai para a tela


def test_a_senha_compartilhada_e_uma_pessoa_so_e_o_antigo_e_podado(tmp_path):
    v = S.Vistos(str(tmp_path / "sala_visto.json"))
    velha = "s|Usina A|Inversor 1.2|ST 04|2026-07-01"
    v.marcar(None, "", [velha, K1], datetime(2026, 7, 2, 9, 0))
    assert v.da_pessoa(None, "", datetime(2026, 7, 2, 9, 1))["eu"]["id"] == S.SEM_IDENTIDADE
    v.marcar(None, "", [K2], datetime(2026, 11, 16, 9, 0))             # a gravação seguinte poda o que tem mais de 90 dias
    vistos = v.da_pessoa(None, "", datetime(2026, 11, 16, 9, 1))["vistos"]
    assert velha not in vistos and K1 in vistos and K2 in vistos
    assert vistos[K2][0]["nome"] == "alguém pela senha"


@pytest.mark.parametrize("ruim", ["", "x|a|b|2026-11-16", "s|Usina|2026-11-1", "s|" + "a" * 300 + "|2026-11-16",
                                  "s|Usina\x01A|Inv|ST|2026-11-16", None, 12])
def test_chave_fora_do_formato_nao_entra(ruim):
    assert S.chave_valida(ruim) is None


def test_arquivo_ilegivel_nao_e_regravado(tmp_path):
    p = tmp_path / "sala_visto.json"
    p.write_text("{quebrado", encoding="utf-8")
    v = S.Vistos(str(p))
    with pytest.raises(ValueError):
        v.marcar("ana@exemplo.invalid", "Ana", [K1], datetime(2026, 11, 16, 9, 0))
    assert p.read_text(encoding="utf-8") == "{quebrado"                 # regravar apagaria o que já estava lá


# ── 3. conferir fontes ───────────────────────────────────────────────────────────────────────────────────────────
SCADA = [{"id": "usina_dupla", "nome": "Usina Dupla 1 e 2", "via": "mqtt", "inv_total": 28},
         {"id": "sozinha", "nome": "sozinha", "via": "modbus", "inv_total": 10},
         {"id": "rio_i_ii", "nome": "Rio Teste I e II", "via": "mqtt", "inv_total": 21},
         {"id": "ipx", "nome": "Vila do para 2C", "via": "mqtt", "inv_total": 20}]


def test_a_usina_do_scada_que_junta_duas_cobre_as_duas():
    x = S.usina_do_scada("Usina Dupla 2", SCADA)
    assert (x["id"], x["cobre"], x["duas"]) == ("usina_dupla", ["usina dupla 1", "usina dupla 2"], True)
    assert S.usina_do_scada("Usina Dupla 3", SCADA) is None


def test_o_nome_inteiro_igual_vence_e_o_cliente_no_fim_do_nome_nao_atrapalha():
    assert S.usina_do_scada("Sozinha", SCADA)["id"] == "sozinha"
    x = S.usina_do_scada("Rio Teste I e II", SCADA)                    # UMA usina no Tempo real, com o "e" no nome
    assert (x["id"], x["duas"], x["cobre"]) == ("rio_i_ii", False, ["rio teste i e ii"])
    assert S.usina_do_scada("Vila do Pará", SCADA)["id"] == "ipx"      # o SCADA escreve o cliente no fim
    assert S.usina_do_scada("Outra Usina", SCADA) is None


def test_leituras_na_ordem_natural_e_sem_valor_na_leitura_ruim():
    l = S.leituras_para_conferir([
        {"equip": "inv-10", "ok": True, "pot_kw": 61.234, "eday": 300.04, "strings": {1: 9.1, 2: 0.0, 3: None}, "serial": "B2"},
        {"equip": "inv-02", "ok": False, "pot_kw": None, "eday": None, "strings": {}, "serial": "A1"}])
    assert [x["eq"] for x in l] == ["inv-02", "inv-10"]
    assert l[1] == {"eq": "inv-10", "ok": True, "kw": 61.23, "kwh": 300.0, "com_corrente": 1, "strings": 2, "sn": "B2", "ts": None}
    assert l[0]["kw"] is None and l[0]["com_corrente"] is None         # lacuna é sem comunicação, não zero



# ── 4. exportar Excel ────────────────────────────────────────────────────────────────────────────────────────────
def test_o_excel_sai_com_as_datas_na_primeira_coluna_e_os_inversores_em_colunas(tmp_path):
    import openpyxl
    wb, arq = S.planilha({"arquivo": "Geração Usina A 2026-11.xlsx", "abas": [
        {"nome": "Geração (kWh)", "cabecalho": ["Data", "Inversor 1.1", "Inversor 1.2"],
         "linhas": [["01/11/2026", 611.7, 345.9], ["02/11/2026", 600, None]]},
        {"nome": "Irradiação", "cabecalho": ["Data", "IPOA (kWh/m²)"], "linhas": [["01/11/2026", 5.52], ["02/11/2026", "=1+1"]]}]})
    assert arq == "Geração Usina A 2026-11.xlsx"
    p = tmp_path / arq
    wb.save(p)
    lido = openpyxl.load_workbook(p)
    assert lido.sheetnames == ["Geração (kWh)", "Irradiação"]
    g = lido["Geração (kWh)"]
    assert [c.value for c in g[1]] == ["Data", "Inversor 1.1", "Inversor 1.2"] and g["A1"].font.bold
    assert (g["A2"].value, g["B2"].value, g["C3"].value) == ("01/11/2026", 611.7, None) and g.freeze_panes == "B2"
    assert lido["Irradiação"]["B3"].value == "'=1+1"                    # texto que parece fórmula não vira fórmula


@pytest.mark.parametrize("corpo", [None, {}, {"abas": []}, {"abas": [{"nome": "x"}]},
                                   {"abas": [{"cabecalho": ["a"], "linhas": [["x"]]}] * 5},
                                   {"abas": [{"cabecalho": ["a"] * 401, "linhas": []}]},
                                   {"abas": [{"cabecalho": ["a"], "linhas": ["não é linha"]}]}])
def test_exportar_fora_do_formato_e_recusado(corpo):
    with pytest.raises(S.ExportRecusado):
        S.planilha(corpo)


def test_o_nome_do_arquivo_e_limpo():
    aba = [{"cabecalho": ["a"], "linhas": []}]
    assert S.planilha({"arquivo": '../../etc/pas"swd', "abas": aba})[1] == "etcpasswd.xlsx"
    assert S.planilha({"abas": aba})[1] == "sala-de-controle.xlsx"
