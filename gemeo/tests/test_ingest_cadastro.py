# gemeo/tests/test_ingest_cadastro.py
"""Linhas da API (headers + values) viram usina/equipamento/alias. HTTP e um dublê com o formato real."""
from gemeo.ingest import cadastro

HDR = ["", "Cliente", "Usina", "Usina Supervisório", "Usina Fractall", "Equipamento", "Equipamento Supervisório",
       "Equipamento Parente", "Chave", "Chave 2", "Potência (kWp)", "N de Inversores", "String Box", "Full O&M", "Strings Ativas", "Observações"]


def _row(n, vals):
    return {"row_number": n, "headers": HDR, "values": vals + [None] * (len(HDR) - len(vals))}


class Http:
    def __init__(self):
        self.pags = {0: {"rows": [
            _row(4, [None, "Athon", "MRO100", "MRO100", "Athon - Mãe do Rio 1 - PA", "UFV", None, "UFV", "MRO100", "MRO100", 6942.0, 25, "Não", "Sim", None]),
            _row(5, [None, "Athon", "MRO100", "MRO100", "Athon - Mãe do Rio 1 - PA", "Inversor 1.1", "INV_1", "UFV", "MRO100", "MRO100INV_1", 277.68, None, "Não", "Sim", 17]),
            _row(6, [None, "Athon", "MRO100", "MRO100", "Athon - Mãe do Rio 1 - PA", "Inversor 1.2", "INV_2", "UFV", "MRO100", "MRO100INV_2", 277.68, None, "Não", "Sim", 17]),
        ]}, 500: {"rows": []}}
    def get(self, url, params=None, headers=None, timeout=None):
        off = int((params or {}).get("offset", 0))
        class R:
            status_code = 200
            def __init__(s, j): s._j = j
            def json(s): return s._j
            def raise_for_status(s): pass
        return R(self.pags.get(off, {"rows": []}))


def test_linhas_da_aba_pula_cabecalho_e_pagina():
    ls = cadastro.linhas_da_aba(Http(), "http://x", "tok", sheet_id=46, header_row=3)
    assert len(ls) == 3 and ls[1]["Equipamento Supervisório"] == "INV_1" and ls[1]["Strings Ativas"] == 17


def test_separa_usina_de_inversores():
    ls = cadastro.linhas_da_aba(Http(), "http://x", "tok", sheet_id=46, header_row=3)
    us, invs = cadastro.separar_equipamentos(ls, piloto=("MRO100",))
    assert us["MRO100"]["kwp"] == 6942.0 and us["MRO100"]["n_inversores"] == 25 and us["MRO100"]["full_om"] is True
    assert us["MRO100"]["fracttal"] == "Athon - Mãe do Rio 1 - PA"
    assert [i["codigo_fonte"] for i in invs["MRO100"]] == ["INV_1", "INV_2"]
    assert invs["MRO100"][0]["nome"] == "Inversor 1.1" and invs["MRO100"][0]["n_strings_esperadas"] == 17


def test_usina_fora_do_piloto_e_ignorada():
    ls = cadastro.linhas_da_aba(Http(), "http://x", "tok", sheet_id=46, header_row=3)
    us, invs = cadastro.separar_equipamentos(ls, piloto=("OUTRA",))
    assert us == {} and invs == {}
