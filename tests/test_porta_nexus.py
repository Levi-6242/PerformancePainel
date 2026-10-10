# -*- coding: utf-8 -*-
"""Porta única com o Nexus (09/10/2026): o passe, os perfis, o modo Nexus, o frame-ancestors e a fase 3 desligada.

Levi, 09/10/2026: "a partir de segunda quero o Nexus como link principal; o Nexus será o centro de tudo, precisamos
trazer o tempo real de performance painel para o Nexus". O Nexus abre cada tela da plataforma numa moldura; o passe
(porta_nexus.py) abre a sessão DESTA plataforma. Spec 2026-10-09-performance-no-nexus-design.md (repositório do Nexus),
seções 5.2 a 5.6 e 9. Sem a NEXUS_SSO_CHAVE nada disso existe: a plataforma sobe por push e não muda para ninguém.
"""
import pathlib
import re
import socket
import time
from html.parser import HTMLParser

import pytest

import app
import leitura_nexus as ln
import porta_nexus as pn

CHAVE = "chave-de-teste-do-passe-" + "x" * 20          # 44 caracteres, como um token_urlsafe(32)
SENHA = "senha-de-teste"
NA_MOLDURA = {"Sec-Fetch-Dest": "iframe", "Sec-Fetch-Site": "same-origin"}
_SEQ = iter(range(10 ** 9))
_SLEEP = time.sleep


@pytest.fixture(autouse=True)
def _sem_rede(monkeypatch):
    """Nada sai da máquina nestes testes (fonte paga, Fracttal, banco): só 127.0.0.1 (o gêmeo, que responde 503 quando
    não está no ar). Espera de nova tentativa encurtada para não alongar a suíte."""
    resolver_de_verdade = socket.getaddrinfo

    def resolver(host, *a, **k):
        if str(host) in ("127.0.0.1", "localhost", "::1"):
            return resolver_de_verdade(host, *a, **k)
        raise socket.gaierror("rede cortada no teste da porta do Nexus")
    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    try:
        import psycopg2

        def _sem_banco(*a, **k):
            raise psycopg2.OperationalError("rede cortada no teste da porta do Nexus")
        monkeypatch.setattr(psycopg2, "connect", _sem_banco)
    except ImportError:
        pass
    monkeypatch.setattr(time, "sleep", lambda s: _SLEEP(min(s, 0.01)))


def passe(destino="/tempo-real", email="analista@exemplo.com", admin=False, vence_em=60, chave=CHAVE, **extra):
    dados = {"v": 1, "email": email, "nome": "Pessoa de Teste", "admin": admin, "destino": destino,
             "vence": time.time() + vence_em, "numero": f"numero-de-teste-{next(_SEQ):08d}"}
    dados.update(extra)
    return pn.assinar_passe(dados, chave)


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", SENHA)
    monkeypatch.setattr(app, "NEXUS_SSO_CHAVE", CHAVE)
    monkeypatch.setattr(app, "PLATAFORMA_ANALISTAS", pn.ler_lista("analista@exemplo.com, admin@exemplo.com"))
    monkeypatch.setattr(app, "PLATAFORMA_GESTORES", pn.ler_lista("gestor@exemplo.com, gestor.admin@exemplo.com"))
    monkeypatch.setattr(app, "NEXUS_PORTA_PRINCIPAL", "")
    monkeypatch.setattr(app, "_PASSES_USADOS", pn.NumerosUsados())
    monkeypatch.setattr(app, "_MODO_WEB", True)
    monkeypatch.setitem(app.app.config, "PROPAGATE_EXCEPTIONS", False)
    return app.app.test_client()


def entrar(cli, email="analista@exemplo.com", destino="/tempo-real", admin=False):
    r = cli.post("/painel/nexus/entrar", data={"passe": passe(destino, email, admin)}, headers=NA_MOLDURA)
    assert r.status_code == 303, r.get_data(as_text=True)[:300]
    return r


def entrar_com_senha(cli):
    assert cli.post("/login", data={"senha": SENHA}).status_code == 302


# ── o mapa (spec 5.6): fonte única, cópia do Nexus ──────────────────────────────────────────────────────────────────
def test_o_mapa_e_a_copia_do_nexus():
    """O Nexus é o dono do mapa; esta é a cópia. O mesmo texto canônico (e a mesma assinatura) está no teste do Nexus:
    mudou lá, muda aqui, e os dois testes mudam juntos."""
    assert len(pn.MAPA) == 13
    assert pn.texto_canonico_do_mapa().splitlines()[0] == "performance|tempo-real|/tempo-real|/tempo-real/<fonte> /monitor|"
    assert pn.texto_canonico_do_mapa().splitlines()[-1] == "base|chaves-fontes|/tokens||admin"
    assert pn.assinatura_do_mapa() == "b80243d6133920c6"
    assert len({(t.torre, t.tela) for t in pn.MAPA}) == 13


