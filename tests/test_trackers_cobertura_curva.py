# -*- coding: utf-8 -*-
"""Curva do dia que cobre pouco não prova "parado" (28/09/2026).

Às 15:44 de 28/09 a rota /api/pg/trackers/parados listou os 48 trackers da Guaratinguetá V (Banco da Thopen,
plant_id 26) como parados. A usina só começou a reportar às 15:10: a curva tinha 9 pontos por tracker, e a frota
estava chegando ao batente oeste (mediana de 50,7° a 55,3°). Amplitude de 0,0° a 8,8° em 40 min — e a régua v2 chama
de parado ("cronico_travado") quem tem amplitude < 10°, sem perguntar quanto tempo a curva cobre. Às 16:2x, com mais
leitura, caiu para 1.

A guarda de cobertura já existia (TRK_COBERTURA_MIN_H, 4 h), mas só na pré-classificação dos motores — que o
`_trk_status_from_curva` sobrescreve com a régua. O registro diário (`_trk_eventos_do_dia`) já recusava dia com
cobertura < 0,5. Faltava a régua.

Regras do Levi que NÃO podem cair junto:
  * usina inteira parada continua aparecendo (SMP100/CPP100) — com curva que cobre o suficiente;
  * a frota girou e um tracker não → parado, mesmo cedo (a frota é a prova; é assim que se pega de manhã);
  * tracker sem comunicação com ângulo fixo conta como parado (`_trk_promove_semcom`, 08/09);
  * overview == detalhe == disponibilidade: os dois dispatchers (curso e perdas) e as duas réguas (v2 e legacy).
"""
import json
import os
from datetime import datetime

import pytest

import app

_FIXDIR = os.path.join(os.path.dirname(__file__), "fixtures", "trackers_cobertura")
_GUARATINGUETA = "pg__guaratingueta-v__2026-09-28.json"
_BOA_ESPERANCA = "pg__boa-esperanca-do-sul-1__2026-09-28.json"


# ── montagem das curvas ───────────────────────────────────────────────────────────────────────────────
def _hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def _serie(ini, fim, f, passo=5):
    """Leituras de `ini` a `fim` (minutos do dia) de `passo` em `passo`; o ângulo é f(minuto)."""
    return [{"x": f"2026-09-28T{_hhmm(m)}:00", "y": round(f(m), 2)} for m in range(ini, fim + 1, passo)]


def _rampa(ini, fim, y0, y1, teto=None):
    """Sobe em linha reta de y0 (em `ini`) a y1 (em `fim`), parando no `teto` se houver (batente)."""
    def f(m):
        y = y0 + (y1 - y0) * (m - ini) / max(1, fim - ini)
        return min(y, teto) if teto is not None else y
    return f


def _chegando_ao_batente():
    """O desenho das 15:44 de 28/09: 14 trackers subindo de 46° e encostando no batente oeste (55,3°) às 15:30, e 6
    parados em 47,6° desde o primeiro ponto — como os Tracker 09–13 da Guaratinguetá V. 9 pontos, 15:10–15:50."""
    g = {f"Tracker {i:02d}": _serie(15 * 60 + 10, 15 * 60 + 50, _rampa(15 * 60 + 10, 15 * 60 + 30, 46.0, 55.3, 55.3))
         for i in range(1, 15)}
    for i in range(15, 21):
        g[f"Tracker {i:02d}"] = _serie(15 * 60 + 10, 15 * 60 + 50, lambda m: 47.6)
    return g


def _status(res):
    """Os dois dispatchers falam a mesma língua para 'parado': curso devolve a string, perdas um dict."""
    return {t: (v if isinstance(v, str) else (v or {}).get("status")) for t, v in (res or {}).items()}


def _parados(res):
    return {t for t, s in _status(res).items() if s == "parado"}


