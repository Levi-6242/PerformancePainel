# gemeo/gemeo/core/db.py
"""Acesso ao banco do gemeo: conexao, migracoes em SQL puro, e os poucos upserts que valem regra.
SQL puro de proposito — quem for depurar as 23h precisa ler o schema, nao um ORM."""
from __future__ import annotations
import datetime as dt
from pathlib import Path
from typing import Iterable
import psycopg2
import psycopg2.extras

PASTA_MIGRACOES = Path(__file__).resolve().parents[2] / "migrations"


def conectar(dsn: str):
    conn = psycopg2.connect(dsn, options="-c search_path=gemeo,public")
    conn.autocommit = False
    return conn


def migrar(conn, pasta: Path | None = None) -> list[str]:
    """Aplica em ordem os .sql ainda nao registrados em schema_migrations. Idempotente."""
    pasta = pasta or PASTA_MIGRACOES
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS gemeo")
        cur.execute("CREATE TABLE IF NOT EXISTS gemeo.schema_migrations (nome text PRIMARY KEY, aplicada_em timestamptz NOT NULL DEFAULT now())")
        cur.execute("SELECT nome FROM gemeo.schema_migrations")
        feitas = {r[0] for r in cur.fetchall()}
        aplicadas = []
        for arq in sorted(pasta.glob("*.sql")):
            if arq.name in feitas:
                continue
            cur.execute(arq.read_text(encoding="utf-8"))
            cur.execute("INSERT INTO gemeo.schema_migrations (nome) VALUES (%s)", (arq.name,))
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
