# gemeo/tests/test_modelar_job.py
"""Job de ponta a ponta sobre o banco semeado com a fixture golden da MRO100 (31/08): persiste esperado,
cascata_dia, perda_dia e evento, e rodar duas vezes deixa o banco IGUAL. Pula sem GEMEO_TEST_DSN."""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from semear import limpar_tudo, semear_fixture  # noqa: E402
from gemeo.modelar import job  # noqa: E402

G = Path(__file__).parent / "fixtures" / "golden"
UTC = dt.timezone.utc


@pytest.fixture
def mro100(conn):
    limpar_tudo(conn)
    trk_inv = json.load(open(G / "mro100_trk_inv.json", encoding="utf-8"))
    usina, ids = semear_fixture(conn, G / "mro100_2026-08-31.json", trk_inv)
    yield usina, ids
    limpar_tudo(conn)


def _foto(conn):
    out = []
    with conn.cursor() as cur:
        for sql in ("SELECT count(*), round(sum(p_esperado_kw)::numeric, 3) FROM esperado",
                    "SELECT count(*), round(sum(delta)::numeric, 3) FROM cascata_dia",
                    "SELECT count(*), round(sum(kwh)::numeric, 3) FROM perda_dia",
                    "SELECT count(*), round(sum(kwh)::numeric, 3) FROM evento"):
            cur.execute(sql); out.append(cur.fetchone())
    return out


def test_job_persiste_e_e_idempotente(conn, mro100):
    usina, ids = mro100
    ini, fim = dt.datetime(2026, 8, 31, 3, 0, tzinfo=UTC), dt.datetime(2026, 9, 1, 3, 0, tzinfo=UTC)   # 00:00 -> 24:00 de Belem
    res = job.modelar(conn, usina, ini, fim)
    assert res["modelo"] == "placa" and res["dias"] >= 1 and res["e_esperado"] > 30000 and res["inferidos"] == 0
    foto1 = _foto(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT e_esperado, e_medido, inv_parado, tracker, cobertura_gate FROM cascata_dia WHERE usina_id=%s AND dia=%s", (usina.id, dt.date(2026, 8, 31)))
        e_esp, e_med, parado, tracker, cob = cur.fetchone()
        assert e_esp > e_med and parado > 1000 and tracker > 50 and cob > 0.9
        cur.execute("SELECT equipamento_id FROM evento WHERE tipo='inversor_parado'")
        assert {r[0] for r in cur.fetchall()} == {ids["inv:22"]}
        cur.execute("SELECT count(*) FROM evento WHERE tipo='tracker_fora_alvo' AND equipamento_id = ANY(%s)", ([ids["trk:4"], ids["trk:17"]],))
        assert cur.fetchone()[0] >= 2
        cur.execute("SELECT count(*) FROM esperado WHERE gate='ok' AND p_esperado_kw IS NULL")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT versao, ativo, tolerancia FROM modelo")
        assert cur.fetchone() == ("placa", True, 0.08)
    job.modelar(conn, usina, ini, fim)
    assert _foto(conn) == foto1


def test_janela_padrao_cobre_tres_dias_locais():
    agora = dt.datetime(2026, 9, 3, 15, 7, tzinfo=UTC)          # 12:07 em Belem
    ini, fim = job.janela_padrao(agora, "America/Belem")
    assert ini == dt.datetime(2026, 9, 1, 3, 0, tzinfo=UTC) and fim == agora
