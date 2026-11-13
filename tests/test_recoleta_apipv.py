# -*- coding: utf-8 -*-
"""Recoleta pela API PV para o Conversor Grid Co. (13/11/2026; Levi: "deve ter algum campo para fazer uma recoleta pela
API... seleciona a usina, o período... geração, ETM"). A API PV é dublada: nada sai para a fonte paga."""
import datetime as dt

import pytest

import app
import recoleta_apipv as rc

HOJE = dt.date(2026, 11, 13)
CONTA = {101: "Ceilandia II - Pitangueira (89)", 202: "Altair 4"}


class Api:
    """Dublê da API PV: devolve o que o teste mandar e conta as chamadas."""

    def __init__(self, energia=None, meteo=None, devices=None):
        self.energia, self.meteo, self.devices, self.feitas = energia or {}, meteo or {}, devices or {}, []

    def __call__(self, caminho, corpo):
        self.feitas.append((caminho, dict(corpo)))
        if caminho == "/plant_devices":
            return [{"plant_devices": self.devices.get(corpo["id"], [])}]
        d = dt.date.fromisoformat(corpo["period"] + "-%02d" % corpo["day"])
        if corpo["data_type"] == "energy":
            return self.energia.get((corpo["id"], d), [])
        return self.meteo.get((corpo["id"], d), [])


@pytest.fixture(autouse=True)
def _conta_zerada(monkeypatch):
    monkeypatch.setattr(rc, "_CONTA", {"dia": None, "n": 0})


def _corpo(**kw):
    c = {"ids": [101], "ini": "2026-11-10", "fim": "2026-11-11", "geracao": True, "etm": True}
    c.update(kw)
    return c


def test_chave_e_o_hmac_da_senha_e_a_do_ambiente_vence():
    a = rc.chave_esperada("", "senha-pv")
    assert len(a) == 64 and a == rc.chave_esperada(None, "senha-pv") and a != rc.chave_esperada("", "outra")
    assert rc.chave_esperada(" fixa ", "senha-pv") == "fixa"
    assert rc.chave_esperada("", "") == "" and not rc.confere("x", "")
    assert rc.confere(a, a) and not rc.confere(a[:-1] + "0", a) and not rc.confere(None, a)


def test_hoje_e_o_de_brasilia_com_o_servidor_em_utc():
    assert rc.hoje_br(dt.datetime(2026, 11, 14, 1, 30, tzinfo=dt.timezone.utc)) == dt.date(2026, 11, 13)


@pytest.mark.parametrize("corpo, trecho", [
    (_corpo(fim="2026-11-13"), "só dia fechado"),
    (_corpo(ini="2026-11-01", fim="2026-11-08"), "no máximo 7 dias"),
    (_corpo(ini="2026-11-11", fim="2026-11-10"), "ao contrário"),
    (_corpo(ids=[999]), "fora da conta"),
    (_corpo(geracao=False, etm=False), "pelo menos"),
    (_corpo(ini="11/10/2026"), "pedido inválido"),
    (_corpo(ids=list(range(1, 10))), "no máximo 8 plantas"),
])
def test_pedido_fora_da_regra_e_recusado_sem_chamar_a_api(corpo, trecho):
    api = Api()
    with pytest.raises(rc.Recusa) as e:
        rc.recoletar(api, corpo, {**CONTA, **{i: str(i) for i in range(1, 10)}}, HOJE)
    assert e.value.status == 400 and trecho in str(e.value) and api.feitas == []


def test_geracao_por_nome_do_supervisorio_e_nulo_nao_vira_zero():
    d1 = dt.date(2026, 11, 10)
    api = Api(devices={101: [{"device_id": 7, "device_name": "INVERSOR03 ", "device_type": "INVERTER"},
                             {"device_id": 9, "device_name": "Estação", "device_type": "METEO"}]},
              energia={(101, d1): [{"idinversor": 7, "eday": "812.456", "dataleitura_new": "2026-11-10T00:00:00"},
                                   {"idinversor": 8, "eday": None, "dataleitura_new": "2026-11-10"},
                                   {"idinversor": 7, "eday": 5, "dataleitura_new": "2026-11-09"}]})
    r = rc.recoletar(api, _corpo(etm=False), CONTA, HOJE)
    dias = r["plantas"]["101"]["dias"]
    assert dias["2026-11-10"]["ger"] == {"INVERSOR03": 812.46}          # o 8 sem Eday não entra; o de outro dia também não
    assert dias["2026-11-11"]["ger"] == {}
    assert r["chamadas"] == 3 == len(api.feitas)                         # devices + 2 dias de energia
    assert r["restam"] == rc.TETO_DIA - 3


def test_etm_integrada_em_kwh_m2_pela_regra_do_coletor():
    d1 = dt.date(2026, 11, 10)
    lei = [{"tsleitura_new": "2026-11-10T%02d:00:00" % h, "conteudojson": {"Ir": 1000, "piraGHI1": 800}} for h in (11, 12)]
    lei.append({"tsleitura_new": "2026-11-10T13:00:00", "conteudojson": '{"Ir": -666, "IrPOA": 1000, "piraGHI1": 0}'})
    api = Api(meteo={(101, d1): lei})
    r = rc.recoletar(api, _corpo(geracao=False, fim="2026-11-10"), CONTA, HOJE)
    dia = r["plantas"]["101"]["dias"]["2026-11-10"]
    assert dia == {"ipoa": 2.0, "ghi": 1.2}                              # 2 h a 1000 W/m²; GHI 800, 800, 0
    assert r["chamadas"] == 1                                            # ETM sozinha não pede os inversores
    assert rc.integrar([lei[0]]) == (None, None)                         # uma leitura não é dia
    sem_ghi = [{"tsleitura_new": "2026-11-10T%02d:00:00" % h, "conteudojson": {"Ir": 500}} for h in (11, 12)]
    assert rc.integrar(sem_ghi) == (0.5, None)                           # estação sem GHI: nulo, não zero


