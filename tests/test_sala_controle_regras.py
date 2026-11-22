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


# ── 5. o raio-x do SCADA e a leitura de agora ────────────────────────────────────────────────────────────────────
def test_raio_x_conta_tracker_e_estacao_por_usina_e_serve_ao_casamento_pelo_nome():
    l = S.raiox_scada({"a": {"inv_total": 2}, "b": {"inv_total": 0}},
                      {"usinas": [{"usina": "a", "nome": "Usina A 1 e 2", "equipamentos": [
                          {"tipo": "inverter", "equipamento": "inv-01"}, {"tipo": "tracker", "equipamento": "t1"},
                          {"tipo": "tracker_ncu", "equipamento": "t2"}, {"tipo": "weather", "equipamento": "e1"}, {"tipo": "relay"}]}]})
    assert l[0] == {"id": "a", "nome": "Usina A 1 e 2", "via": "mqtt", "inv_total": 2, "equipamentos": ["inv-01"],
                    "tipos": {"inverter": 1, "tracker": 1, "tracker_ncu": 1, "weather": 1, "relay": 1}, "trackers": 2, "estacoes": 1}
    assert (l[1]["id"], l[1]["nome"], l[1]["via"], l[1]["trackers"]) == ("b", "b", "modbus", 0)
    assert S.usina_do_scada("Usina A 2", l)["trackers"] == 2


def test_tracker_mudo_nao_tem_angulo_e_a_estacao_ruim_nao_tem_valor():
    t = S.trackers_de_agora({"trackers": [{"equipamento": "tracker-ncu1-010", "posicao_atual": 10, "posicao_alvo": 12, "desvio": 2,
                                           "fora_do_alvo": True, "alarmes": 3},
                                          {"equipamento": "tracker-ncu1-002", "posicao_atual": 1, "posicao_alvo": 12, "desvio": 11,
                                           "fora_do_alvo": True, "sem_comunicacao": True}]})
    assert [x["eq"] for x in t["lista"]] == ["tracker-ncu1-002", "tracker-ncu1-010"]
    assert t["lista"][0] == {"eq": "tracker-ncu1-002", "atual": None, "alvo": 12.0, "desvio": None, "fora": False, "sem_com": True, "alarmes": 0}
    assert (t["total"], t["fora_do_alvo"], t["sem_comunicacao"], t["com_alarme"]) == (2, 1, 1, 1)
    e = S.estacoes_de_agora({"equipamentos": [
        {"tipo": "weather", "equipamento": "e1", "communication_fault": 28, "measurements": {"irradiance_poa": 800}},
        {"tipo": "weather", "equipamento": "e2", "communication_fault": 192, "measurements": {"irradiance_poa": 812.456, "x": 1}},
        {"tipo": "inverter", "equipamento": "1"}]})
    assert [(x["eq"], x["ok"], x["medidas"]) for x in e] == [("e1", False, []), ("e2", True, [{"nome": "POA", "valor": 812.46, "unidade": "W/m²"}])]


