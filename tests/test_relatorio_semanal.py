# -*- coding: utf-8 -*-
"""Relatório Semanal Thopen — as contas (plataforma/relatorio_semanal.py), 29/09/2026.

Relatório para o cliente, pedido pela Ana Patrícia e pelo Levi na reunião de 28/09: PR do portfólio contra a meta do
cliente, disponibilidade por OS, o que a Grid executou e as usinas fora da meta com causa e ação. Cada teste trava uma
régua que o número mostrado ao cliente depende:
- PR = geração ÷ (IPOA × potência) só nos dias com IPOA > 0,3 — a régua do Histórico PR (api_g_diario);
- a meta de PR de uma semana entre dois meses pesa cada mês pelo que o dia pesou no denominador;
- o portfólio soma numeradores e denominadores, nunca faz média de PR;
- fora da meta = PR abaixo de 97% da meta.
"""
from datetime import date

import pytest

import relatorio_semanal as rs


def dia(d, ger, ipoa):
    return {"data": d, "ger": ger, "ipoa": ipoa}


METAS = {9: {"meta": 300_000.0, "metairr": 150.0, "pr": 0.80}, 10: {"meta": 310_000.0, "metairr": 155.0, "pr": 0.70}}


def test_dias_do_periodo_sao_inclusivos():
    assert rs.dias(date(2026, 9, 28), date(2026, 10, 4)) == [date(2026, 9, 28 + i) for i in range(3)] + [
        date(2026, 10, i) for i in range(1, 5)]


def test_pr_da_unidade_e_geracao_sobre_ipoa_vezes_potencia():
    r = rs.pr_unidade([dia(date(2026, 9, 21), 10_000, 5.0), dia(date(2026, 9, 22), 20_000, 5.0)], 5.0, METAS,
                      date(2026, 9, 21), date(2026, 9, 22))
    assert r["pr"] == pytest.approx(30 / (10 * 5))            # 30 MWh ÷ (IPOA 10 × 5 MWp)
    assert r["dias_validos"] == 2 and r["dias_sem_ipoa"] == 0


def test_dia_sem_ipoa_fica_fora_do_pr_mas_conta_na_geracao():
    # a régua do Histórico PR descarta o dia com IPOA <= 0,3 kWh/m²: sem irradiação medida não há PR
    r = rs.pr_unidade([dia(date(2026, 9, 21), 10_000, 5.0), dia(date(2026, 9, 22), 20_000, 0.2)], 5.0, METAS,
                      date(2026, 9, 21), date(2026, 9, 22))
    assert r["pr"] == pytest.approx(10 / 25)
    assert r["ger_total_kwh"] == 30_000 and r["dias_sem_ipoa"] == 1


def test_meta_de_semana_entre_dois_meses_pesa_pelo_denominador_do_dia():
    r = rs.pr_unidade([dia(date(2026, 9, 30), 10_000, 6.0), dia(date(2026, 10, 1), 10_000, 2.0)], 5.0, METAS,
                      date(2026, 9, 30), date(2026, 10, 1))
    assert r["pr_meta"] == pytest.approx((0.80 * 6 + 0.70 * 2) / 8)


def test_meta_em_porcentagem_na_planilha_vira_fracao():
    r = rs.pr_unidade([dia(date(2026, 9, 21), 10_000, 5.0)], 5.0, {9: {"meta": 1.0, "metairr": 1.0, "pr": 78.4}},
                      date(2026, 9, 21), date(2026, 9, 21))
    assert r["pr_meta"] == pytest.approx(0.784)


def test_meta_de_geracao_e_de_irradiacao_sao_a_mensal_rateada_nos_dias_com_dado():
    r = rs.pr_unidade([dia(date(2026, 9, 21), 10_000, 5.0), dia(date(2026, 9, 22), 10_000, 0.0)], 5.0, METAS,
                      date(2026, 9, 21), date(2026, 9, 22))
    assert r["meta_kwh"] == pytest.approx(2 * 300_000 / 30)          # os dois dias têm geração
    assert r["ipoa_meta"] == pytest.approx(150 / 30)                  # só o dia com IPOA medida
    assert r["ipoa"] == pytest.approx(5.0)


