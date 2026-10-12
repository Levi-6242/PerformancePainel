# -*- coding: utf-8 -*-
"""Teto de memória dos caches do worker que cresciam sem limite (11/10/2026).

O caso: o worker subiu às ~00:39 de 11/10 (reinício do PC) e às 22:52 estava com 5,5 GB, deixando 0,3 GB livres de 20
no PC — o mesmo que travou na noite anterior, a hora do fechamento das 23:30 (coleta da API PV e recálculo do BD_Thopen
por Excel COM). Cada restart do worker voltava a passar de 3 GB em 15 min.

O que estes testes travam é o TETO de cada cache, e que o teto não muda número: o que sai do cache é dia FECHADO, que
volta igual se alguém pedir de novo (custa uma busca, não um número diferente).
"""
import threading
import time
from datetime import datetime, timedelta

import pytest

import app


# ── dublê da API PV (/trackers) ───────────────────────────────────────────────────────────────────────────────────────
def _dia(n_trk, n_leit, data_iso, alvo=False):
    out = []
    for i in range(n_leit):
        h, m = 6 + i // 60, i % 60
        trks = [{f"TRK{t + 1}": {"posAg": float(t + i), "posAl": float(t), "aComm": 0}} for t in range(n_trk)]
        out.append({"tsleitura": f"{data_iso} {h:02d}:{m:02d}:00", "conteudojson": {"Trackers": trks}})
    return out


class _Resp:
    status_code = 200

    def __init__(self, corpo):
        self._c = corpo

    def json(self):
        return self._c


class _ApiPV:
    """Responde o dia de qualquer usina: n_trk trackers × n_leit leituras (pontos por entrada = n_trk × n_leit)."""

    def __init__(self, n_trk=4, n_leit=10):
        self.n_trk, self.n_leit, self.pedidos = n_trk, n_leit, []

    def post(self, url, headers=None, json=None, timeout=None):
        self.pedidos.append((json["idusina"], json["date"]))
        iso = datetime.strptime(json["date"], "%d/%m/%Y").strftime("%Y-%m-%d")
        return _Resp(_dia(self.n_trk, self.n_leit, iso))


@pytest.fixture
def api(monkeypatch):
    s = _ApiPV()
    monkeypatch.setattr(app, "_http", lambda: s)
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "tok")
    monkeypatch.setattr(app, "_pv_trk_dia_cache", {})
    monkeypatch.setattr(app, "_pv_trk_dia_locks", {})
    return s


def _br(dias_atras):
    return (datetime.now() - timedelta(days=dias_atras)).strftime("%d/%m/%Y")


def _pontos_passados():
    hoje = datetime.now().strftime("%d/%m/%Y")
    return sum(app._pv_trk_dia_pontos(e) for (pid, data), e in app._pv_trk_dia_cache.items() if data != hoje)


# ── 1. o dia de trackers da API PV (_pv_trk_dia_cache) ───────────────────────────────────────────────────────────────
def test_dia_passado_nao_passa_do_teto_de_pontos(api, monkeypatch):
    """O backfill do mês e o aquecimento das ocorrências enchiam o cache com dia passado — que nunca vencia — e o
    worker passava de 3 GB em 15 min depois de cada restart. Com o teto, o cache de dias passados não passa dele em
    NENHUM momento (a poda é na hora de guardar, não só a cada 10 min do faxineiro)."""
    monkeypatch.setattr(app, "PV_TRK_DIA_TETO_PONTOS", 3 * 40)        # 3 entradas de 4 trackers × 10 leituras
    for k in range(10, 1, -1):
        app._pv_trk_dia(1, _br(k), fetch=True)
        assert _pontos_passados() <= app.PV_TRK_DIA_TETO_PONTOS
    assert len(app._pv_trk_dia_cache) == 3


def test_o_par_relido_fica_e_a_varredura_de_uma_vez_sai(api, monkeypatch):
    """Quem relê dia passado no worker é o backfill da hora: os mesmos pares (usina, dia) de cobertura baixa, de julho a
    outubro, a cada volta. Quem lê UMA vez é a varredura — o aquecimento do D-1, o das ocorrências da 2C (julho), o dia
    de ontem que virou passado à meia-noite. Passou do teto, sai a varredura; o par relido fica, senão cada volta o
    rebaixaria da API PV (paga). Nem "o mais antigo primeiro" (os relidos SÃO os antigos) nem LRU puro serviam."""
    monkeypatch.setattr(app, "PV_TRK_DIA_TETO_PONTOS", 3 * 40)
    relidos = [(1, _br(90)), (2, _br(60))]                           # pares antigos que o backfill relê
    for pid, data in relidos:
        app._pv_trk_dia(pid, data, fetch=True)
        app._pv_trk_dia(pid, data, fetch=True)                       # a volta seguinte relê do cache
    for k in range(2, 9):                                             # a varredura: um dia por vez, lido uma vez
        app._pv_trk_dia(9, _br(k), fetch=True)
        assert _pontos_passados() <= app.PV_TRK_DIA_TETO_PONTOS
    for chave in relidos:
        assert chave in app._pv_trk_dia_cache, f"o par relido {chave} saiu para dar lugar à varredura"
    pedidos = len(api.pedidos)
    for pid, data in relidos:
        app._pv_trk_dia(pid, data, fetch=True)
    assert len(api.pedidos) == pedidos, "o par relido foi rebaixado da API"


