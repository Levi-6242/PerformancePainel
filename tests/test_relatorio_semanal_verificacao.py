# -*- coding: utf-8 -*-
"""Relatório Semanal Thopen — considerações do Levi em 05/10/2026.

1. Usina sem IPOA não fica "fora do PR": o PR usa a irradiação de referência do cliente (a meta de IPOA do mês) nos
   dias sem medição, sempre com asterisco.
2. Geração × disponibilidade incoerente vai ao FIM do relatório, como ponto em verificação ("Thopen gosta de ver que
   está no nosso radar") — sem o dia que a coleta ainda não gravou: na segunda de manhã o domingo ainda não está no
   BD_Thopen (a coleta das 22:30 grava o dia anterior), e em 28/09–04/10 eram 51 dos 65 avisos.
3. O card "Geração real × meta" ganha a segunda linha: atingimento de geração pela meta corrigida pelo IPOA real.
4. Os campos tracejados aceitam digitação em qualquer navegador (contenteditable="true", cola só texto).
5. A causa principal pega a ETM medindo alto: a Vertentes gerou 106% da meta em 30 dias com a IPOA em 131% da
   referência — o PR de 61% contra 82% era o sensor, e o bloco 05 dizia "Trackers parados".
"""
from datetime import date, timedelta
from pathlib import Path

import pytest

import relatorio_semanal as rs

INI, FIM = date(2026, 9, 21), date(2026, 9, 27)
# setembro: meta 300 MWh (10 MWh/dia), irradiação de referência 150 kWh/m² (5/dia), PR meta 80%
METAS = {8: {"meta": 300_000.0, "metairr": 150.0, "pr": 0.80}, 9: {"meta": 300_000.0, "metairr": 150.0, "pr": 0.80}}


def dia(d, ger, ipoa):
    return {"data": d, "ger": ger, "ipoa": ipoa}


def semana(ger, ipoa, ini=INI, n=7):
    return [dia(ini + timedelta(days=i), ger, ipoa) for i in range(n)]


# ── 1. IPOA da referência nos dias sem medição ───────────────────────────────────────────────────────────────────
def test_dia_sem_ipoa_usa_a_irradiacao_de_referencia_do_cliente():
    r = rs.pr_unidade([dia(INI, 10_000, 5.0), dia(INI + timedelta(days=1), 8_000, None)], 2.5, METAS, INI,
                      INI + timedelta(days=1))
    # 18 MWh ÷ ((5,0 medido + 5,0 da referência) × 2,5 MWp)
    assert r["pr"] == pytest.approx(18 / (10 * 2.5))
    assert r["dias_ipoa_meta"] == 1 and r["dias_validos"] == 1 and r["dias_sem_ipoa"] == 1
    assert r["ipoa"] == pytest.approx(5.0) and r["ipoa_meta"] == pytest.approx(5.0)   # o "IPOA real × meta" segue medido


def test_ipoa_zero_tambem_e_sem_medicao_mas_ipoa_baixo_medido_segue_fora():
    r = rs.pr_unidade([dia(INI, 10_000, 0.0)], 2.5, METAS, INI, INI)
    assert r["dias_ipoa_meta"] == 1 and r["pr"] == pytest.approx(10 / (5 * 2.5))
    # 0,2 kWh/m² é medição (dia muito fechado): a régua do Histórico PR o descarta, e a referência não entra no lugar
    r = rs.pr_unidade([dia(INI, 500, 0.2)], 2.5, METAS, INI, INI)
    assert r["dias_ipoa_meta"] == 0 and r["pr"] is None


def test_sem_irradiacao_de_referencia_o_dia_segue_fora():
    r = rs.pr_unidade([dia(INI, 10_000, None)], 2.5, {9: {"meta": 300_000.0, "pr": 0.8}}, INI, INI)
    assert r["pr"] is None and r["dias_ipoa_meta"] == 0


class L:
    """Leitores de mentira. `dados` = {aba: diário}; potência 2,5 MWp; metas de setembro."""

    def __init__(self, dados, disp=None):
        self.dados, self.disp = dados, disp or {}

    def diario(self, aba):
        return self.dados.get(aba) or []

    def pot(self, aba):
        return 2.5 if aba in self.dados else None

    def metas(self, aba):
        return METAS if aba in self.dados else {}

    def disp_diario(self, usina):
        return self.disp.get(usina) or {}

    def oss(self):
        return []

    def linhas_os(self):
        return []

    def falhas(self):
        return {"strings": [], "trackers": []}


def un(nome):
    return {"nome": nome, "bd": [nome], "disp": [nome], "sites": [], "kwp": 2500.0}


