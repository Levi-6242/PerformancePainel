# -*- coding: utf-8 -*-
"""Rondas do mês para o cliente (rodada 3, Levi, 09/10/2026): o que da ronda pode ir ao 5080 público e como a janela é
montada. Trava: o texto livre do técnico, as PENDÊNCIAS e a qualidade da ronda não chegam ao cliente; foto e dúvida só
de OS de ronda de usina do 5080, de 10/2026 em diante."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "thopen"))
import fonte_api  # noqa: E402
import rondas_cliente as rc  # noqa: E402

RESP = ("Computador: Ligado; Sujidade da vala de drenagem: Parcial; Sujidade dos módulos: 2; Altura da vegetação: 3; "
        "As luvas isolantes estão disponíveis?: Sim")
PEND = ("PENDÊNCIAS — ronda longa pendente; levantamento por zonas pendente: sujidade | ACHADOS — trincado: 1 ponto; "
        "praga: Pontual; sombreamento: Pontual")


def test_campos_guarda_checklist_e_achados_e_descarta_texto_livre():
    c = rc.campos(RESP, PEND, "Thopen - Guaratingueta 5 - SP")
    assert c["itens"][0] == ["Computador", "Ligado"] and ["As luvas isolantes estão disponíveis?", "Sim"] in c["itens"]
    assert c["achados"] == {"trincado": "1 ponto", "praga": "Pontual", "sombreamento": "Pontual"}
    assert c["unidade"] == "Guaratingueta 5"
    assert "ronda longa" not in str(c)
    # Caicó 02/10: o campo traz texto livre do técnico — não pode passar
    livre = rc.campos("", "Sujeira nos módulos, falta de água para banheiro", "Thopen - Caicó - RN")
    assert livre["achados"] == {} and "banheiro" not in str(livre) and livre["unidade"] == "Caicó"
    assert rc.campos("", "", "Thopen - Itajá 1 e 2 - RN")["unidade"] == "Itajá 1 e 2"


def _dados(*linhas, ids=(86,)):
    return {"rondas_com_os": list(linhas), "de_para": [{"usina_id": i, "chave_externa": "Guaratinguetá V"} for i in ids]}


def _r(os_, dia="2026-10-02", hi="10:13", hf="11:07", n=19, uid=86):
    return {"os": str(os_), "usina_id": uid, "dia": dia, "hora_inicio": hi, "hora_fim": hf, "n_fotos": n,
            "unidade": "Guaratingueta 5", "itens": [["Sujidade dos módulos", "2"]], "achados": {}}


def test_do_mes_em_brasilia_e_uma_os_por_ronda():
    d = _dados(_r(15176, n=19), _r(15177, n=21), _r(15300, dia="2026-10-01", hi="02:30", hf="03:00"),
               _r(14000, dia="2026-09-30", hi="12:00"))
    out = rc.do_mes(d, "Guaratinguetá V", 2026, 10)
    # 02:30 UTC de 01/10 = 23:30 de 30/09 em Brasília: fica fora de outubro; a ronda em duas OS fica na de mais fotos
    assert [(x["os"], x["dia"], x["inicio"], x["fim"]) for x in out] == [("15177", "2026-10-02", "07:13", "08:07")]
    assert rc.do_mes(d, "Altair", 2026, 10) == [] and rc.do_mes(None, "Guaratinguetá V", 2026, 10) == []


def test_da_os_so_de_usina_do_5080_e_de_outubro_em_diante():
    d = _dados(_r(15176), _r(14000, dia="2026-09-20"), _r(15999, uid=999))
    assert rc.da_os(d, 15176)["os"] == "15176" and rc.da_os(d, "15176") is not None
    assert rc.da_os(d, 14000) is None          # setembro: antes do card
    assert rc.da_os(d, 15999) is None          # usina fora do de-para do 5080 (outro cliente)
    assert rc.da_os(d, 1) is None and rc.da_os(None, 15176) is None and rc.da_os(d, "abc") is None


def test_detalhe_casa_foto_com_item_e_esconde_descricao_solta():
    r = dict(_r(15176), itens=rc.campos(RESP, PEND, "x")["itens"], achados={"trincado": "1 ponto", "praga": "Pontual"})
    descs = ["Sujidade dos módulos — 2", "Ronda 2026-10-02 — Thopen - Guaratingueta 5 - SP · qualidade 95%",
             "Módulo trincado — tr 09 · antes", "Pragas — pontual", "Zona valetas critica", "Sujidade dos módulos — 2"]
    d = rc.detalhe(r, descs)
    suj = next(i for i in d["itens"] if i["item"] == "Sujidade dos módulos")
    assert suj["nivel"] == 2 and suj["frase"].startswith("Sujeira leve") and suj["fotos"] == [0, 5]
    assert next(i for i in d["itens"] if i["item"] == "Computador")["nivel"] is None
    assert [(p["item"], p["resposta"], p["fotos"]) for p in d["pragas"]] == [
        ("Pragas", "Pontual", [3]), ("Dejeto de pássaro nos módulos", "Nenhum", []),
        ("Sombreamento por vegetação", "Nenhum", [])]
    assert [(o["item"], o["resposta"], o["fotos"]) for o in d["ocorrencias"]] == [("Módulo trincado", "1 ponto", [2])]
    assert d["outras"] == [1, 4]
    # a capa leva a qualidade da ronda e a descrição solta pode ser texto do técnico: nenhuma das duas sai
    assert d["fotos"][1] == {"i": 1, "item": "Capa da ronda", "resposta": ""}
    assert d["fotos"][4] == {"i": 4, "item": "Foto da ronda", "resposta": ""}
    assert "qualidade" not in str(d) and "valetas" not in str(d)
    assert (d["os"], d["inicio"]) == ("15176", "07:13")


def test_detalhe_sem_foto_nenhuma():
    d = rc.detalhe(_r(15176), [])
    assert d["fotos"] == [] and d["outras"] == [] and d["itens"][0]["fotos"] == []
    assert [o for o in d["ocorrencias"]] == []                 # trincado só aparece quando o App achou


def test_segredo_ambiente_primeiro_depois_env_da_raiz(monkeypatch, tmp_path):
    monkeypatch.setattr(fonte_api, "_AQUI", str(tmp_path / "thopen"))
    (tmp_path / ".env").write_text('X_TESTE="do-arquivo"\nOUTRA=1\n', encoding="utf-8")
    monkeypatch.delenv("X_TESTE", raising=False)
    assert fonte_api.segredo("X_TESTE") == "do-arquivo" and fonte_api.segredo("NAO_TEM") == ""
    monkeypatch.setenv("X_TESTE", "do-ambiente")
    assert fonte_api.segredo("X_TESTE") == "do-ambiente"


# ── Fonte dinâmica (Levi, 09/10/2026: "as rondas já foram atualizadas até hoje porém no server não está atualizando,
# tem que ser dinâmico"): o livro do App `rondas_app_campo · OS de ronda`, regravado de hora em hora, no lugar do
# `campo_nexus · rondas` (coletor do Nexus parado em 02/10) e da carga única das rondas sem OS (06/10).
DE_PARA = [
    {"usina_id": 86, "sistema": "BD_Performance · Base UFV", "chave_externa": "THPN-GTA500"},
    {"usina_id": 86, "sistema": "Fracttal · Classificação 1", "chave_externa": "Thopen - Guaratingueta 5 - SP"},
    {"usina_id": 86, "sistema": "BD_Thopen · Dados Gerais Usinas", "chave_externa": "Guaratinguetá V"},
    {"usina_id": 7, "sistema": "Fracttal · Classificação 1", "chave_externa": "Thopen - Salto Pirapora 3 - SP"},
]
APP = {"Data": "2026-10-07", "OS": "15654", "Usina": "Thopen - Guaratingueta 5 - SP", "Ativo da usina no Fracttal":
       "THPN-GTA500", "Técnico": "Fulano de Tal", "Técnico (HMAC)": "347b", "Nota da ronda": "95",
       "Falhas": "ronda longa pendente", "Início": "2026-10-07T10:37:12.100Z", "Fim": "2026-10-07T11:20:00.000Z",
       "Sujidade dos módulos (1 a 5)": "2", "Altura da vegetação (1 a 5)": "2",
       "Checklist da ronda": "Computador: Ligado; Sujidade dos módulos: 2 [Poeira / areia]; Altura da vegetação: 2"}


def test_rondas_do_app_ganham_usina_id_pelo_codigo_ou_pelo_nome_e_nada_do_tecnico():
    mapa = rc.mapa_usinas(DE_PARA)
    (r,) = rc.da_app(APP, mapa)
    assert r == {"os": "15654", "usina_id": 86, "dia": "2026-10-07", "hora_inicio": "10:37", "hora_fim": "11:20",
                 "sujidade": 2, "vegetacao": 2, "unidade": "Guaratingueta 5", "achados": {},
                 "itens": [["Computador", "Ligado"], ["Sujidade dos módulos", "2", "Poeira / areia"],
                           ["Altura da vegetação", "2"]]}
    assert "Fulano" not in str(r) and "longa" not in str(r) and "347b" not in str(r) and "95" not in str(r.values())
    # código do ativo que não casa (Salto Pirapora: "SPP300-ETKR1"): vale o nome do Fracttal
    (s,) = rc.da_app(dict(APP, Usina="Thopen - Salto Pirapora 3 - SP", **{"Ativo da usina no Fracttal": "SPP300-ETKR1"}),
                     mapa)
    assert s["usina_id"] == 7
    assert rc.da_app(dict(APP, Usina="Outra - X - SP", **{"Ativo da usina no Fracttal": "OUT100"}), mapa) == []
    assert rc.da_app(dict(APP, **{"Início": None}), mapa) == []        # sem hora não dá o dia em Brasília: não chuta
    (n,) = rc.da_app(dict(APP, OS=None), mapa)                          # OS não criada: vale para a zeladoria
    assert n["os"] is None and n["sujidade"] == 2


def test_achado_sem_o_texto_do_livro_vem_da_foto():
    r = dict(_r(15654), itens=[["Computador", "Ligado"]], achados={})
    d = rc.detalhe(r, ["Pragas — pontual", "Módulo trincado — tr 09 · antes", "Computador — ligado"])
    assert [(p["item"], p["resposta"], p["fotos"]) for p in d["pragas"]] == [
        ("Pragas", "Pontual", [0]), ("Dejeto de pássaro nos módulos", "Nenhum", []),
        ("Sombreamento por vegetação", "Nenhum", [])]
    assert [(o["item"], o["resposta"], o["fotos"]) for o in d["ocorrencias"]] == [("Módulo trincado", "Tr 09 · antes", [1])]


def test_tipo_de_sujidade_vai_junto_do_nivel():
    r = dict(_r(15654), itens=[["Sujidade dos módulos", "2", "Poeira / areia"]])
    (s,) = rc.detalhe(r, [])["itens"]
    assert (s["nivel"], s["obs"]) == (2, "Poeira / areia") and s["frase"].startswith("Sujeira leve")
