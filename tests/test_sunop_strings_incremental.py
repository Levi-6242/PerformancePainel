"""Busca INCREMENTAL da curva de strings do SunOp (_sunop_str_hist_do_dia).

Contexto (02/09/2026): as strings são 5.602 dos 6.607 pathnames que o ciclo pede, e a curva era
rebaixada 00:00→23:59 a cada volta — às 17h, 11h de curva já conhecida re-transferidas ~76 vezes
por dia. O desenho é o mesmo já provado na curva de tracker em 26/08.

O teste que IMPORTA aqui é o de equivalência da fusão: um merge errado não levanta exceção, ele
deforma a curva — e essa curva é o insumo de "string sem corrente" e das ocorrências caiu→voltou.
Por isso os casos abaixo cobrem colisão de timestamp, cache vazio e timestamp ilegível, que são as
três formas de a fusão sair errada sem ninguém perceber.
"""
import datetime as dt

import pytest

import app


@pytest.fixture(autouse=True)
def _limpa():
    app._si("gridco")["str_hist"].clear()
    yield
    app._si("gridco")["str_hist"].clear()


def _fake_hist(monkeypatch, resposta):
    """Troca a busca real e devolve a lista de (inicio, fim) pedidos."""
    pedidos = []

    def _f(pathnames, start, end, inst="gridco", period=None):
        pedidos.append((start, end))
        return resposta(start) if callable(resposta) else resposta
    monkeypatch.setattr(app, "_sunop_analog_history", _f)
    return pedidos


HOJE = dt.date.today().strftime("%Y-%m-%d")
P = "PLT.INV_1.MEDIDAS.I_PV1"


