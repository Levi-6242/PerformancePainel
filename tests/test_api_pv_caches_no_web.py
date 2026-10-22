# -*- coding: utf-8 -*-
"""Os dois caches da API PV que incham o web da plataforma, com prazo e teto (Desempenho, 22/10/2026).

Raio-X do Nexus às 08:51 de 22/10, dentro do web: o dia de trackers da API PV com 545 MB (19 dias de usina) e o dia de
strings da API PV (`_spv_hist_recs`) com 493 MB em só 3 dias, os dois parados desde antes das 07:59, com a máquina em
0,5 GB livres e 3,6 GB no swap. Levi: "resolva esses da API PV que estão atrapalhando".

- O dia de strings: o "~6 MB cada" do código é a usina de 4 inversores; na de 20, o dia cru tem ~28,8 mil registros
  (~165 MB). Agora sai o dia que ninguém relê há SPV_HIST_OCIOSO_S, e a soma dos registros tem teto.
- O dia de trackers: a poda do worker (dia passado parado há 2 h e o teto de pontos) passa a valer também no web. Ela
  ficava só no worker porque a aba Perdas lia esse cache no web; a aba saiu em 12/10, e o único leitor que não busca
  (fetch=False) num dia passado é a rota de depuração da régua.

O que sai é dia FECHADO: pedido de novo, volta igual, ao custo de uma busca. A API PV aqui é de mentira."""
import time
from datetime import datetime, timedelta

import pytest

import app
from test_worker_memoria_teto import _br, _pontos_passados, api  # noqa: F401 — o dublê da API PV (/trackers)


@pytest.fixture
def spv(monkeypatch):
    monkeypatch.setattr(app, "_spv_hist_recs", {})
    monkeypatch.setattr(app, "_spv_hist_uso", {}, raising=False)
    return app._spv_hist_recs


def _dia(n):
    """n registros (o mesmo dict repetido: só o len conta para o teto, e o teste não gasta memória)."""
    return [{"tsleitura_new": "2026-10-21 10:00:00", "idefinversor": 1, "conteudojson": "{}"}] * n


# ── o dia de strings da API PV (_spv_hist_recs) ──────────────────────────────────────────────────────────────────────
def test_o_dia_de_strings_parado_sai(spv):
    agora = time.time()
    spv[(1, "20/10/2026")], spv[(2, "20/10/2026")] = _dia(10), _dia(10)
    app._spv_hist_uso[(1, "20/10/2026")] = agora - app.SPV_HIST_OCIOSO_S - 60      # ninguém relê há mais que o prazo
    app._spv_hist_uso[(2, "20/10/2026")] = agora - 60
    assert app._spv_hist_poda(agora=agora) == 1
    assert list(spv) == [(2, "20/10/2026")]


def test_reler_o_dia_conta_como_uso(spv, monkeypatch):
    """O drill e o CSV do mesmo dia: quem relê dentro do prazo segura o dia guardado (e não paga a cota de novo)."""
    spv[(1, "20/10/2026")] = _dia(10)
    app._spv_hist_uso[(1, "20/10/2026")] = time.time() - app.SPV_HIST_OCIOSO_S + 30
    recs, motivo = app._spv_day_records_hist(1, "tok", "20/10/2026")
    assert motivo is None and len(recs) == 10
    assert app._spv_hist_poda(agora=time.time() + 60) == 0 and (1, "20/10/2026") in spv


def test_o_dia_guardado_por_fora_conta_o_prazo_a_partir_da_poda(spv):
    """Quem guarda direto no dict (sem o carimbo de uso) começa a contar o prazo na poda: não sai nela, e sai depois."""
    spv[(1, "20/10/2026")] = _dia(10)
    agora = time.time()
    assert app._spv_hist_poda(agora=agora) == 0 and (1, "20/10/2026") in spv
    assert app._spv_hist_poda(agora=agora + app.SPV_HIST_OCIOSO_S + 1) == 1 and spv == {}


def test_teto_de_registros_tira_o_lido_ha_mais_tempo(spv, monkeypatch):
    monkeypatch.setattr(app, "SPV_HIST_TETO_REGISTROS", 40)
    agora = time.time()
    for i, atras in ((1, 300), (2, 200), (3, 10)):
        spv[(i, "20/10/2026")] = _dia(20)
        app._spv_hist_uso[(i, "20/10/2026")] = agora - atras
    assert app._spv_hist_poda(agora=agora, manter=(3, "20/10/2026")) == 1
    assert sorted(spv) == [(2, "20/10/2026"), (3, "20/10/2026")]          # 60 → 40 registros: sai o lido há mais tempo


