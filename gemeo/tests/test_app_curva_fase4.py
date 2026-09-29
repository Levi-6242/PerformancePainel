# -*- coding: utf-8 -*-
"""Fase 4 — a plataforma lendo curva do banco do gêmeo em vez da API da SunOp (21/09/2026).

**O número que justifica.** O `/data/v2/usage/me` da SunOp acusou 162.892 requisições de 01 a
20/09 contra uma cota de 100.000/mês: saldo zero desde o dia 12, US$ 31,45 já cobrados, e a
projeção num servidor 24 h passa de 400 mil. O gêmeo, que ingere as MESMAS medidas das mesmas
usinas, gasta **85 requisições por dia** — porque guarda em vez de re-perguntar.

A plataforma re-baixa a curva inteira a cada ciclo; o gêmeo baixa uma vez e grava, com 90 dias de
retenção. É a diferença entre cache e acervo, e vale cerca de 40× por usina.

**Por que HTTP e não ler o arquivo.** O SQLite é local hoje, mas a plataforma vai para um servidor
dedicado; `GEMEO_URL` já é configurável e o proxy `/gemeo/*` já existe. Ler o arquivo direto
funcionaria hoje e quebraria na segunda.
"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gemeo.app import consultas as c  # noqa: E402

UTC = dt.timezone.utc


def test_usina_que_o_gemeo_nao_cobre_devolve_vazio_e_nao_erro(conn):
    """A plataforma serve 115 usinas e o gêmeo cobre 25. 'Não tenho' tem de ser uma resposta barata
    e explícita — se virasse erro, o fallback para a SunOp ficaria escondido atrás de um except."""
    r = c.curva_para_plataforma(conn, "NAO_EXISTE_100", "angulo",
                                dt.datetime(2026, 8, 31, tzinfo=UTC), dt.datetime(2026, 9, 1, tzinfo=UTC))
    assert r["series"] == {} and r["tem_dado"] is False


def test_a_rota_existe_e_e_a_que_a_plataforma_vai_chamar():
    import types
    from gemeo.app import server
    cfg = types.SimpleNamespace(senha_app="x", db_dsn="", porta_app=5075, sunop_token="", teto_sunop_dia=600)
    app = server.criar_app(cfg, conectar=lambda: None)
    assert "/gemeo/api/curva" in {str(r.rule) for r in app.url_map.iter_rules()}


def test_por_pathname_usa_o_parser_do_proprio_ingestor():
    """A troca na plataforma so e segura se o de-para for AUTORITATIVO. O `sunop.classificar` e o
    mesmo codigo que gravou o dado — reconstruir a convencao por fora e como a curva do tracker 17
    acaba rotulada como 18, em silencio.

    Este teste trava o acoplamento: se o ingestor mudar a convencao, o leitor muda junto."""
    from gemeo.ingest import sunop
    from gemeo.app import consultas as cc
    assert cc.classificar_pathname is sunop.classificar
    assert sunop.classificar("MRO100.TRK_17.MEDIDAS.POSAT") == (
        "tracker", "TRK_17", "angulo", {"numero": 17})


def test_pathname_desconhecido_nao_vira_serie_vazia_silenciosa(conn):
    """Pathname que o parser nao reconhece TEM de aparecer como nao-atendido. Se virasse serie
    vazia, a plataforma acharia que o gemeo respondeu e desenharia um grafico em branco em vez de
    cair para a SunOp."""
    from gemeo.app import consultas as cc
    import datetime as _dt
    r = cc.curva_por_pathname(conn, ["MRO100.COISA_NOVA.MEDIDAS.X"],
                              _dt.datetime(2026, 8, 31, tzinfo=UTC), _dt.datetime(2026, 9, 1, tzinfo=UTC))
    assert r["series"] == {} and r["nao_atendidos"] == ["MRO100.COISA_NOVA.MEDIDAS.X"]


def test_a_rota_por_pathname_existe():
    import types
    from gemeo.app import server
    cfg = types.SimpleNamespace(senha_app="x", db_dsn="", porta_app=5075, sunop_token="", teto_sunop_dia=600)
    app = server.criar_app(cfg, conectar=lambda: None)
    assert "/gemeo/api/curva/pathnames" in {str(r.rule) for r in app.url_map.iter_rules()}


def test_rota_por_pathname_respeita_janela_com_fuso_e_devolve_utc(conn):
    """O contrato de que a plataforma depende (28/09/2026, `_sunop_do_gemeo` em plataforma/app.py): ela manda a
    janela do dia da usina JÁ em UTC, com +00:00, e desfaz o carimbo — que volta em UTC — pelo fuso da usina.
    Até 28/09 ela mandava a janela na hora da usina e lia o +00:00 como hora da usina: 3 h de deslocamento no
    drill, na ETM e nos trackers. Se esta rota passar a devolver hora local (o "conserto" óbvio do lado de cá),
    a plataforma converte duas vezes — este teste existe para esse dia."""
    import types
    from gemeo.app import server
    from gemeo.core import db
    from semear import limpar_tudo
    limpar_tudo(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO usina (codigo, nome, fonte, fonte_ref, tz) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                    ("MRO100", "MRO100", "sunop", "MRO100", "America/Belem"))
        uid = cur.fetchone()[0]
        cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte) VALUES (%s,%s,%s) RETURNING id",
                    (uid, "tracker", "TRK_1"))
        eid = cur.fetchone()[0]
    conn.commit()
    db.upsert_leituras(conn, [(eid, "angulo", dt.datetime(2026, 9, 22, 2, 30, tzinfo=UTC), 1.0),   # 23:30 de 21/09 em Belém
                              (eid, "angulo", dt.datetime(2026, 9, 22, 9, 0, tzinfo=UTC), 2.0)])   # 06:00 de 22/09
    cfg = types.SimpleNamespace(senha_app="x", db_dsn="", porta_app=5075, sunop_token="", teto_sunop_dia=600)
    cli = server.criar_app(cfg, conectar=lambda: conn).test_client()

    r = cli.post("/gemeo/api/curva/pathnames", headers={"X-Gemeo-Senha": "x"},
                 json={"pathnames": ["MRO100.TRK_1.MEDIDAS.POSAT"],        # o dia 22/09 de Belém, em UTC
                       "ini": "2026-09-22T03:00:00+00:00", "fim": "2026-09-23T02:59:59+00:00"})

    assert r.get_json()["series"] == {"MRO100.TRK_1.MEDIDAS.POSAT": [["2026-09-22T09:00:00+00:00", 2.0]]}
