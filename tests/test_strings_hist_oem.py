"""Histórico de strings (dia passado) nas usinas da 2ª conta da API PV — a conta OEM.

O caso real, medido em 01/09/2026: UFV Tucano (18758732) e MORADA NOVA (18766373) não carregavam
o histórico de strings de dias anteriores. O dado EXISTE — o `trygenerate` da PV Plataforma devolve
20 strings por inversor para 31/08 —, mas `_spv_inversores_hist` monta a lista de inversores pelo
`/plant_devices`, e esse endpoint responde:

    token OEM        -> HTTP 200 {"message":"Invalid permission, incident will be reported."}
    token principal  -> HTTP 401 {"error":"Invalid id, incident will be reported"}

Sem lista, o laço que buscaria as curvas nunca roda e a tela fica vazia. A usina de controle
(Indaiatuba, 21480) devolve 16 devices normalmente — o caminho só falha nas duas OEM.

A saída é a MESMA que a tela de HOJE já usa nessas usinas: ids pelo `day_inverter` (que a conta OEM
pode chamar) e nome casado por ORDEM com o cadastro. Aqui essa regra vira função única, para as
duas telas não divergirem.
"""
import app


# ── a regra de nomeação, isolada ──────────────────────────────────────────────
def test_nomes_por_ordem_casa_quando_a_quantidade_bate(monkeypatch):
    # cadastro com 3 inversores, day_inverter com os mesmos 3 ids → casa 1 a 1, em ordem
    monkeypatch.setitem(app.EQUIP_NAMES, "USINA TESTE",
                        {"Inversor 1.2": "Inv 1.2", "Inversor 1.1": "Inv 1.1",
                         "Inversor 1.3": "Inv 1.3"})
    nomes = app._pv_nomes_por_ordem("USINA TESTE", [378312, 378310, 378311])
    assert nomes == {378310: "Inversor 1.1", 378311: "Inversor 1.2", 378312: "Inversor 1.3"}


def test_nomes_por_ordem_desiste_quando_a_quantidade_diverge(monkeypatch):
    # 2 no cadastro, 3 com leitura: casar por ordem produziria nome ERRADO em silêncio, e o front
    # casa a curva pelo NOME — então a regra desiste e devolve vazio (o id cru é usado depois).
    monkeypatch.setitem(app.EQUIP_NAMES, "USINA TESTE",
                        {"Inversor 1.1": "Inv 1.1", "Inversor 1.2": "Inv 1.2"})
    assert app._pv_nomes_por_ordem("USINA TESTE", [1, 2, 3]) == {}


def test_nomes_por_ordem_sem_cadastro_devolve_vazio():
    assert app._pv_nomes_por_ordem("USINA QUE NAO EXISTE", [1, 2]) == {}


def test_nomes_por_ordem_ordena_por_tamanho_depois_texto(monkeypatch):
    # mesma chave de ordenação do caminho de hoje: (len(str(x)), str(x)). Ordenar como texto puro
    # poria "1000" antes de "999" e trocaria os nomes de lugar.
    monkeypatch.setitem(app.EQUIP_NAMES, "U", {"A": "a", "B": "b"})
    assert app._pv_nomes_por_ordem("U", [1000, 999]) == {999: "A", 1000: "B"}


# ── o fallback de fato ────────────────────────────────────────────────────────
def _sem_plant_devices(monkeypatch):
    """A conta OEM: /plant_devices não devolve nada."""
    monkeypatch.setattr(app, "_pv_devices_map", lambda idusina, token: {})


