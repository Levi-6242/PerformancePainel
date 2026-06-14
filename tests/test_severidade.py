"""severidade(r) — ordena as usinas do pior (0) ao normal (5).

A ordem de avaliação importa: condições anteriores têm prioridade. Os testes
fixam um resumo "normal" e ligam um problema de cada vez.
"""
import app


def _resumo(**over):
    base = {
        "sem_dados": False,
        "strings_ativas": 5,
        "diferenca": 0,
        "temp_media": 30.0,
        "falha_comunicacao": False,
    }
    base.update(over)
    return base


def test_sev0_sem_geracao():
    assert app.severidade(_resumo(strings_ativas=0)) == 0


def test_sev1_falha_de_string():
    assert app.severidade(_resumo(diferenca=-2)) == 1


def test_sev2_temp_elevada():
    # diferenca >= 0 e temp acima do alerta
    assert app.severidade(_resumo(temp_media=app.TEMP_ALERT)) == 2
    assert app.severidade(_resumo(temp_media=80.0)) == 2


def test_sev3_falha_comunicacao():
    assert app.severidade(_resumo(falha_comunicacao=True)) == 3


def test_sev4_sem_dados():
    # sem_dados pula as 3 primeiras (que exigem `not sem_dados`); precisa de
    # falha_comunicacao=False, senão cairia em 3 antes.
    assert app.severidade(_resumo(sem_dados=True, falha_comunicacao=False)) == 4


def test_sev5_normal():
    assert app.severidade(_resumo()) == 5


def test_prioridade_sem_geracao_vence_temp():
    # strings_ativas==0 vem antes de temp elevada
    assert app.severidade(_resumo(strings_ativas=0, temp_media=90.0)) == 0


def test_prioridade_falha_comunicacao_vence_sem_dados():
    # com sem_dados E falha_comunicacao, a comunicação (3) é avaliada antes (4)
    assert app.severidade(_resumo(sem_dados=True, falha_comunicacao=True)) == 3
