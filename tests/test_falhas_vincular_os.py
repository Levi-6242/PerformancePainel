# -*- coding: utf-8 -*-
"""Vincular OS na aba Strings e trackers (Levi, 20/10/2026): "1.5 Opção de vincular OS, eu clico no botão e buscas as
OSs de recomposição de string desse inversor (...) 1.7 A OS só carrega se eu clicar em vincular, caso eu não clique não
deve carregar nem fazer requisição alguma do fractal (...) 1.8 faça algo parecido com os trackers!".

- A BUSCA (`GET /api/painel/falhas/os`) é a única chamada da tela ao Fracttal. Aqui o Fracttal é um dublê do `_frac_get`
  (o conftest só barra a SunOp e a PV Operation): o `_frac_ativo` e o `_frac_wos_raw` de verdade rodam por cima dele,
  com os caches zerados. O índice de ativos (`_frac_codebase_index`, ~150 páginas com ele vencido) nunca é chamado.
- O VÍNCULO gravado (`/api/painel/falhas/vinculos`) vai ao livro nexus_falhas do banco do Nexus (aqui, um banco de
  mentira que lê o xlsx enviado de verdade), sem pessoa; quem vinculou vai só ao log da máquina.
Casos reais: Guatambu 1.2 (parada de 01 a 20/10) → OS 16561, em andamento, evento 01/10 (no índice da Disponibilidade:
THPN-GTB100-INVR1.2, Ipv18); Mandaguaçu 4.4 (01 a 15/10) → só a 9915, de 23/07, ANTERIOR à parada; Sete Lagoas
Tracker 1.49 (2C) → a 15481 existe no SLG200-ETKR49.200, mas a 2C não está no de-para dos trackers.
"""
import json
from io import BytesIO

import pytest

import app
import falhas_publicar
import falhas_vinculos as fv
import leitura_nexus as ln
from test_porta_nexus import _sem_rede, cli, entrar  # noqa: F401  (fixtures e passos da porta, para o gestor)


# ── o Fracttal de mentira (o REST devolve UMA LINHA POR TAREFA, datas em UTC) ───────────────────────────────────────────
class _Fracttal:
    def __init__(self):
        self.ativos, self.wos, self.pedidos, self.cota = {}, {}, [], False

    def get(self, ep, *, _motivo=None, **params):
        mot = _motivo if _motivo is not None else {}
        self.pedidos.append((ep, params.get("id_item")))
        if self.cota:
            mot.update(status=429, reset="12", erro="Too Many Requests")
            return None
        if ep.startswith("items/"):
            code = ep[len("items/"):]
            if code in self.ativos:
                mot.update(status=200, erro=None)
                return {"data": [{"id": self.ativos[code], "code": code,
                                  "description": f"Inversor {code.rsplit('INVR', 1)[-1]}  Huawei SUN2000"}]}
            mot.update(status=404, erro="not found")
            return None
        if ep == "work_orders/":
            mot.update(status=200, erro=None)
            return {"data": self.wos.get(params["id_item"], [])}
        raise AssertionError(ep)


def _w(folio, desc, status, criada, evento=None, final=None, tipo="Corretiva", task_note="", note="", wo_final=None):
    return {"wo_folio": folio, "description": desc, "tasks_log_task_type_main": tipo, "id_status_work_order": status,
            "creation_date": criada, "event_date": evento, "final_date": final, "wo_final_date": wo_final,
            "task_note": task_note, "note": note}


# Guatambu 1.2: a 16561 (o nº, o status e o evento são os do índice da Disponibilidade de 20/10; o texto é o do OS
# Creator), uma recomposição cancelada e duas OS do mesmo ativo que não são de recomposição de string
W16561 = _w("16561", "[Inversor 1.2] - Recomposição de String", 1, "2026-10-01T14:20:00+00:00", "2026-10-01T12:00:00+00:00",
            task_note="String Ipv18 com corrente nula, verificar e normalizar")
