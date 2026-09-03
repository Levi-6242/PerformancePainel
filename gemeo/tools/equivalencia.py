# gemeo/tools/equivalencia.py
"""Regra de mudanca da spec (§11): lote, periodo, gate ou fusao alterados -> equivalencia com tolerancia
1e-6 sobre um dia real, numero no PR. Roda o modelo duas vezes sobre a MESMA fixture golden (A = parametros
de referencia, B = candidatos) e imprime a maior diferenca absoluta por serie. Tudo aqui compara por
tolerancia; igualdade exata de float e proibida no projeto."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import numpy as np

from gemeo.modelar import decomposicao as dc
from gemeo.modelar import esperado, gate, grade, rollup


def _pipeline(fixture: Path, pg: gate.ParamsGate, pm: dict, trk_inv: dict[int, int] | None) -> dict:
    g = grade.grade_de_fixture(fixture)
    r = gate.avaliar(g.estacao, None, pg, g.usina.tz)
    params = {i: esperado.ParamsModelo(kwp=g.atributos[i]["kwp"], pac0_kw=g.atributos[i]["kw_ac"], **pm) for i in g.inv_p.columns}
    esp = esperado.esperado_por_inversor(g, r, params)
    d = dc.decompor(g, esp, trk_inv or {}, dc.ParamsDecomp())
    c = rollup.cascata(g, r, esp, d)
    return {"esperado_kw": esp.sum(axis=1), "gate_ok": (r.gate == "ok").astype(float), "parado": d.parado.sum(axis=1),
            "tracker": d.tracker.sum(axis=1), "string": d.string.sum(axis=1), "residuo": d.residuo.sum(axis=1),
            "cascata": c.por_dia.iloc[0].astype(float)}


def rodar(fixture: Path, gate_a: gate.ParamsGate, gate_b: gate.ParamsGate, modelo_a: dict, modelo_b: dict,
          trk_inv: dict[int, int] | None = None) -> dict[str, float]:
    a, b = _pipeline(fixture, gate_a, modelo_a, trk_inv), _pipeline(fixture, gate_b, modelo_b, trk_inv)
    out = {}
    for k in a:
        va, vb = a[k].fillna(0.0).values, b[k].fillna(0.0).values
        out[k] = float(np.max(np.abs(va - vb))) if len(va) else 0.0
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="equivalencia A (referencia) x B (candidato) sobre uma fixture golden")
    p.add_argument("fixture")
    p.add_argument("--tol", type=float, default=1e-6)
    p.add_argument("--b-perdas", type=float); p.add_argument("--b-eta", type=float); p.add_argument("--b-gamma", type=float)
    p.add_argument("--b-razao-min", type=float); p.add_argument("--b-razao-max", type=float); p.add_argument("--b-horas-min", type=float)
    a = p.parse_args(argv)
    mb = {k: v for k, v in (("perdas_fixas", a.b_perdas), ("eta_inv", a.b_eta), ("gamma", a.b_gamma)) if v is not None}
    gb = {k: v for k, v in (("razao_min", a.b_razao_min), ("razao_max", a.b_razao_max), ("horas_min_dia", a.b_horas_min)) if v is not None}
    res = rodar(Path(a.fixture), gate.ParamsGate(), gate.ParamsGate(**gb), {}, mb)
    pior = max(res.values())
    print(json.dumps({"fixture": a.fixture, "tolerancia": a.tol, "max_abs_diff": res, "equivalente": bool(pior <= a.tol)}, ensure_ascii=False, indent=1))
    return 0 if pior <= a.tol else 1


if __name__ == "__main__":
    raise SystemExit(main())
