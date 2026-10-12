# -*- coding: utf-8 -*-
"""A Athon do servidor no PC em modo ronda (Levi, 12/10/2026: "a maioria das usinas do tempo real estão sem comunicação,
investigue e resolva"). No PC (`SUNOP_COLETA=ronda`) a tabela de strings da Athon não era montada desde 29/09 e o tempo
real julgava as 10 usinas pela tabela de 29/09: 7 "sem comunicação" e 3 "desligadas", com as 10 normais no servidor.
O PC passa a ler a tabela que o servidor já montou (a mesma rota da aba), sem pedido nenhum à SunOp."""
import pytest
import requests

import app
from test_porta_nexus import SENHA, _sem_rede, cli, entrar_com_senha  # noqa: F401  (fixtures da porta)


class _Resp:
    def __init__(self, status, corpo=None):
        self.status_code, self._corpo = status, corpo

    def json(self):
        return self._corpo


class _Servidor:
    """O servidor de mentira: /login com a senha do painel abre a sessão; /api/sunop/data serve a tabela dele."""

    def __init__(self, linhas):
        self.linhas, self.logins, self.leituras, self.vence_uma_vez, self.senha_ok = linhas, 0, 0, False, True

    def sessao(self):
        srv = self

        class _Sessao:
            def post(self, url, data=None, allow_redirects=True, timeout=None):
                assert url == "https://servidor.exemplo/login" and data == {"senha": SENHA}
                srv.logins += 1
                return _Resp(302 if srv.senha_ok else 200)

            def get(self, url, timeout=None):
                assert url == "https://servidor.exemplo/api/sunop/data"
                srv.leituras += 1
                if srv.vence_uma_vez:
                    srv.vence_uma_vez = False
                    return _Resp(401, {"error": "não autenticado"})
                return _Resp(200, {"rows": srv.linhas, "cache_ts": "10:31"})
        return _Sessao


@pytest.fixture
def ronda(monkeypatch):
    monkeypatch.setattr(app, "SUNOP_COLETA", "ronda")
    monkeypatch.setattr(app, "DASH_PASSWORD", SENHA)                                  # a mesma nas duas máquinas
    monkeypatch.setattr(app, "SUNOP_ESPELHO_URL", "https://servidor.exemplo")
    monkeypatch.setattr(app, "_SUNOP_ESPELHO", {"sessao": None})
    monkeypatch.delenv("SUNOP_ESPELHO", raising=False)
    srv = _Servidor([{"plant_id": "CPP100", "usina": "CPP100", "status": "ok", "str_esp": 120}])
    monkeypatch.setattr(requests, "Session", srv.sessao())
    return srv


def test_so_o_pc_em_modo_ronda_le_a_athon_do_servidor(ronda, monkeypatch):
    assert app._sunop_espelho_ligado() and not app._sunop_espelho_ligado("axis")      # a Axis está sem token nos dois
    monkeypatch.setenv("SUNOP_ESPELHO", "0")
    assert not app._sunop_espelho_ligado()
    monkeypatch.delenv("SUNOP_ESPELHO")
    monkeypatch.setattr(app, "SUNOP_COLETA", "completa")                              # o servidor monta a dele
    assert not app._sunop_espelho_ligado()
    monkeypatch.setattr(app, "SUNOP_COLETA", "ronda")
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    assert not app._sunop_espelho_ligado()


def test_le_a_tabela_do_servidor_com_uma_sessao_e_entra_de_novo_se_ela_vencer(ronda):
    d = app._build_sunop_espelho()
    assert d["rows"][0]["plant_id"] == "CPP100" and d["espelho"] == "https://servidor.exemplo"
    app._build_sunop_espelho()
    assert (ronda.logins, ronda.leituras) == (1, 2)                                   # a sessão é reaproveitada
    ronda.vence_uma_vez = True
    assert app._build_sunop_espelho()["rows"]
    assert (ronda.logins, ronda.leituras) == (2, 4)                                   # 401 → entra de novo, uma vez


def test_falha_levanta_e_nunca_devolve_tabela_vazia(ronda):
    ronda.linhas = []
    with pytest.raises(RuntimeError, match="sem linhas"):
        app._build_sunop_espelho()
    ronda.senha_ok = False
    app._SUNOP_ESPELHO["sessao"] = None
    with pytest.raises(RuntimeError, match="recusou a senha"):
        app._build_sunop_espelho()


def test_o_prewarm_do_pc_troca_a_tabela_da_athon_pelo_espelho(ronda, monkeypatch):
    monkeypatch.setattr(app, "SUNOP_PAUSA_LIGADA", True)
    monkeypatch.setattr(app, "_sunop_gasto_hoje", lambda: 10 ** 6)                    # o teto do dia já estourou
    tarefas = [("SunOp", None, None), ("SunOp espelho", None, None), ("SEMP strings", None, None)]
    fica = [t[0] for t in app._prewarm_filtra_noturno(tarefas)]
    assert "SunOp espelho" in fica and "SunOp" not in fica                           # sem pedido à SunOp, mesmo no teto


def test_a_aba_da_athon_no_pc_serve_o_espelho_sem_dizer_sunop_pausada(cli, ronda, monkeypatch):
    entrar_com_senha(cli)
    monkeypatch.setattr(app, "_sunop_cache", {"ts": 0.0, "payload": None, "_ttl": 600})
    monkeypatch.setattr(app, "_sunop_pausa", lambda considera_ronda=True: "teto")
    d = cli.get("/api/sunop/data").get_json()
    assert [r["plant_id"] for r in d["rows"]] == ["CPP100"] and d["espelho"] and d["sunop_pausa"] is None
