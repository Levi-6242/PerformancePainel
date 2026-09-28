# -*- coding: utf-8 -*-
"""Trava com OS aberta (passo 5, 27/09/2026).

Trancar tira a string da conta e da aba de falhas no mês inteiro; com OS de recomposição ou ticket aberto, a trava esconde
uma perda que o campo ainda vai resolver. No cruzamento com o Fracttal (27/09), a Guatambu tinha a Ipv18 trancada na
Guatambu 1 INVERSOR03 e a OS 11016 aberta no INVR3.2 — o nome dos inversores da Guatambu mudou entre agosto e hoje, e a
ligação não está provada. Trancar é para entrada sem string ligada. A tela passa a perguntar antes de trancar string com OS
ou ticket aberto, e a aba lista as trancadas que uma OS de recomposição aberta cita (pelo nome de inversor de hoje).
"""
import json
import os

import app

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_strings_citadas_no_texto_da_os():
    assert app._falhas_os_citadas("Strings Ipv11 e Ipv12 com corrente nula, verificar e normalizar") == [11, 12]
    assert app._falhas_os_citadas("String 12 sem corrente") == [12]
    assert app._falhas_os_citadas("Strings I_PV15, I_PV16 e I_PV17 com corrente nula") == [15, 16, 17]
    assert app._falhas_os_citadas("Identificar quais strings estão sem corrente") == []


class FakeFrac:
    """work_orders/ por status, paginado como o de verdade (~100 por página, mesmo pedindo 200)."""

    def __init__(self, por_status):
        self.por, self.chamadas = por_status, []

    def __call__(self, ep, **p):
        self.chamadas.append((ep, dict(p)))
        rows = self.por.get(p.get("id_status_work_order"), [])
        s = p.get("start", 0)
        return {"total": len(rows), "data": rows[s:s + 100]}


def wo(folio, code, desc, st, nota=""):
    return {"wo_folio": folio, "code": code, "description": desc, "task_note": nota, "id_status_work_order": st,
            "creation_date": "2026-08-11T12:00:00+00:00", "personnel_description": "Técnico"}


def test_indice_de_os_abertas_guarda_so_recomposicao_e_respeita_as_6_horas(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "FRACTTAL_ON", True)
    monkeypatch.setattr(app, "_FALHAS_OS_PATH", str(tmp_path / "os.json"))
    fake = FakeFrac({
        1: [wo("11016", "THPN-GTB100-INVR3.2", "[Inversor 3.2] - Recomposição de String", 1, "String Ipv18 com corrente nula"),
            wo("20000", "GTB100-CABN1", "Religamento da cabine", 1)]
           + [wo(str(30000 + i), "X", "Preventiva", 1) for i in range(150)],
        0: [wo("12728", "THPN-GTB100-INVR4.3", "[Inversor 4.3] - Recomposição de String", 0, "String Ipv12 com corrente nula")]})
    monkeypatch.setattr(app, "_frac_get", fake)
    monkeypatch.setattr(app.time, "sleep", lambda s: None)
    idx = app._falhas_os_abertas()
    assert [(o["folio"], o["cb"], o["inv"], o["cit"]) for o in idx["os"]] == [("11016", "GTB100", "3.2", [18]),
                                                                           ("12728", "GTB100", "4.3", [12])]
    assert sorted({p["id_status_work_order"] for _, p in fake.chamadas}) == [0, 1, 5, 6]   # a API não aceita lista
    n = len(fake.chamadas)
    app._falhas_os_abertas()                                   # dentro das 6 h: não pergunta de novo
    assert len(fake.chamadas) == n


def _indice(tmp_path, monkeypatch):
    p = tmp_path / "os.json"
    p.write_text(json.dumps({"ts": 0, "os": [{"folio": "11016", "cb": "GTB100", "inv": "3.2", "cit": [18],
                                              "status": "Em andamento", "criada": "11/08/2026",
                                              "descricao": "[Inversor 3.2] - Recomposição de String"}]}), encoding="utf-8")
    monkeypatch.setattr(app, "_FALHAS_OS_PATH", str(p))


