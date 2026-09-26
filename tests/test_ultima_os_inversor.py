# -*- coding: utf-8 -*-
"""Última OS no drill do inversor (Levi, 25/09/2026, item 1 da lista: "Última OS de performance com filtro para último
religamento, último chamado (se tiver) mostrando a OS" — no drill do inversor).

Três fichas, pelas marcas que o Fracttal já dá em cada OS (REST que a plataforma usa, conferido em 25/09):
  - PERFORMANCE: etiqueta "PERFORMANCE" — o OS Creator põe em toda OS de performance (Santarém 1, Inversor 1.1:
    #12097 "[Inversor 1.1] - Recomposição de String", etiqueta verde PERFORMANCE);
  - RELIGAMENTO: tipo "Religamento" ou "Religamento Remoto" — costuma estar no ativo da USINA (a cabine desarma), então
    vale a mais nova entre a do inversor e a da usina, dizendo de qual veio;
  - CHAMADO: etiqueta "CHAMADOS" (o chamado de garantia nasce no mesmo ativo, com a OS de origem como pai).
Cancelada (status 4) nunca conta. O nº abre a OS no OS Creator web (/os/os/folio/<nº>, pelo proxy da plataforma).
"""
import app


def _wo(folio, tipo, st, ev, labels=(), desc="x"):
    return {"wo_folio": folio, "tasks_log_task_type_main": tipo, "id_status_work_order": st,
            "event_date": ev, "creation_date": ev, "description": desc,
            "labels": [{"id": 1, "description": etq} for etq in labels]}


INV = [_wo("12097", "Corretiva", 2, "2026-08-24T18:00:00+00:00", ["PERFORMANCE"], "[Inversor 1.1] - Recomposição de String"),
       _wo("9876", "Corretiva", 2, "2026-07-22T18:00:00+00:00", ["PERFORMANCE"]),
       _wo("12500", "Corretiva", 1, "2026-09-01T12:00:00+00:00", ["CHAMADOS"], "[Ticket 77][Santarém 1][Inversor 1.1] - TCU"),
       _wo("13000", "Preventiva", 2, "2026-09-10T12:00:00+00:00")]
SITE = [_wo("13400", "Religamento Remoto", 2, "2026-09-20T15:30:00+00:00", desc="UFV Santarém 1 - Religamento remoto"),
        _wo("8000", "Religamento", 2, "2026-06-01T15:30:00+00:00")]


def test_cada_ficha_pega_a_mais_recente_da_sua_marca():
    u = app._frac_ultimas_os(INV, SITE)
    p, r, c = u["performance"], u["religamento"], u["chamado"]
    assert p["folio"] == "12097" and p["escopo"] == "inversor" and p["status"] == "Concluída"
    assert p["descricao"] == "[Inversor 1.1] - Recomposição de String" and p["link"] == "/os/os/folio/12097"
    assert r["folio"] == "13400" and r["escopo"] == "usina" and r["tipo"] == "Religamento Remoto"
    assert c["folio"] == "12500" and c["aberta"] is True and c["status"] == "Em andamento"


def test_religamento_do_proprio_inversor_ganha_quando_e_o_mais_novo():
    inv = INV + [_wo("13500", "Religamento", 2, "2026-09-22T09:00:00+00:00")]
    r = app._frac_ultimas_os(inv, SITE)["religamento"]
    assert r["folio"] == "13500" and r["escopo"] == "inversor"


def test_evento_sai_na_hora_local():
    """O Fracttal manda UTC: 15:30Z é 12:30 aqui."""
    assert app._frac_ultimas_os(INV, SITE)["religamento"]["evento"] == "2026-09-20 12:30"


def test_cancelada_nunca_conta():
    inv = [_wo("200", "Corretiva", 4, "2026-09-24T12:00:00+00:00", ["PERFORMANCE"])] + INV
    assert app._frac_ultimas_os(inv, [])["performance"]["folio"] == "12097"


def test_sem_a_marca_a_ficha_fica_vazia():
    u = app._frac_ultimas_os([_wo("1", "Preventiva", 2, "2026-09-01T12:00:00+00:00")], [])
    assert u == {"performance": None, "religamento": None, "chamado": None}


