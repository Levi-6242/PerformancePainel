# -*- coding: utf-8 -*-
"""O "Investigar ativo" do Tempo real (26/10/2026). Levi: "Gostaria de poder clicar com botão direito do mouse em cima do
inversor e ter a opção 'Investigar ativo'. Vai aproveitar o pré carregamento de histórico de OS do OS Creator filtrando
esse ativo, deve mostrar o período filtrado e eu devo conseguir fazer novos filtros e pesquisas pela visão. Vai abrir uma
sub janela sobrepondo a tela dando um blur de fundo que nem quando vamos criar OS."

A plataforma faz duas coisas: o menu do botão direito na linha do inversor (Monitoramento), e o código do Fracttal do
inversor (`/api/fracttal/ativo-do-inversor`: o gravado no de-para ou o derivado do nome, SEM ir ao Fracttal). O histórico
mora no OS Creator do Nexus (`/os/historico/ativo`), que abre na mesma janela do Criar OS."""
import json
import pathlib
import shutil
import subprocess

import pytest

import app
import leitura_nexus as ln

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
MON = (RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")
ENT = (RAIZ / "docs" / "redesign" / "Entrada.html").read_text(encoding="utf-8")


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")

    def sem_fracttal(*a, **k):                 # a cota do Fracttal é da empresa: o clique não pode ir lá
        raise AssertionError("o Investigar ativo foi ao Fracttal")
    monkeypatch.setattr(app, "_frac_get", sem_fracttal)
    monkeypatch.setattr(app, "_frac_codebase_index", sem_fracttal)
    monkeypatch.setattr(app, "_frac_fractall_map", lambda: {"usina teste": "Thopen - Usina Teste - PA"})
    monkeypatch.setattr(app, "FRAC_COD_INV", {})
    monkeypatch.setattr(app, "FRAC_COD_INV_DISP", {})
    monkeypatch.setattr(app, "_frac_cb_index", {})
    monkeypatch.setattr(app, "_FRAC_INDEX_FILE", str(RAIZ / "nao-existe" / "indice.json"))
    return app.app.test_client()


def _ativo(cli, usina="Usina Teste", inv="Inversor 1.1"):
    r = cli.get("/api/fracttal/ativo-do-inversor", query_string={"usina": usina, "inv": inv})
    return r.status_code, r.get_json()


def test_o_codigo_gravado_no_de_para_vale_primeiro(cli, monkeypatch):
    monkeypatch.setattr(app, "FRAC_COD_INV", {"Usina Teste": {app._nrm("Inversor 1.1"): "THPN-CGH100-INVR2.1"}})
    monkeypatch.setattr(app, "_frac_cb_index", {"thopen - usina teste - pa": {"cb": "CGH200", "site": 1}})
    st, j = _ativo(cli)
    assert st == 200 and j == {"ok": True, "codigo": "THPN-CGH100-INVR2.1", "origem": "de-para",
                               "usina_fracttal": "Thopen - Usina Teste - PA"}


def test_sem_o_gravado_o_derivado_do_nome_pelo_indice_que_ja_existe(cli, monkeypatch):
    monkeypatch.setattr(app, "_frac_cb_index", {"thopen - usina teste - pa": {"cb": "CGH100", "site": 1}})
    st, j = _ativo(cli, inv="Inversor 1.10")
    assert st == 200 and j["codigo"] == "CGH100-INVR1.10" and j["origem"] == "derivado"


def test_o_indice_do_disco_serve_quando_a_memoria_esta_fria(cli, monkeypatch, tmp_path):
    arq = tmp_path / "indice.json"
    arq.write_text(json.dumps({"ts": 0, "idx": {"thopen - usina teste - pa": {"cb": "CGH100", "site": 1}}}),
                   encoding="utf-8")
    monkeypatch.setattr(app, "_FRAC_INDEX_FILE", str(arq))
    assert _ativo(cli)[1]["codigo"] == "CGH100-INVR1.1"          # vencido também serve: nada de varrer o parque


def test_sem_indice_nenhum_vai_sem_codigo_e_o_os_creator_acha_pelo_nome(cli):
    st, j = _ativo(cli)
    assert st == 200 and j["codigo"] == "" and j["origem"] == "" and j["usina_fracttal"] == "Thopen - Usina Teste - PA"
    st, j = _ativo(cli, usina="Usina Que Nao Tem De Para")
    assert st == 200 and j["codigo"] == "" and j["usina_fracttal"] == ""


def test_sem_a_usina_ou_o_inversor_400(cli):
    assert _ativo(cli, usina="")[0] == 400 and _ativo(cli, inv="")[0] == 400


def test_a_rota_e_leitura_para_a_ponte_e_para_o_gestor():
    """Classificada (leitura_nexus._GET): a ponte e o gestor leem; não é gravação nem abre a API PV."""
    assert ln.permitido("GET", "/api/fracttal/ativo-do-inversor", ("usina", "inv"))
    assert ln.permitido_gestor("GET", "/api/fracttal/ativo-do-inversor", ("usina", "inv"))
    assert not ln.permitido("POST", "/api/fracttal/ativo-do-inversor")


# ── a tela ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_o_botao_direito_na_linha_do_inversor_de_toda_fonte():
    # 26/10/2026: o portão era o _OS_FONTES (as fontes do Criar OS), e a Colider 2 é da RenoGrid (SolarEdge): o Levi
    # clicou no "Inversor 1.6" e veio o menu do navegador. O menu vale em toda fonte; a marca do chip diz onde.
    i = MON.index("document.addEventListener('contextmenu',")
    f = MON[i:MON.index("\n});", i)]
    assert "closest('.gc-chip[data-inv-usina]')" in f and "_OS_FONTES" not in f
    assert "ev.preventDefault(); gcMenuAtivo(ev,chip);" in f
    # a usina vem da linha que abriu o drill (qualquer fonte); o RD.pv é só reserva
    assert "function buildInversores(pid,usinaDaLinha){" in MON
    assert "const _un=usinaDaLinha||(_urow?_urow.usina:'');" in MON
    assert "inversores:expanded?buildInversores(pid,r.usina):[]};" in MON
    # só a linha de um inversor de verdade, com a usina, ganha as marcas (o protótipo não)
    assert '${(inv.isReal&&inv.usina)?` data-inv-usina="${_he(inv.usina)}" data-inv-nome="${_he(inv.name||\'\')}"' in MON
    # o menu: sem emoji, com as cores do tema
    i = MON.index("function gcMenuAtivo(ev,chip){")
    f = MON[i:MON.index("\n}\n", i)]
    assert "Investigar ativo" in f and "var(--color-surface" in f and "ph-magnifying-glass" in f


def test_a_entrada_abre_so_a_tela_do_os_creator_que_investiga():
    assert ("d.gc==='investigar'&&typeof d.href==='string'&&d.href.indexOf('/os/historico/ativo?')===0) "
            "gcDeparaJanela(d.href,'Investigar ativo')") in ENT
    i = MON.index("function gcAbrirInvestigar(href){")
    f = MON[i:MON.index("\n}\n", i)]
    assert "parent.postMessage({gc:'investigar',href:href},location.origin)" in f and "if(EMBED)" in f
    assert "gcDeparaJanela(href,'Investigar ativo')" in f


def _rodar(embed, resposta):
    node = shutil.which("node")
    if not node:
        pytest.skip("node não instalado")
    ini = MON.index("const OS_WEB_INVESTIGAR=")
    fim = MON.index("function _dpSem(", ini)
    codigo = MON[ini:fim]
    pre = r"""
    const abertos = [], postados = [], pedidos = [];
    globalThis.document = {addEventListener(){}, getElementById(){ return null; }};
    globalThis.window = {addEventListener(){}};
    globalThis.location = {origin: 'https://app.gridco.com.br'};
    globalThis.parent = {postMessage(m, o){ postados.push([m, o]); }};
    const EMBED = %s, SKEY = {}, state = {}, _OS_FONTES = [];
    function _he(s){ return String(s); }
    function gcDeparaJanela(href, rotulo){ abertos.push([href, rotulo]); }
    globalThis.fetch = async (u, o) => { pedidos.push(u); const r = %s;
      if (r === 'rede') throw new Error('rede'); return {ok: r.ok, json: async () => r.corpo}; };
    """ % ("true" if embed else "false", json.dumps(resposta))
    fim_js = r"""
    gcInvestigarAtivo('Usina Teste', 'Inversor 1.1', 'Inversor 2.1').then(() => {
      process.stdout.write(JSON.stringify({abertos, postados, pedidos}));
    });
    """
    p = subprocess.run([node, "-e", pre + codigo + fim_js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_investigar_pede_o_codigo_e_abre_a_janela_com_ele():
    out = _rodar(False, {"ok": True, "corpo": {"ok": True, "codigo": "THPN-CGH100-INVR2.1", "origem": "de-para",
                                                "usina_fracttal": "Thopen - Usina Teste - PA"}})
    assert out["pedidos"] == ["/api/fracttal/ativo-do-inversor?usina=Usina+Teste&inv=Inversor+1.1"]
    assert out["abertos"] == [["/os/historico/ativo?codigo=THPN-CGH100-INVR2.1&usina=Thopen+-+Usina+Teste+-+PA"
                               "&nome=Inversor+1.1&rotulo=Inversor+2.1", "Investigar ativo"]]


def test_sem_o_codigo_a_janela_abre_igual_e_no_embutido_quem_abre_e_a_entrada():
    out = _rodar(True, "rede")
    assert out["abertos"] == []
    m, origem = out["postados"][0]
    assert origem == "https://app.gridco.com.br" and m["gc"] == "investigar"
    assert m["href"] == "/os/historico/ativo?codigo=&usina=Usina+Teste&nome=Inversor+1.1&rotulo=Inversor+2.1"



# ── o caso real: Colider 2, RenoGrid (SolarEdge), "Inversor 1.6" (26/10/2026) ─────────────────────────────────────────────
# A linha e o drill como o servidor serviu às 13:15 (/api/solaredge/data e /api/solaredge/plant/4486122): plant_id NÚMERO
# na linha, id de texto no drill; o inversor desligado chega com o serial no lugar do nome.
_COLIDER2_LINHA = {"plant_id": 4486122, "usina": "Colider 2", "qtd_inversores": 25, "inv_esp": 25, "str_esp": 145,
                   "strings_ativas": 142, "diferenca": -4, "inv_desligados": 1, "inv_desligados_nomes": ["7E05ABED"],
                   "strings_fora": 1, "sol_baixo": False, "falha_comunicacao": False,
                   "ultima_leitura": "2026-10-26T13:15:00Z"}
_COLIDER2_DRILL = [
    {"id": "7E05ABFB", "nome": "Inversor 1.6", "nome_api": "Inverter 6", "nome_fracttal": None, "strings_ativas": 6,
     "total_strings": 6, "str_esp": 6, "strings": [{"id": "Ipv1", "status": "ativa", "corrente": 8.1}]},
    {"id": "7E05ABED", "nome": "7E05ABED", "nome_api": "7E05ABED", "nome_fracttal": None, "strings_ativas": 0,
     "total_strings": 1, "str_esp": 1, "strings": [{"id": "Ipv1", "status": "sem_corrente", "corrente": 0}]},
]

# um DOM de mentira com o mínimo que o menu usa: os ouvintes do document, o body, o createElement e o botão do menu
_DOM_FALSO = r"""
const ouvintes = {}, corpo = [], abertos = [], postados = [], pedidos = [];
function _el(tag){ const e = {tag, style:{}, dataset:{}, attrs:{}, ouv:{}, innerHTML:'', offsetWidth:220, offsetHeight:80,
  setAttribute(k,v){ this.attrs[k]=v; }, addEventListener(t,f){ this.ouv[t]=f; }, focus(){ this.focado=true; },
  contains(x){ return x===this||x===this._botao; }, remove(){ const i=corpo.indexOf(this); if(i>=0) corpo.splice(i,1); },
  querySelector(){ if(!this._botao){ this._botao=_el('button'); } return this._botao; } }; return e; }
globalThis.document = {addEventListener(t,f){ ouvintes[t]=f; }, createElement:_el, body:{appendChild(e){ corpo.push(e); }},
  getElementById(id){ return corpo.find(e=>e.id===id)||null; }};
globalThis.window = {addEventListener(){}, innerWidth:1600, innerHeight:900};
globalThis.location = {origin:'https://app.gridco.com.br'};
globalThis.parent = {postMessage(m,o){ postados.push([m,o]); }};
const SKEY = %(skey)s, state = {source:'renogrid', expandedInversor:null}, _OS_FONTES = %(osf)s;
const EMBED = %(embed)s;
function _he(s){ return String(s); }
function gcDeparaJanela(href, rotulo){ abertos.push([href, rotulo]); }
globalThis.fetch = async (u) => { pedidos.push(u); return {ok:true, json:async()=>({ok:true, codigo:'CLD200-INVR1.6',
  origem:'derivado', usina_fracttal:'RenoGrid - Colíder 2 - MT'})}; };
function _chip(ds){ const c = {dataset:ds}; return {closest(sel){ return sel==='.gc-chip[data-inv-usina]'?c:null; }}; }
function _clique(alvo){ let barrado=false; const ev={target:alvo, clientX:400, clientY:300, preventDefault(){ barrado=true; }};
  ouvintes.contextmenu(ev); return barrado; }
"""


def _node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node não instalado")
    return node


def _trecho(ini, fim):
    a = MON.index(ini)
    return MON[a:MON.index(fim, a)]


def _js_const(nome):
    a = MON.index("const %s=" % nome)
    return MON[a:MON.index(";\n", a) + 2]


def test_colider2_o_drill_da_renogrid_marca_o_inversor_com_a_usina_da_linha():
    """O drill da SolarEdge monta o inversor de verdade com a usina, venha ela da linha ou (reserva) do RD.pv."""
    node = _node()
    codigo = _trecho("const _SCHIP=", "let _chart=null;")
    js = r"""
    function _tkStrInv(){ return []; } function _tkStrCobertura(){ return {cobreTudo:false, semTicket:0}; }
    function _tkStrMarca(){ return null; } function _nrmU(s){ return String(s||'').toLowerCase(); }
    function fetchJSON(){ return Promise.resolve(null); } function render(){}
    const SKEY = %s, state = {source:'renogrid', expandedInversor:null};
    const RD = {plants:{'renogrid|4486122': %s}, pv:null};
    """ % (json.dumps({"renogrid": "solaredge"}), json.dumps(_COLIDER2_DRILL)) + codigo + r"""
    const semPv = buildInversores('4486122', 'Colider 2');            // a linha manda; o RD.pv pode nem estar lá
    RD.pv = {rows:[%s]};
    const reserva = buildInversores('4486122');                       // a reserva: plant_id número x pid texto casa
    RD.pv = {rows:[{plant_id:1, usina:'Outra'}]};
    const outra = buildInversores('4486122', 'Colider 2');            // RD.pv de outra fonte não troca a usina
    const f = l => l.map(i => [i.name, i.isReal, i.usina]);
    process.stdout.write(JSON.stringify({semPv:f(semPv), reserva:f(reserva), outra:f(outra)}));
    """ % json.dumps(_COLIDER2_LINHA)
    p = subprocess.run([node, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    esperado = [["Inversor 1.6", True, "Colider 2"], ["7E05ABED", True, "Colider 2"]]
    assert out == {"semPv": esperado, "reserva": esperado, "outra": esperado}


def _rodar_menu(embed=False):
    node = _node()
    codigo = _trecho("const OS_WEB_INVESTIGAR=", "function _dpSem(")
    pre = _DOM_FALSO % {"skey": json.dumps({"renogrid": "solaredge", "thopen-pv": "pv"}),
                        "osf": _js_const("_OS_FONTES")[len("const _OS_FONTES="):-2], "embed": "true" if embed else "false"}
    fim = r"""
    const r = {};
    r.foraDoInversor = _clique({closest(){ return null; }});          // fora do chip: o menu nativo segue
    r.menusFora = corpo.length;
    r.noInversor = _clique(_chip({invUsina:'Colider 2', invNome:'Inversor 1.6', invFr:''}));
    r.menus = corpo.map(e => e.id); r.texto = corpo[0] && corpo[0].innerHTML;
    if (corpo[0]) corpo[0]._botao.ouv.click();                       // sem menu (o código de antes), nada a clicar
    setTimeout(() => { r.pedidos = pedidos; r.abertos = abertos; r.postados = postados; r.depois = corpo.length;
      process.stdout.write(JSON.stringify(r)); }, 20);
    """
    p = subprocess.run([node, "-e", pre + codigo + fim], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_colider2_o_botao_direito_no_inversor_da_renogrid_abre_o_nosso_menu_e_a_janela():
    assert "'solaredge'" not in _js_const("_OS_FONTES")    # a RenoGrid segue sem Criar OS: o caso é justamente esse
    out = _rodar_menu()
    assert out["foraDoInversor"] is False and out["menusFora"] == 0
    assert out["noInversor"] is True and out["menus"] == ["gc-menu-ativo"]       # o nativo não aparece por cima do nosso
    assert "Investigar ativo" in out["texto"] and "Inversor 1.6 · Colider 2" in out["texto"]
    assert out["depois"] == 0
    assert out["pedidos"] == ["/api/fracttal/ativo-do-inversor?usina=Colider+2&inv=Inversor+1.6"]
    assert out["abertos"] == [["/os/historico/ativo?codigo=CLD200-INVR1.6&usina=RenoGrid+-+Col%C3%ADder+2+-+MT"
                               "&nome=Inversor+1.6&rotulo=Inversor+1.6", "Investigar ativo"]]


def test_colider2_no_embutido_o_menu_abre_igual_e_a_janela_vai_pela_entrada():
    out = _rodar_menu(embed=True)
    assert out["noInversor"] is True and out["abertos"] == []
    m, origem = out["postados"][0]
    assert origem == "https://app.gridco.com.br" and m["gc"] == "investigar"
    assert m["href"].startswith("/os/historico/ativo?codigo=CLD200-INVR1.6&")
