# -*- coding: utf-8 -*-
"""Histórico do mês POR INVERSOR (07/09/2026) — "ver o histórico melhor daquele inversor: geração, PR, meta do dia
alcançada de acordo com IPOA" (Levi). Uma régua só, dia a dia, para o Raio-X e o Diagnóstico v2:
  geração: Thopen → aba diária do BD_Thopen; demais → aba da usina no BD_Performance (as duas únicas bases, 08/09);
  IPOA e metas da usina: a mesma base diária da cascata (/api/g/diario);
  fatia do inversor: potência do Equipamentos → partes iguais; PR = ger ÷ (IPOA × pot); meta pelo IPOA = pot × IPOA × PR meta."""
import pytest

import app


class _R:
    def __init__(self, d):
        self.d = d

    def get_json(self):
        return self.d


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    return app.app.test_client()


def _sem_outras_fontes(monkeypatch):
    monkeypatch.setattr(app, "_bdperf_inv_dias", lambda u, a, m: {})
    monkeypatch.setattr(app, "_pv_pr_cache", {"detail": {}})
    monkeypatch.setattr(app, "_pot_inv", lambda *a, **k: None)      # cadastro real fora do teste


def test_pg_dia_a_dia_com_ipoa_meta_e_pr(monkeypatch):
    monkeypatch.setattr(app, "api_g_diario", lambda: _R({"pontos": [{"dia": 1, "geracao": 4.0, "poa": 5.0}, {"dia": 2, "geracao": 3.0, "poa": 2.5}],
                                                          "meta": 0.8, "pot": 1.0, "meta_ger": 4.8, "meta_poa": 6.0}))
    monkeypatch.setattr(app, "INFO_GERAL", {app._nrm("Ipixuna 1"): {"cliente": "Thopen"}})
    monkeypatch.setattr(app, "_bdthopen_inv_dias", lambda u, a, m: {
        "2026-09-01": {"ipoa": 5.0, "inv": {"INV 1": 2400.0, "INV 2": 1600.0}},
        "2026-09-02": {"ipoa": 2.5, "inv": {"INV 1": 1200.0}},
        "2026-09-07": {"ipoa": 1.0, "inv": {"INV 1": 100.0, "INV 2": 100.0}}} if u == "Ipixuna 1" else {})
    monkeypatch.setattr(app, "_pg_pr_get", lambda dia, force=False: ([], {20: [
        {"id": 171, "nome": "Inversor 1.1", "nome_api": "INV 1", "pot_kwp": 600.0},
        {"id": 172, "nome": "Inversor 1.2", "nome_api": "INV 2", "pot_kwp": 400.0}]}))
    _sem_outras_fontes(monkeypatch)
    d = app._inv_historico("pg", 20, "Ipixuna 1", 2026, 9, agora=app.datetime(2026, 9, 7, 15, 0))
    assert [x["data"] for x in d["dias"]] == ["2026-09-01", "2026-09-02"]        # o dia em curso (15h) fica de fora
    d1 = d["dias"][0]
    assert d1["ipoa"] == 5.0 and d1["origem"] == "bd_thopen"
    i11 = d1["inv"]["Inversor 1.1"]                                             # nome da fonte virou nome de exibição
    assert i11["ger"] == 2400.0 and i11["pr"] == 0.8                            # 2400 ÷ (5 × 600)
    assert i11["meta"] == 2880.0                                                 # 4.800 kWh/dia × 600/1000 (fatia por potência)
    assert i11["meta_ipoa"] == 2400.0                                            # 600 × 5 × 0,8
    assert d["dias"][1]["inv"]["Inversor 1.1"]["meta_ipoa"] == 1200.0 and "Inversor 1.2" not in d["dias"][1]["inv"]
    m = d["inversores"]["Inversor 1.1"]
    assert (m["ger"], m["dias"], m["meta"], m["pct_meta"], m["pct_ipoa"]) == (3600.0, 2, 5760.0, 62.5, 100.0)
    assert m["pr"] == 0.8                                                        # 3600 ÷ ((5 + 2,5) × 600)
    assert d["inversores"]["Inversor 1.2"]["dias"] == 1 and d["rateio"] == "potencia" and d["tem_base"] is True
    assert d["meta_dia_kwh"] == 4800.0 and d["pr_meta"] == 0.8
    # depois das 19h o dia em curso conta
    d2 = app._inv_historico("pg", 20, "Ipixuna 1", 2026, 9, agora=app.datetime(2026, 9, 7, 21, 0))
    assert d2["dias"][-1]["data"] == "2026-09-07" and d2["dias"][-1]["ipoa"] == 1.0   # IPOA do dia veio da própria aba
    # de manhã o PR de hoje ainda está vazio: a potência (e a fatia da meta) vem do cadastro, não da hora do dia
    monkeypatch.setattr(app, "_pg_pr_get", lambda dia, force=False: ([], {}))
    monkeypatch.setattr(app, "_pot_inv", lambda u, a, b=None: {"INV 1": 600.0, "INV 2": 400.0}.get(a))
    d3 = app._inv_historico("pg", 20, "Ipixuna 1", 2026, 9, agora=app.datetime(2026, 9, 7, 8, 0))
    assert d3["rateio"] == "potencia" and d3["inversores"]["INV 1"]["meta"] == 5760.0   # 2 dias × 4.800 × 0,6; nome = o da fonte


