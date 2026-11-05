# -*- coding: utf-8 -*-
"""O dia de trackers da API PV guardado compacto (auditoria do worker, 02/11/2026, achado 7).

O caso: o `_pv_trk_dia_cache` guardava cada leitura de cada tracker como um `{"x", "y"}` do Python, ~218 bytes por
ponto, e o dia de HOJE fica fora do teto de pontos de propósito. À noite o dia está completo: 3,9 milhões de pontos em
86 usinas em 11/10, ≈ 850 MB, o maior consumidor conhecido do worker (5,0 GB no Raio-X de 01/11). Guardado em vetores, o
ponto custa ~16 bytes; quem lê recebe a mesma curva de antes, montada na saída.
"""
import array
import sys
from datetime import datetime

import pytest

import app


def _dia(n_trk, n_leit, data_iso, buraco=None):
    """n_trk trackers × n_leit leituras; `buraco` = (tracker, leitura) sem posição (comunicação morta vira None)."""
    out = []
    for i in range(n_leit):
        h, m = 6 + i // 60, i % 60
        trks = []
        for t in range(n_trk):
            pos = None if buraco == (t, i) else float(t + i) / 3
            trks.append({f"TRK{t + 1}": {"posAg": pos, "posAl": float(t), "aComm": 0}})
        out.append({"tsleitura": f"{data_iso} {h:02d}:{m:02d}:00", "conteudojson": {"Trackers": trks}})
    return list(reversed(out))                      # a API devolve fora de ordem


class _Resp:
    status_code = 200

    def __init__(self, corpo):
        self._c = corpo

    def json(self):
        return self._c


class _ApiPV:
    def __init__(self, n_trk=4, n_leit=10, buraco=None):
        self.n_trk, self.n_leit, self.buraco, self.pedidos = n_trk, n_leit, buraco, []

    def corpo(self, data_br):
        iso = datetime.strptime(data_br, "%d/%m/%Y").strftime("%Y-%m-%d")
        return _dia(self.n_trk, self.n_leit, iso, self.buraco)

    def post(self, url, headers=None, json=None, timeout=None):
        self.pedidos.append((json["idusina"], json["date"]))
        return _Resp(self.corpo(json["date"]))


@pytest.fixture
def api(monkeypatch):
    s = _ApiPV()
    monkeypatch.setattr(app, "_http", lambda: s)
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "tok")
    monkeypatch.setattr(app, "_pv_trk_fora", lambda pid: pid == 2)     # a usina 2 é da 2C: guarda o alvo
    monkeypatch.setattr(app, "_pv_trk_dia_cache", {})
    monkeypatch.setattr(app, "_pv_trk_dia_locks", {})
    return s


def _bytes(obj, vistos=None) -> int:
    """Bytes de `obj` e de tudo o que ele guarda, contando cada objeto uma vez (o texto da hora é um só por leitura)."""
    vistos = set() if vistos is None else vistos
    if id(obj) in vistos:
        return 0
    vistos.add(id(obj))
    total = sys.getsizeof(obj)
    if isinstance(obj, dict):
        total += sum(_bytes(k, vistos) + _bytes(v, vistos) for k, v in obj.items())
    elif isinstance(obj, (list, tuple, set)):
        total += sum(_bytes(x, vistos) for x in obj)
    return total


HOJE = datetime.now().strftime("%d/%m/%Y")


def test_o_dia_guardado_ocupa_pouco_por_ponto(api):
    api.n_trk, api.n_leit = 20, 300                                   # 6.000 pontos
    app._pv_trk_dia(1, HOJE, fetch=True)
    ent = app._pv_trk_dia_cache[(1, HOJE)]
    por_ponto = _bytes(ent["d"]["curva"]) / ent["n"]
    assert ent["n"] == 6000
    assert por_ponto < 40, f"{por_ponto:.0f} bytes por ponto guardado (um dict por ponto dava ~218)"


@pytest.mark.parametrize("pid", [1, 2])                               # 2: a usina da 2C, com o alvo
def test_a_curva_servida_e_a_mesma_do_dia_cru(api, pid):
    api.buraco = (1, 3)                                               # o TRK2 sem posição na 4ª leitura
    esperado = app._pv_trk_parse_dia(api.corpo(HOJE), com_alvo=(pid == 2))
    assert esperado["curva"]["TRK2"][3]["y"] is None and (pid != 2 or esperado["alvo"])
    for vez in ("busca", "cache"):
        d = app._pv_trk_dia(pid, HOJE, fetch=True)
        for campo in ("curva", "alvo", "ultima", "ultima_ts"):
            assert d.get(campo) == esperado.get(campo), f"{campo} mudou na {vez}"
    assert app._pv_trk_dia(pid, HOJE, fetch=False)["curva"] == esperado["curva"]
    assert len(api.pedidos) == 1


def test_mexer_na_curva_servida_nao_muda_o_cache(api):
    d = app._pv_trk_dia(1, HOJE, fetch=True)
    d["curva"]["TRK1"].clear()
    assert app._pv_trk_dia(1, HOJE, fetch=True)["curva"]["TRK1"], "quem leu a curva esvaziou o cache"


def test_o_instantaneo_nao_monta_a_curva(api):
    """O overview e a ronda só querem a última leitura e se há curva: montar ~45 mil pontos por usina a cada volta, para
    jogar fora, era o mesmo lixo de memória que o compacto tira."""
    cheio = app._pv_trk_dia(1, HOJE, fetch=True)
    leve = app._pv_trk_dia(1, HOJE, fetch=True, curva=False)
    assert leve["ultima"] == cheio["ultima"] and leve["ultima_ts"] == cheio["ultima_ts"] and leve["curva"]
    assert not isinstance(next(iter(leve["curva"].values())), list), "curva=False montou a lista de pontos"
    assert isinstance(next(iter(app._pv_trk_dia_cache[(1, HOJE)]["d"]["curva"].values()))[1], array.array)