def test_o_dia_de_hoje_fica_fora_do_teto(api, monkeypatch):
    """Hoje é o que a tela, a ronda e a Entrada leem a cada volta; o TTL de 30 min dele já o renova. O teto vale só
    para o passado — senão a varredura de hoje despejaria a si mesma no meio."""
    monkeypatch.setattr(app, "PV_TRK_DIA_TETO_PONTOS", 40)
    api.n_trk = 50                                                    # hoje sozinho já é 12× o teto
    hoje = datetime.now().strftime("%d/%m/%Y")
    for pid in range(1, 6):
        app._pv_trk_dia(pid, hoje, fetch=True)
    assert len(app._pv_trk_dia_cache) == 5, "o teto do passado não pode tirar entrada de hoje"
    api.n_trk = 4
    app._pv_trk_dia(9, _br(3), fetch=True)
    assert (9, _br(3)) in app._pv_trk_dia_cache, "hoje não conta no teto do passado"


def test_dia_passado_ocioso_sai_no_faxineiro(api, monkeypatch):
    """Dia passado que ninguém pede há PV_TRK_DIA_OCIOSO_S sai, mesmo abaixo do teto: é o D-1 que o aquecimento do
    boot baixou e ninguém mais leu. O que segue em uso (o backfill da hora relendo o mesmo par) fica."""
    app._pv_trk_dia(1, _br(2), fetch=True)
    app._pv_trk_dia(2, _br(2), fetch=True)
    hoje = datetime.now().strftime("%d/%m/%Y")
    app._pv_trk_dia(3, hoje, fetch=True)
    velho = time.time() - app.PV_TRK_DIA_OCIOSO_S - 60
    for k in ((1, _br(2)), (3, hoje)):
        app._pv_trk_dia_cache[k]["ts"] = velho
        app._pv_trk_dia_cache[k].pop("uso", None)
    app._janitor_passada()
    assert (1, _br(2)) not in app._pv_trk_dia_cache, "dia passado ocioso ficou"
    assert (2, _br(2)) in app._pv_trk_dia_cache, "dia passado em uso saiu"
    assert (3, hoje) in app._pv_trk_dia_cache, "hoje não sai por ociosidade (o TTL de 30 min é quem o renova)"


def test_ler_do_cache_conta_como_uso(api, monkeypatch):
    """O backfill da hora relê os mesmos pares de cobertura baixa; sem marcar o uso, a ociosidade os tiraria e a
    volta seguinte baixaria de novo da API PV (que é paga)."""
    app._pv_trk_dia(1, _br(5), fetch=True)
    app._pv_trk_dia_cache[(1, _br(5))]["ts"] = time.time() - app.PV_TRK_DIA_OCIOSO_S - 60
    app._pv_trk_dia(1, _br(5), fetch=True)                            # acerto no cache
    assert len(api.pedidos) == 1, "dia fechado em cache não pode ir à API"
    app._janitor_passada()
    assert (1, _br(5)) in app._pv_trk_dia_cache


def test_a_curva_que_volta_depois_da_poda_e_a_mesma(api, monkeypatch):
    """O teto não muda número: o dia que saiu volta IGUAL quando pedido de novo. Custa uma busca (a contagem prova
    que é uma só), não uma curva diferente."""
    c1 = app._pv_trk_dia(7, _br(6), fetch=True)
    monkeypatch.setattr(app, "PV_TRK_DIA_TETO_PONTOS", 0)
    app._pv_trk_dia_poda()
    assert (7, _br(6)) not in app._pv_trk_dia_cache
    c2 = app._pv_trk_dia(7, _br(6), fetch=True)
    assert c2["curva"] == c1["curva"] and c2["ultima"] == c1["ultima"] and c2["ultima_ts"] == c1["ultima_ts"]
    assert api.pedidos.count((7, _br(6))) == 2


def test_dia_fechado_em_cache_segue_sem_vencer_na_leitura(api):
    """A regra de 22/09 continua: LER um dia fechado do cache nunca o expira (fetch=False devolve o que tem). Quem
    tira é só a poda — por teto ou por ociosidade —, nunca a leitura."""
    d = {"curva": {"TRK1": [{"x": "2026-09-20 10:00", "y": 1.0}]}, "ultima": {"TRK1": {}}, "ultima_ts": "x"}
    app._pv_trk_dia_cache[(1, "20/09/2026")] = {"ts": time.time() - 99999, "d": d}
    assert app._pv_trk_dia(1, "20/09/2026", fetch=False)["curva"]


