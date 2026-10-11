/* plataforma/aviso_de_sessao.js — a sessão venceu no meio da tela (porta única com o Nexus, 10/10/2026).

   POR QUE EXISTE. A sessão que o Nexus abre nesta plataforma (o passe) vale 12 h fixas. Depois disso toda leitura de
   /api/ responde 401 e as telas que releem sozinhas desenhavam o erro como se fosse dado: o Painel NOC, que relê o
   /api/macro a cada 60 s, mostrava "Energia perdida 0,0 MWh" numa tela de NOC (auditoria de 10/10/2026, A5). Número que
   não veio não vira zero: confiabilidade do dado é a prioridade 1 do projeto.

   ONDE MORA. O app.py injeta este arquivo inline no <head> de toda página da plataforma (`_aviso_de_sessao_na_resposta`),
   depois do calço do prefixo e do calço do modo Nexus. Não vai por /static/ de propósito: com o Nexus na raiz, o Caddy
   manda /static/* ao Nexus (menos fonts, logos e notif.js), e um <script src> novo daria 404 no servidor.

   O QUE FAZ:
   - todo fetch de uma rota /api/ DESTE endereço que volta 401 (o portão: "não autenticado") liga o aviso de sessão;
   - na moldura do Nexus (a página em modo Nexus logo abaixo do topo), a faixa "Sessão vencida: abrindo de novo pelo
     Nexus" e o aviso à moldura no mesmo formato do nexus:rota: postMessage({tipo: "nexus:sessao-vencida", caminho},
     a origem deste endereço), no máximo 1 vez a cada 60 s. A moldura pede um passe novo e reabre o mesmo ?p=;
   - fora do Nexus, a faixa "Sessão vencida: entre de novo", com o link do login que volta a esta tela;
   - o /monitor?embed=1 que o Tempo real embute não fala sozinho: passa o aviso à página de cima, que é quem a moldura
     conhece (e o caminho que importa é o dela);
   - gcSessaoDaPlataforma.falhou(motivo, quando[, fim]) / voltou(): a faixa "não atualizou, os números na tela são de ..."
     que as telas que releem sozinhas mostram quando a leitura falha por outro motivo (rede, 500). `fim` (texto) troca o
     resto da frase, para a tela que lê uma vez e não tem número velho a mostrar nem vai tentar de novo sozinha: o
     Diagnóstico (10/10/2026) diz "o que depende dessas leituras está com — (sem leitura): não é usina parada.";
   - gcSessaoDaPlataforma.semAdmin: quem entrou pelo Nexus sem ser administrador (o /tokens responde "Só
     administradores" para ela), e tokens(texto), que troca o "Renove na tela Tokens" pelo caminho que ela tem.

   Cada tela continua dona do próprio número: este arquivo só avisa. Quem guarda o último valor é a tela. */
