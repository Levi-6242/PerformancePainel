# -*- coding: utf-8 -*-
"""A disponibilidade da Thopen pelas normalizações do COS (Levi, 29/10/2026: "calcule a disponibilidade por lá usando o
de-para como referência [...] o que for falha de comunicação tem a coluna Geração Parou, se sim então deve contar na
disponibilidade e entrar nos comentários. Nos comentários tem que vir as proteções atuadas"; decisões dele: só a
Thopen, conta só o que está nas normalizações). As linhas são as do `fato_normalizacao` que o Nexus grava; dados
fictícios. O que estes testes seguram: desligamento conta da falha até a volta do COS; comunicação só com a geração
parada; desfeita, sem hora real e outro tipo ficam fora (e fora do "alinhar"); a OS do Fracttal da Thopen sai da conta
e a de outro cliente segue; o escopo pelo código do equipamento; a usina pelo de-para; as proteções vão na OS."""
from datetime import datetime

import pytest

import disponibilidade as dm

PER_INI, PER_FIM, AGORA = datetime(2026, 10, 1), datetime(2026, 11, 1), datetime(2026, 11, 5, 12, 0)
TOT_H = 12.0 * 31
EQUIP = [
    {"cliente": "Thopen", "usina": "Alfa", "usina_fracttal": "Thopen - Alfa - SP", "equipamento": "UFV",
     "pot_kwp": 1000.0, "n_inv": 2, "full_om": "Sim"},
    {"cliente": "Thopen", "usina": "Alfa", "usina_fracttal": "Thopen - Alfa - SP", "equipamento": "UG 01",
     "pot_kwp": 600.0},
    {"cliente": "Thopen", "usina": "Alfa", "usina_fracttal": "Thopen - Alfa - SP", "equipamento": "UG 02",
     "pot_kwp": 400.0},
    {"cliente": "Thopen", "usina": "Alfa", "usina_fracttal": "Thopen - Alfa - SP", "equipamento": "Inversor 1.1",
     "parente": "UG 01", "pot_kwp": 300.0},
    # um cadastro de site no Registro ("Beta 1 e 2", um usina_id) e duas usinas na aba, como a Ipixuna 1 e 2
    {"cliente": "Thopen", "usina": "Beta 1", "usina_fracttal": "Thopen - Beta 1 e 2 - RN", "equipamento": "UFV",
     "pot_kwp": 500.0, "n_inv": 2, "full_om": "Sim"},
    {"cliente": "Thopen", "usina": "Beta 2", "usina_fracttal": "Thopen - Beta 1 e 2 - RN", "equipamento": "UFV",
     "pot_kwp": 500.0, "n_inv": 2, "full_om": "Sim"},
    {"cliente": "OutraCo", "usina": "Gama", "usina_fracttal": "OutraCo - Gama - RN", "equipamento": "UFV",
     "pot_kwp": 500.0, "n_inv": 2, "full_om": "Sim"},
]
POR_ID = {11: ["Alfa"], 22: ["Gama"], 33: ["Beta 1", "Beta 2"]}


def norm(registro, **kw):
    r = {"registro": registro, "os": "17001", "cliente": "THOPEN", "usina_codigo": "THPN-ALF100", "usina_id": "11",
         "usina_ligada_por": "código cheio", "equipamentos_codigos": "", "tipo_falha": "DESLIGAMENTO_USINA",
         "normalizada": "1", "hora_real": "1", "inicio": "2026-10-10T09:00:00-03:00",
         "normalizado_em": "2026-10-10T15:00:00-03:00", "geracao_parou": "", "protecoes": "27ABC;86"}
    r.update(kw)
    return r


def task(**kw):
    base = {"tasks_log_task_type_main": "Religamento", "id_status_work_order": 3, "event_date": None,
            "date_maintenance": None, "final_date": None, "wo_final_date": None, "creation_date": None,
            "code": "THPN-ALF100", "items_log_description": "Thopen - Alfa - SP  Endereço",
            "groups_1_description": "Thopen - Alfa - SP", "description": "Religamento da Usina"}
    base.update(kw)
    return base


