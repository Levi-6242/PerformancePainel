# -*- coding: utf-8 -*-
"""Dashboard Thopen — Performance da Usina (réplica do Power BI), fonte = BD_Thopen.xlsx.

Lê o BD_Thopen.xlsx sincronizado (o MESMO arquivo que o Power BI consome via SharePoint)
e reproduz o relatório "Performance da Usina":

  • Página Mensal: barras Produzida × Meta + tabela (Meta, Produzida, Diferença %,
    FC Meta, FC Real).  Fonte: tabela diária da usina (soma por mês) + `Historico_2026`
    (Meta/FC/PR) + `T_Usinas` (Potência MWp para o FC Real).
  • Página Diária: barras de energia/dia + linha de irradiação + linha de meta diária,
    KPIs (acumulado mês, irradiação real/meta, disponibilidade), produção anual
    (2023→2026, via `Historico`) e tabela de comentários.

Contas idênticas ao Power BI (ver as queries M de referência):
  • Produzida (MWh)  = Σ "Energia Produzida (kWh)" do mês / 1000
  • FC Real          = Produzida_kWh / (Pot_kWp × 24 × dias)   [dias = dia de hoje no
                       mês corrente, senão dias do mês] — espelha "Historico Atual (%)"
  • Diferença (%)    = (Produzida − Meta) / Meta
  • Meta diária      = Meta_mensal / dias_do_mês  (linha plana do gráfico diário)

Foco V1: Altair (mas o seletor lista todas as usinas que têm tabela diária).
Recarrega sozinho quando o xlsx muda (mtime). Porta 5080.
"""
import os
import shutil
import tempfile
import threading
import datetime as dt
from calendar import monthrange

import openpyxl
from openpyxl.utils import range_boundaries
from flask import Flask, jsonify, render_template, request

# ── Localização do BD_Thopen.xlsx (1ª que existir; env BD_THOPEN_PATH manda) ───
_CANDIDATOS = [
    os.environ.get("BD_THOPEN_PATH"),
    r"C:\Users\Levi Maia\OneDrive - GRID CO\Grid Co_ - 17. Acesso Externo Thopen"
    r"\1. Registro usinas Thopen\BD_Thopen.xlsx",
    r"C:\Users\Levi Maia\OneDrive - GRID CO\BD_Thopen.xlsx",
    r"C:\Users\Levi Maia\OneDrive - GRID CO\Área de Trabalho\BD_Thopen.xlsx",
]

ANO = 2026   # relatório do ano corrente (tabela Historico_2026 é 2026-específica)


def _bd_path():
    for c in _CANDIDATOS:
        if c and os.path.exists(c):
            return c
    raise FileNotFoundError("BD_Thopen.xlsx não encontrado (defina BD_THOPEN_PATH).")


def _planilha_em():
    """Data/hora de modificação do BD_Thopen.xlsx, formatada (ou None)."""
    try:
        return dt.datetime.fromtimestamp(os.path.getmtime(_bd_path())).strftime("%d/%m/%Y %H:%M")
    except OSError:
        return None


def _open_wb(path):
    """Lê o workbook de uma CÓPIA temporária — assim funciona mesmo com o arquivo
    ABERTO no Excel ou sincronizando no OneDrive (a leitura direta dá PermissionError,
    mas o Windows permite copiar com leitura compartilhada)."""
    tmp = os.path.join(tempfile.gettempdir(), "bd_thopen_dash.xlsx")
    try:
        shutil.copy2(path, tmp)
        return openpyxl.load_workbook(tmp, data_only=True)
    except Exception:
        return openpyxl.load_workbook(path, data_only=True)   # fallback: leitura direta


# ── Cache do workbook por mtime ────────────────────────────────────────────────
_lock = threading.Lock()
_state = {"mtime": None, "path": None, "wb": None, "tbl": {}, "daily": {}, "df": {}}


def _ref_of(obj):
    return obj if isinstance(obj, str) else obj.ref


