# -*- coding: utf-8 -*-
"""A OS de comunicação que foi parada volta para a conta da disponibilidade (Levi, 26/10/2026: "agora sabemos tudo o que
estava sem subtarefa porém foi religamento em outubro, bote na conta e a partir de agora veja as últimas OSs criadas
sobre comunicação que foi confirmado na subtarefa que foi religamento").

Desde 19/10/2026 toda OS de "comunicação" sai da conta. Medido em outubro (162 OS de comunicação): a subtarefa
"Diagnóstico" diz "Desligado" em 48 — a usina estava parada —; as 18 com "Só sem comunicação" e "Religamento local" eram
roteador, smartlogger e internet (o religamento é do equipamento de comunicação). O Diagnóstico decide, não a Ação. As
52 sem subtarefa ficam fora, menos as que o COS confirmou (retorno de 26/10/2026), que também tira da conta OS que eram
só comunicação."""
import json
import os
from datetime import datetime

import pytest

import app
import disponibilidade as dm
from test_disp_fracttal import EQUIP, PER_FIM, PER_INI, AGORA, so_alfa, task

COM = "[THPN-ALF100] - Verificação de comunicação do THPN-ALF100"
JULHO = dict(event_date="2026-07-10T12:00:00+00:00", final_date="2026-07-10T15:00:00+00:00")   # 09:00 a 12:00 local


def sub(diag=None, acao=None, **extra):
    s = [{"description": "Equipamento e sintoma", "value": "x"}]
    if diag is not None:
        s.append({"description": "Diagnóstico", "value": diag})
    if acao is not None:
        s.append({"description": "Ação", "value": acao})
    s += [{"description": k, "value": v} for k, v in extra.items()]
    return s


@pytest.mark.parametrize("subtarefas,esperado", [
    (sub("Desligado", "Religamento local"), "parada"),                          # 16498, AP. do Taboado 2
    (sub("Desligado", "Operador avisado"), "parada"),                           # 15632, São Bento V (concessionária)
    (sub("Só sem comunicação (segue gerando)", "Religamento local"), "comunicacao"),   # 16076, smartlogger travado
    (sub("Só sem comunicação (segue gerando)", "Operador avisado"), "comunicacao"),
    ([{"description": "Foi necessário religamento?", "value": "Sim"}], "parada"),        # o formulário do religamento
    ([{"description": "Foi necessário religamento?", "value": "Não — já normalizado"}], None),
    (sub("", ""), None),                                                        # formulário em branco
    ([], None),                                                                 # sem subtarefa
])
def test_veredito_pela_subtarefa(subtarefas, esperado):
    assert dm.veredito_subtarefas(subtarefas) == esperado


def _roda(wos, vereditos=None):
    return dm.calcular(wos, EQUIP, PER_INI, PER_FIM, agora=AGORA, vereditos=vereditos)


def _os(r, folio):
    return next(o for o in r["oss"] if o["folio"] == folio)


def test_comunicacao_com_parada_confirmada_entra_na_conta():
    r = _roda({"40": [task(description=COM, **JULHO)]}, vereditos={"40": "parada"})
    o = _os(r, 40)
    assert o["excl"] is None and o["kwh"] > 0
    assert any("aberta como comunicação" in f and "subtarefa" in f for f in o["flags"])
    assert so_alfa(r)["disp"] < 100 and so_alfa(r)["n_os"] == 1
    # sem o veredito, como desde 19/10: fora da conta
    r2 = _roda({"40": [task(description=COM, **JULHO)]})
    assert _os(r2, 40)["excl"] == dm.EXCL_COMUNICACAO and so_alfa(r2)["disp"] == 100.0


@pytest.mark.parametrize("v", ["comunicacao", None])
def test_comunicacao_sem_parada_confirmada_segue_fora(v):
    r = _roda({"41": [task(description=COM, **JULHO)]}, vereditos={"41": v})
    assert _os(r, 41)["excl"] == dm.EXCL_COMUNICACAO and so_alfa(r)["disp"] == 100.0


def test_o_veredito_so_vale_para_os_de_comunicacao():
    # um religamento de verdade conta sempre; o veredito "comunicacao" da subtarefa não o tira
    r = _roda({"42": [task(**JULHO)]}, vereditos={"42": "comunicacao"})
    assert _os(r, 42)["excl"] is None


