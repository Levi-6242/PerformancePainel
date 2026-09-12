# gemeo/tests/test_tools_backfill_apipv.py
"""`gemeo/tools/backfill_apipv.py`: refaz dias passados de UMA usina da API PV (o custom_query de inversor leva ~146 s por
usina e a API nao aguenta paralelismo). Nasceu em 11/09/2026: a rede caiu das 20:00 as 21:08 no primeiro ciclo e os dias
08 a 10/09 das tres da 2C ficaram sem inversor. Grava pelo mesmo upsert do ingest e deixa rastro em ingest_run."""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1]))
from semear import limpar_tudo  # noqa: E402
from gemeo.core.modelos import UsinaRef  # noqa: E402
from gemeo.ingest.base import Busca  # noqa: E402
from tools import backfill_apipv  # noqa: E402

UTC = dt.timezone.utc


def test_janela_em_dias_de_brasilia_vira_utc_com_fim_exclusivo():
    ini, fim = backfill_apipv.janela("2026-09-08", "2026-09-11")
    assert ini == dt.datetime(2026, 9, 8, 3, 0, tzinfo=UTC) and fim == dt.datetime(2026, 9, 11, 3, 0, tzinfo=UTC)


def test_rodar_grava_pelo_upsert_e_registra_a_corrida(conn):
    limpar_tudo(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO usina (codigo, nome, fonte, fonte_ref, tz) VALUES ('Araputanga','Araputanga','apipv','18771898','America/Cuiaba') RETURNING id")
        uid = cur.fetchone()[0]
        cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte) VALUES (%s,'inversor','400771') RETURNING id", (uid,))
        eid = cur.fetchone()[0]
    conn.commit()
    u = UsinaRef(uid, "Araputanga", "apipv", "18771898", "America/Cuiaba")
    ts = dt.datetime(2026, 9, 10, 15, 0, tzinfo=UTC)

    class Ing:
        fonte = "apipv"
        def buscar(self, usina, ini, fim):
            assert usina is u
            return Busca(leituras=[(eid, "p_ac", ts, 100.0), (eid, "e_dia", ts, None)], n_requisicoes=6, esperadas=1)

    ini, fim = backfill_apipv.janela("2026-09-10", "2026-09-11")
    res = backfill_apipv.rodar(Ing(), conn, u, ini, fim)
    assert res["n_linhas"] == 1 and res["n_requisicoes"] == 6 and res["status"] == "ok" and res["por_medida"] == {"p_ac": 1}
    with conn.cursor() as cur:
        cur.execute("SELECT valor FROM leitura WHERE equipamento_id=%s AND medida='p_ac'", (eid,))
        assert cur.fetchone()[0] == 100.0
        cur.execute("SELECT fonte, status, n_linhas, n_requisicoes FROM ingest_run WHERE usina_id=%s", (uid,))
        assert cur.fetchone() == ("apipv", "ok", 1, 6)
    limpar_tudo(conn)
