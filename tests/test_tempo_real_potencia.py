# -*- coding: utf-8 -*-
"""Potência + POA e GHI no ··· do Tempo real (Levi, 27/10/2026).

"Em relatórios > performance temos a Potência Ativa dos Inversores. Quero que vá para os três pontos no tempo real e seja
Potência Ativa dos Inversores + POA e GHI / E POTÊNCIA ATIVA DA USINA + POA E GHI!"

As duas abas (potinv e potusina) moram no Monitoramento embutido e aparecem no ··· da Entrada só nas fontes com histórico
de potência por inversor. A potência vem da rota do relatório e o POA/GHI da rota do gráfico do ETM; nada é lido antes de
escolher a usina. A potência da usina é a soma dos inversores só nos passos em que todos leram: somar só quem leu
desenharia uma queda que não houve.
"""
import json as _json
import re
import shutil as _sh
import subprocess as _sp
from pathlib import Path

import pytest as _pt

import potencia_ativa as _pa

_RED = Path(__file__).resolve().parent.parent / "docs" / "redesign"
_MON = (_RED / "Monitoramento (novo design).html").read_text(encoding="utf-8-sig")
_ENT = (_RED / "Entrada.html").read_text(encoding="utf-8-sig")


# ── a Entrada: o ··· só oferece o que a fonte tem ───────────────────────────────────────────────────────────────────

def _lista_js(texto, nome):
    m = re.search(nome + r"\s*=\s*(\[[^\]]*\])", texto)
    assert m, nome
    return _json.loads(m.group(1).replace("'", '"'))


def test_o_tres_pontos_so_oferece_a_potencia_onde_o_relatorio_tem_historico():
    """A lista da Entrada é a do relatório traduzida para os ids dos cards; se o relatório ganhar ou perder uma fonte (a
    Athon e a Axis saíram dele em 13/10), este teste aponta o ··· que ficou para trás."""
    card_para_fonte = {"thopen-pv": "pv", "thopen-db": "pg", "renogrid": "solaredge", "2c": "2capi", "semp": "semp",
                       "alveslima": "alveslima", "greenyellow": "greenyellow", "salenergia": "salenergia",
                       "apolo": "apolo", "athon": "sunop", "axis": "axis"}
    com_historico = {f["fonte"] for f in _pa.FONTES if f["familia"]}
    esperado = sorted(c for c, f in card_para_fonte.items() if f in com_historico)
    assert sorted(_lista_js(_ENT, "var POT_FONTES")) == esperado
    assert {"athon", "axis", "salenergia"}.isdisjoint(_lista_js(_ENT, "var POT_FONTES"))
    assert {"potinv", "potusina"} <= set(_lista_js(_ENT, "var VIEWS"))
    # a aba Perdas do Monitoramento acabou no 03fa176 e o item ficou no ··· sem abrir nada (tirado em 27/10/2026)
    assert "perdas" not in _lista_js(_ENT, "var VIEWS") and '["perdas"' not in _ENT


def test_pelo_nexus_a_potencia_passa_e_a_estacao_da_api_pv_nao():
    """A ponte e o gestor leem a rota do relatório (o banco e o scadaGridco); a curva da estação da API PV segue negada
    (abre a usina na API PV na hora), e a tela diz que o POA/GHI não veio em vez de quebrar."""
    import leitura_nexus as ln
    assert ln.permitido("GET", "/api/relatorio/potencia-ativa")
    assert ln.permitido_gestor("GET", "/api/relatorio/potencia-ativa")
    assert not ln.permitido("GET", "/api/etm/chart") and not ln.permitido_gestor("GET", "/api/etm/chart")
    assert ln.permitido("GET", "/api/pg/etm/chart") and ln.permitido_gestor("GET", "/api/pg/etm/chart")


def test_o_monitoramento_abre_as_abas_pela_url_e_pela_mensagem_da_entrada():
    vistas = _lista_js(_MON, "const _VIEWS_URL")
    assert {"potinv", "potusina"} <= set(vistas)
    assert "else if(v.showPot)panel=renderPotencia(v);" in _MON


# ── o comportamento, rodando o bloco da tela no node ───────────────────────────────────────────────────────────────

def _bloco():
    i = _MON.index("// ── Potência + POA e GHI")
    j = _MON.index("function _potCorpo(")
    return _MON[i:_MON.index("\n}\n", j) + 3]


def _uma_linha(nome):
    i = _MON.index(f"function {nome}(")
    return _MON[i:_MON.index("\n", i) + 1]


