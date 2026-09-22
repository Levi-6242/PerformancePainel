# -*- coding: utf-8 -*-
"""Trackers pela API PV FIXA, não mais pela PV Plataforma (Levi, 22/09/2026).

O pedido: *"não é para precisar disso [do bookmarklet] pois já temos a API fixa da PV Operation,
tanto para trackers quanto para strings e combiner box"*. Ele estava certo, e o próprio código
afirmava o contrário — havia um comentário garantindo que "a API PV (apipv) NÃO expõe posição de
tracker; o dado só existe na PV Plataforma". Expõe: `POST /api/v1/trackers {idusina, date:DD/MM/AAAA}`.

Medido em Brodowski - Skid 2 (297378) em 22/09/2026, antes de trocar:
  - snapshot: 52/52 trackers com `posAg`, `posAl` e `aComm` IDÊNTICOS, mesmo carimbo (10:21:00);
  - curva do dia: 29.551 de 29.551 pontos idênticos, maior diferença 0,000°;
  - UMA chamada de 3,3 s no lugar de duas (snapshot 0,4 s + trackerschart 4,2 s).

E dois ganhos que não estavam no pedido:
  1. **4 trackers apareceram.** A Plataforma entrega os trackers agrupados POR INVERSOR, e o TRK41
     ao TRK44 de Brodowski não estão vinculados a inversor nenhum no cadastro dela — a varredura
     atual lê `dados[].trackers` e vê 48, enquanto o `dadosGerais` da mesma resposta tem 52. Some
     tracker de verdade, e a régua de frota parada conta sobre o total errado.
  2. O carimbo é Brasília nas duas pontas. O `x` do trackerschart diz "GMT" e MENTE (00:20 GMT com
     sol de Brasília); o `tsleitura` da API PV é Brasília honesto. Bate minuto a minuto — mas só
     porque nenhum dos dois é convertido. Converter o `tsleitura` como UTC recria o incidente de
     22/09, quando o servidor em UTC deixou 108 usinas "sem comunicação".

O que este arquivo trava é o PARSER, que é onde a troca pode errar em silêncio.
"""
import app


def _leitura(ts, **trks):
    """Uma leitura como a API PV entrega: lista de dicts de um item só, {"TRKn": {...}}."""
    return {"tsleitura": ts,
            "conteudojson": {"Trackers": [{n: v} for n, v in trks.items()]}}


def _trk(posAg, posAl=0.0, aComm=0):
    return {"posAg": posAg, "posAl": posAl, "aComm": aComm, "sTrkOK": 1, "crgBat": 64.0}


DIA = [
    _leitura("2026-09-22 08:00:00", TRK1=_trk(-30.0), TRK2=_trk(-29.8)),
    _leitura("2026-09-22 08:05:00", TRK1=_trk(-25.0), TRK2=_trk(-24.9)),
    _leitura("2026-09-22 10:21:00", TRK1=_trk(0.71),  TRK2=_trk(-0.80)),
]


# ── a curva ───────────────────────────────────────────────────────────────────

def test_a_curva_sai_no_formato_do_trackerschart():
    """O consumidor espera {tracker: [{"x","y"}]}. Trocar a fonte não pode mudar essa forma, senão a
    régua de parado/severo para de enxergar a curva."""
    c = app._pv_trk_parse_dia(DIA)["curva"]
    assert set(c) == {"TRK1", "TRK2"}
    assert c["TRK1"] == [{"x": "2026-09-22 08:00", "y": -30.0}, {"x": "2026-09-22 08:05", "y": -25.0},
                         {"x": "2026-09-22 10:21", "y": 0.71}]


def test_o_x_CARREGA_A_DATA_por_causa_do_grafico_multidia():
    """Só "HH:MM" seria uma regressão silenciosa: o gráfico e o CSV aceitam ?ini=&fim= e concatenam
    vários dias numa série só. Sem data, 10:21 de dois dias diferentes colidem. O carimbo longo do
    trackerschart carregava a data — este tem de carregar também."""
    dia20 = [_leitura("2026-09-20 10:21:00", TRK1=_trk(1.0))]
    dia21 = [_leitura("2026-09-21 10:21:00", TRK1=_trk(2.0))]
    xs = [p["x"] for p in app._pv_trk_parse_dia(dia20)["curva"]["TRK1"]
                      + app._pv_trk_parse_dia(dia21)["curva"]["TRK1"]]
    assert len(set(xs)) == 2, "dois dias viraram o mesmo ponto no eixo"