# ── 6. o novo por pessoa, por usina (o sino do topo do Nexus) ───────────────────────────────────────────────────
def test_o_novo_por_usina_e_a_mesma_regra_da_tela():
    pac = {"strings": {"rows": [{"dia": "2026-11-01"}, {"dia": "2026-11-14"}, {"dia": "2026-11-15"}, {"dia": "2026-11-16"}],
                       "episodios": [
                           _ep("Usina A", "Inversor 1.2", "ST 04", "2026-11-15", "2026-11-15", "2026-11-15 09:10"),      # nova
                           _ep("Usina A", "Inversor 1.2", "ST 05", "2026-11-15", "2026-11-15", "2026-11-15 09:12"),      # nova
                           _ep("Usina A", "Inversor 1.10", "ST 03", "2026-11-15", "2026-11-15", "2026-11-15 09:30"),     # nova (1.10 depois do 1.2)
                           _ep("Usina A", "Inversor 1.3", "ST 01", "2026-11-15", "2026-11-15", "2026-11-15 11:00"),      # nova, já vista
                           _ep("Usina A", "Inversor 1.4", "ST 02", "2026-11-14", "2026-11-14", "2026-11-14 10:00"),      # já voltou
                           _ep("Usina B", "Inversor 2.1", "ST 09", "2026-11-13", "2026-11-15", "2026-11-13 10:00"),      # de antes da 1ª vez
                           _ep("Usina C", "Inversor 3.1", "ST 07", "2026-11-01", "2026-11-15", "2026-11-01 07:10")]},    # vinha de outubro
           "trackers": {"rows": [{"usina": "Usina B", "tracker": "Tracker 09", "inicio": "2026-11-15 13:00", "fim": ""},
                                 {"usina": "Usina B", "tracker": "Tracker 10", "inicio": "2026-11-15 13:05", "fim": "2026-11-15"},
                                 {"usina": "Usina B", "tracker": "Tracker 11", "inicio": "2026-11-12 13:05", "fim": ""}]}}
    idade = {"strings": {"Usina C|Inversor 3.1|ST 07": {"d0": "2026-10-17", "inicio": "2026-10-17 09:40", "antes": False}}}
    vistas = {"s|Usina A|Inversor 1.3|ST 01|2026-11-15"}
    r = S.novas_por_usina(pac, idade, "2026-11-14 18:00", vistas, "2026-11-16")
    # 22/11/2026, Levi, com o print do sino do Nexus: "quando eu abrir uma notificação da sala de controle tem que abrir
    # exatamente na usina e nos equipamentos citados, se não, não serve" — além da conta, QUAIS inversores e trackers
    assert r == [{"usina": "Usina A", "strings": 3, "inversores": 2, "trackers": 0, "inv": ["Inversor 1.2", "Inversor 1.10"], "trk": []},
                 {"usina": "Usina B", "strings": 0, "inversores": 0, "trackers": 1, "inv": [], "trk": ["Tracker 09"]}]
    assert S.novas_por_usina(pac, idade, None, set(), "2026-11-16") == []       # quem nunca abriu a Sala não tem novidade
    # sem a idade real, a string que vinha de outubro pareceria ter parado no dia 1 (e, com um "desde" de antes, seria nova)
    assert [u["usina"] for u in S.novas_por_usina(pac, {}, "2026-10-31 00:00", set(), "2026-11-16")] == ["Usina A", "Usina B", "Usina C"]
    assert "Usina C" not in [u["usina"] for u in S.novas_por_usina(pac, idade, "2026-10-31 00:00", set(), "2026-11-16")]


def test_a_consulta_do_sino_nao_cria_a_pessoa(tmp_path):
    v = S.Vistos(str(tmp_path / "sala_visto.json"))
    assert v.consulta("ana@exemplo.invalid") == (None, set())
    assert not (tmp_path / "sala_visto.json").exists()                          # perguntar não grava nada
    v.da_pessoa("ana@exemplo.invalid", "Ana", datetime(2026, 11, 16, 8, 0))
    v.marcar("ana@exemplo.invalid", "Ana", [K1], datetime(2026, 11, 16, 9, 0))
    v.marcar("bia@exemplo.invalid", "Bia", [K2], datetime(2026, 11, 16, 9, 5))
    assert v.consulta("ana@exemplo.invalid") == ("2026-11-16 08:00", {K1})



