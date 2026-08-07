// ==UserScript==
// @name         GridCo - Auto-token PV Plataforma -> Dashboard
// @namespace    gridco.pv.trackers
// @version      1.1
// @description  Captura o JWT (x-auth-token-update) da PV Plataforma e o envia sozinho ao dashboard (localhost:5050), renovando o token dos Trackers/Curva sem copiar e colar. Dispara quando a Plataforma esta aberta.
// @author       GridCo Performance
// @match        https://plataforma.pvoperation.com/*
// @run-at       document-start
// @grant        GM_xmlhttpRequest
// @connect      localhost
// @connect      127.0.0.1
// @noframes
// ==/UserScript==

(function () {
  'use strict';

  // ----------------------------------------------------------------------------
  // CONFIG: para onde mandar o token. O dashboard roda na MESMA maquina ->
  // localhost:5050 e estavel (a URL do tunel Cloudflare muda, nao usar aqui).
  // Se um dia rodar a Plataforma noutra maquina, troque por: https://SEU-TUNEL.trycloudflare.com
  var DASH_URL = 'http://localhost:5050/api/pv/trackers/token';
  var SCAN_MS  = 5 * 60 * 1000;   // varredura de seguranca a cada 5 min
  // ----------------------------------------------------------------------------

  var ultimoEnviado = '';

  // exp do JWT (>0 = JWT valido com expiracao). Filtra lixo: so manda token de verdade.
  function jwtExp(tok) {
    try {
      var p = String(tok || '').split('.');
      if (p.length !== 3) return 0;
      var b = p[1].replace(/-/g, '+').replace(/_/g, '/');
      b += '==='.slice((b.length + 3) % 4);
      var pl = JSON.parse(atob(b));
      return (pl && pl.exp) ? Number(pl.exp) : 0;
    } catch (e) { return 0; }
  }

  function enviar(tok) {
    tok = (tok || '').trim();
    if (!tok || tok === ultimoEnviado) return;     // dedup: so reenvia se mudou
    if (!jwtExp(tok)) return;                       // ignora valores que nao sao JWT
    ultimoEnviado = tok;
    GM_xmlhttpRequest({
      method: 'POST',
      url: DASH_URL,
      headers: { 'Content-Type': 'application/json' },
      data: JSON.stringify({ token: tok }),
      timeout: 12000,
      onload:  function (r) { toast(r.status === 200 ? 'token enviado ao dashboard' : 'falha ao enviar (HTTP ' + r.status + ')'); },
      onerror: function ()  { ultimoEnviado = ''; toast('dashboard offline em ' + DASH_URL); },
      ontimeout: function () { ultimoEnviado = ''; toast('dashboard nao respondeu'); }
    });
  }

  // 1) FONTE PRINCIPAL: intercepta o header que o proprio app envia nas chamadas
  //    a API. Cobre axios (usa XHR por baixo) e fetch. Pega exatamente o token em uso.
  var _set = XMLHttpRequest.prototype.setRequestHeader;
  XMLHttpRequest.prototype.setRequestHeader = function (k, v) {
    try { if (String(k).toLowerCase() === 'x-auth-token-update' && v) enviar(v); } catch (e) {}
    return _set.apply(this, arguments);
  };

  var _fetch = window.fetch;
  if (_fetch) {
    window.fetch = function (input, init) {
      try {
        if (input && input.headers && typeof input.headers.get === 'function') {
          var ti = input.headers.get('x-auth-token-update'); if (ti) enviar(ti);
        }
        var h = init && init.headers;
        if (h) {
          if (typeof h.get === 'function') { var t = h.get('x-auth-token-update'); if (t) enviar(t); }
          else { for (var k in h) if (String(k).toLowerCase() === 'x-auth-token-update') enviar(h[k]); }
        }
      } catch (e) {}
      return _fetch.apply(this, arguments);
    };
  }

  // 2) REDE DE SEGURANCA: varre localStorage/sessionStorage por um JWT valido.
  //    Cobre a aba aberta e parada (sem chamadas), e o boot antes da 1a requisicao.
  function varrer() {
    try {
      [localStorage, sessionStorage].forEach(function (st) {
        for (var i = 0; i < st.length; i++) {
          var v = st.getItem(st.key(i));
          if (!v) continue;
          if (v.split('.').length === 3 && jwtExp(v)) { enviar(v); continue; }
          if (v.charAt(0) === '{' || v.charAt(0) === '[') {  // token guardado dentro de um JSON
            try {
              var o = JSON.parse(v);
              (function walk(x) {
                if (!x) return;
                if (typeof x === 'string') { if (x.split('.').length === 3 && jwtExp(x)) enviar(x); return; }
                if (typeof x === 'object') for (var kk in x) walk(x[kk]);
              })(o);
            } catch (e) {}
          }
        }
      });
    } catch (e) {}
  }
  varrer();
  setInterval(varrer, SCAN_MS);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) varrer(); });

  // aviso visual discreto (sem emoji)
  function toast(msg) {
    try {
      var run = function () {
        var d = document.createElement('div');
        d.textContent = 'GridCo: ' + msg;
        d.style.cssText = 'position:fixed;z-index:2147483647;right:16px;bottom:16px;' +
          'background:#0b3b2e;color:#fff;font:13px/1.3 Segoe UI,Arial,sans-serif;' +
          'padding:8px 12px;border-radius:6px;box-shadow:0 2px 10px rgba(0,0,0,.35);opacity:.97';
        document.body.appendChild(d);
        setTimeout(function () { d.style.transition = 'opacity .4s'; d.style.opacity = '0'; }, 3200);
        setTimeout(function () { d.remove(); }, 3700);
      };
      if (document.body) run(); else document.addEventListener('DOMContentLoaded', run);
    } catch (e) {}
  }
})();
