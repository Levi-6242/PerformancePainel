# gemeo/tests/test_app_consultas.py
"""As regras puras da tela (faixa, causa, motivo) sem banco; e a Frota e a Usina de ponta a ponta sobre o
banco semeado com a MRO100 de 31/08 (pula sem GEMEO_TEST_DSN)."""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from gemeo.app import consultas as c  # noqa: E402

G = Path(__file__).parent / "fixtures" / "golden"
UTC = dt.timezone.utc


def test_faixa_da_regua_com_placa_e_com_modelo_calibrado():
    assert c.faixa(-0.02, 0.08) == "dentro" and c.faixa(-0.05, 0.08) == "dentro" and c.faixa(-0.09, 0.08) == "grave"
    assert c.faixa(-0.05, 0.03) == "moderado" and c.faixa(-0.081, 0.03) == "grave" and c.faixa(0.01, 0.03) == "dentro"
    assert c.faixa(None, 0.03) == "sem_dado"


def test_causa_dominante_e_a_maior_parcela():
    assert c.causa_dominante({"inv_parado": 1600.0, "tracker": 100.0, "string": 0.0, "residuo": 300.0}) == "inversor parado"
    assert c.causa_dominante({"inv_parado": 0.0, "tracker": 0.0, "string": 0.0, "residuo": 0.0}) == "dentro da tolerância do modelo"
    assert c.causa_dominante(None) == "sem cascata hoje"


def test_motivo_nao_modelada():
    agora = dt.datetime(2026, 8, 31, 20, 0, tzinfo=UTC)
    base = {"n_equip": 5, "ultimo_ingest_ok": agora - dt.timedelta(hours=1), "gate_hoje": "ok", "esperado_kw": 100.0}
    assert c.motivo_nao_modelada(base, agora) is None
    assert c.motivo_nao_modelada({**base, "n_equip": 0}, agora) == "sem equipamentos no cadastro"
    assert c.motivo_nao_modelada({**base, "ultimo_ingest_ok": agora - dt.timedelta(hours=30)}, agora) == "sem ingestão nas últimas 24 h"
    assert c.motivo_nao_modelada({**base, "gate_hoje": "poa_ghi"}, agora) == "sensor em falha hoje (POA × GHI)"
    assert c.motivo_nao_modelada({**base, "gate_hoje": "cobertura"}, agora) == "sem cobertura de sensor hoje"
    assert c.motivo_nao_modelada({**base, "esperado_kw": None}, agora) == "sem esperado calculado hoje"


def test_exp_do_jwt():
    import base64
    payload = base64.urlsafe_b64encode(json.dumps({"exp": 1790000000}).encode()).decode().rstrip("=")
    assert c.exp_do_jwt(f"x.{payload}.y") == dt.datetime.fromtimestamp(1790000000, UTC)
    assert c.exp_do_jwt("nao-e-jwt") is None and c.exp_do_jwt("") is None


@pytest.fixture
def mro100_modelada(conn):
    from semear import limpar_tudo, semear_fixture
    from gemeo.core import db
    from gemeo.modelar import job
    limpar_tudo(conn)
    trk_inv = json.load(open(G / "mro100_trk_inv.json", encoding="utf-8"))
    usina, ids = semear_fixture(conn, G / "mro100_2026-08-31.json", trk_inv)
    ini, fim = dt.datetime(2026, 8, 31, 3, tzinfo=UTC), dt.datetime(2026, 9, 1, 3, tzinfo=UTC)
    job.modelar(conn, usina, ini, fim)
    db.registrar_ingest_run(conn, "sunop", usina.id, ini, fim, "ok", n_linhas=100, cobertura=1.0)
    with conn.cursor() as cur:   # o ingest_run 'ok' precisa parecer recente para o 'agora' congelado da tela
        cur.execute("UPDATE ingest_run SET criado_em=%s", (dt.datetime(2026, 8, 31, 19, 50, tzinfo=UTC),))
    conn.commit()
    yield usina, ids
    limpar_tudo(conn)


