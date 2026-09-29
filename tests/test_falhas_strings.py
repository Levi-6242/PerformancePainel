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


# ── entrada vazia × string morta (27/09/2026) ────────────────────────────────────────────────────────────────────
# Cruzamento com as OS: Ipv29 a Ipv32 davam 41% dos episódios e 55% do kWh de setembro, e são entradas SEM string
# ligada — 0 A cravado o dia inteiro (Santana do Ipanema 1.13, Guatambu 4.6). A régua do dia passa a dizer duas
# coisas a mais para o mês separar uma da outra: se a string leu ZERO o tempo todo (a assinatura da entrada vazia;
# string morta costuma ler ruído) e quantas strings do inversor estavam vivas (para comparar com o cadastro).

def avaliado(curvas):
    return falhas.avaliar_dia(curvas, zero=0.1, piso_inv=0.5)


def test_avaliar_dia_conta_as_strings_vivas_do_inversor():
    r = avaliado(inversor([(h, 0.0) for h, _ in sino(8.0)]))
    assert r["vivas"] == {"Inversor 1.1": 4}


def test_entrada_que_le_zero_o_dia_todo_sai_marcada_como_sempre_zero():
    r = avaliado(inversor([(h, 0.0) for h, _ in sino(8.0)]))
    (m,) = r["mortas"]
    assert m["string"] == "ST 05" and m["sempre_zero"] is True


def test_string_morta_com_ruido_nao_e_sempre_zero_nem_conta_como_viva():
    # 0,3 A de ruído: é string morta (a régua aponta), mas leu alguma coisa — não é a assinatura da entrada vazia
    r = avaliado(inversor([(h, 0.3) for h, _ in sino(8.0)]))
    (m,) = r["mortas"]
    assert m["sempre_zero"] is False
    assert r["vivas"] == {"Inversor 1.1": 4}


def test_string_que_morreu_no_meio_do_dia_nao_e_sempre_zero_e_conta_como_viva():
    r = avaliado(inversor(troca(sino(8.0), "10:00", "12:10", 0.0)))
    (m,) = r["mortas"]
    assert m["sempre_zero"] is False
    assert r["vivas"] == {"Inversor 1.1": 5}


def test_inversor_que_gerou_menos_de_duas_horas_nao_prova_nada():
    # dia de nuvem forte: nem as vivas nem a entrada zerada dizem alguma coisa
    curto = {f"ST 0{i}": sino(8.0, ini=11 * 60, fim=12 * 60 + 30) for i in range(1, 5)}
    curto["ST 05"] = [(h, 0.0) for h, _ in sino(8.0, ini=11 * 60, fim=12 * 60 + 30)]
    assert avaliado({"Inversor 1.1": curto})["vivas"] == {}


def test_inversor_parado_fica_fora_das_vivas():
    curvas = {"Inversor 1.1": {f"ST 0{i}": [(h, 0.0) for h, _ in sino(8.0)] for i in range(1, 6)}}
    assert avaliado(curvas) == {"mortas": [], "vivas": {}, "sombras": []}


def test_morta_leva_a_hora_em_que_o_inversor_comecou_a_gerar():
    # para a montagem saber se a "volta" da manhã durou pouco (a volta falsa com pouca luz)
    (m,) = avaliado(inversor([(h, 0.0) for h, _ in sino(8.0)]))["mortas"]
    assert m["ini_producao"] == "06:30"


def test_strings_sem_corrente_segue_devolvendo_so_as_mortas():
    assert achadas(inversor([(h, 0.0) for h, _ in sino(8.0)])).keys() == {("Inversor 1.1", "ST 05")}


