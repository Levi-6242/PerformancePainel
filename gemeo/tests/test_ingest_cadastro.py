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


def test_bd_trackers_da_o_inversor_de_cada_tracker_com_a_confianca_de_como_casou(conn):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from semear import limpar_tudo
    linhas = [{"Usina Supervisório": "MRO100", "Tracker Supervisório": "TRK_1", "Inversor Supervisório": "Inversor 1.1", "Inversor": "Inversor 1.1"},
              {"Usina Supervisório": "MRO100", "Tracker Supervisório": "TRK_2", "Inversor Supervisório": "INV_2", "Inversor": "Inversor 1.2"},
              {"Usina Supervisório": "MRO100", "Tracker Supervisório": "TRK_3", "Inversor Supervisório": "Inversor 2.11", "Inversor": "Inversor 2.\n11"},
              {"Usina Supervisório": "MRO100", "Tracker Supervisório": "TRK_4", "Inversor Supervisório": "", "Inversor": "Inversor 2.28"},
              {"Usina Supervisório": "MRO100", "Tracker Supervisório": "TRK_99", "Inversor Supervisório": "INV_1", "Inversor": ""},
              {"Usina Supervisório": "XPTO", "Tracker Supervisório": "TRK_1", "Inversor Supervisório": "INV_1"}]
    d = cadastro.separar_trackers(linhas, ("MRO100",))
    assert list(d) == ["MRO100"] and d["MRO100"][2] == ("TRK_3", "Inversor 2.11", "Inversor 2.11")
    limpar_tudo(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO usina (codigo, nome, fonte, fonte_ref, tz) VALUES ('MRO100','MRO100','sunop','MRO100','America/Belem') RETURNING id")
        uid = cur.fetchone()[0]
        for n in (1, 2, 11):
            cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte, nome_exibicao) VALUES (%s,'inversor',%s,%s)", (uid, f"INV_{n}", f"Inversor 1.{n}" if n == 1 else None))
        for n in (1, 2, 3, 4):
            cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte) VALUES (%s,'tracker',%s)", (uid, f"TRK_{n}"))
    conn.commit()
    res = cadastro.aplicar_trackers(conn, d)
    assert res == {"mapeados": 3, "sem_inversor": 1, "sem_tracker": 1}          # TRK_4 -> INV_28 nao existe; TRK_99 nao existe
    with conn.cursor() as cur:
        cur.execute("SELECT t.codigo_fonte, p.codigo_fonte, a.confianca FROM equipamento t JOIN equipamento p ON p.id=t.pai_id "
                    "JOIN alias a ON a.equipamento_id=t.id WHERE t.tipo='tracker' ORDER BY t.codigo_fonte")
        assert cur.fetchall() == [("TRK_1", "INV_1", "direto"), ("TRK_2", "INV_2", "direto"), ("TRK_3", "INV_11", "ordem")]
    limpar_tudo(conn)


