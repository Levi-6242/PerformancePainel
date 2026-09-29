# -*- coding: utf-8 -*-
"""Índice de disponibilidade do Gerencial: a varredura do Fracttal só vira índice INTEIRA (28/09/2026).

O caso: o `_frac_get` devolvia None no 429 (a cota do Fracttal é de 200 pedidos/min para a EMPRESA inteira, dividida
com o App de Campo, os robôs do PCM, o OS Creator e as duas plataformas) e o `_frac_disp_sweep` lia None como "acabaram
as OS". O worker publicava o pedaço lido como se fosse o índice todo. Em 28/09 o servidor servia 51 OS de setembro e 2 de
agosto e o notebook, 573 e 49, contra 991 e 894 da varredura inteira. A #12693 (Religamento, Brodowski, aberta desde 02/09)
sumiu dos dois, e com ela a "Usina desligada" da Brodowski. Sonda do mesmo dia (varredura inteira, 198 pedidos): 20
respostas 429, a 1ª já no primeiro pedido, e 2 conexões derrubadas.

Aqui o Fracttal é falso (só a rede); `_frac_get`, a espera pela cota, a varredura, o cálculo e a rota rodam de verdade.
"""
import json
import threading
from datetime import datetime, timedelta

import pytest
import requests
from requests.structures import CaseInsensitiveDict

import app

MSG_429 = ("Too many requests (200) created from this company (id_company=4987), "
           "please try again after 1 minute")


class _Resposta:
    def __init__(self, status, corpo, headers=None, texto=None):
        self.status_code = status
        self._corpo = corpo
        self.headers = CaseInsensitiveDict(headers or {})
        self.text = texto if texto is not None else json.dumps(corpo)

    def json(self):
        if self._corpo is None:
            raise ValueError("corpo não é JSON")
        return self._corpo


class _FracttalFalso:
    """Token + `work_orders/` paginado DESC por criação, com `total`, como o real (que devolve ~100 linhas mesmo
    pedindo 200). `roteiro(n)` diz o que o n-ésimo GET recebe: None (a página certa), 429, 503, 'vazia', 'encolhe'
    (200 vazio com total 0) ou uma exceção; `roteiro_token(n)` faz o mesmo com o n-ésimo POST do token."""

    TETO_GETS = 400                        # varredura que não para vira falha do teste, não teste travado

    def __init__(self, linhas, tam=3, roteiro=None, roteiro_token=None, reset="37", ascendente=False):
        self.ordem = sorted(linhas, key=lambda w: w["creation_date"], reverse=not ascendente)
        self.tam, self.reset = tam, reset
        self.roteiro = roteiro or (lambda n: None)
        self.roteiro_token = roteiro_token or (lambda n: None)
        self.gets, self.posts = [], 0

    def post(self, url, data=None, timeout=None):
        n, self.posts = self.posts, self.posts + 1
        if self.roteiro_token(n) == 429:   # o /oauth/token também gasta a cota da empresa
            return _Resposta(429, {"message": MSG_429}, {"Retry-After": self.reset, "RateLimit-Reset": self.reset})
        return _Resposta(200, {"access_token": "tok-falso", "token_type": "bearer", "expires_in": 3600})

    def get(self, url, headers=None, params=None, timeout=None):
        assert "work_orders/" in url
        n = len(self.gets)
        assert n < self.TETO_GETS, "a varredura não parou"
        self.gets.append(dict(params or {}))
        acao = self.roteiro(n)
        if isinstance(acao, Exception):
            raise acao
        if acao == 429:                    # a resposta real de 28/09 traz os dois cabeçalhos, com o mesmo valor
            return _Resposta(429, {"message": MSG_429},
                             {"RateLimit-Policy": "200;w=60", "RateLimit-Limit": "200",
                              "RateLimit-Remaining": "0", "RateLimit-Reset": self.reset, "Retry-After": self.reset})
        if acao == 503:
            return _Resposta(503, None, {"Content-Type": "text/html"}, texto="<html>Service Unavailable</html>")
        if acao == "encolhe":
            return _Resposta(200, {"success": True, "message": "", "total": 0, "data": []})
        ini = int((params or {}).get("start", 0))
        data = [] if acao == "vazia" else self.ordem[ini:ini + self.tam]
        return _Resposta(200, {"success": True, "message": "", "total": len(self.ordem), "data": data},
                         {"RateLimit-Policy": "200;w=60", "RateLimit-Limit": "200",
                          "RateLimit-Remaining": "150", "RateLimit-Reset": "20"})


