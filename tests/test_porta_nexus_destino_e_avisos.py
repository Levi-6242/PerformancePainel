# -*- coding: utf-8 -*-
"""Porta única com o Nexus: o "Entrar pelo Nexus" volta à tela pedida (auditoria B6) e os avisos para quem não é
administrador (auditoria B12). 10/10/2026.

B6: abrir uma tela pelo Nexus troca a sessão de 30 dias da senha pela do passe (12 h, que some ao fechar o navegador). No
dia seguinte o favorito (/painel, /painel/falhas...) cai no /login?next=..., e o "Entrar pelo Nexus" (fase 3) ignorava o
next e levava ao Início do Nexus. Agora leva a <NEXUS_PORTA_PRINCIPAL>/t/<torre>/<tela>?p=<next> quando o next é uma
tela do mapa, e ao Início quando não é.

B12: a curva das strings mandava "renove na tela Tokens" para quem leva "Só administradores" no /tokens, e o "Reiniciar
serviço" do Monitor da ronda engolia o 403 e girava ~80 s esperando um reinício que nunca foi pedido.
"""
import json
import pathlib
import re
import shutil
import subprocess
from urllib.parse import parse_qs, quote, urlsplit

import pytest

import app
import porta_nexus as pn

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
NODE = shutil.which("node")
SENHA = "senha-de-teste"


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", SENHA)
    monkeypatch.setattr(app, "NEXUS_SSO_CHAVE", "")
    monkeypatch.setattr(app, "NEXUS_PORTA_PRINCIPAL", "")
    monkeypatch.setattr(app, "_MODO_WEB", True)
    monkeypatch.setitem(app.app.config, "PROPAGATE_EXCEPTIONS", False)
    return app.app.test_client()


_BOTAO = re.compile(r'<a href="([^"]*)" class="nexbtn">Entrar pelo Nexus</a>')


def _botao(cli, query=""):
    html = cli.get("/login" + query).get_data(as_text=True)
    m = _BOTAO.search(html)
    assert m, html[:400]
    return m.group(1).replace("&amp;", "&")


# ── B6: o "Entrar pelo Nexus" com destino ───────────────────────────────────────────────────────────────────────────
def test_o_favorito_volta_a_mesma_tela_dentro_do_nexus(cli, monkeypatch):
    """O caso: o favorito do Painel NOC, no dia seguinte (a sessão do passe sumiu ao fechar o navegador)."""
    monkeypatch.setattr(app, "NEXUS_PORTA_PRINCIPAL", "https://app.exemplo.com/")      # a raiz (fase 4)
    r = cli.get("/painel")                                     # o portão manda ao login com o next
    assert r.status_code == 302 and r.headers["Location"].endswith("/login?next=/painel")
    assert _botao(cli, "?next=/painel") == "https://app.exemplo.com/t/performance/noc?p=%2Fpainel"


def test_cada_tela_do_mapa_vai_ao_seu_item_e_o_nexus_acha_o_mesmo_caminho(cli, monkeypatch):
    monkeypatch.setattr(app, "NEXUS_PORTA_PRINCIPAL", "/nexus/")                      # o prefixo de hoje
    casos = {"/painel/falhas": "performance/strings-trackers", "/gerencial/disponibilidade": "performance/disponibilidade",
             "/ronda/monitor": "performance/monitor-ronda", "/cos": "cos/acompanhamento", "/tokens": "base/chaves-fontes",
             "/tempo-real/athon": "performance/tempo-real", "/monitor?fonte=pv&embed=1": "performance/tempo-real",
             "/painel/usina/São Bento": "performance/diagnostico"}
    for nxt, item in casos.items():
        href = _botao(cli, "?next=" + quote(nxt, safe=""))
        u = urlsplit(href)
        assert u.path == "/nexus/t/" + item, (nxt, href)
        p = parse_qs(u.query)["p"][0]                          # o que o Nexus lê de ?p=
        assert pn.destino_permitido(p) == p and pn.tela_do_caminho(p).tela == item.split("/")[1], (nxt, p)
    p = parse_qs(urlsplit(_botao(cli, "?next=" + quote("/painel/usina/São Bento", safe=""))).query)["p"][0]
    assert p == "/painel/usina/S%C3%A3o%20Bento"               # como o navegador escreve o caminho


def test_fora_do_mapa_ou_next_ruim_leva_ao_inicio(cli, monkeypatch):
    monkeypatch.setattr(app, "NEXUS_PORTA_PRINCIPAL", "https://app.exemplo.com/")
    ruins = ("", "?next=/", "?next=/login", "?next=/painel/nexus/entrar", "?next=//outro.exemplo.com/painel",
             "?next=https://outro.exemplo.com/painel", "?next=%2F%5Coutro.exemplo.com", "?next=/painel%0d%0aX:%20y",
             "?next=/gemeo/%2e%2e/tokens", "?next=painel", "?next=/api/macro", "?next=" + "/painel" * 400)
    for q in ruins:
        assert _botao(cli, q) == "https://app.exemplo.com/", q


