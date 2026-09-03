# gemeo/gemeo/ingest/runner.py
"""`gemeo ingest`: um processo, tres laços em threads (pg, sunop fino/lento, cadastro), cada um com
seu ritmo e seu disjuntor. Exceção da fonte nunca mata a thread — vira ingest_run e o laco segue."""
from __future__ import annotations
import datetime as dt
import threading
import time
import traceback

from gemeo.core import db
from gemeo.core.modelos import UsinaRef


def usinas_do_piloto(conn, codigos: tuple[str, ...]) -> list[UsinaRef]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, codigo, fonte, fonte_ref, tz, coalesce(kwp_dc,0), coalesce(kw_ac,0), lat, lon FROM usina WHERE ativo AND codigo = ANY(%s)", (list(codigos),))
        return [UsinaRef(*r) for r in cur.fetchall()]


def montar(cfg, conn_gemeo, conn_fonte, usinas: list[UsinaRef]) -> list[tuple[str, object, int]]:
    from gemeo.ingest.cadastro import IngestorCadastro
    from gemeo.ingest.pg import IngestorPG
    from gemeo.ingest.sunop import IngestorSunOp
    pg = [u for u in usinas if u.fonte == "pg"]; su = [u for u in usinas if u.fonte in ("sunop", "axis")]
    itens: list[tuple[str, object, int]] = []
    if pg:
        itens.append(("pg", IngestorPG(cfg, conn_gemeo, pg, conn_fonte), int(cfg.ritmo_min["pg"])))
    if su:
        itens.append(("sunop_fino", IngestorSunOp(cfg, conn_gemeo, su, grupo="fino"), int(cfg.ritmo_min["sunop_fino"])))
        itens.append(("sunop_lento", IngestorSunOp(cfg, conn_gemeo, su, grupo="lento"), int(cfg.ritmo_min["sunop_lento"])))
    itens.append(("cadastro", IngestorCadastro(cfg, conn_gemeo), int(cfg.ritmo_min["cadastro"])))
    return itens


def laco(rotulo: str, ingestor, minutos: float, parar: threading.Event) -> None:
    ultimo_reconcilia: dt.date | None = None
    while not parar.is_set():
        agora = dt.datetime.now(dt.timezone.utc)
        reconciliar = agora.hour == 3 and ultimo_reconcilia != agora.date()
        try:
            if hasattr(ingestor, "descobrir"):
                for u in getattr(ingestor, "usinas", []):
                    ingestor.descobrir(u)
            ingestor.ciclo(reconciliar=reconciliar) if "reconciliar" in ingestor.ciclo.__code__.co_varnames else ingestor.ciclo()
            if reconciliar:
                ultimo_reconcilia = agora.date()
        except Exception:                                   # noqa: BLE001 — o laco nao morre
            print(f"[{rotulo}] ciclo falhou:\n{traceback.format_exc()}", flush=True)
        parar.wait(minutos * 60)


def rodar() -> int:
    from gemeo.core.config import carregar
    import psycopg2
    cfg = carregar()
    conn = db.conectar(cfg.db_dsn); conn_fonte = psycopg2.connect(cfg.powerplants_dsn)
    hoje = dt.date.today()
    db.garantir_particoes(conn, [hoje, (hoje.replace(day=28) + dt.timedelta(days=4))])
    usinas = usinas_do_piloto(conn, cfg.usinas_piloto)
    if not usinas:
        print("nenhuma usina do piloto em `usina` — rode o cadastro primeiro (gemeo ingest cria as linhas base a partir do config)")
    parar = threading.Event()
    threads = [threading.Thread(target=laco, args=(r, i, m, parar), name=r, daemon=True) for r, i, m in montar(cfg, conn, conn_fonte, usinas)]
    for t in threads:
        t.start()
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(5)
    except KeyboardInterrupt:
        parar.set()
    return 0
