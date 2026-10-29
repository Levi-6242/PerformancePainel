# -*- coding: utf-8 -*-
"""Relatório Potência Ativa dos Inversores (13/10/2026).

Levi: "Teria como ter um novo relatório de performance pegando a potência ativa de cada inversor e sobrepondo por dia.
Cada inversor terá uma cor diferente. Se chamará relatório Potência Ativa dos Inversores!"

Um gráfico por dia, uma linha por inversor. O que estes testes travam:
- a rota: 2 inversores em 2 dias = 2 dias (2 gráficos) com 2 séries cada, com o nome do cadastro e a média de 5 min;
- o teto de 7 dias seguidos (e o dia que ainda não chegou), recusados com o motivo;
- o "sem dado" (a fonte respondeu sem leitura) separado do "falhou" (a leitura não veio): só o primeiro fica guardado;
- a API PV (paga): dia passado sai da MESMA leitura da Curva (`_spv_day_records_hist`), uma vez só por dia (cache), e
  não é pedida com a cota na reserva nem pelo gestor do Nexus; hoje sai do day_inverter;
- o banco da Thopen e a GreenYellow pelos leitores que a plataforma já tinha; as fontes sem histórico dizem o porquê;
- a página: a régua de ordem natural e a chave cor × traço iguais nos dois lados, e o tema do Nexus.
Nenhum teste fala com fonte paga: os leitores são dublados (a trava do conftest quebraria quem tentasse).
"""
import json
import math
import pathlib
import shutil
import subprocess
from datetime import date, datetime

import pytest

import app
import potencia_ativa as pa

TPL = (pathlib.Path(__file__).resolve().parents[1] / "plataforma" / "templates" / "potencia_ativa.html").read_text(
    encoding="utf-8").replace("\r\n", "\n")
ROTA = "/api/relatorio/potencia-ativa"


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "", raising=False)   # app aberto, como o uso local
    monkeypatch.setattr(app, "_PA_CACHE", {})
    monkeypatch.setattr(app, "_pa_em_voo", {})
    app.app.config["TESTING"] = True
    with app.app.test_client() as c:
        yield c


def _curva(*pares):
    return [(h, v) for h, v in pares]


# ── o módulo puro ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_periodo_um_dia_e_ate_sete_dias():
    hoje = date(2026, 10, 13)
    assert pa.periodo("2026-10-12", "2026-10-12", hoje) == [date(2026, 10, 12)]
    sete = pa.periodo("2026-10-07", "2026-10-13", hoje)
    assert len(sete) == pa.MAX_DIAS == 7 and sete[0] == date(2026, 10, 7) and sete[-1] == hoje


@pytest.mark.parametrize("ini, fim, trecho", [
    ("2026-10-05", "2026-10-12", "no máximo 7 dias"),      # 8 dias
    ("2026-10-12", "2026-10-11", "vem antes do início"),
    ("2026-10-13", "2026-10-14", "não pode passar de hoje"),
    ("12/10/2026", "2026-10-12", "AAAA-MM-DD"),
    ("", "", "AAAA-MM-DD"),
])
def test_periodo_recusado_diz_o_motivo(ini, fim, trecho):
    with pytest.raises(pa.Recusado) as e:
        pa.periodo(ini, fim, date(2026, 10, 13))
    assert trecho in str(e.value)


def test_em_passos_faz_a_media_de_5_min_e_ignora_o_que_nao_e_numero():
    pts = [("10:00", 10.0), ("10:01", 20.0), ("10:04", 30.0), ("10:05", 7.0), ("10:06", None), ("10:07", "x"),
           ("10:08", float("nan")), ("10:09", True), ("2026-10-12 10:12:30", 4.0), (datetime(2026, 10, 12, 10, 14), 6.0),
           ("lixo", 9.0), ("25:00", 9.0)]
    assert pa.em_passos(pts) == [[600, 20.0], [605, 7.0], [610, 5.0]]


def test_monta_dia_ordem_natural_nome_repetido_e_sem_leitura():
    leitura = {"inversores": [
        {"id": 3, "nome": "Inversor 1.10", "pontos": _curva(("12:00", 100))},
        {"id": 1, "nome": "Inversor 1.9", "pontos": _curva(("12:00", 90))},
        {"id": 7, "nome": "INVERSOR08", "pontos": _curva(("12:00", 50))},     # o INVERSOR08 da Morada Nova trocou de id
        {"id": 8, "nome": "INVERSOR08", "pontos": _curva(("12:05", 51))},
        {"id": 9, "nome": "Inversor 2.1", "pontos": _curva(("12:00", None))},  # a fonte o listou sem potência
    ]}
    d = pa.monta_dia(date(2026, 10, 12), leitura, date(2026, 10, 13), datetime(2026, 10, 13, 9, 30))
    assert d["situacao"] == "ok" and d["parcial"] is False and d["lido_em"] == "09:30"
    assert [i["nome"] for i in d["inversores"]] == ["INVERSOR08 (7)", "INVERSOR08 (8)", "Inversor 1.9", "Inversor 1.10"]
    assert d["sem_leitura"] == ["Inversor 2.1"] and d["motivo"] is None


