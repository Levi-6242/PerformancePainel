# gemeo/tests/test_ingest_cadastro_latlon.py
"""Levi, 12/09/2026: "lat/lon, preenchido no info_geral, colunas criadas!!!". A Info Geral ganhou LATITUDE e LONGITUDE;
o cadastro passa a le-las e a gravar em usina.lat/lon. A Info Geral e o cadastro do time de Performance: quando ela
traz coordenada, ela MANDA (por cima do que veio do PostgreSQL ou do /plants da API PV); sem coordenada, nao apaga."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from semear import limpar_tudo  # noqa: E402
from gemeo.ingest import cadastro  # noqa: E402


def test_info_geral_traz_latitude_e_longitude():
    linhas = [{"Usina": "MRO100", "Potência (KWp)": 6942, "Quantidade de Inversores": 25, "LATITUDE": -2.0611, "LONGITUDE": -47.5604},
              {"Usina": "MTS100", "Potência (KWp)": 6625, "LATITUDE": "", "LONGITUDE": None},           # sem coordenada: None
              {"Usina": "CPP100", "Potência (KWp)": 4910, "LATITUDE": "-1,763717", "LONGITUDE": "-47,074518"}]   # virgula decimal
    d = cadastro.separar_info_geral(linhas, ("MRO100", "MTS100", "CPP100"))
    assert (d["MRO100"]["lat"], d["MRO100"]["lon"]) == (-2.0611, -47.5604)
    assert (d["MTS100"]["lat"], d["MTS100"]["lon"]) == (None, None)
    assert (d["CPP100"]["lat"], d["CPP100"]["lon"]) == (-1.763717, -47.074518)


def test_aplicar_grava_a_coordenada_e_nao_apaga_quando_falta(conn):
    limpar_tudo(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO usina (codigo, nome, fonte, fonte_ref, tz, lat, lon) VALUES ('MRO100','MRO100','sunop','MRO100','America/Belem', NULL, NULL)")
        cur.execute("INSERT INTO usina (codigo, nome, fonte, fonte_ref, tz, lat, lon) VALUES ('SANTAREM 1','S1','pg','10','America/Santarem', -2.4, -54.7)")
    conn.commit()
    d = {"MRO100": {"kwp": 6942.0, "n_inversores": 25, "n_trackers": 120, "cliente": "Athon", "p50_mwh_ano": None, "lat": -2.0611, "lon": -47.5604},
         "SANTAREM 1": {"kwp": 3000.0, "n_inversores": 10, "n_trackers": None, "cliente": "Thopen", "p50_mwh_ano": None, "lat": None, "lon": None}}
    assert cadastro.aplicar_info_geral(conn, d) == 2
    with conn.cursor() as cur:
        cur.execute("SELECT codigo, lat, lon FROM usina ORDER BY codigo")
        assert cur.fetchall() == [("MRO100", -2.0611, -47.5604), ("SANTAREM 1", -2.4, -54.7)]   # a do PG ficou como estava
    limpar_tudo(conn)
