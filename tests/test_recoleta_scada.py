# -*- coding: utf-8 -*-
"""Recoleta pelo scadaGridco para a Coletas do Nexus (17/11/2026; Levi: "quero formas de coletar os dados novamente pelas
nossas fontes de dados e gerar uma planilha para colar nos BDs").

A regra é a do coletor da noite (coleta API PV/src/coletar_greenyellow.py), portada: leitura antes das 05h não conta
(o contador da madrugada traz a véspera, Irecê 2 29/09/2026), sem leitura boa depois das 16h o dia ficou pela metade
(nulo e aviso, nunca zero), o maior contador depois de o inversor ligar (a Cedro zera à noite, 12/10/2026) e a ETM só da
Cedro. O supervisório é DUBLADO: nenhuma chamada sai da máquina."""
import ast
import datetime as dt
import os
import types

import pytest
import requests

import scadagridco as sg
from recoleta_fontes import comum
from recoleta_fontes import scada as sc

HOJE = dt.date(2026, 11, 17)
D1, D2 = dt.date(2026, 11, 10), dt.date(2026, 11, 11)
COLETOR = os.environ.get("COLETOR_GREENYELLOW") or os.path.join(
    os.path.expanduser("~"), "OneDrive - GRID CO", "Área de Trabalho", "temp", "coleta API PV", "src",
    "coletar_greenyellow.py")


@pytest.fixture(autouse=True)
def _sem_rede(monkeypatch):
    """Nenhum teste daqui chega ao supervisório de verdade: o cliente da plataforma quebra se for chamado."""
    def proibido(*_a, **_k):
        raise AssertionError("o teste tentou chamar o scadaGridco de verdade")
    monkeypatch.setattr(sg._SESSAO, "get", proibido)
    monkeypatch.setattr(requests, "get", proibido)


def _reg(hhmm, energia=None, pot=None, fault=192, equip="1", dia=D1, campo="total_daily_energy", tipo="inverter"):
    pontos = {}
    if energia is not None:
        pontos[campo] = energia
    if pot is not None:
        pontos["active_power"] = pot
    return {"equipamento": equip, "tipo": tipo, "communication_fault": fault,
            "data_hora": "%s %s:00" % (dia.isoformat(), hhmm), "pontos": pontos}


def _dia_inteiro(equip, kwh, dia=D1):
    """Um inversor que leu o dia todo: a véspera de madrugada, liga às 06h, termina às 17:30."""
    return [_reg("04:10", 950.0, 0.0, equip=equip, dia=dia), _reg("06:00", 0.4, 2.0, equip=equip, dia=dia),
            _reg("12:00", kwh / 2, 80.0, equip=equip, dia=dia), _reg("17:30", kwh, 0.0, equip=equip, dia=dia)]


class Scada:
    """Dublê do `scadagridco.get`: devolve o que o teste mandar e anota cada chamada."""

    def __init__(self, tele=None, mqtt=None, erro=None, erro_equip=(), relogio=None):
        self.tele = tele or {}              # (usina, equipamento, dia ISO, tipo) -> [registros]
        self.mqtt = mqtt or {}              # usina -> [equipamentos inverter]
        self.erro, self.erro_equip, self.relogio = erro, set(erro_equip), relogio
        self.feitas = []

    def __call__(self, rota, params=None, timeout=None):
        self.feitas.append((rota, dict(params or {}), timeout))
        if self.relogio is not None:
            self.relogio.t += 10.0          # cada chamada leva 10 s
        if self.erro:
            raise self.erro
        if rota.startswith("/api/mqtt/"):
            u = rota.rsplit("/", 1)[1]
            return {"equipamentos": [{"equipamento": e, "tipo": "inverter"} for e in self.mqtt.get(u, [])]
                    + [{"equipamento": "estacao-poa", "tipo": "weather"}, {"equipamento": "rele-1", "tipo": "relay"}]}
        assert rota == "/api/telemetria" and params["desde"] == params["ate"]
        if params["equipamento"] in self.erro_equip:
            raise requests.ConnectionError("caiu")
        k = (params["usina"], params["equipamento"], params["desde"], params["tipo"])
        return {"registros": self.tele.get(k, []), "proximo_apos_ts": None}

    def telemetrias(self):
        return [p for r, p, _t in self.feitas if r == "/api/telemetria"]


