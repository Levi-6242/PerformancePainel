# -*- coding: utf-8 -*-
"""Leitura da Operação no Mês (Dashboard Thopen, 08/10/2026): a requisição do cliente nunca espera a rede (a recarga
do BD_Thopen já segura o 1º acesso por ~130 s), só a lista branca entra na memória e leitura que não bate com a aba
`atualizacao` não substitui a última boa."""
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "thopen"))
import fonte_operacao as fo  # noqa: E402

SHEETS = [
    {"id": 1, "workbook_key": "falhas_performance", "sheet_name": "strings_episodios", "row_count": 1},
    {"id": 2, "workbook_key": "falhas_performance", "sheet_name": "trackers_episodios", "row_count": 0},
    {"id": 4, "workbook_key": "falhas_performance", "sheet_name": "atualizacao", "row_count": 1},
    {"id": 5, "workbook_key": "rondas_app_campo", "sheet_name": "OS de ronda", "row_count": 1},
    {"id": 7, "workbook_key": "cadastro_nexus", "sheet_name": "de_para", "row_count": 2},
]
ROWS = {
    1: [{"headers": ["mes", "usina", "string", "plant_id", "avisos"], "values": ["2026-10", "Altair", "Ipv1", "1", "x"]}],
    4: [{"headers": ["mes", "strings_episodios", "trackers_episodios"], "values": ["2026-10", 1, 0]}],
    # rodada 3 (09/10, "tem que ser dinâmico"): as rondas vêm do livro do App, regravado de hora em hora. Ficam a OS,
    # a hora, os níveis e o checklist; o técnico (nome e HMAC), a nota da ronda e as falhas internas morrem na leitura
    5: [{"headers": ["Data", "OS", "Usina", "Ativo da usina no Fracttal", "Técnico", "Nota da ronda", "Falhas",
                     "Início", "Fim", "Técnico (HMAC)", "Sujidade dos módulos (1 a 5)", "Altura da vegetação (1 a 5)",
                     "Checklist da ronda"],
         "values": ["2026-10-02", 15176.0, "Thopen - Altair 1 - SP", "THPN-ALT100", "Fulano", 95,
                    "ronda longa pendente", "2026-10-02T13:00:05Z", "2026-10-02T13:40:00Z", "cf1:x", "2", "3",
                    "Sujidade dos módulos: 2 [Poeira / areia]; Altura da vegetação: 3"]}],
    7: [{"headers": ["usina_id", "sistema", "chave_externa"], "values": [1, "BD_Thopen · Dados Gerais Usinas", "Altair"]},
        {"headers": ["usina_id", "sistema", "chave_externa"], "values": [1, "Fracttal · Classificação 1",
                                                                         "Thopen - Altair 1 - SP"]}],
}


def get_falso(caminho, tok):
    if caminho == "/api/sheets":
        return SHEETS
    sid = int(caminho.split("/")[3])
    return {"rows": ROWS.get(sid, [])}


def test_lista_branca_o_texto_da_ronda_e_o_tecnico_nao_entram():
    d = fo.baixar("", get_falso)
    (r,) = d["rondas_com_os"]
    assert r == {"usina_id": 1, "dia": "2026-10-02", "hora_inicio": "13:00", "hora_fim": "13:40", "os": "15176",
                 "sujidade": 2, "vegetacao": 3, "unidade": "Altair 1", "achados": {},
                 "itens": [["Sujidade dos módulos", "2", "Poeira / areia"], ["Altura da vegetação", "3"]]}
    assert "ronda longa" not in str(d) and "Fulano" not in str(d) and "cf1:" not in str(d) and 95 not in r.values()
    assert "rondas_sem_os" not in d                      # a carga única de 06/10 saiu: o livro do App tem as 125
    assert "avisos" not in d["strings_episodios"][0]
    assert d["de_para"] == [{"usina_id": 1, "chave_externa": "Altair"}]
    assert d["cobertura"] == []                          # aba ainda não publicada: vazio, não erro


# Rodada 2 (08/10, tarde): as OS de string e os trackers por dia, no contrato fixado no plano
SHEETS2 = SHEETS + [
    {"id": 8, "workbook_key": "falhas_performance", "sheet_name": "strings_os", "row_count": 1},
    {"id": 9, "workbook_key": "falhas_performance", "sheet_name": "trackers_dia", "row_count": 1},
]
ROWS2 = dict(ROWS)
ROWS2[2] = [{"headers": ["mes", "fonte", "cliente", "usina", "tracker", "inversor", "parou", "avisos", "plant_id",
                         "dias_comunicou", "dias_sem_prova"],
             "values": ["2026-10", "Thopen · API PV", "Thopen", "Altair", "TRK1", "Inv 1", "2026-10-08 08:00", "x",
                        "297378", 0, 1]}]
