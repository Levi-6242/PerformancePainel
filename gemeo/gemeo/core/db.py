# gemeo/gemeo/core/db.py
"""Acesso ao banco do gemeo: conexao, migracoes em SQL puro, e os poucos upserts que valem regra.
SQL puro de proposito — quem for depurar as 23h precisa ler o schema, nao um ORM."""
from __future__ import annotations
import datetime as dt
from pathlib import Path
from typing import Iterable
import psycopg2
import psycopg2.extras
from psycopg2 import sql

PASTA_MIGRACOES = Path(__file__).resolve().parents[2] / "migrations"


def conectar(dsn: str, schema: str = "gemeo"):
    conn = psycopg2.connect(dsn, options=f"-c search_path={schema},public")
    conn.autocommit = False
    return conn


def schema_status(conn, schema: str) -> dict:
    """Existe? Temos USAGE e CREATE nele? CREATE no banco? E o que `gemeo migrate` imprime — e o pedido ao DBA sai daqui."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (schema,))
        existe = cur.fetchone() is not None
        cur.execute("SELECT current_user, has_database_privilege(current_user, current_database(), 'CREATE')")
        usuario, create_db = cur.fetchone()
        usage = create = False
        if existe:
            cur.execute("SELECT has_schema_privilege(current_user, %s, 'USAGE'), has_schema_privilege(current_user, %s, 'CREATE')", (schema, schema))
            usage, create = cur.fetchone()
    return {"schema": schema, "existe": existe, "usuario": usuario, "create_no_banco": bool(create_db), "usage": bool(usage), "create": bool(create)}


def migrar(conn, pasta: Path | None = None, schema: str = "gemeo") -> list[str]:
    """Aplica em ordem os .sql ainda nao registrados em schema_migrations. Idempotente. Cria o schema so se ele nao
    existir E o usuario puder (banco proprio, CI). Num banco compartilhado (powerplants do Thopen) o DBA cria o schema e
    da USAGE+CREATE, e aqui so se usa — `CREATE SCHEMA IF NOT EXISTS` num schema que ja existe AINDA exige CREATE no
    banco (o PostgreSQL checa a permissao antes de olhar o IF NOT EXISTS), e levi.maia nao tem."""
    pasta = pasta or PASTA_MIGRACOES
    st = schema_status(conn, schema)
    ident = sql.Identifier(schema)
    with conn.cursor() as cur:
        if not st["existe"]:
            if not st["create_no_banco"]:
                raise PermissionError(f"schema {schema!r} nao existe e {st['usuario']!r} nao tem CREATE no banco — peca ao DBA: "
                                      f"CREATE SCHEMA {schema} AUTHORIZATION \"{st['usuario']}\";")
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(ident))
        elif not (st["usage"] and st["create"]):
            raise PermissionError(f"schema {schema!r} existe mas {st['usuario']!r} nao tem USAGE+CREATE nele — peca ao DBA: "
                                  f"GRANT USAGE, CREATE ON SCHEMA {schema} TO \"{st['usuario']}\";")
        # as migracoes criam tabelas sem qualificar: o search_path da sessao decide onde elas nascem
        cur.execute(sql.SQL("SET search_path TO {}, public").format(ident))
        cur.execute(sql.SQL("CREATE TABLE IF NOT EXISTS {}.schema_migrations (nome text PRIMARY KEY, aplicada_em timestamptz NOT NULL DEFAULT now())").format(ident))
        cur.execute(sql.SQL("SELECT nome FROM {}.schema_migrations").format(ident))
        feitas = {r[0] for r in cur.fetchall()}
        aplicadas = []
        for arq in sorted(pasta.glob("*.sql")):
            if arq.name in feitas:
                continue
            cur.execute(arq.read_text(encoding="utf-8"))
            cur.execute(sql.SQL("INSERT INTO {}.schema_migrations (nome) VALUES (%s)").format(ident), (arq.name,))
            aplicadas.append(arq.name)
    conn.commit()
    return aplicadas


def garantir_particoes(conn, meses: Iterable[dt.date]) -> None:
    """Cria a particao mensal de leitura para cada mes pedido (o ingest chama para o mes corrente e o
    proximo). Sem particao, a linha cai na DEFAULT — funciona, mas a retencao por mes deixa de ser um DROP."""
    with conn.cursor() as cur:
        for m in meses:
            ini = m.replace(day=1)
            fim = (ini.replace(year=ini.year + (ini.month // 12), month=ini.month % 12 + 1))
            nome = f"leitura_{ini:%Y_%m}"
            cur.execute(f"CREATE TABLE IF NOT EXISTS {nome} PARTITION OF leitura FOR VALUES FROM (%s) TO (%s)", (ini, fim))
    conn.commit()


def upsert_leituras(conn, linhas: Iterable[tuple[int, str, dt.datetime, float | None]]) -> int:
    """Grava (equipamento, medida, ts, valor). Valor None e DESCARTADO antes de chegar ao banco — e a
    propriedade 'vazio nunca sobrescreve'. Na colisao, o valor novo vence (correcao tardia da fonte)."""
    validas = [(e, m, ts, float(v)) for e, m, ts, v in linhas if v is not None]
    if not validas:
        return 0
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO leitura (equipamento_id, medida, ts, valor) VALUES %s "
            "ON CONFLICT (equipamento_id, medida, ts) DO UPDATE SET valor = EXCLUDED.valor",
            validas, page_size=5000)
    conn.commit()
    return len(validas)


def registrar_ingest_run(conn, fonte: str, usina_id: int | None, ini: dt.datetime, fim: dt.datetime, status: str,
                         n_linhas: int = 0, n_requisicoes: int = 0, duracao_s: float = 0.0,
                         cobertura: float = 0.0, erro: str | None = None) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ingest_run (fonte, usina_id, ini, fim, status, n_linhas, n_requisicoes, duracao_s, cobertura, erro) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (fonte, usina_id, ini, fim, status, n_linhas, n_requisicoes, duracao_s, cobertura, erro))
        rid = cur.fetchone()[0]
    conn.commit()
    return rid


def marca_dagua(conn, usina_id: int) -> dt.datetime | None:
    with conn.cursor() as cur:
        cur.execute("SELECT max(l.ts) FROM leitura l JOIN equipamento e ON e.id = l.equipamento_id WHERE e.usina_id = %s", (usina_id,))
        return cur.fetchone()[0]


def requisicoes_hoje(conn, fonte: str, dia_utc: dt.date) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT coalesce(sum(n_requisicoes),0) FROM ingest_run WHERE fonte=%s AND (criado_em AT TIME ZONE 'UTC')::date = %s", (fonte, dia_utc))
        return int(cur.fetchone()[0])


def ler_estado(conn, chave: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT valor FROM estado WHERE chave=%s", (chave,))
        r = cur.fetchone()
        return r[0] if r else None


def gravar_estado(conn, chave: str, valor: str) -> None:
    with conn.cursor() as cur:
        cur.execute("INSERT INTO estado (chave, valor) VALUES (%s,%s) ON CONFLICT (chave) DO UPDATE SET valor=EXCLUDED.valor, atualizado_em=now()", (chave, valor))
    conn.commit()
