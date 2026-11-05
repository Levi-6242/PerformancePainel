# -*- coding: utf-8 -*-
"""A lista de usinas da Athon quando o catálogo da SunOp não vem (05/11/2026).

O caso: o catálogo inteiro do serviço de dados (/data/v2/metadata sem usina, 47 mil itens) passou a voltar 504 da
própria SunOp depois de ~90 s; a consulta por usina seguia 200. A cópia de 24 h da lista venceu às 00:44 e a Athon ficou
com ZERO usinas no tempo real (Levi: "a API do SunOp não está comunicando??"), e cada ciclo tentava o catálogo de novo.
Agora: a última lista boa vale sem prazo quando o catálogo falha, e a nova tentativa espera 30 min.
"""
import json
import time

import pytest

import app


class _R:
    def __init__(self, status, corpo=None):
        self.status_code, self._c = status, corpo

    def json(self):
        if self._c is None:
            raise ValueError("504 sem json")
        return self._c


@pytest.fixture
def catalogo(tmp_path, monkeypatch):
    arq = tmp_path / "sunop_plants_cache.json"
    monkeypatch.setattr(app, "_SUNOP_PLANTS_ARQ", str(arq))
    monkeypatch.setattr(app, "_SUNOP_CATALOGO_FALHOU", {})
    pedidos = []
    resposta = {"r": _R(504)}

    def _req(metodo, url, inst="gridco", **kw):
        pedidos.append(kw.get("params"))
        return resposta["r"]
    monkeypatch.setattr(app, "_sunop_req", _req)
    return {"arq": arq, "pedidos": pedidos, "resposta": resposta}


def _grava(arq, nomes, idade_s):
    arq.write_text(json.dumps({"gridco": {"nomes": nomes, "ts": time.time() - idade_s}}), encoding="utf-8")


def test_catalogo_504_usa_a_ultima_lista_boa_de_qualquer_idade(catalogo):
    _grava(catalogo["arq"], ["CPP100", "MTS100"], idade_s=3 * 86400)          # venceu há dias
    assert app._sunop_plants_do_dados("gridco") == ["CPP100", "MTS100"]
    assert len(catalogo["pedidos"]) == 1                                       # tentou o catálogo uma vez


def test_depois_da_falha_espera_30_min_sem_pedir_de_novo(catalogo):
    _grava(catalogo["arq"], ["CPP100"], idade_s=2 * 86400)
    app._sunop_plants_do_dados("gridco")
    app._sunop_plants_do_dados("gridco")
    app._sunop_plants_do_dados("gridco")
    assert len(catalogo["pedidos"]) == 1, "cada ciclo pedia o catálogo de novo: 90 s e uma requisição da cota"
    app._SUNOP_CATALOGO_FALHOU["gridco"] = time.time() - app.SUNOP_CATALOGO_ESPERA_S - 1
    app._sunop_plants_do_dados("gridco")
    assert len(catalogo["pedidos"]) == 2


def test_catalogo_que_volta_renova_a_lista(catalogo):
    _grava(catalogo["arq"], ["CPP100"], idade_s=2 * 86400)
    catalogo["resposta"]["r"] = _R(200, {"data": [{"plant": "CPP100"}, {"plant": "TIM200"}], "pages": 1})
    assert app._sunop_plants_do_dados("gridco") == ["CPP100", "TIM200"]
    assert json.loads(catalogo["arq"].read_text(encoding="utf-8"))["gridco"]["nomes"] == ["CPP100", "TIM200"]
    assert "gridco" not in app._SUNOP_CATALOGO_FALHOU


def test_sem_copia_em_disco_usa_o_inventario_das_fontes(catalogo, monkeypatch):
    class _Inv:
        def ler(self):
            return {"fontes": {app._sunop_fonte("gridco"): {"MTS200": {"nome": "MTS200"}, "CPP100": {"nome": "CPP100"}}}}
    monkeypatch.setattr(app, "_COB_INV", _Inv())
    assert app._sunop_plants_do_dados("gridco") == ["CPP100", "MTS200"]


def test_sem_lista_nenhuma_segue_vazio(catalogo, monkeypatch):
    class _Inv:
        def ler(self):
            return {"fontes": {}}
    monkeypatch.setattr(app, "_COB_INV", _Inv())
    assert app._sunop_plants_do_dados("gridco") == []                          # nunca inventa usina
