# gemeo/gemeo/ingest/cadastro.py
"""Cadastro e metas vindos da Gridco Performance API (BD_Performance). Rebaixa so se o updated_at do
workbook mudou — a mesma revalidacao barata do bd_api da plataforma."""
from __future__ import annotations
import json
import re

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
        # "Usina Supervisório" VAZIO nao descarta a linha: nas tres da 2C (11/09/2026) so os inversores trazem o codigo — a UFV e
        # as UG 01/UG 02 vem sem ele, e o nome da usina ("Usina") e o proprio codigo. Mesma regra que a plataforma adotou.
        cod = str(ln.get("Usina Supervisório") or ln.get("Usina") or "").strip()
        if cod not in piloto:
            continue
        eh_ufv = str(ln.get("Equipamento") or "").strip().upper() == "UFV"
        eh_agrupador = str(ln.get("Equipamento Parente") or "").strip().upper() == "UFV" and not str(ln.get("Equipamento Supervisório") or "").strip()
        if eh_ufv or eh_agrupador:
            # a UG (agrupador) so vale quando nao ha linha UFV: na Tupi a UG 02 (3402 kWp, 10 inversores) passava por cima da UFV (6804, 20)
            if eh_ufv or cod not in usinas:
                usinas[cod] = {"cliente": ln.get("Cliente"), "fracttal": ln.get("Usina Fractall"), "kwp": ln.get("Potência (kWp)"),
                               "n_inversores": ln.get("N de Inversores"), "full_om": _sim(ln.get("Full O&M")), "string_box": _sim(ln.get("String Box"))}
            continue
        codigo_fonte, nome = str(ln.get("Equipamento Supervisório") or "").strip(), ln.get("Equipamento")
        if not (codigo_fonte or nome):
            continue
        invs.setdefault(cod, []).append({"codigo_fonte": codigo_fonte, "nome": nome,
                                         "kwp": ln.get("Potência (kWp)"), "n_strings_esperadas": ln.get("Strings Ativas")})
    return usinas, invs


def separar_info_geral(linhas: list[dict], piloto: tuple[str, ...]) -> dict:
    """Aba Info Geral (cabecalho na linha 2): kWp TOTAL da usina, quantidade de inversores e trackers, cliente e P50 anual.
    E a fonte da placa da usina — a aba Equipamentos so lista PARTE dos inversores (03/09: MRO100 12 de 25, MTS100 4 de 40,
    CPP100 2 de 14), e somar o que ela tem dava metade do esperado."""
    def num(ln, k):
        v = ln.get(k)
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None
    out = {}
    for ln in linhas:
        cod = str(ln.get("Usina") or "").strip()
        if cod not in piloto:
            continue
        ni, nt = num(ln, "Quantidade de Inversores"), num(ln, "Qnt. Trackers")
        out[cod] = {"kwp": num(ln, "Potência (KWp)"), "n_inversores": int(ni) if ni else None, "n_trackers": int(nt) if nt else None,
                    "cliente": (str(ln.get("Cliente")).strip() if ln.get("Cliente") else None), "p50_mwh_ano": num(ln, "P50 (MWh)")}
    return out


def aplicar_info_geral(conn, dados: dict) -> int:
    n = 0
    with conn.cursor() as cur:
        for cod, d in dados.items():
            if not d.get("kwp"):
                continue
            cur.execute("UPDATE usina SET kwp_dc=%s, n_inversores=coalesce(%s, n_inversores), cliente=coalesce(%s, cliente) WHERE codigo=%s",
                        (d["kwp"], d.get("n_inversores"), d.get("cliente"), cod))
            n += max(0, cur.rowcount)
    conn.commit()
    return n


VERSAO_CADASTRO = "2026-09-11a"   # entra na marca de versao: mudou o parser, reprocessa mesmo com o workbook igual (11/09: usina pelo nome, inversor pelo nome de exibicao)


def separar_trackers(linhas: list[dict], piloto: tuple[str, ...]) -> dict[str, list[tuple[str, str, str]]]:
    """Aba BD_Trackers: (tracker supervisorio, inversor supervisorio, inversor nome) por usina do piloto. Formatos vistos em
    03/09: tracker 'TRK_17' (igual a SunOp); inversor 'INV_1' (MAB100) ou 'Inversor 1.4' (MRO100, CPP100). A MTS100 vem
    com 'SKC_1' e sem inversor — nao casa com nada (pendencia)."""
    out: dict[str, list] = {}
    for ln in linhas:
        cod = str(ln.get("Usina Supervisório") or "").strip()
        if cod not in piloto:
            continue
        trk = str(ln.get("Tracker Supervisório") or "").strip()
        if not trk:
            continue
        inv_sup = str(ln.get("Inversor Supervisório") or "").strip().replace("\n", "")
        inv_nome = str(ln.get("Inversor") or "").strip().replace("\n", "")
        out.setdefault(cod, []).append((trk, inv_sup, inv_nome))
    return out


