# -*- coding: utf-8 -*-
"""Pouca luz não é usina desligada (Levi, 29/09/2026: "0 strings ativas, usina desligada!").

O print das 08:42: Diamantino 1 e 2 e Guatambu 2, 3 e 4 como "Usina desligada", leitura fresca, todos os inversores
comunicando. Medido na mesma hora:
  - Diamantino 1/2: a estação da usina a 3,5–16 W/m² (céu fechado), os inversores a 0,4–0,9 kW, as strings a 0,1–0,34 A;
  - Guatambu 2/3/4 (sem estação): 2–4,4 kW por inversor, strings a 0,2–0,49 A; um inversor da Guatambu 3 a 0 kW / 0 A.
Nenhuma estava desligada. A régua de string chama de "inativo" o inversor com a mediana abaixo de 0,5 A — o comentário
dela diz "noite/nublado → NÃO é falha" —, e com nenhuma string ativa a linha virava "Usina desligada", em vermelho. A
rampa (corrente real, baixa) só existia para String Box.

E o piso de 2 kW da potência, pensado para sol normal (onde é ≤ 5% da mediana), com céu fechado vira a maior parte do
que todos geram: o inversor a 1,98 kW com os vizinhos a 3,5–4 kW contava como desligado ("2 inv. desligados · 24 strings
fora da conta" na Guatambu 4).

Régua nova: nenhuma string ativa e (a mediana dos inversores produzindo pela régua do projeto, ≥ 2 kW, OU a estação da
usina, fresca, abaixo de 100 W/m²) = pouca luz → "Baixa irradiância", neutro. Sem uma das duas provas continua "Usina
desligada": inversor desligado pode mostrar 0,3 kW com 0,9 A de ruído (test_padrao_athon_todas_as_abas), então potência
baixa sozinha não prova nada.
"""
import json

import pytest

import app

PID, NOME = 987771, "Usina Teste Pouca Luz"


# ── o piso de 2 kW ────────────────────────────────────────────────────────────

def test_com_ceu_fechado_o_inversor_a_1_98_kw_nao_e_desligado():
    """Guatambu 4, 29/09 08:50: 1,98 kW com os vizinhos a 3,5–4 kW. Só o de 0 kW é desligado."""
    assert app._inv_desligados_por_potencia([1.98, 3.5, 3.56, 4.02, 0.0], com_sol=True) == [False, False, False, False, True]


def test_com_sol_normal_o_piso_nao_muda():
    assert app._inv_desligados_por_potencia([100.0, 100.0, 2.5, 100.0], com_sol=True) == [False, False, True, False]
    assert app._inv_desligados_por_potencia([50.0, 48.0, 1.9, 51.0], com_sol=True) == [False, False, True, False]


def test_com_todos_abaixo_de_2_kw_ninguem_e_julgado():
    """Diamantino: 0,36–0,85 kW em todos — a usina não está 'gerando' pela régua, e ninguém vira desligado."""
    assert app._inv_desligados_por_potencia([0.49, 0.57, 0.37, 0.36], com_sol=True) == [False] * 4


# ── a linha da usina ──────────────────────────────────────────────────────────

def _linha(**kw):
    return dict({"usina": NOME, "plant_id": PID, "qtd_inversores": 5, "strings_ativas": 0, "str_esp": 80,
                 "diferenca": -80, "pot_med": 3.84, "inv_off": 0, "inv_desligados": 0, "sem_dados": False,
                 "falha_comunicacao": False, "ultima_leitura": "2026-09-29 08:47:00"}, **kw)


AGORA = app.datetime(2026, 9, 29, 8, 50)


def test_guatambu_produzindo_sem_string_ativa_e_pouca_luz():
    p = app._pouca_luz_de(_linha(), {}, AGORA)
    assert p and p["por"] == "potencia", "3,84 kW por inversor é produzindo pela régua do projeto"


def test_diamantino_abaixo_de_2_kw_com_a_estacao_no_escuro_e_pouca_luz():
    poa = {str(PID): (3.5, "2026-09-29 07:51:00")}          # carimbo cru do registrador (Cuiabá, 1 h atrás)
    p = app._pouca_luz_de(_linha(pot_med=0.555, inv_off=10), poa, AGORA)
    assert p and p["por"] == "estacao" and "3,5 W/m²" in p["texto"]


