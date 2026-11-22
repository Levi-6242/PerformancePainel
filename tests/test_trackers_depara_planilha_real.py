# -*- coding: utf-8 -*-
"""A planilha VERSIONADA do de-para de trackers (plataforma/trackers_depara.xlsx), com os casos reais que a fizeram crescer.

22/11/2026, Levi: "pode fazer as duas, sobe" — as usinas que não tinham de-para (2C, GreenYellow, Santa Bárbara I) entram
onde a contagem da fonte bate com a do Fracttal, tudo marcado (CONFIRMAR) ("a confirmar vai marcado"). O caso que fechou
a regra da 2C: os 4 chamados abertos da Sete Lagoas (SLG200-ETKR38/49/51/58.200) são os Tracker 1.38/1.49/1.51/1.58 que
estavam parados na API em 21/11. As que não fecham pela contagem (Castelo do Piauí, Cedro, Demerval Lobão) ficam nas
Pendências, sem chute.
"""
import os

import pytest

import app

REAL = os.path.join(os.path.dirname(app.__file__), "trackers_depara.xlsx")


@pytest.fixture
def planilha(monkeypatch):
    monkeypatch.setattr(app, "_TRK_DEPARA_PATH", REAL)
    monkeypatch.setattr(app, "_TRK_DEPARA_LOCAL", REAL + ".nao-existe")
    monkeypatch.setattr(app, "_falhas_trk_nome_cadastro", lambda pid: None)
    app._trk_depara_carregar._c = None
    yield
    app._trk_depara_carregar._c = None


@pytest.mark.parametrize("fonte,usina,tracker,code", [
    ("owen", "Sete Lagoas", "Tracker 1.38", "SLG200-ETKR38.200"),       # chamado aberto, parado em 21/11
    ("owen", "Sete Lagoas", "Tracker 1.58", "SLG200-ETKR58.200"),
    ("owen", "Araputanga", "Tracker 1.5", "APG100-ETKR5.100"),          # chamado aberto, parado em 21/11
    ("owen", "Ipixuna do Pará", "Tracker 2.10", "2C-IPX100-ETKR59.100"),  # série única: 49 do skid 1 + 10
    ("owen", "Tupi Paulista", "Tracker 3.1", "TPP100-ETKR11.102"),      # série única: 60 + 1 = 61 = 11 do bloco .102
    ("owen", "Tupi Paulista", "Tracker 2.20", "TPP100-ETKR50.101"),
    ("greenyellow", "Macaiba 1", "5", "MCB100-ETKR5.100"),
    ("pg", "(311) Santa Bárbara I", "Tracker 18", "STB100-ETKR18.100"),  # chamado aberto
])
def test_as_usinas_novas_ligam_e_vao_a_confirmar(planilha, fonte, usina, tracker, code):
    par, motivo = app._falhas_os_trk_par(fonte, None, usina, tracker)
    assert motivo is None and par["code"] == code and par["situacao"] == "a_confirmar"


def test_as_que_nao_fecham_pela_contagem_ficam_nas_pendencias(planilha):
    d = app._trk_depara_carregar()
    assert app._trk_depara_usina("greenyellow", "Castelo do Piauí") is None
    txt = " ".join(" ".join(p.values()) for p in d["pendencias"])
    assert "Castelo do Piauí" in txt and "Cedro" in txt and "Demerval" in txt


def test_o_que_ja_havia_continua(planilha):
    par, motivo = app._falhas_os_trk_par("pv", None, "Altair 1 (73)", "TRK1")
    assert motivo is None and par["code"] == "ALT100-ETKR1.101" and par["situacao"] == "casado"
    assert app._trk_depara_carregar()["n"] == 4745 + 482