def _tarefa(folio, criada, evento=None, fim=None, status=3, tipo="Religamento"):
    """Linha do work_orders/ com os campos que a varredura guarda (usina Alfa do catálogo abaixo)."""
    return {"wo_folio": folio, "id_work_orders_tasks": folio * 10, "creation_date": criada,
            "tasks_log_task_type_main": tipo, "id_status_work_order": status,
            "event_date": evento, "date_maintenance": None, "final_date": fim, "wo_final_date": None,
            "code": "TC-ALF100", "items_log_description": "TesteCo - Alfa 1 - SP  Endereço",
            "groups_1_description": "TesteCo - Alfa 1 - SP", "description": "Religamento da Usina",
            "created_by": "Operador COS", "personnel_description": "Técnico", "user_assigned": "Técnico"}


def _um_por_dia(n=51):
    """OS 1000.. criadas uma por dia, de 20/09/2026 para trás (1000 = 20/09, 1041 = 10/08, 1050 = 01/08)."""
    d0 = datetime(2026, 9, 20, 12, 0)
    return [_tarefa(1000 + i, (d0 - timedelta(days=i)).strftime("%Y-%m-%dT%H:%M:%S+00:00")) for i in range(n)]


@pytest.fixture
def fracttal(monkeypatch):
    """Instala um Fracttal falso no lugar da rede e registra as esperas sem dormir. Só a thread do teste é
    interceptada: daemons de outros testes seguem com a rede e o sono de verdade (o padrão do
    test_ciclo_nao_espera_trackers)."""
    principal, esperas = threading.current_thread(), []
    sono_real, http_real = app.time.sleep, app._http

    def _sono(s):
        if threading.current_thread() is not principal:
            return sono_real(s)
        esperas.append(s)

    monkeypatch.setattr(app, "_frac_token", {"token": "", "exp": 0.0})
    monkeypatch.setattr(app.time, "sleep", _sono)

    def _instala(linhas, **kw):
        falso = _FracttalFalso(linhas, **kw)
        monkeypatch.setattr(app, "_http", lambda: falso if threading.current_thread() is principal else http_real())
        return falso
    _instala.esperas = esperas
    return _instala


LIMITE = datetime(2026, 8, 10)
DEVEM_ESTAR = {str(1000 + i) for i in range(42)}      # criadas de 20/09 a 10/08, o limite


# ── varredura ───────────────────────────────────────────────────────────────────────────────
def test_varredura_inteira_para_ao_passar_do_limite(fracttal):
    falso = fracttal(_um_por_dia())
    got = app._frac_disp_sweep(LIMITE)
    assert DEVEM_ESTAR <= set(got)
    assert len(falso.gets) == 15            # a página 14 termina em 07/08 (< 10/08) e a varredura para ali


def test_429_no_meio_espera_o_reset_e_repete_a_mesma_pagina(fracttal):
    falso = fracttal(_um_por_dia(), roteiro=lambda n: 429 if n == 5 else None)
    got = app._frac_disp_sweep(LIMITE)
    assert DEVEM_ESTAR <= set(got)          # antes: o 429 virava "fim das OS" e voltavam só 15
    assert falso.gets[5]["start"] == falso.gets[6]["start"] == 15
    assert fracttal.esperas == [38]         # RateLimit-Reset 37 + 1 s


def test_reset_zero_nao_vira_laco_de_um_segundo(fracttal):
    fracttal(_um_por_dia(), roteiro=lambda n: 429 if n == 5 else None, reset="0")
    app._frac_disp_sweep(LIMITE)
    assert fracttal.esperas == [2]


def test_reset_longo_espera_no_maximo_um_minuto(fracttal):
    fracttal(_um_por_dia(), roteiro=lambda n: 429 if n == 5 else None, reset="3600")
    app._frac_disp_sweep(LIMITE)
    assert fracttal.esperas == [61]


def test_cota_que_nao_volta_derruba_a_varredura_em_vez_de_entregar_o_pedaco(fracttal):
    fracttal(_um_por_dia(), roteiro=lambda n: 429 if n >= 5 else None)
    with pytest.raises(RuntimeError, match="429"):
        app._frac_disp_sweep(LIMITE)
    assert sum(fracttal.esperas) <= app.FRAC_DISP_ESPERA_MAX_S


