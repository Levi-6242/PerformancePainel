# -*- coding: utf-8 -*-
"""A conferência PV Operation (26/11/2026; Levi: o relatório diário da PV Operation "sempre fazendo a comparação com a
disponibilidade das ocorrências da grid... O que não tiver tem que ter alguma justificativa"). Lê o zip do e-mail, liga
cada usina da PV Operation à do dashboard, grava o dia nos livros (o dia repetido troca, não duplica) e confere com a
conta da Grid. Só a conta Grid. Usinas e inversores fictícios, nada de rede."""
import datetime as dt
import io
import os
import sys
import zipfile

import pytest
from openpyxl import Workbook, load_workbook

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "thopen"))
import acessos  # noqa: E402
import dashboard_thopen as dth  # noqa: E402
import pvop_relatorio as P  # noqa: E402

DIA = dt.date(2026, 11, 25)
CAB = ["Nome", "Prognóstico geração", "Geração", "Diferença Geração", "Prognóstico irradiação", "Irradiação",
       "Diferença Irradiação", "Disponibilidade comunicação", "Disponibilidade geração", "Pr"]
DEBUG = """DEBUG: PERÍODOS DOS INVERSORES USINA 901 - Usina Norte 1 (11)   - DIA 25/11/2026
================================================
🔌 USINA901 - Usina Norte 1 (11)  - INVERSOR 5001:
   📉 PROBLEMAS DE GERAÇÃO (PAC = 0): 1 períodos
    1. 2026-11-25 | 10:00 → 12:00 | 120.0 min
🔌 USINA901 - Usina Norte 1 (11)  - INVERSOR 5002:
   📉 PROBLEMAS DE GERAÇÃO (PAC = 0): 1 períodos
    1. 2026-11-25 | 10:00 → 12:00 | 120.0 min
   📡 PROBLEMAS DE COMUNICAÇÃO: 1 períodos
    1. 2026-11-25 | 15:00 → 15:30 | 30.0 min
RESUMO GERAL USINA 901 - Usina Norte 1 (11)  - DIA 25/11/2026
   Tempo total de geração: 540.0 minutos
   Tempo com problemas Potência ativa zerada: 240.0 minutos
   Tempo com problemas comunicação: 30.0 minutos
DEBUG: PERÍODOS DOS INVERSORES USINA 902 - Usina Norte 2 (12)   - DIA 25/11/2026
RESUMO GERAL USINA 902 - Usina Norte 2 (12)  - DIA 25/11/2026
   Tempo total de geração: 540.0 minutos
"""
# a aba Equipamentos do BD_Performance: a usina do dashboard, a parte no supervisório e a potência dos inversores
EQUIP = [{"Usina": "Usina Norte", "Usina supervisório": "Usina Norte 1 (11)", "Equipamento": "Inversor 1", "Potência (kW)": 300},
         {"Usina": "Usina Norte", "Usina supervisório": "Usina Norte 2 (12)", "Equipamento": "Inversor 1", "Potência (kW)": 100},
         {"Usina": "Usina Sul", "Usina supervisório": "Usina Sul (13)", "Equipamento": "Inversor 1", "Potência (kW)": 50}]


def _planilha(linhas):
    wb = Workbook()
    ws = wb.active
    ws.append(CAB)
    for nome, com, ger in linhas:
        ws.append([nome, 1000, 900, -100, 6, 5.5, -0.5, com, ger, 80])
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


PLAN = [("Usina Norte 1 (11) ", 100, 60), ("Usina Norte 2 (12) ", 100, 100), ("Usina Sul (13) ", 0, 0),
        ("Usina Desconhecida (99) ", 100, 100)]


def _zip(dia=DIA, linhas=PLAN, debug=DEBUG):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("relatorio_usinas_%s.xlsx" % dia.isoformat(), _planilha(linhas))
        z.writestr("debug_usinas_diario_%s.txt" % dia.strftime("%d-%m-%Y"), debug.encode("utf-8"))
        z.writestr("leituras_Usina Norte 1 (11) .xlsx", b"")
    return b.getvalue()


