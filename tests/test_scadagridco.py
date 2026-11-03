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


# ── Trackers pela API de rastreadores (03/11/2026, Levi: "já adapta para a plataforma") ─────────────────────────────
# Os pacotes têm o formato que `/api/trackers/<usina>` e `/api/trackers/<usina>/historico` devolveram em 03/11/2026.
from datetime import datetime  # noqa: E402


def _epoch(dia, hhmm):
    return datetime.strptime(f"{dia} {hhmm}", "%Y-%m-%d %H:%M").replace(tzinfo=sg.TZ).timestamp()


def test_historico_vira_curva_com_o_ponto_no_fim_do_balde():
    """O valor do instante é a última leitura do balde [instante, instante + 15 min): conferido contra a API PV na
    Araputanga (02/11/2026), 3,56° de diferença média com o rótulo da API e 0,57° no fim do balde. Nulo fica fora; o
    último balde do dia fica em 23:59 do mesmo dia; o balde em curso não passa do agora."""
    d = {"dia": "2026-11-02", "passo_min": 15,
         "instantes": [_epoch("2026-11-02", h) for h in ("06:00", "06:15", "06:30", "23:45")],
         "alvo": [-50.0, None, -45.0, 0.0],
         "trackers": [{"equipamento": "1", "posicao": [-49.5, -47.0, None, 0.0]},
                      {"equipamento": "2", "posicao": [None, None, None, None]}]}
    c = sg.curvas_historico(d)
    assert [(t.strftime("%H:%M"), v) for t, v in c["1"]["atual"]] == [("06:15", -49.5), ("06:30", -47.0),
                                                                      ("23:59", 0.0)]
    assert c["1"]["atual"][-1][0].strftime("%Y-%m-%d") == "2026-11-02"
    assert [(t.strftime("%H:%M"), v) for t, v in c["1"]["alvo"]] == [("06:15", -50.0), ("06:45", -45.0), ("23:59", 0.0)]
    assert c["2"]["atual"] == [] and c["2"]["alvo"] == c["1"]["alvo"]            # o alvo é UM, o da usina
    c = sg.curvas_historico(d, ate=_epoch("2026-11-02", "06:20"))
    assert [t.strftime("%H:%M") for t, _v in c["1"]["atual"][:2]] == ["06:15", "06:20"]


def test_agora_le_o_supervisorio_e_stale_e_sem_comunicacao():
    pedidos = []
    pacote = {"total": 3, "trackers": [
        {"equipamento": "tracker-ncu1-001", "posicao_atual": -37.97, "posicao_alvo": -37.71, "sem_comunicacao": False,
         "stale": False, "alarmes": [], "ts": 1793706955.0},
        {"equipamento": "tracker-ncu1-002", "posicao_atual": 0.0, "posicao_alvo": 0.0, "sem_comunicacao": False,
         "stale": True, "alarmes": ["bat_crit"], "ts": 1793644959.0},
        {"equipamento": "tracker-ncu1-003", "posicao_atual": None, "posicao_alvo": None, "sem_comunicacao": True,
         "stale": False, "alarmes": [], "ts": None}]}

    def getter(rota, p=None):
        pedidos.append((rota, p))
        return pacote
    ag = sg.trackers_agora("apolo", "rio_do_peixe_1_2", getter=getter)
    assert pedidos == [("/api/trackers/rio_do_peixe_1_2", None)]
    assert [(t["equip"], t["atual"], t["sem_comunicacao"], t["alarmes"]) for t in ag] == [
        ("tracker-ncu1-001", -37.97, False, []), ("tracker-ncu1-002", 0.0, True, ["bat_crit"]),
        ("tracker-ncu1-003", None, True, [])]


def test_historico_pede_passo_5_pela_chave_do_supervisorio_e_guarda(monkeypatch):
    """Uma chamada por usina do SUPERVISÓRIO e dia: a Cedro 1 e a Cedro 2 são a "cedro", e o de hoje vale 15 min. Passo 5:
    em 03/11/2026 o de 15 dava 96 parados na Castelo do Piauí, contra 84 com o de 5 e o de 1 (os mesmos)."""
    monkeypatch.setattr(sg, "ATUALIZAR", None)
    monkeypatch.setattr(sg, "EXTRAS", {"greenyellow": [
        {"id": "cedro_1", "scada": "cedro", "usina": "Cedro 1", "via": "mqtt"},
        {"id": "cedro_2", "scada": "cedro", "usina": "Cedro 2", "via": "mqtt"}]})
    pedidos = []

    def getter(rota, p=None):
        pedidos.append((rota, dict(p or {})))
        return {"instantes": [], "alvo": [], "trackers": []}
    h, t0 = sg.HistoricoTrackers(), 1_000_000.0
    hoje = sg.hoje()
    h.curvas("greenyellow", "cedro_1", hoje, getter=getter, agora=t0)
    h.curvas("greenyellow", "cedro_2", hoje, getter=getter, agora=t0 + 60)
    assert pedidos == [("/api/trackers/cedro/historico", {"dia": hoje, "passo": 5})]
    h.curvas("greenyellow", "cedro_1", hoje, getter=getter, agora=t0 + 14 * 60)
    assert len(pedidos) == 1
    h.curvas("greenyellow", "cedro_1", hoje, getter=getter, agora=t0 + 15 * 60)    # passaram os 15 min: pede de novo
    assert len(pedidos) == 2 and sg.TRK_PASSO_MIN == 5


def test_junta_agora_poe_o_ponto_novo_so_de_quem_le():
    t = lambda h: datetime.strptime(f"2026-11-03 {h}", "%Y-%m-%d %H:%M")      # noqa: E731
    curvas = {"1": {"atual": [(t("08:45"), -40.0)], "alvo": [(t("08:45"), -40.5)]}}
    agora = [{"equip": "1", "atual": -38.0, "alvo": -38.4, "sem_comunicacao": False, "ts": _epoch("2026-11-03", "08:57")},
             {"equip": "2", "atual": 0.0, "alvo": 0.0, "sem_comunicacao": True, "ts": _epoch("2026-11-02", "15:42")}]
    j = sg.junta_agora(curvas, agora)
    assert j["1"]["atual"] == [(t("08:45"), -40.0), (t("08:57"), -38.0)] and j["1"]["alvo"][-1] == (t("08:57"), -38.4)
    assert j["2"] == {"atual": [], "alvo": []}                                  # sem comunicação: entra, sem ponto velho
    assert curvas["1"]["atual"] == [(t("08:45"), -40.0)]                        # não mexe no guardado
    j = sg.junta_agora(curvas, [dict(agora[0], ts=_epoch("2026-11-03", "08:40"))])
    assert j["1"]["atual"] == [(t("08:45"), -40.0)]                             # mais velho que o histórico: fica fora


def test_rio_do_peixe_sem_a_ncu_unica_de_29_10():
    """Desde 03/11/2026 o supervisório manda os 96 trackers do campo: a NCU única ("1" = "NCU") saiu da configuração."""
    assert "trackers" not in sg.usina_cfg("apolo", "rio_do_peixe_1_2")
    assert not hasattr(sg, "curva_ncu") and set(sg.TIPOS_TRACKER) == {"tracker", "tracker_ncu", "tcu", "rsu"}