def test_dia_com_pr_acima_de_130_por_cento_e_marcado():
    # PR de 150% num dia = IPOA subestimada (o alerta do Criador de hoje)
    r = rs.pr_unidade([dia(date(2026, 9, 21), 15_000, 2.0)], 5.0, METAS, date(2026, 9, 21), date(2026, 9, 21))
    assert r["dias_pr_alto"] == 1


def test_fora_da_meta_e_pr_abaixo_de_97_por_cento_da_meta():
    assert rs.fora_da_meta({"pr": 0.77, "pr_meta": 0.80}) is True       # 0,77 < 0,776
    assert rs.fora_da_meta({"pr": 0.777, "pr_meta": 0.80}) is False
    assert rs.fora_da_meta({"pr": None, "pr_meta": 0.80}) is False      # sem PR não se afirma


def test_perda_estimada_e_a_energia_ate_a_meta_com_o_sol_que_veio():
    assert rs.perda_estimada_mwh({"pr": 0.70, "pr_meta": 0.80, "den_mwh": 100.0}) == pytest.approx(10.0)
    assert rs.perda_estimada_mwh({"pr": 0.85, "pr_meta": 0.80, "den_mwh": 100.0}) == 0.0


def test_portfolio_soma_numerador_e_denominador_e_nao_faz_media_de_pr():
    a = rs.pr_unidade([dia(date(2026, 9, 21), 90_000, 6.0)], 20.0, METAS, date(2026, 9, 21), date(2026, 9, 21))
    b = rs.pr_unidade([dia(date(2026, 9, 21), 1_000, 6.0)], 1.0, METAS, date(2026, 9, 21), date(2026, 9, 21))
    t = rs.soma([a, b])
    assert t["pr"] == pytest.approx(91 / (6 * 21))                      # média dos PRs daria (0,75 + 0,167) / 2
    assert t["ger_total_kwh"] == 91_000 and t["dias_validos"] == 2


def test_pr_mensal_do_portfolio_de_janeiro_ao_mes_corrente():
    serie = [dia(date(2026, 8, 10), 10_000, 5.0), dia(date(2026, 9, 10), 20_000, 5.0)]
    metas = {8: {"meta": 1.0, "metairr": 1.0, "pr": 0.5}, 9: {"meta": 1.0, "metairr": 1.0, "pr": 0.9}}
    ev = rs.pr_mensal([(serie, 5.0, metas)], [(2026, 8), (2026, 9)])
    assert [(m["mes"], round(m["pr"], 3), m["pr_meta"]) for m in ev] == [(8, 0.4, 0.5), (9, 0.8, 0.9)]


def test_assuncao_em_01_01_2026_e_usina_nova_entra_quando_passa_a_ter_dia():
    # Levi, 30/09: "começa por 01/01/2026 e aí tem usinas que entraram depois disso, elas vão entrando no cálculo"
    assert rs.ASSUNCAO == date(2026, 1, 1)
    meses = rs.meses_desde(rs.ASSUNCAO, date(2027, 2, 10))
    assert meses[0] == (2026, 1) and meses[-1] == (2027, 2) and len(meses) == 14
    antiga = ([dia(date(2026, m, 10), 20_000, 5.0) for m in (1, 2, 3)], 5.0, {m: {"pr": 0.8} for m in (1, 2, 3)})
    nova = ([dia(date(2026, 3, 10), 5_000, 5.0)], 5.0, {3: {"pr": 0.8}})              # entrou em março
    ev = rs.pr_mensal([antiga, nova], rs.meses_desde(rs.ASSUNCAO, date(2026, 3, 31)))
    assert [m["usinas"] for m in ev] == [1, 1, 2]
    assert ev[0]["pr"] == pytest.approx(0.8) and ev[2]["pr"] == pytest.approx(25_000 / 1000 / 50)


