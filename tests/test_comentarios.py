# -*- coding: utf-8 -*-
"""Comentários (03/11/2026): o autor vem da sessão, o apagar é do próprio, e a tela Comentários.

Levi, 03/11/2026: "Gostaria de um sistema mais sofisticado de comentários! Ao comentar em tempo real não precisar digitar
o nome, já puxa automático. Ter um campo na performance de Comentários."

O que se prova:
1. a regra pura (`plataforma/comentarios.py`): quem tem identidade, o autor, quem apaga, a conversa sem e-mail, a lista
   com a usina pelo nome e os filtros (busca, usina, autor, período);
2. as rotas: com o passe do Nexus o autor é o da SESSÃO (o nick do corpo é ignorado) e o e-mail fica só no arquivo; pela
   senha o nick é obrigatório, como antes; apagar o de outro = 403 (o admin do Nexus apaga); a senha apaga como antes; o
   gestor lê a tela e não escreve; o desligamento, a OS atribuída e o "Quem está fechando" dos tickets também pegam o nome
   da sessão; o `window.gcEu` da página;
3. a tela `/painel/comentarios` no node (a lista, o "Comentando como", o campo de nome sem identidade, o texto escapado) e
   o modal do Tempo real (o "Seu nome" some com identidade);
4. a porta: a tela no mapa e o gestor alcançando a leitura dela.
"""
import json
import pathlib
import re
import shutil
import socket
import subprocess
import time

import pytest

import app
import comentarios as cm
import leitura_nexus as ln
import porta_nexus as pn

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
NODE = shutil.which("node")
CHAVE = "chave-de-teste-do-passe-" + "x" * 20
SENHA = "senha-de-teste"
NA_MOLDURA = {"Sec-Fetch-Dest": "iframe", "Sec-Fetch-Site": "same-origin"}
_SEQ = iter(range(10 ** 9))


# ── 1. a regra pura ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_identidade_so_com_o_passe_ou_o_microsoft():
    nexus = {"auth": True, "auth_kind": "nexus", "user": "Ana@Exemplo.com", "nome": "  Ana   Lima ", "admin_nexus": False}
    assert cm.identidade(nexus) == {"nome": "Ana Lima", "email": "ana@exemplo.com", "admin": False}
    assert cm.identidade(dict(nexus, admin_nexus=True))["admin"] is True
    assert cm.identidade(dict(nexus, nome="")) == {"nome": "ana@exemplo.com", "email": "ana@exemplo.com", "admin": False}
    assert cm.identidade({"auth": True, "auth_kind": "ms", "user": "b@gridco.com.br"})["nome"] == "b@gridco.com.br"
    assert cm.identidade({"auth": True, "auth_kind": "ms", "user": "b@gridco.com.br", "admin_nexus": True})["admin"] is False
    # não sabe quem é: a senha, a senha de administrador do Nexus (não é uma pessoa), a chave da ponte, sem sessão
    assert cm.identidade({"auth": True, "auth_kind": "senha"}) is None
    assert cm.identidade(dict(nexus, user="admin@nexus.invalid", nome="Administrador do Nexus (senha)")) is None
    assert cm.identidade(nexus, pela_chave_de_leitura=True) is None
    assert cm.identidade({}) is None and cm.identidade(dict(nexus, auth=False)) is None


def test_autor_com_identidade_ignora_o_nick_digitado():
    eu = {"nome": "Ana Lima", "email": "ana@exemplo.com", "admin": False}
    assert cm.autor(eu, "Outra Pessoa") == ("Ana Lima", "ana@exemplo.com")
    assert cm.autor(None, "  Beto   S ") == ("Beto S", None)
    assert cm.autor(None, "") == ("", None) and cm.autor(None, "x" * 99)[0] == "x" * 40


def test_quem_apaga():
    ana = {"nome": "Ana", "email": "ana@exemplo.com", "admin": False}
    adm = {"nome": "Adm", "email": "adm@exemplo.com", "admin": True}
    da_ana, do_beto, sem_email = {"email": "ana@exemplo.com"}, {"email": "beto@exemplo.com"}, {"nick": "x"}
    assert cm.pode_apagar(da_ana, ana) and not cm.pode_apagar(do_beto, ana) and not cm.pode_apagar(sem_email, ana)
    assert cm.pode_apagar(do_beto, adm) and cm.pode_apagar(sem_email, adm)
    assert cm.pode_apagar(do_beto, None) and cm.pode_apagar(sem_email, None)          # a senha: como sempre foi


