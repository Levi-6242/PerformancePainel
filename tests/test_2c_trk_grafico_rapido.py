# -*- coding: utf-8 -*-
"""Gráfico de trackers da 2C (06/10/2026, Levi: "As curvas de trackers na 2C estão demorando muito — carrega carrega e
no final dá erro, na plataforma da PV Operation é diferente!", Sete Lagoas de 01 a 05/10).

Medido no servidor: pelo código do antigo e-mail (STL, o que a aba da 2C usa), UM dia passou de 600 s sem responder;
pelo id da API PV (18771901), 41 s. O gráfico de uma usina baixava, para cada dia, o dia inteiro das SEIS plantas da 2C
(Araputanga, Sete Lagoa, Tupi e as três da Ipixuna, 8 a 64 MB cada), e os dias iam um depois do outro — nos dois
caminhos. A tela desiste aos 90 s e dizia "Sem curva de trackers (...) esta fonte não reportou ângulos", que é falso.
"""
import threading
import time

import pytest

import app


def _dia_falso(pedidos, espera=0.0):
    def _f(pid, data_br, fetch=True):
        with threading.Lock():
            pedidos.append((pid, data_br))
        time.sleep(espera)
        return {"curva": {"TRK1": [{"x": data_br[6:] + "-" + data_br[3:5] + "-" + data_br[:2] + " 10:00:00", "y": 10.0}]},
                "alvo": {}, "ultima": {}, "ultima_ts": None}
    return _f


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    monkeypatch.setattr(app, "_2c_trk_api_memo", {})
    monkeypatch.setattr(app, "_trk_chart_aplica_status", lambda *a, **k: None)
    return app.app.test_client()


def test_grafico_de_uma_usina_da_2c_busca_so_a_planta_dela(cli, monkeypatch):
    pedidos = []
    monkeypatch.setattr(app, "_pv_trk_dia", _dia_falso(pedidos))
    r = cli.get("/api/owen/trackers/STL/chart?ini=2026-10-01&fim=2026-10-03")
    assert r.status_code == 200 and r.get_json()["trackers"][0]["id"] == "Tracker 1.1"
    assert {p for p, _ in pedidos} == {18771901}                          # só a Sete Lagoa
    assert sorted(d for _, d in pedidos) == ["01/10/2026", "02/10/2026", "03/10/2026"]


def test_ipixuna_busca_as_tres_ugs_e_nada_mais(cli, monkeypatch):
    pedidos = []
    monkeypatch.setattr(app, "_pv_trk_dia", _dia_falso(pedidos))
    cli.get("/api/owen/trackers/IPX/chart?ini=2026-10-01&fim=2026-10-01")
    assert {p for p, _ in pedidos} == {18771915, 18771929, 18771930}


def test_dias_do_intervalo_vao_em_paralelo_na_2c(cli, monkeypatch):
    pedidos = []
    monkeypatch.setattr(app, "_pv_trk_dia", _dia_falso(pedidos, espera=0.6))
    t = time.time()
    cli.get("/api/owen/trackers/STL/chart?ini=2026-10-01&fim=2026-10-05")
    assert len(pedidos) == 5 and time.time() - t < 2.0                    # em série seriam 3 s


def test_dias_do_intervalo_vao_em_paralelo_na_api_pv(cli, monkeypatch):
    pedidos = []

    def _graf(idusina, data_br, fetch=True):
        pedidos.append(data_br)
        time.sleep(0.6)
        return {"TRK1": [{"x": "2026-10-01T10:00:00", "y": 10.0}]}
    monkeypatch.setattr(app, "_pv_trk_grafico", _graf)
    t = time.time()
    r = cli.get("/api/2capi/trackers/18771901/chart?ini=2026-10-01&fim=2026-10-05")
    assert r.status_code == 200 and len(pedidos) == 5 and time.time() - t < 2.0


def test_busca_de_uma_usina_nao_vira_o_dia_inteiro_da_2c_no_memo(monkeypatch):
    """A aba, os parados e a ronda leem o dia inteiro pelo memo: o pedaço de uma usina não pode ser guardado nele."""
    monkeypatch.setattr(app, "_2c_trk_api_memo", {})
    monkeypatch.setattr(app, "_pv_trk_dia", _dia_falso([]))
    parcial = app._2c_trk_build_api("2026-10-01", codigos={"STL"})
    assert set(parcial) == {"STL"} and "2026-10-01" not in app._2c_trk_api_memo
    assert set(app._2c_trk_build_api("2026-10-01")) == {"ARA", "STL", "TUP", "IPX"}


def test_tela_diz_que_a_fonte_demorou_e_oferece_tentar_de_novo():
    from pathlib import Path
    html = (Path(app.__file__).resolve().parents[1] / "docs" / "redesign" / "Monitoramento (novo design).html"
            ).read_text(encoding="utf-8")
    assert "RD.trkChart[key]={erro:" in html
    assert "retryTrkChart" in html and "A fonte não respondeu a tempo" in html