def test_le_o_zip_do_email():
    dia, nome, plan, dbg, avisos = P.ler_arquivos({"ENC_Relatorio.zip": _zip()})
    assert dia == DIA and nome == "relatorio_usinas_2026-11-25.xlsx" and avisos == []
    assert [r["nome"] for r in plan] == [n.strip() for n, _c, _g in PLAN]
    assert plan[0]["disp_geracao"] == 60 and plan[0]["disp_comunicacao"] == 100
    n1 = dbg["usina norte 1"]
    assert (n1["pvop_id"], n1["janela"], n1["pac0"], n1["com"]) == ("901", 540.0, 240.0, 30.0)
    assert n1["periodos"] == [("5001", "geração zerada", "2026-11-25T10:00", "2026-11-25T12:00", 120.0),
                              ("5002", "geração zerada", "2026-11-25T10:00", "2026-11-25T12:00", 120.0),
                              ("5002", "comunicação", "2026-11-25T15:00", "2026-11-25T15:30", 30.0)]


def test_sem_a_planilha_recusa_e_sem_o_debug_avisa():
    with pytest.raises(ValueError, match="relatorio_usinas"):
        P.ler_arquivos({"debug_usinas_diario_25-11-2026.txt": DEBUG.encode()})
    _d, _n, plan, dbg, avisos = P.ler_arquivos({"relatorio_usinas_2026-11-25.xlsx": _planilha(PLAN)})
    assert len(plan) == 4 and dbg == {} and "sem o debug" in avisos[0]


def test_o_debug_de_outro_dia_fica_de_fora():
    _d, _n, _p, dbg, avisos = P.ler_arquivos({"relatorio_usinas_2026-11-25.xlsx": _planilha(PLAN),
                                              "debug_usinas_diario_24-11-2026.txt": DEBUG.encode()})
    assert dbg == {} and "outro dia" in avisos[0]


def test_liga_pelo_supervisorio_e_pelos_casos_a_mao():
    su, sk = P.depara(EQUIP)
    assert P.casar("Usina Norte 1 (11) ", su, sk) == ("Usina Norte", 300)
    assert P.casar("Usina Desconhecida (99)", su, sk) == (None, None)
    # o caso à mão da planilha de outubro: o nome da PV Operation não é o do supervisório
    su2, sk2 = P.depara([{"Usina": "Assis", "Usina supervisório": "Assis Chateaubriand  Skid 1 (79)",
                          "Equipamento": "Inversor 1", "Potência (kW)": 75}])
    assert P.casar("Assis 1 (79) ", su2, sk2) == ("Assis", 75)


def test_a_caroa_de_novembro_liga_e_o_kwp_vazio_vai_sem_texto():
    # novembro trouxe "Caroá 1.1 (591)"; sem a parte no supervisório o kWp vai None (o "" dava 500 na API, 05/11)
    assert P.casar("Caroá 1.1 (591) ", {}, {}) == ("Caroá", None)
    disp, _per, sem = P.montar(DIA, "x.xlsx", [{"nome": "Caroá 1.2 (591)", "disp_geracao": 100, "disp_comunicacao": 100,
                                                "geracao": None, "prognostico_geracao": None, "irradiacao": None,
                                                "prognostico_irradiacao": None, "pr": None}], {}, {}, {},
                               dt.datetime(2026, 11, 26))
    assert sem == [] and disp[0]["usina"] == "Caroá" and disp[0]["kwp"] is None


