# -*- coding: utf-8 -*-
"""À noite a tabela de strings não cobra esperadas (Levi, 22/09/2026).

O caso: print das 21:58 da aba Athon do Tempo Real, com a pergunta "os inversores desligados ainda
estão aparecendo como 'esperadas'". Às 22h TODO inversor está desligado — não há sol. A régua de
inversor desligado (`_inv_desligados_por_potencia`) é só de dia, de propósito: sem sol, zero é o
normal, não falha. Só que a TABELA não tinha noção nenhuma de noite: `temD` quer dizer "tem dados",
não "tem dia". Então, às 22h, cada usina saía "Sem geração" em vermelho, com a diferença inteira
cobrada (MAB100: −599) e a linha pulsando como déficit não acompanhado.

A regra nova usa a MESMA régua de sol da plataforma (`_macro_sol_baixo`, 10/09): fora de 07–18h
ninguém é julgado ao vivo; dentro, conta o sol abaixo de 8° no estado da usina. É a mesma janela da
régua de inversor desligado (`_macro_eh_dia`). Com duas réguas, às 18:20 de dezembro o inversor
desligado voltaria a contar como string faltando.

Sem sol, a linha diz "Sem sol", em neutro, sem esperadas nem déficit. Falha de comunicação continua
valendo, porque à noite é o que importa. O dado D-1 (padrão por inversor) também continua: ele não
depende do sol de agora.

A marca é posta na HORA DE SERVIR, não no build: o worker monta o payload a cada ciclo (medido em
22/09: até 15 min por volta) e, marcada lá, a usina montada às 17:55 seguiria "de dia" até a volta
seguinte.
"""
import json
import pathlib
import re
import shutil
import subprocess
import time
from datetime import datetime

