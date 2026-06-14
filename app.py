import os
import re
import unicodedata
import calendar
import io
import csv
import time
import json
import threading
import requests
import pandas as pd
try:
    import psycopg2
except Exception:
    psycopg2 = None
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, render_template, jsonify, request as flask_request, send_file, session, redirect
from flask_compress import Compress

# Credenciais ficam fora do código: .env na raiz do projeto (ver .env.example)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True   # relê o index.html sem precisar reiniciar o servidor
app.jinja_env.auto_reload = True
Compress(app)   # gzip nas respostas (JSON do /api/data cai ~10x)

# ── Autenticação (senha única DASH_PASSWORD) ──────────────────────────────────
# Protege o dashboard quando exposto (Cloudflare Tunnel). Se DASH_PASSWORD estiver
# vazia, o app fica ABERTO (uso local). secret_key derivada da senha = estável entre
# reinícios sem precisar de outra variável.
import hashlib
DASH_PASSWORD = os.environ.get("DASH_PASSWORD", "").strip()
app.secret_key = os.environ.get("SECRET_KEY") or hashlib.sha256(
    ("gridco-dash-" + DASH_PASSWORD).encode()).hexdigest()
app.permanent_session_lifetime = timedelta(days=30)

_LOGIN_HTML = """<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Grid Co. — Acesso</title><style>
*{box-sizing:border-box;font-family:Inter,system-ui,Arial,sans-serif}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#0b0e16;color:#e5e7eb}
.card{background:#11151f;border:1px solid #1f2733;border-radius:14px;padding:34px 30px;width:320px;
box-shadow:0 10px 40px rgba(0,0,0,.4)}
h1{margin:0 0 4px;font-size:20px}.s{color:#9aa4b2;font-size:13px;margin:0 0 22px}
.lb{display:block;color:#cfd6e0;font-size:13px;margin-bottom:6px}
input{width:100%;padding:11px 12px;border-radius:9px;border:1px solid #2a3340;background:#0b0e16;
color:#fff;font-size:15px}
button{width:100%;margin-top:16px;padding:11px;border:0;border-radius:9px;background:#a3e635;
color:#0b0e16;font-weight:700;font-size:15px;cursor:pointer}
.err{color:#f87171;font-size:13px;margin-top:12px;min-height:16px;text-align:center}
.g{color:#a3e635}</style></head>
<body><form class="card" method="post" action="/login">
<img src="/static/logos/grid-h-branco.png" alt="Grid Co." style="height:38px;display:block;margin:0 auto 18px">
<p class="s" style="text-align:center">Monitoramento O&amp;M — acesso restrito</p>
<label class="lb">Senha</label><input type="password" name="senha" autofocus autocomplete="current-password">
<button type="submit">Entrar</button><div class="err">{{erro}}</div></form></body></html>"""


@app.before_request
def _auth_gate():
    if not DASH_PASSWORD:                       # sem senha → app aberto (dev local)
        return
    p = flask_request.path
    if p == "/login" or p == "/healthz" or p.startswith("/static/"):
        return
    if session.get("auth"):
        return
    if p.startswith("/api/"):
        return jsonify({"error": "não autenticado"}), 401
    return redirect("/login")


@app.route("/login", methods=["GET", "POST"])
def login():
    if flask_request.method == "POST":
        if (flask_request.form.get("senha") or "").strip() == DASH_PASSWORD:
            session.permanent = True
            session["auth"] = True
            return redirect("/")
        return _LOGIN_HTML.replace("{{erro}}", "Senha incorreta"), 401
    if session.get("auth"):
        return redirect("/")
    return _LOGIN_HTML.replace("{{erro}}", "")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/healthz")
def healthz():
    return "ok", 200


BASE_URL = "https://apipv.pvoperation.com.br/api/v1"
USERNAME = os.environ.get("PV_USERNAME", "")
PASSWORD = os.environ.get("PV_PASSWORD", "")
STRING_THRESHOLD       = 0.5    # corrente (A) p/ string ativa — fallback (não usado na regra atual)
STRING_ATIVA_FRAC      = 0.30   # API PV + SunOp (FORA de 9-15h): ativa se corrente >= isto × média(produzindo)
STRING_JANELA_MIN_A    = 1.0    # API PV + SunOp (DENTRO de 9-15h): ativa se corrente > isto (A)
STRING_JANELA_INI      = 9      # hora inicial da janela de sol confiável (inclusiva)
STRING_JANELA_FIM      = 15     # hora final da janela de sol confiável (exclusiva)
SUNOP_STRING_THRESHOLD = 0.5    # (legado) — SunOp agora usa a regra da média, igual à API PV
# Régua NOVA de strings (API PV) — instantânea, relativa à mediana do próprio inversor:
#   • trancada (marcada à mão) = MPPT sem string conectada → fora da contagem, pintada azul
#   • sem_corrente = corrente <= STRING_SEM_CORRENTE_A (string morta) → FALHA tipo 1 (vermelho)
#   • baixa_perf   = corrente < STRING_BAIXA_PERF_FRAC × mediana das demais → FALHA tipo 2 (laranja)
#   • se o inversor não está produzindo (mediana < STRING_INV_MIN_MED_A) nada é falha (noite/nublado)
STRING_SEM_CORRENTE_A  = 0.1    # A — abaixo disto a string conta como "sem corrente" (=0)
STRING_BAIXA_PERF_FRAC = 0.60   # < 60% da mediana das demais = baixa performance (40% abaixo)
STRING_INV_MIN_MED_A   = 0.5    # mediana do inversor abaixo disto = inversor parado → não classifica falha
_trancadas = set()              # chaves "plant_id|inv_id|Ipv" das strings trancadas (preenchido do estado)
TEMP_ALERT         = 65.0
COMM_ALERT_MINUTES = 30
CACHE_TTL          = 300   # segundos — cache de 5 min

_cache        = {"payload": None, "ts": 0.0}
_last_known   = {}   # plant_id → último resultado com dados reais
_etm_cache    = {"payload": None, "ts": 0.0}


# ── HTTP: sessão por thread com pool de conexões (keep-alive) ──────────────────
# Cada refresh dispara centenas de chamadas aos mesmos 4 hosts; reusar a conexão
# TCP/TLS corta o handshake de cada uma e reduz o throttling da API PV.
_http_local = threading.local()


def _http() -> requests.Session:
    s = getattr(_http_local, "s", None)
    if s is None:
        s = requests.Session()
        ad = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=32)
        s.mount("https://", ad)
        s.mount("http://", ad)
        _http_local.s = s
    return s


# ── Persistência: marca os caches como "sujos" p/ o loop salvar em disco ───────
_persist_flag = {"dirty": False}


def _persist_mark():
    _persist_flag["dirty"] = True


# ── Stale-while-revalidate genérico ─────────────────────────────────────────────
def _swr(cache: dict, build, force: bool = False) -> dict:
    """Serve o cache na hora e atualiza em thread de fundo quando expirou — nenhuma
    aba bloqueia o usuário na busca lenta. Exceções: force=1 (botão Atualizar) e a
    1ª carga continuam síncronos, pra quem pediu dado fresco receber dado fresco."""
    agora = time.time()
    payload = cache.get("payload")
    fresh = payload is not None and (agora - cache.get("ts", 0.0)) < CACHE_TTL
    lock = cache.setdefault("_lock", threading.Lock())
    if payload is None or force:
        with lock:
            # outro pedido pode ter acabado de construir enquanto esperávamos o lock
            if cache.get("payload") is not None and cache.get("ts", 0.0) >= agora:
                return dict(cache["payload"], stale=False)
            novo = build()
            cache["payload"] = novo
            cache["ts"] = time.time()
            _persist_mark()
            return dict(novo, stale=False)
    if not fresh:
        def _bg():
            if not lock.acquire(blocking=False):
                return                       # já tem refresh em andamento
            try:
                cache["payload"] = build()
                cache["ts"] = time.time()
                _persist_mark()
            except Exception as e:
                print(f"[swr] refresh em fundo falhou: {e}")
            finally:
                lock.release()
        threading.Thread(target=_bg, daemon=True).start()
    return dict(payload, stale=not fresh)

# ── SunOp ─────────────────────────────────────────────────────────────────────
SUNOP_CONFIG  = "https://gridco-api.sunop.net/api"
SUNOP_DATA    = "https://gridco-api.sunop.net/data"
_sunop_token  = {"token": os.environ.get("SUNOP_TOKEN", "")}
_sunop_meta      = {}        # plant_name → metadata dict
_sunop_cache     = {"payload": None, "ts": 0.0}
_sunop_etm_cache = {"payload": None, "ts": 0.0}

# Limite de inversores por planta (após esse nº não há dados reais).
# Ex.: MTS100 só tem dados até o INV_40 — inversores acima são descartados.
SUNOP_INV_MAX = {
    "MTS100": 40,
}

# ── SolarEdge / RenoGrid ───────────────────────────────────────────────────────
SE_BASE          = "https://monitoring.solaredge.com"
SE_COOKIE_PATH   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "se_cookie.txt")
SE_CREDS_PATH    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "se_credentials.txt")
SE_COGNITO_POOL  = os.environ.get("SE_COGNITO_POOL",   "eu-central-1_fVUTz39em")
SE_COGNITO_CLIENT= os.environ.get("SE_COGNITO_CLIENT", "ugfnsujd3384sshcjehaphlh3")
SE_STRING_MIN_W  = 0.0      # potência (W) mínima p/ considerar a string "ativa" (> que isso)
_se_cookie       = {"token": "", "exp": 0.0}
_se_login_lock   = threading.Lock()
_se_cache        = {"payload": None, "ts": 0.0}
_se_plant_cache  = {}       # site_id → {"payload":..., "ts":...} (drill-down)


def _se_credentials():
    u = os.environ.get("SE_USERNAME", ""); p = os.environ.get("SE_PASSWORD", "")
    if u and p:
        return u, p
    try:
        with open(SE_CREDS_PATH, encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        return lines[0], lines[1]
    except Exception:
        return "", ""


def _jwt_exp(token: str) -> float:
    import base64
    try:
        p = token.split(".")[1]; p += "=" * (-len(p) % 4)
        return float(json.loads(base64.urlsafe_b64decode(p)).get("exp", 0))
    except Exception:
        return 0.0


def _se_login() -> str:
    """Login SRP no AWS Cognito → access_token fresco (= cookie se_monitoring_auth)."""
    from pycognito import Cognito
    user, pw = _se_credentials()
    if not (user and pw):
        raise RuntimeError("credenciais SolarEdge ausentes (se_credentials.txt / SE_USERNAME+SE_PASSWORD)")
    c = Cognito(SE_COGNITO_POOL, SE_COGNITO_CLIENT, username=user)
    c.authenticate(password=pw)
    _se_cookie["token"] = c.access_token
    _se_cookie["exp"]   = _jwt_exp(c.access_token)
    try:   # persiste p/ fallback
        with open(SE_COOKIE_PATH, "w", encoding="utf-8") as f:
            f.write(f"se_monitoring_auth={c.access_token}")
    except Exception:
        pass
    mins = int((_se_cookie["exp"] - time.time()) / 60)
    print(f"[SolarEdge] token renovado via Cognito (válido por ~{mins} min)")
    return c.access_token


def _get_se_cookie() -> str:
    """Cookie SolarEdge — renova automaticamente via Cognito quando expira."""
    tok, exp = _se_cookie.get("token"), _se_cookie.get("exp", 0)
    if tok and time.time() < exp - 120:
        return f"se_monitoring_auth={tok}"
    with _se_login_lock:
        tok, exp = _se_cookie.get("token"), _se_cookie.get("exp", 0)
        if tok and time.time() < exp - 120:        # outro thread já renovou
            return f"se_monitoring_auth={tok}"
        try:
            return f"se_monitoring_auth={_se_login()}"
        except Exception as e:
            print(f"[SolarEdge] login automático falhou: {e}")
    # Fallback: cookie manual do arquivo (se houver)
    try:
        with open(SE_COOKIE_PATH, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def _se_headers() -> dict:
    return {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "origin": SE_BASE,
        "referer": f"{SE_BASE}/one",
        "user-agent": "Mozilla/5.0",
        "cookie": _get_se_cookie(),
    }


# ── Cadastro mestre: BD_Performance, aba "Equipamentos" ───────────────────────
# Fonte ÚNICA do cadastro (substitui a antiga planilha "Check Diário"):
#   • Usina / Usina Supervisório         → nome de exibição da usina (USINA_DISPLAY)
#   • Equipamento / Equip. Supervisório  → nome de exibição por inversor (EQUIP_NAMES)
#   • Strings Ativas                     → esperadas por inversor (ESPERADO_INV / ESPERADO)
#   • Full O&M                           → conjunto de usinas Full O&M (FULL_OM)
#   • Potência (kWp)                     → potência por inversor (POWER_INV)
# As chaves supervisório são exatamente os nomes que cada API usa (plant['nome'] / device_name).
# Usa SEMPRE a versão ONLINE (OneDrive→SharePoint, master da equipe); fallback p/ cópia local.
# O Desktop ("Área de Trabalho") pode estar DENTRO do OneDrive, então a pasta
# "Grid Co_ - 4. O&M" aparece tanto na raiz quanto sob "Área de Trabalho" — testamos os dois.
_BD_REL = os.path.join("Grid Co_ - 4. O&M", "6.Gerencial", "4. Gestão à vista",
                       "1. Banco de Dados", "BD_Performance.xlsx")
_OD_ROOT = os.path.join(os.path.expanduser("~"), "OneDrive - GRID CO")
_BD_PERF_ONLINE_CANDS = [p for p in [
    os.environ.get("BD_PERF_PATH"),
    os.path.join(_OD_ROOT, _BD_REL),
    os.path.join(_OD_ROOT, "Área de Trabalho", _BD_REL),
] if p]
_BD_PERF_LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "BD_Performance.xlsx")

# ── BD_Performance direto do SharePoint (Microsoft Graph, app-only) ────────────
# Elimina a dependência do OneDrive sincronizado (que desidrata e quebra o cadastro).
# Fluxo client credentials com permissão Sites.Selected: o app só enxerga o site
# liberado pelo TI. Enquanto as credenciais não existirem no .env, tudo continua
# funcionando pelo OneDrive/cópia local — o Graph é aditivo, não substitui o fallback.
AZ_TENANT_ID     = os.environ.get("AZ_TENANT_ID", "").strip()
AZ_CLIENT_ID     = os.environ.get("AZ_CLIENT_ID", "").strip()
AZ_CLIENT_SECRET = os.environ.get("AZ_CLIENT_SECRET", "").strip()
GRAPH_SITE_HOST  = os.environ.get("GRAPH_SITE_HOST", "").strip()   # ex.: gridco.sharepoint.com
GRAPH_SITE_PATH  = os.environ.get("GRAPH_SITE_PATH", "").strip()   # ex.: /sites/OeM
GRAPH_FILE_PATH  = os.environ.get("GRAPH_FILE_PATH", "").strip()   # caminho do .xlsx dentro da biblioteca
GRAPH_FILE_URL   = os.environ.get("GRAPH_FILE_URL", "").strip()    # URL do arquivo (Doc.aspx/compartilhar) — alternativa ao path
GRAPH_SYNC_SECS  = int(os.environ.get("GRAPH_SYNC_SECS", "300"))   # checa mudança a cada 5 min
_BD_PERF_GRAPH   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "BD_Performance_sharepoint.xlsx")
_graph_tok   = {"token": "", "exp": 0.0}
_graph_state = {"site_id": None, "etag": None, "ok_ts": 0.0}


def _graph_enabled() -> bool:
    # Endereça o arquivo por URL (endpoint /shares) OU por caminho (site + file_path).
    tem_arquivo = bool(GRAPH_FILE_URL) or bool(GRAPH_SITE_HOST and GRAPH_SITE_PATH and GRAPH_FILE_PATH)
    return bool(AZ_TENANT_ID and AZ_CLIENT_ID and AZ_CLIENT_SECRET and tem_arquivo)


def _graph_share_id(url: str) -> str:
    """Converte uma URL de compartilhamento do SharePoint no 'share id' do Graph
    (u! + base64url, sem padding) — aceita Doc.aspx, link de 'Copiar link', etc."""
    import base64
    b64 = base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")
    return "u!" + b64


def _graph_token() -> str:
    if _graph_tok["token"] and time.time() < _graph_tok["exp"] - 60:
        return _graph_tok["token"]
    r = _http().post(f"https://login.microsoftonline.com/{AZ_TENANT_ID}/oauth2/v2.0/token",
                     data={"client_id": AZ_CLIENT_ID, "client_secret": AZ_CLIENT_SECRET,
                           "scope": "https://graph.microsoft.com/.default",
                           "grant_type": "client_credentials"}, timeout=20)
    r.raise_for_status()
    j = r.json()
    _graph_tok["token"] = j["access_token"]
    _graph_tok["exp"]   = time.time() + int(j.get("expires_in", 3600))
    return _graph_tok["token"]


def _graph_site_id() -> str:
    if _graph_state["site_id"]:
        return _graph_state["site_id"]
    H = {"Authorization": f"Bearer {_graph_token()}"}
    r = _http().get(f"https://graph.microsoft.com/v1.0/sites/{GRAPH_SITE_HOST}:{GRAPH_SITE_PATH}",
                    headers=H, timeout=20)
    r.raise_for_status()
    _graph_state["site_id"] = r.json()["id"]
    return _graph_state["site_id"]


def _graph_sync_bd() -> bool:
    """Baixa o BD_Performance do SharePoint SE mudou (eTag) — senão não transfere nada.
    O download atualiza o mtime do arquivo, e a recarga automática por mtime
    (maybe_reload_equipamentos) faz o resto. → True se baixou versão nova."""
    H = {"Authorization": f"Bearer {_graph_token()}"}
    if GRAPH_FILE_URL:
        # endpoint /shares: resolve a URL direto pro arquivo (robusto a mudança de pasta)
        base = f"https://graph.microsoft.com/v1.0/shares/{_graph_share_id(GRAPH_FILE_URL)}/driveItem"
        content_url = base + "/content"
    else:
        fp   = requests.utils.quote(GRAPH_FILE_PATH, safe="/")
        base = f"https://graph.microsoft.com/v1.0/sites/{_graph_site_id()}/drive/root:/{fp}"
        content_url = base + ":/content"
    meta = _http().get(base, headers=H, timeout=20)
    meta.raise_for_status()
    etag = meta.json().get("eTag") or meta.json().get("lastModifiedDateTime")
    if etag and etag == _graph_state["etag"] and os.path.exists(_BD_PERF_GRAPH):
        _graph_state["ok_ts"] = time.time()
        return False
    r = _http().get(content_url, headers=H, timeout=120)
    r.raise_for_status()
    tmp = _BD_PERF_GRAPH + ".tmp"
    with open(tmp, "wb") as f:
        f.write(r.content)
    os.replace(tmp, _BD_PERF_GRAPH)
    _graph_state["etag"]  = etag
    _graph_state["ok_ts"] = time.time()
    print(f"[graph] BD_Performance baixado do SharePoint ({len(r.content) // 1024} KB)")
    return True


def _graph_loop():
    print(f"[graph] sync do BD_Performance via SharePoint ativado (checa a cada {GRAPH_SYNC_SECS}s)")
    while True:
        try:
            _graph_sync_bd()
        except Exception as e:
            print(f"[graph] sync falhou ({e}) — seguindo com OneDrive/cópia local")
        time.sleep(GRAPH_SYNC_SECS)


def _bd_perf_path() -> str:
    """Caminho do BD_Performance — prioridade: (1) cópia baixada do SharePoint via Graph,
    se o sync está saudável (<1 h desde o último sucesso); (2) versão ONLINE do OneDrive;
    (3) cópia local como último recurso. Reavaliado a cada carga."""
    if os.path.exists(_BD_PERF_GRAPH) and (time.time() - _graph_state["ok_ts"]) < 3600:
        return _BD_PERF_GRAPH
    for p in _BD_PERF_ONLINE_CANDS:
        if os.path.exists(p):
            return p
    return _BD_PERF_LOCAL

# Globais preenchidas por load_equipamentos() (recarregáveis em runtime)
ESPERADO_INV  = {}   # {usina_sup: {equip_sup: strings_esperadas}}
EQUIP_NAMES   = {}   # {usina_sup: {equip_sup: equipamento_display}}
USINA_DISPLAY = {}   # {usina_sup: usina_display}
ESPERADO      = {}   # {usina_sup: {"inv_esp": n, "str_esp": soma}}
FULL_OM       = set()
STRING_BOX    = set()   # {usina_sup}  usinas com coluna "String Box"=Sim (sem visão por string)
POWER_INV     = {}   # {usina_sup: {alias_norm: potencia_kwp}}  alias = equip_sup e display
_bd_mtime     = 0.0
_bd_lock      = threading.Lock()


def _nrm(s) -> str:
    return re.sub(r"\s+", "", str(s)).strip().lower()


def load_equipamentos():
    """(Re)carrega TODO o cadastro a partir da aba 'Equipamentos' do BD_Performance:
    esperadas (Strings Ativas), nomes de exibição, Full O&M e potência por inversor.
    Chamada na init e sempre que o arquivo muda (mtime). Uma só leitura alimenta tudo."""
    global ESPERADO_INV, EQUIP_NAMES, USINA_DISPLAY, ESPERADO, FULL_OM, STRING_BOX, POWER_INV, _bd_mtime
    try:
        path = _bd_perf_path()
        df = pd.read_excel(path, sheet_name="Equipamentos", header=2)
        df.columns = [str(c).strip() for c in df.columns]
        c_us   = next(c for c in df.columns if "supervis" in c.lower() and "usina" in c.lower())
        c_usd  = next(c for c in df.columns if c.lower() == "usina")
        c_es   = next(c for c in df.columns if "supervis" in c.lower() and "equip" in c.lower())
        c_eq   = next(c for c in df.columns if c.lower() == "equipamento")
        c_pot  = next(c for c in df.columns if c.lower().startswith("pot"))
        c_full = next((c for c in df.columns if "full" in c.lower()), None)
        c_sa   = next((c for c in df.columns if "string" in c.lower() and "ativ" in c.lower()), None)
        c_sb   = next((c for c in df.columns if "string" in c.lower() and "box" in c.lower()), None)

        esperado_inv, equip_names, usina_display, power_inv = {}, {}, {}, {}
        full_om, string_box = set(), set()
        for _, row in df.iterrows():
            if pd.isna(row[c_us]):
                continue
            us = str(row[c_us]).strip()
            # Nome de exibição da usina (dedup de nomes ambíguos é feito depois)
            if pd.notna(row[c_usd]):
                ud = str(row[c_usd]).strip()
                if ud:
                    usina_display[us] = ud
            # Full O&M e String Box — marcados por linha, consistentes por usina
            if c_full and str(row[c_full]).strip().lower() == "sim":
                full_om.add(us)
            if c_sb and str(row[c_sb]).strip().lower() == "sim":
                string_box.add(us)
            # Daqui pra baixo: só inversores individuais
            eq = row[c_eq]
            if pd.isna(eq) or not str(eq).strip().lower().startswith("inversor"):
                continue
            eq = str(eq).strip()
            es = str(row[c_es]).strip() if pd.notna(row[c_es]) else None
            # Potência (kWp) — indexada por equip_sup e display (ambas chaves possíveis da API)
            try:
                pk = float(row[c_pot])
            except (TypeError, ValueError):
                pk = None
            if pk is not None:
                d = power_inv.setdefault(us, {})
                for alias in (es, eq):
                    if alias:
                        d[_nrm(alias)] = pk
            # Esperadas (Strings Ativas) + nome de exibição — chaveados por equip_sup (chave da API)
            if es:
                equip_names.setdefault(us, {})[es] = eq
                if c_sa is not None and pd.notna(row[c_sa]):
                    try:
                        esperado_inv.setdefault(us, {})[es] = int(round(float(row[c_sa])))
                    except (TypeError, ValueError):
                        pass

        # Remove nomes de exibição AMBÍGUOS (mesmo display p/ vários supervisórios, ex.: "Altair" x5).
        _disp_count = {}
        for _d in usina_display.values():
            _disp_count[_d] = _disp_count.get(_d, 0) + 1
        _ambiguos = sum(1 for v in usina_display.values() if _disp_count[v] > 1)
        usina_display = {sup: disp for sup, disp in usina_display.items() if _disp_count[disp] == 1}
        if _ambiguos:
            print(f"[AVISO] {_ambiguos} usinas com nome de exibição duplicado na planilha — "
                  f"mantido o nome supervisório/API nessas (evita ambiguidade)")

        # Totais por usina (nível usina)
        esperado = {us: {"inv_esp": len(eq), "str_esp": sum(eq.values())}
                    for us, eq in esperado_inv.items()}

        # Publica de uma vez (substitui as globais)
        ESPERADO_INV, EQUIP_NAMES, USINA_DISPLAY = esperado_inv, equip_names, usina_display
        ESPERADO, FULL_OM, STRING_BOX, POWER_INV = esperado, full_om, string_box, power_inv
        try:
            _bd_mtime = os.path.getmtime(path)
        except OSError:
            _bd_mtime = 0.0
        _n_pot = sum(len(v) for v in power_inv.values())
        _src = "LOCAL (fallback)" if path == _BD_PERF_LOCAL else "ONLINE"
        print(f"[OK] BD_Performance/Equipamentos [{_src}]: {len(esperado_inv)} usinas c/ esperadas | "
              f"{len(FULL_OM)} Full O&M | {len(STRING_BOX)} String Box | {_n_pot} aliases de potência")
    except Exception as e:
        print(f"[AVISO] BD_Performance (Equipamentos) não carregado: {e}")


def _pot_inv(plant_sup: str, inv_api: str, inv_disp: str = None):
    """Potência (kWp) do inversor pelas chaves supervisório (plant['nome'], device_name)."""
    d = POWER_INV.get(plant_sup) or POWER_INV.get((plant_sup or "").strip())
    if not d:
        return None
    for k in (inv_api, inv_disp):
        if k:
            v = d.get(_nrm(k))
            if v is not None:
                return v
    return None


def maybe_reload_equipamentos():
    """Recarrega o cadastro se o BD_Performance mudou (verificação barata por mtime)."""
    try:
        m = os.path.getmtime(_bd_perf_path())
    except OSError:
        return
    if m == _bd_mtime:
        return
    with _bd_lock:
        if m == _bd_mtime:           # outro thread já recarregou
            return
        print("[BD] BD_Performance alterado -> recarregando cadastro (esperadas/nomes/Full O&M/potência)...")
        load_equipamentos()
        load_metas()


# ── Metas / previsto: BD_Performance, abas "Info Geral" e "Info Mensal" ───────
# Espelha as queries M do Power BI (InfoGeral / InfoMensal). São a fonte das METAS
# usadas para comparar a performance ao vivo:
#   • Info Geral  → potência da UFV, nº de inversores, P50, perdas por degradação (por usina)
#   • Info Mensal → PR Previsto 1° Ano (%) e IPOA/GHI Previsto (por usina × mês)
# Regra do Power BI: PR Previsto (%) = PR Previsto 1° Ano (%) + Perdas por degradação.
# Chave de join = nome de EXIBIÇÃO da usina (coluna "Usina", ex.: "Araputanga"),
# o mesmo que nome_usina()/USINA_DISPLAY devolvem para o lado ao vivo.
INFO_GERAL    = {}   # {usina_nrm: {usina, cliente, potencia_kwp, potencia_mwp, degradacao, qtd_inv, p50_mwh}}
PR_PREVISTO   = {}   # {usina_nrm: {(ano, mes): {pr_previsto, pr_previsto_1ano, ipoa_previsto, ghi_previsto, p50_mwh, disp_alvo}}}
_metas_mtime  = 0.0


def _unaccent(s) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c))


def _col(cols, *needles, exclude=()):
    """Acha a 1ª coluna cujo nome (sem acento, minúsculo) contém todos os `needles`
    e nenhum dos `exclude`. Robusto a acentos/variações de cabeçalho da planilha."""
    nd = [_unaccent(n).lower() for n in needles]
    ex = [_unaccent(e).lower() for e in exclude]
    for c in cols:
        cl = _unaccent(c).lower()
        if all(n in cl for n in nd) and not any(e in cl for e in ex):
            return c
    return None


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None   # descarta NaN


def load_metas():
    """(Re)carrega as METAS das abas 'Info Geral' e 'Info Mensal' do BD_Performance.
    Preenche INFO_GERAL (por usina) e PR_PREVISTO (por usina × mês). Mesma fonte do
    cadastro, então é recarregada junto pelo mtime."""
    global INFO_GERAL, PR_PREVISTO, _metas_mtime
    try:
        path = _bd_perf_path()

        # --- Info Geral (cabeçalho na 1ª linha) ---
        dg = pd.read_excel(path, sheet_name="Info Geral", header=0)
        dg.columns = [str(c).strip() for c in dg.columns]
        gc_us  = _col(dg.columns, "usina")
        gc_kwp = _col(dg.columns, "potencia", "kwp")
        gc_mwp = _col(dg.columns, "potencia", "mwp")
        gc_deg = _col(dg.columns, "degrada")
        gc_inv = _col(dg.columns, "quantidade", "inversor")
        gc_p50 = _col(dg.columns, "p50")
        gc_cli = _col(dg.columns, "cliente")
        info = {}
        for _, r in dg.iterrows():
            if not gc_us or pd.isna(r[gc_us]):
                continue
            u = str(r[gc_us]).strip()
            if not u:
                continue
            info[_nrm(u)] = {
                "usina":        u,
                "cliente":      str(r[gc_cli]).strip() if gc_cli and pd.notna(r[gc_cli]) else None,
                "potencia_kwp": _num(r[gc_kwp]) if gc_kwp else None,
                "potencia_mwp": _num(r[gc_mwp]) if gc_mwp else None,
                "degradacao":   (_num(r[gc_deg]) or 0.0) if gc_deg else 0.0,
                "qtd_inv":      _num(r[gc_inv]) if gc_inv else None,
                "p50_mwh":      _num(r[gc_p50]) if gc_p50 else None,
            }

        # --- Info Mensal (cabeçalho na 2ª linha; 1ª coluna é índice em branco) ---
        dm = pd.read_excel(path, sheet_name="Info Mensal", header=1)
        dm.columns = [str(c).strip() for c in dm.columns]
        mc_us   = _col(dm.columns, "usina")
        mc_mes  = _col(dm.columns, "mes", exclude=("comenta",))
        mc_pr   = _col(dm.columns, "pr previsto")
        mc_ipoa = _col(dm.columns, "ipoa", "previsto")
        mc_ghi  = _col(dm.columns, "ghi", "previsto")
        mc_p50  = _col(dm.columns, "p50")
        mc_disp = _col(dm.columns, "disponibilidade")
        prev = {}
        for _, r in dm.iterrows():
            if not mc_us or pd.isna(r[mc_us]) or not mc_mes or pd.isna(r[mc_mes]):
                continue
            u = str(r[mc_us]).strip()
            ts = pd.to_datetime(r[mc_mes], errors="coerce", dayfirst=True)
            if pd.isna(ts):
                continue
            deg = info.get(_nrm(u), {}).get("degradacao", 0.0) or 0.0
            pr1 = _num(r[mc_pr]) if mc_pr else None
            prev.setdefault(_nrm(u), {})[(ts.year, ts.month)] = {
                "pr_previsto":      (pr1 + deg) if pr1 is not None else None,   # = regra do Power BI
                "pr_previsto_1ano": pr1,
                "ipoa_previsto":    _num(r[mc_ipoa]) if mc_ipoa else None,
                "ghi_previsto":     _num(r[mc_ghi]) if mc_ghi else None,
                "p50_mwh":          _num(r[mc_p50]) if mc_p50 else None,
                "disp_alvo":        _num(r[mc_disp]) if mc_disp else None,
            }

        INFO_GERAL, PR_PREVISTO = info, prev
        try:
            _metas_mtime = os.path.getmtime(path)
        except OSError:
            _metas_mtime = 0.0
        print(f"[OK] BD_Performance/Info Geral+Mensal: {len(info)} usinas | "
              f"{sum(len(v) for v in prev.values())} linhas mensais de meta")
    except Exception as e:
        print(f"[AVISO] BD_Performance (Info Geral/Mensal) não carregado: {e}")


def info_geral(usina_display):
    """Metadados da UFV (potência, P50, degradação) pelo nome de exibição. None se ausente."""
    return INFO_GERAL.get(_nrm(usina_display)) if usina_display else None


def pr_previsto(usina_display, ano=None, mes=None):
    """PR Previsto (fração, já com degradação) da usina no mês. Sem ano/mês usa o mês atual.
    Faz fallback para o mesmo mês de outro ano, ou a meta mais recente, se faltar o exato."""
    d = PR_PREVISTO.get(_nrm(usina_display)) if usina_display else None
    if not d:
        return None
    if ano is None or mes is None:
        hoje = datetime.now()
        ano, mes = hoje.year, hoje.month
    rec = d.get((ano, mes))
    if rec is None:
        mesmo_mes = [v for (y, m), v in d.items() if m == mes]
        rec = mesmo_mes[-1] if mesmo_mes else d[max(d)]
    return rec


def geracao_alvo_mwh(usina_display, ipoa, ano=None, mes=None):
    """Geração alvo (MWh) pelo ramo IPOA: IPOA × PR Meta × Potência (MWp).
    É APENAS o ramo 2 do DAX 'Meta Mensal Geração' (sem o fallback P50). Para a meta
    fiel ao Power BI por dia, use meta_geracao_dia() — que trata Validação=0 e IPOA<=0."""
    g = info_geral(usina_display)
    rec = pr_previsto(usina_display, ano, mes)
    if not g or not rec or ipoa is None:
        return None
    pot = g.get("potencia_mwp")
    pr  = rec.get("pr_previsto")
    if pot is None or pr is None:
        return None
    return ipoa * pr * pot


