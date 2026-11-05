# -*- coding: utf-8 -*-
"""De noite o dia de trackers de hoje não é baixado de novo a cada 30 min (auditoria do worker, 02/11/2026, achado 9).

O caso: a validade do dia de hoje (`TRK_DIA_TTL`, 30 min) valia as 24 h. Das 19h à meia-noite, com os trackers em
repouso, o `_pv_trk_loop` e a aba da 2C baixavam o dia inteiro de novo a cada 30 min: ~10 vezes por usina, 8,8 a 13,8 MB
cada, ~7 a 11 GB por noite da API PV, e cada busca virava dezenas de MB de objetos que morriam em seguida. Agora: 30 min
de dia (06h às 19h) e na última hora (23h, para o dia fechar completo como antes, a no máximo 30 min da meia-noite); fora
disso, a validade da noite da combiner (`PV_COMB_TTL_NOITE_S`).
"""
import time
from datetime import datetime

import pytest

import app


class _Resp:
    status_code = 200

    def __init__(self, corpo):
        self._c = corpo

    def json(self):
        return self._c


class _ApiPV:
    def __init__(self):
        self.pedidos = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.pedidos.append(json["date"])
        iso = datetime.strptime(json["date"], "%d/%m/%Y").strftime("%Y-%m-%d")
        return _Resp([{"tsleitura": f"{iso} 10:00:00", "conteudojson": {"Trackers": [{"TRK1": {"posAg": 1.0}}]}}])


def _relogio(monkeypatch, hora):
    real = datetime

    class _Agora(real):
        @classmethod
        def now(cls, tz=None):
            return real.now(tz).replace(hour=hora, minute=10)

    monkeypatch.setattr(app, "datetime", _Agora)
    return _Agora.now().strftime("%d/%m/%Y")


@pytest.fixture
def api(monkeypatch):
    s = _ApiPV()
    monkeypatch.setattr(app, "_http", lambda: s)
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "tok")
    monkeypatch.setattr(app, "_pv_trk_fora", lambda pid: False)
    monkeypatch.setattr(app, "_pv_trk_dia_cache", {})
    monkeypatch.setattr(app, "_pv_trk_dia_locks", {})
    return s


@pytest.mark.parametrize("hora, idade_s, busca_de_novo", [
    (20, 3600, False),            # de noite: uma hora depois, o mesmo dia
    (3, 3600, False),             # de madrugada: o dia novo é repouso
    (10, 31 * 60, True),          # de dia: 30 min, como sempre
    (23, 31 * 60, True),          # a última hora: o dia fecha completo, como antes
])
def test_a_validade_do_dia_de_hoje_pela_hora(api, monkeypatch, hora, idade_s, busca_de_novo):
    hoje = _relogio(monkeypatch, hora)
    app._pv_trk_dia(1, hoje, fetch=True)
    app._pv_trk_dia_cache[(1, hoje)]["ts"] = time.time() - idade_s
    app._pv_trk_dia(1, hoje, fetch=True)
    assert len(api.pedidos) == (2 if busca_de_novo else 1)
