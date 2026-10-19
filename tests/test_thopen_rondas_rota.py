# -*- coding: utf-8 -*-
"""As rotas da janela das rondas (rodada 3, 09/10/2026) e da contestação (rodada 4): lista do mês sem Fracttal, detalhe
e foto só de OS de ronda do 5080, Fracttal fora não derruba a ronda, contestação com limite, um canal por item (ronda →
Zeladoria) e sem fingir envio quando o canal não está configurado. Dados, Fracttal e Teams falsos."""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "thopen"))
import dashboard_thopen as dth  # noqa: E402
import contestacao  # noqa: E402
import fonte_operacao as fo  # noqa: E402
import fotos_ronda  # noqa: E402

R = {"os": "15176", "usina_id": 86, "dia": "2026-10-02", "hora_inicio": "10:13", "hora_fim": "11:07", "n_fotos": 2,
     "unidade": "Guaratingueta 5", "itens": [["Sujidade dos módulos", "2"]], "achados": {}, "sujidade": 2,
     "vegetacao": None}
DADOS = {k: [] for k, _ in fo.ABAS.values()}
DADOS.update(rondas_com_os=[R, dict(R, os="99999", usina_id=5)],
             de_para=[{"usina_id": 86, "chave_externa": "Guaratinguetá V"},
                      {"usina_id": 1, "chave_externa": "Altair"}])
GV = "/api/t/rondas?usina=Guaratinguet%C3%A1%20V&ano=2026&mes="
CORPO = {"usina": "Guaratinguetá V", "ano": 2026, "mes": 10, "dia_ini": 4, "dia_fim": 4, "itens": ["disponibilidade"],
         "nome": "Ana", "contato": "ana@x.com.br", "mensagem": "Oi?", "tela": {"disp": "95,8%"}}


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.delenv("THOPEN_RONDAS", raising=False)
    monkeypatch.setattr(fo, "_estado", {"dados": DADOS, "ts": time.time(), "erro": None, "carregando": False,
                                        "proxima": 0.0, "disco_lido": True})
    monkeypatch.setattr(fotos_ronda, "anexos",
                        lambda os_: [{"desc": "Sujidade dos módulos — 2", "url": "u", "mime": "image/jpeg"}])
    monkeypatch.setattr(fotos_ronda, "miniatura", lambda os_, i: (b"mini", "image/jpeg"))
    monkeypatch.setattr(contestacao, "url", lambda k: "https://exemplo/" + k)
    monkeypatch.setattr(dth, "_LIMITE", contestacao.Limite())
    monkeypatch.setattr(dth, "_usinas_disponiveis", lambda: ["Guaratinguetá V", "Altair"])
    enviados = []
    monkeypatch.setattr(contestacao, "enviar", lambda p, d: enviados.append((d, p)))
    import contestacao_banco
    # nada vai ao banco de verdade: o banco falso guarda o que a rota gravaria (desde 19/10/2026 é o destino de todo item)
    gravadas = []
    monkeypatch.setattr(contestacao_banco, "configurado", lambda: True)
    monkeypatch.setattr(contestacao_banco, "registrar_contestacao", lambda *a: gravadas.append(a) or 1)
    c = dth.app.test_client()
    c.enviados, c.gravadas = enviados, gravadas
    return c


def test_lista_do_mes(cli):
    r = cli.get(GV + "10").get_json()
    assert r["disponivel"] and "duvida" not in r and [x["os"] for x in r["rondas"]] == ["15176"]
    assert r["rondas"][0]["inicio"] == "07:13"
    assert cli.get("/api/t/rondas?usina=x&ano=2026&mes=13").status_code == 400
    assert cli.get(GV + "9").get_json()["rondas"] == []


def test_detalhe_e_foto_so_de_os_permitida(cli):
    d = cli.get("/api/t/ronda/15176").get_json()
    assert d["itens"][0]["fotos"] == [0] and d["fotos_erro"] is None and d["itens"][0]["nivel"] == 2
    f = cli.get("/api/t/ronda/15176/foto/0?mini=1")
    assert f.status_code == 200 and f.data == b"mini" and "private" in f.headers["Cache-Control"]
    assert cli.get("/api/t/ronda/99999").status_code == 404           # usina fora do 5080 (outro cliente)
    assert cli.get("/api/t/ronda/12345/foto/0").status_code == 404     # OS que não é ronda do 5080


