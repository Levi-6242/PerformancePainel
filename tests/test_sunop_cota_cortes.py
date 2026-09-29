# -*- coding: utf-8 -*-
"""Cortes no gasto da SunOp (29/09/2026, Levi: "teremos um limite de 100.000 requisições por mês").

Extrato oficial (`/data/v2/usage/me`) de 01 a 29/09: 323.816 requisições, 3,2× a cota; ~22 mil por dia desde 24/09,
para um teto de ~3.300. Quatro cortes, cada um com o seu teste:

1. **Status em lotes que atravessam usinas.** A tabela da Athon pedia o `last_values` em lotes de 500 POR USINA: 6.966
   pathnames em 19 POSTs por leitura. A SunOp aceita 1.000 de usinas diferentes num pedido (medido: 1.000 → 1.002
   valores, 1,06 s) — 7 POSTs. A ETM ia em 1 POST por usina (10 por leitura) e vai em 1.
2. **O `check_token` vale 15 min.** `get_sunop_token` validava o token na rede a CADA chamada, e `ensure_sunop_meta` (no
   começo de ~20 montadores) montava o cabeçalho antes de olhar o cache: ~2 mil validações por dia por worker, fora
   do contador.
3. **O contador conta tudo e não zera no reinício.** Contava só o serviço de dados, somava a Axis (outra conta) junto
   e cada restart regravava o arquivo do dia por cima — com 9 deploys por dia, o extrato não fechava.
4. **O PC coleta só o que a ronda usa** (`SUNOP_COLETA=ronda`). Servidor e PC faziam a MESMA coleta inteira. A ronda
   das 08:25 e das 13:00 roda no PC e usa as curvas de tracker da Athon (e o registro do dia anterior): essas ficam.
"""
import json

import pytest

import app


# ── 1. status em lotes que atravessam usinas ─────────────────────────────────────────────────────────────────────────
def _meta(n_inv, n_str, pref):
    inv_strings = {f"INV_{i}": [f"{pref}.INV_{i}.MEDIDAS.STR.I_PV{s}" for s in range(1, n_str + 1)] for i in range(1, n_inv + 1)}
    inv_other = {f"INV_{i}": {"P": f"{pref}.INV_{i}.MEDIDAS.P", "TEMP_INT": f"{pref}.INV_{i}.MEDIDAS.TEMP_INT"}
                 for i in range(1, n_inv + 1)}
    return {"inv_strings": inv_strings, "inv_other": inv_other, "plant_paths": {"LOGGER.TOT.P": f"{pref}.LOGGER.TOT.P"},
            "trackers": {}, "etm_stations": {"ESTM": {"poa": f"{pref}.ESTM.POA.IRAD", "ghi": f"{pref}.ESTM.GHI.IRAD",
                                                      "poari": f"{pref}.ESTM.POA_R.IRAD"}}}


METAS = {"AAA100": _meta(2, 300, "AAA100"), "BBB100": _meta(2, 350, "BBB100"), "CCC100": _meta(1, 290, "CCC100")}


@pytest.fixture
def sunop_falso(monkeypatch, freeze_now):
    """SunOp de mentira: cada pathname pedido volta com um valor fixo e o carimbo de agora. Registra os lotes."""
    freeze_now("2026-09-29 11:00:00")
    lotes, falhar = [], set()
    monkeypatch.setattr(app, "_sunop_meta", dict(METAS))
    monkeypatch.setattr(app, "_sunop_plants_lista", {"gridco": {"nomes": list(METAS), "ts": 1e18}})
    monkeypatch.setattr(app, "ESPERADO_INV", {})

    class _R:
        def __init__(self, ok, vals):
            self.status_code = 200 if ok else 500
            self._vals = vals

        def json(self):
            return self._vals

    def _req(metodo, url, inst="gridco", **kw):
        ps = (kw.get("json") or {}).get("pathnames") or []
        lotes.append(list(ps))
        if len(lotes) in falhar:
            return _R(False, None)
        vals = []
        for p in ps:
            v = 7.5 if ".I_PV" in p else (420.0 if p.endswith(".IRAD") else (55.0 if p.endswith(".P") else 40.0))
            vals.append({"pathname": p, "value": v, "timestamp": "2026-09-29T10:55:00"})
        return _R(True, vals)

    monkeypatch.setattr(app, "_sunop_req", _req)

    class _SemRede:                                  # nada aqui pode tocar a SunOp de verdade (gasta cota e trava)
        def __getattr__(self, nome):
            raise AssertionError(f"chamada de rede no teste: {nome}")

    monkeypatch.setattr(app, "_http", lambda: _SemRede())
    return lotes, falhar