def test_monta_e_pondera_pelo_kwp_das_partes():
    dia, nome, plan, dbg, _a = P.ler_arquivos({"x.zip": _zip()})
    su, sk = P.depara(EQUIP)
    disp, per, sem = P.montar(dia, nome, plan, dbg, su, sk, dt.datetime(2026, 11, 26, 8, 5))
    assert sem == ["Usina Desconhecida (99)"] and len(disp) == 4 and len(per) == 3
    pu = P.por_usina(disp, 2026, 11)
    # 60% em 300 kW e 100% em 100 kW: (60*300 + 100*100) / 400 = 70%
    assert round(pu["Usina Norte"][DIA]["pvop"], 2) == 70.0 and not pu["Usina Norte"][DIA]["sem_dado"]
    # comunicação 0% e geração 0%: a PV Operation não teve dado (não é parada)
    assert pu["Usina Sul"][DIA]["sem_dado"]
    assert P.por_usina(disp, 2026, 10) == {}


def test_resumo_junta_o_mesmo_trecho_dos_inversores():
    dia, nome, plan, dbg, _a = P.ler_arquivos({"x.zip": _zip()})
    _d, per, _s = P.montar(dia, nome, plan, dbg, *P.depara(EQUIP), dt.datetime(2026, 11, 26))
    assert P.resumo_periodos(per) == ["Usina Norte 1 (11): geração zerada de 10:00 a 12:00 (2 inversores)",
                                      "Usina Norte 1 (11): comunicação de 15:00 a 15:30 (1 inversor)"]
    # o mesmo trecho com o fim em minutos diferentes (a Brodowski de 25/11) vira uma linha só
    per = [{"nome": "Skid 1", "tipo": "comunicação", "inicio": "2026-11-25T16:52", "fim": "2026-11-25T17:24", "inversor": i}
           for i in ("1", "2")] + [{"nome": "Skid 1", "tipo": "comunicação", "inicio": "2026-11-25T16:52",
                                    "fim": "2026-11-25T17:25", "inversor": "3"}]
    assert P.resumo_periodos(per) == ["Skid 1: comunicação de 16:52 a 17:25 (3 inversores)"]


class _Livro:
    """O banco falso: {livro: linhas}; acrescentar e regravar mexem nele."""
    def __init__(self, base=None):
        self.livros = {k: list(v) for k, v in (base or {}).items()}

    def ler(self, livro, aba, tok):
        return list(self.livros.get(livro, []))

    def acrescentar(self, livro, nome, aba, cab, novas, tok):
        self.livros.setdefault(livro, []).extend(dict(x) for x in novas)
        return len(self.livros[livro])

    def regravar(self, livro, nome, aba, cab, linhas, antes, tok):
        assert antes == len(self.livros.get(livro, []))
        self.livros[livro] = [dict(x) for x in linhas]
        return len(linhas)


def test_o_dia_repetido_troca_e_nao_duplica():
    lb = _Livro({P.LIVRO_DISP: [{"dia": "2026-11-24", "usina": "Usina Norte"}]})
    P.trocar_dia(lb, "tok", P.LIVRO_DISP, P.NOME_DISP, P.ABA_DISP, P.CAB_DISP, DIA, [{"dia": "2026-11-25", "usina": "A"}])
    P.trocar_dia(lb, "tok", P.LIVRO_DISP, P.NOME_DISP, P.ABA_DISP, P.CAB_DISP, DIA, [{"dia": "2026-11-25", "usina": "B"}])
    assert lb.livros[P.LIVRO_DISP] == [{"dia": "2026-11-24", "usina": "Usina Norte"}, {"dia": "2026-11-25", "usina": "B"}]
    # o livro que ainda não existe nasce na 1ª gravação
    lb2 = _Livro()
    assert P.trocar_dia(lb2, "tok", P.LIVRO_PER, P.NOME_PER, P.ABA_PER, P.CAB_PER, DIA, [{"dia": "2026-11-25"}]) == 1


