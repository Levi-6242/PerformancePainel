"""Resposta de ERRO da API PV não pode derrubar o PR por inversor inteiro.

Caso real (26/08): o cache `pv_pr` estava **9,8 dias** parado, servindo o payload de 16/08 21:35.
Causa: `UFV Tucano` (18758732) e `MORADA NOVA` (18766373) vêm da **2ª conta (OEM)** e entram na
lista de usinas, mas o `_pv_pr_collect` consulta com o token da conta PRINCIPAL — que não as
enxerga. O `/day_inverter` responde `{"error": "Invalid id, incident will be reported 2"}`, e
`for rec in recs` passou a iterar as CHAVES do dict (strings) em vez de registros:
`AttributeError: 'str' object has no attribute 'get'`. Como o fan-out fazia `raws.append(f.result())`
sem proteção, a exceção de UMA usina matava o build das 104.

Mesma blindagem que o SunOp já tem para o `/plants` ("se o token expirou, devolve um dict de erro
em vez da lista → não crashar"). Ver [[prewarm-falha-silenciosa-linha-incompleta]].
"""
import app


class _Resp:
    def __init__(self, payload): self._p = payload
    def json(self): return self._p


class _Sess:
    def __init__(self, payload): self._p = payload
    def post(self, *a, **k): return _Resp(self._p)
    def get(self, *a, **k): return _Resp([])


PLANTA = {"id": 18758732, "nome": "UFV Tucano"}


def _coleta(monkeypatch, payload):
    monkeypatch.setattr(app, "_http", lambda: _Sess(payload))
    return app._pv_pr_collect("tok", PLANTA)


def test_payload_de_erro_nao_levanta(monkeypatch):
    r = _coleta(monkeypatch, {"error": "Invalid id, incident will be reported 2"})
    assert r["invs"] == [] and r["stringbox"] is False
    assert r["plant_id"] == 18758732


def test_lista_de_strings_tambem_nao_levanta(monkeypatch):
    """Outra forma que a API já usou para reportar erro."""
    r = _coleta(monkeypatch, ["Invalid id"])
    assert r["invs"] == []


def test_resposta_legitima_continua_funcionando(monkeypatch):
    """Contraprova: a blindagem não pode engolir dado bom."""
    recs = [{"idefinversor": 1, "tsleitura_new": "2026-08-26 12:00:00", "eday": 10.0}]
    r = _coleta(monkeypatch, recs)
    assert r["plant_id"] == 18758732
    assert r["ts_max"] or r["invs"] is not None      # passou do guard, processou os registros
