# -*- coding: utf-8 -*-
"""Strings e trackers — a tabela única por OCORRÊNCIA DO INVERSOR, o drill diário, o Vincular OS só no clique e o Excel
(Levi, 20/10/2026: "Em strings quero a junção das duas tabelas (...) Por inversor e dia como tabela principal e única (...)
1.5 Opção de vincular OS (...) 1.6 para ocorrências com mais de um dia quero que ao clicar na linha abra um drill (...)
1.7 A OS só carrega se eu clicar em vincular (...) 2 - Tire o filtro de fonte").

A página roda INTEIRA no node (o <script> dela, com um DOM de mentira e o fetch dublado), como os outros testes de tela
rodam funções extraídas: o que se confere é o código que o navegador roda. Os casos são os do dado real de outubro (pacote
de 20/10 13:45): Inhapi 3.3 (Ipv1–4 paradas desde 01/10 = 1 linha, 8.024,8 kWh, 1.114,8 estimados em 4 dias), Guatambu
2.5 (4 ocorrências) e Guaratinguetá V 1.3 (07 a 14/10: 10 strings distintas, no máximo 6 juntas, 1.273,8 kWh)."""
import json
import os
import re
import shutil
import subprocess

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = open(os.path.join(RAIZ, "plataforma", "templates", "falhas.html"), encoding="utf-8").read()
NODE = shutil.which("node")
precisa_node = pytest.mark.skipif(NODE is None, reason="sem node")


def _script():
    return re.findall(r"<script>(.*?)</script>", HTML, re.S)[1]          # o 1º é o tema do Nexus


# o que o teste enxerga de dentro da página (o IIFE esconde tudo)
GANCHO = ("globalThis.__T = {S, desenha, ocorrencias, planilha, ordenadas, linhas, naConta, base, idLinha, DESC_VIS, "
          "get OC() { return OC; }, get D() { return D; }, get VINC() { return VINC; }};\n")

DOM = r"""
const ELS = {};
function el(id) {
  if (!ELS[id]) ELS[id] = {id, innerHTML: '', textContent: '', hidden: false, value: '', title: '', disabled: false, dataset: {},
    style: {}, _ouv: {}, addEventListener(t, f) { (this._ouv[t] = this._ouv[t] || []).push(f); },
    setAttribute(k, v) { this['@' + k] = String(v); }, getAttribute(k) { return this['@' + k]; },
    classList: {toggle() {}, add() {}, remove() {}, contains() { return false; }}, focus() {}, scrollIntoView() {},
    getBoundingClientRect() { return {bottom: 0, right: 0}; }, offsetHeight: 0, offsetWidth: 0};
  return ELS[id];
}
globalThis.document = {getElementById: el, querySelectorAll: () => [], querySelector: () => null, addEventListener() {},
  createElement: () => ({click() {}, remove() {}}), body: {appendChild() {}}, cookie: ''};
globalThis.location = {hash: '', search: '', href: 'http://bancada/painel/falhas'};
globalThis.history = {replaceState() {}};
globalThis.innerHeight = 800; globalThis.innerWidth = 1200;
const PEDIDOS = [];
let RESP = {};
globalThis.fetch = async (u, o) => {
  PEDIDOS.push({metodo: (o && o.method) || 'GET', url: String(u), corpo: o && o.body ? JSON.parse(o.body) : null});
  const k = String(u).split('?')[0], x = RESP[k];
  if (!x) throw new TypeError('Failed to fetch');
  return {ok: x[0] >= 200 && x[0] < 300, status: x[0], json: async () => JSON.parse(JSON.stringify(x[1])),
          blob: async () => new Blob(['xlsx'])};
};
const espera = async () => { for (let i = 0; i < 30; i++) await new Promise(r => setTimeout(r, 0)); };
const out = o => process.stdout.write('\n' + JSON.stringify(o));
// eventos de mentira: o clique na linha que abre, num botão de OS (data-os) e o Enter na linha
const naLinha = id => ({target: {closest: s => s === 'tr.cn-linha' ? {dataset: {id}} : null, matches: () => false},
                        stopPropagation() {}, preventDefault() {}});
const noBotao = (acao, id, n) => {
  const b = {dataset: {os: acao, n: n == null ? undefined : String(n)}, disabled: false,
             closest: s => s.startsWith('tr[data-id]') ? {dataset: {id}} : null};
  return {target: {closest: s => s === '[data-os]' || s.startsWith('a, button') ? b : null, matches: () => false},
          stopPropagation() {}, preventDefault() {}};
};
const clica = async ev => { for (const f of ELS.tab._ouv.click) await f(ev); await espera(); };
"""