def _range_rows(ws, ref):
    c1, r1, c2, r2 = range_boundaries(ref)
    return list(ws.iter_rows(min_row=r1, max_row=r2, min_col=c1, max_col=c2,
                             values_only=True))


def _header(ws, ref):
    c1, r1, c2, r2 = range_boundaries(ref)
    row = next(ws.iter_rows(min_row=r1, max_row=r1, min_col=c1, max_col=c2,
                            values_only=True), ())
    return [str(h).strip() if h is not None else "" for h in row]


def _usina_da_aba(ws, ref, hdr):
    """Nome OFICIAL da usina = valor da coluna 'Usina' DENTRO da aba (o dado real, que casa
    com as tabelas de meta/cadastro). É a chave correta — o título da aba é só um rótulo e
    às vezes vem abreviado/sem acento. Cai pro título da aba se não houver coluna 'Usina'."""
    iu = next((i for i, h in enumerate(hdr) if h.lower() == "usina"), None)
    if iu is None:
        return ws.title
    c1, r1, _c2, r2 = range_boundaries(ref)
    col = c1 + iu
    for row in ws.iter_rows(min_row=r1 + 1, max_row=min(r1 + 50, r2),
                            min_col=col, max_col=col, values_only=True):
        if row[0] not in (None, ""):
            return str(row[0]).strip()
    return ws.title


def _wb():
    """Workbook em cache; recarrega quando o arquivo muda. Indexa tabelas nomeadas
    e detecta as tabelas diárias (header com 'Energia Produzida')."""
    with _lock:
        path = _bd_path()
        m = os.path.getmtime(path)
        if _state["wb"] is None or _state["mtime"] != m or _state["path"] != path:
            try:
                wb = _open_wb(path)
            except Exception:
                if _state["wb"] is not None:
                    return _state["wb"]     # arquivo travado num instante: mantém a última leitura boa
                raise
            tbl, daily = {}, {}
            for ws in wb.worksheets:
                try:
                    names = list(ws.tables.keys())
                except Exception:
                    names = []
                for nm in names:
                    ref = _ref_of(ws.tables[nm])
                    tbl[nm] = (ws.title, ref)
                    hdr = _header(ws, ref)
                    hl = [h.lower() for h in hdr]
                    # aba diária = tem 'Energia Produzida' E 'Data' (exclui resumos como "Clientes");
                    # chave = nome da coluna 'Usina' (oficial), não o rótulo da aba
                    if any("energia produzida" in h for h in hl) and "data" in hl:
                        daily[_usina_da_aba(ws, ref, hdr)] = (ws.title, ref)
            _state.update(mtime=m, path=path, wb=wb, tbl=tbl, daily=daily, df={})
        return _state["wb"]


def _cols(rows):
    """rows[0] = header. Devolve (header_list, data_rows)."""
    if not rows:
        return [], []
    hdr = [str(h).strip() if h is not None else "" for h in rows[0]]
    return hdr, rows[1:]


def _ci(hdr, *subs):
    """Índice da 1ª coluna cujo nome (minúsculo) contém TODOS os pedaços."""
    for i, h in enumerate(hdr):
        hl = h.lower()
        if all(s in hl for s in subs):
            return i
    return None


def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    if "," in s:                       # formato pt-BR: 1.038.500,67
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _table(name):
    """(header, data_rows) de uma tabela nomeada, em cache."""
    wb = _wb()
    if name in _state["df"]:
        return _state["df"][name]
    out = ([], [])
    if name in _state["tbl"]:
        sheet, ref = _state["tbl"][name]
        out = _cols(_range_rows(wb[sheet], ref))
    _state["df"][name] = out
    return out


