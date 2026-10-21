# -*- coding: utf-8 -*-
"""Inversores sem de-para, à vista na linha do Tempo real (Levi, 13/10/2026, com Sete Lagoas e Tupi Paulista abertas:
"é preciso eu saber isso sem eu precisar ficar abrindo a usina, e tem que abrir um atalho direto para o de-para").

O caso: na conta oem@ (a 2C), o de-para em código chamava os inversores de "Inversor 1.x", e o cadastro (aba
Equipamentos) tinha "INVERSOR01".. com 24 e 20 esperadas. O drill mostrava "esp —" em todos, a linha fechava pelo total
(236 e 400) e o diagnóstico do de-para dizia "ok" (só conferia a quantidade de inversores). Provas: a conferência sai na
linha sem rede (o caminho do nome é o do drill), o diagnóstico acusa, o /api/eu diz quem abre o de-para, e a tela mostra
a etiqueta, a barra e o atalho só para quem abre."""
import json
import pathlib
import shutil
import subprocess

import pytest

import app
import depara_diag as dd
from test_porta_nexus import _sem_rede, cli, entrar, entrar_com_senha  # noqa: F401  (fixtures e passos da porta)

SETE = 18771901
CAD = {"INVERSOR01": 24, "INVERSOR02": 24, "INVERSOR03": 22}
IDS = [400784, 400785, 400786]
DO_CODIGO = {400784: "Inversor 1.1", 400785: "Inversor 1.2", 400786: "Inversor 1.3"}


@pytest.fixture
def cadastro(monkeypatch, tmp_path):
    monkeypatch.setitem(app.ESPERADO_INV, "Sete Lagoas", dict(CAD))
    monkeypatch.setitem(app.EQUIP_NAMES, "Sete Lagoas", {k: k for k in CAD})
    monkeypatch.setattr(app, "_FALHAS_PV_DEV", str(tmp_path / "falhas_pv_dev.json"))
    monkeypatch.setattr(app, "_PV_NOMES_FALHAS", {"mtime": None, "dados": {}})
    monkeypatch.setattr(app, "_pv_devs_cache", {})
    monkeypatch.setattr(app, "_pv_dev_names_cache", {})
    monkeypatch.setattr(app, "_pv_inv_da_tela", lambda pid: {})


def test_conta_oem_com_o_de_para_do_codigo_que_nao_casa(cadastro, monkeypatch):
    monkeypatch.setattr(app, "PV_OEM_PLANTS", {SETE})
    monkeypatch.setattr(app, "_pv_inv_nomes_de", lambda pid: dict(DO_CODIGO))
    assert app._pv_inv_sem_esperadas(SETE, "Sete Lagoas", IDS) == ["Inversor 1.1", "Inversor 1.2", "Inversor 1.3"]
    assert app._pv_inv_sem_esp_campos(SETE, "Sete Lagoas", IDS) == {
        "inv_sem_esp": 3, "inv_sem_esp_nomes": ["Inversor 1.1", "Inversor 1.2", "Inversor 1.3"], "depara_fonte": "2capi"}
    # ligados na tela (o decidido vence o código): casam, inclusive com outra grafia ("INVERSOR 03")
    monkeypatch.setattr(app, "_pv_inv_nomes_de", lambda pid: {400784: "INVERSOR01", 400785: "INVERSOR02",
                                                               400786: "INVERSOR 03"})
    assert app._pv_inv_sem_esperadas(SETE, "Sete Lagoas", IDS) == []
    assert app._pv_inv_sem_esp_campos(SETE, "Sete Lagoas", IDS) == {"inv_sem_esp": 0, "inv_sem_esp_nomes": [],
                                                                    "depara_fonte": "2capi"}
    assert app._pv_inv_sem_esp_campos(7, "Sete Lagoas", []) == {"inv_sem_esp": 0, "inv_sem_esp_nomes": [],
                                                                 "depara_fonte": "pv"}    # a conta principal


def test_conta_oem_sem_de_para_vai_pela_ordem_do_cadastro_como_o_drill(cadastro, monkeypatch):
    monkeypatch.setattr(app, "PV_OEM_PLANTS", {SETE})
    monkeypatch.setattr(app, "_pv_inv_nomes_de", lambda pid: {})
    assert app._pv_inv_sem_esperadas(SETE, "Sete Lagoas", [400786, 400784, 400785]) == []      # 3 e 3: pela ordem
    # quantidade diferente: o drill não adivinha (fica INV-id), e a conferência também não
    assert app._pv_inv_sem_esperadas(SETE, "Sete Lagoas", [400784, 400785]) == ["INV-400784", "INV-400785"]


