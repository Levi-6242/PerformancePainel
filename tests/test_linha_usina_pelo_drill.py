# -*- coding: utf-8 -*-
"""A linha da usina pelos inversores que acabaram de chegar (Levi, 12/10/2026: "quando abrisse e o resultado desse que a
diferença é menor ou maior automaticamente atualizaria o número de diferença da UFV"). Caso real: SMP100 às 17:23, a
linha dizia −2 (tabela das 17:18) e o drill mostrava o 5.2 com −3 e o 6.1 com −8 (2.1 e 2.2 desligados, fora da conta).
A linha passa a ser a soma do drill quando ele é mais novo; reabrir depois de 2 min busca os inversores de novo."""
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


def _inv(nome, ativas, esp, dif, **kw):
    return {"id": nome, "nome": nome, "strings_ativas": ativas, "total_strings": 28, "str_esp": esp, "diferenca": dif, **kw}


SMP100 = ([_inv(f"Inversor {g}.{n}", 18, 18, 0) for g in (1, 3, 4, 7) for n in (1, 2, 3)]
          + [_inv("Inversor 2.1", 1, 18, None, desligado=True, fora_da_conta=True),
             _inv("Inversor 2.2", 2, 17, None, desligado=True, fora_da_conta=True),
             _inv("Inversor 5.1", 18, 18, 0), _inv("Inversor 5.2", 14, 17, -3),
             _inv("Inversor 6.1", 10, 18, -8), _inv("Inversor 6.2", 17, 17, 0)])


def _node(js):
    node = shutil.which("node")
    if not node:
        pytest.skip("node não instalado")
    base = (_func("loadPlant", "async function ") + _func("_resumoDrill")
            + "const state={source:'athon'}; const SKEY={athon:'sunop'}; const PLANT={sunop:'/api/sunop/plant/'};"
              "const RD={plants:{},plantErro:{},plantLento:{},plantTs:{},plantRelendo:{}}; const render=()=>{};"
              "const urls=[]; let resp=null;"
              "async function fetchJSON(u,o){ urls.push(u); if(resp instanceof Error) throw resp; return resp; }")
    p = subprocess.run([node, "-e", base + js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


LINHA = {"plant_id": "SMP100", "strings_ativas": 313, "str_esp": 315, "diferenca": -2, "ultima_leitura": "2026-10-12 17:18"}


def test_o_drill_mais_novo_troca_a_diferenca_da_linha_pela_soma_das_faltas():
    r = _node("(async()=>{ resp={inversores:%s}; await loadPlant('SMP100'); const x=_resumoDrill('SMP100',%s);"
              " process.stdout.write(JSON.stringify(x)); })();" % (json.dumps(SMP100), json.dumps(LINHA)))
    assert r["campos"]["diferenca"] == -11                              # −3 do 5.2 e −8 do 6.1; os desligados fora
    assert r["campos"]["str_esp"] == sum(i["str_esp"] for i in SMP100 if i["diferenca"] is not None)
    assert r["antes"] == -2 and r["leitura"] == "17:18"


def test_a_sobra_de_um_inversor_nao_paga_a_falta_de_outro_e_a_tabela_mais_nova_vence():
    invs = [_inv("Inversor 1.1", 19, 18, 1), _inv("Inversor 1.2", 13, 14, -1)]
    r = _node("(async()=>{ resp={inversores:%s}; await loadPlant('X'); const L=%s;"
              " const a=_resumoDrill('X',L), b=_resumoDrill('X',Object.assign({},L,{ultima_leitura:'2999-01-01 00:00'}));"
              " process.stdout.write(JSON.stringify({a,b})); })();"
              % (json.dumps(invs), json.dumps(dict(LINHA, plant_id="X", diferenca=0, strings_ativas=32, str_esp=32))))
    assert r["a"]["campos"]["diferenca"] == -1 and r["b"] is None


def test_inversor_na_conta_sem_esperadas_deixa_a_linha_da_tabela():
    invs = [_inv("Inversor 1.1", 18, None, None), _inv("Inversor 1.2", 13, 14, -1)]
    invs[0]["diferenca"] = 0                                           # na conta, mas o cadastro não tem as esperadas
    r = _node("(async()=>{ resp={inversores:%s}; await loadPlant('Y'); process.stdout.write(JSON.stringify(_resumoDrill('Y',%s))); })();"
              % (json.dumps(invs), json.dumps(dict(LINHA, plant_id="Y"))))
    assert r is None


def test_reabrir_depois_de_2_min_busca_de_novo_sem_apagar_a_lista():
    r = _node("(async()=>{ resp={inversores:%s}; await loadPlant('SMP100'); await loadPlant('SMP100');"
              " const k='athon|SMP100'; const n1=urls.length; RD.plantTs[k]=Date.now()-121000;"
              " resp=new Error('a fonte não respondeu'); await loadPlant('SMP100');"
              " process.stdout.write(JSON.stringify({n1, n2:urls.length, inv:RD.plants[k].length, erro:RD.plantErro[k]||''})); })();"
              % json.dumps(SMP100))
    assert r["n1"] == 1                                                # aberta há pouco: não busca de novo
    assert r["n2"] == 2 and r["inv"] == len(SMP100) and r["erro"] == ""   # releu; a falha da releitura mantém a lista