def roda(normalizacoes, wos=None):
    return dm.calcular(wos or {}, EQUIP, PER_INI, PER_FIM, agora=AGORA, normalizacoes=normalizacoes,
                       usinas_por_id=POR_ID)


def usina(r, nome):
    return next(u for u in r["usinas"] if u["usina"] == nome)


def a_os(r, folio):
    return next(o for o in r["oss"] if o["folio"] == folio)


def test_desligamento_conta_da_falha_ate_a_volta_do_cos_com_as_protecoes():
    r = roda([norm("r1")])
    o = a_os(r, 17001)
    assert o["fonte"] == "cos" and o["excl"] is None and o["protecoes"] == ["27ABC", "86"]
    assert o["h_solar"] == pytest.approx(6.0) and o["kwh"] == pytest.approx(6000, rel=1e-3)
    assert usina(r, "Alfa")["disp"] == pytest.approx(100 * (1 - 6.0 / TOT_H), abs=0.01)
    assert r["diario"]["Alfa"]["2026-10-10"]["os"][0]["trechos"] == "09:00-15:00"


@pytest.mark.parametrize("geracao,conta,alinhar", [("1", True, False), ("0", False, False), ("", False, True)])
def test_comunicacao_so_com_a_geracao_parada(geracao, conta, alinhar):
    r = roda([norm("r1", tipo_falha="FALHA_COMUNICACAO", geracao_parou=geracao, protecoes="")])
    o = a_os(r, 17001)
    assert (o["excl"] is None) == conta
    assert (usina(r, "Alfa")["disp"] < 100) == conta
    # sem a resposta do operador: fora da conta e no "alinhar", para o COS responder
    assert bool(r["alinhar"]) == alinhar
    if conta:
        assert o["tipos"] == ["falha de comunicação com a geração parada"]


def test_desligamento_de_usina_e_a_usina_inteira_mesmo_com_o_rele_citado():
    r = roda([norm("r1", equipamentos_codigos="ALF100-RELE1")])
    assert a_os(r, 17001)["kwh"] == pytest.approx(1000 * 6, rel=1e-3)


def test_rele_e_a_usina_inteira_e_qgbt_e_cabine():
    # Levi, 30/10/2026: "quando o ativo for rele considere a usina inteira, QGBT é cabine"
    r = roda([norm("r1", tipo_falha="DESLIGAMENTO_CABINE", equipamentos_codigos="ALF100-RELE1")])
    assert a_os(r, 17001)["kwh"] == pytest.approx(1000 * 6, rel=1e-3) and not r["alinhar"]
    r = roda([norm("r1", tipo_falha="ATUACAO_PROTECAO", equipamentos_codigos="THPN-ALF100-RELE1")])
    assert a_os(r, 17001)["kwh"] == pytest.approx(1000 * 6, rel=1e-3) and not r["alinhar"]
    r = roda([norm("r1", tipo_falha="DESLIGAMENTO_QGBT", equipamentos_codigos="THPN-ALF100-QGBT2")])
    assert a_os(r, 17001)["kwh"] == pytest.approx(400 * 6, rel=1e-3)          # a cabine 2 (400 kWp)


def test_codigo_que_nao_e_de_geracao_vai_pela_media_e_para_o_alinhar():
    r = roda([norm("r1", tipo_falha="DESLIGAMENTO_CABINE", equipamentos_codigos="ALF100-DLOG1")])
    assert a_os(r, 17001)["kwh"] == pytest.approx(500 * 6, rel=1e-3)          # a média das cabines (600 e 400)
    assert "potência média" in r["alinhar"][0]["motivo"]


