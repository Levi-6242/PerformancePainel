"""api.py — acesso à API REST do Fracttal One.

Autenticação: OAuth2 client_credentials (FRACTTAL_CLIENT_ID/SECRET) — mesmo método do
dashboard. Alternativamente, um token Bearer direto via FRACTTAL_TOKEN (expira ~1h).

CRIAÇÃO DE OS: o REST /api/work_orders é baseado em referência de tarefa (não cria OS de texto
livre). A OS completa é criada pelo RPC interno (tasks.tasks_noscheduled_react_insert via
app.fracttal.com/rpc/proxy), igual ao web app — ver create_os_rpc abaixo. Esse RPC é autenticado
pelo JWT do LOGIN (sessão do usuário), colado em fracttal_login.txt (gitignored, expira ~12h).
As leituras (ativos/pessoal) continuam pelo OAuth client_credentials. IDs centralizados em CONFIG.
"""
import os
import sys
import json
import time
import uuid
import base64
import shutil
import hashlib
import threading
import requests
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

try:                       # cofre do SO (Windows Credential Manager) — opcional
    import keyring
    _HAS_KEYRING = True
except Exception:
    _HAS_KEYRING = False

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

BASE          = os.environ.get("FRACTTAL_BASE_URL", "https://app.fracttal.com").rstrip("/")
CLIENT_ID     = os.environ.get("FRACTTAL_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("FRACTTAL_CLIENT_SECRET", "").strip()
STATIC_TOKEN  = os.environ.get("FRACTTAL_TOKEN", "").strip()

# ── Config do Fracttal (AJUSTAR conforme a conta — ver comentários) ───────────
# Responsáveis permitidos no Step 4 (filtro por nome no /api/personnel).
RESPONSAVEIS = ["Roger Lélis", "Gabriela Dias", "Ana Patrícia", "Levi Maia"]

# Tipo de tarefa (Step 2) → id_task_type_main do Fracttal. Descobertos via GET /api/tasks/types/
# (campos id_task_type_main + tasks_types_main_description). Referência completa da conta 4987.
# Mostramos TODOS os tipos disponíveis (sem filtro) — a ordem aqui é a ordem do dropdown.
TASK_TYPE_MAIN = {
    "Corretiva":             43885,
    "Corretiva Emergencial": 45742,
    "Preventiva":            43886,
    "Preditiva":             43887,
    "Inspeção":              43889,
    "Handover":              43888,
    "Administrativa":        45606,
}
TASK_TYPES = list(TASK_TYPE_MAIN.keys())   # opções do dropdown "Tipo de Tarefa" (Step 2)

# Criticidade → id_priorities (1=Muito alto, 2=Alto, 3=Médio, 4=Baixo, 5=Muito baixo).
# Confirmado pela cURL de criação. O usuário escolhe no dropdown; default = Médio (3).
ID_PRIORITIES = 2                              # fallback p/ chamadas antigas (clone) sem criticidade
CRITICIDADES = [("Muito alto", 1), ("Alto", 2), ("Médio", 3), ("Baixo", 4), ("Muito baixo", 5)]
CRITICIDADE_DEFAULT = 3                         # Médio

# Listas AO VIVO de Tipo de tarefa + Classificação 1/2 (o dropdown estático não traz Religamento etc.)
RPC_TIPOS_MAIN = "tasks.tasks_types_main_list"   # Tipo de tarefa  → id_task_type_main
RPC_TIPOS_C1   = "tasks.tasks_types_list"        # Classificação 1 → id_task_type
RPC_TIPOS_C2   = "tasks.tasks_types_2_list"      # Classificação 2 → id_task_type_2

# ── Endpoints do RPC interno (criação de OS de verdade, igual ao web app) ──────
# O REST OAuth (client_credentials) NÃO cria OS — só Solicitação. A OS completa
# (subtarefas/tipo/etc.) vem do RPC, autenticado pelo JWT do LOGIN (sessão Fracttal).
RPC_TOKEN_URL  = "https://one.fracttal.com/rpc/token"   # renova o JWT da sessão
RPC_PROXY_URL  = "https://app.fracttal.com/rpc/proxy"   # executa tasks.tasks_noscheduled_react_insert
RPC_METHOD     = "tasks.tasks_noscheduled_react_insert"
def _data_dir() -> str:
    """Pasta de dados GRAVÁVEL do usuário (%APPDATA%/CriarOS-Fracttal). Funciona rodando como
    script OU empacotado em .exe (onde a pasta do app não é gravável)."""
    base = os.environ.get("APPDATA") or os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~")
    d = os.path.join(base, "CriarOS-Fracttal")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


# JWT do login: obtido por fracttal_login() (a pessoa digita e-mail+senha). Guardado em
# %APPDATA%/CriarOS-Fracttal/fracttal_login.txt (gravável no .exe). Expira ~12h. A SENHA NUNCA
# é armazenada. Também aceita FRACTTAL_LOGIN_JWT (.env) como override manual.
LOGIN_JWT_FILE = os.path.join(_data_dir(), "fracttal_login.txt")
RPC_LOGIN_URL  = "https://app.fracttal.com/rpc/login_new"   # e-mail + MD5(senha) → JWT de sessão
RPC_PERSONNEL  = "personnel.personnel_list"                 # pessoal (RPC; campo id = id_responsible)
_KEYRING_SVC   = "os_creator_fracttal"
# Dados da empresa no login (NÃO são segredos — vêm do payload do web app).
ID_COMPANY   = int(os.environ.get("FRACTTAL_ID_COMPANY", "4987"))
ID_SERVER    = os.environ.get("FRACTTAL_ID_SERVER", "AMERICAN")
COMPANY_DESC = os.environ.get("FRACTTAL_COMPANY_DESC", "GRID CO. LTDA")


class FracttalError(Exception):
    """Erro de API com mensagem amigável (já tratada) para exibir na UI."""


class SessionExpired(FracttalError):
    """Sessão do Fracttal morta (token rotacionado/expirado). O app detecta e força novo login."""
    session_expired = True       # marcador lido pelo ApiWorker (sem precisar importar a classe)


# ── Autenticação ──────────────────────────────────────────────────────────────
_tok = {"token": "", "exp": 0.0}
_tok_lock = threading.Lock()


def _get_token() -> str:
    if STATIC_TOKEN:
        return STATIC_TOKEN
    with _tok_lock:
        if _tok["token"] and time.time() < _tok["exp"] - 60:
            return _tok["token"]
        if not (CLIENT_ID and CLIENT_SECRET):
            raise FracttalError("Sem credenciais no .env — defina FRACTTAL_CLIENT_ID e "
                                "FRACTTAL_CLIENT_SECRET (ou FRACTTAL_TOKEN).")
        try:
            r = requests.post(f"{BASE}/oauth/token",
                              data={"grant_type": "client_credentials",
                                    "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
                              timeout=20)
            r.raise_for_status()
            j = r.json()
        except requests.RequestException as e:
            raise FracttalError(f"Não foi possível autenticar no Fracttal: {e}")
        _tok["token"] = j.get("access_token", "")
        _tok["exp"]   = time.time() + float(j.get("expires_in", 3600) or 3600)
        if not _tok["token"]:
            raise FracttalError("Autenticação sem access_token na resposta.")
        return _tok["token"]


def _headers() -> dict:
    return {"Authorization": f"Bearer {_get_token()}",
            "Accept": "application/json", "Content-Type": "application/json"}


def _req(method: str, ep: str, **kw):
    url = f"{BASE}/api/{ep.lstrip('/')}"
    timeout = kw.pop("timeout", 30)
    try:
        r = requests.request(method, url, headers=_headers(), timeout=timeout, **kw)
        if r.status_code == 401 and not STATIC_TOKEN:      # token expirou → renova 1x
            _tok["token"] = ""
            r = requests.request(method, url, headers=_headers(), timeout=timeout, **kw)
        if r.status_code in (406, 429):                    # rate limit → espera e tenta 1x
            time.sleep(float(r.headers.get("ratelimit-reset") or 3))
            r = requests.request(method, url, headers=_headers(), timeout=timeout, **kw)
    except requests.RequestException as e:
        raise FracttalError(f"Erro de conexão com o Fracttal: {e}")
    if r.status_code >= 400:
        raise FracttalError(f"HTTP {r.status_code} — {_extract_error(r)}")
    try:
        return r.json()
    except ValueError:
        return {}


def _extract_error(r) -> str:
    """Mensagem amigável a partir do corpo de erro do Fracttal (inclui campos inválidos)."""
    try:
        j = r.json()
    except ValueError:
        return (r.text or "sem detalhes")[:200]
    if isinstance(j, dict):
        d = j.get("data")
        if isinstance(d, list) and d and isinstance(d[0], dict):
            inv = d[0].get("invalid_fields")
            if inv:
                return "campos obrigatórios faltando: " + ", ".join(
                    f"{f.get('field')} ({f.get('field_message')})" for f in inv)
            if d[0].get("ERROR"):
                return str(d[0]["ERROR"])
        return str(j.get("message") or j)[:200]
    return str(j)[:200]


def _to_iso(ddmmyyyy: str) -> str:
    """'18/06/2026' → '2026-06-18T00:00:00+00:00'. Aceita também ISO já pronto."""
    s = (ddmmyyyy or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%dT00:00:00+00:00")
        except ValueError:
            continue
    return datetime.now().strftime("%Y-%m-%dT00:00:00+00:00")


# ── Leituras (estáveis/testadas) ──────────────────────────────────────────────
def ping():
    """Valida credenciais cedo (1 chamada barata). Lança FracttalError se algo estiver errado."""
    _req("GET", "items/?limit=1")
    return True


# Tipo de equipamento a partir do prefixo do code ({USINA}-{TIPO}{N}).
TYPE_MAP = {
    "INVR": "Inversor", "TRK": "Tracker", "ETKR": "Estrutura Trackers", "SKID": "Skid",
    "CABN": "Cabine", "QGBT": "QGBT", "ESTM": "Estação Meteorológica",
    "TRFR": "Transformador", "TRTP": "Transformador", "TRTC": "Transformador",
    "INFC": "Infraestrutura Civil", "INFE": "Infraestrutura Elétrica", "SOEM": "Sala de O&M",
    "SSEG": "Sistema de Segurança", "SPDA": "SPDA", "SSPV": "Sistema FV", "STRG": "String Box",
}


def _tipo_from_code(code: str, eh_usina: bool):
    """→ (tipo_code, tipo_label). Para o item da usina (sem hierarquia abaixo) → ('','Usina')."""
    if eh_usina:
        return "", "Usina"
    parts = code.split("-")
    if len(parts) >= 2:                       # tipo = ÚLTIMO segmento (robusto p/ code de 2 ou 3 partes:
        alpha = "".join(c for c in parts[-1] if c.isalpha())   # TIM200-CABN4 ou THPN-CGH100-CABN1 → CABN
        if alpha:
            return alpha, TYPE_MAP.get(alpha, alpha)
    return "", "Outro"


def _clean_usina_desc(desc: str) -> str:
    """Nome de usina a partir da descrição do item-usina, sem o '{ CODE }' do final."""
    return (desc.split("{")[0]).strip() or desc


def _build_records(raw: list) -> list:
    """Deriva cliente/usina/tipo de cada ativo (2 passadas) — evita a usina duplicada.
    - Equipamento (parent com ≥2 níveis): usina = 2º nível do parent (nome LIMPO, sem code); tipo pelo code.
    - Item da própria usina (parent só com o cliente; o code aparece no nome): NÃO vira usina duplicada —
      entra como ATIVO de tipo 'Usina', anexado à usina limpa (mapa code-base→usina dos equipamentos).
    - Raiz da organização (sem parent): ignorado no drill-down."""
    parsed, base2usina = [], {}
    for a in raw:
        code = (a.get("code") or "").strip()
        desc = (a.get("description") or "").strip()
        segs = [s.strip() for s in (a.get("parent_description") or "").split("/") if s.strip()]
        parsed.append((a, code, desc, segs))
        if len(segs) >= 2 and code:                       # equipamento → registra a usina limpa do code-base
            cparts = code.split("-")
            base = cparts[-2] if len(cparts) >= 2 else cparts[0]   # penúltimo seg = code-base (CGH100/TIM200)
            if base and segs[1]:
                base2usina.setdefault(base, segs[1])
    out = []
    for a, code, desc, segs in parsed:
        if len(segs) >= 2:                                # equipamento
            cliente, usina = segs[0], segs[1]
            tipo_code, tipo = _tipo_from_code(code, eh_usina=False)
        elif len(segs) == 1:                              # item da usina (code no nome) → tipo 'Usina'
            cliente = segs[0]
            base = code.split("-")[-1] if "-" in code else code      # ATHN-TIM200 → TIM200
            usina = base2usina.get(base) or _clean_usina_desc(desc)
            tipo_code, tipo = "USINA", "Usina"
        else:                                             # raiz da organização → fora do drill-down
            continue
        out.append({"id": a.get("id"), "code": code, "description": desc,
                    "id_parent": a.get("id_parent"), "id_type_item": a.get("id_type_item"),
                    "id_group_task": a.get("id_group_task"),
                    "parent_description": a.get("parent_description"),
                    "cliente": cliente, "usina": usina, "tipo_code": tipo_code, "tipo": tipo,
                    "label": f"{code} — {desc}" if code else desc})
    out.sort(key=lambda x: (x["cliente"].lower(), x["usina"].lower(), x["code"].lower()))
    return out


RPC_ITEMS = "inventories.items_list"   # ativos (RPC, sessão do usuário) — flat com is_tree=false


def _items_params(start: int, limit: int = 200) -> dict:
    return {"filter": [], "sort": [{"property": "id_type_item", "direction": "asc"}], "group": {},
            "page": start // limit + 1, "limit": limit, "start": start, "is_tree": False,
            "node": None, "id_type_item": 0, "id_type_item_not": "", "id_location": None}


def _items_page_rpc(start: int, limit: int = 200) -> list:
    res = _rpc_call(RPC_ITEMS, _items_params(start, limit), timeout=45)
    data = res.get("data") if isinstance(res, dict) else res
    return data if isinstance(data, list) else []


def get_assets() -> list:
    """TODOS os ativos (16k+) via RPC inventories.items_list (is_tree=false, sessão do usuário —
    SEM OAuth). 1ª página dá o total; as demais em paralelo. Cada registro recebe cliente/usina/tipo
    derivados (parent_description + code) p/ o drill-down. Ordenado por cliente+usina+code."""
    first = _rpc_call(RPC_ITEMS, _items_params(0, 200), timeout=45)
    total = int(first.get("total") or 0) if isinstance(first, dict) else 0
    data = list(first.get("data") or []) if isinstance(first, dict) else []
    starts = list(range(200, total, 200))
    if starts:
        res = {}
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = {ex.submit(_items_page_rpc, s): s for s in starts}
            for f in as_completed(futs):
                res[futs[f]] = f.result()
        for s in starts:
            data.extend(res.get(s, []))
    return _build_records(data)


# Cache em disco — evita recarregar 16k ativos a cada abertura do app.
ASSETS_CACHE = os.path.join(_data_dir(), "assets_cache.json")
ASSETS_TTL   = 24 * 3600
_CACHE_VER   = 2   # bump quando o formato do registro muda (v2 = + id_parent/id_type_item/id_group_task)


def _seed_cache():
    """1ª execução (sem cache em %APPDATA%): copia o catálogo embutido (seed) → instantâneo no .exe.
    Seed = ao lado do script (dev) ou dentro do bundle PyInstaller (_MEIPASS)."""
    if os.path.exists(ASSETS_CACHE):
        return
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    seed = os.path.join(base, "assets_cache.json")
    if os.path.exists(seed):
        try:
            shutil.copy2(seed, ASSETS_CACHE)
        except OSError:
            pass


def _read_asset_cache():
    """Lê o catálogo de ativos do cache (mesma versão, dentro do TTL). None se ausente/expirado."""
    try:
        with open(ASSETS_CACHE, encoding="utf-8") as f:
            c = json.load(f)
    except Exception:
        return None
    if c.get("assets") and c.get("ver") == _CACHE_VER and (time.time() - c.get("ts", 0)) < ASSETS_TTL:
        return c["assets"]
    return None


def load_assets_cached(force: bool = False) -> list:
    """Ativos do cache (se < 24h e mesma versão) ou recarrega via RPC (sessão do usuário — sem
    OAuth) e salva. force=True ignora o cache."""
    if not force:
        _seed_cache()
        cached = _read_asset_cache()
        if cached:
            return cached
    assets = get_assets()
    try:
        with open(ASSETS_CACHE, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "ver": _CACHE_VER, "assets": assets}, f, ensure_ascii=False)
    except Exception:
        pass
    return assets


def get_responsaveis() -> list:
    """TODO o pessoal ATIVO via RPC personnel.personnel_list (sessão do usuário — sem OAuth),
    ordenado por nome. → [{'code','name','id_personnel'}] onde id_personnel = campo `id`
    (= id_responsible da WO; confirmado: Levi id=1414413)."""
    allp, start = [], 0
    while True:
        res = _rpc_call(RPC_PERSONNEL, {"page": start // 100 + 1, "limit": 100, "start": start,
                                        "append": True, "filter": [], "sort": []})
        data = res.get("data") if isinstance(res, dict) else res
        data = data if isinstance(data, list) else []
        allp.extend(data)
        start += 100
        if len(data) < 100:
            break
    out = []
    for p in allp:
        full = (p.get("full_name") or p.get("name") or "").strip()
        if full and p.get("active") is not False:
            out.append({"code": p.get("code"), "name": full, "id_personnel": p.get("id")})
    out.sort(key=lambda x: x["name"].lower())
    return out


# ── Escrita: OS de verdade via RPC interno (tasks_noscheduled_react_insert) ────
# O REST work_orders é baseado em referência de tarefa (dá 400 em texto livre). A OS completa
# (subtarefas/tipo/etc.) vem do RPC que o web app usa, autenticado pelo JWT do LOGIN (sessão).

def _save_jwt(jwt: str):
    """Guarda SÓ o JWT — no cofre do SO (keyring) ou, sem keyring, no arquivo gitignored."""
    if _HAS_KEYRING:
        try:
            keyring.set_password(_KEYRING_SVC, "login_jwt", jwt)
            return
        except Exception:
            pass
    try:
        with open(LOGIN_JWT_FILE, "w", encoding="utf-8") as f:
            f.write(jwt)
    except OSError:
        pass


def _read_jwt() -> str:
    """Lê o JWT: env override (FRACTTAL_LOGIN_JWT) → keyring → arquivo."""
    jwt = (os.environ.get("FRACTTAL_LOGIN_JWT", "") or "").strip()
    if not jwt and _HAS_KEYRING:
        try:
            jwt = (keyring.get_password(_KEYRING_SVC, "login_jwt") or "").strip()
        except Exception:
            jwt = ""
    if not jwt:
        try:
            with open(LOGIN_JWT_FILE, encoding="utf-8") as f:
                jwt = f.read().strip()
        except OSError:
            jwt = ""
    if jwt.lower().startswith("bearer "):
        jwt = jwt[7:].strip()
    return jwt


def _clear_jwt():
    if _HAS_KEYRING:
        try:
            keyring.delete_password(_KEYRING_SVC, "login_jwt")
        except Exception:
            pass
    try:
        if os.path.exists(LOGIN_JWT_FILE):
            os.remove(LOGIN_JWT_FILE)
    except OSError:
        pass


def _extract_login_jwt(j) -> str:
    """Acha o JWT na resposta do login_new (varre o JSON; formato flexível)."""
    def _scan(o):
        if isinstance(o, str):
            return o.replace("Bearer ", "").strip() if o.count(".") == 2 and len(o) > 60 else ""
        if isinstance(o, dict):
            for k in ("token", "access_token", "jwt", "id_token", "authorization"):
                v = o.get(k)
                if isinstance(v, str) and v.count(".") == 2:
                    return v.replace("Bearer ", "").strip()
            for v in o.values():
                r = _scan(v)
                if r:
                    return r
        if isinstance(o, list):
            for v in o:
                r = _scan(v)
                if r:
                    return r
        return ""
    return _scan(j)


def _encrypt_password(email: str, password: str, double: bool = True) -> str:
    """Replica o Util.encryptPassword do web app (achado no bundle index-*.js do Fracttal):
        inner = MD5(email + ':' + senha)
        final = MD5(email + ':' + inner)   # doubleEncrypt (padrão do web app)
    É por isso que MD5 simples era recusado (USER_OR_INVALID_KEY)."""
    inner = hashlib.md5(f"{email}:{password}".encode("utf-8")).hexdigest()
    if double:
        return hashlib.md5(f"{email}:{inner}".encode("utf-8")).hexdigest()
    return inner


def fracttal_login(email: str, password: str) -> dict:
    """Loga no Fracttal (rpc/login_new). A senha é transformada IGUAL ao web app
    (_encrypt_password = MD5 duplo com o e-mail como sal). Guarda o JWT e devolve {'email','jwt_exp'}.
    A SENHA NUNCA é armazenada — só usada pra obter o token."""
    email = (email or "").strip()
    if not email or not password:
        raise FracttalError("Informe e-mail e senha.")
    pw_enc = _encrypt_password(email, password)
    body = {"email": email, "password": pw_enc, "id_company": ID_COMPANY,
            "id_server": ID_SERVER, "description": COMPANY_DESC, "platform": "Fracttal/5.7.02 web"}
    try:
        r = requests.post(RPC_LOGIN_URL, json=body, timeout=25,
                          headers={"Content-Type": "application/json", "Accept": "*/*",
                                   "Origin": "https://app.fracttal.com"})
    except requests.RequestException as e:
        raise FracttalError(f"Erro de conexão no login: {e}")
    try:
        j = r.json()
    except ValueError:
        j = {}
    jwt = _extract_login_jwt(j)
    if not jwt:
        msg = str((j.get("message") if isinstance(j, dict) else "") or f"HTTP {r.status_code}")
        mu = msg.upper()
        if "BLOCK" in mu or "FAILURE_INTENT" in mu:
            raise FracttalError("Conta temporariamente BLOQUEADA (tentativas demais). Aguarde "
                                "~30 min SEM tentar e tente de novo. NÃO é senha errada.")
        if "USER_OR_INVALID" in mu or "INVALID_KEY" in mu:
            raise FracttalError("E-mail ou senha incorretos.")
        raise FracttalError(f"Login falhou: {msg}")
    _save_jwt(jwt)
    return {"email": email, "jwt_exp": _jwt_exp(jwt)}


def logout():
    _clear_jwt()


def current_user() -> str:
    """E-mail de quem está logado (lido do JWT), ou '' se não houver."""
    jwt = _read_jwt()
    if not jwt or jwt.count(".") != 2:
        return ""
    try:
        p = jwt.split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p.encode())).get("email", "") or ""
    except Exception:
        return ""


