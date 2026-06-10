#!/usr/bin/env python3
"""
collect_energy.py — Coleta energia diária (eday) de todas as usinas Full O&M via API PV Operation.

Exemplos:
  python collect_energy.py --start 2025-05-01 --end 2025-05-31 --out energia_maio.xlsx
  python collect_energy.py --days 7 --out energia_7dias.xlsx
  python collect_energy.py --days 1 --out hoje.xlsx
"""

import os
import sys
import argparse
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import pandas as pd

# ── Config ─────────────────────────────────────────────────────────────────────
# Credenciais ficam fora do código: .env na raiz do projeto (ver .env.example)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

BASE_URL     = "https://apipv.pvoperation.com.br/api/v1"
USERNAME     = os.environ.get("PV_USERNAME", "")
PASSWORD     = os.environ.get("PV_PASSWORD", "")
NOMEN_PATH   = r"C:\Users\Levi Maia\Downloads\usinas_nomenclatura.xlsx"
STRINGS_PATH = r"C:\Users\Levi Maia\Desktop\Check Diário - Geração e ETM.xlsx"
MAX_WORKERS  = 5


# ── Auth & plantas ─────────────────────────────────────────────────────────────
def get_token() -> str:
    r = requests.post(f"{BASE_URL}/authenticate",
                      json={"username": USERNAME, "password": PASSWORD}, timeout=30)
    r.raise_for_status()
    return r.json()["token"]


def get_plants(token: str) -> list:
    r = requests.get(f"{BASE_URL}/plants", headers={"x-access-token": token}, timeout=30)
    r.raise_for_status()
    return r.json()


# ── Planilhas ──────────────────────────────────────────────────────────────────
def load_nomenclatura() -> dict:
    """Retorna {plant_id_str: nome_desejado}."""
    try:
        df = pd.read_excel(NOMEN_PATH, dtype={"ID": str})
        return {
            str(int(float(row["ID"]))): str(row["Nome Desejado"]).strip()
            for _, row in df.iterrows()
            if pd.notna(row.get("Nome Desejado")) and str(row["Nome Desejado"]).strip()
        }
    except Exception as e:
        print(f"[AVISO] Nomenclatura não carregada: {e}", file=sys.stderr)
        return {}


def load_full_om() -> set:
    """Retorna conjunto com os nomes de supervisão das usinas Full O&M."""
    try:
        s2 = pd.read_excel(STRINGS_PATH, sheet_name="Strings 2", header=1)
        s2.columns = [str(c).strip() for c in s2.columns]
        sup_col  = next((c for c in s2.columns if "supervis" in c.lower() and "usina"  in c.lower()), None)
        full_col = next((c for c in s2.columns if "full" in c.lower()), None)
        if not sup_col or not full_col:
            print("[AVISO] Colunas 'supervisão usina' / 'full' não encontradas na planilha", file=sys.stderr)
            return set()
        mask = s2[full_col].astype(str).str.strip().str.lower() == "sim"
        return set(s2.loc[mask, sup_col].dropna().astype(str).str.strip().unique())
    except Exception as e:
        print(f"[AVISO] Planilha Full O&M não carregada: {e}", file=sys.stderr)
        return set()


# ── Device names ───────────────────────────────────────────────────────────────
def get_device_names(token: str, plant_id: int) -> dict:
    """Retorna {device_id: device_name} para inversores da planta."""
    try:
        raw = requests.get(f"{BASE_URL}/plant_devices",
                           headers={"x-access-token": token},
                           json={"id": plant_id}, timeout=20).json()
        if isinstance(raw, list) and raw and "plant_devices" in raw[0]:
            devs = raw[0]["plant_devices"]
        elif isinstance(raw, dict):
            devs = raw.get("plant_devices", [])
        else:
            devs = raw if isinstance(raw, list) else []
        return {d["device_id"]: d["device_name"]
                for d in devs if d.get("device_type") == "INVERTER"}
    except Exception:
        return {}


# ── Coleta energia de um dia ───────────────────────────────────────────────────
def fetch_energy(token: str, plant_id: int, d: date,
                 dev_names: dict, usina_nome: str) -> list:
    """
    POST /custom_query data_type=energy para um dia.
    Retorna lista de dicts prontos para o DataFrame.
    """
    try:
        r = requests.post(
            f"{BASE_URL}/custom_query",
            headers={"x-access-token": token},
            json={"id": plant_id, "data_type": "energy",
                  "period": d.strftime("%Y-%m"), "day": d.day},
            timeout=60,
        )
        if r.status_code != 200:
            print(f"  [ERRO] plant={plant_id} {d} HTTP {r.status_code}", file=sys.stderr)
            return []
        records = r.json() or []
    except Exception as e:
        print(f"  [ERRO] plant={plant_id} {d}: {e}", file=sys.stderr)
        return []

    rows = []
    for rec in records:
        inv_id = rec.get("idinversor")
        try:
            eday_kwh = float(rec["eday"]) if rec.get("eday") is not None else None
        except (TypeError, ValueError):
            eday_kwh = None
        rows.append({
            "date":        d.isoformat(),
            "plant_id":    plant_id,
            "usina":       usina_nome,
            "idinversor":  inv_id,
            "device_name": dev_names.get(inv_id, str(inv_id) if inv_id else ""),
            "eday_kwh":    eday_kwh,
        })
    return rows