def _roda(tmp_path, pacote, corpo_js, vinculos=None, resp=None, antes=""):
    """`antes`: JS que roda antes da página (segurar um pedido, encurtar o teto) — a página pede tudo ao carregar."""
    if not NODE:
        pytest.skip("sem node")
    r = {"/api/painel/falhas": [200, pacote],
         "/api/painel/falhas/desconsideradas": [200, {"ok": True, "strings": {}, "trackers": {}}],
         "/api/painel/falhas/vinculos": [200, {"ok": True, "vinculos": vinculos or [], "lido_em": "2026-10-20 15:00"}]}
    r.update(resp or {})
    pag = _script()
    fim = pag.rindex("})();")
    js = (DOM + antes + f"RESP = {json.dumps(r, ensure_ascii=False)};\n" + pag[:fim] + GANCHO + pag[fim:]
          + "\n(async () => { await espera(); const T = globalThis.__T;\n" + corpo_js
          + "\n})().catch(e => { console.error(e && e.stack || e); process.exit(1); });\n")
    arq = tmp_path / "pagina.js"
    arq.write_text(js, encoding="utf-8")
    p = subprocess.run([NODE, str(arq)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert p.returncode == 0, p.stderr[-3000:]
    return json.loads(p.stdout.strip().splitlines()[-1])


# ── o dado (os episódios e as linhas do dia reais de outubro, só com os campos que a tela usa) ─────────────────────
def ep(usina, inv, string, inicio, fim, motivo, d0, d1, perda, flags=(), fonte="pv", pid="1", cliente="Thopen"):
    return {"chave": f"{fonte}|{pid}|{inv}|{string}|{inicio[:10]}", "fonte": fonte, "plant_id": pid, "cliente": cliente,
            "usina": usina, "inversor": inv, "string": string, "inicio": inicio, "fim": fim, "fim_motivo": motivo,
            "d0": d0, "d1": d1, "dias": int(d1[8:]) - int(d0[8:]) + 1, "perda_kwh": perda, "perda_nominal_kwh": 0,
            "flags": list(flags)}


def dia(usina, inv, d, strings, perda, flags=(), fonte="pv", dur=12.0, janela="06:00–18:00"):
    return {"dia": d, "fonte": fonte, "cliente": "Thopen", "usina": usina, "inversor": inv, "qtd": len(strings),
            "strings": ", ".join(strings), "dur_h": dur, "dur_min_h": dur, "janela": janela, "perda_kwh": perda,
            "flags": list(flags)}


EST_DIA, SEM_GER = "dias sem varredura estimados", "sem geração no dia (4,5 kWh/kWp)"
IPV = [f"Ipv{i}" for i in range(1, 5)]
INHAPI_EPS = [ep("Inhapi", "Inversor 3.3", s, "2026-10-01 06:30", None, "em aberto", "2026-10-01", "2026-10-20", 2006.2,
                 [EST_DIA, SEM_GER], pid="18748739") for s in IPV]
_INHAPI_PERDA = [438.9, 409.9, 444.6, 437.3, 347.9, 312.5, 395.1, 446.6, 376.5, 434.7, 395.8, 499.4, 500.1, 510.6, 448.5,
                 428.7, 160.9, 459.3, 325.7, 251.7]
_INHAPI_FLAG = {9: [EST_DIA], 17: [EST_DIA], 19: [SEM_GER], 20: [SEM_GER]}
INHAPI_DIAS = [dia("Inhapi", "Inversor 3.3", f"2026-10-{d:02d}", IPV, p, _INHAPI_FLAG.get(d, ()))
               for d, p in enumerate(_INHAPI_PERDA, 1)]


def _gt(s, ini, fim, mot, d0, d1, p, fl=()):
    return ep("Guatambu", "Inversor 2.5", s, ini, fim, mot, d0, d1, p, fl, pid="18747509")


GUATAMBU_EPS = (
    [_gt(s, "2026-10-03 09:50", "2026-10-05 06:30", "voltou de madrugada", "2026-10-03", "2026-10-04", 138.9) for s in ("Ipv14", "Ipv15")]
    + [_gt(s, "2026-10-05 09:20", "2026-10-16 17:40", "voltou", "2026-10-05", "2026-10-16", p, [EST_DIA])
       for s, p in (("Ipv10", 506.9), ("Ipv12", 506.9), ("Ipv9", 498.8))]
    + [_gt(s, "2026-10-06 07:00", "2026-10-16 17:40", "voltou", "2026-10-06", "2026-10-16", 474.7, [EST_DIA]) for s in ("Ipv7", "Ipv11")]
    + [_gt("Ipv10", "2026-10-18 14:30", "2026-10-18 17:40", "voltou", "2026-10-18", "2026-10-18", 26.3)]
    + [_gt(s, "2026-10-19 07:00", None, "em aberto", "2026-10-19", "2026-10-20", 146.6, [SEM_GER]) for s in ("Ipv10", "Ipv12", "Ipv9", "Ipv7", "Ipv11")])
_G5 = ["Ipv7", "Ipv9", "Ipv10", "Ipv11", "Ipv12"]
GUATAMBU_DIAS = ([dia("Guatambu", "Inversor 2.5", "2026-10-05", ["Ipv9", "Ipv10", "Ipv12"], 96.7)]
                 + [dia("Guatambu", "Inversor 2.5", f"2026-10-{d:02d}", _G5, p, [EST_DIA] if d == 9 else ())
                    for d, p in zip(range(6, 17), [184.3, 523.7, 168.0, 129.2, 76.0, 183.8, 69.7, 131.0, 241.1, 369.9, 288.6])])


def _gv(s, ini, fim, mot, d0, d1, p, fl=()):
    return ep("Guaratinguetá V", "Inversor 1.3", s, ini, fim, mot, d0, d1, p, fl, fonte="pg", pid="26")


_ST12 = [f"ST {n}" for n in (13, 16, 17, 18, 20, 21, 22, 23, 25, 26, 27, 28)]
GUARA_EPS = (
    [_gv(s, "2026-10-01 06:30", "2026-10-04 06:24", "voltou de madrugada", "2026-10-01", "2026-10-03", 78.7) for s in _ST12]
    + [_gv(s, "2026-10-05 08:10", "2026-10-06 06:22", "voltou de madrugada", "2026-10-05", "2026-10-05", 67.9, [SEM_GER]) for s in _ST12]
    + [_gv(f"ST {n}", "2026-10-07 08:50", "2026-10-10 06:18", "voltou de madrugada", "2026-10-07", "2026-10-09", 152.8, [SEM_GER])
       for n in (13, 16, 17, 18, 22)]
    + [_gv("ST 20", "2026-10-07 08:50", "2026-10-14 11:00", "voltou", "2026-10-07", "2026-10-14", 311.8, [SEM_GER])]
    + [_gv(f"ST {n}", "2026-10-13 12:00", "2026-10-14 11:00", "voltou", "2026-10-13", "2026-10-14", 49.5) for n in (25, 26, 27, 28)])


def pacote(episodios=(), rows=(), trk=(), trackers_dia=()):
    return {"mes": "2026-10", "meses": ["2026-09", "2026-10"], "quente": True, "periodo": ["2026-10-01", "2026-10-20"],
            "gerado_em": "2026-10-20 13:45",
            "regua": {"kwp_trk_tipico": 55, "yield_padrao": 4.5, "sol_min_graus": 8, "janela": "06–18 h", "janela_strings": "06–18 h"},
            "strings": {"episodios": list(episodios), "rows": list(rows), "qualidade": {}, "desconsideradas": []},
            "trackers": {"rows": list(trk), "qualidade": {}, "sem_comunicacao": [], "desconsideradas": []},
            "trackers_dia": list(trackers_dia)}


RESUMO_OC = """
const oc = T.OC.map(o => ({usina: o.usina, inv: o.inversor, inicio: o.inicio, fim: o.fim, motivo: o.fim_motivo, qtd: o.qtd,
  strings: o.strings, max: o.max_juntas, abertas: o.abertas, dias: o.dias, perda: o.perda_kwh, est: o.est_kwh, est_dias: o.est_dias,
  soma: Math.round(o.membros.reduce((a, e) => a + e.perda_kwh, 0) * 10) / 10, det: o.det.map(x => [x.dia, x.perda])}));
"""


# ── 1. o agrupamento em ocorrências ─────────────────────────────────────────────────────────────────────────────
@precisa_node
def test_inhapi_guatambu_e_guaratingueta_viram_as_ocorrencias_do_dado_real(tmp_path):
    r = _roda(tmp_path, pacote(INHAPI_EPS + GUATAMBU_EPS + GUARA_EPS, INHAPI_DIAS + GUATAMBU_DIAS), RESUMO_OC + "out(oc);")
    por = {}
    for o in r:
        por.setdefault((o["usina"], o["inv"]), []).append(o)
    # Inhapi 3.3: as 4 strings paradas desde 01/10 06:30 são UMA linha (eram 20 na visão por inversor e dia)
    [inh] = por[("Inhapi", "Inversor 3.3")]
    assert (inh["qtd"], inh["strings"], inh["abertas"], inh["fim"], inh["motivo"], inh["dias"]) == (4, "Ipv1, Ipv2, Ipv3, Ipv4", 4, None, "em aberto", 20)
    assert inh["perda"] == 8024.8
    # Guatambu 2.5: 4 ocorrências — a de 03/10 fecha de madrugada em 05/10 06:30, antes da queda das 09:20
    gt = sorted(por[("Guatambu", "Inversor 2.5")], key=lambda o: o["inicio"])
    assert [(o["inicio"], o["fim"], o["qtd"], o["perda"]) for o in gt] == [
        ("2026-10-03 09:50", "2026-10-05 06:30", 2, 277.8), ("2026-10-05 09:20", "2026-10-16 17:40", 5, 2462.0),
        ("2026-10-18 14:30", "2026-10-18 17:40", 1, 26.3), ("2026-10-19 07:00", None, 5, 733.0)]
    assert [o["dias"] for o in gt] == [2, 12, 1, 2]
    # Guaratinguetá V 1.3, 07 a 14/10: a ST20 segura a ocorrência e liga as ST13–22 às ST25–28 — 10 distintas, 6 juntas
    gv = sorted(por[("Guaratinguetá V", "Inversor 1.3")], key=lambda o: o["inicio"])
    assert len(gv) == 3
    assert (gv[2]["qtd"], gv[2]["max"], gv[2]["perda"], gv[2]["dias"], gv[2]["fim"]) == (10, 6, 1273.8, 8, "2026-10-14 11:00")
    assert gv[2]["strings"] == "ST 13, ST 16, ST 17, ST 18, ST 20, ST 22, ST 25, ST 26, ST 27, ST 28"     # ordem natural
    assert gv[0]["max"] == gv[0]["qtd"] == 12


@precisa_node
def test_a_perda_da_ocorrencia_e_a_soma_das_paradas_dela(tmp_path):
    r = _roda(tmp_path, pacote(INHAPI_EPS + GUATAMBU_EPS + GUARA_EPS, INHAPI_DIAS + GUATAMBU_DIAS), RESUMO_OC + "out(oc);")
    assert all(o["perda"] == o["soma"] for o in r)
    total_eps = round(sum(e["perda_kwh"] for e in INHAPI_EPS + GUATAMBU_EPS + GUARA_EPS), 1)
    assert round(sum(o["perda"] for o in r), 1) == total_eps          # partição: nada conta duas vezes
    # o drill fecha com a ocorrência: Guatambu 2.5 (05 a 16/10) = 2.462,0 nos 12 dias
    g2 = next(o for o in r if o["usina"] == "Guatambu" and o["inicio"] == "2026-10-05 09:20")
    assert len(g2["det"]) == 12 and round(sum(p for _, p in g2["det"]), 1) == 2462.0


@precisa_node
def test_juncao_inclusiva_quem_comeca_no_fim_da_outra_entra_nela(tmp_path):
    # Castelo do Piauí 2.2 (14/10): a string 23 volta às 11:20 e outra cai às 11:20, na mesma leitura. A junção estrita
    # ("antes do fim") partia em duas: 349 ocorrências no pacote das 13:45 em vez de 344
    eps = [ep("Castelo do Piauí", "Inversor 2.2", "23", "2026-10-14 09:00", "2026-10-14 11:20", "voltou", "2026-10-14", "2026-10-14", 10.0, pid="CPI"),
           ep("Castelo do Piauí", "Inversor 2.2", "24", "2026-10-14 11:20", "2026-10-14 15:00", "voltou", "2026-10-14", "2026-10-14", 12.0, pid="CPI"),
           ep("Castelo do Piauí", "Inversor 2.2", "25", "2026-10-14 15:01", "2026-10-14 17:00", "voltou", "2026-10-14", "2026-10-14", 5.0, pid="CPI")]
    r = _roda(tmp_path, pacote(eps), RESUMO_OC + "out(oc);")
    assert sorted((o["inicio"], o["qtd"], o["max"], o["perda"]) for o in r) == [("2026-10-14 09:00", 2, 1, 22.0), ("2026-10-14 15:01", 1, 1, 5.0)]


@precisa_node
def test_o_aproximado_e_pelo_dia_e_nao_pela_parada(tmp_path):
    # Inhapi 3.3: só 09, 17, 19 e 20/10 têm estimativa — 1.114,8 de 8.024,8 kWh (pela parada, a linha inteira levava ≈)
    js = RESUMO_OC + """T.desenha(); out({oc, tab: ELS.tab.innerHTML});"""
    r = _roda(tmp_path, pacote(INHAPI_EPS + GUATAMBU_EPS, INHAPI_DIAS + GUATAMBU_DIAS), js)
    inh = next(o for o in r["oc"] if o["usina"] == "Inhapi")
    assert (inh["est"], inh["est_dias"]) == (1114.8, 4)
    assert "1.114,8 de 8.024,8 kWh estimados (4 dias)" in r["tab"].replace("&quot;", '"')
    g2 = next(o for o in r["oc"] if o["usina"] == "Guatambu" and o["inicio"] == "2026-10-05 09:20")
    assert g2["est"] == 129.2                                         # só o 09/10
    g1 = next(o for o in r["oc"] if o["usina"] == "Guatambu" and o["inicio"] == "2026-10-03 09:50")
    assert g1["est"] == 0                                             # dia sem estimativa: sem ≈


@precisa_node
def test_sem_as_linhas_do_dia_o_aproximado_volta_a_ser_o_da_parada(tmp_path):
    # pacote antigo sem strings.rows: cai na flag dos episódios, como a tela fazia antes
    r = _roda(tmp_path, pacote(INHAPI_EPS), RESUMO_OC + "out(oc);")
    assert r[0]["est"] == r[0]["perda"] == 8024.8 and r[0]["det"] == []


@precisa_node
def test_parado_agora_parcial_diz_quantas_ainda_estao_paradas(tmp_path):
    eps = [ep("Colider 1", "Inversor 1.3", "ST1", "2026-10-10 08:00", None, "em aberto", "2026-10-10", "2026-10-20", 100.0, pid="COL"),
           ep("Colider 1", "Inversor 1.3", "ST2", "2026-10-10 08:00", "2026-10-12 10:00", "voltou", "2026-10-10", "2026-10-12", 30.0, pid="COL"),
           ep("Colider 1", "Inversor 1.3", "ST3", "2026-10-11 09:00", "2026-10-12 10:00", "voltou", "2026-10-11", "2026-10-12", 20.0, pid="COL"),
           ep("Colider 1", "Inversor 1.4", "ST9", "2026-10-02 08:00", "2026-10-02 12:00", "voltou", "2026-10-02", "2026-10-02", 3.0, pid="COL")]
    js = RESUMO_OC + """T.desenha(); const antes = ELS.tab.innerHTML;
      T.S.aberto = true; T.desenha(); out({oc, antes, so: T.linhas().map(o => o.inversor), tab: ELS.tab.innerHTML, conta: ELS.conta.innerHTML});"""
    r = _roda(tmp_path, pacote(eps), js)
    o = next(x for x in r["oc"] if x["inv"] == "Inversor 1.3")
    assert (o["abertas"], o["qtd"], o["fim"], o["motivo"]) == (1, 3, None, "em aberto")
    assert "1 de 3 ainda paradas" in r["antes"] and "1 parada agora" in r["antes"]
    assert r["so"] == ["Inversor 1.3"]                               # "Só parados agora" fica com a ocorrência aberta
    assert "<b>1</b> ocorrência" in r["conta"]


@precisa_node
def test_a_dica_do_total_diz_o_que_a_lista_soma_quando_a_faixa_soma_outra_coisa(tmp_path):
    # pacote de 20/10 13:45 com "Só parados agora": a faixa diz 79,4 MWh (as strings paradas agora) e a lista 88,5 MWh (as
    # 66 ocorrências inteiras, com as strings delas que já voltaram). A regra é do Levi e fica; o total da lista diz o que
    # soma. Aqui: a 1.3 tem a ST1 parada (100 kWh) e a ST2 e a ST3 que já voltaram (30 + 20)
    eps = [ep("Colider 1", "Inversor 1.3", "ST1", "2026-10-10 08:00", None, "em aberto", "2026-10-10", "2026-10-20", 100.0, pid="COL"),
           ep("Colider 1", "Inversor 1.3", "ST2", "2026-10-10 08:00", "2026-10-12 10:00", "voltou", "2026-10-10", "2026-10-12", 30.0, pid="COL"),
           ep("Colider 1", "Inversor 1.3", "ST3", "2026-10-11 09:00", "2026-10-12 10:00", "voltou", "2026-10-11", "2026-10-12", 20.0, pid="COL"),
           ep("Colider 1", "Inversor 1.4", "ST9", "2026-10-02 08:00", "2026-10-02 12:00", "voltou", "2026-10-02", "2026-10-02", 3.0, pid="COL")]
    js = r"""const tit = () => (ELS.conta.innerHTML.match(/<b title="([^"]*)">/) || [])[1] || null;
      const faixa = () => ELS.numeros.innerHTML.match(/<span class="v" title="[^"]*">([^<]*)<\/span>/)[1];
      const v = () => ({tit: tit(), conta: ELS.conta.innerHTML.replace(/<[^>]+>/g, ''), faixa: faixa()});
      const r = {};
      T.desenha(); r.nada = v();
      T.S.aberto = true; T.desenha(); r.aberto = v();
      T.S.aberto = false; T.S.str = 'ST2'; T.desenha(); r.str = v();
      T.S.aberto = true; T.desenha(); r.os_dois = v();
      T.S.aberto = false; T.S.str = null; T.S.q = 'st2'; T.desenha(); r.busca = v();
      T.S.q = 'colider'; T.desenha(); r.busca_usina = v();
      T.S.q = ''; T.S.aba = 'trk'; T.S.aberto = true; T.desenha(); r.trk = tit();
      out(r);"""
    r = _roda(tmp_path, pacote(eps), js)
    assert r["nada"]["tit"] is None and r["nada"]["conta"] == "2 ocorrências · 153 kWh no recorte"
    assert (r["aberto"]["faixa"], r["aberto"]["conta"]) == ("100 kWh", "1 ocorrência · 150 kWh no recorte")
    assert r["aberto"]["tit"] == ("Soma das ocorrências inteiras: inclui as strings da mesma ocorrência que já voltaram. "
                                  "A faixa de cima soma só as strings paradas agora.")
    assert (r["str"]["faixa"], r["str"]["conta"]) == ("30 kWh", "1 ocorrência · 150 kWh no recorte")
    assert r["str"]["tit"] == ("Soma das ocorrências inteiras: inclui as outras strings da mesma ocorrência. "
                               "A faixa de cima soma só a string do filtro.")
    assert r["os_dois"]["tit"] == ("Soma das ocorrências inteiras: inclui as outras strings da mesma ocorrência e as que já "
                                   "voltaram. A faixa de cima soma só a string do filtro, parada agora.")
    # a busca que acha uma string tem o mesmo efeito; a que acha a usina, não (as duas somas são a mesma)
    assert r["busca"]["tit"].endswith("A faixa de cima soma só as strings da busca.") and r["busca"]["faixa"] == "30 kWh"
    assert r["busca_usina"]["tit"] is None and r["trk"] is None


@precisa_node
def test_a_volta_de_madrugada_nao_ganha_hora(tmp_path):
    # 43% das ocorrências de outubro voltaram de madrugada: o fim é o nascer do dia seguinte, não uma leitura
    r = _roda(tmp_path, pacote(GUATAMBU_EPS[:2]), "T.desenha(); out(ELS.tab.innerHTML);")
    assert "05/10</span><span class=\"det\"" in r and "de madrugada" in r and "05/10 06:30" not in r
    assert "≈ " in r                                                  # e a duração até o nascer é aproximada


# ── 2. o drill ─────────────────────────────────────────────────────────────────────────────────────────────────
@precisa_node
def test_o_drill_abre_na_linha_de_varios_dias_e_continua_aberto_depois_de_redesenhar(tmp_path):
    js = """T.desenha();
      const inh = T.OC.find(o => o.usina === 'Inhapi'), um = T.OC.find(o => o.usina === 'Guatambu' && o.inicio.startsWith('2026-10-18'));
      const id = T.idLinha(inh), antes = ELS.tab.innerHTML;
      await clica(naLinha(id)); const aberto = ELS.tab.innerHTML, abre = [...T.S.abre];
      T.desenha(); const depois = ELS.tab.innerHTML;
      for (const f of ELS.tab._ouv.keydown) f({key: 'Enter', target: {closest: () => null, matches: s => s === 'tr.cn-linha', dataset: {id}}, preventDefault() {}});
      out({id, umId: T.idLinha(um), antes, aberto, abre, depois, fechado: ELS.tab.innerHTML, abreFim: [...T.S.abre]});"""
    r = _roda(tmp_path, pacote(INHAPI_EPS + GUATAMBU_EPS, INHAPI_DIAS + GUATAMBU_DIAS), js)
    linha = re.compile(r'<tr class="cn-linha" data-id="%s" tabindex="0" aria-expanded="(\w+)"' % re.escape(r["id"]))
    assert linha.search(r["antes"]).group(1) == "false" and 'class="cn-detalhe"' not in r["antes"]
    assert r["abre"] == [r["id"]]
    for html in (r["aberto"], r["depois"]):                          # o desenha() refaz a tabela e o aberto fica aberto
        assert linha.search(html.replace(' class="cn-linha com-detalhe"', ' class="cn-linha"')).group(1) == "true"
        assert f'<tr class="cn-detalhe" data-de="{r["id"]}"><td colspan="10">' in html
        assert "Acompanhamento diário · <b>20 dias com parada</b>" in html and "Duração no dia" in html
    assert r["abreFim"] == [] and 'class="cn-detalhe"' not in r["fechado"]     # Enter na linha fecha
    # a ocorrência de um dia só não abre: sem seta, sem cn-linha
    assert re.search(r'<tr data-id="%s">' % re.escape(r["umId"]), r["antes"])


@precisa_node
def test_o_drill_mostra_o_dia_dividido_com_outra_ocorrencia(tmp_path):
    # Xavantina 2 · 2.3, 18/10: a parada da manhã e a da tarde no mesmo dia; a linha do dia soma as duas (141,7)
    x = dict(fonte="solaredge", pid="X2")
    eps = [ep("Xavantina 2", "Inversor 2.3", "13.1", "2026-10-18 08:45", "2026-10-18 12:00", "voltou", "2026-10-18", "2026-10-18", 71.7, **x),
           ep("Xavantina 2", "Inversor 2.3", "13.1", "2026-10-18 13:45", "2026-10-19 12:00", "voltou", "2026-10-18", "2026-10-19", 120.2, **x)]
    rows = [dia("Xavantina 2", "Inversor 2.3", "2026-10-18", ["13.1"], 141.7, fonte="solaredge"),
            dia("Xavantina 2", "Inversor 2.3", "2026-10-19", ["13.1"], 50.0, fonte="solaredge")]
    js = RESUMO_OC + "out(oc);"
    r = _roda(tmp_path, pacote(eps, rows), js)
    tarde = next(o for o in r if o["inicio"].endswith("13:45"))
    assert tarde["det"] == [["2026-10-18", 70.2], ["2026-10-19", 50.0]]  # a parte desta = 120,2 − 50,0


# o formato EXATO do falhas_job (montar, "O CADASTRO de cada linha", 20/10/2026): a linha do dia leva o `plant_id` do
# cadastro dela; quando dois cadastros da usina têm o MESMO nome de inversor no dia (Itajá 18749574 × 18749576,
# INVERSOR01 a 04, nos stores do PC de 20/10), a linha soma os dois, leva `plant_id` None e a linha de cada um em
# `cadastros` (os mesmos campos, com o plant_id dele)
ITA_A, ITA_B = "18749574", "18749576"


def _linha_job(d, pid, perda, flags=(), cads=None, inv="INVERSOR01", sem_pid=False):
    def campos(p, fl, dur):
        return {"dia": d, "fonte": "pv", "cliente": "Thopen", "usina": "Itajá", "inversor": inv, "qtd": 1,
                "strings": "Ipv1", "h_sol": 10.0, "dur_h": dur, "dur_min_h": dur, "janela": "06:00–18:00",
                "perda_kwh": p, "perda_nominal_kwh": 0.0, "kwp_string": 16.19, "yield": 4.5, "flags": sorted(fl)}
    if sem_pid:                                                        # o pacote de antes de 20/10: sem o campo
        return campos(perda, flags, 12.0)
    if not cads:
        return {**campos(perda, flags, 12.0), "plant_id": pid}
    soma, fl = round(sum(p for _, p, _ in cads), 1), {x for _, _, f in cads for x in f}
    return {**campos(soma, fl, 24.0), "plant_id": None,                 # a soma dos dois: 24 h no dia, como no PC
            "cadastros": [{**campos(p, f, 12.0), "plant_id": c} for c, p, f in cads]}


ITA_EPS = [ep("Itajá", "INVERSOR01", "Ipv1", "2026-10-01 06:00", "2026-10-03 17:00", "voltou", "2026-10-01", "2026-10-03", 1350.0, pid=ITA_A),
           ep("Itajá", "INVERSOR01", "Ipv1", "2026-10-01 06:00", "2026-10-01 17:00", "voltou", "2026-10-01", "2026-10-01", 400.0, pid=ITA_B),
           ep("Itajá", "INVERSOR01", "Ipv1", "2026-10-03 06:00", "2026-10-03 17:00", "voltou", "2026-10-03", "2026-10-03", 400.0, pid=ITA_B)]
ITA_DIAS = [_linha_job("2026-10-01", None, 0, cads=[(ITA_A, 500.0, [SEM_GER]), (ITA_B, 400.0, [])]),   # os dois no dia
            _linha_job("2026-10-02", ITA_A, 450.0),                                                   # só o A
            _linha_job("2026-10-03", None, 0, cads=[(ITA_A, 400.0, []), (ITA_B, 400.0, [])])]


@precisa_node
def test_o_drill_casa_cada_cadastro_pelo_plant_id_dele_e_a_soma_nao_entra(tmp_path):
    # Até a revisão de 20/10 a tela olhava o mapa do plant_id OU, sem ele, o da usina inteiro: o A ficava só com o 02/10
    # (450 de 1.350 kWh) e o B pegava a SOMA dos dois (900 e 800 contra 400 e 400), com o ≈ do A
    js = RESUMO_OC + """
      const A = T.OC.find(o => o.plant_id === '%s');
      T.S.abre.add(T.idLinha(A)); T.desenha(); const tab = ELS.tab.innerHTML;
      const x = T.planilha(T.ordenadas(T.linhas().filter(T.naConta)).sorted);
      out({oc: T.OC.map(o => ({pid: o.plant_id, inicio: o.inicio, perda: o.perda_kwh, est: o.est_kwh, est_dias: o.est_dias,
        det: o.det.map(d => [d.dia, d.perda])})), tab, x});""" % ITA_A
    r = _roda(tmp_path, pacote(ITA_EPS, ITA_DIAS), js)
    por = {(o["pid"], o["inicio"][:10]): o for o in r["oc"]}
    a, b1, b3 = por[(ITA_A, "2026-10-01")], por[(ITA_B, "2026-10-01")], por[(ITA_B, "2026-10-03")]
    assert a["det"] == [["2026-10-01", 500.0], ["2026-10-02", 450.0], ["2026-10-03", 400.0]]
    assert round(sum(p for _, p in a["det"]), 1) == a["perda"] == 1350.0       # o drill fecha com a ocorrência
    assert b1["det"] == [["2026-10-01", 400.0]] and b3["det"] == [["2026-10-03", 400.0]]
    # o ≈ pelo dia é o do cadastro: só o 01/10 do A tem estimativa
    assert (a["est"], a["est_dias"]) == (500.0, 1) and b1["est"] == b3["est"] == 0
    # no drill aberto, a duração do dia é a do cadastro (12 h), não a da soma (24 h)
    assert '>12 h</span>' in r["tab"] and '>24 h</span>' not in r["tab"]
    # o Excel: "Perda estimada" e a aba "Dia a dia" pelo mesmo casamento
    oc, dd = r["x"]["abas"]
    col, dcol = ({c["titulo"]: i for i, c in enumerate(aba["colunas"])} for aba in (oc, dd))
    est = sorted((l[col["Parou"]], l[col["Perda (kWh)"]], l[col["Perda estimada (kWh)"]]) for l in oc["linhas"])
    assert est == [("2026-10-01 06:00", 400.0, 0.0), ("2026-10-01 06:00", 1350.0, 500.0), ("2026-10-03 06:00", 400.0, 0.0)]
    # o A e o B1 começam no mesmo minuto: os cinco dias das três ocorrências, sem a soma (900 e 800) em lugar nenhum
    assert sorted((l[dcol["Parou (a ocorrência)"]], l[dcol["Dia"]], l[dcol["Perda (kWh)"]], l[dcol["Estimada"]]) for l in dd["linhas"]) == [
        ("2026-10-01 06:00", "2026-10-01", 400.0, "não"), ("2026-10-01 06:00", "2026-10-01", 500.0, "sim"),
        ("2026-10-01 06:00", "2026-10-02", 450.0, "não"), ("2026-10-01 06:00", "2026-10-03", 400.0, "não"),
        ("2026-10-03 06:00", "2026-10-03", 400.0, "não")]


@precisa_node
def test_a_reserva_pela_usina_e_so_do_pacote_sem_plant_id_e_vale_dia_a_dia(tmp_path):
    js = RESUMO_OC + "out(oc.map(o => o.det));"
    eps = [ep("Itajá", "INVERSOR01", "Ipv1", "2026-10-01 06:00", "2026-10-02 17:00", "voltou", "2026-10-01", "2026-10-02", 900.0, pid=ITA_A)]
    # a linha do 02/10 sem o campo (pacote antigo) entra pela reserva no dia dela, mesmo com a do 01/10 no cadastro
    misto = [_linha_job("2026-10-01", ITA_A, 500.0), _linha_job("2026-10-02", None, 400.0, sem_pid=True)]
    assert _roda(tmp_path, pacote(eps, misto), js) == [[["2026-10-01", 500.0], ["2026-10-02", 400.0]]]
    # no pacote novo, a linha de OUTRO cadastro com o mesmo nome de inversor nunca serve de reserva
    outro = [_linha_job("2026-10-01", ITA_A, 500.0), _linha_job("2026-10-02", ITA_B, 400.0)]
    assert _roda(tmp_path, pacote(eps, outro), js) == [[["2026-10-01", 500.0]]]


@precisa_node
def test_trackers_ganham_a_coluna_os_e_o_drill_pelo_dia_a_dia_da_linha(tmp_path):
    base = {"fonte": "pv", "plant_id": "18748739", "cliente": "Thopen", "usina": "Inhapi", "inversor": "Inversor 3.3",
            "desvio_pico": 80.0, "cronico": False, "sem_com_desde": None, "flags": []}
    com_dias = {**base, "chave": "pv|18748739|TRK52|2026-10-01", "tracker": "TRK52", "inicio": "2026-10-01 06:30",
                "fim": "2026-10-03", "visto_ate": "2026-10-02", "perda_kwh": 300.0,
                "dias": [["2026-10-01", "06:30", "18:00", 9.5, 180.0, "sim"], ["2026-10-02", "06:00", "18:00", 10.0, 120.0, "sim"]]}
    sem_dias = {**base, "chave": "pv|18748739|TRK13|2026-10-01", "tracker": "TRK13", "inicio": "2026-10-01 07:00",
                "fim": "2026-10-04", "visto_ate": "2026-10-03", "perda_kwh": 200.0}
    td = [{"dia": "2026-10-02", "fonte": "pv", "plant_id": "18748739", "usina": "Inhapi", "cliente": "Thopen",
           "trackers": "TRK13, TRK14", "qtd": 2, "comunicou": "sim"}]
    js = """T.S.aba = 'trk'; T.desenha();
      for (const r of T.D.trackers.rows) T.S.abre.add(T.idLinha(r)); T.desenha(); out(ELS.tab.innerHTML);"""
    html = _roda(tmp_path, pacote(trk=[com_dias, sem_dias], trackers_dia=td), js)
    assert '<th class="">OS</th><th class="col-av">Avisos</th>' in html    # a coluna nova, antes de Avisos
    assert "Horas paradas" in html and "9,5 h" in html and "180 kWh" in html and "comunicou" in html
    assert "parado neste dia" in html and "Detalhe por hora a partir de outubro." in html      # pacote sem `dias`
    # o pacote sem `dias` também lista todos os dias (01 a 03/10): o 02/10 do registro e os outros dois sem leitura
    sem = html.split(f'data-de="pv|18748739|TRK13|2026-10-01|07:00"')[1]
    assert re.findall(r'<tr><td class="tab">(\d\d/\d\d)</td>', sem) == ["01/10", "02/10", "03/10"]
    assert sem.count("sem leitura do tracker no dia") == 2


@precisa_node
def test_o_drill_do_tracker_lista_todos_os_dias_da_parada(tmp_path):
    # Aparecida 3 · Tracker 24 (pacote do worker novo, 20/10 15:00): parou 13/10 15:10, visto parado até 18/10, leitura do
    # tracker só em 13, 17 e 18 (os outros dias ele não mandou leitura: a parada atravessa, sem perda). O cabeçalho dizia
    # "6 dias com parada" e a tabela mostrava 3 — 272 das 1.612 paradas de 2+ dias daquele pacote
    t = {"chave": "pg|21|Tracker 24|2026-10-13", "fonte": "pg", "plant_id": "21", "cliente": "Thopen", "usina": "Aparecida 3",
         "tracker": "Tracker 24", "inversor": "", "inicio": "2026-10-13 15:10", "fim": None, "visto_ate": "2026-10-18",
         "sem_com_desde": "2026-10-19", "desvio_pico": None, "perda_kwh": 37.5, "cronico": False,
         "flags": ["em aberto", "sem comunicação do tracker desde 19/10", "sem ângulo (fator 25%)"],
         "dias": [["2026-10-13", "15:10", "18:00", 2.83, 7.5, "sim"], ["2026-10-17", "06:00", "18:00", 12.0, 15.0, "sim"],
                  ["2026-10-18", "06:00", "18:00", 12.0, 15.0, "sem prova"]]}
    js = """T.S.aba = 'trk'; T.desenha(); T.S.abre.add(T.idLinha(T.D.trackers.rows[0])); T.desenha();
      out({tab: ELS.tab.innerHTML, x: T.planilha(T.ordenadas(T.linhas().filter(T.naConta)).sorted)});"""
    r = _roda(tmp_path, pacote(trk=[t]), js)
    mae, det = r["tab"].split('class="cn-detalhe"')
    assert "6 dias com parada" in mae and "<b>6 dias com parada</b>" in det        # a linha e o cabeçalho do drill
    assert re.findall(r'<tr><td class="tab">(\d\d/\d\d)</td>', det) == ["13/10", "14/10", "15/10", "16/10", "17/10", "18/10"]
    assert det.count("sem leitura do tracker no dia") == 3 and "2,8 h" in det and "15 kWh" in det
    # o Excel: a "Dia a dia" com os mesmos 6 dias (a coluna Dias da "Paradas" diz 6), a perda dos dias = a da parada
    par, dd = r["x"]["abas"]
    assert par["linhas"][0][[c["titulo"] for c in par["colunas"]].index("Dias")] == 6
    assert [l[4] for l in dd["linhas"]] == [f"2026-10-{d}" for d in range(13, 19)]
    sem = [l for l in dd["linhas"] if l[-1] == "sem leitura do tracker no dia"]
    assert [l[4] for l in sem] == ["2026-10-14", "2026-10-15", "2026-10-16"] and all(l[5:9] == [None] * 4 for l in sem)
    assert round(sum(l[8] or 0 for l in dd["linhas"]), 1) == 37.5


# ── 3. Vincular OS: só no clique (1.7) ─────────────────────────────────────────────────────────────────────────
def _corpo_de(nome):
    i = HTML.index(nome)
    prof, j = 0, HTML.index("{", i)
    for k in range(j, len(HTML)):
        prof += {"{": 1, "}": -1}.get(HTML[k], 0)
        if prof == 0:
            return HTML[i:k + 1]
    raise AssertionError(nome)


def test_a_busca_de_os_so_mora_no_ouvinte_do_vincular():
    # Levi, 20/10/2026, 1.7: "A OS só carrega se eu clicar em vincular, caso eu não clique não deve carregar nem fazer
    # requisição alguma do fractal". Abrir, filtrar, ordenar, abrir o drill e baixar o Excel não podem nem citar a busca
    assert HTML.count("/api/painel/falhas/os") == 1
    assert "/api/painel/falhas/os?" in _corpo_de("async function ouvinteOS(")
    for f in ("function desenha(", "function tabela(", "function linha(", "function drillStr(", "function drillTrk(",
              "function osCel(", "function osPainel(", "function planilha(", "function ocorrencias(", "async function carrega(",
              "$('b-xls').addEventListener("):
        corpo = _corpo_de(f)
        assert "falhas/os" not in corpo and "ouvinteOS" not in corpo, f
    assert re.findall(r"\bouvinteOS\b", HTML) == ["ouvinteOS", "ouvinteOS"]      # a definição e o addEventListener
    assert "$('tab').addEventListener('click', ouvinteOS);" in HTML
    assert "strings_os" not in HTML                                   # a OS do pacote não pinta a linha sem clique


OS_RESP = {"ok": True, "ativo": {"code": "THPN-GTB100-INVR2.5", "nome": "Inversor 2.5"}, "buscado_em": "2026-10-20 15:40",
           "os": [{"folio": "16561", "status": "Em andamento", "tipo": "Corretiva", "criada": "2026-10-02 08:00",
                   "evento": "2026-10-01 09:00", "concluida": None, "descricao": "Recomposição de strings do INV 2.5",
                   "strings": ["Ipv9", "Ipv10"], "anterior": False, "link": "/os/os/folio/16561"},
                  {"folio": "9915", "status": "Concluída", "tipo": "Corretiva", "criada": "2026-07-23 10:00",
                   "evento": "2026-07-23 10:00", "concluida": "2026-07-25 16:00", "descricao": "Recomposição de string",
                   "strings": [], "anterior": True, "link": "/os/os/folio/9915"}]}


@precisa_node
def test_abrir_filtrar_ordenar_drill_e_excel_nao_pedem_os_e_o_clique_pede_uma_vez(tmp_path):
    vinc_novo = [{"tipo": "strings", "fonte": "pv", "plant_id": "18747509", "equipamento": "Inversor 2.5",
                  "dia_inicio": "2026-10-05", "os": 16561, "decidida_em": "2026-10-20T18:41:00Z"}]
    js = """const os = () => PEDIDOS.filter(p => p.url.includes('/api/painel/falhas/os'));
      T.desenha(); T.S.usina = 'Guatambu'; T.desenha(); T.S.ord = ['qtd', -1]; T.desenha();
      const g2 = T.OC.find(o => o.inicio === '2026-10-05 09:20'), id = T.idLinha(g2);
      await clica(naLinha(id));
      for (const f of ELS['b-xls']._ouv.click) await f(); await espera();
      const antes = os().length, outros = PEDIDOS.map(p => p.metodo + ' ' + p.url.split('?')[0]);
      await clica(noBotao('vincular', id)); const buscando = os().length, painel = ELS.tab.innerHTML;
      await clica(noBotao('vincular', id)); await clica(noBotao('vincular', id));     // fecha e reabre: a busca desta visita
      const reaberto = os().length;
      RESP['/api/painel/falhas/vinculos'] = [200, {ok: true, vinculos: %s}];
      await clica(noBotao('vinc', id, 16561));
      const post = PEDIDOS.filter(p => p.metodo === 'POST' && p.url === '/api/painel/falhas/vinculos').map(p => p.corpo);
      out({antes, outros, buscando, reaberto, url: os()[0].url, painel, post, tab: ELS.tab.innerHTML, vinc: T.VINC.length});""" % json.dumps(vinc_novo)
    r = _roda(tmp_path, pacote(GUATAMBU_EPS, GUATAMBU_DIAS), js, resp={"/api/painel/falhas/os": [200, OS_RESP],
                                                                       "/api/painel/falhas/exportar": [200, {}]})
    assert r["antes"] == 0, r["outros"]
    assert set(r["outros"]) == {"GET /api/painel/falhas", "GET /api/painel/falhas/desconsideradas",
                                "GET /api/painel/falhas/vinculos", "POST /api/painel/falhas/exportar"}
    assert r["buscando"] == 1 and r["reaberto"] == 1
    assert "tipo=strings" in r["url"] and "plant_id=18747509" in r["url"] and "inversor=Inversor+2.5" in r["url"]
    assert "desde=2026-10-05" in r["url"]
    assert "OS de recomposição de string do Inversor 2.5" in r["painel"] and "16561" in r["painel"]
    assert "anterior à parada" in r["painel"] and "strings citadas: Ipv9, Ipv10" in r["painel"]
    assert r["post"] == [{"tipo": "strings", "fonte": "pv", "plant_id": "18747509", "equipamento": "Inversor 2.5",
                          "dia_inicio": "2026-10-05", "os": 16561, "decisao": "vincular"}]
    assert r["vinc"] == 1 and 'href="/os/os/folio/16561"' in r["tab"] and ">OS 16561</a>" in r["tab"]
    assert "OS 16561 vinculada." in r["tab"]


@precisa_node
def test_o_vinculo_gravado_aparece_sem_clique_e_desvincular_confirma_na_linha(tmp_path):
    vinc = [{"tipo": "strings", "fonte": "pv", "plant_id": "18747509", "equipamento": "Inversor 2.5", "dia_inicio": "2026-10-07",
             "os": 16561, "decidida_em": "2026-10-20T18:41:00Z"}]
    js = """T.desenha(); const html = ELS.tab.innerHTML;
      const g2 = T.OC.find(o => o.inicio === '2026-10-05 09:20'), id = T.idLinha(g2);
      await clica(noBotao('desv', id, 16561)); const pergunta = ELS.tab.innerHTML;
      RESP['/api/painel/falhas/vinculos'] = [200, {ok: true, vinculos: []}];
      await clica(noBotao('desv-sim', id, 16561));
      out({html, pergunta, tab: ELS.tab.innerHTML, pedidos: PEDIDOS.filter(p => p.metodo === 'POST').map(p => p.corpo),
           os: PEDIDOS.filter(p => p.url.includes('falhas/os')).length});"""
    r = _roda(tmp_path, pacote(GUATAMBU_EPS, GUATAMBU_DIAS), js, vinculos=vinc)
    # 07/10 está dentro de 05 a 16/10: o vínculo cola na ocorrência mesmo com o início andando no backfill
    assert r["html"].count(">OS 16561</a>") == 1 and r["os"] == 0
    assert "Desvincular a OS 16561 desta linha?" in r["pergunta"]
    assert r["pedidos"] == [{"tipo": "strings", "fonte": "pv", "plant_id": "18747509", "equipamento": "Inversor 2.5",
                             "dia_inicio": "2026-10-07", "os": 16561, "decisao": "desvincular"}]
    assert ">OS 16561</a>" not in r["tab"] and "OS 16561 desvinculada." in r["tab"]


@precisa_node
def test_fracttal_fora_e_erro_e_o_gestor_fica_so_leitura(tmp_path):
    js = """T.desenha(); const id = T.idLinha(T.OC[0]);
      await clica(noBotao('vincular', id)); const erro = ELS.tab.innerHTML;
      RESP['/api/painel/falhas/os'] = [200, {ok: true, fonte_ok: false, reserva: 'varredura', varrido_em: '2026-10-20 15:03',
        motivo: 'o Fracttal não respondeu (429)', os: [{folio: '16561', status: 'Em andamento', tipo: 'Corretiva', evento: '2026-10-01 09:00'}]}];
      await clica(noBotao('busca', id)); const reserva = ELS.tab.innerHTML;
      RESP['/api/painel/falhas/vinculos'] = [403, {error: 'gestor: só leitura'}];
      await clica(noBotao('vinc', id, 16561));
      out({erro, reserva, tab: ELS.tab.innerHTML});"""
    r = _roda(tmp_path, pacote(INHAPI_EPS, INHAPI_DIAS), js, resp={"/api/painel/falhas/os": [502, {
        "ok": False, "fonte_ok": False, "motivo": "o Fracttal não respondeu (HTTPError 429)"}]})
    # 502 é erro dito como erro, nunca "nenhuma OS"
    assert "Não consegui buscar as OS de recomposição de string do Inversor 3.3: o Fracttal não respondeu (HTTPError 429)." in r["erro"]
    assert "Nenhuma OS" not in r["erro"] and "Tentar de novo" in r["erro"]
    assert "O Fracttal não respondeu; estas são as OS da varredura das 15:03 (pode faltar a mais nova)." in r["reserva"]
    assert 'data-os="vinc"' in r["reserva"]                          # a reserva também vincula
    assert "Seu acesso é só de leitura" in r["tab"] and 'data-os="vincular"' not in r["tab"] and 'data-os="vinc"' not in r["tab"]
    assert "desc-chk" not in r["tab"] and "Tirar da conta" not in r["tab"]   # o 403 do vínculo tira a caixa também


# o GET dos vínculos pendurado: só responde quando o teste soltar (SOLTA) ou quando o teto da tela abortar o pedido
SEGURA_VINCULOS = r"""
const _fetch = globalThis.fetch; let SOLTA = null;
globalThis.fetch = (u, o) => {
  if (String(u).split('?')[0] !== '/api/painel/falhas/vinculos' || (o && o.method === 'POST')) return _fetch(u, o);
  PEDIDOS.push({metodo: 'GET', url: String(u), corpo: null});
  return new Promise((res, rej) => {
    SOLTA = (st, j) => res({ok: st >= 200 && st < 300, status: st, json: async () => j});
    if (o && o.signal) o.signal.addEventListener('abort', () => rej(Object.assign(new Error('aborted'), {name: 'AbortError'})));
  });
};
"""
# o teto de 10 s da tela em 20 ms (os outros relógios como estão)
TETO_CURTO = r"""
const _st = globalThis.setTimeout;
globalThis.setTimeout = (f, ms, ...a) => _st(f, ms >= 10000 ? 20 : ms, ...a);
"""
VINC_16561 = {"tipo": "strings", "fonte": "pv", "plant_id": "18747509", "equipamento": "Inversor 2.5", "dia_inicio": "2026-10-05",
              "os": 16561, "decidida_em": "2026-10-20T18:41:00Z"}


@precisa_node
def test_os_vinculos_atrasados_nao_seguram_a_tabela_e_entram_quando_chegam(tmp_path):
    # revisão de 20/10: a leitura dos vínculos (o livro do Nexus) ia num Promise.all com as tiradas e a tela inteira
    # esperava por ela — o banco do Nexus lento deixava Strings e trackers em branco
    js = """const antes = {tab: ELS.tab.innerHTML, conta: ELS.conta.innerHTML, vinc: T.VINC.length};
      SOLTA(200, {ok: true, vinculos: [%s], lido_em: '2026-10-20 15:00'}); await espera();
      out({antes, depois: ELS.tab.innerHTML, gets: PEDIDOS.filter(p => p.url === '/api/painel/falhas/vinculos').length});""" % json.dumps(VINC_16561)
    r = _roda(tmp_path, pacote(GUATAMBU_EPS, GUATAMBU_DIAS), js, antes=SEGURA_VINCULOS)
    # a tabela já está na tela com o /vinculos pendurado, e a coluna OS diz que eles ainda não chegaram
    assert len(re.findall(r'<tr[^>]* data-id=', r["antes"]["tab"])) == 4 and "<b>4</b> ocorrências" in r["antes"]["conta"]
    assert r["antes"]["vinc"] == 0 and 'OS<span class="th-nota">lendo…</span>' in r["antes"]["tab"]
    assert ">OS 16561</a>" not in r["antes"]["tab"]
    # chegaram: o 2º desenho põe o vínculo e tira o "lendo…" (um pedido só)
    assert ">OS 16561</a>" in r["depois"] and '<th class="">OS</th>' in r["depois"] and "th-nota" not in r["depois"]
    assert r["gets"] == 1


@precisa_node
def test_os_vinculos_que_nao_vem_tem_teto_e_o_erro_fica_no_cabecalho_da_coluna(tmp_path):
    js = """await new Promise(r => _st(r, 150)); await espera(); out(ELS.tab.innerHTML);"""
    tab = _roda(tmp_path, pacote(GUATAMBU_EPS, GUATAMBU_DIAS), js, antes=SEGURA_VINCULOS + TETO_CURTO)
    assert ('title="OS vinculadas: não vieram em 10 s. A coluna pode estar incompleta.">OS<span class="th-nota aviso">'
            'incompleta</span></th>') in tab
    assert len(re.findall(r'<tr[^>]* data-id=', tab)) == 4                      # a tabela inteira, como sempre
    # o banco do Nexus fora: o servidor manda a última leitura boa (ou nada) com o erro; a tela o diz no mesmo lugar
    erro = "o banco do Nexus não respondeu (ConnectionError): nenhuma leitura boa nesta máquina"
    js = "SOLTA(200, {ok: false, vinculos: [], lido_em: null, erro: %s}); await espera(); out(ELS.tab.innerHTML);" % json.dumps(erro)
    tab = _roda(tmp_path, pacote(GUATAMBU_EPS, GUATAMBU_DIAS), js, antes=SEGURA_VINCULOS)
    assert f'title="OS vinculadas: {erro}. A coluna pode estar incompleta.">OS<span class="th-nota aviso">incompleta</span>' in tab


# o foco: um querySelector que acha o controle no HTML da tabela (o DOM de mentira não monta a árvore) e anota quem recebeu
# o foco — o id da linha e o seletor que achou
FOCO_JS = r"""
const FOCO = [];
function trecho(attr, id) {
  const h = ELS.tab.innerHTML, re = /<tr\b[^>]*>/g; let m, ini = -1;
  while ((m = re.exec(h))) {
    if (ini < 0) { if (m[0].includes(`${attr}="${id}"`)) ini = m.index; }
    else if (/ data-(id|de)="/.test(m[0])) return h.slice(ini, m.index);
  }
  return ini < 0 ? null : h.slice(ini);
}
document.querySelector = sel => {
  const m = sel.match(/^#tab tr\[(data-id|data-de)="([^"]*)"\](?: (.+))?$/);
  if (!m) return null;
  const [, attr, id, dentro] = m, t = trecho(attr, id);
  if (t == null) return null;
  if (!dentro) { const tag = t.match(/^<tr\b[^>]*>/)[0]; return {matches: s => s === '.cn-linha' && tag.includes('cn-linha'), focus() { FOCO.push([id, 'linha']); }}; }
  const conds = [...dentro.matchAll(/\[([\w-]+)="([^"]*)"\]/g)].map(x => `${x[1]}="${x[2]}"`);
  const achou = (t.match(/<(button|a|input)\b[^>]*>/g) || []).find(tag => dentro === 'input.desc-chk' ? tag.includes('class="desc-chk"') : conds.every(c => tag.includes(c)));
  return achou ? {focus() { FOCO.push([id, dentro]); }} : null;
};
"""


@precisa_node
def test_o_foco_volta_ao_botao_equivalente_da_mesma_linha(tmp_path):
    # revisão de 20/10: o desenha() refaz a tabela e, pelo teclado, cada clique do Vincular jogava o foco para o começo da
    # página; agora volta ao controle equivalente da mesma linha, como o alternaDrill faz com a linha
    js = FOCO_JS + """T.desenha(); const g2 = T.OC.find(o => o.inicio === '2026-10-05 09:20'), id = T.idLinha(g2);
      const ult = () => FOCO[FOCO.length - 1], f = {};
      await clica(noBotao('vincular', id)); f.abriu = ult();
      await clica(noBotao('fecha', id)); f.fechou = ult();
      await clica(noBotao('desv', id, 16561)); f.pediu = ult();
      await clica(noBotao('desv-nao', id)); f.cancelou = ult();
      await clica(noBotao('desv', id, 16561));
      RESP['/api/painel/falhas/vinculos'] = [200, {ok: true, vinculos: []}];
      await clica(noBotao('desv-sim', id, 16561)); f.desvinculou = ult();
      await clica(noBotao('vincular', id));
      RESP['/api/painel/falhas/vinculos'] = [200, {ok: true, vinculos: [%s]}];
      await clica(noBotao('vinc', id, 16561)); f.vinculou = ult();
      const ev = {target: {closest: () => ({dataset: {chave: g2.chave, id}, checked: true})}};
      await ELS.tab._ouv.change[0](ev); await espera(); f.caixa = ult();
      out({id, f});""" % json.dumps(VINC_16561)
    r = _roda(tmp_path, pacote(GUATAMBU_EPS, GUATAMBU_DIAS), js, vinculos=[VINC_16561],
              resp={"/api/painel/falhas/os": [200, OS_RESP], "/api/painel/falhas/desconsiderar": [200, {"ok": True, "n": 5}]})
    i, f = r["id"], r["f"]
    assert f["abriu"] == [i, '[data-os="vincular"]'] and f["fechou"] == [i, '[data-os="vincular"]']   # o "Fechar a busca"/"Vincular OS"
    assert f["pediu"] == [i, '[data-os="desv-nao"]']                    # o "Cancelar" (Enter duas vezes não desvincula)
    assert f["cancelou"] == [i, '[data-os="desv"][data-n="16561"]']     # de volta ao "×" daquela OS
    assert f["desvinculou"] == [i, '[data-os="vincular"]'] and f["vinculou"] == [i, '[data-os="vincular"]']
    assert f["caixa"] == [i, "input.desc-chk"]                          # a caixa "Tirar da conta" também


@precisa_node
def test_depois_do_1o_403_a_caixa_e_o_voltar_para_a_conta_tambem_somem(tmp_path):
    # revisão de 20/10: depois do 1º 403 só os botões de OS sumiam, e o gestor seguia marcando caixas que voltavam com "Não
    # gravou". Escondidas, não desabilitadas (tests/test_falhas_desconsiderar.py prende que a página não trava a caixa)
    desc = {"ok": True, "trackers": {}, "strings": {"pv|18748739|Inversor 3.3|Ipv1|2026-09-02": {
        "usina": "Inhapi", "inversor": "Inversor 3.3", "string": "Ipv1", "perda_kwh": 12.0, "por": "Davi", "em": "2026-09-03 10:00"}}}
    js = """T.desenha(); const antes = {tab: ELS.tab.innerHTML, gaveta: ELS['desc-tab'].innerHTML};
      const inh = T.OC[0], ev = {target: {closest: () => ({dataset: {chave: inh.chave, id: T.idLinha(inh)}, checked: true})}};
      await ELS.tab._ouv.change[0](ev); await espera();
      T.S.abre.add(T.idLinha(inh)); T.desenha();
      out({antes, tab: ELS.tab.innerHTML, gaveta: ELS['desc-tab'].innerHTML, msg: ELS['desc-msg'].innerHTML, fora: T.OC.map(o => !!o.fora)});"""
    r = _roda(tmp_path, pacote(INHAPI_EPS, INHAPI_DIAS), js, resp={
        "/api/painel/falhas/desconsideradas": [200, desc],
        "/api/painel/falhas/desconsiderar": [403, {"error": "somente leitura (perfil gestor)"}]})
    assert 'class="desc-chk"' in r["antes"]["tab"] and "voltar para a conta" in r["antes"]["gaveta"]
    assert 'data-os="vincular"' in r["antes"]["tab"]
    assert "desc-chk" not in r["tab"] and "Tirar da conta" not in r["tab"] and 'data-os="vincular"' not in r["tab"]
    assert 'colspan="9"' in r["tab"] and "disabled" not in r["tab"]     # o drill acompanha a coluna que saiu
    assert "voltar para a conta" not in r["gaveta"] and "Inhapi" in r["gaveta"]          # a lista das tiradas fica
    assert r["msg"] == ("Não gravou: somente leitura (perfil gestor). Seu acesso é só de leitura: quem tira da conta e "
                        "vincula OS é a equipe de performance.")
    assert r["fora"] == [False]                                         # a linha voltou como estava


@precisa_node
def test_nao_gravou_nao_repete_o_prefixo_que_o_servidor_ja_manda(tmp_path):
    # as rotas de gravação dizem "não gravou — ..." e a tela mostrava "Não gravou: não gravou — ..."
    js = """T.desenha(); const g = T.OC.find(o => o.inicio === '2026-10-05 09:20'), id = T.idLinha(g);
      await clica(noBotao('vincular', id));
      RESP['/api/painel/falhas/vinculos'] = [500, {ok: false, motivo: 'não gravou — o banco do Nexus não aceitou (HTTPError)'}];
      await clica(noBotao('vinc', id, 16561)); const banco = ELS.tab.innerHTML;
      RESP['/api/painel/falhas/vinculos'] = [400, {ok: false, motivo: 'os: número de OS inválido'}];
      await clica(noBotao('vinc', id, 16561)); const formato = ELS.tab.innerHTML;
      const ev = {target: {closest: () => ({dataset: {chave: g.chave, id}, checked: true})}};
      await ELS.tab._ouv.change[0](ev); await espera();
      out({banco, formato, desc: ELS['desc-msg'].innerHTML});"""
    r = _roda(tmp_path, pacote(GUATAMBU_EPS, GUATAMBU_DIAS), js, resp={
        "/api/painel/falhas/os": [200, OS_RESP],
        "/api/painel/falhas/desconsiderar": [500, {"ok": False, "motivo": "não gravou — OSError: disco cheio"}]})
    assert "Não gravou — o banco do Nexus não aceitou (HTTPError)" in r["banco"] and "Não gravou: não gravou" not in r["banco"]
    assert "Não gravou: os: número de OS inválido" in r["formato"]       # o motivo sem o prefixo ganha o "Não gravou:"
    assert r["desc"] == "Não gravou — OSError: disco cheio."


@precisa_node
def test_o_link_da_os_sai_do_folio_conferido_e_nunca_do_link_da_resposta(tmp_path):
    resp_os = {"ok": True, "ativo": {"code": "THPN-INH100-INVR3.3", "nome": "Inversor 3.3"}, "buscado_em": "2026-10-20 15:40", "os": [
        {"folio": "16561", "status": "Em andamento", "link": "javascript:alert(1)", "descricao": "Recomposição de string"},
        {"folio": "16x61", "status": "Concluída", "link": "/os/os/folio/16x61", "descricao": "Recomposição de string"}]}
    js = "T.desenha(); const id = T.idLinha(T.OC[0]); await clica(noBotao('vincular', id)); out(ELS.tab.innerHTML);"
    html = _roda(tmp_path, pacote(INHAPI_EPS, INHAPI_DIAS), js, resp={"/api/painel/falhas/os": [200, resp_os]})
    assert 'href="/os/os/folio/16561"' in html and "javascript:" not in html and 'data-n="16561"' in html
    # fora do formato: o número aparece, sem link e sem "Vincular" (a rota só aceita OS inteira)
    assert "16x61" in html and 'href="/os/os/folio/16x61"' not in html and 'data-n="16x61"' not in html


# ── 4. Tirar da conta na linha = todas as chaves da ocorrência ────────────────────────────────────────────────
@precisa_node
def test_tirar_da_conta_a_ocorrencia_manda_todas_as_chaves_e_risca_na_hora(tmp_path):
    js = """T.desenha(); const inh = T.OC[0];
      const ev = {target: {closest: () => ({dataset: {chave: inh.chave, id: T.idLinha(inh)}, checked: true})}};
      const pend = ELS.tab._ouv.change[0](ev); const riscada = ELS.tab.innerHTML, conta = ELS.conta.innerHTML; await pend; await espera();
      out({riscada, conta, corpo: PEDIDOS.filter(p => p.metodo === 'POST').map(p => p.corpo), fora: T.OC.map(o => o.fora)});"""
    r = _roda(tmp_path, pacote(INHAPI_EPS, INHAPI_DIAS), js, resp={"/api/painel/falhas/desconsiderar": [200, {"ok": True, "n": 4}]})
    [corpo] = r["corpo"]
    assert corpo["tipo"] == "strings" and corpo["desconsiderar"] is True and "chave" not in corpo
    assert corpo["chaves"] == [e["chave"] for e in INHAPI_EPS]
    assert sorted(corpo["resumos"]) == sorted(e["chave"] for e in INHAPI_EPS) and corpo["resumos"][INHAPI_EPS[0]["chave"]]["string"] == "Ipv1"
    assert 'class="desc-on cn-linha"' in r["riscada"] and "<b>0</b> ocorrências" in r["conta"] and r["fora"] == [True]


@precisa_node
def test_tirar_a_ocorrencia_que_divide_a_chave_do_dia_diz_quem_sai_junto(tmp_path):
    # Xavantina 2 · 2.3, 18/10 (pacote das 13:45): as strings 13.1, 13.2 e 13.4 param às 08:45 e às 13:45. A chave da parada
    # é por DIA, então tirar a da manhã tira a da tarde (a regra de sempre: o worker tira pela chave) — a mensagem diz
    x, strs = dict(fonte="solaredge", pid="4425840"), ("13.1", "13.2", "13.4")
    eps = ([ep("Xavantina 2", "Inversor 2.3", s, "2026-10-18 08:45", "2026-10-18 12:00", "voltou", "2026-10-18", "2026-10-18", 23.9, **x) for s in strs]
           + [ep("Xavantina 2", "Inversor 2.3", s, "2026-10-18 13:45", "2026-10-19 06:52", "voltou de madrugada", "2026-10-18", "2026-10-18", 23.4, **x)
              for s in strs])
    js = """const ev = (o, marca) => ({target: {closest: () => ({dataset: {chave: o.chave, id: T.idLinha(o), fora: o.fora ? '1' : undefined}, checked: marca})}});
      T.desenha(); await ELS.tab._ouv.change[0](ev(T.OC.find(o => o.inicio === '2026-10-18 08:45'), true)); await espera();
      const tirou = {msg: ELS['desc-msg'].innerHTML, fora: T.OC.map(o => [o.inicio, !!o.fora]).sort(),
                     post: PEDIDOS.filter(p => p.metodo === 'POST').map(p => p.corpo.chaves)};
      await ELS.tab._ouv.change[0](ev(T.OC.find(o => o.inicio === '2026-10-18 08:45' && o.fora), false)); await espera();
      out({tirou, voltou: ELS['desc-msg'].innerHTML, fora: T.OC.map(o => !!o.fora)});"""
    r = _roda(tmp_path, pacote(eps), js, resp={"/api/painel/falhas/desconsiderar": [200, {"ok": True, "n": 3}]})
    assert r["tirou"]["post"] == [[f"solaredge|4425840|Inversor 2.3|{s}|2026-10-18" for s in strs]]
    assert r["tirou"]["fora"] == [["2026-10-18 08:45", True], ["2026-10-18 13:45", True]]
    assert r["tirou"]["msg"].startswith("Tirada da conta: <b>Xavantina 2 · Inversor 2.3 (3 strings)</b> · parou 18/10 08:45. "
                                        "Também sai a ocorrência de 18/10 13:45, que tem a mesma chave do dia. Saiu dos totais;")
    assert r["voltou"] == ("<b>Xavantina 2 · Inversor 2.3 (3 strings)</b> de volta na conta. Também volta a ocorrência de "
                           "18/10 13:45, que tem a mesma chave do dia.")
    assert r["fora"] == [False, False]


@precisa_node
def test_tirar_a_parada_de_tracker_vai_pela_linha_clicada_e_diz_a_outra_da_mesma_chave(tmp_path):
    # 442 chaves de tracker repetidas no pacote de 20/10 13:45 (pg|21|Tracker 32|2026-10-04...): duas paradas do mesmo
    # tracker no mesmo dia. A caixa achava a linha pela chave — a primeira —, e a mensagem dizia a hora da outra
    base = {"fonte": "pg", "plant_id": "21", "cliente": "Thopen", "usina": "Aparecida 3", "tracker": "Tracker 32", "inversor": "",
            "desvio_pico": 60.0, "cronico": False, "sem_com_desde": None, "flags": [], "chave": "pg|21|Tracker 32|2026-10-04",
            "visto_ate": "2026-10-04"}
    trk = [{**base, "inicio": "2026-10-04 08:00", "fim": "2026-10-04 10:00", "perda_kwh": 5.0},
           {**base, "inicio": "2026-10-04 14:00", "fim": "2026-10-04 16:00", "perda_kwh": 6.0}]
    js = """T.S.aba = 'trk'; T.desenha(); const t = T.D.trackers.rows[1];
      await ELS.tab._ouv.change[0]({target: {closest: () => ({dataset: {chave: t.chave, id: T.idLinha(t)}, checked: true})}}); await espera();
      out({msg: ELS['desc-msg'].innerHTML, post: PEDIDOS.filter(p => p.metodo === 'POST').map(p => [p.corpo.chave, p.corpo.resumo.inicio])});"""
    r = _roda(tmp_path, pacote(trk=trk), js, resp={"/api/painel/falhas/desconsiderar": [200, {"ok": True, "n": 1}]})
    assert r["post"] == [["pg|21|Tracker 32|2026-10-04", "2026-10-04 14:00"]]
    assert r["msg"].startswith("Tirada da conta: <b>Aparecida 3 · tracker Tracker 32</b> · parou 04/10 14:00. Também sai a "
                               "parada de 04/10 08:00, que tem a mesma chave do dia.")


# ── 5. Baixar Excel: as linhas filtradas inteiras, número como número, datas no formato ─────────────────────────
@precisa_node
def test_o_excel_leva_todas_as_linhas_filtradas_sem_o_corte_da_pagina(tmp_path):
    # 75 ocorrências de um dia (uma por inversor) + a Inhapi: a tabela mostra 60; o Excel, as 76 — e a tirada fica de fora
    eps = [ep("Altair", f"Inversor {i // 10}.{i % 10}", "Ipv1", "2026-10-02 08:00", "2026-10-02 12:00", "voltou", "2026-10-02", "2026-10-02",
              float(i), pid="ALT") for i in range(10, 85)]
    js = """T.desenha(); const tela = (ELS.tab.innerHTML.match(/<tr[^>]* data-id=/g) || []).length;
      T.DESC_VIS.add(T.OC.find(o => o.inversor === 'Inversor 1.0').membros[0].chave); T.desenha();   // como a caixa faz
      for (const f of ELS['b-xls']._ouv.click) await f(); await espera();
      const corpo = PEDIDOS.find(p => p.url === '/api/painel/falhas/exportar').corpo;
      T.S.usina = 'Inhapi'; T.desenha();
      for (const f of ELS['b-xls']._ouv.click) await f(); await espera();
      const inh = PEDIDOS.filter(p => p.url === '/api/painel/falhas/exportar')[1].corpo;
      out({tela, corpo, inh});"""
    r = _roda(tmp_path, pacote(eps + INHAPI_EPS + GUATAMBU_EPS[:2], INHAPI_DIAS), js, resp={"/api/painel/falhas/exportar": [200, {}]})
    assert r["tela"] == 60
    oc, dd = r["corpo"]["abas"]
    assert r["corpo"]["nome"] == "strings_2026-10" and oc["nome"] == "Ocorrências" and dd["nome"] == "Dia a dia"
    assert [c["titulo"] for c in oc["colunas"]] == ["Cliente", "Usina", "Fonte", "Inversor", "Strings paradas", "Strings",
        "Máx. ao mesmo tempo", "Parou", "Voltou", "Hora da volta", "Situação", "Duração (h)", "Dias", "Perda (kWh)",
        "Perda estimada (kWh)", "OS vinculadas", "Avisos"]
    tipos = {c["titulo"]: c["tipo"] for c in oc["colunas"]}
    assert (tipos["Strings paradas"], tipos["Parou"], tipos["Voltou"], tipos["Perda (kWh)"]) == ("inteiro", "datahora", "data", "numero")
    assert len(oc["linhas"]) == 75 + 1 + 1 - 1                          # sem o corte de 60; a tirada (Inversor 1.0) fora
    col = {c["titulo"]: i for i, c in enumerate(oc["colunas"])}
    inh = next(l for l in oc["linhas"] if l[col["Usina"]] == "Inhapi")
    assert inh[col["Perda (kWh)"]] == 8024.8 and isinstance(inh[col["Strings paradas"]], int) and inh[col["Dias"]] == 20
    assert inh[col["Perda estimada (kWh)"]] == 1114.8 and inh[col["Parou"]] == "2026-10-01 06:30" and inh[col["Voltou"]] is None
    assert inh[col["Situação"]] == "parado agora"
    mad = next(l for l in oc["linhas"] if l[col["Usina"]] == "Guatambu")
    assert (mad[col["Voltou"]], mad[col["Hora da volta"]], mad[col["Situação"]]) == ("2026-10-05", "de madrugada", "voltou de madrugada")
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", l[col["Parou"]]) for l in oc["linhas"])
    assert all(l[col["Voltou"]] is None or re.fullmatch(r"\d{4}-\d{2}-\d{2}", l[col["Voltou"]]) for l in oc["linhas"])
    # o dia a dia: uma linha por ocorrência × dia (as 20 da Inhapi)
    dcol = {c["titulo"]: i for i, c in enumerate(dd["colunas"])}
    inh_d = [l for l in dd["linhas"] if l[dcol["Usina"]] == "Inhapi"]
    assert len(inh_d) == 20 and inh_d[0][dcol["Dia"]] == "2026-10-01" and inh_d[0][dcol["Das"]] == "06:00" and inh_d[0][dcol["Às"]] == "18:00"
    assert round(sum(l[dcol["Perda (kWh)"]] for l in inh_d), 1) == 8024.7    # as 20 linhas do dia (8.024,8 nas paradas: arredondamento)
    assert [l[dcol["Estimada"]] for l in inh_d].count("sim") == 4
    assert r["inh"]["nome"] == "strings_2026-10_Inhapi" and len(r["inh"]["abas"][0]["linhas"]) == 1


@precisa_node
def test_o_excel_dos_trackers_so_tem_o_dia_a_dia_quando_a_linha_traz_os_dias(tmp_path):
    t = {"chave": "pv|1|TRK1|2026-10-01", "fonte": "pv", "plant_id": "1", "cliente": "Thopen", "usina": "MAB200", "tracker": "TRK1",
         "inversor": "", "inicio": "2026-10-01 06:30", "fim": "2026-10-03", "visto_ate": "2026-10-02", "desvio_pico": None,
         "perda_kwh": 99.94, "cronico": False, "sem_com_desde": None, "flags": ["sem ângulo (fator 25%)"]}
    js = """T.S.aba = 'trk'; T.desenha(); for (const f of ELS['b-xls']._ouv.click) await f(); await espera();
      T.D.trackers.rows[0].dias = [['2026-10-01', '06:30', '18:00', 11.5, 60.0, 'sim'], ['2026-10-02', '06:00', '18:00', 12.0, 39.94, 'sem prova']];
      T.desenha(); for (const f of ELS['b-xls']._ouv.click) await f(); await espera();
      out(PEDIDOS.filter(p => p.url === '/api/painel/falhas/exportar').map(p => p.corpo));"""
    sem, com = _roda(tmp_path, pacote(trk=[t]), js, resp={"/api/painel/falhas/exportar": [200, {}]})
    assert [a["nome"] for a in sem["abas"]] == ["Paradas"] and [a["nome"] for a in com["abas"]] == ["Paradas", "Dia a dia"]
    p = sem["abas"][0]
    col = {c["titulo"]: i for i, c in enumerate(p["colunas"])}
    [l] = p["linhas"]
    assert (l[col["Voltou"]], l[col["Hora da volta"]], l[col["Dias"]], l[col["Perda (kWh)"]], l[col["Desvio (graus)"]]) == ("2026-10-03", "não registrada", 2, 99.9, None)
    assert "Sem o ângulo do tracker" in l[col["Avisos"]]
    assert com["abas"][1]["linhas"][1][-1] == "sem prova (dia que a geração ainda não cobre)"


@precisa_node
def test_texto_longo_vai_cortado_para_o_servidor_nao_recusar_o_excel_inteiro(tmp_path):
    # a rota recusa texto de mais de 500 caracteres (FALHAS_EXPORT_TEXTO_MAX): uma célula derrubaria o arquivo todo
    eps = [ep("Altair", "Inversor 1.1", "Ipv1", "2026-10-02 08:00", "2026-10-02 12:00", "voltou", "2026-10-02", "2026-10-02", 5.0,
              ["aviso " + "x" * 600], pid="ALT")]
    js = """T.desenha(); for (const f of ELS['b-xls']._ouv.click) await f(); await espera();
      out(PEDIDOS.find(p => p.url === '/api/painel/falhas/exportar').corpo.abas[0]);"""
    aba = _roda(tmp_path, pacote(eps), js, resp={"/api/painel/falhas/exportar": [200, {}]})
    col = [c["titulo"] for c in aba["colunas"]].index("Avisos")
    assert len(aba["linhas"][0][col]) == 500 and aba["linhas"][0][col].endswith("…")


@precisa_node
def test_erro_do_excel_fica_na_tela(tmp_path):
    js = """T.desenha(); for (const f of ELS['b-xls']._ouv.click) await f(); await espera();
      out({msg: ELS['baixa-msg'].innerHTML, hidden: ELS['baixa-msg'].hidden, botao: ELS['b-xls'].disabled});"""
    r = _roda(tmp_path, pacote(INHAPI_EPS), js, resp={"/api/painel/falhas/exportar": [500, {"ok": False, "motivo": "openpyxl caiu"}]})
    assert r["hidden"] is False and "Não consegui montar o Excel: openpyxl caiu." in r["msg"] and r["botao"] is False


# ── 7. todo id que o script pede existe na página ─────────────────────────────────────────────────────────────
def ids_que_faltam(html):
    """Os ids que o <script> pede — $('x'), getElementById('x'), querySelector('#x ...') — sem `id="x"` na página. O DOM de
    mentira dos testes de node cria qualquer id que se peça: sem isto, o falhas.html sem o id="b-xls" (o mutante da
    revisão de 20/10) passava em todos os testes, e no navegador o botão do Excel derrubava a página no 1º desenho."""
    js = "\n".join(re.findall(r"<script>(.*?)</script>", html, re.S))
    pedidos = set(re.findall(r"""\$\(\s*['"]([^'"]+)['"]\s*\)""", js))
    pedidos |= set(re.findall(r"""getElementById\(\s*['"]([^'"]+)['"]\s*\)""", js))
    pedidos |= set(re.findall(r"""querySelector(?:All)?\(\s*[`'"]#([A-Za-z][\w-]*)""", js))
    # os montados na hora: a pílula de cada aba ($('p-' + a)) e as duas caixas de recado (for (const id of [...]))
    pedidos |= {"p-str", "p-trk", "desc-msg", "g-msg"}
    return sorted(i for i in pedidos if f'id="{i}"' not in html)


def test_todo_id_que_o_script_pede_existe_na_pagina():
    assert ids_que_faltam(HTML) == []
    assert "lista-msg" not in HTML          # o recado dos vínculos foi para o cabeçalho da coluna OS (thOS)


def test_o_varredor_de_ids_acha_o_id_que_falta():
    # a prova de que o detector pega: os ids do mutante da revisão, um a um
    for i in ("b-xls", "baixa-msg", "tab", "conta", "g-msg", "p-trk"):
        assert ids_que_faltam(HTML.replace(f'id="{i}"', "")) == [i], i


# ── 6. sem o filtro de Fonte (o frescor e o mapa ficam) ───────────────────────────────────────────────────────
def test_o_filtro_de_fonte_saiu_e_o_frescor_ficou():
    assert 'id="f-fonte"' not in HTML and "S.fonte" not in HTML and "fonte: ''" not in HTML
    assert 'id="fonte"' in HTML and "const FONTE = {" in HTML                 # o frescor (sessão vencida) e o rótulo
    assert 'id="vis"' not in HTML and "S.vis" not in HTML and "data-vis" not in HTML   # a visão "Por string" saiu


# ── 7. Strings antes de Avisos (Levi, 21/10/2026: "aumenta o tamanho da coluna de strings prioriza mais isso que avisos")
def test_a_coluna_strings_tem_prioridade_sobre_avisos():
    assert "['qtd', 'Strings', 'col-str']" in HTML and "[null, 'Avisos', 'col-av']" in HTML
    assert "th.col-str,td.col-str{min-width:260px}" in HTML and "td.col-av .tag{white-space:normal}" in HTML
    assert '<td class="col-str">${strCel(r)}</td>' in HTML
    assert "' +' + (o.lista.length" not in HTML                       # a lista inteira, sem o "Ipv1, Ipv2 +2"
