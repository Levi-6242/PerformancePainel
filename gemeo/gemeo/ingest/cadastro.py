# gemeo/gemeo/ingest/cadastro.py
"""Cadastro e metas vindos da Gridco Performance API (BD_Performance). Rebaixa so se o updated_at do
workbook mudou — a mesma revalidacao barata do bd_api da plataforma."""
from __future__ import annotations
import json
import requests

from gemeo.core import alias as _alias
from gemeo.core import db as _db


def _get(http, base, token, caminho, params=None):
    r = http.get(f"{base}{caminho}", params=params, headers={"Accept": "application/json", "Authorization": f"Bearer {token}"}, timeout=90)
    r.raise_for_status()
    return r.json()


def linhas_da_aba(http, base: str, token: str, sheet_id: int, header_row: int) -> list[dict]:
    """Cada linha vira {header: valor}; linhas ate header_row sao cabecalho e saem. Pagina de 500."""
    out, off = [], 0
    while True:
        j = _get(http, base, token, f"/api/sheets/{sheet_id}/rows", {"offset": off, "limit": 500})
        rows = j.get("rows") or []
        for r in rows:
            if int(r.get("row_number") or 0) <= header_row:
                continue
            hs, vs = r.get("headers") or [], r.get("values") or []
            out.append({str(h).strip(): vs[i] if i < len(vs) else None for i, h in enumerate(hs) if str(h).strip()})
        if len(rows) < 500:
            return out
        off += 500


def _sim(v) -> bool:
    return str(v or "").strip().lower() in ("sim", "s", "true", "1")


def separar_equipamentos(linhas: list[dict], piloto: tuple[str, ...]) -> tuple[dict, dict]:
    """Aba Equipamentos → (usinas, inversores por usina), so para as usinas do piloto."""
    usinas: dict[str, dict] = {}
    invs: dict[str, list] = {}
    for ln in linhas:
        cod = str(ln.get("Usina Supervisório") or "").strip()
        if cod not in piloto:
            continue
        if str(ln.get("Equipamento") or "").strip().upper() == "UFV" or str(ln.get("Equipamento Parente") or "").strip().upper() == "UFV" and not str(ln.get("Equipamento Supervisório") or "").strip():
            usinas[cod] = {"cliente": ln.get("Cliente"), "fracttal": ln.get("Usina Fractall"), "kwp": ln.get("Potência (kWp)"),
                           "n_inversores": ln.get("N de Inversores"), "full_om": _sim(ln.get("Full O&M")), "string_box": _sim(ln.get("String Box"))}
            continue
        invs.setdefault(cod, []).append({"codigo_fonte": str(ln.get("Equipamento Supervisório") or "").strip(), "nome": ln.get("Equipamento"),
                                         "kwp": ln.get("Potência (kWp)"), "n_strings_esperadas": ln.get("Strings Ativas")})
    return usinas, invs


class IngestorCadastro:
    fonte = "cadastro"

    def __init__(self, cfg, conn, http=None):
        self.cfg, self.conn, self.http = cfg, conn, http or requests.Session()

    def _sheets(self) -> dict[str, dict]:
        lst = _get(self.http, self.cfg.bd_api_base, self.cfg.bd_api_token, "/api/sheets")
        lst = lst if isinstance(lst, list) else lst.get("items") or []
        return {str(s["sheet_name"]).strip().lower(): s for s in lst if s.get("workbook_key") == "bd_performance"}

    def ciclo(self, force: bool = False) -> dict:
        wbs = _get(self.http, self.cfg.bd_api_base, self.cfg.bd_api_token, "/api/workbooks")
        wb = next((w for w in (wbs if isinstance(wbs, list) else wbs.get("items") or []) if w.get("key") == "bd_performance"), {})
        versao = str(wb.get("updated_at") or "")
        if not force and versao and versao == _db.ler_estado(self.conn, "cadastro.updated_at"):
            return {"mudou": False}
        sheets = self._sheets()
        eq = sheets["equipamentos"]
        linhas = linhas_da_aba(self.http, self.cfg.bd_api_base, self.cfg.bd_api_token, eq["id"], int(eq.get("header_row") or 0))
        usinas, invs = separar_equipamentos(linhas, self.cfg.usinas_piloto)
        res = aplicar_equipamentos(self.conn, usinas, invs)
        _db.gravar_estado(self.conn, "cadastro.updated_at", versao)
        return {"mudou": True, **res}


def aplicar_equipamentos(conn, usinas: dict, invs: dict) -> dict:
    n_u = n_i = 0
    with conn.cursor() as cur:
        for cod, u in usinas.items():
            cur.execute("UPDATE usina SET cliente=%s, kwp_dc=%s, n_inversores=%s, full_om=%s WHERE codigo=%s RETURNING id",
                        (u["cliente"], u["kwp"], u["n_inversores"], u["full_om"], cod))
            r = cur.fetchone()
            if not r:
                continue
            n_u += 1
            if u.get("fracttal"):
                _alias.gravar(conn, "fracttal", str(u["fracttal"]), "direto", "aba Equipamentos", usina_id=r[0])
            for iv in invs.get(cod, []):
                cur.execute("UPDATE equipamento SET nome_exibicao=%s, atributos = json_patch(atributos, %s) WHERE usina_id=%s AND tipo='inversor' AND codigo_fonte=%s RETURNING id",
                            (iv["nome"], json.dumps({"kwp": iv["kwp"], "n_strings_esperadas": iv["n_strings_esperadas"]}), r[0], iv["codigo_fonte"]))
                e = cur.fetchone()
                if e:
                    n_i += 1
                    _alias.gravar(conn, "bd_performance", f"{cod}|{iv['nome']}", "direto", "aba Equipamentos", equipamento_id=e[0], usina_id=r[0])
    conn.commit()
    return {"usinas": n_u, "inversores": n_i}


def inspecionar_cli() -> int:
    from gemeo.core.config import carregar
    cfg = carregar(); http = requests.Session()
    for nome, s in sorted(IngestorCadastro(cfg, None, http)._sheets().items()):
        if nome in ("equipamentos", "info geral", "info mensal", "bd_trackers"):
            j = _get(http, cfg.bd_api_base, cfg.bd_api_token, f"/api/sheets/{s['id']}/rows", {"offset": int(s.get('header_row') or 0), "limit": 1})
            print(f"{s['sheet_name']} (id {s['id']}, header_row {s.get('header_row')}):", (j.get("rows") or [{}])[0].get("headers"))
    return 0
