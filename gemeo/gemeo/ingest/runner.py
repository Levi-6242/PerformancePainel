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
        marcas = ",".join(["%s"] * len(codigos)) or "NULL"
        cur.execute(f"SELECT id, codigo, fonte, fonte_ref, tz, coalesce(kwp_dc,0), coalesce(kw_ac,0), lat, lon FROM usina WHERE ativo AND codigo IN ({marcas})", tuple(codigos))
        return [UsinaRef(*r) for r in cur.fetchall()]


def garantir_usinas(conn, cfg) -> int:
    """Linhas base das usinas do piloto a partir do config (fonte, fonte_ref, fuso). Sem elas nem o cadastro nem a
    descoberta na SunOp tem o que preencher — foi o que faltou na primeira subida (03/09). Idempotente."""
    n = 0
    with conn.cursor() as cur:
        for cod in cfg.usinas_piloto:
            det = getattr(cfg, "usinas_detalhe", {}).get(cod, {})
            cur.execute("INSERT INTO usina (codigo, nome, fonte, fonte_ref, tz) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (codigo) DO NOTHING",
                        (cod, det.get("nome", cod), det.get("fonte", "sunop"), det.get("fonte_ref", cod), det.get("tz", "America/Belem")))
            n += max(0, cur.rowcount)
    conn.commit()
    return n


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


def laco(rotulo: str, ingestor, minutos: float, parar: threading.Event, fabrica_conn=None) -> None:
    ultimo_reconcilia: dt.date | None = None
    if fabrica_conn is not None:
        ingestor.conn = fabrica_conn()          # SQLite: uma conexao POR THREAD, aberta dentro da thread
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
                if fabrica_conn is not None:
                    print(f"[{rotulo}] retencao: {db.retencao(ingestor.conn, 90)} leituras com mais de 90 dias apagadas", flush=True)
        except Exception:                                   # noqa: BLE001 — o laco nao morre
            print(f"[{rotulo}] ciclo falhou:\n{traceback.format_exc()}", flush=True)
        parar.wait(minutos * 60)


def rodar() -> int:
    from gemeo.core.config import carregar
    import psycopg2
    cfg = carregar()
    conn = db.conectar(cfg.db_caminho)
    novas = garantir_usinas(conn, cfg)
    if novas:
        print(f"usinas do piloto criadas a partir do config: {novas}", flush=True)
    usinas = usinas_do_piloto(conn, cfg.usinas_piloto)
    # PostgreSQL do Thopen so quando ha usina de fonte pg no piloto (e o unico lugar em que psycopg2 continua)
    conn_fonte = psycopg2.connect(cfg.powerplants_dsn) if any(u.fonte == "pg" for u in usinas) else None
    if not usinas:
        print("nenhuma usina do piloto em `usina` — rode o cadastro primeiro (gemeo ingest cria as linhas base a partir do config)")
    parar = threading.Event()
    threads = [threading.Thread(target=laco, args=(r, i, m, parar, lambda: db.conectar(cfg.db_caminho)), name=r, daemon=True)
               for r, i, m in montar(cfg, conn, conn_fonte, usinas)]
    for t in threads:
        t.start()
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(5)
    except KeyboardInterrupt:
        parar.set()
    return 0