def test_dia_passado_sempre_busca_cheio(monkeypatch):
    """Dia fechado não cresce mais: incremental ali seria risco sem ganho nenhum."""
    ontem = (dt.date.today() - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    ped = _fake_hist(monkeypatch, {P: [(f"{ontem}T09:00:00", 5.0)]})
    app._sunop_str_hist_do_dia("PLT", ontem, [P])
    app._sunop_str_hist_do_dia("PLT", ontem, [P])
    assert [p[0] for p in ped] == [f"{ontem}T00:00:00", f"{ontem}T00:00:00"]


def test_foto_vazia_nao_e_cacheada(monkeypatch):
    """Falha de borda/token devolvendo vazio não pode virar 'usina sem string' pela hora inteira.

    É a mesma lição do pg_trk congelado 33h e do _sunop_str_med_ent: cachear o vazio transforma
    uma falha de minutos em apagão de horas, e sem nenhum erro na tela."""
    _fake_hist(monkeypatch, {})
    assert app._sunop_str_hist_do_dia("PLT", HOJE, [P]) == {}
    assert ("PLT", HOJE) not in app._si("gridco")["str_hist"]


def test_segunda_volta_pede_so_a_janela_recente(monkeypatch):
    ped = _fake_hist(monkeypatch, lambda start: {P: [(f"{HOJE}T12:00:00", 5.0)]})
    app._sunop_str_hist_do_dia("PLT", HOJE, [P])
    app._si("gridco")["str_hist"][("PLT", HOJE)]["cheio_h"] = dt.datetime.now().hour
    app._sunop_str_hist_do_dia("PLT", HOJE, [P])
    assert ped[0][0] == f"{HOJE}T00:00:00"
    # 12:00 menos a sobreposição de 30 min
    assert ped[1][0] == f"{HOJE}T11:30:00", ped


def test_fusao_mantem_o_antigo_e_o_novo_vence_na_colisao(monkeypatch):
    """União por timestamp. O ponto que a janela estreita nem pediu tem de sobreviver, e o que
    veio corrigido na sobreposição tem de substituir o velho."""
    respostas = [{P: [(f"{HOJE}T11:00:00", 1.0), (f"{HOJE}T12:00:00", 2.0)]},
                 {P: [(f"{HOJE}T12:00:00", 9.9), (f"{HOJE}T12:30:00", 3.0)]}]
    _fake_hist(monkeypatch, lambda start: respostas.pop(0))
    app._sunop_str_hist_do_dia("PLT", HOJE, [P])
    app._si("gridco")["str_hist"][("PLT", HOJE)]["cheio_h"] = dt.datetime.now().hour
    fundido = app._sunop_str_hist_do_dia("PLT", HOJE, [P])
    assert fundido[P] == [(f"{HOJE}T11:00:00", 1.0),    # sobreviveu, não foi pedido de novo
                          (f"{HOJE}T12:00:00", 9.9),    # corrigido pelo novo
                          (f"{HOJE}T12:30:00", 3.0)]


def test_cache_sem_ponto_volta_a_buscar_cheio(monkeypatch):
    """Sem último ponto não há de onde continuar — tentar continuar daria janela inválida."""
    ped = _fake_hist(monkeypatch, lambda start: {P: [(f"{HOJE}T10:00:00", 1.0)]})
    app._sunop_str_hist_do_dia("PLT", HOJE, [P])
    ent = app._si("gridco")["str_hist"][("PLT", HOJE)]
    ent["cheio_h"] = dt.datetime.now().hour
    ent["hist"] = {P: []}
    app._sunop_str_hist_do_dia("PLT", HOJE, [P])
    assert ped[1][0] == f"{HOJE}T00:00:00"


def test_timestamp_ilegivel_volta_a_buscar_cheio(monkeypatch):
    """Na dúvida, dia inteiro: uma data quebrada não pode virar janela silenciosamente errada."""
    ped = _fake_hist(monkeypatch, lambda start: {P: [("nao-e-data", 1.0)]})
    app._sunop_str_hist_do_dia("PLT", HOJE, [P])
    app._si("gridco")["str_hist"][("PLT", HOJE)]["cheio_h"] = dt.datetime.now().hour
    app._sunop_str_hist_do_dia("PLT", HOJE, [P])
    assert ped[1][0] == f"{HOJE}T00:00:00"


def test_uma_busca_cheia_por_hora(monkeypatch):
    """A sobreposição pega ingestão atrasada, não correção que a SunOp faça lá atrás no dia."""
    ped = _fake_hist(monkeypatch, lambda start: {P: [(f"{HOJE}T12:00:00", 1.0)]})
    app._sunop_str_hist_do_dia("PLT", HOJE, [P])
    app._si("gridco")["str_hist"][("PLT", HOJE)]["cheio_h"] = (dt.datetime.now().hour - 1) % 24
    app._sunop_str_hist_do_dia("PLT", HOJE, [P])
    assert ped[1][0] == f"{HOJE}T00:00:00", "hora virou e não houve busca cheia"


def test_baixa_conjunta_pede_todas_as_usinas_de_uma_vez(monkeypatch):
    """O ganho da baixa conjunta é justamente NÃO chamar uma vez por usina: cada chamada separada
    desperdiça a borda do próprio lote."""
    chamadas = []

    def _f(pathnames, start, end, inst="gridco", period=None):
        chamadas.append(sorted(pathnames))
        return {p: [(f"{HOJE}T10:00:00", 1.0)] for p in pathnames}

    monkeypatch.setattr(app, "_sunop_analog_history", _f)
    monkeypatch.setitem(app._si("gridco")["meta"], "U1",
                        {"inv_strings": {"INV_1": ["U1.INV_1.I_PV1"]}})
    monkeypatch.setitem(app._si("gridco")["meta"], "U2",
                        {"inv_strings": {"INV_1": ["U2.INV_1.I_PV1"]}})
    out = app._sunop_str_hist_varias(["U1", "U2"], HOJE)

    assert len(chamadas) == 1, "as duas usinas tinham de sair no MESMO pedido"
    assert chamadas[0] == ["U1.INV_1.I_PV1", "U2.INV_1.I_PV1"]
    # e o recorte por usina tem de devolver só o que é dela
    assert list(out["U1"]) == ["U1.INV_1.I_PV1"]
    assert list(out["U2"]) == ["U2.INV_1.I_PV1"]


def test_baixa_conjunta_separa_cheio_de_incremental(monkeypatch):
    """A query só aceita um `start_time`. Quem precisa do dia inteiro não pode ser arrastado para
    a janela estreita de quem já tem cache — isso deixaria a usina nova sem a manhã."""
    janelas = []

    def _f(pathnames, start, end, inst="gridco", period=None):
        janelas.append(start)
        return {p: [(f"{HOJE}T10:00:00", 1.0)] for p in pathnames}

    monkeypatch.setattr(app, "_sunop_analog_history", _f)
    monkeypatch.setitem(app._si("gridco")["meta"], "U1",
                        {"inv_strings": {"INV_1": ["U1.INV_1.I_PV1"]}})
    monkeypatch.setitem(app._si("gridco")["meta"], "U2",
                        {"inv_strings": {"INV_1": ["U2.INV_1.I_PV1"]}})
    # U1 já tem cache desta hora (vai incremental); U2 não tem (precisa do dia cheio)
    app._si("gridco")["str_hist"][("U1", HOJE)] = {
        "ts": 0.0, "cheio_h": dt.datetime.now().hour,
        "hist": {"U1.INV_1.I_PV1": [(f"{HOJE}T12:00:00", 1.0)]}}
    app._sunop_str_hist_varias(["U1", "U2"], HOJE)

    assert sorted(janelas) == sorted([f"{HOJE}T11:30:00", f"{HOJE}T00:00:00"]), janelas


def test_inversor_unico_nao_usa_o_cache_do_dia():
    """Com `inv`, allp é um SUBCONJUNTO. Gravá-lo na chave (usina, dia) marcaria como completo um
    dia pela metade, e a volta seguinte fundiria em cima achando que tinha a usina inteira."""
    import inspect
    fonte = inspect.getsource(app._sunop_strings_curva)
    assert "_sunop_str_hist_do_dia" in fonte and "if inv is None" in fonte
