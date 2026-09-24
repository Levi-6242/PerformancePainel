# -*- coding: utf-8 -*-
"""Todas as abas no PADRÃO ATHON (Levi, 24/09/2026: "OLHA A DIFERENÇA ENTRE ATHON E THOPEN-PV / NÃO ESTÁ NO MESMO
PADRÃO, QUERO TODOS NO PADRÃO ATHON").

Dois prints lado a lado. Na Athon, toda coluna de strings tem número, e o inversor desligado aparece como aviso na
célula das esperadas ("1 inv. desligado · 13 strings fora da conta"). Na Thopen API PV, duas diferenças de regra:

1. INVERSOR DESLIGADO. A Athon tira o inversor desligado da conta — ativas E esperadas — desde 22/09
   (tests/test_inversor_desligado_fora_das_esperadas.py, que já dizia "começando pela Athon"). A API PV e o Banco
   seguiam a régua de 11/09: todas as strings dele contavam como faltando. A mesma situação lia "−24, Falha de string"
   numa aba e "Inversor desligado" na outra. Agora as três famílias de fonte com potência por inversor (SunOp, API PV,
   Banco) usam a MESMA régua (_inv_desligados_por_potencia) e levam na linha inv_desligados / strings_fora /
   inv_desligados_nomes; no drill, o inversor continua listado, marcado desligado e fora da conta.

2. COLUNAS COM TEXTO. As 13 usinas da régua de padrão por inversor (inv_padrao, 10/09) punham "18/20 inv.", "padrão
   30d", "no padrão" e "2 crônicos" nas colunas de strings. Ativas, esperadas, diferença e disponibilidade voltam a ser
   SEMPRE strings; a proporcionalidade vai para o aviso da célula das esperadas, o mesmo lugar do aviso da Athon. Ouro
   Branco, que TEM visão por string, estava com as strings escondidas atrás do texto (Ouro Branco 4: 68 de 119, −51).

Fica de fora, por falta de dado: SolarEdge (Renogrid) e a 2C do e-mail não têm potência por inversor.
"""
import json
import pathlib
import re
import shutil
import subprocess
from datetime import datetime

import pytest

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
MON = (RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")
NODE = shutil.which("node")

PID, NOME = 987655, "Usina Teste Padrao Athon"


# ── API PV: a linha da usina (build_summary) ──────────────────────────────────

def _rec(inv_id, pac, correntes, ts="2026-09-24 12:00:00"):
    cj = {"Pac": pac, "Eday": 100.0, "Temp": 30.0}
    cj.update({f"Ipv{i + 1}": c for i, c in enumerate(correntes)})
    return {"idefinversor": inv_id, "tsleitura_new": ts, "conteudojson": json.dumps(cj)}


def _registros():
    """1.1, 1.2 e 1.3 gerando (100 kW, 10 strings a 8 A); 1.4 desligado (0,3 kW), 10 strings no ruído de 0,9 A."""
    return [_rec(i, 100.0, [8.0] * 10) for i in (1, 2, 3)] + [_rec(4, 0.3, [0.9] * 10)]


@pytest.fixture
def usina_pv(monkeypatch, freeze_now):
    freeze_now("2026-09-24 12:05:00")
    # o 1.4 tem 12 esperadas no cadastro e os outros 10: o desconto tem de ser o DELE, não a média (10,5)
    monkeypatch.setitem(app.ESPERADO, NOME, {"inv_esp": 4, "str_esp": 42})
    monkeypatch.setitem(app.ESPERADO_INV, NOME, {"INVERSOR 01": 10, "INVERSOR 02": 10, "INVERSOR 03": 10, "INVERSOR 04": 12})
    monkeypatch.setitem(app.EQUIP_NAMES, NOME, {f"INVERSOR 0{i}": f"Inversor 1.{i}" for i in (1, 2, 3, 4)})
    monkeypatch.setattr(app, "_pv_dev_names", lambda pid, token: {i: f"INVERSOR 0{i}" for i in (1, 2, 3, 4)})
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "")
    monkeypatch.setattr(app, "_os_atribuidas_map", lambda: {})
    monkeypatch.setattr(app, "_os_fracttal_inv_abertas", lambda: {})
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    return {"id": PID, "nome": NOME}


