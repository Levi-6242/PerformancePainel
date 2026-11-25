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
    assert dia["03/10"]["os"] == []            # abaixo de 100% sem detalhe: a tela mostra o dia com o comentário vazio
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


# ── de 11/2026 em diante a assistida e a Cambé, Sapopema e Segredo seguem o COS (25/11/2026) ──────────────────────────
NOV = dt.date(2026, 11, 4)


def test_a_lista_que_segue_o_cos_vale_de_novembro_em_diante():
    dc = disp_comentarios
    assert dc.segue_o_cos("Areia Branca", 2026, 11) and dc.segue_o_cos("Cambé", 2027, 1)
    assert not dc.segue_o_cos("Areia Branca", 2026, 10)          # outubro fica como estava
    # sem a disponibilidade_dia da plataforma: seguem no BD
    assert not dc.segue_o_cos("Rondonópolis", 2026, 11) and not dc.segue_o_cos("AP. do Taboado", 2026, 11)
    # um nome com a grafia errada nunca casaria com a usina e ficaria no BD calado: todos têm de ser da lista de sempre
    assert dc.SEGUEM_O_COS <= dc.ASSISTIDAS


@pytest.fixture
def _sem_fechamento(dash, monkeypatch):
    d, chamou = dash
    monkeypatch.setattr(d, "_disp_fechamento", lambda *a: None)
    monkeypatch.setattr(d.operacao_mes, "disp_por_dia", lambda *a, **k: {NOV: 55.0})
    return d, chamou


@pytest.mark.parametrize("usina", ["Areia Branca", "Cambé"])
def test_em_novembro_a_que_seguia_o_bd_segue_o_cos_no_numero_e_no_comentario(_sem_fechamento, usina):
    d, chamou = _sem_fechamento
    assert not d._pelo_bd(usina, 2026, 11) and d._pelo_bd(usina, 2026, 10)
    assert d._disp_dias(usina, 2026, 11) == {NOV: 55.0}          # o número da plataforma, não o do BD (10%)
    d.app.test_client().get("/api/t/operacao?usina=%s&ano=2026&mes=11" % usina)
    assert chamou["bd"] is None and chamou["trips"] == {"1": "27"}


def test_em_novembro_a_assistida_pelas_os_leva_o_relato_do_cos(_sem_fechamento):
    d, chamou = _sem_fechamento
    d.app.test_client().get("/api/t/operacao?usina=Aruanã&ano=2026&mes=11")
    assert chamou["bd"] is None and chamou["disp"] is None and chamou["trips"] == {"1": "27"}


def test_em_novembro_rondonopolis_segue_no_bd(_sem_fechamento):
    d, chamou = _sem_fechamento
    assert d._disp_dias("Rondonópolis", 2026, 11) == {D1: 10.0}
    d.app.test_client().get("/api/t/operacao?usina=Rondonópolis&ano=2026&mes=11")
    assert chamou["bd"][1] == {D1: ["linha do BD"]} and chamou["trips"] == {}


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


# ── a parada fora do período solar (16/11/2026) ────────────────────────────────────────────────────────────────────
def _oc(inicio, fim, tipo="DESLIGAMENTO_USINA", usina_id="7", **kw):
    o = {"os": "18809", "usina_id": usina_id, "tipo_falha": tipo, "equipamentos_codigos": "", "inicio": inicio,
         "normalizado_em": fim, "normalizada": "1", "hora_real": "1"}
    o.update(kw)
    return o


