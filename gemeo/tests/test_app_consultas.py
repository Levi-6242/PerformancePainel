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
