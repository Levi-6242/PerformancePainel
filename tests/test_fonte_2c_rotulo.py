# -*- coding: utf-8 -*-
"""A fonte `owen` É o 2C — não a RenoGrid (varredura de 09/09/2026, confirmado por 3 céticos).

O backend sabe disso em todo lugar que importa: `_TRK_FONTE_LABEL["owen"] = "2C"`, o rollup do macro faz
`for r in _owen_strings_rows(): add("2C", r)`, `_ENTRADA_VKEY["2c"] = "owen"`, `_INV_HIST_FONTE["2c"] =
"owen"`, e as usinas do `OWEN_UFVS` (Araputanga, Ipixuna do Pará, Sete Lagoas 2, Tupi Paulista) são as
do 2C. Três lugares destoavam:

  1. o registro de trackers da Entrada lia o 2C sob a chave "RenoGrid" — então o card do 2C nunca era
     marcado como lido ("fonte não respondeu" para sempre) e o card da RenoGrid dizia ter uma fonte de
     trackers que ela não tem;
  2. o rótulo do sino dizia "RenoGrid" numa queda de string do 2C;
  3. o deep link do sino mandava para /tempo-real/renogrid — a aba do SolarEdge, onde a usina não existe.
"""
import pathlib

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]


def test_os_trackers_do_2c_marcam_o_card_do_2c(monkeypatch):
    monkeypatch.setattr(app, "_macro_cache", {"ts": 0.0, "warming": False, "data": {"usinas": [
        {"usina": "Araputanga", "plant_id": "ARA", "status": "ok", "strings_faltando": 0,
         "cliente": "2C", "fonte": "2C", "ultima_leitura": "2026-09-09 12:00"}]}})
    monkeypatch.setattr(app, "_etm_prob_cache", {"ts": 0.0, "data": {"itens": [], "mes": "09/2026"}})
    monkeypatch.setattr(app, "_trk_geo_annotate", lambda rows: rows)
    monkeypatch.setattr(app, "_ENTRADA_TRK_PRAZO_S", 3)
    monkeypatch.setattr(app, "_sunop_parados_rows", lambda *a, **k: [])
    monkeypatch.setattr(app, "_pv_parados_rows", lambda *a, **k: [])
    monkeypatch.setattr(app, "_pg_parados_rows", lambda *a, **k: [])
    monkeypatch.setattr(app, "_owen_parados_rows", lambda *a, **k: [{"usina": "Araputanga", "cliente": "2C"}])
    d = app._entrada_tempo_real_build()
    por = {g["fonte"]: g for g in d["grupos"]}
    assert por["2C"]["trk_parados"] == 1
    assert por["2C"]["trk_fonte_ok"] is True, "o card do 2C continua dizendo que a fonte não respondeu"
    assert por["RenoGrid"]["trk_fonte_ok"] is False, "a RenoGrid não tem fonte de trackers — não pode se dizer lida"
    assert "RenoGrid" not in (d.get("fontes_pendentes") or []), "a pendência do 2C aparecia como da RenoGrid"


def test_o_sino_rotula_e_linka_o_2c_como_2c():
    assert ("owen", "2C") in app._NOTIF_FONTES, "o sino voltou a chamar o 2C de RenoGrid"
    js = (RAIZ / "plataforma" / "static" / "notif.js").read_text(encoding="utf-8")
    assert 'owen: "2c"' in js, "o deep link do sino manda o 2C para a aba do SolarEdge"
    assert 'owen: "renogrid"' not in js


def test_o_de_para_do_backend_segue_dizendo_que_owen_e_2c():
    """Se algum dia `owen` virar mesmo a RenoGrid, estes três de-para mudam junto — e o teste avisa."""
    assert app._TRK_FONTE_LABEL.get("owen") == "2C"
    assert app._ENTRADA_VKEY.get("2c") == "owen"
    assert set(app.OWEN_UFVS.values()) >= {"Araputanga", "Tupi Paulista"}


# ── A curva do tracker tem de seguir o dia escolhido no cabeçalho ──────────────────────────────────
def test_a_curva_do_tracker_usa_o_dia_do_cabecalho():
    """Achado da mesma frente: `CFG.chart` é string FIXA e as duas funções de curva a usavam crua — o
    seletor de data prometia "vale para trackers" e o gráfico vinha sempre de hoje, calado. As quatro
    rotas de chart já aceitavam `?date=` (`_trk_chart_range`); faltava o front mandar."""
    src = (RAIZ / "plataforma" / "templates" / "painel_usina_v2.html").read_text(encoding="utf-8")
    assert "function _chartURL()" in src, "sumiu o montador da URL da curva com o dia"
    assert "'date='+encodeURIComponent(d)" in src
    assert src.count("await fetch(_chartURL())") == 2, "alguma curva voltou a buscar sem o dia"
    assert "await fetch(CFG.chart)" not in src
