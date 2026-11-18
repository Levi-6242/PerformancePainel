# -*- coding: utf-8 -*-
"""Recoleta por fonte para a Coletas do Nexus (17/11/2026; Levi: "quero formas de coletar os dados novamente pelas nossas
fontes de dados e gerar uma planilha para colar nos BDs"). A base comum, a apipv e a chuva no formato do contrato e a
rota genérica. As fontes não são chamadas: tudo dublado."""
import datetime as dt
import types

import pytest

import app
import recoleta_apipv as rc
import recoleta_fontes
from recoleta_fontes import apipv as f_apipv, chuva as f_chuva, comum

HOJE = dt.date(2026, 11, 17)
EQUIP = [
    {"Usina Supervisório": "Ceilândia II - Pitangueira (89)", "Equipamento Supervisório": "INVERSOR 01",
     "Usina": "Ceilândia 2", "Equipamento": "Inversor 2.1"},
    {"Usina Supervisório": "Ceilandia II - Atena", "Equipamento Supervisório": "INVERSOR01",
     "Usina": "Ceilândia 2", "Equipamento": "Inversor 3.1"},
    {"Usina Supervisório": "Ceilandia II - Atena", "Equipamento Supervisório": "INVERSOR02",
     "Usina": "Ceilândia 2", "Equipamento": "Inversor 3.2"},
    {"Usina Supervisório": "Cascavel", "Equipamento Supervisório": "X", "Usina": "Cascavel (Sunpower)",
     "Equipamento": "Inversor 6,2"},
]


@pytest.fixture(autouse=True)
def _zera(monkeypatch):
    monkeypatch.setattr(comum, "_CONTA", {})


def test_mapa_pela_chave_do_coletor_e_sem_adivinhar():
    m = comum.Mapa(EQUIP)
    assert m.usina_de("Ceilandia II - Pitangueira") == "Ceilândia 2"
    assert m.inversor_de("Ceilândia II - Pitangueira", "INVERSOR01") == ("Ceilândia 2", "Inversor 2.1")
    assert m.inversor_de("Cascavel", "x") == ("Cascavel (Sunpower)", "Inversor 6.2")          # 6,2 = 6.2
    amb = comum.Mapa(EQUIP + [{"Usina Supervisório": "Ceilândia II - Atena", "Equipamento Supervisório": "INVERSOR 01",
                               "Usina": "Outra", "Equipamento": "Inversor 9.9"}])
    assert amb.inversor_de("Ceilandia II - Atena", "INVERSOR01") is None                      # duas grafias, dois destinos


@pytest.mark.parametrize("corpo, trecho", [
    ({"ids": ["1"], "ini": "2026-11-16", "fim": "2026-11-17", "geracao": True}, "só dia fechado"),
    ({"ids": ["1"], "ini": "2026-11-01", "fim": "2026-11-08", "geracao": True}, "no máximo 7 dias"),
    ({"ids": ["9"], "ini": "2026-11-10", "fim": "2026-11-10", "geracao": True}, "não conhece"),
    ({"ids": ["1"], "ini": "2026-11-10", "fim": "2026-11-10"}, "pelo menos"),
])
def test_validar(corpo, trecho):
    with pytest.raises(comum.Recusa) as e:
        comum.validar(corpo, ["1", "2"], 8, HOJE)
    assert e.value.status == 400 and trecho in str(e.value)


def test_dia_com_menos_da_metade_dos_inversores_e_fonte_fora():
    m = comum.Mapa(EQUIP)
    ger = [{"usina": "Ceilândia 2", "inversor": "Inversor 2.1", "data": "2026-11-10", "kwh": 500.0},
           {"usina": "Ceilândia 2", "inversor": "Inversor 3.1", "data": "2026-11-10", "kwh": 0.0},
           {"usina": "Ceilândia 2", "inversor": "Inversor 3.2", "data": "2026-11-10", "kwh": None},
           {"usina": "Ceilândia 2", "inversor": "Inversor 2.1", "data": "2026-11-11", "kwh": 500.0},
           {"usina": "Ceilândia 2", "inversor": "Inversor 3.1", "data": "2026-11-11", "kwh": 480.0}]
    r = comum.montar_resposta({"geracao": ger}, m, 3, 147, 150)
    assert r["dias_fora"] == [{"usina": "Ceilândia 2", "data": "2026-11-10"}]                # 1 de 3 com valor
    assert any("fonte fora do ar" in a for a in r["avisos"]) and r["consultas"] == 3
    assert len(r["geracao"]) == 4 and any("1 valor(es) sem leitura" in a for a in r["avisos"])  # o nulo sai
    # pedido de PARTE da aba (1 inversor de 3 no cadastro) com valor não é fonte fora
    assert comum.dias_fora([{"usina": "Ceilândia 2", "inversor": "Inversor 2.1", "data": "2026-11-12", "kwh": 9.0}]) == []