def test_sem_a_fase_3_nada_muda(cli):
    assert "Entrar pelo Nexus" not in cli.get("/login?next=/painel").get_data(as_text=True)


def test_o_href_sai_escapado_no_html(cli, monkeypatch):
    monkeypatch.setattr(app, "NEXUS_PORTA_PRINCIPAL", "/nexus/")
    html = cli.get("/login?next=" + quote('/painel/usina/"><script>x</script>', safe="")).get_data(as_text=True)
    assert "<script>x" not in html
    m = _BOTAO.search(html)
    assert m and '"' not in m.group(1) and "<" not in m.group(1)


# ── B12: os avisos para quem não é administrador ────────────────────────────────────────────────────────────────────
def _node(js, tmp_path):
    if not NODE:
        pytest.skip("node não instalado")
    arq = tmp_path / "prova.js"
    arq.write_text(js, encoding="utf-8")
    p = subprocess.run([NODE, str(arq)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr[-3000:]
    return json.loads(p.stdout.strip().splitlines()[-1])


def _func(texto, nome):
    for prefixo in ("async function ", "function "):
        alvo = prefixo + nome + "("
        if alvo in texto:
            i = texto.index(alvo)
            return texto[i:texto.index("\n}\n", i) + 3]
    raise AssertionError(f"função {nome} não está na página")


def test_curva_com_token_vencido_manda_pedir_a_um_administrador(tmp_path):
    """Quem entrou pelo Nexus sem ser administrador leva "Só administradores" no /tokens: o aviso da curva não pode
    mandá-la para lá."""
    mon = (RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")
    js = ("const _he=s=>String(s==null?'':s);\n"
          + _func(mon, "_curvaMotivoApiTxt") + _func(mon, "_curvaMotivoTxt")
          + "const admin=_curvaMotivoTxt('token_vencido','26/09','26/09 10:00','inversor','');"
            "globalThis.gcSessaoDaPlataforma={semAdmin:true};"
            "const sem=_curvaMotivoTxt('sem_token','26/09','','inversor','');"
            "process.stdout.write('\\n'+JSON.stringify({admin, sem}));")
    r = _node(js, tmp_path)
    assert 'href="/tokens"' in r["admin"] and "renove na tela" in r["admin"]
    assert "/tokens" not in r["sem"] and "peça a um administrador do Nexus" in r["sem"]


def test_o_diagnostico_passa_a_mensagem_do_servidor_pelo_aviso_de_admin():
    """O `msg` da curva da PV Plataforma (_SPV_MOTIVO_MSG) diz "Renove na tela Tokens."; o Diagnóstico mostra o texto
    pelo `gcSessaoDaPlataforma.tokens`, que troca o caminho para quem não é admin (testado no aviso de sessão)."""
    v2 = (RAIZ / "plataforma" / "templates" / "painel_usina_v2.html").read_text(encoding="utf-8")
    assert "sub.textContent=(m&&S?S.tokens(m):m)||" in v2
    assert "Renove na tela Tokens." in app._SPV_MOTIVO_MSG["token_vencido"]
    assert "Cole um na tela Tokens." in app._SPV_MOTIVO_MSG["sem_token"]
    js = (RAIZ / "plataforma" / "aviso_de_sessao.js").read_text(encoding="utf-8")
    assert "Renove na tela Tokens" in js and "Cole um na tela Tokens" in js, "o aviso troca as duas frases do servidor"


def test_reiniciar_servico_mostra_o_403_na_hora(tmp_path):
    ronda = (RAIZ / "plataforma" / "templates" / "ronda_monitor.html").read_text(encoding="utf-8")
    js = (r"""
let STATUS = 403; const intervalos = [];
globalThis.fetch = async () => ({ok: STATUS < 300, status: STATUS, json: async () => ({error: "só administradores do Nexus"})});
globalThis.setInterval = (f, ms) => { intervalos.push(ms); return 1; };
function load() {}
const document = {getElementById: () => ({textContent: ""})};
""" + _func(ronda, "reiniciarServico") + r"""
(async () => {
  const bt = {dataset: {}, disabled: false, textContent: "", style: {}};
  await reiniciarServico(bt); const t403 = bt.textContent, d403 = bt.disabled, i403 = intervalos.length;
  STATUS = 500; await reiniciarServico(bt); const t500 = bt.textContent;
  STATUS = 200; await reiniciarServico(bt);
  process.stdout.write("\n" + JSON.stringify({t403, d403, i403, t500, i200: intervalos.length, busy: bt.dataset.busy}));
})();""")
    r = _node(js, tmp_path)
    assert r["i403"] == 0, "o 403 não pode virar 80 s de espera"
    assert "Só administradores" in r["t403"] and r["d403"] is False
    assert "HTTP 500" in r["t500"]
    assert r["i200"] == 1 and r["busy"] == "1", "o reinício de verdade segue acompanhando o serviço voltar"


# ── o next do /login não sai deste endereço (revisão adversarial de 10/10/2026) ──────────────────────────────────────
# Provado com o test_client: com sessão aberta (senha ou passe), GET /login?next=/%09/mal.exemplo.com/entrar respondia
# 302 para "//mal.exemplo.com/entrar". O _login_next só olhava a barra do começo; o TAB passava, o Werkzeug (e o
# navegador, pela regra de URL do WHATWG) o tiram e sobra um endereço relativo ao protocolo: outro site. A faixa
# "Sessão vencida: entre de novo" ensina a pessoa a entrar pelo /login?next=, o que deixaria crível um link de phishing.
_NEXT_RUINS = ("/%09/mal.exemplo.com/entrar", "/%0a/mal.exemplo.com/entrar", "/%0d/mal.exemplo.com/entrar",
               "/%0d%0a/mal.exemplo.com", "/%00/mal.exemplo.com", "/%7f/mal.exemplo.com", "/%5C/mal.exemplo.com",
               "/%5Cmal.exemplo.com", "//mal.exemplo.com", "https://mal.exemplo.com/", "%09//mal.exemplo.com")


def test_next_com_controle_ou_barra_invertida_volta_ao_inicio_com_sessao(cli):
    assert cli.post("/login", data={"senha": SENHA}).status_code == 302
    for nxt in _NEXT_RUINS:
        r = cli.get("/login?next=" + nxt)
        assert r.status_code == 302 and r.headers["Location"] == "/", (nxt, r.headers.get("Location"))
    # o que é caminho deste endereço segue valendo: o next do portão (decodificado, com espaço e acento) e o da faixa
    # de sessão vencida (já codificado, com a query)
    for nxt, esperado in (("/painel", "/painel"),
                          (quote("/painel/usina/São Bento", safe=""), "/painel/usina/S%C3%A3o%20Bento"),
                          (quote("/painel/usina/12345678?fonte=pv&nome=S%C3%A3o%20Bento", safe=""),
                           "/painel/usina/12345678?fonte=pv&nome=S%C3%A3o%20Bento")):
        r = cli.get("/login?next=" + nxt)
        assert r.headers["Location"] == esperado, (nxt, r.headers["Location"])


def test_next_com_controle_ou_barra_invertida_no_post_da_senha(cli):
    for nxt in _NEXT_RUINS:
        cli.get("/logout")
        r = cli.post("/login?next=" + nxt, data={"senha": SENHA})
        assert r.status_code == 302 and r.headers["Location"] == "/", (nxt, r.headers["Location"])


def test_next_do_login_microsoft_tem_a_mesma_regua(cli, monkeypatch):
    monkeypatch.setattr(app, "MS_SSO_ON", True)
    monkeypatch.setattr(app, "AZURE_CLIENT_ID", "cliente-de-teste")
    monkeypatch.setattr(app, "AZURE_REDIRECT_URI", "https://app.exemplo.com/auth/callback")
    for nxt, esperado in [(n, "/") for n in _NEXT_RUINS] + [("/painel", "/painel")]:
        r = cli.get("/auth/login?next=" + nxt)
        assert r.status_code == 302 and r.headers["Location"].startswith("https://login.microsoftonline.com/")
        with cli.session_transaction() as s:
            assert s["oauth_next"] == esperado, (nxt, s["oauth_next"])
    # o botão "Entrar com Microsoft" do /login também não leva o next ruim adiante
    for nxt in _NEXT_RUINS:
        html = cli.get("/login?next=" + nxt).get_data(as_text=True)
        assert 'href="/auth/login"' in html, nxt


def test_entrar_pelo_nexus_e_o_login_usam_a_mesma_regua(cli, monkeypatch):
    """A docstring do _entrar_pelo_nexus_href dizia que ele usava a régua do _login_next, e não era verdade: agora é uma
    função só (`_caminho_deste_endereco`) para o login da senha, o da Microsoft e o "Entrar pelo Nexus"."""
    monkeypatch.setattr(app, "NEXUS_PORTA_PRINCIPAL", "https://app.exemplo.com/")
    for nxt in _NEXT_RUINS:
        assert _botao(cli, "?next=" + nxt) == "https://app.exemplo.com/", nxt
    for n in ("/painel", "/painel/usina/São Bento", "/monitor?fonte=pv&embed=1"):
        assert app._caminho_deste_endereco(n), n
    for n in ("", "painel", "//x", "/\t/x", "/\n/x", "/\r/x", "/\x00", "/\x7f", "/\\x", None, 12):
        assert not app._caminho_deste_endereco(n), repr(n)
