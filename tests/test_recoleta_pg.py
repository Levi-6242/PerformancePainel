# -*- coding: utf-8 -*-
"""Recoleta pelo banco da Thopen (recoleta_fontes/pg.py, 17/11/2026). O banco é DUBLADO: nada sai para o PG.

A régua de energia é o porte da do coletor da noite (coletar_pg.energia_por_dia), e régua errada não dá erro, deforma
— por isso a bateria é por MODO DE FALHA, cada um com a série montada como o caso real que o coletor documenta (lá a
bateria roda contra o banco; aqui a série é feita à mão no mesmo desenho)."""
import datetime as dt
import types

import pytest

from recoleta_fontes import comum
from recoleta_fontes import pg

D = dt.date(2026, 9, 1)
ONTEM, AMANHA = D - dt.timedelta(days=1), D + dt.timedelta(days=1)


def ts(dia, hh, mm=0):
    return dt.datetime(dia.year, dia.month, dia.day, hh, mm)


def a_cada_5(dia, h0, m0, h1, m1, valor):
    """[(ts, valor(k, n))] de 5 em 5 min, de h0:m0 a h1:m1 inclusive; valor recebe (k, n)."""
    t, fim, out = ts(dia, h0, m0), ts(dia, h1, m1), []
    n = int((fim - t).total_seconds() // 300)
    for k in range(n + 1):
        out.append((t + dt.timedelta(minutes=5 * k), valor(k, n)))
    return out


def subida(de, ate):
    """Rampa com uma casa decimal, como o contador do inversor (nunca desce por arredondamento)."""
    return lambda k, n: round(de + (ate - de) * k / max(n, 1), 1)


def plano(v):
    return lambda k, n: v


def energia(serie, dia=D):
    return pg.energia_da_serie(serie, dia, dia).get(dia)


# ---------------------------------------------------------------- a régua de energia, modo a modo
def test_contador_que_zera_as_06h_nao_herda_a_vespera():
    """Aparecida do Taboado 1, 01/09: 421,4 parado até 05:55 (total do 31/08), zera às 06:00, sobe a 67,1 às 18:00.
    O MAX gravou 421,4; o certo é 67,1."""
    s = (a_cada_5(ONTEM, 6, 0, 18, 0, subida(0, 421.4)) + a_cada_5(ONTEM, 18, 5, 23, 55, plano(421.4))
         + a_cada_5(D, 0, 0, 5, 55, plano(421.4)) + a_cada_5(D, 6, 0, 18, 0, subida(0, 67.1))
         + a_cada_5(D, 18, 5, 23, 55, plano(67.1)) + [(ts(AMANHA, 0, 0), 67.1)])
    assert energia(s) == 67.1                    # exato: a conta é em Decimal, como o numeric do PG


def test_reset_no_meio_do_dia_soma_os_dois_trechos():
    """Santo Inácio XII: o contador não zera na meia-noite, zera às 13:00. Último valor dava a sobra (50); MAX, 400.
    A 1ª leitura depois do zeramento já tem 2,5 kWh: o trecho novo entra INTEIRO, não só o que subiu depois dela."""
    s = (a_cada_5(ONTEM, 13, 0, 23, 55, subida(0, 80.0)) + a_cada_5(D, 0, 0, 12, 0, subida(80.0, 400.0))
         + a_cada_5(D, 12, 5, 12, 55, plano(400.0)) + a_cada_5(D, 13, 0, 23, 55, subida(2.5, 50.0)))
    assert energia(s) == pytest.approx(320.0 + 50.0)


def test_zero_fantasma_nao_dobra_o_dia():
    """Ipixuna 1, 22:15 de 01/09: 0,0 isolado entre dois 748,3. Contado como reset, o dia ia a 1.496,6."""
    s = ([(ts(ONTEM, 23, 55), 690.0)] + a_cada_5(D, 0, 0, 5, 55, plano(0.0)) + a_cada_5(D, 6, 0, 18, 0, subida(0, 748.3))
         + a_cada_5(D, 18, 5, 23, 55, plano(748.3)))
    s = [(t, 0.0 if t == ts(D, 22, 15) else v) for t, v in s]
    assert energia(s) == 748.3


def test_buraco_atravessando_a_virada_vale_o_acumulado_do_dia():
    """Guaratinguetá V, 26/08: nada até 18:10, e o valor de lá (687,6) é o dia inteiro — como delta perdia 6,1 MWh."""
    s = a_cada_5(ONTEM, 6, 0, 18, 0, subida(0, 650.0)) + a_cada_5(D, 18, 10, 23, 55, plano(687.6))
    assert energia(s) == 687.6


def test_contador_congelado_na_volta_do_buraco_nao_conta():
    """Ibaté 1: travado em 1107,66 do dia 31/08 até as 11:00 de 01/09; os reais do dia foram 128,82."""
    s = (a_cada_5(ONTEM, 6, 0, 18, 0, subida(0, 1107.66)) + a_cada_5(ONTEM, 18, 5, 20, 0, plano(1107.66))
         + a_cada_5(D, 11, 0, 11, 5, plano(1107.66)) + a_cada_5(D, 11, 10, 18, 0, subida(0, 128.82)))
    assert energia(s) == pytest.approx(128.8, abs=0.05)        # a rampa arredonda a 1 casa: o topo é 128,8
    assert energia(s) < 1107.66                                # contar o travado inventava 1,1 MWh


def test_dia_so_com_contador_travado_nao_responde():
    """Marajoara I, 02/09: 72 leituras com 0 e 213,62 e nenhum incremento. Devolver 0 apagaria 2,2 MWh por inversor que
    o BD já tinha: o dia sai SEM resposta."""
    s = a_cada_5(ONTEM, 6, 0, 18, 0, subida(0, 213.62)) + a_cada_5(ONTEM, 18, 5, 23, 55, plano(213.62))
    s += [(ts(D, 0, 0) + dt.timedelta(minutes=20 * k), 0.0 if k % 9 == 4 else 213.62) for k in range(72)]
    assert D not in pg.energia_da_serie(s, D, D)


def test_usina_que_nao_gerou_e_zero_de_verdade():
    s = a_cada_5(ONTEM, 0, 0, 23, 55, plano(0.0)) + a_cada_5(D, 0, 0, 23, 55, plano(0.0))
    assert pg.energia_da_serie(s, D, D) == {D: 0.0}


def test_dia_sem_leitura_nao_vira_zero():
    s = a_cada_5(ONTEM, 6, 0, 18, 0, subida(0, 500.0))
    assert pg.energia_da_serie(s, D, D) == {}


def test_timestamp_repetido_fica_com_o_maior_e_oscilacao_nao_e_reset():
    """O `dedup` (horas com 49 leituras em vez de 12) e o piso do reset: 100,2 -> 100,1 é oscilação, não trecho novo."""
    s = [(ts(ONTEM, 23, 55), 0.0)] + a_cada_5(D, 6, 0, 12, 0, subida(0, 100.2))
    # o mesmo instante repetido com um valor menor (não é zero fantasma, que o `limpo` já tiraria): sem o dedup, o
    # vai-e-vem 48,7 -> 40,0 -> 51,5 contava 11,5 em vez de 2,8
    s += [(ts(D, 9, 0), 40.0)]
    s += [(ts(D, 12, 5), 100.1), (ts(D, 12, 10), 100.3)] + a_cada_5(D, 12, 15, 18, 0, subida(100.3, 200.0))
    assert energia(s) == pytest.approx(100.2 + 0.2 + 99.7)    # a conta do coletor; reset aqui dava 300,2


# ---------------------------------------------------------------- a régua da irradiação
def test_irradiacao_por_trapezio_sem_atravessar_buraco():
    linhas = [(t, 1000.0, None) for t, _ in a_cada_5(D, 10, 0, 11, 0, plano(0))]           # 1 h a 1000 W/m²
    linhas += [(ts(D, 11, 40), 1000.0, None), (ts(D, 11, 45), 1000.0, None)]                 # buraco de 40 min fora
    poa, ghi = pg.irradiacao_da_serie(linhas, D, D)[D]
    assert poa == round(1.0 + 1000.0 * (5 / 60) / 1000.0, 3)    # 3 casas, como o coletor
    assert ghi is None                                          # sem GHI medido: nulo, não 0


# ---------------------------------------------------------------- o banco dublado
class Cursor:
    def __init__(self, banco):
        self.banco, self._res = banco, []

    def execute(self, sql, params=None):
        self.banco.feitas.append((sql, params))
        if sql.startswith("SET LOCAL"):
            self._res = []
            return
        if "tb_power_plants" in sql:
            self._res = [(n, i) for n, i in self.banco.catalogo.items() if n in params[0]]
            return
        pid = params["pid"]
        assert isinstance(pid, int) and params["ini"] <= params["fim"]
        if pid in self.banco.quebra:
            raise RuntimeError("canceling statement due to statement timeout")
        if "raw_inverter" in sql:
            self._res = [(dev_id, nome, t, v) for (dev_id, nome), serie in self.banco.inversores.get(pid, {}).items()
                         for t, v in serie]
        elif "raw_weather_station" in sql:
            self._res = list(self.banco.estacao.get(pid, []))
        else:
            raise AssertionError("consulta inesperada: %s" % sql[:60])

    def fetchall(self):
        return self._res

    def close(self):
        pass


class Conexao:
    def __init__(self, banco):
        self.banco, self.fechada, self.rollbacks = banco, False, 0

    def cursor(self):
        assert not self.fechada
        return Cursor(self.banco)

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.fechada = True


class Banco:
    def __init__(self, catalogo, inversores=None, estacao=None, quebra=()):
        self.catalogo, self.inversores, self.estacao = catalogo, inversores or {}, estacao or {}
        self.quebra, self.feitas, self.conexoes = set(quebra), [], []

    def conectar(self):
        c = Conexao(self)
        self.conexoes.append(c)
        return c

    def consultas(self, trecho):
        return [p for s, p in self.feitas if trecho in s]


CATALOGO = {"(309) Piracicaba I": 15, "(308) Ipixuna 1": 20, "(306) Ibaté 1": 1, "(323) Aparecida do Taboado 1": 9,
            "(296) Ipixuna 2": 21}


def _linha(us, u, es=None, e=None):
    return {"Usina Supervisório": us, "Usina": u, "Equipamento Supervisório": es, "Equipamento": e}


LINHAS = [
    _linha("(309) Piracicaba I", "Piracicaba I", None, "UFV"),
    _linha("(309) Piracicaba I", "Piracicaba I", "Inversor 1.1", "Inversor 1.1"),
    _linha("(309) Piracicaba I", "Piracicaba I", "Inversor 1.2", "Inversor 1.2"),
    _linha("(309) Piracicaba I", "Piracicaba I", "Inversor 1.3", "Inversor 1.3"),
    _linha("(308) Ipixuna 1", "Ipixuna 1", "Inversor 1.4", "Inversor 1.4"),
    _linha("(308) Ipixuna 1", "Ipixuna 1", "Inversor 1.5", "Inversor 1.5"),
    _linha("(306) Ibaté 1", "Ibaté 1", "inversor 10", "Inversor 1.10"),
    _linha("(323) Aparecida do Taboado 1", "Aparecida do Taboado 1", "Inversor 1.1", "Inversor 1.1"),
    _linha("(296) Ipixuna 2", "Ipixuna 2", "Inversor 2.1", "Inversor 2.1"),
]


def dia_simples(dia, total, base=500.0):
    """Um dia comum: a véspera fecha em `base`, o contador zera na meia-noite e sobe até `total`."""
    v = dia - dt.timedelta(days=1)
    return ([(ts(v, 23, 55), base), (ts(dia, 0, 0), 0.0), (ts(dia, 6, 0), 0.0), (ts(dia, 12, 0), round(total / 2, 1)),
             (ts(dia, 18, 0), total), (ts(dia, 23, 55), total)])


def _ctx(banco, linhas=LINHAS):
    app = types.SimpleNamespace(_recoleta_mapa=lambda: comum.Mapa(linhas), _pg_conn=banco.conectar)
    return pg.contexto(app)


def _banco(**kw):
    inv = {
        15: {(101, "Inversor 1.1"): dia_simples(D, 300.5)},
        20: {(201, "Inversor 1.4"): dia_simples(D, 111.1), (202, "Inversor 1.5"): dia_simples(D, 222.2)},
        1: {(301, "inversor 10"): dia_simples(D, 55.5)},
        9: {(401, "Inversor 1.1"): dia_simples(D, 444.4)},
        21: {(501, "Inversor 2.1"): dia_simples(D, 10.0), (502, "Inversor 2.13"): dia_simples(D, 20.0),
             (503, "inversor 14"): dia_simples(D, 30.0)},
    }
    sol = [(t, 800.0, 600.0) for t, _ in a_cada_5(D, 10, 0, 11, 0, plano(0))]
    kw.setdefault("inversores", inv)
    kw.setdefault("estacao", {15: sol, 9: sol})
    return Banco(dict(CATALOGO), **kw)


def _ger(res):
    """Só o que tem valor: o inversor do cadastro sem leitura sai nulo (para a régua do dia fora do comum, que conta as
    linhas devolvidas) e o comum tira o nulo da resposta antes de a Coletas ver."""
    return {(g["usina"], g["inversor"], g["data"]): g["kwh"] for g in res["geracao"] if g["kwh"] is not None}


def test_inversor_do_cadastro_sem_leitura_sai_nulo():
    res = pg.buscar(_ctx(_banco()), ["15"], [D], True, False, False)
    nulos = {(g["inversor"]) for g in res["geracao"] if g["kwh"] is None and g["usina"] == "Piracicaba 1"}
    assert nulos == {"Inversor 1.2", "Inversor 1.3"}


def test_contexto_pega_o_mapa_e_o_pool_do_app():
    b = _banco()
    ctx = _ctx(b)
    assert ctx.conectar == b.conectar and ctx.mapa.usina_de("(309) Piracicaba I") == "Piracicaba I"
    # a trava do dia zerado do comum conta os inversores pela ABA da linha
    assert ctx.mapa.inv_por_usina["Piracicaba 1"] == {"Inversor 1.1", "Inversor 1.2", "Inversor 1.3"}
    assert pg.FONTE == "pg" and pg.PAGA is False and pg.TETO is None and pg.MAX_PLANTAS == 8
    assert pg.custo(["15"], [D], True, True, True) == 0


def test_plantas_pela_aba_do_bd_na_ordem_do_coletor_e_conexao_devolvida():
    b = _banco()
    ctx = _ctx(b)
    pl = pg.plantas(ctx)
    assert pl[0] == {"id": "21", "usina": "Ipixuna 2", "destino": "BD_Thopen", "planta": "(296) Ipixuna 2"}
    assert {p["planta"]: p["usina"] for p in pl}["(309) Piracicaba I"] == "Piracicaba 1"     # romano -> aba arábica
    assert [p["id"] for p in pl] == ["21", "1", "20", "15", "9"]
    assert all(c.fechada for c in b.conexoes) and len(b.conexoes) == 1
    pg.plantas(ctx)                                                 # o catálogo fica no ctx do pedido
    assert len(b.conexoes) == 1


def test_usina_sem_de_para_fica_fora_da_lista():
    b = _banco()
    pl = pg.plantas(_ctx(b, [x for x in LINHAS if x["Usina"] != "Ibaté 1"]))
    assert "(306) Ibaté 1" not in {p["planta"] for p in pl}


def test_buscar_traduz_troca_e_avisa_o_sem_de_para():
    b = _banco()
    ctx = _ctx(b)
    pg.plantas(ctx)
    res = pg.buscar(ctx, ["15", "20", "1", "21"], [D, AMANHA], True, False, False)
    g = _ger(res)
    di = D.isoformat()
    assert g[("Piracicaba 1", "Inversor 1.1", di)] == 300.5
    # Ipixuna 1: o supervisório tem o 1.4 e o 1.5 trocados (11/11/2026)
    assert g[("Ipixuna 1", "Inversor 1.5", di)] == 111.1 and g[("Ipixuna 1", "Inversor 1.4", di)] == 222.2
    assert g[("Ibaté 1", "Inversor 1.10", di)] == 55.5              # "inversor 10" do banco, pelo cadastro
    # o inversor que o cadastro não tem vai pela coluna do nome do banco, AVISADO (Ipixuna 2 / 2.13, 31/08/2026)
    assert g[("Ipixuna 2", "Inversor 2.13", di)] == 20.0 and g[("Ipixuna 2", "Inversor 14", di)] == 30.0
    aviso = next(a for a in res["avisos"] if "sem de-para" in a)
    assert "(296) Ipixuna 2 · Inversor 2.13" in aviso and "(296) Ipixuna 2 · inversor 14" in aviso
    # o dia sem leitura não aparece: nada, não 0
    assert not [k for k in g if k[2] == AMANHA.isoformat()]
    assert res["escalares"] == []                                   # ETM não pedida
    assert all(c.fechada for c in b.conexoes)


def test_etm_errada_fica_fora_e_a_boa_vai_pela_aba():
    b = _banco()
    ctx = _ctx(b)
    res = pg.buscar(ctx, ["15", "9"], [D], False, True, True)       # chuva pedida: o banco não tem, ignora
    esc = {(e["usina"], e["coluna"]): e["valor"] for e in res["escalares"]}
    assert esc == {("Piracicaba 1", "IPOA"): pytest.approx(0.8), ("Piracicaba 1", "GHI"): pytest.approx(0.6)}
    assert [p["pid"] for p in b.consultas("raw_weather_station")] == [15]      # a estação errada nem é lida
    assert any("(323) Aparecida do Taboado 1" in a and "IPOA e GHI não vão" in a for a in res["avisos"])
    assert res["geracao"] == [] and not b.consultas("raw_inverter")


def test_fuso_e_folga_das_consultas():
    """raw_* é UTC; o dia é o de Brasília pelo carimbo do json (plataforma/CLAUDE.md, "Fuso do banco")."""
    for sql in (pg._SQL_ENERGIA, pg._SQL_IRRADIACAO):
        assert "AT TIME ZONE 'America/Sao_Paulo'" in sql
        assert "- interval '1 day'" in sql and "+ interval '2 days'" in sql
    b = _banco()
    pg.buscar(_ctx(b), ["15"], [D], True, True, False)
    assert ("SET LOCAL statement_timeout = 45000", None) in b.feitas
    assert b.consultas("raw_inverter")[0] == {"pid": 15, "ini": D.isoformat(), "fim": D.isoformat()}


def test_dois_dispositivos_no_mesmo_destino_nao_se_adivinha():
    inv = {15: {(101, "Inversor 1.1"): dia_simples(D, 300.5), (102, "Inversor 1.1"): dia_simples(D, 12.0),
                (103, "Inversor 1.2"): dia_simples(D, 50.0), (104, "inversor 1.2"): dia_simples(D, 7.0)}}
    res = pg.buscar(_ctx(_banco(inversores=inv)), ["15"], [D], True, False, False)
    g = _ger(res)
    assert ("Piracicaba 1", "Inversor 1.1", D.isoformat()) not in g            # nome repetido no tb_devices
    assert ("Piracicaba 1", "Inversor 1.2", D.isoformat()) not in g            # só a caixa muda: mesma chave
    assert any("2 valor(es) com dois dispositivos no mesmo destino" in a for a in res["avisos"])


def test_sem_de_para_que_cai_na_coluna_do_cadastro_perde_para_o_cadastro():
    inv = {15: {(101, "Inversor 1.1"): dia_simples(D, 300.5), (102, "INVERSOR X"): dia_simples(D, 1.0)}}
    linhas = [x for x in LINHAS if x["Equipamento Supervisório"] != "Inversor 1.1"] + [
        _linha("(309) Piracicaba I", "Piracicaba I", "INVERSOR X", "Inversor 1.1")]
    # "Inversor 1.1" do banco ficou sem de-para e cai na coluna "Inversor 1.1", que o cadastro dá ao "INVERSOR X"
    res = pg.buscar(_ctx(_banco(inversores=inv), linhas), ["15"], [D], True, False, False)
    assert _ger(res)[("Piracicaba 1", "Inversor 1.1", D.isoformat())] == 1.0
    assert any("ficou o do cadastro" in a for a in res["avisos"])


def test_usina_que_falha_nao_derruba_o_pedido_e_a_conexao_volta():
    b = _banco(quebra={20})
    res = pg.buscar(_ctx(b), ["20", "15"], [D], True, False, False)
    assert _ger(res) == {("Piracicaba 1", "Inversor 1.1", D.isoformat()): 300.5}
    assert any(a.startswith("(308) Ipixuna 1: o banco não respondeu") for a in res["avisos"])
    assert b.conexoes[-1].rollbacks >= 2 and all(c.fechada for c in b.conexoes)


def test_banco_fora_e_recusa_502():
    def fora():
        raise OSError("could not connect to server")
    ctx = pg.contexto(types.SimpleNamespace(_recoleta_mapa=lambda: comum.Mapa(LINHAS), _pg_conn=fora))
    with pytest.raises(comum.Recusa) as e:
        pg.plantas(ctx)
    assert e.value.status == 502 and "banco da Thopen" in str(e.value)


def test_trava_do_dia_zerado_conta_pela_aba():
    """Piracicaba I tem 3 inversores no cadastro e só 1 veio: é fonte fora do ar, mesmo com a linha saindo pela aba
    "Piracicaba 1" (sem o mapa pela aba, o total caía para 1 e a trava não disparava)."""
    b = _banco()
    ctx = _ctx(b)
    res = pg.buscar(ctx, ["15"], [D], True, False, False)
    assert comum.dias_fora(res["geracao"], ctx.mapa) == [("Piracicaba 1", D.isoformat())]


# ---------------------------------------------------------------- a rota de verdade, com o banco dublado
@pytest.fixture
def cli(monkeypatch):
    import app
    import recoleta_apipv as rc
    b = _banco()
    monkeypatch.setattr(app, "DASH_PASSWORD", "senha-de-teste")
    monkeypatch.setattr(app, "PASSWORD", "senha-pv-de-teste")
    monkeypatch.delenv("RECOLETA_CHAVE", raising=False)
    monkeypatch.setattr(app, "_recoleta_mapa", lambda: comum.Mapa(LINHAS))
    monkeypatch.setattr(app, "_pg_conn", b.conectar)
    monkeypatch.setattr(comum, "hoje_br", lambda agora_utc=None: dt.date(2026, 9, 3))
    monkeypatch.setattr(comum, "_CONTA", {})
    return app.app.test_client(), {"X-Recoleta-Chave": rc.chave_esperada("", "senha-pv-de-teste")}, b


def test_rota_lista_e_recoleta(cli):
    c, cab, b = cli
    pl = c.get("/api/recoleta/pg/plantas", headers=cab).get_json()
    assert pl["paga"] is False and pl["teto"] is None and pl["max_plantas"] == 8
    assert {p["usina"] for p in pl["plantas"]} >= {"Piracicaba 1", "Ipixuna 1"}
    r = c.post("/api/recoleta/pg", headers=cab, json={"ids": ["15", "20"], "ini": D.isoformat(), "fim": D.isoformat(),
                                                       "geracao": True, "etm": True})
    j = r.get_json()
    assert r.status_code == 200, j
    assert {(g["usina"], g["inversor"]) for g in j["geracao"]} == {("Piracicaba 1", "Inversor 1.1"),
                                                                   ("Ipixuna 1", "Inversor 1.4"),
                                                                   ("Ipixuna 1", "Inversor 1.5")}
    assert j["consultas"] == 0 and j["cota_restante"] is None
    assert {"usina": "Piracicaba 1", "data": D.isoformat()} in j["dias_fora"]
    assert all(x.fechada for x in b.conexoes)
    assert c.post("/api/recoleta/pg", headers={"X-Recoleta-Chave": "errada"}, json={}).status_code == 401
