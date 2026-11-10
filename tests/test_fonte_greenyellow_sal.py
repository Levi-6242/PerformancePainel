# -*- coding: utf-8 -*-
"""GreenYellow e Sal Energia pelo scadaGridco, como as outras fontes (06/10/2026, Levi: "separe green yellow e sal
energia"; tempo real "Igual às outras fontes"; histórico "só até 45 dias tá bom").

Tabela de strings, drill por inversor, curva de hoje e de até 45 dias atrás, card na Entrada e o rollup do macro. Os
pacotes têm o formato que a API devolveu em 06/10/2026, cortados; o cadastro é o da aba Equipamentos (14 strings por
inversor nas duas da GreenYellow; a Demerval Lobão tem 20 inversores e só a UG 01, 12, no scadaGridco)."""
import re
import time
from pathlib import Path

import pytest

import app
import scadagridco as sg

RAIZ = Path(app.__file__).resolve().parents[1]
MON = (RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")
ENT = (RAIZ / "docs" / "redesign" / "Entrada.html").read_text(encoding="utf-8")
TS = time.time() - 120


def _eq(n, correntes=None, pot=190.0, fault=192):
    m = {"active_power": pot, "total_daily_energy": 1200.0 + n, "temperature_current": 60.0 + n,
         "serial_number": f"SN{n}"}
    cs = correntes if correntes is not None else [9.0] * 14
    for i in range(1, 29):
        m[f"string_current_{i:02d}"] = cs[i - 1] if i <= len(cs) else 0.0      # Huawei: 28 entradas, 14 ligadas
    return {"equipamento": str(n), "indice": n, "tipo": "inverter", "communication_fault": fault,
            "falha_comunicacao": fault != 192, "stale": False, "ts": TS, "measurements": m}


def _mqtt(n_inv, mexe=None):
    eqs = [_eq(i) for i in range(1, n_inv + 1)]
    for i, kw in (mexe or {}).items():
        eqs[i - 1] = _eq(i, **kw)
    return {"usina": "x", "gateway": {"online": True}, "equipamentos": eqs}


def _modbus_fora(n):
    return {"units": [{"label": f"INV {i:02d}", "slave_id": i, "read_error": "TimeoutError: timed out",
                       "stale": True, "updated_at": 0.0, "measurements": {}} for i in range(1, n + 1)]}


# Rio do Peixe I e II (Apolo, 29/10/2026): 21 equipamentos no supervisório, 20 no cadastro (1.1-1.10 e 2.1-2.10, com
# 20/18/20 strings por UG). O 15 é cópia do 14. As entradas vivas ficam espalhadas pelas 28 (no 1, a 2 a 4, 6 a 12...),
# e a temperatura vem em `temperature_internal`.
VIVAS_20 = [2, 3, 4, 6, 7, 8, 9, 10, 11, 12, 16, 17, 18, 21, 22, 23, 25, 26, 27, 28]
VIVAS_18 = [2, 3, 4, 7, 8, 9, 10, 11, 12, 16, 17, 18, 21, 22, 23, 26, 27, 28]
RDP_18 = {4, 5, 6, 7, 14, 15, 16, 17, 18}                 # os equipamentos com 18 strings (o 15 = o 14)


def _eq_rdp(n, mortas=()):
    vivas = [k for k in (VIVAS_18 if n in RDP_18 else VIVAS_20) if k not in mortas]
    m = {"active_power": 252.0, "daily_active_energy": 1100.0 + n, "temperature_internal": 40.0}
    for i in range(1, 29):
        m[f"string_{i}_current"] = 12.5 if i in vivas else 0.0
    return {"equipamento": str(n), "indice": n, "tipo": "inverter", "communication_fault": 192,
            "falha_comunicacao": False, "stale": False, "ts": TS, "measurements": m}


def _rio_do_peixe(mexe=None):
    eqs = [_eq_rdp(i, **((mexe or {}).get(i) or {})) for i in range(1, 22)]
    eqs += [{"equipamento": str(i), "tipo": "relay", "communication_fault": 192, "measurements": {"active_power": 0}}
            for i in (1, 2, 3)] + [{"equipamento": "1", "tipo": "tracker_ncu", "communication_fault": 192, "measurements": {}}]
    return {"usina": "rio_do_peixe_1_2", "gateway": {"online": True}, "equipamentos": eqs}


def _cadastro():
    irece = {f"Inversor 1.{i}": 14 for i in range(1, 11)}
    dem = {f"Inversor 1.{i}": 14 for i in range(1, 13)} | {f"Inversor 2.{i}": 14 for i in range(1, 9)}
    sal = {f"Inversor 1.{i}": 22 for i in range(1, 11)}
    cad = {app._nrm("Irece 2"): irece, app._nrm("Demerval Lobao"): dem}
    for u in ("Aquiraz 1 (Salvales)", "Aquiraz 2 (Carosa)", "Quixadá 1 (Hortina)", "Quixadá 2 (Vitesse)"):
        cad[app._nrm(u)] = dict(sal)
    cad[app._nrm("Cascavel (Sunpower)")] = {"Inversor 1.1": 5, "Inversor 1.2": 11, "Inversor 2.1": 9}
    ug = {1: 20, 2: 20, 3: 20, 4: 18, 5: 18, 6: 18, 7: 18, 8: 20, 9: 20, 10: 20}
    cad[app._nrm("Rio do Peixe I e II")] = {f"Inversor {g}.{i}": e for g in (1, 2) for i, e in ug.items()}
    # Macaíba (GreenYellow), Gravatá II e Iramaia II (Apolo), 10/11/2026: 14 strings em cada inversor
    cad[app._nrm("Macaiba 1")] = {f"Inversor 1.{i}": 14 for i in range(1, 9)} | {f"Inversor 2.{i}": 14 for i in range(1, 8)}
    for u in ("Gravatá II", "Iramaia II"):
        cad[app._nrm(u)] = {f"Inversor 1.{i}": 14 for i in range(1, 11)}
    return cad


@pytest.fixture
def api(monkeypatch):
    """A API falsa: a Irecê 2 com o equipamento 4 (= Inversor 1.4, ordem natural) com a string 3 sem corrente; a Sal Energia toda em
    timeout. Conta os pedidos."""
    pedidos = []
    resp = {"/api/mqtt/irece_2": _mqtt(10, {4: {"correntes": [9.0, 9.0, 0.0] + [9.0] * 11}}),
            "/api/mqtt/dermeval_lobao": _mqtt(12)}
    for u, n in (("salvales", 10), ("carosa", 10), ("sunpower", 11), ("hortina", 10), ("vitesse", 10)):
        resp[f"/api/inversores/{u}"] = _modbus_fora(n)
    resp["/api/mqtt/rio_do_peixe_1_2"] = _rio_do_peixe()
    resp["/api/mqtt/macaiba"] = _mqtt(15)
    resp["/api/mqtt/gravata_ii_apolo"] = _mqtt(10)
    resp["/api/mqtt/iramaia_ii_apolo"] = _mqtt(10)

    def get(rota, params=None, timeout=None):
        pedidos.append((rota, dict(params or {})))
        if rota == "/api/telemetria":
            eq = str(params["equipamento"])                 # pelo nome do equipamento (11/10/2026)
            return {"registros": [{"communication_fault": 192, "data_hora": f"{params['desde']} 10:00:00",
                                   "ts": 1.0, "equipamento": eq,
                                   "pontos": {"string_current_01": 9.0, "string_current_02": 8.5,
                                              "string_current_15": 0.0, "active_power": 190.0}}],
                    "proximo_apos_ts": None}
        return resp[rota]
    monkeypatch.setattr(sg, "get", get)
    monkeypatch.setattr(app, "ESPERADO_INV_DISP", _cadastro(), raising=False)
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    monkeypatch.setattr(app, "_macro_sol_baixo", lambda r, agora=None: False)
    monkeypatch.setattr(app, "DASH_PASSWORD", "", raising=False)
    monkeypatch.setattr(app, "_sg_curvas", sg.CurvasDoDia())
    for c in (app._gy_cache, app._sal_cache, app._apo_cache):
        monkeypatch.setitem(c, "payload", None)
        monkeypatch.setitem(c, "ts", 0.0)
    app.app.config["TESTING"] = True
    with app.app.test_client() as cli:
        cli.pedidos = pedidos
        yield cli


def _linha(d, usina):
    return next(r for r in d["rows"] if r["usina"] == usina)


def test_tabela_da_greenyellow(api):
    d = api.get("/api/greenyellow/data").get_json()
    assert sorted(r["usina"] for r in d["rows"]) == ["Demerval Lobao", "Irece 2", "Macaiba 1"]
    ir = _linha(d, "Irece 2")
    assert ir["plant_id"] == "irece_2" and ir["qtd_inversores"] == 10 and not ir["sem_dados"]
    # 10 × 14 esperadas; as entradas 15 a 28 do Huawei (sem string ligada) não contam como falta
    assert ir["str_esp"] == 140 and ir["strings_ativas"] == 139 and ir["diferenca"] == -1
    assert ir["ultima_leitura"] and ir["temp_media"] is not None and ir["pot_inv_med"] == pytest.approx(190.0)
    assert "sol_baixo" in ir                                       # passou pelo _servir_tabela_strings


def test_demerval_conta_so_a_ug_que_a_fonte_tem(api):
    """12 de 20 inversores no scadaGridco: esperadas da usina = as dos 12 (168), não as 280 do cadastro inteiro."""
    dm = _linha(api.get("/api/greenyellow/data").get_json(), "Demerval Lobao")
    assert dm["inv_esp"] == 12 and dm["str_esp"] == 168 and dm["diferenca"] == 0


def test_sal_energia_sem_leitura_e_sem_comunicacao(api):
    d = api.get("/api/salenergia/data").get_json()
    assert sorted(r["usina"] for r in d["rows"]) == sorted(u["usina"] for u in sg.FONTES["salenergia"]["usinas"])
    for r in d["rows"]:
        assert r["sem_dados"] and r["falha_comunicacao"] and r["strings_ativas"] is None
    assert d["summary"]["alertas_comm"] == 5


def test_sem_token_a_tabela_diz_e_nao_quebra(api, monkeypatch):
    def recusa(*a, **k):
        raise sg.SemAcesso("scadaGridco sem SCADAGRIDCO_URL/SCADAGRIDCO_TOKEN no tokens.txt")
    monkeypatch.setattr(sg, "get", recusa)
    d = api.get("/api/greenyellow/data?force=1").get_json()
    assert all(r["sem_dados"] for r in d["rows"]) and "token" in (d.get("aviso") or "")


def test_uma_usina_por_vez_e_um_pedido_por_usina(api):
    api.get("/api/greenyellow/data")
    assert [r for r, _p in api.pedidos] == ["/api/mqtt/dermeval_lobao", "/api/mqtt/irece_2", "/api/mqtt/macaiba"]


def test_drill_nomeia_pelo_de_para_e_mostra_so_as_ligadas(api):
    d = api.get("/api/greenyellow/plant/irece_2").get_json()
    inv = {i["nome"]: i for i in d["inversores"]}
    assert len(inv) == 10 and [i["nome"] for i in d["inversores"]][:3] == ["Inversor 1.1", "Inversor 1.2", "Inversor 1.3"]
    i18 = inv["Inversor 1.4"]                                     # o equipamento 4 (ordem natural desde 01/10/2026)
    assert i18["id"] == "4" and i18["str_esp"] == 14 and i18["strings_ativas"] == 13 and i18["diferenca"] == -1
    assert [s["id"] for s in i18["strings"]] == [str(k) for k in range(1, 15)]
    assert i18["strings"][2]["status"] == "sem_corrente" and i18["eday"] == 1204.0


def test_curva_do_inversor_de_dia_passado(api):
    d = api.get("/api/greenyellow/curva/irece_2?inv=4&data=2026-10-01").get_json()
    assert d["unidade"] == "A" and len(d["inversores"]) == 1
    iv = d["inversores"][0]
    assert iv["nome"] == "Inversor 1.4" and iv["id"] == "4"
    assert iv["curva"]["1"] == {"x": ["10:00"], "y": [9.0]} and "15" not in iv["curva"]
    assert ("/api/telemetria", {"usina": "irece_2", "desde": "2026-10-01", "ate": "2026-10-01", "tipo": "inverter",
                                "equipamento": "4", "limit": sg.LIMITE}) in api.pedidos


def test_curva_da_usina_inteira_vai_inversor_por_inversor(api):
    d = api.get("/api/greenyellow/curva/irece_2?data=2026-10-01").get_json()
    assert [iv["nome"] for iv in d["inversores"]] == [f"Inversor 1.{i}" for i in range(1, 11)]
    assert sum(1 for r, _p in api.pedidos if r == "/api/telemetria") == 10


def test_curva_alem_dos_45_dias_nao_vai_a_rede(api):
    d = api.get("/api/greenyellow/curva/irece_2?inv=1&data=2026-01-01").get_json()
    assert d["inversores"] == [] and d["motivo"] == "fora_do_historico"
    assert not any(r == "/api/telemetria" for r, _p in api.pedidos)


def test_entrada_e_rollup_tem_as_duas_fontes(api):
    assert ("Greenyellow", "GreenYellow", "greenyellow") in app._ENTRADA_GRUPOS
    assert ("Sal Energia", "Sal Energia", "salenergia") in app._ENTRADA_GRUPOS
    api.get("/api/greenyellow/data")
    api.get("/api/salenergia/data")
    fontes = {u["usina"]: u["fonte"] for u in app._portfolio_rollup()}
    assert fontes.get("Irece 2") == "GreenYellow" and fontes.get("Quixadá 1 (Hortina)") == "Sal Energia"


def test_tela_conhece_as_duas_fontes():
    for fid in ("greenyellow", "salenergia"):
        assert f"'{fid}':'{fid}'" in MON                                        # SKEY
        assert f"{fid}:'/api/{fid}/data'" in MON                                # EP.strings
        assert f"{fid}:'/api/{fid}/plant/'" in MON                              # PLANT
        assert f"id:'{fid}'" in MON                                             # chip da fonte
        assert f'"{fid}"' in ENT                                                # FONTE_ID da Entrada
    assert re.search(r"_CURVA_FONTES=\[[^\]]*'greenyellow'[^\]]*'salenergia'", MON)


def test_ponte_do_nexus_le_as_duas():
    import leitura_nexus
    assert {"greenyellow", "salenergia"} <= set(leitura_nexus.FONTES_API)


def test_aba_de_falhas_recebe_a_curva_do_dia(api, monkeypatch):
    """O worker registra a régua nova sobre a curva de hoje de cada inversor; usina sem leitura não é perguntada."""
    from datetime import datetime
    api.get("/api/greenyellow/data")
    api.get("/api/salenergia/data")
    reg = []
    monkeypatch.setattr(app, "_falhas_registra", lambda fonte, dia, pid, usina, curvas, **k: reg.append(
        (fonte, pid, usina, sorted(curvas), k.get("ids"))))
    monkeypatch.setattr(app, "_falhas_sg_ult", {"final": None})
    n = app._falhas_sg_varre(datetime(2026, 10, 6, 10, 0))
    assert n == 3 and [r[1] for r in reg] == ["dermeval_lobao", "irece_2", "macaiba"] and {r[0] for r in reg} == {"greenyellow"}
    ir = next(r for r in reg if r[1] == "irece_2")
    assert ir[2] == "Irece 2" and len(ir[3]) == 10 and ir[4]["Inversor 1.4"] == "4"
    assert app._falhas_sg_varre(datetime(2026, 10, 6, 5, 0)) == 0            # de madrugada não pergunta


def test_drill_de_noite_nao_pinta_falta(api, monkeypatch):
    """Às 22h o inversor manda pacote com tudo em zero: no drill é "desligado" sem diferença, como na RenoGrid e na
    Athon (a 1ª bancada pintava os 10 da Irecê 2 de vermelho com −14)."""
    noite = _mqtt(10)
    for e in noite["equipamentos"]:
        for k in list(e["measurements"]):
            if k.startswith("string_current_") or k == "active_power":
                e["measurements"][k] = 0.0
    monkeypatch.setattr(sg, "get", lambda rota, params=None, timeout=None: noite)
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: False)
    invs = api.get("/api/greenyellow/plant/irece_2").get_json()["inversores"]
    assert all(i["desligado"] and i["diferenca"] is None and not i["fora_da_conta"] for i in invs)