# ── bloco 04: disponibilidade e desligamentos (índice de disponibilidade por OS do worker) ─────────────────────
def test_disponibilidade_do_periodo_pelo_diario_do_indice():
    # 27/09 da Altair no índice: h_eq 1,553 (disp do dia 87,1%); numa semana de 7 dias a janela é 84 h
    diario = {"2026-09-27": {"h_eq": 1.553, "h_q": 1.553, "h_e": 0.0}, "2026-09-10": {"h_eq": 5.0, "h_q": 0, "h_e": 5}}
    r = rs.disponibilidade(diario, date(2026, 9, 21), date(2026, 9, 27))
    assert r["disp"] == pytest.approx(100 * (1 - 1.553 / 84))       # o dia 10 está fora do período
    assert (r["h_q"], r["h_e"], r["dias"]) == (1.553, 0.0, 7)


def test_dia_fora_do_diario_e_usina_disponivel():
    assert rs.disponibilidade({}, date(2026, 9, 21), date(2026, 9, 27))["disp"] == 100.0


def test_disponibilidade_do_portfolio_pondera_pela_potencia():
    a = rs.disponibilidade({"2026-09-21": {"h_eq": 12.0, "h_q": 12.0, "h_e": 0.0}}, date(2026, 9, 21), date(2026, 9, 21))
    b = rs.disponibilidade({}, date(2026, 9, 21), date(2026, 9, 21))
    t = rs.disponibilidade_portfolio([(a, 1000.0), (b, 3000.0)])
    assert t["disp"] == pytest.approx(75.0) and t["indisp_ext"] == pytest.approx(25.0) and t["indisp_grid"] == 0.0


def _os(origem, ini, fim, usina="Altair", aberta=False):
    return {"origem": origem, "ini": ini, "fim": fim, "usinas": [usina], "aberta": aberta}


def test_desligamento_conta_so_as_horas_de_sol_dentro_do_periodo():
    # queda das 17:00 do dia 21 às 07:00 do dia 22: 1 h de sol em cada dia
    r = rs.desligamentos([_os("queda", "2026-09-21T17:00:00", "2026-09-22T07:00:00")], date(2026, 9, 21),
                         date(2026, 9, 27))
    assert r["queda"] == {"n": 1, "h": pytest.approx(2.0)} and r["equip"] == {"n": 0, "h": 0.0}


def test_desligamento_que_comeca_antes_do_periodo_conta_so_a_parte_de_dentro():
    r = rs.desligamentos([_os("equipamento", "2026-09-20T10:00:00", "2026-09-21T10:00:00")], date(2026, 9, 21),
                         date(2026, 9, 27))
    assert r["equip"] == {"n": 1, "h": pytest.approx(4.0)}           # 06:00–10:00 do dia 21


def test_os_aberta_sem_fim_conta_na_quantidade_com_zero_hora():
    # a régua do módulo disponibilidade: OS aberta sem fim = 0 h (Mandaguaçu e Céu Azul, gerando com OS esquecida)
    r = rs.desligamentos([_os("queda", "2026-09-22T09:00:00", None, aberta=True)], date(2026, 9, 21),
                         date(2026, 9, 27))
    assert r["queda"] == {"n": 1, "h": 0.0}


def test_filtro_de_usinas_no_desligamento():
    oss = [_os("queda", "2026-09-22T09:00:00", "2026-09-22T09:40:00"),
           _os("queda", "2026-09-23T09:00:00", "2026-09-23T10:00:00"),
           _os("queda", "2026-09-23T09:00:00", "2026-09-23T13:00:00", usina="Outra")]
    r = rs.desligamentos(oss, date(2026, 9, 21), date(2026, 9, 27), usinas={"Altair"})
    assert r["queda"] == {"n": 2, "h": pytest.approx(40 / 60 + 1.0)}


# ── bloco 03: o que a Grid executou (linhas de OS do Fracttal que o worker guarda) ──────────────────────────────
SITE = "Thopen - Altair 1 - SP"


