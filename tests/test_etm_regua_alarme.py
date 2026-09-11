# -*- coding: utf-8 -*-
"""Régua de ALARME da ETM (Levi, 10/09/2026): "deve-se alarmar apenas GHI e IPOA zerados; POA-RI é só aviso".

Antes, na Athon, 8 cards ficavam vermelhos por herdar da usina o diagnóstico do mês, os chips "GHI POARI COM"
misturavam sensor medido em zero com sensor que não existe na estação, e TIM200 com POA zerado hoje não ganhava
destaque nenhum. Agora cada flag diz o SENSOR e o TIPO:
  crit  = IPOA (POA) ou GHI medidos em zero com sol → alarme (vermelho)      · sem comunicação (sensor COM, violeta)
  warn  = atenção (estação atrasando, GHI > POA, quedas, buraco na série)
  info  = aviso (tudo do POA-RI)
  nota  = sensor que não reportou nada hoje (não existe na estação, como o GHI das AIML) — cinza, nunca alarma
e o diagnóstico devolve `sensores` (pico e status de POA/GHI/POA-RI) para a tela desenhar os três blocos.
O diagnóstico do MÊS (BD_Performance) separa `alarmes` (IPOA/GHI zerada) de `avisos` (constante, sem leitura de
GHI, PR anômalo) — só os alarmes contam no número do card da Entrada."""
from datetime import datetime

import app


def _serie(poa=None, ghi=None):
    """Pontos a cada 30 min de 06:00 a 17:30 de 10/09/2026; poa/ghi são funções t → W/m² (None = sensor mudo)."""
    out = []
    for h in range(6, 18):
        for m in (0, 30):
            t = datetime(2026, 9, 10, h, m)
            out.append((t, poa(t) if poa else None, ghi(t) if ghi else None))
    return out


def _sol(t):
    """Curva de sol simplificada: pico 1000 W/m² ao meio-dia, zero às 6 e às 18."""
    return max(0.0, 1000.0 * (1 - abs(t.hour + t.minute / 60 - 12) / 6))


def test_ghi_medido_em_zero_com_sol_e_alarme(freeze_now):
    """Caso MTS100 (10/09): POA 1.143 W/m², GHI 0 o dia todo. Era 'warn' (âmbar); agora é crítico e diz o sensor."""
    freeze_now("2026-09-10 16:00:00")
    d = app._diagnostico_etm(_serie(poa=_sol, ghi=lambda t: 0.0))
    f = {x["t"]: x for x in d["flags"]}
    assert f["GHI zerado"]["tipo"] == "crit" and f["GHI zerado"]["sensor"] == "GHI"
    assert d["severidade"] == 0
    assert d["sensores"]["ghi"]["status"] == "zerado" and d["sensores"]["ghi"]["pico"] == 0.0
    assert d["sensores"]["poa"]["status"] == "ok" and d["sensores"]["poa"]["pico"] >= 900


def test_sensor_que_nao_reporta_e_nota_nao_alarme(freeze_now):
    """Caso das AIML: não têm GHI nem POA-RI. 'Sem leitura' vira nota (cinza), não mexe na severidade."""
    freeze_now("2026-09-10 16:00:00")
    d = app._diagnostico_etm(_serie(poa=_sol), poari=[(t, None) for t, _, _ in _serie()])
    tipos = {x["t"]: (x["tipo"], x["sensor"]) for x in d["flags"]}
    assert tipos["Sem leitura de GHI"] == ("nota", "GHI")
    assert tipos["Sem leitura de POA-RI"] == ("info", "POARI")
    assert d["severidade"] == 3
    assert d["sensores"]["ghi"]["status"] == "sem_leitura" and d["sensores"]["poari"]["status"] == "sem_leitura"


def test_poa_ri_zerado_e_so_aviso(freeze_now):
    freeze_now("2026-09-10 16:00:00")
    d = app._diagnostico_etm(_serie(poa=_sol, ghi=_sol), poari=[(t, 0.0) for t, _, _ in _serie()])
    f = {x["t"]: x for x in d["flags"]}
    assert f["POA-RI zerado"]["tipo"] == "info" and f["POA-RI zerado"]["sensor"] == "POARI"
    assert d["severidade"] == 3
    assert d["sensores"]["poari"]["status"] == "zerado"