def test_csv_da_curva(api):
    r = api.get("/api/greenyellow/strings/curva.csv?usina=irece_2&data=2026-10-01")
    linhas = r.get_data(as_text=True).strip().splitlines()
    assert r.status_code == 200 and linhas[0] == "inversor,string,hora,corrente_A"
    assert "Inversor 1.4,1,10:00,9.0" in linhas and len(linhas) == 1 + 10 * 2


# ── Apolo: a Rio do Peixe I e II (29/10/2026, Levi: "As API que tem as mesmas UFVs da GreenYellow também soltou Rio do
#    Peixe 1 e 2 que é da Apolo, traga para o tempo real") ────────────────────────────────────────────────────────────
def test_apolo_tabela_da_rio_do_peixe_sem_a_copia_do_14(api):
    """20 inversores na linha (o 15 é cópia do 14 e fica de fora), as esperadas do cadastro (384) e diferença 0: pela
    ordem do cadastro o 18 (18 strings) virava o 2.8 (20 esperadas) e a linha acusava −2 que não existe."""
    d = api.get("/api/apolo/data").get_json()
    assert sorted(r["usina"] for r in d["rows"]) == ["Gravatá II", "Iramaia II", "Rio do Peixe I e II"]
    r = _linha(d, "Rio do Peixe I e II")
    assert r["plant_id"] == "rio_do_peixe_1_2" and r["qtd_inversores"] == 20 and not r["sem_dados"]
    assert r["str_esp"] == 384 and r["strings_ativas"] == 384 and r["diferenca"] == 0
    assert r["temp_media"] == pytest.approx(40.0) and r["pot_inv_med"] == pytest.approx(252.0)
    assert "/api/mqtt/rio_do_peixe_1_2" in [p for p, _q in api.pedidos]
    assert len(api.pedidos) == 3                                                     # 1 pedido por usina inteira


