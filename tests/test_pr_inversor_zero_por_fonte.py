# -*- coding: utf-8 -*-
"""Inversor que gerou ZERO é 'morto', não 'sem dado' — e a régua tem de ser a mesma nas 5 fontes.

Achado da varredura de 09/09/2026: `_sunop_pr_one` (Athon/Axis) testava a geração por VERDADE
(`if eday`), então 0,0 kWh — inversor que reportou o dia inteiro e não produziu nada — saía como
`geracao_kwh=None` e `pr=None`. Consequência na tela do PR por inversor: ele cai em "sem dado",
some da mediana e o `abaixo` de `_sunop_pr_build` (que exige `pr is not None`) NÃO o conta como
abaixo dos pares. O inversor morto era exatamente o que a tela existia para achar.

As outras três fontes já usavam `is not None` — API PV (`_pv_pr_compute`), PG (`_pg_pr_build`) e
SolarEdge —, então a MESMA coluna tinha régua diferente conforme a usina. A régua da casa está no
BD_Performance: zero é vermelho, nulo é amarelo; invisível não é opção.
"""
import app


def _monta(monkeypatch, eday_por_inv):
    meta = {"inv_other": {nome: {"EPD": f"U.{nome}.EPD"} for nome in eday_por_inv},
            "plant_paths": {"POA": "U.ESTM.POA.IRAD"}, "etm_stations": {}}
    monkeypatch.setattr(app, "_si", lambda inst="gridco": {"meta": {"Usina S": meta}})
    hist = {"U.ESTM.POA.IRAD": [("2026-09-09T06:00:00", 0.0), ("2026-09-09T07:00:00", 1000.0)]}
    for nome, ed in eday_por_inv.items():
        hist[f"U.{nome}.EPD"] = [] if ed is None else [("2026-09-09T07:00:00", ed)]
    monkeypatch.setattr(app, "_sunop_analog_history", lambda paths, a, b, inst="gridco": hist)
    monkeypatch.setattr(app, "_pot_inv", lambda *a, **k: 1000.0)
    return app._sunop_pr_one("Usina S", "2026-09-09")


def test_inversor_zerado_tem_pr_zero_e_geracao_zero(monkeypatch):
    ipoa, _n, invs = _monta(monkeypatch, {"INV1": 250.0, "INV2": 0.0})
    assert ipoa == 0.5, "a integração da POA não pode mudar (trapézio de 1 h a 1000 W/m²)"
    por = {i["id"]: i for i in invs}
    assert por["INV2"]["geracao_kwh"] == 0.0, "inversor morto aparecia como 'sem dado'"
    assert por["INV2"]["pr"] == 0.0, "PR do morto tem de ser 0, não None (é o que o pinta de vermelho)"
    assert por["INV1"]["pr"] == 0.5


def test_inversor_sem_leitura_continua_none(monkeypatch):
    """O outro lado da moeda: sem série nenhuma continua sendo ausência, não zero."""
    _ipoa, _n, invs = _monta(monkeypatch, {"INV1": 250.0, "INV3": None})
    por = {i["id"]: i for i in invs}
    assert por["INV3"]["geracao_kwh"] is None and por["INV3"]["pr"] is None


def test_o_morto_conta_como_abaixo_dos_pares(monkeypatch):
    """É o número que o analista lê no card da usina: `abaixo` exige `pr is not None`."""
    _ipoa, _n, invs = _monta(monkeypatch, {"INV1": 250.0, "INV2": 250.0, "INV3": 0.0})
    prs = sorted(x["pr"] for x in invs if x["pr"] is not None)
    med = prs[len(prs) // 2] if prs else None
    lim = med * (1 - app.PR_REL_SEVERO)
    abaixo = [x["id"] for x in invs if x["pr"] is not None and x["pr"] < lim]
    assert abaixo == ["INV3"], f"o inversor morto ficou fora da conta de 'abaixo dos pares': {abaixo}"


def test_as_outras_fontes_ja_usavam_a_regua_certa():
    """Guarda contra a regressão inversa: se alguém 'padronizar' pela versão errada, quebra aqui.
    (Asserção sobre o ARQUIVO, não sobre `inspect.getsource` — o app.py tem funções homônimas em
    escopos diferentes e o getsource devolve a fatia errada.)"""
    import pathlib
    src = pathlib.Path(app.__file__).read_text(encoding="utf-8")
    assert 'if (i["eday"] is not None and ipoa and i["pot_kwp"]) else None' in src, "API PV mudou de régua"
    assert 'if (ger is not None and p["ipoa"] and pot) else None' in src, "PG mudou de régua"
    assert 'if (kwh is not None and ipoa and pot) else None' in src, "SolarEdge mudou de régua"
    assert 'if (eday is not None and ipoa and pot) else None' in src, "SunOp/Axis mudou de régua"
