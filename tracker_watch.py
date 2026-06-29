# -*- coding: utf-8 -*-
"""
tracker_watch.py — Rastreador persistente de anomalias de trackers.
Fontes: SunOp API (plantas GD) + PostgreSQL/powerplants (usinas Thopen).

Uso:
  python tracker_watch.py              # atualiza o JSON (ambas as fontes) e imprime resumo
  python tracker_watch.py --resolve "Boa Esperança do Sul 1" "Tracker 01" "NCU reposta"
  python tracker_watch.py --note     CPP100 TRK_5 "Aguardando peça" --os ATHN-001234
  python tracker_watch.py --add      CPP100 TRK_5 parado "Mecânico emperrado"
  python tracker_watch.py --list
  python tracker_watch.py --fonte pg      # só PostgreSQL
  python tracker_watch.py --fonte sunop   # só SunOp
"""

import json
import os
import sys
import time
import argparse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

try:
    import psycopg2
except ImportError:
    psycopg2 = None

# Fix encoding no terminal Windows
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    try:
        _sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ── Caminhos ─────────────────────────────────────────────────────────────────
_HERE       = os.path.dirname(os.path.abspath(__file__))
ISSUES_PATH = os.path.join(_HERE, "tracker_issues.json")

# Credenciais ficam fora do código: .env na raiz do projeto (ver .env.example)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_HERE, ".env"))
except ImportError:
    pass

# ── SunOp ────────────────────────────────────────────────────────────────────
SUNOP_CONFIG = "https://gridco-api.sunop.net/api"
SUNOP_DATA   = "https://gridco-api.sunop.net/data"
SUNOP_TOKEN  = os.environ.get("SUNOP_TOKEN", "")
_token_cache = {"token": SUNOP_TOKEN, "ok": False}

# ── Limiares ─────────────────────────────────────────────────────────────────
TRK_SEVERO      = 10.0   # ° |alvo - atual| → severo
TRK_LEVE        = 5.0    # ° |alvo - atual| → leve
TRK_FORA_MEDIA  = 3.0    # ° |atual - média_grupo| → fora_media
TRK_PARADO_STRD = 2.0    # ° STRD_DEV abaixo disto = candidato a parado
TRK_PARADO_REF  = 10.0   # ° mediana STRD_DEV da planta deve superar isso p/ flagrar "parado"
TRK_SEM_DADOS_AGRUPAR = 5  # ≥ N trackers "sem dados" na mesma planta → 1 issue agregado

TIPO_LABEL = {
    "severo":      "Atraso Severo (>10°)",
    "leve":        "Atraso Leve (5°–10°)",
    "fora_media":  "Fora da Média",
    "parado":      "Parado",
    "sem_dados":   "Sem Dados",
}

# ── Nomes de exibição ─────────────────────────────────────────────────────────
USINA_DISPLAY = {
    "SMP100": "Santa Maria do Pará",
    "CPP100": "Capitão Poço",
    "TIM100": "Timon 1",
    "TIM200": "Timon 2",
    "MRO100": "Mãe do Rio",
    "MTS100": "Matões 1",
    "MTS200": "Matões 2",
    "MAB100": "Marabá 1",
    "MAB200": "Marabá 2",
    "JCD100": "Jacundá",
}


# ── PostgreSQL ───────────────────────────────────────────────────────────────
PG_HOST = os.environ.get("PG_HOST", "")
PG_PORT = int(os.environ.get("PG_PORT", "5432"))
PG_DB   = os.environ.get("PG_DB",   "powerplants")
PG_USER = os.environ.get("PG_USER", "")

def _pg_password() -> str:
    if pw := os.environ.get("PG_PASSWORD", ""):
        return pw
    try:
        path = os.path.join(_HERE, "pg_password.txt")
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""

def _pg_conn():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 não instalado")
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB,
        user=PG_USER, password=_pg_password(), connect_timeout=10
    )

# Mapeamento status PG → tipo interno
_PG_STATUS_MAP = {
    "falha de comunicação": "falha_com",
    "modo manual":          "manual",
    "out_of_range":         "fora_range",
    "tracker em curso":     "ok",    # normal — em movimento
    "modo automático":      "ok",
    "modo automático e sleep": "ok",
}

