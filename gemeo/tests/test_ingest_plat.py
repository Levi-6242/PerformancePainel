# gemeo/tests/test_ingest_plat.py
"""Trackers das tres da 2C pela PV Plataforma (apiplataforma.pvoperation.com), com o token da conta oem@ que o Levi passou em
12/09/2026 ("Segue token separado"). Sondado ao vivo: /v2/usinas/trackers devolve, por INVERSOR, a lista dos seus trackers
(o de-para tracker -> inversor vem da propria API; a BD_Trackers nao tem as 2C) e /v2/usinas/trackerschart devolve o angulo
minuto a minuto do dia pedido. Os carimbos vem com sufixo 'GMT' falso: sao hora de Brasilia (a mediana da frota da Araputanga
cruza 0 grau as 12:50, que e o meio-dia solar de lon -58,3 em Brasilia; na Tupi, 12:23). HTTP e um duble com o formato real."""
import datetime as dt
import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from semear import limpar_tudo  # noqa: E402
from gemeo.core.modelos import UsinaRef  # noqa: E402
from gemeo.ingest import plat  # noqa: E402

UTC = dt.timezone.utc
TOKEN = "tok.oem.plat"


def _trk(id_, idinv, modbus, nome, ag=-10.8, al=-10.0):
    return {"id": id_, "idequipamento": None, "idinversor": idinv, "idmodbus": modbus, "idusina": 18771898, "nome": nome, "esn": "",
            "parametros": {"alertaPosicao": 1.5, "criticoPosicao": 3}, "situacao_trk": 1, "skc_motor": "",
            "ultimaleitura": {"posAg": ag, "posAl": al, "aComm": 0, "statusTRK": 512, "endMB": modbus}}


def estado():
    return {"success": True, "ultimaLeitura": "2026-09-11 13:16:00", "leiturasDia": [], "usina": [{"id": 18771898, "nome": "Araputanga"}],
            "dados": [{"idinversor": "400771", "idusina": "18771898", "nome": "INVERSOR01", "marcas": None,
                       "trackers": [_trk(23836, 400771, 1, "TRK1"), _trk(23837, 400771, 2, "TRK2", ag=-10.6)],
                       "dadosGerais": {"tsleitura": "2026-09-11 13:16:00", "Trackers": []}},
                      {"idinversor": "400772", "idusina": "18771898", "nome": "INVERSOR02", "marcas": None,
                       "trackers": [_trk(23842, 400772, 3, "TRK3")],
                       "dadosGerais": {"tsleitura": "2026-09-11 13:16:00", "Trackers": []}}]}


def _x(hhmm):
    return f"Fri, 11 Sep 2026 {hhmm}:00 GMT"


def grafico(minutos=range(0, 17)):
    def pts(base):
        return [{"x": _x(f"13:{m:02d}"), "y": round(base + m / 10, 2)} for m in minutos]
    return {"success": True, "grafico": {"TRK1": pts(10.0), "TRK2": pts(20.0), "TRK9": pts(0.0)},
            "leiturasDia": [{"dataleitura": "2026-09-11", "tsleitura": f"2026-09-11 13:{m:02d}:00"} for m in minutos], "usina": []}


class _Resp:
    def __init__(self, j, status=200):
        self._j, self.status_code, self.text = j, status, json.dumps(j)[:200]

    def json(self):
        return self._j


class Http:
    """Duble da PV Plataforma: token no header x-auth-token-update, dia do grafico em dd/mm/aaaa."""
    def __init__(self, estado_=None, graficos=None, status=200):
        self.estado, self.graficos, self.status = estado_ if estado_ is not None else estado(), graficos or {}, status
        self.chamadas: list[tuple] = []

    def get(self, url, headers=None, params=None, timeout=None):
        fim = url.rsplit("/", 1)[-1]
        self.chamadas.append((fim, dict(params or {})))
        assert headers["x-auth-token-update"] == TOKEN and headers["origin"] == "https://plataforma.pvoperation.com", headers
        if self.status != 200:
            return _Resp({"message": "Token invalido", "success": False}, self.status)
        if fim == "trackers":
            return _Resp(self.estado)
        if fim == "trackerschart":
            return _Resp(self.graficos.get(params["dataleitura"], {"success": True, "grafico": {}, "leiturasDia": [], "usina": []}))
        raise AssertionError(url)