def test_pv_le_a_aba_do_bd_performance(monkeypatch):
    monkeypatch.setattr(app, "api_g_diario", lambda: _R({"pontos": [{"dia": 5, "geracao": 1.0, "poa": 4.0}], "meta": 0.75, "pot": 0.5, "meta_ger": 2.0, "meta_poa": 5.0}))
    monkeypatch.setattr(app, "INFO_GERAL", {})
    monkeypatch.setattr(app, "_bdperf_inv_dias", lambda u, a, m: {
        "2026-09-05": {"ipoa": 4.0, "inv": {"Inversor 1.1": 900.0, "Inversor 1.2": 800.0}},
        "2026-09-06": {"ipoa": None, "inv": {"Inversor 1.1": 700.0, "Inversor 1.2": 650.0}}})
    monkeypatch.setattr(app, "_pv_pr_cache", {"detail": {}})
    monkeypatch.setattr(app, "_pot_inv", lambda *a, **k: None)                  # usina fora do Equipamentos
    d = app._inv_historico("pv", 123, "Usina X", 2026, 9, agora=app.datetime(2026, 9, 7, 21, 0))
    assert [(x["data"], x["origem"]) for x in d["dias"]] == [("2026-09-05", "bd_performance"), ("2026-09-06", "bd_performance")]
    assert d["dias"][1]["ipoa"] is None and d["dias"][1]["inv"]["Inversor 1.1"]["pr"] is None   # sem IPOA: energia sim, PR não
    assert d["rateio"] == "igual" and d["inversores"]["Inversor 1.1"]["pot_kwp"] == 250.0        # 500 kWp ÷ 2 (régua do pr-mes)
    x = d["dias"][0]["inv"]["Inversor 1.1"]
    assert (x["pr"], x["meta"], x["meta_ipoa"]) == (0.9, 1000.0, 750.0)         # 900÷(4×250) · 2.000÷2 · 250×4×0,75
    assert d["inversores"]["Inversor 1.1"]["meta"] == 2000.0                     # 2 dias com dado × 1.000
    # % IPOA compara os MESMOS dias: só o dia 05 tem IPOA → 900 ÷ 750, e não (900+700) ÷ 750
    assert d["inversores"]["Inversor 1.1"]["pct_ipoa"] == 120.0 and d["motivo"] is None


