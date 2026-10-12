# -*- coding: utf-8 -*-
"""As usinas do scadaGridco descobertas na API (Levi, 11/10/2026: "Na API que está puxando as UFVs da GreenYellow não está
aparecendo todas as UFVs"). A lista era fixa (Demerval Lobão e Irecê 2); o supervisório já tinha a Castelo do Piauí (16
inversores) e a "Cedro 1 e 2" (20, que no cadastro são a Cedro 1 e a Cedro 2, de 10 cada). Cada usina é classificada
pelo CLIENTE do cadastro; a de outro cliente fica de fora (vem pela fonte dela)."""
import json

import scadagridco as sg

CASTELO_EQ = [f"inversor-{i:02d}" for i in range(1, 9)] + [f"inversor-{i:02d}-12" for i in range(1, 9)]
CEDRO_EQ = [f"inversor-{i:02d}" for i in range(1, 11)] + [f"inversor-{i:02d}-12" for i in range(1, 11)]


def test_grupo_e_numero_do_equipamento():
    assert [sg.grupo_e_numero(x) for x in ("inversor-03", "inversor-03-12", "4", "INV 03", "medidor")] == \
        [(1, 3), (2, 3), (1, 4), (1, 3), None]


def test_mapa_pelo_nome_do_equipamento():
    cad = [f"Inversor 1.{i}" for i in range(1, 9)] + [f"Inversor 2.{i}" for i in range(1, 9)]
    m = sg.mapa_pelo_nome(CASTELO_EQ, cad)
    assert len(m) == 16 and m["inversor-03"] == "Inversor 1.3" and m["inversor-03-12"] == "Inversor 2.3"
    ced = [f"Inversor 1.{i}" for i in range(1, 11)]                    # as duas Cedro chamam os inversores de 1.x
    c1 = sg.mapa_pelo_nome(CEDRO_EQ, ced, grupo=1, alvo_grupo=1)
    c2 = sg.mapa_pelo_nome(CEDRO_EQ, ced, grupo=2, alvo_grupo=1)
    assert sorted(c1) == CEDRO_EQ[:10] and sorted(c2) == CEDRO_EQ[10:] and c2["inversor-10-12"] == "Inversor 1.10"
    assert sg.mapa_pelo_nome(CASTELO_EQ, cad[:15]) == {}                # um equipamento sem par: vale a ordem do cadastro


def _getter(rota, params=None):
    if rota == "/api/usinas":
        return {"castelo_do_piaui": {"inv_total": 16}, "cedro": {"inv_total": 20}, "dermeval_lobao": {"inv_total": 12},
                "salvales": {"inv_total": 10}, "santo_inacio_xii": {"inv_total": 0}, "crateus": {"inv_total": 0}}
    if rota == "/api/mqtt":
        return {"usinas": [
            {"usina": "castelo_do_piaui", "nome": "Castelo do Piaui",
             "equipamentos": [{"equipamento": e, "tipo": "inverter"} for e in CASTELO_EQ] + [{"equipamento": "rele", "tipo": "relay"}]},
            {"usina": "cedro", "nome": "Cedro 1 e 2", "equipamentos": [{"equipamento": e, "tipo": "inverter"} for e in CEDRO_EQ]},
            {"usina": "dermeval_lobao", "nome": "Dermeval Lobao", "equipamentos": []},
            {"usina": "santo_inacio_xii", "nome": "Santo Inacio XII", "equipamentos": []}]}
    raise AssertionError(rota)


def test_descobrir_junta_usinas_e_gateway_mqtt():
    d = {u["id"]: u for u in sg.descobrir(_getter)}
    assert d["castelo_do_piaui"]["via"] == "mqtt" and d["castelo_do_piaui"]["equipamentos"] == CASTELO_EQ
    assert d["salvales"]["via"] == "modbus" and d["crateus"]["nome"] == "crateus"


# ── a ligação com o app ───────────────────────────────────────────────────────────────────────────────────────────────
import app  # noqa: E402

INFO = {"castelodopiaui": {"usina": "Castelo do Piauí", "cliente": "Greenyellow"},
        "cedro1": {"usina": "Cedro 1", "cliente": "Greenyellow"}, "cedro2": {"usina": "Cedro 2", "cliente": "Greenyellow"},
        "santoinacioxii": {"usina": "Santo Inácio XII", "cliente": "Thopen"},
        "crateus": {"usina": "Crateus", "cliente": "Renogrid"}}
DISP = {"castelodopiauí": {**{f"Inversor 1.{i}": 14 for i in range(1, 9)}, **{f"Inversor 2.{i}": 14 for i in range(1, 9)}},
        "cedro1": {f"Inversor 1.{i}": 14 for i in range(1, 11)}, "cedro2": {f"Inversor 1.{i}": 14 for i in range(1, 11)}}