# ── as rotas ─────────────────────────────────────────────────────────────────────────────────────────────────────
CONTAS = {"c1": {"conta_id": "c1", "nome": "Cliente Teste", "email": "cliente@exemplo.com", "usuario": "cliente",
                 "carteiras": list(acessos.CARTEIRAS), "papel": "cliente"},
          "c3": {"conta_id": "c3", "nome": "Conta Grid", "email": "grid@exemplo.com", "usuario": "grid@exemplo.com",
                 "carteiras": list(acessos.CARTEIRAS), "papel": "grid"}}
GRID = {"Usina Norte": {DIA: 70.3}, "Usina Sul": {DIA: 100.0}, "Usina Leste": {}, "Usina Oeste": {DIA: 100.0}}


@pytest.fixture
def banco(monkeypatch):
    lb = _Livro({"bd_performance": EQUIP})
    for f in ("ler", "acrescentar", "regravar"):
        monkeypatch.setattr(dth.livro_banco, f, getattr(lb, f))
    monkeypatch.setattr(dth.fonte_api, "_token", lambda: "tok")
    monkeypatch.setattr(dth, "_pvop", {"ts": 0.0, "disp": None, "per": None, "jus": None})
    monkeypatch.setattr(dth, "_disp_grid", lambda u, a, m: GRID.get(u, {}))
    monkeypatch.setattr(dth, "_cos_do_mes", lambda u, a, m, dados: (
        {DIA: ["Desligamento de inversor de 10:05 às 12:00"]} if u == "Usina Norte" else {}, {}))
    monkeypatch.setattr(dth, "_op_dados", lambda: {})
    monkeypatch.setattr(dth, "_usinas_do_5080", lambda: ["Usina Norte", "Usina Sul", "Usina Leste", "Usina Oeste"])
    monkeypatch.delenv("THOPEN_LOGIN", raising=False)
    lb.livros["bd_performance"] = EQUIP + [
        {"Usina": "Usina Leste", "Usina supervisório": "Usina Leste (14)", "Equipamento": "Inversor 1", "Potência (kW)": 10},
        {"Usina": "Usina Oeste", "Usina supervisório": "Usina Oeste (15)", "Equipamento": "Inversor 1", "Potência (kW)": 10}]
    return lb


def _sobe(c, conteudo=None):
    return c.post("/api/t/pvop/subir", data={"arquivos": (io.BytesIO(conteudo or _zip(linhas=PLAN + [
        ("Usina Leste (14) ", 100, 100), ("Usina Oeste (15) ", 100, 90)])), "ENC_Relatorio.zip")},
        content_type="multipart/form-data")


def test_subir_grava_e_a_conferencia_cruza_com_a_grid(banco):
    c = dth.app.test_client()
    r = _sobe(c).get_json()
    assert r["ok"] and r["dia"] == "2026-11-25" and r["sem_depara"] == ["Usina Desconhecida (99)"]
    assert len(banco.livros[P.LIVRO_DISP]) == 6 and len(banco.livros[P.LIVRO_PER]) == 3
    _sobe(c)                                                 # o mesmo e-mail de novo: troca, não duplica
    assert len(banco.livros[P.LIVRO_DISP]) == 6
    d = c.get("/api/t/pvop/conferencia?ano=2026&mes=11").get_json()
    sit = {l["usina"]: l["situacao"] for l in d["linhas"]}
    # Norte: 70 x 70,3 bate; Sul: a PV Operation sem dado; Leste: a Grid sem conta; Oeste: 90 x 100 diferente
    assert sit == {"Usina Norte": "bate", "Usina Sul": "sem_dado_pvop", "Usina Leste": "sem_conta_grid",
                   "Usina Oeste": "diferente"}
    assert d["contagem"]["diferente"] == 1 and d["dias_recebidos"] == ["2026-11-25"]
    norte = next(l for l in d["linhas"] if l["usina"] == "Usina Norte")
    assert norte["cos"] == ["Desligamento de inversor de 10:05 às 12:00"]
    assert norte["pvop_viu"][0].startswith("Usina Norte 1 (11): geração 60,0%")
    oeste = next(l for l in d["linhas"] if l["usina"] == "Usina Oeste")
    assert (oeste["pvop"], oeste["grid"], oeste["diferenca"]) == (90.0, 100.0, -10.0)


