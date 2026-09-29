# gemeo/tests/test_ingest_sunop.py
"""Metadata real (34 itens da MRO100) → equipamentos; lote atravessando usinas; teto e 403 → disjuntor.
HTTP e banco sao dubles: o que se testa e o contrato, nao a SunOp."""
import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent))
from semear import limpar_tudo  # noqa: E402
from gemeo.core import db, tempo  # noqa: E402
from gemeo.core.modelos import UsinaRef  # noqa: E402
from gemeo.ingest import sunop  # noqa: E402

UTC = dt.timezone.utc
FIX = json.load(open(Path(__file__).parent / "fixtures" / "sunop_metadata_mro100.json", encoding="utf-8"))


def test_classificar_cada_tipo():
    assert sunop.classificar("MRO100.ESTM.POA.IRAD") == ("estacao", "ESTM", "poa", {})
    assert sunop.classificar("MRO100.INV_7.MEDIDAS.P") == ("inversor", "INV_7", "p_ac", {"numero": 7})
    assert sunop.classificar("MRO100.INV_7.MEDIDAS.EPD") == ("inversor", "INV_7", "e_dia", {"numero": 7})
    assert sunop.classificar("MRO100.INV_7.MEDIDAS.STR.I_PV3") == ("string", "INV_7.I_PV3", "i_string", {"numero": 3, "inversor": "INV_7"})
    assert sunop.classificar("MRO100.TRK_17.MEDIDAS.POSAT") == ("tracker", "TRK_17", "angulo", {"numero": 17})
    assert sunop.classificar("MRO100.TRK_17.MEDIDAS.POSAL") == ("tracker", "TRK_17", "angulo_alvo", {"numero": 17})
    assert sunop.classificar("MRO100.TRK_17.STATUS.WORKSTATE") == ("tracker", "TRK_17", "estado", {"numero": 17})
    assert sunop.classificar("MRO100.CALC.POT.ESP") is None and sunop.classificar("MRO100.TRK_1.ALARME.AUTO_ON") is None


def test_metadata_real_vira_equipamentos_distintos():
    eqs = sunop.equipamentos_de(FIX)
    tipos = {(t, c) for t, c, _ in eqs}
    assert ("estacao", "ESTM") in tipos and ("inversor", "INV_25") in tipos
    assert ("string", "INV_1.I_PV18") in tipos and ("tracker", "TRK_120") in tipos
    assert len(eqs) == len(tipos)                     # um equipamento por (tipo, codigo)


def test_lotes_atravessam_usinas():
    lotes = sunop.lotear(["A.1", "A.2", "B.1", "B.2", "B.3"], tamanho=2)
    assert lotes == [["A.1", "A.2"], ["B.1", "B.2"], ["B.3"]]


def test_ts_local_vira_utc():
    ts = sunop.ts_utc("2026-08-26T12:00:00", "America/Belem")
    assert ts == dt.datetime(2026, 8, 26, 15, 0, tzinfo=dt.timezone.utc)


def test_403_abre_o_disjuntor_e_nao_grava():
    class Resp:
        status_code = 403
        text = "Forbidden (CloudFront)"
        def json(self): return []
    class Http:
        def post(self, *a, **k): return Resp()
    ing = sunop.IngestorSunOp.__new__(sunop.IngestorSunOp)
    from gemeo.ingest.base import Disjuntor
    ing.disjuntor = Disjuntor(); ing.http = Http(); ing.cfg = type("C", (), {"sunop_base": "http://x", "sunop_token": "t"})()
    assert ing._analog(["P.1"], "2026-08-26T00:00:00", "2026-08-26T23:59:59", None) == {}
    assert ing.disjuntor.aberto()


def test_servico_de_dados_usa_o_esquema_bearer_api():
    """/data/v2/* so aceita 'Bearer API <token de API>'; 'Bearer <token>' puro leva 401 (medido em 03/09/2026)."""
    visto = {}

    class Resp:
        status_code = 200
        text = ""
        def json(self): return {}
        def raise_for_status(self): pass

    class Http:
        def post(self, url, **k): visto["post"] = (url, k.get("headers")); return Resp()
        def get(self, url, **k): visto["get"] = (url, k.get("headers")); return Resp()

    ing = sunop.IngestorSunOp.__new__(sunop.IngestorSunOp)
    from gemeo.ingest.base import Disjuntor
    ing.disjuntor = Disjuntor(); ing.http = Http()
    ing.cfg = type("C", (), {"sunop_base": "http://x", "sunop_token": "tok", "cache_dir": "cache-inexistente"})()
    ing._analog(["P.1"], "2026-08-26T00:00:00", "2026-08-26T23:59:59", "15m")
    assert visto["post"][0].endswith("/data/v2/analog_values") and visto["post"][1]["Authorization"] == "Bearer API tok"


