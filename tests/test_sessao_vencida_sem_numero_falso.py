# -*- coding: utf-8 -*-
"""Sessão vencida não vira número falso (porta única com o Nexus, 10/10/2026; auditoria A5).

A sessão que o Nexus abre na plataforma (o passe) vale 12 h. Depois disso toda leitura de /api/ responde 401
{"error": "não autenticado"}, e as telas que releem sozinhas desenhavam o erro como se fosse dado: o Painel NOC, que
relê o /api/macro a cada 60 s, mostrava "Energia perdida 0,0 MWh" numa tela de NOC. Confiabilidade do dado é a
prioridade 1 do projeto: a leitura que não veio não troca o número que está na tela.

Três partes:
1. `plataforma/aviso_de_sessao.js`, injetado inline em toda página da plataforma: o 401 de uma rota /api/ deste
   endereço liga a faixa de sessão vencida e, na moldura do Nexus, manda à moldura
   postMessage({tipo: 'nexus:sessao-vencida', caminho}, origem) — no máximo 1 vez a cada 60 s — para ela pedir um passe
   novo e reabrir a mesma tela (o protocolo combinado com o Nexus);
2. a injeção no app.py (com e sem a NEXUS_SSO_CHAVE: é correção de dado);
3. cada tela que relê sozinha (ou relê ao clicar) guarda o último valor quando a leitura falha. Cada teste de tela roda o
   código da própria página no node com a resposta 401/500 e falhava com o código de antes (o erro virava zero, vazio,
   "DESLIGADA", "FORA DO AR", "Calculando a primeira varredura" ou os EXEMPLOS do protótipo do Monitoramento).
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

import app
import porta_nexus as pn

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
TPL = RAIZ / "plataforma" / "templates"
AVISO = (RAIZ / "plataforma" / "aviso_de_sessao.js").read_text(encoding="utf-8")
NODE = shutil.which("node")

CHAVE = "chave-de-teste-do-passe-" + "x" * 20
SENHA = "senha-de-teste"
NA_MOLDURA = {"Sec-Fetch-Dest": "iframe", "Sec-Fetch-Site": "same-origin"}


def _ler(nome: str) -> str:
    if nome in ("Entrada.html", "Monitoramento (novo design).html"):
        return (RAIZ / "docs" / "redesign" / nome).read_text(encoding="utf-8")
    return (TPL / nome).read_text(encoding="utf-8")


def _trecho(texto: str, inicio: str, fim: str) -> str:
    """Do `inicio` até o primeiro `fim` depois dele (inclusive): uma função da página, para rodar no node."""
    i = texto.index(inicio)
    return texto[i:texto.index(fim, i) + len(fim)]


def _func(texto: str, nome: str, recuo: str = "") -> str:
    for prefixo in ("async function ", "function "):
        alvo = recuo + prefixo + nome + "("
        if alvo in texto:
            return _trecho(texto, alvo, "\n" + recuo + "}\n")
    raise AssertionError(f"função {nome} não está na página")


def _node(js: str, tmp_path) -> dict:
    if not NODE:
        pytest.skip("node não instalado")
    arq = tmp_path / "prova.js"
    arq.write_text(js, encoding="utf-8")
    p = subprocess.run([NODE, str(arq)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr[-3000:]
    return json.loads(p.stdout.strip().splitlines()[-1])


# ── 1. o aviso de sessão (aviso_de_sessao.js) ───────────────────────────────────────────────────────────────────────
_NAVEGADOR = r"""
const CFG = %s;
const ouvidos = [], criados = [], timers = [];
function el(tag) { return { tag, id: "", style: {}, attrs: {}, innerHTML: "", hidden: false, filhos: [],
  setAttribute(k, v) { this.attrs[k] = v; }, appendChild(c) { this.filhos.push(c); return c; } }; }
globalThis.window = globalThis;
globalThis.location = { pathname: CFG.pathname, search: CFG.search, origin: "https://app.exemplo.com",
  href: "https://app.exemplo.com" + CFG.pathname + CFG.search };
globalThis.document = { documentElement: el("html"), body: el("body"),
  createElement: t => { const e = el(t); criados.push(e); return e; } };
