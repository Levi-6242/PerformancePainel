# -*- coding: utf-8 -*-
"""API PV fora do ar não pode travar as OUTRAS fontes (Levi, 24/09/2026: "verifique porquê você travou a chegada dos
dados de todas as fontes, todos estão como sem comunicação").

O que aconteceu: a API PV parou de responder às 09:10 — às 14:35 o /authenticate não respondia nem em 150 s. O worker
tem UM ciclo em série (_prewarm_loop): a aba da API PV primeiro (ETAPA 2), depois Athon, Axis, SEMP, Alves Lima, 2C,
ETMs e o banco (ETAPA 3), e as caras de tempos em tempos (ETAPA 4, com PR e parados da API PV). Cada chamada à API PV
fora do ar esperava o timeout inteiro (30–90 s), e as três passadas do fetch_all — 8 threads, depois 4, depois UMA por
vez — somavam horas. Às 14:42 o banco da Thopen tinha leitura das 14:40 em 17 de 19 usinas, e a plataforma mostrava a
das 13:50: o dado chegava, o worker é que não ia buscar. A Athon parou em 13:54 pelo mesmo motivo.

Três consertos, um teste cada:
  1. DISJUNTOR da API PV: N falhas de rede seguidas → toda chamada à API PV falha NA HORA por um tempo (o padrão do
     disjuntor da SunOp). Quem chama já segura o último dado bom.
  2. TETO na ETAPA 2: o ciclo espera a aba da API PV até PREWARM_ABA_PRINCIPAL_MAX_S; depois ela segue em fundo.
  3. ORDEM na ETAPA 3: quem não depende da API PV vai na frente.
"""
import inspect
import threading
import time

import pytest
import requests

import app


@pytest.fixture(autouse=True)
def disjuntor_zerado(monkeypatch):
    monkeypatch.setattr(app, "_pv_disj", {"falhas": 0, "ate": 0.0, "desde": 0.0})
    yield


@pytest.fixture
def rede(monkeypatch):
    """A 'rede' por baixo do disjuntor: conta as idas e responde o que o teste mandar."""
    estado = {"idas": 0, "modo": "timeout"}

    def _send(self, request, **kw):
        estado["idas"] += 1
        if estado["modo"] == "timeout":
            raise requests.exceptions.ReadTimeout("Read timed out. (read timeout=90)", request=request)
        r = requests.Response()
        r.status_code = 200
        r._content = b"[]"
        r.request = request
        return r
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", _send)
    return estado


def _chama():
    return app._http().post(f"{app.BASE_URL}/day_inverter", json={"id": 1}, timeout=90)


def test_o_http_da_api_pv_passa_pelo_disjuntor_e_o_resto_nao():
    s = app._http()
    assert isinstance(s.get_adapter(f"{app.BASE_URL}/day_inverter"), app._PvDisjuntor)
    assert not isinstance(s.get_adapter("https://apiplataforma.pvoperation.com/x"), app._PvDisjuntor)
    assert not isinstance(s.get_adapter("https://api.fracttal.com/x"), app._PvDisjuntor)


def test_falhas_seguidas_abrem_e_a_proxima_nem_vai_a_rede(rede):
    for _ in range(app.PV_DISJ_FALHAS):
        with pytest.raises(requests.exceptions.Timeout):
            _chama()
    assert rede["idas"] == app.PV_DISJ_FALHAS and app._pv_disj_aberto()
    t0 = time.time()
    with pytest.raises(app.PVForaDoAr):
        _chama()
    assert rede["idas"] == app.PV_DISJ_FALHAS, "com o disjuntor aberto a chamada não pode ir à rede"
    assert time.time() - t0 < 0.5, "falha NA HORA, sem esperar timeout"


def test_o_erro_do_disjuntor_e_erro_de_conexao(rede):
    """Quem chama a API PV já trata ConnectionError (process_plant vira 'sem_dados', o drill vira 504)."""
    assert issubclass(app.PVForaDoAr, requests.exceptions.ConnectionError)


def test_poucas_falhas_nao_abrem(rede):
    for _ in range(app.PV_DISJ_FALHAS - 1):
        with pytest.raises(requests.exceptions.Timeout):
            _chama()
    assert not app._pv_disj_aberto()


def test_uma_resposta_zera_a_contagem(rede):
    for _ in range(app.PV_DISJ_FALHAS - 1):
        with pytest.raises(requests.exceptions.Timeout):
            _chama()
    rede["modo"] = "ok"
    assert _chama().status_code == 200
    assert app._pv_disj["falhas"] == 0


def test_passado_o_tempo_tenta_de_novo_e_se_responder_fecha(rede):
    for _ in range(app.PV_DISJ_FALHAS):
        with pytest.raises(requests.exceptions.Timeout):
            _chama()
    app._pv_disj["ate"] = time.time() - 1          # o tempo de disjuntor aberto passou
    rede["modo"] = "ok"
    assert _chama().status_code == 200
    assert not app._pv_disj_aberto() and app._pv_disj["falhas"] == 0 and app._pv_disj["desde"] == 0.0


def test_passado_o_tempo_se_falhar_abre_de_novo_na_primeira(rede):
    """Uma sonda por janela, não mais N: a API segue fora, uma falha já basta para reabrir."""
    for _ in range(app.PV_DISJ_FALHAS):
        with pytest.raises(requests.exceptions.Timeout):
            _chama()
    app._pv_disj["ate"] = time.time() - 1
    with pytest.raises(requests.exceptions.Timeout):
        _chama()
    assert app._pv_disj_aberto()


