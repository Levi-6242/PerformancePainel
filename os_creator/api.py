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

# O pacote `chamado_garantia` mora na RAIZ do repositório (é compartilhado com o app de campo),
# então a raiz precisa entrar no sys.path ANTES do primeiro import dele. No .exe isto é inócuo:
# o PyInstaller já empacota o pacote via pathex/hiddenimports do .spec.
_RAIZ_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ_REPO not in sys.path:
    sys.path.insert(0, _RAIZ_REPO)

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
CRITICIDADE_DEFAULT = 3                         # Médio (wizard / OS única)
CRITICIDADE_MUITO_ALTO = 1                      # F1: default do COS (religamento é ~sempre crítico)

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


# Tipo de equipamento a partir do code ({USINA}-{TIPO}{N}). A REGRA mora no `chamado_garantia`
# (03/08): o app de campo precisa classificar o ativo do mesmo jeito para escolher as subtarefas,
# e duas derivações significa dois apps pedindo coisas diferentes ao mesmo fabricante — num ponto
# invisível, porque ninguém percebe até o chamado voltar. Aqui ficou só o repasse.
from chamado_garantia.ativos import TIPO_POR_SUFIXO as TYPE_MAP     # noqa: E402  (nome antigo)
from chamado_garantia.ativos import tipo_e_sufixo


def _tipo_from_code(code: str, eh_usina: bool):
    """→ (tipo_code, tipo_label). Para o item da usina (sem hierarquia abaixo) → ('','Usina')."""
    if eh_usina:
        return "", "Usina"
    return tipo_e_sufixo(code)


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


def _corrigir_itens_usina_estrangeiros(assets: list) -> list:
    """Conserta o item-usina PENDURADO NA PLANTA ERRADA (cadastro do Fracttal, 28/07).

    Caso real: o item-usina de "Thopen - Ipixuna 1 e 2 - PA" (THPN-IPX100) está registrado como
    filho da planta "2C - Ipixuna do Pará 1 - PA" — então o campo `usina` dele apontava para a
    planta da 2C e ele aparecia nas cascatas dela (COS/Performance/Nova análise), como o Levi
    reportou. Medido no catálogo inteiro: 7 itens nessa situação (esse + 6 lixos de TESTE
    pendurados em Sarandi), de 16,9 mil.

    Detecção: item tipo "Usina" cuja DESCRIÇÃO não começa com a própria `usina` — a descrição do
    item-usina legítimo sempre embute o rótulo da planta. Correção: realoca para a usina dos
    IRMÃOS DE CÓDIGO (THPN-IPX100 → usina dos THPN-IPX100-*); sem irmão, `usina` fica vazia e o
    item sai das cascatas (melhor sumir do que aparecer na planta errada). Roda na LEITURA, então
    vale para o cache antigo sem forçar recarga de 17 mil ativos."""
    ruins = [a for a in assets
             if a.get("tipo") == "Usina" and a.get("usina") and a.get("description")
             and not _norm_txt(a["description"]).startswith(_norm_txt(a["usina"]))]
    if not ruins:
        return assets
    for a in ruins:
        code = str(a.get("code") or "")
        irmaos = [x.get("usina") for x in assets
                  if x.get("usina") and str(x.get("code") or "").startswith(code + "-")]
        if irmaos:
            a["usina"] = max(set(irmaos), key=irmaos.count)
            cli = [x.get("cliente") for x in assets
                   if x.get("usina") == a["usina"] and x.get("cliente")]
            if cli:
                a["cliente"] = max(set(cli), key=cli.count)
        else:
            a["usina"] = ""
    return assets


def load_assets_cached(force: bool = False) -> list:
    """Ativos do cache (se < 24h e mesma versão) ou recarrega via RPC (sessão do usuário — sem
    OAuth) e salva. force=True ignora o cache."""
    if not force:
        _seed_cache()
        cached = _read_asset_cache()
        if cached:
            return _corrigir_itens_usina_estrangeiros(cached)
    assets = get_assets()
    try:
        with open(ASSETS_CACHE, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "ver": _CACHE_VER, "assets": assets}, f, ensure_ascii=False)
    except Exception:
        pass
    return _corrigir_itens_usina_estrangeiros(assets)


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


def get_conta_info() -> dict:
    """Nome + cargo (perfil) do usuário logado, do Fracttal. → {'nome','email','perfil'}. Defensivo:
    tenta companies.load_account_info; se faltar o perfil, procura na lista de contas pelo e-mail."""
    email = current_user()
    nome, perfil = "", ""
    try:
        r = _rpc_call("companies.load_account_info", {"page": 1, "limit": 200, "start": 0, "append": True})
        data = r.get("data") if isinstance(r, dict) else r
        rec = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else {})
        rec = rec if isinstance(rec, dict) else {}
        nome = str(rec.get("name") or (str(rec.get("first_name") or "") + " "
                   + str(rec.get("last_name") or "")).strip()).strip()
        perfil = str(rec.get("profiles_description") or rec.get("profile_description")
                     or rec.get("profile") or "").strip()
    except FracttalError:
        pass
    if (not perfil or not nome) and email:
        try:
            r2 = _rpc_call("companies.accounts_react_list", {"filter": [], "sort": [], "page": 1,
                           "limit": 500, "start": 0, "is_tree": False, "node": None})
            d2 = r2.get("data") if isinstance(r2, dict) else r2
            for a in (d2 if isinstance(d2, list) else []):
                if isinstance(a, dict) and str(a.get("email") or "").lower() == email.lower():
                    perfil = perfil or str(a.get("profiles_description") or "").strip()
                    nome = nome or str(a.get("name") or "").strip()
                    break
        except FracttalError:
            pass
    return {"nome": nome or (email or "Usuário"), "email": email, "perfil": perfil}


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


def duracao_os(ini, fim) -> str:
    """'1d 16h 20m' entre dois ISO (UTC). '' se faltar/for inválido/negativo."""
    def _p(x):
        s = str(x or "").strip().replace(" ", "T")[:19]
        try:
            return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None
    a, b = _p(ini), _p(fim)
    if not a or not b:
        return ""
    secs = int((b - a).total_seconds())
    if secs < 0:
        return ""
    d, r = divmod(secs, 86400); h, r = divmod(r, 3600); m = r // 60
    out = []
    if d:
        out.append(f"{d}d")
    if h or d:
        out.append(f"{h}h")
    out.append(f"{m}m")
    return " ".join(out)


def _parse_iso(x):
    """ISO 'YYYY-MM-DD[ T]HH:MM[:SS]' → datetime (naive). None se inválido/vazio."""
    s = str(x or "").strip().replace(" ", "T")[:19]
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        try:
            return datetime.strptime(s[:16], "%Y-%m-%dT%H:%M")
        except ValueError:
            return None


def horas_solares(ini, fim, h0=6, h1=18) -> float:
    """Horas dentro da janela solar [h0,h1] de cada dia, entre dois datetime. 0 se fim<=ini."""
    from datetime import time as _time
    if not ini or not fim or fim <= ini:
        return 0.0
    total = 0.0
    d = ini.date()
    while d <= fim.date():
        a = max(ini, datetime.combine(d, _time(h0)))
        b = min(fim, datetime.combine(d, _time(h1)))
        if b > a:
            total += (b - a).total_seconds() / 3600.0
        d += timedelta(days=1)
    return total


def duracao_solar(event_iso, fim_iso=None, h0=6, h1=18):
    """Tempo do problema em HORAS SOLARES (janela h0–h1) do evento até o fim; sem fim → até AGORA.
    → (horas: float|None, em_aberto: bool). None se a data do evento for inválida."""
    ini = _parse_iso(event_iso)
    if not ini:
        return (None, False)
    fim = _parse_iso(fim_iso)
    aberto = fim is None
    if fim is None:
        fim = datetime.now()
    return (round(horas_solares(ini, fim, h0, h1), 2), aberto)


def _path_node(asset: dict) -> str:
    pid, iid = asset.get("id_parent"), asset.get("id")
    return f"{pid}.{iid}" if pid else str(iid)


# id_task_form_item_type → rótulo. SONDADO AO VIVO na conta 4987 (29/07), varrendo os form items de
# 70 OS e olhando o `value` gravado — não vale confiar na doc REST, que diz 3=Data e 5=Dropdown:
#   1 = Texto        ("Foi feita a coleta completa do período?")
#   2 = Sim/Não      (valores 'false' / 'N/A')
#   3 = Número       ("Quantas strings ativas o inversor possui?" → '13', '23')
#   4 = Verificação  (valores '1'/'2'/'3' → Aprovado/Alerta/Falhou, ver _VERIF_MAP)
#   7 = Lista        (traz `dropdown_options`; valores 'Sim', 'Normalizado')
# Faltavam o 2 e o 3: subtarefa desses tipos aparecia sem tipo ("—") no card da OS.
_FORM_ITEM_TYPE_DESC = {1: "Texto", 2: "Sim/Não", 3: "Número", 4: "Verificação", 7: "Lista"}


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
                  event_date: datetime = None, tipo: dict = None, finalizar: dict = None,
                  id_parent=None, falha: dict = None) -> dict:
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
        # SUSPEITA NÃO CONFIRMADA (30/07): no `create_planned_os` foi medido que o Fracttal grava o
        # `initial_date` como data de programação — se valer aqui também, esta OS nasce programada
        # 10 min ANTES do próprio evento. Mas este RPC é OUTRO método (cria tarefa PENDENTE, sem
        # WO), e não consegui reler a tarefa criada para confirmar. Fica como está até dar para
        # medir: é o caminho do Tradicional/COS/Chamados/PCM, não se mexe no escuro.
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
    params["id_parent"] = id_parent                       # OS pai (opcional) — vincula esta OS a outra
    if tipo.get("id_c1") is not None:                     # Classificação 1
        params["id_task_type"] = tipo["id_c1"]
        params["tasks_types_description"] = tipo.get("desc_c1") or ""
    if tipo.get("id_c2") is not None:                     # Classificação 2
        params["id_task_type_2"] = tipo["id_c2"]
        params["tasks_types_2_description"] = tipo.get("desc_c2") or ""
    if falha:                                             # "O ativo falhou?" (F4) — preenche o bloco de falha
        params["failure_asset"] = True
        params["related_failure"] = True
        if falha.get("id_type") is not None:
            params["id_failure_type"] = falha["id_type"]
            params["types_description"] = falha.get("type_desc") or ""
        if falha.get("id_cause") is not None:
            params["id_failure_cause"] = falha["id_cause"]
            params["causes_description"] = falha.get("cause_desc") or ""
        if falha.get("id_detection") is not None:
            params["id_failure_detection_method"] = falha["id_detection"]
            params["detection_method_description"] = falha.get("detection_desc") or ""
        params["id_failure_severity"] = str(falha.get("id_severity") or 0)   # Fracttal grava como string
        params["severiry_description"] = falha.get("severity_desc") or ""     # (sic — grafia do Fracttal)
        if falha.get("id_damage") is not None:
            params["id_damage_type"] = falha["id_damage"]
            params["damages_types_description"] = falha.get("damage_desc") or ""
        if falha.get("out_of_service"):                   # fora de serviço → "desde" = data do evento DA OS
            params["asset_out_of_service"] = True
            params["date_asset_out_of_service"] = _iso_z(ev)
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
STATUS_FECHADOS = frozenset({3, 4})      # a OS não está mais na mão de ninguém


def status_da_os(id_work_order):
    """`id_status_work_order` atual da OS, lido do servidor. None se não achar.

    Serve para CONFERIR uma conclusão: o `recalculate` já respondeu sucesso deixando a OS aberta,
    e sem esta leitura o app anuncia "concluída" para uma OS que continua em processo."""
    if not id_work_order:
        return None
    try:
        res = _rpc_call(RPC_WO_DETAILS, {"id": id_work_order, "get_iso_codes": False})
    except FracttalError:
        return None
    d = res.get("data") if isinstance(res, dict) else res
    d = d[0] if isinstance(d, list) and d else (d if isinstance(d, dict) else {})
    st = (d or {}).get("id_status_work_order")
    return int(st) if st is not None else None
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


# ── Visão COS do histórico (espelha a que existia no Power BI) ───────────────
# Os 4 tipos que a visão do BI deixava marcados; Preventiva ficava DE FORA (é o PCM, outro fluxo).
TIPOS_COS = ("Corretiva", "Corretiva Emergencial", "Religamento", "Religamento Remoto")


def decodifica_gatilho(bruto) -> str:
    """`trigger_description` do Fracttal → português. As regras vieram do Power Query que o Levi
    usava no Power BI: o campo vem em código (`NO_SCHEDULE_TASK`, `DATE$EVERY$30$DAYS`)."""
    s = str(bruto or "").strip()
    if not s:
        return ""
    if "NO_SCHEDULE_TASK" in s:
        return "Tarefa não agendada"
    s = s.replace("EVENT$", "").replace("DATE$EVERY$", "A cada ")
    s = s.replace("$DAYS", " dias").replace("$MONTHS", " meses").replace("$YEARS", " anos")
    for n, sing in (("1 dias", "1 dia"), ("1 meses", "1 mês"), ("1 anos", "1 ano")):
        s = s.replace(n, sing)
    return s.strip()


def _primeiro(w: dict, *chaves) -> str:
    """1º campo preenchido entre `chaves` (data ISO cortada em 19). O Fracttal muda o nome do
    mesmo dado entre endpoints — é o mesmo parse defensivo do `fim_keys` do `_meta_tarefa_por_os`,
    e sem ele uma renomeação silenciosa esvazia a coluna sem ninguém perceber."""
    for k in chaves:
        v = w.get(k)
        if v not in (None, "", []) and str(v).lower() != "none":
            return str(v)[:19]
    return ""


def _shape_wo_row(w: dict) -> dict:
    """Linha crua do `work_orders_list_react` → o dict que o app inteiro consome. Extraído do
    `list_minhas_os` para a versão PAGINADA usar o mesmo formato — duplicar aqui divergiria."""
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
    return {"id": w.get("id"), "folio": w.get("wo_folio"), "cliente": cliente or "—",
            "usina": usina or "—", "ativo": ativo, "tipo": tipo or "—", "descricao": desc,
            "criado_por": str(w.get("created_by") or "").strip(), "etiquetas": etiquetas,
            # QUEM está com a OS. A linha crua já traz isso — sem esses dois campos o
            # board de Performance precisaria de UMA CONSULTA POR ANALISTA; com eles,
            # uma busca só traz todo mundo e o agrupamento é local.
            "atribuido_a": str(w.get("user_assigned")
                               or w.get("personnel_description") or "").strip(),
            "id_atribuido": w.get("id_assigned_user"),
            "data": (w.get("creation_date") or "")[:19],
            "event_date": (w.get("event_date") or w.get("date_maintenance")
                           or w.get("cal_date_maintenance") or "")[:19],   # fallback da lista
            "data_fim": (w.get("final_date") or w.get("date_end")
                         or w.get("real_final_date") or "")[:19],           # fallback da lista
            # ── colunas da visão COS ──
            # Sondado ao vivo em 28/07: a LISTAGEM só tem `date_maintenance` (= programada) e
            # `personnel_description`. `initial_date` e `trigger_description` existem apenas no
            # nível TAREFA — chegam depois, pelo `meta_tarefas_por_os`. Nada de cair no
            # `first_date_task` aqui: ele é IGUAL à data programada, e a coluna "Início" ficaria
            # preenchida com a data errada para toda OS nunca iniciada (33 de 1.306 tarefas
            # medidas têm início real).
            "programada": _primeiro(w, "date_maintenance", "cal_date_maintenance"),
            "inicio": "",
            "equipe": str(w.get("personnel_description")
                          or w.get("user_assigned") or "").strip(),
            "gatilho": "",
            "status_id": stid, "status": WO_STATUS.get(stid, f"Status {stid}")}


