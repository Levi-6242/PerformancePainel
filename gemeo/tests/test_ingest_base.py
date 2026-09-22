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


# ── status por FRESCOR, nao por total fabricado (21/09/2026) ────────────────────────────────────
# Ate aqui o status saia de `n_escrito / esperado`, com o esperado inventado por formula. Medido no
# banco real: 480 de 480 ciclos do PG diziam "parcial" com a fonte saudavel, e o `saude()` tinha
# aprendido a ignorar 'parcial' por isso. Agora o que decide e o atraso da leitura mais nova.
def _busca(atraso_min, n=9, **kw):
    """Busca cujo carimbo mais novo esta `atraso_min` antes do fim da janela (12:00)."""
    ts = dt.datetime(2026, 9, 3, 12, 0, tzinfo=UTC) - dt.timedelta(minutes=atraso_min)
    return base.Busca(leituras=[(7, "p_ac", ts, 1.0)] * n, **kw)


def test_dado_fresco_e_ok_mesmo_com_poucas_linhas():
    """Tres linhas frescas sao uma fonte SAUDAVEL de madrugada. A regra antiga chamava de 'parcial'
    porque esperava centenas — e era exatamente o caso do PG."""
    b = BancoFalso(); ing = _ing(_busca(10, n=3, n_requisicoes=2), b)
    ing.ciclo(agora=dt.datetime(2026, 9, 3, 12, 0, tzinfo=UTC))
    r = b.runs[0]
    assert r["status"] == "ok" and r["n_requisicoes"] == 2 and len(b.leituras) == 3


def test_muita_linha_mas_velha_e_parcial():
    """O inverso, que a regra antiga NAO pegava: 900 linhas de 20 h atras dao 'cobertura' alta e
    escondem uma usina muda. Foi o caso da Araçoiaba da Serra, 45 h sem dado novo."""
    b = BancoFalso(); ing = _ing(_busca(20 * 60, n=900), b)
    ing.ciclo(agora=dt.datetime(2026, 9, 3, 12, 0, tzinfo=UTC))
    assert b.runs[0]["status"] == "parcial" and b.runs[0]["cobertura"] == 0.0


def test_o_corte_padrao_e_de_180_minutos():
    """O numero saiu de medicao: as 13 usinas sadias do PG estavam em <= 83 min e as 5 mudas em
    743 min ou mais. Mudar isso por acidente reabre o problema dos dois lados."""
    assert base.ATRASO_OK_MIN == 180.0
    assert base.avaliar([(7, "p_ac", dt.datetime(2026, 9, 3, 9, 0, tzinfo=UTC), 1.0)],
                        dt.datetime(2026, 9, 3, 12, 0, tzinfo=UTC))[0] == "ok"        # 180 min exatos
    assert base.avaliar([(7, "p_ac", dt.datetime(2026, 9, 3, 8, 59, tzinfo=UTC), 1.0)],
                        dt.datetime(2026, 9, 3, 12, 0, tzinfo=UTC))[0] == "parcial"   # 181 min


def test_cobertura_virou_frescor_e_tem_UM_significado():
    fim = dt.datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    na_borda = base.avaliar([(7, "p_ac", fim, 1.0)], fim)
    meio = base.avaliar([(7, "p_ac", fim - dt.timedelta(minutes=90), 1.0)], fim)
    assert na_borda == ("ok", 1.0) and meio[0] == "ok" and abs(meio[1] - 0.5) < 1e-9


def test_fonte_com_cadencia_propria_pode_apertar_o_corte():
    """apipv entrega a cada 5 min; 3 h de atraso ali e outra coisa que 3 h no PG."""
    fim = dt.datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    leit = [(7, "p_ac", fim - dt.timedelta(minutes=45), 1.0)]
    assert base.avaliar(leit, fim)[0] == "ok"
    assert base.avaliar(leit, fim, tolerancia_min=30)[0] == "parcial"


def test_sem_leitura_nao_inventa_frescor():
    assert base.avaliar([], dt.datetime(2026, 9, 3, 12, 0, tzinfo=UTC)) == ("falha", 0.0)
    assert base.atraso_da_busca([], dt.datetime(2026, 9, 3, 12, 0, tzinfo=UTC)) is None


def test_carimbo_no_futuro_nao_vira_atraso_negativo():
    """Fonte com relogio adiantado daria frescor > 1 e, pior, atraso negativo em qualquer conta."""
    fim = dt.datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    assert base.atraso_da_busca([(7, "p_ac", fim + dt.timedelta(minutes=5), 1.0)], fim) == 0.0


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


def test_sentinela_de_sensor_nao_vira_irradiancia():
    """-999 no POA da Santarem (PostgreSQL) e -666 no GHI da MAB100 (SunOp) sao codigo de erro do equipamento.
    Gravados como medida, derrubavam o gate: a razao POA/GHI da Santarem 1 deu -0,46 e o esperado do dia foi a zero."""
    from gemeo.ingest.base import valor_valido
    assert not valor_valido("poa", -999.0) and not valor_valido("ghi", -666.0)
    assert not valor_valido("poa", None)
    assert valor_valido("ghi", -1.7)          # offset termico do piranometro a noite e leitura de verdade
    assert valor_valido("poa", 0.0) and valor_valido("poa", 943.2)
    assert valor_valido("p_ac", -999.0)       # so irradiancia tem essa regra; potencia negativa e consumo real