def test_usina_sem_supervisorio_entra_pelo_nome_e_a_ug_nao_sobrescreve_a_ufv():
    """2C (11/09/2026): a linha UFV e as UG 01/UG 02 vem com 'Usina Supervisório' VAZIO — so os inversores trazem o codigo.
    Sem cair para o nome, Araputanga/Sete Lagoas/Tupi Paulista ficavam sem usina e os inversores nunca eram aplicados; e a
    UG 02 da Tupi (3402 kWp, 10 inversores) passava por cima da UFV (6804 kWp, 20)."""
    ls = [{"Cliente": "2C", "Usina": "Tupi Paulista", "Usina Supervisório": None, "Usina Fractall": "2C - Tupi Paulista 1 e 2 - SP",
           "Equipamento": "UFV", "Equipamento Supervisório": None, "Equipamento Parente": None, "Potência (kWp)": 6804.0, "N de Inversores": 20, "Full O&M": "Sim"},
          {"Usina": "Tupi Paulista", "Usina Supervisório": None, "Equipamento": "UG 01", "Equipamento Supervisório": None, "Equipamento Parente": "UFV", "Potência (kWp)": 3402, "N de Inversores": 10},
          {"Usina": "Tupi Paulista", "Usina Supervisório": None, "Equipamento": "UG 02", "Equipamento Supervisório": None, "Equipamento Parente": "UFV", "Potência (kWp)": 3402, "N de Inversores": 10},
          {"Usina": "Tupi Paulista", "Usina Supervisório": "Tupi Paulista", "Equipamento": "Inversor 2.1", "Equipamento Supervisório": "INVERSOR11",
           "Equipamento Parente": "UG 02", "Potência (kWp)": 340.2, "Strings Ativas": 20},
          {"Usina": "(289) Boa Esperança do Sul 1", "Usina Supervisório": None, "Equipamento": "UFV", "Potência (kWp)": 1}]      # nome != codigo: segue fora
    us, invs = cadastro.separar_equipamentos(ls, ("Tupi Paulista", "BOA ESPERANCA DO SUL 1"))
    assert list(us) == ["Tupi Paulista"]
    assert us["Tupi Paulista"]["kwp"] == 6804.0 and us["Tupi Paulista"]["n_inversores"] == 20 and us["Tupi Paulista"]["fracttal"] == "2C - Tupi Paulista 1 e 2 - SP"
    assert invs["Tupi Paulista"] == [{"codigo_fonte": "INVERSOR11", "nome": "Inversor 2.1", "kwp": 340.2, "n_strings_esperadas": 20}]


def test_inversor_casa_pelo_nome_de_exibicao_quando_o_codigo_da_fonte_e_outro(conn):
    """API PV: codigo_fonte e o idefinversor (400771) e o cadastro so conhece 'INVERSOR01' — o que os dois tem em comum e o
    nome 'Inversor 1.1' (de-para por valor no config). Mesma escada do tracker: codigo da fonte > nome de exibicao."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from semear import limpar_tudo
    limpar_tudo(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO usina (codigo, nome, fonte, fonte_ref, tz) VALUES ('Araputanga','Araputanga','apipv','18771898','America/Cuiaba') RETURNING id")
        uid = cur.fetchone()[0]
        cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte, nome_exibicao) VALUES (%s,'inversor','400771','Inversor 1.1')", (uid,))
        cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte, nome_exibicao) VALUES (%s,'inversor','400772','Inversor 1.2')", (uid,))
    conn.commit()
    us = {"Araputanga": {"cliente": "2C", "fracttal": "2C - Araputanga 1 - MT", "kwp": 3469.2, "n_inversores": 10, "full_om": True, "string_box": False}}
    invs = {"Araputanga": [{"codigo_fonte": "INVERSOR01", "nome": "Inversor 1.1", "kwp": 338.1, "n_strings_esperadas": 23},
                           {"codigo_fonte": "INVERSOR09", "nome": "Inversor 1.9", "kwp": 352.8, "n_strings_esperadas": 24}]}     # 1.9 nao existe na fonte
    assert cadastro.aplicar_equipamentos(conn, us, invs) == {"usinas": 1, "inversores": 1}
    with conn.cursor() as cur:
        cur.execute("SELECT id, atributos FROM equipamento WHERE usina_id=%s AND codigo_fonte='400771'", (uid,))
        eid, at = cur.fetchone()
        cur.execute("SELECT equipamento_id FROM alias WHERE sistema='bd_performance' AND valor='Araputanga|Inversor 1.1'")
        assert cur.fetchone()[0] == eid
        cur.execute("SELECT atributos FROM equipamento WHERE usina_id=%s AND codigo_fonte='400772'", (uid,))
        assert cur.fetchone()[0] == {}
    assert at == {"kwp": 338.1, "n_strings_esperadas": 23}
    limpar_tudo(conn)
