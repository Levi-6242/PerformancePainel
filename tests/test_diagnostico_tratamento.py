# -*- coding: utf-8 -*-
"""O que já tem tratamento no Diagnóstico da usina (fase 1, 27/10/2026): desligamentos/religamentos e chamados.

Levi, 27/10/2026: cada problema do diagnóstico sai com causa provável + prova + ação, e o que já tem tratamento vai para
"Explicado / em tratamento", deixando na frente só o que ninguém está olhando. Regra SEM parâmetro: OS de
desligamento/religamento no período do problema (o índice da Disponibilidade) ou chamado de garantia aberto (o livro
`nexus_chamados · fato_chamado`, o Acompanhamento de chamados do Nexus) para o ativo = explicado.

Os casos são os de Barretos 1 em 27/10/2026, copiados do índice da Disponibilidade e do livro de chamados daquele dia:
- OS 17016, Corretiva Emergencial no BRS100-DINV1.14, aberta desde 22/10 07:00 (o inversor 1.14 está fora agora);
- OS 15510, Religamento da BRS100-CABN1 (a cabine 1 inteira), de 05/10 15:50 a 13/10 15:06 (fechada);
- OS 16520, Religamento Remoto da usina inteira (THPN-BRS100), 16/10 01:18 a 01:20 (de madrugada: 0 h de sol);
- chamado 17159 (OS de acompanhamento) do BRS100-INVR1.1 com a Sungrow, aberto desde 22/06/2026 → 127 dias em 27/10;
- chamado 17292 do BRS100-ETKR1 (tracker): não liga a problema nesta fase;
- chamado 17704 do THPN-BRS100-PGINVR1 (inversor em almoxarifado): também não.
Nenhum teste fala com a rede: o índice, o livro e o Fracttal são dublados.
"""
import json
from datetime import datetime

import pytest

import app
import diag_tratamento as dt
from test_diagnostico_fonte_fora import PID, _inv, _pagina, _rotas

AGORA = datetime(2026, 10, 27, 15, 0)
SITE = "Thopen - Barretos 1 - SP"

OSS = [
    {"folio": 17016, "tipos": ["Corretiva Emergencial"], "origem": "equipamento", "code": "BRS100-DINV1.14",
     "ini": "2026-10-22T07:00:00", "fim": None, "aberta": True, "excl": None, "h_solar": 59.0,
     "escopo": [{"usina": "Barretos", "nivel": "inversor", "rotulo": "Inversor 1.14", "kwp": 153.5}]},
    {"folio": 15510, "tipos": ["Religamento"], "origem": "queda", "code": "BRS100-CABN1",
     "ini": "2026-10-05T15:50:00", "fim": "2026-10-13T15:06:03", "aberta": False, "excl": None, "h_solar": 95.27,
     "escopo": [{"usina": "Barretos", "nivel": "cabine", "rotulo": "Cabine 1", "kwp": 3069.5}]},
    {"folio": 16520, "tipos": ["Religamento Remoto"], "origem": "queda", "code": "THPN-BRS100",
     "ini": "2026-10-16T01:18:00", "fim": "2026-10-16T01:20:00", "aberta": False, "excl": None, "h_solar": 0,
     "escopo": [{"usina": "Barretos", "nivel": "usina", "rotulo": "Usina inteira", "kwp": 6139.0}]},
    # a excluída da conta (cancelada) não explica nada, e a de outra usina também não
    {"folio": 17620, "tipos": ["Religamento"], "origem": "queda", "code": "BRS100-INVR2.3", "ini": None, "fim": None,
     "aberta": False, "excl": "OS cancelada", "escopo": []},
    # a excluída que ainda traz data e escopo (o índice guarda a OS com o motivo, ex.: "falta de comunicação: não é
    # parada"): a Disponibilidade não a conta, o Diagnóstico também não
    {"folio": 17621, "tipos": ["Religamento"], "origem": "queda", "code": "BRS100-INVR2.4",
     "ini": "2026-10-26T08:00:00", "fim": None, "aberta": True, "excl": "falta de comunicação: não é parada",
     "escopo": [{"usina": "Barretos", "nivel": "inversor", "rotulo": "Inversor 2.4", "kwp": 153.5}]},
    {"folio": 17619, "tipos": ["Religamento"], "origem": "queda", "code": "ELF100-INVR3.4",
     "ini": "2026-10-10T07:08:00", "fim": "2026-10-27T10:31:57", "aberta": False, "excl": None, "h_solar": 80,
     "escopo": [{"usina": "Elias Fausto", "nivel": "inversor", "rotulo": "Inversor 2.3", "kwp": 143.3}]},
]
INVERSORES = [{"inversor": f"Inversor {c}.{n}", "cabine": c} for c in (1, 2) for n in range(1, 21)]
MES = {"fonte": "Fracttal", "periodo": {"ini": "2026-10-01T00:00:00", "fim": "2026-10-27T00:00:00"},
       "usinas": [{"usina": "Barretos", "fracttal": SITE, "inversores": INVERSORES},
                  {"usina": "Elias Fausto", "fracttal": "RenoGrid - Elias Fausto 1 - SP", "inversores": []}],
       "oss": OSS}


