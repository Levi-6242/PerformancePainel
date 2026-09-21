# -*- coding: utf-8 -*-
"""Contador de requisições à SunOp (Levi, 20/09/2026: "vamos precisar otimizar isso").

**O número que motivou:** o `/data/v2/usage/me` acusou **162.892 requisições de 01 a 20/09** contra
uma cota de 100.000/mês. Saldo restante ZERO desde o dia 12, US$ 31,45 já cobrados e projeção de
~US$ 72 no mês fechado. Para caber seriam 3.333/dia; a média é 8.145. Corte necessário: 59%.

**Por que um contador vem ANTES de otimizar:** o gêmeo mede o que gasta (85 req/dia pelo
`ingest_run.n_requisicoes`) e por isso sabemos que ele não é o problema. A plataforma não media
nada — dava para ver a fatura, não o extrato. Sem isto, otimizar é adivinhar, e não dá para provar
que a otimização funcionou.

O `_sunop_req` é o funil ÚNICO de todas as chamadas ao /data (existe desde o disjuntor de 06/08),
então é o lugar certo: um ponto só, e nenhuma chamada escapa dele.
"""
import app


def test_toda_chamada_ao_data_passa_a_ser_contada(monkeypatch):
    """Conta por ENDPOINT, que é a pergunta que interessa: quem gasta a cota."""
    app._sunop_uso_zerar()
    monkeypatch.setattr(app, "_sunop_edge_aberto", lambda: False)
    monkeypatch.setattr(app, "_sunop_data_headers", lambda inst: {})
    monkeypatch.setattr(app, "_sunop_edge_block", lambda r: False)

    class _Resp:
        status_code = 200

    class _Http:
        def request(self, metodo, url, **kw):
            return _Resp()

    monkeypatch.setattr(app, "_http", lambda: _Http())
    base = "https://gridco-api.sunop.net/data/v2"
    for _ in range(3):
        app._sunop_req("POST", f"{base}/analog_values")
    app._sunop_req("POST", f"{base}/last_values")
    app._sunop_req("GET", f"{base}/metadata/MRO100")

    uso = app._sunop_uso_hoje()
    assert uso.get("analog_values") == 3, uso
    assert uso.get("last_values") == 1 and uso.get("metadata") == 1, uso
    assert sum(uso.values()) == 5


def test_chamada_barrada_pelo_disjuntor_nao_conta(monkeypatch):
    """Disjuntor aberto devolve None SEM tocar a rede — contar isso inflaria o extrato e faria a
    gente 'otimizar' um gasto que não existe."""
    app._sunop_uso_zerar()
    monkeypatch.setattr(app, "_sunop_edge_aberto", lambda: True)
    assert app._sunop_req("POST", "https://gridco-api.sunop.net/data/v2/analog_values") is None
    assert app._sunop_uso_hoje() == {}


def test_o_contador_nunca_derruba_a_chamada(monkeypatch):
    """Mesma regra do `_log_arquivo`: registrar não pode quebrar o que estava registrando."""
    app._sunop_uso_zerar()
    monkeypatch.setattr(app, "_sunop_edge_aberto", lambda: False)
    monkeypatch.setattr(app, "_sunop_data_headers", lambda inst: {})
    monkeypatch.setattr(app, "_sunop_edge_block", lambda r: False)
    monkeypatch.setattr(app, "_sunop_uso_conta", lambda url: (_ for _ in ()).throw(RuntimeError("contador quebrado")))

    class _Resp:
        status_code = 200

    monkeypatch.setattr(app, "_http", lambda: type("H", (), {"request": lambda s, m, u, **k: _Resp()})())
    r = app._sunop_req("POST", "https://gridco-api.sunop.net/data/v2/analog_values")
    assert r is not None, "o contador quebrou e levou a requisição junto"


def test_a_rota_de_uso_soma_os_dois_processos(tmp_path, monkeypatch):
    """Web e worker contam separado (dois processos, um arquivo cada). Quem lê tem de somar, senão
    o extrato mostra metade do gasto e a gente 'otimiza' o lado errado."""
    import json as _json
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "sunop_uso_worker.json").write_text(_json.dumps({"2026-09-20": {"analog_values": 900, "last_values": 120}}), encoding="utf-8")
    (logs / "sunop_uso_web.json").write_text(_json.dumps({"2026-09-20": {"analog_values": 40, "metadata": 7}}), encoding="utf-8")
    monkeypatch.setattr(app, "_AQUI", str(tmp_path))
    with app.app.test_request_context():
        d = app._sunop_uso_relatorio()
    dia = d["dias"]["2026-09-20"]
    assert dia["analog_values"] == 940 and dia["last_values"] == 120 and dia["metadata"] == 7
    assert dia["_total"] == 1067
    assert d["cota_mes"] == 100000


def test_a_rota_existe_e_responde_sem_dado(monkeypatch, tmp_path):
    """Sem nenhum arquivo ainda (primeiro boot), responde vazio em vez de explodir."""
    monkeypatch.setattr(app, "_AQUI", str(tmp_path))
    assert "/api/sunop/uso" in {str(r.rule) for r in app.app.url_map.iter_rules()}
    with app.app.test_request_context():
        assert app._sunop_uso_relatorio()["dias"] == {}