def linha(folio, tipo, status, evento, site=SITE, tarefa=None, fim=None, criada=None, **k):
    x = {"wo_folio": str(folio), "tasks_log_task_type_main": tipo, "id_status_work_order": status,
         "event_date": evento, "groups_1_description": site, "id_work_orders_tasks": tarefa,
         "creation_date": criada or evento}
    if "sem_fim" not in k:
        x["final_date"] = fim
    return x


def test_corretivas_e_preventivas_contam_por_tarefa_e_finalizada_e_a_tarefa_com_fim():
    # Levi, 30/09: "quero que conte por tarefa" — a OS 1 tem duas tarefas corretivas, uma só terminada
    ls = [linha(1, "Corretiva", 1, "2026-09-22T12:00:00+00:00", tarefa=11, fim="2026-09-22T15:00:00+00:00"),
          linha(1, "Corretiva", 1, "2026-09-22T12:00:00+00:00", tarefa=12),
          linha(1, "Corretiva", 1, "2026-09-22T12:00:00+00:00", tarefa=12),                  # a mesma tarefa de novo
          linha(2, "Corretiva Emergencial", 3, "2026-09-23T12:00:00+00:00", tarefa=21, fim="2026-09-23T13:00:00+00:00"),
          linha(3, "Administrativa", 3, "2026-09-23T12:00:00+00:00", tarefa=31, fim="2026-09-23T13:00:00+00:00"),
          linha(4, "Corretiva", 4, "2026-09-23T12:00:00+00:00", tarefa=41, fim="2026-09-23T13:00:00+00:00"),  # cancelada
          linha(5, "Corretiva", 2, "2026-09-23T12:00:00+00:00", site="Outra - SP", tarefa=51),
          linha(6, "Preventiva", 1, "2026-09-24T12:00:00+00:00", tarefa=61, fim="2026-09-24T14:00:00+00:00"),
          linha(6, "Preventiva", 1, "2026-09-24T12:00:00+00:00", tarefa=62),
          linha(6, "Preventiva", 1, "2026-09-24T12:00:00+00:00", tarefa=63)]
    r = rs.os_executadas(ls, {SITE}, date(2026, 9, 21), date(2026, 9, 27))
    assert r["corretivas"] == {"concluidas": 2, "total": 3}
    assert r["preventivas"] == {"realizadas": 1, "planejadas": 3}


def test_base_de_antes_do_fim_da_tarefa_usa_a_os_concluida():
    ls = [linha(1, "Corretiva", 3, "2026-09-22T12:00:00+00:00", tarefa=11, sem_fim=True),
          linha(2, "Corretiva", 1, "2026-09-22T12:00:00+00:00", tarefa=21, sem_fim=True)]
    assert not rs.com_fim_da_tarefa(ls)
    assert rs.os_executadas(ls, {SITE}, date(2026, 9, 21), date(2026, 9, 27))["corretivas"] == {"concluidas": 1,
                                                                                                "total": 2}


def test_evento_de_madrugada_em_utc_e_do_dia_anterior_em_brasilia():
    ls = [linha(1, "Preventiva", 3, "2026-09-28T01:00:00+00:00", tarefa=1, fim="2026-09-28T02:00:00+00:00"),  # 27/09 22h
          linha(2, "Preventiva", 1, "2026-09-21T02:00:00+00:00", tarefa=2)]       # 20/09 23:00: fora
    r = rs.os_executadas(ls, {SITE}, date(2026, 9, 21), date(2026, 9, 27))
    assert r["preventivas"] == {"realizadas": 1, "planejadas": 1}


def rel(folio, criada, fim, tipo="Religamento", status=2, site=SITE, tarefa=None):
    return linha(folio, tipo, status, criada, site=site, tarefa=tarefa or folio, fim=fim, criada=criada)


