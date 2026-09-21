# -*- coding: utf-8 -*-
"""ETM e trackers das usinas da 2C que estão na PV Operation (Levi, 16/09/2026):
"para as usinas da 2C que estão na PV Operation, não está aparecendo ETM nem trackers, resolva!"

Eram DUAS causas diferentes, e nenhuma era falta de dado:

**ETM — o backend sempre esteve certo; faltava o chip.** `/api/2capi/etm/analise` já devolvia as três
usinas com GHI e POA "ok" (picos de 954, 1031 e 1130 W/m²) e curva completa, no MESMO formato da SEMP.
Só que a barra de fontes do Monitoramento (`srcDefs`) tinha 8 chips e nenhum era o `2capi` — a fonte
existia inteira no backend (rotas, EP.etm, SKEY, VKEY, PLANT, _srcNome) e **não havia onde clicar**.
Escolher "2C" caía na fonte do e-mail (`owen`). Mesmo padrão do bug da SEMP em 15/09: backend pronto,
front sem porta de entrada.

**Trackers — `/api/2capi/trackers` devolvia 404.** Em 15/09 deixei as três de fora de propósito, para
o mesmo tracker não abrir ocorrência em duas fontes (elas vinham pelo e-mail). O Levi agora pediu na
fonte da PV, o que decide a dúvida que ficou em aberto: a PV Plataforma responde ARA 59, STL 59 e
TUP 100 com leitura do minuto, contra um e-mail que chega horas depois.

**Por que a fonte NÃO entra em `_build_pv_trk_payload`:** aquela varredura é a da conta principal e
alimenta o livro de ocorrências (`tracker_watch`). Pôr as 2C lá poluiria a aba da Thopen-PV com usina
de outro cliente E duplicaria a ocorrência que o e-mail já abre. Por isso `_pv_trk_payload_da_fonte`
passou a CONSTRUIR o payload só com as usinas da fonte, em vez de recortar o global."""
import app


def test_rotas_de_tracker_da_2capi_existem():
    """As quatro que o Monitoramento deriva de `EP.trackers['2capi']` — a lição de 15/09: criar só a
    lista faz a tela mostrar os trackers e tudo que se clica dar 404."""
    regras = {str(r) for r in app.app.url_map.iter_rules()}
    for rota in ("/api/2capi/trackers",
                 "/api/2capi/trackers/<int:idusina>",
                 "/api/2capi/trackers/<int:idusina>/chart",
                 "/api/2capi/trackers/<int:idusina>/chart.csv"):
        assert rota in regras, f"o front deriva {rota} e ela não existe"


def test_payload_da_fonte_constroi_so_as_usinas_dela(monkeypatch):
    """Constrói a partir das usinas DA FONTE — não recorta o payload global, que exclui as 2C
    de propósito. Com o recorte antigo, `/api/2capi/trackers` devolveria SEMPRE vazio."""
    vistos = []

    def _falso(idusina, nome, **kw):
        vistos.append(idusina)
        return {"plant_id": idusina, "usina": nome, "tem_trackers": True, "total": 59,
                "severos": 1, "leves": 0, "parados": 0}

    monkeypatch.setattr(app, "_pv_trackers_analise", _falso)
    monkeypatch.setattr(app, "_plat_token", lambda: "x")
    app._pv_trk_fonte_cache.pop("2capi", None)
    out = app._pv_trk_payload_da_fonte("2capi")
    assert sorted(vistos) == sorted(app.PV_FONTES["2capi"]), "tem de varrer as três da fonte"
    assert out["summary"]["usinas"] == 3
    assert out["summary"]["trackers"] == 177          # 59 × 3
    assert out["summary"]["severos"] == 3


