"""Uma usina incompleta não pode derrubar o overview de trackers inteiro.

Caso real (26/08): `_pg_trackers_overview` estava **33 horas** sem atualizar. Causa: a usina
(305) Guaratinguetá V aparece em `public.raw_tracker` nos últimos 2 dias, mas o
`_pg_trackers_analise` não resolve tracker nenhum para a data-base e devolve o `base` de saída
antecipada — que não trazia `severos`/`medios`/`leves`. O `sum(r["severos"] ...)` do resumo
levantava KeyError, a exceção subia, o `_prewarm_paralelo` engolia num print que ninguém lê
(pythonw não tem console) e o cache NUNCA era republicado. 16 usinas boas sumiram da tela por
causa de 1 linha.

Sintoma que denunciava: `medios` já usava `.get("medios", 0)` enquanto `severos` e `leves`
acessavam direto — alguém tropeçou nisto antes e remendou só um terço.
"""
import app


def test_resumo_tolera_linha_sem_as_chaves():
    linhas = [
        {"usina": "A", "total": 10, "severos": 2, "medios": 1, "leves": 0},
        {"usina": "(305) Guaratinguetá V", "total": 0, "tem_trackers": False},   # a que derrubava
        {"usina": "B", "total": 5, "severos": 1, "medios": 0, "leves": 3},
    ]
    r = app._trk_resumo_linhas(linhas)
    assert r == {"usinas": 3, "trackers": 15, "severos": 3, "medios": 1, "leves": 3}


def test_resumo_de_lista_vazia_nao_explode():
    assert app._trk_resumo_linhas([]) == {"usinas": 0, "trackers": 0, "severos": 0,
                                          "medios": 0, "leves": 0}


def test_resumo_trata_None_como_zero():
    """Linha pode trazer a chave com None (usina sem leitura), e None não soma."""
    r = app._trk_resumo_linhas([{"total": None, "severos": None, "medios": None, "leves": None}])
    assert r["trackers"] == 0 and r["severos"] == 0


def test_base_do_pg_carrega_as_chaves_do_resumo():
    """Conserto de RAIZ, além da tolerância: toda linha que chega ao overview tem de ter a mesma
    forma. Sem isto, o próximo consumidor do payload tropeça no mesmo buraco."""
    import inspect
    fonte = inspect.getsource(app._pg_trackers_analise)
    ini = fonte.index("base = {")
    corpo = fonte[ini:fonte.index("}", ini)]
    for chave in ("severos", "medios", "leves"):
        assert f'"{chave}"' in corpo, f"o dict `base` não declara {chave!r}"