def _ch(os_, codigo, abertura, situacao="aberto", fab="Sungrow", comp="Inversor", site=SITE):
    return {"os": os_, "data_id_abertura": abertura, "data_id_fim": None, "usina_id": 26,
            "usina_ligada_por": "de-para do Fracttal", "site_fracttal": site, "equipamento_id": 1,
            "equipamento_ligado_por": "código do ativo", "codigo_ativo": codigo, "situacao": situacao,
            "fabricante": fab, "componente": comp, "duracao_min": None, "abertura_por": "nota"}


CHAMADOS = [_ch(17159, "BRS100-INVR1.1", 20260622), _ch(17292, "BRS100-ETKR1", 20260302, fab="STI", comp="Tracker"),
            _ch(17704, "THPN-BRS100-PGINVR1", 20261024, comp="Inversor (em almoxarifado)"),
            _ch(17999, "BRS100-INVR2.5", 20261001, situacao="concluido"),          # fechado: não trata mais nada
            _ch(18000, "BRS100-INVR2.6", 20261020, site="Thopen - Outra Usina 1 - SP")]


def _montado():
    its = dt.itens_os(MES, {"Barretos"}, "2026-10", AGORA) + dt.itens_chamado(CHAMADOS, {SITE}, AGORA, "2026-10")
    return dt.montar(its, [(i["inversor"], i["cabine"]) for i in INVERSORES])


# ── 1. a regra (pura) ────────────────────────────────────────────────────────────────────────────────────────────────
def test_ativo_do_codigo_segue_a_regua_da_disponibilidade():
    assert dt.ativo_do_codigo("BRS100-INVR1.1") == ("inversor", "Inversor 1.1")
    assert dt.ativo_do_codigo("MRO100-DINV1.12") == ("inversor", "Inversor 1.12")
    assert dt.ativo_do_codigo("NBS100-INVR16") == ("inversor", "Inversor 16")
    assert dt.ativo_do_codigo("ACB100-CABN2") == ("cabine", "Cabine 2")
    assert dt.ativo_do_codigo("BRS100-SKID2") == ("cabine", "Cabine 2")
    assert dt.ativo_do_codigo("THPN-CLN100") == ("usina", "Usina inteira")
    assert dt.ativo_do_codigo("BRS100-ETKR1")[0] == "outro"
    assert dt.ativo_do_codigo("THPN-BRS100-PGINVR1")[0] == "outro"           # o inversor em almoxarifado não é o da usina


def test_os_aberta_explica_o_problema_de_hoje_do_inversor():
    m = _montado()
    its = m["inversores"]["Inversor 1.14"]
    x = next(i for i in its if i["os"] == 17016)
    assert x["aberta"] and x["hoje"] and x["mes"]
    assert x["link"] == "/os/os/folio/17016"
    assert "Desligamento por falha de equipamento (Corretiva Emergencial) — Inversor 1.14" == x["causa"]
    assert "OS 17016 · Corretiva Emergencial · Inversor 1.14 · desde 22/10 07:00 · aberta" in x["prova"]
    assert x["acao"] == "Já tem OS 17016 aberta há 5 dias: acompanhar a OS."
    assert its[0]["os"] == 17016, "o aberto vem primeiro"