@pytest.mark.parametrize("campo,valor", [("normalizada", "0"), ("hora_real", "0"), ("tipo_falha", "TRACKER_PARADO")])
def test_desfeita_sem_hora_real_e_outro_tipo_ficam_fora_e_fora_do_alinhar(campo, valor):
    r = roda([norm("r1", **{campo: valor})])
    assert a_os(r, 17001)["excl"].startswith("COS: ") and usina(r, "Alfa")["disp"] == 100
    assert not r["alinhar"]


def test_a_os_do_fracttal_da_thopen_sai_e_a_de_outro_cliente_segue():
    wos = {"500": [task(event_date="2026-10-12T12:00:00+00:00", final_date="2026-10-12T18:00:00+00:00")],
           "600": [task(code="OUTR-GAM100", items_log_description="OutraCo - Gama - RN  End",
                        groups_1_description="OutraCo - Gama - RN", event_date="2026-10-12T12:00:00+00:00",
                        final_date="2026-10-12T15:00:00+00:00")]}
    r = roda([], wos)
    assert 500 not in {o["folio"] for o in r["oss"]} and usina(r, "Alfa")["disp"] == 100
    assert a_os(r, 600)["kwh"] > 0 and usina(r, "Gama")["disp"] < 100
    # sem as normalizações (None), a régua de antes: a OS do Fracttal da Thopen conta
    antes = dm.calcular(wos, EQUIP, PER_INI, PER_FIM, agora=AGORA)
    assert usina(antes, "Alfa")["disp"] < 100


def test_escopo_pelo_codigo_do_equipamento():
    r = roda([norm("r1", tipo_falha="DESLIGAMENTO_CABINE", equipamentos_codigos="THPN-ALF100-CABN2")])
    assert a_os(r, 17001)["kwh"] == pytest.approx(400 * 6, rel=1e-3)          # a cabine 2 (400 kWp), 6 h
    r = roda([norm("r1", tipo_falha="DESLIGAMENTO_INVERSOR", equipamentos_codigos="THPN-ALF100-INVR1.1")])
    assert a_os(r, 17001)["kwh"] == pytest.approx(300 * 6, rel=1e-3)


def test_usina_sem_de_para_vai_para_o_alinhar_e_de_outro_cliente_fica_fora():
    r = roda([norm("r1", usina_id="")])
    assert a_os(r, 17001)["excl"].startswith("COS sem de-para") and r["alinhar"][0]["folio"] == 17001
    r = roda([norm("r1", usina_id="22", cliente="OUTRACO")])
    assert 17001 not in {o["folio"] for o in r["oss"]} and usina(r, "Gama")["disp"] == 100


def test_duas_normalizacoes_da_mesma_os_sao_dois_eventos_dela():
    r = roda([norm("r1"), norm("r2", inicio="2026-10-11T09:00:00-03:00", normalizado_em="2026-10-11T10:00:00-03:00",
                               protecoes="59C")])
    assert len([o for o in r["oss"] if o["folio"] == 17001]) == 1
    o = a_os(r, 17001)
    assert o["h_solar"] == pytest.approx(7.0) and o["protecoes"] == ["27ABC", "86", "59C"]


def test_normalizacao_sem_os_tem_numero_negativo_estavel():
    r = roda([norm("r-sem-os", os="")])
    o = next(x for x in r["oss"] if x["fonte"] == "cos")
    assert o["folio"] < 0 and o["folio"] == dm._folio_cos({"registro": "r-sem-os", "os": ""})


def test_fora_do_mes_nao_entra():
    r = roda([norm("r1", inicio="2026-09-10T09:00:00-03:00", normalizado_em="2026-09-10T15:00:00-03:00")])
    assert not [o for o in r["oss"] if o.get("fonte") == "cos"]


