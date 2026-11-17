# -*- coding: utf-8 -*-
"""Recoleta pela conta oem@ da API PV (SEMP, Alves Lima e 2C) no contrato da Coletas do Nexus (17/11/2026). A regra é a
do coletor da noite (coletar_semp.py / coleta_2c.py); a API PV é dublada: o conftest recusa qualquer pedido à fonte
paga, e o teste que tentasse quebraria."""
import datetime as dt
import time
import types

import pytest

import app
import recoleta_apipv as rc
import recoleta_fontes
from recoleta_fontes import comum, oem

HOJE = dt.date(2026, 11, 17)
D1, D2 = dt.date(2026, 11, 10), dt.date(2026, 11, 11)
TUCANO1, MORADA, ARAP, SETE, TUPI, UNIAO = 18758732, 18766373, 18771898, 18771901, 18750925, 18772125
SC1, SC2, SC3 = 18771915, 18771929, 18771930


def _eq(us, es, u, e):
    return {"Usina Supervisório": us, "Equipamento Supervisório": es, "Usina": u, "Equipamento": e}


# A aba Equipamentos como está no espelho de 17/11/2026 (só as usinas da conta oem@).
EQUIP = (
    [_eq("UFV Tucano 1", "INVERSOR0%d" % i, "Tucano 1", "Inversor 1.%d" % i) for i in range(1, 5)]
    + [_eq("UFV Tucano 2", "INVERSOR0%d" % i, "Tucano 2", "Inversor 2.%d" % i) for i in range(1, 5)]
    + [_eq("MORADA NOVA", "INVERSOR0%d" % i, "Morada Nova", "Inversor 1.%d" % i) for i in range(1, 9)]
    + [_eq("Araputanga", "INVERSOR%02d" % i, "Araputanga", "Inversor 1.%d" % i) for i in range(1, 11)]
    + [_eq("Sete Lagoas", "INVERSOR%02d" % i, "Sete Lagoas", "Inversor 1.%d" % i) for i in range(1, 11)]
    + [_eq("Tupi Paulista", "INVERSOR%02d" % i, "Tupi Paulista", "Inversor 1.%d" % i) for i in range(1, 11)]
    + [_eq("Tupi Paulista", "INVERSOR%02d" % (i + 10), "Tupi Paulista", "Inversor 2.%d" % i) for i in range(1, 11)]
    + [_eq("União", "UG%d INVERSOR0%d" % (g, i), "União 1 e 2", "Inversor %d.%d" % (g, i))
       for g in (1, 2) for i in range(1, 7)]
    + [_eq("Santa Cecilia 1", "INVERSOR0 1.%d" % i, "Ipixuna do Pará", "Inversor 1.%d" % i) for i in range(1, 9)]
    + [_eq("Santa Cecilia 2", "INVERSOR0%d" % i, "Ipixuna do Pará", "Inversor 2.%d" % i) for i in range(1, 7)]
    + [_eq("Santa Cecilia 3", "INVERSOR0%d" % i, "Ipixuna do Pará", "Inversor 3.%d" % i) for i in range(1, 7)]
)


class Resp:
    def __init__(self, corpo, status=200, cab=None):
        self._c, self.status_code, self.headers = corpo, status, dict(cab or {})
        self.text = corpo if isinstance(corpo, str) else repr(corpo)

    def json(self):
        if isinstance(self._c, str):
            raise ValueError("não é json")
        return self._c


class ApiOem:
    """Dublê da API PV na conta oem@: o energy e o meteo de cada (planta, dia), o pedido por inversor e as plantas
    "grandes demais". Conta tudo o que foi pedido."""

    def __init__(self, energia=None, meteo=None, por_inv=None, grande=(), cab=None):
        self.energia, self.meteo, self.por_inv = energia or {}, meteo or {}, por_inv or {}
        self.grande, self.cab, self.feitas = set(grande), cab, []

    def post(self, url, **kw):
        c = kw["json"]
        self.feitas.append((url, dict(c)))
        p = str(c["period"]).replace("-", "")
        d = dt.date(int(p[:4]), int(p[4:6]), int(c["day"]))
        cab = self.cab(len(self.feitas)) if callable(self.cab) else self.cab
        if c["data_type"] == "meteo":
            return Resp(self.meteo.get((c["id"], d), []), 200, cab)
        if "idinverter" in c:
            return Resp(self.por_inv.get((c["id"], c["idinverter"], d), []), 200, cab)
        if c["id"] in self.grande:
            return Resp('{"error": "Resposta grande demais", "dica": "um único dispositivo (idinverter ou device_id)"}',
                        400, cab)
        return Resp(self.energia.get((c["id"], d), []), 200, cab)


