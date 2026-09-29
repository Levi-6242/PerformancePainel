# -*- coding: utf-8 -*-
"""Backfill da curva de strings da API PV para o registro da aba de falhas (29/09/2026, Levi, com print da Rodrigues 2.1:
"veja se ocorre com mais usinas da Thopen e resolva"). A queda gravada da API PV depois do fim do dia vinha da potência
da PV Plataforma e acusava string gerando (Rodrigues 2.1, 10/09: Ipv13 a Ipv23 com 9-14 A ao meio-dia); a aba não a conta
mais, e a usina-dia ganha aqui a régua sobre a CORRENTE do dia. A cota de consultas históricas é da conta (800/dia): o
backfill para na reserva, não repete usina-dia e começa pela que tinha queda gravada."""
import json
import math
import time
from datetime import date, datetime

import pytest

import app

PA, PB = "111", "222"


def _curvas(morta):
    """Três strings num inversor, de 10 em 10 min: sino de 9 A de pico; a Ipv3 da usina B lê 0 se `morta`."""
    out = {}
    for st in ("Ipv1", "Ipv2", "Ipv3"):
        serie = []
        for m in range(6 * 60, 18 * 60 + 1, 10):
            v = 0.0 if (morta and st == "Ipv3") else round(max(0.0, 9 * math.sin(math.pi * (m - 360) / 720)), 2)
            serie.append((f"{m // 60:02d}:{m % 60:02d}", v))
        out[st] = serie
    return {"Inversor 1": out}


@pytest.fixture
def pv(monkeypatch, tmp_path):
    """Duas usinas da API PV (a B com a Ipv3 morta), a API falsa e o registro num arquivo à parte."""
    chamadas, motivo = [], {}

    def hist(idusina, token, data):
        chamadas.append((str(idusina), data))
        m = motivo.get((str(idusina), data)) or motivo.get(str(idusina))
        if m:
            return [], m
        return [{"curvas": _curvas(str(idusina) == PB)}], None

    monkeypatch.setattr(app, "get_token", lambda *a, **k: "tok")
    monkeypatch.setattr(app, "get_plants", lambda *a, **k: [{"id": int(PA), "nome": "Usina A (1)"},
                                                            {"id": int(PB), "nome": "Usina B (2)"}])
    monkeypatch.setattr(app, "FULL_OM", set())
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "tok")
    monkeypatch.setattr(app, "_spv_day_records_hist", hist)
    monkeypatch.setattr(app, "_pv_curvas_strings_de", lambda recs, pid, nome, tok: recs[0]["curvas"])
    monkeypatch.setattr(app, "nome_usina", lambda pid, nome: nome.split(" (")[0])
    monkeypatch.setattr(app, "_macro_usina_nome", lambda nome: None)
    monkeypatch.setattr(app, "_trancadas", set())
    monkeypatch.setattr(app, "_perdas_str", {})
    monkeypatch.setattr(app, "_pv_cota", {"dia": None, "hora": None, "ts": 0.0, "zerada_ate": 0.0})
    monkeypatch.setattr(app, "_FALHAS_STR_PATH", str(tmp_path / "falhas_strings.json"))
    monkeypatch.setattr(app, "FALHAS_BF_PV_ESTADO", str(tmp_path / "falhas_backfill_pv.json"))
    monkeypatch.setattr(app, "_FALHAS_MORTAS", {})
    monkeypatch.setattr(app, "FALHAS_BF_PV_PAUSA_S", 0)
    return {"chamadas": chamadas, "motivo": motivo, "reg": tmp_path / "falhas_strings.json"}


def _reg(s):
    return json.loads(s["reg"].read_text(encoding="utf-8"))


def _ts(dia, hh):
    return datetime.strptime(f"{dia} {hh}", "%Y-%m-%d %H:%M").timestamp()


def test_backfill_da_api_pv_grava_a_regua_sobre_a_corrente_dos_dias_que_faltam(pv):
    n = app._falhas_backfill_pv(hoje=date(2026, 9, 4))
    reg = _reg(pv)
    assert n == 6 and sorted(reg) == ["2026-09-01", "2026-09-02", "2026-09-03"]
    ent = reg["2026-09-03"]["pv"][PB]
    assert ent["origem"] == "backfill" and ent["usina"] == "Usina B" and ent["vivas"] == {"Inversor 1": 2}
    (m,) = ent["mortas"]
    assert m["string"] == "Ipv3" and m["voltou"] is None
    assert not reg["2026-09-03"]["pv"][PA]["mortas"]