def test_janela_em_pedacos_de_um_dia():
    ini = dt.datetime(2026, 8, 31, 17, 0, tzinfo=dt.timezone.utc)
    ped = sunop.pedacos_de_um_dia(ini, ini + dt.timedelta(days=3))
    assert len(ped) == 3 and ped[0] == (ini, ini + dt.timedelta(hours=24)) and ped[-1][1] == ini + dt.timedelta(days=3)
    assert sunop.pedacos_de_um_dia(ini, ini + dt.timedelta(minutes=30)) == [(ini, ini + dt.timedelta(minutes=30))]
    assert sunop.pedacos_de_um_dia(ini, ini) == []
    # reconciliacao comecando no quarto de hora: 24 h e uns minutos sao UM pedaco (um pedido por lote), nao dois
    assert sunop.pedacos_de_um_dia(ini, ini + dt.timedelta(hours=24, minutes=15)) == [(ini, ini + dt.timedelta(hours=24, minutes=15))]
    assert len(sunop.pedacos_de_um_dia(ini, ini + dt.timedelta(hours=24, minutes=16))) == 2


def test_fora_da_janela_solar_nao_registra_ingest_run():
    # Noite de 03/09: cada ciclo gravava 'falha' com "fora da janela solar" e o /healthz ficou em 503 a noite inteira.
    class DB:
        def registrar_ingest_run(self, *a, **k): raise AssertionError("noite nao e ciclo: nada a registrar")
    from gemeo.ingest.base import Disjuntor
    ing = sunop.IngestorSunOp.__new__(sunop.IngestorSunOp)
    ing.usinas = [type("U", (), {"id": 1, "tz": "America/Belem"})()]
    ing.cfg = type("C", (), {"janela_solar": ("05:40", "18:20")})(); ing._db = DB(); ing.conn = None; ing.fonte = "sunop"; ing.disjuntor = Disjuntor()
    assert ing.ciclo(agora=dt.datetime(2026, 9, 4, 2, 0, tzinfo=dt.timezone.utc)) == []      # 23:00 em Belem


# ── marca d'agua de cada grupo e reconciliacao (29/09/2026) ─────────────────────────────────────
# O defeito, medido no ingest_run e no acervo de 28/09: o grupo "lento" (tracker+string, de 60 em 60 min) pedia a
# marca d'agua da usina INTEIRA, que o "fino" (estacao+inversor, de 15 em 15 min) empurra. Cada corrida do lento
# buscava so ~40 min (ini 11:50Z na das 12:30Z, 12:50Z na das 13:31Z, 13:55Z na das 14:32Z): os quartos de hora
# :30 e :45 ficavam gravados pela metade (0,6-5,5 graus da SunOp) e a manha nunca voltava (28/09 comeca 08:45).
# Com banco de verdade e HTTP de mentira: o que se confere e o `start_time` que iria para a SunOp.
META = [{"pathname": p} for p in ("MRO100.ESTM.POA.IRAD", "MRO100.INV_1.MEDIDAS.P",
                                  "MRO100.INV_1.MEDIDAS.STR.I_PV1", "MRO100.TRK_1.MEDIDAS.POSAT")]


class _Resposta:
    status_code = 200
    text = ""
    def __init__(self, dado): self.dado = dado
    def json(self): return self.dado


class HttpGravador:
    """SunOp de mentira: guarda os parametros de cada POST e devolve um ponto por pathname, no inicio da janela (fica
    atras da marca e nao a move). `falhas` = quantos POSTs recusar antes de responder (29/09 de manha: ConnectionError
    as 10:07Z, 10:22Z e 10:37Z)."""
    def __init__(self, falhas: int = 0, vazias: int = 0):
        self.pedidos, self.falhas, self.vazias = [], falhas, vazias

    def post(self, url, params=None, json=None, **k):
        if self.falhas:
            self.falhas -= 1
            raise requests.ConnectionError("gridco-api.sunop.net recusou a conexao")
        self.pedidos.append(dict(params))
        if self.vazias:
            self.vazias -= 1
            return _Resposta([])
        return _Resposta([{"pathname": p, "timestamp": params["start_time"], "value": 1.0} for p in json["pathnames"]])


