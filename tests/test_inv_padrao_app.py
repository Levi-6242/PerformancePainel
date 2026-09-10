# -*- coding: utf-8 -*-
"""Integração da régua de padrão por inversor (inv_padrao) no app: macro, nomes do cadastro e sino.

O núcleo puro está em tests/test_inv_padrao.py. Aqui é o encaixe: a usina String Box sem visão (Ceilândia 1,
Céu Azul, Ouro Branco) e Barretos saem do 'ok' eterno quando um inversor cai do padrão; o id da API PV vira o nome
do cadastro ('INVERSOR03' → 'Inversor 1.3'); e o sino recebe UM evento por inversor e dia, não um por ciclo."""
import json

import app
import inv_padrao as ip


def _row(**extra):
    r = {"usina": "Céu Azul II (103)", "plant_id": 60009, "sem_visao": True, "stringbox": True, "strings_ativas": 0,
         "str_esp": 0, "qtd_inversores": 8, "inv_off": 0, "pot_med": 100.0, "ultima_leitura": "2026-09-10 13:07:00"}
    r.update(extra)
    return r


_ALERTA = {"status": "critico", "dia": "2026-09-09", "n_dias_base": 29,
           "alertas": [{"inv": "Inversor 1.1", "status": "critico", "razao": 68.0, "base": 91.0, "delta": -23.0}],
           "cronicos": [], "previa": None}


def test_macro_status_padrao_de_inversor_tira_a_string_box_do_ok_eterno():
    """Sem a régua, `sem_visao` devolvia 'ok' sempre. Com um inversor 23 pp abaixo do padrão ontem, é crítico."""
    r = _row(inv_padrao=_ALERTA)
    assert app._macro_status(r) == "critico"
    causa = app._macro_causa(r, "critico")
    assert "Inversor 1.1" in causa and "68" in causa and "23" in causa
    assert app._macro_status(_row()) == "ok"                       # sem a régua, o comportamento antigo


def test_macro_sem_comunicacao_vence_o_padrao_de_inversor():
    r = _row(falha_comunicacao=True, inv_padrao=_ALERTA)
    assert app._macro_status(r) == "sem_comm"


def test_macro_item_leva_o_padrao_e_nao_inventa_string_faltando():
    item = app._macro_item("API PV", _row(inv_padrao=_ALERTA))
    assert item["status"] == "critico" and item["strings_faltando"] == 0
    assert item["inv_padrao"]["alertas"][0]["inv"] == "Inversor 1.1"
    assert item["sev"] == 1                                          # mesmo degrau de 'falha de string' no ranking


def test_resumo_traduz_o_id_da_api_no_nome_do_cadastro(monkeypatch):
    """A API PV dá 'INVERSOR03' (id 364576); o cadastro chama de 'Inversor 1.3' — é esse que a tela conhece."""
    E = {f"2026-08-{d:02d}": {"364574": 500.0, "364575": 500.0, "364576": 500.0, "364577": 500.0} for d in range(1, 21)}
    E["2026-08-21"] = {"364574": 500.0, "364575": 500.0, "364576": 340.0, "364577": 500.0}
    aval = ip.avaliar_dia(E, "2026-08-21")
    st = ip.Store(None)
    st.gravar_devs(297410, {"364574": "INVERSOR01", "364575": "INVERSOR02", "364576": "INVERSOR03", "364577": "INVERSOR04"},
                   "Barretos 1 (83)")
    monkeypatch.setattr(app, "_inv_padrao_store", st)
    monkeypatch.setitem(app._inv_padrao_cache, "data", {"297410": {"nome": "Barretos 1 (83)", "d1": aval, "previa": None}})
    assert app.EQUIP_NAMES["Barretos 1 (83)"]["INVERSOR03"] == "Inversor 1.3", "o cadastro real mudou; ajuste o caso"
    res = app._inv_padrao_resumo(297410)
    assert res["status"] == "critico" and res["dia"] == "2026-08-21"
    assert res["alertas"] == [{"inv": "Inversor 1.3", "status": "critico", "razao": 68.0, "base": 100.0, "delta": -32.0}]
    assert app._inv_padrao_resumo(999999) is None


def test_sino_recebe_um_evento_por_inversor_e_dia(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "STATE_PATH", str(tmp_path / "ufv_state.json"))
    assert app._inv_padrao_notificar(60009, "Céu Azul II", _ALERTA) == 1
    assert app._inv_padrao_notificar(60009, "Céu Azul II", _ALERTA) == 0    # mesmo inversor, mesmo dia: já avisado
    st = json.load(open(tmp_path / "ufv_state.json", encoding="utf-8"))
    ev = st["notif"]["eventos"]
    assert len(ev) == 1 and ev[0]["tipo"] == "inv_padrao" and ev[0]["inversor"] == "Inversor 1.1"
    assert ev[0]["fonte"] == "pv" and ev[0]["plant_id"] == 60009 and ev[0]["usina"] == "Céu Azul II"
    assert ev[0]["razao"] == 68.0 and ev[0]["base"] == 91.0 and ev[0]["delta"] == -23.0 and ev[0]["dia"] == "2026-09-09"


def test_usina_fatiada_mantem_a_causa_do_padrao_ao_somar_as_partes():
    """Barretos e uma usina fisica em duas plantas (Barretos 1 e 2). O add() elege a pior fatia (Barretos 2, atencao)
    e _somar_partes_da_usina RECALCULA a causa com um dicionario reduzido — sem o inv_padrao a causa voltava a
    'Normal' com o status em atencao (visto ao vivo em 10/09, primeiro ciclo no ar)."""
    r1 = _row(usina="Barretos 1 (83)", plant_id=297410, sem_visao=False, stringbox=True, strings_ativas=120, str_esp=None,
              qtd_inversores=20, inv_padrao={"status": "ok", "dia": "2026-09-09", "alertas": [], "cronicos": ["Inversor 1.3"]})
    r2 = _row(usina="Barretos 2 (83)", plant_id=297415, sem_visao=False, stringbox=True, strings_ativas=24, str_esp=None,
              qtd_inversores=20, inv_padrao={"status": "atencao", "dia": "2026-09-09", "cronicos": [],
                                             "alertas": [{"inv": "Inversor 2.7", "status": "atencao", "razao": 88.0, "base": 98.8, "delta": -10.8}]})
    i1, i2 = app._macro_item("API PV", r1), app._macro_item("API PV", r2)
    assert i2["status"] == "atencao" and "Inversor 2.7" in i2["causa"]
    app._somar_partes_da_usina(i2, [i1, i2])
    assert i2["status"] == "atencao" and i2["n_partes"] == 2 and i2["qtd_inversores"] == 40
    assert "Inversor 2.7" in i2["causa"], i2["causa"]