# ── sombra não é falha (29/09/2026) ──────────────────────────────────────────────────────────────────────────
# Levi, com print da aba: "alarme falsos nessas strings, verifiquei tanto na plataforma quanto em um supervisório
# auxiliar do Fusion e mostra essas strings funcionando normalmente". MAB100 Inversor 4.2 ST07 em 02/09 e Inversor 5.1
# ST07 em 12/09: de manhã a string acompanha as vizinhas; depois ela CAI EM RAMPA — 89% da mediana às 10:00, 51% às
# 12:30, 8% às 14:30, uns 4 pontos a cada 10 min com o inversor a 95-100% do pico — e fica em 0,64/0,44 A até o fim do
# dia, com as vizinhas a 7,5 A. É sombra crescendo, não string que abriu: falha de string é degrau (cai em uma leitura).
# A régua pedia só "abaixo de 10% das vizinhas por 2 h". Na varredura de setembro a mesma rampa só apareceu mais uma
# vez (MTS200 2.15 ST04, 19/09); os outros 14 inversor-dias de "queda lenta" não tinham rampa — ver os testes do fim.
import json as _json
import os as _os

_FIX = _os.path.join(_os.path.dirname(__file__), "fixtures", "falhas_sombra")


def _real(nome):
    d = _json.load(open(_os.path.join(_FIX, nome), encoding="utf-8"))
    return {d["inversor"]: {st: [tuple(p) for p in s] for st, s in d["strings"].items()}}


def _sunop(curvas):
    return falhas.avaliar_dia(curvas, zero=0.1, piso_inv=0.5)


def test_sombra_que_cresce_a_tarde_na_mab100_e_na_mts200_nao_e_falha():
    for nome, st in (("sunop__mab100__2026-09-02__inversor-4.2.json", "ST 07"),
                     ("sunop__mab100__2026-09-12__inversor-5.1.json", "ST 07"),
                     ("sunop__mts200__2026-09-19__inversor-2.15.json", "ST 04")):
        res = _sunop(_real(nome))
        assert [m["string"] for m in res["mortas"]] == [], (nome, res["mortas"])
        (s,) = res["sombras"]
        assert s["string"] == st and s["entrada_min"] >= 60, s


def _fracao(serie, pontos):
    """A curva multiplicada por uma fração que varia no dia: pontos = [(hh:mm, fração)], interpolação linear."""
    xs = [(int(h[:2]) * 60 + int(h[3:]), f) for h, f in pontos]
    out = []
    for hhmm, v in serie:
        m = int(hhmm[:2]) * 60 + int(hhmm[3:])
        if m <= xs[0][0]:
            f = xs[0][1]
        elif m >= xs[-1][0]:
            f = xs[-1][1]
        else:
            (a, fa), (b, fb) = next(((a, fa), (b, fb)) for (a, fa), (b, fb) in zip(xs, xs[1:]) if a <= m <= b)
            f = fa + (fb - fa) * (m - a) / (b - a)
        out.append((hhmm, v * f))
    return out


def test_sombra_sintetica_a_tarde_nao_e_falha():
    r = _sunop(inversor(_fracao(sino(8.0), [("11:00", 1.0), ("14:00", 0.05), ("18:00", 0.05)])))
    assert r["mortas"] == [] and r["sombras"][0]["string"] == "ST 05"


def test_degrau_a_tarde_continua_falha():
    # a mesma hora e a mesma corrente final da sombra, mas caindo de uma leitura para a outra
    r = _sunop(inversor(_fracao(sino(8.0), [("13:50", 1.0), ("14:00", 0.05), ("18:00", 0.05)])))
    (m,) = r["mortas"]
    assert m["string"] == "ST 05" and not r["sombras"]


def test_sombra_da_manha_que_sai_devagar_nao_e_falha():
    r = _sunop(inversor(_fracao(sino(8.0), [("06:00", 0.03), ("09:00", 0.03), ("12:00", 1.0)])))
    assert r["mortas"] == [] and r["sombras"][0]["saida_min"] >= 60


def test_morta_desde_o_amanhecer_com_volta_em_degrau_continua_falha():
    r = _sunop(inversor(troca(sino(8.0), "06:00", "13:00", 0.0)))
    (m,) = r["mortas"]
    assert m["voltou"] == "13:00" and not r["sombras"]


def test_zerada_o_dia_todo_continua_falha_e_nao_e_sombra():
    r = _sunop(inversor(troca(sino(8.0), "06:00", "18:01", 0.0)))
    assert [m["string"] for m in r["mortas"]] == ["ST 05"] and not r["sombras"]