def _cadastro(monkeypatch):
    monkeypatch.setattr(app, "INFO_GERAL", INFO)
    monkeypatch.setattr(app, "ESPERADO_INV_DISP", DISP)


def test_classifica_pelo_cliente_do_cadastro_e_divide_a_cedro(monkeypatch):
    _cadastro(monkeypatch)
    out = app._sg_classifica(sg.descobrir(_getter))
    assert list(out) == ["greenyellow"]                                # Thopen e RenoGrid ficam de fora
    gy = {c["id"]: c for c in out["greenyellow"]}
    assert sorted(gy) == ["castelo_do_piaui", "cedro_1", "cedro_2"]   # a Demerval já está na lista fixa
    assert gy["castelo_do_piaui"]["usina"] == "Castelo do Piauí" and len(gy["castelo_do_piaui"]["inversores"]) == 16
    assert gy["cedro_1"]["scada"] == gy["cedro_2"]["scada"] == "cedro"
    assert sorted(gy["cedro_2"]["inversores"]) == CEDRO_EQ[10:] and gy["cedro_2"]["usina"] == "Cedro 2"


def test_a_usina_dividida_le_o_supervisorio_pelo_id_dele_e_so_os_seus_inversores(monkeypatch):
    _cadastro(monkeypatch)
    monkeypatch.setattr(sg, "EXTRAS", app._sg_classifica(sg.descobrir(_getter)))
    rotas = []

    def get(rota, params=None, timeout=None):
        rotas.append((rota, dict(params or {})))
        if rota.startswith("/api/mqtt/"):
            return {"equipamentos": [{"equipamento": e, "tipo": "inverter", "communication_fault": 192,
                                      "measurements": {"active_power": 50.0}} for e in CEDRO_EQ]}
        return {"registros": []}
    monkeypatch.setattr(sg, "get", get)
    assert sg.usina_cfg("greenyellow", "cedro_2")["usina"] == "Cedro 2" and sg.scada_id("greenyellow", "cedro_2") == "cedro"
    leit = sg.leituras("greenyellow", "cedro_2")
    assert rotas[-1][0] == "/api/mqtt/cedro" and len(leit) == 20
    cfg = sg.usina_cfg("greenyellow", "cedro_2")
    nomes = [sg.nome_inversor(cfg, x["equip"], list(DISP["cedro2"])) for x in leit]
    assert nomes.count(None) == 10 and "Inversor 1.1" in nomes        # os 10 da Cedro 1 não são desta usina
    sg.curva_inversor("greenyellow", "cedro_2", "inversor-03-12", "2026-10-11", getter=lambda r, p: get(r, p))
    assert rotas[-1] == ("/api/telemetria", {"usina": "cedro", "desde": "2026-10-11", "ate": "2026-10-11",
                                             "tipo": "inverter", "equipamento": "inversor-03-12", "limit": sg.LIMITE})


def test_o_worker_descobre_grava_e_o_web_le(monkeypatch):
    _cadastro(monkeypatch)
    monkeypatch.setattr(sg, "configurado", lambda: True)
    monkeypatch.setattr(sg, "descobrir", lambda getter=None: _descobrir_real(_getter))
    monkeypatch.setitem(app._SG_EXTRAS_MEMO, "descoberto", 0.0)
    app._sg_descobre_se_preciso(agora=10_000.0)
    gravado = json.loads(open(app._SG_EXTRAS_PATH, encoding="utf-8").read())
    assert sorted(c["id"] for c in gravado["extras"]["greenyellow"]) == ["castelo_do_piaui", "cedro_1", "cedro_2"]
    monkeypatch.setattr(sg, "EXTRAS", {})                              # o processo web, que não descobriu nada
    monkeypatch.setitem(app._SG_EXTRAS_MEMO, "mtime", None)
    assert [c["id"] for c in sg.usinas("greenyellow")] == ["dermeval_lobao", "irece_2", "castelo_do_piaui", "cedro_1", "cedro_2"]
    # sem token, API fora ou cadastro vazio: a lista de antes fica (nunca troca por vazia)
    monkeypatch.setattr(sg, "descobrir", lambda getter=None: (_ for _ in ()).throw(ConnectionError("fora")))
    monkeypatch.setitem(app._SG_EXTRAS_MEMO, "descoberto", 0.0)
    app._sg_descobre_se_preciso(agora=20_000.0)
    assert len(sg.usinas("greenyellow")) == 5


_descobrir_real = sg.descobrir
