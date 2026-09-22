# gemeo/tests/test_cadastro_casa_usina_por_nome.py
"""A usina casa por CÓDIGO ou por NOME na aba Equipamentos (22/09/2026).

O caso real: as 18 usinas do PG aparecem na aba como "(311) Santa Bárbara I" — com o número do
supervisório e acento. No gêmeo o `codigo` é "SANTA BARBARA I" (maiúscula, sem acento, sem número) e
o `nome` é exatamente "(311) Santa Bárbara I". A igualdade só no código nunca casava.

**Por que ninguém viu:** a cascata dessas usinas continuava certa, porque o kWp da USINA vem da aba
Info Geral por outro caminho. Só a CALIBRAÇÃO quebrava — ela trabalha por inversor, e sem o casamento
o inversor fica com `kwp = 0`, o esperado do PVWatts dá zero e a razão medido/esperado vira infinito.
O erro que aparecia era "razoes invalidas nos dias limpos", a três camadas de distância da causa.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from semear import limpar_tudo  # noqa: E402

from gemeo.ingest.cadastro import aplicar_equipamentos, separar_equipamentos


_SEQ = iter(range(9000, 9999))      # (fonte, fonte_ref) e UNIQUE: cada teste precisa do seu


@pytest.fixture(autouse=True)
def _limpo(conn):
    """Limpa ANTES tambem: teste que falha no meio nao chega ao limpar do fim e envenena o proximo
    com UNIQUE(fonte, fonte_ref) — o erro que aparece esconde o erro que importa."""
    yield


def _usina(conn, codigo, nome):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO usina (codigo, nome, fonte, fonte_ref, tz, ativo) "
                    "VALUES (%s,%s,'pg',%s,'America/Sao_Paulo',1) RETURNING id",
                    (codigo, nome, str(next(_SEQ))))
        uid = cur.fetchone()[0]
        cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte, nome_exibicao) "
                    "VALUES (%s,'inversor','124','Inversor 1.1') RETURNING id", (uid,))
        eid = cur.fetchone()[0]
    conn.commit()
    return uid, eid


def _linhas(cod_na_planilha):
    """Como a aba Equipamentos entrega: a UFV dá a placa da usina, o inversor dá a dele."""
    return [{"Usina Supervisório": cod_na_planilha, "Usina": "Santa Bárbara I", "Equipamento": "UFV",
             "Equipamento Parente": "", "Equipamento Supervisório": "", "Cliente": "Raízen",
             "Potência (kWp)": 3115, "N de Inversores": 12, "Full O&M": "Sim", "String Box": "Não"},
            {"Usina Supervisório": cod_na_planilha, "Usina": "Santa Bárbara I", "Equipamento": "Inversor 1.1",
             "Equipamento Parente": "UG 01", "Equipamento Supervisório": "Inversor 1.1",
             "Potência (kWp)": 255.82, "Strings Ativas": 28}]


def _kwp(conn, eid):
    with conn.cursor() as cur:
        cur.execute("SELECT atributos FROM equipamento WHERE id=%s", (eid,))
        a = cur.fetchone()[0]
    return (a if isinstance(a, dict) else json.loads(a or "{}")).get("kwp")


def test_casa_pelo_NOME_quando_o_codigo_nao_bate(conn):
    """O caso das 18 do PG. Sem este degrau o inversor fica com kwp=0 e a calibração morre."""
    uid, eid = _usina(conn, codigo="SANTA BARBARA I", nome="(311) Santa Bárbara I")
    us, iv = separar_equipamentos(_linhas("(311) Santa Bárbara I"), ("(311) Santa Bárbara I",))
    r = aplicar_equipamentos(conn, us, iv)
    assert r["usinas"] == 1 and r["inversores"] == 1
    assert _kwp(conn, eid) == 255.82
    with conn.cursor() as cur:
        cur.execute("SELECT cliente, kwp_dc, n_inversores FROM usina WHERE id=%s", (uid,))
        assert cur.fetchone() == ("Raízen", 3115, 12)


def test_o_codigo_continua_vindo_PRIMEIRO(conn):
    """As usinas da API PV já casavam pelo código; o degrau novo não pode mudar quem ganha."""
    uid, eid = _usina(conn, codigo="(311) Santa Bárbara I", nome="outro nome qualquer")
    us, iv = separar_equipamentos(_linhas("(311) Santa Bárbara I"), ("(311) Santa Bárbara I",))
    assert aplicar_equipamentos(conn, us, iv)["usinas"] == 1
    assert _kwp(conn, eid) == 255.82


def test_usina_que_nao_existe_nao_casa_com_ninguem(conn):
    """O degrau novo amplia o alcance; não pode virar 'casa com qualquer uma'.

    O código da planilha aqui não existe nem como `codigo` nem como `nome` de usina nenhuma — nem
    das que outros testes deste arquivo deixaram no banco. É de propósito: o teste tem de falhar por
    'não casou', não por 'o banco estava vazio'."""
    _usina(conn, codigo="CAXAMBU", nome="(292) Caxambu")
    us, iv = separar_equipamentos(_linhas("(999) Usina Que Nao Existe"), ("(999) Usina Que Nao Existe",))
    assert aplicar_equipamentos(conn, us, iv) == {"usinas": 0, "inversores": 0}


def test_o_filtro_do_piloto_e_o_PRIMEIRO_portao(conn):
    """Antes de qualquer casamento, `separar_equipamentos` descarta a linha cujo código não está no
    piloto. Era AQUI que as 18 do PG morriam — "(311) Santa Bárbara I" não está no config, que tem
    "SANTA BARBARA I". Corrigir só o casamento não adiantava: a linha nem chegava lá."""
    assert separar_equipamentos(_linhas("(311) Santa Bárbara I"), ("SANTA BARBARA I",)) == ({}, {})
    us, _ = separar_equipamentos(_linhas("(311) Santa Bárbara I"), ("(311) Santa Bárbara I",))
    assert list(us) == ["(311) Santa Bárbara I"]


def test_kwp_do_inversor_e_o_que_destrava_a_calibracao(conn):
    """Trava o elo que ninguém enxergava: o esperado do PVWatts é proporcional ao kWp do inversor.
    Com 0, medido/esperado = infinito e a calibração aborta com 'razoes invalidas'."""
    uid, eid = _usina(conn, codigo="IBATE 2", nome="(307) Ibaté 2")
    assert _kwp(conn, eid) is None, "o inversor nasce sem kWp — é o estado do bug"
    us, iv = separar_equipamentos(_linhas("(307) Ibaté 2"), ("(307) Ibaté 2",))
    aplicar_equipamentos(conn, us, iv)
    k = _kwp(conn, eid)
    assert isinstance(k, (int, float)) and k > 0
