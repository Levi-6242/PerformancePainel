# -*- coding: utf-8 -*-
"""O workbook `falhas_performance` com as OITO abas (11/10/2026, Levi: "Dê seguimento a todas essas que não foram
criadas, faça funcionar").

O catálogo do Nexus (nexus/dados/catalogo.py) registrou em 08 e 09/10/2026 quatro abas da plataforma que nunca chegaram
ao banco: `trackers_dia` (fato falha_tracker_dia), `cobertura` (cobertura_falhas), `strings_os` (os_string) e
`disponibilidade_dia` (disponibilidade_dia). Aqui o caminho do worker de ponta a ponta, com o Fracttal e a API do banco
DUBLADOS (nada sai da máquina): a varredura da Disponibilidade vira o índice (com as OS de string), os stores viram o
pacote do mês, o pacote vira o xlsx e o xlsx vai num POST só — as 9 abas na ordem, o cabeçalho na linha 1, o zero
medido como 0 e o que não foi medido como célula vazia (a API é de leitura aberta e o 5080 e o Nexus leem o vazio como
"não medido": um 0 ali diria "nenhuma OS" ou "nenhuma usina monitorada").
"""
import io
import json
from datetime import datetime

import pytest
from openpyxl import load_workbook

import app
import falhas_job
import falhas_publicar as pub

# as OS da disponibilidade entraram em 12/10/2026 (a janela de Disponibilidade da Visão do responsável do Nexus), e a
# parcela de cada OS em cada dia em 14/10/2026 (o comentário do Dashboard Thopen)
ABAS = ["strings_inversor_dia", "strings_episodios", "trackers_episodios", "cobertura", "strings_os", "trackers_dia",
        "disponibilidade_dia", "disponibilidade_os", "disponibilidade_os_dia", "atualizacao"]
NOVAS = ("cobertura", "strings_os", "trackers_dia", "disponibilidade_dia")


class _Resp:
    def __init__(self, status, js):
        self.status_code, self._js = status, js

    def json(self):
        return self._js

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _ApiDoBanco:
    """A Gridco API (db_performace) dublada: o workbook já existe e o sync-xlsx guarda o arquivo que recebeu."""

    def __init__(self):
        self.syncs = []

    def get(self, url, headers=None, timeout=None, **kw):
        assert url.endswith("/api/workbooks")
        return _Resp(200, [{"key": pub.WORKBOOK}])

    def post(self, url, headers=None, params=None, files=None, json=None, timeout=None, **kw):
        assert url.endswith(f"/api/workbooks/{pub.WORKBOOK}/sync-xlsx"), url    # já existe: só o sync
        assert params == {"replace": "true"} and headers["Authorization"].startswith("Bearer ")
        self.syncs.append(files["file"][1])
        return _Resp(200, {"sheets": len(ABAS), "inserted": 0, "updated": 0, "deleted": 0})


@pytest.fixture
def banco(monkeypatch, tmp_path):
    """O worker grava o workbook (como o servidor), com a API do banco dublada e os pacotes numa pasta do teste."""
    api = _ApiDoBanco()
    real = pub.sincronizar
    monkeypatch.setattr(pub, "sincronizar", lambda conteudo, **kw: real(conteudo, sessao=api, **kw))
    monkeypatch.setenv("FALHAS_WORKBOOK", "1")
    monkeypatch.setenv("GRIDCO_SQL_TOKEN", "token-de-teste")
    monkeypatch.setattr(app, "_falhas_wb", {"ts": 0.0, "marca": None})
    monkeypatch.setattr(app, "_CACHE_DIR", str(tmp_path))          # falhas_AAAA-MM.json do teste
    return api


def _xlsx(conteudo):
    """→ (workbook, {aba: [linha como dict pelo cabeçalho publicado]})."""
    wb = load_workbook(io.BytesIO(conteudo))
    return wb, {ws.title: [dict(zip(pub.CABECALHOS[ws.title], [c.value for c in lin]))
                           for lin in ws.iter_rows(min_row=2)] for ws in wb.worksheets}


def _confere_formato(wb):
    assert wb.sheetnames == ABAS
    for aba in ABAS:
        assert [c.value for c in wb[aba][1]] == pub.CABECALHOS[aba]
    for ws in wb.worksheets:                               # o parser do sync rejeita texto vazio
        assert all(c.value != "" for lin in ws.iter_rows(min_row=2) for c in lin)