def test_cada_caminho_cai_na_sua_tela():
    casos = {"/tempo-real": "tempo-real", "/tempo-real/athon": "tempo-real", "/monitor": "tempo-real",
             "/painel": "noc", "/painel/usina/297410": "diagnostico", "/painel/usina/ATH-12": "diagnostico",
             "/painel/falhas": "strings-trackers", "/gerencial": "gerencial",
             "/gerencial/disponibilidade": "disponibilidade", "/relatorio": "relatorio",
             "/relatorio/semanal": "relatorio-semanal", "/gemeo/": "gemeo", "/gemeo/usina/12": "gemeo",
             "/historico-plataforma": "historico-plataforma", "/ronda/monitor": "monitor-ronda", "/cos": "acompanhamento",
             "/tokens": "chaves-fontes", "/painel/usina/1?antigo=1": "diagnostico"}
    for c, tela in casos.items():
        assert getattr(pn.tela_do_caminho(c), "tela", None) == tela, c
    for c in ("/", "/login", "/painel/nexus/entrar", "/api/data", "/painel/usina/1/x", "/painelx", "/gemeo",
              "/os/", "/v2", "/monitoramento", "/tempo-real/a/b"):
        assert pn.tela_do_caminho(c) is None, c


def _amostra(regra: str) -> str:
    u = re.sub(r"<path:[^>]+>", "x/y", regra)
    return re.sub(r"<[^>]+>", "123", u)


def test_toda_rota_de_pagina_tem_lugar_no_mapa():
    """Rota de página nova (não /api, não /static) entra no MAPA ou no FORA_DO_MAPA com o porquê. Sem isso ela some do
    Nexus calada; é o `test_a_lista_cobre_as_rotas_das_paginas` da ponte, para as telas (spec 5.6)."""
    soltas, regras = [], set()
    for r in app.app.url_map.iter_rules():
        if r.rule.startswith(("/api/", "/static")):
            continue
        regras.add(r.rule)
        if r.rule in pn.FORA_DO_MAPA or pn.tela_do_caminho(_amostra(r.rule)):
            continue
        soltas.append(r.rule)
    assert not soltas, f"rotas de página sem lugar no mapa do Nexus nem no FORA_DO_MAPA: {sorted(soltas)}"
    assert not set(pn.FORA_DO_MAPA) - regras, "FORA_DO_MAPA cita rota que não existe mais"
    for t in pn.MAPA:                                     # toda tela do mapa existe na plataforma
        assert app.app.url_map.bind("localhost").test(_amostra(t.caminho), method="GET"), t.caminho


def test_destino_so_do_mapa_e_sem_redirecionamento_aberto():
    assert pn.destino_permitido("/tempo-real") == "/tempo-real"
    assert pn.destino_permitido("/monitor?fonte=pv&embed=1") == "/monitor?fonte=pv&embed=1"
    assert pn.destino_permitido("/painel/usina/297410") == "/painel/usina/297410"
    for ruim in ("//outro.site/tempo-real", "/\\outro.site", "https://outro.site/tempo-real", "tempo-real",
                 "/tempo-real#x", "/tempo-real?a=1 2", "/tempo-real\r\nX: y", "/../tempo-real", "/login",
                 "/painel/nexus/entrar", "/api/state", "", None, 123, "/" + "a" * 3000):
        assert pn.destino_permitido(ruim) is None, ruim


# ── o passe (spec 5.2) ──────────────────────────────────────────────────────────────────────────────────────────────
def _ler(p, usados=None, agora=None, chave=CHAVE):
    return pn.ler_passe(p, chave, time.time() if agora is None else agora, usados or pn.NumerosUsados())


def test_passe_valido():
    d = _ler(passe("/painel/usina/12", "Pessoa@Exemplo.com", admin=True))
    assert d == {"email": "pessoa@exemplo.com", "nome": "Pessoa de Teste", "admin": True, "destino": "/painel/usina/12"}


def test_admin_so_quando_e_verdadeiro():
    assert _ler(passe(admin="true"))["admin"] is False
    assert _ler(passe(admin=1))["admin"] is False


