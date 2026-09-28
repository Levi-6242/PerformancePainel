# -*- coding: utf-8 -*-
"""Usina calada DESLIGADA x SEM COMUNICAÇÃO, e o relógio do registrador em outro fuso (Levi, 28/09/2026, sobre três
prints da aba API PV).

    "Ceilândia 1.1, 1.2 e 1.3 está desligada. Assis 1, Brodowski 1 e Ribeirão também está desligada, tem que ter essa
    observação, da mesma forma que observa os inversores tem que observar a usina. Diamantino 1 e 2, Alto Paraná 1 e
    Sitio dos Nogueiras 1 está comunicando normalmente, corrija. Canarana 1 e Mandaguaçu e Santo Anastácio está
    desligado."

Medido na API PV às 09:46–10:05 de 28/09 (153 usinas, uma chamada cada):
  - DIAMANTINO 1 e 2: dado minuto a minuto, sempre 62–63 min atrás — às 09:46 ia até 08:44, às 09:54 até 08:52, às
    10:05 até 09:03 com ~250 kW por inversor. É o relógio do registrador no horário de Cuiabá (UTC−4), não falta de
    comunicação; são as ÚNICAS duas das 153 assim. A Canarana, também no MT, manda no horário de Brasília: o fuso é do
    registrador, não do estado — por isso a plataforma APRENDE o atraso de cada usina em vez de uma tabela por UF.
  - Usina calada: a API não diz se a usina está desligada. A plataforma passa a ler assim quando há motivo — OS de
    Religamento aberta na usina inteira no Fracttal (Ceilândia 1 #14711, Assis #14715, Brodowski #12693), a estação
    comunicando com os inversores calados há mais de 2 h (Canarana 1: estação às 09:48, inversores desde 23/09) ou a
    marcação do analista com a observação (Mandaguaçu, Santo Anastácio, Ribeirão: nada no dado, nada no Fracttal).
    Sem motivo, continua "sem comunicação". A marcação some sozinha quando a usina volta a gerar.
  - Alto Paraná 1 e Sítio dos Nogueiras 1: na hora do print a API não tinha o dado delas (a Alto Paraná, nada de 21:01
    às ~09:17); às 09:43 estavam em dia. A plataforma mostrou o que a fonte tinha — nada a corrigir aqui.
"""
import json
import pathlib
import shutil
import subprocess
from datetime import datetime

import pytest

import app