def test_usina_sem_ipoa_entra_no_pr_com_asterisco():
    p = rs.montar(INI, FIM, [un("Brodowski"), un("Altair")],
                  L({"Brodowski": semana(8_000, None), "Altair": semana(10_000, 5.0)}))
    b = next(u for u in p["usinas"] if u["nome"] == "Brodowski")
    assert b["pr"] == pytest.approx(8 / (5 * 2.5)) and b["ipoa_meta_dias"] == 7
    assert p["resumo"]["total"] == 2 and p["resumo"]["ipoa_meta_usinas"] == ["Brodowski"]
    assert any("Brodowski" in a and "referência" in a and "*" in a for a in p["avisos"])
    assert not any("fora do PR" in a for a in p["avisos"])


# ── 2. pontos em verificação no fim do relatório ─────────────────────────────────────────────────────────────────
def test_geracao_zero_com_usina_disponivel_vai_para_a_verificacao():
    dados = {"Altair": semana(10_000, 5.0) + semana(10_000, 5.0, ini=INI - timedelta(days=21), n=21)}
    dados["Altair"][2] = dia(INI + timedelta(days=2), 0.0, 5.0)          # 23/09 sem geração
    dados["Sorocaba"] = semana(9_000, 5.0) + semana(9_000, 5.0, ini=INI - timedelta(days=21), n=21)
    p = rs.montar(INI, FIM, [un("Altair"), un("Sorocaba")], L(dados))
    (v,) = [x for x in p["verificacao"] if x["tipo"] == "geracao_disponibilidade"]
    assert v["usina"] == "Altair" and "23/09" in v["texto"] and "BD_Thopen" not in v["texto"]


def test_dia_que_a_coleta_ainda_nao_gravou_nao_vira_inconsistencia():
    # segunda de manhã: o domingo (27/09) ainda não entrou para nenhuma usina
    dados = {n: semana(10_000, 5.0, n=6) + semana(10_000, 5.0, ini=INI - timedelta(days=21), n=21)
             for n in ("Altair", "Sorocaba", "Caicó")}
    p = rs.montar(INI, FIM, [un(n) for n in dados], L(dados))
    assert not [x for x in p["verificacao"] if x["tipo"] == "geracao_disponibilidade"]
    assert p["periodo"]["dias_sem_coleta"] == ["2026-09-27"]
    assert any("27/09" in a and "coleta" in a for a in p["avisos"])


# ── 3. atingimento de geração pela meta do IPOA ──────────────────────────────────────────────────────────────────
def test_atingimento_de_geracao_pela_meta_corrigida_pelo_ipoa_real():
    # meta 10 MWh/dia com 5 kWh/m²; o sol deu 4 → a meta corrigida é 8 MWh; gerou 8,8 → 110%
    r = rs.pr_unidade(semana(8_800, 4.0), 2.5, METAS, INI, FIM)
    assert r["ger_x_meta_ipoa"] == pytest.approx(8.8 / 8.0)
    p = rs.montar(INI, FIM, [un("Altair")], L({"Altair": semana(8_800, 4.0)}))
    assert p["resumo"]["ger_x_meta_ipoa"] == pytest.approx(1.1)
    assert p["resumo"]["ger_x_meta"] == pytest.approx(0.88)


# ── 5. ETM medindo alto ou baixo ─────────────────────────────────────────────────────────────────────────────────
def _vertentes():
    # 30 dias (29/08 a 27/09) gerando 106% da meta com a IPOA medida em 130% da referência: PR 10,6 ÷ (6,5 × 2,5)
    return semana(10_600, 6.5, ini=FIM - timedelta(days=29), n=30)


def test_geracao_acima_da_meta_com_ipoa_muito_acima_e_a_etm():
    p = rs.montar(INI, FIM, [un("Vertentes")], L({"Vertentes": _vertentes()}))
    (f,) = p["fora_da_meta"]
    assert f["ofensores"][0]["tipo"] == "ipoa" and f["causa_sugerida"].startswith("Irradiância acima do esperado")
    assert "130%" in f["causa_sugerida"] and "106%" in f["causa_sugerida"]
    (v,) = [x for x in p["verificacao"] if x["tipo"] == "etm_alta"]
    assert v["usina"] == "Vertentes" and "estação" in v["texto"]


def test_ipoa_alta_com_geracao_acompanhando_e_so_sol():
    # Ouro Branco 30 dias: geração 122% e IPOA 117% da referência — andaram juntas, o sensor está coerente
    p = rs.montar(INI, FIM, [un("Ouro Branco")],
                  L({"Ouro Branco": semana(12_200, 5.85, ini=FIM - timedelta(days=29), n=30)}))
    assert not [x for x in p["verificacao"] if x["tipo"].startswith("etm")]


