# gemeo/tools/backfill_apipv.py
"""Refaz dias passados de UMA usina da API PV (fonte apipv), em dias de Brasilia, pelo mesmo `buscar` + `upsert` do ingest.

Por que existe: o `custom_query` de inversor leva ~146 s por usina de 10 inversores (Tupi, com 20, mais) e a API PV nao
aguenta paralelismo — o ingest so pede dia passado no primeiro ciclo e na reconciliacao da meia-noite. Quando isso falha
(11/09/2026: a rede da maquina caiu das 20:00 as 21:08 bem no primeiro ciclo das tres da 2C), o dia fica sem inversor e
so entra de novo por aqui. Rode fora de pico e uma usina por vez:

    python -m tools.backfill_apipv "Araputanga" 2026-09-08 2026-09-11      # fim EXCLUSIVO: 08, 09 e 10/09

Deixa rastro em `ingest_run` (fonte apipv) como qualquer ciclo."""
from __future__ import annotations
import datetime as dt
import sys
import time
from zoneinfo import ZoneInfo

BRASILIA = ZoneInfo("America/Sao_Paulo")


def janela(dia_ini: str, dia_fim: str) -> tuple[dt.datetime, dt.datetime]:
    """[dia_ini 00:00, dia_fim 00:00) em Brasilia -> UTC. O ingestor filtra (ini, fim]; o minuto 00:00 do primeiro dia
    nao faz falta e o 00:00 do dia_fim ja pertence ao dia seguinte."""
    ini = dt.datetime.fromisoformat(dia_ini).replace(tzinfo=BRASILIA).astimezone(dt.timezone.utc)
    fim = dt.datetime.fromisoformat(dia_fim).replace(tzinfo=BRASILIA).astimezone(dt.timezone.utc)
    return ini, fim


def rodar(ingestor, conn, usina, ini: dt.datetime, fim: dt.datetime) -> dict:
    from gemeo.core import db
    t0 = time.time()
    b = ingestor.buscar(usina, ini, fim)
    n = db.upsert_leituras(conn, b.leituras)
    cob = min(1.0, n / b.esperadas) if b.esperadas else 1.0
    status = "ok" if cob >= 0.9 else "parcial"
    rid = db.registrar_ingest_run(conn, fonte=ingestor.fonte, usina_id=usina.id, ini=ini, fim=fim, status=status, n_linhas=n,
                                  n_requisicoes=b.n_requisicoes, duracao_s=time.time() - t0, cobertura=cob)
    por_medida: dict[str, int] = {}
    for _, m, _, v in b.leituras:
        if v is not None:
            por_medida[m] = por_medida.get(m, 0) + 1
    return {"ingest_run": rid, "status": status, "n_linhas": n, "n_requisicoes": b.n_requisicoes, "cobertura": round(cob, 2),
            "duracao_s": round(time.time() - t0), "por_medida": por_medida}


def main(argv: list[str] | None = None) -> int:
    from gemeo.core import db
    from gemeo.core.config import carregar
    from gemeo.ingest.apipv import IngestorAPIPV
    from gemeo.ingest.runner import exigir_credenciais_apipv, usinas_do_piloto
    a = argv if argv is not None else sys.argv[1:]
    if len(a) != 3:
        print(__doc__)
        return 2
    codigo, dia_ini, dia_fim = a
    cfg = carregar()
    conn = db.conectar(cfg.db_caminho)
    usinas = [u for u in usinas_do_piloto(conn, cfg.usinas_piloto) if u.codigo == codigo and u.fonte == "apipv"]
    if not usinas:
        print(f"{codigo!r} nao e usina apipv do piloto")
        return 2
    exigir_credenciais_apipv(cfg, usinas)
    ini, fim = janela(dia_ini, dia_fim)
    res = rodar(IngestorAPIPV(cfg, conn, usinas), conn, usinas[0], ini, fim)
    print(f"{codigo} {dia_ini}..{dia_fim}: {res}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