def _analyze_pg() -> list[dict]:
    """
    Consulta dbt.int_tracker_latest_readings no PostgreSQL.
    Retorna lista de trackers anômalos:
      [{plant_id, usina, tracker, device_id, tipo, tipo_label, posat, posal, deviation, status_label, timestamp}, ...]
    """
    anomalos = []
    try:
        conn = _pg_conn()
        cur  = conn.cursor()
        cur.execute("""
            SELECT
                p.id            AS plant_id,
                p.name          AS usina,
                d.device_name   AS tracker,
                t.device_id,
                t.timestamp,
                t.posat,
                t.posal,
                t.deviation,
                t.status,
                t.status_label,
                t.flh_com,
                t.out_of_range,
                t.modo,
                t.auto_on,
                t.manu_on
            FROM dbt.int_tracker_latest_readings t
            JOIN public.tb_power_plants p ON p.id = t.power_plant_id
            JOIN public.tb_devices       d ON d.id = t.device_id
            WHERE
                -- Falha de comunicação individual
                lower(t.status_label) LIKE '%falha%'
                -- Modo manual (inesperado)
                OR lower(t.status_label) LIKE '%manual%'
                -- Out of range
                OR t.out_of_range = 1
            ORDER BY p.name, d.device_name
        """)
        rows = cur.fetchall()
        conn.close()

        for row in rows:
            (plant_id, usina, tracker, device_id, ts,
             posat, posal, deviation,
             status, status_label,
             flh_com, out_of_range, modo, auto_on, manu_on) = row

            sl = (status_label or "").lower()
            if "manual" in sl:
                tipo = "manual"
                tipo_label = "Modo Manual"
            elif "falha" in sl:
                tipo = "falha_com"
                tipo_label = "Falha de Comunicação"
            elif out_of_range:
                tipo = "fora_range"
                tipo_label = "Fora do Range"
            else:
                continue  # não anômalo

            anomalos.append({
                "plant_id":    str(plant_id),
                "usina":       usina,
                "tracker":     tracker,
                "device_id":   device_id,
                "tipo":        tipo,
                "tipo_label":  tipo_label,
                "posat":       round(float(posat), 2)      if posat      is not None else None,
                "posal":       round(float(posal), 2)      if posal      is not None else None,
                "deviation":   round(float(deviation), 3)  if deviation  is not None else None,
                "status_label": status_label,
                "timestamp":   ts.isoformat() if ts else None,
                "fonte":       "pg",
            })
    except Exception as e:
        print(f"  [ERRO PG] {e}")
    return anomalos


# ── Auth SunOp ────────────────────────────────────────────────────────────────
def _sunop_token() -> str:
    if _token_cache["ok"]:
        return _token_cache["token"]
    tok = _token_cache["token"]
    H = {"Authorization": f"JWT {tok}", "Content-Type": "application/json"}
    try:
        if requests.get(f"{SUNOP_CONFIG}/check_token", headers=H, timeout=8).status_code == 200:
            _token_cache["ok"] = True
            return tok
    except Exception:
        pass
    try:
        r = requests.get(f"{SUNOP_CONFIG}/refresh_token", headers=H, timeout=10)
        if r.status_code == 200:
            new = r.json()
            if isinstance(new, str):
                new = new.strip('"')
            _token_cache["token"] = new
            _token_cache["ok"] = True
            return new
    except Exception:
        pass
    _token_cache["ok"] = True  # usa o que tem mesmo
    return tok


def _hdrs():
    return {"Authorization": f"JWT {_sunop_token()}", "Content-Type": "application/json"}


# ── Metadata das plantas ──────────────────────────────────────────────────────
def _get_plants() -> list[str]:
    """Lista de plantas disponíveis no SunOp."""
    try:
        r = requests.get(f"{SUNOP_CONFIG}/plants", headers=_hdrs(), timeout=15)
        return [p["name"] for p in r.json()] if r.status_code == 200 else []
    except Exception:
        return []


