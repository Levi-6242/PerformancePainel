/* gemeo/gemeo/app/static/gemeo.js */
/* Curva do dia em SVG puro (sem biblioteca, sem CDN): esperado tracejado, medido cheio, area de perda entre os
   dois. Le o JSON que o template injeta em #curva-dados. O eixo x e a HORA (nao o indice do ponto): com dado
   faltando — a SunOp entrega ~50% dos slots ate a reconciliacao das 03h — o indice punha 08h e 18h a mesma
   distancia de 06h e 08h. Buraco maior que 40 min quebra a linha em vez de virar uma reta atravessando o vazio. */
(function () {
  var el = document.getElementById("curva-dados"), svg = document.getElementById("curva");
  if (!el || !svg) return;
  var pts = JSON.parse(el.textContent || "[]");
  var x0 = 40, x1 = 540, y0 = 200, y1 = 40, ns = "http://www.w3.org/2000/svg", mono = "IBM Plex Mono, Consolas, monospace";
  function mk(tag, at, txt) { var e = document.createElementNS(ns, tag); for (var k in at) e.setAttribute(k, at[k]); if (txt != null) e.textContent = txt; svg.appendChild(e); return e; }
  var max = 0; pts.forEach(function (p) { max = Math.max(max, p.esperado_kw || 0, p.medido_kw || 0); });
  if (!pts.length || max <= 0) { mk("text", { x: 290, y: 120, "text-anchor": "middle", "font-size": "12", fill: "#6E6A80" }, "sem curva para hoje"); return; }
  /* Janela de 05h as 19h (pedido do Levi, 04/09): das 19h as 5h a usina esta em zero e a curva ficava espremida
     na metade do grafico. A janela ABRE sozinha se houver geracao fora dela — melhor um eixo estranho do que
     esconder dado (usina em outro fuso, leitura fantasma de madrugada). */
  var CORTE = 40, lim = max * 0.01, mIni = 5 * 60, mFim = 19 * 60;
  function minu(h) { return (h && h.length >= 5) ? parseInt(h.slice(0, 2), 10) * 60 + parseInt(h.slice(3, 5), 10) : null; }
  pts.forEach(function (p) {
    var m = minu(p.hora);
    if (m !== null && ((p.esperado_kw || 0) > lim || (p.medido_kw || 0) > lim)) { mIni = Math.min(mIni, m); mFim = Math.max(mFim, m); }
  });
  var vis = pts.filter(function (p) { var m = minu(p.hora); return m !== null && m >= mIni && m <= mFim; });
  if (!vis.length) { vis = pts; mIni = 0; mFim = 24 * 60; }
  var xm = function (m) { return x0 + (x1 - x0) * (m - mIni) / Math.max(1, mFim - mIni); }, yv = function (v) { return y0 - (y0 - y1) * v / max; };
  var faixa = document.getElementById("curva-faixa");
  if (faixa) faixa.textContent = faixa.textContent.split(" · ").slice(0, 2).join(" · ") + " · " + ("0" + Math.floor(mIni / 60)).slice(-2) + "h\u2013" + ("0" + Math.ceil(mFim / 60)).slice(-2) + "h";
  [0, 0.5, 1].forEach(function (f) {
    var y = yv(max * f);
    mk("line", { x1: x0, y1: y, x2: x1, y2: y, stroke: f ? "#F0F1F4" : "#D9D9E0" });
    mk("text", { x: x0 - 6, y: y + 4, "text-anchor": "end", "font-size": "10", fill: "#6E6A80", "font-family": mono }, (max * f / 1000).toFixed(1).replace(".", ","));
  });
  function trechos(chave) {          // quebra a serie onde falta ponto: cada trecho vira uma polyline
    var out = [], atual = [], ant = null;
    vis.forEach(function (p) {
      var m = minu(p.hora), v = p[chave];
      if (v == null) { if (atual.length) out.push(atual); atual = []; ant = null; return; }
      if (ant !== null && m - ant > CORTE) { if (atual.length) out.push(atual); atual = []; }
      atual.push(xm(m) + "," + yv(v)); ant = m;
    });
    if (atual.length) out.push(atual);
    return out;
  }
  var corridas = [], cur = [], ant = null;   // trechos em que esperado E medido existem: area de perda
  vis.forEach(function (p) {
    var m = minu(p.hora), ok = p.esperado_kw != null && p.medido_kw != null;
    if (!ok || (ant !== null && m - ant > CORTE)) { if (cur.length > 1) corridas.push(cur); cur = []; }
    if (ok) { cur.push(p); ant = m; } else { ant = null; }
  });
  if (cur.length > 1) corridas.push(cur);
  corridas.forEach(function (run) {
    var poly = run.map(function (p) { return xm(minu(p.hora)) + "," + yv(p.esperado_kw); });
    for (var i = run.length - 1; i >= 0; i--) poly.push(xm(minu(run[i].hora)) + "," + yv(Math.min(run[i].medido_kw, run[i].esperado_kw)));
    mk("polygon", { points: poly.join(" "), fill: "rgba(179,38,30,.14)" });
  });
  trechos("esperado_kw").forEach(function (t) { if (t.length > 1) mk("polyline", { points: t.join(" "), fill: "none", stroke: "#3E7CB1", "stroke-width": "2.2", "stroke-dasharray": "6 4", "stroke-linecap": "round" }); });
  trechos("medido_kw").forEach(function (t) { if (t.length > 1) mk("polyline", { points: t.join(" "), fill: "none", stroke: "#6A8F0E", "stroke-width": "2.4", "stroke-linecap": "round" }); });
  /* A marca do "agora" so aparece se o ultimo slot medido cai DENTRO da janela: num dia fechado ele e 23:45 e a
     linha no canto direito faria parecer que o dado parou as 19h. */
  var ult = null;
  pts.forEach(function (p) { if (p.medido_kw != null) ult = p; });
  var mu = ult ? minu(ult.hora) : null;
  if (mu !== null && mu >= mIni && mu <= mFim) {
    mk("line", { x1: xm(mu), y1: y1, x2: xm(mu), y2: y0, stroke: "#504C63", "stroke-dasharray": "3 3" });
    mk("text", { x: Math.min(xm(mu) + 6, x1 - 30), y: y1 + 10, "font-size": "10", fill: "#504C63", "font-family": mono }, ult.hora);
  }
  /* Janelas em que inversores ficaram parados juntos (pedido do Levi, 04/09: "marcar o desligamento com uma linha
     vermelha"). Vem prontas do servidor em #paradas-dados — a mesma janela que a aba `evento` do workbook mostra.
     O rotulo diz QUANTOS de quantos inversores cairam: 8/12 e desligamento de usina, 1/12 e falha de equipamento. */
  var pel = document.getElementById("paradas-dados");
  (pel ? JSON.parse(pel.textContent || "[]") : []).forEach(function (j) {
    var a = minu(j.hora_ini), b = minu(j.hora_fim);
    if (a === null || b === null || b < mIni || a > mFim) return;
    var xa = xm(Math.max(a, mIni)), xb = xm(Math.min(b, mFim));
    mk("rect", { "class": "parada-marca", x: xa, y: y1, width: Math.max(1.5, xb - xa), height: y0 - y1, fill: "rgba(179,38,30,.10)" });
    [xa, xb].forEach(function (x) { mk("line", { "class": "parada-marca", x1: x, y1: y1, x2: x, y2: y0, stroke: "#B3261E", "stroke-width": "1.4" }); });
    var rot = mk("text", { "class": "parada-marca", x: (xa + xb) / 2, y: y1 - 6, "text-anchor": "middle", "font-size": "10", fill: "#B3261E", "font-family": mono, "font-weight": "700" },
                 j.n + (j.n > 1 ? " inversores parados" : " inversor parado"));
    var tt = document.createElementNS(ns, "title");
    tt.textContent = j.hora_ini + " a " + j.hora_fim + " (" + j.min + " min) · " + j.n + " de " + j.de + " inversores · " + j.kwh + " kWh";
    rot.appendChild(tt);
  });
  for (var h = Math.ceil(mIni / 120) * 120; h <= mFim; h += 120) {
    mk("text", { x: xm(h), y: y0 + 22, "text-anchor": "middle", "font-size": "10", fill: "#6E6A80", "font-family": mono }, ("0" + Math.floor(h / 60)).slice(-2) + "h");
  }
})();

