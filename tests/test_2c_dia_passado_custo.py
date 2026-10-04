# -*- coding: utf-8 -*-
"""Dia passado da 2C pela API PV: a Tupi Paulista e o custo de cada dia (04/10/2026).

Com o e-mail fora do código (03/10), o dia passado da 2C vem do histórico da API PV (custom_query). A conferência valor
a valor contra o e-mail de 02/10 não andou: a Tupi Paulista (18750925, 20 inversores) respondeu 400 nas 12 tentativas —
`{"error": "Resposta grande demais", "message": "... Consulte um período menor ou um único dispositivo (idinverter ou
device_id)."}`. Araputanga, no mesmo minuto: 200, 12.313 registros. Por inversor, a Tupi responde (1.440 registros),
mas o registro vem sem o `idefinversor`.

E o dia custa: 1 consulta da cota histórica por planta, 20 só da Tupi — ~25 por dia. A aba de falhas guardava o achado
dos dias fechados só na memória do worker: cada reinício (cada deploy) pediria o mês inteiro de novo.
"""
import json
import types

import pytest

import app
import falhas_job
import sol


class _R:
    def __init__(self, code, body):
        self.status_code = code
        self._b = body
        self.text = json.dumps(body)
        self.headers = {}

    def json(self):
        return self._b


GRANDE = {"error": "Resposta grande demais",
          "message": "O volume de dados passou do permitido. Consulte um período menor ou um único dispositivo "
                     "(idinverter ou device_id)."}


@pytest.fixture
def api_tupi(monkeypatch):
    pedidos, falha = [], set()

    def post(url, headers=None, json=None, timeout=None):
        inv = (json or {}).get("idinverter")
        pedidos.append(inv)
        if inv is None:
            return _R(400, GRANDE)
        if inv in falha:
            return _R(500, {"error": "interno"})
        return _R(200, [{"tsleitura_new": f"2026-10-02 10:0{i}:00", "idefinversor": None,
                         "conteudojson": '{"Ipv1": 8.1}'} for i in range(2)])

    monkeypatch.setattr(app, "_http", lambda: types.SimpleNamespace(post=post))
    monkeypatch.setattr(app, "_pv_cota_permite", lambda: True)
    monkeypatch.setattr(app, "_pv_cota_le", lambda r: None)
    monkeypatch.setattr(app, "_spv_hist_recs", {})
    monkeypatch.setitem(app.PV_INV_NOMES, 18750925, {367506: "Inversor 1.1", 367507: "Inversor 1.2"})
    return pedidos, falha


def test_usina_grande_demais_vai_por_inversor(api_tupi):
    pedidos, _ = api_tupi
    recs, motivo = app._spv_day_records_hist(18750925, "tok", "02/10/2026")
    assert motivo is None
    assert pedidos == [None, 367506, 367507]
    assert sorted({r["idefinversor"] for r in recs}) == [367506, 367507]      # o registro por inversor vem sem o id
    assert len(recs) == 4


def test_um_inversor_que_falha_nao_vira_dia_pela_metade(api_tupi):
    pedidos, falha = api_tupi
    falha.add(367507)
    recs, motivo = app._spv_day_records_hist(18750925, "tok", "02/10/2026")
    assert recs == [] and motivo == "http_500"
    assert app._spv_hist_recs == {}                                            # nada guardado: volta a pedir depois


def test_dia_fechado_da_2c_sobrevive_ao_reinicio(monkeypatch):
    """O achado de cada dia fechado vai para o disco (`_FALHAS_2C_PATH`): o worker novo não pede o dia de novo."""
    serie = [(f"{h:02d}:{m:02d}", 8.0) for h in range(7, 17) for m in (0, 10, 20, 30, 40, 50)]
    pedidos = []

    def hist(dia):
        pedidos.append(dia)
        return {"strings": {"TUP": {"1.1": {f"{i}": serie for i in range(1, 5)}}}}

    def monta():
        return falhas_job.montar(app, sol, "2026-09-01", "2026-09-02", geracao={}, str_store={}, trk_store={},
                                 book={}, hist_2c=hist, mortas_curva={}, log=lambda m: None)

    monkeypatch.setattr(falhas_job, "_CACHE_2C", {})
    monkeypatch.setattr(falhas_job, "_CACHE_2C_ARQ", {"path": None})
    monta()
    assert sorted(pedidos) == ["2026-09-01", "2026-09-02"]
    falhas_job._CACHE_2C.clear()                                              # o reinício: memória vazia
    falhas_job._CACHE_2C_ARQ["path"] = None
    pedidos.clear()
    monta()
    assert pedidos == []


def test_trava_nova_refaz_o_dia_guardado(monkeypatch):
    serie = [(f"{h:02d}:{m:02d}", 8.0) for h in range(7, 17) for m in (0, 10, 20, 30, 40, 50)]
    pedidos = []

    def hist(dia):
        pedidos.append(dia)
        return {"strings": {"TUP": {"1.1": {f"{i}": serie for i in range(1, 5)}}}}

    monkeypatch.setattr(falhas_job, "_CACHE_2C", {})
    monkeypatch.setattr(falhas_job, "_CACHE_2C_ARQ", {"path": None})
    falhas_job.montar(app, sol, "2026-09-01", "2026-09-01", geracao={}, str_store={}, trk_store={}, book={},
                      hist_2c=hist, mortas_curva={}, log=lambda m: None)
    monkeypatch.setattr(app, "_trancadas", set(app._trancadas) | {"TUP|1.1|3"})
    falhas_job._CACHE_2C.clear()
    falhas_job._CACHE_2C_ARQ["path"] = None
    pedidos.clear()
    falhas_job.montar(app, sol, "2026-09-01", "2026-09-01", geracao={}, str_store={}, trk_store={}, book={},
                      hist_2c=hist, mortas_curva={}, log=lambda m: None)
    assert pedidos == ["2026-09-01"]
