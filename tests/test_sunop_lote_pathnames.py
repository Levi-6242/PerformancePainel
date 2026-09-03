"""O tamanho do lote pedido à SunOp no /v2/analog_values.

Companheiro de [test_sunop_periodo_agregacao.py], que trava a granularidade. A divisão de
trabalho entre os dois é o que mais confunde quem chega depois:

  * `TRK_CURVA_PERIODO` (5m → 15m) corta PAYLOAD e o processamento do lado deles. Não muda o
    número de POSTs.
  * `SUNOP_LOTE_PATHNAMES` (40 → 300) corta a CONTAGEM de POSTs. Não muda o dado.

Por que 300 virou assunto (02/09/2026): o `/v2/usage/me` mostrou 12.678 requisições num dia
contra uma cota de 100.000/mês — projeção de 3,4× a cota, com o saldo acabando em ~09/09. Os 40
não vinham da API; o OpenAPI não declara limite em `pathnames`. Medido nas 10 usinas, tracker e
string: 6.471 pathnames com valor idêntico, zero divergência, 169 POSTs → 30.
"""
import inspect

import app


def test_o_lote_e_de_600():
    assert app.SUNOP_LOTE_PATHNAMES == 600


def test_a_divisao_em_lotes_acontece_de_verdade(monkeypatch):
    """Captura os lotes que saem, em vez de olhar o texto da função.

    Inspeção de fonte não pegaria o erro que interessa aqui: a constante ser lida uma vez e o
    fatiamento continuar com outro passo — o dado ainda chegaria, só que em N vezes mais POSTs,
    e nada na tela denunciaria."""
    vistos = []

    class _R:
        status_code = 200

        @staticmethod
        def json():
            return []

    def _falso(metodo, url, inst, **kw):
        vistos.append((len((kw.get("json") or {}).get("pathnames") or []), kw.get("timeout")))
        return _R()

    monkeypatch.setattr(app, "_sunop_req", _falso)
    monkeypatch.setattr(app, "_sunop_data_headers", lambda inst: {})
    app._sunop_analog_history([f"X.TRK_{i}.MEDIDAS.POSAT" for i in range(700)],
                              "2026-09-02T05:40:00", "2026-09-02T14:00:00")

    assert [n for n, _ in vistos] == [600, 100]


def test_o_timeout_acompanha_o_lote(monkeypatch):
    """Lote 7,5× maior com o timeout velho de 60s seria perda SILENCIOSA: o `_fetch` devolve []
    quando a resposta não vem, e um lote de 300 apaga a curva de meia usina sem erro nenhum."""
    vistos = []

    class _R:
        status_code = 200

        @staticmethod
        def json():
            return []

    def _falso(metodo, url, inst, **kw):
        vistos.append(kw.get("timeout"))
        return _R()

    monkeypatch.setattr(app, "_sunop_req", _falso)
    monkeypatch.setattr(app, "_sunop_data_headers", lambda inst: {})
    app._sunop_analog_history(["X.TRK_1.MEDIDAS.POSAT"], "2026-09-02T05:40:00",
                              "2026-09-02T14:00:00")

    assert vistos and all(t >= 120 for t in vistos), vistos


def test_nao_sobrou_lote_fixo_na_funcao():
    """A constante tem de ser a ÚNICA fonte do passo. Um `40` esquecido aqui volta a triplicar a
    contagem no dia em que alguém mexer na constante achando que basta."""
    fonte = inspect.getsource(app._sunop_analog_history)
    assert "SUNOP_LOTE_PATHNAMES" in fonte
    assert "i + 40" not in fonte
