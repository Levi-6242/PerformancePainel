# -*- coding: utf-8 -*-
"""Recoleta da SunOp (as 10 GD da Athon) para a Coletas do Nexus (17/11/2026; Levi: "quero formas de coletar os dados
novamente pelas nossas fontes de dados e gerar uma planilha para colar nos BDs"). A régua é a do coletor da noite
(`coleta API PV/src/coletar_sunop.py`). A SunOp é DUBLADA: a `_sunop_req` vira um dublê que anota cada POST, e nada sai
para a fonte paga (o conftest recusaria e quebraria o teste)."""
import datetime as dt
import os
import types

import pytest

from recoleta_fontes import comum
from recoleta_fontes import sunop as so

BRT = dt.timezone(dt.timedelta(hours=-3))
HOJE = dt.date(2026, 11, 17)                     # segunda-feira
D10, D11, D12 = dt.date(2026, 11, 10), dt.date(2026, 11, 11), dt.date(2026, 11, 12)
ABA_MRO = "Athon - Mãe do Rio 1 - PA"
ABA_TIM1 = "Athon - Timon 1 - MA"
ABA_TIM2 = "Athon -  Timon 2 - MA"
ABA_MAB = "Athon - Marabá 1 - PA"


def _linha(us, es, u, e):
    return {"Usina Supervisório": us, "Equipamento Supervisório": es, "Usina": u, "Equipamento": e}


# A aba Equipamentos como o Nexus a publica para a Athon (estrutura_nexus.json de 17/11): a linha UFV vem sem
# "Usina Supervisório" e só as dos inversores a têm. O INV_4 da MRO100 fica sem de-para de propósito.
LINHAS = ([_linha(None, None, ABA_MRO, "UFV")]
          + [_linha("MRO100", "INV_%d" % i, ABA_MRO, "Inversor 1.%d" % i) for i in (1, 2, 3)]
          + [_linha("TIM100", None, ABA_TIM1, "UFV"), _linha("TIM100", "INV_1", ABA_TIM1, "Inversor 1.1")]
          + [_linha("TIM200", "INV_1", ABA_TIM2, "Inversor 1.1")]
          + [_linha("MAB100", "INV_1", ABA_MAB, "Inversor 1.1")])

_NOME = {"poa": "POA.IRAD", "ghi": "GHI.IRAD", "poari": "POA_R.IRAD"}


def _meta(planta, n_inv, estacoes=("ESTM",), medidas=("poa", "ghi"), aiml=False):
    """O metadado como o `_load_sunop_plant_meta` da plataforma o monta."""
    inv = {"INV_%d" % i: {"EPD": "%s.INV_%d.MEDIDAS.EPD" % (planta, i), "P": "%s.INV_%d.MEDIDAS.P" % (planta, i)}
           for i in range(1, n_inv + 1)}
    etm = {e: {m: "%s.%s.%s" % (planta, e, _NOME[m]) for m in medidas} for e in estacoes}
    if aiml:
        etm["AIML"] = {"poa": "%s.AIML.POA" % planta}
    return {"inv_strings": {}, "inv_other": inv, "plant_paths": {}, "etm_stations": etm, "trackers": {}}


def _curva(dia, pontos):
    return [("%sT%s:00" % (dia.isoformat(), hm), v) for hm, v in pontos]


class Resp:
    def __init__(self, corpo, status=200):
        self.corpo, self.status_code = corpo, status

    def json(self):
        if isinstance(self.corpo, Exception):
            raise self.corpo
        return self.corpo


class SunOp:
    """Dublê da `_sunop_req`: devolve TODOS os pontos de cada pathname pedido (a recoleta é quem corta o dia) e anota
    cada POST. `falha(dia_iso, pathnames)` devolve a resposta de um lote que deve falhar, ou None."""

    def __init__(self, pontos=None, falha=None):
        self.pontos, self.falha, self.feitas = pontos or {}, falha, []

    def __call__(self, metodo, url, inst="gridco", **kw):
        self.feitas.append((metodo, url, inst, kw))
        ps = kw["json"]["pathnames"]
        if self.falha:
            r = self.falha(kw["params"]["start_time"][:10], ps)
            if r is not False:
                return r
        return Resp([{"pathname": p, "timestamp": ts, "value": v} for p in ps for ts, v in self.pontos.get(p, [])])


