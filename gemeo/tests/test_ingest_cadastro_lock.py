# gemeo/tests/test_ingest_cadastro_lock.py
"""05:18 de 12/09/2026: a fonte plat gravava 17 mil angulos da Araputanga e o `aplicar_trackers` do cadastro morreu em
'database is locked' (log do ingest) — a passada inteira do cadastro foi perdida e a marca de versao nao foi gravada. As
fontes ja insistem (`db.com_retentativa_de_lock`); o cadastro tem de insistir igual."""
import sqlite3
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from semear import limpar_tudo  # noqa: E402
from gemeo.core import db  # noqa: E402
from gemeo.ingest import cadastro  # noqa: E402


def test_ciclo_do_cadastro_insiste_quando_o_banco_esta_travado(conn, monkeypatch):
    monkeypatch.setattr(db, "PAUSA_LOCK_S", 0.0)
    monkeypatch.setattr(cadastro, "_get", lambda *a, **k: [{"key": "bd_performance", "updated_at": "2026-09-12T05:00"}])
    monkeypatch.setattr(cadastro.IngestorCadastro, "_sheets", lambda self: {"equipamentos": {"id": 1}, "info geral": {"id": 2}, "bd_trackers": {"id": 3}})
    monkeypatch.setattr(cadastro, "linhas_da_aba", lambda *a, **k: [])
    chamadas = {"n": 0}

    def trava_uma_vez(conn_, dados):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return {"mapeados": 0, "sem_inversor": 0}
    monkeypatch.setattr(cadastro, "aplicar_trackers", trava_uma_vez)
    limpar_tudo(conn)
    cfg = types.SimpleNamespace(bd_api_base="http://bd", bd_api_token="t", usinas_piloto=("MRO100",))
    res = cadastro.IngestorCadastro(cfg, conn, http=None).ciclo(force=True)
    assert res["mudou"] and chamadas["n"] == 2 and res["trackers"] == {"mapeados": 0, "sem_inversor": 0}
    assert db.ler_estado(conn, "cadastro.updated_at") == f"2026-09-12T05:00|{cadastro.VERSAO_CADASTRO}"   # a passada terminou
    limpar_tudo(conn)
