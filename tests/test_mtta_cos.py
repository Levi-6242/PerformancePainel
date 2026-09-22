# -*- coding: utf-8 -*-
"""Acompanhamento COS — MTTA: tempo do EVENTO até a OS aparecer no Fracttal, por operador (22/09/2026).

A régua saiu da varredura do histórico inteiro do Fracttal (34.832 tarefas, 4.643 OSs de Religamento,
Religamento Remoto e Corretiva Emergencial desde 08/12/2025), e cada teste aqui é uma armadilha que
aquela varredura mostrou de verdade:

- 89 OSs com o evento 0,1–5 s antes da criação: o app gravou "agora" (o `create_os_rpc` cai no
  `datetime.now()` sem `event_date`). Contadas, dariam ao operador "0 min" que não é medição — a mediana
  de um deles cairia de 52 para 40 min no histórico.
- 21 OSs com o evento DEPOIS da criação: OS programada, não reconhecimento.
- O Fracttal grafa o mesmo operador com e sem espaço ("LuelySantos" / "Luely  Santos"), e várias contas
  vêm sem `code_create_by` — a chave é o nome sem espaços.
- 17 OSs da planta de teste (TESTE - PA) e 326 canceladas saem da conta.
- Lote (mesmo evento em vários ativos) e rajada (várias ocorrências registradas juntas no fim do turno)
  são marcados, não descartados: a tela deixa contar o lote uma vez e mostra a rajada por operador.

Os nomes de pessoa aqui são fictícios.
"""
import json
import pathlib

import pytest

import app
import disponibilidade
import mtta


def linha(folio, evento, criacao, *, tipo="Religamento Remoto", st=2, por="Ana Souza", code="CPP100-CABN6",
          grupo="Athon - Capitão Poço 1 - PA", pai="// Athon/ Athon - Capitão Poço 1 - PA/ ", tarefa=None):
    return {"wo_folio": str(folio), "id_work_orders_tasks": tarefa or int(folio) * 10, "event_date": evento,
            "creation_date": criacao, "tasks_log_task_type_main": tipo, "id_status_work_order": st,
            "created_by": por, "code": code, "groups_1_description": grupo, "parent_description": pai,
            "items_log_description": "Cabine 6  Capitão Poço  Pará Brasil { %s }" % code}


def unica(linhas):
    r = mtta.montar(linhas)
    assert len(r["oss"]) == 1, r["oss"]
    return r["oss"][0]


# ── a conta ────────────────────────────────────────────────────────────────────────────────
def test_reacao_e_a_criacao_da_os_menos_o_evento_em_minutos():
    # OS real 14364 (22/09): evento 15:26 de Brasília, OS criada às 15:46:24
    o = unica([linha(14364, "2026-09-22T18:26:00+00:00", "2026-09-22T18:46:24.220149+00:00")])
    assert round(o["mtta"], 2) == 20.4
    assert o["cls"] == "ok"


def test_so_entram_religamento_religamento_remoto_e_corretiva_emergencial():
    r = mtta.montar([
        linha(1, "2026-09-01T10:00:00+00:00", "2026-09-01T10:30:00+00:00", tipo="Preventiva"),
        linha(2, "2026-09-01T10:00:00+00:00", "2026-09-01T10:30:00+00:00", tipo="Inspeção"),
        linha(3, "2026-09-01T10:00:00+00:00", "2026-09-01T10:30:00+00:00", tipo="  corretiva   emergencial "),
        linha(4, "2026-09-01T10:00:00+00:00", "2026-09-01T10:30:00+00:00", tipo="Religamento"),
    ])
    assert sorted(o["folio"] for o in r["oss"]) == [3, 4]
    assert {o["tipo"] for o in r["oss"]} == {"Corretiva Emergencial", "Religamento"}


def test_tipos_sao_os_mesmos_da_disponibilidade():
    # a régua de tipo já morou em 3 cópias no gêmeo; aqui ela é a da Disponibilidade, importada
    assert mtta.TIPOS == disponibilidade.TIPOS_ALVO


# ── o que sai da conta ─────────────────────────────────────────────────────────────────────
def test_cancelada_sai_da_conta_e_e_contada_a_parte():
    r = mtta.montar([linha(1, "2026-09-01T10:00:00+00:00", "2026-09-01T10:30:00+00:00", st=4),
                     linha(2, "2026-09-01T10:00:00+00:00", "2026-09-01T10:30:00+00:00")])
    assert [o["folio"] for o in r["oss"]] == [2]
    assert r["canceladas"] == 1


