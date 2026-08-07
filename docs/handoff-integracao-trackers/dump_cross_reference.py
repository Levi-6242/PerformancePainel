# -*- coding: utf-8 -*-
"""Gera usinas_cross_reference.json/.csv a partir dos mapas do app da Plataforma.
NAO grava tokens. Enumeracao one-shot; usa o estado quente persistido (snapshot) para pv/pg
e chamadas leves (meta sunop/axis, get_plants, CSVs owen) para o resto."""
import sys, io, os, re, csv, json, unicodedata
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\Levi Maia\OneDrive - GRID CO\Área de Trabalho\temp\Projeto API PV\plataforma")

OUT_DIR = r"C:\Users\Levi Maia\OneDrive - GRID CO\Área de Trabalho\temp\Projeto API PV\docs\handoff-integracao-trackers"

print("=== importando app (carrega planilhas, ~15-30s) ===", flush=True)
import app
try:
    app._carregar_estado_do_disco()
    print("[ok] estado persistido carregado", flush=True)
except Exception as e:
    print(f"[warn] carregar estado: {e}", flush=True)
    try: app._cache_load()
    except Exception: pass

# Aquece os indices Fracttal (cache em disco; sem chamada viva se dentro do TTL)
try: app._frac_fractall_map()
except Exception as e: print(f"[warn] fractall_map: {e}", flush=True)
try: app._frac_codebase_index()
except Exception as e: print(f"[warn] codebase_index: {e}", flush=True)

# ───────────────────────── helpers ─────────────────────────
def _key(s):
    """Chave de agrupamento: minusculo, sem acento, sem '(...)', espacos colapsados."""
    s = str(s or "").strip().lower()
    s = re.sub(r"\(.*?\)", "", s)
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip()

def _no_paren(s):
    return re.sub(r"\(.*?\)", "", str(s or "")).strip()

def _clean(s):
    return str(s if s is not None else "").strip()

def frac_nome(disp):
    """'Usina Fractall' (nome longo) — espelha a rota api_os_creator_fractall_usinas."""
    fmap = app._frac_fractall_map() or {}
    key = str(disp or "").strip().lower(); k2 = _no_paren(key)
    fr = fmap.get(key) or fmap.get(k2)
    if not fr:
        fr = next((v for kk, v in fmap.items() if len(kk) >= 5 and (kk in key or (k2 and kk in k2))), None)
    return fr

def frac_cb(disp):
    """Code-base Fracttal com fallbacks (exato -> sem parenteses -> via nome longo)."""
    try:
        cb = app._frac_codebase(disp)
        if cb: return cb
        k2 = _no_paren(disp)
        if k2 and k2 != disp:
            cb = app._frac_codebase(k2)
            if cb: return cb
        fr = frac_nome(disp)
        if fr:
            ent = (app._frac_codebase_index() or {}).get(str(fr).strip().lower())
            if ent and ent.get("cb"): return ent["cb"]
    except Exception:
        pass
    return None

# ───────────────────────── enumeracao por fonte ─────────────────────────
# item = (source, native, display, plant_id)
itens = []
diag = {}

# --- PV (API PV) : _pv_trk_cache overview (persistido) + get_plants p/ nome nativo ---
pv_rows = ((getattr(app, "_pv_trk_cache", {}) or {}).get("payload") or {}).get("rows") or []
id2raw = {}
try:
    for p in app.get_plants(app.get_token()):
        id2raw[int(p["id"])] = p["nome"]
    diag["pv_getplants"] = f"OK ({len(id2raw)} plantas)"
except Exception as e:
    diag["pv_getplants"] = f"indisponivel ({e!r})"
for r in pv_rows:
    pid = r.get("plant_id")
    disp = _clean(r.get("usina") or str(pid))
    native = id2raw.get(int(pid)) if pid is not None and str(pid).lstrip("-").isdigit() else None
    native = _clean(native or disp)
    itens.append(("pv", native, disp, pid))
diag["pv"] = len(pv_rows)