def _etm_url():
    i = _MON.index("function _etmChartUrl(")
    fim = "return null; }"
    return _MON[i:_MON.index(fim, i) + len(fim)] + "\n"


_BASE = r"""
var window=globalThis, document={querySelectorAll:()=>[]}; let _gtip=null;
const state={source:'thopen-pv',view:'potinv',potPid:null,potData:null};
const RD={pv:{rows:[{plant_id:9,usina:'Aparecida do Taboado 1'},{plant_id:31,usina:'Aparecida do Taboado 2'},
                    {plant_id:'ARA',usina:'Araputanga (Owen)'}]},loading:false};
const SKEY={'thopen-pv':'pv','thopen-db':'pg','athon':'sunop','axis':'axis','renogrid':'solaredge','2c':'owen',
            'semp':'semp','alveslima':'alveslima','2capi':'2capi','greenyellow':'greenyellow','salenergia':'salenergia'};
function _fonte(){ return SKEY[state.source]; }
const PEDIDOS=[]; let RESPOSTAS={};
async function fetchJSON(url,o){ PEDIDOS.push(url); const k=Object.keys(RESPOSTAS).find(p=>url.startsWith(p));
  const r=k?RESPOSTAS[k]:{}; if(r instanceof Error) throw r; return JSON.parse(JSON.stringify(r)); }
let RENDERS=0; function render(){ RENDERS++; }
const _he=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
function _naPanel(n){ return '[NA '+n+']'; } function _loadingPanel(){ return '[CARREGANDO]'; }
function _subMsg(t){ return '[MSG '+t+']'; } function _subLoad(t){ return '[LENDO '+t+']'; }
const espera=()=>new Promise(r=>setTimeout(r,0));
"""