def test_a_conversa_sai_sem_o_email():
    ana = {"nome": "Ana", "email": "ana@exemplo.com", "admin": False}
    t = cm.para_tela([{"nick": "Ana", "texto": "a", "ts": "1", "email": "ana@exemplo.com"},
                      {"nick": "Beto", "texto": "b", "ts": "2", "email": "beto@exemplo.com"}, {"nick": "Velho", "ts": "0"}],
                     ana)
    assert all("email" not in c for c in t)
    assert [(c["nick"], c["pode_apagar"], c["meu"]) for c in t] == [("Ana", True, True), ("Beto", False, False),
                                                                   ("Velho", False, False)]


THREADS = {
    "pv:22854": [{"nick": "Ana", "texto": "Inversor 1.3 desarmado, técnico a caminho", "ts": "2026-11-01 08:00:00.000001"},
                 {"nick": "Beto", "texto": "Religado", "ts": "2026-11-03 10:15:00.000000", "email": "beto@exemplo.com"}],
    "pg:777": [{"nick": "Ana", "texto": "Estação suja", "ts": "2026-10-20 07:30:00", "usina": "Usina Pelo Banco"}],
    "so:CPP100": [{"nick": "Caio", "texto": "Tracker parado", "ts": "2026-11-02 09:00:00.5"}],
    "xx:sem-fonte": [{"nick": "Dani", "texto": "chave estranha", "ts": "2026-09-01 00:00:00"}],
    "pv:vazia": [],
}
CONHECIDAS = {"pv:22854": {"usina": "Pirapora 1", "fonte": "thopen-pv"}, "so:CPP100": {"usina": "Capim", "fonte": "axis"}}


def test_a_lista_mais_nova_primeiro_com_a_usina_pelo_nome():
    it = cm.listar(THREADS, CONHECIDAS, None)
    assert [x["texto"] for x in it] == ["Religado", "Tracker parado", "Inversor 1.3 desarmado, técnico a caminho",
                                        "Estação suja", "chave estranha"]
    por = {x["texto"]: x for x in it}
    assert por["Religado"]["usina"] == "Pirapora 1" and por["Religado"]["fonte"] == "API PV"
    assert por["Religado"]["link"] == "/monitor?fonte=thopen-pv&usina=22854&comentarios=1"
    assert por["Religado"]["quando"] == "03/11/2026 10:15"
    # sem a cache: o nome que a tela mandou no comentário; sem os dois, a chave (nunca um nome inventado)
    assert por["Estação suja"]["usina"] == "Usina Pelo Banco" and por["Estação suja"]["fonte"] == "Thopen (banco)"
    assert por["Estação suja"]["link"] == "/monitor?fonte=thopen-db&usina=777&comentarios=1"
    assert por["chave estranha"]["usina"] == "xx:sem-fonte" and not por["chave estranha"]["usina_conhecida"]
    assert por["chave estranha"]["link"] == ""
    # o `so` do Painel NOC que é da Axis abre na aba da Axis
    assert por["Tracker parado"]["fonte"] == "Axis" and "fonte=axis&usina=CPP100" in por["Tracker parado"]["link"]
    assert all("email" not in x for x in it)


def test_os_filtros_busca_usina_autor_e_periodo():
    it = cm.listar(THREADS, CONHECIDAS, None)
    textos = lambda xs: [x["texto"] for x in xs]
    assert textos(cm.filtrar(it, q="TECNICO")) == ["Inversor 1.3 desarmado, técnico a caminho"]   # sem acento e caixa
    assert textos(cm.filtrar(it, q="pirapora")) == ["Religado", "Inversor 1.3 desarmado, técnico a caminho"]
    assert textos(cm.filtrar(it, q="beto")) == ["Religado"]                                      # o autor também
    assert textos(cm.filtrar(it, chave="pg:777")) == ["Estação suja"]
    assert textos(cm.filtrar(it, autor_="Ana")) == ["Inversor 1.3 desarmado, técnico a caminho", "Estação suja"]
    assert textos(cm.filtrar(it, de="2026-11-01", ate="2026-11-02")) == ["Tracker parado",
                                                                         "Inversor 1.3 desarmado, técnico a caminho"]
    assert textos(cm.filtrar(it, de="2026-11-03")) == ["Religado"]
    assert len(cm.filtrar(it, de="03/11/2026")) == len(it)                                       # data inválida não corta
    op = cm.opcoes(it)
    assert [u["usina"] for u in op["usinas"]] == ["Capim", "Pirapora 1", "Usina Pelo Banco", "xx:sem-fonte"]
    assert {a["nome"]: a["qtd"] for a in op["autores"]} == {"Ana": 2, "Beto": 1, "Caio": 1, "Dani": 1}


