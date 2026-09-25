# -*- coding: utf-8 -*-
"""Falhas de strings — régua nova (pedido do Levi, 24/09/2026).

"Se a string em período solar (de 6 às 18) ficou mais que 2 horas sem corrente ou com variação mínima em relação
aos demais (às vezes pode haver ruído)". Cada teste é um caso que a régua antiga (corrente <= 0,1 A por 30 min)
errava ou que a nova não pode errar:

- string morta que lê 0,3 A de ruído: a régua antiga não via (0,3 > 0,1); a nova compara com as vizinhas;
- queda curta (sombra, nuvem, religamento) não é falha: só conta quem fica 2 h SEGUIDAS sem corrente — somar o
  dia fazia a sombra do amanhecer + a do fim da tarde virar falha (2C, setembro: 60 string-dias assim);
- só conta a hora em que o inversor gera de verdade (>= 12% do próprio pico): sol baixo não é período útil;
- pôr do sol e inversor parado não apontam string — o inversor inteiro caiu junto;
- ruído não pode quebrar a queda em pedaços nem fingir que a string voltou.
"""
import math

import falhas


def sino(pico, ini=6 * 60, fim=18 * 60):
    """Curva de string saudável: meia senoide de ini a fim, uma leitura a cada 10 min."""
    return [(f"{m // 60:02d}:{m % 60:02d}", max(0.0, pico * math.sin(math.pi * (m - ini) / (fim - ini))))
            for m in range(ini, fim + 1, 10)]


def troca(serie, de, ate, valor):
    """A mesma curva com as leituras de [de, ate) trocadas por `valor` (None = sem leitura)."""
    a, b = int(de[:2]) * 60 + int(de[3:]), int(ate[:2]) * 60 + int(ate[3:])
    out = []
    for hhmm, v in serie:
        m = int(hhmm[:2]) * 60 + int(hhmm[3:])
        if a <= m < b:
            if valor is None:
                continue
            out.append((hhmm, valor))
        else:
            out.append((hhmm, v))
    return out


def inversor(teste):
    """Quatro strings saudáveis (8 A de pico) e a string ST 05 sob teste."""
    strs = {f"ST 0{i}": sino(8.0) for i in range(1, 5)}
    strs["ST 05"] = teste
    return {"Inversor 1.1": strs}


def achadas(curvas, **kw):
    return {(r["inversor"], r["string"]): r for r in falhas.strings_sem_corrente(curvas, zero=0.1, piso_inv=0.5, **kw)}


def test_string_zerada_o_dia_todo_sai_na_partida_do_inversor_e_nao_volta():
    r = achadas(inversor(troca(sino(8.0), "06:00", "18:01", 0.0)))
    f = r[("Inversor 1.1", "ST 05")]
    assert f["saiu"] == "06:30"          # 1ª leitura com o inversor a >= 12% do pico (mediana das vivas)
    assert f["voltou"] is None           # ficou zerada até o inversor parar de gerar
    assert f["min_morta"] >= 10 * 60


def test_ruido_perto_de_zero_conta_como_sem_corrente():
    # 0,3 A o dia todo: acima dos 0,1 A da régua antiga, mas < 10% das vizinhas no miolo do dia
    r = achadas(inversor([(h, 0.3) for h, _ in sino(8.0)]))
    f = r[("Inversor 1.1", "ST 05")]
    assert f["criterio"]["abaixo_das_vizinhas"] > 0
    assert f["criterio"]["zerada"] == 0
    assert f["min_morta"] >= 120


def test_queda_de_uma_hora_e_meia_nao_entra():
    assert achadas(inversor(troca(sino(8.0), "10:00", "11:30", 0.0))) == {}


def test_dois_trechos_curtos_no_dia_nao_somam_duas_horas():
    teste = troca(troca(sino(8.0), "09:00", "10:10", 0.0), "13:00", "14:00", 0.0)
    assert achadas(inversor(teste)) == {}