def test_a_parada_so_fora_do_periodo_solar_vira_linha_no_dia():
    """O caso que criou a regra: o Colorado 1 em 07/11, desligado de 01:30 a 06:46 (OS 18809), a 100% e sem nada."""
    dados = {"de_para": DE_PARA, "ocorrencia_cos": [
        # começa depois das 17:30 e vai até o meio do dia seguinte: só o 1º dia é fora do sol (vem antes no livro, mas
        # a linha sai na ordem da hora)
        _oc("2026-11-07T19:15:00-03:00", "2026-11-09T16:00:00-03:00", os="18858", tipo="ATUACAO_PROTECAO",
            equipamentos_codigos="CLR100-RELE1"),
        _oc("2026-11-07T01:30:00-03:00", "2026-11-07T06:46:00-03:00"),
        _oc("2026-11-08T08:00:00-03:00", "2026-11-08T09:00:00-03:00", os="1"),       # dentro do sol: não
        _oc("2026-11-10T02:00:00-03:00", "2026-11-10T04:00:00-03:00", tipo="FALHA_COMUNICACAO"),   # não é parada
        _oc("2026-11-11T02:00:00-03:00", "2026-11-11T04:00:00-03:00", normalizada="0"),           # desfeita
        _oc("2026-11-12T02:00:00-03:00", "2026-11-12T04:00:00-03:00", usina_id="8"),              # outra usina
    ]}
    out = operacao_mes.fora_do_sol_por_dia(dados, "Usina A", 2026, 11)
    assert sorted(out) == [dt.date(2026, 11, 7)]
    assert out[dt.date(2026, 11, 7)] == [
        "Desligamento de usina de 01:30 a 06:46 (OS 18809): fora do período solar (07h30 às 17h30), não afeta a "
        "disponibilidade.",
        "Atuação de proteção (CLR100-RELE1) de 07/11 às 19:15 a 09/11 às 16:00 (OS 18858): fora do período solar "
        "(07h30 às 17h30), não afeta a disponibilidade."]


def test_o_dia_a_100_leva_a_parada_fora_do_sol_e_o_dia_com_perda_nao(_card, monkeypatch):
    monkeypatch.setattr(operacao_mes, "disp_por_dia", lambda *a, **k: {D1: 100.0, D2: 90.0})
    _card["ocorrencia_cos"] = [_oc("2026-10-01T01:00:00-03:00", "2026-10-01T05:00:00-03:00"),
                               _oc("2026-10-02T01:00:00-03:00", "2026-10-02T05:00:00-03:00")]
    r = operacao_mes.resposta(_card, "Usina A", 2026, 10, dt.date(2026, 11, 9))
    dia = {p["dia"]: p for p in r["por_dia"]}
    assert dia["01/10"]["fora_sol"][0].startswith("Desligamento de usina de 01:00 a 05:00")
    assert "fora_sol" not in dia["02/10"]
    # a usina pelo BD (assistida) não leva: o comentário dela é o da equipe
    r = operacao_mes.resposta(_card, "Usina A", 2026, 10, dt.date(2026, 11, 9), bd=({D1: 100.0}, {}))
    assert all("fora_sol" not in p for p in r["por_dia"])


def test_a_aba_das_ocorrencias_entra_so_com_as_colunas_sem_nome():
    k, campos = fonte_operacao.ABAS[("nexus_cos_normalizacoes", "fato_normalizacao")]
    assert k == "ocorrencia_cos" and "os_aberta_por" not in campos and "tecnico" not in campos
    assert fonte_operacao.VERSAO_CACHE >= 14


# ── a janela: Disponibilidade Thopen | Comentário | Disponibilidade Grid (16/11/2026) ─────────────────────────────────
def test_no_mes_da_planilha_cada_numero_tem_o_seu_comentario(_card, monkeypatch):
    monkeypatch.setattr(operacao_mes, "disp_por_dia", lambda *a, **k: {D1: 90.0, D2: 90.0, D3: 70.0})
    r = operacao_mes.resposta(_card, "Usina A", 2026, 10, dt.date(2026, 11, 9),
                              disp={D1: 100.0, D2: 80.0, D3: 100.0}, grid={D1: 90.0, D2: 90.0, D3: 100.0},
                              com_bd={D2: ["Inversor 3: de 08:00 a 10:00"]})
    dia = {p["dia"]: p for p in r["por_dia"]}
    assert r["planilha_thopen"] is True
    assert [(dia[k]["disp"], dia[k]["disp_grid"]) for k in ("01/10", "02/10", "03/10")] == [(100.0, 90.0), (80.0, 90.0),
                                                                                           (100.0, 100.0)]
    # o da Thopen é o do BD_Thopen; o da Grid, o relato do COS (ou as OS) no dia com perda na conta da Grid
    assert dia["02/10"]["com_thopen"] == ["Inversor 3: de 08:00 a 10:00"] and dia["01/10"]["com_thopen"] == []
    assert dia["01/10"]["com_grid"][0].startswith("Usina desligada de 01/10")
    assert dia["02/10"]["com_grid"] == ["OS 2 - linha seca"] and dia["03/10"]["com_grid"] == []
    # a tabela de Comentários (o número do cliente) não muda: 01/10 está a 100% na planilha
    assert dia["01/10"]["os"] == []