def test_conta_principal_pelo_nome_guardado_e_sem_rede(cadastro, monkeypatch):
    monkeypatch.setattr(app, "PV_OEM_PLANTS", set())
    # sem nome guardado nenhum: não dá para saber, e a conferência NÃO chama a API PV (é paga)
    assert app._pv_inv_sem_esperadas(7, "Sete Lagoas", [1, 2]) is None
    assert app._pv_inv_sem_esp_campos(7, "Sete Lagoas", [1, 2]) == {}
    # a cópia que a rotina das Falhas guarda em disco
    pathlib.Path(app._FALHAS_PV_DEV).write_text(json.dumps({"7": {"names": {"1": "INVERSOR01", "2": "Inversor 1.2 "}}}),
                                                encoding="utf-8")
    assert app._pv_inv_sem_esperadas(7, "Sete Lagoas", [1, 2]) == ["Inversor 1.2"]
    # o cache de nomes vence a cópia em disco; o do plant_devices vence os dois; e a tela decide por cima
    app._pv_dev_names_cache[7] = {"ts": 0, "names": {1: "INVERSOR01", 2: "INVERSOR02"}}
    assert app._pv_inv_sem_esperadas(7, "Sete Lagoas", [1, 2]) == []
    app._pv_devs_cache[7] = {"ts": 0, "devs": [{"device_id": 1, "device_name": "INVERSOR01"},
                                               {"device_id": 2, "device_name": "XX"}]}
    assert app._pv_inv_sem_esperadas(7, "Sete Lagoas", [1, 2]) == ["XX"]
    monkeypatch.setattr(app, "_pv_inv_da_tela", lambda pid: {2: "INVERSOR02"})
    assert app._pv_inv_sem_esperadas(7, "Sete Lagoas", [1, 2]) == []
    # usina sem cadastro: nada a dizer aqui (o "sem de-para" da USINA já cobre)
    assert app._pv_inv_sem_esperadas(7, "Sem Cadastro", [1, 2]) == []


def _rec(inv_id, pac, n, ts="2026-10-13 09:20:00"):
    cj = {"Pac": pac, "Eday": 100.0, "Temp": 30.0, **{f"Ipv{i + 1}": 5.4 for i in range(n)}}
    return {"idefinversor": inv_id, "tsleitura_new": ts, "conteudojson": json.dumps(cj)}


def test_a_linha_da_usina_leva_a_conferencia(cadastro, monkeypatch, freeze_now):
    freeze_now("2026-10-13 09:25:00")
    monkeypatch.setitem(app.ESPERADO, "Sete Lagoas", {"inv_esp": 3, "str_esp": 70})
    monkeypatch.setattr(app, "PV_OEM_PLANTS", {SETE})
    monkeypatch.setattr(app, "_pv_inv_nomes_de", lambda pid: dict(DO_CODIGO))
    monkeypatch.setattr(app, "_pv_plant_devices", lambda pid: [])                 # a conta oem@ não lê o plant_devices
    monkeypatch.setattr(app, "_pv_dev_names", lambda pid, token: {})
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "")
    monkeypatch.setattr(app, "_os_atribuidas_map", lambda: {})
    monkeypatch.setattr(app, "_os_fracttal_inv_abertas", lambda: {})
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    r = app.build_summary({"id": SETE, "nome": "Sete Lagoas"}, [_rec(i, 50.0, 24) for i in IDS])
    assert r["inv_sem_esp"] == 3 and r["inv_sem_esp_nomes"][0] == "Inversor 1.1"
    assert r["str_esp"] == 70                                  # a linha segue fechando pelo total do cadastro
    # e leva os inversores que mandaram leitura hoje: o editor do de-para lê daqui em vez de ir à API PV (13/10/2026)
    assert r["inv_ids_hoje"] == sorted(IDS)


def test_o_diagnostico_do_de_para_acusa_inversor_sem_esperadas():
    r = {"plant_id": SETE, "usina": "Sete Lagoas", "str_esp_cadastro": 236, "inv_esp": 10, "qtd_inversores": 10,
         "inv_sem_esp": 10, "inv_sem_esp_nomes": [f"Inversor 1.{n}" for n in range(1, 11)]}
    ctx = {"inv_nomes": {SETE: {400784: "Inversor 1.1"}}}
    u = dd.linha("2capi", r, ctx)
    assert u["pior"] == "atencao" and u["sem_depara"] == "inversor" and u["nomes_inversor"] == "de-para no código"
    assert u["alertas"][0]["texto"] == ("10 de 10 inversor(es) sem esperadas: o nome que chega (Inversor 1.1, Inversor "
                                        "1.2, Inversor 1.3…) não casa com o cadastro; ligue cada um no de-para")
    assert dd.linha("2capi", {**r, "inv_sem_esp": 0}, ctx)["pior"] == "ok"            # todos casam: segue "ok"
    assert dd.linha("2capi", {k: v for k, v in r.items() if k != "inv_sem_esp"}, ctx)["pior"] == "ok"   # não se sabe


