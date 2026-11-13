# -*- coding: utf-8 -*-
"""Fechar ou reabrir um mês da disponibilidade do Dashboard Thopen na mão (13/11/2026, disp_fechamento).

    python fechar_mes.py 2026-10 --conferir      mostra o que seria gravado (a média do mês de cada usina), sem gravar
    python fechar_mes.py 2026-10                 fecha o mês com o número que o dashboard mostra agora
    python fechar_mes.py 2026-10 --reabrir       tira o mês do livro (volta para a conta) — só com o OK do Levi

O fechamento automático (dia 10 do mês seguinte) é o laço do próprio 5080; isto é para o mês que fecha fora dele (o
outubro de 2026, fechado no dia 13/11 a pedido do Levi) e para reabrir.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["THOPEN_LOGIN"] = "0"

import disp_fechamento  # noqa: E402
import fonte_api  # noqa: E402
import fonte_operacao  # noqa: E402
import dashboard_thopen as d  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mes", help="AAAA-MM")
    ap.add_argument("--conferir", action="store_true")
    ap.add_argument("--reabrir", action="store_true")
    ap.add_argument("--origem", default="fechado na mão (fechar_mes.py)")
    a = ap.parse_args()
    ano, mes = (int(x) for x in a.mes.split("-"))
    tok = fonte_api._token()
    if a.reabrir:
        print("linhas tiradas:", disp_fechamento.reabrir(ano, mes, tok))
        return
    fonte_operacao._estado.update(dados=fonte_operacao.baixar(tok), ts=time.time(), erro=None)
    d._wb()
    if a.conferir:
        import datetime as dt
        linhas = disp_fechamento.linhas_do_mes(ano, mes, d._usinas_do_5080(), d._disp_dias,
                                               dt.datetime.now().astimezone(), a.origem)
    else:
        n, linhas = d.fechar_mes(ano, mes, a.origem)
        print("gravado: %d linhas do mês (%d na aba)" % (len(linhas), n))
    por_usina = {}
    for l in linhas:
        por_usina.setdefault(l["usina"], []).append(l["disp_pct"])
    for u, vs in sorted(por_usina.items()):
        print("%-30s %3d dias  média %6.2f%%" % (u, len(vs), sum(vs) / len(vs)))
    print("usinas: %d | linhas: %d" % (len(por_usina), len(linhas)))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