def is_logged_in() -> bool:
    """Há um JWT válido (não vencido) E com sessão viva? A sessão pode ter sido morta server-side
    (USER_NOT_LOGIN) mesmo com o exp futuro — por isso faz 1 checagem ao vivo (barata)."""
    jwt = _read_jwt()
    if not jwt or jwt.count(".") != 2:
        return False
    exp = _jwt_exp(jwt)
    if not exp or time.time() >= exp - 30:
        return False
    try:
        _rpc_call(RPC_LABELS_LIST, {"sort": [], "page": 1, "limit": 1, "start": 0, "is_tree": False,
                  "node": None, "id_work_order": 0, "only_enabled": True}, timeout=20)
        return True
    except FracttalError:
        return False


def _login_jwt() -> str:
    """JWT da sessão (de _read_jwt). Lança FracttalError pedindo login se faltar/malformado."""
    jwt = _read_jwt()
    if not jwt or jwt.count(".") != 2:
        raise FracttalError("Você não está logado no Fracttal. Faça login no app (e-mail + senha).")
    return jwt


def _jwt_exp(jwt: str) -> float:
    """exp (epoch) do JWT, lendo o payload base64. 0 se não der pra ler."""
    try:
        p = jwt.split(".")[1]
        p += "=" * (-len(p) % 4)
        return float(json.loads(base64.urlsafe_b64decode(p.encode())).get("exp") or 0)
    except Exception:
        return 0.0


def _rpc_try_refresh(jwt: str) -> str:
    """POST /rpc/token (sem corpo, Bearer) → JWT renovado. Best-effort; persiste no arquivo.
    Devolve '' se não conseguir (aí o chamador pede a recolagem)."""
    try:
        r = requests.post(RPC_TOKEN_URL, timeout=20, headers={
            "Authorization": f"Bearer {jwt}", "Content-Type": "application/json",
            "Origin": "https://app.fracttal.com"})
        if r.status_code != 200:
            return ""
        new = ""
        try:
            j = r.json()
            if isinstance(j, str):
                new = j
            elif isinstance(j, dict):
                d = j.get("data") if isinstance(j.get("data"), dict) else {}
                new = (j.get("token") or j.get("access_token")
                       or d.get("token") or d.get("access_token") or "")
        except ValueError:
            new = (r.text or "").strip().strip('"')
        new = (new or "").strip()
        if new.count(".") == 2:
            try:
                with open(LOGIN_JWT_FILE, "w", encoding="utf-8") as f:
                    f.write(new)
            except OSError:
                pass
            return new
    except requests.RequestException:
        pass
    return ""