def test_frota_e_usina_sobre_o_banco_semeado(conn, mro100_modelada):
    usina, ids = mro100_modelada
    agora = dt.datetime(2026, 8, 31, 20, 0, tzinfo=UTC)        # 17:00 em Belem, com sol
    fr = c.frota(conn, agora)
    assert [u["codigo"] for u in fr["usinas"]] == ["MRO100"] and fr["nao_modeladas"] == []
    u = fr["usinas"][0]
    assert u["esperado_kw"] > 0 and u["medido_kw"] > 0 and u["faixa"] in ("dentro", "moderado", "grave")
    assert u["cascata"]["inv_parado"] > 1000 and u["causa"] == "inversor parado" and u["perda_kwh"] > 1000
    assert fr["totais"]["confianca"] == 1.0 and fr["regua"]["tolerancia"] == 0.08 and fr["regua"]["calibradas"] == 0
    us = c.usina(conn, usina.id, agora)
    assert us["cabecalho"]["codigo"] == "MRO100" and us["cabecalho"]["n_inversores"] == 25 and us["cabecalho"]["n_trackers"] == 120
    assert len(us["curva"]) > 40 and all(p["esperado_kw"] is None or p["esperado_kw"] >= 0 for p in us["curva"])
    assert us["cascata"]["inv_parado"] > 1000 and any(e["tipo"] == "inversor_parado" for e in us["eventos"])
    inv22 = next(i for i in us["inversores"] if i["id"] == ids["inv:22"])
    assert inv22["status"] == "parado" and inv22["inv_parado"] > 1000
    assert us["trackers"][0]["id"] in (ids["trk:4"], ids["trk:17"]) and us["sensor"]["cobertura_gate"] > 0.9
    # sem ingestao recente a usina sai da regua com motivo, nao some
    fr2 = c.frota(conn, agora + dt.timedelta(hours=30))
    assert fr2["usinas"] == [] and fr2["nao_modeladas"][0]["motivo"] == "sem ingestão nas últimas 24 h"


def test_usina_periodo_soma_as_cascatas_e_as_perdas(conn, mro100_modelada):
    usina, ids = mro100_modelada
    agora = dt.datetime(2026, 8, 31, 20, 0, tzinfo=UTC)
    with conn.cursor() as cur:   # um segundo dia sintetico na cascata, para a soma ter o que somar
        cur.execute("SELECT modelo_id FROM cascata_dia WHERE usina_id=%s LIMIT 1", (usina.id,))
        mid = cur.fetchone()[0]
        cur.execute("INSERT INTO cascata_dia (usina_id, dia, modelo_id, e_esperado, e_medido, delta, inv_parado, tracker, string, residuo, cobertura_gate, trackers_sem_inversor) "
                    "VALUES (%s,%s,%s,40000,38000,2000,1500,0,0,500,1.0,1)", (usina.id, dt.date(2026, 8, 30), mid))
    conn.commit()
    p = c.usina_periodo(conn, usina.id, agora, 7)
    assert p["periodo"] == {"dias": 7, "de": "2026-08-25", "ate": "2026-08-31"} and [d["dia"] for d in p["dias"]] == ["2026-08-30", "2026-08-31"]
    assert p["cascata"]["n_dias"] == 2 and p["cascata"]["e_esperado"] == pytest.approx(40000 + p["dias"][1]["e_esperado"])
    assert p["cascata"]["inv_parado"] > 2500 and p["cabecalho"]["faixa"] in ("dentro", "moderado", "grave")
    assert any(e["tipo"] == "inversor_parado" for e in p["eventos"])
    inv22 = next(i for i in p["inversores"] if i["id"] == ids["inv:22"])
    assert inv22["status"] == "parado" and inv22["inv_parado"] > 1000 and p["trackers"][0]["kwh"] > 0
    assert c.usina_periodo(conn, 999999, agora, 7) is None


def test_saude_a_noite_nao_cobra_idade_do_ciclo_mas_falha_acusa_sempre(conn, mro100_modelada):
    from types import SimpleNamespace
    from gemeo.core import db
    usina, _ = mro100_modelada
    cfg = SimpleNamespace(sunop_token="", teto_sunop_dia=600, janela_solar=("05:40", "18:20"))
    noite = dt.datetime(2026, 9, 1, 2, 0, tzinfo=UTC)       # 23:00 em Belem; ultimo ciclo 'ok' (19:50Z) tem 130 min
    assert not [p for p in c.saude(conn, cfg, noite)["problemas"] if p.startswith("sunop")]
    dia = dt.datetime(2026, 9, 1, 14, 0, tzinfo=UTC)        # 11:00 em Belem, mesmo ciclo com 18 h: ai sim e problema
    assert any(p.startswith("sunop: ok há") for p in c.saude(conn, cfg, dia)["problemas"])
    db.registrar_ingest_run(conn, "sunop", usina.id, noite, noite, "falha", n_requisicoes=1, erro="403 borda")
    assert any(p.startswith("sunop: falha") for p in c.saude(conn, cfg, noite)["problemas"])