def test_api_pv_tira_o_desligado_da_conta_como_a_athon(usina_pv):
    r = app.build_summary(usina_pv, _registros())
    assert r["inv_desligados"] == 1 and r["strings_fora"] == 12, "as 12 esperadas DELE no cadastro, não a média"
    assert r["inv_desligados_nomes"] == ["Inversor 1.4"], "o aviso da tela diz QUAL inversor, com o nome do cadastro"
    assert r["str_esp"] == 30 and r["strings_ativas"] == 30 and r["diferenca"] == 0


def test_api_pv_desligado_com_os_sai_pela_os_e_nao_vira_aviso(usina_pv, monkeypatch):
    """Regra de 11/09 que continua: desligado com OS no inversor é "tudo OK" — alguém já cuida."""
    monkeypatch.setattr(app, "_os_atribuidas_map", lambda: {f"{PID}|4": {"folio": "12345", "usina": NOME}})
    r = app.build_summary(usina_pv, _registros())
    assert r["inv_desligados"] == 0 and r["inv_desligados_nomes"] == [] and r["strings_fora"] == 0
    assert r["inv_com_os"] == 1 and r["strings_com_os"] == 12
    assert r["str_esp"] == 30 and r["diferenca"] == 0


def test_api_pv_sem_sol_ninguem_sai_da_conta(usina_pv, monkeypatch):
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: False)
    r = app.build_summary(usina_pv, _registros())
    assert r["inv_desligados"] == 0 and r["strings_fora"] == 0 and r["str_esp"] == 42


def test_api_pv_usina_inteira_parada_nao_esconde_as_strings(usina_pv):
    """Usina morta de dia é "Usina desligada": tirar todo mundo da conta daria '0 faltando' na usina que não gera."""
    r = app.build_summary(usina_pv, [_rec(i, 0.1, [0.0] * 10) for i in (1, 2, 3, 4)])
    assert r["inv_desligados"] == 0 and r["str_esp"] == 42 and r["strings_ativas"] == 0


# ── API PV: o drill (_pv_plant_inversores) ────────────────────────────────────

class _Resp:
    def __init__(self, d):
        self._d = d

    def json(self):
        return self._d


@pytest.fixture
def drill_pv(usina_pv, monkeypatch):
    estado = {"recs": _registros()}

    class _Http:
        def post(self, url, **k):                  # day_inverter
            return _Resp(estado["recs"])

        def get(self, url, **k):                   # plant_devices
            return _Resp([{"device_id": i, "device_name": f"INVERSOR 0{i}"} for i in (1, 2, 3, 4)])
    monkeypatch.setattr(app, "_http", lambda: _Http())
    monkeypatch.setattr(app, "get_plants", lambda token, force=False: [{"id": PID, "nome": NOME}])
    monkeypatch.setattr(app, "_combiner_strings", lambda pid, inv: None)
    return estado


def test_drill_api_pv_lista_o_desligado_marcado_e_fora_da_conta(drill_pv):
    invs = {i["nome"]: i for i in app._pv_plant_inversores(PID, force=True)}
    d = invs["Inversor 1.4"]
    assert d["desligado"] is True and d["fora_da_conta"] is True
    assert d["diferenca"] is None, "fora da conta não tem diferença — era −12, a conta de 11/09"
    assert all(s["status"] == "desligado" and s["ativa"] is False for s in d["strings"])
    assert invs["Inversor 1.1"]["fora_da_conta"] is False and invs["Inversor 1.1"]["diferenca"] == 0


