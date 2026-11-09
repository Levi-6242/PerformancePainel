# -*- coding: utf-8 -*-
"""O comentário do dia no Dashboard Thopen (Levi, 09/11/2026): o relato que o COS escreve para o cliente
(fato_comentario_dia do Nexus) vence a frase seca das OS; as usinas ASSISTIDAS levam o comentário do BD_Thopen, qualquer
que seja a conta do número; e o dia abaixo de 100% sem o detalhe da parada não vira linha ("Indisponibilidade registrada
sem o detalhe da parada." não deve aparecer). Usinas e textos fictícios."""
import datetime as dt
import json
import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "thopen"))

import disp_comentarios  # noqa: E402
import fonte_operacao  # noqa: E402
import operacao_mes  # noqa: E402

D1, D2, D3 = dt.date(2026, 10, 1), dt.date(2026, 10, 2), dt.date(2026, 10, 3)
DE_PARA = [{"usina_id": 7, "chave_externa": "Usina A"}, {"usina_id": 8, "chave_externa": "Usina B"}]
COS = [{"usina_id": "7", "dia": "2026-10-01", "relato_do_dia": "Usina desligada de 01/10 às 08:00 a 01/10 às 10:00.\n"
        "Cabine 2 desligada desde 01/10 às 14:00, em atendimento pelo COS"},
       {"usina_id": "7", "dia": "2026-11-01", "relato_do_dia": "de outro mês"},
       {"usina_id": "8", "dia": "2026-10-01", "relato_do_dia": "de outra usina"}]


def test_o_relato_do_cos_por_usina_e_dia():
    dados = {"de_para": DE_PARA, "comentario_cos_dia": COS}
    assert operacao_mes.cos_por_dia(dados, "Usina A", 2026, 10) == {D1: [
        "Usina desligada de 01/10 às 08:00 a 01/10 às 10:00.",
        "Cabine 2 desligada desde 01/10 às 14:00, em atendimento pelo COS"]}
    assert operacao_mes.cos_por_dia(dados, "Usina C", 2026, 10) == {}       # sem de-para: nada (nunca chutar ID)
    assert operacao_mes.cos_por_dia({}, "Usina A", 2026, 10) == {}


def test_a_aba_do_cos_entra_na_leitura_so_com_as_tres_colunas():
    k, campos = fonte_operacao.ABAS[("nexus_cos_normalizacoes", "fato_comentario_dia")]
    assert k == "comentario_cos_dia" and campos == ("usina_id", "dia", "relato_do_dia")
    assert fonte_operacao.VERSAO_CACHE >= 13       # o cache antigo, sem a aba, não serve


@pytest.fixture
def _card(monkeypatch):
    monkeypatch.setattr(operacao_mes, "_da_usina", lambda *a: lambda x: False)
    monkeypatch.setattr(operacao_mes, "_e_da_usina", lambda *a: lambda x: False)
    monkeypatch.setattr(operacao_mes, "contar", lambda *a: {"por_dia": [], "strings": 0, "trackers": 0})
    monkeypatch.setattr(operacao_mes, "_mes_info", lambda *a: (None, None))
    monkeypatch.setattr(operacao_mes, "disp_por_dia", lambda *a, **k: {D1: 80.0, D2: 90.0, D3: 70.0})
    monkeypatch.setattr(operacao_mes, "os_por_dia", lambda *a, **k: {D1: ["OS 1 - linha seca"], D2: ["OS 2 - linha seca"]})
    return {"trackers_episodios": [], "trackers_dia": [], "de_para": DE_PARA, "comentario_cos_dia": COS,
            "rondas_com_os": []}


def test_o_relato_vence_a_frase_das_os_e_o_dia_sem_relato_fica_com_a_os(_card):
    r = operacao_mes.resposta(_card, "Usina A", 2026, 10, dt.date(2026, 11, 9))
    dia = {p["dia"]: p for p in r["por_dia"]}
    assert dia["01/10"]["os"][0].startswith("Usina desligada de 01/10") and len(dia["01/10"]["os"]) == 2
    assert dia["02/10"]["os"] == ["OS 2 - linha seca"]
    assert dia["03/10"]["os"] == []            # abaixo de 100% sem detalhe: a tela não mostra, vai à lista do COS
    assert set(r) == set(operacao_mes.CHAVES)


