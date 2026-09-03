# gemeo/tests/conftest.py
"""Banco de teste = GEMEO_TEST_DSN (um PostgreSQL local). Sem a variável, os testes de banco são
PULADOS e não falham: a máquina do analista não tem PostgreSQL (verificado 03/09) e a suíte de
modelo/gate/decomposição — que é pandas puro — precisa rodar mesmo assim."""
import os
import pytest
import psycopg2

DSN = os.environ.get("GEMEO_TEST_DSN")


@pytest.fixture(scope="session")
def conn():
    if not DSN:
        pytest.skip("GEMEO_TEST_DSN nao definido: sem PostgreSQL de teste")
    c = psycopg2.connect(DSN)
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS gemeo CASCADE; CREATE SCHEMA gemeo;")
    c.autocommit = False
    from gemeo.core import db
    with c.cursor() as cur:
        cur.execute("SET search_path TO gemeo, public")
    db.migrar(c)
    yield c
    c.close()
