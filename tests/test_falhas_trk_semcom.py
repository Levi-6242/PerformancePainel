# -*- coding: utf-8 -*-
"""Tracker sem comunicação não entra na aba de falhas (Levi, 01/10/2026: "alguns trackers estão como 'parados' porém
ficaram sem comunicação, não quero esses trackers no relatório").

Desde 08/09 o tracker sem comunicação travado num ângulo conta como parado no tempo real (_trk_promove_semcom) e o
registro do dia guardava só "parado", sem a marca: setembro no PC tinha 5.597 tracker-dias parados de 559 trackers sem
comunicação (Santa Bárbara I, TIM100, Barretos...), 1.065 → 738 MWh. O registro passa a guardar quem estava
sem comunicação (a régua da etiqueta roxa do tempo real, _trk_semcom_set); para os dias de antes vale a marca das rondas
(trackers_parados_hist).
"""
import json

import pytest

import app
import falhas_job
import sol

PID = "18748739"          # Inhapi na API PV (cadastro real, como em test_falhas_job.py)
P = {"status": "parado"}


def _hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def _curva_dia():
    """Seis trackers girando de −50° a +50° das 06:00 às 18:00, um com o sensor morto (0,00° o dia todo) e um que parou de
    reportar às 10:00 com a frota seguindo."""
    def giro(m):
        return round(-50 + 100 * (m - 360) / 720, 1)
    pts = range(6 * 60, 18 * 60 + 1, 5)
    g = {f"TRK{i}": [{"x": f"2026-09-29T{_hhmm(m)}:00", "y": giro(m)} for m in pts] for i in range(1, 7)}
    g["TRK7"] = [{"x": f"2026-09-29T{_hhmm(m)}:00", "y": 0.0} for m in pts]
    g["TRK8"] = [{"x": f"2026-09-29T{_hhmm(m)}:00", "y": giro(m)} for m in pts if m <= 10 * 60]
    return g


def test_registro_do_dia_guarda_quem_estava_sem_comunicacao():
    res = app._trk_eventos_do_dia("8", "Aparecida 3", "29/09/2026", curve=_curva_dia())
    assert res["sem_comunicacao"] == ["TRK7", "TRK8"]


def _dia(d, classes, eventos=(), sc=None, nome="Inhapi"):
    ent = {"nome": nome, "cobertura": 1.0, "classes": classes, "eventos": list(eventos)}
    if sc is not None:
        ent["sem_comunicacao"] = sc
    return {f"2026-09-{d}": {PID: ent}}


def ev(t, parada="08:00", retorno=None, desvio=35.0):
    return {"tracker": t, "parada": parada, "retorno": retorno, "desvio": desvio}


def monta(trk, fim="2026-09-03", hist=None):
    return falhas_job.montar(app, sol, "2026-09-01", fim, geracao={}, str_store={}, trk_store=trk, book={},
                             hist_2c=lambda d: {}, mortas_curva={}, trk_semcom=hist, log=lambda m: None)


def test_tracker_sem_comunicacao_no_dia_nao_entra_no_relatorio():
    p = monta(_dia("01", {"TRK1": P, "TRK2": P}, [ev("TRK1"), ev("TRK2")], sc=["TRK2"]), fim="2026-09-01")
    assert [r["tracker"] for r in p["trackers"]["rows"]] == ["TRK1"]
    assert p["trackers"]["qualidade"]["sem comunicação no dia: fora"] == 1
    (s,) = p["trackers"]["sem_comunicacao"]
    assert (s["usina"], s["tracker"], s["dias"], s["de"], s["ate"]) == ("Inhapi", "TRK2", 1, "2026-09-01", "2026-09-01")