def test_api_eu_diz_quem_abre_o_de_para(cli):
    # `grava_admin` (20/10/2026): abre E grava; o gestor admin do Nexus abre e só lê (tests/test_modo_depara_backend.py)
    entrar_com_senha(cli)
    assert cli.get("/api/eu").get_json() == {"abre_admin": True, "grava_admin": True}
    entrar(cli, "analista@exemplo.com", admin=False)
    assert cli.get("/api/eu").get_json() == {"abre_admin": False, "grava_admin": False}
    entrar(cli, "admin@exemplo.com", admin=True)
    assert cli.get("/api/eu").get_json() == {"abre_admin": True, "grava_admin": True}


def test_pela_chave_de_leitura_do_nexus_nao_abre(cli, monkeypatch):
    """A ponte do Nexus lê com a chave, sem sessão: a página que ela mostra nunca oferece o atalho."""
    monkeypatch.setattr(app, "NEXUS_LEITURA_TOKEN", "chave-de-teste")
    r = cli.get("/api/eu", headers={"X-Nexus-Leitura": "chave-de-teste"})
    assert r.status_code == 200 and r.get_json() == {"abre_admin": False, "grava_admin": False}


# ── a tela ────────────────────────────────────────────────────────────────────────────────────────────────────────────
MON = (pathlib.Path(__file__).resolve().parents[1] / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(
    encoding="utf-8")


def _func(nome):
    i = MON.index("function " + nome + "(")
    return MON[i:MON.index("\n}\n", i) + 3]


def _tela(js, abre_admin):
    node = shutil.which("node")
    if not node:
        pytest.skip("node não instalado")
    he = MON[MON.index("const _he="):MON.index("\n", MON.index("const _he="))]
    base = (he + "\n" + _func("_dpSem") + _func("_dpChip") + _func("_dpBarra")
            + "const state={source:'2c'}; const SKEY={'2c':'owen'}; const RD={abreAdmin:%s};"   # a aba 2C é owen
            % ("true" if abre_admin else "undefined"))
    p = subprocess.run([node, "-e", base + js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


LINHA = {"plant_id": SETE, "qtd_inversores": 10, "inv_sem_esp": 10, "depara_fonte": "2capi",
         "inv_sem_esp_nomes": [f"Inversor 1.{n}" for n in range(1, 11)]}
JS = ("const r=%s; const d=_dpSem(r); const u={dpSem:d};"
      "process.stdout.write(JSON.stringify({d, chip:_dpChip(u), barra:_dpBarra(u), nada:_dpSem({inv_sem_esp:0}),"
      " sem:_dpChip({dpSem:_dpSem({plant_id:1})})}));" % json.dumps(LINHA))


def test_a_linha_mostra_a_etiqueta_e_o_admin_tem_o_atalho_para_o_de_para():
    t = _tela(JS, abre_admin=True)
    href = "/admin/de-para?editar=2capi%7C18771901"
    assert t["d"]["href"] == href and t["d"]["n"] == 10 and t["d"]["tot"] == 10
    assert f'<a class="gc-dp-chip" href="{href}"' in t["chip"] and "sem de-para · 10 inv." in t["chip"]
    assert "Inversor 1.1, Inversor 1.2, Inversor 1.3, Inversor 1.4…" in t["chip"]           # o motivo no título
    assert "10 de 10 inversores sem de-para" in t["barra"] and f'href="{href}"' in t["barra"]
    assert "Ligar no de-para" in t["barra"]
    assert t["nada"] is None and t["sem"] == ""                    # todos casam, ou não se sabe: nada na linha
    # o clique abre a janela por cima da tela (13/10/2026), e não troca o iframe da Entrada pela página do de-para
    abre = "onclick=\"return gcAbrirDepara(event,this.getAttribute('href'))\""
    assert abre in t["chip"] and abre in t["barra"]


def test_quem_nao_abre_o_de_para_ve_o_aviso_sem_o_atalho():
    t = _tela(JS, abre_admin=False)
    assert t["d"]["href"] == "" and "<a " not in t["chip"] and '<span class="gc-dp-chip"' in t["chip"]
    assert "Ligar no de-para" not in t["barra"] and "Peça a um administrador" in t["barra"]