def test_a_tabela_pede_o_status_em_lotes_que_atravessam_usinas(sunop_falso):
    lotes, _ = sunop_falso
    total = sum(len(app._sunop_paths_tabela(m)) for m in METAS.values())       # 1.891 pathnames
    rows = app.fetch_all_sunop("gridco")
    assert [len(l) for l in lotes] == [app.SUNOP_LV_LOTE, total - app.SUNOP_LV_LOTE]
    assert {r["plant_id"] for r in rows} == set(METAS) and not any(r["sem_dados"] for r in rows)


def test_a_linha_de_cada_usina_e_a_mesma_do_pedido_por_usina(sunop_falso):
    lotes, _ = sunop_falso
    juntos = {r["plant_id"]: r for r in app.fetch_all_sunop("gridco")}
    lotes.clear()
    sozinhos = {p: app.process_plant_sunop(p, "gridco") for p in METAS}
    assert juntos == sozinhos


def test_lote_que_falha_so_derruba_quem_estava_nele(sunop_falso):
    lotes, falhar = sunop_falso
    falhar.add(2)                                    # o 2º lote: o fim da BBB100 e a CCC100 inteira
    rows = {r["plant_id"]: r for r in app.fetch_all_sunop("gridco")}
    no_2 = {p.split(".")[0] for p in lotes[1]}
    assert no_2 == {"BBB100", "CCC100"}
    assert rows["AAA100"]["sem_dados"] is False
    assert rows["BBB100"]["sem_dados"] and rows["CCC100"]["sem_dados"]   # foto incompleta não vira número (31/07)


def test_a_etm_das_usinas_vai_num_pedido_so(sunop_falso):
    lotes, _ = sunop_falso
    payload = app._build_sunop_etm_payload("gridco")
    assert len(lotes) == 1 and len(lotes[0]) == 9
    assert {r["plant_id"] for r in payload["rows"]} == set(METAS) and all(r["poa"] == 420.0 for r in payload["rows"])


def test_a_etm_de_cada_usina_e_a_mesma_do_pedido_por_usina(sunop_falso):
    juntos = sorted(app._build_sunop_etm_payload("gridco")["rows"], key=lambda r: r["plant_id"])
    sozinhos = sorted((r for p in METAS for r in app.fetch_sunop_etm_plant(p, "gridco")), key=lambda r: r["plant_id"])
    assert juntos == sozinhos


# ── 2. o check_token vale 15 min ──────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def config_falso(monkeypatch):
    chamadas = []

    class _R:
        def __init__(self, code, body=None):
            self.status_code = code
            self._b = body

        def json(self):
            return self._b

    class _Http:
        def get(self, url, **kw):
            chamadas.append(url.rsplit("/", 1)[-1])
            if url.endswith("/plants"):
                return _R(200, [{"name": n} for n in METAS])
            return _R(200)

    relogio = {"t": 1_790_000_000.0}
    monkeypatch.setattr(app, "_http", lambda: _Http())
    monkeypatch.setattr(app, "_sunop_relogio", lambda: relogio["t"])
    monkeypatch.setitem(app._si("gridco")["token"], "token", "eyJ.token.velho")
    monkeypatch.setattr(app, "_jwt_exp", lambda tok: app.time.time() + 5 * 86400)   # longe de vencer: sem refresh
    monkeypatch.setattr(app, "_sunop_token_ok", {})
    return chamadas, relogio