def test_cadastro_de_site_desliga_as_duas_e_a_cabine_n_e_a_usina_n():
    r = roda([norm("r1", usina_id="33", usina_codigo="THPN-BET100")])
    assert usina(r, "Beta 1")["h_perdidas"] == usina(r, "Beta 2")["h_perdidas"] == pytest.approx(6.0)
    r = roda([norm("r1", usina_id="33", usina_codigo="THPN-BET100", tipo_falha="DESLIGAMENTO_CABINE",
                   equipamentos_codigos="THPN-BET100-CABN2")])
    assert usina(r, "Beta 1")["disp"] == 100 and usina(r, "Beta 2")["h_perdidas"] == pytest.approx(6.0)


def test_normalizacao_longa_conta_e_vai_para_o_alinhar():
    r = roda([norm("r1", inicio="2026-10-01T06:00:00-03:00", normalizado_em="2026-10-04T18:00:00-03:00")])
    assert a_os(r, 17001)["excl"] is None and usina(r, "Alfa")["h_perdidas"] == pytest.approx(48.0)
    assert "normalização de 3 dias" in r["alinhar"][0]["motivo"]


def test_de_para_pelo_site_do_fracttal_e_pelo_nome():
    from depara_fracttal import usinas_por_id
    reg = [{"usina_id": 33, "nome": "Beta 1 e 2", "excluido": ""}, {"usina_id": 11, "nome": "Alfa 1", "excluido": ""}]
    dp = [{"usina_id": 33, "sistema": "Fracttal", "chave_externa": "Thopen - Beta 1 e 2 - RN"},
          {"usina_id": 11, "sistema": "BD_Performance", "chave_externa": "Alfa"}]
    assert usinas_por_id(reg, dp, EQUIP) == {33: ["Beta 1", "Beta 2"], 11: ["Alfa"]}


@pytest.mark.parametrize("tipo,codigos,kwh", [("ATUACAO_PROTECAO", "", 6000), ("FALHA_CONCESSIONARIA", "ALF100-RELE1", 6000),
                                              ("INVERSOR_OFFLINE", "THPN-ALF100-INVR1.1", 1800)])
def test_atuacao_de_protecao_inversor_offline_e_concessionaria_contam(tipo, codigos, kwh):
    # Levi, 29/10/2026: os três tipos também contam (a concessionária é a usina inteira)
    r = roda([norm("r1", tipo_falha=tipo, equipamentos_codigos=codigos)])
    assert a_os(r, 17001)["excl"] is None and a_os(r, 17001)["kwh"] == pytest.approx(kwh, rel=1e-3)


def test_excecoes_do_levi_na_brodowski(monkeypatch):
    monkeypatch.setattr(dm, "COS_EXCECOES", {"os:12693": ("fora", None, "a geração não parou"),
                                             "r-cab": ("cabine", 1, "só a cabine 1 parou")})
    r = roda([norm("r1", os="12693", tipo_falha="FALHA_COMUNICACAO", geracao_parou="1")])
    o = a_os(r, 12693)
    assert o["excl"].startswith("fora pela decisão do Levi") and usina(r, "Alfa")["disp"] == 100
    assert r["alinhar"][0]["folio"] == 12693
    r = roda([norm("r-cab", os="", tipo_falha="FALHA_COMUNICACAO", geracao_parou="1", equipamentos_codigos="ALF100-RELE1")])
    o = next(x for x in r["oss"] if x.get("fonte") == "cos")
    assert o["kwh"] == pytest.approx(600 * 6, rel=1e-3)                        # a cabine 1 (600 kWp), 6 h
    assert "só a cabine 1" in r["alinhar"][0]["motivo"]


def test_vale_o_cos_as_excecoes_da_planilha_sairam():
    # 30/10/2026: o COS corrigiu os registros na Ronda COS e, onde discordou da planilha, o Levi decidiu "Vale o COS"
    assert set(dm.COS_EXCECOES) == {"os:15632"}
    assert dm.ESCOPO_COS[17447][0] == ["Boa Esperança do Sul 2"]