# ── 2. as rotas ─────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _sem_rede(monkeypatch):
    resolver = socket.getaddrinfo

    def so_local(host, *a, **k):
        if str(host) in ("127.0.0.1", "localhost", "::1"):
            return resolver(host, *a, **k)
        raise socket.gaierror("rede cortada no teste dos comentários")
    monkeypatch.setattr(socket, "getaddrinfo", so_local)


@pytest.fixture
def cli(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "STATE_PATH", str(tmp_path / "ufv_state.json"))
    monkeypatch.setattr(app, "DASH_PASSWORD", SENHA)
    monkeypatch.setattr(app, "NEXUS_SSO_CHAVE", CHAVE)
    monkeypatch.setattr(app, "PLATAFORMA_ANALISTAS", pn.ler_lista("ana@exemplo.com, beto@exemplo.com"))
    monkeypatch.setattr(app, "PLATAFORMA_GESTORES", pn.ler_lista("gestor@exemplo.com"))
    monkeypatch.setattr(app, "NEXUS_PORTA_PRINCIPAL", "")
    monkeypatch.setattr(app, "_PASSES_USADOS", pn.NumerosUsados())
    monkeypatch.setattr(app, "_MODO_WEB", True)
    monkeypatch.setitem(app.app.config, "PROPAGATE_EXCEPTIONS", False)
    return app.app.test_client()


def entrar(cli, email="ana@exemplo.com", nome="Ana Lima", admin=False, destino="/painel/comentarios"):
    cli.get("/logout")
    dados = {"v": 1, "email": email, "nome": nome, "admin": admin, "destino": destino, "vence": time.time() + 60,
             "numero": f"numero-de-teste-{next(_SEQ):08d}"}
    r = cli.post("/painel/nexus/entrar", data={"passe": pn.assinar_passe(dados, CHAVE)}, headers=NA_MOLDURA)
    assert r.status_code == 303, r.get_data(as_text=True)[:300]


def entrar_com_senha(cli):
    cli.get("/logout")
    assert cli.post("/login", data={"senha": SENHA}).status_code == 302


def arquivo():
    return json.loads(pathlib.Path(app.STATE_PATH).read_text(encoding="utf-8"))["comments_thread"]


def test_com_o_passe_o_autor_e_o_da_sessao_e_nao_o_do_corpo(cli):
    entrar(cli)
    r = cli.post("/api/state/comment/add", json={"key": "pv:22854", "nick": "Outra Pessoa", "texto": "Religado às 10h",
                                                 "usina": "Pirapora 1"})
    assert r.status_code == 200, r.get_data(as_text=True)
    salvo = arquivo()["pv:22854"][0]
    assert salvo["nick"] == "Ana Lima" and salvo["email"] == "ana@exemplo.com" and salvo["usina"] == "Pirapora 1"
    # o nick nem precisa vir: quem diz é a sessão
    assert cli.post("/api/state/comment/add", json={"key": "pv:22854", "texto": "sem nick"}).status_code == 200
    # a resposta e o /api/state saem sem o e-mail, com o pode_apagar e o meu desta sessão
    th = r.get_json()["thread"]
    assert th[0]["nick"] == "Ana Lima" and "email" not in th[0] and th[0]["pode_apagar"] and th[0]["meu"]
    st = cli.get("/api/state").get_json()["comments_thread"]["pv:22854"]
    assert all("email" not in c and c["meu"] for c in st)
    assert "ana@exemplo.com" not in cli.get("/api/state").get_data(as_text=True)


def test_pela_senha_o_nick_e_obrigatorio_como_antes(cli):
    entrar_com_senha(cli)
    r = cli.post("/api/state/comment/add", json={"key": "pv:1", "texto": "sem nome"})
    assert r.status_code == 400 and "nick" in r.get_json()["error"]
    assert cli.post("/api/state/comment/add", json={"key": "pv:1", "nick": "Beto", "texto": "ok"}).status_code == 200
    salvo = arquivo()["pv:1"][0]
    assert salvo["nick"] == "Beto" and "email" not in salvo


def test_a_senha_de_administrador_do_nexus_nao_e_uma_pessoa(cli, monkeypatch):
    monkeypatch.setattr(app, "PLATAFORMA_ANALISTAS", pn.ler_lista("*"))
    entrar(cli, "admin@nexus.invalid", "Administrador do Nexus (senha)", admin=True)
    assert cli.post("/api/state/comment/add", json={"key": "pv:1", "texto": "x"}).status_code == 400
    assert cli.post("/api/state/comment/add", json={"key": "pv:1", "nick": "Quem Digitou", "texto": "x"}).status_code == 200
    assert arquivo()["pv:1"][0]["nick"] == "Quem Digitou"