def list_minhas_os(modo: str = "criadas", id_account=None, id_label=None,
                   de: str = None, ate: str = None, status_ids=None, cap: int = HISTORICO_CAP) -> list:
    """OS do Fracttal no PERÍODO [de, ate] (datas 'YYYY-MM-DD' — filtradas NO SERVIDOR por
    creation_date, então o período governa a busca de verdade). modo='criadas' (Histórico Geral, por
    'id_created_by') ou 'atribuidas' (id_assigned_user = id_personnel do logado). Em 'criadas',
    id_account: None = LOGADO (default); "TODOS" = todos os criadores; ou um id_account específico.
    id_label (opcional): só OS que CONTÊM a etiqueta. PAGINA o período inteiro (todos os status numa
    busca só) até o teto `cap`, dedup por id, ordena por data desc.
    → [{'id','folio','cliente','usina','ativo','tipo','tipo_tarefa','descricao','criado_por',
        'atribuido_a','id_atribuido','etiquetas','data','status_id','status'}].
        'tipo' = tipo de ativo (Inversor/Tracker/…);
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
    if status_ids:                          # status no servidor (id_status_work_order) — re-busca por status
        cond.append({"operator": "in", "property": "id_status_work_order", "value": list(status_ids)})
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
            if wid not in vistos:
                vistos[wid] = _shape_wo_row(w)
    out = list(vistos.values())
    out.sort(key=lambda x: x["data"], reverse=True)
    meta = _meta_tarefa_por_os([d["id"] for d in out])    # enriquece: tipo de tarefa + evento + fim
    for d in out:
        m = meta.get(d["id"], {})
        d["tipo_tarefa"] = m.get("tipo_tarefa", "")
        d["event_date"] = m.get("event_date") or d.get("event_date", "")   # tarefa manda; senão a da lista
        d["data_fim"] = m.get("data_fim") or d.get("data_fim", "")
        d["note"] = m.get("note", "")                                       # p/ o board ler o bloco CHAMADO
    return out


def contar_minhas_analises() -> int:
    """Quantas OS de PERFORMANCE estão ATRIBUÍDAS ao logado e ABERTAS (status Em Processo).
    Alimenta o selo "N atribuídas a você" do card Performance no launcher. UMA chamada com
    limite=1 — só o `total` do servidor interessa. Em Verificação/Concluída ficam de fora:
    o selo é cobrança de trabalho pendente, não placar."""
    lid = _label_performance_id()
    if not lid:
        return 0
    r = list_minhas_os_pagina("atribuidas", None, lid, None, None, [1], "", 1, 1)
    return int(r.get("total") or 0)


def listar_periodo_completo(modo: str = "criadas", id_account=None, id_label=None,
                            de: str = None, ate: str = None, status_ids=None,
                            busca: str = "", limite: int = 200, max_paginas: int = 80) -> dict:
    """TODAS as OS do período, de uma vez. → {'linhas', 'total', 'completo'}.

    Existe porque cliente/usina/tipo são filtrados NO APP: o servidor não sabe filtrar por usina
    (o `like` em campo de item é ignorado e o `id_group_task` é família de plano, não planta —
    ambos medidos). Então, para o filtro dar uma resposta correta, o período tem de estar inteiro
    na mão.

    Pagina EM PARALELO: a 1ª página revela o total e as demais vão juntas. Medido em 30/07 com
    5.522 OS — sequencial de 60 em 60 levaria ~93 requisições e mais de um minuto; assim são 28
    requisições em 8 vias. `max_paginas` é o freio para período absurdo: devolve o que deu e marca
    `completo=False`, e aí quem chamou avisa em vez de mentir que acabou."""
    p1 = list_minhas_os_pagina(modo, id_account, id_label, de, ate, status_ids, busca, 1, limite)
    total = int(p1.get("total") or 0)
    linhas = list(p1.get("linhas") or [])
    if not p1.get("tem_mais"):
        return {"linhas": linhas, "total": total, "completo": True}
    n_pag = -(-total // limite)                       # teto da divisão
    restantes = list(range(2, min(n_pag, max_paginas) + 1))
    if restantes:
        with ThreadPoolExecutor(max_workers=min(8, len(restantes))) as ex:
            futuros = {ex.submit(list_minhas_os_pagina, modo, id_account, id_label, de, ate,
                                 status_ids, busca, p, limite): p for p in restantes}
            for f in as_completed(futuros):
                try:
                    linhas += (f.result() or {}).get("linhas") or []
                except Exception:
                    pass                              # página que falhar não derruba a varredura
    vistos, unicas = set(), []
    for d in linhas:                                  # páginas concorrentes podem repetir na borda
        if d.get("id") in vistos:
            continue
        vistos.add(d.get("id")); unicas.append(d)
    unicas.sort(key=lambda d: d.get("id") or 0, reverse=True)
    return {"linhas": unicas, "total": total, "completo": len(unicas) >= total}


def meta_tarefas_por_os(wo_ids) -> dict:
    """Público: tipo de tarefa + datas da tarefa por OS (o histórico busca DEPOIS de renderizar —
    medido: 3,5 s para 60 ids, contra 0,7 s da página; enriquecer junto quintuplicava a espera)."""
    return _meta_tarefa_por_os(wo_ids)


def list_minhas_os_pagina(modo: str = "criadas", id_account=None, id_label=None,
                          de: str = None, ate: str = None, status_ids=None,
                          busca: str = "", pagina: int = 1, limite: int = 60,
                          com_meta: bool = False) -> dict:
    """UMA página do histórico — é o que torna a rolagem infinita possível (28/07, reclamação
    da equipe: o histórico puxava até 2000 OS + 16 lotes de enriquecimento ANTES de mostrar a
    primeira linha; medido, uma página de 60 responde em ~0,7 s).

    Mesmos filtros server-side do `list_minhas_os`, MAIS `busca`: like em `wo_folio` OU
    `description` — SÓ essas duas, porque foram as únicas que o servidor comprovadamente filtra
    (sondado ao vivo: 'MOTIVO' em description → 28 acertos reais). CUIDADO ao acrescentar
    propriedade aqui: o servidor IGNORA propriedade desconhecida devolvendo TUDO, e num OR isso
    faz a busca inteira voltar o catálogo completo — foi medido com tasks_descriptions/
    items_description, os dois voltaram total=10272 (tudo).

    → {'linhas': [...], 'total': N no servidor, 'tem_mais': bool}."""
    idp, idacc = _current_user_ids()
    todos = False
    if modo == "atribuidas":
        prop, val = "id_assigned_user", idp
    else:
        prop = "id_created_by"
        if id_account is None:      val = idacc
        elif id_account == "TODOS": val, todos = None, True
        else:                       val = id_account
    if not todos and val is None:
        raise FracttalError("Não consegui identificar seu usuário no Fracttal (e-mail não bate no cadastro).")
    cond = [] if todos else [{"operator": "=", "property": prop, "value": val}]
    if id_label:
        cond.append({"operator": "=", "property": "id_label", "value": id_label})
    if status_ids:
        cond.append({"operator": "in", "property": "id_status_work_order", "value": list(status_ids)})
    if de:
        cond.append({"operator": ">=", "property": "creation_date", "value": de})
    if ate:
        cond.append({"operator": "<=", "property": "creation_date", "value": ate + "T23:59:59"})
    busca = str(busca or "").strip()
    if busca:
        cond += [{"operator": "like", "property": "wo_folio", "value": busca, "condition": "or"},
                 {"operator": "like", "property": "description", "value": busca, "condition": "or"}]
    pagina = max(1, int(pagina))
    start = (pagina - 1) * limite
    res = _rpc_call(RPC_WO_LIST, {"page": pagina, "limit": limite, "start": start, "append": True,
                                  "sort": [{"property": "id", "direction": "desc"}], "filter": cond})
    total = int(res.get("total") or 0) if isinstance(res, dict) else 0
    linhas, vistos = [], set()
    for w in ((res.get("data") or []) if isinstance(res, dict) else []):
        if w.get("id") in vistos:
            continue
        vistos.add(w.get("id"))
        linhas.append(_shape_wo_row(w))
    for d in linhas:
        d.setdefault("tipo_tarefa", "")
    # `com_meta=False` é o DEFAULT de propósito: o enriquecimento custa 5× a página (3,5 s vs
    # 0,7 s, medido) — o histórico renderiza primeiro e busca a meta em separado, assíncrono
    # (`meta_tarefas_por_os`). As datas da linha já vêm com o fallback da listagem.
    if com_meta:
        meta = _meta_tarefa_por_os([d["id"] for d in linhas])
        for d in linhas:
            m = meta.get(d["id"], {})
            d["tipo_tarefa"] = m.get("tipo_tarefa", "")
            d["event_date"] = m.get("event_date") or d.get("event_date", "")
            d["data_fim"] = m.get("data_fim") or d.get("data_fim", "")
            d["note"] = m.get("note", "")
            d["inicio"] = m.get("inicio", "")
            d["gatilho"] = m.get("gatilho", "")
    return {"linhas": linhas, "total": total, "tem_mais": start + len(linhas) < total}


# ── Detalhe de uma OS (ao clicar no nº no histórico): Data do Evento, Notas, Subtarefas ──
RPC_WO_TASKS  = "tasks.work_orders_tasks_new_list"       # tarefa(s) da OS (event_date, notas, tipo)
RPC_WO_FORMIT = "tasks.work_orders_task_form_items_list"  # subtarefas (checklist)


def _meta_tarefa_por_os(wo_ids):
    """{id_work_order: {'tipo_tarefa': 'Tipo' (ou 'A / B'), 'event_date': ISO}} p/ as OS dadas. A
    listagem NÃO traz tipo de tarefa nem a data do evento — vêm do RPC de tarefas (1 chamada por lote,
    em paralelo). Best-effort: erro num lote → ignora (sem quebrar a lista)."""
    ids = [w for w in dict.fromkeys(wo_ids) if w]            # únicos, preserva ordem
    if not ids:
        return {}
    CH = 130
    chunks = [ids[i:i + CH] for i in range(0, len(ids), CH)]

    fim_keys = ("final_date", "date_end", "end_date", "real_final_date", "finished_date",
                "date_finished", "closing_date")

    def _fetch(chunk):
        tipos, evt, fim, notas, start, limit = {}, {}, {}, {}, 0, 2000
        ini, gat = {}, {}                                  # início real e gatilho (visão COS)
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
                if not wid:
                    continue
                tp = str(t.get("tasks_types_main_description") or "").strip()
                if tp:
                    tipos.setdefault(wid, set()).add(tp)
                ev = str(t.get("event_date") or "")[:19]     # data do evento
                if ev and (wid not in evt or ev < evt[wid]):  # a mais antiga (início da OS)
                    evt[wid] = ev
                fv = ""                                       # data fim (conclusão)
                for k in fim_keys:
                    v = t.get(k)
                    if v not in (None, "") and str(v).lower() != "none":
                        fv = str(v)[:19]; break
                if fv and (wid not in fim or fv > fim[wid]):  # a mais recente
                    fim[wid] = fv
                nt = str(t.get("note") or t.get("task_note") or "").strip()   # nota da tarefa
                if nt:
                    cur = notas.get(wid, "")
                    if (_CHAMADO_MK in nt and _CHAMADO_MK not in cur) or \
                       (_CHAMADO_MK not in cur and len(nt) > len(cur)):       # prefere a que tem o bloco
                        notas[wid] = nt
                iv = str(t.get("initial_date") or "")[:19]     # início REAL (só a tarefa tem)
                if iv and iv.lower() != "none" and (wid not in ini or iv < ini[wid]):
                    ini[wid] = iv                              # a mais antiga = início da OS
                gv = str(t.get("trigger_description") or "").strip()
                # Uma OS pode ter tarefas com gatilhos diferentes; a agendada (EVENT$…) diz mais
                # que "não agendada", então ela ganha.
                if gv and (wid not in gat or (gat[wid] == "NO_SCHEDULE_TASK"
                                              and gv != "NO_SCHEDULE_TASK")):
                    gat[wid] = gv
            start += len(data)
            if not data or len(data) < limit:
                break
        return tipos, evt, fim, notas, ini, gat

    tipos_out, evt_out, fim_out, notas_out = {}, {}, {}, {}
    ini_out, gat_out = {}, {}
    with ThreadPoolExecutor(max_workers=min(8, len(chunks))) as ex:
        for tipos, evt, fim, notas, ini, gat in ex.map(_fetch, chunks):
            for wid, s in tipos.items():
                tipos_out.setdefault(wid, set()).update(s)
            for wid, e in evt.items():
                if wid not in evt_out or e < evt_out[wid]:
                    evt_out[wid] = e
            for wid, f2 in fim.items():
                if wid not in fim_out or f2 > fim_out[wid]:
                    fim_out[wid] = f2
            for wid, nt in notas.items():
                cur = notas_out.get(wid, "")
                if (_CHAMADO_MK in nt and _CHAMADO_MK not in cur) or (_CHAMADO_MK not in cur and len(nt) > len(cur)):
                    notas_out[wid] = nt
            for wid, iv in ini.items():
                if wid not in ini_out or iv < ini_out[wid]:
                    ini_out[wid] = iv
            for wid, gv in gat.items():
                if wid not in gat_out or (gat_out[wid] == "NO_SCHEDULE_TASK"
                                          and gv != "NO_SCHEDULE_TASK"):
                    gat_out[wid] = gv
    return {wid: {"tipo_tarefa": " / ".join(sorted(tipos_out.get(wid, set()))),
                  "event_date": evt_out.get(wid, ""), "data_fim": fim_out.get(wid, ""),
                  "note": notas_out.get(wid, ""),
                  "inicio": ini_out.get(wid, ""),
                  "gatilho": decodifica_gatilho(gat_out.get(wid, ""))}
            for wid in set(tipos_out) | set(evt_out) | set(fim_out) | set(notas_out)
                       | set(ini_out) | set(gat_out)}


# Campos onde o Fracttal pode guardar a RESPOSTA de uma subtarefa (o nome varia por tipo/versão).
_FORM_RESP_KEYS = ("value", "response", "result", "answer", "text_value",
                   "task_form_item_value", "value_description", "observation")


# Verificação (id_task_form_item_type=4) guarda a resposta como 1/2/3 no 'value'.
_VERIF_MAP = {"1": "Aprovado", "2": "Alerta", "3": "Falhou"}


def _form_item_resposta(it: dict) -> str:
    """Melhor esforço p/ extrair a resposta dada numa subtarefa (o nome do campo varia no Fracttal)."""
    verif = it.get("id_task_form_item_type") == 4
    for k in _FORM_RESP_KEYS:
        v = it.get(k)
        if v not in (None, "", "None", "null", "NaN"):
            v = str(v).strip()
            if verif and v in _VERIF_MAP:            # Verificação: 1/2/3 → Aprovado/Alerta/Falhou
                return _VERIF_MAP[v]
            return v
    if verif:                                         # sem value → tenta o 'done'
        dn = str(it.get("done")).lower()
        if dn == "true":
            return "Aprovado"
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


RPC_WO_PARENTS = "tasks.work_orders_parents_list"


def buscar_os_pai(termo="", limit=50) -> list:
    """Busca OSs candidatas a PAI por número (wo_folio, filtro 'like'). Vazio = primeiras da lista.
    → [{'id','folio','descricao'}] — 'id' é o id_parent a mandar na criação (NÃO é o nº)."""
    t = str(termo or "").strip()
    filtro = [{"operator": "like", "property": "wo_folio", "value": t, "condition": "or"}] if t else []
    try:
        r = _rpc_call(RPC_WO_PARENTS, {"filter": filtro, "sort": [], "page": 1, "limit": limit,
                                       "start": 0, "is_tree": False, "node": None})
    except FracttalError:
        return []
    data = r.get("data") if isinstance(r, dict) else r
    out = []
    for w in (data if isinstance(data, list) else []):
        if not isinstance(w, dict):
            continue
        idp = w.get("id")
        if idp is None:
            continue
        folio = w.get("wo_folio") or w.get("folio") or ""
        desc = str(w.get("description") or w.get("tasks_description")
                   or w.get("items_description") or "").split("{")[0].strip()[:80]
        out.append({"id": idp, "folio": str(folio), "descricao": desc})
    return out


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
                           "tipo": tipo, "resposta": _form_item_resposta(it),
                           # a QUAL tarefa esta subtarefa pertence. Numa OS de preventiva (a 8709 tem
                           # 13 tarefas e 45 subtarefas) a lista corrida não diz nada — é este id que
                           # deixa o card filtrar por tarefa. Casa com `id` da tarefa (join conferido
                           # ao vivo: 45/45 sem órfã).
                           "id_tarefa": it.get("id_work_order_task")})
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
    # OS pai (id_parent_wo → folio da OS mãe). Só ~15% das OS têm; resolve o número só quando existe.
    os_pai = ""
    pai_id = det.get("id_parent_wo") or t0.get("id_parent_wo")
    if pai_id:
        try:
            rp = _rpc_call(RPC_WO_DETAILS, {"id": pai_id, "get_iso_codes": False})
            dp = rp.get("data") if isinstance(rp, dict) else rp
            dp = dp[0] if isinstance(dp, list) and dp else (dp if isinstance(dp, dict) else {})
            os_pai = str(dp.get("wo_folio") or "").strip()
        except FracttalError:
            os_pai = ""
    # data de conclusão (OS finalizada) — nomes variam; tenta os prováveis na tarefa e no cabeçalho
    data_fim = None
    for src in (t0, det):
        for k in ("final_date", "date_end", "end_date", "real_final_date", "finished_date",
                  "date_finished", "closing_date"):
            v = src.get(k)
            if v not in (None, "") and str(v).lower() != "none":
                data_fim = v
                break
        if data_fim:
            break
    # tipo/classificação/criticidade (rodapé read-only do card, estilo COS)
    _crit_pt = {v: k for k, v in CRITICIDADES}          # {1:'Muito alto',…,3:'Médio',…}
    _c1 = str(t0.get("tasks_types_description") or "").strip()
    _c2 = str(t0.get("tasks_types_2_description") or "").strip()
    classif = " / ".join([x for x in (_c1, _c2) if x])
    criticidade = _crit_pt.get(t0.get("id_priorities"), "")
    # cada TAREFA da OS (a preventiva mensal abre uma por sistema: cabine, medidor, módulos…).
    # Só o `t0` ia para o card antes — numa OS de 13 tarefas isso escondia 12.
    tarefas = [{"id": t.get("id"),
                "titulo": str(t.get("tasks_description") or "").strip(),
                "ativo": (str(t.get("items_description") or "").split("{")[0]).strip()[:60],
                "tipo": str(t.get("tasks_types_main_description") or "").strip(),
                "classif": " / ".join([x for x in (str(t.get("tasks_types_description") or "").strip(),
                                                   str(t.get("tasks_types_2_description") or "").strip()) if x]),
                "criticidade": _crit_pt.get(t.get("id_priorities"), ""),
                "programada": _primeiro(t, "date_maintenance", "cal_date_maintenance"),
                "inicio": _primeiro(t, "initial_date"),
                "fim": _primeiro(t, "final_date"),
                "duracao": str(t.get("duration") or "").strip(),
                "gatilho": decodifica_gatilho(t.get("trigger_description")),
                "nota": str(t.get("task_note") or t.get("note") or "").strip()}
               for t in tasks]
    # CANCELAMENTO: só busca quando a OS está cancelada (status 4). É uma chamada REST a mais, e
    # cobrá-la em toda abertura de card seria pagar por 96% de OS que não precisam.
    canc = {"motivo": "", "nota": ""}
    if (det.get("id_status_work_order") or t0.get("id_status_work_order")) == 4:
        canc = cancelamento_da_os(t0.get("wo_folio"))
    return {"folio": t0.get("wo_folio"),
            "cancel_motivo": canc["motivo"], "cancel_nota": canc["nota"],
            "descricao": str(t0.get("tasks_description") or "").strip(),
            "tipo": str(t0.get("tasks_types_main_description") or "").strip(),
            "classif": classif,
            "criticidade": criticidade,
            "event_date": t0.get("event_date"),
            "data_fim": data_fim,
            "responsavel": resp,
            "criado_por": criado_por,
            "solicitacao": solic,
            "os_pai": os_pai,
            "os_pai_id": pai_id or None,
            "notas": "\n".join(notas),
            "subtarefas": subtarefas,
            "tarefas": tarefas,
            "etiquetas": [{"id": l.get("id"), "nome": l.get("description"), "cor": l.get("color")}
                          for l in (det.get("labels") or []) if isinstance(l, dict) and l.get("id") is not None],
            "code": code0, "ativo": ativo0}


def get_os_detalhes_por_folio(folio) -> dict:
    """Detalhe da OS pelo NÚMERO (wo_folio) em vez do id — usado pelo clonador do COS.
    None se o número não existir."""
    idwo = _wo_id_por_folio(folio)
    if not idwo:
        return None
    d = get_os_detalhes(idwo)
    d["id_work_order"] = idwo
    return d


def _label_id(nome: str):
    """id da etiqueta pelo nome (case-insensitive). None se não existir no Fracttal."""
    alvo = str(nome or "").strip().lower()
    for l in (get_labels() or []):
        if str(l.get("description") or "").strip().lower() == alvo:
            return l.get("id")
    return None


_CHAMADO_MK  = "━━━ CHAMADO ━━━"
_CHAMADO_FIM = "━━━━━━━━━━━━━━━━"
# (rótulo no texto, chave no dict) — ordem = ordem no bloco
_CHAMADO_CAMPOS = [("OS de abertura", "os_pai"), ("Ticket/RMA", "ticket"),
                   ("Serial Number", "serial"), ("Status", "status"),
                   ("Fabricante", "fabricante"), ("Motivo", "motivo"), ("Resolução", "resolucao")]


def bloco_chamado(dados: dict) -> str:
    """Monta o BLOCO padrão do chamado (legível + parseável) p/ gravar na observação da OS.
    O mesmo texto serve pros formatos ANTIGOS (colado na OS) e pra o board LER."""
    linhas = [_CHAMADO_MK]
    for rot, k in _CHAMADO_CAMPOS:
        v = str((dados or {}).get(k) or "").strip() or "—"
        linhas.append(f"{rot}: {v}")
    linhas.append(_CHAMADO_FIM)
    return "\n".join(linhas)


def parse_bloco_chamado(texto) -> dict:
    """INVERSO: lê o bloco CHAMADO de uma observação → {os_pai,ticket,serial,status,fabricante,
    motivo,resolucao}. {} se não tiver o bloco. Tolera acento/caixa no rótulo. '—'/vazio → ''."""
    t = str(texto or "")
    if _CHAMADO_MK not in t and "chamado" not in t.lower():
        return {}
    def _norm(s):
        import unicodedata
        return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c)).strip()
    rot2k = {_norm(r): k for r, k in _CHAMADO_CAMPOS}
    out = {}
    for linha in t.splitlines():
        if ":" not in linha:
            continue
        rot, val = linha.split(":", 1)
        k = rot2k.get(_norm(rot))
        if k:
            v = val.strip()
            out[k] = "" if v in ("", "—") else v
    return out


def list_chamados(de=None, ate=None, status_ids=None) -> list:
    """OSs com a etiqueta CHAMADOS no período [de, ate] (de TODOS os criadores), mais recentes
    primeiro. [] se a etiqueta 'CHAMADOS' não existir no Fracttal."""
    lid = _label_id("CHAMADOS")
    if not lid:
        return []
    return list_minhas_os(modo="criadas", id_account="TODOS", id_label=lid,
                          de=de, ate=ate, status_ids=status_ids)


def list_performance(de=None, ate=None) -> list:
    """OSs com a etiqueta PERFORMANCE no período — a carga do kanban de carga da equipe.

    UMA CONSULTA para o board inteiro. Cada linha já traz `atribuido_a`, `status_id`, `etiquetas`
    e `note`, que é tudo o que o `perf_spec` precisa para dizer de quem é, em que estado está e
    qual a prioridade. Uma busca por analista custaria N vezes isso sem trazer nada a mais.
    Medido em 26/07: **378 OS em 3,8 s** para 90 dias, com todos os criadores.
    """
    lid = _label_id(perf_spec_nome_etiqueta())
    if not lid:
        return []
    return list_minhas_os(modo="criadas", id_account="TODOS", id_label=lid, de=de, ate=ate)


def perf_spec_nome_etiqueta():
    """Nome da etiqueta do setor. Isolado numa função para o api não importar o perf_spec
    (que é regra de tela) e criar ciclo."""
    return "PERFORMANCE"


TIPO_ANALISE = "Administrativa"        # tipo de tarefa da OS de análise (Levi, 03/08)
ANALISE_CLASSIF_1 = "Programada"       # Classificação 1  ┐ mesmas das OS de ETM
ANALISE_CLASSIF_2 = "Elétrica"         # Classificação 2  ┘ (conferido nas OS 10445/10444/10383)


def create_os_analise(asset: dict, id_responsible, resp_code="", resp_name="",
                      prioridade="", motivo="", descricao="", pedido_por="",
                      os_pai_folio="", tipo_tarefa=TIPO_ANALISE, bloco_texto="") -> dict:
    """Cria a OS de ANÁLISE de performance, atribuída a um analista.

    TIPO 'Administrativa' + classificação 'Programada / Elétrica' (Levi, 03/08): é trabalho de
    escritório, igual às OS de ETM, e agora sai idêntico a elas no Fracttal. Antes nascia como
    'Inspeção' e sem classificação nenhuma. O que vai a CAMPO é a OS FILHA que a análise gera —
    o exemplo da Ana na reunião ("a Gabi fechou o card dela e abriu cinco verificações em campo").
    A classificação é resolvida pelo NOME no catálogo (`_classif_ids`), porque a lista é editável
    dentro do Fracttal e id fixo quebraria na primeira edição.

    `bloco_texto` = o bloco [PERFORMANCE] já montado pelo `perf_spec.bloco()` — vem pronto da tela
    para o api não depender do módulo de regra. Entra ANTES da descrição livre porque a API do
    Fracttal não edita OS criada: o que não for gravado agora só muda no Fracttal web.

    → {'ok','folio','id_work_order','etiqueta_ok','aviso'} ou {'ok':False,'erro'}.
    """
    if not isinstance(asset, dict) or not (asset.get("code") or "").strip():
        return {"ok": False, "erro": "Escolha o ativo (usina ou equipamento) no catálogo."}
    if not id_responsible:
        return {"ok": False, "erro": "Escolha o analista — sem responsável a OS não recebe número."}
    lid = _label_id(perf_spec_nome_etiqueta())
    if not lid:
        return {"ok": False, "erro": "Não achei a etiqueta 'PERFORMANCE' no Fracttal."}
    etiquetas = [lid]
    # "Dar prioridade" (2603) entra JUNTO na prioridade máxima: quem abrir a OS direto no Fracttal,
    # sem passar por esta tela, precisa enxergar a urgência lá também.
    if (prioridade or "").strip().lower() == "máxima".lower():
        pid = _label_id("Dar prioridade")
        if pid:
            etiquetas.append(pid)

    titulo = perf_os_nome(asset, (motivo or "").strip() or "Análise de performance")

    id_parent = None
    folio_pai = str(os_pai_folio or "").strip()
    if folio_pai:
        try:
            for c in buscar_os_pai(folio_pai, limit=20):
                if str(c.get("folio")).strip() == folio_pai:
                    id_parent = c.get("id"); break
        except FracttalError:
            pass                        # OS pai é opcional: não achou, cria sem vínculo

    livre = (descricao or "").strip()
    note = (bloco_texto or "").strip()
    note = (note + ("\n\n" + livre if livre else "")) if note else livre

    # `tipo` = classificação 1/2 pelo nome. O `create_os_rpc` só grava o par quando id_c1/id_c2 vêm
    # preenchidos, então nome que não existir no catálogo apenas não entra (OS sem classificação é
    # menos ruim que OS com a classificação errada).
    _c = _classif_ids(ANALISE_CLASSIF_1, ANALISE_CLASSIF_2)
    tipo = {}
    if _c.get("id_task_type") is not None:
        tipo["id_c1"] = _c["id_task_type"]; tipo["desc_c1"] = _c.get("tasks_types_description") or ""
    if _c.get("id_task_type_2") is not None:
        tipo["id_c2"] = _c["id_task_type_2"]; tipo["desc_c2"] = _c.get("tasks_types_2_description") or ""

    res = create_work_orders_bulk([asset], titulo, tipo_tarefa, [], etiqueta_ids=etiquetas,
                                  id_parent=id_parent, id_responsible=id_responsible,
                                  responsible_code=resp_code, responsible_name=resp_name,
                                  note=note, tipo=tipo or None)
    r0 = res[0] if res else {}
    if not r0.get("ok"):
        return {"ok": False, "erro": r0.get("erro") or "não consegui criar a OS."}
    o = r0.get("os") or {}
    return {"ok": True, "folio": o.get("wo_folio"), "id_work_order": o.get("id_work_order"),
            "etiqueta_ok": bool(o.get("etiquetas")), "os_pai": folio_pai or None,
            "aviso": o.get("aviso")}


# Subtarefa → chave do painel. A API NÃO deixa o app editar OS já criada, mas a equipe de chamados
# edita a subtarefa no Fracttal web enquanto a OS está aberta — então o status VIVO se lê daqui,
# não do bloco da observação (que fica congelado no que foi gravado na criação).
_CHAMADO_SUB = {
    "status do chamado": "status",
    "fabricante": "fabricante",
    "no do chamado / protocolo": "ticket",
    "ticket / rma": "ticket",
    "numero de serie": "serial",
    "serial number": "serial",
    "no do rma": "rma",
    "garantia": "garantia",
    "equipamento defeituoso coletado?": "coletado",
}


def _chave_sub(desc):
    d = _norm_txt(desc)
    return _CHAMADO_SUB.get(d)


def status_chamado_em_massa(ids, max_workers: int = 8) -> dict:
    """Lê as subtarefas de VÁRIAS OSs de chamado em paralelo → {id: {status,fabricante,ticket,…}}.
    Medido: ~35 ms por OS com 8 threads (24 OSs em 0,8 s), então dá pra carregar o painel inteiro."""
    ids = [i for i in (ids or []) if i]
    if not ids:
        return {}

    def _um(i):
        try:
            res = _rpc_call(RPC_WO_FORMIT, {"id_work_order": i, "sort": []})
        except FracttalError:
            return i, {}
        out = {}
        for it in ((res.get("data") or []) if isinstance(res, dict) else []):
            k = _chave_sub(it.get("description"))
            if not k:
                continue
            v = str(_form_item_resposta(it) or "").strip()
            if v:
                out[k] = v
        return i, out

    with ThreadPoolExecutor(max_workers=min(max_workers, len(ids))) as ex:
        return dict(ex.map(_um, ids))


def get_chamado_de_os(id_work_order) -> dict:
    """A OS de CHAMADO filha desta OS (ou None). Usada no card da OS: com chamado, o botão vira
    "Ver chamado N" e o nº aparece no bloco de vínculos — evita abrir chamado duplicado.
    Filtra por id_parent_wo NO SERVIDOR (testado: devolve só a filha) e confere a etiqueta, porque
    clone e desdobramento de OS também usam OS pai e não são chamado.
    → {'id','folio','status','status_id'} ou None."""
    if not id_work_order:
        return None
    lid = _label_id("CHAMADOS")
    try:
        res = _rpc_call(RPC_WO_LIST, {"page": 1, "limit": 50, "start": 0, "append": True, "sort": [],
                                      "filter": [{"operator": "=", "property": "id_parent_wo",
                                                  "value": id_work_order}]})
    except FracttalError:
        return None
    for w in ((res.get("data") or []) if isinstance(res, dict) else []):
        etiqs = [str((l or {}).get("description") or "").strip().upper()
                 for l in (w.get("labels") or []) if isinstance(l, dict)]
        ids = [(l or {}).get("id") for l in (w.get("labels") or []) if isinstance(l, dict)]
        if "CHAMADOS" not in etiqs and (not lid or lid not in ids):
            continue
        stid = w.get("id_status_work_order")
        return {"id": w.get("id"), "folio": w.get("wo_folio"),
                "status_id": stid, "status": WO_STATUS.get(stid, "—")}
    return None


def create_os_chamado(parent_folio, id_responsible, resp_code="", resp_name="",
                      concluir=False, note="", ticket="", motivo="", subtarefas=None,
                      dados_chamado=None) -> dict:
    """CHAMADOS: cria uma OS NOVA no MESMO ativo de uma OS existente (nº = parent_folio), vinculando-a
    como OS PAI e aplicando a etiqueta 'CHAMADOS'. `concluir` = fecha a OS logo após criar. Herda tipo/
    classificação/criticidade da OS pai. `ticket`/`motivo` entram no título; `subtarefas` (Lista já
    montadas pela tela) viram as subtarefas rastreáveis. → {'ok','folio','os_pai','etiqueta_ok',
    'concluida','aviso'} ou {'ok':False,'erro'}. NADA é criado se a OS/ativo/etiqueta não forem resolvidos."""
    parent_folio = str(parent_folio or "").strip()
    if not parent_folio:
        return {"ok": False, "erro": "Digite o número da OS do chamado."}
    if not id_responsible:
        return {"ok": False, "erro": "Escolha o responsável (a OS pai e a etiqueta só gravam com ele)."}
    d = get_os_detalhes_por_folio(parent_folio)
    if not isinstance(d, dict):
        return {"ok": False, "erro": f"Não achei a OS nº {parent_folio}."}
    parent_wo = d.get("id_work_order")
    code = (d.get("code") or "").strip()
    asset = _asset_by_code(code) if code else None
    if not isinstance(asset, dict):
        return {"ok": False, "erro": f"A OS {parent_folio} não tem um ativo do catálogo "
                "(recarregue os ativos e tente de novo)."}
    lid = _label_id("CHAMADOS")
    if not lid:
        return {"ok": False, "erro": "Não achei a etiqueta 'CHAMADOS' no Fracttal — crie a etiqueta lá "
                "(Configurações → Etiquetas) e tente de novo."}
    # id_parent = mesma fonte do seletor de OS pai (o 'id' do work_orders_parents_list, não o nº)
    id_parent = parent_wo
    try:
        for c in buscar_os_pai(parent_folio, limit=20):
            if str(c.get("folio")).strip() == parent_folio:
                id_parent = c.get("id"); break
    except FracttalError:
        pass
    # tipo/classificação/criticidade herdados da OS pai (ids diretos da tarefa)
    rt = _rpc_call(RPC_WO_TASKS, {"id_work_order": parent_wo, "sort": []})
    t0 = (rt.get("data") or [{}])[0] if isinstance(rt, dict) else {}
    tipo = {"id_main": t0.get("id_task_type_main"),
            "id_priorities": t0.get("id_priorities") or ID_PRIORITIES}
    if t0.get("id_task_type") is not None:
        tipo["id_c1"] = t0.get("id_task_type"); tipo["desc_c1"] = str(t0.get("tasks_types_description") or "")
    if t0.get("id_task_type_2") is not None:
        tipo["id_c2"] = t0.get("id_task_type_2"); tipo["desc_c2"] = str(t0.get("tasks_types_2_description") or "")
    main = str(t0.get("tasks_types_main_description") or "Corretiva")
    # título: [Ticket X][Usina][Ativo] - Motivo  (cai no padrão do COS; sem ticket/motivo → fallback)
    tk = str(ticket or "").strip()
    base = str(motivo or "").strip() or "Chamado"
    titulo = (f"[Ticket {tk}] " if tk else "") + perf_os_nome(asset, base)
    # observação = BLOCO CHAMADO (que o board lê) + a observação livre do operador
    obs_livre = (note or "").strip()
    if dados_chamado:
        dc = dict(dados_chamado); dc.setdefault("os_pai", parent_folio)   # OS de abertura = a OS pai
        note_final = bloco_chamado(dc) + (("\n\n" + obs_livre) if obs_livre else "")
    else:
        note_final = obs_livre
    res = create_work_orders_bulk([asset], titulo, main, (subtarefas or []),
                                  etiqueta_ids=[lid], id_parent=id_parent,
                                  id_responsible=id_responsible, responsible_code=resp_code,
                                  responsible_name=resp_name, note=note_final, tipo=tipo)
    r0 = res[0] if res else {}
    if not r0.get("ok"):
        return {"ok": False, "erro": r0.get("erro") or "não consegui criar a OS."}
    o = r0.get("os") or {}
    novo_wo = o.get("id_work_order")
    aviso = o.get("aviso")
    concluida = False
    if concluir and novo_wo:
        try:
            cr = concluir_os(novo_wo)
            concluida = not (isinstance(cr, dict) and cr.get("ok") is False)
            if not concluida:
                aviso = ((aviso or "") + " OS criada, mas não consegui concluir.").strip()
        except FracttalError as e:
            aviso = ((aviso or "") + f" OS criada, mas não concluiu: {e}").strip()
    return {"ok": True, "folio": o.get("wo_folio"), "id_work_order": novo_wo,
            "os_pai": parent_folio, "etiqueta_ok": bool(o.get("etiquetas")),
            "concluida": concluida, "aviso": aviso}


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
                    "ativo": str(d.get("items_description") or d.get("item_description")
                                 or d.get("assets_description") or d.get("description_item") or "").strip(),
                    "raw": d})
    return out


RPC_WO_FILES = "tasks.work_orders_tasks_files_list"


def _ids_tarefas_da_os(id_work_order) -> list:
    """id_work_order_task de todas as tarefas da OS. Colhe da lista de tarefas E do endpoint de imagens
    (esse traz o id_work_order_task certo dos anexos), pra não errar o id."""
    tids = []

    def _add(v):
        if v and v not in tids:
            tids.append(v)
    try:
        rt = _rpc_call(RPC_WO_TASKS, {"id_work_order": id_work_order, "sort": []})
        for t in (rt.get("data") if isinstance(rt, dict) else rt) or []:
            if isinstance(t, dict):
                _add(t.get("id_work_order_task") or t.get("id_task") or t.get("id"))
    except Exception:
        pass
    try:
        ri = _rpc_call(RPC_WO_IMAGES, {"id_work_order": id_work_order,
            "sort": [{"property": "order_number", "direction": "asc"}]})
        for d in (ri.get("data") if isinstance(ri, dict) else ri) or []:
            if isinstance(d, dict):
                _add(d.get("id_work_order_task") or d.get("id_task"))
    except Exception:
        pass
    return tids


def s3_get_url(name):
    """URL pré-assinada de DOWNLOAD de um objeto do S3 do Fracttal (companies.s3_object_get). O
    files_list só devolve o CAMINHO (value=.ot/...), então preciso disso p/ exibir a imagem. Resposta de
    shape variável → procuro qualquer URL http na resposta. None se falhar."""
    if not name:
        return None
    body = [{"id": str(uuid.uuid4()), "jsonrpc": "2.0", "method": "companies.s3_object_get",
             "params": {"name": name}}]
    try:
        r = requests.post(RPC_PROXY_URL, headers=_rpc_headers(), json=body, timeout=30)
        j = r.json()
    except Exception:
        return None

    def _find(o):
        if isinstance(o, str):
            return o if o.startswith("http") else None
        if isinstance(o, dict):
            for v in o.values():
                u = _find(v)
                if u:
                    return u
        if isinstance(o, list):
            for v in o:
                u = _find(v)
                if u:
                    return u
        return None
    return _find(j)


def get_os_anexos(id_work_order) -> list:
    """Anexos ligados às TAREFAS da OS (a aba 'Anexos' da tarefa no Fracttal — prints da criação via
    Performance/PCM, notas etc.). São por `id_work_order_task`. Inclui ARQUIVOS (imagem/PDF) E notas de
    TEXTO (sem arquivo). Resolve a URL pré-assinada das imagens p/ a galeria. Separados por usuário.
    → [{'value','nome','user','url','is_image','is_text','desc','raw'}]."""
    out, vistos = [], set()
    for tid in _ids_tarefas_da_os(id_work_order):
        try:
            res = _rpc_call(RPC_WO_FILES, {"page": 1, "limit": 200, "start": 0, "is_tree": False,
                                           "node": None, "id_work_order_task": tid})
        except Exception:
            continue
        for d in (res.get("data") if isinstance(res, dict) else res) or []:
            if not isinstance(d, dict):
                continue
            val = str(d.get("value") or "").strip()
            url = _img_url(d)
            desc = str(d.get("description") or "").strip()
            if not val and not url and not desc:          # nada útil
                continue
            nome = (val.rsplit("/", 1)[-1] if val else (desc or "anexo"))
            chave = (val or url or nome).lower()
            if chave in vistos:                            # dedup (tarefas podem repetir)
                continue
            vistos.add(chave)
            user = str(d.get("accounts_name") or d.get("id_personnel_description")
                       or d.get("personnel_description") or d.get("third_party_description")
                       or d.get("created_by") or "").strip()
            low = (val or nome).lower()
            # POR EXTENSÃO, nunca por "tem URL": PDF/Excel/ZIP do S3 também vêm com URL
            # pré-assinada, então `bool(url)` os marcava como IMAGEM — iam para a galeria,
            # a prévia falhava e o arquivo sumia da tela. Era por isso que não dava para
            # abrir documento nenhum.
            is_image = any(low.endswith(e) for e in
                           (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"))
            is_text = not val and not url                  # nota de texto (sem arquivo)
            out.append({"value": val, "nome": nome, "user": user, "url": url,
                        "is_image": is_image, "is_text": is_text, "desc": desc, "raw": d})
    # imagens que só têm o CAMINHO → busca a URL pré-assinada (em paralelo) p/ a galeria abrir
    faltam = [a for a in out if a.get("is_image") and not a.get("url") and a.get("value")]
    if faltam:
        try:
            with ThreadPoolExecutor(max_workers=8) as ex:
                for a, u in zip(faltam, ex.map(lambda x: s3_get_url(x["value"]), faltam)):
                    if u:
                        a["url"] = u
        except Exception:
            pass
    return out


RPC_WO_FORMIT_ATTACH = "tasks.wo_tasks_form_items_attachments_list"   # anexos POR subtarefa (form item)


def get_os_subtarefa_anexos(id_work_order) -> list:
    """Anexos ligados às SUBTAREFAS (form items) de UMA OS. Busca por (id_work_order_task, id_form_item)
    em cada subtarefa com num_attachments>0. type=1 = arquivo (value=caminho S3 → resolve URL pré-assinada);
    type=3 = nota de texto. Cada anexo carrega a subtarefa de origem.
    → [{'url','thumb','descricao','nome','value','subtarefa','is_image','is_text','raw'}]."""
    try:
        rf = _rpc_call(RPC_WO_FORMIT, {"id_work_order": id_work_order})
    except FracttalError:
        return []
    items = rf.get("data") if isinstance(rf, dict) else rf
    alvos = []
    for it in (items if isinstance(items, list) else []):
        if not isinstance(it, dict):
            continue
        try:
            n = int(it.get("num_attachments") or 0)
        except (TypeError, ValueError):
            n = 0
        wid = it.get("id_work_order_task")
        fid = it.get("id_work_orders_tasks_form_items")
        if n > 0 and wid is not None and fid is not None:
            alvos.append((wid, fid, str(it.get("description") or "").strip()))
    if not alvos:
        return []

    def _fetch(alvo):
        wid, fid, _ = alvo
        try:
            res = _rpc_call(RPC_WO_FORMIT_ATTACH, {"page": 1, "limit": 200, "start": 0, "is_tree": False,
                "node": None, "id_work_order_task": wid, "id_work_orders_tasks_form_items": fid,
                "link_attachment": True})
        except Exception:
            return []
        return (res.get("data") if isinstance(res, dict) else res) or []

    try:
        with ThreadPoolExecutor(max_workers=8) as ex:
            resultados = list(ex.map(_fetch, alvos))
    except Exception:
        resultados = [_fetch(a) for a in alvos]

    out = []
    for (wid, fid, sub_desc), data in zip(alvos, resultados):
        for d in (data if isinstance(data, list) else []):
            if not isinstance(d, dict):
                continue
            val = str(d.get("value") or "").strip()
            att_desc = str(d.get("description") or "").strip()
            legenda = sub_desc + (f"  ·  {att_desc}" if att_desc and att_desc != val else "")
            if d.get("type") == 1 and val and "/" in val:      # arquivo (imagem/doc) no S3
                nome = val.rsplit("/", 1)[-1]
                low = nome.lower()
                is_image = any(low.endswith(e) for e in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"))
                out.append({"url": None, "thumb": None, "descricao": legenda or nome, "nome": nome,
                            "value": val, "subtarefa": sub_desc, "is_image": is_image,
                            "is_text": False, "raw": d})
            else:                                               # nota de texto (type 3)
                out.append({"url": None, "thumb": None, "descricao": legenda or att_desc or val,
                            "nome": att_desc or val or "nota", "value": "", "subtarefa": sub_desc,
                            "is_image": False, "is_text": True, "raw": d})
    arquivos = [a for a in out if not a["is_text"] and a["value"]]   # resolve URL pré-assinada (S3)
    if arquivos:
        try:
            with ThreadPoolExecutor(max_workers=8) as ex:
                for a, u in zip(arquivos, ex.map(lambda x: s3_get_url(x["value"]), arquivos)):
                    if u:
                        a["url"] = u
        except Exception:
            pass
    return out


RPC_REQ_FILES = "requests.attachments_list"


def get_solic_anexos(id_request) -> list:
    """Anexos de uma SOLICITAÇÃO (work request). `id_request` = id_code (o Nº). Best-effort — se
    falhar/vier vazio, []. → [{'value','nome','user','url','is_image','raw'}]."""
    if id_request in (None, ""):
        return []
    try:
        res = _rpc_call(RPC_REQ_FILES, {"filter": [], "sort": [], "page": 1, "limit": 200, "start": 0,
                                        "is_tree": False, "node": None, "id_request": id_request})
    except Exception:
        return []
    data = res.get("data") if isinstance(res, dict) else res
    out = []
    for d in (data if isinstance(data, list) else []):
        if not isinstance(d, dict):
            continue
        val = str(d.get("value") or "").strip()
        url = _img_url(d)
        if not val and not url:
            continue
        nome = val.rsplit("/", 1)[-1] if val else "arquivo"
        user = str(d.get("accounts_name") or d.get("id_personnel_description")
                   or d.get("personnel_description") or d.get("created_by") or "").strip()
        low = (val or nome).lower()
        is_image = any(low.endswith(e) for e in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"))
        out.append({"value": val, "nome": nome, "user": user, "url": url,
                    "is_image": is_image, "raw": d})
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


# ── Bloco "O ativo falhou?" (F4) — vocabulário (RPC) + enums fixos (confirmados no payload real) ──
RPC_FALHA_TIPOS  = "tasks.failures_types_list"
RPC_FALHA_CAUSAS = "tasks.failures_causes_list"
RPC_FALHA_DETEC  = "tasks.failures_detection_methods_list"
FALHA_SEVERIDADES = [("Muito baixo", "1"), ("Baixo", "2"), ("Médio", "3"), ("Alto", "4"), ("Muito alto", "5")]
FALHA_DANOS = [("Nenhum", 1), ("Dano ao meio ambiente", 2), ("Danos nas Instalações", 3),
               ("Lesões ao pessoal interno", 4), ("Lesões a Terceiros", 5), ("Outros", 6)]
_falha_listas_cache = {}


def get_falha_listas() -> dict:
    """{tipos, causas, metodos} p/ o bloco 'O ativo falhou?' — cada um [{'id','description'}]. Cacheado."""
    if _falha_listas_cache:
        return _falha_listas_cache

    def _lst(metodo, extra=None):
        p = {"sort": [{"property": "description", "direction": "asc"}], "page": 1, "limit": 200,
             "start": 0, "is_tree": False, "node": None}
        if extra:
            p.update(extra)
        try:
            r = _rpc_call(metodo, p)
            return [{"id": d.get("id"), "description": d.get("description")}
                    for d in (r.get("data") or []) if d.get("id") is not None]
        except FracttalError:
            return []
    d = {"tipos": _lst(RPC_FALHA_TIPOS),
         "causas": _lst(RPC_FALHA_CAUSAS, {"id_failure_type": None}),
         "metodos": _lst(RPC_FALHA_DETEC, {"id_failure_cause": None})}
    if d["tipos"]:
        _falha_listas_cache.update(d)
    return d


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
            "id_priorities": plan.get("id_priorities"),          # criticidade do plano (se vier)
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
            "wo_folio": data.get("wo_folio"),
            "id_work_order_task": data.get("id_work_order_task") or data.get("id_task"),  # p/ anexar imagem
            "raw": result}


def create_planned_os(asset: dict, plan: dict, id_responsible=None, responsible_name: str = "",
                      event_date: datetime = None, to_work_order: bool = True, id_parent=None,
                      descricao: str = None, note: str = "", linkar_plano: bool = True,
                      prog_date: datetime = None) -> dict:
    """Cria 1 tarefa planejada (tasks_noscheduled_react_insert com o plano: id_task + subtarefas +
    tipo do plano). `to_work_order=True` → vira WO direto (1 ativo). `to_work_order=False` → tarefa
    PENDENTE no kanban (p/ depois juntar várias numa OS só, via create_planned_os_one_wo).
    `descricao` = nome custom da tarefa (senão usa o do plano); `note` = observação da OS.
    `linkar_plano=False` → cria como OS avulsa com as subtarefas COPIADAS do plano (id_task=None) — usado
    p/ trackers individuais, cujo plano mora no ativo generalizado. `plan` = get_plan_details.
    Devolve {'id_task','id_work_order','wo_folio','id_work_order_task','raw'}."""
    id_item = asset.get("id")
    if not id_item:
        raise FracttalError(f"Ativo '{asset.get('code')}' sem id_item — recarregue os ativos.")
    if linkar_plano and not plan.get("id_task"):
        raise FracttalError("Plano sem id_task.")
    if not plan.get("subtasks"):
        raise FracttalError("Não carreguei as subtarefas do plano (estrutura do tasks_details a confirmar) "
                            "— relogue e/ou me mande a resposta do tasks_details.")
    ev = event_date if event_date is not None else datetime.now(timezone.utc)
    if ev.tzinfo is None:
        ev = ev.replace(tzinfo=timezone.utc)
    # DATA PROGRAMADA separada da data do INCIDENTE (pedido do Levi, 27/07): antes a programação era
    # sempre "incidente + 10 min", ou seja, não dava para abrir hoje uma OS para a semana que vem.
    # O default reproduz exatamente a conta antiga (prog = ev+10 → janela ev-10 .. ev+20).
    prog = prog_date if prog_date is not None else ev + timedelta(minutes=10)
    if prog.tzinfo is None:
        prog = prog.replace(tzinfo=timezone.utc)
    dur = int(plan.get("duration") or 900)
    id_ref = plan.get("id_task") if linkar_plano else None       # tracker individual = OS não-linkada
    # A JANELA COMEÇA NA HORA ESCOLHIDA. Medido na OS 10402 (30/07): o Fracttal IGNORA o
    # `date_maintenance` que a gente manda e grava o `initial_date` como data de programação —
    # mandei 11:00Z e ele guardou 10:40Z, que era o initial_date (prog − 20 min). Ou seja, toda OS
    # criada por aqui, INCLUSIVE as de Performance, nascia programada 20 minutos antes da hora que
    # a pessoa escolheu. Agora initial_date = prog, e a janela fecha na duração estimada.
    params = {
        "event_date": _iso_z(ev),
        "cal_date_maintenance": _iso_z(prog),
        "date_maintenance": _iso_z(prog),
        "initial_date": _iso_z(prog),
        "final_date": _iso_z(prog + timedelta(seconds=dur)),
        "type_user": "HUMAN_RESOURCES", "id_priorities": plan.get("id_priorities") or ID_PRIORITIES,
        "id_failure_severity": 0, "id_damage_type": 1, "failure_asset": False,
        "to_in_review": False, "work_done": False, "to_work_order": to_work_order, "stop_assets": False,
        "duration": dur, "real_duration": 0,
        "requested_by": (responsible_name or "").strip() or "GridCo O&M", "edit_mode": False,
        "tasks_types_main_description": plan.get("tasks_types_main_description") or "",
        "subtasks": plan.get("subtasks") or [], "array_resources": [],
        "id_item": id_item, "items_description": asset.get("description") or "",
        "id_request": None, "note": note or "", "name": (responsible_name or "").strip() or None,
        "available": None, "initial_date_out_of_service": None,
        "id_group_task": asset.get("id_group_task"), "assigment_date": _iso_z(ev),
        "id_work_order_task_related": None, "date_asset_out_of_service": None,
        "description": (descricao if descricao is not None else (plan.get("description") or "")),
        "id_type_item": asset.get("id_type_item") or 1,
        "path_node": _path_node(asset), "msg_availability": "ASSET_OUT_OF_SERVICE",
        "id_task_reference": id_ref, "id_task": id_ref,
        "id_task_type_main": plan.get("id_task_type_main"),
        "id_task_type": plan.get("id_task_type"), "id_task_type_2": plan.get("id_task_type_2"),
        "tasks_types_description": plan.get("tasks_types_description") or "",
        "tasks_types_2_description": plan.get("tasks_types_2_description") or "",
        "task_note": "", "id_parent": id_parent,          # OS pai (opcional)
    }
    if to_work_order and id_responsible is not None:      # WO direto (1 ativo) → atribui o responsável
        params["id_assigned_user"] = id_responsible
    body = [{"id": str(uuid.uuid4()), "jsonrpc": "2.0", "method": RPC_METHOD, "params": params}]
    return _react_insert_post(body)


# Planos de PERFORMANCE (aparecem SÓ na aba Performance; escondidos no PCM). Casados por trecho
# distintivo do nome (os planos do Levi não têm a palavra "performance" no nome). Para novos planos:
# ou inclua "performance" no nome (auto), ou acrescente o trecho aqui.
_PERF_PLANOS = (
    "coleta de dados de geracao",
    "inspecao geral do inversor",
    "recomposicao de string",
    "verificacao de tracker parado",
)


def _norm_txt(s) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(s.split())


def _plan_family(desc) -> str:
    """Família do plano a partir da descrição ('[Cliente] - MPM - ...' / 'Handover – ...').
    → 'PERFORMANCE'/'MPM'/'MPA'/'MPS'/'MPQ'/'MPW'/'MPT'/'Handover' ou None."""
    import re
    d = str(desc or "")
    dn = _norm_txt(d)
    if "performance" in dn or any(p in dn for p in _PERF_PLANOS):   # PERFORMANCE (aba Performance; ocultos no PCM)
        return "PERFORMANCE"
    if "handover" in dn:
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


# ═══════════════════ PERFORMANCE — OS por ativo a partir de plano ═══════════════════
PERF_TIPOS = ("Inversor", "Estrutura Trackers", "Estação Meteorológica")   # tipos da aba Performance

# Tipos de equipamento que SÓ plantas têm — o discriminador entre PLANTA e MATERIAL/INVENTÁRIO.
# O catálogo tem materiais com "usina" e "cliente" próprios ("0,3P75 - G2", "0,6/1 kV"…), e
# qualquer lista de usinas montada sem este filtro os deixa vazar (aconteceu no COS em 07/07 e
# de novo no filtro do Histórico em 28/07). Espelho do _CARTEIRA_EQUIP das telas.
CARTEIRA_EQUIP = frozenset({"Inversor", "Cabine", "Tracker", "Estrutura Trackers",
                            "Estação Meteorológica", "Skid"})


def _usina_short(usina: str) -> str:
    """'Cliente - Usina - UF' → 'Usina' (miolo). Fallback: a string toda."""
    parts = [p.strip() for p in str(usina or "").split(" - ")]
    return (" - ".join(parts[1:-1]).strip() if len(parts) >= 3 else str(usina or "").strip()) or str(usina or "")


_CONECTIVOS = {"de", "da", "do", "das", "dos", "e", "em", "no", "na", "nos", "nas", "com", "para"}


def _asset_short_name(a: dict) -> str:
    """Nome curto do ativo (do description): 'Inversor 1.1' / 'Tracker 5.100' / 'Estação Meteorológica'.
    O ativo da PRÓPRIA usina não tem nome de equipamento — o description dele é o nome da usina
    ('Thopen - Céu Azul 1 - PR') → devolve o TIPO ('Usina'). Sem isso o título saía com um pedaço
    do nome da usina no lugar do equipamento: '[Céu Azul 1][Thopen -]'."""
    import re
    desc = str(a.get("description") or "").split("{")[0].strip()
    if str(a.get("tipo_code") or "").upper() == "USINA":       # item-usina (_build_records)
        return str(a.get("tipo") or "").strip() or "Usina"
    if len([p for p in desc.split(" - ") if p.strip()]) >= 3:  # 'Cliente - Usina - UF' sem tipo_code
        return str(a.get("tipo") or "").strip() or "Usina"
    m = re.match(r"([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)?)\s+([\d.]+)", desc)
    if m:
        return f"{m.group(1)} {m.group(2)}".strip()
    toks = [t for t in desc.split() if t.strip("-–—·|/")]      # descarta separador solto ('Thopen -')
    if not toks:
        return a.get("code") or "?"
    if len(toks) > 2 and toks[1].lower().strip(".") in _CONECTIVOS:
        return " ".join(toks[:4])                              # 'Cabine de Medição' (não 'Cabine de')
    return " ".join(toks[:2])


def plano_base_nome(desc: str) -> str:
    """Nome do plano sem o prefixo '[...] - ' → 'Recomposição de String'."""
    import re
    d = str(desc or "").split("{")[0].strip()
    return re.sub(r"^\s*\[[^\]]*\]\s*[-–]\s*", "", d).strip()


def perf_os_nome(asset: dict, base: str) -> str:
    """Monta '[Equipamento] - base'.

    PADRÃO NOVO (27/07, decisão do Levi): era '[Usina][Equipamento] - descrição' e passou a ser
    só '[Equipamento] - descrição'. A usina já aparece na própria OS (ativo, local, cliente), e
    repeti-la no título consumia metade do espaço útil da lista — nomes como
    '[Sítio Batinga – Distrito de Água Fria][Estrutura Trackers 109.100]' não cabiam em lugar
    nenhum. Vale para Performance e COS, que é onde esta função é usada."""
    return f"[{_asset_short_name(asset)}] - {base}".strip()


def _eh_tracker_generalizado(a: dict) -> bool:
    return a.get("tipo") == "Estrutura Trackers" and \
        "estrutura trackers" in _norm_txt(a.get("label") or a.get("description"))


def get_performance_alvos(assets_usina: list, card_frase: str) -> dict:
    """Ativos selecionáveis de UMA usina p/ o card (ex.: 'recomposicao de string'). Inversor/Estação: cada
    ativo com o SEU plano. Tracker: plano do GENERALIZADO aplicado aos individuais (não-linkado).
    → {'is_tracker', 'ativos':[{asset, plano_id_task, plano_id_item, linkar}], 'base', 'erro'?}."""
    frase = _norm_txt(card_frase)
    uativos = [a for a in (assets_usina or []) if isinstance(a, dict) and a.get("tipo") in PERF_TIPOS]
    if "tracker" in frase:
        gen = next((a for a in uativos if _eh_tracker_generalizado(a)), None)
        if not gen:
            return {"is_tracker": True, "ativos": [], "erro": "Não achei a Estrutura Trackers desta usina."}
        planos = [p for p in get_plans_for_assets([gen]) if frase in _norm_txt(p.get("description"))]
        if not planos:
            return {"is_tracker": True, "ativos": [], "erro": "A Estrutura Trackers não tem esse plano."}
        pt, pi = planos[0]["id_task"], gen.get("id")
        indiv = [a for a in uativos if a.get("tipo") == "Estrutura Trackers" and not _eh_tracker_generalizado(a)]
        return {"is_tracker": True, "base": plano_base_nome(planos[0].get("description")),
                "ativos": [{"asset": a, "plano_id_task": pt, "plano_id_item": pi, "linkar": False} for a in indiv]}
    # inversor / estação: cada ativo com o SEU plano
    cands = [a for a in uativos if a.get("tipo") in ("Inversor", "Estação Meteorológica")]
    planos = [p for p in get_plans_for_assets(cands) if frase in _norm_txt(p.get("description"))]
    base = plano_base_nome(planos[0].get("description")) if planos else card_frase
    alvos = [{"asset": p["asset"], "plano_id_task": p["id_task"],
              "plano_id_item": p["asset"].get("id"), "linkar": True} for p in planos]
    # A ESTAÇÃO não tem o plano de coleta — ele mora no INVERSOR. Conferido em Brodowski 1: a ETM
    # tem 11 planos (MPM/MPS/MPA/Handover de estação) e NENHUM é o de coleta, então o filtro por
    # frase nunca devolvia a estação e o modo ETM abria com a lista vazia em toda usina.
    # Solução: a estação entra apontando para o plano do inversor, com `linkar=False` → OS avulsa
    # com as subtarefas COPIADAS. É o mesmo arranjo dos trackers individuais, cujo plano também
    # mora em outro ativo. Só vale para o card de coleta; nos outros, estação não faz sentido.
    if "coleta de dados" in frase and alvos:
        ja_tem = {a["asset"].get("id") for a in alvos}
        p0 = alvos[0]
        for est in uativos:
            if est.get("tipo") == "Estação Meteorológica" and est.get("id") not in ja_tem:
                alvos.append({"asset": est, "plano_id_task": p0["plano_id_task"],
                              "plano_id_item": p0["plano_id_item"], "linkar": False})
        # A USINA INTEIRA como alvo (Levi, 31/07): coletar geração de uma planta de 14 inversores
        # criava 14 OS para uma tarefa que é uma só. O item-usina entra pelo MESMO arranjo da
        # estação — plano do inversor, `linkar=False` — e vira UMA OS no ativo da planta.
        # Vem de `assets_usina` (não de `uativos`), porque o tipo 'Usina' não está em PERF_TIPOS.
        for u in (assets_usina or []):
            if (isinstance(u, dict) and u.get("tipo") == "Usina"
                    and u.get("id") and u.get("id") not in ja_tem):
                alvos.append({"asset": u, "plano_id_task": p0["plano_id_task"],
                              "plano_id_item": p0["plano_id_item"], "linkar": False})
                break                                   # uma planta tem um item-usina
    return {"is_tracker": False, "base": base, "ativos": alvos}


def _find_http_url(o):
    """Primeira URL http encontrada (recursivo) numa resposta de shape variável."""
    if isinstance(o, str):
        return o if o.startswith("http") else None
    if isinstance(o, dict):
        for v in o.values():
            u = _find_http_url(v)
            if u:
                return u
    if isinstance(o, list):
        for v in o:
            u = _find_http_url(v)
            if u:
                return u
    return None


def _find_dict_by_keys(o, nomes):
    """Primeiro dict aninhado sob uma chave em `nomes` (ex.: 'fields'/'form' de um presigned POST)."""
    if isinstance(o, dict):
        for k, v in o.items():
            if str(k).lower() in nomes and isinstance(v, dict):
                return v
        for v in o.values():
            d = _find_dict_by_keys(v, nomes)
            if d:
                return d
    if isinstance(o, list):
        for v in o:
            d = _find_dict_by_keys(v, nomes)
            if d:
                return d
    return None


def _s3_object_post(nome_s3: str, size: int, checksum_hex: str):
    """Pede o upload pré-assinado (companies.s3_object_post). Devolve a resposta JSON CRUA (dict/list)
    pra procurar a URL/fields de forma robusta (o shape varia)."""
    body = [{"id": str(uuid.uuid4()), "jsonrpc": "2.0", "method": "companies.s3_object_post",
             "params": {"name": nome_s3, "size": size, "action": "edit",
                        "checksum": {"hash_algorithm": "SHA256", "hex": checksum_hex}}}]
    r = requests.post(RPC_PROXY_URL, headers=_rpc_headers(), json=body, timeout=45)
    if r.status_code in (401, 403):
        raise SessionExpired("Sessão do Fracttal venceu. Relogue.")
    if r.status_code >= 400:
        raise FracttalError(f"s3_object_post HTTP {r.status_code}: {(r.text or '')[:300]}")
    try:
        return r.json()
    except ValueError:
        raise FracttalError(f"s3_object_post resposta não-JSON: {(r.text or '')[:300]}")


def _s3_post_data(resp) -> dict:
    """Extrai o result.data do s3_object_post (onde vêm bucket/host/key/credential/signature/policy…)."""
    rec = resp[0] if isinstance(resp, list) and resp else resp
    result = rec.get("result") if isinstance(rec, dict) else rec
    data = result.get("data") if isinstance(result, dict) else result
    return data if isinstance(data, dict) else {}


def _s3_upload(data: dict, data_bytes: bytes, filename: str, ct: str):
    """Faz o upload no S3 conforme a forma que a Fracttal devolveu. Confirmado ao vivo: PRESIGNED POST da
    AWS (bucket/host/key/credential/signature/policy/date…) → monta o form AWS4 POST (file por último).
    Fallback: URL direta (PUT) ou url+fields."""
    keys = list(data.keys())
    if data.get("bucket") and data.get("host"):           # presigned POST da AWS (caso da Fracttal)
        bucket, host = data["bucket"], data["host"]
        url = f"https://{bucket}.{host}/" if "." not in bucket else f"https://{host}/{bucket}/"

        def g(*ks):
            return next((data[k] for k in ks if data.get(k)), None)
        form = {
            "key": data.get("key"),
            "X-Amz-Algorithm": g("algorithm", "x_amz_algorithm", "x-amz-algorithm") or "AWS4-HMAC-SHA256",
            "X-Amz-Credential": g("credential", "x_amz_credential", "x-amz-credential"),
            "X-Amz-Date": g("date", "x_amz_date", "x-amz-date", "amz_date"),
            "Policy": g("policy", "Policy"),
            "X-Amz-Signature": g("signature", "x_amz_signature", "x-amz-signature"),
        }
        for src, dst in (("acl", "acl"), ("content_type", "Content-Type"),
                         ("security_token", "X-Amz-Security-Token"),
                         ("x_amz_security_token", "X-Amz-Security-Token"),
                         ("encryption", "x-amz-server-side-encryption")):
            if data.get(src):
                form[dst] = data[src]
        form["success_action_status"] = str(data.get("success_action_status") or "200")   # condição da policy
        import hashlib as _hl
        import base64 as _b64
        # a policy exige x-amz-checksum-sha256 (base64 do SHA256 dos bytes — o S3 confere o conteúdo)
        form["x-amz-checksum-sha256"] = _b64.b64encode(_hl.sha256(data_bytes).digest()).decode()
        falta = [k for k in ("key", "X-Amz-Credential", "X-Amz-Date", "Policy", "X-Amz-Signature")
                 if not form.get(k)]
        if falta:
            raise FracttalError(f"presigned POST incompleto (falta {falta}). CHAVES do data: {keys}")
        form = {k: v for k, v in form.items() if v is not None}
        return requests.post(url, data=form, files={"file": (filename, data_bytes, ct)}, timeout=180)
    # fallback: url direta (PUT) ou url + fields
    url = _find_http_url(data)
    fields = _find_dict_by_keys(data, ("fields", "form", "formdata", "inputs"))
    if not url:
        raise FracttalError(f"s3_object_post sem forma de upload conhecida. CHAVES do data: {keys}")
    if isinstance(fields, dict):
        return requests.post(url, data=fields, files={"file": (filename, data_bytes, ct)}, timeout=180)
    return requests.put(url, data=data_bytes, headers={"Content-Type": ct}, timeout=180)


def attach_imagem_os(id_work_order, id_work_order_task, data_bytes: bytes, filename: str) -> dict:
    """Sobe 1 imagem no S3 do Fracttal e registra na tarefa da OS. Fluxo: s3_object_post (devolve um
    presigned POST da AWS) → POST no S3 → work_orders_tasks_files_insert."""
    import hashlib
    import mimetypes
    if not (id_work_order and id_work_order_task):
        raise FracttalError("OS criada sem id_work_order/_task — não dá p/ anexar.")
    nome_s3 = f".ot/{id_work_order}/{filename}"
    resp = _s3_object_post(nome_s3, len(data_bytes), hashlib.sha256(data_bytes).hexdigest())
    data = _s3_post_data(resp)
    ct = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    try:
        up = _s3_upload(data, data_bytes, filename, ct)
    except requests.RequestException as e:
        raise FracttalError(f"upload S3 falhou ({e}).")
    if up.status_code >= 400:
        raise FracttalError(f"upload S3 HTTP {up.status_code}: {(up.text or '')[:300]}")
    reg = [{"id": str(uuid.uuid4()), "jsonrpc": "2.0", "method": "tasks.work_orders_tasks_files_insert",
            "params": [{"id": str(uuid.uuid4()), "id_personnel": None, "id_third_party": None, "id_task": None,
                        "id_attached": id_work_order_task, "id_item": None, "id_work_order_task": id_work_order_task,
                        "id_work_orders_tasks_files": None, "id_work_orders_tasks_form_items": None, "id_request": None,
                        "link_attachment": False, "value": nome_s3, "description": "", "type": 1, "typeRender": "",
                        "link": "", "can_edit": True}]}]
    r2 = requests.post(RPC_PROXY_URL, headers=_rpc_headers(), json=reg, timeout=45)
    if r2.status_code >= 400:
        raise FracttalError(f"files_insert HTTP {r2.status_code}: {(r2.text or '')[:200]}")
    return {"ok": True, "value": nome_s3}


_LABEL_IDS = {}            # cache {nome normalizado: id} — 0 = procurou e não achou


def label_id_por_nome(nome: str):
    """id de uma etiqueta pelo NOME (casa exato, senão por trecho); cacheia. None se não existir no
    catálogo — quem chama segue sem a etiqueta em vez de derrubar a criação da OS."""
    n = _norm_txt(nome)
    if not n:
        return None
    if n not in _LABEL_IDS:
        try:
            labels = get_labels()
            exata = next((l for l in labels if _norm_txt(l.get("description")) == n), None)
            parcial = next((l for l in labels if n in _norm_txt(l.get("description"))), None)
            _LABEL_IDS[n] = (exata or parcial or {}).get("id") or 0
        except Exception:
            return None                                  # falha de rede não vira "não existe"
    return _LABEL_IDS[n] or None


def _label_performance_id():
    """id da etiqueta 'Performance' (p/ marcar toda OS de Performance)."""
    return label_id_por_nome("performance")


def create_performance_os(itens: list, id_responsible=None, responsible_name: str = "",
                          event_date: datetime = None, id_parent=None, progresso=None,
                          prog_date: datetime = None, etiquetas_extra=None) -> list:
    """Cria N OS (1 por ativo). `itens` = [{asset, plano_id_task, plano_id_item, linkar, base, note, imagens}]
    onde imagens = [{'bytes','nome'}]. Lê o plano (cache por id_task), cria a OS '[Ativo] - base' + note,
    marca com a etiqueta 'Performance' e anexa as imagens. → [{ok, asset, folio/erro, n_img_ok, img_erro}].

    `event_date` = data do INCIDENTE; `prog_date` = data PROGRAMADA (None → incidente + 10 min, como era).
    `etiquetas_extra` = nomes de etiquetas a somar à 'Performance' (o modo ETM manda 'ENGENHARIA').
    Um item pode trazer `titulo`: título LITERAL da OS, que pula o prefixo automático `[Ativo] -`."""
    cache, out = {}, []
    lbl_perf = _label_performance_id()               # etiqueta "Performance" em toda OS criada aqui
    lbls = [l for l in [lbl_perf] +
            [label_id_por_nome(n) for n in (etiquetas_extra or [])] if l]
    itens = [it for it in (itens or []) if isinstance(it.get("asset"), dict)]
    pai_cache = {}
    def _resolve_pai(folio):                         # nº da OS pai (por ativo) → id_parent (via parents_list)
        folio = str(folio or "").strip()
        if not folio:
            return None
        if folio not in pai_cache:
            pid = None
            try:
                for c in buscar_os_pai(folio, limit=20):
                    if str(c.get("folio")).strip() == folio:
                        pid = c.get("id"); break
            except Exception:
                pid = None
            pai_cache[folio] = pid
        return pai_cache[folio]
    for i, it in enumerate(itens):
        a = it["asset"]
        try:
            k = it.get("plano_id_task")
            if k not in cache:
                cache[k] = get_plan_details(k, it.get("plano_id_item"))
            plan = cache[k]
            nome = (it.get("titulo") or "").strip() or \
                perf_os_nome(a, it.get("base") or plano_base_nome(plan.get("description")))
            ip = _resolve_pai(it.get("os_pai")) or id_parent   # OS pai do ativo (senão o global, se houver)
            res = create_planned_os(a, plan, id_responsible=id_responsible, responsible_name=responsible_name,
                                    event_date=event_date, id_parent=ip, descricao=nome,
                                    note=it.get("note") or "", linkar_plano=it.get("linkar", True),
                                    prog_date=prog_date)
            if lbls and res.get("id_work_order"):
                try:
                    apply_labels(res["id_work_order"], lbls)
                except Exception:
                    pass
            nok, nerr = 0, []
            for img in (it.get("imagens") or []):
                try:
                    attach_imagem_os(res.get("id_work_order"), res.get("id_work_order_task"),
                                     img.get("bytes"), img.get("nome") or "imagem.png")
                    nok += 1
                except Exception as e:
                    nerr.append(str(e)[:600])
            out.append({"ok": True, "asset": a.get("label") or a.get("code"), "folio": res.get("wo_folio"),
                        "n_img_ok": nok, "img_erro": nerr})
        except SessionExpired:
            raise
        except Exception as e:
            out.append({"ok": False, "asset": a.get("label") or a.get("code"), "erro": str(e)[:200]})
        if progresso:
            progresso(i + 1, len(itens))
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


def get_subtask_names(pares: list) -> dict:
    """Descrições das subtarefas de cada plano. `pares` = [(id_task, id_item)]. → {id_task: [desc,...]}
    (em paralelo, via get_plan_details). Defensivo: plano que falhar/sem subtarefa não entra no dict."""
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
            nomes = [str(s.get("description") or "").strip() for s in (det.get("subtasks") or [])]
            return (idt, [n for n in nomes if n])
        except Exception:
            return (idt, None)
    out = {}
    if not uniq:
        return out
    with ThreadPoolExecutor(max_workers=8) as ex:
        for idt, nomes in ex.map(_one, list(uniq.items())):
            if nomes is not None:
                out[idt] = nomes
    return out


def create_planned_os_multi(selecoes: list, id_responsible, responsible_name: str = "",
                            event_date: datetime = None, id_parent=None) -> dict:
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
                                  to_work_order=False, id_parent=id_parent)
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


RPC_WO_UPDATE = "tasks.work_orders_update"      # troca o RESPONSÁVEL de uma OS já criada


def mudar_responsavel(id_work_order, id_personnel, nota=None) -> dict:
    """Troca o responsável de uma OS existente.

    Capturado do Fracttal web (28/07). É a ÚNICA edição de OS já criada que a API aceita além de
    status, etiqueta e anexo — e reabre a possibilidade de repassar trabalho sem sair do app.
    `type_user: HUMAN_RESOURCES` é o que distingue pessoa de terceiro; `id_assigned_user` é o
    id_personnel (o mesmo que `get_responsaveis` devolve), NÃO o id da OS."""
    if not id_work_order:
        return {"ok": False, "erro": "OS sem id."}
    if not id_personnel:
        return {"ok": False, "erro": "Escolha a pessoa."}
    res = _rpc_call(RPC_WO_UPDATE, {"page": 1, "limit": 200, "start": 0, "append": True,
                                    "id": id_work_order, "type_user": "HUMAN_RESOURCES",
                                    "id_assigned_user": id_personnel, "note": nota})
    if isinstance(res, dict) and res.get("success") is False:
        return {"ok": False, "erro": str(res.get("message") or "não consegui trocar o responsável")}
    return {"ok": True, "raw": res}


RPC_WO_CHANGE_STATUS = "tasks.work_orders_change_status"        # muda o status da WO (1..4)
RPC_WO_RECALCULATE   = "tasks.work_orders_recalculate_new"     # confirma o fechamento (irreversível)


def mudar_status_os(id_work_order, id_status: int = 1) -> dict:
    """Muda o status da OS SEM fechá-la (1 Em Processo · 2 Em Verificação). É a única escrita que
    a API permite numa OS já criada além de etiqueta/anexo — e é o que a equipe de chamados pediu:
    'quando eu abrir o chamado, eu não vou concluir ela, vou colocar como em progresso'.
    NÃO usar com 3 (Concluída): fechar exige o recalculate e é irreversível → `concluir_os`."""
    if not id_work_order:
        return {"ok": False, "erro": "OS sem id."}
    if int(id_status) not in (1, 2):
        return {"ok": False, "erro": "Status inválido aqui (use 1 Em Processo ou 2 Em Verificação)."}
    res = _rpc_call(RPC_WO_CHANGE_STATUS, {"id_work_order": id_work_order,
                                           "id_status_work_order": int(id_status),
                                           "verify_triggers": True, "update_readings_after": False})
    if isinstance(res, dict) and res.get("success") is False:
        return {"ok": False, "erro": str(res.get("message") or "o Fracttal recusou a mudança "
                                         "(sua conta tem permissão?)")}
    return {"ok": True, "status": WO_STATUS.get(int(id_status), "")}


def concluir_os(id_work_order) -> dict:
    """CONCLUI (fecha) uma OS — IRREVERSÍVEL. 2 passos (fluxo capturado ao vivo, OS 9226):
    1) muda o status p/ Concluída (3); 2) recalcula/fecha (marca subtarefas não executadas como
    pendentes e fecha a OS). A AUTORIZAÇÃO é do Fracttal — sem permissão, a API recusa (FracttalError).
    → {'ok':True}."""
    if not id_work_order:
        raise FracttalError("OS sem id — recarregue o histórico.")
    r1 = _rpc_call(RPC_WO_CHANGE_STATUS, {"id_work_order": id_work_order, "id_status_work_order": 3,
                                          "verify_triggers": True, "update_readings_after": False})
    if isinstance(r1, dict) and r1.get("success") is False:
        raise FracttalError(str(r1.get("message") or "Não foi possível mudar o status da OS "
                                                     "(sua conta tem permissão p/ fechar OS?)."))
    r2 = _rpc_call(RPC_WO_RECALCULATE, {"id_work_order": id_work_order, "verify_work_in_progress": True})
    if isinstance(r2, dict) and r2.get("success") is False:
        raise FracttalError(str(r2.get("message") or "Não foi possível fechar a OS."))
    return {"ok": True, "raw": r2}


def cancelamento_da_os(folio) -> dict:
    """Motivo e observação do cancelamento de uma OS. → {'motivo','nota'} (vazios se não achar).

    VEM DO REST, não do RPC (Levi, 03/08). Procurei o motivo nos três lugares que o app já usa —
    a linha do `work_orders_list_react`, o cabeçalho do `work_order_details_new` e o registro da
    tarefa — e não está em nenhum: são 45 e 95 campos, nenhum com o motivo nem com o id dele.
    O REST expõe em `work_orders_status_custom_description`, e responde por NÚMERO da OS
    (`work_orders/10559/`) em ~0,2 s, sem paginar.

    QUEM CANCELOU NÃO EXISTE em lugar nenhum. Todos os campos de pessoa do registro são outra
    coisa: `created_by` é quem abriu (conferido na 10533 — Juliana abriu, o cancelamento é
    anônimo), `user_assigned`/`personnel_description` é o responsável, `requested_by` é o
    solicitante. Não há "cancelado por". Se um dia precisar, sai da bitácora do Fracttal web.

    A `nota` é a observação digitada no cancelamento: ela SOBRESCREVE a observação da OS
    (`note`); a original continua em `task_note`."""
    folio = str(folio or "").strip()
    if not folio:
        return {"motivo": "", "nota": ""}
    try:
        r = _req("GET", "work_orders/%s/" % folio, timeout=15)
    except FracttalError:
        return {"motivo": "", "nota": ""}
    d = (r.get("data") if isinstance(r, dict) else r) or []
    w = d[0] if isinstance(d, list) and d else (d if isinstance(d, dict) else {})
    return {"motivo": str((w or {}).get("work_orders_status_custom_description") or "").strip(),
            "nota": str((w or {}).get("note") or "").strip()}


def checar_data_fim(id_work_order) -> dict:
    """Quais tarefas da OS estão SEM data de fim (`final_date`).
    → {'ok': bool, 'total': n, 'sem_fim': [título, …]}  (`ok` = todas têm data).

    POR QUE ISTO EXISTE (Levi, 03/08 — caso da OS 10509, religamento em Marialva): a OS fechou
    e a tarefa ficou sem data de fim, e ninguém soube até alguém ir procurar. Medido: das OS
    criadas pelo caminho Fase 1 + Fase 2 (Criar OS, COS, Chamados, PCM, Clonar), a tarefa nasce
    com `initial_date` e `final_date` NULOS — o registro do kanban que vira a OS simplesmente não
    tem esses dois campos, e o `concluir_os` NÃO os preenche (testado na OS 10567: nula antes,
    nula depois). Quem preenche é o cronômetro de execução; sem ele a OS fecha sem data para
    sempre, e conclusão é irreversível.

    Defensivo de propósito: erro de rede aqui devolve `ok=True`. Este é um aviso, não um portão —
    derrubar a conclusão de uma OS porque a conferência falhou seria pior que o problema."""
    if not id_work_order:
        return {"ok": True, "total": 0, "sem_fim": []}
    try:
        rt = _rpc_call(RPC_WO_TASKS, {"id_work_order": id_work_order, "sort": []})
    except FracttalError:
        return {"ok": True, "total": 0, "sem_fim": []}
    tasks = rt.get("data") if isinstance(rt, dict) else rt
    tasks = tasks if isinstance(tasks, list) else []
    sem = []
    for t in tasks:
        v = t.get("final_date")
        if v in (None, "") or str(v).lower() == "none":
            sem.append(str(t.get("tasks_description") or "").strip() or "(tarefa sem título)")
    return {"ok": not sem, "total": len(tasks), "sem_fim": sem}


def concluir_os_checado(id_work_order) -> dict:
    """`concluir_os` + a RECONFERÊNCIA da data de fim, na mesma thread de trabalho.

    O segundo lado do double check: o primeiro avisa ANTES (a tela lê o que já carregou), este
    confere DEPOIS, contra o servidor. Sem ele o app anunciaria "OS concluída" para uma OS que
    fechou sem data de fim — que é exatamente o que ninguém percebeu na 10509.
    → {'ok': True, 'data_fim': {…}} — ver `checar_data_fim`."""
    r = concluir_os(id_work_order)
    return {**r, "data_fim": checar_data_fim(id_work_order)}


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
              etiqueta_ids: list = None, note: str = "", scheduled_date: datetime = None,
              id_parent=None) -> dict:
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
                                event_date=(t.get("event_date") or scheduled_date),
                                id_parent=id_parent)
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
                        descricao: str = "", note: str = "", tipo_task: str = "Corretiva",
                        id_parent=None) -> dict:
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
    return clonar_os(tarefas, id_responsible, responsible_name, etiqueta_ids=None, note=note,
                     id_parent=id_parent)


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


def _req_row_to_d(r, loc):
    """Linha crua do requests_list → dict do card de solicitação (cliente/usina/ativo/descrição/etc.)."""
    item = str(r.get("items_description") or "")
    code = (r.get("code_item") or "").strip() or _extrai_code(item)
    ativo = (item.split("{")[0]).strip()[:60] or code
    cliente, usina, tipo = loc.get(code, ("", "", ""))
    st_raw = r.get("requests_x_status_description") or ""
    desc_full = str(r.get("description") or "").strip()
    return {
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
    }


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
    return [_req_row_to_d(r, loc) for r in (data if isinstance(data, list) else [])]


def get_solicitacao_por_os(id_work_order):
    """Detalhe (dict no formato do SolicitacaoDialog) da solicitação ligada a esta OS. None se não
    houver. Usado p/ abrir o card da solicitação a partir do card da OS."""
    if not id_work_order:
        return None
    try:
        res = _rpc_call(RPC_REQ_LIST, {"filter": [{"operator": "=", "property": "id_work_order",
            "value": id_work_order}], "page": 1, "limit": 5, "start": 0})
    except FracttalError:
        return None
    data = res.get("data") if isinstance(res, dict) else res
    loc = _code_to_loc()
    for r in (data if isinstance(data, list) else []):
        if str(r.get("id_work_order")) == str(id_work_order):
            return _req_row_to_d(r, loc)
    return None


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


def _anexa_imagens_bulk(fase1, imagens_por_ativo):
    """Anexa as imagens de cada ativo na OS criada (best-effort). `imagens_por_ativo` = {code: [{bytes,nome}]}.
    Pega o id_work_order_task da OS via _ids_tarefas_da_os. Falha de anexo vira 'aviso' na OS, não derruba."""
    if not imagens_por_ativo:
        return
    for r in fase1:
        os_ = r.get("os") or {}
        if not (r.get("ok") and os_.get("id_work_order")):
            continue
        imgs = imagens_por_ativo.get(r.get("code")) or []
        if not imgs:
            continue
        idwo = os_["id_work_order"]
        try:
            tids = _ids_tarefas_da_os(idwo)
        except Exception:
            tids = []
        tid = tids[0] if tids else None
        nok = 0
        for im in imgs:
            try:
                attach_imagem_os(idwo, tid, im.get("bytes"), im.get("nome") or "imagem.png")
                nok += 1
            except Exception:
                pass
        if nok < len(imgs):
            os_["aviso"] = ((os_.get("aviso") or "") + f" {len(imgs) - nok} imagem(ns) não anexaram.").strip()


def create_work_orders_bulk(assets: list, description: str, task_type: str, subtasks: list,
                            etiqueta: str = "", responsible_code: str = "",
                            responsible_name: str = "", id_responsible=None,
                            etiqueta_ids: list = None, note: str = "", tipo: dict = None,
                            finalizar: dict = None, event_date=None, id_parent=None,
                            imagens_por_ativo: dict = None, por_ativo: dict = None,
                            falha: dict = None) -> list:
    """Cria N OS (uma por ativo). Fase 1: cria a tarefa pendente (create_os_rpc). Fase 2 (se
    id_responsible): converte em WO numerada + atribui o responsável. Fase 3 (se etiqueta_ids):
    aplica as etiquetas na WO. Fase 4 (se imagens_por_ativo): anexa as imagens em cada OS.
    `por_ativo` (opcional, {code: {'description','note'}}): título/observação POR ativo (COS F2 —
    cada OS ganha '[Usina][Equip] - Motivo' e a observação-pipe do seu próprio ativo). NÃO interrompe
    no 1º erro:
    → [{'code','ok':True,'os':{id_task,id_work_order,wo_folio[,etiquetas][,aviso]}} | {'code','ok':False,'erro'}].
    `finalizar` (OS já realizada) → cada create já devolve a WO concluída c/ responsável → pula Fase 2."""
    fase1 = []
    for a in assets:
        asset = a if isinstance(a, dict) else _asset_by_code(a)
        code = asset.get("code") if isinstance(asset, dict) else str(a)
        if not isinstance(asset, dict):
            fase1.append({"code": code, "ok": False, "erro": "ativo não encontrado no cache."})
            continue
        ov = (por_ativo or {}).get(code) or {}          # override por ativo (COS F2)
        desc_i = ov.get("description", description)
        note_i = ov.get("note", note)
        try:
            os_ = create_os_rpc(asset, desc_i, task_type, subtasks,
                                requested_by=responsible_name, etiqueta=etiqueta, note=note_i,
                                tipo=tipo, event_date=event_date, finalizar=finalizar,
                                id_parent=id_parent, falha=falha)
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
        _anexa_imagens_bulk(fase1, imagens_por_ativo)
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
    _anexa_imagens_bulk(fase1, imagens_por_ativo)
    return fase1


def create_work_orders_datas(asset: dict, description: str, task_type: str, subtasks: list,
                             datas: list, responsible_code: str = "", responsible_name: str = "",
                             id_responsible=None, etiqueta_ids: list = None, note: str = "",
                             tipo: dict = None, finalizar: dict = None, id_parent=None,
                             falha: dict = None) -> list:
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
                                event_date=ev_dt, tipo=tipo, finalizar=fin, id_parent=id_parent, falha=falha)
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


# ══════════════════════════════════════════════════════════════════════════════
# EXECUÇÃO DA TAREFA — iniciar · pausar · retomar · concluir
#
# Fluxo capturado ao vivo no Fracttal web (27/07). Tudo gira no `id_work_order_task`
# (a TAREFA), não na OS — uma OS pode ter várias tarefas, cada uma com seu cronômetro.
#
# POR QUE ISTO IMPORTA para o kanban de Performance: o "fazendo agora" dependia do analista
# LEMBRAR de colar a etiqueta "Atividade em execução". Disciplina manual é exatamente o que
# fez 95% das OS atribuídas a analistas terminarem canceladas. Com o cronômetro do próprio
# Fracttal, ele clica em Iniciar e o tempo é medido — e o tempo de conclusão deixa de ser
# "data de fim menos data de criação", que conta noite e fim de semana como trabalho.
#
# A ASSINATURA (`work_orders_sign_update`) NÃO entra aqui: é etapa da interface web, não do
# servidor — o `concluir_os` fecha OS sem ela desde sempre. E assinatura gerada pelo app seria
# registro falso de que alguém assinou.
# ══════════════════════════════════════════════════════════════════════════════
RPC_EXEC_INSERT = "tasks.work_orders_tasks_execution_insert"
RPC_EXEC_PAUSE = "tasks.wo_tasks_execution_pause"
RPC_EXEC_RESUME = "tasks.wo_tasks_execution_resume"
RPC_EXEC_FINISH = "tasks.work_orders_tasks_execution_finish"
RPC_EXEC_GET = "tasks.wo_task_get_execution"
RPC_EXEC_LIST = "tasks.wo_tasks_execution_list"
RPC_EXEC_TYPES = "tasks.wo_tasks_execution_types_list"

_PAUSA_CACHE = []


def motivos_pausa() -> list:
    """Catálogo de motivos de pausa → [{'id','descricao'}]. Cacheado: não muda no meio do dia."""
    global _PAUSA_CACHE
    if _PAUSA_CACHE:
        return _PAUSA_CACHE
    res = _rpc_call(RPC_EXEC_TYPES, {"filter": [], "sort": [{"property": "description",
                                                             "direction": "asc"}],
                                     "page": 1, "limit": 200, "start": 0,
                                     "is_tree": False, "node": None})
    data = res.get("data") if isinstance(res, dict) else res
    _PAUSA_CACHE = [{"id": d.get("id"), "descricao": str(d.get("description") or "").strip()}
                    for d in (data if isinstance(data, list) else []) if d.get("id")]
    return _PAUSA_CACHE


RPC_WO_TASKS_NEW = "tasks.work_orders_tasks_new_list"


def id_tarefa_da_os(id_work_order):
    """`id_work_order_task` da PRIMEIRA tarefa da OS — é nela que o cronômetro roda.

    USA O CAMPO `id` DESTE endpoint, e não o `_ids_tarefas_da_os` (que serve aos ANEXOS e
    prefere outros campos). A diferença derrubou o primeiro teste ao vivo: aquele devolvia
    `id_task` = 20878948, que é o MODELO da tarefa, não a tarefa desta OS — o Fracttal recusou
    com FOREIGN_KEY_VIOLATION. O valor certo da mesma OS é `id` = 55875684.
    Conferido contra a captura do Levi: WO 36323580 → id 55869196, exatamente o que o web usa."""
    if not id_work_order:
        return None
    try:
        r = _rpc_call(RPC_WO_TASKS_NEW, {"filter": [], "sort": [], "page": 1, "limit": 200,
                                         "start": 0, "is_tree": False, "node": None,
                                         "id_work_order": id_work_order})
    except FracttalError:
        return None
    d = (r.get("data") if isinstance(r, dict) else r) or []
    for t in d:
        if isinstance(t, dict) and t.get("id"):
            return t["id"]
    return None


EXEC_ENCERRADA = 3          # id_wo_tasks_execution_status
ACAO_RODANDO, ACAO_PAUSADA = 1, 0    # action_type


def execucao_atual(id_work_order_task) -> dict:
    """Estado do cronômetro → {'estado','inicio','trabalhado_s','pausado_s','motivo','raw'}.
    estado: 'parada' (nunca começou ou já encerrou) | 'rodando' | 'pausada'.

    LIDO DOS CAMPOS CERTOS, não deduzido por data (conferido contra uma execução real,
    tarefa 55869196): a resposta traz `id_wo_tasks_execution_status` (3 = encerrada) e uma
    lista `actions` com os SEGMENTOS do ciclo — cada um com `action_type` (1 = IN_PROGRESS,
    0 = PAUSED) e `duration_seconds`.

    É daí que sai o TEMPO REAL de trabalho: soma dos segmentos em andamento, sem as pausas.
    Muito melhor que "data de fim menos data de criação", que conta noite e fim de semana."""
    vazio = {"estado": "parada", "inicio": None, "trabalhado_s": 0, "pausado_s": 0,
             "motivo": "", "raw": None}
    if not id_work_order_task:
        return vazio
    try:
        res = _rpc_call(RPC_EXEC_GET, {"page": 1, "limit": 200, "start": 0, "append": True,
                                       "id_work_order_task": id_work_order_task})
    except FracttalError:
        return vazio
    d = res.get("data") if isinstance(res, dict) else res
    if isinstance(d, list):
        d = d[0] if d else None
    if not isinstance(d, dict) or not d:
        return vazio
    # TAREFA NUNCA INICIADA: a resposta NÃO vem vazia — vem um esqueleto com todas as chaves
    # em null. `not d` não pega isso (o dict tem chaves), e sem final_date e sem actions o
    # código caía no ramo "rodando" — ou seja, toda tarefa nunca cronometrada apareceria como
    # EM EXECUÇÃO. Quem diz que existe execução é o `initial_date`.
    if not d.get("initial_date"):
        return vazio

    acoes = [a for a in (d.get("actions") or []) if isinstance(a, dict)]
    trab = sum((a.get("duration_seconds") or 0) for a in acoes
               if a.get("action_type") == ACAO_RODANDO)
    paus = sum((a.get("duration_seconds") or 0) for a in acoes
               if a.get("action_type") == ACAO_PAUSADA)
    ultima = acoes[-1] if acoes else {}

    if d.get("id_wo_tasks_execution_status") == EXEC_ENCERRADA or d.get("final_date"):
        estado = "parada"
    elif ultima.get("action_type") == ACAO_PAUSADA:
        estado = "pausada"
    else:
        estado = "rodando"
    return {"estado": estado, "inicio": str(d.get("initial_date") or "")[:19],
            "trabalhado_s": int(trab), "pausado_s": int(paus),
            "motivo": str(ultima.get("paused_reason_description") or "").strip()
                      if estado == "pausada" else "",
            "raw": d}


def iniciar_execucao(id_work_order_task) -> dict:
    """Liga o cronômetro. `initial_date` em UTC com Z, como o web manda."""
    if not id_work_order_task:
        return {"ok": False, "erro": "OS sem tarefa — não dá para iniciar."}
    import datetime as _d
    agora = _d.datetime.now(_d.timezone.utc)
    iso = agora.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (agora.microsecond // 1000)
    res = _rpc_call(RPC_EXEC_INSERT, {"page": 1, "limit": 200, "start": 0, "append": True,
                                      "id_wo_tasks_execution_categorizations": None,
                                      "id_work_order_task": id_work_order_task,
                                      "initial_date": iso, "done": False})
    if isinstance(res, dict) and res.get("success") is False:
        return {"ok": False, "erro": str(res.get("message") or "nao consegui iniciar")}
    return {"ok": True, "raw": res}


def pausar_execucao(id_work_order_task, id_motivo, nota="") -> dict:
    if not id_work_order_task or not id_motivo:
        return {"ok": False, "erro": "escolha o motivo da pausa."}
    res = _rpc_call(RPC_EXEC_PAUSE, {"page": 1, "limit": 200, "start": 0, "append": True,
                                     "id_work_order_task": id_work_order_task,
                                     "id_wo_tasks_execution_types": id_motivo,
                                     "note": (nota or "").strip()})
    if isinstance(res, dict) and res.get("success") is False:
        return {"ok": False, "erro": str(res.get("message") or "nao consegui pausar")}
    return {"ok": True, "raw": res}


def retomar_execucao(id_work_order_task) -> dict:
    res = _rpc_call(RPC_EXEC_RESUME, {"page": 1, "limit": 200, "start": 0, "append": True,
                                      "id_work_order_task": id_work_order_task})
    if isinstance(res, dict) and res.get("success") is False:
        return {"ok": False, "erro": str(res.get("message") or "nao consegui retomar")}
    return {"ok": True, "raw": res}


def finalizar_execucao(id_work_order_task) -> dict:
    """Para o cronômetro. CUIDADO com o nome do parâmetro: aqui é `id`, e nos outros três é
    `id_work_order_task` — mesmo valor, nome diferente. Está assim no fluxo do web."""
    res = _rpc_call(RPC_EXEC_FINISH, {"page": 1, "limit": 200, "start": 0, "append": True,
                                      "id": id_work_order_task, "view_stop_drawer": False})
    if isinstance(res, dict) and res.get("success") is False:
        return {"ok": False, "erro": str(res.get("message") or "nao consegui concluir")}
    return {"ok": True, "raw": res}


def execucoes_abertas(id_work_order_task) -> list:
    """Execuções da tarefa que NUNCA fecharam (`final_date` vazio). Normalmente é lista vazia."""
    try:
        ex = historico_execucao(id_work_order_task)
    except FracttalError:
        return []
    return [e for e in ex
            if not e.get("final_date") or str(e.get("final_date")).lower() == "none"]


def _dono_execucao(e: dict) -> str:
    """Nome de quem abriu a execução (para a mensagem de erro)."""
    return str(e.get("name") or e.get("personnel_description") or "").strip() or "outro usuário"


def fechar_execucoes_abertas(id_work_order_task) -> dict:
    """Fecha as execuções abertas da tarefa que são DO USUÁRIO LOGADO.
    → {'ok', 'fechadas', 'restantes', 'alheias': [...], 'erro'}.

    Caso real que trouxe esta função (OS 10215, 29/07): o Levi tentou concluir quatro vezes e a OS
    não fechava, sem erro nenhum na tela. A tarefa tinha DUAS execuções — a dele, encerrada, e uma
    da **Ana Barros** aberta desde o dia anterior (`IN_PROGRESS`, `final_date` nulo). O
    `work_orders_recalculate` roda com `verify_work_in_progress: True` e recusa fechar OS com
    trabalho em andamento.

    Dois enganos estavam somados:
    1. confiar no `wo_task_get_execution`, que devolve só a execução MAIS RECENTE — o app via a
       do próprio usuário, fechada, e achava que não havia nada rodando. Quem conta a verdade é o
       `wo_tasks_execution_list`;
    2. o `finish` NÃO encerra cronômetro dos outros: responde `USER_HAS_EXECUTION_IN_PROGRESS`.
       Cronômetro alheio só quem abriu encerra (ou alguém com permissão, pelo Fracttal web) —
       daí devolver o nome e a data em vez de insistir num comando que a API nunca vai aceitar.

    Execução pausada não aceita `finish` direto: precisa RETOMAR antes."""
    if not id_work_order_task:
        return {"ok": True, "fechadas": 0, "restantes": 0, "alheias": []}
    try:
        eu = _current_user_info()[0]
    except Exception:
        eu = None
    fechadas, erro = 0, ""
    for _ in range(4):                       # teto: nunca vimos mais de 2, mas não fica em laço
        minhas = [e for e in execucoes_abertas(id_work_order_task)
                  if eu is None or e.get("id_personnel") == eu]
        if not minhas:
            break
        try:
            retomar_execucao(id_work_order_task)          # pausada não aceita finish
        except FracttalError:
            pass
        r = finalizar_execucao(id_work_order_task)
        if isinstance(r, dict) and r.get("ok") is False:
            erro = str(r.get("erro") or "")
            break
        fechadas += 1
    restantes = execucoes_abertas(id_work_order_task)
    alheias = [e for e in restantes if eu is not None and e.get("id_personnel") != eu]
    if alheias:
        quem = "; ".join("%s (desde %s)" % (_dono_execucao(e), fmt_data_br(e.get("initial_date")))
                         for e in alheias[:3])
        erro = ("o cronômetro desta tarefa está aberto no nome de %s. O Fracttal não deixa você "
                "encerrar execução de outra pessoa — peça para quem iniciou parar, ou encerre pelo "
                "Fracttal web. Enquanto estiver aberto, a OS não fecha." % quem)
    elif restantes and not erro:
        erro = ("ainda há %d execução(ões) aberta(s) nesta tarefa — o Fracttal não fecha OS com "
                "trabalho em andamento." % len(restantes))
    return {"ok": not restantes, "fechadas": fechadas, "restantes": len(restantes),
            "alheias": alheias, "erro": erro}


LABEL_EM_EXECUCAO = "Atividade em execução"      # 3377 — é ela que põe o card em "Em processo"


def marcar_em_execucao(id_work_order, ligado: bool = True) -> dict:
    """Liga/desliga a etiqueta 'Atividade em execução' na OS.

    É a etiqueta, e não o status do Fracttal, que decide a coluna do board (`perf_spec.em_execucao`).
    MEDIDO na OS 10152: apesar do `append: True`, o `work_order_labels_sync` **substitui** o
    conjunto — então tirar a etiqueta é remandar a lista SEM ela. Por isso é preciso ler as atuais
    antes. Se sobrar lista vazia o `apply_labels` recusa (guard dele); na prática não acontece,
    porque toda OS daqui carrega a PERFORMANCE junto."""
    if not id_work_order:
        return {"ok": False, "erro": "OS sem id."}
    alvo = label_id_por_nome(LABEL_EM_EXECUCAO)
    if not alvo:
        return {"ok": False, "erro": "etiqueta '%s' não existe no Fracttal." % LABEL_EM_EXECUCAO}
    atuais = [e.get("id") for e in ((get_os_detalhes(id_work_order) or {}).get("etiquetas") or [])
              if e.get("id")]
    novas = ([i for i in atuais if i != alvo] + [alvo]) if ligado else \
            [i for i in atuais if i != alvo]
    if set(novas) == set(atuais):
        return {"ok": True, "sem_mudanca": True}
    if not novas:
        return {"ok": False, "erro": "não dá para deixar a OS sem nenhuma etiqueta."}
    return apply_labels(id_work_order, novas)


def iniciar_execucao_os(id_work_order, id_work_order_task) -> dict:
    """Dá play E marca a OS como 'Atividade em execução' — para quem usa é UM gesto: apertar o
    play tem de mover o card para a coluna 'Em processo'. A etiqueta é o efeito colateral, então
    uma falha nela NÃO invalida o cronômetro: volta em `etiqueta_erro` para a tela avisar."""
    r = iniciar_execucao(id_work_order_task)
    if r.get("ok"):
        try:
            e = marcar_em_execucao(id_work_order, True)
            if not e.get("ok"):
                r["etiqueta_erro"] = e.get("erro")
        except Exception as exc:
            r["etiqueta_erro"] = str(exc)[:200]
    return r


def finalizar_execucao_os(id_work_order, id_work_order_task) -> dict:
    """Para o cronômetro e MANTÉM o 'Atividade em execução'.

    A v111 tirava a etiqueta aqui e o card voltava para "Não iniciada" — errado, e o Levi
    corrigiu: "mesmo com a OS pausada precisa continuar como Em processo porque foi iniciada".
    Uma vez iniciada, a OS só sai de "Em processo" quando é CONCLUÍDA (`concluir_os_analise`).
    Parar o cronômetro é só encerrar o tempo de trabalho, não devolver a OS para a fila."""
    return finalizar_execucao(id_work_order_task)


LABEL_CHAMADOS = "CHAMADOS"
# A inspeção NÃO leva CHAMADOS. O fluxo que o Levi fechou em 30/07 tem TRÊS OS:
#   religamento do COS → INSPEÇÃO (esta) → OS de chamado.
# Como o painel da Singrid é montado pela etiqueta CHAMADOS, dar essa etiqueta à inspeção faria a
# OS entrar na fila dela antes de o técnico ter ido a campo. "Chamado Garantia" (id 4821) já
# existia no Fracttal e estava sem uso nenhum (0 OS) — diz "isto caminha para uma garantia" sem
# ser a fila do chamado.
LABEL_INSPECAO = "Aguardando Garantia"   # id 2036, já existia no Fracttal (Levi, 30/07)
TIPO_INSPECAO = "Inspeção"


def ultimas_os_do_ativo(id_item, limite: int = 10, com_tipo: bool = True) -> list:
    """Últimas OS daquele ativo, mais recente primeiro.
    → [{'folio','id','descricao','event_date','status','tipo_tarefa'}].

    Serve ao campo "OS pai" da inspeção: quem abre precisa lembrar qual religamento originou o
    caso, e ninguém decora número de OS.

    Filtra por `id_item` NO SERVIDOR — sondado em 30/07 e funciona (APG100-INVR1.1 → total=4).
    Varrer as OS recentes e casar o code no cliente, que foi a primeira ideia, só olharia as
    últimas dezenas do sistema inteiro: ativo com OS de meses atrás voltaria vazio."""
    if not id_item:
        return []
    try:
        res = _rpc_call(RPC_WO_LIST, {"page": 1, "limit": max(1, int(limite)), "start": 0,
                                      "append": True,
                                      "sort": [{"property": "id", "direction": "desc"}],
                                      "filter": [{"operator": "=", "property": "id_item",
                                                  "value": id_item}]})
    except FracttalError:
        return []
    out = []
    for w in ((res.get("data") or []) if isinstance(res, dict) else []):
        d = _shape_wo_row(w)
        out.append({"folio": d.get("folio"), "id": d.get("id"), "descricao": d.get("descricao"),
                    "event_date": d.get("event_date") or d.get("data"), "status": d.get("status"),
                    "tipo_tarefa": ""})
    out = out[:limite]
    if com_tipo and out:
        # o tipo de tarefa não vem na listagem (só no nível tarefa). São ≤10 ids: uma chamada só.
        meta = _meta_tarefa_por_os([d["id"] for d in out])
        for d in out:
            d["tipo_tarefa"] = (meta.get(d["id"], {}) or {}).get("tipo_tarefa", "")
    return out


def respostas_inspecao(id_work_order) -> dict:
    """Respostas do técnico na OS de inspeção, indexadas pela CHAVE do `chamado_spec`.

    É o que faz o diálogo "Abrir chamado" nascer preenchido: a Singrid deixa de garimpar serial e
    sintoma na OS. Casa pela DESCRIÇÃO da subtarefa, que é o único elo entre o form item gravado no
    Fracttal e o modelo do `chamado_insp_spec` — o Fracttal não guarda a chave.
    → {chave: resposta} só com o que foi respondido."""
    import chamado_insp_spec as ci
    porc = {}
    for bloco in [ci.BASE] + list(ci.POR_TIPO.values()) + list(ci.POR_FABRICANTE.values()):
        for s in bloco:
            if s.get("chave"):
                porc[s["desc"].strip().lower()] = s["chave"]
    try:
        rf = _rpc_call(RPC_WO_FORMIT, {"id_work_order": id_work_order})
    except FracttalError:
        return {}
    out = {}
    for it in ((rf.get("data") or []) if isinstance(rf, dict) else []):
        ch = porc.get(str(it.get("description") or "").strip().lower())
        if not ch:
            continue
        v = _form_item_resposta(it)
        if v:
            out[ch] = v
    # o que o app SABE, sem ter perguntado ao técnico: data da falha, nº de unidades e o
    # "menos de 7 dias". Recalculado AGORA, não na criação da OS — a Singrid abre o chamado dias
    # depois e a resposta muda (pedido do Levi, 30/07).
    try:
        det = get_os_detalhes(id_work_order) or {}
        tipo_ativo = ""
        code = det.get("code") or ""
        if code:
            for a in load_assets_cached():
                if a.get("code") == code:
                    tipo_ativo = a.get("tipo") or ""
                    break
        for k, v in ci.derivados(tipo_ativo, det.get("event_date")).items():
            out.setdefault(k, v)
    except Exception:
        pass                       # derivado é bônus; nunca impede o chamado de abrir
    return out


_CLASSIF_CACHE = {}


def _classif_ids(nome_c1: str, nome_c2: str) -> dict:
    """{'id_task_type','tasks_types_description','id_task_type_2','tasks_types_2_description'} a
    partir dos NOMES. Resolve no catálogo do Fracttal (editável lá dentro, então id fixo quebraria).
    Nome que não existir simplesmente não entra — melhor OS sem classificação que com a errada."""
    global _CLASSIF_CACHE
    if not _CLASSIF_CACHE:
        try:
            _CLASSIF_CACHE = get_tipos_classif() or {}
        except Exception:
            return {}
    out = {}
    for chave, nome, campo_id, campo_desc in (
            ("c1", nome_c1, "id_task_type", "tasks_types_description"),
            ("c2", nome_c2, "id_task_type_2", "tasks_types_2_description")):
        alvo = str(nome or "").strip().lower()
        for x in (_CLASSIF_CACHE.get(chave) or []):
            if str(x.get("description") or "").strip().lower() == alvo:
                out[campo_id] = x.get("id")
                out[campo_desc] = str(x.get("description") or "")
                break
    return out


def create_inspecao_chamado(asset: dict, fabricante: str, id_responsible=None,
                            responsible_name: str = "", event_date: datetime = None,
                            prog_date: datetime = None, id_parent=None, note: str = "",
                            etiquetas=None) -> dict:
    """Cria a OS de INSPEÇÃO que alimenta um chamado de garantia.

    As subtarefas vêm do `chamado_insp_spec` (base + tipo do ativo + marca) e vão no PRÓPRIO
    payload — não existe plano cadastrado no Fracttal para isso, e nem precisa: o
    `tasks_noscheduled_react_insert` aceita a lista de subtarefas direto (é o mesmo caminho do
    tracker individual, `linkar_plano=False`).

    `event_date` = data do incidente (herdada da OS pai quando houver, decisão do Levi 29/07);
    `prog_date` = quando o técnico vai a campo. `etiquetas` = nomes; default = LABEL_INSPECAO.
    → {'id_work_order','wo_folio','n_subtarefas','etiqueta_erro'}."""
    import chamado_insp_spec as ci
    tipo_ativo = str(asset.get("tipo") or "").strip()
    subs = ci.subtarefas(tipo_ativo, fabricante)
    if not subs:
        raise FracttalError("Não há modelo de inspeção para %s / %s." % (tipo_ativo or "?",
                                                                         fabricante or "?"))
    desc = ci.titulo(asset, fabricante) if hasattr(ci, "titulo") else (
        "[%s] - Inspeção para chamado %s"
        % ((str(asset.get("description") or "").split("{")[0]).strip()[:60] or asset.get("code"),
           fabricante))
    # `plan` sintético. Dois cuidados: (1) o `create_planned_os` repassa `subtasks` CRU para o RPC,
    # então a lista tem de vir já no formato dele — daí o `_rpc_subtasks`, que é quem põe id,
    # order_number e phantom; (2) sem `id_task_type_main` a OS nasce sem tipo de tarefa, e a visão
    # COS e os filtros do histórico passam a não enxergá-la.
    plano = {"id_task": None, "subtasks": _rpc_subtasks(subs), "description": desc,
             "tasks_types_main_description": TIPO_INSPECAO,
             "id_task_type_main": TASK_TYPE_MAIN.get(TIPO_INSPECAO)}
    # CLASSIFICAÇÃO Programada / Elétrica (Levi, 30/07). Sem isto a OS nascia com a classificação
    # em branco — verificado na OS 10478. Os ids são resolvidos pelo nome no catálogo do Fracttal,
    # e não fixos, porque a lista é editável lá dentro.
    _cls = _classif_ids(ci.CLASSIF_1, ci.CLASSIF_2)
    plano.update(_cls)
    r = create_planned_os(asset, plano, id_responsible=id_responsible,
                          responsible_name=responsible_name, event_date=event_date,
                          prog_date=prog_date, id_parent=id_parent, descricao=desc,
                          note=note, linkar_plano=False)
    idwo = r.get("id_work_order")
    erro_lbl = ""
    nomes = list(etiquetas) if etiquetas else [LABEL_INSPECAO]
    ids = [i for i in (label_id_por_nome(n) for n in nomes) if i]
    if idwo and ids:
        try:
            apply_labels(idwo, ids)
        except Exception as exc:                 # a OS já existe; a etiqueta é o que pode faltar
            erro_lbl = str(exc)[:200]
    return {"id_work_order": idwo, "wo_folio": r.get("wo_folio"),
            "id_work_order_task": r.get("id_work_order_task"),
            "n_subtarefas": len(subs), "etiqueta_erro": erro_lbl}


def concluir_os_analise(id_work_order, id_work_order_task=None, observacao: str = "") -> dict:
    """FECHA a OS de análise — IRREVERSÍVEL. Encerra o cronômetro (se estiver rodando), tira o
    'Atividade em execução' e conclui.

    `observacao` NÃO vai para a observação da OS: a API do Fracttal não tem método de edição de
    OS já criada (só criar/cancelar/mudar status/etiqueta/anexo). Vai para o log local, do mesmo
    jeito que o histórico de chamados — ver `chamado_log`. No dia em que houver método de escrita,
    é aqui que ele entra."""
    if not id_work_order:
        return {"ok": False, "erro": "OS sem id."}
    # 1) o cronômetro tem de estar TODO fechado. Não basta um `finalizar_execucao`: execução de
    #    outro dia que ficou pausada continua aberta e o Fracttal recusa fechar a OS (ver
    #    `fechar_execucoes_abertas`). E o erro daqui NÃO é mais engolido — era ele que fazia a
    #    conclusão falhar em silêncio, com o app dizendo que tinha dado certo.
    tid = None
    try:
        tid = id_work_order_task or id_tarefa_da_os(id_work_order)
    except Exception:
        tid = None
    if tid:
        try:
            fx = fechar_execucoes_abertas(tid)
        except Exception as exc:
            return {"ok": False, "erro": "não consegui encerrar o cronômetro: %s" % str(exc)[:200]}
        if not fx.get("ok"):
            return {"ok": False, "erro": fx.get("erro") or "cronômetro ainda aberto."}
    try:
        marcar_em_execucao(id_work_order, False)
    except Exception:
        pass                               # a etiqueta é cosmética; o que importa é fechar a OS
    try:
        concluir_os(id_work_order)
    except Exception as exc:
        return {"ok": False, "erro": str(exc)[:300]}
    # 2) confere no servidor: o `recalculate` já respondeu sucesso com a OS seguindo aberta.
    #    Sem esta releitura o app diz "concluída" e o card some — mas a OS continua lá.
    try:
        st = status_da_os(id_work_order)
        if st is not None and st not in STATUS_FECHADOS:
            return {"ok": False, "erro": "o Fracttal aceitou o comando mas a OS continua como '%s'. "
                                         "Verifique no Fracttal se falta subtarefa obrigatória ou "
                                         "permissão para fechar." % WO_STATUS.get(st, st)}
    except Exception:
        pass                               # falha na conferência não invalida a conclusão
    # 3) e a tarefa ficou com data de fim? Aqui o cronômetro costuma ter preenchido — mas OS de
    #    análise atribuída a outra pessoa, ou fechada sem nunca ter sido iniciada, cai no mesmo
    #    buraco da 10509. Vai como AVISO no resultado: a OS está fechada, não dá para desfazer.
    return {"ok": True, "data_fim": checar_data_fim(id_work_order)}


def historico_execucao(id_work_order_task) -> list:
    """Todas as execuções da tarefa (mais recente primeiro) — daqui sai o tempo REAL de trabalho,
    já descontando as pausas."""
    res = _rpc_call(RPC_EXEC_LIST, {"sort": [{"property": "initial_date", "direction": "desc"},
                                             {"property": "id", "direction": "desc"}],
                                    "page": 1, "limit": 200, "start": 0, "is_tree": False,
                                    "node": None, "id_work_order_task": id_work_order_task})
    d = res.get("data") if isinstance(res, dict) else res
    return d if isinstance(d, list) else []


def tempo_trabalhado(id_work_order_task):
    """Segundos EFETIVAMENTE trabalhados na tarefa, somando todas as execuções. None quando a
    tarefa nunca foi cronometrada.

    Usa o `total_active_seconds` que o PRÓPRIO Fracttal calcula por execução — conferido contra
    uma execução real (tarefa 55869196): 27 s, idêntico à soma dos segmentos IN_PROGRESS
    (5 + 22), com os 3 s de pausa de fora.

    É a métrica que substitui "data de fim menos data de criação", que contava noite, fim de
    semana e tempo de espera como trabalho."""
    if not id_work_order_task:
        return None
    try:
        h = historico_execucao(id_work_order_task)
    except FracttalError:
        return None
    if not h:
        return None
    total = 0
    achou = False
    for e in h:
        if not isinstance(e, dict):
            continue
        v = e.get("total_active_seconds")
        if v is None:                       # execução antiga sem o campo: soma os segmentos
            v = sum((a.get("duration_seconds") or 0)
                    for a in (e.get("actions") or []) if isinstance(a, dict)
                    and a.get("action_type") == ACAO_RODANDO)
        total += int(v or 0)
        achou = True
    return total if achou else None


def tempo_trabalhado_em_massa(ids_work_order, max_workers=8) -> dict:
    """{id_work_order: segundos_trabalhados | None} em paralelo.

    Duas chamadas por OS (achar a tarefa + ler o histórico), então nunca use isto no quadro
    inteiro — só na tela de UMA pessoa, onde são poucas OS."""
    from concurrent.futures import ThreadPoolExecutor
    ids = [i for i in (ids_work_order or []) if i]
    if not ids:
        return {}

    def _um(wid):
        try:
            return wid, tempo_trabalhado(id_tarefa_da_os(wid))
        except Exception:
            return wid, None

    out = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(ids))) as ex:
        for wid, seg in ex.map(_um, ids):
            out[wid] = seg
    return out