@pytest.fixture
def mro(conn, tmp_path):
    limpar_tudo(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO usina (codigo, nome, fonte, fonte_ref, tz) VALUES ('MRO100','MRO100','sunop','MRO100','America/Belem') RETURNING id")
        uid = cur.fetchone()[0]
    conn.commit()
    (tmp_path / "sunop_meta_MRO100.json").write_text(json.dumps(META), encoding="utf-8")   # metadata vem do disco
    cfg = type("C", (), {"cache_dir": tmp_path, "sunop_base": "http://x", "sunop_token": "t", "lote_pathnames": 600,
                         "teto_sunop_dia": 600, "janela_solar": ("05:40", "18:20"), "sobreposicao_min": 30})()
    u = UsinaRef(uid, "MRO100", "sunop", "MRO100", "America/Belem")
    sunop.IngestorSunOp(cfg, conn, [u], http=HttpGravador()).descobrir(u)                  # estacao, inversor, tracker, string
    with conn.cursor() as cur:
        cur.execute("SELECT tipo, id FROM equipamento WHERE usina_id=%s", (uid,))
        eq = dict(cur.fetchall())
    yield u, cfg, eq
    limpar_tudo(conn)


def _grava(conn, eq, tipo, medida, ts):
    db.upsert_leituras(conn, [(eq[tipo], medida, ts, 1.0)])


def _inicio_do_pedido(conn, mro, grupo, agora) -> str:
    """start_time (hora de Belem) do primeiro POST de uma corrida fora da reconciliacao do dia."""
    u, cfg, _ = mro
    http = HttpGravador()
    ing = sunop.IngestorSunOp(cfg, conn, [u], grupo=grupo, http=http)
    ing._reconciliado_em = tempo.dia_local(agora, u.tz)          # a do dia ja foi: esta corrida e incremental
    ing.ciclo(agora=agora)
    return http.pedidos[0]["start_time"]


def test_lento_busca_desde_a_marca_dos_trackers_e_strings_nao_da_usina(conn, mro):
    """28/09 13:31Z: o fino tinha gravado inversor ate 13:20Z; o ultimo quarto de hora de tracker era o de 12:30Z (09:30
    de Belem), gravado PARCIAL na corrida das 12:30Z. O lento tem de voltar a 12:00Z e regravar o 09:30 inteiro — pedia
    a partir de 09:50 (13:20Z - 30 min) e o 09:30 ficava com o primeiro minuto so."""
    _, _, eq = mro
    _grava(conn, eq, "inversor", "p_ac", dt.datetime(2026, 9, 28, 13, 20, tzinfo=UTC))
    _grava(conn, eq, "tracker", "angulo", dt.datetime(2026, 9, 28, 12, 30, tzinfo=UTC))
    assert _inicio_do_pedido(conn, mro, "lento", dt.datetime(2026, 9, 28, 13, 31, 28, tzinfo=UTC)) == "2026-09-28T09:00:00"


def test_fino_busca_desde_a_marca_da_estacao_e_dos_inversores(conn, mro):
    """O espelho: fino sem gravar desde 11:00Z (disjuntor, 403) e o lento em dia ate 13:30Z. Com a marca da usina o
    fino voltaria so ate 13:00Z e as duas horas de inversor ficariam de fora para sempre."""
    _, _, eq = mro
    _grava(conn, eq, "inversor", "p_ac", dt.datetime(2026, 9, 28, 11, 0, tzinfo=UTC))
    _grava(conn, eq, "tracker", "angulo", dt.datetime(2026, 9, 28, 13, 30, tzinfo=UTC))
    assert _inicio_do_pedido(conn, mro, "fino", dt.datetime(2026, 9, 28, 13, 40, tzinfo=UTC)) == "2026-09-28T07:30:00"


def test_grupo_que_nunca_gravou_nao_arrasta_a_janela_para_tres_dias(conn, mro):
    """Grupo sem leitura nenhuma tem marca None, e None e "primeiro ciclo: 3 dias". Como a janela e o lote sao COMUNS as
    usinas, uma so faria as quatro pedirem 3 dias a cada corrida — 18 pedidos por hora em vez de 6, na cota que e da
    plataforma tambem. A MTS100 tem 52 trackers que nunca mandaram nada (quem a segura sao as strings). Grupo que
    nunca gravou fica com a marca da usina, que e o que valia antes."""
    _, _, eq = mro
    agora = dt.datetime(2026, 9, 28, 13, 31, tzinfo=UTC)
    _grava(conn, eq, "inversor", "p_ac", dt.datetime(2026, 9, 28, 13, 20, tzinfo=UTC))
    ini = sunop.ts_utc(_inicio_do_pedido(conn, mro, "lento", agora), "America/Belem")
    assert dt.timedelta(0) < agora - ini <= dt.timedelta(hours=1)


def test_reconciliacao_das_03Z_vale_na_primeira_corrida_dentro_da_janela_solar(conn, mro):
    """03 UTC e meia-noite em Belem: o ciclo nao busca (fora da janela solar) e o runner da a reconciliacao por feita.
    De 03/09 a 29/09, nenhuma janela de 24 h nos 4.359 registros de ingest_run da SunOp. A do dia vai na primeira
    corrida dentro da janela — e a partir de um quarto de hora inteiro: o balde que comeca no meio sai parcial da SunOp
    e sobrescreveria o bom que ja estava no acervo."""
    u, cfg, eq = mro
    _grava(conn, eq, "tracker", "angulo", dt.datetime(2026, 9, 28, 21, 15, tzinfo=UTC))   # 18:15 de Belem, ontem
    http = HttpGravador()
    ing = sunop.IngestorSunOp(cfg, conn, [u], grupo="lento", http=http)
    assert ing.ciclo(agora=dt.datetime(2026, 9, 29, 3, 0, tzinfo=UTC), reconciliar=True) == [] and http.pedidos == []
    ing.ciclo(agora=dt.datetime(2026, 9, 29, 8, 47, 13, tzinfo=UTC))                      # 05:47:13 de Belem
    assert [p["start_time"] for p in http.pedidos] == ["2026-09-28T05:45:00"]             # 24 h, no quarto de hora, 1 pedido


def test_reconciliacao_uma_vez_por_dia_e_so_depois_de_buscar_de_verdade(conn, mro):
    """Corrida que nao chegou a SunOp nao conta como reconciliada. Depois da que deu certo, o resto do dia e
    incremental (marca - 30 min), senao seriam 24 h de payload a cada hora."""
    u, cfg, eq = mro
    _grava(conn, eq, "tracker", "angulo", dt.datetime(2026, 9, 28, 21, 15, tzinfo=UTC))
    http = HttpGravador(falhas=1)
    ing = sunop.IngestorSunOp(cfg, conn, [u], grupo="lento", http=http)
    ing.ciclo(agora=dt.datetime(2026, 9, 29, 10, 7, tzinfo=UTC))       # ConnectionError: nao reconciliou
    ing.ciclo(agora=dt.datetime(2026, 9, 29, 11, 15, tzinfo=UTC))      # reconcilia: 24 h
    ing.ciclo(agora=dt.datetime(2026, 9, 29, 12, 16, tzinfo=UTC))      # incremental: 21:15Z - 30 min
    assert [p["start_time"] for p in http.pedidos] == ["2026-09-28T08:15:00", "2026-09-28T17:45:00"]


class _BancoTravaUmaVez:
    """O modulo db de verdade, com o primeiro upsert levando 'database is locked'."""
    def __init__(self):
        self.travou = False

    def __getattr__(self, nome):
        return getattr(db, nome)

    def upsert_leituras(self, conn, linhas):
        if not self.travou:
            self.travou = True
            raise sqlite3.OperationalError("database is locked")
        return db.upsert_leituras(conn, linhas)


def test_reconciliacao_que_nao_gravou_fica_para_a_proxima(conn, mro):
    """Buscou, mas o upsert levou 'database is locked' (29/09: a fonte pg segurou o SQLite por horas). O dia NAO esta
    reconciliado: so conta como feito depois que as leituras entraram no banco."""
    u, cfg, eq = mro
    _grava(conn, eq, "tracker", "angulo", dt.datetime(2026, 9, 28, 21, 15, tzinfo=UTC))
    http = HttpGravador()
    ing = sunop.IngestorSunOp(cfg, conn, [u], grupo="lento", http=http)
    ing._db = _BancoTravaUmaVez()
    with pytest.raises(sqlite3.OperationalError):
        ing.ciclo(agora=dt.datetime(2026, 9, 29, 11, 15, tzinfo=UTC))   # buscou e nao gravou
    ing.ciclo(agora=dt.datetime(2026, 9, 29, 12, 16, tzinfo=UTC))       # tenta de novo: 24 h
    assert [p["start_time"] for p in http.pedidos] == ["2026-09-28T08:15:00", "2026-09-28T09:15:00"]


def test_reconciliacao_que_volta_vazia_fica_para_a_proxima(conn, mro):
    """200 com lista vazia (ou nao-200, que `_analog` tambem vira {}) nao e dia reconciliado: a proxima tenta de novo.
    Custa o mesmo numero de pedidos de uma corrida normal (24 h = um pedaco por lote)."""
    u, cfg, eq = mro
    _grava(conn, eq, "tracker", "angulo", dt.datetime(2026, 9, 28, 21, 15, tzinfo=UTC))
    http = HttpGravador(vazias=1)
    ing = sunop.IngestorSunOp(cfg, conn, [u], grupo="lento", http=http)
    ing.ciclo(agora=dt.datetime(2026, 9, 29, 11, 15, tzinfo=UTC))      # voltou vazia
    ing.ciclo(agora=dt.datetime(2026, 9, 29, 12, 16, tzinfo=UTC))      # tenta de novo: 24 h
    assert [p["start_time"] for p in http.pedidos] == ["2026-09-28T08:15:00", "2026-09-28T09:15:00"]