def test_base_com_nan_nao_vaza_para_o_json(monkeypatch):
    """A base diária vem do pandas e manda NaN onde não há cadastro (Ipixuna 2): virava `NaN` no JSON e o parse quebrava."""
    import json
    nan = float("nan")
    monkeypatch.setattr(app, "api_g_diario", lambda: _R({"pontos": [{"dia": 1, "geracao": 1.0, "poa": nan}], "meta": nan, "pot": nan, "meta_ger": nan, "meta_poa": nan}))
    monkeypatch.setattr(app, "INFO_GERAL", {})
    monkeypatch.setattr(app, "_bdthopen_inv_dias", lambda u, a, m: {"2026-09-01": {"ipoa": None, "inv": {"Inversor 2.1": 775.2}}})
    # potência do inversor também pode vir NaN do cadastro — e NaN é truthy: passava no all() e sujava a fatia da meta
    monkeypatch.setattr(app, "_pg_pr_get", lambda dia, force=False: ([], {33: [{"id": 181, "nome": "Inversor 2.1", "nome_api": "Inversor 2.1", "pot_kwp": nan}]}))
    _sem_outras_fontes(monkeypatch)
    d = app._inv_historico("pg", 33, "Ipixuna 2", 2026, 9, agora=app.datetime(2026, 9, 7, 21, 0))
    x = d["dias"][0]
    assert x["ipoa"] is None                                                     # aba sem IPOA = sem medição, não "sem sol"
    assert x["inv"]["Inversor 2.1"] == {"ger": 775.2, "pr": None, "meta": None, "meta_ipoa": None}
    assert d["rateio"] == "igual" and d["inversores"]["Inversor 2.1"]["pot_kwp"] is None
    assert d["pot_kwp"] is None and d["pr_meta"] is None and d["meta_dia_kwh"] is None and d["ipoa_meta_dia"] is None
    json.dumps(d, allow_nan=False)                                               # nada de NaN no payload
    assert app._fin("x") is None and app._fin(float("inf")) is None and app._fin("2.5") == 2.5


def test_solaredge_le_a_mesma_aba_e_sem_aba_diz_o_motivo(monkeypatch):
    """RenoGrid não tem tratamento próprio: lê o BD_Performance como as outras (o render-chart do mês saiu em 08/09)."""
    monkeypatch.setattr(app, "api_g_diario", lambda: _R({"pontos": [], "meta": None, "pot": None, "meta_ger": None, "meta_poa": None}))
    monkeypatch.setattr(app, "INFO_GERAL", {})
    _sem_outras_fontes(monkeypatch)
    monkeypatch.setattr(app, "_se_pr_get", lambda dia, force=False: ([], {4425864: [{"id": "7B0C4F8D", "nome": "Inversor 1.1", "nome_api": "Inverter 1", "pot_kwp": 123.0}]}))
    monkeypatch.setattr(app, "_bdperf_inv_dias", lambda u, a, m: {"2026-09-06": {"ipoa": 6.1, "inv": {"Inversor 1.1": 572.2}}} if u == "Colider 1" else {})
    d = app._inv_historico("solaredge", 4425864, "Colider 1", 2026, 9, agora=app.datetime(2026, 9, 7, 12, 0))
    x = d["dias"][0]
    assert x["origem"] == "bd_performance" and x["ipoa"] == 6.1 and x["inv"]["Inversor 1.1"]["ger"] == 572.2
    assert x["inv"]["Inversor 1.1"]["pr"] == round(572.2 / (6.1 * 123.0), 3) and x["inv"]["Inversor 1.1"]["meta"] is None   # sem P50: sem meta
    assert d["tem_base"] is False and d["inversores"]["Inversor 1.1"]["pct_meta"] is None and d["motivo"] is None
    # usina sem aba: nada de histórico, e o payload diz POR QUÊ (a tela mostra isso no lugar do vazio)
    v = app._inv_historico("solaredge", 4425864, "Nobres", 2026, 9, agora=app.datetime(2026, 9, 7, 12, 0))
    assert v["dias"] == [] and v["inversores"] == {} and "Nobres" in v["motivo"] and "BD_Performance" in v["motivo"]
    assert "BD_Thopen" in app._inv_sem_base("pg", "Ipixuna 1") and "Ipixuna 1" in app._inv_sem_base("pg", "Ipixuna 1")


def test_rota_normaliza_fonte_e_cacheia(cliente, monkeypatch):
    chamadas = []
    monkeypatch.setattr(app, "_inv_historico", lambda f, p, u, a, m, agora=None: chamadas.append((f, p, u, a, m)) or {"dias": [], "inversores": {}})
    monkeypatch.setattr(app, "_inv_hist_cache", {})
    for _ in range(2):
        assert cliente.get("/api/athon/inversores/historico/CPP100?usina=Cora%C3%A7%C3%A3o%202&mes=2026-09").status_code == 200
    assert chamadas == [("athon", "CPP100", "Coração 2", 2026, 9)]              # a 2ª veio do cache
    assert cliente.get("/api/pg/inversores/historico/20?mes=09-2026").status_code == 400
    assert app._INV_HIST_FONTE.get("athon") == "sunop" and app._INV_HIST_FONTE.get("2c") == "owen"


