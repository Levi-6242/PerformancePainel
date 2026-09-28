# -*- coding: utf-8 -*-
"""Falhas de strings — as fontes que a aba não lia (27/09/2026).

O cruzamento dos episódios com as OS do Fracttal achou 14 OS de recomposição que a aba não tinha como ver:
- 8 da Altair, que é String Box: a corrente por string vem da COMBINER e a régua lia só o Ipv do inversor (~0). A
  resposta da combiner (custom_query da API PV v2) já traz o DIA INTEIRO — o código guardava só a última leitura;
- 5 da fonte Banco de Dados da Thopen e 1 da RenoGrid, que não tinham gancho nenhum.
Cada teste trava um pedaço do caminho novo, sem chamada nova à API onde a resposta já vinha completa.
"""
import app

SERIE = [(f"{h:02d}:{m:02d}", 8.0) for h in range(7, 17) for m in (0, 10, 20, 30, 40, 50)]
ZERO = [(t, 0.0) for t, _ in SERIE]


# ── String Box: a curva da combiner ──────────────────────────────────────────────────────────────────────────────
DEVS = [{"device_id": 11, "device_type": "INVERTER", "device_esn": "ESN1", "device_name": "INVERSOR01"},
        {"device_id": 12, "device_type": "INVERTER", "device_esn": "ESN1@x", "device_name": "INVERSOR01 No"},
        {"device_id": 13, "device_type": "INVERTER", "device_esn": "ESN3", "device_name": "INVERSOR03"}]


def test_curva_da_combiner_sai_da_mesma_resposta_que_ja_traz_o_dia_inteiro():
    rows = [   # a v2 manda do mais novo para o mais velho
        {"idcombiner": 1, "conteudojson": {"sn": "CMBESN1", "tsleitura": "2026-09-27 10:02:00", "Ipv1": 9.4, "Ipv2": 0.0}},
        {"idcombiner": 1, "conteudojson": {"sn": "CMBESN1", "tsleitura": "2026-09-27 10:00:00", "Ipv1": 9.5, "Ipv2": 0.0}},
        {"idcombiner": 1, "conteudojson": {"sn": "CMBESN1", "tsleitura": "2026-09-26 17:00:00", "Ipv1": 1.0, "Ipv2": 0.0}},
        {"idcombiner": 2, "conteudojson": {"sn": "CMBOUTRO", "tsleitura": "2026-09-27 10:00:00", "Ipv1": 5.0}},
    ]
    c = app._pv_comb_curvas(rows, DEVS, "2026-09-27")
    assert c[11]["Ipv1"] == [("10:00", 9.5), ("10:02", 9.4)]       # em ordem, só do dia pedido
    assert c[12] == c[11]                                          # inversor cadastrado duas vezes (Tanabi 2)
    assert set(c) == {11, 12}                                      # combiner sem inversor no cadastro fica fora


def _cache_sb(monkeypatch, curvas, ts=1.0):
    monkeypatch.setitem(app._pv_comb_cache, 555, {"ts": ts, "por_inv": {}, "curvas": curvas, "dia": "2026-09-27"})
    monkeypatch.setattr(app, "_pv_plant_devices", lambda pid: DEVS)


def test_string_box_registra_a_regua_nova_com_a_curva_da_combiner(monkeypatch):
    monkeypatch.setattr(app, "_FALHAS_MORTAS", {})
    monkeypatch.setattr(app, "_falhas_comb_reg", {})
    _cache_sb(monkeypatch, {11: {"Ipv1": SERIE, "Ipv2": SERIE, "Ipv3": SERIE, "Ipv4": ZERO}})
    app._falhas_combiner({"id": 555, "nome": "Usina SB"})
    ent = app._FALHAS_MORTAS[("pvsb", "2026-09-27")]["555"]
    assert [m["string"] for m in ent["mortas"]] == ["Ipv4"]
    assert ent["ids"] == {"INVERSOR01": "11"} and ent["vivas"] == {"INVERSOR01": 3}