def _cfg(token=TOKEN):
    return types.SimpleNamespace(plat_base="http://plat", pv_plat_token_oem=token, sobreposicao_min=30)


# ── funcoes puras ─────────────────────────────────────────────────────────────
def test_carimbo_do_grafico_e_brasilia_com_sufixo_gmt_falso():
    assert plat.ts_utc("Fri, 11 Sep 2026 12:50:00 GMT") == dt.datetime(2026, 9, 11, 15, 50, tzinfo=UTC)
    assert plat.ts_utc("2026-09-11 13:16:00") == dt.datetime(2026, 9, 11, 16, 16, tzinfo=UTC)          # tsleitura do estado


def test_estado_lista_os_trackers_de_cada_inversor():
    assert plat.trackers_do_estado(estado()) == [("TRK1", "400771", 1, 23836), ("TRK2", "400771", 2, 23837), ("TRK3", "400772", 3, 23842)]
    assert plat.trackers_do_estado({"success": False, "message": "x"}) == []


def test_grafico_vira_uma_amostra_de_angulo_por_bloco_de_15_min_dentro_da_janela():
    """1 ponto/min x 59 trackers = 85 mil linhas/dia so na Araputanga; o modelo trabalha em blocos de 15 min (mesma regra do
    p_ac da API PV). Tracker que o cadastro nao conhece fica fora; ponto fora da janela tambem."""
    mapa = {"TRK1": 21, "TRK2": 22}
    ini, fim = dt.datetime(2026, 9, 11, 16, 0, tzinfo=UTC), dt.datetime(2026, 9, 11, 16, 30, tzinfo=UTC)     # (13:00, 13:30] Brasilia
    ls = plat.leituras_grafico(grafico(), mapa, ini, fim)
    t15 = dt.datetime(2026, 9, 11, 16, 15, tzinfo=UTC)
    assert (21, "angulo", t15, 11.5) in ls and (22, "angulo", t15, 21.5) in ls
    assert [t for e, _, t, _ in ls if e == 21] == [dt.datetime(2026, 9, 11, 16, 1, tzinfo=UTC), t15]        # 13:00 esta FORA de (ini, fim]; 13:01 e a 1a do bloco
    assert len(ls) == 4 and not any(v == 0.0 for *_, v in ls)                                                # TRK9 nao existe no cadastro
    assert plat.leituras_grafico({"success": True, "grafico": {}}, mapa, ini, fim) == []


def test_estado_da_o_alvo_do_instante():
    mapa = {"TRK1": 21, "TRK2": 22, "TRK3": 23}
    ini, fim = dt.datetime(2026, 9, 11, 16, 0, tzinfo=UTC), dt.datetime(2026, 9, 11, 16, 30, tzinfo=UTC)
    ls = plat.leituras_estado(estado(), mapa, ini, fim)
    t = dt.datetime(2026, 9, 11, 16, 16, tzinfo=UTC)
    assert (21, "angulo_alvo", t, -10.0) in ls and (22, "angulo", t, -10.6) in ls and len(ls) == 9   # + alarme_com
    assert plat.leituras_estado(estado(), mapa, ini, dt.datetime(2026, 9, 11, 16, 10, tzinfo=UTC)) == []   # instante depois da janela


def test_dias_da_janela_sao_os_dias_de_brasilia_que_ela_toca():
    ini, fim = dt.datetime(2026, 9, 11, 2, 30, tzinfo=UTC), dt.datetime(2026, 9, 11, 3, 30, tzinfo=UTC)     # 23:30 de 10/09 a 00:30 de 11/09
    assert plat.dias_da_janela(ini, fim) == [dt.date(2026, 9, 10), dt.date(2026, 9, 11)]
    assert plat.dias_da_janela(dt.datetime(2026, 9, 11, 16, 0, tzinfo=UTC), dt.datetime(2026, 9, 11, 17, 0, tzinfo=UTC)) == [dt.date(2026, 9, 11)]