def test_os_dois_parsers_de_hora_que_existem_continuam_achando_a_hora():
    r"""A troca de formato é segura só porque `_trk_mins` (backend) e `fmtHora` (painel) leem o
    PRIMEIRO \d{1,2}:\d{2}. Se algum dia um deles mudar, é aqui que se descobre."""
    import re
    x = app._pv_trk_parse_dia(DIA)["curva"]["TRK1"][-1]["x"]
    assert app._trk_mins(x) == 10 * 60 + 21
    assert re.search(r"(\d{1,2}:\d{2})(?::\d{2})?", x).group(1) == "10:21"   # regex literal do fmtHora


def test_a_curva_sai_ordenada_no_tempo():
    """A API devolve as leituras FORA DE ORDEM (medido: d[0] era 05:11 num dia que começa 00:00).
    A régua de amplitude e de freeze lê a sequência como série temporal — desordenada, um tracker
    saudável vira 'salto de recuperação'."""
    c = app._pv_trk_parse_dia(list(reversed(DIA)))["curva"]
    assert [p["x"][-5:] for p in c["TRK1"]] == ["08:00", "08:05", "10:21"]


def test_o_carimbo_e_brasilia_e_NAO_se_converte():
    """`tsleitura` já vem em Brasília. Tratar como UTC desloca a curva 3 h e recria o incidente do
    servidor: leitura fresca lida como velha, usina marcada 'sem comunicação', strings suprimidas."""
    assert app._pv_trk_parse_dia(DIA)["curva"]["TRK1"][-1]["x"] == "2026-09-22 10:21"


# ── o instantâneo ─────────────────────────────────────────────────────────────

def test_o_instantaneo_e_a_leitura_MAIS_NOVA_nao_a_primeira():
    d = app._pv_trk_parse_dia(DIA)
    assert d["ultima_ts"] == "2026-09-22 10:21:00"
    assert d["ultima"]["TRK1"]["posAg"] == 0.71


def test_o_instantaneo_traz_alvo_e_comunicacao():
    """Os três campos que a régua usa: posição, alvo e o aComm que marca 'sem comunicação'."""
    dia = [_leitura("2026-09-22 10:21:00", TRK9=_trk(0.0, posAl=0.0, aComm=1))]
    u = app._pv_trk_parse_dia(dia)["ultima"]["TRK9"]
    assert (u["posAg"], u["posAl"], u["aComm"]) == (0.0, 0.0, 1)


def test_tracker_que_so_aparece_numa_leitura_nao_some():
    """Tracker mudo a manhã inteira que volta às 10:21 tem de entrar no instantâneo — é exatamente
    o que se quer enxergar."""
    dia = DIA + [_leitura("2026-09-22 10:21:00", TRK1=_trk(0.71), TRK99=_trk(0.5))]
    d = app._pv_trk_parse_dia(dia)
    assert "TRK99" in d["ultima"] and len(d["curva"]["TRK99"]) == 1


# ── o que a Plataforma perdia ─────────────────────────────────────────────────

def test_tracker_sem_inversor_vinculado_APARECE():
    """O ganho de cobertura: a API PV entrega lista PLANA, sem passar pelo vínculo com inversor que
    engolia TRK41..TRK44 em Brodowski. Nada no parser pode reintroduzir esse filtro."""
    dia = [_leitura("2026-09-22 10:21:00", **{f"TRK{i}": _trk(0.8) for i in range(41, 45)})]
    assert sorted(app._pv_trk_parse_dia(dia)["ultima"]) == ["TRK41", "TRK42", "TRK43", "TRK44"]


# ── o que não pode quebrar ────────────────────────────────────────────────────

def test_payload_vazio_devolve_vazio_e_nao_levanta():
    """Dia sem leitura (usina nova, madrugada) não é erro. Levantar aqui derrubaria a varredura
    inteira das 115 usinas por causa de uma."""
    for ruim in ([], None, {}, {"error": "Invalid period"}):
        d = app._pv_trk_parse_dia(ruim)
        assert d["curva"] == {} and d["ultima"] == {} and d["ultima_ts"] is None


