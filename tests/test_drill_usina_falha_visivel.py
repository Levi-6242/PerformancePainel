# -*- coding: utf-8 -*-
"""Abrir uma usina e a fonte não responder não pode virar "usina sem inversores" (Levi, 30/09/2026, Guatambu 2 na API
PV: "fica 'carregando inversores...' aí eu fico esperando um tempo e do nada o nome some e não carrega nada!
intankável").

A busca passou dos 90 s da tela com a API PV lenta. O `loadPlant` guardava [] calado no catch (e também quando a rota
devolvia 504 com {"error"}), a linha ficava em branco e reabrir não tentava de novo — `RD.plants` só se esvazia
recarregando a página. Agora: aos 10 s a linha diz que está esperando; a falha diz o motivo, com "Tentar de novo"; e a
falha não fica guardada (reabrir a usina tenta outra vez). Usina que a fonte devolveu sem inversor diz isso."""
import json
import pathlib
import shutil
import subprocess

import pytest

MON = (pathlib.Path(__file__).resolve().parents[1] / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(
    encoding="utf-8")


def _func(nome, prefixo="function "):
    i = MON.index(prefixo + nome + "(")
    return MON[i:MON.index("\n}\n", i) + 3]


def _node(js):
    node = shutil.which("node")
    if not node:
        pytest.skip("node não instalado")
    base = (_func("loadPlant", "async function ") + _func("_invCarregando") + _func("_invErro") + _func("_invVazio")
            + "const state={source:'thopen-pv'}; const SKEY={'thopen-pv':'pv'}; const PLANT={pv:'/api/plant/'};"
              "const RD={plants:{},plantErro:{},plantLento:{}}; const render=()=>{};"
              "const _he=s=>String(s==null?'':s).replace(/</g,'&lt;'); const urls=[]; let resp=null, solta=null;"
              "async function fetchJSON(u,o){ urls.push(u); if(o&&o.onLento) o.onLento();"
              " if(solta) await new Promise(r=>{ solta=r; });"
              " if(resp instanceof Error) throw resp; return resp; }")
    p = subprocess.run([node, "-e", base + js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_a_falha_diz_o_motivo_e_tem_tentar_de_novo():
    r = _node("(async()=>{ resp=new Error('a fonte não respondeu em 90s'); await loadPlant(18747509);"
              " const k='thopen-pv|18747509', e1=_invErro(18747509), inv1=RD.plants[k];"
              " resp={plant_id:18747509,inversores:[{id:1,nome:'Inversor 1.1'}]}; await loadPlant(18747509);"
              " process.stdout.write(JSON.stringify({e1, inv1, urls, inv2:RD.plants[k], e2:_invErro(18747509)})); })();")
    assert "Não consegui carregar os inversores" in r["e1"] and "a fonte não respondeu em 90s" in r["e1"]
    assert "Tentar de novo" in r["e1"] and "loadPlant('18747509')" in r["e1"]
    assert r["inv1"] == []
    assert len(r["urls"]) == 2, "reabrir depois da falha tem de buscar de novo (antes o [] ficava guardado)"
    assert r["inv2"] == [{"id": 1, "nome": "Inversor 1.1"}] and r["e2"] == ""


def test_o_504_da_rota_e_falha_nao_usina_vazia():
    r = _node("(async()=>{ resp={error:'falha',detalhe:'ReadTimeout: day_inverter'}; await loadPlant(18747509);"
              " process.stdout.write(JSON.stringify({e:_invErro(18747509), inv:RD.plants['thopen-pv|18747509']})); })();")
    assert "Não consegui carregar os inversores" in r["e"] and "ReadTimeout: day_inverter" in r["e"]
    assert r["inv"] == []


def test_aos_10_s_a_linha_diz_que_esta_esperando():
    r = _node("(async()=>{ solta=1; resp={inversores:[]}; const p=loadPlant(18747509); await new Promise(r=>setTimeout(r,20));"
              " const durante=_invCarregando(18747509); solta(); await p;"
              " process.stdout.write(JSON.stringify({durante, depois:_invCarregando(18747509), lento:RD.plantLento})); })();")
    assert "carregando inversores" in r["durante"] and "demorando" in r["durante"] and "90 s" in r["durante"]
    assert "demorando" not in r["depois"] and r["lento"] == {}


def test_usina_que_a_fonte_devolveu_sem_inversor_diz_isso():
    r = _node("(async()=>{ resp={plant_id:1,inversores:[]}; await loadPlant(1);"
              " process.stdout.write(JSON.stringify({e:_invErro(1), v:_invVazio()})); })();")
    assert r["e"] == "" and "não devolveu inversores" in r["v"]


def test_a_linha_expandida_usa_os_tres_estados():
    assert "_invCarregando(u.id)" in MON and "_invErro(u.id)" in MON and "_invVazio()" in MON
    assert "plantErro:{}" in MON and "plantLento:{}" in MON
    i = MON.index("async function loadPlant(")
    corpo = MON[i:MON.index("\n}\n", i)]
    assert "catch(e){ RD.plants[key]=[]; }" not in corpo, "a falha voltou a ser guardada calada"
