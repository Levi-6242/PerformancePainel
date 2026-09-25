# -*- coding: utf-8 -*-
"""Falhas de strings e trackers — a montagem do mês (falhas_job.montar), sobre stores sintéticos (24/09/2026).

Cada teste trava uma regra que o Levi pediu ao ver o estudo:
- "se passou o dia com string nula e o dia acabou, então continua em aberto, teremos mais informações no outro
  dia" — sem notícia depois, o episódio segue EM ABERTO (antes virava "sem registro depois" e saía do filtro);
- a string que amanhece zerada continua o episódio da véspera (saiu / voltou atravessando a noite);
- só entra quem fica 2 h seguidas sem corrente;
- tracker que começa parado e vira atraso severo sai da visão; "parado" no alvo o episódio todo não é falha.
A usina é a Inhapi de verdade (cadastro local), para a perda sair com kWp e estado do sol reais.
"""
import pytest

import app
import falhas_job
import sol

PID = "18748739"          # Inhapi na API PV


def ev(st, caiu, voltou=None, inv="Inversor 3.3"):
    return {"inversor": inv, "string": st, "caiu": caiu, "voltou": voltou, "dur_min": 0, "gerando_agora": False}


def store(**por_dia):
    """store(d01=[eventos], d02=[...]) → o formato do perdas_strings.json, fonte API PV."""
    return {f"2026-09-{k[1:]}": {"pv": {PID: {"usina": "Inhapi", "ts": 0, "eventos": evs}}} for k, evs in por_dia.items()}


def monta(str_store, trk_store=None, fim="2026-09-03", pv_dev=None, agora=None):
    return falhas_job.montar(app, sol, "2026-09-01", fim, geracao={}, str_store=str_store, trk_store=trk_store or {},
                             book={}, hist_2c=lambda dia: {}, pv_dev=pv_dev, agora=agora, log=lambda m: None)


def episodios(p, string="Ipv1"):
    return [e for e in p["strings"]["episodios"] if e["string"] == string]


def test_string_que_termina_o_dia_zerada_e_some_do_registro_segue_em_aberto():
    st = store(d01=[ev("Ipv1", "08:00")])
    # o registro seguiu nos dias 02 e 03 (outra usina), mas esta não apareceu mais
    for d in ("2026-09-02", "2026-09-03"):
        st[d] = {"pv": {"999": {"usina": "Outra", "ts": 0, "eventos": [ev("Ipv9", "10:00", "13:00")]}}}
    (e,) = episodios(monta(st))
    assert e["fim"] is None and e["fim_motivo"] == "em aberto"
    assert "sem registro desde 01/09" in e["flags"]


def test_string_trancada_sai_mesmo_com_o_nome_do_dispositivo_em_outra_caixa(monkeypatch):
    # Indaiatuba, 25/09: trava 21480|378276|Ipv18; o plant_devices chama o 378276 de "INVERSOR 1.10" e a queda gravada
    # diz "Inversor 1.10". Comparando o nome exato, a trava não era conferida e 16 episódios da string trancada
    # apareciam na aba (o Levi viu). O nome vale normalizado, como no resto da plataforma.
    monkeypatch.setattr(app, "_trancadas", {f"{PID}|378276|Ipv1"})
    monkeypatch.setattr(app, "_TRANC_INV", {("378276", "Ipv1")})
    dev = {PID: {"names": {"378276": "INVERSOR 3.3"}, "nome_api": None, "usina": "Inhapi"}}
    p = monta(store(d01=[ev("Ipv1", "08:00", "12:00"), ev("Ipv2", "08:00", "12:00")]), pv_dev=dev)
    assert [e["string"] for e in p["strings"]["episodios"]] == ["Ipv2"]
    assert p["strings"]["qualidade"]["trancada: fora"] == 1


def test_trava_que_nao_da_para_conferir_fica_avisada_na_linha(monkeypatch):
    monkeypatch.setattr(app, "_trancadas", {f"{PID}|999|Ipv1"})
    (e,) = episodios(monta(store(d01=[ev("Ipv1", "08:00", "12:00")]), pv_dev={}))      # sem de-para da usina
    assert "trava não conferida (sem de-para)" in e["flags"]


def test_athon_inversor_sem_trava_nao_fica_como_trava_nao_conferida(monkeypatch):
    # MAB100 Inv 3.9, 25/09: a usina tem uma trava (no Inversor 2.3) e por isso toda queda dela ficava "trava não
    # conferida". Na Athon o nome da trava sai da mesma função que nomeia a queda: fora do mapa = sem trava.
    monkeypatch.setattr(app, "_trancadas", {"TIM100|INV_35|I_PV2"})
    st = {"2026-09-01": {"sunop": {"TIM100": {"usina": "TIM100", "ts": 0,
                                                "eventos": [ev("ST 01", "08:00", "12:00", inv="Inversor 3.5")]}}}}
    (e,) = monta(st)["strings"]["episodios"]
    assert not any("trava" in f for f in e["flags"])