W_CANCELADA = _w("16600", "[Inversor 1.2] - Recomposição de String", 4, "2026-10-03T10:00:00+00:00")
W_CABOS = _w("15990", "Recomposição de cabos CC do inversor", 2, "2026-09-20T10:00:00+00:00", final="2026-09-21T15:00:00+00:00")
W_INSPECAO = _w("15000", "Inspeção termográfica", 2, "2026-09-01T10:00:00+00:00", tipo="Inspeção", final="2026-09-02T12:00:00+00:00")
# Mandaguaçu 4.4: a 9915, concluída em julho (a conclusão é a MAIOR final_date das tarefas, no relógio daqui)
W9915_A = _w("9915", "[Inversor 4.4] - Recomposição de String", 2, "2026-07-23T13:00:00+00:00", "2026-07-23T11:00:00+00:00",
             final="2026-07-24T18:30:00+00:00", task_note="String Ipv5 com corrente nula")
W9915_B = dict(W9915_A, final_date="2026-07-25T12:10:00+00:00", wo_final_date="2026-08-25T13:00:00+00:00")


@pytest.fixture
def fr(monkeypatch):
    f = _Fracttal()
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    monkeypatch.setattr(app, "FRACTTAL_ON", True)
    monkeypatch.setattr(app, "_frac_get", f.get)
    monkeypatch.setattr(app, "_frac_code_cache", {})
    monkeypatch.setattr(app, "_frac_wos_cache", {})
    monkeypatch.setattr(app, "USINA_COD", {"guatambu": "GTB100", "mandaguacu": "MNG100", "ipixuna 1": "IPX100",
                                           "ipixuna do para": "2CIPX100"})
    monkeypatch.setattr(app, "USINA_PREFIXO_FRAC", {"GTB100": "THPN", "IPX100": "2C"})
    monkeypatch.setattr(app, "_frac_disp_dados", lambda: {})          # sem índice de reserva, salvo quem testa

    def _proibido(*a, **k):
        raise AssertionError("a busca não pode varrer o índice de ativos do Fracttal dentro do clique")
    monkeypatch.setattr(app, "_frac_codebase_index", _proibido)
    f.ativos = {"THPN-GTB100-INVR1.2": 501, "MNG100-INVR4.4": 502, "IPX100-INVR1.1": 503, "2C-IPX100-INVR1.1": 504}
    f.wos = {501: [W16561, W_CANCELADA, W_CABOS, W_INSPECAO], 502: [W9915_A, W9915_B]}
    return f


def _busca(c, **q):
    return c.get("/api/painel/falhas/os", query_string=q)


def test_strings_lista_so_a_recomposicao_viva_do_inversor(fr):
    c = app.app.test_client()
    r = _busca(c, tipo="strings", fonte="pv", plant_id="18747508", usina="Guatambu", inversor="Inversor 1.2",
               desde="2026-10-01")
    assert r.status_code == 200
    j = r.get_json()
    assert j["ok"] is True and j["ativo"] == {"code": "THPN-GTB100-INVR1.2", "nome": "Inversor 1.2"}
    (o,) = j["os"]                                     # cancelada, "cabos CC" e inspeção fora (régua do strings_os)
    assert o == {"folio": "16561", "status": "Em andamento", "tipo": "Corretiva", "criada": "2026-10-01 11:20",
                 "evento": "2026-10-01 09:00", "concluida": None, "descricao": "[Inversor 1.2] - Recomposição de String",
                 "strings": [18], "anterior": False, "link": "/os/os/folio/16561"}
    assert len(j["buscado_em"]) == 16
    # 3 pedidos com o cache frio (o code sem prefixo não existe; com o da Thopen, sim; as OS do ativo) e 0 no 2º clique
    assert fr.pedidos == [("items/GTB100-INVR1.2", None), ("items/THPN-GTB100-INVR1.2", None), ("work_orders/", 501)]
    _busca(c, tipo="strings", usina="Guatambu", inversor="Inversor 1.2", desde="2026-10-01")
    assert len(fr.pedidos) == 3


