"""A granularidade pedida à SunOp na curva de tracker.

Contexto (reunião com o gestor de backend da SunOp, 02/09/2026): o consumo da nossa conta estava
alto — 9.950 requisições num dia só do nosso token, e 7.984 SEGUNDOS de processamento do lado
deles, medidos no `/v2/usage`. A orientação dele para tracker foi pedir a agregação de 15 min em
vez da granularidade fina.

Dois fatos que este teste existe para não deixar esquecer:

1. **Nunca puxamos dado cru.** Não passar `aggregation` não é "raw" — o default da API é `avg`
   com `period='5m'`. A mudança foi de 5m para 15m, não de cru para agregado.
2. **Isto NÃO reduz o número de requisições.** O lote do `_sunop_analog_history` é de 40
   PATHNAMES, então 5m e 15m dão exatamente o mesmo nº de POSTs. Quem quiser cortar a CONTAGEM
   tem de mexer em quantos pathnames ou com que frequência se pede — não aqui.

Verificado contra a API real antes de ligar (3 usinas × 150 trackers): mesmos parados
(41/10/10), zero divergência, 60% menos pontos. A margem do tracker mais próximo do limiar de
15° ficou entre 10° e 14°.
"""
import inspect
import re

import app


def test_a_curva_de_tracker_pede_15_minutos():
    assert app.TRK_CURVA_PERIODO == "15m"


def test_a_busca_de_historico_aceita_period():
    # se o parâmetro sumir, o `period=` das chamadas vira TypeError na primeira busca — mas só
    # em produção, porque nada mais exercita esse caminho.
    assert "period" in inspect.signature(app._sunop_analog_history).parameters


def test_period_so_entra_nos_params_quando_pedido():
    """Omitir `period` tem de manter o default da API (avg/5m), não mandar period=None.

    Mandar `period=None` na querystring viraria a string "None" e a SunOp responderia erro — e o
    chamador veria lista vazia, que aqui não é erro: é "usina sem curva". Falha muda."""
    fonte = inspect.getsource(app._sunop_analog_history)
    assert re.search(r"if period:\s*\n\s*params\[.period.\]\s*=\s*period", fonte)


def test_as_duas_curvas_de_tracker_usam_a_constante():
    """A do dia (`_sunop_trk_curvas`) e a multi-dia (`_sunop_trk_curvas_range`).

    A multi-dia é a que mais pesa — o gráfico vai até 5 dias. Se uma das duas ficar para trás,
    metade do ganho some sem ninguém notar, porque as duas devolvem curva com a mesma cara."""
    for fn in (app._sunop_trk_curvas, app._sunop_trk_curvas_range):
        assert "TRK_CURVA_PERIODO" in inspect.getsource(fn), fn.__name__


def test_a_curva_de_strings_nao_foi_alterada_junto():
    """Só TRACKER mudou. A orientação do gestor separou explicitamente: analógica faz sentido
    fina, tracker não. Strings são corrente por string — a régua de 'sem corrente' olha o valor
    instantâneo, e agregar mais grosso poderia esconder queda curta."""
    fonte = inspect.getsource(app._sunop_strings_curva)
    assert "TRK_CURVA_PERIODO" not in fonte
