#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
coletar_geracao_hoje.py
=======================================================================
Coleta, para o DIA DE HOJE, de TODAS as UFVs da API PV Operation:

  1) Geração por INVERSOR  (energia do dia, kWh)
  2) Irradiação por USINA  (POA e GHI integrados no dia, kWh/m²)

Gera um Excel com duas abas: "Geracao_Inversor" e "Irradiacao_Usina".

-----------------------------------------------------------------------
CONTEXTO DA API PV OPERATION  (referência para coletas)
-----------------------------------------------------------------------
Base URL : https://apipv.pvoperation.com.br/api/v1
Auth     : POST /authenticate  {"username","password"} -> {"token"}
           Enviar o token no header  x-access-token  em todas as chamadas.

Endpoints usados aqui:
  • GET  /plants
        -> lista todas as usinas: [{"id":..., "nome":...}, ...]

  • POST /plant_devices   json={"id": plant_id}
        -> dispositivos da usina; inversores têm device_type="INVERTER",
           com device_id e device_name. (Usado p/ nomear o inversor.)

  • POST /custom_query    json={"id":plant_id,"data_type":"energy",
                                "period":"YYYY-MM","day":N}
        -> energia diária por inversor. ESTE data_type TEM HISTÓRICO
           (funciona p/ dias passados) e é o único sem timeout.
           Retorna: [{"dataleitura_new":"...","eday":"1473.48",
                      "idinversor":46064}, ...]
        NOTA: data_types "irradiance"/"irradiation"/"string"/"mppt"
              retornam 401 (não existem). Apenas "energy" e "meteo"
              são válidos; "meteo" via custom_query só dá o dia corrente.

  • POST /day_meteo       json={"id": plant_id}
        -> leituras meteorológicas do DIA CORRENTE (intradiário), em
           conteudojson. Campos de irradiância variam por usina:
             POA (W/m²): IrPOA  ou  Ir  ou  Ir1  ou  piraPOA1
             GHI (W/m²): IrGHI  ou  piraGHI1
           ATENÇÃO: o histórico de meteo NÃO é acessível (só hoje).
           Por isso a irradiação só pode ser coletada no próprio dia.

Como a irradiação DIÁRIA (kWh/m²) é calculada:
   integral trapezoidal das leituras instantâneas de W/m² ao longo do
   dia, dividido por 1000  ->  kWh/m²  (equivale às "horas de sol pleno").