# ── Leitura por domínio ─────────────────────────────────────────────────────────
def _daily_records(usina):
    """Lista de {data(date), ger, ipoa, disp, com} da tabela diária da usina."""
    key = ("recs", usina)
    if key in _state["df"]:
        return _state["df"][key]
    wb = _wb()
    entry = _state["daily"].get(usina)
    recs = []
    if entry:
        sheet_title, ref = entry
        hdr, rows = _cols(_range_rows(wb[sheet_title], ref))
        iD = _ci(hdr, "data")
        iG = _ci(hdr, "energia produzida")
        iI = _ci(hdr, "ipoa")
        iDp = _ci(hdr, "disponibilidade", "usina")
        iC = _ci(hdr, "coment")
        for r in rows:
            d = r[iD] if iD is not None else None
            if not isinstance(d, (dt.datetime, dt.date)):
                continue
            com = None
            if iC is not None and r[iC] not in (None, ""):
                com = str(r[iC]).strip()
            recs.append({
                "data": d.date() if isinstance(d, dt.datetime) else d,
                "ger": _num(r[iG]) if iG is not None else None,
                "ipoa": _num(r[iI]) if iI is not None else None,
                "disp": _num(r[iDp]) if iDp is not None else None,
                "com": com,
            })
    _state["df"][key] = recs
    return recs


def _meta2026(usina):
    """{mes: {meta(kWh), fc, metairr, pr}} para a usina (tabela Historico_2026)."""
    hdr, rows = _table("Historico_2026")
    out = {}
    if not hdr:
        return out
    iU = _ci(hdr, "usina")
    iMes = _ci(hdr, "mês") if _ci(hdr, "mês") is not None else _ci(hdr, "mes")
    iFC = _ci(hdr, "fc")
    iMeta = _ci(hdr, "meta (2026)")
    iIrr = _ci(hdr, "irradia")
    iPR = _ci(hdr, "pr")
    for r in rows:
        if iU is None or str(r[iU]).strip() != usina:
            continue
        mv = r[iMes]
        m = mv.month if isinstance(mv, (dt.datetime, dt.date)) else _num(mv)
        if not m:
            continue
        out[int(m)] = {
            "meta": _num(r[iMeta]) if iMeta is not None else None,
            "fc": _num(r[iFC]) if iFC is not None else None,
            "metairr": _num(r[iIrr]) if iIrr is not None else None,
            "pr": _num(r[iPR]) if iPR is not None else None,
        }
    return out


def _registro():
    """{usina: {nome, cidade, estado, cliente, pot_mwp}} (tabela T_Usinas)."""
    if ("reg",) in _state["df"]:
        return _state["df"][("reg",)]
    hdr, rows = _table("T_Usinas")
    out = {}
    if hdr:
        iU = _ci(hdr, "usina")
        iNome = _ci(hdr, "nome")
        iCid = _ci(hdr, "cidade")
        iEst = _ci(hdr, "estado")
        iCli = _ci(hdr, "cliente")
        iPot = _ci(hdr, "mwp")
        for r in rows:
            u = r[iU] if iU is not None else None
            if not u:
                continue
            out[str(u).strip()] = {
                "nome": r[iNome] if iNome is not None else None,
                "cidade": r[iCid] if iCid is not None else None,
                "estado": r[iEst] if iEst is not None else None,
                "cliente": r[iCli] if iCli is not None else None,
                "pot_mwp": _num(r[iPot]) if iPot is not None else None,
            }
    _state["df"][("reg",)] = out
    return out


def _produzida_mensal(usina, ano):
    """{mes: kWh} de 'Produzida (<ano>)' (linhas COM mês) — para o comparativo mensal."""
    hdr, rows = _table("Historico")
    out = {}
    if not hdr:
        return out
    iU = _ci(hdr, "usina")
    iMes = _ci(hdr, "mês")
    iTipo = _ci(hdr, "tipo")
    iVal = _ci(hdr, "valor")
    alvo = str(ano)
    for r in rows:
        if iU is None or str(r[iU]).strip() != usina:
            continue
        tipo = str(r[iTipo]).strip().lower() if iTipo is not None else ""
        if "produzida" not in tipo or alvo not in tipo:
            continue
        mv = r[iMes] if iMes is not None else None
        if isinstance(mv, (dt.datetime, dt.date)):
            v = _num(r[iVal]) if iVal is not None else None
            if v is not None:
                out[mv.month] = out.get(mv.month, 0.0) + v
    return out