def _ctx(meta, sunop=None, pausa=None, gasto=0, teto=2700, edge=False, sem_rede=None, lote=600):
    chamadas = []

    def _pausa(considera_ronda=True):
        chamadas.append(considera_ronda)
        return pausa

    def _token(*a, **k):
        pytest.fail("validou o token web na rede (o /data usa o token de API, que a _sunop_req põe)")

    return types.SimpleNamespace(
        mapa=comum.Mapa(LINHAS), inst="gridco", data_url="https://gridco-api.sunop.net/data", meta=meta,
        ensure_meta=lambda: None, get_sunop_token=_token, sunop_req=sunop or SunOp(), pausa=_pausa, teto_dia=teto,
        gasto_hoje=lambda: gasto, edge_aberto=lambda: edge, sem_rede=lambda: sem_rede, fuso=lambda p: BRT,
        lote=lote, chamadas_pausa=chamadas)


@pytest.fixture(autouse=True)
def _estado_zerado(monkeypatch):
    monkeypatch.setattr(comum, "_CONTA", {})
    monkeypatch.setattr(so, "_ANOTADO", {"lote": so.LOTE_PADRAO, "caminhos": {}})


# ---------------------------------------------------------------- geração = EPD máximo
def test_geracao_e_o_epd_maximo_do_dia_e_o_nulo_nao_vira_zero():
    s = SunOp({
        # a véspera traz 2.000 no fim do dia: se entrasse, seria o "EPD da véspera" (MRO100 21/09) virando o máximo
        "MRO100.INV_1.MEDIDAS.EPD": [("2026-11-09T23:50:00", 2000.0)]
                                    + _curva(D10, [("06:00", 0.0), ("12:00", 700.25), ("18:00", 1198.456),
                                                   ("23:55", 1198.4)]),
        "MRO100.INV_3.MEDIDAS.EPD": _curva(D10, [("06:00", 0.0), ("12:00", 0.0)]),      # zero medido segue zero
        "MRO100.INV_4.MEDIDAS.EPD": _curva(D10, [("12:00", 900.0)]),                     # sem de-para
    })                                                                                  # INV_2: nenhum ponto
    r = so.buscar(_ctx({"MRO100": _meta("MRO100", 4)}, s), ["MRO100"], [D10], True, False, False)
    assert r["geracao"] == [
        {"usina": ABA_MRO, "inversor": "Inversor 1.1", "data": "2026-11-10", "kwh": 1198.46},
        {"usina": ABA_MRO, "inversor": "Inversor 1.2", "data": "2026-11-10", "kwh": None},
        {"usina": ABA_MRO, "inversor": "Inversor 1.3", "data": "2026-11-10", "kwh": 0.0},
    ]
    assert r["geracao"][1]["kwh"] is None                                              # nulo é nulo, não 0
    assert r["escalares"] == []                                                         # ETM não foi pedido
    assert any("INV_4" in a and "sem de-para" in a for a in r["avisos"])
    assert len(s.feitas) == 1 and s.feitas[0][3]["json"]["pathnames"] == [
        "MRO100.INV_%d.MEDIDAS.EPD" % i for i in (1, 2, 3, 4)]                           # só o EPD: o ETM não custa


def test_carimbo_com_fuso_volta_para_a_hora_da_usina_e_o_dia_seguinte_fica_de_fora():
    s = SunOp({"MRO100.INV_1.MEDIDAS.EPD": [
        ("2026-11-10T12:00:00", 800.0),
        ("2026-11-11T02:30:00+00:00", 1300.0),       # 23:30 de 10/11 em Mãe do Rio: é do dia 10
        ("2026-11-11T00:05:00", 5.0),                # já é o dia 11 na usina
        ("lixo", 99999.0),                           # carimbo ilegível não entra
    ]})
    r = so.buscar(_ctx({"MRO100": _meta("MRO100", 1)}, s), ["MRO100"], [D10, D11], True, False, False)
    assert [(g["data"], g["kwh"]) for g in r["geracao"]] == [("2026-11-10", 1300.0), ("2026-11-11", 5.0)]