def test_pr_acima_de_130_por_cento_em_3_dias_e_etm_medindo_baixo():
    d = semana(10_000, 5.0, ini=FIM - timedelta(days=29), n=30)
    for k in (25, 26, 27):
        d[k] = dia(d[k]["data"], 10_000, 2.0)                              # PR 200% nesses dias
    p = rs.montar(INI, FIM, [un("Corrego do Sapucaia")], L({"Corrego do Sapucaia": d}))
    (v,) = [x for x in p["verificacao"] if x["tipo"] == "etm_baixa"]
    assert v["usina"] == "Corrego do Sapucaia" and "3 dias" in v["texto"]


def test_usina_com_pr_pela_referencia_aparece_na_verificacao():
    p = rs.montar(INI, FIM, [un("Brodowski")], L({"Brodowski": semana(8_000, None)}))
    (v,) = [x for x in p["verificacao"] if x["tipo"] == "ipoa_meta"]
    assert v["usina"] == "Brodowski" and v["texto"].endswith("*")


def test_emissao_guarda_os_pontos_em_verificacao():
    est = {}
    snap = {"leitura": "ok", "responsavel": "Ana", "linhas": [], "verificacao": ["Vertentes: sensor em verificação"]}
    rs.registra_emissao(est, INI, FIM, snap, em="agora", por="teste")
    assert est[rs.chave(INI, FIM)]["emissoes"][0]["verificacao"] == ["Vertentes: sensor em verificação"]


# ── a página ────────────────────────────────────────────────────────────────────────────────────────────────────
PAGINA = (Path(rs.__file__).resolve().parent / "templates" / "relatorio_semanal.html").read_text(encoding="utf-8")


def test_pagina_tem_a_segunda_linha_do_card_de_geracao():
    assert "Atingimento de geração pela meta do IPOA" in PAGINA and "ger_x_meta_ipoa" in PAGINA


def test_pagina_tem_o_bloco_de_pontos_em_verificacao_no_fim():
    assert "Pontos em verificação pela Grid" in PAGINA
    assert PAGINA.index("${s05}") < PAGINA.index("${s06}")


def test_campos_editaveis_valem_em_qualquer_navegador():
    # "plaintext-only" é valor que navegador antigo não conhece: o campo fica tracejado e não aceita digitação
    assert 'contenteditable="plaintext-only"' not in PAGINA and 'contenteditable="true"' in PAGINA
    assert "addEventListener('paste'" in PAGINA                            # colar entra como texto puro


def test_rodape_diz_que_o_pr_sem_ipoa_usa_a_referencia():
    assert "dias sem medição de IPOA ficam fora do PR" not in PAGINA
    assert "irradiação de referência do cliente" in PAGINA


# ── 1b. a referência corrigida pelo sol do dia (Levi, 05/10/2026: "Corrigir pelo sol do dia"; "entra em tudo porém com
#        um asterisco") ─────────────────────────────────────────────────────────────────────────────────────────────
def test_fator_do_dia_e_a_ipoa_medida_sobre_a_referencia_de_quem_mediu():
    series = [(semana(10_000, 4.0), 2.5, METAS), (semana(9_000, 6.0), 2.5, METAS), (semana(8_000, None), 2.5, METAS)]
    f = rs.fator_sol(series)
    assert f[INI] == pytest.approx((4.0 + 6.0) / (5.0 + 5.0))      # quem não mediu não entra no fator


def test_dia_sem_ipoa_usa_a_referencia_corrigida_pelo_sol_do_dia():
    r = rs.pr_unidade(semana(8_000, None), 2.5, METAS, INI, FIM, fator={INI + timedelta(days=i): 0.8 for i in range(7)})
    assert r["pr"] == pytest.approx(8 / (5 * 0.8 * 2.5))


def test_semana_nublada_nao_derruba_o_pr_da_usina_sem_ipoa():
    # a Altair mede 4,0 (80% da referência) — a Brodowski, sem sensor, ganha a mesma correção
    p = rs.montar(INI, FIM, [un("Brodowski"), un("Altair")],
                  L({"Brodowski": semana(8_000, None), "Altair": semana(8_000, 4.0)}))
    b = next(u for u in p["usinas"] if u["nome"] == "Brodowski")
    assert b["pr"] == pytest.approx(8 / (5 * 0.8 * 2.5))


def test_evolucao_marca_o_mes_com_pr_pela_referencia():
    series = [(semana(8_000, None), 2.5, METAS), (semana(8_000, 4.0), 2.5, METAS)]
    (m,) = rs.pr_mensal(series, [(2026, 9)], fator=rs.fator_sol(series))
    assert m["ipoa_meta"] is True and m["usinas"] == 2
    assert m["pr"] == pytest.approx(16 / (2 * 4.0 * 2.5))           # as duas com 4,0 de sol: a medida e a corrigida


def test_pagina_marca_a_evolucao_com_asterisco():
    assert "corrigida pelo sol do dia" in PAGINA and "m.ipoa_meta" in PAGINA