/* Barras por dia (periodo de 7 ou 30 dias): esperado tracejado, medido cheio, em MWh. Le #dias-dados. */
(function () {
  var el = document.getElementById("dias-dados"), svg = document.getElementById("barras");
  if (!el || !svg) return;
  var dias = JSON.parse(el.textContent || "[]");
  var x0 = 40, x1 = 545, y0 = 200, y1 = 30, ns = "http://www.w3.org/2000/svg", mono = "IBM Plex Mono, Consolas, monospace";
  function mk(tag, at, txt) { var e = document.createElementNS(ns, tag); for (var k in at) e.setAttribute(k, at[k]); if (txt != null) e.textContent = txt; svg.appendChild(e); return e; }
  var max = 0; dias.forEach(function (d) { max = Math.max(max, d.e_esperado || 0, d.e_medido || 0); });
  if (!dias.length || max <= 0) { mk("text", { x: 290, y: 120, "text-anchor": "middle", "font-size": "12", fill: "#6E6A80" }, "sem cascata no período"); return; }
  [0, 0.5, 1].forEach(function (f) {
    var y = y0 - (y0 - y1) * f;
    mk("line", { x1: x0, y1: y, x2: x1, y2: y, stroke: f ? "#F0F1F4" : "#D9D9E0" });
    mk("text", { x: x0 - 6, y: y + 4, "text-anchor": "end", "font-size": "10", fill: "#6E6A80", "font-family": mono }, (max * f / 1000).toFixed(1).replace(".", ","));
  });
  var n = dias.length, larg = (x1 - x0) / n, bw = Math.max(2, larg * 0.36), passo = Math.max(1, Math.ceil(n / 12));
  dias.forEach(function (d, i) {
    var cx = x0 + larg * (i + 0.5), he = (y0 - y1) * (d.e_esperado || 0) / max, hm = (y0 - y1) * (d.e_medido || 0) / max;
    /* Dia com desligamento: a mesma marca vermelha da curva do dia, aqui na coluna inteira mais um traco no eixo.
       Sem ela a barra de um dia com 8 inversores fora passa por "dia ruim" qualquer. */
    var par = d.paradas || [], txt = "";
    if (par.length) {
      var kwh = 0, nmax = 0, minutos = 0;
      par.forEach(function (j) { kwh += j.kwh || 0; nmax = Math.max(nmax, j.n || 0); minutos += j.min || 0; });
      mk("rect", { "class": "parada-marca", x: cx - larg / 2 + 1, y: y1, width: Math.max(2, larg - 2), height: y0 - y1, fill: "rgba(179,38,30,.10)" });
      mk("line", { "class": "parada-marca", x1: cx - larg / 2 + 1, y1: y0 + 3.5, x2: cx + larg / 2 - 1, y2: y0 + 3.5, stroke: "#B3261E", "stroke-width": "2.5" });
      txt = " · parada: " + nmax + " de " + par[0].de + " inversores, " + minutos + " min, " + Math.round(kwh) + " kWh";
    }
    mk("rect", { x: cx - bw, y: y0 - he, width: bw, height: he, fill: "none", stroke: "#3E7CB1", "stroke-width": "1.5", "stroke-dasharray": "4 3" });
    var r = mk("rect", { x: cx, y: y0 - hm, width: bw, height: hm, fill: "#6A8F0E" });
    var t = document.createElementNS(ns, "title"); t.textContent = d.dia + ": esperado " + ((d.e_esperado || 0) / 1000).toFixed(1) + " MWh · medido " + ((d.e_medido || 0) / 1000).toFixed(1) + " MWh" + txt; r.appendChild(t);
    if (i % passo === 0) {
      var dt = d.dia.slice(8, 10) + "/" + d.dia.slice(5, 7);
      mk("text", { "class": par.length ? "parada-marca" : "", x: cx, y: y0 + 14, "text-anchor": "middle", "font-size": "9", fill: par.length ? "#B3261E" : "#6E6A80", "font-family": mono, "font-weight": par.length ? "700" : "400" }, dt);
      // a mesma data em cinza por baixo: aparece no lugar da vermelha quando as marcas estao escondidas
      if (par.length) mk("text", { "class": "parada-off", x: cx, y: y0 + 14, "text-anchor": "middle", "font-size": "9", fill: "#6E6A80", "font-family": mono }, dt);
    }
  });
})();

