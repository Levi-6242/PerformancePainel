# -*- coding: utf-8 -*-
"""Curva de strings de DIA PASSADO vazia tem de dizer POR QUÊ (Levi, 28/09/2026).

O drill do inversor da Assis Chateaubriand Skid 5 (Inversor 5.1), no dia 26/09, dizia "Sem corrente por string em
26/09/2026 — a fonte não guardou curva de strings nessa data." A PV Plataforma TINHA a curva — o Levi abriu o mesmo
relatório (`/v2/relatorios/trygenerate`, type 9) na própria PV Plataforma. Quem faltava era o token dela: vencido às
10:43 de 28/09 no servidor (no notebook, desde 23/09). Em 22/09 esse token tinha virado "reserva" (os trackers e o
combiner passaram a vir da API PV) e parou de alarmar, mas a curva de strings dos dias anteriores só existe na PV
Plataforma e depende dele. O backend até mandava "pode ser token vencido" no `msg`; a tela ignorava e culpava a fonte.
"Alarme falso não pode passar batido!"

Agora o backend diz o motivo (`motivo`, e por inversor em `faltando`), a tela só afirma que a fonte não tem quando a
fonte respondeu vazio, nunca desenha a curva de OUTRO inversor no lugar do pedido, e a tela de tokens volta a alarmar.
"""
import base64
import json as _json
import shutil as _sh
import subprocess as _sp
import time
from datetime import datetime
from pathlib import Path

import pytest as _pt

import app

