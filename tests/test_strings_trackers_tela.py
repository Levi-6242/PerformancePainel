# -*- coding: utf-8 -*-
"""Strings e trackers no desenho da Sala de controle (17/11/2026). Levi: "A parte de string e trackers vai passar por um
rework indo para todas as fontes da sala de controle, quero que avalie como está e deixe ao estilo sala de controle";
depois do mockup, "Sobe o strings e trackers". A tela nova mora no /painel/falhas (o endereço do mapa do Nexus) e a de
20/10 segue no mesmo endereço com ?antiga=1."""
import json
import os
import shutil
import subprocess

import pytest

import app

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = open(os.path.join(RAIZ, "plataforma", "templates", "strings_trackers.html"), encoding="utf-8").read()


@pytest.fixture
def cli():
    app.app.config["TESTING"] = True
    with app.app.test_client() as c:
        yield c


def test_a_tela_nova_abre_no_endereco_de_sempre_com_a_folha_da_sala(cli):
    r = cli.get("/painel/falhas")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "<title>Strings e trackers</title>" in html and "function montar(ent, fal)" in html
    assert "{% raw %}" not in html and "{{ sala_css" not in html                 # nada do Jinja vaza para a tela
    # a folha é a da Sala, tirada do template dela (uma só para as duas telas)
    sala = open(os.path.join(RAIZ, "plataforma", "templates", "sala_controle.html"), encoding="utf-8-sig").read()
    css = sala[sala.index("<style>") + 7:sala.index("</style>")]
    assert css.strip() and css in html.replace("\r\n", "\n") or css.replace("\r\n", "\n") in html.replace("\r\n", "\n")
    assert ".tela{display:grid" in html and "--fundo:#090d18" in html             # navy, nunca o lilás
    assert app._sala_css() is app._sala_css()                                     # relida só quando o arquivo muda


def test_a_tela_de_antes_segue_com_antiga_1(cli):
    html = cli.get("/painel/falhas?antiga=1").get_data(as_text=True)
    assert "DESC_VIS" in html and 'href="/painel/falhas?antiga=1"' in HTML
    assert "/painel/falhas/antiga" not in [r.rule for r in app.app.url_map.iter_rules()]      # sem rota nova: o mapa do Nexus não muda


def test_le_so_o_que_ja_existia_e_grava_pelas_rotas_de_antes():
    assert 'pega("/api/entrada/tempo-real", 90000), pega("/api/painel/falhas"' in HTML
    for rota in ("/api/painel/falhas/desconsiderar", "/api/painel/falhas/exportar", "/os/performance/criar", "/api/spv/usina/", "/api/pg/curva/"):
        assert rota in HTML
    # a ocorrência de string leva todas as chaves dela; quem só lê não vê os botões
    assert '{tipo: "strings", chaves: o.chaves, desconsiderar: tirar' in HTML and "const EU = window.gcEu || {}, PODE = !!EU.grava;" in HTML
    assert 'p.set("frase", ehS ? "recomposicao de string" : "verificacao de tracker parado")' in HTML
    assert "<emoji" not in HTML and "#191528" not in HTML.split("{{ sala_css|safe }}")[1].split("</style>")[0]