def test_duas_horas_e_dez_seguidas_entram_com_saida_e_volta():
    f = achadas(inversor(troca(sino(8.0), "10:00", "12:10", 0.0)))[("Inversor 1.1", "ST 05")]
    assert f["min_morta"] == 130
    assert f["trechos"] == [["10:00", "12:10"]]
    assert (f["saiu"], f["voltou"]) == ("10:00", "12:10")


def test_por_do_sol_nao_e_falha():
    # todas as strings apagam juntas às 17:00: é o inversor inteiro, não uma string
    curvas = {"Inversor 1.1": {f"ST 0{i}": sino(8.0, fim=17 * 60) for i in range(1, 6)}}
    assert achadas(curvas) == {}


def test_inversor_parado_nao_aponta_string():
    curvas = {"Inversor 1.1": {f"ST 0{i}": [(h, 0.0) for h, _ in sino(8.0)] for i in range(1, 6)}}
    assert achadas(curvas) == {}


def test_volta_no_meio_do_dia():
    f = achadas(inversor(troca(sino(8.0), "06:00", "12:00", 0.0)))[("Inversor 1.1", "ST 05")]
    assert (f["saiu"], f["voltou"]) == ("06:30", "12:00")


def test_uma_leitura_boa_no_meio_da_queda_nao_vira_volta():
    teste = troca(troca(sino(8.0), "06:00", "12:00", 0.0), "12:10", "18:01", 0.0)   # só 12:00 lê normal
    f = achadas(inversor(teste))[("Inversor 1.1", "ST 05")]
    assert f["voltou"] is None
    assert len(f["trechos"]) == 1


def test_piscadas_isoladas_nao_somam_duas_horas():
    teste = sino(8.0)
    for h in range(7, 18):                  # 11 leituras zeradas, uma por hora, isoladas
        teste = troca(teste, f"{h:02d}:30", f"{h:02d}:40", 0.0)
    assert achadas(inversor(teste)) == {}


def test_string_sem_nenhuma_leitura_nao_afirma_queda():
    assert achadas(inversor([])) == {}


def test_string_que_para_de_reportar_com_as_vizinhas_produzindo_conta_como_zerada():
    teste = troca(sino(8.0), "09:00", "18:01", None)       # a partir das 09:00 o canal some
    f = achadas(inversor(teste))[("Inversor 1.1", "ST 05")]
    assert f["saiu"] == "09:00" and f["voltou"] is None


def test_inversor_com_mais_da_metade_das_strings_mortas_ainda_aponta_as_mortas():
    # SMP100 Inversor 3.1, 24/09: 10 de 17 strings zeradas → a mediana de TODAS vira zero e o inversor
    # parecia parado. A referência é a mediana das strings VIVAS, como no classificador ao vivo da plataforma.
    strs = {f"ST {i:02d}": sino(1.5) for i in range(1, 8)}
    strs.update({f"ST {i:02d}": [(h, 0.0) for h, _ in sino(1.5)] for i in range(8, 18)})
    r = achadas({"Inversor 3.1": strs})
    assert {s for _, s in r} == {f"ST {i:02d}" for i in range(8, 18)}


def test_uma_string_viva_sozinha_nao_faz_o_inversor_gerar():
    # canal único com leitura (ruído ou string solta) não basta para dizer que o inversor está gerando
    strs = {"ST 01": sino(8.0)}
    strs.update({f"ST {i:02d}": [(h, 0.0) for h, _ in sino(8.0)] for i in range(2, 10)})
    assert achadas({"Inversor 1.1": strs}) == {}


def test_sombra_de_sol_baixo_no_amanhecer_e_no_fim_da_tarde_nao_e_falha():
    # Sete Lagoas Inv 1.9, 01/09: a string acorda depois e apaga antes das vizinhas (sombra com o sol baixo) —
    # somando o dia dava mais de 2 h "sem corrente" e virava falha. São dois trechos, e nenhum tem 2 h seguidas.
    teste = troca(troca(sino(8.0), "06:00", "08:00", 0.0), "16:00", "18:01", 0.0)
    assert achadas(inversor(teste)) == {}