def test_primeiro_a_usina_dia_que_tinha_queda_gravada(pv, monkeypatch):
    # a aba deixou de contar essa queda (potência da PV Plataforma): é a usina-dia que ficou sem nada
    monkeypatch.setattr(app, "_perdas_str", {"2026-09-01": {"pv": {PA: {"usina": "Usina A", "ts": 0,
                                                                        "eventos": [{"string": "Ipv13"}]}}}})
    app._falhas_backfill_pv(hoje=date(2026, 9, 4), maximo=1)
    assert pv["chamadas"] == [(PA, "01/09/2026")]


def test_depois_vai_do_dia_mais_recente_para_tras(pv):
    app._falhas_backfill_pv(hoje=date(2026, 9, 4), maximo=2)
    assert [d for _, d in pv["chamadas"]] == ["03/09/2026", "03/09/2026"]


def test_para_na_reserva_da_cota_do_dia(pv, monkeypatch):
    # a coleta da noite e a combiner gastam a MESMA cota da conta: abaixo da reserva o backfill não pede nada
    monkeypatch.setattr(app, "_pv_cota", {"dia": app.FALHAS_BF_PV_RESERVA_DIA - 1, "hora": 150, "ts": time.time(),
                                          "zerada_ate": 0.0})
    assert app._falhas_backfill_pv(hoje=date(2026, 9, 4)) == 0 and pv["chamadas"] == []


def test_para_na_reserva_da_cota_da_hora(pv, monkeypatch):
    monkeypatch.setattr(app, "_pv_cota", {"dia": 700, "hora": app.FALHAS_BF_PV_RESERVA_HORA - 1, "ts": time.time(),
                                          "zerada_ate": 0.0})
    assert app._falhas_backfill_pv(hoje=date(2026, 9, 4)) == 0 and pv["chamadas"] == []


def test_cota_estourada_para_a_passada_e_a_usina_dia_volta_na_seguinte(pv):
    pv["motivo"][(PB, "03/09/2026")] = "cota_api"         # o 1º da fila: dia 03, a usina B
    app._falhas_backfill_pv(hoje=date(2026, 9, 4))
    assert len(pv["chamadas"]) == 1                  # parou no 1º pedido, sem marcar
    pv["motivo"].clear()
    assert app._falhas_backfill_pv(hoje=date(2026, 9, 4)) == 6


def test_usina_dia_sem_leitura_na_api_nao_ganha_registro_nem_volta_a_api(pv):
    pv["motivo"][PA] = "sem_dados_api"
    app._falhas_backfill_pv(hoje=date(2026, 9, 4))
    assert all(PA not in (fs.get("pv") or {}) for fs in _reg(pv).values())
    n_antes = len(pv["chamadas"])
    assert app._falhas_backfill_pv(hoje=date(2026, 9, 4)) == 0
    assert len(pv["chamadas"]) == n_antes


def test_nao_pisa_no_registro_completo_nem_refaz_a_regua_anterior(pv):
    # completo = avaliado depois das 18h, com as vivas; a régua anterior (sem "regua") NÃO refaz: cada usina-dia custa
    # uma consulta da cota da conta
    pv["reg"].write_text(json.dumps({"2026-09-03": {"pv": {PA: {"usina": "Usina A", "ts": _ts("2026-09-03", "23:50"),
                                                                "mortas": [], "vivas": {"Inversor 1": 3}}}}}),
                         encoding="utf-8")
    app._falhas_backfill_pv(hoje=date(2026, 9, 4))
    assert (PA, "03/09/2026") not in pv["chamadas"]
    assert _reg(pv)["2026-09-03"]["pv"][PA]["ts"] == _ts("2026-09-03", "23:50")


def test_refaz_o_registro_parcial(pv):
    pv["reg"].write_text(json.dumps({"2026-09-03": {"pv": {PA: {"usina": "Usina A", "ts": _ts("2026-09-03", "12:00"),
                                                                "mortas": [], "vivas": {"Inversor 1": 3}}}}}),
                         encoding="utf-8")
    app._falhas_backfill_pv(hoje=date(2026, 9, 4))
    assert _reg(pv)["2026-09-03"]["pv"][PA]["origem"] == "backfill"


def test_nunca_toca_hoje(pv):
    app._falhas_backfill_pv(hoje=date(2026, 9, 2))
    assert {d for _, d in pv["chamadas"]} == {"01/09/2026"}


def test_so_uma_plataforma_gasta_a_cota(monkeypatch):
    monkeypatch.setenv("FALHAS_BF_PV", "0")
    assert app._falhas_bf_pv_ligado() is False
    monkeypatch.setenv("FALHAS_BF_PV", "1")
    assert app._falhas_bf_pv_ligado() is True


def test_o_laco_do_backfill_da_api_pv_roda_no_worker():
    assert "_falhas_backfill_pv_loop" in app._iniciar_loops_de_fundo.__code__.co_names
