# gemeo/gemeo/core/db.py
"""Acesso ao banco do gemeo: SQLite EMBUTIDO — um arquivo, sem servidor, sem DBA (decisao do Levi em 03/09/2026, para
nao depender de ninguem criar schema). Migracoes em SQL puro e os poucos upserts que valem regra.

Convencoes que o resto do codigo assume:
- todo instante e texto ISO 8601 em UTC ('2026-09-01T12:00:00+00:00'); datetime AWARE entra e sai sozinho (adapters e
  converters); naive e erro em voz alta; colunas de expressao pedem alias '"x [TIMESTAMP]"' para voltar como datetime;
- dict/list entram como JSON e colunas declaradas JSON voltam como dict; BOOLEAN volta como bool; DATE como date;
- os '%s' do estilo psycopg2 sao traduzidos para '?' no cursor, entao o SQL do projeto continua o mesmo de antes;
- WAL + busy_timeout: ingest, modelar e app abrem conexoes PROPRIAS ao mesmo arquivo (uma por thread)."""
from __future__ import annotations
import datetime as dt
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

PASTA_MIGRACOES = Path(__file__).resolve().parents[2] / "migrations"
UTC = dt.timezone.utc
_AGORA_SQL = "strftime('%Y-%m-%dT%H:%M:%S+00:00','now')"
# "database is locked" na subida de 11/09/2026: pg, sunop, cadastro e apipv disputando o arquivo na largada. WAL + busy_timeout de
# 30 s nao bastam — a fila do SQLite nao e justa e quem perde nao espera de novo. Quem escreve leva grande desfaz, espera e repete.
TENTATIVAS_LOCK, PAUSA_LOCK_S = 6, 10.0