def meta_geracao_dia(usina_display, data, ipoa, validacao):
    """Meta de geração do DIA (MWh) — espelha fielmente a coluna DAX 'Meta Mensal Geração':
        1. Validação == 0          -> P50 mensal / dias do mês
        2. IPOA > 0 (e validado)   -> IPOA × PR Meta × Potência (MWp)
        3. senão (IPOA <= 0/nulo)  -> P50 mensal / dias do mês
    `data` = date/datetime da linha; `ipoa` em kWh/m²; `validacao` numérico (0 = não validado).
    P50 mensal e PR Meta vêm da Info Mensal; potência da Info Geral. None se faltar insumo."""
    if data is None:
        return None
    ano, mes = data.year, data.month
    rec = pr_previsto(usina_display, ano, mes)
    g = info_geral(usina_display)
    dias_no_mes = calendar.monthrange(ano, mes)[1]
    p50 = rec.get("p50_mwh") if rec else None
    fallback = (p50 / dias_no_mes) if (p50 is not None and dias_no_mes) else None

    val = _num(validacao)
    if val == 0:                                   # 1. dia não validado
        return fallback
    pr  = rec.get("pr_previsto") if rec else None
    pot = g.get("potencia_mwp") if g else None
    if ipoa is not None and ipoa > 0 and pr is not None and pot is not None:
        return ipoa * pr * pot                     # 2. ramo IPOA
    return fallback                                # 3. IPOA <= 0 ou nulo


load_equipamentos()   # carga inicial do cadastro mestre
load_metas()          # carga inicial das metas (Info Geral / Info Mensal)


@app.before_request
def _auto_reload_bd():
    """Qualquer refresh forçado (force=1, o que o botão Atualizar faz) relê o BD_Performance se mudou.
    Robusto independente da versão do frontend em cache no navegador."""
    if flask_request.args.get("force") == "1":
        maybe_reload_equipamentos()
        maybe_reload_tickets()


def maybe_reload_tickets():
    """Recarrega a planilha de Tickets se ela mudou (mtime). Com LOCK: o botão Atualizar
    dispara vários force=1 em paralelo e ler o xlsx em várias threads ao mesmo tempo
    (pandas/openpyxl) pode derrubar o processo."""
    path = _tickets_path()
    if not path:
        return
    try:
        m = os.path.getmtime(path)
    except OSError:
        return
    if m == _tickets_mtime:
        return
    with _tickets_lock:
        if m == _tickets_mtime:        # outra thread já recarregou
            return
        print("[Tickets] planilha alterada -> recarregando ocorrências...")
        load_tickets_trackers()


def nome_usina(plant_id, nome_api):
    # Nome de exibição vem do BD_Performance (coluna "Usina"); senão, o nome da própria API
    return USINA_DISPLAY.get(nome_api.strip()) or nome_api.strip()


# ── Auth & helpers ─────────────────────────────────────────────────────────────
# Token da API PV CACHEADO: antes, autenticava a CADA chamada (cada /api/data, cada
# detalhe, cada prewarm) — o que fazia a API PV limitar/bloquear o /authenticate e
# devolver resposta não-JSON (500). Agora autentica 1× e reusa pela validade do JWT.
_pv_token      = {"token": "", "exp": 0.0}
_pv_token_lock = threading.Lock()


def get_token(force=False) -> str:
    now = time.time()
    if not force and _pv_token["token"] and now < _pv_token["exp"]:
        return _pv_token["token"]
    with _pv_token_lock:
        if not force and _pv_token["token"] and time.time() < _pv_token["exp"]:
            return _pv_token["token"]
        r = _http().post(f"{BASE_URL}/authenticate",
                          json={"username": USERNAME, "password": PASSWORD}, timeout=30)
        try:
            tok = r.json()["token"]
        except Exception:
            if _pv_token["token"]:                 # resposta inválida → reusa o anterior
                return _pv_token["token"]
            raise RuntimeError(f"API PV /authenticate falhou (HTTP {r.status_code})")
        exp = time.time() + 2700                   # fallback 45 min
        try:
            import base64
            pl = tok.split(".")[1]; pl += "=" * (-len(pl) % 4)
            jexp = json.loads(base64.urlsafe_b64decode(pl)).get("exp")
            if jexp:
                exp = float(jexp) - 60             # 1 min de folga antes do vencimento
        except Exception:
            pass
        _pv_token.update({"token": tok, "exp": exp})
        return tok


def get_plants(token: str) -> list:
    r = _http().get(f"{BASE_URL}/plants", headers={"x-access-token": token}, timeout=30)
    return r.json()


def parse_cj(raw) -> dict:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return raw or {}


# ── API PV: string ativa = relativa à média do inversor ───────────────────────
def _na_janela_sol(agora=None) -> bool:
    """True se 'agora' está na janela de sol confiável (09:00–15:00 local)."""
    h = (agora or datetime.now()).hour
    return STRING_JANELA_INI <= h < STRING_JANELA_FIM


def _ipv_ativas(correntes: list, em_janela=None) -> list:
    """Recebe as correntes (A) das strings de UM inversor → lista de bools 'ativa'.
    DENTRO de 09:00–15:00 (sol forte): ativa se corrente > STRING_JANELA_MIN_A (1 A) — régua
    simples, sem falso negativo porque a irradiância é alta.
    FORA da janela (início/fim de dia, noite): ativa se corrente > STRING_JANELA_MIN_A (1 A)
    — passou de 1 A, tem corrente real = ativa — OU (para strings abaixo de 1 A) se
    >= STRING_ATIVA_FRAC × média(strings produzindo), pegando produtoras em luz fraca.
    Valor 0 = sempre inativa."""
    if em_janela is None:
        em_janela = _na_janela_sol()
    if em_janela:
        return [isinstance(c, (int, float)) and c > STRING_JANELA_MIN_A for c in correntes]
    produzindo = [c for c in correntes if isinstance(c, (int, float)) and c > 0]
    if not produzindo:
        return [False] * len(correntes)
    limiar = (sum(produzindo) / len(produzindo)) * STRING_ATIVA_FRAC
    # > 1 A já conta como ativa (tem corrente); abaixo disso, usa a régua relativa
    return [isinstance(c, (int, float)) and c > 0 and (c > STRING_JANELA_MIN_A or c >= limiar)
            for c in correntes]


def _str_key(plant_id, inv_id, ipv) -> str:
    return f"{plant_id}|{inv_id}|{ipv}"


def _classifica_strings(plant_id, inv_id, ipv_keys, correntes):
    """Classifica as strings de UM inversor (instantâneo, relativo à mediana do PRÓPRIO
    inversor). → lista de status alinhada a ipv_keys, em {trancada, sem_corrente,
    baixa_perf, ativa, inativa}.
      • trancada   = marcada à mão (MPPT sem string) → fora da contagem de ativas
      • inativa    = inversor parado (mediana ~0: noite/nublado) → NÃO é falha
      • sem_corrente = string morta (=0) com o inversor produzindo → falha tipo 1
      • baixa_perf = corrente < 60% da mediana das demais → falha tipo 2
      • ativa      = produzindo normal
    'ativas' = ativa + baixa_perf (produzindo, descontadas as trancadas)."""
    trancada = [_str_key(plant_id, inv_id, k) in _trancadas for k in ipv_keys]
    prod = sorted(c for c, t in zip(correntes, trancada)
                  if (not t) and isinstance(c, (int, float)) and c > STRING_SEM_CORRENTE_A)
    med  = prod[len(prod) // 2] if prod else 0.0
    produzindo = med >= STRING_INV_MIN_MED_A
    out = []
    for c, t in zip(correntes, trancada):
        cv = c if isinstance(c, (int, float)) else 0.0
        if t:
            out.append("trancada")
        elif not produzindo:
            out.append("inativa")
        elif cv <= STRING_SEM_CORRENTE_A:
            out.append("sem_corrente")
        elif cv < STRING_BAIXA_PERF_FRAC * med:
            out.append("baixa_perf")
        else:
            out.append("ativa")
    return out


def _str_ativas(statuses) -> int:
    return sum(1 for s in statuses if s in ("ativa", "baixa_perf"))


# ── Monta resumo de usina a partir dos registros brutos ───────────────────────
def build_summary(plant: dict, records: list) -> dict:
    pid  = plant["id"]
    nome = nome_usina(pid, plant["nome"])

    latest = {}
    for rec in records:
        inv_id = rec.get("idefinversor")
        ts     = rec.get("tsleitura_new", "")
        if inv_id not in latest or ts > latest[inv_id].get("tsleitura_new", ""):
            latest[inv_id] = rec

    ts_max = max((r.get("tsleitura_new", "") for r in latest.values()), default="")

    falha = False
    if ts_max:
        try:
            diff = (datetime.now() - datetime.strptime(ts_max, "%Y-%m-%d %H:%M:%S")).total_seconds() / 60
            falha = diff > COMM_ALERT_MINUTES
        except Exception:
            pass

    strings_ativas = 0
    temps = []
    for rec in latest.values():
        cj = parse_cj(rec.get("conteudojson"))
        inv_id = rec.get("idefinversor")
        ipv_keys  = [k for k in cj if k.startswith("Ipv") and isinstance(cj[k], (int, float))]
        correntes = [cj[k] for k in ipv_keys]
        # exclui trancadas e aplica a régua relativa à mediana do inversor
        strings_ativas += _str_ativas(_classifica_strings(pid, inv_id, ipv_keys, correntes))
        t = cj.get("Temp")
        if isinstance(t, (int, float)):
            temps.append(t)

    esp       = ESPERADO.get(plant["nome"].strip(), {})
    inv_esp   = esp.get("inv_esp")
    str_esp   = esp.get("str_esp")
    diferenca = (strings_ativas - str_esp) if (str_esp is not None) else None

    return {
        "usina": nome, "plant_id": pid,
        "qtd_inversores": len(latest),
        "strings_ativas": strings_ativas,
        "inv_esp": inv_esp, "str_esp": str_esp, "diferenca": diferenca,
        "temp_media": round(sum(temps) / len(temps), 1) if temps else None,
        "ultima_leitura": ts_max or None,
        "sem_dados": False,
        "falha_comunicacao": falha,
        "stringbox": plant["nome"].strip() in STRING_BOX,
    }


# ── Processa uma usina (visão geral) ──────────────────────────────────────────
def process_plant(token: str, plant: dict, timeout: int = 45) -> dict:
    pid  = plant["id"]
    nome = nome_usina(pid, plant["nome"])
    base = {"usina": nome, "plant_id": pid,
            "qtd_inversores": None, "strings_ativas": None,
            "temp_media": None, "ultima_leitura": None,
            "sem_dados": True, "falha_comunicacao": False,
            "stringbox": plant["nome"].strip() in STRING_BOX}
    try:
        records = _http().post(f"{BASE_URL}/day_inverter",
                                headers={"x-access-token": token},
                                json={"id": pid}, timeout=timeout).json()
    except Exception:
        return base
    if not records:
        return base
    return build_summary(plant, records)


# ── Severidade para ordenação ─────────────────────────────────────────────────
def severidade(r) -> int:
    if not r.get("sem_dados") and r.get("strings_ativas") == 0:
        return 0  # sem geração
    if not r.get("sem_dados") and r.get("diferenca") is not None and r["diferenca"] < 0:
        return 1  # falha de string
    if not r.get("sem_dados") and r.get("temp_media") is not None and r["temp_media"] >= TEMP_ALERT:
        return 2  # temp elevada
    if r.get("falha_comunicacao"):
        return 3  # falha comunicação
    if r.get("sem_dados"):
        return 4  # sem dados
    return 5      # normal


# ── Busca todos ────────────────────────────────────────────────────────────────
def fetch_all() -> list:
    token     = get_token()
    all_plants = get_plants(token)
    # Filtra apenas usinas Full O&M = Sim (se a lista estiver carregada)
    plants = [p for p in all_plants if p["nome"].strip() in FULL_OM] if FULL_OM else all_plants
    plant_map = {p["id"]: p for p in plants}
    rows      = []

    # Concorrência moderada: um único token sob 20 requisições pesadas paralelas
    # faz a API throttlar as maiores (ex.: Saturnino, 2 MB) → vinham vazias/sem_dados.
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(process_plant, token, p): p for p in plants}
        for f in as_completed(futures):
            rows.append(f.result())

    rows_by_id = {r["plant_id"]: r for r in rows}

    # Passada 2 — retry paralelo leve (token renovado) para as que falharam
    sem_dados_ids = [pid for pid, r in rows_by_id.items() if r.get("sem_dados")]
    if sem_dados_ids:
        token2 = get_token()
        retry_plants = [plant_map[pid] for pid in sem_dados_ids if pid in plant_map]
        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = {ex.submit(process_plant, token2, p): p for p in retry_plants}
            for f in as_completed(futures):
                r = f.result()
                if not r.get("sem_dados"):
                    rows_by_id[r["plant_id"]] = r

    # Passada 3 — SEQUENCIAL (1 por vez, sem concorrência, timeout alto).
    # Resolve usinas pesadas que a API throttla sob carga paralela (ex.: Sorocaba).
    ainda_sem = [pid for pid, r in rows_by_id.items() if r.get("sem_dados")]
    if ainda_sem:
        token3 = get_token()
        for pid in ainda_sem:
            if pid not in plant_map:
                continue
            r = process_plant(token3, plant_map[pid], timeout=60)
            if not r.get("sem_dados"):
                rows_by_id[pid] = r

    rows = list(rows_by_id.values())
    return sorted(rows, key=lambda x: (severidade(x), x["usina"]))


# ── Drill-down: detalhe de uma usina ──────────────────────────────────────────
@app.route("/api/plant/<int:plant_id>")
def api_plant_detail(plant_id):
    token = get_token()
    try:
        records = _http().post(f"{BASE_URL}/day_inverter",
                                headers={"x-access-token": token},
                                json={"id": plant_id}, timeout=60).json()
    except Exception:
        return jsonify({"error": "timeout"}), 504

    if not records:
        return jsonify({"inversores": []})

    # Busca nome da usina (para lookup no ESPERADO_INV)
    plant_nome_api = ""
    try:
        plants = get_plants(token)
        plant_nome_api = next((p["nome"].strip() for p in plants if p["id"] == plant_id), "")
    except Exception:
        pass

    # Busca nomes dos dispositivos
    dev_names = {}
    try:
        devs_raw = _http().get(f"{BASE_URL}/plant_devices",
                                headers={"x-access-token": token},
                                json={"id": plant_id}, timeout=20).json()
        devs = devs_raw
        if isinstance(devs_raw, list) and devs_raw and "plant_devices" in devs_raw[0]:
            devs = devs_raw[0]["plant_devices"]
        elif isinstance(devs_raw, dict):
            devs = devs_raw.get("plant_devices", [])
        # .strip(): a API às vezes retorna o nome com espaço no fim (ex.: "INVERSOR 04 "),
        # o que quebrava o match com a planilha (nome/esperada caíam no cru). Normaliza aqui.
        dev_names = {d["device_id"]: str(d.get("device_name", "")).strip() for d in devs}
    except Exception:
        pass

    # Registro mais recente por inversor (+ todos os registros do dia p/ fallback de strings)
    latest, by_inv = {}, {}
    for rec in records:
        inv_id = rec.get("idefinversor")
        ts     = rec.get("tsleitura_new", "")
        by_inv.setdefault(inv_id, []).append(rec)
        if inv_id not in latest or ts > latest[inv_id]["tsleitura_new"]:
            latest[inv_id] = rec

    # Usa plant_devices como fonte completa — filtra só inversores reais
    _EXCLUIR_CONTEM = ["x", "old", "velho", "antigo"]

    def eh_inversor(dev_id):
        api_nome_orig = dev_names.get(dev_id, str(dev_id))
        api_nome      = api_nome_orig.lower()
        display_nome  = EQUIP_NAMES.get(plant_nome_api, {}).get(api_nome_orig, api_nome_orig).lower()
        if "inv" not in api_nome and "inv" not in display_nome:
            return False
        for nome in (api_nome, display_nome):
            if any(exc in nome for exc in _EXCLUIR_CONTEM):
                return False
        return True

    all_ids = sorted(
        [d for d in (dev_names.keys() if dev_names else latest.keys()) if eh_inversor(d)],
        key=lambda x: dev_names.get(x, str(x))
    )

    inversores = []
    for inv_id in all_ids:
        inv_nome_api = dev_names.get(inv_id, f"INV-{inv_id}")
        # Traduz para o nome da planilha (Equipamento), mantém API name como fallback
        inv_nome = EQUIP_NAMES.get(plant_nome_api, {}).get(inv_nome_api, inv_nome_api)
        rec      = latest.get(inv_id)          # None se inversor sem dados hoje

        if rec:
            cj = parse_cj(rec.get("conteudojson"))
            ipv_keys  = [k for k in sorted(cj.keys()) if k.startswith("Ipv") and isinstance(cj[k], (int, float))]
            scj = cj
            # O ping mais recente às vezes vem só com Eday/Temp (sem Ipv). Pra um inversor que
            # está gerando não aparecer "0/0" ao expandir, usa o registro mais recente do DIA
            # que tenha corrente por string (dado real) — mantém Eday/Temp/leitura do último.
            if not ipv_keys:
                for prev in sorted(by_inv.get(inv_id, []),
                                   key=lambda r: r.get("tsleitura_new", ""), reverse=True):
                    pcj = parse_cj(prev.get("conteudojson"))
                    pk  = [k for k in sorted(pcj.keys()) if k.startswith("Ipv") and isinstance(pcj[k], (int, float))]
                    if pk:
                        scj, ipv_keys = pcj, pk
                        break
            correntes = [scj[k] for k in ipv_keys]
            stt       = _classifica_strings(plant_id, inv_id, ipv_keys, correntes)
            strings   = [{"id": k, "corrente": c, "status": s,
                          "ativa": s in ("ativa", "baixa_perf"), "trancada": s == "trancada"}
                         for k, c, s in zip(ipv_keys, correntes, stt)]
            strings_ativas = _str_ativas(stt)
            temp   = cj.get("Temp")
            eday   = cj.get("Eday")
            ts_rec = rec.get("tsleitura_new", "")
            falha  = False
            if ts_rec:
                try:
                    diff = (datetime.now() - datetime.strptime(ts_rec, "%Y-%m-%d %H:%M:%S")).total_seconds() / 60
                    falha = diff > COMM_ALERT_MINUTES
                except Exception:
                    pass
            desligado = False
        else:
            # Inversor desligado / sem comunicação hoje
            strings        = []
            strings_ativas = 0
            temp           = None
            eday           = None
            ts_rec         = None
            falha          = True
            desligado      = True

        # Lookup de strings esperadas usa o nome da API (chave original da planilha)
        inv_str_esp   = ESPERADO_INV.get(plant_nome_api, {}).get(inv_nome_api)
        inv_diferenca = (strings_ativas - inv_str_esp) if (inv_str_esp is not None and not desligado) else None

        inversores.append({
            "id": inv_id,
            "nome": inv_nome,
            "nome_api": inv_nome_api,
            "ultima_leitura": ts_rec,
            "falha_comunicacao": falha,
            "desligado": desligado,
            "strings_ativas": strings_ativas,
            "total_strings": len(strings),
            "str_esp": inv_str_esp,
            "diferenca": inv_diferenca,
            "temp": temp,
            "eday": eday,
            "strings": strings,
        })

    # Deduplica por nome_api: se mesmo inversor aparecer duplicado, fica o com dados
    seen = {}
    for inv in inversores:
        key = inv.get("nome_api", inv["nome"])
        if key not in seen:
            seen[key] = inv
        elif seen[key].get("desligado") and not inv.get("desligado"):
            seen[key] = inv
    inversores = list(seen.values())

    return jsonify({"plant_id": plant_id, "inversores": inversores})


# ── Debug: mostra chaves ESPERADO vs nomes da API ─────────────────────────────
@app.route("/api/debug/match")
def api_debug_match():
    token  = get_token()
    plants = get_plants(token)
    api_names = [{"id": p["id"], "nome_api": p["nome"]} for p in plants[:30]]
    esp_keys  = sorted(ESPERADO.keys())[:30]
    matches   = [p for p in plants if p["nome"].strip() in ESPERADO]
    return jsonify({
        "esperado_total": len(ESPERADO),
        "esperado_sample": esp_keys,
        "api_total": len(plants),
        "api_sample": api_names,
        "matches_count": len(matches),
        "matches": [{"id": p["id"], "nome": p["nome"]} for p in matches],
    })


# ── Visão geral ────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", today=datetime.now().strftime("%d/%m/%Y"))


_data_refreshing   = {"on": False}
_data_refresh_lock = threading.Lock()


def _build_data_payload():
    """Busca TUDO e monta o payload da aba Strings (parte cara: ~71 usinas da API PV)."""
    rows = fetch_all()
    # Salva último dado conhecido para cada usina com dados reais
    for r in rows:
        if not r.get("sem_dados"):
            _last_known[r["plant_id"]] = r.copy()

    # Substitui sem_dados pelo último dado conhecido (marcado como histórico)
    rows_final = []
    for r in rows:
        if r.get("sem_dados") and r["plant_id"] in _last_known:
            hist = _last_known[r["plant_id"]].copy()
            hist["dado_historico"] = True
            rows_final.append(hist)
        else:
            rows_final.append(r)
    rows = sorted(rows_final, key=lambda x: (severidade(x), x["usina"]))

    rows_com_dados  = [r for r in rows if not r.get("sem_dados")]
    total_strings   = sum(r["strings_ativas"] for r in rows_com_dados)
    alertas_strings = [r for r in rows_com_dados if r["strings_ativas"] == 0]
    alertas_temp    = [r for r in rows_com_dados if r["temp_media"] and r["temp_media"] >= TEMP_ALERT]
    alertas_comm    = [r for r in rows if r.get("sem_dados") or r.get("falha_comunicacao")]

    # Gráficos de barras (strings ativas + temperatura) são montados no navegador
    # a partir de "rows" (renderPvCharts no index.html) — nada de Plotly no payload.
    payload = {
        "rows": rows,
        "summary": {
            "total_usinas": len(rows),
            "total_strings": total_strings,
            "alertas_strings": len(alertas_strings),
            "alertas_temp": len(alertas_temp),
            "alertas_comm": len(alertas_comm),
        },
        "alertas_strings_list": [r["usina"] for r in alertas_strings],
        "alertas_temp_list":    [{"usina": r["usina"], "temp": r["temp_media"]} for r in alertas_temp],
        "alertas_comm_list":    [{"usina": r["usina"], "ultima_leitura": r.get("ultima_leitura")} for r in alertas_comm],
        "cache_ts": datetime.now().strftime("%H:%M:%S"),
    }
    return payload


def _refresh_data_cache():
    """Atualiza o cache do /api/data (com lock, sem refreshes concorrentes)."""
    with _data_refresh_lock:
        if _data_refreshing["on"]:
            return
        _data_refreshing["on"] = True
    try:
        _cache["payload"] = _build_data_payload()
        _cache["ts"] = time.time()
        _persist_mark()
    except Exception as e:
        print(f"[api/data] refresh falhou: {e}")
    finally:
        _data_refreshing["on"] = False


@app.route("/api/data")
def api_data():
    # Stale-while-revalidate: NUNCA bloqueia na busca lenta (~71 usinas). Serve o cache
    # na hora e atualiza em background. O prewarm mantém o cache sempre quente.
    force = flask_request.args.get("force", "0") == "1"
    agora = time.time()
    fresh = bool(_cache["payload"]) and (agora - _cache["ts"]) < CACHE_TTL
    if force or not fresh:
        threading.Thread(target=_refresh_data_cache, daemon=True).start()
    if _cache["payload"]:
        out = dict(_cache["payload"]); out["stale"] = not fresh
        return jsonify(out)
    # 1ª carga, cache ainda vazio → resposta leve "carregando" (frontend re-tenta)
    return jsonify({"rows": [], "alertas_comm_list": [], "alertas_strings_list": [],
                    "alertas_temp_list": [],
                    "summary": {"total_usinas": 0, "total_strings": 0, "alertas_strings": 0,
                                "alertas_temp": 0, "alertas_comm": 0},
                    "carregando": True, "cache_ts": datetime.now().strftime("%H:%M:%S")})


# ── ETM helpers ────────────────────────────────────────────────────────────────
def _get_meteo_val(cj: dict, *keys):
    """Retorna o primeiro valor numérico válido dentre as chaves."""
    for k in keys:
        v = cj.get(k)
        if v is None or v == "-":
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            pass
    return None


IRR_MAX_PLAUSIVEL = 1600.0   # W/m²: acima disso é leitura espúria (ex.: piraPOA1=6393)
def _pick_irr(cj: dict, *keys):
    """Escolhe a irradiância instantânea (W/m²) entre vários campos candidatos.
    Os campos variam por usina (IrPOA às vezes é energia/ciclo ~0,006; piraPOA1 às
    vezes vem espúrio ~6393; Ir costuma ser o confiável). Em vez de ordem fixa,
    pega o MAIOR valor PLAUSÍVEL (descarta None, '-' e valores > IRR_MAX_PLAUSIVEL).
    O instantâneo (centenas de W/m²) domina o per-ciclo (~0,006). Só sobrando
    valores espúrios/erro, cai no 1º numérico (comportamento antigo)."""
    vals = []
    for k in keys:
        v = cj.get(k)
        if v is None or v == "-":
            continue
        try:
            vals.append(float(v))
        except (TypeError, ValueError):
            pass
    if not vals:
        return None
    plaus = [v for v in vals if -50 <= v <= IRR_MAX_PLAUSIVEL]
    return max(plaus) if plaus else vals[0]


def _sensor_status(v) -> str:
    """ok = sensor funcionando, erro = valor de erro, sem = sem dados.
    Erro = sentinela negativa (ex.: -666, -10 sensor morto) ou leitura espúria
    (> IRR_MAX_PLAUSIVEL). POA/GHI reais de meio-dia chegam a ~1000+ W/m² → NÃO
    são erro (o limiar antigo de 500 marcava usinas saudáveis como erro)."""
    if v is None:
        return "sem"
    if v <= -50 or v > IRR_MAX_PLAUSIVEL:
        return "erro"
    return "ok"


def fetch_etm_plant(token: str, plant: dict) -> dict:
    pid  = plant["id"]
    nome = nome_usina(pid, plant["nome"])
    base = {
        "usina": nome, "plant_id": pid,
        "poa": None, "ghi": None, "poari": None,
        "poa_status": "sem", "ghi_status": "sem", "poari_status": "sem",
        "sem_dados": True, "ultima_leitura": None,
    }
    try:
        recs = _http().post(f"{BASE_URL}/day_meteo",
                             headers={"x-access-token": token},
                             json={"id": pid}, timeout=30).json()
    except Exception:
        return base
    if not recs:
        return base
    recs.sort(key=lambda x: x.get("tsleitura_new", ""), reverse=True)
    rec = recs[0]
    cj  = parse_cj(rec.get("conteudojson"))
    poa   = _pick_irr(cj, "IrPOA",    "piraPOA1",   "Ir1", "Ir")
    ghi   = _pick_irr(cj, "IrGHI",    "piraGHI1")
    poari = _pick_irr(cj, "IrPOA_RI", "piraPOA_RI1", "RadPoaRI")
    return {
        "usina": nome, "plant_id": pid,
        "poa":   round(poa,   2) if poa   is not None else None,
        "ghi":   round(ghi,   2) if ghi   is not None else None,
        "poari": round(poari, 2) if poari is not None else None,
        "poa_status":   _sensor_status(poa),
        "ghi_status":   _sensor_status(ghi),
        "poari_status": _sensor_status(poari),
        "sem_dados": False,
        "ultima_leitura": rec.get("tsleitura_new"),
    }


def etm_severidade(r: dict) -> int:
    if r.get("sem_dados"):
        return 0
    statuses = [r.get("poa_status"), r.get("ghi_status"), r.get("poari_status")]
    ok = sum(1 for s in statuses if s == "ok")
    if ok == 3:
        return 2   # Normal
    if ok >= 1:
        return 1   # Parcial
    return 0       # Sem sensores / sem dados


# ── Visão geral ETM ────────────────────────────────────────────────────────────
def _build_etm_payload():
    token      = get_token()
    all_plants = get_plants(token)
    plants     = [p for p in all_plants if p["nome"].strip() in FULL_OM] if FULL_OM else all_plants
    rows       = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = {ex.submit(fetch_etm_plant, token, p): p for p in plants}
        for f in as_completed(futures):
            rows.append(f.result())
    rows.sort(key=lambda x: (etm_severidade(x), x["usina"]))
    return {"rows": rows, "cache_ts": datetime.now().strftime("%H:%M:%S")}


@app.route("/api/etm")
def api_etm():
    force = flask_request.args.get("force", "0") == "1"
    return jsonify(_swr(_etm_cache, _build_etm_payload, force))


# ── Export ETM CSV ─────────────────────────────────────────────────────────────
@app.route("/api/etm/export")
def api_etm_export():
    import csv, io
    plant_id = flask_request.args.get("plant_id", type=int)
    if not plant_id:
        return jsonify({"error": "plant_id required"}), 400
    token = get_token()
    try:
        plants = get_plants(token)
        plant  = next((p for p in plants if p["id"] == plant_id), None)
        nome   = nome_usina(plant_id, plant["nome"]) if plant else str(plant_id)
    except Exception:
        nome = str(plant_id)
    try:
        all_recs = _http().post(f"{BASE_URL}/day_meteo",
                                  headers={"x-access-token": token},
                                  json={"id": plant_id}, timeout=30).json() or []
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    if not all_recs:
        return jsonify({"error": "Sem dados para esta usina"}), 404
    all_recs.sort(key=lambda x: x.get("tsleitura_new", ""))
    all_cj_keys: set = set()
    parsed = []
    for rec in all_recs:
        cj = parse_cj(rec.get("conteudojson"))
        all_cj_keys.update(cj.keys())
        row = {
            "tsleitura_new":   rec.get("tsleitura_new"),
            "dataleitura_new": rec.get("dataleitura_new"),
        }
        row.update(cj)
        parsed.append(row)
    skip = {"sn", "tpLei", "uid", "time_cycle", "tsleitura"}
    cols = ["tsleitura_new", "dataleitura_new"] + sorted(k for k in all_cj_keys if k not in skip)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for row in parsed:
        w.writerow(row)
    from flask import Response
    csv_bytes = buf.getvalue().encode("utf-8-sig")  # BOM → Excel abre corretamente
    safe_nome = re.sub(r"[^\w\s-]", "", nome).strip().replace(" ", "_")
    today_str = datetime.now().strftime("%Y-%m-%d")
    fname = f"ETM_{safe_nome}_{today_str}.csv"
    return Response(csv_bytes, mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={fname}"})


# ── ETM: curva intradiária do dia (gráfico) ────────────────────────────────────
@app.route("/api/etm/chart")
def api_etm_chart():
    plant_id = flask_request.args.get("plant_id", type=int)
    if not plant_id:
        return jsonify({"error": "plant_id required"}), 400
    token = get_token()
    try:
        recs = _http().post(f"{BASE_URL}/day_meteo",
                             headers={"x-access-token": token},
                             json={"id": plant_id}, timeout=30).json() or []
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    recs.sort(key=lambda x: x.get("tsleitura_new", ""))

    def _clamp(x):
        # Mantém só irradiância instantânea plausível (0–1600 W/m²); descarta erro/acumulado
        if x is None or x < -50 or x >= 1600:
            return None
        return round(max(0.0, x), 1)      # negativos pequenos (noite) → 0

    # IMPORTANTE: usar apenas campos INSTANTÂNEOS (IrPOA/Ir/Ir1, IrGHI).
    # Os campos pira* são ACUMULADOS (crescem o dia todo) e não servem p/ a curva.
    labels, poa, ghi, poari = [], [], [], []
    for rec in recs:
        ts = rec.get("tsleitura_new", "")
        if not ts:
            continue
        cj = parse_cj(rec.get("conteudojson"))
        labels.append(ts[11:16])          # HH:MM
        poa.append(_clamp(_pick_irr(cj, "IrPOA", "piraPOA1", "Ir", "Ir1")))
        ghi.append(_clamp(_pick_irr(cj, "IrGHI", "piraGHI1")))
        poari.append(_clamp(_pick_irr(cj, "IrPOA_RI", "piraPOA_RI1", "RadPoaRI")))
    return jsonify({"plant_id": plant_id, "labels": labels,
                    "poa": poa, "ghi": ghi, "poari": poari})


# ── ETM: pré-análise automática (varredura de anomalias na curva do dia) ───────
_etm_analise_cache = {"payload": None, "ts": 0.0}


def _etm_clamp(x):
    if x is None or x < -50 or x >= 1600:
        return None
    return round(max(0.0, x), 1)


def _diagnostico_etm(series: list) -> dict:
    """series = [(datetime, poa, ghi), ...] ordenada → {flags, severidade, spark, ultima_leitura}.

    Compartilhado por todas as fontes que tenham curva intradiária (PV, PG).
    """
    base = {"flags": [], "severidade": 3,
            "spark": {"labels": [], "poa": [], "ghi": []}, "ultima_leitura": None}
    series = [s for s in series if s[0] is not None]
    if not series:
        return base
    series.sort(key=lambda s: s[0])
    last_t = series[-1][0]
    agora  = datetime.now()
    flags  = []
    sev    = 3   # 0=crítico, 1=atenção, 3=normal

    # 1) Falha de comunicação — última leitura velha
    diff_min = (agora - last_t).total_seconds() / 60
    if diff_min > COMM_ALERT_MINUTES:
        flags.append({"t": "Sem comunicação", "tipo": "crit",
                      "info": f"última há {int(diff_min)} min"}); sev = min(sev, 0)

    # 2) POA zerado — em horário de sol o pico de POA é ~0
    janela = [(t, p) for (t, p, g) in series if 9 <= t.hour < 15]
    if janela and agora.hour >= 10:
        pico_jan = max([p for (_, p) in janela if p is not None] or [0])
        if pico_jan < 20:
            flags.append({"t": "POA zerado", "tipo": "crit",
                          "info": f"pico {pico_jan:.0f} W/m²"}); sev = min(sev, 0)

    dia = [(t, p, g) for (t, p, g) in series
           if (p is not None and p > 50) or (g is not None and g > 50)]

    # 3) GHI > POA na maior parte do tempo
    both = [(p, g) for (_, p, g) in dia if p is not None and g is not None]
    if len(both) >= 10:
        cnt = sum(1 for p, g in both if g > p + 5)
        frac = cnt / len(both)
        if frac > 0.6:
            flags.append({"t": "GHI > POA", "tipo": "warn",
                          "info": f"{int(frac*100)}% do tempo"}); sev = min(sev, 1)

    # 4) Quedas de POA a zero e volta (dropouts)
    poas = [p for (_, p, _) in series]
    drops, i, n = 0, 0, len(poas)
    while i < n:
        if poas[i] is not None and poas[i] < 5:
            j = i
            while j < n and poas[j] is not None and poas[j] < 5:
                j += 1
            antes  = poas[i-1] if i > 0 else None
            depois = poas[j]   if j < n else None
            if antes and depois and antes > 50 and depois > 50 and (j - i) <= 4:
                drops += 1
            i = j
        else:
            i += 1
    if drops >= 1:
        flags.append({"t": f"Quedas de POA ({drops})", "tipo": "warn",
                      "info": "caiu a zero e voltou"}); sev = min(sev, 1)

    # Sparkline (~48 pontos)
    k = max(1, n // 48)
    labels, sp_poa, sp_ghi = [], [], []
    for idx in range(0, n, k):
        t, p, g = series[idx]
        labels.append(t.strftime("%H:%M")); sp_poa.append(p); sp_ghi.append(g)

    return {"flags": flags, "severidade": sev,
            "spark": {"labels": labels, "poa": sp_poa, "ghi": sp_ghi},
            "ultima_leitura": last_t.strftime("%Y-%m-%d %H:%M")}


def _analisa_etm_plant(token: str, plant: dict) -> dict:
    """Pré-análise de uma usina via API PV (day_meteo)."""
    pid  = plant["id"]
    nome = nome_usina(pid, plant["nome"])
    base = {"usina": nome, "plant_id": pid, "flags": [], "severidade": 3,
            "spark": {"labels": [], "poa": [], "ghi": []},
            "ultima_leitura": None, "sem_dados": True}
    try:
        recs = _http().post(f"{BASE_URL}/day_meteo",
                             headers={"x-access-token": token},
                             json={"id": pid}, timeout=30).json() or []
    except Exception:
        return base
    if not recs:
        return base
    series = []
    for rec in recs:
        ts = rec.get("tsleitura_new", "")
        if not ts:
            continue
        try:
            t = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
        cj = parse_cj(rec.get("conteudojson"))
        series.append((t, _etm_clamp(_pick_irr(cj, "IrPOA", "piraPOA1", "Ir", "Ir1")),
                          _etm_clamp(_pick_irr(cj, "IrGHI", "piraGHI1"))))
    diag = _diagnostico_etm(series)
    if diag["ultima_leitura"] is None:
        return base
    return {"usina": nome, "plant_id": pid, "sem_dados": False, **diag}


def _agrupar_skids_etm(rows: list) -> list:
    """Agrupa skids da mesma UFV (mesmo código '(NNN)' no nome) num card só.
    Mostra o MELHOR skid do grupo (com dado, curva mais completa, leitura mais recente).
    UFVs com 1 skid só ficam intactas."""
    grupos = {}
    for r in rows:
        m = re.search(r"\((\d+)\)\s*$", r.get("usina", "").strip())
        chave = m.group(1) if m else f"__solo_{id(r)}"
        grupos.setdefault(chave, []).append(r)

    def _npts(r):
        sp = (r.get("spark") or {}).get("poa") or []
        return sum(1 for v in sp if v is not None)

    out = []
    for chave, lst in grupos.items():
        if len(lst) == 1 or chave.startswith("__solo_"):
            out.extend(lst); continue
        # melhor skid: tem dado > mais pontos de curva > leitura mais recente
        melhor = max(lst, key=lambda r: (not r.get("sem_dados", False),
                                         _npts(r), r.get("ultima_leitura") or ""))
        # nome do grupo = remove o nº do skid antes do "(NNN)"
        melhor = dict(melhor)
        melhor["usina"] = re.sub(r"\s*(?:-\s*Skid\s*[\d.]+|[\d.]+)\s*(\(\d+\))$",
                                 r" \1", melhor["usina"]).strip()
        melhor["skids"] = len(lst)   # quantos skids essa UFV tem (info p/ o card)
        out.append(melhor)
    return out


def _build_etm_analise_payload():
    token      = get_token()
    all_plants = get_plants(token)
    plants     = [p for p in all_plants if p["nome"].strip() in FULL_OM] if FULL_OM else all_plants
    rows = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_analisa_etm_plant, token, p): p for p in plants}
        for f in as_completed(futures):
            rows.append(f.result())
    rows = _agrupar_skids_etm(rows)   # junta skids da mesma UFV → 1 card por UFV (melhor skid)
    # Ordem pedida: Sem comunicação → Grave → Atenção → Normal
    def _ana_rank(r):
        flags = r.get("flags") or []
        if r.get("sem_dados") or any(str(fl.get("t", "")).startswith("Sem comunica") for fl in flags):
            return 0   # Sem comunicação (inclui "Sem dados")
        if r.get("severidade") == 0:
            return 1   # Grave (ex.: POA zerado)
        if r.get("severidade") == 1:
            return 2   # Atenção
        return 3       # Normal
    rows.sort(key=lambda x: (_ana_rank(x), x["usina"]))
    return {
        "rows": rows,
        "summary": {
            "total":   len(rows),
            "criticos": sum(1 for r in rows if r["severidade"] == 0),
            "atencao":  sum(1 for r in rows if r["severidade"] == 1),
            "sem_dados": sum(1 for r in rows if r.get("sem_dados")),
        },
        "cache_ts": datetime.now().strftime("%H:%M:%S"),
    }


