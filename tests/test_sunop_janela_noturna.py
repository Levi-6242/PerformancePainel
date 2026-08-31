"""Pausa noturna das curvas da SunOp/Axis.

Fora da janela solar não há o que calcular a partir da curva do dia: "parado" se mede por
amplitude do ângulo, disponibilidade e ocorrências de string vivem em 06-18h, e depois da
meia-noite a curva de HOJE está literalmente vazia. Mesmo assim o worker rebaixava o dia
inteiro dos ~1000 trackers a cada ciclo, a noite toda — a maior fatia de requisição inútil
à SunOp que sobrou depois da deduplicação de 26/08.

Estes testes fixam as DUAS metades da regra: o que pausa, e o que nunca pode pausar junto.
"""
import app


# ── a janela ──────────────────────────────────────────────────────────────────
def test_janela_fechada_de_madrugada(freeze_now):
    freeze_now("2026-08-26 03:00:00")
    assert app._sunop_janela_curva() is False


def test_janela_aberta_ao_meio_dia(freeze_now):
    freeze_now("2026-08-26 12:00:00")
    assert app._sunop_janela_curva() is True


def test_janela_abre_ANTES_do_sol(freeze_now):
    """A curva tem de chegar QUENTE às 06:00 — abrir só no nascer do sol deixaria o
    primeiro ciclo do dia inteiro frio, que é justamente o horário da ronda das 08:25."""
    freeze_now("2026-08-26 05:39:00")
    assert app._sunop_janela_curva() is False
    freeze_now("2026-08-26 05:40:00")
    assert app._sunop_janela_curva() is True


def test_janela_pega_a_cauda_do_fim_de_tarde(freeze_now):
    freeze_now("2026-08-26 18:19:00")
    assert app._sunop_janela_curva() is True
    freeze_now("2026-08-26 18:20:00")
    assert app._sunop_janela_curva() is False


# ── o filtro do prewarm ───────────────────────────────────────────────────────
_TAREFAS = [(n, (lambda: None)) for n in (
    "PG disponibilidade", "SunOp disponibilidade", "Axis disponibilidade", "2C disponibilidade",
    "SunOp", "Axis", "SunOp ETM", "SunOp trackers", "SunOp ETM anál",
    "strings SunOp", "strings Axis", "parados PV")]


def _nomes(ts):
    return [n for n, _ in ts]


def test_de_dia_nao_filtra_nada(freeze_now):
    freeze_now("2026-08-26 12:00:00")
    assert _nomes(app._prewarm_filtra_noturno(_TAREFAS)) == _nomes(_TAREFAS)


def test_de_noite_pausa_exatamente_as_tarefas_de_curva(freeze_now):
    freeze_now("2026-08-26 22:00:00")
    fora = set(_nomes(_TAREFAS)) - set(_nomes(app._prewarm_filtra_noturno(_TAREFAS)))
    assert fora == {"SunOp disponibilidade", "Axis disponibilidade", "SunOp trackers",
                    "SunOp ETM anál", "strings SunOp", "strings Axis"}


def test_de_noite_o_status_BARATO_continua(freeze_now):
    """last_values é quem acende falha de COMUNICAÇÃO (ver process_plant_sunop: falha_comm sai
    do ts_max do lote, não da curva). Pausá-lo cegaria a madrugada — decisão do Levi 26/08."""
    freeze_now("2026-08-26 02:00:00")
    ficaram = _nomes(app._prewarm_filtra_noturno(_TAREFAS))
    for nome in ("SunOp", "Axis", "SunOp ETM"):
        assert nome in ficaram


def test_de_noite_outras_fontes_nao_sao_afetadas(freeze_now):
    """A régua é só da SunOp/Axis: PG, 2C e API PV têm cadência própria e nada a ver com isto."""
    freeze_now("2026-08-26 02:00:00")
    ficaram = _nomes(app._prewarm_filtra_noturno(_TAREFAS))
    for nome in ("PG disponibilidade", "2C disponibilidade", "parados PV"):
        assert nome in ficaram


# ── o que o portão NÃO pode alcançar ──────────────────────────────────────────
def test_primitiva_de_busca_NAO_e_bloqueada_a_noite(freeze_now, monkeypatch):
    """O portão é do REAQUECIMENTO de hoje, nunca da busca. De madrugada o _fecha_dia_loop
    (01:30) consolida o D-1 e os backfills horários completam dias passados — todos passam
    por aqui. E o force=1/drill é ação do usuário, que sempre busca."""
    freeze_now("2026-08-26 03:00:00")
    chamou = {"n": 0}

    class _R:
        status_code = 200

        @staticmethod
        def json():
            return [{"pathname": "P.TRK_1.POSAT", "timestamp": "2026-08-25T09:00:00", "value": 12.0}]

    def _fake_req(*a, **k):
        chamou["n"] += 1
        return _R()

    monkeypatch.setattr(app, "_sunop_req", _fake_req)
    out = app._sunop_analog_history(["P.TRK_1.POSAT"], "2026-08-25T00:00:00", "2026-08-25T23:59:59")
    assert chamou["n"] == 1, "a busca do dia PASSADO tem de continuar livre de madrugada"
    assert out["P.TRK_1.POSAT"] == [("2026-08-25T09:00:00", 12.0)]