def test_a_os_16498_na_normalizacao_so_vale_a_ap2(monkeypatch):
    # a regra de 26/10/2026 (ESCOPO_COS) vale também na normalização da mesma OS (30/10/2026: a barra da AP1 não caiu)
    monkeypatch.setattr(dm, "ESCOPO_COS", {17001: (["Beta 2"], "só a Beta 2")})
    r = roda([norm("r1", usina_id="33", usina_codigo="THPN-BET100")])
    assert usina(r, "Beta 1")["disp"] == 100 and usina(r, "Beta 2")["h_perdidas"] == pytest.approx(6.0)


def test_excecao_fora_tira_a_os_e_vai_ao_alinhar(monkeypatch):
    monkeypatch.setattr(dm, "COS_EXCECOES", {"os:14838": ("fora", None, "não desligou")})
    r = roda([norm("r1", os="14838")])
    assert a_os(r, 14838)["excl"].startswith("fora pela decisão do Levi") and usina(r, "Alfa")["disp"] == 100


def test_usina_da_thopen_monitorada_pelo_cos_entra_mesmo_sem_full_om():
    # 30/10/2026: Aruanã, Sapopema e Segredo ("Full O&M: Não" na aba) têm desligamento registrado pelo COS e "passam
    # para o COS"; a usina da Thopen sem normalização nenhuma e sem O&M completo segue fora
    eq = EQUIP + [
        {"cliente": "Thopen", "usina": "Eta", "usina_fracttal": "Thopen - Eta - PR", "equipamento": "UFV",
         "pot_kwp": 800.0, "n_inv": 2, "full_om": "Não"},
        {"cliente": "Thopen", "usina": "Teta", "usina_fracttal": "", "equipamento": "UFV", "pot_kwp": 500.0,
         "n_inv": 2, "full_om": "Não"}]
    r = dm.calcular({}, eq, PER_INI, PER_FIM, agora=AGORA, usinas_por_id={55: ["Eta"], 66: ["Teta"]},
                    normalizacoes=[norm("r1", usina_id="55", usina_codigo="THPN-ETA100")])
    nomes = {u["usina"] for u in r["usinas"]}
    assert "Eta" in nomes and "Teta" not in nomes
    assert usina(r, "Eta")["h_perdidas"] == pytest.approx(6.0)


def test_volta_e_trecho_corrigidos_pelo_levi(monkeypatch):
    monkeypatch.setattr(dm, "COS_EXCECOES", {
        "os:17001": ("volta", {"*": datetime(2026, 10, 10, 11, 0)}, "voltou 11:00"),
        "os:17002": ("periodo", (datetime(2026, 10, 12, 10, 0), datetime(2026, 10, 12, 10, 30)), "caiu 10:00 a 10:30"),
        "os:17003": ("volta", {"Beta 1": datetime(2026, 10, 14, 9, 0), "Beta 2": datetime(2026, 10, 14, 11, 0)}, "duas")})
    r = roda([norm("r1"),
              norm("r2", os="17002", inicio="2026-10-12T00:00:00-03:00", normalizado_em="2026-10-12T18:00:00-03:00"),
              norm("r3", os="17003", usina_id="33", usina_codigo="THPN-BET100", inicio="2026-10-14T06:00:00-03:00",
                   normalizado_em="2026-10-14T18:00:00-03:00")])
    assert a_os(r, 17001)["h_solar"] == pytest.approx(2.0)                       # 09:00 a 11:00
    assert a_os(r, 17002)["h_solar"] == pytest.approx(0.5)                       # 10:00 a 10:30
    assert usina(r, "Beta 1")["h_perdidas"] == pytest.approx(3.0) and usina(r, "Beta 2")["h_perdidas"] == pytest.approx(5.0)
    assert a_os(r, 17003)["fim_por_usina"] == {"Beta 1": "2026-10-14T09:00:00", "Beta 2": "2026-10-14T11:00:00"}
    assert any("hora pela decisão do Levi" in a["motivo"] for a in r["alinhar"])