@pytest.fixture(params=["v2", "legacy"])
def regua(request, monkeypatch):
    """As duas réguas: a v2 é a de produção (TRK_REGUA_V2=1 no tokens.txt); a legacy é para onde tudo cai se a v2
    quebrar. O worktree não tem tokens.txt, então sem isto a suíte só exercitaria a legacy."""
    if request.param == "v2":
        if app._regua_v2 is None:
            pytest.skip("trk_regua_v2 indisponível")
        monkeypatch.setattr(app, "TRK_REGUA_V2", True)
    else:
        monkeypatch.setattr(app, "TRK_REGUA_V2", False)
    return request.param


DISPATCHERS = pytest.mark.parametrize("classifica", [app._trk_classifica_curso, app._trk_classifica_curso_perdas],
                                      ids=["curso", "perdas"])


# ── o defeito ─────────────────────────────────────────────────────────────────────────────────────────
@DISPATCHERS
def test_quarenta_minutos_chegando_ao_batente_nao_e_parado(regua, classifica):
    """Quebra que pega: régua que julga 'parado' pela amplitude sem olhar quanto tempo a curva cobre.
    A v2 marcava os 20 (amplitude ≤ 9,3° < 10°); a legacy, os 6 retos (amplitude 0° < 3°)."""
    res = classifica(_chegando_ao_batente())
    assert _parados(res) == set(), f"40 min de curva viraram parado na régua {regua}: {sorted(_parados(res))}"
    # e quem acompanhou a frota até o batente é normal — ninguém vira outra coisa por falta de dado
    assert all(_status(res)[f"Tracker {i:02d}"] == "normal" for i in range(1, 15)), _status(res)


def _curvas_reais(nome, ate):
    """Foto do banco (public.raw_tracker, mesma consulta do _pg_trk_plant_curvas) cortada em `ate` (HH:MM), no
    formato que o _pg_trk_plant_curvas devolve: {tracker: {'atual': [(datetime, v)], 'alvo': [...]}}."""
    fx = json.load(open(os.path.join(_FIXDIR, nome), encoding="utf-8"))

    def _dt(h):
        return datetime(2026, 9, 28, int(h[:2]), int(h[3:5]))
    return {n: {"atual": [(_dt(h), v) for h, v in d["atual"] if h <= ate],
                "alvo": [(_dt(h), v) for h, v in d["alvo"] if h <= ate]}
            for n, d in fx["trackers"].items()}


def _analise_pg(monkeypatch, nome, pid, ate):
    """O motor do Banco (`_pg_trackers_analise`) inteiro, com a consulta ao banco trocada pela foto."""
    trks = _curvas_reais(nome, ate)
    monkeypatch.setattr(app, "_pg_trk_plant_curvas", lambda plant_id, date, date_fim=None: trks)
    return app._pg_trackers_analise(pid, "2026-09-28"), trks


def _pelo_grafico(trks):
    """O /chart: mesma cadeia dos cards, com o alvo do supervisório de cada tracker."""
    g = {n: [{"x": t.strftime("%Y-%m-%dT%H:%M:%S"), "y": v} for t, v in d["atual"]] for n, d in trks.items()}
    trackers = [{"id": n, "x": [p["x"] for p in pts], "y": [p["y"] for p in pts]} for n, pts in g.items()]
    payload = {}
    app._trk_chart_aplica_status(trackers, g, payload, {n: d["alvo"][-1][1] for n, d in trks.items() if d["alvo"]})
    return payload, {t["id"]: t["status"] for t in trackers}


def test_guaratingueta_v_as_15h50_nao_tem_parado(monkeypatch, freeze_now):
    """O caso real, pelo mesmo motor da rota /api/pg/trackers/parados (`_pg_trackers_analise`) e pelo /chart.
    Quebra que pega: sem o piso, os 48 saem parados."""
    monkeypatch.setattr(app, "TRK_REGUA_V2", True)
    freeze_now("2026-09-28 15:50:00")
    a, trks = _analise_pg(monkeypatch, _GUARATINGUETA, "26", "15:50")
    assert a["total"] == 48 and all(len(d["atual"]) == 9 for d in trks.values()), "a foto mudou"
    assert a["parados"] == 0, f"{a['parados']} parados com 40 min de curva"
    assert not [t["id"] for t in a["trackers"] if t["status"] == "parado"]
    payload, por_id = _pelo_grafico(trks)
    assert payload["parados"] == 0 and "parado" not in por_id.values(), "o gráfico diverge dos cards"


