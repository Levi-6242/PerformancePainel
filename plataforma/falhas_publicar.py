# -*- coding: utf-8 -*-
"""Publica as falhas de strings e trackers no workbook `falhas_performance` da Gridco API (25/09/2026).

O Levi decidiu guardar no workbook, e não numa tabela no PostgreSQL da Thopen (nosso usuário não cria tabela lá):
"pode ser guardado no workbook". São as tabelas que ele pediu no começo, já montadas pelo worker em
`falhas_AAAA-MM.json` — este módulo só as põe no formato da planilha e sincroniza.

Caminho que grava cabeçalho na API (o do gêmeo, em produção desde 03/09): xlsx com a linha 1 = cabeçalho, célula
vazia = None (o parser do sync rejeita texto vazio) e POST /api/workbooks/<chave>/sync-xlsx?replace=true. A API não
tem DELETE de workbook: o `sincronizar` só cria quando falta. O `replace` troca as abas presentes no arquivo e apaga
o excedente — por isso o arquivo leva TODOS os meses publicados.

As linhas vão pela data de início (o novo entra no fim) e nenhuma coluna muda sozinha a cada volta: o sync é de hora
em hora e a API guarda histórico por linha — regravar o mês inteiro a cada volta encheria esse histórico. O "quando"
mora na aba `atualizacao`, uma linha por mês.
"""
import io

WORKBOOK = "falhas_performance"
NOME = "Falhas de strings e trackers"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FONTE_ROT = {"pv": "Thopen · API PV", "pg": "Thopen · Banco", "sunop": "Athon", "axis": "Axis", "owen": "2C · e-mail"}

CABECALHOS = {
    "strings_inversor_dia": ["mes", "dia", "fonte", "cliente", "usina", "inversor", "qtd_strings", "strings",
                             "horas_x_strings", "perda_kwh", "perda_nominal_kwh", "kwp_string", "kwh_kwp_dia", "avisos"],
    "strings_episodios": ["mes", "fonte", "cliente", "usina", "inversor", "string", "saiu", "voltou", "situacao", "dias",
                          "horas_sol", "perda_kwh", "perda_inferida_kwh", "kwp_string", "metodo", "avisos"],
    "trackers_episodios": ["mes", "fonte", "cliente", "usina", "tracker", "inversor", "parou", "voltou", "situacao",
                           "horas_sol", "desvio_pico_graus", "fator_perda", "kwp_tracker", "perda_kwh", "cronico", "avisos"],
    "atualizacao": ["mes", "periodo_inicio", "periodo_fim", "atualizado_em", "strings_inversor_dia", "strings_episodios",
                    "trackers_episodios", "regua_strings", "regua_trackers"],
}


def _v(x):
    """Vazio de verdade (None) para None, "" e lista vazia; lista vira texto separado por "; "; booleano, sim/não."""
    if x is None or x == "" or x == []:
        return None
    if isinstance(x, bool):
        return "sim" if x else "não"
    if isinstance(x, (list, tuple)):
        return "; ".join(str(i) for i in x)
    return x


def _situacao_tracker(r):
    if not r.get("fim"):
        return "em aberto"
    saiu = next((f for f in r.get("flags") or [] if str(f).startswith("saiu:")), None)
    if saiu:
        return saiu
    if "gap fechado no fim do dia" in (r.get("flags") or []):
        return "sem dado depois"
    return "voltou a girar"


def tabelas(pacotes):
    """[pacote do mês] → {aba: [linhas na ordem do cabeçalho]}. Meses na ordem, cada um pela data de início."""
    out = {aba: [] for aba in CABECALHOS}
    for p in sorted(pacotes, key=lambda p: p.get("mes") or ""):
        mes = p.get("mes") or (p.get("periodo") or [""])[0][:7]
        s, t = p.get("strings") or {}, p.get("trackers") or {}
        rs = sorted(s.get("rows") or [], key=lambda r: (r["dia"], r["fonte"], r["usina"], r["inversor"]))
        for r in rs:
            out["strings_inversor_dia"].append([_v(x) for x in (
                mes, r["dia"], FONTE_ROT.get(r["fonte"], r["fonte"]), r.get("cliente"), r["usina"], r["inversor"],
                r.get("qtd"), r.get("strings"), r.get("h_sol"), r.get("perda_kwh"), r.get("perda_nominal_kwh"),
                r.get("kwp_string"), r.get("yield"), r.get("flags"))])
        es = sorted(s.get("episodios") or [], key=lambda e: (e["inicio"], e["fonte"], e["usina"], e["inversor"], e["string"]))
        for e in es:
            out["strings_episodios"].append([_v(x) for x in (
                mes, FONTE_ROT.get(e["fonte"], e["fonte"]), e.get("cliente"), e["usina"], e["inversor"], e["string"],
                e["inicio"], e.get("fim"), e.get("fim_motivo"), e.get("dias"), e.get("h_sol"), e.get("perda_kwh"),
                e.get("perda_inferida_kwh"), e.get("kwp_string"), e.get("metodo"), e.get("flags"))])
        ts = sorted(t.get("rows") or [], key=lambda r: (r["inicio"], r["fonte"], r["usina"], str(r["tracker"])))
        for r in ts:
            out["trackers_episodios"].append([_v(x) for x in (
                mes, FONTE_ROT.get(r["fonte"], r["fonte"]), r.get("cliente"), r["usina"], r["tracker"], r.get("inversor"),
                r["inicio"], r.get("fim"), _situacao_tracker(r), r.get("h_sol"), r.get("desvio_pico"), r.get("fator"),
                r.get("kwp_tracker"), r.get("perda_kwh"), bool(r.get("cronico")),
                [f for f in r.get("flags") or [] if f != "em aberto"])])
        per = p.get("periodo") or [None, None]
        reg = p.get("regua") or {}
        out["atualizacao"].append([_v(x) for x in (
            mes, per[0], per[1], p.get("gerado_em"), len(rs), len(es), len(ts), reg.get("janela_strings"),
            reg.get("fator_tracker"))])
    return out


def xlsx_bytes(tabs):
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)
    for aba, cab in CABECALHOS.items():
        ws = wb.create_sheet(aba)
        ws.append(cab)
        for lin in tabs.get(aba, []):
            ws.append(lin)
        ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def sincronizar(conteudo, *, base, token, sessao=None, chave=WORKBOOK, nome=NOME):
    """Garante o workbook (cria só se faltar — não há DELETE na API) e sincroniza com replace=true.
    → o JSON da API: {sheets, inserted, updated, deleted}. Erro HTTP levanta (quem chama registra e segue)."""
    import requests
    s = sessao or requests
    base = base.rstrip("/")
    h = {"Authorization": f"Bearer {token}"}
    r = s.get(f"{base}/api/workbooks", headers=h, timeout=60)
    r.raise_for_status()
    if chave not in {w.get("key") for w in r.json()}:
        rc = s.post(f"{base}/api/workbooks", headers=h, json={"key": chave, "display_name": nome}, timeout=60)
        rc.raise_for_status()
    r = s.post(f"{base}/api/workbooks/{chave}/sync-xlsx", headers=h, params={"replace": "true"},
               files={"file": (f"{chave}.xlsx", conteudo, MIME_XLSX)}, timeout=300)
    r.raise_for_status()
    return r.json()
