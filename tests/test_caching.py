"""Cache do get_plants — evita rebaixar a lista de usinas uma vez por usina.

A aba "Curva das strings" do Thopen carregava todas as ~108 usinas e cada chamada
refazia GET /plants. Este teste prova, contando as idas à rede (via _http mockado),
que a 2ª chamada vem do cache e que force=True o ignora.
"""
import app


class _FakeSession:
    """Sessão falsa que conta quantos GET /plants foram feitos."""
    def __init__(self, data):
        self.data = data
        self.gets = 0

    def get(self, *a, **k):
        self.gets += 1
        sess = self

        class _R:
            def json(self_inner):
                return sess.data
        return _R()


def test_get_plants_cacheia(monkeypatch):
    plants = [{"id": 1, "nome": "Araputanga"}, {"id": 2, "nome": "Colíder 1"}]
    sess = _FakeSession(plants)
    monkeypatch.setattr(app, "_http", lambda: sess)
    monkeypatch.setattr(app, "_plants_cache", {"ts": 0.0, "data": None})  # cache limpo p/ o teste

    assert app.get_plants("tok") == plants
    assert app.get_plants("tok") == plants
    assert sess.gets == 1            # a 2ª veio do cache: só 1 ida à rede


def test_get_plants_force_ignora_cache(monkeypatch):
    plants = [{"id": 1, "nome": "Araputanga"}]
    sess = _FakeSession(plants)
    monkeypatch.setattr(app, "_http", lambda: sess)
    monkeypatch.setattr(app, "_plants_cache", {"ts": 0.0, "data": None})

    app.get_plants("tok")
    app.get_plants("tok", force=True)   # força rebuscar
    assert sess.gets == 2


def test_get_plants_nao_cacheia_resposta_vazia(monkeypatch):
    # Resposta vazia/inválida (API instável) não deve "grudar" no cache.
    sess = _FakeSession([])
    monkeypatch.setattr(app, "_http", lambda: sess)
    monkeypatch.setattr(app, "_plants_cache", {"ts": 0.0, "data": None})

    app.get_plants("tok")
    app.get_plants("tok")
    assert sess.gets == 2            # nada foi cacheado → bateu na rede de novo