def test_apolo_drill_nomeia_pelo_de_para_e_acusa_a_string_morta(api, monkeypatch):
    monkeypatch.setattr(sg, "get", lambda rota, params=None, timeout=None: _rio_do_peixe({16: {"mortas": (7,)}}))
    invs = api.get("/api/apolo/plant/rio_do_peixe_1_2").get_json()["inversores"]
    por_id = {i["id"]: i for i in invs}
    assert len(invs) == 20 and "15" not in por_id and [i["nome"] for i in invs][10:12] == ["Inversor 2.1", "Inversor 2.2"]
    assert por_id["14"]["nome"] == "Inversor 2.4" and por_id["21"]["nome"] == "Inversor 2.10"
    i25 = por_id["16"]                                          # o 16 é o Inversor 2.5 (18 strings)
    assert i25["nome"] == "Inversor 2.5" and i25["str_esp"] == 18 and i25["strings_ativas"] == 17 and i25["diferenca"] == -1
    d = api.get("/api/apolo/data?force=1").get_json()["rows"][0]
    assert d["diferenca"] == -1 and d["strings_ativas"] == 383


def test_apolo_curva_da_usina_vai_nos_20_inversores(api):
    d = api.get("/api/apolo/curva/rio_do_peixe_1_2?data=" + sg.hoje()).get_json()
    assert len(d["inversores"]) == 20 and "15" not in {iv["id"] for iv in d["inversores"]}
    tel = [p for r, p in api.pedidos if r == "/api/telemetria"]
    assert len(tel) == 20 and "15" not in {p["equipamento"] for p in tel} and {p["usina"] for p in tel} == {"rio_do_peixe_1_2"}


