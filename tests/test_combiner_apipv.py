# -*- coding: utf-8 -*-
"""Combiner (String Box) pela API PV, não mais pela PV Plataforma (Levi, 16/09/2026).

O administrador da Solan avisou que a combiner também está na API, e está: `POST /api/v2/custom_query`
com `data_type: "combiner"` devolve `idcombiner`, `conteudojson` (Ipv1..IpvN, Upv, Pac, sn) e
`tsleitura`. Três ganhos medidos sobre a fonte antiga (`apiplataforma /v2/inversores/view`):

1. **UMA chamada por USINA** em vez de uma por inversor (a antiga custava 25 s cada, num laço).
2. **Token que renova sozinho** (usuário+senha, 1 h) em vez do PLAT_TOKEN manual de 7 dias com
   CAPTCHA/MFA.
3. **Dado correto.** Conferido na Tanabi 2 em 16/09: para 3 dos 4 combiners as duas fontes deram o
   MESMO valor no MESMO segundo (maior diferença 0,00 A). No quarto — o INVERSOR02 Novo, id 365433 —
   a PV Plataforma devolvia as 13 strings em ZERO com `tsleitura` de **28/05/2026 09:48** (quase 4
   meses congelada) enquanto o inversor gerava 92,32 kW e a API PV dava a corrente real (5,69 / 5,39
   / 5,41 …). Ou seja: a usina acusava 13 strings mortas desde maio, e o código não percebia porque
   nunca olhava a idade da leitura. Daí a guarda de idade aqui.

O de-para combiner → inversor é DETERMINÍSTICO pelo número de série: o `sn` do combiner é "CMB" +
o `device_esn` do inversor no `plant_devices` (o esn pode ter sufixo "@..." que não conta). Não é
casamento por valor nem por ordem de id."""
import app


# plant_devices como a API devolve (recorte real da Tanabi 2, 16/09/2026)
DEVS = [
    {"device_id": 369744, "device_name": "INVERSOR07", "device_type": "INVERTER",
     "device_esn": "A2192604585@1779972254"},                       # esn com sufixo @
    {"device_id": 50215, "device_name": "INVERSOR04 ", "device_type": "INVERTER",
     "device_esn": "A2192604657"},
    {"device_id": 365433, "device_name": "INVERSOR02 No", "device_type": "INVERTER",
     "device_esn": "A2151700567"},
    {"device_id": 99999, "device_name": "ETM", "device_type": "METEO", "device_esn": "MET123"},
]


def _linha(idc, sn, ts, ipvs):
    cj = {f"Ipv{i + 1}": v for i, v in enumerate(ipvs)}
    cj.update({"sn": sn, "tsleitura": ts, "Pac": 0.0})
    return {"idcombiner": idc, "conteudojson": cj, "tsleitura": ts}


def test_de_para_pelo_numero_de_serie():
    """sn do combiner = 'CMB' + device_esn do inversor; o sufixo '@...' do esn não entra."""
    rows = [_linha(935, "CMBA2192604585", "2026-09-16 14:22:16", [9.48, 9.12]),
            _linha(246, "CMBA2192604657", "2026-09-16 14:22:20", [8.80, 8.64])]
    out = app._pv_comb_parse(rows, DEVS, agora="2026-09-16 14:25:00")
    assert set(out) == {369744, 50215}
    assert out[369744]["idcombiner"] == 935
    assert out[369744]["strings"] == [("Ipv1", 9.48), ("Ipv2", 9.12)]
    assert out[50215]["idcombiner"] == 246


def test_pega_a_leitura_mais_recente_de_cada_combiner():
    """A v2 devolve o dia inteiro (720 linhas na Tanabi 2); vale a última de cada combiner."""
    rows = [_linha(246, "CMBA2192604657", "2026-09-16 08:00:00", [1.0, 1.0]),
            _linha(246, "CMBA2192604657", "2026-09-16 14:22:20", [8.80, 8.64]),
            _linha(246, "CMBA2192604657", "2026-09-16 11:00:00", [5.0, 5.0])]
    out = app._pv_comb_parse(rows, DEVS, agora="2026-09-16 14:25:00")
    assert out[50215]["ts"] == "2026-09-16 14:22:20"
    assert out[50215]["strings"] == [("Ipv1", 8.80), ("Ipv2", 8.64)]