def _ctx(api, inv_nomes=None, tela=None, cota_app=None, configurada=True, disjuntor=False):
    return types.SimpleNamespace(
        mapa=comum.Mapa(EQUIP), token=lambda force=False: "tok-oem", http=lambda: api,
        base="https://apipv.pvoperation.com.br/api/v1", base_v2="https://apipv.pvoperation.com.br/api/v2",
        inv_nomes=inv_nomes or (lambda pid: dict(app.PV_INV_NOMES.get(int(pid)) or {})),   # o de-para real da plataforma
        tela=tela or (lambda pid: {}),
        cota_app=cota_app if cota_app is not None else {"dia": None, "hora": None, "ts": 0.0, "zerada_ate": 0.0},
        reserva_dia=300, reserva_hora=20, disjuntor=lambda: disjuntor, configurada=configurada)


def _e(idi, eday, dia=D1):
    return {"idinversor": idi, "eday": eday, "dataleitura_new": dia.isoformat() + "T00:00:00"}


def _meteo(dia, ini="06:00", fim="18:00", poa=800.0, ghi=700.0, temp=40.0, passo_min=30):
    h, m = map(int, ini.split(":"))
    t, fim_t = dt.datetime.combine(dia, dt.time(h, m)), dt.datetime.combine(dia, dt.time(*map(int, fim.split(":"))))
    out = []
    while t <= fim_t:
        out.append({"tsleitura_new": t.isoformat(),
                    "conteudojson": {"IrPOA": poa, "piraGHI1": ghi, "tempMod": temp, "tempAmb": 25.0}})
        t += dt.timedelta(minutes=passo_min)
    return out


@pytest.fixture(autouse=True)
def _zera(monkeypatch):
    monkeypatch.setattr(comum, "_CONTA", {})
    monkeypatch.setattr(comum, "hoje_br", lambda agora_utc=None: HOJE)
    monkeypatch.setattr(oem, "_COTA", {"dia": None, "hora": None, "ts": 0.0, "zerada_ate": 0.0})
    monkeypatch.setattr(oem, "FORA", set())


def _ger(r):
    return {(g["usina"], g["inversor"], g["data"]): g["kwh"] for g in r["geracao"]}


# ---------------------------------------------------------------- as usinas e o de-para
def test_usinas_sao_as_da_conta_oem_e_os_ids_batem_com_o_de_para_da_plataforma():
    assert set(oem.POR_ID) == app.PV_OEM_PLANTS            # planta nova na oem@ da plataforma tem de entrar aqui
    for pid, nomes in app.PV_INV_NOMES.items():
        assert set(nomes) == set(oem.POR_ID[pid][1]["inversores"]), pid


def test_plantas_com_a_aba_do_bd_performance_e_a_ipixuna_em_tres():
    pl = oem.plantas(_ctx(ApiOem()))
    assert len(pl) == 10 and {p["destino"] for p in pl} == {"BD_Performance"}
    aba = {p["id"]: p["usina"] for p in pl}
    assert aba[str(TUCANO1)] == "Tucano 1" and aba[str(MORADA)] == "Morada Nova"        # pela aba Equipamentos
    assert aba[str(SETE)] == "Sete Lagoas" and aba[str(UNIAO)] == "União 1 e 2"          # "Sete Lagoa" na API
    assert [p["planta"] for p in pl if p["usina"] == "Ipixuna do Pará"] == [
        "Santa Cecilia 1", "Santa Cecilia 2", "Santa Cecilia 3"]
    with pytest.raises(comum.Recusa) as e:
        oem.plantas(_ctx(ApiOem(), configurada=False))
    assert e.value.status == 503 and "PV_OEM_USERNAME" in str(e.value)


