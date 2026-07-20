"""Captura a 'foto' do dado CRU de uma fonte para virar fixture de regressao (projeto
Confiabilidade da Plataforma). Salva SO o dado bruto da fonte, ANTES de qualquer deteccao.

Uso:
  python tests/capturar_caso.py trackers apipv <idusina> <dd/mm/aaaa> <slug>

Ex.:
  python tests/capturar_caso.py trackers apipv 18746926 06/07/2026 primavera-1

-> tests/fixtures/trackers/apipv__<slug>__<aaaa-mm-dd>.raw.json

O gabarito (.gab.json) e escrito a parte, a partir da narracao do especialista.
"""
import os
import re
import sys
import json
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PLAT_BASE = "https://apiplataforma.pvoperation.com"
GRID_MIN = 5   # reamostra a curva para 1 ponto a cada 5 min (grade comum entre trackers)


def _mins(x):
    m = re.search(r"(\d{1,2}):(\d{2})", str(x))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _resample(pts):
    """Reamostra [{x,y}] para grade de GRID_MIN min (ULTIMO ponto por bucket), rotulando "HH:MM".
    Encolhe o fixture ~10x e ALINHA os timestamps entre trackers (a mediana da frota agrupa por x).
    Preserva amplitude (min/max) e o padrao do dia; a deteccao usa amplitude robusta + mediana."""
    bucket = {}
    for p in (pts or []):
        y = p.get("y")
        m = _mins(p.get("x"))
        if m is None or not isinstance(y, (int, float)):
            continue
        b = (m // GRID_MIN) * GRID_MIN
        bucket[b] = y                       # ultimo y do bucket vence
    return [{"x": "{:02d}:{:02d}".format(b // 60, b % 60), "y": bucket[b]} for b in sorted(bucket)]


def _plat_token():
    """Mesma fonte do app: env PLAT_TOKEN, senao plat_token.txt na raiz."""
    t = os.environ.get("PLAT_TOKEN", "").strip()
    if t:
        return t
    with open(os.path.join(ROOT, "plat_token.txt"), encoding="utf-8") as f:
        return f.read().strip()


def _stats_full(graf_cru, jini=7 * 60, jfim=18 * 60):
    """Estatisticas por tracker da resolucao CHEIA (antes de reamostrar), na janela diurna: amplitude,
    min, max, flat_pct (% de pontos IGUAIS ao anterior = travado/glitch), fora_pct (% |angulo|>56 =
    fora do curso fisico), n. Preserva sinais por-minuto (ex.: flatness) que a grade de 5 min apaga."""
    out = {}
    for name, pts in (graf_cru or {}).items():
        ys = [p.get("y") for p in (pts or [])
              if isinstance(p.get("y"), (int, float))
              and (_mins(p.get("x")) is not None and jini <= _mins(p.get("x")) <= jfim)]
        if not ys:
            continue
        flat = sum(1 for i in range(1, len(ys)) if ys[i] == ys[i - 1]) / max(1, len(ys) - 1)
        fora = sum(1 for y in ys if abs(y) > 56) / len(ys)
        out[name] = {"amp": round(max(ys) - min(ys), 1), "min": round(min(ys), 1),
                     "max": round(max(ys), 1), "flat_pct": round(flat * 100),
                     "fora_pct": round(fora * 100), "n": len(ys)}
    return out


def cap_trackers_apipv(idusina, data_br, slug):
    """Foto = a curva CRUA do trackerschart (a mesma que a deteccao consome via _pv_trk_grafico)."""
    tok = _plat_token()
    h = {"accept": "application/json", "origin": "https://plataforma.pvoperation.com",
         "referer": "https://plataforma.pvoperation.com/", "user-agent": "Mozilla/5.0",
         "x-auth-token-update": tok}
    r = requests.get(PLAT_BASE + "/v2/usinas/trackerschart",
                     params={"idusina": idusina, "dataleitura": data_br}, headers=h, timeout=120)
    r.raise_for_status()
    graf_cru = (r.json() or {}).get("grafico") or {}
    graf = {name: _resample(pts) for name, pts in graf_cru.items()}
    stats = _stats_full(graf_cru)                               # da resolução CHEIA, antes de reamostrar
    dia_iso = "-".join(reversed(data_br.split("/")))            # dd/mm/aaaa -> aaaa-mm-dd
    out = {"meta": {"fonte": "apipv", "equipamento": "trackers", "idusina": int(idusina),
                    "usina": slug, "data": data_br, "data_iso": dia_iso,
                    "reamostrado_min": GRID_MIN, "stats": stats},
           "grafico": graf}
    outdir = os.path.join(HERE, "fixtures", "trackers")
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, "apipv__{}__{}.raw.json".format(slug, dia_iso))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    n_pts = sum(len(v) for v in graf.values())
    print("OK {}  ({} trackers, {} pontos, {} KB)".format(
        os.path.basename(path), len(graf), n_pts, os.path.getsize(path) // 1024))
    return path


def cap_trackers_sunop(plant_name, dia_iso, slug, inst="gridco"):
    """Foto dos trackers do SunOp/Athon: curva POSAT (angulo atual) por tracker, via _sunop_trk_curvas
    (importa o app). Times CRUS do SunOp (UTC — a janela diurna do classificador vai precisar de ajuste
    de fuso p/ SunOp)."""
    sys.path.insert(0, ROOT)
    import app
    app.ensure_sunop_meta(inst)
    cur = app._sunop_trk_curvas(plant_name, dia_iso, inst)
    posat = cur.get("posat") or {}       # angulo REAL por tracker
    posal = cur.get("posal") or {}       # angulo ALVO (setpoint) por tracker — o "ideal" cru da fonte
    graf_cru = {n: [{"x": t, "y": v} for t, v in s] for n, s in posat.items() if s}
    graf = {name: _resample(pts) for name, pts in graf_cru.items()}
    stats = _stats_full(graf_cru)
    # alvo: mediana da frota de posal por timestamp (o setpoint é ~igual entre trackers; mediana robustece)
    alvo_cru = {}
    for s in posal.values():
        for t, v in (s or []):
            if isinstance(v, (int, float)):
                alvo_cru.setdefault(t, []).append(v)
    alvo_pts = [{"x": t, "y": sorted(vs)[len(vs) // 2]} for t, vs in alvo_cru.items() if vs]
    alvo_pts.sort(key=lambda p: p["x"])
    alvo = _resample(alvo_pts)
    out = {"meta": {"fonte": "sunop", "inst": inst, "equipamento": "trackers", "plant": plant_name,
                    "usina": slug, "data_iso": dia_iso, "reamostrado_min": GRID_MIN,
                    "fuso": "UTC (SunOp) — janela do classificador precisa ajustar", "stats": stats},
           "grafico": graf, "alvo": alvo}
    outdir = os.path.join(HERE, "fixtures", "trackers")
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, "sunop__{}__{}.raw.json".format(slug, dia_iso))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    n_pts = sum(len(v) for v in graf.values())
    print("OK {}  ({} trackers, {} pontos, {} KB)".format(
        os.path.basename(path), len(graf), n_pts, os.path.getsize(path) // 1024))
    return path


def cap_trackers_pg(plant, dia_iso, slug):
    """Foto dos trackers do PG/Thopen (banco). `plant` = plant_id (digitos) OU nome (resolve no overview).
    Guarda a curva REAL (posat) por tracker + o ALVO real (posal) — o PG entrega o setpoint, que e a
    regua ABSOLUTA p/ desvio-do-ideal (persistencia >10deg = severo, 3-10deg = leve)."""
    sys.path.insert(0, ROOT)
    import app
    if str(plant).isdigit():
        plant_id = str(plant)
    else:                                        # resolve nome -> plant_id via tb_power_plants (o overview
        conn = app._pg_conn(); cur = conn.cursor()   # dos trackers nao traz nome; a tabela mestre traz)
        cur.execute("SELECT id, name FROM public.tb_power_plants WHERE name ILIKE %s ORDER BY id",
                    ("%" + plant + "%",))
        cand = cur.fetchall(); conn.close()
        if not cand:
            raise SystemExit("usina PG nao encontrada: %r (passe o plant_id direto)" % plant)
        plant_id = str(cand[0][0])
        print("[PG] '%s' -> plant_id=%s (%s)" % (plant, plant_id, cand[0][1]))
    trks = app._pg_trk_plant_curvas(plant_id, dia_iso)
    graf_cru, alvo_cru = {}, {}
    for n, d in trks.items():
        if d.get("atual"):
            graf_cru[n] = [{"x": t.strftime("%Y-%m-%dT%H:%M:%S"), "y": v} for t, v in d["atual"]]
        for t, v in (d.get("alvo") or []):
            alvo_cru.setdefault(t, []).append(v)
    graf = {name: _resample(pts) for name, pts in graf_cru.items()}
    stats = _stats_full(graf_cru)
    alvo_pts = [{"x": t.strftime("%Y-%m-%dT%H:%M:%S"), "y": sorted(vs)[len(vs) // 2]}
                for t, vs in sorted(alvo_cru.items()) if vs]
    alvo = _resample(alvo_pts)
    out = {"meta": {"fonte": "pg", "equipamento": "trackers", "plant_id": str(plant_id),
                    "usina": slug, "data_iso": dia_iso, "reamostrado_min": GRID_MIN,
                    "tem_alvo": bool(alvo), "stats": stats},
           "grafico": graf, "alvo": alvo}
    outdir = os.path.join(HERE, "fixtures", "trackers")
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, "pg__{}__{}.raw.json".format(slug, dia_iso))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    n_pts = sum(len(v) for v in graf.values())
    print("OK {}  ({} trackers, {} pontos, alvo={} pts, {} KB)".format(
        os.path.basename(path), len(graf), n_pts, len(alvo), os.path.getsize(path) // 1024))
    return path


if __name__ == "__main__":
    equip, fonte = sys.argv[1:3]
    if fonte == "apipv":
        _, _, idusina, data_br, slug = sys.argv[1:6]
        cap_trackers_apipv(idusina, data_br, slug)
    elif fonte == "sunop":                       # trackers sunop <plant_name> <aaaa-mm-dd> <slug>
        _, _, plant, dia_iso, slug = sys.argv[1:6]
        cap_trackers_sunop(plant, dia_iso, slug)
    elif fonte == "pg":                          # trackers pg <plant_id|nome> <aaaa-mm-dd> <slug>
        _, _, plant, dia_iso, slug = sys.argv[1:6]
        cap_trackers_pg(plant, dia_iso, slug)
    else:
        raise SystemExit("fonte deve ser apipv, sunop ou pg")