ROWS2[4] = [{"headers": ["mes", "periodo_fim", "atualizado_em", "strings_inversor_dia", "strings_episodios",
                         "trackers_episodios", "regua_strings", "regua_trackers", "cobertura", "strings_os",
                         "trackers_dia"],
             "values": ["2026-10", "2026-10-08", "2026-10-08 10:05", 9, 1, 1, "r", "r", None, 1, 1]}]
ROWS2[8] = [{"headers": ["mes", "data_evento", "cliente", "usina", "plant_id", "inversor", "os", "status", "strings",
                         "qtd", "origem", "observacoes", "tecnico"],
             "values": ["2026-10", "2026-10-02", "Thopen", "Altair", 297378.0, "Inversor 1.1", 15221.0, "Concluída",
                        "Ipv3, Ipv7", 2, "texto", "texto livre da OS", "Fulano"]}]
ROWS2[9] = [{"headers": ["mes", "dia", "fonte", "cliente", "usina", "plant_id", "trackers", "qtd", "comunicou", "x"],
             "values": ["2026-10", "2026-10-02", "Thopen · API PV", "Thopen", "Altair", "297378", "TRK1, TRK2", 2,
                        "sim", "fora"]}]


def get_falso2(caminho, tok):
    if caminho == "/api/sheets":
        return SHEETS2
    return {"rows": ROWS2.get(int(caminho.split("/")[3]), [])}


def test_lista_branca_das_abas_da_rodada_2():
    d = fo.baixar("", get_falso2)
    (o,) = d["strings_os"]
    # o número da OS fica na memória do servidor só para não contar a mesma OS duas vezes (nunca vai ao cliente);
    # o texto livre da OS e o técnico não entram nem aqui
    assert o == {"mes": "2026-10", "data_evento": "2026-10-02", "cliente": "Thopen", "usina": "Altair",
                 "plant_id": "297378", "inversor": "Inversor 1.1", "os": "15221", "status": "Concluída",
                 "strings": "Ipv3, Ipv7", "qtd": 2, "origem": "texto"}
    (t,) = d["trackers_dia"]
    assert set(t) == {"mes", "dia", "fonte", "cliente", "usina", "plant_id", "trackers", "qtd", "comunicou"}
    (e,) = d["trackers_episodios"]
    assert (e["dias_comunicou"], e["dias_sem_prova"]) == (0, 1) and "avisos" not in e
    (a,) = d["atualizacao"]
    assert (a["strings_os"], a["trackers_dia"], a["cobertura"]) == (1, 1, None)


def test_leitura_da_rodada_2_conferida_com_a_atualizacao(monkeypatch, tmp_path):
    monkeypatch.setattr(fo, "CACHE", str(tmp_path / "c.json.gz"))
    monkeypatch.setattr(fo, "_estado", {"dados": None, "ts": 0.0, "erro": None, "carregando": True, "proxima": 0.0,
                                        "disco_lido": True})
    fo._recarrega(get=get_falso2, espera=0)
    assert fo._estado["erro"] is None and fo._estado["dados"]["strings_os"][0]["os"] == "15221"
    # a aba strings_os lida pela metade (o sync trocando linhas) não substitui a leitura boa
    boa = fo._estado["dados"]
    ruim = dict(ROWS2)
    ruim[8] = []
    monkeypatch.setitem(fo._estado, "carregando", True)

    def get_ruim(caminho, tok):
        return SHEETS2 if caminho == "/api/sheets" else {"rows": ruim.get(int(caminho.split("/")[3]), [])}
    fo._recarrega(get=get_ruim, espera=0)
    assert fo._estado["dados"] is boa and "atualizacao" in fo._estado["erro"]


def test_requisicao_nunca_espera_a_rede(monkeypatch, tmp_path):
    monkeypatch.setattr(fo, "CACHE", str(tmp_path / "c.json.gz"))
    monkeypatch.setattr(fo, "_estado", {"dados": None, "ts": 0.0, "erro": None, "carregando": False, "proxima": 0.0,
                                        "disco_lido": False})
    disparos = []
    assert fo.dados(agora=1000.0, iniciar=disparos.append) is None          # nada ainda: dispara e volta na hora
    assert fo.dados(agora=1001.0, iniciar=disparos.append) is None          # já carregando: não dispara de novo
    assert len(disparos) == 1