def test_cota_na_reserva_recusa_antes_e_para_no_meio():
    with pytest.raises(rc.Recusa) as e:
        rc.recoletar(Api(), _corpo(), CONTA, HOJE, cota_permite=lambda: False)
    assert e.value.status == 429 and "reserva" in str(e.value)
    respostas = iter([True] + [False] * 10)                              # passa na entrada, acaba no meio
    r = rc.recoletar(Api(), _corpo(), CONTA, HOJE, cota_permite=lambda: next(respostas))
    assert all(d.get("erro") == "cota da API PV na reserva" for d in r["plantas"]["101"]["dias"].values())


def test_teto_do_dia_soma_os_pedidos_e_vira_no_dia_seguinte(monkeypatch):
    monkeypatch.setattr(rc, "TETO_DIA", 10)
    rc.recoletar(Api(), _corpo(), CONTA, HOJE)                           # 1 + 2 × 2 = 5
    rc.recoletar(Api(), _corpo(), CONTA, HOJE)                           # 10
    with pytest.raises(rc.Recusa) as e:
        rc.recoletar(Api(), _corpo(), CONTA, HOJE)
    assert e.value.status == 429 and "teto" in str(e.value)
    assert rc.recoletar(Api(), _corpo(), CONTA, HOJE + dt.timedelta(days=1))["restam"] == 5


def test_dia_que_falha_nao_derruba_o_pedido():
    class Quebra(Api):
        def __call__(self, caminho, corpo):
            if caminho == "/custom_query" and corpo["day"] == 11:
                raise RuntimeError("API PV HTTP 502")
            return super().__call__(caminho, corpo)
    r = rc.recoletar(Quebra(), _corpo(etm=False), CONTA, HOJE)
    assert r["plantas"]["101"]["dias"]["2026-11-11"]["erro"] == "RuntimeError: API PV HTTP 502"
    assert "erro" not in r["plantas"]["101"]["dias"]["2026-11-10"]


# ---------------------------------------------------------------- a rota
@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "senha-de-teste")
    monkeypatch.setattr(app, "PASSWORD", "senha-pv-de-teste")
    monkeypatch.delenv("RECOLETA_CHAVE", raising=False)
    monkeypatch.setattr(app, "_pv_disj_aberto", lambda: False)
    monkeypatch.setattr(app, "_pv_cota_permite", lambda: True)
    monkeypatch.setattr(app, "_recoleta_plantas", lambda: {k: (v, v) for k, v in CONTA.items()})
    monkeypatch.setattr(rc, "hoje_br", lambda agora_utc=None: HOJE)
    return app.app.test_client()


def _cab():
    return {"X-Recoleta-Chave": rc.chave_esperada("", "senha-pv-de-teste")}


def test_rota_sem_a_chave_e_401_sem_tocar_na_api(cli, monkeypatch):
    monkeypatch.setattr(app, "_recoleta_post", lambda *a: pytest.fail("chamou a API PV sem a chave"))
    assert cli.get("/api/recoleta/apipv/plantas").status_code == 401
    r = cli.post("/api/recoleta/apipv", json=_corpo(), headers={"X-Recoleta-Chave": "errada"})
    assert r.status_code == 401 and r.get_json()["erro"] == "chave da recoleta recusada"


def test_rota_com_a_chave_lista_e_recoleta(cli, monkeypatch):
    api = Api(energia={(101, dt.date(2026, 11, 10)): [{"idinversor": 7, "eday": 10.0}]},
              devices={101: [{"device_id": 7, "device_name": "INVERSOR01", "device_type": "INVERTER"}]})
    monkeypatch.setattr(app, "_recoleta_post", api)
    pl = cli.get("/api/recoleta/apipv/plantas", headers=_cab()).get_json()
    assert pl["plantas"][0] == {"id": 101, "nome": CONTA[101], "cadastro": CONTA[101]}
    assert pl["max_dias"] == rc.MAX_DIAS and pl["restam_hoje"] == rc.TETO_DIA
    r = cli.post("/api/recoleta/apipv", json=_corpo(etm=False, fim="2026-11-10"), headers=_cab())
    assert r.status_code == 200 and r.get_json()["plantas"]["101"]["dias"]["2026-11-10"]["ger"] == {"INVERSOR01": 10.0}
    assert cli.post("/api/recoleta/apipv", json=_corpo(fim="2026-11-13"), headers=_cab()).status_code == 400


def test_rota_com_a_api_pv_fora_e_503(cli, monkeypatch):
    monkeypatch.setattr(app, "_pv_disj_aberto", lambda: True)
    assert cli.post("/api/recoleta/apipv", json=_corpo(), headers=_cab()).status_code == 503