_MON = (Path(__file__).resolve().parent.parent / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(
    encoding="utf-8")


def _jwt(exp):
    b64 = lambda o: base64.urlsafe_b64encode(_json.dumps(o).encode()).rstrip(b"=").decode()
    return f"{b64({'alg': 'HS256'})}.{b64({'exp': exp, 'iat': exp - 604800})}.assinatura"


class _Resp:
    def __init__(self, status, corpo=None):
        self.status_code, self._c = status, corpo

    def json(self):
        if isinstance(self._c, Exception):
            raise self._c
        return self._c


class _Http:
    def __init__(self, resp=None, erro=None):
        self.resp, self.erro, self.chamadas = resp, erro, 0

    def get(self, *a, **k):
        self.chamadas += 1
        if self.erro:
            raise self.erro
        return self.resp


# ── backend: o motivo de cada falha ──────────────────────────────────────────────────────────────────────────────

def test_token_vencido_nem_chama_a_plataforma(monkeypatch):
    """Vencido pelo exp do JWT, a recusa é certa — chamar seria uma recusa por inversor (a Assis tem dezenas)."""
    http = _Http(_Resp(200, {}))
    monkeypatch.setattr(app, "_plat_token", lambda: _jwt(time.time() - 60))
    monkeypatch.setattr(app, "_http", lambda: http)
    assert app._spv_trygenerate_st(362262, "26/09/2026") == ({}, "token_vencido")
    assert http.chamadas == 0


def test_sem_token_e_motivo_proprio(monkeypatch):
    monkeypatch.setattr(app, "_plat_token", lambda: "")
    assert app._spv_trygenerate_st(362262, "26/09/2026") == ({}, "sem_token")


@_pt.mark.parametrize("resp,erro,motivo", [
    (_Resp(401), None, "token_vencido"),            # a PV Plataforma recusa o token
    (_Resp(403), None, "token_vencido"),
    (_Resp(500), None, "http_500"),
    (None, TimeoutError("lento"), "erro_rede"),
    (_Resp(200, ValueError("não é json")), None, "resposta_invalida"),
    (_Resp(200, [1, 2]), None, "resposta_invalida"),
])
def test_cada_falha_tem_o_seu_motivo(monkeypatch, resp, erro, motivo):
    monkeypatch.setattr(app, "_plat_token", lambda: _jwt(time.time() + 3600))
    monkeypatch.setattr(app, "_http", lambda: _Http(resp, erro))
    assert app._spv_trygenerate_st(362262, "26/09/2026") == ({}, motivo)


def test_resposta_boa_vem_sem_motivo_e_o_embrulho_antigo_segue_dando_dict(monkeypatch):
    rel = {"dados_energia_dia": {"ST 01": 10.0}}
    monkeypatch.setattr(app, "_plat_token", lambda: _jwt(time.time() + 3600))
    monkeypatch.setattr(app, "_http", lambda: _Http(_Resp(200, rel)))
    assert app._spv_trygenerate_st(1, "26/09/2026") == (rel, None)
    assert app._spv_trygenerate(1, "26/09/2026") == rel
    monkeypatch.setattr(app, "_http", lambda: _Http(_Resp(500)))
    assert app._spv_trygenerate(1, "26/09/2026") == {}


def _usina(monkeypatch, invs, relatorios):
    """Histórico com inversores e relatórios simulados: relatorios = {id: (json, motivo)}."""
    monkeypatch.setattr(app, "_plat_token", lambda: _jwt(time.time() + 3600))
    monkeypatch.setattr(app, "get_plants", lambda tok: [])
    monkeypatch.setattr(app, "_spv_inversores_hist", lambda idusina, tok, nome: invs)
    monkeypatch.setattr(app, "_spv_load_notas", lambda: {})
    monkeypatch.setattr(app, "_spv_trygenerate_st", lambda idinv, data: relatorios[idinv])
    return app._spv_usina_historico(18748335, "tok", "26/09/2026", True)


def _relatorio_bom():
    serie = lambda w: [{"potencia": w, "tsleitura": f"Sat Sep 26 2026 {h:02d}:00:00 GMT"} for h in range(8, 17)]
    return {"dados_energia_dia": {"ST 01": 12.5, "ST 02": 12.1, "ST 03": 11.9},
            "dados_potencia_string": {"ST 01": serie(1500.0), "ST 02": serie(1480.0), "ST 03": serie(1450.0)}}


def test_historico_com_token_vencido_diz_o_motivo_e_quando_venceu(monkeypatch):
    venceu = datetime(2026, 9, 28, 10, 43).timestamp()          # o do servidor
    monkeypatch.setattr(app, "_plat_token", lambda: _jwt(venceu))

    def _nao_chame(*a, **k):
        raise AssertionError("com o token vencido não há por que listar inversores nem chamar a PV Plataforma")

    monkeypatch.setattr(app, "_spv_inversores_hist", _nao_chame)
    p = app._spv_usina_historico(18748335, "tok", "26/09/2026", True)
    assert p["inversores"] == [] and p["motivo"] == "token_vencido"
    assert p["token_exp"] == "28/09/2026 10:43"
    assert "token da PV Plataforma" in p["msg"]


def test_so_a_fonte_que_respondeu_vazio_e_sem_curva_na_fonte(monkeypatch):
    p = _usina(monkeypatch, [(1, "Inversor 5.1"), (2, "Inversor 5.2")], {1: ({}, None), 2: ({}, None)})
    assert p["inversores"] == [] and p["motivo"] == "sem_curva_na_fonte"
    assert {x["motivo"] for x in p["faltando"]} == {"sem_curva_na_fonte"}


def test_token_recusado_no_meio_vence_os_outros_motivos(monkeypatch):
    p = _usina(monkeypatch, [(1, "Inversor 5.1"), (2, "Inversor 5.2")], {1: ({}, "token_vencido"), 2: ({}, None)})
    assert p["motivo"] == "token_vencido"


def test_fonte_fora_nao_vira_fonte_sem_dado(monkeypatch):
    p = _usina(monkeypatch, [(1, "Inversor 5.1"), (2, "Inversor 5.2")], {1: ({}, "http_500"), 2: ({}, "erro_rede")})
    assert p["motivo"] == "erro_fonte"


def test_parcial_lista_quem_faltou(monkeypatch):
    p = _usina(monkeypatch, [(1, "Inversor 5.1"), (2, "Inversor 5.2")], {1: (_relatorio_bom(), None), 2: ({}, "http_500")})
    assert [i["nome"] for i in p["inversores"]] == ["Inversor 5.1"]
    assert p["faltando"] == [{"id": 2, "nome": "Inversor 5.2", "motivo": "http_500"}]
    assert "motivo" not in p


def test_dia_passado_com_inversor_faltando_nao_fica_no_cache_para_sempre(monkeypatch):
    """Histórico é imutável e ia para o cache "para sempre" quando vinha com inversores. Um inversor que faltou por
    falha de busca ficaria faltando mesmo depois de renovar o token."""
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    monkeypatch.setattr(app, "_spv_cache", {})
    monkeypatch.setattr(app, "_pv_token_for", lambda idusina: "tok")
    monkeypatch.setattr(app, "_spv_day_records_hist", lambda idusina, token, data: ([], "sem_dados_api"))
    chamadas = []

    def _hist(idusina, token, data, full):
        chamadas.append(data)
        return {"idusina": idusina, "data": data, "inversores": [{"id": 1, "nome": "Inversor 5.1"}],
                "faltando": [{"id": 2, "nome": "Inversor 5.2", "motivo": "token_vencido"}]}

    monkeypatch.setattr(app, "_spv_usina_historico", _hist)
    c = app.app.test_client()
    c.get("/api/spv/usina/18748335?full=1&data=26/09/2026")
    c.get("/api/spv/usina/18748335?full=1&data=26/09/2026")
    assert len(chamadas) == 2, "com inversor faltando por falha, busca de novo"
    monkeypatch.setattr(app, "_spv_usina_historico", lambda *a: {"inversores": [{"id": 1}], "faltando": [
        {"id": 2, "nome": "Inversor 5.2", "motivo": "sem_curva_na_fonte"}]})
    c.get("/api/spv/usina/18748335?full=1&data=25/09/2026")
    monkeypatch.setattr(app, "_spv_usina_historico", lambda *a: (_ for _ in ()).throw(AssertionError("não re-busca")))
    assert c.get("/api/spv/usina/18748335?full=1&data=25/09/2026").get_json()["inversores"] == [{"id": 1}]


# ── a tela de tokens ─────────────────────────────────────────────────────────────────────────────────────────────

def _linha_plat():
    return next(r for r in app._tokens_status()["tokens"] if r["fonte"] == "plat")


def test_token_da_plataforma_vencido_volta_a_alarmar(monkeypatch):
    monkeypatch.setattr(app, "_plat_token", lambda: _jwt(time.time() - 60))
    st = app._tokens_status()
    assert _linha_plat()["status"] == "vencido" and st["alerta"]
    assert "dias anteriores" in _linha_plat()["nome"]


def test_token_da_plataforma_so_avisa_no_ultimo_dia(monkeypatch):
    """Vale 7 dias: com o aviso de 3 dias da regra geral, ele ficaria amarelo quase metade do tempo."""
    monkeypatch.setattr(app, "_plat_token", lambda: _jwt(time.time() + 2 * 86400))
    assert _linha_plat()["status"] == "ok"
    monkeypatch.setattr(app, "_plat_token", lambda: _jwt(time.time() + 12 * 3600))
    assert _linha_plat()["status"] == "atencao"


# ── a tela: o que ela diz e qual inversor ela desenha ─────────────────────────────────────────────────────────────

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
    base = (_func("_curvaDoInversor") + _func("_curvaMotivo") + _func("_curvaMotivoTxt") + _linha("_curvaMotivoCor")
            + _func("_curvaMotivoApiTxt") + _linha("_curvaUnidade")
            + "const _he=s=>String(s==null?'':s);")
    p = _sp.run([node, "-e", base + js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return _json.loads(p.stdout)


def test_a_frase_do_token_vencido_culpa_o_acesso_nao_a_fonte():
    t = _node("process.stdout.write(JSON.stringify(_curvaMotivoTxt('token_vencido','26/09/2026','28/09/2026 10:43','inversor')))")
    assert "vencido desde 28/09/2026 10:43" in t and "PV Plataforma" in t and 'href="/tokens"' in t
    assert "não guardou" not in t
    cor = _node("process.stdout.write(JSON.stringify(_curvaMotivoCor('token_vencido')))")
    assert cor == "#f59e0b", "dá para agir: âmbar"


def test_so_a_fonte_que_respondeu_vazio_diz_que_a_fonte_nao_tem():
    t = _node("process.stdout.write(JSON.stringify([_curvaMotivoTxt('sem_curva_na_fonte','26/09/2026',null,'inversor'),"
              "_curvaMotivoTxt('http_502','26/09/2026',null,'inversor'), _curvaMotivoTxt(null,'26/09/2026',null,'inversor')]))")
    assert "respondeu, mas sem curva" in t[0] and t[0].startswith("A PV Plataforma")
    assert "não respondeu" in t[1] and "HTTP 502" in t[1]
    assert t[2] is None, "sem motivo, a tela usa as frases de sempre (fontes que não mandam motivo)"


def test_a_curva_nunca_e_a_de_outro_inversor():
    r = _node("const L=[{nome:'Inversor 5.2',id:'b',curva:{x:1}},{nome:'Inversor 5.3',id:'c',curva:{x:1}}];"
              "process.stdout.write(JSON.stringify(["
              "_curvaDoInversor(L,true,'Inversor 5.1','a',0),"                      # pedido fora da lista: NADA
              "_curvaDoInversor([L[0]],true,'Inversor 5.1','a',1),"                 # item único, mas outro faltou: NADA
              "_curvaDoInversor([L[0]],false,'x','z',0),"                           # ?inv= já filtrou: vale
              "_curvaDoInversor(L,true,'Inversor 5.3','c',0).nome]))")
    assert r == [None, None, {"nome": "Inversor 5.2", "id": "b", "curva": {"x": 1}}, "Inversor 5.3"]


def test_o_motivo_do_inversor_vem_do_faltando():
    r = _node("process.stdout.write(JSON.stringify(["
              "_curvaMotivo({faltando:[{nome:'Inversor 5.1',motivo:'http_500'}]},[{nome:'Inversor 5.2',curva:{a:1}}],null,'Inversor 5.1'),"
              "_curvaMotivo({motivo:'token_vencido',token_exp:'28/09/2026 10:43'},[],null,'Inversor 5.1'),"
              "_curvaMotivo({},[{nome:'Inversor 5.2',curva:{a:1}}],null,'Inversor 5.1'),"
              "_curvaMotivo({motivo:'token_vencido'},[],{curva:{a:{x:[],y:[]}}},'Inversor 5.1')]))")
    assert r[0]["motivo"] == "http_500"
    assert r[1] == {"motivo": "token_vencido", "token_exp": "28/09/2026 10:43", "motivo_api": None}
    assert r[2]["motivo"] == "inversor_ausente"
    assert r[3] == {}, "com curva, não há motivo de vazio"


def _bloco(curva, meta, strings=(), hoje="2026-09-28", dia="2026-09-26"):
    node = _sh.which("node")
    if not node:
        _pt.skip("node não instalado")
    js = (_func("_curvaMotivoTxt") + _linha("_curvaMotivoCor") + _func("_curvaMotivoApiTxt") + _linha("_curvaUnidade")
          + _func("_curvaBlock")
          + "const _he=s=>String(s==null?'':s);"
          "function _snum(s){ const d=String(s==null?'':s).replace(/\\D/g,''); return d?parseInt(d,10):null; }"
          "const state={source:'thopen-pv',invData:" + _json.dumps(dia) + "}; const SKEY={'thopen-pv':'pv'};"
          "const _todayISO=()=>" + _json.dumps(hoje) + "; const _invIso=()=>state.invData;"
          "const _brdate=iso=>iso.slice(8,10)+'/'+iso.slice(5,7)+'/'+iso.slice(0,4);"
          "const _ckey=(pid,inv)=>pid+'|'+inv;"
          "const RD={pv:{rows:[]},curva:{'10|11':" + _json.dumps(curva) + "},curvaMeta:{'10|11':" + _json.dumps(meta) + "}};"
          "process.stdout.write(JSON.stringify(_curvaBlock({pid:'10',invId:'11',strings:" + _json.dumps(list(strings)) + "})));")
    p = _sp.run([node, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return _json.loads(p.stdout)


def test_o_drill_do_inversor_diz_token_vencido_em_vez_de_culpar_a_fonte():
    """O caso do print: Assis Chateaubriand Skid 5, Inversor 5.1, 26/09."""
    h = _bloco({}, {"motivo": "token_vencido", "token_exp": "28/09/2026 10:43"})
    assert "vencido desde 28/09/2026 10:43" in h and "26/09/2026" in h
    assert "não guardou" not in h


def test_o_drill_com_todas_as_strings_trancadas_nao_diz_que_a_fonte_nao_guardou():
    h = _bloco({"ST 01": {"x": ["10:00"], "y": [1.0]}}, {}, strings=[{"name": "Ipv1", "trancada": True}])
    assert "trancadas" in h and "não guardou" not in h


def test_o_drill_so_diz_que_a_fonte_nao_tem_quando_ela_respondeu_vazio():
    h = _bloco({}, {"motivo": "sem_curva_na_fonte"})
    assert "respondeu, mas sem curva" in h and "não guardou" not in h