class Relogio:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _ctx(api, relogio=None, configurado=True):
    return types.SimpleNamespace(mapa=comum.Mapa([]), get=api, configurado=lambda: configurado,
                                 sem_acesso=sg.SemAcesso, hoje=lambda: HOJE, relogio=relogio or (lambda: 0.0))


def _por_coluna(res, usina, dia=D1):
    return {r["inversor"]: r["kwh"] for r in res["geracao"] if r["usina"] == usina and r["data"] == dia.isoformat()}


# ── Contrato ────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_contrato_e_as_plantas_do_coletor_da_noite():
    assert (sc.FONTE, sc.PAGA, sc.TETO) == ("scada", False, None) and sc.MAX_PLANTAS >= 1
    assert sc.custo(["cedro_1"], [D1], True, True, False) == 0
    pl = sc.plantas(None)
    assert {p["usina"] for p in pl} == {"Castelo do Piauí", "Demerval Lobão", "Irece 2", "Cedro 1", "Cedro 2",
                                        "Gravatá II", "Iramaia II", "Rio do Peixe I e II", "Marialva", "PEII", "PEIII"}
    assert len({p["id"] for p in pl}) == len(pl) == 11
    assert all(p["destino"] == "BD_Performance" and isinstance(p["id"], str) for p in pl)
    ids = {p["usina"]: p["id"] for p in pl}
    assert ids["Cedro 1"] == "cedro_1" and ids["Cedro 2"] == "cedro_2" and ids["PEII"] == "pe_ii"


def test_contexto_usa_o_cliente_e_o_mapa_da_plataforma():
    mapa = comum.Mapa([])
    app = types.SimpleNamespace(_sg=sg, _recoleta_mapa=lambda: mapa)
    ctx = sc.contexto(app)
    assert ctx.mapa is mapa
    assert ctx.get is sg.get                       # o get() que segura o _LOCK: uma chamada por vez
    assert ctx.configurado is sg.configurado and ctx.sem_acesso is sg.SemAcesso
    assert ctx.hoje is comum.hoje_br


# ── A régua do coletor ─────────────────────────────────────────────────────────────────────────────────────────────
def test_leitura_antes_das_05h_nao_conta():
    """De madrugada o contador ainda traz a véspera (Irecê 2, 29/09/2026), mesmo com potência."""
    regs = [_reg("04:10", 950.0, 0.0), _reg("04:50", 950.0, 3.0), _reg("06:00", 0.4, 2.0),
            _reg("12:00", 400.0, 80.0), _reg("17:30", 812.346, 0.0)]
    assert sc.energia_do_dia(regs) == 812.346
    api = Scada(tele={("marialva", "1", "2026-11-10", "inverter"): regs})
    res = sc.buscar(_ctx(api), ["marialva"], [D1], True, False, False)
    assert _por_coluna(res, "Marialva")["Inversor 1.1"] == 812.35


def test_maior_contador_depois_de_ligar_e_nao_o_ultimo():
    """A Cedro zera o daily_active_energy quando desliga (12/10/2026: 570,6 ao meio-dia, 0,0 às 23:57)."""
    regs = [_reg("06:00", 0.0, 1.0, campo="daily_active_energy"), _reg("12:00", 570.6, 90.0, campo="daily_active_energy"),
            _reg("23:57", 0.0, 0.0, campo="daily_active_energy")]
    assert sc.energia_do_dia(regs) == 570.6


def test_dia_sem_leitura_depois_das_16h_vira_aviso_e_nulo():
    metade = [_reg("06:00", 0.3, 2.0), _reg("12:00", 300.0, 80.0), _reg("15:40", 420.0, 30.0),
              _reg("17:00", 600.0, 0.0, fault=28)]           # leitura ruim depois das 16h não salva o dia
    api = Scada(tele={("marialva", "1", "2026-11-10", "inverter"): metade,
                      ("marialva", "2", "2026-11-10", "inverter"): _dia_inteiro("2", 700.0)})
    res = sc.buscar(_ctx(api), ["marialva"], [D1], True, False, False)
    col = _por_coluna(res, "Marialva")
    assert col["Inversor 1.1"] is None and col["Inversor 1.2"] == 700.0
    av = [a for a in res["avisos"] if a.startswith("Marialva 2026-11-10")]
    assert len(av) == 1 and "7 de 8 inversores sem valor (fica nulo, não zero)" in av[0]
    assert "antes das 16h): Inversor 1.1 (até 15:40)" in av[0]
    assert "sem leitura boa depois das 05h: Inversor 1.3" in av[0]