def test_rota_devolve_as_tres_fichas(monkeypatch):
    monkeypatch.setattr(app, "FRACTTAL_ON", True)
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    monkeypatch.setattr(app, "_frac_inv_code", lambda usina, inv: "STR100-INVR1.1")
    monkeypatch.setattr(app, "_frac_ativo", lambda code: {"id": 11, "code": code, "desc": "Inversor 1.1"})
    monkeypatch.setattr(app, "_frac_usina_ent", lambda usina: {"cb": "STR100", "site": 22})
    monkeypatch.setattr(app, "_frac_wos_raw", lambda i: {11: INV, 22: SITE}[i])
    d = app.app.test_client().get("/api/fracttal/ultima-os?usina=Santarém 1&inv=Inversor 1.1").get_json()
    assert d["ok"] is True and d["code"] == "STR100-INVR1.1"
    assert (d["performance"]["folio"], d["religamento"]["folio"], d["chamado"]["folio"]) == ("12097", "13400", "12500")


def test_rota_sem_ativo_no_fracttal(monkeypatch):
    monkeypatch.setattr(app, "FRACTTAL_ON", True)
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    monkeypatch.setattr(app, "_frac_inv_code", lambda usina, inv: "XXX100-INVR9.9")
    monkeypatch.setattr(app, "_frac_ativo", lambda code: None)
    d = app.app.test_client().get("/api/fracttal/ultima-os?usina=X&inv=Inversor 9.9").get_json()
    assert d["ok"] is False and d["sem_ativo"] is True and d["code"] == "XXX100-INVR9.9"


def test_rota_sem_credencial(monkeypatch):
    monkeypatch.setattr(app, "FRACTTAL_ON", False)
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    d = app.app.test_client().get("/api/fracttal/ultima-os?usina=X&inv=Inversor 1.1").get_json()
    assert d["ok"] is False and d["sem_credencial"] is True


# ── a tela ────────────────────────────────────────────────────────────────────
import json as _json
import pathlib as _pl
import shutil as _sh
import subprocess as _sp

import pytest as _pt

_MON = (_pl.Path(app.__file__).resolve().parents[1] / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")


def _func(nome, fim="\n}\n"):
    i = _MON.index(f"function {nome}(")
    return _MON[i:_MON.index(fim, i) + len(fim)]


def test_abrir_o_inversor_busca_a_ultima_os():
    tog = _MON[_MON.index("window.toggleInversor="):]
    assert "loadUltimaOs(" in tog[:tog.index("\n")]
    assert "/api/fracttal/ultima-os?usina=" in _func("loadUltimaOs")
    assert "${_ultOsBlock(inv)}" in _MON, "o bloco entra no inversor aberto"


def _render(dado, aba):
    node = _sh.which("node")
    if not node:
        _pt.skip("node não instalado")
    js = (_func("_ultOsBlock") + "const _he=s=>String(s==null?'':s);"
          "const _ULTOS_ABAS=[['performance','Performance'],['religamento','Religamento'],['chamado','Chamado']];"
          "const RD={ultOs:{'10|11':" + _json.dumps(dado, ensure_ascii=False) + "}};"
          "const state={ultOsAba:" + _json.dumps(aba) + "};"
          "process.stdout.write(JSON.stringify(_ultOsBlock({isReal:true,pid:'10',invId:'11'})));")
    p = _sp.run([node, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return _json.loads(p.stdout)


def test_a_ficha_mostra_o_numero_que_abre_a_os():
    d = {"ok": True, **app._frac_ultimas_os(INV, SITE)}
    h = _render(d, "performance")
    assert 'href="/os/os/folio/12097"' in h and "Recomposição de String" in h and "Concluída" in h
    h = _render(d, "religamento")
    assert "13400" in h and "OS da usina" in h


def test_sem_os_da_marca_diz_isso():
    h = _render({"ok": True, "performance": None, "religamento": None, "chamado": None}, "chamado")
    assert "Nenhum chamado" in h


def test_inversor_fora_do_fracttal_diz_isso():
    assert "sem ativo no Fracttal" in _render({"ok": False, "sem_ativo": True, "code": "XXX100-INVR9.9"}, "performance")