def test_poa_zerado_continua_critico_e_diz_o_sensor(freeze_now):
    """Caso TIM200 (10/09): POA 0 o dia todo — alarme de verdade que não ficava vermelho."""
    freeze_now("2026-09-10 16:00:00")
    d = app._diagnostico_etm(_serie(poa=lambda t: 0.0, ghi=_sol))
    f = {x["t"]: x for x in d["flags"]}
    assert f["POA zerado"]["tipo"] == "crit" and f["POA zerado"]["sensor"] == "POA"
    assert d["sensores"]["poa"]["status"] == "zerado"


def test_sem_comunicacao_e_sensor_com(freeze_now):
    freeze_now("2026-09-10 16:00:00")
    s = [x for x in _serie(poa=_sol, ghi=_sol) if x[0].hour < 14]        # última leitura 13:30 → 150 min
    d = app._diagnostico_etm(s)
    f = {x["t"]: x for x in d["flags"]}
    assert f["Sem comunicação"]["tipo"] == "crit" and f["Sem comunicação"]["sensor"] == "COM"


def test_estacao_ok_nao_tem_flag_de_sensor(freeze_now):
    freeze_now("2026-09-10 16:00:00")
    d = app._diagnostico_etm(_serie(poa=_sol, ghi=lambda t: _sol(t) * 0.9), poari=[(t, _sol(t) * 0.5) for t, _, _ in _serie()])
    assert d["flags"] == [] and d["severidade"] == 3
    assert {k: v["status"] for k, v in d["sensores"].items()} == {"poa": "ok", "ghi": "ok", "poari": "ok"}


# ── diagnóstico do MÊS (BD_Performance) ─────────────────────────────────────────────────────────────
def test_mes_ipoa_zerada_e_alarme_e_ghi_sem_leitura_e_aviso():
    assert app._etm_prob_classifica([0.0] * 9, "IPOA", trava_pr=True) == \
        [("IPOA zerada no mês inteiro (9d) — PR não calculável", "alarme")]
    assert app._etm_prob_classifica([None] * 9, "GHI") == \
        [("GHI sem leitura no mês inteiro (9d) — sensor não reporta?", "aviso")]
    assert app._etm_prob_classifica([None] * 9, "IPOA", trava_pr=True) == \
        [("IPOA sem leitura no mês inteiro (9d) — PR não calculável", "alarme")]


def test_mes_constante_e_aviso_e_zeros_em_dias_e_alarme():
    r = dict(app._etm_prob_classifica([5.1, 5.1, 5.1, 5.1, 6.0, 0.0, 0.0, 0.0, 6.2], "GHI"))
    assert r["GHI constante em 5.1 por 4 dias seguidos (sensor travado?)"] == "aviso"
    assert r["GHI zerada/nula em 3 de 9 dias"] == "alarme"
    assert app._etm_prob_classifica([5.1, 6.0, 5.8, 6.2], "GHI") == []


def test_item_do_mes_separa_alarmes_de_avisos():
    probs = {}
    app._etm_prob_add(probs, "MTS100", "Athon", "GHI zerada no mês inteiro (9d)", "alarme")
    app._etm_prob_add(probs, "MTS100", "Athon", "IPOA constante em 5.1 por 3 dias seguidos (sensor travado?)", "aviso")
    app._etm_prob_add(probs, "MTS100", "Athon", "GHI zerada no mês inteiro (9d)", "alarme")      # repetido: não duplica
    app._etm_prob_add(probs, "JCD100", "Athon", "PR anômalo (145%)", "aviso")
    itens = app._etm_prob_itens(probs)
    mts, jcd = (next(i for i in itens if i["usina"] == u) for u in ("MTS100", "JCD100"))
    assert mts["alarme"] is True and mts["alarmes"] == ["GHI zerada no mês inteiro (9d)"]
    assert mts["avisos"] == ["IPOA constante em 5.1 por 3 dias seguidos (sensor travado?)"]
    assert mts["problemas"] == mts["alarmes"] + mts["avisos"]                          # compat: quem lia a lista continua lendo
    assert jcd["alarme"] is False and jcd["alarmes"] == [] and jcd["problemas"] == ["PR anômalo (145%)"]
    assert app._etm_item_alarme(mts) is True and app._etm_item_alarme(jcd) is False
    assert app._etm_item_alarme({"problemas": ["x"]}) is True                          # item antigo (snapshot) sem o campo = alarme
