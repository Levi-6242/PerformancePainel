# -*- coding: utf-8 -*-
"""Teto diário e domingo sem SunOp (04/10/2026, Levi: "temos como limitar em 3000 requisições por dia e domingo não faz
requisições?" — e, perguntado: "só a ronda poderá", com a Axis dentro do teto).

Medido no `/api/sunop/uso` antes da mudança (03/10): servidor 3.011 da nossa conta + 2.315 da Axis, PC 295 + 230. Da
Axis, 100% eram falhas: o token web dela venceu em 17/07, ela não tem token de API, e mesmo assim cada ciclo batia
`check_token`, `refresh_token`, `/plants` e o catálogo — e o da Athon, vencido em 23/07, ~540 por dia do mesmo jeito.

As regras, cada uma com o seu teste:
1. Domingo, nenhuma requisição à SunOp (Athon e Axis) — fora a ronda do WhatsApp (08:25 e 13:00).
2. Passou do teto do dia (servidor 2.700 + PC 300 = 3.000), idem: só a ronda.
3. A pausa não apaga dado: a tela segura o último dado bom, a Entrada fica com a última contagem, o livro de trackers
   atualiza só pelo banco.
4. Token web VENCIDO não vai à rede (o check e o refresh falham sempre com `exp` no passado) e a Axis sem token de
   API com o web vencido não chama o serviço de dados.
"""
import base64
import json
import time
from contextlib import contextmanager

import pytest

import app

DOMINGO = "2026-10-04 10:00:00"
SEGUNDA = "2026-10-05 10:00:00"


@pytest.fixture
def pausa_ligada(monkeypatch, tmp_path):
    """Liga a pausa (o conftest a desliga para o resto da suíte, que roda em qualquer dia) com o contador zerado e os
    arquivos do contador num diretório só do teste."""
    monkeypatch.setattr(app, "SUNOP_PAUSA_LIGADA", True)
    monkeypatch.setattr(app, "_AQUI", str(tmp_path))
    monkeypatch.setattr(app, "_SUNOP_USO", {})
    monkeypatch.setattr(app, "_SUNOP_USO_BASE", {})
    monkeypatch.setattr(app, "_sunop_uso_herdado", {"ok": False})
    monkeypatch.setattr(app, "_sunop_uso_outro", {"t": 0.0, "dia": None, "n": 0})
    monkeypatch.setattr(app, "_sunop_ronda", {"ate": 0.0})
    monkeypatch.setattr(app, "SUNOP_TETO_DIA", 2700)
    return tmp_path


class _R:
    def __init__(self, code=200, body=None):
        self.status_code = code
        self._b = body
        self.headers = {}

    def json(self):
        return self._b


@pytest.fixture
def rede(monkeypatch):
    """Toda chamada HTTP fica registrada; nenhuma sai do PC."""
    chamadas = []

    class _Http:
        def request(self, metodo, url, **kw):
            chamadas.append(url)
            return _R(200, {"data": []})

        def get(self, url, **kw):
            chamadas.append(url)
            if url.endswith("/plants"):
                return _R(200, [{"name": "AAA100"}])
            return _R(200)

    monkeypatch.setattr(app, "_http", lambda: _Http())
    monkeypatch.setattr(app, "_sunop_api_token", lambda inst="gridco": "eyJ.api.token")
    monkeypatch.setattr(app, "_sunop_token_ok", {})
    return chamadas