def test_apagar_so_o_proprio_ou_o_admin_do_nexus(cli):
    entrar(cli, "beto@exemplo.com", "Beto Souza")
    cli.post("/api/state/comment/add", json={"key": "pv:9", "texto": "do Beto"})
    ts = arquivo()["pv:9"][0]["ts"]
    entrar(cli, "ana@exemplo.com", "Ana Lima")
    assert cli.get("/api/state").get_json()["comments_thread"]["pv:9"][0]["pode_apagar"] is False
    r = cli.post("/api/state/comment/del", json={"key": "pv:9", "ts": ts})
    assert r.status_code == 403 and "Só quem escreveu" in r.get_json()["error"]
    assert len(arquivo()["pv:9"]) == 1                                                  # nada saiu
    entrar(cli, "beto@exemplo.com", "Beto Souza")                                       # o próprio apaga
    assert cli.post("/api/state/comment/del", json={"key": "pv:9", "ts": ts}).status_code == 200
    assert arquivo()["pv:9"] == []
    # o admin do Nexus apaga o de qualquer um, e o de quem escreveu pela senha (sem e-mail)
    entrar_com_senha(cli)
    cli.post("/api/state/comment/add", json={"key": "pv:9", "nick": "Pela Senha", "texto": "x"})
    ts2 = arquivo()["pv:9"][0]["ts"]
    entrar(cli, "ana@exemplo.com", "Ana Lima")
    assert cli.post("/api/state/comment/del", json={"key": "pv:9", "ts": ts2}).status_code == 403
    entrar(cli, "ana@exemplo.com", "Ana Lima", admin=True)
    assert cli.post("/api/state/comment/del", json={"key": "pv:9", "ts": ts2}).status_code == 200


def test_pela_senha_apaga_como_antes(cli):
    entrar(cli, "beto@exemplo.com", "Beto Souza")
    cli.post("/api/state/comment/add", json={"key": "pv:9", "texto": "do Beto"})
    ts = arquivo()["pv:9"][0]["ts"]
    entrar_com_senha(cli)
    assert cli.get("/api/state").get_json()["comments_thread"]["pv:9"][0]["pode_apagar"] is True
    assert cli.post("/api/state/comment/del", json={"key": "pv:9", "ts": ts}).status_code == 200
    assert arquivo()["pv:9"] == []


def test_a_tela_comentarios_lista_e_filtra(cli, monkeypatch):
    monkeypatch.setitem(app._cache, "payload", {"rows": [{"plant_id": 22854, "usina": "Pirapora 1"}]})
    pathlib.Path(app.STATE_PATH).write_text(json.dumps({"comments_thread": THREADS}), encoding="utf-8")
    entrar(cli)
    assert cli.get("/painel/comentarios", headers=NA_MOLDURA).status_code == 200
    d = cli.get("/api/comentarios").get_json()
    assert d["total"] == 5 and len(d["itens"]) == 5 and d["itens"][0]["texto"] == "Religado"
    assert d["itens"][0]["usina"] == "Pirapora 1" and d["eu"] == {"identificado": True, "nome": "Ana Lima",
                                                                   "apaga_todos": False, "grava": True}
    assert "beto@exemplo.com" not in json.dumps(d)
    f = cli.get("/api/comentarios?q=religado").get_json()
    assert [x["texto"] for x in f["itens"]] == ["Religado"] and f["total"] == 5
    assert len(f["usinas"]) == 4 and len(f["autores"]) == 4                 # filtrar não some com as opções
    assert [x["texto"] for x in cli.get("/api/comentarios?chave=pg:777").get_json()["itens"]] == ["Estação suja"]
    assert len(cli.get("/api/comentarios?autor=Ana").get_json()["itens"]) == 2
    assert [x["texto"] for x in cli.get("/api/comentarios?de=2026-11-03&ate=2026-11-03").get_json()["itens"]] == ["Religado"]


def test_o_gestor_le_a_tela_e_nao_escreve(cli):
    entrar(cli, "gestor@exemplo.com", "Gestora")
    assert cli.get("/painel/comentarios", headers=NA_MOLDURA).status_code == 200
    d = cli.get("/api/comentarios")
    assert d.status_code == 200 and d.get_json()["eu"]["grava"] is False
    assert cli.post("/api/state/comment/add", json={"key": "pv:1", "texto": "x"}).status_code == 403
    assert cli.post("/api/state/comment/del", json={"key": "pv:1", "ts": "x"}).status_code == 403


