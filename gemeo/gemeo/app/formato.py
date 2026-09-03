# gemeo/gemeo/app/formato.py
"""Numeros em pt-BR para as telas: virgula decimal, ponto de milhar, travessao para o que nao existe.
O sinal de menos e o tipografico (U+2212), como nos mockups."""
from __future__ import annotations
import datetime as dt


def num(v: float | None, casas: int = 1) -> str:
    if v is None:
        return "—"
    s = f"{abs(v):,.{casas}f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return ("−" if v < 0 else "") + s


def mw(kw: float | None) -> str:
    if kw is None:
        return "—"
    v = kw / 1000.0
    return num(v, 2) if abs(v) < 1 else num(v, 1)


def pct(frac: float | None, casas: int = 1) -> str:
    return "—" if frac is None else num(frac * 100.0, casas) + "%"


def brl(v: float | None) -> str:
    if v is None:
        return "—"
    return f"R$ {num(v / 1000.0, 1)} mil" if abs(v) >= 1000 else f"R$ {num(v, 0)}"


def idade(ts: dt.datetime | None, agora: dt.datetime) -> str:
    if ts is None:
        return "nunca"
    m = int((agora - ts).total_seconds() // 60)
    return f"{m} min" if m < 120 else f"{m // 60} h"