@pytest.mark.parametrize("como, motivo", [
    (lambda: passe(vence_em=-1), "venceu"),
    (lambda: passe(vence_em=600), "mais que 60 s"),
    (lambda: passe(chave="outra-chave-" + "y" * 30), "assinatura"),
    (lambda: (lambda c, a: pn._b64(pn._deb64(c).replace(b"analista@", b"invasora@")) + "." + a)(*passe().split(".")),
     "assinatura"),
    (lambda: passe().split(".")[0] + "." + pn._b64(b"\x00" * 32), "assinatura"),
    (lambda: passe().replace(".", ""), "formato"),
    (lambda: passe() + ".x", "formato"),
    (lambda: "!!!." + passe().split(".")[1], "formato"),
    (lambda: pn._b64(b"nao e json") + "." + pn._b64(pn._assinatura(b"nao e json", CHAVE)), "formato"),
    (lambda: passe(v=2), "versão"),
    (lambda: passe(vence="amanha"), "vence"),
    (lambda: passe(email="sem-arroba"), "quem é"),
    (lambda: passe(numero="curto"), "formato"),
    (lambda: passe("/login"), "destino"),
    (lambda: passe("//outro.site/x"), "destino"),
    (lambda: "", "não chegou"),
    (lambda: "a." + "b" * 5000, "formato"),
])
def test_passe_recusado_diz_o_motivo(como, motivo):
    with pytest.raises(pn.PasseRecusado) as e:
        _ler(como())
    assert motivo in e.value.motivo


def test_passe_de_uso_unico_e_a_lista_esquece_depois_de_2_min():
    usados = pn.NumerosUsados()
    p = passe()
    _ler(p, usados)
    with pytest.raises(pn.PasseRecusado, match="já foi usado"):
        _ler(p, usados)
    agora = time.time()
    assert usados.marcar("numero-qualquer-0001", agora)
    assert not usados.marcar("numero-qualquer-0001", agora + 119)
    assert usados.marcar("numero-qualquer-0001", agora + 250)       # o passe vale 60 s: 2 min depois já não importa


def test_passe_recusado_nao_gasta_o_numero():
    """Só passe autêntico entra na lista dos usados: sem a chave ninguém a enche (e um passe que falhou por outra razão
    não fica marcado)."""
    usados = pn.NumerosUsados()
    with pytest.raises(pn.PasseRecusado):
        _ler(passe(chave="outra-chave-" + "y" * 30, numero="numero-unico-abcdef"), usados)
    _ler(passe(numero="numero-unico-abcdef"), usados)


def test_chave_curta_desliga_a_porta():
    assert app._chave_do_passe_valida("curta") == ""
    assert app._chave_do_passe_valida(CHAVE) == CHAVE
    assert app._chave_do_passe_valida("") == ""


# ── os perfis (spec 5.3) ────────────────────────────────────────────────────────────────────────────────────────────
def test_perfis_pelas_listas():
    a, g = pn.ler_lista, pn.perfil_de
    assert a(" Um@X.com ; dois@x.com\nTRES@x.com ") == {"um@x.com", "dois@x.com", "tres@x.com"}
    assert g("um@x.com", a("um@x.com"), a("")) == "analista"
    assert g("um@x.com", a(""), a("um@x.com")) == "gestor"
    assert g("um@x.com", a("um@x.com"), a("um@x.com")) == "gestor"          # escrito nas duas: o mais restrito
    assert g("um@x.com", a("*"), a("um@x.com")) == "gestor"                # o escrito vence o *
    assert g("um@x.com", a("um@x.com"), a("*")) == "analista"
    assert g("outro@x.com", a("*"), a("um@x.com")) == "analista"
    assert g("outro@x.com", a("*"), a("*")) == "gestor"
    assert g("outro@x.com", a("um@x.com"), a("")) is None
    assert g("", a("*"), a("")) is None


# ── sem a chave: nada muda ──────────────────────────────────────────────────────────────────────────────────────────
def test_sem_chave_painel_nexus_e_404(cli, monkeypatch):
    monkeypatch.setattr(app, "NEXUS_SSO_CHAVE", "")
    for metodo in ("get", "post"):
        for c in ("/painel/nexus/entrar", "/painel/nexus/sair", "/painel/nexus/qualquer"):
            assert getattr(cli, metodo)(c, data={"passe": passe()}).status_code == 404, (metodo, c)
    assert cli.get("/api/state").status_code == 401                          # e não abriu sessão nenhuma


