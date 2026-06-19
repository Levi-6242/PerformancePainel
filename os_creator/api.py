"""api.py — acesso à API REST do Fracttal One.

Autenticação: OAuth2 client_credentials (FRACTTAL_CLIENT_ID/SECRET) — mesmo método do
dashboard. Alternativamente, um token Bearer direto via FRACTTAL_TOKEN (expira ~1h).

⚠️ CONTRATO DE CRIAÇÃO: o payload de criação de work_orders (OS) + subtarefas + atribuição
de responsável NÃO é documentado publicamente. As funções create_work_order / assign_and_start
abaixo são o MELHOR ESFORÇO a partir da estrutura observada na API. Em caso de erro, a mensagem
exata da API é propagada (FracttalError) para ajuste fino — e os IDs de config (tipos de tarefa,
prioridade, status) ficam centralizados em CONFIG logo abaixo, fáceis de corrigir.
"""
import os
import json
import time
import threading
import requests
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

BASE          = os.environ.get("FRACTTAL_BASE_URL", "https://app.fracttal.com").rstrip("/")
CLIENT_ID     = os.environ.get("FRACTTAL_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("FRACTTAL_CLIENT_SECRET", "").strip()
STATIC_TOKEN  = os.environ.get("FRACTTAL_TOKEN", "").strip()

# ── Config do Fracttal (AJUSTAR conforme a conta — ver comentários) ───────────
# Responsáveis permitidos no Step 4 (filtro por nome no /api/personnel).
RESPONSAVEIS = ["Roger Lélis", "Gabriela Dias", "Ana Patrícia", "Levi Maia"]

# Tipo de tarefa escolhido no Step 2 → id_task_type do Fracttal.
# Descobrir os ids reais: GET /api/tasks/ (campo id_task_type) ou inspecionando uma OS
# existente de cada tipo. Enquanto None, a OS é criada SEM tipo (a API pode exigir → ajustar).
TASK_TYPE_IDS = {"Corretiva": None, "Inspeção": None}

# Criticidade fixa "Alta" → id_priorities. Na API: 1=VERY_HIGH, 2=HIGH (típico). "Alta" = 2.
PRIORITY_ALTA = 2

# Status "Em Processo" → id_status_work_order (ajustar: nas OS vistas, 3 aparece como concluída).
STATUS_EM_PROCESSO = 2

# Grupo fixo das subtarefas.
SUBTASK_GROUP = "Diagnóstico Inicial"


class FracttalError(Exception):
    """Erro de API com mensagem amigável (já tratada) para exibir na UI."""


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
                    "cliente": cliente, "usina": usina, "tipo_code": tipo_code, "tipo": tipo,
                    "label": f"{code} — {desc}" if code else desc})
    out.sort(key=lambda x: (x["cliente"].lower(), x["usina"].lower(), x["code"].lower()))
    return out


def _fetch_page(start: int, limit: int = 99) -> list:
    return _req("GET", f"items/?limit={limit}&start={start}", timeout=40).get("data", []) or []


def get_assets() -> list:
    """TODOS os ativos (16k+). 1ª página dá o total; as demais em paralelo (a paginação
    capa ~100/página e não há filtro server-side). Cada registro recebe cliente/usina/tipo
    derivados (parent_description + code) p/ o drill-down. Ordenado por cliente+usina+code."""
    first = _req("GET", "items/?limit=99&start=0", timeout=40)
    total = int(first.get("total") or 0)
    data = list(first.get("data", []) or [])
    starts = list(range(99, total, 99))
    if starts:
        res = {}
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = {ex.submit(_fetch_page, s): s for s in starts}
            for f in as_completed(futs):
                res[futs[f]] = f.result()
        for s in starts:
            data.extend(res.get(s, []))
    return _build_records(data)


# Cache em disco — evita recarregar 16k ativos a cada abertura do app.
ASSETS_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets_cache.json")
ASSETS_TTL   = 24 * 3600


def load_assets_cached(force: bool = False) -> list:
    """Ativos do cache (se < 24h) ou recarrega tudo e salva. force=True ignora o cache."""
    if not force:
        try:
            with open(ASSETS_CACHE, encoding="utf-8") as f:
                c = json.load(f)
            if c.get("assets") and (time.time() - c.get("ts", 0)) < ASSETS_TTL:
                return c["assets"]
        except Exception:
            pass
    assets = get_assets()
    try:
        with open(ASSETS_CACHE, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "assets": assets}, f, ensure_ascii=False)
    except Exception:
        pass
    return assets


