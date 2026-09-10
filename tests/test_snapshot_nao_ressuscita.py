# -*- coding: utf-8 -*-
"""O snapshot do worker não pode desfazer o que este processo acabou de invalidar (varredura 09/09/2026).

Achado: no `_cache_load`, os extras `sunop_str_ev` e `plat_view` eram injetados às CEGAS — sem a regra
anti-retrocesso que o resto da função aplica ("salvo mais velho não sobrescreve memória mais nova").

Como isso aparecia para o analista: ele tranca uma string; a rota POST limpa as ocorrências do SunOp
no processo web e a tela mostra certo; até 20 s depois o `_snapshot_watch_loop` relê o snapshot que o
worker gravou ANTES da trava e reinjeta as mesmas linhas — a string trancada volta para a aba
Ocorrências e para o "sem corrente". Era o segundo mecanismo do mesmo sintoma que a recarga das travas
resolve do lado do worker (ver test_trancadas_recarga.py).

A marca d'água (`_marca_invalidacao_local`) é o que distingue os dois casos que 'chave ausente' não
distingue sozinha: cache vazio de BOOT (pode encher com o snapshot) x cache ESVAZIADO de propósito
(não pode).
"""
import json
import time

import app


def _snap(tmp_path, extras):
    p = tmp_path / "cache_snapshot.json"
    p.write_text(json.dumps({"saved_at": time.time(), "caches": {}, "extras": extras}), encoding="utf-8")
    return str(p)


def _isola(monkeypatch, caminho):
    monkeypatch.setattr(app, "_PERSIST_PATH", caminho)
    monkeypatch.setattr(app, "_sunop_str_ev_cache", dict(app._sunop_str_ev_cache))
    monkeypatch.setattr(app, "_plat_view_cache", dict(app._plat_view_cache))
    monkeypatch.setattr(app, "_str_prob_pv_cache", dict(app._str_prob_pv_cache))
    monkeypatch.setattr(app, "_INVALIDADO_EM", [0.0], raising=False)


def test_snapshot_enche_cache_frio_no_boot(tmp_path, monkeypatch):
    """O caso que justifica o bloco existir: web nasce frio e herda o trabalho caro do worker
    (as ocorrências do SunOp levam ~1 min para calcular)."""
    _isola(monkeypatch, _snap(tmp_path, {"sunop_str_ev": {"gridco|2026-09-09": {"ts": 100.0, "rows": [1]}}}))
    app._sunop_str_ev_cache.clear()
    app._cache_load()
    assert app._sunop_str_ev_cache[("gridco", "2026-09-09")]["rows"] == [1]


def test_snapshot_velho_nao_passa_por_cima_de_memoria_nova(tmp_path, monkeypatch):
    """Mesma regra que o resto do `_cache_load` já seguia: quem tem `ts` maior manda."""
    _isola(monkeypatch, _snap(tmp_path, {"sunop_str_ev": {"gridco|2026-09-09": {"ts": 100.0, "rows": ["velho"]}},
                                         "plat_view": {"991": {"ts": 100.0, "dados": "velho"}}}))
    app._sunop_str_ev_cache[("gridco", "2026-09-09")] = {"ts": 500.0, "rows": ["novo"]}
    app._plat_view_cache[991] = {"ts": 500.0, "dados": "novo"}
    app._cache_load()
    assert app._sunop_str_ev_cache[("gridco", "2026-09-09")]["rows"] == ["novo"]
    assert app._plat_view_cache[991]["dados"] == "novo"


def test_o_que_foi_invalidado_de_proposito_nao_ressuscita(tmp_path, monkeypatch):
    """O caso do Levi: trancou a string, o POST limpou as ocorrências, o snapshot do worker (calculado
    ANTES) não pode reinjetar as linhas de volta 20 s depois."""
    _isola(monkeypatch, _snap(tmp_path, {"sunop_str_ev": {"gridco|2026-09-09": {"ts": time.time() - 60,
                                                                               "rows": ["com a trancada"]}}}))
    app._sunop_str_ev_cache[("gridco", "2026-09-09")] = {"ts": time.time() - 60, "rows": ["com a trancada"]}
    app._sunop_str_ev_cache.clear()          # é o que a rota POST faz
    app._marca_invalidacao_local()
    app._cache_load()
    assert ("gridco", "2026-09-09") not in app._sunop_str_ev_cache, \
        "o snapshot ressuscitou a linha da string trancada"


def test_linha_calculada_DEPOIS_da_trava_pode_entrar(tmp_path, monkeypatch):
    """A marca d'água não pode congelar o cache para sempre: assim que o worker recalcula (já com a
    trava, graças à recarga do ufv_state.json), o resultado novo tem de voltar a valer."""
    _isola(monkeypatch, _snap(tmp_path, {}))
    app._sunop_str_ev_cache.clear()
    app._marca_invalidacao_local()
    monkeypatch.setattr(app, "_PERSIST_PATH",
                        _snap(tmp_path, {"sunop_str_ev": {"gridco|2026-09-09": {"ts": time.time() + 1,
                                                                               "rows": ["sem a trancada"]}}}))
    app._cache_load()
    assert app._sunop_str_ev_cache[("gridco", "2026-09-09")]["rows"] == ["sem a trancada"]


def test_str_prob_pv_invalidado_nao_volta_do_snapshot(tmp_path, monkeypatch):
    """`_str_prob_pv_cache` é invalidado zerando `rows` e MANTENDO o `ts` — a regra ">= ts" sozinha
    deixava o snapshot do worker repor as linhas na hora seguinte."""
    _isola(monkeypatch, _snap(tmp_path, {"str_prob_pv": {"ts": time.time() - 60, "rows": ["com a trancada"]}}))
    app._str_prob_pv_cache.update({"ts": time.time() - 120, "rows": None})
    app._marca_invalidacao_local()
    app._cache_load()
    assert app._str_prob_pv_cache["rows"] is None, "o 'sem corrente' voltou com a string trancada"


def test_a_rota_que_tranca_marca_a_invalidacao():
    """Se o POST parar de marcar, o snapshot volta a desfazer a limpeza dele."""
    import inspect
    assert "_marca_invalidacao_local()" in inspect.getsource(app.api_state_string_trancada)
    assert "_marca_invalidacao_local()" in inspect.getsource(app._tranc_invalida_caches)