# ── com banco ────────────────────────────────────────────────────────────────
def _usina(conn, inversores=("400771", "400772")) -> UsinaRef:
    limpar_tudo(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO usina (codigo, nome, fonte, fonte_ref, tz) VALUES ('Araputanga','Araputanga','apipv','18771898','America/Cuiaba') RETURNING id")
        uid = cur.fetchone()[0]
        for n, idef in enumerate(inversores, 1):        # como a descoberta da fonte apipv os deixa
            cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte, nome_exibicao, atributos) VALUES (%s,'inversor',%s,%s,%s)",
                        (uid, idef, f"Inversor 1.{n}", json.dumps({"numero": n})))
    conn.commit()
    return UsinaRef(uid, "Araputanga", "apipv", "18771898", "America/Cuiaba")


def _equip(conn, u):
    with conn.cursor() as cur:
        cur.execute("SELECT t.codigo_fonte, i.codigo_fonte, t.atributos FROM equipamento t LEFT JOIN equipamento i ON i.id=t.pai_id "
                    "WHERE t.usina_id=%s AND t.tipo='tracker' ORDER BY t.codigo_fonte", (u.id,))
        return {c: (pai, a) for c, pai, a in cur.fetchall()}


def test_descobrir_cria_os_trackers_com_o_inversor_da_api_como_pai(conn):
    u = _usina(conn)
    http = Http()
    ing = plat.IngestorPlatTrackers(_cfg(), conn, [u], http=http)
    ing.descobrir(u)
    por = _equip(conn, u)
    assert por["TRK1"] == ("400771", {"numero": 1, "plat_id": 23836}) and por["TRK2"][0] == "400771" and por["TRK3"] == ("400772", {"numero": 3, "plat_id": 23842})
    ing.descobrir(u)
    assert len(_equip(conn, u)) == 3                                            # idempotente
    limpar_tudo(conn)


def test_tracker_cujo_inversor_ainda_nao_foi_descoberto_ganha_o_pai_depois(conn):
    """A descoberta da fonte apipv corre em outra thread: na primeira passada o inversor pode nao existir. O tracker nasce sem
    pai e a passada seguinte completa — em vez de ficar orfao para sempre (a parcela iria para a usina)."""
    u = _usina(conn, inversores=("400771",))
    ing = plat.IngestorPlatTrackers(_cfg(), conn, [u], http=Http())
    ing.descobrir(u)
    assert _equip(conn, u)["TRK3"][0] is None
    with conn.cursor() as cur:
        cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte, nome_exibicao, atributos) VALUES (%s,'inversor','400772','Inversor 1.2','{}')", (u.id,))
    conn.commit()
    ing.descobrir(u)
    assert _equip(conn, u)["TRK3"][0] == "400772"
    limpar_tudo(conn)


