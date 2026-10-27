# -*- coding: utf-8 -*-
"""A Barretos numera os inversores no Fracttal de outro jeito que o cadastro (Levi, 27/10/2026: "arrume o de-para de
barretos"): lá INVR1.1 a INVR1.40 numa fila só (1.21–1.40 no SKID 2 / QGBT 2, conferido ativo por ativo), aqui 1.1–1.20
(UG 1) e 2.1–2.20 (UG 2). Casos reais: a OS 17428 (religamento do BRS100-INVR1.21) caía num "Inversor 1.21" que não
existe; o código derivado do 2.5 (BRS100-INVR2.5) não existe no Fracttal."""
import disponibilidade as disp
import diag_tratamento as dtr


def _barretos():
    U = disp.UsinaCat("Barretos")
    U.fracttal, U.pot = "Thopen - Barretos 1 - SP", 6139.0
    U.ugs = {1: 3069.5, 2: 3069.5}
    for c in (1, 2):
        for n in range(1, 21):
            U.invs[f"{c}.{n}"], U.inv_ug[f"{c}.{n}"] = 153.5, c
    return {"Barretos": U}


def _os(code):
    return {"code": code, "g1": "Thopen - Barretos 1 - SP", "item": code, "flags": []}


def test_os_do_inversor_1_21_do_fracttal_cai_no_2_1_do_cadastro():
    us = _barretos()
    o = _os("BRS100-INVR1.21")
    assert disp.escopo_os(o, us, disp.indices_g1(us)) == [("Barretos", "inversor", "inv2.1", 153.5)]
    assert any("1.21 do Fracttal = 2.1" in f for f in o["flags"])


def test_disjuntor_e_ultimo_inversor_e_a_ug_1_ficam_como_estao():
    us, idx = _barretos(), None
    idx = disp.indices_g1(us)
    assert disp.escopo_os(_os("BRS100-DINV1.40"), us, idx)[0][2] == "inv2.20"
    o = _os("BRS100-INVR1.20")
    assert disp.escopo_os(o, us, idx)[0][2] == "inv1.20" and not o["flags"]


def test_outra_usina_nao_renumera():
    assert disp.inv_do_fracttal("CPP100-INVR1.21", "1.21") == "1.21"
    assert disp.inv_para_fracttal("CPP100", "2.1") == "2.1"


def test_ida_e_volta():
    for n in range(1, 21):
        assert disp.inv_do_fracttal("THPN-BRS100-INVR" + disp.inv_para_fracttal("BRS100", f"2.{n}"), f"1.{20 + n}") \
            == f"2.{n}"
    assert disp.inv_para_fracttal("BRS100", "1.7") == "1.7"


def test_chamado_do_inversor_da_ug_2():
    assert dtr.ativo_do_codigo("THPN-BRS100-INVR1.33") == ("inversor", "Inversor 2.13")
    assert dtr.ativo_do_codigo("BRS100-INVR1.14") == ("inversor", "Inversor 1.14")


def test_codigo_derivado_do_inversor_2_n(monkeypatch):
    import app
    monkeypatch.setattr(app, "_frac_cod_gravado", lambda u, i: None)
    monkeypatch.setattr(app, "_frac_codebase", lambda u: "BRS100")
    assert app._frac_inv_code("Barretos", "Inversor 2.5") == "BRS100-INVR1.25"
    assert app._frac_inv_code("Barretos", "Inversor 1.5") == "BRS100-INVR1.5"