def _contagens(l):
    return {a["mes"]: tuple(a[k] for k in NOVAS) for a in l["atualizacao"]}


# ══ 1. o POST que o worker manda, de pacotes prontos ═════════════════════════════════════════════════════════════════
def _base(mes, gerado, ini, fim):
    return {"mes": mes, "gerado_em": gerado, "periodo": [ini, fim],
            "regua": {"janela_strings": "06–18h, 2 h seguidas", "fator_tracker": "1 − cos(desvio)"},
            "strings": {"rows": [], "episodios": [], "dias_registrados": [ini], "dias_com_vivas": [ini]},
            "trackers": {"rows": []}}


def _setembro():
    """Setembro como foi montado em 02/10/2026, antes das abas novas: nenhuma das chaves delas."""
    p = _base("2026-09", "2026-10-02 23:52", "2026-09-01", "2026-09-30")
    p["strings"]["episodios"] = [
        {"fonte": "pv", "plant_id": 297378, "cliente": "Thopen", "usina": "Brodowski", "inversor": "Inversor 2.1",
         "string": "Ipv3", "inicio": "2026-09-10 07:00", "fim": "2026-09-12 10:00", "fim_motivo": "voltou",
         "flags": []}]
    p["trackers"]["rows"] = [
        {"fonte": "pv", "plant_id": "297381", "cliente": "Thopen", "usina": "Brodowski", "tracker": "TRK7",
         "inicio": "2026-09-15 08:00", "fim": "2026-09-16 10:00", "flags": []}]
    return p


def _outubro():
    p = _base("2026-10", "2026-10-11 15:00", "2026-10-01", "2026-10-11")
    p["trackers"]["rows"] = [
        {"fonte": "pv", "plant_id": "297381", "cliente": "Thopen", "usina": "Brodowski", "tracker": "TRK1",
         "inicio": "2026-10-10 08:00", "fim": None, "dias_comunicou": 0, "dias_sem_prova": 1, "flags": ["em aberto"]}]
    p["cobertura"] = [{"fonte": "pv", "plant_id": "297381", "usina": "Brodowski", "cliente": "Thopen",
                       "dias_strings": 11, "dias_trackers": 0, "dias_comunicou": 10, "primeiro_dia": "2026-10-01"}]
    p["strings_os"] = [
        {"data_evento": "2026-10-03", "cliente": "Thopen", "usina": "Guaratinguetá V", "plant_id": None,
         "inversor": "Inversor 1.3", "os": "15150", "status": "Em andamento", "strings": None, "qtd": None,
         "origem": "sem_quantidade"},
        # a OS que escreveu "Strings sem corrente: 0": o zero é medido (o técnico achou todas com corrente)
        {"data_evento": "2026-10-06", "cliente": "Thopen", "usina": "Guaratinguetá V", "plant_id": "18750000",
         "inversor": "Inversor 1.4", "os": 15700, "status": "Concluída", "strings": None, "qtd": 0, "origem": "texto"}]
    p["trackers_dia"] = [{"dia": "2026-10-10", "fonte": "pv", "plant_id": "297381", "cliente": "Thopen",
                          "usina": "Brodowski", "trackers": "TRK1", "qtd": 1, "comunicou": "sem prova"}]
    p["disponibilidade"] = {"periodo": ["2026-10-01", "2026-10-03"],
                            "usinas": [{"usina": "Altair", "fracttal": "Thopen - Altair 1 - SP", "cliente": "Thopen",
                                        "pot_kwp": 6898.0}],
                            "diario": {"Altair": {"2026-10-02": {"disp": 75.0, "h_eq": 3.0}}}}
    return p


def _novembro():
    """O dia 1: o mês montado e ainda sem nada (nenhuma OS, nenhum tracker, nenhum dia fechado) = 0, não vazio."""
    p = _base("2026-11", "2026-11-01 07:00", "2026-11-01", "2026-11-01")
    p["cobertura"] = [{"fonte": "sunop", "plant_id": "SMP100", "usina": "SMP100", "cliente": "Athon",
                       "dias_strings": 1, "dias_trackers": 1, "dias_comunicou": 0, "primeiro_dia": "2026-11-01"}]
    p["strings_os"], p["trackers_dia"] = [], []
    p["disponibilidade"] = {"periodo": ["2026-11-01", "2026-11-01"],
                            "usinas": [{"usina": "Altair", "fracttal": "Thopen - Altair 1 - SP", "cliente": "Thopen",
                                        "pot_kwp": 6898.0}], "diario": {}}
    return p