def test_paradas_juntam_inversores_que_caem_na_mesma_janela(conn, mro100_modelada):
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/Belem")
    ev = [{"tipo": "inversor_parado", "equipamento": "Inversor 1.1", "kwh": 600.0, "ini": "2026-09-03T13:00:00+00:00", "fim": "2026-09-03T17:00:00+00:00"},
          {"tipo": "inversor_parado", "equipamento": "Inversor 1.2", "kwh": 620.0, "ini": "2026-09-03T13:15:00+00:00", "fim": "2026-09-03T17:00:00+00:00"},
          {"tipo": "inversor_parado", "equipamento": "Inversor 4.1", "kwh": 580.0, "ini": "2026-09-03T17:15:00+00:00", "fim": "2026-09-03T18:00:00+00:00"},  # encosta: mesma janela
          {"tipo": "inversor_parado", "equipamento": "Inversor 6.1", "kwh": 100.0, "ini": "2026-09-03T20:00:00+00:00", "fim": "2026-09-03T21:00:00+00:00"},  # separada
          {"tipo": "tracker_fora_alvo", "equipamento": "TRK_4", "kwh": 9.0, "ini": "2026-09-03T13:00:00+00:00", "fim": "2026-09-03T17:00:00+00:00"},
          {"tipo": "inversor_parado", "equipamento": "Inversor 9.9", "kwh": 5.0, "ini": "2026-09-03T13:00:00+00:00", "fim": None}]               # em aberto: fica de fora
    j = c._paradas(ev, tz, 12)
    assert len(j) == 2
    assert (j[0]["hora_ini"], j[0]["hora_fim"], j[0]["n"], j[0]["de"], j[0]["min"]) == ("10:00", "15:00", 3, 12, 300)
    assert j[0]["kwh"] == 1800.0 and j[1]["n"] == 1 and j[1]["hora_ini"] == "17:00"
    assert c._paradas([e for e in ev if e["tipo"] != "inversor_parado"], tz, 12) == []


def test_dia_fechado_mostra_o_selo_do_dia_e_nao_o_instante_da_meia_noite(conn, mro100_modelada):
    usina, _ = mro100_modelada
    fim_do_dia = dt.datetime(2026, 9, 1, 2, 59, 59, tzinfo=UTC)          # 23:59:59 de 31/08 em Belem: o que "Ver dia" congela
    d = c.usina(conn, usina.id, fim_do_dia)["cabecalho"]
    assert d["base"] == "dia" and d["faixa"] != "sem_dado" and -1 < (d["delta"] or 0) < 1
    meio_dia = dt.datetime(2026, 8, 31, 17, 0, tzinfo=UTC)              # 14:00 em Belem: ai o instante vale
    assert c.usina(conn, usina.id, meio_dia)["cabecalho"]["base"] == "agora"
    velho = dt.datetime(2026, 8, 31, 2, 59, 59, tzinfo=UTC)             # dia 30/08: a leitura mais nova e POSTERIOR
    v = c.usina(conn, usina.id, velho)["cabecalho"]
    assert v["idade_leitura_min"] is None and v["frio"] is False        # "ha -1440 min" nao vai para a tela


def test_periodo_marca_o_dia_que_teve_parada(conn, mro100_modelada):
    usina, ids = mro100_modelada
    p = c.usina_periodo(conn, usina.id, dt.datetime(2026, 8, 31, 20, 0, tzinfo=UTC), 7)
    dia31 = next(d for d in p["dias"] if d["dia"] == "2026-08-31")
    assert dia31["paradas"] and dia31["paradas"][0]["n"] >= 1 and dia31["paradas"][0]["de"] == 25
    assert dia31["paradas"][0]["hora_fim"] and dia31["paradas"][0]["kwh"] > 0
    assert p["paradas"] == [j for d in p["dias"] for j in d["paradas"]]        # o topo e a soma dos dias


def test_frota_a_noite_fala_do_dia_e_nao_do_instante(conn, mro100_modelada):
    usina, _ = mro100_modelada
    meio_dia = dt.datetime(2026, 8, 31, 17, 0, tzinfo=UTC)               # 14:00 em Belem
    f = c.frota(conn, meio_dia)
    assert f["base"] == "agora" and f["totais"]["esperado_kw"] > 0
    noite = dt.datetime(2026, 9, 1, 2, 30, tzinfo=UTC)                   # 23:30 em Belem, mesmo dia local
    n = c.frota(conn, noite)
    assert n["base"] == "dia"
    u = next(x for x in n["usinas"] if x["id"] == usina.id)
    assert u["esperado_kw"] == pytest.approx(u["cascata"]["e_esperado"])  # energia do dia, nao potencia do instante
    assert u["medido_kw"] == pytest.approx(u["cascata"]["e_medido"])
    assert -1 < u["delta"] < 1 and u["faixa"] != "sem_dado" and u["frio"] is False
    assert n["totais"]["delta"] == pytest.approx((u["cascata"]["e_medido"] - u["cascata"]["e_esperado"]) / u["cascata"]["e_esperado"])
    assert n["totais"]["confianca"] > 0                                  # de noite a confianca vem do gate do DIA


