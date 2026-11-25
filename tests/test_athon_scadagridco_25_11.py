# -*- coding: utf-8 -*-
"""A Athon pelo scadaGridco, com a SunOp de reserva (25/11/2026).

Levi: "no SCADA da Grid agora tem as usinas da ATHON. Eu gostaria que todos os gráficos de string fossem puxados desses
dados da API do SCADA da Grid. E caso caia, aí vai ter de backup a API ali do SunOp"; "vai ter que ter o de para do SCADA
da Grid, para tá batendo a informação de string esperada e tudo mais"; "tem que abrir rápido, carregar rápido".

O scadaGridco entra por baixo, nos pathnames da SunOp: a linha, o drill e a curva da Athon não mudam, as esperadas e as
strings trancadas seguem pela chave dela (INV_N, I_PVn). Aqui, com uma usina de mentira (TST400) e o supervisório e a
SunOp dublados (o conftest recusa a SunOp de verdade): o de-para pelo valor (o equipamento 1 é o Inversor 1.2 = INV_2),
a SunOp que não é chamada quando o scadaGridco serve, e a reserva quando ele cai, não cobre todos os inversores ou está
sem leitura boa."""
import time

import pytest

import app
import scadagridco as sg

U = "TST400"
META = {"inv_strings": {f"INV_{i}": [f"{U}.INV_{i}.MEDIDAS.STR.I_PV{s}" for s in (1, 2, 3)] for i in (1, 2)},
        "inv_other": {f"INV_{i}": {"P": f"{U}.INV_{i}.MEDIDAS.P", "EPD": f"{U}.INV_{i}.MEDIDAS.EPD"} for i in (1, 2)},
        "plant_paths": {"LOGGER.TOT.P": f"{U}.LOGGER.TOT.P"}}
# o de-para pelo valor, de propósito fora da ordem: o equipamento 1 do supervisório é o Inversor 1.2 (= INV_2 da SunOp)
CFG = {"id": "tst_400", "usina": U, "inversores": {"1": "Inversor 1.2", "2": "Inversor 1.1"}}


def leitura(equip, strings, pot=50.0, ok=True, idade_s=60):
    return {"equip": equip, "ts": time.time() - idade_s, "ok": ok, "pot_kw": pot, "eday": 120.0, "temp": 41.0,
            "serial": None, "strings": strings}


@pytest.fixture
def athon(monkeypatch):
    estado = {"sunop": 0, "leituras": [leitura("1", {1: 8.0, 2: 8.1, 3: 0.0}), leitura("2", {1: 8.0, 2: 7.9, 3: 8.2})],
              "erro": None}

    class _R:
        status_code = 200

        def json(self):
            estado["sunop"] += 1
            ts = app.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            return [{"pathname": p, "value": 8.0, "timestamp": ts} for ps in META["inv_strings"].values() for p in ps] + \
                   [{"pathname": f"{U}.INV_{i}.MEDIDAS.P", "value": 50.0, "timestamp": ts} for i in (1, 2)]

    def _leituras(fonte, pid):
        assert (fonte, pid) == ("athonscada", "tst_400")
        if estado["erro"]:
            raise estado["erro"]
        return estado["leituras"]
    monkeypatch.setitem(app._si("gridco")["meta"], U, META)
    monkeypatch.setitem(app.ESPERADO_INV, U, {"INV_1": 3, "INV_2": 3})
    monkeypatch.setitem(app.EQUIP_NAMES, U, {"INV_1": "Inversor 1.1", "INV_2": "Inversor 1.2"})
    monkeypatch.setitem(sg.FONTES["athonscada"], "usinas", list(sg.FONTES["athonscada"]["usinas"]) + [CFG])
    monkeypatch.setattr(sg, "configurado", lambda: True)
    monkeypatch.setattr(sg, "leituras", _leituras)
    monkeypatch.setattr(app, "_sunop_req", lambda *a, **k: _R())
    monkeypatch.setattr(app, "ensure_sunop_meta", lambda *a, **k: None)
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    monkeypatch.delenv("ATHON_SCADA", raising=False)
    app._athon_sg_estado.pop(U, None)
    yield estado
    app._athon_sg_estado.pop(U, None)


def test_a_linha_vem_do_scadagridco_com_as_esperadas_da_athon_e_sem_pedir_a_sunop(athon):
    """O equipamento 1 (a string 3 em 0 A) é o INV_2: a falta cai no INV_2, contra as esperadas do cadastro."""
    r = app.process_plant_sunop(U, "gridco")
    assert athon["sunop"] == 0
    assert (r["strings_ativas"], r["str_esp"], r["diferenca"], r["fonte_strings"]) == (5, 6, -1, "scadaGridco")
    assert r["pot_med"] == 100.0 and not r["sem_dados"] and not r["falha_comunicacao"]


def test_o_drill_pelo_scadagridco_com_o_nome_e_a_chave_da_athon(athon):
    por = {i["id"]: i for i in app._sunop_plant_build(U, "gridco")}
    assert athon["sunop"] == 0
    assert por["INV_2"]["nome"] == "Inversor 1.2" and por["INV_2"]["strings_ativas"] == 2
    assert por["INV_1"]["strings_ativas"] == 3 and por["INV_1"]["eday"] == 120.0
    assert [s["id"] for s in por["INV_2"]["strings"]] == ["I_PV1", "I_PV2", "I_PV3"]


