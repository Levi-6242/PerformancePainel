# -*- coding: utf-8 -*-
"""Status do gráfico de trackers == status dos CARDS (08/09/2026).

O /chart tinha um motor PARALELO de status: classificava a curva do dia e pronto, sem exonerar o falso-parado em
cima do alvo e sem separar quem está sem comunicação. Resultado no TIM100: a legenda do gráfico dizia "76 parado"
enquanto os cards da mesma tela mostravam 8 parados, 36 sem comunicação e 101 normais. "Não pode ter tracker parado
no status e no card estar normalizado — o certo é o dos cards" (Levi).

Aqui a prova é de COMPORTAMENTO: a mesma curva, pelos dois caminhos, tem de dar o mesmo status tracker a tracker.
"""
import app


def _curva(hhmm_ini=6 * 60, hhmm_fim=18 * 60, passo=10):
    """Minutos do dia (06–18h) de 10 em 10, em ISO — a janela que as réguas usam."""
    return [f"2026-09-08T{m // 60:02d}:{m % 60:02d}:00" for m in range(hhmm_ini, hhmm_fim + 1, passo)]


def _frota(n=10):
    """Curva realista: a frota varre de −50° a +50° no dia; o alvo é a mediana dela."""
    xs = _curva()
    g = {}
    for i in range(1, n + 1):
        g[f"Tracker {i}"] = [{"x": x, "y": round(-50 + 100 * k / (len(xs) - 1) + (i % 3) * 0.2, 2)}
                             for k, x in enumerate(xs)]
    return g


def _cadeia_dos_cards(g, alvos=None):
    """A cadeia que o detalhe (cards) roda: freeze-based + comm-morta, depois alvo-mediana + exoneração."""
    lst = [{"id": n, "atual": (pts[-1]["y"] if pts else None), "alvo": (alvos or {}).get(n), "status": "normal"}
           for n, pts in g.items()]
    app._trk_status_from_curva(lst, g)
    app._trk_alvo_mediana({"trackers": lst, "parados": 0, "sem_comunicacao": not any(g.values())})
    return {t["id"]: (t.get("status"), bool(t.get("sem_comunicacao"))) for t in lst}


def _pelo_gráfico(g, alvos=None):
    trackers = [{"id": n, "x": [p["x"] for p in pts], "y": [p["y"] for p in pts]} for n, pts in g.items()]
    payload = {}
    app._trk_chart_aplica_status(trackers, g, payload, alvos)
    return {t["id"]: (t.get("status"), bool(t.get("sem_comunicacao"))) for t in trackers}, payload, trackers


def test_grafico_e_cards_dao_o_mesmo_status_na_mesma_curva():
    g = _frota()
    g["Tracker 11"] = [{"x": x, "y": 0.0} for x in _curva()]        # sensor morto: 100% em 0,00° (assinatura TIM100)
    g["Tracker 12"] = [{"x": x, "y": -50.0} for x in _curva()]      # congelado longe da frota: parado de verdade
    alvos = {n: 50.0 for n in g}                                    # alvo do supervisório no fim do dia
    do_grafico, payload, trackers = _pelo_gráfico(g, alvos)
    dos_cards = _cadeia_dos_cards(g, alvos)
    assert do_grafico == dos_cards, "o gráfico voltou a ter régua própria"
    # e o resultado é o que o analista lê nos cards:
    assert do_grafico["Tracker 11"] == ("parado", True), "sensor morto tem de sair como SEM COMUNICAÇÃO"
    assert do_grafico["Tracker 12"] == ("parado", False)            # congelado fora do alvo segue parado
    assert all(do_grafico[f"Tracker {i}"] == ("normal", False) for i in range(1, 11))
    # contadores do payload = a lista (o front conta a lista; divergir aqui era o bug do Inhapi 3)
    assert payload["parados"] == sum(1 for s, _ in do_grafico.values() if s == "parado") == 2
    assert payload["sem_comunicacao_n"] == 1 and payload["severos"] == 0
    assert all("disparidade" in t for t in trackers)                 # disparidade = contra o alvo bom, como no card


def test_falso_parado_em_cima_do_alvo_nao_conta_no_grafico():
    """O caso que inflava a legenda: rastreou o dia, parou perto do alvo e a frota também parou (fim de tarde).
    A régua consolidada rebaixa para normal — e agora o gráfico rebaixa junto."""
    xs = _curva()
    g = _frota()
    congelado = []
    for k, x in enumerate(xs):
        y = round(-50 + 100 * k / (len(xs) - 1), 2)
        congelado.append({"x": x, "y": min(y, 44.0)})               # segue a frota e trava a 6° do fim (dentro dos 12°)
    g["Tracker 11"] = congelado
    do_grafico, payload, _ = _pelo_gráfico(g, {n: 50.0 for n in g})
    assert do_grafico == _cadeia_dos_cards(g, {n: 50.0 for n in g})
    assert do_grafico["Tracker 11"][0] != "parado", "falso-parado em cima do alvo voltou a contar como parado"
    assert payload["parados"] == 0


def test_motor_paralelo_do_grafico_nao_existe_mais():
    """Uma régua só: se alguém recriar o atalho, este teste cai."""
    assert not hasattr(app, "_trk_chart_status"), "voltou o motor paralelo do /chart"
    import inspect
    src = inspect.getsource(app._trk_chart_aplica_status)
    assert "_trk_status_from_curva" in src and "_trk_alvo_mediana" in src
