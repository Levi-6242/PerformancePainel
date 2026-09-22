# gemeo/tests/test_ingest_apipv.py
"""Fonte API PV Operation (conta oem@): as tres da 2C que a API enxerga — Araputanga, Sete Lagoa(s) e Tupi Paulista
(Levi, 11/09/2026: "comece com as usinas da 2C que estao na API PV"). Registros no formato real de 11/09 viram leituras
em UTC; a descoberta cria estacao, inversores com o nome do de-para e strings; dia passado so via custom_query quando a
janela cobre o dia. HTTP e banco de teste sao dubles com o formato real — o que se testa e o contrato, nao a API."""
import base64
import datetime as dt
import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from semear import limpar_tudo  # noqa: E402
from gemeo.core.modelos import UsinaRef  # noqa: E402
from gemeo.ingest import apipv  # noqa: E402

UTC = dt.timezone.utc


def _inv(idef, ts, **cj):
    return {"idefinversor": idef, "tsleitura_new": ts, "dataleitura_new": ts[:10] + " 00:00:00", "conteudojson": json.dumps(cj)}


def _met(ts, **cj):
    return {"iddispositivo": 4235, "tsleitura_new": ts, "conteudojson": json.dumps({"sn": "estacao_18771898", **cj})}


def _cfg(**extra):
    base = dict(apipv_base="http://x/api/v1", pv_oem_usuario="oem@x", pv_oem_senha="s", sobreposicao_min=30,
                usinas_detalhe={"Araputanga": {"fonte": "apipv", "fonte_ref": "18771898", "tz": "America/Cuiaba",
                                               "inversores": {"400771": "Inversor 1.1", "400772": "Inversor 1.2"}}})
    base.update(extra)
    return types.SimpleNamespace(**base)


class _Resp:
    def __init__(self, j, status=200):
        self._j, self.status_code, self.text = j, status, json.dumps(j)[:200]

    def json(self):
        return self._j


def _jwt(exp=9999999999):
    return "h." + base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=") + ".s"


class Http:
    """Duble da API PV com o formato real de 11/09/2026: token no header x-access-token, erro como dict."""
    def __init__(self, inv=None, met=None, plants=None, hist=None, erro=None):
        self.inv, self.met, self.plants, self.hist, self.erro = inv or [], met or [], plants or [], hist or {}, erro
        self.chamadas: list[tuple] = []

    def post(self, url, json=None, headers=None, timeout=None):
        fim = url.rsplit("/", 1)[-1]
        self.chamadas.append((fim, json, headers))
        if fim == "authenticate":
            assert json == {"username": "oem@x", "password": "s"}
            return _Resp({"token": _jwt()})
        assert headers == {"x-access-token": _jwt()}, headers
        if self.erro:
            return _Resp(self.erro)
        if fim == "day_inverter":
            return _Resp(self.inv)
        if fim == "day_meteo":
            return _Resp(self.met)
        if fim == "custom_query":
            return _Resp(self.hist.get((json["data_type"], json["day"]), []))
        raise AssertionError(url)

    def get(self, url, headers=None, timeout=None):
        self.chamadas.append(("plants", None, headers))
        return _Resp(self.plants)


# ── funcoes puras ─────────────────────────────────────────────────────────────
def test_carimbo_da_api_e_horario_de_brasilia_para_toda_usina():
    """As 19:26 de Brasilia (11/09) a ultima leitura da Araputanga (MT, UTC-4) era 19:20 e a da Tupi (SP) 19:22 — se o
    carimbo fosse hora local de MT, a Araputanga estaria em 18:2x. Fuso fixo, independente do tz da usina."""
    assert apipv.ts_utc("2026-09-11 13:18:00") == dt.datetime(2026, 9, 11, 16, 18, tzinfo=UTC)