def test_os_de_antes_da_parada_vem_marcada_anterior_e_conclui_na_ultima_tarefa(fr):
    j = _busca(app.app.test_client(), tipo="strings", usina="Mandaguaçu", inversor="Inversor 4.4",
               desde="2026-10-01").get_json()
    (o,) = j["os"]
    assert (o["folio"], o["status"], o["anterior"]) == ("9915", "Concluída", True)
    assert o["evento"] == "2026-07-23 08:00" and o["concluida"] == "2026-07-25 09:10"   # a maior final_date, UTC−3
    assert o["strings"] == [5]


def test_codigo_de_dois_clientes_procura_so_o_ativo_do_cliente_da_usina(fr):
    # IPX100: "IPX100" é a Ipixuna da Thopen e "2CIPX100" a do Pará da 2C (Info Geral); no Fracttal, IPX100-INVR1.1 e
    # 2C-IPX100-INVR1.1. O _frac_ativo puro acharia o da Thopen para a 2C
    c = app.app.test_client()
    j = _busca(c, tipo="strings", usina="Ipixuna do Pará", inversor="Inversor 1.1").get_json()
    assert j["ativo"]["code"] == "2C-IPX100-INVR1.1"
    assert [p for p in fr.pedidos if p[0].startswith("items/")] == [("items/2C-IPX100-INVR1.1", None)]
    fr.pedidos.clear()
    j = _busca(c, tipo="strings", usina="Ipixuna 1", inversor="Inversor 1.1").get_json()
    assert j["ativo"]["code"] == "IPX100-INVR1.1"
    assert not any("2C-" in p[0] for p in fr.pedidos)
    fr.ativos.pop("2C-IPX100-INVR1.1")
    fr.pedidos.clear()
    app._frac_code_cache.clear()
    j = _busca(c, tipo="strings", usina="Ipixuna do Pará", inversor="Inversor 1.1").get_json()
    assert j["ativo"] is None and "dois clientes" in j["motivo"]                   # nunca o ativo da Thopen
    assert [p[0] for p in fr.pedidos] == ["items/2C-IPX100-INVR1.1"]


def test_ativo_nao_achado_e_200_com_o_motivo_e_sem_os(fr):
    c = app.app.test_client()
    j = _busca(c, tipo="strings", usina="Santo Antonio do Platina", inversor="Inversor 1.1").get_json()
    assert j["ok"] is True and j["ativo"] is None and j["os"] == [] and "Info Geral" in j["motivo"]
    assert fr.pedidos == []                                   # sem código, nem pergunta
    j = _busca(c, tipo="strings", usina="Guatambu", inversor="Inversor 9.9").get_json()
    assert j["ativo"] is None and "GTB100-INVR9.9" in j["motivo"] and j["os"] == []


def test_fracttal_sem_resposta_e_502_e_nao_sem_os(fr):
    fr.cota = True
    c = app.app.test_client()
    r = _busca(c, tipo="strings", usina="Guatambu", inversor="Inversor 1.2", desde="2026-10-01")
    assert r.status_code == 502
    assert r.get_json() == {"ok": False, "fonte_ok": False, "motivo": "o Fracttal não respondeu (HTTP 429: Too Many Requests)"}
    # a falha não fica no cache como "não existe": voltando a cota, a mesma busca acha
    fr.cota = False
    assert _busca(c, tipo="strings", usina="Guatambu", inversor="Inversor 1.2").get_json()["ativo"]["code"] == \
        "THPN-GTB100-INVR1.2"


def _indice(monkeypatch, entradas, ts=1760979390.0):
    monkeypatch.setattr(app, "_frac_disp_dados", lambda: {"ts": ts, "os_string": entradas})


# entradas do índice os_string da Disponibilidade, como estavam no PC em 20/10/2026 14:56
IDX_16561_12 = {"os": "16561", "code": "THPN-GTB100-INVR1.2", "prefixo": "THPN", "cb": "GTB100", "inv": "1.2",
                "evento": "2026-10-01", "status": "Em andamento", "qtd_texto": None, "strings_texto": [], "cit": [18]}