const moldura = { postMessage(m, o) { ouvidos.push({ m, o }); } };
if (CFG.moldura) { window.parent = moldura; window.top = moldura; }
else if (CFG.paiPlataforma) { window.parent = { gcSessaoDaPlataforma: { vencida() { ouvidos.push({ delegou: true }); } } }; window.top = moldura; }
else { window.parent = window; window.top = window; }
if (CFG.modoNexus) window.gcModoNexus = true;
window.APP_PREFIX = CFG.prefixo || "";
let RESP = 401;
window.fetch = async () => ({ status: RESP, ok: RESP >= 200 && RESP < 300, json: async () => ({}) });
let AGORA = 1e9; Date.now = () => AGORA;
globalThis.setTimeout = (f, ms) => { timers.push({ f, ms }); return timers.length; };
function faixa() { const f = criados.find(e => e.id === "gc-sessao-faixa"); return f ? { html: f.innerHTML, hidden: f.hidden } : null; }
function out(o) { process.stdout.write("\n" + JSON.stringify(o)); }
"""


def _aviso(cfg: dict, roteiro: str, tmp_path, sem_admin=False) -> dict:
    base = {"pathname": "/nexus/painel", "search": "?x=1", "prefixo": "/nexus"}
    base.update(cfg)
    js = AVISO.replace("/*SEM_ADMIN*/false", "true" if sem_admin else "false")
    return _node(_NAVEGADOR % json.dumps(base) + js + "\n(async () => {\n" + roteiro + "\n})();", tmp_path)


def test_na_moldura_o_401_pede_ao_nexus_para_reabrir_a_mesma_tela(tmp_path):
    r = _aviso({"moldura": True, "modoNexus": True}, """
      await fetch("/api/macro");                       // a releitura de 60 s do Painel NOC, sessão vencida
      const um = ouvidos.slice(), f1 = faixa();
      await fetch("/nexus/api/gerencial");             // o mesmo segundo, outra leitura: não repete o aviso
      const dois = ouvidos.length;
      AGORA += 61000; await fetch("/api/macro");       // passou 1 min sem a moldura reabrir: avisa de novo
      const tres = ouvidos.length;
      timers.filter(t => t.ms === 15000).forEach(t => t.f());
      out({ um, f1, dois, tres, f2: faixa() });""", tmp_path)
    assert r["um"] == [{"m": {"tipo": "nexus:sessao-vencida", "caminho": "/painel?x=1"}, "o": "https://app.exemplo.com"}]
    assert "Sessão vencida:</b> abrindo de novo pelo Nexus" in r["f1"]["html"] and not r["f1"]["hidden"]
    assert r["dois"] == 1, "no máximo 1 aviso a cada 60 s (sem laço com a moldura)"
    assert r["tres"] == 2
    assert "clique de novo no item do menu do Nexus" in r["f2"]["html"]


def test_so_o_401_de_uma_api_deste_endereco_e_a_sessao(tmp_path):
    r = _aviso({"moldura": True, "modoNexus": True}, """
      await fetch("/gemeo/api/usina/1");                          // outro serviço pelo proxy
      await fetch("https://outro.exemplo.com/api/macro");         // outro endereço
      await fetch("/painel");                                      // página, não API
      RESP = 500; await fetch("/api/macro");                       // erro, mas não é a sessão
      RESP = 200; await fetch("/api/macro");
      out({ ouvidos, f: faixa() });""", tmp_path)
    assert r["ouvidos"] == [] and r["f"] is None


def test_fora_do_nexus_a_faixa_manda_entrar_de_novo_e_volta_a_tela(tmp_path):
    for cfg in ({}, {"modoNexus": True}):        # aba solta, mesmo com a sessão do passe: não há moldura para avisar
        r = _aviso(cfg, 'await fetch("/api/macro"); out({ ouvidos, f: faixa() });', tmp_path)
        assert r["ouvidos"] == []
        assert "Sessão vencida:</b> entre de novo" in r["f"]["html"]
        assert 'href="/nexus/login?next=%2Fpainel%3Fx%3D1" target="_top"' in r["f"]["html"]


def test_a_tela_embutida_passa_o_aviso_para_a_pagina_de_cima(tmp_path):
    """O /monitor?embed=1 que o Tempo real embute é moldura dentro da moldura: quem a moldura do Nexus conhece (e cujo
    caminho importa) é a página de cima."""
    r = _aviso({"paiPlataforma": True, "modoNexus": True}, """
      await fetch("/api/data");
      window.gcSessaoDaPlataforma.falhou("sessão vencida", "de 14:32");   // a releitura da própria tela, logo depois
      out({ ouvidos, f: faixa() });""", tmp_path)
    # provado no navegador (10/10/2026): sem se lembrar da sessão, a tela de baixo cobria a explicação com "Não atualizou"
    assert r["ouvidos"] == [{"delegou": True}] and r["f"] is None


def test_falhou_e_voltou_e_a_sessao_tem_prioridade(tmp_path):
    r = _aviso({}, """
      const S = window.gcSessaoDaPlataforma;
      S.falhou("HTTP 502", "de 14:32"); const f1 = faixa();
      S.voltou(); const f2 = faixa();
      await fetch("/api/macro"); S.falhou("HTTP 502", "de 14:33"); const f3 = faixa();
      out({ f1, f2, f3 });""", tmp_path)
    assert "Não atualizou</b> (HTTP 502): os números na tela são de 14:32" in r["f1"]["html"]
    assert r["f2"]["hidden"]
    assert "Sessão vencida" in r["f3"]["html"] and "14:33" not in r["f3"]["html"]


def test_tokens_so_troca_o_texto_para_quem_nao_e_admin(tmp_path):
    msg = "Sem corrente da API PV para esta data, e o token da PV Plataforma venceu. Renove na tela Tokens."
    roteiro = f'out({{ t: window.gcSessaoDaPlataforma.tokens({json.dumps(msg)}), s: window.gcSessaoDaPlataforma.semAdmin }});'
    admin = _aviso({}, roteiro, tmp_path)
    assert admin == {"t": msg, "s": False}
    sem = _aviso({}, roteiro, tmp_path, sem_admin=True)
    assert sem["s"] is True and "Renove na tela Tokens" not in sem["t"]
    assert "Peça a um administrador do Nexus" in sem["t"]


# ── 2. a injeção no app.py ──────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", SENHA)
    monkeypatch.setattr(app, "NEXUS_SSO_CHAVE", "")
    monkeypatch.setattr(app, "PLATAFORMA_ANALISTAS", pn.ler_lista("analista@exemplo.com, admin@exemplo.com"))
    monkeypatch.setattr(app, "PLATAFORMA_GESTORES", pn.ler_lista(""))
    monkeypatch.setattr(app, "NEXUS_PORTA_PRINCIPAL", "")
    monkeypatch.setattr(app, "_PASSES_USADOS", pn.NumerosUsados())
    monkeypatch.setattr(app, "_MODO_WEB", True)
    monkeypatch.setitem(app.app.config, "PROPAGATE_EXCEPTIONS", False)
    return app.app.test_client()


def _entrar_com_senha(c):
    assert c.post("/login", data={"senha": SENHA}).status_code == 302


def _passe(email, admin=False, destino="/painel"):
    import time
    return pn.assinar_passe({"v": 1, "email": email, "nome": "Pessoa de Teste", "admin": admin, "destino": destino,
                             "vence": time.time() + 60, "numero": "numero-de-teste-" + email.split("@")[0] + "-0001"},
                            CHAVE)


_TELAS = ("/painel", "/tempo-real", "/tempo-real/athon", "/monitor?fonte=pv&embed=1", "/gerencial",
          "/gerencial/disponibilidade", "/painel/falhas", "/ronda/monitor", "/cos", "/tokens", "/historico-plataforma",
          "/relatorio", "/relatorio/semanal")


def test_toda_tela_leva_o_aviso_mesmo_sem_a_chave_do_nexus(cli):
    """É correção de dado, não da porta: a sessão da senha também vence (30 dias). Sem a chave, nada de modo Nexus."""
    _entrar_com_senha(cli)
    for c in _TELAS:
        html = cli.get(c).get_data(as_text=True)
        assert html.count("window.gcSessaoDaPlataforma = {") == 1, c
        assert "var SEM_ADMIN = false;" in html, c
        assert "window.gcModoNexus=true" not in html and "modo-nexus" not in html, c
    assert "gcSessaoDaPlataforma" not in cli.get("/login").get_data(as_text=True)


def test_o_aviso_vai_inteiro_e_sem_fechar_o_script():
    js = app._AVISO_DE_SESSAO_JS
    assert "</script" not in js.lower() and "<!--" not in js
    assert "POR QUE EXISTE" not in js, "o cabeçalho do arquivo não precisa ir em toda página"
    assert "/*SEM_ADMIN*/false" in js


def test_na_moldura_o_aviso_vem_depois_do_calco_e_sabe_quem_e_admin(cli, monkeypatch):
    monkeypatch.setattr(app, "NEXUS_SSO_CHAVE", CHAVE)
    for email, admin, esperado in (("analista@exemplo.com", False, "true"), ("admin@exemplo.com", True, "false")):
        cli.get("/logout")
        r = cli.post("/painel/nexus/entrar", data={"passe": _passe(email, admin)}, headers=NA_MOLDURA)
        assert r.status_code == 303, r.get_data(as_text=True)[:300]
        html = cli.get("/painel", headers=NA_MOLDURA).get_data(as_text=True)
        cabeca = html[:html.index("</head>")]
        assert "window.gcModoNexus=true" in cabeca
        assert cabeca.index("nexus:rota") < cabeca.index("nexus:sessao-vencida"), "o calço do modo Nexus vem antes"
        assert f"var SEM_ADMIN = {esperado};" in cabeca, email


def test_o_que_e_de_outro_servico_nao_leva_o_aviso():
    for c in ("/gemeo/", "/gemeo/usina/1", "/os/", "/os/tickets", "/login", "/auth/callback", "/painel/nexus/entrar"):
        assert not app._recebe_o_aviso_de_sessao(c), c
    for c in ("/", "/painel", "/monitor", "/tokens", "/painel/usina/12"):
        assert app._recebe_o_aviso_de_sessao(c), c


# ── 3. cada tela guarda o último valor ──────────────────────────────────────────────────────────────────────────────
_RESPOSTAS = r"""
let R = {};
const chamadas = [];
globalThis.fetch = async (u, o) => { const k = String(u).split("?")[0], x = R[k] || R[u];
  chamadas.push(k); if (!x) throw new TypeError("Failed to fetch");
  return { ok: x[0] >= 200 && x[0] < 300, status: x[0], json: async () => x[1] }; };