MESES = ["2026-09", "2026-10", "2026-11"]


def _grava(*pacotes):
    for p in pacotes:
        app._falhas_gravar(app._falhas_arquivo(p["mes"]), p)


def test_o_post_leva_as_9_abas_com_o_zero_medido_e_o_vazio_do_que_nao_foi_medido(banco):
    _grava(_setembro(), _outubro(), _novembro())
    app._falhas_publicar_workbook(MESES)
    (conteudo,) = banco.syncs                         # um POST só, com todos os meses: o replace troca a aba inteira
    wb, l = _xlsx(conteudo)
    _confere_formato(wb)
    (s,) = l["strings_episodios"]
    assert (s["mes"], s["plant_id"]) == ("2026-09", "297378")                        # número no pacote, texto na aba
    assert [(t["mes"], t["plant_id"], t["dias_comunicou"], t["dias_sem_prova"]) for t in l["trackers_episodios"]] == [
        ("2026-09", "297381", None, None),          # montado antes: não medido
        ("2026-10", "297381", 0, 1)]                # medido: a usina não comunicou nenhum dia; 1 dia ainda sem prova
    assert [(c["mes"], c["fonte"], c["plant_id"], c["dias_strings"], c["dias_trackers"], c["dias_comunicou"])
            for c in l["cobertura"]] == [("2026-10", "Thopen · API PV", "297381", 11, 0, 10),
                                         ("2026-11", "Athon", "SMP100", 1, 1, 0)]
    assert [(o["mes"], o["os"], o["qtd"], o["strings"], o["origem"]) for o in l["strings_os"]] == [
        ("2026-10", "15150", None, None, "sem_quantidade"),           # sem quantidade: vazio, nunca 0
        ("2026-10", "15700", 0, None, "texto")]                       # o 0 escrito na OS fica 0
    assert [(t["dia"], t["fonte"], t["plant_id"], t["trackers"], t["qtd"], t["comunicou"]) for t in l["trackers_dia"]] \
        == [("2026-10-10", "Thopen · API PV", "297381", "TRK1", 1, "sem prova")]
    assert [(d["mes"], d["dia"], d["usina"], d["usina_fracttal"], d["disp"], d["h_perdidas"])
            for d in l["disponibilidade_dia"]] == [
        ("2026-10", "2026-10-01", "Altair", "Thopen - Altair 1 - SP", 100.0, 0),     # dia sem OS: 100 escrito, 0 h
        ("2026-10", "2026-10-02", "Altair", "Thopen - Altair 1 - SP", 75.0, 3.0)]
    assert _contagens(l) == {"2026-09": (None, None, None, None),      # não montadas: vazio
                             "2026-10": (1, 2, 1, 2),
                             "2026-11": (1, 0, 0, 0)}                  # montadas e vazias: 0


def test_o_gerado_em_novo_nao_sobe_o_workbook_e_a_os_que_fechou_sobe(banco):
    # a API guarda histórico por linha: a volta que só muda o "atualizado em" (a aba `atualizacao`) não regrava nada;
    # mudança numa aba nova (o status da OS) sobe
    _grava(_setembro(), _outubro(), _novembro())
    app._falhas_publicar_workbook(MESES)
    out = _outubro()
    out["gerado_em"] = "2026-10-11 15:30"
    _grava(out)
    app._falhas_wb["ts"] = 0.0                        # passou a hora do TTL
    app._falhas_publicar_workbook(MESES)
    assert len(banco.syncs) == 1
    out["strings_os"][0]["status"] = "Concluída"
    _grava(out)
    app._falhas_wb["ts"] = 0.0
    app._falhas_publicar_workbook(MESES)
    assert len(banco.syncs) == 2
    _, l = _xlsx(banco.syncs[-1])
    assert l["strings_os"][0]["status"] == "Concluída"


# ══ 2. o mês que a volta não remonta segue o índice do Gerencial ══════════════════════════════════════════════════════
def _mes_idx(ini, fim, diario):
    """Um mês do frac_disp_index.json como o disponibilidade.calcular publica (só o que a aba usa)."""
    return {"periodo": {"ini": f"{ini}T00:00:00", "fim": f"{fim}T00:00:00", "dias": 0},
            "usinas": [{"usina": "Alfa", "fracttal": "TesteCo - Alfa 1 - SP", "cliente": "TesteCo", "pot_kwp": 1000.0,
                        "disp": 99.0, "h_perdidas": 3.0, "inversores": []}],
            "diario": diario}