def test_monta_dia_sem_ponto_nenhum_e_sem_dado_com_o_motivo_da_fonte():
    d = pa.monta_dia(date(2026, 10, 12), {"inversores": [], "motivo": "o banco não tem leitura"}, date(2026, 10, 13))
    assert d["situacao"] == "sem_dado" and d["motivo"] == "o banco não tem leitura" and d["inversores"] == []
    f = pa.dia_que_falhou(date(2026, 10, 12), "a API PV não respondeu")
    assert f["situacao"] == "falhou" and f["inversores"] == [] and "não respondeu" in f["motivo"] and f["perfil"] is False


def test_cada_fonte_do_tempo_real_tem_familia_ou_o_motivo_de_nao_ter():
    # Athon e Axis saíram (Levi, 13/10/2026: "Não, por hora pode tirar Axis e Athon")
    assert {f["fonte"] for f in pa.FONTES} == {"pv", "pg", "solaredge", "2capi", "semp", "alveslima", "greenyellow",
                                                "salenergia", "apolo"}
    # a Apolo (Rio do Peixe, 29/10/2026) vem pelo gateway MQTT da GreenYellow: a telemetria traz a potência
    assert pa.fonte("apolo")["familia"] == pa.fonte("greenyellow")["familia"] == "scadagridco"
    # o RenoGrid é potência CC (a soma das strings), escrita como tal; as outras, potência ativa
    assert pa.grandeza(pa.fonte("solaredge")) == "Potência CC" and "CC" in pa.fonte("solaredge")["rotulo"]
    assert {pa.grandeza(f) for f in pa.FONTES if f["fonte"] != "solaredge"} == {"Potência ativa"}
    for f in pa.FONTES:
        assert (f["familia"] and f.get("origem")) or (not f["familia"] and len(f.get("motivo") or "") > 40), f["fonte"]
    assert {f["fonte"] for f in pa.FONTES if f["familia"] == "apipv"} == {"pv", "2capi", "semp", "alveslima"}


# ── a rota: 2 inversores × 2 dias ────────────────────────────────────────────────────────────────────────────────────
def test_rota_dois_inversores_dois_dias_dois_graficos_com_duas_series(cli, monkeypatch, freeze_now):
    freeze_now("2026-10-13 15:00:00")
    pedidos = []

    def ler_pg(pid, dia):
        pedidos.append((pid, dia))
        base = 100.0 if dia == date(2026, 10, 11) else 80.0
        return {"inversores": [
            {"id": 11, "nome": "Inversor 1.2", "pontos": _curva(("10:00", base), ("10:02", base + 2), ("10:05", base + 5))},
            {"id": 10, "nome": "Inversor 1.1", "pontos": _curva(("10:00", base - 10), ("10:05", base - 5))},
        ]}
    monkeypatch.setattr(app, "_pa_ler_pg", ler_pg)
    monkeypatch.setattr(app, "_pg_cache", {"summary": [{"plant_id": 8, "usina": "Usina do Banco"}], "detail": {}, "ts": 0})
    r = cli.get(f"{ROTA}?fonte=pg&usina=8&ini=2026-10-11&fim=2026-10-12")
    assert r.status_code == 200
    j = r.get_json()
    assert j["ok"] and j["unidade"] == "kW" and j["passo_min"] == 5 and j["usina_nome"] == "Usina do Banco"
    assert [d["dia"] for d in j["dias"]] == ["2026-10-11", "2026-10-12"]                    # um gráfico por dia
    for d, base in zip(j["dias"], (100.0, 80.0)):
        assert d["situacao"] == "ok" and d["parcial"] is False
        assert [i["nome"] for i in d["inversores"]] == ["Inversor 1.1", "Inversor 1.2"]       # duas séries, ordem natural
        assert d["inversores"][1]["pontos"] == [[600, base + 1], [605, base + 5]]          # média de 5 min
    assert pedidos == [(8, date(2026, 10, 11)), (8, date(2026, 10, 12))]


def test_rota_recusa_mais_de_sete_dias_e_o_futuro(cli, monkeypatch, freeze_now):
    freeze_now("2026-10-13 15:00:00")
    chamou = []
    monkeypatch.setattr(app, "_pa_ler_pg", lambda *a: chamou.append(a))
    r = cli.get(f"{ROTA}?fonte=pg&usina=8&ini=2026-10-01&fim=2026-10-08")
    assert r.status_code == 400 and "no máximo 7 dias" in r.get_json()["motivo"]
    r = cli.get(f"{ROTA}?fonte=pg&usina=8&ini=2026-10-13&fim=2026-10-14")
    assert r.status_code == 400 and "não pode passar de hoje" in r.get_json()["motivo"]
    for q, trecho in (("fonte=xyz&usina=8", "fonte desconhecida"), ("fonte=pg", "escolha a usina"),
                      ("fonte=pg&usina=abc", "o id é um número"), ("fonte=greenyellow&usina=nao_existe", "desconhecida")):
        r = cli.get(f"{ROTA}?{q}&ini=2026-10-12&fim=2026-10-12")
        assert r.status_code == 400 and trecho in r.get_json()["motivo"], q
    assert chamou == []                                             # nada foi lido para um pedido recusado