def test_fracttal_fora_mostra_a_ronda_e_avisa(cli, monkeypatch):
    def ocupado(os_):
        raise fotos_ronda.Ocupado("429")
    monkeypatch.setattr(fotos_ronda, "anexos", ocupado)
    d = cli.get("/api/t/ronda/15176").get_json()
    assert d["itens"] and d["fotos"] == [] and "1 minuto" in d["fotos_erro"]

    def sem(os_):
        raise fotos_ronda.SemCredencial("x")
    monkeypatch.setattr(fotos_ronda, "anexos", sem)
    assert "não estão disponíveis" in cli.get("/api/t/ronda/15176").get_json()["fotos_erro"]


def test_contestacao_vai_ao_canal_de_cada_item_com_limite(cli):
    # a disponibilidade vai para o COS (Levi, 15/10/2026: "Disponibilidade e desligamento vão para o setor de COS")
    assert cli.post("/api/t/contestar", json=CORPO).get_json() == {"ok": True, "destinos": ["COS"]}
    (destino, card), = cli.enviados
    assert destino == "https://exemplo/cos" and "Guaratinguetá V" in str(card) and "04/10/2026" in str(card)
    r = cli.post("/api/t/contestar", json=dict(CORPO, itens=["ronda", "string"], dia_fim=6)).get_json()
    assert r == {"ok": True, "destinos": ["Performance", "Zeladoria"]}
    assert [d for d, _ in cli.enviados[1:]] == ["https://exemplo/performance", "https://exemplo/zeladoria"]
    assert "04 a 06/10/2026" in str(cli.enviados[1][1])
    h = {"CF-Connecting-IP": "1.2.3.4"}
    assert [cli.post("/api/t/contestar", json=CORPO, headers=h).status_code for _ in range(4)] == [200, 200, 200, 429]


def test_contestacao_so_de_usina_do_painel_dia_valido_e_de_outubro_em_diante(cli):
    assert cli.post("/api/t/contestar", json=dict(CORPO, usina="Outra")).status_code == 404
    assert cli.post("/api/t/contestar", json=dict(CORPO, mes=9)).status_code == 400
    assert cli.post("/api/t/contestar", json=dict(CORPO, dia_ini=5, dia_fim=4)).status_code == 400
    assert cli.post("/api/t/contestar", json=dict(CORPO, dia_fim=32)).status_code == 400
    assert cli.post("/api/t/contestar", json=dict(CORPO, contato="x")).status_code == 400
    assert cli.post("/api/t/contestar", json=dict(CORPO, itens=[])).status_code == 400
    assert cli.enviados == []


def test_isca_finge_que_foi_e_nao_avisa(cli):
    assert cli.post("/api/t/contestar", json=dict(CORPO, site="x")).get_json()["ok"] is True
    assert cli.enviados == []


def test_teams_fora_com_o_banco_gravado_vale_pelo_nexus(cli, monkeypatch):
    # 19/10/2026 (Levi: "vai direto para contestações do Nexus e a gente resolve lá, esquece teams"): o registro é o
    # banco, que o Nexus mostra; o Teams que recusou não derruba a contestação, e a linha diz que ele não recebeu
    def enviar(p, d):
        if d.endswith("zeladoria"):
            raise RuntimeError("o Teams respondeu 400")
        cli.enviados.append((d, p))
    monkeypatch.setattr(contestacao, "enviar", enviar)
    r = cli.post("/api/t/contestar", json=dict(CORPO, itens=["ronda", "tracker"]))
    assert r.status_code == 200 and r.get_json() == {"ok": True, "destinos": ["Performance", "Zeladoria"]}
    (*_, avisos), = cli.gravadas
    assert avisos == {"performance": True, "zeladoria": False}


