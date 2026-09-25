# -*- coding: utf-8 -*-
"""União na 2C (Levi, 25/09/2026: "adicione a usina União em 2C!").

Ela está na conta oem@ da API PV — a mesma da Araputanga, da Sete Lagoa e da Tupi Paulista — como "União " (id
18772125, 2.162 kWp, instalada em 22/09/2026); a conta principal não a enxerga. Medido às 15h do dia: 6 inversores com
28 Ipv cada (18 com corrente), ~905 leituras no dia, a última de 15:00. No cadastro ela é "União 1 e 2" (Info Geral:
cliente 2C, Piauí, 4,46 MWp, 12 inversores) — o caso da "Sete Lagoa" de novo: sem a ponte do nome, a usina não achava o
cliente e o card da 2C na Entrada a descartava. O Equipamentos ainda não tem os inversores dela: sem esperadas, a linha
mostra as strings sem julgar déficit, e o drill mostra o inversor pelo id (a conta oem@ não dá nome, e o de-para só
vale fechado POR VALOR — PV_INV_NOMES —, nunca pela ordem dos ids).
"""
import app

UNIAO = 18772125


def test_uniao_e_da_fonte_2capi_e_vai_pela_conta_oem():
    assert UNIAO in app.PV_FONTES["2capi"] and app._pv_fonte_de(UNIAO) == "2capi" and app._pv_is_oem(UNIAO)


def test_as_outras_tres_seguem_na_2c():
    assert {18771898, 18771901, 18750925} <= app.PV_FONTES["2capi"]


def test_o_nome_da_api_vira_o_do_cadastro(monkeypatch):
    monkeypatch.setattr(app, "USINA_DISPLAY", {"União 1 e 2": "União 1 e 2"})
    assert app.nome_usina(UNIAO, "União ") == "União 1 e 2", "a API escreve 'União ' (com espaço no fim)"


def test_o_cadastro_da_uniao_vale_para_a_usina_da_api(monkeypatch):
    """No dia em que o Equipamentos ganhar as linhas da União (esperadas, nomes), elas valem para a usina da API sem
    mudar nada aqui — a mesma ponte da Sete Lagoa (_aplica_alias_api_cadastro)."""
    for m in ("ESPERADO_INV", "EQUIP_NAMES", "POWER_INV", "USINA_DISPLAY"):
        monkeypatch.setattr(app, m, {})
    monkeypatch.setattr(app, "ESPERADO", {"União 1 e 2": {"inv_esp": 6, "str_esp": 108}})
    monkeypatch.setattr(app, "FULL_OM", {"União 1 e 2"})
    monkeypatch.setattr(app, "STRING_BOX", set())
    app._aplica_alias_api_cadastro()
    assert app.ESPERADO["União"] == {"inv_esp": 6, "str_esp": 108} and "União" in app.FULL_OM


def test_os_trackers_da_uniao_vem_pela_aba_da_2c():
    """Como as outras três: fora da varredura da Thopen PV (não duplica) e dentro da aba da 2C, cujo detalhe vai à API."""
    assert app._pv_trk_fora(UNIAO)
    assert app._owen_id_da_api_pv(str(UNIAO)) == UNIAO
