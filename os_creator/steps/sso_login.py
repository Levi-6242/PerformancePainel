"""Login SSO/Microsoft via navegador embutido (QtWebEngine).

O usuário entra no Fracttal normalmente (inclusive pela Microsoft) numa janela embutida; o app
CAPTURA o token de sessão automaticamente — sem o usuário precisar mexer em token nenhum.

Como captura: um script injetado no início de cada documento intercepta o header
`Authorization: Bearer <jwt>` das requisições do app web (XHR/fetch) e também varre o localStorage
por um JWT. O Python faz polling via runJavaScript; ao achar um JWT válido, fecha e devolve o token.
"""
from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript

FRACTTAL_URL = "https://app.fracttal.com/"

# Injetado em DocumentCreation (antes do JS da página): hooka Authorization de XHR e fetch.
# IMPORTANTE: só captura de requisições pro fracttal.com (no login Microsoft passa por
# microsoftonline.com — não pode capturar o token da MS por engano).
_HOOK_JS = r"""
(function(){
  if (window.__gridco_hooked) return;
  window.__gridco_hooked = true;
  window.__gridco_token = "";
  function isFr(u){ return (''+u).indexOf("fracttal.com") >= 0; }
  function cap(v){
    try { if (v && (''+v).indexOf("Bearer ")===0) window.__gridco_token = (''+v).slice(7).trim(); } catch(e){}
  }
  var oOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(m, u){ try{ this.__fr = isFr(u); }catch(e){} return oOpen.apply(this, arguments); };
  var oSet = XMLHttpRequest.prototype.setRequestHeader;
  XMLHttpRequest.prototype.setRequestHeader = function(k, v){
    try { if (this.__fr && k && (''+k).toLowerCase()==="authorization") cap(v); } catch(e){}
    return oSet.apply(this, arguments);
  };
  var oF = window.fetch;
  if (oF) window.fetch = function(input, init){
    try {
      var u = (typeof input==='string') ? input : (input && input.url) || '';
      if (isFr(u)) {
        var h = init && init.headers, a = "";
        if (h) a = (h.get ? h.get("Authorization") : (h["Authorization"]||h["authorization"])) || "";
        cap(a);
      }
    } catch(e){}
    return oF.apply(this, arguments);
  };
})();
"""

# Lê o token capturado; senão, e SE estiver numa página do Fracttal, varre o localStorage por um JWT.
_POLL_JS = r"""
(function(){
  if (window.__gridco_token) return window.__gridco_token;
  try {
    if (location.hostname.indexOf("fracttal.com") < 0) return "";
    var re = /eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+/;
    for (var i=0;i<localStorage.length;i++){
      var v = localStorage.getItem(localStorage.key(i)) || "";
      var m = v.match(re);
      if (m) return m[0];
    }
  } catch(e){}
  return "";
})()
"""


def _parece_jwt(tok):
    return bool(tok) and tok.count(".") == 2 and len(tok) > 60


class SsoLoginDialog(QDialog):
    """Abre o Fracttal num navegador embutido; .token recebe o JWT capturado (None se cancelar)."""
    def __init__(self, parent=None, url=FRACTTAL_URL):
        super().__init__(parent)
        self.token = None
        self.setWindowTitle("Entrar no Fracttal — Microsoft / SSO")
        self.resize(560, 740)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        info = QLabel("  Entre normalmente (inclusive pela Microsoft). "
                      "Assim que logar, esta janela fecha sozinha.")
        info.setStyleSheet("color:#9aa0b4; background:#14161f; padding:8px;")
        lay.addWidget(info)

        self.profile = QWebEngineProfile(self)            # off-the-record (sessão só em memória)
        script = QWebEngineScript()
        script.setName("gridco_hook")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(True)
        script.setSourceCode(_HOOK_JS)
        self.profile.scripts().insert(script)

        self.page = QWebEnginePage(self.profile, self)
        self.view = QWebEngineView(self)
        self.view.setPage(self.page)
        lay.addWidget(self.view, 1)
        self.view.load(QUrl(url))

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(800)

    def _poll(self):
        self.page.runJavaScript(_POLL_JS, self._got)

    def _got(self, tok):
        if _parece_jwt(tok) and not self.token:
            self.token = tok
            self._timer.stop()
            self.accept()

    def closeEvent(self, e):
        self._timer.stop()
        super().closeEvent(e)