IDX_16561_11 = dict(IDX_16561_12, code="THPN-GTB100-INVR1.1", inv="1.1", cit=[6])
IDX_9915 = {"os": "9915", "code": "MNG100-INVR4.4", "prefixo": None, "cb": "MNG100", "inv": "4.4", "evento": "2026-07-23",
            "status": "Concluída", "qtd_texto": None, "strings_texto": [], "cit": [5]}


def test_fracttal_sem_resposta_nas_strings_cai_no_indice_de_30_min(fr, monkeypatch):
    fr.cota = True
    _indice(monkeypatch, [IDX_16561_11, IDX_16561_12, IDX_9915])
    r = _busca(app.app.test_client(), tipo="strings", usina="Guatambu", inversor="Inversor 1.2", desde="2026-10-01")
    assert r.status_code == 200
    j = r.get_json()
    assert (j["ok"], j["fonte_ok"], j["reserva"]) == (True, False, "varredura")
    assert j["motivo"] == "o Fracttal não respondeu (HTTP 429: Too Many Requests)"
    assert j["varrido_em"] == app.datetime.fromtimestamp(1760979390.0).strftime("%Y-%m-%d %H:%M")
    assert j["ativo"] == {"code": "THPN-GTB100-INVR1.2", "nome": None}
    assert j["os"] == [{"folio": "16561", "status": "Em andamento", "tipo": None, "criada": None, "evento": "2026-10-01",
                        "concluida": None, "descricao": None, "strings": [18], "anterior": False,
                        "link": "/os/os/folio/16561"}]                               # só o 1.2, não o 1.1 da mesma OS
    j = _busca(app.app.test_client(), tipo="strings", usina="Mandaguaçu", inversor="Inversor 4.4",
               desde="2026-10-01").get_json()
    assert j["reserva"] == "varredura" and j["os"][0]["anterior"] is True


def test_sem_nada_no_indice_ou_nos_trackers_a_falha_e_502(fr, monkeypatch, depara):
    fr.cota = True
    _indice(monkeypatch, [IDX_9915])                     # o índice não tem OS do Guatambu 1.2
    c = app.app.test_client()
    assert _busca(c, tipo="strings", usina="Guatambu", inversor="Inversor 1.2").status_code == 502
    _indice(monkeypatch, [])
    assert _busca(c, tipo="strings", usina="Mandaguaçu", inversor="Inversor 4.4").status_code == 502
    _indice(monkeypatch, [IDX_16561_12])                 # nos trackers não há reserva: 502
    r = _busca(c, tipo="trackers", fonte="pv", plant_id="60062", usina="Altair", tracker="TRK67")
    assert r.status_code == 502 and r.get_json()["fonte_ok"] is False


def test_parametros_fora_do_formato_e_sem_credencial(fr, monkeypatch):
    c = app.app.test_client()
    assert _busca(c, tipo="outro", usina="Guatambu", inversor="Inversor 1.2").status_code == 400
    assert _busca(c, tipo="strings", usina="Guatambu").status_code == 400
    assert _busca(c, tipo="strings", usina="Guatambu", inversor="Inversor 1.2", desde="01/10/2026").status_code == 400
    assert _busca(c, tipo="trackers", fonte="pv", usina="Altair", tracker="TRK67").status_code == 400   # sem plant_id
    assert fr.pedidos == []
    monkeypatch.setattr(app, "FRACTTAL_ON", False)
    r = _busca(c, tipo="strings", usina="Guatambu", inversor="Inversor 1.2")
    assert r.status_code == 503 and r.get_json()["fonte_ok"] is False and "credencial" in r.get_json()["motivo"]