def test_de_para_por_id_e_equipamento_sem_de_para_vira_aviso():
    api = ApiOem(energia={(ARAP, D1): [_e(400771, 812.4), _e(400772, "790.1"), _e(999999, 5.0)],
                          (TUCANO1, D1): [_e(378310, 1500.0), _e(378313, 1490.5)]})
    r = oem.buscar(_ctx(api), [str(ARAP), str(TUCANO1)], [D1], True, False, False)
    g = _ger(r)
    assert g == {("Araputanga", "Inversor 1.1", "2026-11-10"): 812.4,
                 ("Araputanga", "Inversor 1.2", "2026-11-10"): 790.1,
                 ("Tucano 1", "Inversor 1.1", "2026-11-10"): 1500.0,                    # INVERSOR01 pela Equipamentos
                 ("Tucano 1", "Inversor 1.4", "2026-11-10"): 1490.5}
    txt = " | ".join(r["avisos"])
    assert "999999" in txt and "fora do de-para" in txt
    assert "8 inversor(es) do de-para sem leitura" in txt                               # vazio, não 0
    # sem plant_devices (a oem@ recebe "Invalid permission"): só o energy, uma consulta por planta x dia
    assert [(u.rsplit("/", 1)[1], c["data_type"]) for u, c in api.feitas] == [("custom_query", "energy")] * 2


def test_tela_por_cima_e_os_dois_de_paras_divergindo_viram_aviso():
    api = ApiOem(energia={(ARAP, D1): [_e(400771, 812.4), _e(400775, 700.0)]})
    tela = {"400771": "INVERSOR03"}                       # a tela diz que o 400771 é o INVERSOR03 = Inversor 1.3
    plat = lambda pid: {**app.PV_INV_NOMES[ARAP], 400771: "INVERSOR03"}                   # noqa: E731 (tela por cima)
    r = oem.buscar(_ctx(api, tela=lambda pid: tela, inv_nomes=plat), [str(ARAP)], [D1], True, False, False)
    assert _ger(r) == {("Araputanga", "Inversor 1.3", "2026-11-10"): 812.4,
                       ("Araputanga", "Inversor 1.5", "2026-11-10"): 700.0}
    # a plataforma mudou o 400771 e o coletor não: não se adivinha
    plat2 = lambda pid: {**app.PV_INV_NOMES[ARAP], 400771: "Inversor 1.9"}                # noqa: E731
    r = oem.buscar(_ctx(api, inv_nomes=plat2), [str(ARAP)], [D1], True, False, False)
    assert _ger(r) == {("Araputanga", "Inversor 1.5", "2026-11-10"): 700.0}
    assert any("400771" in a and "concordarem" in a for a in r["avisos"])
    assert not any("sem coluna" in a or "fora do de-para" in a for a in r["avisos"])     # um aviso só, o certo


def test_uniao_e_ipixuna_com_os_nomes_do_supervisorio_da_plataforma_e_os_do_coletor():
    """A plataforma chama de "INVERSOR0 1.1" (Santa Cecilia 1) e "UNI_Inv_2.1" (União); o coletor, pela coluna."""
    ctx = _ctx(ApiOem())
    sc1 = oem.depara(ctx, "Santa Cecilia 1", oem.USINAS["Santa Cecilia 1"])
    assert sc1["col"][400840] == ("Ipixuna do Pará", "Inversor 1.1") and sc1["avisos"] == [] and not sc1["sem_trad"]
    un = oem.depara(ctx, "União", oem.USINAS["União"])
    assert un["col"][401313] == ("União 1 e 2", "Inversor 2.1") and un["col"][401322] == ("União 1 e 2", "Inversor 1.1")


# ---------------------------------------------------------------- Tupi por inversor
def test_tupi_vai_um_inversor_por_vez_quando_a_usina_inteira_e_grande_demais():
    ids = sorted(oem.USINAS["Tupi Paulista"]["inversores"])
    api = ApiOem(grande={TUPI}, por_inv={(TUPI, i, D1): [{"eday": 100.0 + k, "dataleitura_new": "2026-11-10"}]
                                          for k, i in enumerate(ids)})
    r = oem.buscar(_ctx(api), [str(TUPI)], [D1], True, False, False)
    g = _ger(r)
    assert len(g) == 20 and g[("Tupi Paulista", "Inversor 1.1", "2026-11-10")] == 100.0
    assert g[("Tupi Paulista", "Inversor 2.10", "2026-11-10")] == 119.0
    por_inv = [c for u, c in api.feitas if "idinverter" in c]
    assert len(api.feitas) == 21 and [c["idinverter"] for c in por_inv] == ids
    assert all(u.endswith("/api/v2/custom_query") and c["period"] == "202611" for u, c in api.feitas[1:])
    assert comum.restante("oem", oem.TETO) == oem.TETO - 20          # o a mais sai do teto do dia
    assert any("20 consulta(s) a mais" in a for a in r["avisos"])


