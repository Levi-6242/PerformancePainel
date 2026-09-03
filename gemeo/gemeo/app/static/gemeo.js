/* gemeo/gemeo/app/static/gemeo.js */
/* Curva do dia em SVG puro (sem biblioteca, sem CDN): esperado tracejado o dia inteiro, medido cheio ate o
   ultimo slot conhecido, area de perda entre os dois. Le o JSON que o template injeta em #curva-dados. */
(function () {
  var el = document.getElementById("curva-dados"), svg = document.getElementById("curva");
  if (!el || !svg) return;
  var pts = JSON.parse(el.textContent || "[]");
  var x0 = 40, x1 = 540, y0 = 200, y1 = 40, ns = "http://www.w3.org/2000/svg", mono = "IBM Plex Mono, Consolas, monospace";
  function mk(tag, at, txt) { var e = document.createElementNS(ns, tag); for (var k in at) e.setAttribute(k, at[k]); if (txt != null) e.textContent = txt; svg.appendChild(e); return e; }
  var max = 0; pts.forEach(function (p) { max = Math.max(max, p.esperado_kw || 0, p.medido_kw || 0); });
  if (!pts.length || max <= 0) { mk("text", { x: 290, y: 120, "text-anchor": "middle", "font-size": "12", fill: "#6E6A80" }, "sem curva para hoje"); return; }
  var n = pts.length, xi = function (i) { return x0 + (x1 - x0) * i / Math.max(1, n - 1); }, yv = function (v) { return y0 - (y0 - y1) * v / max; };
  [0, 0.5, 1].forEach(function (f) {
    var y = yv(max * f);
    mk("line", { x1: x0, y1: y, x2: x1, y2: y, stroke: f ? "#F0F1F4" : "#D9D9E0" });
    mk("text", { x: x0 - 6, y: y + 4, "text-anchor": "end", "font-size": "10", fill: "#6E6A80", "font-family": mono }, (max * f / 1000).toFixed(1).replace(".", ","));
  });
  var esp = [], med = [], poly = [], ult = -1;
  pts.forEach(function (p, i) {
    if (p.esperado_kw != null) esp.push(xi(i) + "," + yv(p.esperado_kw));
    if (p.medido_kw != null) { med.push(xi(i) + "," + yv(p.medido_kw)); ult = i; }
    if (p.esperado_kw != null && p.medido_kw != null) poly.push(xi(i) + "," + yv(p.esperado_kw));
  });
  for (var i = n - 1; i >= 0; i--) { var p = pts[i]; if (p.esperado_kw != null && p.medido_kw != null) poly.push(xi(i) + "," + yv(Math.min(p.medido_kw, p.esperado_kw))); }
  if (poly.length > 2) mk("polygon", { points: poly.join(" "), fill: "rgba(179,38,30,.14)" });
  if (esp.length) mk("polyline", { points: esp.join(" "), fill: "none", stroke: "#3E7CB1", "stroke-width": "2.2", "stroke-dasharray": "6 4", "stroke-linecap": "round" });
  if (med.length) mk("polyline", { points: med.join(" "), fill: "none", stroke: "#6A8F0E", "stroke-width": "2.4", "stroke-linecap": "round" });
  if (ult >= 0) {
    mk("line", { x1: xi(ult), y1: y1, x2: xi(ult), y2: y0, stroke: "#504C63", "stroke-dasharray": "3 3" });
    mk("text", { x: xi(ult) + 6, y: y1 + 10, "font-size": "10", fill: "#504C63", "font-family": mono }, pts[ult].hora || "");
  }
  pts.forEach(function (p, i) {
    if (p.hora && /:00$/.test(p.hora) && parseInt(p.hora, 10) % 3 === 0) mk("text", { x: xi(i), y: y0 + 22, "text-anchor": "middle", "font-size": "10", fill: "#6E6A80", "font-family": mono }, p.hora.slice(0, 2) + "h");
  });
})();