def test_o_que_acabou_de_entrar_fica_mesmo_sozinho_acima_do_teto(spv, monkeypatch):
    monkeypatch.setattr(app, "SPV_HIST_TETO_REGISTROS", 40)
    spv[(9, "20/10/2026")] = _dia(50)
    assert app._spv_hist_poda(manter=(9, "20/10/2026")) == 0 and (9, "20/10/2026") in spv


class _RespCQ:
    status_code = 200
    text = ""

    def __init__(self, corpo):
        self._c = corpo

    def json(self):
        return self._c


class _CustomQuery:
    """O custom_query v2 de mentira: o dia de qualquer usina com `n` registros."""

    def __init__(self, n):
        self.n, self.pedidos = n, []

    def post(self, url, headers=None, json=None, timeout=None):
        self.pedidos.append((json["id"], json["day"]))
        return _RespCQ(_dia(self.n))


def test_a_busca_guarda_e_respeita_o_teto(spv, monkeypatch):
    """Na hora de guardar, não só a cada 10 min: três dias de usina grande seguidos não ficam todos na memória."""
    cq = _CustomQuery(20)
    monkeypatch.setattr(app, "_http", lambda: cq)
    monkeypatch.setattr(app, "_pv_cota_permite", lambda: True)
    monkeypatch.setattr(app, "_pv_cota_le", lambda r: None)
    monkeypatch.setattr(app, "SPV_HIST_TETO_REGISTROS", 40)
    for pid in (1, 2, 3):
        recs, motivo = app._spv_day_records_hist(pid, "tok", "21/10/2026")
        assert motivo is None and len(recs) == 20
        assert sum(len(v) for v in spv.values()) <= 40
    assert (3, "21/10/2026") in spv and (1, "21/10/2026") not in spv
    app._spv_day_records_hist(3, "tok", "21/10/2026")
    assert len(cq.pedidos) == 3                                          # o dia guardado não pede de novo


def test_no_maximo_tres_dias(spv):
    agora = time.time()
    for i in range(1, 5):
        spv[(i, "20/10/2026")] = _dia(1)
        app._spv_hist_uso[(i, "20/10/2026")] = agora - 100 + i
    app._spv_hist_poda(agora=agora)
    assert sorted(k[0] for k in spv) == [2, 3, 4]


# ── o dia de trackers da API PV no web (_pv_trk_dia_cache) ───────────────────────────────────────────────────────────
def test_no_web_o_dia_passado_de_tracker_tambem_tem_teto(api, monkeypatch):
    monkeypatch.setattr(app, "_MODO_WEB", True)
    monkeypatch.setattr(app, "PV_TRK_DIA_TETO_PONTOS", 3 * 40)        # 3 entradas de 4 trackers × 10 leituras
    for k in range(10, 1, -1):
        app._pv_trk_dia(1, _br(k), fetch=True)
        assert _pontos_passados() <= app.PV_TRK_DIA_TETO_PONTOS
    assert len(app._pv_trk_dia_cache) == 3


# ── quem roda as podas ───────────────────────────────────────────────────────────────────────────────────────────────
class _Para(BaseException):
    pass


def test_o_laco_do_web_poda_os_dois_antes_de_devolver_a_memoria(monkeypatch):
    ordem = []
    voltas = {"n": 0}

    class _Tempo:
        def __getattr__(self, nome):
            return getattr(time, nome)

        @staticmethod
        def sleep(_s):
            voltas["n"] += 1
            if voltas["n"] > 1:
                raise _Para()
    monkeypatch.setattr(app, "_pv_trk_dia_poda", lambda *a, **k: ordem.append("trackers") or 0)
    monkeypatch.setattr(app, "_spv_hist_poda", lambda *a, **k: ordem.append("strings") or 0)
    monkeypatch.setattr(app, "_devolve_memoria", lambda: ordem.append("devolve"))
    monkeypatch.setattr(app, "_relatorio_memoria_worker", lambda *a, **k: ordem.append("relatorio"))
    monkeypatch.setattr(app, "time", _Tempo())
    with pytest.raises(_Para):
        app._memoria_web_loop(intervalo=0)
    assert ordem == ["trackers", "strings", "devolve", "relatorio"]


def test_o_faxineiro_do_worker_poda_o_dia_de_strings(monkeypatch):
    chamado = []
    monkeypatch.setattr(app, "_spv_hist_poda", lambda *a, **k: chamado.append(1) or 2)
    assert "dia de strings da API PV:2" in app._janitor_passada() and chamado