/* Clicar em "Parada de inversores" na legenda esconde as marcas vermelhas do grafico — pedido do Levi (04/09) para
   tirar print sem elas. A escolha fica no navegador: sem isso o auto-refresh de 5 min traria as linhas de volta no
   meio do print. E so visual: o evento, a cascata e o workbook continuam iguais. */
(function () {
  var CHAVE = "gemeo.paradas.ocultas", botoes = document.querySelectorAll(".lg-toggle");
  if (!botoes.length) return;
  var oculto = false;
  try { oculto = localStorage.getItem(CHAVE) === "1"; } catch (e) { }
  function pinta() {
    botoes.forEach(function (b) {
      var svg = document.getElementById(b.getAttribute("data-alvo"));
      if (svg) svg.classList.toggle("sem-paradas", oculto);
      b.classList.toggle("off", oculto);
      b.setAttribute("aria-pressed", oculto ? "false" : "true");
      b.title = oculto ? "mostrar as marcas de parada" : "esconder as marcas de parada (para o print)";
    });
  }
  botoes.forEach(function (b) {
    b.addEventListener("click", function () {
      oculto = !oculto;
      try { localStorage.setItem(CHAVE, oculto ? "1" : "0"); } catch (e) { }
      pinta();
    });
  });
  pinta();
})();