def test_religamento_vai_da_criacao_da_os_ao_fim_da_tarefa_de_religamento():
    # Levi, 30/09: "basicamente a data da criação da OS - data fim da tarefa de religamento"
    ls = [rel(1, "2026-09-22T12:00:00+00:00", "2026-09-22T12:30:00+00:00"),
          rel(2, "2026-09-23T12:00:00+00:00", "2026-09-23T12:40:00+00:00", tipo="Religamento Remoto"),
          rel(3, "2026-09-24T12:00:00+00:00", "2026-09-24T12:50:00+00:00"),
          # queda longa da concessionária: puxa a média, não a mediana
          rel(4, "2026-09-25T09:00:00+00:00", "2026-09-26T15:00:00+00:00"),
          rel(5, "2026-09-18T12:00:00+00:00", "2026-09-18T13:00:00+00:00"),                   # terminou antes
          rel(6, "2026-09-22T12:00:00+00:00", "2026-09-22T13:00:00+00:00", status=4),         # cancelada
          rel(7, "2026-09-22T12:00:00+00:00", "2026-09-22T13:00:00+00:00", site="Outra - SP")]
    r = rs.religamento(ls, {SITE}, date(2026, 9, 21), date(2026, 9, 27))
    assert r["n"] == 4 and r["mediano_min"] == pytest.approx(45.0) and r["medio_min"] > 400
    assert r["retroativas"] == 0


def test_religamento_usa_a_tarefa_de_religamento_e_nao_a_corretiva_da_mesma_os():
    ls = [rel(1, "2026-09-22T12:00:00+00:00", "2026-09-22T12:20:00+00:00", tarefa=11),
          rel(1, "2026-09-22T12:00:00+00:00", "2026-09-25T12:00:00+00:00", tipo="Corretiva", tarefa=12)]
    assert rs.religamento(ls, {SITE}, date(2026, 9, 21), date(2026, 9, 27))["mediano_min"] == pytest.approx(20.0)


def test_os_registrada_depois_do_religamento_fica_fora_e_e_contada():
    ls = [rel(1, "2026-09-22T15:00:00+00:00", "2026-09-22T12:00:00+00:00"),
          rel(2, "2026-09-22T12:00:00+00:00", "2026-09-22T12:10:00+00:00")]
    r = rs.religamento(ls, {SITE}, date(2026, 9, 21), date(2026, 9, 27))
    assert (r["n"], r["retroativas"], r["mediano_min"]) == (1, 1, pytest.approx(10.0))


def test_rondas_do_app_de_campo_na_semana():
    ls = [{"Data": "2026-09-22", "Usina": SITE, "Tipo": "curta"}, {"Data": "2026-09-23", "Usina": SITE, "Tipo": "longa"},
          {"Data": "2026-09-24", "Usina": "Thopen - Sarandi - PR", "Tipo": "curta"},
          {"Data": "2026-09-20", "Usina": SITE, "Tipo": "curta"},                         # fora do período
          {"Data": "2026-09-22", "Usina": "RenoGrid - Colíder 2 - MT", "Tipo": "longa"}]   # fora da carteira
    r = rs.rondas(ls, {SITE, "Thopen - Sarandi - PR"}, date(2026, 9, 21), date(2026, 9, 27))
    assert r == {"total": 3, "curtas": 2, "longas": 1, "usinas": 2}


def _ger(dias_kwh):
    return {date(2026, 9, d): v for d, v in dias_kwh.items()}


def test_geracao_casa_com_a_disponibilidade_do_dia():
    # Levi, 30/09: "se a disponibilidade for 0 então a geração também será 0 e assim por diante"
    ger = _ger({d: 10_000.0 for d in range(1, 21)})
    ger.update(_ger({21: 0.0, 22: 0.0, 24: 9_500.0, 25: 9_000.0, 26: 10_000.0, 27: 10_000.0}))   # 23: sem linha
    disp = {date(2026, 9, 21): 0.0, date(2026, 9, 22): 1.0, date(2026, 9, 23): 0.5, date(2026, 9, 26): 0.0}
    av = rs.geracao_x_disponibilidade("Altair", ger, disp, date(2026, 9, 21), date(2026, 9, 27))
    assert av == ["Altair: sem geração no BD_Thopen em 22 a 23/09, com 50% a 100% de disponibilidade pelas OS",
                  "Altair: gerou 100% do típico em 26/09, com 0% de disponibilidade pelas OS"]


