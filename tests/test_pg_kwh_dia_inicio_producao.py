# -*- coding: utf-8 -*-
"""O kWh do dia do banco da Thopen conta do começo da PRODUÇÃO, não da 1ª queda do contador (16/11/2026).

O caso: na Aparecida do Taboado 1 cada inversor tem duas séries de leitura intercaladas. Das 00:00 às 05:30 uma delas
repete o total de ontem depois de a outra já ter zerado; a régua antiga (o MAX depois da 1ª queda) ficava com o de ontem
até a geração de hoje passar dele: 350,9 kWh na tela com o contador em 174,9, em 13 inversores, e o PR do dia inflado.

A régua mora no SQL de três consultas do `plataforma/app.py`. Aqui: (1) as três trazem a régua nova e nenhuma ficou com a
antiga; (2) a régua em Python, igual à do SQL, nas séries reais que a decidiram, inclusive as duas tentativas reprovadas
na prova de 01-15/11 e 12-31/10 contra a 1ª leitura do dia seguinte (5.983 inversor-dias, nenhum caso certo quebrado).
"""
import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTE = open(os.path.join(RAIZ, "plataforma", "app.py"), encoding="utf-8-sig").read().replace("\r\n", "\n")


def _consultas():
    """As consultas que leem o contador `daily_active_energy` do public.raw_inverter para o kWh do dia."""
    return [s for s in re.findall(r'sql = """(.*?)"""', FONTE, flags=re.S) if "dae < dae_prev - 1" in s]


def test_as_tres_consultas_contam_do_comeco_da_producao():
    sqls = _consultas()
    assert len(sqls) == 3
    for s in sqls:
        assert "->>'active_power')::numeric AS pot" in s                    # a potência entra na leitura
        assert "MIN(ts) FILTER (WHERE pot > 0)" in s and "AS t_prod" in s   # a 1ª leitura do dia com potência
        assert "ABS(dae_prev - dae_ini) < 0.05" in s and "AS t_acorda" in s  # quem zera depois de começar a gerar
        assert "WHEN t_acorda IS NOT NULL THEN ts >= t_acorda" in s and "ELSE ts >= t_prod END" in s
        assert "FROM acorda GROUP BY" in s and "FROM ciclo GROUP BY" not in s
        assert "MAX(dae) FILTER (WHERE t_reset IS NULL OR ts >= t_reset)" not in s      # a régua antiga saiu
        # o psycopg interpola a string INTEIRA: sinal de porcentagem solto (até em comentário) quebra a consulta
        assert not re.search(r"%(?!\()", s)


def kwh_do_dia(leituras):
    """A régua do SQL, em Python: leituras = [(minuto do dia, contador, potência)] em ordem."""
    quedas = [i for i in range(1, len(leituras)) if leituras[i - 1][1] is not None and leituras[i][1] is not None
              and leituras[i][1] < leituras[i - 1][1] - 1]
    t_reset = leituras[quedas[0]][0] if quedas else None
    com_pot = [t for t, _, p in leituras if p is not None and p > 0]
    t_prod = com_pot[0] if com_pot else None
    ini = leituras[0][1]
    acorda = [leituras[i][0] for i in quedas if t_prod is not None and leituras[i][0] >= t_prod
              and ini is not None and abs(leituras[i - 1][1] - ini) < 0.05]
    if t_prod is None:
        de = t_reset
    else:
        de = acorda[0] if acorda else t_prod
    vals = [d for t, d, _ in leituras if d is not None and (de is None or t >= de)]
    return max(vals) if vals else None


def _duas_series(ontem, hoje_fim, zera_noite=False):
    """A Taboado 1: uma série em :00 e outra em :04; a 1ª repete o total de ontem até 05:30, a 2ª já está em zero."""
    out = []
    for t in range(0, 1440, 5):
        gerando = 360 <= t <= 1080
        cont = round(hoje_fim * min(1, max(0, (t - 360) / 720)), 1)
        velha = ontem if t <= 330 else cont
        if zera_noite and t >= 1435:
            velha = 0.0                                   # uma das séries zera perto das 23:55
        out.append((t, velha, 50.0 if gerando else 0.0))
        out.append((t + 4, cont, 50.0 if gerando else 0.0))
    return out


def test_o_total_de_ontem_repetido_ate_05_30_nao_vira_o_kwh_de_hoje():
    s = _duas_series(ontem=350.9, hoje_fim=174.9)
    assert kwh_do_dia(s) == 174.9
    # a régua antiga (o MAX depois da 1ª queda) devolvia o de ontem: é o defeito
    t_reset = next(s[i][0] for i in range(1, len(s)) if s[i][1] < s[i - 1][1] - 1)
    assert max(d for t, d, _ in s if t >= t_reset) == 350.9


def test_a_serie_que_zera_as_23_55_nao_zera_o_dia_fechado():
    # reprovada em 01-15/11: contar da ÚLTIMA queda dava 0,0 no dia fechado (13/11, 14 inversores)
    assert kwh_do_dia(_duas_series(ontem=120.0, hoje_fim=559.3, zera_noite=True)) == 559.3


def test_quem_zera_depois_de_comecar_a_gerar_conta_do_zero():
    # Guaratinguetá V, 11/11: o contador ainda traz o total de ontem nas primeiras leituras com potência
    s = [(t, 1202.8, 0.0) for t in range(0, 360, 5)] + [(360, 1202.8, 12.0), (365, 1202.8, 20.0), (370, 0.4, 25.0)]
    s += [(t, round((t - 370) * 0.99, 1), 60.0) for t in range(375, 1085, 5)] + [(t, 704.6, 0.0) for t in range(1085, 1440, 5)]
    assert kwh_do_dia(s) == 704.6


def test_potencia_zerada_com_o_contador_andando_nao_corta_o_dia():
    # reprovada em 01-15/11: contar só leitura COM potência cortava a São Bento V (04/11: 1.755 virava 1.113)
    s = [(0, 900.0, 0.0), (5, 0.0, 0.0)] + [(t, round((t - 360) * 2.4, 1), 80.0 if t < 800 else 0.0) for t in range(360, 1095, 5)]
    assert kwh_do_dia(s) == round((1090 - 360) * 2.4, 1)


def test_dia_sem_leitura_com_potencia_segue_a_regua_da_1a_queda():
    s = [(0, 400.0, None), (5, 0.0, None), (600, 0.0, None)]
    assert kwh_do_dia(s) == 0.0
    assert kwh_do_dia([(0, 400.0, None), (600, 400.0, None)]) == 400.0      # nunca caiu: vale o dia todo, como antes