def test_frota_nao_chama_de_agora_um_esperado_velho(conn, mro100_modelada):
    """04/09 as 23:55: a Ibate 2 tinha esperado de 1,1 MW no ultimo slot COM esperado — o do por do sol, 7 h antes —
    e isso segurava a Frota no modo 'agora' no meio da madrugada."""
    usina, _ = mro100_modelada
    tarde = dt.datetime(2026, 8, 31, 21, 45, tzinfo=UTC)     # 18:45 em Belem: o sol ja se pos, mas o slot e recente
    assert c.frota(conn, tarde)["base"] in ("agora", "dia")  # depende do dado; o que nao pode e quebrar
    muito_depois = dt.datetime(2026, 9, 1, 4, 0, tzinfo=UTC) # 01:00: qualquer esperado tem mais de 30 min
    f = c.frota(conn, muito_depois)
    assert f["base"] == "dia"


def test_frota_de_madrugada_cai_no_ultimo_dia_fechado(conn, mro100_modelada):
    """Entre a meia-noite e as 5h o dia local mal comecou e nao tem cascata: quem abre a tela a essa hora quer o dia
    que fechou. A tela passa a dizer qual dia esta mostrando (`dia_ref`)."""
    usina, _ = mro100_modelada
    madrugada = dt.datetime(2026, 9, 1, 4, 30, tzinfo=UTC)          # 01:30 de 01/09 em Belem; a cascata e de 31/08
    f = c.frota(conn, madrugada)
    assert f["base"] == "dia" and f["dia_ref"] == "2026-08-31"
    u = next(x for x in f["usinas"] if x["id"] == usina.id)
    assert u["esperado_kw"] > 0 and u["esperado_kw"] == pytest.approx(u["cascata"]["e_esperado"])
    fim_da_tarde = dt.datetime(2026, 9, 1, 2, 30, tzinfo=UTC)       # 23:30 de 31/08: o proprio dia ja tem cascata
    assert c.frota(conn, fim_da_tarde)["dia_ref"] == "2026-08-31"


def test_usina_traz_curva_por_inversor_alinhada_a_da_usina_e_codigo(conn, mro100_modelada):
    """O Raio-X do /painel desenha a curva do inversor sobre a da usina (06/09/2026). Cada inversor sai com `codigo`
    (codigo_fonte, para casar com a plataforma) e duas series do MESMO tamanho da curva da usina; a soma das medidas
    dos inversores em cada slot e a propria curva medida da usina (mesma origem, `pac`)."""
    usina, ids = mro100_modelada
    agora = dt.datetime(2026, 8, 31, 20, 0, tzinfo=UTC)
    d = c.usina(conn, usina.id, agora)
    n = len(d["curva"])
    assert n > 0 and d["inversores"] and d["cabecalho"]["fonte_ref"]
    for inv in d["inversores"]:
        assert inv["codigo"] and len(inv["curva_medida_kw"]) == n and len(inv["curva_esperada_kw"]) == n
    for i, ponto in enumerate(d["curva"]):
        parcelas = [inv["curva_medida_kw"][i] for inv in d["inversores"] if inv["curva_medida_kw"][i] is not None]
        if ponto["medido_kw"] is None:
            assert not parcelas
        else:
            assert sum(parcelas) == pytest.approx(ponto["medido_kw"], abs=0.05 * len(parcelas) + 0.01)
    p = c.usina_periodo(conn, usina.id, agora, 7)
    assert all(inv["codigo"] for inv in p["inversores"]) and p["cabecalho"]["fonte_ref"]


def test_catalogo_diz_como_a_plataforma_acha_a_usina(conn, mro100_modelada):
    usina, _ = mro100_modelada
    cat = c.catalogo(conn)
    m = next(u for u in cat if u["id"] == usina.id)
    assert m["codigo"] == "MRO100" and m["fonte"] == "sunop" and m["fonte_ref"] and "n_equip" in m
