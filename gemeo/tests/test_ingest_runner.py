# gemeo/tests/test_ingest_runner.py
"""O laco nunca morre por excecao da fonte e para quando o Event manda. Ritmo em minutos, do config."""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gemeo.ingest import runner  # noqa: E402


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


def test_garantir_usinas_cria_as_do_piloto_uma_vez(conn):
    import types
    from semear import limpar_tudo
    limpar_tudo(conn)
    cfg = types.SimpleNamespace(usinas_piloto=("MRO100", "MAB100"), usinas_detalhe={"MRO100": {"fonte": "sunop", "tz": "America/Belem", "nome": "Mae do Rio"}})
    assert runner.garantir_usinas(conn, cfg) == 2
    assert runner.garantir_usinas(conn, cfg) == 0                    # idempotente
    us = {u.codigo: u for u in runner.usinas_do_piloto(conn, cfg.usinas_piloto)}
    assert us["MRO100"].fonte == "sunop" and us["MRO100"].tz == "America/Belem" and us["MAB100"].fonte_ref == "MAB100"
    limpar_tudo(conn)


def test_montar_inclui_a_api_pv_quando_ha_usina_dessa_fonte():
    cfg = type("C", (), {"ritmo_min": {"pg": 15, "sunop_fino": 15, "sunop_lento": 60, "cadastro": 30, "apipv": 15}, "usinas_piloto": ("Araputanga",),
                        "sobreposicao_min": 30, "cache_dir": ".", "sunop_base": "", "sunop_token": "", "lote_pathnames": 600, "teto_sunop_dia": 600,
                        "janela_solar": ("05:40", "18:20"), "bd_api_base": "", "bd_api_token": "", "apipv_base": "http://x", "pv_oem_usuario": "u",
                        "pv_oem_senha": "s", "usinas_detalhe": {}})()
    from gemeo.core.modelos import UsinaRef
    us = [UsinaRef(3, "Araputanga", "apipv", "18771898", "America/Cuiaba")]
    itens = runner.montar(cfg, conn_gemeo=None, conn_fonte=None, usinas=us)
    assert {(r, m) for r, _, m in itens} == {("apipv", 15), ("cadastro", 30)}
    assert next(i for r, i, _ in itens if r == "apipv").fonte == "apipv"


def test_usina_da_api_pv_sem_credencial_falha_nomeando_as_chaves():
    """Segredo ausente e erro em voz alta ANTES de subir as threads — a plataforma perdeu horas com credencial vazia
    virando token vazio em silencio. Sem usina apipv no piloto, nada e exigido."""
    import types
    import pytest
    from gemeo.core.config import SegredoAusente
    from gemeo.core.modelos import UsinaRef
    ara = UsinaRef(3, "Araputanga", "apipv", "18771898", "America/Cuiaba")
    mro = UsinaRef(1, "MRO100", "sunop", "MRO100", "America/Belem")
    with pytest.raises(SegredoAusente) as e:
        runner.exigir_credenciais_apipv(types.SimpleNamespace(pv_oem_usuario="", pv_oem_senha=""), [mro, ara])
    assert "PV_OEM_USERNAME" in str(e.value) and "PV_OEM_PASSWORD" in str(e.value)
    runner.exigir_credenciais_apipv(types.SimpleNamespace(pv_oem_usuario="", pv_oem_senha=""), [mro])
    runner.exigir_credenciais_apipv(types.SimpleNamespace(pv_oem_usuario="u", pv_oem_senha="s"), [mro, ara])


def test_laco_desfaz_a_transacao_quando_o_ciclo_falha():
    """13/09/2026 12:33: a fonte plat falhou (IntegrityError) e a conexao da thread ficou com a transacao ABERTA durante os
    15 min de espera — 'database is locked' no apipv, no pg e em 4 usinas do modelar. Ciclo que falha tem de dar rollback."""
    class Conn:
        def __init__(self): self.rollbacks = 0
        def rollback(self): self.rollbacks += 1
    class IngFalha:
        def __init__(self): self.conn = Conn(); self.fonte = "x"
        def ciclo(self, reconciliar=False): raise RuntimeError("CHECK constraint failed")
    parar = threading.Event(); ing = IngFalha()
    threading.Timer(0.25, parar.set).start()
    runner.laco("x", ing, minutos=0.001, parar=parar)
    assert ing.conn.rollbacks >= 1