def test_leitura_torta_e_PULADA_sem_derrubar_as_boas():
    """Um registro sem tsleitura ou sem Trackers não pode levar o dia junto."""
    dia = [{"tsleitura": None, "conteudojson": {"Trackers": []}},
           {"conteudojson": {"Trackers": [{"TRK1": _trk(9.9)}]}},          # sem ts
           {"tsleitura": "2026-09-22 09:00:00"},                            # sem conteudojson
           _leitura("2026-09-22 09:05:00", TRK1=_trk(1.5))]
    d = app._pv_trk_parse_dia(dia)
    assert d["curva"]["TRK1"] == [{"x": "2026-09-22 09:05", "y": 1.5}]
    assert d["ultima_ts"] == "2026-09-22 09:05:00"


def test_posicao_nula_entra_na_curva_como_None_e_nao_vira_zero():
    """Zero é um ângulo REAL (meio-dia). Trocar leitura ausente por 0.0 inventa um tracker no zênite
    e apaga justamente o sintoma de comunicação morta que a régua procura."""
    dia = [_leitura("2026-09-22 09:00:00", TRK1={"posAl": 0.0, "aComm": 1})]
    assert app._pv_trk_parse_dia(dia)["curva"]["TRK1"] == [{"x": "2026-09-22 09:00", "y": None}]


# ── o adaptador para o instantâneo ────────────────────────────────────────────
#   `_pv_trackers_analise` tem ~60 linhas de régua (mediana da frota, acumulador, cruzamento com
#   tickets) que já funcionam. Trocar a fonte por dentro dela seria reescrever a régua junto; em vez
#   disso o dia da API PV é NORMALIZADO para o formato que ela já lê. A régua não muda uma linha.

def test_o_adaptador_entrega_o_formato_que_a_regua_ja_le():
    d = app._pv_trk_parse_dia(DIA)
    j = app._pv_trk_j_da_api(d)
    assert j["ultimaLeitura"] == "2026-09-22 10:21:00"
    trks = [t for bloco in j["dados"] for t in bloco["trackers"]]
    assert {t["nome"] for t in trks} == {"TRK1", "TRK2"}
    um = next(t for t in trks if t["nome"] == "TRK1")
    assert um["ultimaleitura"]["posAg"] == 0.71 and um["ultimaleitura"]["posAl"] == 0.0


def test_o_adaptador_ordena_por_numero_nao_por_texto():
    """TRK10 depois de TRK9, não entre TRK1 e TRK2 — a mediana da frota e a tabela leem em ordem."""
    dia = [_leitura("2026-09-22 10:00:00", **{f"TRK{i}": _trk(0.5) for i in (1, 2, 9, 10, 41)})]
    j = app._pv_trk_j_da_api(app._pv_trk_parse_dia(dia))
    assert [t["nome"] for t in j["dados"][0]["trackers"]] == ["TRK1", "TRK2", "TRK9", "TRK10", "TRK41"]


def test_dia_vazio_vira_j_vazio_e_a_analise_devolve_a_base():
    """Sem leitura, o adaptador não pode inventar um `dados` com lista vazia que a régua leia como
    'usina com 0 trackers' — isso marcaria a usina como frota 100% parada."""
    j = app._pv_trk_j_da_api({"curva": {}, "ultima": {}, "ultima_ts": None})
    assert j == {}


# ── a tela de tokens ──────────────────────────────────────────────────────────

def test_o_PLAT_TOKEN_vencido_nao_alarma_mais(monkeypatch):
    """Consequência da troca, e o motivo de ela ter sido pedida: o token da Plataforma vence a cada
    7 dias e só se renova com alguém colando pelo bookmarklet. Num servidor sem ninguém na frente da
    tela isso alarmava para sempre. Agora ele é reserva — vencido, os trackers continuam vindo.

    Alarme que não se pode atender é alarme que se aprende a ignorar; foi assim que o SunOp gritou
    'VENCIDO' por semanas até a Athon subir muda sem ninguém olhar."""
    monkeypatch.setattr(app, "_plat_token", lambda: "", raising=False)
    linha = next(r for r in app._tokens_status()["tokens"] if r["fonte"] == "plat")
    assert linha["status"] != "vencido", "PLAT vencido voltou a alarmar"
    assert "reserva" in linha["dica"].lower() or "reserva" in linha["nome"].lower()


def test_o_token_de_API_do_sunop_continua_alarmando(monkeypatch):
    """A troca não pode rebaixar quem ainda derruba dado: sem o SUNOP_API_TOKEN a Athon fica muda."""
    monkeypatch.setattr(app, "_sunop_api_token", lambda inst: "", raising=False)
    linha = next(r for r in app._tokens_status()["tokens"] if r["fonte"] == "sunop_api")
    assert linha["tipo"] == "manual" and linha["status"] in ("vencido", "desconhecido")