def test_o_token_e_validado_uma_vez_a_cada_15_min(config_falso):
    chamadas, relogio = config_falso
    for _ in range(5):
        app.get_sunop_token("gridco")
    assert chamadas.count("check_token") == 1
    relogio["t"] += app.SUNOP_TOKEN_VALIDO_S + 1
    app.get_sunop_token("gridco")
    assert chamadas.count("check_token") == 2


def test_token_trocado_e_validado_de_novo(config_falso):
    chamadas, _ = config_falso
    app.get_sunop_token("gridco")
    app._si("gridco")["token"]["token"] = "eyJ.token.novo"
    app.get_sunop_token("gridco")
    assert chamadas.count("check_token") == 2


def test_metadata_completa_nao_toca_a_rede(config_falso, monkeypatch):
    chamadas, relogio = config_falso
    monkeypatch.setattr(app, "_sunop_meta", dict(METAS))
    monkeypatch.setattr(app, "_sunop_plants_lista", {"gridco": {"nomes": list(METAS), "ts": app.time.time()}})
    for _ in range(20):                                  # os ~20 montadores de um ciclo
        app.ensure_sunop_meta("gridco")
    assert chamadas == []


def test_config_que_recusa_o_token_desfaz_a_validade(config_falso, monkeypatch):
    """A SunOp já derrubou as sessões web no servidor (03/09): o /plants devolve erro com o token "válido". A próxima
    chamada tem de validar de novo, e não confiar nos 15 min."""
    chamadas, relogio = config_falso
    app.get_sunop_token("gridco")

    class _Recusa:
        def get(self, url, **kw):
            chamadas.append(url.rsplit("/", 1)[-1])
            return type("R", (), {"status_code": 401, "json": lambda s: {"detail": "Invalid credentials."}})()

    monkeypatch.setattr(app, "_http", lambda: _Recusa())
    monkeypatch.setattr(app, "_sunop_plants_lista", {})
    monkeypatch.setattr(app, "_sunop_plants_do_dados", lambda inst: [])
    app.ensure_sunop_meta("gridco")
    assert "gridco" not in app._sunop_token_ok


# ── 3. o contador conta tudo e não zera no reinício ─────────────────────────────────────────────────────────────────
def test_o_contador_separa_config_e_axis(monkeypatch):
    app._sunop_uso_zerar()
    monkeypatch.setattr(app, "_SUNOP_USO_FLUSH", 10 ** 9)
    app._sunop_uso_conta("https://gridco-api.sunop.net/api/check_token")
    app._sunop_uso_conta("https://gridco-api.sunop.net/data/v2/last_values")
    app._sunop_uso_conta("https://axis-api.sunop.net/data/v2/last_values")
    assert app._sunop_uso_hoje() == {"cfg:check_token": 1, "last_values": 1, "axis:last_values": 1}


def test_a_validacao_do_token_entra_no_contador(config_falso, monkeypatch):
    app._sunop_uso_zerar()
    monkeypatch.setattr(app, "_SUNOP_USO_FLUSH", 10 ** 9)
    app.get_sunop_token("gridco")
    assert app._sunop_uso_hoje().get("cfg:check_token") == 1


def test_o_contador_soma_ao_arquivo_do_dia_depois_do_reinicio(tmp_path, monkeypatch, freeze_now):
    freeze_now("2026-09-29 15:00:00")
    (tmp_path / "logs").mkdir()
    arq = tmp_path / "logs" / "sunop_uso_worker.json"
    arq.write_text(json.dumps({"2026-09-29": {"last_values": 900}, "2026-09-28": {"last_values": 5}}), encoding="utf-8")
    monkeypatch.setattr(app, "_AQUI", str(tmp_path))
    monkeypatch.setattr(app, "_MODO_WEB", False)
    monkeypatch.setattr(app, "_SUNOP_USO_FLUSH", 1)
    app._sunop_uso_zerar()                               # o processo novo nasce zerado
    app._sunop_uso_conta("https://gridco-api.sunop.net/data/v2/last_values")
    d = json.loads(arq.read_text(encoding="utf-8"))
    assert d["2026-09-29"]["last_values"] == 901 and d["2026-09-28"]["last_values"] == 5