def test_dia_sem_dado_fica_guardado_e_o_que_falhou_nao(cli, monkeypatch, freeze_now):
    freeze_now("2026-10-13 15:00:00")
    vezes = {"sem": 0, "falha": 0}

    def ler_pg(pid, dia):
        if dia == date(2026, 10, 11):
            vezes["sem"] += 1
            return {"inversores": [], "motivo": "o banco da Thopen não tem leitura de inversor desta usina neste dia"}
        vezes["falha"] += 1
        raise pa.FonteNaoRespondeu("o banco da Thopen não respondeu (OperationalError)")
    monkeypatch.setattr(app, "_pa_ler_pg", ler_pg)
    for _ in range(2):
        j = cli.get(f"{ROTA}?fonte=pg&usina=8&ini=2026-10-11&fim=2026-10-12").get_json()
        sem, falha = j["dias"]
        assert sem["situacao"] == "sem_dado" and "não tem leitura" in sem["motivo"] and sem["inversores"] == []
        assert falha["situacao"] == "falhou" and "não respondeu" in falha["motivo"] and falha["inversores"] == []
    assert vezes == {"sem": 1, "falha": 2}                          # a falha é lida de novo; o sem dado, não


def test_fonte_sem_historico_diz_o_porque_e_nao_le_nada(cli, monkeypatch, freeze_now):
    freeze_now("2026-10-13 15:00:00")
    monkeypatch.setattr(app, "_pa_ler", lambda *a: pytest.fail("fonte sem histórico não pode ser lida"))
    j = cli.get(f"{ROTA}?fonte=salenergia&usina=QUALQUER&ini=2026-10-12&fim=2026-10-12").get_json()
    assert j["ok"] and j["sem_historico"] is True and j["dias"] == [] and len(j["motivo"]) > 40
    for fora in ("sunop", "axis"):                                   # saíram do relatório: fonte desconhecida
        r = cli.get(f"{ROTA}?fonte={fora}&usina=QUALQUER&ini=2026-10-12&fim=2026-10-12")
        assert r.status_code == 400 and "fonte desconhecida" in r.get_json()["motivo"], fora


# ── API PV (paga): as leituras da Curva, uma vez por dia, nunca com a cota na reserva nem pelo gestor ────────────────
def _registros(dia_iso, por_inv):
    return [{"idefinversor": inv, "tsleitura_new": f"{dia_iso} {h}:00", "conteudojson": json.dumps({"Pac": v, "Ipv1": 3.0})}
            for inv, pontos in por_inv.items() for h, v in pontos]


@pytest.fixture
def api_pv(monkeypatch):
    """A API PV dublada nas funções que a plataforma já usa (nenhum pedido sai): o nome vem do plant_devices + o
    Equipamentos, como no drill."""
    chamadas = {"hist": [], "hoje": []}
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "tok")
    monkeypatch.setattr(app, "get_token", lambda *a, **k: "tok")
    monkeypatch.setattr(app, "get_plants", lambda *a, **k: [{"id": 297410, "nome": "UFV Teste PA"}])
    monkeypatch.setattr(app, "_pv_plant_devices", lambda pid: [{"device_id": 101, "device_name": "INV 01"},
                                                               {"device_id": 102, "device_name": "INV 02"}])
    monkeypatch.setitem(app.EQUIP_NAMES, "UFV Teste PA", {"INV 01": "Inversor 1.1", "INV 02": "Inversor 1.2"})
    monkeypatch.setattr(app, "_plants_cache", {"ts": 0.0, "data": [{"id": 297410, "nome": "UFV Teste PA"},
                                                                  {"id": 18758732, "nome": "UFV Tucano 1"}]})
    monkeypatch.setattr(app, "_spv_hist_recs", {})
    monkeypatch.setattr(app, "_pv_cota", {"dia": None, "hora": None, "ts": 0.0, "zerada_ate": 0.0})

    def hist(pid, token, data):
        chamadas["hist"].append(data)
        iso = datetime.strptime(data, "%d/%m/%Y").strftime("%Y-%m-%d")
        return _registros(iso, {101: [("11:00", 150.0), ("11:01", 152.0)], 102: [("11:00", 140.0), ("11:03", 142.0)]}), None

    def hoje(pid, token, data):
        chamadas["hoje"].append(data)
        return _registros("2026-10-13", {101: [("09:00", 60.0)], 102: [("09:00", 55.0)]})
    monkeypatch.setattr(app, "_spv_day_records_hist", hist)
    monkeypatch.setattr(app, "_spv_day_records", hoje)
    return chamadas


