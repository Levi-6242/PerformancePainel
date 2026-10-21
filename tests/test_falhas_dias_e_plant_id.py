# -*- coding: utf-8 -*-
"""O pacote da aba Strings e trackers para a tabela única (Levi, 20/10/2026).

- Trackers: cada parada ganha `dias` — o dia a dia que o falhas_job já calculava e jogava fora (a duração e a perda de
  cada dia), para o drill "acompanhamento diário" da parada de mais de um dia ("1.6 (...) ao clicar na linha abra um
  drill mostrando o acompanhamento diário e a duração"; "1.8 faça algo parecido com os trackers!"). Os dias somam a
  perda e as horas da linha, sem sobra de arredondamento. O dia em que o TRACKER ficou sem comunicação não entra (não
  conta perda); `comunicou` é da USINA no dia.
- Strings: a linha inversor × dia leva o `plant_id` (o drill casa o dia com a ocorrência por fonte + plant_id +
  inversor; cinco usinas têm mais de um cadastro).
- O workbook `falhas_performance` não muda: o falhas_publicar escreve colunas explícitas.
A usina é a Inhapi de verdade (cadastro local), como em test_falhas_job.py.
"""
import pytest

import app
import falhas_job
import falhas_publicar
import sol

PID = "18748739"          # Inhapi na API PV


def _monta(str_store=None, trk_store=None, fim="2026-09-04", geracao=None):
    return falhas_job.montar(app, sol, "2026-09-01", fim, geracao=geracao or {}, str_store=str_store or {},
                             trk_store=trk_store or {}, book={}, hist_2c=lambda dia: {}, mortas_curva={},
                             log=lambda m: None)


def _parado(dia, sc=None):
    ent = {"nome": "Inhapi", "cobertura": 1.0, "classes": {"TRK1": {"status": "parado"}},
           "eventos": [{"tracker": "TRK1", "parada": "08:00", "retorno": None, "desvio": 35.0}]}
    if sc is not None:
        ent["sem_comunicacao"] = sc
        ent["eventos"] = []
    return {f"2026-09-{dia}": {PID: ent}}


# A geração diz quem comunicou: a Inhapi gerou no dia 01 ("sim"); a frota tem geração até o dia 03 (GER_ATE), então os
# dias 02 e 03 da Inhapi sem geração estão FECHADOS sem prova ("sem comunicação"); o 04 ainda não fechou ("sem prova")
GERACAO = {"Inhapi": {"kwp": 1000.0, "dias": {"2026-09-01": 5000.0}},
           "Outra Usina": {"kwp": 100.0, "dias": {"2026-09-03": 400.0}}}


@pytest.fixture
def frota20(monkeypatch):
    """O cadastro de trackers da Inhapi (BD_Trackers) com 20 trackers no Inversor 3.3: o kWp do tracker sai do cadastro."""
    monkeypatch.setitem(app.BD_TRK_INV, app._nome_base("Inhapi"), {i: "Inversor 3.3" for i in range(1, 21)})


def test_os_dias_da_parada_somam_a_perda_e_as_horas_da_linha(frota20):
    t = {**_parado("01"), **_parado("02"), **_parado("03"), **_parado("04")}
    (r,) = _monta(trk_store=t, geracao=GERACAO)["trackers"]["rows"]
    assert [d[0] for d in r["dias"]] == ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"]
    assert all(len(d) == 6 and d[1] == "08:00" and isinstance(d[3], float) for d in r["dias"])
    assert r["perda_kwh"] > 0
    # repartidos pelas somas acumuladas: nenhum 0,1 kWh sobrando entre o drill e a linha
    assert round(sum(d[4] for d in r["dias"]), 1) == r["perda_kwh"]
    assert round(sum(d[3] for d in r["dias"]), 2) == r["h_sol"]
    assert all(abs(d[3] - round(d[3], 2)) < 1e-9 and abs(d[4] - round(d[4], 1)) < 1e-9 for d in r["dias"])
    # a usina: gerou no 01; 02 e 03 fechados sem prova nenhuma; o 04 a geração ainda não cobre
    assert [d[5] for d in r["dias"]] == ["sim", "sem comunicação", "sem comunicação", "sem prova"]
    assert (r["dias_comunicou"], r["dias_sem_prova"]) == (1, 1)


