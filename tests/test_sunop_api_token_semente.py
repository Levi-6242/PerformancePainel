# -*- coding: utf-8 -*-
"""O token de API do SunOp precisa de SEMENTE, não só de estado (22/09/2026).

O caso: a plataforma subiu num servidor dedicado e a Athon veio sem strings, sem ETM e sem
trackers. A causa não foi rede nem senha — foram DOIS tokens diferentes no mesmo fornecedor:

  - `SUNOP_TOKEN`  — token WEB, 7 dias, esquema `JWT …`, serve aos endpoints de CONFIGURAÇÃO (/api).
  - `SUNOP_API_TOKEN` — token de API, gerado à mão na interface, 6 a 12 meses, esquema
    `Bearer API …`, e é o ÚNICO que o serviço de DADOS (/data) aceita desde 30/07/2026.

O segundo vivia só no `tokens_runtime.json` — um arquivo classificado como "estado que o app
reescreve", que por isso ficou fora da migração de propósito. A regra estava certa para o
PLAT_TOKEN (levar estado velho sequestra a renovação) e errada para este, que é credencial de
gente, de vida longa. Sem ele o /data caía no token web, vencido desde 23/07, e tomava 401 em tudo.

O teste trava a escada e, principalmente, a EXISTÊNCIA da semente: se `SUNOP_API_TOKEN` sumir do
caminho de leitura, a próxima instalação limpa repete o mesmo silêncio.
"""
import time

import pytest

import app


def _jwt(exp_epoch: float) -> str:
    """JWT de mentira com `exp` — só o payload importa para `_jwt_exp`."""
    import base64
    import json
    p = base64.urlsafe_b64encode(json.dumps({"sub": "t", "exp": int(exp_epoch)}).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJIUzI1NiJ9.{p}.assinatura"


@pytest.fixture
def sem_runtime(monkeypatch):
    """Servidor recém-instalado: tokens.txt veio, tokens_runtime.json não."""
    monkeypatch.setattr(app, "_tokens_rt_get", lambda *_a, **_k: "", raising=False)


def test_sem_runtime_a_semente_do_tokens_txt_e_usada(monkeypatch, sem_runtime):
    """É exatamente o estado do servidor novo. Sem esta linha, a Athon sobe muda."""
    tok = _jwt(time.time() + 200 * 86400)
    monkeypatch.setenv("SUNOP_API_TOKEN", tok)
    assert app._sunop_api_token("gridco") == tok


def test_sem_semente_e_sem_runtime_devolve_vazio_e_nao_levanta(monkeypatch, sem_runtime):
    """Sem token nenhum o /data cai no header web — comportamento antigo, não exceção."""
    monkeypatch.delenv("SUNOP_API_TOKEN", raising=False)
    assert app._sunop_api_token("gridco") == ""


def test_vence_quem_tem_validade_MAIOR_nao_a_ordem(monkeypatch):
    """Mesma regra do PLAT_TOKEN, e pelo mesmo motivo: em 25/07/2026 uma semente velha ganhou de um
    token recém-colado e a plataforma seguiu no vencido até alguém editar na mão."""
    novo, velho = _jwt(time.time() + 300 * 86400), _jwt(time.time() + 10 * 86400)
    monkeypatch.setattr(app, "_tokens_rt_get", lambda *_a, **_k: velho, raising=False)
    monkeypatch.setenv("SUNOP_API_TOKEN", novo)
    assert app._sunop_api_token("gridco") == novo, "semente mais nova tem de ganhar do runtime velho"
    monkeypatch.setattr(app, "_tokens_rt_get", lambda *_a, **_k: novo, raising=False)
    monkeypatch.setenv("SUNOP_API_TOKEN", velho)
    assert app._sunop_api_token("gridco") == novo, "runtime mais novo tem de ganhar da semente velha"


def test_a_axis_tem_a_propria_chave(monkeypatch, sem_runtime):
    """Instâncias separadas: `AXIS_API_TOKEN` não pode cair no do gridco — seria mandar o token de
    uma conta para a API da outra."""
    monkeypatch.setenv("SUNOP_API_TOKEN", _jwt(time.time() + 100 * 86400))
    monkeypatch.delenv("AXIS_API_TOKEN", raising=False)
    assert app._sunop_api_token("axis") == ""
    tok = _jwt(time.time() + 100 * 86400)
    monkeypatch.setenv("AXIS_API_TOKEN", tok)
    assert app._sunop_api_token("axis") == tok


def test_o_header_de_dados_usa_o_esquema_Bearer_API(monkeypatch, sem_runtime):
    """O /data recusa `JWT …` desde 30/07/2026; o esquema faz parte do conserto."""
    monkeypatch.setenv("SUNOP_API_TOKEN", _jwt(time.time() + 100 * 86400))
    h = app._sunop_data_headers("gridco")
    assert h["Authorization"].startswith("Bearer API "), h["Authorization"][:20]


def test_a_semente_esta_no_arquivo_de_segredos():
    """Guarda de migração: o tokens.txt é o que viaja para um servidor novo. Se `SUNOP_API_TOKEN`
    sair de lá, a próxima instalação limpa repete o incidente de 22/09 — e sem erro na tela, porque
    o /data devolve 401 e a fonte simplesmente aparece vazia."""
    import pathlib
    raiz = pathlib.Path(app.__file__).resolve().parents[1]
    arq = raiz / "tokens.txt"
    if not arq.exists():
        pytest.skip("tokens.txt não está nesta máquina (é segredo, fora do git)")
    chaves = {l.split("=", 1)[0].strip() for l in arq.read_text(encoding="utf-8", errors="ignore").splitlines()
              if "=" in l and not l.strip().startswith("#")}
    assert "SUNOP_API_TOKEN" in chaves, "o token que o /data exige sumiu do arquivo de segredos"