# ── o TTL, que é uma decisão de CUSTO ─────────────────────────────────────────
#   A API PV só entrega o DIA INTEIRO: `last`, `limit`, `init/end`, `hora` e `ultima` foram todos
#   testados em 22/09 e IGNORADOS — as seis variantes devolveram as mesmas 610 leituras, 13,8 MB.
#   Então a única alavanca de custo é a frequência. Medido em 16 usinas com 8 workers:
#
#     antigo, instantâneo (a cada 5 min) .....  1,7 s ·   6,0 MB   (0,375 MB/usina)
#     antigo, curva (ronda de 30 min) ........ 45,1 s · 164,8 MB   (10,3 MB/usina)
#     novo, serve os DOIS .................... 27,2 s · 141,6 MB   (8,85 MB/usina)
#
#   Extrapolando para as ~80 usinas com tracker: hoje são ~2,0 GB/h (instantâneo de 5 em 5 min mais
#   a curva de 30 em 30). Buscando o dia a cada 5 min seriam ~8 GB/h — quatro vezes o de hoje, para
#   rebaixar 13 MB e ganhar duas leituras. A 30 min dá ~1,4 GB/h: MENOS tráfego que hoje, e some a
#   chamada separada de instantâneo.
#
#   O preço é frescor: o instantâneo do overview passa de ≤5 min para ≤30 min de idade. Não muda
#   decisão nenhuma — a leitura da usina vem de 2,5 em 2,5 min e a régua de parado trabalha em horas
#   — e o botão "Atualizar status" (force) continua buscando na hora.

def test_o_dia_de_hoje_tem_TTL_proprio_alinhado_a_ronda():
    """Se este número voltar para CACHE_TTL (5 min), o tráfego quadruplica em silêncio."""
    assert app.TRK_DIA_TTL == 1800


def test_dia_FECHADO_nao_expira():
    """O passado não muda. Rebuscar 13 MB por TTL vencido seria desperdício puro — é o mesmo
    cuidado que o cache do trackerschart já tinha."""
    import time as _t
    app._pv_trk_dia_cache.clear()
    d = {"curva": {"TRK1": [{"x": "2026-09-20 10:00", "y": 1.0}]}, "ultima": {"TRK1": {}}, "ultima_ts": "x"}
    app._pv_trk_dia_cache[(1, "20/09/2026")] = {"ts": _t.time() - 99999, "d": d}
    assert app._pv_trk_dia(1, "20/09/2026", fetch=False)["curva"], "dia fechado foi descartado do cache"


# ── os portões que zeravam a tela ─────────────────────────────────────────────
#   Seis endpoints começavam com `if not _plat_token(): return {"sem_token": True}` e devolviam
#   lista VAZIA. Era coerente quando a Plataforma era a única fonte; agora é um portão que tranca a
#   porta de uma casa que tem outra entrada — e tranca em silêncio, porque a tela mostra "sem token"
#   em vez de "sem dado", e quem lê vai renovar um token que não era o problema.

import pytest


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "", raising=False)
    monkeypatch.setattr(app, "_plat_token", lambda: "", raising=False)   # servidor sem bookmarklet
    app.app.config["TESTING"] = True
    with app.app.test_client() as c:
        yield c


@pytest.mark.parametrize("rota", [
    "/api/pv/trackers", "/api/semp/trackers", "/api/2capi/trackers",
    "/api/pv/trackers/parada", "/api/pv/trackers/parados",
])
def test_sem_PLAT_TOKEN_a_rota_nao_desiste(cliente, monkeypatch, rota):
    """Não afirma que virá dado (depende da rede) — afirma que a rota não desiste ANTES de tentar."""
    monkeypatch.setattr(app, "_build_pv_trk_payload", lambda *a, **k: {"rows": [], "summary": {}}, raising=False)
    monkeypatch.setattr(app, "_pv_trk_dia", lambda *a, **k: {"curva": {}, "ultima": {}, "ultima_ts": None}, raising=False)
    r = cliente.get(rota)
    assert r.status_code == 200
    assert not (r.get_json() or {}).get("sem_token"), f"{rota} ainda aborta por falta do PLAT_TOKEN"