# ── trackers: o "Code Fracttal" do de-para, pelo cadastro do plant_id ────────────────────────────────────────────────────
def _depara_falso():
    """O formato do _trk_depara_carregar com duas sub-usinas da Altair (o número do tracker se repete entre elas)."""
    def usina(fonte, nome, trackers):
        lin = [{"tracker": t, "num": app._trk_id_num(t), "fracttal": None, "code": code, "cabine": None, "casou": "",
                "obs": obs, "situacao": "sem_par" if obs else "casado"} for t, code, obs in trackers]
        return {"fonte": fonte, "usina": nome, "usina_fracttal": None, "trackers": lin,
                "por_num": {x["num"]: x for x in lin}}
    por = {("pv", app._trk_depara_nrm("Altair 1 (73)")): usina("pv", "Altair 1 (73)", [("TRK67", "ALT100-ETKR67.100", None)]),
           ("pv", app._trk_depara_nrm("Altair 3 (75)")): usina("pv", "Altair 3 (75)", [("TRK67", "ALT100-ETKR67.101", None),
                                                                                        ("TRK90", None, "excedente")])}
    return {"por_usina": por, "resumo": [], "pendencias": [], "arquivo": "trackers_depara.xlsx", "mtime": None, "n": 3}


W16596 = _w("16596", "[Tracker 67.101] - Verificação de Tracker Parado", 1, "2026-10-08T12:00:00+00:00",
            "2026-10-08T11:30:00+00:00")
W_TRK_CANC = _w("16610", "[Tracker 67.101] - Verificação de Tracker Parado", 4, "2026-10-09T12:00:00+00:00")
W_TRK_INSP = _w("15100", "Inspeção de trackers", 3, "2026-09-10T12:00:00+00:00", tipo="Inspeção",
                final="2026-09-10T20:00:00+00:00")


@pytest.fixture
def depara(monkeypatch, fr):
    monkeypatch.setattr(app, "_trk_depara_carregar", _depara_falso)
    # o registro de trackers sabe com que nome a fonte cadastra o plant_id (o nome do drill do Monitoramento)
    monkeypatch.setattr(app, "_trk_eventos", {"2026-10-18": {"60062": {"nome": "Altair 3 (75)"}},
                                              "2026-10-19": {"60062": {"nome": "Altair 3 (75)"}, "60060": {"nome": "Altair 1 (73)"}}})
    fr.ativos["ALT100-ETKR67.101"] = 701
    fr.wos[701] = [W_TRK_INSP, W16596, W_TRK_CANC]
    return fr


def test_trackers_acha_o_ativo_pelo_cadastro_do_plant_id_e_lista_todas_as_vivas(depara):
    j = _busca(app.app.test_client(), tipo="trackers", fonte="pv", plant_id="60062", usina="Altair", tracker="TRK67",
               desde="2026-10-13").get_json()
    assert j["ok"] is True and j["ativo"]["code"] == "ALT100-ETKR67.101"            # o da Altair 3, não o da Altair 1
    assert [o["folio"] for o in j["os"]] == ["16596", "15100"]                    # a mais nova primeiro; cancelada fora
    assert j["os"][0]["anterior"] is True and j["os"][0]["evento"] == "2026-10-08 08:30"
    assert all("strings" not in o for o in j["os"])                              # "strings citadas" é só das strings


def test_tracker_sem_code_diz_por_que_sem_perguntar_ao_fracttal(depara):
    c = app.app.test_client()
    # a 2C não está no de-para: a Sete Lagoas Tracker 1.49 tem a 15481 no SLG200-ETKR49.200 do Fracttal, mas a regra
    # "Tracker 1.N = ETKR N.200" não está combinada
    j = _busca(c, tipo="trackers", fonte="owen", plant_id="STL", usina="Sete Lagoas", tracker="Tracker 1.49").get_json()
    assert j["ok"] is True and j["ativo"] is None and "2C" in j["motivo"] and j["os"] == []
    j = _busca(c, tipo="trackers", fonte="pv", plant_id="60062", usina="Altair", tracker="TRK90").get_json()
    assert j["ativo"] is None and "sem Code Fracttal" in j["motivo"] and "excedente" in j["motivo"]
    # o plant_id que o registro desta máquina não conhece: a usina canônica tem duas sub-usinas com o TRK67 — não chuta
    j = _busca(c, tipo="trackers", fonte="pv", plant_id="99999", usina="Altair", tracker="TRK67").get_json()
    assert j["ativo"] is None and "99999" in j["motivo"]
    assert depara.pedidos == []


