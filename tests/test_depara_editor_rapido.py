"""O editor do de-para abre sem esperar a API PV (13/10/2026, Levi: "Gostaria de entender porquê demora tanto para
carregar o de-para de uma usina [...] Não é aceitável essa demora toda"). Cada abertura fazia, na hora, o day_inverter
(o dia inteiro, só para saber QUAIS inversores mandaram dado hoje) e, com o cache frio, o plant_devices: 0,8 a 4,6 s por
abertura no PC. Agora os ids vêm da linha da tabela que o worker já monta, e os nomes do que já foi lido."""
import json

import pytest

import app
from test_depara_equipamentos import _tabelas_do_dia, ligado  # noqa: F401  (fixture e montagem do dia)
from test_porta_nexus import _sem_rede, cli, entrar_com_senha  # noqa: F401  (fixtures da porta)

PID = 18749574


class _SemApi:
    def __init__(self):
        self.pedidos = []

    def post(self, url, **k):
        self.pedidos.append(url)
        raise AssertionError(f"o editor foi à API PV: {url}")

    get = post


def _editor_rapido(monkeypatch, linha_ts=None, ids=(501, 502)):
    """O dia da tela (cadastro, tabelas), com a tabela do worker trazendo os ids de hoje e a API PV proibida."""
    _tabelas_do_dia(monkeypatch)
    # o _tabelas_do_dia dubla o _dp_ids_hoje_api_pv e o _pv_plant_devices: aqui valem os de verdade
    monkeypatch.setattr(app, "_dp_ids_hoje_api_pv", _ORIG["ids"])
    monkeypatch.setattr(app, "_pv_plant_devices", _ORIG["devs"])
    monkeypatch.setattr(app, "_cache", {"ts": app.time.time() if linha_ts is None else linha_ts, "payload": {"rows": [
        {"plant_id": PID, "usina": "Itaja 1 (228)", "inv_ids_hoje": list(ids)}]}})
    monkeypatch.setattr(app, "_DP_HOJE_MEMO", {})
    monkeypatch.setattr(app, "ESPERADO_INV", {"Itaja 1 (551)": {"Inversor 1.1": 19, "Inversor 1.2": 19}})
    monkeypatch.setattr(app, "EQUIP_NAMES", {})
    monkeypatch.setattr(app, "_dp_planta", lambda pid: {"id": pid, "nome": "Itaja 1 (551)", "nome_api": "Itaja 1 (228)"})
    monkeypatch.setattr(app, "_pv_devs_cache", {})
    monkeypatch.setattr(app, "_pv_dev_names_cache", {PID: {"ts": 0.0, "names": {501: "Inversor 1.1", 502: "INV-02"}}})
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "tok")
    api = _SemApi()
    monkeypatch.setattr(app, "_http", lambda: api)
    return api


_ORIG = {"ids": app._dp_ids_hoje_api_pv, "devs": app._pv_plant_devices}


def test_o_editor_abre_pela_tabela_do_worker_sem_ir_a_api_pv(cli, ligado, monkeypatch):  # noqa: F811
    entrar_com_senha(cli)
    api = _editor_rapido(monkeypatch)
    d = cli.get(f"/api/admin/de-para/usina?fonte=pv&id={PID}").get_json()
    por = {x["id"]: x for x in d["inversores"]}
    assert api.pedidos == [] and set(por) == {"501", "502"} and d["fonte_hoje_erro"] is None
    assert por["501"]["origem"] == "nome" and por["502"]["nome_api"] == "INV-02" and por["502"]["na_fonte_hoje"]


def test_tabela_velha_vai_a_api_uma_vez_e_guarda_10_min(cli, ligado, monkeypatch):  # noqa: F811
    entrar_com_senha(cli)
    _editor_rapido(monkeypatch, linha_ts=app.time.time() - 3600)

    class Api:
        pedidos = []

        def post(self, url, **k):
            self.pedidos.append(url)

            class R:
                @staticmethod
                def json():
                    return [{"idefinversor": 501}, {"idefinversor": 503}]
            return R()
    api = Api()
    monkeypatch.setattr(app, "_http", lambda: api)
    for _ in range(2):
        d = cli.get(f"/api/admin/de-para/usina?fonte=pv&id={PID}").get_json()
        assert {x["id"] for x in d["inversores"]} == {"501", "503"}
    assert len(api.pedidos) == 1 and api.pedidos[0].endswith("/day_inverter")


def test_os_nomes_sem_rede_vem_da_copia_das_falhas(monkeypatch, tmp_path):
    caminho = tmp_path / "falhas_pv_dev.json"
    caminho.write_text(json.dumps({str(PID): {"names": {"501": "INV-01 ", "x": "lixo"}}}), encoding="utf-8")
    monkeypatch.setattr(app, "_FALHAS_PV_DEV", str(caminho))
    monkeypatch.setattr(app, "_PV_NOMES_FALHAS", {"mtime": None, "dados": {}})
    monkeypatch.setattr(app, "_pv_devs_cache", {})
    monkeypatch.setattr(app, "_pv_dev_names_cache", {})

    def nao(pid):
        raise AssertionError("foi à API PV")
    monkeypatch.setattr(app, "_pv_plant_devices", nao)
    assert app._dp_nomes_api(PID) == {501: "INV-01"}