def test_os_da_cabine_e_da_usina_cobrem_os_inversores_de_baixo_so_no_mes():
    m = _montado()
    i11 = {x["os"]: x for x in m["inversores"]["Inversor 1.5"]}
    assert set(i11) == {15510, 16520}                                         # a cabine 1 e a usina inteira
    assert i11[15510]["mes"] and not i11[15510]["hoje"], "fechada em 13/10: explica o mês, não o problema de agora"
    assert "fechada em 13/10 15:06" in i11[15510]["prova"] and "95 h de sol fora no mês" in i11[15510]["prova"]
    assert i11[15510]["acao"] == "Já tratado pela OS 15510 (fechada em 13/10 15:06)."
    i21 = {x["os"] for x in m["inversores"]["Inversor 2.1"]}
    assert i21 == {16520}, "a OS da cabine 1 não cobre a cabine 2"
    assert {x["os"] for x in m["usina"]} == {16520}


def test_chamado_aberto_do_inversor_e_aguardando_fabricante_ha_n_dias():
    m = _montado()
    ch = next(x for x in m["inversores"]["Inversor 1.1"] if x["tipo"] == "chamado")
    assert ch["os"] == 17159 and ch["dias"] == 127 and ch["hoje"] and ch["mes"]
    assert ch["acao"] == "Aguardando fabricante há 127 dias."
    assert ch["causa"] == "Chamado de garantia com Sungrow · Inversor — Inversor 1.1"
    assert "aberto desde 22/06/2026" in ch["prova"] and ch["link"] == "/os/os/folio/17159"


def test_chamado_fechado_de_outra_usina_ou_de_tracker_nao_explica_inversor():
    m = _montado()
    todos = [x for v in m["inversores"].values() for x in v]
    assert not [x for x in todos if x["os"] in (17999, 18000, 17292, 17704)]
    assert {x["os"] for x in m["outros"]} == {17292, 17704}, "tracker e almoxarifado ficam só contados"
    assert "Inversor 2.5" not in m["inversores"] or all(x["os"] != 17999 for x in m["inversores"]["Inversor 2.5"])


def test_os_cancelada_e_de_outra_usina_nao_entram():
    its = dt.itens_os(MES, {"Barretos"}, "2026-10", AGORA)
    assert {x["os"] for x in its} == {17016, 15510, 16520}


def test_inversor_sem_nada_nao_aparece_no_mapa():
    m = _montado()
    assert "Inversor 2.9" in m["inversores"], "a OS da usina inteira cobre todo inversor"
    # sem a OS da usina, o inversor 2.9 não tem nada
    mes = dict(MES, oss=[o for o in OSS if o["folio"] != 16520])
    its = dt.itens_os(mes, {"Barretos"}, "2026-10", AGORA) + dt.itens_chamado(CHAMADOS, {SITE}, AGORA, "2026-10")
    m2 = dt.montar(its, [(i["inversor"], i["cabine"]) for i in INVERSORES])
    assert "Inversor 2.9" not in m2["inversores"]


def test_mes_passado_nao_ganha_chamado_aberto_depois():
    ch = dt.itens_chamado([_ch(1, "BRS100-INVR1.4", 20261023)], {SITE}, AGORA, "2026-09")
    assert ch and ch[0]["mes"] is False and ch[0]["hoje"] is True


# ── 2. a rota ──────────────────────────────────────────────────────────────────────────────────────────────────────────
class _Livro:
    def __init__(self, linhas):
        self._l = linhas

    def linhas(self):
        return self._l, False, "2026-10-27T17:50:00Z"


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    monkeypatch.setattr(app, "NEXUS_SSO_CHAVE", "")
    monkeypatch.setitem(app.app.config, "PROPAGATE_EXCEPTIONS", False)
    monkeypatch.setattr(app, "_frac_disp_dados", lambda: {"meses": {"2026-10": MES}})
    monkeypatch.setattr(app, "_frac_fractall_map", lambda: {"barretos": SITE})
    linhas = [[c.get(k) for k in dt.CAB_CHAMADO] for c in CHAMADOS]
    monkeypatch.setattr(app, "_dtr_chamados_livro", lambda: _Livro(linhas))
    return app.app.test_client()