def test_hist_cai_para_o_day_inverter_quando_plant_devices_nega(monkeypatch):
    # é o caso da Tucano: plant_devices negado, mas o day_inverter de hoje traz os 4 inversores
    _sem_plant_devices(monkeypatch)
    monkeypatch.setattr(app, "_pv_ids_do_dia",
                        lambda idusina, token: [378310, 378311, 378312, 378313])
    # o cadastro mapeia nome da API -> nome de exibição, e é o de EXIBIÇÃO que sai daqui — igual
    # ao caminho de hoje, que resolve `display = mapa.get(api_nome_orig, api_nome_orig)`. Os dois
    # precisam bater: o front casa a curva com o drill pelo NOME.
    monkeypatch.setitem(app.EQUIP_NAMES, "UFV Tucano 1",
                        {"Inversor 1.1": "Inv 1.1", "Inversor 1.2": "Inv 1.2",
                         "Inversor 1.3": "Inv 1.3", "Inversor 1.4": "Inv 1.4"})
    monkeypatch.setattr(app, "_spv_inv_hist_cache", {})
    invs = app._spv_inversores_hist(18758732, "tok", "UFV Tucano 1")
    assert [i for i, _ in invs] == [378310, 378311, 378312, 378313]
    assert [n for _, n in invs] == ["Inv 1.1", "Inv 1.2", "Inv 1.3", "Inv 1.4"]


def test_hist_sem_cadastro_ainda_devolve_os_inversores(monkeypatch):
    # Sem cadastro não há nome, mas a lista NÃO pode vir vazia: sem id não há curva nenhuma.
    # O nome cru serve — o front casa pelo nome, e id cru é melhor que tela em branco.
    _sem_plant_devices(monkeypatch)
    monkeypatch.setattr(app, "_pv_ids_do_dia", lambda idusina, token: [378310, 378311])
    monkeypatch.setattr(app, "_spv_inv_hist_cache", {})
    invs = app._spv_inversores_hist(18758732, "tok", "USINA SEM CADASTRO")
    assert [i for i, _ in invs] == [378310, 378311]
    assert all(n for _, n in invs)          # algum nome, nunca vazio


def test_hist_usa_o_cache_quando_a_usina_nao_reportou_hoje(monkeypatch):
    # é o caso da MORADA NOVA, medido em 01/09: day_inverter devolveu 0 registros hoje. Sem cache,
    # a usina ficaria sem histórico justamente no dia em que ela mais precisa dele.
    _sem_plant_devices(monkeypatch)
    monkeypatch.setattr(app, "_pv_ids_do_dia", lambda idusina, token: [])
    monkeypatch.setattr(app, "_spv_inv_hist_cache",
                        {18766373: [(1, "Inversor 1.1"), (2, "Inversor 1.2")]})
    invs = app._spv_inversores_hist(18766373, "tok", "MORADA NOVA")
    assert invs == [(1, "Inversor 1.1"), (2, "Inversor 1.2")]


def test_hist_grava_no_cache_o_que_deu_certo(monkeypatch):
    _sem_plant_devices(monkeypatch)
    monkeypatch.setattr(app, "_pv_ids_do_dia", lambda idusina, token: [9, 8])
    cache = {}
    monkeypatch.setattr(app, "_spv_inv_hist_cache", cache)
    app._spv_inversores_hist(18758732, "tok", "SEM CADASTRO")
    assert [i for i, _ in cache.get(18758732, [])] == [8, 9]


def test_hist_nao_mexe_no_caminho_das_usinas_normais(monkeypatch):
    # regressão: onde o plant_devices responde (a esmagadora maioria), nada muda — o fallback
    # nem é consultado. Se o day_inverter fosse chamado aqui, seria uma requisição por usina a mais.
    monkeypatch.setattr(app, "_pv_devices_map",
                        lambda idusina, token: {43468: "INVERSOR 1.3", 999: "medidor"})

    def _nao_deve_ser_chamado(idusina, token):
        raise AssertionError("day_inverter não deve ser chamado quando plant_devices respondeu")

    monkeypatch.setattr(app, "_pv_ids_do_dia", _nao_deve_ser_chamado)
    monkeypatch.setattr(app, "_spv_inv_hist_cache", {})
    # nome de usina sem cadastro de propósito: o filtro "só quem está no cadastro" é regra ANTIGA
    # e não é o que este teste mede — aqui se mede que o fallback não entra em ação.
    invs = app._spv_inversores_hist(21480, "tok", "USINA SEM CADASTRO")
    assert invs == [(43468, "INVERSOR 1.3")]      # "medidor" não é inversor → fora