def test_descarta_leitura_congelada():
    """O caso real que motivou a guarda: INVERSOR02 Novo com 13 zeros carimbados em 28/05, quatro
    meses antes, enquanto o inversor gerava. Leitura velha NÃO entra — o inversor cai em 'sem visão',
    que é honesto, em vez de virar 13 strings mortas."""
    rows = [_linha(933, "CMBA2151700567", "2026-05-28 09:48:00", [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
            _linha(246, "CMBA2192604657", "2026-09-16 14:22:20", [8.80, 8.64])]
    out = app._pv_comb_parse(rows, DEVS, agora="2026-09-16 14:25:00")
    assert 365433 not in out, "leitura de 28/05 não pode passar por leitura de agora"
    assert 50215 in out, "a leitura boa do vizinho continua valendo"


def test_combiner_sem_inversor_correspondente_e_ignorado():
    rows = [_linha(777, "CMBZZZDESCONHECIDO", "2026-09-16 14:22:20", [7.0])]
    assert app._pv_comb_parse(rows, DEVS, agora="2026-09-16 14:25:00") == {}


def test_ordem_das_strings_e_numerica_nao_alfabetica():
    """Ipv10 vem depois de Ipv9 — ordenar como texto colocaria Ipv10 entre Ipv1 e Ipv2."""
    rows = [_linha(246, "CMBA2192604657", "2026-09-16 14:22:20", [1.1, 2.2, 3.3, 4.4, 5.5,
                                                                 6.6, 7.7, 8.8, 9.9, 10.1, 11.1, 12.1])]
    out = app._pv_comb_parse(rows, DEVS, agora="2026-09-16 14:25:00")
    assert [k for k, _ in out[50215]["strings"]] == [f"Ipv{i}" for i in range(1, 13)]


def test_formato_igual_ao_da_fonte_antiga():
    """O resultado entra no MESMO lugar que `_plat_combiner_strings` alimentava (cj.update(dict(...))),
    então tem de ter a mesma forma: lista de pares (nome, corrente) + ts."""
    rows = [_linha(246, "CMBA2192604657", "2026-09-16 14:22:20", [8.80, 8.64])]
    d = app._pv_comb_parse(rows, DEVS, agora="2026-09-16 14:25:00")[50215]
    assert set(d) >= {"strings", "ts"}
    assert dict(d["strings"]) == {"Ipv1": 8.80, "Ipv2": 8.64}


def test_inversor_cadastrado_duas_vezes_recebe_a_combiner_nos_dois_ids():
    """Tanabi 2, 25/09/2026 (Levi: "tem vários inversores que a plataforma escondeu a string"). O INVERSOR02 está
    cadastrado DUAS vezes na API com o mesmo número de série — 369742 "INVERSOR02 Novo" (é ele que reporta no
    day_inverter) e 365433 "INVERSOR02 No" (esn com sufixo @). O de-para guardava só o ÚLTIMO da lista: a combiner caía
    no 365433, que não aparece, e o 2.2 da tela ficava "sem visão" com a combiner dele chegando a cada 2 min."""
    devs = [{"device_id": 369742, "device_name": "INVERSOR02 Novo", "device_type": "INVERTER", "device_esn": "A2151700567"},
            {"device_id": 365433, "device_name": "INVERSOR02 No", "device_type": "INVERTER",
             "device_esn": "A2151700567@1779972254"}]
    rows = [_linha(933, "CMBA2151700567", "2026-09-25 09:04:24", [1.5, 1.8, 1.64])]
    out = app._pv_comb_parse(rows, devs, agora="2026-09-25 09:06:00")
    assert set(out) == {369742, 365433}, "a combiner tem de chegar no id que a tela mostra, qualquer que seja"
    assert out[369742]["strings"] == [("Ipv1", 1.5), ("Ipv2", 1.8), ("Ipv3", 1.64)]


# ── a cota diária da API PV (25/09/2026) ─────────────────────────────────────
# "Você atingiu o limite diário de consultas históricas. Tente novamente amanhã" — a Tanabi 1 às 09:05. A combiner sai do
# custom_query, que devolve o DIA INTEIRO e conta nessa cota; a plataforma pedia de novo a cada 5 min, noite inclusive.

def _conta_idas(monkeypatch):
    idas = []

    class _R:
        status_code = 200

        def json(self):
            return []

    class _H:
        def post(self, url, **k):
            idas.append(url)
            return _R()
    monkeypatch.setattr(app, "_http", lambda: _H())
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "")
    monkeypatch.setattr(app, "_pv_plant_devices", lambda pid: [])
    monkeypatch.setattr(app, "_pv_comb_falhou", {})
    return idas

# (os testes de validade da combiner foram para tests/test_combiner_cota_e_sem_visao.py: 1 h de dia, sem renovar à noite)
