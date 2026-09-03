# gemeo/tests/test_ingest_base.py
"""O ciclo e onde as regras de honestidade moram: ciclo vazio grava falha e nada mais; disjuntor aberto
nem chama a fonte; excecao vira ingest_run com o erro em texto. Testado com dublês — sem banco."""
import datetime as dt
from gemeo.core.modelos import UsinaRef
from gemeo.ingest import base

UTC = dt.timezone.utc
U = UsinaRef(id=1, codigo="T1", fonte="pg", fonte_ref="1", tz="America/Belem")


class BancoFalso:
    def __init__(self):
        self.leituras, self.runs, self.marca = [], [], None
    def marca_dagua(self, conn, usina_id): return self.marca
    def upsert_leituras(self, conn, linhas): ls = list(linhas); self.leituras += ls; return len(ls)
    def registrar_ingest_run(self, conn, **kw): self.runs.append(kw); return len(self.runs)


class Falso(base.Ingestor):
    fonte = "falso"
    def __init__(self, resposta, *a, **kw):
        super().__init__(*a, **kw); self.resposta = resposta; self.chamadas = 0
    def descobrir(self, usina): pass
    def buscar(self, usina, ini, fim):
        self.chamadas += 1
        if isinstance(self.resposta, Exception): raise self.resposta
        return self.resposta


def _ing(resposta, banco):
    ing = Falso(resposta, cfg=type("C", (), {"sobreposicao_min": 30})(), conn=None, usinas=[U])
    ing._db = banco
    return ing


def test_busca_vazia_grava_falha_e_nenhuma_leitura():
    b = BancoFalso(); ing = _ing(base.Busca(leituras=[]), b)
    ing.ciclo(agora=dt.datetime(2026, 9, 3, 12, 0, tzinfo=UTC))
    assert b.leituras == [] and b.runs[0]["status"] == "falha" and b.runs[0]["cobertura"] == 0


def test_busca_boa_grava_e_mede_cobertura():
    ts = dt.datetime(2026, 9, 3, 11, 0, tzinfo=UTC)
    b = BancoFalso(); ing = _ing(base.Busca(leituras=[(7, "p_ac", ts, 1.0)] * 9, esperadas=10, n_requisicoes=2), b)
    ing.ciclo(agora=dt.datetime(2026, 9, 3, 12, 0, tzinfo=UTC))
    r = b.runs[0]
    assert len(b.leituras) == 9 and r["status"] == "ok" and abs(r["cobertura"] - 0.9) < 1e-9 and r["n_requisicoes"] == 2


def test_cobertura_baixa_e_parcial():
    ts = dt.datetime(2026, 9, 3, 11, 0, tzinfo=UTC)
    b = BancoFalso(); ing = _ing(base.Busca(leituras=[(7, "p_ac", ts, 1.0)] * 5, esperadas=10), b)
    ing.ciclo(agora=dt.datetime(2026, 9, 3, 12, 0, tzinfo=UTC))
    assert b.runs[0]["status"] == "parcial"


def test_excecao_vira_run_com_erro():
    b = BancoFalso(); ing = _ing(RuntimeError("timeout na fonte"), b)
    ing.ciclo(agora=dt.datetime(2026, 9, 3, 12, 0, tzinfo=UTC))
    assert b.runs[0]["status"] == "falha" and "timeout" in b.runs[0]["erro"]


def test_disjuntor_aberto_nao_chama_a_fonte():
    b = BancoFalso(); ing = _ing(base.Busca(leituras=[]), b)
    ing.disjuntor.abrir("403 da borda")
    ing.ciclo(agora=dt.datetime(2026, 9, 3, 12, 0, tzinfo=UTC))
    assert ing.chamadas == 0 and b.runs[0]["erro"].startswith("disjuntor")


def test_janela_parte_da_marca_menos_sobreposicao():
    b = BancoFalso(); b.marca = dt.datetime(2026, 9, 3, 11, 45, tzinfo=UTC)
    vistas = {}
    class Espia(Falso):
        def buscar(self, usina, ini, fim): vistas["ini"] = ini; return base.Busca(leituras=[])
    ing = Espia(None, cfg=type("C", (), {"sobreposicao_min": 30})(), conn=None, usinas=[U]); ing._db = b
    ing.ciclo(agora=dt.datetime(2026, 9, 3, 12, 0, tzinfo=UTC))
    assert vistas["ini"] == dt.datetime(2026, 9, 3, 11, 15, tzinfo=UTC)