def test_api_pv_dia_passado_e_hoje_pelas_leituras_da_curva_com_o_nome_do_cadastro(cli, api_pv, freeze_now):
    freeze_now("2026-10-13 15:00:00")
    j = cli.get(f"{ROTA}?fonte=pv&usina=297410&ini=2026-10-12&fim=2026-10-13").get_json()
    ontem, hoje = j["dias"]
    assert [i["nome"] for i in ontem["inversores"]] == ["Inversor 1.1", "Inversor 1.2"]
    assert ontem["inversores"][0]["pontos"] == [[660, 151.0]] and ontem["inversores"][1]["pontos"] == [[660, 141.0]]
    assert hoje["parcial"] is True and hoje["inversores"][1]["pontos"] == [[540, 55.0]]
    assert api_pv == {"hist": ["12/10/2026"], "hoje": ["13/10/2026"]}
    cli.get(f"{ROTA}?fonte=pv&usina=297410&ini=2026-10-12&fim=2026-10-12")
    assert api_pv["hist"] == ["12/10/2026"]                         # dia passado lido = cache: a cota não paga de novo


def test_api_pv_usina_que_a_plataforma_nao_conhece_nao_gasta_cota(cli, api_pv, freeze_now):
    freeze_now("2026-10-13 15:00:00")
    r = cli.get(f"{ROTA}?fonte=pv&usina=999999&ini=2026-10-12&fim=2026-10-12")
    assert r.status_code == 400 and "desconhecida na API PV" in r.get_json()["motivo"]
    assert api_pv == {"hist": [], "hoje": []}


def test_api_pv_cota_na_reserva_nao_pede_o_dia_passado(cli, api_pv, monkeypatch, freeze_now):
    freeze_now("2026-10-13 15:00:00")
    import time
    monkeypatch.setattr(app, "_pv_cota", {"dia": 420, "hora": 150, "ts": time.time(), "zerada_ate": 0.0})
    d = cli.get(f"{ROTA}?fonte=pv&usina=297410&ini=2026-10-12&fim=2026-10-12").get_json()["dias"][0]
    assert d["situacao"] == "falhou" and "cota histórica" in d["motivo"] and api_pv["hist"] == []
    # o dia que o drill/curva já baixou cru (no _spv_hist_recs) não gasta cota: sai mesmo com a cota na reserva
    app._spv_hist_recs[(297410, "12/10/2026")] = ["já baixado"]
    d = cli.get(f"{ROTA}?fonte=pv&usina=297410&ini=2026-10-12&fim=2026-10-12").get_json()["dias"][0]
    assert d["situacao"] == "ok" and api_pv["hist"] == ["12/10/2026"]


def test_api_pv_sem_registro_no_dia_e_sem_dado_e_resposta_ruim_e_falha(cli, api_pv, monkeypatch, freeze_now):
    freeze_now("2026-10-13 15:00:00")
    monkeypatch.setattr(app, "_spv_day_records_hist", lambda pid, tok, data: ([], "sem_dados_api"))
    d = cli.get(f"{ROTA}?fonte=semp&usina=18758732&ini=2026-10-11&fim=2026-10-11").get_json()["dias"][0]
    assert d["situacao"] == "sem_dado" and "sem leitura de inversor" in d["motivo"]
    monkeypatch.setattr(app, "_spv_day_records_hist", lambda pid, tok, data: ([], "http_502"))
    d = cli.get(f"{ROTA}?fonte=semp&usina=18758732&ini=2026-10-10&fim=2026-10-10").get_json()["dias"][0]
    assert d["situacao"] == "falhou" and "HTTP 502" in d["motivo"]
    sem_pac = [{"idefinversor": 101, "tsleitura_new": "2026-10-09 10:00:00", "conteudojson": {"Ipv1": 2.0}}]
    monkeypatch.setattr(app, "_spv_day_records_hist", lambda pid, tok, data: (sem_pac, None))
    d = cli.get(f"{ROTA}?fonte=semp&usina=18758732&ini=2026-10-09&fim=2026-10-09").get_json()["dias"][0]
    assert d["situacao"] == "sem_dado" and "Pac" in d["motivo"] and d["sem_leitura"]


def test_gestor_do_nexus_nao_abre_a_api_pv_e_le_o_dia_ja_guardado(cli, api_pv, monkeypatch, freeze_now):
    freeze_now("2026-10-13 15:00:00")
    cli.get(f"{ROTA}?fonte=pv&usina=297410&ini=2026-10-12&fim=2026-10-12")      # um analista leu o dia 12
    monkeypatch.setattr(app._ln, "pedido_do_nexus", lambda: True)
    j = cli.get(f"{ROTA}?fonte=pv&usina=297410&ini=2026-10-11&fim=2026-10-12").get_json()
    d11, d12 = j["dias"]
    assert d11["situacao"] == "falhou" and "gestor" in d11["motivo"] and d11["perfil"] is True   # nem foi pedido
    assert d12["situacao"] == "ok" and len(d12["inversores"]) == 2
    assert api_pv["hist"] == ["12/10/2026"]                         # o 11 não foi pedido à API PV