def test_com_o_bd_o_comentario_e_o_do_bd(_card):
    bd = ({D1: 50.0}, {D1: ["Desligamento usina - 01/10 08:00 às 10:00"]})
    r = operacao_mes.resposta(_card, "Usina A", 2026, 10, dt.date(2026, 11, 9), bd=bd, disp={D1: 80.0})
    dia = {p["dia"]: p for p in r["por_dia"]}
    assert dia["01/10"]["disp"] == 80.0 and dia["01/10"]["os"] == ["Desligamento usina - 01/10 08:00 às 10:00"]
    assert r["fonte_disp"] == "bd_comentarios"


def test_as_assistidas_sao_as_dez_da_lista():
    assert disp_comentarios.ASSISTIDAS == {"Rondonópolis", "Aruanã", "Lyon", "AP. do Taboado", "Areia Branca",
                                           "Monte Aprazível", "Nova Iguaçu", "Sapopema", "Segredo", "Cambé"}
    assert disp_comentarios.USINAS <= disp_comentarios.ASSISTIDAS


@pytest.fixture
def dash(monkeypatch):
    import dashboard_thopen as d
    monkeypatch.delenv("THOPEN_OPERACAO", raising=False)
    monkeypatch.setattr(d, "_op_dados", lambda: {"x": 1})
    monkeypatch.setattr(d, "_disp_excecao", lambda *a: None)
    monkeypatch.setattr(d, "_canais_da_contestacao", lambda: None)
    chamou = {}

    def resposta(dados, usina, ano, mes, hoje, trips=None, bd=None, disp=None, **k):
        chamou.update(usina=usina, bd=bd, disp=disp, trips=trips)
        return {"disponivel": False}
    monkeypatch.setattr(d.operacao_mes, "resposta", resposta)
    monkeypatch.setattr(d.operacao_mes, "disp_por_dia", lambda *a, **k: {D1: 80.0})
    monkeypatch.setattr(d, "_disp_bd", lambda u, a, m: ({D1: 10.0}, {D1: ["linha do BD"]}))
    monkeypatch.setattr(d, "_trips_da_tela", lambda *a: ({"1": "27"}, False))
    return d, chamou


def test_assistida_pelas_os_leva_o_numero_das_os_e_o_comentario_do_bd(dash):
    d, chamou = dash
    d.app.test_client().get("/api/t/operacao?usina=Aruanã&ano=2026&mes=10")
    assert chamou["bd"][1] == {D1: ["linha do BD"]} and chamou["disp"] == {D1: 80.0} and chamou["trips"] == {}


def test_a_que_nao_e_assistida_segue_o_cos_e_as_os(dash):
    d, chamou = dash
    d.app.test_client().get("/api/t/operacao?usina=Altair&ano=2026&mes=10")
    assert chamou["bd"] is None and chamou["disp"] is None and chamou["trips"] == {"1": "27"}


def test_antes_de_outubro_a_assistida_segue_como_era(dash):
    d, chamou = dash
    d.app.test_client().get("/api/t/operacao?usina=Aruanã&ano=2026&mes=9")
    assert chamou["bd"] is None


NODE = shutil.which("node")
T = open(os.path.join(os.path.dirname(__file__), "..", "thopen", "templates", "dashboard_thopen.html"),
         encoding="utf-8").read()


def test_o_dia_sem_detalhe_nao_entra_na_frase_dos_dias_ocultos():
    # dizer "não tiveram parada registrada" do dia abaixo de 100% sem detalhe seria falso
    if not NODE:
        pytest.skip("node não instalado")
    fn = T[T.index("function _cmtNada("):T.index("function _cmtGrupos(")]
    pd = {"1": {"disp": 80, "os": ["OS 1"]}, "2": {"disp": 70, "os": []}, "3": {"disp": 100, "os": []}}
    js = (fn + "\nprocess.stdout.write(JSON.stringify(_cmtNada(%s, %s, %s, 2026, 10, 'cmt')));"
          % (json.dumps([1]), json.dumps(pd), json.dumps({"fonte_disp": "os"})))
    r = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    txt = json.loads(r.stdout)
    assert "03/10" in txt and "02" not in txt
