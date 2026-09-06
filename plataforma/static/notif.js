/* plataforma/static/notif.js — sino de notificacoes (05/09/2026, pedido do Levi).
   O que faz: a cada 60 s le /api/notificacoes; string que ZEROU desde a ultima leitura do servidor (que roda a cada
   30 min, so de dia) vira badge no sino, um aviso no canto e, se a pessoa permitiu, notificacao do navegador. Vale em
   qualquer tela que tenha <span id="gc-sino"> — e assim quem esta olhando Thopen fica sabendo da queda na Athon.
   "Visto" fica no navegador (localStorage), por pessoa. Sem som de proposito. */
(function () {
  if (document.documentElement.classList.contains("embed")) return;   // dentro da tela do cliente, o sino e o do pai
  var CHAVE = "gc.notif.visto", ULT = "gc.notif.ultimo";
  var visto = "", ultimo = "", eventos = [], aberto = false;
  try { visto = localStorage.getItem(CHAVE) || ""; ultimo = localStorage.getItem(ULT) || ""; } catch (e) { }

  var css = document.createElement("style");
  css.textContent = [
    ".gc-sino{position:relative;display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;border-radius:9px;",
    "border:1px solid rgba(255,255,255,.09);background:transparent;color:#c3cad7;cursor:pointer;transition:border-color .2s,color .2s}",
    ".gc-sino:hover{color:#fff;border-color:rgba(163,217,0,.45)}.gc-sino svg{width:17px;height:17px;display:block}",
    ".gc-sino.tem{color:#f2555a}",
    ".gc-badge{position:absolute;top:-7px;right:-7px;min-width:18px;height:18px;padding:0 5px;border-radius:9px;background:#f2555a;color:#fff;",
    "font:700 11px/18px 'IBM Plex Mono',Consolas,monospace;text-align:center;box-shadow:0 0 0 2px #090d18}",
    ".gc-notif-caixa{position:absolute;right:0;top:42px;width:360px;max-height:70vh;overflow:auto;z-index:90;border-radius:12px;",
    "background:linear-gradient(180deg,#1b2338,#161d30);border:1px solid rgba(255,255,255,.09);box-shadow:0 26px 54px rgba(0,0,0,.55);",
    "font-family:'Inter',system-ui,sans-serif;font-size:13px;color:#e9eef6;text-align:left}",
    ".gc-notif-cab{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:12px 14px;border-bottom:1px solid rgba(255,255,255,.09);font-size:10.5px;text-transform:uppercase;letter-spacing:.14em;font-weight:700;color:#767d92}",
    ".gc-notif-cab button{background:none;border:0;color:#a3d900;font:600 11px 'Inter',system-ui,sans-serif;cursor:pointer;letter-spacing:0;text-transform:none}",
    ".gc-notif-item{display:flex;gap:10px;padding:10px 14px;border-bottom:1px solid rgba(255,255,255,.06)}",
    ".gc-notif-item:last-child{border-bottom:0}.gc-notif-item.novo{background:rgba(242,85,90,.07)}",
    ".gc-notif-item .q{font-family:'IBM Plex Mono',Consolas,monospace;font-size:11.5px;color:#96a0b4;white-space:nowrap;padding-top:2px}",
    ".gc-notif-item b{color:#fff}.gc-notif-item .f{color:#96a0b4;font-size:12px}",
    ".gc-notif-vazio{padding:22px 14px;color:#96a0b4;text-align:center}",
    ".gc-notif-pe{padding:9px 14px;border-top:1px solid rgba(255,255,255,.09);font-family:'IBM Plex Mono',Consolas,monospace;font-size:11px;color:#767d92}",
    ".gc-toasts{position:fixed;right:18px;bottom:18px;z-index:120;display:flex;flex-direction:column;gap:10px;max-width:380px}",
    ".gc-toast{padding:12px 14px;border-radius:12px;background:linear-gradient(180deg,#1b2338,#161d30);border:1px solid rgba(242,85,90,.45);",
    "border-left:3px solid #f2555a;box-shadow:0 18px 44px rgba(0,0,0,.5);font-family:'Inter',system-ui,sans-serif;font-size:13px;color:#e9eef6;",
    "animation:gc-toast-in .35s cubic-bezier(.2,.7,.2,1)}",
    ".gc-toast b{color:#fff}.gc-toast .f{color:#96a0b4;font-size:12px;margin-top:2px}",
    "@keyframes gc-toast-in{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}",
    "@media (prefers-reduced-motion:reduce){.gc-toast{animation:none}}"
  ].join("\n");
  document.head.appendChild(css);

  var SINO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    + '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/></svg>';

  function hora(iso) { return iso ? String(iso).slice(11, 16) : ""; }
  function dia(iso) { return iso ? String(iso).slice(8, 10) + "/" + String(iso).slice(5, 7) : ""; }
  function texto(e) { return "<b>" + (e.usina || "?") + "</b>" + (e.inversor ? " · " + e.inversor : "") + " · string " + (e.string || "?") + " zerou"; }
  function fonte(e) { return (e.rotulo || e.fonte || "") + (e.cliente && e.cliente !== e.rotulo ? " · " + e.cliente : ""); }

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
    caixa.addEventListener("click", function (ev) { ev.stopPropagation(); });
    render();
  }

  function render() {
    var slot = document.getElementById("gc-sino"); if (!slot || !slot.firstChild) return;
    var bt = slot.querySelector(".gc-sino"), badge = slot.querySelector(".gc-badge"), caixa = slot.querySelector(".gc-notif-caixa");
    var naoVistos = eventos.filter(function (e) { return e.quando > visto; });
    badge.hidden = !naoVistos.length; badge.textContent = naoVistos.length > 99 ? "99+" : String(naoVistos.length);
    bt.classList.toggle("tem", naoVistos.length > 0);
    var ult = eventos.slice(-30).reverse();
    caixa.innerHTML = '<div class="gc-notif-cab"><span>Strings que zeraram</span>' + (naoVistos.length ? '<button type="button" id="gc-notif-lidas">marcar como vistas</button>' : "") + "</div>"
      + (ult.length ? ult.map(function (e) {
          return '<div class="gc-notif-item' + (e.quando > visto ? " novo" : "") + '"><span class="q">' + dia(e.quando) + " " + hora(e.quando) + "</span><span>" + texto(e) + '<div class="f">' + fonte(e) + "</div></span></div>";
        }).join("") : '<div class="gc-notif-vazio">Nenhuma queda nova desde a última leitura.</div>')
      + '<div class="gc-notif-pe">' + (meta.ultima ? "última leitura " + hora(meta.ultima) : "sem leitura ainda") + " · a cada " + (meta.intervalo || 30) + " min" + (meta.de_dia === false ? " · à noite não conta" : "") + "</div>";
    var ml = document.getElementById("gc-notif-lidas");
    if (ml) ml.addEventListener("click", function () { visto = new Date().toISOString().slice(0, 19); try { localStorage.setItem(CHAVE, visto); } catch (e) { } render(); });
  }

  var meta = {};
  function toasts(novos) {
    var caixa = document.querySelector(".gc-toasts");
    if (!caixa) { caixa = document.createElement("div"); caixa.className = "gc-toasts"; document.body.appendChild(caixa); }
    novos.slice(-4).forEach(function (e) {
      var t = document.createElement("div"); t.className = "gc-toast";
      t.innerHTML = texto(e) + " às " + hora(e.quando) + '<div class="f">' + fonte(e) + "</div>";
      caixa.appendChild(t);
      setTimeout(function () { t.style.transition = "opacity .4s"; t.style.opacity = "0"; setTimeout(function () { t.remove(); }, 450); }, 9000);
    });
    if (novos.length > 4) {
      var m = document.createElement("div"); m.className = "gc-toast"; m.innerHTML = "<b>+" + (novos.length - 4) + "</b> outras strings zeraram. Veja no sino.";
      caixa.appendChild(m); setTimeout(function () { m.remove(); }, 9000);
    }
    try {
      if (window.Notification && Notification.permission === "granted") {
        new Notification("Strings zeraram · " + novos.length, { body: novos.slice(0, 3).map(function (e) { return (e.rotulo || e.fonte) + " · " + e.usina + " · string " + e.string; }).join("\n"), silent: true });
      }
    } catch (e) { }
  }

  function ler() {
    fetch("/api/notificacoes", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (d) {
      meta = { ultima: d.ultima_leitura, intervalo: d.intervalo_min, de_dia: d.de_dia };
      var lista = d.eventos || [];
      var novos = ultimo ? lista.filter(function (e) { return e.quando > ultimo; }) : [];
      eventos = lista;
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
