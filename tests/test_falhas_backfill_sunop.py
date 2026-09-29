# -*- coding: utf-8 -*-
"""Backfill da curva de strings da SunOp para o registro da aba de falhas (28/09/2026, Levi: "faça o backfill da
curva da SunOp"). Antes de 25/09 o Athon só tinha as quedas gravadas, que acham a string morta "viva" com pouca luz —
MTS100 4.2 ST13 passou o 23/09 inteiro sem corrente e a queda só foi marcada às 12:30. A curva do dia passado existe na
SunOp; o acervo do gêmeo devolve em UTC, e por isso o backfill vai direto na API, na hora da usina."""
import json
import math
from datetime import date, datetime

import pytest

import app

P1, P2 = "AAA100", "BBB100"
STRS = {p: {"INV_1": [f"{p}.INV_1.MEDIDAS.STR.I_PV{i}" for i in (1, 2, 3)]} for p in (P1, P2)}


class _Resp:
    def __init__(self, recs, status=200):
        self.status_code, self._recs = status, recs

    def json(self):
        return self._recs


def _serie(dia, morta):
    """5 em 5 min, 05:30–18:30 na hora da usina: sino de 9 A de pico; a morta lê 0."""
    out = []
    for m in range(5 * 60 + 30, 18 * 60 + 31, 5):
        v = 0.0 if morta else round(max(0.0, 9 * math.sin(math.pi * (m - 360) / 720)), 2)
        out.append((f"{dia}T{m // 60:02d}:{m % 60:02d}:00", v))
    return out


@pytest.fixture
def sunop(monkeypatch, tmp_path):
    """Duas usinas da Athon, uma string morta (I_PV3 da BBB100), a API da SunOp falsa e o registro num arquivo à parte."""
    chamadas = []

    def req(metodo, url, inst, headers=None, params=None, json=None, timeout=None):
        dia = params["start_time"][:10]
        chamadas.append((dia, tuple(json["pathnames"])))
        if falhar and len(chamadas) in falhar:
            return None                                   # disjuntor da borda aberto / erro de rede
        return _Resp([{"pathname": p, "timestamp": t, "value": v}
                      for p in json["pathnames"] for t, v in _serie(dia, p.endswith("I_PV3") and p.startswith(P2))])

    falhar = set()
    # o _si monta um dict novo a cada chamada: quem se troca são os objetos do módulo
    monkeypatch.setattr(app, "_sunop_meta", {p: {"inv_strings": STRS[p], "trackers": {}} for p in (P1, P2)})
    monkeypatch.setattr(app, "_sunop_str_med_cache", {})
    monkeypatch.setattr(app, "ensure_sunop_meta", lambda inst="gridco": None)
    monkeypatch.setattr(app, "_sunop_data_headers", lambda inst="gridco": {})
    monkeypatch.setattr(app, "_sunop_req", req)
    monkeypatch.setattr(app, "GEMEO_CURVA_ATIVO", True)      # ligado como no servidor: quem for pelo acervo cai aqui
    monkeypatch.setattr(app, "_gemeo_curva", lambda *a, **k: pytest.fail("o backfill não pode ler o acervo do gêmeo (UTC)"))
    monkeypatch.setattr(app, "_trancadas", set())
    monkeypatch.setattr(app, "_FALHAS_STR_PATH", str(tmp_path / "falhas_strings.json"))
    monkeypatch.setattr(app, "FALHAS_BF_ESTADO", str(tmp_path / "falhas_backfill_sunop.json"))
    monkeypatch.setattr(app, "_FALHAS_MORTAS", {})
    monkeypatch.setattr(app, "FALHAS_BF_PAUSA_LOTE_S", 0)
    monkeypatch.setattr(app, "FALHAS_BF_PAUSA_DIA_S", 0)
    return {"chamadas": chamadas, "falhar": falhar, "reg": tmp_path / "falhas_strings.json"}