// ── Alternador Cascata / Assinaturas (Levi, 21/09/2026) ─────────────────────────────────────────
// Os dois respondem a mesma pergunta — o que a usina perdeu hoje — e lado a lado disputavam a
// largura que a curva precisa. Viraram um card so. Abre SEMPRE em Cascata, como ele pediu: nao
// guardo a escolha, porque "default em cascata" tem de valer toda vez que alguem abre a usina.
// Troca por `hidden`, nao por remocao: o SVG e as listas ja estao montados, mudar de aba nao refaz nada.
(function () {
  var barra = document.querySelector(".alt");
  if (!barra) return;
  var rot = document.getElementById("alt-rot");
  var botoes = Array.prototype.slice.call(barra.querySelectorAll("button[data-aba]"));

  // O rotulo vem em data-rot/data-sub, texto puro: montar HTML aqui e mais seguro que carregar
  // marcacao dentro de atributo (e foi onde a primeira versao quebrou, escapando aspas do Jinja).
  function rotular(b) {
    if (!rot) return;
    rot.textContent = b.dataset.rot || "";
    if (b.dataset.sub) {
      var s = document.createElement("small");
      s.textContent = b.dataset.sub;
      rot.appendChild(s);
    }
  }

  function mostrar(aba) {
    botoes.forEach(function (b) {
      var meu = b.dataset.aba === aba;
      b.setAttribute("aria-selected", meu ? "true" : "false");
      var painel = document.getElementById(b.getAttribute("aria-controls"));
      if (painel) painel.hidden = !meu;
      if (meu) rotular(b);
    });
  }

  barra.addEventListener("click", function (ev) {
    var b = ev.target.closest("button[data-aba]");
    if (b) mostrar(b.dataset.aba);
  });
  // setas esquerda/direita, que e o que um role="tablist" promete a quem navega por teclado
  barra.addEventListener("keydown", function (ev) {
    if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
    var i = botoes.indexOf(document.activeElement);
    if (i < 0) return;
    var alvo = botoes[(i + (ev.key === "ArrowRight" ? 1 : botoes.length - 1)) % botoes.length];
    alvo.focus(); mostrar(alvo.dataset.aba); ev.preventDefault();
  });
})();