def test_apolo_no_card_no_rollup_e_na_aba_de_falhas(api, monkeypatch):
    from datetime import datetime
    assert ("Apolo", "Apolo", "apolo") in app._ENTRADA_GRUPOS and app._ENTRADA_VKEY["apolo"] == "apo"
    api.get("/api/apolo/data")
    fontes = {u["usina"]: u["fonte"] for u in app._portfolio_rollup()}
    assert fontes.get("Rio do Peixe I e II") == "Apolo" and app._rollup_cob_fonte("Apolo", "x") == "apolo"
    reg = []
    monkeypatch.setattr(app, "_falhas_registra", lambda fonte, dia, pid, usina, curvas, **k: reg.append((fonte, pid)))
    monkeypatch.setattr(app, "_falhas_sg_ult", {"final": None})
    app._falhas_sg_varre(datetime(2026, 10, 29, 10, 0))
    assert ("apolo", "rio_do_peixe_1_2") in reg


def test_apolo_nas_listas_das_outras_telas():
    import cobertura
    import depara
    import falhas_job
    import falhas_publicar
    import falhas_vinculos
    import leitura_nexus
    import potencia_ativa
    assert cobertura.FONTES["apolo"] == "Apolo" and "apolo" in depara.FONTES_INVERSOR and "apolo" in app._DP_SG
    assert falhas_job.FONTE_ROT["apolo"] == falhas_publicar.FONTE_ROT["apolo"] == "Apolo"
    assert "apolo" in falhas_vinculos.FONTES and "apolo" in leitura_nexus.FONTES_API
    assert potencia_ativa.fonte("apolo")["familia"] == "scadagridco"
    assert "'apolo':'apolo'" in MON and "apolo:'/api/apolo/data'" in MON and "apolo:'/api/apolo/plant/'" in MON
    assert "id:'apolo'" in MON and '"Apolo": "apolo"' in ENT
    assert re.search(r"_CURVA_FONTES=\[[^\]]*'apolo'", MON) and re.search(r"_POT_FONTES=\[[^\]]*'apolo'", MON)


