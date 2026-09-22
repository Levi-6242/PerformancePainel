# -*- coding: utf-8 -*-
"""O processo TEM de rodar em horário de Brasília — e quando não roda, tem de gritar (22/09/2026).

O incidente: a plataforma entrou num servidor Linux em UTC. Dezenas de réguas comparam carimbo de
usina com `datetime.now()` NAIVE — `falha_comunicacao`, a janela solar 07-18 h, a ronda das
08:25/13:00, o fechamento do dia às 01:30 — e todas assumem que a hora local do processo É Brasília,
o que sempre foi verdade nas máquinas Windows da equipe.

Com 3 h de defasagem, `diff` deu ~183 min contra um limiar de 30 e **108 das 115 usinas da API PV
apareceram "sem comunicação"**, com o dado chegando normal e mais fresco que o da máquina local.
Usina marcada assim tem as strings suprimidas — então a tela não listava string nenhuma, e o
sintoma relatado foi "a lista de strings não carrega", a três camadas da causa.

O conserto de verdade é `TZ=America/Sao_Paulo` no serviço. Estes testes seguram o AVISO: que a
próxima vez seja uma linha de log que se lê, não 108 usinas mudas.
"""
import pytest

import app


@pytest.mark.parametrize("h", [-3.0, -3.2, -2.7])
def test_brasilia_passa(monkeypatch, h):
    """−3 e a folga de meia hora: relógio levemente fora não é motivo de alarme."""
    monkeypatch.setattr(app, "_fuso_do_processo_h", lambda: h)
    r = app._conferir_fuso()
    assert r["ok"] is True and r["msg"] == ""


def test_utc_acusa_e_diz_o_efeito(monkeypatch):
    """É o caso do servidor. A mensagem tem de dizer o EFEITO, senão quem lê não liga o aviso ao
    sintoma que está vendo na tela."""
    monkeypatch.setattr(app, "_fuso_do_processo_h", lambda: 0.0)
    r = app._conferir_fuso()
    assert r["ok"] is False
    assert "180 min" in r["msg"], r["msg"]
    assert "sem comunicação" in r["msg"] and "America/Sao_Paulo" in r["msg"]


def test_fuso_adiantado_tambem_acusa(monkeypatch):
    """Não é só UTC: qualquer fuso diferente quebra as mesmas réguas."""
    monkeypatch.setattr(app, "_fuso_do_processo_h", lambda: -6.0)
    assert app._conferir_fuso()["ok"] is False


def test_healthz_continua_200_e_comeca_com_ok(monkeypatch):
    """Monitor que olha só o código HTTP não pode passar a apitar por causa do aviso — mas quem lê
    o corpo tem de ver o problema."""
    monkeypatch.setattr(app, "DASH_PASSWORD", "", raising=False)
    app.app.config["TESTING"] = True
    monkeypatch.setattr(app, "_fuso_do_processo_h", lambda: 0.0)
    with app.app.test_client() as c:
        r = c.get("/healthz")
        assert r.status_code == 200
        corpo = r.data.decode("utf-8")
        assert corpo.startswith("ok") and "ATENCAO" in corpo and "America/Sao_Paulo" in corpo


def test_healthz_fica_limpo_no_fuso_certo(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "", raising=False)
    app.app.config["TESTING"] = True
    monkeypatch.setattr(app, "_fuso_do_processo_h", lambda: -3.0)
    with app.app.test_client() as c:
        assert c.get("/healthz").data.decode("utf-8") == "ok"


def test_o_limiar_de_comunicacao_continua_30_min():
    """O número que a defasagem de fuso atropelava. Se mudar, o cálculo do aviso muda junto."""
    assert app.COMM_ALERT_MINUTES == 30


def test_o_fuso_esperado_e_brasilia_sem_horario_de_verao():
    assert app.FUSO_ESPERADO_H == -3.0
