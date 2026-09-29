# -*- coding: utf-8 -*-
"""Fase 4: o acervo do gêmeo guarda em UTC, e o resto da plataforma lê a SunOp na hora da usina (28/09/2026).

**O defeito.** `_sunop_analog_history` pedia ao gêmeo a janela `{dia}T00:00:00 a {dia}T23:59:59` — hora da
usina, como a SunOp recebe com `use_plant_timezone` — e o gêmeo a lia como UTC. Na volta, o carimbo vinha com
`+00:00` e quem consome (`str(t)[11:16]`, `ts[11:13]`, `datetime.fromisoformat`) o tratava como hora da usina.
Conferido no mesmo pathname, MTS100.INV_1.MEDIDAS.STR.I_PV1 em 22/09: pelo gêmeo, corrente acima de 0,5 A de
11:30 a 20:00; pela API, de 06:10 a 17:10. O primeiro dos "três enganos" do teste da Fase 4 (comparar sem
alinhar o fuso) tinha ficado registrado — e o código seguia cometendo.

**Onde doía, além do drill.** A mesma função serve trackers, ETM e PR:
  - a pré-análise de ETM da Athon parou às 08:50 de 28/09 e não publicou mais — a estação servida pelo gêmeo
    chegava com fuso, a da API sem, e `datetime.now() - carimbo` levanta TypeError;
  - a curva de tracker de hoje continuava de um ponto "no futuro" (o log mostrou 19:15 às 17:27);
  - o EPD máximo do dia pegava o total da VÉSPERA (21:00–23:59 da usina cabem na janela UTC do dia).

**A regra.** O gêmeo é um acervo em UTC; quem traduz é a plataforma, com o fuso de CADA usina: a janela vai em
UTC e o carimbo volta na hora da usina, no mesmo formato da SunOp. O fuso sai do estado da usina no cadastro
(Info Geral) e, sem estado, é o de Brasília — a hora em que a plataforma já lê a SunOp.
"""
import datetime as dt
import tomllib
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import app

UTC = dt.timezone.utc


class _AcervoFalso:
    """O gêmeo como ele é (gemeo/app/server.py + consultas.curva_por_pathname): guarda em UTC, lê a janela sem
    fuso como UTC, serve [ini, fim) e devolve o carimbo com +00:00. Pathname sem ponto na janela vai para
    `nao_atendidos` — é o que manda a plataforma à SunOp."""

    def __init__(self, pontos):
        self.pontos = pontos                    # {pathname: [(datetime em UTC, valor)]}
        self.janelas = []

    def __call__(self, pathnames, ini, fim):
        a, b = dt.datetime.fromisoformat(ini), dt.datetime.fromisoformat(fim)
        a = a if a.tzinfo else a.replace(tzinfo=UTC)
        b = b if b.tzinfo else b.replace(tzinfo=UTC)
        self.janelas.append((ini, fim))
        series = {}
        for p in pathnames:
            s = [[t.isoformat(), float(v)] for t, v in self.pontos.get(p, []) if a <= t < b]
            if s:
                series[p] = s
        return {"series": series, "nao_atendidos": sorted(p for p in pathnames if p not in series),
                "n_pontos": sum(len(v) for v in series.values())}


class _SunOpFalsa:
    """A API da SunOp com `use_plant_timezone`: carimbo na hora da usina, sem fuso. Registra cada janela pedida."""

    def __init__(self, pontos=None):
        self.pontos = pontos or {}              # {pathname: [("AAAA-MM-DDTHH:MM:SS", valor)]}
        self.pedidos = []

    def __call__(self, pathnames, start, end, inst="gridco", period=None):
        self.pedidos.append((sorted(pathnames), start, end))
        a, b = start.replace(" ", "T"), end.replace(" ", "T")
        return {p: [(t, v) for t, v in self.pontos[p] if a <= t <= b] for p in pathnames if p in self.pontos}


def _u(texto):
    """'2026-09-22 09:10' em UTC → datetime aware."""
    return dt.datetime.strptime(texto, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)


