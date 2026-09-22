# -*- coding: utf-8 -*-
"""Fase 4: a plataforma lendo curva do acervo do gêmeo em vez da API da SunOp (21/09/2026).

**O número.** `/data/v2/usage/me` da SunOp: 162.892 requisições de 01 a 20/09 contra cota de
100.000/mês — saldo zero desde o dia 12, US$ 31,45 cobrados, e num servidor 24 h a projeção passa
de 400 mil. O gêmeo ingere as MESMAS medidas das mesmas usinas por **85 requisições/dia**, porque
guarda em vez de re-perguntar.

**A equivalência foi MEDIDA antes de ligar**, contra a API real, MRO100 em 20/09, 20 trackers:
95 de 96 pontos idênticos por série. O único divergente é sempre 20:30 UTC (17:30 em Belém, o
pôr do sol), com ~2,4° — é o dado que a SunOp ingere ATRASADO e que chega depois de o gêmeo já ter
gravado aquele slot. Mesmo atraso que motivou a sobreposição de 30 min na busca incremental.

Três enganos no caminho, que este arquivo registra para ninguém repetir:
  1. comparar sem alinhar o FUSO — a SunOp responde em hora da usina (`use_plant_timezone`) e o
     gêmeo grava em UTC; em tracker, 3 h de deslocamento viram 66° de diferença;
  2. comparar sem alinhar o PERÍODO — o gêmeo grava tracker com `period=15m` e a SunOp devolvia
     10m por padrão: 4.680 pontos contra 1.920;
  3. supor que a resposta vem aninhada por série — ela é PLANA, um item por ponto com `pathname`.
"""
import app


def test_le_do_gemeo_e_so_pede_a_sunop_o_que_faltou(monkeypatch):
    """O ganho todo está aqui: o que o gêmeo atende não vira requisição na SunOp."""
    monkeypatch.setattr(app, "GEMEO_CURVA_ATIVO", True)      # a suíte desliga por padrão (conftest)
    servido = {"MRO100.TRK_1.MEDIDAS.POSAT": [["2026-09-20T12:00:00+00:00", 10.5]]}
    monkeypatch.setattr(app, "_gemeo_curva",
                        lambda pns, ini, fim: {"series": servido, "nao_atendidos": ["X.TRK_9.MEDIDAS.POSAT"]})
    pedidos = []

    def _sunop_falso(pathnames, start, end, inst="gridco", period=None):
        pedidos.append(list(pathnames))
        return {p: [("2026-09-20 12:00:00", 1.0)] for p in pathnames}

    monkeypatch.setattr(app, "_sunop_analog_history_api", _sunop_falso)
    r = app._sunop_analog_history(["MRO100.TRK_1.MEDIDAS.POSAT", "X.TRK_9.MEDIDAS.POSAT"],
                                  "2026-09-20 00:00:00", "2026-09-21 00:00:00")
    assert pedidos == [["X.TRK_9.MEDIDAS.POSAT"]], f"só o não-atendido podia ir à SunOp: {pedidos}"
    assert len(r["MRO100.TRK_1.MEDIDAS.POSAT"]) == 1 and r["X.TRK_9.MEDIDAS.POSAT"]


def test_gemeo_fora_do_ar_nao_derruba_nem_atrasa(monkeypatch):
    """O gêmeo é OPCIONAL no caminho. Se ele cair, a plataforma busca tudo na SunOp como sempre —
    nunca o contrário, que seria trocar uma dependência por duas."""
    monkeypatch.setattr(app, "GEMEO_CURVA_ATIVO", True)

    def _explode(pns, ini, fim):
        raise RuntimeError("gemeo fora")
    monkeypatch.setattr(app, "_gemeo_curva", _explode)
    monkeypatch.setattr(app, "_sunop_analog_history_api",
                        lambda pathnames, start, end, inst="gridco", period=None: {p: [("t", 1.0)] for p in pathnames})
    r = app._sunop_analog_history(["MRO100.TRK_1.MEDIDAS.POSAT"], "2026-09-20 00:00:00", "2026-09-21 00:00:00")
    assert r["MRO100.TRK_1.MEDIDAS.POSAT"] == [("t", 1.0)]


def test_desligado_por_configuracao_nem_tenta(monkeypatch):
    """Interruptor para a segunda-feira: com `GEMEO_CURVA=0` o caminho novo some inteiro, sem
    precisar reverter código no dia do deploy."""
    monkeypatch.setattr(app, "GEMEO_CURVA_ATIVO", False)
    tentou = []
    monkeypatch.setattr(app, "_gemeo_curva", lambda pns, ini, fim: tentou.append(1) or {"series": {}, "nao_atendidos": []})
    monkeypatch.setattr(app, "_sunop_analog_history_api",
                        lambda pathnames, start, end, inst="gridco", period=None: {p: [] for p in pathnames})
    app._sunop_analog_history(["MRO100.TRK_1.MEDIDAS.POSAT"], "2026-09-20 00:00:00", "2026-09-21 00:00:00")
    assert tentou == []