def test_string_box_nao_registra_a_string_trancada(monkeypatch):
    monkeypatch.setattr(app, "_FALHAS_MORTAS", {})
    monkeypatch.setattr(app, "_falhas_comb_reg", {})
    monkeypatch.setattr(app, "_trancadas", {"555|11|Ipv4"})
    _cache_sb(monkeypatch, {11: {"Ipv1": SERIE, "Ipv2": SERIE, "Ipv3": SERIE, "Ipv4": ZERO}})
    app._falhas_combiner({"id": 555, "nome": "Usina SB"})
    assert app._FALHAS_MORTAS[("pvsb", "2026-09-27")]["555"]["mortas"] == []


def test_string_box_so_registra_de_novo_quando_a_combiner_trouxe_leitura_nova(monkeypatch):
    # o build_summary passa por aqui a cada volta do worker (~5 min); a combiner só muda de hora em hora
    monkeypatch.setattr(app, "_FALHAS_MORTAS", {})
    monkeypatch.setattr(app, "_falhas_comb_reg", {})
    _cache_sb(monkeypatch, {11: {"Ipv1": SERIE, "Ipv2": SERIE, "Ipv3": SERIE, "Ipv4": ZERO}})
    app._falhas_combiner({"id": 555, "nome": "Usina SB"})
    app._FALHAS_MORTAS.clear()
    app._falhas_combiner({"id": 555, "nome": "Usina SB"})
    assert app._FALHAS_MORTAS == {}


# ── RenoGrid (SolarEdge): a série do dia que a tabela já baixa ──────────────────────────────────────────────────
SERIE15 = [(f"{h:02d}:{m:02d}", 9000.0) for h in range(7, 17) for m in (0, 15, 30, 45)]
ZERO15 = [(t, 0.0) for t, _ in SERIE15]
DEVS_SE = [{"deviceType": "INVERTER", "deviceSerial": "INV-A", "deviceName": "Inverter 1"},
           *[{"deviceType": "STRING", "deviceSerial": f"S{i}", "deviceName": f"String 1.{i}", "partOfSerial": "INV-A"}
             for i in range(1, 5)]]


def test_busca_da_tabela_da_renogrid_devolve_tambem_a_serie_do_dia(monkeypatch):
    class R:
        status_code = 200

        def json(self):
            return {"meta": {"datasetsMeta": [{"reportObject": {"entityId": "S1"}}]},
                    "data": [[["2026-09-01T10:00:00Z", 100, 9000.0], ["2026-09-01T10:15:00Z", 100, 9100.0]]]}

    class H:
        def post(self, *a, **k):
            return R()

    monkeypatch.setattr(app, "_http", lambda: H())
    monkeypatch.setattr(app, "_se_headers", lambda: {})
    power, _ts, falhos = app.se_string_power(1, ["S1"], "America/Fortaleza")
    assert power == {"S1": 9100.0} and falhos == 0
    assert app._se_serie_ultima[1] == {"S1": [("07:00", 9000.0), ("07:15", 9100.0)]}   # na hora da usina (UTC−3)


def test_renogrid_registra_a_curva_de_potencia_em_W_e_na_grade_de_15_min(monkeypatch):
    monkeypatch.setattr(app, "_FALHAS_MORTAS", {})
    monkeypatch.setattr(app, "_se_por_inversor", lambda sts: {"INV-A": sts})
    app._falhas_solaredge({"id": 4425864, "nome": "Usina SE Teste", "timezone": "America/Fortaleza"}, DEVS_SE,
                          {"S1": SERIE15, "S2": SERIE15, "S3": SERIE15, "S4": ZERO15})
    ((fonte, _dia), usinas), = app._FALHAS_MORTAS.items()
    ent = usinas["4425864"]
    assert fonte == "solaredge"
    assert [m["string"] for m in ent["mortas"]] == ["1.4"]
    assert ent["vivas"] == {"Inverter 1": 3} and ent["ids"] == {"Inverter 1": "INV-A"}