# ── o vínculo gravado: livro nexus_falhas · fato_decisao_vinculo_os ─────────────────────────────────────────────────────
class _R:
    def __init__(self, d, code=200):
        self._d, self.status_code = d, code

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class _Banco:
    """A db_performace de mentira, com o livro dos vínculos (lê o xlsx enviado de verdade)."""

    def __init__(self):
        self.livros, self.linhas, self.fora = set(), None, False

    def get(self, url, headers=None, params=None, timeout=None):
        if self.fora:
            raise ConnectionError("banco fora")
        if url.endswith("/api/workbooks"):
            return _R([{"key": k} for k in self.livros])
        if url.endswith("/api/sheets"):
            return _R([{"id": 9, "workbook_key": fv.LIVRO, "sheet_name": fv.ABA}] if self.linhas is not None else [])
        if url.endswith("/api/sheets/9/rows"):
            off, lim = params["offset"], params["limit"]
            return _R({"rows": [{"headers": fv.CAB, "values": lin} for lin in (self.linhas or [])[off:off + lim]]})
        raise AssertionError(url)

    def post(self, url, headers=None, json=None, params=None, files=None, timeout=None):
        if self.fora:
            raise ConnectionError("banco fora")
        assert headers["Authorization"] == "Bearer tok"
        if url.endswith("/api/workbooks"):
            self.livros.add(json["key"])
            return _R({})
        if url.endswith(f"/api/workbooks/{fv.LIVRO}/sync-xlsx"):
            from openpyxl import load_workbook
            ws = load_workbook(BytesIO(files["file"][1]))[fv.ABA]
            assert [c.value for c in ws[1]] == fv.CAB
            self.linhas = [list(r) for r in ws.iter_rows(min_row=2, values_only=True)]
            return _R({"inserted": len(self.linhas)})
        raise AssertionError(url)


@pytest.fixture
def banco(monkeypatch, tmp_path):
    b = _Banco()
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    monkeypatch.setattr(app, "_FV_DECISOES", app._cob.Decisoes(
        "https://x/db", lambda: app.os.environ.get("GRIDCO_SQL_TOKEN", ""), str(tmp_path / "fv.json"), ttl=0, sessao=b,
        livro=fv.LIVRO, aba=fv.ABA, cab=fv.CAB, nome_livro=fv.NOME_LIVRO))
    monkeypatch.setattr(app, "_FV_LOG", str(tmp_path / "falhas_vinculos.log"))
    monkeypatch.setenv("GRIDCO_SQL_TOKEN", "tok")
    return b


GUATAMBU = {"tipo": "strings", "fonte": "pv", "plant_id": "18747508", "equipamento": "Inversor 1.2",
            "dia_inicio": "2026-10-01", "os": 16561, "decisao": "vincular"}
MANDAGUACU = {"tipo": "strings", "fonte": "pv", "plant_id": 18747520, "equipamento": "Inversor 4.4",
              "dia_inicio": "2026-10-01", "os": "9915", "decisao": "vincular"}