def test_recarga_boa_vai_para_a_memoria_e_o_disco(monkeypatch, tmp_path):
    monkeypatch.setattr(fo, "CACHE", str(tmp_path / "c.json.gz"))
    monkeypatch.setattr(fo, "_estado", {"dados": None, "ts": 0.0, "erro": None, "carregando": True, "proxima": 0.0,
                                        "disco_lido": True})
    fo._recarrega(get=get_falso, espera=0)
    assert fo._estado["dados"]["strings_episodios"][0]["plant_id"] == "1"
    monkeypatch.setattr(fo, "_estado", {"dados": None, "ts": 0.0, "erro": None, "carregando": False, "proxima": 0.0,
                                        "disco_lido": False})
    assert fo.dados(agora=fo.time.time(), iniciar=lambda f: None)["strings_episodios"]   # sobe pelo disco


def test_leitura_que_nao_bate_com_a_atualizacao_nao_substitui_a_boa(monkeypatch, tmp_path):
    monkeypatch.setattr(fo, "CACHE", str(tmp_path / "c.json.gz"))
    boa = {"strings_episodios": ["boa"]}
    monkeypatch.setattr(fo, "_estado", {"dados": boa, "ts": 1.0, "erro": None, "carregando": True, "proxima": 0.0,
                                        "disco_lido": True})
    ruim = dict(ROWS)
    ruim[4] = [{"headers": ["mes", "strings_episodios", "trackers_episodios"], "values": ["2026-10", 5, 0]}]

    def get_ruim(caminho, tok):
        return SHEETS if caminho == "/api/sheets" else {"rows": ruim.get(int(caminho.split("/")[3]), [])}
    fo._recarrega(get=get_ruim, espera=0)
    assert fo._estado["dados"] is boa and "atualizacao" in fo._estado["erro"]
    assert fo._estado["carregando"] is False and fo._estado["proxima"] > 0


def test_cache_em_disco_de_antes_da_rodada_2_nao_sobe(monkeypatch, tmp_path):
    # o cache da rodada 1 (sem strings_os e trackers_dia) daria o card sem as OS até a 1ª recarga
    arq = tmp_path / "c.json.gz"
    velho = {k: [] for k, _ in fo.ABAS.values() if k not in ("strings_os", "trackers_dia")}
    with gzip.open(arq, "wt", encoding="utf-8") as f:
        json.dump({"ts": 1.0, "dados": velho}, f)
    monkeypatch.setattr(fo, "CACHE", str(arq))
    monkeypatch.setattr(fo, "_estado", {"dados": None, "ts": 0.0, "erro": None, "carregando": False, "proxima": 0.0,
                                        "disco_lido": False})
    assert fo.dados(agora=1000.0, iniciar=lambda f: None) is None


def test_cache_em_disco_sem_a_versao_da_rodada_3_nao_sobe(monkeypatch, tmp_path):
    # o cache da rodada 2 tem todas as abas, mas as rondas sem OS, itens e achados: a janela abriria vazia até a recarga
    arq = tmp_path / "c.json.gz"
    with gzip.open(arq, "wt", encoding="utf-8") as f:
        json.dump({"ts": 1.0, "dados": {k: [] for k, _ in fo.ABAS.values()}}, f)
    monkeypatch.setattr(fo, "CACHE", str(arq))
    monkeypatch.setattr(fo, "_estado", {"dados": None, "ts": 0.0, "erro": None, "carregando": False, "proxima": 0.0,
                                        "disco_lido": False})
    assert fo.dados(agora=1000.0, iniciar=lambda f: None) is None
    fo._grava_cache({k: [] for k, _ in fo.ABAS.values()}, 5.0)
    assert fo._le_cache()["ts"] == 5.0


