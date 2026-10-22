/* Modo de-para: a tabela por inversor do Tempo real e da Base · De-para de equipamentos (20/10/2026).

   Levi, com o protótipo aprovado ("Boa, é isso mesmo. Implementa no tempo real e adapta na base o de-para para ficar nesse
   padrão de tabela e apresentar uma usina por linha"). UMA linha por inversor, agrupada pela usina da fonte, em que se liga
   cada inversor da fonte ao ativo dele no Fracttal, à cabine (sempre a CABN: "foque em cabine") e à usina do Registro mestre,
   com as strings corretas e o kWp pela regra do Levi (kWp da usina no Registro ÷ strings corretas da usina inteira × strings
   do inversor). O mesmo componente nas duas telas: no Monitoramento (`docs/redesign/Monitoramento (novo design).html`) ele
   ocupa o cartão "Detalhamento por Usina" no lugar da tabela; na Base (`plataforma/templates/depara.html`) ele dá a linha
   de cada usina e abre a tabela por inversor dela.

   De onde vem cada coisa (nenhuma chamada à API PV: o que a fonte manda já está na linha do ciclo, `inv_resumo`):
   - a árvore do Fracttal e as usinas: `/api/admin/de-para/fracttal/usinas` e `/fracttal/arvore` (a foto dos ativos de 22/09
     no banco do Nexus; a usina refeita depois, como a Pharmas em THPN-PHS100, a plataforma lê no Fracttal em fundo);
   - o Registro mestre (kWp real; sem a real, a contratual: decisão do Levi de 20/10): `/api/admin/de-para/registro`;
   - a "Usina Fractall" da aba: `/api/os-creator/fractall-usinas` (o mesmo de-para que o Criar OS já usa);
   - o que já está gravado (o selo, as chaves, os inversores com o código e o Conferido): o Nexus,
     `/t/base/equipamentos/depara/estado`, na MESMA origem (a tela roda dentro da moldura do Nexus pela porta única).
   Quem grava: primeiro o Nexus (`/t/base/equipamentos/depara/salvar`, o remendo com o selo; ele calcula o kWp da usina
   inteira e marca a chave "no lugar da aba"), depois a ponte da fonte na plataforma (`/api/admin/de-para/decidir`), só
   quando a chave escolhida não é a de hoje. Falha de um dos dois é dita com todas as letras, usina por usina.

   As regras de sugestão (medidas na frota em 20/10, `levantamento/cobertura.md`: com estes ajustes, 88% dos inversores):
   - usina do Fracttal: a "Usina Fractall" da aba, o código no nome da linha (a Athon chama a usina "MAB100"), o nome-base
     com o número (Colorado 2 → a irmã de número 2) e as irmãs do mesmo código-base; entre elas, a que casa mais inversores
     pelo CÓDIGO e, empatadas, a árvore mais nova (a Pharma II casa os 6 inversores na THPN-PHS100 de hoje e também na
     PHS200 da foto, que não existe mais no Fracttal);
   - inversor: pelo CÓDIGO N.M procurado na usina inteira — o N.M do nome ("Inversor 2.3") ou o número da planta com o do
     inversor ("Pharma II" + "INVERSOR01" → INVR2.1) —, a cabine é a CABN em que ele está. O número sai SEMPRE do código,
     nunca da descrição (que traz marca e modelo: o "1" do "SUN2000-250KTL-H1" acertaria 2% da frota);
   - Registro mestre: a usina da chave no Nexus, a do Fracttal, o código cheio, o fim do código e a irmã de mesmo
     código-base com o número da planta (Pharma II → Pharmas 2, THPN-PHS200).
*/
(function (G) {
  'use strict';

  // ════════════════════════════════════════════ a regra (pura: o node testa) ════════════════════════════════════════════
  const ROMANO = {I: 1, II: 2, III: 3, IV: 4, V: 5, VI: 6, VII: 7, VIII: 8, IX: 9, X: 10, XI: 11, XII: 12};
  const FONTE_CLIENTE = {pv: 'thopen', semp: 'semp', alveslima: 'alves lima', '2capi': '2c', owen: '2c'};
  const MAX_POR_PEDIDO = 50;             // o MAX_DEPARA do Nexus: chaves (e usinas) por pedido
  const NEXUS_ESTADO = '/t/base/equipamentos/depara/estado', NEXUS_SALVAR = '/t/base/equipamentos/depara/salvar';

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c])); }
  function norm(s) { return String(s == null ? '' : s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/\s+/g, ' ').trim(); }
  // a chave do cadastro como o Nexus a guarda (o texto() dele: os espaços juntados, caixa e acento como estão). A aba e a
  // API PV escrevem "Assis Chateaubriand  Skid 1 (79)" (espaço duplo) e o Nexus "Assis Chateaubriand Skid 1 (79)": pela
  // igualdade exata a tela contava os inversores do Nexus e os da tela como membros diferentes (216,3 kWp no lugar de 324,5
  // no ensaio da Itajá), oferecia duas chaves "iguais" e pulava a ponte. Toda comparação de chave passa por aqui
  const _nk = new Map();
  function nk(s) {
    const t = String(s == null ? '' : s);
    let v = _nk.get(t);
    if (v === undefined) { v = t.split(/\s+/).filter(Boolean).join(' '); if (_nk.size < 20000) _nk.set(t, v); }
    return v;
  }
  function semParenteses(s) { return String(s == null ? '' : s).replace(/\([^)]*\)/g, ' ').replace(/\s+/g, ' ').trim(); }
  // o número no fim do nome: "Itaja 2 (229)" → 2 (o parêntese é o id da API, não o número), "Pharma II" → 2, "INVERSOR03" → 3
  function num(s) {
    const t = semParenteses(s);
    let m = t.match(/(\d+)\s*$/);
    if (m) return +m[1];
    m = t.match(/(?:^|[\s-])([IVX]+)\s*$/);
    return m && ROMANO[m[1]] ? ROMANO[m[1]] : null;
  }
  function nm(s) { const m = String(s == null ? '' : s).match(/(\d+)\.(\d+)/); return m ? `${+m[1]}.${+m[2]}` : null; }
  // os números de um nome de usina do Fracttal: "Pharmas 2, 3 e 4" → [2, 3, 4] (uma usina do Fracttal junta várias plantas)
  function numeros(s) {
    const t = semParenteses(s), out = new Set();
    (t.match(/\b\d+\b/g) || []).forEach(x => out.add(+x));
    (t.match(/(?:^|[\s,])([IVX]+)(?=$|[\s,])/g) || []).forEach(x => { const r = ROMANO[x.replace(/[\s,]/g, '')]; if (r) out.add(r); });
    return [...out];
  }
  // "Thopen - Itajá 1 e 2 - RN" → "Itajá 1 e 2": o Fracttal nomeia a usina "Cliente - Usina - UF"
  function meioDoNome(nome) {
    const p = String(nome || '').split(' - ').map(x => x.trim()).filter(Boolean);
    if (p.length >= 3) return p.slice(1, -1).join(' - ');
    if (p.length === 2) return /^[A-Z]{2}$/.test(p[1]) ? p[0] : p[1];
    return p[0] || '';
  }
  // o nome sem o número da planta: "Itaja 1 (228)" → "itaja", "Pharma II" → "pharma", "Ceilandia 1.1 (89)" → "ceilandia"
  // (o protótipo deixava o ponto, "ceilandia 1.", e a linha ficava sem usina), "Brodowski - Skid 1" → "brodowski"
  function baseNome(s) {
    let t = norm(semParenteses(s));
    t = t.replace(/\bskid\s*\d+$/, '').replace(/\b\d+(?:\.\d+)*$/, '').replace(/\b(?:i|ii|iii|iv|v|vi|vii|viii|ix|x)$/, '');
    t = t.replace(/[\s\-–.,]+$/, '').trim();
    return t.replace(/s$/, '');            // "Pharmas" (Fracttal) e "Pharma" (fonte)
  }
  function canon(c) { return String(c == null ? '' : c).replace(/\s+/g, '').toUpperCase(); }
  function codigoBase(c) { const a = canon(c).match(/[A-Z]{3}\d{3}/g); return a ? a[a.length - 1] : null; }
  function letras(c) { const b = codigoBase(c); return b ? b.slice(0, 3) : null; }
  function suf(c) { return canon(c).split('-').pop(); }
  function site(c) { const m = canon(c).match(/^((?:[A-Z0-9]+-)?[A-Z]{3}\d{3})-/); return m ? m[1] : null; }
  function nmDoCodigo(c) { const m = canon(c).match(/-INVR(\d+(?:\.\d+)*)$/); return m ? m[1].split('.').map(x => String(+x)).join('.') : null; }
  function rotuloInversor(c) { const n = nmDoCodigo(c); return n ? 'Inversor ' + n : null; }
  function nCabine(c) { const m = canon(c).match(/-CABN0*(\d+)$/); return m ? +m[1] : null; }
  function rotuloCabine(c) { const n = nCabine(c); return n != null ? 'Cabine ' + n : canon(c); }
  // o número da cabine do Nexus pelo nome "UG NN" (a cabine é a CABN: CABN2 → "UG 02"); o que não se chama UG (a "UFV" da
  // usina 11, a "PEI" da 85) não tem número e fica fora da conta da cabine, como no Nexus
  function numUG(nome) { const m = String(nome == null ? '' : nome).match(/^\s*UG\s*0*(\d+)\s*$/i); return m ? +m[1] : null; }
  // o casamento do nome do inversor que a plataforma usa (_equip_key): MAIÚSCULO, sem espaço, sem zero à esquerda
  // ("INVERSOR01" da API = "INVERSOR 01" da aba, Rodrigues 27/08); igualdade, nunca substring ("2.1" ≠ "2.18")
  function chaveEquip(s) { return String(s == null ? '' : s).replace(/\s+/g, '').toUpperCase().replace(/(^|\D)0+(\d)/g, '$1$2'); }
  function maior(a, b) { for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] > b[i]; return false; }

  // ── a árvore de uma usina do Fracttal (o formato da rota) ──
  function invsDaArvore(a) {
    if (!a) return [];
    if (a.__invs) return a.__invs;
    const out = [];
    (a.cabines || []).forEach(c => (c.inversores || []).forEach(i => out.push({codigo: canon(i.codigo), nome: rotuloInversor(i.codigo) || i.nome || i.codigo, cab: canon(c.codigo)})));
    (a.sem_cabine || []).forEach(i => out.push({codigo: canon(i.codigo), nome: rotuloInversor(i.codigo) || i.nome || i.codigo, cab: '-'}));
    Object.defineProperty(a, '__invs', {value: out, enumerable: false, configurable: true});
    return out;
  }
  function mapaNM(a) {
    if (!a) return {};
    if (a.__nm) return a.__nm;
    const m = {};
    invsDaArvore(a).forEach(i => { const n = nmDoCodigo(i.codigo); if (n && !m[n]) m[n] = i; });
    Object.defineProperty(a, '__nm', {value: m, enumerable: false, configurable: true});
    return m;
  }
  function blocosDe(a) { return [...new Set(invsDaArvore(a).map(i => (nmDoCodigo(i.codigo) || '').split('.')[0]).filter(Boolean))]; }
  function cabDoCodigo(a, cod) { const i = invsDaArvore(a).find(x => x.codigo === canon(cod)); return i ? i.cab : ''; }

  // ── o inversor da fonte em N.M ──
  // a planta com rótulo de subusina "N.M" ("Ceilandia 1.2 (90)", "Junco 2.1 (134)", "Rodrigues 2.1 (233)"): o número da
  // planta é o N; o ".2" do fim não é número de nada (lido como planta 2, a Ceilandia 1.2 ia para os INVR2.x em vez dos 3.x
  // que o cadastro dela tem: 33 dos 841 inversores da `pv` na medida de 20/10)
  function rotuloNM(n) { return /\d+\.\d+\s*$/.test(semParenteses(n)); }
  function numeroDaPlanta(g) {
    for (const n of [g.usina, g.nome_api, g.chave_cadastro]) {
      if (!n) continue;
      if (rotuloNM(n)) return +semParenteses(n).match(/(\d+)\.\d+\s*$/)[1];
      const x = num(n);
      if (x != null) return x;
    }
    return null;
  }
  function plantaComRotulo(g) { return [g.usina, g.nome_api, g.chave_cadastro].some(n => n && rotuloNM(n)); }
  function nmA(inv) { return nm(inv.nome) || nm(inv.nome_api); }                       // o N.M do nome ("Inversor 2.3")
  function mDoInversor(inv) {
    const x = nm(inv.nome) || nm(inv.nome_api);
    if (x) return +x.split('.')[1];
    const n = num(inv.nome_api);
    return n != null ? n : num(inv.nome);
  }
  function nmB(g, inv) { const M = mDoInversor(inv); return M != null ? `${numeroDaPlanta(g) || 1}.${M}` : null; }   // a planta + o inversor
  function acertos(g, a) {
    const m = mapaNM(a), temN = numeroDaPlanta(g) != null && !plantaComRotulo(g);
    let ha = 0, hb = 0;
    (g.invs || []).forEach(inv => { const x = nmA(inv), y = nmB(g, inv); if (x && m[x]) ha++; if (y && m[y]) hb++; });
    // empatados, vale o número da planta quando a planta tem número: a Coração 2 tem no cadastro os nomes "Inversor 1.x"
    // (que são os ativos da Coração 1) e no Fracttal os INVR2.x
    return {a: ha, b: hb, melhor: Math.max(ha, hb), metodo: hb > ha ? 'b' : ha > hb ? 'a' : (temN ? 'b' : 'a')};
  }
  function sugereInversor(g, inv, a, metodo) {
    if (!a) return null;
    const m = mapaNM(a), fs = metodo === 'b' ? [nmB(g, inv), nmA(inv)] : [nmA(inv), nmB(g, inv)];
    for (const x of fs) if (x && m[x]) return m[x];
    // um bloco só na usina do Fracttal: o número do inversor nesse bloco (Colorado 2: a CLR200 só tem INVR1.x)
    const bs = blocosDe(a), M = mDoInversor(inv);
    if (bs.length === 1 && M != null && m[`${bs[0]}.${M}`]) return m[`${bs[0]}.${M}`];
    return null;
  }

  // ── a usina do Fracttal ──
  function candidatosUF(g, ctx) {
    const ufs = ctx.ufs || [], por = ctx.ufPor || {}, out = [], visto = new Set();
    const add = (u, ordem, porQue) => { if (u && !visto.has(u.codigo)) { visto.add(u.codigo); out.push({codigo: u.codigo, ordem, por: porQue}); } };
    // 1) a "Usina Fractall" da aba (pelo nome da linha, pela chave do cadastro, pelo nome que a API escreve)
    const fr = [g.usina, g.chave_cadastro, g.nome_api].map(n => n && (ctx.fractall || {})[n]).find(Boolean);
    if (fr) { const nf = norm(fr); ufs.filter(u => norm(u.nome) === nf).forEach(u => add(u, 1, 'aba')); }
    // 2) o código no nome da linha (a Athon chama a usina pelo código: "MAB100")
    const cb = codigoBase(g.usina) || codigoBase(g.nome_api);
    if (cb) { const us = ufs.filter(u => codigoBase(u.codigo) === cb); if (us.length === 1) add(us[0], 2, 'código'); }
    // 3) o nome-base da linha no nome da usina do Fracttal
    const nomes = [];
    [baseNome(g.nome_api || ''), baseNome(g.usina || ''), baseNome(g.chave_cadastro || '')].forEach(b => { if (b.length >= 4 && !nomes.includes(b)) nomes.push(b); });
    const porNome = [];
    nomes.forEach(b => ufs.forEach(u => { if (norm(meioDoNome(u.nome)).includes(b) && !porNome.includes(u)) porNome.push(u); }));
    // o cliente da fonte, quando há candidata dele (a Linhares da Thopen ia para a AXIS-LHN100, que vem antes na lista)
    const cli = FONTE_CLIENTE[g.fonte];
    const doCliente = cli ? porNome.filter(u => norm(u.cliente).includes(cli)) : [];
    (doCliente.length ? doCliente : porNome).forEach(u => add(u, 3, 'nome'));
    // 4) as irmãs pelo código-base (as mesmas três letras, o mesmo cliente): a THPN-PHS100 de hoje é irmã da PHS200 da foto
    const fam = new Set(out.map(c => letras(c.codigo)).filter(Boolean));
    const clis = new Set(out.map(c => (por[c.codigo] || {}).cliente).filter(Boolean));
    ufs.forEach(u => { if (fam.has(letras(u.codigo)) && (!clis.size || clis.has(u.cliente))) add(u, 4, 'irmã'); });
    return out.slice(0, 8);
  }
  function escolheUF(g, cands, ctx) {
    const n = numeroDaPlanta(g);
    let melhor = null;
    (cands || []).forEach(c => {
      const a = (ctx.arvores || {})[c.codigo], u = (ctx.ufPor || {})[c.codigo] || {};
      const h = a && !a.erro ? acertos(g, a) : {melhor: 0, metodo: 'a'};
      // a árvore mais nova: lida no Fracttal hoje, ou que só existe pelos códigos que o PCM gravou depois da foto
      const nova = !!(a && a.fonte === 'fracttal') || u.fonte === 'fracttal' || !u.nome || u.nome === u.codigo;
      const comN = n != null && numeros(meioDoNome(u.nome)).includes(n);
      const nota = h.melhor > 0 ? [h.melhor, nova ? 1 : 0, -c.ordem, comN ? 1 : 0] : [0, 0, -c.ordem, comN ? 1 : 0];
      if (!melhor || maior(nota, melhor.nota)) melhor = {codigo: c.codigo, nota, metodo: h.metodo, por: c.por};
    });
    return melhor;
  }
  function ufDoCodigo(cod, ctx) {
    const s = site(cod), ufs = ctx.ufs || [];
    if (!s) return null;
    if ((ctx.ufPor || {})[s]) return s;
    const us = ufs.filter(u => codigoBase(u.codigo) === codigoBase(s));
    return us.length === 1 ? us[0].codigo : null;
  }

  // ── a usina do Registro mestre e a chave do cadastro ──
  function sugereRegistro(g, ufCod, ctx) {
    const regs = ctx.reg || [], regPor = ctx.regPor || {};
    const uidN = g.chave_cadastro && (ctx.chaveUsina || {})[nk(g.chave_cadastro)];
    if (uidN && regPor[uidN]) return {uid: uidN, por: 'a chave no Nexus'};
    const u = (ctx.ufPor || {})[ufCod];
    if (!u) return null;
    if (u.usina_id && regPor[u.usina_id]) return {uid: u.usina_id, por: 'o Fracttal'};
    let r = regs.filter(x => x.codigo && canon(x.codigo) === canon(u.codigo));
    if (r.length === 1) return {uid: r[0].usina_id, por: 'o código'};
    // o fim do código, só quando é de UMA usina: o IPX100 é da 2C e da Thopen
    r = regs.filter(x => x.codigo && suf(x.codigo) === suf(u.codigo));
    if (r.length === 1) return {uid: r[0].usina_id, por: 'o fim do código'};
    const L = letras(u.codigo), n = numeroDaPlanta(g);
    if (L && n != null) {
      r = regs.filter(x => x.codigo && letras(x.codigo) === L && num(x.nome) === n);
      if (r.length === 1) return {uid: r[0].usina_id, por: 'a irmã com o número da planta'};
    }
    return null;
  }
  function sugereChave(g, uid, ctx) {
    if (g.chave_cadastro) return {chave: g.chave_cadastro, por: 'ligada hoje'};
    const est = (ctx.nexus || {})[uid];
    if (!est) return null;
    const ch = (est.chaves || []).map(c => c.usina_supervisorio);
    const n = numeroDaPlanta(g);
    // "Itaja 1 (228)" (a API) → "Itaja 1 (551)" (o cadastro): o mesmo número da planta
    let c = ch.filter(x => n != null && num(x) === n);
    if (c.length === 1) return {chave: c[0], por: 'o número da planta'};
    const b = baseNome(g.usina);
    c = ch.filter(x => baseNome(x) === b);
    if (c.length === 1) return {chave: c[0], por: 'o nome'};
    if (ch.length === 1) return {chave: ch[0], por: 'a única da usina'};
    return null;
  }
  // o estado do Nexus da usina a que a chave está ligada lá (pela chave normalizada), ou null
  function estDaChave(ctx, chave) {
    const uid = chave ? (ctx.chaveUsina || {})[nk(chave)] : null;
    return uid ? (ctx.nexus || {})[uid] || null : null;
  }
  // o inversor do cadastro da chave escolhida para a linha da fonte: pelo Equipamento Supervisório e, sem ele, pelo nome do
  // cadastro igual ao que a fonte manda. A Pharma II manda "Inversor 1.1" e a aba (e o Nexus) têm a "Pharma 2" com
  // INVERSOR01 = "Inversor 1.1": só pelo supervisório, a tela contava os 6 duas vezes no kWp (os do Nexus e os da tela) e
  // punha os 6 de novo como "sem leitura agora" (medido na `pv` de 20/10)
  function cadDoInv(ctx, chave, inv) {
    const c = chave ? (ctx.cadPor || {})[nk(chave)] : null;
    if (!c) return null;
    const invs = c.inversores || [], k = chaveEquip(inv.nome_api);
    return invs.find(i => chaveEquip(i.esup) === k) || invs.find(i => chaveEquip(i.nome) === k) || null;
  }
  // o nome do inversor no cadastro da chave escolhida (o "Equipamento" da aba, a coluna do BD): vai no pedido ao Nexus (o
  // inversor novo nasce com ele, nunca com o "Inversor N.M" do código: a Coração 2 tem "Inversor 1.x" na aba e INVR2.x no
  // Fracttal, e o nome tirado do código mudava a chave do BD). Sem o cadastro da chave, o nome da linha só vale se ele é do
  // cadastro da MESMA chave (o `inv_resumo` usa o da chave de hoje)
  function nomeDoCadastro(ctx, chave, inv) {
    const x = cadDoInv(ctx, chave, inv);
    if (x && x.nome) return x.nome;
    if (inv.sem_leitura) return inv.nome || '';
    return inv.nome && inv.nome !== inv.nome_api && inv.chave_do_nome && nk(inv.chave_do_nome) === nk(chave) ? inv.nome : '';
  }
  // o inversor que o Nexus tem para a linha: na chave, pelo Equipamento Supervisório; senão pelo nome do cadastro, dentro
  // da usina (a regra do salvar do Nexus, dado-7 de 20/10: os 214 inversores do Nexus sem Equipamento Supervisório e a
  // Cambé pela chave "Cambé", com os 20 inversores na "Cambé (85)", davam 409 "mande outro nome" que a tela não resolvia)
  function invNexus(ctx, chave, inv) {
    const est = estDaChave(ctx, chave);
    if (!est) return null;
    const c = nk(chave), k = chaveEquip(inv.nome_api), invs = est.inversores || [];
    const daChave = invs.filter(i => nk(i.usina_supervisorio) === c);
    const x = daChave.find(i => i.equipamento_supervisorio && chaveEquip(i.equipamento_supervisorio) === k);
    if (x) return x;
    const nome = nomeDoCadastro(ctx, chave, inv);
    if (!nome) return null;
    const n = chaveEquip(nome);
    return daChave.find(i => chaveEquip(i.nome) === n) || invs.find(i => chaveEquip(i.nome) === n && !i.equipamento_supervisorio) || null;
  }
  function cabCodigoNexus(est, cabineId) {
    const c = ((est && est.cabines) || []).find(x => x.cabine_id === cabineId);
    return c && c.codigo_fracttal ? canon(c.codigo_fracttal) : '';
  }
  // a cabine do Nexus que a CABN do pedido vai ocupar (a regra do `_cabine_da_cabn` do Nexus): a que já tem o código; senão
  // a "UG NN" de mesmo número ainda sem código (a da aba: a Itajá tem UG 01 e UG 02); senão a "UG NN" que nasce. A soma da
  // cabine na faixa é a dessa cabine, com os inversores do Nexus que já estão nela
  function cabIdent(est, codigo) {
    const cod = canon(codigo), n = nCabine(cod), cabs = (est && est.cabines) || [];
    if (!cod || cod === '-') return '';
    const x = cabs.find(c => c.codigo_fracttal && canon(c.codigo_fracttal) === cod)
      || (n != null ? cabs.find(c => !c.codigo_fracttal && numUG(c.nome) === n) : null);
    return x ? 'c:' + x.cabine_id : (n != null ? 'ug:' + n : 'cabn:' + cod);
  }

  // ── a conta do kWp (a regra do Levi, como o Nexus a faz ao salvar) ──
  // kWp do inversor = kWp da usina no Registro ÷ Σ strings corretas de TODOS os inversores vivos da usina × strings dele;
  // kWp da cabine = a soma dos inversores dela. A soma é da usina inteira no Nexus (todas as chaves dela), com o que a tela
  // vai mandar por cima: salvar só a Itaja 1 com a Itaja 2 fora do Nexus daria 649 kWp por inversor, o dobro do certo.
  // `membros` = [{id, strings, cab, k?, kwpAntes?}] — base do Nexus já sobreposta pela tela (montada pela instância).
  // As duas exceções, as do Nexus (decisões do orquestrador de 20/10, D-c e D-d):
  // - sem potência no Registro (nem real nem contratual): ninguém muda, o kWp e a linhagem de antes ficam (0 ou vazio NUNCA
  //   por cima de dado: com a chave no lugar da aba, a usina perderia o POWER_INV, o PR e a perda);
  // - o inversor vivo sem strings corretas fica com o kWp de antes, e esse kWp sai do kWp do Registro ANTES da divisão
  //   pelos que têm strings: a soma da usina continua sendo o Registro (a Sapopema, com 2 dos 20 inversores sem strings,
  //   passava 10% do Registro). Se os de antes já somam o Registro ou mais, o Nexus recusa a usina: `erro`.
  function contaKwp(kwpUsina, membros) {
    let total = 0, fixo = 0;
    const sem = [];
    membros.forEach(m => {
      if (m.strings > 0) total += +m.strings;
      else { sem.push(m); if (m.kwpAntes > 0) fixo += +m.kwpAntes; }
    });
    const temKwp = kwpUsina > 0, inv = {}, antes = {}, cab = {};
    let por = null, erro = '';
    if (temKwp && total) {
      if (fixo >= kwpUsina) erro = `o kWp de antes dos ${sem.length} inversor(es) sem strings corretas (${fmt(fixo)} kWp) já soma o kWp da usina no Registro mestre (${fmt(kwpUsina)} kWp) ou mais: o Nexus recusa esta usina até as strings deles serem preenchidas`;
      else por = (kwpUsina - fixo) / total;
    }
    const naCabine = (m, v) => { if (!m.cab || m.cab === '-') return; const c = cab[m.cab] = cab[m.cab] || {kwp: 0, strings: 0, n: 0}; c.kwp += v; c.strings += m.strings > 0 ? +m.strings : 0; c.n++; };
    membros.forEach(m => {
      if (por != null && m.strings > 0) { const v = por * m.strings; if (m.k) inv[m.k] = v; naCabine(m, v); return; }
      // fica o de antes: sem strings (D-d), ou sem kWp no Registro (D-c), ou a usina recusada
      if (m.kwpAntes != null && isFinite(m.kwpAntes)) { if (m.k) { inv[m.k] = +m.kwpAntes; antes[m.k] = true; } if (por != null) naCabine(m, +m.kwpAntes); }
    });
    // a cabine só tem a soma nova quando algum inversor dela entrou na divisão (a do Nexus: as outras não mudam)
    Object.keys(cab).forEach(c => { if (!membros.some(m => m.cab === c && m.strings > 0)) delete cab[c]; });
    return {kwp: temKwp ? +kwpUsina : null, total, por, inv, antes, cab, n: membros.length, fixo, semStrings: sem.length, erro};
  }
  const _nf1 = new Intl.NumberFormat('pt-BR', {minimumFractionDigits: 1, maximumFractionDigits: 1});
  function fmt(v) { return _nf1.format(v); }
  function sobrepor(base, tela) {
    // base: [{id, strings, cab, kwpAntes}] do Nexus; tela: [{id, strings, cab, k}]. O que a tela traz vence; strings ou
    // cabine vazias na tela não apagam o que o Nexus tem (o remendo do Nexus não mexe no que vem vazio), e o kWp de antes é
    // sempre o do Nexus (a tela não manda kWp: o Nexus calcula)
    const m = new Map();
    base.forEach(b => m.set(b.id, Object.assign({}, b)));
    tela.forEach(t => { const a = m.get(t.id) || {id: t.id, strings: 0, cab: ''}; m.set(t.id, {id: t.id, strings: t.strings > 0 ? +t.strings : a.strings, cab: t.cab && t.cab !== '-' ? t.cab : a.cab, k: t.k, kwpAntes: a.kwpAntes}); });
    return [...m.values()];
  }

  // ════════════════════════════════════════════════ leitura ════════════════════════════════════════════════════════
  // O Nexus é a página de cima da moldura, na mesma origem (`/nexus/t/<torre>/<tela>` no servidor; `/t/...` na raiz):
  // o prefixo dele é o que vem antes do `/t/`. Fora da moldura não há Nexus para gravar a estrutura.
  function nexusBase() {
    if (typeof G.GC_NEXUS_BASE === 'string') return G.GC_NEXUS_BASE;     // bancada de prova
    try {
      if (!G.top || G.top === G) return null;
      const m = String(G.top.location.pathname || '').match(/^(.*?)\/t\/[a-z0-9_-]+\/[a-z0-9_-]+(?:\/|$)/i);
      return m ? m[1] : null;
    } catch (e) { return null; }
  }
  function erroDe(msg, status, dados, naoJson) { const e = new Error(msg); e.status = status; e.dados = dados; e.naoJson = !!naoJson; return e; }
  // a resposta que não é JSON (P-l, 20/10): o `_tela` do Nexus devolve 403 em HTML para quem não é admin e, sem a chave do
  // cadastro, HTML com status 200; lida como dado, a tela dizia "HTTP 200 sem JSON" ou seguia como se tivesse gravado. Diz
  // quem respondeu, o quê (a página e o título dela) e o que isso quer dizer
  function textoNaoJson(quem, status, ok, bruto) {
    const html = !!bruto && /<(?:!doctype|html|head|body)\b/i.test(bruto);
    const tit = html ? ((bruto.match(/<title[^>]*>([^<]{1,140})<\/title>/i) || bruto.match(/<h1[^>]*>([^<]{1,140})<\/h1>/i) || [])[1] || '').trim() : '';
    const oQue = html ? 'uma página' + (tit ? ` (“${tit}”)` : '') : bruto ? 'um texto' : 'uma resposta vazia';
    const porQue = status === 401 ? ': a sessão venceu (entre de novo)' : status === 403 ? ': sem permissão (só administradores do Nexus)'
      : ok ? ': a rota não chegou a responder (a sessão do Nexus pode ter vencido, ou a tela do Nexus recusou o pedido antes, por exemplo sem a chave do cadastro)'
        : '';
    return `${quem} respondeu ${oQue} em vez dos dados (HTTP ${status})${porQue}`;
  }
  async function lerJson(url, op) {
    op = op || {};
    const ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    const t = ctrl ? setTimeout(() => ctrl.abort(), op.timeout || 60000) : null;
    let r;
    try {
      r = await fetch(url, {method: op.method || 'GET', credentials: 'same-origin',
        headers: op.body ? {'Content-Type': 'application/json'} : undefined,
        body: op.body ? JSON.stringify(op.body) : undefined, signal: ctrl ? ctrl.signal : undefined});
    } catch (e) {
      throw erroDe(e && e.name === 'AbortError' ? 'não respondeu a tempo' : 'sem resposta (rede)', 0);
    } finally { if (t) clearTimeout(t); }
    let d = null, bruto = null;
    if (typeof r.text === 'function') {
      try { bruto = await r.text(); } catch (e) { bruto = null; }
      if (bruto != null && String(bruto).trim()) { try { d = JSON.parse(bruto); } catch (e) { d = null; } }
    } else {
      try { d = await r.json(); } catch (e) { d = null; }
    }
    if (d == null || typeof d !== 'object') throw erroDe(textoNaoJson(op.quem || 'o servidor', r.status, r.ok, bruto), r.status, null, true);
    if (!r.ok) {
      const m = d.motivo || d.error || d.erro || (r.status === 401 ? 'a sessão venceu'
        : r.status === 403 ? 'sem permissão (só administradores do Nexus)' : r.status === 409 ? 'mudou desde que a tela abriu: recarregue'
          : 'HTTP ' + r.status);
      throw erroDe(m, r.status, d);
    }
    if (d.ok === false) throw erroDe(d.motivo || 'recusado', r.status, d);
    return d;
  }
  // a falha do POST em que não se sabe se o Nexus gravou (P-f): sem resposta (rede, estouro de 180 s), a gravação que falhou
  // no meio (o 500 do Nexus diz "leia o estado de novo") e o 502/504 do proxy. Recusa 4xx e o 503 em JSON do Nexus (o banco
  // fora ANTES de gravar) são "nada foi gravado"
  function semSaberSeGravou(e) { return e.status === 0 || e.status === 500 || e.status === 502 || e.status === 504 || (e.naoJson && e.status >= 500); }
  async function emParalelo(itens, n, fn) {
    let i = 0;
    const vai = async () => { while (i < itens.length) { const x = itens[i++]; try { await fn(x); } catch (e) { /* cada um diz o seu */ } } };
    await Promise.all(Array.from({length: Math.min(n, itens.length)}, vai));
  }
  function espera(ms) { return new Promise(r => setTimeout(r, ms)); }

  // ════════════════════════════════════════════════ desenho ════════════════════════════════════════════════════════
  const nf = new Intl.NumberFormat('pt-BR');
  // um formatador por número de casas: criado a cada chamada, o kWp custava ~230 ms a cada desenho da `pv` inteira
  // (medido no perfil da bancada de 20/10: a função mais cara da tela)
  const _nfCasas = {};
  function kw(v, casas) {
    if (v == null || !isFinite(v)) return '—';
    const c = casas == null ? 1 : casas;
    const f = _nfCasas[c] || (_nfCasas[c] = new Intl.NumberFormat('pt-BR', {minimumFractionDigits: c, maximumFractionDigits: c}));
    return f.format(v) + (c === 1 ? ' kWp' : '');
  }
  function hora(iso) { const m = String(iso || '').match(/T?(\d{2}:\d{2})/); return m ? m[1] : ''; }
  function dataBR(iso) { const m = String(iso || '').match(/(\d{4})-(\d{2})-(\d{2})/); return m ? `${m[3]}/${m[2]}` : ''; }

  const CSS = `
.gc-dp{--dp-amb:var(--dp-amb-txt,#f5c877);--dp-red:var(--dp-red-txt,#ff9a9d);--dp-ok:var(--dp-ok-txt,var(--color-accent-300,#c4e755));--dp-act:var(--dp-acao,var(--color-accent,#a3d900))}
.gc-dp table.dp-tab{width:100%;border-collapse:collapse;font-size:14px}
.gc-dp table.dp-tab thead th{text-align:center;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;line-height:1.35;white-space:normal;color:var(--color-neutral-500,#767d92);padding:12px 8px;border-bottom:1px solid var(--color-divider,rgba(255,255,255,.09))}
.gc-dp table.dp-tab tbody td{border-bottom:1px solid var(--color-divider,rgba(255,255,255,.09))}
.gc-dp table.dp-tab th,.gc-dp table.dp-tab td{border-top:0;vertical-align:middle}
.gc-dp table.dp-tab td{color:inherit}
.gc-dp .dp-bloco{background:var(--color-surface,#161d30);border:1px solid var(--color-divider,rgba(255,255,255,.09));border-radius:var(--radius-md,10px);margin:0 0 16px;overflow:hidden}
.gc-dp .dp-bcab{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;padding:16px 22px;border-bottom:1px solid var(--color-divider,rgba(255,255,255,.09))}
.gc-dp .dp-bnome{font-size:16px;font-weight:600;color:var(--color-text,#e9eef6)}
.gc-dp .dp-bconta{font-size:12.5px;color:var(--color-neutral-400,#96a0b4)}
.gc-dp .dp-grupo td{background:color-mix(in srgb,var(--color-neutral-900,#0e1626) 70%,transparent);padding:9px 14px 9px 22px;font-size:12px;color:var(--color-neutral-400,#96a0b4);text-align:left}
.gc-dp .dp-grupo td b{color:var(--color-text,#e9eef6);font-size:13px}
.gc-dp .dp-gl{display:flex;flex-wrap:wrap;align-items:center;gap:6px 14px}
.gc-dp .dp-gl .dp-ch{display:inline-flex;align-items:center;gap:8px;color:var(--color-neutral-400,#96a0b4)}
.gc-dp .dp-gl .dp-ch select{min-width:200px;width:auto;max-width:320px}
.gc-dp .dp-gp{color:var(--dp-amb);font-weight:600}
.gc-dp .dp-gp.red{color:var(--dp-red)}
.gc-dp .dp-row td{padding:8px 7px;vertical-align:middle;text-align:center}
.gc-dp .dp-row td.w-reg{min-width:160px}.gc-dp .dp-row td.w-uf{min-width:185px}.gc-dp .dp-row td.w-cab{min-width:105px}.gc-dp .dp-row td.w-at{min-width:125px}
.gc-dp .dp-row.fora td{opacity:.55}.gc-dp .dp-row.fora td:last-child{opacity:1}
.gc-dp .dp-row:hover td{background:var(--dp-hover,color-mix(in srgb,#0a4f52 14%,transparent))}
.gc-dp select.cel{text-align:center;text-align-last:center}
.gc-dp .dp-kwp{font-variant-numeric:tabular-nums;font-weight:600;color:var(--color-text,#e9eef6);white-space:nowrap}
.gc-dp .dp-kwp small{display:block;font-weight:400;font-size:11px;color:var(--color-neutral-500,#767d92)}
.gc-dp .dp-kwp s{color:var(--color-neutral-500,#767d92);font-weight:400;text-decoration:none}
.gc-dp .dp-faixa td{padding:0!important;text-align:left}
.gc-dp .kwp-faixa{display:flex;flex-wrap:wrap;align-items:center;gap:8px 22px;padding:9px 22px;font-size:12.5px;color:var(--color-neutral-400,#96a0b4)}
.gc-dp .kwp-faixa b{color:var(--color-text,#e9eef6);font-variant-numeric:tabular-nums}
.gc-dp .kwp-faixa .uf{font-weight:600;color:var(--color-text,#e9eef6)}
.gc-dp .kwp-faixa .conta,.gc-dp .mono{font-family:'IBM Plex Mono',Consolas,monospace;font-size:12px;color:var(--color-neutral-300,#c3cad7)}
.gc-dp .kwp-faixa .cab{display:inline-flex;gap:6px;align-items:baseline;padding:3px 10px;border-radius:6px;background:var(--color-neutral-900,#0e1626)}
.gc-dp .kwp-faixa .amb{color:var(--dp-amb)}
.gc-dp .dp-inv{font-weight:600;display:inline-block;text-align:center}
.gc-dp .dp-inv small{display:block;font:400 11px/1.3 'IBM Plex Mono',Consolas,monospace;color:var(--color-neutral-500,#767d92)}
.gc-dp .cel{font-family:inherit;font-size:12.5px;font-weight:600;color:var(--color-text,#e9eef6);background:var(--color-neutral-900,#0e1626);border:1px solid var(--color-divider,rgba(255,255,255,.09));border-radius:8px;padding:6px 9px;height:32px;width:100%;min-width:0}
.gc-dp .cel:focus{outline:none;border-color:var(--dp-act)}
.gc-dp .cel.sug{border-style:dashed;border-color:color-mix(in srgb,var(--dp-act) 55%,transparent)}
.gc-dp .cel.falta{border-color:color-mix(in srgb,var(--gc-red,#f2555a) 70%,transparent)}
.gc-dp .cel[disabled]{opacity:.55}
.gc-dp input.cel{text-align:center;font-variant-numeric:tabular-nums;width:64px}
.gc-dp .dp-hint{display:block;font-size:11px;color:var(--color-neutral-500,#767d92);margin-top:3px;white-space:nowrap}
.gc-dp .dp-hint.amb{color:var(--dp-amb)}
.gc-dp .st{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;white-space:nowrap}
.gc-dp .st::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor}
.gc-dp .st.ok{color:var(--dp-ok)} .gc-dp .st.sug{color:var(--color-neutral-300,#c3cad7)} .gc-dp .st.amb{color:var(--dp-amb)} .gc-dp .st.red{color:var(--dp-red)}
.gc-dp .legenda{display:flex;flex-wrap:wrap;gap:10px 18px;padding:11px 22px;border-bottom:1px solid var(--color-divider,rgba(255,255,255,.09));font-size:12px;color:var(--color-neutral-400,#96a0b4)}
.gc-dp .legenda span{display:inline-flex;align-items:center;gap:7px}
.gc-dp .legenda .amostra{width:26px;height:16px;border-radius:5px;border:1px dashed color-mix(in srgb,var(--dp-act) 55%,transparent)}
.gc-dp .legenda .amostra.cheia{border-style:solid;border-color:var(--color-divider,rgba(255,255,255,.09))}
.gc-dp .dp-fontes{display:flex;flex-wrap:wrap;gap:6px 18px;padding:10px 22px;border-bottom:1px solid var(--color-divider,rgba(255,255,255,.09));font-size:12px;color:var(--color-neutral-400,#96a0b4)}
.gc-dp .dp-fontes b{color:var(--color-neutral-200,#e2e7f0);font-weight:600}
.gc-dp .dp-fontes .amb{color:var(--dp-amb)} .gc-dp .dp-fontes .red{color:var(--dp-red)}
.gc-dp .dp-carrega{padding:34px 22px;text-align:center;color:var(--color-neutral-400,#96a0b4);font-size:13px}
.gc-dp .btn-conf{display:inline-flex;align-items:center;gap:5px;font-weight:600;font-size:12px;line-height:1;font-family:inherit;padding:7px 11px;border-radius:8px;border:1px solid var(--dp-act);background:transparent;color:var(--dp-act);cursor:pointer}
.gc-dp .btn-conf:hover{background:color-mix(in srgb,var(--dp-act) 14%,transparent)}
.gc-dp .btn-conf.desfaz{border:0;padding:2px 4px;color:var(--color-neutral-500,#767d92);text-decoration:underline;font-weight:500}
.gc-dp td.situ .st{white-space:normal;text-align:left}
.gc-dp td.situ .btn-conf.desfaz{display:block;margin:2px auto 0}
.gc-dp .dp-abrir{font:inherit;font-size:12.5px;font-weight:600;padding:5px 12px;border-radius:8px;border:1px solid var(--color-divider,rgba(255,255,255,.15));background:transparent;color:var(--color-text,#e9eef6);cursor:pointer}
.gc-dp .dp-abrir:hover{border-color:var(--dp-act);color:var(--dp-act)}
.gc-dp .dp-res td{padding:12px 14px;text-align:center;vertical-align:middle}
.gc-dp .dp-res td.esq{text-align:left}
.gc-dp .dp-res small{display:block;font-size:11px;color:var(--color-neutral-500,#767d92);font-weight:400}
.gc-dp .dp-aberta>td{padding:0!important;background:color-mix(in srgb,var(--color-neutral-900,#0e1626) 55%,transparent)}
#gc-dpbar .dp-res-lista{margin:8px 0 0;padding-left:18px;max-height:150px;overflow:auto;font-size:12.5px;color:var(--color-neutral-300,#c3cad7)}
#gc-dpbar .dp-res-lista li{margin:2px 0}
#gc-dpbar .ok{color:var(--dp-ok-txt,var(--color-accent-300,#c4e755))} #gc-dpbar .red{color:var(--dp-red-txt,#ff9a9d)} #gc-dpbar .amb{color:var(--dp-amb-txt,#f5c877)}
#gc-dpbar button.lnk{background:transparent;color:var(--color-neutral-400,#96a0b4);text-decoration:underline;border:0;cursor:pointer;font-size:12px;font-family:inherit}
#gc-dpbar button.salvar{background:var(--color-accent,#a3d900);color:#161826;font-weight:700;border:0;border-radius:8px;padding:8px 16px;font-size:12.5px;cursor:pointer;font-family:inherit;display:inline-flex;align-items:center;gap:6px}
#gc-dpbar button.salvar[disabled]{opacity:.45;cursor:default}
`;
  function instalaCss(doc) {
    if (!doc || doc.getElementById('gc-dp-css')) return;
    const s = doc.createElement('style'); s.id = 'gc-dp-css'; s.textContent = CSS; doc.head.appendChild(s);
  }

  // ════════════════════════════════════════════════ a instância ════════════════════════════════════════════════════
  function grupoDaLinha(r, fonte) {
    // `chave_do_nome`: o `nome` do resumo é o do cadastro da chave de HOJE (o `inv_resumo` do build_summary)
    return {fonte: r.depara_fonte || fonte, plant_id: r.plant_id, pid: String(r.plant_id), usina: r.usina || String(r.plant_id),
      nome_api: r.nome_api || '', chave_cadastro: r.chave_cadastro || '',
      invs: (Array.isArray(r.inv_resumo) ? r.inv_resumo : []).map(i => Object.assign({}, i, {chave_do_nome: r.chave_cadastro || ''})),
      sem_visao: !!r.sem_visao, strings_ativas: r.strings_ativas, qtd_inversores: r.qtd_inversores};
  }

  function criar(op) {
    op = op || {};
    const D = G.document;
    const S = {
      ativo: false, carregando: false, etapa: '', grupos: [], porPid: {},
      // chaveUsina e grafia: pela chave normalizada (`nk`); grafia = como o Nexus escreve a chave (o que vai no pedido)
      ctx: {ufs: [], ufPor: {}, arvores: {}, reg: [], regPor: {}, nexus: {}, chaveUsina: {}, grafia: {}, fractall: {},
        cad: [], cadPor: {}, nexusBase: null, nexusErro: '', lido: {}, avisos: [], grava: false, abre: false},
      cands: {}, sel: {}, gsel: {}, base: {}, gbase: {}, salvando: false, etapaSalvar: '', resultado: null,
      abertos: new Set(), lendoArv: {},
      // a ponte que falhou depois de o Nexus gravar (P-b): {pid: {chave, alvo, motivo}}. O próximo Salvar manda só o decidir
      pontePend: {},
      // os avisos do Nexus do último Salvar, por usina da fonte (P-k)
      avisosG: {},
    };
    const k = (g, inv) => `${g.pid}|${inv.id}`;
    const regNome = uid => { const r = S.ctx.regPor[uid]; return r ? r.nome : (uid ? 'usina ' + uid : ''); };

    // ── leitura ──
    async function lerComEspera(url, opL) {
      // a 1ª leitura do banco nesta máquina devolve 503 com `carregando`: tenta de novo por até 1 minuto
      for (let n = 0; n < 12; n++) {
        try { return await lerJson(url, opL); }
        catch (e) { if (!(e.status === 503 && e.dados && e.dados.carregando) || n === 11) throw e; await espera(5000); }
      }
      return null;
    }
    async function lerNexus(chaves, usinas) {
      const nb = S.ctx.nexusBase;
      if (nb == null) return;
      chaves = [...new Set((chaves || []).filter(c => c && !(nk(c) in S.ctx.chaveUsina) && !String(c).includes('|')).map(nk))];
      usinas = [...new Set((usinas || []).filter(u => u && !S.ctx.nexus[u]))];
      const pedidos = [];
      for (let i = 0; i < Math.max(chaves.length, usinas.length); i += MAX_POR_PEDIDO)
        pedidos.push([chaves.slice(i, i + MAX_POR_PEDIDO), usinas.slice(i, i + MAX_POR_PEDIDO)]);
      for (const [cs, us] of pedidos) {
        const q = [cs.length ? 'chaves=' + cs.map(encodeURIComponent).join('|') : '', us.length ? 'usinas=' + us.join(',') : ''].filter(Boolean).join('&');
        try {
          const d = await lerJson(nb + NEXUS_ESTADO + '?' + q, {timeout: 60000, quem: 'o Nexus'});
          (d.usinas || []).forEach(guardaEstado);
          (d.chaves_sem_usina || []).forEach(c => { S.ctx.chaveUsina[nk(c)] = null; });
          S.ctx.lido.nexus = new Date().toISOString();
        } catch (e) { S.ctx.nexusErro = e.message; }
      }
    }
    function guardaEstado(u) {
      S.ctx.nexus[u.usina_id] = u;
      (u.chaves || []).forEach(c => { S.ctx.chaveUsina[nk(c.usina_supervisorio)] = u.usina_id; S.ctx.grafia[nk(c.usina_supervisorio)] = c.usina_supervisorio; });
    }
    // a chave como vai ao Nexus (D-g, 20/10): a grafia dele quando ele já tem a chave; senão com os espaços juntados, que é
    // como ele grava. A ponte, ao contrário, vai com a grafia do cadastro da plataforma (`alvoDaPonte`)
    function chaveParaNexus(chave) { return S.ctx.grafia[nk(chave)] || nk(chave); }
    async function lerArvore(cod) {
      if (!cod || S.ctx.arvores[cod] && !S.ctx.arvores[cod].pendente) return;
      try {
        const a = await lerJson('/api/admin/de-para/fracttal/arvore?codigo=' + encodeURIComponent(cod), {timeout: 45000});
        S.ctx.arvores[cod] = a;
        if (a.codigo && a.codigo !== cod) S.ctx.arvores[a.codigo] = a;
      } catch (e) { S.ctx.arvores[cod] = {codigo: cod, erro: e.message, cabines: [], sem_cabine: []}; }
    }
    async function lerArvores(cods) { await emParalelo([...new Set(cods.filter(Boolean))].filter(c => !S.ctx.arvores[c]), 6, lerArvore); }

    async function carregar() {
      S.carregando = true; S.etapa = 'Lendo o Fracttal, o Registro mestre e o que o Nexus já tem…'; desenhar();
      S.ctx.nexusBase = nexusBase();
      if (S.ctx.nexusBase == null) S.ctx.nexusErro = 'fora do Nexus';
      const nomes = [...new Set(S.grupos.flatMap(g => [g.usina, g.chave_cadastro, g.nome_api]).filter(Boolean))];
      const [ufs, reg, fr, eu, cad] = await Promise.all([
        lerComEspera('/api/admin/de-para/fracttal/usinas').catch(e => ({__erro: e.message})),
        lerComEspera('/api/admin/de-para/registro').catch(e => ({__erro: e.message})),
        lerJson('/api/os-creator/fractall-usinas', {method: 'POST', body: {usinas: nomes}}).catch(() => ({map: {}})),
        // quem grava (P-a): o gestor que é admin do Nexus abre a tabela e não grava (a ponte daria 403 depois do Nexus)
        lerJson('/api/eu').catch(e => ({__erro: e.message})),
        // o cadastro da plataforma: as chaves da aba que o Nexus não tem, os inversores sem leitura agora, os nomes
        lerJson('/api/admin/de-para/cadastro').catch(e => ({__erro: e.message})),
        lerNexus(S.grupos.map(g => g.chave_cadastro), [])]);
      if (ufs.__erro) S.ctx.avisos.push('As usinas do Fracttal não vieram: ' + ufs.__erro + '.');
      if (reg.__erro) S.ctx.avisos.push('O Registro mestre não veio: ' + reg.__erro + '.');
      S.ctx.abre = !!eu.abre_admin; S.ctx.grava = !!eu.grava_admin;
      S.ctx.gravaPorQue = eu.__erro ? `não deu para saber se esta sessão grava (/api/eu: ${eu.__erro})`
        : S.ctx.abre ? 'o seu perfil na Performance é de gestor: a tabela abre para conferir, sem salvar'
          : 'só administradores do Nexus salvam o de-para';
      if (cad.__erro) S.ctx.avisos.push('O cadastro da plataforma não veio: ' + cad.__erro + ' (as chaves da aba que o Nexus ainda não tem e os inversores sem leitura agora não aparecem).');
      S.ctx.cadErro = !!cad.__erro;
      S.ctx.cad = cad.chaves || []; S.ctx.cadPor = Object.fromEntries(S.ctx.cad.map(c => [nk(c.chave), c]));
      S.ctx.ufs = ufs.usinas || []; S.ctx.ufPor = Object.fromEntries(S.ctx.ufs.map(u => [u.codigo, u]));
      S.ctx.lido.fracttal = ufs.lido_em || null; S.ctx.lido.foto = ufs.foto_em || null;
      S.ctx.reg = reg.usinas || []; S.ctx.regPor = Object.fromEntries(S.ctx.reg.map(r => [r.usina_id, r]));
      S.ctx.lido.registro = reg.lido_em || null;
      S.ctx.fractall = (fr && fr.map) || {};
      // as árvores: das usinas candidatas e das que o Nexus já tem gravadas
      S.etapa = 'Lendo a árvore do Fracttal de cada usina…'; desenhar();
      const cods = [];
      S.grupos.forEach(g => {
        S.cands[g.pid] = candidatosUF(g, S.ctx);
        S.cands[g.pid].forEach(c => cods.push(c.codigo));
        g.invs.forEach(inv => { const nx = invNexus(S.ctx, g.chave_cadastro, inv); const u = nx && nx.codigo_fracttal && ufDoCodigo(nx.codigo_fracttal, S.ctx); if (u) cods.push(u); });
      });
      await lerArvores(cods);
      // a usina do Registro de cada uma, e o estado no Nexus das que ainda não vieram
      const ufDe = {}, regDe = {};
      S.grupos.forEach(g => { ufDe[g.pid] = decideUF(g); regDe[g.pid] = sugereRegistro(g, (ufDe[g.pid] || {}).codigo, S.ctx); });
      await lerNexus([], Object.values(regDe).filter(Boolean).map(r => r.uid));
      S.grupos.forEach(g => iniciaGrupo(g, ufDe[g.pid], regDe[g.pid]));
      S.carregando = false; S.etapa = ''; desenhar();
      vigiaPendentes();
    }
    function decideUF(g) {
      for (const inv of g.invs) {
        const nx = invNexus(S.ctx, g.chave_cadastro, inv);
        const u = nx && nx.codigo_fracttal ? ufDoCodigo(nx.codigo_fracttal, S.ctx) : null;
        if (u) { const a = S.ctx.arvores[u]; return {codigo: u, metodo: a ? acertos(g, a).metodo : 'a', por: 'o Nexus'}; }
      }
      return escolheUF(g, S.cands[g.pid] || [], S.ctx);
    }
    // a árvore que a plataforma está lendo no Fracttal (fora da foto): pergunta de novo a cada 6 s, por até 2 min, e
    // refaz a sugestão das usinas que ninguém mexeu ainda
    async function vigiaPendentes() {
      for (let n = 0; n < 20 && S.ativo; n++) {
        const pend = Object.keys(S.ctx.arvores).filter(c => S.ctx.arvores[c] && S.ctx.arvores[c].pendente);
        if (!pend.length) return;
        await espera(6000);
        await emParalelo(pend, 3, lerArvore);
        let mudou = false;
        S.grupos.forEach(g => { if (!mexido(g) && pend.includes(ufDoGrupo(g))) { const u = decideUF(g); iniciaGrupo(g, u, sugereRegistro(g, (u || {}).codigo, S.ctx)); mudou = true; } });
        if (mudou) desenhar();
      }
    }

    // ── o estado de cada linha ──
    function lidas(g) { return g.invs.filter(i => !i.sem_leitura); }
    function ufDoGrupo(g) { const inv = lidas(g)[0] || g.invs[0]; return inv ? (S.sel[k(g, inv)] || {}).uf : ''; }
    // as strings corretas sugeridas e de onde vieram: o Nexus, o cadastro (a aba) ou a LEITURA de agora. A da leitura (P-d,
    // 20/10) é só ponto de partida: 155 inversores da aba não têm Strings Ativas (Sapopema 20, Segredo 40, Sol Maior GD 35),
    // e uma string parada na hora viraria "não esperada" para sempre (o "strings faltando" zera, o alarme some) e entraria na
    // divisão do kWp. Fica a pendência "confira as strings" até o Conferido da linha
    function stringsDe(chave, inv, nx) {
      if (nx && nx.strings_esperadas_qtd > 0) return {strings: +nx.strings_esperadas_qtd, strDe: 'nexus'};
      const x = cadDoInv(S.ctx, chave, inv);
      if (x && x.esp > 0) return {strings: +x.esp, strDe: 'cadastro'};
      if (inv.esp > 0) return {strings: +inv.esp, strDe: 'cadastro'};
      if (inv.ativas > 0) return {strings: +inv.ativas, strDe: 'leitura'};
      return {strings: null, strDe: ''};
    }
    function kwpDoCadastro(chave, inv) {
      const x = cadDoInv(S.ctx, chave, inv);
      return x && x.kwp != null && isFinite(x.kwp) ? +x.kwp : null;
    }
    function selInicial(g, inv, uf, metodo, chave) {
      const nx = invNexus(S.ctx, chave, inv), st = stringsDe(chave, inv, nx);
      if (nx && nx.codigo_fracttal) {
        const cod = canon(nx.codigo_fracttal), ufN = ufDoCodigo(cod, S.ctx) || uf, a = S.ctx.arvores[ufN];
        const est = estDaChave(S.ctx, chave);
        return {uf: ufN || '', cab: cabCodigoNexus(est, nx.cabine_id) || (a ? cabDoCodigo(a, cod) : '') || '', ativo: cod,
          strings: st.strings, strDe: st.strDe, conf: !!nx.conferido_em, sug: !nx.conferido_em, salvo: true};
      }
      const a = S.ctx.arvores[uf], at = sugereInversor(g, inv, a, metodo);
      let cab = at ? at.cab : '';
      if (!at && a && (a.cabines || []).length === 1) cab = canon(a.cabines[0].codigo);
      return {uf: uf || '', cab, ativo: at ? at.codigo : '', strings: st.strings, strDe: st.strDe, conf: false, sug: true, salvo: false};
    }
    // ── os inversores da chave que NÃO mandaram leitura agora (P-m, 20/10) ──
    // O `inv_resumo` só traz quem leu neste ciclo: o inversor parado (justamente o que importa) não aparecia na tela. Ele
    // vira uma linha "sem leitura agora", do cadastro da plataforma (a aba, com as chaves do Nexus por cima) e do Nexus, com
    // as strings do cadastro (editáveis). Começa "de fora" (o Nexus não mexe nele: fica o que a aba ou o Nexus têm) quando a
    // sugestão não fecha; com tudo sugerido, vai como as outras, a conferir. Sem chamada nenhuma à API PV.
    function semLeituraDe(g, chave) {
      if (!chave) return [];
      const c = nk(chave), lid = lidas(g), out = [], visto = new Set();
      // A fonte mandou inversor SEM o nome ("INV-368373": a plataforma não sabe o nome dele sem ir à API PV) — Levi, 22/10/2026,
      // com print da Pharma 3 (851): "duplicou a quantidade de inversores de pharmas 3 pharmas 4". Sem o nome não dá para
      // saber qual inversor do cadastro já está na tela: os 6 do cadastro apareciam de novo como "sem leitura agora", 12
      // linhas para 6 inversores. Com um só sem nome, não se acrescenta nenhum; a linha diz "sem o nome do inversor na fonte"
      if (lid.some(i => /^INV-\d+$/.test(String(i.nome_api || '')))) return [];
      const nxLidos = new Set(lid.map(inv => (invNexus(S.ctx, chave, inv) || {}).inversor_id).filter(x => x != null));
      // a linha da fonte que já é este inversor: pelo cadastro (o supervisório ou o nome igual ao da fonte, `cadDoInv`), ou
      // pelo nome do cadastro da chave de hoje
      const casados = new Set(lid.map(i => (cadDoInv(S.ctx, chave, i) || {}).esup).filter(Boolean).map(chaveEquip));
      const casa = (esup, nome) => casados.has(chaveEquip(esup)) || lid.some(i => chaveEquip(i.nome_api) === chaveEquip(esup)
        || (nome && (chaveEquip(i.nome_api) === chaveEquip(nome) || (i.nome && i.nome !== i.nome_api && chaveEquip(i.nome) === chaveEquip(nome)))));
      const add = (esup, nome, esp) => {
        const ce = chaveEquip(esup);
        if (!esup || visto.has(ce)) return;
        visto.add(ce);
        out.push({id: 'sl:' + ce, nome_api: esup, nome: nome || esup, ativas: null, total: null, esp: esp > 0 ? +esp : null,
          sem_visao: false, sem_leitura: true, chave_do_nome: chave});
      };
      const cad = S.ctx.cadPor[c];
      ((cad && cad.inversores) || []).forEach(x => { if (!casa(x.esup, x.nome)) add(x.esup, x.nome, x.esp); });
      const est = estDaChave(S.ctx, chave);
      ((est && est.inversores) || []).forEach(i => {
        if (nk(i.usina_supervisorio) !== c || nxLidos.has(i.inversor_id) || !i.equipamento_supervisorio) return;
        if (!casa(i.equipamento_supervisorio, i.nome)) add(i.equipamento_supervisorio, i.nome, i.strings_esperadas_qtd);
      });
      return out;
    }
    // refaz o que depende da chave escolhida: as linhas "sem leitura agora" (a troca de chave troca os inversores do
    // cadastro; a base delas é a sugestão, para que só a troca da chave conte como mexida) e as strings que só tinham vindo
    // da leitura de agora, que passam às do cadastro da chave nova quando ele as tem (a Coração 2, sem ligação hoje, ganha
    // as 20 da "Coração 2 (112)" no lugar das 19 com corrente na hora)
    function refazSemLeitura(g) {
      const gs = S.gsel[g.pid] || {};
      g.invs.filter(i => i.sem_leitura).forEach(i => { delete S.sel[k(g, i)]; delete S.base[k(g, i)]; });
      g.invs = lidas(g);
      g.invs.forEach(inv => {
        const s = S.sel[k(g, inv)];
        if (!s || !(s.strDe === 'leitura' || !s.strDe)) return;
        const st = stringsDe(gs.chave, inv, invNexus(S.ctx, gs.chave, inv));
        if (st.strDe === 'nexus' || st.strDe === 'cadastro') S.sel[k(g, inv)] = Object.assign({}, s, st);
      });
      const uf = ufDoGrupo(g), novos = semLeituraDe(g, gs.chave);
      novos.forEach(inv => {
        const s = selInicial(g, inv, uf, gs.metodo, gs.chave);
        if (!(s.uf && s.cab && s.ativo && s.strings > 0)) s.fora = true;
        S.sel[k(g, inv)] = s;
        S.base[k(g, inv)] = Object.assign({}, s);
      });
      g.invs = g.invs.concat(novos);
    }
    function iniciaGrupo(g, uf, reg) {
      // a usina do Registro que vem da chave já ligada no Nexus é fato, não sugestão (borda cheia)
      const gs = {reg: reg ? reg.uid : null, regSug: !(reg && reg.por === 'a chave no Nexus'), chave: '', chaveSug: true, metodo: (uf || {}).metodo || 'a'};
      const sc = gs.reg ? sugereChave(g, gs.reg, S.ctx) : (g.chave_cadastro ? {chave: g.chave_cadastro, por: 'ligada hoje'} : null);
      gs.chave = sc ? sc.chave : '';
      gs.chaveSug = !g.chave_cadastro;
      S.gsel[g.pid] = gs;
      lidas(g).forEach(inv => { S.sel[k(g, inv)] = selInicial(g, inv, (uf || {}).codigo, gs.metodo, gs.chave); });
      refazSemLeitura(g);
      fotografa(g);
    }
    function fotografa(g) {
      S.gbase[g.pid] = Object.assign({}, S.gsel[g.pid]);
      g.invs.forEach(inv => { S.base[k(g, inv)] = Object.assign({}, S.sel[k(g, inv)]); });
    }
    function mexido(g) {
      const gs = S.gsel[g.pid], gb = S.gbase[g.pid];
      if (!gs || !gb) return false;
      if (gs.reg !== gb.reg || nk(gs.chave) !== nk(gb.chave)) return true;
      return g.invs.some(inv => { const a = S.sel[k(g, inv)] || {}, b = S.base[k(g, inv)] || {};
        return ['uf', 'cab', 'ativo', 'strings', 'conf', 'fora'].some(f => (a[f] == null || a[f] === false ? null : a[f]) !== (b[f] == null || b[f] === false ? null : b[f])); });
    }
    // o Equipamento Supervisório que vai no pedido: o do Nexus; o inversor que o Nexus achou pelo nome sem ter o dele (os 214
    // sem Equipamento Supervisório) leva o da fonte, e o Nexus o preenche
    function esupDe(g, inv, chave) {
      const nx = invNexus(S.ctx, chave, inv);
      if (nx && nx.equipamento_supervisorio) return nx.equipamento_supervisorio;
      const x = !nx ? cadDoInv(S.ctx, chave, inv) : null;              // o da aba, que o Nexus semeia na chave nova
      return x && x.esup ? x.esup : inv.nome_api;
    }
    // a identidade do inversor na conta e no "um código num inversor só": o que o Nexus tem, pelo id dele; o que o Nexus
    // ainda não tem, pela chave normalizada e o Equipamento Supervisório (a mesma da semente da aba em `membrosDa`).
    // Guardada até a próxima mudança: a `pv` tem 115 usinas e 840 inversores por desenho
    function idDe(g, inv, chave) {
      const e = _memo && _memo.esup, kk = k(g, inv) + '|' + nk(chave);
      if (e && kk in e) return e[kk];
      const nx = invNexus(S.ctx, chave, inv);
      const x = nx ? null : cadDoInv(S.ctx, chave, inv);
      const v = nx ? 'nx:' + nx.inversor_id : 'novo:' + nk(chave) + '|' + chaveEquip(x && x.esup ? x.esup : inv.nome_api);
      if (e) e[kk] = v;
      return v;
    }

    // o código de cada inversor vivo do Nexus (nas usinas lidas), para o "um código num inversor só"
    function usoNoNexus() {
      const uso = {};
      Object.values(S.ctx.nexus).forEach(est => (est.inversores || []).forEach(i => {
        if (i.codigo_fracttal) (uso[canon(i.codigo_fracttal)] = uso[canon(i.codigo_fracttal)] || []).push({id: 'nx:' + i.inversor_id, nome: i.nome, chave: i.usina_supervisorio});
      }));
      return uso;
    }
    let _memo = null;
    function memo() {
      if (_memo) return _memo;
      const naTela = {};
      S.grupos.forEach(g => g.invs.forEach(inv => { const s = S.sel[k(g, inv)] || {};
        if (s.ativo && !s.fora) (naTela[s.ativo] = naTela[s.ativo] || []).push(k(g, inv)); }));
      _memo = {naTela, ids: new Set(), nexus: usoNoNexus(), conta: {}, contaSo: {}, pend: {}, esup: {}, vai: new Set(),
        cabn: {}, irma: {}};
      // as CABN escolhidas por usina do Registro e número (a pendência das duas CABN de mesmo número, `duasCabnDe`)
      S.grupos.forEach(g => { const gs = S.gsel[g.pid]; if (!gs || !gs.reg) return;
        g.invs.forEach(inv => { const s = S.sel[k(g, inv)] || {}, n = s.cab && s.cab !== '-' && !s.fora ? nCabine(s.cab) : null;
          if (n == null) return; const u = _memo.cabn[gs.reg] = _memo.cabn[gs.reg] || {}; (u[n] = u[n] || new Set()).add(canon(s.cab)); }); });
      // P-e (20/10): o "já está no X no Nexus" só se isenta quando o X vai no MESMO Salvar. Isentar por estar em qualquer
      // usina da tela (também a que tem pendência e fica fora) deixava passar o código que o Nexus ainda tem noutro inversor,
      // e o Nexus recusava o pedido inteiro com 409, levando junto as outras usinas do lote (o ITA100-INVR1.1 trocado na
      // Itaja 1 com pendência e posto na Itaja 2). O que vai depende da pendência, e a pendência do que vai: repete até
      // parar de mudar (cada volta só tira usina; em geral uma ou duas voltas)
      let vai = S.grupos.filter(g => mexido(g) && !pendenciasGrupo(g).length && g.invs.some(inv => !(S.sel[k(g, inv)] || {}).fora));
      for (let n = 0; n <= S.grupos.length; n++) {
        const ids = new Set();
        vai.forEach(g => { const gs = S.gsel[g.pid]; g.invs.forEach(inv => { if (!(S.sel[k(g, inv)] || {}).fora) ids.add(idDe(g, inv, gs.chave)); }); });
        _memo.ids = ids; _memo.pend = {};
        const nos = new Set(vai.map(g => g.pid));
        const fica = vai.filter(g => g.invs.every(inv => !pendencia(g, inv)) && !irmaFora(g, nos));
        if (fica.length === vai.length) break;
        vai = fica;
      }
      _memo.vai = new Set(vai.map(g => g.pid));
      S.grupos.forEach(g => { const t = mexido(g) ? irmaFora(g, _memo.vai) : ''; if (t) _memo.irma[g.pid] = t; });
      return _memo;
    }
    // a chave irmã que fica de fora (2ª revisão final, 21/10/2026): o Nexus semeia da aba a chave que ainda não tem e divide
    // o Registro pelas strings da usina INTEIRA que ele conhece. A Coração 2 salva sozinha (usina 77 vazia no Nexus) dividia
    // os 3.250 do Registro só pelas 80 strings dela (250 → 812,5 kWp por inversor), e com a Coração 1 (111) seguindo pela aba
    // a usina somaria 6.500 nos leitores. Outra planta da tela na MESMA usina do Registro, com uma chave da aba que o Nexus
    // ainda não tem, vai no mesmo Salvar ou nenhuma das duas vai (o Nexus recusa o mesmo caso pelas Ligações)
    // A irmã SEM chave escolhida também segura (revisão do acerto final, 21/10/2026): no dado real as duas Coração chegam com
    // a chave vazia (sem ligação hoje e a usina 77 vazia no Nexus, então nada sugere a chave); escolhida só a "Coração 2 (112)",
    // ela ia sozinha e o Nexus gravava 812,5 kWp por inversor. Conta a planta da mesma usina do Registro que não escolheu
    // chave mas tem, entre as opções, uma chave da aba que o Nexus ainda não tem
    function irmaFora(g, nos) {
      const gs = S.gsel[g.pid] || {};
      if (!gs.reg) return '';
      const daAbaFora = c => c && nk(c) !== nk(gs.chave) && !S.ctx.chaveUsina[nk(c)] && S.ctx.cadPor[nk(c)];
      const h = S.grupos.find(x => { const xs = S.gsel[x.pid] || {};
        if (x === g || xs.reg !== gs.reg || nos.has(x.pid)) return false;
        return xs.chave ? daAbaFora(xs.chave) : chavesDoCadastro(x).some(daAbaFora); });
      if (!h) return '';
      const hc = (S.gsel[h.pid] || {}).chave;
      return hc ? `a chave “${hc}” (de ${h.usina}) também é desta usina do Registro e ainda não está no Nexus: confira e salve as duas juntas (o Nexus divide o kWp do Registro pelas strings da usina inteira; sem ela, a divisão sairia só pelas outras)`
        : `${h.usina} também é desta usina do Registro e a chave dela ainda não está no Nexus: escolha a chave de ${h.usina}, confira e salve as duas juntas (o Nexus divide o kWp do Registro pelas strings da usina inteira; sem ela, a divisão sairia só pelas outras)`;
    }
    function pendencia(g, inv) {
      const M = memo(), key = k(g, inv);
      if (key in M.pend) return M.pend[key];
      return (M.pend[key] = pendenciaSemMemo(g, inv));
    }
    const CONFIRA = 'confira as strings: vieram da leitura de agora';
    // a pendência que o próprio Conferido resolve (a linha mostra o botão junto)
    function soConferir(p) { return p === CONFIRA; }
    function pendenciaSemMemo(g, inv) {
      const key = k(g, inv), s = S.sel[key] || {}, gs = S.gsel[g.pid] || {};
      if (s.fora) return '';
      if (/^INV-\d+$/.test(String(inv.nome_api || ''))) return 'sem o nome do inversor na fonte';
      if (!s.uf) return 'falta a usina do Fracttal';
      if (!s.cab) return 'falta a cabine';
      if (!s.ativo) return 'falta o inversor';
      const M = memo();
      if ((M.naTela[s.ativo] || []).length > 1) return 'inversor repetido';
      const meu = gs.chave ? idDe(g, inv, gs.chave) : '';
      const outro = (M.nexus[s.ativo] || []).find(x => x.id !== meu && !M.ids.has(x.id));
      if (outro) return `já está no ${outro.nome} (${outro.chave}) no Nexus`;
      if (!(s.strings > 0)) return 'falta strings';
      if (!gs.reg) return 'falta a usina do Registro mestre';
      if (s.strDe === 'leitura' && !s.conf) return CONFIRA;
      return '';
    }
    function pendenciasGrupo(g) {
      const gs = S.gsel[g.pid] || {}, out = [];
      if (!lidas(g).length) out.push('a fonte não mandou os inversores desta usina neste ciclo');
      if (!gs.chave) out.push(opcoesDeChave(g).length ? 'falta a chave do cadastro'
        : 'falta a chave do cadastro: esta planta não tem chave na aba Equipamentos nem no Nexus (ligue a chave na Base > Equipamentos das usinas; o de-para não cria chave nova)');
      else {
        const outro = S.grupos.find(h => h.pid !== g.pid && nk((S.gsel[h.pid] || {}).chave) === nk(gs.chave));
        if (outro) out.push(`a chave “${gs.chave}” também está em ${outro.usina}`);
        const uidN = S.ctx.chaveUsina[nk(gs.chave)];
        if (uidN && gs.reg && uidN !== gs.reg) out.push(`no Nexus a chave “${gs.chave}” é de ${regNome(uidN)}: escolha essa usina do Registro ou desligue a chave lá`);
        if (chaveSemCadastro(g, gs.chave)) out.push(`a chave “${gs.chave}” não está na aba Equipamentos nem no Nexus: o Nexus recusa (o de-para não cria chave nova, que nunca valeria no lugar da aba); escolha a chave da aba ou ligue esta na Base > Equipamentos das usinas`);
      }
      if (gs.reg && S.ctx.nexusBase != null && !S.ctx.nexus[gs.reg]) out.push('o estado desta usina no Nexus não foi lido' + (S.ctx.nexusErro ? ` (${S.ctx.nexusErro})` : ''));
      // D-d: o kWp de antes dos inversores sem strings sai do Registro; se já soma o Registro, o Nexus recusa a usina (a conta
      // com esta usina só por cima do Nexus, que é a que ele faz quando ela vai no pedido)
      const c = gs.reg && gs.chave ? contaSo(g) : null;
      if (c && c.erro) out.push(c.erro);
      const dc = duasCabnDe(g);
      if (dc) out.push(dc);
      return out;
    }
    // as pendências que a tela mostra: as do grupo e a da chave irmã (calculada com o que vai no Salvar, em `memo`)
    function pendenciasTela(g) { const M = memo(), ir = M.irma[g.pid]; return ir ? pendenciasGrupo(g).concat([ir]) : pendenciasGrupo(g); }
    // duas CABN de mesmo número na mesma usina do Registro (2ª revisão final, 21/10/2026): a Ipixuna do Pará (usina 56) tem a
    // Santa Cecilia 1 na IPX100-CABN1 e a 2 na 2C-IPX100-CABN1, duas árvores no Fracttal. A regra "UG NN = o número da CABN"
    // põe as duas na "UG 01", e o Nexus recusa a usina inteira (409) a cada Salvar sem a tela dizer o que fazer. Também a
    // UG de mesmo número que no Nexus já tem OUTRO código. Como nomear a 2ª CABN1 é regra nova: fica com o Levi
    function duasCabnDe(g) {
      const gs = S.gsel[g.pid] || {}, M = memo();
      if (!gs.reg) return '';
      const daUsina = M.cabn[gs.reg] || {}, est = S.ctx.nexus[gs.reg];
      for (const inv of g.invs) {
        const s = S.sel[k(g, inv)] || {}, n = s.cab && s.cab !== '-' && !s.fora ? nCabine(s.cab) : null;
        if (n == null) continue;
        const cods = [...(daUsina[n] || [])];
        const noNexus = ((est && est.cabines) || []).find(c => numUG(c.nome) === n && c.codigo_fracttal && canon(c.codigo_fracttal) !== canon(s.cab));
        if (cods.length > 1 || noNexus) {
          const todos = [...new Set(cods.concat(noNexus ? [canon(noNexus.codigo_fracttal)] : []))].sort();
          return `duas cabines do Fracttal com o número ${n} (${todos.join(' e ')}) caem na “UG ${String(n).padStart(2, '0')}” desta usina do Registro${noNexus ? ' (uma já está no Nexus)' : ''}: o Nexus recusa (a cabine é a CABN, e o nome é “UG NN”). Como nomear a 2ª é decisão a levar ao Levi; até lá, deixe de fora as linhas de uma das plantas`;
        }
      }
      return '';
    }
    // vai no Salvar (o Nexus e depois a ponte): mexida, sem pendência, com algum inversor que não está de fora (tudo de fora
    // não é de-para: a chave iria "no lugar da aba" sem inversor nenhum)
    function pronto(g) { return memo().vai.has(g.pid); }
    // a ponte que ficou pendente (P-b): o Nexus gravou e a ponte não. O próximo Salvar manda só o decidir, enquanto a chave
    // escolhida for a mesma
    // A ponte pendente vem do ESTADO, não só da memória desta instância (2ª revisão final, 21/10/2026): o Tempo real cria
    // uma instância a cada "Modo de-para", e trocar de fonte ou recarregar a Base também esquecia o `pontePend`. Reaberta,
    // a Itaja 1 (228) aparecia "ligada e conferida", com "sugestão: a ponte grava ao salvar", e o Salvar desligado (nada
    // mexido): a fonte seguia sem ponte com a estrutura já gravada no Nexus. Há ponte pendente quando a chave escolhida não
    // é a de hoje, o Nexus já tem essa chave NESTA usina do Registro e todo inversor da fonte que vai está nela com o código
    // do Fracttal e Conferido (o rastro do Salvar; os 1.932 do "Ligar pela aba" não têm código)
    function ponteDerivada(g) {
      const gs = S.gsel[g.pid] || {};
      if (!gs.chave || !gs.reg || S.ctx.nexusBase == null || S.ctx.chaveUsina[nk(gs.chave)] !== gs.reg || mexido(g)) return null;
      const p = alvoDaPonte(g, gs.chave);
      if (!p) return null;
      const vao = lidas(g).filter(inv => !(S.sel[k(g, inv)] || {}).fora);
      const gravados = vao.length && vao.every(inv => { const nx = invNexus(S.ctx, gs.chave, inv);
        return nx && nx.codigo_fracttal && nx.fracttal_ligado_por === 'conferido' && nk(nx.usina_supervisorio) === nk(gs.chave); });
      return gravados ? Object.assign(p, {motivo: 'o Nexus já tem esta usina gravada na chave escolhida, e a fonte não liga a ela'}) : null;
    }
    // a ponte que ficou pendente (P-b): o Nexus gravou e a ponte não. O próximo Salvar manda só o decidir, enquanto a chave
    // escolhida for a mesma. Devolve a ponte ({chave, alvo, motivo}) ou null
    // Usina com pendência NÃO grava ponte (revisão do acerto final, 21/10/2026): a ponte derivada da Coração 2 saía com a
    // pendência vermelha "a chave 'Coração 1 (111)' também está em Coração 1" na tela (os INVERSOR01..03 dela casavam pelo
    // nome com os da Coração 1 já gravados), e um Salvar só da Pharma II ligava a planta Coração 2 à chave da outra planta.
    // Vale também para a ponte que ficou pendente nesta instância: com pendência, a pessoa resolve antes
    function comPendencia(g) {
      return pendenciasTela(g).length > 0 || g.invs.some(inv => !(S.sel[k(g, inv)] || {}).fora && !!pendencia(g, inv));
    }
    function precisaPonte(g) {
      const p = S.pontePend[g.pid], gs = S.gsel[g.pid] || {};
      if (comPendencia(g)) return null;
      return p && nk(p.chave) === nk(gs.chave) ? p : ponteDerivada(g);
    }

    // a conta do kWp de um grupo: o Nexus da usina inteira, com o que vai ser salvo por cima, e o próprio grupo. A chave que
    // o Nexus ainda não tem entra como ele a vai semear da aba ANTES do remendo (D-a, 20/10: todos os inversores da aba com as
    // strings e o kWp dela): sem isso a tela dividia o Registro só pelos inversores que leram agora
    function ugIdent(est, n) {
      const x = ((est && est.cabines) || []).find(c => numUG(c.nome) === n);
      return x ? 'c:' + x.cabine_id : 'ug:' + n;
    }
    function membrosDa(uid, incluir) {
      const est = S.ctx.nexus[uid], base = [];
      ((est && est.inversores) || []).forEach(i => base.push({id: 'nx:' + i.inversor_id,
        strings: i.strings_esperadas_qtd > 0 ? +i.strings_esperadas_qtd : 0, cab: i.cabine_id != null ? 'c:' + i.cabine_id : '',
        kwpAntes: i.potencia_kwp != null && isFinite(i.potencia_kwp) ? +i.potencia_kwp : null}));
      const tela = [], semeadas = new Set(), rotulos = {};
      S.grupos.forEach(g => {
        const gs = S.gsel[g.pid];
        if (!gs || gs.reg !== uid || !gs.chave || !incluir.has(g.pid)) return;
        const c = nk(gs.chave);
        if (est && !(est.chaves || []).some(x => nk(x.usina_supervisorio) === c) && !semeadas.has(c)) {
          semeadas.add(c);
          ((S.ctx.cadPor[c] || {}).inversores || []).forEach(x => base.push({id: 'novo:' + c + '|' + chaveEquip(x.esup),
            strings: x.esp > 0 ? +x.esp : 0, cab: numUG(x.ug) != null ? ugIdent(est, numUG(x.ug)) : '',
            kwpAntes: x.kwp != null && isFinite(x.kwp) ? +x.kwp : null}));
        }
        g.invs.forEach(inv => {
          const s = S.sel[k(g, inv)] || {}, id = idDe(g, inv, gs.chave);
          // a linha de fora não vai no pedido, mas o inversor que o Nexus já tem segue na conta dele com o que está lá: a
          // linha mostra o kWp que ELE vai gravar (o parado da Ouro Branco 4 (773), com 17 strings no Nexus, vai de 145,2
          // a 133,7 junto com os outros, e não "fica o de hoje")
          if (s.fora) { if (base.some(b => b.id === id)) tela.push({id, strings: null, cab: '', k: k(g, inv)}); return; }
          const cab = s.cab && s.cab !== '-' ? cabIdent(est, s.cab) : '';
          if (cab) rotulos[cab] = rotuloCabine(s.cab);
          tela.push({id, strings: s.strings, cab, k: k(g, inv)});
        });
      });
      return {membros: sobrepor(base, tela), base, rotulos};
    }
    function contaDe(g, incluir, cache) {
      const gs = S.gsel[g.pid] || {};
      if (!gs.reg) return null;
      if (cache[g.pid]) return cache[g.pid];
      const {membros, base, rotulos} = membrosDa(gs.reg, incluir);
      const est = S.ctx.nexus[gs.reg], r = S.ctx.regPor[gs.reg] || {};
      // P-c (20/10): o kWp da conta é o do estado do Nexus (o Registro com que ELE calcula ao gravar); a cópia do Registro da
      // plataforma (`/api/admin/de-para/registro`, 10 min, só muda num Publicar) fica para a tela sem o Nexus e para o rótulo
      // da lista. No ensaio da Itajá com 2.700 kWp no Nexus e 2.596 na cópia, a tela mostrava 324,5 "igual ao de hoje" e o
      // Nexus gravava 337,5. As duas diferentes: a faixa diz
      const doNexus = !!est && S.ctx.nexusBase != null;
      const kwpU = doNexus ? est.kwp : r.kwp, kwpDe = doNexus ? est.kwp_de : r.kwp_de;
      const diverge = doNexus && (r.kwp > 0 || est.kwp > 0)
        && (Math.abs((+r.kwp || 0) - (+est.kwp || 0)) >= 0.05 || (r.kwp_de || null) !== (est.kwp_de || null));
      const c = Object.assign(contaKwp(kwpU > 0 ? +kwpU : null, membros), {uid: gs.reg, kwp_de: kwpDe || null,
        doNexus: base.length, semNexus: !doNexus, diverge, kwpCopia: r.kwp > 0 ? +r.kwp : null, kwpDeCopia: r.kwp_de || null, rotulos});
      cache[g.pid] = c;
      return c;
    }
    // só esta usina por cima do Nexus (a pendência do kWp recusado) e com as que vão no Salvar (o que a tela mostra)
    function contaSo(g) { return contaDe(g, new Set([g.pid]), memo().contaSo); }
    function contaDo(g) { const M = memo(); return contaDe(g, new Set([...M.vai, g.pid]), M.conta); }

    // ── desenho ──
    function lazySelect(cls, tipo, valor, rotulo, extra) {
      return `<select class="cel ${cls}" data-lazy="${tipo}"${extra || ''}><option value="${esc(valor || '')}" selected>${esc(rotulo)}</option></select>`;
    }
    // os rótulos cabem na célula: o kWp antes do código (o que corta é o fim) e, na usina do Fracttal, sem o cliente e a UF
    // (o cliente é o grupo da lista); o nome inteiro fica no title
    function rotuloReg(r) { return r ? `${r.nome} · ${r.kwp ? kw(r.kwp) + (r.kwp_de === 'contratual' ? ' (contratual)' : '') : 'sem kWp'}${r.codigo ? ' · ' + r.codigo : ''}` : 'Escolha'; }
    function rotuloUF(u) { if (!u) return 'Escolha a usina'; const m = meioDoNome(u.nome); return u.nome === u.codigo || !m ? u.codigo : `${m} · ${u.codigo}`; }
    function opcoesReg(valor) {
      const regs = S.ctx.reg.slice().sort((a, b) => String(a.nome).localeCompare(String(b.nome), 'pt-BR', {numeric: true}));
      return '<option value="">Escolha</option>' + regs.map(r => `<option value="${r.usina_id}"${r.usina_id === +valor ? ' selected' : ''}>${esc(rotuloReg(r))}</option>`).join('');
    }
    function opcoesUF(valor) {
      const g = {};
      S.ctx.ufs.forEach(u => (g[u.cliente || 'Sem cliente'] = g[u.cliente || 'Sem cliente'] || []).push(u));
      return '<option value="">Escolha a usina</option>' + Object.entries(g).sort((a, b) => a[0].localeCompare(b[0], 'pt-BR')).map(([c, us]) =>
        `<optgroup label="${esc(c)}">${us.slice().sort((a, b) => String(a.nome).localeCompare(String(b.nome), 'pt-BR', {numeric: true})).map(u =>
          `<option value="${esc(u.codigo)}"${u.codigo === valor ? ' selected' : ''}>${esc(rotuloUF(u))}</option>`).join('')}</optgroup>`).join('');
    }
    function htmlFontes() {
      const c = S.ctx, p = [];
      const nPend = Object.values(c.arvores).filter(a => a && a.pendente).length;
      p.push(`<span>Fracttal: <b>${c.ufs.length}</b> usinas da foto dos ativos${c.lido.foto ? ' de ' + esc(dataBR(c.lido.foto)) : ''}${nPend ? ` · <span class="amb">lendo no Fracttal de hoje a árvore de ${nPend} usina(s) fora da foto</span>` : ''}</span>`);
      p.push(`<span>Registro mestre: <b>${c.reg.length}</b> usinas${c.lido.registro ? ' · lido às ' + esc(hora(c.lido.registro)) : ''}</span>`);
      p.push(c.nexusBase == null ? '<span class="amb">Sem o Nexus nesta tela: dá para conferir as sugestões, não para salvar (abra pelo Nexus, que grava a estrutura das usinas)</span>'
        : c.nexusErro ? `<span class="red">O Nexus não respondeu: ${esc(c.nexusErro)}</span>`
          : `<span>Nexus: estrutura de <b>${Object.keys(c.nexus).length}</b> usinas lida${c.lido.nexus ? ' às ' + esc(hora(c.lido.nexus)) : ''}</span>`);
      if (!c.grava) p.push(`<span class="amb">Só leitura: ${esc(c.gravaPorQue || 'esta sessão não salva o de-para')}</span>`);
      c.avisos.forEach(a => p.push(`<span class="red">${esc(a)}</span>`));
      return `<div class="dp-fontes">${p.join('')}</div>`;
    }
    function htmlLegenda() {
      return '<div class="legenda"><span><span class="amostra"></span>tracejado = sugestão: confira e troque se preciso, depois clique em <b style="color:var(--color-text,#e9eef6)">Conferido</b></span>'
        + '<span><span class="amostra cheia"></span>cheio = conferido</span><span>A usina escolhida desce para as outras linhas da mesma usina da fonte. A cabine filtra pela usina do Fracttal e o inversor pela cabine. O kWp vem da usina do Registro mestre e é o que o Nexus vai gravar: a conta é a da usina inteira.</span></div>';
    }
    function colunas() {
      return '<th style="padding-left:22px">Inversor</th><th>Com corrente agora</th><th>Strings corretas</th><th>Usina no Registro mestre</th><th>kWp do inversor</th><th>Usina no Fracttal</th><th>Cabine</th><th>Inversor no Fracttal</th><th style="padding-right:22px">Situação</th>';
    }
    function htmlFaixa(g) {
      const c = contaDo(g), gs = S.gsel[g.pid] || {};
      if (!gs.reg) return '';
      const r = S.ctx.regPor[gs.reg] || {}, est = S.ctx.nexus[gs.reg] || {}, nome = esc(est.nome || r.nome || regNome(gs.reg));
      // as duas cópias do Registro diferentes (P-c): vale o do Nexus, que é quem grava
      const div = c && c.diverge ? `<span class="amb">a cópia do Registro desta tela diz ${c.kwpCopia ? kw(c.kwpCopia) + (c.kwpDeCopia === 'contratual' ? ' (contratual)' : '') : 'sem kWp'}; o Nexus grava com ${c.kwp ? kw(c.kwp) + (c.kwp_de === 'contratual' ? ' (contratual)' : '') : 'sem kWp'}: vale o do Nexus</span>` : '';
      // sem potência real nem contratual (D-c): o Nexus não mexe no kWp de ninguém, fica o de antes
      if (!c || !c.kwp) return `<tr class="dp-faixa"><td colspan="9"><div class="kwp-faixa"><span class="uf">${nome}</span><span class="amb">sem potência real nem contratual no Registro mestre: o Nexus não mexe no kWp desta usina (fica o de antes em cada inversor e cabine)</span>${div}</div></td></tr>`;
      const ufA = S.ctx.arvores[ufDoGrupo(g)];
      // as cabines desta usina da fonte: a identidade da cabine no Nexus (a CABN do pedido cai na "UG NN" da aba de mesmo número)
      const idents = [...new Set(g.invs.map(inv => { const s = S.sel[k(g, inv)] || {}; return !s.fora && s.cab && s.cab !== '-' ? cabIdent(est, s.cab) : ''; }).filter(Boolean))];
      const cabs = idents.filter(i => c.cab[i]).map(i => [c.rotulos[i] || i, c.cab[i]]);
      // o kWp de antes dos inversores sem strings sai do Registro antes da divisão (D-d): a soma da usina continua o Registro
      const conta = c.erro ? `<span class="red">${esc(c.erro)}</span>`
        : c.fixo > 0 ? `<span class="conta">(${kw(c.kwp)} − ${kw(c.fixo)} dos ${c.semStrings} sem strings corretas, que ficam com o kWp de antes) ÷ ${nf.format(c.total)} strings corretas = <b>${kw(c.por, 3)}</b> kWp por string</span>`
          : `<span class="conta">${kw(c.kwp)} ÷ ${nf.format(c.total)} strings corretas = <b>${kw(c.por, 3)}</b> kWp por string</span>${c.semStrings ? `<span class="amb">${c.semStrings} inversor(es) sem strings corretas e sem kWp de antes: ficam sem kWp</span>` : ''}`;
      return `<tr class="dp-faixa"><td colspan="9"><div class="kwp-faixa"><span class="uf">${nome}</span><span class="mono">${esc(est.codigo || r.codigo || '')}</span>
        <span>Registro mestre <b>${kw(c.kwp)}</b>${c.kwp_de === 'contratual' ? ' <span class="amb">(contratual: sem a potência real)</span>' : ''}</span>
        ${conta}
        ${cabs.map(([rot, x]) => `<span class="cab">${esc(rot)} <b>${kw(x.kwp)}</b> <span>${x.n} inv. · ${x.strings} strings</span></span>`).join('')}
        ${c.semNexus ? '<span class="amb">só com os inversores desta tela (sem o Nexus, a conta não tem o resto da usina)</span>'
          : c.doNexus && c.n > g.invs.length ? `<span>a conta tem os ${c.n} inversores da usina no Nexus</span>` : ''}
        ${div}${ufA && ufA.pendente ? '<span class="amb">lendo esta usina no Fracttal de hoje…</span>' : ''}${ufA && ufA.aviso ? `<span class="amb">${esc(ufA.aviso)}</span>` : ''}</div></td></tr>`;
    }
    // as chaves do cadastro da plataforma com o mesmo nome-base e o mesmo número da planta (P-j, 20/10): a Coração 1 e 2 da
    // `pv`, sem ligação hoje, têm na aba "Coração 1 (111)" e "Coração 2 (112)", que o Nexus não tem; a tela só oferecia
    // "Nova chave", que criava no Nexus uma chave paralela à da aba
    function chavesDoCadastro(g) {
      const n = numeroDaPlanta(g), bases = new Set([baseNome(g.usina || ''), baseNome(g.nome_api || '')].filter(b => b.length >= 3));
      if (!bases.size) return [];
      // o nome-base e o número de cada chave do cadastro, uma vez só (são 190 chaves, em cada cabeçalho de usina)
      return (S.ctx.cad || []).filter(c => {
        if (c.__base === undefined) Object.defineProperties(c, {__base: {value: baseNome(c.chave)}, __num: {value: num(c.chave)}});
        return bases.has(c.__base) && (n == null ? c.__num == null : c.__num === n);
      }).map(c => c.chave);
    }
    // as chaves que a lista oferece, pela chave normalizada (D-g: a "Assis Chateaubriand  Skid 1 (79)" da aba e a do Nexus
    // são UMA chave): a de hoje, as do Nexus para a usina do Registro e as do cadastro com o nome-base e o número da planta.
    // A "Nova chave" (o nome que a fonte manda, fora da aba) SAIU (2ª revisão final, 21/10/2026): ela nunca valia no lugar
    // da aba (os leitores não a conhecem), virava a chave da usina no Nexus e prendia os códigos do Fracttal nos inversores
    // dela; na Pharma 3 (851), escolhida a "Pharma 3 (851)" e depois a "Pharma 3" da aba, as 6 linhas ficavam com "já está
    // no Inversor 1.m (Pharma 3 (851)) no Nexus" para sempre. O Nexus também a recusa
    function opcoesDeChave(g) {
      const gs = S.gsel[g.pid] || {}, est = gs.reg ? S.ctx.nexus[gs.reg] : null;
      const opcoes = [], vistas = new Set();
      const poe = (c, nota) => { const n = nk(c); if (!n || vistas.has(n)) return; vistas.add(n); opcoes.push([c, nota]); };
      if (g.chave_cadastro) poe(g.chave_cadastro, ' (ligada hoje)');
      ((est && est.chaves) || []).forEach(c => poe(c.usina_supervisorio, ''));
      if (gs.chave) poe(gs.chave, '');
      chavesDoCadastro(g).forEach(c => poe(c, S.ctx.chaveUsina[nk(c)] ? '' : ' (da aba Equipamentos: o Nexus a traz da aba ao salvar)'));
      return opcoes;
    }
    // a chave que o Nexus não tem e o cadastro (a aba) também não: o Nexus recusa (não cria chave nova). Sem o cadastro lido
    // não dá para saber, e quem diz é o Nexus
    function chaveSemCadastro(g, chave) {
      const c = nk(chave);
      return !!c && !S.ctx.cadErro && !S.ctx.chaveUsina[c] && !S.ctx.cadPor[c] && c !== nk(g.chave_cadastro);
    }
    function htmlCabecalhoGrupo(g) {
      const gs = S.gsel[g.pid] || {}, lid = lidas(g), sv = g.sem_visao || (lid.length && lid.every(i => i.sem_visao || i.ativas == null));
      const opc = '<option value="">Escolha a chave</option>' + opcoesDeChave(g).map(([c, nota]) => `<option value="${esc(c)}"${nk(c) === nk(gs.chave) ? ' selected' : ''}>${esc(c)}${esc(nota)}</option>`).join('');
      const pend = pendenciasTela(g), sl = g.invs.length - lid.length, pp = precisaPonte(g);
      const avs = S.avisosG[g.pid] || [];
      return `<tr class="dp-grupo" data-g="${esc(g.pid)}"><td colspan="9"><div class="dp-gl"><b>${esc(g.usina)}</b>
        <label class="dp-ch">chave do cadastro <select class="cel j-chave${gs.chaveSug && gs.chave ? ' sug' : ''}${gs.chave ? '' : ' falta'}" data-g="${esc(g.pid)}" aria-label="Chave do cadastro de ${esc(g.usina)}">${opc}</select></label>
        <span>plant ${esc(g.plant_id)}${g.nome_api && g.nome_api !== g.usina ? ` · a API escreve “${esc(g.nome_api)}”` : ''} · ${lid.length} inversores na fonte${sl ? ` · ${sl} do cadastro sem leitura agora` : ''} · ${sv ? 'sem visão por string (as strings corretas vêm do cadastro)' : nf.format(g.strings_ativas || 0) + ' strings com corrente agora'}</span>
        ${pend.map(p => `<span class="dp-gp${/também está|é de |recusa/.test(p) ? ' red' : ''}">${esc(p)}</span>`).join('')}
        ${pp ? `<span class="dp-gp">ponte pendente: o Nexus já gravou, e a fonte segue ligada a “${esc(g.chave_cadastro || 'nenhuma chave')}”; o Salvar grava só a ponte para “${esc(pp.chave)}”</span>` : ''}
        ${avs.map(a => `<span class="dp-gp${foraDaAba(a) ? ' red' : ''}">Nexus: ${esc(a)}</span>`).join('')}</div></td></tr>`;
    }
    // o aviso do Nexus de que a chave gravada NÃO passou a valer no lugar da aba (D-b): os leitores seguem com a aba
    function foraDaAba(a) { return /n[ãa]o (?:vale|passou a valer) no lugar da aba/i.test(String(a || '')); }
    // `mx`: a usina mexida, calculada uma vez por usina no desenho (por linha eram 990 comparações da usina inteira)
    function htmlLinha(g, inv, mx) {
      const key = k(g, inv), s = S.sel[key] || {}, gs = S.gsel[g.pid] || {}, a = S.ctx.arvores[s.uf], u = S.ctx.ufPor[s.uf];
      const pend = pendencia(g, inv), sug = s.conf ? '' : ' sug', nx = invNexus(S.ctx, gs.chave, inv);
      const btnConf = `<button type="button" class="btn-conf" data-acao="conf"><svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>Conferido</button>`;
      const situ = s.fora ? `<span class="st sug">${inv.sem_leitura ? 'sem leitura agora: fica como está' : 'fica de fora'}</span> <button type="button" class="btn-conf desfaz" data-acao="volta" title="${inv.sem_leitura ? 'Mandar este inversor no de-para com o que estiver na linha' : 'Ligar este inversor de novo'}">${inv.sem_leitura ? 'incluir' : 'desfazer'}</button>`
        : soConferir(pend) ? `<span class="st amb">${esc(pend)}</span> ${btnConf}`
          : pend ? `<span class="st ${/repetido|já está/.test(pend) ? 'red' : 'amb'}">${esc(pend)}</span> <button type="button" class="btn-conf desfaz" data-acao="fora" title="O inversor não vai neste de-para (o trocado que a fonte ainda lista: “(old)”, “Cancelado”); o Nexus não mexe nele">deixar de fora</button>`
            : s.conf ? `<span class="st ok">conferido</span> <button type="button" class="btn-conf desfaz" data-acao="desfaz" title="Voltar a sugestão">desfazer</button>`
              : btnConf;
      // depois de ligado, o inversor aparece com o nome do Fracttal (Levi, 20/10: "Após ligar o de-para o nome do inversor
      // que aparece é o inversor no fractall"); o da fonte fica embaixo, pequeno
      const ligado = s.salvo && s.ativo && !(mx === undefined ? mexido(g) : mx) ? rotuloInversor(s.ativo) : '';
      const corrente = inv.sem_leitura ? '<span class="text-muted" title="Está no cadastro desta chave e não mandou leitura neste ciclo (parado, sem comunicação ou trocado)">sem leitura agora</span>'
        : inv.sem_visao ? '<span class="text-muted" title="A fonte não manda a corrente de cada string deste inversor">sem visão</span>'
          : inv.ativas == null ? '<span class="text-muted" title="Correntes reais, baixas demais para contar (manhã, fim de tarde, céu fechado)">pouca luz</span>'
            : `<b style="color:var(--color-text,#e9eef6)">${inv.ativas}</b>/${inv.total == null ? '—' : inv.total}`;
      const cad = inv.esp > 0 ? +inv.esp : null;
      const c = contaDo(g), v = c && c.inv[key] != null ? c.inv[key] : null, antes = !!(c && c.antes[key]);
      // o kWp de hoje: o do Nexus; o inversor que ele ainda não tem, numa chave que ele vai semear da aba (ou sem o Nexus
      // nesta tela), o da aba: na Coração 2 a tela mostra "250 → 812,5" (o Registro de 3.250 é só o da Coração 1: D-h)
      const estG = gs.reg ? S.ctx.nexus[gs.reg] : null, semeada = !estG || !(estG.chaves || []).some(x => nk(x.usina_supervisorio) === nk(gs.chave));
      const hoje = nx && nx.potencia_kwp != null ? +nx.potencia_kwp : !nx && semeada ? kwpDoCadastro(gs.chave, inv) : null;
      const r = gs.reg ? S.ctx.regPor[gs.reg] : null;
      const kwpTxt = v != null && !antes
        ? (hoje != null && Math.abs(hoje - v) >= 0.05 ? `<s title="kWp de hoje no cadastro">${kw(hoje, 1).replace(' kWp', '')} →</s> ${kw(v)}` : kw(v))
          + `<small>${s.strings} × ${kw(c.por, 3)}${hoje != null && Math.abs(hoje - v) < 0.05 ? ' · igual ao de hoje' : ''}</small>`
        : v != null ? `${kw(v)}<small>fica o de antes: ${!c.kwp ? 'sem kWp no Registro' : c.erro ? 'a usina não salva' : 'sem strings corretas'}</small>`
          : (gs.reg && c && !c.kwp ? '—<small>sem kWp no Registro (o Nexus não mexe)</small>' : hoje != null ? `${kw(hoje)}<small>o de hoje</small>` : '—');
      const cabs = a ? (a.cabines || []).map(x => ({codigo: canon(x.codigo), nome: rotuloCabine(x.codigo)})).concat((a.sem_cabine || []).length ? [{codigo: '-', nome: 'Sem cabine no Fracttal'}] : []) : [];
      const ativos = a && s.cab ? invsDaArvore(a).filter(i => i.cab === s.cab) : [];
      const lendo = s.uf && !a;
      const dica = cad ? 'cadastro ' + cad : s.strDe === 'leitura' ? 'da leitura de agora' : 'sem cadastro';
      return `<tr class="dp-row${s.fora ? ' fora' : ''}" data-k="${esc(key)}" data-g="${esc(g.pid)}">
        <td style="padding-left:22px"><span class="dp-inv">${esc(ligado || inv.nome || inv.nome_api)}<small>${ligado ? 'na fonte ' + esc([inv.nome_api, inv.nome].find(n => n && n !== ligado) || inv.nome_api || inv.nome) : inv.sem_leitura ? 'do cadastro · ' + esc(inv.nome_api) : 'id ' + esc(inv.id) + (inv.nome_api && inv.nome_api !== inv.nome ? ' · ' + esc(inv.nome_api) : '')}</small></span></td>
        <td style="white-space:nowrap;color:var(--color-neutral-300,#c3cad7);font-variant-numeric:tabular-nums">${corrente}</td>
        <td><input class="cel j-str${sug}${s.strings > 0 ? '' : ' falta'}" type="number" min="1" max="99" value="${s.strings == null ? '' : esc(s.strings)}" aria-label="Strings corretas"><span class="dp-hint${(cad && cad !== s.strings) || s.strDe === 'leitura' ? ' amb' : ''}">${dica}</span></td>
        <td class="w-reg">${lazySelect('j-reg' + (gs.regSug ? ' sug' : '') + (gs.reg ? '' : ' falta'), 'reg', gs.reg || '', gs.reg ? rotuloReg(r) : 'Escolha', ` aria-label="Usina no Registro mestre" title="${esc(r ? rotuloReg(r) : '')}"`)}</td>
        <td><span class="dp-kwp">${kwpTxt}</span></td>
        <td class="w-uf">${lazySelect('j-uf' + sug + (s.uf ? '' : ' falta'), 'uf', s.uf || '', s.uf ? rotuloUF(u || {nome: s.uf, codigo: s.uf}) : 'Escolha a usina', ` aria-label="Usina no Fracttal" title="${esc(u ? u.nome + ' · ' + u.codigo : s.uf || '')}"`)}</td>
        <td class="w-cab"><select class="cel j-cab${sug}${s.cab ? '' : ' falta'}" aria-label="Cabine"${a ? '' : ' disabled'}><option value="">${a ? 'Escolha' : lendo ? 'lendo…' : '—'}</option>${cabs.map(x => `<option value="${esc(x.codigo)}"${x.codigo === s.cab ? ' selected' : ''}>${esc(x.nome)}</option>`).join('')}</select>${a && a.erro ? `<span class="dp-hint amb" title="${esc(a.erro)}">árvore não veio</span>` : ''}</td>
        <td class="w-at"><select class="cel j-at${sug}${s.ativo ? '' : ' falta'}" aria-label="Inversor no Fracttal"${s.cab ? '' : ' disabled'}><option value="">${s.cab ? (ativos.length ? 'Escolha' : 'sem inversor nesta cabine') : '—'}</option>${ativos.map(i => `<option value="${esc(i.codigo)}"${i.codigo === s.ativo ? ' selected' : ''}>${esc(i.nome)}</option>`).join('')}</select><span class="dp-hint">${s.ativo ? esc(s.ativo) : ''}</span></td>
        <td class="situ" style="padding-right:18px;max-width:170px">${situ}</td></tr>`;
    }
    function htmlCorpoGrupo(g) { const mx = mexido(g); return htmlCabecalhoGrupo(g) + htmlFaixa(g) + g.invs.map(inv => htmlLinha(g, inv, mx)).join(''); }
    // um <tbody> por usina da fonte: a mudança numa usina redesenha só ela e as que a conta ou o código alcançam
    function htmlTabela(grupos) {
      return `<div style="overflow-x:auto"><table class="table dp-tab"><thead><tr>${colunas()}</tr></thead>${grupos.map(g => `<tbody data-gt="${esc(g.pid)}">${htmlCorpoGrupo(g)}</tbody>`).join('')}</table></div>`;
    }
    function htmlDoGrupo(g) { return op.resumo ? htmlResumoGrupo(g) : htmlCorpoGrupo(g); }
    function situacaoGrupo(g) {
      const pg = pendenciasTela(g), pl = g.invs.filter(inv => pendencia(g, inv)).length;
      if (pg.length || pl) return {cls: 'amb', txt: pl ? `${pl} com pendência` : pg[0]};
      if (pronto(g)) return {cls: 'ok', txt: 'pronta para salvar'};
      if (precisaPonte(g)) return {cls: 'amb', txt: 'ponte pendente: o Salvar grava só a ponte'};
      const vao = g.invs.filter(inv => !(S.sel[k(g, inv)] || {}).fora);
      const nconf = vao.filter(inv => (S.sel[k(g, inv)] || {}).conf).length, nsalvo = vao.filter(inv => (S.sel[k(g, inv)] || {}).salvo).length;
      if (vao.length && nsalvo === vao.length && nconf === vao.length) return {cls: 'ok', txt: 'ligada e conferida'};
      return {cls: 'sug', txt: `${vao.length - nconf} sugeridos a conferir`};
    }
    // a Base · De-para: UMA USINA POR LINHA, e o Abrir dá a mesma tabela por inversor
    function htmlResumoGrupo(g) {
        const gs = S.gsel[g.pid] || {}, r = gs.reg ? S.ctx.regPor[gs.reg] : null, uf = S.ctx.ufPor[ufDoGrupo(g)];
        const lid = lidas(g), sl = g.invs.length - lid.length;
        const ligados = lid.filter(inv => (S.sel[k(g, inv)] || {}).salvo).length;
        const sug = lid.filter(inv => { const s = S.sel[k(g, inv)] || {}; return s.ativo && !s.salvo; }).length;
        const vao = g.invs.filter(inv => !(S.sel[k(g, inv)] || {}).fora);
        const str = vao.reduce((t, inv) => t + (+(S.sel[k(g, inv)] || {}).strings || 0), 0), cad = vao.reduce((t, inv) => t + (inv.esp > 0 ? +inv.esp : 0), 0);
        // a soma só dos inversores que têm kWp na conta: nenhum (sem strings corretas, a Cambé) é "—", nunca "0,0 kWp"
        const c = contaDo(g), comKwp = c ? vao.filter(inv => c.inv[k(g, inv)] != null) : [];
        const kwpG = comKwp.length ? comKwp.reduce((t, inv) => t + c.inv[k(g, inv)], 0) : null;
        // o kWp da usina mostrado é o do Nexus quando lido (P-c); a cópia da plataforma só sem ele
        const kwpU = c ? c.kwp : (r && r.kwp), kwpDe = c ? c.kwp_de : (r && r.kwp_de);
        const st = situacaoGrupo(g), aberto = S.abertos.has(g.pid);
        const naChave = gs.chave ? (nk(gs.chave) === nk(g.chave_cadastro) ? 'ligada hoje' : precisaPonte(g) ? 'ponte pendente' : 'sugestão: a ponte grava ao salvar') : 'falta';
        return `<tr class="dp-res" data-g="${esc(g.pid)}">
          <td class="esq" style="padding-left:22px"><b style="color:var(--color-text,#e9eef6)">${esc(g.usina)}</b><small>plant ${esc(g.plant_id)}${g.nome_api && g.nome_api !== g.usina ? ' · a API escreve “' + esc(g.nome_api) + '”' : ''}</small></td>
          <td>${gs.chave ? esc(gs.chave) : '—'}<small>${naChave}</small></td>
          <td>${r ? esc(r.nome) : '—'}<small>${r ? esc(r.codigo || 'sem código') + (kwpU ? ' · ' + kw(kwpU) + (kwpDe === 'contratual' ? ' (contratual)' : '') : ' · sem kWp') : 'falta'}</small></td>
          <td>${uf ? esc(uf.nome) : '—'}<small>${uf ? esc(uf.codigo) : 'falta'}</small></td>
          <td style="font-variant-numeric:tabular-nums"><b style="color:var(--color-text,#e9eef6)">${ligados}</b> / ${lid.length}<small>${sug ? sug + ' sugerido(s)' : ligados ? 'gravados no Nexus' : ''}${sl ? `${sug || ligados ? ' · ' : ''}${sl} sem leitura agora` : ''}</small></td>
          <td style="font-variant-numeric:tabular-nums">${str ? nf.format(str) : '—'}<small>${cad ? 'cadastro ' + nf.format(cad) : 'sem cadastro'}</small></td>
          <td><span class="dp-kwp">${kwpG != null ? kw(kwpG) : '—'}</span></td>
          <td><span class="st ${st.cls}">${esc(st.txt)}</span></td>
          <td style="padding-right:22px"><button type="button" class="dp-abrir" data-dp-abrir="${esc(g.pid)}" aria-expanded="${aberto}">${aberto ? 'Fechar' : 'Abrir'}</button></td></tr>`
          + (aberto ? `<tr class="dp-aberta"><td colspan="9">${htmlTabela([g])}</td></tr>` : '');
    }
    function htmlResumo(grupos) {
      const linhas = grupos.map(g => `<tbody data-gt="${esc(g.pid)}">${htmlResumoGrupo(g)}</tbody>`).join('');
      return `<div style="overflow-x:auto"><table class="table dp-tab"><thead><tr><th style="padding-left:22px;text-align:left">Usina na fonte</th><th>Chave do cadastro</th><th>Usina no Registro mestre</th><th>Usina no Fracttal</th><th>Inversores<br>ligados / na fonte</th><th>Strings corretas</th><th>kWp</th><th>Situação</th><th style="padding-right:22px"><span style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)">Ação</span></th></tr></thead>${linhas}</table></div>`;
    }
    function contaBloco(gs) {
      const pend = gs.filter(g => situacaoGrupo(g).cls === 'amb').length, ok = gs.filter(g => situacaoGrupo(g).txt === 'ligada e conferida').length;
      return `${gs.length} usina(s) · ${ok} ligada(s) e conferida(s)${pend ? ` · <span style="color:var(--dp-amb)">${pend} com pendência</span>` : ''}`;
    }
    function html(filtro) {
      _memo = null;
      S.filtro = filtro || null;
      if (!S.ativo) return '';
      const grupos = filtro ? S.grupos.filter(filtro) : S.grupos;
      if (S.carregando) return `<div class="gc-dp" data-dp-raiz="1"><div class="dp-carrega">${esc(S.etapa || 'Carregando…')}</div></div>`;
      if (!S.grupos.length) return '<div class="gc-dp" data-dp-raiz="1"><div class="dp-carrega">Esta fonte não mandou o resumo por inversor neste ciclo: espere a próxima leitura (5 min) e entre de novo.</div></div>';
      const vazio = grupos.length ? '' : '<div class="dp-carrega">Nenhuma usina com esse filtro.</div>';
      if (!op.resumo) return `<div class="gc-dp" data-dp-raiz="1">${htmlFontes()}${htmlLegenda()}${htmlTabela(grupos)}${vazio}</div>`;
      // a Base: um bloco por fonte (a conta da API PV), uma usina por linha
      const blocos = (op.blocos || [{id: null, nome: ''}]).map(b => {
        const gs = grupos.filter(g => b.id == null || g.fonte === b.id);
        if (!gs.length) return '';
        return `<section class="dp-bloco" aria-label="${esc(b.nome)}"><div class="dp-bcab"><span class="dp-bnome">${esc(b.nome)}</span><span class="dp-bconta" data-bloco="${esc(b.id == null ? '' : b.id)}">${contaBloco(gs)}</span></div>${htmlResumo(gs)}</section>`;
      }).join('');
      return `<div class="gc-dp" data-dp-raiz="1"><section class="dp-bloco">${htmlFontes()}${htmlLegenda()}</section>${blocos}${vazio}</div>`;
    }

    // ── a barra do rodapé (como a do Criar OS) ──
    function barra() {
      if (!D) return;
      let b = D.getElementById('gc-dpbar');
      const mostra = S.ativo && !S.carregando && (op.resumo ? (S.abertos.size || S.grupos.some(mexido) || S.resultado) : true);
      if (!b) { if (!mostra) return; b = D.createElement('div'); b.id = 'gc-dpbar'; b.setAttribute('role', 'region'); b.setAttribute('aria-label', 'Modo de-para'); D.body.appendChild(b); }
      b.style.cssText = `position:fixed;left:0;right:0;bottom:0;z-index:400;align-items:center;gap:14px;flex-wrap:wrap;background:var(--color-surface,#161d30);color:var(--color-text,#e9eef6);border-top:2px solid var(--color-accent,#a3d900);padding:12px 28px;font-size:13px;box-shadow:0 -6px 24px rgba(0,0,0,.4);display:${mostra ? 'flex' : 'none'}`;
      if (!mostra) { if (op.aoBarra) op.aoBarra(); return; }
      const linhas = S.grupos.flatMap(g => g.invs.map(inv => ({g, inv})));
      const fora = linhas.filter(x => (S.sel[k(x.g, x.inv)] || {}).fora).length;
      const pend = linhas.filter(x => pendencia(x.g, x.inv)).length, conf = linhas.filter(x => !pendencia(x.g, x.inv) && (S.sel[k(x.g, x.inv)] || {}).conf).length;
      const strings = linhas.reduce((t, x) => { const s = S.sel[k(x.g, x.inv)] || {}; return t + (s.fora ? 0 : +s.strings || 0); }, 0);
      const sugeridos = linhas.length - conf - pend - fora, prontos = S.grupos.filter(pronto), presos = S.grupos.filter(g => mexido(g) && !pronto(g));
      const soPonte = S.grupos.filter(g => !pronto(g) && precisaPonte(g));
      const semNexus = S.ctx.nexusBase == null, grava = !!S.ctx.grava;
      const tem = prontos.length || soPonte.length;
      const tit = semNexus ? 'Abra pelo Nexus para salvar: quem grava a estrutura das usinas é o Nexus'
        : !grava ? 'Só leitura: ' + (S.ctx.gravaPorQue || 'esta sessão não salva o de-para')
          : tem ? 'Grava no Nexus as usinas que você mexeu e que não têm pendência; depois, a ponte da fonte' : 'Nada para salvar: mexa ou confira uma usina sem pendência';
      let res = '';
      if (S.salvando) res = `<div style="flex-basis:100%;color:var(--color-neutral-300,#c3cad7)">${esc(S.etapaSalvar || 'Gravando…')}</div>`;
      else if (S.resultado) res = htmlResultado(S.resultado);
      b.innerHTML = `${res}<span style="flex:1;color:var(--color-neutral-300,#c3cad7)"><b style="color:var(--color-text,#e9eef6)">${conf}</b> de ${linhas.length} inversores conferidos · <b style="color:var(--color-text,#e9eef6)">${nf.format(strings)}</b> strings esperadas${sugeridos ? ` · ${sugeridos} sugeridos a conferir` : ''}${fora ? ` · ${fora} de fora` : ''}${pend ? ` · <span class="amb">${pend} com pendência</span>` : ''}${prontos.length ? ` · <b style="color:var(--color-text,#e9eef6)">${prontos.length}</b> usina(s) para salvar` : ''}${soPonte.length ? ` · <span class="amb">${soPonte.length} ponte(s) pendente(s)</span>` : ''}${presos.length ? ` · <span class="amb">${presos.length} mexida(s) com pendência fica(m) de fora</span>` : ''}${!grava && !semNexus ? ` · <span class="amb">só leitura: ${esc(S.ctx.gravaPorQue || '')}</span>` : ''}</span>
        <button type="button" class="lnk" id="gc-dp-conf-todos"${sugeridos ? '' : ' hidden'}>conferir todos os sugeridos</button>
        <button type="button" class="lnk" id="gc-dp-descartar">descartar</button>
        <button type="button" class="salvar" id="gc-dp-salvar"${!semNexus && grava && tem && !S.salvando ? '' : ' disabled'} title="${esc(tit)}"><svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true"><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>Salvar de-para</button>`;
      if (op.aoBarra) op.aoBarra();
    }
    // os avisos do Nexus da usina (P-k): o que ele diz de cada uma vai junto dela, e o "não vale no lugar da aba" em destaque
    function htmlAvisos(avs) {
      return avs && avs.length ? `<ul class="dp-res-lista" style="margin:2px 0 4px">${avs.map(a => foraDaAba(a)
        ? `<li><b class="red">não vale no lugar da aba:</b> ${esc(a)}</li>` : `<li class="amb">${esc(a)}</li>`).join('')}</ul>` : '';
    }
    function htmlResultado(res) {
      const itens = [];
      res.nexus.forEach(x => {
        const u = esc(x.g.usina);
        if (!x.ok && x.semSaber) itens.push(`<li><span class="red">${u}: não se sabe se o Nexus gravou</span> — ${esc(x.motivo)}.</li>`);
        else if (!x.ok && x.culpada) itens.push(`<li><span class="red">${u}: o Nexus recusou esta usina</span> — ${esc(x.motivo)}. Nada desta usina foi gravado, e a ponte não foi tentada; as outras do mesmo pedido foram de novo sem ela.</li>`);
        else if (!x.ok) itens.push(`<li><span class="red">${u}: o Nexus NÃO gravou</span> — ${esc(x.motivo)}. Nada desta usina foi gravado, e a ponte não foi tentada.</li>`);
        else if (x.ponte === 'falhou') itens.push(`<li><span class="amb">${u}: o Nexus gravou a estrutura, a ponte NÃO</span> — ${esc(x.ponteMotivo)}. A fonte segue ligada a “${esc(x.g.chave_cadastro || 'nenhuma chave')}” até a ponte ser gravada: o próximo Salvar grava só a ponte (sem ir ao Nexus de novo), ou ligue no editor da ponte (Base · De-para · Diagnóstico).${htmlAvisos(x.avisos)}</li>`);
        else itens.push(`<li><span class="ok">${u}: gravada no Nexus</span>${x.tarde ? ' (o Nexus respondeu tarde, mas o selo da usina mudou: gravou)' : ''}${x.ponte === 'ok' ? ` e a ponte da fonte para “${esc(x.chave)}”` : ''}.${htmlAvisos(x.avisos)}</li>`);
      });
      (res.ponte || []).forEach(x => itens.push(x.ok ? `<li><span class="ok">${esc(x.g.usina)}: a ponte da fonte para “${esc(x.chave)}” gravada</span> (a estrutura já estava no Nexus).</li>`
        : `<li><span class="amb">${esc(x.g.usina)}: a ponte de novo NÃO</span> — ${esc(x.motivo)}. A fonte segue ligada a “${esc(x.g.chave_cadastro || 'nenhuma chave')}”.</li>`));
      res.avisos.forEach(a => itens.push(foraDaAba(a) ? `<li><b class="red">não vale no lugar da aba:</b> ${esc(a)}</li>` : `<li class="amb">${esc(a)}</li>`));
      const ok = res.nexus.filter(x => x.ok).length, falhou = res.nexus.length - ok, pf = res.nexus.filter(x => x.ponte === 'falhou').length;
      const np = (res.ponte || []).length, pOk = (res.ponte || []).filter(x => x.ok).length;
      // as chaves gravadas que NÃO valem no lugar da aba (D-b): os leitores seguem com a aba nelas, e a manchete diz (âmbar),
      // em vez do "Vale no tempo real em até 1 min" verde da Pharma II com o Full O&M diferente
      const nao = res.naoMarcadas || [], naoTxt = nao.length ? `; ${nao.length} chave(s) NÃO valem no lugar da aba (${nao.slice(0, 4).map(c => '“' + esc(c) + '”').join(', ')}${nao.length > 4 ? ' e mais' : ''}): nelas os leitores seguem com a aba, e o tempo real não muda` : '';
      const cab = falhou || pf || np - pOk ? `<b class="${falhou ? 'red' : 'amb'}">Gravado em parte:</b> ${ok} de ${res.nexus.length} usina(s) no Nexus${pf ? `, ${pf} sem a ponte` : ''}${np ? `; ponte pendente: ${pOk} de ${np} gravada(s)` : ''}${naoTxt}.`
        : res.nexus.length && nao.length ? `<b class="amb">Gravado no Nexus:</b> ${ok} usina(s) (${res.mudancas} mudança(s))${pOk ? ` e ${pOk} ponte(s) pendente(s)` : ''}${naoTxt}. O que vale no lugar da aba entra no tempo real em até 1 min; a ponte, na próxima leitura da lista de usinas (até 5 min).`
        : res.nexus.length ? `<b class="ok">De-para salvo:</b> ${ok} usina(s) no Nexus (${res.mudancas} mudança(s))${pOk ? ` e ${pOk} ponte(s) pendente(s)` : ''}. Vale no tempo real em até 1 min (a plataforma relê a visão do Nexus); a ponte, na próxima leitura da lista de usinas (até 5 min).`
          : `<b class="ok">Ponte gravada:</b> ${pOk} usina(s). Vale na próxima leitura da lista de usinas (até 5 min).`;
      return `<div style="flex-basis:100%;display:flex;gap:12px;align-items:flex-start"><div style="flex:1">${cab}<ul class="dp-res-lista">${itens.join('')}</ul></div><button type="button" class="lnk" id="gc-dp-fechar-res" aria-label="Fechar o resultado">fechar</button></div>`;
    }

    // `pids`: só as usinas que a mudança alcança, trocando o <tbody> delas na tela; sem `pids` (ou sem a tabela na tela), a
    // tela inteira. Medido na `pv` de 20/10 (120 usinas, 990 inversores): a tabela inteira são 2,7 MB de HTML e ~290 ms só
    // para montar, a cada clique; uma usina, poucos KB
    function desenhar(pids) {
      _memo = null;
      const raiz = pids && D && !S.carregando ? D.querySelector('.gc-dp[data-dp-raiz]') : null;
      if (raiz && raiz.querySelector('tbody[data-gt]')) {
        const esc2 = v => (G.CSS && G.CSS.escape) ? G.CSS.escape(v) : v;
        [...new Set(pids)].forEach(pid => { const el = raiz.querySelector(`tbody[data-gt="${esc2(pid)}"]`), g = S.porPid[pid]; if (el && g) el.innerHTML = htmlDoGrupo(g); });
        const f = raiz.querySelector('.dp-fontes');
        if (f) f.outerHTML = htmlFontes();
        raiz.querySelectorAll('.dp-bconta[data-bloco]').forEach(el => { const b = el.getAttribute('data-bloco');
          el.innerHTML = contaBloco(S.grupos.filter(g => (!b || g.fonte === b) && (!S.filtro || S.filtro(g)))); });
        barra();
        return;
      }
      if (op.redesenhar) op.redesenhar(); else if (op.raizId && D) { const el = D.getElementById(op.raizId); if (el) el.innerHTML = html(S.filtro); }
      barra();
    }
    // as usinas que uma mudança na usina `g` alcança: ela, as da mesma usina do Registro (a conta do kWp é da usina
    // inteira), as da mesma chave e as que têm um dos códigos do Fracttal que ela tinha ou passou a ter (o "repetido")
    function fotoDoGrupo(g) {
      const gs = S.gsel[g.pid] || {};
      return {reg: gs.reg, chave: nk(gs.chave), cods: g.invs.map(inv => (S.sel[k(g, inv)] || {}).ativo).filter(Boolean)};
    }
    function alcance(g, antes) {
      const d = fotoDoGrupo(g), regs = new Set([antes.reg, d.reg].filter(Boolean)), chaves = new Set([antes.chave, d.chave].filter(Boolean));
      const cods = new Set(antes.cods.concat(d.cods));
      return S.grupos.filter(h => { const hs = S.gsel[h.pid] || {};
        return h === g || regs.has(hs.reg) || chaves.has(nk(hs.chave)) || h.invs.some(inv => cods.has((S.sel[k(h, inv)] || {}).ativo)); }).map(h => h.pid);
    }

    // ── as mudanças ──
    async function aplicaUF(g, uf, keyAlterada, antes) {
      antes = antes || fotoDoGrupo(g);
      if (uf && !S.ctx.arvores[uf]) { S.lendoArv[uf] = 1; g.invs.forEach(inv => { S.sel[k(g, inv)] = Object.assign({}, S.sel[k(g, inv)], {uf, cab: '', ativo: '', sug: false, conf: false}); }); desenhar(alcance(g, antes)); await lerArvore(uf); delete S.lendoArv[uf]; }
      const a = S.ctx.arvores[uf], gs = S.gsel[g.pid], chaveAntes = nk(gs.chave);
      gs.metodo = a ? acertos(g, a).metodo : 'a';
      g.invs.forEach(inv => {
        const kk = k(g, inv), antes = S.sel[kk] || {}, at = sugereInversor(g, inv, a, gs.metodo);
        let cab = at ? at.cab : '';
        if (!at && a && (a.cabines || []).length === 1) cab = canon(a.cabines[0].codigo);
        // as strings (e de onde vieram) e o "de fora" ficam: a usina do Fracttal não muda o inversor da fonte
        S.sel[kk] = {uf: uf || '', cab, ativo: at ? at.codigo : '', strings: antes.strings, strDe: antes.strDe, fora: antes.fora,
          conf: false, sug: kk !== keyAlterada, salvo: false};
      });
      if (gs.regSug) {
        const r = sugereRegistro(g, uf, S.ctx);
        gs.reg = r ? r.uid : gs.reg;
        if (gs.reg && !S.ctx.nexus[gs.reg]) await lerNexus([], [gs.reg]);
        if (gs.chaveSug) { const c = gs.reg ? sugereChave(g, gs.reg, S.ctx) : null; gs.chave = c ? c.chave : gs.chave; }
      }
      if (nk(gs.chave) !== chaveAntes) refazSemLeitura(g);
      desenhar(alcance(g, antes));
    }
    async function aplicaReg(g, uid, antes) {
      const gs = S.gsel[g.pid], chaveAntes = nk(gs.chave);
      antes = antes || fotoDoGrupo(g);
      gs.reg = uid || null; gs.regSug = false;
      if (uid && !S.ctx.nexus[uid]) { desenhar(alcance(g, antes)); await lerNexus([], [uid]); }
      if (gs.chaveSug && !g.chave_cadastro) { const c = uid ? sugereChave(g, uid, S.ctx) : null; gs.chave = c ? c.chave : ''; }
      if (nk(gs.chave) !== chaveAntes) refazSemLeitura(g);
      desenhar(alcance(g, antes));
    }
    // as mudanças da tela (os eventos chamam estas; os testes também)
    function mudarChave(pid, chave) {
      const g = S.porPid[pid]; if (!g) return;
      const antes = fotoDoGrupo(g), gs = S.gsel[g.pid], troca = nk(gs.chave) !== nk(chave);
      gs.chave = chave; gs.chaveSug = false;
      // a chave nova traz os inversores do cadastro dela que não leram agora (P-m)
      if (troca) refazSemLeitura(g);
      desenhar(alcance(g, antes));
    }
    async function mudar(key, cls, valor) {
      const g = S.porPid[String(key).split('|')[0]];
      if (!g || !S.sel[key]) return;
      const antes = fotoDoGrupo(g);
      const s = S.sel[key] = Object.assign({}, S.sel[key], {sug: false, conf: false});
      if (cls === 'j-uf') return aplicaUF(g, valor, key, antes);
      if (cls === 'j-reg') return aplicaReg(g, valor ? +valor : null, antes);
      if (cls === 'j-cab') { s.cab = valor; s.ativo = ''; }
      if (cls === 'j-at') s.ativo = valor;
      if (cls === 'j-str') { s.strings = valor === '' || valor == null ? null : +valor; s.strDe = 'tela'; }
      desenhar(alcance(g, antes));
    }
    function conferir(key, conf) {
      const g = S.porPid[String(key).split('|')[0]];
      if (!g || !S.sel[key]) return;
      const antes = fotoDoGrupo(g);
      S.sel[key] = Object.assign({}, S.sel[key], {conf, sug: !conf});
      desenhar(alcance(g, antes));
    }
    function deixarDeFora(key, fora) {
      const g = S.porPid[String(key).split('|')[0]];
      if (!g || !S.sel[key]) return;
      const antes = fotoDoGrupo(g);
      S.sel[key] = Object.assign({}, S.sel[key], {fora, conf: false});
      desenhar(alcance(g, antes));
    }
    function conferirTodos() {
      _memo = null;
      S.grupos.forEach(g => g.invs.forEach(inv => { const s = S.sel[k(g, inv)] || {}; if (!s.fora && !pendencia(g, inv)) S.sel[k(g, inv)] = Object.assign({}, s, {conf: true, sug: false}); }));
      desenhar();
    }
    function aoMudar(ev) {
      if (!S.ativo) return;
      const t = ev.target;
      if (t.classList.contains('j-chave')) { mudarChave(t.getAttribute('data-g'), t.value); return; }
      const tr = t.closest && t.closest('tr.dp-row');
      if (!tr) return;
      const key = tr.getAttribute('data-k'), cls = [...t.classList].find(c => c.indexOf('j-') === 0);
      if (!cls) return;
      Promise.resolve(mudar(key, cls, t.value)).then(() => foca(key, cls));
    }
    function foca(key, cls) {
      if (!D || !cls) return;
      const el = D.querySelector(`tr.dp-row[data-k="${(G.CSS && G.CSS.escape) ? G.CSS.escape(key) : key}"] .${cls}`);
      if (el) try { el.focus({preventScroll: true}); } catch (e) { el.focus(); }
    }
    function encheLazy(t) {
      if (!t || t.getAttribute('data-cheio') === '1') return;
      const tipo = t.getAttribute('data-lazy'), v = t.value;
      if (tipo === 'reg') t.innerHTML = opcoesReg(v);
      else if (tipo === 'uf') t.innerHTML = opcoesUF(v);
      else return;
      t.value = v;
      t.setAttribute('data-cheio', '1');
    }
    function aoClicar(ev) {
      if (!S.ativo) return;
      const t = ev.target, alvo = t.closest ? t : null;
      if (!alvo) return;
      const bc = t.closest('.gc-dp .btn-conf');
      if (bc) {
        const tr = bc.closest('tr.dp-row'), acao = bc.getAttribute('data-acao');
        if (tr) { if (acao === 'fora' || acao === 'volta') deixarDeFora(tr.getAttribute('data-k'), acao === 'fora'); else conferir(tr.getAttribute('data-k'), acao === 'conf'); }
        return;
      }
      const ab = t.closest('[data-dp-abrir]');
      if (ab) { const pid = ab.getAttribute('data-dp-abrir'); if (S.abertos.has(pid)) S.abertos.delete(pid); else S.abertos.add(pid); desenhar([pid]); return; }
      if (t.closest('#gc-dp-conf-todos')) { conferirTodos(); return; }
      if (t.closest('#gc-dp-descartar')) { descartar(); return; }
      if (t.closest('#gc-dp-fechar-res')) { S.resultado = null; barra(); return; }
      if (t.closest('#gc-dp-salvar')) { salvar(); return; }
    }
    function descartar() {
      S.resultado = null;
      if (op.aoDescartar && op.aoDescartar() === false) return;
      S.grupos.forEach(g => {
        const antes = nk((S.gsel[g.pid] || {}).chave);
        S.gsel[g.pid] = Object.assign({}, S.gbase[g.pid]);
        if (nk(S.gsel[g.pid].chave) !== antes) refazSemLeitura(g);      // as linhas "sem leitura agora" da chave de antes
        g.invs.forEach(inv => { if (S.base[k(g, inv)]) S.sel[k(g, inv)] = Object.assign({}, S.base[k(g, inv)]); });
      });
      desenhar();
    }
    if (D && !G.__gcDpOuvintes) {
      G.__gcDpOuvintes = true;
      D.addEventListener('change', ev => { const i = G.__gcDpAtual; if (i) i._aoMudar(ev); });
      D.addEventListener('click', ev => { const i = G.__gcDpAtual; if (i) i._aoClicar(ev); });
      // as listas grandes (258 usinas do Registro, 150 do Fracttal) só ganham as opções quando a pessoa abre: com uma linha
      // por inversor (a `pv` tem 840), desenhar todas as opções em todas as linhas travaria a tela
      ['mousedown', 'focusin', 'keydown'].forEach(tipo => D.addEventListener(tipo, ev => { const t = ev.target; if (t && t.matches && t.matches('.gc-dp select[data-lazy]')) encheLazy(t); }, true));
    }

    // ── salvar: primeiro o Nexus, depois a ponte ──
    function itensDaUsina(uid, prontos) {
      const porChave = {};
      prontos.filter(g => S.gsel[g.pid].reg === uid).forEach(g => {
        const gs = S.gsel[g.pid], c = nk(gs.chave);
        // a chave com a grafia do Nexus (D-g); o item leva a da tela para a ponte
        const it = porChave[c] = porChave[c] || {usina_supervisorio: chaveParaNexus(gs.chave), usina_id: uid,
          selo: (S.ctx.nexus[uid] || {}).selo || '', inversores: [], grupos: []};
        it.grupos.push(g);
        g.invs.forEach(inv => { const s = S.sel[k(g, inv)];
          if (s.fora) return;
          // o `nome` do cadastro (P-i): o inversor que o Nexus cria nasce com o "Equipamento" da aba, a coluna do BD (a
          // decisão 5); vazio, o Nexus usa o da aba para a (chave, Equipamento Supervisório) e só então o do código
          it.inversores.push({equipamento_supervisorio: esupDe(g, inv, gs.chave), nome: nomeDoCadastro(S.ctx, gs.chave, inv),
            strings: +s.strings, cabine_codigo_fracttal: s.cab && s.cab !== '-' ? s.cab : '', codigo_fracttal: s.ativo,
            conferido: !!s.conf}); });
      });
      return Object.values(porChave);
    }
    function lotes(prontos) {
      // todas as chaves de uma usina no MESMO pedido (o selo é da usina: um 2º pedido para ela levaria 409), até 50 chaves; e
      // as usinas que trocam códigos do Fracttal entre si também juntas (2ª revisão final, 21/10/2026): o Nexus confere "um
      // código num inversor vivo só" depois de aplicar, mas por PEDIDO. A THPN-PHS100 é um site só para as Pharmas 2, 3 e 4,
      // e a troca dos blocos entre a Pharma 2 e a 3 (um Salvar antigo com 3.x na 2 e 2.x na 3) em dois pedidos era recusada
      // nos dois (409), a cada Salvar, para sempre. Saiu o pedido só da usina lida no Fracttal de hoje (a fora da foto): a
      // recusa do código fora da dimensão volta com a culpada (D-f), e o resto vai de novo sem ela
      const uids = [...new Set(prontos.map(g => S.gsel[g.pid].reg))];
      const its = new Map(uids.map(uid => [uid, itensDaUsina(uid, prontos)]));
      const dono = new Map();                                   // código → a usina que o tem hoje no Nexus
      Object.values(S.ctx.nexus).forEach(est => (est.inversores || []).forEach(i => { if (i.codigo_fracttal) dono.set(canon(i.codigo_fracttal), est.usina_id); }));
      const pai = new Map(uids.map(u => [u, u]));
      const raiz = u => { while (pai.get(u) !== u) u = pai.get(u); return u; };
      uids.forEach(uid => its.get(uid).forEach(it => it.inversores.forEach(i => {
        const d = dono.get(canon(i.codigo_fracttal));
        if (d != null && d !== uid && pai.has(d)) pai.set(raiz(uid), raiz(d)); })));
      const comp = new Map();
      uids.forEach(u => { const r = raiz(u); comp.set(r, (comp.get(r) || []).concat([u])); });
      const out = [], max = op.maxPorPedido || MAX_POR_PEDIDO; let cur = [];
      comp.forEach(us => {
        const lote = us.flatMap(u => its.get(u));
        if (cur.length && cur.length + lote.length > max) { out.push(cur); cur = []; }
        cur = cur.concat(lote);
      });
      if (cur.length) out.push(cur);
      return out;
    }
    function corpoDe(it) { return {usina_supervisorio: it.usina_supervisorio, usina_id: it.usina_id, selo: it.selo, inversores: it.inversores}; }
    // a usina que o Nexus recusou (D-f, 20/10): a recusa 4xx que é de uma usina traz "usina_id" e "usina_supervisorio" dela.
    // Saem TODOS os itens dessa usina (o selo é da usina e o Nexus grava as chaves dela juntas)
    function culpadas(e, lote) {
      const d = e && e.dados;
      if (!d || !(e.status >= 400 && e.status < 500) || (d.usina_id == null && !d.usina_supervisorio)) return [];
      const uids = new Set(lote.filter(it => (d.usina_id != null && +d.usina_id === +it.usina_id)
        || (d.usina_supervisorio && nk(d.usina_supervisorio) === nk(it.usina_supervisorio))).map(it => +it.usina_id));
      return lote.filter(it => uids.has(+it.usina_id));
    }
    // os avisos do Nexus por usina (P-k): o que cita a chave (“…”) vai com ela; o que é da usina (o nome do Registro, a
    // "(usina N)", uma chave dela) vai com a 1ª usina da fonte dela neste pedido; o resto, no fim do resultado
    // o aviso do Nexus vem como {usina_id, usina_supervisorio, tipo, texto}; o `tipo` "nao_marcada" é o "não vale no lugar da
    // aba" (D-b), destacado mesmo que o texto mude de redação
    function textoAviso(a) {
      if (!a || typeof a !== 'object') return String(a == null ? '' : a);
      const t = String(a.texto || a.aviso || a.motivo || '');
      return a.tipo === 'nao_marcada' && !foraDaAba(t) ? 'não vale no lugar da aba: ' + t : t;
    }
    function daChave(a, chave) {
      const c = nk(chave);
      if (!c) return false;
      if (a && typeof a === 'object') return nk(a.usina_supervisorio) === c;
      return nk(a).includes('“' + c + '”');
    }
    function daUsina(a, uid) {
      if (a && typeof a === 'object') return a.usina_id != null && +a.usina_id === +uid;
      const t = nk(a), est = S.ctx.nexus[uid] || {}, nome = nk(est.nome || (S.ctx.regPor[uid] || {}).nome || '');
      return t.includes('(usina ' + uid + ')') || (!!nome && (t.startsWith(nome + ':') || t.includes(' de ' + nome + ' ') || t.includes(' de ' + nome + ':')))
        || (est.chaves || []).some(c => daChave(a, c.usina_supervisorio));
    }
    // `marcacao` (a volta do Nexus, D-b): chave a chave, se passou a valer no lugar da aba. Gravar no Nexus já não quer dizer
    // valer nos leitores (2ª revisão final, 21/10/2026: a manchete dizia "De-para salvo ... Vale no tempo real em até 1 min"
    // com toda chave em `nao_marcada`). As que não valem vão em `res.naoMarcadas`; sem a `marcacao` (o caminho "respondeu
    // tarde", ou um Nexus de antes), pelos avisos `nao_marcada` de chave
    function gravouLote(lote, avs, res, tarde, marcacao) {
      const usado = avs.map(() => false), primeiro = {}, nao = res.naoMarcadas = res.naoMarcadas || [];
      const poeNao = c => { if (c && !nao.some(x => nk(x) === nk(c))) nao.push(c); };
      if (Array.isArray(marcacao)) marcacao.forEach(m => { if (m && m.marcada === false) poeNao(m.usina_supervisorio); });
      else avs.forEach(a => { if (a && typeof a === 'object' && a.tipo === 'nao_marcada') poeNao(a.usina_supervisorio); });
      lote.forEach(it => it.grupos.forEach(g => {
        const x = {g, ok: true, chave: S.gsel[g.pid].chave, tarde, avisos: []};
        avs.forEach((a, i) => { if (!usado[i] && daChave(a, it.usina_supervisorio)) { usado[i] = true; x.avisos.push(textoAviso(a)); } });
        if (!(it.usina_id in primeiro)) primeiro[it.usina_id] = x;
        res.nexus.push(x);
      }));
      Object.keys(primeiro).forEach(uid => avs.forEach((a, i) => { if (!usado[i] && daUsina(a, uid)) { usado[i] = true; primeiro[uid].avisos.push(textoAviso(a)); } }));
      avs.forEach((a, i) => { if (!usado[i]) res.avisos.push(textoAviso(a)); });
    }
    // P-f (20/10): sem resposta, estouro de 180 s ou a gravação que falhou no meio, o Nexus PODE ter gravado (e marcado a
    // chave no lugar da aba). A tela dizia "nada foi gravado" e não tentava a ponte. Relê as usinas: o Nexus grava o pedido
    // inteiro num passo só, e o selo de uma usina dele que mudou quer dizer que gravou (segue para a ponte)
    // A releitura ESPERA o Nexus terminar (2ª revisão final, 21/10/2026): no estouro de 180 s e no 502/504 do proxy o
    // pedido abandonado continua no servidor, e o estado relido na hora devolvia o selo de antes. A tela concluía "está
    // como antes: salve de novo" e guardava o selo velho; o Nexus gravava segundos depois e o 2º Salvar levava 409, sem a
    // ponte (provado com a Itaja 1: selo-93 guardado, selo-93-gravado no Nexus). O estado diz `gravando`: enquanto ele for
    // verdadeiro (ou o Nexus não disser) e o selo não mudar, relê a cada 15 s até passar o teto do sync do livro (300 s).
    // Selo mudou = gravou (segue para a ponte); `gravando` falso e o selo igual = como antes; o prazo passou sem saber =
    // "não se sabe se o Nexus gravou", sem trocar a base da usina pelo selo relido (ela e a ponte seguem pendentes)
    async function conferePeloSelo(lote, e, res) {
      const uids = [...new Set(lote.map(it => it.usina_id))];
      const passo = op.esperaSelo != null ? op.esperaSelo : 15000, prazo = Date.now() + (op.prazoSelo != null ? op.prazoSelo : 330000);
      let lidas = null, e2 = null, gravando = null, mudou = false;
      for (let volta = 0; ; volta++) {
        S.etapaSalvar = volta ? `O Nexus ${gravando ? 'ainda está gravando' : 'ainda não disse se terminou de gravar'}: relendo a usina a cada ${Math.round(passo / 1000)} s (até 5 min e meio)…`
          : `O Nexus não respondeu (${e.message}): relendo as usinas para saber se ele gravou…`;
        barra();
        try {
          const d = await lerJson(S.ctx.nexusBase + NEXUS_ESTADO + '?usinas=' + uids.join(','), {timeout: 60000, quem: 'o Nexus'});
          lidas = d.usinas || []; gravando = typeof d.gravando === 'boolean' ? d.gravando : null; e2 = null;
          mudou = lote.some(it => { const u = lidas.find(x => +x.usina_id === +it.usina_id); return u && u.selo !== it.selo; });
          if (mudou || gravando === false) break;
        } catch (x) { e2 = x; }
        if (Date.now() >= prazo) break;
        await espera(passo);
      }
      if (lidas && mudou) {
        lidas.forEach(guardaEstado);
        gravouLote(lote, avisosDoEstado(lote, lidas), res, true);
        return;
      }
      if (lidas && gravando === false) {
        lidas.forEach(guardaEstado);
        lote.forEach(it => it.grupos.forEach(g => res.nexus.push({g, ok: false,
          motivo: `o Nexus não respondeu (${e.message}); relida a usina com o Nexus sem gravação em curso, a estrutura dela está como antes: salve de novo (o remendo repetido não duplica nada)`})));
        return;
      }
      lote.forEach(it => it.grupos.forEach(g => res.nexus.push({g, ok: false, semSaber: true,
        motivo: lidas ? `${e.message}; relida a usina por 5 min e meio, o selo não mudou e o Nexus ${gravando ? 'seguia gravando' : 'não disse se terminou de gravar'}: recarregue a tela daqui a alguns minutos e confira antes de salvar de novo`
          : `${e.message}; a releitura da usina também falhou (${e2 ? e2.message : 'sem resposta'}): recarregue a tela e confira antes de salvar de novo`})));
    }
    // o que o estado relido diz da marca, no caminho "respondeu tarde" (P-k/D-b): a chave gravada que não vale no lugar da
    // aba vira o aviso `nao_marcada` (os motivos não vieram: o Nexus respondeu ao navegador que já tinha desistido)
    function avisosDoEstado(lote, lidas) {
      const out = [];
      lote.forEach(it => { const u = lidas.find(x => +x.usina_id === +it.usina_id);
        const c = u && (u.chaves || []).find(x => nk(x.usina_supervisorio) === nk(it.usina_supervisorio));
        if (c && !c.substitui_aba) out.push({usina_id: it.usina_id, usina_supervisorio: it.usina_supervisorio, tipo: 'nao_marcada',
          texto: `A chave “${it.usina_supervisorio}” foi gravada e não vale no lugar da aba (relido do estado: o Nexus respondeu tarde e os motivos não vieram; confira na Base > Equipamentos das usinas)`}); });
      return out;
    }
    // a ponte da fonte para a chave escolhida, ou null quando a fonte já liga a ela:
    // - a chave de hoje, pela forma normalizada (D-g: "Assis Chateaubriand  Skid 1 (79)" da aba = a do Nexus);
    // - a linha SEM ponte nenhuma (sem `nome_api`) que já se chama como a chave (P-g: só aí. Com `nome_api`, a ponte por id
    //   já renomeou a planta, o nome por dentro é o alvo dela, e pular deixava a planta procurando o alvo velho);
    // - com `nome_api` e a chave igual a ele: a ponte vai VAZIA ("sem ponte": vale o nome que a API escreve, que é a chave);
    // - senão, a chave como o cadastro da plataforma a escreve (a fonte procura a grafia exata; o decidir relê a visão do
    //   Nexus quando ela ainda não está no cadastro).
    function alvoDaPonte(g, chave) {
      const c = nk(chave);
      if (g.chave_cadastro && nk(g.chave_cadastro) === c) return null;
      if (!g.chave_cadastro && !g.nome_api && nk(g.usina) === c) return null;
      if (g.nome_api && nk(g.nome_api) === c) return {chave, alvo: ''};
      const cad = S.ctx.cadPor[c];
      return {chave, alvo: cad ? cad.chave : chave};
    }
    async function gravaPonte(g, p) {
      try {
        await lerJson('/api/admin/de-para/decidir', {method: 'POST', body: {fonte: g.fonte, id: String(g.plant_id), usina_supervisorio: p.alvo}});
        g.chave_cadastro = p.chave;
        delete S.pontePend[g.pid];
        return {ok: true};
      } catch (e) {
        // P-b: a ponte que falha NÃO vira a base da usina; fica pendente e o próximo Salvar manda só ela
        S.pontePend[g.pid] = Object.assign({}, p, {motivo: e.message});
        return {ok: false, motivo: e.message};
      }
    }
    async function salvar() {
      if (S.salvando) return;
      _memo = null;
      const nb = S.ctx.nexusBase, prontos = S.grupos.filter(pronto), soPonte = S.grupos.filter(g => !pronto(g) && precisaPonte(g));
      if (nb == null || !S.ctx.grava || (!prontos.length && !soPonte.length)) return;
      S.salvando = true; S.resultado = null;
      const res = {nexus: [], ponte: [], avisos: [], mudancas: 0, naoMarcadas: []};
      const ls = lotes(prontos);
      for (let i = 0; i < ls.length; i++) {
        let lote = ls[i];
        // D-f: a usina que o Nexus recusa sai do lote e o resto vai de novo, no máximo 3 vezes
        for (let reenvio = 0; lote.length; reenvio++) {
          S.etapaSalvar = `Gravando no Nexus (${i + 1} de ${ls.length})${reenvio ? `, de novo sem a usina recusada (${reenvio}ª vez)` : ''}…`; barra();
          try {
            const d = await lerJson(nb + NEXUS_SALVAR, {method: 'POST', timeout: 180000, quem: 'o Nexus', body: {itens: lote.map(corpoDe)}});
            (d.usinas || []).forEach(guardaEstado);
            res.mudancas += d.mudancas || 0;
            gravouLote(lote, d.avisos || [], res, false, d.marcacao);
            break;
          } catch (e) {
            if (semSaberSeGravou(e)) { await conferePeloSelo(lote, e, res); break; }
            const fora = culpadas(e, lote);
            if (fora.length && fora.length < lote.length && reenvio < 3) {
              fora.forEach(it => it.grupos.forEach(g => res.nexus.push({g, ok: false, culpada: true, reenviou: true, motivo: e.message})));
              lote = lote.filter(it => !fora.includes(it));
              continue;
            }
            lote.forEach(it => it.grupos.forEach(g => res.nexus.push(fora.includes(it) ? {g, ok: false, culpada: true, motivo: e.message}
              : {g, ok: false, motivo: fora.length ? `o pedido foi recusado ${reenvio + 1} vez(es) por outra usina e não foi de novo (salve de novo): ${e.message}` : e.message})));
            break;
          }
        }
      }
      // a ponte da fonte (a plataforma): só das usinas que o Nexus gravou e cuja chave não é a de hoje
      for (const x of res.nexus.filter(y => y.ok)) {
        const g = x.g, p = alvoDaPonte(g, x.chave);
        if (!p) { x.ponte = 'já ligava'; delete S.pontePend[g.pid]; continue; }
        S.etapaSalvar = `Gravando a ponte de ${g.usina}…`; barra();
        const r = await gravaPonte(g, p);
        if (r.ok) x.ponte = 'ok';
        else { x.ponte = 'falhou'; x.ponteMotivo = r.motivo; }
      }
      // a ponte que tinha ficado pendente (P-b): só o decidir, sem ir ao Nexus de novo
      for (const g of soPonte) {
        const p = precisaPonte(g);
        S.etapaSalvar = `Gravando a ponte de ${g.usina}…`; barra();
        const r = await gravaPonte(g, p);
        res.ponte.push({g, ok: r.ok, motivo: r.motivo, chave: p.chave});
      }
      // o que o Nexus devolveu passa a ser a base das usinas gravadas (a ponte que falhou fica em `pontePend`)
      res.nexus.filter(x => x.ok).forEach(x => {
        const g = x.g, gs = S.gsel[g.pid];
        g.invs.forEach(inv => { const nx = invNexus(S.ctx, gs.chave, inv), s = S.sel[k(g, inv)];
          if (nx && nx.codigo_fracttal) S.sel[k(g, inv)] = Object.assign({}, s, {ativo: canon(nx.codigo_fracttal),
            strings: nx.strings_esperadas_qtd > 0 ? +nx.strings_esperadas_qtd : s.strings, strDe: nx.strings_esperadas_qtd > 0 ? 'nexus' : s.strDe,
            conf: !!nx.conferido_em, sug: !nx.conferido_em, salvo: true}); });
        gs.chaveSug = false; gs.regSug = false;
        S.avisosG[g.pid] = x.avisos || [];
        fotografa(g);
      });
      S.salvando = false; S.etapaSalvar = ''; S.resultado = res;
      desenhar();
      if (op.aoSalvar) op.aoSalvar(res);
    }

    const inst = {
      S, html, desenhar, barra, salvar, descartar, mudar, mudarChave, conferir, conferirTodos, deixarDeFora,
      pendencia: (pid, id) => { const g = S.porPid[String(pid)]; const inv = g && g.invs.find(i => String(i.id) === String(id)); _memo = null; return inv ? pendencia(g, inv) : null; },
      pronto: pid => { _memo = null; const g = S.porPid[String(pid)]; return !!g && pronto(g); },
      conta: pid => { _memo = null; const g = S.porPid[String(pid)]; return g ? contaDo(g) : null; },
      _aoMudar: aoMudar, _aoClicar: aoClicar,
      // o HTML do resultado do último Salvar (a manchete e a lista da barra), sem a barra na tela (os testes)
      resultadoHtml: () => S.resultado ? htmlResultado(S.resultado) : '',
      entrar(linhas, fonte) {
        G.__gcDpAtual = inst;
        instalaCss(D);
        S.ativo = true; S.resultado = null;
        S.grupos = (linhas || []).filter(r => Array.isArray(r.inv_resumo)).map(r => grupoDaLinha(r, fonte || op.fonte || 'pv'));
        S.porPid = Object.fromEntries(S.grupos.map(g => [g.pid, g]));
        return carregar();
      },
      sair() { S.ativo = false; S.resultado = null; S.abertos.clear(); if (G.__gcDpAtual === inst) G.__gcDpAtual = null; barra(); },
      ativo() { return S.ativo; },
      mexidos() { return S.grupos.filter(mexido).length; },
      pontePendente: pid => { _memo = null; const g = S.porPid[String(pid)]; return !!g && !!precisaPonte(g); },
      // o que se perde ao sair do modo sem salvar: as usinas mexidas e as pontes pendentes (o confirm do Tempo real)
      pontesPendentes() { _memo = null; return S.grupos.filter(g => !pronto(g) && precisaPonte(g)).length; },
    };
    return inst;
  }

  const API = {
    criar, nexusBase, lerJson,
    regras: {norm, num, nm, numeros, meioDoNome, baseNome, canon, codigoBase, letras, suf, site, nmDoCodigo, rotuloInversor,
      rotuloCabine, chaveEquip, invsDaArvore, mapaNM, numeroDaPlanta, nmA, nmB, acertos, sugereInversor, candidatosUF,
      escolheUF, ufDoCodigo, sugereRegistro, sugereChave, invNexus, contaKwp, sobrepor, grupoDaLinha, nk, numUG,
      cabIdent, cadDoInv, nomeDoCadastro, estDaChave, textoNaoJson, semSaberSeGravou},
  };
  G.DeparaTabela = API;
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
})(typeof window !== 'undefined' ? window : globalThis);