def test_usina_parada_continua_desligada():
    """Sem potência (ou só o ruído) e sem estação dizendo que falta luz: é a 'Usina desligada' de 23/09."""
    assert app._pouca_luz_de(_linha(pot_med=0.1), {}, AGORA) is None
    assert app._pouca_luz_de(_linha(pot_med=0.3), {str(PID): (620.0, "2026-09-29 08:45:00")}, AGORA) is None, \
        "com sol forte na estação, 0,3 kW é a usina parada (ou o ruído de corrente reversa)"


def test_estacao_velha_nao_prova_nada():
    assert app._pouca_luz_de(_linha(pot_med=0.5), {str(PID): (3.0, "2026-09-29 05:10:00")}, AGORA) is None


def test_quem_ja_tem_outro_estado_nao_muda():
    for kw in ({"strings_ativas": 12}, {"sem_visao": True}, {"falha_comunicacao": True}, {"sem_dados": True},
               {"sol_baixo": True}, {"dado_historico": True}):
        assert app._pouca_luz_de(_linha(**kw), {}, AGORA) is None, kw


def test_a_tabela_marca_a_linha_e_tira_do_card_sem_geracao(monkeypatch, freeze_now):
    freeze_now("2026-09-29 08:50:00")
    monkeypatch.setattr(app, "_poa_atual_por_pid", lambda: {})
    payload = {"rows": [_linha(), _linha(plant_id=PID + 1, usina=NOME + " B", pot_med=0.0)],
               "summary": {"alertas_strings": 2}, "alertas_strings_list": [NOME, NOME + " B"]}
    out = app._com_pouca_luz(payload, app._sem_geracao_api_pv)
    a, b = out["rows"]
    assert a["rampa"] is True and a["pouca_luz"]["por"] == "potencia" and not b.get("rampa")
    assert out["summary"]["alertas_strings"] == 1 and out["alertas_strings_list"] == [NOME + " B"]
    assert payload["rows"][0].get("rampa") is None, "só cópias: o payload em cache é do worker"


# ── a tela ────────────────────────────────────────────────────────────────────

import pathlib
import shutil
import subprocess