def test_rota_monta_pela_usina_do_indice_e_pelo_site(cli):
    j = cli.get("/api/diagnostico/tratamento?usina=Barretos&mes=2026-10").get_json()
    assert j["os_ok"] and j["chamados_ok"] and j["site_fracttal"] == SITE
    assert {x["os"] for x in j["inversores"]["Inversor 1.1"]} >= {17159, 15510, 16520}
    assert any(x["acao"].startswith("Aguardando fabricante há") for x in j["inversores"]["Inversor 1.1"])


def test_rota_sem_o_mes_no_indice_diz_que_nao_leu(cli):
    j = cli.get("/api/diagnostico/tratamento?usina=Barretos&mes=2026-08").get_json()
    assert j["os_ok"] is False and "não tem 2026-08" in j["os_erro"]
    # os chamados seguem: são outra leitura
    assert j["chamados_ok"] and any(x["tipo"] == "chamado" for x in j["inversores"]["Inversor 1.1"])


def test_rota_sem_o_livro_de_chamados_diz_que_nao_leu(cli, monkeypatch):
    class _Nada:
        def linhas(self):
            return None, False, None
    monkeypatch.setattr(app, "_dtr_chamados_livro", lambda: _Nada())
    j = cli.get("/api/diagnostico/tratamento?usina=Barretos").get_json()
    assert j["chamados_ok"] is False and "não foi lido" in j["chamados_erro"]


def test_rota_e_leitura_do_gestor_do_nexus():
    import leitura_nexus
    assert leitura_nexus.permitido_gestor("GET", "/api/diagnostico/tratamento", ["usina", "mes"])
    assert not leitura_nexus.permitido_gestor("POST", "/api/diagnostico/tratamento")


# ── 3. a tela: o script inteiro da página no node, com a rede dublada ─────────────────────────────────────────────
def _trat(**troca):
    its = dt.itens_os(MES, {"Barretos"}, "2026-10", AGORA) + dt.itens_chamado(CHAMADOS, {SITE}, AGORA, "2026-10")
    corpo = dict(dt.montar(its, [(i["inversor"], i["cabine"]) for i in INVERSORES]), mes="2026-10", os_ok=True,
                 chamados_ok=True)
    corpo.update(troca)
    return [200, json.loads(json.dumps(corpo, default=str))]


def _motor(*invs):
    """O motor da API PV dizendo R-09 nos inversores pedidos (o problema "de agora")."""
    return [200, {"diagnosticos": [{"regra": "R-09", "nivel": "inversor", "escopo": n, "causa": "Subperformance de inversor",
                                    "confianca": "media", "severidade": "atencao", "classificacao": "controlavel",
                                    "acao": "Abrir inspeção.", "evidencia": ["teste"]} for n in invs],
                  "trackers_por_inversor": {}, "resumo": {}, "trk_ok": True}]


def _rotas_trat(trat, motor):
    r = _rotas(plant=[200, {"plant_id": PID, "inversores": [_inv("1.1"), _inv("1.5"), _inv("1.14"), _inv("2.9")]}],
               diag=motor)
    r["/api/diagnostico/tratamento"] = trat
    return r


_LER = """
  const h = ELS.diags.innerHTML, i = h.indexOf('<details class="tdet">');
  out({ frente: i < 0 ? h : h.slice(0, i), grupo: i < 0 ? '' : h.slice(i), c: cartoes() });"""


def test_tela_os_aberta_vai_para_em_tratamento_e_o_sem_nada_fica_na_frente(tmp_path):
    r = _pagina(_rotas_trat(_trat(), _motor("Inversor 1.14", "Inversor 2.9")), _LER, tmp_path,
                search="?fonte=pv&nome=Barretos")
    # 2.9 só tem a OS da usina de 16/10 (fechada): o problema DE AGORA dele não tem tratamento
    assert "Inversor 2.9" in r["frente"] and "Sem tratamento <b class=\"num\">1</b>" in r["frente"], r["frente"]
    assert "Inversor 1.14" not in r["frente"]
    g = r["grupo"]
    assert "Explicado / em tratamento <b class=\"num\">1</b>" in g and "Inversor 1.14" in g
    assert 'href="/os/os/folio/17016"' in g and "aberta há 5 dias: acompanhar a OS." in g and "em tratamento" in g
    assert "22/10/2026" in g, "Desde = o início da OS"


