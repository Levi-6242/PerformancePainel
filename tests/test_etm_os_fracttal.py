"""OS de estação meteorológica nos cards do ETM (pedido Levi 26/08).

Três pontas: o FILTRO que decide se um ativo pertence ao grupo (é ele que acende o destaque
laranja), o endpoint em lote dos cards, e a paginação do histórico (10 em 10). Os nomes dos
casos positivos/negativos vieram do dump REAL do índice openwo de 26/08 — inclusive a armadilha
"Estrutura Trackers Rua Bom Jesus" (contém "tr", não pode casar) e o fato de a estação vir com
o ENDEREÇO grudado no nome ("Estação Meteorológica Estrada da Areia Branca, s/n Jacundá").
"""
import app


# ── o filtro do grupo ─────────────────────────────────────────────────────────
def test_grupo_etm_positivos_reais():
    for nome in (
        "Estação Meteorológica",
        "Estação Meteorológica Estrada da Areia Branca, s/n Jacundá",
        "Estação Meteorológica Fazenda Esperança, Zona Rural, S/N Tucano",
        "Piranômetro 1",
        "Pluviômetro 2",
        "Datalogger Campbell",
        "ETM 1",
    ):
        assert app._frac_eh_etm(nome), nome


def test_grupo_etm_negativos_reais():
    for nome in (
        "Inversor 1.4", "NCU 1", "Transformador 1", "Cabine 1", "Nobreak 1",
        "Sistema de Combate a Incêndio", "Infraestrutura Civil",
        "Estrutura Trackers Rua Bom Jesus, S/N Marabá",   # tem "Est..." mas não é estação
        "", None,
    ):
        assert not app._frac_eh_etm(nome), nome


def test_etm_dentro_de_palavra_nao_casa():
    """\\betm\\b: 'etm' como PALAVRA. Já virou backspace invisível numa camada de escape — este
    teste trava o comportamento de verdade, não a aparência do regex."""
    assert app._frac_eh_etm("ETM")
    assert not app._frac_eh_etm("Sistema NETMonitor")


