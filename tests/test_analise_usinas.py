# -*- coding: utf-8 -*-
"""Análise das usinas (25/11/2026, docs/analise-das-usinas.md): as regras puras da visão inicial, sem Flask nem rede.
Usinas de mentira; os números do caso real (Santarém 2, novembro) vêm comentados onde servem de régua."""
import pytest

import analise_usinas as A


# ── o semáforo: ≥ 95% do esperado verde, 85 a 95 amarelo, abaixo vermelho; disponibilidade 98 / 95 ────────────────────
@pytest.mark.parametrize("r, esperado", [(1.02, "ok"), (.95, "ok"), (.949, "alerta"), (.85, "alerta"), (.849, "critico"),
                                         (None, "neutro")])
def test_o_sinal_de_uma_razao(r, esperado):
    assert A.sinal(r) == esperado


@pytest.mark.parametrize("v, esperado", [(100, "ok"), (98, "ok"), (97.9, "alerta"), (95, "alerta"), (94.9, "critico"),
                                         (None, "neutro")])
def test_o_sinal_da_disponibilidade(v, esperado):
    assert A.sinal_disp(v) == esperado


def test_a_cor_da_usina_e_o_pior_dos_tres_sinais_e_sem_dado_e_neutro():
    assert A.sinal_usina({"at": 98, "pr": 70, "meta": 83.3, "disp": 99}) == "critico"     # o PR (84% da meta) manda
    assert A.sinal_usina({"at": 92, "pr": 80, "meta": 80, "disp": 99}) == "alerta"
    assert A.sinal_usina({"at": 101, "pr": 80, "meta": 80, "disp": None}) == "ok"         # sem disponibilidade não pesa
    assert A.sinal_usina({"at": None, "pr": None, "meta": None, "disp": None}) == "neutro"


# ── o agregado de um grupo pela conta do Gerencial ───────────────────────────────────────────────────────────────────
def test_o_pr_do_grupo_e_geracao_sobre_poa_vezes_potencia_e_nao_a_media_das_usinas():
    us = [{"prod": 100, "p50": 100, "prod_pr": 70, "ipoa": 100, "mwp": 1, "meta": 80, "disp": 99},
          # a usina de sensor ruim (PR 900%, como a Alto Paraná 2 em 24/11) puxava a média simples para 83%
          {"prod": 10, "p50": 20, "prod_pr": 9, "ipoa": 1, "mwp": 1, "meta": 80, "disp": 97}]
    a = A.agrega(us)
    assert a["at"] == pytest.approx(110 / 120)
    assert a["pr"] == pytest.approx((70 + 9) / (100 * 1 + 1 * 1) * 100)
    assert a["meta"] == pytest.approx(80)
    assert a["disp"] == pytest.approx(98)
    assert A.agrega([]) == {"at": None, "pr": None, "meta": None, "disp": None}


# ── a disponibilidade do mês pela régua do COS: o índice só guarda os dias com perda ──────────────────────────────────
def test_a_disponibilidade_do_mes_conta_os_dias_sem_perda_como_cem():
    diario = {"2026-11-03": {"disp": 81.2, "h_eq": 1.882}, "2026-11-09": {"disp": 89.0, "h_eq": 1.104}}
    disp, h = A.disp_mes(diario, ("2026-11-01", "2026-11-04"))
    assert disp == pytest.approx((81.2 + 100 * 3) / 4) and h == pytest.approx(1.882)        # o dia 9 está fora do período
    assert A.disp_mes(None, ("2026-11-01", "2026-11-04")) == (None, None)


def test_as_ocorrencias_do_mes_contam_a_os_uma_vez_em_cada_usina_dela():
    oss = [{"folio": "16958", "usinas": ["Santarém 2"]}, {"folio": "19865", "usinas": ["Santarém 2"]},
           {"folio": "19865", "usinas": ["Santarém 2"]}, {"folio": "15335", "usinas": ["Ipixuna 1", "Ipixuna 2"]}]
    assert A.ocorrencias(oss, "Santarém 2") == 2 and A.ocorrencias(oss, "santarem 2") == 2
    assert A.ocorrencias(oss, "Ipixuna 2") == 1 and A.ocorrencias(oss, "Outra") == 0


# ── a visão inicial ──────────────────────────────────────────────────────────────────────────────────────────────────
GER = {"cache_ts": "16:47:32", "mes": "11/2026",
       "usinas": [{"usina": "Santarém 2", "cliente": "Thopen", "atingimento": 96.6, "pr": 69.8, "pr_meta": 83.3, "prod": 349.4,
                   "prod_pr": 349.4, "ipoa": 153.7, "p50": 361.7, "pot_mwp": 3.256, "dias_cob": 20, "pr_motivo": None},
                  {"usina": "Lajedo 1", "cliente": "Axis", "atingimento": None, "pr": None, "pr_meta": 80, "prod": None,
                   "p50": 50, "pot_mwp": 1.0, "dias_cob": 0, "pr_motivo": "sem POA"}]}
DISP = {"periodo": ["2026-11-01", "2026-11-02"], "usinas": [{"usina": "Santarém 2"}],
        "diario": {"Santarém 2": {"2026-11-01": {"disp": 89.7, "h_eq": 1.029}, "2026-11-02": {"disp": 89.7, "h_eq": 1.029}}},
        "oss": [{"folio": "16958", "usinas": ["Santarém 2"]}]}


def test_a_visao_junta_o_gerencial_a_regua_do_cos_a_mobilizacao_e_as_ocultas():
    v = A.visao(GER, DISP, ocultas={"Lajedo 1": {"quem": "Ana", "ts": "2026-11-25 10:00"}}, mobil={"santarem 2": "2025-10-20"})
    st, lj = v["usinas"]
    assert st["u"] == "Santarém 2" and st["c"] == "Thopen" and st["at"] == 96.6 and st["pr"] == 69.8 and st["meta"] == 83.3
    assert st["disp"] == pytest.approx(89.7) and st["h_perdidas"] == pytest.approx(2.058) and st["nos"] == 1
    assert st["mob"] == "2025-10-20" and st["oculta"] is None and st["sinal"] == "critico"
    # a usina que a régua do COS não tem fica SEM disponibilidade (não 100%) e sem contagem de ocorrências
    assert lj["disp"] is None and lj["nos"] is None and lj["oculta"] == {"quem": "Ana", "ts": "2026-11-25 10:00"}
    assert lj["sinal"] == "neutro" and lj["motivo"] == "sem POA"
    assert v["lido"] == "16:47:32" and v["periodo_disp"] == ["2026-11-01", "2026-11-02"]


def test_a_visao_sem_a_regua_do_cos_segue_com_o_gerencial():
    v = A.visao(GER, None, ocultas={}, mobil={})
    assert [u["disp"] for u in v["usinas"]] == [None, None] and v["periodo_disp"] is None


@pytest.mark.parametrize("mes, ok", [("2026-11", True), ("2026-1", False), ("2026-13", False), ("abc", False), ("", False)])
def test_o_mes_pedido_tem_de_estar_no_formato(mes, ok):
    assert (A.mes_valido(mes) is not None) == ok
