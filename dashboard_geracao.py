# -*- coding: utf-8 -*-
"""Dashboard de Geração / PR (réplica do Power BI) — SÓ HISTÓRICO, fonte = banco.

Lê os diários do BD_Performance (abas por usina: JCD100, MTS100, ...), reconstrói o
"Consolidado Diário" do Power BI e serve os gráficos numa página local (porta 5060).

Regras (idênticas ao Power BI, ver docs/dashboard-tempo-real.md):
  • PR por inversor/dia = (Geração kWh/1000) / (IPOA_DEF × Potência_MWp) × Validação
  • Agregação PONDERADA POR ENERGIA: Σ geração / (Σ IPOA × potência), filtrando validação>0
    (NUNCA média de PRs) — espelha o DAX PR Agregado Mensal.
  • Meta (linha "PR Previsto") = pr_previsto() mensal da Info Mensal.

Reaproveita a camada de metas do app principal (app.py) sem subir o servidor dele.
"""
import os
import pandas as pd
from flask import Flask, jsonify, render_template, request

# Camada de metas/cadastro vem do app principal (app.py), mas importada de forma
# PREGUIÇOSA: importar app.py lê o Excel (~5s) e atrasaria o bind do Flask, fazendo o
# preview navegar antes do servidor subir. Carregamos só na 1ª chamada de dados.
_bd_perf_path = _bd_readable_path = _num = _pot_inv = _nrm = _unaccent = None
info_geral = pr_previsto = meta_geracao_dia = None
INFO_GERAL = {}
USINA_DISPLAY = {}
_app_loaded = False


def _load_app():
    global _bd_perf_path, _bd_readable_path, _num, _pot_inv, _nrm, _unaccent, info_geral, pr_previsto
    global meta_geracao_dia, INFO_GERAL, USINA_DISPLAY, _app_loaded
    if _app_loaded:
        return
    import app as a
    _bd_perf_path, _bd_readable_path = a._bd_perf_path, a._bd_readable_path
    _num, _pot_inv, _nrm = a._num, a._pot_inv, a._nrm
    _unaccent = a._unaccent
    info_geral, pr_previsto, meta_geracao_dia = a.info_geral, a.pr_previsto, a.meta_geracao_dia
    INFO_GERAL, USINA_DISPLAY = a.INFO_GERAL, a.USINA_DISPLAY
    _app_loaded = True


app = Flask(__name__)

# ── Registro dinâmico: abas de usina → cliente (via Info Geral) ────────────────
# Monta { canon: {sheet, sup, cliente} } e { cliente: [canon,...] } cruzando os nomes
# de aba do BD_Performance com a Info Geral (sem acento). Novos clientes/usinas entram
# sozinhos. A potência por inversor usa o nome SUPERVISÓRIO (chave da POWER_INV).
_META_SHEETS = {"info geral", "info mensal", "equipamentos"}
_SKIP_SHEETS = {"falhas", "trackers", "pvsyst", "acumulado anual", "aux"}

_reg_cache = {}   # {mtime: (USINAS, CLIENTES)}
_cache = {}       # {(cliente, mtime): (inv_df, dia_df)}


def _n2(s):
    """Normaliza sem acento/espaço/caixa — casa nomes entre abas e Info Geral."""
    return _nrm(_unaccent(s))


def _match_ig(sheet):
    """Registro da Info Geral correspondente à aba (exato sem acento; senão por prefixo,
    p/ casos como 'Sete Lagoas' ↔ 'Sete Lagoas 2')."""
    k = _n2(sheet)
    for g in INFO_GERAL.values():
        if _n2(g.get("usina", "")) == k:
            return g
    for g in INFO_GERAL.values():
        gk = _n2(g.get("usina", ""))
        if gk and (gk.startswith(k) or k.startswith(gk)):
            return g
    return None


def _registry():
    """(USINAS, CLIENTES) montados das abas + Info Geral, cacheado por mtime do arquivo."""
    _load_app()
    from openpyxl import load_workbook
    try:
        m = os.path.getmtime(_bd_perf_path())
    except OSError:
        m = 0.0
    if m in _reg_cache:
        return _reg_cache[m]
    wb = load_workbook(_bd_readable_path(), read_only=True)
    sheets = wb.sheetnames
    wb.close()
    d2s = {_n2(dsp): sup for sup, dsp in USINA_DISPLAY.items()}
    usinas, clientes = {}, {}
    for s in sheets:
        sl = s.strip().lower()
        if sl in _META_SHEETS or sl in _SKIP_SHEETS or "backup" in sl or sl.startswith("plan"):
            continue
        g = _match_ig(s)
        if not g or not g.get("cliente"):
            continue
        canon, cli = g["usina"], g["cliente"]
        sup = d2s.get(_n2(canon)) or canon
        usinas[canon] = {"sheet": s, "sup": sup, "cliente": cli}
        clientes.setdefault(cli, []).append(canon)
    for c in clientes:
        clientes[c].sort()
    _reg_cache.clear()
    _reg_cache[m] = (usinas, clientes)
    return usinas, clientes


