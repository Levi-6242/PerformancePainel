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


def test_analisar_escreve_as_estatisticas_que_o_otimizador_usa(conn):
    """17/09/2026 — o banco de producao rodou 3 meses SEM `sqlite_stat1`: o otimizador trabalhava cego
    sobre 17,3 M linhas e as telas levavam 50 s. Um ANALYZE levou para 2,5 s. E a migracao 0003/0004,
    que recria tabelas, derrubou as estatisticas de novo (37 s -> 2,7 s depois de reanalisar).

    Por isso o ANALYZE tem de ser rotina, nao socorro manual."""
    from gemeo.core import db
    with conn.cursor() as cur:                      # sqlite_stat1 so nasce com o primeiro ANALYZE
        cur.execute("SELECT count(*) FROM sqlite_master WHERE name='sqlite_stat1'")
        assert cur.fetchone()[0] == 0
    assert db.analisar(conn) is True
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM sqlite_stat1")
        assert cur.fetchone()[0] > 0, "ANALYZE nao escreveu estatistica nenhuma"


def test_manutencao_diaria_apaga_o_velho_e_reanalisa_na_mesma_passada(conn):
    """A retencao ja rodava sozinha uma vez por dia; o ANALYZE nao rodava nunca. Andam juntos de
    proposito: apagar milhoes de linhas e exatamente o que envelhece a estatistica."""
    import datetime as _dt
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent))
    from semear import limpar_tudo
    from gemeo.core import db
    limpar_tudo(conn)
    velho = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=120)
    novo = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=1)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO usina (codigo, nome, fonte, fonte_ref, tz) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                    ("MAN1", "Manutencao", "sunop", "MAN1", "America/Belem"))
        uid = cur.fetchone()[0]
        cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte, ativo) VALUES (%s,'inversor','I1',1) RETURNING id", (uid,))
        eid = cur.fetchone()[0]
        for ts in (velho, novo):
            cur.execute("INSERT INTO leitura (equipamento_id, medida, ts, valor) VALUES (%s,'p_ac',%s,1.0)", (eid, ts))
    conn.commit()

    texto = db.manutencao_diaria(conn, dias=90)

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM leitura WHERE equipamento_id=%s", (eid,))
        assert cur.fetchone()[0] == 1, "so a leitura de 120 dias devia sair"
        cur.execute("SELECT count(*) FROM sqlite_stat1")
        assert cur.fetchone()[0] > 0, "a manutencao tem de deixar o otimizador com estatistica"
    assert "1 leitura" in texto and "ANALYZE ok" in texto
    limpar_tudo(conn)


def test_a_lista_de_medidas_do_codigo_e_a_mesma_do_CHECK_do_schema(conn):
    """`db.MEDIDAS` existe porque a consulta da ultima leitura precisa fixar a medida para usar a PK
    (equipamento_id, medida, ts) como busca. Se uma migracao futura acrescentar uma medida e esquecer
    esta lista, a consulta simplesmente NAO olha para ela e devolve um carimbo velho — sem erro
    nenhum. Este teste e a trava contra essa falha silenciosa."""
    import re
    from gemeo.core import db
    with conn.cursor() as cur:
        cur.execute("SELECT sql FROM sqlite_master WHERE name='leitura'")
        ddl = cur.fetchone()[0]
    trecho = re.search(r"medida\s+TEXT\s+NOT NULL\s+CHECK\s*\(\s*medida\s+IN\s*\((.*?)\)\s*\)", ddl, re.S | re.I)
    assert trecho, ddl
    no_schema = tuple(m.strip().strip("'") for m in trecho.group(1).split(","))
    assert set(db.MEDIDAS) == set(no_schema), f"codigo={sorted(db.MEDIDAS)} schema={sorted(no_schema)}"
