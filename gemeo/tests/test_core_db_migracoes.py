# gemeo/tests/test_core_db_migracoes.py
from pathlib import Path
from gemeo.core import db

TABELAS = {"usina", "equipamento", "alias", "leitura", "ingest_run", "modelo", "esperado",
           "cascata_dia", "perda_dia", "evento", "meta_mes", "estado", "schema_migrations"}


def test_migrar_cria_todas_as_tabelas(conn):
    with conn.cursor() as cur:
        cur.execute("select table_name from information_schema.tables where table_schema='gemeo'")
        assert TABELAS <= {r[0] for r in cur.fetchall()}


def test_migrar_e_idempotente(conn):
    assert db.migrar(conn) == []          # segunda chamada: nada a aplicar


def test_migrar_em_schema_criado_pelo_dba(conn):
    """Banco compartilhado: o DBA cria o schema e da USAGE+CREATE; migrar nao tenta CREATE SCHEMA e poe as tabelas LA."""
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS dt_teste CASCADE; CREATE SCHEMA dt_teste")
    conn.commit()
    try:
        assert db.schema_status(conn, "dt_teste")["existe"] and db.migrar(conn, schema="dt_teste") == ["0001_schema.sql"]
        with conn.cursor() as cur:
            cur.execute("select count(*) from information_schema.tables where table_schema='dt_teste' "
                        "and table_name in ('leitura','esperado','evento','schema_migrations')")
            assert cur.fetchone()[0] == 4
        assert db.migrar(conn, schema="dt_teste") == []
        assert db.schema_status(conn, "nao_existe")["existe"] is False
    finally:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS dt_teste CASCADE; SET search_path TO gemeo, public")
        conn.commit()


def test_leitura_tem_chave_natural(conn):
    with conn.cursor() as cur:
        cur.execute("""select count(*) from information_schema.table_constraints
                       where table_schema='gemeo' and table_name='leitura' and constraint_type='PRIMARY KEY'""")
        assert cur.fetchone()[0] == 1
