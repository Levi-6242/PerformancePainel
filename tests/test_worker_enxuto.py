# -*- coding: utf-8 -*-
"""O worker mais enxuto sem perder função (auditoria do worker, 02/11/2026, achados 16, 19 e 20).

- 16: a ronda do WhatsApp, o vigia dele e o túnel só funcionam no PC Windows (PowerShell, C:\\GridcoWhats, cloudflared),
  mas subiam em qualquer máquina: no servidor, três threads à toa, e um `whats_ronda.json` ligado lá faria o vigia
  "reiniciar" o nada a cada 6 min.
- 19: o `_qualidade_loop` baixava de hora em hora, também de madrugada, o dia inteiro dos inversores das 7 usinas da 2C
  (fonte paga): das 18:20 às 05:40 o resultado não muda.
- 20: o mesmo minuto criado de novo em cada ponto: a combiner recortava o horário para cada string de cada leitura
  (~65 MB dos 199 MB do `_pv_comb_cache` em 01/11) e a 2C fazia um `strptime` por ponto (~860 mil por montagem).
"""
import pytest

import app


# ── 20 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_combiner_guarda_um_texto_por_minuto():
    devs = [{"device_type": "INVERTER", "device_esn": "ABC", "device_id": 7}]
    rows = [{"conteudojson": {"tsleitura": "2026-11-02 10:00:00", "sn": "CMBABC", "Ipv1": 1.0, "Ipv2": 2.0, "Ipv3": 3.0}}]
    curv = app._pv_comb_curvas(rows, devs, "2026-11-02")[7]
    horas = [curv[k][0][0] for k in ("Ipv1", "Ipv2", "Ipv3")]
    assert horas == ["10:00"] * 3
    assert horas[0] is horas[1] is horas[2], "um texto por string: o mesmo minuto repetido em cada ponto"


def test_a_2c_guarda_um_datetime_por_minuto(monkeypatch):
    x = "2026-11-02 10:00"
    monkeypatch.setattr(app, "_2C_TRK_FAIXAS", [("ARA", None, None, None, 999)])
    monkeypatch.setattr(app, "_cob_entra", lambda fonte, pid: True)
    monkeypatch.setattr(app, "_2c_trk_api_memo", {})
    monkeypatch.setattr(app, "_2c_trk_memo_poda", lambda *a, **k: None)
    monkeypatch.setattr(app, "_2c_trk_da_api", lambda pid, trk: ("ARA", int(trk[3:])))
    monkeypatch.setattr(app, "_pv_trk_dia", lambda pid, data, fetch=True, **_: {
        "curva": {"TRK1": [{"x": x, "y": 1.0}], "TRK2": [{"x": x, "y": 2.0}]}, "alvo": {}})
    out = app._2c_trk_build_api("2026-11-02")
    t1, t2 = out["ARA"][1]["atual"][0][0], out["ARA"][2]["atual"][0][0]
    assert t1 == t2 and t1.hour == 10
    assert t1 is t2, "um datetime por ponto: o mesmo minuto montado de novo em cada tracker"


# ── 19 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
class _Para(BaseException):
    """Tira o laço infinito do teste (não é Exception: o laço engole Exception)."""


class _Tempo:
    """O módulo time de verdade, com um sleep que conta as voltas e para o laço na terceira."""

    def __init__(self):
        import time as _t
        self._t, self.voltas = _t, 0

    def __getattr__(self, nome):
        return getattr(self._t, nome)

    def sleep(self, s):
        self.voltas += 1
        if self.voltas > 3:
            raise _Para()


@pytest.mark.parametrize("de_dia, ciclos", [(True, 3), (False, 0)])
def test_a_qualidade_so_roda_de_dia(monkeypatch, de_dia, ciclos):
    feitos = []
    monkeypatch.setattr(app, "time", _Tempo())
    monkeypatch.setattr(app, "_notif_de_dia", lambda agora=None: de_dia)
    monkeypatch.setattr(app, "_qualidade_ciclo", lambda: feitos.append(1))
    with pytest.raises(_Para):
        app._qualidade_loop()
    assert len(feitos) == ciclos


# ── 16 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("sistema, no_pc", [("nt", True), ("posix", False)])
def test_ronda_vigia_e_tunel_so_sobem_no_pc(monkeypatch, sistema, no_pc):
    subiram = []

    class _Thread:
        def __init__(self, target=None, daemon=None, **k):
            self.target = target

        def start(self):
            subiram.append(self.target)

    monkeypatch.setattr(app.threading, "Thread", _Thread)
    monkeypatch.setattr(app.os, "name", sistema)
    app._iniciar_loops_de_fundo()
    so_no_pc = {app._ronda_whats_loop, app._whats_watchdog_loop, app._tunnel_url_loop}
    if no_pc:
        assert so_no_pc <= set(subiram)
    else:
        assert so_no_pc.isdisjoint(subiram), "laço que só funciona no Windows subiu no servidor"
    assert app._pv_trk_loop in subiram and app._janitor_loop in subiram          # o resto sobe nos dois
