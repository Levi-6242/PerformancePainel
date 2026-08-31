"""Régua de strings da API PV / SunOp / PG — funções puras de app.py.

Cobre _str_key, _classifica_strings, _str_ativas, _ipv_ativas e _na_janela_sol.
Casos-base validados na sessão de 14/06 (ver memória testes-automatizados-plano).
"""
from datetime import datetime

import app


def test_str_key_formato():
    assert app._str_key(100, 50, "Ipv6") == "100|50|Ipv6"
    assert app._str_key("UFV", "INV01", "Ipv3") == "UFV|INV01|Ipv3"


def test_classifica_strings_caso_validado_dia(set_trancadas):
    # Ipv6 trancada à mão; inversor produzindo (mediana alta).
    set_trancadas({app._str_key(100, 50, "Ipv6")})
    keys = [f"Ipv{i}" for i in range(1, 7)]
    corr = [8.0, 8.2, 0.0, 4.0, 7.8, 8.1]
    statuses = app._classifica_strings(100, 50, keys, corr)
    assert statuses == ["ativa", "ativa", "sem_corrente", "baixa_perf", "ativa", "trancada"]
    # ativas = ativa + baixa_perf, descontando a trancada
    assert app._str_ativas(statuses) == 4


def test_classifica_strings_noite_tudo_inativa(set_trancadas):
    # Inversor parado (mediana ~0): NÃO é falha, é "inativa".
    set_trancadas(set())
    keys = ["Ipv1", "Ipv2"]
    statuses = app._classifica_strings(1, 1, keys, [0.1, 0.0])
    assert statuses == ["inativa", "inativa"]
    assert app._str_ativas(statuses) == 0


def test_classifica_strings_trancada_fora_da_mediana(set_trancadas):
    # A string trancada não entra na mediana nem na contagem de ativas, mesmo
    # que sua corrente fosse alta.
    set_trancadas({app._str_key(7, 3, "Ipv1")})
    keys = ["Ipv1", "Ipv2", "Ipv3"]
    statuses = app._classifica_strings(7, 3, keys, [99.0, 5.0, 5.0])
    assert statuses[0] == "trancada"
    assert app._str_ativas(statuses) == 2


def test_classifica_strings_sem_corrente_vs_baixa_perf(set_trancadas):
    # Régua relativa à mediana do PRÓPRIO inversor: 0 => sem_corrente;
    # < 60% da mediana => baixa_perf.
    set_trancadas(set())
    keys = ["Ipv1", "Ipv2", "Ipv3", "Ipv4"]
    # mediana das demais ~10 -> 0 é sem_corrente, 5 (<6) é baixa_perf
    statuses = app._classifica_strings(2, 9, keys, [10.0, 10.0, 0.0, 5.0])
    assert statuses == ["ativa", "ativa", "sem_corrente", "baixa_perf"]


def test_str_ativas_conta_ativa_e_baixa_perf():
    assert app._str_ativas(["ativa", "baixa_perf", "sem_corrente",
                            "trancada", "inativa", "ativa"]) == 3
    assert app._str_ativas([]) == 0
    assert app._str_ativas(["inativa", "trancada"]) == 0


def test_ipv_ativas_dentro_da_janela():
    # Em 9-15h: ativa se corrente > 1.0 A (régua simples). 1.0 NÃO conta (estrito).
    out = app._ipv_ativas([8.0, 0.0, 1.0, 1.5], em_janela=True)
    assert out == [True, False, False, True]


def test_ipv_ativas_fora_da_janela_relativa():
    # Fora da janela: > 1.0 já é ativa; abaixo disso, >= 30% da média(produzindo).
    # produzindo=[0.5, 2.0] -> média 1.25 -> limiar 0.375.
    out = app._ipv_ativas([0.5, 0.0, 2.0], em_janela=False)
    assert out == [True, False, True]


def test_ipv_ativas_tudo_zero_fora_da_janela():
    assert app._ipv_ativas([0.0, 0.0], em_janela=False) == [False, False]


def test_ipv_ativas_ignora_nao_numerico():
    out = app._ipv_ativas([8.0, None, "x", 0.0], em_janela=True)
    assert out == [True, False, False, False]


def test_spv_analise_inversor_exclui_trancada_da_curva(set_trancadas):
    # Curva de strings (API PV): a string trancada à mão (checkbox 🔒) NÃO entra no
    # gráfico — some de 'curva' e de 'strings'. (Régua igual à da tabela.)
    set_trancadas({app._str_key(100, 50, "Ipv2")})
    recs = [{"tsleitura_new": "2026-06-15 12:00:00",
             "conteudojson": {"Ipv1": 8.0, "Ipv2": 8.0, "Ipv3": 7.5}}]
    out = app._spv_analise_inversor(50, "Inversor 1.1", recs, "15/06/2026", {},
                                    full=True, plant_id=100)
    assert out is not None
    assert set(out["curva"].keys()) == {"ST 01", "ST 03"}          # ST 02 (trancada) fora
    assert {s["nome"] for s in out["strings"]} == {"ST 01", "ST 03"}