def _t(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


# ── relógio do registrador ────────────────────────────────────────────────────
@pytest.fixture
def relogio(monkeypatch):
    mem = {}
    monkeypatch.setattr(app, "_pv_relogio", mem)
    monkeypatch.setattr(app, "_pv_relogio_save", lambda: None)
    return mem


def test_registrador_uma_hora_atras_com_dado_andando_e_corrigido(relogio):
    c = app._pv_relogio_corrige
    # 1ª leitura com 62 min: pode ser relógio, pode ser usina que parou há uma hora — só vira candidato
    assert c(18751455, "2026-09-28 08:44:00", _t("2026-09-28 09:46:00")) == "2026-09-28 08:44:00"
    # o dado ANDOU e a defasagem repetiu: é o relógio. Usina parada não anda.
    assert c(18751455, "2026-09-28 08:52:00", _t("2026-09-28 09:54:00")) == "2026-09-28 09:52:00"
    assert c(18751455, "2026-09-28 09:03:00", _t("2026-09-28 10:05:00")) == "2026-09-28 10:03:00"
    assert app._pv_relogio_h(18751455) == 1


def test_usina_que_parou_ha_uma_hora_nao_vira_relogio(relogio):
    """Ceilândia 1.1 de 28/09: gerando 1,4 MW até 08:10 e nada depois. O carimbo não anda — não é fuso."""
    c = app._pv_relogio_corrige
    assert c(53241, "2026-09-28 08:10:00", _t("2026-09-28 09:10:00")) == "2026-09-28 08:10:00"
    assert c(53241, "2026-09-28 08:10:00", _t("2026-09-28 09:14:00")) == "2026-09-28 08:10:00"
    assert c(53241, "2026-09-28 08:10:00", _t("2026-09-28 09:25:00")) == "2026-09-28 08:10:00"
    assert app._pv_relogio_h(53241) == 0


def test_relogio_consertado_zera_na_hora(relogio):
    c = app._pv_relogio_corrige
    c(1, "2026-09-28 08:44:00", _t("2026-09-28 09:46:00"))
    c(1, "2026-09-28 08:52:00", _t("2026-09-28 09:54:00"))
    assert app._pv_relogio_h(1) == 1
    assert c(1, "2026-09-28 10:03:00", _t("2026-09-28 10:05:00")) == "2026-09-28 10:03:00", "acertaram o relógio"
    assert app._pv_relogio_h(1) == 0


def test_usina_com_relogio_atrasado_que_para_volta_a_ser_sem_comunicacao(relogio, monkeypatch, freeze_now):
    """A correção não esconde parada de verdade: com o dado parado a leitura corrigida envelhece como qualquer outra."""
    c = app._pv_relogio_corrige
    c(7, "2026-09-28 08:44:00", _t("2026-09-28 09:46:00"))
    c(7, "2026-09-28 08:52:00", _t("2026-09-28 09:54:00"))
    assert c(7, "2026-09-28 08:52:00", _t("2026-09-28 10:40:00")) == "2026-09-28 09:52:00"   # 48 min: já passou dos 30


# a linha da usina (build_summary), com o mesmo molde de test_inversor_sem_leitura_desligado.py
PID, NOME = 987691, "Usina Teste Relogio"


def _rec(inv_id, ts):
    cj = {"Pac": 250.0, "Eday": 100.0, "Temp": 30.0}
    cj.update({f"Ipv{i + 1}": 8.0 for i in range(4)})
    return {"idefinversor": inv_id, "tsleitura_new": ts, "conteudojson": json.dumps(cj)}


@pytest.fixture
def usina(monkeypatch, relogio):
    monkeypatch.setitem(app.ESPERADO, NOME, {"inv_esp": 2, "str_esp": 8})
    monkeypatch.setattr(app, "STRING_BOX", set(app.STRING_BOX) - {NOME})
    monkeypatch.setattr(app, "_pv_plant_devices", lambda pid: [])
    monkeypatch.setattr(app, "_pv_dev_names", lambda pid, token: {})
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "")
    monkeypatch.setattr(app, "_os_atribuidas_map", lambda: {})
    monkeypatch.setattr(app, "_os_fracttal_inv_abertas", lambda: {})
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    return {"id": PID, "nome": NOME}


def test_linha_da_usina_deixa_de_acusar_sem_comunicacao_depois_de_aprender_o_relogio(usina, freeze_now):
    freeze_now("2026-09-28 09:46:00")
    r = app.build_summary(usina, [_rec(1, "2026-09-28 08:44:00"), _rec(2, "2026-09-28 08:44:00")])
    assert r["falha_comunicacao"] is True, "1ª vez ainda não dá para saber"
    freeze_now("2026-09-28 09:54:00")
    r = app.build_summary(usina, [_rec(1, "2026-09-28 08:52:00"), _rec(2, "2026-09-28 08:52:00")])
    assert r["falha_comunicacao"] is False and r["ultima_leitura"] == "2026-09-28 09:52:00"


def test_estacao_do_mesmo_registrador_tambem_e_corrigida(relogio):
    """A ETM da Diamantino vinha "Sem comunicação · última há 65 min" pelo mesmo relógio."""
    c = app._pv_relogio_corrige
    c(18751455, "2026-09-28 08:44:00", _t("2026-09-28 09:46:00"))
    c(18751455, "2026-09-28 08:52:00", _t("2026-09-28 09:54:00"))
    serie = [(_t("2026-09-28 08:50:00"), 500.0, 450.0), (_t("2026-09-28 08:52:00"), 510.0, 455.0)]
    assert [s[0] for s in app._pv_relogio_serie(18751455, serie)] == [_t("2026-09-28 09:50:00"), _t("2026-09-28 09:52:00")]
    assert app._pv_relogio_serie(99, serie) == serie, "sem relógio aprendido, a série passa intacta"


# ── usina calada: desligada ou sem comunicação ──────────────────────────────
def _calada(**kw):
    base = {"usina": "Ceilandia 1.1 (89)", "plant_id": 53241, "sem_dados": False, "falha_comunicacao": True,
            "ultima_leitura": "2026-09-28 08:10:00", "strings_ativas": 0, "str_esp": 0, "sol_baixo": False}
    base.update(kw)
    return base