def _jwt(iat, exp):
    pl = base64.urlsafe_b64encode(json.dumps({"iat": iat, "exp": exp}).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJIUzI1NiJ9.{pl}.assinatura"


def _hoje():
    return app.datetime.now().date().isoformat()


# ── 1. domingo ───────────────────────────────────────────────────────────────────────────────────────────────────────
def test_domingo_nenhuma_requisicao_a_sunop(pausa_ligada, rede, freeze_now):
    freeze_now(DOMINGO)
    assert app._sunop_pausa() == "domingo"
    assert app._sunop_req("POST", "https://gridco-api.sunop.net/data/v2/last_values", "gridco", json={}) is None
    assert app._sunop_req("POST", "https://axis-api.sunop.net/data/v2/last_values", "axis", json={}) is None
    assert rede == []
    assert app._SUNOP_USO == {}                          # o que não saiu não conta


def test_dia_util_abaixo_do_teto_chama_normal(pausa_ligada, rede, freeze_now):
    freeze_now(SEGUNDA)
    assert app._sunop_pausa() is None
    assert app._sunop_req("POST", "https://gridco-api.sunop.net/data/v2/last_values", "gridco", json={}) is not None
    assert len(rede) == 1


def test_domingo_a_ronda_busca(pausa_ligada, rede, freeze_now):
    freeze_now(DOMINGO)
    with app._sunop_libera_ronda():
        assert app._sunop_pausa() is None
        assert app._sunop_req("POST", "https://gridco-api.sunop.net/data/v2/analog_values", "gridco", json={}) is not None
    assert app._sunop_pausa() == "domingo"               # a janela fecha com a ronda
    assert len(rede) == 1


def test_a_janela_da_ronda_fecha_mesmo_se_a_ronda_quebrar(pausa_ligada, freeze_now):
    freeze_now(DOMINGO)
    with pytest.raises(RuntimeError):
        with app._sunop_libera_ronda():
            raise RuntimeError("WhatsApp fora")
    assert app._sunop_pausa() == "domingo"


def test_o_disparo_da_ronda_abre_a_janela(pausa_ligada, monkeypatch, freeze_now):
    """É o `_ronda_whats_disparo` (horários do whats_ronda.json e o teste manual) que abre a janela — não o
    `_ronda_parados_all`, que a prévia da tela também chama."""
    freeze_now(DOMINGO)
    visto = {}

    def _parados(force=True):
        visto["pausa"] = app._sunop_pausa()
        return [], [], []

    monkeypatch.setattr(app, "_ronda_parados_all", _parados)
    monkeypatch.setattr(app, "_whats_cfg", lambda: {"grupos": {"Sul": "grupo-sul"}})
    monkeypatch.setattr(app, "_whats_send", lambda cfg, gid, txt: (True, ""))
    monkeypatch.setattr(app, "_ronda_coleta", {})
    app._ronda_whats_disparo("08:25", confirmar=False)
    assert visto["pausa"] is None
    assert app._sunop_pausa() == "domingo"


def test_retentativa_da_ronda_reaproveita_a_coleta_por_10_min(pausa_ligada, monkeypatch, freeze_now):
    """Com o WhatsApp fora, o laço retenta a cada 30 s por até 2 h; cada retentativa recoletava tudo (force=True) — e,
    liberada da pausa, a ronda queimaria a SunOp 240 vezes. Mesmo horário, menos de 10 min: reaproveita."""
    agora = freeze_now(SEGUNDA)
    n = {"c": 0}

    def _parados(force=True):
        n["c"] += 1
        return [], [], []

    monkeypatch.setattr(app, "_ronda_parados_all", _parados)
    monkeypatch.setattr(app, "_whats_cfg", lambda: {"grupos": {"Sul": "grupo-sul"}})
    monkeypatch.setattr(app, "_whats_send", lambda cfg, gid, txt: (False, "aguardando_qr"))
    monkeypatch.setattr(app, "_ronda_coleta", {})
    app._ronda_whats_disparo("08:25", confirmar=False)
    app._ronda_whats_disparo("08:25", confirmar=False)
    assert n["c"] == 1
    freeze_now((agora + app.timedelta(minutes=11)).strftime("%Y-%m-%d %H:%M:%S"))
    app._ronda_whats_disparo("08:25", confirmar=False)
    assert n["c"] == 2


# ── 2. teto do dia ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_passou_do_teto_so_a_ronda(pausa_ligada, rede, freeze_now):
    freeze_now(SEGUNDA)
    app._SUNOP_USO[_hoje()] = {"last_values:str": 2000, "axis:cfg:check_token": 700}
    assert app._sunop_pausa() == "teto"
    assert app._sunop_req("POST", "https://gridco-api.sunop.net/data/v2/last_values", "gridco", json={}) is None
    with app._sunop_libera_ronda():
        assert app._sunop_req("POST", "https://gridco-api.sunop.net/data/v2/analog_values", "gridco", json={}) is not None
    assert len(rede) == 1


def test_o_gasto_soma_os_dois_processos_o_anterior_e_a_axis(pausa_ligada, freeze_now):
    freeze_now(SEGUNDA)
    logs = pausa_ligada / "logs"
    logs.mkdir()
    eu, outro = ("web", "worker") if app._MODO_WEB else ("worker", "web")
    (logs / f"sunop_uso_{outro}.json").write_text(json.dumps({_hoje(): {"last_values:str": 100, "axis:metadata": 7},
                                                              "2026-10-04": {"last_values:str": 9999}}))
    (logs / f"sunop_uso_{eu}.json").write_text(json.dumps({_hoje(): {"cfg:check_token": 20}}))   # o processo anterior
    app._SUNOP_USO[_hoje()] = {"analog_values:trk": 3}
    assert app._sunop_gasto_hoje() == 100 + 7 + 20 + 3


def test_teto_por_maquina(monkeypatch):
    """3.000 por dia na conta: 2.700 para o servidor (coleta completa) e 300 para o PC (só a ronda). Medido em 03/10:
    PC 295 + 230 da Axis — com o token vencido fora da rede, sobra ~215."""
    assert app._sunop_teto_de("completa", None) == 2700
    assert app._sunop_teto_de("ronda", None) == 300
    assert app._sunop_teto_de("completa", "1500") == 1500


# ── 3. a pausa não apaga dado ────────────────────────────────────────────────────────────────────────────────────────
def test_na_pausa_a_tela_segura_o_ultimo_dado_bom_sem_prazo(pausa_ligada, freeze_now):
    freeze_now(DOMINGO)
    cache = {"payload": {"rows": [{"usina": "AAA100", "sem_dados": False}], "dados_ts": time.time() - 12 * 3600}}
    ret = app._sunop_guarda_vazio(cache, [{"usina": "AAA100", "sem_dados": True}], "gridco", "visão geral")
    assert ret is not None and ret["retido"] is True and ret["pausa"] == "domingo"


def test_fora_da_pausa_a_retencao_segue_com_prazo(pausa_ligada, freeze_now):
    freeze_now(SEGUNDA)
    cache = {"payload": {"rows": [{"usina": "AAA100", "sem_dados": False}], "dados_ts": time.time() - 12 * 3600}}
    assert app._sunop_guarda_vazio(cache, [{"usina": "AAA100", "sem_dados": True}], "gridco", "visão geral") is None


def test_prewarm_no_domingo_tira_todas_as_tarefas_da_sunop(pausa_ligada, freeze_now):
    freeze_now(DOMINGO)
    f = lambda: None
    tarefas = [("SunOp", f), ("Axis", f), ("strings SunOp", f), ("SunOp trackers", f), ("API PV", f), ("Thopen", f)]
    assert [n for n, _ in app._prewarm_filtra_noturno(tarefas)] == ["API PV", "Thopen"]


def test_prewarm_ignora_a_janela_da_ronda(pausa_ligada, freeze_now):
    """Ciclo de prewarm que começasse com a janela aberta seguiria buscando depois que ela fechasse."""
    freeze_now(DOMINGO)
    f = lambda: None
    with app._sunop_libera_ronda():
        assert [n for n, _ in app._prewarm_filtra_noturno([("SunOp", f), ("API PV", f)])] == ["API PV"]


def test_entrada_na_pausa_fica_com_a_ultima_contagem(pausa_ligada, monkeypatch, freeze_now):
    freeze_now(DOMINGO)
    monkeypatch.setattr(app, "SUNOP_COLETA", "completa")
    monkeypatch.setattr(app, "_entrada_trk_do_resumo", lambda inst: None)        # resumo velho
    monkeypatch.setattr(app, "_sunop_parados_rows", lambda *a, **k: pytest.fail("buscou na pausa"))
    with pytest.raises(RuntimeError, match="domingo"):
        app._entrada_trk_fonte("Athon")()


def test_livro_de_trackers_na_pausa_atualiza_so_pelo_banco(pausa_ligada, monkeypatch, freeze_now):
    freeze_now(DOMINGO)
    pedido = {}

    class _TW:
        def atualizar(self, verbose=False, fonte="ambas"):
            pedido["fonte"] = fonte
            return {}

        def get_issues_json(self):
            return {}

    monkeypatch.setattr(app, "_TRACKER_WATCH_OK", True)
    monkeypatch.setattr(app, "_tw", _TW())
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    with app.app.test_client() as c:
        c.post("/api/tracker-watch/update")
    assert pedido["fonte"] == "pg"


def test_uso_diz_a_pausa_o_teto_e_o_gasto(pausa_ligada, monkeypatch, freeze_now):
    freeze_now(DOMINGO)
    app._SUNOP_USO[_hoje()] = {"last_values:str": 12}
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    with app.app.test_client() as c:
        j = c.get("/api/sunop/uso").get_json()
    assert j["pausa"] == "domingo" and j["teto_dia"] == 2700 and j["gasto_hoje"] == 12


# ── 4. token web vencido não vai à rede ──────────────────────────────────────────────────────────────────────────────
def test_token_web_vencido_nao_bate_check_nem_refresh(pausa_ligada, rede, monkeypatch, freeze_now):
    freeze_now(SEGUNDA)
    vencido = _jwt(time.time() - 80 * 86400, time.time() - 73 * 86400)          # o da Athon no servidor: 23/07
    monkeypatch.setitem(app._si("gridco")["token"], "token", vencido)
    monkeypatch.setattr(app, "_tokens_rt_get", lambda k: "")
    for _ in range(5):
        assert app.get_sunop_token("gridco") == vencido
    assert rede == []


def test_token_vencido_adota_o_colado_pela_tela(pausa_ligada, rede, monkeypatch, freeze_now):
    freeze_now(SEGUNDA)
    vencido = _jwt(time.time() - 80 * 86400, time.time() - 73 * 86400)
    colado = _jwt(time.time() - 60, time.time() + 7 * 86400)
    monkeypatch.setitem(app._si("gridco")["token"], "token", vencido)
    monkeypatch.setattr(app, "_tokens_rt_get", lambda k: colado)
    assert app.get_sunop_token("gridco") == colado
    assert rede == []


def test_na_pausa_o_token_nao_e_validado_na_rede(pausa_ligada, rede, monkeypatch, freeze_now):
    freeze_now(DOMINGO)
    vivo = _jwt(time.time() - 3600, time.time() + 5 * 86400)
    monkeypatch.setitem(app._si("gridco")["token"], "token", vivo)
    assert app.get_sunop_token("gridco") == vivo
    assert rede == []


def test_token_de_24h_renova_so_na_metade_da_vida(pausa_ligada, rede, monkeypatch, freeze_now):
    """O token web da Axis vive 24 h: "vence em menos de 2 dias" era verdade SEMPRE, e cada chamada renovava."""
    freeze_now(SEGUNDA)
    novo = _jwt(time.time() - 3600, time.time() + 23 * 3600)
    monkeypatch.setitem(app._si("axis")["token"], "token", novo)
    app.get_sunop_token("axis")
    assert not any(u.endswith("/refresh_token") for u in rede)
    meio = _jwt(time.time() - 13 * 3600, time.time() + 11 * 3600)
    monkeypatch.setitem(app._si("axis")["token"], "token", meio)
    monkeypatch.setattr(app, "_sunop_persist", lambda tok, inst: None)
    app.get_sunop_token("axis")
    assert any(u.endswith("/refresh_token") for u in rede)


def test_plants_com_token_web_vencido_vai_direto_a_lista_do_servico_de_dados(pausa_ligada, rede, monkeypatch,
                                                                            freeze_now):
    freeze_now(SEGUNDA)
    vencido = _jwt(time.time() - 80 * 86400, time.time() - 73 * 86400)
    monkeypatch.setitem(app._si("gridco")["token"], "token", vencido)
    monkeypatch.setattr(app, "_tokens_rt_get", lambda k: "")
    monkeypatch.setattr(app, "_sunop_plants_lista", {})
    monkeypatch.setattr(app, "_sunop_plants_do_dados", lambda inst: ["AAA100"])
    monkeypatch.setitem(app._si("gridco"), "meta", {"AAA100": {"trackers": {}}})
    app.ensure_sunop_meta("gridco")
    assert not any("/plants" in u or "check_token" in u or "refresh_token" in u for u in rede)
    assert app._sunop_plants_lista["gridco"]["nomes"] == ["AAA100"]


def test_axis_sem_token_de_api_e_web_vencido_nao_chama_o_servico_de_dados(pausa_ligada, rede, monkeypatch, freeze_now):
    freeze_now(SEGUNDA)
    vencido = _jwt(time.time() - 80 * 86400, time.time() - 79 * 86400)          # o da Axis no servidor: 17/07
    monkeypatch.setitem(app._si("axis")["token"], "token", vencido)
    monkeypatch.setattr(app, "_tokens_rt_get", lambda k: "")
    monkeypatch.setattr(app, "_sunop_api_token", lambda inst="gridco": "" if inst == "axis" else "eyJ.api")
    assert app._sunop_req("GET", "https://axis-api.sunop.net/data/v2/metadata", "axis") is None
    assert rede == []


# ── 5. a tela diz que está pausada ───────────────────────────────────────────────────────────────────────────────────
def test_abas_da_athon_dizem_a_pausa(pausa_ligada, monkeypatch, freeze_now):
    """O topo do Monitoramento diz "ao vivo · HH:MM": no domingo, com o dado de sábado, seria falso."""
    freeze_now(DOMINGO)
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    for k in ("cache", "etm_cache", "analise_cache", "trk_cache"):
        monkeypatch.setitem(app._si("gridco"), k, {"payload": {"rows": []}, "ts": time.time(), "_ttl": 10 ** 9})
    with app.app.test_client() as c:
        for rota in ("/api/sunop/data", "/api/sunop/etm", "/api/sunop/etm/analise", "/api/sunop/trackers"):
            assert c.get(rota).get_json()["sunop_pausa"] == "domingo", rota


def test_a_tela_troca_o_ao_vivo_pela_pausa():
    from pathlib import Path
    html = (Path(app.__file__).resolve().parents[1] / "docs" / "redesign" / "Monitoramento (novo design).html"
            ).read_text(encoding="utf-8")
    assert "RD.pv.sunop_pausa" in html and "SunOp pausada · ${v.sunopPausa}" in html