# ── guardas contra a pausa "vazar" em silêncio ────────────────────────────────
def test_nomes_do_frozenset_existem_mesmo_no_prewarm():
    """O filtro casa por NOME. Um nome com erro de digitação faria a pausa não pausar NADA,
    sem sintoma nenhum: o worker seguiria baixando curva a noite toda e os testes acima
    continuariam verdes, porque exercitam uma lista sintética."""
    import inspect
    fonte = inspect.getsource(app._prewarm_loop)
    for nome in app._SUNOP_TAREFAS_CURVA:
        assert f'"{nome}"' in fonte, f"{nome!r} não aparece no _prewarm_loop — nome errado?"


def test_todas_as_etapas_do_prewarm_passam_pelo_filtro():
    """São três chamadas a _prewarm_paralelo (etapas 1, 3 e 4). Uma que escape do filtro
    vaza a pausa: aquela etapa volta a baixar curva de madrugada, também sem sintoma."""
    import inspect
    import re
    fonte = inspect.getsource(app._prewarm_loop)
    chamadas = re.findall(r"_prewarm_paralelo\(\s*([A-Za-z_\[]+)", fonte)
    assert len(chamadas) == 3, f"esperava 3 chamadas, achei {len(chamadas)}: {chamadas}"
    for c in chamadas:
        assert c.startswith("_prewarm_filtra_noturno"), f"etapa sem filtro: {c!r}"


# ── prova de ponta a ponta: um ciclo REAL do prewarm ──────────────────────────
class _Parou(Exception):
    """Sentinela para sair do laço infinito depois de uma volta completa."""


def _roda_um_ciclo(monkeypatch, quando, freeze_now):
    """Executa UMA volta do _prewarm_loop de verdade e devolve os nomes que cada etapa pediu."""
    freeze_now(quando)
    vistos = []

    def _falso_paralelo(tarefas, workers=4):
        tarefas = list(tarefas)
        vistos.append([n for n, _ in tarefas])
        if len(vistos) == 3:          # etapas 1, 3 e 4 — volta completa
            raise _Parou

    monkeypatch.setattr(app, "_prewarm_paralelo", _falso_paralelo)
    monkeypatch.setattr(app, "_refresh_data_cache", lambda *a, **k: None)   # ETAPA 2
    monkeypatch.setattr(app, "maybe_reload_equipamentos", lambda *a, **k: None)
    monkeypatch.setattr(app, "maybe_reload_tickets", lambda *a, **k: None)
    monkeypatch.setattr(app, "_expira_por_token_novo", lambda *a, **k: None)
    monkeypatch.setattr(app.time, "sleep", lambda *a, **k: None)
    try:
        app._prewarm_loop()
    except _Parou:
        pass
    return [n for etapa in vistos for n in etapa]


def test_ciclo_noturno_nao_pede_NENHUMA_curva_da_sunop(monkeypatch, freeze_now):
    pedidos = _roda_um_ciclo(monkeypatch, "2026-08-26 23:10:00", freeze_now)
    vazou = [n for n in pedidos if n in app._SUNOP_TAREFAS_CURVA]
    assert vazou == [], f"curva da SunOp pedida de madrugada: {vazou}"


def test_ciclo_noturno_MANTEM_o_status_barato(monkeypatch, freeze_now):
    """Sem isto a economia viraria cegueira: é o last_values que acende falha de comunicação."""
    pedidos = _roda_um_ciclo(monkeypatch, "2026-08-26 23:10:00", freeze_now)
    for nome in ("SunOp", "Axis", "SunOp ETM"):
        assert nome in pedidos, f"{nome!r} sumiu do ciclo noturno"


def test_ciclo_DIURNO_pede_a_curva_normalmente(monkeypatch, freeze_now):
    """A contraprova: de dia nada foi perdido."""
    pedidos = _roda_um_ciclo(monkeypatch, "2026-08-26 13:00:00", freeze_now)
    for nome in ("SunOp disponibilidade", "SunOp trackers", "strings SunOp"):
        assert nome in pedidos, f"{nome!r} não foi pedido no ciclo diurno"
