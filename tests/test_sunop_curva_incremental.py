"""Busca INCREMENTAL da curva de tracker do dia (SunOp/Axis).

Hoje toda atualização re-baixa `00:00→23:59`, então às 17h o worker re-transfere 11h de curva
que já tem em cache, para 1005 trackers × 2 séries. NÃO reduz a CONTAGEM de requisições (o lote
é de 40 pathnames: 1h ou 24h dão o mesmo nº de POSTs) — o ganho é payload, latência e CPU sob o
GIL, que é o que encurta o ciclo do prewarm.

O risco desta mudança é silencioso: uma fusão errada não dá erro, ela ENCOLHE ou DEFORMA a curva,
e a curva é o insumo de "parado por amplitude". Por isso o teste central aqui é o de
EQUIVALÊNCIA — a série fundida tem de ser idêntica à do fetch completo.
"""
from datetime import datetime, timedelta

import app


def _si_falso(trk_hist, trackers):
    return lambda inst="gridco": {"trk_hist": trk_hist, "meta": {"MAB100": {"trackers": trackers}}}


TRACKERS = {"TRK_1": {"atual": "MAB100.TRK_1.POSAT", "alvo": "MAB100.TRK_1.POSAL"}}


def _fonte(ate_hh):
    """Curva sintética de 06:00 até `ate_hh`, um ponto a cada 10 min. Determinística."""
    pts = []
    t = datetime(2026, 8, 26, 6, 0, 0)
    fim = datetime(2026, 8, 26, ate_hh, 0, 0)
    while t <= fim:
        pts.append((t.strftime("%Y-%m-%dT%H:%M:%S"), round(-55 + (t.hour - 6) * 9.0, 2)))
        t += timedelta(minutes=10)
    return pts


def _monta(monkeypatch, ate_hh, agora):
    """Prepara app com uma fonte que só devolve pontos DENTRO da janela pedida."""
    pedidos = []
    periodos = []
    _monta.periodos = periodos      # exposto p/ o teste da granularidade abaixo

    def _hist(paths, ini, fim, inst="gridco", period=None):
        # `period` entrou em 02/09 (agregação de 15 min pedida à SunOp). Fica registrado à parte
        # de `pedidos` de propósito: as asserções das janelas comparam a lista inteira, e somar
        # um terceiro campo às tuplas quebraria todas por um motivo que não é o delas.
        pedidos.append((ini, fim))
        periodos.append(period)
        todos = _fonte(ate_hh)
        dentro = [(ts, v) for ts, v in todos if ini <= ts <= fim]
        return {p: list(dentro) for p in paths}

    monkeypatch.setattr(app, "_sunop_analog_history", _hist)

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return agora

    monkeypatch.setattr(app, "datetime", _Frozen)
    return pedidos


def test_cache_frio_busca_o_DIA_INTEIRO(monkeypatch):
    hist = {}
    monkeypatch.setattr(app, "_si", _si_falso(hist, TRACKERS))
    pedidos = _monta(monkeypatch, 10, datetime(2026, 8, 26, 10, 5))
    app._sunop_trk_curvas("MAB100", "2026-08-26")
    assert pedidos == [("2026-08-26T00:00:00", "2026-08-26T23:59:59")]


def test_segunda_busca_na_MESMA_hora_pede_so_o_delta(monkeypatch):
    hist = {}
    monkeypatch.setattr(app, "_si", _si_falso(hist, TRACKERS))
    pedidos = _monta(monkeypatch, 10, datetime(2026, 8, 26, 10, 5))
    app._sunop_trk_curvas("MAB100", "2026-08-26")

    hist[("MAB100", "2026-08-26")]["ts"] = 0.0          # vence o TTL, força nova busca
    pedidos = _monta(monkeypatch, 10, datetime(2026, 8, 26, 10, 40))
    app._sunop_trk_curvas("MAB100", "2026-08-26")
    ini, fim = pedidos[0]
    assert ini == "2026-08-26T09:30:00", f"esperava último ponto (10:00) − 30 min, veio {ini}"
    assert fim == "2026-08-26T23:59:59"


def test_a_cada_HORA_volta_a_buscar_o_dia_inteiro(monkeypatch):
    """Sobreposição pega ingestão atrasada, mas não pega correção que a SunOp faça lá atrás."""
    hist = {}
    monkeypatch.setattr(app, "_si", _si_falso(hist, TRACKERS))
    _monta(monkeypatch, 10, datetime(2026, 8, 26, 10, 5))
    app._sunop_trk_curvas("MAB100", "2026-08-26")

    hist[("MAB100", "2026-08-26")]["ts"] = 0.0
    pedidos = _monta(monkeypatch, 11, datetime(2026, 8, 26, 11, 5))   # virou a hora
    app._sunop_trk_curvas("MAB100", "2026-08-26")
    assert pedidos[0] == ("2026-08-26T00:00:00", "2026-08-26T23:59:59")