=======================================================================
"""

import os
import sys
import json
import argparse
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import pandas as pd

# ── Config ─────────────────────────────────────────────────────────────────────
# Credenciais ficam fora do código: .env na raiz do projeto (ver .env.example)
try:
    from dotenv import load_dotenv
    # .env fica na RAIZ do repo (compartilhado com a plataforma); este arquivo vive em coletor/
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except ImportError:
    pass

BASE_URL    = "https://apipv.pvoperation.com.br/api/v1"
USERNAME    = os.environ.get("PV_USERNAME", "")
PASSWORD    = os.environ.get("PV_PASSWORD", "")
MAX_WORKERS = 5

# Campos de irradiância (instantânea, W/m²) tentados em ordem, por variarem por usina
POA_FIELDS = ["IrPOA", "Ir", "Ir1", "piraPOA1"]
GHI_FIELDS = ["IrGHI", "piraGHI1", "GHI"]
ERRO_ABS   = 2000.0   # acima disso (em módulo) é código de erro do sensor (ex.: -666)


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


def get_device_names(token: str, plant_id: int) -> dict:
    """{device_id: device_name} apenas dos inversores."""
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


def _parse_cj(raw):
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return raw or {}


def _num(cj: dict, fields: list):
    """Primeiro valor numérico válido dentre os campos candidatos."""
    for f in fields:
        v = cj.get(f)
        if v is None or v == "-":
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if abs(x) >= ERRO_ABS:      # código de erro do sensor
            continue
        return x
    return None


def _integra_kwh_m2(pares):
    """pares = [(timestamp, valor_Wm2), ...] -> kWh/m² (integral trapezoidal)."""
    pares = [(t, max(0.0, v)) for t, v in pares if v is not None]  # negativos -> 0 (noite)
    pares.sort(key=lambda x: x[0])
    if len(pares) < 2:
        return None
    total_wh = 0.0
    for (t1, v1), (t2, v2) in zip(pares, pares[1:]):
        dt_h = (t2 - t1).total_seconds() / 3600.0
        if dt_h <= 0 or dt_h > 1.0:     # ignora saltos > 1h (lacunas)
            continue
        total_wh += (v1 + v2) / 2.0 * dt_h
    return round(total_wh / 1000.0, 3)  # Wh/m² -> kWh/m²


# ── Coleta de uma usina ────────────────────────────────────────────────────────
def coleta_energia(token, plant, dev_names, usina):
    """Geração por inversor (hoje)."""
    pid = plant["id"]
    hoje = date.today()
    try:
        r = requests.post(f"{BASE_URL}/custom_query",
                          headers={"x-access-token": token},
                          json={"id": pid, "data_type": "energy",
                                "period": hoje.strftime("%Y-%m"), "day": hoje.day},
                          timeout=60)
        recs = r.json() if r.status_code == 200 else []
    except Exception:
        recs = []
    out = []
    for rec in recs or []:
        inv_id = rec.get("idinversor")
        try:
            eday = float(rec["eday"]) if rec.get("eday") is not None else None
        except (TypeError, ValueError):
            eday = None
        out.append({
            "date": hoje.isoformat(), "plant_id": pid, "usina": usina,
            "idinversor": inv_id,
            "device_name": dev_names.get(inv_id, str(inv_id) if inv_id else ""),
            "eday_kwh": eday,
        })
    return out


def coleta_irradiacao(token, plant, usina):
    """Irradiação POA e GHI integradas no dia (kWh/m²) + picos."""
    pid = plant["id"]
    hoje = date.today()
    try:
        recs = requests.post(f"{BASE_URL}/day_meteo",
                             headers={"x-access-token": token},
                             json={"id": pid}, timeout=30).json() or []
    except Exception:
        recs = []
    poa_pares, ghi_pares = [], []
    poa_pico = ghi_pico = None
    for rec in recs:
        ts = rec.get("tsleitura_new")
        if not ts:
            continue
        try:
            t = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
        cj = _parse_cj(rec.get("conteudojson"))
        poa = _num(cj, POA_FIELDS)
        ghi = _num(cj, GHI_FIELDS)
        if poa is not None:
            poa_pares.append((t, poa)); poa_pico = poa if poa_pico is None else max(poa_pico, poa)
        if ghi is not None:
            ghi_pares.append((t, ghi)); ghi_pico = ghi if ghi_pico is None else max(ghi_pico, ghi)
    return {
        "date": hoje.isoformat(), "plant_id": pid, "usina": usina,
        "poa_kwh_m2": _integra_kwh_m2(poa_pares),
        "ghi_kwh_m2": _integra_kwh_m2(ghi_pares),
        "poa_pico_wm2": round(poa_pico, 1) if poa_pico is not None else None,
        "ghi_pico_wm2": round(ghi_pico, 1) if ghi_pico is not None else None,
        "n_leituras": len(recs),
    }


def processa_usina(token, plant, dev_names, usina):
    return coleta_energia(token, plant, dev_names, usina), coleta_irradiacao(token, plant, usina)


# ── Full O&M (opcional) ────────────────────────────────────────────────────────
def carrega_full_om():
    """Conjunto de nomes de usina Full O&M, lido da planilha Check (aba Strings 2)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "Check Diário - Geração e ETM.xlsx")
    try:
        s2 = pd.read_excel(path, sheet_name="Strings 2", header=1)
        s2.columns = [str(c).strip() for c in s2.columns]
        sup  = next(c for c in s2.columns if "supervis" in c.lower() and "usina" in c.lower())
        full = next(c for c in s2.columns if "full" in c.lower())
        mask = s2[full].astype(str).str.strip().str.lower() == "sim"
        return set(s2.loc[mask, sup].dropna().astype(str).str.strip().unique())
    except Exception as e:
        print(f"[AVISO] Full O&M não carregado: {e}", file=sys.stderr)
        return set()


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Coleta geração (por inversor) e irradiação (por usina) de HOJE — API PV")
    ap.add_argument("--out", default=f"geracao_hoje_{date.today().isoformat()}.xlsx",
                    help="arquivo Excel de saída")
    ap.add_argument("--fullom", action="store_true",
                    help="coletar apenas usinas Full O&M (senão, TODAS)")
    ap.add_argument("--plant", type=int, default=None,
                    help="coletar só esta usina (id) — para teste")
    args = ap.parse_args()

    print("Autenticando…")
    token = get_token()
    plants = get_plants(token)

    if args.plant:
        plants = [p for p in plants if p["id"] == args.plant]
    elif args.fullom:
        full = carrega_full_om()
        if full:
            plants = [p for p in plants if p["nome"].strip() in full]
        print(f"Full O&M: {len(plants)} usinas")
    print(f"Coletando HOJE ({date.today()}) de {len(plants)} usina(s)…")

    # Nomes de inversores (paralelo)
    dev_map = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(get_device_names, token, p["id"]): p["id"] for p in plants}
        for f in as_completed(futs):
            dev_map[futs[f]] = f.result()

    ger_rows, irr_rows = [], []
    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(processa_usina, token, p, dev_map.get(p["id"], {}), p["nome"].strip()): p
                for p in plants}
        for f in as_completed(futs):
            g, i = f.result()
            ger_rows.extend(g); irr_rows.append(i)
            done += 1
            if done % max(1, len(plants)//10) == 0 or done == len(plants):
                print(f"  {done}/{len(plants)}")

    df_ger = pd.DataFrame(ger_rows, columns=["date","plant_id","usina","idinversor","device_name","eday_kwh"]) \
               .sort_values(["usina","device_name"]).reset_index(drop=True)
    df_irr = pd.DataFrame(irr_rows, columns=["date","plant_id","usina","poa_kwh_m2","ghi_kwh_m2",
                                             "poa_pico_wm2","ghi_pico_wm2","n_leituras"]) \
               .sort_values("usina").reset_index(drop=True)

    with pd.ExcelWriter(args.out, engine="openpyxl") as xw:
        df_ger.to_excel(xw, sheet_name="Geracao_Inversor", index=False)
        df_irr.to_excel(xw, sheet_name="Irradiacao_Usina", index=False)

    print(f"\nConcluído.")
    print(f"  Geração:    {len(df_ger)} linhas (inversores)")
    print(f"  Irradiação: {len(df_irr)} usinas")
    print(f"  Arquivo:    {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()