# ── Trackers pela API de rastreadores (03/11/2026, Levi: "já adapta para a plataforma") ─────────────────────────────
# Formato de `/api/trackers/<usina>` e `/historico` de 03/11/2026. Castelo do Piauí: "tracker-ncu1-NNN" e "-ncu2-NNN",
# intercalados na resposta; Cedro (a Cedro 1 e a 2 juntas no supervisório): "tracker-ncu1-001" a "-068"; Rio do Peixe:
# "1" a "96" (a NCU única de 29/10 virou os trackers do campo); Demerval Lobão e Irecê 2: total 0.
from datetime import datetime  # noqa: E402

_CEDRO = [{"id": "cedro_1", "scada": "cedro", "usina": "Cedro 1", "via": "mqtt", "descoberta": True, "inversores": None},
          {"id": "cedro_2", "scada": "cedro", "usina": "Cedro 2", "via": "mqtt", "descoberta": True, "inversores": None}]
_CASTELO = {"id": "castelo_do_piaui", "usina": "Castelo do Piauí", "via": "mqtt", "descoberta": True, "inversores": None}


def _girando(m):
    return -50.0 + 100.0 * (m - 360) / 720 if 360 <= m <= 1080 else -10.0


def _hist(dia, angulos, ate=None):
    """O `/historico` do dia (a resposta diz o passo dela, aqui 15): `angulos` = {equipamento: f(minuto) ou None}; nada depois de `ate` (minuto)."""
    inst = [datetime.strptime(dia, "%Y-%m-%d").replace(tzinfo=sg.TZ).timestamp() + 900 * i for i in range(96)]
    cabe = lambda i: ate is None or 15 * i <= ate                                # noqa: E731
    return {"dia": dia, "passo_min": 15, "instantes": inst,
            "alvo": [round(_girando(15 * i + 14), 2) if cabe(i) else None for i in range(96)],
            "trackers": [{"equipamento": e, "posicao": [round(f(15 * i + 14), 2) if (f and cabe(i)) else None
                                                        for i in range(96)]} for e, f in angulos.items()]}