# ---------------------------------------------------------------- POA/GHI = integral com teto
def test_integral_trapezoidal_com_o_teto_de_1600_e_o_negativo_em_zero():
    t = lambda h, m=0: dt.datetime(2026, 11, 10, h, m)
    # 2.000 W/m² ao meio-dia é erro de sensor: vale 1.600. (0+1600)/2 x 6 h + (1600+0)/2 x 6 h = 9.600 Wh/m²
    assert so._integral([(t(6), 0.0), (t(12), 2000.0), (t(18), 0.0)]) == 9.6
    assert so._integral([(t(6), -50.0), (t(7), 100.0)]) == 0.05                         # negativo conta como 0
    assert so._integral([(t(6, 0), 600.0), (t(6, 5), 600.0)]) == 0.05                   # Δt real (5 min)
    assert so._integral([(t(12), 800.0)]) is None and so._integral([]) is None          # 1 ponto não é curva


def test_ipoa_e_ghi_saem_com_o_nome_da_coluna_do_bd_e_a_aiml_nao_entra():
    poa = _curva(D10, [("06:00", 0.0), ("12:00", 2000.0), ("18:00", 0.0)])
    s = SunOp({
        "MRO100.ESTM.POA.IRAD": poa,
        "MRO100.ESTM.GHI.IRAD": _curva(D10, [("06:00", 0.0), ("12:00", 1000.0), ("18:00", 0.0)]),
        # a POA da previsão (AI/ML) maior que a da estação: o `_build_escalares` pegaria o maior e ela não é sensor
        "MRO100.AIML.POA": _curva(D10, [("06:00", 0.0), ("12:00", 1500.0), ("13:00", 1500.0), ("18:00", 0.0)]),
    })
    r = so.buscar(_ctx({"MRO100": _meta("MRO100", 1, aiml=True)}, s), ["MRO100"], [D10], False, True, False)
    assert r["escalares"] == [
        {"usina": ABA_MRO, "data": "2026-11-10", "coluna": "IPOA (kWh/m²) ETM", "valor": 9.6},
        {"usina": ABA_MRO, "data": "2026-11-10", "coluna": "GHI (kWh/m²)", "valor": 6.0},
    ]
    assert r["geracao"] == []
    assert "MRO100.AIML.POA" not in s.feitas[0][3]["json"]["pathnames"]


def test_tim100_uma_coluna_por_estacao_mab100_a_estacao_que_mede_e_tim200_a_poa_ri():
    sol = _curva(D10, [("06:00", 0.0), ("12:00", 1000.0), ("18:00", 0.0)])             # 6,0 kWh/m²
    zero = _curva(D10, [("06:00", 0.0), ("12:00", 0.0), ("18:00", 0.0)])
    s = SunOp({
        "TIM100.ESTM_1.POA.IRAD": sol, "TIM100.ESTM_1.GHI.IRAD": sol,
        "TIM100.ESTM_2.POA.IRAD": zero, "TIM100.ESTM_2.GHI.IRAD": sol,
        "MAB100.ESTM_1.POA.IRAD": zero, "MAB100.ESTM_2.POA.IRAD": sol,
        "TIM200.ESTM.POA.IRAD": zero, "TIM200.ESTM.POA_R.IRAD": sol,
    })
    meta = {"TIM100": _meta("TIM100", 1, estacoes=("ESTM", "ESTM_1", "ESTM_2")),   # a "ESTM" solta sai
            "MAB100": _meta("MAB100", 1, estacoes=("ESTM_1", "ESTM_2"), medidas=("poa",)),
            "TIM200": _meta("TIM200", 1, medidas=("poa", "poari"))}
    r = so.buscar(_ctx(meta, s), ["TIM100", "MAB100", "TIM200"], [D10], False, True, False)
    got = {(e["usina"], e["coluna"]): e["valor"] for e in r["escalares"]}
    assert got == {
        (ABA_TIM1, "IPOA (kWh/m²) ETM 1"): 6.0, (ABA_TIM1, "GHI ETM 1 (kWh/m²)"): 6.0,
        (ABA_TIM1, "IPOA (kWh/m²) ETM 2"): None,                                       # estação lendo zero: nulo
        (ABA_TIM1, "GHI ETM 2 (kWh/m²)"): 6.0,
        (ABA_MAB, "IPOA (kWh/m²) ETM"): 6.0,                                           # a ESTM_2, que mede
        (ABA_TIM2, "IPOA (kWh/m²) ETM"): 6.0,                                          # a POA-RI (fallback)
    }
    pedidos = s.feitas[0][3]["json"]["pathnames"]
    assert "TIM100.ESTM.POA.IRAD" not in pedidos and "TIM200.ESTM.POA_R.IRAD" in pedidos