def test_string_aberta_hoje_conta_ate_agora_e_nao_ate_as_18h():
    from datetime import datetime
    # às 10:00 de hoje, a string que caiu às 08:00 e não voltou soma 2 h — não as 10 h até as 18:00
    (e,) = episodios(monta(store(d03=[ev("Ipv1", "08:00")]), agora=datetime(2026, 9, 3, 10, 0)))
    assert e["fim"] is None and e["h_sol"] == pytest.approx(2.0, abs=0.2)


def test_tracker_parado_hoje_conta_ate_agora_e_nao_ate_as_18h():
    from datetime import datetime
    # 25/09, 10:21: os 405 trackers parados desde a manhã contavam até as 18:00 (~11 h cada) — 45 MWh a mais no dia
    t = trk(d03=("parado", 40.0))
    t["2026-09-03"][PID]["eventos"][0]["parada"] = "07:00"
    (r,) = monta({}, t, agora=datetime(2026, 9, 3, 10, 20))["trackers"]["rows"]
    assert r["fim"] is None and r["h_sol"] == pytest.approx(3.33, abs=0.1)


def test_amanheceu_zerada_continua_o_mesmo_episodio():
    (e,) = episodios(monta(store(d01=[ev("Ipv1", "10:00")], d02=[ev("Ipv1", "06:10", "11:00")])))
    assert (e["inicio"], e["fim"], e["dias"]) == ("2026-09-01 10:00", "2026-09-02 11:00", 2)


def test_voltou_de_madrugada_quando_a_usina_aparece_sem_a_string_zerada():
    # no dia 02 a usina está no registro (outra string caiu), mas a Ipv1 não amanheceu zerada
    (e,) = episodios(monta(store(d01=[ev("Ipv1", "10:00")], d02=[ev("Ipv2", "12:00", "15:00")])))
    assert e["fim_motivo"] == "voltou de madrugada" and e["fim"].startswith("2026-09-02 ")


def test_queda_de_menos_de_duas_horas_seguidas_nao_entra():
    p = monta(store(d01=[ev("Ipv1", "10:00", "11:30")]))
    assert episodios(p) == []
    assert p["strings"]["qualidade"]["descartado: menos de 2 h seguidas sem corrente"] == 1


def test_as_duas_visoes_de_strings_somam_o_mesmo_kwh():
    p = monta(store(d01=[ev("Ipv1", "10:00"), ev("Ipv2", "09:00", "13:00")], d02=[ev("Ipv1", "06:10", "11:00")]))
    kwh_ep = sum(e["perda_kwh"] for e in p["strings"]["episodios"])
    assert kwh_ep > 0
    assert sum(r["perda_kwh"] for r in p["strings"]["rows"]) == pytest.approx(kwh_ep, abs=0.2)


def trk(**por_dia):
    """trk(d01=(status, desvio), ...) → o formato do trk_eventos.json, um tracker só."""
    out = {}
    for k, (status, desvio) in por_dia.items():
        evs = [{"tracker": "TRK1", "parada": "08:00", "retorno": None, "desvio": desvio}] if status == "parado" else []
        out[f"2026-09-{k[1:]}"] = {PID: {"nome": "Inhapi", "cobertura": 1.0, "classes": {"TRK1": {"status": status}},
                                          "eventos": evs}}
    return out


def test_tracker_parado_que_vira_atraso_severo_sai_da_visao():
    (r,) = monta({}, trk(d01=("parado", 35.0), d02=("severo", None)))["trackers"]["rows"]
    assert r["fim"] is not None and r["fim"].startswith("2026-09-01 ")
    assert "saiu: severo" in r["flags"]


def test_depois_da_meia_noite_o_parado_de_ontem_segue_em_aberto():
    # 25/09, 00:33 no servidor: o período já ia até "hoje" (25/09, ainda sem dado) e todo tracker parado em 24/09
    # fechou como "sem dado depois" — 0 em aberto. O em aberto conta pelo último dia COM dado.
    (r,) = monta({}, trk(d01=("parado", 35.0), d02=("parado", 35.0)), fim="2026-09-03")["trackers"]["rows"]
    assert r["fim"] is None and "em aberto" in r["flags"]


def test_depois_da_meia_noite_a_string_zerada_de_ontem_segue_em_aberto_sem_aviso_de_sumico():
    (e,) = episodios(monta(store(d01=[ev("Ipv1", "08:00")], d02=[ev("Ipv1", "06:10")]), fim="2026-09-03"))
    assert e["fim"] is None and not any(f.startswith("sem registro desde") for f in e["flags"])