def test_sem_as_normalizacoes_o_worker_nao_publica_e_a_thopen_nao_cai_no_fracttal(monkeypatch, tmp_path):
    # 30/10/2026, Levi: "garanta que a única fonte seja a de normalizações + adaptações sem puxar OS de fractall"
    import app
    avisos = []
    monkeypatch.setattr(app, "FRACTTAL_ON", True)
    monkeypatch.setattr(app, "_FRAC_DISP_FILE", str(tmp_path / "frac_disp_index.json"))
    monkeypatch.setattr(app, "_frac_disp_sweep", lambda limite, resumo=None: {"1": [{"code": "X"}]})
    monkeypatch.setattr(app, "_disp_equip_linhas", lambda: EQUIP)
    monkeypatch.setattr(app, "_disp_pot_reserva", lambda equip: {})
    monkeypatch.setattr(app, "_frac_com_vereditos", lambda wos: {})
    monkeypatch.setattr(app, "_disp_normalizacoes", lambda equip: (None, {}, "o livro ainda não está no banco"))
    monkeypatch.setattr(app, "_frac_disp_registrar", lambda ok, msg, resumo=None: avisos.append((ok, msg)))
    app._frac_disp_recalcular()
    assert avisos and avisos[0][0] is False and "normalizações do COS indisponíveis" in avisos[0][1]
    assert not (tmp_path / "frac_disp_index.json").exists()


def test_cabine_de_usina_de_site_dividido_e_lida_na_propria_usina():
    # 30/10/2026: a Rodrigues 2 (site "Rodrigues 1 e 2") citava a CABN1 dela, e a régua a mandava para a Rodrigues 1
    eq = EQUIP + [
        {"cliente": "Thopen", "usina": "Delta 1", "usina_fracttal": "Thopen - Delta 1 e 2 - SP", "equipamento": "UFV",
         "pot_kwp": 500.0, "n_inv": 2, "full_om": "Sim"},
        {"cliente": "Thopen", "usina": "Delta 2", "usina_fracttal": "Thopen - Delta 1 e 2 - SP", "equipamento": "UFV",
         "pot_kwp": 900.0, "n_inv": 3, "full_om": "Sim"},
        {"cliente": "Thopen", "usina": "Delta 2", "usina_fracttal": "Thopen - Delta 1 e 2 - SP", "equipamento": "UG 01",
         "pot_kwp": 300.0},
        {"cliente": "Thopen", "usina": "Delta 2", "usina_fracttal": "Thopen - Delta 1 e 2 - SP", "equipamento": "UG 02",
         "pot_kwp": 600.0}]
    r = dm.calcular({}, eq, PER_INI, PER_FIM, agora=AGORA, usinas_por_id={44: ["Delta 2"]},
                    normalizacoes=[norm("r1", usina_id="44", usina_codigo="THPN-DLT200", tipo_falha="DESLIGAMENTO_CABINE",
                                        equipamentos_codigos="THPN-DLT200-CABN1")])
    o = a_os(r, 17001)
    assert o["kwh"] == pytest.approx(300 * 6, rel=1e-3) and usina(r, "Delta 1")["disp"] == 100
    assert not r["alinhar"]


def test_falha_de_comunicacao_que_o_levi_disse_ser_desligamento():
    # 30/10/2026: a OS 15632 (São Bento 5), comunicação sem a resposta "a geração parou?": "considera desligamento"
    assert dm.COS_EXCECOES["os:15632"][0] == "desligamento"
    r = roda([norm("r1", os="15632", tipo_falha="FALHA_COMUNICACAO", geracao_parou="", protecoes="")])
    o = a_os(r, 15632)
    assert o["excl"] is None and o["tipos"] == ["desligamento de usina"] and o["kwh"] == pytest.approx(6000, rel=1e-3)