def test_leitor_do_bd_thopen_acha_a_aba_pela_chave_tolerante_e_so_dias_fechados(monkeypatch):
    """'Piracicaba I' na plataforma é 'Piracicaba 1' na coluna Usina da aba; dia em curso e outro mês ficam de fora;
    célula vazia é ausência (linha pré-criada), IPOA zero é "sem medição"."""
    import datetime as dt
    import dashboard_thopen as D
    hoje = dt.date.today()
    ontem, anteontem = hoje - dt.timedelta(days=1), hoje - dt.timedelta(days=2)
    monkeypatch.setattr(D, "_wb", lambda: None)
    monkeypatch.setattr(D, "_state", {"daily": {"Piracicaba 1": ("Piracicaba 1", "A1:R9")}, "df": {}})
    pedidos = []

    def _recs(nome):
        pedidos.append(nome)
        return [{"data": anteontem, "ger": 900.0, "ipoa": 0.0, "validacao": 1.0, "inv": {"Inversor 1.1": 500.0, "Inversor 1.2": 400.0}},
                {"data": ontem, "ger": 700.0, "ipoa": 4.4, "validacao": 1.0, "inv": {"Inversor 1.1": 700.0}},
                {"data": hoje, "ger": 0.0, "ipoa": None, "validacao": 0.0, "inv": {}},
                {"data": dt.date(2025, 12, 31), "ger": 1.0, "ipoa": 1.0, "validacao": 1.0, "inv": {"Inversor 1.1": 1.0}}]
    monkeypatch.setattr(D, "_daily_inversores", _recs)
    d = app._bdthopen_inv_dias("Piracicaba I", hoje.year, hoje.month)
    assert pedidos == ["Piracicaba 1"]
    if ontem.month == hoje.month and anteontem.month == hoje.month:          # nos dias 1 e 2 do mês o teste só checa o hoje
        assert d[anteontem.isoformat()] == {"ipoa": None, "inv": {"Inversor 1.1": 500.0, "Inversor 1.2": 400.0}, "validacao": 1.0}
        assert d[ontem.isoformat()]["ipoa"] == 4.4 and d[ontem.isoformat()]["inv"] == {"Inversor 1.1": 700.0}
    assert hoje.isoformat() not in d and "2025-12-31" not in d
    assert app._bdthopen_inv_dias("Usina Que Nao Existe", hoje.year, hoje.month) == {}


def test_leitor_da_aba_diaria_traz_os_inversores():
    """dashboard_thopen._daily_inversores: colunas 'Inversor N.M' viram {nome: kWh}; vazio não vira zero."""
    import datetime as dt
    import openpyxl
    import dashboard_thopen as D
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Teste 1"
    ws.append(["Usina", "Data", "IPOA (kWh/m²)", "Energia Produzida (kWh)", "Inversor 1.1", "Inversor 1.2", "Validação"])
    ws.append(["Teste 1", dt.datetime(2026, 9, 1), 5.5, 900.0, 500.0, 400.0, 1])
    ws.append(["Teste 1", dt.datetime(2026, 9, 2), None, 0, None, None, 0])
    ws.append(["Teste 1", "texto", None, None, None, None, None])
    antes = (D._state, D._wb)
    try:
        D._state = {"daily": {"Teste 1": ("Teste 1", "A1:G4")}, "df": {}}
        D._wb = lambda: wb
        r = D._daily_inversores("Teste 1")
    finally:
        D._state, D._wb = antes
    assert len(r) == 2
    assert r[0] == {"data": dt.date(2026, 9, 1), "ger": 900.0, "ipoa": 5.5, "validacao": 1.0, "inv": {"Inversor 1.1": 500.0, "Inversor 1.2": 400.0}}
    assert r[1]["inv"] == {} and r[1]["ger"] == 0.0 and r[1]["ipoa"] is None