def test_retorno_do_cos_poe_na_conta_a_sem_subtarefa_e_tira_a_que_era_so_comunicacao():
    assert dm.RETORNO_COS[16640][0] == "parada" and dm.RETORNO_COS[14997][0] == "comunicacao"
    r = _roda({"16640": [task(description=COM, **JULHO)],                 # sem subtarefa: o COS confirmou a parada
               "14997": [task(description="Religamento do THPN-ALF100", **JULHO)],   # Religamento que era só comunicação
               "16653": [task(description=COM, **JULHO)]},                # a subtarefa diz Desligado; o COS, só comunicação
              vereditos={"16653": "parada"})
    assert _os(r, 16640)["excl"] is None and any("retorno do COS" in f for f in _os(r, 16640)["flags"])
    assert _os(r, 14997)["excl"] == dm.EXCL_COMUNICACAO and _os(r, 16653)["excl"] == dm.EXCL_COMUNICACAO


def test_comunicacao_fora_e_a_mesma_decisao_da_conta():
    assert dm.comunicacao_fora(40, COM, "", {"40": "parada"}) is False
    assert dm.comunicacao_fora(40, COM, "", {}) is True
    assert dm.comunicacao_fora(14997, "Religamento do THPN-CLN100", "", {}) is True       # o COS
    assert dm.comunicacao_fora(42, "Religamento da Usina", "", {"42": "comunicacao"}) is False


# ── o worker: as subtarefas lidas do Fracttal, guardadas em disco ────────────────────────────────────────────────────
def _wos():
    return {"50": [task(description=COM, id_status_work_order=3, **JULHO)],               # concluída
            "51": [task(description=COM, id_status_work_order=1, event_date="2026-07-10T12:00:00+00:00")],   # aberta
            "52": [task(**JULHO)]}                                                         # religamento: não lê


@pytest.fixture
def frac(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "_FRAC_COM_SUB_FILE", str(tmp_path / "frac_com_subtarefas.json"))
    respostas = {"50": sub("Desligado", "Religamento local"), "51": sub("Só sem comunicação (segue gerando)", "Operador avisado")}
    pedidos = []

    def get(ep, orc, **params):
        assert ep == "work_orders_subtasks/"
        pedidos.append(str(params["folio"]))
        return {"data": respostas[str(params["folio"])]}
    monkeypatch.setattr(app, "_frac_get_paciente", get)
    return pedidos, respostas


def test_worker_le_so_as_de_comunicacao_e_guarda(frac):
    pedidos, _ = frac
    assert app._frac_com_vereditos(_wos()) == {"50": "parada", "51": "comunicacao"}
    assert sorted(pedidos) == ["50", "51"]
    guardado = json.load(open(app._FRAC_COM_SUB_FILE, encoding="utf-8"))
    assert guardado["50"]["veredito"] == "parada" and guardado["50"]["aberta"] is False


def test_worker_rele_so_a_aberta(frac):
    pedidos, respostas = frac
    app._frac_com_vereditos(_wos())
    respostas["51"] = sub("Desligado", "Religamento local")                  # o técnico respondeu depois
    pedidos.clear()
    assert app._frac_com_vereditos(_wos()) == {"50": "parada", "51": "parada"}
    assert pedidos == ["51"]                                                  # a concluída não é pedida de novo


def test_worker_com_o_fracttal_fora_fica_com_o_que_tinha(frac, monkeypatch):
    app._frac_com_vereditos(_wos())

    def falha(*a, **k):
        raise RuntimeError("cota não passou")
    monkeypatch.setattr(app, "_frac_get_paciente", falha)
    assert app._frac_com_vereditos(_wos()) == {"50": "parada", "51": "comunicacao"}


def test_indice_publica_os_vereditos_para_as_telas():
    src = open(os.path.join(os.path.dirname(app.__file__), "app.py"), encoding="utf-8").read()
    corpo = src[src.index("def _frac_disp_recalcular("):src.index("def _frac_disp_dados(")]
    assert "vereditos=vereditos" in corpo and '"comunicacao": vereditos' in corpo
    # a cascata e o relatório decidem como a conta (nada de "comunicação" pelo texto sozinho)
    assert src.count("_disp_mod.eh_falta_de_comunicacao(o.get(\"descricao\"), o.get(\"ativo\"))") == 0
    assert src.count("if _disp_comunicacao_fora(o)") == 2


