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


def test_upsert_espera_o_lock_do_sqlite_em_vez_de_derrubar_a_leva(monkeypatch):
    """Na subida de 11/09/2026 (fonte apipv nova) o primeiro INSERT levou 'database is locked': pg, sunop, cadastro e apipv
    disputando o mesmo arquivo na largada — a fila do SQLite nao e justa e o busy_timeout de 30 s nao bastou. Perder uma leva
    de 146 s de custom_query por um lock e caro: desfaz, espera e tenta de novo; so depois de esgotar e que a excecao sobe."""
    import datetime as dt
    import sqlite3
    import pytest
    from gemeo.core import db
    dorme = []
    monkeypatch.setattr(db.time, "sleep", lambda s: dorme.append(s))

    class Cur:
        def __init__(s, c): s.c = c
        def __enter__(s): return s
        def __exit__(s, *a): return False
        def executemany(s, sql, seq):
            s.c.tentativas += 1
            if s.c.tentativas < 3:
                raise sqlite3.OperationalError("database is locked")

    class Conn:
        def __init__(s): s.tentativas = 0; s.rollbacks = 0; s.commits = 0
        def cursor(s): return Cur(s)
        def rollback(s): s.rollbacks += 1
        def commit(s): s.commits += 1

    ts = dt.datetime(2026, 9, 11, 16, 0, tzinfo=dt.timezone.utc)
    c = Conn()
    assert db.upsert_leituras(c, [(1, "p_ac", ts, 1.0)]) == 1
    assert (c.tentativas, c.rollbacks, c.commits, len(dorme)) == (3, 2, 1, 2)
    c2 = Conn(); c2.tentativas = -100                                   # nunca destrava
    with pytest.raises(sqlite3.OperationalError):
        db.upsert_leituras(c2, [(1, "p_ac", ts, 1.0)])
    assert c2.tentativas == -100 + db.TENTATIVAS_LOCK and c2.commits == 0
    c3 = Conn(); c3.tentativas = 10                                     # outro erro nao e lock: sobe na primeira

    class CurOutro(Cur):
        def executemany(s, sql, seq): raise sqlite3.OperationalError("no such table: leitura")
    c3.cursor = lambda: CurOutro(c3)
    with pytest.raises(sqlite3.OperationalError):
        db.upsert_leituras(c3, [(1, "p_ac", ts, 1.0)])
    assert c3.rollbacks == 0
