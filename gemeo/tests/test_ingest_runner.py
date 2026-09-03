# gemeo/tests/test_ingest_runner.py
"""O laco nunca morre por excecao da fonte e para quando o Event manda. Ritmo em minutos, do config."""
import threading
from gemeo.ingest import runner


class Ing:
    def __init__(self, falha=False): self.n = 0; self.falha = falha; self.fonte = "x"
    def ciclo(self, reconciliar=False):
        self.n += 1
        if self.falha: raise RuntimeError("fonte fora")


def test_laco_para_no_event_e_sobrevive_a_excecao():
    parar = threading.Event(); ing = Ing(falha=True)
    def _depois(): parar.set()
    t = threading.Timer(0.3, _depois); t.start()
    runner.laco("x", ing, minutos=0.001, parar=parar)     # 0,001 min = 60 ms entre ciclos
    assert ing.n >= 2                                      # continuou apos a excecao


def test_montar_usa_o_ritmo_do_config():
    cfg = type("C", (), {"ritmo_min": {"pg": 15, "sunop_fino": 15, "sunop_lento": 60, "cadastro": 30}, "usinas_piloto": ("MRO100",),
                        "sobreposicao_min": 30, "cache_dir": ".", "sunop_base": "", "sunop_token": "", "lote_pathnames": 600, "teto_sunop_dia": 600, "janela_solar": ("05:40","18:20"), "bd_api_base": "", "bd_api_token": ""})()
    from gemeo.core.modelos import UsinaRef
    us = [UsinaRef(1, "MRO100", "sunop", "MRO100", "America/Belem"), UsinaRef(2, "Santarem 1", "pg", "10", "America/Belem")]
    itens = runner.montar(cfg, conn_gemeo=None, conn_fonte=None, usinas=us)
    assert {(r, m) for r, _, m in itens} == {("pg", 15), ("sunop_fino", 15), ("sunop_lento", 60), ("cadastro", 30)}
