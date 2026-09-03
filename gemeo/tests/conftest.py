# gemeo/tests/conftest.py
"""Banco de teste = GEMEO_TEST_DSN (um PostgreSQL local). Sem a variável, os testes de banco são
PULADOS e não falham: a máquina do analista não tem PostgreSQL (verificado 03/09) e a suíte de
modelo/gate/decomposição — que é pandas puro — precisa rodar mesmo assim."""
import os
import pytest
import psycopg2

DSN = os.environ.get("GEMEO_TEST_DSN")


@pytest.fixture(scope="session")
def _conn_sessao():
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


@pytest.fixture
def conn(_conn_sessao):
    """Por teste: rollback antes de entregar e depois de usar — um teste que morre no meio de uma transacao deixa a
    conexao abortada e derrubaria todos os seguintes (a CI de 03/09 mostrou 3 falhas em cascata por isso)."""
    _conn_sessao.rollback()
    yield _conn_sessao
    _conn_sessao.rollback()