MON = (pathlib.Path(app.__file__).resolve().parents[1] / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")


def _status(r):
    node = shutil.which("node")
    if not node:
        pytest.skip("node não instalado")

    def trecho(ini, fim):
        i = MON.index(ini)
        return MON[i:MON.index(fim, i) + len(fim)]
    js = "\n".join([trecho("const pill=(bg,fg)=>", "\n"), trecho("const pillOk=", "\n"), trecho("const pillRed=", "\n"),
                    trecho("const pillAmber=", "\n"), trecho("const semGer=", "\n"),
                    trecho("function _strStatus(", "/* fim _strStatus */"),
                    "process.stdout.write(JSON.stringify(_strStatus(%s,false)[0]));" % json.dumps(r)])
    p = subprocess.run([node, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_a_tela_diz_baixa_irradiancia_e_nao_esconde_o_desligado_de_verdade():
    base = _linha(rampa=True, pouca_luz={"por": "potencia", "texto": "inversores gerando 3,7 kW"})
    assert _status(base) == "Baixa irradiância"
    assert _status(dict(base, inv_desligados=1)) == "Inversor desligado", \
        "Guatambu 3: o 3.1 a 0 kW com os vizinhos gerando está parado de verdade — a pouca luz não pode escondê-lo"
    assert _status(_linha()) == "Usina desligada", "sem a prova de que gera, segue a régua de 23/09"
    i = MON.index("expNote:(r.inv_desligados>0")
    assert "!r.rampa" not in MON[i:MON.index("?", i)], "o aviso '1 inv. desligado' aparece também com pouca luz"
    assert "dif=(semSol||semCom||r.rampa)?null" in MON, "a linha com pouca luz não pinta de vermelho nem pulsa pelo déficit"


# ── a macro (Entrada, NOC) ────────────────────────────────────────────────────

def test_macro_nao_chama_de_parada_a_usina_com_pouca_luz(freeze_now):
    freeze_now("2026-09-29 10:00:00")
    r = _linha(pot_med=0.555, inv_off=10, rampa=True)
    assert app._macro_status(r) == "ok", "sem isto: sem_producao, o alerta de usina parada"
    assert app._macro_causa(r, "ok") == "Baixa irradiância"
    assert app._macro_status(dict(r, inv_desligados=1)) == "critico", "desligado de verdade continua valendo"
    assert app._macro_item("API PV", r)["strings_faltando"] == 0


# ── o drill da API PV ─────────────────────────────────────────────────────────

def _rec(inv_id, pac, correntes, ts="2026-09-29 08:50:00"):
    cj = {"Pac": pac, "Eday": 5.0, "Temp": 25.0}
    cj.update({f"Ipv{i + 1}": c for i, c in enumerate(correntes)})
    return {"idefinversor": inv_id, "tsleitura_new": ts, "conteudojson": json.dumps(cj)}


class _Resp:
    def __init__(self, d):
        self._d, self.status_code = d, 200

    def json(self):
        return self._d


@pytest.fixture
def drill(monkeypatch, freeze_now):
    freeze_now("2026-09-29 08:52:00")
    estado = {"recs": []}

    class _Http:
        def post(self, url, **k):
            return _Resp([] if "custom_query" in url else estado["recs"])

        def get(self, url, **k):
            return _Resp([{"device_id": i, "device_name": f"INVERSOR 0{i}"} for i in range(1, 6)])
    monkeypatch.setattr(app, "_http", lambda: _Http())
    monkeypatch.setattr(app, "get_plants", lambda token, force=False: [{"id": PID, "nome": NOME}])
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "")
    monkeypatch.setattr(app, "_os_atribuidas_map", lambda: {})
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    monkeypatch.setattr(app, "_pv_devs_cache", {})
    monkeypatch.setattr(app, "_pv_comb_cache", {})
    monkeypatch.setattr(app, "_pv_comb_falhou", {})
    monkeypatch.setattr(app, "_plat_combiner_strings", lambda idinv: None)
    monkeypatch.setattr(app, "_poa_atual_por_pid", lambda: {})
    monkeypatch.setitem(app.EQUIP_NAMES, NOME, {f"INVERSOR 0{i}": f"Inversor 1.{i}" for i in range(1, 6)})
    monkeypatch.setitem(app.ESPERADO_INV, NOME, {f"INVERSOR 0{i}": 16 for i in range(1, 6)})
    return estado


def test_drill_da_diamantino_nao_mostra_os_inversores_desligados(drill, monkeypatch):
    """Todos abaixo de 2 kW com a estação no escuro: antes os 10 inversores saíam 'desligado', com todas as strings."""
    monkeypatch.setattr(app, "_poa_atual_por_pid", lambda: {str(PID): (3.5, "2026-09-29 07:51:00")})
    drill["recs"] = [_rec(i, p, [0.22, 0.21, 0.2, 0.19]) for i, p in zip(range(1, 6), (0.49, 0.57, 0.37, 0.36, 0.85))]
    invs = app._pv_plant_inversores(PID, force=True)
    assert not any(i.get("desligado") for i in invs)
    assert all(i.get("rampa") and i.get("strings_ativas") is None for i in invs), "neutro: não conta ativa nem falta"


def test_drill_da_guatambu_so_o_de_0_kw_e_desligado(drill):
    drill["recs"] = ([_rec(i, p, [0.3, 0.29, 0.21, 0.21]) for i, p in zip(range(1, 5), (1.98, 3.5, 3.56, 4.02))]
                     + [_rec(5, 0.0, [0.0, 0.0, 0.0, 0.0])])
    invs = {i["id"]: i for i in app._pv_plant_inversores(PID, force=True)}
    assert [k for k, i in invs.items() if i.get("desligado")] == [5]
    assert all(invs[k].get("rampa") for k in (1, 2, 3, 4))


def test_drill_da_usina_parada_continua_desligado(drill):
    """Usina morta de dia (0 kW, 0 A, sem estação): o drill segue marcando os inversores desligados."""
    drill["recs"] = [_rec(i, 0.0, [0.0, 0.0, 0.0, 0.0]) for i in range(1, 6)]
    assert all(i.get("desligado") for i in app._pv_plant_inversores(PID, force=True))
