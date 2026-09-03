# gemeo/tools/importar_alias.py
"""Planilha de-para trackers (supervisorio x Fracttal) -> tabela alias. Leitura pura, gravacao a parte."""
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path

CONFIANCA_POR_COMO_CASOU = {
    "direto": "direto",
    "por contagem da sub-usina": "contagem",
    "por skid da planilha bd_trackers": "contagem",
    "por ordem da sub-usina (confirmar)": "ordem",
    "por bloco na serie unica (confirmar)": "ordem",
    "por limite dos skids (confirmar)": "limite_skid",
    "por limite dos skids, ordem do mab100": "limite_skid",
}


@dataclass(frozen=True)
class LinhaAlias:
    usina_sup: str
    tracker_sup: str
    numero: int
    code_fracttal: str
    confianca: str


def _numero(nome: str) -> int | None:
    m = re.search(r"(\d+)", str(nome or ""))
    return int(m.group(1)) if m else None


def ler_planilha(caminho: Path) -> list[LinhaAlias]:
    import openpyxl
    ws = openpyxl.load_workbook(caminho, read_only=True)["De-Para Trackers"]
    linhas = iter(ws.iter_rows(values_only=True))
    cab = [str(c or "").strip() for c in next(linhas)]
    col = {n: cab.index(n) for n in ("UFV Supervisório", "Tracker Supervisório", "Code Fracttal", "Como casou")}
    out = []
    for r in linhas:
        code = str(r[col["Code Fracttal"]] or "").strip()
        if not code:
            continue
        como = str(r[col["Como casou"]] or "").strip().lower()
        conf = CONFIANCA_POR_COMO_CASOU.get(como, "manual")
        num = _numero(r[col["Tracker Supervisório"]])
        if num is None:
            continue
        out.append(LinhaAlias(str(r[col["UFV Supervisório"]]).strip(), str(r[col["Tracker Supervisório"]]).strip(), num, code, conf))
    return out


def importar(conn, linhas: list[LinhaAlias]) -> dict:
    """Casa cada linha com o tracker da usina pelo NUMERO (equipamento.atributos->>'numero') e grava
    alias(sistema='fracttal', valor=code). Usina e resolvida pelo alias 'bd_performance' do nome do
    supervisorio, ou pelo codigo da usina."""
    from gemeo.core import alias as al
    n_ok = n_sem_usina = n_sem_trk = 0
    with conn.cursor() as cur:
        for ln in linhas:
            cur.execute("SELECT id FROM usina WHERE codigo=%s", (ln.usina_sup,))
            r = cur.fetchone()
            if not r:
                cur.execute("SELECT usina_id FROM alias WHERE sistema='bd_performance' AND valor=%s AND usina_id IS NOT NULL", (ln.usina_sup,))
                r = cur.fetchone()
            if not r:
                n_sem_usina += 1; continue
            cur.execute("SELECT id FROM equipamento WHERE usina_id=%s AND tipo='tracker' AND CAST(json_extract(atributos, '$.numero') AS INTEGER)=%s", (r[0], ln.numero))
            e = cur.fetchone()
            if not e:
                n_sem_trk += 1; continue
            al.gravar(conn, "fracttal", ln.code_fracttal, ln.confianca, "planilha de-para 03/09/2026", equipamento_id=e[0], usina_id=r[0])
            n_ok += 1
    return {"gravados": n_ok, "sem_usina": n_sem_usina, "sem_tracker": n_sem_trk}


def rodar_cli(xlsx: str) -> int:
    from gemeo.core import db
    from gemeo.core.config import carregar
    cfg = carregar(); conn = db.conectar(cfg.db_caminho)
    print(importar(conn, ler_planilha(Path(xlsx))))
    return 0