def test_api_pv_registrador_em_outro_fuso_vai_na_observacao(cli, api_pv, monkeypatch, freeze_now):
    freeze_now("2026-10-13 15:00:00")
    monkeypatch.setitem(app._pv_relogio, "297410", {"h": 1})
    d = cli.get(f"{ROTA}?fonte=pv&usina=297410&ini=2026-10-12&fim=2026-10-12").get_json()["dias"][0]
    assert "1 h atrás de Brasília" in d["obs"]


# ── banco da Thopen e GreenYellow: os leitores de verdade, com a fonte dublada ──────────────────────────────────────
class _CursorFalso:
    def __init__(self, linhas, log):
        self.linhas, self.log = linhas, log

    def execute(self, sql, params=None):
        self.log.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self.linhas


class _ConexaoFalsa:
    def __init__(self, linhas, log):
        self.cur, self.log = _CursorFalso(linhas, log), log

    def cursor(self):
        return self.cur

    def close(self):
        self.log.append(("close", None))


def test_banco_le_o_active_power_do_dia_com_o_nome_do_cadastro(monkeypatch):
    log = []
    linhas = [(5, "INV-A ", "UFV Banco PA", datetime(2026, 10, 12, 10, 0), 120.5),
              (5, "INV-A ", "UFV Banco PA", datetime(2026, 10, 12, 10, 5), None),
              (6, "INV-B", "UFV Banco PA", datetime(2026, 10, 12, 10, 1), 118.0)]
    monkeypatch.setattr(app, "_pg_conn", lambda: _ConexaoFalsa(linhas, log))
    monkeypatch.setitem(app.EQUIP_NAMES, "UFV Banco PA", {"INV-A": "Inversor 1.1", "INV-B": "Inversor 1.2"})
    out = app._pa_ler_pg(8, date(2026, 10, 12))
    d = pa.monta_dia(date(2026, 10, 12), out, date(2026, 10, 13))
    assert [(i["nome"], i["pontos"]) for i in d["inversores"]] == [("Inversor 1.1", [[600, 120.5]]),
                                                                  ("Inversor 1.2", [[600, 118.0]])]
    assert log[0][0] == "SET LOCAL statement_timeout = 45000"
    assert "active_power" in log[1][0] and "AT TIME ZONE 'America/Sao_Paulo'" in log[1][0]
    assert log[1][1] == {"pid": 8, "dia": "2026-10-12"} and log[-1] == ("close", None)


def test_banco_fora_e_falha_nao_dia_sem_dado(monkeypatch):
    def fora():
        raise RuntimeError("rede cortada")
    monkeypatch.setattr(app, "_pg_conn", fora)
    with pytest.raises(pa.FonteNaoRespondeu):
        app._pa_ler_pg(8, date(2026, 10, 12))


def test_greenyellow_le_a_potencia_da_curva_que_a_aba_curva_ja_usa(monkeypatch):
    pedidos = []

    class Curvas:
        def curva(self, fonte, pid, equip, dia, getter=None, agora=None):
            pedidos.append((fonte, pid, equip, dia))
            if equip == "3":
                raise TimeoutError("o supervisório demorou")
            return {"strings": {1: [("10:00", 8.0)]}, "pot": [("10:00", 100.0 + int(equip)), ("10:03", 102.0 + int(equip))],
                    "ultimo_ts": 1}
    monkeypatch.setattr(app, "_sg_curvas", Curvas())
    monkeypatch.setattr(app._sg, "hoje", lambda: "2026-10-13")
    out = app._pa_ler_sg("greenyellow", "irece_2", date(2026, 10, 12))
    assert len(pedidos) == 10 and all(p[3] == "2026-10-12" for p in pedidos)
    d = pa.monta_dia(date(2026, 10, 12), out, date(2026, 10, 13))
    assert d["inversores"][0] == {"nome": "Inversor 1.1", "pontos": [[600, 102.0]]}
    assert len(d["inversores"]) == 9 and d["faltaram"] == ["Inversor 1.3"]   # o que falhou não apaga os outros
    # o dia com inversor faltando não fica guardado (pode ser lido de novo); o de 45+ dias nem vai à rede
    longe = app._pa_ler_sg("greenyellow", "irece_2", date(2026, 8, 1))
    assert longe["inversores"] == [] and "45 dias" in longe["motivo"] and len(pedidos) == 10


def test_dia_com_inversor_que_faltou_nao_fica_guardado(cli, monkeypatch, freeze_now):
    freeze_now("2026-10-13 15:00:00")
    vezes = []

    def ler_sg(fonte, pid, dia):
        vezes.append(dia)
        return {"inversores": [{"id": "1", "nome": "Inversor 1.1", "pontos": _curva(("10:00", 90.0))}],
                "faltaram": ["Inversor 1.2"]}
    monkeypatch.setattr(app, "_pa_ler_sg", ler_sg)
    for _ in range(2):
        d = cli.get(f"{ROTA}?fonte=greenyellow&usina=irece_2&ini=2026-10-12&fim=2026-10-12").get_json()["dias"][0]
        assert d["situacao"] == "ok" and d["faltaram"] == ["Inversor 1.2"]
    assert len(vezes) == 2


