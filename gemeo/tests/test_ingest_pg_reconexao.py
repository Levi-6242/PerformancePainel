# gemeo/tests/test_ingest_pg_reconexao.py
"""A conexão com o PostgreSQL do Thopen cai — e agora VOLTA (28/09/2026).

De 27/09 13:50 UTC até a manhã de 28/09 as 18 usinas do banco do Thopen ficaram sem coleta: o `rodar()` abria a
conexão UMA vez, na partida, e ela nunca fazia commit — a sessão ficava "ociosa em transação" por dias, segurando a
limpeza do banco do Thopen. Quando o servidor a derrubou, todo ciclo seguinte morreu em `psycopg2.InterfaceError:
connection already closed` e o /healthz respondeu 503. E se o banco não respondesse na partida, o `psycopg2.connect`
derrubava a coleta inteira, SunOp e API PV juntas.

Agora a coleta do banco recebe uma FÁBRICA de conexão: abre quando precisa, só leitura em autocommit (nenhuma
transação aberta entre ciclos), e reabre quando a conexão está fechada. Banco fora vira falha do ciclo do pg — o laço
registra e tenta de novo — e as outras fontes nem ficam sabendo.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from gemeo.ingest import runner  # noqa: E402
from gemeo.ingest.pg import IngestorPG  # noqa: E402

CFG = type("C", (), {})()


class Conn:
    def __init__(self):
        self.closed = 0
        self.autocommit = False


def test_nao_conecta_ao_montar_e_reabre_quando_a_conexao_cai():
    abertas = []

    def fabrica():
        c = Conn()
        abertas.append(c)
        return c

    ing = IngestorPG(CFG, None, [], fabrica)
    assert abertas == [], "construir não conecta: a coleta sobe mesmo com o banco do Thopen fora"
    c1 = ing.fonte_conn
    assert len(abertas) == 1 and ing.fonte_conn is c1, "conexão viva é reusada, não reaberta a cada consulta"
    c1.closed = 1                                     # o servidor derrubou a sessão (o caso de 27/09)
    c2 = ing.fonte_conn
    assert c2 is not c1 and len(abertas) == 2
    c2.closed = 2                                     # conexão quebrada no meio de uma consulta (OperationalError)
    assert ing.fonte_conn is not c2 and len(abertas) == 3


def test_conexao_da_fonte_nasce_em_autocommit():
    ing = IngestorPG(CFG, None, [], Conn)
    assert ing.fonte_conn.autocommit is True, "só leitura: nenhuma transação aberta de um ciclo para o outro"


def test_banco_fora_falha_so_o_uso_e_tenta_de_novo_depois():
    tentativas = []

    def fabrica():
        tentativas.append(1)
        if len(tentativas) == 1:
            raise ConnectionError("could not connect to server")
        return Conn()

    ing = IngestorPG(CFG, None, [], fabrica)
    with pytest.raises(ConnectionError):
        _ = ing.fonte_conn                            # o erro fica no ciclo do pg — o laço registra e repete
    assert ing.fonte_conn.closed == 0 and len(tentativas) == 2, "no ciclo seguinte, conecta"


def test_conexao_pronta_continua_servindo():
    """Compatibilidade: quem entrega a conexão já aberta (os testes antigos) segue funcionando."""
    c = Conn()
    ing = IngestorPG(CFG, None, [], c)
    assert ing.fonte_conn is c


def test_rodar_entrega_uma_fabrica_e_nao_abre_o_banco_na_partida():
    fonte = Path(runner.__file__).read_text(encoding="utf-8")
    ini = fonte.index("def rodar(")
    corpo = fonte[ini:]
    assert "conn_fonte = psycopg2.connect(" not in corpo, "a conexão não pode mais nascer na partida"
    assert "_fabrica_pg(" in corpo
    fab = fonte[fonte.index("def _fabrica_pg("):ini]
    assert "psycopg2.connect(" in fab and "connect_timeout" in fab