# ── o defeito que a troca de fonte EXPÔS ──────────────────────────────────────
#   `_trk_classifica_curso(g, jini=6*60, jfim=18*60)` promete janela de geração 06–18 h, e a legacy
#   cumpre: recebe `jini, jfim`. A régua v2 — que é a que roda, com TRK_REGUA_V2 ligado — era
#   chamada como `_regua_v2(g)`, com a curva CRUA. A promessa da assinatura não valia para o
#   caminho em produção.
#
#   Ninguém tinha visto porque o trackerschart da Plataforma começa por volta de 00:20 e a madrugada
#   dele é plana. A API PV começa às 00:00, e esses 19 pontos a mais bastaram: em Brodowski - Skid 2,
#   TRK5, TRK34 e TRK48 passaram de 'parado' para 'normal' — mexendo o suficiente entre 00:00 e 00:19
#   (estacionamento noturno, valores de −10,8°) para a amplitude robusta deixar de ser plana.
#
#   O veredito certo é 'parado' nos três: a usina passou o dia inteiro travada perto de 0,7°.
#   Com a janela aplicada as duas fontes concordam em 52/52 — a troca fica neutra E o defeito sai.

def _curva(pontos):
    return {"TRK1": [{"x": f"2026-09-22 {h}", "y": y} for h, y in pontos]}


def test_movimento_de_MADRUGADA_nao_pode_salvar_um_tracker_parado():
    """O caso medido. Travado em 0,7° das 06 h às 17 h, com um solavanco às 00:18 — é um tracker
    parado, e a madrugada não tem por que opinar sobre rastreamento."""
    pontos = [("00:18", -10.85), ("00:19", -1.98)] + [(f"{h:02d}:00", 0.70) for h in range(6, 18)]
    r = app._trk_classifica_curso(_curva(pontos), usina="Brodowski - Skid 2")
    assert r["TRK1"] == "parado", f"madrugada salvou um tracker parado: {r}"


def test_quem_rastreia_de_verdade_continua_normal():
    """Guarda do outro lado: a janela não pode transformar frota saudável em parada."""
    pontos = [(f"{h:02d}:00", -50.0 + (h - 6) * 9.0) for h in range(6, 18)]
    r = app._trk_classifica_curso(_curva(pontos), usina="x")
    assert r["TRK1"] != "parado", f"tracker que girou 100 graus virou parado: {r}"


def test_a_janela_explicita_continua_valendo_para_a_v2():
    """Quem passa jini/jfim diferentes (relatórios de perdas) tem de ser obedecido também."""
    pontos = [("03:00", -40.0), ("04:00", 40.0)] + [(f"{h:02d}:00", 0.70) for h in range(6, 18)]
    fora = app._trk_classifica_curso(_curva(pontos), jini=6 * 60, jfim=18 * 60, usina="x")
    assert fora["TRK1"] == "parado", "a janela padrão não descartou 03–04 h"


def test_parados_rows_nao_desiste_sem_PLAT_TOKEN(monkeypatch):
    """O portão que escapou da primeira varredura: `_pv_parados_rows` devolvia [] SEM dizer
    "sem_token" — só uma lista vazia. Foi ele que deixou o alarme de frota parada mudo na validação
    ao vivo, com QUATRO usinas a 100% de trackers parados na tabela ao lado.

    Lista vazia por falta de um token de RESERVA é o pior formato de falha possível aqui: a tela
    mostra "nenhum tracker parado", que é indistinguível de "está tudo bem"."""
    monkeypatch.setattr(app, "_plat_token", lambda: "", raising=False)
    monkeypatch.setattr(app, "_pv_trk_plant", {1: {"usina": "X", "trackers": []}}, raising=False)
    monkeypatch.setattr(app, "get_plants", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(app, "get_token", lambda *a, **k: "t", raising=False)
    chamou = {"swr": 0}
    monkeypatch.setattr(app, "_swr", lambda *a, **k: chamou.__setitem__("swr", chamou["swr"] + 1), raising=False)
    err = {}
    app._pv_parados_rows(force=False, errout=err)
    assert err.get("erro") != "token da Plataforma ausente/vencido", "ainda desiste pelo token da reserva"


def test_a_frota_parada_enxerga_a_usina_toda_parada():
    """Ponta a ponta da régua com a fonte nova: 41 de 41 parados há 3 h é alarme."""
    rows = [{"usina": "Guatambu 4 (128)", "plant_id": "128", "tracker": f"TRK{i}", "horas_parado": 3.0}
            for i in range(1, 42)]
    r = app.frota_parada({"Guatambu 4 (128)": 41}, rows)
    assert len(r) == 1 and r[0]["alarme"] is True and r[0]["trackers"] == 41