def test_mes_nao_remontado_segue_o_indice_do_gerencial_e_o_que_saiu_dele_fica(monkeypatch, tmp_path):
    # setembro foi montado em 02/10, antes da aba: sem isto ele não teria nenhuma linha na `disponibilidade_dia`,
    # e o mês anterior ficaria congelado no dia 2 enquanto o Gerencial segue recalculando
    monkeypatch.setattr(app, "_CACHE_DIR", str(tmp_path))
    idx = {"meses": {"2026-10": _mes_idx("2026-10-01", "2026-10-11", {}),
                     "2026-09": _mes_idx("2026-09-01", "2026-10-01",
                                         {"Alfa": {"2026-09-05": {"disp": 75.0, "h_eq": 3.0, "kwh": 900}}})}}
    monkeypatch.setattr(app, "_frac_disp_dados", lambda: idx)
    for mes in ("2026-08", "2026-09", "2026-10"):
        app._falhas_gravar(app._falhas_arquivo(mes), {"mes": mes, "strings": {}, "trackers": {}})

    assert app._falhas_disp_fora_da_volta(["2026-10"]) == ["2026-09"]
    set_ = app._falhas_ler(app._falhas_arquivo("2026-09"))
    assert set_["disponibilidade"] == app._falhas_disp_mes("2026-09")
    assert set_["disponibilidade"]["diario"] == {"Alfa": {"2026-09-05": {"disp": 75.0, "h_eq": 3.0}}}
    assert set_["strings"] == {} and set_["trackers"] == {}          # o resto do pacote fica como estava
    assert "disponibilidade" not in app._falhas_ler(app._falhas_arquivo("2026-10"))   # remontado nesta volta
    assert "disponibilidade" not in app._falhas_ler(app._falhas_arquivo("2026-08"))   # fora do índice: não mexe

    assert app._falhas_disp_fora_da_volta(["2026-10"]) == []          # nada mudou: nada regravado
    # a OS de setembro fechada com atraso muda o dia dela no Gerencial: o pacote acompanha
    idx["meses"]["2026-09"]["diario"]["Alfa"]["2026-09-05"] = {"disp": 87.5, "h_eq": 1.5}
    assert app._falhas_disp_fora_da_volta(["2026-10"]) == ["2026-09"]
    # 01/11: setembro saiu do índice e fica com a última que recebeu
    del idx["meses"]["2026-09"]
    assert app._falhas_disp_fora_da_volta(["2026-10"]) == []
    fica = app._falhas_ler(app._falhas_arquivo("2026-09"))["disponibilidade"]
    assert fica["diario"]["Alfa"]["2026-09-05"] == {"disp": 87.5, "h_eq": 1.5}


