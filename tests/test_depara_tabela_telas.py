# -*- coding: utf-8 -*-
"""As telas do Modo de-para (20/10/2026): a tabela por inversor do Tempo real e a Base · De-para de equipamentos, uma usina
por linha. Levi, com o protótipo aprovado: "Boa, é isso mesmo. Implementa no tempo real e adapta na base o de-para para
ficar nesse padrão de tabela e apresentar uma usina por linha".

O componente (`plataforma/static/depara_tabela.js`) roda aqui no node, com as rotas dubladas no formato delas e o dado de
20/10 da Itajá e da Pharmas (os dois casos do protótipo): as sugestões, a conta do kWp, o Conferido, o inversor repetido,
o Salvar (primeiro o Nexus, depois a ponte, e a falha de um dos dois dita com todas as letras) e a Base com uma usina por
linha. Por último, a ligação nas duas telas e a chave do cadastro que a linha da API PV passou a levar."""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
COMP = RAIZ / "plataforma" / "static" / "depara_tabela.js"
MON = (RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")
DEP = (RAIZ / "plataforma" / "templates" / "depara.html").read_text(encoding="utf-8")
NODE = shutil.which("node")

# o dado de 20/10 (protótipo + banco) nos formatos das rotas da plataforma e do Nexus
FIXTURAS = r"""
const inv = cod => ({codigo: cod, nome: 'Inversor ' + cod.split('INVR')[1], descricao: 'Inversor 1.3 Huawei SUN2000-250KTL-H1'});
const arv = (codigo, nome, cabs, extra) => Object.assign({codigo, nome, cliente: 'Thopen', usina_id: null,
  cabines: cabs.map(([c, is]) => ({codigo: c, nome: 'Cabine ' + c.match(/CABN(\d+)/)[1], inversores: is.map(inv)})),
  sem_cabine: [], fonte: 'foto', pendente: false}, extra || {});
const N = (pre, n, m) => Array.from({length: m}, (_, i) => `${pre}-INVR${n}.${i + 1}`);
F.arvores = {
  'THOPEN-ITA100': arv('THOPEN-ITA100', 'Thopen - Itajá 1 e 2 - RN', [['ITA100-CABN1', N('ITA100', 1, 4)], ['ITA100-CABN2', N('ITA100', 2, 4)]], {usina_id: 93}),
  'THPN-PHS200': arv('THPN-PHS200', 'Thopen - Pharmas 2 - PR', [['THPN-PHS200-CABN1', N('THPN-PHS200', 1, 6)]], {usina_id: 108}),
  'THPN-PHS300': arv('THPN-PHS300', 'Thopen - Pharmas 3 - PR', [['THPN-PHS300-CABN1', N('THPN-PHS300', 1, 6)]], {usina_id: 109}),
  'THPN-PHS400': arv('THPN-PHS400', 'Thopen - Pharmas 4 - PR', [['THPN-PHS400-CABN1', N('THPN-PHS400', 1, 6)]], {usina_id: 110}),
  'THPN-PHS100': arv('THPN-PHS100', 'THPN-PHS100', [['THPN-PHS100-CABN2', N('THPN-PHS100', 2, 6)], ['THPN-PHS100-CABN3', N('THPN-PHS100', 3, 6)], ['THPN-PHS100-CABN4', N('THPN-PHS100', 4, 6)]], {fora_da_foto: true}),
};
F.ufs = Object.values(F.arvores).map(a => ({codigo: a.codigo, nome: a.nome, cliente: 'Thopen', usina_id: a.usina_id,
  cabines: a.cabines.map(c => ({codigo: c.codigo, nome: c.nome})), fonte: 'foto'}));
F.registro = [
  {usina_id: 93, codigo: 'ITA100', nome: 'Itajá 1 e 2', status: 'OPERAÇÃO', kwp: 2596, kwp_de: 'real', cliente: 'Thopen'},
  {usina_id: 108, codigo: 'THPN-PHS200', nome: 'Pharmas 2', status: 'OPERAÇÃO', kwp: 990, kwp_de: 'real', cliente: 'Thopen'},
  {usina_id: 109, codigo: 'THPN-PHS300', nome: 'Pharmas 3', status: 'OPERAÇÃO', kwp: 990, kwp_de: 'real', cliente: 'Thopen'},
  {usina_id: 110, codigo: 'THPN-PHS400', nome: 'Pharmas 4', status: 'OPERAÇÃO', kwp: 990, kwp_de: 'real', cliente: 'Thopen'},
  {usina_id: 161, codigo: 'QAIR-AQZ100', nome: 'Aquiraz 1 (Salvales)', status: 'OPERAÇÃO', kwp: 3260, kwp_de: 'contratual', cliente: 'Qair'},
  {usina_id: 200, codigo: 'XYZ100', nome: 'Sem Potência', status: 'A MOBILIZAR', kwp: null, kwp_de: null, cliente: 'X'},
];
const r = (pid, usina, ids, nomes, esp, extra) => Object.assign({plant_id: pid, usina, depara_fonte: 'pv', qtd_inversores: ids.length, strings_ativas: 76,
  inv_resumo: ids.map((id, i) => ({id, nome_api: nomes[i], nome: nomes[i], ativas: 19, total: 30, esp: esp[i], sem_visao: false}))}, extra || {});
const I4 = ['INVERSOR01', 'INVERSOR02', 'INVERSOR03', 'INVERSOR04'], I6 = I4.concat(['INVERSOR05', 'INVERSOR06']);
F.linhas = [
  r(18749574, 'Itaja 1 (228)', [365249, 365250, 365247, 365251], I4, [null, null, null, null]),
  r(18749576, 'Itaja 2 (229)', [365252, 365254, 365253, 365255], I4, [null, null, null, null]),
  r(18758592, 'Pharma II', [378064, 378065, 378066, 378067, 378068, 378069], ['Inversor 1.1', 'Inversor 1.2', 'Inversor 1.3', 'Inversor 1.4', 'Inversor 1.5', 'Inversor 1.6'], [14, 14, 14, 14, 13, 13], {chave_cadastro: 'Pharma 2', strings_ativas: 0}),
  r(18751504, 'Pharma 3 (851)', [368373, 368374, 368375, 368376, 368377, 368378], I6, [null, null, null, null, null, null], {strings_ativas: 0}),
];
F.fractall = {'Pharma II': 'Thopen - Pharmas 2 - PR', 'Pharma 2': 'Thopen - Pharmas 2 - PR'};
const nInv = (id, sid, chave, nome, esup, cab, str, kwp) => ({inversor_id: id, supervisorio_id: sid, usina_supervisorio: chave, nome,
  equipamento_supervisorio: esup, cabine_id: cab, strings_esperadas_qtd: str, potencia_kwp: kwp, codigo_fracttal: null, equipamento_id: null,
  potencia_regra: null, fracttal_ligado_por: null, conferido_em: null});
F.nexus = {
  93: {usina_id: 93, nome: 'Itajá 1 e 2', codigo: 'ITA100', selo: 'selo-93', kwp: 2596, kwp_de: 'real',
    chaves: [{supervisorio_id: 162, usina_supervisorio: 'Itaja 1 (551)', principal: false, substitui_aba: false},
      {supervisorio_id: 163, usina_supervisorio: 'Itaja 2 (552)', principal: false, substitui_aba: false},
      {supervisorio_id: 164, usina_supervisorio: 'Itajá', principal: true, substitui_aba: false}],
    cabines: [{cabine_id: 176, nome: 'UG 01', codigo_fracttal: null, potencia_kwp: 1298.08}, {cabine_id: 177, nome: 'UG 02', codigo_fracttal: null, potencia_kwp: 1298.08}],
    inversores: [1, 2, 3, 4].map(m => nInv(1317 + m, 162, 'Itaja 1 (551)', 'Inversor 1.' + m, 'INVERSOR0' + m, 176, 19, 324.52))
      .concat([1, 2, 3, 4].map(m => nInv(1321 + m, 163, 'Itaja 2 (552)', 'Inversor 2.' + m, 'INVERSOR0' + m, 177, 19, 324.52)))},
  108: {usina_id: 108, nome: 'Pharmas 2', codigo: 'THPN-PHS200', selo: 'selo-108', kwp: 990, kwp_de: 'real',
    chaves: [{supervisorio_id: 170, usina_supervisorio: 'Pharma 2', principal: true, substitui_aba: false}],
    cabines: [{cabine_id: 190, nome: 'UG 01', codigo_fracttal: null, potencia_kwp: 990}],
    inversores: [14, 14, 14, 14, 13, 13].map((s, i) => nInv(1400 + i, 170, 'Pharma 2', 'Inversor 1.' + (i + 1), 'Inversor 1.' + (i + 1), 190, s, 165))},
  109: {usina_id: 109, nome: 'Pharmas 3', codigo: 'THPN-PHS300', selo: 'selo-109', kwp: 990, kwp_de: 'real', chaves: [], cabines: [], inversores: []},
};
// o cadastro da plataforma (`/api/admin/de-para/cadastro`: a aba com as chaves do Nexus por cima), como a aba de 20/10
const C = (chave, exib, invs) => ({chave, exibicao: exib, inversores: invs.map(([esup, nome, esp, kwp, ug]) => ({esup, nome, esp, kwp, ug}))});
F.cadastro = [
  C('Itaja 1 (551)', 'Itajá', [1, 2, 3, 4].map(m => ['INVERSOR0' + m, 'Inversor 1.' + m, 19, 324.52, 'UG 01'])),
  C('Itaja 2 (552)', 'Itajá', [1, 2, 3, 4].map(m => ['INVERSOR0' + m, 'Inversor 2.' + m, 19, 324.52, 'UG 02'])),
  C('Pharma 2', 'Pharma 2', [14, 14, 14, 14, 13, 13].map((s, i) => ['Inversor 1.' + (i + 1), 'Inversor 1.' + (i + 1), s, 165, 'UG 01'])),
];
F.eu = {abre_admin: true, grava_admin: true};
// as rotas dubladas: a plataforma e o Nexus (na mesma origem, debaixo de /nexus). `corpo` string = a página (HTML)
const resp = (status, corpo) => ({ok: status >= 200 && status < 300, status,
  text: async () => corpo === undefined ? '' : typeof corpo === 'string' ? corpo : JSON.stringify(corpo),
  json: async () => { if (corpo === undefined || typeof corpo === 'string') throw new Error('sem JSON'); return corpo; }});
const PEDIDOS = [];
const DUBLE = {salvar: null, estado: null, decidir: () => resp(200, {ok: true, gravadas: 1, total: 21})};
globalThis.fetch = async (url, init) => {
  const body = init && init.body ? JSON.parse(init.body) : null;
  PEDIDOS.push({url, method: (init && init.method) || 'GET', body});
  if (url === '/api/eu') return resp(200, F.eu);
  if (url.startsWith('/api/admin/de-para/cadastro')) return resp(200, {chaves: F.cadastro, carregado_em: '20/10 13:00:00'});
  if (url.startsWith('/api/admin/de-para/fracttal/usinas')) return resp(200, {usinas: F.ufs, fonte: 'foto', lido_em: '2026-10-20T13:00:00Z', foto_em: '2026-09-22'});
  if (url.startsWith('/api/admin/de-para/fracttal/arvore')) { const c = decodeURIComponent(url.split('codigo=')[1]); return F.arvores[c] ? resp(200, F.arvores[c]) : resp(404, {error: 'não existe'}); }
  if (url.startsWith('/api/admin/de-para/registro')) return resp(200, {usinas: F.registro, lido_em: '2026-10-20T13:01:00Z'});
  if (url.startsWith('/api/os-creator/fractall-usinas')) return resp(200, {map: F.fractall});
  if (url.startsWith('/nexus/t/base/equipamentos/depara/estado')) {
    if (DUBLE.estado) return DUBLE.estado(url);
    const q = new URLSearchParams(url.split('?')[1]);
    const chaves = (q.get('chaves') || '').split('|').filter(Boolean), us = (q.get('usinas') || '').split(',').filter(Boolean).map(Number);
    const out = [], sem = [];
    chaves.forEach(c => { const u = Object.values(F.nexus).find(x => x.chaves.some(y => y.usina_supervisorio === c)); if (u) { if (!out.includes(u)) out.push(u); } else sem.push(c); });
    us.forEach(id => { if (F.nexus[id] && !out.includes(F.nexus[id])) out.push(F.nexus[id]); });
    return resp(200, {ok: true, usinas: out, chaves_sem_usina: sem});
  }
  if (url.startsWith('/nexus/t/base/equipamentos/depara/salvar')) {
    const r = DUBLE.salvar ? DUBLE.salvar(body) : resp(200, {ok: true, usinas: body.itens.map(it => F.nexus[it.usina_id]), kwp: {}, visao_mudou: true, erros: [], avisos: [], mudancas: 9});
    if (r === 'rede') throw new TypeError('Failed to fetch');           // a rede caiu na volta, ou o estouro de 180 s
    return r;
  }
  if (url.startsWith('/api/admin/de-para/decidir')) return DUBLE.decidir(body);
  return resp(404, {error: 'rota não dublada: ' + url});
};
globalThis.GC_NEXUS_BASE = '/nexus';
"""


def _node(corpo: str, tmp_path) -> dict:
    """Roda `corpo` (async) com o componente (DT), as fixturas (F), os pedidos feitos (PEDIDOS) e as dublês (DUBLE); o corpo
    devolve um objeto, que volta como JSON."""
    if not NODE:
        pytest.skip("node não instalado")
    js = tmp_path / "caso.js"
    js.write_text("const F = {};\n" + FIXTURAS + f"\nconst DT = require({json.dumps(str(COMP))});\n"
                  "(async () => {\n" + corpo + "\n})().then(r => process.stdout.write(JSON.stringify(r)))"
                  ".catch(e => { console.error(e && e.stack || e); process.exit(1); });\n", encoding="utf-8")
    p = subprocess.run([NODE, str(js)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


_CTX = """const R = DT.regras;
const ctx = {ufs: F.ufs, ufPor: Object.fromEntries(F.ufs.map(u => [u.codigo, u])), arvores: F.arvores, reg: F.registro,
  regPor: Object.fromEntries(F.registro.map(r => [r.usina_id, r])), nexus: F.nexus, chaveUsina: {}, fractall: F.fractall};
Object.values(F.nexus).forEach(u => u.chaves.forEach(c => { ctx.chaveUsina[c.usina_supervisorio] = u.usina_id; }));
const sugere = l => { const g = R.grupoDaLinha(l, 'pv'), e = R.escolheUF(g, R.candidatosUF(g, ctx), ctx);
  const reg = R.sugereRegistro(g, e && e.codigo, ctx), ch = reg && R.sugereChave(g, reg.uid, ctx);
  return {uf: e && e.codigo, reg: reg && reg.uid, chave: ch && ch.chave,
    invs: g.invs.map(i => { const a = R.sugereInversor(g, i, ctx.arvores[e.codigo], e.metodo); return a ? [a.codigo, a.cab] : null; })}; };
"""


# ── as sugestões (Itajá e Pharmas, os dois casos do protótipo) ───────────────────────────────────────────────────────
def test_a_itaja_sugere_o_ita100_a_cabine_de_cada_planta_e_a_chave_do_mesmo_numero(tmp_path):
    """A API escreve "Itaja 1 (228)" e o cadastro tem "Itaja 1 (551)" (sem de-para hoje). Um site do Fracttal para as duas
    plantas: a Itaja 1 cai na Cabine 1 com os INVR1.x e a Itaja 2 na Cabine 2 com os INVR2.x; o "(228)" é o id da API, não o
    número da planta."""
    r = _node(_CTX + "return [sugere(F.linhas[0]), sugere(F.linhas[1])];", tmp_path)
    assert r[0] == {"uf": "THOPEN-ITA100", "reg": 93, "chave": "Itaja 1 (551)",
                    "invs": [[f"ITA100-INVR1.{m}", "ITA100-CABN1"] for m in (1, 2, 3, 4)]}
    assert r[1]["uf"] == "THOPEN-ITA100" and r[1]["chave"] == "Itaja 2 (552)"
    assert r[1]["invs"] == [[f"ITA100-INVR2.{m}", "ITA100-CABN2"] for m in (1, 2, 3, 4)]


def test_a_pharmas_vai_para_a_arvore_de_hoje_e_nao_para_a_da_foto(tmp_path):
    """A aba ainda diz "Thopen - Pharmas 2 - PR" (a PHS200 da foto de 22/09), e o Fracttal de hoje juntou as três na
    THPN-PHS100, com CABN2/3/4. A Pharma II (que o cadastro chama "Inversor 1.1".."1.6") casa os 6 inversores nas duas
    árvores; vale a mais nova, e o número da planta põe os inversores na CABN2. O Registro mestre segue o de cada planta:
    a Pharmas 2 pela chave já ligada no Nexus e a Pharmas 3 pela irmã de mesmo código-base com o número da planta."""
    r = _node(_CTX + "return [sugere(F.linhas[2]), sugere(F.linhas[3])];", tmp_path)
    assert r[0]["uf"] == "THPN-PHS100" and r[0]["reg"] == 108 and r[0]["chave"] == "Pharma 2"
    assert r[0]["invs"] == [[f"THPN-PHS100-INVR2.{m}", "THPN-PHS100-CABN2"] for m in range(1, 7)]
    assert r[1]["uf"] == "THPN-PHS100" and r[1]["reg"] == 109 and r[1]["chave"] is None     # a 109 não tem chave no Nexus
    assert r[1]["invs"] == [[f"THPN-PHS100-INVR3.{m}", "THPN-PHS100-CABN3"] for m in range(1, 7)]


def test_o_numero_sai_do_codigo_e_nunca_da_descricao(tmp_path):
    """2.380 das 2.477 descrições trazem marca e modelo ("Inversor 1.3 Huawei SUN2000-250KTL-H1"): o nome do ativo na
    tabela é o do código."""
    r = _node(_CTX + """const a = JSON.parse(JSON.stringify(F.arvores['THPN-PHS100']));
      a.cabines[0].inversores[0].nome = 'Inversor 1.3 Huawei SUN2000-250KTL-H1';
      return {nomes: R.invsDaArvore(a).slice(0, 2).map(i => i.nome), rot: R.rotuloInversor('THPN-PHS100-INVR02.01'),
        num: [R.num('Itaja 2 (229)'), R.num('Pharma II'), R.num('INVERSOR03')], base: [R.baseNome('Ceilandia 1.1 (89)'), R.baseNome('Brodowski - Skid 1')]};""", tmp_path)
    assert r == {"nomes": ["Inversor 2.1", "Inversor 2.2"], "rot": "Inversor 2.1", "num": [2, 2, 3],
                 "base": ["ceilandia", "brodowski"]}


def test_a_planta_com_rotulo_de_subusina_usa_o_numero_do_cadastro(tmp_path):
    """"Ceilandia 1.2 (90)" é a subusina 1.2: o ".2" do fim não é o número da planta. Lido como planta 2, a Ceilandia 1.2
    (que o cadastro chama "Inversor 3.1".."4.7") ia para os INVR2.x da CLN100: 33 dos 841 inversores da `pv` errados na
    medida de 20/10 (com a regra, 839 de 841 certos). O número da planta é o N do rótulo, e no empate vale o nome."""
    r = _node(_CTX + """
      const arv = {codigo: 'THPN-CLN100', nome: 'Thopen - Ceilândia 1 - DF', cliente: 'Thopen', usina_id: null, sem_cabine: [], fonte: 'foto',
        cabines: [{codigo: 'CLN100-CABN1', nome: 'Cabine 1', inversores: ['2.1', '2.2', '3.1', '3.2'].map(n => ({codigo: 'THPN-CLN100-INVR' + n}))}]};
      ctx.arvores['THPN-CLN100'] = arv; ctx.ufs.push({codigo: 'THPN-CLN100', nome: arv.nome, cliente: 'Thopen', usina_id: null, cabines: [], fonte: 'foto'});
      ctx.ufPor['THPN-CLN100'] = ctx.ufs[ctx.ufs.length - 1];
      const g = R.grupoDaLinha({plant_id: 90, usina: 'Ceilandia 1.2 (90)', depara_fonte: 'pv', inv_resumo: [
        {id: 1, nome_api: 'SKID 3 INV 1', nome: 'Inversor 3.1'}, {id: 2, nome_api: 'SKID 3 INV 2', nome: 'Inversor 3.2'}]}, 'pv');
      const e = R.escolheUF(g, R.candidatosUF(g, ctx), ctx);
      return {n: R.numeroDaPlanta(g), junco: R.numeroDaPlanta({usina: 'Junco 2.1 (134)'}), uf: e.codigo, metodo: e.metodo,
        invs: g.invs.map(i => R.sugereInversor(g, i, arv, e.metodo).codigo)};""", tmp_path)
    assert r["n"] == 1 and r["junco"] == 2 and r["uf"] == "THPN-CLN100" and r["metodo"] == "a"
    assert r["invs"] == ["THPN-CLN100-INVR3.1", "THPN-CLN100-INVR3.2"]


# ── a conta do kWp ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_o_kwp_e_a_regra_do_levi_na_usina_inteira(tmp_path):
    """kWp do inversor = kWp do Registro ÷ Σ strings corretas da usina INTEIRA × strings dele; a cabine soma os seus. Na
    Itajá 2.596 ÷ 152 × 19 = 324,5 (as duas chaves no Nexus entram na conta); só a Itaja 1, sem a Itaja 2 no Nexus, daria
    649, o dobro: é o que o Nexus faria, e a tela mostra o que ele vai gravar. Na Pharma II, 990 ÷ 82 × 14 e × 13."""
    r = _node(_CTX + """
      const um = R.contaKwp(2596, [1, 2, 3, 4].flatMap(m => [{id: 'a' + m, strings: 19, cab: 'C1', k: 'a' + m}, {id: 'b' + m, strings: 19, cab: 'C2'}]));
      const so = R.contaKwp(2596, [1, 2, 3, 4].map(m => ({id: 'a' + m, strings: 19, cab: 'C1', k: 'a' + m})));
      const ph = R.contaKwp(990, [14, 14, 14, 14, 13, 13].map((s, i) => ({id: 'p' + i, strings: s, cab: 'CABN2', k: 'p' + i})));
      const sem = R.contaKwp(null, [{id: 'x', strings: 10, k: 'x'}]);
      const sob = R.sobrepor([{id: 'a', strings: 19, cab: 'C1'}], [{id: 'a', strings: null, cab: '', k: 'ka'}, {id: 'n', strings: 12, cab: '-', k: 'kn'}]);
      const r3 = v => Math.round(v * 1000) / 1000;
      return {um: [r3(um.inv.a1), r3(um.cab.C1.kwp), um.total], so: r3(so.inv.a1), ph: [r3(ph.inv.p0), r3(ph.inv.p4), r3(ph.cab.CABN2.kwp)],
        sem: [sem.por, Object.keys(sem.inv).length], sob};""", tmp_path)
    assert r["um"] == [324.5, 1298.0, 152] and r["so"] == 649.0
    assert r["ph"] == [169.024, 156.951, 990.0] and r["sem"] == [None, 0]       # sem kWp no Registro: em branco
    # o vazio da tela não apaga o que o Nexus tem (o remendo não mexe no que vem vazio)
    assert r["sob"] == [{"id": "a", "strings": 19, "cab": "C1", "k": "ka"}, {"id": "n", "strings": 12, "cab": "", "k": "kn"}]


# ── a instância: o Conferido, o repetido e o Salvar ──────────────────────────────────────────────────────────────────
_ENTRA = "const inst = DT.criar({fonte: 'pv'}); await inst.entrar(F.linhas, 'pv');\n"


def test_a_tabela_abre_com_as_sugestoes_o_kwp_e_a_regra_do_registro(tmp_path):
    r = _node(_ENTRA + """const h = inst.html();
      return {linhas: (h.match(/class="dp-row"/g) || []).length, grupos: (h.match(/class="dp-grupo"/g) || []).length,
        col: (h.split('<thead>')[1].split('</thead>')[0].match(/<th/g) || []).length,
        itaja: h.includes('324,5 kWp'), pharma: h.includes('169,0 kWp') && h.includes('157,0 kWp'),
        conta: h.includes('2.596,0 kWp ÷ 152 strings corretas'), tracejado: (h.match(/class="cel j-at sug/g) || []).length,
        lazy: (h.match(/data-lazy="reg"/g) || []).length, opcoesReg: (h.match(/<option value="9\\d"/g) || []).length,
        pend3: h.includes('falta a chave do cadastro'), conf: (h.match(/data-acao="conf"/g) || []).length};""", tmp_path)
    assert r["linhas"] == 20 and r["grupos"] == 4 and r["col"] == 9          # uma linha por inversor, agrupada por usina
    assert r["itaja"] and r["pharma"] and r["conta"]
    assert r["tracejado"] == 20                                                # tudo é sugestão até alguém conferir
    # as listas grandes ficam com uma opção só até a pessoa abrir (a `pv` tem 840 inversores)
    assert r["lazy"] == 20 and r["opcoesReg"] <= 20
    assert r["pend3"]                                                          # a Pharma 3 sem chave no Nexus diz o que falta
    # o Conferido é da linha: a Pharma 3 confere os inversores, e a falta da chave (do grupo) segura só o Salvar
    assert r["conf"] == 20


def test_conferido_desfazer_e_conferir_todos(tmp_path):
    r = _node(_ENTRA + """const k = id => '18749574|' + id, out = {};
      out.antes = inst.pronto(18749574);
      [365249, 365250, 365247, 365251].forEach(id => inst.conferir(k(id), true));
      out.depois = inst.pronto(18749574);
      inst.conferir(k(365249), false);
      out.um = [inst.pronto(18749574), inst.S.sel[k(365249)].sug];
      [365250, 365247, 365251].forEach(id => inst.conferir(k(id), false));
      out.desfeito = inst.pronto(18749574);
      inst.conferirTodos();
      out.todos = [inst.pronto(18749574), inst.pronto(18749576), inst.pronto(18758592), inst.pronto(18751504)];
      return out;""", tmp_path)
    assert r["antes"] is False and r["depois"] is True                         # só o que a pessoa mexeu ou conferiu vai
    assert r["um"] == [True, True]                 # desfazer um volta a sugestão; os outros três seguem para salvar
    assert r["desfeito"] is False                  # desfeitos todos, a usina volta ao que era: nada a salvar
    assert r["todos"] == [True, True, True, False]                             # a Pharma 3 fica: falta a chave


def test_o_mesmo_codigo_em_dois_inversores_e_pendencia(tmp_path):
    """O "inversor repetido" do protótipo (a Coração 2 sugeria os mesmos ativos da Coração 1): na tela, e contra o que o
    Nexus já tem gravado num inversor que não está na tela."""
    r = _node(_ENTRA + """const out = {};
      await inst.mudar('18749576|365252', 'j-cab', 'ITA100-CABN1');
      await inst.mudar('18749576|365252', 'j-at', 'ITA100-INVR1.1');
      out.tela = [inst.pendencia(18749574, 365249), inst.pendencia(18749576, 365252)];
      await inst.mudar('18749576|365252', 'j-cab', 'ITA100-CABN2');
      await inst.mudar('18749576|365252', 'j-at', 'ITA100-INVR2.1');
      inst.S.ctx.nexus[109].inversores.push({inversor_id: 9, usina_supervisorio: 'Outra', nome: 'Inversor 9.9', equipamento_supervisorio: 'X', codigo_fracttal: 'THPN-PHS100-INVR3.1'});
      out.nexus = inst.pendencia(18751504, 368373);
      out.livre = inst.pendencia(18749576, 365252);
      return out;""", tmp_path)
    assert r["tela"] == ["inversor repetido", "inversor repetido"]
    assert r["nexus"] == "já está no Inversor 9.9 (Outra) no Nexus" and r["livre"] == ""


def test_o_inversor_trocado_fica_de_fora_e_a_usina_salva(tmp_path):
    """A API PV ainda lista o inversor trocado ("INVERSOR 2.1 (old)", "INVERSOR03-Cancelado"): os dois casam o mesmo ativo
    e a usina inteira ficava presa no "inversor repetido" (Embu Guaçu 2 e 3, Indaiatuba 2 e Junco 1 na bancada de
    20/10). "Deixar de fora" tira a linha do pedido: o remendo do Nexus não mexe no que não vai. Tudo de fora não salva."""
    r = _node("""F.linhas[0].inv_resumo.push({id: 999, nome_api: 'INVERSOR01 (old)', nome: 'INVERSOR01 (old)', ativas: 0, total: 0, esp: null, sem_visao: false});
      const inst = DT.criar({fonte: 'pv'}); await inst.entrar(F.linhas, 'pv');
      const out = {};
      await inst.mudar('18749574|999', 'j-cab', 'ITA100-CABN1'); await inst.mudar('18749574|999', 'j-at', 'ITA100-INVR1.1');
      out.antes = [inst.pendencia(18749574, 999), inst.pendencia(18749574, 365249)];
      inst.deixarDeFora('18749574|999', true);
      out.depois = [inst.pendencia(18749574, 999), inst.pendencia(18749574, 365249)];
      ['365249', '365250', '365247', '365251'].forEach(id => inst.conferir('18749574|' + id, true));
      out.pronto = inst.pronto(18749574);
      out.html = inst.html().includes('fica de fora');
      await inst.salvar();
      const it = PEDIDOS.find(p => p.url.endsWith('/salvar')).body.itens.find(i => i.usina_supervisorio === 'Itaja 1 (551)');
      out.enviados = it.inversores.map(i => i.equipamento_supervisorio);
      ['365252', '365254', '365253', '365255'].forEach(id => inst.deixarDeFora('18749576|' + id, true));
      out.tudoDeFora = inst.pronto(18749576);
      return out;""", tmp_path)
    assert r["antes"] == ["inversor repetido", "inversor repetido"] and r["depois"] == ["", ""]
    assert r["pronto"] is True and r["html"]
    assert r["enviados"] == ["INVERSOR01", "INVERSOR02", "INVERSOR03", "INVERSOR04"]      # o (old) não vai
    assert r["tudoDeFora"] is False                    # a chave iria "no lugar da aba" sem inversor nenhum


def test_salvar_grava_primeiro_o_nexus_e_depois_a_ponte(tmp_path):
    """O remendo vai ao Nexus com a chave do cadastro, a usina do Registro, o selo e, por inversor, o nome no supervisório,
    as strings, a CABN, o código e o Conferido; a ponte da fonte para a chave vai DEPOIS, só quando a chave não é a de
    hoje (a Itaja 1 (228) não liga a nada; a Pharma II já liga à "Pharma 2")."""
    r = _node(_ENTRA + """inst.conferirTodos();
      await inst.salvar();
      const posts = PEDIDOS.filter(p => p.method === 'POST' && !p.url.includes('fractall')).map(p => [p.url, p.body]);
      return {posts, res: inst.S.resultado.nexus.map(x => [x.g.usina, x.ok, x.ponte || null]), sobrou: inst.mexidos(),
        pharma3: inst.pronto(18751504)};""", tmp_path)
    urls = [u for u, _ in r["posts"]]
    salvar = [b for u, b in r["posts"] if u == "/nexus/t/base/equipamentos/depara/salvar"]
    assert urls == ["/nexus/t/base/equipamentos/depara/salvar"] + ["/api/admin/de-para/decidir"] * 2   # o Nexus primeiro
    # um pedido só (2ª revisão final, 21/10): a Pharma, com a árvore da THPN-PHS100 fora da foto, ia num pedido só dela, e a
    # troca de códigos entre usinas em pedidos diferentes era recusada nos dois; a recusa do código fora da dimensão volta
    # com a culpada (D-f) e o resto vai de novo sem ela
    assert [len(b["itens"]) for b in salvar] == [3]
    itens = {i["usina_supervisorio"]: i for b in salvar for i in b["itens"]}
    assert set(itens) == {"Itaja 1 (551)", "Itaja 2 (552)", "Pharma 2"}       # a Pharma 3 (sem chave) fica de fora
    assert itens["Itaja 1 (551)"]["usina_id"] == 93 and itens["Itaja 1 (551)"]["selo"] == "selo-93"
    # o `nome` é o do cadastro da chave (P-i): o inversor que o Nexus criar nasce com o "Equipamento" da aba
    assert itens["Itaja 1 (551)"]["inversores"][0] == {"equipamento_supervisorio": "INVERSOR01", "nome": "Inversor 1.1",
                                                       "strings": 19, "cabine_codigo_fracttal": "ITA100-CABN1",
                                                       "codigo_fracttal": "ITA100-INVR1.1", "conferido": True}
    assert itens["Pharma 2"]["inversores"][4]["equipamento_supervisorio"] == "Inversor 1.5"     # o nome no supervisório
    assert itens["Pharma 2"]["inversores"][4]["codigo_fracttal"] == "THPN-PHS100-INVR2.5"
    assert r["posts"][1][1] == {"fonte": "pv", "id": "18749574", "usina_supervisorio": "Itaja 1 (551)"}
    assert sorted(r["res"]) == [["Itaja 1 (228)", True, "ok"], ["Itaja 2 (229)", True, "ok"], ["Pharma II", True, "já ligava"]]
    # o que o Nexus devolveu vira a base. A Pharma 3 não foi conferida pelo "conferir todos": as strings dela vieram da
    # leitura de agora (P-d) e pedem o Conferido da linha; ela nem fica mexida, e segue fora do Salvar (sem a chave)
    assert r["sobrou"] == 0 and r["pharma3"] is False


def test_falha_parcial_e_dita_com_todas_as_letras(tmp_path):
    """O Nexus grava e a ponte não (a máquina sem o GRIDCO_SQL_TOKEN): a usina diz que a estrutura foi e a ponte não. O
    Nexus recusa (o selo velho, 409): nada desta usina foi gravado, e a ponte DELA nem é tentada (a ponte pendente da
    Itaja 1 vai de novo no mesmo Salvar: P-b)."""
    r = _node(_ENTRA + """DUBLE.decidir = () => resp(503, {error: 'sem GRIDCO_SQL_TOKEN nesta máquina'});
      ['365249', '365250', '365247', '365251'].forEach(id => inst.conferir('18749574|' + id, true));
      await inst.salvar();
      const um = {res: inst.S.resultado.nexus.map(x => [x.g.usina, x.ok, x.ponte, x.ponteMotivo || null])};
      inst.S.resultado = null;
      DUBLE.salvar = () => resp(409, {ok: false, motivo: 'A estrutura da usina da chave “Itaja 2 (552)” mudou desde que a tela abriu (outra aba ou outra pessoa): recarregue. Nada foi gravado.'});
      ['365252', '365254', '365253', '365255'].forEach(id => inst.conferir('18749576|' + id, true));
      const antes = PEDIDOS.length;
      await inst.salvar();
      um.dois = inst.S.resultado.nexus.map(x => [x.g.usina, x.ok, x.motivo]);
      um.ponteDepois = PEDIDOS.slice(antes).filter(p => p.url.includes('decidir')).map(p => p.body.id);
      return um;""", tmp_path)
    assert r["res"] == [["Itaja 1 (228)", True, "falhou", "sem GRIDCO_SQL_TOKEN nesta máquina"]]
    assert r["dois"][0][1] is False and "mudou desde que a tela abriu" in r["dois"][0][2]
    assert r["ponteDepois"] == ["18749574"]               # só a ponte pendente da Itaja 1; nenhuma da Itaja 2


def test_o_resultado_na_barra_diz_o_que_foi_e_o_que_nao_foi(tmp_path):
    r = _node(_ENTRA + """DUBLE.decidir = () => resp(503, {error: 'sem GRIDCO_SQL_TOKEN nesta máquina'});
      ['365249', '365250', '365247', '365251'].forEach(id => inst.conferir('18749574|' + id, true));
      await inst.salvar();
      return {h: inst.S.resultado && 1};""", tmp_path)
    assert r["h"] == 1
    # o texto é montado no componente: a ponte que falhou diz o que fazer
    js = COMP.read_text(encoding="utf-8")
    assert "o Nexus gravou a estrutura, a ponte NÃO" in js and "o Nexus NÃO gravou" in js
    assert "Nada desta usina foi gravado, e a ponte não foi tentada." in js


def test_sem_o_nexus_nesta_tela_da_para_conferir_mas_nao_salvar(tmp_path):
    r = _node("""globalThis.GC_NEXUS_BASE = undefined; delete globalThis.GC_NEXUS_BASE;
      const inst = DT.criar({fonte: 'pv'}); await inst.entrar(F.linhas, 'pv');
      inst.conferirTodos(); const n = PEDIDOS.length; await inst.salvar();
      return {h: inst.html().includes('Sem o Nexus nesta tela'), nexus: PEDIDOS.filter(p => p.url.startsWith('/nexus')).length, depois: PEDIDOS.length - n,
        itaja: inst.html().includes('324,5 kWp')};""", tmp_path)
    assert r["h"] and r["nexus"] == 0 and r["depois"] == 0
    assert r["itaja"] is False          # sem o Nexus a conta é só da tela, e a Itajá do cadastro (19 strings) não vem


# ── a 1ª revisão (20/10): os achados e as decisões do orquestrador, um teste por correção, com o caso real ──────────
_REAIS = r"""
// a Coração 1 e 2 (usina 77, THPN-COR100) está VAZIA no Nexus; a aba tem "Coração 1 (111)" e "Coração 2 (112)" (os
// inversores da Coração 2 se chamam "Inversor 1.x" na aba e são os COR100-INVR2.x do Fracttal, 250 kWp e 20 strings cada)
F.arvores['THOPEN-COR100'] = arv('THOPEN-COR100', 'Thopen - Coração 1 e 2 - SC', [['COR100-CABN1', N('COR100', 1, 12).concat(N('COR100', 2, 4))]], {usina_id: 77});
// a Sapopema (125, THPN-SPM100): 20 inversores no Nexus sem strings corretas, 159,8 kWp cada (3.196 no Registro)
F.arvores['THPN-SPM100'] = arv('THPN-SPM100', 'Thopen - Sapopema - PR', [['THPN-SPM100-CABN1', N('THPN-SPM100', 1, 20)]], {usina_id: 125});
// a Assis Chateaubriand (212, THPN-ACB100): 6 chaves no Nexus, a da Skid 1 com espaço ÚNICO; a aba e a API escrevem duplo
F.arvores['THPN-ACB100'] = arv('THPN-ACB100', 'Thopen - Assis Chateaubriand - PR', [['THPN-ACB100-CABN1', N('THPN-ACB100', 1, 4)]], {usina_id: 212});
['THOPEN-COR100', 'THPN-SPM100', 'THPN-ACB100'].forEach(c => { const a = F.arvores[c]; F.ufs.push({codigo: a.codigo, nome: a.nome, cliente: 'Thopen', usina_id: a.usina_id, cabines: a.cabines.map(x => ({codigo: x.codigo, nome: x.nome})), fonte: 'foto'}); });
F.registro.push({usina_id: 77, codigo: 'THPN-COR100', nome: 'Coração 1 e 2', status: 'OPERAÇÃO', kwp: 3250, kwp_de: 'real', cliente: 'Thopen'},
  {usina_id: 125, codigo: 'THPN-SPM100', nome: 'Sapopema', status: 'OPERAÇÃO', kwp: 3196, kwp_de: 'real', cliente: 'Thopen'},
  {usina_id: 212, codigo: 'THPN-ACB100', nome: 'Assis Chateaubriand', status: 'OPERAÇÃO', kwp: 6296, kwp_de: 'contratual', cliente: 'Thopen'});
F.nexus[77] = {usina_id: 77, nome: 'Coração 1 e 2', codigo: 'THPN-COR100', selo: 'selo-77', kwp: 3250, kwp_de: 'real', chaves: [], cabines: [], inversores: []};
F.nexus[125] = {usina_id: 125, nome: 'Sapopema', codigo: 'THPN-SPM100', selo: 'selo-125', kwp: 3196, kwp_de: 'real',
  chaves: [{supervisorio_id: 230, usina_supervisorio: 'Sapopema (39)', principal: true, substitui_aba: false}],
  cabines: [{cabine_id: 300, nome: 'UG 01', codigo_fracttal: null, potencia_kwp: 3196}],
  inversores: Array.from({length: 20}, (_, i) => nInv(3000 + i, 230, 'Sapopema (39)', 'Inversor 1.' + (i + 1), 'INVERSOR' + String(i + 1).padStart(2, '0'), 300, null, 159.8))};
const SKIDS = [[1, 79, [21, 21, 21, 21]], [2, 80, [21, 21, 21, 21]], [3, 81, [21, 21, 21, 21]], [4, 82, [21, 21, 21, 21]], [5, 2, [22, 21, 22, 20]]];
F.nexus[212] = {usina_id: 212, nome: 'Assis Chateaubriand', codigo: 'THPN-ACB100', selo: 'selo-212', kwp: 6296, kwp_de: 'contratual',
  chaves: [{supervisorio_id: 258, usina_supervisorio: 'Assis', principal: true, substitui_aba: false}].concat(SKIDS.map(([n, p]) => ({supervisorio_id: 258 + n, usina_supervisorio: `Assis Chateaubriand Skid ${n} (${p})`, principal: false, substitui_aba: false}))),
  cabines: SKIDS.map(([n]) => ({cabine_id: 400 + n, nome: 'UG 0' + n, codigo_fracttal: null, potencia_kwp: null})),
  inversores: SKIDS.flatMap(([n, p, ss]) => ss.map((s, m) => nInv(4000 + 10 * n + m, 258 + n, `Assis Chateaubriand Skid ${n} (${p})`, `Inversor ${n}.${m + 1}`, 'INVERSOR0' + (m + 1), 400 + n, s, s * 15.4)))};
F.cadastro.push(C('Coração 1 (111)', 'Coração 1', Array.from({length: 12}, (_, i) => ['INVERSOR' + String(i + 1).padStart(2, '0'), 'Inversor 1.' + (i + 1), 20, 251.94, 'UG 01'])),
  C('Coração 2 (112)', 'Coração 2', [1, 2, 3, 4].map(m => ['INVERSOR0' + m, 'Inversor 1.' + m, 20, 250, 'UG 01'])),
  C('Sapopema (39)', 'Sapopema', Array.from({length: 20}, (_, i) => ['INVERSOR' + String(i + 1).padStart(2, '0'), 'Inversor 1.' + (i + 1), null, 159.8, 'UG 01'])),
  C('Assis Chateaubriand  Skid 1 (79)', 'Assis', [1, 2, 3, 4].map(m => ['INVERSOR0' + m, 'Inversor 1.' + m, 21, 323.4, 'UG 01'])));
const inv_ = (pid, n, nome, ativas) => ({id: pid * 100 + n, nome_api: 'INVERSOR' + String(n).padStart(2, '0'), nome: nome || 'INVERSOR' + String(n).padStart(2, '0'), ativas, total: ativas, esp: null, sem_visao: false});
// a Coração 2 na `pv` (plant 18747863, sem ligação hoje): 3 dos 4 inversores mandaram leitura, o INVERSOR04 está parado
const CORACAO = {plant_id: 18747863, usina: 'Coração 2', depara_fonte: 'pv', qtd_inversores: 3, strings_ativas: 57, inv_resumo: [1, 2, 3].map(n => inv_(18747863, n, null, 19))};
// a Sapopema ligada à "Sapopema (39)", com 18 dos 20 lendo (16 strings com corrente). A planta é de mentira (125125): a
// Sapopema não está na `pv` de 20/10; o caso é o da usina 125 do Registro, o do achado
const SAPOPEMA = {plant_id: 125125, usina: 'Sapopema', depara_fonte: 'pv', chave_cadastro: 'Sapopema (39)', qtd_inversores: 18, strings_ativas: 288,
  inv_resumo: Array.from({length: 18}, (_, i) => inv_(125125, i + 1, 'Inversor 1.' + (i + 1), 16))};
// a Assis Skid 1 (plant 18747433) liga HOJE à chave da aba, com espaço duplo
const ASSIS = {plant_id: 18747433, usina: 'Assis Chateaubriand  Skid 1 (79)', depara_fonte: 'pv', chave_cadastro: 'Assis Chateaubriand  Skid 1 (79)', qtd_inversores: 4, strings_ativas: 84,
  inv_resumo: [1, 2, 3, 4].map(n => Object.assign(inv_(18747433, n, 'Inversor 1.' + n, 21), {esp: 21}))};
"""


def test_a_conta_do_kwp_desconta_o_de_antes_e_nunca_apaga_sem_registro(tmp_path):
    """D-d e D-c, a conta pura (a mesma do Nexus). Sapopema: 20 inversores, 2 sem strings corretas com 159,8 kWp de antes;
    os 159,8 × 2 saem do Registro (3.196) ANTES de dividir pelas 288 strings dos 18 (antes, a soma ia a 3.515,6, +10%). Se
    o de antes já soma o Registro, a usina é recusada. Sem potência no Registro, ninguém muda: fica o kWp de antes."""
    r = _node(_CTX + """
      const sap = R.contaKwp(3196, Array.from({length: 18}, (_, i) => ({id: 'a' + i, strings: 16, cab: 'c:300', k: 'a' + i}))
        .concat([{id: 'b1', strings: 0, kwpAntes: 159.8, cab: 'c:300', k: 'b1'}, {id: 'b2', strings: 0, kwpAntes: 159.8, cab: 'c:300'}]));
      const rec = R.contaKwp(3196, [{id: 'a', strings: 16, k: 'a'}, {id: 'b', strings: 0, kwpAntes: 1700}, {id: 'c', strings: 0, kwpAntes: 1700}]);
      const dc = R.contaKwp(null, [{id: 'a', strings: 19, k: 'a', kwpAntes: 324.52}, {id: 'n', strings: 19, k: 'n'}]);
      const r3 = v => Math.round(v * 1000) / 1000;
      return {sap: [r3(sap.fixo), r3(sap.por), r3(sap.inv.a0), sap.inv.b1, sap.antes.b1, r3(sap.cab['c:300'].kwp),
                    r3(Object.values(sap.inv).reduce((t, v) => t + v, 0) + 159.8)],
        rec: [rec.por, /já soma o kWp da usina no Registro mestre/.test(rec.erro)],
        dc: [dc.kwp, dc.inv.a, dc.antes.a, 'n' in dc.inv]};""", tmp_path)
    assert r["sap"] == [319.6, 9.988, 159.8, 159.8, True, 3196.0, 3196.0]     # a soma da usina é o Registro
    assert r["rec"] == [None, True]
    assert r["dc"] == [None, 324.52, True, False]                              # 0 ou vazio NUNCA por cima de dado


def test_sapopema_os_sem_leitura_ficam_de_fora_e_o_kwp_fecha_no_registro(tmp_path):
    """D-d e P-m na tela, com a Sapopema: os 2 inversores que não leram agora aparecem ("sem leitura agora") e começam de
    fora (sem strings no cadastro: o Nexus não mexe neles, ficam com 159,8); a conta dos 18 desconta os 319,6 e fecha em
    3.196. As strings dos 18 vieram da leitura de agora: pendência até o Conferido de cada linha (P-d). O pedido leva só os
    18. Com o kWp de antes dos dois passando do Registro, a usina não salva e diz por quê."""
    r = _node(_REAIS + """F.linhas = [SAPOPEMA];
      const inst = DT.criar({fonte: 'pv'}); await inst.entrar(F.linhas, 'pv');
      const g = inst.S.porPid['125125'], K = n => '125125|' + (12512500 + n), out = {};
      out.sl = g.invs.filter(i => i.sem_leitura).map(i => [i.nome_api, inst.S.sel['125125|' + i.id].fora]);
      out.pend = inst.pendencia(125125, 12512501);
      const c = inst.conta(125125);
      const dosLidos = Array.from({length: 18}, (_, i) => c.inv[K(i + 1)]).reduce((t, v) => t + v, 0);
      // os 2 de fora seguem na conta do Nexus com o kWp de antes (a linha mostra o que ele vai gravar: "fica o de antes")
      const sl = g.invs.filter(i => i.sem_leitura).map(i => [c.inv['125125|' + i.id], c.antes['125125|' + i.id]]);
      out.conta = [Math.round(c.fixo * 10) / 10, Math.round(c.inv[K(1)] * 1000) / 1000, Math.round((dosLidos + c.fixo) * 10) / 10, sl];
      out.faixa = inst.html().includes('(3.196,0 kWp − 319,6 kWp dos 2 sem strings corretas, que ficam com o kWp de antes) ÷ 288 strings corretas');
      out.semLeitura = (inst.html().match(/sem leitura agora: fica como está/g) || []).length;
      for (let n = 1; n <= 18; n++) inst.conferir(K(n), true);
      out.pronto = inst.pronto(125125);
      await inst.salvar();
      out.pedido = PEDIDOS.find(p => p.url.endsWith('/salvar')).body.itens[0].inversores.map(i => i.equipamento_supervisorio);
      inst.S.ctx.nexus[125].inversores[18].potencia_kwp = 1700; inst.S.ctx.nexus[125].inversores[19].potencia_kwp = 1700;
      inst.conferir(K(1), false); inst.conferir(K(1), true);
      out.recusa = [inst.pronto(125125), inst.S.resultado && 1, inst.html().includes('já soma o kWp da usina no Registro mestre')];
      return out;""", tmp_path)
    assert r["sl"] == [["INVERSOR19", True], ["INVERSOR20", True]]
    assert r["pend"] == "confira as strings: vieram da leitura de agora"
    assert r["conta"] == [319.6, 159.8, 3196.0, [[159.8, True], [159.8, True]]] and r["faixa"] and r["semLeitura"] == 2
    assert r["pronto"] is True and r["pedido"] == [f"INVERSOR{n:02d}" for n in range(1, 19)]
    assert r["recusa"][0] is False and r["recusa"][2] is True


def test_sem_potencia_no_registro_a_tela_diz_que_o_kwp_de_antes_fica(tmp_path):
    """D-c: sem real nem contratual (o Registro desta máquina do Nexus perdeu a potência), o Nexus não mexe no kWp; a tela
    mostra o de hoje com "fica o de antes", nunca um kWp em branco por cima."""
    r = _node("""F.nexus[93].kwp = null; F.nexus[93].kwp_de = null;
      const inst = DT.criar({fonte: 'pv'}); await inst.entrar(F.linhas, 'pv');
      const h = inst.html();
      return {faixa: h.includes('o Nexus não mexe no kWp desta usina'), linha: h.includes('324,5 kWp<small>fica o de antes: sem kWp no Registro'),
        branco: h.includes('o kWp dos inversores fica em branco')};""", tmp_path)
    assert r == {"faixa": True, "linha": True, "branco": False}


def test_coracao_2_a_chave_da_aba_o_parado_e_o_nome_do_cadastro(tmp_path):
    """P-j, P-m, P-i e a conta da chave que o Nexus vai semear da aba (D-a), com a Coração 2 (sem ligação hoje, usina 77 vazia
    no Nexus): a tela oferece a "Coração 2 (112)" da aba (antes, só "Nova chave", uma chave paralela à da aba), o INVERSOR04
    parado vira linha "sem leitura agora" com as strings da aba e o COR100-INVR2.4, o pedido leva o nome do cadastro
    ("Inversor 1.1", e não o "Inversor 2.1" do código: a chave do BD não muda) e a conta é a que o Nexus fará depois de
    semear a chave: 3.250 (o Registro, que é só a Coração 1: D-h) ÷ 80 strings = 812,5, com "250,0 →" na linha."""
    r = _node(_REAIS + """F.linhas = [CORACAO];
      const inst = DT.criar({fonte: 'pv'}); await inst.entrar(F.linhas, 'pv');
      const out = {}, P = '18747863';
      out.opcoes = (inst.html().match(/<option value="[^"]*"[^>]*>[^<]*<\\/option>/g) || []).filter(o => /Cora/.test(o)).map(o => o.replace(/<[^>]+>/g, ''));
      inst.mudarChave(P, 'Coração 2 (112)');
      const g = inst.S.porPid[P];
      out.invs = g.invs.map(i => { const s = inst.S.sel[P + '|' + i.id]; return [i.nome_api, !!i.sem_leitura, s.ativo, s.strings, !!s.fora]; });
      const c = inst.conta(18747863);
      out.kwp = Object.values(c.inv).map(v => Math.round(v * 10) / 10);
      out.cab = Object.values(c.cab).map(x => Math.round(x.kwp * 10) / 10);
      const h = inst.html();
      out.tela = [h.includes('250,0 →'), h.includes('sem leitura agora')];
      inst.conferirTodos(); await inst.salvar();
      const it = PEDIDOS.find(p => p.url.endsWith('/salvar')).body.itens[0];
      out.item = [it.usina_supervisorio, it.usina_id, it.inversores.map(i => [i.equipamento_supervisorio, i.nome, i.strings, i.codigo_fracttal])];
      out.ponte = PEDIDOS.filter(p => p.url.includes('decidir')).map(p => p.body);
      return out;""", tmp_path)
    assert "Coração 2 (112) (da aba Equipamentos: o Nexus a traz da aba ao salvar)" in r["opcoes"]
    assert not any("Coração 1 (111)" in o for o in r["opcoes"])                 # outro número de planta
    assert r["invs"] == [["INVERSOR01", False, "COR100-INVR2.1", 20, False], ["INVERSOR02", False, "COR100-INVR2.2", 20, False],
                         ["INVERSOR03", False, "COR100-INVR2.3", 20, False], ["INVERSOR04", True, "COR100-INVR2.4", 20, False]]
    assert r["kwp"] == [812.5] * 4 and r["cab"] == [3250.0] and r["tela"] == [True, True]
    assert r["item"] == ["Coração 2 (112)", 77, [[f"INVERSOR0{m}", f"Inversor 1.{m}", 20, f"COR100-INVR2.{m}"] for m in (1, 2, 3, 4)]]
    assert r["ponte"] == [{"fonte": "pv", "id": "18747863", "usina_supervisorio": "Coração 2 (112)"}]


_CORACAO1 = """const CORACAO1 = {plant_id: 18747862, usina: 'Coração 1', depara_fonte: 'pv', qtd_inversores: 12, strings_ativas: 240,
  inv_resumo: Array.from({length: 12}, (_, i) => Object.assign(inv_(18747862, i + 1, null, 20), {esp: 20}))};
"""


def test_a_irma_sem_chave_escolhida_tambem_segura_a_usina(tmp_path):
    """Revisão do acerto final (21/10/2026), dado real da `pv`: as duas Coração chegam sem chave (sem ligação hoje e a usina
    77 vazia no Nexus). Escolhida só a "Coração 2 (112)", ela ia sozinha e o Nexus gravava 3.250 ÷ 80 = 812,5 kWp por
    inversor. A Coração 1, sem chave escolhida mas com a "Coração 1 (111)" da aba entre as opções, segura a usina."""
    r = _node(_REAIS + _CORACAO1 + """F.linhas = [CORACAO1, CORACAO];
      const inst = DT.criar({fonte: 'pv'}); await inst.entrar(F.linhas, 'pv');
      const A = '18747862', B = '18747863', out = {};
      out.chave = [inst.S.gsel[A].chave, inst.S.gsel[B].chave];
      inst.mudarChave(B, 'Coração 2 (112)'); inst.conferirTodos();
      out.pronto = [inst.pronto(A), inst.pronto(B)];
      out.tela = inst.html().includes('Coração 1 também é desta usina do Registro e a chave dela ainda não está no Nexus');
      await inst.salvar();
      out.salvar = PEDIDOS.filter(p => p.url.endsWith('/salvar')).length;
      return out;""", tmp_path)
    assert r["chave"] == ["", ""]
    assert r["pronto"] == [False, False] and r["tela"] and r["salvar"] == 0


def test_usina_com_pendencia_nao_grava_ponte_derivada(tmp_path):
    """Revisão do acerto final (21/10/2026): com a "Coração 1 (111)" gravada e conferida no Nexus (usina 77), a Coração 2 sem
    ligação recebe a sugestão dessa chave e os INVERSOR01..03 dela casam pelo nome com os da Coração 1: a ponte "derivava"
    mesmo com a pendência vermelha "a chave também está em Coração 1", e um Salvar só da Pharma II mandava junto o decidir
    Coração 2 → "Coração 1 (111)" (a planta passava a ler o cadastro da outra). Com pendência, nenhuma ponte."""
    r = _node(_REAIS + _CORACAO1 + """const u = F.nexus[77];
      u.chaves.push({supervisorio_id: 900, usina_supervisorio: 'Coração 1 (111)', principal: true, substitui_aba: false});
      for (let n = 1; n <= 12; n++) u.inversores.push(Object.assign(nInv(9000 + n, 900, 'Coração 1 (111)', 'Inversor 1.' + n,
        'INVERSOR' + String(n).padStart(2, '0'), null, 20, 0), {codigo_fracttal: 'COR100-INVR1.' + n, fracttal_ligado_por: 'conferido',
        conferido_em: '2026-10-21T12:00:00Z'}));
      const C1 = Object.assign({}, CORACAO1, {chave_cadastro: 'Coração 1 (111)'});
      const PH = F.linhas.find(l => l.usina === 'Pharma II');
      const inst = DT.criar({fonte: 'pv'}); await inst.entrar([C1, CORACAO, PH], 'pv');
      const B = '18747863', P = '18758592', out = {};
      out.chave = inst.S.gsel[B].chave;
      out.ponte = inst.pontePendente(B);
      inst.S.porPid[P].invs.forEach(i => inst.conferir(P + '|' + i.id, true));
      await inst.salvar();
      out.decidir = PEDIDOS.filter(p => p.url.includes('decidir')).map(p => String(p.body.id));
      return out;""", tmp_path)
    assert r["chave"] == "Coração 1 (111)"                     # a sugestão continua (a pendência diz o que fazer)
    assert r["ponte"] is False and "18747863" not in r["decidir"]


def test_a_fonte_que_manda_o_nome_do_cadastro_casa_com_o_inversor_da_aba(tmp_path):
    """A Pharma II manda "Inversor 1.1".."1.6"; a aba e o Nexus têm a "Pharma 2" com INVERSOR01..06 chamados "Inversor 1.1"..
    (o banco de 20/10). Só pelo Equipamento Supervisório a tela não reconhecia: contava os 6 duas vezes no kWp (12 membros,
    164 strings) e punha os 6 de novo como "sem leitura agora" (medido na `pv`). Pelo nome do cadastro, são os do Nexus, e
    o pedido vai com o supervisório dele."""
    r = _node("""F.nexus[108].inversores.forEach((i, n) => { i.equipamento_supervisorio = 'INVERSOR0' + (n + 1); });
      F.cadastro[2].inversores.forEach((i, n) => { i.esup = 'INVERSOR0' + (n + 1); });
      const inst = DT.criar({fonte: 'pv'}); await inst.entrar(F.linhas, 'pv');
      const g = inst.S.porPid['18758592'], c = inst.conta(18758592);
      [378064, 378065, 378066, 378067, 378068, 378069].forEach(id => inst.conferir('18758592|' + id, true));
      await inst.salvar();
      const it = PEDIDOS.filter(p => p.url.endsWith('/salvar')).flatMap(p => p.body.itens).find(i => i.usina_supervisorio === 'Pharma 2');
      return {sl: g.invs.filter(i => i.sem_leitura).length, n: c.n, total: c.total, um: Math.round(c.inv['18758592|378064'] * 1000) / 1000,
        esup: it.inversores.map(i => [i.equipamento_supervisorio, i.nome])};""", tmp_path)
    assert r["sl"] == 0 and r["n"] == 6 and r["total"] == 82 and r["um"] == 169.024
    assert r["esup"] == [[f"INVERSOR0{n}", f"Inversor 1.{n}"] for n in range(1, 7)]


def test_assis_skid_1_com_espaco_duplo_e_uma_chave_so(tmp_path):
    """D-g na tela: a Assis Skid 1 liga hoje à "Assis Chateaubriand  Skid 1 (79)" (espaço duplo, a da aba e da API) e o Nexus a
    tem com espaço único. A tela casa pela forma normalizada: os 4 inversores são os do Nexus (a conta tem as 421 strings
    da usina, não 505; 6.296 contratual ÷ 421 × 21 = 314,05), a lista tem a chave uma vez só, o pedido vai com a grafia do
    Nexus e a ponte não é gravada (a fonte já liga a ela)."""
    r = _node(_REAIS + """F.linhas = [ASSIS];
      const inst = DT.criar({fonte: 'pv'}); await inst.entrar(F.linhas, 'pv');
      const c = inst.conta(18747433), h = inst.html(), out = {};
      out.conta = [c.total, Math.round(c.inv['18747433|1874743301'] * 100) / 100, c.kwp_de];
      out.opcoes = (h.match(/<option value="Assis Chateaubriand\\s+Skid 1 \\(79\\)"/g) || []).length;
      [1, 2, 3, 4].forEach(n => inst.conferir('18747433|' + (1874743300 + n), true));
      await inst.salvar();
      out.item = PEDIDOS.find(p => p.url.endsWith('/salvar')).body.itens.map(i => i.usina_supervisorio);
      out.ponte = PEDIDOS.filter(p => p.url.includes('decidir')).length;
      out.res = inst.S.resultado.nexus.map(x => [x.ok, x.ponte]);
      return out;""", tmp_path)
    assert r["conta"] == [421, 314.05, "contratual"] and r["opcoes"] == 1
    assert r["item"] == ["Assis Chateaubriand Skid 1 (79)"] and r["ponte"] == 0 and r["res"] == [[True, "já ligava"]]


def test_a_usina_que_o_nexus_recusa_sai_do_lote_e_o_resto_vai_de_novo(tmp_path):
    """D-f: o Nexus recusa o pedido INTEIRO (até 50 chaves); a recusa que é de uma usina traz o usina_id dela. A tela tira
    essa usina e manda o resto de novo (até 3 vezes), e diz qual recusou e por quê. Itajá e Coração no mesmo lote."""
    r = _node(_REAIS + """F.linhas.push(CORACAO);
      const inst = DT.criar({fonte: 'pv'}); await inst.entrar(F.linhas, 'pv');
      inst.mudarChave('18747863', 'Coração 2 (112)');
      inst.conferirTodos();
      DUBLE.salvar = body => body.itens.some(it => it.usina_id === 77)
        ? resp(409, {ok: false, motivo: 'O código COR100-INVR2.1 já está no inversor “Inversor 2.1” (usina 77): um código do Fracttal fica num inversor vivo só. Nada foi gravado.', usina_id: 77, usina_supervisorio: 'Coração 2 (112)'})
        : resp(200, {ok: true, usinas: body.itens.map(it => F.nexus[it.usina_id]), kwp: {}, avisos: [], mudancas: 4});
      await inst.salvar();
      return {posts: PEDIDOS.filter(p => p.url.endsWith('/salvar')).map(p => p.body.itens.map(i => i.usina_id)),
        res: inst.S.resultado.nexus.map(x => [x.g.usina, x.ok, !!x.culpada, x.ponte || null]),
        ponte: PEDIDOS.filter(p => p.url.includes('decidir')).map(p => p.body.id)};""", tmp_path)
    assert r["posts"] == [[93, 93, 108, 77], [93, 93, 108]]                  # a Coração sai, o resto vai de novo
    assert sorted(r["res"]) == [["Coração 2", False, True, None], ["Itaja 1 (228)", True, False, "ok"],
                                ["Itaja 2 (229)", True, False, "ok"], ["Pharma II", True, False, "já ligava"]]
    assert sorted(r["ponte"]) == ["18749574", "18749576"]                     # a recusada não tenta a ponte


def test_o_gestor_admin_do_nexus_ve_a_tabela_so_de_leitura(tmp_path):
    """P-a: o /api/eu diz que abre e não grava (o gestor que é admin do Nexus). A tabela abre com o motivo, e o Salvar não
    vai a lugar nenhum (antes, o Nexus gravava e a ponte levava 403: gravação pela metade)."""
    r = _node("""F.eu = {abre_admin: true, grava_admin: false};
      const inst = DT.criar({fonte: 'pv'}); await inst.entrar(F.linhas, 'pv');
      inst.conferirTodos(); const n = PEDIDOS.length; await inst.salvar();
      return {html: inst.html().includes('Só leitura: o seu perfil na Performance é de gestor'), pronto: inst.pronto(18749574),
        posts: PEDIDOS.slice(n).filter(p => p.method === 'POST').length};""", tmp_path)
    assert r == {"html": True, "pronto": True, "posts": 0}


def test_a_ponte_que_falhou_vai_sozinha_no_salvar_seguinte(tmp_path):
    """P-b: o Nexus gravou e a ponte falhou (503 sem GRIDCO_SQL_TOKEN). A usina não vira a base com a chave nova: fica "ponte
    pendente", e o Salvar seguinte manda SÓ o decidir, sem ir ao Nexus de novo (antes, zero pedidos e o "salve de novo"
    não tinha como valer)."""
    r = _node(_ENTRA + """DUBLE.decidir = () => resp(503, {error: 'sem GRIDCO_SQL_TOKEN nesta máquina'});
      ['365249', '365250', '365247', '365251'].forEach(id => inst.conferir('18749574|' + id, true));
      await inst.salvar();
      const out = {pend1: inst.pontePendente(18749574), barra: inst.html().includes('ponte pendente')};
      DUBLE.decidir = () => resp(200, {ok: true, gravadas: 1, total: 22});
      const antes = PEDIDOS.length; await inst.salvar();
      out.depois = PEDIDOS.slice(antes).map(p => p.url.split('?')[0]);
      out.pend2 = inst.pontePendente(18749574);
      out.res = inst.S.resultado.ponte.map(x => [x.g.usina, x.ok, x.chave]);
      out.chave = inst.S.porPid['18749574'].chave_cadastro;
      return out;""", tmp_path)
    assert r["pend1"] is True and r["barra"] is True
    assert r["depois"] == ["/api/admin/de-para/decidir"] and r["pend2"] is False
    assert r["res"] == [["Itaja 1 (228)", True, "Itaja 1 (551)"]] and r["chave"] == "Itaja 1 (551)"


def test_o_kwp_da_conta_e_o_do_nexus_e_a_divergencia_e_dita(tmp_path):
    """P-c: o Nexus calcula com o Registro DELE. Itajá com 2.700 kWp no Nexus e 2.596 na cópia da plataforma: a tela mostra
    337,5 (o que o Nexus grava), não 324,5 "igual ao de hoje", e a faixa diz que as duas cópias diferem."""
    r = _node("""F.nexus[93].kwp = 2700;
      const inst = DT.criar({fonte: 'pv'}); await inst.entrar(F.linhas, 'pv');
      const c = inst.conta(18749574), h = inst.html();
      return {kwp: c.kwp, um: Math.round(c.inv['18749574|365249'] * 10) / 10, dito: h.includes('a cópia do Registro desta tela diz 2.596,0 kWp; o Nexus grava com 2.700,0 kWp: vale o do Nexus')};""", tmp_path)
    assert r == {"kwp": 2700, "um": 337.5, "dito": True}


def test_strings_da_leitura_de_agora_pedem_o_conferido_da_linha(tmp_path):
    """P-d: sem strings no Nexus nem no cadastro, a sugestão vem das strings com corrente agora (a Pharma 3 tem 19) e fica
    pendência "confira as strings" até o Conferido DA LINHA: o "conferir todos" não as confere (uma string parada na hora
    viraria "não esperada" para sempre). Digitar as strings também resolve."""
    r = _node(_ENTRA + """const P = '18751504|';
      const out = {antes: inst.pendencia(18751504, 368373), dica: inst.html().includes('da leitura de agora')};
      inst.conferirTodos();
      out.todos = inst.pendencia(18751504, 368373);
      inst.conferir(P + '368373', true);
      out.conferido = inst.pendencia(18751504, 368373);
      await inst.mudar(P + '368374', 'j-str', '14');
      out.digitado = [inst.pendencia(18751504, 368374), inst.S.sel[P + '368374'].strDe];
      return out;""", tmp_path)
    assert r["antes"] == r["todos"] == "confira as strings: vieram da leitura de agora" and r["dica"]
    assert r["conferido"] == "" and r["digitado"] == ["", "tela"]


def test_o_codigo_que_o_nexus_tem_numa_usina_que_nao_vai_e_pendencia(tmp_path):
    """P-e (a prova da revisão): o Nexus tem o ITA100-INVR1.1 no INVERSOR01 da Itaja 1 (551). Na tela, a Itaja 1 perde o
    inversor (fica com pendência e NÃO vai no Salvar) e a Itaja 2 pega o INVR1.1. Antes, o código era isento por estar
    "na tela", a Itaja 2 ia e o Nexus recusava o lote inteiro com 409. Agora a Itaja 2 diz onde o código está; com a Itaja 1
    acertada (a troca entre as duas no MESMO Salvar), passa."""
    r = _node("""F.nexus[93].inversores[0].codigo_fracttal = 'ITA100-INVR1.1';
      const inst = DT.criar({fonte: 'pv'}); await inst.entrar(F.linhas, 'pv');
      const A = '18749574|365249', B = '18749576|365252', out = {};
      await inst.mudar(A, 'j-cab', 'ITA100-CABN2');                      // a Itaja 1 sem inversor: fica fora do Salvar
      await inst.mudar(B, 'j-cab', 'ITA100-CABN1'); await inst.mudar(B, 'j-at', 'ITA100-INVR1.1');
      ['365252', '365254', '365253', '365255'].forEach(id => inst.conferir('18749576|' + id, true));
      out.antes = [inst.pendencia(18749574, 365249), inst.pendencia(18749576, 365252), inst.pronto(18749576)];
      await inst.mudar(A, 'j-at', 'ITA100-INVR2.1');
      ['365249', '365250', '365247', '365251'].forEach(id => inst.conferir('18749574|' + id, true));
      out.depois = [inst.pendencia(18749576, 365252), inst.pronto(18749574), inst.pronto(18749576)];
      return out;""", tmp_path)
    assert r["antes"] == ["falta o inversor", "já está no Inversor 1.1 (Itaja 1 (551)) no Nexus", False]
    assert r["depois"] == ["", True, True]


def test_sem_resposta_do_nexus_a_tela_rele_pelo_selo_e_espera_o_nexus_terminar(tmp_path):
    """P-f e a 2ª revisão final (21/10): a rede caiu na volta (ou o estouro de 180 s). O pedido abandonado continua no
    Nexus, e o estado relido na hora devolvia o selo de antes: a tela dizia "está como antes: salve de novo", guardava o
    selo velho, o Nexus gravava segundos depois e o 2º Salvar levava 409 sem a ponte. Agora ela relê esperando: o selo que
    mudou quer dizer que o Nexus gravou (segue para a ponte); o selo igual só é "como antes" com o Nexus dizendo que não há
    gravação em curso (`gravando: false`); com ele gravando (ou sem dizer) até o prazo, "não se sabe se o Nexus gravou", e
    a base da usina não troca pelo selo relido. A releitura que também falha: "não se sabe"."""
    r = _node("""const roda = async (estados) => {
        const inst = DT.criar({fonte: 'pv', esperaSelo: 5, prazoSelo: 60}); await inst.entrar(F.linhas, 'pv');
        ['365249', '365250', '365247', '365251'].forEach(id => inst.conferir('18749574|' + id, true));
        let n_ = 0;
        DUBLE.salvar = () => 'rede'; DUBLE.estado = url => estados[Math.min(n_++, estados.length - 1)](url);
        const n = PEDIDOS.length; await inst.salvar(); DUBLE.estado = null; DUBLE.salvar = null;
        const x = inst.S.resultado.nexus[0];
        return [x.ok, !!x.tarde, !!x.semSaber, x.ponte || null, String(x.motivo || ''), PEDIDOS.slice(n).filter(p => p.url.includes('decidir')).length,
          inst.S.ctx.nexus[93].selo, n_, inst.pronto(18749574)];
      };
      const est = (selo, gravando) => () => resp(200, Object.assign({ok: true, usinas: [Object.assign({}, F.nexus[93], {selo})], chaves_sem_usina: []},
        gravando === undefined ? {} : {gravando}));
      const fora = () => resp(503, {ok: false, motivo: 'Não consegui ler a estrutura no banco (ConnectionError).'});
      return {gravou: await roda([est('selo-93-depois', false)]),
        // o caso da revisão: relido no meio da gravação (selo velho, gravando), e depois o selo novo
        noMeio: await roda([est('selo-93', true), est('selo-93', true), est('selo-93-gravado', false)]),
        igual: await roda([est('selo-93', false)]),
        semDizer: await roda([est('selo-93')]), gravandoSempre: await roda([est('selo-93', true)]),
        fora: await roda([fora])};""", tmp_path)
    assert r["gravou"][:4] == [True, True, False, "ok"] and r["gravou"][5] == 1
    assert r["noMeio"][:4] == [True, True, False, "ok"] and r["noMeio"][5] == 1 and r["noMeio"][6:8] == ["selo-93-gravado", 3]
    assert r["igual"][0] is False and "está como antes: salve de novo" in r["igual"][4] and r["igual"][5] == 0
    for caso in ("semDizer", "gravandoSempre"):          # até o prazo sem saber: nada de "como antes", nada de ponte
        x = r[caso]
        assert x[0] is False and x[2] is True and "recarregue a tela daqui a alguns minutos" in x[4] and x[5] == 0, caso
        assert x[7] > 1 and x[8] is True                 # releu mais de uma vez; a usina segue pendente para salvar
    assert r["fora"][0] is False and r["fora"][2] is True and "a releitura da usina também falhou" in r["fora"][4]


def test_a_ponte_so_e_pulada_sem_nome_api(tmp_path):
    """P-g: com `nome_api`, a ponte por id já renomeou a planta (o nome por dentro é o alvo dela, que saiu do cadastro).
    Escolhida a chave com o nome que a API escreve (a chave existe na aba), a ponte vai VAZIA ("sem ponte": vale o nome da
    API, que é a chave), e não é pulada como "já ligava" (a planta seguiria procurando o alvo velho). Sem `nome_api`, a
    mesma escolha não precisa de ponte: a fonte já se chama assim. (A "Nova chave", o nome da fonte fora da aba, saiu da
    lista na 2ª revisão final de 21/10: o Nexus a recusa.)"""
    r = _node("""F.linhas[1] = Object.assign({}, F.linhas[1], {usina: 'Itaja II antiga', nome_api: 'Itaja 2 (229)'});
      F.cadastro.push(C('Itaja 2 (229)', 'Itajá', [1, 2, 3, 4].map(m => ['INVERSOR0' + m, 'Inversor 2.' + m, 19, 324.52, 'UG 02'])));
      const roda = async () => {
        const inst = DT.criar({fonte: 'pv'}); await inst.entrar(F.linhas, 'pv');
        inst.mudarChave('18749576', 'Itaja 2 (229)');
        ['365252', '365254', '365253', '365255'].forEach(id => inst.conferir('18749576|' + id, true));
        const n = PEDIDOS.length; await inst.salvar();
        return [PEDIDOS.slice(n).filter(p => p.url.includes('decidir')).map(p => p.body.usina_supervisorio), inst.S.resultado.nexus.find(x => x.g.pid === '18749576').ponte];
      };
      const com = await roda();
      F.linhas[1] = Object.assign({}, F.linhas[1], {usina: 'Itaja 2 (229)', nome_api: ''});
      return {com, sem: await roda()};""", tmp_path)
    assert r["com"] == [[""], "ok"] and r["sem"] == [[], "já ligava"]


def test_os_avisos_do_nexus_aparecem_na_usina_com_o_nao_vale_no_lugar_da_aba(tmp_path):
    """P-k: o aviso que cita a chave vai com a usina da fonte dela; o da usina (o nome do Registro) com a 1ª usina dela no
    pedido; o resto no fim. "Não vale no lugar da aba porque…" em destaque, na barra e no cabeçalho da usina."""
    r = _node(_ENTRA + """DUBLE.salvar = body => resp(200, {ok: true, usinas: body.itens.map(it => F.nexus[it.usina_id]), kwp: {}, mudancas: 8,
        avisos: ['A chave “Itaja 1 (551)” não vale no lugar da aba porque: Full O&M (a aba diz Sim, o Nexus Não)',
                 'Itajá 1 e 2: 2 inversor(es) sem strings corretas ficaram fora da conta, com o kWp de antes.', 'um aviso de outra coisa']});
      ['365249', '365250', '365247', '365251', ].forEach(id => inst.conferir('18749574|' + id, true));
      ['365252', '365254', '365253', '365255'].forEach(id => inst.conferir('18749576|' + id, true));
      await inst.salvar();
      const por = Object.fromEntries(inst.S.resultado.nexus.map(x => [x.g.usina, x.avisos]));
      return {por, soltos: inst.S.resultado.avisos, cab: inst.html().includes('<span class="dp-gp red">Nexus: A chave “Itaja 1 (551)” não vale no lugar da aba')};""", tmp_path)
    assert r["por"]["Itaja 1 (228)"] == ["A chave “Itaja 1 (551)” não vale no lugar da aba porque: Full O&M (a aba diz Sim, o Nexus Não)",
                                         "Itajá 1 e 2: 2 inversor(es) sem strings corretas ficaram fora da conta, com o kWp de antes."]
    assert r["por"]["Itaja 2 (229)"] == [] and r["soltos"] == ["um aviso de outra coisa"] and r["cab"]
    js = COMP.read_text(encoding="utf-8")
    assert '<b class="red">não vale no lugar da aba:</b>' in js                 # o destaque no resultado da barra


def test_os_avisos_no_formato_do_nexus_vao_pela_usina_e_pela_chave(tmp_path):
    """O Nexus manda cada aviso como {usina_id, usina_supervisorio, tipo, texto} (TIPOS_AVISO dele): o da chave vai com a
    usina da fonte dela, o da usina inteira (sem chave) com a 1ª dela no pedido; o `tipo` "nao_marcada" é destacado como
    "não vale no lugar da aba" mesmo com outra redação."""
    r = _node(_ENTRA + """DUBLE.salvar = body => resp(200, {ok: true, usinas: body.itens.map(it => F.nexus[it.usina_id]), kwp: {}, mudancas: 8, avisos: [
        {usina_id: 93, usina_supervisorio: 'Itaja 2 (552)', tipo: 'nao_marcada', texto: 'A chave “Itaja 2 (552)” segue com a aba: String Box'},
        {usina_id: 93, usina_supervisorio: '', tipo: 'sem_strings', texto: 'Itajá 1 e 2: 1 inversor(es) sem strings corretas ficaram com o kWp de antes'}]});
      ['365249', '365250', '365247', '365251'].forEach(id => inst.conferir('18749574|' + id, true));
      ['365252', '365254', '365253', '365255'].forEach(id => inst.conferir('18749576|' + id, true));
      await inst.salvar();
      return Object.fromEntries(inst.S.resultado.nexus.map(x => [x.g.usina, x.avisos]));""", tmp_path)
    assert r["Itaja 2 (229)"] == ["não vale no lugar da aba: A chave “Itaja 2 (552)” segue com a aba: String Box"]
    assert r["Itaja 1 (228)"] == ["Itajá 1 e 2: 1 inversor(es) sem strings corretas ficaram com o kWp de antes"]


def test_a_resposta_do_nexus_que_nao_e_json_e_dita_com_todas_as_letras(tmp_path):
    """P-l: o `_tela` do Nexus devolve 403 em HTML para quem não é admin e HTML com status 200 sem a chave do cadastro. A tela
    dizia "HTTP 200 sem JSON"; agora diz quem respondeu, o quê (a página e o título) e o que isso quer dizer."""
    r = _node("""const pagina = t => '<!doctype html><html><head><title>' + t + '</title></head><body><h1>' + t + '</h1></body></html>';
      DUBLE.estado = () => resp(200, pagina('Nexus · Entrar'));
      const inst = DT.criar({fonte: 'pv'}); await inst.entrar(F.linhas, 'pv');
      const out = {estado: inst.S.ctx.nexusErro};
      DUBLE.estado = null;
      const inst2 = DT.criar({fonte: 'pv'}); await inst2.entrar(F.linhas, 'pv');
      ['365249', '365250', '365247', '365251'].forEach(id => inst2.conferir('18749574|' + id, true));
      DUBLE.salvar = () => resp(403, pagina('Só administradores'));
      await inst2.salvar();
      out.salvar = inst2.S.resultado.nexus[0].motivo;
      return out;""", tmp_path)
    assert r["estado"].startswith("o Nexus respondeu uma página (“Nexus · Entrar”) em vez dos dados (HTTP 200): a rota não chegou a responder")
    assert r["salvar"] == "o Nexus respondeu uma página (“Só administradores”) em vez dos dados (HTTP 403): sem permissão (só administradores do Nexus)"


# ── o acerto final (2ª revisão, 21/10/2026): um teste por achado, com o caso real ───────────────────────────────────
# o Nexus de verdade grava os códigos e o Conferido e devolve o estado novo (o selo muda); o `estado` dublado lê o mesmo F
_NEXUS_GRAVA = r"""
DUBLE.salvar = body => { body.itens.forEach(it => { const u = F.nexus[it.usina_id];
    it.inversores.forEach(i => { const x = u.inversores.find(v => v.usina_supervisorio === it.usina_supervisorio && v.equipamento_supervisorio === i.equipamento_supervisorio);
      if (x) Object.assign(x, {codigo_fracttal: i.codigo_fracttal, strings_esperadas_qtd: i.strings, conferido_em: i.conferido ? '2026-10-21T12:00:00Z' : null,
        fracttal_ligado_por: i.conferido ? 'conferido' : 'sugestao'}); });
    u.selo = 'selo-novo-' + it.usina_id; });
  return resp(200, {ok: true, usinas: body.itens.map(it => F.nexus[it.usina_id]), kwp: {}, visao_mudou: true, erros: [], avisos: [], mudancas: 4,
    marcacao: body.itens.map(it => ({usina_id: it.usina_id, usina_supervisorio: it.usina_supervisorio, principal: false, marcada: true, fora_da_regra: []}))}); };
"""


def test_a_nova_chave_saiu_da_lista_e_a_chave_fora_da_aba_e_do_nexus_e_pendencia(tmp_path):
    """Contrato-1/regressão (2ª revisão final): a tela oferecia "Nova chave: 'Pharma 3 (851)'" (o nome da fonte, fora da
    aba) ao lado da "Pharma 3" da aba. Com o D-b ela nunca vale no lugar da aba; o Nexus a gravava como a chave da usina e
    prendia os códigos nos inversores dela, e trocada depois para a "Pharma 3" as 6 linhas ficavam com "já está no Inversor
    1.m (Pharma 3 (851)) no Nexus". A opção saiu (o Nexus também recusa); a planta sem chave nenhuma diz o que fazer, e a
    chave que não está na aba nem no Nexus é pendência com o porquê."""
    r = _node("""const inst = DT.criar({fonte: 'pv'}); await inst.entrar(F.linhas, 'pv');
      const h = inst.html(), P = '18751504', out = {};
      out.nova = /Nova chave/.test(h);
      out.opcoes = (h.match(/<select class="cel j-chave[^"]*" data-g="18751504"[\\s\\S]*?<\\/select>/) || [''])[0].replace(/<[^>]+>/g, '|').split('|').filter(x => x.trim());
      out.pend = inst.S.porPid[P] && inst.html().includes('esta planta não tem chave na aba Equipamentos nem no Nexus');
      inst.mudarChave(P, 'Pharma 3 (851)');
      inst.S.porPid[P].invs.forEach(i => inst.conferir(P + '|' + i.id, true));
      out.fora = [inst.pronto(P), inst.html().includes('a chave “Pharma 3 (851)” não está na aba Equipamentos nem no Nexus: o Nexus recusa')];
      return out;""", tmp_path)
    assert r["nova"] is False and r["opcoes"] == ["Escolha a chave"] and r["pend"]
    assert r["fora"] == [False, True]


def test_a_ponte_pendente_volta_ao_reabrir_e_o_salvar_manda_so_a_ponte(tmp_path):
    """Contrato-2 (P-b, 2ª revisão final): a ponte que falhou depois de o Nexus gravar ficava SÓ na memória da instância. O
    Tempo real cria uma a cada "Modo de-para" e o confirm de sair contava só as mexidas (0 depois do Salvar): reaberta, a
    Itaja 1 (228) aparecia "ligada e conferida", com "sugestão: a ponte grava ao salvar", e o Salvar desligado. Agora a
    ponte pendente vem do estado (a chave escolhida não é a de hoje e o Nexus já a tem nesta usina com os inversores da
    fonte gravados e conferidos): reaberta, a usina está em "só ponte" e o Salvar manda só o decidir."""
    r = _node(_NEXUS_GRAVA + """DUBLE.decidir = () => resp(503, {error: 'o banco não aceitou a gravação (Timeout)'});
      const i1 = DT.criar({fonte: 'pv'}); await i1.entrar(F.linhas, 'pv');
      ['365249', '365250', '365247', '365251'].forEach(id => i1.conferir('18749574|' + id, true));
      await i1.salvar();
      const out = {antes: [i1.pontePendente(18749574), i1.mexidos(), i1.pontesPendentes()]};
      i1.sair();
      DUBLE.decidir = () => resp(200, {ok: true, gravadas: 1, total: 22});
      const i2 = DT.criar({fonte: 'pv', resumo: true}); await i2.entrar(F.linhas, 'pv');
      const linha = (i2.html().match(/<tr class="dp-res" data-g="18749574">[\\s\\S]*?<\\/tr>/) || [''])[0].replace(/<[^>]+>/g, ' ').replace(/\\s+/g, ' ');
      out.reaberta = [i2.pontePendente(18749574), i2.pronto(18749574), i2.pontesPendentes(), linha.includes('ponte pendente'),
        linha.includes('ligada e conferida')];
      // a Itaja 2 não foi salva: nada de ponte "derivada" para ela (o Nexus não tem os códigos dela)
      out.itaja2 = i2.pontePendente(18749576);
      const n = PEDIDOS.length; await i2.salvar();
      out.depois = PEDIDOS.slice(n).filter(p => p.method === 'POST').map(p => [p.url, p.body && p.body.id, p.body && p.body.usina_supervisorio]);
      out.res = i2.S.resultado.ponte.map(x => [x.g.usina, x.ok, x.chave]);
      out.fim = [i2.pontePendente(18749574), i2.S.porPid['18749574'].chave_cadastro];
      return out;""", tmp_path)
    assert r["antes"] == [True, 0, 1]
    assert r["reaberta"] == [True, False, 1, True, False] and r["itaja2"] is False
    assert r["depois"] == [["/api/admin/de-para/decidir", "18749574", "Itaja 1 (551)"]]
    assert r["res"] == [["Itaja 1 (228)", True, "Itaja 1 (551)"]] and r["fim"] == [False, "Itaja 1 (551)"]
    # o confirm de sair do modo no Tempo real conta também as pontes pendentes
    i = MON.index("window.toggleDpMode=")
    assert "_dpI.pontesPendentes()" in MON[i:MON.index("\n};", i)] and "ponte(s) pendente(s)" in MON[i:MON.index("\n};", i)]


def test_a_troca_de_codigos_entre_usinas_vai_num_pedido_so(tmp_path):
    """Contrato-8 (2ª revisão final): o Nexus confere "um código num inversor vivo só" por PEDIDO, e a tela mandava a usina
    lida no Fracttal de hoje (fora da foto) num pedido só dela. A THPN-PHS100 é um site para as Pharmas 2, 3 e 4: depois de
    um Salvar antigo com os blocos trocados (3.x na Pharma 2, 2.x na Pharma 3), a correção ia em dois pedidos ([108] e
    [109]), os dois recusados, a cada Salvar. As usinas que trocam códigos entre si vão juntas."""
    r = _node("""
      F.nexus[108].inversores.forEach((i, n) => { i.codigo_fracttal = 'THPN-PHS100-INVR3.' + (n + 1); i.conferido_em = '2026-10-19T10:00:00Z'; i.fracttal_ligado_por = 'conferido'; });
      F.nexus[109] = {usina_id: 109, nome: 'Pharmas 3', codigo: 'THPN-PHS300', selo: 'selo-109', kwp: 990, kwp_de: 'real',
        chaves: [{supervisorio_id: 171, usina_supervisorio: 'Pharma 3', principal: true, substitui_aba: false}],
        cabines: [{cabine_id: 191, nome: 'UG 02', codigo_fracttal: 'THPN-PHS100-CABN2', potencia_kwp: 990}],
        inversores: [1, 2, 3, 4, 5, 6].map(m => Object.assign(nInv(1410 + m, 171, 'Pharma 3', 'Inversor 1.' + m, 'INVERSOR0' + m, 191, 14, 165),
          {codigo_fracttal: 'THPN-PHS100-INVR2.' + m, conferido_em: '2026-10-19T10:00:00Z', fracttal_ligado_por: 'conferido'}))};
      F.linhas[3] = Object.assign({}, F.linhas[3], {chave_cadastro: 'Pharma 3'});
      F.cadastro.push(C('Pharma 3', 'Pharma III', [1, 2, 3, 4, 5, 6].map(m => ['INVERSOR0' + m, 'Inversor 1.' + m, 14, 165, 'UG 01'])));
      // um pedido por usina (o teto de chaves por pedido em 1): a Itajá vai sozinha, e a Pharma 2 e a 3, que trocam códigos,
      // vão juntas mesmo assim
      const inst = DT.criar({fonte: 'pv', maxPorPedido: 1}); await inst.entrar(F.linhas, 'pv');
      ['365249', '365250', '365247', '365251'].forEach(id => inst.conferir('18749574|' + id, true));
      for (const [pid, ids, b] of [['18758592', [378064, 378065, 378066, 378067, 378068, 378069], 2], ['18751504', [368373, 368374, 368375, 368376, 368377, 368378], 3]])
        for (let m = 1; m <= 6; m++) { await inst.mudar(pid + '|' + ids[m - 1], 'j-cab', 'THPN-PHS100-CABN' + b); await inst.mudar(pid + '|' + ids[m - 1], 'j-at', `THPN-PHS100-INVR${b}.${m}`); inst.conferir(pid + '|' + ids[m - 1], true); }
      const prontas = [inst.pronto('18758592'), inst.pronto('18751504')];
      const n = PEDIDOS.length; await inst.salvar();
      return {prontas,
        pedidos: PEDIDOS.slice(n).filter(p => p.url.endsWith('/salvar')).map(p => [...new Set(p.body.itens.map(i => i.usina_id))].sort())};""", tmp_path)
    assert r["prontas"] == [True, True] and r["pedidos"] == [[93], [108, 109]]    # as duas que trocam, juntas


def test_duas_cabn_de_mesmo_numero_na_mesma_usina_sao_pendencia(tmp_path):
    """Contrato (2ª revisão final): a Ipixuna do Pará (usina 56) tem a Santa Cecilia 1 na IPX100-CABN1 e a 2 na
    2C-IPX100-CABN1, duas árvores no Fracttal; a tela punha as duas na mesma "UG 01" sem pendência e o Nexus recusava a
    usina a cada Salvar. Aqui a Itaja 2 numa segunda árvore (2C-ITA100): as duas plantas ficam com a pendência e o porquê,
    e nada vai ao Nexus. A UG de mesmo número que já tem outro código no Nexus também é pendência."""
    r = _node("""F.arvores['2C-ITA100'] = arv('2C-ITA100', '2C - Itajá 2 - RN', [['2C-ITA100-CABN1', N('2C-ITA100', 1, 4)]], {usina_id: 93});
      F.ufs.push({codigo: '2C-ITA100', nome: '2C - Itajá 2 - RN', cliente: 'Thopen', usina_id: 93, cabines: [{codigo: '2C-ITA100-CABN1', nome: 'Cabine 1'}], fonte: 'foto'});
      const inst = DT.criar({fonte: 'pv'}); await inst.entrar(F.linhas, 'pv');
      const ids2 = [365252, 365254, 365253, 365255];
      await inst.mudar('18749576|' + ids2[0], 'j-uf', '2C-ITA100');
      for (let m = 1; m <= 4; m++) { await inst.mudar('18749576|' + ids2[m - 1], 'j-cab', '2C-ITA100-CABN1'); await inst.mudar('18749576|' + ids2[m - 1], 'j-at', '2C-ITA100-INVR1.' + m); inst.conferir('18749576|' + ids2[m - 1], true); }
      ['365249', '365250', '365247', '365251'].forEach(id => inst.conferir('18749574|' + id, true));
      const h = inst.html(), out = {};
      out.prontas = [inst.pronto('18749574'), inst.pronto('18749576')];
      out.texto = (h.match(/duas cabines do Fracttal com o número 1 \\(([^)]*)\\)/g) || []).length;
      const n = PEDIDOS.length; await inst.salvar();
      out.pedidos = PEDIDOS.slice(n).filter(p => p.url.endsWith('/salvar')).length;
      // só a Itaja 2 de fora: a Itaja 1 passa. E a UG 01 que o Nexus já tem com a ITA100-CABN1, contra a 2C da Itaja 2
      ids2.forEach(id => inst.deixarDeFora('18749576|' + id, true));
      out.so1 = inst.pronto('18749574');
      inst.S.ctx.nexus[93].cabines[0].codigo_fracttal = 'ITA100-CABN1';
      ids2.forEach(id => inst.deixarDeFora('18749576|' + id, false));
      ['365249', '365250', '365247', '365251'].forEach(id => inst.deixarDeFora('18749574|' + id, true));
      ids2.forEach(id => inst.conferir('18749576|' + id, true));
      out.noNexus = [inst.pronto('18749576'), inst.html().includes('(uma já está no Nexus)')];
      return out;""", tmp_path)
    assert r["prontas"] == [False, False] and r["texto"] == 2 and r["pedidos"] == 0
    assert r["so1"] is True and r["noNexus"] == [False, True]


def test_o_cabecalho_do_resultado_diz_as_chaves_que_nao_valem_no_lugar_da_aba(tmp_path):
    """Contrato/regressão (P-k, D-b; 2ª revisão final): gravar no Nexus já não quer dizer valer nos leitores, e a manchete
    dizia em verde "De-para salvo ... Vale no tempo real em até 1 min" com a Pharma II em `nao_marcada` (Full O&M). Agora a
    manchete conta as chaves que não valem (pela `marcacao`) e fica âmbar; no caminho "respondeu tarde", pelo
    `substitui_aba` do estado relido (lá os avisos não vinham)."""
    r = _node("""const out = {}, P = id => '18758592|' + id, ids = [378064, 378065, 378066, 378067, 378068, 378069];
      DUBLE.salvar = body => resp(200, {ok: true, usinas: body.itens.map(it => F.nexus[it.usina_id]), kwp: {}, mudancas: 9,
        avisos: [{usina_id: 108, usina_supervisorio: 'Pharma 2', tipo: 'nao_marcada', texto: 'A chave “Pharma 2” não vale no lugar da aba porque: Full O&M: Não na aba, Sim no Nexus'}],
        marcacao: [{usina_id: 108, usina_supervisorio: 'Pharma 2', principal: true, marcada: false, fora_da_regra: ['Full O&M: Não na aba, Sim no Nexus.']}]});
      const roda = async antes => { const i = DT.criar({fonte: 'pv', esperaSelo: 5, prazoSelo: 60}); await i.entrar(F.linhas, 'pv');
        ids.forEach(id => i.conferir(P(id), true)); if (antes) antes(); await i.salvar(); return i; };
      let inst = await roda();
      const h = inst.resultadoHtml();
      out.um = [inst.S.resultado.naoMarcadas, h.includes('<b class="amb">Gravado no Nexus:</b>'), h.includes('1 chave(s) NÃO valem no lugar da aba (“Pharma 2”)'),
        h.includes('<b class="ok">De-para salvo:</b>')];
      // tudo marcado: o verde de antes
      DUBLE.salvar = body => resp(200, {ok: true, usinas: body.itens.map(it => F.nexus[it.usina_id]), kwp: {}, mudancas: 9, avisos: [],
        marcacao: [{usina_id: 108, usina_supervisorio: 'Pharma 2', principal: true, marcada: true, fora_da_regra: []}]});
      inst = await roda();
      out.verde = inst.resultadoHtml().includes('<b class="ok">De-para salvo:</b>');
      // o Nexus respondeu tarde: o selo mudou, e o estado diz que a chave não vale no lugar da aba
      inst = await roda(() => { DUBLE.salvar = () => 'rede';
        DUBLE.estado = () => resp(200, {ok: true, gravando: false, chaves_sem_usina: [], usinas: [Object.assign({}, F.nexus[108], {selo: 'selo-108-depois',
          chaves: [{supervisorio_id: 170, usina_supervisorio: 'Pharma 2', principal: true, substitui_aba: false}]})]}); });
      const t = inst.resultadoHtml(), x = inst.S.resultado.nexus[0];
      out.tarde = [x.ok, x.tarde, inst.S.resultado.naoMarcadas, t.includes('NÃO valem no lugar da aba'), (x.avisos || []).some(a => /relido do estado/.test(a)), x.motivo || ''];
      return out;""", tmp_path)
    assert r["um"] == [["Pharma 2"], True, True, False] and r["verde"] is True
    assert r["tarde"] == [True, True, ["Pharma 2"], True, True, ""], r["tarde"]


def test_a_chave_irma_da_aba_fora_do_nexus_vai_no_mesmo_salvar(tmp_path):
    """Dado-1 (2ª revisão final): a Coração 2 salva sozinha (usina 77 vazia no Nexus) dividia os 3.250 do Registro só pelas
    80 strings dela (250 → 812,5 kWp por inversor), e com a Coração 1 (111) seguindo pela aba a usina somaria 6.500 nos
    leitores. As duas plantas da `pv` são da mesma usina do Registro e as duas chaves estão na aba e não no Nexus: uma só
    vai se a outra também for (pendência "salve as duas juntas"), e juntas a conta divide pelas 320 strings das duas."""
    r = _node(_REAIS + """
      const CORACAO1 = {plant_id: 18747862, usina: 'Coração 1', depara_fonte: 'pv', qtd_inversores: 12, strings_ativas: 240,
        inv_resumo: Array.from({length: 12}, (_, i) => Object.assign(inv_(18747862, i + 1, null, 20), {esp: 20}))};
      F.linhas = [CORACAO1, CORACAO];
      const inst = DT.criar({fonte: 'pv'}); await inst.entrar(F.linhas, 'pv');
      const A = '18747862', B = '18747863', out = {};
      inst.mudarChave(A, 'Coração 1 (111)'); inst.mudarChave(B, 'Coração 2 (112)');
      // a Coração 1 com um inversor sem o ativo (pendência): não vai, e a Coração 2 não pode ir sozinha
      await inst.mudar(A + '|' + inst.S.porPid[A].invs[0].id, 'j-cab', '');
      inst.conferirTodos();
      out.sozinha = [inst.pronto(B), inst.html().includes('a chave “Coração 1 (111)” (de Coração 1) também é desta usina do Registro e ainda não está no Nexus: confira e salve as duas juntas')];
      await inst.mudar(A + '|' + inst.S.porPid[A].invs[0].id, 'j-cab', 'COR100-CABN1');
      await inst.mudar(A + '|' + inst.S.porPid[A].invs[0].id, 'j-at', 'COR100-INVR1.1');
      inst.conferirTodos();
      out.juntas = [inst.pronto(A), inst.pronto(B)];
      out.conta = Math.round(inst.conta(B).inv[B + '|' + inst.S.porPid[B].invs[0].id] * 1000) / 1000;
      const n = PEDIDOS.length; await inst.salvar();
      out.pedidos = PEDIDOS.slice(n).filter(p => p.url.endsWith('/salvar')).map(p => p.body.itens.map(i => i.usina_supervisorio).sort());
      return out;""", tmp_path)
    assert r["sozinha"] == [False, True]
    assert r["juntas"] == [True, True] and r["conta"] == round(3250 / 320 * 20, 3)          # 203,125, não 812,5
    assert r["pedidos"] == [["Coração 1 (111)", "Coração 2 (112)"]]


# ── a Base: uma usina por linha ──────────────────────────────────────────────────────────────────────────────────────
def test_a_base_mostra_uma_usina_por_linha_e_o_abrir_da_a_tabela_por_inversor(tmp_path):
    r = _node("""const inst = DT.criar({resumo: true, blocos: [{id: 'pv', nome: 'Thopen · API PV Operation'}, {id: 'semp', nome: 'SEMP'}]});
      await inst.entrar(F.linhas, 'pv');
      const h = inst.html(), cab = h.split('dp-res')[0].split('<thead>').pop();
      inst.S.abertos.add('18749574');
      const aberto = inst.html();
      return {usinas: (h.match(/class="dp-res"/g) || []).length, linhas: (h.match(/class="dp-row"/g) || []).length,
        col: (cab.match(/<th/g) || []).length, cab: cab.replace(/<[^>]+>/g, '|').split('|').filter(x => x.trim()),
        blocos: (h.match(/class="dp-bloco" aria-label/g) || []).length, abrir: (h.match(/data-dp-abrir=/g) || []).length,
        aberto: (aberto.match(/class="dp-row"/g) || []).length, chave: h.includes('Itaja 1 (551)') && h.includes('sugestão: a ponte grava ao salvar')};""", tmp_path)
    assert r["usinas"] == 4 and r["linhas"] == 0                             # fechada, nenhuma linha por inversor
    assert r["col"] == 9 and r["cab"][:8] == ["Usina na fonte", "Chave do cadastro", "Usina no Registro mestre",
                                               "Usina no Fracttal", "Inversores", "ligados / na fonte", "Strings corretas", "kWp"]
    assert r["blocos"] == 1                                                    # a SEMP sem usina não vira bloco vazio
    assert r["abrir"] == 4 and r["aberto"] == 4 and r["chave"]


# ── a ligação nas telas ──────────────────────────────────────────────────────────────────────────────────────────────
def _func(nome: str) -> str:
    i = MON.index(f"function {nome}(")
    return MON[i:MON.index("\n", i)]


def test_o_botao_so_aparece_para_admin_nas_contas_da_api_pv(tmp_path):
    if not NODE:
        pytest.skip("node não instalado")
    js = ("const SKEY={'thopen-pv':'pv','thopen-db':'pg','2c':'owen','semp':'semp'};"
          "let state={source:'thopen-pv',view:'strings',dpMode:false}, RD={abreAdmin:true,gravaAdmin:true,pv:{rows:[{plant_id:1,inv_resumo:[]}]}};"
          "global.window={DeparaTabela:{}};"
          + MON[MON.index("const _DP_FONTES="):MON.index("function _dpSair()")] +
          "const out=[_dpBtn().includes('Modo de-para')];"
          "RD.abreAdmin=false; out.push(_dpBtn()==='');"
          "RD.abreAdmin=true; state.source='thopen-db'; out.push(_dpBtn()==='');"
          "state.source='2c'; out.push(_dpBtn().includes('Modo de-para'));"
          "state.source='thopen-pv'; state.view='etm'; out.push(_dpBtn()==='');"
          "state.view='strings'; RD.pv.rows=[{plant_id:1}]; out.push(_dpBtn()==='');"
          "RD.pv.rows=[{plant_id:1,inv_resumo:[]}]; RD.gravaAdmin=false; out.push(_dpBtn()==='');"
          "RD.gravaAdmin=true; state.dpMode=true; out.push(_dpBtn().includes('Sair do modo de-para'));"
          "process.stdout.write(JSON.stringify(out));")
    p = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert p.returncode == 0, p.stderr
    # admin na API PV; o passe sem admin não vê; o banco não tem; a 2C (owen) tem; só na aba Strings; sem o resumo do
    # ciclo, não; o gestor que é admin do Nexus (abre, não grava: P-a) não vê; e no modo o botão vira "Sair do modo de-para"
    assert json.loads(p.stdout) == [True, True, True, True, True, True, True, True]


def test_o_componente_vem_por_caminho_da_plataforma_e_so_para_quem_grava():
    """21/10/2026, antes do 1º push: com o Nexus na raiz o Caddy manda /static/* ao Nexus (menos fonts, logos e notif.js), e
    o /static/depara_tabela.js dava 404 no servidor (o botão sumiria calado). O componente vem de /admin/de-para/tabela.js
    (só admin, como a Base); o Monitoramento só o pede para quem grava, depois do /api/eu."""
    assert '<script src="/static/depara_tabela.js"' not in MON
    assert '<script src="/static/depara_tabela.js"' not in DEP and '<script src="/admin/de-para/tabela.js"></script>' in DEP
    i = MON.index("function _dpCarrega(")
    c = MON[i:MON.index("\n}\n", i)]
    assert "!RD.abreAdmin||!RD.gravaAdmin) return;" in c and "(window.__pfx||(u=>u))('/admin/de-para/tabela.js')" in c
    assert "s.onload=()=>{ if(window.DeparaTabela) render(); };" in c
    i = MON.index("RD.gravaAdmin=!!eu.grava_admin;")
    assert "_dpCarrega();" in MON[i:i + 200]                                   # logo depois do /api/eu
    import app
    from porta_nexus import so_admin
    assert so_admin("/admin/de-para/tabela.js")
    r = app.app.test_client().get("/admin/de-para/tabela.js")                 # sem DASH_PASSWORD no teste: aberto
    assert r.status_code == 200 and r.mimetype == "application/javascript"
    assert r.get_data() == COMP.read_bytes()


def test_o_monitoramento_segue_o_molde_do_criar_os():
    assert "dpMode:false" in MON and "${_dpBtn()}${_osBtn()}${_histBtn()}" in MON
    for f in ("window.setView=", "window.setSource="):                         # trocar de aba ou de fonte sai do modo
        linha = MON[MON.index(f):MON.index("\n", MON.index(f))]
        assert "_dpSair()" in linha and "trkOsMode=false" in linha and "_trkOsSel.clear()" in linha, f
    assert "['gc-osbar','gc-trkosbar','gc-dpbar']" in MON                      # a barra presa na fatia visível do iframe
    assert "if(state.dpMode) return `<button class=\"btn btn-secondary\" disabled" in _func("_osBtn")
    assert "window.toggleOsMode=()=>{ if(state.dpMode) return;" in MON
    assert "(v.loading||state.dpMode)?'':_chipsStatus()" in MON               # os chips somem no modo (o protótipo)
    assert "function gcDeparaJanela(href,rotulo)" in MON                       # a janela fica: o Criar OS usa


def test_o_inversor_aparece_com_o_nome_do_fracttal_e_a_cabine_do_cadastro():
    """Decisão 5 do Levi: depois de ligado, o nome do Fracttal na frente e o da fonte embaixo; a chave (`name`) não muda."""
    i = MON.index("function buildInversores(")
    b = MON[i:MON.index("\n}\n", i)]
    assert "name:inv.nome," in b
    assert "nomeFracttal:(inv.nome_fracttal&&inv.nome_fracttal!==inv.nome)?inv.nome_fracttal:''" in b
    assert "cabine:inv.cabine||(cab?('cabine '+cab[1]):'')" in b
    i = MON.index("function renderInversor(")
    r = MON[i:MON.index("\nfunction ", i + 10)]
    assert "${_he(inv.nomeFracttal)}" in r and "na fonte ${_he(inv.name)}" in r
    assert "toggleInversor('${inv.id}',event,'${inv.pid||''}','${inv.invId||''}','${(inv.name||'')" in r   # a chave segue


def test_a_base_tem_as_abas_e_o_editor_de_antes_fica():
    assert '<h1>De-para de equipamentos</h1>' in DEP and 'href="/" data-casca' in DEP
    assert 'id="abaUsina" aria-selected="true"' in DEP and 'id="secDiag" role="tabpanel" aria-labelledby="abaDiag" hidden' in DEP
    assert '<script src="/admin/de-para/tabela.js"></script>' in DEP
    assert "if(!document.documentElement.classList.contains('janela')) lerUsinas();" in DEP   # a janela é só o editor
    assert 'id="ed" role="dialog" aria-modal="true" aria-labelledby="edTit" hidden' in DEP
    # o tema do Nexus na moldura; na janela por cima do Tempo real, o navy dele
    assert 'html.modo-nexus[data-tema="claro"]:not(.janela){color-scheme:light;' in DEP
    assert "nexus_tema=(claro|escuro)" in DEP


# ── a chave do cadastro na linha da API PV ───────────────────────────────────────────────────────────────────────────
def test_a_linha_da_api_pv_leva_a_chave_do_cadastro_de_hoje(monkeypatch):
    """A tela manda ao Nexus a chave certa e só grava a ponte quando a pessoa escolhe outra. "Sete Lagoa" (API) é a "Sete
    Lagoas" do cadastro; a "União" está sob o código "UNI"; a Itaja 1 (228), sem ligação, não leva chave."""
    monkeypatch.setattr(app, "PV_NOME_API_ALIAS", {"Sete Lagoa": "Sete Lagoas", "União": "União 1 e 2"})
    monkeypatch.setattr(app, "PV_ALIAS_CODIGO", {"União": "UNI"})
    monkeypatch.setattr(app, "_dp_apelidos_da_tela", lambda: {})
    for chave in ("Itaja 1 (551)", "Sete Lagoas", "UNI"):
        monkeypatch.setitem(app.ESPERADO_INV, chave, {"INVERSOR01": 19})
    assert app._pv_chave_da_linha({"id": 1, "nome": "Itaja 1 (551)"}) == {"chave_cadastro": "Itaja 1 (551)"}
    assert app._pv_chave_da_linha({"id": 2, "nome": "Sete Lagoa"}) == {"chave_cadastro": "Sete Lagoas"}
    assert app._pv_chave_da_linha({"id": 3, "nome": "União "}) == {"chave_cadastro": "UNI"}
    assert app._pv_chave_da_linha({"id": 4, "nome": "Itaja 1 (228)"}) == {}


def test_as_rotas_que_o_componente_chama_estao_classificadas():
    """Toda rota da plataforma que o componente chama tem lugar nas listas da ponte e do gestor (como as das páginas)."""
    import leitura_nexus as ln
    rotas = {r.rstrip("/") for r in re.findall(r"(?<![\w])/api/[A-Za-z0-9_\-/]+", COMP.read_text(encoding="utf-8"))}
    assert rotas == {"/api/admin/de-para/fracttal/usinas", "/api/admin/de-para/fracttal/arvore", "/api/admin/de-para/registro",
                     "/api/os-creator/fractall-usinas", "/api/admin/de-para/decidir", "/api/eu", "/api/admin/de-para/cadastro"}
    for r in rotas:
        ponte = (ln.permitido("GET", r) or ln.permitido("POST", r) or any(r.startswith(g) for g in ln.GRAVACOES)
                 or any(r == a or r.startswith(a + "/") for a in ln.ADMIN_DAS_PAGINAS))
        gestor = (ln.permitido_gestor("GET", r) or ln.permitido_gestor("POST", r)
                  or any(r.startswith(g) for g in ln.GRAVACOES_GESTOR))
        assert ponte and gestor, r


def test_fonte_sem_o_nome_do_inversor_nao_duplica_os_do_cadastro(tmp_path):
    """22/10/2026, Levi com print da Pharma 3 (851): "duplicou a quantidade de inversores de pharmas 3 pharmas 4". A API PV
    chegou sem o nome dos inversores ("INV-368373"..: a plataforma não o tinha guardado), a tela não sabia qual inversor do
    cadastro era cada um e punha os 6 da "Pharma 3" de novo como "sem leitura agora": 12 linhas para 6 inversores. Sem o
    nome, nenhuma linha do cadastro é acrescentada; as 6 da fonte dizem que a plataforma ainda não tem o nome delas (22/10: o texto antigo, "sem o nome do
    inversor na fonte", fazia parecer que a API PV não tinha o nome; quem não tinha era a plataforma)."""
    r = _node("""
      F.nexus[109] = {usina_id: 109, nome: 'Pharmas 3', codigo: 'THPN-PHS300', selo: 'selo-109', kwp: 990, kwp_de: 'real',
        chaves: [{supervisorio_id: 171, usina_supervisorio: 'Pharma 3', principal: true, substitui_aba: false}],
        cabines: [{cabine_id: 191, nome: 'UG 03', codigo_fracttal: null, potencia_kwp: 990}],
        inversores: [1, 2, 3, 4, 5, 6].map(m => nInv(1410 + m, 171, 'Pharma 3', 'Inversor 1.' + m, 'INVERSOR0' + m, 191, 14, 165))};
      const ids = [368373, 368374, 368375, 368376, 368377, 368378];
      F.linhas[3] = Object.assign({}, F.linhas[3], {chave_cadastro: 'Pharma 3',
        inv_resumo: ids.map(id => ({id, nome_api: 'INV-' + id, nome: 'INV-' + id, ativas: 0, total: 0, esp: null, sem_visao: false}))});
      F.cadastro.push(C('Pharma 3', 'Pharma III', [1, 2, 3, 4, 5, 6].map(m => ['INVERSOR0' + m, 'Inversor 1.' + m, 14, 165, 'UG 03'])));
      const inst = DT.criar({fonte: 'pv'}); await inst.entrar(F.linhas, 'pv');
      const g = inst.S.porPid['18751504'];
      return {linhas: g.invs.length, sem_leitura: g.invs.filter(i => i.sem_leitura).length,
        aviso: inst.html().includes('a plataforma ainda não tem o nome deste inversor')};""", tmp_path)
    assert r == {"linhas": 6, "sem_leitura": 0, "aviso": True}