def test_pagina_vazia_antes_do_limite_e_falha_nao_fim_dos_dados(fracttal):
    fracttal(_um_por_dia(), roteiro=lambda n: "vazia" if n == 5 else None)
    with pytest.raises(RuntimeError, match="vazia"):
        app._frac_disp_sweep(LIMITE)


def test_total_que_encolhe_na_pagina_vazia_nao_vale_como_fim(fracttal):
    # uma resposta 200 vazia dizendo total 0 no meio da varredura não prova que a base acabou
    fracttal(_um_por_dia(), roteiro=lambda n: "encolhe" if n == 5 else None)
    with pytest.raises(RuntimeError, match="vazia"):
        app._frac_disp_sweep(LIMITE)


def test_base_que_acaba_antes_do_limite_e_a_base_inteira(fracttal):
    # 6 OS, todas depois do limite: a página vazia chega com start >= total — é o fim de verdade
    fracttal(_um_por_dia(6))
    assert set(app._frac_disp_sweep(LIMITE)) == {"1000", "1001", "1002", "1003", "1004", "1005"}


def test_queda_de_rede_passageira_repete_a_pagina(fracttal):
    fracttal(_um_por_dia(), roteiro=lambda n: requests.ConnectionError("rede caiu") if n == 5 else None)
    assert DEVEM_ESTAR <= set(app._frac_disp_sweep(LIMITE))
    assert fracttal.esperas == [5]


def test_rede_fora_de_vez_derruba_a_varredura(fracttal):
    fracttal(_um_por_dia(), roteiro=lambda n: requests.ConnectionError("rede caiu") if n >= 5 else None)
    with pytest.raises(RuntimeError, match="ConnectionError"):
        app._frac_disp_sweep(LIMITE)
    assert len(fracttal.esperas) == app.FRAC_FALHAS_SEGUIDAS_MAX - 1


def test_5xx_passageiro_repete_a_pagina(fracttal):
    fracttal(_um_por_dia(), roteiro=lambda n: 503 if n == 5 else None)
    assert DEVEM_ESTAR <= set(app._frac_disp_sweep(LIMITE))
    assert fracttal.esperas == [5]


def test_5xx_que_nao_passa_diz_o_status(fracttal):
    fracttal(_um_por_dia(), roteiro=lambda n: 503 if n >= 5 else None)
    with pytest.raises(RuntimeError, match="503"):
        app._frac_disp_sweep(LIMITE)


def test_token_recusado_no_meio_da_varredura_e_passageiro(fracttal):
    # o token vence de hora em hora e a renovação também leva 429 quando a cota da empresa acabou
    fracttal(_um_por_dia(), roteiro_token=lambda n: 429 if n == 0 else None)
    assert DEVEM_ESTAR <= set(app._frac_disp_sweep(LIMITE))
    assert fracttal.esperas == [5]


def test_ordem_crescente_e_recusada(fracttal):
    # o limite só funciona com a lista DESC: crescente, a 1ª página (as OS mais velhas) já "passaria do limite"
    fracttal(_um_por_dia(), ascendente=True)
    with pytest.raises(RuntimeError, match="ordem"):
        app._frac_disp_sweep(LIMITE)


def test_teto_de_linhas_sem_chegar_ao_limite_e_falha(fracttal, monkeypatch):
    monkeypatch.setattr(app, "FRAC_DISP_TETO_LINHAS", 9, raising=False)
    fracttal(_um_por_dia())
    with pytest.raises(RuntimeError, match="sem chegar"):
        app._frac_disp_sweep(LIMITE)


def test_web_continua_sem_esperar_no_429(fracttal):
    # quem chama o _frac_get sem pedir paciência (as rotas do web) segue recebendo None na hora: esperar o reset
    # prenderia uma linha do waitress por até 1 min. O motivo fica disponível para quem pedir.
    falso = fracttal(_um_por_dia(), roteiro=lambda n: 429)
    motivo = {}
    assert app._frac_get("work_orders/", _motivo=motivo, start=0, limit=200) is None
    assert fracttal.esperas == [] and len(falso.gets) == 1
    assert (motivo.get("status"), motivo.get("reset")) == (429, "37")


def test_motivo_so_entra_pelo_nome(fracttal):
    # um 2º argumento posicional por engano não pode virar o `_motivo` em silêncio (a outra sessão chama o _frac_get)
    fracttal(_um_por_dia())
    with pytest.raises(TypeError):
        app._frac_get("work_orders/", {"start": 0})


