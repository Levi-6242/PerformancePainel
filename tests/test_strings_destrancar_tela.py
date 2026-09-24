# -*- coding: utf-8 -*-
"""Destrancar string pelo cadeado reflete NA HORA (Levi, 23/09/2026).

O relato: *"Quando eu vou destrancar uma string pelo ícone de cadeado não destranca imediatamente, eu tenho que atualizar
a página para ver que destrancou, porém quando eu tranco já aparece trancado"* (Inversor 6.1, 12 trancadas).

A causa: para a string trancada o servidor manda status "trancada" (`_classifica_strings`), e o status real some do
payload. Trancar é só ligar a trava — "trancada" vale qualquer que seja o status —, mas destrancar precisa do status que
a string TERIA, e a tela não tinha: o chip ficava azul até recarregar. E a curva do dia também vinha do servidor SEM a
string (ele tira as trancadas da curva), então ela não voltava ao gráfico.

A tela passa a recalcular a string destrancada com a MESMA régua do `_classifica_strings`. O teste de paridade roda as
duas contas, a do Python e a do JS da página (no node), nas mesmas correntes.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
MON = (RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")
NODE = shutil.which("node")


def _trecho(ini, fim):
    i = MON.index(ini)
    return MON[i:MON.index(fim, i) + len(fim)]


def _node(js):
    if not NODE:
        pytest.skip("node não instalado")
    p = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def _js_reclassifica(inv, ids):
    return _node("\n".join([_trecho("const STR_SEM_CORRENTE_A=", "/* fim _strReclassifica */"),
                            "process.stdout.write(JSON.stringify(_strReclassifica(%s,%s)));" % (json.dumps(inv),
                                                                                                 json.dumps(ids))]))


def _servidor(monkeypatch, correntes, trancadas):
    """O status de cada string segundo o servidor, com as de índice em `trancadas` trancadas."""
    keys = ["Ipv%d" % (i + 1) for i in range(len(correntes))]
    monkeypatch.setattr(app, "_trancadas", {app._str_key("P", "I", keys[i]) for i in trancadas})
    return dict(zip(keys, app._classifica_strings("P", "I", keys, correntes)))


# (correntes em A, índices trancados antes, índices destrancados agora)
CASOS = [
    ([8.1, 0.0, 0.0, 8.0, 3.0, 8.2], {1, 2}, [1]),        # morta ao lado de strings produzindo → sem_corrente
    ([8.1, 7.9, 8.0, 2.0], {1}, [1]),                      # destrancar uma que produz → ativa, e ela entra na mediana
    ([8.0, 8.0, 4.0], {2}, [2]),                           # abaixo de 60% da mediana → baixa_perf
    ([0.05, 0.0, 0.1, 0.3], {1}, [1]),                     # inversor parado (noite, nublado) → inativa, não é falha
    ([8.1, 0.0, 0.0, 0.0, 8.0], {1, 2, 3}, [1, 2, 3]),    # "Destrancar todas" de uma vez
    ([0.0, 0.0], {0, 1}, [0]),                             # tudo trancado: sem referência → inativa
]


@pytest.mark.parametrize("correntes,antes,agora", CASOS)
def test_destrancar_recalcula_igual_ao_servidor(monkeypatch, correntes, antes, agora):
    keys = ["Ipv%d" % (i + 1) for i in range(len(correntes))]
    chegou = _servidor(monkeypatch, correntes, antes)             # o payload como a tela recebeu
    inv = {"strings": [{"id": k, "corrente": c, "status": chegou[k], "trancada": chegou[k] == "trancada",
                        "ativa": chegou[k] in ("ativa", "baixa_perf")} for k, c in zip(keys, correntes)]}
    alvos = [keys[i] for i in agora]
    for i in agora:                                               # o que o clique faz antes de recalcular
        inv["strings"][i]["trancada"] = False
    esperado = _servidor(monkeypatch, correntes, set(antes) - set(agora))
    out = {s["id"]: s for s in _js_reclassifica(inv, alvos)["strings"]}
    for k in alvos:
        assert out[k]["status"] == esperado[k], (k, out[k]["status"], esperado[k])
        assert out[k]["ativa"] == (esperado[k] in ("ativa", "baixa_perf"))
    for k in keys:
        if k not in alvos:
            assert out[k]["status"] == chegou[k], "as outras ficam como o servidor mandou"


def test_inversor_desligado_a_destrancada_fica_desligada_como_as_outras():
    """Inversor parado de dia: o servidor pinta de "desligado" toda string que não está trancada (_pv_plant_inversores,
    _sunop_plant_build, PG), e a corrente reversa residual (0,8–1 A) não conta como produção. A destrancada entra junto."""
    inv = {"strings": [{"id": "Ipv1", "corrente": 0.9, "status": "desligado", "trancada": False, "ativa": False},
                       {"id": "Ipv2", "corrente": 0.0, "status": "trancada", "trancada": False, "ativa": False},
                       {"id": "Ipv3", "corrente": 0.8, "status": "desligado", "trancada": False, "ativa": False}]}
    s = _js_reclassifica(inv, ["Ipv2"])["strings"][1]
    assert (s["status"], s["ativa"]) == ("desligado", False)


def test_os_limites_da_tela_sao_os_do_servidor():
    """Mudou o limite no app.py e não na página, a tela volta a mentir até recarregar."""
    for js, py in (("STR_SEM_CORRENTE_A", "STRING_SEM_CORRENTE_A"), ("STR_BAIXA_PERF_FRAC", "STRING_BAIXA_PERF_FRAC"),
                   ("STR_INV_MIN_MED_A", "STRING_INV_MIN_MED_A")):
        m = re.search(r"\b%s=([0-9.]+)" % js, MON)
        assert m and float(m.group(1)) == getattr(app, py), js


def _corpo(ini):
    i = MON.index(ini)
    return MON[i:MON.index("\n};", i)]


def test_o_cadeado_recalcula_ao_destrancar_e_desfaz_tudo_se_falhar():
    corpo = _corpo("window.trancarString=")
    assert "if(!trancar) _strReclassifica(inv,[sid])" in corpo
    assert "_curvaRecarrega(pid,invId,inv.nome)" in corpo
    assert "Object.assign(st,antes)" in corpo, "o servidor recusou: volta a trava E o status de antes"
    corpo = _corpo("window.destrancarTodas=")
    assert "_strReclassifica(inv,ids)" in corpo and "_curvaRecarrega(pid,invId,inv.nome)" in corpo
    assert "antes.forEach(" in corpo


def _recarrega(curvas, **kw):
    """Roda o _curvaRecarrega com um loadCurva de mentira que só anota a chamada."""
    js = "\n".join([
        "const state={source:'thopen-pv',invData:%s}; const _todayISO=()=>'2026-09-23';" % json.dumps(kw.get("dia")),
        "const RD={curva:%s,curvaMeta:{}}; const chamadas=[];" % json.dumps(curvas),
        "function loadCurva(){ chamadas.push([...arguments]); }",
        _trecho("function _invIso(", "\n"), _trecho("function _ckey(", "\n"),
        _trecho("function _curvaRecarrega(", "/* fim _curvaRecarrega */"),
        "_curvaRecarrega('90','6.1','Inversor 6.1');",
        "process.stdout.write(JSON.stringify({chaves:Object.keys(RD.curva).sort(),chamadas}));"])
    return _node(js)


def test_destrancou_a_curva_e_buscada_de_novo_sem_apagar_a_da_tela():
    """O servidor tira a string trancada da curva: a curva guardada não tem a série dela. Esquece a do inversor nas
    outras datas e busca a do dia de novo — com a atual na tela até a nova chegar (sem piscar "Carregando curva…")."""
    k = "thopen-pv|90|6.1|"
    r = _recarrega({k + "2026-09-23": {"I_PV2": {}}, k + "2026-09-20": {}, "thopen-pv|90|6.2|2026-09-23": {}})
    assert r["chaves"] == ["thopen-pv|90|6.1|2026-09-23", "thopen-pv|90|6.2|2026-09-23"]
    assert r["chamadas"] == [["90", "6.1", "Inversor 6.1", True]]
    assert _recarrega({})["chamadas"] == [], "curva nunca aberta: nada a buscar"


def test_loadcurva_refazendo_nao_mostra_carregando_nem_troca_por_erro():
    i = MON.index("async function loadCurva(")
    corpo = MON[i:MON.index("\n}", i)]
    assert "if(RD.curva[key]!==undefined&&!refazer) return;" in corpo
    assert "if(!refazer){ RD.curva[key]=null; render(); }" in corpo
    assert "if(!refazer){ RD.curva[key]={}; RD.curvaMeta[key]={abaixo:new Set(),erro:1}; }" in corpo, \
        "busca de fundo que falha mantém a curva que já estava na tela"