def test_aviso_de_trava_lista_a_os_e_o_ticket_abertos_da_string(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "DASH_PASSWORD", "", raising=False)
    _indice(tmp_path, monkeypatch)
    monkeypatch.setattr(app, "_tickets_str_da_linha",
                        lambda nome: [{"inv": "3.2", "strings": [18], "desde": "11/08/2026", "linha": 50, "qtd": 1}])
    monkeypatch.setitem(app.USINA_COD, "guatambu", "GTB100")
    app.app.config["TESTING"] = True
    with app.app.test_client() as c:
        j = c.get("/api/strings/trava-aviso?usina=Guatambu&inv=Inversor 3.2&strings=Ipv18").get_json()
        assert [o["folio"] for o in j["os"]] == ["11016"] and [t["linha"] for t in j["tickets"]] == [50]
        j = c.get("/api/strings/trava-aviso?usina=Guatambu&inv=Inversor 3.2&strings=Ipv5").get_json()
        assert j["os"] == [] and j["tickets"] == []            # a OS e o ticket citam outra string


def test_trancada_da_api_pv_com_os_aberta_aparece_na_aba(monkeypatch):
    monkeypatch.setattr(app, "_trancadas", {"18747508|360312|Ipv18"})
    monkeypatch.setitem(app.USINA_COD, "guatambu", "GTB100")
    pv_dev = {"18747508": {"usina": "Guatambu", "nome_api": "Guatambu 1 (teste)", "names": {"360312": "Inversor 3.2"}}}
    idx = {"os": [{"folio": "11016", "cb": "GTB100", "inv": "3.2", "cit": [18], "status": "Em andamento",
                   "criada": "11/08/2026", "descricao": "[Inversor 3.2] - Recomposição de String"}]}
    (t,) = app._falhas_travas_com_os(idx, pv_dev)
    assert (t["fonte"], t["usina"], t["inversor"], t["string"], t["os"]) == ("pv", "Guatambu", "Inversor 3.2", "Ipv18", "11016")


def test_trancada_da_athon_com_os_aberta_aparece_na_aba(monkeypatch):
    monkeypatch.setattr(app, "_trancadas", {"SMP100|INV_52|I_PV19"})
    monkeypatch.setattr(app, "_sunop_inv_display", lambda plant, key: "Inversor 5.2" if key == "INV_52" else key)
    idx = {"os": [{"folio": "13297", "cb": "SMP100", "inv": "5.2", "cit": [19, 20], "status": "Em andamento",
                   "criada": "09/09/2026", "descricao": "[Inversor 5.2] - Recomposição de String"}]}
    (t,) = app._falhas_travas_com_os(idx, {})
    assert (t["fonte"], t["inversor"], t["string"], t["os"]) == ("sunop", "Inversor 5.2", "ST 19", "13297")


def test_pacote_do_mes_leva_as_trancadas_com_os_aberta(monkeypatch):
    monkeypatch.setattr(app, "_falhas_travas_com_os", lambda idx, pv_dev: [{"string": "Ipv18", "os": "11016"}])
    pacote = {"strings": {"episodios": []}}
    app._falhas_anexa_travas(pacote, {"os": []}, {})
    assert pacote["strings"]["travas_com_os"] == [{"string": "Ipv18", "os": "11016"}]


def test_tela_pergunta_antes_de_trancar_string_com_manutencao_aberta():
    html = open(os.path.join(RAIZ, "docs", "redesign", "Monitoramento (novo design).html"), encoding="utf-8").read()
    ts = html[html.index("window.trancarString="):]
    ts = ts[:ts.index("\n};")]
    assert "if(trancar&&!(await _travaOk(pid,inv,[sid]))) return;" in ts
    ti = html[html.index("window.trancarInativas="):]
    ti = ti[:ti.index("\n};")]
    assert "if(!(await _travaOk(pid,inv,ids))) return;" in ti
    assert "async function _travaOk(" in html and "/api/strings/trava-aviso" in html


def test_aba_mostra_entradas_vazias_trancadas_com_os_e_as_fontes_novas(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "", raising=False)
    app.app.config["TESTING"] = True
    with app.app.test_client() as c:
        html = c.get("/painel/falhas").get_data(as_text=True)
    assert 'id="t-vaz"' in html and 'id="t-trv"' in html
    assert "D.strings.entradas_vazias" in html and "D.strings.travas_com_os" in html
    assert "pvsb:" in html and "solaredge:" in html