# ── recálculo, arquivo e rota ─────────────────────────────────────────────────────────────────
EQUIP = [
    {"cliente": "TesteCo", "usina": "Alfa", "usina_fracttal": "TesteCo - Alfa 1 - SP",
     "equipamento": "UFV", "pot_kwp": 1000.0, "n_inv": 2, "full_om": "Sim"},
]
MESES = [("2026-09", datetime(2026, 9, 1), datetime(2026, 9, 21)),
         ("2026-08", datetime(2026, 8, 1), datetime(2026, 9, 1))]          # limite = 01/08 − 45 d = 17/06


@pytest.fixture
def ambiente(monkeypatch, tmp_path, fracttal):
    """Worker e web apontando para uma pasta temporária; planilha e banco fora (catálogo mínimo, sem geração)."""
    logs = []
    monkeypatch.setattr(app, "FRACTTAL_ON", True)
    monkeypatch.setattr(app, "_FRAC_DISP_FILE", str(tmp_path / "frac_disp_index.json"))
    monkeypatch.setattr(app, "_FRAC_DISP_STATUS", str(tmp_path / "frac_disp_status.json"), raising=False)
    monkeypatch.setattr(app, "_frac_disp_mem", {"mtime": 0.0, "dados": {}})
    monkeypatch.setattr(app, "_disp_meses_alvo", lambda hoje=None: MESES)
    monkeypatch.setattr(app, "_disp_equip_linhas", lambda: EQUIP)
    monkeypatch.setattr(app, "_disp_geracao", lambda *a, **k: {})
    monkeypatch.setattr(app, "_log_arquivo", lambda nome, msg: logs.append((nome, msg)))
    monkeypatch.setattr(app, "_DISP_GER_ULTIMA", {})          # a aba Falhas lê isto: não vazar a geração falsa
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    return {"dir": tmp_path, "logs": logs, "fracttal": fracttal, "web": app.app.test_client()}


def _indice_bom(tmp_path):
    """O índice que estava no ar antes: uma OS só (999), publicada às 16:55 UTC de 28/09."""
    from disponibilidade import calcular
    wos = {"999": [_tarefa(999, "2026-09-05T12:00:00+00:00", evento="2026-09-05T12:00:00+00:00",
                           fim="2026-09-05T15:00:00+00:00")]}
    dados = {"ts": 1790614551.0, "meses": {rot: calcular(wos, EQUIP, ini, fim, agora=datetime(2026, 9, 28, 12))
                                           for rot, ini, fim in MESES}}
    p = tmp_path / "frac_disp_index.json"
    p.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return p.read_bytes()


def _tres_os():
    return [_tarefa(2000, "2026-09-10T12:00:00+00:00", evento="2026-09-10T12:00:00+00:00",
                    fim="2026-09-10T15:00:00+00:00"),
            _tarefa(2001, "2026-08-20T12:00:00+00:00", evento="2026-08-20T12:00:00+00:00",
                    fim="2026-08-20T13:00:00+00:00"),
            _tarefa(2002, "2026-06-01T12:00:00+00:00", evento="2026-06-01T12:00:00+00:00",
                    fim="2026-06-01T13:00:00+00:00")]


def _status(amb):
    return json.loads((amb["dir"] / "frac_disp_status.json").read_text(encoding="utf-8"))


def test_varredura_que_falha_nao_toca_no_indice_e_avisa(ambiente):
    antes = _indice_bom(ambiente["dir"])
    ambiente["fracttal"](_tres_os(), tam=1, roteiro=lambda n: 429 if n >= 1 else None)
    app._frac_disp_recalcular()
    assert (ambiente["dir"] / "frac_disp_index.json").read_bytes() == antes     # o índice bom fica
    nome, msg = ambiente["logs"][-1]                                             # e a falha aparece
    assert nome == "fracttal.log" and "429" in msg and "índice anterior mantido" in msg
    st = _status(ambiente)
    assert st["ok"] is False and "429" in st["erro"]
    assert (st["varredura"]["paginas"], st["varredura"]["esperas"]) == (1, 31)   # até onde foi: 1 página, 31 × 38 s
    d = ambiente["web"].get("/api/gerencial/disponibilidade?mes=2026-09").get_json()
    assert d["quente"] is True and [o["folio"] for o in d["oss"]] == [999]
    assert d["ultima_tentativa"]["ok"] is False and "429" in d["ultima_tentativa"]["erro"]


def test_varredura_vazia_nao_publica_indice_vazio(ambiente):
    antes = _indice_bom(ambiente["dir"])
    ambiente["fracttal"]([])
    app._frac_disp_recalcular()
    assert (ambiente["dir"] / "frac_disp_index.json").read_bytes() == antes
    assert _status(ambiente)["ok"] is False