def _get_meta(plant: str) -> dict:
    """Pathnames de trackers de uma planta: {TRK_N: {alvo, atual, desvio}}"""
    try:
        r = requests.get(f"{SUNOP_DATA}/v2/metadata",
                         headers=_hdrs(),
                         params={"plant": plant, "size": 6000},
                         timeout=20)
        if r.status_code != 200:
            return {}
    except Exception:
        return {}

    _ETM_MEDIDA = {"POA.IRAD": "poa", "GHI.IRAD": "ghi", "POA_R.IRAD": "poari"}
    _TRK_MEDIDA = {"MEDIDAS.POSAL": "alvo", "MEDIDAS.POSAT": "atual",
                   "MEDIDAS.STRD_DEV": "strd"}
    # A API devolve {"data": [...]}; cair p/ lista direta por robustez
    try:
        payload = r.json()
        items = payload.get("data", []) if isinstance(payload, dict) else payload
    except Exception:
        return {}
    trackers = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        path = item.get("pathname") or item.get("name") or ""
        if not path.startswith(plant + "."):
            continue
        rest  = path[len(plant) + 1:]
        parts = rest.split(".")
        if len(parts) < 3:
            continue
        sub = parts[0]
        if sub.startswith("TRK_"):
            medida = _TRK_MEDIDA.get(".".join(parts[1:]))
            if medida:
                trackers.setdefault(sub, {})[medida] = path
    return trackers


# ── Leitura instantânea ───────────────────────────────────────────────────────
def _last_values(pathnames: list[str]) -> dict[str, float | None]:
    """POST /v2/last_values → {pathname: valor}"""
    out = {p: None for p in pathnames}
    if not pathnames:
        return out
    BATCH = 500
    for i in range(0, len(pathnames), BATCH):
        chunk = pathnames[i:i + BATCH]
        try:
            r = requests.post(
                f"{SUNOP_DATA}/v2/last_values",
                headers=_hdrs(),
                json={"pathnames": chunk},
                timeout=20,
            )
            if r.status_code == 200:
                for entry in r.json():
                    p = entry.get("pathname") or entry.get("name") or ""
                    v = entry.get("value")
                    if p in out and v is not None:
                        try:
                            out[p] = float(v)
                        except (TypeError, ValueError):
                            pass
        except Exception:
            pass
    return out


