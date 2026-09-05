# gemeo/tests/test_ingest_pg.py
"""Parse do json_data das tabelas raw_* → leituras normalizadas. Chaves reais medidas em 03/09/2026."""
import datetime as dt
from gemeo.ingest import pg

UTC = dt.timezone.utc
TS = dt.datetime(2026, 9, 3, 15, 0, tzinfo=UTC)


def test_weather_vira_cinco_medidas():
    mapa = {("estacao", "900"): 50}
    ls = pg.linhas_de({"irradiance_poa": 812.5, "irradiance_ghi": 700.0, "module_temperature": 48.2,
                       "air_temperature": 31.0, "wind_speed": 2.1, "rain_signal": 0}, "raw_weather_station", "900", TS, mapa)
    assert {(m, v) for _, m, _, v in ls} == {("poa", 812.5), ("ghi", 700.0), ("temp_modulo", 48.2), ("temp_ar", 31.0), ("vento", 2.1)}
    assert all(e == 50 for e, *_ in ls)


def test_inversor_e_suas_strings():
    mapa = {("inversor", "765"): 10, ("string", "765.string_1"): 11, ("string", "765.string_2"): 12}
    ls = pg.linhas_de({"active_power": 150.0, "daily_active_energy": 1479.9, "state_simplified": 2,
                       "string_1_current": 8.4, "string_2_current": 0.0, "string_3_current": None}, "raw_inverter", "765", TS, mapa)
    d = {(e, m): v for e, m, _, v in ls}
    assert d[(10, "p_ac")] == 150.0 and d[(10, "e_dia")] == 1479.9 and d[(10, "estado")] == 2
    assert d[(11, "i_string")] == 8.4 and d[(12, "i_string")] == 0.0
    assert (13, "i_string") not in d                     # string_3 sem equipamento cadastrado e None: fora


def test_tracker_angulos():
    mapa = {("tracker", "77"): 3}
    ls = pg.linhas_de({"posat": -12.5, "posal": -13.0, "flh_com": 0}, "raw_tracker", "77", TS, mapa)
    assert {(m, v) for _, m, _, v in ls} == {("angulo", -12.5), ("angulo_alvo", -13.0)}


def test_valor_nao_numerico_e_descartado():
    ls = pg.linhas_de({"active_power": "erro"}, "raw_inverter", "765", TS, {("inversor", "765"): 10})
    assert ls == []


def test_tracker_e_string_ficam_com_uma_amostra_por_bloco_de_15_min():
    """18 usinas do Thopen na cadencia de 5 min dariam 17 GB em 90 dias, e 72% seria corrente de string — que o
    modelo so consulta para dizer 'zerada ou nao'. Potencia e estacao seguem finas: delas sai a media do bloco."""
    mapa = {("inversor", "7"): 70, ("string", "7.string_1"): 71, ("tracker", "9"): 90}
    vistos: set = set()
    linhas = []
    for minuto in (0, 5, 10, 15, 20):
        ts = dt.datetime(2026, 9, 4, 13, minuto, tzinfo=dt.timezone.utc)
        linhas += pg.linhas_de({"active_power": 100.0, "string_1_current": 8.0}, "raw_inverter", "7", ts, mapa, vistos)
        linhas += pg.linhas_de({"posat": 20.0, "posal": 21.0}, "raw_tracker", "9", ts, mapa, vistos)
    conta = {}
    for _, medida, _, _ in linhas:
        conta[medida] = conta.get(medida, 0) + 1
    assert conta["p_ac"] == 5                                   # fisica: uma por leitura da fonte
    assert conta["i_string"] == 2 and conta["angulo"] == 2 and conta["angulo_alvo"] == 2   # blocos 13:00 e 13:15
    minutos = sorted(ts.minute for _, m, ts, _ in linhas if m == "i_string")
    assert minutos == [0, 15]                                   # a PRIMEIRA de cada bloco
    sem_vistos = pg.linhas_de({"string_1_current": 8.0}, "raw_inverter", "7", dt.datetime(2026, 9, 4, 13, 5, tzinfo=dt.timezone.utc), mapa)
    assert len(sem_vistos) == 1                                 # sem o conjunto, nada e descartado
