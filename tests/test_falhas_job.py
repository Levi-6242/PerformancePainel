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


def monta(str_store, trk_store=None, fim="2026-09-03"):
    return falhas_job.montar(app, sol, "2026-09-01", fim, geracao={}, str_store=str_store, trk_store=trk_store or {},
                             book={}, hist_2c=lambda dia: {}, log=lambda m: None)


def episodios(p, string="Ipv1"):
    return [e for e in p["strings"]["episodios"] if e["string"] == string]


def test_string_que_termina_o_dia_zerada_e_some_do_registro_segue_em_aberto():
    (e,) = episodios(monta(store(d01=[ev("Ipv1", "08:00")])))
    assert e["fim"] is None and e["fim_motivo"] == "em aberto"
    assert "sem registro desde 01/09" in e["flags"]


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