# ── a lista de fontes e usinas: as do Tempo real, do que já está em memória ─────────────────────────────────────────
def test_lista_de_usinas_vem_das_tabelas_do_tempo_real(cli, monkeypatch):
    monkeypatch.setattr(app, "_cache", {"payload": {"rows": [
        {"plant_id": 18771929, "usina": "Ipixuna do Pará"}, {"plant_id": 18771915, "usina": "Ipixuna do Pará"},
        {"plant_id": 297410, "usina": "Barretos 10"}, {"plant_id": 297411, "usina": "Barretos 9"},
        {"plant_id": 297410, "usina": "Barretos 10"}]}, "ts": 0})
    monkeypatch.setattr(app, "_plants_cache", {"ts": 0, "data": [{"id": 18771915, "nome": "Santa Cecilia 1"},
                                                                  {"id": 18771929, "nome": "Santa Cecilia 2"}]})
    monkeypatch.setattr(app, "_pg_cache", {"summary": None, "detail": {}, "ts": 0})
    j = cli.get(f"{ROTA}/usinas").get_json()
    assert j["ok"] and j["max_dias"] == 7
    f = {x["fonte"]: x for x in j["fontes"]}
    assert [u["nome"] for u in f["pv"]["usinas"]] == ["Barretos 9", "Barretos 10", "Ipixuna do Pará · Santa Cecilia 1",
                                                      "Ipixuna do Pará · Santa Cecilia 2"]
    assert f["pv"]["historico"] is True and "Pac" in f["pv"]["origem"]
    assert f["pg"]["usinas"] == [] and "ainda não foi montada" in f["pg"]["aviso"]   # tabela fria: diz, não inventa
    assert "sunop" not in f and "axis" not in f                                    # fora a pedido do Levi (13/10)
    assert f["solaredge"]["historico"] is True and f["solaredge"]["grandeza"] == "Potência CC"
    assert f["pv"]["grandeza"] == "Potência ativa"
    assert [x["fonte"] for x in j["fontes"]][:3] == ["pv", "pg", "solaredge"]       # a ordem dos cards do Tempo real


def test_a_pagina_abre_e_esta_no_mapa_na_central_de_emissao_do_nexus(cli):
    """No mapa da porta única (cópia do Nexus) desde 13/10/2026: torre Relatórios, tela `potencia-ativa`, aberta pela
    Central de emissão do Nexus."""
    import porta_nexus as pn
    r = cli.get("/relatorio/potencia-ativa")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "<title>Potência Ativa dos Inversores" in html
    t = pn.tela_do_caminho("/relatorio/potencia-ativa")
    assert (t.torre, t.tela) == ("relatorios", "potencia-ativa") and "/relatorio/potencia-ativa" not in pn.FORA_DO_MAPA
    assert "modo-" + "nexus" not in TPL                             # "no Nexus" = o window.gcModoNexus do calço