def test_parado_que_perde_a_comunicacao_segue_em_aberto_sem_contar_os_dias_sem_dado():
    # parado de verdade no dia 01; nos dias 02 e 03 sem comunicação: a perda é só do dia 01 e ninguém sabe se voltou
    t = {**_dia("01", {"TRK1": P}, [ev("TRK1")], sc=[]),
         **_dia("02", {"TRK1": P}, [], sc=["TRK1"]), **_dia("03", {"TRK1": P}, [], sc=["TRK1"])}
    (r,) = monta(t)["trackers"]["rows"]
    assert r["inicio"].startswith("2026-09-01") and r["fim"] is None
    assert "sem comunicação do tracker desde 02/09" in r["flags"]
    # não "segue parado": a aba e o semanal tiram das contas de em aberto pelo sem_com_desde
    assert (r["sem_com_desde"], r["visto_ate"]) == ("2026-09-02", "2026-09-01")
    so_dia_01 = monta(_dia("01", {"TRK1": P}, [ev("TRK1")], sc=[]), fim="2026-09-01")["trackers"]["rows"][0]
    assert so_dia_01["sem_com_desde"] is None and so_dia_01["visto_ate"] == "2026-09-01"
    assert r["perda_kwh"] == so_dia_01["perda_kwh"]


def test_sem_comunicacao_no_meio_nao_parte_o_episodio():
    t = {**_dia("01", {"TRK1": P}, [ev("TRK1")], sc=[]), **_dia("02", {}, [], sc=["TRK1"]),
         **_dia("03", {"TRK1": P}, [ev("TRK1", parada="06:30")], sc=[])}
    (r,) = monta(t)["trackers"]["rows"]
    assert r["inicio"].startswith("2026-09-01") and r["fim"] is None
    assert "sem comunicação em parte do episódio" in r["flags"]


def test_frota_sem_comunicacao_nao_faz_o_dia_de_frota_parada():
    # 52 sem comunicação em 0,0° (Santa Bárbara I) não são "a maioria da frota parada": o desvio do parado de verdade vale.
    # Usina fora do cadastro: a frota é a vista no registro (10), e 10 "parados" fariam o dia de frota parada
    cls = {f"TRK{i}": P for i in range(1, 11)}
    t = _dia("01", cls, [ev("TRK1", desvio=40.0)], sc=[f"TRK{i}" for i in range(2, 11)], nome="Usina Teste")
    (r,) = monta(t, fim="2026-09-01")["trackers"]["rows"]
    assert r["tracker"] == "TRK1" and r["desvio_pico"] == 40.0
    assert not any("maioria da frota" in f for f in r["flags"])


def test_dia_sem_a_marca_no_registro_usa_a_ronda():
    hist = {"2026-09-01": {falhas_job.chave_semcom("Inhapi", "TRK2")}}
    p = monta(_dia("01", {"TRK1": P, "TRK2": P}, [ev("TRK1"), ev("TRK2")]), fim="2026-09-01", hist=hist)
    assert [r["tracker"] for r in p["trackers"]["rows"]] == ["TRK1"]


def test_a_marca_do_registro_vence_a_da_ronda():
    hist = {"2026-09-01": {falhas_job.chave_semcom("Inhapi", "TRK1")}}
    p = monta(_dia("01", {"TRK1": P}, [ev("TRK1")], sc=[]), fim="2026-09-01", hist=hist)
    assert [r["tracker"] for r in p["trackers"]["rows"]] == ["TRK1"]


def test_chave_da_ronda_ignora_acento_caixa_e_o_id_da_api():
    assert falhas_job.chave_semcom("Barretos 1 (83)", "TRK1") == falhas_job.chave_semcom("barretos 1", "trk1")
    assert falhas_job.chave_semcom("Mandaguaçu", "Tracker 01") == falhas_job.chave_semcom("MANDAGUACU", "tracker 01")


def _hist(tmp_path, snaps):
    f = tmp_path / "trackers_parados_hist.jsonl"
    f.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in snaps) + "\n", encoding="utf-8")
    return str(f)