_INDICE = {"meses": {"2026-09": {"oss": [
    {"folio": 14711, "aberta": True, "tipos": ["Religamento"], "ini": "2026-09-26T15:30:00",
     "desc": "[THPN-CLN100] - Religamento do THPN-CLN100", "escopo": [{"nivel": "usina", "usina": "Ceilândia 1", "rotulo": "Usina inteira"}]},
    {"folio": 14710, "aberta": True, "tipos": ["Religamento"], "ini": "2026-09-26T15:40:00",
     "desc": "[THPN-CLN200] - Religamento do THPN-CLN200", "escopo": [{"nivel": "usina", "usina": "Ceilândia 2", "rotulo": "Usina inteira"}]},
    {"folio": 14605, "aberta": True, "tipos": ["Religamento"], "ini": "2026-09-25T08:45:00",
     "desc": "[Cabine 3] - Religamento da Cabine 3", "escopo": [{"nivel": "cabine", "usina": "Assis", "rotulo": "Cabine 3"}]},
    {"folio": 13000, "aberta": False, "tipos": ["Religamento"], "ini": "2026-09-10T10:00:00",
     "desc": "Religamento antigo", "escopo": [{"nivel": "usina", "usina": "Brodowski", "rotulo": "Usina inteira"}]},
]}}}


@pytest.fixture
def sinais(monkeypatch, freeze_now):
    freeze_now("2026-09-28 10:00:00")
    marcas, etm, liberadas = {}, {}, []
    monkeypatch.setattr(app, "_frac_disp_dados", lambda: _INDICE)
    monkeypatch.setattr(app, "_usinas_desligadas_marcas", lambda: marcas)
    monkeypatch.setattr(app, "_etm_leitura_por_pid", lambda: etm)
    monkeypatch.setattr(app, "_usina_desligada_liberar", lambda pid, usina: liberadas.append(str(pid)))
    monkeypatch.setattr(app, "_pv_relogio", {})
    return {"marcas": marcas, "etm": etm, "liberadas": liberadas}


def _desl(r):
    return (app._com_usina_desligada({"rows": [r]})["rows"][0]).get("desligada")


def test_calada_com_religamento_aberto_na_usina_inteira_e_desligada(sinais):
    d = _desl(_calada())
    assert d["por"] == "os" and d["folio"] == 14711 and d["desde"] == "2026-09-26T15:30:00"


def test_religamento_de_cabine_ou_ja_fechado_nao_desliga_a_usina(sinais):
    assert _desl(_calada(usina="Assis Chateaubriand  Skid 1 (79)", plant_id=18747433, sem_dados=True,
                         falha_comunicacao=False, ultima_leitura=None)) is None
    assert _desl(_calada(usina="Brodowski - Skid 1 (86)", plant_id=297381, sem_dados=True,
                         falha_comunicacao=False, ultima_leitura=None)) is None


def test_usina_gerando_com_religamento_aberto_segue_normal(sinais):
    """Ceilândia II em 28/09: OS 14710 aberta desde 26/09, usina gerando. OS aberta não desliga quem gera."""
    r = _calada(usina="Ceilandia II - Atena (92)", plant_id=22844, falha_comunicacao=False,
                ultima_leitura="2026-09-28 09:58:00", strings_ativas=60, str_esp=60)
    assert _desl(r) is None


def test_estacao_comunicando_com_inversores_calados_ha_mais_de_2h_e_desligada(sinais):
    """Canarana 1: estação às 09:48, inversores sem nada desde 23/09 15:54."""
    sinais["etm"]["23914"] = "2026-09-28 09:48"
    d = _desl(_calada(usina="Canarana 1", plant_id=23914, ultima_leitura="2026-09-23 15:54:00", strings_ativas=124, str_esp=124))
    assert d["por"] == "etm"


def test_estacao_viva_com_inversores_calados_ha_pouco_nao_basta(sinais):
    """Uma hora sem inversor com a estação viva pode ser o barramento — ainda é "sem comunicação"."""
    sinais["etm"]["23914"] = "2026-09-28 09:48"
    assert _desl(_calada(usina="Canarana 1", plant_id=23914, ultima_leitura="2026-09-28 09:00:00")) is None


def test_estacao_tambem_calada_nao_diz_nada(sinais):
    sinais["etm"]["18752351"] = "2026-09-28 00:21"
    assert _desl(_calada(usina="Santo Anastacio", plant_id=18752351, ultima_leitura="2026-09-27 20:04:00")) is None