def test_a_linha_agregada_nao_entra_pela_normalizacao(monkeypatch):
    # 30/10/2026: a "AP. do Taboado" (PARQUE_EXCLUI) tem o site da 1 e da 2 e o de-para a liga à normalização delas
    monkeypatch.setattr(dm, "PARQUE_EXCLUI", {"Eta"})
    eq = EQUIP + [{"cliente": "Thopen", "usina": "Eta", "usina_fracttal": "Thopen - Eta - PR", "equipamento": "UFV",
                   "pot_kwp": 800.0, "n_inv": 2, "full_om": "Não"}]
    r = dm.calcular({}, eq, PER_INI, PER_FIM, agora=AGORA, usinas_por_id={55: ["Eta"]},
                    normalizacoes=[norm("r1", usina_id="55", usina_codigo="THPN-ETA100")])
    assert "Eta" not in {u["usina"] for u in r["usinas"]}


# ── as ocorrências ainda abertas (30/10/2026, Levi: "para as em aberto contar na disponibilidade precisamos puxar os dados
# dessa fonte") ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def aberta(registro, **kw):
    """Uma linha do `fato_ocorrencia_aberta` do Nexus (sem a volta)."""
    r = {"registro": registro, "os": "16958", "cliente": "THOPEN", "usina_codigo": "THPN-ALF100", "usina_id": "11",
         "usina_ligada_por": "código cheio", "equipamentos_codigos": "", "equipamentos_qtd": "0", "equipamentos_de": "",
         "tipo_falha": "DESLIGAMENTO_USINA", "severidade": "CRITICO", "etapa": "Aguardando peça",
         "inicio": "2026-10-10T09:00:00-03:00", "data_id_inicio": "20261010", "dias_aberta_qtd": "20",
         "geracao_parou": "", "protecoes": "27"}
    r.update(kw)
    return r


def roda_com_abertas(normalizacoes, abertas, agora=AGORA):
    linhas = normalizacoes + dm.abertas_como_normalizacao(abertas, normalizacoes)
    return dm.calcular({}, EQUIP, PER_INI, PER_FIM, agora=agora, normalizacoes=linhas, usinas_por_id=POR_ID)


def test_desligamento_aberto_conta_ate_o_fim_do_periodo_e_sai_em_aberto():
    r = roda_com_abertas([], [aberta("a1")])
    o = a_os(r, 16958)
    # 10/10 das 09:00 às 18:00 (9 h de sol) e de 11 a 31/10 inteiros (21 dias de 12 h): o período corta, o agora é 05/11
    assert o["excl"] is None and o["aberta"] is True and o["fim"] is None
    assert usina(r, "Alfa")["h_perdidas"] == pytest.approx(9 + 21 * 12)
    assert any("ocorrência aberta na Ronda COS" in a["motivo"] and "aguardando peça" in a["motivo"] for a in r["alinhar"])


def test_aberta_conta_ate_agora_dentro_do_mes():
    r = roda_com_abertas([], [aberta("a1", inicio="2026-10-20T08:00:00-03:00")], agora=datetime(2026, 10, 20, 12, 0))
    assert usina(r, "Alfa")["h_perdidas"] == pytest.approx(4.0)
    # aberta há menos de um dia: conta sem pedir o olho
    assert not r["alinhar"]


def test_inversor_aberto_conta_so_o_inversor():
    # a OS 16958 de Santarém (inversor 2.7 aguardando peça desde 12/07) é este caso: a fração do inversor, o mês todo
    r = roda_com_abertas([], [aberta("a1", tipo_falha="DESLIGAMENTO_INVERSOR", inicio="2026-07-12T08:00:00-03:00",
                                     equipamentos_codigos="THPN-ALF100-INVR1.1", equipamentos_qtd="1",
                                     equipamentos_de="ocorrencias")])
    assert a_os(r, 16958)["kwh"] == pytest.approx(300 * 12 * 31, rel=1e-3)
    assert usina(r, "Alfa")["disp"] == pytest.approx(100 * (1 - 0.3), abs=0.01)