def test_drill_api_pv_usina_inteira_parada_cobra_as_esperadas(drill_pv):
    """Mesma conta da linha: ninguém sai, cada inversor deve todas as suas."""
    drill_pv["recs"] = [_rec(i, 0.1, [0.0] * 10) for i in (1, 2, 3, 4)]
    invs = app._pv_plant_inversores(PID, force=True)
    assert all(i["desligado"] and not i["fora_da_conta"] for i in invs)
    assert [i["diferenca"] for i in invs] == [-10, -10, -10, -12]


# ── Banco de dados (Thopen Banco, _pg_build_snapshot) ─────────────────────────

@pytest.fixture
def banco(monkeypatch, freeze_now):
    freeze_now("2026-09-24 12:05:00")
    sup, pid, ts = "Usina PG Padrao Athon", 900001, datetime(2026, 9, 24, 12, 0)
    corrente = {1: 8.0, 2: 7.9, 3: 0.9}
    recs = [(pid, sup, d, f"INV {d}", s, corrente[d], ts) for d in (1, 2, 3) for s in range(1, 5)]

    class _Cur:
        def execute(self, sql):
            pass

        def fetchall(self):
            return recs

    class _Conn:
        def cursor(self):
            return _Cur()

        def close(self):
            pass
    monkeypatch.setattr(app, "_pg_conn", lambda: _Conn())
    monkeypatch.setattr(app, "_pg_analogic_snapshot", lambda force=False: {
        pid: [{"device_id": d, "active_power": p} for d, p in ((1, 52.0), (2, 50.5), (3, 0.0))]})
    monkeypatch.setitem(app.ESPERADO_INV, sup, {"INV 1": 4, "INV 2": 4, "INV 3": 4})
    monkeypatch.setitem(app.EQUIP_NAMES, sup, {"INV 1": "Inversor 1.1", "INV 2": "Inversor 1.2", "INV 3": "Inversor 1.3"})
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    return pid


def test_banco_tira_o_desligado_da_conta_como_a_athon(banco):
    summary, detail = app._pg_build_snapshot()
    r = next(x for x in summary if x["plant_id"] == banco)
    assert r["str_esp"] == 8 and r["strings_ativas"] == 8 and r["diferenca"] == 0
    assert r["inv_desligados"] == 1 and r["strings_fora"] == 4 and r["inv_desligados_nomes"] == ["Inversor 1.3"]
    d = {i["nome"]: i for i in detail[banco]}["Inversor 1.3"]
    assert d["fora_da_conta"] is True and d["diferenca"] is None and d["desligado"] is True
    assert {i["nome"]: i for i in detail[banco]}["Inversor 1.1"]["fora_da_conta"] is False


def test_banco_sem_sol_nada_muda(banco, monkeypatch):
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: False)
    summary, _detail = app._pg_build_snapshot()
    r = next(x for x in summary if x["plant_id"] == banco)
    assert r["str_esp"] == 12 and r["inv_desligados"] == 0 and r["strings_fora"] == 0


# ── a tela ────────────────────────────────────────────────────────────────────

def _trecho(ini, fim):
    i = MON.index(ini)
    return MON[i:MON.index(fim, i) + len(fim)]


def _node(js):
    if not NODE:
        pytest.skip("node não instalado")
    p = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def _status(r, velho=False):
    return _node("\n".join([
        _trecho("const pill=(bg,fg)=>", "\n"),
        _trecho("const pillOk=", "\n"), _trecho("const pillRed=", "\n"),
        _trecho("const pillAmber=", "\n"), _trecho("const semGer=", "\n"),
        _trecho("function _strStatus(", "/* fim _strStatus */"),
        "process.stdout.write(JSON.stringify(_strStatus(%s,%s)[0]));" % (json.dumps(r), json.dumps(velho))]))


def _nota(r):
    return _node("\n".join([_trecho("function _strNotaPadrao(", "/* fim _strNotaPadrao */"),
                            "process.stdout.write(JSON.stringify(_strNotaPadrao(%s)));" % json.dumps(r)]))


def _linhas():
    m = MON[MON.index("usinas=pv.rows.filter("):]
    return m[:m.index("}).sort(")]