def test_registros_do_inversor_viram_p_ac_e_dia_e_corrente_por_string():
    mapa = {("inversor", "400771"): 1, ("string", "400771.Ipv1"): 11, ("string", "400771.Ipv2"): 12}
    recs = [_inv(400771, "2026-09-11 13:18:00", Pac=250.27, Eday=1615.45, Ipv1=0.87, Ipv2="-", Ipv3=1.0, Status=40960.0),
            _inv(400771, "2026-09-11 13:21:00", Pac=249.9, Eday=1619.6, Ipv1=0.9, Ipv2=1.1),
            _inv(999999, "2026-09-11 13:18:00", Pac=1.0)]                        # inversor que o cadastro nao conhece: fora
    ini, fim = dt.datetime(2026, 9, 11, 16, 0, tzinfo=UTC), dt.datetime(2026, 9, 11, 17, 0, tzinfo=UTC)
    ls = apipv.leituras_inversor(recs, mapa, ini, fim, set())
    t1, t2 = dt.datetime(2026, 9, 11, 16, 18, tzinfo=UTC), dt.datetime(2026, 9, 11, 16, 21, tzinfo=UTC)
    assert (1, "p_ac", t1, 250.27) in ls and (1, "e_dia", t1, 1615.45) in ls and (1, "p_ac", t2, 249.9) in ls
    assert (11, "i_string", t1, 0.87) in ls and (12, "i_string", t2, 1.1) in ls   # Ipv2 '-' nao e numero; Ipv3 nao esta no cadastro
    assert (11, "i_string", t2, 0.9) not in ls                                  # corrente de string: uma amostra por bloco de 15 min
    assert not any(m == "estado" for _, m, *_ in ls)                            # Status da API nao vira medida
    assert len(ls) == 6


def test_p_ac_fica_com_uma_amostra_a_cada_5_min_como_as_fontes_pg():
    """1 leitura/min x 40 inversores x 2 medidas = 115 mil linhas/dia so nas tres; o modelo trabalha em blocos de 15 min e
    o PostgreSQL do Thopen entrega 5 min — mesma cadencia aqui. A estacao continua em 1 min (e a fisica do esperado)."""
    mapa = {("inversor", "400771"): 1}
    recs = [_inv(400771, f"2026-09-11 13:{m:02d}:00", Pac=float(m), Eday=1.0) for m in range(15, 25)]
    ini, fim = dt.datetime(2026, 9, 11, 16, 0, tzinfo=UTC), dt.datetime(2026, 9, 11, 17, 0, tzinfo=UTC)
    ls = apipv.leituras_inversor(recs, mapa, ini, fim, set())
    assert [v for _, m, _, v in ls if m == "p_ac"] == [15.0, 20.0] and [v for _, m, _, v in ls if m == "e_dia"] == [1.0, 1.0]
    est = [_met(f"2026-09-11 13:{m:02d}:00", Ir=float(m)) for m in range(15, 20)]
    assert [v for _, m, _, v in apipv.leituras_estacao(est, 7, ini, fim) if m == "poa"] == [15.0, 16.0, 17.0, 18.0, 19.0]


def test_so_entra_o_que_esta_dentro_da_janela():
    mapa = {("inversor", "400771"): 1}
    recs = [_inv(400771, "2026-09-11 12:00:00", Pac=1.0), _inv(400771, "2026-09-11 13:00:00", Pac=2.0), _inv(400771, "2026-09-11 14:00:00", Pac=3.0)]
    ini, fim = dt.datetime(2026, 9, 11, 15, 0, tzinfo=UTC), dt.datetime(2026, 9, 11, 16, 0, tzinfo=UTC)   # (12:00, 13:00] em Brasilia
    assert [v for _, m, _, v in apipv.leituras_inversor(recs, mapa, ini, fim, set()) if m == "p_ac"] == [2.0]