def test_ghi_todo_zero_e_estacao_sem_ponto_sao_nulos_e_nunca_zero():
    s = SunOp({"MRO100.ESTM.GHI.IRAD": _curva(D10, [("06:00", 0.0), ("12:00", 0.0), ("18:00", 0.0)])})
    r = so.buscar(_ctx({"MRO100": _meta("MRO100", 1)}, s), ["MRO100"], [D10], False, True, False)
    assert [(e["coluna"], e["valor"]) for e in r["escalares"]] == [("IPOA (kWh/m²) ETM", None), ("GHI (kWh/m²)", None)]
    assert all(e["valor"] is None for e in r["escalares"])


# ---------------------------------------------------------------- custo = lotes de pathnames por dia
def _duas_grandes():
    return {"MTS100": _meta("MTS100", 350), "MTS200": _meta("MTS200", 300)}         # 352 + 302 pathnames


def test_custo_e_o_lote_de_600_pathnames_atravessando_usinas_um_post_por_dia():
    ctx = _ctx(_duas_grandes())
    ctx.mapa = comum.Mapa([_linha(p, "INV_%d" % i, "Athon - %s" % p, "Inversor %d" % i)
                           for p, n in (("MTS100", 350), ("MTS200", 300)) for i in range(1, n + 1)])
    assert [p["id"] for p in so.plantas(ctx)] == ["MTS100", "MTS200"]
    ids, dias = ["MTS100", "MTS200"], [D10, D11, D12]
    assert so.custo(ids, dias, True, True, False) == 6                              # 654 pathnames = 2 lotes x 3 dias
    assert so.custo(ids, dias, True, False, False) == 6                             # 650 = 2 lotes
    assert so.custo(ids, dias, False, True, False) == 3                             # 4 = 1 lote
    assert so.custo(["MTS100"], dias, True, True, False) == 3
    assert so.custo(ids, dias, False, False, True) == 0                             # chuva não custa
    assert so.custo(ids, [], True, True, False) == 0
    assert so.custo(["MTS100", "XYZ100"], [D10], True, True, False) == 2            # sem anotação: 1 lote só dela

    s = SunOp()
    ctx.sunop_req = s
    so.buscar(ctx, ids, dias, True, True, False)
    assert len(s.feitas) == so.custo(ids, dias, True, True, False)                  # gasta o que o custo prometeu
    for metodo, url, inst, kw in s.feitas:
        assert (metodo, url, inst) == ("POST", "https://gridco-api.sunop.net/data/v2/analog_values", "gridco")
        assert len(kw["json"]["pathnames"]) <= 600 and kw["timeout"] == 120
        p = kw["params"]
        assert p["use_plant_timezone"] == "true" and p["source"] == "Historical" and p["fill_missing"] == "false"
        assert p["start_time"][11:] == "00:00:00" and p["end_time"][11:] == "23:59:59"
        assert p["start_time"][:10] == p["end_time"][:10] and "period" not in p
    primeiro = {x.split(".")[0] for x in s.feitas[0][3]["json"]["pathnames"]}
    assert primeiro == {"MTS100", "MTS200"}                                         # o lote mistura as usinas
    assert sorted({kw["params"]["start_time"][:10] for *_x, kw in s.feitas}) == ["2026-11-10", "2026-11-11",
                                                                                  "2026-11-12"]