def test_dia_em_que_o_tracker_ficou_sem_comunicacao_nao_entra_no_dia_a_dia(frota20):
    # parado no 01 e no 02; sem comunicação no 03 (não conta perda: atravessa); parado de novo no 04
    t = {**_parado("01"), **_parado("02"), **_parado("03", sc=["TRK1"]), **_parado("04")}
    (r,) = _monta(trk_store=t, geracao=GERACAO)["trackers"]["rows"]
    assert [d[0] for d in r["dias"]] == ["2026-09-01", "2026-09-02", "2026-09-04"]
    assert "sem comunicação em parte do episódio" in r["flags"]
    assert round(sum(d[4] for d in r["dias"]), 1) == r["perda_kwh"]
    assert [d[5] for d in r["dias"]] == ["sim", "sem comunicação", "sem prova"]


def test_parada_de_um_dia_tem_um_dia_e_a_reparticao_fecha_com_muitos_dias():
    assert falhas_job._reparte([0.04, 0.04, 0.04], 1) == [0.0, 0.1, 0.0]      # 0,12 → 0,1: os três somam o total
    vals = [123.456, 0.049, 77.777, 0.051, 10.0] * 7
    rep = falhas_job._reparte(vals, 1)
    assert round(sum(rep), 1) == round(sum(vals), 1) and all(abs(a - b) <= 0.1 + 1e-9 for a, b in zip(rep, vals))


def test_o_dia_a_dia_dos_trackers_nao_vai_ao_workbook(frota20):
    t = {**_parado("01"), **_parado("02")}
    p = _monta(trk_store=t, geracao=GERACAO)
    assert p["trackers"]["rows"][0]["dias"]
    tabs = falhas_publicar.tabelas([dict(p, mes="2026-09")])
    (lin,) = tabs["trackers_episodios"]
    assert len(lin) == len(falhas_publicar.CABECALHOS["trackers_episodios"])
    assert not any(isinstance(v, list) or (isinstance(v, str) and "2026-09-02" in v and "08:00" in v) for v in lin)


# ── strings: o plant_id na linha inversor × dia ──────────────────────────────────────────────────────────────────────
def _ev(st, caiu, voltou, inv="Inversor 3.3"):
    return {"inversor": inv, "string": st, "caiu": caiu, "voltou": voltou, "dur_min": 0, "gerando_agora": False}


def test_a_linha_do_dia_leva_o_plant_id_do_cadastro():
    st = {"2026-09-01": {"pv": {PID: {"usina": "Inhapi", "ts": 0, "eventos": [_ev("Ipv1", "08:00", "12:00")]}}}}
    p = _monta(str_store=st, fim="2026-09-01")
    (row,) = p["strings"]["rows"]
    (ep,) = p["strings"]["episodios"]
    assert row["plant_id"] == ep["plant_id"] == PID and "cadastros" not in row


def test_dois_cadastros_com_o_mesmo_inversor_no_dia_levam_a_linha_de_cada_um():
    # Nos stores do PC de 20/10, a Itajá (18749574 e 18749576) tem INVERSOR01 a 04 nos dois cadastros. A linha do dia
    # segue sendo usina × inversor × dia — o grão da strings_inversor_dia (chave do catálogo: fonte, usina, inversor, dia),
    # que não muda — e diz que é de dois cadastros: plant_id None e a linha de cada um em `cadastros`, para o drill não
    # mandar a perda de um para a ocorrência do outro
    st = {"2026-09-01": {"pv": {PID: {"usina": "Inhapi", "ts": 0, "eventos": [_ev("Ipv1", "08:00", "12:00")]},
                                "18748740": {"usina": "Inhapi", "ts": 0, "eventos": [_ev("Ipv1", "09:00", "13:00")]}}}}
    p = _monta(str_store=st, fim="2026-09-01")
    (row,) = p["strings"]["rows"]
    assert row["plant_id"] is None and (row["inversor"], row["qtd"]) == ("Inversor 3.3", 1)
    cads = sorted(row["cadastros"], key=lambda c: c["plant_id"])
    assert [(c["plant_id"], c["inversor"], c["qtd"], c["strings"]) for c in cads] == [
        (PID, "Inversor 3.3", 1, "Ipv1"), ("18748740", "Inversor 3.3", 1, "Ipv1")]
    por_pid = {e["plant_id"]: e["perda_kwh"] for e in p["strings"]["episodios"]}
    assert {c["plant_id"]: c["perda_kwh"] for c in cads} == por_pid
    assert abs(sum(c["perda_kwh"] for c in cads) - row["perda_kwh"]) <= 0.1 + 1e-9         # cada uma arredondada
    # o workbook: uma linha só, com as colunas de sempre (sem plant_id na strings_inversor_dia)
    tabs = falhas_publicar.tabelas([dict(p, mes="2026-09")])
    assert "plant_id" not in falhas_publicar.CABECALHOS["strings_inversor_dia"]
    (lin,) = tabs["strings_inversor_dia"]
    assert len(lin) == len(falhas_publicar.CABECALHOS["strings_inversor_dia"])