def test_nulo_nao_vira_zero_e_zero_medido_fica_zero():
    sem_contador = [_reg("06:00", "-", 0.0), _reg("17:00", "-", 0.0)]      # "-" = ponto sem sensor
    zero_medido = [_reg(h, 0.0, 0.0, equip="2") for h in ("06:00", "12:00", "17:00")]
    api = Scada(tele={("pe_iii", "1", "2026-11-10", "inverter"): sem_contador,
                      ("pe_iii", "2", "2026-11-10", "inverter"): zero_medido})
    res = sc.buscar(_ctx(api), ["pe_iii"], [D1], True, False, False)
    col = _por_coluna(res, "PEIII")
    assert len(col) == 10                                   # todo inversor do de-para sai, com valor ou nulo
    assert col["Inversor 1.1"] is None and col["Inversor 1.3"] is None
    assert col["Inversor 1.2"] == 0.0 and isinstance(col["Inversor 1.2"], float)
    assert sum(1 for v in col.values() if v == 0) == 1      # só o que mediu zero; o nulo não virou 0
    # o comum vê o dia sem nenhum inversor com valor como fonte fora do ar (não sugerir)
    resp = comum.montar_resposta(res, comum.Mapa([]), 0, None, None)
    assert resp["dias_fora"] == [{"usina": "PEIII", "data": "2026-11-10"}]


def test_traducao_para_a_coluna_do_bd_pelo_de_para_do_coletor():
    """A coluna é a do BD (a do coletor), não a do cadastro do tempo real: na Rio do Peixe o 16 é o Inversor 3.5 do BD
    (no scadagridco.FONTES seria o 2.5) e o 15, cópia do 14, fica de fora."""
    assert sc.USINAS["Castelo do Piauí"]["inversores"]["inversor-02-12"] == "Inversor 2.2"
    api = Scada(tele={("rio_do_peixe_1_2", "6", "2026-11-10", "inverter"): _dia_inteiro("6", 610.0),
                      ("rio_do_peixe_1_2", "16", "2026-11-10", "inverter"): _dia_inteiro("16", 716.0),
                      ("rio_do_peixe_1_2", "21", "2026-11-10", "inverter"): _dia_inteiro("21", 721.0),
                      ("cedro", "inversor-03-12", "2026-11-10", "inverter"): _dia_inteiro("inversor-03-12", 503.0)},
                mqtt={"rio_do_peixe_1_2": [str(i) for i in range(1, 23)],
                      "cedro": ["inversor-%02d" % i for i in range(1, 11)] + ["inversor-%02d-12" % i for i in range(1, 11)]})
    res = sc.buscar(_ctx(api), ["rio_do_peixe_1_2", "cedro_2"], [D1], True, False, False)
    rp = _por_coluna(res, "Rio do Peixe I e II")
    assert (rp["Inversor 2.1"], rp["Inversor 3.5"], rp["Inversor 4.5"]) == (610.0, 716.0, 721.0)
    assert len(rp) == 20 and "15" not in {p["equipamento"] for p in api.telemetrias()}
    assert _por_coluna(res, "Cedro 2")["Inversor 1.3"] == 503.0
    assert "Cedro 1" not in {r["usina"] for r in res["geracao"]}
    av = " | ".join(res["avisos"])
    assert "Rio do Peixe I e II: equipamento(s) 22 do supervisório sem de-para" in av
    assert "o equipamento 15 do supervisório fica de fora: cópia do 14" in av
    assert "Cedro 1 e Cedro 2: equipamento" not in av       # os 20 da "cedro" estão no de-para das duas