def test_justificar_tira_da_fila_e_o_vazio_devolve(banco):
    c = dth.app.test_client()
    _sobe(c)
    r = c.post("/api/t/pvop/justificar", json={"usina": "Usina Oeste", "dia": "2026-11-25",
                                               "texto": "Inversor sem comunicação com o datalogger, gerando."})
    assert r.get_json()["ok"]
    d = c.get("/api/t/pvop/conferencia?ano=2026&mes=11").get_json()
    assert {l["usina"]: l["situacao"] for l in d["linhas"]}["Usina Oeste"] == "justificada"
    c.post("/api/t/pvop/justificar", json={"usina": "Usina Oeste", "dia": "2026-11-25", "texto": ""})
    d = c.get("/api/t/pvop/conferencia?ano=2026&mes=11").get_json()
    assert {l["usina"]: l["situacao"] for l in d["linhas"]}["Usina Oeste"] == "diferente"
    assert c.post("/api/t/pvop/justificar", json={"usina": "Outra", "dia": "2026-11-25", "texto": "x"}).status_code == 400
    # quem justificou não vai ao banco: só a usina, o dia, o texto e a hora
    assert set(banco.livros[P.LIVRO_JUS][0]) == set(P.CAB_JUS)


def test_exportar_so_as_diferencas(banco):
    c = dth.app.test_client()
    _sobe(c)
    r = c.get("/api/t/pvop/conferencia.xlsx?ano=2026&mes=11&so=diferentes")
    ws = load_workbook(io.BytesIO(r.data)).active
    assert ws.cell(1, 1).value == "Usina" and ws.cell(1, 9).value == "Justificativa"
    assert [ws.cell(i, 1).value for i in range(2, ws.max_row + 1)] == ["Usina Oeste"]
    todas = load_workbook(io.BytesIO(c.get("/api/t/pvop/conferencia.xlsx?ano=2026&mes=11").data)).active
    assert todas.max_row == 5


def test_subir_recusa_o_que_nao_e_o_relatorio(banco):
    c = dth.app.test_client()
    r = c.post("/api/t/pvop/subir", data={"arquivos": (io.BytesIO(b"nada"), "x.zip")}, content_type="multipart/form-data")
    assert r.status_code == 400
    r = _sobe(c, _zip(dia=dt.date.today() + dt.timedelta(days=2)))
    assert r.status_code == 400 and "ainda não chegou" in r.get_json()["erro"]
    assert P.LIVRO_DISP not in banco.livros


@pytest.fixture
def entra(monkeypatch):
    monkeypatch.setenv("THOPEN_LOGIN", "1")
    monkeypatch.setitem(dth.app.config, "SESSION_COOKIE_SECURE", False)
    monkeypatch.setattr(acessos, "conta", lambda cid: CONTAS.get(cid))
    monkeypatch.setattr(dth, "_usinas_disponiveis", lambda: ["Altair"])

    def _cli(cid):
        c = dth.app.test_client()
        with c.session_transaction() as s:
            s["conta_id"] = cid
        return c
    return _cli


def test_o_cliente_nao_ve_a_aba_nem_as_rotas(entra):
    c = entra("c1")
    assert 'data-page="conferencia"' not in c.get("/").get_data(as_text=True)
    for metodo, rota in (("get", "/api/t/pvop/conferencia?ano=2026&mes=11"),
                         ("get", "/api/t/pvop/conferencia.xlsx?ano=2026&mes=11"),
                         ("post", "/api/t/pvop/subir"), ("post", "/api/t/pvop/justificar")):
        assert getattr(c, metodo)(rota).status_code == 403, rota


def test_a_grid_ve_a_aba(entra):
    assert 'data-page="conferencia"' in entra("c3").get("/").get_data(as_text=True)