def test_teto_e_um_so_para_o_conversor_a_apipv_e_a_chuva(monkeypatch):
    monkeypatch.setattr(rc, "TETO_DIA", 10)
    rc.gastar(4, HOJE)                                                  # o Conversor (formato cru)
    assert comum.gastar("apipv", 3, 10, HOJE) == 3                      # a Coletas
    assert comum.restante("chuva", 10, HOJE) == 3                       # a chuva enxerga o mesmo saldo
    with pytest.raises(comum.Recusa):
        comum.gastar("chuva", 4, 10, HOJE)


def test_apipv_traduz_o_cru_para_o_contrato():
    m = comum.Mapa(EQUIP)
    cru = {"90": {"nome": "Ceilandia II - Atena", "dias": {
               "2026-11-10": {"ger": {"INVERSOR01": 700.0, "INVERSOR09": 5.0}, "ipoa": 6.5, "ghi": 5.0,
                              "chuva": 12.4, "chuva_conf": False}}},
           "89": {"nome": "Ceilândia II - Pitangueira (89)", "dias": {
               "2026-11-10": {"ger": {"INVERSOR 01": 812.46}, "ipoa": 6.1234, "ghi": None, "chuva": None},
               "2026-11-11": {"erro": "RuntimeError: API PV HTTP 502"}}}}
    r = f_apipv.traduzir(cru, m)
    assert sorted((g["inversor"], g["kwh"]) for g in r["geracao"]) == [("Inversor 2.1", 812.46), ("Inversor 3.1", 700.0)]
    esc = {(e["coluna"]): e["valor"] for e in r["escalares"]}
    assert esc == {"IPOA": 6.1234, "GHI": 5.0, "Chuva": 12.4}           # IPOA da 89 (1º id); GHI e chuva da 90
    txt = " | ".join(r["avisos"])
    assert "INVERSOR09" in txt and "não respondeu" in txt and "LARANJA" in txt


def test_chuva_pela_regra_do_coletor_e_nulo_sem_leitura():
    lei = [{"conteudojson": {"chuTotal": v, "Chu": 0}} for v in (1.0, 1.0, 4.5, 13.0)]
    assert rc.analisa_chuva(lei) == (12.0, True)
    assert rc.analisa_chuva(lei[:1]) == (None, True)                    # uma leitura não é dia: nulo, não 0
    vies = [{"conteudojson": {"chuTotal": v, "Chu": 0.2}} for v in range(12)]
    assert rc.analisa_chuva(vies)[1] is False                           # Chu cravado em 0,2: laranja
    assert rc.analisa_chuva([{"conteudojson": {"chuTotal": 0}}, {"conteudojson": {"chuTotal": 900}}]) == (None, False)


def test_custos():
    dias = [HOJE - dt.timedelta(days=k) for k in (3, 2)]
    assert f_apipv.custo(["1", "2"], dias, True, True, False) == 2 * (1 + 2 * 2)
    assert f_apipv.custo(["1"], dias, False, True, True) == 2                 # ETM e chuva na mesma consulta
    assert f_chuva.custo(["1"], dias, False, False, True) == 2


# ---------------------------------------------------------------- a rota genérica
class Falsa:
    FONTE, PAGA, MAX_PLANTAS, TETO = "falsa", True, 8, 20
    chamou = []
    recusa = None

    @staticmethod
    def contexto(app_):
        return types.SimpleNamespace(mapa=comum.Mapa(EQUIP))

    @staticmethod
    def plantas(ctx):
        return [{"id": "89", "usina": "Ceilândia 2", "destino": "BD_Thopen"}]

    @staticmethod
    def custo(ids, dias, g, e, c):
        return len(ids) * len(dias)

    @classmethod
    def permite(cls, ctx, n):
        return cls.recusa

    @classmethod
    def buscar(cls, ctx, ids, dias, g, e, c):
        cls.chamou.append((ids, [d.isoformat() for d in dias]))
        return {"geracao": [{"usina": "Ceilândia 2", "inversor": "Inversor 2.1", "data": "2026-11-10", "kwh": None}],
                "escalares": [], "avisos": []}


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(app, "PASSWORD", "senha-pv-de-teste")
    monkeypatch.delenv("RECOLETA_CHAVE", raising=False)
    monkeypatch.setattr(recoleta_fontes, "modulo", lambda f: Falsa if f == "falsa" else None)
    monkeypatch.setattr(comum, "hoje_br", lambda agora_utc=None: HOJE)
    Falsa.chamou, Falsa.recusa = [], None
    return app.app.test_client()


CAB = {"X-Recoleta-Chave": rc.chave_esperada("", "senha-pv-de-teste")}
CORPO = {"ids": ["89"], "ini": "2026-11-10", "fim": "2026-11-11", "geracao": True}


def test_rota_sem_chave_e_fonte_desconhecida(cli):
    assert cli.get("/api/recoleta/falsa/plantas").status_code == 401
    assert cli.get("/api/recoleta/xyz/plantas", headers=CAB).status_code == 404


