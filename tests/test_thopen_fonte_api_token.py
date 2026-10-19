# -*- coding: utf-8 -*-
"""O token de escrita do banco (GRIDCO_SQL_TOKEN) também vem do .env da raiz (19/10/2026).

POR QUE ESTE TESTE EXISTE
O `fonte_api._token()` lia só o ambiente e o `tokens.txt`, enquanto todo outro segredo do painel (`fonte_api.segredo`)
lê o `.env` também. O clone do cliente (C:\\GridcoAuto\\PerformancePainel) tinha só o `.env`: no 5080 com login, a
senha definida pelo link e a contestação não gravavam no banco ("sem o token de escrita"), calado, de 16 a 19/10/2026.
A ordem fica: ambiente, `tokens.txt` (como sempre) e, por último, o `.env`.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "thopen"))
import fonte_api  # noqa: E402


def _raiz(tmp_path, monkeypatch, env=None, tokens=None):
    (tmp_path / "thopen").mkdir()
    if env is not None:
        (tmp_path / ".env").write_text("OUTRA=1\nGRIDCO_SQL_TOKEN=%s\n" % env, encoding="utf-8")
    if tokens is not None:
        (tmp_path / "tokens.txt").write_text("GRIDCO_SQL_TOKEN=%s\n" % tokens, encoding="utf-8")
    monkeypatch.setattr(fonte_api, "_AQUI", str(tmp_path / "thopen"))
    monkeypatch.delenv("GRIDCO_SQL_TOKEN", raising=False)


def test_token_so_no_env_vale(tmp_path, monkeypatch):
    _raiz(tmp_path, monkeypatch, env="do-env")
    assert fonte_api._token() == "do-env"


def test_tokens_txt_vence_o_env_e_o_ambiente_vence_os_dois(tmp_path, monkeypatch):
    _raiz(tmp_path, monkeypatch, env="do-env", tokens="do-tokens")
    assert fonte_api._token() == "do-tokens"
    monkeypatch.setenv("GRIDCO_SQL_TOKEN", "do-ambiente")
    assert fonte_api._token() == "do-ambiente"


def test_sem_nada_e_vazio(tmp_path, monkeypatch):
    _raiz(tmp_path, monkeypatch)
    assert fonte_api._token() == ""