def test_a_pagina_leva_o_gc_eu(cli):
    entrar(cli, nome="Ana </script><script>alert(1)</script>")
    html = cli.get("/painel/comentarios", headers=NA_MOLDURA).get_data(as_text=True)
    cabeca = html[:html.index("</head>")]
    m = re.search(r"window\.gcEu=(\{.*?\});", cabeca)
    assert m and json.loads(m.group(1))["identificado"] is True
    assert "</script><script>alert" not in cabeca                     # o nome não fecha o script
    assert json.loads(m.group(1))["nome"].startswith("Ana </script>")
    assert "@exemplo.com" not in cabeca                                # o e-mail não vai na página
    entrar_com_senha(cli)
    html = cli.get("/painel/comentarios").get_data(as_text=True)
    assert json.loads(re.search(r"window\.gcEu=(\{.*?\});", html).group(1)) == {
        "identificado": False, "nome": "", "apaga_todos": False, "grava": True}


def test_desligamento_e_os_atribuida_pegam_o_nome_da_sessao(cli, monkeypatch):
    entrar(cli)
    r = cli.post("/api/state/usina-desligada", json={"pid": "1", "usina": "U", "texto": "furto", "nick": "Outro"})
    assert r.status_code == 200 and r.get_json()["rec"]["nick"] == "Ana Lima" and "email" not in r.get_json()["rec"]
    r = cli.post("/api/state/os-atribuir", json={"pid": "1", "inv_id": "2", "folio": "3", "usina": "U", "nick": "Outro"})
    assert r.status_code == 200 and r.get_json()["rec"]["nick"] == "Ana Lima"
    entrar_com_senha(cli)
    r = cli.post("/api/state/usina-desligada", json={"pid": "1", "usina": "U", "texto": "furto", "nick": "Digitado"})
    assert r.get_json()["rec"]["nick"] == "Digitado"


def test_quem_esta_fechando_o_ticket_e_a_sessao(cli, monkeypatch):
    visto = {}

    def salvar(linha, esperado, valores, quem, **k):
        visto["quem"] = quem
        return {"confirmado": False, "valores": {}}
    monkeypatch.setattr(app, "_tk_str_do_ticket", lambda linha: {"strings": []})
    monkeypatch.setattr(app._estado_backup, "_token", lambda: "token-de-teste")
    monkeypatch.setattr(app._tkf, "salvar", salvar)
    entrar(cli)
    assert cli.post("/api/strings/tickets/7/salvar", json={"quem": "Outro"}).status_code == 200
    assert visto["quem"] == "Ana Lima (plataforma)"
    entrar_com_senha(cli)
    cli.post("/api/strings/tickets/7/salvar", json={"quem": "Digitado"})
    assert visto["quem"] == "Digitado (plataforma)"


# ── 3. as telas no node ─────────────────────────────────────────────────────────────────────────────────────────────
_DOM = r"""
const ELS = {};
function E(id) { return ELS[id] || (ELS[id] = { id, innerHTML: '', textContent: '', value: '', className: '', dataset: {},
  style: {}, _ev: {}, addEventListener(t, f) { this._ev[t] = f; }, focus() {} }); }
const document = { getElementById: E, cookie: '', documentElement: { setAttribute() {}, classList: { add() {} } } };
const localStorage = { _d: {}, getItem(k) { return this._d[k] || null; }, setItem(k, v) { this._d[k] = String(v); } };
const location = { search: '' };
const espera = () => new Promise(r => setImmediate(r));
"""