@pytest.mark.parametrize("code,pai", [("TESTE100-CABN1", "// TESTE - PA/ "), ("THPN-TESTE", "// TESTE - PA/ "),
                                      ("TESTE100-INVR1.2", "// TESTE - PA/ Cabine 1/ SKID 1/ QGBT 1/ ")])
def test_planta_de_teste_sai_da_conta(code, pai):
    r = mtta.montar([linha(1, "2026-06-12T08:00:00+00:00", "2026-06-26T09:06:00+00:00", code=code, grupo="", pai=pai)])
    assert r["oss"] == [] and r["teste"] == 1


def test_evento_depois_da_criacao_nao_e_reconhecimento():
    o = unica([linha(1, "2026-09-16T17:00:00+00:00", "2026-09-03T10:00:00+00:00")])
    assert o["cls"] == "evento_depois"


def test_evento_carimbado_no_segundo_da_criacao_nao_e_medicao():
    # OS 13195 (08/09): evento 13:17:39.151Z, criação 13:17:39.260Z — o app gravou "agora"
    o = unica([linha(13195, "2026-09-08T13:17:39.151+00:00", "2026-09-08T13:17:39.260147+00:00")])
    assert o["cls"] == "evento_eh_criacao"


def test_doze_segundos_ja_e_medicao():
    o = unica([linha(1, "2026-09-08T13:17:27+00:00", "2026-09-08T13:17:39+00:00")])
    assert o["cls"] == "ok"


# ── quem, onde e quando ────────────────────────────────────────────────────────────────────
def test_operador_com_e_sem_espaco_no_nome_e_a_mesma_pessoa():
    r = mtta.montar([linha(1, "2026-09-01T10:00:00+00:00", "2026-09-01T10:30:00+00:00", por="AnaSouza"),
                     linha(2, "2026-09-02T10:00:00+00:00", "2026-09-02T10:30:00+00:00", por="Ana  Souza"),
                     linha(3, "2026-09-03T10:00:00+00:00", "2026-09-03T10:30:00+00:00", por="Ana Souza")])
    assert {o["nome"] for o in r["oss"]} == {"Ana Souza"}      # mostra a grafia com espaço


def test_os_com_varias_tarefas_usa_o_evento_mais_antigo():
    r = mtta.montar([linha(7, "2026-09-01T10:20:00+00:00", "2026-09-01T11:00:00+00:00", tarefa=71),
                     linha(7, "2026-09-01T10:00:00+00:00", "2026-09-01T11:00:00+00:00", tarefa=72)])
    assert len(r["oss"]) == 1 and r["oss"][0]["mtta"] == 60


def test_usina_vem_do_caminho_do_ativo_quando_o_grupo_vem_vazio():
    # JCD100-CABN1: groups_1_description vazio, o nome da usina só está no caminho
    o = unica([linha(1, "2026-09-01T10:00:00+00:00", "2026-09-01T10:30:00+00:00", code="JCD100-CABN1", grupo="",
                     pai="// Athon/ Athon - Jacundá 1 - PA/ ")])
    assert o["usina"] == "Jacundá 1" and o["cliente"] == "Athon"


def test_horas_do_evento_e_da_criacao_sao_de_brasilia():
    # evento 02:30Z = 23:30 da véspera aqui; criação 11:00Z = 08:00
    o = unica([linha(1, "2026-09-02T02:30:00+00:00", "2026-09-02T11:00:00+00:00")])
    assert o["h_ev"] == 23 and o["h_cri"] == 8


# ── lote e rajada ──────────────────────────────────────────────────────────────────────────
def test_lote_mesmo_evento_em_varios_ativos_marca_so_a_primeira_os():
    ev = "2026-09-01T10:00:00+00:00"
    r = mtta.montar([linha(1, ev, "2026-09-01T10:31:00+00:00", code="CPP100-CABN1"),
                     linha(2, ev, "2026-09-01T10:30:00+00:00", code="CPP100-CABN2"),
                     linha(3, ev, "2026-09-01T10:32:00+00:00", code="CPP100-CABN3")])
    por = {o["folio"]: o for o in r["oss"]}
    assert {o["lote_n"] for o in r["oss"]} == {3}
    assert [f for f, o in sorted(por.items()) if o["lote_1o"]] == [2]      # a criada primeiro