def test_estacao_usa_a_ordem_de_campos_do_coletor_e_descarta_lixo():
    """Medido em 11/09/2026: na Tupi piraPOA1 = 4921 W/m2 e piraGHI1 = '-' o dia todo; na Araputanga IrGHI = 41 milhoes.
    A ordem de campos e a do coletor (POA: IrPOA, Ir, Ir1, piraPOA1; GHI: piraGHI1, IrGHI, ...) e |valor| >= 2000 nao e medida."""
    tupi = _met("2026-09-11 13:32:00", Ir=1108.5, piraPOA1=4921.7, piraGHI1="-", IrGHI=1072.4, tempMod=50.4, tempAmb=34.0, velVento=7.7)
    ara = _met("2026-09-11 13:18:00", Ir=1167.7, piraPOA1=1167.7, piraGHI1=1163.9, IrGHI=41403952.0, tempMod=53.1, tempAmb=37.2, velVento=8.1)
    ini, fim = dt.datetime(2026, 9, 11, 15, 0, tzinfo=UTC), dt.datetime(2026, 9, 11, 17, 0, tzinfo=UTC)
    por = {m: v for _, m, _, v in apipv.leituras_estacao([tupi], 7, ini, fim)}
    assert por == {"poa": 1108.5, "ghi": 1072.4, "temp_modulo": 50.4, "temp_ar": 34.0, "vento": 7.7}
    por = {m: v for _, m, _, v in apipv.leituras_estacao([ara], 7, ini, fim)}
    assert por["poa"] == 1167.7 and por["ghi"] == 1163.9
    assert all(e == 7 and t == dt.datetime(2026, 9, 11, 16, 18, tzinfo=UTC) for e, _, t, _ in apipv.leituras_estacao([ara], 7, ini, fim))
    assert apipv.irradiancia({"piraGHI1": "-", "IrGHI": 41403952.0}, apipv.CAMPOS_GHI) is None     # so lixo: sem leitura
    assert apipv.irradiancia({"Ir": -1.8}, apipv.CAMPOS_POA) == -1.8                             # offset noturno e medida (o piso -20 e do base)
    assert apipv.leituras_estacao([tupi], None, ini, fim) == []                                  # usina sem estacao cadastrada


def test_coordenada_da_api_com_virgula_e_espaco():
    """/plants (oem@) escreve '-15,479992' na Araputanga e ' -44.203342\\xa0 ' na Sete Lagoa (11/09/2026)."""
    assert apipv.coord("-15,479992") == -15.479992 and apipv.coord(" -44.203342\xa0 ") == -44.203342
    assert apipv.coord(None) is None and apipv.coord("") is None and apipv.coord("x") is None


def test_dia_passado_so_quando_a_janela_cobre_o_dia_de_verdade():
    hoje = dt.date(2026, 9, 11)
    ini, fim = dt.datetime(2026, 9, 8, 22, 30, tzinfo=UTC), dt.datetime(2026, 9, 11, 22, 30, tzinfo=UTC)   # primeiro ciclo: 3 dias
    assert apipv.dias_passados(ini, fim, hoje) == [dt.date(2026, 9, 8), dt.date(2026, 9, 9), dt.date(2026, 9, 10)]
    # marca d'agua as 00:13 de Brasilia com 30 min de sobreposicao: 17 min de ontem nao valem 146 s de custom_query
    ini, fim = dt.datetime(2026, 9, 11, 2, 43, tzinfo=UTC), dt.datetime(2026, 9, 11, 3, 15, tzinfo=UTC)
    assert apipv.dias_passados(ini, fim, hoje) == []
    # reconciliacao (24 h) a meia-noite de Brasilia: ontem inteiro
    ini, fim = dt.datetime(2026, 9, 10, 3, 0, tzinfo=UTC), dt.datetime(2026, 9, 11, 3, 0, tzinfo=UTC)
    assert apipv.dias_passados(ini, fim, hoje) == [dt.date(2026, 9, 10)]