def test_etm_da_cedro_uma_chamada_para_as_duas_e_zero_o_dia_todo_e_nulo():
    poa = [_reg("04:00", 7000.0, campo="irradiation_poa", equip="estacao-poa", tipo="weather"),   # véspera
           _reg("10:00", 3000.0, campo="irradiation_poa", equip="estacao-poa", tipo="weather"),
           _reg("12:00", 1193046.0, campo="irradiation_poa", equip="estacao-poa", tipo="weather"),  # lixo do sensor
           _reg("17:00", 6500.0, campo="irradiation_poa", equip="estacao-poa", tipo="weather")]
    ghi = [_reg(h, 0.0, campo="irradiation_ghi", equip="estacao-ghi", tipo="weather") for h in ("08:00", "17:00")]
    api = Scada(tele={("cedro", "estacao-poa", "2026-11-10", "weather"): poa,
                      ("cedro", "estacao-ghi", "2026-11-10", "weather"): ghi})
    res = sc.buscar(_ctx(api), ["cedro_1", "cedro_2", "marialva"], [D1], False, True, False)
    esc = {(e["usina"], e["coluna"]): e["valor"] for e in res["escalares"]}
    assert esc == {("Cedro 1", "IPOA (kWh/m²)"): 6.5, ("Cedro 1", "GHI (kWh/m²)"): None,
                   ("Cedro 2", "IPOA (kWh/m²)"): 6.5, ("Cedro 2", "GHI (kWh/m²)"): None}
    assert all(e["data"] == "2026-11-10" for e in res["escalares"])
    assert len(api.feitas) == 2                             # POA e GHI uma vez para as duas Cedro; sem mqtt, sem inversor
    av = " | ".join(res["avisos"])
    assert "Cedro 1 2026-11-10 GHI (kWh/m²):" in av and "fica nulo" in av
    assert "Marialva: sem ETM por esta fonte" in av
    assert res["geracao"] == []


# ── O que é da recoleta ────────────────────────────────────────────────────────────────────────────────────────────
def test_mais_de_45_dias_vira_aviso_sem_chamada():
    velho, limite = HOJE - dt.timedelta(days=46), HOJE - dt.timedelta(days=45)
    api = Scada()
    res = sc.buscar(_ctx(api), ["marialva"], [velho, limite], True, False, False)
    assert {p["desde"] for p in api.telemetrias()} == {limite.isoformat()}
    assert any("%s fora do histórico do scadaGridco (ele guarda 45 dias)" % velho.isoformat() in a
               for a in res["avisos"])
    assert {r["data"] for r in res["geracao"]} == {limite.isoformat()}


def test_so_vazio_ou_maior_vira_aviso_so_nas_abas_dele():
    res = sc.buscar(_ctx(Scada()), ["marialva", "castelo_do_piaui"], [D1], True, False, False)
    av = [a for a in res["avisos"] if "só vazio ou maior" in a]
    assert len(av) == 1 and av[0].startswith("Marialva:")


def test_cada_chamada_pelo_get_da_plataforma_com_timeout_e_um_inversor_por_pedido():
    api = Scada()
    sc.buscar(_ctx(api), ["marialva"], [D1], True, False, False)
    assert api.feitas[0][0] == "/api/mqtt/marialva"
    tel = api.telemetrias()
    assert [p["equipamento"] for p in tel] == [str(i) for i in range(1, 9)]
    assert all(p["usina"] == "marialva" and p["tipo"] == "inverter" and p["limit"] == sc.LIMITE for p in tel)
    assert {t for _r, _p, t in api.feitas} == {sc.TIMEOUT_S}


def test_paginacao_pelo_apos_ts():
    paginas = {None: {"registros": [_reg("06:00", 1.0, 1.0), _reg("06:00", 9.0, 9.0, equip="2")],
                      "proximo_apos_ts": 111},
               111: {"registros": [_reg("17:00", 5.0, 0.0)], "proximo_apos_ts": None}}
    pedidos = []

    def get(rota, p):
        pedidos.append(p.get("apos_ts"))
        return paginas[p.get("apos_ts")]
    regs = sc._telemetria(get, "marialva", "1", "2026-11-10")
    assert pedidos == [None, 111] and len(regs) == 2       # o registro de outro equipamento fica fora


def test_sem_token_recusa_e_token_recusado_para_tudo():
    api = Scada()
    with pytest.raises(comum.Recusa) as e:
        sc.buscar(_ctx(api, configurado=False), ["marialva"], [D1], True, False, False)
    assert e.value.status == 503 and api.feitas == []
    api = Scada(erro=sg.SemAcesso("scadaGridco recusou o token (HTTP 302)"))
    with pytest.raises(comum.Recusa) as e:
        sc.buscar(_ctx(api), ["marialva"], [D1], True, False, False)
    assert e.value.status == 502 and "302" in str(e.value)


def test_orcamento_de_tempo_para_entre_plantas_dias_sem_dia_pela_metade():
    rel = Relogio()
    api = Scada(tele={("marialva", str(i), d.isoformat(), "inverter"): _dia_inteiro(str(i), 100.0 + i, d)
                      for i in range(1, 9) for d in (D1, D2)}, relogio=rel)
    res = sc.buscar(_ctx(api, relogio=rel), ["marialva"], [D1, D2], True, False, False)
    assert len(api.feitas) == 9                             # mqtt + 8 inversores do 1º dia = 90 s > 75 s
    assert {r["data"] for r in res["geracao"]} == {"2026-11-10"} and len(res["geracao"]) == 8
    assert any(a.startswith("Marialva: 2026-11-11 não buscado(s): o pedido passou de 75 s") for a in res["avisos"])