def test_vincular_grava_sem_pessoa_e_devolve_os_vigentes(banco):
    c = app.app.test_client()
    r = c.post("/api/painel/falhas/vinculos", json=GUATAMBU)
    assert r.status_code == 200
    assert r.get_json()["vinculos"] == [{"tipo": "strings", "fonte": "pv", "plant_id": "18747508",
                                         "equipamento": "Inversor 1.2", "dia_inicio": "2026-10-01", "os": 16561,
                                         "decidida_em": banco.linhas[0][0]}]
    (lin,) = banco.linhas
    d = dict(zip(fv.CAB, lin))
    # o dia do início vai ao livro como papel AAAAMMDD (regra 7 do Nexus); a API da tela segue com "AAAA-MM-DD"
    assert (d["data_id_inicio"], d["os"], d["origem"], d["decisao"]) == (20261001, 16561, "tela", "vincular")
    assert "senha" not in json.dumps(lin, default=str) and "@" not in json.dumps(lin, default=str)   # regra 8
    log = open(app._FV_LOG, encoding="utf-8").read()
    assert "senha compartilhada" in log and "vincular OS 16561" in log and "18747508|Inversor 1.2|20261001" in log
    r = c.post("/api/painel/falhas/vinculos", json=MANDAGUACU)                   # plant_id número e os texto também valem
    assert [v["os"] for v in r.get_json()["vinculos"]] == [16561, 9915]
    j = c.get("/api/painel/falhas/vinculos").get_json()
    assert j["ok"] is True and len(j["vinculos"]) == 2 and j["lido_em"] and "erro" not in j


def test_desvincular_so_acrescenta_e_tira_dos_vigentes(banco):
    c = app.app.test_client()
    c.post("/api/painel/falhas/vinculos", json=GUATAMBU)
    c.post("/api/painel/falhas/vinculos", json=MANDAGUACU)
    r = c.post("/api/painel/falhas/vinculos", json=dict(GUATAMBU, decisao="desvincular"))
    assert [v["os"] for v in r.get_json()["vinculos"]] == [9915]
    assert len(banco.linhas) == 3                                                # o histórico fica no livro


@pytest.mark.parametrize("troca", [{"tipo": "inversor"}, {"decisao": "ligar"}, {"fonte": "2capi"}, {"fonte": ""},
                                   {"plant_id": ""}, {"plant_id": "x" * 121}, {"equipamento": "  "},
                                   {"equipamento": "y" * 121}, {"dia_inicio": "2026-13-01"},
                                   {"dia_inicio": "01/10/2026"}, {"os": 0}, {"os": "16561a"}, {"os": True},
                                   {"os": 1.5},
                                   # texto livre num livro de leitura aberta que não se apaga (revisão de 20/10/2026)
                                   {"plant_id": "Fulano da Silva"}, {"equipamento": "Fulano da Silva"},
                                   {"equipamento": "Inversor 1.2\n2026-10-20 forjada"},
                                   {"equipamento": "Inversor 1.2\x01"}, {"os": 99999999999999999999}])
def test_vinculo_fora_do_formato_e_400_e_nao_grava(banco, troca):
    r = app.app.test_client().post("/api/painel/falhas/vinculos", json=dict(GUATAMBU, **troca))
    assert r.status_code == 400 and r.get_json()["ok"] is False and r.get_json()["motivo"]
    assert banco.linhas is None


@pytest.mark.parametrize("pid,eq", [("18749574", "INVERSOR01"), ("18748739", "Inversor 3.3"), ("26", "INV-402513"),
                                    ("STL", "Tracker 1.49"), ("73", "TRK67"), ("CPP100", "Inversor 13")])
def test_os_nomes_reais_dos_pacotes_passam(pid, eq):
    # a forma conferida nos pacotes de setembro e outubro: todo plant_id e todo equipamento da aba passam
    assert fv.linha("strings", "pv", pid, eq, "2026-10-01", 16561, "vincular")[4:6] == [pid, eq]


def test_as_fontes_do_vinculo_sao_as_do_pacote_da_aba():
    # a 2C dos trackers é "owen" e a String Box é "pvsb" no pacote; a cobertura.FONTES (2capi) recusaria as duas
    assert set(fv.FONTES) == set(falhas_publicar.FONTE_ROT)
    assert fv.linha("trackers", "owen", "STL", "Tracker 1.49", "2026-10-01", 15481, "vincular")[3] == "owen"


def test_banco_fora_le_a_ultima_leitura_boa_e_nao_grava(banco):
    c = app.app.test_client()
    c.post("/api/painel/falhas/vinculos", json=GUATAMBU)
    banco.fora = True
    j = c.get("/api/painel/falhas/vinculos").get_json()
    assert j["ok"] is True and [v["os"] for v in j["vinculos"]] == [16561] and "ConnectionError" in j["erro"]
    r = c.post("/api/painel/falhas/vinculos", json=MANDAGUACU)
    assert r.status_code == 500 and "não gravou" in r.get_json()["motivo"]


