# -*- coding: utf-8 -*-
"""Higiene do worker: gravar o snapshot e faxinar a memória sem atropelar quem está trabalhando.

Dois achados da varredura de 09/09/2026, ambos invisíveis no dia a dia e caros quando aparecem:

1. `_cache_save` mandava os acumuladores VIVOS (`_trk_accum`, `_trk_parada_total`, `_last_known`) por
   REFERÊNCIA para dentro do `json.dump`. O serializador anda a estrutura por dentro enquanto o
   worker escreve nela a cada leitura de tracker → "dictionary changed size during iteration". E o
   `_persist_loop` zerava a flag `dirty` ANTES de salvar: a exceção derrubava a gravação e ninguém
   tentava de novo — o web seguia servindo o snapshot velho até alguma outra coisa sujar a flag.

2. O faxineiro removia locks de `_pv_trk_graf_locks` sem o guarda e sem olhar se o lock estava EM USO.
   O lock só vira entrada de cache DEPOIS do fetch (que leva até 90 s); no meio disso a chave não
   está no cache, o faxineiro tirava o lock e o próximo pedido criava OUTRO — o dedup, que existe
   justamente para não bater N vezes no trackerschart, saía de cena na hora de maior carga.
"""
import threading

import app


# ── 1. o snapshot não pode sair de estrutura viva ──────────────────────────────────────────────────
class _JsonEspiao:
    """Fica no lugar do módulo json só para guardar o que foi entregue ao dump."""
    def __init__(self):
        self.data = None

    def dump(self, obj, f, **kw):
        self.data = obj
        f.write("{}")


def test_o_snapshot_leva_copia_dos_acumuladores_vivos(tmp_path, monkeypatch):
    esp = _JsonEspiao()
    monkeypatch.setattr(app, "json", esp)
    monkeypatch.setattr(app, "_PERSIST_PATH", str(tmp_path / "snap.json"))
    monkeypatch.setattr(app, "_trk_accum", {"date": "2026-09-09", "plants": {"1": {"trk": {"a": {"n": 1}}}}})
    monkeypatch.setattr(app, "_trk_parada_total", {"date": "2026-09-09", "plants": {"1": {"desde": 1.0}}})
    monkeypatch.setattr(app, "_last_known", {1: {"usina": "Teste"}})
    app._cache_save()
    d = esp.data
    assert d["trk_accum"] is not app._trk_accum, "acumulador vivo entregue por referência ao json.dump"
    assert d["trk_accum"]["plants"] is not app._trk_accum["plants"], "cópia rasa não protege o miolo"
    assert d["trk_parada"] is not app._trk_parada_total
    assert d["last_known"] is not app._last_known
    assert d["trk_accum"] == app._trk_accum, "a cópia tem de ser fiel ao que estava lá"


def test_a_copia_nao_muda_quando_o_worker_continua_escrevendo(tmp_path, monkeypatch):
    """É o ponto todo: a gravação vê um retrato parado, não um alvo em movimento."""
    esp = _JsonEspiao()
    monkeypatch.setattr(app, "json", esp)
    monkeypatch.setattr(app, "_PERSIST_PATH", str(tmp_path / "snap.json"))
    monkeypatch.setattr(app, "_trk_accum", {"date": "2026-09-09", "plants": {"1": {"trk": {}}}})
    app._cache_save()
    app._trk_accum["plants"]["2"] = {"trk": {}}          # o worker segue lendo trackers
    assert list(esp.data["trk_accum"]["plants"]) == ["1"]


def test_snapshot_que_falhou_e_tentado_de_novo(monkeypatch):
    """A flag `dirty` só pode ser zerada por uma gravação que DEU CERTO."""
    tentativas = []

    def _falha_uma_vez():
        tentativas.append(1)
        if len(tentativas) == 1:
            raise RuntimeError("dictionary changed size during iteration")

    class _Parou(Exception):
        pass

    class _RelogioFalso:
        @staticmethod
        def sleep(_s):
            if len(tentativas) >= 2:
                raise _Parou
        time = staticmethod(app.time.time)

    monkeypatch.setattr(app, "_cache_save", _falha_uma_vez)
    monkeypatch.setattr(app, "time", _RelogioFalso)
    app._persist_flag["dirty"] = True
    try:
        app._persist_loop()
    except _Parou:
        pass
    assert len(tentativas) == 2, "a gravação que falhou não foi tentada de novo"
    assert app._persist_flag["dirty"] is False, "gravação boa tem de baixar a flag"


# ── 2. o faxineiro e o dedup do gráfico de trackers ────────────────────────────────────────────────
def test_faxineiro_nao_tira_o_lock_de_quem_esta_buscando(monkeypatch):
    """A busca do trackerschart leva até 90 s e só popula o cache no fim. Tirar o lock no meio faz o
    próximo pedido criar outro e bater de novo na API — em dobro, justamente sob carga."""
    monkeypatch.setattr(app, "_pv_trk_graf_locks", {})
    monkeypatch.setattr(app, "_pv_trk_graf_cache", {})
    em_uso, livre = threading.Lock(), threading.Lock()
    em_uso.acquire()
    app._pv_trk_graf_locks[(1, "09/09/2026")] = em_uso      # alguém buscando agora
    app._pv_trk_graf_locks[(2, "08/09/2026")] = livre       # ninguém quer mais
    try:
        app._janitor_passada()
        assert (1, "09/09/2026") in app._pv_trk_graf_locks, "faxineiro tirou o lock de uma busca em curso"
        assert (2, "08/09/2026") not in app._pv_trk_graf_locks, "lock órfão tem de sair (era um por usina/dia, para sempre)"
    finally:
        em_uso.release()


def test_faxineiro_preserva_o_lock_de_quem_tem_cache(monkeypatch):
    """Chave com curva no cache continua valendo — é a regra que já existia."""
    monkeypatch.setattr(app, "_pv_trk_graf_locks", {})
    monkeypatch.setattr(app, "_pv_trk_graf_cache", {(3, "09/09/2026"): {"ts": app.time.time(), "g": {}}})
    app._pv_trk_graf_locks[(3, "09/09/2026")] = threading.Lock()
    app._janitor_passada()
    assert (3, "09/09/2026") in app._pv_trk_graf_locks
