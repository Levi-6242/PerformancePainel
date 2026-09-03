# gemeo/tests/conftest.py
"""Banco de teste = um SQLite temporario por sessao (03/09/2026: saiu o PostgreSQL). Os testes de banco rodam em
QUALQUER maquina, sem servidor nem variavel de ambiente — antes pulavam sem GEMEO_TEST_DSN e so a CI os via."""
import pytest

from gemeo.core import db


@pytest.fixture(scope="session")
def _conn_sessao(tmp_path_factory):
    caminho = tmp_path_factory.mktemp("banco") / "gemeo_teste.sqlite"
    c = db.conectar(caminho)
    db.migrar(c)
    yield c
    c.close()


@pytest.fixture
def conn(_conn_sessao):
    """Por teste: rollback antes de entregar e depois de usar — um teste que morre no meio de uma transacao deixaria
    a conexao com transacao aberta e derrubaria os seguintes (a CI de 03/09 mostrou 3 falhas em cascata por isso)."""
    _conn_sessao.rollback()
    yield _conn_sessao
    _conn_sessao.rollback()
