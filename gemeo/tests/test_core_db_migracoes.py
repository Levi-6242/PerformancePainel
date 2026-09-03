# gemeo/tests/test_core_db_migracoes.py
"""Migracoes em SQLite: todas as tabelas, idempotencia, chave natural da leitura, e os tipos que o db.py promete
(datetime aware entra e sai, dict entra e sai como JSON, bool volta bool, date volta date, '%s' vira '?')."""
import datetime as dt
from pathlib import Path

import pytest

from gemeo.core import db

TABELAS = {"usina", "equipamento", "alias", "leitura", "ingest_run", "modelo", "esperado",
           "cascata_dia", "perda_dia", "evento", "meta_mes", "estado", "schema_migrations"}
UTC = dt.timezone.utc


def test_migrar_cria_todas_as_tabelas(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        assert TABELAS <= {r[0] for r in cur.fetchall()}
    assert set(db.status(conn)["tabelas"]) >= TABELAS - {"schema_migrations"} | {"schema_migrations"}


def test_migrar_e_idempotente(conn):
    assert db.migrar(conn) == []          # segunda chamada: nada a aplicar


def test_leitura_tem_chave_natural(conn):
    with conn.cursor() as cur:
        cur.execute("PRAGMA table_info(leitura)")
        pk = [r[1] for r in sorted(cur.fetchall(), key=lambda r: r[5]) if r[5] > 0]
        assert pk == ["equipamento_id", "medida", "ts"]


def test_tipos_vao_e_voltam_como_o_codigo_espera(conn):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO usina (codigo, nome, fonte, fonte_ref, tz, full_om) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                    ("T9", "Teste", "sunop", "T9", "America/Belem", True))
        uid = cur.fetchone()[0]
        cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte, atributos) VALUES (%s,'inversor','INV_1',%s) RETURNING id", (uid, {"kwp": 277.68, "numero": 1}))
        eid = cur.fetchone()[0]
        cur.execute("INSERT INTO modelo (usina_id, versao, parametros, ativo) VALUES (%s,'placa',%s,1) RETURNING id", (uid, {"gamma": -0.0035}))
        mid = cur.fetchone()[0]                    # AUTOINCREMENT nao volta a 1 entre testes: nunca chutar id
        cur.execute("INSERT INTO cascata_dia (usina_id, dia, modelo_id, e_esperado, e_medido, delta) VALUES (%s,%s,%s,1,1,0)", (uid, dt.date(2026, 9, 1), mid))
        cur.execute("SELECT atributos, ativo, descoberto_em FROM equipamento WHERE id=%s", (eid,))
        at, ativo, desc = cur.fetchone()
        assert at == {"kwp": 277.68, "numero": 1} and ativo is True and desc.tzinfo is not None
        cur.execute("SELECT json_extract(atributos, '$.numero') FROM equipamento WHERE id=%s", (eid,))
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT parametros, calibrado, ativo FROM modelo WHERE usina_id=%s", (uid,))
        assert cur.fetchone() == ({"gamma": -0.0035}, False, True)
        cur.execute("SELECT dia FROM cascata_dia WHERE usina_id=%s", (uid,))
        assert cur.fetchone()[0] == dt.date(2026, 9, 1)
        cur.execute("SELECT fonte FROM usina WHERE codigo LIKE 'T%%' AND id=%s", (uid,))
        assert cur.fetchone()[0] == "sunop"                                     # '%%' vira '%' na traducao
        with pytest.raises(ValueError):
            cur.execute("INSERT INTO estado (chave, valor, atualizado_em) VALUES ('x','y',%s)", (dt.datetime(2026, 9, 1, 12, 0),))  # naive nao entra
    conn.rollback()