def test_string_morta_que_le_resto_de_corrente_com_pouca_luz_continua_falha():
    # SMP100 5.2 ST15 (MPPT em curto, OS 13297): lê ~0,4 A fixo; de manhã as vizinhas também estão fracas e ela parece
    # "viva", depois as vizinhas sobem e a razão cai devagar — não é sombra, a corrente dela nunca caiu
    r = _sunop(inversor([(h, 0.4 if v > 0.1 else 0.0) for h, v in sino(8.0)]))
    assert [m["string"] for m in r["mortas"]] == ["ST 05"] and not r["sombras"]


def test_resto_de_corrente_que_passa_de_50_por_cento_na_partida_continua_falha():
    # com 0,6 A fixos a string morta lê mais que metade das vizinhas na partida do inversor; depois a razão "cai em
    # rampa" sozinha, porque as vizinhas sobem com o sol. Só o sol forte exigido na janela separa isso da sombra
    r = _sunop(inversor([(h, 0.6 if v > 0.1 else 0.0) for h, v in sino(8.0)]))
    assert [m["string"] for m in r["mortas"]] == ["ST 05"] and not r["sombras"]


def test_nuvem_no_meio_da_rampa_nao_desfaz_a_sombra():
    # na nuvem não há sol direto e a sombra some: por uma leitura a string sombreada volta a ler como as vizinhas (a
    # leitura boa de referência vale com qualquer luz) e a rampa segue depois dela, com sol forte
    ref = dict(sino(8.0))
    strs = {f"ST 0{i}": sino(8.0) for i in range(1, 5)}
    strs["ST 05"] = _fracao(sino(8.0), [("11:00", 1.0), ("14:00", 0.05), ("18:00", 0.05)])
    strs = {st: [(h, ref[h] * 0.2 if h == "12:30" else v) for h, v in serie] for st, serie in strs.items()}
    r = _sunop({"Inversor 1.1": strs})
    assert r["mortas"] == [] and [x["string"] for x in r["sombras"]] == ["ST 05"]


# ── o que parecia "queda lenta" e não era sombra (varredura de setembro, 29/09) ─────────────────────────────────
# Medir só o relógio desde a última leitura boa (a 1ª versão da régua da sombra) chamava de sombra 23 trechos, em 9
# inversor-dias, sem rampa nenhuma. A rampa pede, em toda célula entre a leitura boa e o trecho, sol forte e a razão
# para as vizinhas num sentido só.

def test_queda_que_atravessa_buraco_de_dado_nao_e_sombra():
    # MTS100 Inversor 3.7, 22/09: ST11-13 a 100% das vizinhas às 12:20, 2 h SEM LEITURA do inversor e zeradas às
    # 14:20 — o relógio via 120 min de "queda". Amanheceram mortas no dia 23: falha.
    res = _sunop(_real("sunop__mts100__2026-09-22__inversor-3.7.json"))
    assert sorted(m["string"] for m in res["mortas"]) == ["ST 11", "ST 12", "ST 13"] and res["sombras"] == []


def test_dia_no_patamar_de_20_por_cento_do_pico_nao_desenha_sombra():
    # CPP100 Inversor 4.1, 14/09: o inversor passa o dia a ~20% do pico, com picos curtos de sol. A última leitura boa
    # com sol forte ficava horas antes do trecho (ST05 com "saída" de 240 min) — sem sol forte não há sombra
    res = _sunop(_real("sunop__cpp100__2026-09-14__inversor-4.1.json"))
    assert sorted(m["string"] for m in res["mortas"]) == ["ST 02", "ST 05", "ST 10", "ST 17"] and res["sombras"] == []


def test_string_que_pisca_nao_e_sombra():
    # SMP100 Inversor 3.1, 22/09: a ST03 pisca entre 0 e 0,4 A o dia todo com o inversor forte; na "volta" das 14 h
    # ela vai a 36% e 43% das vizinhas e cai para 16% antes de passar de 50% — não é rampa
    res = _sunop(_real("sunop__smp100__2026-09-22__inversor-3.1.json"))
    assert "ST 03" in {m["string"] for m in res["mortas"]} and res["sombras"] == []
