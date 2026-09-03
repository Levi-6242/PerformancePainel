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


def test_info_geral_da_a_placa_total_e_vence_a_soma_parcial_da_equipamentos(conn):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from semear import limpar_tudo
    linhas = [{"Usina": "MRO100", "Potência (KWp)": 6942, "Quantidade de Inversores": 25, "Qnt. Trackers": 120, "Cliente": "Athon", "P50 (MWh)": 12058},
              {"Usina": "XPTO", "Potência (KWp)": 1, "Quantidade de Inversores": 1}, {"Usina": "", "Potência (KWp)": 9}]
    d = cadastro.separar_info_geral(linhas, ("MRO100",))
    assert d == {"MRO100": {"kwp": 6942.0, "n_inversores": 25, "n_trackers": 120, "cliente": "Athon", "p50_mwh_ano": 12058.0}}
    limpar_tudo(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO usina (codigo, nome, fonte, fonte_ref, tz, kwp_dc, n_inversores) VALUES ('MRO100','MRO100','sunop','MRO100','America/Belem',3332.16,12)")
    conn.commit()
    assert cadastro.aplicar_info_geral(conn, d) == 1
    with conn.cursor() as cur:
        cur.execute("SELECT kwp_dc, n_inversores, cliente FROM usina WHERE codigo='MRO100'")
        assert cur.fetchone() == (6942.0, 25, "Athon")
    limpar_tudo(conn)