# ── CLI ────────────────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description="Coleta eday das usinas Full O&M (API PV Operation)")
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("--days",  type=int, metavar="N",
                     help="Últimos N dias completos (não inclui o dia atual)")
    grp.add_argument("--start", metavar="YYYY-MM-DD",
                     help="Data inicial do período (requer --end)")
    p.add_argument("--end", metavar="YYYY-MM-DD",
                   help="Data final do período (requer --start)")
    p.add_argument("--out", required=True, metavar="arquivo.xlsx",
                   help="Caminho do arquivo Excel de saída")
    args = p.parse_args()
    if args.start and not args.end:
        p.error("--start requer --end")
    if args.end and not args.start:
        p.error("--end requer --start")
    return args


def build_date_range(args) -> list:
    if args.days:
        today = date.today()
        return [today - timedelta(days=i + 1) for i in range(args.days)][::-1]
    start = date.fromisoformat(args.start)
    end   = date.fromisoformat(args.end)
    if end < start:
        print("[ERRO] --end não pode ser anterior a --start", file=sys.stderr)
        sys.exit(1)
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    args  = parse_args()
    dates = build_date_range(args)
    print(f"Período: {dates[0]} → {dates[-1]}  ({len(dates)} dia(s))")

    print("Autenticando na API PV Operation…")
    token = get_token()

    nomen = load_nomenclatura()
    full  = load_full_om()
    all_plants = get_plants(token)

    if full:
        plants = [p for p in all_plants if p["nome"].strip() in full]
        print(f"Full O&M: {len(plants)}/{len(all_plants)} usinas")
    else:
        plants = all_plants
        print(f"[AVISO] Filtro Full O&M vazio — usando todas as {len(plants)} usinas")

    if not plants:
        print("[ERRO] Nenhuma usina encontrada.", file=sys.stderr)
        sys.exit(1)

    def usina_nome(p):
        return nomen.get(str(p["id"]), p["nome"].strip())

    # Carrega device names em paralelo
    print(f"Carregando nomes de dispositivos ({len(plants)} usinas)…")
    dev_names_map: dict = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(get_device_names, token, p["id"]): p["id"] for p in plants}
        for f in as_completed(futs):
            dev_names_map[futs[f]] = f.result()

    # Coleta energia — (plant, date) pairs
    tasks = [(p, d) for p in plants for d in dates]
    total = len(tasks)
    print(f"Coletando energia: {total} requisições ({len(plants)} usinas × {len(dates)} dias)…")

    all_rows: list = []
    failed:   list = []
    done = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {
            ex.submit(fetch_energy, token, p["id"], d,
                      dev_names_map.get(p["id"], {}), usina_nome(p)): (p, d)
            for p, d in tasks
        }
        for f in as_completed(futs):
            p, d = futs[f]
            rows = f.result()
            done += 1
            if not rows:
                failed.append((p, d))
            else:
                all_rows.extend(rows)
            if done % max(1, total // 10) == 0 or done == total:
                print(f"  {done}/{total} ({done/total*100:.0f}%)  —  {len(all_rows)} registros")

    # Retry com token renovado para pares sem dados
    if failed:
        print(f"Retry: {len(failed)} pares sem retorno — renovando token…")
        token2 = get_token()
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = {
                ex.submit(fetch_energy, token2, p["id"], d,
                          dev_names_map.get(p["id"], {}), usina_nome(p)): (p, d)
                for p, d in failed
            }
            retry_ok = 0
            for f in as_completed(futs):
                rows = f.result()
                if rows:
                    all_rows.extend(rows)
                    retry_ok += 1
        print(f"  Retry recuperou {retry_ok}/{len(failed)} pares")

    if not all_rows:
        print("[ERRO] Nenhum dado coletado.", file=sys.stderr)
        sys.exit(1)

    df = pd.DataFrame(all_rows, columns=[
        "date", "plant_id", "usina", "idinversor", "device_name", "eday_kwh"
    ])
    df = df.sort_values(["date", "usina", "device_name"]).reset_index(drop=True)
    df.to_excel(args.out, index=False)
    print(f"\nConcluído. Salvo em: {args.out}  ({len(df)} linhas)")


if __name__ == "__main__":
    main()