def test_rajada_tres_ocorrencias_diferentes_registradas_em_trinta_minutos():
    r = mtta.montar([linha(1, "2026-09-01T04:00:00+00:00", "2026-09-01T08:00:00+00:00"),
                     linha(2, "2026-09-01T05:10:00+00:00", "2026-09-01T08:05:00+00:00", code="CPP100-CABN2"),
                     linha(3, "2026-09-01T06:20:00+00:00", "2026-09-01T08:10:00+00:00", code="CPP100-CABN3"),
                     linha(4, "2026-09-01T09:00:00+00:00", "2026-09-01T09:40:00+00:00")])   # 1h30 depois: fora
    raj = {o["folio"]: o["rajada"] for o in r["oss"]}
    assert raj == {1: True, 2: True, 3: True, 4: False}


def test_lote_nao_mistura_os_que_esta_fora_da_conta():
    # achado na comparação com o protótipo (22/09): se a 1ª OS do lote tem o evento carimbado na
    # criação (fora da conta), "lote conta 1 vez" apagaria o evento inteiro — nenhuma OS da conta
    # ficaria marcada como a 1ª do lote
    ev = "2026-09-08T13:17:00+00:00"
    r = mtta.montar([linha(1, "2026-09-08T13:17:39.151+00:00", "2026-09-08T13:17:39.260+00:00", code="CPP100-CABN1"),
                     linha(2, ev, "2026-09-08T13:40:00+00:00", code="CPP100-CABN2"),
                     linha(3, ev, "2026-09-08T13:41:00+00:00", code="CPP100-CABN3")])
    por = {o["folio"]: o for o in r["oss"]}
    assert por[1]["cls"] == "evento_eh_criacao"
    assert (por[2]["lote_n"], por[2]["lote_1o"], por[3]["lote_1o"]) == (2, True, False)


def test_site_sem_cliente_no_nome_vira_o_proprio_cliente():
    # "Grid Co." = ativo genérico de usina de terceiros: não tem " - " no nome
    o = unica([linha(9037, "2026-07-06T18:00:00+00:00", "2026-07-06T18:06:00+00:00", code="GRID",
                     grupo="Grid Co.", pai="// Grid Co./ ")])
    assert o["cliente"] == "Grid Co." and o["usina"] == "Grid Co."


def test_lote_de_um_evento_so_nao_e_rajada():
    ev = "2026-09-01T10:00:00+00:00"
    r = mtta.montar([linha(i, ev, "2026-09-01T10:30:%02d+00:00" % i, code="CPP100-CABN%d" % i) for i in (1, 2, 3, 4)])
    assert not any(o["rajada"] for o in r["oss"])


# ── o pacote da tela e a base acumulada ────────────────────────────────────────────────────
def test_payload_compacto_referencia_as_listas_por_indice():
    p = mtta.payload([linha(1, "2026-09-01T10:00:00+00:00", "2026-09-01T10:30:00+00:00", por="Ana Souza"),
                      linha(2, "2026-09-01T12:00:00+00:00", "2026-09-01T12:05:00+00:00", por="Bruno Lima", tipo="Religamento"),
                      linha(3, "2026-09-01T12:00:00+00:00", "2026-09-01T12:05:00+00:00", st=4)],
                     varrido_em="2026-09-22 16:02")
    assert p["varrido_em"] == "2026-09-22 16:02" and p["total_tarefas"] == 3 and p["canceladas"] == 1
    assert p["tipos"] == ["Religamento Remoto", "Religamento", "Corretiva Emergencial"]
    assert json.loads(json.dumps(p)) == p                                  # vai por JSON sem perda
    linhas = {r[0]: r for r in p["os"]}
    folio, iop, itipo, ius, ev_s, reacao, cls = linhas[2][:7]
    assert p["ops"][iop] == "Bruno Lima" and p["tipos"][itipo] == "Religamento"
    assert p["usinas"][ius] == "Capitão Poço 1" and reacao == 5 and cls == 0
    from datetime import datetime, timezone
    assert ev_s == int(datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc).timestamp())