def test_o_extrato_separa_a_nossa_cota_da_axis(tmp_path, monkeypatch):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "sunop_uso_worker.json").write_text(json.dumps({"2026-09-29": {
        "last_values": 100, "cfg:check_token": 40, "axis:last_values": 70}}), encoding="utf-8")
    monkeypatch.setattr(app, "_AQUI", str(tmp_path))
    dia = app._sunop_uso_relatorio()["dias"]["2026-09-29"]
    assert dia["_total"] == 140 and dia["_total_axis"] == 70


# ── 4. o PC coleta só o que a ronda usa ─────────────────────────────────────────────────────────────────────────────
TAREFAS = [(n, None) for n in ("SunOp", "Axis", "SunOp ETM", "SunOp ETM anál", "SunOp trackers", "SunOp disponibilidade",
                                "Axis disponibilidade", "strings SunOp", "strings Axis", "PG snapshot", "ETM")]


def test_no_modo_ronda_o_prewarm_so_leva_os_trackers_da_athon(monkeypatch, freeze_now):
    freeze_now("2026-09-29 11:00:00")
    monkeypatch.setattr(app, "SUNOP_COLETA", "ronda")
    assert [n for n, _ in app._prewarm_filtra_noturno(TAREFAS)] == [
        "SunOp trackers", "SunOp disponibilidade", "PG snapshot", "ETM"]


def test_coleta_completa_continua_como_era(monkeypatch, freeze_now):
    freeze_now("2026-09-29 11:00:00")
    monkeypatch.setattr(app, "SUNOP_COLETA", "completa")
    assert app._prewarm_filtra_noturno(TAREFAS) == TAREFAS


def test_o_padrao_e_a_coleta_completa():
    assert app._sunop_coleta_de("") == "completa" and app._sunop_coleta_de(None) == "completa"
    assert app._sunop_coleta_de("ronda") == "ronda" and app._sunop_coleta_de(" RONDA ") == "ronda"
    assert app._sunop_coleta_de("qualquer coisa") == "completa"


def test_no_modo_ronda_a_curva_de_tracker_vale_1_h(monkeypatch):
    """A ronda busca o dia inteiro na hora de sair (force); o resto do dia o PC não precisa refazer a cada 10 min."""
    monkeypatch.setattr(app, "SUNOP_COLETA", "ronda")
    assert app._sunop_trk_ttl() == 3600
    monkeypatch.setattr(app, "SUNOP_COLETA", "completa")
    assert app._sunop_trk_ttl() == app.SUNOP_TTL == 600               # o servidor segue a régua do Levi (10 min)


def test_a_ronda_busca_a_athon_mesmo_no_modo_ronda(monkeypatch):
    """O force da ronda limpa a curva do dia e busca de novo, qualquer que seja a validade."""
    monkeypatch.setattr(app, "SUNOP_COLETA", "ronda")
    monkeypatch.setattr(app, "ensure_sunop_meta", lambda inst="gridco": None)
    monkeypatch.setattr(app, "_sunop_meta", {"AAA100": {"trackers": {"T1": {}}}})
    hist = app._si("gridco")["trk_hist"]
    monkeypatch.setitem(hist, ("AAA100", "2026-09-29"), {"ts": app.time.time(), "posat": {}, "posal": {}})
    vistos = []
    monkeypatch.setattr(app, "_sunop_trackers_plant_curva", lambda p, inst: vistos.append(p) or {"trackers": []})
    app._sunop_parados_rows("gridco", force=True)
    assert vistos == ["AAA100"] and ("AAA100", "2026-09-29") not in hist


def test_no_modo_ronda_a_entrada_nao_busca_a_athon(monkeypatch):
    """A Entrada do PC montava as curvas de tracker da Athon a cada 30 min, no processo web, sem ninguém olhando."""
    monkeypatch.setattr(app, "SUNOP_COLETA", "ronda")
    chamou = []
    monkeypatch.setattr(app, "_sunop_parados_rows", lambda inst, force=False: chamou.append(inst) or [])
    for fonte in ("Athon", "Axis"):
        with pytest.raises(RuntimeError):
            app._entrada_trk_fonte(fonte)()
    assert chamou == []
