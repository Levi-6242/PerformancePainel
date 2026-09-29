# -*- coding: utf-8 -*-
"""Frota de trackers da cascata e do Criador de Relatório (29/09/2026).

`_trk_frota_total` é o denominador da perda de tracker: fração = horas paradas ÷ (12 h × dias × frota)
e perda = possível × fração × ganho do rastreio. Desde que nasceu, em 25/07/2026 (commit f476ae1), ela
apontava a API PV para `_pv_trackers_overview`, nome que nunca existiu — o NameError morria no `except`
e a função devolvia 0 — e só conhecia "pv" e "pg": SunOp, Axis e a 2C do e-mail também davam 0. Os dois
chamadores (`_cascata_usina` e `_relatorio_build`) caíam então no `n_frota` de reserva, que é o nº de
trackers que PARARAM no período, não a frota. No relatório de setembro da MAB100 (Athon), 13 trackers
parados numa frota de 150 dividiam como se a frota fosse 13: perda de tracker 11,5× maior.

O que estes testes seguram:
  1. a frota vem do overview que a própria fonte publica (o `total` da tabela de Trackers);
  2. usina que a fonte não lista hoje cai no cadastro (aba BD_Trackers);
  3. a frota nunca é menor que os trackers que pararam naquela usina;
  4. nada disso reconstrói overview no caminho da requisição.
"""
import time

import pytest

import app

FONTES = ("pv", "pg", "sunop", "axis", "owen")


def _linha_overview(usina, total, plant_id=None):
    """Linha do overview de trackers como o worker publica (o `total` é a coluna da tabela)."""
    return {"plant_id": plant_id or usina, "usina": usina, "total": total, "severos": 0, "medios": 0,
            "leves": 0, "parados": 0, "sem_comunicacao": False, "disponibilidade_tempo": None}


def _paradas(usina, trackers, ini="2026-09-10", dias=3):
    """Uma parada FECHADA por tracker, de `dias` dias inteiros (12 h solares por dia), no formato do book."""
    fim = f"2026-09-{int(ini[8:]) + dias - 1:02d}"
    volta = f"2026-09-{int(ini[8:]) + dias:02d}"
    return [{"usina": usina, "tracker": t, "inicio": ini, "fim": fim, "parado_desde": f"{ini} 06:00",
             "voltou_em": f"{volta} 06:00", "dias": dias, "aberta": False,
             "horas_solares": 12.0 * dias, "horas_solares_fmt": f"{12 * dias}h"} for t in trackers]


@pytest.fixture
def overview(monkeypatch):
    """Publica linhas no overview de uma fonte, como o snapshot do worker deixa no processo web.
    Começa com todos VAZIOS e o cadastro vazio: nada vaza do estado da máquina que roda o teste."""
    caches = {"pv": app._pv_trk_cache, "pg": app._pg_trk_cache,
              "sunop": app._sunop_trk_cache, "axis": app._axis_trk_cache}
    for c in caches.values():
        monkeypatch.setitem(c, "payload", None)
        monkeypatch.setitem(c, "ts", 0.0)
    monkeypatch.setattr(app, "BD_TRK_INV", {})
    monkeypatch.setattr(app, "_owen_accum", {"date": None, "etm": {}, "strings": {}, "trackers": {}})

    def _publica(fonte, linhas):
        monkeypatch.setitem(caches[fonte], "payload", {"rows": linhas, "summary": {}, "cache_ts": "08:27:13"})
        monkeypatch.setitem(caches[fonte], "ts", time.time())
    return _publica


# ── 1. a frota de cada fonte ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("fonte,usina,total", [
    ("pv", "Vertentes", 53),
    ("sunop", "MAB100", 150),
    ("axis", "PEII", 40),
])
def test_frota_vem_do_overview_que_a_fonte_publica(overview, fonte, usina, total):
    overview(fonte, [_linha_overview(usina, total), _linha_overview("Outra Usina", 999)])
    assert app._trk_frota_total(fonte, usina) == total


def test_frota_da_2c_vem_do_acervo_do_dia(overview, monkeypatch):
    """A 2C do e-mail não publica overview (a aba monta na hora): a frota é o que o acervo do dia tem. A
    Ipixuna do Pará não está na aba BD_Trackers — sem o acervo, só sobraria o nº de parados."""
    trk = lambda n: {str(i): {"alvo": [], "atual": []} for i in range(1, n + 1)}
    monkeypatch.setattr(app, "_owen_accum", {"date": "2026-09-28", "etm": {}, "strings": {},
                                             "trackers": {"IPX": trk(122), "TUP": trk(100)}})
    assert app._trk_frota_total("owen", app._owen_nome("IPX")) == 122