def test_sem_chave_nenhuma_resposta_muda(cli, monkeypatch):
    monkeypatch.setattr(app, "NEXUS_SSO_CHAVE", "")
    entrar_com_senha(cli)
    for c in ("/tempo-real", "/painel", "/login"):
        r = cli.get(c, headers=NA_MOLDURA)
        assert "Content-Security-Policy" not in r.headers, c
        assert "modo-nexus" not in r.get_data(as_text=True), c
    r = cli.get("/", headers=NA_MOLDURA)
    assert r.status_code == 200 and "Content-Security-Policy" not in r.headers     # a Entrada, como hoje


def test_sessao_do_passe_cai_quando_a_chave_sai_ou_muda(cli, monkeypatch):
    entrar(cli)
    assert cli.get("/api/state").status_code == 200
    monkeypatch.setattr(app, "NEXUS_SSO_CHAVE", "outra-chave-" + "z" * 30)
    assert cli.get("/api/state").status_code == 401                          # spec 8: trocar a chave derruba o passe
    entrar_com_senha(cli)
    assert cli.get("/api/state").status_code == 200                          # a senha não cai


# ── o passe pela rota ───────────────────────────────────────────────────────────────────────────────────────────────
def test_passe_valido_abre_a_sessao_da_plataforma_e_leva_a_tela(cli):
    assert cli.get("/api/state").status_code == 401
    r = entrar(cli, destino="/painel/usina/297410")
    assert r.headers["Location"].endswith("/painel/usina/297410")
    with cli.session_transaction() as s:
        assert s["auth"] is True and s["auth_kind"] == "nexus" and s["user"] == "analista@exemplo.com"
        assert s["perfil"] == "analista" and s["admin_nexus"] is False
        assert 12 * 3600 - 60 <= s["nexus_ate"] - time.time() <= 12 * 3600       # 12 h, não os 30 dias da senha
        assert not s.permanent                                                    # o cookie some ao fechar o navegador
    assert cli.get("/api/state").status_code == 200


@pytest.mark.parametrize("p, motivo", [
    (lambda: passe(vence_em=-5), "venceu"),
    (lambda: passe(chave="outra-chave-" + "w" * 30), "assinatura"),
    (lambda: passe("/os/"), "destino"),
    (lambda: passe("https://outro.site/"), "destino"),
])
def test_passe_recusado_nao_abre_sessao(cli, p, motivo):
    r = cli.post("/painel/nexus/entrar", data={"passe": p()}, headers=NA_MOLDURA)
    html = r.get_data(as_text=True)
    assert r.status_code == 403 and "Abra de novo pelo Nexus" in html and motivo in html
    assert "Location" not in r.headers
    assert cli.get("/api/state").status_code == 401


def test_passe_repetido_e_recusado(cli):
    p = passe()
    assert cli.post("/painel/nexus/entrar", data={"passe": p}).status_code == 303
    cli.get("/logout")
    r = cli.post("/painel/nexus/entrar", data={"passe": p})
    assert r.status_code == 403 and "já foi usado" in r.get_data(as_text=True)
    assert cli.get("/api/state").status_code == 401


def test_passe_na_url_nao_vale(cli):
    # POST, nunca na URL: o passe leva o e-mail e não pode ficar em log de proxy nem no histórico (spec 5.2)
    r = cli.post("/painel/nexus/entrar?passe=" + passe())
    assert r.status_code == 403 and "não chegou" in r.get_data(as_text=True)


