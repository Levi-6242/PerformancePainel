# gemeo/tests/test_ingest_pg_transacao.py
"""29/09/2026: a descoberta do pg segurava o SQLite do gemeo enquanto esperava o PostgreSQL do Thopen.

`IngestorPG.descobrir` fazia o INSERT do primeiro equipamento — o que abre, implicita, a transacao de ESCRITA do
sqlite3 — e seguia consultando o Postgres dentro do mesmo laco (o ultimo registro de cada inversor, depois os
trackers) ate o commit do fim. Com o Postgres do Thopen lento, a sessao do gemeo passou 21+ min em
`SELECT DISTINCT device_id FROM public.raw_tracker ...` com a escrita aberta, e quem mais grava no arquivo — sunop
fino e lento, apipv, plat, cadastro e o modelar — morreu em 'database is locked' (251 no ingest.log; nenhuma corrida
da SunOp nem da API PV depois das 15:01Z).

A regra agora: o que vem do Postgres vem todo antes; o SQLite grava numa transacao curta, que insiste no lock e que,
ao insistir, nao volta ao Postgres (naquele dia cada consulta levava 20 min).
"""
import datetime as dt
import sqlite3
import sys
import types
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from semear import limpar_tudo  # noqa: E402
from gemeo.core import db  # noqa: E402
from gemeo.core.modelos import UsinaRef  # noqa: E402
from gemeo.ingest.pg import IngestorPG  # noqa: E402

UTC = dt.timezone.utc
AGORA = dt.datetime(2026, 9, 29, 15, 0, tzinfo=UTC)
TS = AGORA - dt.timedelta(minutes=10)
CFG = types.SimpleNamespace(sobreposicao_min=30)

# O que o PostgreSQL do Thopen devolve, no formato do psycopg2: device_id inteiro, json_data ja dict (jsonb).
PLACA = (1234.5, -23.5, -46.6)
DISPOSITIVOS = {"raw_weather_station": [(900,)], "raw_inverter": [(765,), (766,)], "raw_tracker": [(77,)]}
ULTIMO_DO_INVERSOR = {765: {"active_power": 10.0, "string_1_current": 8.0, "string_2_current": 7.5},
                      766: {"active_power": 11.0, "string_1_current": 8.1}}
NOMES = [(765, "Inversor 1.1"), (766, "Inversor 1.2"), (77, "  ")]
REGISTROS = {"raw_weather_station": [(TS, 900, {"irradiance_poa": 800.0})],
             "raw_inverter": [(TS, 765, {"active_power": 10.0, "string_1_current": 8.0})],
             "raw_tracker": [(TS, 77, {"posat": 10.0, "posal": 11.0})]}

# (tipo, codigo_fonte) -> (nome_exibicao, atributos, codigo_fonte do pai). Conferido a mao, e contra o codigo de antes.
EQUIPAMENTOS = {
    ("estacao", "900"): (None, {"numero": 900}, None),
    ("inversor", "765"): ("Inversor 1.1", {"numero": 765}, None),
    ("inversor", "766"): ("Inversor 1.2", {"numero": 766}, None),
    ("string", "765.string_1"): (None, {"numero": 1}, "765"),
    ("string", "765.string_2"): (None, {"numero": 2}, "765"),
    ("string", "766.string_1"): (None, {"numero": 1}, "766"),
    ("tracker", "77"): (None, {"numero": 77}, None),      # nome em branco no tb_devices nao vira nome
}


def _responde(sql: str, params: tuple) -> list:
    if "FROM public.tb_power_plants" in sql:
        return [PLACA]
    if "FROM public.tb_devices" in sql:
        return NOMES
    if sql.startswith("SELECT json_data FROM public.raw_inverter"):
        return [(ULTIMO_DO_INVERSOR[params[1]],)]
    for tabela in DISPOSITIVOS:
        if sql.startswith(f"SELECT DISTINCT device_id FROM public.{tabela} "):
            return DISPOSITIVOS[tabela]
        if sql.startswith(f"SELECT timestamp, device_id, json_data FROM public.{tabela} "):
            return REGISTROS[tabela]
    raise AssertionError(f"consulta que o teste nao conhece: {sql}")


class FontePG:
    """Conexao falsa com o PostgreSQL do Thopen, com a API de cursor que o IngestorPG usa. `ao_consultar(sql)` roda em
    cada execute, ANTES da resposta: e o instante em que, na vida real, o gemeo esta esperando o Postgres."""

    def __init__(self, ao_consultar=None):
        self.ao_consultar = ao_consultar or (lambda sql: None)
        self.consultas: list[tuple[str, str]] = []

    def cursor(self):
        return _CursorPG(self)


class _CursorPG:
    def __init__(self, fonte: FontePG):
        self._fonte, self._linhas = fonte, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        self._fonte.consultas.append((sql, repr(params)))
        self._fonte.ao_consultar(sql)
        self._linhas = _responde(sql, tuple(params))

    def fetchall(self):
        return list(self._linhas)

    def fetchone(self):
        return self._linhas[0] if self._linhas else None