import pytest

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
MON = (RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")
NODE = shutil.which("node")

NOITE = datetime(2026, 9, 22, 21, 58)      # a hora do print
MEIO_DIA = datetime(2026, 9, 22, 12, 0)


def _linha(usina, **kw):
    """Linha da tabela como os builders a devolvem, à noite: tudo em zero."""
    return dict({"usina": usina, "plant_id": usina, "qtd_inversores": 12, "strings_ativas": 0,
                 "str_esp": 599, "diferenca": -599, "sem_dados": False, "falha_comunicacao": False,
                 "ultima_leitura": "2026-09-22 21:55:00"}, **kw)


def _payload(*linhas, **summary):
    return {"rows": list(linhas),
            "summary": dict({"total_usinas": len(linhas), "total_strings": 0,
                             "alertas_strings": sum(1 for r in linhas if r["strings_ativas"] == 0)}, **summary),
            "cache_ts": "21:58:00"}


# ── a marca, na saída ─────────────────────────────────────────────────────────

def test_a_noite_toda_usina_sai_marcada_sem_sol():
    p = app._servir_com_sol(_payload(_linha("MAB100"), _linha("MRO100")), app._sem_geracao_padrao, agora=NOITE)
    assert [r["sol_baixo"] for r in p["rows"]] == [True, True]


def test_ao_meio_dia_nenhuma_usina_sai_marcada(monkeypatch):
    monkeypatch.setattr(app, "_estado_da_usina", lambda nome: "Piaui")
    p = app._servir_com_sol(_payload(_linha("MAB100", strings_ativas=500, diferenca=-99)),
                            app._sem_geracao_padrao, agora=MEIO_DIA)
    assert p["rows"][0]["sol_baixo"] is False


@pytest.mark.parametrize("hora", [(6, 30), (7, 20), (12, 0), (17, 25), (17, 50), (18, 5), (21, 58)])
@pytest.mark.parametrize("estado", ["Piaui", "Rio Grande do Sul", None])
def test_a_marca_e_a_regua_de_sol_do_macro(monkeypatch, hora, estado):
    """Uma régua só na plataforma. Se a tabela usasse outra, ela e a régua de inversor desligado (que
    passa por `_macro_eh_dia`) discordariam no fim da tarde: uma diria 'de dia, cobre', a outra 'de
    noite, não tire ninguém da conta' — e o inversor desligado viraria string faltando."""
    monkeypatch.setattr(app, "_estado_da_usina", lambda nome: estado)
    agora = datetime(2026, 9, 22, *hora)
    r = _linha("X")
    p = app._servir_com_sol(_payload(r), app._sem_geracao_padrao, agora=agora)
    assert p["rows"][0]["sol_baixo"] is app._macro_sol_baixo(r, agora)


def test_nao_mexe_no_payload_do_cache():
    """O payload em cache é do worker (mesma regra do `inv_padrao` no /api/data): marcá-lo no lugar
    gravaria a noite de hoje no snapshot, e a linha seguiria 'sem sol' quando o sol voltasse."""
    original = _payload(_linha("MAB100"))
    antes = json.dumps(original, sort_keys=True)
    app._servir_com_sol(original, app._sem_geracao_padrao, agora=NOITE)
    assert json.dumps(original, sort_keys=True) == antes


def test_payload_sem_linhas_passa_intacto():
    """Resposta 'carregando' e erro da fonte vêm sem linhas; nada a marcar, nada a quebrar."""
    vazio = {"rows": [], "summary": {}, "carregando": True}
    assert app._servir_com_sol(vazio, app._sem_geracao_padrao, agora=NOITE) == vazio


# ── o card "Sem geração" ──────────────────────────────────────────────────────

def test_a_noite_o_card_sem_geracao_nao_conta_ninguem():
    """Às 22h o card dizia "Sem geração: 10" em vermelho — a Athon inteira, por não ter sol."""
    p = app._servir_com_sol(_payload(_linha("MAB100"), _linha("MRO100")), app._sem_geracao_padrao, agora=NOITE)
    assert p["summary"]["alertas_strings"] == 0
    assert p["summary"]["sem_sol"] == 2


def test_de_dia_o_card_fica_identico_ao_do_builder(monkeypatch):
    """De dia nada muda, nem se o critério da rota discordasse do builder: com ninguém sem sol, o
    resumo sai byte a byte o que o builder montou."""
    monkeypatch.setattr(app, "_estado_da_usina", lambda nome: "Piaui")
    p0 = _payload(_linha("MAB100"), alertas_strings=7)
    p = app._servir_com_sol(p0, app._sem_geracao_padrao, agora=MEIO_DIA)
    assert p["summary"] == p0["summary"]


def test_no_fim_da_tarde_so_sai_do_card_quem_ja_esta_sem_sol(monkeypatch):
    """17:30 de setembro: o Piauí já está com o sol abaixo de 8°, o Rio Grande do Sul ainda não. A
    usina gaúcha zerada continua sendo alerta; a piauiense sai."""
    agora = datetime(2026, 9, 22, 17, 30)
    estados = {"PI-1": "Piaui", "RS-1": "Rio Grande do Sul"}
    monkeypatch.setattr(app, "_estado_da_usina", lambda nome: estados.get(nome))
    assert app._sol.sol_baixo("Piaui", agora) and not app._sol.sol_baixo("Rio Grande do Sul", agora), \
        "premissa do teste: às 17:30 de 22/09 o sol já baixou no PI e não no RS"
    p = app._servir_com_sol(_payload(_linha("PI-1"), _linha("RS-1")), app._sem_geracao_padrao, agora=agora)
    por = {r["usina"]: r["sol_baixo"] for r in p["rows"]}
    assert por == {"PI-1": True, "RS-1": False}
    assert p["summary"]["alertas_strings"] == 1 and p["summary"]["sem_sol"] == 1


def test_na_api_pv_a_lista_de_alertas_acompanha_o_card():
    """O /api/data leva também a LISTA das usinas contadas; as duas não podem discordar."""
    p0 = _payload(_linha("MAB100"), _linha("MRO100"))
    p0["alertas_strings_list"] = ["MAB100", "MRO100"]
    p = app._servir_com_sol(p0, app._sem_geracao_api_pv, agora=NOITE)
    assert p["alertas_strings_list"] == [] and p["summary"]["alertas_strings"] == 0


def test_o_criterio_de_cada_fonte_e_o_do_seu_builder():
    """O card de cada fonte tem o seu critério (a API PV não conta 'sem visão' nem foto histórica; o
    e-mail da 2C conta déficit). O ajuste da noite tira do card só quem o builder tinha contado."""
    assert app._sem_geracao_padrao(_linha("A")) is True
    assert app._sem_geracao_padrao(_linha("A", sem_dados=True)) is False
    assert app._sem_geracao_api_pv(_linha("A", sem_visao=True)) is False
    assert app._sem_geracao_api_pv(_linha("A", dado_historico=True)) is False
    assert app._sem_geracao_api_pv(_linha("A")) is True
    assert app._sem_geracao_2c_email(_linha("A", diferenca=-3, strings_ativas=5)) is True
    assert app._sem_geracao_2c_email(_linha("A", diferenca=0)) is False


# ── as rotas que a tabela chama ───────────────────────────────────────────────

def _rotas_da_tabela():
    """As rotas de strings que o Monitoramento chama, lidas do próprio HTML (o mapa `strings:{...}`)."""
    m = re.search(r"strings:\{([^}]*)\}", MON)
    assert m, "mapa de rotas de strings sumiu do Monitoramento"
    return sorted(set(re.findall(r"'(/api/[^']+)'", m.group(1))))


@pytest.fixture
def servidor(monkeypatch):
    """Cliente com o portão aberto (como no dev local) e TODA fonte com o cache fresco já montado —
    nenhuma rota pode sair à rede."""
    monkeypatch.setattr(app, "DASH_PASSWORD", "", raising=False)
    monkeypatch.setattr(app, "_macro_sol_baixo", lambda r, agora=None: True)     # noite, sem depender do relógio
    agora = time.time()

    def fresco(cache):
        monkeypatch.setitem(cache, "payload", _payload(_linha("MAB100"), _linha("MRO100")))
        monkeypatch.setitem(cache, "ts", agora)

    for c in (app._cache, app._semp_cache, app._alveslima_cache, app._2capi_cache, app._se_cache,
              app._si("gridco")["cache"], app._si("axis")["cache"]):
        fresco(c)
    monkeypatch.setattr(app, "_pg_get_snapshot", lambda force=False: ([_linha("MAB100"), _linha("MRO100")], {}))
    monkeypatch.setattr(app, "_owen_strings_rows", lambda force=False: [_linha("MAB100"), _linha("MRO100")])
    app.app.config["TESTING"] = True
    with app.app.test_client() as c:
        yield c


ROTAS = ["/api/data", "/api/pg/data", "/api/sunop/data", "/api/axis/data", "/api/solaredge/data",
         "/api/owen/strings/data", "/api/semp/data", "/api/alveslima/data", "/api/2capi/data"]


def test_toda_rota_de_strings_da_tabela_esta_coberta():
    """Fonte nova na tabela sem a marca de sol voltaria a pintar a noite de vermelho, sem ninguém ver."""
    assert _rotas_da_tabela() == sorted(ROTAS)


@pytest.mark.parametrize("rota", ROTAS)
def test_a_rota_entrega_a_marca_e_o_card_da_noite(servidor, rota):
    d = servidor.get(rota).get_json() or {}
    assert d.get("rows"), f"{rota} não devolveu linhas: {d}"
    assert all(r.get("sol_baixo") is True for r in d["rows"]), f"{rota} sem a marca de sol"
    assert d["summary"]["alertas_strings"] == 0, f"{rota}: o card 'Sem geração' ainda conta a noite"
    assert d["summary"]["sem_sol"] == len(d["rows"])


def test_a_rota_nao_grava_a_marca_no_cache(servidor):
    servidor.get("/api/sunop/data")
    assert all("sol_baixo" not in r for r in app._si("gridco")["cache"]["payload"]["rows"])


# ── a tela ────────────────────────────────────────────────────────────────────

def _trecho(ini, fim):
    i = MON.index(ini)
    return MON[i:MON.index(fim, i) + len(fim)]


def _status(r, velho=False):
    """Roda `_strStatus` no node com o MESMO código do HTML (arranjo de test_etm_alarme_e_do_agora)."""
    if not NODE:
        pytest.skip("node não instalado")
    js = "\n".join([
        _trecho("const pill=(bg,fg)=>", "\n"),
        _trecho("const pillOk=", "\n"), _trecho("const pillRed=", "\n"),
        _trecho("const pillAmber=", "\n"), _trecho("const semGer=", "\n"),
        _trecho("function _strStatus(", "/* fim _strStatus */"),
        "process.stdout.write(JSON.stringify(_strStatus(%s,%s)[0]));" % (json.dumps(r), json.dumps(velho)),
    ])
    p = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_a_noite_a_linha_diz_sem_sol_e_nao_sem_geracao():
    """O print das 21:58: MAB100 com 0 de 599 e −599, em vermelho."""
    assert _status(_linha("MAB100", sol_baixo=True)) == "Sem sol"


def test_a_noite_deficit_nao_vira_falha_de_string():
    assert _status(_linha("MAB100", sol_baixo=True, strings_ativas=12, diferenca=-587)) == "Sem sol"


def test_a_noite_falha_de_comunicacao_continua_valendo():
    """À noite, comunicação é o que importa — a Entrada diz isso desde o início."""
    assert _status(_linha("MAB100", sol_baixo=True, falha_comunicacao=True)) == "Usina sem comunicação"
    assert _status(_linha("MAB100", sol_baixo=True), velho=True) == "Usina sem comunicação"
    assert _status(_linha("MAB100", sol_baixo=True, sem_dados=True)) == "Sem dados"


def test_a_noite_o_padrao_do_dia_anterior_continua_valendo():
    """A régua de padrão por inversor compara o D-1: não depende do sol de agora."""
    assert _status(_linha("Barretos", sol_baixo=True, sem_visao=True, inv_padrao={"status": "critico"})) \
        == "Inversor fora do padrão"


def test_de_dia_nada_muda():
    assert _status(_linha("MAB100", sol_baixo=False)) == "Usina desligada"   # era "Sem geração" (23/09/2026)
    assert _status(_linha("MAB100", sol_baixo=False, strings_ativas=500, diferenca=-99)) == "Falha de string"
    assert _status(_linha("MAB100", sol_baixo=False, strings_ativas=514, diferenca=0, inv_desligados=5)) == "Inversor desligado"
    assert _status(_linha("MAB100", sol_baixo=False, strings_ativas=599, diferenca=0)) == "Normal"
    assert _status(_linha("MAB100", strings_ativas=599, diferenca=0)) == "Normal", "linha sem a marca = de dia"


def test_a_noite_as_colunas_nao_cobram():
    """Esperadas, diferença e disponibilidade saem em '—' sem sol, e a linha não pulsa: o déficit
    (`dif`) é anulado na origem, e é dele que saem a cor, a ordem e o pulso."""
    m = MON[MON.index("usinas=pv.rows.filter("):]
    m = m[:m.index("}).sort(")]
    assert re.search(r"dif=\(semSol\|\|semCom\)\?null:r\.diferenca", m), "o déficit da noite tem de ser anulado na origem"
    assert re.search(r"expected:\(r\.rampa\|\|r\.sem_visao\|\|semSol\)\?'—'", m), "esperadas sem sol devem sair em '—'"
    assert re.search(r"avail:\([^\n]*semSol[^\n]*\)\?[^\n]*:'—'", m), "disponibilidade sem sol deve sair em '—'"


def test_a_noite_o_card_sem_geracao_diz_sem_sol():
    """Com a fonte inteira sem sol, o card não mostra um '0' que parece 'tudo gerando'."""
    real = MON[MON.index("pvReal=true"):]            # o card de verdade, não o de demonstração do topo
    i = real.index("label:'Usinas desligadas'")          # o card "Sem geração" virou "Usinas desligadas" em 23/09
    card = real[real.rindex("{icon:", 0, i):real.index("}", i)]
    assert "_semSolTodas?'sem sol'" in card, f"o card da noite não diz 'sem sol': {card}"
    assert re.search(r"const _semSolTodas=sm\.sem_sol>0&&sm\.sem_sol>=pv\.rows\.length", real), \
        "'sem sol' no card só quando a fonte INTEIRA está sem sol (no fim da tarde o número já vem ajustado)"