def test_tupi_por_inversor_que_nao_cabe_no_teto_nao_pede_nada(monkeypatch):
    monkeypatch.setattr(oem, "TETO", 10)
    api = ApiOem(grande={TUPI})
    r = oem.buscar(_ctx(api), [str(TUPI)], [D1], True, False, False)
    assert r["geracao"] == [] and len(api.feitas) == 1
    assert any("grande demais" in a and "teto" in a for a in r["avisos"])


# ---------------------------------------------------------------- Ipixuna: três plantas numa aba
def test_ipixuna_soma_as_tres_plantas_numa_aba_e_a_etm_sai_de_uma_so():
    en = {(SC1, D1): [_e(i, 1000.0) for i in oem.USINAS["Santa Cecilia 1"]["inversores"]],
          (SC2, D1): [_e(i, 900.0) for i in oem.USINAS["Santa Cecilia 2"]["inversores"]],
          (SC3, D1): [_e(i, 800.0) for i in oem.USINAS["Santa Cecilia 3"]["inversores"]]}
    api = ApiOem(energia=en, meteo={(SC1, D1): _meteo(D1, poa=-1.0)})        # o POA inclinado da Ipixuna não mede
    ids = [str(SC1), str(SC2), str(SC3)]
    r = oem.buscar(_ctx(api), ids, [D1], True, True, False)
    g = _ger(r)
    assert len(g) == 20 and {k[0] for k in g} == {"Ipixuna do Pará"}
    assert g[("Ipixuna do Pará", "Inversor 1.8", "2026-11-10")] == 1000.0
    assert g[("Ipixuna do Pará", "Inversor 2.6", "2026-11-10")] == 900.0
    assert g[("Ipixuna do Pará", "Inversor 3.1", "2026-11-10")] == 800.0
    met = [c for _u, c in api.feitas if c["data_type"] == "meteo"]
    assert [c["id"] for c in met] == [SC1]                                    # uma estação: uma consulta, não três
    assert len(api.feitas) == oem.custo(ids, [D1], True, True, False) == 4
    assert [(e["coluna"], e["valor"]) for e in r["escalares"]] == [("GHI", 8.4)]       # 700 W/m² × 12 h
    assert any("IPOA sem valor" in a for a in r["avisos"])
    r = oem.buscar(_ctx(ApiOem(energia=en)), [str(SC2)], [D1], True, False, False)
    assert any("1 das 3 plantas" in a for a in r["avisos"])                   # o dias_fora contaria a aba inteira


# ---------------------------------------------------------------- nulo é nulo
def test_nulo_nao_vira_zero_e_dois_ids_na_mesma_coluna_somam():
    api = ApiOem(energia={(MORADA, D1): [_e(388162, None), _e(388159, 0.0), _e(388158, "abc"),
                                         _e(388164, None), _e(402513, 677.7),     # o INVERSOR08 trocou de id
                                         _e(388165, 1900.0, dia=dt.date(2026, 11, 9))]})   # outro dia não entra
    r = oem.buscar(_ctx(api), [str(MORADA)], [D1], True, False, False)
    g = _ger(r)
    assert g[("Morada Nova", "Inversor 1.1", "2026-11-10")] is None          # Eday nulo: nulo, nunca 0
    assert g[("Morada Nova", "Inversor 1.3", "2026-11-10")] is None          # Eday ilegível também
    assert g[("Morada Nova", "Inversor 1.2", "2026-11-10")] == 0.0           # zero medido fica zero
    assert g[("Morada Nova", "Inversor 1.8", "2026-11-10")] == 677.7         # nulo + 677,7
    assert ("Morada Nova", "Inversor 1.4", "2026-11-10") not in g             # sem leitura do dia: não inventa linha
    assert any("geração nula" in a and "Inversor 1.1" in a for a in r["avisos"])


def test_api_sem_nenhuma_leitura_e_queda_da_fonte_nao_de_nome():
    r = oem.buscar(_ctx(ApiOem()), [str(MORADA)], [D1], True, False, False)
    assert r["geracao"] == [] and any("NENHUMA leitura" in a and "fora de operação" in a for a in r["avisos"])


