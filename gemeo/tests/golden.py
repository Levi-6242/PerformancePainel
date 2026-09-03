# gemeo/tests/golden.py
"""Atalhos dos golden tests: fixture -> grade -> gate -> esperado de placa (kwp e kw_ac do proprio
inversor), e o de-para tracker->inversor da MRO100 congelado em mro100_trk_inv.json (aba BD_Trackers)."""
import json
from pathlib import Path

import pandas as pd

from gemeo.modelar import esperado, gate, grade

G = Path(__file__).parent / "fixtures" / "golden"


def esperado_de_placa(caminho: Path):
    g = grade.grade_de_fixture(caminho)
    r = gate.avaliar(g.estacao, None, gate.ParamsGate(), g.usina.tz)
    params = {i: esperado.ParamsModelo(kwp=g.atributos[i]["kwp"], pac0_kw=g.atributos[i]["kw_ac"]) for i in g.inv_p.columns}
    return g, r, esperado.esperado_por_inversor(g, r, params)


def sem_gate(g) -> gate.Resultado:
    """Gate 'ok' em todo slot — para a grade sintetica, que tem 2 h e nunca passaria nas 8 h minimas do dia."""
    return gate.Resultado(gate=pd.Series("ok", index=g.indice, dtype=object))


def veredito(caminho: Path) -> dict:
    """O veredito do spike congelado na fixture e o contrato do golden test — quem muda o numero muda a fixture."""
    return json.load(open(caminho, encoding="utf-8"))["veredito_esperado"]


def trk_inv_mro100(g) -> dict[int, int]:
    # "Inversor 1.4" -> INV_4 -> id 1004. O skid 2 numera de outro jeito (pendencia do de-para, ver spec §13):
    # o que nao casa com um inversor da grade fica SEM inversor, e e assim que o modelo deve tratar.
    m = json.load(open(G / "mro100_trk_inv.json", encoding="utf-8"))
    out = {}
    for n, nome in m.items():
        eid = 1000 + int(str(nome).split(".")[-1])
        if eid in g.inv_p.columns:
            out[2000 + int(n)] = eid
    return out
