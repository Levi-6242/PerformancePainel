import os
import re
import unicodedata
import calendar
import io
import csv
import time
import json
import shutil
import subprocess
import tempfile
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
    # Renovação do token da Plataforma (trackers): o bookmarklet roda na origem
    # plataforma.pvoperation.com (cross-origin, SEM sessão do dashboard) → precisa passar pelo gate.
    # Seguro: o handler só aceita um JWT válido (3 partes) e grava só o token da fonte de trackers.
    if p == "/api/pv/trackers/token":
        return
    if session.get("auth"):
        return
    if p.startswith("/api/"):
        return jsonify({"error": "não autenticado"}), 401
    return redirect("/login")


@app.after_request
def _no_cache_html(resp):
    """HTML sempre revalidado — assim atualização de código (ex.: nova sub-aba) aparece sem precisar
    de hard-refresh; evita o navegador servir uma versão antiga da página pelo túnel."""
    if resp.headers.get("Content-Type", "").startswith("text/html"):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


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


def _tokens_status():
    """Validade dos tokens externos — alimenta o aviso de vencimento no dashboard.
    Só tokens MANUAIS (Plataforma) e auto-renováveis (SunOp/Athon, Axis) disparam alerta;
    os de login automático (API PV, SolarEdge) renovam sozinhos e só aparecem como info."""
    agora = time.time()

    def _row(nome, fonte, exp, tipo, dica=""):
        dias = (exp - agora) / 86400.0 if exp else None
        if not exp:
            st = "desconhecido"
        elif exp <= agora:
            st = "vencido"
        elif tipo == "manual" and dias < 3:
            st = "atencao"
        else:
            st = "ok"   # auto-renova (SunOp/Axis): renova sozinho pelo keepalive → só alerta se VENCIDO
        if tipo == "auto-login":          # login com usuário/senha: se cura sozinho → nunca alerta
            st = "auto"
        return {"nome": nome, "fonte": fonte, "tipo": tipo,
                "exp": datetime.fromtimestamp(exp).strftime("%d/%m/%Y %H:%M") if exp else None,
                "dias": round(dias, 1) if dias is not None else None, "status": st, "dica": dica}

    rows = [
        _row("Plataforma (trackers)", "plat", _jwt_exp(_plat_token()), "manual",
             "Renove pelo bookmarklet de 1 clique (logado em plataforma.pvoperation.com)."),
        _row("SunOp / Athon", "sunop", _jwt_exp(_sunop_token.get("token", "")), "auto-renova",
             "Renova sozinho; só recolar SUNOP_TOKEN no .env se o servidor ficou dias desligado."),
        _row("Axis SunOp", "axis", _jwt_exp(_axis_token.get("token", "")), "auto-renova",
             "Renova sozinho; recolar AXIS_TOKEN no .env ou axis_token.txt se ficar dias desligado."),
        _row("SolarEdge", "solaredge", _se_cookie.get("exp", 0.0), "auto-login", ""),
        _row("API PV", "apipv", _pv_token.get("exp", 0.0), "auto-login", ""),
    ]
    alerta = [r for r in rows if r["status"] in ("vencido", "atencao")]
    partes = []
    for r in alerta:
        quando = "VENCIDO" if r["status"] == "vencido" else f"vence em {r['dias']}d"
        partes.append(f"{r['nome']}: {quando}")
    return {"tokens": rows, "alerta": bool(alerta), "msg": "; ".join(partes)}


@app.route("/api/tokens")
def api_tokens():
    return jsonify(_tokens_status())


BASE_URL = "https://apipv.pvoperation.com.br/api/v1"
USERNAME = os.environ.get("PV_USERNAME", "")
PASSWORD = os.environ.get("PV_PASSWORD", "")
STRING_ATIVA_FRAC      = 0.30   # API PV + SunOp (FORA de 9-15h): ativa se corrente >= isto × média(produzindo)
STRING_JANELA_MIN_A    = 1.0    # API PV + SunOp (DENTRO de 9-15h): ativa se corrente > isto (A)
STRING_JANELA_INI      = 9      # hora inicial da janela de sol confiável (inclusiva)
STRING_JANELA_FIM      = 15     # hora final da janela de sol confiável (exclusiva)
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
ETM_LATE_WARN_MIN  = 15    # ETM: última leitura atrasando (entre isto e COMM_ALERT_MINUTES, de dia) = possível falta (atenção)
ETM_GAP_WARN_MIN   = 30    # ETM: buraco na série durante o dia (min) = possível falta (atenção)
ETM_DIA_INI, ETM_DIA_FIM = 6, 18   # janela diurna em que a estação deveria estar reportando
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
SUNOP_TOKEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sunop_token.txt")


def _jwt_exp(tok: str) -> float:
    """exp (epoch) de um JWT, sem validar assinatura. 0 se não der p/ ler."""
    try:
        import base64
        pl = tok.split(".")[1]; pl += "=" * (-len(pl) % 4)
        return float(json.loads(base64.urlsafe_b64decode(pl)).get("exp", 0) or 0)
    except Exception:
        return 0.0


def _sunop_token_inicial(env_var: str = "SUNOP_TOKEN", path: str = None) -> str:
    """Token de MAIOR validade entre o persistido (arquivo, renovado sozinho pelo /refresh_token)
    e o do .env (semente manual). env_var/path parametrizados p/ múltiplas instâncias (gridco/axis)."""
    path = path or SUNOP_TOKEN_PATH
    env_tok = os.environ.get(env_var, "")
    file_tok = ""
    try:
        with open(path, encoding="utf-8") as f:
            file_tok = f.read().strip()
    except Exception:
        pass
    return file_tok if _jwt_exp(file_tok) > _jwt_exp(env_tok) else env_tok


# ── Instâncias SunOp: gridco (Athon, default) e axis ──────────────────────────
# A MESMA API (analog_values/plants/metadata) serve as duas; só mudam URL/token/meta/caches.
# Todas as funções SunOp recebem inst="gridco" por padrão → o Athon ao vivo fica IDÊNTICO.
AXIS_CONFIG     = "https://axis-api.sunop.net/api"
AXIS_DATA       = "https://axis-api.sunop.net/data"
AXIS_TOKEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "axis_token.txt")

_sunop_token     = {"token": _sunop_token_inicial("SUNOP_TOKEN", SUNOP_TOKEN_PATH)}
_sunop_meta      = {}        # plant_name → metadata dict
_sunop_cache     = {"payload": None, "ts": 0.0}
_sunop_etm_cache = {"payload": None, "ts": 0.0}

_axis_token       = {"token": _sunop_token_inicial("AXIS_TOKEN", AXIS_TOKEN_PATH)}
_axis_meta        = {}
_axis_cache       = {"payload": None, "ts": 0.0}
_axis_etm_cache   = {"payload": None, "ts": 0.0}
_axis_curva_cache = {}
_axis_str_med_cache = {}
_axis_trk_cache   = {"payload": None, "ts": 0.0}
_axis_trk_hist    = {}
_axis_pr_cache    = {}
_axis_analise_cache = {"payload": None, "ts": 0.0}


def _si(inst: str = "gridco") -> dict:
    """Estado da instância SunOp (URLs + token + meta + caches). gridco = Athon (default)."""
    if inst == "axis":
        return {"config": AXIS_CONFIG, "data": AXIS_DATA, "token_path": AXIS_TOKEN_PATH,
                "env": "AXIS_TOKEN", "token": _axis_token, "meta": _axis_meta,
                "cache": _axis_cache, "etm_cache": _axis_etm_cache,
                "curva_cache": _axis_curva_cache, "str_med_cache": _axis_str_med_cache,
                "trk_cache": _axis_trk_cache, "trk_hist": _axis_trk_hist, "pr_cache": _axis_pr_cache,
                "analise_cache": _axis_analise_cache}
    return {"config": SUNOP_CONFIG, "data": SUNOP_DATA, "token_path": SUNOP_TOKEN_PATH,
            "env": "SUNOP_TOKEN", "token": _sunop_token, "meta": _sunop_meta,
            "cache": _sunop_cache, "etm_cache": _sunop_etm_cache,
            "curva_cache": _sunop_curva_cache, "str_med_cache": _sunop_str_med_cache,
            "trk_cache": _sunop_trk_cache, "trk_hist": _sunop_trk_hist, "pr_cache": _sunop_pr_cache,
            "analise_cache": _sunop_analise_cache}


def _sunop_persist(tok: str, inst: str = "gridco"):
    try:
        with open(_si(inst)["token_path"], "w", encoding="utf-8") as f:
            f.write(tok)
    except Exception:
        pass

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

def _bd_perf_path() -> str:
    """Caminho do BD_Performance — prioridade: (1) versão ONLINE do OneDrive;
    (2) cópia local como último recurso. Reavaliado a cada carga."""
    for p in _BD_PERF_ONLINE_CANDS:
        if os.path.exists(p):
            return p
    return _BD_PERF_LOCAL


_BD_TMP = os.path.join(tempfile.gettempdir(), "bd_perf_dashboard.xlsx")


def _bd_readable_path():
    """Caminho LEGÍVEL do BD_Performance: copia para uma cópia temporária (contorna o lock
    do Excel/OneDrive quando o arquivo está aberto) e devolve a cópia. Se a cópia falhar,
    devolve o original (o chamador trata o erro). O mtime do cache continua vindo do original."""
    src = _bd_perf_path()
    try:
        shutil.copy2(src, _BD_TMP)
        return _BD_TMP
    except Exception:
        return src

# Globais preenchidas por load_equipamentos() (recarregáveis em runtime)
ESPERADO_INV  = {}   # {usina_sup: {equip_sup: strings_esperadas}}
EQUIP_NAMES   = {}   # {usina_sup: {equip_sup: equipamento_display}}
USINA_DISPLAY = {}   # {usina_sup: usina_display}
USINA_GRUPO   = {}   # {usina_sup: usina_fisica} — SEM dedup; agrupa sub-usinas (Indaiatuba 1-4 → "Indaiatuba")
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
    global ESPERADO_INV, EQUIP_NAMES, USINA_DISPLAY, USINA_GRUPO, ESPERADO, FULL_OM, STRING_BOX, POWER_INV, _bd_mtime
    try:
        path = _bd_perf_path()
        df = pd.read_excel(_bd_readable_path(), sheet_name="Equipamentos", header=2)
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

        # Mapa p/ AGRUPAR sub-usinas (Indaiatuba 1-4, Ceilândia II - *, Céu Azul I/II/III…) pela
        # usina física — guardado ANTES da dedup abaixo (que descarta justamente os agrupados).
        usina_grupo = dict(usina_display)
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
        USINA_GRUPO = usina_grupo
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


# ── BD_Trackers (aba do BD_Performance): relação tracker ↔ inversor (começou no Thopen) ──
BD_TRK_INV    = {}   # {nrm(usina_sup): {tracker_num(int): inversor_sup}}
INV_TRK       = {}   # {nrm(usina_sup): {nrm(inversor_sup): [tracker_nums]}}
BD_TRK_USINAS = set()  # nrm(usina_sup) cobertas pela planilha


def _findcol_exact(cols, *names):
    low = {str(c).strip().lower(): c for c in cols}
    for n in names:
        if n.lower() in low:
            return low[n.lower()]
    return None


def _nome_base(s):
    """Nome 'base' p/ casar usinas entre fontes que usam ids diferentes: remove '(id)' do INÍCIO
    (PG: '(289) Nome') e do FIM (BD/API PV: 'Nome (73)') e normaliza."""
    s = str(s or "")
    s = re.sub(r"^\s*\(\d+\)\s*", "", s)
    s = re.sub(r"\s*\(\d+\)\s*$", "", s)
    return _nrm(s.strip())


def load_bd_trackers():
    """Carrega a aba 'BD_Trackers' (tracker↔inversor por usina). Chaveado por NOME-BASE (sem id)
    p/ casar com o PG; inversor pela coluna 'Inversor' (display, ex.: 'Inversor 1.1' = device_name
    do PG). Tolerante a usina FORA da planilha (R-10 degrada, não quebra)."""
    global BD_TRK_INV, INV_TRK, BD_TRK_USINAS
    try:
        df = pd.read_excel(_bd_readable_path(), sheet_name="BD_Trackers", header=2)
    except Exception as e:
        print(f"[AVISO] BD_Trackers não carregado: {e}")
        return
    c_us  = _findcol_exact(df.columns, "Usina Supervisório", "Usina Supervisorio")
    c_ivd = _findcol_exact(df.columns, "Inversor")                      # display (= device_name PG)
    c_ivs = _findcol_exact(df.columns, "Inversor Supervisório", "Inversor Supervisorio")
    c_trk = _findcol_exact(df.columns, "Tracker")
    if not (c_us and c_trk and (c_ivd or c_ivs)):
        print(f"[AVISO] BD_Trackers sem as colunas esperadas — achei {list(df.columns)[:9]}")
        return
    bd, inv_trk, usinas = {}, {}, set()
    for _, row in df.iterrows():
        us, tk = row[c_us], row[c_trk]
        iv = row[c_ivd] if (c_ivd and pd.notna(row[c_ivd])) else (row[c_ivs] if c_ivs else None)
        if pd.isna(us) or iv is None or pd.isna(iv) or pd.isna(tk):
            continue
        usn, ivs = _nome_base(us), str(iv).strip()
        try:
            tkn = int(float(tk))
        except (TypeError, ValueError):
            continue
        bd.setdefault(usn, {})[tkn] = ivs
        inv_trk.setdefault(usn, {}).setdefault(_nrm(ivs), []).append(tkn)
        usinas.add(usn)
    BD_TRK_INV, INV_TRK, BD_TRK_USINAS = bd, inv_trk, usinas
    print(f"[OK] BD_Trackers: {len(usinas)} usinas | "
          f"{sum(len(v) for v in bd.values())} trackers mapeados a inversores")


def _bd_trk_offset(bdm):
    """Offset da numeração da planilha p/ a LOCAL da fonte (TRK1..N). A aba às vezes numera o
    COMPLEXO inteiro em sequência por sub-usina (Céu Azul III = 41..60, Altair 5 = 90..113): se o
    mapa da usina-supervisório não começa em 1, o nº local n corresponde ao (n + menor - 1)."""
    if not bdm:
        return 0
    lo = min(bdm)
    return (lo - 1) if lo > 1 else 0


def _bd_trk_lookup(nome_raw, num):
    """Inversor do tracker `num` (numeração LOCAL da fonte) na usina `nome_raw` — tenta direto e
    com o offset da planilha. None se não mapeado."""
    if num is None:
        return None
    bdm = BD_TRK_INV.get(_nome_base(nome_raw)) or {}
    if num in bdm:
        return bdm[num]
    off = _bd_trk_offset(bdm)
    return bdm.get(num + off) if off else None


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
        load_bd_trackers()


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


# Estado → região do Brasil. Chave = nome do estado NORMALIZADO (sem acento/minúsculo), então
# cobre "São Paulo"/"Sao Paulo", siglas (SP) e nomes completos. Derivado no código (não gravamos
# no BD_Performance, que é o mestre da plataforma + Power BI). Usado p/ agrupar por região no painel
# e planejar rondas de trackers por proximidade geográfica.
_UF_REGIAO = {
    "norte":        ["AC", "Acre", "AP", "Amapa", "AM", "Amazonas", "PA", "Para", "RO", "Rondonia",
                     "RR", "Roraima", "TO", "Tocantins"],
    "nordeste":     ["AL", "Alagoas", "BA", "Bahia", "CE", "Ceara", "MA", "Maranhao", "PB", "Paraiba",
                     "PE", "Pernambuco", "PI", "Piaui", "RN", "Rio Grande do Norte", "SE", "Sergipe"],
    "centro-oeste": ["DF", "Distrito Federal", "GO", "Goias", "MT", "Mato Grosso",
                     "MS", "Mato Grosso do Sul"],
    "sudeste":      ["ES", "Espirito Santo", "MG", "Minas Gerais", "RJ", "Rio de Janeiro",
                     "SP", "Sao Paulo"],
    "sul":          ["PR", "Parana", "RS", "Rio Grande do Sul", "SC", "Santa Catarina"],
}
_ESTADO2REGIAO = {_nrm(n): reg.capitalize().replace("Centro-oeste", "Centro-Oeste")
                  for reg, nomes in _UF_REGIAO.items() for n in nomes}


def _regiao_do_estado(estado):
    """Nome da região (Norte/Nordeste/Centro-Oeste/Sudeste/Sul) a partir do estado. None se não mapear."""
    if not estado:
        return None
    return _ESTADO2REGIAO.get(_nrm(str(estado).strip()))


def load_metas():
    """(Re)carrega as METAS das abas 'Info Geral' e 'Info Mensal' do BD_Performance.
    Preenche INFO_GERAL (por usina) e PR_PREVISTO (por usina × mês). Mesma fonte do
    cadastro, então é recarregada junto pelo mtime."""
    global INFO_GERAL, PR_PREVISTO, _metas_mtime
    try:
        path = _bd_perf_path()
        rd = _bd_readable_path()

        # --- Info Geral (cabeçalho na 1ª linha) ---
        dg = pd.read_excel(rd, sheet_name="Info Geral", header=0)
        dg.columns = [str(c).strip() for c in dg.columns]
        gc_us  = _col(dg.columns, "usina")
        gc_kwp = _col(dg.columns, "potencia", "kwp")
        gc_mwp = _col(dg.columns, "potencia", "mwp")
        gc_deg = _col(dg.columns, "degrada")
        gc_inv = _col(dg.columns, "quantidade", "inversor")
        gc_p50 = _col(dg.columns, "p50")
        gc_cli = _col(dg.columns, "cliente")
        gc_est = _col(dg.columns, "estado")
        gc_reg = _col(dg.columns, "regi")     # coluna "Região" da Info Geral (Levi 03/07): fonte
        info = {}                             # OFICIAL p/ ronda/agrupamentos; UF→região é só fallback
        for _, r in dg.iterrows():
            if not gc_us or pd.isna(r[gc_us]):
                continue
            u = str(r[gc_us]).strip()
            if not u:
                continue
            estado = str(r[gc_est]).strip() if gc_est and pd.notna(r[gc_est]) else None
            regiao = str(r[gc_reg]).strip() if gc_reg and pd.notna(r[gc_reg]) else ""
            info[_nrm(u)] = {
                "usina":        u,
                "cliente":      str(r[gc_cli]).strip() if gc_cli and pd.notna(r[gc_cli]) else None,
                "estado":       estado,
                "regiao":       regiao or _regiao_do_estado(estado),
                "potencia_kwp": _num(r[gc_kwp]) if gc_kwp else None,
                "potencia_mwp": _num(r[gc_mwp]) if gc_mwp else None,
                "degradacao":   (_num(r[gc_deg]) or 0.0) if gc_deg else 0.0,
                "qtd_inv":      _num(r[gc_inv]) if gc_inv else None,
                "p50_mwh":      _num(r[gc_p50]) if gc_p50 else None,
            }

        # --- Info Mensal (cabeçalho na 2ª linha; 1ª coluna é índice em branco) ---
        dm = pd.read_excel(rd, sheet_name="Info Mensal", header=1)
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


# ── Meta de geração das usinas do BANCO (Thopen): BD_Thopen.xlsx, tabela Historico_2026 ──
# O P50/meta das usinas do banco NÃO está no BD_Performance (o Info Mensal cobre outras carteiras);
# mora aqui — MESMA fonte do dashboard_thopen. {nrm(usina): {mes_int: {meta_mwh, ipoa_meta, pr_meta}}}.
THOPEN_META = {}
_BD_THOPEN_CANDS = [
    os.environ.get("BD_THOPEN_PATH"),
    r"C:\Users\Levi Maia\OneDrive - GRID CO\Grid Co_ - 17. Acesso Externo Thopen\1. Registro usinas Thopen\BD_Thopen.xlsx",
    r"C:\Users\Levi Maia\OneDrive - GRID CO\BD_Thopen.xlsx",
    r"C:\Users\Levi Maia\OneDrive - GRID CO\Área de Trabalho\BD_Thopen.xlsx",
]


def _bd_thopen_path():
    for p in _BD_THOPEN_CANDS:
        if p and os.path.exists(p):
            return p
    return None


def load_thopen_meta():
    """Lê a tabela nomeada Historico_2026 (meta kWh / irradiância-meta / PR por usina×mês)."""
    global THOPEN_META
    path = _bd_thopen_path()
    if not path:
        print("[AVISO] BD_Thopen.xlsx não encontrado — meta gerencial do banco ficará vazia")
        return
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True)
        sheet = ref = None
        for ws in wb.worksheets:
            if "Historico_2026" in ws.tables:
                sheet, ref = ws, ws.tables["Historico_2026"].ref
                break
        if not ref:
            wb.close(); print("[AVISO] tabela Historico_2026 não achada no BD_Thopen"); return
        cells = list(sheet[ref])
        hdr = [str(c.value).strip().lower() if c.value is not None else "" for c in cells[0]]

        def ci(*needles):
            for i, h in enumerate(hdr):
                if any(n in h for n in needles):
                    return i
            return None
        iU, iMes, iMeta, iIrr, iPR = ci("usina"), ci("mês", "mes"), ci("meta"), ci("irradia"), ci("pr")
        out = {}
        for row in cells[1:]:
            v = [c.value for c in row]
            u = v[iU] if iU is not None else None
            if not u:
                continue
            mv = v[iMes] if iMes is not None else None
            m = mv.month if hasattr(mv, "month") else (int(mv) if isinstance(mv, (int, float)) else None)
            if not m:
                continue
            meta = v[iMeta] if (iMeta is not None and isinstance(v[iMeta], (int, float))) else None
            meta_mwh = (meta / 1000.0 if (meta and meta > 10000) else meta)   # auto kWh→MWh
            out.setdefault(_nrm(str(u).strip()), {})[int(m)] = {
                "meta_mwh": meta_mwh,
                "ipoa_meta": float(v[iIrr]) if (iIrr is not None and isinstance(v[iIrr], (int, float))) else None,
                "pr_meta": float(v[iPR]) if (iPR is not None and isinstance(v[iPR], (int, float))) else None,
            }
        wb.close()
        THOPEN_META = out
        print(f"[OK] BD_Thopen/Historico_2026: {len(out)} usinas com meta (gerencial)")
    except Exception as e:
        print(f"[AVISO] BD_Thopen meta não carregado: {e}")


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
load_thopen_meta()    # meta de geração do BANCO/Thopen (BD_Thopen / Historico_2026)
load_bd_trackers()    # carga inicial da relação tracker↔inversor (aba BD_Trackers)


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


_plants_cache = {"ts": 0.0, "data": None}   # lista de usinas (id/nome) — muda raramente
_plants_lock  = threading.Lock()


def get_plants(token: str, force=False) -> list:
    """Lista de usinas da API PV, cacheada por CACHE_TTL. A relação de usinas muda
    raramente, mas vários endpoints a consultam UMA VEZ POR USINA (a aba Curva das
    strings rebaixava /plants ~108×, uma por usina, a cada abertura). O dado DENTRO de
    cada usina segue buscado fresco nos outros endpoints — aqui só evitamos repetir o
    download da lista inteira."""
    now = time.time()
    if not force and _plants_cache["data"] is not None and (now - _plants_cache["ts"]) < CACHE_TTL:
        return _plants_cache["data"]
    with _plants_lock:
        if not force and _plants_cache["data"] is not None and (time.time() - _plants_cache["ts"]) < CACHE_TTL:
            return _plants_cache["data"]
        r = _http().get(f"{BASE_URL}/plants", headers={"x-access-token": token}, timeout=30)
        data = r.json()
        if isinstance(data, list) and data:        # só cacheia resposta válida e não vazia
            _plants_cache["data"], _plants_cache["ts"] = data, time.time()
        return data


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

    # by_inv = TODOS os registros do dia por inversor (precisa p/ o fallback "último com Ipv")
    by_inv, latest = {}, {}
    for rec in records:
        inv_id = rec.get("idefinversor")
        by_inv.setdefault(inv_id, []).append(rec)
        ts = rec.get("tsleitura_new", "")
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
    pacs, ativas_inv = [], []                 # potência ativa (Pac) + strings ativas POR inversor
    sb = plant["nome"].strip() in STRING_BOX
    sem_visao = 0                             # inversores String Box SEM combiner exposta na Plataforma
    for inv_id, rec in latest.items():
        cj = parse_cj(rec.get("conteudojson"))
        ipv_keys  = [k for k in cj if k.startswith("Ipv") and isinstance(cj[k], (int, float))]
        _pac = cj.get("Pac")
        # Mesma régua do drill (api_plant_detail): se o ÚLTIMO ping não tem Ipv (vem só Eday/Temp),
        # busca o último do dia que TEM — evita o inversor virar "0 strings ativas" na linha-pai
        # enquanto está produzindo (descoberto na Indaiatuba 1: linha-pai 29, soma do drill 157).
        if not ipv_keys:
            for prev in sorted(by_inv.get(inv_id, []),
                               key=lambda r: r.get("tsleitura_new", ""), reverse=True):
                pcj = parse_cj(prev.get("conteudojson"))
                pk  = [k for k in pcj if k.startswith("Ipv") and isinstance(pcj[k], (int, float))]
                if pk:
                    cj, ipv_keys = pcj, pk
                    break
        if sb and len(ipv_keys) <= 1:
            # String Box: corrente por string REAL vem da COMBINER (Plataforma). Sem combiner
            # exposta → "sem visão": não conta a string fantasma nem o esperado desse inversor.
            cmb = _plat_combiner_strings(inv_id)
            if cmb:
                cj = dict(cj); cj.update(dict(cmb["strings"]))
                ipv_keys = [k for k, _ in cmb["strings"]]
            else:
                sem_visao += 1
                ipv_keys = []
        correntes = [cj[k] for k in ipv_keys]
        # exclui trancadas e aplica a régua relativa à mediana do inversor
        _at = _str_ativas(_classifica_strings(pid, inv_id, ipv_keys, correntes))
        strings_ativas += _at
        ativas_inv.append(_at)
        pacs.append(_pac if isinstance(_pac, (int, float)) else None)
        t = cj.get("Temp")
        if isinstance(t, (int, float)):
            temps.append(t)

    esp       = ESPERADO.get(plant["nome"].strip(), {})
    inv_esp   = esp.get("inv_esp")
    str_esp   = esp.get("str_esp")
    if sb and sem_visao and isinstance(str_esp, (int, float)) and latest:
        # desconta as esperadas dos inversores sem visão (proporcional) p/ não gerar déficit falso
        str_esp = max(0, round(str_esp * (1 - sem_visao / len(latest))))
    diferenca = (strings_ativas - str_esp) if (str_esp is not None) else None
    # potência ativa → parada por inversor; deficit operante = tira os inversores parados.
    # (sem nome de inversor aqui p/ o esperado individual → estima pela média str_esp/qtd)
    prod, pot_med, n_off = _macro_prod(pacs)
    dif_operante = diferenca
    if (isinstance(diferenca, (int, float)) and n_off and str_esp and latest):
        esp_por_inv = str_esp / len(latest)
        dif_operante = min(0, round(diferenca + n_off * esp_por_inv))   # adiciona de volta o deficit dos parados

    return {
        "usina": nome, "plant_id": pid,
        "qtd_inversores": len(latest),
        "strings_ativas": strings_ativas,
        "pot_med": pot_med, "inv_off": n_off, "diferenca_operante": dif_operante,
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
def _pv_plant_inversores(plant_id):
    """Inversores da usina (API PV) com strings classificadas. Reusado pelo endpoint /api/plant
    e pelo motor de diagnóstico (R-10). Levanta exceção em erro de rede."""
    token = get_token()
    records = _http().post(f"{BASE_URL}/day_inverter",
                            headers={"x-access-token": token},
                            json={"id": plant_id}, timeout=60).json()
    if not records:
        return []

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
        mapa          = EQUIP_NAMES.get(plant_nome_api, {})
        display_nome  = mapa.get(api_nome_orig, api_nome_orig).lower()
        if "inv" not in api_nome and "inv" not in display_nome:
            return False
        for nome in (api_nome, display_nome):
            if any(exc in nome for exc in _EXCLUIR_CONTEM):
                return False
        # O cadastro (BD Equipamentos) é a fonte da verdade dos inversores. Se a usina TEM
        # cadastro e este device não está nele E não tem leitura, é um device avulso/duplicado
        # do supervisório (ex.: "INVERSOR08" fantasma ao lado do "Inversor 2.8" real) → fora.
        if mapa and api_nome_orig not in mapa and dev_id not in latest:
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
            # String Box: day_inverter expõe ≤1 Ipv por inversor → a corrente por string REAL vem
            # da COMBINER via Plataforma (mesma régua/status; snapshot, como o PG). Inversor de
            # usina String Box SEM combiner exposta (ex.: trocado/recadastrado, id 35xxxx) fica
            # "sem visão": nada de 1 string fantasma virando "-13 faltando" falso.
            eh_combiner = sem_visao = False
            if len(ipv_keys) <= 1:
                cmb = _plat_combiner_strings(inv_id)
                if cmb:
                    scj = dict(scj)                       # não polui o cj original (Temp/Eday ficam)
                    scj.update(dict(cmb["strings"]))
                    ipv_keys = [k for k, _ in cmb["strings"]]
                    eh_combiner = True
                elif plant_nome_api in STRING_BOX:
                    sem_visao = True
            correntes = [scj[k] for k in ipv_keys]
            stt       = _classifica_strings(plant_id, inv_id, ipv_keys, correntes)
            strings   = [{"id": k, "corrente": c, "status": s,
                          "ativa": s in ("ativa", "baixa_perf"), "trancada": s == "trancada"}
                         for k, c, s in zip(ipv_keys, correntes, stt)]
            strings_ativas = _str_ativas(stt)
            if sem_visao:                                 # sem visão por string → neutro (sem contagem)
                strings, strings_ativas = [], None
            temp   = cj.get("Temp")
            eday   = cj.get("Eday")
            _pac   = scj.get("Pac")
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
            _pac           = None
            ts_rec         = None
            falha          = True
            desligado      = True
            eh_combiner    = False
            sem_visao      = False

        # Lookup de strings esperadas usa o nome da API (chave original da planilha)
        inv_str_esp   = None if sem_visao else ESPERADO_INV.get(plant_nome_api, {}).get(inv_nome_api)
        inv_diferenca = (strings_ativas - inv_str_esp) \
            if (inv_str_esp is not None and not desligado and isinstance(strings_ativas, (int, float))) else None

        inversores.append({
            "id": inv_id,
            "nome": inv_nome,
            "nome_api": inv_nome_api,
            "ultima_leitura": ts_rec,
            "falha_comunicacao": falha,
            "desligado": desligado,
            "active_power": _pac,
            "strings_ativas": strings_ativas,
            "total_strings": len(strings),
            "str_esp": inv_str_esp,
            "diferenca": inv_diferenca,
            "temp": temp,
            "eday": eday,
            "combiner": eh_combiner,     # strings vieram da COMBINER (Plataforma) — usina String Box
            "sem_visao": sem_visao,      # String Box sem combiner exposta → sem contagem (neutro)
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

    # ── Inversor DESLIGADO de dia (MESMA régua do PG): potência ativa (Pac) ~0 → inversor parado.
    # A régua por-inversor (_classifica_strings) marca tudo "inativa" (parece noite) → o heatmap
    # pintava VERDE e o card contava como OK. De dia, Pac~0 = trip/desligamento real → linha inteira
    # vira 'desligado' (a corrente reversa residual não é produção). Fallback (sem Pac): régua antiga
    # por strings (≥2 inversores gerando = usina produz; inversor 100% sem corrente = desligado).
    _dia = 7 <= datetime.now().hour < 18
    _prod, _potmed, _ = _macro_prod([inv.get("active_power") for inv in inversores])
    _tem_pac = any(isinstance(inv.get("active_power"), (int, float)) for inv in inversores)
    _plant_prod = len([inv for inv in inversores if (inv.get("strings_ativas") or 0) > 0]) >= 2
    for inv, pr in zip(inversores, _prod):
        if _tem_pac:
            _off = pr is False and _dia
        else:                                     # fallback sem Pac: só se a usina está gerando
            _off = _plant_prod and (inv.get("strings_ativas") or 0) == 0
        if _off and any(s["status"] != "trancada" for s in inv["strings"]):
            inv["desligado"] = True
            for s in inv["strings"]:
                if s["status"] != "trancada":
                    s["status"] = "desligado"; s["ativa"] = False
    return inversores


@app.route("/api/plant/<int:plant_id>")
def api_plant_detail(plant_id):
    try:
        invs = _pv_plant_inversores(plant_id)
    except Exception:
        return jsonify({"error": "timeout"}), 504
    return jsonify({"plant_id": plant_id, "inversores": invs})


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


@app.route("/teste-layout")
def teste_layout():
    # Protótipo do NOVO estilo da página principal (aba API PV · Strings · Visão geral).
    # Consome o /api/data ao vivo. Aprovado → portar p/ index.html; reprovado → apagar rota+template.
    return render_template("teste_layout.html", today=datetime.now().strftime("%d/%m/%Y"))


@app.route("/gerencial")
def gerencial():
    # Painel 3 — Visão Gerencial (atingimento × P50 por usina/cliente). Consome /api/gerencial.
    return render_template("gerencial.html")


@app.route("/painel")
def painel_portfolio():
    # Painel NOC — Monitoramento de Portfólio (versão rica). Consome /api/macro + /api/gerencial.
    return render_template("painel_portfolio.html", today=datetime.now().strftime("%d/%m/%Y"))




@app.route("/painel/usina/<plant_id>")
def painel_usina(plant_id):
    # Painel NOC — Diagnóstico de Usina (drill). id pode ser int (PV/PG) ou string (Athon/Axis/2C).
    return render_template("painel_usina.html", plant_id=plant_id,
                           today=datetime.now().strftime("%d/%m/%Y"))


@app.route("/historico2c")
def historico2c():
    # Navega o banco-por-dia do 2C (2C_historico) com curvas. Consome /api/2c/*.
    return render_template("historico2c.html")


@app.route("/historico-plataforma")
def historico_plataforma():
    # Histórico por dia das usinas da API PV (Trackers tem curva; Strings/ETM só dia atual).
    return render_template("historico_pv.html")


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
    date = (flask_request.args.get("date") or "").strip()
    if date and date != datetime.now().strftime("%Y-%m-%d"):
        # day_meteo só entrega o DIA ATUAL; histórico de ETM da API PV não é confiável (custom_query lento)
        return jsonify({"labels": [], "poa": [], "ghi": [], "poari": [], "sem_historico": True})
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
    elif ETM_DIA_INI <= agora.hour < ETM_DIA_FIM and diff_min > ETM_LATE_WARN_MIN:
        # de dia, a estação parou de enviar há um tempo (mas < limite crítico) → possível falta
        flags.append({"t": "Possível falta de dados", "tipo": "warn",
                      "info": f"sem leitura nova há {int(diff_min)} min"}); sev = min(sev, 1)

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

    # 5) Possível falta de dados — buraco grande na série DURANTE O DIA (ignora madrugada,
    #    quando a estação naturalmente reporta esparso). Distinto de dropout de POA (que é valor).
    diurnas = [t for (t, _, _) in series if ETM_DIA_INI <= t.hour < ETM_DIA_FIM]
    maxgap = max(((diurnas[i] - diurnas[i - 1]).total_seconds() / 60
                  for i in range(1, len(diurnas))), default=0)
    if maxgap > ETM_GAP_WARN_MIN:
        flags.append({"t": "Possível falta de dados", "tipo": "warn",
                      "info": f"buraco de {int(maxgap)} min na série"}); sev = min(sev, 1)

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
def _sunop_try_refresh(headers, inst: str = "gridco") -> str:
    """Chama /refresh_token (exige o token ATUAL ainda válido) → novo token; atualiza memória
    e persiste no arquivo da instância (p/ sobreviver a reinícios)."""
    S = _si(inst)
    try:
        r = _http().get(f"{S['config']}/refresh_token", headers=headers, timeout=10)
        if r.status_code == 200:
            nt = r.json()
            if isinstance(nt, str):
                nt = nt.strip('"')
            if nt and nt.startswith("eyJ"):
                S["token"]["token"] = nt
                _sunop_persist(nt, inst)
                return nt
    except Exception:
        pass
    return ""


def get_sunop_token(inst: str = "gridco") -> str:
    S   = _si(inst)
    tok = S["token"]["token"]
    H   = {"Authorization": f"JWT {tok}", "Content-Type": "application/json"}
    # Renova PROATIVAMENTE enquanto o token ainda é válido (vence em < 2 dias). O /refresh_token
    # só aceita token válido — não dá p/ esperar expirar. O keepalive (6h) garante essa janela.
    exp = _jwt_exp(tok)
    if exp and 0 < (exp - time.time()) < 2 * 86400:
        nt = _sunop_try_refresh(H, inst)
        if nt:
            return nt
    # Caminho normal: valida; se inválido, tenta refresh (best-effort — pode falhar se já expirou).
    try:
        if _http().get(f"{S['config']}/check_token", headers=H, timeout=8).status_code == 200:
            return tok
    except Exception:
        pass
    return _sunop_try_refresh(H, inst) or tok


def _sunop_headers(inst: str = "gridco") -> dict:
    return {"Authorization": f"JWT {get_sunop_token(inst)}",
            "Content-Type": "application/json"}


# ── SunOp: carrega metadados de uma planta ────────────────────────────────────
def _sunop_invnum(x):
    """Chave de ordenação p/ inversor — tupla de números no id. Funciona p/ gridco ('INV_1' → (1,))
    e axis ('SKID_1.LVDB_1.INV_3' → (1,1,3))."""
    nums = re.findall(r"\d+", x)
    return tuple(int(n) for n in nums) if nums else (999,)


def _sunop_inv_display(plant_name, inv_key):
    """Nome de exibição do inversor: EQUIP_NAMES (gridco) ou derivado do id (axis SKID/INV)."""
    eq = EQUIP_NAMES.get(plant_name, {}).get(inv_key)
    if eq:
        return eq
    sk = re.search(r"SKID_(\d+)", inv_key); iv = re.search(r"INV_(\d+)", inv_key)
    if sk and iv:
        return f"Skid {sk.group(1)} · Inv {iv.group(1)}"
    if iv:
        return f"Inversor {iv.group(1)}"
    return inv_key


def _load_sunop_plant_meta(plant_name: str, inst: str = "gridco") -> dict:
    H = _sunop_headers(inst)
    try:
        r = _http().get(f"{_si(inst)['data']}/v2/metadata", headers=H,
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
    # Axis: trackers em PLANT.NCU_x.TRK_y.{ANALOG.TARGET_POS|CURRENT_POS|DEVIATION | STATUS.WORKSTATE}
    _TRK_MEDIDA_AXIS = {"ANALOG.TARGET_POS": "alvo", "ANALOG.CURRENT_POS": "atual",
                        "ANALOG.DEVIATION": "desvio", "STATUS.WORKSTATE": "estado"}

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

        # Correntes de string (genérico p/ gridco e axis):
        #   gridco: PLANT.INV_N.MEDIDAS.STR.I_PVx              → inv = INV_N
        #   axis:   PLANT.SKID_s.LVDB_l.INV_i.ANALOG.STR.I_PVx → inv = SKID_s.LVDB_l.INV_i
        if len(parts) >= 5 and parts[-2] == "STR" and parts[-1].startswith("I_PV"):
            inv_strings.setdefault(".".join(parts[1:-3]), []).append(path)

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

        # ── AXIS ──────────────────────────────────────────────────────────────
        # EPD por inversor (p/ PR): PLANT.SKID.LVDB.INV.ANALOG.EPD → inv = SKID.LVDB.INV
        elif parts[-2] == "ANALOG" and parts[-1] == "EPD" and "INV_" in path:
            inv_other.setdefault(".".join(parts[1:-2]), {})["EPD"] = path

        # Trackers axis: PLANT.NCU_x.TRK_y.{ANALOG.TARGET_POS|CURRENT_POS|DEVIATION | STATUS.WORKSTATE}
        elif sub.startswith("NCU_") and len(parts) >= 4 and parts[2].startswith("TRK_"):
            medida = _TRK_MEDIDA_AXIS.get(".".join(parts[3:]))
            if medida:
                trackers.setdefault(parts[2], {})[medida] = path

        # POA modelada axis (PE III): PLANT.AIML.POA — usada só se não houver estação real
        elif sub == "AIML" and len(parts) >= 3 and parts[2] == "POA":
            etm_stations.setdefault("AIML", {})["poa"] = path
            plant_paths.setdefault("POA", path)

        # Estação meteo REAL axis (Ponto Belo): PLANT.METEOST_x.ANALOG.POA_IRRAD → prioriza sobre AIML
        elif sub.startswith("METEOST") and parts[-1] in ("POA_IRRAD", "POA"):
            etm_stations.setdefault(sub, {})["poa"] = path
            plant_paths["POA"] = path

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


def ensure_sunop_meta(inst: str = "gridco"):
    """Carrega metadata de todas as plantas SunOp (lazy, uma vez por processo/instância)."""
    S = _si(inst)
    if S["meta"]:
        return
    H = _sunop_headers(inst)
    try:
        plants = _http().get(f"{S['config']}/plants", headers=H, timeout=15).json()
    except Exception as e:
        print(f"[SUNOP:{inst}] Erro plants: {e}")
        return
    # Blindagem: se o token expirou, /api/plants devolve um dict de erro (ex.:
    # {"detail":"Token has expired."}) em vez da lista → não crashar.
    if not isinstance(plants, list) or not all(isinstance(p, dict) and "name" in p for p in plants):
        print(f"[SUNOP:{inst}] /plants não retornou lista de plantas (token expirado?): {str(plants)[:120]}")
        return
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(_load_sunop_plant_meta, p["name"], inst): p["name"] for p in plants}
        for f in as_completed(futures):
            pname = futures[f]
            meta  = f.result()
            if meta:
                S["meta"][pname] = meta
    print(f"[SUNOP:{inst}] Metadata: {len(S['meta'])} plantas carregadas")


# ── SunOp: processa uma planta ────────────────────────────────────────────────
def process_plant_sunop(plant_name: str, inst: str = "gridco") -> dict:
    base = {
        "usina": USINA_DISPLAY.get(plant_name, plant_name), "plant_id": plant_name,
        "qtd_inversores": None, "strings_ativas": None,
        "inv_esp": None, "str_esp": None, "diferenca": None,
        "temp_media": None, "ultima_leitura": None,
        "sem_dados": True, "falha_comunicacao": False,
        "energia_dia": None, "potencia_atual": None,
    }
    meta = _si(inst)["meta"].get(plant_name)
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
    H = _sunop_headers(inst)
    data_url = _si(inst)["data"]
    all_vals = []
    for i in range(0, len(pathnames), 500):
        batch = pathnames[i:i+500]
        try:
            r = _http().post(f"{data_url}/v2/last_values?use_plant_timezone=true", headers=H,
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

    # "Sem comunicação" da USINA = o logger da planta não reporta (leitura velha), MESMA régua da
    # API PV. NÃO usar InvsFalhaComunicacao do supervisório aqui: falha PARCIAL de inversor com a
    # usina reportando (leitura fresca + strings ativas) é déficit de inversor, não sem-comm da
    # usina — senão a usina some da contagem de déficit do portfólio (caso CPP100, 05/07).
    falha_comm = False
    if ts_max:
        try:
            diff = (datetime.now() - datetime.fromisoformat(ts_max)).total_seconds() / 60
            falha_comm = diff > COMM_ALERT_MINUTES
        except Exception:
            pass

    # Produção da usina (p/ separar PARADA de baixa-perf de strings): potência total da planta
    # (LOGGER.TOT.P) ou, na falta, o contador de inversores produzindo/parados do supervisório.
    tot_p  = _pval("LOGGER.TOT.P")
    n_prod = _pval("InvsProduzindo")
    n_par  = _pval("InvsParados")
    if isinstance(tot_p, (int, float)):
        pot_med = tot_p
    elif isinstance(n_prod, (int, float)):
        pot_med = 0.0 if n_prod <= 0 else 999.0        # sentinela: produzindo/parada pelo contador
    else:
        pot_med = None
    if isinstance(n_par, (int, float)):
        inv_off = int(n_par)
    elif isinstance(n_prod, (int, float)):
        inv_off = max(0, qtd_inv_com_dados - int(n_prod))
    else:
        inv_off = 0

    return {
        "usina": USINA_DISPLAY.get(plant_name, plant_name), "plant_id": plant_name,
        "qtd_inversores": qtd_inv_com_dados,
        "strings_ativas": total_ativas,
        "inv_esp": inv_esp,
        "str_esp": str_esp,
        "diferenca": diferenca,
        "pot_med": pot_med, "inv_off": inv_off,
        "temp_media": round(sum(temps) / len(temps), 1) if temps else None,
        "ultima_leitura": ts_max or None,
        "sem_dados": False,
        "falha_comunicacao": falha_comm,
    }


def fetch_all_sunop(inst: str = "gridco") -> list:
    ensure_sunop_meta(inst)
    rows = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(process_plant_sunop, pname, inst): pname
                   for pname in _si(inst)["meta"]}
        for f in as_completed(futures):
            rows.append(f.result())
    return sorted(rows, key=lambda x: (severidade(x), x["usina"]))


# ── SunOp: visão geral ────────────────────────────────────────────────────────
def _build_sunop_payload(inst: str = "gridco"):
    rows = fetch_all_sunop(inst)
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
@app.route("/api/axis/data")
def api_sunop_data():
    inst = "axis" if flask_request.path.startswith("/api/axis/") else "gridco"
    force = flask_request.args.get("force", "0") == "1"
    return jsonify(_swr(_si(inst)["cache"], lambda: _build_sunop_payload(inst), force))


# ── SunOp: drill-down inversores (SWR por usina: serve cache na hora, atualiza em fundo) ─
_so_plant_cache = {}      # plant_name -> {"ts": float, "inversores": [...]}
_so_plant_lock  = threading.Lock()


def _sunop_plant_build(plant_name, inst: str = "gridco"):
    ensure_sunop_meta(inst)
    meta = _si(inst)["meta"].get(plant_name)
    if not meta:
        return []

    pathnames = []
    for inv, paths in meta["inv_strings"].items():
        pathnames.extend(paths)
    for inv, others in meta["inv_other"].items():
        pathnames.extend(others.values())

    H = _sunop_headers(inst)
    data_url = _si(inst)["data"]
    all_vals = []
    for i in range(0, len(pathnames), 500):
        try:
            r = _http().post(f"{data_url}/v2/last_values?use_plant_timezone=true", headers=H,
                              json={"pathnames": pathnames[i:i+500]}, timeout=30)
            if r.status_code == 200:
                all_vals.extend(r.json())
        except Exception:
            pass

    by_path = {v["pathname"]: v for v in all_vals}

    inversores = []
    for inv_name in sorted(meta["inv_strings"].keys(), key=_sunop_invnum):
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

        # Traduz nome do inversor: EQUIP_NAMES (gridco, ex. INV_1 → Inversor 1.1) ou id axis (SKID/INV)
        inv_display = _sunop_inv_display(plant_name, inv_name)
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

    return inversores


def _sunop_plant_get(plant_name, force=False, inst: str = "gridco"):
    """SWR por usina: serve o último drill-down na hora e atualiza em segundo plano.
    Evita que expandir uma usina (Strings / Curva das strings) trave numa chamada ao
    vivo do SunOp quando a API está sob carga (ex.: durante um 'Atualizar')."""
    agora = time.time()
    ckey = (inst, plant_name)
    ent = _so_plant_cache.get(ckey)
    if ent and not force and (agora - ent["ts"]) < CACHE_TTL:
        return ent["inversores"]
    if ent and not force:                       # tem stale → serve já e atualiza em fundo
        def _bg():
            if not _so_plant_lock.acquire(blocking=False):
                return
            try:
                _so_plant_cache[ckey] = {"ts": time.time(),
                                         "inversores": _sunop_plant_build(plant_name, inst)}
            except Exception as e:
                print(f"[sunop/plant] refresh {plant_name} falhou: {e}")
            finally:
                _so_plant_lock.release()
        threading.Thread(target=_bg, daemon=True).start()
        return ent["inversores"]
    inv = _sunop_plant_build(plant_name, inst)  # 1ª vez (ou forçado) → constrói na hora
    _so_plant_cache[ckey] = {"ts": time.time(), "inversores": inv}
    return inv


@app.route("/api/sunop/plant/<plant_name>")
@app.route("/api/axis/plant/<plant_name>")
def api_sunop_plant(plant_name):
    inst = "axis" if flask_request.path.startswith("/api/axis/") else "gridco"
    force = flask_request.args.get("force", "0") == "1"
    try:
        inversores = _sunop_plant_get(plant_name, force, inst)
    except Exception as e:
        return jsonify({"error": str(e), "inversores": []}), 500
    return jsonify({"plant_id": plant_name, "inversores": inversores})


# ── SunOp ETM ─────────────────────────────────────────────────────────────────
def _etm_label(station: str) -> str:
    """'ESTM' → '' (estação única); 'ESTM_1' → 'ESTM 1'."""
    return "" if station == "ESTM" else station.replace("_", " ")


def fetch_sunop_etm_plant(plant_name: str, inst: str = "gridco") -> list:
    """Retorna UMA linha por estação meteorológica da planta (ESTM, ESTM_1, ESTM_2…)."""
    meta     = _si(inst)["meta"].get(plant_name, {})
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

    H = _sunop_headers(inst)
    by_path = {}
    if all_paths:
        try:
            r = _http().post(f"{_si(inst)['data']}/v2/last_values?use_plant_timezone=true", headers=H,
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


def _build_sunop_etm_payload(inst: str = "gridco"):
    ensure_sunop_meta(inst)
    rows = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(fetch_sunop_etm_plant, pname, inst): pname for pname in _si(inst)["meta"]}
        for f in as_completed(futures):
            rows.extend(f.result())   # uma ou mais linhas por planta (uma por estação)
    rows.sort(key=lambda x: (etm_severidade(x), x["usina"], x.get("etm", "")))
    return {"rows": rows, "cache_ts": datetime.now().strftime("%H:%M:%S")}


@app.route("/api/sunop/etm")
@app.route("/api/axis/etm")
def api_sunop_etm():
    inst = "axis" if flask_request.path.startswith("/api/axis/") else "gridco"
    force = flask_request.args.get("force", "0") == "1"
    return jsonify(_swr(_si(inst)["etm_cache"], lambda: _build_sunop_etm_payload(inst), force))


# ── SunOp: pré-análise ETM (CURVA REAL via /data/v2/analog_values) ─────────────
_sunop_analise_cache = {"payload": None, "ts": 0.0}


def _sunop_etm_estacoes(inst: str = "gridco"):
    """→ lista de (plant, station_raw, {poa,ghi,poari: path}) p/ todas as estações."""
    out = []
    for plant, meta in _si(inst)["meta"].items():
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


def _build_sunop_analise_payload(inst: str = "gridco"):
    ensure_sunop_meta(inst)
    estacoes = _sunop_etm_estacoes(inst)
    dia = datetime.now().strftime("%Y-%m-%d")
    all_paths = [paths[k] for _, _, paths in estacoes for k in ("poa", "ghi", "poari") if paths.get(k)]
    hist = _sunop_analog_history(all_paths, f"{dia}T00:00:00", f"{dia}T23:59:59", inst)

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
@app.route("/api/axis/etm/analise")
def api_sunop_etm_analise():
    inst = "axis" if flask_request.path.startswith("/api/axis/") else "gridco"
    force = flask_request.args.get("force", "0") == "1"
    return jsonify(_swr(_si(inst)["analise_cache"], lambda: _build_sunop_analise_payload(inst), force))


@app.route("/api/sunop/etm/chart")
@app.route("/api/axis/etm/chart")
def api_sunop_etm_chart():
    inst = "axis" if flask_request.path.startswith("/api/axis/") else "gridco"
    plant = (flask_request.args.get("plant") or "").strip()
    est   = (flask_request.args.get("estacao") or "ESTM").strip() or "ESTM"
    dia   = (flask_request.args.get("date") or datetime.now().strftime("%Y-%m-%d")).strip()
    ensure_sunop_meta(inst)
    meta = _si(inst)["meta"].get(plant, {})
    stations = meta.get("etm_stations") or {"ESTM": {
        "poa": f"{plant}.ESTM.POA.IRAD", "ghi": f"{plant}.ESTM.GHI.IRAD",
        "poari": f"{plant}.ESTM.POA_R.IRAD"}}
    paths = stations.get(est) or {}
    used = [paths[k] for k in ("poa", "ghi", "poari") if paths.get(k)]
    hist = _sunop_analog_history(used, f"{dia}T00:00:00", f"{dia}T23:59:59", inst)
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
TRK_ALVO_MOVE_MIN = 30.0 # ° — (régua relativa) referência de movimento dos vizinhos
TRK_COBERTURA_MIN_H = 4.0   # h — span da curva p/ julgar "parado" de forma ABSOLUTA (independe
                            #     dos vizinhos → pega a PLANTA INTEIRA parada, que a régua
                            #     relativa deixava passar como "Normal")
TRK_PARADA_GLOBAL_HORA = 12 # h — passada esta hora, planta que mal girou (mediana baixa) = TODOS
                            #     parados, não "ainda não girou" (corrige o falso "Normal")
TRK_FROTA_ACORDA_HORA  = 11 # h — hora-limite (escolha do Levi 07/07): frota que NUNCA girou até
                            #     aqui já DEVIA ter acordado → travada (não "dormindo"). Antes
                            #     disso, frota imóvel = madrugada/manhã normal (sem alarme).
TRK_DESVIO_MIN   = 5.0   # ° — disparidade ATUAL acima da MEDIANA da planta (e não parado) = "desvio"
TRK_ATRASO_DELTA = 10.0  # ° — disparidade MÁX do dia acima da MEDIANA da planta = "atraso" (amarelo)
#   (relativo à mediana p/ descontar o "ruído estrutural": o alvo costuma ir a ângulos mais
#    extremos que o tracker alcança nas pontas do dia → ~11° de disparidade máx é NORMAL)
def _amp_robusta(vals):
    """Amplitude do dia ROBUSTA a glitch de telemetria: range entre os percentis 2 e 98 — um
    punhado de leituras podres não infla a amplitude (caso Tracker 82 SMP100 07/07: reto em
    -15,5° o dia todo, mas amp crua 16,1° > TRK_PARADO_AMP → escapava do 'parado' e caía em
    'desvio'). Série curta (<20 pts) usa o range cru (não há o que aparar)."""
    v = sorted(x for x in vals if x is not None)
    if len(v) < 2:
        return None
    if len(v) >= 20:
        return v[int(len(v) * 0.98)] - v[int(len(v) * 0.02)]
    return v[-1] - v[0]


def _frota_acordou(amps, dia_coberto=False, data_ref=None):
    """A usina 'acordou' quando a FROTA já girou de verdade (régua do Levi 07/07): é NORMAL a
    usina inteira parada de madrugada/manhã no ângulo leste; e logo após o despertar alguns
    trackers ainda estão subindo (o 'primeiro se moveu' pegaria os lentos como falso-parado).
    Duas portas (régua do Levi 07/07 tarde — caso CPP100 60/63 travados, mediana 0,2°):
    1) MEDIANA das amplitudes do dia > TRK_ALVO_MOVE_MIN → metade da frota girou de verdade;
    2) a frota JÁ DEVIA ter acordado e não girou = TRAVADA (não 'dormindo'): dia_coberto (≥4h de
       dados) E (dia PASSADO, ou hoje após TRK_FROTA_ACORDA_HORA). Sem a porta 2, a usina com a
       MAIORIA da frota travada nunca 'acordava' pela mediana e mostrava 0 parados (regressão do
       Furo 1 / SMP100), enquanto a disponibilidade por tempo denunciava 3%.
    amps = {tracker: amplitude_do_dia} ou lista; data_ref = 'YYYY-MM-DD' ou 'DD/MM/YYYY' do dia
    analisado (None = hoje)."""
    vals = sorted(a for a in (amps.values() if hasattr(amps, "values") else amps) if a is not None)
    if not vals:
        return False
    if vals[len(vals) // 2] > TRK_ALVO_MOVE_MIN:
        return True
    if not dia_coberto:
        return False
    if data_ref:
        try:
            d = str(data_ref)
            if "/" in d:
                d = datetime.strptime(d, "%d/%m/%Y").strftime("%Y-%m-%d")
            if d < datetime.now().strftime("%Y-%m-%d"):
                return True          # dia PASSADO coberto e a frota nunca girou → travada o dia todo
        except Exception:
            pass
    return datetime.now().hour >= TRK_FROTA_ACORDA_HORA


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

# ── Alerta: usina com TODOS os trackers parados há mais de X horas (a partir das 9h) ──
TRK_PARADA_NOTIF_HORAS    = 2.0   # h — todos os trackers parados por mais que isto → notifica na tela
TRK_PARADA_NOTIF_HORA_INI = 9     # h — só notifica a partir desta hora local (sem ruído de madrugada)
_trk_parada_total = {"date": "", "plants": {}}   # plants[str(pid)] = {"desde": epoch, "usina": nome}
_trk_parada_lock  = threading.Lock()


def _trk_parada_reconcilia():
    """Atualiza o estado 'desde quando TODOS os trackers parados' a partir dos payloads por-planta
    (_pv_trk_plant, parados==total). Preserva o 'desde' (1ª observação) — inclusive o persistido entre
    restarts — e limpa quem saiu do estado. Zera na virada do dia. Retorna o snapshot do estado."""
    hoje = datetime.now().strftime("%Y-%m-%d")
    agora = time.time()
    with _trk_parada_lock:
        if _trk_parada_total["date"] != hoje:
            _trk_parada_total["date"], _trk_parada_total["plants"] = hoje, {}
        st = _trk_parada_total["plants"]
        for pid, ent in list(_pv_trk_plant.items()):
            pl = ent.get("payload", {})
            total = pl.get("total") or 0
            # "todos parados" = todos em estado anômalo (parado + desvio crítico): no overview a
            # classificação "parado" depende da curva cacheada / acumulador 9-15h e cedo de manhã
            # vem zerada — usar só "parados" perderia usina rastreando 0 trackers. Severos = par+desv.
            ruins = (pl.get("parados") or 0) + (pl.get("desvios") or 0)
            all_parado = total > 0 and ruins >= total and not pl.get("sem_comunicacao")
            key = str(pid)
            if all_parado:
                if key in st:
                    st[key]["usina"] = pl.get("usina") or st[key].get("usina")
                    st[key]["total"] = total
                else:
                    st[key] = {"desde": agora, "usina": pl.get("usina"), "total": total}
            else:
                st.pop(key, None)
        snap = {k: dict(v) for k, v in st.items()}
    _persist_mark()
    return snap


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
    # A régua relativa deixava passar a PLANTA INTEIRA parada: mediana baixa → concluía "não
    # girou, não dá p/ julgar". Mas se já passou o meio da janela de operação e a planta mal
    # girou, ela está PARADA (todos travados) — não "ainda não girou".
    if med < TRK_ALVO_MOVE_MIN and datetime.now().hour < TRK_PARADA_GLOBAL_HORA:
        return set()                    # cedo no dia e ninguém girou — ainda não dá p/ julgar
    return {tid for tid, a in amps.items() if a < TRK_PARADO_AMP}



def _sunop_trk_curvas(plant_name: str, date: str, inst: str = "gridco") -> dict:
    """Busca (e cacheia) as curvas do dia POSAT/POSAL de todos os trackers da planta."""
    cache = _si(inst)["trk_hist"]
    key = (plant_name, date)
    ent = cache.get(key)
    if ent and time.time() - ent["ts"] < CACHE_TTL:
        return ent
    trk = (_si(inst)["meta"].get(plant_name, {}) or {}).get("trackers") or {}
    posat = {n: d["atual"] for n, d in trk.items() if d.get("atual")}
    posal = {n: d["alvo"]  for n, d in trk.items() if d.get("alvo")}
    hist = _sunop_analog_history(list(posat.values()) + list(posal.values()),
                                 f"{date}T00:00:00", f"{date}T23:59:59", inst)
    novo = {"ts": time.time(),
            "posat": {n: hist.get(p, []) for n, p in posat.items()},
            "posal": {n: hist.get(p, []) for n, p in posal.items()}}
    # GUARDA anti-encolhimento: a curva do MESMO dia só CRESCE (pontos acumulam). Resposta com
    # MENOS pontos que o cache = retorno PARCIAL da SunOp (throttle/atraso de ingestão) → mantém a
    # curva boa anterior; senão as amplitudes encolhem e a contagem de parados "pula" entre refreshes.
    if ent:
        _old = sum(len(s) for s in ent["posat"].values())
        _new = sum(len(s) for s in novo["posat"].values())
        if _new < _old:
            ent["ts"] = time.time()          # renova o TTL (não rebate a SunOp a cada chamada)
            return ent
    cache[key] = novo
    return novo


TRK_CHART_MAX_DIAS = 5    # janela máxima do gráfico De/Até (pedido Levi 07/07)


def _trk_chart_range():
    """Lê ?ini/?fim (YYYY-MM-DD ou DD/MM/YYYY; ?date p/ compat) e devolve (ini_iso, fim_iso, ndias)
    com ini<=fim e a janela TRAVADA em TRK_CHART_MAX_DIAS (mantém o FIM, recua o início). Sem
    parâmetros → hoje/hoje. É o contrato único do seletor De/Até nas 4 fontes."""
    args = flask_request.args
    hoje = datetime.now().strftime("%Y-%m-%d")

    def _iso(v):
        v = (v or "").strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            return v
        try:
            return datetime.strptime(v, "%d/%m/%Y").strftime("%Y-%m-%d")
        except Exception:
            return None

    ini, fim, d = _iso(args.get("ini")), _iso(args.get("fim")), _iso(args.get("date"))
    if not ini and not fim:
        ini = fim = d or hoje
    else:
        ini, fim = (ini or fim), (fim or ini)
    if ini > fim:
        ini, fim = fim, ini
    di, df = datetime.strptime(ini, "%Y-%m-%d"), datetime.strptime(fim, "%Y-%m-%d")
    if (df - di).days > TRK_CHART_MAX_DIAS - 1:          # trava a janela
        di = df - timedelta(days=TRK_CHART_MAX_DIAS - 1)
        ini = di.strftime("%Y-%m-%d")
    return ini, fim, (df - di).days + 1


def _trk_chart_down_alvo(ndias):
    """Alvo de pontos por série no downsample: 1 dia = 180 (resolução cheia); intervalo = mais
    esparso (~80/dia, teto 400) p/ o Plotly aguentar N trackers × N dias sem travar."""
    return 180 if ndias <= 1 else min(80 * ndias, 400)


def _sunop_trk_curvas_range(plant_name: str, ini: str, fim: str, inst: str = "gridco") -> dict:
    """Curvas POSAT/POSAL de um INTERVALO [ini, fim] (YYYY-MM-DD) — 1 só chamada ao histórico
    analógico (que já aceita start/end). Sem cache (on-demand no expand); 1 dia usa o cacheado."""
    trk = (_si(inst)["meta"].get(plant_name, {}) or {}).get("trackers") or {}
    posat = {n: d["atual"] for n, d in trk.items() if d.get("atual")}
    posal = {n: d["alvo"]  for n, d in trk.items() if d.get("alvo")}
    hist = _sunop_analog_history(list(posat.values()) + list(posal.values()),
                                 f"{ini}T00:00:00", f"{fim}T23:59:59", inst)
    return {"posat": {n: hist.get(p, []) for n, p in posat.items()},
            "posal": {n: hist.get(p, []) for n, p in posal.items()}}


def _sunop_trackers_plant_curva(plant_name: str, inst: str = "gridco") -> dict:
    """Análise por CURVA do dia:
    - 'parado' (vermelho): amplitude do ângulo baixa enquanto os VIZINHOS se moveram (não
      precisa de alvo → funciona em plantas sem POSAL, ex.: MAB100).
    - 'desvio' (laranja): disparidade alvo×atual ATUAL > limiar (está fora do ângulo agora).
    - 'atraso' (amarelo): disparidade MÁX do dia > limiar mas já voltou (saiu por pouco tempo).
    Trackers/plantas SEM alvo (POSAL) → só 'parado'/'normal' (sem desvio/atraso)."""
    meta = _si(inst)["meta"].get(plant_name, {})
    trk  = meta.get("trackers") or {}
    base = {"usina": USINA_DISPLAY.get(plant_name, plant_name), "plant_id": plant_name,
            "total": 0, "parados": 0, "desvios": 0, "atrasos": 0, "sem_alvo": False,
            "pior_disparidade": None, "ultima_leitura": None,
            "trackers": [], "tem_trackers": bool(trk)}
    if not trk:
        return base
    cur = _sunop_trk_curvas(plant_name, datetime.now().strftime("%Y-%m-%d"), inst)
    posat, posal = cur["posat"], cur["posal"]

    # Span de tempo coberto pela curva hoje → julga "parado" de forma ABSOLUTA (amplitude baixa
    # por horas = travado), sem depender de os VIZINHOS terem girado (senão a planta INTEIRA
    # parada nunca seria pega). E curva vazia / sem ponto = SEM COMUNICAÇÃO (não "normal").
    def _hh(ts):
        try:    return int(ts[11:13]) + int(ts[14:16]) / 60.0
        except Exception: return None
    _horas = []
    for s in posat.values():
        for ts, _ in s:
            h = _hh(ts)
            if h is not None:
                _horas.append(h)
    span_h = (max(_horas) - min(_horas)) if _horas else 0.0
    dia_coberto = span_h >= TRK_COBERTURA_MIN_H
    sem_dados = not _horas

    def _num(n):
        try: return int(n.split("_")[1])
        except Exception: return 999

    # amplitude de cada tracker + referência (mediana) = "quanto os trackers se moveram".
    # SÓ a JANELA DIURNA 06–18h (a curva vem 00:00–23:59: reposicionamento NOTURNO não é
    # rastreamento — inflava a amplitude do travado) + range ROBUSTO (p02–p98, mata spike).
    def _vals_dia(s):
        return [v for ts, v in s if ts[11:13].isdigit() and 6 <= int(ts[11:13]) < 18]
    amps = {n: (_amp_robusta(_vals_dia(s)) if s else None) for n, s in posat.items()}
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
        if amp is not None and amp < TRK_PARADO_AMP and _frota_acordou(amps, dia_coberto):
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
    # Cruzamento com a planilha de Tickets (nome da usina + nº do tracker) — espelha a API PV
    tick, ambiguo = _tickets_lookup(_tk_norm(base["usina"]))
    nums = (tick or {}).get("nums", {})
    novos = acomp = normalizados = 0
    for t in lst:
        tstat = nums.get(_pv_trk_num(t["id"]))
        t["na_planilha"]   = tstat is not None
        t["ticket_status"] = tstat
        t["normalizado"]   = bool(t["na_planilha"] and t["status"] == "normal")
        if t["normalizado"]:
            normalizados += 1
        if t["status"] != "normal":                 # anômalo (parado/desvio/atraso)
            if t["na_planilha"]:
                acomp += 1
            else:
                novos += 1
    # métricas p/ o OVERVIEW (mesmo motor de curva, sem depender do snapshot):
    _atuais = [r["atual"] for r in raw if r["atual"] is not None]
    media_ang = (sum(_atuais) / len(_atuais)) if _atuais else None
    _cdisp = [r["cur_disp"] for r in raw if r["cur_disp"] is not None]
    desvio_med = (sum(_cdisp) / len(_cdisp)) if _cdisp else None
    base.update({"total": len(lst), "parados": parados, "desvios": desvios, "atrasos": atrasos,
                 "sem_alvo": sem_alvo, "amp_ref": round(amp_ref, 1), "sem_comunicacao": sem_dados,
                 "pior_disparidade": round(pior, 2) if pior is not None else None,
                 "tem_ticket": tick is not None, "ambiguo": ambiguo,
                 "novos": novos, "acompanhados": acomp, "normalizados": normalizados,
                 # aliases p/ o overview usar a MESMA régua (parado+desvio = severo; atraso = leve)
                 "severos": parados + desvios, "leves": atrasos, "fora_media": 0,
                 "media_angulo": round(media_ang, 1) if media_ang is not None else None,
                 "desvio_medio": round(desvio_med, 2) if desvio_med is not None else None,
                 "ultima_leitura": ts_max or None, "trackers": lst})
    return _trk_alvo_mediana(base)


def _trk_alvo_mediana(base):
    """Fonte SEM ângulo alvo → alvo INFERIDO = mediana do ângulo ATUAL dos trackers que NÃO
    estão parados (pedido do Levi 06/07). Preenche t.alvo/disparidade só onde faltam e marca
    alvo_inferido=True (a UI rotula "mediana da frota"). NÃO mexe nos status — a régua
    consolidada de parado/desvio continua a mesma."""
    try:
        ts = base.get("trackers") or []
        if not ts or all(t.get("alvo") is not None for t in ts):
            return base
        # 1) há alvos na frota → tracker SEM alvo herda a MEDIANA dos alvos existentes
        #    (caso TRK54 do Inhapi: 2 têm alvo 66° e 1 vem sem — mesma ordem de comando)
        alvos = sorted(t["alvo"] for t in ts if isinstance(t.get("alvo"), (int, float)))
        if alvos:
            med = alvos[len(alvos) // 2]
        else:
            # 2) NINGUÉM tem alvo → mediana do ângulo ATUAL dos trackers girando (≥3, senão não inventa)
            vals = sorted(t["atual"] for t in ts
                          if isinstance(t.get("atual"), (int, float))
                          and t.get("status") not in ("parado", "severo"))
            if len(vals) < 3:
                return base
            med = vals[len(vals) // 2]
            base["alvo_inferido"] = True     # usina inteira com alvo inferido → rótulo na UI
        for t in ts:
            if t.get("alvo") is None:
                t["alvo"] = round(med, 2)
                if t.get("disparidade") is None and isinstance(t.get("atual"), (int, float)):
                    t["disparidade"] = round(abs(t["atual"] - med), 2)
    except Exception:
        pass
    return base


def _trk_severidade(r) -> int:
    if r.get("sem_comunicacao"): return 0   # sem leitura = crítico (não pode passar por "normal")
    if r.get("severos"):    return 0
    if r.get("leves"):      return 1
    if r.get("fora_media"): return 2
    if not r.get("total"):  return 4
    return 3


def _build_sunop_trk_payload(inst: str = "gridco"):
    ensure_sunop_meta(inst)
    plantas = [p for p, m in _si(inst)["meta"].items() if m.get("trackers")]
    rows = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        # MESMO motor de curva das sub-abas Parados/Ocorrências (régua absoluta amp<15°+≥4h),
        # p/ o overview não divergir do detalhe (ex.: usina inteira parada não some).
        futures = {ex.submit(_sunop_trackers_plant_curva, p, inst): p for p in plantas}
        for f in as_completed(futures):
            r = f.result()
            r.pop("trackers", None)   # overview não carrega a lista completa
            rows.append(r)
    rows.sort(key=lambda x: (_trk_severidade(x), x["usina"]))
    disp_pid = _sunop_disp_hoje(inst)              # disponibilidade por TEMPO (janela 06:00–18:00)
    for r in rows:
        r["disponibilidade_tempo"] = disp_pid.get(r["plant_id"])
    return {
        "rows": rows,
        "summary": {
            "usinas":  len(rows),
            "trackers": sum(r["total"] for r in rows),
            "severos": sum(r["severos"] for r in rows),
            "leves":   sum(r["leves"] for r in rows),
            "novos":        sum(r.get("novos") or 0 for r in rows),
            "acompanhados": sum(r.get("acompanhados") or 0 for r in rows),
            "normalizados": sum(r.get("normalizados") or 0 for r in rows),
        },
        "cache_ts": datetime.now().strftime("%H:%M:%S"),
    }


@app.route("/api/sunop/trackers")
@app.route("/api/axis/trackers")
def api_sunop_trackers():
    inst = "axis" if flask_request.path.startswith("/api/axis/") else "gridco"
    force = flask_request.args.get("force", "0") == "1"
    return jsonify(_swr(_si(inst)["trk_cache"], lambda: _build_sunop_trk_payload(inst), force))


@app.route("/api/sunop/trackers/<plant_name>")
@app.route("/api/axis/trackers/<plant_name>")
def api_sunop_trackers_plant(plant_name):
    inst = "axis" if flask_request.path.startswith("/api/axis/") else "gridco"
    ensure_sunop_meta(inst)
    return jsonify(_sunop_trackers_plant_curva(plant_name, inst))   # análise por curva do dia


# ── SunOp: HISTÓRICO intradiário (endpoint /data/v2/analog_values) ─────────────
#   Descoberto via DevTools: POST com pathnames no corpo + start/end na query.
#   Serve curva do dia de QUALQUER medida analógica (tracker POSAT/POSAL, POA, GHI…),
#   inclusive datas passadas (source=Historical).
def _sunop_analog_history(pathnames: list, start: str, end: str, inst: str = "gridco") -> dict:
    """→ {pathname: [(timestamp, value), ...]} ordenado por tempo."""
    H = _sunop_headers(inst)
    data_url = _si(inst)["data"]
    params = {"fill_missing": "false", "source": "Historical",
              "start_time": start, "end_time": end, "use_plant_timezone": "true"}
    batches = [pathnames[i:i + 40] for i in range(0, len(pathnames), 40)]

    def _fetch(batch):
        try:
            r = _http().post(f"{data_url}/v2/analog_values", headers=H,
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
_sunop_str_med_cache = {}   # (plant_name, dia) -> {"ts","med"} — mediana das strings da USINA inteira


def _sunop_str_med_ent(plant_name: str, dia: str, inst: str = "gridco") -> dict:
    """Entrada cacheada {med, curva} da mediana das strings da USINA (todos os inversores):
      • med   = mediana da energia (∫corrente no dia) de todas as strings — referência p/ comparar
                inversores ENTRE si (pega o inversor inteiro em baixa).
      • curva = mediana REAL por instante (HH:MM) da corrente de todas as strings — MESMA referência
                do gráfico de correlação (mediana dos pares), p/ a Curva do inversor não usar proxy.
    A busca do histórico de todas as strings já era feita p/ 'med', então a curva sai quase de graça.
    Cacheada por (usina, dia)."""
    cache = _si(inst)["str_med_cache"]
    key = (plant_name, dia)
    ent = cache.get(key)
    if ent and (time.time() - ent["ts"]) < CACHE_TTL and "curva" in ent:
        return ent
    meta = _si(inst)["meta"].get(plant_name)
    med = 0.0
    curva = {"x": [], "y": []}
    if meta:
        inv_strings = meta["inv_strings"]
        allp = [p for ps in inv_strings.values() for p in ps]
        hist = _sunop_analog_history(allp, f"{dia}T00:00:00", f"{dia}T23:59:59", inst)
        somas = []
        vivas = {}   # {path: serie}  — strings vivas (não trancadas)
        for inv_name, ps in inv_strings.items():
            for p in ps:
                if _str_key(plant_name, inv_name, p.split(".")[-1]) in _trancadas:
                    continue
                serie = hist.get(p, [])
                if serie:
                    somas.append(sum(max(0.0, v) for _, v in serie))
                    # timestamp -> "HH:MM" (o _str_grades usa _str_min_of, que só casa HH:MM ancorado —
                    # datetime/ISO cru quebra), mesma conversão do builder da curva por string.
                    vivas[p] = [(str(t)[11:16], max(0.0, v)) for t, v in serie]
        somas.sort()
        med = somas[len(somas) // 2] if somas else 0.0
        # mediana REAL por instante na grade STR_EV (06–18h/10min) — reamostra p/ alinhar a fase
        # de loggers diferentes (bucket por HH:MM cru enviesa: cada minuto pega poucas strings). É a
        # MESMA grade/lógica da "mediana dos pares" do gráfico de correlação.
        ncells = (STR_EV_WIN_FIM - STR_EV_WIN_INI) // STR_EV_STEP + 1
        grids = _str_grades(vivas, ncells)
        gx, gy = _corr_xs(), []
        for i in range(ncells):
            vv = sorted(g[i] for g in grids.values() if g[i] is not None)
            gy.append(round(vv[len(vv) // 2], 2) if vv else None)
        curva = {"x": gx, "y": gy}
    ent = {"ts": time.time(), "med": med, "curva": curva}
    cache[key] = ent
    return ent


def _sunop_str_med_usina(plant_name: str, dia: str, inst: str = "gridco") -> float:
    """Mediana da energia diária das strings da usina (escalar). Ver _sunop_str_med_ent."""
    return _sunop_str_med_ent(plant_name, dia, inst)["med"]


def _sunop_strings_curva(plant_name: str, dia: str, inv=None, inst: str = "gridco") -> dict:
    ensure_sunop_meta(inst)
    meta = _si(inst)["meta"].get(plant_name)
    if not meta:
        return {"plant_id": plant_name, "data": dia, "inversores": []}
    med_ent = _sunop_str_med_ent(plant_name, dia, inst)       # referência da USINA (escalar + curva real)
    med_usina = med_ent["med"]
    inv_strings = meta["inv_strings"]
    nomes = [inv] if (inv and inv in inv_strings) else list(inv_strings.keys())
    allp  = [p for n in nomes for p in inv_strings.get(n, [])]
    hist  = _sunop_analog_history(allp, f"{dia}T00:00:00", f"{dia}T23:59:59", inst)

    def _invnum(x):                       # ordena gridco (INV_1) e axis (SKID_1.LVDB_1.INV_3)
        return _sunop_invnum(x)

    def _pvnum(x):
        t = x.rsplit("I_PV", 1)[-1]
        return int(t) if t.isdigit() else 999

    out = []
    for inv_name in sorted(nomes, key=_invnum):
        soma, curva = {}, {}
        for p in sorted(meta["inv_strings"][inv_name], key=_pvnum):
            # string trancada (🔒, MPPT sem string) sai da curva — chave igual à da tabela
            # (_strChipSimple/trancaStr): plant_name | inv_name | id (último segmento do path)
            if _str_key(plant_name, inv_name, p.split(".")[-1]) in _trancadas:
                continue
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
        ref = med_usina if med_usina > 0 else med   # compara com a USINA inteira (cai p/ inversor se sem base)
        strings, abaixo = [], 0
        for lbl in sorted(soma, key=_spv_stnum):
            e = soma[lbl]; sub = (ref > 0 and e < ref * SPV_SUB_FRAC); abaixo += 1 if sub else 0
            strings.append({"nome": lbl, "ativa": e > 0, "sub": sub,
                            "energia": round(e, 1), "pct": round(100.0 * e / ref) if ref else None})
        out.append({"id": inv_name, "nome": _sunop_inv_display(plant_name, inv_name),
                    "nome_api": inv_name, "curva": curva, "mediana": round(med, 1),
                    "mediana_usina": round(med_usina, 1), "abaixo": abaixo, "strings": strings})
    _marca_inv_sub(out)
    return {"plant_id": plant_name, "data": dia, "inversores": out,
            "mediana_usina": round(med_usina, 1),
            "mediana_usina_curva": med_ent.get("curva")}   # mediana REAL da usina por instante


_sunop_curva_cache = {}   # (plant_name, dia, inv) -> {"ts", "payload"} — curva por inversor/dia


@app.route("/api/sunop/curva/<plant_name>")
@app.route("/api/axis/curva/<plant_name>")
def api_sunop_curva(plant_name):
    inst = "axis" if flask_request.path.startswith("/api/axis/") else "gridco"
    dia = (flask_request.args.get("data") or datetime.now().strftime("%Y-%m-%d")).strip()
    if re.match(r"^\d{2}/\d{2}/\d{4}$", dia):
        dia = datetime.strptime(dia, "%d/%m/%Y").strftime("%Y-%m-%d")
    inv = (flask_request.args.get("inv") or "").strip() or None   # opcional: só um inversor (inv_name)
    force = flask_request.args.get("force", "0") == "1"
    cache = _si(inst)["curva_cache"]
    key = (plant_name, dia, inv)
    ent = cache.get(key)
    if ent and not force and (time.time() - ent["ts"]) < CACHE_TTL:
        return jsonify(ent["payload"])
    try:
        payload = _sunop_strings_curva(plant_name, dia, inv, inst)
        cache[key] = {"ts": time.time(), "payload": payload}
        return jsonify(payload)
    except Exception as e:
        return jsonify({"error": str(e), "inversores": []}), 500


@app.route("/api/axis/usinas")
def api_axis_usinas():
    """Usinas da instância Axis (PE III, Ponto Belo 1) + inversores — alimenta a aba Axis SunOp.
    Lê só a metadata (lazy, cacheada); a curva de strings por inversor vem de /api/axis/curva."""
    ensure_sunop_meta("axis")
    meta = _si("axis")["meta"]

    def _n(x):
        try: return int(x.split("_")[1])
        except Exception: return 999

    rows = []
    for pname in sorted(meta):
        invs = sorted(meta[pname]["inv_strings"].keys(), key=_n)
        rows.append({"id": pname, "usina": pname,
                     "inversores": [{"id": iv, "nome": EQUIP_NAMES.get(pname, {}).get(iv, iv)}
                                    for iv in invs]})
    return jsonify({"rows": rows, "total": len(rows)})


# ── SunOp (Athon): PR por inversor ─────────────────────────────────────────────
#   PR_inv = geração_inv_dia (EPD, kWh) ÷ (IPOA_dia × potência_inv). EPD = MAX da
#   energia diária do inversor no histórico; IPOA = integração trapezoidal do POA
#   do ETM SunOp; potência do Equipamentos (POWER_INV). Mesmo formato do /api/pg/pr.
#   O POA do SunOp é bem calibrado (PR realista ~0,6-0,8), diferente do PG.
_sunop_pr_cache = {}
_sunop_pr_lock  = threading.Lock()


def _sunop_pr_one(plant_name: str, dia: str, inst: str = "gridco"):
    """→ (ipoa, n_leituras_poa, [inversores]) de uma planta SunOp no dia."""
    meta = _si(inst)["meta"].get(plant_name) or {}
    epd  = {inv: o.get("EPD") for inv, o in (meta.get("inv_other") or {}).items() if o.get("EPD")}
    stations = meta.get("etm_stations") or {}
    # prioriza a POA REAL (plant_paths["POA"], já priorizada p/ METEOST sobre AIML); cai p/ 1ª estação
    poa_path = ((meta.get("plant_paths") or {}).get("POA")
                or next((p["poa"] for p in stations.values() if p.get("poa")), f"{plant_name}.ESTM.POA.IRAD"))
    hist  = _sunop_analog_history(list(epd.values()) + [poa_path], f"{dia}T00:00:00", f"{dia}T23:59:59", inst)
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


def _sunop_pr_build(dia: str, inst: str = "gridco"):
    ensure_sunop_meta(inst)
    plantas = [p for p, m in _si(inst)["meta"].items() if m.get("inv_strings")]

    def _one(pn):
        try:    return pn, _sunop_pr_one(pn, dia, inst)
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


def _sunop_pr_get(dia: str, force=False, inst: str = "gridco"):
    agora = time.time()
    cache = _si(inst)["pr_cache"]
    with _sunop_pr_lock:
        ent = cache.get(dia)
        if not force and ent and (agora - ent["ts"]) < CACHE_TTL:
            return ent["summary"], ent["detail"]
        summary, detail = _sunop_pr_build(dia, inst)
        cache[dia] = {"ts": agora, "summary": summary, "detail": detail}
        return summary, detail


@app.route("/api/sunop/pr")
@app.route("/api/axis/pr")
def api_sunop_pr():
    inst = "axis" if flask_request.path.startswith("/api/axis/") else "gridco"
    dia = _pr_dia_arg()
    force = flask_request.args.get("force", "0") == "1"
    try:
        summary, _ = _sunop_pr_get(dia, force, inst)
    except Exception as e:
        return jsonify({"error": str(e), "rows": [], "data": dia, "summary": {}}), 500
    return jsonify({"rows": summary, "data": dia,
                    "summary": {"usinas": len(summary), "inversores": sum(r["total"] for r in summary),
                                "abaixo": sum(r["abaixo"] for r in summary),
                                "sem_pot": sum(r["sem_pot"] for r in summary)},
                    "cache_ts": datetime.now().strftime("%H:%M:%S")})


@app.route("/api/sunop/pr/<plant_name>")
@app.route("/api/axis/pr/<plant_name>")
def api_sunop_pr_plant(plant_name):
    inst = "axis" if flask_request.path.startswith("/api/axis/") else "gridco"
    dia = _pr_dia_arg()
    try:
        _, detail = _sunop_pr_get(dia, inst=inst)
    except Exception as e:
        return jsonify({"error": str(e), "inversores": []}), 500
    return jsonify({"plant_id": plant_name, "data": dia, "inversores": detail.get(plant_name, [])})


@app.route("/api/sunop/trackers/<plant_name>/chart")
@app.route("/api/axis/trackers/<plant_name>/chart")
def api_sunop_trackers_chart(plant_name):
    inst = "axis" if flask_request.path.startswith("/api/axis/") else "gridco"
    ensure_sunop_meta(inst)
    trk = (_si(inst)["meta"].get(plant_name, {}) or {}).get("trackers") or {}
    if not trk:
        return jsonify({"plant": plant_name, "trackers": [], "alvo": None})
    ini, fim, ndias = _trk_chart_range()
    cur = _sunop_trk_curvas(plant_name, ini, inst) if ndias == 1 \
        else _sunop_trk_curvas_range(plant_name, ini, fim, inst)   # intervalo: 1 chamada ao histórico
    posat, posal = cur["posat"], cur["posal"]
    _alvo_max = _trk_chart_down_alvo(ndias)

    def _down(serie):
        step = max(1, len(serie) // _alvo_max)
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
    return jsonify({"plant": USINA_DISPLAY.get(plant_name, plant_name), "date": ini,
                    "ini": ini, "fim": fim, "ndias": ndias, "trackers": trackers, "alvo": alvo})


# ── SunOp/Axis: Trackers parados (agora) + Ocorrências (travou→voltou) — espelho das sub-abas API PV ──
#   Curva via _sunop_trk_curvas (cacheada, API analógica) → Ocorrências on-demand por dia (paralelizado).
def _sunop_curve_for(plant_name, data_br, inst):
    """Curva ATUAL por tracker no formato do motor de eventos: {tracker: [{x,y}]}."""
    try:
        date_iso = datetime.strptime(data_br, "%d/%m/%Y").strftime("%Y-%m-%d")
    except Exception:
        date_iso = data_br
    cur = _sunop_trk_curvas(plant_name, date_iso, inst)
    return {n.replace("TRK_", "Tracker "): [{"x": ts, "y": v} for ts, v in s]
            for n, s in cur.get("posat", {}).items() if s}


def _sunop_parados_rows(inst, force=False):
    ensure_sunop_meta(inst)
    if force:
        _si(inst)["trk_hist"].clear()          # busta as curvas do dia → recomputa o status do zero
    plantas = [p for p, m in _si(inst)["meta"].items() if m.get("trackers")]
    rows = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_sunop_trackers_plant_curva, p, inst): p for p in plantas}
        for f in as_completed(futs):
            try:
                a = f.result()
            except Exception:
                continue
            for t in a.get("trackers", []):
                if t.get("status") == "parado":
                    desde = _trk_parado_desde_hist(a["plant_id"], t["id"])   # varredura da curva (mesma do PV)
                    hrs = dias = None
                    if desde:
                        try:
                            _sec = (datetime.now() - datetime.fromisoformat(desde)).total_seconds()
                            hrs, dias = round(_sec / 3600, 1), int(_sec // 86400)
                        except Exception:
                            pass
                    rows.append({"plant_id": a["plant_id"], "usina": a["usina"], "tracker": t["id"],
                                 "inversor": "", "atual": t.get("atual"), "alvo": t.get("alvo"),
                                 "disparidade": t.get("disparidade"), "amplitude": t.get("amplitude"),
                                 "na_planilha": bool(t.get("na_planilha")), "ticket_status": t.get("ticket_status"),
                                 "parado_desde": desde, "horas_parado": hrs, "dias_parado": dias,
                                 "ultima_leitura": a.get("ultima_leitura")})
    rows.sort(key=lambda r: (r["usina"], _pv_trk_num(r["tracker"])))
    return _trk_geo_annotate(rows)


@app.route("/api/sunop/trackers/parados")
@app.route("/api/axis/trackers/parados")
def api_sunop_trackers_parados():
    inst = "axis" if flask_request.path.startswith("/api/axis/") else "gridco"
    rows = _sunop_parados_rows(inst, force=flask_request.args.get("force") == "1")
    return jsonify({"rows": rows, "total": len(rows), "cache_ts": datetime.now().strftime("%H:%M:%S")})


_sunop_ev_cache = {"gridco": {}, "axis": {}}


def _sunop_eventos_calc(inst, date_iso):
    """Calcula (e cacheia) as ocorrências + disponibilidade por tempo do SunOp/Axis num dia.
    disp_pid chaveado pelo código interno da planta (ex.: 'MRO100') — mesma chave do overview."""
    hoje_iso = datetime.now().strftime("%Y-%m-%d")
    cache = _sunop_ev_cache[inst]
    ent = cache.get(date_iso)
    if ent and (date_iso != hoje_iso or (time.time() - ent["ts"]) < CACHE_TTL):
        return ent
    data_br = datetime.strptime(date_iso, "%Y-%m-%d").strftime("%d/%m/%Y")
    dd = date_iso.split("-")
    plantas = [p for p, m in _si(inst)["meta"].items() if m.get("trackers")]

    def _um(p):
        un = USINA_DISPLAY.get(p, p)
        try:
            res = _trk_eventos_do_dia(p, p, data_br, curve=_sunop_curve_for(p, data_br, inst))
        except Exception:
            return un, p, None, []
        # PERSISTE os eventos no histórico global (mesmo store do PV, pid=plant_name, tracker="Tracker N")
        # → habilita a varredura "parado desde" do SunOp (_trk_parado_desde_hist). Formato idêntico ao PV.
        if res.get("eventos") is not None:
            with _trk_eventos_lock:
                _trk_eventos.setdefault(date_iso, {})[str(p)] = {
                    "nome": un, "ts": time.time(),
                    "cobertura": res.get("cobertura", 0), "eventos": res["eventos"]}
        rws = [{"data_iso": date_iso, "data": f"{dd[2]}/{dd[1]}", "usina": un, "tracker": ev["tracker"],
                "inversor": "", "parada": ev["parada"], "retorno": ev.get("retorno"), "dur_min": ev.get("dur_min")}
               for ev in res["eventos"]]
        return un, p, res.get("disponibilidade"), rws
    rows, disp, disp_pid = [], {}, {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for un, pid, dsp, part in ex.map(_um, plantas):
            rows.extend(part)
            if dsp is not None:
                disp[un] = dsp
                disp_pid[pid] = dsp
    rows.sort(key=lambda r: (r["usina"], r["parada"]))
    ent = {"ts": time.time(), "rows": rows, "disp": disp, "disp_pid": disp_pid}
    cache[date_iso] = ent
    try:
        _trk_ev_save()          # persiste o histórico (agora com o SunOp) em disco → varredura sobrevive a restart
    except Exception:
        pass
    return ent


def _sunop_disp_hoje(inst):
    """Disponibilidade por tempo (hoje) por plant_id — reusa/aquece o cache de Ocorrências."""
    hoje_iso = datetime.now().strftime("%Y-%m-%d")
    try:
        return _sunop_eventos_calc(inst, hoje_iso).get("disp_pid", {})
    except Exception:
        return {}


@app.route("/api/sunop/trackers/eventos")
@app.route("/api/axis/trackers/eventos")
def api_sunop_trackers_eventos():
    inst = "axis" if flask_request.path.startswith("/api/axis/") else "gridco"
    ensure_sunop_meta(inst)
    ini = (flask_request.args.get("ini") or datetime.now().strftime("%Y-%m-%d")).strip()
    date_iso = ini if re.match(r"^\d{4}-\d{2}-\d{2}$", ini) else datetime.now().strftime("%Y-%m-%d")
    ent = _sunop_eventos_calc(inst, date_iso)
    return jsonify({"rows": ent["rows"], "disp": ent.get("disp", {}), "ini": date_iso, "fim": date_iso, "total": len(ent["rows"]),
                    "data_ini_hist": "2026-06-01", "progresso": {}})


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


# ── Plataforma: COMBINER/String Box por inversor (destrava as usinas String Box) ─────────────────
# A API PV não expõe corrente por string nessas usinas (day_inverter dá ≤1 Ipv por inversor), mas a
# Plataforma expõe: /v2/inversores/view?id=<idinversor> → combiner.leitura Ipv1..N. Os ids de
# inversor são os MESMOS da API PV (confirmado 03/07: 49687 = "Inversor 1.1" da usina 60560).
# É SNAPSHOT (sem curva por string) → régua instantânea, como o PG.
_plat_view_cache = {}   # idinversor -> {ts, dados|None}


def _plat_combiner_strings(idinv):
    """→ {"strings": [(IpvN, corrente_A)], "ts": "YYYY-MM-DD HH:MM:SS"} ou None (sem combiner/token).
    Cache 5 min por inversor; o 'GMT' do tsleitura é sufixo falso (horário já vem local, como nos
    trackers)."""
    if not _plat_token():
        return None
    ent = _plat_view_cache.get(idinv)
    if ent and (time.time() - ent["ts"]) < CACHE_TTL:
        return ent["dados"]
    dados = None
    try:
        r = _http().get(f"{PLAT_BASE}/v2/inversores/view", headers=_plat_headers(),
                        params={"id": idinv}, timeout=25)
        j = r.json() if r.status_code == 200 else {}
        cmb = j.get("combiner") or {}
        lei = cmb.get("leitura") or {}
        strings = sorted(((k, float(v)) for k, v in lei.items()
                          if k.startswith("Ipv") and isinstance(v, (int, float))),
                         key=lambda t: _pv_trk_num(t[0]))
        if strings:
            ts = ""
            try:
                ts = datetime.strptime(str(cmb.get("tsleitura")).replace("GMT", "").strip(),
                                       "%a, %d %b %Y %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
            dados = {"strings": strings, "ts": ts}
    except Exception as e:
        print(f"[combiner] view {idinv}: {e}")
    _plat_view_cache[idinv] = {"ts": time.time(), "dados": dados}
    return dados


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
        c_sk = next((c for c in df.columns if "skid" in c.lower()), None)
        m = {}   # usina_norm → {skid_str: {"nums": {int: status}, "statuses": set}}  (skid "" = sem skid)
        for _, row in df.iterrows():
            st = str(row[c_st]).strip()
            if not st or st.lower() in ("nan", "em conformidade"):
                continue
            u = _tk_norm(row[c_us])
            if not u:
                continue
            sk = ""
            if c_sk and pd.notna(row[c_sk]):
                sk = re.sub(r"\.0$", "", str(row[c_sk]).strip())   # "1.0" → "1"
            try:
                n = int(float(row[c_nt]))
            except (TypeError, ValueError):
                n = None
            e = m.setdefault(u, {}).setdefault(sk, {"nums": {}, "statuses": set()})
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


def _tickets_lookup(plant_norm, skid=None):
    """→ ({"nums","statuses"}|None, ambiguo). Casa exato por nome (senão por prefixo, marcando
    ambíguo). Com `skid`: casa o SKID exato — cruzamento CONFIÁVEL (os nº de tracker se repetem
    entre skids). Sem `skid`: agrega todos os skids da usina (comportamento das usinas únicas)."""
    e = TICKETS_TRK.get(plant_norm)
    ambiguo = False
    if not e:
        for k, v in TICKETS_TRK.items():
            if plant_norm == k or plant_norm.startswith(k + " "):
                e, ambiguo = v, True
                break
    if not e:
        return None, False
    if skid is not None:
        skid = str(skid)
        if skid in e:
            return e[skid], ambiguo                      # SKID exato → confiável
        if any(k for k in e):                            # usina separa por skid, mas não tem este
            return {"nums": {}, "statuses": set()}, ambiguo
        # planilha não separa por skid (só "") → cai no agregado abaixo
    nums, statuses = {}, set()
    for v in e.values():
        nums.update(v.get("nums", {}))
        statuses |= v.get("statuses", set())
    multi = sum(1 for k in e if k) > 1
    return {"nums": nums, "statuses": statuses}, (ambiguo or (skid is None and multi))


load_tickets_trackers()   # carga inicial


# Detecção por desvio vs a MEDIANA DA FROTA — independe do alvo, que na API PV pode vir tão
# furado quanto o tracker travado (ex.: Saturnino TRK22, cujo posAl também travou em 43.9°).
TRK_PV_DESVIO_FROTA = 10.0   # ° — desvio do tracker vs a mediana da frota = anômalo (instantâneo e curva)
_pv_trk_graf_cache  = {}     # (idusina, data) -> {ts, g}: grafico cru do trackerschart (reusa detalhe+chart)
_pv_trk_graf_locks  = {}     # (idusina, data) -> Lock: DEDUP de fetch concorrente (1 busca por chave)
_pv_trk_graf_lock_guard = threading.Lock()


def _pv_trk_grafico(idusina, data: str, fetch: bool = True) -> dict:
    """Curva crua do dia (PV Plataforma /v2/usinas/trackerschart) → {tracker: [{x,y}]}. Cacheada
    por (usina, data). fetch=False → SÓ o cache (não dispara o trackerschart, que é pesado ~46k–104k
    pontos e pode passar de 90s) — usado no refino do detalhe p/ não travar/zerar a detecção."""
    hoje = datetime.now().strftime("%d/%m/%Y")
    key, agora = (idusina, data), time.time()
    ent = _pv_trk_graf_cache.get(key)
    if ent and ((data != hoje and ent["g"]) or (agora - ent["ts"]) < CACHE_TTL):
        return ent["g"]
    if not fetch:
        # melhor-esforço: o refino do overview usa a ÚLTIMA curva cacheada (mesmo > TTL). O job de
        # eventos reabastece o cache a cada 30 min, então a linha-pai fica curva-ciente sem rebater
        # o trackerschart (pesado) a cada refresh do overview.
        return (ent or {}).get("g") or {}
    # DEDUP de fetch concorrente: 1 só busca por (usina,data) mesmo com N requests simultâneos
    # (mini-curvas do grupo + refino + detalhe) — evita N× trackerschart pesado e protege o Plataforma.
    with _pv_trk_graf_lock_guard:
        lk = _pv_trk_graf_locks.setdefault(key, threading.Lock())
    with lk:
        ent = _pv_trk_graf_cache.get(key)                 # re-check: outro thread já pode ter buscado
        if ent and ((data != hoje and ent["g"]) or (time.time() - ent["ts"]) < CACHE_TTL):
            return ent["g"]
        try:
            r = _http().get(f"{PLAT_BASE}/v2/usinas/trackerschart", headers=_plat_headers(),
                            params={"idusina": idusina, "dataleitura": data}, timeout=90)
            g = (r.json() or {}).get("grafico") or {}
        except Exception:
            g = {}
        if g:
            _pv_trk_graf_cache[key] = {"ts": time.time(), "g": g}
            return g
        # busca vazia/falha (timeout/throttle sob carga): NÃO cacheia vazio — senão "Sem curva" gruda
        # por 5 min mesmo o Plataforma já devolvendo dado. Devolve a última curva boa.
        return (ent or {}).get("g") or {}


def _pv_trk_refina_curva(idusina, lst, date, fetch=False):
    """Refina o status pela CURVA do dia — MESMA lógica do `_trkWindowDetect` do front (única fonte de
    verdade p/ não divergir linha-pai × expandir): janela diurna 07:00–18:00, "parado" por (frota
    girou e ele <15°) OU (P75 dos funcionais) OU (girou de manhã e travou = cauda plana), "desvio" por
    saiu >10° da mediana da frota em algum momento; NUNCA rebaixa um 'parado' já detectado nem o
    desvio/atraso do instantâneo. Pega o que o instantâneo perde: o tracker que CONGELOU num ângulo
    que o sol depois cruza (|atual-alvo|≈0 naquele instante → escapava da linha-pai).
    fetch=False (padrão) usa SÓ a curva já cacheada — reabastecida pelo job de eventos; fetch=True
    (ronda/force) baixa a curva que faltar (boot frio zerava a detecção e a ronda saía vazia)."""
    g = _pv_trk_grafico(idusina, date or datetime.now().strftime("%d/%m/%Y"), fetch=fetch)
    if not g:
        return
    JIni, JFim = 7 * 60, 18 * 60                     # janela diurna (min do dia), igual ao front
    def _mins(x):
        m = re.search(r"(\d{1,2}):(\d{2})", str(x))
        return int(m.group(1)) * 60 + int(m.group(2)) if m else None
    ser = {}
    for name, pts in g.items():
        s = [(p.get("x"), p.get("y")) for p in (pts or [])
             if isinstance(p.get("y"), (int, float))
             and (_mins(p.get("x")) is not None and JIni <= _mins(p.get("x")) <= JFim)]
        if s:
            ser[name] = s
    if len(ser) < 5:
        return
    by_ts = {}
    for s in ser.values():
        for x, y in s:
            by_ts.setdefault(x, []).append(y)
    fleet = {x: sorted(v)[len(v) // 2] for x, v in by_ts.items() if v}   # mediana da frota por ts
    # amplitude ROBUSTA (p02–p98, mata spike de telemetria — mesma régua do SunOp, caso Tracker 82);
    # a janela diurna já está aplicada (ser = só pontos 07–18h)
    amps = {n: _amp_robusta([y for _, y in s]) for n, s in ser.items()}
    amps_sorted = sorted(a for a in amps.values() if a is not None)
    p75     = amps_sorted[int(len(amps_sorted) * 0.75)] if amps_sorted else 0.0
    moved_p75 = p75 > 30                             # há trackers funcionais (25% mais móveis) = o que a planta CONSEGUIU no dia
    # (a antiga 'moved' (mediana>30) virou a porta 1 do _frota_acordou — o gate já garante a referência)
    # span coberto na janela → régua ABSOLUTA (MESMA das outras fontes): pega a usina INTEIRA parada,
    # que os testes de "frota girou" (moved/moved_p75) perderiam quando ninguém mexeu.
    _allmin = [_mins(x) for x in by_ts if _mins(x) is not None]
    dia_coberto = (len(_allmin) >= 2 and (max(_allmin) - min(_allmin)) / 60.0 >= TRK_COBERTURA_MIN_H)
    for t in lst:
        s = ser.get(t["id"])
        if not s:
            continue                                 # sem curva na janela p/ este tracker → mantém o status do servidor
        amp = amps.get(t["id"])
        ys = [y for _, y in s]
        k = max(3, int(len(ys) * 0.4))
        tail = ys[-k:]                               # cauda do dia (~últimos 40% das amostras)
        tail_amp = (max(tail) - min(tail)) if tail else None
        devs = [abs(y - fleet[x]) for x, y in s if x in fleet]
        max_dev = max(devs) if devs else 0.0
        cur_dev = devs[-1] if devs else 0.0
        t["amplitude"] = round(amp, 1) if amp is not None else None
        t["max_disp"] = round(max_dev, 1)
        if t.get("atual") is None and ys:            # Plataforma sem 'ultimaleitura' (posAg) → usa o
            t["atual"] = round(ys[-1], 1)            # último ponto da curva = ângulo onde travou
        if t.get("disparidade") is None or cur_dev > t["disparidade"]:
            t["disparidade"] = round(cur_dev, 2)     # badge mostra o maior desvio vs frota (mais fiel)
        sv = t["status"]                             # status já detectado (instantâneo/acumulador)
        st = "normal"
        if not _frota_acordou(amps, dia_coberto, date):
            st = "normal"                            # gate do Levi: usina ainda DORMINDO (madrugada/manhã, ninguém girou) → ninguém parado
        elif amp is not None and amp < TRK_PARADO_AMP:
            st = "parado"                            # frota acordou (girou OU já devia ter girado) e ele quase não mexeu = travado
        elif moved_p75 and amp is not None and amp < min(20, p75 * 0.3):
            st = "parado"                            # planta meio parada — referência pelos funcionais (P75)
        elif amp is not None and amp >= 20 and tail_amp is not None and tail_amp < 5 and cur_dev > TRK_DESVIO_MIN:
            st = "parado"                            # girou de manhã e TRAVOU LONGE do alvo (cauda plana
                                                     # + desviado da frota agora). O 'cur_dev>5' evita o
                                                     # falso da MANHÃ, quando a cauda é plana p/ todos (giro lento)
        elif max_dev > 10:
            st = "desvio"                            # saiu da frota >10° em algum momento da janela
        # NÃO preserva o desvio/atraso INSTANTÂNEO (vinha de |atual-ALVO| e o alvo da API PV é furado).
        # Preserva o 'parado' do acumulador SÓ se a curva NÃO o contradiz: se o tracker ACOMPANHOU a
        # frota (amplitude cheia + colado: amp>=30 e max_dev<=10), é 'normal' — mata falso positivo de
        # acumulador velho/sujo (ex.: TRK51/52 com amp 60° e 1,8° da frota). A curva vs FROTA é a verdade.
        if sv == "parado" and not (amp is not None and amp >= 30 and max_dev <= 10):
            st = "parado"
        t["status"] = st


def _pv_trackers_analise(idusina, nome_disp, date=None, curva=False, fetch_curvas=False) -> dict:
    """Analisa os trackers de UMA usina. Instantâneo (overview, rápido): disparidade |posAg-posAl|
    vs limiares. curva=True (detalhe, sob demanda): refina pela CURVA do dia (travado + desvio vs
    a mediana da frota) — pega o que o instantâneo perde. Formato compatível c/ a aba Trackers."""
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
            # NÃO classifica por |atual-ALVO|: o alvo da API PV é furado (tracker que acompanha a frota
            # tem |atual-alvo| alto e virava "desvio" falso, afundando a disponibilidade — pior ainda
            # quando "Sem curva" e o refino não roda). Começa 'normal'; o desvio vem da MEDIANA DA FROTA
            # (abaixo, instantâneo e sempre disponível) e o 'parado' do acumulador/curva.
            status = "normal"
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
    # Desvio vs a MEDIANA DA FROTA (instantâneo, rápido): pega o tracker fora do consenso AGORA —
    # robusto ao alvo furado (tracker travado cujo posAl também travou → |atual-alvo|=0). É o que o
    # |posAg-posAl| perdia: São Bento TRK42 (alvo o acompanhou) e Saturnino TRK22 (travado).
    angs = [t["atual"] for t in lst if t["atual"] is not None]
    if len(angs) >= 5:
        fleet_med = sorted(angs)[len(angs) // 2]
        for t in lst:
            if t["atual"] is None:
                continue
            df = abs(t["atual"] - fleet_med)
            if df > TRK_PV_DESVIO_FROTA and t["status"] == "normal":
                t["status"] = "desvio"
            t["disparidade"] = round(df, 2)           # disparidade exibida = desvio vs a FROTA (não vs alvo furado)
            t["max_disp"] = round(df, 2)
    if curva:        # detalhe: refina pela CURVA (cache; fetch_curvas=True baixa a que faltar — ronda)
        _pv_trk_refina_curva(idusina, lst, date, fetch=fetch_curvas)
    # Cruzamento com a planilha de Tickets. Na API PV cada SKID é uma usina ("Indaiatuba 1 (131)"
    # = Indaiatuba/Skid 1) → casa por SKID quando a planilha agrupa a usina (senão, pelo nome todo).
    m_sk = re.match(r"^(.*?)\s+(\d+)\s*(?:\(\d+\))?\s*$", str(nome_disp or ""))
    if m_sk and _tk_norm(m_sk.group(1)) in TICKETS_TRK:
        tick, ambiguo = _tickets_lookup(_tk_norm(m_sk.group(1)), m_sk.group(2))
    else:
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
    base.update({"total": len(lst), "tem_trackers": bool(lst), "sem_comunicacao": not atuais,
                 "severos": desv + par, "leves": atr, "desvios": desv, "atrasos": atr, "parados": par,
                 "parada_total": bool(lst) and par == len(lst),   # TODOS os trackers parados
                 "sem_alvo": all(t["alvo"] is None for t in lst) if lst else False,
                 "pior_disparidade": round(pior, 2) if pior is not None else None,
                 "desvio_medio": _trk_accum_desvio(idusina),
                 "media_angulo": round(sum(atuais) / len(atuais), 1) if atuais else None,
                 "ultima_leitura": _ult, "trackers": lst, "refinado": curva,
                 "tem_ticket": tick is not None, "ambiguo": ambiguo,
                 "novos": novos, "acompanhados": acomp, "normalizados": normalizados})
    _trk_alvo_mediana(base)   # fonte sem alvo → alvo inferido = mediana da frota (in-place)
    return base


def _build_pv_trk_payload(fetch_curvas=False):
    plants = get_plants(get_token())
    agora = time.time()
    alvo_plants = [p for p in plants if (not FULL_OM or p["nome"].strip() in FULL_OM)]
    rows = []
    parados_livro, cobertas = [], set()          # alimenta o livro de ocorrências (tracker_watch)
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_pv_trackers_analise, p["id"], nome_usina(p["id"], p["nome"]),
                          curva=True, fetch_curvas=fetch_curvas): p
                for p in alvo_plants}
        for f in as_completed(futs):
            try:
                r = f.result()
                if r.get("tem_trackers"):
                    r["grupo"] = USINA_GRUPO.get(futs[f]["nome"].strip())   # usina física do cadastro → agrupa sub-usinas
                    _pv_trk_plant[r["plant_id"]] = {"ts": agora, "payload": r}
                    rows.append({k: r[k] for k in ("plant_id", "usina", "total", "severos", "leves",
                                 "parados", "desvios", "atrasos",
                                 "fora_media", "pior_disparidade", "desvio_medio", "ultima_leitura",
                                 "media_angulo", "novos", "acompanhados", "normalizados",
                                 "tem_ticket", "ambiguo", "sem_comunicacao", "grupo")})
                    if not r.get("sem_comunicacao"):    # usina avaliada (com comm) → entra no livro
                        cobertas.add(r["plant_id"])
                        for t in (r.get("trackers") or []):
                            if t.get("status") == "parado":
                                parados_livro.append({
                                    "plant_id": r["plant_id"], "usina": r.get("usina"),
                                    "tracker": t.get("id"), "tracker_label": t.get("id"),
                                    "leitura": {"atual": t.get("atual"), "alvo": t.get("alvo"),
                                                "disparidade": t.get("disparidade")}})
            except Exception:
                pass
    if _TRACKER_WATCH_OK and cobertas:               # abre/fecha as ocorrências da API PV no livro único
        try:
            _tw.sync_api_pv(parados_livro, plants_cobertas=cobertas)
        except Exception as e:
            print(f"[trk_livro] sync_api_pv falhou: {e}")
    # ordena: mais NOVOS (fora da planilha) no topo, depois severidade
    rows.sort(key=lambda x: (not x.get("sem_comunicacao"), -(x.get("novos") or 0),
                             -(x["severos"] * 10 + x["leves"]), x["usina"]))
    hoje_iso = datetime.now().strftime("%Y-%m-%d")     # disponibilidade por TEMPO (janela 06:00–18:00)
    disp_pid = _trk_eventos_disp_by_id(hoje_iso, hoje_iso)   # só a persistência de hoje (sem backfill síncrono)
    for r in rows:
        r["disponibilidade_tempo"] = disp_pid.get(str(r["plant_id"]))
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
        # "Atualizar status" (force) = rebuild PROFUNDO: baixa a curva do dia que faltar no cache e
        # refina (frota girou e ele travou → 'parado', não 'desvio'). Sem isto o botão rebuildava LIGHT
        # (só curva já cacheada) e a linha-pai marcava 0 parados enquanto os cards da curva já mostravam
        # os travados (ex.: Mandaguaçu 31 parados caíam como 'desvio' na tabela). Warm = instantâneo;
        # cold = baixa em paralelo (8 workers), MESMO caminho que a ronda/parados já usa. O auto-refresh
        # (force=False) segue LIGHT, curva-ciente pelo job de eventos (30 min) — não martela o Plataforma.
        build = (lambda: _build_pv_trk_payload(fetch_curvas=True)) if force else _build_pv_trk_payload
        return jsonify(_swr(_pv_trk_cache, build, force))
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


@app.route("/api/pv/trackers/parada")
def api_pv_trackers_parada():
    """Alerta de tela: usinas com TODOS os trackers parados há >= TRK_PARADA_NOTIF_HORAS (a partir das
    9h). Leve — garante o cache do overview (SWR; força só na 1ª vez) e reconcilia o estado a partir
    dos payloads por-planta. O 'desde' (1ª observação) persiste entre restarts."""
    if not _plat_token():
        return jsonify({"alertas": [], "sem_token": True})
    try:
        _swr(_pv_trk_cache, _build_pv_trk_payload, force=not _pv_trk_plant)
    except Exception:
        pass
    estado = _trk_parada_reconcilia()
    agora = time.time()
    alertas, debug_cand = [], []
    hora_ok = datetime.now().hour >= TRK_PARADA_NOTIF_HORA_INI
    for key, ent in estado.items():
        horas = (agora - ent["desde"]) / 3600.0
        pid = int(key) if str(key).lstrip("-").isdigit() else key
        pl = (_pv_trk_plant.get(pid) or {}).get("payload", {})
        item = {"plant_id": pid, "usina": ent.get("usina") or pl.get("usina") or str(pid),
                "total": ent.get("total") or pl.get("total"), "horas": round(horas, 1),
                "desde": datetime.fromtimestamp(ent["desde"]).strftime("%H:%M"),
                "ultima_leitura": pl.get("ultima_leitura")}
        debug_cand.append(item)
        if hora_ok and horas >= TRK_PARADA_NOTIF_HORAS:
            alertas.append(item)
    alertas.sort(key=lambda a: -a["horas"])
    resp = {"alertas": alertas, "limite_horas": TRK_PARADA_NOTIF_HORAS,
            "cache_ts": datetime.now().strftime("%H:%M:%S")}
    if flask_request.args.get("debug") == "1":     # ?debug=1 → inspeção
        resp["debug"] = {"hora_ok": hora_ok, "hora_local": datetime.now().strftime("%H:%M"),
                         "candidatos": debug_cand, "n_pv_trk_plant": len(_pv_trk_plant)}
    return jsonify(resp)


def _pv_parados_rows(force=False, errout=None):
    """Lista de TODOS os trackers 'parado' (cruza as usinas via _pv_trk_plant). Nome pela coluna
    'Usina' (_macro_usina_nome) + inversor via BD_TRK_INV; 'parado desde' pelo histórico/livro.
    Devolve [] se sem token. errout: dict opcional — falha no recomputo vira mensagem VISÍVEL
    (a ronda mostrava 0 parados quando o rebuild quebrava calado)."""
    if not _plat_token():
        if errout is not None:
            errout["erro"] = "token da Plataforma ausente/vencido"
        return []
    _force = force
    try:
        # force (ronda) → re-puxa o snapshot de TODAS as usinas E baixa a curva do dia que estiver
        # faltando no cache (senão, após restart, o refino não roda e a ronda sai VAZIA em silêncio).
        # Em servidor quente as curvas já estão no cache (job de eventos, 30 min) → rápido.
        if _force or not _pv_trk_plant:
            _swr(_pv_trk_cache, lambda: _build_pv_trk_payload(fetch_curvas=True), force=True)
    except Exception as e:
        print(f"[pv parados] recomputo falhou: {e}")
        if errout is not None:
            errout["erro"] = f"recomputo falhou: {e}"
    try:
        nome_raw_by_pid = {p["id"]: p["nome"] for p in get_plants(get_token())}
    except Exception:
        nome_raw_by_pid = {}
    # "Parado desde": cruza com o LIVRO de ocorrências (tracker_watch), que persiste data_deteccao
    # por (plant_id|tracker) ENTRE DIAS e restarts — então sobrevive à virada do dia e ao reboot.
    livro = {}
    if _TRACKER_WATCH_OK:
        try:
            livro = (_tw.get_issues_json() or {}).get("active", {})
        except Exception:
            livro = {}
    rows = []
    for pid, ent in list(_pv_trk_plant.items()):
        pl = ent.get("payload") or {}
        if not pl.get("tem_trackers"):
            continue
        nome_raw = nome_raw_by_pid.get(pid) or pl.get("usina") or ""
        usina = _macro_usina_nome(nome_raw) or pl.get("usina") or str(pid)
        for t in (pl.get("trackers") or []):
            if t.get("status") != "parado":
                continue
            iss = livro.get(f"{pid}|{t.get('id')}") or {}
            # "Parado desde" = VARREDURA da curva (fonte de verdade: distingue intermitente de
            # travado, se auto-atualiza dia a dia). Livro só como fallback quando a curva não cobre.
            desde = _trk_parado_desde_hist(pid, t.get("id")) or iss.get("data_deteccao")
            horas = dias = None
            if desde:
                try:
                    _sec = (datetime.now() - datetime.fromisoformat(desde)).total_seconds()
                    horas, dias = round(_sec / 3600, 1), int(_sec // 86400)
                except Exception:
                    horas, dias = iss.get("horas_aberto"), iss.get("dias_aberto")
            rows.append({"plant_id": pid, "usina": usina, "tracker": t.get("id"),
                         "inversor": _bd_trk_lookup(nome_raw, _pv_trk_num(t.get("id"))) or "",
                         "atual": t.get("atual"), "alvo": t.get("alvo"),
                         "disparidade": t.get("disparidade"), "amplitude": t.get("amplitude"),
                         "na_planilha": bool(t.get("na_planilha")),
                         "ticket_status": t.get("ticket_status"),
                         "parado_desde": desde,                        # início contínuo (histórico)
                         "horas_parado": horas, "dias_parado": dias,
                         "ultima_leitura": pl.get("ultima_leitura")})
    rows.sort(key=lambda r: (r["usina"], _pv_trk_num(r["tracker"])))
    return _trk_geo_annotate(rows)


@app.route("/api/pv/trackers/parados")
def api_pv_trackers_parados():
    if not _plat_token():
        return jsonify({"rows": [], "sem_token": True, "erro": "token da Plataforma ausente/vencido"})
    err = {}
    rows = _pv_parados_rows(force=flask_request.args.get("force") == "1", errout=err)
    ts = max((e.get("ts", 0) for e in _pv_trk_plant.values()), default=0)
    return jsonify({"rows": rows, "total": len(rows), "erro": err.get("erro"),
                    "computado": datetime.fromtimestamp(ts).strftime("%H:%M") if ts else None,
                    "cache_ts": datetime.now().strftime("%H:%M:%S")})


# ══ Histórico de eventos: tracker INDIVIDUAL que travou → voltou (por dia, desde 01/06) ══════════
# Detecta na CURVA do dia, por tracker, RELATIVO À FROTA (travado = ângulo ~plano enquanto a frota
# gira; descarta meio-dia lento e anoitecer, onde todos param). Ignora tracker/usina com falha de
# comunicação na maior parte do período (cobertura < limiar). Guarda por dia (arquivo próprio).
TRK_EV_DATA_INI    = "2026-06-01"    # início do histórico (a pedido — não pesar)
TRK_EV_STEP        = 10              # min — resolução da grade de detecção
TRK_EV_WIN_INI     = 6 * 60          # janela começa 06:00 (amanhecer) — o INÍCIO efetivo é DINÂMICO:
TRK_EV_WIN_FIM     = 18 * 60         #   detecta o "despertar" da frota (1ª variação) em vez de fixar 07:30
TRK_EV_WAKE        = 5.0             # ° — tracker que se afastou isto do amanhecer = "acordou" (saiu do stow)
TRK_EV_LOOKBACK    = 3               # células (=30 min) p/ medir movimento na janela deslizante (= tolerância)
TRK_EV_FLEET_RANGE = 3.0             # ° — a frota mexeu isto na janela → dá p/ julgar "travado"
TRK_EV_STUCK_RANGE = 1.5             # ° — tracker mexeu <= isto na janela → travado
TRK_EV_RESUME      = 3.0             # ° — voltou a mexer isto do patamar travado → retorno
TRK_EV_MIN_MIN     = 30              # min — duração mínima do travamento p/ virar ocorrência
TRK_EV_COBERTURA   = 0.5             # fração mínima de dados (senão = falha de comunicação no período)
# Régua de AMPLITUDE DIÁRIA: tracker que mal variou no dia inteiro (mesmo com saltos pontuais
# entre patamares estáticos: ex. 0°→25°→0°, amp=25°) é considerado parado o dia todo. Pega o
# caso que o onset/retorno em janela curta perdia (fechava em "retorno" no salto e nunca via que
# o tracker mal funcionou no dia).
TRK_EV_DESVIO      = 12.0            # ° — |ângulo − mediana da frota| acima disto = fora do alvo (desvio/atraso), conta como indisponível no tempo
# Stow leste matinal: o tracker fica em ~-55° esperando o sol nascer — NÃO é ocorrência. Se o
# evento detectado começa nesse patamar e o tracker sai do stow até o limite normal (10:30),
# descarta. Só vira ocorrência se ele ficar travado no stow MUITO além disso.
TRK_EV_STOW_ANG     = -55.0          # ° — ângulo aproximado do stow leste
TRK_EV_STOW_TOL     = 10.0           # ° — tolerância (-65° a -45° conta como stow)
TRK_EV_STOW_INI     = 7 * 60 + 30    # 07:30 — janela onde o stow é esperado
TRK_EV_STOW_FIM_MAX = 10 * 60 + 30   # 10:30 — limite p/ o tracker sair do stow sem virar ocorrência
_TRK_EV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trk_eventos.json")
_trk_eventos = {}      # {data_iso: {str(pid): {"nome","ts","cobertura","eventos":[...]}}}
_trk_eventos_lock = threading.Lock()
_trk_ev_prog = {"running": False, "feito": 0, "total": 0, "atual": "", "fim_ts": 0.0, "erro": ""}


def _trk_ev_load():
    global _trk_eventos
    try:
        if os.path.exists(_TRK_EV_PATH):
            with open(_TRK_EV_PATH, encoding="utf-8") as f:
                _trk_eventos = json.load(f) or {}
            print(f"[trk_ev] histórico: {sum(len(v) for v in _trk_eventos.values())} usina-dias carregados")
    except Exception as e:
        print(f"[trk_ev] snapshot ilegível ({e}) — começando vazio")


def _trk_ev_save():
    try:
        with _trk_eventos_lock:
            snap = json.dumps(_trk_eventos, ensure_ascii=False)
        tmp = _TRK_EV_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(snap)
        os.replace(tmp, _TRK_EV_PATH)
    except Exception as e:
        print(f"[trk_ev] falha ao salvar: {e}")


def _trk_min_x(x):
    m = re.search(r"(\d{1,2}):(\d{2})", str(x))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


_TRK_PARADO_MANHA  = 9 * 60          # parada <= 09:00 = travou de MANHÃ (não voltou do despertar)
_TRK_PARADO_ANOITE = 16 * 60 + 30    # retorno >= 16:30 (ou None) = não voltou de verdade, só anoiteceu


def _trk_parado_desde_hist(pid, tracker):
    """Desde quando o tracker está CONTINUAMENTE parado, VARRENDO a curva (trk_eventos) dia a dia
    de hoje p/ trás — a fonte de verdade (o livro reinicia/erra). Régua de um dia 'parado o dia
    todo': travou de MANHÃ (<= 09:00) E não voltou a girar no dia produtivo (retorno None ou já
    no anoitecer >= 16:30). Assim trackers INTERMITENTES (que voltam ao meio-dia) não são contados
    como parados de dias atrás. Dias SEM DADOS (cobertura 0) são ATRAVESSADOS (não quebram nem
    iniciam a sequência). Para no 1º dia que o tracker girou de verdade. Como varre a curva a cada
    chamada e a curva cresce todo dia, o valor se auto-atualiza. ISO 'YYYY-MM-DDTHH:MM' ou None."""
    desde = None
    d = datetime.now().date()
    hoje_d = d
    tracker = str(tracker)
    with _trk_eventos_lock:
        for _ in range(70):
            ent = (_trk_eventos.get(d.strftime("%Y-%m-%d")) or {}).get(str(pid))
            if ent is None or ent.get("cobertura", 0) == 0:   # buraco de dados → atravessa
                d -= timedelta(days=1)
                continue
            parou = None
            inicio_meio_dia = None    # dia PASSADO em que girou de manhã e TRAVOU no meio/fim do dia
            for e in ent.get("eventos", []):
                if str(e.get("tracker")) != tracker:
                    continue
                pm = _trk_min_x(e.get("parada"))
                rm = _trk_min_x(e.get("retorno")) if e.get("retorno") else None
                if pm is not None and pm <= _TRK_PARADO_MANHA and (rm is None or rm >= _TRK_PARADO_ANOITE):
                    parou = e.get("parada"); inicio_meio_dia = None
                    break
                if pm is not None and (rm is None or rm >= _TRK_PARADO_ANOITE):
                    # evento ABERTO no fim do dia com parada DEPOIS das 09:00:
                    if d == hoje_d:
                        # HOJE (dia parcial) = está parado AGORA (ex.: CPP100, 'parada' 11:20 porque o 1º
                        # movimento da frota foi o reset) — mantém a cadeia p/ os dias anteriores em vez
                        # de devolver 'recente'. Sem break: um evento 'dia todo' tem prioridade se vier.
                        parou = e.get("parada")
                    else:
                        # dia PASSADO: girou de manhã e travou no meio/fim do dia e NÃO voltou → é o
                        # COMEÇO REAL da cadeia (calibração Levi 07/07: MAB100 TRK11 travou 21/06 à
                        # tarde; antes esse dia quebrava a cadeia e o 'desde' pulava p/ o dia seguinte).
                        inicio_meio_dia = e.get("parada")
            if parou is not None:
                desde = f"{d.strftime('%Y-%m-%d')}T{parou}"   # continua p/ trás
                d -= timedelta(days=1)
                continue
            if inicio_meio_dia is not None:
                desde = f"{d.strftime('%Y-%m-%d')}T{inicio_meio_dia}"
            break                                              # começo da cadeia (ou dia que girou) → fim
    return desde


def _trk_eventos_do_dia(idusina, nome, data_br, curve=None):
    """Eventos travou→voltou dos trackers de UMA usina num dia (data_br = DD/MM/YYYY).
    Retorna {cobertura, eventos:[{tracker, parada 'HH:MM', retorno 'HH:MM'|None, dur_min}]}.
    curve = {tracker: [{x,y}]} pronto (outras fontes); se None, busca a curva da API PV (trackerschart)."""
    g = curve if curve is not None else _pv_trk_grafico(idusina, data_br, fetch=True)
    if not g:
        return {"cobertura": 0.0, "eventos": []}
    ncells = (TRK_EV_WIN_FIM - TRK_EV_WIN_INI) // TRK_EV_STEP + 1
    # Cobertura é relativa à janela JÁ DECORRIDA. HOJE às 10h só existem ~3h da janela 07:30–18:00 (10,5h);
    # com o denominador CHEIO a cobertura fica ~0,3 e TODAS as usinas seriam descartadas como "sem
    # comunicação" → Ocorrências do dia atual ficariam vazias até a tarde. Para hoje, conta só as células
    # até agora; dias passados usam a janela inteira.
    if data_br == datetime.now().strftime("%d/%m/%Y"):
        _agora_min = datetime.now().hour * 60 + datetime.now().minute
        ncells_cob = max(1, (min(TRK_EV_WIN_FIM, _agora_min) - TRK_EV_WIN_INI) // TRK_EV_STEP + 1)
    else:
        ncells_cob = ncells

    def _grid(pts):
        gr = [None] * ncells
        for p in (pts or []):
            mn = _trk_min_x(p.get("x")); y = p.get("y")
            if mn is None or not isinstance(y, (int, float)):
                continue
            if TRK_EV_WIN_INI <= mn <= TRK_EV_WIN_FIM:
                gr[(mn - TRK_EV_WIN_INI) // TRK_EV_STEP] = float(y)   # último valor da célula
        return gr

    grids = {name: _grid(pts) for name, pts in g.items()}
    fleet = []
    for i in range(ncells):
        vals = [gr[i] for gr in grids.values() if gr[i] is not None]
        fleet.append(sorted(vals)[len(vals) // 2] if vals else None)
    cob_usina = sum(1 for v in fleet if v is not None) / ncells_cob
    if cob_usina < TRK_EV_COBERTURA:          # falha de comunicação na maior parte do período (decorrido)
        return {"cobertura": round(cob_usina, 2), "eventos": []}

    def _rng(seq):
        s = [v for v in seq if v is not None]
        return (max(s) - min(s)) if len(s) >= 2 else None

    def _hhmm(i):
        mn = TRK_EV_WIN_INI + i * TRK_EV_STEP
        return f"{mn // 60:02d}:{mn % 60:02d}"

    # amplitude da FROTA no dia inteiro — referência p/ régua de "parado o dia todo"
    fleet_vals = [f for f in fleet if f is not None]
    amp_frota_dia = (max(fleet_vals) - min(fleet_vals)) if len(fleet_vals) >= 2 else 0.0
    # span de horas coberto pela curva hoje → só julga "parado o dia todo" após TRK_COBERTURA_MIN_H (4h),
    # senão de manhã cedo (todos ainda ~parados) viraria falso positivo. MESMA guarda das abas Overview/Parados.
    _cov = [i for i, f in enumerate(fleet) if f is not None]
    dia_coberto = (len(_cov) >= 2 and (_cov[-1] - _cov[0]) * TRK_EV_STEP / 60.0 >= TRK_COBERTURA_MIN_H)
    # régua do Levi (07/07): a usina só "acorda" quando METADE da frota girou (mediana>30°) — OU quando
    # já DEVIA ter acordado (dia coberto + após TRK_FROTA_ACORDA_HORA / dia passado) e ninguém girou =
    # frota TRAVADA (caso CPP100: 60/63 presos, a mediana nunca sobe). MESMO gate das abas ao vivo.
    frota_acordou = _frota_acordou([_amp_robusta([v for v in gr if v is not None]) for gr in grids.values()],
                                   dia_coberto, data_br)

    # DESPERTAR DINÂMICO DA FROTA: 1ª célula em que ALGUM tracker saiu do amanhecer (variou >= WAKE
    # da posição inicial). Antes disso (madrugada/stow) tracker parado é NORMAL → não se julga. Substitui
    # o corte fixo de 07:30: a contagem de "não acompanhou" começa na 1ª variação real (cedo em dia
    # limpo, mais tarde em dia nublado). A 1ª ocorrência só dispara ~30 min (LOOKBACK) após o despertar.
    wake_i = ncells
    for _n, _gr in grids.items():
        _base = next((v for v in _gr if v is not None), None)
        if _base is None:
            continue
        for _i, _v in enumerate(_gr):
            if _v is not None and abs(_v - _base) >= TRK_EV_WAKE:
                if _i < wake_i:
                    wake_i = _i
                break
    if wake_i >= ncells:
        wake_i = 0     # ninguém se moveu (dia todo parado / sem dado) — não restringe

    W, eventos = TRK_EV_LOOKBACK, []
    for name, gr in grids.items():
        if sum(1 for v in gr if v is not None) / ncells_cob < TRK_EV_COBERTURA:
            continue                          # este tracker ficou sem comunicação na maior parte (decorrido)
        # RÉGUA "PARADO O DIA TODO" (amplitude diária, ABSOLUTA — MESMA régua das abas Overview/Parados,
        # TRK_PARADO_AMP): tracker cuja amplitude TOTAL no dia é baixa está travado, INDEPENDENTE da frota
        # ter girado. Sem isto, a PLANTA INTEIRA travada (frota amp~0, ex.: SMP100 preso em 15°) escapava
        # da grade (0 ocorrências) enquanto Overview/Parados marcavam 89. Uma regra só p/ todas as abas.
        valids = [(i, v) for i, v in enumerate(gr) if v is not None]
        if valids:
            ys = [v for _, v in valids]
            amp_trk_dia = _amp_robusta(ys)     # p02–p98: célula com leitura podre não infla a amplitude
            if amp_trk_dia is not None and amp_trk_dia <= TRK_PARADO_AMP and frota_acordou:
                # INÍCIO = começo do PATAMAR FINAL (quando o ângulo PAROU de variar), não o despertar:
                # o tracker pode ter girado de manhã e travado às 07:46 (não 07:10). Recua do fim
                # enquanto está no mesmo patamar (±STUCK_RANGE); clampa no despertar (nunca-acordou).
                ifim, fin, j = valids[-1][0], valids[-1][1], valids[-1][0]
                while j - 1 >= 0 and gr[j - 1] is not None and abs(gr[j - 1] - fin) <= TRK_EV_STUCK_RANGE:
                    j -= 1
                i0 = max(j, wake_i)
                dur = (ifim - i0) * TRK_EV_STEP
                if dur >= TRK_EV_MIN_MIN:
                    eventos.append({"tracker": name, "parada": _hhmm(i0),
                                    "retorno": None, "dur_min": dur})
                continue                      # pula a régua de janela curta (já marcou)
        # INÍCIO da travada: a frota gira e o tracker está plano (janela deslizante, relativo à frota)
        onset = [False] * ncells
        for i in range(W, ncells):
            if gr[i] is None:
                continue
            fr, tr = _rng(fleet[i - W:i + 1]), _rng(gr[i - W:i + 1])
            if fr is not None and tr is not None and fr >= TRK_EV_FLEET_RANGE and tr <= TRK_EV_STUCK_RANGE:
                onset[i] = True
        i = W
        while i < ncells:
            if not onset[i] or gr[i] is None:
                i += 1; continue
            plat = gr[i]
            start = i                                  # recua até o começo real do patamar
            while start - 1 >= 0 and gr[start - 1] is not None and abs(gr[start - 1] - plat) <= TRK_EV_STUCK_RANGE:
                start -= 1
            start = max(start, wake_i)                 # não conta antes do despertar (stow matinal é normal)
            # ESTENDE a travada pelo próprio patamar do tracker (independe da frota — não fatia no meio-dia);
            # termina quando o tracker sai do patamar (retorno) ou acabam os dados.
            ret, last_in, k = None, i, i + 1
            while k < ncells:
                if gr[k] is not None:
                    if abs(gr[k] - plat) > TRK_EV_RESUME:
                        ret = k; break
                    last_in = k
                k += 1
            fim_i = ret if ret is not None else last_in
            dur = (fim_i - start) * TRK_EV_STEP
            # Filtra STOW LESTE matinal: parada começa cedo em -55°±10° E o tracker sai do stow
            # até 10:30 — comportamento normal (parking esperando o sol), não é ocorrência. Tracker
            # preso no stow muito além das 10:30 (ou que NÃO sai) continua virando ocorrência.
            parada_min = TRK_EV_WIN_INI + start * TRK_EV_STEP
            ret_min    = (TRK_EV_WIN_INI + ret * TRK_EV_STEP) if ret is not None else None
            eh_stow = (parada_min <= TRK_EV_STOW_INI + 60   # parada até ~08:30
                       and abs(plat - TRK_EV_STOW_ANG) <= TRK_EV_STOW_TOL
                       and ret_min is not None and ret_min <= TRK_EV_STOW_FIM_MAX)
            if not eh_stow and dur >= TRK_EV_MIN_MIN:
                eventos.append({"tracker": name, "parada": _hhmm(start),
                                "retorno": _hhmm(ret) if ret is not None else None, "dur_min": dur})
            i = (ret + 1) if ret is not None else (last_in + 1)
    eventos.sort(key=lambda e: (_trk_min_x(e["parada"]) or 0, _pv_trk_num(e["tracker"])))

    # ── DISPONIBILIDADE POR TEMPO (janela 06:00–18:00) ───────────────────────────
    # Indisponível = tempo PARADO (ocorrências) + tempo FORA DO ALVO (desvio/atraso: longe da
    # mediana da frota). Parado o dia todo → conta desde 06:00 (disp 0). Quem se move → janela a
    # partir da partida da frota (wake). Trackers sem comunicação no período ficam fora do cálculo.
    parado_cells = {}
    for e in eventos:
        p0 = _trk_min_x(e["parada"]); pr = _trk_min_x(e.get("retorno")) if e.get("retorno") else None
        if p0 is None:
            continue
        i0 = max(0, (p0 - TRK_EV_WIN_INI) // TRK_EV_STEP)
        i1 = ((pr - TRK_EV_WIN_INI) // TRK_EV_STEP) if pr is not None else (ncells - 1)
        s = parado_cells.setdefault(e["tracker"], set())
        for c in range(i0, min(ncells, i1 + 1)):
            s.add(c)
    disp_num = disp_den = 0
    for name, gr in grids.items():
        if sum(1 for v in gr if v is not None) / ncells_cob < TRK_EV_COBERTURA:
            continue                                    # sem comunicação no período → fora do cálculo
        ys = [v for v in gr if v is not None]
        amp = _amp_robusta(ys) or 0.0                    # p02–p98 (mesma régua da detecção)
        if amp <= TRK_PARADO_AMP and frota_acordou:      # travado E a usina já operou (frota acordou)
            disp_den += ncells                          # parado o dia todo (06:00–18:00) → 0% disponível
            continue
        pc = parado_cells.get(name, set())
        win = ncells - wake_i                           # movedor: da partida da frota até 18:00
        if win <= 0:
            continue
        down = 0
        for i in range(wake_i, ncells):
            if i in pc:
                down += 1                               # parado (ocorrência)
            elif gr[i] is not None and fleet[i] is not None and abs(gr[i] - fleet[i]) > TRK_EV_DESVIO:
                down += 1                               # desvio/atraso: fora do alvo da frota
        disp_den += win
        disp_num += (win - down)
    disponibilidade = round(disp_num / disp_den * 100, 1) if disp_den else None
    return {"cobertura": round(cob_usina, 2), "eventos": eventos, "disponibilidade": disponibilidade}


def _trk_ev_dias(ini_iso, fim_iso):
    d0 = datetime.strptime(ini_iso, "%Y-%m-%d").date()
    d1 = datetime.strptime(fim_iso, "%Y-%m-%d").date()
    out, d = [], d0
    while d <= d1:
        out.append(d); d += timedelta(days=1)
    return out


def _trk_ev_backfill(ini_iso, fim_iso):
    """Job de fundo: processa os (dia, usina-com-trackers) faltantes de ini..fim e guarda. Retomável
    (pula prontos); HOJE é sempre reprocessado (parcial). Throttle leve p/ não martelar a Plataforma."""
    if _trk_ev_prog["running"]:
        return
    _trk_ev_prog.update({"running": True, "feito": 0, "total": 0, "atual": "", "fim_ts": 0.0, "erro": ""})
    try:
        try:
            _swr(_pv_trk_cache, _build_pv_trk_payload, force=not _pv_trk_plant)
        except Exception:
            pass
        # só usinas COM trackers (evita gastar chamada em quem não tem)
        com_trk = {pid: ent["payload"] for pid, ent in _pv_trk_plant.items()
                   if (ent.get("payload") or {}).get("total")}
        hoje_iso = datetime.now().strftime("%Y-%m-%d")
        fim_iso = min(fim_iso, hoje_iso)
        tarefas = []
        for d in _trk_ev_dias(ini_iso, fim_iso):
            d_iso, d_br = d.strftime("%Y-%m-%d"), d.strftime("%d/%m/%Y")
            for pid, pl in com_trk.items():
                if _trk_eventos.get(d_iso, {}).get(str(pid)) and d_iso != hoje_iso:
                    continue                  # já processado (dia passado é imutável)
                tarefas.append((d_iso, d_br, pid, pl.get("usina") or str(pid)))
        # processa do dia MAIS RECENTE → mais antigo: HOJE (o que o operador olha agora) sai PRIMEIRO,
        # não por último. Sem isto, o "Gerar histórico" (01/06→hoje) só preenchia o dia atual no FIM —
        # com o trackerschart lento, a aba Ocorrências de hoje ficava vazia por muito tempo.
        tarefas.sort(key=lambda t: t[0], reverse=True)
        _trk_ev_prog["total"] = len(tarefas)

        def _um(t):
            d_iso, d_br, pid, pnome = t
            try:
                res = _trk_eventos_do_dia(pid, pnome, d_br)
                with _trk_eventos_lock:
                    _trk_eventos.setdefault(d_iso, {})[str(pid)] = {
                        "nome": pnome, "ts": time.time(),
                        "cobertura": res["cobertura"], "eventos": res["eventos"],
                        "disponibilidade": res.get("disponibilidade")}
            except Exception:
                pass
            time.sleep(0.3)                   # throttle leve

        feito = 0
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = {ex.submit(_um, t): t for t in tarefas}
            for f in as_completed(futs):
                feito += 1
                _trk_ev_prog.update({"feito": feito, "atual": f"{futs[f][3]} {futs[f][1]}"})
                if feito % 25 == 0:
                    _trk_ev_save()
        _trk_ev_save()
        # curvas do dia agora QUENTES no cache → rebuild LIGHT do overview (sem baixar nada de novo)
        # reclassifica os travados que o build frio marcou como 'desvio'/normal para 'parado'. Sem isto
        # a linha-pai (ex.: Mandaguaçu) ficava com 0 parados até alguém clicar "Atualizar status".
        if fim_iso >= datetime.now().strftime("%Y-%m-%d"):
            try:
                _swr(_pv_trk_cache, _build_pv_trk_payload, force=True)
            except Exception as e:
                print(f"[trk_ev] rebuild do overview pós-warm falhou: {e}")
    except Exception as e:
        _trk_ev_prog["erro"] = str(e)
    finally:
        _trk_ev_prog.update({"running": False, "fim_ts": time.time()})


def _trk_eventos_rows(ini, fim):
    """Linhas da tabela de ocorrências no período. Nome da usina pela coluna 'Usina' do BD_Performance
    (mesma régua do macro, `_macro_usina_nome`). Inversor resolvido em tempo de listagem via
    BD_TRK_INV — assim funciona p/ eventos JÁ salvos sem precisar regerar, e se o mapa mudar a
    tabela reflete na próxima leitura."""
    try:
        nome_raw_by_pid = {p["id"]: p["nome"] for p in get_plants(get_token())}
    except Exception:
        nome_raw_by_pid = {}
    rows = []
    with _trk_eventos_lock:
        dias = [d for d in _trk_eventos.keys() if ini <= d <= fim]
        for d_iso in dias:
            dd = d_iso.split("-")                       # [Y, M, D]
            for pid, ent in _trk_eventos[d_iso].items():
                usina = _macro_usina_nome(ent.get("nome") or "") or ent.get("nome") or pid
                # mapa tracker_num → inversor: prefere o nome_raw da API PV (o BD_TRK_INV é chaveado
                # por _nome_base do supervisório); cai p/ o nome guardado se a plataforma estiver fora
                nome_raw = nome_raw_by_pid.get(int(pid) if str(pid).lstrip("-").isdigit() else pid) \
                           or ent.get("nome") or ""
                for ev in ent.get("eventos", []):
                    inv = ev.get("inversor") or _bd_trk_lookup(nome_raw, _pv_trk_num(ev["tracker"])) or ""
                    rows.append({"data_iso": d_iso, "data": f"{dd[2]}/{dd[1]}",
                                 "usina": usina, "tracker": ev["tracker"],
                                 "inversor": inv,
                                 "parada": ev["parada"], "retorno": ev.get("retorno"),
                                 "dur_min": ev.get("dur_min")})
    rows.sort(key=lambda r: (r["usina"], r["parada"]))
    rows.sort(key=lambda r: r["data_iso"], reverse=True)        # dias recentes 1º
    return rows


def _trk_eventos_disp(ini, fim):
    """Disponibilidade (por tempo) por usina — usa o dia MAIS RECENTE processado de cada usina no período."""
    out, vist = {}, {}
    with _trk_eventos_lock:
        for d_iso in sorted((d for d in _trk_eventos if ini <= d <= fim), reverse=True):
            for pid, ent in _trk_eventos[d_iso].items():
                un = _macro_usina_nome(ent.get("nome") or "") or ent.get("nome") or pid
                if un in vist:
                    continue
                vist[un] = True
                if ent.get("disponibilidade") is not None:
                    out[un] = ent["disponibilidade"]
    return out


def _trk_eventos_disp_by_id(ini, fim):
    """Como _trk_eventos_disp, mas chaveado por plant_id (str) — pro merge no overview por id
    (o overview e as ocorrências podem exibir nomes ligeiramente diferentes; o id não erra)."""
    out, vist = {}, {}
    with _trk_eventos_lock:
        for d_iso in sorted((d for d in _trk_eventos if ini <= d <= fim), reverse=True):
            for pid, ent in _trk_eventos[d_iso].items():
                if pid in vist:
                    continue
                vist[pid] = True
                if ent.get("disponibilidade") is not None:
                    out[pid] = ent["disponibilidade"]
    return out


@app.route("/api/pv/trackers/eventos")
def api_pv_trackers_eventos():
    """Tabela de ocorrências travou→voltou (lê o que já foi processado). ?ini=YYYY-MM-DD&fim=YYYY-MM-DD."""
    ini = (flask_request.args.get("ini") or TRK_EV_DATA_INI).strip()
    fim = (flask_request.args.get("fim") or datetime.now().strftime("%Y-%m-%d")).strip()
    rows = _trk_eventos_rows(ini, fim)
    return jsonify({"rows": rows, "disp": _trk_eventos_disp(ini, fim), "ini": ini, "fim": fim,
                    "total": len(rows), "data_ini_hist": TRK_EV_DATA_INI, "progresso": dict(_trk_ev_prog)})


@app.route("/api/pv/trackers/eventos/export")
def api_pv_trackers_eventos_export():
    """Exporta a tabela de ocorrências do período em CSV (; + BOM, p/ o Excel BR abrir certo).
    Aceita ?usina= p/ respeitar o filtro de usina mostrado no front."""
    import csv
    ini = (flask_request.args.get("ini") or TRK_EV_DATA_INI).strip()
    fim = (flask_request.args.get("fim") or datetime.now().strftime("%Y-%m-%d")).strip()
    qf = (flask_request.args.get("usina") or "").strip().lower()
    rows = _trk_eventos_rows(ini, fim)
    if qf:
        rows = [r for r in rows if qf in (r.get("usina") or "").lower()]
    buf = io.StringIO()
    buf.write("﻿")                                 # BOM
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Data", "Usina", "Tracker", "Inversor", "Parada", "Retorno", "Duração"])
    for r in rows:
        dur = r.get("dur_min") or 0
        ret = (r["data"] + " " + r["retorno"]) if r.get("retorno") else "não retornou no dia"
        w.writerow([r["data"], r["usina"], r["tracker"], r.get("inversor") or "",
                    r["data"] + " " + r["parada"], ret, f"{dur // 60}h{dur % 60:02d}"])
    resp = app.response_class(buf.getvalue(), mimetype="text/csv")
    resp.headers["Content-Disposition"] = f'attachment; filename="ocorrencias_trackers_{ini}_a_{fim}.csv"'
    return resp


# ══ Export Excel (.xlsx) ESTILIZADO das sub-abas de trackers — vale p/ TODAS as fontes ═══════════
_TRK_FONTE_LABEL = {"pv": "API PV", "pg": "Thopen", "sunop": "Athon", "axis": "Axis", "owen": "2C"}
_TRK_FONTES = set(_TRK_FONTE_LABEL)


def _trk_eventos_export_data(fonte, ini):
    """→ (rows, disp) das ocorrências de UM dia (ini=YYYY-MM-DD) p/ a fonte (mesma origem da tabela)."""
    if fonte == "pv":
        return _trk_eventos_rows(ini, ini), _trk_eventos_disp(ini, ini)
    if fonte in ("sunop", "axis"):
        ent = _sunop_eventos_calc("axis" if fonte == "axis" else "gridco", ini)
        return ent.get("rows", []), ent.get("disp", {})
    if fonte == "pg":
        ent = _pg_eventos_calc(ini);  return ent.get("rows", []), ent.get("disp", {})
    if fonte == "owen":
        ent = _owen_eventos_calc(ini); return ent.get("rows", []), ent.get("disp", {})
    return [], {}


def _trk_parados_rows_fonte(fonte, force=False):
    """Linhas de 'trackers parados agora' p/ a fonte (mesma origem da tabela/endpoint)."""
    if fonte == "pv":   return _pv_parados_rows(force)
    if fonte == "pg":   return _pg_parados_rows(force)
    if fonte == "owen": return _owen_parados_rows(force)
    if fonte in ("sunop", "axis"):
        return _sunop_parados_rows("axis" if fonte == "axis" else "gridco", force)
    return []


def _xlsx_resp(wb, filename):
    bio = io.BytesIO(); wb.save(bio); bio.seek(0)
    resp = app.response_class(bio.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def _xlsx_dur(m):
    m = int(m or 0)
    return f"{m // 60}h{m % 60:02d}"


@app.route("/api/<fonte>/trackers/eventos/export.xlsx")
def api_trk_eventos_xlsx(fonte):
    """Ocorrências (travou→voltou) do dia em Excel estilizado (cabeçalho escuro, faixa de
    disponibilidade colorida, linha rosa p/ 'parado agora', 'não retornou' em vermelho)."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    if fonte not in _TRK_FONTES:
        return jsonify({"error": "fonte inválida"}), 404
    ini = (flask_request.args.get("ini") or datetime.now().strftime("%Y-%m-%d")).strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", ini):
        ini = datetime.now().strftime("%Y-%m-%d")
    qf = (flask_request.args.get("usina") or "").strip().lower()
    rows, disp = _trk_eventos_export_data(fonte, ini)
    if qf:
        rows = [r for r in rows if qf in (r.get("usina") or "").lower()]
        disp = {u: v for u, v in disp.items() if qf in u.lower()}
    try:
        par_set = {f"{r.get('usina')}|{r.get('tracker')}" for r in _trk_parados_rows_fonte(fonte)}
    except Exception:
        par_set = set()
    label = _TRK_FONTE_LABEL[fonte]
    dia_br = datetime.strptime(ini, "%Y-%m-%d").strftime("%d/%m/%Y")

    NAVY = "1A1B2E"
    hdr_fill = PatternFill("solid", fgColor=NAVY); hdr_font = Font(color="FFFFFF", bold=True)
    pink = PatternFill("solid", fgColor="FFF1F1")
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Ocorrências"
    ro = 1
    ws.cell(row=ro, column=1, value=f"Ocorrências de trackers — travou → voltou · {label} · {dia_br}").font = Font(bold=True, size=14, color=NAVY)
    ro += 2
    if disp:
        ws.cell(row=ro, column=1, value="Disponibilidade por tempo (06:00–18:00 · parado + desvio + atraso)").font = Font(bold=True, color="374151")
        ro += 1
        for j, (u, v) in enumerate(sorted(disp.items(), key=lambda kv: kv[1]), start=1):
            cor = "16A34A" if v >= 98 else ("D97706" if v >= 90 else "DC2626")
            ws.cell(row=ro, column=j, value=f"{u}: {v}%").font = Font(bold=True, color=cor)
        ro += 2
    headers = ["Data", "Usina", "Tracker", "Inversor", "Parada", "Retorno", "Duração"]
    hr = ro
    for j, h in enumerate(headers, start=1):
        c = ws.cell(row=hr, column=j, value=h); c.fill = hdr_fill; c.font = hdr_font
    ro += 1
    for r in rows:
        parado = f"{r.get('usina')}|{r.get('tracker')}" in par_set
        trk = f"{r.get('tracker')}  ● parado agora" if parado else r.get("tracker")
        ret = f"{r['data']} {r['retorno']}" if r.get("retorno") else "não retornou no dia"
        vals = [r["data"], r["usina"], trk, r.get("inversor") or "—",
                f"{r['data']} {r.get('parada','')}", ret, _xlsx_dur(r.get("dur_min"))]
        for j, val in enumerate(vals, start=1):
            ws.cell(row=ro, column=j, value=val)
        if parado:
            for j in range(1, len(headers) + 1):
                ws.cell(row=ro, column=j).fill = pink
            ws.cell(row=ro, column=3).font = Font(bold=True, color="B91C1C")
        if not r.get("retorno"):
            ws.cell(row=ro, column=6).font = Font(color="B91C1C")
        ro += 1
    for j, w in enumerate([12, 22, 22, 20, 18, 22, 10], start=1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = ws.cell(row=hr + 1, column=1)
    return _xlsx_resp(wb, f"ocorrencias_{fonte}_{ini}.xlsx")


@app.route("/api/<fonte>/trackers/parados/export.xlsx")
def api_trk_parados_xlsx(fonte):
    """Trackers parados (agora) em Excel estilizado (cabeçalho escuro; disparidade em vermelho;
    'parado desde' âmbar≥24h/vermelho≥36h; situação verde 'na planilha' / vermelho 'novo')."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    if fonte not in _TRK_FONTES:
        return jsonify({"error": "fonte inválida"}), 404
    qf = (flask_request.args.get("usina") or "").strip().lower()
    rows = _trk_parados_rows_fonte(fonte)
    if qf:
        rows = [r for r in rows if qf in (r.get("usina") or "").lower()]
    label = _TRK_FONTE_LABEL[fonte]
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")

    def _ang(v):
        return "—" if v is None else f"{round(float(v), 1)}°"

    NAVY = "1A1B2E"
    hdr_fill = PatternFill("solid", fgColor=NAVY); hdr_font = Font(color="FFFFFF", bold=True)
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Trackers parados"
    ro = 1
    ws.cell(row=ro, column=1, value=f"Trackers parados agora · {label} · {agora}").font = Font(bold=True, size=14, color=NAVY)
    ro += 1
    ws.cell(row=ro, column=1, value=f"{len(rows)} tracker(s) parado(s) em {len({r.get('usina') for r in rows})} usina(s)").font = Font(color="6B7280")
    ro += 2
    headers = ["Usina", "Tracker", "Inversor", "Ângulo atual", "Alvo", "Disparidade",
               "Amplitude", "Parado desde", "Situação", "Última leitura"]
    hr = ro
    for j, h in enumerate(headers, start=1):
        c = ws.cell(row=hr, column=j, value=h); c.fill = hdr_fill; c.font = hdr_font
    ro += 1
    for r in rows:
        desde = ""
        if r.get("parado_desde"):
            iso = str(r["parado_desde"]).replace("T", " ")
            desde = f"{iso[8:10]}/{iso[5:7]} {iso[11:16]}"
        h = r.get("horas_parado")
        if isinstance(h, (int, float)):
            desde += f" (há {int(h // 24)}d)" if h >= 24 else (f" (há {round(h)}h)" if h >= 1 else "")
        sit = (("na planilha" + (f" ({r.get('ticket_status')})" if r.get("ticket_status") else ""))
               if r.get("na_planilha") else "novo (fora da planilha)")
        ult = str(r.get("ultima_leitura")).replace("T", " ")[:16] if r.get("ultima_leitura") else "—"
        vals = [r.get("usina"), r.get("tracker"), r.get("inversor") or "—",
                _ang(r.get("atual")), _ang(r.get("alvo")), _ang(r.get("disparidade")),
                _ang(r.get("amplitude")), desde or "recente", sit, ult]
        for j, val in enumerate(vals, start=1):
            ws.cell(row=ro, column=j, value=val)
        ws.cell(row=ro, column=6).font = Font(bold=True, color="B91C1C")
        if isinstance(h, (int, float)) and h >= 36:
            ws.cell(row=ro, column=8).font = Font(bold=True, color="B91C1C")
        elif isinstance(h, (int, float)) and h >= 24:
            ws.cell(row=ro, column=8).font = Font(color="B45309")
        ws.cell(row=ro, column=9).font = Font(color=("16A34A" if r.get("na_planilha") else "B91C1C"),
                                              bold=not r.get("na_planilha"))
        ro += 1
    for j, w in enumerate([22, 12, 16, 13, 10, 12, 11, 22, 22, 18], start=1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = ws.cell(row=hr + 1, column=1)
    return _xlsx_resp(wb, f"trackers_parados_{fonte}_{datetime.now().strftime('%Y-%m-%d_%H%M')}.xlsx")


@app.route("/api/pv/trackers/eventos/gerar", methods=["POST"])
def api_pv_trackers_eventos_gerar():
    """Dispara (em 2º plano) o processamento do histórico de eventos de ini..fim (default 01/06→hoje)."""
    if not _plat_token():
        return jsonify({"ok": False, "sem_token": True})
    if _trk_ev_prog["running"]:
        return jsonify({"ok": True, "ja_rodando": True, "progresso": dict(_trk_ev_prog)})
    body = flask_request.get_json(silent=True) or {}
    ini = (body.get("ini") or TRK_EV_DATA_INI).strip()
    fim = (body.get("fim") or datetime.now().strftime("%Y-%m-%d")).strip()
    threading.Thread(target=_trk_ev_backfill, args=(ini, fim), daemon=True).start()
    return jsonify({"ok": True, "iniciado": True, "ini": ini, "fim": fim})


@app.route("/api/pv/trackers/eventos/progresso")
def api_pv_trackers_eventos_progresso():
    return jsonify(dict(_trk_ev_prog))


_pv_trk_plant_det = {}   # (idusina, data) -> {ts, payload}: detalhe REFINADO pela curva (por data)


@app.route("/api/pv/trackers/<int:idusina>")
def api_pv_trackers_plant(idusina):
    """Detalhe de UMA usina: análise REFINADA pela curva do dia (travado + desvio vs frota).
    Aceita ?date=YYYY-MM-DD (ou DD/MM/YYYY) p/ ver dias anteriores; padrão = hoje."""
    data = (flask_request.args.get("date") or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", data):
        data = datetime.strptime(data, "%Y-%m-%d").strftime("%d/%m/%Y")
    hoje = datetime.now().strftime("%d/%m/%Y")
    data = data or hoje
    key = (idusina, data)
    ent = _pv_trk_plant_det.get(key)
    if ent and ((data != hoje and ent["payload"].get("trackers")) or (time.time() - ent["ts"]) < CACHE_TTL):
        return jsonify(ent["payload"])
    try:
        nome = next((nome_usina(p["id"], p["nome"]) for p in get_plants(get_token())
                     if p["id"] == idusina), str(idusina))
    except Exception:
        nome = str(idusina)
    r = _pv_trackers_analise(idusina, nome, date=(None if data == hoje else data), curva=True)
    _pv_trk_plant_det[key] = {"ts": time.time(), "payload": r}
    if data == hoje:
        _pv_trk_plant[idusina] = {"ts": time.time(), "payload": r}   # alimenta o cache do overview tb
    return jsonify(r)


_pv_trk_chart_cache = {}   # (idusina, data) -> {ts, payload}: evita rebater o trackerschart (90s) a cada abertura


@app.route("/api/pv/trackers/<int:idusina>/chart")
def api_pv_trackers_chart(idusina):
    """Curva de posição por tracker (PV Plataforma /v2/usinas/trackerschart). 1 dia (cacheado) ou
    intervalo De/Até (até TRK_CHART_MAX_DIAS): concatena a curva de cada dia — cada dia é uma busca
    ao trackerschart (pesada), mas cada uma é cacheada por (usina, dia)."""
    ini_iso, fim_iso, ndias = _trk_chart_range()
    hoje = datetime.now().strftime("%d/%m/%Y")
    agora = time.time()
    if ndias == 1:                                   # caminho de 1 dia: mantém o cache do payload
        data = datetime.strptime(ini_iso, "%Y-%m-%d").strftime("%d/%m/%Y")
        key = (idusina, data)
        ent = _pv_trk_chart_cache.get(key)
        if ent and ((data != hoje and ent["payload"].get("trackers")) or (agora - ent["ts"]) < CACHE_TTL):
            return jsonify(ent["payload"])
        g = _pv_trk_grafico(idusina, data)           # cru + cacheado (compartilhado com o detalhe)
    else:                                            # intervalo: concatena a curva de cada dia
        g = {}
        for d in _trk_ev_dias(ini_iso, fim_iso):
            data_br = d.strftime("%d/%m/%Y")
            for nome, pts in (_pv_trk_grafico(idusina, data_br) or {}).items():
                g.setdefault(nome, []).extend(pts or [])

    _alvo_max = _trk_chart_down_alvo(ndias)
    def _down(serie):
        step = max(1, len(serie) // _alvo_max)
        return serie[::step]

    trackers = []
    for nome in sorted(g.keys(), key=_pv_trk_num):
        s = _down(g[nome] or [])
        trackers.append({"id": nome, "x": [p.get("x") for p in s],
                         "y": [round(p.get("y"), 2) if isinstance(p.get("y"), (int, float)) else None
                               for p in s]})
    payload = {"plant": idusina, "date": datetime.strptime(ini_iso, "%Y-%m-%d").strftime("%d/%m/%Y"),
               "ini": ini_iso, "fim": fim_iso, "ndias": ndias, "trackers": trackers, "alvo": None}
    if ndias == 1:
        _pv_trk_chart_cache[(idusina, payload["date"])] = {"ts": agora, "payload": payload}
    return jsonify(payload)


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
    # Validação FORTE (o endpoint é público p/ o bookmarklet): exige um JWT de verdade — payload
    # base64 decodável p/ JSON com 'exp'. Evita gravar lixo (ex.: "x.y.z" passava no count de pontos).
    exp = None
    try:
        import base64
        pl = tok.split(".")[1]; pl += "=" * (-len(pl) % 4)
        exp = json.loads(base64.urlsafe_b64decode(pl)).get("exp")
    except Exception:
        exp = None
    if tok.count(".") != 2 or not exp:
        r = jsonify({"ok": False, "error": "token inválido (não é um JWT da Plataforma)"})
        r.headers["Access-Control-Allow-Origin"] = "*"
        return r, 400
    try:
        with open(_PLAT_TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(tok)
        _pv_trk_cache["payload"] = None   # invalida overview p/ recarregar com token novo
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
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


@app.route("/api/trackers/os-sugeridas")
def api_trackers_os_sugeridas():
    """Fila de OSs SUGERIDAS (Nível 2): trackers parados >36h ou recorrentes (3x/30d), já com os
    campos prontos p/ o os_creator pré-preencher (usina, ativo 'Estrutura Trackers', assunto, tipo).
    NÃO cria nada — só sugere. O app desktop busca aqui e abre o wizard preenchido."""
    if not _TRACKER_WATCH_OK:
        return jsonify({"rows": [], "total": 0, "error": "tracker_watch indisponível"}), 500
    try:
        rows = _tw.os_sugeridas()
        return jsonify({"rows": rows, "total": len(rows),
                        "cache_ts": datetime.now().strftime("%H:%M:%S")})
    except Exception as e:
        return jsonify({"rows": [], "total": 0, "error": str(e)}), 500


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

    # potência ativa por inversor (dbt.stg_inverter_analogic_data) → separa PARADO de baixa-perf de strings
    try:
        _ana = _pg_analogic_snapshot()
        _pow = {(pid, a["device_id"]): a.get("active_power")
                for pid, lst in _ana.items() for a in lst}
    except Exception:
        _pow = {}

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
        inv_list, tot_ativas, tot_esp, powers = [], 0, 0, []
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
            powers.append(_pow.get((pid, dev_id)))
            inv_list.append({
                "id": dev_id, "nome": equip_disp.get(inv["dev"], inv["dev"]), "nome_api": inv["dev"],
                "ultima_leitura": inv["ts"].strftime("%Y-%m-%d %H:%M") if inv["ts"] else None,
                "falha_comunicacao": False, "desligado": ativas == 0,
                "active_power": _pow.get((pid, dev_id)),
                "strings_ativas": ativas, "total_strings": total,
                "str_esp": str_esp, "diferenca": ativas - str_esp,
                "temp": None, "eday": None, "strings": inv["strings"],
            })
        # potência ativa → produzindo por inversor; deficit de strings SÓ dos que produzem
        prod, pot_med, n_off = _macro_prod(powers)
        _dia = 7 <= datetime.now().hour < 18       # de dia inversor parado é problema (à noite é normal)
        for iv, pr in zip(inv_list, prod):
            iv["produzindo"] = pr
            # inversor PARADO (potência ~0) de dia → strings deixam de ser "inativa" VERDE e viram
            # "desligado" (vermelho-escuro): não faz sentido inversor desligado com string 0A "OK".
            _off = (pr is False) if pr is not None else (iv["strings_ativas"] == 0)
            if _off and _dia:
                iv["desligado"] = True
                for s in iv["strings"]:      # inversor OFF: linha inteira = desligado (a corrente reversa residual não é produção)
                    if s["status"] != "trancada":
                        s["status"] = "desligado"; s["ativa"] = False
        dif_oper = sum(min(0, iv["diferenca"]) for iv, pr in zip(inv_list, prod) if pr is not False)
        detail[pid] = inv_list
        summary.append({
            "usina": USINA_DISPLAY.get(sup, sup), "plant_id": pid,
            "qtd_inversores": len(p["invs"]), "inv_esp": len(p["invs"]),
            "strings_ativas": tot_ativas, "str_esp": tot_esp,
            "diferenca": tot_ativas - tot_esp,             # = soma das diferenças dos inversores
            "diferenca_operante": dif_oper,                # deficit só de inversores PRODUZINDO
            "pot_med": pot_med, "inv_off": n_off,          # potência mediana + nº parados (Pac ~0)
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


# ══ VISÃO MACRO DO PORTFÓLIO ("o que tá ruim") — Painel 1 ════════════════════════
# Agrega os overviews que CADA fonte já mantém em cache (SEM re-bater as usinas ao vivo)
# numa lista única, ordenada por severidade. Fase 1: PG/Thopen (autoritativo) + API PV
# (só completa usinas que faltarem — as duas são a MESMA frota Thopen, então dedup por nome).
# Fases seguintes plugam SunOp/Axis/SolarEdge/Owen (clientes diferentes) e BD_Trackers.
# ── "Sem produção": usina/inversor PARADO por POTÊNCIA ATIVA (não por strings) ─────────
# Caxambu-like: usina parada com correntes residuais/reversas → strings_ativas>0 mas potência ~0.
# Separa PARADO (Pac/active_power ~0) de baixa-performance de strings, p/ o painel focar no que é
# operante. Só de DIA e com telemetria fresca (senão é noite / falha de comunicação, não parada).
MACRO_POT_INV_MIN = 2.0     # potência ativa por inversor abaixo disto = NÃO produzindo (mesma base do R-06)


def _macro_prod(powers):
    """powers = potência ativa por inversor (None = sem dado).
    → (produzindo: list[bool|None] alinhada, pot_med, n_off). Sem dado de potência → tudo None."""
    vals = [p for p in powers if isinstance(p, (int, float))]
    if not vals:
        return [None] * len(powers), None, 0
    med = _median(vals)
    lim = max(MACRO_POT_INV_MIN, (med or 0) * DIAG_TRIP_FRAC)
    prod = [None if not isinstance(p, (int, float)) else (p >= lim) for p in powers]
    return prod, med, sum(1 for x in prod if x is False)


def _macro_sem_producao(r) -> bool:
    """Usina praticamente PARADA de dia (potência ~0) e com telemetria fresca — não é 'strings abaixo'."""
    if r.get("stringbox") or r.get("sem_dados") or r.get("falha_comunicacao"):
        return False
    pm = r.get("pot_med")
    if not isinstance(pm, (int, float)):     # fonte sem potência ativa (2C) → cai no strings_ativas==0
        return bool(r.get("qtd_inversores")) and r.get("strings_ativas") == 0 and _macro_eh_dia(r)
    return pm < MACRO_POT_INV_MIN and bool(r.get("qtd_inversores")) and _macro_eh_dia(r)


def _macro_eh_dia(r) -> bool:
    """De dia (07–18h Brasília) — a régua de 'sem produção'/inversor-parado só vale com sol.
    A frescura já vem embutida: pot_med sai da analógica das ÚLTIMAS 6h (PG) / última leitura do dia
    (PV); dado velho não gera pot_med → não vira 'sem produção'."""
    return 7 <= datetime.now().hour < 18


def _macro_dif(r):
    """Déficit de strings AGORA = ativas − esperadas, IGUAL em todas as fontes (o mesmo número
    que aparece na coluna Diferença do detalhamento de cada fonte). Antes preferia
    'diferenca_operante' (só inversores PRODUZINDO), campo que só API PV/PG calculam e que zera
    quando os inversores param → deixava a régua inconsistente (Athon/Axis mostravam o total cru,
    API PV/PG mostravam 0). String Box não tem visão por string → sem str_esp → sem déficit."""
    a, e = r.get("strings_ativas"), r.get("str_esp")
    if isinstance(a, (int, float)) and isinstance(e, (int, float)):
        return a - e
    d = r.get("diferenca")
    return d if isinstance(d, (int, float)) else None


def _macro_status(r) -> str:
    """ok / atencao / critico / sem_producao / sem_comm — dos sinais por usina que já calculamos.
    String Box (sem telemetria de string) NÃO entra na régua de strings: 0 ali é esperado, não falha."""
    if r.get("sem_dados") or r.get("falha_comunicacao"):
        return "sem_comm"
    if r.get("stringbox"):
        return "ok"
    if _macro_sem_producao(r):
        return "sem_producao"                          # usina parada (potência ~0) → alerta próprio
    off = r.get("inv_off")
    if isinstance(off, int) and off > 0 and _macro_eh_dia(r):
        return "critico"                               # usina PRODUZINDO com inversor(es) parado(s) = crítico
    dif = _macro_dif(r)
    if isinstance(dif, (int, float)) and dif < 0:
        return "critico" if dif <= -5 else "atencao"   # ≥5 strings abaixo (de inversor OPERANTE) = crítico
    return "ok"


def _macro_causa(r, status: str) -> str:
    if status == "sem_comm":
        return "Sem comunicação"
    if r.get("stringbox"):
        return "Sem visão por string (String Box)"
    if status == "sem_producao":
        off, tot = r.get("inv_off"), r.get("qtd_inversores")
        if isinstance(off, int) and off and isinstance(tot, int):
            return f"Sem produção · {off}/{tot} inversores parados"
        return "Usina sem produção"
    partes = []
    off = r.get("inv_off")
    if isinstance(off, int) and off > 0:
        partes.append(f"{off} inversor(es) parado(s)")
    dif = _macro_dif(r)
    if isinstance(dif, (int, float)) and dif < 0:
        partes.append(f"{-dif} string(s) abaixo do esperado")
    return " · ".join(partes) if partes else "Normal"


def _macro_item(fonte: str, r: dict) -> dict:
    status = _macro_status(r)
    sev = 0 if status == "sem_producao" else severidade(r)   # parada é crítica no ranking
    dif = _macro_dif(r)
    faltando = max(0, -dif) if isinstance(dif, (int, float)) else 0
    if status in ("sem_producao", "sem_comm") or r.get("stringbox"):
        faltando = 0                                   # sai do ranking de "strings abaixo"
    return {
        "fonte": fonte, "usina": r.get("usina"), "plant_id": r.get("plant_id"),
        "status": status, "sev": sev, "causa": _macro_causa(r, status),
        "stringbox": bool(r.get("stringbox")),
        "strings_ativas": r.get("strings_ativas"), "str_esp": r.get("str_esp"),
        "diferenca": dif, "strings_faltando": faltando,
        "inv_off": r.get("inv_off"), "qtd_inversores": r.get("qtd_inversores"),
        "ultima_leitura": r.get("ultima_leitura"),
    }


def _macro_idade_h(s):
    """Idade (horas) de uma 'ultima_leitura' (aceita 'YYYY-MM-DD HH:MM[:SS]'). None se não parsear."""
    if not s:
        return None
    s = str(s).strip()
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return (datetime.now() - datetime.strptime(s, f)).total_seconds() / 3600.0
        except ValueError:
            pass
    return None


_macro_n2u = {"src": None, "map": {}}   # cache {nrm(sup-sem-id): "Usina"} derivado de USINA_GRUPO


def _macro_usina_nome(raw):
    """Nome de EXIBIÇÃO da usina pela coluna 'Usina' do BD_Performance (Equipamentos), nunca o
    'Usina Supervisório'. USINA_GRUPO = mapa completo sup→'Usina' (inclui agrupados). Fallback:
    casa sem o sufixo ' (id)'; por último, devolve o nome sem o '(id)'."""
    s = (raw or "").strip()
    if not s:
        return s
    if s in USINA_GRUPO:
        return USINA_GRUPO[s]
    if _macro_n2u["src"] is not USINA_GRUPO:          # rebuild se o cadastro recarregou
        m = {}
        for sup, val in USINA_GRUPO.items():
            base = re.sub(r"\s*\(\d+\)\s*$", "", sup).strip()
            if base:
                m[_nrm(base)] = val
        _macro_n2u["src"] = USINA_GRUPO
        _macro_n2u["map"] = m
    base = re.sub(r"\s*\(\d+\)\s*$", "", s).strip()
    return _macro_n2u["map"].get(_nrm(base)) or base or s


def _trk_geo_annotate(rows):
    """Anexa estado/região/carteira a cada linha de tracker (parados), por usina, via Info Geral +
    mapa de carteiras. Resolve o nome pela MESMA régua do macro (_macro_usina_nome) → casa mesmo com
    os nomes 'display' que variam por fonte. Usado pela ronda por região (Sudeste separado por cliente)."""
    for r in rows:
        canon = _macro_usina_nome(r.get("usina") or "")
        ig = INFO_GERAL.get(_nrm(canon)) or INFO_GERAL.get(_nrm(r.get("usina") or "")) or {}
        if not ig and canon:
            # usina AGRUPADA ("Nova Londrina") vs Info Geral por sub-usina ("Nova Londrina 1"):
            # cai na 1ª sub-usina de mesmo prefixo — estado/região/cliente são os mesmos.
            # (_nrm remove espaços: "novalondrina1".startswith("novalondrina") + resto curto com dígito)
            base = _nrm(canon)
            ig = next((v for k, v in INFO_GERAL.items()
                       if k.startswith(base) and 0 < len(k) - len(base) <= 8
                       and any(ch.isdigit() for ch in k[len(base):])), {})
        r["estado"] = ig.get("estado")
        r["regiao"] = ig.get("regiao")
        r["cliente"] = _carteira_de(canon) or ig.get("cliente")   # carteira (Thopen/Copel/Matrix/Polaris)
    return rows


def _portfolio_rollup() -> list:
    """Lista única de usinas do portfólio, pior→melhor. Reusa os caches das fontes.
    Nome pela coluna 'Usina' (Equipamentos); sub-usinas que caem na mesma 'Usina' física são
    agrupadas mantendo o PIOR status (e a dedup PG↔API PV cai naturalmente nessa chave)."""
    por_usina = {}                            # nrm('Usina') -> item (mantém o pior)

    def add(fonte, r):
        item = _macro_item(fonte, r)
        nome = _macro_usina_nome(item.get("usina"))
        if not nome:
            return
        item["usina"] = nome
        k = _nrm(nome)
        prev = por_usina.get(k)
        if (prev is None or item["sev"] < prev["sev"]
                or (item["sev"] == prev["sev"]
                    and item.get("strings_faltando", 0) > prev.get("strings_faltando", 0))):
            por_usina[k] = item

    try:                                      # PG/Thopen (banco — fonte confiável)
        rows, _ = _pg_get_snapshot(False)
        for r in rows:
            add("Thopen", r)
    except Exception as e:
        print(f"[macro] PG/Thopen indisponível: {e}")
    try:                                      # API PV (cache prewarmed) — completa o que faltar
        for r in (_cache.get("payload") or {}).get("rows", []):
            add("API PV", r)
    except Exception as e:
        print(f"[macro] API PV indisponível: {e}")
    try:                                      # Athon (SunOp gridco) — SÓ cache, sem fetch novo
        for r in (_sunop_cache.get("payload") or {}).get("rows", []):
            add("Athon", r)
    except Exception as e:
        print(f"[macro] SunOp/Athon indisponível: {e}")
    try:                                      # Axis (SunOp axis) — SÓ cache
        for r in (_axis_cache.get("payload") or {}).get("rows", []):
            add("Axis", r)
    except Exception as e:
        print(f"[macro] Axis indisponível: {e}")
    try:                                      # 2C / Owen (arquivos locais, barato/cacheado)
        for r in _owen_strings_rows():
            add("2C", r)
    except Exception as e:
        print(f"[macro] 2C/Owen indisponível: {e}")

    usinas = list(por_usina.values())
    # Guard de telemetria parada: se a frota está lendo fresco (dia/sistema no ar) mas uma usina
    # está com a última leitura velha (>2h), é problema de comunicação — não "sem geração".
    # À noite/sistema fora, a frota inteira fica velha → fleet_up=False → não reclassifica nada.
    idades = [_macro_idade_h(u.get("ultima_leitura")) for u in usinas]
    fresca = min([a for a in idades if a is not None], default=None)
    fleet_up = fresca is not None and fresca < 1.0
    if fleet_up:
        for u, a in zip(usinas, idades):
            # usina PARADA (potência ~0) fica como 'sem produção' mesmo com leitura velha — ela parou de
            # enviar PORQUE está desligada; só reclassifica p/ comm quem NÃO é sem_producao.
            if a is not None and a > 2 and u["status"] not in ("sem_comm", "sem_producao"):
                u["status"] = "sem_comm"
                u["sev"] = 3
                u["causa"] = f"Telemetria parada (última leitura {u.get('ultima_leitura')})"
                u["strings_faltando"] = 0

    for u in usinas:                          # estado/região (Info Geral) por usina → agrupamento e rondas
        ig = INFO_GERAL.get(_nrm(u.get("usina") or "")) or {}
        u["estado"] = ig.get("estado")
        u["regiao"] = ig.get("regiao")
    usinas.sort(key=lambda u: (u["sev"], -u.get("strings_faltando", 0), u.get("usina") or ""))
    return usinas


# ── Tendência por usina (sparkline do Painel NOC) ───────────────────────────────
# Buffer em memória: a cada chamada de /api/macro guardamos um ponto de "saúde" por usina
# (strings faltando + peso por severidade). Honesto: começa curto/plano e enche com o tempo
# de servidor no ar — não inventa histórico. Serve só pra direção (piorando/estável/melhorando).
_macro_trend = {}                  # nrm(usina) -> deque[float]  (mais antigo→mais novo)
_MACRO_TREND_MAX = 24
_SEV_PESO = {3: 6.0, 0: 6.0, 1: 3.0, 2: 1.0}   # sem_comm/critico pesam mais que atenção


def _macro_trend_push(usinas):
    from collections import deque
    vistos = set()
    for u in usinas:
        k = _nrm(u.get("usina") or "")
        if not k:
            continue
        vistos.add(k)
        score = float(u.get("strings_faltando") or 0) + _SEV_PESO.get(u.get("sev"), 0.0)
        dq = _macro_trend.get(k)
        if dq is None:
            dq = _macro_trend[k] = deque(maxlen=_MACRO_TREND_MAX)
        dq.append(round(score, 2))


def _macro_trend_serie(usina):
    dq = _macro_trend.get(_nrm(usina or ""))
    return list(dq) if dq else []


@app.route("/api/macro")
def api_macro():
    us = _portfolio_rollup()
    try:                                       # enriquece com a CAUSA do motor (onde há telemetria)
        diags = _macro_diags()
        for u in us:
            d = diags.get(_nrm(u.get("usina") or ""))
            if d:
                u["diag"] = d
    except Exception as e:
        print(f"[macro] diag enrich falhou: {e}")
    _macro_trend_push(us)                      # tendência (sparkline) por usina — buffer em memória
    for u in us:
        u["trend"] = _macro_trend_serie(u.get("usina"))
    resumo = {"total": len(us)}
    for st in ("critico", "atencao", "sem_comm", "ok"):
        resumo[st] = sum(1 for u in us if u["status"] == st)
    resumo["strings_faltando"] = sum(u.get("strings_faltando", 0) for u in us)
    resumo["com_diagnostico"] = sum(1 for u in us if u.get("diag"))
    return jsonify({"usinas": us, "resumo": resumo,
                    "cache_ts": datetime.now().strftime("%H:%M:%S")})


# ══ VISÃO GERENCIAL (Painel 3) — Fatia 1: Gerada × Recurso × P50 por usina/cliente ═══
# Mês corrente (MTD). Fonte: PG (geração + IPOA medido) + INFO_GERAL/PR_PREVISTO (P50/IPOA
# previsto/cliente/potência). Degradação graciosa: usina sem match/dado fica fora dos totais.
# Receita (R$) e garantias contratuais = Fatia 3 (faltam tarifa/PPA); O&M = Fatia 2 (Fracttal).
GER_META_MIN = 95.0   # % de atingimento p/ contar a usina "dentro da meta"
_ger_cache = {"ts": 0.0, "data": None}
GER_TTL = 300

# ── Geração mensal das carteiras NÃO-PG (Thopen/Copel/Matrix) ────────────────────
# O PG só tem a frota Polaris/Raízen em tempo real; as demais carteiras têm a geração do mês nas
# abas diárias do BD_Thopen (+ planilhas externas Matrix/Copel). Reusa o engine do dashboard_thopen
# (módulo standalone, sem import circular). Cacheado + aquecido em BACKGROUND: a leitura do xlsx é
# pesada → NUNCA bloqueia o /api/gerencial (frio = cai pro PG-only nessa chamada, enche na próxima).
_thopen_prod_cache = {"ts": 0.0, "ym": None, "data": {}, "warming": False}
_THOPEN_PROD_TTL = 1800


def _carteira_de(usina):
    try:
        import dashboard_thopen as _dth
        return _dth._CARTEIRA_DE.get((usina or "").strip())
    except Exception:
        return None


def _thopen_prod_build():
    out = {}
    try:
        import dashboard_thopen as _dth
        hoje = datetime.now()
        reg = _dth._registro()                       # T_Usinas: {usina: {cliente, pot_mwp, ...}}
        universo = set(reg.keys()) | set(_dth._CARTEIRA_DE.keys())
        for u in universo:
            if _dth._CARTEIRA_DE.get(u) == "Polaris":   # Polaris já vem do PG (tempo real)
                continue
            try:
                recs = _dth._daily_records(u)
            except Exception:
                continue
            prod = sum(r["ger"] for r in recs
                       if r.get("ger") and r["data"].year == hoje.year and r["data"].month == hoje.month)
            if prod > 0:
                out[_nrm(u)] = {"usina": u, "prod_mwh": prod / 1000.0,
                                "carteira": _dth._CARTEIRA_DE.get(u),
                                "pot_mwp": (reg.get(u) or {}).get("pot_mwp"),
                                "cliente": (reg.get(u) or {}).get("cliente")}
        print(f"[gerencial] Thopen prod MTD (xlsx): {len(out)} usinas")
    except Exception as e:
        print(f"[gerencial] Thopen prod build falhou: {e}")
    _thopen_prod_cache.update({"data": out, "ts": time.time(),
                               "ym": (datetime.now().year, datetime.now().month), "warming": False})


def _thopen_prod_mtd():
    """Map cacheado {nrm: {usina,prod_mwh,carteira,pot_mwp,cliente}}; aquece em background quando
    frio/velho (a 1ª carga do xlsx demora) → nunca bloqueia o /api/gerencial."""
    ym = (datetime.now().year, datetime.now().month)
    c = _thopen_prod_cache
    if (c["ym"] != ym or (time.time() - c["ts"]) >= _THOPEN_PROD_TTL) and not c["warming"]:
        c["warming"] = True
        threading.Thread(target=_thopen_prod_build, daemon=True).start()
    return c["data"] or {}


# ── Geração MTD Athon/Axis/2C: abas por-usina do BD_Performance (meta P50 = Info Geral) ──
#   Cada usina Athon/Axis/2C tem uma aba própria no BD_Performance com geração diária por
#   inversor (colunas "Inversor *"). Somamos o mês corrente; a meta P50 (anual) vem da Info Geral.
#   Isso libera atingimento/energia perdida dessas fontes (antes só PG + Thopen tinham meta).
_bdperf_prod_cache = {"ts": 0.0, "ym": None, "data": {}, "warming": False}
_BDPERF_PROD_TTL = 1800
_BDPERF_FONTES = {"athon", "axis", "2c"}


def _bdperf_prod_build():
    out = {}
    try:
        import openpyxl
        hoje = datetime.now()
        hoje_d = hoje.date()
        wb = openpyxl.load_workbook(_bd_readable_path(), read_only=True, data_only=True)
        sheets = set(wb.sheetnames)
        for k, ig in INFO_GERAL.items():
            if (ig.get("cliente") or "").strip().lower() not in _BDPERF_FONTES:
                continue
            nome = ig.get("usina")
            if nome not in sheets:
                continue
            try:
                it = wb[nome].iter_rows(values_only=True)
                hdr = next(it, None) or ()
                invcols = [i for i, h in enumerate(hdr) if h and str(h).startswith("Inversor")]
                if not invcols:
                    continue
                ii = next((i for i, h in enumerate(hdr) if h and "IPOA" in str(h) and "DEF" in str(h)), None)
                etmc = [i for i, h in enumerate(hdr) if h and "IPOA" in str(h).upper() and "ETM" in str(h).upper()]
                tot = 0.0        # geração do mês inteiro (prod_mwh MTD)
                gen_pr = 0.0     # geração só dos dias com IPOA utilizável (numerador do PR)
                ipoa = 0.0
                for r in it:
                    d = r[1] if len(r) > 1 else None
                    if not isinstance(d, datetime) or d.year != hoje.year or d.month != hoje.month:
                        continue
                    rowgen = sum(r[i] for i in invcols if i < len(r) and isinstance(r[i], (int, float)))
                    tot += rowgen
                    if d.date() < hoje_d:               # PR só de dias COMPLETOS
                        ipd = r[ii] if (ii is not None and ii < len(r)) else None
                        ip = None
                        if isinstance(ipd, (int, float)):
                            if ipd > 0.5:               # DEF fechada usa; ==0 = rejeição → pula
                                ip = ipd
                        else:                           # DEF vazia → melhor IPOA ETM medida
                            cand = [r[i] for i in etmc
                                    if i < len(r) and isinstance(r[i], (int, float)) and r[i] > 0.5]
                            if cand:
                                ip = max(cand)
                        if ip is not None:
                            ipoa += ip; gen_pr += rowgen
                if tot > 0:
                    mwp = ig.get("potencia_mwp")
                    pr = (gen_pr / (mwp * 1000.0 * ipoa) * 100) if (mwp and ipoa and gen_pr) else None
                    rec = pr_previsto(nome)
                    prm = rec.get("pr_previsto") if rec else None
                    out[k] = {"usina": nome, "prod_mwh": tot / 1000.0,
                              "cliente": ig.get("cliente"), "pot_mwp": mwp,
                              "pr": round(pr, 1) if pr is not None else None,
                              "pr_meta": round(prm * 100, 1) if isinstance(prm, (int, float)) else None}
            except Exception:
                continue
        try:
            wb.close()
        except Exception:
            pass
        print(f"[gerencial] BD_Performance prod MTD (Athon/Axis/2C): {len(out)} usinas")
    except Exception as e:
        print(f"[gerencial] BD_Performance prod build falhou: {e}")
    _bdperf_prod_cache.update({"data": out, "ts": time.time(),
                               "ym": (datetime.now().year, datetime.now().month), "warming": False})


def _bdperf_prod_mtd():
    """Map cacheado {nrm: {usina,prod_mwh,cliente,pot_mwp}} das usinas Athon/Axis/2C; aquece em
    background (a 1ª leitura de ~13 abas do xlsx demora) → não bloqueia o /api/gerencial."""
    ym = (datetime.now().year, datetime.now().month)
    c = _bdperf_prod_cache
    if (c["ym"] != ym or (time.time() - c["ts"]) >= _BDPERF_PROD_TTL) and not c["warming"]:
        c["warming"] = True
        threading.Thread(target=_bdperf_prod_build, daemon=True).start()
    return c["data"] or {}


# ── PR MENSAL por inversor (heatmap do drill) — abas por-usina do BD_Performance ──────────────
#   PR_inv = Σ geração_inv ÷ (potência_inv × Σ IPOA válida) no mês. ABSOLUTO (geração÷IPOA×kWp,
#   mesma régua do projeto "Geração Diária"); flag 'sensor' quando o PR sai fisicamente impossível
#   (>130% → IPOA subestimada). Potência/inversor ~= MWp da Info Geral ÷ nº de inversores da aba.
#   IPOA por dia: usa a DEF quando fechada (>0.5); DEF==0 = rejeição do analista → pula o dia;
#   DEF em branco = dia ainda não fechado → cai p/ a melhor IPOA medida (ETM). Conta só dias
#   COMPLETOS (exclui o dia em curso). Sem gate de "Validação" — o gate é ter IPOA utilizável.
_bdperf_pr_cache = {}          # usina_nrm -> {ts, ym, data}
_BDPERF_PR_TTL = 1800


def _bdperf_pr_inv(usina):
    k = _nrm(usina)
    ym = (datetime.now().year, datetime.now().month)
    ent = _bdperf_pr_cache.get(k)
    if ent and ent["ym"] == ym and (time.time() - ent["ts"]) < _BDPERF_PR_TTL:
        return ent["data"]
    out = {"inversores": {}, "ipoa_mes": None, "ndias": 0, "sensor": False,
           "mes": datetime.now().strftime("%m/%Y")}
    try:
        import openpyxl
        hoje = datetime.now()
        wb = openpyxl.load_workbook(_bd_readable_path(), read_only=True, data_only=True)
        nome = next((s for s in wb.sheetnames if _nrm(s) == k), None)
        if not nome:
            wb.close(); return out
        mwp = (INFO_GERAL.get(k) or {}).get("potencia_mwp")
        it = wb[nome].iter_rows(values_only=True)
        hdr = next(it, None) or ()
        invc = [(i, str(h)) for i, h in enumerate(hdr) if h and str(h).startswith("Inversor")]
        ii = next((i for i, h in enumerate(hdr) if h and "IPOA" in str(h) and "DEF" in str(h)), None)
        # IPOA medida (ETM) — fallback quando a DEF ainda não foi fechada. Pode haver mais de uma
        # estação (ETM 1/ETM 2); usa a MAIOR leitura válida do dia (a menor costuma ser sensor furado).
        etmc = [i for i, h in enumerate(hdr) if h and "IPOA" in str(h).upper() and "ETM" in str(h).upper()]
        gen = {nm: 0.0 for _, nm in invc}
        ipoa, ndias = 0.0, 0
        hoje_d = hoje.date()
        for r in it:
            d = r[1] if len(r) > 1 else None
            # só dias COMPLETOS do mês corrente (exclui o dia em curso p/ não distorcer o MTD)
            if not (isinstance(d, datetime) and d.year == hoje.year and d.month == hoje.month
                    and d.date() < hoje_d):
                continue
            ipd = r[ii] if (ii is not None and ii < len(r)) else None
            if isinstance(ipd, (int, float)):
                if ipd <= 0.5:          # DEF==0 = analista rejeitou/sem dado no dia → pula
                    continue
                ip = ipd                # DEF fechada → usa
            else:                       # DEF em branco → melhor IPOA medida (ETM) do dia
                cand = [r[i] for i in etmc
                        if i < len(r) and isinstance(r[i], (int, float)) and r[i] > 0.5]
                ip = max(cand) if cand else None
                if ip is None:
                    continue
            ipoa += ip; ndias += 1
            for i, nm in invc:
                v = r[i] if i < len(r) else None
                if isinstance(v, (int, float)):
                    gen[nm] += v
        wb.close()
        pinv = (mwp * 1000.0 / len(invc)) if (mwp and invc) else None
        for nm, g in gen.items():
            pr = (g / (pinv * ipoa)) if (pinv and ipoa and g) else None
            if pr is not None and pr > 1.3:
                out["sensor"] = True
            out["inversores"][nm] = {"pr": round(pr * 100, 1) if pr is not None else None,
                                     "gen_mwh": round(g / 1000.0, 1)}
        # PR Meta da UFV (Info Mensal — régua Power BI, já com degradação) p/ o comparativo por
        # inversor; e PR MTD da usina inteira (Σgeração ÷ (MWp × Σipoa)) como contexto.
        rec = pr_previsto(usina)
        prm = rec.get("pr_previsto") if rec else None
        tot_g = sum(gen.values())
        out.update({"ipoa_mes": round(ipoa, 1), "ndias": ndias,
                    "pot_inv_kwp": round(pinv, 1) if pinv else None,
                    "pr_meta": round(prm * 100, 1) if isinstance(prm, (int, float)) else None,
                    "pr_usina": (round(tot_g / (mwp * 1000.0 * ipoa) * 100, 1)
                                 if (mwp and ipoa and tot_g) else None)})
    except Exception as e:
        out["erro"] = str(e)
    _bdperf_pr_cache[k] = {"ts": time.time(), "ym": ym, "data": out}
    return out


@app.route("/api/inv/pr-mes")
def api_inv_pr_mes():
    """PR mensal (MTD) por inversor de uma usina (abas do BD_Performance). ?usina=<nome display>."""
    usina = (flask_request.args.get("usina") or "").strip()
    if not usina:
        return jsonify({"error": "usina required", "inversores": {}}), 400
    return jsonify(_bdperf_pr_inv(usina))


# ── ETM: varredura de PROBLEMAS que impedem/estragam o PR (visão "ETM" da Frota) ──────────────
#   Régua (pedido do Levi 05/07): IPOA nula/zerada · GHI nula/zerada · IPOA/GHI CONSTANTE por
#   vários dias (sensor travado, ex. -1) · PR anômalo (>130% ou <0 = IPOA subestimada, régua do
#   SENSOR). Fontes: série diária das abas por-usina do BD_Performance (IPOA ETM/GHI do mês) +
#   /api/gerencial (IPOA do PG zerada com produção; PR anômalo em qualquer fonte).
_etm_prob_cache = {"ts": 0.0, "data": None}
_ETM_PROB_TTL = 900


def _etm_problemas_build():
    hoje = datetime.now()
    hoje_d = hoje.date()
    probs = {}   # nrm -> {"usina","cliente","problemas":[...]}

    def add(nome, cliente, txt):
        p = probs.setdefault(_nrm(nome), {"usina": nome, "cliente": cliente or "—", "problemas": []})
        if txt not in p["problemas"]:
            p["problemas"].append(txt)

    # 1) Abas por-usina do BD_Performance — série DIÁRIA de IPOA (ETM) e GHI do mês corrente
    try:
        import openpyxl
        wb = openpyxl.load_workbook(_bd_readable_path(), read_only=True, data_only=True)
        sheets = set(wb.sheetnames)
        for k, ig in INFO_GERAL.items():
            nome = ig.get("usina")
            if nome not in sheets:
                continue
            try:
                it = wb[nome].iter_rows(values_only=True)
                hdr = next(it, None) or ()
                etmc = [i for i, h in enumerate(hdr) if h and "IPOA" in str(h).upper() and "ETM" in str(h).upper()]
                ghic = [i for i, h in enumerate(hdr) if h and str(h).strip().upper().startswith("GHI")]
                if not etmc and not ghic:
                    continue
                si, sg = [], []      # série diária (dias completos do mês): melhor leitura do dia
                for r in it:
                    d = r[1] if len(r) > 1 else None
                    if not (isinstance(d, datetime) and d.year == hoje.year
                            and d.month == hoje.month and d.date() < hoje_d):
                        continue
                    iv = [r[i] for i in etmc if i < len(r) and isinstance(r[i], (int, float))]
                    gv = [r[i] for i in ghic if i < len(r) and isinstance(r[i], (int, float))]
                    si.append(max(iv) if iv else None)
                    sg.append(max(gv) if gv else None)

                def _diag(serie, rot, trava_pr=False):
                    if not serie:
                        return
                    suf = " — PR não calculável" if trava_pr else ""
                    vals = [v for v in serie if v is not None]
                    if not vals or all(v <= 0.5 for v in vals):
                        add(nome, ig.get("cliente"), f"{rot} sem leitura/zerada no mês inteiro ({len(serie)}d){suf}")
                        return
                    # valor CONSTANTE ≥3 dias seguidos (sensor travado; pega -1, 0.0 repetido etc.)
                    run_v = None; run_n = 0; best_v = None; best_n = 0
                    for v in serie:
                        if v is not None and v == run_v:
                            run_n += 1
                        else:
                            run_v, run_n = v, (1 if v is not None else 0)
                        if run_v is not None and run_n > best_n:
                            best_v, best_n = run_v, run_n
                    if best_n >= 3:
                        add(nome, ig.get("cliente"), f"{rot} constante em {round(best_v, 3)} por {best_n} dias seguidos (sensor travado?)")
                    nz = sum(1 for v in vals if v <= 0.5)
                    if 3 <= nz < len(vals):
                        add(nome, ig.get("cliente"), f"{rot} zerada/nula em {nz} de {len(serie)} dias")
                _diag(si, "IPOA (ETM)", trava_pr=True)   # sem IPOA não há PR
                _diag(sg, "GHI")                          # GHI não trava o PR, mas é sensor doente
            except Exception:
                continue
        wb.close()
    except Exception as e:
        print(f"[etm/problemas] BD_Performance falhou: {e}")

    # 2) Gerencial — IPOA do PG zerada com produção (PR não sai) + PR anômalo em qualquer fonte
    try:
        g = _gerencial_payload()
        for u in g.get("usinas", []):
            pr = u.get("pr")
            if u.get("src") == "pg" and not u.get("ipoa") and (u.get("prod") or 0) > 0:
                add(u["usina"], u.get("cliente"), "IPOA do PG zerada/ausente no mês com usina gerando — PR não calculável")
            if pr is not None and (pr > 130 or pr < 0):
                add(u["usina"], u.get("cliente"), f"PR anômalo ({nfmt(pr)}%) — IPOA subestimada/furada (régua SENSOR >130%)")
    except Exception as e:
        print(f"[etm/problemas] gerencial falhou: {e}")

    itens = sorted(probs.values(), key=lambda p: p["usina"])
    return {"itens": itens, "mes": hoje.strftime("%m/%Y"),
            "cache_ts": datetime.now().strftime("%H:%M:%S")}


def nfmt(v):
    try:
        return f"{v:,.0f}".replace(",", ".")
    except Exception:
        return str(v)


@app.route("/api/etm/problemas")
def api_etm_problemas():
    force = flask_request.args.get("force", "0") == "1"
    c = _etm_prob_cache
    if force or not c["data"] or (time.time() - c["ts"]) >= _ETM_PROB_TTL:
        c["data"] = _etm_problemas_build()
        c["ts"] = time.time()
    out = dict(c["data"])
    # anexa o estado do ticket (comentário + feito) por usina — compartilhado entre analistas
    with _state_lock:
        tk = _load_state().get("etm_tickets", {})
    out["itens"] = [dict(i, ticket=tk.get(_nrm(i["usina"])) or {}) for i in out["itens"]]
    return jsonify(out)


@app.route("/api/etm/ticket", methods=["POST"])
def api_etm_ticket():
    """Salva comentário + checkbox 'Ticket criado?' de uma usina da visão ETM (ufv_state.json)."""
    body = flask_request.get_json(force=True) or {}
    usina = (body.get("usina") or "").strip()
    if not usina:
        return jsonify({"error": "usina required"}), 400
    with _state_lock:
        d = _load_state()
        d.setdefault("etm_tickets", {})[_nrm(usina)] = {
            "usina": usina,
            "comentario": (body.get("comentario") or "").strip()[:2000],
            "feito": bool(body.get("feito")),
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        _save_state(d)
    return jsonify({"ok": True})


# ══ HISTÓRICO D-1 · VISÃO PR — motor do Dashboard de Geração (5070) portado p/ o Painel NOC ═════
#   Mesmas regras do Power BI: PR dia = (ger kWh/1000) ÷ (IPOA_DEF × Pot_MWp) × Validação;
#   agregação SEMPRE ponderada por energia (Σger ÷ ΣIPOA×pot), nunca média de PRs.
#   Fontes: abas por-usina do BD_Performance (com inversor) + BD_Thopen via dashboard_thopen
#   (carteiras Thopen/Copel/Matrix/Polaris — só por USINA, o banco não tem inversor).
_G_META_SHEETS = {"info geral", "info mensal", "equipamentos"}
_G_SKIP_SHEETS = {"falhas", "trackers", "pvsyst", "acumulado anual", "aux"}
_g_reg_cache = {}
_g_cache = {}


def _g_n2(s):
    return _nrm(_unaccent(s))


def _g_match_ig(sheet):
    k = _g_n2(sheet)
    for g in INFO_GERAL.values():
        if _g_n2(g.get("usina", "")) == k:
            return g
    for g in INFO_GERAL.values():
        gk = _g_n2(g.get("usina", ""))
        if gk and (gk.startswith(k) or k.startswith(gk)):
            return g
    return None


def _g_registry():
    """(USINAS, CLIENTES) das abas do BD_Performance × Info Geral, cacheado por mtime."""
    from openpyxl import load_workbook
    try:
        m = os.path.getmtime(_bd_perf_path())
    except OSError:
        m = 0.0
    if m in _g_reg_cache:
        return _g_reg_cache[m]
    wb = load_workbook(_bd_readable_path(), read_only=True)
    sheets = wb.sheetnames
    wb.close()
    d2s = {_g_n2(dsp): sup for sup, dsp in USINA_DISPLAY.items()}
    usinas, clientes = {}, {}
    for s in sheets:
        sl = s.strip().lower()
        if sl in _G_META_SHEETS or sl in _G_SKIP_SHEETS or "backup" in sl or sl.startswith("plan"):
            continue
        g = _g_match_ig(s)
        if not g or not g.get("cliente"):
            continue
        canon, cli = g["usina"], g["cliente"]
        usinas[canon] = {"sheet": s, "sup": d2s.get(_g_n2(canon)) or canon, "cliente": cli}
        clientes.setdefault(cli, []).append(canon)
    for c in clientes:
        clientes[c].sort()
    _g_reg_cache.clear()
    _g_reg_cache[m] = (usinas, clientes)
    return usinas, clientes


def _g_find(cols, *needles, exclude=()):
    nd = [n.lower() for n in needles]
    ex = [e.lower() for e in exclude]
    for c in cols:
        cl = str(c).lower()
        if all(n in cl for n in nd) and not any(e in cl for e in ex):
            return c
    return None


def _g_build(entries):
    """entries=[(canon, sheet, sup)] → (inv_df, dia_df) por inversor/dia e usina/dia.
    Lê TODAS as abas numa única passada do xlsx (sheet_name=lista) — ler 1 aba por vez
    reabre/parseia o arquivo inteiro N vezes e era o gargalo da visão PR."""
    path = _bd_readable_path()
    inv_rows, dia_rows = [], []
    try:
        dfs = pd.read_excel(path, sheet_name=[s for _, s, _ in entries], header=0)
    except Exception:
        dfs = {}
    for canon, sheet, sup in entries:
        df = dfs.get(sheet)
        if df is None:
            continue
        df.columns = [str(c).strip() for c in df.columns]
        c_data = _g_find(df.columns, "data")
        c_ipoa = _g_find(df.columns, "ipoa", "def") or _g_find(df.columns, "ipoa", "etm") \
            or _g_find(df.columns, "ipoa")
        c_val = next((c for c in df.columns if str(c).lower().startswith("valida")), None)
        inv_cols = [c for c in df.columns if str(c).lower().startswith("inversor")]
        if not c_data or not inv_cols:
            continue
        for _, r in df.iterrows():
            if pd.isna(r[c_data]):
                continue
            dt = pd.to_datetime(r[c_data], errors="coerce")
            if pd.isna(dt):
                continue
            ipoa = _num(r[c_ipoa]) if c_ipoa else None
            val = _num(r[c_val]) if c_val else None
            for ic in inv_cols:
                gen = _num(r[ic])
                if gen is None:
                    continue
                pot = _pot_inv(sup, ic)
                pr = (gen / (ipoa * pot) * val) if (pot and ipoa and ipoa > 0 and val is not None) else None
                inv_rows.append({"usina": canon, "data": dt, "ano": dt.year, "mes": dt.month,
                                 "inversor": ic, "geracao": gen, "ipoa": ipoa, "validacao": val,
                                 "pot_kwp": pot, "pr": pr})
            gen_dia = sum(_num(r[ic]) or 0.0 for ic in inv_cols)
            dia_rows.append({"usina": canon, "data": dt, "ano": dt.year, "mes": dt.month,
                             "geracao": gen_dia, "ipoa": ipoa, "validacao": val})
    return pd.DataFrame(inv_rows), pd.DataFrame(dia_rows)


_g_lock = threading.Lock()


def _g_get(cliente):
    usinas, clientes = _g_registry()
    try:
        m = os.path.getmtime(_bd_perf_path())
    except OSError:
        m = 0.0
    key = (cliente, m)
    # lock: os 3 gráficos da visão PR chegam JUNTOS — sem isto, 3 builds paralelos do mesmo cliente
    with _g_lock:
        if key not in _g_cache:
            entries = [(c, usinas[c]["sheet"], usinas[c]["sup"]) for c in clientes.get(cliente, [])]
            _g_cache[key] = _g_build(entries)
    return _g_cache[key]


def _g_pr_pond(df_dia, usina_disp):
    g = info_geral(usina_disp)
    pot_mwp = (g or {}).get("potencia_mwp")
    val = df_dia[(df_dia["validacao"] > 0) & (df_dia["ipoa"] > 0)]
    if not pot_mwp or val.empty:
        return None
    den = val["ipoa"].sum() * pot_mwp
    return (val["geracao"].sum() / 1000.0 / den) if den else None


# --- engine BD_Thopen (carteiras do banco; POR USINA — o banco não tem inversor) ---
def _g_th_carteiras():
    try:
        import dashboard_thopen as _dth
        return sorted(set(c for c in _dth._CARTEIRA_DE.values() if c))
    except Exception:
        return []


def _g_th_usinas(carteira):
    import dashboard_thopen as _dth
    return sorted(u for u, c in _dth._CARTEIRA_DE.items() if c == carteira)


def _g_th_pot(usina):
    import dashboard_thopen as _dth
    reg = _dth._registro()
    return (reg.get(usina) or {}).get("pot_mwp") or (INFO_GERAL.get(_nrm(usina)) or {}).get("potencia_mwp")


def _g_th_meta(usina, ano, mes):
    """Meta de PR (fração): Info Mensal (pr_previsto); fallback Historico_2026 do BD_Thopen."""
    rec = pr_previsto(usina, ano, mes)
    prm = (rec or {}).get("pr_previsto")
    if prm is None:
        prm = ((THOPEN_META.get(_nrm(usina)) or {}).get(mes) or {}).get("pr_meta")
    if isinstance(prm, (int, float)) and prm > 2:   # planilha em %, não fração
        prm /= 100.0
    return prm


def _g_th_daily(usina):
    import dashboard_thopen as _dth
    return [r for r in _dth._daily_records(usina)
            if r.get("ger") and r.get("ipoa") and r["ipoa"] > 0.3]


@app.route("/api/g/clientes")
def api_g_clientes():
    _, cls = _g_registry()
    return jsonify(sorted(set(cls.keys()) | set(_g_th_carteiras())))


@app.route("/api/g/usinas")
def api_g_usinas():
    cli = flask_request.args.get("cliente", "")
    if cli in _g_th_carteiras():                     # carteira do banco (prioridade — pedido do Levi)
        return jsonify(_g_th_usinas(cli))
    _, cls = _g_registry()
    return jsonify(cls.get(cli, []))


@app.route("/api/g/mensal")
def api_g_mensal():
    cli = flask_request.args.get("cliente", "")
    u = flask_request.args.get("usina", "")
    if cli in _g_th_carteiras():
        pot = _g_th_pot(u)
        por = {}
        for r in _g_th_daily(u):
            k = (r["data"].year, r["data"].month)
            a = por.setdefault(k, [0.0, 0.0])
            a[0] += r["ger"]; a[1] += r["ipoa"]
        pts = [{"ano": a, "mes": m,
                "realizado": (g / 1000.0 / (ip * pot)) if (pot and ip) else None,
                "meta": _g_th_meta(u, a, m)} for (a, m), (g, ip) in sorted(por.items())]
        return jsonify({"usina": u, "fonte": "bd_thopen", "pontos": pts})
    _, dia = _g_get(cli)
    disp = (INFO_GERAL.get(_nrm(u), {}) or {}).get("usina", u)
    out = []
    if not dia.empty:
        for (ano, mes), grp in dia[dia["usina"] == disp].groupby(["ano", "mes"]):
            rec = pr_previsto(disp, int(ano), int(mes))
            out.append({"ano": int(ano), "mes": int(mes), "realizado": _g_pr_pond(grp, disp),
                        "meta": (rec or {}).get("pr_previsto")})
        out.sort(key=lambda x: (x["ano"], x["mes"]))
    return jsonify({"usina": disp, "fonte": "bd_perf", "pontos": out})


@app.route("/api/g/diario")
def api_g_diario():
    cli = flask_request.args.get("cliente", "")
    u = flask_request.args.get("usina", "")
    ano = int(flask_request.args.get("ano")); mes = int(flask_request.args.get("mes"))
    if cli in _g_th_carteiras():
        pot = _g_th_pot(u)
        pts = [{"dia": r["data"].day,
                "realizado": (r["ger"] / 1000.0 / (r["ipoa"] * pot)) if pot else None}
               for r in _g_th_daily(u) if r["data"].year == ano and r["data"].month == mes]
        pts.sort(key=lambda p: p["dia"])
        return jsonify({"usina": u, "meta": _g_th_meta(u, ano, mes), "pontos": pts})
    _, dia = _g_get(cli)
    disp = (INFO_GERAL.get(_nrm(u), {}) or {}).get("usina", u)
    g = info_geral(disp)
    pot_mwp = (g or {}).get("potencia_mwp")
    rec = pr_previsto(disp, ano, mes)
    pts = []
    if not dia.empty:
        sub = dia[(dia["usina"] == disp) & (dia["ano"] == ano) & (dia["mes"] == mes)]
        for _, r in sub.sort_values("data").iterrows():
            pr = None
            if pot_mwp and r["ipoa"] and r["ipoa"] > 0 and r["validacao"]:
                pr = (r["geracao"] / 1000.0) / (r["ipoa"] * pot_mwp) * r["validacao"]
            pts.append({"dia": int(r["data"].day), "realizado": pr})
    return jsonify({"usina": disp, "meta": (rec or {}).get("pr_previsto"), "pontos": pts})


@app.route("/api/g/inversores")
def api_g_inversores():
    cli = flask_request.args.get("cliente", "")
    u = flask_request.args.get("usina", "")
    if cli in _g_th_carteiras():                     # banco é por usina — sem visão de inversor
        return jsonify({"usina": u, "alvo": None, "por_usina": True, "inversores": []})
    ini = pd.to_datetime(flask_request.args.get("ini")) if flask_request.args.get("ini") else None
    fim = pd.to_datetime(flask_request.args.get("fim")) if flask_request.args.get("fim") else None
    inv, _ = _g_get(cli)
    disp = (INFO_GERAL.get(_nrm(u), {}) or {}).get("usina", u)
    if inv.empty:
        return jsonify({"usina": disp, "alvo": None, "inversores": []})
    sub = inv[inv["usina"] == disp].copy()
    if ini is not None:
        sub = sub[sub["data"] >= ini]
    if fim is not None:
        sub = sub[sub["data"] <= fim]
    sub = sub[(sub["validacao"] > 0) & (sub["ipoa"] > 0)]
    rows = []
    for nome, grp in sub.groupby("inversor"):
        pot = grp["pot_kwp"].dropna()
        if grp.empty or pot.empty:
            continue
        den = grp["ipoa"].sum() * (pot.iloc[0] / 1000.0)
        rows.append({"inversor": nome, "pr": (grp["geracao"].sum() / 1000.0 / den) if den else None})
    alvo = None
    if not sub.empty:
        d0 = sub["data"].min()
        alvo = (pr_previsto(disp, d0.year, d0.month) or {}).get("pr_previsto")
    for r in rows:
        r["alvo"] = alvo
        r["dif"] = (r["pr"] - alvo) if (r["pr"] is not None and alvo is not None) else None
    rows.sort(key=lambda x: (x["pr"] is None, x["pr"]))
    return jsonify({"usina": disp, "alvo": alvo, "inversores": rows})


def _gerencial_payload(force=False):
    if not force and _ger_cache["data"] and (time.time() - _ger_cache["ts"]) < GER_TTL:
        return _ger_cache["data"]
    hoje = datetime.now().date()
    ini = hoje.replace(day=1)
    dias_mes = calendar.monthrange(hoje.year, hoje.month)[1]
    prorata = hoje.day / dias_mes
    ym = (hoje.year, hoje.month)
    try:
        gen = _pg_geracao_periodo(ini.strftime("%Y-%m-%d"), hoje.strftime("%Y-%m-%d"))
    except Exception as e:
        return {"erro": str(e), "usinas": [], "clientes": [], "portfolio": {}, "scorecard": {},
                "mes": hoje.strftime("%m/%Y"), "cache_ts": datetime.now().strftime("%H:%M:%S")}
    # 1) agrega produzida (kWh) + IPOA real (kWh/m²) por usina canônica
    agg = {}
    for row in gen:
        name, ger, ipoa = row.get("usina"), row.get("geracao_kwh"), row.get("ipoa")
        if not name or name == "—":
            continue
        nome = _macro_usina_nome(name)
        d = agg.setdefault(_nrm(nome), {"usina": nome, "prod_kwh": 0.0, "ipoa": 0.0})
        if isinstance(ger, (int, float)):  d["prod_kwh"] += ger
        if isinstance(ipoa, (int, float)): d["ipoa"]     += ipoa
    # 2) decompõe por usina (casa com INFO_GERAL/PR_PREVISTO; P50/IPOA previsto prorrateados MTD)
    usinas, sem_match = [], 0
    for k, d in agg.items():
        ig = INFO_GERAL.get(k)
        if not ig:
            sem_match += 1
            continue
        # META: 1º BD_Thopen (banco), depois Info Mensal (outras carteiras), por fim P50 anual/12
        tm = (THOPEN_META.get(k) or {}).get(hoje.month) or {}
        p50_mes, ipoa_prev_mes = tm.get("meta_mwh"), tm.get("ipoa_meta")
        p50_src = "thopen" if p50_mes else None
        if p50_mes is None or ipoa_prev_mes is None:
            prm_all = PR_PREVISTO.get(k) or {}
            prm = prm_all.get(ym) or {}
            if p50_mes is None and prm.get("p50_mwh"):
                p50_mes, p50_src = prm["p50_mwh"], "mes_exato"
            if ipoa_prev_mes is None:
                ipoa_prev_mes = prm.get("ipoa_previsto")
            if p50_mes is None or ipoa_prev_mes is None:    # ano-base → mesmo mês
                for (yy, mm), v in prm_all.items():
                    if mm == hoje.month:
                        if p50_mes is None and v.get("p50_mwh"):
                            p50_mes, p50_src = v["p50_mwh"], "mesmo_mes"
                        if ipoa_prev_mes is None:
                            ipoa_prev_mes = v.get("ipoa_previsto")
        if p50_mes is None and ig.get("p50_mwh"):           # último recurso: P50 ANUAL rateado
            p50_mes, p50_src = ig["p50_mwh"] / 12.0, "anual_12"
        pot = ig.get("potencia_mwp")
        prod = d["prod_kwh"] / 1000.0
        p50 = (p50_mes * prorata) if p50_mes else None
        ipoa_prev = (ipoa_prev_mes * prorata) if ipoa_prev_mes else None
        recurso = (p50 * (d["ipoa"] / ipoa_prev)) if (p50 and ipoa_prev and d["ipoa"]) else None
        atg = (prod / p50 * 100) if p50 else None
        pr  = (prod / (d["ipoa"] * pot) * 100) if (d["ipoa"] and pot) else None
        _rec = pr_previsto(d["usina"]); _prm = _rec.get("pr_previsto") if _rec else None
        usinas.append({"usina": d["usina"], "cliente": ig.get("cliente") or "—",
                       "carteira": _carteira_de(d["usina"]) or ig.get("cliente") or "—",
                       "prod": round(prod, 1), "p50": round(p50, 1) if p50 else None,
                       "recurso": round(recurso, 1) if recurso else None,
                       "pot_mwp": pot, "atingimento": round(atg, 1) if atg is not None else None,
                       "pr": round(pr, 1) if pr is not None else None,
                       "pr_meta": round(_prm * 100, 1) if isinstance(_prm, (int, float)) else None,
                       "ipoa": round(d["ipoa"], 1), "p50_src": p50_src, "src": "pg"})

    # 2b) carteiras NÃO-PG (Thopen/Copel/Matrix): geração do mês via BD_Thopen (motor dashboard_thopen)
    pg_keys = set(agg.keys())
    for k, tp in _thopen_prod_mtd().items():
        if k in pg_keys:                                   # já veio do PG (tempo real)
            continue
        tm = (THOPEN_META.get(k) or {}).get(hoje.month) or {}
        p50_mes = tm.get("meta_mwh"); p50_src = "thopen" if p50_mes else None
        if p50_mes is None:
            prm_all = PR_PREVISTO.get(k) or {}
            if (prm_all.get(ym) or {}).get("p50_mwh"):
                p50_mes, p50_src = prm_all[ym]["p50_mwh"], "mes_exato"
            else:
                for (yy, mm), v in prm_all.items():
                    if mm == hoje.month and v.get("p50_mwh"):
                        p50_mes, p50_src = v["p50_mwh"], "mesmo_mes"; break
        ig = INFO_GERAL.get(k)
        if p50_mes is None and ig and ig.get("p50_mwh"):
            p50_mes, p50_src = ig["p50_mwh"] / 12.0, "anual_12"
        p50 = (p50_mes * prorata) if p50_mes else None
        prod = tp["prod_mwh"]
        atg = (prod / p50 * 100) if p50 else None
        _rec = pr_previsto(tp["usina"]); _prm = _rec.get("pr_previsto") if _rec else None
        usinas.append({"usina": tp["usina"], "cliente": tp.get("cliente") or "—",
                       "carteira": tp.get("carteira") or "—",
                       "prod": round(prod, 1), "p50": round(p50, 1) if p50 else None,
                       "recurso": None, "pot_mwp": tp.get("pot_mwp"),
                       "atingimento": round(atg, 1) if atg is not None else None,
                       "pr": None, "pr_meta": round(_prm * 100, 1) if isinstance(_prm, (int, float)) else None,
                       "ipoa": 0, "p50_src": (p50_src or "sem"), "src": "bdthopen"})

    # 2c) Athon/Axis/2C: geração do mês via abas por-usina do BD_Performance; meta P50 da Info Geral
    have_k = {_nrm(u["usina"]) for u in usinas}
    for k, bp in _bdperf_prod_mtd().items():
        if k in have_k:
            continue
        ig = INFO_GERAL.get(k) or {}
        p50_mes = (ig.get("p50_mwh") / 12.0) if ig.get("p50_mwh") else None
        p50 = (p50_mes * prorata) if p50_mes else None
        prod = bp["prod_mwh"]
        atg = (prod / p50 * 100) if p50 else None
        usinas.append({"usina": bp["usina"], "cliente": bp.get("cliente") or "—",
                       "carteira": bp.get("cliente") or "—",
                       "prod": round(prod, 1), "p50": round(p50, 1) if p50 else None,
                       "recurso": None, "pot_mwp": bp.get("pot_mwp"),
                       "atingimento": round(atg, 1) if atg is not None else None,
                       "pr": bp.get("pr"), "pr_meta": bp.get("pr_meta"),
                       "ipoa": 0, "p50_src": "infogeral_anual12", "src": "bdperf"})

    def _roll(lst):
        # cada razão sobre o SEU subconjunto válido (não mistura denominadores)
        prod_all = sum(u["prod"] for u in lst if u["prod"] is not None)
        com50 = [u for u in lst if u["p50"]]                     # tem meta → atingimento
        sp50 = sum(u["prod"] for u in com50); s50 = sum(u["p50"] for u in com50)
        comR = [u for u in com50 if u["recurso"]]                # tem recurso → decomposição clima/desemp
        spR = sum(u["prod"] for u in comR); sr = sum(u["recurso"] for u in comR)
        s50R = sum(u["p50"] for u in comR)
        comPR = [u for u in lst if u["ipoa"] and u["pot_mwp"]]   # tem IPOA medido → PR
        spPR = sum(u["prod"] for u in comPR); sipot = sum(u["ipoa"] * u["pot_mwp"] for u in comPR)
        return {"n": len(lst), "n_meta": len(com50), "prod": round(prod_all, 1),
                "p50": round(s50, 1) if s50 else None,
                "recurso": round(sr, 1) if sr else None,
                "atingimento": round(sp50 / s50 * 100, 1) if s50 else None,
                "indice_recurso": round(sr / s50R * 100, 1) if s50R else None,
                "indice_desempenho": round(spR / sr * 100, 1) if sr else None,
                "pr": round(spPR / sipot * 100, 1) if sipot else None,
                "na_meta": sum(1 for u in com50 if (u["atingimento"] or 0) >= GER_META_MIN)}

    portfolio = _roll(usinas)
    # por CARTEIRA (Thopen/Copel/Matrix/Polaris) — a coluna "Cliente" do BD_Performance é genérica
    by_cli = {}
    for u in usinas:
        by_cli.setdefault(u.get("carteira") or u.get("cliente") or "—", []).append(u)
    clientes = [{"cliente": c, **_roll(lst)} for c, lst in by_cli.items()]
    clientes.sort(key=lambda c: (c["atingimento"] is None, c["atingimento"] or 0))
    # melhores/piores (só com atingimento e geração relevante)
    comatg = [u for u in usinas if u["atingimento"] is not None and u["prod"] > 0]
    best = sorted(comatg, key=lambda u: -u["atingimento"])[:6]
    worst = sorted(comatg, key=lambda u: u["atingimento"])[:6]
    out = {"mes": hoje.strftime("%m/%Y"), "prorata": round(prorata, 2),
           "portfolio": portfolio, "clientes": clientes,
           "best": best, "worst": worst, "usinas": usinas,
           "cobertura": {"com_geracao": len(agg), "com_match": len(usinas), "sem_match": sem_match,
                         "p50_srcs": {lbl: sum(1 for u in usinas if (u.get("p50_src") or "sem") == lbl)
                                      for lbl in ("thopen", "mes_exato", "mesmo_mes", "anual_12", "sem")}},
           "cache_ts": datetime.now().strftime("%H:%M:%S")}
    _ger_cache.update({"ts": time.time(), "data": out})
    return out


@app.route("/api/gerencial")
def api_gerencial():
    try:
        return jsonify(_gerencial_payload(force=flask_request.args.get("force") == "1"))
    except Exception as e:
        return jsonify({"erro": str(e), "usinas": [], "clientes": [], "portfolio": {}}), 500


# ══ MOTOR DE DIAGNÓSTICO (Painel 2) — v0, Thopen-first, PEER-RELATIVO ═════════════
# Princípio (da matriz de regras): nunca valor cru, sempre DESVIO vs os pares da usina.
# Assim não dependemos de limiar absoluto (75°C) nem da unidade do Riso. Fonte: a tabela
# analógica por inversor (dbt.stg_inverter_analogic_data) — Riso/temp/estado/potência.
# Fatores relativos (ajustáveis):
DIAG_TRIP_FRAC    = 0.05   # potência < 5% da mediana dos pares  → parado/trip
DIAG_SUBPERF_FRAC = 0.80   # potência < 80% da mediana dos pares → subperformance
DIAG_TEMP_MARGIN  = 8.0    # °C acima da mediana dos pares        → quente (derate)
DIAG_RISO_FRAC    = 0.50   # Riso < 50% da mediana dos pares      → isolação suspeita
DIAG_MIN_PEERS    = 3      # mínimo de inversores p/ comparar com confiança
_pg_analog = {"ts": 0.0, "data": {}}
_pg_analog_lock = threading.Lock()
PG_ANALOG_TTL = 180


def _median(xs):
    xs = sorted(x for x in xs if isinstance(x, (int, float)))
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def _pg_analogic_snapshot(force=False):
    """Última leitura analógica por inversor (Riso/temp/estado/potência), por usina. SWR simples.
    → {plant_id: [{device_id, active_power, temperature_internal, resistance_insulation,
                   state_operation, state_simplified, string_voltage, ts}]}."""
    if not force and _pg_analog["data"] and (time.time() - _pg_analog["ts"]) < PG_ANALOG_TTL:
        return _pg_analog["data"]
    with _pg_analog_lock:
        if not force and _pg_analog["data"] and (time.time() - _pg_analog["ts"]) < PG_ANALOG_TTL:
            return _pg_analog["data"]
        conn = _pg_conn(); cur = conn.cursor()
        cur.execute("""
          WITH latest AS (
            SELECT DISTINCT ON (power_plant_id, device_id)
                   power_plant_id, device_id, active_power, temperature_internal,
                   resistance_insulation, state_operation, state_simplified, string_voltage, timestamp
            FROM dbt.stg_inverter_analogic_data
            WHERE timestamp > now() - interval '6 hours'
            ORDER BY power_plant_id, device_id, timestamp DESC)
          SELECT * FROM latest;""")
        out = {}
        for pid, dev, p, t, riso, sop, ssimp, sv, ts in cur.fetchall():
            out.setdefault(pid, []).append({
                "device_id": dev,
                "active_power": float(p) if p is not None else None,
                "temperature_internal": float(t) if t is not None else None,
                "resistance_insulation": float(riso) if riso is not None else None,
                "state_operation": sop, "state_simplified": ssimp,
                "string_voltage": float(sv) if sv is not None else None,
                "ts": ts.strftime("%Y-%m-%d %H:%M") if ts else None})
        conn.close()
        _pg_analog["data"] = out; _pg_analog["ts"] = time.time()
        return out


def _diag(regra, causa, escopo, confianca, severidade, classificacao, acao, evidencia):
    return {"regra": regra, "nivel": "inversor", "escopo": escopo, "causa": causa,
            "confianca": confianca, "severidade": severidade, "classificacao": classificacao,
            "acao": acao, "evidencia": evidencia if isinstance(evidencia, list) else [evidencia]}


def _diagnosticar_inversores(invs, nomes=None):
    """Regras peer-relativas sobre os inversores de UMA usina. Só roda se a usina está gerando
    (mediana de potência dos pares > 0) e há pares suficientes — senão não dá p/ comparar."""
    nomes = nomes or {}
    diags = []
    pots = [i["active_power"] for i in invs if isinstance(i.get("active_power"), (int, float))]
    if len(pots) < DIAG_MIN_PEERS:
        return diags
    med_pot = _median(pots)
    if not med_pot or med_pot < 2:            # planta parada/noite → sem base de comparação
        return diags
    med_temp = _median([i["temperature_internal"] for i in invs
                        if isinstance(i.get("temperature_internal"), (int, float)) and i["temperature_internal"] > 0])
    med_riso = _median([i["resistance_insulation"] for i in invs
                        if isinstance(i.get("resistance_insulation"), (int, float)) and i["resistance_insulation"] > 0])
    for i in invs:
        dev = i.get("device_id")
        nome = nomes.get(dev) or f"INV {dev}"
        p, t, riso = i.get("active_power"), i.get("temperature_internal"), i.get("resistance_insulation")
        if not isinstance(p, (int, float)):
            continue
        if p < med_pot * DIAG_TRIP_FRAC:                                   # R-07 trip
            diags.append(_diag("R-07", "Inversor parado / trip", nome, "alta", "critico", "controlavel",
                "Resetar/inspecionar o inversor; investigar a causa do trip (sobretensão DC, ground fault, AC).",
                [f"Potência {p:.1f} kW ≈ 0 com os pares gerando (mediana {med_pot:.0f} kW)."]))
            continue
        if med_temp and isinstance(t, (int, float)) and t > med_temp + DIAG_TEMP_MARGIN and p < med_pot * 0.9:  # R-06
            diags.append(_diag("R-06", "Derate térmico (suspeita)", nome, "media", "atencao", "controlavel",
                "Verificar ventilação / limpeza de filtros / obstrução de dutos do inversor.",
                [f"Temp {t:.0f}°C acima dos pares (mediana {med_temp:.0f}°C) com potência abaixo."]))
            continue
        if med_riso and isinstance(riso, (int, float)) and riso < med_riso * DIAG_RISO_FRAC:   # R-08 isolação
            diags.append(_diag("R-08", "Isolação possivelmente baixa (verificar)", nome, "baixa", "atencao", "protecao_ativo",
                "Confiança baixa até confirmar a unidade do Riso; se confirmar, inspeção de aterramento/umidade.",
                [f"Resistência de isolação {riso:g} abaixo dos pares (mediana {med_riso:g}) — calibrar antes de afirmar."]))
            continue
        if med_pot >= 10 and p < med_pot * DIAG_SUBPERF_FRAC:            # R-09 subperformance
            diags.append(_diag("R-09", "Subperformance de inversor", nome, "media", "atencao", "controlavel",
                "Abrir inspeção: strings/MPPT/fusíveis internos (cruzar com a régua de strings).",
                [f"Potência {p:.0f} kW abaixo dos pares (mediana {med_pot:.0f} kW), sem temp alta nem trip."]))
    return diags


def _macro_diags():
    """Diagnóstico por usina canônica p/ enriquecer o portfólio — BARATO e SEGURO: só usa os
    snapshots já cacheados (analógica PG SWR 180s + detalhe PG), zero fetch novo (não toca o
    Plataforma). Peer-relativo. Degradação graciosa: usina sem analógica simplesmente não entra.
    → {_nrm('Usina'): {regra,causa,confianca,severidade,acao,escopo,n}} com o PIOR inversor + total."""
    out = {}
    try:
        snap = _pg_analogic_snapshot()
        rows, detail = _pg_get_snapshot(False)
    except Exception:
        return out
    pid_nome = {r.get("plant_id"): _macro_usina_nome(r.get("usina")) for r in rows}
    SEV = {"critico": 0, "atencao": 1, "informativo": 2}
    CONF = {"alta": 0, "media": 1, "baixa": 2}
    rank = lambda d: (SEV.get(d.get("severidade"), 9), CONF.get(d.get("confianca"), 9))
    for pid, invs in snap.items():
        nome = pid_nome.get(pid)
        if not nome:
            continue
        nomes = {inv.get("id"): inv.get("nome") for inv in detail.get(pid, [])}
        diags = _diagnosticar_inversores(invs, nomes)
        if not diags:
            continue
        diags.sort(key=rank)
        top = diags[0]
        cand = {"regra": top["regra"], "causa": top["causa"], "confianca": top["confianca"],
                "severidade": top["severidade"], "acao": top["acao"], "escopo": top["escopo"],
                "n": len(diags)}
        k = _nrm(nome)
        if k not in out or rank(cand) < rank(out[k]):
            out[k] = cand
    return out


@app.route("/api/diagnostico/<int:plant_id>")
def api_diagnostico(plant_id):
    """Painel 2 — diagnósticos por inversor de uma usina (Thopen, peer-relativo)."""
    try:
        snap = _pg_analogic_snapshot()
    except Exception as e:
        return jsonify({"error": str(e), "diagnosticos": []}), 500
    invs = snap.get(plant_id, [])
    nomes = {}
    try:
        _, detail = _pg_get_snapshot(False)
        for inv in detail.get(plant_id, []):
            nomes[inv["id"]] = inv.get("nome")
    except Exception:
        pass
    diags = _diagnosticar_inversores(invs, nomes)
    return jsonify({"plant_id": plant_id, "n_inversores": len(invs),
                    "tem_analogica": bool(invs), "diagnosticos": diags,
                    "cache_ts": datetime.now().strftime("%H:%M:%S")})


# ── R-10 (tracker travado correlacionado) — lado API PV, via BD_Trackers ────────
# Cruza: trackers em desvio/parado (PV Plataforma) → nº → inversor (BD_Trackers, coluna "Inversor"
# = nome display do inversor na API PV) → o inversor está subperformando? Se sim, alta confiança:
# o tracker travado é a causa. Senão, sinaliza o tracker (média) antes que afete a geração.
def _diagnostico_pv(idusina, nome_raw, nome_disp):
    """Diagnóstico da usina (lado API PV) p/ o analista — foco: subperformance de strings e
    CORRELAÇÃO tracker↔inversor. Regras: R-10 (tracker travado afetando o inversor, via BD_Trackers)
    e R-09 (inversor abaixo dos pares por strings, sem tracker explicando). Peer-relativo + guarda
    de geração (não diagnostica à noite/anoitecer). → {diagnosticos, correlacoes, resumo}."""
    vazio = {"diagnosticos": [], "correlacoes": [], "trackers_por_inversor": {},
             "resumo": {"strings_abaixo": 0, "inversores_abaixo": 0, "trackers_parados": 0, "correlacoes": 0}}
    try:
        invs = _pv_plant_inversores(idusina)
    except Exception:
        return vazio
    if not invs:
        return vazio
    strings_abaixo = sum(1 for i in invs for s in (i.get("strings") or [])
                         if s.get("status") in ("sem_corrente", "baixa_perf"))
    # trackers travados → inversor (BD_Trackers, casado por nome-base + coluna "Inversor")
    bdm = BD_TRK_INV.get(_nome_base(nome_raw)) or {}
    inv_trk_map = INV_TRK.get(_nome_base(nome_raw)) or {}
    travados, trk_parados, trk_list, trk_semcom = {}, 0, [], False
    try:
        _ta = _pv_trackers_analise(idusina, nome_disp)
        trk_list = _ta.get("trackers") or []
        trk_semcom = bool(_ta.get("sem_comunicacao"))
        for t in trk_list:
            stt = t.get("status")
            if stt in ("parado", "desvio", "atraso"):
                if stt == "parado":
                    trk_parados += 1
                inv = _bd_trk_lookup(nome_raw, _pv_trk_num(t.get("id")))
                if inv:
                    travados.setdefault(_nrm(inv), []).append(_pv_trk_num(t.get("id")))
    except Exception:
        pass
    # cards de trackers por inversor (no drill): nº do tracker → status atual, via INV_TRK (nome-base + "Inversor").
    # A planilha pode numerar o complexo em sequência (global) → converte p/ o nº LOCAL da fonte via offset.
    trk_by_num = {_pv_trk_num(t.get("id")): t for t in trk_list}
    _off = _bd_trk_offset(bdm)
    trackers_por_inversor = {}
    for i in invs:
        nums = inv_trk_map.get(_nrm(i.get("nome") or ""))
        if not nums:
            continue
        cards = []
        for n in sorted(set(nums)):
            t = trk_by_num.get(n - _off) or trk_by_num.get(n)
            atual = t.get("atual") if t else None
            if t is None:
                stt = "sem_dado"
            elif atual is None or trk_semcom:
                stt = "sem_comunicacao"
            else:
                stt = t.get("status") or "normal"
            cards.append({"tracker": (t.get("id") if t else f"TRK{n}"), "num": n, "status": stt,
                          "disparidade": (t.get("disparidade") if t else None), "atual": atual,
                          "alvo": (t.get("alvo") if t else None),
                          "na_planilha": bool(t.get("na_planilha")) if t else False,
                          "ticket_status": (t.get("ticket_status") if t else None)})
        if cards:
            trackers_por_inversor[i.get("nome")] = cards
    # peer baseline + guarda de geração (mediana de strings ativas dos pares que estão lendo)
    ativas = [i.get("strings_ativas") for i in invs
              if isinstance(i.get("strings_ativas"), (int, float)) and not i.get("desligado")]
    med = sorted(ativas)[len(ativas) // 2] if ativas else 0
    gerando = len(ativas) >= 3 and med >= 3
    diags, correl, inv_abaixo = [], [], 0
    if gerando:
        for i in invs:
            nrm_inv = _nrm(i.get("nome") or "")
            sa = 0 if i.get("desligado") else i.get("strings_ativas")
            if not (i.get("desligado") or (isinstance(sa, (int, float)) and sa < med * 0.5)):
                continue                          # inversor não está abaixo dos pares
            inv_abaixo += 1
            nums = travados.get(nrm_inv)
            esp = i.get("str_esp")
            faltando = (esp - sa) if isinstance(esp, (int, float)) else None
            if nums:                              # R-10: tracker travado é a causa
                nums_txt = ", ".join(str(n) for n in sorted(set(nums)))
                diags.append(_diag("R-10", "Tracker travado afetando o inversor", i.get("nome") or nrm_inv,
                    "alta", "atencao", "controlavel",
                    f"Reset/inspeção do(s) tracker(s) {nums_txt}.",
                    [f"Tracker(s) {nums_txt} em desvio/parado e o inversor com {sa} strings ativas "
                     f"vs mediana {med} dos pares."]))
                correl.append({"inversor": i.get("nome") or nrm_inv, "trackers": sorted(set(nums)),
                               "strings_perdidas": faltando})
            else:                                 # R-09: subperf sem tracker → string/MPPT/combiner
                diags.append(_diag("R-09", "Subperformance de inversor", i.get("nome") or nrm_inv,
                    "media", "atencao", "controlavel",
                    "Abrir inspeção: strings / MPPT / fusíveis / conectores (combiner).",
                    [f"Inversor com {sa} strings ativas vs mediana {med} dos pares, sem tracker travado associado."]))
    return {"diagnosticos": diags, "correlacoes": correl, "trackers_por_inversor": trackers_por_inversor,
            "resumo": {"strings_abaixo": strings_abaixo, "inversores_abaixo": inv_abaixo,
                       "trackers_parados": trk_parados, "correlacoes": len(correl)}}


@app.route("/api/diagnostico/pv/<int:idusina>")
def api_diagnostico_pv(idusina):
    """Painel 2 (piloto) — diagnóstico da usina no lado API PV: strings + correlação tracker↔inversor."""
    raw = str(idusina)
    try:
        raw = next((p["nome"] for p in get_plants(get_token()) if p["id"] == idusina), str(idusina))
    except Exception:
        pass
    disp = nome_usina(idusina, raw)
    res = _diagnostico_pv(idusina, raw, disp)
    res.update({"idusina": idusina, "usina": disp,
                "cobertura_bd_trackers": _nome_base(raw) in BD_TRK_USINAS,
                "cache_ts": datetime.now().strftime("%H:%M:%S")})
    return jsonify(res)


# ── Correlação tracker × inversor (card "Correlação" do drill do Painel NOC) ────
# Devolve a curva de PRODUÇÃO do inversor associado ao tracker p/ sobrepor ao ângulo:
# de-para da aba BD_Trackers quando existir; sem de-para → inversor de PIOR performance
# do dia (pedido do Levi, 02/07). TODAS as fontes do drill (02/07 à noite): produção =
# corrente média por string (A) — PV day_inverter, SunOp I_PV, 2C hist 5min — e no PG a
# potência ativa (kW) da analógica; sempre na grade STR_EV, comparável com a mediana dos pares.
_corr_pv_cache = {}   # pid -> {ts, series, xs}


def _corr_xs():
    ncells = (STR_EV_WIN_FIM - STR_EV_WIN_INI) // STR_EV_STEP + 1
    return [_str_hhmm(STR_EV_WIN_INI + i * STR_EV_STEP) for i in range(ncells)]


def _corr_mean_grid(strings_por_inv):
    """{inv: {sid: [(ts|hhmm, v)]}} → {inv: [média das séries por célula]} na grade STR_EV.
    Com 1 série por inversor (potência do PG) a média é o próprio valor."""
    ncells = (STR_EV_WIN_FIM - STR_EV_WIN_INI) // STR_EV_STEP + 1
    series = {}
    for inv, strings in strings_por_inv.items():
        grids = _str_grades(strings, ncells)
        med = []
        for i in range(ncells):
            vals = [g[i] for g in grids.values() if g[i] is not None]
            med.append(round(sum(vals) / len(vals), 2) if vals else None)
        series[inv] = med
    return series


def _pv_series_inversores(pid, nome_raw, token, force=False):
    """→ ({inversor_display: [corrente média/string por célula]}, labels_x). Grade STR_EV (06–18h/10min)."""
    ent = _corr_pv_cache.get(pid)
    if ent and not force and (time.time() - ent["ts"]) < CACHE_TTL:
        return ent["series"], ent["xs"]
    series = _corr_mean_grid(_pv_curvas_strings(pid, nome_raw, token))
    xs = _corr_xs()
    _corr_pv_cache[pid] = {"ts": time.time(), "series": series, "xs": xs}
    return series, xs


def _pg_series_inversores(pid):
    """→ (series {inv_display: [kW por célula]}, nome_raw sup da usina). Série do DIA da analógica."""
    hoje = datetime.now().strftime("%Y-%m-%d")
    strings_por_inv, sup = {}, ""
    try:
        conn = _pg_conn(); cur = conn.cursor()
        cur.execute("""
            SELECT d.device_name, s.timestamp, s.active_power, p.name
            FROM dbt.stg_inverter_analogic_data s
            JOIN public.tb_devices d ON d.id = s.device_id
            LEFT JOIN public.tb_power_plants p ON p.id = s.power_plant_id
            WHERE s.power_plant_id = %(pid)s AND s.timestamp::date = %(dia)s
            ORDER BY s.timestamp
        """, {"pid": pid, "dia": hoje})
        linhas = cur.fetchall()
        conn.close()
    except Exception as e:
        print(f"[correlacao PG] erro: {e}")
        return {}, ""
    for dname, ts, pot, pname in linhas:
        sup = (pname or "").strip() or sup
        inv_disp = (EQUIP_NAMES.get(sup, {}) or {}).get((dname or "").strip(), (dname or "").strip())
        strings_por_inv.setdefault(inv_disp, {}).setdefault("P", []).append(
            (ts, float(pot) if pot is not None else None))
    return _corr_mean_grid(strings_por_inv), sup


def _sunop_series_inversores(plant_name, inst):
    pay = _sunop_strings_curva(plant_name, datetime.now().strftime("%Y-%m-%d"), None, inst)
    strings_por_inv = {iv["nome"]: {st: list(zip(c["x"], c["y"])) for st, c in (iv.get("curva") or {}).items()}
                       for iv in (pay.get("inversores") or [])}
    return _corr_mean_grid(strings_por_inv)


def _owen_series_inversores(u):
    data = _hist_build(datetime.now().strftime("%Y-%m-%d")).get("strings", {}).get(u, {})
    strings_por_inv = {inv: {sid: serie for sid, serie in strs.items()
                             if _str_key(u, inv, sid) not in _trancadas}
                      for inv, strs in data.items()}
    return _corr_mean_grid(strings_por_inv)


_corr_series_cache = {}   # (fonte, str(id)) -> {ts, series, nome_raw} — pg/sunop/axis/owen (pv tem o dele)


@app.route("/api/painel/correlacao/<fonte>/<idusina>")
def api_painel_correlacao(fonte, idusina):
    trk_id = (flask_request.args.get("tracker") or "").strip()
    unidade = "A/string"
    if fonte == "pv":
        try:
            pid = int(idusina)
        except ValueError:
            return jsonify({"erro": "id inválido"}), 400
        token = get_token()
        nome_raw = str(pid)
        try:
            nome_raw = next((p["nome"].strip() for p in get_plants(token) if p["id"] == pid), nome_raw)
        except Exception:
            pass
        series, xs = _pv_series_inversores(pid, nome_raw, token)
    elif fonte in ("pg", "sunop", "axis", "owen"):
        xs = _corr_xs()
        ck = (fonte, str(idusina))
        ent = _corr_series_cache.get(ck)
        if ent and (time.time() - ent["ts"]) < CACHE_TTL:
            series, nome_raw = ent["series"], ent["nome_raw"]
        else:
            if fonte == "pg":
                series, nome_raw = _pg_series_inversores(idusina)   # potência ativa (kW)
            elif fonte == "owen":
                series, nome_raw = _owen_series_inversores(idusina), _owen_nome(idusina)
            else:
                inst = "axis" if fonte == "axis" else "gridco"
                series, nome_raw = _sunop_series_inversores(idusina, inst), idusina
            _corr_series_cache[ck] = {"ts": time.time(), "series": series, "nome_raw": nome_raw}
        if fonte == "pg":
            unidade = "kW"
    else:
        return jsonify({"erro": "fonte sem correlação"}), 404
    if not series:
        return jsonify({"erro": "sem curva de inversores hoje"}), 404

    def _media_dia(s):
        vals = [v for v in s if v is not None]
        return (sum(vals) / len(vals)) if vals else None

    num = _pv_trk_num(trk_id) if trk_id else None
    alvo, metodo = None, None
    inv_bd = _bd_trk_lookup(nome_raw, num)
    if inv_bd:
        want = _nrm(inv_bd)
        alvo = next((inv for inv in series if _nrm(inv) == want), None)
        if alvo is not None:
            metodo = "bd_trackers"
    if alvo is None:                        # sem de-para → inversor de PIOR performance do dia
        rank = [(inv, m) for inv, m in ((inv, _media_dia(s)) for inv, s in series.items()) if m is not None]
        if not rank:
            return jsonify({"erro": "sem leitura válida de inversores hoje"}), 404
        alvo = min(rank, key=lambda t: t[1])[0]
        metodo = "pior_inversor"
    pares = []
    for i in range(len(xs)):
        vals = sorted(s[i] for inv, s in series.items() if inv != alvo and s[i] is not None)
        pares.append(vals[len(vals) // 2] if vals else None)
    return jsonify({"tracker": trk_id, "tracker_num": num, "inversor": alvo, "metodo": metodo,
                    "cobertura_bd": _nome_base(nome_raw) in BD_TRK_USINAS, "unidade": unidade,
                    "curva": {"x": xs, "y": series[alvo]}, "pares": {"x": xs, "y": pares},
                    "cache_ts": datetime.now().strftime("%H:%M:%S")})


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
    _dia = 7 <= datetime.now().hour < 18
    for inv in invs:
        keys = [s["id"] for s in inv["strings"]]
        st   = _classifica_strings(plant_id, inv["id"], keys,
                                   [s["corrente"] for s in inv["strings"]])
        for s, stt in zip(inv["strings"], st):
            s["status"]   = stt
            s["ativa"]    = stt in ("ativa", "baixa_perf")
            s["trancada"] = stt == "trancada"
        inv["strings_ativas"] = _str_ativas(st)
        # inversor PARADO (potência ~0, do snapshot) de dia → strings "inativa" viram "desligado"
        # (vermelho-escuro): não faz sentido inversor desligado com string 0A pintada verde "OK".
        _off = (inv.get("produzindo") is False) if inv.get("produzindo") is not None else (inv["strings_ativas"] == 0)
        if _off and _dia:
            inv["desligado"] = True
            for s in inv["strings"]:      # inversor OFF: linha inteira = desligado (corrente reversa residual ≠ produção)
                if s["status"] != "trancada":
                    s["status"] = "desligado"; s["ativa"] = False
        if inv.get("str_esp") is not None:
            inv["diferenca"] = inv["strings_ativas"] - inv["str_esp"]
    return jsonify({"plant_id": plant_id, "inversores": invs})


# ── PG: curva diária de corrente por string (botão "Curva do dia" do drill-down) ─
#   Mesma FORMA do SPV (API PV) p/ reusar o plot do frontend (_spvPlotInto):
#   por inversor → curva {ST_xx: {x,y}}, mediana da corrente integrada do dia e
#   strings em subperformance (< SPV_SUB_FRAC da mediana). Fonte = stg_inverter_string_data.
_pg_str_med_cache = {}   # (plant_id, dia) -> {"ts","med"} — mediana das strings da USINA inteira (PG)


def _pg_str_med_usina(plant_id: int, dia: str) -> float:
    """Mediana da energia (∫corrente no dia) de TODAS as strings da usina (todos os inversores) no PG.
    Referência cross-inversor p/ pegar inversor inteiro em baixa — ver _sunop_str_med_usina."""
    key = (plant_id, dia)
    ent = _pg_str_med_cache.get(key)
    if ent and (time.time() - ent["ts"]) < CACHE_TTL:
        return ent["med"]
    med = 0.0
    try:
        conn = _pg_conn(); cur = conn.cursor()
        cur.execute("""
            SELECT s.device_id, s.string_number, SUM(GREATEST(s.string_current, 0)) AS soma
            FROM dbt.stg_inverter_string_data s
            WHERE s.power_plant_id = %(pid)s AND s.timestamp::date = %(dia)s
            GROUP BY s.device_id, s.string_number
        """, {"pid": plant_id, "dia": dia})
        somas = []
        for dev_id, snum, soma in cur.fetchall():
            if _str_key(plant_id, dev_id, str(snum)) in _trancadas:
                continue
            somas.append(float(soma) if soma is not None else 0.0)
        conn.close()
        somas.sort()
        med = somas[len(somas) // 2] if somas else 0.0
    except Exception:
        med = 0.0
    _pg_str_med_cache[key] = {"ts": time.time(), "med": med}
    return med


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

    med_usina = _pg_str_med_usina(plant_id, dia)   # referência da USINA (não do inversor)
    out = []
    for dev_id in sorted(invs):
        inv = invs[dev_id]
        soma, curva = {}, {}
        for snum, serie in inv["strings"].items():
            # string trancada (🔒) sai da curva — chave igual à da tabela: pid | dev_id | snum
            if _str_key(plant_id, dev_id, snum) in _trancadas:
                continue
            serie.sort(key=lambda x: x[0])
            lbl = f"ST {int(snum):02d}" if snum.isdigit() else f"ST {snum}"
            soma[lbl] = sum(max(0.0, v) for _, v in serie)
            step = max(1, len(serie) // 160)
            sp   = serie[::step]
            curva[lbl] = {"x": [t.strftime("%H:%M") for t, _ in sp],
                          "y": [round(v, 2) for _, v in sp]}
        vals = sorted(soma.values())
        med  = vals[len(vals) // 2] if vals else 0.0
        ref  = med_usina if med_usina > 0 else med   # compara com a USINA inteira
        strings, abaixo = [], 0
        for lbl in sorted(soma, key=_spv_stnum):
            e   = soma[lbl]
            sub = (ref > 0 and e < ref * SPV_SUB_FRAC)
            abaixo += 1 if sub else 0
            strings.append({"nome": lbl, "ativa": e > 0, "sub": sub,
                            "energia": round(e, 1), "pct": round(100.0 * e / ref) if ref else None})
        out.append({"id": dev_id,
                    "nome": (EQUIP_NAMES.get(sup, {}) or {}).get(inv["nome_api"], inv["nome_api"]),
                    "nome_api": inv["nome_api"], "curva": curva,
                    "mediana": round(med, 1), "mediana_usina": round(med_usina, 1),
                    "abaixo": abaixo, "strings": strings})
    _marca_inv_sub(out)
    return {"plant_id": plant_id, "data": dia, "inversores": out,
            "mediana_usina": round(med_usina, 1)}


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
    date = (flask_request.args.get("date") or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        sql = """
          SELECT timestamp, irradiance_poa, irradiance_ghi
          FROM dbt.stg_weather_station_analogic_data
          WHERE power_plant_id = %s AND timestamp::date = %s
          ORDER BY timestamp;
        """
        params = (plant_id, date)
    else:
        sql = """
          SELECT timestamp, irradiance_poa, irradiance_ghi
          FROM dbt.stg_weather_station_analogic_data
          WHERE power_plant_id = %s AND timestamp::date = CURRENT_DATE
          ORDER BY timestamp;
        """
        params = (plant_id,)
    try:
        conn = _pg_conn(); cur = conn.cursor(); cur.execute(sql, params)
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
    d.setdefault("comments", {})          # {chave: texto} (legado, 1 comentário sobrescrito)
    d.setdefault("comments_thread", {})   # {chave: [{nick, texto, ts}]} (thread multi-analista)
    d.setdefault("tracking", {})   # {chave: int}  → strings em acompanhamento
    d.setdefault("manutencao", [])  # lista de chaves de ETM em manutenção (ex.: "etm:pv:22854")
    d.setdefault("strings_trancadas", [])  # chaves "plant_id|inv_id|Ipv" de strings trancadas (MPPT sem string)
    d.setdefault("etm_tickets", {})   # {usina_nrm: {usina, comentario, feito, ts}} — visão ETM da Frota
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
    trancada = bool(body.get("trancada"))
    # Aceita uma string (compat) OU uma lista 'strings' (trancar/destrancar em lote,
    # ex.: o botão "Trancar strings inativas" do inversor).
    raw      = body.get("strings")
    nomes    = ([str(x).strip() for x in raw if str(x).strip()] if isinstance(raw, list)
                else [str(body.get("string", "")).strip()])
    nomes    = [n for n in nomes if n]
    if not (plant_id and inv_id and nomes):
        return jsonify({"error": "plant_id, inv_id e string(s) obrigatórios"}), 400
    with _state_lock:
        d = _load_state()
        s = set(d.get("strings_trancadas", []))
        for nm in nomes:
            key = f"{plant_id}|{inv_id}|{nm}"
            s.add(key) if trancada else s.discard(key)
        d["strings_trancadas"] = sorted(s)
        _save_state(d)
        _trancadas = s
    # As curvas de strings excluem as trancadas → invalida os caches da usina afetada
    # (API PV e SunOp) p/ a próxima abertura do gráfico recomputar já sem a string.
    # O ck[0] é o id da usina em ambos (idusina / plant_name) = o plant_id do POST.
    # PG não tem cache de curva (recomputa do banco a cada chamada).
    for ck in [ck for ck in _spv_cache if str(ck[0]) == plant_id]:
        _spv_cache.pop(ck, None)
    for ck in [ck for ck in _sunop_curva_cache if str(ck[0]) == plant_id]:
        _sunop_curva_cache.pop(ck, None)
    # As sub-abas OCORRÊNCIAS e SEM-CORRENTE também excluem as trancadas, mas SERVEM DE CACHE (rows já
    # calculadas). Sem invalidar, a string recém-trancada segue aparecendo até o TTL (5min hoje;
    # PERMANENTE em dia passado da API PV). Levi 08/07: "trancada não pode aparecer nas 2 abas". (PG e
    # 2C reaplicam a régua na LEITURA → não precisam.)
    _str_prob_pv_cache["rows"] = None                    # sem-corrente API PV
    _pv_str_ev_cache.clear()                             # ocorrências API PV (todas as datas)
    _sunop_str_ev_cache.clear()                          # ocorrências SunOp/Axis
    for _c in (_sunop_str_med_cache, _pg_str_med_cache, _axis_str_med_cache):
        for _ck in [c for c in _c if str(c[0]) == plant_id]:
            _c.pop(_ck, None)
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


@app.route("/api/state/comment/add", methods=["POST"])
def api_state_comment_add():
    """Adiciona um comentário de analista (thread multi-usuário) numa usina. Sem login por pessoa
    (o dashboard é 1 senha compartilhada) → o 'nick' é auto-declarado (confiança da equipe)."""
    body  = flask_request.get_json(force=True, silent=True) or {}
    key   = str(body.get("key", "")).strip()
    nick  = str(body.get("nick", "")).strip()[:40]
    texto = str(body.get("texto", "")).strip()[:2000]
    if not key or not nick or not texto:
        return jsonify({"error": "key, nick e texto obrigatórios"}), 400
    with _state_lock:
        d = _load_state()
        item = {"nick": nick, "texto": texto, "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")}
        d["comments_thread"].setdefault(key, []).append(item)
        _save_state(d)
        thread = d["comments_thread"][key]
    return jsonify({"ok": True, "thread": thread})


@app.route("/api/state/comment/del", methods=["POST"])
def api_state_comment_del():
    """Remove um comentário da thread pelo timestamp (sem login → confiança da equipe)."""
    body = flask_request.get_json(force=True, silent=True) or {}
    key  = str(body.get("key", "")).strip()
    ts   = str(body.get("ts", "")).strip()
    with _state_lock:
        d = _load_state()
        lst = d.get("comments_thread", {}).get(key, [])
        d.setdefault("comments_thread", {})[key] = [c for c in lst if c.get("ts") != ts]
        _save_state(d)
        thread = d["comments_thread"][key]
    return jsonify({"ok": True, "thread": thread})


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
        # Dia de REFERÊNCIA = o mais recente presente nas pastas flat (não "hoje" fixo). Early morning,
        # antes da coleta das 9:10, as flat ainda têm ONTEM → mostra ontem + última leitura em vez de
        # "Sem dados". Após a coleta de hoje (que limpa as flat), vira hoje sozinho.
        _datas = {t.strftime("%Y-%m-%d") for _p, t, _v in _owen_rows("ETM")}
        if not _datas:
            _datas = {t.strftime("%Y-%m-%d") for _p, t, _v in _owen_rows("Strings")}
        data_ref = max(_datas) if _datas else hoje
        if _owen_accum.get("date") != data_ref:           # mudou o dia de referência → zera
            _owen_accum.update({"date": data_ref, "etm": {}, "strings": {}, "trackers": {}})
        else:
            _owen_prune_today(data_ref)                    # limpa sobras de outros dias
        rxs = re.compile(r"_Inv_([\d.]+)_STR_Corrente PV(\d+)")
        rxt = re.compile(r"_TRK_([\d.]+)_MED_(.+?) \(graus\)")
        # ETM
        for pn, t, v in _owen_rows("ETM"):
            if t.strftime("%Y-%m-%d") != data_ref:        # só do dia de referência
                continue
            u = pn.split("_", 1)[0]
            if u not in OWEN_UFVS:
                continue
            med = "ghi" if "GHI" in pn else ("poa" if "POA" in pn else None)
            if med:
                _owen_accum["etm"].setdefault(u, {}).setdefault(med, {})[t.strftime(OWEN_TS_FMT)] = _etm_clamp(v)
        # Strings (mantém o valor mais recente por string)
        for pn, t, v in _owen_rows("Strings"):
            if t.strftime("%Y-%m-%d") != data_ref:
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
            if t.strftime("%Y-%m-%d") != data_ref:
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
def _owen_etm_build(force=False):
    _owen_refresh(force)
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
    data = _owen_etm_build(flask_request.args.get("force") == "1")
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
    date = (flask_request.args.get("date") or "").strip()
    if date and date != datetime.now().strftime("%Y-%m-%d"):
        merged = _owen_etm_series(_hist_build(date).get("etm", {}).get(u, {}))   # dia passado: 2C_historico
    else:
        merged = _owen_etm_series(_owen_etm_build().get(u, {}))                   # hoje: acumulador
    return jsonify({"labels": [t.strftime("%H:%M") for t, _, _ in merged],
                    "poa": [p for _, p, _ in merged],
                    "ghi": [g for _, _, g in merged], "poari": []})


# ── Owen: Strings (corrente por string/inversor, último valor do dia) ──────────
def _owen_strings_build(force=False):
    _owen_refresh(force)
    with _owen_lock:
        out = {}   # ufv → inv → strnum → (datetime, valor)
        for u, invs in _owen_accum.get("strings", {}).items():
            out[u] = {inv: {sn: (datetime.strptime(ts, OWEN_TS_FMT), v) for sn, (ts, v) in strs.items()}
                      for inv, strs in invs.items()}
        return out


def _owen_inv_tag(code, inv):
    return f"{code}_Inv_{inv}"   # nomenclatura supervisório (igual ao que está no BD_Performance)



def _owen_strings_rows(force=False):
    """Linhas por usina do 2C (mesmo formato do rollup/macro). Reusado pelo endpoint e por
    _portfolio_rollup. Lê os arquivos locais do 2C (barato/cacheado), sem rede."""
    data = _owen_strings_build(force)
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
            ids = list(strs.keys()); correntes = [strs[s][1] for s in ids]
            ativas += _str_ativas(_classifica_strings(u, inv, ids, correntes))   # desconta trancadas
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
    return rows


# ══ Strings SEM CORRENTE (agora) — espelho de "Trackers parados (agora)" ═════════════════════════
#   Régua do Levi (02/07): SÓ string sem corrente. Fontes com CURVA (API PV) usam a janela correta —
#   da 1ª string do inversor que INICIA até a última ZERAR; zerada a janela toda = sem corrente
#   (quem caiu no meio é OCORRÊNCIA). PG (snapshot 1 ts/dia) e 2C (só última leitura no acumulador)
#   ficam na régua instantânea: ≤0.1 A com o inversor produzindo.
_STR_PROB   = ("sem_corrente",)
_STR_LABEL  = {"sem_corrente": "sem corrente"}
_str_prob_pv_cache = {"ts": 0.0, "rows": None}


def _strings_problema_rows(fonte, force=False):
    """→ [{plant_id, usina, inversor, string, corrente, status, status_label, desde?}] geo-anotado.
    PG/2C são baratos (uma leitura); API PV busca a CURVA do dia só das usinas com déficit."""
    rows = []

    def _add(usina, pid, inv, sid, corrente, st):
        if st in _STR_PROB:
            rows.append({"plant_id": pid, "usina": usina, "inversor": inv or "",
                         "string": str(sid), "corrente": corrente,
                         "status": st, "status_label": _STR_LABEL.get(st, st)})

    if fonte == "pg":
        summary, detail = _pg_get_snapshot(force)
        nome_by = {str(r["plant_id"]): r["usina"] for r in summary}
        for pid, invs in detail.items():
            usina = _macro_usina_nome(nome_by.get(str(pid), "")) or nome_by.get(str(pid), str(pid))
            for inv in invs:
                for s in inv.get("strings", []):
                    _add(usina, pid, inv.get("nome"), s.get("id"), s.get("corrente"), s.get("status"))
    elif fonte == "pv":
        ent = _str_prob_pv_cache
        if ent["rows"] is not None and not force and (time.time() - ent["ts"]) < CACHE_TTL:
            rows = [dict(r) for r in ent["rows"]]
        else:
            token = get_token()
            try:
                pid2api = {p["id"]: p["nome"].strip() for p in get_plants(token)}
            except Exception:
                pid2api = {}
            ov = (_cache.get("payload") or {}).get("rows", [])
            alvo = [r for r in ov if not r.get("sem_dados") and not r.get("stringbox")
                    and isinstance(r.get("diferenca"), (int, float)) and r["diferenca"] < 0]
            sbox = [r for r in ov if r.get("stringbox") and not r.get("sem_dados")]

            def _um(r):
                pid = r["plant_id"]
                curvas = _pv_curvas_strings(pid, pid2api.get(pid, r["usina"]), token)
                mortas = _str_mortas_calc(_macro_usina_nome(r["usina"]) or r["usina"], curvas)
                for m in mortas:
                    m["plant_id"] = pid
                return mortas

            def _um_sbox(r):
                # String Box: sem curva por string → régua INSTANTÂNEA da combiner (como o PG)
                usina = _macro_usina_nome(r["usina"]) or r["usina"]
                out = []
                for inv in _pv_plant_inversores(r["plant_id"]):
                    if not inv.get("combiner") or inv.get("desligado"):
                        continue
                    for s in inv.get("strings", []):
                        if s.get("status") == "sem_corrente":
                            out.append({"plant_id": r["plant_id"], "usina": usina,
                                        "inversor": inv.get("nome") or "", "string": str(s.get("id")),
                                        "corrente": s.get("corrente"), "status": "sem_corrente",
                                        "status_label": "sem corrente"})
                return out

            with ThreadPoolExecutor(max_workers=6) as ex:
                futs = [ex.submit(_um, r) for r in alvo] + [ex.submit(_um_sbox, r) for r in sbox]
                for f in as_completed(futs):
                    try:
                        rows.extend(f.result())
                    except Exception:
                        pass
            ent["rows"] = [dict(r) for r in rows]
            ent["ts"] = time.time()
    elif fonte == "owen":
        data = _owen_strings_build(force)
        for u, invs in data.items():
            usina = _macro_usina_nome(_owen_nome(u)) or _owen_nome(u)
            for inv, strs in invs.items():
                ids = list(strs.keys()); correntes = [strs[k][1] for k in ids]
                stt = _classifica_strings(u, inv, ids, correntes)
                for k, c, s in zip(ids, correntes, stt):
                    _add(usina, u, inv, k, c, s)
    elif fonte in ("sunop", "axis"):
        # Athon/Axis não têm snapshot instantâneo por string → derivamos das OCORRÊNCIAS de HOJE:
        # ocorrência ABERTA (caiu e "não voltou" até o fim de geração) = string zerada AGORA com o
        # inversor produzindo = sem corrente atual. Compartilha o cache do eventos (não recalcula 2×).
        inst = "axis" if fonte == "axis" else "gridco"
        hoje = datetime.now().strftime("%Y-%m-%d")
        for e in _sunop_strings_eventos(hoje, inst, force):
            if e.get("voltou") or not e.get("gerando_agora"):
                continue        # já voltou, ou o inversor está SEM geração agora (parado) → ignora
            rows.append({"plant_id": e.get("plant_id"), "usina": e.get("usina"),
                         "inversor": e.get("inversor") or "", "string": str(e.get("string")),
                         "corrente": 0.0, "status": "sem_corrente",
                         "status_label": _STR_LABEL["sem_corrente"], "desde": e.get("caiu")})
    rows.sort(key=lambda r: (r.get("usina") or "", str(r.get("inversor") or ""),
                             _pv_trk_num(r.get("string") or "0")))
    return _trk_geo_annotate(rows)


@app.route("/api/<fonte>/strings/problema")
def api_strings_problema(fonte):
    if fonte not in ("pv", "pg", "owen", "sunop", "axis"):
        return jsonify({"rows": [], "total": 0, "indisponivel": True,
                        "cache_ts": datetime.now().strftime("%H:%M:%S")})
    rows = _strings_problema_rows(fonte, force=flask_request.args.get("force") == "1")
    return jsonify({"rows": rows, "total": len(rows), "cache_ts": datetime.now().strftime("%H:%M:%S")})


@app.route("/api/<fonte>/strings/problema/export.xlsx")
def api_strings_problema_xlsx(fonte):
    """Strings com problema (agora) em Excel estilizado (mesma cara do export de trackers)."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    if fonte not in ("pv", "pg", "owen", "sunop", "axis"):
        return jsonify({"error": "fonte sem strings por-string"}), 404
    qf = (flask_request.args.get("usina") or "").strip().lower()
    rows = _strings_problema_rows(fonte)
    if qf:
        rows = [r for r in rows if qf in (r.get("usina") or "").lower()]
    label = _TRK_FONTE_LABEL.get(fonte, fonte)
    NAVY = "1A1B2E"
    hdr_fill = PatternFill("solid", fgColor=NAVY); hdr_font = Font(color="FFFFFF", bold=True)
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Strings sem corrente"
    ro = 1
    ws.cell(row=ro, column=1, value=f"Strings sem corrente agora · {label} · {datetime.now().strftime('%d/%m/%Y %H:%M')}").font = Font(bold=True, size=14, color=NAVY)
    ro += 1
    ws.cell(row=ro, column=1, value=f"{len(rows)} string(s) em {len({r.get('usina') for r in rows})} usina(s)").font = Font(color="6B7280")
    ro += 2
    headers = ["Usina", "Inversor", "String", "Corrente (A)", "Desde", "Cliente"]   # espelho da tela
    hr = ro
    for j, h in enumerate(headers, start=1):
        c = ws.cell(row=hr, column=j, value=h); c.fill = hdr_fill; c.font = hdr_font
    ro += 1
    for r in rows:
        cur = r.get("corrente")
        vals = [r.get("usina"), r.get("inversor") or "—", r.get("string"),
                round(float(cur), 2) if isinstance(cur, (int, float)) else "—",
                r.get("desde") or "—", r.get("cliente") or "—"]
        for j, val in enumerate(vals, start=1):
            ws.cell(row=ro, column=j, value=val)
        ws.cell(row=ro, column=4).font = Font(bold=True, color="DC2626")
        ro += 1
    for j, w in enumerate([24, 16, 8, 13, 9, 12], start=1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = ws.cell(row=hr + 1, column=1)
    return _xlsx_resp(wb, f"strings_problema_{fonte}_{datetime.now().strftime('%Y-%m-%d_%H%M')}.xlsx")


# ══ Ocorrências de strings (caiu → voltou) — string que zerou e voltou no dia ════════════════════
#   Espelho de "Ocorrências (travou→voltou)" dos trackers, mas na CORRENTE da string: queda a ~0
#   ENQUANTO o inversor produz (mediana das strings dele > limiar) → caiu; voltou = corrente de volta.
STR_EV_WIN_INI     = 6 * 60     # 06:00
STR_EV_WIN_FIM     = 18 * 60    # 18:00
STR_EV_STEP        = 10         # min
STR_EV_MIN_MIN     = 30         # duração mínima da queda p/ virar ocorrência
STR_EV_INV_MIN_MED = 0.5        # mediana de corrente do inversor acima disto = inversor PRODUZINDO
# DIA PASSADO da API PV: a Plataforma só recupera POTÊNCIA (W) por string (day_inverter/corrente é
# só hoje). Mesma detecção, limiares em W (string desconectada = ~0 W; produzindo = centenas de W).
STR_EV_POT_ZERO_W  = 15.0       # potência (W) <= isto = string ZERADA
STR_EV_POT_INV_MED = 40.0       # piso ABSOLUTO de potência (W) do inversor p/ "produzindo"
STR_EV_POT_INV_FRAC = 0.12      # E >= 12% do PICO do inversor — corta a rampa de pôr-do-sol (mediana
                                # baixa no entardecer = string que zera ali é o fim do dia, não falha)


def _str_min_of(ts):
    try:
        return ts.hour * 60 + ts.minute
    except AttributeError:
        m = re.match(r"(\d{1,2}):(\d{2})", str(ts))
        return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _str_hhmm(mn):
    return f"{mn // 60:02d}:{mn % 60:02d}"


def _str_grades(strings, ncells):
    """{string_id: [(ts|hhmm, A)]} → {string_id: grade de ncells células de STR_EV_STEP min (None = sem leitura)}."""
    grids = {}
    for sid, serie in strings.items():
        g = [None] * ncells
        for ts, c in serie:
            m = _str_min_of(ts)
            if m is None or m < STR_EV_WIN_INI or m > STR_EV_WIN_FIM:
                continue
            i = (m - STR_EV_WIN_INI) // STR_EV_STEP
            if 0 <= i < ncells:
                g[i] = float(c) if c is not None else 0.0
        grids[sid] = g
    return grids


def _str_mortas_calc(usina, curvas_inv):
    """Strings SEM CORRENTE do dia (régua do Levi 02/07): janela do inversor = da 1ª string que
    INICIA até a última string ZERAR; string zerada (≤ STRING_SEM_CORRENTE_A) durante TODA essa
    janela = sem corrente. Fora da janela (madrugada/anoitecer) nada é falha; quem produziu e caiu
    no meio vira OCORRÊNCIA (outra sub-aba). Inversor que nunca produziu não aponta strings (o
    problema é do inversor, já sai no Painel como parado)."""
    ncells = (STR_EV_WIN_FIM - STR_EV_WIN_INI) // STR_EV_STEP + 1
    out = []
    for inv_nome, strings in curvas_inv.items():
        grids = _str_grades(strings, ncells)
        if not grids:
            continue
        vivas = [i for i in range(ncells)
                 if any(g[i] is not None and g[i] > STRING_SEM_CORRENTE_A for g in grids.values())]
        if not vivas:
            continue
        ini, fim = vivas[0], vivas[-1]
        if (fim - ini) * STR_EV_STEP < STR_EV_MIN_MIN:
            continue                                   # janela curta demais p/ afirmar falha
        for sid, g in grids.items():
            jan = [v for v in g[ini:fim + 1] if v is not None]
            if not jan or any(v > STRING_SEM_CORRENTE_A for v in jan):
                continue                               # produziu em algum momento → não é "sem corrente"
            out.append({"usina": usina, "inversor": inv_nome, "string": sid,
                        "corrente": jan[-1], "desde": _str_hhmm(STR_EV_WIN_INI + ini * STR_EV_STEP),
                        "status": "sem_corrente", "status_label": "sem corrente"})
    return out


def _str_eventos_calc(usina, curvas_inv, zero_thr=None, inv_min=None, inv_min_frac=0.0):
    """curvas_inv = {inv_nome: {string_id: [(ts|hhmm, valor)]}} do dia → ocorrências 'caiu→voltou'.
    UNIDADE-AGNÓSTICO: HOJE = corrente (A); DIA PASSADO da API PV = potência (W, via PV Plataforma).
    zero_thr = valor <= é 'zerada'; inv_min = piso ABSOLUTO da mediana p/ 'produzindo'; inv_min_frac =
    fração do PICO do inversor exigida também (0 = só o piso; usado na POTÊNCIA p/ cortar o pôr-do-sol)."""
    zero = STRING_SEM_CORRENTE_A if zero_thr is None else zero_thr
    imin = STR_EV_INV_MIN_MED  if inv_min  is None else inv_min
    ncells = (STR_EV_WIN_FIM - STR_EV_WIN_INI) // STR_EV_STEP + 1
    eventos = []
    for inv_nome, strings in curvas_inv.items():
        grids = _str_grades(strings, ncells)
        if not grids:
            continue
        meds = []                                       # mediana das strings por célula
        for i in range(ncells):
            vals = [g[i] for g in grids.values() if g[i] is not None]
            meds.append(sorted(vals)[len(vals) // 2] if vals else None)
        # "produzindo" = mediana >= piso ABSOLUTO (imin) E >= fração do PICO (inv_min_frac). A fração,
        # usada na POTÊNCIA, exclui a rampa de pôr-do-sol (mediana já baixa vs. o pico do dia).
        peak = max((m for m in meds if m is not None), default=0.0)
        floor = max(imin, peak * inv_min_frac)
        inv_prod = [m is not None and m >= floor for m in meds]
        # WAKE do inversor = 1ª célula em que ele PRODUZ (mediana das strings >= limiar). Régua do Levi
        # (08/07): a partir da PARTIDA do inversor conta-se o tempo de string zerada — inclusive a string
        # que já estava zerada quando ele acordou (antes exigia que ELA tivesse produzido antes, então
        # string caída desde a partida escapava). Espelha o "frota acordou" dos trackers.
        wake = next((i for i in range(ncells) if inv_prod[i]), None)
        if wake is None:
            continue                                    # inversor não produziu no dia → problema do inversor, não das strings
        # FIM DE GERAÇÃO do inversor = última célula em que ALGUMA string dele ainda teve corrente
        # (régua do Levi 08/07: a string que não voltou encerra quando a ÚLTIMA string do inversor
        # para de gerar — não num limiar de mediana, que fechava cedo).
        inv_fim = max((k for k in range(ncells)
                       if any(g[k] is not None and g[k] > zero for g in grids.values())),
                      default=None)
        # INVERSOR GERANDO AGORA (Levi 08/07: "inversor sem geração ignora as strings"). Serve p/ o
        # 'sem corrente ATUAL' descartar strings de inversor parado AGORA — sem tocar nas ocorrências
        # (histórico legítimo). Sinal = SOMA das strings (imune aos canais fantasmas, que somam 0) nas 2
        # últimas leituras vs 10% do próprio pico. O piso alto (10%) rejeita a inflação por RUÍDO de
        # inversor morto (17 strings oscilando ~1A somam ~18A, mas < 10% de um pico de ~250A) e ainda
        # MANTÉM inversor gerando pouco de verdade — na dúvida, mostra (não esconde dado real).
        tot = [sum(g[i] for g in grids.values() if g[i] is not None and g[i] > zero)
               for i in range(ncells)]
        peak_tot = max(tot) if tot else 0.0
        data_cells = [i for i in range(ncells) if any(g[i] is not None for g in grids.values())]
        recent = data_cells[-2:]                          # últimos ~20 min (grade "última leitura vence")
        alive_floor = max(imin, peak_tot * 0.10)
        gerando_agora = bool(recent) and max((tot[i] for i in recent), default=0.0) >= alive_floor
        for sid, g in grids.items():
            if all(v is None for v in g):
                continue                                # sem leitura na janela → não dá p/ afirmar queda
            i = wake
            while i < ncells:
                # início de um trecho ZERADO com o inversor produzindo (conta desde a wake)
                if not (inv_prod[i] and (g[i] is None or g[i] <= zero)):
                    i += 1
                    continue
                start = i
                while i < ncells and (g[i] is None or g[i] <= zero):
                    i += 1
                ret = i if (i < ncells and g[i] is not None and g[i] > zero) else None
                if ret is not None:
                    fim = ret                           # voltou: fecha na volta da corrente
                else:
                    # não voltou: encerra no FIM DE GERAÇÃO do inversor (última string a parar). Se a
                    # string só zerou DEPOIS que o inversor já parou de gerar, é o pôr-do-sol, não falha.
                    if inv_fim is None or inv_fim <= start:
                        continue
                    fim = inv_fim
                dur = (fim - start) * STR_EV_STEP
                if dur >= STR_EV_MIN_MIN:
                    eventos.append({"usina": usina, "inversor": inv_nome, "string": sid,
                                    "caiu": _str_hhmm(STR_EV_WIN_INI + start * STR_EV_STEP),
                                    "voltou": _str_hhmm(STR_EV_WIN_INI + ret * STR_EV_STEP) if ret is not None else None,
                                    "dur_min": dur, "gerando_agora": bool(gerando_agora)})
    return eventos



_pv_dev_names_cache = {}   # pid -> {ts, names}


def _pv_dev_names(pid, token):
    ent = _pv_dev_names_cache.get(pid)
    if ent and time.time() - ent["ts"] < 1800:
        return ent["names"]
    names = {}
    try:
        raw = _http().get(f"{BASE_URL}/plant_devices", headers={"x-access-token": token},
                          json={"id": pid}, timeout=20).json()
        devs = raw
        if isinstance(raw, list) and raw and "plant_devices" in raw[0]:
            devs = raw[0]["plant_devices"]
        elif isinstance(raw, dict):
            devs = raw.get("plant_devices", [])
        names = {d["device_id"]: str(d.get("device_name", "")).strip() for d in devs}
    except Exception:
        pass
    _pv_dev_names_cache[pid] = {"ts": time.time(), "names": names}
    return names


def _pv_curvas_strings(pid, nome_api, token):
    """Curva de corrente por string do DIA (day_inverter/Ipv) → {inv_display: {IpvN: [(hhmm, A)]}}.
    nome_api = nome da usina NA API (chave do EQUIP_NAMES); trancadas ficam de fora."""
    try:
        recs = _http().post(f"{BASE_URL}/day_inverter", headers={"x-access-token": token},
                            json={"id": pid}, timeout=45).json()
    except Exception:
        return {}
    if not recs:
        return {}
    dev_names = _pv_dev_names(pid, token)
    curvas = {}
    for rec in recs:
        inv_id = rec.get("idefinversor")
        ts = rec.get("tsleitura_new", "")
        if len(ts) < 16:
            continue
        hhmm = ts[11:16]
        cj = parse_cj(rec.get("conteudojson"))
        inv_api  = dev_names.get(inv_id, f"INV-{inv_id}")
        inv_disp = EQUIP_NAMES.get(nome_api, {}).get(inv_api, inv_api)
        for k, v in cj.items():
            if k.startswith("Ipv") and isinstance(v, (int, float)) \
                    and _str_key(pid, inv_id, k) not in _trancadas:
                curvas.setdefault(inv_disp, {}).setdefault(k, []).append((hhmm, v))
    return curvas


def _pv_curvas_strings_hist(pid, nome_api, data_br, token):
    """Curva de POTÊNCIA (W) por string de um DIA PASSADO (PV Plataforma · trygenerate) — a API PV não
    recupera CORRENTE histórica de string, mas recupera POTÊNCIA (mesma fonte da 'Curva das strings').
    Formato p/ _str_eventos_calc: {inv_display: {IpvN: [(hhmm, W)]}}. Trancadas ficam de fora."""
    curvas = {}
    for dev_id, nome in _spv_inversores_hist(pid, token, nome_api):
        pot = (_spv_trygenerate(dev_id, data_br) or {}).get("dados_potencia_string") or {}
        for st_key, serie in pot.items():
            n = _spv_stnum(st_key)
            if _str_key(pid, dev_id, f"Ipv{n}") in _trancadas:
                continue
            pts = []
            for p in (serie or []):
                parts = str(p.get("tsleitura") or "").split()
                hhmm = parts[4][:5] if len(parts) >= 5 and ":" in parts[4] else ""
                if hhmm:
                    pts.append((hhmm, float(p.get("potencia") or 0.0)))
            if pts:
                curvas.setdefault(nome, {})[f"Ipv{n}"] = pts
    return curvas


_pv_str_ev_cache = {}   # date_iso -> {ts, rows}


def _pv_strings_eventos(date_iso, force=False):
    """Ocorrências de strings da API PV (caiu→voltou). HOJE = CORRENTE (A) via day_inverter/Ipv;
    DIA PASSADO = POTÊNCIA (W) por string via PV Plataforma (trygenerate) — a corrente histórica não
    é recuperável, mas a potência sim (mesma fonte da 'Curva das strings')."""
    hoje = datetime.now().strftime("%Y-%m-%d")
    ent = _pv_str_ev_cache.get(date_iso)
    if ent and not force and (date_iso != hoje or (time.time() - ent["ts"]) < CACHE_TTL):
        return ent["rows"]
    token = get_token()
    try:
        plants = [p for p in get_plants(token) if (not FULL_OM or p["nome"].strip() in FULL_OM)]
    except Exception:
        return []
    data_br = datetime.strptime(date_iso, "%Y-%m-%d").strftime("%d/%m/%Y")
    passado = date_iso != hoje

    def _um(p):
        pid = p["id"]
        if passado:      # dia passado → potência (W) via Plataforma, limiares em W
            curvas = _pv_curvas_strings_hist(pid, p["nome"].strip(), data_br, token)
            evs = _str_eventos_calc(_macro_usina_nome(nome_usina(pid, p["nome"])) or nome_usina(pid, p["nome"]),
                                    curvas, zero_thr=STR_EV_POT_ZERO_W, inv_min=STR_EV_POT_INV_MED,
                                    inv_min_frac=STR_EV_POT_INV_FRAC) if curvas else []
        else:            # hoje → corrente (A) via day_inverter
            curvas = _pv_curvas_strings(pid, p["nome"].strip(), token)
            evs = _str_eventos_calc(_macro_usina_nome(nome_usina(pid, p["nome"])) or nome_usina(pid, p["nome"]),
                                    curvas) if curvas else []
        for e in evs:
            e["plant_id"] = pid
        return evs

    rows = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for evs in ex.map(_um, plants):
            rows.extend(evs)
    rows.sort(key=lambda r: (r["usina"], str(r["inversor"]), r["caiu"]))
    rows = _trk_geo_annotate(rows)
    _pv_str_ev_cache[date_iso] = {"ts": time.time(), "rows": rows}
    return rows


def _owen_strings_eventos(date_iso, force=False):
    """Ocorrências de strings do 2C (caiu→voltou) — curvas 5 min do banco-por-dia (_hist_build:
    hoje = pastas flat com cache 120s; dia passado = 2C_historico permanente)."""
    data = _hist_build(date_iso).get("strings", {})
    rows = []
    for u, invs in data.items():
        usina = _macro_usina_nome(_owen_nome(u)) or _owen_nome(u)
        curvas = {inv: {sid: serie for sid, serie in strs.items()
                        if _str_key(u, inv, sid) not in _trancadas}
                  for inv, strs in invs.items()}
        for ev in _str_eventos_calc(usina, curvas):
            ev["plant_id"] = u
            rows.append(ev)
    rows.sort(key=lambda r: (r["usina"], str(r["inversor"]), r["caiu"]))
    return _trk_geo_annotate(rows)


_sunop_str_ev_cache = {}   # (inst, date_iso) -> {ts, rows}


def _sunop_strings_eventos(date_iso, inst="gridco", force=False):
    """Ocorrências de strings do SunOp (Athon/Axis) — curva I_PV por inversor via
    _sunop_strings_curva (trancadas já filtradas; horário do plant timezone)."""
    hoje = datetime.now().strftime("%Y-%m-%d")
    key = (inst, date_iso)
    ent = _sunop_str_ev_cache.get(key)
    if ent and not force and (date_iso != hoje or (time.time() - ent["ts"]) < CACHE_TTL):
        return ent["rows"]
    try:
        ensure_sunop_meta(inst)
        plants = list(_si(inst)["meta"].keys())
    except Exception:
        return []

    def _um(pn):
        try:
            pay = _sunop_strings_curva(pn, date_iso, None, inst)
        except Exception:
            return []
        curvas = {iv["nome"]: {st: list(zip(c["x"], c["y"])) for st, c in (iv.get("curva") or {}).items()}
                  for iv in (pay.get("inversores") or [])}
        if not curvas:
            return []
        usina = _macro_usina_nome(pn) or pn
        evs = _str_eventos_calc(usina, curvas)
        for e in evs:
            e["plant_id"] = pn
        return evs

    rows = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for f in as_completed([ex.submit(_um, p) for p in plants]):
            try:
                rows.extend(f.result())
            except Exception:
                pass
    rows.sort(key=lambda r: (r["usina"], str(r["inversor"]), r["caiu"]))
    rows = _trk_geo_annotate(rows)
    _sunop_str_ev_cache[key] = {"ts": time.time(), "rows": rows}
    return rows


_STR_EV_FONTES = ("pv", "owen", "sunop", "axis")   # PG fica fora: string é snapshot (sem curva)


def _strings_eventos_rows(fonte, date_iso, force=False):
    if fonte == "pv":
        return _pv_strings_eventos(date_iso, force)
    if fonte == "owen":
        return _owen_strings_eventos(date_iso, force)
    if fonte in ("sunop", "axis"):
        return _sunop_strings_eventos(date_iso, "axis" if fonte == "axis" else "gridco", force)
    # PG NÃO dá: stg_inverter_string_data é snapshot (1 leitura/dia, sem curva intradiária).
    return []


@app.route("/api/<fonte>/strings/eventos")
def api_strings_eventos(fonte):
    if fonte not in _STR_EV_FONTES:
        return jsonify({"rows": [], "total": 0, "indisponivel": True, "ini": "", "fim": "",
                        "cache_ts": datetime.now().strftime("%H:%M:%S")})
    dia = (flask_request.args.get("ini") or datetime.now().strftime("%Y-%m-%d")).strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", dia):
        dia = datetime.now().strftime("%Y-%m-%d")
    rows = _strings_eventos_rows(fonte, dia, force=flask_request.args.get("force") == "1")
    return jsonify({"rows": rows, "total": len(rows), "ini": dia, "fim": dia,
                    "cache_ts": datetime.now().strftime("%H:%M:%S")})


@app.route("/api/<fonte>/strings/eventos/export.xlsx")
def api_strings_eventos_xlsx(fonte):
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    if fonte not in _STR_EV_FONTES:
        return jsonify({"error": "fonte sem ocorrências de strings (PG é snapshot)"}), 404
    dia = (flask_request.args.get("ini") or datetime.now().strftime("%Y-%m-%d")).strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", dia):
        dia = datetime.now().strftime("%Y-%m-%d")
    qf = (flask_request.args.get("usina") or "").strip().lower()
    rows = _strings_eventos_rows(fonte, dia)
    if qf:
        rows = [r for r in rows if qf in (r.get("usina") or "").lower()]
    label = _TRK_FONTE_LABEL.get(fonte, fonte)
    NAVY = "1A1B2E"
    hdr_fill = PatternFill("solid", fgColor=NAVY); hdr_font = Font(color="FFFFFF", bold=True)
    dia_br = datetime.strptime(dia, "%Y-%m-%d").strftime("%d/%m/%Y")
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Ocorrências strings"
    ro = 1
    ws.cell(row=ro, column=1, value=f"Ocorrências de strings (caiu → voltou) · {label} · {dia_br}").font = Font(bold=True, size=14, color=NAVY)
    ro += 2
    headers = ["Usina", "Inversor", "String", "Caiu", "Voltou", "Duração", "Região", "Cliente"]
    hr = ro
    for j, h in enumerate(headers, start=1):
        c = ws.cell(row=hr, column=j, value=h); c.fill = hdr_fill; c.font = hdr_font
    ro += 1
    for r in rows:
        dur = int(r.get("dur_min") or 0)
        ret = f"{dia_br} {r['voltou']}" if r.get("voltou") else "não voltou no dia"
        vals = [r.get("usina"), r.get("inversor") or "—", r.get("string"),
                f"{dia_br} {r.get('caiu','')}", ret, f"{dur // 60}h{dur % 60:02d}",
                r.get("regiao") or "—", r.get("cliente") or "—"]
        for j, val in enumerate(vals, start=1):
            ws.cell(row=ro, column=j, value=val)
        if not r.get("voltou"):
            ws.cell(row=ro, column=5).font = Font(color="B91C1C")
        ro += 1
    for j, w in enumerate([24, 16, 8, 16, 20, 10, 14, 12], start=1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = ws.cell(row=hr + 1, column=1)
    return _xlsx_resp(wb, f"ocorrencias_strings_{fonte}_{dia}.xlsx")


@app.route("/api/owen/strings/data")
def api_owen_strings_data():
    rows = _owen_strings_rows(flask_request.args.get("force") == "1")
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
        # mesma régua do SunOp/API PV: status + trancada (string aberta sai da contagem)
        stt = _classifica_strings(plant_id, inv, ids, correntes)
        chips = [{"id": s, "corrente": c, "status": st,
                  "ativa": st in ("ativa", "baixa_perf"), "trancada": st == "trancada"}
                 for s, c, st in zip(ids, correntes, stt)]
        ativas = _str_ativas(stt)
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
def _owen_trackers_build(force=False, date=None):
    # date=YYYY-MM-DD passado → lê o banco-por-dia (2C_historico); hoje/None → acumulador ao vivo.
    if date and date != datetime.now().strftime("%Y-%m-%d"):
        return _hist_build(date).get("trackers", {})
    _owen_refresh(force)
    with _owen_lock:
        return {u: {n: {"alvo": _owen_pts(d["alvo"]), "atual": _owen_pts(d["atual"])}
                    for n, d in trks.items()}
                for u, trks in _owen_accum.get("trackers", {}).items()}


def _owen_trackers_analise(plant_id, date=None):
    nome = _owen_nome(plant_id)
    trks = _owen_trackers_build(date=date).get(plant_id, {})
    base = {"usina": nome, "plant_id": plant_id, "total": 0, "parados": 0,
            "desvios": 0, "atrasos": 0, "sem_alvo": False, "pior_disparidade": None,
            "ultima_leitura": None, "trackers": [], "tem_trackers": bool(trks)}
    if not trks:
        return base
    # amplitude = JANELA DIURNA 06–18h (reposicionamento noturno não é rastreamento) + range
    # ROBUSTO p02–p98 (glitch de telemetria não infla) — mesma régua do SunOp/PV (caso Tracker 82)
    amps = {n: (_amp_robusta([v for t, v in d["atual"] if 6 <= t.hour < 18]) if d["atual"] else None)
            for n, d in trks.items()}
    amp_ok = sorted(a for a in amps.values() if a is not None)
    amp_ref = amp_ok[len(amp_ok) // 2] if amp_ok else 0.0
    sem_alvo = all(not d["alvo"] for d in trks.values())
    # span coberto pela curva → régua ABSOLUTA de "parado" (MESMA do SunOp/PG/grade): amp baixa por ≥4h,
    # sem depender de os vizinhos girarem (senão usina INTEIRA parada nunca era pega, ex.: SMP100/CPP100).
    _all_ts = [t for d in trks.values() for (t, _) in d["atual"]]
    span_h = ((max(_all_ts) - min(_all_ts)).total_seconds() / 3600.0) if len(_all_ts) >= 2 else 0.0
    dia_coberto = span_h >= TRK_COBERTURA_MIN_H

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
        if amp is not None and amp < TRK_PARADO_AMP and _frota_acordou(amps, dia_coberto, date):
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
    _atuais = [r["atual"] for r in raw if r["atual"] is not None]
    media_ang = (sum(_atuais) / len(_atuais)) if _atuais else None
    _cdisp = [r["cur"] for r in raw if r["cur"] is not None]
    desvio_med = (sum(_cdisp) / len(_cdisp)) if _cdisp else None
    base.update({"total": len(lst), "parados": par, "desvios": des, "atrasos": atr,
                 # aliases p/ a tabela-resumo compartilhada (renderSoTrackers lê severos/leves/fora_media)
                 "severos": par, "leves": des, "fora_media": atr,
                 "sem_alvo": sem_alvo, "pior_disparidade": pior,
                 "media_angulo": round(media_ang, 1) if media_ang is not None else None,
                 "desvio_medio": round(desvio_med, 2) if desvio_med is not None else None,
                 "sem_comunicacao": not _atuais,
                 "ultima_leitura": ts_max.strftime("%Y-%m-%d %H:%M") if ts_max else None,
                 "trackers": lst})
    return _trk_alvo_mediana(base)


@app.route("/api/owen/trackers")
def api_owen_trackers():
    rows = []
    for u in OWEN_UFVS:
        r = _owen_trackers_analise(u)
        r.pop("trackers", None)
        rows.append(r)
    disp_pid = _owen_disp_hoje()                   # disponibilidade por TEMPO (janela 06:00–18:00)
    for r in rows:
        r["disponibilidade_tempo"] = disp_pid.get(r["plant_id"])
    rows.sort(key=lambda x: (_trk_severidade2(x), x["usina"]))
    return jsonify({"rows": rows, "summary": {
        "usinas": sum(1 for r in rows if r["total"]),
        "trackers": sum(r["total"] for r in rows),
        "parados": sum(r["parados"] for r in rows),
        "atrasos": sum(r["atrasos"] for r in rows)},
        "cache_ts": datetime.now().strftime("%H:%M:%S")})


@app.route("/api/owen/trackers/<plant_id>")
def api_owen_trackers_plant(plant_id):
    date = (flask_request.args.get("date") or "").strip()
    return jsonify(_owen_trackers_analise(plant_id, date=date or None))


@app.route("/api/owen/trackers/<plant_id>/chart")
def api_owen_trackers_chart(plant_id):
    ini, fim, ndias = _trk_chart_range()
    hoje = datetime.now().strftime("%Y-%m-%d")
    # concatena dia a dia (o acervo do 2C é por dia): {tracker: {'atual':[(dt,v)], 'alvo':[...]}}
    merged = {}
    for d in _trk_ev_dias(ini, fim):
        d_iso = d.strftime("%Y-%m-%d")
        day = _owen_trackers_build(date=(None if d_iso == hoje else d_iso)).get(plant_id, {})
        for n, dd in day.items():
            m = merged.setdefault(n, {"atual": [], "alvo": []})
            m["atual"].extend(dd.get("atual") or [])
            m["alvo"].extend(dd.get("alvo") or [])
    _alvo_max = _trk_chart_down_alvo(ndias)
    def _down(s): return s[::max(1, len(s) // _alvo_max)]
    def _num(n): return [int(p) for p in n.split(".")]
    out, alvo = [], None
    for n in sorted(merged, key=_num):
        s = merged[n]["atual"]
        if s:
            s = _down(s)
            out.append({"id": f"Tracker {n}", "x": [t.strftime("%Y-%m-%dT%H:%M:%SZ") for t, _ in s],
                        "y": [round(v, 2) for _, v in s]})
    for n in sorted(merged, key=_num):
        s = merged[n]["alvo"]
        if s:
            s = _down(s)
            alvo = {"x": [t.strftime("%Y-%m-%dT%H:%M:%SZ") for t, _ in s], "y": [round(v, 2) for _, v in s]}
            break
    return jsonify({"plant": _owen_nome(plant_id), "date": ini, "ini": ini, "fim": fim,
                    "ndias": ndias, "trackers": out, "alvo": alvo})


# ── Owen (2C): Trackers parados (agora) + Ocorrências (travou→voltou) — espelho das sub-abas API PV ──
#   Curva: acumulador (hoje) / 2C_historico (passado). Só 4 UFVs → on-demand direto (sem pool/job).
def _owen_curve_for(code, data_br):
    """Curva ATUAL por tracker no formato do motor de eventos: {tracker: [{x,y}]}."""
    try:
        date_iso = datetime.strptime(data_br, "%d/%m/%Y").strftime("%Y-%m-%d")
    except Exception:
        date_iso = data_br
    trks = _owen_trackers_build(date=date_iso).get(code, {})
    return {f"Tracker {n}": [{"x": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "y": v} for t, v in d["atual"]]
            for n, d in trks.items() if d.get("atual")}


def _owen_parados_rows(force=False):
    if force:
        try:
            _owen_refresh(force=True)          # recarrega o acervo do dia → recomputa o status
        except Exception:
            pass
    rows = []
    for code in OWEN_UFVS:
        try:
            a = _owen_trackers_analise(code)
        except Exception:
            continue
        for t in a.get("trackers", []):
            if t.get("status") == "parado":
                rows.append({"plant_id": code, "usina": a["usina"], "tracker": t["id"],
                             "inversor": "", "atual": t.get("atual"), "alvo": t.get("alvo"),
                             "disparidade": t.get("disparidade"), "amplitude": t.get("amplitude"),
                             "na_planilha": False, "parado_desde": None,
                             "horas_parado": None, "dias_parado": None,
                             "ultima_leitura": a.get("ultima_leitura")})
    rows.sort(key=lambda r: (r["usina"], _pv_trk_num(r["tracker"])))
    return _trk_geo_annotate(rows)


@app.route("/api/owen/trackers/parados")
def api_owen_trackers_parados():
    """Lista flat de todos os trackers 2C 'parado' agora (analise por usina)."""
    rows = _owen_parados_rows(force=flask_request.args.get("force") == "1")
    return jsonify({"rows": rows, "total": len(rows), "cache_ts": datetime.now().strftime("%H:%M:%S")})


_owen_ev_cache = {}   # date_iso -> {ts, rows, disp, disp_pid}


def _owen_eventos_calc(date_iso):
    """Calcula (e cacheia) as ocorrências + disponibilidade por tempo do 2C num dia.
    disp_pid chaveado pelo code da usina (ex.: 'TUP') — mesma chave do overview."""
    hoje_iso = datetime.now().strftime("%Y-%m-%d")
    ent = _owen_ev_cache.get(date_iso)
    if ent and (date_iso != hoje_iso or (time.time() - ent["ts"]) < CACHE_TTL):
        return ent
    data_br = datetime.strptime(date_iso, "%Y-%m-%d").strftime("%d/%m/%Y")
    dd = date_iso.split("-")
    rows, disp, disp_pid = [], {}, {}
    for code in OWEN_UFVS:
        un = _owen_nome(code)
        try:
            res = _trk_eventos_do_dia(code, un, data_br, curve=_owen_curve_for(code, data_br))
        except Exception:
            continue
        if res.get("disponibilidade") is not None:
            disp[un] = res["disponibilidade"]
            disp_pid[code] = res["disponibilidade"]
        for ev in res["eventos"]:
            rows.append({"data_iso": date_iso, "data": f"{dd[2]}/{dd[1]}", "usina": un,
                         "tracker": ev["tracker"], "inversor": "",
                         "parada": ev["parada"], "retorno": ev.get("retorno"), "dur_min": ev.get("dur_min")})
    rows.sort(key=lambda r: (r["usina"], r["parada"]))
    ent = {"ts": time.time(), "rows": rows, "disp": disp, "disp_pid": disp_pid}
    _owen_ev_cache[date_iso] = ent
    return ent


def _owen_disp_hoje():
    """Disponibilidade por tempo (hoje) por code de usina — reusa/aquece o cache de Ocorrências."""
    hoje_iso = datetime.now().strftime("%Y-%m-%d")
    try:
        return _owen_eventos_calc(hoje_iso).get("disp_pid", {})
    except Exception:
        return {}


@app.route("/api/owen/trackers/eventos")
def api_owen_trackers_eventos():
    """Ocorrências travou→voltou do 2C, ON-DEMAND por dia (acumulador hoje / 2C_historico passado)."""
    ini = (flask_request.args.get("ini") or datetime.now().strftime("%Y-%m-%d")).strip()
    date_iso = ini if re.match(r"^\d{4}-\d{2}-\d{2}$", ini) else datetime.now().strftime("%Y-%m-%d")
    ent = _owen_eventos_calc(date_iso)
    return jsonify({"rows": ent["rows"], "disp": ent.get("disp", {}), "ini": date_iso, "fim": date_iso, "total": len(ent["rows"]),
                    "data_ini_hist": "2026-05-13", "progresso": {}})


def _trk_severidade2(r) -> int:
    if r.get("parados"): return 0
    if r.get("desvios"): return 1
    if r.get("atrasos"): return 2
    if not r.get("total"): return 4
    return 3


# ══ HISTÓRICO 2C — navega o banco-por-dia (2C_historico/<data>) com curvas ══════
#   O coletor arquiva cada dia em OWEN_ROOT/2C_historico/AAAA-MM-DD/{ETM,Strings,Trackers}.
#   Aqui lemos uma DATA específica e montamos as séries COMPLETAS (5 min) p/ gráfico —
#   diferente do _owen_refresh (só dia atual + colapsa string no último valor).
_HIST_ROOT        = os.path.join(OWEN_ROOT, "2C_historico")
_hist_cache       = {}            # data → {etm, strings, trackers} (séries completas)
_hist_cache_order = []            # LRU
_HIST_CACHE_MAX   = 2
_hist_lock        = threading.Lock()


def _hist_rows(dirpath):
    """Itera (point_name, datetime, value) dos CSVs de um diretório (latin-1)."""
    if not os.path.isdir(dirpath):
        return
    for fn in sorted(os.listdir(dirpath)):
        if not fn.lower().endswith(".csv"):
            continue
        try:
            with open(os.path.join(dirpath, fn), encoding="latin-1", newline="") as fh:
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


def _hist_days():
    """Datas disponíveis no arquivo (AAAA-MM-DD), mais recente primeiro."""
    if not os.path.isdir(_HIST_ROOT):
        return []
    ds = [d for d in os.listdir(_HIST_ROOT)
          if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) and os.path.isdir(os.path.join(_HIST_ROOT, d))]
    return sorted(ds, reverse=True)


def _hist_build(date):
    """Séries completas (5 min) de um dia. Dia PASSADO: lê 2C_historico (cache permanente).
    HOJE: lê as pastas flat (OWEN_ROOT), sempre atuais, com cache curto (o arquivo do dia ainda enche)."""
    hoje = datetime.now().strftime("%Y-%m-%d")
    is_today = (date == hoje)
    with _hist_lock:
        ent = _hist_cache.get(date)
        if ent and (not is_today or (time.time() - ent["ts"]) < 120):
            try: _hist_cache_order.remove(date)
            except ValueError: pass
            _hist_cache_order.append(date)
            return ent["data"]
    base = OWEN_ROOT if is_today else os.path.join(_HIST_ROOT, date)
    rxs = re.compile(r"_Inv_([\d.]+)_STR_Corrente PV(\d+)")
    rxt = re.compile(r"_TRK_([\d.]+)_MED_(.+?) \(graus\)")
    etm, strings, trackers = {}, {}, {}
    for pn, t, v in _hist_rows(os.path.join(base, "ETM")):
        if is_today and t.strftime("%Y-%m-%d") != hoje: continue   # flat pode ter sobra de outro dia
        u = pn.split("_", 1)[0]
        if u not in OWEN_UFVS:
            continue
        med = "ghi" if "GHI" in pn else ("poa" if "POA" in pn else None)
        if med:
            etm.setdefault(u, {}).setdefault(med, []).append((t, _etm_clamp(v)))
    for pn, t, v in _hist_rows(os.path.join(base, "Strings")):
        if is_today and t.strftime("%Y-%m-%d") != hoje: continue
        u = pn.split("_", 1)[0]
        if u not in OWEN_UFVS:
            continue
        m = rxs.search(pn)
        if not m:
            continue
        strings.setdefault(u, {}).setdefault(m.group(1), {}).setdefault(str(int(m.group(2))), []).append((t, v))
    for pn, t, v in _hist_rows(os.path.join(base, "Trackers")):
        if is_today and t.strftime("%Y-%m-%d") != hoje: continue
        u = pn.split("_", 1)[0]
        if u not in OWEN_UFVS:
            continue
        m = rxt.search(pn)
        if not m:
            continue
        key = "alvo" if "Alvo" in m.group(2) else ("atual" if "Atual" in m.group(2) else None)
        if key:
            trackers.setdefault(u, {}).setdefault(m.group(1), {"alvo": [], "atual": []})[key].append((t, v))
    for d in etm.values():
        for s in d.values(): s.sort()
    for invs in strings.values():
        for strs in invs.values():
            for s in strs.values(): s.sort()
    for trks in trackers.values():
        for node in trks.values():
            node["alvo"].sort(); node["atual"].sort()
    built = {"etm": etm, "strings": strings, "trackers": trackers}
    with _hist_lock:
        _hist_cache[date] = {"ts": time.time(), "data": built}
        _hist_cache_order.append(date)
        while len(_hist_cache_order) > _HIST_CACHE_MAX:
            old = _hist_cache_order.pop(0)
            if old != date: _hist_cache.pop(old, None)
    return built


def _inv_key(x):
    try:    return [int(p) for p in x.split(".")]
    except Exception: return [9999]


@app.route("/api/2c/dias")
def api_2c_dias():
    return jsonify({"dias": _hist_days(),
                    "usinas": [{"id": u, "nome": _owen_nome(u)} for u in OWEN_UFVS]})


@app.route("/api/2c/<date>")
def api_2c_overview(date):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date or ""):
        return jsonify({"erro": "data inválida"}), 400
    b = _hist_build(date)
    out = []
    for u in OWEN_UFVS:
        invs = b["strings"].get(u, {})
        etm  = b["etm"].get(u, {})
        out.append({"id": u, "nome": _owen_nome(u),
                    "inversores": len(invs),
                    "strings": sum(len(s) for s in invs.values()),
                    "trackers": len(b["trackers"].get(u, {})),
                    "etm": bool(etm.get("ghi") or etm.get("poa")),
                    "tem_dados": bool(invs or b["trackers"].get(u) or etm)})
    return jsonify({"date": date, "usinas": out})


@app.route("/api/2c/<date>/etm/<usina>")
def api_2c_etm(date, usina):
    d = _hist_build(date)["etm"].get(usina, {})
    byts = {}
    for med in ("poa", "ghi"):
        for t, v in d.get(med, []):
            byts.setdefault(t, {})[med] = v
    ts = sorted(byts)
    return jsonify({"usina": _owen_nome(usina), "date": date,
                    "labels": [t.strftime("%H:%M") for t in ts],
                    "poa": [byts[t].get("poa") for t in ts],
                    "ghi": [byts[t].get("ghi") for t in ts]})


@app.route("/api/2c/<date>/strings/<usina>")
def api_2c_strings(date, usina):
    invs = _hist_build(date)["strings"].get(usina, {})
    out = []
    for inv in sorted(invs, key=_inv_key):
        strs = invs[inv]
        # Eixo por MINUTO (HH:MM), não pelo timestamp com segundos: alguns inversores (ex.: ARA 1.3/1.10)
        # reportam em segundos diferentes a cada leva, o que duplicava os minutos no eixo (288 pts) e
        # deixava cada string com None alternado → linha invisível. Agrupar por minuto resolve.
        allmin = sorted({t.strftime("%H:%M") for sn in strs for t, _ in strs[sn]})
        idx = {hm: i for i, hm in enumerate(allmin)}
        series = []
        for sn in sorted(strs, key=lambda x: int(x)):
            y = [None] * len(allmin)
            for t, v in strs[sn]:
                y[idx[t.strftime("%H:%M")]] = round(v, 2)   # última leitura do minuto
            series.append({"id": sn, "y": y})
        out.append({"inv": inv, "labels": allmin, "strings": series})
    return jsonify({"usina": _owen_nome(usina), "date": date, "inversores": out})


@app.route("/api/2c/<date>/trackers/<usina>")
def api_2c_trackers(date, usina):
    trks = _hist_build(date)["trackers"].get(usina, {})
    def _down(s, m=220): return s[::max(1, len(s) // m)] if len(s) > m else s
    out, alvo = [], None
    for n in sorted(trks, key=_inv_key):
        s = _down(trks[n]["atual"])
        if s:
            out.append({"id": f"Tracker {n}",
                        "x": [t.strftime("%H:%M") for t, _ in s],
                        "y": [round(v, 2) for _, v in s]})
    for n in sorted(trks, key=_inv_key):
        if trks[n]["alvo"]:
            s = _down(trks[n]["alvo"])
            alvo = {"x": [t.strftime("%H:%M") for t, _ in s], "y": [round(v, 2) for _, v in s]}
            break
    return jsonify({"usina": _owen_nome(usina), "date": date, "trackers": out, "alvo": alvo})


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
    """Resumo por usina — MESMO motor de curva das sub-abas Parados/Ocorrências
    (régua ABSOLUTA amp<15°+≥4h), p/ o overview não divergir do detalhe."""
    conn = _pg_conn(); cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT p.id, p.name
        FROM dbt.int_tracker_latest_readings t
        JOIN public.tb_power_plants p ON p.id = t.power_plant_id
        ORDER BY p.name
    """)
    plants = cur.fetchall(); conn.close()

    out = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_pg_trackers_analise, str(pid)): pname for pid, pname in plants}
        for f in as_completed(futs):
            try:
                r = f.result()
            except Exception:
                continue
            r.pop("trackers", None)   # overview não carrega a lista completa
            r["tem_trackers"] = True
            out.append(r)
    out.sort(key=lambda x: (_trk_severidade(x), x["usina"]))
    disp_pid = _pg_disp_hoje(ov_rows=out)          # disponibilidade por TEMPO (janela 06:00–18:00)
    for r in out:
        r["disponibilidade_tempo"] = disp_pid.get(str(r["plant_id"]))
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


def _pg_trk_plant_curvas(plant_id: str, date: str, date_fim: str = None) -> dict:
    """Série de uma usina → {tracker: {'alvo':[(ts,v)], 'atual':[(ts,v)]}}. date_fim=None → só o
    'date'; senão o INTERVALO [date, date_fim] inclusive (gráfico De/Até multi-dia)."""
    fim = date_fim or date
    key = (str(plant_id), date, fim)
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
        """, (int(plant_id), date, fim))
        for dname, ts, posat, posal in cur.fetchall():
            d = dados.setdefault(dname, {"alvo": [], "atual": []})
            if posat is not None:
                d["atual"].append((ts, float(posat)))
            if posal is not None:
                d["alvo"].append((ts, float(posal)))
        conn.close()
    except Exception as e:
        print(f"[PG TRK] erro curvas {plant_id}/{date}..{fim}: {e}")
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
    # amplitude = JANELA DIURNA 06–18h (reposicionamento noturno não é rastreamento) + range
    # ROBUSTO p02–p98 (glitch de telemetria não infla) — mesma régua do SunOp/PV (caso Tracker 82)
    amps = {n: (_amp_robusta([v for t, v in d["atual"] if 6 <= t.hour < 18]) if d["atual"] else None)
            for n, d in trks.items()}
    amp_ok = sorted(a for a in amps.values() if a is not None)
    amp_ref = amp_ok[len(amp_ok) // 2] if amp_ok else 0.0
    sem_alvo = all(not d["alvo"] for d in trks.values())
    # span coberto pela curva → régua ABSOLUTA de "parado" (MESMA do SunOp/grade): amp baixa por ≥4h,
    # sem depender de os vizinhos girarem (senão usina INTEIRA parada nunca era pega, ex.: SMP100/CPP100).
    _all_ts = [t for d in trks.values() for (t, _) in d["atual"]]
    span_h = ((max(_all_ts) - min(_all_ts)).total_seconds() / 3600.0) if len(_all_ts) >= 2 else 0.0
    dia_coberto = span_h >= TRK_COBERTURA_MIN_H

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
        if amp is not None and amp < TRK_PARADO_AMP and _frota_acordou(amps, dia_coberto, date):
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
    _atuais = [r["atual"] for r in raw if r["atual"] is not None]
    media_ang = (sum(_atuais) / len(_atuais)) if _atuais else None
    _cdisp = [r["cur"] for r in raw if r["cur"] is not None]
    desvio_med = (sum(_cdisp) / len(_cdisp)) if _cdisp else None
    base.update({"total": len(lst), "parados": par, "desvios": des, "atrasos": atr,
                 "severos": par, "leves": des, "fora_media": atr,
                 "sem_alvo": sem_alvo, "pior_disparidade": pior,
                 "media_angulo": round(media_ang, 1) if media_ang is not None else None,
                 "desvio_medio": round(desvio_med, 2) if desvio_med is not None else None,
                 "sem_comunicacao": not _atuais,
                 "ultima_leitura": ts_max.strftime("%Y-%m-%d %H:%M") if ts_max else None,
                 "trackers": lst})
    return _trk_alvo_mediana(base)


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
    ini, fim, ndias = _trk_chart_range()
    if ndias == 1 and not flask_request.args.get("ini") and not flask_request.args.get("fim"):
        ini = fim = (flask_request.args.get("date") or _pg_trk_default_date()).strip()   # compat: default do PG
    trks = _pg_trk_plant_curvas(plant_id, ini, fim if ndias > 1 else None)
    _alvo_max = _trk_chart_down_alvo(ndias)
    def _down(s): return s[::max(1, len(s) // _alvo_max)]
    out, alvo = [], None
    for n in sorted(trks, key=_pg_trk_num):
        s = trks[n]["atual"]
        if s:
            s = _down(s)
            out.append({"id": n, "x": [t.strftime("%Y-%m-%dT%H:%M:%SZ") for t, _ in s],
                        "y": [round(v, 2) for _, v in s]})
    for n in sorted(trks, key=_pg_trk_num):
        s = trks[n]["alvo"]
        if s:
            s = _down(s)
            alvo = {"x": [t.strftime("%Y-%m-%dT%H:%M:%SZ") for t, _ in s], "y": [round(v, 2) for _, v in s]}
            break
    return jsonify({"plant": _pg_trk_nome(plant_id), "date": ini, "ini": ini, "fim": fim,
                    "ndias": ndias, "trackers": out, "alvo": alvo})


# ── PG: Trackers parados (agora) + Ocorrências (travou→voltou) — espelho das sub-abas da API PV ──
#   A curva vem do banco (rápido), então as Ocorrências são calculadas ON-DEMAND por dia (sem o job de
#   backfill/persistência que a API PV precisa por causa do trackerschart de 90s).
def _pg_curve_for(plant_id, data_br):
    """Curva ATUAL por tracker no formato do motor de eventos: {tracker: [{x,y}]}."""
    try:
        date_iso = datetime.strptime(data_br, "%d/%m/%Y").strftime("%Y-%m-%d")
    except Exception:
        date_iso = data_br
    cv = _pg_trk_plant_curvas(plant_id, date_iso)
    return {n: [{"x": ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "y": v} for ts, v in d["atual"]]
            for n, d in cv.items() if d.get("atual")}


def _pg_parados_rows(force=False):
    date = _pg_trk_default_date()
    if force:
        _pg_trk_curva_cache.clear()            # busta as curvas do dia → recomputa do banco
    ov = _swr(_pg_trk_cache, _pg_trackers_overview, force)
    rows = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_pg_trackers_analise, r["plant_id"], date): r for r in (ov.get("rows") or [])}
        for f in as_completed(futs):
            try:
                a = f.result()
            except Exception:
                continue
            for t in a.get("trackers", []):
                if t.get("status") == "parado":
                    rows.append({"plant_id": a["plant_id"],
                                 "usina": _macro_usina_nome(a["usina"]) or a["usina"], "tracker": t["id"],
                                 "inversor": "", "atual": t.get("atual"), "alvo": t.get("alvo"),
                                 "disparidade": t.get("disparidade"), "amplitude": t.get("amplitude"),
                                 "na_planilha": False, "parado_desde": None,
                                 "horas_parado": None, "dias_parado": None,
                                 "ultima_leitura": a.get("ultima_leitura")})
    rows.sort(key=lambda r: (r["usina"], _pg_trk_num(r["tracker"])))
    return _trk_geo_annotate(rows)


@app.route("/api/pg/trackers/parados")
def api_pg_trackers_parados():
    """Lista flat de todos os trackers PG classificados como 'parado' agora (curva do dia, por usina)."""
    rows = _pg_parados_rows(force=flask_request.args.get("force") == "1")
    return jsonify({"rows": rows, "total": len(rows), "cache_ts": datetime.now().strftime("%H:%M:%S")})


_pg_ev_cache = {}   # date_iso -> {ts, rows, disp, disp_pid}


def _pg_eventos_calc(date_iso, ov_rows=None):
    """Calcula (e cacheia) as ocorrências + disponibilidade por tempo do PG num dia. `ov_rows` evita
    rechamar o overview quando já o temos em mãos (usado pelo próprio _pg_trackers_overview, sem
    recursão). disp_pid chaveado por plant_id (str) — pro merge no overview por id, sem depender do
    nome bater (o overview usa o nome cru do banco; o de exibição pode diferir)."""
    hoje_iso = datetime.now().strftime("%Y-%m-%d")
    ent = _pg_ev_cache.get(date_iso)
    if ent and (date_iso != hoje_iso or (time.time() - ent["ts"]) < CACHE_TTL):
        return ent
    data_br = datetime.strptime(date_iso, "%Y-%m-%d").strftime("%d/%m/%Y")
    dd = date_iso.split("-")
    if ov_rows is None:
        ov_rows = (_swr(_pg_trk_cache, _pg_trackers_overview, False).get("rows") or [])

    def _um(r):
        pid, nome = r["plant_id"], r["usina"]
        un = _macro_usina_nome(nome) or nome
        try:
            res = _trk_eventos_do_dia(pid, nome, data_br, curve=_pg_curve_for(pid, data_br))
        except Exception:
            return un, str(pid), None, []
        rws = [{"data_iso": date_iso, "data": f"{dd[2]}/{dd[1]}", "usina": un,
                "tracker": ev["tracker"], "inversor": "",
                "parada": ev["parada"], "retorno": ev.get("retorno"), "dur_min": ev.get("dur_min")}
               for ev in res["eventos"]]
        return un, str(pid), res.get("disponibilidade"), rws
    rows, disp, disp_pid = [], {}, {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for un, pid_s, dsp, part in ex.map(_um, ov_rows):
            rows.extend(part)
            if dsp is not None:
                disp[un] = dsp
                disp_pid[pid_s] = dsp
    rows.sort(key=lambda r: (r["usina"], r["parada"]))
    ent = {"ts": time.time(), "rows": rows, "disp": disp, "disp_pid": disp_pid}
    _pg_ev_cache[date_iso] = ent
    return ent


def _pg_disp_hoje(ov_rows=None):
    """Disponibilidade por tempo (hoje) por plant_id (str) — reusa/aquece o cache de Ocorrências."""
    hoje_iso = datetime.now().strftime("%Y-%m-%d")
    try:
        return _pg_eventos_calc(hoje_iso, ov_rows=ov_rows).get("disp_pid", {})
    except Exception:
        return {}


@app.route("/api/pg/trackers/eventos")
def api_pg_trackers_eventos():
    """Ocorrências travou→voltou do PG, calculadas ON-DEMAND por dia (banco é rápido). ?ini=&fim= (usa o dia)."""
    ini = (flask_request.args.get("ini") or _pg_trk_default_date()).strip()
    date_iso = ini if re.match(r"^\d{4}-\d{2}-\d{2}$", ini) else _pg_trk_default_date()
    ent = _pg_eventos_calc(date_iso)
    return jsonify({"rows": ent["rows"], "disp": ent.get("disp", {}), "ini": date_iso, "fim": date_iso,
                    "total": len(ent["rows"]), "data_ini_hist": "2026-06-01", "progresso": {}})


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
SPV_INV_PARES_FRAC = 0.90   # inversor com mediana < 90% da mediana dos inversores da usina = abaixo dos pares


def _marca_inv_sub(invs):
    """Sinaliza inversores ABAIXO DOS PARES: a régua de string compara cada string com a
    mediana do PRÓPRIO inversor, então um inversor inteiro baixo (ex.: bloco de trackers
    parados — todas as strings em 'sino', não clippam) passa como 'OK'. Aqui marcamos o
    inversor quando sua mediana < SPV_INV_PARES_FRAC × mediana das medianas dos inversores
    PRODUZINDO da usina. Adiciona 'inv_sub' (bool) e 'med_usina' a cada inversor."""
    meds = sorted(i["mediana"] for i in invs if i.get("mediana", 0) > 0)
    med_usina = meds[len(meds) // 2] if meds else 0.0
    for i in invs:
        m = i.get("mediana", 0) or 0
        i["med_usina"] = round(med_usina, 1)
        i["inv_sub"] = bool(med_usina > 0 and m > 0 and m < SPV_INV_PARES_FRAC * med_usina)
    return invs


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


def _spv_analise_inversor(idinv, nome, recs, data, notas, full=False, plant_id=None) -> dict:
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
    # Strings trancadas (MPPT sem string, marcadas à mão no checkbox) saem da curva e da
    # contagem — mesma régua da tabela (_classifica_strings): "fora da contagem de ativas".
    ipv_keys = [k for k in ipv_keys if _str_key(plant_id, idinv, k) not in _trancadas]
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


def _spv_med_usina(ordem) -> float:
    """Mediana da corrente integrada de TODAS as strings ATIVAS da usina (cross-inversor) e
    reescreve pct/sub de cada string vs essa referência — pega o inversor inteiro em baixa
    (todas as strings caem juntas, que vs o PRÓPRIO inversor pareceria ~100% "OK").
    Ver _sunop_str_med_usina. Roda DEPOIS do _marca_inv_sub (que usa a mediana do inversor)."""
    energias = sorted(s["energia"] for inv in ordem for s in inv.get("strings", [])
                      if s.get("ativa") and s.get("energia", 0) > 0)
    med_u = energias[len(energias) // 2] if energias else 0.0
    for inv in ordem:
        ref = med_u if med_u > 0 else inv.get("mediana", 0.0)
        abaixo = 0
        for s in inv.get("strings", []):
            if s.get("ativa") and ref > 0:
                s["sub"] = s["energia"] < ref * SPV_SUB_FRAC
                s["pct"] = round(100.0 * s["energia"] / ref)
                if s["sub"]:
                    abaixo += 1
        inv["abaixo"] = abaixo
        inv["mediana_usina"] = round(med_u, 1)
    return round(med_u, 1)


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


# ── DIAS ANTERIORES: curva de POTÊNCIA por string (fonte: PV Plataforma · trygenerate) ──
#   A API PV não recupera corrente HISTÓRICA por string (custom_query lento/vazio). A PV
#   Plataforma devolve, por inversor, energia/dia + curva de potência por string. O idInversor
#   da Plataforma == idefinversor da API PV (confirmado). type=9 (potência), status=2.
#   HOJE continua na corrente (day_inverter, Ipv); só o histórico usa potência.
def _spv_trygenerate(idinv, data: str) -> dict:
    """Relatório de strings de UM inversor numa data: dados_energia_dia (kWh/string) +
    dados_potencia_string ([{potencia, tsleitura}] por string). {} em qualquer falha."""
    try:
        r = _http().get(f"{PLAT_BASE}/v2/relatorios/trygenerate",
                        params={"idInversor": idinv, "data": data, "type": 9, "status": 2},
                        headers=_plat_headers(), timeout=45)
        if r.status_code != 200:
            return {}
        j = r.json()
        return j if isinstance(j, dict) else {}
    except Exception:
        return {}


def _spv_inversores_hist(idusina, token, plant_nome_api: str) -> list:
    """[(device_id, nome_exibição)] dos inversores reais da usina via plant_devices — p/ datas
    passadas (não dependem de leitura do dia). Mesma régua de _carrega_inversores: nome contém
    'inv', sem x/old/velho/antigo, e — se a usina tem cadastro — só os que estão nele."""
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
        return []
    mapa = EQUIP_NAMES.get(plant_nome_api, {})
    EXCL = ["x", "old", "velho", "antigo"]
    out = []
    for dev_id, api_nome_orig in dev_names.items():
        api_nome = api_nome_orig.lower()
        display = mapa.get(api_nome_orig, api_nome_orig)
        dl = display.lower()
        if "inv" not in api_nome and "inv" not in dl:
            continue
        if any(e in api_nome for e in EXCL) or any(e in dl for e in EXCL):
            continue
        if mapa and api_nome_orig not in mapa:      # device fantasma fora do cadastro
            continue
        out.append((dev_id, display))
    return out


def _spv_analise_inv_potencia(idinv, nome, data, notas, full=False, plant_id=None) -> dict:
    """Igual a _spv_analise_inversor, mas dos DIAS ANTERIORES via trygenerate (potência).
    dados_energia_dia → energia/string (mediana + subperformance); dados_potencia_string → curva (W).
    Retorna None se não há visão de strings p/ o inversor/data."""
    j = _spv_trygenerate(idinv, data)
    energia_dia = (j or {}).get("dados_energia_dia") or {}
    pot = (j or {}).get("dados_potencia_string") or {}
    if not energia_dia:
        return None
    st_keys = sorted(energia_dia.keys(), key=_spv_stnum)
    # trancadas (MPPT sem string, marcadas à mão) saem — ST NN ↔ Ipv n (mesma régua do hoje)
    st_keys = [k for k in st_keys
               if _str_key(plant_id, idinv, f"Ipv{_spv_stnum(k)}") not in _trancadas]
    if not st_keys:
        return None
    energias = [float(energia_dia.get(k) or 0.0) for k in st_keys]
    ativas = _ipv_ativas(energias, em_janela=False)     # energia >> 1 nas reais, ~0 nas inativas
    reais = [k for k, a in zip(st_keys, ativas) if a]
    if not reais:
        return None
    ativa_set = set(reais)
    plot_keys = st_keys if full else reais
    curva = {}
    for k in plot_keys:
        serie = pot.get(k) or []
        step = max(1, len(serie) // 160)                # ~160 pts na curva (igual ao hoje)
        xs, ys = [], []
        for i, p in enumerate(serie):
            if i % step:
                continue
            parts = str(p.get("tsleitura") or "").split()
            hhmm = parts[4][:5] if len(parts) >= 5 and ":" in parts[4] else ""
            xs.append(hhmm)
            ys.append(round(float(p.get("potencia") or 0.0), 1))
        curva[k] = {"x": xs, "y": ys}
    soma = {k: float(energia_dia.get(k) or 0.0) for k in reais}
    vals = sorted(soma.values())
    med = vals[len(vals) // 2] if vals else 0.0
    avg = sum(vals) / len(vals) if vals else 0.0
    strings, abaixo = [], 0
    for k in sorted(plot_keys, key=_spv_stnum):
        ativa = k in ativa_set
        e = float(energia_dia.get(k) or 0.0)
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
            "strings": strings, "curva": curva_fmt, "nota": nota, "unidade": "potencia"}


def _spv_usina_historico(idusina, token, data: str, full: bool) -> dict:
    """Monta o payload da usina p/ DIAS ANTERIORES: potência por string (trygenerate), um
    inversor por vez (paralelo). Mesma estrutura do payload de hoje + unidade='potencia'."""
    plant_nome_api = ""
    try:
        plant_nome_api = next((p["nome"].strip() for p in get_plants(token) if p["id"] == idusina), "")
    except Exception:
        pass
    invs = _spv_inversores_hist(idusina, token, plant_nome_api)
    if not invs:
        return {"idusina": idusina, "data": data, "inversores": [],
                "msg": "Não consegui listar os inversores desta usina (API PV)."}
    notas = _spv_load_notas()
    results = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_spv_analise_inv_potencia, dev_id, nome, data, notas, full, idusina): dev_id
                for dev_id, nome in invs}
        for f in as_completed(futs):
            try:
                rr = f.result()
                if rr:
                    results[rr["id"]] = rr
            except Exception:
                pass
    if not results:
        return {"idusina": idusina, "data": data, "inversores": [], "unidade": "potencia",
                "msg": "Sem dados de strings para esta data na PV Plataforma "
                       "(pode ser token da Plataforma vencido — renove pelo bookmarklet)."}
    ordem = sorted(results.values(),
                   key=lambda x: [int(p) for p in re.findall(r"\d+", x["nome"])] or [9999])
    _marca_inv_sub(ordem)
    med_usina = _spv_med_usina(ordem)
    return {"idusina": idusina, "data": data, "inversores": ordem,
            "total_abaixo": sum(i["abaixo"] for i in ordem),
            "mediana_usina": med_usina, "unidade": "potencia",
            "cache_ts": datetime.now().strftime("%H:%M:%S")}


@app.route("/api/spv/usina/<int:idusina>")
def api_spv_usina(idusina):
    """Inversores da usina + análise de strings. HOJE: corrente (day_inverter, Ipv). DIAS
    ANTERIORES: potência por string (PV Plataforma · trygenerate) — a API PV não recupera
    corrente histórica de string. unidade='corrente' (hoje) / 'potencia' (histórico)."""
    data = (flask_request.args.get("data") or datetime.now().strftime("%d/%m/%Y")).strip()
    force = flask_request.args.get("force", "0") == "1"
    full = flask_request.args.get("full", "0") == "1"   # inclui strings inativas na curva
    key = (idusina, data, full)
    agora = time.time()
    hoje = datetime.now().strftime("%d/%m/%Y")
    if not force:
        ent = _spv_cache.get(key)
        # Dia passado já carregado é IMUTÁVEL → serve do cache p/ sempre (a API PV usa
        # custom_query p/ histórico, lento ~120s; hoje continua com TTL p/ acompanhar ao vivo).
        if ent and ((data != hoje and ent["payload"].get("inversores")) or (agora - ent["ts"]) < CACHE_TTL):
            return jsonify(ent["payload"])
    try:
        token = get_token()
    except Exception as e:
        return jsonify({"idusina": idusina, "data": data, "inversores": [],
                        "msg": f"API PV indisponível: {e}"})
    # DIAS ANTERIORES → potência por string (PV Plataforma · trygenerate). Histórico é imutável:
    # cacheia p/ sempre quando vier com inversores; vazio (token?) não cacheia → retenta depois.
    if data != hoje:
        payload = _spv_usina_historico(idusina, token, data, full)
        if payload.get("inversores"):
            _spv_cache[key] = {"ts": agora, "payload": payload}
        return jsonify(payload)
    # HOJE → corrente via day_inverter (inalterado)
    try:
        records = _spv_day_records(idusina, token, data)
    except Exception as e:
        return jsonify({"idusina": idusina, "data": data, "inversores": [],
                        "msg": f"API PV indisponível: {e}"})
    if not records:
        payload = {"idusina": idusina, "data": data, "inversores": [],
                   "msg": "Sem dados de inversores para esta usina/data (API PV)."}
        if data != hoje:        # histórico vazio/timeout do custom_query → cacheia (TTL) p/ não re-esperar ~120s
            _spv_cache[key] = {"ts": agora, "payload": payload}
        return jsonify(payload)
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
            futs[ex.submit(_spv_analise_inversor, idinv, nome, recs, data, notas, full, idusina)] = idinv
        for f in as_completed(futs):
            try:
                rr = f.result()
                if rr:
                    results[rr["id"]] = rr
            except Exception:
                pass
    ordem = sorted(results.values(),
                   key=lambda x: [int(p) for p in re.findall(r"\d+", x["nome"])] or [9999])
    _marca_inv_sub(ordem)   # sinaliza inversores abaixo da mediana dos pares da usina
    med_usina = _spv_med_usina(ordem)   # pct/sub de cada string vs a USINA inteira (cross-inversor)
    payload = {"idusina": idusina, "data": data, "inversores": ordem,
               "total_abaixo": sum(i["abaixo"] for i in ordem),
               "mediana_usina": med_usina, "unidade": "corrente",
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
    # Logo da Grid no rodapé (horizontal, sobre branco) e no cabeçalho (branco, sobre azul)
    try:
        _logo = _mpimg.imread(os.path.join(_STATIC, "logos", "grid-h-verde-azul.png"))
    except Exception:
        _logo = None
    try:
        _logo_hdr = _mpimg.imread(os.path.join(_STATIC, "logos", "grid-h-branco.png"))
    except Exception:
        _logo_hdr = None
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
                fig.text(0.975, 0.930, f"{tot_abaixo} string(s) abaixo das demais" if tot_abaixo else "Todas as strings OK",
                         color=HDR_LT, fontsize=9, ha="right", va="center")
                # Logo Grid Co. centralizado no cabeçalho (branco sobre o azul)
                if _logo_hdr is not None:
                    _hax = fig.add_axes([0.44, 0.937, 0.12, 0.040]); _hax.axis("off"); _hax.imshow(_logo_hdr)
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
                    _na = iv["abaixo"]
                    status = (f"{_na} string{'s' if _na > 1 else ''} abaixo das demais" if _na else "Todas as strings OK")
                    axt.text(0, 1.0, status, transform=axt.transAxes, va="top", ha="left",
                             fontsize=8, fontweight="bold", color=RED if _na else OK)
                    outs = ", ".join(f"{s['nome']}: {100 - s['pct']}% abaixo"
                                     for s in iv["strings"] if s["sub"] and s.get("pct") is not None) or "nenhuma"
                    y = 0.80
                    axt.text(0, y, "Strings abaixo das demais:", transform=axt.transAxes, va="top", fontsize=7,
                             fontweight="bold", color="#64748b"); y -= 0.115
                    for ln in textwrap.wrap(outs, Wtxt)[:3]:
                        axt.text(0, y, ln, transform=axt.transAxes, va="top", fontsize=6.8, color="#475569"); y -= 0.115
                    y -= 0.05
                    axt.text(0, y, "Motivo:", transform=axt.transAxes, va="top", fontsize=7,
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
                fig.text(0.5, 0.036, "Cinza = strings normais   ·   Vermelha = string abaixo das demais do inversor   ·   critério: >10% abaixo da mediana (corrente acumulada no dia)",
                         color="#94a3b8", fontsize=7.5, ha="center", va="center")
                fig.text(0.975, 0.036, f"Gerado em {agora}", color="#94a3b8", fontsize=7.5, ha="right", va="center")
                pdf.savefig(fig, facecolor="white"); plt.close(fig)
                paginas += 1
    buf.seek(0)
    if paginas == 0:
        return jsonify({"error": "Nada para exportar (selecione ao menos uma usina com inversores)."}), 400
    fname = f"strings_{data.replace('/','-')}.pdf"
    return send_file(buf, as_attachment=True, download_name=fname, mimetype="application/pdf")


def _curva_pdf_response(usinas_payloads, data, so_abaixo=False, fname_prefix="strings"):
    """PDF de curvas de strings (genérico p/ SunOp/PG — MESMO layout do /api/spv/pdf).
    usinas_payloads = lista de (usina_nome, payload{inversores, total_abaixo?}); 3 inv/página."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    import textwrap
    from matplotlib.patches import Rectangle, FancyBboxPatch
    from matplotlib import font_manager as _fm
    import matplotlib.image as _mpimg
    _STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
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
    try:
        _logo = _mpimg.imread(os.path.join(_STATIC, "logos", "grid-h-verde-azul.png"))
    except Exception:
        _logo = None
    try:
        _logo_hdr = _mpimg.imread(os.path.join(_STATIC, "logos", "grid-h-branco.png"))
    except Exception:
        _logo_hdr = None
    plt.rcParams.update({
        "font.family": _pdf_font, "axes.edgecolor": "#cbd5e1", "axes.linewidth": 0.7,
        "axes.labelcolor": "#64748b", "xtick.color": "#94a3b8", "ytick.color": "#94a3b8",
        "text.color": "#1f2937",
    })
    HDR, HDR_LT = "#1d4ed8", "#bfdbfe"
    GRAY_LN, RED, OK = "#c3cedd", "#dc2626", "#16a34a"
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    CHUNK, Wtxt = 3, 46
    paginas = 0
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        for usina_nome, payload in usinas_payloads:
            invs = (payload or {}).get("inversores", [])
            if so_abaixo:
                invs = [iv for iv in invs if iv.get("abaixo")]
            if not invs:
                continue
            tot_abaixo = (payload or {}).get("total_abaixo") or sum((iv.get("abaixo") or 0) for iv in invs)
            for ini in range(0, len(invs), CHUNK):
                grupo = invs[ini:ini + CHUNK]
                fig = plt.figure(figsize=(11.69, 8.27))
                fig.patches.append(Rectangle((0, 0.915), 1, 0.085, transform=fig.transFigure,
                                             facecolor=HDR, edgecolor="none", zorder=-1))
                fig.text(0.028, 0.953, usina_nome, color="white", fontsize=16, fontweight="bold", va="center")
                fig.text(0.028, 0.928, "Relatório de Strings  ·  corrente de cada string ao longo do dia",
                         color=HDR_LT, fontsize=8.5, va="center")
                fig.text(0.975, 0.957, data, color="white", fontsize=11.5, fontweight="bold", ha="right", va="center")
                fig.text(0.975, 0.930, f"{tot_abaixo} string(s) abaixo das demais" if tot_abaixo else "Todas as strings OK",
                         color=HDR_LT, fontsize=9, ha="right", va="center")
                if _logo_hdr is not None:
                    _hax = fig.add_axes([0.44, 0.937, 0.12, 0.040]); _hax.axis("off"); _hax.imshow(_logo_hdr)
                if len(invs) > CHUNK:
                    fig.text(0.5, 0.892, f"Inversores {ini+1}-{ini+len(grupo)} de {len(invs)}",
                             color="#94a3b8", fontsize=8, ha="center", style="italic")
                gs = fig.add_gridspec(2, CHUNK, height_ratios=[2.0, 1.6], hspace=0.40, wspace=0.16,
                                      left=0.034, right=0.985, top=0.85, bottom=0.09)
                for j in range(CHUNK):
                    axc = fig.add_subplot(gs[0, j]); axt = fig.add_subplot(gs[1, j]); axt.axis("off")
                    if j >= len(grupo):
                        axc.axis("off"); continue
                    iv = grupo[j]
                    pc, ptx = axc.get_position(), axt.get_position()
                    fig.add_artist(FancyBboxPatch(
                        (pc.x0 - 0.013, ptx.y0 - 0.016),
                        (pc.x1 - pc.x0) + 0.026, (pc.y1 - ptx.y0) + 0.052,
                        boxstyle="round,pad=0,rounding_size=0.012", transform=fig.transFigure,
                        facecolor="#fbfcfe", edgecolor="#e6e9f0", linewidth=0.9, zorder=-3))
                    _cx0 = pc.x0 - 0.013; _cw = (pc.x1 - pc.x0) + 0.026
                    _ctop = (ptx.y0 - 0.016) + (pc.y1 - ptx.y0) + 0.052
                    fig.add_artist(Rectangle((_cx0 + 0.006, _ctop - 0.007), _cw - 0.012, 0.005,
                                   transform=fig.transFigure, facecolor=(RED if iv.get("abaixo") else OK),
                                   edgecolor="none", zorder=-2))
                    curva = iv.get("curva") or {}
                    subnames = {s["nome"] for s in (iv.get("strings") or []) if s.get("sub")}
                    xs = next(iter(curva.values()))["x"] if curva else []
                    for st, c in curva.items():
                        if st not in subnames:
                            axc.plot(c["x"], c["y"], lw=0.5, color=GRAY_LN, alpha=0.85, zorder=1)
                    for st, c in curva.items():
                        if st in subnames:
                            axc.plot(c["x"], c["y"], lw=1.3, color=RED, zorder=3)
                    axc.set_title(iv.get("nome", ""), fontsize=10, fontweight="bold", pad=7,
                                  color=RED if iv.get("abaixo") else "#0f172a")
                    axc.spines[["top", "right"]].set_visible(False)
                    axc.grid(axis="y", color="#eef2f7", lw=0.8, zorder=0)
                    axc.set_ylim(bottom=0); axc.margins(x=0.01)
                    axc.tick_params(labelsize=6.5, length=2, color="#cbd5e1")
                    if xs:
                        step = max(1, len(xs) // 4)
                        axc.set_xticks(range(0, len(xs), step)); axc.set_xticklabels(xs[::step], fontsize=6.5)
                    _na = iv.get("abaixo") or 0
                    status = (f"{_na} string{'s' if _na > 1 else ''} abaixo das demais" if _na else "Todas as strings OK")
                    axt.text(0, 1.0, status, transform=axt.transAxes, va="top", ha="left",
                             fontsize=8, fontweight="bold", color=RED if _na else OK)
                    outs = ", ".join(f"{s['nome']}: {100 - s['pct']}% abaixo"
                                     for s in (iv.get("strings") or []) if s.get("sub") and s.get("pct") is not None) or "nenhuma"
                    y = 0.80
                    axt.text(0, y, "Strings abaixo das demais:", transform=axt.transAxes, va="top", fontsize=7,
                             fontweight="bold", color="#64748b"); y -= 0.115
                    for ln in textwrap.wrap(outs, Wtxt)[:3]:
                        axt.text(0, y, ln, transform=axt.transAxes, va="top", fontsize=6.8, color="#475569"); y -= 0.115
                    y -= 0.05
                    axt.text(0, y, "Motivo:", transform=axt.transAxes, va="top", fontsize=7,
                             fontweight="bold", color="#64748b"); y -= 0.115
                    for ln in textwrap.wrap(iv.get("nota") or "sem observacao registrada", Wtxt)[:3]:
                        axt.text(0, y, ln, transform=axt.transAxes, va="top", fontsize=6.8,
                                 color="#7c3aed" if iv.get("nota") else "#9ca3af"); y -= 0.115
                fig.patches.append(Rectangle((0.052, 0.062), 0.923, 0.0012, transform=fig.transFigure,
                                             facecolor="#e5e7eb", edgecolor="none"))
                if _logo is not None:
                    _lax = fig.add_axes([0.028, 0.016, 0.12, 0.038]); _lax.axis("off"); _lax.imshow(_logo)
                else:
                    fig.text(0.028, 0.036, "Grid Co.  ·  Monitoramento O&M", color="#94a3b8", fontsize=7.5, va="center")
                fig.text(0.5, 0.036, "Cinza = strings normais   ·   Vermelha = string abaixo das demais do inversor",
                         color="#94a3b8", fontsize=7.5, ha="center", va="center")
                fig.text(0.975, 0.036, f"Gerado em {agora}", color="#94a3b8", fontsize=7.5, ha="right", va="center")
                pdf.savefig(fig, facecolor="white"); plt.close(fig)
                paginas += 1
    buf.seek(0)
    if paginas == 0:
        return jsonify({"error": "Nada para exportar (nenhuma usina com inversores)."}), 400
    fname = f"{fname_prefix}_{data.replace('/','-')}.pdf"
    return send_file(buf, as_attachment=True, download_name=fname, mimetype="application/pdf")


@app.route("/api/sunop/pdf")
def api_sunop_pdf():
    """PDF de curvas de strings do SunOp (mesmo layout do /api/spv/pdf)."""
    dia = (flask_request.args.get("data") or datetime.now().strftime("%Y-%m-%d")).strip()
    if re.match(r"^\d{2}/\d{2}/\d{4}$", dia):
        dia = datetime.strptime(dia, "%d/%m/%Y").strftime("%Y-%m-%d")
    data_br = datetime.strptime(dia, "%Y-%m-%d").strftime("%d/%m/%Y")
    so_abaixo = flask_request.args.get("soabaixo", "0") == "1"
    sel = (flask_request.args.get("usinas") or "").strip()
    ensure_sunop_meta()
    plants = [p for p, m in _sunop_meta.items() if m.get("inv_strings")]
    if sel:
        want = set(sel.split(","))
        plants = [p for p in plants if p in want]
    usinas = sorted(((p, USINA_DISPLAY.get(p, p)) for p in plants), key=lambda x: x[1])
    payloads = [(nome, _sunop_strings_curva(p, dia)) for p, nome in usinas]
    return _curva_pdf_response(payloads, data_br, so_abaixo, "strings_sunop")


@app.route("/api/pg/pdf")
def api_pg_pdf():
    """PDF de curvas de strings do PG/Banco de Dados (mesmo layout do /api/spv/pdf)."""
    dia = (flask_request.args.get("data") or datetime.now().strftime("%Y-%m-%d")).strip()
    if re.match(r"^\d{2}/\d{2}/\d{4}$", dia):
        dia = datetime.strptime(dia, "%d/%m/%Y").strftime("%Y-%m-%d")
    data_br = datetime.strptime(dia, "%Y-%m-%d").strftime("%d/%m/%Y")
    so_abaixo = flask_request.args.get("soabaixo", "0") == "1"
    sel = (flask_request.args.get("usinas") or "").strip()
    summary, _ = _pg_get_snapshot()
    usinas = [(r["plant_id"], r["usina"]) for r in summary]
    if sel:
        want = set(sel.split(","))
        usinas = [u for u in usinas if str(u[0]) in want]
    payloads = [(nome, _pg_strings_curva(int(pid), dia)) for pid, nome in usinas]
    return _curva_pdf_response(payloads, data_br, so_abaixo, "strings_pg")


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
    """Mantém os tokens SunOp (gridco/axis) sempre vivos: chama get_sunop_token(inst) (valida e,
    se preciso, renova via /refresh_token) a cada 6 h — bem dentro da janela de ~7 dias.
    Enquanto o servidor estiver de pé, nunca precisa colar token novo manualmente."""
    print("[SunOp] keep-alive iniciado (renova tokens gridco/axis a cada 6 h)")
    while True:
        time.sleep(21600)   # 6 horas
        for inst in ("gridco", "axis"):
            if not _si(inst)["token"]["token"]:
                continue
            try:
                get_sunop_token(inst)
            except Exception as e:
                print(f"[SunOp:{inst}] keep-alive erro: {e}")


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
        # Disponibilidade por TEMPO (Ocorrências) de HOJE — aquece ANTES dos overviews de trackers
        # (abaixo), senão o overview reconstrói com "disponibilidade_tempo" vazio (cache de eventos
        # ainda frio) e fica preso nesse payload até o próximo ciclo (SWR não invalida sozinho).
        for nome, fn in (("PG disponibilidade", _pg_disp_hoje), ("SunOp disponibilidade", lambda: _sunop_disp_hoje("gridco")),
                         ("Axis disponibilidade", lambda: _sunop_disp_hoje("axis")), ("2C disponibilidade", _owen_disp_hoje)):
            try:
                fn()
            except Exception as e:
                print(f"[prewarm] {nome} falhou: {e}")
        outros = [
            ("ETM",            _etm_cache,           _build_etm_payload),
            ("ETM análise",    _etm_analise_cache,   _build_etm_analise_payload),
            ("SunOp",          _sunop_cache,         _build_sunop_payload),
            ("Axis",           _axis_cache,          lambda: _build_sunop_payload("axis")),
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
        try:
            _thopen_prod_build()              # geração mensal das carteiras não-PG (BD_Thopen) p/ o gerencial
        except Exception as e:
            print(f"[prewarm] Thopen prod falhou: {e}")
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
            "trk_parada": _trk_parada_total,
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
    saved_par = data.get("trk_parada")
    if isinstance(saved_par, dict) and saved_par.get("plants") is not None:
        _trk_parada_total.update(saved_par)
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


def _trk_parada_loop():
    """Mantém o estado 'desde quando todos parados' atualizado em background — sem isto o 'desde'
    só conta enquanto alguém abre /api/pv/trackers/parada, o que atrasa a hora real do travamento."""
    while True:
        try:
            time.sleep(60)
            if _pv_trk_plant:                     # só reconcilia se o overview já populou o cache
                _trk_parada_reconcilia()
        except Exception as e:
            print(f"[trk_parada_loop] falhou: {e}")


def _trk_ev_hoje_loop():
    """Reprocessa o dia atual a cada 30 min — dia parcial muda durante o expediente (eventos
    travou→voltou que aconteceram nas últimas horas só ficam completos depois do retorno). Sem
    isto, a sub-aba "Ocorrências" depende do usuário clicar "Gerar/Atualizar histórico"."""
    time.sleep(120)                               # dá tempo do servidor estabilizar antes da 1ª rodada
    while True:
        try:
            if _plat_token() and _pv_trk_plant and not _trk_ev_prog["running"]:
                hoje = datetime.now().strftime("%Y-%m-%d")
                threading.Thread(target=_trk_ev_backfill, args=(hoje, hoje), daemon=True).start()
        except Exception as e:
            print(f"[trk_ev_hoje_loop] falhou: {e}")
        time.sleep(30 * 60)                       # 30 min


# ── Paliativo do "link fixo": mantém tunnel_url.txt sempre com a URL atual do túnel ──────────────
# Lê o log do cloudflared (qualquer forma de subir o túnel — .bat, PowerShell, auto-restart — grava
# nele) e extrai a ÚLTIMA URL trycloudflare. O os_creator (e a UI) leem esse arquivo. Some o problema
# de "qual o link?" — desde que o túnel grave o log em cloudflared_tunnel.log na pasta do projeto.
_TUNNEL_URL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tunnel_url.txt")
_CF_LOGS = [os.path.join(os.path.dirname(os.path.abspath(__file__)), n)
            for n in ("cloudflared_tunnel.log", "cloudflared_tunnel.out.log")]


def _tunnel_url_atual() -> str:
    try:
        if os.path.exists(_TUNNEL_URL_FILE):
            with open(_TUNNEL_URL_FILE, encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return ""


def _tunnel_url_loop():
    last = _tunnel_url_atual()
    while True:
        try:
            txt = ""
            for p in _CF_LOGS:
                if os.path.exists(p):
                    with open(p, encoding="utf-8", errors="ignore") as f:
                        txt += f.read()
            achados = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", txt)
            if achados and achados[-1] != last:
                last = achados[-1]
                with open(_TUNNEL_URL_FILE, "w", encoding="utf-8") as f:
                    f.write(last)
                print(f"[tunnel_url] URL atual: {last}")
        except Exception as e:
            print(f"[tunnel_url_loop] falhou: {e}")
        time.sleep(20)


@app.route("/api/tunnel-url")
def api_tunnel_url():
    """URL pública atual do túnel (lida de tunnel_url.txt) — usada pela UI e pelo os_creator."""
    return jsonify({"url": _tunnel_url_atual()})


# ════ FRACTTAL (CMMS de manutenção) — OS por ativo, no drill do inversor ════════════
# OAuth2 client_credentials (credenciais no .env, NUNCA hardcoded; base app.fracttal.com).
# O ativo do inversor resolve por code "{USINA}-INVR{N.M}" (= "Usina Supervisório" + nº do
# display "Inversor N.M") via items/{code} — 1 chamada, sem paginar a base. As OS vêm de
# work_orders?id_item=. Token, resolução de code e OS são cacheados (rate limit 200/min).
FRACTTAL_BASE      = os.environ.get("FRACTTAL_BASE_URL", "https://app.fracttal.com").rstrip("/")
FRACTTAL_CLIENT_ID = os.environ.get("FRACTTAL_CLIENT_ID", "").strip()
FRACTTAL_SECRET    = os.environ.get("FRACTTAL_CLIENT_SECRET", "").strip()
FRACTTAL_ON        = bool(FRACTTAL_CLIENT_ID and FRACTTAL_SECRET)
FRAC_WO_STATUS = {0: "Pendente", 1: "Em andamento", 2: "Concluída", 3: "Concluída",
                  4: "Cancelada", 5: "Aguardando", 6: "Pausada"}
FRAC_OS_TTL    = 600         # OS por ativo: 10 min
FRAC_CODE_TTL  = 12 * 3600   # resolução code→ativo: ativos mudam raramente

_frac_token      = {"token": "", "exp": 0.0}
_frac_token_lock = threading.Lock()
_frac_code_cache = {}        # code -> {"ts": float, "ativo": {id, desc}|None}
_frac_os_cache   = {}        # id_item -> {"ts": float, "data": [...]}


def get_fracttal_token() -> str:
    if _frac_token["token"] and time.time() < _frac_token["exp"]:
        return _frac_token["token"]
    with _frac_token_lock:
        if _frac_token["token"] and time.time() < _frac_token["exp"]:
            return _frac_token["token"]
        r = _http().post(f"{FRACTTAL_BASE}/oauth/token",
                         data={"grant_type": "client_credentials",
                               "client_id": FRACTTAL_CLIENT_ID, "client_secret": FRACTTAL_SECRET},
                         timeout=20)
        d = r.json()
        _frac_token["token"] = d["access_token"]
        _frac_token["exp"]   = time.time() + int(d.get("expires_in", 3600)) - 60
        return _frac_token["token"]


def _frac_get(ep, **params):
    """GET autenticado na Fracttal; trata 401 (re-auth) e 406 (rate limit). None se falhar."""
    url = f"{FRACTTAL_BASE}/api/{ep.lstrip('/')}"
    for _ in range(3):
        h = {"Authorization": f"Bearer {get_fracttal_token()}", "Accept": "application/json"}
        try:
            r = _http().get(url, headers=h, params=params, timeout=30)
        except Exception:
            return None
        if r.status_code == 401:
            _frac_token["token"] = ""          # token venceu → força re-auth
            continue
        if r.status_code == 406:               # rate limit (200/min)
            time.sleep(int(r.headers.get("ratelimit-reset", 5)) or 5)
            continue
        return r.json() if r.status_code == 200 else None
    return None


_frac_bd_map   = {}; _frac_bd_ts = 0.0     # {nome.lower → "Usina Fractall"} do BD
_frac_cb_index = {}; _frac_cb_ts = 0.0     # {description.lower → code-base} da Fracttal


def _frac_fractall_map():
    """{nome_usina.lower → 'Usina Fractall' (description Fracttal)} do BD_Performance. Cacheado.
    Mapeia tanto o display ("Caxambu") quanto o supervisório → a description da Fracttal."""
    global _frac_bd_map, _frac_bd_ts
    if _frac_bd_map and (time.time() - _frac_bd_ts) < FRAC_CODE_TTL:
        return _frac_bd_map
    m = {}
    try:
        df = pd.read_excel(_bd_readable_path(), sheet_name="Equipamentos", header=2)
        sub = df[["Usina", "Usina Supervisório", "Usina Fractall"]].dropna(subset=["Usina Fractall"])
        for _, r in sub.iterrows():
            fr = str(r["Usina Fractall"]).strip()
            for k in (r["Usina"], r["Usina Supervisório"]):
                if pd.notna(k) and str(k).strip():
                    m[str(k).strip().lower()] = fr
    except Exception as e:
        print(f"[fracttal] mapa BD (Usina Fractall) falhou: {e}")
    if m:
        _frac_bd_map, _frac_bd_ts = m, time.time()
    return _frac_bd_map


_FRAC_INDEX_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fracttal_index.json")


def _frac_codebase_index():
    """{groups_1_description.lower → {'cb': code-base, 'site': id_item da raiz}} dos ativos
    Fracttal (item_type=1). 1x (lazy), cacheado. 'cb' de qualquer ativo (regex XXX###); 'site'
    do ativo cujo code é "PREFIXO-CODEBASE" (raiz da usina) — usado p/ contar OS no badge.
    PERSISTIDO em disco: paginar o parque inteiro custa ~150 requests na Fracttal, e o cache em
    memória morria a cada restart do servidor — o arquivo evita repagar dentro do TTL."""
    global _frac_cb_index, _frac_cb_ts
    if _frac_cb_index and (time.time() - _frac_cb_ts) < FRAC_CODE_TTL:
        return _frac_cb_index
    if not _frac_cb_index:                     # boot frio → tenta o índice salvo antes de ir à API
        try:
            with open(_FRAC_INDEX_FILE, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("idx") and (time.time() - d.get("ts", 0)) < FRAC_CODE_TTL:
                _frac_cb_index, _frac_cb_ts = d["idx"], d["ts"]
                return _frac_cb_index
        except Exception:
            pass
    idx, start = {}, 0
    while True:
        d = _frac_get("items/", item_type=1, start=start, limit=200)
        page = (d.get("data") if isinstance(d, dict) else d) or []
        if not page:
            break
        for it in page:
            code = str(it.get("code") or "")
            cb = re.search(r"[A-Z]{3}\d{3}", code)
            g1 = str(it.get("groups_1_description") or "").strip().lower()
            if not (cb and g1):
                continue
            ent = idx.setdefault(g1, {"cb": cb.group(0), "site": None})
            parts = code.split("-")
            if ent["site"] is None and len(parts) == 2 and re.fullmatch(r"[A-Z]{3}\d{3}", parts[1]):
                ent["site"] = it.get("id")
        total = d.get("total") if isinstance(d, dict) else None
        start += len(page)
        if (total and start >= total) or start > 30000:
            break
    if idx:
        _frac_cb_index, _frac_cb_ts = idx, time.time()
        try:
            with open(_FRAC_INDEX_FILE, "w", encoding="utf-8") as f:
                json.dump({"ts": _frac_cb_ts, "idx": idx}, f, ensure_ascii=False)
        except Exception as e:
            print(f"[fracttal] não consegui salvar o índice: {e}")
    elif not _frac_cb_index:                   # API falhou e sem memória → índice salvo mesmo velho
        try:
            with open(_FRAC_INDEX_FILE, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("idx"):
                print("[fracttal] API indisponível — usando índice salvo (stale)")
                _frac_cb_index, _frac_cb_ts = d["idx"], time.time() - FRAC_CODE_TTL + 600
        except Exception:
            pass
    return _frac_cb_index


def _frac_usina_ent(usina):
    """Entrada do índice ({cb, site}) p/ a usina do dashboard: nome → 'Usina Fractall' → índice."""
    desc = _frac_fractall_map().get(str(usina or "").strip().lower())
    return _frac_codebase_index().get(desc.strip().lower()) if desc else None


def _frac_codebase(usina):
    """Code-base Fracttal (ex. CPP100/CXB100) a partir do nome da usina no dashboard. Athon: o
    nome JÁ é o code-base; demais (Thopen…): nome → 'Usina Fractall' (BD) → code-base (índice)."""
    s = str(usina or "").strip()
    if not s:
        return None
    if re.fullmatch(r"[A-Za-z]{3}\d{3}", s):       # já é um code-base (CPP100, TIM100, MAB200…)
        return s.upper()
    ent = _frac_usina_ent(s)
    return ent.get("cb") if ent else None


def _frac_inv_code(usina, inv_disp):
    """Code Fracttal do inversor: "{CODE-BASE}-INVR{N.M}" (N.M do display "Inversor N.M")."""
    m = re.search(r"\d+\.\d+|\d+", str(inv_disp or ""))
    base = _frac_codebase(usina)
    return f"{base}-INVR{m.group(0)}" if (m and base) else None


def _frac_ativo(code):
    """Resolve um code Fracttal → {id, desc} via items/{code} (cacheado). None se não existir."""
    ent = _frac_code_cache.get(code)
    if ent and (time.time() - ent["ts"]) < FRAC_CODE_TTL:
        return ent["ativo"]
    d = _frac_get(f"items/{code}")
    data = (d.get("data") if isinstance(d, dict) else d) or []
    it = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) and data else None)
    ativo = {"id": it.get("id"), "desc": str(it.get("description") or "").split("  ")[0].strip()} if it else None
    _frac_code_cache[code] = {"ts": time.time(), "ativo": ativo}
    return ativo


def _frac_os_de(id_item, n=5):
    """Últimas n OS de um ativo (dedup por folio, mais recentes 1º). Cacheado FRAC_OS_TTL."""
    ent = _frac_os_cache.get(id_item)
    if not (ent and (time.time() - ent["ts"]) < FRAC_OS_TTL):
        d = _frac_get("work_orders/", id_item=id_item, limit=200)
        rows = (d.get("data") if isinstance(d, dict) else d) or []
        seen = {}
        for w in rows:
            seen.setdefault(w.get("wo_folio"), w)
        wos = sorted(seen.values(), key=lambda w: str(w.get("creation_date") or ""), reverse=True)
        data = [{"folio": w.get("wo_folio"),
                 "descricao": str(w.get("description") or "").strip(),
                 "status": FRAC_WO_STATUS.get(w.get("id_status_work_order"), "—"),
                 "aberta": w.get("id_status_work_order") in (0, 1, 5, 6),
                 "criada": str(w.get("creation_date") or "")[:10]} for w in wos]
        ent = {"ts": time.time(), "data": data}
        _frac_os_cache[id_item] = ent
    return ent["data"][:n]


@app.route("/api/fracttal/inversor")
def api_fracttal_inversor():
    """Últimas OS da Fracttal de um inversor do dashboard. ?usina=CPP100&inv=Inversor 6.1[&n=5]"""
    if not FRACTTAL_ON:
        return jsonify({"ok": False, "sem_credencial": True})
    code = _frac_inv_code(flask_request.args.get("usina"), flask_request.args.get("inv"))
    if not code:
        return jsonify({"ok": False, "motivo": "inversor sem número reconhecível"})
    try:
        n = max(1, min(int(flask_request.args.get("n", 5)), 20))
    except (TypeError, ValueError):
        n = 5
    try:
        ativo = _frac_ativo(code)
        if not ativo:
            return jsonify({"ok": False, "motivo": "sem ativo correspondente na Fracttal", "code": code})
        return jsonify({"ok": True, "code": code, "ativo": ativo.get("desc"),
                        "os": _frac_os_de(ativo["id"], n)})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)})


_frac_usina_cache = {}     # usina.lower -> {"ts", "abertas", "total"}


@app.route("/api/fracttal/usina")
def api_fracttal_usina():
    """OS ABERTAS no site da usina (badge no overview). ?usina=CPP100. Conta no nível do site
    (religamentos/verificações da usina); as OS por inversor aparecem no drill de cada um."""
    if not FRACTTAL_ON:
        return jsonify({"ok": False, "sem_credencial": True})
    usina = (flask_request.args.get("usina") or "").strip()
    key = usina.lower()
    ent = _frac_usina_cache.get(key)
    if ent and (time.time() - ent["ts"]) < FRAC_OS_TTL:
        return jsonify({"ok": True, "abertas": ent["abertas"], "total": ent["total"], "os": ent.get("os", [])})
    try:
        info = _frac_usina_ent(usina)
        site = info.get("site") if info else None
        if not site:
            return jsonify({"ok": False, "motivo": "sem site na Fracttal"})
        d = _frac_get("work_orders/", id_item=site, limit=200)
        rows = (d.get("data") if isinstance(d, dict) else d) or []
        folios = {}
        for w in rows:
            folios.setdefault(w.get("wo_folio"), w)
        ab = sorted((w for w in folios.values() if w.get("id_status_work_order") in (0, 1, 5, 6)),
                    key=lambda w: str(w.get("creation_date") or ""), reverse=True)
        os_ab = [{"folio": w.get("wo_folio"), "descricao": str(w.get("description") or "").strip(),
                  "status": FRAC_WO_STATUS.get(w.get("id_status_work_order"), "—"),
                  "criada": str(w.get("creation_date") or "")[:10]} for w in ab]
        res = {"abertas": len(os_ab), "total": len(folios), "os": os_ab}
        _frac_usina_cache[key] = {"ts": time.time(), **res}
        return jsonify({"ok": True, **res})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)})


# ── OS por tipo (corretiva/emergencial/inspeção/religamento[/remoto]) — usina + inversor/cabine ──
FRAC_TIPOS_ALVO = {"corretiva", "corretiva emergencial", "inspeção", "inspecao",
                   "religamento", "religamento remoto"}
_frac_wos_cache = {}     # id_item -> {ts, rows(brutas)}


def _frac_wos_raw(id_item):
    """WOs BRUTAS de um ativo (com tasks_log_task_type_main + creation_date), cacheado FRAC_OS_TTL."""
    ent = _frac_wos_cache.get(id_item)
    if ent and (time.time() - ent["ts"]) < FRAC_OS_TTL:
        return ent["rows"]
    d = _frac_get("work_orders/", id_item=id_item, limit=200)
    rows = (d.get("data") if isinstance(d, dict) else d) or []
    _frac_wos_cache[id_item] = {"ts": time.time(), "rows": rows}
    return rows


def _frac_ativo_curto(ild: str) -> str:
    """Extrai o nome curto do ativo do `items_log_description`. Padrão Fracttal:
    OS de SITE  : 'Thopen - Caxambu 1 - SP  Caxambu São Paulo Brasil { THPN-CXB100 }' → 'Caxambu 1'
    OS de INV   : 'Inversor 2.2 Huawei SUN2000-250KTL-H1   { CPP100-INVR2.2 }' → 'Inversor 2.2'"""
    s = (ild or "").strip()
    if not s:
        return ""
    base = re.sub(r"\s*\{[^}]*\}\s*$", "", s).strip()    # tira " { CODE }"
    nome = re.split(r"\s{2,}", base, maxsplit=1)[0].strip()   # 1º bloco antes do endereço
    m = re.match(r"(Inversor\s+[\d.]+)", nome)
    if m:
        return m.group(1)
    # Descarta segmento de endereço/UF: começa com UF de 2 letras + espaço (ex.: "GO Rodovia BR 040…")
    # ou é só a UF. Isso pega: 'Thopen - Caxambu 1 - SP' → 'Caxambu 1';
    # 'Thopen - Sítio dos Nogueiras 1 - GO Rodovia BR 040…' → 'Sítio dos Nogueiras 1'.
    parts = [p.strip() for p in nome.split(" - ") if p.strip()]
    util = [p for p in parts if not re.match(r"^[A-Z]{2}(\s|$)", p)]
    if util:
        return util[-1]
    if parts:
        return parts[-1]
    return nome[:60]


def _frac_os_filtradas(id_item, mes=None):
    """OSs do ativo nos 5 tipos-alvo (por tasks_log_task_type_main). Mostra: (a) toda OS NÃO encerrada
    (aberta), independentemente da data; (b) as concluídas do mês YYYY-MM pedido. NUNCA mostra
    Canceladas (status 4). Dedup por folio (uma OS pode ter várias tarefas). Abertas em 1º lugar."""
    seen = {}
    for w in _frac_wos_raw(id_item):
        tipo = str(w.get("tasks_log_task_type_main") or "").strip()
        if tipo.lower() not in FRAC_TIPOS_ALVO:
            continue
        st = w.get("id_status_work_order")
        if st == 4:                                  # Cancelada → nunca mostra
            continue
        aberta = st in (0, 1, 5, 6)                  # não encerrada
        cri = str(w.get("creation_date") or "")
        if not aberta and mes and cri[:7] != mes:    # concluída fora do mês → fora
            continue
        fol = w.get("wo_folio")
        if fol in seen:
            continue
        seen[fol] = {"folio": fol, "tipo": tipo, "descricao": str(w.get("description") or "").strip(),
                     "ativo": _frac_ativo_curto(w.get("items_log_description") or ""),
                     "status": FRAC_WO_STATUS.get(st, "—"), "aberta": aberta, "criada": cri[:10]}
    # abertas primeiro, depois por data (mais recente no topo)
    return sorted(seen.values(), key=lambda x: (x["aberta"], x["criada"]), reverse=True)


@app.route("/api/fracttal/os", methods=["POST"])
def api_fracttal_os():
    """OSs (5 tipos) de uma usina no mês — nível usina (site) + por inversor (com cabine).
    Body JSON: {usina, mes:'YYYY-MM'|None, inversores:[nomes display 'Inversor N.M']}."""
    if not FRACTTAL_ON:
        return jsonify({"ok": False, "sem_credencial": True})
    body = flask_request.get_json(silent=True) or {}
    usina = (body.get("usina") or "").strip()
    mes = (body.get("mes") or "").strip() or None
    invs = body.get("inversores") or []
    out = {"ok": True, "usina": usina, "mes": mes, "usina_os": [], "por_inversor": {}}
    try:
        ent = _frac_usina_ent(usina)
        if ent and ent.get("site"):
            out["usina_os"] = _frac_os_filtradas(ent["site"], mes)
    except Exception as e:
        out["erro_site"] = str(e)
    for nome in invs:
        try:
            code = _frac_inv_code(usina, nome)
            ativo = _frac_ativo(code) if code else None
            if not ativo:
                continue
            m = re.search(r"(\d+)\.(\d+)", str(nome))
            out["por_inversor"][nome] = {
                "cabine": int(m.group(1)) if m else None,
                "inv": int(m.group(2)) if m else None,
                "code": code, "os": _frac_os_filtradas(ativo["id"], mes)}
        except Exception:
            continue
    tot = len(out["usina_os"]) + sum(len(v["os"]) for v in out["por_inversor"].values())
    out["total"] = tot
    return jsonify(out)


# ══ RONDA AUTOMÁTICA VIA WHATSAPP — 5 grupos (1 por região), 2 envios/dia ════════════════════════
# Serviço Node local (C:\GridcoWhats\wa_service.js, whatsapp-web.js) segura a sessão do CHIP
# DEDICADO e expõe /send em 127.0.0.1:5099. Config: whats_ronda.json {"enabled", "service_url",
# "token", "horarios": ["07:30","15:30"], "grupos": {"Norte": "1203...@g.us", ...}}.
# Texto = MESMO formato do modal da ronda (rondaTexto/_rondaUsinas do index.html), gerado aqui.
_WHATS_CFG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whats_ronda.json")
_WHATS_SENT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whats_enviados.json")


def _whats_sent_load():
    """Estado de envio da ronda PERSISTIDO em disco: {"YYYY-MM-DD|HH:MM": ["Norte","Sul",...]} =
    regiões já enviadas COM SUCESSO naquele slot. Em disco → sobrevive a restart do servidor (antes
    era só na memória, então um reinício no meio da janela reenviava TUDO). Mantém só o dia de hoje."""
    try:
        with open(_WHATS_SENT_PATH, encoding="utf-8") as f:
            d = json.load(f) or {}
    except Exception:
        d = {}
    hoje = datetime.now().strftime("%Y-%m-%d")
    return {k: list(v) for k, v in d.items() if str(k).startswith(hoje) and isinstance(v, list)}


def _whats_sent_save(d):
    try:
        hoje = datetime.now().strftime("%Y-%m-%d")
        d = {k: sorted(set(v)) for k, v in d.items() if str(k).startswith(hoje)}
        with open(_WHATS_SENT_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[ronda-whats] não gravei whats_enviados.json: {e}")


# {key: [regiões enviadas com sucesso]} — carregado do disco no boot (retoma o dia sem reenviar)
_whats_state = {"enviados": _whats_sent_load()}


def _whats_cfg():
    try:
        with open(_WHATS_CFG_PATH, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _ronda_ang(v):
    return f"{round(v)}°" if isinstance(v, (int, float)) else "—"


def _ronda_parados_all(force=True):
    """Parados de TODAS as fontes em paralelo — MESMOS critérios da subaba 'Trackers parados
    (agora)' (as próprias funções _*_parados_rows) + lista de fontes que falharam."""
    partes, falhas = [], []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(_pv_parados_rows, force): "API PV",
                ex.submit(_pg_parados_rows, force): "Thopen",
                ex.submit(_sunop_parados_rows, "gridco", force): "Athon",
                ex.submit(_sunop_parados_rows, "axis", force): "Axis",
                ex.submit(_owen_parados_rows, force): "2C"}
        for f in as_completed(futs):
            try:
                partes.extend(f.result() or [])
            except Exception as e:
                falhas.append(futs[f])
                print(f"[ronda-whats] fonte {futs[f]} falhou: {e}")
    vistos, rows = set(), []
    for r in partes:
        k = (_nrm(r.get("usina") or ""), str(r.get("tracker")))
        if k not in vistos:
            vistos.add(k)
            rows.append(r)
    # Usinas EXCLUÍDAS da ronda (whats_ronda.json > "excluir_usinas"): casa por SUBSTRING no nome
    # normalizado — "Salto Pirapora" tira "Salto Pirapora 3" e qualquer unidade futura. Só afeta a
    # RONDA (o dashboard segue mostrando tudo). Reversível editando o JSON: o _whats_cfg relê a cada
    # disparo, sem precisar reiniciar o servidor.
    excl = [_nrm(x) for x in (_whats_cfg().get("excluir_usinas") or []) if str(x).strip()]
    if excl:
        rows = [r for r in rows if not any(e in _nrm(r.get("usina") or "") for e in excl)]
    return rows, falhas


def _ronda_bloco_usinas(rs, ind=""):
    out = []
    for u in sorted({str(r.get("usina") or "?") for r in rs}):
        g = [r for r in rs if str(r.get("usina") or "?") == u]
        out.append(f"{ind}[{u}]  ({len(g)})")
        for r in g:
            inv = f" — {r['inversor']}" if r.get("inversor") else ""
            out.append(f"{ind}- {r.get('tracker')}{inv}  (atual {_ronda_ang(r.get('atual'))} · alvo {_ronda_ang(r.get('alvo'))})")
    return out


def _ronda_texto_regiao(reg, rows, quando, alerta=""):
    n = len(rows)
    linhas = [f"RONDA DE TRACKERS PARADOS — {reg.upper()} — {quando}",
              "Se após o reset o tracker NÃO voltar a operar, avise neste grupo para o time de "
              "Performance abrir uma Ordem de Serviço de inspeção."]
    if alerta:
        linhas.append(alerta)
    linhas.append("")
    if not rows:
        linhas.append("Nenhum tracker parado agora.")
        return "\n".join(linhas)
    linhas.append(f"═══ {reg.upper()} · {n} parado{'s' if n != 1 else ''} ═══")
    if reg == "Sudeste":                              # maior região → sub-divide por cliente/carteira
        por_cli = {}
        for r in rows:
            por_cli.setdefault(r.get("cliente") or "—", []).append(r)
        for c in sorted(por_cli):
            linhas.append(f"\n  ▸ {c}  ({len(por_cli[c])})")
            linhas.extend(_ronda_bloco_usinas(por_cli[c], "    "))
    else:
        linhas.extend(_ronda_bloco_usinas(rows))
    return "\n".join(linhas)


def _whats_send(cfg, grupo_id, texto):
    r = _http().post(cfg.get("service_url", "http://127.0.0.1:5099").rstrip("/") + "/send",
                     json={"para": grupo_id, "texto": texto},
                     headers={"x-token": cfg.get("token", "")}, timeout=90)
    try:
        ok = r.status_code == 200 and bool((r.json() or {}).get("ok"))
    except Exception:
        ok = False
    return ok, (r.text or "")[:200]


def _ronda_whats_disparo(slot_label, so_regiao=None, destino=None, pular_regioes=None, confirmar=True):
    """destino: override do id de envio (ex.: número do Levi p/ testar o FORMATO sem incomodar o grupo
    real; None = grupos do config). pular_regioes: regiões JÁ enviadas com sucesso neste slot — NÃO
    reenvia (evita duplicar quem já recebeu na retentativa). confirmar: envia o resumo p/ o admin."""
    cfg = _whats_cfg()
    grupos = cfg.get("grupos") or {}
    if not grupos:
        return {"ok": False, "erro": "sem grupos no whats_ronda.json"}
    pular = set(pular_regioes or ())
    rows, falhas = _ronda_parados_all(force=True)
    quando = datetime.now().strftime("%d/%m/%Y %H:%M")
    alerta = ("ATENÇÃO: ronda incompleta — sem resposta de " + ", ".join(falhas)) if falhas else ""
    por_reg = {}
    for r in rows:
        por_reg.setdefault(r.get("regiao") or "Sem região", []).append(r)
    resultados = {}
    for reg, gid in grupos.items():
        if so_regiao and reg != so_regiao:
            continue
        if reg in pular:                              # já enviado com sucesso neste slot → NÃO reenvia
            continue
        texto = _ronda_texto_regiao(reg, por_reg.get(reg, []), quando, alerta)
        try:
            ok, det = _whats_send(cfg, destino or gid, texto)
        except Exception as e:
            ok, det = False, str(e)
        resultados[reg] = {"ok": ok, "trackers": len(por_reg.get(reg, [])),
                           "detalhe": None if ok else det}
        print(f"[ronda-whats] {slot_label} → {reg}: {'OK' if ok else 'FALHOU ' + str(det)}")
    # confirmação p/ o admin (pedido do Levi 06/07): resumo do que foi enviado, no número dele.
    # Em teste com destino override, só confirma se o destino É o próprio admin (senão duplica).
    conf = (cfg.get("confirmar_para") or "").strip()
    if confirmar and conf and resultados and (not destino or str(destino).replace("+", "").replace(" ", "") == conf):
        ok_n = sum(1 for v in resultados.values() if v["ok"])
        lin = [f"✅ Ronda {slot_label} · {quando} — {ok_n}/{len(resultados)} grupo(s) OK"]
        for reg, v in sorted(resultados.items()):
            lin.append((" • ✅ " if v["ok"] else " • ❌ ") + f"{reg}: {v['trackers']} tracker(s)"
                       + ("" if v["ok"] else f" — FALHOU: {str(v['detalhe'])[:80]}"))
        if falhas:
            lin.append("⚠️ Fontes sem resposta: " + ", ".join(falhas))
        try:
            _whats_send(cfg, conf, "\n".join(lin))
        except Exception as e:
            print(f"[ronda-whats] confirmação p/ admin falhou: {e}")
    return {"ok": bool(resultados) and all(v["ok"] for v in resultados.values()),
            "resultados": resultados, "fontes_falharam": falhas}


RONDA_GRACE_MIN = 15   # min após o horário do slot em que a ronda ainda RETENTA se o envio falhou


def _ronda_whats_loop():
    """Dispara nos horários do config. CORREÇÃO 08/07 (Levi: a ronda das 08:25 falhou — navegador do
    whatsapp-web.js travou — mas o estado marcou 'enviado' e não retentou): marca 'ok' SÓ depois do
    envio CONFIRMAR (o loop é síncrono → o disparo bloqueia, não há overlap); se falhar, RETENTA a
    cada 30s até RONDA_GRACE_MIN após o horário. Assim o status reflete a verdade e um serviço que
    piscou é reenviado. enabled=false = dormindo."""
    time.sleep(120)                                   # deixa o boot aquecer caches
    while True:
        try:
            cfg = _whats_cfg()
            if cfg.get("enabled"):
                agora = datetime.now()
                hoje = agora.strftime("%Y-%m-%d")
                now_min = agora.hour * 60 + agora.minute
                todas_regs = set((cfg.get("grupos") or {}).keys())
                for slot in (cfg.get("horarios") or []):
                    key = hoje + "|" + slot
                    ja = set(_whats_state["enviados"].get(key, []))
                    if todas_regs and ja >= todas_regs:
                        continue                       # slot COMPLETO (todos os grupos) → nada a fazer
                    try:
                        _sh, _sm = map(int, slot.split(":")); slot_min = _sh * 60 + _sm
                    except Exception:
                        continue
                    if slot_min <= now_min <= slot_min + RONDA_GRACE_MIN:
                        # envia SÓ os grupos que ainda NÃO receberam (nunca reenvia quem já recebeu na
                        # retentativa) e persiste em disco (restart no meio da janela não reenvia).
                        res = _ronda_whats_disparo(slot, pular_regioes=ja, confirmar=False)
                        novos = [r for r, v in (res.get("resultados") or {}).items() if v.get("ok")]
                        if novos:
                            ja |= set(novos)
                            _whats_state["enviados"][key] = sorted(ja)
                            _whats_sent_save(_whats_state["enviados"])
                        if todas_regs and ja >= todas_regs:
                            print(f"[ronda-whats] {slot} enviada OK (todos os {len(todas_regs)} grupos)")
                            conf = (cfg.get("confirmar_para") or "").strip()
                            if conf:                   # resumo p/ o admin 1x só (slot já fica marcado)
                                ffalh = res.get("fontes_falharam") or []
                                msg = (f"✅ Ronda {slot} enviada · {agora:%d/%m/%Y %H:%M} — "
                                       f"{len(todas_regs)} grupos OK"
                                       + (f"\n⚠️ Fontes sem resposta: {', '.join(ffalh)}" if ffalh else ""))
                                try: _whats_send(cfg, conf, msg)
                                except Exception: pass
                        else:
                            print(f"[ronda-whats] {slot} parcial — faltam {sorted(todas_regs - ja)}, "
                                  f"retenta até +{RONDA_GRACE_MIN}min")
                        break                          # 1 disparo por ciclo (é síncrono, evita 2 slots juntos)
        except Exception as e:
            print(f"[ronda-whats] loop: {e}")
        time.sleep(30)


def _whats_service_restart():
    """Reergue o serviço WhatsApp (C:\\GridcoWhats): mata os chromes ZUMBIS do GridcoWhats + o node,
    remove o lock do perfil e reinicia o node. MESMA receita do fix manual (detached Frame deixa o
    node vivo mas quebrado + ~7 chromes zumbis segurando o lock do perfil). True se o comando rodou."""
    ps = (
        "Get-CimInstance Win32_Process -Filter \"name='chrome.exe'\" | "
        "Where-Object { $_.CommandLine -match 'GridcoWhats' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; "
        "Get-CimInstance Win32_Process -Filter \"name='node.exe'\" | "
        "Where-Object { $_.CommandLine -match 'wa_service' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; "
        "Start-Sleep -Seconds 2; "
        "Remove-Item 'C:\\GridcoWhats\\session\\session\\lockfile' -Force -ErrorAction SilentlyContinue; "
        "Start-Process -FilePath 'C:\\Program Files\\nodejs\\node.exe' -ArgumentList 'wa_service.js' "
        "-WorkingDirectory 'C:\\GridcoWhats' -WindowStyle Hidden "
        "-RedirectStandardOutput 'C:\\GridcoWhats\\wa_service.out.log' "
        "-RedirectStandardError 'C:\\GridcoWhats\\wa_service.err.log'"
    )
    try:
        # CREATE_NO_WINDOW: não pisca janela de console ao chamar o powershell (rodamos sob pythonw).
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=45, capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        return True
    except Exception as e:
        print(f"[whats-watchdog] restart falhou: {e}")
        return False


_whats_wd_state = {"ultimo_restart": 0.0, "restarts_hoje": 0, "dia": "", "notif_pend": None}


def _whats_watchdog_loop():
    """Vigia o serviço WhatsApp: a cada 3 min sonda /health (getState ATIVO — pega o 'detached Frame'
    que o /status esconde). QUEBRADO + enabled → reergue o serviço sozinho NA HORA. A notificação ao
    admin sai no PRÓXIMO ciclo já saudável (a sessão precisa re-sincronizar o LID do nº avulso após o
    restart; enviar na hora cai em erro silencioso). Cooldown de 5 min entre restarts. Criado 08/07
    após 2 quedas no dia (08:25 e 13:15 — navegador do whatsapp-web.js travou e a ronda falhou calada)."""
    time.sleep(200)                                   # não concorre com o boot
    while True:
        try:
            cfg = _whats_cfg()
            if cfg.get("enabled"):
                url = cfg.get("service_url", "http://127.0.0.1:5099").rstrip("/")
                tok = cfg.get("token", "")
                try:
                    h = _http().get(url + "/health", headers={"x-token": tok}, timeout=15)
                    broken = (h.status_code != 200) or (not (h.json() or {}).get("ok"))
                except Exception:
                    broken = True                     # timeout/sem resposta = travado ou caído
                agora = time.time()
                if broken and (agora - _whats_wd_state["ultimo_restart"]) > 300:
                    print("[whats-watchdog] serviço QUEBRADO (health falhou) — reiniciando...")
                    _whats_wd_state["ultimo_restart"] = agora
                    hoje = datetime.now().strftime("%Y-%m-%d")
                    if _whats_wd_state["dia"] != hoje:
                        _whats_wd_state.update({"dia": hoje, "restarts_hoje": 0})
                    _whats_wd_state["restarts_hoje"] += 1
                    _whats_service_restart()
                    _whats_wd_state["notif_pend"] = (datetime.now().strftime("%H:%M"),
                                                     _whats_wd_state["restarts_hoje"])
                elif _whats_wd_state["notif_pend"] and not broken:
                    # serviço saudável de novo (sessão já aquecida) → agora sim avisa o admin
                    quando, n = _whats_wd_state["notif_pend"]
                    conf = (cfg.get("confirmar_para") or "").strip()
                    if conf:
                        try:
                            _whats_send(cfg, conf, f"[watchdog] O serviço da ronda TRAVOU (navegador) "
                                        f"por volta das {quando} e foi reiniciado automaticamente. "
                                        f"Envios já normalizados (restart nº {n} hoje).")
                        except Exception:
                            pass
                    _whats_wd_state["notif_pend"] = None
        except Exception as e:
            print(f"[whats-watchdog] loop: {e}")
        time.sleep(180)


@app.route("/api/ronda/whats/status")
def api_ronda_whats_status():
    cfg = _whats_cfg()
    try:
        svc = _http().get(cfg.get("service_url", "http://127.0.0.1:5099").rstrip("/") + "/status",
                          headers={"x-token": cfg.get("token", "")}, timeout=8).json()
    except Exception as e:
        svc = {"ok": False, "erro": f"serviço WhatsApp fora do ar ({e})"}
    gset = set((cfg.get("grupos") or {}).keys())
    hoje = datetime.now().strftime("%Y-%m-%d")
    env = {k: set(v) for k, v in _whats_state["enviados"].items() if k.startswith(hoje)}
    return jsonify({"enabled": bool(cfg.get("enabled")), "horarios": cfg.get("horarios"),
                    "grupos": sorted(gset), "servico": svc,
                    "enviados_hoje": sorted(k for k, v in env.items() if gset and v >= gset),
                    "parciais_hoje": {k: sorted(gset - v) for k, v in env.items()
                                      if gset and not (v >= gset)}})


@app.route("/api/ronda/whats/grupos")
def api_ronda_whats_grupos():
    """Lista os grupos visíveis pela sessão do chip — p/ copiar os ids pro whats_ronda.json."""
    cfg = _whats_cfg()
    try:
        return jsonify(_http().get(cfg.get("service_url", "http://127.0.0.1:5099").rstrip("/") + "/grupos",
                                   headers={"x-token": cfg.get("token", "")}, timeout=30).json())
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 502


@app.route("/api/ronda/whats/testar", methods=["POST"])
def api_ronda_whats_testar():
    """Envia a ronda AGORA (todas as regiões, ou {'regiao': 'Norte'} p/ uma só).
    {'para': '55...'} = destino de TESTE (número/id) em vez do grupo real."""
    body = flask_request.get_json(silent=True) or {}
    return jsonify(_ronda_whats_disparo("teste-manual", so_regiao=(body.get("regiao") or None),
                                        destino=(body.get("para") or None)))


@app.route("/api/ronda/whats/preview")
def api_ronda_whats_preview():
    """Texto EXATO da ronda por região SEM enviar nada (p/ conferir o que os grupos receberam).
    ?regiao=Sul p/ uma; sem regiao = todas. force=1 recoleta (senão usa o cache quente)."""
    so = (flask_request.args.get("regiao") or "").strip() or None
    rows, falhas = _ronda_parados_all(force=flask_request.args.get("force") == "1")
    quando = datetime.now().strftime("%d/%m/%Y %H:%M")
    alerta = ("ATENÇÃO: ronda incompleta — sem resposta de " + ", ".join(falhas)) if falhas else ""
    por_reg = {}
    for r in rows:
        por_reg.setdefault(r.get("regiao") or "Sem região", []).append(r)
    regs = [so] if so else list((_whats_cfg().get("grupos") or {}).keys())
    return jsonify({"quando": quando, "fontes_falharam": falhas,
                    "textos": {reg: _ronda_texto_regiao(reg, por_reg.get(reg, []), quando, alerta)
                               for reg in regs}})


if __name__ == "__main__":
    _cache_load()
    _trk_ev_load()
    threading.Thread(target=_ronda_whats_loop, daemon=True).start()
    threading.Thread(target=_whats_watchdog_loop, daemon=True).start()   # reergue o wa_service se travar
    threading.Thread(target=_owen_loop, daemon=True).start()
    threading.Thread(target=_sunop_keepalive_loop, daemon=True).start()
    threading.Thread(target=_prewarm_loop, daemon=True).start()
    threading.Thread(target=_persist_loop, daemon=True).start()
    threading.Thread(target=_trk_parada_loop, daemon=True).start()
    threading.Thread(target=_trk_ev_hoje_loop, daemon=True).start()
    threading.Thread(target=_tunnel_url_loop, daemon=True).start()
    # aquece o gerencial no boot (PR/meta por usina) — sem isso, logo após restart o Painel NOC
    # abre com anomalias SEM a linha de PR (gerencial frio) até o 1º ciclo de warm. A 1ª chamada
    # dispara os warms de BD_Performance/BD_Thopen em background; a 2ª (forçada) consolida.
    def _ger_prewarm():
        try:
            _gerencial_payload()
            time.sleep(90)
            _gerencial_payload(force=True)
            print("[prewarm] gerencial aquecido")
        except Exception as e:
            print(f"[prewarm] gerencial falhou: {e}")
    threading.Thread(target=_ger_prewarm, daemon=True).start()
    try:
        from waitress import serve
        print("[server] waitress em http://0.0.0.0:5050 (threads=16)")
        serve(app, host="0.0.0.0", port=5050, threads=16)
    except ImportError:
        print("[server] waitress não instalado — usando o servidor de dev do Flask")
        app.run(debug=False, port=5050, threaded=True)