def test_tela_chamado_aberto_aguardando_fabricante(tmp_path):
    r = _pagina(_rotas_trat(_trat(), _motor("Inversor 1.1")), _LER, tmp_path, search="?fonte=pv&nome=Barretos")
    assert "Inversor 1.1" in r["grupo"] and "Aguardando fabricante há 127 dias." in r["grupo"], r["grupo"]
    assert 'href="/os/os/folio/17159"' in r["grupo"] and "Chamado de garantia com Sungrow" in r["grupo"]
    assert "Nada sem tratamento" in r["frente"]


def test_tela_os_fechada_no_mes_nao_explica_problema_de_agora(tmp_path):
    """Inversor 1.5: só a cabine 1 (fechada em 13/10) e a usina (16/10). O R-09 de agora fica na frente."""
    r = _pagina(_rotas_trat(_trat(), _motor("Inversor 1.5")), _LER, tmp_path, search="?fonte=pv&nome=Barretos")
    assert "Inversor 1.5" in r["frente"] and not r["grupo"], r


def test_tela_problema_do_mes_e_explicado_pela_os_do_mes(tmp_path):
    """O mesmo inversor 1.5 abaixo da meta no MÊS: a OS da cabine 1 (05 a 13/10) explica."""
    rotas = _rotas_trat(_trat(), _motor())
    rotas["/api/inv/pr-mes"] = [200, {"inversores": {"Inversor 1.5": {"pr": 60.0, "gen_mwh": 10},
                                                     "Inversor 2.9": {"pr": 81.0, "gen_mwh": 12}},
                                      "pr_meta": 80, "pr_usina": 80.5}]
    r = _pagina(rotas, _LER, tmp_path, search="?fonte=pv&nome=Barretos")
    assert "Inversor 1.5" in r["grupo"] and "Já tratado pela OS 15510" in r["grupo"], r
    assert "explicado" in r["grupo"] and "Inversor 1.5" not in r["frente"]


def test_tela_sem_a_leitura_do_tratamento_nao_afirma_sem_tratamento(tmp_path):
    r = _pagina(_rotas_trat([503, {"erro": "fora"}], _motor("Inversor 1.14")), _LER, tmp_path,
                search="?fonte=pv&nome=Barretos")
    # a OS aberta que a tela já lê do Fracttal continuaria valendo; aqui o Fracttal da tela não tem nenhuma
    assert "Inversor 1.14" in r["frente"] and not r["grupo"]
    assert "não cruzei com as OS de desligamento e os chamados" in r["frente"], r["frente"]


def test_tela_os_aberta_do_fracttal_da_tela_tambem_conta(tmp_path):
    """A OS aberta que a própria tela lê do Fracttal (o "Acompanhar OS" de antes), mesmo sem o índice dela."""
    rotas = _rotas_trat(_trat(inversores={}, usina=[], cabines={}), _motor("Inversor 2.9"))
    rotas["/api/fracttal/os"] = [200, {"ok": True, "usina_os": [], "total": 1, "por_inversor": {
        "Inversor 2.9": {"code": "BRS100-INVR2.9", "os": [{"folio": 17777, "tipo": "Corretiva", "aberta": True,
                                                           "criada": "2026-10-26", "ativo": "Inversor 2.9"}]}}}]
    rotas["/api/inv/pr-mes"] = [200, {"inversores": {"Inversor 2.9": {"pr": 81.0, "gen_mwh": 12}}, "pr_meta": 80}]
    r = _pagina(rotas, _LER, tmp_path, search="?fonte=pv&nome=Barretos")
    assert "Inversor 2.9" in r["grupo"] and "Já tem OS 17777 aberta: acompanhar." in r["grupo"], r