# --- PG (Thopen/PostgreSQL) : _pg_trk_cache overview (persistido) ou query direta ---
pg_rows = ((getattr(app, "_pg_trk_cache", {}) or {}).get("payload") or {}).get("rows") or []
pg_src = "_pg_trk_cache (persistido)"
if not pg_rows:
    pg_src = "query direta raw_tracker JOIN tb_power_plants"
    try:
        conn = app._pg_conn(); cur = conn.cursor()
        cur.execute("""SELECT DISTINCT p.id, p.name
            FROM (SELECT DISTINCT power_plant_id FROM public.raw_tracker
                  WHERE "timestamp" >= now() - interval '2 days') t
            JOIN public.tb_power_plants p ON p.id = t.power_plant_id
            ORDER BY p.name""")
        pg_rows = [{"plant_id": rid, "usina": rname} for rid, rname in cur.fetchall()]
        conn.close()
    except Exception as e:
        diag["pg_erro"] = repr(e); pg_rows = []
for r in pg_rows:
    pid = r.get("plant_id"); nm = _clean(r.get("usina") or str(pid))
    itens.append(("pg", nm, nm, pid))          # no PG o nome do banco = nativo = display
diag["pg"] = len(pg_rows); diag["pg_src"] = pg_src
# cross-check leve do PG por query direta (so diagnostico)
try:
    conn = app._pg_conn(); cur = conn.cursor()
    cur.execute("""SELECT count(DISTINCT power_plant_id) FROM public.raw_tracker
                   WHERE "timestamp" >= now() - interval '2 days'""")
    diag["pg_query_count"] = cur.fetchone()[0]; conn.close()
except Exception as e:
    diag["pg_query_count"] = f"erro {e!r}"

# --- SUNOP (Athon/gridco) e AXIS : trk_cache persistido -> fallback meta vivo (com retry) ---
import time as _t
for fonte, inst in (("sunop", "gridco"), ("axis", "axis")):
    src = None; enum = []
    # 1) overview de trackers PERSISTIDO (sem chamada viva): rows tem plant_id (code-base) + usina
    trk_rows = ((app._si(inst).get("trk_cache") or {}).get("payload") or {}).get("rows") or []
    if trk_rows:
        src = "trk_cache persistido"
        for r in trk_rows:
            p = _clean(r.get("plant_id")); disp = _clean(r.get("usina") or p)
            enum.append((p, disp))
    else:
        # 2) meta vivo, com ate 3 tentativas (o servico /plants costuma ficar de pe)
        for attempt in range(3):
            try:
                app.ensure_sunop_meta(inst)
                meta = app._si(inst)["meta"]
                com = [(p, m) for p, m in meta.items() if m.get("trackers")]
                diag[f"{fonte}_meta_total"] = len(meta)
                if com:
                    src = f"meta vivo (tentativa {attempt+1})"
                    for p, m in com:
                        disp = _clean(app.USINA_DISPLAY.get(p, p))
                        enum.append((_clean(p), disp))
                    break
            except Exception as e:
                diag[f"{fonte}_erro"] = repr(e)
            _t.sleep(4)
    for p, disp in enum:
        itens.append((fonte, p, disp, None))
    diag[fonte] = len(enum); diag[f"{fonte}_src"] = src or "vazio/indisponivel"

# --- OWEN (2C) : conjunto fixo OWEN_UFVS ---
owen_n = 0
for code in app.OWEN_UFVS:
    disp = _clean(app._owen_nome(code))
    itens.append(("owen", _clean(code), disp, code))
    owen_n += 1
diag["owen"] = owen_n

# ───────────────────────── merge por display normalizado ─────────────────────────
COL = {"pv": "api_pv", "pg": "thopen_pg", "sunop": "athon_sunop", "axis": "axis", "owen": "dois_c_owen"}
PRIO = {"pv": 0, "pg": 1, "owen": 2, "sunop": 3, "axis": 4}
rows = {}
for source, native, disp, pid in itens:
    k = _key(disp)
    if not k:
        continue
    rec = rows.get(k)
    if rec is None:
        rec = {"display": disp, "_prio": 99,
               "fracttal_codebase": None, "fracttal_nome": None,
               "athon_sunop": None, "axis": None, "api_pv": None,
               "thopen_pg": None, "dois_c_owen": None,
               "fontes": [], "_ids": {}}
        rows[k] = rec
    rec[COL[source]] = native
    if source not in rec["fontes"]:
        rec["fontes"].append(source)
    if pid is not None:
        rec["_ids"][source] = pid
    if PRIO[source] < rec["_prio"] or (PRIO[source] == rec["_prio"] and len(str(disp)) > len(str(rec["display"]))):
        rec["display"] = disp; rec["_prio"] = PRIO[source]