def test_comunicacao_aberta_so_conta_quando_o_cos_responder():
    # a resposta "a geração parou?" vem na normalização: até lá fica fora, sem ir ao "alinhar"
    r = roda_com_abertas([], [aberta("a1", tipo_falha="FALHA_COMUNICACAO", protecoes="")])
    assert a_os(r, 16958)["excl"].startswith(dm.EXCL_COS_NAO_CONTA) and usina(r, "Alfa")["disp"] == 100
    assert not r["alinhar"]
    r = roda_com_abertas([], [aberta("a1", tipo_falha="FALHA_COMUNICACAO", geracao_parou="1", protecoes="")])
    assert a_os(r, 16958)["excl"] is None and usina(r, "Alfa")["disp"] < 100


def test_a_aberta_que_ja_normalizou_conta_uma_vez_pela_volta_do_cos():
    nr = [norm("a1", os="16958")]
    assert dm.abertas_como_normalizacao([aberta("a1"), aberta("a2")], nr) == [
        dict(aberta("a2"), normalizado_em="", normalizada="1", hora_real="1", aberta="1")]
    r = roda_com_abertas(nr, [aberta("a1")])
    o = a_os(r, 16958)
    assert o["aberta"] is False and o["h_solar"] == pytest.approx(6.0)
    # a normalização desfeita reabre: a ocorrência aberta conta
    assert len(dm.abertas_como_normalizacao([aberta("a1")], [norm("a1", normalizada="0")])) == 1


def test_a_os_com_uma_parte_normalizada_e_outra_aberta_segue_aberta():
    r = roda_com_abertas([norm("r1", os="16958")],
                         [aberta("a2", tipo_falha="DESLIGAMENTO_CABINE", equipamentos_codigos="THPN-ALF100-CABN2",
                                 inicio="2026-10-30T09:00:00-03:00")])
    o = a_os(r, 16958)
    assert o["aberta"] is True and o["fim"] is None
    # 6 h da usina inteira (a normalizada) e 21 h da cabine 2 (400 kWp de 1.000) de 30 a 31/10
    assert usina(r, "Alfa")["h_perdidas"] == pytest.approx(6 + 21 * 0.4)


@pytest.mark.normalizacoes_reais
def test_o_worker_le_as_abertas_e_confere_a_contagem(monkeypatch):
    import app

    class Leitor:
        def __init__(self, linhas):
            self._l = linhas

        def linhas(self):
            return self._l

    def leitores(atu, fato, ab):
        tabelas = {"atualizacao": atu, "fato_normalizacao": fato, "fato_ocorrencia_aberta": ab}
        monkeypatch.setattr(app, "_disp_cos_leitor", lambda aba, cab: Leitor(
            [[d.get(c, "") for c in cab] for d in tabelas[aba]] if tabelas[aba] is not None else None))

    monkeypatch.setattr(app, "_dpf_livro", lambda nome: Leitor(([{"x": 1}], None, None)))
    monkeypatch.setattr(app._dpf, "usinas_por_id", lambda reg, dp, equip: POR_ID)
    fato = [norm("r1")]
    leitores([{"linhas_qtd": "1", "abertas_qtd": "2"}], fato, [aberta("a1"), aberta("r1")])
    linhas, por_id, erro = app._disp_normalizacoes(EQUIP)
    # a aberta que já está nas normalizações sai; a outra vem com a marca de aberta
    assert erro == "" and [(x["registro"], x.get("aberta")) for x in linhas] == [("r1", None), ("a1", "1")]
    leitores([{"linhas_qtd": "1", "abertas_qtd": "3"}], fato, [aberta("a1")])
    assert "ocorrências abertas pela metade" in app._disp_normalizacoes(EQUIP)[2]
    # a gravação de antes das abertas (sem abertas_qtd): só as normalizações
    leitores([{"linhas_qtd": "1"}], fato, None)
    assert [x["registro"] for x in app._disp_normalizacoes(EQUIP)[0]] == ["r1"]