def test_guaratingueta_v_as_17h05_o_tracker_33_continua_parado(monkeypatch, freeze_now):
    """O outro lado, no MESMO dado: às 17:05 a frota já voltou de 55,3° para 19° e o Tracker 33 ficou congelado em
    39,95° desde 16:30. A curva ainda é curta (1h55), mas a frota girou 36° no mesmo intervalo — isso prova.
    Quebra que pega: piso que só olha a duração da curva e esquece a frota."""
    monkeypatch.setattr(app, "TRK_REGUA_V2", True)
    freeze_now("2026-09-28 17:05:00")
    a, trks = _analise_pg(monkeypatch, _GUARATINGUETA, "26", "17:05")
    assert {t["id"] for t in a["trackers"] if t["status"] == "parado"} == {"Tracker 33"}
    assert a["parados"] == 1
    payload, por_id = _pelo_grafico(trks)
    assert {n for n, s in por_id.items() if s == "parado"} == {"Tracker 33"} and payload["parados"] == 1


# ── o que tem de continuar valendo ────────────────────────────────────────────────────────────────────
def _parada_inteira(ini, fim):
    """Usina inteira travada (SMP100/CPP100): 10 trackers retos, cada um no seu ângulo, com ruído de leitura."""
    return {f"Tracker {i}": _serie(ini, fim, lambda m, i=i: -12.3 + i * 0.7 + (0.05 if (m // 5) % 2 else -0.05))
            for i in range(1, 11)}


@DISPATCHERS
def test_um_ponto_tardio_nao_declara_a_frota_muda(regua, classifica):
    """Um tracker com uma leitura solta às 23:50 (relógio torto, reenvio) não pode fazer os outros parecerem
    emudecidos — a mesma trava do `_trk_promove_semcom`. Quebra que pega: medir o "emudeceu" contra o MÁXIMO da
    frota, e não a mediana; os 40 min voltariam a dar parado.
    Só os 14 que sobem até o batente (amplitude 9,3°): os retos (0°) seriam promovidos de volta pela regra de 08/09,
    porque o rótulo de sem comunicação (`_trk_semcom_set`) usa o máximo de propósito — isso é da promoção, não do piso."""
    g = {n: pts for n, pts in _chegando_ao_batente().items() if int(n.split()[1]) <= 14}
    g["Tracker 01"] = g["Tracker 01"] + [{"x": "2026-09-28T23:50:00", "y": 55.3}]
    assert _parados(classifica(g)) == set(), _status(classifica(g))


@DISPATCHERS
def test_cinco_horas_parada_continua_parado(regua, classifica):
    """Quebra que pega: piso que esconde a usina inteira travada mesmo com a curva cobrindo o dia (06–11 h)."""
    res = classifica(_parada_inteira(6 * 60, 11 * 60))
    assert _parados(res) == {f"Tracker {i}" for i in range(1, 11)}, _status(res)


@DISPATCHERS
def test_a_cobertura_minima_e_inclusiva(regua, classifica):
    """Curva de exatamente TRK_COBERTURA_MIN_H já julga; 10 min a menos, com a frota imóvel, ainda não.
    Quebra que pega: '>' no lugar de '>=' (ou o contrário) na comparação da cobertura."""
    cob = int(app.TRK_COBERTURA_MIN_H * 60)
    assert _parados(classifica(_parada_inteira(10 * 60, 10 * 60 + cob))) == {f"Tracker {i}" for i in range(1, 11)}
    assert _parados(classifica(_parada_inteira(10 * 60, 10 * 60 + cob - 10))) == set()


@DISPATCHERS
def test_a_frota_girou_e_um_ficou_parado_cedo(regua, classifica):
    """08:30, 2h30 de curva: a frota saiu do batente leste e girou 35°, um tracker não saiu. É parado já — a régua
    pega de manhã justamente por ter a frota como referência. Quebra que pega: piso sem a prova da frota."""
    g = {f"Tracker {i}": _serie(6 * 60, 8 * 60 + 30, _rampa(6 * 60, 8 * 60 + 30, -55.0 + i * 0.3, -20.0 + i * 0.3))
         for i in range(1, 11)}
    g["Tracker 11"] = _serie(6 * 60, 8 * 60 + 30, lambda m: -55.0)
    res = classifica(g)
    assert _parados(res) == {"Tracker 11"}, _status(res)


@DISPATCHERS
def test_sensor_morto_com_curva_curta_segue_parado(regua, classifica):
    """Regra de 08/09: sem comunicação em ângulo fixo conta como parado. O sensor morto (0,00° o tempo todo) numa
    usina que acabou de voltar a reportar ainda é parado. Quebra que pega: aplicar o piso DEPOIS da promoção do
    `_trk_promove_semcom` (ela seria desfeita)."""
    g = _chegando_ao_batente()
    g["Tracker 21"] = _serie(15 * 60 + 10, 15 * 60 + 50, lambda m: 0.0)
    assert _parados(classifica(g)) == {"Tracker 21"}


@DISPATCHERS
def test_mudo_desde_a_madrugada_segue_parado(regua, classifica):
    """Tracker que só tem leitura de madrugada (último ponto às 05:00) com a frota reportando até as 15h: está sem
    comunicação o dia inteiro, e a v2 o conta como parado. Não é caso de cobertura — é de comunicação. Quebra que
    pega: piso que rebaixa o mudo (a promoção não o recupera, porque ele não tem ângulo dentro da janela)."""
    g = {f"Tracker {i}": _serie(6 * 60, 15 * 60, _rampa(6 * 60, 15 * 60, -50.0 + i * 0.2, 40.0 + i * 0.2))
         for i in range(1, 11)}
    g["Tracker 11"] = _serie(4 * 60, 5 * 60, lambda m: -3.0)
    esperado = {"Tracker 11"} if regua == "v2" else set()   # a legacy nunca classificou quem não tem ponto na janela
    assert _parados(classifica(g)) == esperado


@DISPATCHERS
def test_usina_calada_desde_a_madrugada_nao_some(regua, classifica):
    """Santo Inácio XII, 28/09: nenhum ponto entre 01:34 e 12:37. Às 10:00 a curva do dia só tem madrugada, e a
    v2 conta os trackers como parados ('comunicacao_morta'); a tela da usina grita "Sem dado há Xh". Sem leitura na
    janela não é curva curta, é comunicação. Quebra que pega: piso que trata janela vazia como curta — os 41
    virariam normais e a usina calada sumiria da lista de parados, da ronda e do alarme de frota."""
    g = {f"Tracker {i}": _serie(0, 94, lambda m, i=i: 10.8 + i * 0.1, passo=2) for i in range(1, 11)}
    esperado = {f"Tracker {i}" for i in range(1, 11)} if regua == "v2" else set()   # a legacy nunca os classificou
    assert _parados(classifica(g)) == esperado


def test_boa_esperanca_as_08h_frota_imovel_so_o_sem_comunicacao_e_parado(monkeypatch, freeze_now):
    """Boa Esperança do Sul 1, 28/09: a frota inteira imóvel da madrugada até ~10:15 (amplitude 0,0° nos 49 entre
    06:00 e 10:00). Às 08:00 não dá para saber quem está travado — só quem lê 0,00° o tempo todo, que é sensor sem
    comunicação e conta como parado pela regra de 08/09 (16 deles; 14 seguem em 0,0° até 12:30). Quebra que pega:
    (1) sem piso, os 49; (2) o piso que só pula a regra de amplitude e deixa a análise de congelamento decidir contra
    uma frota que também não se mexe — dava 30, e 15 deles giraram normalmente depois; (3) piso aplicado depois da
    promoção do sem comunicação — sairiam 0."""
    monkeypatch.setattr(app, "TRK_REGUA_V2", True)
    freeze_now("2026-09-28 08:00:00")
    a, trks = _analise_pg(monkeypatch, _BOA_ESPERANCA, "21", "08:00")
    zerados = {n for n, d in trks.items()                     # contados na curva, sem passar pela régua
               if all(abs(v) < 0.05 for t, v in d["atual"] if t.hour >= 6)}
    assert len(zerados) == 16, "a foto mudou"
    parados = {t["id"] for t in a["trackers"] if t["status"] == "parado"}
    assert a["total"] == 49 and parados == zerados, f"{len(parados)} parados com a frota imóvel às 08:00"
    assert all(t["sem_comunicacao"] for t in a["trackers"] if t["id"] in zerados)


def test_boa_esperanca_as_12h_os_17_travados_continuam(monkeypatch, freeze_now):
    """O mesmo dia às 12:00: seis horas de curva, a frota já girou (~20° de mediana) e 17 trackers ficaram abaixo de
    10° de amplitude — contados à mão na curva. O piso não pode tocar aqui."""
    monkeypatch.setattr(app, "TRK_REGUA_V2", True)
    freeze_now("2026-09-28 12:00:00")
    a, _ = _analise_pg(monkeypatch, _BOA_ESPERANCA, "21", "12:00")
    assert a["parados"] == 17


def test_quem_emudeceu_fica_como_estava(monkeypatch):
    """Tracker que reportou das 06:00 às 07:00 e emudeceu, com a frota reportando até as 15h: curva curta, mas o caso
    é de comunicação — fica EXATAMENTE como a régua o deixava (parado, sem janela de episódio inventada). Quebra que
    pega: piso sem a exceção do mudo — ele viraria normal e a promoção do sem comunicação o traria de volta com outra
    janela no book de perdas."""
    monkeypatch.setattr(app, "TRK_REGUA_V2", True)
    g = {f"Tracker {i}": _serie(6 * 60, 15 * 60, lambda m, i=i: -55.0 + i * 0.2 if m < 8 * 60
                                else -55.0 + i * 0.2 + (m - 8 * 60) * 0.15) for i in range(1, 11)}
    g["Tracker 11"] = _serie(6 * 60, 7 * 60, lambda m: -55.0)
    com_piso = app._trk_classifica_curso_perdas(g)["Tracker 11"]
    monkeypatch.setattr(app, "_trk_curva_curta", lambda *a, **k: set())
    assert com_piso == app._trk_classifica_curso_perdas(g)["Tracker 11"]
    assert com_piso["status"] == "parado"


def test_refino_da_api_pv_usa_o_mesmo_piso(monkeypatch):
    """A API PV não passa pelo `_trk_status_from_curva`: o refino do overview dela chama o dispatcher direto. Ela
    tem de ver a mesma coisa (overview == detalhe). Quebra que pega: o refino da API PV com régua própria."""
    monkeypatch.setattr(app, "TRK_REGUA_V2", True)
    g = _chegando_ao_batente()
    monkeypatch.setattr(app, "_pv_trk_grafico", lambda idusina, data, fetch=True: g)
    lst = [{"id": n, "alvo": None, "atual": None, "disparidade": None, "amplitude": None, "max_disp": None,
            "status": "normal"} for n in g]
    app._pv_trk_refina_curva(1, lst, "28/09/2026", fetch=False)
    assert [t["id"] for t in lst if t["status"] == "parado"] == []
