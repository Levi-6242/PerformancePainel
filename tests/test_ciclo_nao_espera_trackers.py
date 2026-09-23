# -*- coding: utf-8 -*-
"""O ciclo do worker não espera a varredura de trackers (Levi, 22/09/2026).

O caso: às 17:49 a tela dizia "atualizado 17:48:25" sobre usinas com a última leitura de 16:20
(SMP100, Athon), 16:54 (Saturnino 1, API PV) e 17:10 (o banco inteiro). O pedido: "gostaria que os
dados se conversassem; por mais que não tenha um dado 17:48, puxa pelo menos o último".

A causa estava no ritmo do worker. Medido em 22/09, com processo novo e uma tarefa por vez: a
varredura de trackers da API PV levou 897 s. Todas as outras tarefas do ciclo, somadas, levaram
uns 3 min (a aba principal, sozinha, 116 s). A API PV só entrega o dia inteiro de tracker, de 8,8 a
13,8 MB por usina. No ciclo, ela ocupava uma das três vagas da ETAPA 3, que só acaba quando a
última tarefa acaba. Com isso, SunOp, banco, ETM e a aba principal eram refeitos a cada ~16 min,
em vez de 5.

Agora a varredura tem laço próprio (`_pv_trk_loop`) e ninguém espera por ela. A validade do dado
não muda: o overview é refeito quando passa do CACHE_TTL, e o dia de cada usina é rebaixado a cada
TRK_DIA_TTL.
"""
import threading

import pytest

import app


class _Parou(Exception):
    """Sentinela para sair do laço infinito depois de uma volta completa."""


def _roda_um_ciclo(monkeypatch, quando, freeze_now):
    """Uma volta REAL do _prewarm_loop (mesmo arranjo de test_sunop_janela_noturna). Devolve os nomes
    que as etapas pediram e se alguém chamou a varredura de trackers durante a volta."""
    freeze_now(quando)
    vistos, varreu = [], []

    def _falso_paralelo(tarefas, workers=4):
        vistos.append([n for n, _ in list(tarefas)])
        if len(vistos) == 3:          # etapas 1, 3 e 4: volta completa
            raise _Parou

    monkeypatch.setattr(app, "_prewarm_paralelo", _falso_paralelo)
    monkeypatch.setattr(app, "_refresh_data_cache", lambda *a, **k: None)   # ETAPA 2
    monkeypatch.setattr(app, "maybe_reload_equipamentos", lambda *a, **k: None)
    monkeypatch.setattr(app, "maybe_reload_tickets", lambda *a, **k: None)
    monkeypatch.setattr(app, "_expira_por_token_novo", lambda *a, **k: None)
    monkeypatch.setattr(app, "_build_pv_trk_payload", lambda *a, **k: varreu.append(k) or {"rows": []})
    monkeypatch.setattr(app.time, "sleep", lambda *a, **k: None)
    try:
        app._prewarm_loop()
    except _Parou:
        pass
    return [n for etapa in vistos for n in etapa], varreu


@pytest.mark.parametrize("quando", ["2026-09-22 13:00:00", "2026-09-22 22:30:00"])
def test_o_ciclo_principal_nao_roda_a_varredura_de_trackers(monkeypatch, freeze_now, quando):
    pedidos, varreu = _roda_um_ciclo(monkeypatch, quando, freeze_now)
    assert "PV trackers" not in pedidos, "a varredura de 15 min voltou para dentro do ciclo"
    assert varreu == [], "alguma etapa do ciclo chamou a varredura de trackers"


def test_o_resto_do_ciclo_continua_la(monkeypatch, freeze_now):
    """A contraprova: tirar a varredura não pode levar mais nada junto."""
    pedidos, _ = _roda_um_ciclo(monkeypatch, "2026-09-22 13:00:00", freeze_now)
    for nome in ("SunOp", "PG trackers", "SunOp trackers", "2C API PV", "ETM", "parados PV"):
        assert nome in pedidos, f"{nome!r} sumiu do ciclo"


# ── o laço próprio ────────────────────────────────────────────────────────────

class _Sinal:
    """Troca o threading.Event da 1ª aba principal: registra a espera sem esperar de verdade."""
    def __init__(self, ordem):
        self.ordem = ordem

    def wait(self, timeout=None):
        self.ordem.append(("esperou a aba principal", timeout))
        return True

    def set(self):
        self.ordem.append("aba principal saiu")

    def is_set(self):
        return True