def test_usina_com_disjuntor_aberto_vira_sem_dados_na_hora(rede, monkeypatch):
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "")
    app._pv_disj.update(falhas=app.PV_DISJ_FALHAS, ate=time.time() + 60, desde=time.time())
    t0 = time.time()
    r = app.process_plant("", {"id": 1, "nome": "Usina X"}, timeout=90)
    assert r["sem_dados"] is True and time.time() - t0 < 0.5 and rede["idas"] == 0


# ── o teto da ETAPA 2 ─────────────────────────────────────────────────────────

def test_a_aba_da_api_pv_lenta_nao_segura_o_ciclo(monkeypatch):
    solta = threading.Event()
    monkeypatch.setattr(app, "_refresh_data_cache", lambda: solta.wait(5))
    t0 = time.time()
    assert app._prewarm_aba_principal(espera_max=0.2) is False
    assert time.time() - t0 < 1.5, "o ciclo tem de seguir para as outras fontes"
    solta.set()


def test_a_aba_da_api_pv_rapida_segue_em_primeiro_e_sozinha(monkeypatch):
    feito = []
    monkeypatch.setattr(app, "_refresh_data_cache", lambda: feito.append(1))
    assert app._prewarm_aba_principal(espera_max=5) is True and feito == [1]


def test_o_laco_usa_o_teto():
    src = inspect.getsource(app._prewarm_loop)
    assert "_prewarm_aba_principal()" in src and "_refresh_data_cache()" not in src


# ── teto em TODA etapa, e nada em dobro (24/09/2026, 15:51) ───────────────────
# Uma hora depois do conserto da API PV, o mesmo defeito com outra fonte: o banco da Thopen passou a comprimir os dados
# antigos e a consulta da tabela do Banco foi de ~3 s para 83 s sozinha. Com duas cópias no servidor (web e worker), uma
# da plataforma local e as órfãs de cada restart, nenhuma terminava — e a ETAPA 3, que só acaba quando a ÚLTIMA tarefa
# acaba, segurou a Athon de novo (parada em 15:22). O teto passa a valer para toda etapa do ciclo.

def test_etapa_com_tarefa_lenta_nao_segura_o_ciclo(monkeypatch):
    monkeypatch.setattr(app, "_PREWARM_EM_VOO", set())
    solta, feitas = threading.Event(), []
    t0 = time.time()
    app._prewarm_paralelo([("PG snapshot", lambda: solta.wait(10)), ("SunOp", lambda: feitas.append("SunOp"))],
                          workers=3, espera_max=0.3)
    assert time.time() - t0 < 1.5, "a etapa tem de seguir sem a tarefa lenta"
    assert feitas == ["SunOp"]
    solta.set()


def test_tarefa_que_ainda_roda_nao_comeca_de_novo(monkeypatch):
    """A volta seguinte não põe uma segunda consulta pesada por cima da que ainda está no banco."""
    monkeypatch.setattr(app, "_PREWARM_EM_VOO", set())
    solta, inicios = threading.Event(), []

    def _lenta():
        inicios.append(1)
        solta.wait(10)
    app._prewarm_paralelo([("PG snapshot", _lenta)], workers=2, espera_max=0.2)
    app._prewarm_paralelo([("PG snapshot", _lenta)], workers=2, espera_max=0.2)
    assert inicios == [1], "começou outra igual com a primeira ainda rodando"
    solta.set()
    for _ in range(50):
        if not app._PREWARM_EM_VOO:
            break
        time.sleep(0.05)
    app._prewarm_paralelo([("PG snapshot", lambda: inicios.append(2))], workers=2, espera_max=2)
    assert inicios == [1, 2], "terminada a primeira, a volta seguinte roda normal"


def test_no_web_a_tabela_do_banco_vencida_nao_reconstroi(monkeypatch):
    """O web serve o que o worker publica (cache_snapshot.json) — como o _swr já fazia com as outras abas."""
    chamadas = []
    monkeypatch.setattr(app, "_MODO_WEB", True)
    monkeypatch.setattr(app, "_pg_build_snapshot", lambda: chamadas.append(1) or ([], {}))
    monkeypatch.setattr(app, "_pg_cache", {"summary": [{"usina": "X"}], "detail": {}, "ts": time.time() - 3600})
    rows, _ = app._pg_get_snapshot()
    time.sleep(0.2)
    assert rows == [{"usina": "X"}] and chamadas == []


# ── a ordem da ETAPA 3 ────────────────────────────────────────────────────────

def test_quem_depende_da_api_pv_vai_por_ultimo():
    src = inspect.getsource(app._prewarm_loop)
    for nome in app.PREWARM_DEPENDEM_API_PV:
        assert f'("{nome}",' in src, f"{nome!r} não existe mais no _prewarm_loop — a lista ficou velha"
    assert "key=lambda t: t[0] in PREWARM_DEPENDEM_API_PV" in src
    tarefas = [("ETM", 1), ("SunOp", 2), ("SEMP strings", 3), ("PG snapshot", 4), ("2C API PV", 5), ("Axis", 6)]
    ordem = [n for n, _ in sorted(tarefas, key=lambda t: t[0] in app.PREWARM_DEPENDEM_API_PV)]
    assert ordem == ["SunOp", "PG snapshot", "Axis", "ETM", "SEMP strings", "2C API PV"]