# ── endpoint em lote dos cards ────────────────────────────────────────────────
def _client(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")          # app aberto no teste
    monkeypatch.setattr(app, "FRACTTAL_ON", True)
    return app.app.test_client()


def test_api_etm_os_separa_cadastrada_de_sem_cadastro(monkeypatch):
    c = _client(monkeypatch)
    monkeypatch.setattr(app, "_frac_fractall_map",
                        lambda: {"ibaté": "Thopen - Ibaté 1 - SP"})
    monkeypatch.setattr(app, "_frac_openwo_fresco", lambda: {
        app._frac_grpkey("Thopen - Ibaté 1 - SP"): [
            {"folio": "9412", "ativo": "Estação Meteorológica", "desc": "ETM sem comunicação",
             "criada": "2026-08-25", "status": "Em processo", "responsavel": "X"},
            {"folio": "9001", "ativo": "Inversor 1.2", "desc": "outra coisa",
             "criada": "2026-08-20", "status": "Em processo"},
        ]})
    r = c.post("/api/etm/os", json={"usinas": ["Ibaté", "Guatambu"]}).get_json()
    assert r["ok"]
    ib = r["por_usina"]["Ibaté"]
    assert ib["cadastrada"] is True
    assert [o["folio"] for o in ib["os"]] == ["9412"]      # só a do grupo ETM
    gu = r["por_usina"]["Guatambu"]
    assert gu == {"cadastrada": False, "os": []}           # sem Fracttal → front esconde tudo


# ── histórico paginado ────────────────────────────────────────────────────────
def test_historico_pagina_de_10_em_10(monkeypatch):
    c = _client(monkeypatch)
    monkeypatch.setattr(app, "_frac_etm_ativos", lambda u: [{"id": 77, "desc": "Estação"}])
    todas = [{"folio": str(1000 + i), "descricao": f"OS {i}", "status": "Concluída",
              "aberta": False, "criada": f"2026-{(i % 12) + 1:02d}-01"} for i in range(23)]
    monkeypatch.setattr(app, "_frac_os_de", lambda id_item, n=200: todas)
    r0 = c.get("/api/etm/os/historico?usina=Ibaté&offset=0").get_json()
    assert r0["total"] == 23 and len(r0["os"]) == 10
    r20 = c.get("/api/etm/os/historico?usina=Ibaté&offset=20").get_json()
    assert len(r20["os"]) == 3
    # ordenadas da mais recente p/ a mais antiga
    datas = [o["criada"] for o in r0["os"]]
    assert datas == sorted(datas, reverse=True)


def test_historico_usina_sem_ativo_nao_explode(monkeypatch):
    c = _client(monkeypatch)
    monkeypatch.setattr(app, "_frac_etm_ativos", lambda u: [])
    r = c.get("/api/etm/os/historico?usina=Guatambu").get_json()
    assert r["ok"] and r["sem_ativo"] and r["total"] == 0 and r["os"] == []


# ── divergência de UF entre BD e Fracttal (caso Ponto Belo, 26/08) ────────────
def test_uf_divergente_ainda_casa(monkeypatch):
    """BD diz 'Axis - Ponto Belo 1 - PE'; o Fracttal, 'axis - ponto belo 1 - ba' (a usina fica
    no ES — os DOIS estão errados, de UFs diferentes). Com casamento exato a usina inteira some
    do recurso; o fallback sem-UF resolve sem perder a unicidade (prefixo cliente+usina+número)."""
    c = _client(monkeypatch)
    monkeypatch.setattr(app, "_frac_fractall_map",
                        lambda: {"ponto belo": "Axis - Ponto Belo 1 - PE"})
    monkeypatch.setattr(app, "_frac_openwo_fresco", lambda: {
        "axis - ponto belo 1 - ba": [
            {"folio": "12086", "ativo": "Estação Meteorológica", "desc": "Conferencia de ETM",
             "criada": "2026-08-24", "status": "Em andamento"}]})
    r = c.post("/api/etm/os", json={"usinas": ["Ponto Belo"]}).get_json()
    pb = r["por_usina"]["Ponto Belo"]
    assert pb["cadastrada"] and [o["folio"] for o in pb["os"]] == ["12086"]


def test_key_semuf_nao_colide_usinas_diferentes():
    a = app._frac_key_semuf("Axis - Ponto Belo 1 - PE")
    b = app._frac_key_semuf("Axis - Ponto Belo 2 - BA")
    assert a != b, "número da usina tem de continuar diferenciando"


def test_historico_fallback_por_id_item_da_os_aberta(monkeypatch):
    """Caso TCN100 (Tucano): a carteira não segue o padrão {BASE}-ESTM{n}, mas as OS abertas do
    grupo ETM trazem o id_item do ativo — o histórico resolve por elas (e memoriza, para seguir
    acessível depois que a OS fechar)."""
    c = _client(monkeypatch)
    monkeypatch.setattr(app, "_frac_codebase", lambda u: "TCN100")
    monkeypatch.setattr(app, "_frac_ativo", lambda code: None)          # padrão ESTM falha
    monkeypatch.setattr(app, "_frac_fractall_map", lambda: {"tucano 1": "SEMP - Tucano 1 - BA"})
    monkeypatch.setattr(app, "_frac_openwo_fresco", lambda: {
        "semp - tucano 1 - ba": [
            {"folio": "11454", "ativo": "Estação Meteorológica Fazenda Esperança",
             "id_item": 999, "desc": "x", "criada": "2026-08-01", "status": "Em andamento"},
            {"folio": "11326", "ativo": "Estação Meteorológica Fazenda Esperança",
             "id_item": 999, "desc": "y", "criada": "2026-07-20", "status": "Em andamento"},
        ]})
    monkeypatch.setattr(app, "_frac_os_de",
                        lambda id_item, n=200: [{"folio": "11454", "descricao": "x", "status": "Em processo",
                                                 "aberta": True, "criada": "2026-08-01"}] if id_item == 999 else [])
    app._frac_etm_ativos._cache.clear()
    r = c.get("/api/etm/os/historico?usina=Tucano 1").get_json()
    assert r["total"] == 1 and r["os"][0]["folio"] == "11454"
    assert app._frac_etm_ativos._cache["tucano 1"] == [{"id": 999, "desc": "Estação Meteorológica Fazenda Esperança"}]


def test_os_de_converte_datas_do_fuso_e_traz_autoria(monkeypatch):
    """Os campos novos do histórico (Levi 26/08): evento, início, fim, quem criou e quando.
    O caso do teste é o que ERRA o dia sem conversão: 00:40Z do dia 25 = 21:40 LOCAL do dia 24 —
    cortar [:10] do UTC mostraria 25/08 num evento que aconteceu 24/08 aqui."""
    app._frac_os_cache.clear()
    wo = {"wo_folio": "12086", "description": "Conferencia de ETM", "id_status_work_order": 1,
          "creation_date": "2026-08-25T00:40:00+00:00",     # 24/08 21:40 local
          "event_date": "2026-08-24T14:40:35.225+00:00",    # 24/08 11:40 local
          "initial_date": None, "final_date": None, "wo_final_date": None,
          "requested_by": "Vitor Valadares", "personnel_description": "Thiago Morais "}
    monkeypatch.setattr(app, "_frac_get", lambda ep, **k: {"data": [wo]})
    os_ = app._frac_os_de(4341, n=10)
    o = os_[0]
    assert o["evento"] == "24/08/2026"
    assert o["criada_em"] == "24/08/2026 21:40"             # dia local, não o dia UTC
    assert o["criada_por"] == "Vitor Valadares"
    assert o["responsavel"] == "Thiago Morais"
    assert o["inicio"] is None and o["fim"] is None and o["aberta"] is True


def test_historico_esconde_canceladas(monkeypatch):
    """Pedido Levi 26/08: OS cancelada não aparece no histórico — e o TOTAL desconta junto,
    senão a paginação promete página que não existe."""
    c = _client(monkeypatch)
    monkeypatch.setattr(app, "_frac_etm_ativos", lambda u: [{"id": 77, "desc": "Estação"}])
    todas = [
        {"folio": "3", "descricao": "boa", "status": "Em andamento", "aberta": True, "criada": "2026-08-20"},
        {"folio": "2", "descricao": "cancelada", "status": "Cancelada", "aberta": False, "criada": "2026-08-18"},
        {"folio": "1", "descricao": "ok", "status": "Concluída", "aberta": False, "criada": "2026-08-10"},
    ]
    monkeypatch.setattr(app, "_frac_os_de", lambda id_item, n=200: todas)
    r = c.get("/api/etm/os/historico?usina=Ibaté").get_json()
    assert r["total"] == 2
    assert [o["folio"] for o in r["os"]] == ["3", "1"]


def test_etm_grupos_expoe_o_cadastro_normalizado(monkeypatch):
    """/api/etm/grupos: a régua de agrupamento dos cards é a aba Equipamentos (Levi 27/08).
    Chaves: supervisório, supervisório sem o '(id)' e display — tudo minúsculo/espaço colapsado."""
    c = _client(monkeypatch)
    monkeypatch.setattr(app, "USINA_GRUPO", {
        "Ceilandia 1.1 (89)": "Ceilândia 1", "Ceilandia 1.2 (90)": "Ceilândia 1",
        "Céu Azul I (102)": "Céu Azul", "Caicó  1.1 (224)": "Caicó",
        "Caxambu": "Caxambu"})
    monkeypatch.setattr(app, "USINA_DISPLAY", {"Céu Azul I (102)": "Céu Azul I"})
    g = c.get("/api/etm/grupos").get_json()["grupos"]
    assert g["ceilandia 1.1 (89)"] == "Ceilândia 1"
    assert g["ceilandia 1.1"] == "Ceilândia 1"          # sem o (id)
    assert g["céu azul i"] == "Céu Azul"                # pelo display
    assert g["caicó 1.1 (224)"] == "Caicó"              # espaço duplo colapsado
    assert g["caxambu"] == "Caxambu"
