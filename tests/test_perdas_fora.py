# -*- coding: utf-8 -*-
"""A aba Perdas do Monitoramento saiu (12/10/2026).

Levi: "tira a aba Perdas do menu também — destrói essa porcaria"; a tela de verdade é a Falhas do Diagnóstico
("Falhas de strings e trackers, com a perda em kWh"). Ela já não era aberta — e o worker gastava a cada boot memória e
chamadas à API PV aquecendo um cache dela que o web nem lia (ver tests/test_worker_memoria_teto.py).

Saíram a vista e o menu, as rotas que só ela usava e o que só essas rotas alcançavam. FICAM, porque outras telas leem:
a rota do histórico de paradas (painéis de usina e de portfólio), o status do fechamento das 01:30 e os stores que a
Falhas lê (perdas_strings.json, trk_eventos.json, paradas_book.json).
"""
import pathlib

import app

MON = (pathlib.Path(app.__file__).resolve().parents[1] / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")
TPL = pathlib.Path(app.__file__).resolve().parent / "templates"


def test_a_aba_saiu_do_menu_e_da_tela():
    assert "{id:'perdas',label:'Perdas'}" not in MON
    assert "'perdas'" not in MON, "a vista 'perdas' ainda é aceita na URL (?view=perdas) ou no menu"
    for peca in ("renderPerdas", "loadPerda", "setPerdaSub", "_PERDA_EP", "RD.perdas", "showPerdas", "/api/perdas"):
        assert peca not in MON, f"{peca!r} ficou na tela"


def test_os_helpers_que_outras_vistas_usam_ficaram():
    """O bloco da Perdas tinha no meio helpers que Trackers e Strings usam (data, faixa de status, barra de duração)."""
    for f in ("function _dtBR(", "function _isHoje(", "function _stTd(", "function _sevColor(", "function _durBar(",
              "function _durCell(", "function _tnum("):
        assert f in MON, f"{f} saiu junto — outra vista usa"


def test_as_rotas_da_aba_sairam_e_as_que_outras_telas_leem_ficaram():
    regras = {str(r) for r in app.app.url_map.iter_rules()}
    for rota in ("/api/perdas/<fonte>/trackers/ocorrencias", "/api/perdas/<fonte>/trackers/ocorrencias/export",
                 "/api/perdas/<fonte>/trackers/parados", "/api/perdas/<fonte>/trackers/parados/export",
                 "/api/perdas/<fonte>/strings/ocorrencias", "/api/perdas/<fonte>/strings/ocorrencias/export",
                 "/api/perdas/<fonte>/strings/zeradas", "/api/perdas/<fonte>/strings/zeradas/export",
                 "/api/perdas/<fonte>/qualidade"):
        assert rota not in regras, f"{rota} ainda existe"
    assert "/api/perdas/<fonte>/trackers/paradas-hist" in regras, "o histórico de paradas é dos painéis de usina e portfólio"
    assert "/api/perdas/fechamento" in regras, "o status do fechamento das 01:30 não é da aba"
    painel = (TPL / "painel_usina_v2.html").read_text(encoding="utf-8")
    assert "/trackers/paradas-hist" in painel, "o painel de usina deixou de ler o histórico (então a rota pode sair)"


def test_o_que_so_a_aba_usava_saiu_e_o_que_a_falhas_le_ficou():
    for f in ("_perdas_trk_ocor_cached", "_perdas_trk_ocor_build", "_trk_ocor_classes_list", "_PERDAS_OCOR_CACHE",
              "_PERDAS_QUAL_CACHE", "_perdas_qualidade_pg", "_str_ev_rows_range", "_perdas_xlsx"):
        assert not hasattr(app, f), f"{f} ficou sem ninguém que o chame"
    for f in ("_perdas_str_backfill", "_perdas_str_load", "_trk_ev_backfill", "_paradas_book_refresh",
              "_trk_paradas_hist", "_fecha_dia_anterior", "_trk_ocor_curva_list"):
        assert callable(getattr(app, f, None)), f"{f} saiu — a Falhas, o book ou a régua dependem dele"


def test_o_menu_ainda_tem_as_outras_vistas():
    for v in ("{id:'strings',label:'Strings'}", "{id:'etm',label:'ETM'}", "{id:'trackers',label:'Trackers'}",
              "{id:'curva',label:'Curva das strings'}"):
        assert v in MON