def _passos(ini_utc, fim_utc, minutos):
    t, out = _u(ini_utc), []
    while t <= _u(fim_utc):
        out.append(t)
        t += dt.timedelta(minutes=minutos)
    return out


@pytest.fixture
def fase4(monkeypatch):
    """Liga a Fase 4 com o acervo e a SunOp dublados, metadata e caches da Athon isolados, e o log da Fase 4
    fora do disco (o `_log_arquivo` real escreveria na pasta logs/ da plataforma). O estado das usinas é o do
    cadastro em 28/09, fixo aqui: o `import app` baixa o cadastro da API quando consegue, e o teste não pode
    mudar de resultado conforme a rede."""
    monkeypatch.setattr(app, "GEMEO_CURVA_ATIVO", True)
    monkeypatch.setattr(app, "_log_arquivo", lambda nome, msg: None)
    monkeypatch.setattr(app, "ensure_sunop_meta", lambda inst="gridco": None)
    monkeypatch.setattr(app, "_estado_da_usina", lambda nome: {"MTS100": "Maranhão", "MRO100": "Pará"}.get(nome))
    for nome in ("_sunop_curva_cache", "_sunop_str_med_cache", "_sunop_trk_hist", "_sunop_str_hist"):
        monkeypatch.setattr(app, nome, {})
    monkeypatch.setattr(app, "_sunop_analise_cache", {"payload": None, "ts": 0.0, "_ttl": app.SUNOP_TTL})
    monkeypatch.setattr(app, "_trancadas", set())

    def _liga(meta, acervo, sunop=None):
        monkeypatch.setattr(app, "_sunop_meta", meta)
        monkeypatch.setattr(app, "_gemeo_curva", acervo)
        sunop = sunop or _SunOpFalsa()
        monkeypatch.setattr(app, "_sunop_analog_history_api", sunop)
        return sunop

    return _liga


def test_drill_de_dia_passado_pelo_gemeo_sai_na_hora_da_usina(fase4):
    """O caso de 22/09 no drill "Curva das strings". A string gera das 06:15 às 17:00 da usina (09:15–20:00 UTC).
    Pelo gêmeo, antes, o eixo mostrava 09:15–20:00, começava num ponto da véspera (02:00 UTC = 23:00 de 21/09) e
    perdia o fim do dia da usina (01:00 UTC de 23/09 = 22:00 de 22/09)."""
    pn = "MTS100.INV_1.MEDIDAS.STR.I_PV1"
    corrente = [(t, 5.0 if _u("2026-09-22 09:15") <= t <= _u("2026-09-22 20:00") else 0.0)
                for t in _passos("2026-09-22 08:30", "2026-09-22 21:30", 15)]
    acervo = _AcervoFalso({pn: [(_u("2026-09-22 02:00"), 7.7)] + corrente + [(_u("2026-09-23 01:00"), 0.0)]})
    fase4({"MTS100": {"inv_strings": {"INV_1": [pn]}}}, acervo)

    pay = app._sunop_strings_curva("MTS100", "2026-09-22", "INV_1", "gridco")

    c = pay["inversores"][0]["curva"]["ST 01"]
    acima = [x for x, y in zip(c["x"], c["y"]) if y > 0.5]
    assert (acima[0], acima[-1]) == ("06:15", "17:00"), f"horas da corrente fora da hora da usina: {acima[:2]}…"
    assert c["x"][0] == "05:30", f"o dia da usina começa no 1º ponto dele, não na véspera: {c['x'][:3]}"
    assert c["x"][-1] == "22:00", f"o fim do dia da usina (22:00) é 01:00 UTC do dia seguinte: {c['x'][-3:]}"