def test_buscar_baixa_o_grafico_de_cada_dia_da_janela_e_o_alvo_do_instante(conn):
    u = _usina(conn)
    http = Http(graficos={"11/09/2026": grafico()})
    ing = plat.IngestorPlatTrackers(_cfg(), conn, [u], http=http)
    ing.descobrir(u)
    ini, fim = dt.datetime(2026, 9, 11, 16, 0, tzinfo=UTC), dt.datetime(2026, 9, 11, 17, 0, tzinfo=UTC)
    b = ing.buscar(u, ini, fim)
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM equipamento WHERE usina_id=%s AND tipo='tracker' AND codigo_fonte='TRK1'", (u.id,))
        trk1 = cur.fetchone()[0]
    assert (trk1, "angulo", dt.datetime(2026, 9, 11, 16, 15, tzinfo=UTC), 11.5) in b.leituras
    assert (trk1, "angulo_alvo", dt.datetime(2026, 9, 11, 16, 16, tzinfo=UTC), -10.0) in b.leituras
    assert [c[1]["dataleitura"] for c in http.chamadas if c[0] == "trackerschart"] == ["11/09/2026"]
    assert b.n_requisicoes == 2 and b.esperadas == 3 * (60 // 15)               # 3 trackers, um angulo por bloco de 15 min
    limpar_tudo(conn)


def test_token_recusado_diz_qual_segredo_renovar(conn):
    """O token da PV Plataforma vale 7 dias e e colado a mao no gemeo.env (nao ha login por senha nesta API para a conta oem@).
    Quando vence, o ciclo tem de dizer ONDE renovar — e nao chamar mais nada ate la (disjuntor)."""
    u = _usina(conn)
    ing = plat.IngestorPlatTrackers(_cfg(), conn, [u], http=Http(status=401))
    with pytest.raises(RuntimeError, match="PV_PLAT_TOKEN_OEM"):
        ing.descobrir(u)
    assert ing.disjuntor.aberto()
    limpar_tudo(conn)


def test_marca_dagua_dos_trackers_e_a_dos_proprios_trackers():
    """A usina e a mesma da fonte apipv (inversores a cada 15 min). Se a marca d'agua fosse a da usina inteira, um token vencido
    por dias deixaria um buraco nos angulos que nenhum ciclo voltaria a cobrir — o p_ac teria empurrado a marca para frente."""
    assert plat.IngestorPlatTrackers.tipos == ("tracker",)


def test_runner_so_liga_os_trackers_da_plataforma_quando_ha_token_e_usina_apipv():
    from gemeo.ingest import runner
    u = UsinaRef(1, "Araputanga", "apipv", "18771898", "America/Cuiaba")
    base = dict(ritmo_min={"pg": 5, "sunop_fino": 5, "sunop_lento": 15, "cadastro": 60, "apipv": 15}, pv_oem_usuario="a", pv_oem_senha="b",
                usinas_detalhe={}, plat_base="http://plat", apipv_base="http://x", sobreposicao_min=30, bd_api_base="http://bd", bd_api_token="t",
                usinas_piloto=("Araputanga",), cache_dir=".", sunop_base="", sunop_token="", lote_pathnames=600, teto_sunop_dia=600,
                janela_solar=("05:40", "18:20"))
    com = runner.montar(types.SimpleNamespace(pv_plat_token_oem=TOKEN, **base), None, None, [u])
    sem = runner.montar(types.SimpleNamespace(pv_plat_token_oem="", **base), None, None, [u])
    assert [(r, m) for r, _, m in com if r == "plat"] == [("plat", 15)] and not [r for r, _, _ in sem if r == "plat"]


def test_validade_do_token_vem_do_exp_do_jwt():
    import base64
    tok = "h." + base64.urlsafe_b64encode(json.dumps({"exp": 1789789166}).encode()).decode().rstrip("=") + ".s"
    assert plat.validade_token(tok) == dt.datetime(2026, 9, 19, 3, 39, 26, tzinfo=UTC)
    assert plat.validade_token("opaco") is None


def test_estado_traz_o_alarme_de_comunicacao_de_cada_tracker():
    """Araputanga TRK5 (13/09/2026): a PV Plataforma manda posAg=0,0 fixo e aComm=1 — e um tracker MUDO, nao um angulo. O alarme
    entra como medida `alarme_com` (0/1) por ciclo, para o modelo e o card 'agora' distinguirem mudo de desalinhado."""
    est = estado()
    est["dados"][1]["trackers"][0]["ultimaleitura"]["aComm"] = 1        # TRK3 sem comunicacao
    mapa = {"TRK1": 21, "TRK2": 22, "TRK3": 23}
    ini, fim = dt.datetime(2026, 9, 11, 16, 0, tzinfo=UTC), dt.datetime(2026, 9, 11, 16, 30, tzinfo=UTC)
    ls = plat.leituras_estado(est, mapa, ini, fim)
    t = dt.datetime(2026, 9, 11, 16, 16, tzinfo=UTC)
    assert (21, "alarme_com", t, 0.0) in ls and (23, "alarme_com", t, 1.0) in ls
    assert len(ls) == 9                                                    # 3 trackers x (angulo, angulo_alvo, alarme_com)
