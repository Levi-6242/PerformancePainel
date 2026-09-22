/* plataforma/static/notif.js — sino de notificacoes (05/09/2026, pedido do Levi).
   O que faz: a cada 60 s le /api/notificacoes; string que ZEROU desde a ultima leitura do servidor (que roda a cada
   30 min, so de dia) vira badge no sino, um aviso no canto e, se a pessoa permitiu, notificacao do navegador. Vale em
   qualquer tela que tenha <span id="gc-sino"> — e assim quem esta olhando Thopen fica sabendo da queda na Athon.
   v2: os eventos sao AGRUPADOS por leitura + usina + inversor (uma string box que cai zera 20 strings de uma vez —
   20 linhas iguais nao ajudam ninguem) e cada item e um LINK: abre a tela do cliente na aba Strings, com a usina e
   o inversor abertos e a curva do dia do evento (deep link ?usina=&inversor=&dia=). O rodape diz quais fontes o
   servidor esta lendo e qual nao respondeu. "Visto" fica no navegador (localStorage), por pessoa. Sem som de proposito. */
(function () {
  if (document.documentElement.classList.contains("embed")) return;   // dentro da tela do cliente, o sino e o do pai
  var CHAVE = "gc.notif.visto", ULT = "gc.notif.ultimo", VISTOS = "gc.notif.vistos";
  var FONTE_ID = { pv: "thopen-pv", pg: "thopen-db", sunop: "athon", axis: "axis", owen: "2c", semp: "semp", alveslima: "alveslima", "2capi": "2capi" };
  var visto = "", ultimo = "", vistos = {}, grupos = [], aberto = false, meta = {};
  try {
    visto = localStorage.getItem(CHAVE) || ""; ultimo = localStorage.getItem(ULT) || "";
    vistos = JSON.parse(localStorage.getItem(VISTOS) || "{}") || {};
  } catch (e) { }

  var css = document.createElement("style");
  css.textContent = [
    ".gc-sino{position:relative;display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;border-radius:9px;",
    "border:1px solid rgba(255,255,255,.09);background:transparent;color:#c3cad7;cursor:pointer;transition:border-color .2s,color .2s}",
    ".gc-sino:hover{color:#fff;border-color:rgba(163,217,0,.45)}.gc-sino svg{width:17px;height:17px;display:block}",
    ".gc-sino.tem{color:#f2555a}",
    ".gc-badge{position:absolute;top:-7px;right:-7px;min-width:18px;height:18px;padding:0 5px;border-radius:9px;background:#f2555a;color:#fff;",
    "font:700 11px/18px 'IBM Plex Mono',Consolas,monospace;text-align:center;box-shadow:0 0 0 2px #090d18}",
    ".gc-notif-caixa{position:absolute;right:0;top:42px;width:390px;max-height:70vh;overflow:auto;z-index:90;border-radius:12px;",
    "background:linear-gradient(180deg,#1b2338,#161d30);border:1px solid rgba(255,255,255,.09);box-shadow:0 26px 54px rgba(0,0,0,.55);",
    "font-family:'Inter',system-ui,sans-serif;font-size:13px;color:#e9eef6;text-align:left}",
    ".gc-notif-cab{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:12px 14px;border-bottom:1px solid rgba(255,255,255,.09);font-size:10.5px;text-transform:uppercase;letter-spacing:.14em;font-weight:700;color:#767d92}",
    ".gc-notif-cab button{background:none;border:0;color:#a3d900;font:600 11px 'Inter',system-ui,sans-serif;cursor:pointer;letter-spacing:0;text-transform:none}",
    ".gc-notif-item{display:flex;gap:10px;padding:10px 14px;border-bottom:1px solid rgba(255,255,255,.06);color:inherit;text-decoration:none;transition:background .15s}",
    ".gc-notif-item:hover{background:rgba(163,217,0,.08)}",
    ".gc-notif-item:last-child{border-bottom:0}.gc-notif-item.novo{background:rgba(242,85,90,.07)}.gc-notif-item.novo:hover{background:rgba(242,85,90,.13)}",
    ".gc-notif-item .q{font-family:'IBM Plex Mono',Consolas,monospace;font-size:11.5px;color:#96a0b4;white-space:nowrap;padding-top:2px}",
    ".gc-notif-item b{color:#fff}.gc-notif-item .f{color:#96a0b4;font-size:12px;margin-top:2px}",
    ".gc-notif-item .ir{margin-left:auto;align-self:center;color:#767d92;font-size:14px;flex:none}.gc-notif-item:hover .ir{color:#a3d900}",
    ".gc-notif-vazio{padding:22px 14px;color:#96a0b4;text-align:center}",
    ".gc-notif-pe{padding:9px 14px;border-top:1px solid rgba(255,255,255,.09);font-family:'IBM Plex Mono',Consolas,monospace;font-size:11px;color:#767d92;line-height:1.5}",
    ".gc-notif-pe .ruim{color:#f5a623}",
    ".gc-toasts{position:fixed;right:18px;bottom:18px;z-index:120;display:flex;flex-direction:column;gap:10px;max-width:380px}",
    ".gc-toast{display:block;padding:12px 14px;border-radius:12px;background:linear-gradient(180deg,#1b2338,#161d30);border:1px solid rgba(242,85,90,.45);",
    "border-left:3px solid #f2555a;box-shadow:0 18px 44px rgba(0,0,0,.5);font-family:'Inter',system-ui,sans-serif;font-size:13px;color:#e9eef6;text-decoration:none;",
    "animation:gc-toast-in .35s cubic-bezier(.2,.7,.2,1)}",
    "a.gc-toast:hover{border-color:rgba(163,217,0,.55)}",
    ".gc-toast b{color:#fff}.gc-toast .f{color:#96a0b4;font-size:12px;margin-top:2px}",
    "@keyframes gc-toast-in{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}",
    "@media (prefers-reduced-motion:reduce){.gc-toast{animation:none}}"
  ].join("\n");
  document.head.appendChild(css);

  var SINO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    + '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/></svg>';

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function hora(iso) { return iso ? String(iso).slice(11, 16) : ""; }
  function dia(iso) { return iso ? String(iso).slice(8, 10) + "/" + String(iso).slice(5, 7) : ""; }
  function numOrd(a, b) { var x = parseFloat(String(a).replace(/[^\d.]/g, "")), y = parseFloat(String(b).replace(/[^\d.]/g, "")); return (isNaN(x) || isNaN(y)) ? String(a).localeCompare(String(b)) : x - y; }

  // uma linha por leitura + fonte + usina + inversor: "Ipixuna 2 · Inversor 2.7 · strings 13, 14 e 17 zeraram"
  function agrupar(lista) {
    var m = {}, ordem = [];
    lista.forEach(function (e) {
      // tipo "inv_padrao" (10/09): inversor que caiu do padrao dos 30 dias numa usina sem visao por string — um evento
      // por inversor e dia, sem lista de strings; o link abre o diagnostico da usina, nao a curva de strings
      var tipo = e.tipo || "string_zerou";
      var k = [e.quando, e.fonte, e.plant_id, e.inversor, tipo].join("|");
      if (!m[k]) { m[k] = { chave: k, quando: e.quando, tipo: tipo, fonte: e.fonte, rotulo: e.rotulo, cliente: e.cliente, usina: e.usina, plant_id: e.plant_id, inversor: e.inversor, strings: [], padrao: null }; ordem.push(k); }
      if (tipo === "inv_padrao") m[k].padrao = e; else m[k].strings.push(String(e.string));
    });
    return ordem.map(function (k) { return m[k]; });
  }
  function link(g) {
    if (g.tipo === "inv_padrao") return "/painel/usina/" + encodeURIComponent(g.plant_id) + "?fonte=" + encodeURIComponent(g.fonte || "pv") + "&nome=" + encodeURIComponent(g.usina || "");
    var fid = FONTE_ID[g.fonte];
    if (!fid) return "/tempo-real";
    var u = "/tempo-real/" + fid + "?view=strings";
    if (g.plant_id != null && g.plant_id !== "") u += "&usina=" + encodeURIComponent(g.plant_id);
    if (g.inversor) u += "&inversor=" + encodeURIComponent(g.inversor);
    if (g.quando) u += "&dia=" + String(g.quando).slice(0, 10);
    return u;
  }
  function textoStrings(g) {
    var s = g.strings.slice().sort(numOrd);
    if (s.length === 1) return "string " + s[0] + " zerou";
    if (s.length > 6) return s.length + " strings zeraram (" + s.slice(0, 4).join(", ") + "…)";
    return "strings " + s.slice(0, -1).join(", ") + " e " + s[s.length - 1] + " zeraram";
  }
  function textoPadrao(g) {
    var p = g.padrao || {}, r = Math.round(p.razao || 0), b = Math.round(p.base || 0), d = Math.round(p.delta || 0);
    var dia = p.dia ? " em " + String(p.dia).slice(8, 10) + "/" + String(p.dia).slice(5, 7) : "";
    return (p.status === "critico" ? "caiu para " : "abaixo do padrão: ") + r + "% do padrão de " + b + "% (" + (d > 0 ? "+" : "") + d + " pp" + dia + ")";
  }
  function texto(g) { return "<b>" + esc(g.usina || "?") + "</b>" + (g.inversor ? " · " + esc(g.inversor) : "") + " · " + esc(g.tipo === "inv_padrao" ? textoPadrao(g) : textoStrings(g)); }
  function fonte(g) { return esc((g.rotulo || g.fonte || "") + (g.cliente && g.cliente !== g.rotulo && (g.rotulo || "").indexOf(g.cliente) < 0 ? " · " + g.cliente : "")); }
  function novo(g) { return g.quando > visto && !vistos[g.chave]; }
  function marcaVisto(g) {
    vistos[g.chave] = 1;
    var ks = Object.keys(vistos); if (ks.length > 600) ks.slice(0, ks.length - 600).forEach(function (k) { delete vistos[k]; });
    try { localStorage.setItem(VISTOS, JSON.stringify(vistos)); } catch (e) { }
  }

  function montar(slot) {
    slot.style.position = "relative";
    slot.innerHTML = '<button class="gc-sino" type="button" title="Strings que zeraram" aria-label="Notificações">' + SINO + '<span class="gc-badge" hidden></span></button><div class="gc-notif-caixa" hidden></div>';
    var bt = slot.querySelector(".gc-sino"), caixa = slot.querySelector(".gc-notif-caixa");
    bt.addEventListener("click", function (ev) {
      ev.stopPropagation();
      aberto = !aberto; caixa.hidden = !aberto;
      if (aberto) {
        try { if (window.Notification && Notification.permission === "default") Notification.requestPermission(); } catch (e) { }
        render();
      }
    });
    document.addEventListener("click", function () { if (aberto) { aberto = false; caixa.hidden = true; } });
    caixa.addEventListener("click", function (ev) {
      ev.stopPropagation();
      var a = ev.target.closest("a.gc-notif-item");
      if (a) { var g = grupos.filter(function (x) { return x.chave === a.getAttribute("data-chave"); })[0]; if (g) marcaVisto(g); }   // navega em seguida
    });
    render();
  }

  function rodape() {
    var f = meta.fontes || {}, ks = Object.keys(f);
    var l1 = (meta.ultima ? "última leitura " + dia(meta.ultima) + " " + hora(meta.ultima) : "sem leitura ainda") + " · a cada " + (meta.intervalo || 30) + " min" + (meta.de_dia === false ? " · à noite não conta" : "");
    if (!ks.length) return l1;
    var lidas = ks.filter(function (k) { return f[k].ok; }).map(function (k) { return f[k].rotulo; });
    var fora = ks.filter(function (k) { return !f[k].ok; }).map(function (k) { return f[k].rotulo; });
    return l1 + "<br>lendo " + esc(lidas.join(", ")) + (fora.length ? '<br><span class="ruim">sem resposta: ' + esc(fora.join(", ")) + "</span>" : "");
  }

  function render() {
    var slot = document.getElementById("gc-sino"); if (!slot || !slot.firstChild) return;
    var bt = slot.querySelector(".gc-sino"), badge = slot.querySelector(".gc-badge"), caixa = slot.querySelector(".gc-notif-caixa");
    var naoVistos = grupos.filter(novo);
    badge.hidden = !naoVistos.length; badge.textContent = naoVistos.length > 99 ? "99+" : String(naoVistos.length);
    bt.classList.toggle("tem", naoVistos.length > 0);
    var ult = grupos.slice(-40).reverse();
    caixa.innerHTML = '<div class="gc-notif-cab"><span>Alertas · strings e inversores</span>' + (naoVistos.length ? '<button type="button" id="gc-notif-lidas">marcar como vistas</button>' : "") + "</div>"
      + (ult.length ? ult.map(function (g) {
          return '<a class="gc-notif-item' + (novo(g) ? " novo" : "") + '" href="' + esc(link(g)) + '" data-chave="' + esc(g.chave) + '" title="' + (g.tipo === "inv_padrao" ? "abrir o diagnóstico da usina" : "abrir a curva deste inversor no dia") + '"><span class="q">' + dia(g.quando) + " " + hora(g.quando) + "</span><span>" + texto(g) + '<div class="f">' + fonte(g) + '</div></span><span class="ir" aria-hidden="true">›</span></a>';
        }).join("") : '<div class="gc-notif-vazio">Nenhuma queda nova desde a última leitura.</div>')
      + '<div class="gc-notif-pe">' + rodape() + "</div>";
    var ml = document.getElementById("gc-notif-lidas");
    if (ml) ml.addEventListener("click", function () { visto = new Date().toISOString().slice(0, 19); try { localStorage.setItem(CHAVE, visto); } catch (e) { } render(); });
  }

  function toasts(novos) {
    var caixa = document.querySelector(".gc-toasts");
    if (!caixa) { caixa = document.createElement("div"); caixa.className = "gc-toasts"; document.body.appendChild(caixa); }
    novos.slice(-4).forEach(function (g) {
      var t = document.createElement("a"); t.className = "gc-toast"; t.href = link(g); t.title = "abrir a curva deste inversor";
      t.innerHTML = texto(g) + " às " + hora(g.quando) + '<div class="f">' + fonte(g) + "</div>";
      t.addEventListener("click", function () { marcaVisto(g); });
      caixa.appendChild(t);
      setTimeout(function () { t.style.transition = "opacity .4s"; t.style.opacity = "0"; setTimeout(function () { t.remove(); }, 450); }, 9000);
    });
    if (novos.length > 4) {
      var m = document.createElement("div"); m.className = "gc-toast"; m.innerHTML = "<b>+" + (novos.length - 4) + "</b> outros inversores com string zerada. Veja no sino.";
      caixa.appendChild(m); setTimeout(function () { m.remove(); }, 9000);
    }
    try {
      if (window.Notification && Notification.permission === "granted") {
        new Notification("Alertas · " + novos.length + (novos.length === 1 ? " inversor" : " inversores"),
          { body: novos.slice(0, 3).map(function (g) { return (g.rotulo || g.fonte) + " · " + g.usina + (g.inversor ? " · " + g.inversor : "") + " · " + textoStrings(g); }).join("\n"), silent: true });
      }
    } catch (e) { }
  }

  function ler() {
    fetch("/api/notificacoes", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (d) {
      meta = { ultima: d.ultima_leitura, intervalo: d.intervalo_min, de_dia: d.de_dia, fontes: d.fontes || {} };
      var lista = d.eventos || [];
      grupos = agrupar(lista);
      var novos = ultimo ? grupos.filter(function (g) { return g.quando > ultimo; }) : [];
      if (lista.length) { ultimo = lista[lista.length - 1].quando; try { localStorage.setItem(ULT, ultimo); } catch (e) { } }
      if (novos.length) toasts(novos);
      render();
    }).catch(function () { });
  }

  function garantir() {
    var slot = document.getElementById("gc-sino");
    if (slot && !slot.firstChild) montar(slot);            // o Monitoramento redesenha o cabecalho a cada render
  }
  garantir(); ler();
  setInterval(garantir, 1000);
  setInterval(ler, 60000);
})();