def _reg(s):
    return json.loads(s["reg"].read_text(encoding="utf-8"))


def _grava(s, dados):
    s["reg"].write_text(json.dumps(dados), encoding="utf-8")


def _ts(dia, hh):
    return datetime.strptime(f"{dia} {hh}", "%Y-%m-%d %H:%M").timestamp()


def test_backfill_grava_os_dias_que_faltam_na_hora_da_usina(sunop):
    n = app._falhas_backfill_sunop("gridco", hoje=date(2026, 9, 4))
    reg = _reg(sunop)
    assert n == 6 and sorted(reg) == ["2026-09-01", "2026-09-02", "2026-09-03"]
    ent = reg["2026-09-03"]["sunop"][P2]
    assert ent["origem"] == "backfill" and ent["vivas"] == {"Inversor 1": 2}
    (m,) = ent["mortas"]
    # na hora da usina a string morta sai quando o inversor começa a gerar (~06:20); em UTC sairia depois das 09:00
    assert m["string"] == "ST 03" and m["saiu"] < "07:00" and m["voltou"] is None
    assert not reg["2026-09-03"]["sunop"][P1]["mortas"]


def test_backfill_nao_pisa_no_registro_completo_do_dia(sunop):
    _grava(sunop, {"2026-09-03": {"sunop": {P1: {"usina": P1, "ts": _ts("2026-09-03", "23:50"), "mortas": [],
                                                 "vivas": {"Inversor 1": 3}, "regua": app.FALHAS_REGUA_VER}}}})
    app._falhas_backfill_sunop("gridco", hoje=date(2026, 9, 4))
    reg = _reg(sunop)
    assert reg["2026-09-03"]["sunop"][P1]["ts"] == _ts("2026-09-03", "23:50")
    assert reg["2026-09-03"]["sunop"][P2]["origem"] == "backfill"
    # o dia 03 só pediu a BBB100 à SunOp
    assert all(p.startswith(P2) for d, ps in sunop["chamadas"] if d == "2026-09-03" for p in ps)


def test_backfill_refaz_o_registro_parcial_e_o_sem_vivas(sunop):
    # P1: a plataforma caiu às 12h do dia 03 e a última avaliação ficou pela metade; P2: registro de antes das vivas
    _grava(sunop, {"2026-09-03": {"sunop": {P1: {"usina": P1, "ts": _ts("2026-09-03", "12:00"), "mortas": [],
                                                 "vivas": {"Inversor 1": 3}},
                                            P2: {"usina": P2, "ts": _ts("2026-09-03", "23:50"), "mortas": []}}}})
    app._falhas_backfill_sunop("gridco", hoje=date(2026, 9, 4))
    reg = _reg(sunop)
    assert reg["2026-09-03"]["sunop"][P1]["origem"] == "backfill"
    assert reg["2026-09-03"]["sunop"][P2]["origem"] == "backfill" and reg["2026-09-03"]["sunop"][P2]["mortas"]


def test_dia_com_lote_falho_nao_e_gravado_pela_metade(sunop, monkeypatch):
    monkeypatch.setattr(app, "SUNOP_LOTE_PATHNAMES", 3)       # 1 lote por usina
    sunop["falhar"].add(2)                                    # o 2º lote do 1º dia (o mais recente) falha
    assert app._falhas_backfill_sunop("gridco", hoje=date(2026, 9, 4)) == 0
    assert not sunop["reg"].exists() or "2026-09-03" not in _reg(sunop)
    # a próxima passada refaz o dia inteiro
    sunop["falhar"].clear()
    assert app._falhas_backfill_sunop("gridco", hoje=date(2026, 9, 4)) == 6


