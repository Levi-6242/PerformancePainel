# -*- coding: utf-8 -*-
"""A Alves Lima (Morada Nova) no tempo real (Levi, 19/10/2026: "inclua a usina morada nova cliente Alves Lima no tempo
real!").

A fonte `alveslima` (conta oem@ da API PV, plant_id 18766373) já tinha a aba no Monitoramento, mas nunca esteve no
`_portfolio_rollup`: o card da Entrada nasceria vazio e o Painel NOC não a via. Ela entra no rollup como a SEMP (só o
cache, nenhuma busca nova), com o rótulo "Alves Lima", e obedece às Fontes do tempo real pela fonte `alveslima`."""
import app

MORADA = {"usina": "Morada Nova", "plant_id": 18766373, "strings_ativas": 128, "str_esp": 128, "diferenca": 0,
          "qtd_inversores": 8, "inv_esp": 8, "inv_off": 0, "pot_med": 900.0, "ultima_leitura": "2026-10-19 11:55:00",
          "nome_api": "Morada Nova", "depara_fonte": "alveslima"}


def _rollup(monkeypatch, linhas_alveslima):
    vazio = {"payload": {"rows": []}}
    for nome in ("_cache", "_sunop_cache", "_axis_cache", "_se_cache", "_semp_cache", "_2capi_cache", "_gy_cache",
                 "_sal_cache"):
        monkeypatch.setattr(app, nome, dict(vazio))
    monkeypatch.setattr(app, "_alveslima_cache", {"payload": {"rows": linhas_alveslima}})
    monkeypatch.setattr(app, "INV_PADRAO_PLANTAS", set())
    monkeypatch.setattr(app, "USINA_GRUPO", {"Morada Nova": "Morada Nova", "MORADA NOVA": "Morada Nova"})
    monkeypatch.setattr(app, "_pg_get_snapshot", lambda force=False: ([], None))
    monkeypatch.setattr(app, "_usinas_desligadas_marcas", lambda: {})
    monkeypatch.setattr(app, "_religamentos_abertos_usina", lambda: {})
    monkeypatch.setattr(app, "_etm_leitura_por_pid", lambda: {})
    monkeypatch.setattr(app, "_poa_atual_por_pid", lambda: {})
    return {u["usina"]: u for u in app._portfolio_rollup()}


def test_a_morada_nova_entra_no_rollup_como_alves_lima(monkeypatch, freeze_now):
    freeze_now("2026-10-19 12:00:00")
    u = _rollup(monkeypatch, [dict(MORADA)])["Morada Nova"]
    assert u["fonte"] == "Alves Lima" and u["plant_id"] == 18766373
    assert u["str_esp"] == 128 and u["qtd_inversores"] == 8


def test_tirada_nas_fontes_do_tempo_real_ela_sai_do_rollup(monkeypatch, freeze_now):
    freeze_now("2026-10-19 12:00:00")
    perguntas = []

    def cob(fonte, chave):
        perguntas.append((fonte, chave))
        return fonte != "alveslima"

    monkeypatch.setattr(app, "_cob_entra", cob)
    assert "Morada Nova" not in _rollup(monkeypatch, [dict(MORADA)])
    assert ("alveslima", 18766373) in perguntas            # perguntou pela fonte dela, não pela "Alves Lima" do rótulo


def test_sem_o_cache_dela_nada_quebra(monkeypatch, freeze_now):
    freeze_now("2026-10-19 12:00:00")
    monkeypatch.setattr(app, "_alveslima_cache", {"payload": None, "ts": 0.0})
    assert _rollup(monkeypatch, []) == {}


def test_o_pr_do_diagnostico_usa_a_conta_que_enxerga_a_usina(monkeypatch):
    """O Painel NOC abre o Diagnóstico da Morada Nova com fonte=pv, e o PR do dia ia com o token da conta principal: no
    servidor, em 19/10/2026, Tucano e Araputanga voltavam "Invalid id" (502, "PR do dia não respondeu")."""
    usados = []
    monkeypatch.setattr(app, "_pv_pr_cache", {"detail": {}})
    monkeypatch.setattr(app, "get_token", lambda: "principal")
    monkeypatch.setattr(app, "get_token_oem", lambda: "oem")
    monkeypatch.setattr(app, "get_plants", lambda token, force=False: [{"id": 18766373, "nome": "Morada Nova"},
                                                                         {"id": 53241, "nome": "Ceilandia 1.1 (89)"}])
    monkeypatch.setattr(app, "_pv_pr_collect", lambda token, plant: usados.append((plant["id"], token)) or {"falha": "x"})
    with app.app.test_request_context():
        app.api_pv_pr_plant(18766373)
        app.api_pv_pr_plant(53241)
    assert usados == [(18766373, "oem"), (53241, "principal")]