def _produzida_anual(usina):
    """{ano(str): kWh}. Usa o TOTAL anual explícito (linha com Mês vazio) quando existe;
    senão soma os meses. Evita contar em DOBRO quando há AMBOS (ex.: 2023/2024 ganharam
    linhas mensais mas mantiveram a linha de total anual)."""
    hdr, rows = _table("Historico")
    if not hdr:
        return {}
    iU = _ci(hdr, "usina")
    iAno = _ci(hdr, "ano")
    iMes = _ci(hdr, "mês")
    iTipo = _ci(hdr, "tipo")
    iVal = _ci(hdr, "valor")
    total, mensal = {}, {}
    for r in rows:
        if iU is None or str(r[iU]).strip() != usina:
            continue
        tipo = str(r[iTipo]).strip().lower() if iTipo is not None else ""
        if not tipo.startswith("produzida"):
            continue
        v = _num(r[iVal]) if iVal is not None else None
        if v is None:
            continue
        ano = str(r[iAno]).strip() if iAno is not None else ""
        mv = r[iMes] if iMes is not None else None
        if isinstance(mv, (dt.datetime, dt.date)):
            mensal[ano] = mensal.get(ano, 0.0) + v
        else:
            total[ano] = total.get(ano, 0.0) + v
    return {a: (total[a] if a in total else mensal.get(a)) for a in (set(total) | set(mensal))}


# ── Endpoints ─────────────────────────────────────────────────────────────────
app = Flask(__name__)


@app.route("/api/t/usinas")
def usinas():
    _wb()
    us = sorted(_state["daily"].keys())
    default = "Altair" if "Altair" in us else (us[0] if us else None)
    return jsonify({"usinas": us, "default": default})


@app.route("/api/t/overview")
def overview():
    usina = request.args.get("usina", "Altair")
    recs = _daily_records(usina)
    reg = _registro().get(usina, {})
    pot_mwp = reg.get("pot_mwp")
    meta = _meta2026(usina)
    today = dt.date.today()

    prod = {}
    for r in recs:
        if r["data"].year == ANO and r["ger"] is not None:
            prod[r["data"].month] = prod.get(r["data"].month, 0.0) + r["ger"]
    p2023 = _produzida_mensal(usina, 2023)  # anos anteriores, mês a mês (Historico)
    p2024 = _produzida_mensal(usina, 2024)
    p2025 = _produzida_mensal(usina, 2025)

    meses = []
    for m in range(1, 13):
        mt = meta.get(m, {})
        meta_kwh = mt.get("meta")
        pz = prod.get(m)
        pz23 = p2023.get(m)
        pz24 = p2024.get(m)
        pz25 = p2025.get(m)
        dias = today.day if (ANO == today.year and m == today.month) else monthrange(ANO, m)[1]
        fc_real = (pz / (pot_mwp * 1000 * 24 * dias)) if (pz is not None and pot_mwp) else None
        dif = ((pz - meta_kwh) / meta_kwh) if (pz is not None and meta_kwh) else None
        meses.append({
            "mes": m,
            "meta": (meta_kwh / 1000) if meta_kwh else None,
            "produzida": (pz / 1000) if pz is not None else None,
            "produzida_2023": (pz23 / 1000) if pz23 else None,
            "produzida_2024": (pz24 / 1000) if pz24 else None,
            "produzida_2025": (pz25 / 1000) if pz25 else None,
            "dif": dif,
            "fc_meta": mt.get("fc"),
            "fc_real": fc_real,
        })

    pa = _produzida_anual(usina)
    prod2026 = sum(prod.values())
    meta2026_ytd = sum((meta.get(m, {}).get("meta") or 0) for m in prod)
    anual = [
        {"label": "Produzida 2023", "valor": pa.get("2023")},
        {"label": "Produzida 2024", "valor": pa.get("2024")},
        {"label": "Produzida 2025", "valor": pa.get("2025")},
        {"label": "Meta 2026", "valor": meta2026_ytd or None},
        {"label": "Produzida 2026", "valor": prod2026 or None},
    ]

    per = sorted({(r["data"].year, r["data"].month) for r in recs if r["ger"] is not None})
    periodos = [{"ano": a, "mes": mm} for a, mm in per]

    return jsonify({
        "usina": usina, "nome": reg.get("nome") or usina, "cidade": reg.get("cidade"),
        "estado": reg.get("estado"), "cliente": reg.get("cliente"),
        "potencia_mwp": pot_mwp, "ano": ANO, "meses": meses,
        "anual": anual, "periodos": periodos, "planilha_em": _planilha_em(),
    })