def _inversor_de(cur, usina_id: int, inv_sup: str, inv_nome: str) -> tuple[int | None, str]:
    """Resolve o inversor do tracker: codigo da fonte ('INV_4') > nome de exibicao do cadastro ('Inversor 1.4') >
    numero apos o ponto ('Inversor 2.11' -> INV_11, a convencao que casou 119 de 120 na MRO100)."""
    for cand in (inv_sup, inv_nome):
        if re.fullmatch(r"INV_\d+", cand):
            cur.execute("SELECT id FROM equipamento WHERE usina_id=%s AND tipo='inversor' AND codigo_fonte=%s", (usina_id, cand))
            r = cur.fetchone()
            if r:
                return r[0], "direto"
    for cand in (inv_sup, inv_nome):
        if cand:
            cur.execute("SELECT id FROM equipamento WHERE usina_id=%s AND tipo='inversor' AND nome_exibicao=%s", (usina_id, cand))
            r = cur.fetchone()
            if r:
                return r[0], "direto"
    for cand in (inv_sup, inv_nome):
        m = re.search(r"(\d+)\s*$", cand) if cand else None
        if m:
            cur.execute("SELECT id FROM equipamento WHERE usina_id=%s AND tipo='inversor' AND codigo_fonte=%s", (usina_id, f"INV_{int(m.group(1))}"))
            r = cur.fetchone()
            if r:
                return r[0], "ordem"
    return None, ""


def aplicar_trackers(conn, dados: dict[str, list[tuple[str, str, str]]]) -> dict:
    """Grava o pai (inversor) de cada tracker e o alias bd_trackers com a confianca de como casou. Sem isso toda
    perda de tracker vai para a usina, nao para um inversor."""
    mapeados = sem_inversor = sem_tracker = 0
    with conn.cursor() as cur:
        for cod, itens in dados.items():
            cur.execute("SELECT id FROM usina WHERE codigo=%s", (cod,))
            u = cur.fetchone()
            if not u:
                continue
            for trk, inv_sup, inv_nome in itens:
                cur.execute("SELECT id FROM equipamento WHERE usina_id=%s AND tipo='tracker' AND codigo_fonte=%s", (u[0], trk))
                t = cur.fetchone()
                if not t:
                    sem_tracker += 1
                    continue
                inv_id, conf = _inversor_de(cur, u[0], inv_sup, inv_nome)
                if inv_id is None:
                    sem_inversor += 1
                    continue
                cur.execute("UPDATE equipamento SET pai_id=%s WHERE id=%s", (inv_id, t[0]))
                _alias.gravar(conn, "bd_trackers", f"{cod}|{trk}", conf, "aba BD_Trackers", equipamento_id=t[0], usina_id=u[0])
                mapeados += 1
    conn.commit()
    return {"mapeados": mapeados, "sem_inversor": sem_inversor, "sem_tracker": sem_tracker}


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
        versao = f"{wb.get('updated_at') or ''}|{VERSAO_CADASTRO}"
        if not force and versao and versao == _db.ler_estado(self.conn, "cadastro.updated_at"):
            return {"mudou": False}
        sheets = self._sheets()
        eq = sheets["equipamentos"]
        linhas = linhas_da_aba(self.http, self.cfg.bd_api_base, self.cfg.bd_api_token, eq["id"], int(eq.get("header_row") or 0))
        usinas, invs = separar_equipamentos(linhas, self.cfg.usinas_piloto)
        res = aplicar_equipamentos(self.conn, usinas, invs)
        ig = sheets.get("info geral")
        if ig:                                   # a placa TOTAL da usina vem daqui, por cima da soma parcial da Equipamentos
            linhas_ig = linhas_da_aba(self.http, self.cfg.bd_api_base, self.cfg.bd_api_token, ig["id"], int(ig.get("header_row") or 0))
            res["info_geral"] = aplicar_info_geral(self.conn, separar_info_geral(linhas_ig, self.cfg.usinas_piloto))
        bt = sheets.get("bd_trackers")
        if bt:                                   # tracker -> inversor
            linhas_bt = linhas_da_aba(self.http, self.cfg.bd_api_base, self.cfg.bd_api_token, bt["id"], int(bt.get("header_row") or 0))
            res["trackers"] = aplicar_trackers(self.conn, separar_trackers(linhas_bt, self.cfg.usinas_piloto))
        _db.gravar_estado(self.conn, "cadastro.updated_at", versao)
        return {"mudou": True, **res}


def _aplicar_inversor(cur, usina_id: int, iv: dict):
    """Escada igual a do tracker: codigo da fonte ('INV_1') > nome de exibicao ('Inversor 1.1'). O segundo degrau e o das
    usinas da API PV (11/09/2026): la o codigo_fonte e o idefinversor (400771) e o cadastro so conhece 'INVERSOR01' — o que
    os dois tem em comum e o nome, que o de-para do config ja escreveu no equipamento na descoberta."""
    patch = json.dumps({"kwp": iv["kwp"], "n_strings_esperadas": iv["n_strings_esperadas"]})
    for coluna, valor in (("codigo_fonte", iv["codigo_fonte"]), ("nome_exibicao", iv["nome"])):
        if not valor:
            continue
        cur.execute(f"UPDATE equipamento SET nome_exibicao=%s, atributos = json_patch(atributos, %s) WHERE usina_id=%s AND tipo='inversor' AND {coluna}=%s RETURNING id",
                    (iv["nome"], patch, usina_id, str(valor).strip()))
        e = cur.fetchone()
        if e:
            return e
    return None


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
                e = _aplicar_inversor(cur, r[0], iv)
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