def test_dias_do_aviso_viram_intervalo():
    ds = [date(2026, 9, d) for d in (21, 22, 23, 25)] + [date(2026, 10, 1)]
    assert rs._dias_txt(ds) == "21 a 23/09, 25/09 e 01/10"
    assert rs._dias_txt([date(2026, 9, 30), date(2026, 10, 1)]) == "30/09 a 01/10"


def test_usina_que_entrou_no_meio_do_periodo_nao_tem_dia_faltando_antes_de_existir():
    ger = _ger({25: 8_000.0, 26: 8_000.0, 27: 8_000.0})
    assert rs.geracao_x_disponibilidade("Nova", ger, {}, date(2026, 9, 21), date(2026, 9, 27)) == []


def test_strings_que_voltaram_sao_os_episodios_que_terminaram_no_periodo():
    eps = [{"usina": "Altair", "inversor": "Inversor 1.1", "string": "Ipv1", "inicio": "2026-09-10 08:00",
            "fim": "2026-09-23 10:00"},
           {"usina": "Altair", "inversor": "Inversor 1.1", "string": "Ipv2", "inicio": "2026-09-10 08:00", "fim": None},
           {"usina": "Altair", "inversor": "Inversor 1.2", "string": "Ipv1", "inicio": "2026-09-10 08:00",
            "fim": "2026-09-29 10:00"},
           {"usina": "Outra", "inversor": "Inversor 1.1", "string": "Ipv1", "inicio": "2026-09-10 08:00",
            "fim": "2026-09-22"}]
    assert rs.strings_voltaram(eps, date(2026, 9, 21), date(2026, 9, 27), {"Altair"}) == 1
    assert rs.strings_voltaram(eps, date(2026, 9, 21), date(2026, 9, 27), None) == 2


# ── bloco 05: ofensores medidos e causa sugerida ────────────────────────────────────────────────────────────────
def test_ofensores_vem_do_maior_para_o_menor_em_energia():
    desl = {"queda": {"n": 2, "h": 9.5}, "equip": {"n": 0, "h": 0.0}}
    trk = [{"tracker": "T1", "inicio": "2026-09-21 08:00", "fim": None, "perda_kwh": 700.0, "dias": 7}]
    strs = [{"inversor": "Inversor 1.1", "string": f"Ipv{i}", "inicio": "2026-09-21 08:00", "fim": None,
             "perda_kwh": 100.0, "dias": 7} for i in range(3)]
    ofs = rs.ofensores(desl, trk, strs, {"dias_validos": 7, "dias_sem_ipoa": 0, "dias_pr_alto": 0}, 5_000.0,
                       date(2026, 9, 21), date(2026, 9, 27))
    assert [o["tipo"] for o in ofs] == ["desligamento", "tracker", "string"]
    assert ofs[0]["kwh"] == 5_000.0 and "2 quedas de rede (9,5 h)" in ofs[0]["texto"]
    assert rs.causa_sugerida(ofs) == ofs[0]["texto"]


def test_episodio_que_passa_do_periodo_conta_so_a_parte_de_dentro():
    trk = [{"tracker": "T1", "d0": "2026-09-14", "d1": "2026-09-27", "perda_kwh": 1_400.0, "dias": 14}]
    (o,) = rs.ofensores({}, trk, [], {"dias_validos": 7, "dias_sem_ipoa": 0, "dias_pr_alto": 0}, 0.0,
                        date(2026, 9, 21), date(2026, 9, 27))
    assert o["kwh"] == pytest.approx(700.0)                               # 7 dos 14 dias no período


