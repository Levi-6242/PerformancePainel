# -*- coding: utf-8 -*-
"""scadaGridco como fonte (06/10/2026, Levi: "OS para tempo real e histórico das UFVs da Green Yellow"; "separe green
yellow e sal energia"; "só até 45 dias tá bom"). Os pacotes abaixo têm o formato que a API devolveu de verdade em
06/10/2026 (Irecê 2 pelo gateway MQTT, Boa Esperança do Sul pelo Modbus), cortados."""
import pytest

import scadagridco as sg


def _eq_mqtt(equip, fault=192, stale=False, **m):
    base = {"active_power": 3.247, "total_daily_energy": 1780.35, "temperature_current": 48.5,
            "serial_number": "6T22C9013326", "string_current_01": 0.53, "string_current_02": 0.35,
            "string_current_15": 0.0}
    base.update(m)
    return {"alarmes": [], "communication_fault": fault, "device_type": "Huawei SUN2000 (mapa nativo)",
            "equipamento": str(equip), "falha_comunicacao": fault != 192, "indice": int(equip), "stale": stale,
            "tipo": "inverter", "ts": 1791318738.0, "measurements": base}


def test_leitura_mqtt_normaliza_strings_potencia_e_energia():
    x = sg.leitura_mqtt(_eq_mqtt(1))
    assert x["ok"] and x["equip"] == "1" and x["pot_kw"] == 3.247 and x["eday"] == 1780.35 and x["temp"] == 48.5
    assert x["strings"] == {1: 0.53, 2: 0.35, 15: 0.0}


def test_leitura_ruim_nao_vira_zero():
    """communication_fault 28 (ou stale): lacuna é sem comunicação, não string morta."""
    for eq in (_eq_mqtt(2, fault=28), _eq_mqtt(2, stale=True)):
        x = sg.leitura_mqtt(eq)
        assert not x["ok"] and x["strings"] == {} and x["pot_kw"] is None and x["eday"] is None


def test_gateway_novo_escreve_string_n_current():
    assert sg.strings_de({"string_1_current": 9.1, "string_12_current": None, "daily_active_energy": 1}) == \
        {1: 9.1, 12: None}


def test_leitura_modbus_em_kw_e_timeout_sem_valor():
    boa = {"label": "INV 01", "slave_id": 1, "read_error": None, "stale": False, "updated_at": 1791319445.0,
           "measurements": {"active_power_w": 66100.0, "daily_energy_kwh": 889.3, "internal_temperature_c": 41.0,
                            "string_01_i": 7.2, "string_02_i": 0.0}}
    x = sg.leitura_modbus(boa)
    assert x["ok"] and x["pot_kw"] == pytest.approx(66.1) and x["strings"] == {1: 7.2, 2: 0.0} and x["equip"] == "1"
    # Sal Energia em 06/10/2026: todos os inversores assim, desde pelo menos 17/09
    hort = {"label": "INV 01", "slave_id": 1, "read_error": "TimeoutError: timed out", "stale": True,
            "updated_at": 0.0, "measurements": {}}
    y = sg.leitura_modbus(hort)
    assert not y["ok"] and y["ts"] is None and y["strings"] == {}


def test_de_para_da_irece_2_segue_a_ordem_natural_desde_outubro():
    """Por valor contra o BD_Performance em 01, 05 e 09/10/2026 (10/10): o equipamento N é o Inversor 1.N. O de-para de
    27 a 30/09 (4 = 1.8, 7 = 1.4) só batia em setembro."""
    cfg = sg.usina_cfg("greenyellow", "irece_2")
    assert sg.nome_inversor(cfg, "4") == "Inversor 1.4" and sg.nome_inversor(cfg, "7") == "Inversor 1.7"
    assert sorted(cfg["inversores"].values(), key=sg.ordem_par) == [f"Inversor 1.{i}" for i in range(1, 11)]
    dem = sg.usina_cfg("greenyellow", "dermeval_lobao")
    assert len(dem["inversores"]) == 12 and sg.nome_inversor(dem, "12") == "Inversor 1.12"   # só a UG 01


def test_sal_energia_vai_pela_ordem_do_cadastro_ate_confirmar():
    cfg = sg.usina_cfg("salenergia", "sunpower")
    cad = ["Inversor 2.1", "Inversor 1.2", "Inversor 6.3", "Inversor 1.1"]
    assert sg.nome_inversor(cfg, "1", cad) == "Inversor 1.1" and sg.nome_inversor(cfg, "3", cad) == "Inversor 2.1"
    assert sg.nome_inversor(cfg, "9", cad) is None