def test_contexto_copia_o_lote_do_app_e_o_custo_segue_ele():
    app = _app_dublado(lote=300)
    ctx = so.contexto(app)
    ctx.mapa = comum.Mapa([_linha("MTS100", "INV_%d" % i, "Athon - MTS100", "Inversor %d" % i) for i in range(1, 351)])
    app.meta.update({"MTS100": _meta("MTS100", 350)})
    so.plantas(ctx)
    assert ctx.lote == 300 and so.custo(["MTS100"], [D10], True, True, False) == 2   # 352 / 300


# ---------------------------------------------------------------- permite: pausa de domingo e teto do dia
def test_permite_recusa_o_domingo_e_o_teto_pela_pausa_da_plataforma_sem_a_janela_da_ronda():
    ctx = _ctx({}, pausa="domingo")
    assert "domingo" in so.permite(ctx, 3)
    assert ctx.chamadas_pausa == [False]                                            # a janela da ronda não vale aqui
    assert "teto do dia" in so.permite(_ctx({}, pausa="teto"), 3)
    assert so.permite(_ctx({}, pausa="domingo"), 0) is None                          # sem requisição, nada a pausar


def test_permite_recusa_quando_a_recoleta_passaria_do_teto_do_dia_da_maquina():
    motivo = so.permite(_ctx({}, gasto=2695, teto=2700), 6)
    assert motivo and "passaria do teto" in motivo and "2695 de 2700" in motivo
    assert so.permite(_ctx({}, gasto=2695, teto=2700), 5) is None                    # cabe exato
    assert so.permite(_ctx({}), 7) is None
    assert "borda" in so.permite(_ctx({}, edge=True), 1)
    assert "sem credencial" in so.permite(_ctx({}, sem_rede="sem credencial"), 1)


def test_teto_da_recoleta_vem_do_ambiente_e_zero_nao_desliga_o_limite():
    assert so.TETO == so._teto_do_ambiente(os.environ.get("RECOLETA_SUNOP_TETO_DIA")) and so._teto_do_ambiente(None) == 150
    assert so._teto_do_ambiente("80") == 80
    assert so._teto_do_ambiente("0") == 150 and so._teto_do_ambiente("-5") == 150 and so._teto_do_ambiente("x") == 150
    assert so.PAGA is True and so.FONTE == "sunop" and so.MAX_PLANTAS == 10


# ---------------------------------------------------------------- lote que falha
def test_lote_que_falha_deixa_sem_valor_so_as_usinas_dele_e_o_dia_nao_e_sugerido():
    ctx = _ctx(_duas_grandes())
    ctx.mapa = comum.Mapa([_linha(p, "INV_%d" % i, "Athon - %s" % p, "Inversor %d" % i)
                           for p, n in (("MTS100", 350), ("MTS200", 300)) for i in range(1, n + 1)])
    so.plantas(ctx)
    pontos = {"%s.INV_%d.MEDIDAS.EPD" % (p, i): _curva(D10, [("12:00", 100.0), ("18:00", 200.0)])
              for p, n in (("MTS100", 350), ("MTS200", 300)) for i in range(1, n + 1)}
    # o 2º lote do dia (só pathnames da MTS200) volta 500: a MTS200 inteira fica sem valor; a MTS100, inteira no 1º
    s = SunOp(pontos, falha=lambda dia, ps: (Resp({"detail": "x"}, 500) if all(p.startswith("MTS200.") for p in ps)
                                             else False))
    ctx.sunop_req = s
    r = so.buscar(ctx, ["MTS100", "MTS200"], [D10], True, False, False)
    assert len(s.feitas) == 2                                                       # não tenta de novo
    mts1 = [g["kwh"] for g in r["geracao"] if g["usina"] == "Athon - MTS100"]
    mts2 = [g["kwh"] for g in r["geracao"] if g["usina"] == "Athon - MTS200"]
    assert len(mts1) == 350 and set(mts1) == {200.0}
    assert len(mts2) == 300 and set(mts2) == {None}                                 # nem o que veio no 1º lote vale
    aviso = [a for a in r["avisos"] if "MTS200" in a and "HTTP 500" in a]
    assert aviso and "SEM valor" in aviso[0] and "MTS100" not in aviso[0]
    resp = comum.montar_resposta(r, ctx.mapa, 2, 148, 150)
    assert resp["dias_fora"] == [{"usina": "Athon - MTS200", "data": "2026-11-10"}]