def test_irradiancia_nao_confiavel_vem_antes_de_tudo():
    # sem IPOA em mais da metade dos dias o PR da semana não se sustenta — a causa é o sensor, não a usina
    ofs = rs.ofensores({"queda": {"n": 1, "h": 2.0}, "equip": {"n": 0, "h": 0.0}}, [], [],
                       {"dias_validos": 2, "dias_sem_ipoa": 5, "dias_pr_alto": 0}, 900.0,
                       date(2026, 9, 21), date(2026, 9, 27))
    assert rs.causa_sugerida(ofs).startswith("Irradiância não confiável")


def test_pr_acima_de_130_por_cento_num_dia_tambem_e_irradiancia_suspeita():
    ofs = rs.ofensores({}, [], [], {"dias_validos": 7, "dias_sem_ipoa": 0, "dias_pr_alto": 2}, 0.0,
                       date(2026, 9, 21), date(2026, 9, 27))
    assert ofs[0]["tipo"] == "ipoa"


def test_sem_ofensor_medido_pede_verificacao():
    assert rs.causa_sugerida([]) == "Sem ofensor medido — verificar sujidade, vegetação ou limitação"


# ── unidades: índice de disponibilidade (cadastro) × abas do BD_Thopen ──────────────────────────────────────────
import re as _re
import unicodedata as _ud

_ROM = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5"}


def _chave(nome):
    """Réplica pequena do app._usina_chave_solta (sem acento, romano como número, sem da/do/de)."""
    s = _ud.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode().lower()
    return "".join(_ROM.get(t, t) for t in _re.findall(r"[a-z]+|\d+", s) if t not in {"da", "do", "de", "e"})


GRUPOS = [{"nome": "Nova Londrina", "vivo": ["Nova Londrina 1", "Nova Londrina 2"], "ger": ["Nova Londrina"]},
          {"nome": "Ouro Branco", "vivo": ["Ouro Branco"], "ger": ["Ouro Branco I", "Ouro Branco II"]}]
IDX = [{"usina": "Altair", "fracttal": "Thopen - Altair 1 - SP", "pot_kwp": 6898.0},
       {"usina": "Nova Londrina 1", "fracttal": "Thopen - Nova Londrina 1 - PR", "pot_kwp": 1000.0},
       {"usina": "Nova Londrina 2", "fracttal": "Thopen - Nova Londrina 2 - PR", "pot_kwp": 3000.0},
       {"usina": "Ouro Branco", "fracttal": "Thopen - Ouro Branco - AL", "pot_kwp": 5000.0},
       {"usina": "Corrego do Sapucaia", "fracttal": "Thopen - Córrego - SP", "pot_kwp": 2000.0},
       {"usina": "Vargem Grande IB", "fracttal": "Thopen - Vargem - SP", "pot_kwp": 1000.0},
       {"usina": "Sem Aba", "fracttal": "Thopen - Sem Aba - SP", "pot_kwp": 1000.0}]
BD = {"Altair", "Nova Londrina", "Ouro Branco I", "Ouro Branco II", "Córrego do Sapucaia", "Vargem Grande 1"}


def test_unidades_juntam_partes_abrem_grupos_e_casam_grafia():
    us, avisos = rs.unidades(IDX, BD, _chave, GRUPOS, {"Vargem Grande IB": "Vargem Grande 1"})
    por = {u["nome"]: u for u in us}
    assert por["Nova Londrina"]["bd"] == ["Nova Londrina"]
    assert por["Nova Londrina"]["disp"] == ["Nova Londrina 1", "Nova Londrina 2"] and por["Nova Londrina"]["kwp"] == 4000
    assert por["Ouro Branco"]["bd"] == ["Ouro Branco I", "Ouro Branco II"]
    assert por["Corrego do Sapucaia"]["bd"] == ["Córrego do Sapucaia"]
    assert por["Vargem Grande IB"]["bd"] == ["Vargem Grande 1"]
    assert por["Sem Aba"]["bd"] == [] and any("Sem Aba" in a for a in avisos)
    assert por["Altair"]["sites"] == ["Thopen - Altair 1 - SP"]