def test_curva_mqtt_so_com_leitura_boa():
    regs = [{"communication_fault": 192, "data_hora": "2026-10-06 10:00:40", "ts": 100.0, "equipamento": "1",
             "pontos": {"string_current_01": 9.0, "string_current_02": None, "active_power": 190.0}},
            {"communication_fault": 28, "data_hora": "2026-10-06 10:01:40", "ts": 160.0, "equipamento": "1",
             "pontos": {"string_current_01": 0.0}},
            {"communication_fault": 192, "data_hora": "2026-10-06 10:02:40", "ts": 220.0, "equipamento": "1",
             "pontos": {"string_current_01": 9.2, "string_current_02": 9.1}}]
    c = sg.curva_mqtt(regs)
    assert c["strings"] == {1: [("10:00", 9.0), ("10:02", 9.2)], 2: [("10:02", 9.1)]}
    assert c["pot"] == [("10:00", 190.0)] and c["ultimo_ts"] == 220.0


def test_curva_modbus_por_string():
    regs = [{"current_a": 0.0, "data_hora": "2026-10-06 06:03:07", "slave_id": 1, "string_num": 1, "ts": 1.0},
            {"current_a": 4.5, "data_hora": "2026-10-06 08:03:07", "slave_id": 1, "string_num": 1, "ts": 2.0},
            {"current_a": None, "data_hora": "2026-10-06 08:03:07", "slave_id": 1, "string_num": 2, "ts": 2.0}]
    assert sg.curva_modbus(regs)["strings"] == {1: [("06:03", 0.0), ("08:03", 4.5)]}


def test_curva_de_hoje_busca_so_o_que_chegou_depois(monkeypatch):
    """A doc pede busca incremental: a 2ª busca do dia vai com apos_ts = o último carimbo guardado."""
    monkeypatch.setattr(sg, "hoje", lambda: "2026-10-06")
    pedidos = []

    def getter(rota, p):
        pedidos.append(dict(p))
        t0 = p.get("apos_ts") or 0.0
        return {"registros": [{"communication_fault": 192, "data_hora": f"2026-10-06 10:0{int(t0)}:00",
                               "ts": t0 + 1, "equipamento": "3", "pontos": {"string_current_01": 5.0}}],
                "proximo_apos_ts": None}
    cd = sg.CurvasDoDia()
    a = cd.curva("greenyellow", "irece_2", "3", "2026-10-06", getter=getter, agora=1000.0)
    b = cd.curva("greenyellow", "irece_2", "3", "2026-10-06", getter=getter, agora=1100.0)   # dentro dos 5 min
    c = cd.curva("greenyellow", "irece_2", "3", "2026-10-06", getter=getter, agora=1400.0)
    assert len(pedidos) == 2 and pedidos[0].get("apos_ts") is None and pedidos[1]["apos_ts"] == 1.0
    # pelo NOME do equipamento desde 11/10/2026 (o `indice` não filtra quem tem nome, como a "inversor-01" da Cedro)
    assert pedidos[0]["equipamento"] == "3" and pedidos[0]["tipo"] == "inverter"
    assert a is b and [v for _t, v in c["strings"][1]] == [5.0, 5.0] and c["ultimo_ts"] == 2.0


def test_pagina_segue_o_proximo_apos_ts():
    paginas = iter([{"registros": [{"slave_id": 2, "string_num": 1, "current_a": 1.0, "ts": 1.0,
                                    "data_hora": "2026-10-01 09:00:00"}], "proximo_apos_ts": 1.0},
                    {"registros": [{"slave_id": 2, "string_num": 1, "current_a": 2.0, "ts": 2.0,
                                    "data_hora": "2026-10-01 09:05:00"}], "proximo_apos_ts": None}])
    c = sg.curva_inversor("salenergia", "hortina", "2", "2026-10-01", getter=lambda r, p: next(paginas))
    assert c["strings"] == {1: [("09:00", 1.0), ("09:05", 2.0)]}


def test_sem_token_nao_vai_a_rede(monkeypatch):
    monkeypatch.delenv("SCADAGRIDCO_TOKEN", raising=False)
    monkeypatch.setattr(sg._SESSAO, "get", lambda *a, **k: pytest.fail("foi à rede sem token"))
    with pytest.raises(sg.SemAcesso):
        sg.get("/api/usinas")