@pytest.fixture
def usina(conn):
    limpar_tudo(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO usina (codigo, nome, fonte, fonte_ref, tz) VALUES ('TESTE PG','TESTE PG','pg','2','America/Sao_Paulo') RETURNING id")
        uid = cur.fetchone()[0]
    conn.commit()
    yield UsinaRef(id=uid, codigo="TESTE PG", fonte="pg", fonte_ref="2", tz="America/Sao_Paulo")
    limpar_tudo(conn)


@pytest.fixture
def outra(conn, usina):
    """Outra conexao ao MESMO arquivo: o papel da sunop, da apipv, da plat, do cadastro e do modelar. Nao espera o lock
    — o que em producao sao 30 s de busy_timeout e 6 tentativas aqui responde na hora. Fecha antes do `usina` limpar."""
    c = db.conectar(db.status(conn)["arquivo"])
    c.execute("PRAGMA busy_timeout=0")
    yield c
    c.rollback()
    c.close()


def _equipamentos(conn, usina_id: int) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT e.tipo, e.codigo_fonte, e.nome_exibicao, e.atributos, p.codigo_fonte FROM equipamento e "
                    "LEFT JOIN equipamento p ON p.id = e.pai_id WHERE e.usina_id=%s", (usina_id,))
        return {(t, c): (n, a, pai) for t, c, n, a, pai in cur.fetchall()}


def test_o_sqlite_fica_livre_enquanto_o_postgres_responde(conn, usina, outra):
    """A cada consulta ao Postgres — descoberta e busca, na ordem do laco do runner — a conexao do gemeo nao pode estar
    em transacao; e, a prova de verdade, outra fonte consegue gravar no arquivo naquele instante."""
    em_transacao, barradas = [], []

    def ao_consultar(sql):
        consulta = sql.split(" WHERE ")[0]
        if conn.in_transaction:
            em_transacao.append(consulta)
        try:
            outra.execute("INSERT INTO estado (chave, valor) VALUES ('teste.outra_fonte', ?) "
                          "ON CONFLICT (chave) DO UPDATE SET valor=excluded.valor", (consulta,))
            outra.commit()
        except sqlite3.OperationalError as e:
            outra.rollback()
            barradas.append(f"{consulta} -> {e}")

    fonte = FontePG(ao_consultar)
    ing = IngestorPG(CFG, conn, [usina], fonte)
    ing.descobrir(usina)                        # o laco do runner: descobrir cada usina, depois o ciclo
    ing.ciclo(agora=AGORA)
    assert len(fonte.consultas) == 10           # descoberta: placa, 3 tabelas, 2 inversores, nomes; busca: 3 tabelas
    assert em_transacao == [], f"consulta ao Postgres com a escrita do SQLite aberta: {em_transacao}"
    assert barradas == [], f"outra fonte barrada no SQLite enquanto o gemeo esperava o Postgres: {barradas}"


def test_descoberta_grava_placa_equipamentos_strings_e_nomes(conn, usina):
    """A correcao muda QUANDO a descoberta grava, nao O QUE grava: placa e coordenadas so onde estava vazio; estacao,
    inversores com as strings do ultimo registro, tracker; nomes do tb_devices. Rodar de novo (o laco roda a cada
    ciclo) nao duplica nem sobrescreve."""
    with conn.cursor() as cur:
        cur.execute("UPDATE usina SET kwp_dc=1000.0 WHERE id=%s", (usina.id,))     # a placa do cadastro continua mandando
    conn.commit()
    ing = IngestorPG(CFG, conn, [usina], FontePG())
    ing.descobrir(usina)
    ing.descobrir(usina)
    with conn.cursor() as cur:
        cur.execute("SELECT kwp_dc, lat, lon FROM usina WHERE id=%s", (usina.id,))
        assert cur.fetchone() == (1000.0, -23.5, -46.6)
    assert _equipamentos(conn, usina.id) == EQUIPAMENTOS


@pytest.mark.parametrize("quando", ["public.tb_power_plants", "public.raw_weather_station", "public.tb_devices"],
                         ids=["placa", "equipamentos", "nomes"])
def test_gravacao_espera_o_lock_sem_voltar_ao_postgres(conn, usina, outra, monkeypatch, quando):
    """Outra fonte pega a escrita do arquivo enquanto o gemeo espera o Postgres e so solta depois. A gravacao da
    descoberta que encontra o arquivo ocupado desfaz, espera e grava — e nenhuma consulta ao Postgres se repete."""
    esperas = []

    def ao_consultar(sql):
        if quando in sql and not esperas and not outra.in_transaction:
            outra.execute("BEGIN IMMEDIATE")           # a outra fonte comeca a gravar e segura o arquivo

    def espera(segundos):                             # a pausa do com_retentativa_de_lock: a outra fonte termina
        esperas.append(segundos)
        outra.commit()

    monkeypatch.setattr(db.time, "sleep", espera)
    conn.execute("PRAGMA busy_timeout=0")              # o gemeo tambem nao espera: o lock responde na hora
    try:
        fonte = FontePG(ao_consultar)
        IngestorPG(CFG, conn, [usina], fonte).descobrir(usina)
    finally:
        conn.execute("PRAGMA busy_timeout=30000")      # o valor do db.conectar
    assert len(esperas) == 1, "a gravacao encontrou o arquivo ocupado e esperou a vez"
    repetidas = [sql for (sql, _), n in Counter(fonte.consultas).items() if n > 1]
    assert repetidas == [], f"a retentativa voltou ao Postgres: {repetidas}"
    assert len(fonte.consultas) == 7
    assert _equipamentos(conn, usina.id) == EQUIPAMENTOS