def _agora(angulos, stale=(), alarmes=None):
    ts = time.time() - 30
    return {"total": len(angulos), "trackers": [
        {"equipamento": e, "posicao_atual": -20.0, "posicao_alvo": -20.5, "sem_comunicacao": False,
         "stale": e in stale, "alarmes": list((alarmes or {}).get(e) or []), "ts": ts} for e in angulos]}


@pytest.fixture
def trk(monkeypatch):
    """A API falsa dos rastreadores: `estado["usinas"]` = {id do supervisório: {equipamento: f(minuto)}}; conta os
    pedidos. A Castelo do Piauí e a Cedro 1/2 entram como as descobertas (sg.EXTRAS), todas liberadas no tempo real."""
    estado = {"usinas": {}, "pedidos": [], "stale": (), "alarmes": {}}

    def get(rota, params=None, timeout=None):
        estado["pedidos"].append((rota, dict(params or {})))
        m = re.match(r"^/api/trackers/([^/]+)(/historico)?$", rota)
        assert m, rota
        angs = estado["usinas"].get(m.group(1)) or {}
        if m.group(2):
            assert params["passo"] == 5
            ate = None
            if params["dia"] == sg.hoje():
                agora = datetime.now(sg.TZ)
                ate = agora.hour * 60 + agora.minute - 15
            return _hist(params["dia"], angs, ate)
        return _agora(angs, estado["stale"], estado["alarmes"])
    monkeypatch.setattr(sg, "get", get)
    monkeypatch.setattr(sg, "ATUALIZAR", None)
    monkeypatch.setattr(sg, "EXTRAS", {"greenyellow": [_CASTELO] + _CEDRO})
    monkeypatch.setattr(app, "_cob_entra", lambda fonte, chave: True)
    monkeypatch.setattr(app, "_sg_trk_hist", sg.HistoricoTrackers())
    monkeypatch.setattr(app, "DASH_PASSWORD", "", raising=False)
    for c in (app._apo_trk_cache, app._gy_trk_cache):
        monkeypatch.setitem(c, "payload", None)
        monkeypatch.setitem(c, "ts", 0.0)
    app.app.config["TESTING"] = True
    return estado