def test_linha_leva_o_NOME_da_usina_nao_o_id(monkeypatch):
    """Bug meu na 1ª versão: `nome_usina(pid, str(pid))` usa o id como fallback, então a tela
    listava "18771901" no lugar de "Sete Lagoas". O nome tem de vir do nome da API (get_plants),
    passando pelo de-para do cadastro como a varredura global já fazia."""
    monkeypatch.setattr(app, "get_token", lambda *a, **k: "t")
    monkeypatch.setattr(app, "get_plants", lambda *a, **k: [
        {"id": 18771898, "nome": "Araputanga"}, {"id": 18771901, "nome": "Sete Lagoa"},
        {"id": 18750925, "nome": "Tupi Paulista"}])
    monkeypatch.setattr(app, "_pv_trackers_analise",
                        lambda idusina, nome, **kw: {"plant_id": idusina, "usina": nome,
                                                     "tem_trackers": True, "total": 1})
    app._pv_trk_fonte_cache.pop("2capi", None)
    nomes = {r["usina"] for r in app._pv_trk_payload_da_fonte("2capi")["rows"]}
    assert not any(str(n).isdigit() for n in nomes), f"linha com id no lugar do nome: {nomes}"
    assert "Sete Lagoas" in nomes, "e o de-para do cadastro vale (API diz 'Sete Lagoa', singular)"


def test_2c_da_api_segue_fora_da_varredura_da_conta_principal():
    """A aba "API PV" é da conta principal e alimenta o livro de ocorrências. As três da 2C ficam
    fora dela para não duplicar a ocorrência que o e-mail (`owen`) já abre."""
    for pid in app.PV_FONTES["2capi"]:
        assert app._pv_trk_fora(pid) is True


def test_trackers_da_fonte_2c_usam_a_api_para_quem_esta_nela(monkeypatch):
    """O CONSERTO CERTO. A aba separada "2C · API PV" saiu do seletor em 11/09 a pedido do Levi
    ("eu quero no tempo real, tudo junto") — então quem tem de mostrar o tracker da PV é a fonte
    `2c` UNIFICADA, não um chip novo. O ETM dela já unificava (`_2c_unifica_rows` na
    `/api/owen/etm/analise`); os trackers não, e por isso as três apareciam com a leitura do e-mail
    (11:59) enquanto a PV Plataforma já tinha a das 14:56. A Ipixuna, que não está na API,
    continua vindo do e-mail."""
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    monkeypatch.setattr(app, "_owen_trackers_analise",
                        lambda u, **kw: {"usina": app._owen_nome(u), "plant_id": u, "total": 10,
                                         "parados": 0, "severos": 0, "leves": 0, "medios": 0,
                                         "ultima_leitura": "2026-09-16 11:59", "trackers": []})
    monkeypatch.setattr(app, "_owen_disp_hoje", lambda: {})
    monkeypatch.setattr(app, "_pv_trk_payload_da_fonte", lambda *a, **k: {"rows": [
        {"usina": "Araputanga", "plant_id": 18771898, "total": 59, "parados": 0, "severos": 1,
         "leves": 0, "ultima_leitura": "2026-09-16 14:54"},
        {"usina": "Sete Lagoas", "plant_id": 18771901, "total": 59, "parados": 0, "severos": 2,
         "leves": 0, "ultima_leitura": "2026-09-16 14:53"},
        {"usina": "Tupi Paulista", "plant_id": 18750925, "total": 100, "parados": 0, "severos": 2,
         "leves": 0, "ultima_leitura": "2026-09-16 14:56"}]})
    d = app.app.test_client().get("/api/owen/trackers").get_json()
    por = {r["usina"]: r for r in d["rows"]}
    assert set(por) == {"Araputanga", "Sete Lagoas", "Tupi Paulista", "Ipixuna do Pará"}
    for u, n in (("Araputanga", 59), ("Sete Lagoas", 59), ("Tupi Paulista", 100)):
        assert por[u]["sub_fonte"] == "api", f"{u} tem de vir da API PV"
        assert por[u]["total"] == n and por[u]["ultima_leitura"].endswith(("14:53", "14:54", "14:56"))
    assert por["Ipixuna do Pará"]["sub_fonte"] == "email"    # não está na API — segue pelo e-mail


