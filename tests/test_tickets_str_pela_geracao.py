# -*- coding: utf-8 -*-
"""Tickets de strings na aba Thopen API PV: Fracttal flexível e julgamento PELA GERAÇÃO (Levi, 24/09/2026).

Duas respostas do Levi à lista de dificuldades:
  - "o inversor de canarana 1 existe: THPN-CNN100-INVR1.1, assim como o de alto paraná: THPN-APR100-INVR1.10 (...)
    flexibilize melhor". Conferido no Fracttal: ALT100-INVR1.8, CTS100-INVR1.1 e MTS100-INVR6.2 existem SEM o
    prefixo do cliente; THPN-CNN100-INVR1.1, THPN-APR100-INVR1.10 e THPN-EBG100-INVR2.2 só COM ele. A Embu Guaçu é
    uma usina só no Fracttal (EBG100, "inversor 2.2 = inversor 2 da cabine 2") e duas na PV Operation.
  - "sei que tem usinas e inversores que não temos nenhuma visão de strings, nesse caso vamos nos basear pela
    geração!". O inversor sem visão é comparado com os PARES da mesma usina, por string esperada.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

import app


# ── Fracttal: o código com e sem o prefixo do cliente ──────────────────────────
def _fracttal(existem):
    chamadas = []

    def falso(caminho, **kw):
        chamadas.append(caminho)
        code = caminho.split("/", 1)[1]
        if code in existem:
            return {"data": [{"id": existem[code], "description": "Inversor  { %s }" % code}]}
        return {"data": []}
    return falso, chamadas


def test_codigo_sem_prefixo_que_nao_existe_tenta_com_o_do_cliente(monkeypatch):
    falso, chamadas = _fracttal({"THPN-CNN100-INVR1.1": 50193050})
    monkeypatch.setattr(app, "_frac_get", falso)
    monkeypatch.setattr(app, "_frac_code_cache", {})
    monkeypatch.setattr(app, "USINA_PREFIXO_FRAC", {"CNN100": "THPN"}, raising=False)
    a = app._frac_ativo("CNN100-INVR1.1")
    assert (a["id"], a["code"]) == (50193050, "THPN-CNN100-INVR1.1")
    assert chamadas == ["items/CNN100-INVR1.1", "items/THPN-CNN100-INVR1.1"]
    chamadas.clear()
    assert app._frac_ativo("CNN100-INVR1.1")["id"] == 50193050 and chamadas == [], "a segunda sai do cache"


def test_codigo_que_existe_sem_prefixo_nao_procura_outro(monkeypatch):
    """Altair: ALT100-INVR1.8 existe como está (e THPN-ALT100-INVR1.8 não)."""
    falso, chamadas = _fracttal({"ALT100-INVR1.8": 44142720})
    monkeypatch.setattr(app, "_frac_get", falso)
    monkeypatch.setattr(app, "_frac_code_cache", {})
    monkeypatch.setattr(app, "USINA_PREFIXO_FRAC", {"ALT100": "THPN"}, raising=False)
    assert app._frac_ativo("ALT100-INVR1.8")["code"] == "ALT100-INVR1.8" and chamadas == ["items/ALT100-INVR1.8"]


def test_usina_sem_prefixo_conhecido_tenta_o_da_thopen(monkeypatch):
    """Canarana: a aba de usinas tem código 0, então o prefixo dela não se sabe. THPN é o da Thopen."""
    falso, chamadas = _fracttal({"THPN-APR100-INVR1.10": 48709607})
    monkeypatch.setattr(app, "_frac_get", falso)
    monkeypatch.setattr(app, "_frac_code_cache", {})
    monkeypatch.setattr(app, "USINA_PREFIXO_FRAC", {}, raising=False)
    assert app._frac_ativo("APR100-INVR1.10")["id"] == 48709607


def test_codigo_que_ja_tem_prefixo_nao_ganha_outro(monkeypatch):
    falso, chamadas = _fracttal({})
    monkeypatch.setattr(app, "_frac_get", falso)
    monkeypatch.setattr(app, "_frac_code_cache", {})
    monkeypatch.setattr(app, "USINA_PREFIXO_FRAC", {"ALT100": "THPN"}, raising=False)
    assert app._frac_ativo("THPN-ALT100-INVR9.9") is None and chamadas == ["items/THPN-ALT100-INVR9.9"]


# ── a geração do inversor sem visão contra os pares (linha da tabela, API PV) ──
PID, NOME = 876543, "Usina Teste Sem Visao"


def _rec(inv_id, pac, correntes=(0.0,) * 12, ts="2026-09-24 11:00:00"):
    cj = {"Pac": pac, "Eday": 300.0, "Temp": 40.0}
    cj.update({f"Ipv{i + 1}": c for i, c in enumerate(correntes)})
    return {"idefinversor": inv_id, "tsleitura_new": ts, "conteudojson": json.dumps(cj)}


def _arma(monkeypatch, esperadas=(12, 12, 12, 12)):
    nomes = {i: "INV0%d" % i for i in (1, 2, 3, 4)}
    monkeypatch.setitem(app.ESPERADO, NOME, {"inv_esp": 4, "str_esp": sum(esperadas)})
    monkeypatch.setitem(app.ESPERADO_INV, NOME, {nomes[i]: e for i, e in zip((1, 2, 3, 4), esperadas) if e})
    monkeypatch.setitem(app.EQUIP_NAMES, NOME, {nomes[i]: "Inversor 1.%d" % i for i in (1, 2, 3, 4)})
    monkeypatch.setattr(app, "STRING_BOX", set(app.STRING_BOX) | {NOME})
    monkeypatch.setattr(app, "_combiner_strings", lambda pid, inv: None)      # String Box sem combiner exposta
    monkeypatch.setattr(app, "_os_atribuidas_map", lambda: {})
    monkeypatch.setattr(app, "_pv_dev_names", lambda pid, token: dict(nomes))
    monkeypatch.setattr(app, "_pv_token_for", lambda pid: "")
    return {"id": PID, "nome": NOME}


def _linha(monkeypatch, pacs, **kw):
    return app.build_summary(_arma(monkeypatch, **kw), [_rec(i + 1, p) for i, p in enumerate(pacs)])


def test_linha_sem_visao_leva_a_geracao_de_cada_inversor_contra_os_pares(monkeypatch, freeze_now):
    """4 inversores de 12 strings a 200/198/185/201 kW: o 1.3 gera 185/12 contra a mediana dos pares (200/12) = 92,5%."""
    freeze_now("2026-09-24 11:05:00")
    r = _linha(monkeypatch, (200.0, 198.0, 185.0, 201.0))
    assert r["sem_visao"] is True and sorted(r["inv_sem_visao"]) == ["1.1", "1.2", "1.3", "1.4"]
    assert r["ger_inv"]["1.3"] == {"r": 0.925, "esp": 12, "pac": 185.0}
    assert r["ger_inv"]["1.1"]["r"] == pytest.approx(200 / 198, abs=0.001)


def test_inversores_de_tamanhos_diferentes_comparam_por_string_esperada(monkeypatch, freeze_now):
    """O 1.4 tem 24 strings e gera o dobro: por string, é igual aos outros."""
    freeze_now("2026-09-24 11:05:00")
    r = _linha(monkeypatch, (200.0, 200.0, 200.0, 400.0), esperadas=(12, 12, 12, 24))
    assert r["ger_inv"]["1.4"]["r"] == 1.0 and r["ger_inv"]["1.4"]["esp"] == 24


def test_sem_o_esperado_de_todos_compara_a_potencia_crua(monkeypatch, freeze_now):
    freeze_now("2026-09-24 11:05:00")
    r = _linha(monkeypatch, (200.0, 198.0, 185.0, 201.0), esperadas=(12, 12, 0, 12))
    assert r["ger_inv"]["1.3"]["esp"] is None and r["ger_inv"]["1.3"]["r"] == 0.925


def test_de_noite_nao_ha_geracao_para_comparar(monkeypatch, freeze_now):
    freeze_now("2026-09-24 22:00:00")
    r = app.build_summary(_arma(monkeypatch), [_rec(i, 0.0, ts="2026-09-24 21:55:00") for i in (1, 2, 3, 4)])
    assert not r["ger_inv"]


# ── a régua: voltou, ainda abaixo, ou a geração não mostra ────────────────────
@pytest.mark.parametrize("g,n,esperado", [
    ({"r": 1.01, "esp": 12}, 1, True),     # 1 de 12 parada seria ~92%: gera 101% → voltou
    ({"r": 0.925, "esp": 12}, 1, False),   # 92,5%: é o que 1 string parada em 12 dá
    ({"r": 0.93, "esp": 12}, 2, True),     # 2 de 12 paradas seria ~83%; o limiar é o meio (91,7%) e 93% passou dele
    ({"r": 0.90, "esp": 12}, 2, False),
    ({"r": 0.99, "esp": None}, 1, True),   # sem o esperado do inversor: "gera como os pares" (97%)
    ({"r": 0.95, "esp": None}, 1, False),
])
def test_regua_pela_geracao(g, n, esperado):
    """Voltou = mais perto de 100% dos pares do que do que ele geraria com as N strings do ticket paradas."""
    assert app._tk_str_pela_geracao(g, n)[0] is esperado


def test_perda_pequena_demais_a_geracao_nao_mostra():
    """1 string em 24 = 4%: some na diferença normal entre inversores. Não chuta: diz que não dá."""
    normal, motivo = app._tk_str_pela_geracao({"r": 0.99, "esp": 24}, 1)
    assert normal is None and "1 string em 24" in motivo
    assert app._tk_str_pela_geracao(None, 1)[0] is None


# ── a coluna Tickets e o "para fechar" com a geração ──────────────────────────
@pytest.fixture
def tickets(monkeypatch):
    import test_tickets_strings as base
    return base._carregar(monkeypatch)


def _linha_tabela(**kw):
    return dict({"usina": "Altair", "plant_id": 1, "str_esp": 0, "strings_ativas": 0, "diferenca": 0,
                 "sol_baixo": False, "falha_comunicacao": False}, **kw)


def _ts(r):
    return app._com_tickets_str({"rows": [r], "summary": {}})["rows"][0]["tickets_str"]


def test_usina_sem_visao_fecha_pela_geracao(tickets):
    """Altair (fixture): ticket de 2 strings no Inversor 1.7, de 12 esperadas. Gerando 99% dos pares → para fechar."""
    ts = _ts(_linha_tabela(sem_visao=True, inv_sem_visao=["1.7"], ger_inv={"1.7": {"r": 0.99, "esp": 12, "pac": 190.0}}))
    t = ts["lista"][0]
    assert ts["para_fechar"] == 1 and t["normalizado"] is True
    assert t["pela_geracao"]["normal"] is True and t["pela_geracao"]["r"] == 0.99


def test_usina_sem_visao_abaixo_dos_pares_nao_fecha(tickets):
    ts = _ts(_linha_tabela(sem_visao=True, inv_sem_visao=["1.7"], ger_inv={"1.7": {"r": 0.84, "esp": 12, "pac": 160.0}}))
    assert ts["para_fechar"] == 0 and ts["lista"][0]["pela_geracao"]["normal"] is False


def test_inversor_sem_visao_em_usina_com_visao_vai_pela_geracao_dele(tickets):
    """Antes, o ticket de um inversor sem visão numa usina com as outras strings normais era dado por fechado pela
    conta das OUTRAS. Agora vale a geração dele: 84% dos pares com 2 de 12 paradas = não voltou."""
    ts = _ts(_linha_tabela(str_esp=100, strings_ativas=100, inv_sem_visao=["1.7"],
                           ger_inv={"1.7": {"r": 0.84, "esp": 12, "pac": 160.0}}))
    assert ts["para_fechar"] == 0 and ts["lista"][0]["normalizado"] is False


def test_sem_sol_nem_a_geracao_julga(tickets):
    ts = _ts(_linha_tabela(sem_visao=True, sol_baixo=True, inv_sem_visao=["1.7"],
                           ger_inv={"1.7": {"r": 0.99, "esp": 12, "pac": 190.0}}))
    assert ts["para_fechar"] == 0 and "sem sol" in ts["motivo"]


# ── o card no inversor: o estado pela geração ─────────────────────────────────
RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
MON = (RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")
NODE = shutil.which("node")


def _estado(t, inv):
    if not NODE:
        pytest.skip("node não instalado")
    i = MON.index("function _tkInvChave(")
    js = "\n".join([MON[MON.index("function _snum("):MON.index("\n", MON.index("function _snum("))],
                    MON[i:MON.index("/* fim _tkStr */", i)],
                    "process.stdout.write(JSON.stringify(_tkEstado(%s,%s)));" % (json.dumps(t), json.dumps(inv))])
    p = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_card_do_inversor_sem_visao_diz_o_que_a_geracao_mostra():
    t = {"qtd": 2, "strings": [], "pela_geracao": {"r": 0.99, "esp": 12, "normal": True, "motivo": ""}}
    e = _estado(t, {"semVisao": True, "strings": []})
    assert e["k"] == "voltou" and "99% dos pares" in e["txt"]
    t["pela_geracao"] = {"r": 0.84, "esp": 12, "normal": False, "motivo": ""}
    e = _estado(t, {"semVisao": True, "strings": []})
    assert e["k"] == "morta" and "84%" in e["txt"] and "~83%" in e["txt"], "com 2 de 12 paradas seria ~83%"
    t["pela_geracao"] = {"r": 0.99, "esp": 24, "normal": None, "motivo": "1 string em 24: a perda fica dentro da variação"}
    e = _estado(dict(t, qtd=1), {"semVisao": True, "strings": []})
    assert e["k"] == "mudo" and e["txt"].startswith("1 string em 24")
    assert _estado({"qtd": 1, "strings": []}, {"semVisao": True, "strings": []})["txt"] == "Inversor sem visão por string"


def test_coluna_mostra_para_fechar_mesmo_em_usina_sem_visao():
    """A coluna escondia o "para fechar" de toda usina sem visão; quem julga agora é o backend, pela geração."""
    assert "tkStr:_tkStrCel(r,semSol||semCom||!!r.rampa)," in MON


# ── a tabela da API PV não congela com a API lenta (24/09/2026) ────────────────
def test_primeira_passada_espera_90s_por_usina(monkeypatch):
    """24/09: a API PV respondia em ~48 s por usina e a 1ª passada desistia em 45 s — tudo caía na 3ª, SEQUENCIAL (até
    60 s cada, 115 usinas ≈ 2 h de ciclo), e a aba ficou com o dado das 09:08 até depois do meio-dia."""
    vistos = []

    def falso(token, plant, timeout=45):
        vistos.append(timeout)
        return {"usina": plant["nome"], "plant_id": plant["id"], "sem_dados": False}
    monkeypatch.setattr(app, "get_token", lambda: "tok")
    monkeypatch.setattr(app, "get_plants", lambda token: [{"id": i, "nome": "U%d" % i} for i in range(3)])
    monkeypatch.setattr(app, "_pv_plantas_da_fonte", lambda plantas, fonte: plantas)
    monkeypatch.setattr(app, "process_plant", falso)
    assert len(app.fetch_all()) == 3 and vistos == [90, 90, 90]