def test_pr_do_inversor_nao_pega_o_total_da_vespera(fase4):
    """EPD é o contador do dia: fica no total até a meia-noite da usina e zera. Com a janela lida como UTC, as
    21:00–23:59 da VÉSPERA entravam no dia, e o máximo era o total de ontem (900) em vez do de hoje (600)."""
    epd, poa = "MRO100.INV_1.MEDIDAS.EPD", "MRO100.AIML.POA"
    pontos = []
    for t in _passos("2026-09-21 21:00", "2026-09-23 02:45", 15):   # 21/09 18:00 a 22/09 23:45 na usina
        local = t - dt.timedelta(hours=3)
        if local.date() == dt.date(2026, 9, 21):
            v = 900.0                                                  # total de ontem, parado até a meia-noite
        elif local.hour < 6:
            v = 0.0
        elif local.hour < 18:
            v = round(600.0 * ((local.hour - 6) * 60 + local.minute) / (12 * 60), 1)
        else:
            v = 600.0                                                  # total de hoje
        pontos.append((t, v))
    sunop = _SunOpFalsa({poa: [(f"2026-09-22T{h:02d}:00:00", 500.0) for h in range(6, 19)]})
    fase4({"MRO100": {"inv_other": {"INV_1": {"EPD": epd}}, "plant_paths": {"POA": poa}, "inv_strings": {}}},
          _AcervoFalso({epd: pontos}), sunop)

    _ipoa, _n, invs = app._sunop_pr_one("MRO100", "2026-09-22", "gridco")

    assert invs[0]["geracao_kwh"] == 600.0, f"EPD do dia pegou outro dia: {invs[0]['geracao_kwh']}"


def test_pre_analise_de_etm_com_estacao_servida_pelo_gemeo_sai_na_hora_da_usina(fase4, freeze_now):
    """28/09: a pré-análise de ETM da Athon parou às 08:50 e não publicou mais. POA e GHI vinham do gêmeo (com
    fuso), o POA-RI da SunOp (sem), e o diagnóstico não consegue nem ordenar nem subtrair um do outro."""
    freeze_now("2026-09-22 15:00:00")
    poa, ghi, ri = "MTS100.ESTM.POA.IRAD", "MTS100.ESTM.GHI.IRAD", "MTS100.ESTM.POA_R.IRAD"
    horas = _passos("2026-09-22 09:00", "2026-09-22 18:00", 60)       # 06:00 a 15:00 na usina
    acervo = _AcervoFalso({poa: [(t, 600.0) for t in horas], ghi: [(t, 500.0) for t in horas]})
    sunop = _SunOpFalsa({ri: [(f"2026-09-22T{h:02d}:00:00", 550.0) for h in range(6, 16)]})
    fase4({"MTS100": {"etm_stations": {"ESTM": {"poa": poa, "ghi": ghi, "poari": ri}}}}, acervo, sunop)

    pay = app._build_sunop_analise_payload("gridco")

    r = next(x for x in pay["rows"] if x["plant_id"] == "MTS100")
    assert r["sem_dados"] is False
    assert r["ultima_leitura"] == "2026-09-22 15:00", f"última leitura fora da hora da usina: {r['ultima_leitura']}"
    assert r["spark"]["labels"] == [f"{h:02d}:00" for h in range(6, 16)], \
        f"POA/GHI do gêmeo e POA-RI da SunOp têm de cair no MESMO instante: {r['spark']['labels']}"


def test_curva_de_tracker_de_hoje_continua_de_onde_parou_e_nao_do_futuro(fase4, freeze_now):
    """A busca incremental volta 30 min antes do último ponto. Com o último ponto em UTC (17:45+00:00 = 14:45 na
    usina), a janela seguinte começava às 17:15 — no futuro da usina, às 15:00 — e o que a SunOp atende (o
    tracker que o gêmeo não tem) parava de crescer. No log de 28/09: janela de 19:15 pedida às 17:27."""
    freeze_now("2026-09-22 15:00:00")
    t1, t2 = "MRO100.TRK_1.MEDIDAS.POSAT", "MRO100.TRK_2.MEDIDAS.POSAT"
    acervo = _AcervoFalso({t1: [(t, 10.0) for t in _passos("2026-09-22 09:00", "2026-09-22 17:45", 15)]})
    sunop = _SunOpFalsa({t2: [(f"2026-09-22T{h:02d}:{m:02d}:00", 12.0) for h in range(6, 15) for m in (0, 15, 30, 45)]})
    fase4({"MRO100": {"trackers": {"TRK_1": {"atual": t1}, "TRK_2": {"atual": t2}}}}, acervo, sunop)

    app._sunop_trk_curvas("MRO100", "2026-09-22", "gridco")
    app._sunop_trk_hist[("MRO100", "2026-09-22")]["ts"] = 0.0          # TTL vencido, mesma hora: incremental
    app._sunop_trk_curvas("MRO100", "2026-09-22", "gridco")

    assert [ini for _pns, ini, _fim in sunop.pedidos] == ["2026-09-22T00:00:00", "2026-09-22T14:15:00"]