@pytest.mark.parametrize("caso", ["caiu", "sem_leitura_boa", "de_para_incompleto", "desligado"])
def test_a_sunop_segura_quando_o_scadagridco_nao_serve(athon, monkeypatch, caso):
    if caso == "caiu":
        athon["erro"] = RuntimeError("502 Bad Gateway")
    elif caso == "sem_leitura_boa":
        athon["leituras"] = [leitura("1", {1: 8.0}, idade_s=3600), leitura("2", {1: 8.0}, ok=False)]
    elif caso == "de_para_incompleto":
        monkeypatch.setitem(sg.FONTES["athonscada"], "usinas",
                            [dict(CFG, inversores={"1": "Inversor 1.2"})])
    else:
        monkeypatch.setenv("ATHON_SCADA", "0")
    r = app.process_plant_sunop(U, "gridco")
    assert athon["sunop"] >= 1 and r["fonte_strings"] == "SunOp" and r["strings_ativas"] == 6


def test_pedido_que_nao_e_da_tabela_nao_passa_pelo_scadagridco(athon):
    """A ETM (e qualquer outro pathname fora da tabela de strings) segue pela SunOp: o scadaGridco não manda ele."""
    out = app._sunop_last_values_multi({U: [f"{U}.ESTM.MEDIDAS.POA"]}, "gridco")
    assert athon["sunop"] == 1 and U in out


def test_a_curva_das_strings_pelo_scadagridco_sem_a_trancada(athon, monkeypatch):
    curvas = {"1": {"strings": {1: [("10:00", 5.0), ("10:01", 5.2)], 2: [("10:00", 5.1)], 3: [("10:00", 0.0)]}},
              "2": {"strings": {1: [("10:00", 6.0)], 2: [("10:00", 6.1)], 3: [("10:00", 6.2)]}}}
    monkeypatch.setattr(app._sg_curvas, "curva", lambda fonte, pid, equip, dia: curvas[equip])
    monkeypatch.setattr(app, "_trancadas", {app._str_key(U, "INV_1", "I_PV3")})
    hoje = app.datetime.now().strftime("%Y-%m-%d")
    p = app._sunop_strings_curva(U, hoje, None, "gridco")
    assert athon["sunop"] == 0 and p["fonte_strings"] == "scadaGridco"
    por = {i["id"]: i for i in p["inversores"]}
    assert por["INV_2"]["nome"] == "Inversor 1.2" and por["INV_2"]["curva"]["ST 01"]["y"] == [5.0, 5.2]
    assert "ST 03" not in por["INV_1"]["curva"] and por["INV_1"]["curva"]["ST 01"]["x"] == ["10:00"]
    # um inversor só (o botão "Curva do dia"): a referência da usina vem do mesmo dado, sem a SunOp
    um = app._sunop_strings_curva(U, hoje, "INV_1", "gridco")
    assert athon["sunop"] == 0 and [i["id"] for i in um["inversores"]] == ["INV_1"]


def test_a_lista_das_athon_no_scadagridco_e_o_de_para_pelo_valor():
    """As quatro que fecharam pelo valor em 23 e 24/11/2026; um equipamento por inversor, sem repetir."""
    us = {c["usina"]: c for c in sg.FONTES["athonscada"]["usinas"]}
    assert set(us) == {"CPP100", "SMP100", "TIM200", "MAB200"}
    assert {u: len(c["inversores"]) for u, c in us.items()} == {"CPP100": 14, "SMP100": 20, "TIM200": 20, "MAB200": 50}
    for c in us.values():
        assert len(set(c["inversores"].values())) == len(c["inversores"])
    assert us["TIM200"]["inversores"]["5"] == "Inversor 2.4" and us["TIM200"]["inversores"]["8"] == "Inversor 2.1"
    assert us["CPP100"]["inversores"]["14"] == "Inversor 7.2" and us["MAB200"]["inversores"]["11"] == "Inversor 2.1"


def test_com_a_sunop_parada_a_usina_dela_segura_a_ultima_boa_ao_lado_das_do_scadagridco(monkeypatch):
    """A tabela com parte pelo scadaGridco tem leitura mesmo com a SunOp pausada: a usina da SunOp sem leitura fica com
    a última linha boa (pausa, ou linha com menos de 30 min), e não "sem dados" ao lado das do supervisório."""
    agora = app.datetime.now()
    velha = (agora - app.timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")
    recente = (agora - app.timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S")
    cache = {"payload": {"rows": [{"plant_id": "A", "sem_dados": False, "ultima_leitura": velha, "strings_ativas": 9},
                                  {"plant_id": "B", "sem_dados": False, "ultima_leitura": recente, "strings_ativas": 7}]}}
    novas = [{"plant_id": "S", "sem_dados": False, "fonte_strings": "scadaGridco"},
             {"plant_id": "A", "sem_dados": True, "fonte_strings": "SunOp"},
             {"plant_id": "B", "sem_dados": True, "fonte_strings": "SunOp"}]
    monkeypatch.setattr(app, "_sunop_pausa", lambda *a, **k: None)
    out = {r["plant_id"]: r for r in app._athon_retem_linhas(novas, cache)}
    assert out["A"]["sem_dados"] is True                                  # 3 h sem ler e sem pausa: é sem dados
    assert out["B"]["strings_ativas"] == 7 and out["B"]["retido"] is True
    monkeypatch.setattr(app, "_sunop_pausa", lambda *a, **k: "teto")
    out = {r["plant_id"]: r for r in app._athon_retem_linhas(novas, cache)}
    assert out["A"]["strings_ativas"] == 9 and out["A"]["retido"] is True  # pausada: segura sem prazo
    # sem nenhuma pelo scadaGridco, nada muda (a tabela inteira segue com o _sunop_guarda_vazio de sempre)
    assert app._athon_retem_linhas([dict(r, fonte_strings="SunOp") for r in novas], cache)[1]["sem_dados"] is True