def _rpc_headers() -> dict:
    jwt = _login_jwt()
    exp = _jwt_exp(jwt)
    if exp and time.time() > exp - 60:          # perto de vencer → tenta renovar
        novo = _rpc_try_refresh(jwt)
        if novo:
            jwt = novo
        elif time.time() > exp:                 # já venceu e não renovou → recolar
            raise FracttalError("O JWT do login do Fracttal expirou — cole um novo em fracttal_login.txt.")
    return {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://app.fracttal.com", "x-version": "Fracttal/5.7.02 web"}


def _iso_z(dt: datetime) -> str:
    """datetime → ISO UTC com milissegundos e Z (formato que o web app envia)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


_BR_TZ = timezone(timedelta(hours=-3))   # Brasília (UTC-3)


def fmt_data_br(iso, com_hora: bool = True) -> str:
    """Data que o Fracttal devolve em UTC (creation_date / event_date / date...) → string em horário
    de BRASÍLIA: 'DD/MM/YYYY HH:MM' (ou só 'DD/MM/YYYY'). Tolerante a vazio/curto/cru."""
    s = str(iso or "").strip()
    if not s:
        return "—"
    s2 = s.replace(" ", "T")[:19]
    try:
        dt = datetime.strptime(s2, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        try:                                           # só data (sem hora) → NÃO aplica fuso
            return datetime.strptime(s2[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            return s                                   # formato inesperado → devolve cru
    dt = dt.replace(tzinfo=timezone.utc).astimezone(_BR_TZ)
    return dt.strftime("%d/%m/%Y %H:%M" if com_hora else "%d/%m/%Y")


def _path_node(asset: dict) -> str:
    pid, iid = asset.get("id_parent"), asset.get("id")
    return f"{pid}.{iid}" if pid else str(iid)


# id_task_form_item_type → rótulo (confirmado ao vivo: 1=Texto, 4=Verificação na conta 4987).
_FORM_ITEM_TYPE_DESC = {1: "Texto", 4: "Verificação"}


def _rpc_subtasks(subtasks: list, respostas: list = None) -> list:
    """Subtarefas no formato do RPC. Cada item pode ser:
      - str  → tipo Texto (id 1) — usado no Criar OS manual.
      - dict {description, id_task_form_item_type, task_form_item_type_description, ...} → PRESERVA
        o tipo original (usado na clonagem, p/ manter Verificação/Texto/etc. como na OS de origem).
    Mínimo 1 (default 'Procedimento'). Campos do tipo são copiados quando vêm no dict.
    `respostas` (opcional, paralelo por ordem) = respostas das subtarefas p/ OS já finalizada →
    injeta `value` em cada item (igual o web ao concluir a tarefa)."""
    norm = []
    for s in (subtasks or []):
        if isinstance(s, dict):
            d = str(s.get("description") or "").strip()
            if d:
                norm.append({**s, "description": d})
        else:
            d = str(s or "").strip()
            if d:
                norm.append({"description": d})
    if not norm:
        norm = [{"description": "Procedimento"}]
    out = []
    for i, s in enumerate(norm):
        tipo_id = s.get("id_task_form_item_type") or 1
        tipo_desc = _FORM_ITEM_TYPE_DESC.get(tipo_id) or s.get("task_form_item_type_description")
        item = {"id": str(uuid.uuid4()), "id_task_form_item_type": tipo_id,
                "id_task_form_item_group": s.get("id_task_form_item_group"),
                "order_number": i + 1, "description": s["description"],
                "task_form_item_type_description": tipo_desc,
                "task_form_item_group_description": s.get("task_form_item_group_description"),
                "is_required": bool(s.get("is_required", False)),
                "attachments_required": bool(s.get("attachments_required", False)),
                "is_new": False, "dropdown_options": s.get("dropdown_options"),
                "phantom": True, "num_attachments": 0}
        resp = None
        if respostas and i < len(respostas):
            resp = respostas[i]
        elif s.get("value") not in (None, ""):           # dict já trazendo a resposta
            resp = s.get("value")
        if resp not in (None, ""):
            item["value"] = resp                          # resposta da subtarefa (OS finalizada)
        out.append(item)
    return out


def _asset_by_code(code: str):
    """Registro completo do ativo pelo code (a partir do cache de ativos). None se não achar."""
    try:
        for a in load_assets_cached():
            if a.get("code") == code:
                return a
    except Exception:
        pass
    return None


def create_os_rpc(asset: dict, description: str, task_type: str, subtasks: list,
                  requested_by: str = "", etiqueta: str = "", note: str = "",
                  event_date: datetime = None, tipo: dict = None, finalizar: dict = None) -> dict:
    """Cria uma OS (tarefa não-planejada) via RPC interno do Fracttal. asset = registro do
    get_assets() (precisa de id/id_parent/id_type_item/id_group_task). `event_date` = data
    programada (datetime; default = agora). `tipo` = dict opcional com id_main (id_task_type_main),
    id_priorities (criticidade) e Classificação 1/2 (id_c1/desc_c1, id_c2/desc_c2).
    `finalizar` (opcional) = OS JÁ REALIZADA → cria a WO concluída direto, com:
    {to_in_review(bool: True=Verificação, False=Finalizados), final_date(datetime), id_assigned_user
    (=id_personnel do responsável), name(str), respostas(list paralela às subtarefas)}.
    Devolve {'id_work_order','wo_folio','raw'}. Em erro, a mensagem do RPC é propagada (FracttalError)."""
    id_item = asset.get("id")
    if not id_item:
        raise FracttalError(f"Ativo '{asset.get('code')}' sem id_item — recarregue os ativos (cache antigo).")
    tipo = tipo or {}
    main_id = tipo.get("id_main")
    if main_id is None:                                   # chamadas antigas (clone): mapeia pelo nome
        main_id = TASK_TYPE_MAIN.get(task_type)
    if main_id is None:
        raise FracttalError(f"Tipo de tarefa desconhecido: {task_type}")
    prio = tipo.get("id_priorities")
    if prio is None:
        prio = ID_PRIORITIES
    fin = finalizar or {}
    finalizada = bool(fin)                                # "Esta tarefa já foi realizada?"
    em_verificacao = bool(fin.get("to_in_review"))       # True = Verificação; False = Finalizados
    ev = event_date if event_date is not None else datetime.now(timezone.utc)
    if ev.tzinfo is None:                                 # garante UTC-aware p/ o _iso_z
        ev = ev.replace(tzinfo=timezone.utc)
    fdt = fin.get("final_date")
    if fdt is not None and getattr(fdt, "tzinfo", None) is None:
        fdt = fdt.replace(tzinfo=timezone.utc)
    final_iso = _iso_z(fdt) if fdt is not None else _iso_z(ev + timedelta(minutes=20))
    params = {
        "event_date": _iso_z(ev),
        "cal_date_maintenance": _iso_z(ev + timedelta(minutes=10)),
        "date_maintenance": _iso_z(ev + timedelta(minutes=10)),
        "initial_date": _iso_z(ev - timedelta(minutes=10)),
        "final_date": final_iso,
        "type_user": "HUMAN_RESOURCES",
        "id_priorities": prio,
        "id_failure_severity": 0, "id_damage_type": 1,
        "failure_asset": False,
        "to_in_review": em_verificacao,
        "work_done": finalizada and not em_verificacao,  # Finalizados → concluída
        "to_work_order": finalizada,                     # finalizada vira WO direto (sem Fase 2)
        "stop_assets": False,
        "duration": 600, "real_duration": 600,
        "requested_by": (requested_by or "").strip() or "GridCo O&M",
        "edit_mode": False,
        "tasks_types_main_description": task_type,
        "subtasks": _rpc_subtasks(subtasks, fin.get("respostas")),
        "array_resources": [],                       # responsável: pendente de 1 captura p/ mapear
        "id_item": id_item,
        "items_description": asset.get("description") or "",
        "id_request": None, "note": (note or "").strip() or None,
        "name": (fin.get("name") or None) if finalizada else None, "available": None,
        "initial_date_out_of_service": None,
        "id_group_task": asset.get("id_group_task"),
        "assigment_date": _iso_z(ev),
        "id_work_order_task_related": None, "date_asset_out_of_service": None,
        "description": (description or "").strip(),
        "id_type_item": asset.get("id_type_item") or 1,
        "path_node": _path_node(asset),
        "msg_availability": "ASSET_OUT_OF_SERVICE",
        "id_task_type_main": main_id,
    }
    params["task_note"] = params["note"]                  # o web manda task_note = note
    if tipo.get("id_c1") is not None:                     # Classificação 1
        params["id_task_type"] = tipo["id_c1"]
        params["tasks_types_description"] = tipo.get("desc_c1") or ""
    if tipo.get("id_c2") is not None:                     # Classificação 2
        params["id_task_type_2"] = tipo["id_c2"]
        params["tasks_types_2_description"] = tipo.get("desc_c2") or ""
    if finalizada and fin.get("id_assigned_user") is not None:
        params["id_assigned_user"] = fin["id_assigned_user"]   # responsável da WO concluída
    body = [{"id": str(uuid.uuid4()), "jsonrpc": "2.0", "method": RPC_METHOD, "params": params}]
    try:
        r = requests.post(RPC_PROXY_URL, headers=_rpc_headers(), json=body, timeout=45)
    except requests.RequestException as e:
        raise FracttalError(f"Erro de conexão com o RPC do Fracttal: {e}")
    if r.status_code in (401, 403):
        raise FracttalError("Login recusado (HTTP %d) — o JWT do Fracttal venceu/é inválido. "
                            "Cole um novo em fracttal_login.txt." % r.status_code)
    if r.status_code >= 400:
        raise FracttalError(f"RPC HTTP {r.status_code} — {(r.text or 'sem detalhes')[:240]}")
    try:
        j = r.json()
    except ValueError:
        raise FracttalError(f"RPC devolveu resposta não-JSON: {(r.text or '')[:200]}")
    rec = j[0] if isinstance(j, list) and j else j
    if isinstance(rec, dict) and rec.get("error"):
        err = rec["error"]
        msg = err.get("message") if isinstance(err, dict) else err
        raise FracttalError(f"RPC erro: {str(msg)[:240]}")
    # Resposta: {"success":bool,"message":"ACTION_DONE","data":{id_task,id_work_order,wo_folio,...}}
    result = rec.get("result") if isinstance(rec, dict) else None
    if isinstance(result, list) and result:
        result = result[0]
    if isinstance(result, dict) and result.get("success") is False:
        raise FracttalError(f"RPC recusou: {result.get('message') or 'sem detalhe'}")
    data = result.get("data") if isinstance(result, dict) else {}
    data = data if isinstance(data, dict) else {}
    return {"id_task": data.get("id_task"),
            "id_work_order": data.get("id_work_order"),
            "wo_folio": data.get("wo_folio"),
            "raw": result}


# ── Fase 2: converter tarefa pendente em WO numerada + atribuir responsável ───
RPC_KANBAN   = "tasks.tasks_todo_list_kanban"
RPC_WO_INSERT = "tasks.work_order_insert"
# Campos que o web app inclui no registro de array_tasks_todo mas que a lista do kanban
# não devolve (defaults observados no cURL real). O registro do kanban tem precedência.
_WO_TASK_DEFAULTS = {
    "id_status_work_order": 5, "resources": [], "num_resources": 0, "triggers": {},
    "cfg_description": None, "custom_fields_values": None, "first_date_maintenance": None,
    "related_items": None, "reschedule_causes": None, "task_failure": None,
    "cc_description": None, "wo_folio": None, "custom_fields_groups_description": None,
    "is_configured": True,
}


def _rpc_call(method: str, params: dict, timeout: int = 45):
    """Chamada genérica ao rpc/proxy. Devolve o 'result' (ou levanta FracttalError)."""
    body = [{"id": str(uuid.uuid4()), "jsonrpc": "2.0", "method": method, "params": params}]
    try:
        r = requests.post(RPC_PROXY_URL, headers=_rpc_headers(), json=body, timeout=timeout)
    except requests.RequestException as e:
        raise FracttalError(f"Erro de conexão (RPC {method}): {e}")
    if r.status_code in (401, 403):
        _clear_jwt()
        raise SessionExpired(f"Login recusado (HTTP {r.status_code}) — faça login de novo no app.")
    if r.status_code >= 400:
        raise FracttalError(f"RPC {method} HTTP {r.status_code} — {(r.text or '')[:200]}")
    try:
        j = r.json()
    except ValueError:
        raise FracttalError(f"RPC {method} resposta não-JSON: {(r.text or '')[:160]}")
    rec = j[0] if isinstance(j, list) and j else j
    if isinstance(rec, dict) and rec.get("error"):
        err = rec["error"]
        raise FracttalError(f"RPC {method} erro: {str(err.get('message') if isinstance(err, dict) else err)[:200]}")
    result = rec.get("result") if isinstance(rec, dict) else rec
    # sessão morta server-side (USER_NOT_LOGIN/INVALID_TOKEN…) → vem success:false (HTTP 200).
    # Limpa o token e pede login, em vez de devolver lista vazia silenciosa.
    if isinstance(result, dict) and result.get("success") is False:
        msg = str(result.get("message") or "")
        if any(k in msg.upper() for k in ("NOT_LOGIN", "INVALID_TOKEN", "SESSION",
                                          "TOKEN_EXPIRED", "UNAUTHORIZED", "NOT_AUTH")):
            _clear_jwt()
            raise SessionExpired("Sua sessão do Fracttal expirou ou foi encerrada. Faça login de novo.")
    return result


def _kanban_records(id_tasks: set, tentativas: int = 3) -> dict:
    """Busca na lista de tarefas pendentes (kanban) os registros completos dos id_tasks dados.
    → {id_task: registro}. Retenta pois a tarefa recém-criada pode demorar 1-2s p/ aparecer."""
    faltam = set(id_tasks)
    achados = {}
    for _ in range(tentativas):
        res = _rpc_call(RPC_KANBAN, {"page": 1, "limit": 200, "start": 0, "append": True,
                                     "is_tree": False, "id_type_item": 0, "filter": [], "group": {}, "sort": []})
        data = res.get("data") if isinstance(res, dict) else res
        for t in (data if isinstance(data, list) else []):
            if isinstance(t, dict) and t.get("id_task") in faltam:
                achados[t["id_task"]] = t
        faltam -= set(achados)
        if not faltam:
            break
        time.sleep(1.5)
    return achados


def _work_order_insert(kanban_recs: list, id_responsible, responsible_name: str = "",
                       duration: int = 600) -> dict:
    """Insere UMA WO contendo TODAS as tarefas dos registros de kanban dados (array_tasks_todo).
    1 registro → OS de 1 tarefa; N registros → 1 OS com N tarefas (igual a selecionar várias
    tarefas pendentes no kanban e gerar uma OT só). Atribui o responsável (id_personnel)."""
    recs = []
    for kr in kanban_recs:
        rec = {**_WO_TASK_DEFAULTS, **dict(kr)}
        rec["resources"] = []
        recs.append(rec)
    nome = (responsible_name or "").strip()
    inner = {
        "creation_mode": 1, "type_user": "HUMAN_RESOURCES", "duration": duration,
        "enable_budget": False, "id_third_party": None, "third_party_description": "",
        "id_responsible": id_responsible, "personnel_description": nome, "name": nome,
        "array_tasks_todo": recs,
    }
    params = {"page": 1, "limit": 200, "start": 0, "append": True,
              "id_internal": str(uuid.uuid4()), "id_background_process_type": 1,
              "status": 1, "determinate": False, "params": inner,
              **inner, "wo_creation_status": False, "id_transaction": None}
    res = _rpc_call(RPC_WO_INSERT, params)
    data = res.get("data") if isinstance(res, dict) else (res if isinstance(res, dict) else {})
    data = data if isinstance(data, dict) else {}
    # síncrono: a resposta (message SUCCESS_NEW_WO_VERIFY_QUEUE) já traz a WO em data.id + wo_folio
    return {"id_work_order": data.get("id") or data.get("id_work_order"),
            "wo_folio": data.get("wo_folio") or data.get("code"),
            "id_transaction": data.get("id_transaction"), "raw": res}


def convert_task_to_wo(kanban_rec: dict, id_responsible, responsible_name: str = "",
                       duration: int = 600) -> dict:
    """Fase 2 (1 tarefa): converte UMA tarefa pendente (registro do kanban) em WO numerada e
    atribui o responsável (id_responsible = id_personnel)."""
    return _work_order_insert([kanban_rec], id_responsible, responsible_name, duration)


# ── Fase 3: etiquetas (work_order_labels) — catálogo + aplicar numa WO ─────────
RPC_LABELS_LIST = "tasks.work_order_labels_list"
RPC_LABELS_SYNC = "tasks.work_order_labels_sync"


def get_labels() -> list:
    """Catálogo de etiquetas habilitadas → [{'id','description','color'}] (ordenado por descrição)."""
    res = _rpc_call(RPC_LABELS_LIST, {"sort": [{"property": "description", "direction": "asc"}],
                                      "page": 1, "limit": 200, "start": 0, "is_tree": False,
                                      "node": None, "id_work_order": 0, "only_enabled": True})
    data = res.get("data") if isinstance(res, dict) else res
    return [{"id": d.get("id"), "description": d.get("description"), "color": d.get("color")}
            for d in (data if isinstance(data, list) else []) if d.get("enabled", True)]


def apply_labels(id_work_order, id_labels: list) -> dict:
    """Aplica (sync) o conjunto de etiquetas id_labels numa WO. Devolve {'ok',...}."""
    ids = [i for i in (id_labels or []) if i]
    if not id_work_order or not ids:
        return {"ok": False, "erro": "sem id_work_order ou id_labels"}
    res = _rpc_call(RPC_LABELS_SYNC, {"page": 1, "limit": 200, "start": 0, "append": True,
                                      "id_work_order": id_work_order, "id_labels": ids})
    return {"ok": True, "raw": res}


# ── Histórico: "Minhas OS" (criadas por mim / atribuídas a mim) ───────────────
RPC_WO_LIST = "tasks.work_orders_list_react"
# Mapa de id_status_work_order → rótulo (confirmado no kanban do Fracttal: colunas
# "OSs em Processo" 1, "em Verificação" 2, "Concluídas" 3 + selo CANCELADO = 4).
WO_STATUS = {1: "Em Processo", 2: "Em Verificação", 3: "Concluída", 4: "Cancelada"}
_user_ids_cache = {}   # email -> (id_personnel, id_account, nome)


def _current_user_info():
    """(id_personnel, id_account, nome) do usuário logado — achados no personnel pelo e-mail. Cacheado."""
    email = (current_user() or "").strip().lower()
    if not email:
        return (None, None, "")
    if email in _user_ids_cache:
        return _user_ids_cache[email]
    info = (None, None, "")
    start = 0
    while True:
        res = _rpc_call(RPC_PERSONNEL, {"page": start // 100 + 1, "limit": 100, "start": start,
                                        "append": True, "filter": [], "sort": []})
        data = res.get("data") if isinstance(res, dict) else res
        data = data if isinstance(data, list) else []
        for p in data:
            if (p.get("account_email") or p.get("email") or "").strip().lower() == email:
                info = (p.get("id"), p.get("id_account"),
                        (p.get("full_name") or p.get("name") or "").strip())
                break
        start += 100
        if info[0] is not None or len(data) < 100:
            break
    _user_ids_cache[email] = info
    return info


def _current_user_ids():
    """(id_personnel, id_account). id_personnel = 'atribuídas a mim' (id_assigned_user);
    id_account = 'criadas por mim' (id_created_by)."""
    idp, idacc, _ = _current_user_info()
    return (idp, idacc)


def current_user_name():
    """Nome de exibição do usuário logado (do personnel), ou o e-mail se não achar."""
    return _current_user_info()[2] or current_user()


# ── Solicitação de Serviço (work request) via RPC requests.requests_insert ────
RPC_REQ_TYPES   = "requests.types_list"     # Grupo
RPC_REQ_TYPES_1 = "requests.types_1_list"   # Classificação 1 (obrigatória)
RPC_REQ_TYPES_2 = "requests.types_2_list"   # Classificação 2
RPC_REQ_INSERT  = "requests.requests_insert"


def _req_type_list(method: str) -> list:
    res = _rpc_call(method, {"sort": [{"property": "description", "direction": "asc"}],
                             "page": 1, "limit": 200, "start": 0, "is_tree": False, "node": None})
    data = res.get("data") if isinstance(res, dict) else res
    return [{"id": x.get("id"), "description": x.get("description")}
            for x in (data if isinstance(data, list) else []) if x.get("enabled", True)]


def get_request_types() -> dict:
    """Listas dos dropdowns da Solicitação: grupo, classif1 (obrigatória), classif2."""
    return {"grupo":    _req_type_list(RPC_REQ_TYPES),
            "classif1": _req_type_list(RPC_REQ_TYPES_1),
            "classif2": _req_type_list(RPC_REQ_TYPES_2)}


def create_solicitacao(asset: dict, descricao: str, id_type_1, id_type=None, id_type_2=None,
                       observation: str = "", date_incident: datetime = None,
                       is_urgent: bool = False, desc_type_1: str = "",
                       desc_type: str = "", desc_type_2: str = "") -> dict:
    """Cria uma Solicitação de Serviço (work request) via RPC requests.requests_insert.
    Obrigatórios: descrição, ativo (id_item), id_type_1 (Classificação 1).
    desc_type*/_1/_2 = textos dos dropdowns (o web app os envia preenchidos — sem isso o
    servidor recusa a validação da classificação)."""
    if not (descricao or "").strip():
        raise FracttalError("A descrição não pode ficar em branco.")
    if not asset or not asset.get("id"):
        raise FracttalError("Selecione o ativo.")
    if not id_type_1:
        raise FracttalError("A Classificação 1 não pode ficar em branco.")
    dz = _iso_z(date_incident or datetime.now(timezone.utc))
    uid = str(uuid.uuid4())
    nome = current_user_name()
    items_desc = asset.get("parent_description") or ""
    if not items_desc:                      # fallback p/ o caminho do ativo (cosmético)
        cli, usi = asset.get("cliente") or "", asset.get("usina") or ""
        items_desc = f"// {cli}/  {usi}/".strip()
    params = {
        "id": uid, "id_code": None, "id_work_order": 0, "wo_folio": "", "status_description": "",
        "description": descricao.strip(), "is_urgent": bool(is_urgent),
        "id_item": asset.get("id"), "items_description": items_desc,
        "code_item": asset.get("code") or "", "parent_description": "",
        "date": dz, "date_incident": dz, "date_maintenance": dz, "date_solution": dz, "date_status": dz,
        "observation": observation or "", "requests_x_status_notes": "",
        "id_cost_center": None, "costs_center_description": "",
        "id_type": id_type, "types_description": desc_type or "",
        "id_type_1": id_type_1, "types_1_description": desc_type_1 or "",
        "id_type_2": id_type_2, "types_2_description": desc_type_2 or "",
        "priorities_description": "", "rating": "", "rating_notes": "", "id_user": "",
        "accounts_name": nome, "requested_by": nome, "email_requested_by": "",
        "requests_x_status_accounts_name": "",
        "requests_x_key_words_id_key_words": None, "requests_x_key_words_descriptions": None,
        "id_status": 0, "geolocation": None, "attachments": None,
        "id_group": None, "groups_description": "", "groups_1_description": "",
        "id_group_1": None, "id_group_2": None, "groups_2_description": "",
        "identifier": "", "id_work_order_task_related": None, "id_related": "",
        "idInternal": uid,
    }
    res = _rpc_call(RPC_REQ_INSERT, params)
    # o servidor pode recusar com success:false (HTTP 200) — sem isso a UI mostrava "criada" à toa
    if isinstance(res, dict) and res.get("success") is False:
        raise FracttalError("O Fracttal recusou a solicitação: "
                            + (str(res.get("message") or "").replace("_", " ").strip() or "motivo não informado"))
    data = res.get("data") if isinstance(res, dict) else {}
    data = data if isinstance(data, dict) else {}
    id_code = data.get("id_code") if isinstance(data, dict) else None
    if not id_code:
        raise FracttalError("A solicitação não retornou número (provavelmente não foi criada). "
                            "Resposta do servidor: " + str(res)[:240])
    return {"id_code": id_code, "raw": res}


def create_solicitacoes_bulk(assets: list, descricao: str, id_type_1, id_type=None, id_type_2=None,
                             observation: str = "", date_incident: datetime = None,
                             is_urgent: bool = False, desc_type_1: str = "",
                             desc_type: str = "", desc_type_2: str = "") -> list:
    """Cria N Solicitações — uma por ativo, com os MESMOS campos (descrição/classificação/data).
    Não para no 1º erro. → [{'code','ok':True,'id_code'} | {'code','ok':False,'erro'}]."""
    out = []
    for a in (assets or []):
        asset = a if isinstance(a, dict) else _asset_by_code(a)
        code = asset.get("code") if isinstance(asset, dict) else str(a)
        if not isinstance(asset, dict):
            out.append({"code": code, "ok": False, "erro": "ativo não encontrado no cache."})
            continue
        try:
            r = create_solicitacao(asset, descricao, id_type_1, id_type=id_type, id_type_2=id_type_2,
                                   observation=observation, date_incident=date_incident,
                                   is_urgent=is_urgent, desc_type_1=desc_type_1,
                                   desc_type=desc_type, desc_type_2=desc_type_2)
            out.append({"code": code, "ok": True, "id_code": r.get("id_code")})
        except FracttalError as e:
            out.append({"code": code, "ok": False, "erro": str(e)})
    return out


_code_loc = {}


def _usina_curta(usina_full: str) -> str:
    """'Thopen - Ceilândia 1 - DF' (Cliente - Usina - Estado) → 'Ceilândia 1'."""
    parts = [p.strip() for p in str(usina_full).split(" - ") if p.strip()]
    if len(parts) <= 1:
        return usina_full
    parts = parts[1:]                                          # tira o cliente (1º)
    if len(parts) > 1 and len(parts[-1]) == 2 and parts[-1].isalpha():
        parts = parts[:-1]                                     # tira a sigla do estado (último)
    return " - ".join(parts)


def _code_to_loc():
    """{code do ativo: (cliente, usina_curta, tipo)} a partir do catálogo (cacheado).
    `tipo` = rótulo do tipo de ativo (Inversor, Tracker, Cabine, Transformador, Usina…)."""
    if _code_loc:
        return _code_loc
    try:
        for a in load_assets_cached():
            c = a.get("code")
            if c:
                _code_loc[c] = (a.get("cliente") or "", _usina_curta(a.get("usina") or ""),
                                a.get("tipo") or "")
    except Exception:
        pass
    return _code_loc


def _extrai_code(desc: str) -> str:
    """'... { GDEN-GJR100-ETKR10.200 }' → 'GDEN-GJR100-ETKR10.200'."""
    if "{" in desc and "}" in desc:
        return desc[desc.rfind("{") + 1:desc.rfind("}")].strip()
    return ""


HISTORICO_CAP = 2000   # teto de OS por carga do histórico (limita o enriquecimento de tipo_tarefa)


def list_minhas_os(modo: str = "criadas", id_account=None, id_label=None,
                   de: str = None, ate: str = None, cap: int = HISTORICO_CAP) -> list:
    """OS do Fracttal no PERÍODO [de, ate] (datas 'YYYY-MM-DD' — filtradas NO SERVIDOR por
    creation_date, então o período governa a busca de verdade). modo='criadas' (Histórico Geral, por
    'id_created_by') ou 'atribuidas' (id_assigned_user = id_personnel do logado). Em 'criadas',
    id_account: None = LOGADO (default); "TODOS" = todos os criadores; ou um id_account específico.
    id_label (opcional): só OS que CONTÊM a etiqueta. PAGINA o período inteiro (todos os status numa
    busca só) até o teto `cap`, dedup por id, ordena por data desc.
    → [{'id','folio','cliente','usina','ativo','tipo','tipo_tarefa','descricao','criado_por',
        'etiquetas','data','status_id','status'}]. 'tipo' = tipo de ativo (Inversor/Tracker/…);
        'tipo_tarefa' = tipo da OS (Corretiva/Preventiva/Inspeção/…), via _tipo_tarefa_por_os."""
    idp, idacc = _current_user_ids()
    todos = False
    if modo == "atribuidas":
        prop, val = "id_assigned_user", idp
    else:                                   # criadas / Histórico Geral
        prop = "id_created_by"
        if id_account is None:    val = idacc            # default: logado
        elif id_account == "TODOS": val, todos = None, True
        else:                     val = id_account
    if not todos and val is None:
        raise FracttalError("Não consegui identificar seu usuário no Fracttal (e-mail não bate no cadastro).")
    cond = [] if todos else [{"operator": "=", "property": prop, "value": val}]
    if id_label:                            # OS que contêm a etiqueta (server-side)
        cond.append({"operator": "=", "property": "id_label", "value": id_label})
    if de:                                  # período no servidor (creation_date é ISO UTC)
        cond.append({"operator": ">=", "property": "creation_date", "value": de})
    if ate:
        cond.append({"operator": "<=", "property": "creation_date", "value": ate + "T23:59:59"})
    limit = 200

    def _fetch_page(start):                 # uma página da listagem (período já está em cond)
        try:
            return _rpc_call(RPC_WO_LIST, {"page": start // limit + 1, "limit": limit, "start": start,
                "append": True, "sort": [{"property": "id", "direction": "desc"}], "filter": cond})
        except FracttalError:
            return None

    first = _fetch_page(0)                   # 1ª página dá o total; as demais em paralelo
    total = int(first.get("total") or 0) if isinstance(first, dict) else 0
    paginas = [first]
    starts = list(range(limit, min(total, cap), limit))
    if starts:
        with ThreadPoolExecutor(max_workers=min(6, len(starts))) as ex:
            paginas.extend(ex.map(_fetch_page, starts))
    vistos = {}
    for res in paginas:
        for w in ((res.get("data") or []) if isinstance(res, dict) else []):
            wid = w.get("id")
            if wid in vistos:
                continue
            item = w.get("items_log_descriptions") or ""
            if isinstance(item, list):
                item = ", ".join(str(x) for x in item)
            item = str(item)
            code = _extrai_code(item)
            ativo = (item.split("{")[0]).strip()[:60]
            cliente, usina, tipo = _code_to_loc().get(code, ("", "", ""))
            desc = w.get("tasks_descriptions") or ""
            if isinstance(desc, list):
                desc = ", ".join(str(x) for x in desc)
            desc = str(desc).strip()[:90] or "—"
            stid = w.get("id_status_work_order")
            etiquetas = [{"id": l.get("id"), "nome": l.get("description")}
                         for l in (w.get("labels") or []) if isinstance(l, dict)]
            vistos[wid] = {"id": wid, "folio": w.get("wo_folio"), "cliente": cliente or "—",
                           "usina": usina or "—", "ativo": ativo, "tipo": tipo or "—", "descricao": desc,
                           "criado_por": str(w.get("created_by") or "").strip(), "etiquetas": etiquetas,
                           "data": (w.get("creation_date") or "")[:19],
                           "status_id": stid, "status": WO_STATUS.get(stid, f"Status {stid}")}
    out = list(vistos.values())
    out.sort(key=lambda x: x["data"], reverse=True)
    tt = _tipo_tarefa_por_os([d["id"] for d in out])      # enriquece c/ o tipo de tarefa (RPC tarefas)
    for d in out:
        d["tipo_tarefa"] = tt.get(d["id"], "")
    return out


# ── Detalhe de uma OS (ao clicar no nº no histórico): Data do Evento, Notas, Subtarefas ──
RPC_WO_TASKS  = "tasks.work_orders_tasks_new_list"       # tarefa(s) da OS (event_date, notas, tipo)
RPC_WO_FORMIT = "tasks.work_orders_task_form_items_list"  # subtarefas (checklist)


def _tipo_tarefa_por_os(wo_ids):
    """{id_work_order: 'Tipo' (ou 'Tipo1 / Tipo2' se a OS tiver tarefas de tipos diferentes)} p/ as OS
    dadas. A listagem (work_orders_list_react) NÃO traz o tipo de tarefa — ele vem do RPC de tarefas,
    que aceita busca ampla com filtro 'in' por id_work_order (1 chamada por lote de ~80 OS, em paralelo).
    Best-effort: erro em um lote → ignora aquele lote (filtro fica vazio p/ ele, sem quebrar a lista)."""
    ids = [w for w in dict.fromkeys(wo_ids) if w]            # únicos, preserva ordem
    if not ids:
        return {}
    CH = 130                                                 # OS por chamada (lotes grandes = menos rodadas)
    chunks = [ids[i:i + CH] for i in range(0, len(ids), CH)]

    def _fetch(chunk):
        acc, start, limit = {}, 0, 2000
        while True:
            try:
                r = _rpc_call(RPC_WO_TASKS, {"page": 1, "limit": limit, "start": start,
                              "sort": [{"property": "id", "direction": "desc"}],
                              "filter": [{"operator": "in", "property": "id_work_order", "value": chunk}]})
            except FracttalError:
                break
            data = (r.get("data") or []) if isinstance(r, dict) else []
            for t in data:
                wid = t.get("id_work_order")
                tp = str(t.get("tasks_types_main_description") or "").strip()
                if wid and tp:
                    acc.setdefault(wid, set()).add(tp)
            start += len(data)
            if not data or len(data) < limit:                # lote completo
                break
        return acc

    out = {}
    with ThreadPoolExecutor(max_workers=min(8, len(chunks))) as ex:
        for acc in ex.map(_fetch, chunks):
            for wid, s in acc.items():
                out.setdefault(wid, set()).update(s)
    return {k: " / ".join(sorted(v)) for k, v in out.items()}


# Campos onde o Fracttal pode guardar a RESPOSTA de uma subtarefa (o nome varia por tipo/versão).
_FORM_RESP_KEYS = ("value", "response", "result", "answer", "text_value",
                   "task_form_item_value", "value_description", "observation")


def _form_item_resposta(it: dict) -> str:
    """Melhor esforço p/ extrair a resposta dada numa subtarefa (o nome do campo varia no Fracttal)."""
    for k in _FORM_RESP_KEYS:
        v = it.get(k)
        if v not in (None, "", "None", "null", "NaN"):
            return str(v).strip()
    if it.get("id_task_form_item_type") == 4:        # só Verificação usa o 'done' como resposta
        dn = str(it.get("done")).lower()
        if dn == "true":
            return "Sim / OK"
        if dn == "false":
            return "Não / pendente"
    return ""                                         # Texto/outros sem valor → frontend mostra "(sem resposta)"


_personnel_name_cache = {}   # id_personnel -> nome (preenchido sob demanda, p/ resolver o atribuído)


def _personnel_nome_por_id() -> dict:
    """Mapa {id_personnel: nome} de TODO o pessoal (cacheado p/ a sessão)."""
    if not _personnel_name_cache:
        try:
            m = {p["id_personnel"]: p["name"] for p in get_responsaveis()
                 if p.get("id_personnel") is not None}
            if m:
                _personnel_name_cache.update(m)
        except FracttalError:
            pass
    return _personnel_name_cache


# campos de NOME do atribuído/responsável que a resposta do Fracttal pode trazer (shape variável)
_ATRIB_NOME_KEYS = ("personnel_description", "assigned_user_name", "responsible_description",
                    "id_assigned_user_description", "name_assigned_user", "accounts_name")


def _nome_atribuido(fontes) -> str:
    """1º campo de NOME não-vazio em qualquer das fontes (tarefas/cabeçalho da WO). '' se nenhum."""
    for src in fontes:
        if not isinstance(src, dict):
            continue
        for k in _ATRIB_NOME_KEYS:
            v = str(src.get(k) or "").strip()
            if v and v.lower() != "none":
                return v
    return ""


def _ids_atribuido(fontes) -> list:
    """IDs do atribuído/responsável (id_assigned_user/id_responsible) presentes nas fontes."""
    ids = []
    for src in fontes:
        if not isinstance(src, dict):
            continue
        for k in ("id_assigned_user", "id_responsible"):
            iv = src.get(k)
            if iv not in (None, "", 0) and iv not in ids:
                ids.append(iv)
    return ids


def _solicitacao_da_os(id_work_order, det, t0) -> str:
    """Nº (id_code) da solicitação de serviço ligada a esta OS. Tenta um código direto no cabeçalho/
    tarefa; senão consulta requests_list filtrando por id_work_order (confere o vínculo). '' se nenhuma."""
    for src in (det, t0):
        if not isinstance(src, dict):
            continue
        for k in ("request_code", "requests_id_code", "id_code_request", "code_request"):
            v = src.get(k)
            if v not in (None, "", 0):
                return str(v)
    if not id_work_order:
        return ""
    try:
        res = _rpc_call(RPC_REQ_LIST, {"filter": [{"operator": "=", "property": "id_work_order",
            "value": id_work_order}], "page": 1, "limit": 5, "start": 0})
    except FracttalError:
        return ""
    data = res.get("data") if isinstance(res, dict) else res
    for r in (data if isinstance(data, list) else []):
        if (isinstance(r, dict) and str(r.get("id_work_order")) == str(id_work_order)
                and r.get("id_code") not in (None, "", 0)):
            return str(r.get("id_code"))
    return ""


def get_os_detalhes(id_work_order) -> dict:
    """Detalhe de UMA OS p/ o histórico. → {'folio','descricao','tipo','event_date','responsavel',
    'notas','subtarefas':[{'descricao','feito','tipo','resposta'}]}. event_date/notas da tarefa;
    subtarefas (descrição + tipo + resposta dada) vêm dos form items; responsavel = atribuído da OS."""
    rt = _rpc_call(RPC_WO_TASKS, {"id_work_order": id_work_order, "sort": []})
    tasks = rt.get("data") if isinstance(rt, dict) else rt
    tasks = tasks if isinstance(tasks, list) else []
    rf = _rpc_call(RPC_WO_FORMIT, {"id_work_order": id_work_order})
    items = rf.get("data") if isinstance(rf, dict) else rf
    items = items if isinstance(items, list) else []
    t0 = tasks[0] if tasks else {}
    notas = []
    for t in tasks:                                  # junta note + task_note de todas as tarefas
        for k in ("note", "task_note"):
            v = str(t.get(k) or "").strip()
            if v and v.lower() != "none" and v not in notas:
                notas.append(v)
    subtarefas = []
    for it in sorted(items, key=lambda x: x.get("order_number") or 0):
        desc = str(it.get("description") or "").strip()
        if not desc:
            continue
        tid = it.get("id_task_form_item_type")
        tipo = (_FORM_ITEM_TYPE_DESC.get(tid)
                or str(it.get("task_form_item_type_description") or "").strip() or "—")
        subtarefas.append({"descricao": desc, "feito": str(it.get("done")).lower() == "true",
                           "tipo": tipo, "resposta": _form_item_resposta(it)})
    code0 = (t0.get("code_item") or "").strip() or _extrai_code(str(t0.get("items_description") or ""))
    ativo0 = (str(t0.get("items_description") or "").split("{")[0]).strip()[:60] or code0
    # cabeçalho da WO (sempre) → responsável + quem criou + solicitação ligada
    det = {}
    try:
        rd = _rpc_call(RPC_WO_DETAILS, {"id": id_work_order, "get_iso_codes": False})
        det = rd.get("data") if isinstance(rd, dict) else rd
        det = det[0] if isinstance(det, list) and det else (det if isinstance(det, dict) else {})
    except FracttalError:
        det = {}
    resp = _nome_atribuido(tasks) or _nome_atribuido([det])
    if not resp:
        ids = _ids_atribuido(list(tasks) + [det])
        nm = _personnel_nome_por_id() if ids else {}
        nomes = [nm.get(i) for i in ids if nm.get(i)]
        resp = " / ".join(dict.fromkeys(nomes)) if nomes else ""
    criado_por = str(det.get("created_by") or det.get("creation_user")
                     or det.get("accounts_name") or t0.get("created_by") or "").strip()
    solic = _solicitacao_da_os(id_work_order, det, t0)
    return {"folio": t0.get("wo_folio"),
            "descricao": str(t0.get("tasks_description") or "").strip(),
            "tipo": str(t0.get("tasks_types_main_description") or "").strip(),
            "event_date": t0.get("event_date"),
            "responsavel": resp,
            "criado_por": criado_por,
            "solicitacao": solic,
            "notas": "\n".join(notas),
            "subtarefas": subtarefas,
            "code": code0, "ativo": ativo0}


# ── Fotos anexadas às subtarefas da OS ────────────────────────────────────────
RPC_WO_IMAGES = "tasks.work_orders_tasks_images_all_list"


def _img_url(d: dict):
    """URL (pré-assinada S3) da imagem cheia na resposta — prefere amazonaws/extensão de imagem."""
    cands = [v for v in d.values() if isinstance(v, str) and v.lower().startswith("http")]
    if not cands:
        return None
    for v in cands:
        low = v.lower()
        if "amazonaws" in low or any(e in low for e in (".jpg", ".jpeg", ".png", ".webp", ".gif")):
            return v
    return cands[0]


def _is_img_b64(s) -> bool:
    """True se a string parece base64 de imagem (PNG/JPEG/GIF) — por ASSINATURA, não por tamanho."""
    return isinstance(s, str) and (s.startswith("data:image") or s[:4] == "/9j/"
                                   or s[:5] in ("iVBOR", "R0lGO"))


def _img_thumb(d: dict):
    """Thumbnail em base64, se a resposta trouxer (campos variáveis / assinatura de imagem)."""
    for k in ("thumbnail", "thumb", "base64", "image_base64", "img_base64", "preview"):
        v = d.get(k)
        if _is_img_b64(v) or (isinstance(v, str) and len(v) > 200 and not v.lower().startswith("http")):
            return v
    for v in d.values():
        if _is_img_b64(v):
            return v
    return None


def get_os_imagens(id_work_order) -> list:
    """Fotos anexadas às subtarefas de UMA OS (1 chamada → todas). Cada foto: URL pré-assinada da S3
    (imagem cheia) + thumbnail base64 (se vier) + descrição da subtarefa de origem. Parse DEFENSIVO —
    os nomes exatos dos campos ainda serão confirmados ao vivo. → [{'url','thumb','descricao','raw'}]."""
    try:
        res = _rpc_call(RPC_WO_IMAGES, {"id_work_order": id_work_order,
            "sort": [{"property": "order_number", "direction": "asc"}]})
    except FracttalError:
        return []
    data = res.get("data") if isinstance(res, dict) else res
    out = []
    for d in (data if isinstance(data, list) else []):
        if not isinstance(d, dict):
            continue
        url, thumb = _img_url(d), _img_thumb(d)
        if not (url or thumb):
            continue
        out.append({"url": url, "thumb": thumb,
                    "descricao": str(d.get("description") or d.get("task_description")
                                     or d.get("items_log_description") or "").strip(),
                    "raw": d})
    return out


def baixar_imagem(url) -> bytes:
    """Bytes de uma imagem por URL pré-assinada (S3 — sem cabeçalhos de auth)."""
    if not url:
        raise FracttalError("Imagem sem URL para download.")
    try:
        r = requests.get(url, timeout=30)
    except requests.RequestException as e:
        raise FracttalError(f"Erro ao baixar a imagem: {e}")
    if r.status_code >= 400:
        raise FracttalError(f"Falha ao baixar a imagem (HTTP {r.status_code}).")
    return r.content


# ── Cancelar OS ───────────────────────────────────────────────────────────────
RPC_WO_CANCEL        = "tasks.work_order_cancel"
RPC_WO_STATUS_CUSTOM = "tasks.work_orders_status_custom_list"   # lista dos MOTIVOS de cancelamento


def get_cancel_motivos() -> list:
    """Motivos de cancelamento de OS (status custom). → [{'id','description'}], ordenado por descrição."""
    r = _rpc_call(RPC_WO_STATUS_CUSTOM, {"sort": [{"property": "description", "direction": "asc"}],
                                         "page": 1, "limit": 200, "start": 0, "is_tree": False, "node": None})
    data = r.get("data") if isinstance(r, dict) else r
    out = []
    for d in (data if isinstance(data, list) else []):
        idc = d.get("id") if d.get("id") is not None else d.get("id_work_orders_status_custom")
        if idc is not None:
            out.append({"id": idc, "description": str(d.get("description") or "?")})
    return out


# ── Tipo de tarefa + Classificação 1/2 (listas ao vivo p/ os dropdowns de criação) ──
_TIPOS_CACHE = {}                              # {key: [{'id','description'}]} — 1 fetch por sessão


def _lista_tipos(metodo: str, key: str) -> list:
    """Busca uma lista de tipos/classificações (id+description), ordenada por descrição. Cacheia."""
    if _TIPOS_CACHE.get(key) is not None:
        return _TIPOS_CACHE[key]
    r = _rpc_call(metodo, {"sort": [{"property": "description", "direction": "asc"}],
                           "page": 1, "limit": 300, "start": 0, "is_tree": False, "node": None})
    data = r.get("data") if isinstance(r, dict) else r
    out = []
    for d in (data if isinstance(data, list) else []):
        idv = d.get("id")
        if idv is None:                            # alguns endpoints nomeiam o id de outro jeito
            for k in ("id_task_type_main", "id_task_type", "id_task_type_2"):
                if d.get(k) is not None:
                    idv = d.get(k); break
        if idv is not None:
            out.append({"id": idv, "description": str(d.get("description") or "?")})
    _TIPOS_CACHE[key] = out
    return out


def get_task_types() -> list:
    """Tipos de tarefa AO VIVO (id_task_type_main) — inclui Religamento/Religamento Remoto."""
    return _lista_tipos(RPC_TIPOS_MAIN, "main")


def get_classif1() -> list:
    """Classificação 1 (id_task_type)."""
    return _lista_tipos(RPC_TIPOS_C1, "c1")


def get_classif2() -> list:
    """Classificação 2 (id_task_type_2)."""
    return _lista_tipos(RPC_TIPOS_C2, "c2")


def get_tipos_classif() -> dict:
    """Tipo de tarefa + Classif 1 + Classif 2 numa chamada só (p/ a UI carregar tudo em 1 worker)."""
    return {"tipos": get_task_types(), "c1": get_classif1(), "c2": get_classif2()}


# ── PCM: planos de tarefa de um ativo (MPS/MPA/MPM/Handover) ──────────────────
RPC_TASK_EVENTS = "tasks.task_events_list"


def get_task_plans(id_item, id_group_task=None) -> list:
    """Planos de tarefa (eventos programados) de um ativo → [{id_task, description}].
    São os MPS/MPA/MPM/Handover que o Fracttal oferece p/ o ativo. PARSE DEFENSIVO — a estrutura
    exata da resposta ainda será confirmada (ajustar os campos quando vier a captura real)."""
    if not id_item:
        return []
    r = _rpc_call(RPC_TASK_EVENTS, {"filter": [], "sort": [], "page": 1, "limit": 200, "start": 0,
                                    "is_tree": False, "node": None,
                                    "id_item": id_item, "id_group_task": id_group_task})
    data = r.get("data") if isinstance(r, dict) else r
    out = []
    for d in (data if isinstance(data, list) else []):
        if not isinstance(d, dict):
            continue
        idt = d.get("id_task") if d.get("id_task") is not None else d.get("id")
        desc = (d.get("description") or d.get("tasks_description") or d.get("task_description")
                or d.get("code") or "")
        if idt is not None:
            out.append({"id_task": idt, "description": str(desc).strip() or f"Plano {idt}",
                        "raw": d})
    return out


RPC_TASK_DETAILS = "tasks.tasks_details"


def _find_subtasks(plan: dict) -> list:
    """Acha a lista de subtarefas (form items) na resposta do tasks_details (shape variável)."""
    if not isinstance(plan, dict):
        return []
    cands = ["subtasks", "task_form_items", "tasks_form_items", "form_items", "submodules", "items"]
    for k in cands + list(plan.keys()):
        v = plan.get(k)
        if isinstance(v, list) and v and isinstance(v[0], dict) and "id_task_form_item_type" in v[0]:
            return v
    return []


def get_plan_details(id_task, id_item) -> dict:
    """Detalhe do plano (subtarefas + tipo/classif + descrição + duração) p/ montar a OS planejada.
    Parse DEFENSIVO do tasks_details (estrutura exata a confirmar ao vivo)."""
    r = _rpc_call(RPC_TASK_DETAILS, {"page": 1, "limit": 200, "start": 0, "append": True,
        "id_task": id_task, "include_submodules_data": True, "is_from_unplanned": True, "id_item": id_item})
    data = r.get("data") if isinstance(r, dict) else r
    plan = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else {})
    if not isinstance(plan, dict):
        plan = {}
    return {"id_task": id_task,
            "description": plan.get("description") or plan.get("task_description") or "",
            "id_task_type_main": plan.get("id_task_type_main"),
            "id_task_type": plan.get("id_task_type"),
            "id_task_type_2": plan.get("id_task_type_2"),
            "tasks_types_main_description": plan.get("tasks_types_main_description") or "",
            "tasks_types_description": plan.get("tasks_types_description") or "",
            "tasks_types_2_description": plan.get("tasks_types_2_description") or "",
            "duration": int(plan.get("duration") or 900),
            "subtasks": _find_subtasks(plan), "raw": plan}


def _react_insert_post(body: list) -> dict:
    """POST do tasks_noscheduled_react_insert + parse da resposta (id_work_order/wo_folio/id_task)."""
    try:
        r = requests.post(RPC_PROXY_URL, headers=_rpc_headers(), json=body, timeout=45)
    except requests.RequestException as e:
        raise FracttalError(f"Erro de conexão com o RPC do Fracttal: {e}")
    if r.status_code in (401, 403):
        raise SessionExpired("Login recusado — sua sessão do Fracttal venceu. Relogue.")
    if r.status_code >= 400:
        raise FracttalError(f"RPC HTTP {r.status_code} — {(r.text or 'sem detalhes')[:240]}")
    try:
        j = r.json()
    except ValueError:
        raise FracttalError(f"RPC devolveu resposta não-JSON: {(r.text or '')[:200]}")
    rec = j[0] if isinstance(j, list) and j else j
    if isinstance(rec, dict) and rec.get("error"):
        err = rec["error"]
        raise FracttalError(f"RPC erro: {str(err.get('message') if isinstance(err, dict) else err)[:240]}")
    result = rec.get("result") if isinstance(rec, dict) else None
    if isinstance(result, list) and result:
        result = result[0]
    if isinstance(result, dict) and result.get("success") is False:
        raise FracttalError(f"RPC recusou: {result.get('message') or 'sem detalhe'}")
    data = result.get("data") if isinstance(result, dict) else {}
    data = data if isinstance(data, dict) else {}
    return {"id_task": data.get("id_task"), "id_work_order": data.get("id_work_order"),
            "wo_folio": data.get("wo_folio"), "raw": result}


def create_planned_os(asset: dict, plan: dict, id_responsible=None, responsible_name: str = "",
                      event_date: datetime = None, to_work_order: bool = True) -> dict:
    """Cria 1 tarefa planejada (tasks_noscheduled_react_insert com o plano: id_task + subtarefas +
    tipo do plano). `to_work_order=True` → vira WO direto (1 ativo). `to_work_order=False` → tarefa
    PENDENTE no kanban (p/ depois juntar várias numa OS só, via create_planned_os_one_wo).
    `plan` = get_plan_details. Devolve {'id_task','id_work_order','wo_folio','raw'}."""
    id_item = asset.get("id")
    if not id_item:
        raise FracttalError(f"Ativo '{asset.get('code')}' sem id_item — recarregue os ativos.")
    if not plan.get("id_task"):
        raise FracttalError("Plano sem id_task.")
    if not plan.get("subtasks"):
        raise FracttalError("Não carreguei as subtarefas do plano (estrutura do tasks_details a confirmar) "
                            "— relogue e/ou me mande a resposta do tasks_details.")
    ev = event_date if event_date is not None else datetime.now(timezone.utc)
    if ev.tzinfo is None:
        ev = ev.replace(tzinfo=timezone.utc)
    dur = int(plan.get("duration") or 900)
    params = {
        "event_date": _iso_z(ev),
        "cal_date_maintenance": _iso_z(ev + timedelta(minutes=10)),
        "date_maintenance": _iso_z(ev + timedelta(minutes=10)),
        "initial_date": _iso_z(ev - timedelta(minutes=10)),
        "final_date": _iso_z(ev + timedelta(minutes=20)),
        "type_user": "HUMAN_RESOURCES", "id_priorities": ID_PRIORITIES,
        "id_failure_severity": 0, "id_damage_type": 1, "failure_asset": False,
        "to_in_review": False, "work_done": False, "to_work_order": to_work_order, "stop_assets": False,
        "duration": dur, "real_duration": 0,
        "requested_by": (responsible_name or "").strip() or "GridCo O&M", "edit_mode": False,
        "tasks_types_main_description": plan.get("tasks_types_main_description") or "",
        "subtasks": plan.get("subtasks") or [], "array_resources": [],
        "id_item": id_item, "items_description": asset.get("description") or "",
        "id_request": None, "note": "", "name": (responsible_name or "").strip() or None,
        "available": None, "initial_date_out_of_service": None,
        "id_group_task": asset.get("id_group_task"), "assigment_date": _iso_z(ev),
        "id_work_order_task_related": None, "date_asset_out_of_service": None,
        "description": plan.get("description") or "", "id_type_item": asset.get("id_type_item") or 1,
        "path_node": _path_node(asset), "msg_availability": "ASSET_OUT_OF_SERVICE",
        "id_task_reference": plan.get("id_task"), "id_task": plan.get("id_task"),
        "id_task_type_main": plan.get("id_task_type_main"),
        "id_task_type": plan.get("id_task_type"), "id_task_type_2": plan.get("id_task_type_2"),
        "tasks_types_description": plan.get("tasks_types_description") or "",
        "tasks_types_2_description": plan.get("tasks_types_2_description") or "",
        "task_note": "",
    }
    if to_work_order and id_responsible is not None:      # WO direto (1 ativo) → atribui o responsável
        params["id_assigned_user"] = id_responsible
    body = [{"id": str(uuid.uuid4()), "jsonrpc": "2.0", "method": RPC_METHOD, "params": params}]
    return _react_insert_post(body)


def _plan_family(desc) -> str:
    """Família do plano a partir da descrição ('[Cliente] - MPM - ...' / 'Handover – ...').
    → 'MPM'/'MPA'/'MPS'/'MPQ'/'MPW'/'MPT'/'Handover' ou None."""
    import re
    d = str(desc or "")
    if "handover" in d.lower():
        return "Handover"
    m = re.search(r"\bMP[A-Z]\b", d.upper())
    return m.group(0) if m else None


def get_plans_for_assets(assets: list) -> list:
    """Planos de tarefa de VÁRIOS ativos (1 task_events_list por ativo, em paralelo). Cada plano vem
    com o ATIVO e a FAMÍLIA (parseada da descrição). → [{id_task, description, family, asset, asset_label}]."""
    alist = [a for a in (assets or []) if isinstance(a, dict) and a.get("id")]

    def _one(a):
        try:
            r = _rpc_call(RPC_TASK_EVENTS, {"filter": [], "sort": [], "page": 1, "limit": 300, "start": 0,
                "is_tree": False, "node": None, "id_item": a.get("id"), "id_group_task": a.get("id_group_task")})
        except FracttalError:
            return []
        data = r.get("data") if isinstance(r, dict) else r
        res = []
        for d in (data if isinstance(data, list) else []):
            if not isinstance(d, dict):
                continue
            idt = d.get("id_task") if d.get("id_task") is not None else d.get("id")
            desc = d.get("task_description") or d.get("tasks_description") or d.get("description") or ""
            if idt is not None:
                res.append({"id_task": idt, "description": str(desc).strip(),
                            "family": _plan_family(desc), "asset": a,
                            "asset_label": a.get("label") or a.get("code") or "?"})
        return res
    out = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for r in ex.map(_one, alist):
            out.extend(r)
    return out


def get_subtask_counts(pares: list) -> dict:
    """Nº de subtarefas de cada plano. `pares` = [(id_task, id_item)]. → {id_task: n} (em paralelo,
    via tasks_details). Defensivo: plano que falhar/sem subtarefa não entra no dict (a UI mostra '?')."""
    uniq = {}
    for p in (pares or []):
        try:
            idt, idi = p
        except (TypeError, ValueError):
            continue
        if idt is not None and idt not in uniq:
            uniq[idt] = idi

    def _one(item):
        idt, idi = item
        try:
            det = get_plan_details(idt, idi)
            return (idt, len(det.get("subtasks") or []))
        except Exception:
            return (idt, None)
    out = {}
    if not uniq:
        return out
    with ThreadPoolExecutor(max_workers=8) as ex:
        for idt, n in ex.map(_one, list(uniq.items())):
            if n is not None:
                out[idt] = n
    return out


def create_planned_os_multi(selecoes: list, id_responsible, responsible_name: str = "",
                            event_date: datetime = None) -> dict:
    """1 OS com as tarefas dos planos SELECIONADOS — `selecoes` = [{asset, id_task[, event_date]}]. Para
    cada um: busca as subtarefas (tasks_details) e cria a tarefa PENDENTE (com a data da própria linha,
    se houver, senão a `event_date` geral); Fase 2 junta tudo numa OS só.
    → {'ok','os':{id_work_order,wo_folio,id_tasks},'n_tarefas','n_criadas','erros'[,'aviso']}."""
    sel = [s for s in (selecoes or []) if isinstance(s.get("asset"), dict) and s.get("id_task")]
    if not sel:
        return {"ok": False, "erro": "Nenhum plano selecionado.", "n_tarefas": 0, "n_criadas": 0}
    id_tasks, erros = [], []
    for s in sel:
        asset, idt = s["asset"], s["id_task"]
        try:
            plan = get_plan_details(idt, asset.get("id"))
            if not plan.get("subtasks"):
                erros.append(f"{asset.get('code')}: plano sem subtarefas"); continue
            r = create_planned_os(asset, plan, event_date=s.get("event_date") or event_date,
                                  to_work_order=False)
            if r.get("id_task"):
                id_tasks.append(r["id_task"])
            else:
                erros.append(f"{asset.get('code')}: tarefa não criada")
        except FracttalError as e:
            erros.append(f"{asset.get('code')}: {e}")
    if not id_tasks:
        return {"ok": False, "erro": "Falha ao criar as tarefas: " + "; ".join(erros[:3]),
                "n_tarefas": len(sel), "n_criadas": 0}
    try:
        recs_map = _kanban_records(set(id_tasks))
    except FracttalError as e:
        return {"ok": True, "os": {"id_tasks": id_tasks}, "n_tarefas": len(sel), "n_criadas": len(id_tasks),
                "erros": erros, "aviso": f"tarefas criadas; não gerei a OS numerada ({e})."}
    recs = [recs_map[i] for i in id_tasks if i in recs_map]
    if not recs:
        return {"ok": True, "os": {"id_tasks": id_tasks}, "n_tarefas": len(sel), "n_criadas": len(id_tasks),
                "erros": erros, "aviso": "tarefas criadas, mas não as achei no kanban p/ gerar a OS."}
    wo = _work_order_insert(recs, id_responsible, responsible_name)
    return {"ok": True, "n_tarefas": len(sel), "n_criadas": len(id_tasks), "erros": erros,
            "os": {"id_work_order": wo.get("id_work_order"), "wo_folio": wo.get("wo_folio"), "id_tasks": id_tasks}}


def create_planned_os_one_wo(assets: list, plan: dict, id_responsible, responsible_name: str = "",
                             event_date: datetime = None) -> dict:
    """Cria UMA OS com VÁRIAS tarefas — cada ativo vira 1 tarefa (com as subtarefas do plano).
    Mesmo molde do clone: Fase 1 cria N tarefas planejadas PENDENTES; Fase 2 junta no kanban e faz
    1 work_order_insert → 1 OS multi-tarefa + responsável.
    → {'ok','os':{id_work_order,wo_folio,id_tasks},'n_tarefas','n_criadas','erros'[,'aviso']}."""
    val = []
    for a in (assets or []):
        asset = a if isinstance(a, dict) else _asset_by_code(a)
        if isinstance(asset, dict) and asset.get("id"):
            val.append(asset)
    if not val:
        return {"ok": False, "erro": "Nenhum ativo válido.", "n_tarefas": 0, "n_criadas": 0}
    if not plan.get("subtasks"):
        return {"ok": False, "erro": "Plano sem subtarefas (estrutura do tasks_details a confirmar) — "
                "relogue e/ou me mande a resposta do tasks_details.", "n_tarefas": len(val), "n_criadas": 0}
    # Fase 1 — N tarefas planejadas PENDENTES (1 por ativo)
    id_tasks, erros = [], []
    for asset in val:
        try:
            r = create_planned_os(asset, plan, event_date=event_date, to_work_order=False)
            if r.get("id_task"):
                id_tasks.append(r["id_task"])
            else:
                erros.append(f"{asset.get('code')}: tarefa não criada")
        except FracttalError as e:
            erros.append(f"{asset.get('code')}: {e}")
    if not id_tasks:
        return {"ok": False, "erro": "Falha ao criar as tarefas: " + "; ".join(erros[:3]),
                "n_tarefas": len(val), "n_criadas": 0}
    # Fase 2 — junta os registros do kanban e cria 1 WO com TODAS as tarefas
    try:
        recs_map = _kanban_records(set(id_tasks))
    except FracttalError as e:
        return {"ok": True, "os": {"id_tasks": id_tasks}, "n_tarefas": len(val), "n_criadas": len(id_tasks),
                "erros": erros, "aviso": f"tarefas criadas; não gerei a OS numerada ({e})."}
    recs = [recs_map[i] for i in id_tasks if i in recs_map]
    if not recs:
        return {"ok": True, "os": {"id_tasks": id_tasks}, "n_tarefas": len(val), "n_criadas": len(id_tasks),
                "erros": erros, "aviso": "tarefas criadas, mas não as achei no kanban p/ gerar a OS."}
    wo = _work_order_insert(recs, id_responsible, responsible_name)
    return {"ok": True, "n_tarefas": len(val), "n_criadas": len(id_tasks), "erros": erros,
            "os": {"id_work_order": wo.get("id_work_order"), "wo_folio": wo.get("wo_folio"),
                   "id_tasks": id_tasks}}


def cancel_os(id_work_order, id_status_custom, note: str = "", cancellation_type: int = 1,
              utc_min: int = -180) -> dict:
    """Cancela a OS via tasks.work_order_cancel. id_status_custom = MOTIVO (de get_cancel_motivos);
    cancellation_type=1 ('Cancelar OS', fixo); utc_min=-180 (Brasília). A AUTORIZAÇÃO é do Fracttal —
    se a conta não puder cancelar, a API recusa (FracttalError). → {'ok':True,'raw':...}."""
    if not id_work_order:
        raise FracttalError("OS sem id — recarregue o histórico.")
    if not id_status_custom:
        raise FracttalError("Escolha o motivo do cancelamento.")
    params = {"id": id_work_order, "id_work_orders_status_custom": id_status_custom,
              "note": (note or "").strip(), "cancellation_type": cancellation_type, "utc_min": utc_min}
    res = _rpc_call(RPC_WO_CANCEL, params)
    if isinstance(res, dict) and res.get("success") is False:      # recusa não-sessão (ex.: sem permissão)
        raise FracttalError(str(res.get("message") or "Cancelamento recusado pelo Fracttal "
                                                      "(sua conta tem permissão p/ cancelar OS?)."))
    return {"ok": True, "raw": res}


# ── Clonar OS: lê a OS de referência (ativo + tipo + descrição + subtarefas + etiquetas) ──
RPC_WO_DETAILS = "tasks.work_order_details_new"   # cabeçalho da WO (labels, etc.)


def _wo_id_por_folio(folio):
    """Resolve o nº da OS (wo_folio) → id_work_order, varrendo a lista por status. None se não achar."""
    folio = str(folio).strip()
    if not folio:
        return None
    for st in (1, 2, 3, 4):
        try:
            res = _rpc_call(RPC_WO_LIST, {"page": 1, "limit": 50, "start": 0, "append": True,
                            "id_status_work_order": st,
                            "filter": [{"operator": "=", "property": "wo_folio", "value": folio}],
                            "sort": [{"property": "id", "direction": "desc"}]})
        except FracttalError:
            continue
        for w in (res.get("data") or []):
            if str(w.get("wo_folio")).strip() == folio:
                return w.get("id")
    return None


def get_os_para_clonar(id_work_order) -> dict:
    """Lê uma OS p/ CLONAR — TODAS as tarefas (a OS pode ter vários ativos). →
    {'folio','tarefas':[{'code','asset'(dict do catálogo ou None),'tipo','descricao',
     'subtarefas':[str],'notas'}],'etiqueta_ids':[int],'notas','n_sem_ativo'}.
    Cada tarefa traz seu próprio ativo (resolvido do code_item/items_description), tipo,
    descrição e subtarefas (form items agrupados por id_work_order_task = id da tarefa)."""
    rt = _rpc_call(RPC_WO_TASKS, {"id_work_order": id_work_order, "sort": []})
    tasks = rt.get("data") if isinstance(rt, dict) else rt
    tasks = tasks if isinstance(tasks, list) else []
    rf = _rpc_call(RPC_WO_FORMIT, {"id_work_order": id_work_order})
    items = rf.get("data") if isinstance(rf, dict) else rf
    items = items if isinstance(items, list) else []
    # subtarefas (form items) agrupadas por tarefa (id_work_order_task == id da tarefa).
    # Guarda o TIPO original de cada uma (id_task_form_item_type etc.) p/ o clone preservar
    # Verificação/Texto/etc. em vez de rebaixar tudo p/ Texto.
    subs_por_tarefa = {}
    for it in sorted(items, key=lambda x: x.get("order_number") or 0):
        d = str(it.get("description") or "").strip()
        if not d:
            continue
        subs_por_tarefa.setdefault(it.get("id_work_order_task"), []).append({
            "description": d,
            "id_task_form_item_type": it.get("id_task_form_item_type"),
            "task_form_item_type_description": it.get("task_form_item_type_description"),
            "id_task_form_item_group": it.get("id_task_form_item_group"),
            "task_form_item_group_description": it.get("task_form_item_group_description"),
            "is_required": bool(it.get("is_required")),
            "attachments_required": bool(it.get("attachments_required")),
            "dropdown_options": it.get("dropdown_options"),
        })
    folio = None
    tarefas = []
    notas_os = []
    n_sem_ativo = 0
    for t in tasks:
        folio = folio or t.get("wo_folio")
        code = (t.get("code_item") or "").strip() or _extrai_code(str(t.get("items_description") or ""))
        asset = _asset_by_code(code) if code else None
        if asset is None:
            n_sem_ativo += 1
        tipo = str(t.get("tasks_types_main_description") or "").strip()
        notas_t = []
        for k in ("note", "task_note"):
            v = str(t.get(k) or "").strip()
            if v and v.lower() != "none" and v not in notas_t:
                notas_t.append(v)
            if v and v.lower() != "none" and v not in notas_os:
                notas_os.append(v)
        subt = subs_por_tarefa.get(t.get("id")) or subs_por_tarefa.get(t.get("id_work_order_task")) or []
        tarefas.append({
            "code": code, "asset": asset,
            "tipo": tipo if tipo in TASK_TYPE_MAIN else "Corretiva",
            "descricao": str(t.get("tasks_description") or "").strip(),
            "ativo_nome": (str(t.get("items_description") or "").split("{")[0]).strip()[:60] or code,
            "subtarefas": subt, "notas": "\n".join(notas_t),
            "event_date_orig": t.get("event_date"),        # data programada original (ISO UTC), p/ prefill
        })
    etiqueta_ids = []
    try:                                              # etiquetas vêm do cabeçalho da WO
        rd = _rpc_call(RPC_WO_DETAILS, {"id": id_work_order, "get_iso_codes": False})
        det = rd.get("data") if isinstance(rd, dict) else rd
        det = det[0] if isinstance(det, list) and det else (det if isinstance(det, dict) else {})
        etiqueta_ids = [l.get("id") for l in (det.get("labels") or [])
                        if isinstance(l, dict) and l.get("id") is not None]
    except FracttalError:
        pass
    return {"folio": folio, "tarefas": tarefas, "etiqueta_ids": etiqueta_ids,
            "notas": "\n".join(notas_os), "n_sem_ativo": n_sem_ativo}


# ── Atualizar subtarefas a partir do MODELO de tarefa do ativo ────────────────
RPC_TASK_EVENTS = "tasks.task_events_list"          # modelos (gatilhos) disponíveis p/ um ativo
RPC_TASK_TEMPLATE_ITEMS = "tasks.tasks_form_items_list"   # subtarefas de um modelo (por id_task)


def _subtarefas_de_modelo(id_task) -> list:
    """Subtarefas (form items) atuais de um modelo de tarefa, pelo id_task do modelo.
    → [{'description','id_task_form_item_type','task_form_item_type_description',...}] ordenadas."""
    res = _rpc_call(RPC_TASK_TEMPLATE_ITEMS, {"id_task": id_task})
    data = res.get("data") if isinstance(res, dict) else res
    out = []
    for it in sorted((data if isinstance(data, list) else []), key=lambda x: x.get("order_number") or 0):
        d = str(it.get("description") or "").strip()
        if not d:
            continue
        out.append({"description": d,
                    "id_task_form_item_type": it.get("id_task_form_item_type"),
                    "task_form_item_type_description": it.get("task_form_item_type_description"),
                    "id_task_form_item_group": it.get("id_task_form_item_group"),
                    "task_form_item_group_description": it.get("task_form_item_group_description"),
                    "is_required": bool(it.get("is_required")),
                    "attachments_required": bool(it.get("attachments_required")),
                    "dropdown_options": it.get("dropdown_options")})
    return out


def get_template_subtarefas(asset: dict, task_description: str) -> dict:
    """Re-seleciona o MODELO de tarefa do mesmo nome p/ o ativo (como ao criar OS e escolher o
    ativo) e devolve as subtarefas ATUAIS desse modelo — p/ o botão 'Atualizar do modelo' do clone.
    Casa o evento pelo nome (tasks_description == task_description).
    → {'achou':bool,'subtarefas':[dict],'nome','id_task','erro'}."""
    id_item = asset.get("id") if isinstance(asset, dict) else None
    if not id_item:
        return {"achou": False, "subtarefas": [], "erro": "Ativo sem id — recarregue os ativos."}
    res = _rpc_call(RPC_TASK_EVENTS, {"filter": [], "sort": [], "page": 1, "limit": 300, "start": 0,
                    "is_tree": False, "node": None, "id_item": id_item,
                    "id_group_task": asset.get("id_group_task")})
    data = res.get("data") if isinstance(res, dict) else res
    alvo = (task_description or "").strip().lower()
    id_task = None
    for e in (data if isinstance(data, list) else []):
        nome = str(e.get("tasks_description") or e.get("task_description") or "").strip()
        if nome.lower() == alvo:
            id_task = e.get("id_task")
            break
    if not id_task:
        return {"achou": False, "subtarefas": [],
                "erro": f"Nenhum modelo com o nome “{task_description}” para este ativo."}
    subs = _subtarefas_de_modelo(id_task)
    return {"achou": True, "subtarefas": subs, "nome": task_description, "id_task": id_task}


def atualizar_modelos_subtarefas(tarefas: list) -> list:
    """Em lote: p/ cada tarefa COM ativo, re-busca o modelo do mesmo nome e devolve as subtarefas
    atuais. NÃO muta as tarefas (a UI aplica, na thread principal). Não interrompe no 1º erro.
    → lista PARALELA a 'tarefas': cada item é None (tarefa sem ativo) ou
      {'achou':bool,'subtarefas':[dict],'erro':str|None}."""
    out = []
    for t in (tarefas or []):
        asset = t.get("asset") if isinstance(t, dict) else None
        if not (isinstance(asset, dict) and asset.get("id")):
            out.append(None)
            continue
        try:
            r = get_template_subtarefas(asset, t.get("descricao") or "")
            out.append({"achou": bool(r.get("achou")), "subtarefas": r.get("subtarefas") or [],
                        "erro": r.get("erro")})
        except FracttalError as e:
            out.append({"achou": False, "subtarefas": [], "erro": str(e)})
    return out


def clonar_os(tarefas: list, id_responsible, responsible_name: str = "",
              etiqueta_ids: list = None, note: str = "", scheduled_date: datetime = None) -> dict:
    """Cria UMA OS nova com TODAS as 'tarefas' dadas (cada uma: asset, tipo, descricao,
    subtarefas — formato de get_os_para_clonar). Fase 1: cria N tarefas pendentes. Fase 2:
    1 work_order_insert com as N → 1 OS multi-tarefa + responsável. Fase 3: etiquetas.
    'note' (se preenchido) sobrescreve a observação de TODAS as tarefas; senão usa a de cada uma.
    Data programada: cada tarefa pode trazer seu próprio 'event_date' (datetime); 'scheduled_date'
    é o fallback p/ as que não tiverem (default de ambos = agora).
    → {'ok','os':{id_work_order,wo_folio,id_tasks[,etiquetas]}|None,'erro','aviso','n_tarefas','n_criadas'}."""
    val = [t for t in (tarefas or []) if isinstance(t.get("asset"), dict) and t["asset"].get("id")]
    if not val:
        return {"ok": False, "erro": "Nenhuma tarefa com ativo resolvido no catálogo — "
                "recarregue os ativos no Criar OS e tente de novo.",
                "n_tarefas": len(tarefas or []), "n_criadas": 0}
    note = (note or "").strip()
    # Fase 1 — cria as tarefas pendentes (uma por tarefa da OS de referência)
    id_tasks, erros = [], []
    for t in val:
        try:
            os_ = create_os_rpc(t["asset"], t.get("descricao") or "", t.get("tipo") or "Corretiva",
                                t.get("subtarefas") or [], requested_by=responsible_name,
                                note=(note or t.get("notas") or ""),
                                event_date=(t.get("event_date") or scheduled_date))
            if os_.get("id_task"):
                id_tasks.append(os_["id_task"])
            else:
                erros.append(f"{t.get('code') or '?'}: tarefa não criada")
        except FracttalError as e:
            erros.append(f"{t.get('code') or '?'}: {e}")
    if not id_tasks:
        return {"ok": False, "erro": "Falha ao criar as tarefas: " + "; ".join(erros[:3]),
                "n_tarefas": len(val), "n_criadas": 0}
    # sem responsável: ficam como tarefas pendentes (não viram OS numerada)
    if not id_responsible:
        return {"ok": True, "os": {"id_tasks": id_tasks, "wo_folio": None},
                "aviso": "tarefas criadas como pendentes (escolha um responsável p/ gerar a OS numerada).",
                "n_tarefas": len(val), "n_criadas": len(id_tasks)}
    # Fase 2 — junta os registros do kanban e cria 1 WO com TODAS as tarefas
    try:
        recs_map = _kanban_records(set(id_tasks))
    except FracttalError as e:
        return {"ok": True, "os": {"id_tasks": id_tasks},
                "aviso": f"tarefas criadas; não consegui gerar a OS numerada ({e}).",
                "n_tarefas": len(val), "n_criadas": len(id_tasks)}
    recs = [recs_map[i] for i in id_tasks if i in recs_map]   # preserva a ordem
    if not recs:
        return {"ok": True, "os": {"id_tasks": id_tasks},
                "aviso": "tarefas criadas, mas não as achei no kanban p/ gerar a OS.",
                "n_tarefas": len(val), "n_criadas": len(id_tasks)}
    wo = _work_order_insert(recs, id_responsible, responsible_name)
    idwo = wo.get("id_work_order")
    os_out = {"id_work_order": idwo, "wo_folio": wo.get("wo_folio"), "id_tasks": id_tasks}
    avisos = []
    if idwo and etiqueta_ids:
        try:
            apply_labels(idwo, etiqueta_ids)
            os_out["etiquetas"] = list(etiqueta_ids)
        except FracttalError as e:
            avisos.append(f"etiqueta falhou: {e}")
    if erros:
        avisos.append(f"{len(erros)} tarefa(s) não criadas: " + "; ".join(erros[:2]))
    return {"ok": True, "os": os_out, "aviso": " | ".join(avisos) or None,
            "n_tarefas": len(val), "n_criadas": len(recs)}


def create_os_sem_plano(selecoes: list, id_responsible, responsible_name: str = "",
                        descricao: str = "", note: str = "", tipo_task: str = "Corretiva") -> dict:
    """1 OS com VÁRIAS tarefas SEM plano de tarefas — cada ativo vira 1 tarefa com a subtarefa PADRÃO
    'Procedimento' (subtasks=[] → _rpc_subtasks injeta 'Procedimento'). `selecoes` = [{asset[,event_date]}];
    `descricao` (vazia = 'Procedimento') vale p/ todas; `note` = observação. Reusa o motor do clone
    (Fase 1 cria as tarefas pendentes; Fase 2 junta numa OS só + responsável).
    → {'ok','os':{...},'n_tarefas','n_criadas','erros'/'erro'[,'aviso']}."""
    desc = (descricao or "").strip() or "Procedimento"
    tarefas = [{"asset": s.get("asset"), "tipo": tipo_task, "descricao": desc,
                "subtarefas": [], "event_date": s.get("event_date")}
               for s in (selecoes or []) if isinstance(s.get("asset"), dict) and s["asset"].get("id")]
    if not tarefas:
        return {"ok": False, "erro": "Nenhum ativo selecionado.", "n_tarefas": 0, "n_criadas": 0}
    return clonar_os(tarefas, id_responsible, responsible_name, etiqueta_ids=None, note=note)


# ── Histórico de Solicitações (work requests) ─────────────────────────────────
RPC_REQ_LIST = "requests.requests_list"
# requests_x_status_description (string estável) → rótulo PT. OT = Ordem de Trabalho (= OS).
REQ_STATUS = {
    "OPEN_STATUS":      "Aberta",
    "OT_IN_PROCESS":    "OS em processo",
    "OT_IN_REVIEW":     "OS em verificação",
    "CLOSE_STATUS":     "Concluída",
    "OT_FINALIZED":     "OS concluída",
    "APPROVED_STATUS":  "Aprovada",
    "REJECTED_STATUS":  "Rejeitada",
    "CANCEL_STATUS":    "Cancelada",
    "SOLVED_WITH_OT_STATUS":    "Resolvida com OS",
    "SOLVED_WITHOUT_OT_STATUS": "Resolvida sem OS",
    "AGAIN_REQUEST_TODO":       "Reaberta (refazer)",
}


def _req_status_label(st_raw, id_status=None):
    """Rótulo PT do status da solicitação. Conhecido → mapa REQ_STATUS; desconhecido → humaniza o
    código cru (ex.: 'FOO_BAR_STATUS' → 'Foo bar') p/ nunca exibir SCREAMING_SNAKE pro usuário."""
    if st_raw in REQ_STATUS:
        return REQ_STATUS[st_raw]
    if st_raw:
        s = st_raw.replace("_STATUS", "").replace("_TODO", "").replace("_", " ").strip()
        return s.capitalize() if s else st_raw
    return f"Status {id_status}" if id_status is not None else "—"


def list_minhas_solicitacoes(id_account=None, limite: int = 120) -> list:
    """Solicitações de serviço (work requests). id_account: None = usuário LOGADO (default);
    "TODOS" = todas; ou um id_account específico = filtra por criador. Cada uma traz a OS ligada
    (wo_folio/id_work_order) e a descrição COMPLETA (p/ o detalhe ao clicar no nº).
    → [{'id_code','cliente','usina','ativo','descricao','descricao_full','observacao','criado_por',
        'data','status_id','status','os_folio','id_work_order'}], mais recentes primeiro."""
    if id_account is None:
        _idp, id_account, _nome = _current_user_info()
        if id_account is None:
            raise FracttalError("Não consegui identificar seu usuário no Fracttal (e-mail não bate no cadastro).")
        filtro = [{"operator": "=", "property": "id_account", "value": id_account}]
    elif id_account == "TODOS":
        filtro = []
    else:
        filtro = [{"operator": "=", "property": "id_account", "value": id_account}]
    res = _rpc_call(RPC_REQ_LIST, {"filter": filtro,
                                   "sort": [{"property": "id_code", "direction": "desc"}],
                                   "page": 1, "limit": limite, "start": 0})
    data = res.get("data") if isinstance(res, dict) else res
    loc = _code_to_loc()
    out = []
    for r in (data if isinstance(data, list) else []):
        item = str(r.get("items_description") or "")
        code = (r.get("code_item") or "").strip() or _extrai_code(item)
        ativo = (item.split("{")[0]).strip()[:60] or code
        cliente, usina, tipo = loc.get(code, ("", "", ""))
        st_raw = r.get("requests_x_status_description") or ""
        desc_full = str(r.get("description") or "").strip()
        out.append({
            "id_code": r.get("id_code"),
            "cliente": cliente or "—", "usina": usina or "—", "ativo": ativo,
            "tipo": tipo or "—",
            "descricao": (desc_full[:90] or "—"),
            "descricao_full": desc_full,
            "observacao": str(r.get("observation") or "").strip(),
            "criado_por": str(r.get("requested_by") or r.get("accounts_name") or "").strip(),
            "data": (str(r.get("date") or r.get("date_incident") or ""))[:19],
            "status_id": r.get("id_status"),
            "status": _req_status_label(st_raw, r.get("id_status")),
            "os_folio": r.get("wo_folio"),
            "id_work_order": r.get("id_work_order"),
        })
    return out


RPC_REQ_STATUS_INSERT = "requests.requests_x_status_insert"


def cancelar_solicitacao(id_request, note: str = "") -> dict:
    """Cancela uma SOLICITAÇÃO de serviço (work request): status vira CANCEL_STATUS (id_status=5),
    com uma nota opcional. `id_request` = id_code da solicitação (o Nº mostrado). A AUTORIZAÇÃO é a do
    usuário no Fracttal — se a conta não puder cancelar, a API recusa (FracttalError). → {'ok':True,'raw'}."""
    if id_request in (None, ""):
        raise FracttalError("Solicitação sem número (id) — recarregue o histórico.")
    params = {"id_request": str(id_request), "id_status": 5,
              "requests_x_status_description": "CANCEL_STATUS", "notes": (note or "").strip()}
    res = _rpc_call(RPC_REQ_STATUS_INSERT, params)
    if isinstance(res, dict) and res.get("success") is False:    # recusa não-sessão (ex.: sem permissão)
        raise FracttalError(str(res.get("message") or "Cancelamento recusado pelo Fracttal "
                                                      "(sua conta tem permissão p/ cancelar solicitações?)."))
    return {"ok": True, "raw": res}


def get_pessoas_contas() -> dict:
    """Contas (quem cria OS/solicitação) p/ o filtro de 'criado por' + a conta do usuário logado.
    Acha o 'eu' (id_account do logado) na MESMA paginação do pessoal — uma passada só.
    → {"pessoas": [{"id_account","nome"}] (ordenado por nome), "eu": id_account_logado}."""
    email = (current_user() or "").strip().lower()
    eu = None
    vistos = {}
    start = 0
    while True:
        res = _rpc_call(RPC_PERSONNEL, {"page": start // 100 + 1, "limit": 100, "start": start,
                                        "append": True, "filter": [], "sort": []})
        data = res.get("data") if isinstance(res, dict) else res
        data = data if isinstance(data, list) else []
        for p in data:
            ida = p.get("id_account")
            if ida is not None and ida not in vistos:
                nome = (p.get("full_name") or p.get("name") or p.get("account_email") or "").strip()
                if nome:
                    vistos[ida] = nome
            if eu is None and email and (p.get("account_email") or p.get("email") or "").strip().lower() == email:
                eu = ida
        start += 100
        if len(data) < 100:
            break
    pessoas = sorted(({"id_account": k, "nome": v} for k, v in vistos.items()),
                     key=lambda x: x["nome"].lower())
    return {"pessoas": pessoas, "eu": eu}


def create_work_orders_bulk(assets: list, description: str, task_type: str, subtasks: list,
                            etiqueta: str = "", responsible_code: str = "",
                            responsible_name: str = "", id_responsible=None,
                            etiqueta_ids: list = None, note: str = "", tipo: dict = None,
                            finalizar: dict = None, event_date=None) -> list:
    """Cria N OS (uma por ativo). Fase 1: cria a tarefa pendente (create_os_rpc). Fase 2 (se
    id_responsible): converte em WO numerada + atribui o responsável. Fase 3 (se etiqueta_ids):
    aplica as etiquetas na WO. NÃO interrompe no 1º erro:
    → [{'code','ok':True,'os':{id_task,id_work_order,wo_folio[,etiquetas][,aviso]}} | {'code','ok':False,'erro'}].
    `finalizar` (OS já realizada) → cada create já devolve a WO concluída c/ responsável → pula Fase 2."""
    fase1 = []
    for a in assets:
        asset = a if isinstance(a, dict) else _asset_by_code(a)
        code = asset.get("code") if isinstance(asset, dict) else str(a)
        if not isinstance(asset, dict):
            fase1.append({"code": code, "ok": False, "erro": "ativo não encontrado no cache."})
            continue
        try:
            os_ = create_os_rpc(asset, description, task_type, subtasks,
                                requested_by=responsible_name, etiqueta=etiqueta, note=note,
                                tipo=tipo, event_date=event_date, finalizar=finalizar)
            fase1.append({"code": code, "ok": True, "os": os_})
        except FracttalError as e:
            fase1.append({"code": code, "ok": False, "erro": str(e)})

    # OS já realizada: a WO concluída já saiu da Fase 1 (to_work_order) → só aplica etiquetas
    if finalizar:
        if etiqueta_ids:
            for r in [x for x in fase1 if x.get("ok") and x["os"].get("id_work_order")]:
                try:
                    apply_labels(r["os"]["id_work_order"], etiqueta_ids)
                    r["os"]["etiquetas"] = list(etiqueta_ids)
                except FracttalError as e:
                    r["os"]["aviso"] = f"WO {r['os'].get('wo_folio')} criada, mas etiqueta falhou: {e}"
        return fase1

    # Fase 2 — converter em WO + responsável (só se um responsável foi escolhido)
    pend = [r for r in fase1 if r.get("ok") and r["os"].get("id_task")]
    if id_responsible and pend:
        try:
            recs = _kanban_records({r["os"]["id_task"] for r in pend})
        except FracttalError as e:
            recs = {}
            for r in pend:
                r["os"]["aviso"] = f"tarefa criada; não converti em WO ({e})."
        for r in pend:
            if "aviso" in r["os"]:
                continue
            rec = recs.get(r["os"]["id_task"])
            if not rec:
                r["os"]["aviso"] = "tarefa criada, mas não a achei no kanban p/ virar WO."
                continue
            try:
                wo = convert_task_to_wo(rec, id_responsible, responsible_name)
                idwo = wo.get("id_work_order")
                r["os"]["id_work_order"] = idwo or r["os"].get("id_work_order")
                r["os"]["wo_folio"] = wo.get("wo_folio") or r["os"].get("wo_folio")
                if idwo and etiqueta_ids:                       # Fase 3 — etiquetas na WO
                    try:
                        apply_labels(idwo, etiqueta_ids)
                        r["os"]["etiquetas"] = list(etiqueta_ids)
                    except FracttalError as e:
                        r["os"]["aviso"] = f"WO {r['os'].get('wo_folio')} criada, mas etiqueta falhou: {e}"
            except FracttalError as e:
                r["os"]["aviso"] = f"tarefa criada, mas falhou virar WO: {e}"
    return fase1


def create_work_orders_datas(asset: dict, description: str, task_type: str, subtasks: list,
                             datas: list, responsible_code: str = "", responsible_name: str = "",
                             id_responsible=None, etiqueta_ids: list = None, note: str = "",
                             tipo: dict = None, finalizar: dict = None) -> list:
    """Cria N OS p/ o MESMO ativo — uma por DATA de incidente. `datas` = lista de datetimes (já no
    horário escolhido; tz-aware = Brasília); se `finalizar`, cada item é uma tupla (inicial, final).
    Mesmas 3 fases do create_work_orders_bulk (tarefa → WO+responsável → etiquetas), sem parar no 1º erro.
    → lista paralela a `datas`: [{'data','ok':True,'os':{...}} | {'data','ok':False,'erro'}]."""
    if not isinstance(asset, dict) or not asset.get("id"):
        return [{"data": None, "ok": False, "erro": "Ativo inválido / sem id — recarregue os ativos."}]
    fase1 = []
    for d in (datas or []):
        if isinstance(d, (tuple, list)):                 # (inicial, final) p/ OS finalizada
            ev_dt, fim_dt = d[0], (d[1] if len(d) > 1 else None)
        else:
            ev_dt, fim_dt = d, None
        rot = ev_dt.strftime("%d/%m %H:%M") if hasattr(ev_dt, "strftime") else str(ev_dt)
        fin = {**finalizar, "final_date": fim_dt} if finalizar else None
        try:
            os_ = create_os_rpc(asset, description, task_type, subtasks,
                                requested_by=responsible_name, etiqueta="", note=note,
                                event_date=ev_dt, tipo=tipo, finalizar=fin)
            fase1.append({"data": rot, "ok": True, "os": os_})
        except FracttalError as e:
            fase1.append({"data": rot, "ok": False, "erro": str(e)})

    if finalizar:                                        # WO concluída já saiu da Fase 1
        if etiqueta_ids:
            for r in [x for x in fase1 if x.get("ok") and x["os"].get("id_work_order")]:
                try:
                    apply_labels(r["os"]["id_work_order"], etiqueta_ids)
                    r["os"]["etiquetas"] = list(etiqueta_ids)
                except FracttalError as e:
                    r["os"]["aviso"] = f"WO {r['os'].get('wo_folio')} criada, mas etiqueta falhou: {e}"
        return fase1

    pend = [r for r in fase1 if r.get("ok") and r["os"].get("id_task")]
    if id_responsible and pend:
        try:
            recs = _kanban_records({r["os"]["id_task"] for r in pend})
        except FracttalError as e:
            recs = {}
            for r in pend:
                r["os"]["aviso"] = f"tarefa criada; não converti em WO ({e})."
        for r in pend:
            if "aviso" in r["os"]:
                continue
            rec = recs.get(r["os"]["id_task"])
            if not rec:
                r["os"]["aviso"] = "tarefa criada, mas não a achei no kanban p/ virar WO."
                continue
            try:
                wo = convert_task_to_wo(rec, id_responsible, responsible_name)
                idwo = wo.get("id_work_order")
                r["os"]["id_work_order"] = idwo or r["os"].get("id_work_order")
                r["os"]["wo_folio"] = wo.get("wo_folio") or r["os"].get("wo_folio")
                if idwo and etiqueta_ids:
                    try:
                        apply_labels(idwo, etiqueta_ids)
                        r["os"]["etiquetas"] = list(etiqueta_ids)
                    except FracttalError as e:
                        r["os"]["aviso"] = f"WO {r['os'].get('wo_folio')} criada, mas etiqueta falhou: {e}"
            except FracttalError as e:
                r["os"]["aviso"] = f"tarefa criada, mas falhou virar WO: {e}"
    return fase1


# ══ Dashboard O&M — fila de OS sugeridas (trackers parados >36h / recorrentes) ══════════════════
# O dashboard (Flask) calcula a fila em /api/trackers/os-sugeridas (atrás de login DASH_PASSWORD).
# Aqui só LEMOS — o técnico/PCM confirma e cria a OS pelo wizard. Config em %APPDATA%.
DASH_CONFIG_FILE = os.path.join(_data_dir(), "dash_config.json")


def load_dash_config() -> dict:
    """Config do dashboard: {url, senha, tunnel_file}. url/senha p/ logar; tunnel_file (opcional) =
    caminho do tunnel_url.txt do dashboard (no OneDrive) p/ pegar a URL atual sozinho."""
    try:
        if os.path.exists(DASH_CONFIG_FILE):
            with open(DASH_CONFIG_FILE, encoding="utf-8") as f:
                d = json.load(f)
                return {"url": (d.get("url") or "").strip(),
                        "senha": d.get("senha") or "",
                        "tunnel_file": (d.get("tunnel_file") or "").strip()}
    except Exception:
        pass
    return {"url": "", "senha": "", "tunnel_file": ""}


def save_dash_config(url: str, senha: str, tunnel_file: str = "") -> None:
    with open(DASH_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"url": (url or "").strip(), "senha": senha or "",
                   "tunnel_file": (tunnel_file or "").strip()}, f, ensure_ascii=False)


def _dash_url(cfg: dict) -> str:
    """URL efetiva: se houver tunnel_file legível, usa o conteúdo dele (sempre fresco); senão a url fixa."""
    tf = cfg.get("tunnel_file")
    if tf and os.path.exists(tf):
        try:
            with open(tf, encoding="utf-8") as f:
                u = f.read().strip()
            if u.startswith("http"):
                return u.rstrip("/")
        except Exception:
            pass
    return (cfg.get("url") or "").strip().rstrip("/")


def fetch_os_sugeridas(cfg: dict = None) -> list:
    """Loga no dashboard (sessão + DASH_PASSWORD) e busca /api/trackers/os-sugeridas. Devolve a lista
    de sugestões (rows). Lança RuntimeError com mensagem amigável se URL/senha faltarem ou der erro."""
    cfg = cfg or load_dash_config()
    url = _dash_url(cfg)
    senha = cfg.get("senha") or ""
    if not url:
        raise RuntimeError("Configure a URL do dashboard (botão Configurar).")
    s = requests.Session()
    try:
        if senha:
            s.post(f"{url}/login", data={"senha": senha}, timeout=20, allow_redirects=False)
        r = s.get(f"{url}/api/trackers/os-sugeridas", timeout=30)
    except requests.RequestException as e:
        raise RuntimeError(f"Não consegui falar com o dashboard ({url}). O túnel está no ar? [{e}]")
    if r.status_code == 401:
        raise RuntimeError("Login recusado — confira a senha do dashboard (DASH_PASSWORD).")
    if r.status_code != 200:
        raise RuntimeError(f"Dashboard respondeu HTTP {r.status_code}.")
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError("Resposta do dashboard não é JSON (sessão/URL errada?).")
    if data.get("error"):
        raise RuntimeError(str(data["error"]))
    return data.get("rows", [])
