# gemeo/tests/sintetico.py
"""Grade sintetica pequena para os testes de invariantes do modelo: 2 inversores, 3 trackers (o 2003 sem
inversor), 4 strings no inversor 1001, 8 slots por dia a partir das 09:00 de Belem. Valores redondos de
proposito — o teste enxerga a regra, nao o ruido. `dias=3` empilha 29, 30 e 31/08 (para o 'abaixo dos pares')."""
import pandas as pd

from gemeo.core.modelos import UsinaRef
from gemeo.modelar.grade import Grade


def grade_sintetica(n: int = 8, dias: int = 1, poa: float = 800.0, ghi: float = 700.0) -> Grade:
    partes = [pd.date_range(f"2026-08-{28 + k:02d}T12:00", periods=n, freq="15min", tz="UTC") for k in range(4 - dias, 4)]
    idx = partes[0]
    for p in partes[1:]:
        idx = idx.union(p)
    est = pd.DataFrame({"poa": poa, "ghi": ghi, "temp_modulo": 45.0, "temp_ar": 30.0}, index=idx)
    inv_p = pd.DataFrame({1001: 180.0, 1002: 180.0}, index=idx)
    inv_e = pd.DataFrame(index=idx)
    trk = pd.DataFrame({2001: 20.0, 2002: 20.0, 2003: 20.0}, index=idx)   # mediana da frota = 20; o teste desloca um
    alvo = trk.copy()
    strs = pd.DataFrame({3101: 8.0, 3102: 8.0, 3103: 8.0, 3104: 8.0}, index=idx)
    pai = {3101: 1001, 3102: 1001, 3103: 1001, 3104: 1001, 2001: 1001, 2002: 1002}
    tipo = {1001: "inversor", 1002: "inversor", 2001: "tracker", 2002: "tracker", 2003: "tracker",
            3101: "string", 3102: "string", 3103: "string", 3104: "string", 1: "estacao"}
    usina = UsinaRef(id=0, codigo="SINT", fonte="sunop", fonte_ref="", tz="America/Belem", kwp=555.36, kw_ac=400.0, lat=-2.05, lon=-47.55)
    atributos = {1001: {"kwp": 277.68, "kw_ac": 200.0}, 1002: {"kwp": 277.68, "kw_ac": 200.0}}
    return Grade(usina, idx, est, inv_p, inv_e, trk, alvo, strs, pai, tipo, atributos, {})
