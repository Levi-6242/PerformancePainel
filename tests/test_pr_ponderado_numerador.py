# -*- coding: utf-8 -*-
"""O card "PR ponderado (mês)" tem de dividir os MESMOS dias em cima e embaixo (varredura de 09/09/2026).

Achado: o rollup do /gerencial fazia `Σ prod ÷ Σ(ipoa × pot)`. `prod` é a geração do MÊS INTEIRO — todo
dia que a fonte reportou — enquanto `ipoa` só acumula o dia que passou na régua da fonte:

  BD_Thopen        (`_thopen_prod_build`)  soma IPOA só com ipoa > 0,3
  BD_Performance   (`_bdperf_prod_build`)  exige dia FECHADO (< hoje) + Validação > 0 + DEF/ETM utilizável
  PG               (`_gerencial_payload`)  só soma o dia que veio com POA na linha

Resultado: dias de geração a mais sobre dias de sol a menos — o card ficava acima das próprias linhas da
tabela (que sempre usaram o par certo) e podia passar de 100%. Os dois numeradores JÁ existiam dentro dos
builders (`gsum`, `gen_pr`); eram calculados, usados na linha da usina e jogados fora na hora de exportar.
"""
import app


def test_o_numerador_do_pr_e_o_que_casa_com_a_ipoa():
    assert app._ger_prod_pr({"prod": 100.0, "prod_pr": 80.0}) == 80.0


def test_sem_o_par_separado_cai_no_prod_e_nao_piora_nada():
    """Fonte que ainda não separa os dois continua com o número de antes — nunca com None."""
    assert app._ger_prod_pr({"prod": 100.0}) == 100.0
    assert app._ger_prod_pr({"prod": 100.0, "prod_pr": None}) == 100.0
    assert app._ger_prod_pr({"prod": 0.0, "prod_pr": 0.0}) == 0.0


def test_zero_e_zero_nao_e_ausencia():
    """Usina parada o mês inteiro tem numerador 0, e 0 não pode virar 'use o prod'."""
    assert app._ger_prod_pr({"prod": 500.0, "prod_pr": 0.0}) == 0.0


def test_thopen_exporta_a_geracao_dos_dias_que_entraram_na_ipoa(monkeypatch):
    """Dia sem IPOA entra no atingimento (prod_mwh) e NÃO entra no PR (prod_pr_mwh)."""
    import dashboard_thopen as dth
    from datetime import datetime as _dt
    hoje = _dt.now()
    d1 = hoje.replace(day=1)
    monkeypatch.setattr(dth, "_registro", lambda: {"Usina W": {"cliente": "Thopen", "pot_mwp": 1.0}})
    monkeypatch.setattr(dth, "_CARTEIRA_DE", {"Usina W": "Thopen"})
    monkeypatch.setattr(dth, "_daily_records", lambda u: [
        {"data": d1, "ger": 1000.0, "ipoa": 5.0},      # dia com sol medido: entra nos dois
        {"data": hoje, "ger": 900.0, "ipoa": None},    # sensor sem leitura: só no atingimento
    ])
    monkeypatch.setattr(app, "_thopen_prod_cache", {"ts": 0.0, "ym": None, "data": {}, "warming": True})
    out = app._thopen_prod_build()
    r = out[app._nrm("Usina W")]
    assert round(r["prod_mwh"], 3) == 1.9, "o atingimento continua contando o mês inteiro"
    assert round(r["prod_pr_mwh"], 3) == 1.0, "o PR não pode contar geração de dia sem POA"


def test_o_rollup_usa_o_numerador_certo():
    """`_roll` é fechada dentro do payload — esta é a garantia de que ela não voltou ao `prod`."""
    import inspect
    src = inspect.getsource(app._gerencial_payload)
    assert "spPR = sum(_ger_prod_pr(u) or 0 for u in comPR)" in src, \
        "o rollup do PR voltou a somar a geração do mês inteiro"
    assert 'spPR = sum(u["prod"] for u in comPR)' not in src


def test_as_tres_fontes_exportam_o_par():
    """Se uma fonte parar de exportar `prod_pr`, ela volta silenciosamente ao número inflado."""
    import inspect
    assert '"prod_pr_mwh": gsum / 1000.0' in inspect.getsource(app._thopen_prod_build)
    assert '"prod_pr_mwh": gen_pr / 1000.0' in inspect.getsource(app._bdperf_prod_build)
    src = inspect.getsource(app._gerencial_payload)
    assert 'd["prod_pr_kwh"] += ger' in src and '"prod_pr": round(d["prod_pr_kwh"] / 1000.0, 1)' in src