# ── 7. as plantas de uma usina agrupada, cada uma na sua linha, SÓ na Sala (22/11/2026) ────────────────────────────
# Levi: "é a Barretos 2, separa e sobe", e na escolha "Só na Sala e no aviso". O cadastro junta as plantas 297410 e 297415
# da API PV na Barretos física; a Sala lia só a 297410 e o aviso contava os trackers das duas juntos (81, TRK42 nas duas).
def test_o_nome_de_cada_planta():
    assert S.nome_da_planta("Barretos 2 (83)") == "Barretos 2"
    assert S.nome_da_planta("Assis Chateaubriand  Skid 1 (79)") == "Assis Chateaubriand Skid 1"
    ps = S.plantas_da_usina("Barretos", [{"plant_id": 297410, "usina": "Barretos 1 (83)"}, {"plant_id": 297415, "usina": "Barretos 2 (83)"}])
    assert ps == [{"plant_id": 297410, "nome": "Barretos 1"}, {"plant_id": 297415, "nome": "Barretos 2"}]
    # o nome vazio, repetido, igual ao da usina física ou ao de outra usina da lista leva o id (duas linhas nunca se juntam)
    ps = S.plantas_da_usina("Fazenda", [{"plant_id": 1, "usina": "Fazenda (9)"}, {"plant_id": 2, "usina": "Outra (3)"},
                                        {"plant_id": 3, "usina": "X 1"}, {"plant_id": 4, "usina": "X 1 (5)"}, {"plant_id": 5, "usina": ""}],
                            outros={"Outra"})
    assert [p["nome"] for p in ps] == ["Fazenda · 1", "Outra · 2", "X 1 · 3", "X 1 · 4", "Fazenda · 5"]
    ent = {"grupos": [{"usinas": [{"usina": "Barretos", "partes": [{"plant_id": 297410, "nome": "Barretos 1"}, {"plant_id": 297415, "nome": "Barretos 2"}]},
                                  {"usina": "Altair 1", "plant_id": 22860}]}]}
    assert S.plantas_da_entrada(ent) == {"297410": "Barretos 1", "297415": "Barretos 2"}
    assert S.plantas_da_entrada(None) == {} and S.plantas_da_entrada({"aquecendo": True, "grupos": []}) == {}


def test_o_novo_separa_as_plantas_da_usina_agrupada():
    pac = {"strings": {"rows": [{"dia": "2026-11-01"}, {"dia": "2026-11-15"}, {"dia": "2026-11-16"}],
                       "episodios": [dict(_ep("Indaiatuba", "Inversor 2.1", "ST 03", "2026-11-15", "2026-11-15", "2026-11-15 09:10"), plant_id="21481"),
                                     dict(_ep("Indaiatuba", "Inversor 1.1", "ST 01", "2026-11-01", "2026-11-15", "2026-11-01 07:00"), plant_id=21480)]},
           "trackers": {"rows": [{"usina": "Barretos", "plant_id": "297410", "tracker": "TRK42", "inicio": "2026-11-15 13:00", "fim": ""},
                                 {"usina": "Barretos", "plant_id": "297415", "tracker": "TRK42", "inicio": "2026-11-15 13:00", "fim": ""},
                                 {"usina": "Barretos", "plant_id": "297415", "tracker": "TRK7", "inicio": "2026-11-15 14:00", "fim": ""}]}}
    # a idade real é da usina FÍSICA (o pacote do mês anterior não sabe da separação): a ST 01 vinha de outubro, não é nova
    idade = {"strings": {"Indaiatuba|Inversor 1.1|ST 01": {"d0": "2026-10-17", "inicio": "2026-10-17 09:40", "antes": False}}}
    plantas = {"297410": "Barretos 1", "297415": "Barretos 2", "21480": "Indaiatuba 1", "21481": "Indaiatuba 2"}
    r = S.novas_por_usina(pac, idade, "2026-11-14 18:00", {"t|Barretos 1|TRK42|2026-11-15"}, "2026-11-16", plantas=plantas)
    assert r == [{"usina": "Barretos 2", "strings": 0, "inversores": 0, "trackers": 2, "inv": [], "trk": ["TRK7", "TRK42"]},
                 {"usina": "Indaiatuba 2", "strings": 1, "inversores": 1, "trackers": 0, "inv": ["Inversor 2.1"], "trk": []}]
    # sem o mapa (a Entrada aquecendo), como era: a usina física
    assert [u["usina"] for u in S.novas_por_usina(pac, idade, "2026-11-14 18:00", set(), "2026-11-16")] == ["Barretos", "Indaiatuba"]