def test_spv_analise_inversor_sem_trancada_inclui_todas(set_trancadas):
    # Controle: sem trancadas, todas as strings entram na curva.
    set_trancadas(set())
    recs = [{"tsleitura_new": "2026-06-15 12:00:00",
             "conteudojson": {"Ipv1": 8.0, "Ipv2": 8.0, "Ipv3": 7.5}}]
    out = app._spv_analise_inversor(50, "Inversor 1.1", recs, "15/06/2026", {},
                                    full=True, plant_id=100)
    assert set(out["curva"].keys()) == {"ST 01", "ST 02", "ST 03"}


def test_spv_analise_inversor_trancada_alta_sai_da_curva(set_trancadas):
    # Mesmo com corrente alta no pico, a string trancada sai do gráfico (não é "string real").
    set_trancadas({app._str_key(100, 50, "Ipv1")})
    recs = [{"tsleitura_new": "2026-06-15 12:00:00",
             "conteudojson": {"Ipv1": 99.0, "Ipv2": 5.0, "Ipv3": 5.0}}]
    out = app._spv_analise_inversor(50, "Inv", recs, "15/06/2026", {},
                                    full=True, plant_id=100)
    assert "ST 01" not in out["curva"]
    assert set(out["curva"].keys()) == {"ST 02", "ST 03"}


def test_pg_strings_curva_exclui_trancada(set_trancadas, monkeypatch):
    # PG (Thopen): a string trancada (🔒) some da curva. Chave = pid | dev_id | snum.
    set_trancadas({app._str_key(100, 7, "2")})
    ts = datetime(2026, 6, 15, 12, 0)
    rows = [(7, "INV 7", "Usina X", 1, ts, 8.0),
            (7, "INV 7", "Usina X", 2, ts, 8.0)]

    class _Cur:
        def execute(self, *a, **k): pass
        def fetchall(self): return rows

    class _Conn:
        def cursor(self): return _Cur()
        def close(self): pass

    monkeypatch.setattr(app, "_pg_conn", lambda: _Conn())
    iv = app._pg_strings_curva(100, "2026-06-15")["inversores"][0]
    assert set(iv["curva"].keys()) == {"ST 01"}                  # ST 02 (trancada) fora
    assert {s["nome"] for s in iv["strings"]} == {"ST 01"}


def test_pg_strings_curva_sem_trancada_inclui_todas(set_trancadas, monkeypatch):
    set_trancadas(set())
    ts = datetime(2026, 6, 15, 12, 0)
    rows = [(7, "INV 7", "Usina X", 1, ts, 8.0),
            (7, "INV 7", "Usina X", 2, ts, 8.0)]

    class _Cur:
        def execute(self, *a, **k): pass
        def fetchall(self): return rows

    class _Conn:
        def cursor(self): return _Cur()
        def close(self): pass

    monkeypatch.setattr(app, "_pg_conn", lambda: _Conn())
    iv = app._pg_strings_curva(100, "2026-06-15")["inversores"][0]
    assert set(iv["curva"].keys()) == {"ST 01", "ST 02"}


def test_sunop_strings_curva_exclui_trancada(set_trancadas, monkeypatch):
    # SunOp (Athon): a string trancada some da curva. Chave = plant_name | inv_name | id,
    # onde id = último segmento do pathname (ex.: "INV_01.I_PV2" -> "I_PV2").
    plant, inv_name = "Athon X", "INV_01"
    paths = [f"{inv_name}.I_PV1", f"{inv_name}.I_PV2"]
    serie = [(datetime(2026, 6, 15, 12, 0), 8.0)]
    monkeypatch.setattr(app, "ensure_sunop_meta", lambda *a, **k: None)
    monkeypatch.setattr(app, "_sunop_meta", {plant: {"inv_strings": {inv_name: paths}}})
    monkeypatch.setattr(app, "_sunop_analog_history", lambda *a, **k: {p: serie for p in paths})
    set_trancadas({app._str_key(plant, inv_name, "I_PV2")})
    iv = app._sunop_strings_curva(plant, "2026-06-15")["inversores"][0]
    assert set(iv["curva"].keys()) == {"ST 01"}                  # ST 02 (trancada) fora
    assert {s["nome"] for s in iv["strings"]} == {"ST 01"}