def test_marcacao_do_analista_e_a_observacao_da_usina(sinais):
    sinais["marcas"]["60560"] = {"usina": "Mandaguaçu 1 (140)", "texto": "Desligada pela concessionária",
                                 "desde": "2026-09-27 23:48", "nick": "Levi", "ts": "2026-09-28 10:00:00"}
    d = _desl(_calada(usina="Mandaguaçu 1 (140)", plant_id=60560, ultima_leitura="2026-09-27 23:48:00"))
    assert d["por"] == "manual" and d["texto"] == "Desligada pela concessionária" and d["nick"] == "Levi"


def test_marcacao_vale_para_usina_sem_dado_nenhum(sinais):
    sinais["marcas"]["18746686"] = {"usina": "Ribeirão Cascalheiras", "texto": "Desligada", "nick": "Levi"}
    d = _desl({"usina": "Ribeirão Cascalheiras", "plant_id": 18746686, "sem_dados": True, "falha_comunicacao": False,
               "ultima_leitura": None, "strings_ativas": None})
    assert d["por"] == "manual"


def test_sem_motivo_nenhum_continua_sem_comunicacao(sinais):
    assert _desl(_calada(usina="Ribeirão Cascalheiras", plant_id=18746686, sem_dados=True, falha_comunicacao=False,
                         ultima_leitura=None)) is None


def test_marcacao_some_quando_a_usina_volta_a_gerar(sinais):
    sinais["marcas"]["60560"] = {"usina": "Mandaguaçu 1 (140)", "texto": "Desligada", "nick": "Levi"}
    r = _calada(usina="Mandaguaçu 1 (140)", plant_id=60560, falha_comunicacao=False,
                ultima_leitura="2026-09-28 09:58:00", strings_ativas=80, str_esp=84, pot_med=40.0)
    assert _desl(r) is None and sinais["liberadas"] == ["60560"]


def test_marcacao_fica_enquanto_a_usina_segue_parada(sinais):
    """Dado fresco, de dia, nada gerando: ainda desligada — a marca não sai (e a tela já diz "Usina desligada")."""
    sinais["marcas"]["60560"] = {"usina": "Mandaguaçu 1 (140)", "texto": "Desligada", "nick": "Levi"}
    r = _calada(usina="Mandaguaçu 1 (140)", plant_id=60560, falha_comunicacao=False,
                ultima_leitura="2026-09-28 09:58:00", strings_ativas=0, str_esp=84, pot_med=0.0)
    app._com_usina_desligada({"rows": [r]})
    assert sinais["liberadas"] == []


def test_nao_libera_de_noite(sinais):
    sinais["marcas"]["60560"] = {"usina": "Mandaguaçu 1 (140)", "texto": "Desligada", "nick": "Levi"}
    r = _calada(usina="Mandaguaçu 1 (140)", plant_id=60560, falha_comunicacao=False, sol_baixo=True,
                ultima_leitura="2026-09-28 09:58:00", strings_ativas=3, pot_med=1.0)
    app._com_usina_desligada({"rows": [r]})
    assert sinais["liberadas"] == []


def test_o_payload_em_cache_nao_e_mexido(sinais):
    r = _calada()
    p = {"rows": [r]}
    app._com_usina_desligada(p)
    assert "desligada" not in r and "desligada" not in p["rows"][0]


def test_tabela_de_strings_aplica_na_saida(sinais, monkeypatch):
    monkeypatch.setattr(app, "_servir_com_sol", lambda p, conta: p)
    monkeypatch.setattr(app, "_com_tickets_str", lambda p: p)
    out = app._servir_tabela_strings({"rows": [_calada()]}, None)
    assert out["rows"][0]["desligada"]["por"] == "os"


# ── Entrada: a desligada sai da conta de "sem comunicação" ──────────────────
def test_rollup_diz_desligada_e_nao_sem_comunicacao(sinais):
    r = dict(_calada(), desligada={"por": "os", "folio": 14711, "desde": "2026-09-26T15:30:00", "texto": "x"})
    assert app._macro_status(r) == "desligada"
    it = app._macro_item("API PV", r)
    assert it["status"] == "desligada" and it["strings_faltando"] == 0 and "desligada" in it["causa"].lower()
    assert app._macro_status(_calada()) == "sem_comm"


def test_card_da_entrada_nao_conta_strings_da_desligada(sinais):
    assert app._entrada_tr_strings_de({"status": "desligada", "diferenca": -48})["strings_faltando"] == 0


# ── rotas da marcação ─────────────────────────────────────────────────────────
@pytest.fixture
def estado(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "STATE_PATH", str(tmp_path / "ufv_state.json"))
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    app._usinas_desl_cache["ts"] = 0
    return app.app.test_client()


