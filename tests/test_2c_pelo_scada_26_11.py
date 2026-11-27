# -*- coding: utf-8 -*-
"""A 2C pelo SCADA da Grid, com a API PV de reserva (Levi, 26/11/2026: "boa", à proposta de ligar o SCADA como fonte
principal da Araputanga e da Ipixuna do Pará). As leituras do supervisório viram registros do day_inverter com o id do
inversor da API PV; a API PV só entra quando o SCADA não responde ou não leu nada hoje."""
import json

import pytest

import app
import pv_scada as P
import scadagridco as SG


def _reg(eq, hora, pac, eday, strings, falha=192, ts=None):
    p = {"active_power": pac, "daily_active_energy": eday, "temperature_internal": 40.0}
    p.update({f"string_{n}_current": a for n, a in strings.items()})
    return {"equipamento": str(eq), "data_hora": f"2026-11-26 {hora}:00", "ts": ts or 1795700000 + int(hora[:2]) * 3600,
            "communication_fault": falha, "pontos": p}


def test_o_de_para_provado_pelo_valor():
    # a Araputanga FICA na API PV: o supervisório manda 20 entradas por inversor e ela tem ~24 strings (176 de 236 pelo
    # SCADA, 236 de 236 pela API PV em 26/11 às 13:00); a Ipixuna do Pará em três UGs, a 1 pulando 400841 e 400842
    assert 18771898 not in P.USINAS and P.ARAPUTANGA_FORA["equip"]["10"] == 400780
    sc1, sc2, sc3 = (P.USINAS[p]["equip"] for p in (18771915, 18771929, 18771930))
    assert sc1 == {"1": 400840, "2": 400843, "3": 400844, "4": 400845, "5": 400846, "6": 400847, "7": 400848, "8": 400849}
    assert sc2 == {str(9 + i): 400882 + i for i in range(6)} and sc3 == {str(15 + i): 400888 + i for i in range(6)}
    # todo inversor de cada usina é um id do de-para da API PV (PV_INV_NOMES), e nenhum equipamento se repete na Ipixuna
    for pid, cfg in P.USINAS.items():
        assert set(cfg["equip"].values()) <= set(app.PV_INV_NOMES[pid])
    assert len(set(sc1) | set(sc2) | set(sc3)) == 20


def test_as_leituras_viram_registros_do_day_inverter():
    regs = {"1": [_reg(1, "12:00", 174.2, 204.8, {1: 9.5, 2: 9.4, 14: 0.0}),
                  _reg(1, "12:00", 174.2, 204.8, {1: 9.5}),                  # o mesmo minuto duas vezes: um registro
                  _reg(1, "12:05", None, None, {1: 9.0}, falha=28)]}         # leitura ruim do gateway: lacuna
    r, = P.registros(regs, P.USINAS[18771915], SG.strings_de, SG.COM_OK)
    assert r["idefinversor"] == 400840 and r["tsleitura_new"] == "2026-11-26 12:00:00"
    assert json.loads(r["conteudojson"]) == {"Ipv1": 9.5, "Ipv2": 9.4, "Ipv14": 0.0, "Pac": 174.2, "Eday": 204.8, "Temp": 40.0}


@pytest.fixture
def scada(monkeypatch):
    pedidos = []
    leituras = {"1": [_reg(1, "12:00", 174.2, 204.8, {1: 9.5})], "2": [_reg(2, "12:00", 170.0, 200.0, {1: 9.1})]}

    def paginas(rota, params, getter):
        pedidos.append(dict(params))
        if leituras.get("erro"):
            raise SG.SemAcesso("scadaGridco recusou o token (HTTP 302)")
        return list(leituras.get(params["equipamento"]) or [])
    monkeypatch.setattr(SG, "configurado", lambda: True)
    monkeypatch.setattr(SG, "hoje", lambda: "2026-11-26")
    monkeypatch.setattr(SG, "_paginas", paginas)
    monkeypatch.setattr(app, "_PV_SG_REGS", {})
    monkeypatch.setattr(app, "_PV_SG_LOCKS", {})
    return pedidos, leituras


def test_o_dia_vem_do_scada_e_e_relido_so_no_que_chegou_depois(scada, monkeypatch):
    pedidos, leituras = scada
    recs = app._pv_scada_dia(18771915)
    assert {r["idefinversor"] for r in recs} == {400840, 400843} and len(pedidos) == 8       # um pedido por inversor
    assert all(p["apos_ts"] is None for p in pedidos)
    app._pv_scada_dia(18771915)
    assert len(pedidos) == 8                                    # dentro de PV_SG_RELER_S: a cópia
    monkeypatch.setattr(app, "PV_SG_RELER_S", 0)
    leituras["1"] = [_reg(1, "13:00", 250.2, 560.8, {1: 12.0})]
    recs = app._pv_scada_dia(18771915)
    assert pedidos[8]["apos_ts"] == 1795700000 + 12 * 3600        # só o que chegou depois da última leitura
    assert sorted(r["tsleitura_new"] for r in recs if r["idefinversor"] == 400840) == ["2026-11-26 12:00:00", "2026-11-26 13:00:00"]


def test_usina_fora_do_scada_ou_scada_fora_vai_a_api_pv(scada, monkeypatch):
    pedidos, leituras = scada
    assert app._pv_scada_dia(18771901) is None and not pedidos            # Sete Lagoas: não está no supervisório
    assert app._pv_scada_dia(18771898) is None and not pedidos            # Araputanga: fica na API PV
    leituras["erro"] = True
    assert app._pv_scada_dia(18771915) is None                           # o SCADA recusou: a reserva

    class _R:
        def json(self):
            return [{"idefinversor": 400840, "tsleitura_new": "2026-11-26 12:00:00", "conteudojson": "{}"}]
    chamadas = []
    monkeypatch.setattr(app, "_http", lambda: type("H", (), {"post": lambda s, *a, **k: chamadas.append(k) or _R()})())
    recs, via = app._pv_dia_do_inversor(18771915, "T", 45)
    assert via == "API PV" and len(chamadas) == 1 and recs[0]["idefinversor"] == 400840
    leituras.pop("erro")
    monkeypatch.setattr(app, "_PV_SG_REGS", {})
    recs, via = app._pv_dia_do_inversor(18771915, "T", 45)
    assert via == "scadaGridco" and len(chamadas) == 1                    # com o SCADA lendo, a API PV não é chamada


def test_o_scada_sem_leitura_nenhuma_hoje_vai_a_api_pv(scada):
    pedidos, leituras = scada
    leituras.clear()
    assert app._pv_scada_dia(18771915) is None
