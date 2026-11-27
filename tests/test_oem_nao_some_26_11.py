# -*- coding: utf-8 -*-
"""A 2C, a SEMP e a Alves Lima não somem da Sala de controle com a API PV lenta (26/11/2026).

Com a API PV a 55 s por login, a lista de usinas da conta OEM não vinha, a `get_plants` guardava 5 min a lista só com a
Thopen, a tabela das três fontes da conta OEM saía VAZIA por cima da última boa e elas sumiam da Sala (Levi: "É sempre
para mostrar. O que a gente já teve dado"). Agora vale a última lista boa da conta OEM (ou as usinas da última leitura) e
a tabela da fonte nunca sai vazia por cima da última leitura: fica a linha histórica, com o "sem comunicação"."""
import pytest

import app

MORADA = {"usina": "Morada Nova", "plant_id": 18766373, "nome_api": "Morada Nova", "strings_ativas": 128,
          "ultima_leitura": "2026-11-26 13:28:00", "sem_dados": False, "falha_comunicacao": False}


class _Resp:
    def __init__(self, dado):
        self.dado = dado

    def json(self):
        return self.dado


class _Http:
    """A API PV de mentira: a conta principal responde; a OEM responde, falha ou devolve vazio."""

    def __init__(self, oem):
        self.oem = oem

    def get(self, url, headers=None, timeout=None):
        if (headers or {}).get("x-access-token") == "OEM":
            if isinstance(self.oem, Exception):
                raise self.oem
            return _Resp(self.oem)
        return _Resp([{"id": 1, "nome": "Altair 1"}])


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(app, "PV_OEM_USERNAME", "oem")
    monkeypatch.setattr(app, "get_token_oem", lambda: "OEM")
    monkeypatch.setattr(app, "_pv_nome_do_cadastro", lambda d: d)
    monkeypatch.setattr(app, "_last_known", {})

    def usar(oem, cache=None):
        monkeypatch.setattr(app, "_plants_cache", dict({"ts": 0.0, "data": None}, **(cache or {})))
        monkeypatch.setattr(app, "_http", lambda: _Http(oem))
        return app.get_plants("PRINCIPAL")
    return usar


def test_a_lista_da_conta_oem_que_vem_e_guardada(api):
    ps = api([{"id": 18766373, "nome": "Morada Nova"}, {"id": 999, "nome": "de fora"}])
    assert [p["id"] for p in ps] == [1, 18766373] and app._plants_cache["oem"] == [{"id": 18766373, "nome": "Morada Nova"}]


def test_a_lista_da_conta_oem_que_nao_vem_usa_a_ultima_boa(api):
    ps = api(TimeoutError("55 s"), {"oem": [{"id": 18766373, "nome": "Morada Nova"}]})
    assert [p["id"] for p in ps] == [1, 18766373]
    # a resposta vazia (a API devolveu [] ou um erro em JSON) também não vale como lista
    assert [p["id"] for p in api([], {"oem": [{"id": 18766373, "nome": "Morada Nova"}]})] == [1, 18766373]
    assert [p["id"] for p in api({"message": "erro"}, {"oem": [{"id": 18766373, "nome": "Morada Nova"}]})] == [1, 18766373]


def test_sem_lista_guardada_valem_as_usinas_da_ultima_leitura(api, monkeypatch):
    monkeypatch.setattr(app, "_last_known", {18766373: dict(MORADA), 1: {"usina": "Altair 1"}})
    ps = api(TimeoutError("55 s"))
    assert ps == [{"id": 1, "nome": "Altair 1"}, {"id": 18766373, "nome": "Morada Nova"}]


def test_a_tabela_da_fonte_nao_sai_vazia_por_cima_da_ultima_leitura(monkeypatch):
    monkeypatch.setattr(app, "_last_known", {18766373: dict(MORADA)})
    monkeypatch.setattr(app, "fetch_all", lambda fonte=None: [])
    p = app._build_data_payload("alveslima")
    r, = p["rows"]
    assert r["usina"] == "Morada Nova" and r["dado_historico"] and r["falha_comunicacao"] and r["strings_ativas"] == 128
    assert p["alertas_comm_list"] == [{"usina": "Morada Nova", "ultima_leitura": "2026-11-26 13:28:00"}]
    # a principal (Thopen) segue como sempre: sem usina na lista, sem linha
    assert app._build_data_payload(None)["rows"] == []


def test_a_lista_da_conta_oem_vai_para_o_disco_e_volta(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "_PERSIST_PATH", str(tmp_path / "snap.json"))
    monkeypatch.setattr(app, "_plants_cache", {"ts": 0.0, "data": None, "oem": [{"id": 18766373, "nome": "Morada Nova"}]})
    app._cache_save()
    monkeypatch.setattr(app, "_plants_cache", {"ts": 0.0, "data": None})
    app._cache_load()
    assert app._plants_cache["oem"] == [{"id": 18766373, "nome": "Morada Nova"}]