def test_banco_fora_diz_o_que_foi_e_o_que_nao_foi(cli, monkeypatch):
    # o banco recusou: só vale o setor que o Teams recebeu; o resto não foi a lugar nenhum e o cliente fica sabendo
    import contestacao_banco

    def falha(*a):
        raise contestacao_banco.GravacaoErro("a API respondeu 500")
    monkeypatch.setattr(contestacao_banco, "registrar_contestacao", falha)
    monkeypatch.setattr(contestacao, "url", lambda k: "https://exemplo/p" if k == "performance" else "")
    r = cli.post("/api/t/contestar", json=dict(CORPO, itens=["tracker", "disponibilidade"]))
    assert r.status_code == 502 and r.get_json()["destinos"] == ["Performance"] and "COS" in r.get_json()["erro"]


def test_cos_sem_teams_vai_ao_nexus(cli, monkeypatch):
    # o caso que motivou (19/10/2026): sem o fluxo do Teams do COS, Disponibilidade e Desligamento não marcavam
    monkeypatch.setattr(contestacao, "url", lambda k: "" if k == "cos" else "https://exemplo/" + k)
    r = cli.post("/api/t/contestar", json=dict(CORPO, itens=["disponibilidade", "desligamento"]))
    assert r.status_code == 200 and r.get_json() == {"ok": True, "destinos": ["COS"]} and cli.enviados == []
    (d, usina, usina_id, ano, mes, ini, fim, avisos), = cli.gravadas
    # None = o setor não tem fluxo do Teams (o Nexus mostra "só no Nexus", não "o Teams recusou")
    assert (usina, usina_id, ini) == ("Guaratinguetá V", 86, 4) and avisos == {"cos": None}
    assert d["itens"] == ["disponibilidade", "desligamento"]
    o = cli.get("/api/t/operacao?usina=Guaratinguet%C3%A1%20V&ano=2026&mes=10").get_json()
    assert o["contestar"] == {"performance": True, "cos": True, "zeladoria": True}


def test_sem_banco_e_sem_teams_nao_finge(cli, monkeypatch):
    import contestacao_banco
    monkeypatch.setattr(contestacao_banco, "configurado", lambda: False)
    monkeypatch.setattr(contestacao, "url", lambda k: "https://exemplo/p" if k == "performance" else "")
    r = cli.post("/api/t/contestar", json=dict(CORPO, itens=["ronda"]))
    assert r.status_code == 503 and cli.enviados == [] and cli.gravadas == []
    monkeypatch.setattr(contestacao.fonte_api, "segredo", lambda n: "x" if n == "THOPEN_TEAMS_PERFORMANCE" else "")
    o = cli.get("/api/t/operacao?usina=Guaratinguet%C3%A1%20V&ano=2026&mes=10").get_json()
    assert o["contestar"] == {"performance": True, "cos": False, "zeladoria": False}


def test_chave_desliga_tudo(cli, monkeypatch):
    monkeypatch.setenv("THOPEN_RONDAS", "0")
    assert cli.get(GV + "10").get_json()["motivo"] == "desligado"
    assert cli.get("/api/t/ronda/15176").status_code == 404
    assert cli.get("/api/t/ronda/15176/foto/0").status_code == 404
    assert cli.get("/api/t/ronda/15176/foto/0?mini=1").status_code == 404


def test_contestacao_vai_ao_banco_para_o_nexus_com_o_que_o_teams_recebeu(cli, monkeypatch):
    # rodada 5 (Levi, 13/10): "contestação ligada ao Nexus" — uma linha por setor, com o setor que o Teams recebeu
    def enviar(p, d):
        if d.endswith("zeladoria"):
            raise RuntimeError("o Teams respondeu 400")
    monkeypatch.setattr(contestacao, "enviar", enviar)
    cli.post("/api/t/contestar", json=dict(CORPO, itens=["geracao", "ronda"]))
    (d, usina, usina_id, ano, mes, ini, fim, avisos), = cli.gravadas
    assert (usina, usina_id, ano, mes, ini, fim) == ("Guaratinguetá V", 86, 2026, 10, 4, 4)
    assert avisos == {"performance": True, "zeladoria": False} and d["itens"] == ["geracao", "ronda"]
    cli.gravadas.clear()
    assert cli.post("/api/t/contestar", json=dict(CORPO, site="x")).get_json()["ok"] and cli.gravadas == []   # isca não grava