def test_nao_recriar_a_aba_separada_da_2c():
    """Trava de regressão: o chip "2C · API PV" saiu do seletor de propósito em 11/09/2026. Eu mesmo
    o recriei em 16/09 tentando resolver este chamado, e foi o teste da unificação que pegou."""
    import pathlib
    MON = (pathlib.Path(app.__file__).resolve().parents[1] / "docs" / "redesign" /
           "Monitoramento (novo design).html").read_text(encoding="utf-8")
    assert "id:'2capi'" not in MON, "a aba separada da 2C voltou ao seletor"


def test_raiox_da_2capi_pede_trackers():
    import pathlib
    PORT = (pathlib.Path(app.__file__).resolve().parents[1] / "plataforma" / "templates" /
            "painel_portfolio.html").read_text(encoding="utf-8")
    bloco = PORT.split("'2capi':")[1][:400]
    assert "trk:" in bloco, "o Raio-X da fonte 2capi não busca trackers"


def test_detalhe_e_curva_da_fonte_unificada_atendem_as_usinas_que_vem_da_api_pv(monkeypatch):
    """18/09/2026, o Levi: "as usinas da 2C que vêm da API PV mesmo lendo os trackers não estão
    carregando as curvas".

    Medido antes da correção, com o app no ar: `/api/owen/trackers/<id>` e `/chart` devolviam
    **0 trackers** para Araputanga (18771898), Sete Lagoas (18771901) e Tupi (18750925), enquanto a
    Ipixuna (id 'IPX', que vem do acervo de e-mail) devolvia 122 e a rota `/api/2capi/trackers/<id>`
    — a mesma implementação da API PV — devolvia 59, 59 e 100.

    A causa é a metade que faltou: em 15/09 eu unifiquei a LISTA (`api_owen_trackers` passou a juntar
    `_pv_trk_payload_da_fonte('2capi')`), mas o detalhe e a curva continuaram lendo só o acervo de
    e-mail, que não conhece id numérico. É o MESMO erro que eu tinha acabado de travar com teste para
    a SEMP: criar a lista sem as derivadas faz a tela mostrar a usina e o clique não trazer nada."""
    chamadas = {"pv_plant": [], "pv_chart": [], "email_build": []}
    monkeypatch.setattr(app, "api_pv_trackers_plant", lambda i: chamadas["pv_plant"].append(int(i)) or {"trackers": [1] * 59})
    monkeypatch.setattr(app, "api_pv_trackers_chart", lambda i: chamadas["pv_chart"].append(int(i)) or {"trackers": [1] * 59})
    monkeypatch.setattr(app, "_owen_trackers_analise", lambda p, **kw: chamadas["email_build"].append(p) or {"trackers": []})

    da_pv = sorted(app.PV_FONTES.get("2capi") or ())
    assert da_pv, "a fonte 2capi precisa ter usinas para este teste valer"

    with app.app.test_request_context():
        for ident in da_pv:
            app.api_owen_trackers_plant(str(ident))
            app.api_owen_trackers_chart(str(ident))

    assert chamadas["pv_plant"] == da_pv, f"detalhe não delegou para a API PV: {chamadas}"
    assert chamadas["pv_chart"] == da_pv, f"curva não delegou para a API PV: {chamadas}"
    assert not chamadas["email_build"], "id da API PV não pode cair no acervo de e-mail"


def test_usina_do_acervo_de_email_continua_indo_para_o_acervo(monkeypatch):
    """A Ipixuna ('IPX') não tem id numérico e é a única que o e-mail ainda serve — a delegação não
    pode roubá-la. Foi o que quase aconteceu ao testar com id: um `int()` cru levantaria ValueError."""
    chamadas = {"pv": [], "email": []}
    monkeypatch.setattr(app, "api_pv_trackers_plant", lambda i: chamadas["pv"].append(i) or {"trackers": []})
    monkeypatch.setattr(app, "_owen_trackers_analise", lambda p, **kw: chamadas["email"].append(p) or {"trackers": [1] * 122})
    with app.app.test_request_context():
        app.api_owen_trackers_plant("IPX")
    assert chamadas["email"] == ["IPX"] and not chamadas["pv"]