def test_cache_em_disco_de_outra_versao_nao_sobe(monkeypatch, tmp_path):
    # um cache gravado antes de uma aba nova entrar em ABAS faria a rota cair em KeyError (500) até a 1ª recarga:
    # cache sem todas as chaves é como cache nenhum — a tela fica em "carregando" e a recarga traz o dado inteiro
    arq = tmp_path / "c.json.gz"
    with gzip.open(arq, "wt", encoding="utf-8") as f:
        json.dump({"ts": 1.0, "dados": {"strings_episodios": []}}, f)
    monkeypatch.setattr(fo, "CACHE", str(arq))
    monkeypatch.setattr(fo, "_estado", {"dados": None, "ts": 0.0, "erro": None, "carregando": False, "proxima": 0.0,
                                        "disco_lido": False})
    assert fo.dados(agora=1000.0, iniciar=lambda f: None) is None


def test_disponibilidade_do_dia_liga_a_usina_pelo_nome_do_fracttal():
    # rodada 4 (09/10): a aba disponibilidade_dia traz o nome do BD_Performance e o do Fracttal; o usina_id sai do
    # de-para do Nexus pelo nome do Fracttal, como as rondas
    sheets = SHEETS + [{"id": 10, "workbook_key": "falhas_performance", "sheet_name": "disponibilidade_dia", "row_count": 2}]
    rows = dict(ROWS)
    cab = ["mes", "dia", "cliente", "usina", "usina_fracttal", "pot_kwp", "disp", "h_perdidas"]
    rows[10] = [{"headers": cab, "values": ["2026-10", "2026-10-02", "Thopen", "Altair", "Thopen - Altair 1 - SP", 6898.0,
                                           95.8, 0.5]},
                {"headers": cab, "values": ["2026-10", "2026-10-02", "Athon", "SMP100", "Athon - SMP100", 100.0, 100.0, 0]}]

    def get(caminho, tok):
        return sheets if caminho == "/api/sheets" else {"rows": rows.get(int(caminho.split("/")[3]), [])}
    d = fo.baixar("", get)
    altair, smp = d["disponibilidade_dia"]
    assert altair["usina_ids"] == [1] and altair["disp"] == 95.8 and altair["h_perdidas"] == 0.5
    assert "cliente" not in altair
    assert smp["usina_ids"] == []


def test_parcela_da_os_no_dia_sem_o_numero_e_ligada_pelo_nome_do_fracttal():
    # 14/10 (Levi: "A partir de outubro quero os comentários 100% OS Fracttal"): o comentário do dia é a parcela de cada
    # OS na conta do Gerencial (disponibilidade_os_dia). O 5080 é público: o nº da OS e a origem não entram na memória
    # nem no disco; o kWp afetado, os trechos e as horas, sim. As OS do mês (disponibilidade_os) não são mais lidas
    sheets = SHEETS + [{"id": 11, "workbook_key": "falhas_performance", "sheet_name": "disponibilidade_os_dia",
                        "row_count": 1},
                       {"id": 12, "workbook_key": "falhas_performance", "sheet_name": "disponibilidade_os",
                        "row_count": 1}]
    rows = dict(ROWS)
    cab = ["mes", "dia", "usina", "usina_fracttal", "os", "tipo", "origem", "escopo", "kwp", "inicio", "fim", "aberta",
           "trechos", "h_perdidas"]
    rows[11] = [{"headers": cab, "values": ["2026-10", "2026-10-07", "Altair", "Thopen - Altair 1 - SP", "15692",
                                           "Religamento Remoto", "queda", "Usina inteira", 6898, "2026-10-07T12:55:00",
                                           "2026-10-07T12:57:00", "não", "12:55-12:57", 0.033]}]
    rows[12] = [{"headers": ["mes", "os", "usina"], "values": ["2026-10", "15692", "Altair"]}]

    def get(caminho, tok):
        return sheets if caminho == "/api/sheets" else {"rows": rows.get(int(caminho.split("/")[3]), [])}
    d = fo.baixar("", get)
    (o,) = d["disponibilidade_os_dia"]
    # o nº da OS entra desde 15/10/2026, à tarde (Levi: "invés de OS do fracttal quero o número desse OS")
    assert o == {"mes": "2026-10", "dia": "2026-10-07", "usina": "Altair", "usina_fracttal": "Thopen - Altair 1 - SP",
                 "os": "15692",
                 "tipo": "Religamento Remoto", "escopo": "Usina inteira", "kwp": 6898, "inicio": "2026-10-07T12:55:00",
                 "fim": "2026-10-07T12:57:00", "aberta": "não", "trechos": "12:55-12:57", "h_perdidas": 0.033,
                 "usina_ids": [1]}
    assert "disponibilidade_os" not in d and "queda" not in str(d)          # a origem não entra