const avisos = [];
const window = { gcSessaoDaPlataforma: { falhou(m, q) { avisos.push(["falhou", m, q]); }, voltou() { avisos.push(["voltou"]); },
  semAdmin: false, tokens: t => t } };
const ELS = {};
function E(id) { return ELS[id] || (ELS[id] = { id, innerHTML: "", textContent: "", hidden: false, style: {}, value: "",
  className: "", options: [], dataset: {}, disabled: false }); }
const document = { getElementById: E, body: { classList: { add() {}, remove() {} } } };
const espera = () => new Promise(r => setImmediate(r));
function out(o) { process.stdout.write("\n" + JSON.stringify(o)); }
"""
_401 = '[401, {error: "não autenticado"}]'


def test_painel_noc_401_nao_vira_energia_perdida_zero(tmp_path):
    """O caso da auditoria: 60 s depois de a sessão vencer, o Painel NOC dizia "Energia perdida 0,0 MWh"."""
    h = _ler("painel_portfolio.html")
    js = (_RESPOSTAS + _trecho(h, "const nf=", "\n")
          + "const COR={ok:()=>'g',atencao:()=>'a',critico:()=>'r',sem_comm:()=>'o'};"
            "function merge(){} function fillWallCli(){} function renderWall(){} function renderFeed(){} function renderRegion(){}"
            "let MACRO=null, GER=null, MAP={};\n"
          + _func(h, "_lerOk") + _func(h, "_hhmm") + _func(h, "boot") + _func(h, "stamp") + _func(h, "renderKpis")
          + """(async () => {
  R = {"/api/macro": [200, {resumo: {total: 80, ok: 70}, cache_ts: "14:32"}],
       "/api/gerencial": [200, {usinas: [{usina: "A", p50: 100, prod: 90, pot_mwp: 5}], portfolio: {pr: 80}, cache_ts: "14:30"}]};
  await boot(); const antes = E("kpis").innerHTML;
  R = {"/api/macro": %(x)s, "/api/gerencial": %(x)s};
  await boot(); const depois = E("kpis").innerHTML, upd = E("upd").innerHTML, foot = E("footsrc").textContent;
  R = {"/api/macro": [200, {resumo: {total: 81}, cache_ts: "14:40"}], "/api/gerencial": [500, {erro: "x", usinas: [], portfolio: {}}]};
  await boot(); const misto = E("kpis").innerHTML;
  R = {"/api/macro": [200, {usinas: [], resumo: {total: 0}, carregando: true}], "/api/gerencial": [200, {usinas: [{p50: 100, prod: 90, pot_mwp: 5}], portfolio: {}, cache_ts: "14:50"}]};
  await boot(); const montando = E("kpis").innerHTML;
  out({antes, depois, upd, foot, misto, montando, avisos});
})();""" % {"x": _401})
    r = _node(js, tmp_path)
    perda = re.compile(r"Energia perdida \(mês\)</div><div class=\"v num\">([^<]*)<")
    assert perda.search(r["antes"]).group(1).strip() == "10,0"
    assert r["depois"] == r["antes"], "o 401 trocou os números da tela"
    assert perda.search(r["depois"]).group(1).strip() != "0,0"
    assert "14:32" in r["upd"] and "não atualizou" in r["upd"] and "sessão vencida" in r["foot"]
    assert ">81<" in r["misto"] and perda.search(r["misto"]).group(1).strip() == "10,0", "o 500 do gerencial zerou a perda"
    assert ">81<" in r["montando"], "o 'carregando' do web que acabou de subir virou 0 usinas"
    assert ["falhou", "sessão vencida", "de 14:32 (ao vivo) e 14:30 (mês)"] in r["avisos"]


def test_painel_noc_sem_nenhuma_leitura_diz_que_falhou_e_nao_mostra_zero(tmp_path):
    h = _ler("painel_portfolio.html")
    js = (_RESPOSTAS + _trecho(h, "const nf=", "\n")
          + "const COR={ok:()=>'g',atencao:()=>'a',critico:()=>'r',sem_comm:()=>'o'};"
            "function merge(){} function fillWallCli(){} function renderWall(){} function renderFeed(){} function renderRegion(){}"
            "let MACRO=null, GER=null, MAP={};\n"
          + _func(h, "_lerOk") + _func(h, "_hhmm") + _func(h, "boot") + _func(h, "stamp") + _func(h, "renderKpis")
          + """(async () => { R = {"/api/macro": %(x)s, "/api/gerencial": %(x)s}; await boot();
  const k1 = E("kpis").innerHTML; GER = null; MACRO = null; renderKpis();
  out({k1, wall: E("wall").innerHTML, k2: E("kpis").innerHTML}); })();""" % {"x": _401})
    r = _node(js, tmp_path)
    assert r["k1"] == "" and "Falha ao carregar: sessão vencida" in r["wall"]
    assert "0,0" not in r["k2"] and "— <span class=\"u\">MWh</span>" in r["k2"], "sem leitura, 'Energia perdida' é —"


def test_tempo_real_401_guarda_os_cards_e_espera_1_min(tmp_path):
    """Entrada / Tempo real (/tempo-real e /tempo-real/<fonte>): o 401 virava "Fonte desconhecida" no nível 3 e a
    releitura martelava a cada 8 s."""
    h = _ler("Entrada.html")
    js = (_RESPOSTAS + "const desenhos=[], textos=[], timers=[]; let fonteSel='athon', esperando=0;"
          "function desenha(d){ desenhos.push(d.cache_ts); } function esqueleto(){ textos.push('esqueleto'); }"
          "function aviso(t){ textos.push(t); } globalThis.setTimeout=(f,ms)=>{ timers.push(ms); return 0; };\n"
          + "var ultimoTs = '';\n" + _func(h, "lerOk", "    ") + _func(h, "carrega", "    ")
          + """(async () => {
  R = {"/api/entrada/tempo-real": [200, {grupos: [{fonte: "SunOp"}], cache_ts: "14:32:05"}]}; carrega(); await espera(); await espera();
  R = {"/api/entrada/tempo-real": %(x)s}; carrega(); await espera(); await espera();
  const t401 = textos.slice(-1)[0], timer401 = timers.slice(-1)[0];
  R = {"/api/entrada/tempo-real": [500, {}]}; carrega(); await espera(); await espera();
  const t500 = textos.slice(-1)[0], timer500 = timers.slice(-1)[0];
  R = {"/api/entrada/tempo-real": [200, {aquecendo: true}]}; carrega(); await espera(); await espera();
  out({desenhos, t401, timer401, t500, timer500, ultimo: textos.slice(-1)[0], textos, avisos});
})();""" % {"x": _401})
    r = _node(js, tmp_path)
    assert r["desenhos"] == ["14:32:05"], "o erro foi desenhado como dado"
    assert "sessão vencida" in r["t401"] and "números de 14:32:05" in r["t401"] and r["timer401"] == 60000
    assert "a plataforma respondeu 500" in r["t500"] and r["timer500"] == 8000
    assert "esqueleto" not in r["textos"] and "montando de novo" in r["ultimo"], "o aquecimento apagou os cards"
    assert ["falhou", "a plataforma respondeu 500", "de 14:32:05"] in r["avisos"]


_MON_BASE = r"""
const FETCH_TMO_MS=90000, FETCH_LENTO_MS=10000;
const state={view:'strings', source:'thopen-pv'};
let RD={pv:null,loading:false,na:false,erro:null,cache:{},lento:false};
function render(){} function loadMeta(){} function loadGeracao(){} function loadPerda(){}
function _urlFor(v,s){ return '/api/data'; }
const _he=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
"""


def _mon(js_teste, tmp_path):
    h = _ler("Monitoramento (novo design).html")
    funcs = "".join(_func(h, n) for n in ("_erroHttp", "fetchJSON", "fonteForaHTML", "loadCurrent", "_guardaUltimo",
                                          "_exigeLinhas", "_pollFresco"))
    return _node(_RESPOSTAS.replace("const window =", "globalThis.window =") + _MON_BASE + funcs + js_teste, tmp_path)


def test_monitoramento_401_nao_vira_os_exemplos_do_prototipo(tmp_path):
    """Sem `rows`, o Monitoramento desenha os exemplos do protótipo (76 usinas, 505 strings ativas...). O 401 voltava do
    fetchJSON como payload: Atualizar depois de 12 h trocava a fonte pelos exemplos."""
    r = _mon("""(async () => {
  R = {"/api/data": [200, {rows: [{usina: "A"}], cache_ts: "14:32"}]}; await loadCurrent(false);
  R = {"/api/data": %(x)s}; await loadCurrent(true);
  const guardou = RD.pv && RD.pv.rows && RD.pv.rows[0].usina, erro1 = RD.erro;
  RD.cache = {}; await loadCurrent(false);
  const e2 = RD.erro && {sessao: RD.erro.sessao, http: RD.erro.http}, pv2 = RD.pv, html = fonteForaHTML(RD.erro, "os dados desta fonte");
  R = {"/api/data": [500, {error: "boom"}]}; await loadCurrent(false); const m500 = RD.erro && RD.erro.message;
  R = {"/api/data": [200, {error: "sem token"}]}; await loadCurrent(false); const m200 = RD.erro && RD.erro.http;
  R = {"/api/plant/1": [504, {error: "falha", detalhe: "ReadTimeout"}]}; const corpo = await fetchJSON("/api/plant/1");
  out({guardou, erro1, e2, pv2, html, m500, m200, corpo});
})();""" % {"x": _401}, tmp_path)
    assert r["guardou"] == "A" and r["erro1"] is None, "a releitura com a sessão vencida apagou a fonte da tela"
    assert r["e2"] == {"sessao": True, "http": 401} and r["pv2"] is None
    assert "Sessão vencida" in r["html"] and "Nada foi trocado por zero" in r["html"]
    assert "500" in r["m500"] and "boom" in r["m500"]
    assert r["m200"] == 200, "200 com {error} e sem rows também não é dado"
    assert r["corpo"] == {"error": "falha", "detalhe": "ReadTimeout"}, "sem exigeOk, o 504 segue chegando a quem chama"


def test_monitoramento_poll_do_stale_nao_troca_a_fonte_pelo_401(tmp_path):
    r = _mon("""(async () => {
  const _st = setTimeout; globalThis.setTimeout = (f, ms) => ms === 8000 ? (queueMicrotask(f), 0) : _st(f, ms);
  RD.pv = {rows: [{usina: "A"}]}; RD.cache["strings|thopen-pv"] = RD.pv;
  R = {"/api/data": %(x)s}; await _pollFresco("/api/data", "strings|thopen-pv", "strings", "thopen-pv");
  out({usina: RD.pv.rows ? RD.pv.rows[0].usina : null, erro: RD.pv.error || null});
})();""" % {"x": _401}, tmp_path)
    assert r == {"usina": "A", "erro": None}


def test_monitoramento_sem_dado_esconde_os_cards_de_exemplo():
    h = _ler("Monitoramento (novo design).html")
    assert "if(RD.erro&&(RD.erro.fonteFora||RD.erro.sessao||RD.erro.http)) panel=fonteForaHTML" in h
    assert "(RD.erro&&!RD.pv))?'':renderKPIs(v)" in h


def test_disponibilidade_401_nao_vira_calculando_a_primeira_varredura(tmp_path):
    h = _ler("disponibilidade.html")
    js = (_RESPOSTAS + "let DADOS=null; const HEAT={pag:0,cli:null}; const renders=[]; function render(j){ renders.push(j.mes); }"
          "function mesLabel(m){ return m; } const $=id=>E(id); E('frio').hidden=true; E('conteudo').hidden=true;\n"
          + _func(h, "naoLeu") + _func(h, "carregar")
          + """(async () => {
  R = {"/api/gerencial/disponibilidade": [200, {quente: true, mes: "2026-10", meses: ["2026-10"], clientes: [], usinas: [], atualizado: 1791640000}]};
  await carregar(); const d1 = DADOS;
  R = {"/api/gerencial/disponibilidade": %(x)s}; await carregar();
  out({renders, frio: E("frio").hidden, conteudo: E("conteudo").hidden, mesmo: DADOS === d1, avisos});
})();""" % {"x": _401})
    r = _node(js, tmp_path)
    assert r["renders"] == ["2026-10"] and r["mesmo"]
    assert r["frio"] is True and r["conteudo"] is False, "o 401 escondeu os números atrás do 'Calculando…'"


def test_disponibilidade_sem_leitura_diz_o_motivo(tmp_path):
    h = _ler("disponibilidade.html")
    js = (_RESPOSTAS + "let DADOS=null; const HEAT={pag:0,cli:null}; function render(){} function mesLabel(m){ return m; }"
          "const $=id=>E(id);\n" + _func(h, "naoLeu") + _func(h, "carregar")
          + """(async () => { R = {"/api/gerencial/disponibilidade": [500, {}]}; await carregar();
  out({frio: E("frio").innerHTML}); })();""")
    r = _node(js, tmp_path)
    assert "Não consegui ler a disponibilidade" in r["frio"] and "HTTP 500" in r["frio"]
    assert "Calculando a primeira varredura" not in r["frio"]


def test_monitor_da_ronda_401_nao_diz_desligada_nem_fora_do_ar(tmp_path):
    h = _ler("ronda_monitor.html")
    js = (_RESPOSTAS + "const desenhos=[]; function svcBadge(d){ desenhos.push('svc'); E('svcTit').textContent='WhatsApp conectado'; }"
          "function slotCards(){ desenhos.push('slots'); } function hist(){ desenhos.push('hist'); }\n"
          + "let RONDA_LIDA='';\n" + _func(h, "load")
          + """(async () => {
  R = {"/api/ronda/whats/status": [200, {enabled: true, agora: "2026-10-10 14:32:05", servico: {status: "conectado"}}]};
  await load(); const banner1 = E("offBanner").style.display;
  R = {"/api/ronda/whats/status": %(x)s}; await load();
  out({desenhos, banner1, banner2: E("offBanner").style.display, tit: E("svcTit").textContent, upd: E("upd").textContent});
})();""" % {"x": _401})
    r = _node(js, tmp_path)
    assert r["desenhos"] == ["svc", "slots", "hist"], "o 401 foi desenhado como estado"
    assert r["banner1"] == r["banner2"] == "none", "o 401 dizia 'A ronda automática está DESLIGADA'"
    assert r["tit"] == "WhatsApp conectado"
    assert "não atualizou (sessão vencida)" in r["upd"] and "14:32:05" in r["upd"]


def test_strings_e_trackers_401_nao_apaga_o_mes_da_tela(tmp_path):
    h = _ler("falhas.html")
    js = (_RESPOSTAS + "let D={mes:'2026-10', gerado_em:'2026-10-10 14:32:00'}; const d0=D; const desenhos=[];"
          "function desenha(){ desenhos.push(1); } function meses(){} const rotMes=m=>'mes '+m; const $=id=>E(id);"
          "E('frio').hidden=true;\n" + _func(h, "carrega", "  ")
          + """(async () => { E("f-mes").value = "2026-09"; R = {"/api/painel/falhas": %(x)s}; await carrega("2026-09");
  out({mesmo: D === d0, desenhos, frio: E("frio").hidden, fonte: E("fonte").textContent, sel: E("f-mes").value}); })();"""
          % {"x": _401})
    r = _node(js, tmp_path)
    assert r["mesmo"] and r["desenhos"] == [] and r["frio"] is True, "o 401 virou 'ainda está sendo montado'"
    assert "sessão vencida" in r["fonte"] and "mes 2026-10" in r["fonte"] and r["sel"] == "2026-10"


def test_gerencial_401_nao_vira_mes_sem_usina(tmp_path):
    h = _ler("gerencial.html")
    js = (_RESPOSTAS + "let RAW={ano:2026, mes_num:10, usinas:[{usina:'A'}]}; const r0=RAW; const aplicou=[];"
          "function _fillCli(){} function _aplica(){ aplicou.push(1); } function loadDisp(){}\n" + _func(h, "load")
          + """(async () => { R = {"/api/gerencial": %(x)s}; await load(2026, 9);
  out({mesmo: RAW === r0, aplicou, cov: E("cov").textContent, mes: E("fMes").value}); })();""" % {"x": _401})
    r = _node(js, tmp_path)
    assert r["mesmo"] and r["aplicou"] == [], "o 401 virou um mês sem usina, totais em zero"
    assert "sessão vencida" in r["cov"] and "10/2026" in r["cov"] and r["mes"] == "2026-10"


def test_chaves_das_fontes_401_nao_diz_zero_em_verde(tmp_path):
    h = _ler("tokens.html")
    js = (_RESPOSTAS + "const renders=[]; function render(d){ renders.push(d.tokens.length); E('atualizado').textContent='lido às 14:32'; }\n"
          + "let TOKENS_LIDOS = \"\";\n" + _func(h, "carregar")
          + """(async () => { R = {"/api/tokens": [200, {tokens: [{fonte: "sunop"}]}]}; await carregar();
  R = {"/api/tokens": %(x)s}; await carregar();
  out({renders, at: E("atualizado").textContent}); })();""" % {"x": _401})
    r = _node(js, tmp_path)
    assert r["renders"] == [1], "o 401 virou 'Precisam de você: 0'"
    assert "não atualizou (sessão vencida)" in r["at"] and "14:32" in r["at"]


def test_acompanhamento_cos_401_nao_diz_montando_o_indice(tmp_path):
    h = _ler("cos.html")
    js = (_RESPOSTAS + "const timers=[]; globalThis.setTimeout=(f,ms)=>{ timers.push(ms); return 0; }; function iniciar(){}\n"
          "R = {\"/api/cos/mtta\": %s};\n" % _401
          + _trecho(h, "(function carrega(tentativa) {", "})(0);")
          + "\n(async () => { await espera(); await espera(); out({est: E('estado').innerHTML, timers}); })();")
    r = _node(js, tmp_path)
    assert "Sessão vencida" in r["est"] and "Montando o índice" not in r["est"] and r["timers"] == [60000]