def test_token_recusado_e_302(monkeypatch):
    monkeypatch.setenv("SCADAGRIDCO_URL", "https://exemplo/supervisorio")
    monkeypatch.setenv("SCADAGRIDCO_TOKEN", "x")

    class R:
        status_code = 302
    monkeypatch.setattr(sg._SESSAO, "get", lambda *a, **k: R())
    with pytest.raises(sg.SemAcesso):
        sg.get("/api/usinas")


def test_rio_do_peixe_o_15_e_copia_do_14_e_fica_de_fora():
    """Apolo (29/10/2026): 21 equipamentos no supervisório e 20 inversores no cadastro. O 15 repete o 14 minuto a minuto
    (315 de 316 com sol em 28/10/2026); pelo padrão das strings (20/18/20 por UG) o 11 a 14 são o 2.1 a 2.4 e o 16 a 21
    o 2.5 a 2.10. O que não está no de-para não vira inversor da usina."""
    cfg = sg.usina_cfg("apolo", "rio_do_peixe_1_2")
    assert sg.via("apolo", "rio_do_peixe_1_2") == "mqtt" and cfg["usina"] == "Rio do Peixe I e II"
    assert [sg.nome_inversor(cfg, str(e)) for e in (1, 10, 11, 14, 15, 16, 21)] == \
        ["Inversor 1.1", "Inversor 1.10", "Inversor 2.1", "Inversor 2.4", None, "Inversor 2.5", "Inversor 2.10"]
    assert len(set(cfg["inversores"].values())) == 20 and cfg.get("provisorio")


def test_temperatura_interna_do_gateway_da_apolo():
    eq = _eq_mqtt(3)
    del eq["measurements"]["temperature_current"]
    eq["measurements"]["temperature_internal"] = 41.5
    assert sg.leitura_mqtt(eq)["temp"] == 41.5
    assert sg.leitura_mqtt(_eq_mqtt(3))["temp"] == 48.5                 # a da GreenYellow segue valendo


def test_curva_da_ncu_angulo_alvo_e_falhas():
    """A NCU da Rio do Peixe (29/10/2026, Levi: "traga a NCU como tracker também e nomeie como NCU"): posat = ângulo,
    posal = alvo, as falhas em 0/1 da última leitura boa. Leitura ruim fica fora (lacuna não é zero)."""
    regs = [{"communication_fault": 192, "data_hora": "2026-10-28 12:07:30", "ts": 2.0, "equipamento": "1",
             "pontos": {"posat": 12.05, "posal": 12.17, "flh_com": 1, "flh_leve": 0, "out_of_range": 0}},
            {"communication_fault": 28, "data_hora": "2026-10-28 12:08:30", "ts": 3.0, "equipamento": "1",
             "pontos": {"posat": 0.0, "posal": 0.0, "flh_com": 0}},
            {"communication_fault": 192, "data_hora": "2026-10-28 12:06:30", "ts": 1.0, "equipamento": "1",
             "pontos": {"posat": 11.8, "posal": None, "flh_com": 0}}]
    c = sg.curva_ncu(regs)
    assert [round(v, 2) for _t, v in c["atual"]] == [11.8, 12.05] and [v for _t, v in c["alvo"]] == [12.17]
    assert c["atual"][0][0].strftime("%H:%M") == "12:06" and c["ultimo_ts"] == 3.0
    assert c["alarmes"] == {"flh_com": 1, "flh_leve": 0, "out_of_range": 0}        # a da 12:07 (a 12:08 é ruim)
    assert sg.trackers(sg.usina_cfg("apolo", "rio_do_peixe_1_2")) == {"1": "NCU"}
    assert sg.trackers(sg.usina_cfg("greenyellow", "irece_2")) == {}


def test_curva_da_ncu_pede_o_tipo_tracker_ncu_pelo_nome():
    pedidos = []

    def getter(rota, p):
        pedidos.append((rota, dict(p)))
        return {"registros": [], "proximo_apos_ts": None}
    sg.curva_tracker("apolo", "rio_do_peixe_1_2", "1", "2026-10-28", getter=getter)
    assert pedidos == [("/api/telemetria", {"usina": "rio_do_peixe_1_2", "desde": "2026-10-28", "ate": "2026-10-28",
                                            "tipo": "tracker_ncu", "equipamento": "1", "limit": sg.LIMITE})]