@pytest.mark.parametrize("resposta", [None, Resp({"data": []}), Resp(ValueError("não é JSON")), Resp(["texto"]),
                                      Resp([], 403)])
def test_resposta_fora_do_formato_e_lote_falho_nunca_dia_vazio(resposta):
    s = SunOp({"MRO100.INV_1.MEDIDAS.EPD": _curva(D10, [("12:00", 500.0)])}, falha=lambda dia, ps: resposta)
    r = so.buscar(_ctx({"MRO100": _meta("MRO100", 1)}, s), ["MRO100"], [D10], True, True, False)
    assert [g["kwh"] for g in r["geracao"]] == [None]
    assert [e["valor"] for e in r["escalares"]] == [None, None]
    assert any("não devolveu o lote" in a for a in r["avisos"])


def test_chuva_nao_e_da_sunop_e_usina_sem_metadado_vira_aviso():
    s = SunOp()
    r = so.buscar(_ctx({}, s), ["MRO100"], [D10], False, False, True)
    assert r["geracao"] == [] and r["escalares"] == [] and s.feitas == []
    assert any("chuva" in a for a in r["avisos"])
    r = so.buscar(_ctx({}, s), ["MRO100"], [D10], True, True, False)
    assert s.feitas == [] and any("MRO100" in a and "metadado" in a for a in r["avisos"])


# ---------------------------------------------------------------- contexto e plantas
def _app_dublado(lote=600):
    meta = {}

    def _nao(*a, **k):
        pytest.fail("chamou a SunOp")

    app = types.SimpleNamespace(
        meta=meta, ensure=[], sem_rede_inst=[], SUNOP_TETO_DIA=2700, SUNOP_LOTE_PATHNAMES=lote,
        _recoleta_mapa=lambda: comum.Mapa(LINHAS), get_sunop_token=_nao, _sunop_req=_nao,
        _sunop_pausa=lambda considera_ronda=True: None, _sunop_gasto_hoje=lambda: 12, _sunop_edge_aberto=lambda: False,
        _sunop_fuso_usina=lambda p: BRT)
    app._si = lambda inst="gridco": {"data": "https://gridco-api.sunop.net/data", "meta": meta}
    app.ensure_sunop_meta = lambda inst="gridco": app.ensure.append(inst)
    app._sunop_sem_rede = lambda inst="gridco": app.sem_rede_inst.append(inst)
    return app


def test_contexto_pega_do_app_o_contador_a_pausa_e_o_metadado_vivo_sem_ir_a_rede():
    app = _app_dublado()
    ctx = so.contexto(app)
    assert ctx.meta is app.meta and ctx.teto_dia == 2700 and ctx.gasto_hoje() == 12 and ctx.inst == "gridco"
    assert ctx.sunop_req is app._sunop_req and ctx.pausa is app._sunop_pausa and ctx.lote == 600
    app.meta.update({"MRO100": _meta("MRO100", 4), "XYZ100": _meta("XYZ100", 2), "VAZ100": {"inv_other": {}}})
    pl = so.plantas(ctx)
    assert app.ensure == ["gridco"]                                                 # o cache da plataforma
    # XYZ100 sem aba no BD e VAZ100 sem pathname nenhum ficam fora, como na fonte apipv
    assert pl == [{"id": "MRO100", "usina": ABA_MRO, "destino": "BD_Performance"}]
    assert so.permite(ctx, 1) is None and app.sem_rede_inst == ["gridco"]


