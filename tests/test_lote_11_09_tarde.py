# -*- coding: utf-8 -*-
"""Lote da tarde de 11/09/2026 (Levi):
  2. inversor DESLIGADO com OS aberta no Fracttal no seu ativo não entra nas strings esperadas ("se está desligado e tem
     OS então está tudo OK") — a OS vem do índice de disponibilidade que o worker já monta (escopo por nível);
  4. Raio-X (painel_portfolio): coluna "% da meta (mês)" e a "razão" de energia ordenadas do MENOR para o maior;
  5. Diagnóstico v2, drill-down do dia: a cor da legenda (tooltip) de cada string é a cor da linha;
  1. MTS100: o drill-down do dia pedia a curva ao SunOp pelo NOME quando IC_INVID ainda não existia (só nasce na aba
     Curvas) → usina inteira, lento, estourava. O id da API vem do PLANT."""
import pathlib

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]


def test_os_aberta_no_fracttal_por_inversor_vem_do_indice(monkeypatch):
    idx = {"meses": {"2026-09": {"oss": [
        {"folio": 1, "aberta": True, "escopo": [{"usina": "Colorado 2", "nivel": "inversor", "rotulo": "Inversor 1.3"}]},
        {"folio": 2, "aberta": False, "escopo": [{"usina": "Colorado 2", "nivel": "inversor", "rotulo": "Inversor 1.4"}]},   # fechada não conta
        {"folio": 3, "aberta": True, "escopo": [{"usina": "Colorado 2", "nivel": "usina", "rotulo": "Usina inteira"}]},     # nível usina não é do inversor
        {"folio": 4, "aberta": True, "escopo": [{"usina": "Tupi Paulista", "nivel": "inversor", "rotulo": "Inversor 2.5"}]},
    ]}}}
    monkeypatch.setattr(app, "_frac_disp_dados", lambda: idx)
    monkeypatch.setattr(app, "_os_frac_inv_cache", {"ts": 0.0, "map": {}})
    m = app._os_fracttal_inv_abertas()
    assert m == {app._nrm("Colorado 2"): {app._nrm("Inversor 1.3")}, app._nrm("Tupi Paulista"): {app._nrm("Inversor 2.5")}}


def test_so_o_inversor_desligado_com_os_sai_das_esperadas():
    """ids da API → nome da API → nome de exibição do cadastro; só quem está DESLIGADO e tem OS aberta."""
    api_nome = {11: "INVERSOR03", 12: "INVERSOR04", 13: "INVERSOR05"}
    disp = {"INVERSOR03": "Inversor 1.3", "INVERSOR04": "Inversor 1.4", "INVERSOR05": "Inversor 1.5"}
    rotulos = {app._nrm("Inversor 1.3"), app._nrm("Inversor 1.5")}
    assert app._ids_com_os_fracttal({11, 12}, api_nome, disp, rotulos) == {11}       # 12 não tem OS; 13 tem OS mas está ligado
    assert app._ids_com_os_fracttal(set(), api_nome, disp, rotulos) == set()
    assert app._ids_com_os_fracttal({13}, {}, {}, {app._nrm("13")}) == {13}          # sem nome: casa pelo próprio id


def test_raio_x_ordena_meta_e_razao_do_menor_para_o_maior():
    por = (RAIZ / "plataforma/templates/painel_portfolio.html").read_text(encoding="utf-8")
    assert "((rzG(a)??9e9)-(rzG(b)??9e9))" in por and "((rzE(a)??9e9)-(rzE(b)??9e9))" in por
    assert "((a.razao??9e9)-(b.razao??9e9))" in por
    assert "(rzG(b)??-1)-(rzG(a)??-1)" not in por and "(rzE(b)??-1)-(rzE(a)??-1)" not in por


def test_v2_legenda_da_string_com_a_cor_da_linha_e_id_da_api_pelo_plant():
    v2 = (RAIZ / "plataforma/templates/painel_usina_v2.html").read_text(encoding="utf-8")
    assert "function _hdCor(" in v2 and v2.count("_hdCor(") >= 4                   # strings, inversor, correlação
    assert "function _hdApiId(" in v2 and "_hdApiId(k)" in v2


def test_raio_x_sem_botao_e_sem_visao_meta():
    """Levi, 11/09 (tarde): "remova o botão e visão meta" do card lateral — fica só a energia do dia."""
    por = (RAIZ / "plataforma/templates/painel_portfolio.html").read_text(encoding="utf-8")
    assert "onclick=\"rxInvModo('meta')\"" not in por and "rxInvModo('energia')" not in por
    assert "const modoMeta=false" in por
