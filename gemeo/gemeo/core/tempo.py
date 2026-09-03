# gemeo/gemeo/core/tempo.py
"""Tempo: grade de 15 min, janela incremental e fuso da usina. Tudo aware em UTC — naive e erro."""
from __future__ import annotations
import datetime as dt
from zoneinfo import ZoneInfo

GRADE_MIN = 15


def _exige_aware(ts: dt.datetime) -> None:
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError(f"timestamp sem fuso: {ts!r} — tudo no gemeo e aware em UTC")


def piso_grade(ts: dt.datetime, minutos: int = GRADE_MIN) -> dt.datetime:
    _exige_aware(ts)
    return ts.replace(minute=(ts.minute // minutos) * minutos, second=0, microsecond=0)


def janela(agora: dt.datetime, marca: dt.datetime | None, sobreposicao_min: int,
           reconciliar: bool = False, dias_iniciais: int = 3) -> tuple[dt.datetime, dt.datetime]:
    """Inicio da busca: sem marca d'agua = `dias_iniciais` para tras (primeiro ciclo de uma usina);
    com marca = marca menos a sobreposicao (a ingestao das fontes atrasa); reconciliar = 24h inteiras,
    uma vez por dia, para pegar correcao feita la atras."""
    _exige_aware(agora)
    if reconciliar:
        return agora - dt.timedelta(hours=24), agora
    if marca is None:
        return agora - dt.timedelta(days=dias_iniciais), agora
    _exige_aware(marca)
    return marca - dt.timedelta(minutes=sobreposicao_min), agora


def dia_local(ts: dt.datetime, tz: str) -> dt.date:
    _exige_aware(ts)
    return ts.astimezone(ZoneInfo(tz)).date()


def dentro_janela_solar(agora: dt.datetime, tz: str, janela_hm: tuple[str, str]) -> bool:
    _exige_aware(agora)
    local = agora.astimezone(ZoneInfo(tz))
    h0, m0 = map(int, janela_hm[0].split(":")); h1, m1 = map(int, janela_hm[1].split(":"))
    minuto = local.hour * 60 + local.minute
    return h0 * 60 + m0 <= minuto <= h1 * 60 + m1