@app.route("/api/etm/analise")
def api_etm_analise():
    force = flask_request.args.get("force", "0") == "1"
    return jsonify(_swr(_etm_analise_cache, _build_etm_analise_payload, force))


# ── SunOp: autenticação ───────────────────────────────────────────────────────
def get_sunop_token() -> str:
    tok = _sunop_token["token"]
    H   = {"Authorization": f"JWT {tok}", "Content-Type": "application/json"}
    try:
        if _http().get(f"{SUNOP_CONFIG}/check_token", headers=H, timeout=8).status_code == 200:
            return tok
    except Exception:
        pass
    # Tenta renovar automaticamente
    try:
        r = _http().get(f"{SUNOP_CONFIG}/refresh_token", headers=H, timeout=10)
        if r.status_code == 200:
            new_tok = r.json()
            if isinstance(new_tok, str):
                new_tok = new_tok.strip('"')
            _sunop_token["token"] = new_tok
            return new_tok
    except Exception:
        pass
    return tok


def _sunop_headers() -> dict:
    return {"Authorization": f"JWT {get_sunop_token()}",
            "Content-Type": "application/json"}


# ── SunOp: carrega metadados de uma planta ────────────────────────────────────
def _load_sunop_plant_meta(plant_name: str) -> dict:
    H = _sunop_headers()
    try:
        r = _http().get(f"{SUNOP_DATA}/v2/metadata", headers=H,
                         params={"plant": plant_name, "size": 6000}, timeout=30)
        items = r.json().get("data", [])
    except Exception:
        return {}

    inv_strings = {}   # inv_name → [pathnames de corrente I_PVx]
    inv_other   = {}   # inv_name → {TEMP_INT: path, P: path, EPD: path, Workstate: path}
    plant_paths = {}   # chave → path (ex: "EPD" → "CPP100.CALC.LOGGER.EPD")
    etm_stations = {}  # estação → {poa: path, ghi: path, poari: path} (ESTM, ESTM_1, ESTM_2…)
    trackers    = {}   # TRK_N → {alvo, atual, desvio, estado: path}

    _ETM_MEDIDA = {"POA.IRAD": "poa", "GHI.IRAD": "ghi", "POA_R.IRAD": "poari"}
    _TRK_MEDIDA = {"MEDIDAS.POSAL": "alvo", "MEDIDAS.POSAT": "atual",
                   "MEDIDAS.STRD_DEV": "desvio", "STATUS.WORKSTATE": "estado"}

    inv_max = SUNOP_INV_MAX.get(plant_name)   # nº máx de inversor com dados (None = sem limite)

    def _inv_acima_limite(sub: str) -> bool:
        """True se o inversor 'INV_N' ultrapassa o limite da planta (descartar)."""
        if inv_max is None:
            return False
        try:
            return int(sub.split("_")[1]) > inv_max
        except (IndexError, ValueError):
            return False

    for item in items:
        path  = item["pathname"]
        parts = path.split(".")
        if len(parts) < 3:
            continue
        sub = parts[1]

        # Descarta inversores acima do limite da planta (ex.: MTS100 > INV_40)
        if sub.startswith("INV_") and _inv_acima_limite(sub):
            continue

        # Correntes de string: PLANT.INV_N.MEDIDAS.STR.I_PVx
        if (len(parts) == 5 and sub.startswith("INV_") and
                parts[2] == "MEDIDAS" and parts[3] == "STR" and parts[4].startswith("I_PV")):
            inv_strings.setdefault(sub, []).append(path)

        # Medidas por inversor: PLANT.INV_N.MEDIDAS.{P|TEMP_INT|EPD|Workstate}
        elif (len(parts) == 4 and sub.startswith("INV_") and
              parts[2] == "MEDIDAS" and parts[3] in ("P", "TEMP_INT", "EPD", "Workstate")):
            inv_other.setdefault(sub, {})[parts[3]] = path

        # CALC nível planta
        elif sub == "CALC" and len(parts) >= 3:
            key = ".".join(parts[2:])
            plant_paths[key] = path

        # Estações meteorológicas: PLANT.ESTM[_N].{POA|GHI|POA_R}.IRAD
        elif sub.startswith("ESTM"):
            medida = _ETM_MEDIDA.get(".".join(parts[2:]))
            if medida:
                etm_stations.setdefault(sub, {})[medida] = path

        # Trackers: PLANT.TRK_N.{MEDIDAS.POSAL|POSAT|STRD_DEV | STATUS.WORKSTATE}
        elif sub.startswith("TRK_"):
            medida = _TRK_MEDIDA.get(".".join(parts[2:]))
            if medida:
                trackers.setdefault(sub, {})[medida] = path

    # Se há estações numeradas (ESTM_1, ESTM_2…), descarta a "ESTM" solta (redundante/agregada)
    numeradas = [s for s in etm_stations if s != "ESTM"]
    if numeradas:
        etm_stations = {s: etm_stations[s] for s in numeradas}

    return {
        "inv_strings":  inv_strings,   # {INV_N: [pathnames]}
        "inv_other":    inv_other,     # {INV_N: {medida: path}}
        "plant_paths":  plant_paths,   # {"LOGGER.EPD": path, ...}
        "etm_stations": etm_stations,  # {ESTM/ESTM_1/…: {poa,ghi,poari: path}}
        "trackers":     trackers,      # {TRK_N: {alvo,atual,desvio,estado: path}}
    }


def ensure_sunop_meta():
    """Carrega metadata de todas as plantas SunOp (lazy, uma vez por processo)."""
    if _sunop_meta:
        return
    H = _sunop_headers()
    try:
        plants = _http().get(f"{SUNOP_CONFIG}/plants", headers=H, timeout=15).json()
    except Exception as e:
        print(f"[SUNOP] Erro plants: {e}")
        return
    # Blindagem: se o token expirou, /api/plants devolve um dict de erro (ex.:
    # {"detail":"Token has expired."}) em vez da lista → não crashar.
    if not isinstance(plants, list) or not all(isinstance(p, dict) and "name" in p for p in plants):
        print(f"[SUNOP] /plants não retornou lista de plantas (token expirado?): {str(plants)[:120]}")
        return
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(_load_sunop_plant_meta, p["name"]): p["name"] for p in plants}
        for f in as_completed(futures):
            pname = futures[f]
            meta  = f.result()
            if meta:
                _sunop_meta[pname] = meta
    print(f"[SUNOP] Metadata: {len(_sunop_meta)} plantas carregadas")


# ── SunOp: processa uma planta ────────────────────────────────────────────────
def process_plant_sunop(plant_name: str) -> dict:
    base = {
        "usina": USINA_DISPLAY.get(plant_name, plant_name), "plant_id": plant_name,
        "qtd_inversores": None, "strings_ativas": None,
        "inv_esp": None, "str_esp": None, "diferenca": None,
        "temp_media": None, "ultima_leitura": None,
        "sem_dados": True, "falha_comunicacao": False,
        "energia_dia": None, "potencia_atual": None,
    }
    meta = _sunop_meta.get(plant_name)
    if not meta:
        return base

    # Monta lista de pathnames a buscar
    pathnames = []
    for inv, paths in meta["inv_strings"].items():
        pathnames.extend(paths)
    for inv, others in meta["inv_other"].items():
        pathnames.extend(others.values())
    # Métricas de planta
    for key in ("LOGGER.EPD", "LOGGER.TOT.P", "InvsProduzindo",
                "InvsParados", "InvsFalhaComunicacao"):
        if key in meta["plant_paths"]:
            pathnames.append(meta["plant_paths"][key])

    if not pathnames:
        return base

    # Busca em lotes de 500 (limite seguro da API)
    H = _sunop_headers()
    all_vals = []
    for i in range(0, len(pathnames), 500):
        batch = pathnames[i:i+500]
        try:
            r = _http().post(f"{SUNOP_DATA}/v2/last_values", headers=H,
                              json={"pathnames": batch}, timeout=30)
            if r.status_code == 200:
                all_vals.extend(r.json())
        except Exception:
            pass

    if not all_vals:
        return base

    # Indexa por pathname
    by_path = {v["pathname"]: v for v in all_vals}

    # Processa inversores
    temps       = []
    ts_max      = ""
    total_str   = 0
    total_ativas = 0
    qtd_inv_com_dados = 0

    for inv_name, str_paths in meta["inv_strings"].items():
        correntes, ids = [], []
        for p in sorted(str_paths,
                        key=lambda x: int(x.rsplit("I_PV", 1)[-1]) if x.rsplit("I_PV", 1)[-1].isdigit() else 999):
            if p not in by_path:
                continue
            v   = by_path[p].get("value")
            ts  = by_path[p].get("timestamp", "")
            if ts > ts_max:
                ts_max = ts
            if isinstance(v, (int, float)):
                ids.append(p.split(".")[-1]); correntes.append(v)

        if not correntes:
            continue
        qtd_inv_com_dados += 1
        # régua nova (igual API PV): exclui trancadas e classifica vs mediana do inversor
        ativas = _str_ativas(_classifica_strings(plant_name, inv_name, ids, correntes))
        total_str   += len(correntes)
        total_ativas += ativas

        # Temperatura do inversor
        temp_path = meta["inv_other"].get(inv_name, {}).get("TEMP_INT")
        if temp_path and temp_path in by_path:
            t = by_path[temp_path].get("value")
            if isinstance(t, (int, float)):
                temps.append(t)

    if qtd_inv_com_dados == 0:
        return base

    # Esperados: vêm do BD_Performance/Equipamentos (ESPERADO_INV), mesma fonte da API PV.
    # Soma apenas os inversores presentes na metadata (respeita limites como MTS100 > INV_40).
    esp_inv  = ESPERADO_INV.get(plant_name, {})
    esp_vals = [esp_inv[inv] for inv in meta["inv_strings"] if inv in esp_inv]
    str_esp  = sum(esp_vals) if esp_vals else None
    inv_esp  = len(meta["inv_strings"])
    diferenca = (total_ativas - str_esp) if str_esp is not None else None

    def _pval(key):
        path = meta["plant_paths"].get(key)
        return by_path[path]["value"] if (path and path in by_path) else None

    falha_n = _pval("InvsFalhaComunicacao")

    falha_comm = False
    if ts_max:
        try:
            diff = (datetime.now() - datetime.fromisoformat(ts_max)).total_seconds() / 60
            falha_comm = diff > COMM_ALERT_MINUTES
        except Exception:
            pass
    if falha_n and isinstance(falha_n, (int, float)) and falha_n > 0:
        falha_comm = True

    return {
        "usina": USINA_DISPLAY.get(plant_name, plant_name), "plant_id": plant_name,
        "qtd_inversores": qtd_inv_com_dados,
        "strings_ativas": total_ativas,
        "inv_esp": inv_esp,
        "str_esp": str_esp,
        "diferenca": diferenca,
        "temp_media": round(sum(temps) / len(temps), 1) if temps else None,
        "ultima_leitura": ts_max or None,
        "sem_dados": False,
        "falha_comunicacao": falha_comm,
    }


def fetch_all_sunop() -> list:
    ensure_sunop_meta()
    rows = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(process_plant_sunop, pname): pname
                   for pname in _sunop_meta}
        for f in as_completed(futures):
            rows.append(f.result())
    return sorted(rows, key=lambda x: (severidade(x), x["usina"]))


# ── SunOp: visão geral ────────────────────────────────────────────────────────
def _build_sunop_payload():
    rows = fetch_all_sunop()
    rows_com = [r for r in rows if not r.get("sem_dados")]
    return {
        "rows":     rows,
        "summary": {
            "total_usinas":    len(rows),
            "total_strings":   sum(r["strings_ativas"] for r in rows_com),
            "alertas_strings": sum(1 for r in rows_com if r["strings_ativas"] == 0),
            "alertas_temp":    sum(1 for r in rows_com if r["temp_media"] and r["temp_media"] >= TEMP_ALERT),
            "alertas_comm":    sum(1 for r in rows if r.get("sem_dados") or r.get("falha_comunicacao")),
        },
        "cache_ts": datetime.now().strftime("%H:%M:%S"),
    }


@app.route("/api/sunop/data")
def api_sunop_data():
    force = flask_request.args.get("force", "0") == "1"
    return jsonify(_swr(_sunop_cache, _build_sunop_payload, force))


# ── SunOp: drill-down inversores ──────────────────────────────────────────────
@app.route("/api/sunop/plant/<plant_name>")
def api_sunop_plant(plant_name):
    ensure_sunop_meta()
    meta = _sunop_meta.get(plant_name)
    if not meta:
        return jsonify({"inversores": []})

    pathnames = []
    for inv, paths in meta["inv_strings"].items():
        pathnames.extend(paths)
    for inv, others in meta["inv_other"].items():
        pathnames.extend(others.values())

    H = _sunop_headers()
    all_vals = []
    for i in range(0, len(pathnames), 500):
        try:
            r = _http().post(f"{SUNOP_DATA}/v2/last_values", headers=H,
                              json={"pathnames": pathnames[i:i+500]}, timeout=30)
            if r.status_code == 200:
                all_vals.extend(r.json())
        except Exception:
            pass

    by_path = {v["pathname"]: v for v in all_vals}

    inversores = []
    for inv_name in sorted(meta["inv_strings"].keys(),
                           key=lambda x: int(x.split("_")[1])):
        str_paths = meta["inv_strings"][inv_name]
        ids, correntes = [], []
        ts_inv = ""
        n_real = 0      # quantas strings vieram com leitura numérica real (não o fallback 0 A)
        for p in sorted(str_paths,
                        key=lambda x: int(x.rsplit("I_PV", 1)[-1]) if x.rsplit("I_PV", 1)[-1].isdigit() else 999):
            d  = by_path.get(p) or {}
            v  = d.get("value")
            ts = d.get("timestamp", "")
            if ts > ts_inv:
                ts_inv = ts
            # Lista TODAS as strings conhecidas do inversor (metadata), mesmo sem leitura:
            # valor real quando a API devolve, senão 0 A — assim um inversor sem geração
            # ainda mostra suas strings (em 0 A) ao expandir, em vez de vir vazio.
            ids.append(p.split(".")[-1])
            if isinstance(v, (int, float)):
                correntes.append(v); n_real += 1
            else:
                correntes.append(0.0)
        _st     = _classifica_strings(plant_name, inv_name, ids, correntes)
        strings = [{"id": i, "corrente": c, "status": s,
                    "ativa": s in ("ativa", "baixa_perf"), "trancada": s == "trancada"}
                   for i, c, s in zip(ids, correntes, _st)]

        others = meta["inv_other"].get(inv_name, {})
        def _ov(key):
            p = others.get(key)
            return by_path[p]["value"] if (p and p in by_path) else None

        temp       = _ov("TEMP_INT")
        eday       = _ov("EPD")
        str_ativas  = _str_ativas(_st)
        desligado   = n_real == 0      # nenhuma leitura real → inversor desligado/sem comunicação
        # Strings esperadas vêm do BD_Performance/Equipamentos (ESPERADO_INV), igual à API PV
        str_esp_inv = ESPERADO_INV.get(plant_name, {}).get(inv_name)
        inv_diferenca = (str_ativas - str_esp_inv) if (str_esp_inv is not None and not desligado) else None

        falha = False
        if ts_inv:
            try:
                diff = (datetime.now() - datetime.fromisoformat(ts_inv)).total_seconds() / 60
                falha = diff > COMM_ALERT_MINUTES
            except Exception:
                pass

        # Traduz nome do inversor pela nomenclatura da planilha (Equipamento), ex.: INV_1 → Inversor 1.1
        inv_display = EQUIP_NAMES.get(plant_name, {}).get(inv_name, inv_name)
        inversores.append({
            "id": inv_name, "nome": inv_display, "nome_api": inv_name,
            "ultima_leitura": ts_inv or None,
            "falha_comunicacao": falha,
            "desligado": desligado,
            "strings_ativas": str_ativas,
            "total_strings": len(strings),
            "str_esp": str_esp_inv,
            "diferenca": inv_diferenca,
            "temp": temp, "eday": eday,
            "strings": strings,
        })

    return jsonify({"plant_id": plant_name, "inversores": inversores})


# ── SunOp ETM ─────────────────────────────────────────────────────────────────
def _etm_label(station: str) -> str:
    """'ESTM' → '' (estação única); 'ESTM_1' → 'ESTM 1'."""
    return "" if station == "ESTM" else station.replace("_", " ")


def fetch_sunop_etm_plant(plant_name: str) -> list:
    """Retorna UMA linha por estação meteorológica da planta (ESTM, ESTM_1, ESTM_2…)."""
    meta     = _sunop_meta.get(plant_name, {})
    stations = meta.get("etm_stations") or {"ESTM": {
        "poa":   f"{plant_name}.ESTM.POA.IRAD",
        "ghi":   f"{plant_name}.ESTM.GHI.IRAD",
        "poari": f"{plant_name}.ESTM.POA_R.IRAD",
    }}

    def _base(station):
        return {
            "usina": USINA_DISPLAY.get(plant_name, plant_name), "plant_id": plant_name,
            "etm": _etm_label(station),
            "poa": None, "ghi": None, "poari": None,
            "poa_status": "sem", "ghi_status": "sem", "poari_status": "sem",
            "sem_dados": True, "ultima_leitura": None,
        }

    # Junta todos os pathnames de todas as estações numa única requisição
    all_paths = []
    for paths in stations.values():
        all_paths.extend(paths.values())

    H = _sunop_headers()
    by_path = {}
    if all_paths:
        try:
            r = _http().post(f"{SUNOP_DATA}/v2/last_values", headers=H,
                              json={"pathnames": all_paths}, timeout=15)
            if r.status_code == 200:
                by_path = {v["pathname"]: v for v in (r.json() or [])}
        except Exception:
            by_path = {}

    def _val(path):
        v = by_path.get(path, {}).get("value")
        if v is None or v == "-":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    rows = []
    for station in sorted(stations):
        paths = stations[station]
        if not by_path:
            rows.append(_base(station))
            continue
        ts_max = max((by_path.get(p, {}).get("timestamp", "")
                      for p in paths.values()), default="")
        poa   = _val(paths.get("poa", ""))
        ghi   = _val(paths.get("ghi", ""))
        poari = _val(paths.get("poari", ""))
        rows.append({
            "usina": USINA_DISPLAY.get(plant_name, plant_name), "plant_id": plant_name,
            "etm": _etm_label(station),
            "poa":   round(poa,   2) if poa   is not None else None,
            "ghi":   round(ghi,   2) if ghi   is not None else None,
            "poari": round(poari, 2) if poari is not None else None,
            "poa_status":   _sensor_status(poa),
            "ghi_status":   _sensor_status(ghi),
            "poari_status": _sensor_status(poari),
            "sem_dados": False,
            "ultima_leitura": ts_max or None,
        })
    return rows


def _build_sunop_etm_payload():
    ensure_sunop_meta()
    rows = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(fetch_sunop_etm_plant, pname): pname for pname in _sunop_meta}
        for f in as_completed(futures):
            rows.extend(f.result())   # uma ou mais linhas por planta (uma por estação)
    rows.sort(key=lambda x: (etm_severidade(x), x["usina"], x.get("etm", "")))
    return {"rows": rows, "cache_ts": datetime.now().strftime("%H:%M:%S")}


@app.route("/api/sunop/etm")
def api_sunop_etm():
    force = flask_request.args.get("force", "0") == "1"
    return jsonify(_swr(_sunop_etm_cache, _build_sunop_etm_payload, force))


# ── SunOp: pré-análise ETM (CURVA REAL via /data/v2/analog_values) ─────────────
_sunop_analise_cache = {"payload": None, "ts": 0.0}


def _sunop_etm_estacoes():
    """→ lista de (plant, station_raw, {poa,ghi,poari: path}) p/ todas as estações."""
    out = []
    for plant, meta in _sunop_meta.items():
        stations = meta.get("etm_stations") or {"ESTM": {
            "poa": f"{plant}.ESTM.POA.IRAD", "ghi": f"{plant}.ESTM.GHI.IRAD",
            "poari": f"{plant}.ESTM.POA_R.IRAD"}}
        for st, paths in stations.items():
            out.append((plant, st, paths))
    return out


def _merge_etm(hist: dict, paths: dict):
    """Junta POA/GHI/POA-RI por timestamp → lista ordenada de (ts_str, poa, ghi, poari)."""
    byts = {}
    for key in ("poa", "ghi", "poari"):
        p = paths.get(key)
        if not p:
            continue
        for ts, v in hist.get(p, []):
            byts.setdefault(ts, {})[key] = _etm_clamp(v)
    return [(ts, d.get("poa"), d.get("ghi"), d.get("poari")) for ts, d in sorted(byts.items())]