def test_cada_usina_na_janela_e_no_fuso_dela(fase4, monkeypatch):
    """Fuso é da usina, não do lote. Cuiabá (UTC−4) e São Luís (UTC−3) no mesmo pedido: 03:30 UTC é 00:30 de
    22/09 no Maranhão e 23:30 de 21/09 em Mato Grosso; e o MESMO instante, 09:10 UTC, é 05:10 numa e 06:10 na
    outra. Usina sem estado no cadastro fica na hora de Brasília, que é a hora em que a plataforma lê a SunOp."""
    estados = {"CBA100": "Mato Grosso", "MTS100": "Maranhão"}
    monkeypatch.setattr(app, "_estado_da_usina", lambda nome: estados.get(nome))
    mt, ma, sem = ("CBA100.INV_1.MEDIDAS.STR.I_PV1", "MTS100.INV_1.MEDIDAS.STR.I_PV1",
                   "XYZ100.INV_1.MEDIDAS.STR.I_PV1")
    acervo = _AcervoFalso({mt: [(_u("2026-09-22 03:30"), 0.0), (_u("2026-09-22 09:10"), 0.5),
                                (_u("2026-09-22 10:10"), 1.0)],
                           ma: [(_u("2026-09-22 03:30"), 0.0), (_u("2026-09-22 09:10"), 1.0)],
                           sem: [(_u("2026-09-22 09:10"), 1.0)]})
    fase4({}, acervo)

    r = app._sunop_analog_history([mt, ma, sem], "2026-09-22T00:00:00", "2026-09-22T23:59:59", "gridco")

    assert r == {mt: [("2026-09-22T05:10:00", 0.5), ("2026-09-22T06:10:00", 1.0)],
                 ma: [("2026-09-22T00:30:00", 0.0), ("2026-09-22T06:10:00", 1.0)],
                 sem: [("2026-09-22T06:10:00", 1.0)]}


def test_fuso_de_cada_usina_da_sunop_no_acervo_e_o_mesmo_do_gemeo():
    """A volta só é exata com o MESMO fuso da ida: o gêmeo converteu a hora da usina em UTC pelo `tz` do config
    dele; a plataforma desfaz pelo estado do cadastro (ou Brasília). Usina da SunOp que entrar no acervo num fuso
    que a plataforma não resolve igual deslocaria a curva inteira em horas cheias, sem erro nenhum."""
    cfg = tomllib.loads((Path(__file__).resolve().parents[1] / "gemeo" / "config.toml").read_text(encoding="utf-8"))
    instante = dt.datetime(2026, 9, 22, 12, 0)
    sunop = {cod: d for cod, d in cfg["usinas"]["detalhe"].items() if d.get("fonte", "sunop") in ("sunop", "axis")}
    assert sunop, "o config do gêmeo não tem mais usina da SunOp — revisar este teste"
    divergentes = {}
    for cod, d in sunop.items():
        do_gemeo = ZoneInfo(d.get("tz", "America/Belem")).utcoffset(instante)
        da_plataforma = app._sunop_fuso_usina(cod).utcoffset(instante)
        if do_gemeo != da_plataforma:
            divergentes[cod] = (str(do_gemeo), str(da_plataforma))
    assert not divergentes, f"fuso do gêmeo × plataforma: {divergentes}"
