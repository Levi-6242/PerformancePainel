# gemeo/gemeo/modelar/grade.py
"""Leituras → DataFrames na grade de 15 min (UTC). Duas origens, mesma estrutura: o banco e os golden
dos spikes — e o segundo que deixa a suite do modelo rodar sem PostgreSQL."""
from __future__ import annotations
import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from gemeo.core.modelos import UsinaRef

MEDIDAS_ESTACAO = ("poa", "ghi", "temp_modulo", "temp_ar")


@dataclass
class Grade:
    usina: UsinaRef
    indice: pd.DatetimeIndex
    estacao: pd.DataFrame
    inv_p: pd.DataFrame
    inv_e: pd.DataFrame
    trk_ang: pd.DataFrame
    trk_alvo: pd.DataFrame
    str_i: pd.DataFrame
    pai: dict[int, int] = field(default_factory=dict)
    tipo: dict[int, str] = field(default_factory=dict)
    atributos: dict[int, dict] = field(default_factory=dict)
    nome: dict[int, str] = field(default_factory=dict)


def _regrade(df: pd.DataFrame, indice: pd.DatetimeIndex) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(index=indice)
    return df.resample("15min").mean().reindex(indice)


def carregar_grade(conn, usina: UsinaRef, ini: dt.datetime, fim: dt.datetime, grade_min: int = 15) -> Grade:
    with conn.cursor() as cur:
        cur.execute("SELECT id, tipo, pai_id, atributos, coalesce(nome_exibicao, codigo_fonte) FROM equipamento WHERE usina_id=%s AND ativo", (usina.id,))
        eqs = cur.fetchall()
        cur.execute("SELECT l.equipamento_id, l.medida, l.ts, l.valor FROM leitura l JOIN equipamento e ON e.id=l.equipamento_id "
                    "WHERE e.usina_id=%s AND l.ts >= %s AND l.ts < %s", (usina.id, ini, fim))
        rows = cur.fetchall()
    tipo = {i: t for i, t, *_ in eqs}; pai = {i: p for i, _, p, *_ in eqs if p}
    atributos = {i: (a or {}) for i, _, _, a, _ in eqs}; nome = {i: n for i, *_, n in eqs}
    df = pd.DataFrame(rows, columns=["eq", "medida", "ts", "valor"])
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    indice = pd.date_range(pd.Timestamp(ini).floor("15min"), pd.Timestamp(fim).ceil("15min"), freq="15min", tz="UTC")
    def _wide(medida, tipos):
        # df["eq"], nunca df.eq: "eq" e METODO do DataFrame e a coluna some atras dele — a CI (primeiro banco real) achou
        sub = df[(df.medida == medida) & df["eq"].map(tipo).isin(tipos)] if not df.empty else df
        if sub.empty:
            return pd.DataFrame(index=indice)
        return _regrade(sub.pivot_table(index="ts", columns="eq", values="valor", aggfunc="mean"), indice)
    est = pd.DataFrame(index=indice)
    for m in MEDIDAS_ESTACAO:
        w = _wide(m, {"estacao"})
        est[m] = w.mean(axis=1) if not w.empty else float("nan")
    return Grade(usina, indice, est, _wide("p_ac", {"inversor"}), _wide("e_dia", {"inversor"}),
                 _wide("angulo", {"tracker"}), _wide("angulo_alvo", {"tracker"}), _wide("i_string", {"string"}), pai, tipo, atributos, nome)


def grade_de_fixture(caminho: Path) -> Grade:
    j = json.load(open(caminho, encoding="utf-8"))
    tz = ZoneInfo(j["tz"])
    def _serie(d: dict) -> pd.Series:
        if not d:
            return pd.Series(dtype=float)
        s = pd.Series({pd.Timestamp(k).tz_localize(tz).tz_convert("UTC"): float(v) for k, v in d.items()})
        return s.sort_index()
    dia = pd.Timestamp(j["dia"]).tz_localize(tz)
    indice = pd.date_range(dia.tz_convert("UTC"), (dia + pd.Timedelta(days=1)).tz_convert("UTC"), freq="15min", inclusive="left")
    est = pd.DataFrame({m: _serie(j["estacao"].get(m, {})) for m in MEDIDAS_ESTACAO}).reindex(indice)
    tipo, pai, atributos, nome = {}, {}, {}, {}
    def _bloco(chave, base, tipo_eq):
        cols = {}
        for k, d in (j.get(chave) or {}).items():
            eid = base + int(str(k).split(".")[-1]) if tipo_eq != "string" else 3000 + int(str(k).split(".")[0]) * 100 + int(str(k).split(".")[1])
            cols[eid] = _serie(d); tipo[eid] = tipo_eq; nome[eid] = f"{tipo_eq} {k}"
            atributos[eid] = {"numero": int(str(k).split(".")[-1])}
            if tipo_eq == "string":
                pai[eid] = 1000 + int(str(k).split(".")[0])
        return pd.DataFrame(cols).reindex(indice) if cols else pd.DataFrame(index=indice)
    inv_p = _bloco("inv_p", 1000, "inversor"); inv_e = _bloco("inv_e_dia", 1000, "inversor")
    trk_ang = _bloco("trk_ang", 2000, "tracker"); trk_alvo = _bloco("trk_alvo", 2000, "tracker")
    str_i = _bloco("str_i", 3000, "string")
    tipo[1] = "estacao"; nome[1] = "ESTM"
    for eid in inv_p.columns:
        atributos[eid].update({"kwp": j["kwp"] / j["n_inv"], "kw_ac": j["kw_ac"] / j["n_inv"]})
    usina = UsinaRef(id=0, codigo=j["usina"], fonte=j["fonte"], fonte_ref="", tz=j["tz"], kwp=j["kwp"], kw_ac=j["kw_ac"], lat=-2.05, lon=-47.55)
    return Grade(usina, indice, est, inv_p, inv_e, trk_ang, trk_alvo, str_i, pai, tipo, atributos, nome)