def test_trk_regua_da_2c_sobre_o_historico_girando_travado_e_mudo(trk):
    """Dia passado (só o histórico, 1 pedido): girando = normal, ângulo fixo em 4,1° o dia todo = parado (a régua da
    amplitude), sem leitura nenhuma = sem comunicação (não verde)."""
    trk["usinas"]["rio_do_peixe_1_2"] = {"1": _girando, "2": _girando, "3": _girando, "4": lambda m: 4.1, "5": None}
    a = app._sg_trackers_analise("apolo", sg.usina_cfg("apolo", "rio_do_peixe_1_2"), "2026-10-27")
    assert trk["pedidos"] == [("/api/trackers/rio_do_peixe_1_2/historico", {"dia": "2026-10-27", "passo": 5})]
    st = {t["id"]: t for t in a["trackers"]}
    assert a["total"] == 5 and [t["id"] for t in a["trackers"]] == ["1", "2", "3", "4", "5"]
    assert st["1"]["status"] == "normal" and st["1"]["amplitude"] > 90 and not st["1"]["sem_comunicacao"]
    assert st["4"]["status"] == "parado" and st["5"]["sem_comunicacao"] and a["parados"] >= 1


def test_trk_greenyellow_aba_drill_grafico_e_entrada(trk):
    """Hoje: o agora + o histórico. Castelo do Piauí na ordem dos números (ncu1 antes da ncu2, não a da API); a Cedro 1
    e a Cedro 2 numa linha só, sem chutar a divisão; a Demerval e a Irecê (total 0) não ganham linha nem pedido de
    histórico; stale do supervisório = sem comunicação; os alarmes vão como estão."""
    trk["usinas"]["castelo_do_piaui"] = {"tracker-ncu2-001": _girando, "tracker-ncu1-001": _girando,
                                         "tracker-ncu2-002": _girando, "tracker-ncu1-002": _girando}
    trk["usinas"]["cedro"] = {f"tracker-ncu1-{i:03d}": _girando for i in range(1, 69)}
    trk["stale"] = ("tracker-ncu1-002",)
    trk["alarmes"] = {"tracker-ncu2-001": ["bat_crit"]}
    hoje = sg.hoje()
    with app.app.test_client() as cli:
        d = cli.get("/api/greenyellow/trackers?force=1").get_json()
        assert sorted((r["usina"], r["plant_id"], r["total"]) for r in d["rows"]) == [
            ("Castelo do Piauí", "castelo_do_piaui", 4), ("Cedro 1 e Cedro 2", "cedro_1", 68)]
        assert d["summary"]["trackers"] == 72 and "por_pid" not in d
        hist = [r for r, _p in trk["pedidos"] if r.endswith("/historico")]
        assert sorted(hist) == ["/api/trackers/castelo_do_piaui/historico", "/api/trackers/cedro/historico"]
        dr = cli.get("/api/greenyellow/trackers/castelo_do_piaui").get_json()
        assert [t["id"] for t in dr["trackers"]] == ["tracker-ncu1-001", "tracker-ncu1-002", "tracker-ncu2-001",
                                                     "tracker-ncu2-002"]
        st = {t["id"]: t for t in dr["trackers"]}
        assert st["tracker-ncu1-002"]["sem_comunicacao"] and not st["tracker-ncu1-001"]["sem_comunicacao"]
        assert st["tracker-ncu2-001"]["alarmes"] == ["bat_crit"] and st["tracker-ncu1-001"]["alarmes"] == []
        n = len(trk["pedidos"])
        ch = cli.get(f"/api/greenyellow/trackers/cedro_2/chart?ini={hoje}&fim={hoje}").get_json()
        assert ch["plant"] == "Cedro 1 e Cedro 2" and len(ch["trackers"]) == 68 and ch["alvo"]
        assert [r for r, _p in trk["pedidos"][n:] if r.endswith("/historico")] == []    # o histórico guardado
        assert cli.get("/api/greenyellow/trackers/nao_existe").status_code == 404
    par = app._sg_parados_rows("greenyellow")                       # a Entrada: o mesmo pacote, sem ir ao supervisório
    n = len(trk["pedidos"])
    esperado = sorted((a["usina"], t["id"]) for a in app._gy_trk_cache["payload"]["por_pid"].values()
                      for t in a["trackers"] if t["status"] == "parado")
    assert sorted((r["usina"], r["tracker"]) for r in par) == esperado and len(trk["pedidos"]) == n
    assert "greenyellow:'/api/greenyellow/trackers'" in MON                     # a aba Trackers do Monitoramento