@app.route("/api/t/diario")
def diario():
    usina = request.args.get("usina", "Altair")
    ano = int(request.args.get("ano", ANO))
    mes = int(request.args.get("mes", 1))
    recs = [r for r in _daily_records(usina)
            if r["data"].year == ano and r["data"].month == mes]
    recs.sort(key=lambda r: r["data"])

    meta = _meta2026(usina).get(mes, {}) if ano == ANO else {}
    dias_mes = monthrange(ano, mes)[1]
    meta_kwh = meta.get("meta")
    meta_dia = (meta_kwh / dias_mes) if meta_kwh else None

    pontos = [{"dia": r["data"].day, "ger": r["ger"], "ipoa": r["ipoa"], "com": r["com"]}
              for r in recs]
    disp_vals = [r["disp"] for r in recs if r["disp"] is not None]
    kpis = {
        "acum_prod": sum((r["ger"] or 0) for r in recs),
        "acum_meta": meta_kwh,
        "irr_real": round(sum((r["ipoa"] or 0) for r in recs), 1),
        "irr_meta": meta.get("metairr"),
        "disp": (sum(disp_vals) / len(disp_vals)) if disp_vals else None,
    }
    # Agrupa dias CONSECUTIVOS com o MESMO comentário num intervalo
    # (ex.: "01/05/2026 a 06/05/2026"). Dia sem comentário ou texto diferente quebra a sequência.
    grupos = []
    prev_d = None
    for r in recs:
        c, d = r["com"], r["data"]
        if c:
            if (grupos and grupos[-1]["com"] == c and prev_d is not None
                    and (d - prev_d).days == 1 and grupos[-1]["fim"] == prev_d):
                grupos[-1]["fim"] = d
            else:
                grupos.append({"ini": d, "fim": d, "com": c})
        prev_d = d

    def _drange(g):
        a = g["ini"].strftime("%d/%m/%Y")
        b = g["fim"].strftime("%d/%m/%Y")
        return a if a == b else a + " a " + b

    coment = [{"data": _drange(g), "com": g["com"]} for g in grupos]

    return jsonify({"usina": usina, "ano": ano, "mes": mes, "pontos": pontos,
                    "meta_dia": meta_dia, "kpis": kpis, "comentarios": coment})


@app.route("/api/t/reload")
def reload_bd():
    """Força reler o BD_Thopen.xlsx (limpa o cache) — usado pelo botão Atualizar."""
    with _lock:
        _state["wb"] = None
        _state["mtime"] = None
        _state["df"] = {}
    _wb()  # recarrega agora (chamado FORA do lock — _wb() readquire o lock)
    return jsonify({"ok": True, "planilha_em": _planilha_em(),
                    "atualizado_em": dt.datetime.now().strftime("%H:%M:%S")})


@app.route("/")
def index():
    return render_template("dashboard_thopen.html")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5080, debug=False, threaded=True)