def _build_sunop_analise_payload():
    ensure_sunop_meta()
    estacoes = _sunop_etm_estacoes()
    dia = datetime.now().strftime("%Y-%m-%d")
    all_paths = [paths[k] for _, _, paths in estacoes for k in ("poa", "ghi", "poari") if paths.get(k)]
    hist = _sunop_analog_history(all_paths, f"{dia}T00:00:00", f"{dia}T23:59:59")

    rows = []
    for plant, st, paths in estacoes:
        nome = USINA_DISPLAY.get(plant, plant)
        lbl  = _etm_label(st)
        if lbl:
            nome = f"{nome} · {lbl}"
        merged = _merge_etm(hist, paths)
        if not merged:
            rows.append({"usina": nome, "plant_id": plant, "etm_est": st,
                         "flags": [], "severidade": 3, "sem_curva": False,
                         "spark": {"labels": [], "poa": [], "ghi": []},
                         "ultima_leitura": None, "sem_dados": True})
            continue
        series = [(datetime.fromisoformat(ts), poa, ghi) for ts, poa, ghi, _ in merged]
        diag = _diagnostico_etm(series)
        # enriquece o sparkline com a 3ª curva (POA-RI), alinhada por amostragem
        k = max(1, len(merged) // 48)
        sp = merged[::k]
        diag["spark"] = {
            "labels": [ts[11:16] for ts, _, _, _ in sp],
            "poa":   [p for _, p, _, _ in sp],
            "ghi":   [g for _, _, g, _ in sp],
            "poari": [r for _, _, _, r in sp],
        }
        rows.append({"usina": nome, "plant_id": plant, "etm_est": st,
                     "sem_dados": False, "sem_curva": False, **diag})
    rows.sort(key=lambda x: (x["severidade"], x["usina"]))
    return {
        "rows": rows,
        "summary": {"total": len(rows),
                    "criticos": sum(1 for r in rows if r["severidade"] == 0),
                    "atencao":  sum(1 for r in rows if r["severidade"] == 1),
                    "sem_dados": sum(1 for r in rows if r.get("sem_dados"))},
        "cache_ts": datetime.now().strftime("%H:%M:%S"),
    }


@app.route("/api/sunop/etm/analise")
def api_sunop_etm_analise():
    force = flask_request.args.get("force", "0") == "1"
    return jsonify(_swr(_sunop_analise_cache, _build_sunop_analise_payload, force))


@app.route("/api/sunop/etm/chart")
def api_sunop_etm_chart():
    plant = (flask_request.args.get("plant") or "").strip()
    est   = (flask_request.args.get("estacao") or "ESTM").strip() or "ESTM"
    dia   = (flask_request.args.get("date") or datetime.now().strftime("%Y-%m-%d")).strip()
    ensure_sunop_meta()
    meta = _sunop_meta.get(plant, {})
    stations = meta.get("etm_stations") or {"ESTM": {
        "poa": f"{plant}.ESTM.POA.IRAD", "ghi": f"{plant}.ESTM.GHI.IRAD",
        "poari": f"{plant}.ESTM.POA_R.IRAD"}}
    paths = stations.get(est) or {}
    used = [paths[k] for k in ("poa", "ghi", "poari") if paths.get(k)]
    hist = _sunop_analog_history(used, f"{dia}T00:00:00", f"{dia}T23:59:59")
    merged = _merge_etm(hist, paths)
    return jsonify({
        "labels": [ts[11:16] for ts, _, _, _ in merged],
        "poa":   [p for _, p, _, _ in merged],
        "ghi":   [g for _, _, g, _ in merged],
        "poari": [r for _, _, _, r in merged],
    })


# ── SunOp: Trackers (POSAL alvo, POSAT atual, desvio, estado) ──────────────────
TRK_DISP_LEVE   = 5.0    # ° — disparidade alvo×atual: alerta leve (overview, instantâneo)
TRK_DISP_SEVERO = 10.0   # ° — disparidade alvo×atual: alerta severo (overview, instantâneo)
TRK_FORA_MEDIA  = 3.0    # ° — desvio do ângulo atual vs média da usina
# Análise por CURVA do dia (drill-down):
TRK_PARADO_AMP   = 15.0  # ° — amplitude do ângulo no dia abaixo disto = "parado" (linha reta)
TRK_ALVO_MOVE_MIN = 30.0 # ° — só conta "parado" se os VIZINHOS variaram mais que isto (houve movimento)
TRK_DESVIO_MIN   = 5.0   # ° — disparidade ATUAL acima da MEDIANA da planta (e não parado) = "desvio"
TRK_ATRASO_DELTA = 10.0  # ° — disparidade MÁX do dia acima da MEDIANA da planta = "atraso" (amarelo)
#   (relativo à mediana p/ descontar o "ruído estrutural": o alvo costuma ir a ângulos mais
#    extremos que o tracker alcança nas pontas do dia → ~11° de disparidade máx é NORMAL)
_sunop_trk_cache = {"payload": None, "ts": 0.0}
_sunop_trk_hist  = {}    # cache {(plant,date): {ts, posat:{name:serie}, posal:{name:serie}}}

# ── Acumulador intradiário de disparidade dos trackers ─────────────────────────
# "Desvio médio do dia" SEM rebaixar a curva inteira de cada usina a cada refresh
# (pesado; a PV Plataforma throttla). Aproveitamos a leitura INSTANTÂNEA que o
# overview já faz: a cada amostra nova (ts avançou, dentro de 9h-15h) somamos
# |alvo-atual| por tracker. Desvio médio = soma÷contagem → O(1) de memória.
# Persiste junto do snapshot de cache e zera na virada do dia. Compartilhado pelas
# três fontes (PV Plataforma, SunOp, PG) — a aba Trackers é a mesma.
TRK_DIA_INI = 9     # hora inicial da janela do desvio do dia (inclusiva)
TRK_DIA_FIM = 15    # hora final (exclusiva)
_trk_accum = {"date": "", "plants": {}}   # plants[str(pid)] = {"last_ts": str, "trk": {tid: {"n","sum"}}}
_trk_accum_lock = threading.Lock()


def _trk_accum_feed(pid, ts, trios):
    """trios = [(tracker_id, disparidade|None, ângulo_atual|None)]. Acumula 1 amostra por
    usina durante o horário de operação (9-15h, HORA LOCAL — robusto a leituras em UTC),
    usando o ts da leitura só p/ não contar a mesma duas vezes. Por tracker guarda a soma
    da disparidade (→ desvio médio) e o mín/máx do ângulo (→ amplitude, p/ achar travado).
    Zera na virada do dia."""
    agora = datetime.now()
    hoje  = agora.strftime("%Y-%m-%d")
    key   = str(pid)
    # chave de dedup: o ts da leitura; se vier vazio, um balde de 5 min do relógio
    sts = str(ts) if ts else agora.strftime("%Y-%m-%dT%H:") + str(agora.minute // 5)
    with _trk_accum_lock:
        if _trk_accum["date"] != hoje:
            _trk_accum["date"], _trk_accum["plants"] = hoje, {}
        if not (TRK_DIA_INI <= agora.hour < TRK_DIA_FIM):
            return                      # fora do horário de operação — não amostra
        ent = _trk_accum["plants"].setdefault(key, {"last_ts": "", "samples": 0, "trk": {}})
        if sts == ent["last_ts"]:
            return                      # mesma leitura — não conta de novo
        ent["last_ts"] = sts
        ent["samples"] = ent.get("samples", 0) + 1
        for tid, disp, atual in trios:
            d = ent["trk"].setdefault(str(tid), {"n": 0, "sum": 0.0, "amin": None, "amax": None})
            if disp is not None:
                d["n"] += 1
                d["sum"] += abs(disp)
            if atual is not None:       # .get() tolera entradas antigas (sem amin/amax)
                d["amin"] = atual if d.get("amin") is None else min(d["amin"], atual)
                d["amax"] = atual if d.get("amax") is None else max(d["amax"], atual)
    _persist_mark()


def _trk_accum_desvio(pid):
    """Desvio médio do dia = média (entre trackers) da disparidade média de cada
    tracker na janela 9-15h. None enquanto não houver amostras (ex.: antes das 9h)."""
    with _trk_accum_lock:
        ent = _trk_accum["plants"].get(str(pid))
        medias = [d["sum"] / d["n"] for d in ent["trk"].values() if d["n"] > 0] if ent else []
    return round(sum(medias) / len(medias), 2) if medias else None


def _trk_accum_parados(pid):
    """IDs dos trackers 'travados' hoje: amplitude do ângulo < TRK_PARADO_AMP enquanto a
    usina girou (mediana das amplitudes > TRK_ALVO_MOVE_MIN). Exige um mínimo de amostras
    p/ não acusar travado no começo do dia, quando ninguém girou ainda. Pega o tracker
    parado o dia inteiro — que o instantâneo (alvo×atual) perde quando o sol cruza o ângulo
    em que ele congelou."""
    with _trk_accum_lock:
        ent = _trk_accum["plants"].get(str(pid))
        if not ent or ent.get("samples", 0) < 6:
            return set()
        amps = {tid: (d["amax"] - d["amin"]) for tid, d in ent["trk"].items()
                if d.get("amin") is not None and d.get("amax") is not None}
    if not amps:
        return set()
    med = sorted(amps.values())[len(amps) // 2]
    if med < TRK_ALVO_MOVE_MIN:
        return set()                    # a usina como um todo não girou — não dá p/ julgar
    return {tid for tid, a in amps.items() if a < TRK_PARADO_AMP}


def _sunop_trackers_plant(plant_name: str) -> dict:
    """Lê e analisa os trackers de uma planta SunOp → resumo + lista por tracker."""
    meta = _sunop_meta.get(plant_name, {})
    trk  = meta.get("trackers") or {}
    base = {"usina": USINA_DISPLAY.get(plant_name, plant_name), "plant_id": plant_name,
            "total": 0, "severos": 0, "leves": 0, "fora_media": 0,
            "media_angulo": None, "pior_disparidade": None, "ultima_leitura": None,
            "trackers": [], "tem_trackers": bool(trk)}
    if not trk:
        return base

    paths = [p for d in trk.values() for p in d.values()]
    by_path, H = {}, _sunop_headers()
    for i in range(0, len(paths), 500):
        try:
            r = _http().post(f"{SUNOP_DATA}/v2/last_values", headers=H,
                              json={"pathnames": paths[i:i + 500]}, timeout=30)
            if r.status_code == 200:
                for v in (r.json() or []):
                    by_path[v.get("pathname")] = v
        except Exception:
            pass

    def _val(p):
        v = by_path.get(p, {}).get("value")
        return float(v) if isinstance(v, (int, float)) else None

    lst, atuais, ts_max = [], [], ""
    for name in sorted(trk.keys(), key=lambda x: int(x.split("_")[1]) if x.split("_")[1].isdigit() else 999):
        d = trk[name]
        alvo, atual = _val(d.get("alvo", "")), _val(d.get("atual", ""))
        desvio, estado = _val(d.get("desvio", "")), _val(d.get("estado", ""))
        for p in d.values():
            ts = by_path.get(p, {}).get("timestamp", "")
            if ts > ts_max:
                ts_max = ts
        disp = abs(alvo - atual) if (alvo is not None and atual is not None) else None
        if atual is not None:
            atuais.append(atual)
        lst.append({"id": name.replace("TRK_", "Tracker "), "alvo": alvo, "atual": atual,
                    "disparidade": round(disp, 2) if disp is not None else None,
                    "desvio": round(desvio, 2) if desvio is not None else None,
                    "estado": estado})

    media = sum(atuais) / len(atuais) if atuais else None
    # Média do ângulo ATUAL por grupo de MESMO ALVO (trackers c/ mesmo alvo devem estar
    # no mesmo ângulo) → detecta um tracker fora de linha sem distorcer por alvos diferentes.
    grupos = {}
    for t in lst:
        if t["alvo"] is not None and t["atual"] is not None:
            grupos.setdefault(round(t["alvo"], 1), []).append(t["atual"])
    media_grupo = {k: sum(v) / len(v) for k, v in grupos.items()}

    sev = leve = fora = 0
    for t in lst:
        disp, alvo, atual = t["disparidade"], t["alvo"], t["atual"]
        gkey = round(alvo, 1) if alvo is not None else None
        if disp is not None and disp > TRK_DISP_SEVERO:
            t["status"] = "severo"; sev += 1
        elif disp is not None and disp > TRK_DISP_LEVE:
            t["status"] = "leve"; leve += 1
        elif (gkey in media_grupo and atual is not None
              and abs(atual - media_grupo[gkey]) > TRK_FORA_MEDIA):
            t["status"] = "fora_media"; fora += 1
        else:
            t["status"] = "normal"
    pior = max((t["disparidade"] for t in lst if t["disparidade"] is not None), default=None)
    _trk_accum_feed(plant_name, ts_max, [(t["id"], t["disparidade"], t["atual"]) for t in lst])
    # travado o dia todo (amplitude ~0 enquanto a usina girou) — sobrepõe o instantâneo e conta como severo
    _par = _trk_accum_parados(plant_name)
    for t in lst:
        if str(t["id"]) in _par:
            t["status"] = "parado"
    sev  = sum(1 for t in lst if t["status"] in ("severo", "parado"))
    leve = sum(1 for t in lst if t["status"] == "leve")
    fora = sum(1 for t in lst if t["status"] == "fora_media")
    base.update({"total": len(lst), "severos": sev, "leves": leve, "fora_media": fora,
                 "media_angulo": round(media, 1) if media is not None else None,
                 "pior_disparidade": round(pior, 2) if pior is not None else None,
                 "desvio_medio": _trk_accum_desvio(plant_name),
                 "ultima_leitura": ts_max or None, "trackers": lst})
    return base


def _sunop_trk_curvas(plant_name: str, date: str) -> dict:
    """Busca (e cacheia) as curvas do dia POSAT/POSAL de todos os trackers da planta."""
    key = (plant_name, date)
    ent = _sunop_trk_hist.get(key)
    if ent and time.time() - ent["ts"] < CACHE_TTL:
        return ent
    trk = (_sunop_meta.get(plant_name, {}) or {}).get("trackers") or {}
    posat = {n: d["atual"] for n, d in trk.items() if d.get("atual")}
    posal = {n: d["alvo"]  for n, d in trk.items() if d.get("alvo")}
    hist = _sunop_analog_history(list(posat.values()) + list(posal.values()),
                                 f"{date}T00:00:00", f"{date}T23:59:59")
    ent = {"ts": time.time(),
           "posat": {n: hist.get(p, []) for n, p in posat.items()},
           "posal": {n: hist.get(p, []) for n, p in posal.items()}}
    _sunop_trk_hist[key] = ent
    return ent


def _sunop_trackers_plant_curva(plant_name: str) -> dict:
    """Análise por CURVA do dia:
    - 'parado' (vermelho): amplitude do ângulo baixa enquanto os VIZINHOS se moveram (não
      precisa de alvo → funciona em plantas sem POSAL, ex.: MAB100).
    - 'desvio' (laranja): disparidade alvo×atual ATUAL > limiar (está fora do ângulo agora).
    - 'atraso' (amarelo): disparidade MÁX do dia > limiar mas já voltou (saiu por pouco tempo).
    Trackers/plantas SEM alvo (POSAL) → só 'parado'/'normal' (sem desvio/atraso)."""
    meta = _sunop_meta.get(plant_name, {})
    trk  = meta.get("trackers") or {}
    base = {"usina": USINA_DISPLAY.get(plant_name, plant_name), "plant_id": plant_name,
            "total": 0, "parados": 0, "desvios": 0, "atrasos": 0, "sem_alvo": False,
            "pior_disparidade": None, "ultima_leitura": None,
            "trackers": [], "tem_trackers": bool(trk)}
    if not trk:
        return base
    cur = _sunop_trk_curvas(plant_name, datetime.now().strftime("%Y-%m-%d"))
    posat, posal = cur["posat"], cur["posal"]

    def _num(n):
        try: return int(n.split("_")[1])
        except Exception: return 999

    # amplitude de cada tracker + referência (mediana) = "quanto os trackers se moveram"
    amps = {n: (max(v for _, v in s) - min(v for _, v in s)) if s else None
            for n, s in posat.items()}
    amp_ok = sorted(a for a in amps.values() if a is not None)
    amp_ref = amp_ok[len(amp_ok) // 2] if amp_ok else 0.0          # mediana
    sem_alvo = all(not posal.get(n) for n in trk)                  # planta sem POSAL

    # Passada 1: coleta valores brutos por tracker
    raw, ts_max = [], ""
    for name in sorted(trk.keys(), key=_num):
        s, sp = posat.get(name, []), posal.get(name, [])
        atual = s[-1][1] if s else None
        alvo  = sp[-1][1] if sp else None
        if s and s[-1][0] > ts_max:
            ts_max = s[-1][0]
        cur_disp = max_disp = None
        if s and sp:
            alvo_ts = dict(sp)
            disps = [abs(v - alvo_ts[ts]) for ts, v in s if ts in alvo_ts]
            if disps:
                max_disp, cur_disp = max(disps), disps[-1]
        raw.append({"name": name, "atual": atual, "alvo": alvo, "amp": amps.get(name),
                    "cur_disp": cur_disp, "max_disp": max_disp})

    def _mediana(vals):
        v = sorted(x for x in vals if x is not None)
        return v[len(v) // 2] if v else 0.0
    med_cur = _mediana([r["cur_disp"] for r in raw])   # ruído estrutural ATUAL da planta
    med_max = _mediana([r["max_disp"] for r in raw])   # ruído estrutural MÁX da planta

    # Passada 2: classifica (parado peer-based; desvio/atraso relativos à mediana)
    lst, parados, desvios, atrasos = [], 0, 0, 0
    for r in raw:
        amp, cur_disp, max_disp = r["amp"], r["cur_disp"], r["max_disp"]
        if amp is not None and amp < TRK_PARADO_AMP and amp_ref > TRK_ALVO_MOVE_MIN:
            status = "parado"; parados += 1
        elif cur_disp is not None and (cur_disp - med_cur) > TRK_DESVIO_MIN:
            status = "desvio"; desvios += 1
        elif max_disp is not None and (max_disp - med_max) > TRK_ATRASO_DELTA:
            status = "atraso"; atrasos += 1
        else:
            status = "normal"
        lst.append({"id": r["name"].replace("TRK_", "Tracker "),
                    "alvo":  round(r["alvo"], 2)  if r["alvo"]  is not None else None,
                    "atual": round(r["atual"], 2) if r["atual"] is not None else None,
                    "disparidade": round(cur_disp, 2) if cur_disp is not None else None,
                    "max_disp":    round(max_disp, 1) if max_disp is not None else None,
                    "amplitude":   round(amp, 1)  if amp  is not None else None,
                    "status": status})
    pior = max((t["max_disp"] for t in lst if t["max_disp"] is not None), default=None)
    base.update({"total": len(lst), "parados": parados, "desvios": desvios, "atrasos": atrasos,
                 "sem_alvo": sem_alvo, "amp_ref": round(amp_ref, 1),
                 "pior_disparidade": round(pior, 2) if pior is not None else None,
                 "ultima_leitura": ts_max or None, "trackers": lst})
    return base


def _trk_severidade(r) -> int:
    if r.get("severos"):    return 0
    if r.get("leves"):      return 1
    if r.get("fora_media"): return 2
    if not r.get("total"):  return 4
    return 3


def _build_sunop_trk_payload():
    ensure_sunop_meta()
    plantas = [p for p, m in _sunop_meta.items() if m.get("trackers")]
    rows = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(_sunop_trackers_plant, p): p for p in plantas}
        for f in as_completed(futures):
            r = f.result()
            r.pop("trackers", None)   # overview não carrega a lista completa
            rows.append(r)
    rows.sort(key=lambda x: (_trk_severidade(x), x["usina"]))
    return {
        "rows": rows,
        "summary": {
            "usinas":  len(rows),
            "trackers": sum(r["total"] for r in rows),
            "severos": sum(r["severos"] for r in rows),
            "leves":   sum(r["leves"] for r in rows),
        },
        "cache_ts": datetime.now().strftime("%H:%M:%S"),
    }


@app.route("/api/sunop/trackers")
def api_sunop_trackers():
    force = flask_request.args.get("force", "0") == "1"
    return jsonify(_swr(_sunop_trk_cache, _build_sunop_trk_payload, force))


@app.route("/api/sunop/trackers/<plant_name>")
def api_sunop_trackers_plant(plant_name):
    ensure_sunop_meta()
    return jsonify(_sunop_trackers_plant_curva(plant_name))   # análise por curva do dia


# ── SunOp: HISTÓRICO intradiário (endpoint /data/v2/analog_values) ─────────────
#   Descoberto via DevTools: POST com pathnames no corpo + start/end na query.
#   Serve curva do dia de QUALQUER medida analógica (tracker POSAT/POSAL, POA, GHI…),
#   inclusive datas passadas (source=Historical).
def _sunop_analog_history(pathnames: list, start: str, end: str) -> dict:
    """→ {pathname: [(timestamp, value), ...]} ordenado por tempo."""
    H = _sunop_headers()
    params = {"fill_missing": "false", "source": "Historical",
              "start_time": start, "end_time": end, "use_plant_timezone": "true"}
    batches = [pathnames[i:i + 40] for i in range(0, len(pathnames), 40)]

    def _fetch(batch):
        try:
            r = _http().post(f"{SUNOP_DATA}/v2/analog_values", headers=H,
                              params=params, json={"pathnames": batch}, timeout=60)
            return r.json() or [] if r.status_code == 200 else []
        except Exception:
            return []

    out = {}
    # lotes em paralelo: 1 inversor já é ~28 paths (1 lote); a usina inteira eram ~18 lotes
    # em série — o serial era o que deixava a curva do dia lenta.
    with ThreadPoolExecutor(max_workers=min(6, len(batches) or 1)) as ex:
        for recs in ex.map(_fetch, batches):
            for rec in recs:
                v = rec.get("value")
                if isinstance(v, (int, float)):
                    out.setdefault(rec["pathname"], []).append((rec["timestamp"], v))
    for p in out:
        out[p].sort()
    return out


# ── SunOp: curva diária de corrente por string (botão "Curva do dia") ──────────
#   Mesma FORMA do SPV (reusa _spvPlotInto). Fonte = histórico analógico das strings.
def _sunop_strings_curva(plant_name: str, dia: str, inv=None) -> dict:
    ensure_sunop_meta()
    meta = _sunop_meta.get(plant_name)
    if not meta:
        return {"plant_id": plant_name, "data": dia, "inversores": []}
    inv_strings = meta["inv_strings"]
    nomes = [inv] if (inv and inv in inv_strings) else list(inv_strings.keys())
    allp  = [p for n in nomes for p in inv_strings.get(n, [])]
    hist  = _sunop_analog_history(allp, f"{dia}T00:00:00", f"{dia}T23:59:59")

    def _invnum(x):
        try: return int(x.split("_")[1])
        except Exception: return 999

    def _pvnum(x):
        t = x.rsplit("I_PV", 1)[-1]
        return int(t) if t.isdigit() else 999

    out = []
    for inv_name in sorted(nomes, key=_invnum):
        soma, curva = {}, {}
        for p in sorted(meta["inv_strings"][inv_name], key=_pvnum):
            serie = hist.get(p, [])
            if not serie:
                continue
            num = "".join(c for c in p.split(".")[-1] if c.isdigit()) or "0"
            lbl = f"ST {int(num):02d}"
            soma[lbl] = sum(max(0.0, v) for _, v in serie)
            step = max(1, len(serie) // 160); sp = serie[::step]
            curva[lbl] = {"x": [str(t)[11:16] for t, _ in sp], "y": [round(v, 2) for _, v in sp]}
        if not curva:
            continue
        vals = sorted(soma.values()); med = vals[len(vals) // 2] if vals else 0.0
        strings, abaixo = [], 0
        for lbl in sorted(soma, key=_spv_stnum):
            e = soma[lbl]; sub = (med > 0 and e < med * SPV_SUB_FRAC); abaixo += 1 if sub else 0
            strings.append({"nome": lbl, "ativa": e > 0, "sub": sub,
                            "energia": round(e, 1), "pct": round(100.0 * e / med) if med else None})
        out.append({"id": inv_name, "nome": EQUIP_NAMES.get(plant_name, {}).get(inv_name, inv_name),
                    "nome_api": inv_name, "curva": curva, "mediana": round(med, 1),
                    "abaixo": abaixo, "strings": strings})
    return {"plant_id": plant_name, "data": dia, "inversores": out}


@app.route("/api/sunop/curva/<plant_name>")
def api_sunop_curva(plant_name):
    dia = (flask_request.args.get("data") or datetime.now().strftime("%Y-%m-%d")).strip()
    if re.match(r"^\d{2}/\d{2}/\d{4}$", dia):
        dia = datetime.strptime(dia, "%d/%m/%Y").strftime("%Y-%m-%d")
    inv = (flask_request.args.get("inv") or "").strip() or None   # opcional: só um inversor (inv_name)
    try:
        return jsonify(_sunop_strings_curva(plant_name, dia, inv))
    except Exception as e:
        return jsonify({"error": str(e), "inversores": []}), 500


# ── SunOp (Athon): PR por inversor ─────────────────────────────────────────────
#   PR_inv = geração_inv_dia (EPD, kWh) ÷ (IPOA_dia × potência_inv). EPD = MAX da
#   energia diária do inversor no histórico; IPOA = integração trapezoidal do POA
#   do ETM SunOp; potência do Equipamentos (POWER_INV). Mesmo formato do /api/pg/pr.
#   O POA do SunOp é bem calibrado (PR realista ~0,6-0,8), diferente do PG.
_sunop_pr_cache = {}
_sunop_pr_lock  = threading.Lock()


def _sunop_pr_one(plant_name: str, dia: str):
    """→ (ipoa, n_leituras_poa, [inversores]) de uma planta SunOp no dia."""
    meta = _sunop_meta.get(plant_name) or {}
    epd  = {inv: o.get("EPD") for inv, o in (meta.get("inv_other") or {}).items() if o.get("EPD")}
    stations = meta.get("etm_stations") or {}
    poa_path = next((p["poa"] for p in stations.values() if p.get("poa")), f"{plant_name}.ESTM.POA.IRAD")
    hist  = _sunop_analog_history(list(epd.values()) + [poa_path], f"{dia}T00:00:00", f"{dia}T23:59:59")
    serie = hist.get(poa_path, [])
    ipoa  = 0.0
    for i in range(1, len(serie)):
        try:
            t0 = datetime.fromisoformat(str(serie[i-1][0])[:19]); t1 = datetime.fromisoformat(str(serie[i][0])[:19])
        except Exception:
            continue
        dth = (t1 - t0).total_seconds() / 3600.0
        if 0 < dth <= 1:
            ipoa += (serie[i-1][1] + serie[i][1]) / 2.0 * dth
    ipoa = round(ipoa / 1000.0, 3)
    invs = []
    for inv_name, ep in epd.items():
        eday = max((v for _, v in hist.get(ep, [])), default=None)
        disp = (EQUIP_NAMES.get(plant_name, {}) or {}).get(inv_name)
        pot  = _pot_inv(plant_name, inv_name, disp)
        pr   = round(eday / (ipoa * pot), 3) if (eday and ipoa and pot) else None
        invs.append({"id": inv_name, "nome": disp or inv_name, "nome_api": inv_name,
                     "geracao_kwh": round(eday, 1) if eday else None, "pot_kwp": pot, "pr": pr})
    return ipoa, len(serie), invs


def _sunop_pr_build(dia: str):
    ensure_sunop_meta()
    plantas = [p for p, m in _sunop_meta.items() if m.get("inv_strings")]

    def _one(pn):
        try:    return pn, _sunop_pr_one(pn, dia)
        except Exception: return pn, (None, 0, [])

    summary, detail = [], {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        for pn, (ipoa, npoa, invs) in ex.map(_one, plantas):
            if not invs:
                continue
            invs.sort(key=lambda x: _pv_trk_num(x["nome_api"]))
            prs = sorted(x["pr"] for x in invs if x["pr"] is not None)
            med = prs[len(prs) // 2] if prs else None
            lim = med * (1 - PR_REL_SEVERO) if med is not None else None
            abaixo = 0
            for x in invs:
                x["abaixo"] = bool(x["pr"] is not None and lim is not None and x["pr"] < lim)
                abaixo += 1 if x["abaixo"] else 0
            confiavel = ((ipoa or 0) >= 2.0 and npoa >= 50 and med is not None and med <= 1.05)
            detail[pn] = invs
            summary.append({"usina": USINA_DISPLAY.get(pn, pn), "plant_id": pn, "ipoa": ipoa,
                            "pr_mediana": med, "geracao_kwh": round(sum(x["geracao_kwh"] or 0 for x in invs), 1),
                            "total": len(invs), "abaixo": abaixo,
                            "sem_pot": sum(1 for x in invs if x["pot_kwp"] is None),
                            "cobertura": None, "confiavel": confiavel})
    summary.sort(key=lambda x: (0 if x["confiavel"] else 1, 0 if x["abaixo"] else 1,
                                -(x["abaixo"] or 0), x["usina"]))
    return summary, detail


def _sunop_pr_get(dia: str, force=False):
    agora = time.time()
    with _sunop_pr_lock:
        ent = _sunop_pr_cache.get(dia)
        if not force and ent and (agora - ent["ts"]) < CACHE_TTL:
            return ent["summary"], ent["detail"]
        summary, detail = _sunop_pr_build(dia)
        _sunop_pr_cache[dia] = {"ts": agora, "summary": summary, "detail": detail}
        return summary, detail


@app.route("/api/sunop/pr")
def api_sunop_pr():
    dia = _pr_dia_arg()
    force = flask_request.args.get("force", "0") == "1"
    try:
        summary, _ = _sunop_pr_get(dia, force)
    except Exception as e:
        return jsonify({"error": str(e), "rows": [], "data": dia, "summary": {}}), 500
    return jsonify({"rows": summary, "data": dia,
                    "summary": {"usinas": len(summary), "inversores": sum(r["total"] for r in summary),
                                "abaixo": sum(r["abaixo"] for r in summary),
                                "sem_pot": sum(r["sem_pot"] for r in summary)},
                    "cache_ts": datetime.now().strftime("%H:%M:%S")})


@app.route("/api/sunop/pr/<plant_name>")
def api_sunop_pr_plant(plant_name):
    dia = _pr_dia_arg()
    try:
        _, detail = _sunop_pr_get(dia)
    except Exception as e:
        return jsonify({"error": str(e), "inversores": []}), 500
    return jsonify({"plant_id": plant_name, "data": dia, "inversores": detail.get(plant_name, [])})


@app.route("/api/sunop/trackers/<plant_name>/chart")
def api_sunop_trackers_chart(plant_name):
    ensure_sunop_meta()
    trk = (_sunop_meta.get(plant_name, {}) or {}).get("trackers") or {}
    if not trk:
        return jsonify({"plant": plant_name, "trackers": [], "alvo": None})
    date = (flask_request.args.get("date") or datetime.now().strftime("%Y-%m-%d")).strip()
    cur = _sunop_trk_curvas(plant_name, date)   # mesmo cache do drill-down
    posat, posal = cur["posat"], cur["posal"]

    def _down(serie, alvo_max=180):
        step = max(1, len(serie) // alvo_max)
        return serie[::step]

    def _num(n):
        try: return int(n.split("_")[1])
        except Exception: return 999

    trackers = []
    for n in sorted(trk.keys(), key=_num):
        s = posat.get(n, [])
        if not s:
            continue
        s = _down(s)
        trackers.append({"id": n.replace("TRK_", "Tracker "),
                         "x": [t for t, _ in s], "y": [round(v, 2) for _, v in s]})
    # alvo de referência = série do 1º tracker que tiver POSAL
    alvo = None
    for n in sorted(trk.keys(), key=_num):
        s = posal.get(n, [])
        if s:
            s = _down(s)
            alvo = {"x": [t for t, _ in s], "y": [round(v, 2) for _, v in s]}
            break
    return jsonify({"plant": USINA_DISPLAY.get(plant_name, plant_name), "date": date,
                    "trackers": trackers, "alvo": alvo})


# ── API PV · Trackers (fonte: PV Plataforma) ──────────────────────────────────
#   A API PV (apipv) NÃO expõe posição de tracker; o dado só existe na PV Plataforma
#   (mesma idusina). Endpoints: /v2/usinas/trackers (estado atual: posAg=atual,
#   posAl=alvo, parametros.{alertaPosicao,criticoPosicao}) e /v2/usinas/trackerschart
#   (curva do dia por tracker). Token manual (CAPTCHA+MFA) em plat_token.txt.
PLAT_BASE        = "https://apiplataforma.pvoperation.com"
_PLAT_TOKEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plat_token.txt")
_pv_trk_cache    = {"payload": None, "ts": 0.0}
_pv_trk_plant    = {}   # idusina → {ts, payload}  (análise por usina, reusada no drill-down)


def _plat_token() -> str:
    t = os.environ.get("PLAT_TOKEN", "")
    if t:
        return t.strip()
    try:
        with open(_PLAT_TOKEN_PATH, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def _plat_headers() -> dict:
    return {"accept": "application/json", "origin": "https://plataforma.pvoperation.com",
            "referer": "https://plataforma.pvoperation.com/", "user-agent": "Mozilla/5.0",
            "x-auth-token-update": _plat_token()}


def _pv_trk_num(nome) -> int:
    try:
        return int("".join(c for c in str(nome) if c.isdigit()) or 999)
    except Exception:
        return 999


# ── Tickets de Performance (aba Trackers): ocorrências JÁ acompanhadas ─────────
#   Cruza com o tempo real p/ saber o que já está na planilha vs o que é NOVO.
#   Ignora "Em conformidade". Casa por NOME da usina (sem "(NNN)") + nº do tracker.
_TICKETS_REL = os.path.join("Grid Co_ - 4. O&M", "9.Pós Operação", "3. Análises de Performance",
                            "Tickets de Performance (atualizada).xlsx")
_TICKETS_CANDS = [p for p in [
    os.environ.get("TICKETS_PATH"),
    os.path.join(_OD_ROOT, _TICKETS_REL),
    os.path.join(_OD_ROOT, "Área de Trabalho", _TICKETS_REL),
] if p]
TICKETS_TRK    = {}     # usina_norm → {"nums": {int: status}, "statuses": set}
_tickets_mtime = 0.0
_tickets_lock  = threading.Lock()


def _tk_norm(s) -> str:
    return re.sub(r"\(.*?\)", "", str(s)).strip().lower()


def _tickets_path():
    for p in _TICKETS_CANDS:
        if os.path.exists(p):
            return p
    return None


def load_tickets_trackers():
    """(Re)carrega a aba Trackers da planilha de Tickets (ocorrências não-conformes)."""
    global TICKETS_TRK, _tickets_mtime
    path = _tickets_path()
    if not path:
        print("[AVISO] Tickets de Performance não encontrada (cruzamento desativado)")
        return
    try:
        df = pd.read_excel(path, sheet_name="Trackers", header=3)
        df.columns = [str(c).strip() for c in df.columns]
        c_us = next(c for c in df.columns if c.lower() == "usina")
        c_st = next(c for c in df.columns if c.lower() == "status")
        c_nt = next(c for c in df.columns if "tracker" in c.lower() and "identif" in c.lower())
        m = {}
        for _, row in df.iterrows():
            st = str(row[c_st]).strip()
            if not st or st.lower() in ("nan", "em conformidade"):
                continue
            u = _tk_norm(row[c_us])
            if not u:
                continue
            try:
                n = int(float(row[c_nt]))
            except (TypeError, ValueError):
                n = None
            e = m.setdefault(u, {"nums": {}, "statuses": set()})
            e["statuses"].add(st)
            if n is not None:
                e["nums"][n] = st
        TICKETS_TRK = m
        try:
            _tickets_mtime = os.path.getmtime(path)
        except OSError:
            _tickets_mtime = 0.0
        print(f"[OK] Tickets/Trackers: {len(m)} usinas com ocorrências (fora 'Em conformidade')")
    except Exception as e:
        print(f"[AVISO] Tickets/Trackers não carregado: {e}")


def _tickets_lookup(plant_norm):
    """→ (entrada|None, ambiguo). Casa exato por nome; senão por prefixo (usina agrupada
    na planilha, ex.: 'altair' ⊂ 'altair 1') marcando ambíguo."""
    e = TICKETS_TRK.get(plant_norm)
    if e:
        return e, False
    for k, v in TICKETS_TRK.items():
        if plant_norm == k or plant_norm.startswith(k + " "):
            return v, True
    return None, False


load_tickets_trackers()   # carga inicial


def _pv_trackers_analise(idusina, nome_disp, date=None) -> dict:
    """Analisa os trackers de UMA usina (estado atual da Plataforma): disparidade =
    |posAg - posAl| vs limiares (parametros). Formato compatível c/ a aba Trackers."""
    base = {"plant_id": idusina, "usina": nome_disp, "total": 0, "severos": 0, "leves": 0,
            "fora_media": 0, "parados": 0, "desvios": 0, "atrasos": 0, "sem_alvo": False,
            "pior_disparidade": None, "media_angulo": None, "ultima_leitura": None,
            "trackers": [], "tem_trackers": False}
    try:
        date = date or datetime.now().strftime("%d/%m/%Y")
        r = _http().get(f"{PLAT_BASE}/v2/usinas/trackers", headers=_plat_headers(),
                         params={"idusina": idusina, "date": date}, timeout=30)
        j = r.json() if r.status_code == 200 else {}
    except Exception:
        return base
    lst, atuais = [], []
    for inv in (j.get("dados") or []):
        for t in (inv.get("trackers") or []):
            ul = t.get("ultimaleitura") or {}
            par = t.get("parametros") or {}
            atual = ul.get("posAg"); alvo = ul.get("posAl")
            atual = float(atual) if isinstance(atual, (int, float)) else None
            alvo  = float(alvo)  if isinstance(alvo,  (int, float)) else None
            disp  = abs(atual - alvo) if (atual is not None and alvo is not None) else None
            al_th = par.get("alertaPosicao") or 1.5
            cr_th = par.get("criticoPosicao") or 3
            status = ("desvio" if (disp is not None and disp > cr_th)
                      else "atraso" if (disp is not None and disp > al_th) else "normal")
            if atual is not None:
                atuais.append(atual)
            lst.append({"id": t.get("nome") or f"TRK{len(lst)+1}", "alvo": alvo, "atual": atual,
                        "disparidade": round(disp, 2) if disp is not None else None,
                        "amplitude": None, "max_disp": round(disp, 2) if disp is not None else None,
                        "status": status})
    lst.sort(key=lambda x: _pv_trk_num(x["id"]))
    # Alimenta o acumulador do dia (disparidade + ângulo) e marca os travados: amplitude
    # ~0 enquanto a usina girou → "parado" sobrepõe o status instantâneo (que perderia um
    # tracker congelado no meio do dia, quando o sol cruza o ângulo em que ele travou).
    _ult = (j.get("ultimaLeitura") or None)
    _trk_accum_feed(idusina, _ult, [(t["id"], t["disparidade"], t["atual"]) for t in lst])
    parados_set = _trk_accum_parados(idusina)
    for t in lst:
        if str(t["id"]) in parados_set:
            t["status"] = "parado"
    # Cruzamento com a planilha de Tickets (nome da usina + nº do tracker)
    tick, ambiguo = _tickets_lookup(_tk_norm(nome_disp))
    nums = (tick or {}).get("nums", {})
    novos = acomp = normalizados = 0
    for t in lst:
        ts = nums.get(_pv_trk_num(t["id"]))
        t["na_planilha"] = ts is not None
        t["ticket_status"] = ts
        # Normalizado = está NORMAL no tempo real mas a planilha lista como problema
        t["normalizado"] = bool(t["na_planilha"] and t["status"] == "normal")
        if t["normalizado"]:
            normalizados += 1
        if t["status"] in ("desvio", "atraso", "parado"):  # anômalo (inclui travado o dia todo)
            if t["na_planilha"]:
                acomp += 1
            else:
                novos += 1
    desv = sum(1 for t in lst if t["status"] == "desvio")
    atr  = sum(1 for t in lst if t["status"] == "atraso")
    par  = sum(1 for t in lst if t["status"] == "parado")
    pior = max((t["disparidade"] for t in lst if t["disparidade"] is not None), default=None)
    base.update({"total": len(lst), "tem_trackers": bool(lst),
                 "severos": desv + par, "leves": atr, "desvios": desv, "atrasos": atr, "parados": par,
                 "sem_alvo": all(t["alvo"] is None for t in lst) if lst else False,
                 "pior_disparidade": round(pior, 2) if pior is not None else None,
                 "desvio_medio": _trk_accum_desvio(idusina),
                 "media_angulo": round(sum(atuais) / len(atuais), 1) if atuais else None,
                 "ultima_leitura": _ult, "trackers": lst,
                 "tem_ticket": tick is not None, "ambiguo": ambiguo,
                 "novos": novos, "acompanhados": acomp, "normalizados": normalizados})
    return base


def _build_pv_trk_payload():
    plants = get_plants(get_token())
    agora = time.time()
    alvo_plants = [p for p in plants if (not FULL_OM or p["nome"].strip() in FULL_OM)]
    rows = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_pv_trackers_analise, p["id"], nome_usina(p["id"], p["nome"])): p
                for p in alvo_plants}
        for f in as_completed(futs):
            try:
                r = f.result()
                if r.get("tem_trackers"):
                    _pv_trk_plant[r["plant_id"]] = {"ts": agora, "payload": r}
                    rows.append({k: r[k] for k in ("plant_id", "usina", "total", "severos", "leves",
                                 "fora_media", "pior_disparidade", "desvio_medio", "ultima_leitura",
                                 "media_angulo", "novos", "acompanhados", "normalizados",
                                 "tem_ticket", "ambiguo")})
            except Exception:
                pass
    # ordena: mais NOVOS (fora da planilha) no topo, depois severidade
    rows.sort(key=lambda x: (-(x.get("novos") or 0), -(x["severos"] * 10 + x["leves"]), x["usina"]))
    return {"rows": rows,
            "summary": {"usinas": len(rows), "trackers": sum(r["total"] for r in rows),
                        "severos": sum(r["severos"] for r in rows),
                        "leves": sum(r["leves"] for r in rows),
                        "novos": sum(r.get("novos") or 0 for r in rows),
                        "acompanhados": sum(r.get("acompanhados") or 0 for r in rows),
                        "normalizados": sum(r.get("normalizados") or 0 for r in rows)},
            "cache_ts": datetime.now().strftime("%H:%M:%S")}


@app.route("/api/pv/trackers")
def api_pv_trackers():
    """Overview de trackers das usinas API PV (Full O&M). Fonte: PV Plataforma."""
    force = flask_request.args.get("force", "0") == "1"
    if not _plat_token():
        return jsonify({"rows": [], "summary": {"usinas": 0, "trackers": 0, "severos": 0, "leves": 0},
                        "sem_token": True, "cache_ts": datetime.now().strftime("%H:%M:%S")})
    try:
        return jsonify(_swr(_pv_trk_cache, _build_pv_trk_payload, force))
    except Exception as e:
        return jsonify({"rows": [], "summary": {"usinas": 0, "trackers": 0, "severos": 0, "leves": 0},
                        "erro": f"API PV indisponível: {e}"})


@app.route("/api/pv/trackers/alertas")
def api_pv_trackers_alertas():
    """Trackers anômalos no tempo real que NÃO estão na planilha de Tickets (= NOVOS).
    Usa o cache do overview; chame /api/pv/trackers antes (ou force=1)."""
    if not _pv_trk_cache["payload"]:
        api_pv_trackers()                       # popula o cache
    alertas = []
    for idusina, ent in _pv_trk_plant.items():
        p = ent["payload"]
        for t in p.get("trackers", []):
            if t["status"] in ("desvio", "atraso") and not t.get("na_planilha"):
                alertas.append({"plant_id": idusina, "usina": p["usina"], "tracker": t["id"],
                                "status": t["status"], "disparidade": t["disparidade"],
                                "atual": t["atual"], "alvo": t["alvo"], "ambiguo": p.get("ambiguo")})
    alertas.sort(key=lambda a: -(a["disparidade"] or 0))
    return jsonify({"total": len(alertas), "alertas": alertas,
                    "cache_ts": datetime.now().strftime("%H:%M:%S")})


@app.route("/api/pv/trackers/<int:idusina>")
def api_pv_trackers_plant(idusina):
    ent = _pv_trk_plant.get(idusina)
    if ent and (time.time() - ent["ts"]) < CACHE_TTL:
        return jsonify(ent["payload"])
    try:
        nome = next((nome_usina(p["id"], p["nome"]) for p in get_plants(get_token())
                     if p["id"] == idusina), str(idusina))
    except Exception:
        nome = str(idusina)
    r = _pv_trackers_analise(idusina, nome)
    _pv_trk_plant[idusina] = {"ts": time.time(), "payload": r}
    return jsonify(r)


@app.route("/api/pv/trackers/<int:idusina>/chart")
def api_pv_trackers_chart(idusina):
    """Curva diária de posição por tracker (PV Plataforma /v2/usinas/trackerschart)."""
    data = (flask_request.args.get("date") or datetime.now().strftime("%d/%m/%Y")).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", data):     # aceita YYYY-MM-DD do <input type=date>
        data = datetime.strptime(data, "%Y-%m-%d").strftime("%d/%m/%Y")
    try:
        r = _http().get(f"{PLAT_BASE}/v2/usinas/trackerschart", headers=_plat_headers(),
                         params={"idusina": idusina, "dataleitura": data}, timeout=90)
        g = (r.json() or {}).get("grafico") or {}
    except Exception:
        g = {}

    def _down(serie, mx=180):
        step = max(1, len(serie) // mx)
        return serie[::step]

    trackers = []
    for nome in sorted(g.keys(), key=_pv_trk_num):
        s = _down(g[nome] or [])
        trackers.append({"id": nome, "x": [p.get("x") for p in s],
                         "y": [round(p.get("y"), 2) if isinstance(p.get("y"), (int, float)) else None
                               for p in s]})
    return jsonify({"plant": idusina, "date": data, "trackers": trackers, "alvo": None})


@app.route("/api/pv/trackers/token", methods=["POST", "OPTIONS"])
def api_pv_trackers_token():
    """Salva o token da PV Plataforma (usado pelo bookmarklet de 1 clique).
    CORS liberado: o bookmarklet roda na origem plataforma.pvoperation.com."""
    if flask_request.method == "OPTIONS":      # preflight do navegador
        resp = app.make_response(("", 204))
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp
    body = flask_request.get_json(force=True, silent=True) or {}
    tok = (body.get("token") or "").strip()
    if tok.count(".") != 2:
        r = jsonify({"ok": False, "error": "token inválido"}); r.headers["Access-Control-Allow-Origin"] = "*"
        return r, 400
    try:
        with open(_PLAT_TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(tok)
        _pv_trk_cache["payload"] = None   # invalida overview p/ recarregar com token novo
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    exp = None
    try:
        import base64
        pl = tok.split(".")[1]; pl += "=" * (-len(pl) % 4)
        exp = json.loads(base64.urlsafe_b64decode(pl)).get("exp")
    except Exception:
        pass
    r = jsonify({"ok": True, "exp": exp}); r.headers["Access-Control-Allow-Origin"] = "*"
    return r


# ── Tracker Watch ─────────────────────────────────────────────────────────────
try:
    import tracker_watch as _tw
    _TRACKER_WATCH_OK = True
except Exception:
    _TRACKER_WATCH_OK = False


@app.route("/api/tracker-watch")
def api_tracker_watch():
    if not _TRACKER_WATCH_OK:
        return jsonify({"error": "tracker_watch não disponível", "active": {}, "history_recent": []}), 500
    try:
        return jsonify(_tw.get_issues_json())
    except Exception as e:
        return jsonify({"error": str(e), "active": {}, "history_recent": []}), 500


@app.route("/api/tracker-watch/update", methods=["POST"])
def api_tracker_watch_update():
    """Atualiza ao vivo (SunOp + PostgreSQL) e só responde quando termina,
    devolvendo já os dados frescos + resumo da rodada."""
    if not _TRACKER_WATCH_OK:
        return jsonify({"error": "tracker_watch não disponível"}), 500
    try:
        stats = _tw.atualizar(verbose=False, fonte="ambas")
        return jsonify({"ok": True, "stats": stats, "data": _tw.get_issues_json()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/tracker-watch/action", methods=["POST"])
def api_tracker_watch_action():
    """Ações manuais: resolve, note."""
    if not _TRACKER_WATCH_OK:
        return jsonify({"error": "tracker_watch não disponível"}), 500
    body   = flask_request.get_json(force=True) or {}
    action = body.get("action", "")
    plant  = body.get("plant", "")
    tracker = body.get("tracker", "")
    if not plant or not tracker:
        return jsonify({"error": "plant e tracker são obrigatórios"}), 400
    if action == "resolve":
        _tw.resolver(plant, tracker, body.get("obs", ""))
    elif action == "note":
        _tw.anotar(plant, tracker, body.get("obs", ""), body.get("os_fracttal", ""), body.get("supervisor", ""))
    elif action == "add":
        _tw.adicionar_manual(plant, tracker, body.get("tipo", "parado"), body.get("obs", ""), body.get("supervisor", ""))
    else:
        return jsonify({"error": f"action '{action}' desconhecida"}), 400
    return jsonify({"ok": True})


# ── SunOp ETM: ACUMULADOR DIÁRIO (integra o IRAD instantâneo ao longo do dia) ──
#   A API SunOp só expõe o último valor (W/m²), sem curva histórica acessível.
#   Solução: amostrar periodicamente e integrar pela área (trapézio) usando o
#   timestamp do PRÓPRIO sensor → kWh/m² acumulado no dia. Robustez:
#     • sensor travado (ts não avança) → não integra (não infla);
#     • janela > SUNOP_ACCUM_MAX_GAP_H (servidor caiu) → intervalo descartado;
#     • vira o dia → zera os acumuladores.
SUNOP_ACCUM_PATH      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sunop_etm_accum.json")
SUNOP_SAMPLE_INTERVAL = int(os.environ.get("SUNOP_SAMPLE_INTERVAL", "300"))  # s entre amostras
SUNOP_ACCUM_MAX_GAP_H = 0.5    # h: intervalo máx entre leituras p/ integrar (descarta gaps)
_sunop_accum      = {"date": None, "stations": {}}
_sunop_accum_lock = threading.Lock()


def _load_sunop_accum():
    global _sunop_accum
    try:
        with open(SUNOP_ACCUM_PATH, encoding="utf-8") as f:
            _sunop_accum = json.load(f)
    except Exception:
        _sunop_accum = {"date": None, "stations": {}}
    _sunop_accum.setdefault("date", None)
    _sunop_accum.setdefault("stations", {})


def _save_sunop_accum():
    tmp = SUNOP_ACCUM_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_sunop_accum, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SUNOP_ACCUM_PATH)
    except Exception as e:
        print(f"[SUNOP] erro salvando acumulador: {e}")


def _sunop_etm_snapshot() -> dict:
    """Lê o último valor de POA/GHI/POA_R de todas as estações → {key: {poa,ghi,poari,ts}}."""
    ensure_sunop_meta()
    station_paths, all_paths = {}, []
    for plant, meta in _sunop_meta.items():
        stations = meta.get("etm_stations") or {"ESTM": {
            "poa": f"{plant}.ESTM.POA.IRAD", "ghi": f"{plant}.ESTM.GHI.IRAD",
            "poari": f"{plant}.ESTM.POA_R.IRAD"}}
        for station, paths in stations.items():
            station_paths[f"{plant}|{station}"] = paths
            all_paths.extend(paths.values())
    by_path = {}
    H = _sunop_headers()
    for i in range(0, len(all_paths), 500):
        batch = all_paths[i:i + 500]
        try:
            r = _http().post(f"{SUNOP_DATA}/v2/last_values", headers=H,
                              json={"pathnames": batch}, timeout=20)
            if r.status_code == 200:
                for v in (r.json() or []):
                    by_path[v.get("pathname")] = v
        except Exception:
            pass

    def _v(path):
        v = by_path.get(path, {}).get("value")
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return None
        return _etm_clamp(fv)   # >=0, teto 1600

    out = {}
    for key, paths in station_paths.items():
        ts = max((by_path.get(p, {}).get("timestamp", "") for p in paths.values()), default="")
        out[key] = {"poa": _v(paths.get("poa", "")), "ghi": _v(paths.get("ghi", "")),
                    "poari": _v(paths.get("poari", "")), "ts": ts or None}
    return out


def _sunop_accum_integrate():
    """Uma passada: amostra todas as estações e integra no acumulador do dia."""
    snap = _sunop_etm_snapshot()
    hoje = datetime.now().strftime("%Y-%m-%d")
    n_int = 0
    with _sunop_accum_lock:
        if _sunop_accum.get("date") != hoje:
            _sunop_accum["date"] = hoje
            _sunop_accum["stations"] = {}
        stations = _sunop_accum["stations"]
        for key, cur in snap.items():
            st = stations.setdefault(key, {"poa_kwh": 0.0, "ghi_kwh": 0.0, "poari_kwh": 0.0,
                                           "last_ts": None, "last_poa": None,
                                           "last_ghi": None, "last_poari": None, "samples": 0})
            cts = cur["ts"]
            if not cts or cts == st["last_ts"]:
                continue   # sem leitura nova → não integra
            if st["last_ts"] is not None:
                try:
                    dt_h = (datetime.fromisoformat(cts) - datetime.fromisoformat(st["last_ts"])).total_seconds() / 3600.0
                except Exception:
                    dt_h = 0.0
                if 0 < dt_h <= SUNOP_ACCUM_MAX_GAP_H:
                    for m, acc in (("poa", "poa_kwh"), ("ghi", "ghi_kwh"), ("poari", "poari_kwh")):
                        prev, now_v = st[f"last_{m}"], cur[m]
                        if prev is not None and now_v is not None:
                            st[acc] += (prev + now_v) / 2.0 * dt_h / 1000.0   # W/m²·h ÷ 1000 = kWh/m²
                    n_int += 1
            st["last_ts"]  = cts
            st["last_poa"] = cur["poa"]; st["last_ghi"] = cur["ghi"]; st["last_poari"] = cur["poari"]
            st["samples"] += 1
        _save_sunop_accum()
    return n_int


def _sunop_accum_get(plant_name: str, station: str) -> dict:
    """Acumulado do dia p/ uma estação (key = 'PLANT|ESTM…'); {} se vazio/outro dia."""
    with _sunop_accum_lock:
        if _sunop_accum.get("date") != datetime.now().strftime("%Y-%m-%d"):
            return {}
        st = _sunop_accum["stations"].get(f"{plant_name}|{station}")
        if not st:
            return {}
        return {"poa_dia": round(st["poa_kwh"], 3), "ghi_dia": round(st["ghi_kwh"], 3),
                "poari_dia": round(st["poari_kwh"], 3), "amostras": st["samples"],
                "acum_ts": st.get("last_ts")}


def _sunop_accum_loop():
    """Thread daemon: amostra e integra a cada SUNOP_SAMPLE_INTERVAL segundos."""
    _load_sunop_accum()
    print(f"[SUNOP] acumulador ETM iniciado (amostra a cada {SUNOP_SAMPLE_INTERVAL}s)")
    while True:
        try:
            n = _sunop_accum_integrate()
            print(f"[SUNOP] acumulador: {n} estações integradas")
        except Exception as e:
            print(f"[SUNOP] acumulador erro: {e}")
        time.sleep(SUNOP_SAMPLE_INTERVAL)


# ── SolarEdge: lista de usinas ─────────────────────────────────────────────────
def se_sites() -> list:
    """searchSites → lista de {id, nome, timezone, inv, optimizers, status}."""
    body = {
        "pageRequest": {"sitesInPage": 200, "pageNum": 1,
                        "sortRequest": {"sortColumnType": "maxImpact", "sortOrder": "DESC"}},
        "locationFilter": {"countries": [], "states": [], "city": "", "address": "", "zip": ""},
        "peakPowerFilter": {"min": 0, "max": 9999999},
        "maxImpactFilter": {"min": 0, "max": 9},
        "installationDateFilter": {}, "statusFilter": [], "serialNumber": "",
        "siteNameFilter": "", "accountNameFilter": [], "groupFilter": "",
        "favoriteFilter": False, "devicesFilter": {}, "demoSitesFilter": False,
        "siteMagnitudeFilter": None, "geoBoundingBox": None,
    }
    try:
        r = _http().post(f"{SE_BASE}/services/sitelist/searchSites",
                          headers=_se_headers(),
                          params={"v": int(time.time() * 1000)}, json=body, timeout=30)
        if r.status_code != 200:
            return []
        page = r.json().get("page", [])
    except Exception:
        return []
    return [{
        "id":       s["solarFieldId"],
        "nome":     s.get("name"),
        "timezone": s.get("timeZone"),
        "inv":      s.get("inverterCount"),
        "status":   s.get("status"),
    } for s in page]


# ── SolarEdge: dispositivos de um site (inversores + strings) ──────────────────
def se_devices(site_id) -> list:
    try:
        r = _http().get(f"{SE_BASE}/services/cni/ui-api/pages/site/analysis/custom/site/{site_id}/devices",
                         headers=_se_headers(), timeout=30)
        if r.status_code != 200:
            return []
        return r.json()
    except Exception:
        return []


def _se_day_range(tzname):
    """Intervalo do dia local da usina em ISO-Z (from=meia-noite local, to=agora)."""
    tz = None
    if ZoneInfo and tzname:
        try:
            tz = ZoneInfo(tzname)
        except Exception:
            tz = None
    now_local = datetime.now(tz) if tz else datetime.now(timezone.utc)
    start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    frm = start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    to  = now_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.999Z")
    return frm, to


def se_string_power(site_id, uuids, tzname) -> dict:
    """generate-chart em lotes → {uuid: ultima_potencia_W ou None}, e timestamp máx."""
    frm, to = _se_day_range(tzname)
    out, ts_max = {}, ""
    H = _se_headers()
    for i in range(0, len(uuids), 50):
        batch = uuids[i:i + 50]
        payload = {
            "reportPeriod": {"from": frm, "to": to},
            "datasources": [{
                "metrics": [
                    {"metricType": "calculation", "calculationCategoryUri": "optimizer_calculations",
                     "periodType": "FIVE_MINUTES", "calculationMetricUri": "energy"},
                    {"metricType": "calculation", "calculationCategoryUri": "optimizer_calculations",
                     "periodType": "FIVE_MINUTES", "calculationMetricUri": "power"},
                ],
                "datasourcePopulation": {"populationType": "deviceList", "siteId": int(site_id),
                                          "deviceType": "STRING", "deviceSerials": batch},
                "alignmentGranularity": "QUARTER_HOUR",
            }],
        }
        try:
            r = _http().post(
                f"{SE_BASE}/services/cni/ui-api/pages/site/analysis/custom/site/{site_id}/generate-chart",
                headers=H, json=payload, timeout=40)
            if r.status_code != 200:
                continue
            d = r.json()
        except Exception:
            continue
        metas = d.get("meta", {}).get("datasetsMeta", [])
        data  = d.get("data", [])
        for j, meta in enumerate(metas):
            uuid = meta.get("reportObject", {}).get("entityId")
            if j >= len(data):
                continue
            last_p = None
            for row in data[j]:        # row = [ts, energia_Wh, potencia_W]
                if row[2] is not None:
                    last_p = row[2]
                    if row[0] > ts_max:
                        ts_max = row[0]
            out[uuid] = last_p
    return out, ts_max


# ── SolarEdge: processa uma usina (visão geral) ────────────────────────────────
def process_site_solaredge(site: dict) -> dict:
    sid  = site["id"]
    nome = site["nome"]                              # supervisório (chave p/ ESPERADO_INV)
    nome_disp = USINA_DISPLAY.get(nome, nome)        # nome de exibição (BD_Performance)
    base = {
        "usina": nome_disp, "plant_id": sid,
        "qtd_inversores": None, "strings_ativas": None,
        "inv_esp": site.get("inv"), "str_esp": None, "diferenca": None,
        "temp_media": None, "ultima_leitura": None,
        "sem_dados": True, "falha_comunicacao": False,
    }
    devs = se_devices(sid)
    if not devs:
        return base
    strings = [d for d in devs if d.get("deviceType") == "STRING"]
    invs    = [d for d in devs if d.get("deviceType") == "INVERTER"]
    if not strings:
        return base
    uuids = [s["deviceSerial"] for s in strings]
    power, ts_max = se_string_power(sid, uuids, site.get("timezone"))
    if not power:
        return base
    ativas = sum(1 for u in uuids if (power.get(u) is not None and power[u] > SE_STRING_MIN_W))
    total  = len(strings)
    # Esperadas vêm do BD_Performance (ESPERADO_INV); fallback = total físico
    esp_map = ESPERADO_INV.get(nome, {})
    str_esp = sum(esp_map.values()) if esp_map else total
    return {
        "usina": nome_disp, "plant_id": sid,
        "qtd_inversores": len(invs),
        "strings_ativas": ativas,
        "inv_esp": site.get("inv"),
        "str_esp": str_esp,
        "diferenca": ativas - str_esp,
        "temp_media": None,
        "ultima_leitura": ts_max or None,
        "sem_dados": False,
        "falha_comunicacao": False,
    }


def fetch_all_solaredge() -> list:
    sites = se_sites()
    rows = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(process_site_solaredge, s): s for s in sites}
        for f in as_completed(futs):
            rows.append(f.result())
    return sorted(rows, key=lambda x: (severidade(x), x["usina"]))


def _build_se_payload():
    rows = fetch_all_solaredge()
    rows_com = [r for r in rows if not r.get("sem_dados")]
    return {
        "rows": rows,
        "summary": {
            "total_usinas":    len(rows),
            "total_strings":   sum(r["strings_ativas"] for r in rows_com),
            "alertas_strings": sum(1 for r in rows_com if r["strings_ativas"] == 0),
            "alertas_temp":    0,
            "alertas_comm":    sum(1 for r in rows if r.get("sem_dados") or r.get("falha_comunicacao")),
        },
        "cache_ts": datetime.now().strftime("%H:%M:%S"),
    }


@app.route("/api/solaredge/data")
def api_solaredge_data():
    force = flask_request.args.get("force", "0") == "1"
    return jsonify(_swr(_se_cache, _build_se_payload, force))


@app.route("/api/solaredge/plant/<int:site_id>")
def api_solaredge_plant(site_id):
    # Busca timezone e nome do site (da lista, em cache curto)
    site = next((s for s in se_sites() if int(s["id"]) == site_id), None)
    tzname    = site.get("timezone") if site else None
    site_nome = site.get("nome") if site else None
    esp_inv_map    = ESPERADO_INV.get(site_nome, {})
    equip_disp_map = EQUIP_NAMES.get(site_nome, {})

    devs = se_devices(site_id)
    if not devs:
        return jsonify({"plant_id": site_id, "inversores": []})

    invs    = [d for d in devs if d.get("deviceType") == "INVERTER"]
    strings = [d for d in devs if d.get("deviceType") == "STRING"]
    inv_nome = {d["deviceSerial"]: d.get("deviceName", d["deviceSerial"]) for d in invs}

    uuids = [s["deviceSerial"] for s in strings]
    power, _ = se_string_power(site_id, uuids, tzname)

    # Agrupa strings por inversor (partOfSerial / pluggedTo)
    por_inv = {}
    for s in strings:
        parent = s.get("partOfSerial") or s.get("pluggedTo") or "—"
        por_inv.setdefault(parent, []).append(s)

    def _str_num(name):
        # "String 25.3" → (25, 3) para ordenar
        try:
            a, b = name.replace("String", "").strip().split(".")
            return (int(a), int(b))
        except Exception:
            return (999, 999)

    inversores = []
    for parent, slist in por_inv.items():
        slist.sort(key=lambda s: _str_num(s.get("deviceName", "")))
        chips, ativas = [], 0
        ts_inv = None
        for s in slist:
            p = power.get(s["deviceSerial"])
            ativa = p is not None and p > SE_STRING_MIN_W
            if ativa:
                ativas += 1
            chips.append({"id": s.get("deviceName", "").replace("String", "").strip(),
                          "corrente": p if p is not None else 0,
                          "unidade": "W", "ativa": ativa})
        total = len(slist)
        desligado = ativas == 0
        nome_inv = inv_nome.get(parent, parent)            # nome SolarEdge (ex.: "Inverter 1")
        str_esp_inv = esp_inv_map.get(nome_inv)            # esperadas da planilha
        if str_esp_inv is None:
            str_esp_inv = total                            # fallback = total físico
        nome_disp = equip_disp_map.get(nome_inv, nome_inv) # nome de exibição (BD_Performance)
        inversores.append({
            "id": parent, "nome": nome_disp, "nome_api": nome_inv,
            "ultima_leitura": None, "falha_comunicacao": False, "desligado": desligado,
            "strings_ativas": ativas, "total_strings": total,
            "str_esp": str_esp_inv, "diferenca": ativas - str_esp_inv,
            "temp": None, "eday": None, "strings": chips,
        })
    def _inv_num(name):
        m = re.search(r"(\d+)", name or "")
        return int(m.group(1)) if m else 999
    inversores.sort(key=lambda x: _inv_num(x["nome"]))
    return jsonify({"plant_id": site_id, "inversores": inversores})


# ── SolarEdge: PR por inversor (render-chart MONTH) ────────────────────────────
#   UM render-chart por site já traz, junto, a energia diária de cada inversor (Wh)
#   E a série "Global Irradiance" (W/m²) — sem precisar do generate-chart (que 500a
#   no nível INVERTER). Para a data pedida pega-se o ponto diário (MONTH = 1 pt/dia,
#   janela dos últimos ~31 dias, valor FECHADO de dias passados).
#     IPOA (kWh/m²) = irr_diário × 0,25 / 1000   (validado: soma das 96 amostras 15min
#                     do DAY == valor diário do MONTH).
#     geração_inv (kWh) = ponto_diário (Wh) / 1000.
#     PR_inv = geração ÷ (IPOA × potência_inv);  potência via Equipamentos (POWER_INV).
#   Xavantina 2 e Colíder 2 não têm sensor → herdam a irradiância da co-localizada
#   (Xavantina 1 / Colíder 1) pelo SE_IRR_MIRROR.
SE_IRR_MIRROR = {"UFV Xavantina 2": "UFV Xavantina 1",
                 "UFV Colider 2":   "UFV Colider 1"}
_SE_SERIAL_RE = re.compile(r"\(([^)]+)\)\s*$")
_se_pr_cache  = {}      # "YYYY-MM-DD" → {ts, summary, detail}
_se_pr_lock   = threading.Lock()


def _se_render_month(sid, serials):
    """render-chart MONTH → highcharts.series (energia/inversor em Wh + Global Irradiance)."""
    body = {"chartPeriodScale": "MONTH", "intervalIndex": 0,
            "chartUri": "inverter-energy-generation",
            "chartPopulation": {"siteId": int(sid), "populationType": "deviceList",
                                "deviceType": "INVERTER", "deviceSerials": serials}}
    try:
        r = _http().post(
            f"{SE_BASE}/services/cni/ui-api/pages/site/analysis/execute/site/{sid}/render-chart",
            headers=_se_headers(), json=body, timeout=45)
        if r.status_code != 200:
            return None
        return r.json().get("highcharts", {}).get("series", [])
    except Exception:
        return None


def _ts_local_date(ms, tzname) -> str:
    try:
        tz = ZoneInfo(tzname) if (ZoneInfo and tzname) else timezone.utc
    except Exception:
        tz = timezone.utc
    return datetime.fromtimestamp(ms / 1000, tz).date().isoformat()


def _se_parse_month(series, tzname, dia):
    """→ ({serial: geração_kWh_no_dia}, irr_valor_diário|None) para a data 'dia'."""
    ger, irr = {}, None
    for s in (series or []):
        nm   = s.get("name", "")
        data = s.get("data", []) or []
        if "Irradiance" in nm:
            for p in data:
                if len(p) > 1 and p[1] is not None and _ts_local_date(p[0], tzname) == dia:
                    irr = float(p[1]); break
        elif nm.startswith("Energy Produced"):
            m = _SE_SERIAL_RE.search(nm)
            serial = m.group(1) if m else nm
            for p in data:
                if len(p) > 1 and p[1] is not None and _ts_local_date(p[0], tzname) == dia:
                    ger[serial] = float(p[1]) / 1000.0; break
    return ger, irr


def _se_pr_build(dia: str):
    sites = se_sites()

    def _one(site):
        sid, nome, tz = site["id"], site.get("nome"), site.get("timezone")
        devs    = se_devices(sid)
        invs    = [d for d in devs if d.get("deviceType") == "INVERTER"]
        serials = [d["deviceSerial"] for d in invs]
        ser2dev = {d["deviceSerial"]: d.get("deviceName", d["deviceSerial"]) for d in invs}
        ger, irr = _se_parse_month(_se_render_month(sid, serials), tz, dia)
        return nome, {"sid": sid, "sup": nome, "ser2dev": ser2dev, "ger": ger, "irr": irr}

    raw = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for nome, info in ex.map(_one, sites):
            raw[nome] = info

    # irradiância espelhada para os sites sem sensor próprio
    for nome, info in raw.items():
        if info["irr"] is None and nome in SE_IRR_MIRROR:
            src = raw.get(SE_IRR_MIRROR[nome])
            if src:
                info["irr"] = src["irr"]

    summary, detail = [], {}
    for nome, info in raw.items():
        sup  = info["sup"]
        ipoa = round(info["irr"] * 0.25 / 1000.0, 3) if info["irr"] else None
        invs = []
        for serial, kwh in info["ger"].items():
            dev  = info["ser2dev"].get(serial, serial)
            disp = (EQUIP_NAMES.get(sup, {}) or {}).get(dev, dev)
            pot  = _pot_inv(sup, dev, disp)
            pr   = round(kwh / (ipoa * pot), 3) if (kwh is not None and ipoa and pot) else None
            invs.append({"id": serial, "nome": disp, "nome_api": dev,
                         "geracao_kwh": round(kwh, 1) if kwh is not None else None,
                         "pot_kwp": pot, "pr": pr})
        invs.sort(key=lambda x: _pv_trk_num(x["nome_api"]))
        prs = sorted(x["pr"] for x in invs if x["pr"] is not None)
        med = prs[len(prs) // 2] if prs else None
        lim = med * (1 - PR_REL_SEVERO) if med is not None else None
        abaixo = 0
        for x in invs:
            x["abaixo"] = bool(x["pr"] is not None and lim is not None and x["pr"] < lim)
            abaixo += 1 if x["abaixo"] else 0
        # confiável p/ PR ABSOLUTO: tem irradiância (própria/espelhada) plausível e
        # mediana fisicamente coerente (≤1,05); senão vale só a comparação relativa.
        confiavel = bool(ipoa and ipoa >= 2.0 and med is not None and med <= 1.05)
        detail[info["sid"]] = invs
        summary.append({
            "usina": USINA_DISPLAY.get(sup, sup), "plant_id": info["sid"],
            "ipoa": ipoa, "pr_mediana": med,
            "geracao_kwh": round(sum(x["geracao_kwh"] or 0 for x in invs), 1),
            "total": len(invs), "abaixo": abaixo,
            "sem_pot": sum(1 for x in invs if x["pot_kwp"] is None),
            "cobertura": None, "confiavel": confiavel,
        })
    summary.sort(key=lambda x: (0 if x["confiavel"] else 1,
                                0 if x["abaixo"] else 1, -(x["abaixo"] or 0), x["usina"]))
    return summary, detail


def _se_pr_get(dia: str, force=False):
    agora = time.time()
    with _se_pr_lock:
        ent = _se_pr_cache.get(dia)
        if not force and ent and (agora - ent["ts"]) < CACHE_TTL:
            return ent["summary"], ent["detail"]
        summary, detail = _se_pr_build(dia)
        _se_pr_cache[dia] = {"ts": agora, "summary": summary, "detail": detail}
        return summary, detail


@app.route("/api/solaredge/pr")
def api_solaredge_pr():
    """Overview de PR por usina (SolarEdge/RenoGrid). Cada usina abre em PR por inversor."""
    dia = _pr_dia_arg()
    force = flask_request.args.get("force", "0") == "1"
    try:
        summary, _ = _se_pr_get(dia, force)
    except Exception as e:
        return jsonify({"error": str(e), "rows": [], "data": dia, "summary": {}}), 500
    return jsonify({"rows": summary, "data": dia,
                    "summary": {"usinas": len(summary),
                                "inversores": sum(r["total"] for r in summary),
                                "abaixo": sum(r["abaixo"] for r in summary),
                                "sem_pot": sum(r["sem_pot"] for r in summary)},
                    "cache_ts": datetime.now().strftime("%H:%M:%S")})


@app.route("/api/solaredge/pr/<int:site_id>")
def api_solaredge_pr_plant(site_id):
    dia = _pr_dia_arg()
    try:
        _, detail = _se_pr_get(dia)
    except Exception as e:
        return jsonify({"error": str(e), "inversores": []}), 500
    return jsonify({"plant_id": site_id, "data": dia, "inversores": detail.get(site_id, [])})


# ── PostgreSQL (powerplants) ───────────────────────────────────────────────────
PG_HOST = os.environ.get("PG_HOST", "")
PG_PORT = int(os.environ.get("PG_PORT", "5432"))
PG_DB   = os.environ.get("PG_DB", "powerplants")
PG_USER = os.environ.get("PG_USER", "")
PG_PASS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pg_password.txt")
PG_STRING_THRESHOLD = 0.5
_pg_cache     = {"summary": None, "detail": {}, "ts": 0.0}  # snapshot único: resumo + drill-down
_pg_lock      = threading.Lock()
_pg_etm_cache = {"payload": None, "ts": 0.0}


def _pg_password() -> str:
    pw = os.environ.get("PG_PASSWORD", "")
    if pw:
        return pw
    try:
        with open(PG_PASS_PATH, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def _pg_conn():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 não instalado")
    return psycopg2.connect(host=PG_HOST, port=PG_PORT, dbname=PG_DB,
                            user=PG_USER, password=_pg_password(), connect_timeout=10)


# ── PG: snapshot único (resumo + drill-down vêm da MESMA leitura) ──────────────
def _pg_build_snapshot():
    """Uma query → estado consistente: total da usina = soma dos inversores."""
    sql = """
      WITH latest AS (
        SELECT DISTINCT ON (s.power_plant_id, s.device_id, s.string_number)
               s.power_plant_id, p.name AS pname, s.device_id, s.device_name,
               s.string_number, s.string_current, s.timestamp
        FROM dbt.stg_inverter_string_data s
        LEFT JOIN public.tb_power_plants p ON p.id = s.power_plant_id
        ORDER BY s.power_plant_id, s.device_id, s.string_number, s.timestamp DESC
      )
      SELECT power_plant_id, pname, device_id, device_name, string_number, string_current, timestamp
      FROM latest ORDER BY power_plant_id, device_id, string_number;
    """
    conn = _pg_conn(); cur = conn.cursor(); cur.execute(sql); recs = cur.fetchall(); conn.close()

    plants = {}
    for pid, pname, dev_id, dev_name, snum, curr, ts in recs:
        p   = plants.setdefault(pid, {"sup": (pname or f"Usina {pid}").strip(), "invs": {}, "ts": None})
        inv = p["invs"].setdefault(dev_id, {"dev": dev_name or f"INV {dev_id}", "strings": [], "ts": None})
        c = float(curr) if curr is not None else 0.0
        inv["strings"].append({"id": str(snum), "corrente": c, "ativa": c > PG_STRING_THRESHOLD})
        if ts:
            if inv["ts"] is None or ts > inv["ts"]: inv["ts"] = ts
            if p["ts"]   is None or ts > p["ts"]:   p["ts"]   = ts

    summary, detail = [], {}
    for pid, p in plants.items():
        sup        = p["sup"]
        esp_map    = ESPERADO_INV.get(sup, {})
        equip_disp = EQUIP_NAMES.get(sup, {})
        inv_list, tot_ativas, tot_esp = [], 0, 0
        for dev_id in sorted(p["invs"]):
            inv = p["invs"][dev_id]
            inv["strings"].sort(key=lambda s: int(s["id"]) if s["id"].isdigit() else 999)
            # régua nova (igual API PV): trancada/sem_corrente/baixa_perf/ativa/inativa vs mediana do inversor
            _keys = [s["id"] for s in inv["strings"]]
            _st   = _classifica_strings(pid, dev_id, _keys, [s["corrente"] for s in inv["strings"]])
            for s, stt in zip(inv["strings"], _st):
                s["status"] = stt
                s["ativa"]  = stt in ("ativa", "baixa_perf")
                s["trancada"] = stt == "trancada"
            ativas = _str_ativas(_st)
            total  = len(inv["strings"])
            str_esp = esp_map.get(inv["dev"], total)     # esperadas da planilha; fallback = total
            tot_ativas += ativas; tot_esp += str_esp
            inv_list.append({
                "id": dev_id, "nome": equip_disp.get(inv["dev"], inv["dev"]), "nome_api": inv["dev"],
                "ultima_leitura": inv["ts"].strftime("%Y-%m-%d %H:%M") if inv["ts"] else None,
                "falha_comunicacao": False, "desligado": ativas == 0,
                "strings_ativas": ativas, "total_strings": total,
                "str_esp": str_esp, "diferenca": ativas - str_esp,
                "temp": None, "eday": None, "strings": inv["strings"],
            })
        detail[pid] = inv_list
        summary.append({
            "usina": USINA_DISPLAY.get(sup, sup), "plant_id": pid,
            "qtd_inversores": len(p["invs"]), "inv_esp": len(p["invs"]),
            "strings_ativas": tot_ativas, "str_esp": tot_esp,
            "diferenca": tot_ativas - tot_esp,             # = soma das diferenças dos inversores
            "temp_media": None,
            "ultima_leitura": p["ts"].strftime("%Y-%m-%d %H:%M") if p["ts"] else None,
            "sem_dados": False, "falha_comunicacao": False,
        })
    summary.sort(key=lambda x: (severidade(x), x["usina"]))
    return summary, detail


def _pg_get_snapshot(force=False):
    """SWR: serve o snapshot atual na hora; quando expira, atualiza em fundo.
    force=1 e a 1ª carga continuam síncronos."""
    agora = time.time()
    if force or _pg_cache["summary"] is None:
        with _pg_lock:
            if _pg_cache["summary"] is None or _pg_cache["ts"] < agora:
                summary, detail = _pg_build_snapshot()
                _pg_cache.update({"summary": summary, "detail": detail, "ts": time.time()})
                _persist_mark()
        return _pg_cache["summary"], _pg_cache["detail"]
    if (agora - _pg_cache["ts"]) >= CACHE_TTL:
        def _bg():
            if not _pg_lock.acquire(blocking=False):
                return
            try:
                summary, detail = _pg_build_snapshot()
                _pg_cache.update({"summary": summary, "detail": detail, "ts": time.time()})
                _persist_mark()
            except Exception as e:
                print(f"[pg] refresh em fundo falhou: {e}")
            finally:
                _pg_lock.release()
        threading.Thread(target=_bg, daemon=True).start()
    return _pg_cache["summary"], _pg_cache["detail"]


# ── PG: visão geral de strings por usina ───────────────────────────────────────
@app.route("/api/pg/data")
def api_pg_data():
    force = flask_request.args.get("force", "0") == "1"
    try:
        rows, _ = _pg_get_snapshot(force)
    except Exception as e:
        return jsonify({"error": str(e), "rows": [], "summary": {}}), 500
    rows_com = [r for r in rows if not r.get("sem_dados")]
    return jsonify({
        "rows": rows,
        "summary": {
            "total_usinas":    len(rows),
            "total_strings":   sum(r["strings_ativas"] for r in rows_com),
            "alertas_strings": sum(1 for r in rows_com if r["strings_ativas"] == 0),
            "alertas_temp":    0,
            "alertas_comm":    sum(1 for r in rows if r.get("sem_dados")),
        },
        "cache_ts": datetime.now().strftime("%H:%M:%S"),
    })


# ── PG: drill-down (mesmo snapshot da visão geral → sempre consistente) ─────────
@app.route("/api/pg/plant/<int:plant_id>")
def api_pg_plant(plant_id):
    try:
        _, detail = _pg_get_snapshot(False)
    except Exception as e:
        return jsonify({"error": str(e), "inversores": []}), 500
    invs = detail.get(plant_id, [])
    # Reaplica a régua de trancadas no ato: o snapshot é cacheado (SWR), então uma string
    # recém-(des)marcada não estaria refletida aqui. Reclassifica sobre as correntes já no
    # snapshot p/ o drill-down ficar consistente com _trancadas sem reconstruir tudo.
    for inv in invs:
        keys = [s["id"] for s in inv["strings"]]
        st   = _classifica_strings(plant_id, inv["id"], keys,
                                   [s["corrente"] for s in inv["strings"]])
        for s, stt in zip(inv["strings"], st):
            s["status"]   = stt
            s["ativa"]    = stt in ("ativa", "baixa_perf")
            s["trancada"] = stt == "trancada"
        inv["strings_ativas"] = _str_ativas(st)
        if inv.get("str_esp") is not None:
            inv["diferenca"] = inv["strings_ativas"] - inv["str_esp"]
    return jsonify({"plant_id": plant_id, "inversores": invs})


# ── PG: curva diária de corrente por string (botão "Curva do dia" do drill-down) ─
#   Mesma FORMA do SPV (API PV) p/ reusar o plot do frontend (_spvPlotInto):
#   por inversor → curva {ST_xx: {x,y}}, mediana da corrente integrada do dia e
#   strings em subperformance (< SPV_SUB_FRAC da mediana). Fonte = stg_inverter_string_data.
def _pg_strings_curva(plant_id: int, dia: str, inv=None) -> dict:
    sql = """
      SELECT s.device_id, d.device_name, p.name AS pname,
             s.string_number, s.timestamp, s.string_current
      FROM dbt.stg_inverter_string_data s
      JOIN public.tb_devices d ON d.id = s.device_id
      LEFT JOIN public.tb_power_plants p ON p.id = s.power_plant_id
      WHERE s.power_plant_id = %(pid)s AND s.timestamp::date = %(dia)s
        AND (%(inv)s IS NULL OR s.device_id = %(inv)s)
      ORDER BY s.device_id, s.string_number, s.timestamp
    """
    conn = _pg_conn(); cur = conn.cursor()
    cur.execute(sql, {"pid": plant_id, "dia": dia, "inv": inv})
    recs = cur.fetchall(); conn.close()

    sup, invs = "", {}
    for dev_id, dev_name, pname, snum, ts, curr in recs:
        sup = sup or (pname or "").strip()
        inv = invs.setdefault(dev_id, {"nome_api": (dev_name or f"INV {dev_id}").strip(), "strings": {}})
        inv["strings"].setdefault(str(snum), []).append((ts, float(curr) if curr is not None else 0.0))

    out = []
    for dev_id in sorted(invs):
        inv = invs[dev_id]
        soma, curva = {}, {}
        for snum, serie in inv["strings"].items():
            serie.sort(key=lambda x: x[0])
            lbl = f"ST {int(snum):02d}" if snum.isdigit() else f"ST {snum}"
            soma[lbl] = sum(max(0.0, v) for _, v in serie)
            step = max(1, len(serie) // 160)
            sp   = serie[::step]
            curva[lbl] = {"x": [t.strftime("%H:%M") for t, _ in sp],
                          "y": [round(v, 2) for _, v in sp]}
        vals = sorted(soma.values())
        med  = vals[len(vals) // 2] if vals else 0.0
        strings, abaixo = [], 0
        for lbl in sorted(soma, key=_spv_stnum):
            e   = soma[lbl]
            sub = (med > 0 and e < med * SPV_SUB_FRAC)
            abaixo += 1 if sub else 0
            strings.append({"nome": lbl, "ativa": e > 0, "sub": sub,
                            "energia": round(e, 1), "pct": round(100.0 * e / med) if med else None})
        out.append({"id": dev_id,
                    "nome": (EQUIP_NAMES.get(sup, {}) or {}).get(inv["nome_api"], inv["nome_api"]),
                    "nome_api": inv["nome_api"], "curva": curva,
                    "mediana": round(med, 1), "abaixo": abaixo, "strings": strings})
    return {"plant_id": plant_id, "data": dia, "inversores": out}


@app.route("/api/pg/curva/<int:plant_id>")
def api_pg_curva(plant_id):
    dia = (flask_request.args.get("data") or datetime.now().strftime("%Y-%m-%d")).strip()
    if re.match(r"^\d{2}/\d{2}/\d{4}$", dia):              # aceita dd/mm/aaaa
        dia = datetime.strptime(dia, "%d/%m/%Y").strftime("%Y-%m-%d")
    inv = flask_request.args.get("inv", type=int)          # opcional: só um inversor (device_id)
    try:
        return jsonify(_pg_strings_curva(plant_id, dia, inv))
    except Exception as e:
        return jsonify({"error": str(e), "inversores": []}), 500


# ── PG: ETM (estações meteorológicas) ──────────────────────────────────────────
def _build_pg_etm_payload():
    sql = """
      SELECT w.power_plant_id, p.name, w.timestamp,
             w.irradiance_poa, w.irradiance_ghi, w.module_temperature
      FROM dbt.int_weather_station_latest_readings w
      LEFT JOIN public.tb_power_plants p ON p.id = w.power_plant_id
      ORDER BY p.name;
    """
    rows = []
    conn = _pg_conn(); cur = conn.cursor()
    cur.execute(sql)
    for pid, nome, ts, poa, ghi, tmod in cur.fetchall():
        poa = float(poa) if poa is not None else None
        ghi = float(ghi) if ghi is not None else None
        _usina_sup = (nome or f"Usina {pid}").strip()
        rows.append({
            "usina": USINA_DISPLAY.get(_usina_sup, _usina_sup), "plant_id": pid,
            "poa": round(poa, 2) if poa is not None else None,
            "ghi": round(ghi, 2) if ghi is not None else None,
            "poari": round(float(tmod), 1) if tmod is not None else None,  # 3ª coluna = temp módulo
            "poa_status":   _sensor_status(poa),
            "ghi_status":   _sensor_status(ghi),
            "poari_status": "ok" if tmod is not None else "sem",
            "sem_dados": False,
            "ultima_leitura": ts.strftime("%Y-%m-%d %H:%M") if ts else None,
        })
    conn.close()
    rows.sort(key=lambda x: (etm_severidade(x), x["usina"]))
    return {"rows": rows, "cache_ts": datetime.now().strftime("%H:%M:%S")}


@app.route("/api/pg/etm")
def api_pg_etm():
    force = flask_request.args.get("force", "0") == "1"
    try:
        return jsonify(_swr(_pg_etm_cache, _build_pg_etm_payload, force))
    except Exception as e:
        return jsonify({"error": str(e), "rows": []}), 500


# ── PG: pré-análise ETM (curva intradiária do banco) ───────────────────────────
_pg_analise_cache = {"payload": None, "ts": 0.0}


def _build_pg_analise_payload():
    sql = """
      SELECT w.power_plant_id, p.name, w.timestamp, w.irradiance_poa, w.irradiance_ghi
      FROM dbt.stg_weather_station_analogic_data w
      LEFT JOIN public.tb_power_plants p ON p.id = w.power_plant_id
      WHERE w.timestamp::date = CURRENT_DATE
      ORDER BY w.power_plant_id, w.timestamp;
    """
    conn = _pg_conn(); cur = conn.cursor(); cur.execute(sql)
    recs = cur.fetchall(); conn.close()

    plants = {}
    for pid, nome, ts, poa, ghi in recs:
        p = plants.setdefault(pid, {"sup": (nome or f"Usina {pid}").strip(), "serie": []})
        p["serie"].append((ts, _etm_clamp(float(poa) if poa is not None else None),
                               _etm_clamp(float(ghi) if ghi is not None else None)))
    rows = []
    for pid, p in plants.items():
        diag = _diagnostico_etm(p["serie"])
        usina = USINA_DISPLAY.get(p["sup"], p["sup"])
        if diag["ultima_leitura"] is None:
            rows.append({"usina": usina, "plant_id": pid, "flags": [], "severidade": 3,
                         "spark": {"labels": [], "poa": [], "ghi": []},
                         "ultima_leitura": None, "sem_dados": True})
        else:
            rows.append({"usina": usina, "plant_id": pid, "sem_dados": False, **diag})
    rows.sort(key=lambda x: (x["severidade"], x["usina"]))
    return {
        "rows": rows,
        "summary": {"total": len(rows),
                    "criticos": sum(1 for r in rows if r["severidade"] == 0),
                    "atencao":  sum(1 for r in rows if r["severidade"] == 1),
                    "sem_dados": sum(1 for r in rows if r.get("sem_dados"))},
        "cache_ts": datetime.now().strftime("%H:%M:%S"),
    }


@app.route("/api/pg/etm/analise")
def api_pg_etm_analise():
    force = flask_request.args.get("force", "0") == "1"
    try:
        return jsonify(_swr(_pg_analise_cache, _build_pg_analise_payload, force))
    except Exception as e:
        return jsonify({"error": str(e), "rows": [], "summary": {}}), 500


@app.route("/api/pg/etm/chart")
def api_pg_etm_chart():
    plant_id = flask_request.args.get("plant_id", type=int)
    if not plant_id:
        return jsonify({"error": "plant_id required"}), 400
    sql = """
      SELECT timestamp, irradiance_poa, irradiance_ghi
      FROM dbt.stg_weather_station_analogic_data
      WHERE power_plant_id = %s AND timestamp::date = CURRENT_DATE
      ORDER BY timestamp;
    """
    try:
        conn = _pg_conn(); cur = conn.cursor(); cur.execute(sql, (plant_id,))
        recs = cur.fetchall(); conn.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    labels, poa, ghi = [], [], []
    for ts, p, g in recs:
        labels.append(ts.strftime("%H:%M"))
        poa.append(_etm_clamp(float(p) if p is not None else None))
        ghi.append(_etm_clamp(float(g) if g is not None else None))
    return jsonify({"plant_id": plant_id, "labels": labels, "poa": poa, "ghi": ghi, "poari": []})


# ── PG: geração diária + irradiação (IPOA/GHI) por usina e período ─────────────
#   Geração = SUM por inversor do MAX(daily_active_energy) do dia (acumulado que
#   zera à meia-noite). Geração TOTAL por usina vem pronta do modelo dbt
#   int_inverter_power_plant_daily_energy_timeseries (= soma dos inversores).
#   IPOA/GHI = INTEGRAÇÃO TRAPEZOIDAL pelo tempo REAL entre leituras → kWh/m²
#   (área = Σ (v0+v1)/2 × Δt_horas ÷ 1000). Robusto a gaps: cada leitura pesa
#   pelo intervalo real até a próxima (não assume 5 min fixos). Intervalos > 60 min
#   são DESCARTADOS (não interpola buracos longos às cegas) e o dia é sinalizado.
#   Qualidade: n_leituras (288=dia cheio), cobertura %, maior gap diurno (08–16h).
PG_IRR_GAP_CAP_MIN = 60      # intervalo máx p/ integrar (min); acima disso, descarta
def _pg_geracao_periodo(start: str, end: str):
    sql = """
      WITH gen AS (
        SELECT power_plant_id, date AS dia,
               total_energy_kwh AS geracao_kwh, total_active_inverters AS invs
        FROM dbt.int_inverter_power_plant_daily_energy_timeseries
        WHERE date BETWEEN %(start)s AND %(end)s
      ),
      pts AS (
        SELECT power_plant_id, timestamp::date AS dia, timestamp AS ts,
               irradiance_poa AS poa, irradiance_ghi AS ghi,
               LAG(timestamp)      OVER w AS pts_prev,
               LAG(irradiance_poa) OVER w AS poa_prev,
               LAG(irradiance_ghi) OVER w AS ghi_prev
        FROM dbt.stg_weather_station_analogic_data
        WHERE timestamp::date BETWEEN %(start)s AND %(end)s
        WINDOW w AS (PARTITION BY power_plant_id, timestamp::date ORDER BY timestamp)
      ),
      irr AS (
        SELECT power_plant_id, dia,
               ROUND(SUM(CASE WHEN pts_prev IS NOT NULL
                              AND EXTRACT(EPOCH FROM (ts - pts_prev)) <= %(gapcap)s
                         THEN (poa + poa_prev)/2.0
                              * EXTRACT(EPOCH FROM (ts - pts_prev))/3600.0
                         ELSE 0 END) / 1000.0, 3) AS ipoa,
               ROUND(SUM(CASE WHEN pts_prev IS NOT NULL
                              AND EXTRACT(EPOCH FROM (ts - pts_prev)) <= %(gapcap)s
                         THEN (ghi + ghi_prev)/2.0
                              * EXTRACT(EPOCH FROM (ts - pts_prev))/3600.0
                         ELSE 0 END) / 1000.0, 3) AS ghi,
               COUNT(*) AS n_leituras,
               ROUND(MAX(CASE WHEN pts_prev IS NOT NULL
                              AND EXTRACT(HOUR FROM ts) BETWEEN 8 AND 16
                         THEN EXTRACT(EPOCH FROM (ts - pts_prev))/60.0 END)) AS gap_diurno_min
        FROM pts GROUP BY power_plant_id, dia
      )
      SELECT p.name,
             COALESCE(g.dia, i.dia) AS dia,
             g.geracao_kwh, g.invs, i.ipoa, i.ghi, i.n_leituras, i.gap_diurno_min
      FROM gen g
      FULL OUTER JOIN irr i
        ON g.power_plant_id = i.power_plant_id AND g.dia = i.dia
      LEFT JOIN public.tb_power_plants p
        ON p.id = COALESCE(g.power_plant_id, i.power_plant_id)
      ORDER BY p.name, dia;
    """
    conn = _pg_conn(); cur = conn.cursor()
    cur.execute(sql, {"start": start, "end": end, "gapcap": PG_IRR_GAP_CAP_MIN * 60})  # min→s (EPOCH é em s)
    recs = cur.fetchall(); conn.close()
    rows = []
    for nome, dia, ger, invs, ipoa, ghi, nleit, gapd in recs:
        n = int(nleit) if nleit is not None else None
        cobertura = round(100.0 * n / 288.0) if n is not None else None
        gapd = int(gapd) if gapd is not None else None
        # Confiável se cobertura >= 80% E nenhum gap diurno > 30 min
        confiavel = (cobertura is not None and cobertura >= 80
                     and (gapd is None or gapd <= 30))
        rows.append({
            "usina": nome or "—",
            "data": dia.strftime("%Y-%m-%d") if dia else None,
            "inversores": int(invs) if invs is not None else None,
            "geracao_kwh": float(ger) if ger is not None else None,
            "ipoa": float(ipoa) if ipoa is not None else None,
            "ghi":  float(ghi)  if ghi  is not None else None,
            "n_leituras": n,
            "cobertura": cobertura,         # % de 288
            "gap_diurno_min": gapd,         # maior gap entre 08–16h (min)
            "confiavel": confiavel,
        })
    return rows


def _periodo_args():
    """Lê start/end dos args; default = ontem→ontem. Retorna (start, end) ou (None, msg)."""
    hoje  = datetime.now().date()
    ontem = (hoje - timedelta(days=1)).isoformat()
    start = (flask_request.args.get("start") or ontem).strip()
    end   = (flask_request.args.get("end")   or start).strip()
    for d in (start, end):
        try:
            datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            return None, f"data inválida: {d} (use YYYY-MM-DD)"
    if start > end:
        start, end = end, start
    return (start, end), None


# ── PG: PR por inversor (BD_Thopen) — qualquer data ────────────────────────────
#   PR_inv = geração_inv_dia (kWh) ÷ (IPOA_dia (kWh/m²) × potência_inv (kWp)).
#   Geração = MAX(daily_active_energy) do inversor no dia (acumulado que zera 0h);
#   IPOA = integração trapezoidal da irradiância da estação da usina (mesma régua
#   do /api/pg/geracao); potência por inversor vem do Equipamentos (POWER_INV).
#   Inversor "abaixo" = PR < mediana da usina × (1 - PR_REL_SEVERO).
_pg_pr_cache = {}      # "YYYY-MM-DD" → {ts, summary, detail}
_pg_pr_lock  = threading.Lock()


def _pg_pr_build(dia: str):
    sql = """
      WITH gen AS (
        SELECT a.power_plant_id AS pid, a.device_id AS did, d.device_name AS dev,
               MAX(a.daily_active_energy) AS ger
        FROM dbt.stg_inverter_analogic_data a
        JOIN public.tb_devices d ON d.id = a.device_id
        WHERE a.timestamp::date = %(dia)s
        GROUP BY a.power_plant_id, a.device_id, d.device_name
      ),
      pts AS (
        SELECT power_plant_id, timestamp AS ts, irradiance_poa AS poa,
               LAG(timestamp)      OVER w AS pts_prev,
               LAG(irradiance_poa) OVER w AS poa_prev
        FROM dbt.stg_weather_station_analogic_data
        WHERE timestamp::date = %(dia)s
        WINDOW w AS (PARTITION BY power_plant_id ORDER BY timestamp)
      ),
      irr AS (
        SELECT power_plant_id,
               ROUND(SUM(CASE WHEN pts_prev IS NOT NULL
                              AND EXTRACT(EPOCH FROM (ts - pts_prev)) <= %(gapcap)s
                         THEN (poa + poa_prev)/2.0
                              * EXTRACT(EPOCH FROM (ts - pts_prev))/3600.0
                         ELSE 0 END) / 1000.0, 3) AS ipoa,
               COUNT(*) AS n_leituras,
               ROUND(MAX(CASE WHEN pts_prev IS NOT NULL
                              AND EXTRACT(HOUR FROM ts) BETWEEN 8 AND 16
                         THEN EXTRACT(EPOCH FROM (ts - pts_prev))/60.0 END)) AS gap_diurno_min
        FROM pts GROUP BY power_plant_id
      )
      SELECT p.name, g.pid, g.did, g.dev, g.ger, i.ipoa, i.n_leituras, i.gap_diurno_min
      FROM gen g
      LEFT JOIN irr i ON i.power_plant_id = g.pid
      LEFT JOIN public.tb_power_plants p ON p.id = g.pid
      ORDER BY p.name, g.dev;
    """
    conn = _pg_conn(); cur = conn.cursor()
    cur.execute(sql, {"dia": dia, "gapcap": PG_IRR_GAP_CAP_MIN * 60})
    recs = cur.fetchall(); conn.close()

    plants = {}
    for nome, pid, did, dev, ger, ipoa, nleit, gapd in recs:
        sup = (nome or f"Usina {pid}").strip()
        p   = plants.setdefault(pid, {"sup": sup,
                                      "ipoa": float(ipoa) if ipoa is not None else None,
                                      "n": int(nleit) if nleit is not None else None,
                                      "gap": int(gapd) if gapd is not None else None, "invs": []})
        ger = float(ger) if ger is not None else None
        pot = _pot_inv(sup, dev)
        pr  = round(ger / (p["ipoa"] * pot), 3) if (ger is not None and p["ipoa"] and pot) else None
        p["invs"].append({"id": did, "nome": (EQUIP_NAMES.get(sup, {}) or {}).get(dev, dev),
                          "nome_api": dev, "geracao_kwh": round(ger, 1) if ger is not None else None,
                          "pot_kwp": pot, "pr": pr})

    summary, detail = [], {}
    for pid, p in plants.items():
        invs = sorted(p["invs"], key=lambda x: _pv_trk_num(x["nome_api"]))
        prs  = sorted(x["pr"] for x in invs if x["pr"] is not None)
        med  = prs[len(prs) // 2] if prs else None
        lim  = med * (1 - PR_REL_SEVERO) if med is not None else None
        abaixo = 0
        for x in invs:
            x["abaixo"] = bool(x["pr"] is not None and lim is not None and x["pr"] < lim)
            abaixo += 1 if x["abaixo"] else 0
        # A estação grava ~150-210 leituras/dia (não 288), então cobertura é informativa;
        # a confiabilidade do PR é gateada por: sem buraco diurno grande, IPOA fisicamente
        # plausível (dia incompleto/sensor com falha → IPOA baixa → PR inflado) e nº mínimo
        # de leituras. Mesmo assim o ABSOLUTO depende da calibração do POA — a leitura
        # robusta é a comparação RELATIVA entre inversores da mesma usina (mesmo IPOA).
        cobertura = round(100.0 * p["n"] / 288.0) if p["n"] is not None else None
        # Confiável p/ PR ABSOLUTO: irradiância sem buraco grande, com leituras suficientes,
        # E PR fisicamente plausível (≤1,05). PR > 1,05 denuncia sensor POA lendo baixo /
        # dia de nuvem variável — aí só a comparação relativa entre inversores vale.
        confiavel = ((p["ipoa"] or 0) >= 2.0 and (p["n"] or 0) >= 100
                     and (p["gap"] is None or p["gap"] <= 30)
                     and med is not None and med <= 1.05)
        detail[pid] = invs
        summary.append({
            "usina": USINA_DISPLAY.get(p["sup"], p["sup"]), "plant_id": pid,
            "ipoa": p["ipoa"], "pr_mediana": med,
            "geracao_kwh": round(sum(x["geracao_kwh"] or 0 for x in invs), 1),
            "total": len(invs), "abaixo": abaixo,
            "sem_pot": sum(1 for x in invs if x["pot_kwp"] is None),
            "cobertura": cobertura, "confiavel": confiavel,
        })
    # confiáveis primeiro; dentro de cada grupo, mais inversores abaixo no topo
    summary.sort(key=lambda x: (0 if x["confiavel"] else 1,
                                0 if x["abaixo"] else 1, -(x["abaixo"] or 0), x["usina"]))
    return summary, detail


def _pg_pr_get(dia: str, force=False):
    agora = time.time()
    with _pg_pr_lock:
        ent = _pg_pr_cache.get(dia)
        if not force and ent and (agora - ent["ts"]) < CACHE_TTL:
            return ent["summary"], ent["detail"]
        summary, detail = _pg_pr_build(dia)
        _pg_pr_cache[dia] = {"ts": agora, "summary": summary, "detail": detail}
        return summary, detail


def _pr_dia_arg() -> str:
    """Data do PR (YYYY-MM-DD) vinda do ?date=; default = hoje."""
    d = (flask_request.args.get("date") or "").strip()
    return d if re.match(r"^\d{4}-\d{2}-\d{2}$", d) else datetime.now().date().isoformat()


@app.route("/api/pg/pr")
def api_pg_pr():
    """Overview de PR por usina (BD_Thopen). Cada usina abre em PR/Geração por inversor."""
    dia = _pr_dia_arg()
    force = flask_request.args.get("force", "0") == "1"
    try:
        summary, _ = _pg_pr_get(dia, force)
    except Exception as e:
        return jsonify({"error": str(e), "rows": [], "data": dia, "summary": {}}), 500
    return jsonify({"rows": summary, "data": dia,
                    "summary": {"usinas": len(summary),
                                "inversores": sum(r["total"] for r in summary),
                                "abaixo": sum(r["abaixo"] for r in summary),
                                "sem_pot": sum(r["sem_pot"] for r in summary)},
                    "cache_ts": datetime.now().strftime("%H:%M:%S")})


@app.route("/api/pg/pr/<int:plant_id>")
def api_pg_pr_plant(plant_id):
    dia = _pr_dia_arg()
    try:
        _, detail = _pg_pr_get(dia)
    except Exception as e:
        return jsonify({"error": str(e), "inversores": []}), 500
    return jsonify({"plant_id": plant_id, "data": dia, "inversores": detail.get(plant_id, [])})


@app.route("/api/pg/geracao")
def api_pg_geracao():
    periodo, err = _periodo_args()
    if err:
        return jsonify({"error": err, "rows": []}), 400
    start, end = periodo
    try:
        rows = _pg_geracao_periodo(start, end)
    except Exception as e:
        return jsonify({"error": str(e), "rows": []}), 500
    return jsonify({
        "rows": rows, "start": start, "end": end,
        "cache_ts": datetime.now().strftime("%H:%M:%S"),
    })


@app.route("/api/pg/geracao/export")
def api_pg_geracao_export():
    periodo, err = _periodo_args()
    if err:
        return jsonify({"error": err}), 400
    start, end = periodo
    try:
        rows = _pg_geracao_periodo(start, end)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=["usina", "data", "geracao_kwh", "inversores", "ipoa", "ghi",
                                   "cobertura", "gap_diurno_min"])
    df = df.rename(columns={
        "usina": "Usina", "data": "Data",
        "geracao_kwh": "Geração (kWh)", "inversores": "Inversores ativos",
        "ipoa": "IPOA (kWh/m²)", "ghi": "GHI (kWh/m²)",
        "cobertura": "Cobertura (%)", "gap_diurno_min": "Maior gap diurno (min)",
    })[["Usina", "Data", "Geração (kWh)", "Inversores ativos", "IPOA (kWh/m²)", "GHI (kWh/m²)",
        "Cobertura (%)", "Maior gap diurno (min)"]]

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        df.to_excel(xl, index=False, sheet_name="Geração diária")
        ws = xl.sheets["Geração diária"]
        for col_cells in ws.columns:
            largura = max((len(str(c.value)) for c in col_cells if c.value is not None), default=10)
            ws.column_dimensions[col_cells[0].column_letter].width = min(largura + 3, 40)
    buf.seek(0)
    fname = f"geracao_PG_{start}_a_{end}.xlsx"
    return send_file(buf, as_attachment=True, download_name=fname,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ── Estado compartilhado: verificação + comentários por usina ──────────────────
STATE_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ufv_state.json")
_state_lock = threading.Lock()


def _load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {}
    d.setdefault("verified", [])   # lista de chaves (ex.: "pv:22854", "so:CPP100")
    d.setdefault("comments", {})   # {chave: texto}
    d.setdefault("tracking", {})   # {chave: int}  → strings em acompanhamento
    d.setdefault("manutencao", [])  # lista de chaves de ETM em manutenção (ex.: "etm:pv:22854")
    d.setdefault("strings_trancadas", [])  # chaves "plant_id|inv_id|Ipv" de strings trancadas (MPPT sem string)
    return d


def _save_state(d: dict) -> None:
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)   # gravação atômica


_trancadas = set(_load_state().get("strings_trancadas", []))   # carga inicial em memória


@app.route("/api/state")
def api_state_get():
    with _state_lock:
        return jsonify(_load_state())


@app.route("/api/state/string-trancada", methods=["POST"])
def api_state_string_trancada():
    """Marca/desmarca uma string como 'trancada' (MPPT sem string conectada). Persiste no
    estado e atualiza o set em memória (usado por _classifica_strings)."""
    global _trancadas
    body     = flask_request.get_json(force=True, silent=True) or {}
    plant_id = str(body.get("plant_id", "")).strip()
    inv_id   = str(body.get("inv_id", "")).strip()
    string   = str(body.get("string", "")).strip()
    trancada = bool(body.get("trancada"))
    if not (plant_id and inv_id and string):
        return jsonify({"error": "plant_id, inv_id e string obrigatórios"}), 400
    key = f"{plant_id}|{inv_id}|{string}"
    with _state_lock:
        d = _load_state()
        s = set(d.get("strings_trancadas", []))
        s.add(key) if trancada else s.discard(key)
        d["strings_trancadas"] = sorted(s)
        _save_state(d)
        _trancadas = s
    return jsonify({"ok": True, "trancadas": len(s)})


@app.route("/api/state/verified", methods=["POST"])
def api_state_verified():
    body    = flask_request.get_json(force=True, silent=True) or {}
    key     = str(body.get("key", "")).strip()
    checked = bool(body.get("checked"))
    if not key:
        return jsonify({"error": "key required"}), 400
    with _state_lock:
        d = _load_state()
        s = set(d["verified"])
        s.add(key) if checked else s.discard(key)
        d["verified"] = sorted(s)
        _save_state(d)
    return jsonify({"ok": True})


@app.route("/api/state/manutencao", methods=["POST"])
def api_state_manutencao():
    body    = flask_request.get_json(force=True, silent=True) or {}
    key     = str(body.get("key", "")).strip()
    checked = bool(body.get("checked"))
    if not key:
        return jsonify({"error": "key required"}), 400
    with _state_lock:
        d = _load_state()
        s = set(d["manutencao"])
        s.add(key) if checked else s.discard(key)
        d["manutencao"] = sorted(s)
        _save_state(d)
    return jsonify({"ok": True})


@app.route("/api/state/tracking", methods=["POST"])
def api_state_tracking():
    body = flask_request.get_json(force=True, silent=True) or {}
    key  = str(body.get("key", "")).strip()
    val  = body.get("value")
    if not key:
        return jsonify({"error": "key required"}), 400
    with _state_lock:
        d = _load_state()
        if val in (None, "", 0):
            d["tracking"].pop(key, None)
        else:
            try:
                d["tracking"][key] = int(val)
            except (TypeError, ValueError):
                d["tracking"].pop(key, None)
        _save_state(d)
    return jsonify({"ok": True})


@app.route("/api/state/comment", methods=["POST"])
def api_state_comment():
    body = flask_request.get_json(force=True, silent=True) or {}
    key  = str(body.get("key", "")).strip()
    text = str(body.get("text", "")).strip()
    if not key:
        return jsonify({"error": "key required"}), 400
    with _state_lock:
        d = _load_state()
        if text:
            d["comments"][key] = text
        else:
            d["comments"].pop(key, None)
        _save_state(d)
    return jsonify({"ok": True})


# ══ FONTE E-MAIL (Owen) — CSVs SCADA via Gmail (ARA/IPX/STL/TUP) ═══════════════
#   Formato longo: Point name,Time,Value,Rendered,Annotation (latin-1).
#   Point name codifica UFV + dispositivo + medida. Acumula os CSVs das pastas.
# Pasta dos CSVs do 2C — resolve entre candidatos (o Desktop fica DENTRO do OneDrive,
# então a pasta real é a "irmã" do projeto em ...\temp\Projetos e-mail).
_OWEN_CANDS = [p for p in [
    os.environ.get("OWEN_ROOT"),
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Projetos e-mail"),
    os.path.join(os.path.expanduser("~"), "Desktop", "Projetos e-mail"),
    os.path.join(os.path.expanduser("~"), "OneDrive - GRID CO", "Área de Trabalho", "temp", "Projetos e-mail"),
] if p]
OWEN_ROOT = next((p for p in _OWEN_CANDS if os.path.isdir(p)), _OWEN_CANDS[-1])
OWEN_UFVS = {"ARA": "Araputanga", "IPX": "Ipixuna do Pará",
             "STL": "Sete Lagoas 2", "TUP": "Tupi Paulista"}   # fallback (código→nome)


def _owen_nome(code):
    """Nome de exibição da UFV: vem do BD_Performance (USINA_DISPLAY: Usina Supervisório→Usina),
    igual às outras abas; cai no fallback fixo se não estiver cadastrado."""
    return USINA_DISPLAY.get(code) or OWEN_UFVS.get(code) or code
# Acumulador persistente: como os e-mails são INCREMENTAIS (cada janela traz só o pedaço
# novo) e o baixador sobrescreve o arquivo, mesclamos cada leitura no acervo do DIA em disco.
OWEN_ACCUM_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "owen_accum.json")
OWEN_TS_FMT = "%Y-%m-%d %H:%M:%S"
_owen_accum = {"date": None, "etm": {}, "strings": {}, "trackers": {}}
_owen_lock = threading.Lock()
_owen_refresh_ts = 0.0


def _owen_num(s):
    s = str(s).strip().lstrip("'").replace(",", ".")
    try:    return float(s)
    except ValueError: return None


def _owen_rows(folder):
    """Itera (point_name, datetime, value) de todos os CSVs da subpasta (latin-1)."""
    d = os.path.join(OWEN_ROOT, folder)
    if not os.path.isdir(d):
        return
    for fn in sorted(os.listdir(d)):
        if not fn.lower().endswith(".csv"):
            continue
        try:
            with open(os.path.join(d, fn), encoding="latin-1", newline="") as fh:
                for row in csv.reader(fh):
                    if len(row) < 3 or row[0] == "Point name":
                        continue
                    v = _owen_num(row[2])
                    if v is None:
                        continue
                    try:
                        t = datetime.strptime(row[1].strip(), "%Y/%m/%d %H:%M:%S")
                    except Exception:
                        continue
                    yield row[0], t, v
        except Exception:
            continue


def _owen_load():
    global _owen_accum
    try:
        with open(OWEN_ACCUM_PATH, encoding="utf-8") as f:
            _owen_accum = json.load(f)
    except Exception:
        _owen_accum = {"date": None, "etm": {}, "strings": {}, "trackers": {}}
    for k in ("etm", "strings", "trackers"):
        _owen_accum.setdefault(k, {})


def _owen_save():
    try:
        tmp = OWEN_ACCUM_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_owen_accum, f)
        os.replace(tmp, OWEN_ACCUM_PATH)
    except Exception as e:
        print(f"[OWEN] erro salvando acumulador: {e}")


def _owen_prune_today(hoje):
    """Remove do acervo qualquer ponto que NÃO seja do dia 'hoje' (YYYY-MM-DD).
    Defesa contra sobras de CSV de dias anteriores que ainda estejam na pasta."""
    pref = hoje + " "
    for meds in _owen_accum.get("etm", {}).values():
        for series in meds.values():
            for ts in [k for k in series if not k.startswith(pref)]:
                del series[ts]
    for invs in _owen_accum.get("strings", {}).values():
        for strs in invs.values():
            for sn in [k for k, v in strs.items() if not str(v[0]).startswith(pref)]:
                del strs[sn]
    for trks in _owen_accum.get("trackers", {}).values():
        for node in trks.values():
            for key in ("alvo", "atual"):
                serie = node.get(key, {})
                for ts in [k for k in serie if not k.startswith(pref)]:
                    del serie[ts]


def _owen_refresh(force=False):
    """Mescla os CSVs atuais da pasta no acervo do dia (dedupe por ponto+timestamp)."""
    global _owen_refresh_ts
    with _owen_lock:
        if not force and _owen_accum.get("date") and (time.time() - _owen_refresh_ts) < CACHE_TTL:
            return
        hoje = datetime.now().strftime("%Y-%m-%d")
        if _owen_accum.get("date") != hoje:               # vira o dia → zera
            _owen_accum.update({"date": hoje, "etm": {}, "strings": {}, "trackers": {}})
        else:
            _owen_prune_today(hoje)                        # limpa sobras de dias anteriores
        rxs = re.compile(r"_Inv_([\d.]+)_STR_Corrente PV(\d+)")
        rxt = re.compile(r"_TRK_([\d.]+)_MED_(.+?) \(graus\)")
        # ETM
        for pn, t, v in _owen_rows("ETM"):
            if t.strftime("%Y-%m-%d") != hoje:            # só dados de HOJE
                continue
            u = pn.split("_", 1)[0]
            if u not in OWEN_UFVS:
                continue
            med = "ghi" if "GHI" in pn else ("poa" if "POA" in pn else None)
            if med:
                _owen_accum["etm"].setdefault(u, {}).setdefault(med, {})[t.strftime(OWEN_TS_FMT)] = _etm_clamp(v)
        # Strings (mantém o valor mais recente por string)
        for pn, t, v in _owen_rows("Strings"):
            if t.strftime("%Y-%m-%d") != hoje:
                continue
            u = pn.split("_", 1)[0]
            if u not in OWEN_UFVS:
                continue
            m = rxs.search(pn)
            if not m:
                continue
            ts = t.strftime(OWEN_TS_FMT)
            d = _owen_accum["strings"].setdefault(u, {}).setdefault(m.group(1), {})
            sn = str(int(m.group(2)))
            if sn not in d or ts > d[sn][0]:
                d[sn] = [ts, v]
        # Trackers (curva alvo/atual)
        for pn, t, v in _owen_rows("Trackers"):
            if t.strftime("%Y-%m-%d") != hoje:
                continue
            u = pn.split("_", 1)[0]
            if u not in OWEN_UFVS:
                continue
            m = rxt.search(pn)
            if not m:
                continue
            key = "alvo" if "Alvo" in m.group(2) else ("atual" if "Atual" in m.group(2) else None)
            if key:
                node = _owen_accum["trackers"].setdefault(u, {}).setdefault(m.group(1), {"alvo": {}, "atual": {}})
                node[key][t.strftime(OWEN_TS_FMT)] = v
        _owen_save()
        _owen_refresh_ts = time.time()


def _owen_pts(d):
    """{ts_str: v} → [(datetime, v)] ordenado."""
    return sorted((datetime.strptime(ts, OWEN_TS_FMT), v) for ts, v in d.items())


_owen_load()   # carrega o acervo do dia (persistido) na inicialização


# ── Owen: ETM (POA/GHI por UFV) ────────────────────────────────────────────────
def _owen_etm_build():
    _owen_refresh()
    with _owen_lock:
        return {u: {m: _owen_pts(s) for m, s in d.items()}
                for u, d in _owen_accum.get("etm", {}).items()}


def _owen_etm_series(ufv_data):
    """Junta poa/ghi por timestamp → série [(dt, poa, ghi, _)] p/ diagnóstico/chart."""
    byts = {}
    for m in ("poa", "ghi"):
        for t, v in ufv_data.get(m, []):
            byts.setdefault(t, {})[m] = v
    return [(t, d.get("poa"), d.get("ghi")) for t, d in sorted(byts.items())]


@app.route("/api/owen/etm/analise")
def api_owen_etm_analise():
    data = _owen_etm_build()
    rows = []
    for u in OWEN_UFVS:
        nome = _owen_nome(u)
        merged = _owen_etm_series(data.get(u, {}))
        if not merged:
            rows.append({"usina": nome, "plant_id": u, "flags": [], "severidade": 3,
                         "spark": {"labels": [], "poa": [], "ghi": []}, "sem_curva": False,
                         "ultima_leitura": None, "sem_dados": True})
            continue
        diag = _diagnostico_etm(merged)
        rows.append({"usina": nome, "plant_id": u, "sem_dados": False, "sem_curva": False, **diag})
    rows.sort(key=lambda x: (x["severidade"], x["usina"]))
    return jsonify({"rows": rows, "summary": {
        "total": len(rows),
        "criticos": sum(1 for r in rows if r["severidade"] == 0),
        "atencao":  sum(1 for r in rows if r["severidade"] == 1),
        "sem_dados": sum(1 for r in rows if r.get("sem_dados"))},
        "cache_ts": datetime.now().strftime("%H:%M:%S")})


@app.route("/api/owen/etm/chart")
def api_owen_etm_chart():
    u = (flask_request.args.get("plant") or "").strip()
    data = _owen_etm_build()
    merged = _owen_etm_series(data.get(u, {}))
    return jsonify({"labels": [t.strftime("%H:%M") for t, _, _ in merged],
                    "poa": [p for _, p, _ in merged],
                    "ghi": [g for _, _, g in merged], "poari": []})


# ── Owen: Strings (corrente por string/inversor, último valor do dia) ──────────
def _owen_strings_build():
    _owen_refresh()
    with _owen_lock:
        out = {}   # ufv → inv → strnum → (datetime, valor)
        for u, invs in _owen_accum.get("strings", {}).items():
            out[u] = {inv: {sn: (datetime.strptime(ts, OWEN_TS_FMT), v) for sn, (ts, v) in strs.items()}
                      for inv, strs in invs.items()}
        return out


def _owen_inv_tag(code, inv):
    return f"{code}_Inv_{inv}"   # nomenclatura supervisório (igual ao que está no BD_Performance)


def _owen_esp(code, inv):
    """Esperadas do BD_Performance pela chave SUPERVISÓRIO (Usina Sup=código, Equip Sup=tag),
    igual à API PV/SunOp. None se NÃO cadastrado — não inventa contagem física."""
    return ESPERADO_INV.get(code, {}).get(_owen_inv_tag(code, inv))


@app.route("/api/owen/strings/data")
def api_owen_strings_data():
    data = _owen_strings_build()
    rows = []
    for u in OWEN_UFVS:
        nome = _owen_nome(u)
        invs = data.get(u, {})
        if not invs:
            rows.append({"usina": nome, "plant_id": u, "qtd_inversores": 0,
                         "strings_ativas": None, "str_esp": None, "diferenca": None,
                         "temp_media": None, "ultima_leitura": None, "sem_dados": True,
                         "falha_comunicacao": False})
            continue
        ativas, ts_max = 0, None
        for inv, strs in invs.items():
            ativas += sum(_ipv_ativas([v for _, v in strs.values()]))
            tmax = max((t for t, _ in strs.values()), default=None)
            if tmax and (ts_max is None or tmax > ts_max):
                ts_max = tmax
        esp_map = ESPERADO_INV.get(u, {})                  # esperado vem SÓ do BD_Performance
        str_esp = sum(esp_map.values()) if esp_map else None
        rows.append({"usina": nome, "plant_id": u, "qtd_inversores": len(invs),
                     "strings_ativas": ativas, "str_esp": str_esp,
                     "diferenca": (ativas - str_esp) if str_esp is not None else None,
                     "temp_media": None,
                     "ultima_leitura": ts_max.strftime("%Y-%m-%d %H:%M") if ts_max else None,
                     "sem_dados": False, "falha_comunicacao": False})
    rows.sort(key=lambda x: (severidade(x), x["usina"]))
    return jsonify({"rows": rows, "summary": {
        "total_usinas": len(rows),
        "total_strings": sum(r["strings_ativas"] for r in rows if r.get("strings_ativas")),
        "alertas_strings": sum(1 for r in rows if r.get("diferenca") is not None and r["diferenca"] < 0)},
        "cache_ts": datetime.now().strftime("%H:%M:%S")})


@app.route("/api/owen/strings/plant/<plant_id>")
def api_owen_strings_plant(plant_id):
    data = _owen_strings_build()
    nome = _owen_nome(plant_id)
    invs = data.get(plant_id, {})
    inversores = []
    for inv in sorted(invs, key=lambda x: [int(p) for p in x.split(".")]):
        strs = invs[inv]
        ids = sorted(strs, key=lambda x: int(x))
        correntes = [strs[s][1] for s in ids]
        flags = _ipv_ativas(correntes)
        chips = [{"id": s, "corrente": strs[s][1], "ativa": a} for s, a in zip(ids, flags)]
        ativas = sum(flags)
        tag = _owen_inv_tag(plant_id, inv)
        esp = ESPERADO_INV.get(plant_id, {}).get(tag)          # SÓ do BD_Performance (None se não cadastrado)
        nome_inv = EQUIP_NAMES.get(plant_id, {}).get(tag, f"Inversor {inv}")
        ts_inv = max((t for t, _ in strs.values()), default=None)
        inversores.append({"id": inv, "nome": nome_inv, "nome_api": tag,
                           "ultima_leitura": ts_inv.strftime("%Y-%m-%d %H:%M") if ts_inv else None,
                           "falha_comunicacao": False, "desligado": ativas == 0,
                           "strings_ativas": ativas, "total_strings": len(strs),
                           "str_esp": esp, "diferenca": (ativas - esp) if esp is not None else None,
                           "temp": None, "eday": None, "strings": chips})
    return jsonify({"plant_id": plant_id, "inversores": inversores})


# ── Owen: Trackers (alvo/atual por UFV, análise por curva) ─────────────────────
def _owen_trackers_build():
    _owen_refresh()
    with _owen_lock:
        return {u: {n: {"alvo": _owen_pts(d["alvo"]), "atual": _owen_pts(d["atual"])}
                    for n, d in trks.items()}
                for u, trks in _owen_accum.get("trackers", {}).items()}


def _owen_trackers_analise(plant_id):
    nome = _owen_nome(plant_id)
    trks = _owen_trackers_build().get(plant_id, {})
    base = {"usina": nome, "plant_id": plant_id, "total": 0, "parados": 0,
            "desvios": 0, "atrasos": 0, "sem_alvo": False, "pior_disparidade": None,
            "ultima_leitura": None, "trackers": [], "tem_trackers": bool(trks)}
    if not trks:
        return base
    amps = {n: (max(v for _, v in d["atual"]) - min(v for _, v in d["atual"])) if d["atual"] else None
            for n, d in trks.items()}
    amp_ok = sorted(a for a in amps.values() if a is not None)
    amp_ref = amp_ok[len(amp_ok) // 2] if amp_ok else 0.0
    sem_alvo = all(not d["alvo"] for d in trks.values())

    raw, ts_max = [], None
    for n, d in trks.items():
        s, sp = d["atual"], d["alvo"]
        atual = s[-1][1] if s else None
        alvo = sp[-1][1] if sp else None
        if s and (ts_max is None or s[-1][0] > ts_max):
            ts_max = s[-1][0]
        cur_disp = max_disp = None
        if s and sp:
            ad = dict(sp)
            disps = [abs(v - ad[t]) for t, v in s if t in ad]
            if disps:
                max_disp, cur_disp = max(disps), disps[-1]
        raw.append({"n": n, "atual": atual, "alvo": alvo, "amp": amps.get(n),
                    "cur": cur_disp, "max": max_disp})

    def _med(vals):
        v = sorted(x for x in vals if x is not None)
        return v[len(v) // 2] if v else 0.0
    med_cur, med_max = _med([r["cur"] for r in raw]), _med([r["max"] for r in raw])

    lst = []; par = des = atr = 0
    for r in raw:
        amp, cur, mx = r["amp"], r["cur"], r["max"]
        if amp is not None and amp < TRK_PARADO_AMP and amp_ref > TRK_ALVO_MOVE_MIN:
            st = "parado"; par += 1
        elif cur is not None and (cur - med_cur) > TRK_DESVIO_MIN:
            st = "desvio"; des += 1
        elif mx is not None and (mx - med_max) > TRK_ATRASO_DELTA:
            st = "atraso"; atr += 1
        else:
            st = "normal"
        lst.append({"id": f"Tracker {r['n']}",
                    "alvo": round(r["alvo"], 2) if r["alvo"] is not None else None,
                    "atual": round(r["atual"], 2) if r["atual"] is not None else None,
                    "disparidade": round(cur, 2) if cur is not None else None,
                    "max_disp": round(mx, 1) if mx is not None else None,
                    "amplitude": round(amp, 1) if amp is not None else None, "status": st})
    lst.sort(key=lambda x: [int(p) for p in x["id"].replace("Tracker ", "").split(".")])
    pior = max((t["max_disp"] for t in lst if t["max_disp"] is not None), default=None)
    base.update({"total": len(lst), "parados": par, "desvios": des, "atrasos": atr,
                 # aliases p/ a tabela-resumo compartilhada (renderSoTrackers lê severos/leves/fora_media)
                 "severos": par, "leves": des, "fora_media": atr,
                 "sem_alvo": sem_alvo, "pior_disparidade": pior,
                 "ultima_leitura": ts_max.strftime("%Y-%m-%d %H:%M") if ts_max else None,
                 "trackers": lst})
    return base


@app.route("/api/owen/trackers")
def api_owen_trackers():
    rows = []
    for u in OWEN_UFVS:
        r = _owen_trackers_analise(u)
        r.pop("trackers", None)
        rows.append(r)
    rows.sort(key=lambda x: (_trk_severidade2(x), x["usina"]))
    return jsonify({"rows": rows, "summary": {
        "usinas": sum(1 for r in rows if r["total"]),
        "trackers": sum(r["total"] for r in rows),
        "parados": sum(r["parados"] for r in rows),
        "atrasos": sum(r["atrasos"] for r in rows)},
        "cache_ts": datetime.now().strftime("%H:%M:%S")})


@app.route("/api/owen/trackers/<plant_id>")
def api_owen_trackers_plant(plant_id):
    return jsonify(_owen_trackers_analise(plant_id))


@app.route("/api/owen/trackers/<plant_id>/chart")
def api_owen_trackers_chart(plant_id):
    trks = _owen_trackers_build().get(plant_id, {})
    def _down(s, m=180): return s[::max(1, len(s) // m)]
    def _num(n): return [int(p) for p in n.split(".")]
    out, alvo = [], None
    for n in sorted(trks, key=_num):
        s = trks[n]["atual"]
        if s:
            s = _down(s)
            out.append({"id": f"Tracker {n}", "x": [t.strftime("%H:%M") for t, _ in s],
                        "y": [round(v, 2) for _, v in s]})
    for n in sorted(trks, key=_num):
        s = trks[n]["alvo"]
        if s:
            s = _down(s)
            alvo = {"x": [t.strftime("%H:%M") for t, _ in s], "y": [round(v, 2) for _, v in s]}
            break
    return jsonify({"plant": _owen_nome(plant_id), "trackers": out, "alvo": alvo})


def _trk_severidade2(r) -> int:
    if r.get("parados"): return 0
    if r.get("desvios"): return 1
    if r.get("atrasos"): return 2
    if not r.get("total"): return 4
    return 3


# ── PG: Trackers (espelho do Athon/SunOp, dados do PostgreSQL) ─────────────────
#   Overview  : leitura instantânea (dbt.int_tracker_latest_readings) → severo/leve/fora
#   Detalhe+curva: série do dia (dbt.stg_tracker_analogic_data) → parado/desvio/atraso
_pg_trk_cache      = {"payload": None, "ts": 0.0}     # overview de todas as usinas
_pg_trk_curva_cache = {}                              # (plant_id, date) → {ts, dados}


def _pg_trk_num(name: str) -> int:
    try:
        return int("".join(c for c in str(name) if c.isdigit()) or 999)
    except Exception:
        return 999


def _pg_trackers_overview() -> dict:
    """Resumo instantâneo por usina (última leitura de cada tracker)."""
    conn = _pg_conn(); cur = conn.cursor()
    cur.execute("""
        SELECT p.id, p.name, d.device_name,
               t.posat, t.posal, t.status_label, t.timestamp
        FROM dbt.int_tracker_latest_readings t
        JOIN public.tb_power_plants p ON p.id = t.power_plant_id
        JOIN public.tb_devices       d ON d.id = t.device_id
        ORDER BY p.name, d.device_name
    """)
    rows = cur.fetchall(); conn.close()

    plants = {}
    for pid, pname, dname, posat, posal, label, ts in rows:
        alvo  = float(posal) if posal is not None else None
        atual = float(posat) if posat is not None else None
        disp  = abs(alvo - atual) if (alvo is not None and atual is not None) else None
        p = plants.setdefault(str(pid), {"usina": pname, "trks": [], "ts": None})
        if ts and (p["ts"] is None or ts > p["ts"]):
            p["ts"] = ts
        p["trks"].append({"alvo": alvo, "atual": atual, "disp": disp, "tid": dname})

    out = []
    for pid, p in plants.items():
        lst = p["trks"]
        grupos = {}
        for t in lst:
            if t["alvo"] is not None and t["atual"] is not None:
                grupos.setdefault(round(t["alvo"], 1), []).append(t["atual"])
        media_grupo = {k: sum(v) / len(v) for k, v in grupos.items()}
        for t in lst:
            disp, alvo, atual = t["disp"], t["alvo"], t["atual"]
            gk = round(alvo, 1) if alvo is not None else None
            if disp is not None and disp > TRK_DISP_SEVERO:
                t["st"] = "severo"
            elif disp is not None and disp > TRK_DISP_LEVE:
                t["st"] = "leve"
            elif gk in media_grupo and atual is not None and abs(atual - media_grupo[gk]) > TRK_FORA_MEDIA:
                t["st"] = "fora_media"
            else:
                t["st"] = "normal"
        pior = max((t["disp"] for t in lst if t["disp"] is not None), default=None)
        _trk_accum_feed(pid, p["ts"], [(t["tid"], t["disp"], t["atual"]) for t in lst])
        # travado o dia todo (amplitude ~0 enquanto a usina girou) — conta como severo
        _par = _trk_accum_parados(pid)
        for t in lst:
            if str(t["tid"]) in _par:
                t["st"] = "parado"
        sev  = sum(1 for t in lst if t["st"] in ("severo", "parado"))
        leve = sum(1 for t in lst if t["st"] == "leve")
        fora = sum(1 for t in lst if t["st"] == "fora_media")
        out.append({
            "usina": p["usina"], "plant_id": pid, "total": len(lst),
            "severos": sev, "leves": leve, "fora_media": fora,
            "pior_disparidade": round(pior, 2) if pior is not None else None,
            "desvio_medio": _trk_accum_desvio(pid),
            "ultima_leitura": p["ts"].strftime("%Y-%m-%d %H:%M") if p["ts"] else None,
            "tem_trackers": True,
        })
    out.sort(key=lambda x: (_trk_severidade(x), x["usina"]))
    return {"rows": out, "summary": {
        "usinas": len(out), "trackers": sum(r["total"] for r in out),
        "severos": sum(r["severos"] for r in out), "leves": sum(r["leves"] for r in out)},
        "cache_ts": datetime.now().strftime("%H:%M:%S")}


def _pg_trk_default_date() -> str:
    """Última data com dados; se for madrugada, usa o dia anterior (dia 'cheio')."""
    try:
        conn = _pg_conn(); cur = conn.cursor()
        cur.execute("SELECT max(timestamp) FROM dbt.stg_tracker_analogic_data")
        mx = cur.fetchone()[0]; conn.close()
        if mx is None:
            return datetime.now().strftime("%Y-%m-%d")
        d = mx.date()
        if mx.hour < 6:
            d = d - timedelta(days=1)
        return d.strftime("%Y-%m-%d")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")


def _pg_trk_plant_curvas(plant_id: str, date: str) -> dict:
    """Série do dia de uma usina → {tracker: {'alvo':[(ts,v)], 'atual':[(ts,v)]}}"""
    key = (str(plant_id), date)
    ent = _pg_trk_curva_cache.get(key)
    if ent and time.time() - ent["ts"] < CACHE_TTL:
        return ent["dados"]
    dados = {}
    try:
        conn = _pg_conn(); cur = conn.cursor()
        cur.execute("""
            SELECT d.device_name, s.timestamp, s.posat, s.posal
            FROM dbt.stg_tracker_analogic_data s
            JOIN public.tb_devices d ON d.id = s.device_id
            WHERE s.power_plant_id = %s
              AND s.timestamp >= %s::date
              AND s.timestamp <  (%s::date + interval '1 day')
            ORDER BY d.device_name, s.timestamp
        """, (int(plant_id), date, date))
        for dname, ts, posat, posal in cur.fetchall():
            d = dados.setdefault(dname, {"alvo": [], "atual": []})
            if posat is not None:
                d["atual"].append((ts, float(posat)))
            if posal is not None:
                d["alvo"].append((ts, float(posal)))
        conn.close()
    except Exception as e:
        print(f"[PG TRK] erro curvas {plant_id}/{date}: {e}")
    _pg_trk_curva_cache[key] = {"ts": time.time(), "dados": dados}
    return dados


def _pg_trk_nome(plant_id: str) -> str:
    for r in (_pg_trk_cache.get("payload") or {}).get("rows", []):
        if r["plant_id"] == str(plant_id):
            return r["usina"]
    return str(plant_id)


def _pg_trackers_analise(plant_id: str, date: str = None) -> dict:
    """Detalhe por CURVA do dia (mesma lógica do Owen): parado/desvio/atraso."""
    date = date or _pg_trk_default_date()
    trks = _pg_trk_plant_curvas(plant_id, date)
    base = {"usina": _pg_trk_nome(plant_id), "plant_id": str(plant_id), "date": date,
            "total": 0, "parados": 0, "desvios": 0, "atrasos": 0, "sem_alvo": False,
            "pior_disparidade": None, "ultima_leitura": None,
            "trackers": [], "tem_trackers": bool(trks)}
    if not trks:
        return base
    amps = {n: (max(v for _, v in d["atual"]) - min(v for _, v in d["atual"])) if d["atual"] else None
            for n, d in trks.items()}
    amp_ok = sorted(a for a in amps.values() if a is not None)
    amp_ref = amp_ok[len(amp_ok) // 2] if amp_ok else 0.0
    sem_alvo = all(not d["alvo"] for d in trks.values())

    raw, ts_max = [], None
    for n, d in trks.items():
        s, sp = d["atual"], d["alvo"]
        atual = s[-1][1] if s else None
        alvo  = sp[-1][1] if sp else None
        if s and (ts_max is None or s[-1][0] > ts_max):
            ts_max = s[-1][0]
        cur_disp = max_disp = None
        if s and sp:
            ad = dict(sp)
            disps = [abs(v - ad[t]) for t, v in s if t in ad]
            if disps:
                max_disp, cur_disp = max(disps), disps[-1]
        raw.append({"n": n, "atual": atual, "alvo": alvo, "amp": amps.get(n),
                    "cur": cur_disp, "max": max_disp})

    def _med(vals):
        v = sorted(x for x in vals if x is not None)
        return v[len(v) // 2] if v else 0.0
    med_cur, med_max = _med([r["cur"] for r in raw]), _med([r["max"] for r in raw])

    lst = []; par = des = atr = 0
    for r in raw:
        amp, cur_, mx = r["amp"], r["cur"], r["max"]
        if amp is not None and amp < TRK_PARADO_AMP and amp_ref > TRK_ALVO_MOVE_MIN:
            st = "parado"; par += 1
        elif cur_ is not None and (cur_ - med_cur) > TRK_DESVIO_MIN:
            st = "desvio"; des += 1
        elif mx is not None and (mx - med_max) > TRK_ATRASO_DELTA:
            st = "atraso"; atr += 1
        else:
            st = "normal"
        lst.append({"id": r["n"],
                    "alvo":  round(r["alvo"], 2)  if r["alvo"]  is not None else None,
                    "atual": round(r["atual"], 2) if r["atual"] is not None else None,
                    "disparidade": round(cur_, 2) if cur_ is not None else None,
                    "max_disp":    round(mx, 1)   if mx   is not None else None,
                    "amplitude":   round(amp, 1)  if amp  is not None else None, "status": st})
    lst.sort(key=lambda x: _pg_trk_num(x["id"]))
    pior = max((t["max_disp"] for t in lst if t["max_disp"] is not None), default=None)
    base.update({"total": len(lst), "parados": par, "desvios": des, "atrasos": atr,
                 "severos": par, "leves": des, "fora_media": atr,
                 "sem_alvo": sem_alvo, "pior_disparidade": pior,
                 "ultima_leitura": ts_max.strftime("%Y-%m-%d %H:%M") if ts_max else None,
                 "trackers": lst})
    return base


@app.route("/api/pg/trackers")
def api_pg_trackers():
    force = flask_request.args.get("force", "0") == "1"
    try:
        return jsonify(_swr(_pg_trk_cache, _pg_trackers_overview, force))
    except Exception as e:
        return jsonify({"rows": [], "summary": {"usinas": 0, "trackers": 0, "severos": 0, "leves": 0},
                        "erro": str(e), "cache_ts": datetime.now().strftime("%H:%M:%S")})


@app.route("/api/pg/trackers/<plant_id>")
def api_pg_trackers_plant(plant_id):
    return jsonify(_pg_trackers_analise(plant_id, flask_request.args.get("date")))


@app.route("/api/pg/trackers/<plant_id>/chart")
def api_pg_trackers_chart(plant_id):
    date = (flask_request.args.get("date") or _pg_trk_default_date()).strip()
    trks = _pg_trk_plant_curvas(plant_id, date)
    def _down(s, m=180): return s[::max(1, len(s) // m)]
    out, alvo = [], None
    for n in sorted(trks, key=_pg_trk_num):
        s = trks[n]["atual"]
        if s:
            s = _down(s)
            out.append({"id": n, "x": [t.strftime("%H:%M") for t, _ in s],
                        "y": [round(v, 2) for _, v in s]})
    for n in sorted(trks, key=_pg_trk_num):
        s = trks[n]["alvo"]
        if s:
            s = _down(s)
            alvo = {"x": [t.strftime("%H:%M") for t, _ in s], "y": [round(v, 2) for _, v in s]}
            break
    return jsonify({"plant": _pg_trk_nome(plant_id), "date": date, "trackers": out, "alvo": alvo})


# ── API PV: PR por inversor (usinas string-box, dia atual) ─────────────────────
#   PR_inv = Geração_inv (Eday, kWh) / (IPOA do dia (kWh/m²) × Potência_inv (kWp))
#   Potência vem do Equipamentos (POWER_INV). String-box = inversores com ≤1 string.
#   Classificação: relativa à MEDIANA da usina (inversor abaixo = candidato a perda).
PR_REL_LEVE   = 0.05   # PR < mediana×(1-0.05) → leve
PR_REL_SEVERO = 0.10   # PR < mediana×(1-0.10) → severo
_pv_pr_cache  = {"payload": None, "ts": 0.0, "detail": {}}


def _ipv_count(cj: dict) -> int:
    return len([k for k in cj if k.startswith("Ipv") and isinstance(cj[k], (int, float))])


def _ipoa_from_meteo(recs: list):
    """Integra a curva de POA (W/m²) do dia → IPOA em kWh/m² (trapézio, descarta gaps)."""
    pts = []
    for rec in (recs or []):
        cj  = parse_cj(rec.get("conteudojson"))
        poa = _pick_irr(cj, "IrPOA", "piraPOA1", "Ir1", "Ir")
        ts  = rec.get("tsleitura_new", "")
        if poa is None or not ts:
            continue
        try:
            t = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
        pts.append((t, max(0.0, float(poa))))
    pts.sort()
    area = 0.0
    for (t0, p0), (t1, p1) in zip(pts, pts[1:]):
        dt = (t1 - t0).total_seconds() / 3600.0
        if dt <= 0 or dt > 0.5:          # descarta gaps > 30 min
            continue
        area += (p0 + p1) / 2.0 * dt
    return round(area / 1000.0, 3) if area > 0 else None


def _pv_pr_collect(token: str, plant: dict) -> dict:
    """Fase A: geração (Eday) + nº de strings por inversor; detecta string-box. SEM IPOA."""
    pid  = plant["id"]
    psup = str(plant["nome"]).strip()
    raw  = {"usina": nome_usina(pid, plant["nome"]), "plant_id": pid, "plant_sup": psup,
            "stringbox": False, "invs": [], "ts_max": ""}
    try:
        recs = _http().post(f"{BASE_URL}/day_inverter", headers={"x-access-token": token},
                             json={"id": pid}, timeout=45).json()
    except Exception:
        return raw
    if not recs:
        return raw
    dev_names = {}
    try:
        dr = _http().get(f"{BASE_URL}/plant_devices", headers={"x-access-token": token},
                          json={"id": pid}, timeout=20).json()
        devs = dr
        if isinstance(dr, list) and dr and "plant_devices" in dr[0]:
            devs = dr[0]["plant_devices"]
        elif isinstance(dr, dict):
            devs = dr.get("plant_devices", [])
        dev_names = {d["device_id"]: str(d.get("device_name", "")).strip() for d in devs}
    except Exception:
        pass
    latest = {}
    for rec in recs:
        i = rec.get("idefinversor"); ts = rec.get("tsleitura_new", "")
        if i not in latest or ts > latest[i]["tsleitura_new"]:
            latest[i] = rec
    _EXCL = ["x", "old", "velho", "antigo"]
    def _eh_inv(did):
        a    = dev_names.get(did, str(did)).lower()
        disp = EQUIP_NAMES.get(psup, {}).get(dev_names.get(did, str(did)), dev_names.get(did, str(did))).lower()
        if "inv" not in a and "inv" not in disp:
            return False
        return not any(e in a or e in disp for e in _EXCL)
    ids = sorted([d for d in (dev_names.keys() if dev_names else latest.keys()) if _eh_inv(d)],
                 key=lambda x: dev_names.get(x, str(x)))
    ipv_max, ts_max, invs = 0, "", []
    for did in ids:
        name_api = dev_names.get(did, f"INV-{did}")
        name     = EQUIP_NAMES.get(psup, {}).get(name_api, name_api)
        rec      = latest.get(did)
        eday = None; ipvc = 0; ts = None
        if rec:
            cj   = parse_cj(rec.get("conteudojson"))
            ipvc = _ipv_count(cj); ipv_max = max(ipv_max, ipvc)
            e    = cj.get("Eday"); eday = float(e) if isinstance(e, (int, float)) else None
            ts   = rec.get("tsleitura_new")
            if ts and ts > ts_max:
                ts_max = ts
        invs.append({"id": name, "nome_api": name_api,
                     "eday": round(eday, 1) if eday is not None else None,
                     "pot_kwp": _pot_inv(psup, name_api, name), "ipv": ipvc,
                     "ultima_leitura": ts})
    # Deduplica por nome de exibição: mantém o que tem dados (igual ao api_plant_detail)
    seen = {}
    for inv in invs:
        k = inv["id"]
        if k not in seen or (seen[k].get("eday") is None and inv.get("eday") is not None):
            seen[k] = inv
    invs = list(seen.values())
    raw.update({"stringbox": (ipv_max <= 1 and len(invs) > 0), "inversores": invs, "ts_max": ts_max or None})
    return raw


def _pv_pr_compute(raw: dict, token: str) -> dict:
    """Fase B: busca IPOA do dia e calcula PR por inversor + da usina; classifica vs mediana."""
    pid = raw["plant_id"]
    ipoa = None
    try:
        meteo = _http().post(f"{BASE_URL}/day_meteo", headers={"x-access-token": token},
                              json={"id": pid}, timeout=30).json() or []
        ipoa = _ipoa_from_meteo(meteo)
    except Exception:
        pass
    invs = raw["inversores"]
    for i in invs:
        i["pr"] = (round(i["eday"] / (ipoa * i["pot_kwp"]), 3)
                   if (i["eday"] is not None and ipoa and i["pot_kwp"]) else None)
    prs = sorted(i["pr"] for i in invs if i["pr"] is not None)
    med = prs[len(prs) // 2] if prs else None
    abaixo = sem_pot = 0
    for i in invs:
        if i["pot_kwp"] is None:
            sem_pot += 1
        if i["pr"] is None:
            i["status"] = "sem_dados"
        elif med and i["pr"] < med * (1 - PR_REL_SEVERO):
            i["status"] = "severo"; abaixo += 1
        elif med and i["pr"] < med * (1 - PR_REL_LEVE):
            i["status"] = "leve"; abaixo += 1
        else:
            i["status"] = "ok"
    g = sum(i["eday"] for i in invs if i["eday"] is not None and i["pot_kwp"] is not None)
    p = sum(i["pot_kwp"] for i in invs if i["eday"] is not None and i["pot_kwp"] is not None)
    raw.update({
        "ipoa":        ipoa,
        "geracao_kwh": round(g, 1) if g else None,
        "pot_kwp":     round(p, 1) if p else None,
        "pr":          round(g / (ipoa * p), 3) if (ipoa and p) else None,
        "pr_mediana":  round(med, 3) if med else None,
        "total":       len(invs), "abaixo": abaixo, "sem_pot": sem_pot,
        "ultima_leitura": raw.get("ts_max"),
    })
    return raw


def _build_pv_pr_payload():
    token = get_token()
    plants = get_plants(token)
    plants = [p for p in plants if p["nome"].strip() in FULL_OM] if FULL_OM else plants
    # Fase A — todas as usinas (detecta string-box)
    raws = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_pv_pr_collect, token, p): p for p in plants}
        for f in as_completed(futs):
            raws.append(f.result())
    sb = [r for r in raws if r.get("stringbox")]
    # Fase B — só string-box (busca IPOA + calcula PR)
    detail = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_pv_pr_compute, r, token): r for r in sb}
        for f in as_completed(futs):
            r = f.result(); detail[r["plant_id"]] = r
    keys = ("usina", "plant_id", "ipoa", "pr", "pr_mediana", "total", "abaixo",
            "sem_pot", "geracao_kwh", "pot_kwp", "ultima_leitura")
    rows = [{k: r.get(k) for k in keys} for r in detail.values()]
    rows.sort(key=lambda x: (0 if x.get("abaixo") else 1, -(x.get("abaixo") or 0), x["usina"]))
    payload = {"rows": rows, "summary": {
        "usinas": len(rows),
        "inversores": sum(r.get("total") or 0 for r in rows),
        "abaixo": sum(r.get("abaixo") or 0 for r in rows),
        "sem_pot": sum(r.get("sem_pot") or 0 for r in rows)},
        "cache_ts": datetime.now().strftime("%H:%M:%S")}
    _pv_pr_cache["detail"] = detail
    return payload


@app.route("/api/pv/pr")
def api_pv_pr():
    """Overview de PR por inversor — só usinas string-box (sem visão real de strings)."""
    force = flask_request.args.get("force", "0") == "1"
    try:
        return jsonify(_swr(_pv_pr_cache, _build_pv_pr_payload, force))
    except Exception as e:
        return jsonify({"rows": [], "summary": {"usinas": 0, "inversores": 0, "abaixo": 0, "sem_pot": 0},
                        "erro": f"API PV indisponível: {e}", "cache_ts": datetime.now().strftime("%H:%M:%S")})


@app.route("/api/pv/pr/<int:plant_id>")
def api_pv_pr_plant(plant_id):
    d = _pv_pr_cache["detail"].get(plant_id)
    if d:
        return jsonify(d)
    token = get_token()
    try:
        plant = next((p for p in get_plants(token) if p["id"] == plant_id), None)
    except Exception:
        plant = None
    if not plant:
        return jsonify({"error": "usina não encontrada", "inversores": []}), 404
    return jsonify(_pv_pr_compute(_pv_pr_collect(token, plant), token))


# ── Curva diária de STRINGS por inversor (aba "Strings") — fonte: API PV ───────
#   Migrado da PV Plataforma (apiplataforma, protegida por CAPTCHA+MFA) para a
#   API PV (apipv): day_inverter → corrente por string (Ipv*). As strings reais são
#   filtradas com _ipv_ativas (mesma régua da visão principal, descarta canais de
#   hardware não usados) e a subperformance é detectada vs MEDIANA da corrente
#   integrada do dia. idusina/idinversor são COMPARTILHADOS com a API PV
#   (id da Plataforma == idefinversor da API PV).
SPV_SUB_FRAC   = 0.90   # string com corrente < 90% da mediana = subperformance
SPV_NOTAS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "string_notas.json")
_spv_cache     = {}     # (idusina, data) → {ts, payload}
_spv_lock      = threading.Lock()


def _spv_stnum(nome: str) -> int:
    try:
        return int("".join(c for c in str(nome) if c.isdigit()) or 999)
    except Exception:
        return 999


def _spv_is_stringbox(plant_nome_api) -> bool:
    """String-box = usina com coluna 'String Box' = Sim no BD_Performance (sem visão
    real por string). Fonte direta da planilha, sem custo de API."""
    return (plant_nome_api or "").strip() in STRING_BOX


def _spv_load_notas() -> dict:
    try:
        with open(SPV_NOTAS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _spv_save_notas(d: dict):
    try:
        tmp = SPV_NOTAS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SPV_NOTAS_PATH)
    except Exception as e:
        print(f"[SPV] erro salvando notas: {e}")


def _spv_day_records(idusina, token, data: str) -> list:
    """Leituras por inversor da usina na data. Hoje → day_inverter (rápido, completo);
    datas passadas → custom_query (best-effort, pode ser lento/timeout)."""
    H = {"x-access-token": token}
    hoje = datetime.now().strftime("%d/%m/%Y")
    if data == hoje:
        return _http().post(f"{BASE_URL}/day_inverter", headers=H,
                             json={"id": idusina}, timeout=60).json() or []
    try:
        d = datetime.strptime(data, "%d/%m/%Y")
        body = {"id": idusina, "data_type": "inverter", "period": d.strftime("%Y-%m"), "day": d.day}
        return _http().post(f"{BASE_URL}/custom_query", headers=H, json=body, timeout=120).json() or []
    except Exception:
        return []


def _spv_analise_inversor(idinv, nome, recs, data, notas, full=False) -> dict:
    """Strings reais (via _ipv_ativas no pico solar) → corrente integrada por string +
    curva (A) + subperformance vs mediana. Retorna None se não há visão de strings.
    O campo 'energia' carrega a corrente integrada do dia (índice relativo, não kWh);
    o que importa p/ subperformance é o 'pct' vs mediana, que é adimensional.
    full=True inclui TAMBÉM as strings inativas na curva (cada string ganha flag 'ativa');
    mediana/subperformance seguem só nas ativas."""
    recs = [r for r in recs if r.get("conteudojson")]
    if not recs:
        return None
    recs.sort(key=lambda r: r.get("tsleitura_new") or "")

    def _tot(r):
        cj = parse_cj(r.get("conteudojson"))
        return sum(v for k, v in cj.items()
                   if k.startswith("Ipv") and isinstance(v, (int, float)) and v > 0)

    peak    = max(recs, key=_tot)                       # pico solar = maior corrente total
    cj_peak = parse_cj(peak.get("conteudojson"))
    ipv_keys = sorted([k for k in cj_peak if k.startswith("Ipv")
                       and isinstance(cj_peak[k], (int, float))], key=_spv_stnum)
    if not ipv_keys:
        return None
    ativas = _ipv_ativas([cj_peak[k] for k in ipv_keys], em_janela=True)   # pico = sol forte
    reais  = [k for k, a in zip(ipv_keys, ativas) if a]
    if not reais:
        return None
    ativa_set = set(reais)
    plot_keys = ipv_keys if full else reais             # full = inclui inativas na curva

    soma  = {k: 0.0 for k in reais}                     # média/sub só nas ativas
    curva = {k: {"x": [], "y": []} for k in plot_keys}
    step  = max(1, len(recs) // 160)                    # downsample p/ ~160 pts na curva
    for i, r in enumerate(recs):
        cj   = parse_cj(r.get("conteudojson"))
        hhmm = (r.get("tsleitura_new") or "")[11:16]
        emt  = (i % step == 0)
        for k in plot_keys:
            v = cj.get(k)
            if isinstance(v, (int, float)):
                if k in ativa_set:
                    soma[k] += max(0.0, v)
                if emt:
                    curva[k]["x"].append(hhmm)
                    curva[k]["y"].append(round(v, 2))

    vals = sorted(soma.values())
    med  = vals[len(vals) // 2] if vals else 0.0
    avg  = sum(vals) / len(vals) if vals else 0.0
    strings, abaixo = [], 0
    for k in sorted(plot_keys, key=_spv_stnum):
        ativa = k in ativa_set
        e   = soma.get(k, 0.0)
        sub = (ativa and med > 0 and e < med * SPV_SUB_FRAC)
        if sub:
            abaixo += 1
        strings.append({"nome": f"ST {_spv_stnum(k):02d}", "ativa": ativa,
                        "energia": round(e, 1) if ativa else 0.0,
                        "pct": round(100.0 * e / med) if (ativa and med) else None, "sub": sub})
    curva_fmt = {f"ST {_spv_stnum(k):02d}": curva[k] for k in plot_keys}
    nota = notas.get(f"{data}|{idinv}", "")
    return {"id": idinv, "nome": nome, "n_strings": len(reais),
            "mediana": round(med, 1), "media": round(avg, 1), "abaixo": abaixo,
            "strings": strings, "curva": curva_fmt, "nota": nota}


@app.route("/api/spv/usinas")
def api_spv_usinas():
    """Catálogo de usinas (ids compartilhados com a API PV), EXCLUINDO string-box
    (usinas sem visão real de strings — análise por string não se aplica a elas).
    String-box é derivado do BD_Performance (ESPERADO_INV) — instantâneo, sem API."""
    try:
        plants = get_plants(get_token())
    except Exception as e:
        return jsonify({"rows": [], "erro": f"API PV indisponível: {e}"})
    plants = [p for p in plants if p["nome"].strip() in FULL_OM] if FULL_OM else plants
    rows, n_sbox = [], 0
    for p in plants:
        if _spv_is_stringbox(p["nome"]):
            n_sbox += 1
        else:
            rows.append({"id": p["id"], "usina": nome_usina(p["id"], p["nome"])})
    rows.sort(key=lambda x: x["usina"])
    return jsonify({"rows": rows, "excluidas_stringbox": n_sbox})


@app.route("/api/spv/usina/<int:idusina>")
def api_spv_usina(idusina):
    """Inversores da usina + análise de strings (curva de corrente + subperformance).
    Fonte: API PV (day_inverter hoje; custom_query p/ datas passadas). Uma chamada por
    usina traz todos os inversores — o resto é processamento das correntes Ipv*."""
    data = (flask_request.args.get("data") or datetime.now().strftime("%d/%m/%Y")).strip()
    force = flask_request.args.get("force", "0") == "1"
    full = flask_request.args.get("full", "0") == "1"   # inclui strings inativas na curva
    key = (idusina, data, full)
    agora = time.time()
    if not force:
        ent = _spv_cache.get(key)
        if ent and (agora - ent["ts"]) < CACHE_TTL:
            return jsonify(ent["payload"])
    try:
        token = get_token()
        records = _spv_day_records(idusina, token, data)
    except Exception as e:
        return jsonify({"idusina": idusina, "data": data, "inversores": [],
                        "msg": f"API PV indisponível: {e}"})
    if not records:
        return jsonify({"idusina": idusina, "data": data, "inversores": [],
                        "msg": "Sem dados de inversores para esta usina/data (API PV)."})
    # Nome da usina (p/ EQUIP_NAMES) + nomes dos dispositivos (idefinversor → nome)
    plant_nome_api = ""
    try:
        plant_nome_api = next((p["nome"].strip() for p in get_plants(token) if p["id"] == idusina), "")
    except Exception:
        pass
    dev_names = {}
    try:
        devs_raw = _http().get(f"{BASE_URL}/plant_devices", headers={"x-access-token": token},
                                json={"id": idusina}, timeout=20).json()
        devs = devs_raw
        if isinstance(devs_raw, list) and devs_raw and "plant_devices" in devs_raw[0]:
            devs = devs_raw[0]["plant_devices"]
        elif isinstance(devs_raw, dict):
            devs = devs_raw.get("plant_devices", [])
        dev_names = {d["device_id"]: str(d.get("device_name", "")).strip() for d in devs}
    except Exception:
        pass
    # Agrupa registros por inversor (filtrando à data quando o timestamp permite)
    iso = None
    try:
        iso = datetime.strptime(data, "%d/%m/%Y").strftime("%Y-%m-%d")
    except Exception:
        pass
    by_inv = {}
    for r in records:
        ts = r.get("tsleitura_new") or ""
        if iso and ts and not ts.startswith(iso):
            continue
        by_inv.setdefault(r.get("idefinversor"), []).append(r)
    notas = _spv_load_notas()
    results = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {}
        for idinv, recs in by_inv.items():
            nome_api = dev_names.get(idinv, f"INV-{idinv}")
            nome = EQUIP_NAMES.get(plant_nome_api, {}).get(nome_api, nome_api)
            futs[ex.submit(_spv_analise_inversor, idinv, nome, recs, data, notas, full)] = idinv
        for f in as_completed(futs):
            try:
                rr = f.result()
                if rr:
                    results[rr["id"]] = rr
            except Exception:
                pass
    ordem = sorted(results.values(),
                   key=lambda x: [int(p) for p in re.findall(r"\d+", x["nome"])] or [9999])
    payload = {"idusina": idusina, "data": data, "inversores": ordem,
               "total_abaixo": sum(i["abaixo"] for i in ordem),
               "cache_ts": datetime.now().strftime("%H:%M:%S")}
    _spv_cache[key] = {"ts": agora, "payload": payload}
    return jsonify(payload)


@app.route("/api/spv/nota", methods=["POST"])
def api_spv_nota():
    body = flask_request.get_json(force=True) or {}
    data = (body.get("data") or "").strip()
    idinv = body.get("idinversor")
    nota = (body.get("nota") or "").strip()
    if not data or idinv is None:
        return jsonify({"error": "data e idinversor obrigatórios"}), 400
    with _spv_lock:
        notas = _spv_load_notas()
        k = f"{data}|{idinv}"
        if nota:
            notas[k] = nota
        else:
            notas.pop(k, None)
        _spv_save_notas(notas)
    # invalida cache da data (qualquer usina) p/ refletir a nota
    for key in [k for k in _spv_cache if k[1] == data]:
        _spv_cache.pop(key, None)
    return jsonify({"ok": True})


@app.route("/api/spv/pdf")
def api_spv_pdf():
    """Relatório PDF do dia: por usina, cards de inversores com curvas + strings em
    subperformance + motivo anotado. ?data=dd/mm/aaaa e ?idusina=ID (uma usina) ou
    ?idusina=all (todas as usinas que tiverem nota OU string abaixo)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    data = (flask_request.args.get("data") or datetime.now().strftime("%d/%m/%Y")).strip()
    alvo = (flask_request.args.get("idusina") or "").strip()

    # Resolve nomes de usina (e catálogo p/ "todas")
    nomes, plants = {}, []
    try:
        plants = get_plants(get_token())
        for p in plants:
            nomes[p["id"]] = nome_usina(p["id"], p["nome"])
    except Exception:
        pass

    import textwrap
    sel = (flask_request.args.get("usinas") or "").strip()   # csv de ids escolhidos
    if sel:
        usinas_ids = [int(x) for x in sel.split(",") if x.strip().isdigit()]
        usinas_ids.sort(key=lambda i: nomes.get(i, str(i)))
    elif alvo == "todas":
        cat = [p for p in plants if (not FULL_OM or p["nome"].strip() in FULL_OM)]
        usinas_ids = [p["id"] for p in cat if not _spv_is_stringbox(p["nome"])]
        usinas_ids.sort(key=lambda i: nomes.get(i, str(i)))
    elif alvo and alvo != "all":
        usinas_ids = [int(alvo)]
    else:
        usinas_ids = [k[0] for k in _spv_cache if k[1] == data]

    from matplotlib.patches import Rectangle, FancyBboxPatch
    from matplotlib import font_manager as _fm
    import matplotlib.image as _mpimg
    _STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    # Registra qualquer .ttf/.otf de static/fonts/ e prefere Poppins (depois Satoshi);
    # senão, fallback limpo (DejaVu Sans).
    _pdf_font = "DejaVu Sans"
    try:
        _fdir = os.path.join(_STATIC, "fonts")
        if os.path.isdir(_fdir):
            for _ff in os.listdir(_fdir):
                if _ff.lower().endswith((".ttf", ".otf")):
                    _fm.fontManager.addfont(os.path.join(_fdir, _ff))
            _avail = {f.name for f in _fm.fontManager.ttflist}
            for _pref in ("Poppins", "Satoshi"):
                _hit = next((n for n in _avail if _pref.lower() in n.lower()), None)
                if _hit:
                    _pdf_font = _hit
                    break
    except Exception:
        pass
    # Logo da Grid no rodapé (horizontal, sobre branco)
    try:
        _logo = _mpimg.imread(os.path.join(_STATIC, "logos", "grid-h-verde-azul.png"))
    except Exception:
        _logo = None
    plt.rcParams.update({
        "font.family": _pdf_font, "axes.edgecolor": "#cbd5e1", "axes.linewidth": 0.7,
        "axes.labelcolor": "#64748b", "xtick.color": "#94a3b8", "ytick.color": "#94a3b8",
        "text.color": "#1f2937",
    })
    HDR, HDR_LT = "#1d4ed8", "#bfdbfe"   # cabeçalho azul Grid (antes verde) + texto azul claro
    GRAY_LN, RED, OK = "#c3cedd", "#dc2626", "#16a34a"
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    so_abaixo = flask_request.args.get("soabaixo", "0") == "1"   # só inversores com string abaixo
    CHUNK, Wtxt = 3, 46     # 3 inversores por página (charts mais largos); Wtxt = chars/linha do texto
    paginas = 0
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        for idu in usinas_ids:
            ent = _spv_cache.get((idu, data))
            if ent:
                payload = ent["payload"]
            else:
                with app.test_request_context(f"/api/spv/usina/{idu}?data={data}"):
                    payload = api_spv_usina(idu).get_json()
            invs = payload.get("inversores", [])
            if so_abaixo:
                invs = [iv for iv in invs if iv.get("abaixo")]
            if not invs:
                continue
            usina_nome = nomes.get(idu, str(idu))
            tot_abaixo = payload.get("total_abaixo", 0)
            for ini in range(0, len(invs), CHUNK):
                grupo = invs[ini:ini + CHUNK]
                fig = plt.figure(figsize=(11.69, 8.27))                  # A4 paisagem
                # ── Faixa de cabeçalho ───────────────────────────────────────
                fig.patches.append(Rectangle((0, 0.915), 1, 0.085, transform=fig.transFigure,
                                             facecolor=HDR, edgecolor="none", zorder=-1))
                fig.text(0.028, 0.953, usina_nome, color="white", fontsize=16, fontweight="bold", va="center")
                fig.text(0.028, 0.928, "Relatório de Strings  ·  corrente de cada string ao longo do dia",
                         color=HDR_LT, fontsize=8.5, va="center")
                fig.text(0.975, 0.957, data, color="white", fontsize=11.5, fontweight="bold", ha="right", va="center")
                fig.text(0.975, 0.930, f"{tot_abaixo} string(s) abaixo do esperado" if tot_abaixo else "Todas as strings dentro do esperado",
                         color=HDR_LT, fontsize=9, ha="right", va="center")
                if len(invs) > CHUNK:
                    fig.text(0.5, 0.892, f"Inversores {ini+1}–{ini+len(grupo)} de {len(invs)}",
                             color="#94a3b8", fontsize=8, ha="center", style="italic")
                gs = fig.add_gridspec(2, CHUNK, height_ratios=[2.0, 1.6], hspace=0.40, wspace=0.16,
                                      left=0.034, right=0.985, top=0.85, bottom=0.09)
                for j in range(CHUNK):
                    axc = fig.add_subplot(gs[0, j]); axt = fig.add_subplot(gs[1, j]); axt.axis("off")
                    if j >= len(grupo):
                        axc.axis("off"); continue
                    iv = grupo[j]
                    # cartão de fundo (estilo dos cards do ETM)
                    pc, ptx = axc.get_position(), axt.get_position()
                    fig.add_artist(FancyBboxPatch(
                        (pc.x0 - 0.013, ptx.y0 - 0.016),
                        (pc.x1 - pc.x0) + 0.026, (pc.y1 - ptx.y0) + 0.052,
                        boxstyle="round,pad=0,rounding_size=0.012", transform=fig.transFigure,
                        facecolor="#fbfcfe", edgecolor="#e6e9f0", linewidth=0.9, zorder=-3))
                    # faixa colorida no topo do card (estilo border-top dos cards do ETM)
                    _cx0 = pc.x0 - 0.013; _cw = (pc.x1 - pc.x0) + 0.026
                    _ctop = (ptx.y0 - 0.016) + (pc.y1 - ptx.y0) + 0.052
                    fig.add_artist(Rectangle((_cx0 + 0.006, _ctop - 0.007), _cw - 0.012, 0.005,
                                   transform=fig.transFigure, facecolor=(RED if iv["abaixo"] else OK),
                                   edgecolor="none", zorder=-2))
                    subnames = {s["nome"] for s in iv["strings"] if s["sub"]}
                    xs = next(iter(iv["curva"].values()))["x"] if iv["curva"] else []
                    for st, c in iv["curva"].items():                    # normais ao fundo
                        if st not in subnames:
                            axc.plot(c["x"], c["y"], lw=0.5, color=GRAY_LN, alpha=0.85, zorder=1)
                    for st, c in iv["curva"].items():                    # outliers por cima
                        if st in subnames:
                            axc.plot(c["x"], c["y"], lw=1.3, color=RED, zorder=3)
                    axc.set_title(iv["nome"], fontsize=10, fontweight="bold", pad=7,
                                  color=RED if iv["abaixo"] else "#0f172a")
                    axc.spines[["top", "right"]].set_visible(False)
                    axc.grid(axis="y", color="#eef2f7", lw=0.8, zorder=0)
                    axc.set_ylim(bottom=0); axc.margins(x=0.01)
                    axc.tick_params(labelsize=6.5, length=2, color="#cbd5e1")
                    if xs:
                        step = max(1, len(xs) // 4)
                        axc.set_xticks(range(0, len(xs), step)); axc.set_xticklabels(xs[::step], fontsize=6.5)
                    # ── Observações do inversor ──────────────────────────────
                    status = f"Referência (mediana): {iv['mediana']}   ·   " + (f"{iv['abaixo']} abaixo" if iv["abaixo"] else "todas OK")
                    axt.text(0, 1.0, status, transform=axt.transAxes, va="top", ha="left",
                             fontsize=8, fontweight="bold", color=RED if iv["abaixo"] else OK)
                    outs = ", ".join(f"{s['nome']}: {s['pct']}%" for s in iv["strings"] if s["sub"]) or "nenhuma"
                    y = 0.80
                    axt.text(0, y, "Strings abaixo (% da referência):", transform=axt.transAxes, va="top", fontsize=7,
                             fontweight="bold", color="#64748b"); y -= 0.115
                    for ln in textwrap.wrap(outs, Wtxt)[:3]:
                        axt.text(0, y, ln, transform=axt.transAxes, va="top", fontsize=6.8, color="#475569"); y -= 0.115
                    y -= 0.05
                    axt.text(0, y, "Motivo (preenchido pela análise):", transform=axt.transAxes, va="top", fontsize=7,
                             fontweight="bold", color="#64748b"); y -= 0.115
                    for ln in textwrap.wrap(iv["nota"] or "sem observação registrada", Wtxt)[:3]:
                        axt.text(0, y, ln, transform=axt.transAxes, va="top", fontsize=6.8,
                                 color="#7c3aed" if iv["nota"] else "#9ca3af"); y -= 0.115
                # ── Rodapé ───────────────────────────────────────────────────
                fig.patches.append(Rectangle((0.052, 0.062), 0.923, 0.0012, transform=fig.transFigure,
                                             facecolor="#e5e7eb", edgecolor="none"))
                if _logo is not None:
                    _lax = fig.add_axes([0.028, 0.016, 0.12, 0.038]); _lax.axis("off"); _lax.imshow(_logo)
                else:
                    fig.text(0.028, 0.036, "Grid Co.  ·  Monitoramento O&M", color="#94a3b8", fontsize=7.5, va="center")
                fig.text(0.5, 0.036, "linha cinza = strings normais   ·   linha vermelha = string abaixo do esperado   ·   referência = mediana da corrente acumulada no dia",
                         color="#94a3b8", fontsize=7.5, ha="center", va="center")
                fig.text(0.975, 0.036, f"Gerado em {agora}", color="#94a3b8", fontsize=7.5, ha="right", va="center")
                pdf.savefig(fig, facecolor="white"); plt.close(fig)
                paginas += 1
    buf.seek(0)
    if paginas == 0:
        return jsonify({"error": "Nada para exportar (selecione ao menos uma usina com inversores)."}), 400
    fname = f"strings_{data.replace('/','-')}.pdf"
    return send_file(buf, as_attachment=True, download_name=fname, mimetype="application/pdf")


@app.route("/api/check/reload", methods=["POST", "GET"])
def api_check_reload():
    """Recarrega o cadastro (BD_Performance) se ele mudou (chamado pelo botão Atualizar)."""
    antes = _bd_mtime
    maybe_reload_equipamentos()
    return jsonify({
        "reloaded": _bd_mtime != antes,
        "inversores": sum(len(v) for v in ESPERADO_INV.values()),
        "usinas_esperadas": len(ESPERADO),
        "full_om": len(FULL_OM),
    })


def _owen_loop():
    """Mescla os CSVs no acervo do dia periodicamente — captura cada janela (3h) antes do
    próximo e-mail sobrescrever o arquivo, mesmo sem ninguém abrir a aba."""
    print("[2C/Owen] acumulador iniciado (refresh a cada 10 min)")
    while True:
        try:
            _owen_refresh(force=True)
        except Exception as e:
            print(f"[2C/Owen] loop erro: {e}")
        time.sleep(600)


def _sunop_keepalive_loop():
    """Mantém o token do SunOp sempre vivo: chama get_sunop_token() (que valida e, se
    preciso, renova via /refresh_token) a cada 6 h — bem dentro da janela de ~7 dias.
    Enquanto o servidor estiver de pé, nunca precisa colar token novo manualmente."""
    print("[SunOp] keep-alive iniciado (renova token a cada 6 h)")
    while True:
        time.sleep(21600)   # 6 horas
        try:
            get_sunop_token()
        except Exception as e:
            print(f"[SunOp] keep-alive erro: {e}")


def _prewarm_loop():
    """Mantém TODAS as abas quentes: o /api/data (aba padrão e a mais lenta) é
    reaquecido a cada ciclo; as demais fontes são reconstruídas EM SÉRIE quando o
    cache delas está perto de expirar (os acessos dos usuários via SWR já ajudam a
    manter quente — aqui é a rede de segurança pra ninguém pegar busca fria)."""
    import time as _t
    _t.sleep(5)
    while True:
        t0 = _t.time()
        try:
            _refresh_data_cache()
            print(f"[prewarm] /api/data aquecido em {_t.time()-t0:.0f}s")
        except Exception as e:
            print(f"[prewarm] erro: {e}")
        outros = [
            ("ETM",            _etm_cache,           _build_etm_payload),
            ("ETM análise",    _etm_analise_cache,   _build_etm_analise_payload),
            ("SunOp",          _sunop_cache,         _build_sunop_payload),
            ("SunOp ETM",      _sunop_etm_cache,     _build_sunop_etm_payload),
            ("SunOp ETM anál", _sunop_analise_cache, _build_sunop_analise_payload),
            ("SunOp trackers", _sunop_trk_cache,     _build_sunop_trk_payload),
            ("SolarEdge",      _se_cache,            _build_se_payload),
            ("PG ETM",         _pg_etm_cache,        _build_pg_etm_payload),
            ("PG ETM análise", _pg_analise_cache,    _build_pg_analise_payload),
            ("PG trackers",    _pg_trk_cache,        _pg_trackers_overview),
            ("PV PR",          _pv_pr_cache,         _build_pv_pr_payload),
        ]
        if _plat_token():
            outros.append(("PV trackers", _pv_trk_cache, _build_pv_trk_payload))
        for nome, cache, build in outros:
            if (_t.time() - cache.get("ts", 0.0)) < CACHE_TTL - 30:
                continue                      # ainda fresco (usuário acabou de buscar)
            lock = cache.setdefault("_lock", threading.Lock())
            if not lock.acquire(blocking=False):
                continue                      # já tem refresh em andamento
            try:
                t1 = _t.time()
                cache["payload"] = build()
                cache["ts"] = _t.time()
                _persist_mark()
                print(f"[prewarm] {nome} aquecido em {_t.time()-t1:.0f}s")
            except Exception as e:
                print(f"[prewarm] {nome} falhou: {e}")
            finally:
                lock.release()
        try:
            _pg_get_snapshot()                # PG strings (snapshot) também sempre quente
        except Exception as e:
            print(f"[prewarm] PG snapshot falhou: {e}")
        _t.sleep(max(60, CACHE_TTL - 30))   # reaquece antes de expirar (~4,5 min)


# ── Persistência dos caches em disco ───────────────────────────────────────────
# Os caches vivem em memória; sem isto, um reinício do servidor perde tudo e todo
# mundo pega carga fria. O loop salva um snapshot por minuto (quando algo mudou) e
# o boot recarrega: o dashboard volta servindo o último dado conhecido na hora,
# enquanto o prewarm/SWR busca dado fresco em fundo.
_PERSIST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache_snapshot.json")


def _persist_registry():
    return {
        "data":          _cache,
        "etm":           _etm_cache,
        "etm_analise":   _etm_analise_cache,
        "sunop":         _sunop_cache,
        "sunop_etm":     _sunop_etm_cache,
        "sunop_analise": _sunop_analise_cache,
        "sunop_trk":     _sunop_trk_cache,
        "pv_trk":        _pv_trk_cache,
        "se":            _se_cache,
        "pg_etm":        _pg_etm_cache,
        "pg_analise":    _pg_analise_cache,
        "pg_trk":        _pg_trk_cache,
        "pv_pr":         _pv_pr_cache,
    }


def _cache_save():
    data = {"saved_at": time.time(),
            "last_known": _last_known,
            "trk_accum": _trk_accum,
            "pg": {"summary": _pg_cache["summary"], "detail": _pg_cache["detail"],
                   "ts": _pg_cache["ts"]},
            "caches": {}}
    for nome, c in _persist_registry().items():
        data["caches"][nome] = {k: v for k, v in c.items() if not k.startswith("_")}
    tmp = _PERSIST_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=str)
    os.replace(tmp, _PERSIST_PATH)


def _int_keys(d):
    return {int(k): v for k, v in (d or {}).items() if str(k).lstrip("-").isdigit()}


def _cache_load():
    if not os.path.exists(_PERSIST_PATH):
        return
    try:
        with open(_PERSIST_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[persist] snapshot ilegível ({e}) — começando frio")
        return
    n = 0
    for nome, c in _persist_registry().items():
        saved = (data.get("caches") or {}).get(nome)
        if saved and saved.get("payload") is not None:
            c.update(saved)
            n += 1
    # chaves int viram str no JSON — restaura
    _pv_pr_cache["detail"] = _int_keys(_pv_pr_cache.get("detail"))
    _last_known.update(_int_keys(data.get("last_known")))
    saved_trk = data.get("trk_accum")
    if isinstance(saved_trk, dict) and saved_trk.get("plants") is not None:
        _trk_accum.update(saved_trk)
    pg = data.get("pg") or {}
    if pg.get("summary") is not None:
        _pg_cache.update({"summary": pg["summary"], "detail": _int_keys(pg.get("detail")),
                          "ts": pg.get("ts", 0.0)})
        n += 1
    idade = (time.time() - data.get("saved_at", 0)) / 60
    print(f"[persist] snapshot carregado: {n} caches restaurados ({idade:.0f} min atrás) — "
          f"servindo último dado conhecido enquanto o prewarm atualiza")


def _persist_loop():
    while True:
        time.sleep(60)
        if not _persist_flag["dirty"]:
            continue
        try:
            _persist_flag["dirty"] = False
            _cache_save()
        except Exception as e:
            print(f"[persist] save falhou: {e}")


if __name__ == "__main__":
    _cache_load()
    threading.Thread(target=_owen_loop, daemon=True).start()
    threading.Thread(target=_sunop_keepalive_loop, daemon=True).start()
    threading.Thread(target=_prewarm_loop, daemon=True).start()
    threading.Thread(target=_persist_loop, daemon=True).start()
    if _graph_enabled():
        threading.Thread(target=_graph_loop, daemon=True).start()
    else:
        print("[graph] desativado (faltam AZ_*/GRAPH_* no .env) — BD_Performance via OneDrive/local")
    try:
        from waitress import serve
        print("[server] waitress em http://0.0.0.0:5050 (threads=16)")
        serve(app, host="0.0.0.0", port=5050, threads=16)
    except ImportError:
        print("[server] waitress não instalado — usando o servidor de dev do Flask")
        app.run(debug=False, port=5050, threaded=True)