def test_historico_da_ronda_vale_a_ultima_foto_do_dia_e_o_rotulo_repetido_so_com_todos_sem_comunicacao(tmp_path,
                                                                                                    monkeypatch):
    # a ronda junta Guatambu 1 a 4 como "Guatambu", com um TRK1 em cada: só vale se todos os TRK1 estão sem comunicação
    snaps = [{"ts": "2026-09-10 08:25", "parados": [{"u": "Aparecida 3", "t": "Tracker 02", "sc": True},
                                                    {"u": "Aparecida 3", "t": "Tracker 03", "sc": True}]},
             {"ts": "2026-09-10 13:15", "parados": [{"u": "Aparecida 3", "t": "Tracker 03", "sc": False},
                                                    {"u": "Guatambu", "t": "TRK1", "sc": True},
                                                    {"u": "Guatambu", "t": "TRK1", "sc": False},
                                                    {"u": "Guatambu", "t": "TRK2", "sc": True},
                                                    {"u": "Guatambu", "t": "TRK2", "sc": True}]}]
    monkeypatch.setattr(app, "_TRK_HIST_PATH", _hist(tmp_path, snaps))
    monkeypatch.setattr(app, "_FALHAS_TRK_SEMCOM_PATH", str(tmp_path / "importado.json"))
    h = app._falhas_trk_semcom_hist()
    ch = falhas_job.chave_semcom
    assert h == {"2026-09-10": {ch("Aparecida 3", "Tracker 02"), ch("Guatambu", "TRK2")}}


def test_dia_sem_ronda_entre_dois_dias_sem_comunicacao_tambem_e_sem_comunicacao(tmp_path, monkeypatch):
    # Santa Bárbara I Tracker 48: sem comunicação em todas as fotos de 15 a 30/09; nos dias sem ronda (20 e 26/09) o
    # registro o dava por parado e o episódio seguia aberto pela semana
    def foto(ts, *pars):
        return {"ts": ts, "parados": [{"u": "Santa Bárbara I", "t": t, "sc": sc} for t, sc in pars]}
    snaps = [foto("2026-09-25 13:04", ("Tracker 48", True), ("Tracker 49", True), ("Tracker 50", False)),
             foto("2026-09-28 09:25", ("Tracker 48", True), ("Tracker 50", True)),
             foto("2026-09-29 08:28", ("Tracker 51", True)),
             foto("2026-10-05 08:30", ("Tracker 51", True))]          # 5 dias sem foto: lacuna longa, não preenche
    monkeypatch.setattr(app, "_TRK_HIST_PATH", _hist(tmp_path, snaps))
    monkeypatch.setattr(app, "_FALHAS_TRK_SEMCOM_PATH", str(tmp_path / "importado.json"))
    h = app._falhas_trk_semcom_hist()
    ch = falhas_job.chave_semcom
    for d in ("2026-09-26", "2026-09-27"):
        assert h[d] == {ch("Santa Bárbara I", "Tracker 48")}               # o 49 não estava na foto de 28/09
    assert "2026-10-01" not in h and "2026-10-04" not in h


@pytest.fixture
def cli(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    monkeypatch.setattr(app, "_FALHAS_TRK_SEMCOM_PATH", str(tmp_path / "falhas_trk_semcom.json"))
    monkeypatch.setattr(app, "_TRK_HIST_PATH", str(tmp_path / "sem_ronda.jsonl"))
    return app.app.test_client()


def test_servidor_recebe_a_marca_das_rondas_do_pc(cli):
    # o servidor não faz a ronda do WhatsApp: a marca dos dias de antes vem do PC
    ch = falhas_job.chave_semcom("Aparecida 3", "Tracker 02")
    r = cli.post("/api/painel/falhas/trk-semcom", json={"2026-09-10": [ch]})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    cli.post("/api/painel/falhas/trk-semcom", json={"2026-09-11": [ch]})
    assert app._falhas_trk_semcom_hist() == {"2026-09-10": {ch}, "2026-09-11": {ch}}


@pytest.mark.parametrize("corpo", [[], {"10/09/2026": ["a|b"]}, {"2026-09-10": "a|b"}, {"2026-09-10": ["sem barra"]}])
def test_marca_fora_do_formato_e_recusada(cli, corpo):
    assert cli.post("/api/painel/falhas/trk-semcom", json=corpo).status_code == 400


def test_aba_mostra_os_trackers_sem_comunicacao_e_quem_comecou_no_periodo(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "", raising=False)
    app.app.config["TESTING"] = True
    with app.app.test_client() as c:
        html = c.get("/painel/falhas").get_data(as_text=True)
    assert 'id="t-sc"' in html and "D.trackers.sem_comunicacao" in html
    assert "começaram no período" in html and "já vinham parados" in html
