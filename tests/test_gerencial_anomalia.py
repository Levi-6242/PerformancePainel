# -*- coding: utf-8 -*-
"""Número anômalo no Gerencial: SÓ SINALIZA, o número fica (Levi, 18/10/2026: "quero que apenas sinalize que o número
está anômalo e o dado pode estar errado, temos que sinalizar pela plataforma e não ficar travando a construção!").

A régua que ele escolheu: a meta do mês fora de 2 a 8 kWh por kWp por dia. Caso que criou: outubro/2026, Santo
Anastácio (meta de 1,28 kWh/kWp/dia, atingimento 217,7%) e Álvares Machado (0,90; 331,1%) — a meta da aba "Dados
Mensais 2026" do BD_Thopen baixa."""
import app


def _u(meta_dia_kwh, pot_mwp=3.531, **k):
    return {"usina": "Alvares Machado", "pot_mwp": pot_mwp, "meta_dia_kwh": meta_dia_kwh, **k}


def test_meta_baixa_sinaliza_com_o_codigo_e_a_frase():
    # Álvares Machado, outubro: 53,9 MWh em 17 dias = 3.170 kWh/dia em 3.531 kWp = 0,90 kWh/kWp/dia
    assert app._ger_anomalia(_u(3170.6)) == [("meta_baixa", "meta do mês de 0,9 kWh por kWp por dia (o normal é de 2 a "
                                                            "8): o dado da meta pode estar errado")]


def test_meta_normal_e_os_limites_nao_sinalizam():
    assert app._ger_anomalia(_u(4.6 * 3531)) == []                      # o portfólio fica de 4 a 6
    assert app._ger_anomalia(_u(2.0 * 3531)) == [] and app._ger_anomalia(_u(8.0 * 3531)) == []
    assert [c for c, _f in app._ger_anomalia(_u(8.5 * 3531))] == ["meta_alta"]


def test_sem_potencia_ou_sem_meta_nao_julga_e_sem_meta_do_dia_usa_a_prorrateada():
    assert app._ger_anomalia(_u(3170.6, pot_mwp=None)) == []
    assert app._ger_anomalia({"usina": "X", "pot_mwp": 3.573}) == []
    # sem meta_dia_kwh: a meta prorrateada ÷ os dias da meta (Santo Anastácio: 73,4 MWh em 16 dias → 1,28)
    ((c, f),) = app._ger_anomalia({"usina": "Santo Anastacio", "pot_mwp": 3.573, "p50": 73.4, "meta_dias": 16})
    assert c == "meta_baixa" and "1,3 kWh por kWp" in f


def test_o_dia_estourado_vira_o_codigo_geracao_impossivel():
    # a Ibirapuã II com o 13/10 fora da conta (o filtro dela): sinaliza também, com a meta normal
    an = app._ger_anomalia({"usina": "Ibirapuã II", "pot_mwp": 3.396, "meta_dia_kwh": 4.4 * 3396,
                            "dias_sem_leitura": [{"dia": 13, "ger_kwh": 10620890.0, "kwh_kwp": 3127.5}]})
    assert [c for c, _f in an] == ["geracao_impossivel"] and "no dia 13" in an[0][1]


def test_so_os_codigos_do_dominio_do_nexus():
    # dominios.ANOMALIA_META do catálogo do Nexus (2b489cb) = meta_baixa, meta_alta, geracao_impossivel
    codigos = {c for meta in (0.5, 1.9, 8.1, 20) for c, _f in app._ger_anomalia(_u(meta * 3531))}
    codigos |= {c for c, _f in app._ger_anomalia(_u(4.6 * 3531, dias_sem_leitura=[{"dia": 13}]))}
    assert codigos == {"meta_baixa", "meta_alta", "geracao_impossivel"}


def test_o_gerencial_poe_a_anomalia_em_toda_usina_e_a_tela_mostra():
    import inspect
    src = inspect.getsource(app._gerencial_payload)
    assert 'u["anomalia"] = ",".join(c for c, _f in _an) or None' in src and 'u["anomalia_txt"]' in src
    html = open(app.os.path.join(app._AQUI, "templates", "gerencial.html"), encoding="utf-8").read()
    assert "u.anomalia" in html and "dado anômalo</span>" in html
