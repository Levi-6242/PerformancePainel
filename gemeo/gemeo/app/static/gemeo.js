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
    mk("rect", { x: xa, y: y1, width: Math.max(1.5, xb - xa), height: y0 - y1, fill: "rgba(179,38,30,.10)" });
    [xa, xb].forEach(function (x) { mk("line", { x1: x, y1: y1, x2: x, y2: y0, stroke: "#B3261E", "stroke-width": "1.4" }); });
    var rot = mk("text", { x: (xa + xb) / 2, y: y1 - 6, "text-anchor": "middle", "font-size": "10", fill: "#B3261E", "font-family": mono, "font-weight": "700" },
                 j.n + "/" + j.de + " inv. parados");
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
    mk("rect", { x: cx - bw, y: y0 - he, width: bw, height: he, fill: "none", stroke: "#3E7CB1", "stroke-width": "1.5", "stroke-dasharray": "4 3" });
    var r = mk("rect", { x: cx, y: y0 - hm, width: bw, height: hm, fill: "#6A8F0E" });
    var t = document.createElementNS(ns, "title"); t.textContent = d.dia + ": esperado " + ((d.e_esperado || 0) / 1000).toFixed(1) + " MWh · medido " + ((d.e_medido || 0) / 1000).toFixed(1) + " MWh"; r.appendChild(t);
    if (i % passo === 0) mk("text", { x: cx, y: y0 + 14, "text-anchor": "middle", "font-size": "9", fill: "#6E6A80", "font-family": mono }, d.dia.slice(8, 10) + "/" + d.dia.slice(5, 7));
  });
})();
