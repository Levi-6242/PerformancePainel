# gemeo/tests/semear.py
"""Semeia o banco de teste com uma fixture golden: usina, equipamentos (estacao, inversores, trackers com
pai pelo de-para, strings) e leituras em UTC. Devolve a UsinaRef e o mapa 'chave da fixture' -> id.
Serve ao teste do job (Tarefa 16) e aos do app (Tarefa 18)."""
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from gemeo.core import db
from gemeo.core.modelos import UsinaRef


def semear_fixture(conn, caminho: Path, trk_inv: dict[str, str] | None = None) -> tuple[UsinaRef, dict]:
    j = json.load(open(caminho, encoding="utf-8"))
    tz = ZoneInfo(j["tz"]); n_inv = int(j["n_inv"])
    ids: dict[str, int] = {}
    with conn.cursor() as cur:
        cur.execute("INSERT INTO usina (codigo, nome, fonte, fonte_ref, tz, kwp_dc, kw_ac, n_inversores, lat, lon) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (j["usina"], j["usina"], j["fonte"], j["usina"], j["tz"], j["kwp"], j["kw_ac"], n_inv, -2.05, -47.55))
        uid = cur.fetchone()[0]

        def eq(tipo, codigo, pai=None, atributos=None):
            cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte, pai_id, atributos) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                        (uid, tipo, codigo, pai, json.dumps(atributos or {})))
            return cur.fetchone()[0]

        ids["estacao"] = eq("estacao", "ESTM")
        for n in j["inv_p"]:
            ids[f"inv:{n}"] = eq("inversor", f"INV_{n}", None, {"numero": int(n), "kwp": j["kwp"] / n_inv, "kw_ac": j["kw_ac"] / n_inv})
        for n in (j.get("trk_ang") or {}):
            pai = ids.get("inv:" + str(trk_inv[n]).split(".")[-1]) if trk_inv and n in trk_inv else None
            ids[f"trk:{n}"] = eq("tracker", f"TRK_{n}", pai, {"numero": int(n)})
        for k in (j.get("str_i") or {}):
            i, s = k.split(".")
            ids[f"str:{k}"] = eq("string", f"INV_{i}.I_PV{s}", ids[f"inv:{i}"], {"numero": int(s)})
    conn.commit()

    def ts_utc(k):
        return pd.Timestamp(k).tz_localize(tz).tz_convert("UTC").to_pydatetime()

    linhas = [(ids["estacao"], m, ts_utc(k), v) for m, serie in j["estacao"].items() for k, v in serie.items()]
    for chave, pref, medida in (("inv_p", "inv", "p_ac"), ("inv_e_dia", "inv", "e_dia"), ("trk_ang", "trk", "angulo"),
                                ("trk_alvo", "trk", "angulo_alvo"), ("str_i", "str", "i_string")):
        for k, serie in (j.get(chave) or {}).items():
            linhas += [(ids[f"{pref}:{k}"], medida, ts_utc(t), v) for t, v in serie.items()]
    db.upsert_leituras(conn, linhas)
    usina = UsinaRef(id=uid, codigo=j["usina"], fonte=j["fonte"], fonte_ref=j["usina"], tz=j["tz"], kwp=j["kwp"], kw_ac=j["kw_ac"], lat=-2.05, lon=-47.55)
    return usina, ids
