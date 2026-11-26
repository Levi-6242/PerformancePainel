# -*- coding: utf-8 -*-
"""As strings pelo logger do COS no formato de sempre, na Sala de controle (26/11/2026).

Levi, na Santo Anastácio com a API PV fora: o quadro cru do logger "completamente fora do padrão criado, sendo que os
dados que a gente puxa do COS tem dado histórico"; e "sim" à proposta de fazer do COS a reserva por dentro da Sala. O que
este arquivo prova:

- a leitura do logger sai nos nomes, nas esperadas, nas trancadas e na régua da API PV, pela MESMA montagem do drill, sem
  nenhuma ida à API PV (paga) e sem a combiner guardada dela;
- o inversor que o logger não trouxe fica "sem leitura", NÃO desligado; o que não casou vai para `fora`, com o motivo;
- o inversor em que as duas leituras já discordaram fica fora até nova prova (a Rodrigues 1 de 17/11/2026);
- o drill do logger não entra no memo da API PV (não é leitura dela);
- a tela pede as duas rotas e o gestor (só leitura) alcança as duas.
"""
import json
import os

import pytest

import app
import leitura_nexus
import sala_cos

PID, NOME = 987661, "Usina Teste Reserva Do Cos"
DEVS = [{"device_id": i, "device_name": f"INV0{i}", "device_type": "INVERTER"} for i in (1, 2, 3)]


class _ProibidaApiPv:
    def post(self, *a, **k):
        raise AssertionError("o drill do logger foi à API PV")

    get = post


@pytest.fixture
def sala(monkeypatch, tmp_path, freeze_now):
    freeze_now("2026-11-26 12:00:00")
    monkeypatch.setattr(app, "_http", lambda: _ProibidaApiPv())
    monkeypatch.setattr(app, "get_plants", lambda *a, **k: (_ for _ in ()).throw(AssertionError("lista de usinas")))
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: (_ for _ in ()).throw(AssertionError("token da API PV")))
    monkeypatch.setattr(app, "_combiner_guardada", lambda *a: (_ for _ in ()).throw(AssertionError("combiner da API PV")))
    monkeypatch.setattr(app, "_os_atribuidas_map", lambda: {})
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    monkeypatch.setattr(app, "_poa_atual_por_pid", lambda: {})
    monkeypatch.setattr(app, "_pv_devs_cache", {PID: {"ts": 0.0, "devs": [dict(d) for d in DEVS]}})
    monkeypatch.setattr(app, "_plants_cache", {"data": [{"id": PID, "nome": NOME}], "ts": 0.0})
    monkeypatch.setattr(app, "_pv_dev_names_cache", {})
    monkeypatch.setattr(app, "_FALHAS_PV_DEV", str(tmp_path / "falhas_pv_dev.json"))      # não existe: sem a cópia em disco
    monkeypatch.setattr(app, "_PV_NOMES_FALHAS", {"mtime": None, "dados": {}})
    monkeypatch.setattr(app, "_PV_PLANT_MEMO", {})
    monkeypatch.setattr(app, "_trancadas", {app._str_key(PID, 1, "Ipv4")})
    monkeypatch.setitem(app.EQUIP_NAMES, NOME, {"INV01": "Inversor 1.1", "INV02": "Inversor 1.2", "INV03": "Inversor 1.3"})
    monkeypatch.setitem(app.ESPERADO_INV, NOME, {"INV01": 3, "INV02": 4, "INV03": 4})
    monkeypatch.setattr(app, "_SALA_COS_CONF", sala_cos.Conferencias(str(tmp_path / "conf.json"), os.replace))
    app.app.config["TESTING"] = True
    with app.app.test_client() as c:
        yield c


DO_LOGGER = [
    {"ch": "1.1", "nome": "SKID 1 - INV01", "kw": 40.0, "ss": [[1, 8.1], [2, 8.0], [3, 7.9], [4, 0.0]]},
    {"ch": "1.2", "nome": "SKID 1 - INV02", "kw": 38.0, "ss": [[1, 8.0], [2, 0.0], [3, 8.2], [4, 8.1]]},
    {"ch": "9.9", "nome": "SKID 9 - INV09", "kw": 10.0, "ss": [[1, 5.0]]},
]