def _node(js):
    node = _sh.which("node")
    if not node:
        _pt.skip("node não instalado")
    base = (_BASE + _uma_linha("_hm") + _uma_linha("_todayISO") + _uma_linha("_brData") + _etm_url() + _bloco())
    p = _sp.run([node, "-e", base + "(async()=>{" + js + "})().catch(e=>{console.error(e);process.exit(1);});"],
                capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return _json.loads(p.stdout)


_DIA_OK = ("{ok:true,passo_min:5,lacuna_max_min:15,usina_nome:'Aparecida do Taboado 1',origem:'Banco',sem_historico:false,"
           "dias:[{dia:'2026-10-26',situacao:'ok',parcial:false,lido_em:'10:00',sem_leitura:['INV 9'],faltaram:[],"
           "inversores:[{nome:'INV <1>',pontos:[[600,10],[605,11],[610,12]]},{nome:'INV 2',pontos:[[600,20],[610,22]]}]}]}")


def test_nada_e_lido_antes_de_escolher_a_usina():
    r = _node("await _loadPot(); state.potData='2026-10-26'; await _loadPot();"
              "process.stdout.write(JSON.stringify(PEDIDOS));")
    assert r == []


@_pt.mark.parametrize("fonte,pid,pot,irr", [
    ("thopen-pv", 9, "fonte=pv&usina=9", "/api/etm/chart?plant_id=9&date=2026-10-26"),
    ("thopen-db", 9, "fonte=pg&usina=9", "/api/pg/etm/chart?plant_id=9&date=2026-10-26"),
    ("2c", 9, "fonte=2capi&usina=9", "/api/etm/chart?plant_id=9&date=2026-10-26"),
    ("renogrid", 9, "fonte=solaredge&usina=9", None),           # a SolarEdge não tem a estação: nem pede
    ("greenyellow", 9, "fonte=greenyellow&usina=9", None),
])
def test_escolher_a_usina_le_a_potencia_do_relatorio_e_o_poa_ghi_do_etm(fonte, pid, pot, irr):
    r = _node(f"state.source='{fonte}'; state.potData='2026-10-26'; state.potPid='{pid}'; await _loadPot();"
              "process.stdout.write(JSON.stringify(PEDIDOS));")
    assert r[0] == f"/api/relatorio/potencia-ativa?{pot}&ini=2026-10-26&fim=2026-10-26"
    assert r[1:] == ([irr] if irr else [])


def test_usina_da_owen_na_2c_nao_tem_potencia_e_nao_vai_a_rota():
    r = _node("state.source='2c'; state.potPid='ARA'; await _loadPot();"
              "process.stdout.write(JSON.stringify({pedidos:PEDIDOS, lista:_potLinhas().map(x=>x.usina)}));")
    assert r["pedidos"] == []
    assert r["lista"] == ["Aparecida do Taboado 1", "Aparecida do Taboado 2"], "a lista da 2C só leva as da API PV"


def test_dia_passado_lido_nao_e_relido_e_a_falha_nao_fica_guardada():
    r = _node("state.potData='2026-10-26'; state.potPid='9';"
              f"RESPOSTAS={{'/api/relatorio':{_DIA_OK},'/api/etm':{{sem_historico:true}}}};"
              "await _loadPot(); await _loadPot(); const n1=PEDIDOS.length;"
              "state.potData='2026-10-25'; RESPOSTAS['/api/relatorio']={ok:true,dias:[{dia:'2026-10-25',situacao:'falhou',"
              "motivo:'a API PV não respondeu',inversores:[]}]}; await _loadPot(); await _loadPot();"
              "process.stdout.write(JSON.stringify([n1, PEDIDOS.length]));")
    assert r == [2, 6], "26/10 lido uma vez (2 pedidos); 25/10 falhou e foi relido (mais 2 + 2)"


def test_a_soma_da_usina_so_fecha_onde_todo_inversor_leu():
    r = _node("process.stdout.write(JSON.stringify(_potSoma([{pontos:[[0,1],[5,2],[10,3]]},{pontos:[[0,10],[10,30]]}])));")
    assert r["pts"] == [[0, 11], [10, 33]]
    assert r["falta"] == {"5": 1}, "no passo das 00:05 o 2º inversor não leu: sem soma, nunca 2 kW"


def test_a_tela_diz_por_que_falta_cada_parte():
    r = _node("state.potData='2026-10-26'; state.potPid='9'; state.view='potusina';"
              f"RESPOSTAS={{'/api/relatorio':{_DIA_OK},'/api/etm':{{sem_historico:true}}}};"
              "await _loadPot(); const usina=renderPotencia({});"
              "state.view='potinv'; const inv=renderPotencia({});"
              "state.potData='2026-10-24'; RESPOSTAS['/api/relatorio']={ok:true,sem_historico:true,dias:[],"
              "motivo:'A Sal Energia chega por Modbus'}; await _loadPot(); const semHist=renderPotencia({});"
              "process.stdout.write(JSON.stringify({usina,inv,semHist}));")
    u = r["usina"]
    assert "soma de 2 inversores" in u and "1 passo de 5 min sem a soma" in u
    assert "INV 9 (fora da soma)" in u
    assert "A API PV só entrega o POA/GHI do dia de hoje" in u
    assert 'data-pot="kw"' in u and 'data-pot="irr"' not in u
    assert "INV &lt;1&gt;" in r["inv"] and "INV <1>" not in r["inv"], "nome de inversor entra escapado"
    assert "A Sal Energia chega por Modbus" in r["semHist"] and 'data-pot="kw"' not in r["semHist"]


def test_fonte_sem_historico_nem_desenha_a_aba():
    r = _node("state.source='athon'; process.stdout.write(JSON.stringify(renderPotencia({})));")
    assert r.startswith("[NA ")


def test_poa_e_ghi_no_mesmo_grafico_da_potencia_com_o_eixo_da_direita():
    """Levi, 27/10/2026 (print da Araputanga): "quero que o IPOA e GHI fique junto do gráfico da geração/potência ativa".
    Um SVG só, o W/m² à direita, e cada marca dos dois eixos na mesma linha de grade (o zero com o zero)."""
    r = _node(f"state.potPid='9';"
              f"RESPOSTAS={{'/api/relatorio':{_DIA_OK.replace("2026-10-26", "'+_todayISO()+'")},"
              "'/api/etm':{labels:['10:00','10:05','10:10'],poa:[400,980,1210],ghi:[300,700,800]}};"
              "await _loadPot(); const h=renderPotencia({});"
              "process.stdout.write(JSON.stringify({h, par:_potTicksPar([0,5,10,15,20,25],1210),"
              "neg:_potTicksPar([-5,0,5,10],1000)}));")
    h = r["h"]
    assert h.count("<svg data-pot=") == 1 and 'data-pot="kw"' in h and 'data-pot="irr"' not in h
    assert "W/m²</text>" in h and "kW</text>" in h, "as duas unidades no mesmo gráfico"
    assert "POA (W/m²)" in h and "GHI (W/m²)" in h, "a legenda diz que a irradiância é do eixo da direita"
    assert r["par"] == [0, 250, 500, 750, 1000, 1250], "5 intervalos dos dois lados, zero com zero, cobre 1210"
    assert r["neg"] == [-500, 0, 500, 1000], "kW abaixo de zero: o zero da direita na mesma linha"