# ── a correção manual do fim (Levi, 26/10/2026: "15192 infelizmente não temos mais como editar então faça essa
# peculiaridade manual") ─────────────────────────────────────────────────────────────────────────────────────────────
def test_o_fim_corrigido_pelo_cos_vale_no_lugar_da_atividade():
    from datetime import datetime as _dt
    # São Bento do Una, OS 15192: evento 02/10 09:00, a atividade no Fracttal termina em 05/10 22:30; o COS: 10:40 de 02/10
    tarefa = task(description="[THPN-ALF100] - Verificação de comunicação do THPN-ALF100",
                  event_date="2026-10-02T12:00:00+00:00", final_date="2026-10-06T01:30:00+00:00")
    o = dm.consolidar_os("15192", [tarefa], _dt(2026, 10, 26, 12), {"15192": "parada"})
    assert o["excl"] is None and o["ini"] == _dt(2026, 10, 2, 9, 0) and o["fim"] == _dt(2026, 10, 2, 10, 40)
    assert any("fim corrigido pelo COS" in f for f in o["flags"])
    assert any("fim corrigido pelo COS" in a for a in o["alinhar"])           # à vista na lista, com o fim do Fracttal
    assert not any("religamento de" in a for a in o["alinhar"])               # não é mais "religamento de 3 dias"
    assert dm.fim_corrigido(15192, _dt(2026, 10, 5, 22, 30)) == _dt(2026, 10, 2, 10, 40)
    assert dm.fim_corrigido(15193, _dt(2026, 10, 5, 22, 30)) == _dt(2026, 10, 5, 22, 30)


def test_o_drill_usa_o_fim_corrigido():
    src = open(os.path.join(os.path.dirname(app.__file__), "app.py"), encoding="utf-8").read()
    corpo = src[src.index("def _frac_os_filtradas("):src.index("def api_fracttal_os(")]
    assert "_disp_mod.fim_corrigido(" in corpo


def test_metodologia_da_tela_explica_a_comunicacao():
    h = open(os.path.join(os.path.dirname(app.__file__), "templates", "disponibilidade.html"), encoding="utf-8").read()
    met = h[h.index('<div class="metodo">'):h.index('id="mAtual"')]
    assert "comunicação" in met and "Desligado" in met and "COS" in met


# ── a OS no site de duas usinas que o COS diz ser de uma só (Levi, 26/10/2026: OS 16498 "Só na AP2") ───────────────────
def test_escopo_do_cos_conta_so_na_usina_que_parou():
    beta = task(description="[TC-BET100] - Verificação de comunicação do TC-BET100", code="TC-BET100",
                items_log_description="TesteCo - Beta 1 e 2 - RN  Endereço", groups_1_description="TesteCo - Beta 1 e 2 - RN",
                **JULHO)
    sem = _roda({"900": [beta]}, vereditos={"900": "parada"})
    assert {u["usina"] for u in sem["usinas"] if u["disp"] < 100} == {"Beta 1", "Beta 2"}       # o site: as duas
    dm.ESCOPO_COS[900] = (["Beta 2"], "teste: só a Beta 2 parou")
    try:
        r = _roda({"900": [beta]}, vereditos={"900": "parada"})
    finally:
        del dm.ESCOPO_COS[900]
    assert {u["usina"] for u in r["usinas"] if u["disp"] < 100} == {"Beta 2"}
    assert any("escopo pelo COS" in f for f in _os(r, 900)["flags"])


def test_16498_so_na_aparecida_do_taboado_2():
    assert dm.ESCOPO_COS[16498][0] == ["Aparecida do Taboado 2"]
    assert dm.escopo_cos_exclui(16498, "Aparecida do Taboado 1") and not dm.escopo_cos_exclui(16498, "Aparecida do Taboado 2")
    assert not dm.escopo_cos_exclui(16499, "Aparecida do Taboado 1")
    src = open(os.path.join(os.path.dirname(app.__file__), "app.py"), encoding="utf-8").read()
    assert src.count("_disp_mod.escopo_cos_exclui(o.get(\"folio\"), usina)") >= 3      # cascata, relatório e o drill