def _strings(c, corpo=None):
    r = c.post("/api/sala/cos/strings", json=corpo or {"plant_id": PID, "inversores": DO_LOGGER})
    return r.status_code, r.get_json()


def test_o_logger_sai_nos_nomes_esperadas_e_trancadas_da_api_pv_sem_ir_a_ela(sala):
    st, j = _strings(sala)
    assert st == 200 and j["ok"] and j["da_cos"] and j["lido_em"] == "12:00"
    por = {i["nome"]: i for i in j["inversores"]}
    assert set(por) == {"Inversor 1.1", "Inversor 1.2", "Inversor 1.3"}
    i1, i2 = por["Inversor 1.1"], por["Inversor 1.2"]
    # a 4ª do 1.1 é trancada (sem cabo): fica fora da conta, e o 1.1 fecha as 3 esperadas
    assert [s["status"] for s in i1["strings"]] == ["ativa", "ativa", "ativa", "trancada"]
    assert (i1["str_esp"], i1["strings_ativas"], i1["diferenca"]) == (3, 3, 0)
    # a string 2 do 1.2 sem corrente com o inversor gerando: falta 1, como na leitura da API PV
    assert [s["status"] for s in i2["strings"]] == ["ativa", "sem_corrente", "ativa", "ativa"]
    assert (i2["str_esp"], i2["strings_ativas"], i2["diferenca"]) == (4, 3, -1)
    assert i1["active_power"] == 40.0 and i1["cos"] == "sem_prova" and not i1.get("sem_cos")


def test_o_que_o_logger_nao_trouxe_fica_sem_leitura_e_nao_desligado(sala):
    st, j = _strings(sala)
    i3 = next(i for i in j["inversores"] if i["nome"] == "Inversor 1.3")
    assert i3["sem_cos"] is True and i3["desligado"] is False and i3["strings"] == [] and i3["diferenca"] is None
    assert j["fora"] == [{"nome": "SKID 9 - INV09", "motivo": "nenhum inversor da API PV com este nome"}]


def test_o_drill_do_logger_nao_entra_no_memo_da_api_pv(sala):
    _strings(sala)
    assert PID not in app._PV_PLANT_MEMO


def test_inversor_em_que_as_duas_leituras_discordaram_fica_fora_ate_nova_prova(sala):
    r = sala.post("/api/sala/cos/conferencia", json={"plant_id": PID, "pares": [
        {"ch": "1.2", "ok": False, "zer": 0, "comp": 4, "motivo": "1 de 4 strings não batem"},
        {"ch": "1.1", "ok": True, "zer": 1, "comp": 4},
        {"ch": "1.3", "ok": False, "zer": 0, "comp": 2, "motivo": "poucas strings para comparar"}]})   # não conclusivo
    assert r.get_json() == {"ok": True, "mudou": 2}
    conf = sala.get(f"/api/sala/cos/conferencia?plant_id={PID}").get_json()["conferencia"]
    assert set(conf) == {"1.1", "1.2"}
    st, j = _strings(sala)
    por = {i["nome"]: i for i in j["inversores"]}
    assert por["Inversor 1.1"]["cos"] == "numeracao"
    assert por["Inversor 1.2"]["sem_cos"] is True
    assert any(f["nome"] == "SKID 1 - INV02" and "não bateram" in f["motivo"] for f in j["fora"])


def test_sem_os_dispositivos_da_api_pv_nao_monta(sala, monkeypatch):
    monkeypatch.setattr(app, "_pv_devs_cache", {})
    st, j = _strings(sala)
    assert st == 409 and "não tem guardados os inversores" in j["motivo"]
    st, j = _strings(sala, {"plant_id": PID, "inversores": [{"ch": "7.7", "nome": "X", "ss": [[1, 2.0]]}]})
    assert st == 409


