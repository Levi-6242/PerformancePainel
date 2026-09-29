# -*- coding: utf-8 -*-
"""Curva de strings de DIA PASSADO: corrente pela API PV quando ela tem o histórico, potência quando não tem.

Levi, 28/09/2026: "essa curva de strings não pega da API?" e, com o teste em mãos, "SE TIVER HISTÓRICO DE CORRENTE,
DEIXA CORRENTE, SE NÃO TIVER PEGA POTÊNCIA". Até ali o dia passado ia só para a PV Plataforma (potência, token manual
de 7 dias), por causa de um teste de 15/06 que voltou "Sem dados" — feito na Matão 1, que parara de reportar em 12/06.
Medido em 28/09 na Assis Chateaubriand Skid 5, dia 26/09: o custom_query v2 da API PV com o dia devolve a usina inteira
em 5,3 s (4 inversores × 1.440 leituras, Ipv no conteudojson) e as 6 strings zeradas do Inversor 5.1 são as da tela.
"""
import json as _json
import shutil as _sh
import subprocess as _sp
from pathlib import Path

import pytest as _pt

import app

_MON = (Path(__file__).resolve().parent.parent / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(
    encoding="utf-8")


class _Resp:
    def __init__(self, status, corpo=None, headers=None):
        self.status_code, self._c, self.headers = status, corpo, headers or {}

    def json(self):
        if isinstance(self._c, Exception):
            raise self._c
        return self._c


class _Http:
    def __init__(self, resp=None, erro=None):
        self.resp, self.erro, self.posts = resp, erro, []

    def post(self, url, **k):
        self.posts.append((url, k.get("json")))
        if self.erro:
            raise self.erro
        return self.resp

    def get(self, *a, **k):              # plant_devices: sem nomes (a tela casa por INV-<id>)
        raise ConnectionError("sem plant_devices no teste")


def _rec(inv, hhmm, ipvs, dia="2026-09-26"):
    return {"idefinversor": inv, "tsleitura_new": f"{dia} {hhmm}:00", "tsleitura": f"{dia} {hhmm}:00",
            "dataleitura": dia, "conteudojson": _json.dumps(ipvs)}


def _dia_de_strings(inv, correntes, dia="2026-09-26"):
    """Um registro por hora, das 06 às 18, com a corrente de cada Ipv seguindo o sol (pico ao meio-dia)."""
    out = []
    for h in range(6, 19):
        f = max(0.0, 1 - abs(h - 12) / 6)
        out.append(_rec(inv, f"{h:02d}:00", {f"Ipv{i + 1}": round(c * f, 2) for i, c in enumerate(correntes)}, dia))
    return out


@_pt.fixture
def _limpa(monkeypatch):
    monkeypatch.setattr(app, "_spv_hist_recs", {})
    monkeypatch.setattr(app, "_pv_cota", {"dia": None, "hora": None, "ts": 0.0, "zerada_ate": 0.0})
    monkeypatch.setattr(app, "_trancadas", set())


# ── a busca na API PV ────────────────────────────────────────────────────────────────────────────────────────────

def test_busca_o_dia_na_v2_com_period_e_day_e_guarda(monkeypatch, _limpa):
    recs = _dia_de_strings(362262, [10.0, 12.0]) + [_rec(362262, "10:00", {"Ipv1": 1}, dia="2026-09-25")]
    http = _Http(_Resp(200, recs, {"X-RateLimit-Remaining-Day": "578", "X-RateLimit-Remaining-Hour": "181"}))
    monkeypatch.setattr(app, "_http", lambda: http)
    got, motivo = app._spv_day_records_hist(18748335, "tok", "26/09/2026")
    assert motivo is None and len(got) == 13, "só os registros do dia pedido"
    url, body = http.posts[0]
    assert url.endswith("/api/v2/custom_query")
    assert body == {"id": 18748335, "data_type": "inverter", "period": "202609", "day": 26}
    assert app._pv_cota["dia"] == 578, "a cota lida nos cabeçalhos vale para a combiner também"
    app._spv_day_records_hist(18748335, "tok", "26/09/2026")
    assert len(http.posts) == 1, "dia passado não muda: o 2º pedido (o CSV depois do drill) não gasta cota"


def test_sem_cota_nem_chama(monkeypatch, _limpa):
    http = _Http(_Resp(200, []))
    monkeypatch.setattr(app, "_http", lambda: http)
    monkeypatch.setattr(app, "_pv_cota_permite", lambda: False)
    assert app._spv_day_records_hist(1, "tok", "26/09/2026") == ([], "cota_api")
    assert http.posts == []


@_pt.mark.parametrize("resp,erro,motivo", [
    (_Resp(429, {}), None, "cota_api"),
    (_Resp(502, ValueError("html")), None, "http_502"),
    (None, TimeoutError("lento"), "erro_rede"),
    (_Resp(200, {"message": "Invalid permission"}), None, "resposta_invalida"),
    (_Resp(200, []), None, "sem_dados_api"),
])
def test_cada_falha_da_api_tem_motivo(monkeypatch, _limpa, resp, erro, motivo):
    monkeypatch.setattr(app, "_http", lambda: _Http(resp, erro))
    assert app._spv_day_records_hist(1, "tok", "26/09/2026") == ([], motivo)


# ── a rota: corrente primeiro, potência só onde faltar ───────────────────────────────────────────────────────────

def _rota(monkeypatch, recs_api, motivo_api=None):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    monkeypatch.setattr(app, "_spv_cache", {})
    monkeypatch.setattr(app, "_pv_token_for", lambda idusina: "tok")
    monkeypatch.setattr(app, "get_token", lambda: "tok")
    monkeypatch.setattr(app, "get_plants", lambda tok: [])
    monkeypatch.setattr(app, "_spv_load_notas", lambda: {})
    monkeypatch.setattr(app, "_http", lambda: _Http())
    monkeypatch.setattr(app, "_spv_day_records_hist", lambda idusina, token, data: (recs_api, motivo_api))
    return app.app.test_client()


def test_dia_passado_com_corrente_na_api_vem_em_corrente_e_sem_a_plataforma(monkeypatch, _limpa):
    recs = _dia_de_strings(362262, [10.0, 12.0, 11.0]) + _dia_de_strings(362263, [9.0, 9.5, 10.0])
    c = _rota(monkeypatch, recs)
    monkeypatch.setattr(app, "_spv_usina_historico", lambda *a: (_ for _ in ()).throw(AssertionError("não vai à reserva")))
    monkeypatch.setattr(app, "_spv_trygenerate_st", lambda *a: (_ for _ in ()).throw(AssertionError("não vai à reserva")))
    d = c.get("/api/spv/usina/18748335?full=1&data=26/09/2026").get_json()
    assert d["historico"] == "api_pv" and d["unidade"] == "corrente"
    assert sorted(i["id"] for i in d["inversores"]) == [362262, 362263]
    assert all(i["unidade"] == "corrente" for i in d["inversores"])
    assert (18748335, "26/09/2026", True) in app._spv_cache, "completo: fica no cache para sempre"


def test_inversor_sem_corrente_cai_na_potencia_e_os_outros_ficam_em_corrente(monkeypatch, _limpa):
    """A regra vale POR INVERSOR: usina com um inversor de String Box (sem Ipv na API PV) não perde a corrente dos outros."""
    from test_curva_strings_motivo import _relatorio_bom
    recs = _dia_de_strings(362262, [10.0, 12.0, 11.0]) + [_rec(362263, "12:00", {"Pac": 50000})]
    c = _rota(monkeypatch, recs)
    monkeypatch.setattr(app, "_spv_trygenerate_st", lambda idinv, data: (_relatorio_bom(), None))
    d = c.get("/api/spv/usina/18748335?full=1&data=26/09/2026").get_json()
    un = {i["id"]: i["unidade"] for i in d["inversores"]}
    assert un == {362262: "corrente", 362263: "potencia"} and d["unidade"] == "misto"


def test_sem_nada_na_api_a_usina_inteira_vai_para_a_potencia_e_diz_por_que(monkeypatch, _limpa):
    c = _rota(monkeypatch, [], "http_502")
    monkeypatch.setattr(app, "_spv_usina_historico", lambda idusina, token, data, full: {
        "idusina": idusina, "data": data, "inversores": [], "motivo": "token_vencido", "token_exp": "28/09/2026 10:43"})
    d = c.get("/api/spv/usina/18748335?full=1&data=26/09/2026").get_json()
    assert d["motivo"] == "token_vencido" and d["motivo_api"] == "http_502"


def test_csv_do_dia_passado_sai_em_corrente_quando_a_api_tem(monkeypatch, _limpa):
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "tok")
    monkeypatch.setattr(app, "get_token", lambda: "tok")
    monkeypatch.setattr(app, "get_plants", lambda tok: [])
    monkeypatch.setattr(app, "_pv_dev_names", lambda pid, tok: {362262: "Inversor 5.1"})
    monkeypatch.setattr(app, "_spv_day_records_hist", lambda pid, tok, data: (_dia_de_strings(362262, [10.0, 12.0]), None))
    monkeypatch.setattr(app, "_pv_curvas_strings_hist", lambda *a: (_ for _ in ()).throw(AssertionError("tem corrente")))
    rows, unidade = app._strings_curva_longo("pv", "18748335", "2026-09-26")
    assert unidade == "corrente_A" and rows and rows[0][0] == "Inversor 5.1"
    monkeypatch.setattr(app, "_spv_day_records_hist", lambda pid, tok, data: ([], "sem_dados_api"))
    monkeypatch.setattr(app, "_pv_curvas_strings_hist", lambda *a: {"Inversor 5.1": {"Ipv1": [("12:00", 1500.0)]}})
    rows, unidade = app._strings_curva_longo("pv", "18748335", "2026-09-26")
    assert unidade == "potencia_W", "sem corrente na API PV, a reserva em potência"