def test_tracker_parado_no_alvo_o_episodio_todo_nao_e_falha():
    p = monta({}, trk(d01=("parado", 0.4)))
    assert p["trackers"]["rows"] == []
    assert p["trackers"]["qualidade"]["descartado: no alvo o episódio todo (desvio < 2°)"] == 1


# ── a aba na plataforma: a tela abre e a API só LÊ o pacote que o worker publicou ─────────────
@pytest.fixture
def cliente(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "DASH_PASSWORD", "", raising=False)   # sem senha, o gate libera
    monkeypatch.setattr(app, "_falhas_arquivo", lambda mes: str(tmp_path / f"falhas_{mes}.json"))
    monkeypatch.setattr(app, "_falhas_mem", {})
    app.app.config["TESTING"] = True
    with app.app.test_client() as c:
        yield c, tmp_path


def test_a_tela_abre_debaixo_do_painel(cliente):
    c, _ = cliente
    r = c.get("/painel/falhas")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "/api/painel/falhas" in html and "{% raw %}" not in html     # o bloco raw do Jinja não vaza para a tela


def test_mes_sem_pacote_publicado_responde_frio_sem_calcular(cliente):
    c, _ = cliente
    j = c.get("/api/painel/falhas?mes=2026-09").get_json()
    assert j["quente"] is False and j["mes"] == "2026-09" and "2026-09" in j["meses"]


def test_mes_publicado_pelo_worker_e_servido_como_esta(cliente):
    c, pasta = cliente
    pacote = monta(store(d01=[ev("Ipv1", "08:00")]))
    app._falhas_publicar("2026-09", pacote)            # como o worker publica (o arquivo já é a resposta)
    j = c.get("/api/painel/falhas?mes=2026-09").get_json()
    assert j["quente"] is True
    assert j["strings"]["episodios"] == pacote["strings"]["episodios"]


def test_mes_invalido_e_recusado(cliente):
    c, _ = cliente
    assert c.get("/api/painel/falhas?mes=../../etc").status_code == 400


# ── o workbook falhas_performance: só o servidor grava, de hora em hora, e só quando o dado mudou ──────
import falhas_publicar


@pytest.fixture
def worker_wb(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "_falhas_arquivo", lambda mes: str(tmp_path / f"falhas_{mes}.json"))
    monkeypatch.setattr(app, "_falhas_wb", {"ts": 0.0, "marca": None})
    monkeypatch.setenv("GRIDCO_SQL_TOKEN", "tok-teste")
    chamadas = []
    monkeypatch.setattr(falhas_publicar, "sincronizar", lambda conteudo, **kw: chamadas.append(kw) or {"sheets": 4})
    app._falhas_publicar("2026-09", monta(store(d01=[ev("Ipv1", "08:00")])), ["2026-09"])
    return chamadas


def test_workbook_so_grava_com_a_chave_ligada(monkeypatch):
    # 25/09, 00:36: o registro de strings do SERVIDOR só tinha 22–24/09 (a plataforma foi para lá em 22/09) e o
    # replace=true trocaria a carga de setembro inteiro (7.419 linhas, do registro do PC) por 566 episódios. Até o
    # servidor ter o histórico, ninguém grava sozinho; e duas plataformas gravando trocariam de versão a cada hora.
    monkeypatch.delenv("FALHAS_WORKBOOK", raising=False)
    for nome in ("nt", "posix"):
        monkeypatch.setattr(app.os, "name", nome)
        assert app._falhas_workbook_ligado() is False
    monkeypatch.setenv("FALHAS_WORKBOOK", "1")
    assert app._falhas_workbook_ligado() is True


def test_workbook_sobe_uma_vez_por_hora_e_so_quando_o_dado_muda(monkeypatch, worker_wb):
    monkeypatch.setenv("FALHAS_WORKBOOK", "1")
    app._falhas_publicar_workbook(["2026-09"])
    assert len(worker_wb) == 1 and worker_wb[0]["token"] == "tok-teste"
    app._falhas_publicar_workbook(["2026-09"])                  # mesma hora: não sobe de novo
    assert len(worker_wb) == 1
    app._falhas_wb["ts"] = 0.0                                   # passou a hora, mas o dado é o mesmo
    app._falhas_publicar_workbook(["2026-09"])
    assert len(worker_wb) == 1


def test_workbook_desligado_nao_sobe(monkeypatch, worker_wb):
    monkeypatch.setenv("FALHAS_WORKBOOK", "0")
    app._falhas_publicar_workbook(["2026-09"])
    assert worker_wb == []