def test_EQUIVALENCIA_a_serie_fundida_e_identica_a_do_fetch_completo(monkeypatch):
    """O teste que importa. Duas voltas incrementais têm de produzir exatamente a mesma curva
    que uma única busca do dia inteiro no mesmo instante.

    Aqui a igualdade EXATA vale porque a fonte deste teste é determinística. Contra a API REAL,
    NÃO use `==`: medido em 26/08, duas buscas CHEIAS idênticas já devolvem 59 pontos com valores
    diferentes nos últimos bits do float (diferença 0,0000 grau). Comparar bits contra a SunOp
    acusa uma deformação que não existe — a verificação ao vivo tem de usar tolerância. Com
    tolerância de 1e-6 a curva fundida bateu com a do zero em 63/63 trackers da CPP100, mesmos
    timestamps e mesma contagem de pontos (9709)."""
    hist = {}
    monkeypatch.setattr(app, "_si", _si_falso(hist, TRACKERS))

    _monta(monkeypatch, 8, datetime(2026, 8, 26, 8, 5))
    app._sunop_trk_curvas("MAB100", "2026-08-26")
    hist[("MAB100", "2026-08-26")]["ts"] = 0.0
    _monta(monkeypatch, 9, datetime(2026, 8, 26, 9, 5))
    app._sunop_trk_curvas("MAB100", "2026-08-26")
    hist[("MAB100", "2026-08-26")]["ts"] = 0.0
    _monta(monkeypatch, 9, datetime(2026, 8, 26, 9, 40))
    incremental = app._sunop_trk_curvas("MAB100", "2026-08-26")

    limpo = {}                                          # a contraprova: tudo de uma vez só
    monkeypatch.setattr(app, "_si", _si_falso(limpo, TRACKERS))
    _monta(monkeypatch, 9, datetime(2026, 8, 26, 9, 40))
    cheio = app._sunop_trk_curvas("MAB100", "2026-08-26")

    assert incremental["posat"]["TRK_1"] == cheio["posat"]["TRK_1"]
    assert incremental["posal"]["TRK_1"] == cheio["posal"]["TRK_1"]
    assert len(incremental["posat"]["TRK_1"]) == len(_fonte(9))


def test_dia_PASSADO_nunca_e_incremental(monkeypatch):
    """Dia fechado não cresce mais; incremental ali só criaria risco sem ganho."""
    hist = {}
    monkeypatch.setattr(app, "_si", _si_falso(hist, TRACKERS))
    _monta(monkeypatch, 10, datetime(2026, 8, 26, 10, 5))
    app._sunop_trk_curvas("MAB100", "2026-08-25")
    hist[("MAB100", "2026-08-25")]["ts"] = 0.0
    pedidos = _monta(monkeypatch, 10, datetime(2026, 8, 26, 10, 40))
    app._sunop_trk_curvas("MAB100", "2026-08-25")
    assert pedidos[0] == ("2026-08-25T00:00:00", "2026-08-25T23:59:59")


def test_guarda_anti_encolhimento_continua_valendo(monkeypatch):
    """Resposta PARCIAL da SunOp não pode encolher a curva — a contagem de parados pularia
    entre refreshes. Guarda que já existia; a fusão não pode tê-la desarmado."""
    hist = {}
    monkeypatch.setattr(app, "_si", _si_falso(hist, TRACKERS))
    _monta(monkeypatch, 10, datetime(2026, 8, 26, 10, 5))
    boa = app._sunop_trk_curvas("MAB100", "2026-08-26")
    n_bom = len(boa["posat"]["TRK_1"])

    hist[("MAB100", "2026-08-26")]["ts"] = 0.0
    hist[("MAB100", "2026-08-26")]["cheio_h"] = -1      # força busca CHEIA (não incremental)
    monkeypatch.setattr(app, "_sunop_analog_history",
                        lambda paths, ini, fim, inst="gridco", period=None: {p: [] for p in paths})
    depois = app._sunop_trk_curvas("MAB100", "2026-08-26")
    assert len(depois["posat"]["TRK_1"]) == n_bom, "curva boa foi substituída por resposta vazia"


def test_a_granularidade_de_15min_e_pedida_em_TODA_busca(monkeypatch):
    """Cada busca de curva de tracker tem de mandar `period=15m` — inclusive a INCREMENTAL.

    Se só a busca cheia mandasse, a incremental voltaria com pontos de 5 min e a fusão por
    timestamp misturaria as duas grades na mesma série. Não daria erro: deformaria a curva, que
    é o insumo de 'parado por amplitude'. É a mesma classe de falha muda que o teste de
    EQUIVALÊNCIA acima existe para pegar."""
    hist = {}
    monkeypatch.setattr(app, "_si", _si_falso(hist, TRACKERS))
    _monta(monkeypatch, 10, datetime(2026, 8, 26, 10, 5))
    app._sunop_trk_curvas("MAB100", "2026-08-26")     # 1ª volta: cheia
    # sem vencer o TTL a 2ª volta sai do cache e NÃO busca — o teste passaria vendo só a cheia,
    # que é justamente o caminho que ele NÃO precisa provar.
    hist[("MAB100", "2026-08-26")]["ts"] = 0.0
    app._sunop_trk_curvas("MAB100", "2026-08-26")     # 2ª volta na mesma hora: incremental
    periodos = _monta.periodos
    assert len(periodos) >= 2, "esperava duas buscas (cheia + incremental)"
    assert set(periodos) == {app.TRK_CURVA_PERIODO}, periodos