# ── com banco ─────────────────────────────────────────────────────────────────
def _usina(conn) -> UsinaRef:
    limpar_tudo(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO usina (codigo, nome, fonte, fonte_ref, tz) VALUES ('Araputanga','Araputanga','apipv','18771898','America/Cuiaba') RETURNING id")
        uid = cur.fetchone()[0]
    conn.commit()
    return UsinaRef(uid, "Araputanga", "apipv", "18771898", "America/Cuiaba")


def _http_hoje():
    return Http(inv=[_inv(400772, "2026-09-11 13:18:00", Pac=1.0, Eday=2.0, Ipv1=0.5, Ipv2=0.6),
                     _inv(400771, "2026-09-11 13:18:00", Pac=250.0, Eday=1600.0, Ipv1=0.5, Ipv2=0.6, Ipv3=0.7)],
                met=[_met("2026-09-11 13:18:00", Ir=1000.0, piraGHI1=900.0, tempMod=50.0, tempAmb=30.0, velVento=2.0)],
                plants=[{"id": 18771898, "nome": "Araputanga", "capacidade": "3469.20", "latitude": "-15,479992", "longitude": "-58,3263"},
                        {"id": 1, "nome": "Outra", "latitude": "0", "longitude": "0"}])


def test_descobrir_cria_estacao_inversores_nomeados_e_strings_e_preenche_coordenadas(conn):
    u = _usina(conn)
    http = _http_hoje()
    ing = apipv.IngestorAPIPV(_cfg(), conn, [u], http=http)
    ing.descobrir(u)
    with conn.cursor() as cur:
        cur.execute("SELECT tipo, codigo_fonte, nome_exibicao, atributos FROM equipamento WHERE usina_id=%s", (u.id,))
        por = {(t, c): (n, a) for t, c, n, a in cur.fetchall()}
        cur.execute("SELECT lat, lon, kwp_dc FROM usina WHERE id=%s", (u.id,))
        placa = cur.fetchone()
        cur.execute("SELECT count(*) FROM equipamento s JOIN equipamento i ON i.id=s.pai_id WHERE s.usina_id=%s AND s.tipo='string' "
                    "AND i.tipo='inversor' AND s.codigo_fonte LIKE i.codigo_fonte || '.Ipv%%'", (u.id,))
        com_pai = cur.fetchone()[0]
    assert por[("estacao", "ESTM")][0] is None
    assert por[("inversor", "400771")] == ("Inversor 1.1", {"numero": 1}) and por[("inversor", "400772")] == ("Inversor 1.2", {"numero": 2})
    assert por[("string", "400771.Ipv3")][1] == {"numero": 3} and ("string", "400772.Ipv3") not in por
    assert com_pai == 5 and len(por) == 8                                       # 1 estacao + 2 inversores + 5 strings
    assert placa == (-15.479992, -58.3263, 3469.2)
    ing.descobrir(u)                                                            # idempotente
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM equipamento WHERE usina_id=%s", (u.id,))
        assert cur.fetchone()[0] == 8
    assert sum(1 for c in http.chamadas if c[0] == "authenticate") == 1         # token pedido uma vez
    limpar_tudo(conn)


def test_buscar_hoje_reaproveita_o_dia_baixado_na_descoberta(conn):
    u = _usina(conn)
    http = _http_hoje()
    ing = apipv.IngestorAPIPV(_cfg(), conn, [u], http=http)
    ing.descobrir(u)
    ini, fim = dt.datetime(2026, 9, 11, 16, 0, tzinfo=UTC), dt.datetime(2026, 9, 11, 17, 0, tzinfo=UTC)
    b = ing.buscar(u, ini, fim)
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM equipamento WHERE usina_id=%s AND tipo='inversor' AND codigo_fonte='400771'", (u.id,))
        inv1 = cur.fetchone()[0]
        cur.execute("SELECT id FROM equipamento WHERE usina_id=%s AND tipo='estacao'", (u.id,))
        est = cur.fetchone()[0]
    t = dt.datetime(2026, 9, 11, 16, 18, tzinfo=UTC)
    assert (inv1, "p_ac", t, 250.0) in b.leituras and (est, "poa", t, 1000.0) in b.leituras and (est, "ghi", t, 900.0) in b.leituras
    assert len(b.leituras) == 2 * 2 + 5 + 5                                     # 2 inversores x (p_ac, e_dia) + 5 strings + 5 medidas da estacao
    assert sum(1 for c in http.chamadas if c[0] == "day_inverter") == 1 and b.n_requisicoes == 2     # descoberta e busca dividem a mesma baixa
    assert not any(c[0] == "custom_query" for c in http.chamadas)               # janela so de hoje: nada de historico
    limpar_tudo(conn)


def test_dia_passado_vem_do_custom_query_com_o_dia_de_brasilia(conn):
    u = _usina(conn)
    http = _http_hoje()
    http.hist = {("inverter", 10): [_inv(400771, "2026-09-10 12:00:00", Pac=100.0, Eday=5.0, Ipv1=3.0)],
                 ("meteo", 10): [_met("2026-09-10 12:00:00", Ir=900.0)]}
    ing = apipv.IngestorAPIPV(_cfg(), conn, [u], http=http)
    ing.descobrir(u)
    ini, fim = dt.datetime(2026, 9, 10, 3, 0, tzinfo=UTC), dt.datetime(2026, 9, 11, 16, 30, tzinfo=UTC)    # 00:00 de ontem ate agora
    b = ing.buscar(u, ini, fim)
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM equipamento WHERE usina_id=%s AND tipo='inversor' AND codigo_fonte='400771'", (u.id,))
        inv1 = cur.fetchone()[0]
        cur.execute("SELECT id FROM equipamento WHERE usina_id=%s AND tipo='estacao'", (u.id,))
        est = cur.fetchone()[0]
    ontem = dt.datetime(2026, 9, 10, 15, 0, tzinfo=UTC)
    assert (inv1, "p_ac", ontem, 100.0) in b.leituras and (est, "poa", ontem, 900.0) in b.leituras
    assert (inv1, "p_ac", dt.datetime(2026, 9, 11, 16, 18, tzinfo=UTC), 250.0) in b.leituras                 # e o de hoje continua
    corpos = [c[1] for c in http.chamadas if c[0] == "custom_query"]
    assert corpos == [{"id": 18771898, "data_type": "inverter", "period": "2026-09", "day": 10},
                      {"id": 18771898, "data_type": "meteo", "period": "2026-09", "day": 10}]
    assert b.n_requisicoes == 4
    limpar_tudo(conn)


def test_erro_da_api_vem_como_dict_e_vira_falha_em_voz_alta(conn):
    """A API PV devolve erro como DICT (401 {"error": "Invalid id"} para id de outra conta); iterar as chaves como se
    fossem registros ja derrubou rota da plataforma. Aqui e excecao — o ciclo registra 'falha' com o texto."""
    u = _usina(conn)
    http = _http_hoje()
    http.erro = {"error": "Invalid id"}
    ing = apipv.IngestorAPIPV(_cfg(), conn, [u], http=http)
    with pytest.raises(RuntimeError) as e:
        ing.buscar(u, dt.datetime(2026, 9, 11, 16, 0, tzinfo=UTC), dt.datetime(2026, 9, 11, 17, 0, tzinfo=UTC))
    assert "Invalid id" in str(e.value)
    limpar_tudo(conn)


def test_sem_credencial_falha_nomeando_as_chaves(conn):
    u = _usina(conn)
    ing = apipv.IngestorAPIPV(_cfg(pv_oem_usuario="", pv_oem_senha=""), conn, [u], http=_http_hoje())
    with pytest.raises(RuntimeError) as e:
        ing.descobrir(u)
    assert "PV_OEM_USERNAME" in str(e.value) and "PV_OEM_PASSWORD" in str(e.value)
    limpar_tudo(conn)
