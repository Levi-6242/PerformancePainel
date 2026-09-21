# -*- coding: utf-8 -*-
"""A SEMP tem DUAS usinas na conta oem@ da API PV (Levi, 15/09/2026).

Até 15/09 a fonte `semp` listava só a "UFV Tucano 1" (18758732), então a Tucano 2 NUNCA aparecia no
tempo real — só no histórico, pela aba do BD_Performance. Levi: "não aparece no tempo real, mas está
na PV Operation que nem a Tucano 1". A conta oem@ devolve as duas ("UFV Tucano 1" e "UFV Tucano 2",
id 18768694) e o de-para de supervisório já existia no Equipamentos. Conferido ao vivo: /api/semp/data
passou a devolver as duas linhas e o /api/macro foi de 102 para 103 usinas.

A fonte filtra por ID explícito (`_pv_plantas_da_fonte`), NÃO pelo FULL_OM — por isso faltar o id é
falha silenciosa: a usina simplesmente não existe para o tempo real, sem erro nenhum."""
import app


def test_semp_tem_as_duas_tucano():
    ids = app.PV_FONTES["semp"]
    assert 18758732 in ids, "UFV Tucano 1"
    assert 18768694 in ids, "UFV Tucano 2 — sem este id ela some do tempo real"
    assert len(ids) == 2


def test_tucano2_entra_no_universo_oem():
    # as usinas da conta OEM são a união das fontes — a Tucano 2 tem de estar lá
    assert 18768694 in app.PV_OEM_PLANTS
    assert app._pv_fonte_de(18768694) == "semp"
    assert app._pv_is_oem(18768694) is True