def test_lock_orfao_do_dia_sai_e_o_de_quem_busca_fica(api):
    """Um Lock por (usina, dia), para sempre — o mesmo defeito que o faxineiro já tirava do gráfico de trackers."""
    em_uso, livre = threading.Lock(), threading.Lock()
    em_uso.acquire()
    app._pv_trk_dia_locks[(1, _br(3))] = em_uso
    app._pv_trk_dia_locks[(2, _br(3))] = livre
    try:
        app._pv_trk_dia_poda()
        assert (1, _br(3)) in app._pv_trk_dia_locks, "tirou o lock de uma busca em curso (busca dobrada na API)"
        assert (2, _br(3)) not in app._pv_trk_dia_locks
    finally:
        em_uso.release()


def test_o_teto_padrao_cabe_os_pares_relidos_e_fica_longe_de_um_dia_inteiro():
    """Medido dentro do worker em 11–12/10/2026: o dia inteiro (86 entradas) era 3,9 milhões de pontos; os pares de
    cobertura baixa que o backfill da hora relê, 2–7 mil pontos cada (~1.263 pares sem classe, ~160 deles com curva);
    a maior planta-dia (2C, curva e alvo de minuto em minuto), 273 mil. O teto cabe os relidos com folga e fica bem
    abaixo de um dia inteiro, que é justamente o que se acumulava a cada meia-noite."""
    assert 160 * 7_000 <= app.PV_TRK_DIA_TETO_PONTOS <= 3_900_000 // 2


class _ApiPVDeterministica:
    """O dia de cada (usina, data) é sempre o mesmo, em qualquer ordem de pedido: a rodada sem teto e a com teto recebem
    EXATAMENTE o mesmo dado. Um tracker em cada cinco fica parado a 5° (a régua tem o que classificar), e um trecho da
    manhã falta (episódio que volta)."""

    def __init__(self):
        self.pedidos = []

    def post(self, url, headers=None, json=None, timeout=None):
        import random
        import zlib
        pid, data = json["idusina"], json["date"]
        self.pedidos.append((pid, data))
        iso = datetime.strptime(data, "%d/%m/%Y").strftime("%Y-%m-%d")
        rnd = random.Random(zlib.crc32(f"{pid}|{iso}".encode()))
        out = []
        for i in range(0, 24 * 60, 5):
            ang = 0.0 if not 360 <= i <= 1080 else 55.0 * ((i - 720) / 360)
            trks = []
            for t in range(10):
                parado = t % 5 == 2 or (t == 7 and 600 <= i <= 690)          # TRK3/TRK8 parados; TRK8 volta às 11:30
                trks.append({f"TRK{t + 1}": {"posAg": round((5.0 if parado else ang) + rnd.uniform(-0.5, 0.5), 2),
                                             "posAl": round(ang, 2), "aComm": 0}})
            out.append({"tsleitura": f"{iso} {i // 60:02d}:{i % 60:02d}:00", "conteudojson": {"Trackers": trks}})
        rnd.shuffle(out)
        return _Resp(out)


def _rodada_backfill(monkeypatch, teto, ocioso):
    """O backfill de eventos do PV em 4 usinas × 6 dias passados, duas voltas (a da hora seguinte relê tudo com force),
    com o teto dado. Devolve (acervo de eventos, curvas servidas, nº de pedidos à API)."""
    import copy
    s = _ApiPVDeterministica()
    monkeypatch.setattr(app, "_http", lambda: s)
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "tok")
    monkeypatch.setattr(app, "_pv_trk_dia_cache", {})
    monkeypatch.setattr(app, "_pv_trk_dia_locks", {})
    monkeypatch.setattr(app, "_pv_trk_graf_cache", {})
    monkeypatch.setattr(app, "_trk_eventos", {})
    monkeypatch.setattr(app, "_build_pv_trk_payload", lambda *a, **k: {})
    monkeypatch.setattr(app, "_pv_trk_plant", {pid: {"ts": time.time(), "payload": {"total": 10, "usina": f"Usina {pid}"}}
                                               for pid in (101, 102, 103, 104)})
    monkeypatch.setattr(app, "PV_TRK_DIA_TETO_PONTOS", teto)
    monkeypatch.setattr(app, "PV_TRK_DIA_OCIOSO_S", ocioso)
    ini = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    fim = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    for _volta in range(2):
        app._trk_ev_backfill(ini, fim, force=True)
        for dia in list(app._trk_eventos):                      # a volta seguinte reprocessa (régua "antiga")
            for e in app._trk_eventos[dia].values():
                e["regua"] = "outra"
    acervo = {d: {p: {k: e.get(k) for k in ("classes", "eventos", "cobertura", "disponibilidade", "sem_comunicacao")}
                  for p, e in ent.items()} for d, ent in app._trk_eventos.items()}
    curvas = {(pid, k): copy.deepcopy(app._pv_trk_dia(pid, _br(k), fetch=True)["curva"])
              for pid in (101, 102, 103, 104) for k in range(2, 8)}
    return acervo, curvas, len(s.pedidos)