# ── montagem: o payload inteiro, com os leitores trocados por stubs ─────────────────────────────────────────────
class L:
    """Leitores de mentira: 7 dias de sol igual, a Altair abaixo da meta, a Nova Londrina na meta."""
    hoje = date(2026, 9, 29)

    def diario(self, aba):
        ger = {"Altair": 18_000.0, "Nova Londrina": 16_000.0}.get(aba)
        if ger is None:
            return []
        return [dia(date(2026, 9, 21 + i), ger, 5.0) for i in range(7)] + [dia(date(2026, 8, 10), ger, 5.0)]

    def pot(self, aba):
        return {"Altair": 6.898, "Nova Londrina": 4.0}.get(aba)

    def metas(self, aba):
        return {8: {"meta": 1e6, "metairr": 150.0, "pr": 0.78}, 9: {"meta": 1e6, "metairr": 150.0, "pr": 0.78}} \
            if aba in ("Altair", "Nova Londrina") else {}

    def disp_diario(self, usina):
        return {"2026-09-23": {"h_eq": 3.0, "h_q": 3.0, "h_e": 0.0, "kwh": 12_000.0}} if usina == "Altair" else {}

    def oss(self):
        return [{"origem": "queda", "ini": "2026-09-23T09:00:00", "fim": "2026-09-23T12:00:00", "usinas": ["Altair"],
                 "aberta": False}]

    def linhas_os(self):
        return [linha(7, "Corretiva", 1, "2026-09-24T12:00:00+00:00")]

    def falhas(self):
        return {"strings": [], "trackers": []}


def test_montagem_devolve_os_cinco_blocos_e_a_usina_fora_da_meta_com_o_pre_diagnostico():
    us = [{"nome": "Altair", "bd": ["Altair"], "disp": ["Altair"], "sites": [SITE], "kwp": 6898.0},
          {"nome": "Nova Londrina", "bd": ["Nova Londrina"], "disp": ["Nova Londrina 1", "Nova Londrina 2"],
           "sites": [], "kwp": 4000.0}]
    p = rs.montar(date(2026, 9, 21), date(2026, 9, 27), us, L())
    assert set(p) >= {"periodo", "resumo", "evolucao", "executado", "disponibilidade", "fora_da_meta", "usinas", "avisos"}
    # Altair: 18 MWh ÷ (5 × 6,898) = 0,522 < 0,97 × 0,78; Nova Londrina: 16 ÷ 20 = 0,80 >= 0,7566
    (f,) = p["fora_da_meta"]
    assert f["nome"] == "Altair" and f["perda_mwh"] > 0
    assert f["causa_sugerida"].startswith("Desligamentos: 1 queda de rede (3,0 h)")
    # a energia do desligamento é a da usina naquele sol (18 MWh ÷ 12 h de sol × 3 h), não a potência nominal × horas —
    # nominal, 1,6 h de queda na Altair passava na frente de 56 trackers parados
    assert f["ofensores"][0]["kwh"] == pytest.approx(3.0 * 18_000 / 12)
    assert p["resumo"]["fora"] == 1 and p["resumo"]["total"] == 2
    assert p["executado"]["corretivas"] == {"concluidas": 0, "total": 1}
    assert p["disponibilidade"]["queda"] == {"n": 1, "h": pytest.approx(3.0)}
    assert [m["mes"] for m in p["evolucao"]["meses"]] == list(range(1, 10))


def test_usina_sem_nenhum_dia_com_ipoa_vira_aviso():
    class SemIpoa(L):
        def diario(self, aba):
            return [dia(date(2026, 9, 21 + i), 10_000.0, 0.0) for i in range(7)]
    us = [{"nome": "Guatambu", "bd": ["Altair"], "disp": ["Guatambu"], "sites": [], "kwp": 1000.0}]
    p = rs.montar(date(2026, 9, 21), date(2026, 9, 27), us, SemIpoa())
    assert p["resumo"]["total"] == 0 and any("Guatambu" in a and "IPOA" in a for a in p["avisos"])