def _roda_o_laco(monkeypatch, voltas, prewarm, ordem=None):
    """Roda `voltas` voltas do _pv_trk_loop. O sono só é interceptado nesta thread: as outras
    (daemons de outros testes) seguem com o sono de verdade."""
    principal, dormiu, sono_real = threading.current_thread(), [], app.time.sleep

    def _sono(s):
        if threading.current_thread() is not principal:
            return sono_real(s)
        dormiu.append(s)
        if len(dormiu) >= voltas:     # um sono por volta, no fim dela
            raise _Parou

    monkeypatch.setattr(app.time, "sleep", _sono)
    monkeypatch.setattr(app, "_prewarm_um_cache", prewarm)
    monkeypatch.setattr(app, "_ABA_PRINCIPAL_SAIU", _Sinal(ordem if ordem is not None else []))
    with pytest.raises(_Parou):
        app._pv_trk_loop()
    return dormiu


def test_no_boot_o_laco_espera_a_primeira_aba_principal(monkeypatch):
    """A largada do worker já é a hora mais disputada: ~25 laços começam juntos e dividem a mesma CPU
    (medido em 22/09: boot + ETAPA 1 + aba principal custam ~3,6 min sozinhos e levaram 23 min no
    servidor, 26 aqui). A varredura de trackers sempre veio DEPOIS da aba principal (ETAPA 3); largando
    junto, ela empurraria a 1ª aba principal pós-deploy mais para longe. Então a 1ª volta espera."""
    ordem = []

    def _prewarm(cache, build):
        ordem.append("varredura")
        return False
    _roda_o_laco(monkeypatch, 1, _prewarm, ordem)
    assert ordem and isinstance(ordem[0], tuple) and ordem[0][0] == "esperou a aba principal", ordem
    assert ordem[1] == "varredura"
    assert ordem[0][1] and ordem[0][1] > 0, "espera sem teto: se o prewarm morrer, os trackers param para sempre"


def test_o_ciclo_avisa_quando_a_aba_principal_saiu(monkeypatch, freeze_now):
    """O aviso sai depois da ETAPA 2 mesmo que a aba principal FALHE: ele diz 'já pode', não 'deu certo'."""
    ordem = []
    monkeypatch.setattr(app, "_ABA_PRINCIPAL_SAIU", _Sinal(ordem))

    def _falha():
        raise RuntimeError("API PV fora do ar")
    monkeypatch.setattr(app, "_refresh_data_cache", _falha)
    freeze_now("2026-09-22 13:00:00")
    vistos = []

    def _falso_paralelo(tarefas, workers=4):
        vistos.append([n for n, _ in list(tarefas)])
        if len(vistos) == 3:
            raise _Parou
    monkeypatch.setattr(app, "_prewarm_paralelo", _falso_paralelo)
    for nome in ("maybe_reload_equipamentos", "maybe_reload_tickets", "_expira_por_token_novo"):
        monkeypatch.setattr(app, nome, lambda *a, **k: None)
    monkeypatch.setattr(app.time, "sleep", lambda *a, **k: None)
    with pytest.raises(_Parou):
        app._prewarm_loop()
    assert "aba principal saiu" in ordem


def test_o_laco_proprio_refaz_o_overview_com_a_curva_completa(monkeypatch):
    """Mesma regra de antes (RÉGUA ÚNICA, 04/08): o worker classifica com a curva completa."""
    pedidos, builds = [], []
    monkeypatch.setattr(app, "_build_pv_trk_payload", lambda **k: builds.append(k) or {"rows": []})

    def _prewarm(cache, build):
        pedidos.append(cache)
        build()
        return True
    _roda_o_laco(monkeypatch, 2, _prewarm)
    assert len(pedidos) == 2 and all(c is app._pv_trk_cache for c in pedidos)
    assert builds == [{"fetch_curvas": True}, {"fetch_curvas": True}]


def test_o_laco_proprio_nao_morre_numa_falha(monkeypatch):
    """Um erro da API PV numa volta não pode parar os trackers até o próximo restart."""
    n = []

    def _prewarm(cache, build):
        n.append(1)
        if len(n) == 1:
            raise RuntimeError("API PV fora do ar")
        return False
    _roda_o_laco(monkeypatch, 2, _prewarm)
    assert len(n) == 2


def test_o_laco_proprio_sobe_com_o_worker(monkeypatch):
    alvos = []

    class _Thread:
        def __init__(self, target=None, daemon=None, **k):
            alvos.append(target)

        def start(self):
            pass
    monkeypatch.setattr(app.threading, "Thread", _Thread)
    app._iniciar_loops_de_fundo()
    assert app._pv_trk_loop in alvos, "sem o laço no worker, os trackers param de atualizar"