def test_passe_de_outro_site_e_recusado(cli):
    r = cli.post("/painel/nexus/entrar", data={"passe": passe()}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert cli.get("/api/state").status_code == 401


def test_fora_das_listas_sem_acesso(cli):
    r = cli.post("/painel/nexus/entrar", data={"passe": passe(email="tecnico@exemplo.com")})
    html = r.get_data(as_text=True)
    assert r.status_code == 403 and "Sem acesso à Performance" in html
    assert cli.get("/api/state").status_code == 401


def test_recusa_derruba_a_sessao_de_passe_que_ja_estava_aberta(cli):
    """Caso da cópia de prova (10/10/2026): depois de um gestor, um login fora das listas via "Sem acesso" na moldura e
    seguia com a sessão do gestor. Quem entrou no Nexus agora não herda a sessão de outro; a da senha fica."""
    entrar(cli, "gestor@exemplo.com")
    assert cli.post("/painel/nexus/entrar", data={"passe": passe(email="tecnico@exemplo.com")}).status_code == 403
    assert cli.get("/api/state").status_code == 401
    entrar(cli)
    assert cli.post("/painel/nexus/entrar", data={"passe": passe(vence_em=-1)}).status_code == 403
    assert cli.get("/api/state").status_code == 401
    entrar_com_senha(cli)
    assert cli.post("/painel/nexus/entrar", data={"passe": passe(email="tecnico@exemplo.com")}).status_code == 403
    assert cli.get("/api/state").status_code == 200


def test_sair_encerra_so_a_sessao_do_passe(cli):
    entrar(cli)
    r = cli.post("/painel/nexus/sair", data={"volta": "/nexus/entrar"})
    assert r.status_code == 303 and r.headers["Location"].endswith("/nexus/entrar")
    assert cli.get("/api/state").status_code == 401
    entrar_com_senha(cli)
    assert cli.post("/painel/nexus/sair", data={"volta": "//outro.site/"}).status_code == 200    # sem redirecionar fora
    assert cli.get("/api/state").status_code == 200                          # a sessão da senha fica


def test_quem_grava_pelo_passe_fica_no_diario():
    with app.app.test_request_context("/"):
        from flask import session
        session.update({"auth": True, "auth_kind": "nexus", "user": "analista@exemplo.com"})
        assert app._quem_na_sessao() == "analista@exemplo.com"
        session.update({"auth_kind": "senha", "user": None})
        assert app._quem_na_sessao() == "senha compartilhada"


# ── perfis na prática ───────────────────────────────────────────────────────────────────────────────────────────────
def test_analista_grava(cli):
    entrar(cli)
    r = cli.post("/api/state/tracking", json={"key": "pv:1", "value": 3})
    assert r.status_code == 200, r.get_data(as_text=True)


def test_gestor_nao_grava(cli):
    entrar(cli, "gestor@exemplo.com")
    r = cli.post("/api/state/tracking", json={"key": "pv:1", "value": 3})
    assert r.status_code == 403 and r.get_json()["error"] == "somente leitura (perfil gestor)"
    for c in ln.GRAVACOES_GESTOR:
        u = c.rstrip("/") + ("/1/salvar" if c.endswith("/") else "")
        assert cli.post(u, json={}).status_code == 403, u
    assert cli.get("/api/state?force=1").status_code == 403                  # parâmetro que dispara coleta
    assert cli.get("/api/macro?backfill=1").status_code == 403
    assert cli.get("/api/plant/297410").status_code == 403                   # abre a usina na API PV na hora
    assert cli.get("/api/diagnostico/pv/297410").status_code == 403
    assert cli.get("/api/painel/correlacao/pv/297410").status_code == 403
    assert cli.get("/os/").status_code == 403                                # o OS Creator não é tela do gestor


def test_gestor_marca_o_pedido_como_so_leitura(cli):
    """O pedido do gestor leva a trava da API PV e não monta cache (o mesmo `pedido_do_nexus` da ponte)."""
    entrar(cli, "gestor@exemplo.com")
    vistos = []
    orig = app._entrada_tr_disparar

    def espia(*a, **k):
        vistos.append(ln.pedido_do_nexus())
        return orig(*a, **k)
    try:
        app._entrada_tr_disparar = espia
        cli.get("/api/entrada/tempo-real")
    finally:
        app._entrada_tr_disparar = orig
    assert vistos and all(vistos)


@pytest.mark.parametrize("tela", pn.MAPA, ids=lambda t: f"{t.torre}-{t.tela}")
def test_gestor_le_cada_tela_do_mapa(cli, tela):
    entrar(cli, "gestor.admin@exemplo.com", admin=True)
    r = cli.get(_amostra(tela.caminho), headers=NA_MOLDURA)
    # o gêmeo é outro processo (503 quando não está no ar nesta máquina): o que importa é a porta não barrar
    assert r.status_code in (200, 503), (tela.caminho, r.status_code)
    if r.status_code == 200 and tela.tela != "gemeo":
        assert re.search(r'<html[^>]*class="[^"]*modo-nexus', r.get_data(as_text=True)), tela.caminho


def test_gestor_le_as_apis_das_telas(cli, monkeypatch):
    monkeypatch.setattr(app, "FRACTTAL_ON", False)                            # a consulta não vai ao Fracttal no teste
    entrar(cli, "gestor.admin@exemplo.com", admin=True)
    for c in ("/api/state", "/api/cos/mtta", "/api/gerencial/disponibilidade", "/api/painel/falhas",
              "/api/painel/falhas/desconsideradas", "/api/relatorio/usinas", "/api/ronda/recorrentes",
              "/api/ronda/obs", "/api/tokens", "/api/notificacoes", "/api/entrada/tempo-real"):
        assert cli.get(c).status_code != 403, c
    assert cli.post("/api/fracttal/os", json={"usina": "x"}).status_code != 403          # consulta por POST


# As páginas das telas do mapa (os templates delas, a Entrada e o Monitoramento do Tempo real e o sino).
RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
TEMPLATES_DAS_TELAS = sorted(p for p in (RAIZ / "plataforma" / "templates").glob("*.html") if p.name != "nexus_aviso.html")
PAGINAS_DAS_TELAS = TEMPLATES_DAS_TELAS + [RAIZ / "docs" / "redesign" / "Entrada.html",
                                          RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html",
                                          RAIZ / "plataforma" / "static" / "notif.js"]


def test_a_lista_do_gestor_cobre_as_rotas_das_telas():
    """Rota nova numa tela do mapa precisa ser classificada para o gestor: leitura (entra em `_GET_GESTOR`), consulta
    por POST (`POSTS_DE_CONSULTA_GESTOR`) ou gravação (`GRAVACOES_GESTOR`). Sem isso, a tela abre pela metade para o
    gestor, calada."""
    soltas = set()
    for p in PAGINAS_DAS_TELAS:
        for rota in re.findall(r"(?<![\w])/api/[A-Za-z0-9_\-/]+", p.read_text(encoding="utf-8")):
            rota = rota.rstrip("/")
            if rota == "/api":
                continue                                     # '/api/'+f+... : coberto pelas FONTES_API
            if ln.permitido_gestor("GET", rota) or ln.permitido_gestor("POST", rota):
                continue
            if any(rota == g.rstrip("/") or rota.startswith(g) for g in ln.GRAVACOES_GESTOR):
                continue
            if any(r.match(rota) or r.match(rota + "/") for r in ln.NEGADOS_API_PV_GESTOR):
                continue                                     # abre a usina na API PV na hora: fora de propósito
            soltas.add(f"{rota} ({p.name})")
    assert not soltas, f"rotas das telas fora da lista do gestor: {sorted(soltas)}"


def test_a_ponte_segue_com_a_lista_dela():
    """A chave X-Nexus-Leitura (ponte de 04/10) não ganha nada com o gestor: a lista dela é a de antes."""
    assert not ln.permitido("GET", "/painel") and not ln.permitido("GET", "/api/cos/mtta")
    assert ln.permitido_gestor("GET", "/painel") and ln.permitido_gestor("GET", "/api/cos/mtta")


def test_tokens_so_admin_do_nexus(cli):
    entrar(cli, "analista@exemplo.com", admin=False)
    r = cli.get("/tokens", headers=NA_MOLDURA)
    assert r.status_code == 403 and "Só administradores do Nexus" in r.get_data(as_text=True)
    assert cli.get("/api/tokens").status_code == 403
    assert cli.post("/api/tokens/sunop", json={"token": "x"}).status_code == 403
    cli.get("/logout")
    entrar(cli, "admin@exemplo.com", admin=True, destino="/tokens")
    assert cli.get("/tokens", headers=NA_MOLDURA).status_code == 200
    assert cli.get("/api/tokens").status_code == 200
    cli.get("/logout")
    entrar_com_senha(cli)
    assert cli.get("/tokens").status_code == 200                             # a senha segue como hoje


def test_sessao_do_passe_vence_em_12_horas(cli):
    entrar(cli)
    with cli.session_transaction() as s:
        s["nexus_ate"] = int(time.time()) - 1
    assert cli.get("/api/state").status_code == 401


# ── o modo Nexus (spec 5.4) ─────────────────────────────────────────────────────────────────────────────────────────
def test_modo_nexus_so_com_a_sessao_do_passe_dentro_da_moldura(cli):
    entrar(cli)
    dentro = cli.get("/painel", headers=NA_MOLDURA).get_data(as_text=True)
    assert re.search(r'<html[^>]*class="[^"]*modo-nexus', dentro)
    assert "html.modo-nexus [data-casca]{display:none!important}" in dentro
    assert "tipo:'nexus:rota'" in dentro and "location.origin" in dentro
    fora = cli.get("/painel").get_data(as_text=True)                          # aba solta, sem moldura
    assert "modo-nexus" not in fora
    cli.get("/logout")
    entrar_com_senha(cli)
    senha = cli.get("/painel", headers=NA_MOLDURA).get_data(as_text=True)     # a senha dentro de um iframe qualquer
    assert "modo-nexus" not in senha


def test_modo_nexus_nao_dobra_e_respeita_class_que_ja_existe():
    from flask import Response, session
    with app.app.test_request_context("/x", headers=NA_MOLDURA):
        session.update({"auth": True, "auth_kind": "nexus"})
        old = app.NEXUS_SSO_CHAVE
        app.NEXUS_SSO_CHAVE = CHAVE
        try:
            r = app._porta_do_nexus_na_resposta(Response('<!doctype html><html lang="pt" class="dark"><head></head>'
                                                         "<body></body></html>", mimetype="text/html"))
            html = r.get_data(as_text=True)
            assert '<html lang="pt" class="dark modo-nexus">' in html and html.count("nexus:rota") == 1
            frag = app._porta_do_nexus_na_resposta(Response("<div>fragmento</div>", mimetype="text/html"))
            assert "nexus:rota" not in frag.get_data(as_text=True)              # fragmento não é página
        finally:
            app.NEXUS_SSO_CHAVE = old


def test_barra_na_moldura_leva_ao_tempo_real(cli):
    entrar(cli)
    r = cli.get("/", headers=NA_MOLDURA)
    assert r.status_code == 302 and r.headers["Location"].endswith("/tempo-real")
    assert cli.get("/").status_code == 200                                    # fora da moldura, a Entrada (fase 3 off)


def test_moldura_sem_sessao_manda_abrir_pelo_nexus(cli):
    r = cli.get("/painel", headers=NA_MOLDURA)
    assert r.status_code == 401 and "Abra de novo pelo Nexus" in r.get_data(as_text=True)
    r = cli.get("/painel")                                                     # aba solta: o login de sempre
    assert r.status_code == 302 and "/login?next=" in r.headers["Location"]


_LINK_PARA_A_ENTRADA = re.compile(r"<a\b[^>]*\bhref=[\"']/[\"'][^>]*>")


class _LinksParaAEntrada(HTMLParser):
    """Acha os <a href="/"> fora de um elemento `data-casca` (o próprio link marcado também vale). Dentro de <script>
    (a barra do Monitoramento é montada por JavaScript) o link precisa levar a marca na própria tag."""
    VAZIOS = {"img", "br", "hr", "input", "meta", "link", "source", "wbr", "col", "area", "base", "embed", "track"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.casca = []                                 # [tag, profundidade] do elemento data-casca aberto
        self.soltos = []
        self.em_script = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script":
            self.em_script = True
        if self.casca and tag == self.casca[-1][0]:
            self.casca[-1][1] += 1
        if tag == "a" and a.get("href") == "/" and not self.casca and "data-casca" not in a:
            self.soltos.append((self.get_starttag_text() or "")[:90])
        if "data-casca" in a and not self.casca and tag not in self.VAZIOS:
            self.casca.append([tag, 1])

    def handle_endtag(self, tag):
        if tag == "script":
            self.em_script = False
        if self.casca and tag == self.casca[-1][0]:
            self.casca[-1][1] -= 1
            if not self.casca[-1][1]:
                self.casca.pop()

    def handle_data(self, data):
        if self.em_script:
            self.soltos += [t[:90] for t in _LINK_PARA_A_ENTRADA.findall(data) if "data-casca" not in t]


def test_toda_pagina_com_link_para_a_entrada_o_marca_como_casca():
    """O que leva à Entrada da plataforma (o "← Início", o "‹ Entrada", a marca) é navegação da plataforma: dentro do
    Nexus quem faz esse papel é o menu dele, e o `data-casca` some em modo Nexus (spec 5.4)."""
    soltos = []
    for p in PAGINAS_DAS_TELAS[:-1]:
        leitor = _LinksParaAEntrada()
        leitor.feed(p.read_text(encoding="utf-8"))
        soltos += [f"{p.name}: {s}" for s in leitor.soltos]
    assert not soltos, soltos


# ── frame-ancestors (spec 5.4) ──────────────────────────────────────────────────────────────────────────────────────
def test_frame_ancestors_em_toda_resposta_html(cli):
    def confere(r, c):
        if (r.content_type or "").startswith("text/html"):
            assert "frame-ancestors 'self'" in r.headers.get("Content-Security-Policy", ""), c
        else:
            assert "Content-Security-Policy" not in r.headers, c
    for c in ("/login", "/painel", "/rota-que-nao-existe", "/api/state"):
        confere(cli.get(c), c)                                                    # sem sessão (redirect, 404, 401)
    confere(cli.post("/painel/nexus/entrar", data={"passe": "x"}), "passe ruim")
    entrar_com_senha(cli)
    for t in pn.MAPA:
        c = _amostra(t.caminho)
        confere(cli.get(c), c)
    for c in ("/", "/monitor?fonte=pv&embed=1", "/tempo-real/athon", "/api/state"):
        confere(cli.get(c), c)


# ── fase 3: o "/" leva ao Nexus (desligada por padrão) ──────────────────────────────────────────────────────────────
def test_fase3_desligada_o_barra_segue_a_entrada(cli):
    r = cli.get("/")
    assert r.status_code == 302 and "/login?next=" in r.headers["Location"]  # como hoje
    assert "Entrar pelo Nexus" not in cli.get("/login").get_data(as_text=True)


def test_fase3_ligada(cli, monkeypatch):
    monkeypatch.setattr(app, "NEXUS_PORTA_PRINCIPAL", "/nexus/")
    r = cli.get("/")
    assert r.status_code == 302 and r.headers["Location"] == "/nexus/"       # sem login, direto ao Nexus
    login = cli.get("/login").get_data(as_text=True)
    assert 'href="/nexus/" class="nexbtn">Entrar pelo Nexus' in login and 'name="senha"' in login
    entrar_com_senha(cli)
    assert cli.get("/").headers["Location"] == "/nexus/"                       # a senha também cai no Nexus
    assert cli.get("/tempo-real").status_code == 200                          # e o resto segue igual
    cli.get("/logout")
    entrar(cli)
    r = cli.get("/", headers=NA_MOLDURA)                                       # dentro da moldura: nunca o Nexus no Nexus
    assert r.headers["Location"].endswith("/tempo-real")


def test_fase3_valor_invalido_desliga():
    v = app._porta_principal_valida
    assert v("/nexus/") == "/nexus/" and v("https://exemplo.com/nexus/") == "https://exemplo.com/nexus/"
    assert v("http://127.0.0.1:5070/") == "http://127.0.0.1:5070/"
    for ruim in ("//outro.site", "javascript:alert(1)", '/nexus/"><script>', "nexus", " / nexus", "ftp://x"):
        assert v(ruim) == "", ruim


# ── revisão adversarial da porta (10/10/2026) ───────────────────────────────────────────────────────────────────────
# Cada teste abaixo falhava no código de 09/10 e passa com a correção (o caso que o motivou está no nome).
_ADMINISTRACAO = (("POST", "/api/admin/base/bd_performance"), ("GET", "/api/admin/bases"),
                  ("POST", "/api/ronda/whats/testar"), ("POST", "/api/ronda/whats/reiniciar"),
                  ("GET", "/api/ronda/whats/grupos"))


def test_administracao_da_plataforma_so_para_admin_do_nexus(cli):
    """Revisão de 10/10: só /tokens era "só admin". Com PLATAFORMA_ANALISTAS=* qualquer conta do Fracttal trocava o
    BD_Performance do espelho do servidor (/api/admin/base), lia os caminhos do servidor (/api/admin/bases), mandava a
    ronda pelo chip da empresa a qualquer número (/api/ronda/whats/testar) ou derrubava o serviço do WhatsApp
    (/api/ronda/whats/reiniciar). Spec 5.3: administração é só do admin do Nexus. O portão recusa ANTES do handler:
    nada é gravado nem enviado neste teste."""
    for metodo, c in _ADMINISTRACAO:
        assert pn.so_admin(c), c
    assert not pn.so_admin("/api/ronda/whats/status") and not pn.so_admin("/api/ronda/whats/qr")   # o Monitor lê
    assert not pn.so_admin("/api/administrativo")                                  # prefixo é por segmento
    entrar(cli, "analista@exemplo.com", admin=False)
    for metodo, c in _ADMINISTRACAO:
        r = cli.open(c, method=metodo, data=b"x" * 2048)
        assert r.status_code == 403 and r.get_json()["error"] == "só administradores do Nexus", (metodo, c)
    cli.get("/logout")
    entrar(cli, "admin@exemplo.com", admin=True)
    assert cli.get("/api/admin/bases").status_code == 200                           # o admin do Nexus passa
    cli.get("/logout")
    entrar_com_senha(cli)
    assert cli.get("/api/admin/bases").status_code == 200                           # a senha segue como hoje