def test_mes_que_falha_no_calculo_nao_publica_os_outros(ambiente, monkeypatch):
    # índice com um mês a menos também é parcial: o _religamentos_abertos_usina perderia as OS daquele mês
    antes = _indice_bom(ambiente["dir"])
    real = app._disp_mod.calcular

    def _calc(wos, equip, ini, fim, **k):
        if ini == datetime(2026, 8, 1):
            raise ValueError("data torta numa OS de agosto")
        return real(wos, equip, ini, fim, **k)
    monkeypatch.setattr(app._disp_mod, "calcular", _calc)
    ambiente["fracttal"](_tres_os(), tam=2)
    app._frac_disp_recalcular()
    assert (ambiente["dir"] / "frac_disp_index.json").read_bytes() == antes
    st = _status(ambiente)
    assert st["ok"] is False and "2026-08" in st["erro"]


def test_dia_1_com_o_mes_corrente_vazio_publica(ambiente, monkeypatch):
    # no dia 1 o mês corrente não tem dia fechado e vai vazio de propósito: isso não é falha de cálculo
    monkeypatch.setattr(app, "_disp_meses_alvo", lambda hoje=None: [
        ("2026-10", datetime(2026, 10, 1), datetime(2026, 10, 1)),
        ("2026-09", datetime(2026, 9, 1), datetime(2026, 10, 1))])
    ambiente["fracttal"](_tres_os(), tam=2)
    app._frac_disp_recalcular()
    idx = json.loads((ambiente["dir"] / "frac_disp_index.json").read_text(encoding="utf-8"))
    assert sorted(idx["meses"]) == ["2026-09", "2026-10"] and idx["meses"]["2026-10"]["periodo"]["dias"] == 0
    assert _status(ambiente)["ok"] is True


class _Parou(Exception):
    pass


def test_laco_registra_a_falha_que_escapa_do_recalculo(ambiente, monkeypatch):
    # ex.: o Windows/OneDrive trancando o arquivo na hora de gravar — o status não pode seguir dizendo "ok" antigo
    (ambiente["dir"] / "frac_disp_status.json").write_text(json.dumps({"ok": True, "ts": 1.0, "erro": None}),
                                                           encoding="utf-8")
    monkeypatch.setattr(app, "_FRAC_DISP_FILE", str(ambiente["dir"] / "nao_existe" / "frac_disp_index.json"))
    ambiente["fracttal"](_tres_os(), tam=2)
    principal, sono = threading.current_thread(), app.time.sleep

    def _sono(s):
        if s == app.FRAC_DISP_TTL and threading.current_thread() is principal:
            raise _Parou                   # uma volta só do laço
        return sono(s)
    monkeypatch.setattr(app.time, "sleep", _sono)
    with pytest.raises(_Parou):
        app._frac_disp_loop()
    st = _status(ambiente)
    assert st["ok"] is False and "FileNotFoundError" in st["erro"]


def test_varredura_inteira_publica_diz_ate_onde_leu_e_limpa_o_aviso(ambiente):
    _indice_bom(ambiente["dir"])
    (ambiente["dir"] / "frac_disp_status.json").write_text(
        json.dumps({"ok": False, "ts": 1790614551.0, "erro": "429 na página 3"}), encoding="utf-8")
    ambiente["fracttal"](_tres_os(), tam=2, roteiro=lambda n: 429 if n == 1 else None)
    app._frac_disp_recalcular()
    idx = json.loads((ambiente["dir"] / "frac_disp_index.json").read_text(encoding="utf-8"))
    v = idx.get("varredura") or {}
    assert tuple(v.get(k) for k in ("paginas", "linhas", "oss", "ate", "limite", "esperas", "espera_s")) == \
        (2, 3, 3, "2026-06-01", "2026-06-17", 1, 38)
    assert any(o["folio"] == 2000 for o in idx["meses"]["2026-09"]["oss"])
    d = ambiente["web"].get("/api/gerencial/disponibilidade?mes=2026-09").get_json()
    assert d["ultima_tentativa"]["ok"] is True and not d["ultima_tentativa"].get("erro")
    assert d["varredura"]["ate"] == "2026-06-01"
    assert any(o["folio"] == 2000 for o in d["oss"])
    assert ambiente["logs"] and ambiente["logs"][-1][0] == "fracttal.log"      # a volta também fica registrada