def test_processo_reiniciado_com_a_api_pv_fora_monta_pela_copia_em_disco(sala, monkeypatch, tmp_path):
    """Sem a lista de usinas nem os dispositivos em memória (o web recém-reiniciado, a API PV fora: quando a reserva mais
    importa), o nome e os dispositivos vêm da cópia em disco das Falhas (7 dias)."""
    monkeypatch.setattr(app, "_plants_cache", {"data": None, "ts": 0.0})
    monkeypatch.setattr(app, "_pv_devs_cache", {})
    (tmp_path / "falhas_pv_dev.json").write_text(json.dumps({str(PID): {
        "ts": "0", "nome_api": NOME, "usina": "Reserva", "names": {str(d["device_id"]): d["device_name"] for d in DEVS}}}),
        encoding="utf-8")
    st, j = _strings(sala)
    assert st == 200, j
    assert {i["nome"] for i in j["inversores"]} == {"Inversor 1.1", "Inversor 1.2", "Inversor 1.3"}


def test_pedido_torto_responde_400(sala):
    assert sala.post("/api/sala/cos/strings", json={"inversores": []}).status_code == 400
    assert sala.post("/api/sala/cos/strings", json={"plant_id": PID, "inversores": "x"}).status_code == 400
    assert sala.post("/api/sala/cos/conferencia", json={"plant_id": PID, "pares": {}}).status_code == 400


# ── a regra pura ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_chave_do_inversor():
    assert sala_cos.chave_inv("Inversor 1.3") == "1.3"
    assert sala_cos.chave_inv("Inversor 01.10") == "1.10"
    assert sala_cos.chave_inv("INV03") is None


def test_chave_repetida_nao_liga_nenhum():
    m = sala_cos.mapa_dispositivos({1: "a", 2: "b", 3: "c"}, {"a": "Inversor 1.1", "b": "Inversor 1.1", "c": "Inversor 1.2"}.get)
    assert m == {"1.2": 3}


def test_estado_da_prova(tmp_path):
    cf = sala_cos.Conferencias(str(tmp_path / "c.json"), os.replace)
    assert sala_cos.estado(cf.ler(1), "1.1") == ""
    cf.gravar(1, [{"ch": "1.1", "ok": True, "zer": 0, "comp": 6}], "2026-11-26T10:00:00")
    assert sala_cos.estado(cf.ler(1), "1.1") == "inversor"
    cf.gravar(1, [{"ch": "1.1", "ok": True, "zer": 2, "comp": 6}], "2026-11-26T11:00:00")
    assert sala_cos.estado(cf.ler(1), "1.1") == "numeracao"
    cf.gravar(1, [{"ch": "1.1", "ok": False, "comp": 6, "motivo": "2 de 6 strings não batem"}], "2026-11-26T12:00:00")
    assert sala_cos.estado(cf.ler(1), "1.1") == "contradita"
    # depois da discordância, a leitura que volta a bater com tudo ligado prova o inversor, não a numeração antiga
    cf.gravar(1, [{"ch": "1.1", "ok": True, "zer": 0, "comp": 6}], "2026-11-26T13:00:00")
    assert sala_cos.estado(cf.ler(1), "1.1") == "inversor"


def test_registros_do_logger():
    recs, usados, fora = sala_cos.registros(
        [{"ch": "1.1", "nome": "A", "kw": 3.5, "ss": [[1, 2.0], [2, None], ["x", 1], [3, True]]},
         {"ch": "1.2", "nome": "B", "ss": []}], {"1.1": 11, "1.2": 12}, {}, "2026-11-26 12:00:00")
    assert usados == {11: "1.1"} and [f["nome"] for f in fora] == ["B"]
    assert json.loads(recs[0]["conteudojson"]) == {"Ipv1": 2.0, "Pac": 3.5}
    assert recs[0]["idefinversor"] == 11 and recs[0]["tsleitura_new"] == "2026-11-26 12:00:00"


# ── a tela e o portão do gestor ───────────────────────────────────────────────────────────────────────────────────
def test_a_tela_pede_as_duas_rotas_e_o_gestor_alcanca():
    app.app.config["TESTING"] = True
    with app.app.test_client() as c:
        html = c.get("/painel/sala-de-controle").get_data(as_text=True)
    for x in ("/api/sala/cos/strings", "/api/sala/cos/conferencia", "cosParaDrill", "Strings pelo logger do COS"):
        assert x in html, x
    assert {"/api/sala/cos/strings", "/api/sala/cos/conferencia"} <= set(leitura_nexus.POSTS_DE_CONSULTA_GESTOR)
