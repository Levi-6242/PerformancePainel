# gemeo/gemeo/core/alias.py
"""O de-para entre sistemas como dado de primeira classe, com confianca. E o '7o de-para' que a
sondagem do Fracttal pediu — sem ele, falha e telemetria nao se cruzam."""
from __future__ import annotations

CONFIANCAS = ("direto", "contagem", "ordem", "limite_skid", "manual")


def resolver(conn, sistema: str, valor: str) -> int | None:
    with conn.cursor() as cur:
        cur.execute("SELECT equipamento_id FROM alias WHERE sistema=%s AND valor=%s", (sistema, valor))
        r = cur.fetchone()
        return r[0] if r else None


def gravar(conn, sistema: str, valor: str, confianca: str, origem: str,
           equipamento_id: int | None = None, usina_id: int | None = None) -> int:
    if confianca not in CONFIANCAS:
        raise ValueError(f"confianca invalida: {confianca}")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO alias (usina_id, equipamento_id, sistema, valor, confianca, origem) VALUES (%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (sistema, valor) DO UPDATE SET equipamento_id=EXCLUDED.equipamento_id, usina_id=EXCLUDED.usina_id, "
            "confianca=EXCLUDED.confianca, origem=EXCLUDED.origem RETURNING id",
            (usina_id, equipamento_id, sistema, valor, confianca, origem))
        rid = cur.fetchone()[0]
    conn.commit()
    return rid
