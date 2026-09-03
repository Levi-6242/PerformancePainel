# gemeo/gemeo/cli.py
"""`gemeo <comando>`. Cada comando importa só o que usa: o app não carrega pvlib, o ingest não carrega Flask."""
from __future__ import annotations
import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gemeo")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="aplica as migracoes SQL pendentes")
    sub.add_parser("ingest", help="laco de ingestao (tres fontes)")
    m = sub.add_parser("modelar", help="roda o modelo para as usinas do piloto")
    m.add_argument("--ini"); m.add_argument("--fim"); m.add_argument("--usina")
    c = sub.add_parser("calibrar", help="gera versao calibrada do modelo")
    c.add_argument("--usina", required=True); c.add_argument("--dias", type=int, default=45)
    sub.add_parser("app", help="sobe as telas (waitress)")
    ia = sub.add_parser("importar-alias", help="planilha de-para -> tabela alias")
    ia.add_argument("xlsx")
    sub.add_parser("inspecionar-cadastro", help="imprime os headers das abas do BD_Performance")
    a = p.parse_args(argv)
    if a.cmd == "migrate":
        from gemeo.core import db; from gemeo.core.config import carregar
        cfg = carregar(); conn = db.conectar(cfg.db_dsn, cfg.db_schema)
        print("schema:", db.schema_status(conn, cfg.db_schema))
        for nome in db.migrar(conn, schema=cfg.db_schema): print("aplicada", nome)
        return 0
    if a.cmd == "ingest":
        from gemeo.ingest.runner import rodar; return rodar()
    if a.cmd == "modelar":
        from gemeo.modelar.job import rodar_cli; return rodar_cli(a.ini, a.fim, a.usina)
    if a.cmd == "calibrar":
        from gemeo.modelar.calibrar import rodar_cli; return rodar_cli(a.usina, a.dias)
    if a.cmd == "app":
        from gemeo.app.server import servir; return servir()
    if a.cmd == "importar-alias":
        from tools.importar_alias import rodar_cli; return rodar_cli(a.xlsx)
    if a.cmd == "inspecionar-cadastro":
        from gemeo.ingest.cadastro import inspecionar_cli; return inspecionar_cli()
    return 2


if __name__ == "__main__":
    sys.exit(main())