def test_frota_do_banco_casa_o_nome_com_o_id_na_frente(overview):
    """O overview do Banco escreve "(307) Ibaté 2"; a cascata pergunta por "Ibaté 2". Era o único ramo que
    funcionava — e continua."""
    overview("pg", [_linha_overview("(307) Ibaté 2", 50, "2"), _linha_overview("(306) Ibaté 1", 48, "1")])
    assert app._trk_frota_total("pg", "Ibaté 2") == 50


def test_id_na_frente_nao_entra_na_comparacao_do_nome(overview):
    """"Boa Esperança do Sul 1 e 2" (o nome do cadastro) casa com as paradas de "Boa Esperança do Sul 1";
    com o "(305) " na frente, o nome do overview do Banco não casava, e a frota caía nos parados."""
    overview("pg", [_linha_overview("(305) Boa Esperança do Sul 1", 49, "5")])
    assert app._trk_frota_total("pg", "Boa Esperança do Sul 1 e 2") == 49


# ── 2. e 3. cadastro de reserva e o piso ──────────────────────────────────────────────────────────────
def test_usina_que_a_fonte_nao_lista_cai_no_cadastro(overview, monkeypatch):
    """Colorado 2 não estava no overview da API PV em 29/09 (não listou tracker hoje): a frota vem da aba
    BD_Trackers. Sem o cadastro, os 3 trackers que pararam em setembro virariam a frota inteira."""
    overview("pv", [_linha_overview("Vertentes", 53)])
    monkeypatch.setattr(app, "BD_TRK_INV", {"colorado2": {n: "Inversor 1.1" for n in range(1, 23)}})
    sel = _paradas("Colorado 2", ["TRK3", "TRK7", "TRK15"])
    assert app._trk_frota_total("pv", "Colorado 2", sel) == 22


@pytest.mark.parametrize("pelo", ["overview", "cadastro"])
def test_frota_nunca_e_menor_que_os_trackers_que_pararam(overview, monkeypatch, pelo):
    """29/09: o overview da Guatambu 3 dizia 18 e o cadastro da Vertentes, 26 — e pararam 19 e 44 trackers
    diferentes em setembro. Fonte que conta menos do que parou está incompleta; dividir por ela infla."""
    if pelo == "overview":
        overview("pv", [_linha_overview("Guatambu 3 (130)", 18)])
        usina, n = "Guatambu 3 (130)", 19
    else:
        overview("pv", [])
        monkeypatch.setattr(app, "BD_TRK_INV", {"vertentes": {i: "Inversor 1.1" for i in range(1, 27)}})
        usina, n = "Vertentes", 44
    sel = _paradas(usina, [f"TRK{i}" for i in range(1, n + 1)])
    assert app._trk_frota_total("pv", usina, sel) == n


# ── 4. o caminho da requisição ────────────────────────────────────────────────────────────────────────
def test_overview_vazio_nao_e_reconstruido_no_caminho_da_requisicao(overview, monkeypatch):
    """A cascata e o relatório rodam no processo WEB, e `_swr` com cache VAZIO constrói na hora: o overview
    da API PV é a varredura de até 15 min, o da Axis nem entra no snapshot (no web está sempre vazio) e
    custa requisição da SunOp. A frota só lê o que o worker publicou."""
    chamou = []
    for nome in ("_build_pv_trk_payload", "_pg_trackers_overview", "_build_sunop_trk_payload"):
        monkeypatch.setattr(app, nome, lambda *a, _n=nome, **k: chamou.append(_n) or {"rows": []})
    for fonte in FONTES:
        app._trk_frota_total(fonte, "Qualquer")
    assert chamou == []


# ── de ponta a ponta: a perda que sai na cascata e no relatório ──────────────────────────────────────
def _serie_setembro():
    """30 dias, 40 MWh e 5 kWh/m² por dia. Com 10 MWp e PR meta 0,80: possível = 150 × 10 × 0,80 = 1.200 MWh."""
    return [{"dia": d, "realizado": 0.8, "geracao": 40.0, "poa": 5.0} for d in range(1, 31)]


@pytest.fixture
def usina_controlada(monkeypatch, overview):
    """Série, cadastro e paradas controlados; Fracttal e strings desligados (o teste não sai da máquina)."""
    def _monta(usina, fonte, paradas_book, linhas_overview):
        serie = {"usina": usina, "meta": 0.8, "pot": 10.0, "meta_ger": 45.0, "meta_poa": 5.5,
                 "pontos": _serie_setembro()}
        monkeypatch.setattr(app, "api_g_diario", lambda: app.jsonify(serie))
        monkeypatch.setattr(app, "api_g_inversores", lambda: app.jsonify({"usina": usina, "alvo": None,
                                                                            "inversores": []}))
        monkeypatch.setattr(app, "INFO_GERAL", {})
        monkeypatch.setitem(app.PR_PREVISTO, app._nrm(usina), {(2026, 9): {"pr_previsto_1ano": 0.8}})
        monkeypatch.setattr(app, "_paradas_book", {f: {"ts": time.time(), "rows": paradas_book if f == fonte else []}
                                                   for f in FONTES})
        monkeypatch.setattr(app, "FRACTTAL_ON", False)
        monkeypatch.setattr(app, "_frac_usina_ent", lambda *a, **k: None)
        monkeypatch.setattr(app, "_strings_problema_rows", lambda *a, **k: [])
        overview(fonte, linhas_overview)
    return _monta