def test_usina_declarada_fora_vira_aviso_sem_consulta(monkeypatch):
    monkeypatch.setattr(oem, "FORA", {comum.chave_nome("MORADA NOVA")})
    api = ApiOem()
    assert oem.custo([str(MORADA)], [D1, D2], True, True, False) == 0
    r = oem.buscar(_ctx(api), [str(MORADA)], [D1], True, True, False)
    assert api.feitas == [] and any("fora de operação" in a for a in r["avisos"])
    assert [p for p in oem.plantas(_ctx(api)) if p["id"] == str(MORADA)][0]["fora_de_operacao"] is True


# ---------------------------------------------------------------- ETM e temperatura
def test_etm_do_dia_inteiro_com_temperatura_da_tucano_e_meteo_parcial_nao_integra():
    api = ApiOem(meteo={(TUCANO1, D1): _meteo(D1, poa=800.0, ghi=600.0, temp=40.0),
                        (ARAP, D1): _meteo(D1, ini="16:15", fim="18:00")})
    r = oem.buscar(_ctx(api), [str(TUCANO1), str(ARAP)], [D1], False, True, False)
    esc = {(e["usina"], e["coluna"]): e["valor"] for e in r["escalares"]}
    assert esc == {("Tucano 1", "IPOA"): 9.6, ("Tucano 1", "GHI"): 7.2, ("Tucano 1", "Temperatura"): 40.0}
    assert any("Araputanga" in a and "cobre só 16:15-17:45" in a for a in r["avisos"])     # a de 08/09/2026


def test_chuva_nao_ha_nesta_conta_e_nao_gasta():
    api = ApiOem()
    assert oem.custo([str(TUCANO1)], [D1], False, False, True) == 0
    r = oem.buscar(_ctx(api), [str(TUCANO1)], [D1], False, False, True)
    assert api.feitas == [] and any(a.startswith("Chuva:") for a in r["avisos"])


# ---------------------------------------------------------------- custo e cota
def test_custo_planta_por_dia_na_geracao_e_aba_por_dia_na_etm():
    dias = [D1, D2]
    assert oem.custo([str(TUPI)], dias, True, False, False) == 2
    assert oem.custo([str(TUPI), str(ARAP)], dias, True, True, False) == 2 * (2 + 2)
    assert oem.custo([str(SC1), str(SC2), str(SC3), str(TUPI)], dias, True, True, False) == 2 * (4 + 2)
    assert oem.custo([str(SC1), str(SC2)], dias, False, True, True) == 2


def test_permite_com_a_cota_na_reserva():
    agora = time.time()
    ctx = _ctx(ApiOem())
    assert oem.permite(ctx, 0) is None and oem.permite(ctx, 50) is None          # sem leitura: a 1ª resposta traz
    oem._COTA.update(dia=310, hora=150, ts=agora)
    assert "reserva de 300" in oem.permite(ctx, 12) and oem.permite(ctx, 10) is None
    oem._COTA.update(dia=700, hora=25)
    assert "nesta hora" in oem.permite(ctx, 10)
    oem._COTA.update(dia=700, hora=150, ts=agora - 2 * 3600)                     # leitura velha não vale
    assert oem.permite(ctx, 10) is None
    # sem leitura própria, vale a da plataforma — que não diz a conta: na dúvida, contra
    ctx = _ctx(ApiOem(), cota_app={"dia": 305, "hora": 100, "ts": agora, "zerada_ate": 0.0})
    assert "não diz de qual conta" in oem.permite(ctx, 10)
    oem._COTA.update(dia=700, hora=150, ts=agora)                                # a da própria conta vence
    assert oem.permite(ctx, 10) is None
    oem._COTA["zerada_ate"] = agora + 600
    assert "zerou" in oem.permite(ctx, 1)
    oem._COTA["zerada_ate"] = 0.0
    assert "429" in oem.permite(_ctx(ApiOem(), cota_app={"ts": 0, "zerada_ate": agora + 120}), 1)
    assert "disjuntor" in oem.permite(_ctx(ApiOem(), disjuntor=True), 1)
    assert "PV_OEM_USERNAME" in oem.permite(_ctx(ApiOem(), configurada=False), 1)