def test_marcar_exige_observacao(estado):
    r = estado.post("/api/state/usina-desligada", json={"pid": "60560", "usina": "Mandaguaçu 1 (140)", "texto": "  "})
    assert r.status_code == 400


def test_marcar_e_desmarcar(estado):
    r = estado.post("/api/state/usina-desligada", json={"pid": "60560", "usina": "Mandaguaçu 1 (140)", "fonte": "pv",
                                                         "texto": "Desligada pela concessionária", "desde": "2026-09-27T23:48",
                                                         "nick": "Levi"})
    assert r.status_code == 200 and r.get_json()["rec"]["texto"] == "Desligada pela concessionária"
    m = app._usinas_desligadas_marcas()
    assert m["60560"]["nick"] == "Levi" and m["60560"]["desde"] == "2026-09-27 23:48"
    assert estado.post("/api/state/usina-religada", json={"pid": "60560"}).status_code == 200
    assert "60560" not in app._usinas_desligadas_marcas()


# ── a tela ────────────────────────────────────────────────────────────────────
RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
MON = (RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")
ENT = (RAIZ / "docs" / "redesign" / "Entrada.html").read_text(encoding="utf-8")


def _trecho(ini, fim):
    i = MON.index(ini)
    return MON[i:MON.index(fim, i) + len(fim)]


def _status(r, velho=False):
    node = shutil.which("node")
    if not node:
        pytest.skip("node não instalado")
    js = "\n".join([_trecho("const pill=(bg,fg)=>", "\n"), _trecho("const pillOk=", "\n"), _trecho("const pillRed=", "\n"),
                    _trecho("const pillAmber=", "\n"), _trecho("const semGer=", "\n"),
                    _trecho("function _strStatus(", "/* fim _strStatus */"),
                    "process.stdout.write(JSON.stringify(_strStatus(%s,%s)[0]));" % (json.dumps(r), json.dumps(velho))])
    p = subprocess.run([node, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


_D = {"por": "os", "folio": 14711, "desde": "2026-09-26T15:30:00", "texto": "OS 14711 de religamento aberta"}


def test_tela_calada_com_motivo_diz_usina_desligada():
    assert _status(_calada(desligada=_D)) == "Usina desligada"
    assert _status(_calada(falha_comunicacao=False, ultima_leitura="2026-09-20 10:00:00", desligada=_D), velho=True) == "Usina desligada"
    assert _status({"sem_dados": True, "falha_comunicacao": False, "desligada": _D}) == "Usina desligada"


def test_tela_calada_sem_motivo_continua_sem_comunicacao():
    assert _status(_calada()) == "Usina sem comunicação"
    assert _status({"sem_dados": True, "falha_comunicacao": False, "sol_baixo": False}) == "Sem dados"


def test_a_linha_leva_a_observacao_e_o_drill_marca_e_desmarca():
    m = MON[MON.index("usinas=pv.rows.filter("):]
    m = m[:m.index("}).sort(")]
    assert "deslNote:" in m, "a observação da usina desligada vai na linha, como o aviso do inversor desligado"
    assert "${u.deslNote?" in MON
    assert "'/api/state/usina-desligada'" in MON and "'/api/state/usina-religada'" in MON
    assert "${RD.pv?_deslBarra(u):''}" in MON, "o marcar/desmarcar mora no drill da usina, antes dos inversores"


def test_entrada_diz_quantas_desligadas_ficaram_fora_da_conta():
    node = shutil.which("node")
    if not node:
        pytest.skip("node não instalado")
    i, j = ENT.index("function fmt(n)"), ENT.index("function strSub(")
    g1 = {"strings_faltando": 22, "strings_nao_rec": 0, "usinas_critico": 1, "usinas_sem_comm": 1, "usinas_desligadas": 5}
    g2 = {"strings_faltando": 0, "strings_nao_rec": 0, "usinas_critico": 0, "usinas_sem_comm": 0, "usinas_desligadas": 2}
    chamada = "process.stdout.write(JSON.stringify([strSub(%s,' · ',false), strSub(%s,' · ',false)]));" % (
        json.dumps(g1), json.dumps(g2))
    js = "\n".join([ENT[i:ENT.index("\n", i)], ENT[j:ENT.index("function strCls(", j)], chamada])
    p = subprocess.run([node, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    a, b = json.loads(p.stdout)
    assert a.endswith("fora da conta: 1 usina sem comunicação e 5 desligadas")
    assert b.endswith("fora da conta: 2 usinas desligadas")