def test_sem_indice_nenhum_mes_e_tocado(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(app, "_frac_disp_dados", lambda: {})
    app._falhas_gravar(app._falhas_arquivo("2026-09"), {"mes": "2026-09"})
    assert app._falhas_disp_fora_da_volta([]) == []
    assert app._falhas_ler(app._falhas_arquivo("2026-09")) == {"mes": "2026-09"}


# ══ 3. ponta a ponta: a varredura do Fracttal (dublada) → o índice → a volta das falhas → o POST ══════════════════════
AGORA = datetime(2026, 10, 11, 15, 0)
PID = "18748739"          # Inhapi na API PV (cadastro real, como no test_falhas_job)
COD = "INP100"            # o Código Fractal da Inhapi, fixado para não depender do cadastro
EQUIP = [{"cliente": "TesteCo", "usina": "Alfa", "usina_fracttal": "TesteCo - Alfa 1 - SP", "equipamento": "UFV",
          "pot_kwp": 1000.0, "n_inv": 2, "full_om": "Sim"}]
MESES_DISP = [("2026-10", datetime(2026, 10, 1), datetime(2026, 10, 11)),
              ("2026-09", datetime(2026, 9, 1), datetime(2026, 10, 1))]


def _wo(folio, tipo, code, desc, criada, evento=None, fim=None, status=3, note="", task_note="", g1=""):
    """Uma linha do work_orders/ do Fracttal, com mais campos do que a varredura guarda (o técnico, o custo)."""
    return {"wo_folio": folio, "id_work_orders_tasks": folio * 10, "creation_date": criada,
            "tasks_log_task_type_main": tipo, "id_status_work_order": status, "event_date": evento,
            "date_maintenance": None, "final_date": fim, "wo_final_date": None, "code": code,
            "items_log_description": g1, "groups_1_description": g1, "description": desc, "note": note,
            "task_note": task_note, "created_by": "Operador COS", "personnel_description": "Tecnico Exemplo",
            "user_assigned": "Tecnico Exemplo", "costs": 123.0}


def _ordens():
    return [
        # religamento da Alfa em 05/10, 12:00–15:00 de Brasília: 3 h perdidas na régua do Gerencial (disp 75)
        _wo(9001, "Religamento", "TC-ALF100", "Religamento da Usina", "2026-10-05T15:00:00+00:00",
            evento="2026-10-05T15:00:00+00:00", fim="2026-10-05T18:00:00+00:00", g1="TesteCo - Alfa 1 - SP"),
        # a linha do contrato com o OS Creator na observação da OS
        _wo(9002, "Corretiva", "THPN-INP100-INVR3.3", "[Inversor 3.3] - Recomposição de String",
            "2026-10-09T14:00:00+00:00", evento="2026-10-09T13:00:00+00:00", status=1,
            note="Strings sem corrente: 2 (Ipv5, Ipv6)"),
        # sem event_date: o evento é a criação (09:00 de 10/10 em Brasília); as strings citadas na tarefa
        _wo(9003, "Corretiva", "THPN-INP100-INVR3.4", "[Inversor 3.4] - Recomposição de String",
            "2026-10-10T12:00:00+00:00", status=0, task_note="Strings Ipv7 e Ipv8 sem corrente"),
        # sem número nem citação, em outubro: as strings que a régua viu no inversor no dia do evento
        _wo(9004, "Corretiva", "THPN-INP100-INVR3.3", "[Inversor 3.3] - Recomposição de String",
            "2026-10-09T16:00:00+00:00", evento="2026-10-09T15:00:00+00:00", status=1),
        _wo(9005, "Corretiva", "THPN-INP100-INVR3.5", "[Inversor 3.5] - Recomposição de String",
            "2026-10-08T12:00:00+00:00", evento="2026-10-08T12:00:00+00:00", status=4),          # cancelada
    ]


def _fracttal_dublado(monkeypatch, linhas):
    ordem = sorted(linhas, key=lambda w: w["creation_date"], reverse=True)       # DESC por criação, como o real
    pedidos = []

    def _pagina(ep, orcamento, start=0, limit=200, **kw):
        assert ep == "work_orders/"
        pedidos.append(start)
        return {"success": True, "total": len(ordem), "data": ordem[start:start + limit]}
    monkeypatch.setattr(app, "_frac_get_paciente", _pagina)
    return pedidos


def _congela(monkeypatch):
    class _Congelado(datetime):
        @classmethod
        def now(cls, tz=None):
            return AGORA
    monkeypatch.setattr(app, "datetime", _Congelado)
    monkeypatch.setattr(falhas_job, "datetime", _Congelado)


def _disponibilidade_dublada(monkeypatch):
    """O worker da Disponibilidade com a planilha e o banco fora: catálogo mínimo, sem geração (o padrão do
    test_disp_varredura_completa)."""
    real = app._disp_mod.calcular
    monkeypatch.setattr(app, "FRACTTAL_ON", True)
    monkeypatch.setattr(app, "_frac_disp_mem", {"mtime": 0.0, "dados": {}})
    monkeypatch.setattr(app, "_disp_meses_alvo", lambda hoje=None: MESES_DISP)
    monkeypatch.setattr(app, "_disp_equip_linhas", lambda: EQUIP)
    monkeypatch.setattr(app, "_disp_geracao", lambda *a, **k: {})
    monkeypatch.setattr(app._disp_mod, "calcular", lambda *a, **k: real(*a, **{**k, "agora": AGORA}))
    monkeypatch.setattr(app, "_log_arquivo", lambda nome, msg: None)
    monkeypatch.setattr(app, "_DISP_GER_ULTIMA", {})


def _morta(st, inv="Inversor 3.3"):
    """Uma string da régua nova sobre a curva (falhas.avaliar_dia) que já leu corrente antes (não é entrada vazia)."""
    return {"inversor": inv, "string": st, "saiu": "07:00", "voltou": None, "min_morta": 600,
            "trechos": [["07:00", None]], "criterio": {"zerada": 600, "abaixo_das_vizinhas": 0},
            "ini_producao": "06:30", "fim_producao": "17:30", "sempre_zero": False}


def _registro():
    """falhas_strings.json: a régua leu a Inhapi de 01 a 10/10 com produção; em 09/10 a Ipv16 do 3.3 ficou sem
    corrente."""
    out = {}
    for d in range(1, 11):
        dia = f"2026-10-{d:02d}"
        out[dia] = {"pv": {PID: {"usina": "Inhapi", "ts": 0, "vivas": {"Inversor 3.3": 22},
                                 "mortas": [_morta("Ipv16")] if dia == "2026-10-09" else []}}}
    return out


def _trackers():
    """trk_eventos.json: o TRK1 da Inhapi parado em 09 e 10/10 (o registro classificou os dois dias)."""
    return {dia: {PID: {"nome": "Inhapi", "cobertura": 1.0, "classes": {"TRK1": {"status": "parado"}},
                        "eventos": [{"tracker": "TRK1", "parada": "08:00", "retorno": None, "desvio": 35.0}]}}
            for dia in ("2026-10-09", "2026-10-10")}


def _volta_das_falhas_dublada(monkeypatch):
    """A volta do worker com as fontes fora: nenhum pedido à API PV, ao Banco, ao scadaGridco nem ao Fracttal."""
    monkeypatch.setattr(app, "_falhas_importa_historico", lambda: 0)
    monkeypatch.setattr(app, "_falhas_pg_varre", lambda *a, **k: None)
    monkeypatch.setattr(app, "_falhas_sg_varre", lambda *a, **k: None)
    monkeypatch.setattr(app, "_falhas_persistir_mortas", _registro)
    monkeypatch.setattr(app, "_falhas_pv_dev", lambda store: {})
    monkeypatch.setattr(app, "_falhas_geracao", lambda mes, ini, fim: {})
    monkeypatch.setattr(app, "_falhas_os_abertas", lambda forcar=False: {})
    monkeypatch.setattr(app, "_2c_hist_api", lambda dia: {})
    monkeypatch.setattr(app, "_perdas_str", {})
    monkeypatch.setattr(app, "USINA_COD", {**app.USINA_COD, "inhapi": COD})
    with open(app._TRK_EV_PATH, "w", encoding="utf-8") as f:           # o autouse do conftest já o pôs no tmp_path
        json.dump(_trackers(), f)


def test_da_varredura_do_fracttal_ao_post_com_as_9_abas(monkeypatch, banco):
    _congela(monkeypatch)
    _disponibilidade_dublada(monkeypatch)
    _fracttal_dublado(monkeypatch, _ordens())
    _volta_das_falhas_dublada(monkeypatch)
    # setembro já estava publicado (montado em 02/10, antes das abas novas): a volta de 11/10 não o remonta
    _grava(_setembro())

    app._frac_disp_recalcular()                       # o worker da Disponibilidade: índice com as OS de string
    with open(app._FRAC_DISP_FILE, encoding="utf-8") as f:
        idx = json.load(f)
    oss = {o["os"]: o for o in idx["os_string"]}
    assert sorted(oss) == ["9002", "9003", "9004"]                    # a cancelada e o religamento ficam fora
    assert oss["9003"]["evento"] == "2026-10-10"                      # sem event_date: a criação
    assert all(not {"note", "task_note", "description", "tecnico", "personnel_description"} & set(o)
               for o in idx["os_string"])                             # texto livre não vai ao índice

    app._falhas_recalcular()                          # a volta das falhas: monta outubro e sobe o workbook
    out = app._falhas_ler(app._falhas_arquivo("2026-10"))
    assert {"cobertura", "trackers_dia", "strings_os", "disponibilidade"} <= set(out)
    set_ = app._falhas_ler(app._falhas_arquivo("2026-09"))
    assert "disponibilidade" in set_ and not {"cobertura", "trackers_dia", "strings_os"} & set(set_)

    (conteudo,) = banco.syncs
    assert b"Tecnico Exemplo" not in conteudo
    wb, l = _xlsx(conteudo)
    _confere_formato(wb)
    inhapi = out["trackers"]["rows"][0]["usina"]                       # o nome canônico do cadastro
    so = [(o["data_evento"], o["os"], o["inversor"], o["qtd"], o["strings"], o["origem"]) for o in l["strings_os"]]
    assert so == [("2026-10-09", "9002", "Inversor 3.3", 2, "Ipv5, Ipv6", "texto"),
                  ("2026-10-09", "9004", "Inversor 3.3", 1, "Ipv16", "estimado"),
                  ("2026-10-10", "9003", "Inversor 3.4", 2, "Ipv7, Ipv8", "citadas")]
    assert {o["usina"] for o in l["strings_os"]} == {inhapi} and {o["cliente"] for o in l["strings_os"]} == {"Thopen"}
    assert l["strings_os"][1]["plant_id"] == PID                      # a estimativa diz de qual cadastro
    assert [(t["dia"], t["plant_id"], t["trackers"], t["qtd"], t["comunicou"]) for t in l["trackers_dia"]] == [
        ("2026-10-09", PID, "TRK1", 1, "sim"), ("2026-10-10", PID, "TRK1", 1, "sim")]
    (t,) = l["trackers_episodios"][1:]                                 # o 1º é o de setembro
    assert (t["mes"], t["plant_id"], t["dias_comunicou"], t["dias_sem_prova"]) == ("2026-10", PID, 2, 0)
    (c,) = l["cobertura"]
    assert (c["mes"], c["fonte"], c["plant_id"], c["dias_strings"], c["dias_trackers"], c["dias_comunicou"]) == \
        ("2026-10", "Thopen · API PV", PID, 10, 2, 10)
    disp = {(d["mes"], d["dia"]): (d["disp"], d["h_perdidas"]) for d in l["disponibilidade_dia"]}
    assert len([k for k in disp if k[0] == "2026-10"]) == 10          # 01 a 10/10: os dias fechados (até D-1)
    assert len([k for k in disp if k[0] == "2026-09"]) == 30          # setembro inteiro, do índice
    assert disp[("2026-10", "2026-10-05")] == (75.0, 3.0)
    assert disp[("2026-10", "2026-10-04")] == (100.0, 0) and disp[("2026-09", "2026-09-30")] == (100.0, 0)
    assert _contagens(l) == {"2026-09": (None, None, None, 30), "2026-10": (1, 3, 2, 10)}
    for aba in NOVAS:                                                  # a contagem é a das linhas do mês
        for a in l["atualizacao"]:
            if a[aba] is not None:
                assert a[aba] == sum(1 for x in l[aba] if x["mes"] == a["mes"])


def test_erro_no_indice_das_os_de_string_nao_segura_a_disponibilidade(monkeypatch):
    # isolamento: a peça nova que falha não para a que já funcionava — o índice sai sem a chave, e o mês sem a aba
    # `strings_os` (vazio, "não publicado"), nunca com "0 OS"
    _disponibilidade_dublada(monkeypatch)
    _fracttal_dublado(monkeypatch, _ordens())
    logs = []
    monkeypatch.setattr(app, "_log_arquivo", lambda nome, msg: logs.append(msg))

    def _quebra(wos):
        raise ValueError("texto torto numa OS")
    monkeypatch.setattr(app, "_falhas_os_string", _quebra)
    app._frac_disp_recalcular()
    with open(app._FRAC_DISP_FILE, encoding="utf-8") as f:
        idx = json.load(f)
    assert sorted(idx["meses"]) == ["2026-09", "2026-10"] and "os_string" not in idx
    assert app._falhas_os_string_indice() is None
    assert any("OS de string fora do índice" in m for m in logs)


def test_a_varredura_guarda_tudo_o_que_o_indice_das_os_de_string_le():
    # o índice lê a tarefa reduzida pela varredura (_DISP_CAMPOS_TASK): campo lido e não guardado vira sempre vazio,
    # sem erro nenhum (foi o caso da criação até 11/10/2026)
    lidos = {"description", "task_note", "note", "code", "event_date", "creation_date", "id_status_work_order"}
    assert lidos <= set(app._DISP_CAMPOS_TASK)


# ══ 4. revisão adversarial de 11/10/2026 ═══════════════════════════════════════════════════════════════════════════════
def test_strings_os_e_uma_linha_por_os_e_inversor_e_essa_e_a_chave(monkeypatch, banco):
    # o catálogo do Nexus declarava o fato os_string com chave (mes, os) e "1 linha = 1 OS"; a aba sai com uma linha por
    # OS × INVERSOR (a OS 13585 da Altair tem seis tarefas, uma por inversor, e sai em seis linhas com o mesmo nº). A chave
    # que vale é (mes, os, inversor) — e ela não repete. O catálogo do Nexus é corrigido na frente do Nexus
    _congela(monkeypatch)
    _disponibilidade_dublada(monkeypatch)
    _fracttal_dublado(monkeypatch, _ordens() + [
        _wo(9006, "Corretiva", "THPN-INP100-INVR3.3", "Recomposição de String", "2026-10-08T12:00:00+00:00",
            evento="2026-10-08T12:00:00+00:00", status=1, task_note="Strings Ipv1 e Ipv2 sem corrente"),
        _wo(9006, "Corretiva", "THPN-INP100-INVR3.4", "Recomposição de String", "2026-10-08T12:00:00+00:00",
            evento="2026-10-08T12:00:00+00:00", status=1, task_note="String Ipv9 sem corrente")])
    _volta_das_falhas_dublada(monkeypatch)
    _grava(_setembro())                               # já publicado: a volta de 11/10 não o remonta
    app._frac_disp_recalcular()
    app._falhas_recalcular()
    (conteudo,) = banco.syncs
    _, l = _xlsx(conteudo)
    chaves = [(o["mes"], o["os"], o["inversor"]) for o in l["strings_os"]]
    assert len(chaves) == len(set(chaves)) == 5                          # (mes, os, inversor) não repete
    assert sum(1 for c in chaves if c[:2] == ("2026-10", "9006")) == 2    # (mes, os) repete: não é a chave
    assert {(o["inversor"], o["strings"], o["qtd"]) for o in l["strings_os"] if o["os"] == "9006"} == {
        ("Inversor 3.3", "Ipv1, Ipv2", 2), ("Inversor 3.4", "Ipv9", 1)}


def test_em_janeiro_o_dezembro_do_workbook_segue_com_as_os_concluidas_nele(monkeypatch, banco):
    # revisão adversarial de 11/10/2026: o Gerencial refaz o índice com o relógio de agora, e o fim da OS só valia no ano
    # de agora. Em 05/01/2027 o dezembro do índice perdia toda OS concluída em dezembro ("OS concluída sem data final
    # válida"); o _falhas_disp_fora_da_volta leva o índice para o pacote de dezembro (não remontado depois do dia 2) e a
    # disponibilidade_dia saía com 100% em todos os dias. Aqui o worker da Disponibilidade roda com o relógio do
    # servidor congelado em janeiro — sem `agora` na mão, como em produção
    jan = datetime(2027, 1, 5, 10, 0)

    class _Janeiro(datetime):
        @classmethod
        def now(cls, tz=None):
            return jan
    monkeypatch.setattr(app, "datetime", _Janeiro)
    monkeypatch.setattr(app._disp_mod, "datetime", _Janeiro)
    monkeypatch.setattr(app, "FRACTTAL_ON", True)
    monkeypatch.setattr(app, "_frac_disp_mem", {"mtime": 0.0, "dados": {}})
    monkeypatch.setattr(app, "_disp_equip_linhas", lambda: EQUIP)
    monkeypatch.setattr(app, "_disp_geracao", lambda *a, **k: {})
    monkeypatch.setattr(app, "_log_arquivo", lambda nome, msg: None)
    monkeypatch.setattr(app, "_DISP_GER_ULTIMA", {})
    # religamento da Alfa em 15/12, 12:00–15:00 de Brasília: 3 h perdidas (disp 75 no dia)
    _fracttal_dublado(monkeypatch, [
        _wo(9101, "Religamento", "TC-ALF100", "Religamento da Usina", "2026-12-15T15:00:00+00:00",
            evento="2026-12-15T15:00:00+00:00", fim="2026-12-15T18:00:00+00:00", g1="TesteCo - Alfa 1 - SP")])
    _grava(_base("2026-12", "2027-01-02 23:50", "2026-12-01", "2026-12-31"))     # montado pela última vez em 02/01

    app._frac_disp_recalcular()
    assert sorted(app._frac_disp_dados()["meses"]) == ["2026-12", "2027-01"]
    assert app._falhas_disp_fora_da_volta(["2027-01"]) == ["2026-12"]        # a volta de 05/01 só remonta janeiro
    app._falhas_publicar_workbook(["2026-12"])
    (conteudo,) = banco.syncs
    _, l = _xlsx(conteudo)
    dez = {d["dia"]: (d["disp"], d["h_perdidas"]) for d in l["disponibilidade_dia"]}
    assert len(dez) == 31
    assert dez["2026-12-15"] == (75.0, 3.0)
    assert dez["2026-12-14"] == (100.0, 0) and dez["2026-12-16"] == (100.0, 0)
