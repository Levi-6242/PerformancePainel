# -*- coding: utf-8 -*-
"""Publica o de-para de trackers (plataforma/trackers_depara.xlsx) no banco da Performance, como workbook
`de_para_trackers` da API SQL (app.gridco.com.br/db_performace) — o mesmo caminho que o gêmeo usa para o
`gemeo_digital` (POST /api/workbooks + POST /api/workbooks/<key>/sync-xlsx?replace=true).

Uso:  python publicar_depara.py            (a partir de plataforma/)
Token de escrita: GRIDCO_SQL_TOKEN, do ambiente ou do tokens.txt da raiz. Nunca é impresso.
`replace=true` só mexe nas abas presentes no arquivo (medido em 31/08): reenviar a planilha editada é seguro."""
import os
import sys
from pathlib import Path

import requests

_AQUI = Path(__file__).resolve().parent
_RAIZ = _AQUI.parent
API_BASE = os.environ.get("GRIDCO_DB_API", "https://app.gridco.com.br/db_performace").rstrip("/")
WORKBOOK = "de_para_trackers"
PLANILHA = _AQUI / "trackers_depara.xlsx"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _token() -> str:
    tok = os.environ.get("GRIDCO_SQL_TOKEN", "").strip()
    if not tok and (_RAIZ / "tokens.txt").exists():
        for ln in (_RAIZ / "tokens.txt").read_text(encoding="utf-8", errors="ignore").splitlines():
            if ln.strip().startswith("GRIDCO_SQL_TOKEN="):
                tok = ln.split("=", 1)[1].strip().strip('"').strip("'")
    if not tok:
        sys.exit("GRIDCO_SQL_TOKEN ausente (ambiente ou tokens.txt)")
    return tok


def publicar(caminho: Path = PLANILHA, chave: str = WORKBOOK, sessao=None) -> dict:
    s = sessao or requests
    h = {"Authorization": f"Bearer {_token()}"}
    r = s.get(f"{API_BASE}/api/workbooks", headers=h, timeout=60)
    r.raise_for_status()
    if chave not in {w.get("key") for w in r.json()}:
        rc = s.post(f"{API_BASE}/api/workbooks", headers=h, timeout=60,
                    json={"key": chave, "display_name": "De-para Trackers (supervisório x Fracttal)"})
        rc.raise_for_status()
        print(f"workbook {chave} criado")
    with open(caminho, "rb") as f:
        r = s.post(f"{API_BASE}/api/workbooks/{chave}/sync-xlsx", headers=h, params={"replace": "true"},
                   files={"file": (f"{chave}.xlsx", f.read(), MIME_XLSX)}, timeout=300)
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    res = publicar()
    print(f"{WORKBOOK}: {res}")