def test_fundir_troca_so_a_janela_recente_da_base():
    velha = linha(1, "2026-08-01T10:00:00+00:00", "2026-08-01T10:30:00+00:00", tarefa=10)
    recente = linha(2, "2026-09-20T10:00:00+00:00", "2026-09-20T10:30:00+00:00", tarefa=20)
    sumiu = linha(3, "2026-09-21T10:00:00+00:00", "2026-09-21T10:30:00+00:00", tarefa=30)   # apagada no Fracttal
    cancelada_agora = dict(recente, id_status_work_order=4)
    nova = linha(4, "2026-09-22T10:00:00+00:00", "2026-09-22T10:30:00+00:00", tarefa=40)
    base = mtta.fundir([velha, recente, sumiu], [cancelada_agora, nova], desde="2026-09-12T00:00:00+00:00")
    por = {w["id_work_orders_tasks"]: w for w in base}
    assert set(por) == {10, 20, 40}
    assert por[20]["id_status_work_order"] == 4                            # a versão fresca vence


# ── o laço do worker e as rotas ────────────────────────────────────────────────────────────
def _paginas(linhas, tam=2):
    """Imita o work_orders/ paginado, em ordem DESC de criação."""
    ordem = sorted(linhas, key=lambda w: w["creation_date"], reverse=True)

    def falso(ep, **p):
        assert ep == "work_orders/"
        ini = int(p.get("start", 0))
        return {"total": len(ordem), "data": ordem[ini:ini + tam]}
    return falso


def test_varredura_incremental_para_depois_de_passar_da_data_limite(monkeypatch):
    lin = [linha(i, "2026-09-%02dT10:00:00+00:00" % d, "2026-09-%02dT10:30:00+00:00" % d, tarefa=i)
           for i, d in enumerate([1, 3, 5, 8, 12, 15, 18, 21], start=1)]
    chamadas = []
    falso = _paginas(lin)
    monkeypatch.setattr(app, "_frac_get", lambda ep, **p: chamadas.append(p) or falso(ep, **p))
    from datetime import datetime, timezone
    got = app._frac_mtta_sweep(datetime(2026, 9, 14, tzinfo=timezone.utc))
    assert {w["id_work_orders_tasks"] for w in got} >= {6, 7, 8}          # 15, 18 e 21/09
    assert len(chamadas) < 4                                               # não varreu a base inteira


def test_varredura_que_falha_no_meio_nao_vira_base(monkeypatch):
    lin = [linha(i, "2026-09-%02dT10:00:00+00:00" % i, "2026-09-%02dT10:30:00+00:00" % i, tarefa=i) for i in range(1, 9)]
    falso = _paginas(lin)
    monkeypatch.setattr(app, "_frac_get", lambda ep, **p: None if int(p.get("start", 0)) >= 4 else falso(ep, **p))
    with pytest.raises(RuntimeError):
        app._frac_mtta_sweep(None)


def test_recalcular_publica_o_indice_e_a_rota_serve(monkeypatch, tmp_path):
    lin = [linha(1, "2026-09-01T10:00:00+00:00", "2026-09-01T10:30:00+00:00", tarefa=1),
           linha(2, "2026-09-02T10:00:00+00:00", "2026-09-02T10:45:00+00:00", tarefa=2)]
    monkeypatch.setattr(app, "FRACTTAL_ON", True)
    monkeypatch.setattr(app, "_frac_get", _paginas(lin))
    monkeypatch.setattr(app, "_FRAC_MTTA_FILE", str(tmp_path / "frac_mtta_index.json"))
    monkeypatch.setattr(app, "_FRAC_MTTA_BASE", str(tmp_path / "frac_mtta_linhas.json"))
    monkeypatch.setattr(app, "_frac_mtta_mem", {"mtime": 0.0, "dados": {}})
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    c = app.app.test_client()
    assert c.get("/api/cos/mtta").get_json()["quente"] is False            # antes da 1ª varredura
    app._frac_mtta_recalcular()
    d = c.get("/api/cos/mtta").get_json()
    assert d["quente"] is True and len(d["os"]) == 2 and d["total_tarefas"] == 2
    assert sorted(r[5] for r in d["os"]) == [30, 45]
    html = c.get("/cos").get_data(as_text=True)
    assert "Acompanhamento" in html and "/api/cos/mtta" in html


def test_tela_nao_aponta_para_caminho_que_o_caddy_sequestra():
    # /monitoramento e /auth morrem em 502 no servidor (ver test_monitoramento_fora_do_caddy.py)
    html = (pathlib.Path(app.__file__).resolve().parent / "templates" / "cos.html").read_text(encoding="utf-8")
    assert '"/monitoramento' not in html and "'/monitoramento" not in html and '"/auth' not in html
