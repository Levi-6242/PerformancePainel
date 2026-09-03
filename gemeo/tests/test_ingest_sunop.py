# gemeo/tests/test_ingest_sunop.py
"""Metadata real (34 itens da MRO100) → equipamentos; lote atravessando usinas; teto e 403 → disjuntor.
HTTP e banco sao dubles: o que se testa e o contrato, nao a SunOp."""
import datetime as dt
import json
from pathlib import Path
from gemeo.ingest import sunop

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
