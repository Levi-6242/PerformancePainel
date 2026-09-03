# gemeo/tests/test_core_db_upsert.py
"""'Vazio nunca sobrescreve' como PROPRIEDADE da escrita, nao como cuidado de quem chama. A plataforma
aprendeu isso com o pg_trk congelado 33h e com o _sunop_str_med_ent cacheando foto vazia."""
import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from semear import limpar_tudo  # noqa: E402
from gemeo.core import db  # noqa: E402

UTC = dt.timezone.utc


@pytest.fixture
def usina_eq(conn):
    limpar_tudo(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO usina (codigo, nome, fonte, fonte_ref, tz) VALUES ('T1','Teste','pg','1','America/Belem') RETURNING id")
        u = cur.fetchone()[0]
        cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte) VALUES (%s,'inversor','INV_1') RETURNING id", (u,))
        e = cur.fetchone()[0]
    conn.commit()
    yield u, e
    limpar_tudo(conn)


def test_none_nunca_sobrescreve_valor(conn, usina_eq):
    _, e = usina_eq
    ts = dt.datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    assert db.upsert_leituras(conn, [(e, "p_ac", ts, 150.0)]) == 1
    assert db.upsert_leituras(conn, [(e, "p_ac", ts, None)]) == 0
    with conn.cursor() as cur:
        cur.execute("SELECT valor FROM leitura WHERE equipamento_id=%s", (e,))
        assert cur.fetchone()[0] == pytest.approx(150.0)


def test_valor_novo_vence_na_colisao(conn, usina_eq):
    _, e = usina_eq
    ts = dt.datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    db.upsert_leituras(conn, [(e, "p_ac", ts, 150.0)])
    db.upsert_leituras(conn, [(e, "p_ac", ts, 151.5)])
    with conn.cursor() as cur:
        cur.execute("SELECT count(*), max(valor) FROM leitura WHERE equipamento_id=%s", (e,))
        n, v = cur.fetchone()
    assert n == 1 and v == pytest.approx(151.5)


def test_marca_dagua_e_o_maior_ts_da_usina(conn, usina_eq):
    u, e = usina_eq
    assert db.marca_dagua(conn, u) is None
    t1 = dt.datetime(2026, 9, 1, 12, 0, tzinfo=UTC); t2 = t1 + dt.timedelta(minutes=15)
    db.upsert_leituras(conn, [(e, "p_ac", t2, 1.0), (e, "p_ac", t1, 1.0)])
    assert db.marca_dagua(conn, u) == t2


def test_ingest_run_e_requisicoes_hoje(conn, usina_eq):
    u, _ = usina_eq
    hoje = dt.datetime.now(UTC)
    db.registrar_ingest_run(conn, "sunop", u, hoje, hoje, "ok", n_linhas=10, n_requisicoes=3, duracao_s=1.2, cobertura=1.0)
    db.registrar_ingest_run(conn, "sunop", u, hoje, hoje, "falha", n_requisicoes=1, erro="403 borda")
    assert db.requisicoes_hoje(conn, "sunop", hoje.date()) == 4
    assert db.requisicoes_hoje(conn, "pg", hoje.date()) == 0


def test_estado_pequeno(conn):
    assert db.ler_estado(conn, "cadastro.updated_at") is None
    db.gravar_estado(conn, "cadastro.updated_at", "2026-09-02T14:51")
    db.gravar_estado(conn, "cadastro.updated_at", "2026-09-03T08:00")
    assert db.ler_estado(conn, "cadastro.updated_at") == "2026-09-03T08:00"