# ── a página (o JavaScript do template, no node) ────────────────────────────────────────────────────────────────────
def _node(js: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("node não instalado")
    p = subprocess.run([node, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def _trecho(inicio: str, fim: str) -> str:
    i = TPL.index(inicio)
    return TPL[i:TPL.index(fim, i) + len(fim)]


def test_a_ordem_natural_da_pagina_e_a_do_servidor():
    nomes = ["Inversor 1.10", "Inversor 1.2", "inversor 1.1", "INV 10", "INV 2", "Inversor 2.1", "INVERSOR0 1.10",
             "INVERSOR0 1.9", "UNI_Inv_2.1", "UNI_Inv_1.6", "Inversor 1.1 (402513)", "Inversor 1.1 (388164)", "B", "a"]
    js = (_trecho("function chaveNatural(", "\n}\n") + _trecho("function comparaNatural(", "\n}\n")
          + f"process.stdout.write(JSON.stringify({json.dumps(nomes)}.slice().sort(comparaNatural)));")
    assert _node(js) == sorted(nomes, key=pa.chave_natural)


def test_cada_inversor_tem_cor_e_traco_proprios_ate_48_e_a_9a_cor_nunca_existe():
    js = ("const S = { idx: new Map(), ordem: [] };\n" + _trecho("const TRACOS = ", ";\n") + _trecho("const N_CORES", ";\n")
          + _trecho("function chave(nome)", "\n}\n") + _trecho("function grupos()", "\n}\n")
          + "S.ordem = Array.from({length: 50}, (_, i) => 'Inversor ' + (i + 1)); S.ordem.forEach((n, i) => S.idx.set(n, i));"
          + "process.stdout.write(JSON.stringify({ks: S.ordem.map(chave), g: grupos().map(x => x.length)}));")
    r = _node(js)
    ks = r["ks"]
    assert ks[0] == {"cor": "var(--s1)", "traco": ""} and ks[7] == {"cor": "var(--s8)", "traco": ""}
    assert ks[8] == {"cor": "var(--s1)", "traco": "7 5"} and ks[9] == {"cor": "var(--s2)", "traco": "7 5"}
    assert len({(k["cor"], k["traco"]) for k in ks[:48]}) == 48            # 8 cores × 6 traços, sem repetir
    assert {k["cor"] for k in ks} == {f"var(--s{i})" for i in range(1, 9)}    # nunca uma 9ª cor
    assert r["g"] == [48, 2]                                                # o 49º vai para o 2º gráfico do dia


def test_as_cores_da_pagina_sao_a_paleta_validada_nos_dois_temas():
    claro = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
    escuro = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
    raiz = _trecho(":root{", "\n}")
    dark = _trecho(':root[data-theme="dark"]{', "\n}")
    for i, (c, e) in enumerate(zip(claro, escuro), 1):
        assert f"--s{i}:{c};" in raiz and f"--s{i}:{e};" in dark, i
    assert "--pagina:#090d18;" in dark and "--cartao:#161d30;" in dark      # o navy, nunca o lilás
    assert "#191528" not in TPL


def _tema(nexus, cookie="", local=None, evento=None):
    js = ("const attrs={'data-theme':'dark'}; const ouvintes={};"
          "global.document={cookie:%s, documentElement:{setAttribute:(k,v)=>{attrs[k]=v;}, getAttribute:k=>attrs[k]}};"
          "global.localStorage={getItem:k=>(%s)[k]||null};"
          "global.window={gcModoNexus:%s, addEventListener:(t,f)=>{ouvintes[t]=f;}};"
          % (json.dumps(cookie), json.dumps(local or {}), "true" if nexus else "undefined")
          + _trecho("(function(){\n  var raiz = document.documentElement;", "})();")
          + (";ouvintes.storage(%s);" % json.dumps(evento) if evento else "")
          + "process.stdout.write(JSON.stringify(attrs['data-theme']));")
    return _node(js)


def test_tema_fora_do_nexus_e_o_da_pagina_e_dentro_e_o_do_nexus():
    assert _tema(False) == "dark"                                            # navy é o padrão
    assert _tema(False, local={"pa.tema": "claro"}) == "light"
    assert _tema(False, cookie="nexus_tema=claro") == "dark"                  # fora do Nexus o Nexus não manda
    assert _tema(True, cookie="a=1; nexus_tema=claro") == "light"
    assert _tema(True, local={"nexus.tema": "claro", "pa.tema": "escuro"}) == "light"
    assert _tema(True, cookie="nexus_tema=claro", evento={"key": "nexus.tema", "newValue": "escuro"}) == "dark"
    assert _tema(True, cookie="nexus_tema=claro", evento={"key": "outra", "newValue": "escuro"}) == "light"


def test_o_botao_de_tema_e_a_navegacao_sao_da_casca():
    assert 'id="tema" data-casca' in TPL
    assert '<a class="nav" href="/" data-casca>' in TPL and '<span class="marca" data-casca>' in TPL


def test_escala_do_eixo_y_e_redonda():
    js = _trecho("function ticksY(", "\n}\n") + "process.stdout.write(JSON.stringify([ticksY(0, 243.7), ticksY(0, 1), ticksY(-3, 98)]));"
    a, b, c = _node(js)
    assert a == [0, 50, 100, 150, 200, 250] and b[0] == 0 and b[-1] >= 1 and c[0] < 0 and c[-1] >= 98
    assert all(math.isclose(y - x, a[1] - a[0]) for x, y in zip(a, a[1:]))


# ── RenoGrid (SolarEdge): potência CC, a soma das strings de cada inversor (Levi, 13/10/2026: "Quero sim") ─────────
def _se_falso(monkeypatch, series, lotes_falhos=0, sites=None, devs=None):
    """A SolarEdge dublada: 1 site em Cuiabá, 2 inversores com 2 strings cada; `series` = {uuid: [(HH:MM, W)]}."""
    pedidos = {"sites": 0, "devs": 0, "series": 0}
    sites = sites if sites is not None else [{"id": 4425840, "nome": "UFV RenoGrid PA", "timezone": "America/Cuiaba"}]
    devs = devs if devs is not None else [
        {"deviceType": "INVERTER", "deviceSerial": "INV-A", "deviceName": "Inverter 1"},
        {"deviceType": "INVERTER", "deviceSerial": "INV-B", "deviceName": "Inverter 2"},
        {"deviceType": "STRING", "deviceSerial": "S11", "deviceName": "String 1.1", "partOfSerial": "INV-A"},
        {"deviceType": "STRING", "deviceSerial": "S12", "deviceName": "String 1.2", "partOfSerial": "INV-A"},
        {"deviceType": "STRING", "deviceSerial": "S21", "deviceName": "String 2.1", "partOfSerial": "INV-B"},
        {"deviceType": "STRING", "deviceSerial": "S22", "deviceName": "String 2.2", "partOfSerial": "INV-B"}]

    def se_sites():
        pedidos["sites"] += 1
        return sites

    def se_devices(site_id):
        pedidos["devs"] += 1
        return devs

    def se_string_series(site_id, uuids, tzname, dia):
        pedidos["series"] += 1
        assert tzname == "America/Cuiaba"                    # a curva no fuso da usina, nunca em UTC
        return {u: series[u] for u in uuids if u in series}, lotes_falhos
    monkeypatch.setattr(app, "se_sites", se_sites)
    monkeypatch.setattr(app, "se_devices", se_devices)
    monkeypatch.setattr(app, "se_string_series", se_string_series)
    monkeypatch.setattr(app, "_PA_SE_ESTRUTURA", {})
    monkeypatch.setitem(app.EQUIP_NAMES, "UFV RenoGrid PA", {"Inverter 1": "Inversor 1.1", "Inverter 2": "Inversor 1.2"})
    return pedidos


def test_renogrid_soma_as_strings_de_cada_inversor_em_kw(monkeypatch):
    pedidos = _se_falso(monkeypatch, {"S11": [("10:00", 6000.0), ("10:15", 6100.0)],
                                      "S12": [("10:00", 5000.0), ("10:15", 5200.0)],
                                      "S21": [("10:00", 4000.0)], "S22": [("10:00", 3500.5), ("10:15", 3600.0)]})
    out = app._pa_ler_se(4425840, date(2026, 10, 12))
    d = pa.monta_dia(date(2026, 10, 12), out, date(2026, 10, 13))
    assert [(i["nome"], i["pontos"]) for i in d["inversores"]] == [
        ("Inversor 1.1", [[600, 11.0], [615, 11.3]]),
        ("Inversor 1.2", [[600, 7.5], [615, 3.6]])]          # a S21 sem o ponto das 10:15: a soma é só da S22...
    assert "potência CC" in d["obs"] and "America/Cuiaba" in d["obs"]
    assert "alguma string sem leitura" in d["obs"] and "Inversor 1.2 (1)" in d["obs"]     # ...e a tela diz onde
    assert "Inversor 1.1 (" not in d["obs"]
    # o site e os dispositivos ficam guardados: o 2º dia só pede as strings
    app._pa_ler_se(4425840, date(2026, 10, 11))
    assert pedidos == {"sites": 1, "devs": 1, "series": 2}


def test_renogrid_lote_que_falhou_ou_resposta_vazia_e_falha_nao_dia_sem_dado(monkeypatch):
    _se_falso(monkeypatch, {"S11": [("10:00", 6000.0)]}, lotes_falhos=1)
    with pytest.raises(pa.FonteNaoRespondeu, match="soma sairia menor"):
        app._pa_ler_se(4425840, date(2026, 10, 12))
    _se_falso(monkeypatch, {})                               # 200 sem dado: o limite de pedidos da SolarEdge
    with pytest.raises(pa.FonteNaoRespondeu, match="limite"):
        app._pa_ler_se(4425840, date(2026, 10, 12))
    _se_falso(monkeypatch, {}, sites=[])                     # sem o site não há o fuso: não desenha em UTC
    with pytest.raises(pa.FonteNaoRespondeu, match="lista de sites"):
        app._pa_ler_se(4425840, date(2026, 10, 12))


def test_renogrid_pela_rota_diz_a_grandeza_e_recusa_a_usina_que_o_tempo_real_nao_conhece(cli, monkeypatch, freeze_now):
    freeze_now("2026-10-13 15:00:00")
    _se_falso(monkeypatch, {"S11": [("10:00", 6000.0)], "S21": [("10:00", 4000.0)]})
    monkeypatch.setattr(app, "_se_cache", {"payload": {"rows": [{"plant_id": 4425840, "usina": "RenoGrid PA"}]}, "ts": 0})
    j = cli.get(f"{ROTA}?fonte=solaredge&usina=4425840&ini=2026-10-12&fim=2026-10-12").get_json()
    assert j["ok"] and j["grandeza"] == "Potência CC" and j["usina_nome"] == "RenoGrid PA"
    assert j["dias"][0]["situacao"] == "ok" and [i["nome"] for i in j["dias"][0]["inversores"]] == [
        "Inversor 1.1", "Inversor 1.2"]
    r = cli.get(f"{ROTA}?fonte=solaredge&usina=999&ini=2026-10-12&fim=2026-10-12")
    assert r.status_code == 400 and "desconhecida na SolarEdge" in r.get_json()["motivo"]
    lista = {x["fonte"]: x for x in cli.get(f"{ROTA}/usinas").get_json()["fontes"]}
    assert lista["solaredge"]["usinas"] == [{"id": "4425840", "nome": "RenoGrid PA"}]


def test_a_pagina_escreve_a_grandeza_da_fonte():
    assert "const gr = f.grandeza || 'Potência ativa';" in TPL and "Não é a potência ativa (CA) do inversor." in TPL
    assert "${gr.toLowerCase()} de cada inversor em kW" in TPL