// ── Drill-down: curva das strings do inversor (Levi, 21/09/2026) ────────────────────────────────
// "quando eu clicar nessa linha quero que abra um drill down da curva das strings do inversor para
// aquele dia". Desenha TODAS as irmãs do mesmo inversor, com a clicada em destaque e a mediana da
// família tracejada — porque a pergunta que se faz olhando uma string ruim não é "ela caiu?", é
// "ela caiu SOZINHA?". Contra as irmãs isso se vê num relance; a string isolada não responde nada.
(function () {
  var alvo = document.getElementById("str-drill");
  if (!alvo) return;
  var cacheInv = null;

  function esc(s) { var d = document.createElement("div"); d.textContent = s == null ? "" : s; return d.innerHTML; }
  function hhmm(iso) { return String(iso).slice(11, 16); }

  function svg(dados, destaque) {
    var nomes = Object.keys(dados.series || {});
    if (!nomes.length) return '<div class="vazio">Sem corrente por string gravada neste dia.</div>';
    var W = 560, H = 210, L = 34, B = 24, pts = [], mx = 0, t0 = null, t1 = null;
    nomes.forEach(function (n) {
      (dados.series[n] || []).forEach(function (p) {
        var t = Date.parse(p[0]); if (!isFinite(t)) return;
        if (t0 === null || t < t0) t0 = t; if (t1 === null || t > t1) t1 = t;
        if (p[1] > mx) mx = p[1];
      });
    });
    if (t0 === null || t1 === t0) return '<div class="vazio">Sem janela de tempo utilizável.</div>';
    mx = mx || 1;
    var x = function (t) { return L + (t - t0) / (t1 - t0) * (W - L - 8); };
    var y = function (v) { return H - B - v / mx * (H - B - 12); };
    function linha(serie, cor, larg, trac) {
      var d = serie.map(function (p) { return x(Date.parse(p[0])).toFixed(1) + "," + y(p[1]).toFixed(1); }).join(" ");
      return '<polyline fill="none" stroke="' + cor + '" stroke-width="' + larg + '"'
        + (trac ? ' stroke-dasharray="5 4"' : "") + ' points="' + d + '"/>';
    }
    // irmãs primeiro, em cinza; o destaque e a mediana por cima, para não ficarem soterrados
    var corpo = nomes.filter(function (n) { return n !== destaque; })
      .map(function (n) { return linha(dados.series[n], "var(--gc-line)", 1.2, false); }).join("");
    if (dados.mediana && dados.mediana.length) corpo += linha(dados.mediana, "var(--gc-mut)", 1.8, true);
    if (dados.series[destaque]) corpo += linha(dados.series[destaque], "var(--st-risk)", 2.4, false);
    var eixo = "";
    for (var k = 0; k <= 4; k++) {
      var t = t0 + (t1 - t0) * k / 4;
      eixo += '<text x="' + x(t).toFixed(0) + '" y="' + (H - 6) + '" class="ax">' + hhmm(new Date(t).toISOString()) + "</text>";
    }
    return '<svg viewBox="0 0 ' + W + " " + H + '" class="cv" role="img" aria-label="Corrente das strings do inversor">'
      + '<line x1="' + L + '" y1="' + (H - B) + '" x2="' + (W - 8) + '" y2="' + (H - B) + '" class="gl"/>'
      + '<text x="2" y="' + y(mx).toFixed(0) + '" class="ax">' + mx.toFixed(1).replace(".", ",") + " A</text>" + corpo + eixo + "</svg>";
  }

  function pinta(dados, destaque, dia) {
    if (dados.erro) { alvo.innerHTML = '<div class="vazio">' + esc(dados.erro) + "</div>"; alvo.hidden = false; return; }
    alvo.innerHTML =
      '<div class="drill-cab"><b>' + esc(dados.inversor) + "</b> · " + esc(dia)
      + ' <small>' + dados.n_strings + " strings · destaque: " + esc(destaque) + "</small>"
      + '<button type="button" id="str-fechar">fechar</button></div>'
      + svg(dados, destaque)
      + '<div class="drill-leg"><span><i style="border-color:var(--st-risk)"></i>' + esc(destaque) + "</span>"
      + '<span><i style="border-color:var(--gc-mut);border-top-style:dashed"></i>mediana do inversor</span>'
      + '<span><i style="border-color:var(--gc-line)"></i>irmãs</span></div>';
    alvo.hidden = false;
    var b = document.getElementById("str-fechar");
    if (b) b.addEventListener("click", function () { alvo.hidden = true; });
    alvo.scrollIntoView({ block: "nearest" });
  }

  async function abrir(tr) {
    var inv = tr.dataset.inv, str = tr.dataset.str, uid = tr.dataset.uid, dia = tr.dataset.dia;
    if (!inv || !uid) return;
    // cache por (inversor, dia): clicar em cinco strings do MESMO inversor é o caso comum, e cada
    // clique rebuscando as 28 séries seria pagar cinco vezes pela mesma resposta.
    var chave = uid + "|" + inv + "|" + dia;
    if (cacheInv && cacheInv.chave === chave) { pinta(cacheInv.dados, str, dia); return; }
    alvo.innerHTML = '<div class="vazio">Carregando a curva das strings…</div>';
    alvo.hidden = false;
    try {
      var u = (window.GEMEO_PREFIXO || "/gemeo") + "/api/usina/" + encodeURIComponent(uid) + "/strings"
        + "?inversor=" + encodeURIComponent(inv) + "&dia=" + encodeURIComponent(dia);
      var r = await fetch(u, { headers: { Accept: "application/json" } });
      var d = await r.json();
      cacheInv = { chave: chave, dados: d };
      pinta(d, str, dia);
    } catch (e) {
      alvo.innerHTML = '<div class="vazio">Não consegui carregar a curva (' + esc(String(e && e.message || e)) + ").</div>";
    }
  }

  document.addEventListener("click", function (ev) {
    var tr = ev.target.closest && ev.target.closest("tr.str-lin");
    if (tr) abrir(tr);
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key !== "Enter" && ev.key !== " ") return;
    var tr = ev.target.closest && ev.target.closest("tr.str-lin");
    if (tr) { abrir(tr); ev.preventDefault(); }
  });
})();