# ── Detecção de anomalias ─────────────────────────────────────────────────────
def _analyze_plant(plant: str) -> list[dict]:
    """
    Retorna lista de trackers anômalos:
    [{tracker, tipo, alvo, atual, disparidade, strd}, ...]
    Trackers OK não aparecem na lista.
    """
    meta = _get_meta(plant)
    if not meta:
        return []

    # Coletar todos os pathnames
    paths = []
    for trk_paths in meta.values():
        paths.extend(trk_paths.values())
    vals = _last_values(paths)

    # Montar lista raw
    raw = []
    for name in sorted(meta.keys(), key=lambda n: int(n.split("_")[1]) if n.split("_")[1].isdigit() else 999):
        tp = meta[name]
        alvo  = vals.get(tp.get("alvo"))   # POSAL
        atual = vals.get(tp.get("atual"))  # POSAT
        strd  = vals.get(tp.get("strd"))   # STRD_DEV
        raw.append({"name": name, "alvo": alvo, "atual": atual, "strd": strd})

    if not raw:
        return []

    # Média por grupo de mesmo alvo (para detectar "fora_media")
    grupos: dict[float, list[float]] = {}
    for r in raw:
        if r["alvo"] is not None and r["atual"] is not None:
            gk = round(r["alvo"], 1)
            grupos.setdefault(gk, []).append(r["atual"])
    media_grupo = {gk: sum(v) / len(v) for gk, v in grupos.items()}

    # Mediana de STRD_DEV para detecção de "parado"
    strds = [r["strd"] for r in raw if r["strd"] is not None]
    strd_ref = sorted(strds)[len(strds) // 2] if strds else 0.0

    anomalos = []
    for r in raw:
        alvo, atual, strd = r["alvo"], r["atual"], r["strd"]

        if atual is None and alvo is None:
            tipo = "sem_dados"
        else:
            disp = abs(alvo - atual) if (alvo is not None and atual is not None) else None
            gk   = round(alvo, 1) if alvo is not None else None

            if strd is not None and strd < TRK_PARADO_STRD and strd_ref > TRK_PARADO_REF:
                tipo = "parado"
            elif disp is not None and disp > TRK_SEVERO:
                tipo = "severo"
            elif disp is not None and disp > TRK_LEVE:
                tipo = "leve"
            elif (gk in media_grupo and atual is not None
                  and abs(atual - media_grupo[gk]) > TRK_FORA_MEDIA):
                tipo = "fora_media"
            else:
                tipo = "ok"

        if tipo != "ok":
            disp = abs(alvo - atual) if (alvo is not None and atual is not None) else None
            anomalos.append({
                "tracker":     r["name"],
                "tipo":        tipo,
                "alvo":        round(alvo, 2)  if alvo  is not None else None,
                "atual":       round(atual, 2) if atual is not None else None,
                "disparidade": round(disp, 2)  if disp  is not None else None,
                "strd":        round(strd, 2)  if strd  is not None else None,
            })
    return anomalos


# ── Gerenciamento do JSON ─────────────────────────────────────────────────────
def _load_issues() -> dict:
    if os.path.exists(ISSUES_PATH):
        try:
            with open(ISSUES_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"ultima_atualizacao": None, "active": {}, "history": []}


def _save_issues(data: dict):
    with open(ISSUES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def _issue_key(plant: str, tracker: str) -> str:
    return f"{plant}|{tracker}"


def _dias_aberto(data_deteccao: str) -> int:
    try:
        d = datetime.fromisoformat(data_deteccao)
        return max(0, (datetime.now() - d).days)
    except Exception:
        return 0


# ── Escalada p/ sugestão de OS (Nível 2) ──────────────────────────────────────
# Reset (operacional) NÃO abre OS. Só vira SUGESTÃO de OS o tracker que: ficou parado tempo
# demais (provável falha mecânica/elétrica), OU recorre (reset não está resolvendo).
ESCALA_HORAS       = 36   # h aberto sem voltar → sugere OS
ESCALA_RECORR      = 3    # nº de ocorrências (incl. a atual) em ESCALA_RECORR_DIAS → sugere OS
ESCALA_RECORR_DIAS = 30


def _horas_aberto(data_deteccao: str) -> float:
    try:
        d = datetime.fromisoformat(data_deteccao)
        return max(0.0, (datetime.now() - d).total_seconds() / 3600.0)
    except Exception:
        return 0.0


def _recorrencias(history: list, key: str, dias: int = ESCALA_RECORR_DIAS) -> int:
    """Quantas ocorrências PASSADAS (resolvidas) deste plant|tracker nos últimos `dias`."""
    cutoff = datetime.now() - timedelta(days=dias)
    n = 0
    for h in (history or []):
        if _issue_key(h.get("plant_id", ""), h.get("tracker", "")) != key:
            continue
        ts = h.get("data_resolucao") or h.get("data_deteccao") or ""
        try:
            if datetime.fromisoformat(ts) >= cutoff:
                n += 1
        except Exception:
            pass
    return n


def _avalia_escalada(issue: dict, key: str, history: list) -> dict:
    """Decide se a issue ativa vira SUGESTÃO de OS (Nível 2) + o motivo. Calculado na leitura
    (depende do tempo). Não persiste nada."""
    horas = _horas_aberto(issue.get("data_deteccao", ""))
    passadas = _recorrencias(history, key)
    total = passadas + 1                               # + a ocorrência atual
    motivos = []
    if horas > ESCALA_HORAS:
        motivos.append(f"parado há {int(horas)}h")
    if total >= ESCALA_RECORR:
        motivos.append(f"{total}ª vez em {ESCALA_RECORR_DIAS}d")
    return {"horas_aberto": round(horas, 1), "recorrencias_30d": passadas,
            "sugerir_os": bool(motivos), "motivo_os": " · ".join(motivos)}


# ── Atualização principal ─────────────────────────────────────────────────────
def atualizar(verbose: bool = True, fonte: str = "ambas") -> dict:
    """
    Polling SunOp e/ou PostgreSQL → atualiza tracker_issues.json.
    fonte: "sunop" | "pg" | "ambas"
    Retorna dict com contadores: novos, confirmados, resolvidos.
    """
    agora = datetime.now().isoformat(timespec="minutes")
    data    = _load_issues()
    active  = data["active"]
    history = data["history"]

    # ── Coleta todos os anômalos das fontes solicitadas ───────────────────────
    anomalas_agora: dict[str, dict] = {}   # key → info do tracker

    # --- SunOp ---
    if fonte in ("sunop", "ambas"):
        plants = _get_plants()
        if not plants and verbose:
            print("[AVISO SunOp] Não foi possível listar plantas (token expirado?).")
        elif plants:
            if verbose:
                print(f"[SunOp] {len(plants)} plantas. Analisando trackers...")
            results: dict[str, list[dict]] = {}
            with ThreadPoolExecutor(max_workers=6) as ex:
                futures = {ex.submit(_analyze_plant, p): p for p in plants}
                for fut in as_completed(futures):
                    p = futures[fut]
                    try:
                        results[p] = fut.result()
                    except Exception as e:
                        if verbose:
                            print(f"  [ERRO SunOp] {p}: {e}")
                        results[p] = []
            for plant, anomalos in results.items():
                usina = USINA_DISPLAY.get(plant, plant)
                sem_dados = [t for t in anomalos if t["tipo"] == "sem_dados"]
                reais     = [t for t in anomalos if t["tipo"] != "sem_dados"]

                # Planta inteira (ou quase) sem telemetria → 1 issue agregado,
                # em vez de inundar a lista com dezenas de "Sem Dados".
                if len(sem_dados) >= TRK_SEM_DADOS_AGRUPAR:
                    key = _issue_key(plant, "PLANTA")
                    anomalas_agora[key] = {
                        "usina":         usina,
                        "plant_id":      plant,
                        "tracker":       "PLANTA",
                        "tracker_label": f"Planta sem telemetria ({len(sem_dados)} trackers)",
                        "tipo":          "sem_dados",
                        "tipo_label":    "Planta sem telemetria de trackers",
                        "fonte":         "sunop",
                        "leitura":       {"trackers_afetados": len(sem_dados)},
                    }
                else:
                    reais = anomalos  # poucos sem_dados: trata individualmente junto

                for trk in reais:
                    key = _issue_key(plant, trk["tracker"])
                    anomalas_agora[key] = {
                        "usina":        usina,
                        "plant_id":     plant,
                        "tracker":      trk["tracker"],
                        "tracker_label": trk["tracker"].replace("TRK_", "Tracker "),
                        "tipo":         trk["tipo"],
                        "tipo_label":   TIPO_LABEL.get(trk["tipo"], trk["tipo"]),
                        "fonte":        "sunop",
                        "leitura": {
                            "alvo": trk.get("alvo"), "atual": trk.get("atual"),
                            "disparidade": trk.get("disparidade"), "strd": trk.get("strd"),
                        },
                    }

    # --- PostgreSQL ---
    if fonte in ("pg", "ambas"):
        if verbose:
            print("[PG] Consultando int_tracker_latest_readings...")
        pg_anomalos = _analyze_pg()
        if verbose:
            print(f"  {len(pg_anomalos)} trackers com problema no PG.")
        for trk in pg_anomalos:
            key = _issue_key(trk["plant_id"], trk["tracker"])
            anomalas_agora[key] = {
                "usina":        trk["usina"],
                "plant_id":     trk["plant_id"],
                "tracker":      trk["tracker"],
                "tracker_label": trk["tracker"],
                "tipo":         trk["tipo"],
                "tipo_label":   trk["tipo_label"],
                "fonte":        "pg",
                "leitura": {
                    "alvo":        trk.get("posal"),
                    "atual":       trk.get("posat"),
                    "disparidade": abs(trk["posal"] - trk["posat"])
                                   if trk.get("posal") is not None and trk.get("posat") is not None
                                   else None,
                    "desvio":      trk.get("deviation"),
                    "status_label": trk.get("status_label"),
                    "ultima_leitura": trk.get("timestamp"),
                },
            }

    # ── Atualiza o JSON ───────────────────────────────────────────────────────
    novos = confirmados = 0
    for key, info in anomalas_agora.items():
        if key in active:
            active[key]["ultima_confirmacao"] = agora
            active[key]["tipo"]        = info["tipo"]
            active[key]["tipo_label"]  = info["tipo_label"]
            active[key]["dias_aberto"] = _dias_aberto(active[key]["data_deteccao"])
            active[key]["leitura"]     = info["leitura"]
            confirmados += 1
        else:
            active[key] = {
                "usina":              info["usina"],
                "plant_id":           info["plant_id"],
                "tracker":            info["tracker"],
                "tracker_label":      info["tracker_label"],
                "tipo":               info["tipo"],
                "tipo_label":         info["tipo_label"],
                "data_deteccao":      agora,
                "ultima_confirmacao": agora,
                "dias_aberto":        0,
                "supervisor":         "",
                "os_fracttal":        "",
                "obs":                "",
                "fonte":              info["fonte"],
                "leitura":            info["leitura"],
            }
            novos += 1
            if verbose:
                print(f"  + [{info['usina']}] {info['tracker_label']} → {info['tipo_label']}")

    # Tracker que sumiu das fontes monitoradas = resolvido automaticamente
    resolvidos = 0
    for key in list(active.keys()):
        issue = active[key]
        # Só auto-resolve issues da mesma fonte(s) que estamos verificando
        if fonte == "ambas" or issue.get("fonte") == fonte:
            if key not in anomalas_agora:
                issue = active.pop(key)
                issue["data_resolucao"] = agora
                try:
                    issue["duracao_horas"] = int(
                        (datetime.fromisoformat(agora) - datetime.fromisoformat(issue["data_deteccao"])).total_seconds() / 3600
                    )
                except Exception:
                    issue["duracao_horas"] = 0
                history.append(issue)
                resolvidos += 1
                if verbose:
                    print(f"  RESOLVIDO [{issue['usina']}] {issue['tracker']} "
                          f"(duração: {issue['duracao_horas']}h)")

    data["ultima_atualizacao"] = agora
    _save_issues(data)

    stats = {"novos": novos, "confirmados": confirmados,
             "resolvidos": resolvidos, "total_ativos": len(active)}
    if verbose:
        print(f"\nResumo: {novos} novos | {confirmados} confirmados | "
              f"{resolvidos} resolvidos | {len(active)} total ativos")
    return stats


# ── Ações manuais ─────────────────────────────────────────────────────────────
def resolver(plant: str, tracker: str, obs: str = ""):
    """Marca um tracker ativo como resolvido manualmente."""
    data   = _load_issues()
    key    = _issue_key(plant, tracker)
    agora  = datetime.now().isoformat(timespec="minutes")
    active = data["active"]
    if key not in active:
        print(f"[AVISO] {key} não está na lista de ativos.")
        return
    issue = active.pop(key)
    issue["data_resolucao"] = agora
    issue["obs"]            = obs or issue.get("obs", "")
    try:
        issue["duracao_horas"] = int(
            (datetime.fromisoformat(agora) - datetime.fromisoformat(issue["data_deteccao"])).total_seconds() / 3600
        )
    except Exception:
        issue["duracao_horas"] = 0
    data["history"].append(issue)
    _save_issues(data)
    print(f"✅ {key} resolvido (duração: {issue['duracao_horas']}h). Obs: {obs}")


def anotar(plant: str, tracker: str, obs: str = "", os_fracttal: str = "", supervisor: str = ""):
    """Adiciona nota / OS Fracttal a um tracker ativo."""
    data  = _load_issues()
    key   = _issue_key(plant, tracker)
    if key not in data["active"]:
        print(f"[AVISO] {key} não está na lista de ativos.")
        return
    if obs:         data["active"][key]["obs"]         = obs
    if os_fracttal: data["active"][key]["os_fracttal"] = os_fracttal
    if supervisor:  data["active"][key]["supervisor"]  = supervisor
    _save_issues(data)
    print(f"📝 {key} anotado.")


def adicionar_manual(plant: str, tracker: str, tipo: str, causa: str = "", supervisor: str = ""):
    """Adiciona manualmente um tracker (p/ usinas fora do SunOp, e.g., SCADA)."""
    data  = _load_issues()
    key   = _issue_key(plant, tracker)
    agora = datetime.now().isoformat(timespec="minutes")
    if key in data["active"]:
        print(f"[AVISO] {key} já existe nos ativos.")
        return
    data["active"][key] = {
        "usina":              plant,
        "plant_id":           plant,
        "tracker":            tracker,
        "tracker_label":      tracker.replace("TRK_", "Tracker "),
        "tipo":               tipo,
        "tipo_label":         TIPO_LABEL.get(tipo, tipo),
        "data_deteccao":      agora,
        "ultima_confirmacao": agora,
        "dias_aberto":        0,
        "supervisor":         supervisor,
        "os_fracttal":        "",
        "obs":                causa,
        "fonte":              "manual",
        "leitura":            {},
    }
    _save_issues(data)
    print(f"➕ {key} adicionado manualmente.")


def sync_api_pv(parados: list, plants_cobertas=None, verbose: bool = False) -> dict:
    """Alimenta o livro com os trackers PARADOS da API PV (a detecção é feita no app.py, com a
    régua boa — amplitude<15°+≥4h). Abre/confirma os parados e auto-resolve os que voltaram —
    mexe SÓ nas issues fonte='apipv' (não toca SunOp/PG). Mesma semântica do atualizar().
    `parados` = [{plant_id, usina, tracker, tracker_label?, leitura?}].
    `plants_cobertas` = ids das usinas REALMENTE avaliadas nesta rodada (com comunicação). Só
    auto-resolve issues de usina coberta — usina SEM COMUNICAÇÃO mantém o tracker aberto (não dá
    p/ saber se voltou). Se None, assume cobertas = as usinas presentes em `parados`."""
    agora = datetime.now().isoformat(timespec="minutes")
    data    = _load_issues()
    active  = data["active"]
    history = data["history"]

    atuais = {}
    for p in (parados or []):
        plant_id = str(p.get("plant_id") or "").strip()
        tracker  = str(p.get("tracker") or "").strip()
        if plant_id and tracker:
            atuais[_issue_key(plant_id, tracker)] = p
    if plants_cobertas is None:
        cobertas = {k.split("|", 1)[0] for k in atuais}
    else:
        cobertas = {str(x) for x in plants_cobertas}

    novos = confirmados = 0
    for key, p in atuais.items():
        if key in active:
            active[key]["ultima_confirmacao"] = agora
            active[key]["leitura"] = p.get("leitura") or active[key].get("leitura") or {}
            confirmados += 1
        else:
            active[key] = {
                "usina":         p.get("usina") or str(p.get("plant_id")),
                "plant_id":      str(p.get("plant_id")),
                "tracker":       str(p.get("tracker")),
                "tracker_label": p.get("tracker_label") or str(p.get("tracker")),
                "tipo":          "parado",
                "tipo_label":    TIPO_LABEL.get("parado", "Parado"),
                "data_deteccao": agora, "ultima_confirmacao": agora, "dias_aberto": 0,
                "supervisor":    "", "os_fracttal": "", "obs": "",
                "fonte":         "apipv", "leitura": p.get("leitura") or {},
            }
            novos += 1

    resolvidos = 0
    for key in list(active.keys()):
        if active[key].get("fonte") != "apipv":          # não mexe nas fontes SunOp/PG
            continue
        if str(active[key].get("plant_id")) not in cobertas:   # usina sem comm/não avaliada → mantém aberto
            continue
        if key not in atuais:
            issue = active.pop(key)
            issue["data_resolucao"] = agora
            try:
                issue["duracao_horas"] = int((datetime.fromisoformat(agora) -
                    datetime.fromisoformat(issue["data_deteccao"])).total_seconds() / 3600)
            except Exception:
                issue["duracao_horas"] = 0
            history.append(issue)
            resolvidos += 1

    data["ultima_atualizacao"] = agora
    _save_issues(data)
    stats = {"novos": novos, "confirmados": confirmados, "resolvidos": resolvidos,
             "total_ativos": len(active)}
    if verbose:
        print(f"[apipv] {novos} novos | {confirmados} confirmados | {resolvidos} resolvidos")
    return stats


def listar():
    """Imprime a lista de issues ativos."""
    data   = _load_issues()
    active = data["active"]
    if not active:
        print("Nenhum tracker com problema no momento.")
        return
    print(f"\n{'='*70}")
    print(f"TRACKERS ATIVOS — {len(active)} ocorrência(s)")
    print(f"Última atualização: {data.get('ultima_atualizacao', '—')}")
    print(f"{'='*70}")
    for key, issue in sorted(active.items()):
        dias = issue.get("dias_aberto", 0)
        print(f"  [{issue['usina']}] {issue['tracker_label']}  "
              f"→ {issue['tipo_label']}  "
              f"| detectado: {issue['data_deteccao']}  ({dias}d)  "
              f"| obs: {issue.get('obs','—')}")
    print()


# ── API JSON pública (usada pelo endpoint Flask) ──────────────────────────────
def get_issues_json() -> dict:
    """Retorna o conteúdo atual de tracker_issues.json para a API Flask."""
    data = _load_issues()
    history = data.get("history", [])
    # Atualiza dias_aberto + escalada (Nível 2) sem escrever no arquivo
    for key, issue in data["active"].items():
        issue["dias_aberto"] = _dias_aberto(issue.get("data_deteccao", ""))
        issue.update(_avalia_escalada(issue, key, history))   # horas_aberto, sugerir_os, motivo_os, recorrencias_30d
    # Últimos 60 dias de histórico
    cutoff = (datetime.now() - timedelta(days=60)).isoformat()
    data["history_recent"] = [
        h for h in history
        if h.get("data_resolucao", "") >= cutoff
    ]
    return data


def _num_cabine(tracker: str):
    """Extrai (nº do tracker, cabine) do identificador. Cabine = sufixo após '.' (convenção
    Fracttal: TRK30 → '30.100', .100 = cabine). Devolve (num|None, cabine|None)."""
    import re
    m = re.search(r"(\d+)(?:\.(\d+))?", str(tracker or ""))
    if not m:
        return None, None
    return m.group(1), m.group(2)


def os_sugeridas() -> list:
    """Issues ativas que viraram SUGESTÃO de OS (Nível 2 — >36h ou recorrente), já com os campos
    prontos p/ o os_creator PRÉ-PREENCHER (usina, tracker, assunto, tipo). NÃO cria nada."""
    data = _load_issues()
    history = data.get("history", [])
    out = []
    for key, issue in data.get("active", {}).items():
        esc = _avalia_escalada(issue, key, history)
        if not esc["sugerir_os"]:
            continue
        usina = issue.get("usina") or issue.get("plant_id") or ""
        trk_label = issue.get("tracker_label") or issue.get("tracker") or ""
        num, cabine = _num_cabine(issue.get("tracker") or trk_label)
        ref = f"Tracker {num}" + (f" (cabine {cabine})" if cabine else "") if num else trk_label
        out.append({
            "key": key, "usina": usina, "plant_id": issue.get("plant_id"),
            "tracker": issue.get("tracker"), "tracker_num": num, "cabine": cabine,
            "tipo_anomalia": issue.get("tipo_label"), "fonte": issue.get("fonte"),
            "horas_aberto": esc["horas_aberto"], "recorrencias_30d": esc["recorrencias_30d"],
            "motivo_os": esc["motivo_os"], "os_fracttal": issue.get("os_fracttal", ""),
            # prontos p/ a OS no Fracttal (o os_creator resolve o ativo "Estrutura Trackers" da usina):
            "ativo_tipo": "Estrutura Trackers",
            "tipo_tarefa": "Corretiva",
            "assunto": f"{ref} parado — {usina}",
            "descricao": f"{ref} parado ({esc['motivo_os']}). Detectado em "
                         f"{issue.get('data_deteccao','')}. Persistente/recorrente — reset não "
                         f"resolveu; verificar estrutura do tracker.",
        })
    out.sort(key=lambda r: (-r["horas_aberto"], r["usina"]))
    return out


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rastreador de trackers SunOp")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list", aliases=["listar"])
    p_upd = sub.add_parser("update", aliases=["atualizar"])
    p_upd.add_argument("--fonte", choices=["sunop","pg","ambas"], default="ambas")

    p_res = sub.add_parser("resolve", aliases=["resolver"])
    p_res.add_argument("plant");  p_res.add_argument("tracker")
    p_res.add_argument("obs", nargs="?", default="")

    p_note = sub.add_parser("note", aliases=["anotar"])
    p_note.add_argument("plant");  p_note.add_argument("tracker")
    p_note.add_argument("obs", nargs="?", default="")
    p_note.add_argument("--os",  dest="os_fracttal", default="")
    p_note.add_argument("--sup", dest="supervisor",  default="")

    p_add = sub.add_parser("add", aliases=["adicionar"])
    p_add.add_argument("plant");  p_add.add_argument("tracker")
    p_add.add_argument("tipo",    nargs="?", default="parado")
    p_add.add_argument("causa",   nargs="?", default="")
    p_add.add_argument("--sup",   dest="supervisor", default="")

    args = parser.parse_args()
    cmd  = args.cmd or "update"

    if cmd in ("list", "listar"):
        listar()
    elif cmd in ("resolve", "resolver"):
        resolver(args.plant, args.tracker, args.obs)
    elif cmd in ("note", "anotar"):
        anotar(args.plant, args.tracker, args.obs, args.os_fracttal, args.supervisor)
    elif cmd in ("add", "adicionar"):
        adicionar_manual(args.plant, args.tracker, args.tipo, args.causa, args.supervisor)
    else:
        fonte = getattr(args, "fonte", "ambas") or "ambas"
        atualizar(verbose=True, fonte=fonte)