def test_o_teto_nao_muda_o_acervo_de_eventos_nem_a_curva(monkeypatch):
    """A prova de que o teto não muda número: o MESMO backfill (o do boot e o da hora, com force), com o teto desligado
    (como era) e com um teto que despeja a cada dia guardado. O acervo de eventos — que o web lê do disco e vira as
    Ocorrências, o book de paradas e a disponibilidade por tempo — e as curvas servidas saem idênticos. A diferença é
    só de custo: com o teto, o dia que saiu é buscado de novo."""
    sem_teto = _rodada_backfill(monkeypatch, teto=10 ** 12, ocioso=10 ** 9)
    com_teto = _rodada_backfill(monkeypatch, teto=300, ocioso=10 ** 9)   # 300 pontos: menos de um dia de uma usina
    assert sem_teto[0], "o backfill não gravou nada: o teste não provaria coisa alguma"
    assert any((e.get("classes") or {}) for ent in sem_teto[0].values() for e in ent.values()), \
        "nenhuma classificação no acervo: a régua não teve o que classificar"
    assert com_teto[0] == sem_teto[0], "o teto mudou o acervo de eventos"
    assert com_teto[1] == sem_teto[1], "o teto mudou a curva servida"
    assert com_teto[2] > sem_teto[2], "com o teto, o dia que saiu tem de ser buscado de novo (senão o teto não agiu)"


# ── 2. o memo do dia da 2C (_2c_trk_api_memo) e o "dia veio vazio" (_2c_trk_vazio) ──────────────────────────────────
def _curva_2c(*a, **k):
    return {"curva": {"TRK1": [{"x": "2026-10-11 10:00", "y": 1.0}]}, "alvo": {"TRK1": [{"x": "2026-10-11 10:00", "y": 1.0}]},
            "ultima": {}, "ultima_ts": None}


def test_memo_da_2c_nao_guarda_o_que_nao_serve_mais(monkeypatch):
    """O memo existe para não remontar o dia a cada código dentro de 60 s; quem lê não aceita entrada mais velha que
    isso. Mas cada DATA ficava no dicionário para sempre — ~56 MB de tuplas (datetime, valor) por dia da 2C."""
    monkeypatch.setattr(app, "_pv_trk_dia", _curva_2c)
    monkeypatch.setattr(app, "_2c_trk_api_memo", {"2026-09-01": (time.time() - 3600, {"ARA": {}}),
                                                  "2026-09-02": (time.time() - 5, {"ARA": {}})})
    app._2c_trk_build_api("2026-10-11")
    assert "2026-09-01" not in app._2c_trk_api_memo, "entrada vencida (que ninguém lê) ficou"
    assert "2026-09-02" in app._2c_trk_api_memo, "entrada ainda válida saiu"
    assert "2026-10-11" in app._2c_trk_api_memo


def test_memo_da_2c_serve_igual_dentro_dos_60_s(monkeypatch):
    """A poda não muda o que o memo serve: dentro da validade, a mesma resposta sem remontar."""
    chamadas = []

    def _conta(*a, **k):
        chamadas.append(a)
        return _curva_2c()
    monkeypatch.setattr(app, "_pv_trk_dia", _conta)
    monkeypatch.setattr(app, "_2c_trk_api_memo", {})
    r1 = app._2c_trk_build_api("2026-10-11")
    n = len(chamadas)
    r2 = app._2c_trk_build_api("2026-10-11")
    assert r2 == r1 and len(chamadas) == n


def test_dia_vazio_da_2c_nao_acumula(monkeypatch):
    """A marca de "veio vazio" só vale 5 min para quem lê; passava a valer para sempre no dicionário."""
    agora = datetime(2026, 10, 11, 10, 0)
    monkeypatch.setattr(app, "_pv_trk_dia", lambda *a, **k: {"curva": {}, "ultima": {}, "ultima_ts": None})
    monkeypatch.setattr(app, "_pv_trk_dia_cache", {})
    monkeypatch.setattr(app, "_2c_trk_vazio", {(1, "01/09/2026"): time.time() - 3600})
    app._2c_trk_renova_dias(agora)
    assert (1, "01/09/2026") not in app._2c_trk_vazio
    assert any(k[1] == "11/10/2026" for k in app._2c_trk_vazio), "o vazio de hoje tem de ficar (é a espera de 5 min)"