def test_renogrid_com_lote_falho_nao_registra_a_curva(monkeypatch):
    # lote que não voltou tira 50 strings da série: elas pareceriam mortas (a mesma regra que marca a usina SEM DADOS)
    monkeypatch.setattr(app, "_FALHAS_MORTAS", {})
    monkeypatch.setattr(app, "se_devices", lambda sid: DEVS_SE)

    def power(sid, uuids, tz):
        app._se_serie_ultima[sid] = {"S1": SERIE15}
        return {"S1": 9000.0}, "2026-09-28T13:00:00Z", 1

    monkeypatch.setattr(app, "se_string_power", power)
    app.process_site_solaredge({"id": 4425864, "nome": "Usina SE Teste", "timezone": "America/Fortaleza"})
    assert app._FALHAS_MORTAS == {}


# ── Banco de Dados da Thopen: a curva do dia por usina, de 2 em 2 h ──────────────────────────────────────────────
def test_banco_monta_a_curva_do_dia_com_o_nome_do_cadastro_e_sem_a_trancada(monkeypatch):
    from datetime import datetime
    monkeypatch.setattr(app, "_trancadas", {"31|67|2"})
    t = lambda h, m: datetime(2026, 9, 28, h, m)
    recs = [(67, "INV 01", "Usina PG Teste", 1, t(10, 5), 8.1), (67, "INV 01", "Usina PG Teste", 1, t(10, 0), 8.0),
            (67, "INV 01", "Usina PG Teste", 2, t(10, 0), 0.0), (68, "INV 02", "Usina PG Teste", 1, t(10, 0), 7.9)]
    curvas, ids = app._falhas_pg_monta(recs, 31)
    assert curvas == {"INV 01": {"ST 01": [("10:00", 8.0), ("10:05", 8.1)]}, "INV 02": {"ST 01": [("10:00", 7.9)]}}
    assert ids == {"INV 01": 67, "INV 02": 68}


def test_banco_varre_de_duas_em_duas_horas_de_dia_e_fecha_o_dia_depois_das_18h30(monkeypatch):
    # uma consulta por usina (~1–2,5 s, 22 usinas): de hora em hora seria carga à toa no banco da Thopen
    from datetime import datetime
    monkeypatch.setattr(app, "_FALHAS_MORTAS", {})
    monkeypatch.setattr(app, "_falhas_pg_ult", {"em": None, "final": None})
    monkeypatch.setitem(app._pg_cache, "summary", [{"plant_id": 31, "usina": "Santarém 1"}])
    chamadas = []
    monkeypatch.setattr(app, "_falhas_pg_consulta", lambda pid, dia: chamadas.append((pid, dia)) or [])
    for h, m in ((6, 30), (8, 0), (9, 0), (10, 5), (18, 45), (19, 30)):
        app._falhas_pg_varre(datetime(2026, 9, 28, h, m))
    assert chamadas == [(31, "2026-09-28")] * 3          # 08:00, 10:05 e 18:45 (fecha o dia)
    assert app._FALHAS_MORTAS == {}                       # consulta vazia não é "usina sem falha": não registra


def test_banco_sem_o_snapshot_pronto_nao_marca_a_varredura(monkeypatch):
    # o laço da aba roda 7 min depois do boot e o snapshot do Banco pode ainda não ter saído: sem usina para varrer, a
    # volta seguinte tenta de novo (antes, marcava a hora e a próxima varredura só vinha 2 h depois)
    from datetime import datetime
    monkeypatch.setattr(app, "_FALHAS_MORTAS", {})
    monkeypatch.setattr(app, "_falhas_pg_ult", {"em": None, "final": None})
    chamadas = []
    monkeypatch.setattr(app, "_falhas_pg_consulta", lambda pid, dia: chamadas.append(pid) or [])
    monkeypatch.setitem(app._pg_cache, "summary", None)
    app._falhas_pg_varre(datetime(2026, 9, 28, 8, 0))
    monkeypatch.setitem(app._pg_cache, "summary", [{"plant_id": 31, "usina": "Santarém 1"}])
    app._falhas_pg_varre(datetime(2026, 9, 28, 8, 30))
    assert chamadas == [31]