def test_rota_simular_nao_busca_e_mostra_o_custo(cli):
    r = cli.post("/api/recoleta/falsa", json=dict(CORPO, simular=True), headers=CAB).get_json()
    assert r == {"consultas": 2, "cota_restante": 20, "teto": 20} and Falsa.chamou == []


def test_rota_busca_gasta_e_responde_o_contrato(cli):
    pl = cli.get("/api/recoleta/falsa/plantas", headers=CAB).get_json()
    assert pl["plantas"][0]["usina"] == "Ceilândia 2" and pl["paga"] is True and pl["max_dias"] == 7
    r = cli.post("/api/recoleta/falsa", json=CORPO, headers=CAB).get_json()
    assert Falsa.chamou == [(["89"], ["2026-11-10", "2026-11-11"])]
    assert r["consultas"] == 2 and r["cota_restante"] == 18 and r["geracao"] == []          # nulo não vai
    assert any("sem leitura" in a for a in r["avisos"])


def test_rota_fonte_paga_com_a_cota_na_reserva_e_429(cli):
    Falsa.recusa = "a cota está na reserva da coleta da noite"
    r = cli.post("/api/recoleta/falsa", json=CORPO, headers=CAB)
    assert r.status_code == 429 and "reserva" in r.get_json()["erro"] and Falsa.chamou == []


def test_apipv_formato_bd_vai_pela_rota_generica(cli, monkeypatch):
    monkeypatch.setattr(recoleta_fontes, "modulo", lambda f: Falsa if f == "apipv" else None)
    r = cli.post("/api/recoleta/apipv?formato=bd", json=CORPO, headers=CAB)
    assert r.status_code == 200 and "geracao" in r.get_json()


def test_chave_do_nexus_pela_nexus_sso_chave(cli, monkeypatch):
    sso = "x" * 40
    monkeypatch.setattr(app, "NEXUS_SSO_CHAVE", sso)
    nexus = {"X-Recoleta-Chave": rc.chave_do_nexus(sso)}
    assert cli.get("/api/recoleta/falsa/plantas", headers=nexus).status_code == 200
    assert cli.get("/api/recoleta/falsa/plantas", headers=CAB).status_code == 200          # a do Conversor segue valendo
    monkeypatch.setattr(app, "NEXUS_SSO_CHAVE", "")
    assert cli.get("/api/recoleta/falsa/plantas", headers=nexus).status_code == 401        # sem a SSO, não existe
    assert rc.chave_do_nexus("") == "" and rc.chave_do_nexus("curta") == ""
    assert cli.get("/api/recoleta/falsa/plantas", headers={"X-Recoleta-Chave": ""}).status_code == 401


def test_rotear_como_o_coletor():
    assert comum.rotear("Piracicaba I", "Inversor 1.1") == ("Piracicaba 1", "Inversor 1.1")
    assert comum.rotear("Ouro Branco", "Inversor 2.3") == ("Ouro Branco 2", "Inversor 1.3")
    assert comum.rotear("Altair", "Inversor 4.1") == ("Altair", "Inversor 4.1")
    m = comum.Mapa([{"Usina Supervisório": "OB", "Equipamento Supervisório": e, "Usina": "Ouro Branco",
                     "Equipamento": e} for e in ("Inversor 1.1", "Inversor 2.1")])
    assert comum.abas_de("Ouro Branco", m) == ["Ouro Branco 1", "Ouro Branco 2"]


def test_lista_da_api_pv_sai_da_ultima_boa_e_renova_em_fundo(monkeypatch):
    """18/11/2026: a lista de usinas da apipv/chuva levava 37,6 s cada vez que os 5 min do get_plants venciam. Agora sai
    da última lista boa na hora e renova em fundo; só a 1ª leitura do processo espera a API PV."""
    import time as _t
    chamadas = []

    def ler():
        chamadas.append(1)
        return {1: ("A", "A")} if len(chamadas) == 1 else {1: ("A", "A"), 2: ("B", "B")}
    monkeypatch.setattr(app, "_recoleta_plantas_ler", ler)
    monkeypatch.setattr(app, "_RECOLETA_PLANTAS", {"t": 0.0, "v": None, "renovando": False})
    assert app._recoleta_plantas(agora=1000.0) == {1: ("A", "A")} and len(chamadas) == 1     # 1ª: espera a fonte
    assert app._recoleta_plantas(agora=1100.0) == {1: ("A", "A")} and len(chamadas) == 1     # dentro dos 5 min
    assert app._recoleta_plantas(agora=1000.0 + app.CACHE_TTL + 1) == {1: ("A", "A")}       # vencida: a velha, na hora
    for _ in range(100):
        if not app._RECOLETA_PLANTAS["renovando"]:
            break
        _t.sleep(0.02)
    assert len(chamadas) == 2 and app._RECOLETA_PLANTAS["v"] == {1: ("A", "A"), 2: ("B", "B")}  # renovou em fundo