def test_sem_leitura_nenhuma_o_get_diz_que_nao_sabe(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    b = _Banco()
    b.fora = True
    monkeypatch.setattr(app, "_FV_DECISOES", app._cob.Decisoes("https://x/db", "tok", str(tmp_path / "nada.json"), ttl=0,
                                                               sessao=b, livro=fv.LIVRO, aba=fv.ABA, cab=fv.CAB))
    j = app.app.test_client().get("/api/painel/falhas/vinculos").get_json()
    assert j == {"ok": False, "vinculos": [], "lido_em": None,
                 "erro": "o banco do Nexus não respondeu (ConnectionError): nenhuma leitura boa nesta máquina"}


def test_sem_a_chave_do_banco_nao_grava(banco, monkeypatch):
    monkeypatch.setenv("GRIDCO_SQL_TOKEN", "")
    r = app.app.test_client().post("/api/painel/falhas/vinculos", json=GUATAMBU)
    assert r.status_code == 500 and "GRIDCO_SQL_TOKEN" in r.get_json()["motivo"] and banco.linhas is None


def test_vigentes_le_o_que_o_banco_devolve_em_outro_tipo():
    q = "2026-10-20T15:00:00Z"
    lin = fv.linha("strings", "pv", "18747508", "Inversor 1.2", "2026-10-01", 16561, "vincular", quando=q)
    assert lin[1] == 20261020 and lin[6] == 20261001
    # o banco pode devolver o número como 18747508.0 e o papel da data como texto: a chave é a mesma
    volta = [q, 20261020.0, "strings", "pv", 18747508.0, "Inversor 1.2", "20261001", 16561.0, "vincular", "tela"]
    assert fv.vigentes([volta]) == fv.vigentes([lin]) == [
        {"tipo": "strings", "fonte": "pv", "plant_id": "18747508", "equipamento": "Inversor 1.2",
         "dia_inicio": "2026-10-01", "os": 16561, "decidida_em": q}]
    # a última decisão vale; linha ilegível não conta
    tira = fv.linha("strings", "pv", "18747508", "Inversor 1.2", "2026-10-01", 16561, "desvincular",
                    quando="2026-10-20T15:05:00Z")
    assert fv.vigentes([lin, tira]) == [] and fv.vigentes([tira, lin]) == []
    assert fv.vigentes([lin[:6] + [20261399] + lin[7:]]) == []


# ── o gestor do Nexus: busca e baixa, não grava ──────────────────────────────────────────────────────────────────────
def test_gestor_le_e_busca_mas_nao_vincula(cli, monkeypatch):
    monkeypatch.setattr(app, "FRACTTAL_ON", False)                # a busca não vai ao Fracttal no teste
    entrar(cli, "gestor@exemplo.com")
    r = cli.post("/api/painel/falhas/vinculos", json=GUATAMBU)
    assert r.status_code == 403 and r.get_json()["error"] == "somente leitura (perfil gestor)"
    assert cli.get("/api/painel/falhas/vinculos").status_code == 200
    assert cli.get("/api/painel/falhas/os?tipo=strings&usina=Guatambu&inversor=Inversor%201.2").status_code == 503
    assert "/api/painel/falhas/vinculos" in ln.GRAVACOES_GESTOR
    assert not ln.permitido_gestor("POST", "/api/painel/falhas/vinculos")
    assert ln.permitido_gestor("GET", "/api/painel/falhas/os") and ln.permitido_gestor("GET", "/api/painel/falhas/vinculos")
    # a ponte do Nexus (X-Nexus-Leitura) segue sem a aba de falhas
    assert not ln.permitido("GET", "/api/painel/falhas/os") and not ln.permitido("POST", "/api/painel/falhas/vinculos")