def get_responsaveis() -> list:
    """Pessoal filtrado aos nomes de RESPONSAVEIS (match client-side — o ?search da API
    não filtra de forma confiável). → [{'code','name'}] na ordem de RESPONSAVEIS."""
    allp, start, limit = [], 0, 100
    while True:
        j = _req("GET", f"personnel/?limit={limit}&start={start}", timeout=30)
        data = j.get("data", []) or []
        allp.extend(data)
        total = int(j.get("total") or 0)
        start += limit
        if not data or start >= total:
            break
    out = []
    for nome in RESPONSAVEIS:
        for p in allp:
            full = (p.get("full_name") or p.get("name") or "").strip()
            if full and nome.lower() in full.lower():
                out.append({"code": p.get("code"), "name": full})
                break
    return out


# ── Escrita (MELHOR ESFORÇO — ver aviso no topo do arquivo) ───────────────────
def create_work_order(asset_code: str, description: str, task_type: str,
                      subtasks: list, etiqueta: str = "", responsible_code: str = "") -> dict:
    """Cria uma OS (work order) ad-hoc + subtarefas. Retorna {'id_work_order','wo_folio'}.
    Datas automáticas (como o Fracttal faz): incidente = hoje 00:00; manutenção = agora + 15 min
    (garante 'data futura'), no fuso local. responsible_code é OBRIGATÓRIO na criação (a API exige
    responsible_code ou third_party_code). Payload best-effort — em erro, a mensagem da API é
    propagada para ajuste."""
    now = datetime.now().astimezone()
    incidente  = now.replace(hour=0, minute=0, second=0, microsecond=0)
    manutencao = now + timedelta(minutes=15)
    payload = {
        "code":            asset_code,          # ativo (code do /api/items)
        "description":     description.strip(),
        "id_priorities":   PRIORITY_ALTA,       # criticidade Alta (fixo)
        "date_incident":   incidente.isoformat(),
        "date_maintenance": manutencao.isoformat(),
        "send_to_pending": True,                # "Enviar para tarefas pendentes"
        "creation_mode":   "single",            # tudo em uma OS
        "depends_on_wo":   False,
        "depends_on_budget": False,
    }
    if responsible_code:
        payload["responsible_code"] = responsible_code   # responsável (exigido na criação)
    if etiqueta.strip():
        payload["key_words"] = etiqueta.strip()          # etiqueta — best-effort (ajustar se recusar)
    tid = TASK_TYPE_IDS.get(task_type)
    if tid is not None:
        payload["id_task_type"] = tid
    else:
        payload["tasks_types_description"] = task_type   # fallback por nome
    # subtarefas (mínimo 1): ordem sequencial, tipo Texto, grupo fixo, obrigatórias
    payload["subtasks"] = [
        {"order": i + 1, "description": (st or "").strip(), "type": "Texto",
         "group": SUBTASK_GROUP, "required": True}
        for i, st in enumerate(subtasks) if (st or "").strip()
    ]
    j = _req("POST", "work_orders/", json=payload, timeout=45)
    data = j.get("data")
    rec  = data[0] if isinstance(data, list) and data else (data or j)
    rec  = rec if isinstance(rec, dict) else {}
    return {"id_work_order": rec.get("id_work_order") or rec.get("id"),
            "wo_folio":       rec.get("wo_folio") or rec.get("folio")}


def create_work_orders_bulk(asset_codes: list, description: str, task_type: str,
                            subtasks: list, etiqueta: str = "", responsible_code: str = "") -> list:
    """Cria N OS idênticas (uma por ativo) já com o responsável e move cada uma p/ 'Em Processo'
    (best-effort). NÃO interrompe no 1º erro — retorna o status de cada:
    → [{'code','ok':True,'os':{...}} | {'code','ok':False,'erro':str}]."""
    out = []
    for code in asset_codes:
        try:
            os = create_work_order(code, description, task_type, subtasks, etiqueta, responsible_code)
            if os.get("id_work_order") and responsible_code:
                try:
                    assign_and_start(os["id_work_order"], responsible_code)   # → Em Processo (best-effort)
                except FracttalError:
                    pass
            out.append({"code": code, "ok": True, "os": os})
        except FracttalError as e:
            out.append({"code": code, "ok": False, "erro": str(e)})
    return out


def assign_and_start(id_work_order, person_code: str):
    """Atribui o responsável (person_code = code do pessoal) e move a OS para 'Em Processo'.
    Best-effort via PUT /api/work_orders/{id}."""
    if not id_work_order:
        raise FracttalError("OS sem id — não dá para atribuir responsável.")
    _req("PUT", f"work_orders/{id_work_order}", json={
        "user_code":             person_code,
        "id_status_work_order":  STATUS_EM_PROCESSO,
    }, timeout=30)
    return True


def assign_and_start_bulk(os_list: list, person_code: str) -> list:
    """Atribui o responsável e move p/ 'Em Processo' em TODAS as OS. → lista de erros (vazia = ok)."""
    errs = []
    for o in os_list:
        ref = o.get("wo_folio") or o.get("id_work_order")
        try:
            assign_and_start(o.get("id_work_order"), person_code)
        except FracttalError as e:
            errs.append(f"OS {ref}: {e}")
    return errs