# ── a tela ───────────────────────────────────────────────────────────────────────────────────────────────────────

def _func(nome, fim="\n}\n"):
    i = _MON.index(f"function {nome}(")
    return _MON[i:_MON.index(fim, i) + len(fim)]


def _linha(nome):
    i = _MON.index(f"function {nome}(")
    return _MON[i:_MON.index("\n", i) + 1]


def _node(js):
    node = _sh.which("node")
    if not node:
        _pt.skip("node não instalado")
    base = (_linha("_curvaUnidade") + _func("_curvaMotivoApiTxt") + _func("_curvaMotivoTxt")
            + "const _he=s=>String(s==null?'':s);")
    p = _sp.run([node, "-e", base + js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return _json.loads(p.stdout)


def test_a_unidade_do_grafico_vem_da_resposta():
    r = _node("process.stdout.write(JSON.stringify([_curvaUnidade('pv','corrente'),_curvaUnidade('pv','potencia'),"
              "_curvaUnidade('pv',null),_curvaUnidade('solaredge',null)]))")
    assert r == ["A", "W", "A", "W"], "a potência da reserva não pode sair com eixo de corrente"


def test_a_frase_diz_por_que_a_api_nao_trouxe_e_que_a_reserva_esta_sem_token():
    t = _node("process.stdout.write(JSON.stringify(_curvaMotivoTxt('token_vencido','26/09/2026','28/09/2026 10:43','inversor','http_502')))")
    assert "A API PV não respondeu (HTTP 502)" in t and "reserva em potência" in t and "vencido desde 28/09/2026 10:43" in t


def test_o_drill_e_a_aba_usam_a_unidade_da_resposta():
    bloco = _func("_curvaBlock")
    assert "_curvaUnidade(SKEY[state.source],(RD.curvaMeta[key]||{}).unidade)" in bloco
    assert "curvaSVG(iv.curva,smap,state.curvaRed,_curvaUnidade(f,iv.unidade))" in _MON