def caminho_padrao() -> Path:
    """Fora de pasta sincronizada: OneDrive + SQLite = arquivo subido pela metade e lock preso (ja nos machucou)."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "GridCo" / "gemeo" / "gemeo.sqlite"


# ── tipos: o que entra e o que sai ───────────────────────────────────────────
def _adapta_datetime(v: dt.datetime) -> str:
    if v.tzinfo is None or v.utcoffset() is None:
        raise ValueError(f"datetime sem fuso nao entra no banco: {v!r} — tudo no gemeo e aware em UTC")
    return v.astimezone(UTC).isoformat()


def _converte_timestamp(b: bytes) -> dt.datetime:
    s = b.decode()
    d = dt.datetime.fromisoformat(s.replace(" ", "T"))
    return d if d.tzinfo else d.replace(tzinfo=UTC)


sqlite3.register_adapter(dt.datetime, _adapta_datetime)
sqlite3.register_adapter(pd.Timestamp, _adapta_datetime)
sqlite3.register_adapter(dt.date, lambda d: d.isoformat())
sqlite3.register_adapter(dict, lambda d: json.dumps(d, ensure_ascii=False, default=str))
sqlite3.register_adapter(list, lambda d: json.dumps(d, ensure_ascii=False, default=str))
for _t in (np.float16, np.float32, np.float64):
    sqlite3.register_adapter(_t, float)
for _t in (np.int8, np.int16, np.int32, np.int64, np.uint8, np.uint16, np.uint32, np.uint64):
    sqlite3.register_adapter(_t, int)
sqlite3.register_adapter(np.bool_, int)
sqlite3.register_converter("TIMESTAMP", _converte_timestamp)
sqlite3.register_converter("DATE", lambda b: dt.date.fromisoformat(b.decode()))
sqlite3.register_converter("BOOLEAN", lambda b: b.decode().strip().lower() in ("1", "true", "t", "sim"))
sqlite3.register_converter("JSON", lambda b: json.loads(b.decode()) if b else {})


def _traduz(sql: str) -> str:
    """'%s' do psycopg2 -> '?', e '%%' -> '%'. So mexe quando ha '%s'/'%%'; SQL sem parametros passa intacto."""
    if "%s" in sql or "%%" in sql:
        return sql.replace("%%", "\x00").replace("%s", "?").replace("\x00", "%")
    return sql


class Cursor(sqlite3.Cursor):
    """Cursor com `with` (o sqlite3 nao tem) e com a traducao dos placeholders."""
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def execute(self, sql, params=None):                      # noqa: D102
        return super().execute(_traduz(sql)) if params is None else super().execute(_traduz(sql), params)

    def executemany(self, sql, seq):                          # noqa: D102
        return super().executemany(_traduz(sql), seq)


class Conexao(sqlite3.Connection):
    def cursor(self, factory=Cursor):                         # noqa: D102
        return super().cursor(factory)


def conectar(caminho: str | os.PathLike):
    p = Path(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), factory=Conexao, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def status(conn) -> dict:
    """O que `gemeo migrate` imprime: onde esta o arquivo, tamanho e tabelas."""
    with conn.cursor() as cur:
        cur.execute("PRAGMA database_list")
        arq = next((r[2] for r in cur.fetchall() if r[1] == "main"), "?")
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        tabelas = [r[0] for r in cur.fetchall()]
    tam = os.path.getsize(arq) / 1e6 if arq and os.path.exists(arq) else 0.0
    return {"arquivo": arq, "tamanho_mb": round(tam, 1), "tabelas": tabelas, "sqlite": sqlite3.sqlite_version}


def migrar(conn, pasta: Path | None = None) -> list[str]:
    """Aplica em ordem os .sql ainda nao registrados em schema_migrations. Idempotente."""
    pasta = pasta or PASTA_MIGRACOES
    with conn.cursor() as cur:
        cur.execute(f"CREATE TABLE IF NOT EXISTS schema_migrations (nome TEXT PRIMARY KEY, aplicada_em TIMESTAMP NOT NULL DEFAULT ({_AGORA_SQL}))")
        cur.execute("SELECT nome FROM schema_migrations")
        feitas = {r[0] for r in cur.fetchall()}
        aplicadas = []
        for arq in sorted(pasta.glob("*.sql")):
            if arq.name in feitas:
                continue
            cur.executescript(arq.read_text(encoding="utf-8"))
            cur.execute("INSERT INTO schema_migrations (nome) VALUES (?)", (arq.name,))
            aplicadas.append(arq.name)
    conn.commit()
    return aplicadas


def retencao(conn, dias: int = 90) -> int:
    """Bruto por `dias` (spec: 90); cascata, perdas, eventos e modelo ficam para sempre. Devolve linhas apagadas."""
    limite = dt.datetime.now(UTC) - dt.timedelta(days=dias)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM leitura WHERE ts < %s", (limite,))
        n = cur.rowcount
    conn.commit()
    return int(n)


def com_retentativa_de_lock(conn, fn, tentativas: int = TENTATIVAS_LOCK, pausa_s: float = PAUSA_LOCK_S):
    """Roda `fn()`; em 'database is locked' desfaz a transacao, espera e tenta de novo; qualquer outro erro sobe na hora e o
    lock tambem sobe depois da ultima tentativa. O ingestor da API PV perdeu o primeiro INSERT da vida assim (11/09/2026)."""
    for i in range(1, tentativas + 1):
        try:
            return fn()
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower() or i == tentativas:
                raise
            conn.rollback()
            time.sleep(pausa_s)


def upsert_leituras(conn, linhas: Iterable[tuple[int, str, dt.datetime, float | None]]) -> int:
    """Grava (equipamento, medida, ts, valor). Valor None e DESCARTADO antes de chegar ao banco — e a
    propriedade 'vazio nunca sobrescreve'. Na colisao, o valor novo vence (correcao tardia da fonte)."""
    validas = [(e, m, ts, float(v)) for e, m, ts, v in linhas if v is not None]
    if not validas:
        return 0

    def _grava():
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO leitura (equipamento_id, medida, ts, valor) VALUES (%s,%s,%s,%s) "
                            "ON CONFLICT (equipamento_id, medida, ts) DO UPDATE SET valor = excluded.valor", validas)
        conn.commit()
        return len(validas)
    return com_retentativa_de_lock(conn, _grava)


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
        cur.execute('SELECT max(l.ts) AS "ts [TIMESTAMP]" FROM leitura l JOIN equipamento e ON e.id = l.equipamento_id WHERE e.usina_id = %s', (usina_id,))
        return cur.fetchone()[0]


def requisicoes_hoje(conn, fonte: str, dia_utc: dt.date) -> int:
    ini = dt.datetime.combine(dia_utc, dt.time.min, tzinfo=UTC)
    with conn.cursor() as cur:
        cur.execute("SELECT coalesce(sum(n_requisicoes),0) FROM ingest_run WHERE fonte=%s AND criado_em >= %s AND criado_em < %s",
                    (fonte, ini, ini + dt.timedelta(days=1)))
        return int(cur.fetchone()[0])


def ler_estado(conn, chave: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT valor FROM estado WHERE chave=%s", (chave,))
        r = cur.fetchone()
        return r[0] if r else None


def gravar_estado(conn, chave: str, valor: str) -> None:
    with conn.cursor() as cur:
        cur.execute(f"INSERT INTO estado (chave, valor) VALUES (%s,%s) ON CONFLICT (chave) DO UPDATE SET valor=excluded.valor, atualizado_em={_AGORA_SQL}",
                    (chave, valor))
    conn.commit()