def test_cota_lida_nos_cabecalhos_e_a_busca_para_na_reserva(monkeypatch):
    monkeypatch.setattr(oem, "TRABALHADORES", 1)
    api = ApiOem(energia={(ARAP, D1): [_e(400771, 1.0)], (ARAP, D2): [_e(400771, 2.0)]},
                 cab={"X-RateLimit-Remaining-Day": "300", "X-RateLimit-Remaining-Hour": "150"})
    r = oem.buscar(_ctx(api), [str(ARAP)], [D1, D2], True, False, False)
    assert oem._COTA["dia"] == 300 and len(api.feitas) == 1                      # a 2ª deixaria a conta em 299
    assert _ger(r) == {("Araputanga", "Inversor 1.1", "2026-11-10"): 1.0}
    assert any("2026-11-11: geração não pedida" in a and "reserva" in a for a in r["avisos"])
    oem._COTA.update(dia=None, hora=None, ts=0.0)
    api = ApiOem()
    api.post = lambda url, **kw: Resp({"message": "limite"}, 429, {"Retry-After": "120"})          # noqa: E731
    r = oem.buscar(_ctx(api), [str(ARAP)], [D1], True, False, False)
    assert oem._COTA["zerada_ate"] > time.time() + 60 and "zerou" in oem.permite(_ctx(api), 1)
    assert any("HTTP 429" in a for a in r["avisos"])


def test_401_renova_o_token_uma_vez():
    api = ApiOem(energia={(ARAP, D1): [_e(400771, 5.0)]})
    feitas, tokens = [], []
    orig = api.post

    def post(url, **kw):
        feitas.append(kw["headers"]["x-access-token"])
        return Resp({"message": "expirou"}, 401) if len(feitas) == 1 else orig(url, **kw)
    api.post = post
    ctx = _ctx(api)
    ctx.token = lambda force=False: tokens.append(force) or ("novo" if force else "velho")
    r = oem.buscar(ctx, [str(ARAP)], [D1], True, False, False)
    assert tokens == [False, True] and feitas == ["velho", "novo"] and _ger(r)


# ---------------------------------------------------------------- o que vem da plataforma e a rota
def test_contexto_pega_o_que_a_plataforma_ja_tem(monkeypatch):
    mapa = comum.Mapa(EQUIP)
    monkeypatch.setattr(app, "_recoleta_mapa", lambda: mapa)                     # sem ler o BD_Performance
    ctx = oem.contexto(app)
    assert ctx.mapa is mapa and ctx.token is app.get_token_oem and ctx.http is app._http
    assert ctx.base == app.BASE_URL and ctx.base_v2 == app.PV_V2_BASE and ctx.cota_app is app._pv_cota
    assert ctx.reserva_dia == app.PV_COTA_RESERVA_DIA and ctx.reserva_hora == app.PV_COTA_RESERVA_HORA
    assert ctx.inv_nomes(ARAP)[400771] == "Inversor 1.1" and ctx.tela(ARAP) == {}  # o conftest desliga a tela
    assert ctx.disjuntor() is False


def test_rota_generica_com_a_fonte_oem(monkeypatch):
    api = ApiOem(energia={(ARAP, D1): [_e(400771 + i, 500.0 + i) for i in range(10)]},
                 meteo={(ARAP, D1): _meteo(D1)})
    monkeypatch.setattr(app, "PASSWORD", "senha-pv-de-teste")
    monkeypatch.delenv("RECOLETA_CHAVE", raising=False)
    monkeypatch.setattr(oem, "contexto", lambda app_: _ctx(api))
    assert recoleta_fontes.modulo("oem") is oem
    cab = {"X-Recoleta-Chave": rc.chave_esperada("", "senha-pv-de-teste")}
    cli = app.app.test_client()
    pl = cli.get("/api/recoleta/oem/plantas", headers=cab).get_json()
    assert pl["paga"] is True and pl["teto"] == oem.TETO and pl["max_plantas"] == oem.MAX_PLANTAS
    corpo = {"ids": [str(ARAP)], "ini": "2026-11-10", "fim": "2026-11-10", "geracao": True, "etm": True}
    r = cli.post("/api/recoleta/oem", json=dict(corpo, simular=True), headers=cab).get_json()
    assert r["consultas"] == 2 and api.feitas == []
    r = cli.post("/api/recoleta/oem", json=corpo, headers=cab).get_json()
    assert r["consultas"] == 2 == len(api.feitas) and r["cota_restante"] == oem.TETO - 2
    assert len(r["geracao"]) == 10 and r["dias_fora"] == []
    assert {e["coluna"] for e in r["escalares"]} == {"IPOA", "GHI"}
