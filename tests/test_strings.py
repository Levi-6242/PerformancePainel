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


def test_na_janela_sol_limites():
    # Janela [9, 15): inclusiva no 9, exclusiva no 15.
    assert app._na_janela_sol(datetime(2026, 6, 14, 9, 0)) is True
    assert app._na_janela_sol(datetime(2026, 6, 14, 14, 59)) is True
    assert app._na_janela_sol(datetime(2026, 6, 14, 15, 0)) is False
    assert app._na_janela_sol(datetime(2026, 6, 14, 8, 59)) is False