def test_sunop_strings_curva_sem_trancada_inclui_todas(set_trancadas, monkeypatch):
    plant, inv_name = "Athon X", "INV_01"
    paths = [f"{inv_name}.I_PV1", f"{inv_name}.I_PV2"]
    serie = [(datetime(2026, 6, 15, 12, 0), 8.0)]
    monkeypatch.setattr(app, "ensure_sunop_meta", lambda *a, **k: None)
    monkeypatch.setattr(app, "_sunop_meta", {plant: {"inv_strings": {inv_name: paths}}})
    monkeypatch.setattr(app, "_sunop_analog_history", lambda *a, **k: {p: serie for p in paths})
    set_trancadas(set())
    iv = app._sunop_strings_curva(plant, "2026-06-15")["inversores"][0]
    assert set(iv["curva"].keys()) == {"ST 01", "ST 02"}


def test_marca_inv_sub_pega_inversor_abaixo_dos_pares():
    # Caso TIM100: blocos com tracker parado (med ~2825) entre inversores saudáveis (~3850).
    # A régua intra-inversor marcaria "OK"; _marca_inv_sub pega o inversor inteiro abaixo dos pares.
    invs = [{"nome": "1.1", "mediana": 3850}, {"nome": "1.2", "mediana": 3800},
            {"nome": "5.2", "mediana": 2825}, {"nome": "2.9", "mediana": 2877},
            {"nome": "noite", "mediana": 0}]
    app._marca_inv_sub(invs)
    by = {i["nome"]: i for i in invs}
    assert by["1.1"]["med_usina"] == 3800.0          # mediana das medianas dos inversores produzindo
    assert by["5.2"]["inv_sub"] is True              # 2825 < 90% de 3800
    assert by["2.9"]["inv_sub"] is True
    assert by["1.1"]["inv_sub"] is False
    assert by["1.2"]["inv_sub"] is False
    assert by["noite"]["inv_sub"] is False           # sem geração (mediana 0) não é marcado


def test_marca_inv_sub_usina_homogenea_nao_marca():
    invs = [{"mediana": 3850}, {"mediana": 3800}, {"mediana": 3820}]
    app._marca_inv_sub(invs)
    assert all(i["inv_sub"] is False for i in invs)   # todos perto da mediana → nada abaixo dos pares


def test_jwt_exp_le_exp_do_payload():
    # _jwt_exp decide qual token SunOp usar (maior validade entre tokens_runtime.json e .env).
    import base64
    import json as _json
    def mk(e):
        p = base64.urlsafe_b64encode(_json.dumps({"exp": e}).encode()).decode().rstrip("=")
        return "h." + p + ".s"
    assert app._jwt_exp(mk(1781885159)) == 1781885159.0
    assert app._jwt_exp("") == 0.0
    assert app._jwt_exp("nao-e-um-jwt") == 0.0


def test_na_janela_sol_limites():
    # Janela [9, 15): inclusiva no 9, exclusiva no 15.
    assert app._na_janela_sol(datetime(2026, 6, 14, 9, 0)) is True
    assert app._na_janela_sol(datetime(2026, 6, 14, 14, 59)) is True
    assert app._na_janela_sol(datetime(2026, 6, 14, 15, 0)) is False
    assert app._na_janela_sol(datetime(2026, 6, 14, 8, 59)) is False


# ── esperadas por inversor no drill (Levi 27/08) ──────────────────────────────
def test_equip_key_casa_grafias_da_planilha_e_da_api():
    """Caso real (Rodrigues): API entrega 'INVERSOR01', a aba Equipamentos cadastra 'INVERSOR 01' —
    o lookup exato falhava e as esperadas por inversor saíam None com o cadastro certo. A chave
    normalizada casa por IGUALDADE (nunca substring: 2.1 ≠ 2.18, o gotcha do deep link)."""
    assert app._equip_key("INVERSOR 01") == app._equip_key("INVERSOR01") == "INVERSOR1"
    assert app._equip_key("Inversor 001") == "INVERSOR1"
    assert app._equip_key("INVERSOR 10") == "INVERSOR10"          # 10 não perde o zero interno
    assert app._equip_key("Inversor 2.1") != app._equip_key("Inversor 2.18")


def test_equip_lookup_exato_primeiro_e_normalizado_depois():
    d = {"INVERSOR 01": 17, "INVERSOR 02": 18}
    assert app._equip_lookup(d, "INVERSOR 01") == 17     # exato continua valendo
    assert app._equip_lookup(d, "INVERSOR01") == 17      # grafia da API casa
    assert app._equip_lookup(d, "inversor 02") == 18
    assert app._equip_lookup(d, "INVERSOR 03") is None   # inexistente não inventa
    assert app._equip_lookup(None, "x") is None
