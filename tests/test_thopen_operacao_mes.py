# -*- coding: utf-8 -*-
"""Operação no Mês do Dashboard Thopen (08/10/2026): as contas puras do card do Diário.

Cada teste trava um erro previsto antes de ir ao cliente: Brodowski pela metade sem o plant_id, duas linhas iguais que
são dois trackers (Assis), parada com a usina muda, zero que é "sem monitoramento", Ipixuna da 2C na tela da Thopen,
ronda repetida em 3 OS, hora da ronda em UTC, nome que não casa, nível fora da escala, nada antes de 10/2026.

Rodada 2 (08/10, tarde — Ana e Levi): strings vêm das OS de recomposição de string do Fracttal, pela data do evento;
trackers por dia vêm das ocorrências da plataforma com a usina comunicando; a resposta ganha `por_dia` e `avisos`.
"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "thopen"))
import operacao_mes as om  # noqa: E402

HOJE = dt.date(2026, 10, 8)


def ep_s(usina, pid, inv, st, mes="2026-10", cliente="Thopen", fonte="Thopen · API PV"):
    return {"mes": mes, "fonte": fonte, "cliente": cliente, "usina": usina, "inversor": inv, "string": st, "plant_id": pid}


def ep_t(usina, pid, trk, dias_com=1, mes="2026-10", cliente="Thopen", fonte="Thopen · API PV"):
    return {"mes": mes, "fonte": fonte, "cliente": cliente, "usina": usina, "tracker": trk, "plant_id": pid,
            "dias_comunicou": dias_com}


def cob(usina, pid, s=8, t=8, mes="2026-10", cliente="Thopen"):
    return {"mes": mes, "fonte": "Thopen · API PV", "cliente": cliente, "usina": usina, "plant_id": pid,
            "dias_strings": s, "dias_trackers": t}


def os_(usina, dia, inv="Inversor 1.1", strings="", qtd=None, origem="texto", os="15001", status="Concluída",
        cliente="Thopen", pid="1"):
    """Uma linha da aba strings_os (1 OS de recomposição de string do Fracttal, contrato da rodada 2)."""
    return {"mes": dia[:7], "data_evento": dia, "cliente": cliente, "usina": usina, "plant_id": pid, "inversor": inv,
            "os": os, "status": status, "strings": strings, "qtd": qtd, "origem": origem}


def td(usina, dia, trackers, pid="1", comunicou="sim", cliente="Thopen", fonte="Thopen · API PV"):
    """Uma linha da aba trackers_dia (usina-fonte-plant_id × dia com tracker parado e a usina comunicando)."""
    return {"mes": dia[:7], "dia": dia, "fonte": fonte, "cliente": cliente, "usina": usina, "plant_id": pid,
            "trackers": ", ".join(trackers), "qtd": len(trackers), "comunicou": comunicou}


# o mês publicado com as abas da rodada 2 (as contagens só valem para a conferência; aqui não se confere)
PUB = [{"mes": "2026-10", "periodo_fim": "2026-10-08", "atualizado_em": "2026-10-08 10:05", "strings_os": 0,
        "trackers_dia": 0}]


def _p3(por_dia):
    """O por_dia sem a disponibilidade e a ronda (rodada 4): os testes das rodadas 1 e 2 olham strings e trackers."""
    return [{k: x[k] for k in ("dia", "strings", "trackers")} for x in por_dia]


def dados(**kw):
    base = {"strings_episodios": [], "trackers_episodios": [], "cobertura": [], "atualizacao": [],
            "strings_os": [], "trackers_dia": [], "rondas_com_os": [], "rondas_sem_os": [], "de_para": []}
    base.update(kw)
    return base


def test_brodowski_conta_os_dois_cadastros_pelo_plant_id():
    t = [ep_t("Brodowski", "297378", f"TRK{i}") for i in range(1, 53)] + \
        [ep_t("Brodowski", "297381", f"TRK{i}") for i in range(1, 52)]
    r = om.resposta(dados(trackers_episodios=t, cobertura=[cob("Brodowski", "297378")], atualizacao=PUB),
                    "Brodowski", 2026, 10, HOJE)
    assert r["trackers"] == 103


def test_duas_linhas_iguais_de_cadastros_diferentes_sao_dois_trackers():
    # Assis, out/2026: TRK15 do 18747549 e do 18747550 chegam iguais tirando o plant_id — deduplicar apagaria um
    t = [ep_t("Assis", "18747549", "TRK15"), ep_t("Assis", "18747550", "TRK15"), ep_t("Assis", "18747550", "TRK15")]
    assert om.resposta(dados(trackers_episodios=t, atualizacao=PUB), "Assis", 2026, 10, HOJE)["trackers"] == 2


def test_parada_com_a_usina_muda_nao_conta_e_a_coluna_vazia_conta():
    t = [ep_t("Altair", "1", "TRK1", dias_com=0), ep_t("Altair", "1", "TRK2", dias_com=None),
         ep_t("Altair", "1", "TRK3", dias_com=2)]
    assert om.resposta(dados(trackers_episodios=t, atualizacao=PUB), "Altair", 2026, 10, HOJE)["trackers"] == 2


def test_strings_das_os_distintas_por_usina_inversor_e_string():
    # a mesma string citada em duas OS do mês é uma só; o nome do inversor e da string vêm escritos de jeitos diferentes
    o = [os_("Altair", "2026-10-01", "Inversor 1.1", "Ipv3, Ipv7", os="1"),
         os_("Altair", "2026-10-05", "inversor 1.1", "IPV 3; Ipv9", os="2"),
         os_("Altair", "2026-10-06", "Inversor 1.2", "Ipv3", os="3")]
    assert om.resposta(dados(strings_os=o, atualizacao=PUB), "Altair", 2026, 10, HOJE)["strings"] == 4


def test_os_sem_lista_soma_a_quantidade_uma_vez_por_os():
    # "Strings sem corrente: 4" sem a lista: vale o número; a mesma OS lida duas vezes não soma duas
    o = [os_("Altair", "2026-10-01", qtd=4, os="10"), os_("Altair", "2026-10-01", qtd=4, os="10"),
         os_("Altair", "2026-10-02", qtd="2", os="11"), os_("Altair", "2026-10-03", strings="Ipv1", qtd=1, os="12")]
    assert om.resposta(dados(strings_os=o, atualizacao=PUB), "Altair", 2026, 10, HOJE)["strings"] == 7


def test_os_sem_quantidade_nao_soma_e_avisa_com_a_data():
    o = [os_("Altair", "2026-10-05", origem="sem_quantidade", os="20"), os_("Altair", "2026-10-06", qtd=3, os="21")]
    r = om.resposta(dados(strings_os=o, atualizacao=PUB), "Altair", 2026, 10, HOJE)
    assert r["strings"] == 3
    assert r["avisos"] == ["1 OS de string sem quantidade (05/10), fora da soma"]


def test_so_os_sem_quantidade_e_traco_e_nao_zero():
    # houve OS de string e não se sabe quantas: "0" seria o zero que é "sem dado"
    o = [os_("Altair", "2026-10-05", origem="sem_quantidade", os="20")]
    r = om.resposta(dados(strings_os=o, cobertura=[cob("Altair", "1")], atualizacao=PUB), "Altair", 2026, 10, HOJE)
    assert r["strings"] is None and r["avisos"]
    assert _p3(r["por_dia"]) == [{"dia": "05/10", "strings": None, "trackers": 0}]


def test_os_estimada_pela_grid_avisa():
    # outubro: OS sem quantidade completada do nosso lado pelo monitoramento (Levi, 08/10), marcada "estimado"
    o = [os_("Altair", "2026-10-05", strings="Ipv1, Ipv2", qtd=2, origem="estimado")]
    r = om.resposta(dados(strings_os=o, atualizacao=PUB), "Altair", 2026, 10, HOJE)
    assert r["strings"] == 2 and r["avisos"] == [om.AVISO_ESTIMADO]
    assert om.AVISO_ESTIMADO == "parte das strings estimada pela Grid (OS sem quantidade)"


def test_string_vai_para_o_mes_da_data_do_evento():
    o = [os_("Altair", "2026-09-30", strings="Ipv1", os="1"), os_("Altair", "2026-10-02", strings="Ipv2", os="2")]
    o[0]["mes"] = "2026-10"                       # a OS do mês publicado com o evento ainda em setembro
    r = om.resposta(dados(strings_os=o, atualizacao=PUB), "Altair", 2026, 10, HOJE)
    assert r["strings"] == 1 and [p["dia"] for p in r["por_dia"]] == ["02/10"]


def test_os_cancelada_nao_conta():
    # a mesma regra do histórico de OS da plataforma (Levi, 26/08): cancelada fica fora, pelo texto do status
    o = [os_("Altair", "2026-10-02", strings="Ipv1, Ipv2", status="Cancelada", os="1"),
         os_("Altair", "2026-10-03", strings="Ipv5", os="2")]
    r = om.resposta(dados(strings_os=o, atualizacao=PUB), "Altair", 2026, 10, HOJE)
    assert r["strings"] == 1 and [p["dia"] for p in r["por_dia"]] == ["03/10"]


def test_medida_sem_falha_e_zero_e_sem_cobertura_e_sem_monitoramento():
    r = om.resposta(dados(cobertura=[cob("Altair", "1", s=8, t=0)], atualizacao=PUB), "Altair", 2026, 10, HOJE)
    assert (r["strings"], r["trackers"]) == (0, None)
    r = om.resposta(dados(atualizacao=PUB), "Lyon", 2026, 10, HOJE)
    assert (r["strings"], r["trackers"], r["disponivel"]) == (None, None, True)


def test_aba_nova_ainda_nao_publicada_e_traco_e_nao_zero():
    # antes de a plataforma publicar strings_os/trackers_dia no mês (coluna vazia na atualizacao), "0" seria falso; e o
    # total de trackers sem o detalhe por dia deixaria a tabela do Diário dizendo "0" no dia em que houve parada
    at = [{"mes": "2026-10", "periodo_fim": "2026-10-08", "strings_os": None, "trackers_dia": None}]
    t = [ep_t("Altair", "1", "TRK1")]
    r = om.resposta(dados(cobertura=[cob("Altair", "1")], trackers_episodios=t, atualizacao=at), "Altair", 2026, 10,
                    HOJE)
    assert (r["strings"], r["trackers"], r["disponivel"]) == (None, None, True)


def test_cliente_de_outra_empresa_nunca_entra():
    # Ipixuna do Pará é da 2C (2C-IPX100); Ipixuna 1 e 2 da Polaris são THPN-IPX100 — regra 4 do Kimball
    o = [os_("Ipixuna 1", "2026-10-02", strings="Ipv1", cliente="2C")]
    t = [td("Ipixuna 1", "2026-10-02", ["TRK1"], cliente="2C")]
    r = om.resposta(dados(strings_os=o, trackers_dia=t, atualizacao=PUB), "Ipixuna 1", 2026, 10, HOJE)
    assert (r["strings"], r["trackers"], r["por_dia"]) == (None, None, [])


def test_nomes_das_falhas_que_nao_sao_os_do_5080():
    # Primavera 1 e 2 viram uma Primavera no 5080 e têm cada uma o seu "Inversor 1.1": são duas strings
    s = [os_("Primavera 1", "2026-10-02", strings="Ipv1", os="a"),
         os_("Primavera 2", "2026-10-02", strings="Ipv1", os="b"),
         os_("Marajoara I", "2026-10-02", strings="Ipv1", os="c"),
         os_("Corrego do Sapucaia", "2026-10-02", strings="Ipv1", os="d"),
         os_("Santo Antonio do Platina", "2026-10-02", strings="Ipv1", os="e")]
    d = dados(strings_os=s, atualizacao=PUB)
    assert om.resposta(d, "Primavera", 2026, 10, HOJE)["strings"] == 2
    assert om.resposta(d, "Marajoara 1", 2026, 10, HOJE)["strings"] == 1
    assert om.resposta(d, "Córrego do Sapucaia", 2026, 10, HOJE)["strings"] == 1
    assert om.resposta(d, "Santo Antonio da Platina", 2026, 10, HOJE)["strings"] == 1


def test_sem_plant_id_publicado_nao_mostra_numero():
    t = [ep_t("Altair", None, "TRK1")]
    r = om.resposta(dados(trackers_episodios=t, atualizacao=PUB), "Altair", 2026, 10, HOJE)
    assert r["disponivel"] is False and "plant_id" in r["motivo"]
    # o tracker por dia também conta distinto por plant_id (Brodowski): sem ele, a mesma barreira
    r = om.resposta(dados(trackers_dia=[td("Altair", "2026-10-02", ["TRK1"], pid="")], atualizacao=PUB), "Altair",
                    2026, 10, HOJE)
    assert r["disponivel"] is False and "plant_id" in r["motivo"]


def test_os_e_episodio_de_string_sem_plant_id_nao_travam_o_card():
    # as strings vêm das OS (chave usina + inversor + string): o plant_id delas não entra na conta; e os episódios da
    # régua de 2 h não dão mais número nenhum ao card
    o = [os_("Altair", "2026-10-02", strings="Ipv1", pid=None)]
    s = [ep_s("Altair", None, "Inversor 1.1", "Ipv1")]
    r = om.resposta(dados(strings_os=o, strings_episodios=s, atualizacao=PUB), "Altair", 2026, 10, HOJE)
    assert r["disponivel"] is True and r["strings"] == 1


def test_linha_sem_plant_id_de_outra_usina_ou_cliente_nao_trava_a_usina():
    # revisão de 08/10: em 10/2026 havia 245 linhas da Athon, 171 da Renogrid e 33 da 2C sem plant_id — uma linha de
    # outro cliente (ou de outra usina) não diz nada sobre a contagem desta
    t = [ep_t("X", None, "TRK1", cliente="Athon", fonte="Athon"), ep_t("Brodowski", None, "TRK1"),
         ep_t("Altair", "1", "TRK1"), ep_t("Y", "", "TRK1", cliente="Renogrid")]
    r = om.resposta(dados(trackers_episodios=t, atualizacao=PUB), "Altair", 2026, 10, HOJE)
    assert r["disponivel"] is True and r["trackers"] == 1
    r = om.resposta(dados(trackers_episodios=t, atualizacao=PUB), "Brodowski", 2026, 10, HOJE)
    assert r["disponivel"] is False and "plant_id" in r["motivo"]


def test_antes_de_outubro_nao_responde_e_sem_dados_esta_carregando():
    assert om.resposta(dados(), "Altair", 2026, 9, HOJE)["motivo"] == "antes de 10/2026"
    r = om.resposta(None, "Altair", 2026, 10, HOJE)
    assert r["disponivel"] is False and r["motivo"] == "carregando"


def test_niveis_do_texto_da_ronda_e_fora_da_escala_e_sem_leitura():
    t = ("Computador: Ligado; Sujidade da vala de drenagem: Limpa; Sujidade dos módulos: 4; "
         "Altura da vegetação: Não se aplica")
    assert om.ler_respostas(t) == {"sujidade": 4, "vegetacao": None}
    assert om.ler_respostas("Sujidade dos módulos: 7; Altura da vegetação: 0") == {"sujidade": None, "vegetacao": None}


def test_nivel_quebrado_nao_vira_nivel_inteiro():
    # "1.05" passava pela régua antiga do plano (tirava o ".0" e sobrava "15", que é dígito) e virava nível 1
    assert [om.nivel(v) for v in ("1.05", "2,5", "4.5", 3.0, "3.0", " 2 ", True, None, "")] == \
        [None, None, None, 3, 3, 2, None, None, None]


def ronda(uid, dia, hi, suj, veg, hf="11:00"):
    return {"usina_id": uid, "dia": dia, "hora_inicio": hi, "hora_fim": hf, "sujidade": suj, "vegetacao": veg}


DP = [{"usina_id": 1, "chave_externa": "Altair"}, {"usina_id": 114, "chave_externa": "Primavera"},
      {"usina_id": 115, "chave_externa": "Primavera"}, {"usina_id": 77, "chave_externa": "Coração 1"},
      {"usina_id": 77, "chave_externa": "Coração 2"}]


def test_zeladoria_e_a_ultima_ronda_do_mes_com_a_frase_da_regua():
    rs = [ronda(1, "2026-10-01", "13:00", 5, 5), ronda(1, "2026-10-02", "12:00", 2, 3),
          ronda(1, "2026-09-30", "13:00", 1, 1)]
    z = om.resposta(dados(rondas_com_os=rs, de_para=DP), "Altair", 2026, 10, HOJE)["zeladoria"]
    assert z == {"data": "02/10", "sujidade": {"nivel": 2, "frase": om.REGUA["sujidade"][2]},
                 "vegetacao": {"nivel": 3, "frase": om.REGUA["vegetacao"][3]}}


def test_hora_da_ronda_e_utc():
    # 01/10 às 00:30 UTC é 30/09 21:30 em Brasília: não é ronda de outubro
    rs = [ronda(1, "2026-10-01", "00:30", 4, 4)]
    assert om.resposta(dados(rondas_com_os=rs, de_para=DP), "Altair", 2026, 10, HOJE)["zeladoria"] is None


def test_ronda_sem_os_entra_e_a_mais_tarde_do_dia_vence():
    rs = [ronda(1, "2026-10-06", "10:00", 2, 2)]
    sem = [{"usina_id": 1, "inicio": "2026-10-06T16:43:50.341Z", "sujidade": 4, "vegetacao": 1}]
    z = om.resposta(dados(rondas_com_os=rs, rondas_sem_os=sem, de_para=DP), "Altair", 2026, 10, HOJE)["zeladoria"]
    assert (z["sujidade"]["nivel"], z["vegetacao"]["nivel"]) == (4, 1)


def test_usina_de_dois_ids_e_id_de_duas_usinas():
    rs = [ronda(115, "2026-10-02", "12:00", 3, 3), ronda(77, "2026-10-01", "12:00", 2, 2)]
    d = dados(rondas_com_os=rs, de_para=DP)
    assert om.resposta(d, "Primavera", 2026, 10, HOJE)["zeladoria"]["data"] == "02/10"
    assert om.resposta(d, "Coração 1", 2026, 10, HOJE)["zeladoria"]["data"] == "01/10"
    assert om.resposta(d, "Coração 2", 2026, 10, HOJE)["zeladoria"]["data"] == "01/10"


def test_usina_sem_ligacao_no_cadastro_nao_chuta_id():
    rs = [ronda(1, "2026-10-02", "12:00", 3, 3)]
    assert om.resposta(dados(rondas_com_os=rs, de_para=DP), "Lyon", 2026, 10, HOJE)["zeladoria"] == om.SEM_CADASTRO


def test_usina_sem_ligacao_no_cadastro_nao_e_usina_sem_ronda():
    # revisão de 08/10: 13 usinas do 5080 (Ouro Branco I a V, AP. do Taboado, Lyon...) não têm usina_id no de-para do
    # cadastro do Nexus. A Ouro Branco 1 teve 3 rondas em 09/2026 — "sem leitura no mês" seria o zero que é "sem dado"
    sem_ligacao = om.resposta(dados(de_para=DP), "Lyon", 2026, 10, HOJE)
    sem_ronda = om.resposta(dados(de_para=DP), "Altair", 2026, 10, HOJE)
    assert sem_ligacao["zeladoria"] == {"sem_cadastro": True}
    assert sem_ronda["zeladoria"] is None
    assert tuple(sem_ligacao) == om.CHAVES                                 # sem chave nova fora da lista branca


def test_ronda_repetida_em_varias_os_e_uma_so():
    rs = [ronda(1, "2026-10-02", "12:00", 3, 3)] * 3
    assert len(om.rondas_com_os(rs)) == 1


def test_mes_corrente_diz_ate_quando_e_a_resposta_so_tem_as_chaves_da_lista():
    at = [{"mes": "2026-10", "periodo_fim": "2026-10-08", "atualizado_em": "2026-10-08 10:05",
           "strings_episodios": 0, "trackers_episodios": 0, "cobertura": 0}]
    r = om.resposta(dados(atualizacao=at), "Altair", 2026, 10, HOJE)
    assert (r["parcial_ate"], r["atualizado_em"]) == ("08/10", "2026-10-08 10:05")
    assert tuple(r) == om.CHAVES                                           # lista branca: nada além disto ao cliente


def test_conferencia_da_leitura_com_a_aba_atualizacao():
    at = [{"mes": "2026-10", "strings_episodios": 1, "trackers_episodios": 0, "cobertura": None}]
    assert om.conferir(dados(atualizacao=at, strings_episodios=[ep_s("Altair", "1", "Inversor 1.1", "Ipv1")]))
    assert not om.conferir(dados(atualizacao=at))


def test_conferencia_nao_passa_sem_a_linha_do_mes_na_atualizacao():
    # revisão de 08/10: aba atualizacao renomeada, ainda não sincronizada ou lida vazia no meio do sync — sem ela não
    # há com o que conferir, e a leitura parcial dos episódios seria aceita e gravada em disco como boa
    s = [ep_s("Altair", "1", "Inversor 1.1", "Ipv1")] * 3
    assert not om.conferir(dados(strings_episodios=s))
    at = [{"mes": "2026-09", "strings_episodios": 0, "trackers_episodios": 0, "cobertura": None}]
    assert not om.conferir(dados(strings_episodios=s, atualizacao=at))          # outubro sem a linha dele
    assert not om.conferir(dados(cobertura=[cob("Altair", "1")], atualizacao=at))
    assert om.conferir(dados())                                                # nada publicado: nada a conferir


def test_mes_sem_fechamento_diz_ate_quando_mesmo_depois_de_virar_o_mes():
    # revisão de 08/10: no dia 1º, com o fechamento do mês anterior ainda por sair, o card mostrava o mês como fechado
    at = [{"mes": "2026-10", "periodo_fim": "2026-10-29", "atualizado_em": "2026-10-30 10:05"}]
    r = om.resposta(dados(atualizacao=at), "Altair", 2026, 10, dt.date(2026, 11, 1))
    assert r["parcial_ate"] == "29/10"
    at[0]["periodo_fim"] = "2026-10-31"                                        # fechado: sem o aviso
    assert om.resposta(dados(atualizacao=at), "Altair", 2026, 10, dt.date(2026, 11, 1))["parcial_ate"] is None


def test_tracker_em_dia_sem_prova_conta():
    # decisão do orquestrador (08/10): o dia corrente sem a geração fechada não é falha de comunicação comprovada
    t = [ep_t("Altair", "1", "TRK1", dias_com=0), ep_t("Altair", "1", "TRK2", dias_com=0),
         ep_t("Altair", "1", "TRK3", dias_com=0), ep_t("Altair", "1", "TRK4", dias_com=1)]
    t[0]["dias_sem_prova"], t[1]["dias_sem_prova"], t[2]["dias_sem_prova"] = 1, 0, None
    assert om.resposta(dados(trackers_episodios=t, atualizacao=PUB), "Altair", 2026, 10, HOJE)["trackers"] == 2


def test_por_dia_junta_as_os_e_os_trackers_do_dia_em_ordem():
    o = [os_("Brodowski", "2026-10-05", strings="Ipv1, Ipv2", os="1"), os_("Brodowski", "2026-10-01", qtd=4, os="2")]
    t = [td("Brodowski", "2026-10-01", ["TRK1", "TRK2"], pid="297378"),
         td("Brodowski", "2026-10-01", ["TRK1"], pid="297381"),
         td("Brodowski", "2026-10-03", ["TRK1"], pid="297378")]
    ep = [ep_t("Brodowski", "297378", "TRK1"), ep_t("Brodowski", "297378", "TRK2"), ep_t("Brodowski", "297381", "TRK1")]
    r = om.resposta(dados(strings_os=o, trackers_dia=t, trackers_episodios=ep, cobertura=[cob("Brodowski", "297378")],
                          atualizacao=PUB), "Brodowski", 2026, 10, HOJE)
    assert _p3(r["por_dia"]) == [{"dia": "01/10", "strings": 4, "trackers": 3},
                            {"dia": "03/10", "strings": 0, "trackers": 1},
                            {"dia": "05/10", "strings": 2, "trackers": 0}]
    assert (r["strings"], r["trackers"]) == (6, 3)


def test_por_dia_sem_monitoramento_e_traco_e_nao_zero():
    # usina sem cobertura de strings e sem OS no mês: o dia do tracker não diz "0 strings"
    t = [td("Altair", "2026-10-03", ["TRK1"])]
    r = om.resposta(dados(trackers_dia=t, trackers_episodios=[ep_t("Altair", "1", "TRK1")], atualizacao=PUB),
                    "Altair", 2026, 10, HOJE)
    assert _p3(r["por_dia"]) == [{"dia": "03/10", "strings": None, "trackers": 1}]


def test_tracker_do_dia_sem_comunicacao_nao_entra_e_sem_prova_entra():
    t = [td("Altair", "2026-10-02", ["TRK1"], comunicou="não"),
         td("Altair", "2026-10-08", ["TRK2"], comunicou="sem prova")]
    r = om.resposta(dados(trackers_dia=t, cobertura=[cob("Altair", "1")], atualizacao=PUB), "Altair", 2026, 10, HOJE)
    assert _p3(r["por_dia"]) == [{"dia": "08/10", "strings": 0, "trackers": 1}]


def test_total_do_mes_nunca_e_menor_que_o_de_um_dia():
    # as duas abas vêm da mesma régua; se um dia divergirem, a tela não pode dizer "2 no mês" e "3 num dia"
    t = [td("Altair", "2026-10-02", ["TRK1", "TRK2", "TRK3"])]
    ep = [ep_t("Altair", "1", "TRK1"), ep_t("Altair", "1", "TRK2")]
    r = om.resposta(dados(trackers_dia=t, trackers_episodios=ep, atualizacao=PUB), "Altair", 2026, 10, HOJE)
    assert r["trackers"] == 3


def test_resposta_nunca_leva_o_numero_da_os_nem_texto_da_os():
    o = [os_("Altair", "2026-10-02", strings="Ipv1", os="15221", status="Concluída"),
         os_("Altair", "2026-10-03", origem="sem_quantidade", os="15222")]
    r = om.resposta(dados(strings_os=o, atualizacao=PUB), "Altair", 2026, 10, HOJE)
    txt = json.dumps(r, ensure_ascii=False)
    assert "15221" not in txt and "15222" not in txt and "Concluída" not in txt and "Ipv1" not in txt
    assert tuple(r) == om.CHAVES and {"por_dia", "avisos"} <= set(om.CHAVES)
    # rodada 4: + disp e ronda; 13/10: + os (o registro da OS do dia abaixo de 100%, sem o nº)
    assert all(set(p) == {"dia", "strings", "trackers", "disp", "ronda", "os"} for p in r["por_dia"])
    assert all(isinstance(a, str) for a in r["avisos"])


def test_antes_de_outubro_e_carregando_tem_listas_vazias():
    for d, m in ((dados(), 9), (None, 10)):
        r = om.resposta(d, "Altair", 2026, m, HOJE)
        assert (r["por_dia"], r["avisos"]) == ([], [])


def test_conferencia_tambem_das_os_e_dos_trackers_por_dia():
    at = [{"mes": "2026-10", "strings_episodios": 0, "trackers_episodios": 0, "cobertura": 0, "strings_os": 2,
           "trackers_dia": 1}]
    o = [os_("Altair", "2026-10-02", strings="Ipv1", os="1"), os_("Altair", "2026-10-03", strings="Ipv2", os="2")]
    t = [td("Altair", "2026-10-02", ["TRK1"])]
    assert om.conferir(dados(atualizacao=at, strings_os=o, trackers_dia=t))
    assert not om.conferir(dados(atualizacao=at, strings_os=o[:1], trackers_dia=t))        # leu no meio do sync
    assert not om.conferir(dados(atualizacao=at, strings_os=o, trackers_dia=t + t))
    at[0]["strings_os"] = at[0]["trackers_dia"] = None                                     # coluna vazia: não confere
    assert om.conferir(dados(atualizacao=at, strings_os=o, trackers_dia=t + t))
    assert not om.conferir(dados(strings_os=o))                                           # mês sem a linha dele


# ── Rodada 4 (Levi, 09/10/2026): a tabela volta a ter colunas — Disp (%) do dia pela régua do Gerencial (Fracttal),
# Tracker e String — e o comentário ganha a ronda do dia. O card da disponibilidade do mês usa a mesma régua de outubro
# em diante ("a partir de outubro somente; antes disso é modelo anterior").
def dsp(usina, dia, disp, ids=None, pot=1000.0, fr=None):
    """Uma linha da aba disponibilidade_dia, já com os usina_ids que a leitura liga pelo nome do Fracttal."""
    return {"mes": dia[:7], "dia": dia, "usina": usina, "usina_fracttal": fr, "pot_kwp": pot, "disp": disp,
            "usina_ids": ids or []}


PUB4 = [dict(PUB[0], disponibilidade_dia=0)]


def test_disponibilidade_do_dia_e_do_mes_pela_regua_do_gerencial():
    ds = [dsp("Altair", f"2026-10-0{d}", v, ids=[1]) for d, v in ((1, 100.0), (2, 95.8), (3, 100.0), (4, 100.0))]
    r = om.resposta(dados(disponibilidade_dia=ds, de_para=DP, atualizacao=PUB4), "Altair", 2026, 10, HOJE)
    assert r["disponibilidade"] == 98.95                          # a média dos dias: a conta do Gerencial (12 h/dia)
    pd = {x["dia"]: x for x in r["por_dia"]}
    assert [pd[d]["disp"] for d in ("01/10", "02/10", "03/10", "04/10")] == [100.0, 95.8, 100.0, 100.0]


def test_usina_com_dois_cadastros_no_gerencial_pondera_pela_potencia():
    ds = [dsp("Primavera 1", "2026-10-02", 90.0, ids=[114], pot=1000.0),
          dsp("Primavera 2", "2026-10-02", 100.0, ids=[115], pot=3000.0)]
    r = om.resposta(dados(disponibilidade_dia=ds, de_para=DP, atualizacao=PUB4), "Primavera", 2026, 10, HOJE)
    assert [x["disp"] for x in r["por_dia"] if x["dia"] == "02/10"] == [97.5]


def test_sem_ligacao_no_de_para_casa_pelo_nome_e_nunca_chuta():
    ds = [dsp("Altair", "2026-10-02", 95.0), dsp("Altair 2", "2026-10-02", 50.0)]
    r = om.resposta(dados(disponibilidade_dia=ds, atualizacao=PUB4), "Altair", 2026, 10, HOJE)
    assert [x["disp"] for x in r["por_dia"]] == [95.0] and r["disponibilidade"] == 95.0
    sem = om.resposta(dados(atualizacao=PUB4), "Altair", 2026, 10, HOJE)
    assert sem["disponibilidade"] is None                       # sem dado: "—", nunca 100


def test_ronda_do_dia_vai_no_por_dia_com_os_niveis():
    rs = [ronda(1, "2026-10-02", "10:00", 2, 3), ronda(1, "2026-10-02", "15:00", 4, None), ronda(1, "2026-10-05", "12:00", 1, 1)]
    r = om.resposta(dados(rondas_com_os=rs, de_para=DP, atualizacao=PUB4), "Altair", 2026, 10, HOJE)
    pd = {x["dia"]: x for x in r["por_dia"]}
    assert pd["02/10"]["ronda"] == {"sujidade": 4, "vegetacao": None}       # a última do dia vence
    assert pd["05/10"]["ronda"] == {"sujidade": 1, "vegetacao": 1}
    assert pd["05/10"]["disp"] is None


def test_disponibilidade_conferida_com_a_atualizacao():
    ds = [dsp("Altair", "2026-10-01", 100.0, ids=[1])]
    assert om.conferir(dados(disponibilidade_dia=ds, atualizacao=[dict(PUB[0], disponibilidade_dia=1)]))
    assert not om.conferir(dados(disponibilidade_dia=ds, atualizacao=[dict(PUB[0], disponibilidade_dia=2)]))


def test_nome_proprio_no_gerencial_vence_o_site_compartilhado_do_fracttal():
    # Aparecida do Taboado 1 e 2 (e Santarém 1/2, Rodrigues 1/2) dividem um site no Fracttal: pelo id do de-para as duas
    # recebiam a média das duas (87,53% cada, com o Gerencial dizendo 100% e 78,84%). O nome da usina vence o site
    dp = [{"usina_id": 3, "chave_externa": "Aparecida do Taboado 1"}, {"usina_id": 4, "chave_externa": "Aparecida do Taboado 2"}]
    ds = [dsp("Aparecida do Taboado 1", "2026-10-02", 100.0, ids=[3, 4]),
          dsp("Aparecida do Taboado 2", "2026-10-02", 78.84, ids=[3, 4])]
    d = dados(disponibilidade_dia=ds, de_para=dp, atualizacao=PUB4)
    assert om.resposta(d, "Aparecida do Taboado 1", 2026, 10, HOJE)["disponibilidade"] == 100.0
    assert om.resposta(d, "Aparecida do Taboado 2", 2026, 10, HOJE)["disponibilidade"] == 78.84


def test_mes_pelas_horas_perdidas_e_nao_pelo_dia_arredondado():
    # o dia vem arredondado em 1 casa; a média de dias arredondados errava o mês do Gerencial em 0,01–0,02 p.p.
    ds = [dict(dsp("Altair", "2026-10-01", 97.9, ids=[1]), h_perdidas=0.254),
          dict(dsp("Altair", "2026-10-02", 100.0, ids=[1]), h_perdidas=0)]
    r = om.resposta(dados(disponibilidade_dia=ds, de_para=DP, atualizacao=PUB4), "Altair", 2026, 10, HOJE)
    assert r["disponibilidade"] == round(100 * (1 - 0.254 / 24), 2) == 98.94
    assert [x["disp"] for x in r["por_dia"]] == [97.9, 100.0]


# ── 13/10 (Levi): "tem dias que a disponibilidade tá menor que 100 e não tem comentário de desligamento, isso não pode
# acontecer"; 14/10, noite: "A partir de outubro quero os comentários 100% OS Fracttal. Comentários e disponibilidade!".
# O comentário do dia é a parcela de cada OS na conta do Gerencial (aba disponibilidade_os_dia): os trechos em que a OS
# foi dona da perda, nunca o início e o fim dela — o dia em que a OS não tirou hora na conta não tem linha (Canarana 1,
# 08 a 12/10: refeita pelo 5080, a OS de usina inteira virava "usina parada o dia todo" ao lado de 87,5%).
def osd(usina, dia, trechos, ini, fim, tipo="Religamento", escopo="Usina inteira", ids=None, aberta="não", kwp=None,
        h=None, os=None):
    """Uma linha da aba disponibilidade_os_dia como a leitura deixa (sem a origem; o nº da OS desde 15/10/2026)."""
    return {"mes": "2026-10", "dia": dia, "usina": usina, "usina_fracttal": None, "os": os, "tipo": tipo, "escopo": escopo,
            "kwp": kwp, "inicio": ini, "fim": fim, "aberta": aberta, "trechos": trechos, "h_perdidas": h,
            "usina_ids": ids or []}


PUB5 = [dict(PUB[0], disponibilidade_dia=0, disponibilidade_os_dia=0)]


def test_dia_abaixo_de_100_leva_o_registro_da_os_do_fracttal():
    ds = [dsp("Alvares Machado", f"2026-10-0{d}", v) for d, v in ((5, 22.2), (6, 25.9), (7, 99.7), (8, 100.0))]
    longa = ("Alvares Machado", "2026-10-05T08:40:00", "2026-10-06T14:53:52")
    os_ = [osd(longa[0], "2026-10-05", "08:40-18:00", *longa[1:], os="15410"),
           osd(longa[0], "2026-10-06", "06:00-14:53", *longa[1:], os="15410"),
           osd("Alvares Machado", "2026-10-07", "12:55-12:57", "2026-10-07T12:55:00", "2026-10-07T12:57:00",
               tipo="Religamento Remoto", os="15692")]
    r = om.resposta(dados(disponibilidade_dia=ds, disponibilidade_os_dia=os_, atualizacao=PUB5), "Alvares Machado", 2026,
                    10, HOJE)
    pd = {x["dia"]: x for x in r["por_dia"]}
    # 14/10 (Levi: "preciso de um motivo que faça sentido"): o que parou NAQUELE dia, e o desligamento inteiro junto
    # 15/10/2026, tarde (Levi: "pode ficar só como: Desligamento Cabine 2 de 09/10 às 16:29h a 13/10 às 18:21h;
    # religamento, OS do Fracttal / invés de OS do fracttal quero o número desse OS")
    assert pd["06/10"]["os"] == ["Desligamento Usina de 05/10 às 08:40h a 06/10 às 14:53h; religamento, OS 15410"]
    assert pd["07/10"]["os"] == ["Desligamento Usina de 07/10 às 12:55h a 07/10 às 12:57h; religamento remoto, OS 15692"]
    assert pd["08/10"]["os"] == []                                    # 100%: nada a explicar


def test_os_de_cabine_de_inversor_e_em_aberto():
    ds = [dsp("Cipó Guaçu", "2026-10-02", 32.5)]
    os_ = [osd("Cipó Guaçu", "2026-10-02", "06:00-18:00", "2026-09-11T09:20:00", "2026-10-06T15:30:39", escopo="Cabine 3"),
           osd("Cipó Guaçu", "2026-10-02", "06:00-18:00", "2026-09-30T10:00:00", "2026-09-30T10:00:00",
               tipo="Corretiva Emergencial", escopo="Inversor 1.3; Inversor 1.5", aberta="sim"),
           osd("Cipó Guaçu", "2026-10-02", "sem hora", "2026-09-01T10:00:00", "2026-09-01T10:00:00")]   # não lê: fora
    r = om.resposta(dados(disponibilidade_dia=ds, disponibilidade_os_dia=os_, atualizacao=PUB5), "Cipó Guaçu", 2026, 10,
                    HOJE)
    assert r["por_dia"][0]["os"] == [
        "Desligamento Cabine 3 de 11/09 às 09:20h a 06/10 às 15:30h; religamento, OS do Fracttal",   # sem o nº
        "Desligamento Inversor 1.3 e Inversor 1.5 desde 30/09 às 10:00h, em aberto; corretiva emergencial, OS do Fracttal"]


def test_os_segue_a_mesma_ligacao_da_disponibilidade():
    # o nome vence o site compartilhado: a OS da Aparecida do Taboado 2 nunca explica o dia da 1
    dp = [{"usina_id": 3, "chave_externa": "Aparecida do Taboado 1"}, {"usina_id": 4, "chave_externa": "Aparecida do Taboado 2"}]
    ds = [dsp("Aparecida do Taboado 1", "2026-10-04", 90.0, ids=[3, 4]),
          dsp("Aparecida do Taboado 2", "2026-10-04", 40.3, ids=[3, 4])]
    os_ = [osd("Aparecida do Taboado 1", "2026-10-04", "07:00-08:12", "2026-10-04T07:00:00", "2026-10-04T08:12:00",
               ids=[3, 4]),
           osd("Aparecida do Taboado 2", "2026-10-04", "06:00-18:00", "2026-10-04T06:00:00", "2026-10-05T18:00:00",
               ids=[3, 4])]
    d = dados(disponibilidade_dia=ds, disponibilidade_os_dia=os_, de_para=dp, atualizacao=PUB5)
    (um,) = om.resposta(d, "Aparecida do Taboado 1", 2026, 10, HOJE)["por_dia"]
    assert um["os"] == ["Desligamento Usina de 04/10 às 07:00h a 04/10 às 08:12h; religamento, OS do Fracttal"]


def test_o_dia_diz_quanto_da_usina_parou_e_por_quanto_tempo():
    # Altair, outubro (Levi, 14/10: "Como assim continua? preciso de um motivo que faça sentido esse valor de 80%"): a
    # cabine 2 (1.379,6 de 6.898 kWp = 20%) parou de 09/10 16:29 a 13/10 18:21 — 09/10 a 97,5% (16:29 às 18:00) e 10 a
    # 12/10 a 80% (o dia todo). A frase de cada dia diz isso; os dias iguais seguidos viram uma linha na tela
    ds = [dsp("Altair", f"2026-10-{d:02d}", v, pot=6898.0) for d, v in ((9, 97.5), (10, 80.0), (11, 80.0), (12, 80.0))]
    os_ = [osd("Altair", f"2026-10-{d:02d}", t, "2026-10-09T16:29:00", "2026-10-13T18:21:44", escopo="Cabine 2",
               kwp=1379.6) for d, t in ((9, "16:29-18:00"), (10, "06:00-18:00"), (11, "06:00-18:00"), (12, "06:00-18:00"))]
    r = om.resposta(dados(disponibilidade_dia=ds, disponibilidade_os_dia=os_, atualizacao=PUB5), "Altair", 2026, 10, HOJE)
    pd = {x["dia"]: x["os"] for x in r["por_dia"]}
    # 15/10/2026, tarde: o texto curto é o mesmo nos quatro dias; a disponibilidade de cada dia diz quanto parou
    curto = ["Desligamento Cabine 2 de 09/10 às 16:29h a 13/10 às 18:21h; religamento, OS do Fracttal"]
    assert pd["09/10"] == pd["10/10"] == pd["11/10"] == pd["12/10"] == curto


def test_os_conferida_com_a_atualizacao():
    o = [osd("Altair", "2026-10-01", "08:00-09:00", "2026-10-01T08:00:00", "2026-10-01T09:00:00")]
    assert om.conferir(dados(disponibilidade_os_dia=o, atualizacao=[dict(PUB[0], disponibilidade_os_dia=1)]))
    assert not om.conferir(dados(disponibilidade_os_dia=o, atualizacao=[dict(PUB[0], disponibilidade_os_dia=2)]))


def test_os_contida_na_da_usina_inteira_nao_vira_outra_linha():
    # Mandaguaçu, 11/10/2026: a usina parada o dia todo (OS de 08/10 a 13/10) e mais 4 OS abertas por cima naquele dia
    # — 5 linhas para um dia só. A que está dentro da OS da usina inteira não explica nada a mais
    # (a de cabine nem tem linha: com a usina inteira parada, a conta do Gerencial não dá parcela a ela)
    ds = [dsp("Mandaguaçu", "2026-10-11", 0.0)]
    os_ = [osd("Mandaguaçu", "2026-10-11", "06:00-18:00", "2026-10-08T12:51:00", "2026-10-13T19:47:00"),
           osd("Mandaguaçu", "2026-10-11", "06:26-11:55", "2026-10-11T06:26:00", "2026-10-11T11:55:00"),
           osd("Mandaguaçu", "2026-10-11", "11:29-12:23", "2026-10-11T11:29:00", "2026-10-11T12:23:00",
               tipo="Corretiva Emergencial")]
    (dia,) = om.resposta(dados(disponibilidade_dia=ds, disponibilidade_os_dia=os_, atualizacao=PUB5), "Mandaguaçu", 2026,
                         10, HOJE)["por_dia"]
    assert dia["os"] == ["Desligamento Usina de 08/10 às 12:51h a 13/10 às 19:47h; religamento, OS do Fracttal"]


def test_dia_com_dois_trechos_e_parte_da_potencia():
    # a OS de cabine coberta por uma de usina inteira só é dona da perda fora dela: os trechos dizem isso
    ds = [dsp("Altair", "2026-10-09", 70.0, pot=6898.0)]
    os_ = [osd("Altair", "2026-10-09", "06:00-08:00; 10:00-12:00", "2026-10-09T06:00:00", "2026-10-09T12:00:00",
               escopo="Cabine 2", kwp=1379.6),
           osd("Altair", "2026-10-09", "08:00-10:00", "2026-10-09T08:00:00", "2026-10-09T10:00:00",
               tipo="Religamento Remoto")]
    (dia,) = om.resposta(dados(disponibilidade_dia=ds, disponibilidade_os_dia=os_, atualizacao=PUB5), "Altair", 2026, 10,
                         HOJE)["por_dia"]
    assert dia["os"] == ["Desligamento Cabine 2 de 09/10 às 06:00h a 09/10 às 12:00h; religamento, OS do Fracttal",
                         "Desligamento Usina de 09/10 às 08:00h a 09/10 às 10:00h; religamento remoto, OS do Fracttal"]


def test_os_sem_linha_na_parcela_nao_tem_comentario():
    # Canarana 1, 08/10/2026: a OS de usina inteira ia de 08 a 12/10, e o índice de então contou só o inversor 1.8
    # (1,5 h = 87,5%; a régua tirava o dia pela geração, o que saiu em 15/10/2026). O 5080 não refaz a conta com o
    # início e o fim da OS: só a linha da parcela vira frase — nunca "usina parada o dia todo" ao lado de 87,5%
    ds = [dsp("Canarana 1", "2026-10-08", 87.5, pot=1942.0), dsp("Canarana 1", "2026-10-13", 100.0, pot=1942.0)]
    os_ = [osd("Canarana 1", "2026-10-08", "06:00-18:00", "2026-10-07T13:50:00", "2026-10-13T13:29:13",
               tipo="Corretiva Emergencial", escopo="Inversor 1.8", kwp=242.8, h=1.5)]
    pd = {x["dia"]: x["os"] for x in om.resposta(dados(disponibilidade_dia=ds, disponibilidade_os_dia=os_,
                                                       atualizacao=PUB5), "Canarana 1", 2026, 10, HOJE)["por_dia"]}
    assert pd["08/10"] == ["Desligamento Inversor 1.8 de 07/10 às 13:50h a 13/10 às 13:29h; corretiva emergencial, OS "
                           "do Fracttal"]
    assert pd["13/10"] == []


def test_parcela_ainda_nao_publicada_nao_vira_dia_sem_os():
    # o mês publicado antes da aba nova (coluna vazia na atualizacao): o dia abaixo de 100% vem com os None, e a tela
    # diz que o registro ainda não chegou — nunca um "sem OS" que só não foi publicado
    ds = [dsp("Altair", "2026-10-09", 80.0)]
    pub = [dict(PUB[0], disponibilidade_dia=1)]
    (dia,) = om.resposta(dados(disponibilidade_dia=ds, atualizacao=pub), "Altair", 2026, 10, HOJE)["por_dia"]
    assert dia["disp"] == 80.0 and dia["os"] is None