def _find(cols, *needles, exclude=()):
    nd = [n.lower() for n in needles]
    ex = [e.lower() for e in exclude]
    for c in cols:
        cl = str(c).lower()
        if all(n in cl for n in nd) and not any(e in cl for e in ex):
            return c
    return None


def _build(entries):
    """entries = [(canon, sheet, sup)]. DataFrames por inversor/dia e por usina/dia."""
    path = _bd_readable_path()
    inv_rows, dia_rows = [], []
    for canon, sheet, sup in entries:
        try:
            df = pd.read_excel(path, sheet_name=sheet, header=0)
        except Exception:
            continue
        df.columns = [str(c).strip() for c in df.columns]
        c_data = _find(df.columns, "data")
        c_ipoa = _find(df.columns, "ipoa", "def") or _find(df.columns, "ipoa", "etm") \
            or _find(df.columns, "ipoa")
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
            gen_dia = 0.0
            n_inv = 0
            for ic in inv_cols:
                gen = _num(r[ic])
                if gen is None:
                    continue
                pot = _pot_inv(sup, ic)          # kWp (chave supervisório)
                gen_dia += gen
                n_inv += 1
                pr = None
                if pot and ipoa and ipoa > 0 and val is not None:
                    pr = gen / (ipoa * pot) * val   # = (gen/1000)/(IPOA×pot_MWp)×val
                inv_rows.append({
                    "usina": canon, "data": dt, "ano": dt.year, "mes": dt.month,
                    "inversor": ic, "geracao": gen, "ipoa": ipoa, "validacao": val,
                    "pot_kwp": pot, "pr": pr,
                })
            meta = meta_geracao_dia(canon, dt, ipoa, val)   # MWh (todos os dias)
            dia_rows.append({
                "usina": canon, "data": dt, "ano": dt.year, "mes": dt.month,
                "geracao": gen_dia, "ipoa": ipoa, "validacao": val,
                "meta_mwh": meta, "n_inv": n_inv,
            })
    return pd.DataFrame(inv_rows), pd.DataFrame(dia_rows)


def _get(cliente):
    """Consolidado (inv_df, dia_df) de todas as usinas do cliente, cacheado por mtime."""
    usinas, clientes = _registry()
    try:
        m = os.path.getmtime(_bd_perf_path())
    except OSError:
        m = 0.0
    key = (cliente, m)
    if key not in _cache:
        entries = [(c, usinas[c]["sheet"], usinas[c]["sup"]) for c in clientes.get(cliente, [])]
        _cache[key] = _build(entries)
    return _cache[key]


def _pr_ponderado(df_dia, usina_disp):
    """PR realizado agregado (fração) = (Σ geração kWh/1000) / (Σ IPOA × Potência_MWp),
    só dias validação>0. Ponderado por energia (= DAX)."""
    g = info_geral(usina_disp)
    pot_mwp = (g or {}).get("potencia_mwp")
    val = df_dia[(df_dia["validacao"] > 0) & (df_dia["ipoa"] > 0)]
    if not pot_mwp or val.empty:
        return None
    ger = val["geracao"].sum() / 1000.0
    ipoa = val["ipoa"].sum()
    den = ipoa * pot_mwp
    return (ger / den) if den else None


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.route("/api/g/clientes")
def clientes():
    _, cls = _registry()
    return jsonify(sorted(cls.keys()))


@app.route("/api/g/usinas")
def usinas():
    _, cls = _registry()
    return jsonify(cls.get(request.args.get("cliente", ""), []))


@app.route("/api/g/mensal")
def mensal():
    """PR Realizado × Previsto (mensal) para uma usina — bar (realizado) + linha (meta)."""
    u = request.args.get("usina")
    _, dia = _get(request.args.get("cliente", ""))
    disp = (INFO_GERAL.get(_nrm(u), {}) or {}).get("usina", u)
    if dia.empty:
        return jsonify({"usina": disp, "pontos": []})
    sub = dia[dia["usina"] == disp]
    out = []
    for (ano, mes), grp in sub.groupby(["ano", "mes"]):
        realizado = _pr_ponderado(grp, disp)
        rec = pr_previsto(disp, ano, mes)
        out.append({
            "ano": int(ano), "mes": int(mes),
            "realizado": realizado,
            "meta": (rec or {}).get("pr_previsto"),
        })
    out.sort(key=lambda x: (x["ano"], x["mes"]))
    return jsonify({"usina": disp, "pontos": out})