(function () {
  "use strict";
  if (window.gcSessaoDaPlataforma) return;
  var SEM_ADMIN = /*SEM_ADMIN*/false;   // o app.py troca por true para quem entrou pelo Nexus sem ser administrador
  var INTERVALO_MS = 60000;             // a moldura reabre no máximo 1 vez a cada 60 s; aqui também não insiste mais
  var DICA_MS = 15000;                  // passou disso e a moldura não reabriu (Nexus antigo, ou dentro dos 60 s): diz o que fazer
  var avisouEm = 0, faixa = null, estado = "", dicaMenu = false;

  function prefixo() { return window.APP_PREFIX || ""; }
  // O caminho desta tela sem o prefixo, como o calço do modo Nexus o manda (o Nexus o usa como ?p=).
  function rota() {
    var p = prefixo(), c = location.pathname;
    if (p && c.indexOf(p) === 0) c = c.slice(p.length) || "/";
    return c + location.search;
  }
  // Só /api/ deste endereço: 401 de outro serviço (o gêmeo, o OS Creator Web pelo proxy) não é a sessão daqui.
  function daApi(u) {
    var url;
    try { url = new URL(typeof u === "string" ? u : (u && u.url) || "", location.href); } catch (e) { return false; }
    if (url.origin !== location.origin) return false;
    var c = url.pathname, p = prefixo();
    if (p && c.indexOf(p + "/") === 0) c = c.slice(p.length);
    return c.indexOf("/api/") === 0;
  }
  function deCima() {
    try {
      if (window.parent !== window && window.parent.gcSessaoDaPlataforma) return window.parent.gcSessaoDaPlataforma;
    } catch (e) { }                     // pai de outra origem: não é a plataforma
    return null;
  }
  // Modo Nexus = o servidor pôs o calço do modo Nexus nesta página (ele marca window.gcModoNexus), e a mesma régua dele:
  // só a página de cima da moldura fala com ela.
  function naMoldura() {
    return window.gcModoNexus === true && window.parent !== window && window.parent === window.top;
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function mostra(html, tipo) {
    estado = tipo;
    if (!faixa) {
      faixa = document.createElement("div");
      faixa.id = "gc-sessao-faixa";
      faixa.setAttribute("role", "status");
      faixa.setAttribute("aria-live", "polite");
      // tema navy da plataforma; âmbar = dá para agir (a cor diz a severidade, sem ícone). Centrada por left/right 0 e
      // margin auto: com left:50% a caixa encolhia para metade da tela (provado no navegador, 10/10/2026)
      faixa.style.cssText = "position:fixed;top:10px;left:0;right:0;margin:0 auto;width:fit-content;box-sizing:border-box;" +
        "z-index:2147483000;max-width:min(760px,calc(100vw - 24px));padding:9px 16px;border-radius:10px;" +
        "background:#161d30;color:#e9eef6;" +
        "border:1px solid rgba(245,166,35,.45);border-left:3px solid #f5a623;box-shadow:0 14px 34px rgba(0,0,0,.5);" +
        "font:500 13px/1.45 'Inter',system-ui,-apple-system,sans-serif;text-align:left";
      (document.body || document.documentElement).appendChild(faixa);
    }
    faixa.innerHTML = html;
    faixa.hidden = false;
  }
  function textoVencida() {
    if (naMoldura()) {
      return "<b>Sessão vencida:</b> abrindo de novo pelo Nexus. Os números na tela são os da última leitura." +
        (dicaMenu ? " Se não abrir, clique de novo no item do menu do Nexus." : "");
    }
    var login = prefixo() + "/login?next=" + encodeURIComponent(rota());
    return "<b>Sessão vencida:</b> entre de novo. Os números na tela são os da última leitura. " +
      "<a href=\"" + esc(login) + "\" target=\"_top\" style=\"color:#a3d900;font-weight:600\">Entrar</a>";
  }
  function vencida() {
    var cima = deCima();
    // A de cima mostra a faixa e avisa a moldura; esta só se lembra, para o "não atualizou" da própria tela não cobrir
    // a explicação (provado no navegador, 10/10/2026: a faixa de baixo dizia "Não atualizou (sessão vencida)").
    if (cima) { try { cima.vencida(); estado = "vencida"; return; } catch (e) { } }
    mostra(textoVencida(), "vencida");
    if (!naMoldura()) return;
    var agora = Date.now();
    if (agora - avisouEm < INTERVALO_MS) return;
    avisouEm = agora;
    try { window.parent.postMessage({ tipo: "nexus:sessao-vencida", caminho: rota() }, location.origin); } catch (e) { }
    setTimeout(function () { if (estado === "vencida") { dicaMenu = true; mostra(textoVencida(), "vencida"); } }, DICA_MS);
  }
  // A leitura falhou por outro motivo (rede, 500): a tela segue com o último número, e a faixa diz desde quando.
  // `fim`: a tela diz o resto da frase (o Diagnóstico lê uma vez: não tem "última leitura" nem tenta de novo sozinho).
  function falhou(motivo, quando, fim) {
    if (estado === "vencida") return;   // a sessão explica tudo; não troca a faixa dela
    mostra("<b>Não atualizou</b>" + (motivo ? " (" + esc(motivo) + ")" : "") + (fim ? ": " + esc(fim) :
      (quando ? ": os números na tela são " + esc(quando) + "." : ": a tela segue com a última leitura.") +
      " Tento de novo sozinho."), "falha");
  }
  function voltou() {
    if (faixa && estado) { faixa.hidden = true; faixa.innerHTML = ""; }
    estado = ""; dicaMenu = false;
  }
  // B12 (10/10/2026): "Renove na tela Tokens" para quem leva "Só administradores" ao abrir o /tokens.
  function tokens(texto) {
    if (!SEM_ADMIN) return texto;
    return String(texto == null ? "" : texto)
      .replace(/Renove na tela Tokens\.?/g, "Peça a um administrador do Nexus para renovar (Chaves das fontes).")
      .replace(/Cole um na tela Tokens\.?/g, "Peça a um administrador do Nexus para colar um (Chaves das fontes).");
  }

  var original = window.fetch;
  if (original) {
    window.fetch = function (u) {
      var api = daApi(u), p = original.apply(window, arguments);
      return api ? p.then(function (r) { if (r && r.status === 401) vencida(); return r; }) : p;
    };
  }
  window.gcSessaoDaPlataforma = {
    vencida: vencida, falhou: falhou, voltou: voltou, tokens: tokens, semAdmin: SEM_ADMIN, rota: rota,
    estado: function () { return estado; }
  };
})();
