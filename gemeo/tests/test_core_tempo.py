# gemeo/tests/test_core_tempo.py
"""Tudo em UTC aware. Naive levanta erro: foi um filtro sem fuso que zerou o resultado em silencio
no dbt ('ultimas 2 horas' caiu no futuro)."""
import datetime as dt
import pytest
from gemeo.core import tempo

UTC = dt.timezone.utc


def test_piso_grade_arredonda_para_baixo():
    assert tempo.piso_grade(dt.datetime(2026, 9, 3, 12, 14, 59, tzinfo=UTC)) == dt.datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    assert tempo.piso_grade(dt.datetime(2026, 9, 3, 12, 15, tzinfo=UTC)) == dt.datetime(2026, 9, 3, 12, 15, tzinfo=UTC)


def test_naive_e_erro():
    with pytest.raises(ValueError):
        tempo.piso_grade(dt.datetime(2026, 9, 3, 12, 0))


def test_janela_sem_marca_volta_dias_iniciais():
    agora = dt.datetime(2026, 9, 3, 12, 7, tzinfo=UTC)
    ini, fim = tempo.janela(agora, None, sobreposicao_min=30, dias_iniciais=3)
    assert ini == agora - dt.timedelta(days=3) and fim == agora


def test_janela_incremental_volta_a_sobreposicao():
    agora = dt.datetime(2026, 9, 3, 12, 7, tzinfo=UTC)
    marca = dt.datetime(2026, 9, 3, 11, 45, tzinfo=UTC)
    ini, fim = tempo.janela(agora, marca, sobreposicao_min=30)
    assert ini == dt.datetime(2026, 9, 3, 11, 15, tzinfo=UTC) and fim == agora


def test_janela_reconciliar_volta_24h():
    agora = dt.datetime(2026, 9, 3, 12, 7, tzinfo=UTC)
    ini, _ = tempo.janela(agora, agora - dt.timedelta(minutes=10), sobreposicao_min=30, reconciliar=True)
    assert ini == agora - dt.timedelta(hours=24)


def test_dia_local_usa_o_fuso_da_usina():
    # 02:30 UTC de 04/09 ainda e 23:30 de 03/09 em Belem (UTC-3)
    assert tempo.dia_local(dt.datetime(2026, 9, 4, 2, 30, tzinfo=UTC), "America/Belem") == dt.date(2026, 9, 3)


def test_janela_solar():
    j = ("05:40", "18:20")
    assert tempo.dentro_janela_solar(dt.datetime(2026, 9, 3, 15, 0, tzinfo=UTC), "America/Belem", j)     # 12:00 local
    assert not tempo.dentro_janela_solar(dt.datetime(2026, 9, 3, 23, 0, tzinfo=UTC), "America/Belem", j) # 20:00 local