@app.route("/api/g/diario")
def diario():
    """PR diário de um mês (bar) + linha de meta mensal."""
    u = request.args.get("usina")
    ano = int(request.args.get("ano"))
    mes = int(request.args.get("mes"))
    _, dia = _get(request.args.get("cliente", ""))
    disp = (INFO_GERAL.get(_nrm(u), {}) or {}).get("usina", u)
    if dia.empty:
        return jsonify({"usina": disp, "meta": None, "pontos": []})
    sub = dia[(dia["usina"] == disp) & (dia["ano"] == ano) & (dia["mes"] == mes)].copy()
    g = info_geral(disp)
    pot_mwp = (g or {}).get("potencia_mwp")
    rec = pr_previsto(disp, ano, mes)
    pts = []
    for _, r in sub.sort_values("data").iterrows():
        pr = None
        if pot_mwp and r["ipoa"] and r["ipoa"] > 0 and r["validacao"]:
            pr = (r["geracao"] / 1000.0) / (r["ipoa"] * pot_mwp) * r["validacao"]
        pts.append({"dia": int(r["data"].day), "realizado": pr})
    return jsonify({"usina": disp, "meta": (rec or {}).get("pr_previsto"), "pontos": pts})


@app.route("/api/g/inversores")
def inversores():
    """Tabela de Performance Inversores + Top10 piores (período). PR realizado e alvo."""
    u = request.args.get("usina")
    ini = pd.to_datetime(request.args.get("ini")) if request.args.get("ini") else None
    fim = pd.to_datetime(request.args.get("fim")) if request.args.get("fim") else None
    inv, _ = _get(request.args.get("cliente", ""))
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
        ger = grp["geracao"].sum() / 1000.0
        ipoa = grp["ipoa"].sum()
        den = ipoa * (pot.iloc[0] / 1000.0)
        pr = (ger / den) if den else None
        rows.append({"inversor": nome, "pr": pr})
    # alvo da usina = pr_previsto do período (1º mês do range, simplificação V1)
    alvo = None
    if not sub.empty:
        d0 = sub["data"].min()
        rec = pr_previsto(disp, d0.year, d0.month)
        alvo = (rec or {}).get("pr_previsto")
    for r in rows:
        r["alvo"] = alvo
        r["dif"] = (r["pr"] - alvo) if (r["pr"] is not None and alvo is not None) else None
    rows.sort(key=lambda x: (x["pr"] is None, x["pr"]))
    return jsonify({"usina": disp, "alvo": alvo, "inversores": rows})


@app.route("/api/g/kpi")
def kpi():
    """PR UFV (usina) e PR GRID (cliente inteiro) ponderados, no período/mês corrente."""
    cli = request.args.get("cliente", "")
    u = request.args.get("usina")
    _, dia = _get(cli)
    disp = (INFO_GERAL.get(_nrm(u), {}) or {}).get("usina", u)
    if dia.empty:
        return jsonify({"pr_ufv": None, "pr_grid": None})

    def _pr_ultimo_mes(df_u, nome):
        # último mês COM valor (pula meses sem dado, ex.: junho ainda vazio)
        for a, m in sorted(df_u.groupby(["ano", "mes"]).groups.keys(), reverse=True):
            pr = _pr_ponderado(df_u[(df_u["ano"] == a) & (df_u["mes"] == m)], nome)
            if pr is not None:
                return pr
        return None

    # PR UFV: último mês com valor da usina
    pr_ufv = _pr_ultimo_mes(dia[dia["usina"] == disp], disp)
    # PR GRID: média ponderada por potência de todas as usinas do cliente
    num = den = 0.0
    for usi in dia["usina"].unique():
        s = dia[dia["usina"] == usi]
        if s.empty:
            continue
        pr = _pr_ultimo_mes(s, usi)
        pot = (info_geral(usi) or {}).get("potencia_mwp")
        if pr is not None and pot:
            num += pr * pot
            den += pot
    pr_grid = (num / den) if den else None
    return jsonify({"pr_ufv": pr_ufv, "pr_grid": pr_grid})


@app.route("/api/g/refresh", methods=["POST", "GET"])
def refresh():
    """Recarrega a planilha: metas/cadastro do app (Info Geral/Mensal/Equipamentos) e
    limpa os caches locais (registro + consolidados). Os dados diários já recarregam por
    mtime, mas as metas são lidas uma vez na init deste processo — aqui forçamos tudo."""
    global INFO_GERAL, USINA_DISPLAY
    _load_app()
    import app as a
    a.load_equipamentos()                       # esperadas/nomes/Full O&M/potência
    a.load_metas()                              # Info Geral + Info Mensal (metas)
    INFO_GERAL, USINA_DISPLAY = a.INFO_GERAL, a.USINA_DISPLAY   # re-vincula (foram reatribuídas)
    _reg_cache.clear()
    _cache.clear()
    return jsonify({"ok": True})


@app.route("/")
def index():
    return render_template("dashboard_geracao.html")


if __name__ == "__main__":
    app.run(host="127.0.0.1", debug=False, port=5070, threaded=True)