# Fracttal por linha (display canonico)
for rec in rows.values():
    d = rec["display"]
    rec["fracttal_codebase"] = frac_cb(d)
    rec["fracttal_nome"] = frac_nome(d)
    rec["fontes"] = sorted(rec["fontes"], key=lambda f: PRIO[f])
    rec.pop("_prio", None)

# ordena por display
ordenado = sorted(rows.values(), key=lambda r: _key(r["display"]))

# ───────────────────────── escreve arquivos ─────────────────────────
os.makedirs(OUT_DIR, exist_ok=True)
FIELDS = ["display", "fracttal_codebase", "fracttal_nome", "athon_sunop",
          "axis", "api_pv", "thopen_pg", "dois_c_owen", "fontes"]

json_path = os.path.join(OUT_DIR, "usinas_cross_reference.json")
csv_path = os.path.join(OUT_DIR, "usinas_cross_reference.csv")

json_out = []
for r in ordenado:
    o = {k: r.get(k) for k in FIELDS}
    o["_plant_ids"] = r.get("_ids", {})   # auxiliar: chaves numericas p/ integracao (pv/pg/owen)
    json_out.append(o)
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(json_out, f, ensure_ascii=False, indent=2)

with open(csv_path, "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(FIELDS)
    for r in ordenado:
        w.writerow([
            r.get("display") or "",
            r.get("fracttal_codebase") or "",
            r.get("fracttal_nome") or "",
            r.get("athon_sunop") or "",
            r.get("axis") or "",
            r.get("api_pv") or "",
            r.get("thopen_pg") or "",
            r.get("dois_c_owen") or "",
            ";".join(r.get("fontes") or []),
        ])

# ───────────────────────── diagnostico ─────────────────────────
print("\n========== DIAGNOSTICO ==========", flush=True)
print("Itens brutos por fonte:", {k: diag.get(k) for k in ("pv", "pg", "sunop", "axis", "owen")}, flush=True)
print("PV get_plants:", diag.get("pv_getplants"), flush=True)
print("PG fonte:", diag.get("pg_src"), diag.get("pg_erro", ""), " | query cross-check DISTINCT:", diag.get("pg_query_count"), flush=True)
print("SUNOP src:", diag.get("sunop_src"), " (meta_total:", diag.get("sunop_meta_total"), ")", flush=True)
print("AXIS  src:", diag.get("axis_src"), " (meta_total:", diag.get("axis_meta_total"), ")", flush=True)
if diag.get("axis_erro"): print("AXIS erro:", diag["axis_erro"], flush=True)
if diag.get("sunop_erro"): print("SUNOP erro:", diag["sunop_erro"], flush=True)

# contagem por coluna preenchida
col_counts = {c: sum(1 for r in ordenado if r.get(c)) for c in
              ("athon_sunop", "axis", "api_pv", "thopen_pg", "dois_c_owen",
               "fracttal_codebase", "fracttal_nome")}
print("\nLINHAS TOTAIS (usinas):", len(ordenado), flush=True)
print("Preenchidas por coluna:", col_counts, flush=True)

sem_frac = [r["display"] for r in ordenado if not r.get("fracttal_codebase")]
print(f"\nSem code-base Fracttal ({len(sem_frac)}):", flush=True)
for d in sem_frac: print("   -", d, flush=True)

# colisoes de code-base entre fontes diferentes (mesma usina fisica, displays diferentes)
by_cb = {}
for r in ordenado:
    cb = r.get("fracttal_codebase")
    if cb:
        by_cb.setdefault(cb, []).append(r)
colis = {cb: rs for cb, rs in by_cb.items() if len(rs) > 1}
print(f"\nCode-bases repetidos em +1 linha ({len(colis)}) — possiveis sub-usinas OU match cross-fonte a revisar:", flush=True)
for cb, rs in sorted(colis.items()):
    print(f"   {cb}: " + " | ".join(f"{r['display']}<{','.join(r['fontes'])}>" for r in rs), flush=True)

print("\nArquivos:", flush=True)
print("  JSON:", json_path, flush=True)
print("  CSV :", csv_path, flush=True)
print("\n===== 6 PRIMEIRAS LINHAS DO CSV =====", flush=True)
with open(csv_path, encoding="utf-8") as f:
    for i, line in enumerate(f):
        if i >= 6: break
        print(line.rstrip("\n"), flush=True)
print("=== FIM ===", flush=True)