def test_o_montar_pendura_as_falhas_do_mes_nas_usinas_da_entrada():
    """A conta roda de verdade (no node): a Thopen se divide em banco e API PV, a usina casa pelo id e depois pelo nome,
    a ocorrência de string junta as strings do mesmo inversor e da mesma parada, e o tirado da conta não soma."""
    if not shutil.which("node"):
        pytest.skip("sem o node nesta máquina")
    js = HTML[HTML.index("const NOME = {"):HTML.index("function lado() {")]
    ent = {"cache_ts": "12:00:00", "grupos": [
        {"fonte_id": "thopen-db", "usinas": [{"usina": "Usina A", "plant_id": 1, "trk_parados": 2}]},
        {"fonte_id": "thopen-pv", "usinas": [{"usina": "Usina B", "plant_id": 10}, {"usina": "Usina B", "plant_id": 11}]},
        {"fonte_id": "salenergia", "usinas": [{"usina": "Sal 1", "plant_id": "s1"}]},
        {"fonte_id": "greenyellow", "usinas": [{"usina": "GY 1", "plant_id": "gy1", "trk_parados": 3}]}]}
    ep = lambda fonte, pid, cli_, usina, inv, s, ini, fim, perda: {  # noqa: E731
        "chave": f"{fonte}|{pid}|{inv}|{s}|{ini[:10]}", "fonte": fonte, "plant_id": str(pid), "cliente": cli_, "usina": usina, "inversor": inv,
        "string": s, "inicio": ini, "fim": fim, "dias": 3, "h_sol": 20.0, "perda_kwh": perda, "flags": ["aviso x"]}
    trk = lambda t, fim, perda, cron=False: {"chave": f"pg|1|{t}|2026-11-02", "fonte": "pg", "plant_id": "1", "cliente": "Thopen", "usina": "Usina A",  # noqa: E731
                                           "tracker": t, "inicio": "2026-11-02 08:00", "fim": fim, "h_sol": 9.0, "desvio_pico": 30.0, "perda_kwh": perda,
                                           "cronico": cron, "flags": ["em aberto", "kWp: típico"], "dias": [[1], [2]]}
    fal = {"mes": "2026-11", "meses": ["2026-10", "2026-11"], "gerado_em": "2026-11-17 14:32", "quente": True, "regua": {},
           "cobertura": [{"fonte": "pg", "plant_id": "1", "usina": "Usina A", "cliente": "Thopen", "dias_strings": 17, "dias_trackers": 17, "dias_comunicou": 17},
                         {"fonte": "pv", "plant_id": "11", "usina": "Usina B", "cliente": "Thopen", "dias_strings": 10, "dias_trackers": None, "dias_comunicou": 10},
                         {"fonte": "greenyellow", "plant_id": "gy1", "usina": "GY 1", "cliente": "Greenyellow", "dias_strings": 17, "dias_trackers": None, "dias_comunicou": 17}],
           "strings": {"episodios": [ep("pg", 1, "Thopen", "Usina A", "Inversor 1", "ST 01", "2026-11-05 07:00", None, 100.0),
                                     ep("pg", 1, "Thopen", "Usina A", "Inversor 1", "ST 02", "2026-11-05 07:00", None, 50.0),
                                     ep("pg", 1, "Thopen", "Usina A", "Inversor 2", "ST 09", "2026-11-03 09:00", "2026-11-04", 10.0),
                                     ep("pv", 11, "Thopen", "Usina B", "Inversor 1.1", "Ipv3", "2026-11-06 10:00", None, 7.0)],
                       "desconsideradas": [], "qualidade": {"x": 1}},
           "strings_os": [{"data_evento": "2026-11-05", "os": "18000", "status": "Concluída", "plant_id": "1", "inversor": "inversor 1", "usina": "Usina A"}],
           "trackers": {"rows": [trk("Tracker 1", None, 300.0, True), trk("Tracker 2", "2026-11-03", 40.0)],
                        "desconsideradas": [trk("Tracker 9", None, 999.0)], "qualidade": {}}}
    script = ("globalThis.window = {}; globalThis.document = {querySelector: () => null, getElementById: () => null};\n" + js +
              "\nconst d = montar(" + json.dumps(ent) + ", " + json.dumps(fal) + ");\n"
              "const u = k => US[k];\n"
              "console.log(JSON.stringify({a: [u('thopen-db|1').sAb, u('thopen-db|1').nS, u('thopen-db|1').perdaS, u('thopen-db|1').tAb, u('thopen-db|1').nT, u('thopen-db|1').perdaT],"
              " b10: [u('thopen-pv|10').naConta, u('thopen-pv|10').nS], b11: [u('thopen-pv|11').naConta, u('thopen-pv|11').sAb],"
              " sal: [semStr(u('salenergia|s1')), semTrk(u('salenergia|s1')), nuncaTrk(u('salenergia|s1'))], gy: [semStr(u('greenyellow|gy1')), semTrk(u('greenyellow|gy1'))],"
              " oc: d.s.map(o => [o.k, o.inv, o.strs.join('+'), o.chaves.length, o.perda, o.os && o.os[0]]), fora: d.t.filter(o => o.fora).map(o => o.trk),"
              " flags: d.t[0].flags, fontes: d.fontes.map(f => f.id)}));")
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    o = json.loads(r.stdout)
    assert o["a"] == [2, 2, 160.0, 1, 2, 340.0]                    # 2 strings paradas agora em 2 ocorrências; o Tracker 9 (fora) não soma
    assert o["b10"] == [False, 0] and o["b11"] == [True, 1]        # o episódio vai para a usina do id dele, não para a xará
    assert o["sal"] == [True, False, True] and o["gy"] == [False, True]   # a Sal fora das strings; os trackers da GY fora da conta
    assert o["oc"][0] == ["thopen-db|1", "Inversor 1", "ST 01+ST 02", 2, 150.0, "18000"]
    assert o["fora"] == ["Tracker 9"] and o["flags"] == [] and o["fontes"] == ["thopen-db", "thopen-pv", "salenergia", "greenyellow"]


def test_o_ciclo_das_falhas_grava_o_proprio_estado(tmp_path, monkeypatch):
    """18/11/2026: o pacote do mês parou em 17/11 14:32 e ninguém via por quê (o ciclo que falha só imprimia no log do
    worker). Cada volta grava quando começou, quando acabou e o erro; a rota devolve e a tela avisa."""
    monkeypatch.setattr(app, "_FALHAS_CICLO_PATH", str(tmp_path / "falhas_ciclo.json"))

    def falha():
        raise KeyError("usina sem kWp")
    monkeypatch.setattr(app, "_falhas_recalcular", falha)
    app._falhas_ciclo()                                                            # não levanta
    c = app._falhas_ler(app._FALHAS_CICLO_PATH)
    assert c["ok"] is False and c["erro"].startswith("KeyError") and "usina sem kWp" in c["rastro"] and c["inicio"] and c["fim"]
    monkeypatch.setattr(app, "_falhas_recalcular", lambda: None)
    app._falhas_ciclo()
    c = app._falhas_ler(app._FALHAS_CICLO_PATH)
    assert c["ok"] is True and c["erro"] is None and c["rastro"] is None and c["ultimo_ok"] == c["fim"]
    app.app.config["TESTING"] = True
    with app.app.test_client() as cli_:
        j = cli_.get("/api/painel/falhas/ciclo").get_json()
    assert j["ok"] and j["ciclo"]["ok"] is True
    assert 'pega("/api/painel/falhas/ciclo", 20000).catch(() => null)' in HTML and "o último recálculo FALHOU" in HTML
