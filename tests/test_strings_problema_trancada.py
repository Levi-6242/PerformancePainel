# -*- coding: utf-8 -*-
"""Trancada não pode aparecer na sub-aba "sem corrente" (Levi, 08/07) — nem vinda do snapshot.

Achado da varredura de 09/09/2026, colhido enquanto se verificava o achado crítico das travas: a rota
que tranca diz, em comentário, que "PG e 2C reaplicam a régua na LEITURA → não precisam" de
invalidação. O 2C reaplica mesmo; o PG NÃO — `_strings_problema_rows("pg")` lê o `status` cru do
snapshot que o WORKER construiu. Entre trancar a string e o worker publicar um snapshot novo, ela
continuava listada como "sem corrente" (e o sino continuava contando).
"""
import app


def _snap():
    return ([{"plant_id": 7, "usina": "Usina P"}],
            {7: [{"id": 55, "nome": "INV 1", "nome_api": "INV 1", "strings": [
                {"id": "3", "corrente": 0.0, "status": "sem_corrente"},
                {"id": "4", "corrente": 0.0, "status": "sem_corrente"},
                {"id": "5", "corrente": 8.2, "status": "ativa"}]}]})


def test_pg_reaplica_a_trava_na_leitura(monkeypatch):
    monkeypatch.setattr(app, "_pg_get_snapshot", lambda force=False: _snap())
    monkeypatch.setattr(app, "_trancadas", {app._str_key(7, 55, "3")})
    monkeypatch.setattr(app, "_TRANC_INV", {("55", "3")})
    rows = app._strings_problema_rows("pg")
    assert [r["string"] for r in rows] == ["4"], \
        "a string trancada voltou para a sub-aba 'sem corrente' pelo snapshot do worker"


def test_pg_sem_trava_lista_as_duas(monkeypatch):
    """Controle: sem trava nenhuma, as duas sem corrente continuam aparecendo."""
    monkeypatch.setattr(app, "_pg_get_snapshot", lambda force=False: _snap())
    monkeypatch.setattr(app, "_trancadas", set())
    monkeypatch.setattr(app, "_TRANC_INV", set())
    rows = app._strings_problema_rows("pg")
    assert [r["string"] for r in rows] == ["3", "4"]
