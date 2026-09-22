# -*- coding: utf-8 -*-
"""Checagens de qualidade do dado da IEC 61724-1:2021 §12.2.1 que ainda faltavam (21/09/2026).

A norma lista dez métodos recomendados para identificar dado inválido. O comparativo de 21/09
mostrou que já tínhamos quatro (limites físicos, valor travado, dado faltante, disponibilidade) e
que faltavam três que dependem só de software — os outros dependem de hardware que não temos.

Os três aqui:
  • **limites físicos de máximo e mínimo** — explícito na norma;
  • **limites de taxa máxima de variação** — explícito na norma;
  • **carimbos duplicados e lacunas** — explícito na norma.

O que NÃO entra, e o motivo: "comparar sensores múltiplos" é impossível com UM piranômetro por
usina (é o buraco de hardware que o comparativo apontou), e "códigos de erro do sensor" exigiria
que a fonte os exponha.

**O calibre dos limiares veio do dado real, não de chute.** Em 17/09 medi a Sete Lagoas num dia de
nuvem quebrada: salto MEDIANO de 68,8 W/m² por minuto e pico de 836, com picos de irradiância de
1.238 W/m² — acima do céu claro, por realce de borda de nuvem. Um limiar ingênuo transformaria
esse dia legítimo em alarme. Por isso o corte é o LIMITE FÍSICO do sensor (1.500 W/m², a faixa que
a Tabela 4 da norma exige), não a estatística do dia.
"""
import datetime as dt

from gemeo.modelar import qualidade as q

UTC = dt.timezone.utc


def _serie(valores, passo_min=1, ini=None):
    t0 = ini or dt.datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    return [(t0 + dt.timedelta(minutes=i * passo_min), v) for i, v in enumerate(valores)]


def test_valor_acima_do_limite_fisico_do_sensor():
    """A Tabela 4 exige piranômetro com faixa até 1.500 W/m². Acima disso não é irradiância, é
    defeito — e não confundir com realce de nuvem, que chega a 1.238 e é real."""
    r = q.fora_da_faixa(_serie([800, 1238, 1600, 900]), "ghi")
    assert r["n"] == 1 and r["exemplo"][1] == 1600
    assert q.fora_da_faixa(_serie([800, 1238, 900]), "ghi")["n"] == 0


def test_negativo_grande_e_defeito_mas_offset_noturno_nao():
    """Piranômetro marca uns poucos W negativos à noite por offset térmico — é normal e a própria
    norma manda tratar no §12.1. Dezenas de negativos, não."""
    assert q.fora_da_faixa(_serie([-3, -1, 0, 5]), "ghi")["n"] == 0
    assert q.fora_da_faixa(_serie([-80]), "ghi")["n"] == 1


def test_salto_impossivel_de_temperatura():
    """Módulo não esquenta 30 °C em um minuto. Irradiância pode saltar (nuvem), temperatura não —
    por isso o limiar de taxa é POR MEDIDA, e não um número só para tudo."""
    r = q.salto_impossivel(_serie([45.0, 45.4, 75.0, 46.0]), "temp_modulo")
    # DOIS, não um: um pico viola a física na subida E na volta. Contar só a subida esconderia
    # metade do defeito, e foi o que eu supus errado ao escrever este teste na primeira vez.
    assert r["n"] == 2 and abs(r["exemplo"][1] - 29.6) < 0.1


def test_nuvem_quebrada_nao_vira_salto_impossivel():
    """O dado real da Sete Lagoas em 17/09: 1225 -> 372 -> 1202 em minutos. É meteorologia, não
    defeito. Se esta regra acusasse isso, ela seria desligada na primeira semana."""
    assert q.salto_impossivel(_serie([1225, 372, 1202, 588, 931]), "ghi")["n"] == 0


def test_carimbo_duplicado_e_lacuna():
    """§12.2.1: "checking timestamps to identify gaps or duplicates in data"."""
    t0 = dt.datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    s = [(t0, 1.0), (t0, 2.0), (t0 + dt.timedelta(minutes=1), 3.0),
         (t0 + dt.timedelta(minutes=40), 4.0)]
    r = q.carimbos(s, passo_esperado_min=1)
    assert r["duplicados"] == 1
    # 38 e não 39: a lacuna é o tempo em que faltou DADO (minutos 2 a 39), não o intervalo entre
    # os dois carimbos. É o número que responde "quanto tempo a usina ficou muda".
    assert r["lacunas"] == 1 and r["maior_lacuna_min"] == 38


def test_serie_curta_nao_opina():
    """Duas leituras não sustentam veredito de qualidade nenhum."""
    assert q.salto_impossivel(_serie([10]), "ghi")["n"] == 0
    assert q.carimbos([], passo_esperado_min=1)["duplicados"] == 0


def test_medida_sem_limite_definido_nao_inventa():
    """Medida fora da tabela de limites devolve zero em vez de aplicar um limiar qualquer."""
    assert q.fora_da_faixa(_serie([1, 2, 99999]), "medida_que_nao_existe")["n"] == 0
