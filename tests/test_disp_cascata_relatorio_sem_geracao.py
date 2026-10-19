# -*- coding: utf-8 -*-
"""A "Disponibilidade UFV" da cascata do Gerencial e do Criador de Relatório não depende da geração (Levi, 15/10/2026:
"a geração não deve afetar a disponibilidade, isso não faz sentido, disponibilidade é full Fracttal isolada da geração").

Até 15/10 as duas dividiam as horas de OS pelos dias QUE TINHAM GERAÇÃO na série (`n`): um dia sem geração no BD tirava
12 h do divisor e derrubava a disponibilidade. Agora o divisor são os dias fechados do período; a perda em energia
(que é da geração) segue pelos dias da série."""
import app
from test_trk_frota_total import overview, usina_controlada  # noqa: F401  (fixtures)

OS_DE_UM_DIA = [{"folio": 1, "tipo": "Religamento", "evento": "2026-09-05 06:00", "evento_ts": None, "fim_ts": None,
                 "horas_solares": 12.0}]


def _com_os(monkeypatch):
    monkeypatch.setattr(app, "_frac_usina_ent", lambda *a, **k: {"site": "TesteCo - Usina X - SP"})
    monkeypatch.setattr(app, "_frac_os_filtradas", lambda site, mes, falhas=None: list(OS_DE_UM_DIA))


def _so_os_dias(monkeypatch, dias):
    """A série do mês com geração só em `dias` (o resto sem leitura, como o BD que ainda não fechou o dia)."""
    with app.app.app_context():
        serie = app.api_g_diario().get_json()
    serie["pontos"] = [p for p in serie["pontos"] if p["dia"] in dias]
    monkeypatch.setattr(app, "api_g_diario", lambda: app.jsonify(serie))


def test_cascata_divide_pelos_dias_do_mes_e_nao_pelos_dias_com_geracao(usina_controlada, monkeypatch):
    # 12 h de OS de usina inteira em setembro: 1 − 12 ÷ (12 × 30) = 96,67%, com a série inteira ou só com 20 dias
    usina_controlada("Usina X", "pv", [], [])
    _com_os(monkeypatch)
    cheio = app._cascata_usina("", "Usina X", 2026, 9)
    _so_os_dias(monkeypatch, range(1, 21))
    falha = app._cascata_usina("", "Usina X", 2026, 9)
    assert cheio["ok"] and falha["ok"] and falha["dias"] == 20                  # a energia segue pelos dias da série
    assert cheio["disponibilidade_ufv"] == falha["disponibilidade_ufv"] == 0.9667   # até 15/10: 0,95 com 20 dias


def test_relatorio_divide_pelos_dias_do_periodo_e_nao_pelos_dias_com_geracao(usina_controlada, monkeypatch):
    usina_controlada("Usina X", "pv", [], [])
    _com_os(monkeypatch)
    cheio = app._relatorio_build("Usina X", "2026-09-01", "2026-09-30")
    _so_os_dias(monkeypatch, range(1, 21))
    falha = app._relatorio_build("Usina X", "2026-09-01", "2026-09-30")
    assert cheio["ok"] and falha["ok"]
    assert cheio["disponibilidade_ufv"] == falha["disponibilidade_ufv"] == 0.9667


def test_falta_de_comunicacao_nao_entra_na_cascata_nem_no_relatorio(usina_controlada, monkeypatch):
    # Levi, 19/10/2026: "a falta de comunicação não deve entrar no cálculo de disponibilidade"
    usina_controlada("Usina X", "pv", [], [])
    monkeypatch.setattr(app, "_frac_usina_ent", lambda *a, **k: {"site": "TesteCo - Usina X - SP"})
    monkeypatch.setattr(app, "_frac_os_filtradas", lambda site, mes, falhas=None: [
        {**OS_DE_UM_DIA[0], "descricao": "[THPN-BWK100] - Verificação de comunicação do THPN-BWK100"}])
    c = app._cascata_usina("", "Usina X", 2026, 9)
    r = app._relatorio_build("Usina X", "2026-09-01", "2026-09-30")
    assert c["disponibilidade_ufv"] == 1.0 and c["os"]["qtd"] == 0
    assert r["disponibilidade_ufv"] == 1.0


def test_cascata_do_mes_que_ainda_nao_fechou_um_dia_sai_sem_disponibilidade(usina_controlada, monkeypatch):
    # mês futuro (nenhum dia fechado): "—" na tela, nunca 0% nem 100%
    usina_controlada("Usina X", "pv", [], [])
    _com_os(monkeypatch)
    d = app._cascata_usina("", "Usina X", 2099, 9)
    assert d["ok"] and d["disponibilidade_ufv"] is None