def test_cascata_da_api_pv_divide_pela_frota_da_usina(usina_controlada):
    """10 trackers × 3 dias = 360 h numa frota de 60: fração = 360 ÷ (12 × 30 × 60) = 1/60, perda =
    1.200 × 1/60 × 0,20 = 4,0 MWh. Dividindo pelos 10 que pararam dava 1.200 × 0,10 × 0,20 = 24,0."""
    usina_controlada("Vertentes", "pv", _paradas("Vertentes", [f"TRK{i}" for i in range(1, 11)]),
                     [_linha_overview("Vertentes", 60)])
    d = app._cascata_usina("", "Vertentes", 2026, 9)
    assert d["ok"] and d["possivel"] == 1200.0 and d["trk"]["horas_solares"] == 360.0
    assert d["trk"]["frota"] == 60
    assert d["perda_trk"] == 4.0


def test_cascata_de_usina_sem_tracker_segue_sem_perda_de_tracker(usina_controlada):
    """A maior parte das usinas não tem tracker em fonte nenhuma: a cascata segue, com perda de tracker 0.
    (As paradas agora vão para a frota também quando não há fonte — e têm de existir, vazias.)"""
    usina_controlada("Usina Fixa", "pv", [], [])
    d = app._cascata_usina("", "Usina Fixa", 2026, 9)
    assert d["ok"] and d["perda_trk"] == 0.0 and d["trk"]["frota"] == 0


def test_cascata_de_usina_fora_do_overview_divide_pelo_cadastro(usina_controlada, monkeypatch):
    """A usina não está no overview de hoje, só nas paradas e na aba BD_Trackers (24 trackers). A cascata
    tem de entregar as paradas à frota para ela achar a usina: 3 × 36 h = 108 h, fração = 108 ÷ (12 × 30
    × 24) = 0,0125, perda = 1.200 × 0,0125 × 0,20 = 3,0 MWh. Dividindo pelos 3 que pararam dava 24,0."""
    usina_controlada("Colorado 2", "pv", _paradas("Colorado 2", ["TRK3", "TRK7", "TRK15"]),
                     [_linha_overview("Vertentes", 53)])
    monkeypatch.setattr(app, "BD_TRK_INV", {"colorado2": {n: "Inversor 1.1" for n in range(1, 25)}})
    d = app._cascata_usina("", "Colorado 2", 2026, 9)
    assert d["ok"] and d["trk"]["horas_solares"] == 108.0
    assert d["trk"]["frota"] == 24
    assert d["perda_trk"] == 3.0


def test_relatorio_da_athon_divide_pela_frota_da_sunop(usina_controlada, monkeypatch):
    """Relatório de setembro da MAB100 com o histórico do STORE (o book do período, reconstruído): 10
    trackers parados de 10 a 12/09 (36 h cada) numa frota de 150. Fração = 360 ÷ (12 × 30 × 150),
    perda = 1.200 × 0,20 ÷ 150 = 1,6 MWh. Dividindo pelos 10 que pararam dava 24,0."""
    usina_controlada("MAB100", "sunop", _paradas("MAB100", ["TRK1"]), [_linha_overview("MAB100", 150)])
    parados = {f"TRK{i}" for i in range(1, 11)}
    store = {f"2026-09-{d:02d}": {"MAB100": {
        "nome": "MAB100", "ts": 0, "cobertura": 1.0, "eventos": [],
        "classes": {t: {"status": "parado" if (10 <= d <= 12 and t in parados) else "ok"}
                    for t in (f"TRK{i}" for i in range(1, 151))}}}
        for d in range(1, 31)}
    monkeypatch.setattr(app, "_trk_eventos", store)
    monkeypatch.setitem(app._trk_ev_pids_cache, "sunop", {"ts": time.time(), "pids": {"MAB100"}})
    d = app._relatorio_build("MAB100", "2026-09-01", "2026-09-30")
    assert d["ok"] and d["possivel"] == 1200.0 and d["trk"]["horas_solares"] == 360.0
    assert d["trk"]["frota"] == 150
    assert d["perda_trk"] == 1.6