# ---------------------------------------------------------------- a rota de verdade, com a SunOp dublada
def test_rota_de_ponta_a_ponta_conta_o_que_gasta_e_recusa_o_domingo(monkeypatch):
    import app
    import recoleta_apipv as rc
    monkeypatch.setattr(app, "DASH_PASSWORD", "senha-de-teste")
    monkeypatch.setattr(app, "PASSWORD", "senha-pv-de-teste")
    monkeypatch.delenv("RECOLETA_CHAVE", raising=False)
    monkeypatch.setattr(comum, "hoje_br", lambda agora_utc=None: HOJE)
    monkeypatch.setattr(app, "_recoleta_mapa", lambda: comum.Mapa(LINHAS))
    monkeypatch.setattr(app, "_sunop_meta", {"MRO100": _meta("MRO100", 3)})
    monkeypatch.setattr(app, "ensure_sunop_meta", lambda inst="gridco": None)
    s = SunOp({"MRO100.INV_1.MEDIDAS.EPD": _curva(D10, [("12:00", 600.0), ("18:00", 1198.0)]),
               "MRO100.ESTM.POA.IRAD": _curva(D10, [("06:00", 0.0), ("12:00", 1000.0), ("18:00", 0.0)])})
    monkeypatch.setattr(app, "_sunop_req", s)
    pausa = {"v": None}
    monkeypatch.setattr(app, "_sunop_pausa", lambda considera_ronda=True: pausa["v"])
    monkeypatch.setattr(app, "_sunop_gasto_hoje", lambda: 10)
    monkeypatch.setattr(app, "_sunop_edge_aberto", lambda: False)
    monkeypatch.setattr(app, "_sunop_sem_rede", lambda inst="gridco": None)
    monkeypatch.setattr(app, "_sunop_fuso_usina", lambda p: BRT)
    monkeypatch.setattr(app, "get_sunop_token", lambda *a, **k: pytest.fail("validou o token web na rede"))
    cli = app.app.test_client()
    cab = {"X-Recoleta-Chave": rc.chave_esperada("", "senha-pv-de-teste")}

    pl = cli.get("/api/recoleta/sunop/plantas", headers=cab).get_json()
    assert pl["plantas"] == [{"id": "MRO100", "usina": ABA_MRO, "destino": "BD_Performance"}]
    assert pl["paga"] is True and pl["teto"] == so.TETO and pl["max_plantas"] == 10 and s.feitas == []

    corpo = {"ids": ["MRO100"], "ini": "2026-11-10", "fim": "2026-11-10", "geracao": True, "etm": True}
    sim = cli.post("/api/recoleta/sunop", json=dict(corpo, simular=True), headers=cab).get_json()
    assert sim["consultas"] == 1 and s.feitas == []                                 # simular não gasta

    r = cli.post("/api/recoleta/sunop", json=corpo, headers=cab)
    j = r.get_json()
    assert r.status_code == 200 and j["consultas"] == 1 == len(s.feitas) and j["cota_restante"] == so.TETO - 1
    assert {"usina": ABA_MRO, "inversor": "Inversor 1.1", "data": "2026-11-10", "kwh": 1198.0} in j["geracao"]
    assert {"usina": ABA_MRO, "data": "2026-11-10", "coluna": "IPOA (kWh/m²) ETM", "valor": 6.0} in j["escalares"]

    pausa["v"] = "domingo"
    r = cli.post("/api/recoleta/sunop", json=corpo, headers=cab)
    assert r.status_code == 429 and "domingo" in r.get_json()["erro"] and len(s.feitas) == 1