def test_a_usina_que_a_grid_conta_pelo_bd_leva_o_comentario_do_bd_na_grid(_card):
    bd = ({D1: 50.0}, {D1: ["Desligamento usina - 01/10 08:00 às 13:00"]})
    r = operacao_mes.resposta(_card, "Usina A", 2026, 10, dt.date(2026, 11, 9), bd=bd, disp={D1: 80.0},
                              grid={D1: 50.0}, com_bd={D1: ["Desligamento usina - 01/10 08:00 às 13:00"]},
                              grid_bd=True)
    p = {p["dia"]: p for p in r["por_dia"]}["01/10"]
    assert p["com_grid"] == ["Desligamento usina - 01/10 08:00 às 13:00"] == p["com_thopen"]


def test_sem_a_planilha_a_coluna_grid_e_o_proprio_numero(_card):
    r = operacao_mes.resposta(_card, "Usina A", 2026, 10, dt.date(2026, 11, 9))
    assert r["planilha_thopen"] is False
    assert all(p["disp_grid"] == p["disp"] for p in r["por_dia"])


# ── outubro: na assistida, o relato do COS vence o comentário do BD_Thopen no dia em que existe (25/11/2026) ──────────
def test_a_regra_do_cos_no_comentario_vale_nas_assistidas_de_outubro_em_diante():
    dc = disp_comentarios
    assert dc.cos_no_comentario("Segredo", 2026, 10) and dc.cos_no_comentario("Cambé", 2026, 10)
    assert dc.cos_no_comentario("Sapopema", 2026, 10) and dc.cos_no_comentario("Lyon", 2026, 10)
    # de novembro em diante a que segue o COS inteiro já não passa pelo BD; Rondonópolis e AP. do Taboado ainda passam
    assert not dc.cos_no_comentario("Cambé", 2026, 11) and dc.cos_no_comentario("Rondonópolis", 2026, 11)
    assert not dc.cos_no_comentario("Segredo", 2026, 9)          # antes de outubro, como era
    assert not dc.cos_no_comentario("Altair", 2026, 10)          # fora das assistidas: nunca passou pelo BD


def test_com_o_bd_e_o_cos_no_bd_o_relato_vence_no_dia_e_o_bd_fica_no_dia_sem_relato(_card):
    bd = ({D1: 50.0, D2: 60.0}, {D1: ["linha do BD em 01/10"], D2: ["linha do BD em 02/10"]})
    r = operacao_mes.resposta(_card, "Usina A", 2026, 10, dt.date(2026, 11, 9), bd=bd, disp={D1: 80.0, D2: 90.0},
                              cos_no_bd=True)
    dia = {p["dia"]: p for p in r["por_dia"]}
    assert dia["01/10"]["os"][0].startswith("Usina desligada de 01/10") and len(dia["01/10"]["os"]) == 2
    assert dia["02/10"]["os"] == ["linha do BD em 02/10"]
    # o número não muda: segue o da exceção / do fechamento
    assert (dia["01/10"]["disp"], dia["02/10"]["disp"]) == (80.0, 90.0) and r["fonte_disp"] == "bd_comentarios"
    # sem a marca, como era: o BD no dia todo
    r = operacao_mes.resposta(_card, "Usina A", 2026, 10, dt.date(2026, 11, 9), bd=bd, disp={D1: 80.0, D2: 90.0})
    assert {p["dia"]: p for p in r["por_dia"]}["01/10"]["os"] == ["linha do BD em 01/10"]


@pytest.mark.parametrize("usina,mes,esperado", [("Segredo", 10, True), ("Cambé", 10, True), ("Aruanã", 10, True),
                                                ("Altair", 10, False)])
def test_a_rota_marca_o_cos_no_bd_na_assistida_de_outubro(dash, monkeypatch, usina, mes, esperado):
    d, _ = dash
    pegou = {}
    monkeypatch.setattr(d.operacao_mes, "resposta",
                        lambda *a, **k: pegou.update(k) or {"disponivel": False})
    d.app.test_client().get(f"/api/t/operacao?usina={usina}&ano=2026&mes={mes}")
    assert pegou.get("cos_no_bd") is esperado