def _roda_pagina(eu, resposta):
    html = (RAIZ / "plataforma" / "templates" / "comentarios.html").read_text(encoding="utf-8")
    js = re.findall(r"<script>(.*?)</script>", html, flags=re.S)[-1]
    prog = _DOM + f"""
const window = {{ gcEu: {json.dumps(eu)}, addEventListener() {{}}, confirm: () => true }};
globalThis.window = window;
const pedidos = [];
globalThis.fetch = async (u, o) => {{ pedidos.push([u, o && o.body]); return {{ ok: true, status: 200, json: async () => ({json.dumps(resposta)}) }}; }};
{js}
(async () => {{ await espera(); await espera(); await espera();
  process.stdout.write(JSON.stringify({{lista: E('lista').innerHTML, quem: E('quem').innerHTML, contagem: E('contagem').textContent,
    usinas: E('fUsina').innerHTML, pedidos}})); }})();
"""
    r = subprocess.run([NODE, "-e", prog], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(not NODE, reason="node não instalado")
def test_a_pagina_desenha_a_lista_e_o_autor_da_sessao():
    itens = cm.listar(dict(THREADS, **{"pv:22854": THREADS["pv:22854"] + [
        {"nick": "Eva", "texto": "<img src=x onerror=alert(1)>", "ts": "2026-11-03 11:00:00"}]}), CONHECIDAS,
        {"nome": "Ana", "email": "ana@exemplo.com", "admin": False})
    eu = {"identificado": True, "nome": "Ana Lima", "apaga_todos": False, "grava": True}
    d = dict(cm.opcoes(itens), itens=itens, total=len(itens), eu=eu, lido_em="14:05:00")
    o = _roda_pagina(eu, d)
    assert "Comentando como <b>Ana Lima</b>" in o["quem"] and 'id="nick"' not in o["quem"]
    assert o["contagem"] == "6 comentários" and o["lista"].count('class="cmt"') == 6
    assert "&lt;img src=x onerror=alert(1)&gt;" in o["lista"] and "<img" not in o["lista"]      # o texto escapado
    assert "Pirapora 1" in o["lista"] and "Abrir no tempo real" in o["lista"]
    assert 'href="/monitor?fonte=thopen-pv&amp;usina=22854&amp;comentarios=1"' in o["lista"]
    assert "Apagar" not in o["lista"]                                  # nada ali é da Ana: só o admin apagaria
    assert "Capim · Axis (1)" in o["usinas"]
    assert o["pedidos"][0][0] == "/api/comentarios"


@pytest.mark.skipif(not NODE, reason="node não instalado")
def test_a_pagina_sem_identidade_pede_o_nome_e_o_gestor_so_le():
    eu = {"identificado": False, "nome": "", "apaga_todos": False, "grava": True}
    itens = cm.listar(THREADS, CONHECIDAS, None)
    o = _roda_pagina(eu, dict(cm.opcoes(itens), itens=itens, total=5, eu=eu))
    assert 'id="nick"' in o["quem"] and "Seu nome" in o["quem"]
    assert o["lista"].count("Apagar") == 5 and o["lista"].count("Responder") == 5
    gestor = dict(eu, grava=False)
    o = _roda_pagina(gestor, dict(cm.opcoes(itens), itens=itens, total=5, eu=gestor))
    assert "Somente leitura" in o["quem"] and "Responder" not in o["lista"] and "Apagar" not in o["lista"]


MON = (RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")


def _modal_do_tempo_real(eu, thread):
    """O trecho do modal de comentários do Monitoramento, rodado sozinho no node com o resto dublado."""
    i, f = MON.index("/* ── Comentários + OS por usina (modal) ── */"), MON.index("/* ── Atribuir OS (Fracttal)")
    prog = _DOM + f"""
const window = {{ gcEu: {json.dumps(eu)} }}; globalThis.window = window;
const state = {{ _ckey: 'pv:1', _cusina: 'Pirapora 1' }}, RD = {{ comments: {{ 'pv:1': {json.dumps(thread)} }}, _osList: [] }};
const esc = s => String(s); function _prendeOverlays() {{}} function render() {{}} function _toast() {{}}
const pedidos = []; async function fetchJSON(u, o) {{ pedidos.push([u, JSON.parse(o.body)]); return {{ thread: [] }}; }}
{MON[i:f]}
(async () => {{ _renderComent(); const html = E('gc-cmodal').innerHTML;
  E('gc-ctxt').value = 'texto novo'; E('gc-cnick').value = 'Digitado'; await window.publicarComent();
  process.stdout.write(JSON.stringify({{ html, pedidos }})); }})();
"""
    r = subprocess.run([NODE, "-e", prog], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(not NODE, reason="node não instalado")
def test_o_modal_do_tempo_real_nao_pede_o_nome_a_quem_entrou_pelo_nexus():
    th = [{"nick": "Ana Lima", "texto": "a", "ts": "2026-11-03 10:00:00", "pode_apagar": True, "meu": True},
          {"nick": "Beto", "texto": "b", "ts": "2026-11-03 09:00:00", "pode_apagar": False, "meu": False}]
    o = _modal_do_tempo_real({"identificado": True, "nome": "Ana Lima", "apaga_todos": False, "grava": True}, th)
    assert 'id="gc-cnick"' not in o["html"] and "Comentando como" in o["html"] and "Ana Lima" in o["html"]
    assert o["html"].count('title="Excluir"') == 1 and "(você)" in o["html"]
    assert o["pedidos"][-1] == ["/api/state/comment/add", {"key": "pv:1", "nick": "Ana Lima", "texto": "texto novo",
                                                           "usina": "Pirapora 1"}]
    o = _modal_do_tempo_real({"identificado": False, "nome": "", "apaga_todos": False, "grava": True},
                             [dict(c, pode_apagar=True, meu=False) for c in th])
    assert 'id="gc-cnick"' in o["html"] and "Comentando como" not in o["html"]
    assert o["html"].count('title="Excluir"') == 2
    assert o["pedidos"][-1][1]["nick"] == "Digitado"


# ── 4. a porta ──────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_tela_esta_no_mapa_e_o_gestor_le():
    t = pn.tela_do_caminho("/painel/comentarios")
    assert (t.torre, t.tela, t.so_admin) == ("performance", "comentarios", False)
    assert "performance|comentarios|/painel/comentarios||" in pn.texto_canonico_do_mapa().splitlines()
    assert pn.destino_permitido("/painel/comentarios") == "/painel/comentarios"
    assert ln.permitido_gestor("GET", "/painel/comentarios") and ln.permitido_gestor("GET", "/api/comentarios")
    assert not ln.permitido_gestor("POST", "/api/state/comment/add")
    assert not ln.permitido("GET", "/api/comentarios")                # a chave da ponte não ganha a tela nova


# ── 5. o comentário automático da OS criada (03/11/2026) ────────────────────────────────────────────────────────────
# Levi: "quando eu crio uma OS de performance já vira um comentário automático: '<Levi> criou uma OS de <String> para o
# <inversor X>' + 'Observação da OS'".
def _os(cli, **corpo):
    base = {"chave": "pv:22854", "usina": "Pirapora 1", "tipo": "Recomposição de String",
            "criadas": [{"folio": "16958", "ativo": "Inversor 1.3", "observacao": "Strings 3 e 4 sem corrente"}]}
    base.update(corpo)
    return cli.post("/api/state/comment/os", json=base)


def test_a_os_criada_vira_comentario_com_o_autor_da_sessao(cli):
    entrar(cli)
    r = _os(cli, quem="Outro Nome")
    assert r.status_code == 200 and r.get_json()["gravadas"] == ["16958"]
    c = arquivo()["pv:22854"][0]
    assert c["texto"] == ("Ana Lima criou a OS 16958 de Recomposição de String para o Inversor 1.3\n"
                          "Observação: Strings 3 e 4 sem corrente")
    assert (c["nick"], c["origem"], c["folio"], c["link_os"], c["email"]) == (
        "Ana Lima", "os", "16958", "/os/os/folio/16958", "ana@exemplo.com")
    th = r.get_json()["thread"]
    assert "email" not in th[0] and th[0]["pode_apagar"] is False          # o automático não é do autor apagar


def test_a_mesma_os_nao_vira_dois_comentarios(cli):
    entrar(cli)
    assert _os(cli).get_json()["gravadas"] == ["16958"]
    r = _os(cli, chave="pg:777")                                            # a mesma OS avisada por outro caminho
    assert r.get_json()["gravadas"] == [] and r.get_json()["repetidas"] == ["16958"]
    r = _os(cli, criadas=[{"folio": "16958"}, {"folio": "16959", "ativo": "Inversor 1.4"}, {"folio": "16959"}])
    assert r.get_json()["gravadas"] == ["16959"] and r.get_json()["repetidas"] == ["16958", "16959"]
    st = arquivo()
    assert len(st["pv:22854"]) == 2 and "pg:777" not in st


def test_a_criacao_que_falhou_nao_vira_comentario(cli):
    entrar(cli)
    assert _os(cli, criadas=[]).status_code == 400
    r = _os(cli, criadas=[{"folio": "", "ativo": "Inversor 1.3"}, {"folio": None}, {"folio": "abc"}])
    assert r.status_code == 200 and r.get_json()["gravadas"] == []
    assert not pathlib.Path(app.STATE_PATH).exists() or not arquivo().get("pv:22854")


def test_a_os_sem_a_tela_que_a_abriu_vai_pela_usina(cli):
    entrar_com_senha(cli)
    r = _os(cli, chave="", usina="Irecê 2 - BA", quem="Pessoa do Fracttal")
    assert r.get_json()["chave"] == "os:irece-2-ba"
    c = arquivo()["os:irece-2-ba"][0]
    assert c["nick"] == "Pessoa do Fracttal" and "email" not in c        # sem identidade: o login do Fracttal
    assert _os(cli, chave="xx:a b", usina="").status_code == 400          # chave torta e sem usina: nada
    it = cm.listar(arquivo(), {}, None)
    assert it[0]["usina"] == "Irecê 2 - BA" and it[0]["link"] == "" and it[0]["link_os"] == "/os/os/folio/16958"


def test_o_comentario_da_os_so_o_admin_apaga(cli):
    entrar(cli)
    _os(cli)
    ts = arquivo()["pv:22854"][0]["ts"]
    assert cli.post("/api/state/comment/del", json={"key": "pv:22854", "ts": ts}).status_code == 403   # nem o autor
    entrar_com_senha(cli)
    assert cli.post("/api/state/comment/del", json={"key": "pv:22854", "ts": ts}).status_code == 403   # nem a senha
    entrar(cli, admin=True)
    assert cli.post("/api/state/comment/del", json={"key": "pv:22854", "ts": ts}).status_code == 200


def test_a_tela_filtra_as_os_criadas(cli):
    entrar(cli)
    _os(cli)
    cli.post("/api/state/comment/add", json={"key": "pv:22854", "texto": "escrito"})
    assert [x["texto"] for x in cli.get("/api/comentarios?origem=comentario").get_json()["itens"]] == ["escrito"]
    so = cli.get("/api/comentarios?origem=os").get_json()["itens"]
    assert len(so) == 1 and so[0]["folio"] == "16958" and so[0]["link_os"] == "/os/os/folio/16958"
    assert len(cli.get("/api/comentarios").get_json()["itens"]) == 2


def test_o_gestor_nao_grava_o_comentario_da_os(cli):
    entrar(cli, "gestor@exemplo.com", "Gestora")
    assert _os(cli).status_code == 403
    assert any("/api/state/comment/os".startswith(g.rstrip("/")) for g in ln.GRAVACOES_GESTOR)


def _trk_comentario(itens, j):
    i = MON.index("function _trkOsComentario(")
    f = MON.index("function _trkOsAlvoOpts(")
    prog = f"""
const SKEY={{'thopen-pv':'pv','athon':'sunop'}}, VKEY={{'thopen-pv':'pv','athon':'so'}}, state={{source:'thopen-pv'}}, RD={{comments:{{}}}};
function render(){{}}
function _trkOsFalhou(j,it){{ return (j.falhou||[]).includes(it.k); }}
const pedidos=[]; globalThis.fetch=async(u,o)=>{{ pedidos.push([u, JSON.parse(o.body)]); return {{ok:true, json:async()=>({{}})}}; }};
{MON[i:f]}
_trkOsComentario({json.dumps(itens)}, {json.dumps(j)});
setImmediate(()=>process.stdout.write(JSON.stringify(pedidos)));
"""
    r = subprocess.run([NODE, "-e", prog], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(not NODE, reason="node não instalado")
def test_o_criar_os_dos_trackers_comenta_cada_os_que_saiu():
    it = lambda k, lab: {"k": k, "usinaFr": "Thopen - Capim - MG", "base": "Verificação de Tracker Parado",
                         "alvo": {"label": lab, "code": "C-" + lab}, "obs": "Tracker parado desde 08:00"}
    itens = [it("sunop|CPP100|T1", "Tracker 1"), it("sunop|CPP100|T2", "Tracker 2"), it("sunop|CPP100|T3", "Tracker 3")]
    # o T2 falhou: os nº que voltaram (na ordem) são do T1 e do T3
    p = _trk_comentario(itens, {"ok": 2, "falhas": 1, "folios": [501, 503], "falhou": ["sunop|CPP100|T2"]})
    assert len(p) == 1 and p[0][0] == "/api/state/comment/os"
    assert p[0][1]["chave"] == "so:CPP100" and p[0][1]["tipo"] == "Verificação de Tracker Parado"
    assert [(c["folio"], c["ativo"]) for c in p[0][1]["criadas"]] == [("501", "Tracker 1"), ("503", "Tracker 3")]
    # nada saiu (ou saiu sem nº): nenhum pedido
    assert _trk_comentario(itens, {"ok": 0, "falhas": 3, "folios": [], "falhou": [x["k"] for x in itens]}) == []
    assert _trk_comentario(itens[:1], {"ok": 1, "falhas": 0, "folios": [None]}) == []


def test_os_links_do_tempo_real_levam_a_conversa_da_usina():
    """As OS de strings e de ETM abrem a página de criar do OS Creator: o link leva `comentario=<chave>` para ela gravar
    o comentário na conversa certa quando a OS sair."""
    i = MON.index("function _osLink(g)")
    assert "comentario:(VKEY[state.source]||'pv')+':'+g.pid" in MON[i:i + 400]
    i = MON.index("window.abrirOsEtm=")
    assert "q.comentario=(VKEY[state.source]||'pv')+':'+lin.plant_id" in MON[i:i + 900]


@pytest.mark.skipif(not NODE, reason="node não instalado")
def test_a_pagina_marca_a_os_criada_com_o_link():
    th = {"pv:22854": [{"nick": "Ana Lima", "texto": "Ana Lima criou a OS 16958 de Recomposição de String",
                        "ts": "2026-11-03 10:00:00", "origem": "os", "folio": "16958", "link_os": "/os/os/folio/16958"}]}
    itens = cm.listar(th, CONHECIDAS, None)
    eu = {"identificado": False, "nome": "", "apaga_todos": False, "grava": True}
    o = _roda_pagina(eu, dict(cm.opcoes(itens), itens=itens, total=1, eu=eu))
    assert 'OS criada · <a href="/os/os/folio/16958"' in o["lista"] and "nº 16958" in o["lista"]
    assert "Apagar" not in o["lista"] and "Responder" in o["lista"]        # o automático não se apaga pela senha