def test_colunas_de_strings_nao_levam_texto_do_padrao():
    """O print: "20/20 inv.", "padrão 30d", "no padrão" e "2 crônicos" onde a Athon tem número de strings."""
    m = _linhas()
    for texto in ("} inv.`", "padrão ${", "'no padrão'", "crônico${"):
        assert texto not in m, f"{texto!r} voltou para as colunas de strings"
    assert re.search(r"active:\(r\.rampa\|\|r\.sem_visao\|\|semCom\)\?'—'", m)
    assert re.search(r"expected:\(r\.rampa\|\|r\.sem_visao\|\|semSol\)\?'—'", m)
    assert re.search(r"diff:\(r\.rampa\|\|r\.sem_visao\)\?'—'", m)


def test_o_aviso_do_padrao_fica_na_celula_das_esperadas():
    assert "padNote:semCom?null:_strNotaPadrao(r)" in _linhas()
    assert "${u.padNote?`<span class=\"gc-desl\"" in MON, "o aviso usa a mesma linha miúda do aviso da Athon"


def test_sem_visao_leva_o_pior_inversor_no_aviso():
    n = _nota({"sem_visao": True, "inv_padrao": {"status": "atencao", "dia": "2026-09-23", "n_dias_base": 30, "cronicos": [],
                                                 "alertas": [{"inv": "Inversor 2.6", "delta": -15.9, "razao": 83, "base": 99}]}})
    assert n["txt"] == "Inversor 2.6 -15,9 pp do padrão 30d"
    assert "83% do padrão de 99%" in n["tit"]


def test_sem_visao_sem_alerta_explica_os_tracos():
    assert _nota({"sem_visao": True})["txt"] == "sem visão por string"
    assert _nota({"sem_visao": True, "inv_padrao": {"status": "ok", "alertas": [], "cronicos": []}})["txt"] \
        == "sem visão por string · no padrão 30d"
    assert _nota({"sem_visao": True, "inv_padrao": {"status": "ok", "alertas": [], "cronicos": ["Inversor 1.3", "Inversor 1.4"]}})["txt"] \
        == "sem visão por string · 2 crônicos no padrão 30d"


def test_com_visao_o_padrao_so_aparece_quando_alerta():
    assert _nota({"sem_visao": False, "inv_padrao": {"status": "ok", "alertas": [], "cronicos": ["Inversor 1.1"]}}) is None
    assert _nota({"usina": "MTS100", "strings_ativas": 502}) is None, "a Athon não muda"


def test_com_visao_as_strings_de_agora_vem_antes_do_padrao_de_ontem():
    """Ouro Branco 4 no print: 68 de 119 strings. A linha diz "Falha de string", como a Athon diria; o padrão de ontem
    só fala quando as strings de agora não têm nada a dizer."""
    ob = {"usina": "Ouro Branco 4 (773)", "qtd_inversores": 4, "strings_ativas": 68, "str_esp": 119, "diferenca": -51,
          "sem_dados": False, "falha_comunicacao": False, "sol_baixo": False, "inv_padrao": {"status": "critico"}}
    assert _status(ob) == "Falha de string"
    assert _status(dict(ob, strings_ativas=119, diferenca=0)) == "Inversor fora do padrão"
    assert _status(dict(ob, sol_baixo=True)) == "Sem sol"


def test_sem_visao_o_padrao_continua_sendo_o_julgamento():
    bt = {"usina": "Barretos 2 (83)", "qtd_inversores": 20, "strings_ativas": 0, "str_esp": 0, "diferenca": 0,
          "sem_dados": False, "falha_comunicacao": False, "sem_visao": True, "inv_padrao": {"status": "atencao"}}
    assert _status(bt) == "Inversor abaixo do padrão"
    assert _status(dict(bt, sol_baixo=True)) == "Inversor abaixo do padrão", "compara o D-1: vale à noite"
    assert _status(dict(bt, inv_padrao={"status": "ok"})) == "Sem visão de strings"