def test_trk_apolo_os_96_da_rio_do_peixe_com_o_nome_do_supervisorio(trk):
    trk["usinas"]["rio_do_peixe_1_2"] = {str(i): _girando for i in range(1, 97)}
    with app.app.test_client() as cli:
        d = cli.get("/api/apolo/trackers?force=1").get_json()
        assert [(r["usina"], r["total"]) for r in d["rows"]] == [("Rio do Peixe I e II", 96)]
        dr = cli.get("/api/apolo/trackers/rio_do_peixe_1_2").get_json()
    assert [t["id"] for t in dr["trackers"]][:3] == ["1", "2", "3"] and dr["trackers"][-1]["id"] == "96"
    assert "NCU" not in {t["id"] for t in dr["trackers"]}


def test_trk_a_entrada_nao_conta_sem_o_pacote_de_hoje(trk):
    for f in ("greenyellow", "apolo"):
        with pytest.raises(RuntimeError):
            app._sg_parados_rows(f)
    assert trk["pedidos"] == []                                                 # SÓ cache: não vai ao supervisório


def test_trk_as_duas_fontes_na_entrada_e_no_worker():
    import inspect
    src = inspect.getsource(app)
    assert 'fontes_trk["GreenYellow"] = lambda: _sg_parados_rows("greenyellow")' in src
    assert '("GreenYellow trk", _gy_trk_cache,       _build_gy_trk_payload)' in src
    assert app._persist_registry()["gy_trk"] is app._gy_trk_cache and app._SG_TRK_CACHE["greenyellow"] is app._gy_trk_cache


# ── 10/11/2026, Levi: "Usinas da Apolo no tempo real, na nossa API já temos Iramaia e Gravata, por gentileza inserir";
#    "Em greenyellow também temos macaíba". A descoberta não as casava pelo nome ("Gravata II Apolo", "Iramaia II apolo",
#    "Macaíba" no supervisório) e elas entraram na lista fixa com o de-para ────────────────────────────────────────────
def test_gravata_iramaia_e_macaiba_no_tempo_real(api):
    apo = api.get("/api/apolo/data").get_json()
    for u, pid in (("Gravatá II", "gravata_ii_apolo"), ("Iramaia II", "iramaia_ii_apolo")):
        r = _linha(apo, u)
        assert r["plant_id"] == pid and r["qtd_inversores"] == 10 and not r["sem_dados"] and r["str_esp"] == 140
    mac = _linha(api.get("/api/greenyellow/data").get_json(), "Macaiba 1")
    assert mac["plant_id"] == "macaiba" and mac["qtd_inversores"] == 15 and mac["str_esp"] == 210 and mac["diferenca"] == 0
    # o de-para: equipamento N = Inversor 1.N na Apolo; na Macaíba, 1 a 8 = UG 01 e 9 a 15 = UG 02
    assert sg.usina_cfg("apolo", "gravata_ii_apolo")["inversores"]["10"] == "Inversor 1.10"
    m = sg.usina_cfg("greenyellow", "macaiba")["inversores"]
    assert m["8"] == "Inversor 1.8" and m["9"] == "Inversor 2.1" and m["15"] == "Inversor 2.7"