def test_dia_ja_baixado_nao_volta_a_sunop(sunop, monkeypatch):
    # a usina que não tinha leitura no dia continua sem registro — e nem por isso o dia volta à SunOp a cada passada
    real = app._sunop_req
    monkeypatch.setattr(app, "_sunop_req", lambda m, u, i, headers=None, params=None, json=None, timeout=None: real(
        m, u, i, headers=headers, params=params, json={"pathnames": [p for p in json["pathnames"] if not p.startswith(P1)]}))
    app._falhas_backfill_sunop("gridco", hoje=date(2026, 9, 4))
    n_antes = len(sunop["chamadas"])
    assert app._falhas_backfill_sunop("gridco", hoje=date(2026, 9, 4)) == 0
    assert len(sunop["chamadas"]) == n_antes


def test_backfill_nunca_toca_hoje(sunop):
    app._falhas_backfill_sunop("gridco", hoje=date(2026, 9, 2))
    assert {d for d, _ in sunop["chamadas"]} == {"2026-09-01"}


def test_usina_sem_leitura_no_dia_nao_ganha_registro(sunop, monkeypatch):
    # sem série nenhuma não há o que dizer — e um registro vazio apagaria as quedas gravadas daquela usina-dia
    real = app._sunop_req

    def req(metodo, url, inst, headers=None, params=None, json=None, timeout=None):
        r = real(metodo, url, inst, headers=headers, params=params, json={"pathnames": [p for p in json["pathnames"]
                                                                                        if not p.startswith(P1)]})
        return r
    monkeypatch.setattr(app, "_sunop_req", req)
    app._falhas_backfill_sunop("gridco", hoje=date(2026, 9, 2))
    assert list(_reg(sunop)["2026-09-01"]["sunop"]) == [P2]


def test_registro_em_memoria_de_ontem_nao_desfaz_o_backfill(sunop):
    # ontem ficou pela metade em memória (live); o backfill refaz e o persist do laço seguinte não volta ao parcial
    parcial = {"usina": P1, "ts": _ts("2026-09-03", "12:00"), "mortas": [], "vivas": {"Inversor 1": 3}}
    app._FALHAS_MORTAS[("sunop", "2026-09-03")] = {P1: dict(parcial)}
    app._falhas_backfill_sunop("gridco", hoje=date(2026, 9, 4))
    app._falhas_persistir_mortas()
    assert _reg(sunop)["2026-09-03"]["sunop"][P1]["origem"] == "backfill"


def test_axis_grava_na_chave_da_axis(sunop, monkeypatch):
    monkeypatch.setattr(app, "_axis_meta", {P2: {"inv_strings": STRS[P2], "trackers": {}}})
    monkeypatch.setattr(app, "_axis_str_med_cache", {})
    app._falhas_backfill_sunop("axis", hoje=date(2026, 9, 2))
    assert list(_reg(sunop)["2026-09-01"]) == ["axis"]


def test_o_laco_do_backfill_roda_no_worker():
    # pelo nome que o código carrega, não pelo texto: linha comentada não conta
    assert "_falhas_backfill_sunop_loop" in app._iniciar_loops_de_fundo.__code__.co_names


def test_backfill_refaz_o_dia_avaliado_com_a_regua_anterior(sunop):
    # 29/09: a régua passou a separar a sombra que cresce devagar (MAB100 ST07) — o dia avaliado antes disso é refeito,
    # mesmo já tendo sido baixado pela versão anterior do backfill
    _grava(sunop, {"2026-09-03": {"sunop": {P1: {"usina": P1, "ts": _ts("2026-09-03", "23:50"), "mortas": [],
                                                 "vivas": {"Inversor 1": 3}}}}})
    import json as _j
    open(app.FALHAS_BF_ESTADO, "w", encoding="utf-8").write(_j.dumps({"gridco": {"2026-09-03": 1}}))
    app._falhas_backfill_sunop("gridco", hoje=date(2026, 9, 4))
    ent = _reg(sunop)["2026-09-03"]["sunop"][P1]
    assert ent["origem"] == "backfill" and ent["regua"] == app.FALHAS_REGUA_VER and "sombras" in ent