def test_supervisorio_fora_para_o_resto_e_inversor_que_falha_sozinho_fica_nulo():
    api = Scada(erro=requests.ConnectionError("fora"))
    res = sc.buscar(_ctx(api), ["marialva"], [D1, D2], True, False, False)
    assert len(api.feitas) == sc.FALHAS_SEGUIDAS            # mqtt + 2 inversores, e para
    assert res["geracao"] == []                             # a planta-dia em curso não sai pela metade
    assert any("2026-11-10, 2026-11-11 não buscado(s): o scadaGridco não respondeu em 3 chamadas seguidas" in a
               for a in res["avisos"])
    api = Scada(tele={("marialva", "1", "2026-11-10", "inverter"): _dia_inteiro("1", 500.0)}, erro_equip={"2"})
    res = sc.buscar(_ctx(api), ["marialva"], [D1], True, False, False)
    col = _por_coluna(res, "Marialva")
    assert col["Inversor 1.1"] == 500.0 and col["Inversor 1.2"] is None
    assert any("erro na leitura (ConnectionError): Inversor 1.2" in a for a in res["avisos"])


# ── Igual ao coletor da noite ──────────────────────────────────────────────────────────────────────────────────────
def _do_coletor():
    """A configuração e as funções puras do coletor, lidas do arquivo dele sem importá-lo (o import puxa o config e a
    rede da coleta)."""
    if not os.path.exists(COLETOR):
        pytest.skip("coletar_greenyellow.py não está nesta máquina")
    with open(COLETOR, encoding="utf-8") as fh:
        arv = ast.parse(fh.read())
    nomes = {"COM_OK", "HORA_MIN", "HORA_FIM_DIA", "LIMITE", "USINAS", "ETM", "TETO_WH_M2"}
    funcs = {"_num", "energia_do_dia", "irradiacao_do_dia", "abas_so_vazio_ou_maior"}
    corpo = [n for n in arv.body
             if (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in nomes for t in n.targets))
             or (isinstance(n, ast.FunctionDef) and n.name in funcs)]
    ns = {}
    exec(compile(ast.Module(body=corpo, type_ignores=[]), COLETOR, "exec"), ns)
    return ns


def test_igual_ao_coletor_da_noite():
    """A porta não diverge em silêncio: mudou o coletar_greenyellow.py, este teste quebra até mudar aqui também."""
    c = _do_coletor()
    assert sc.USINAS == c["USINAS"] and sc.ETM == c["ETM"]
    assert (sc.COM_OK, sc.HORA_MIN, sc.HORA_FIM_DIA, sc.LIMITE, sc.TETO_WH_M2) == \
        (c["COM_OK"], c["HORA_MIN"], c["HORA_FIM_DIA"], c["LIMITE"], c["TETO_WH_M2"])
    assert {a for a, cfg in sc.USINAS.items() if cfg.get("so_vazio_ou_maior")} == c["abas_so_vazio_ou_maior"]()
    casos = [_dia_inteiro("1", 812.346), [], [_reg("06:00", 0.3, 2.0), _reg("15:40", 420.0, 30.0)],
             [_reg("06:00", "-", 0.0), _reg("17:00", "-", 0.0)], [_reg("17:00", 600.0, 0.0, fault=28)],
             [_reg("06:00", 0.0, 1.0, campo="daily_active_energy"), _reg("12:00", 570.6, 90.0, campo="daily_active_energy"),
              _reg("23:57", 0.0, 0.0, campo="daily_active_energy")],
             [_reg("04:50", 950.0, 3.0), _reg("10:00", 10.0, 0.0), _reg("16:00", 20.0, 0.0)]]
    for regs in casos:
        assert sc.energia_do_dia(regs) == c["energia_do_dia"](regs)
    est = [_reg("04:00", 7000.0, campo="irradiation_poa"), _reg("12:00", 1193046.0, campo="irradiation_poa"),
           _reg("17:00", 6500.0, campo="irradiation_poa")]
    for regs in (est, est[:2], [_reg("17:00", 0.0, campo="irradiation_poa")]):
        assert sc.irradiacao_do_dia(regs, "irradiation_poa") == c["irradiacao_do_dia"](regs, "irradiation_poa")
