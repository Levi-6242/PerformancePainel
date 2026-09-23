# -*- coding: utf-8 -*-
"""Versão da plataforma: o ícone que diz se o commit chegou (Levi, 22/09/2026).

O pedido: *"um card mostrando a 'versão' da plataforma e quando eu passo o mouse em cima deve ter
uma data da última atualização de versão"*. E o porquê, dito depois: o servidor lê a plataforma do
GitHub, "cada commit em tese é para atualizar", e ele quer VER se é verdade.

Por isso o ícone não pode só mostrar um número. Tem de separar os estados em que um deploy por
`git pull` engana quem olha:

  1. disco e processo no mesmo commit .............. "versão 2026.09.22"
  2. disco com commit mais novo que o processo ...... baixou, FALTA REINICIAR
  3. HTML novo, payload sem versão .................. o mesmo caso, visto pelo navegador

O 2 e o 3 existem porque as duas metades da tela atualizam em momentos diferentes: o `Entrada.html`
é relido do disco quando o arquivo muda (`_serve_html_cru`, sem restart), e o Python só muda quando
o processo reinicia. Um `git pull` sem restart deixa a tela nova conversando com o código velho — e
sem este aviso quem olha conclui "o commit não subiu", que é o diagnóstico errado.

Diagnóstico de 22/09, feito daqui antes de o ícone existir: o servidor JÁ rodava o `2c75fb8`. Um
caminho inexistente sob /api/gemeo/ deu 404 — no commit antigo o portão de login barra com 401 —,
e o controle /api/nao-existe deu 401, provando o login ligado. Código novo, processo reiniciado.

Por que a versão sai do git e não de um VERSION = "1.4.2" escrito à mão: o número à mão depende de
alguém lembrar de mexer, e no dia em que esquecerem a tela mente com confiança.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
ENTRADA = (RAIZ / "docs" / "redesign" / "Entrada.html").read_text(encoding="utf-8")
NODE = shutil.which("node")


# ── o processo ────────────────────────────────────────────────────────────────

def test_a_versao_e_a_data_do_ultimo_commit():
    """AAAA.MM.DD responde "de quando é isto que estou vendo". Um hash sozinho não responde."""
    v = app._versao_plataforma()
    assert re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", v["versao"]), v["versao"]


def test_o_hover_diz_de_quando_e_o_commit_E_desde_quando_o_processo_esta_no_ar():
    """As duas datas juntas respondem a pergunta do Levi: commit feito às 11:47 e processo no ar desde
    as 13:10 quer dizer que reiniciaram depois do commit. Só a primeira não diz isso."""
    d = app._versao_plataforma()["detalhe"]
    assert "commit" in d and "no ar desde" in d, d


def test_a_versao_do_processo_e_lida_no_BOOT_e_nao_na_primeira_visita():
    """Pego em 22/09 na plataforma local: processo no ar desde 21:55, e a /versao dizendo que ele rodava
    o ae8a5a7, commitado às 22:42. A leitura era feita na PRIMEIRA VISITA, não no boot, e ninguém
    tinha aberto a tela entre um e outro. Um `git pull` nesse intervalo passava a valer como a versão
    do processo: o chip mostrava o commit novo sobre código velho, e o "falta reiniciar", que é a razão
    de ele existir, sumia. Processo novo, sem visita nenhuma: a versão já tem de estar lida."""
    p = subprocess.run([__import__("sys").executable, "-c",
                        "import app; print('LIDA' if app._VERSAO_CACHE['d'] else 'VAZIA')"],
                       cwd=str(RAIZ / "plataforma"), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300, env=dict(__import__("os").environ, GRIDCO_SOLO="1"))
    assert p.returncode == 0, p.stderr[-2000:]
    assert p.stdout.strip().splitlines()[-1] == "LIDA", "a versão só é lida quando alguém abre a tela"


def test_a_leitura_do_processo_e_CACHEADA(monkeypatch):
    """O processo não muda de versão enquanto está de pé; ler o git a cada request de uma tela que se
    redesenha sozinha, em várias abas, seria desperdício."""
    app._versao_plataforma(force=True)
    chamou = {"n": 0}
    real = app.subprocess.run

    def conta(*a, **k):
        chamou["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(app.subprocess, "run", conta)
    for _ in range(5):
        app._versao_plataforma()
    assert chamou["n"] == 0, "leu o git de novo — o cache não segurou"


def test_sem_git_NAO_levanta_e_cai_no_arquivo(monkeypatch):
    """O oem-app.zip da T.I. não leva o `.git`. A tela não pode quebrar por isso."""
    def explode(*a, **k):
        raise FileNotFoundError("git não existe aqui")
    monkeypatch.setattr(app.subprocess, "run", explode)
    v = app._versao_plataforma(force=True)
    assert v["versao"] and "sem git" in v["detalhe"], v
    app._versao_plataforma(force=True)                 # devolve o estado real aos próximos testes


def test_git_que_responde_lixo_nao_derruba(monkeypatch):
    class R:
        returncode, stdout, stderr = 0, "", ""
    monkeypatch.setattr(app.subprocess, "run", lambda *a, **k: R())
    assert app._versao_plataforma(force=True)["versao"]
    monkeypatch.undo()
    app._versao_plataforma(force=True)


# ── disco × processo: o caso que faz parecer que o commit não subiu ────────────

def test_disco_MAIS_NOVO_que_o_processo_acusa_falta_reiniciar(monkeypatch):
    """`git pull` feito, restart não. É o estado 2."""
    monkeypatch.setattr(app, "_versao_em_disco", lambda *a, **k: "f" * 40)
    kv = app._versao_kv()
    assert kv["versao_pendente"] is True
    assert kv["versao_disco"] == "fffffff"


def test_disco_igual_ao_processo_nao_acusa_nada(monkeypatch):
    real = app._versao_plataforma()["commit_completo"]
    monkeypatch.setattr(app, "_versao_em_disco", lambda *a, **k: real)
    kv = app._versao_kv()
    assert kv["versao_pendente"] is False and "versao_disco" not in kv


def test_disco_DESCONHECIDO_nao_vira_alarme(monkeypatch):
    """Sem git no disco (deploy por zip) não há como comparar. Acusar "falta reiniciar" ali seria
    alarme falso permanente — o tipo que ensina a ignorar o ícone."""
    monkeypatch.setattr(app, "_versao_em_disco", lambda *a, **k: "")
    assert app._versao_kv()["versao_pendente"] is False


def test_a_leitura_do_disco_e_barata_mas_viva(monkeypatch):
    """O disco muda com `git pull` a qualquer hora, então não pode ser lido uma vez só como o
    processo — mas também não a cada request. Um minuto de cache segura as duas coisas."""
    app._VERSAO_DISCO.update(ts=0.0, h="")
    chamou = {"n": 0}
    real = app.subprocess.run

    def conta(*a, **k):
        chamou["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(app.subprocess, "run", conta)
    for _ in range(5):
        app._versao_em_disco()
    assert chamou["n"] == 1, f"{chamou['n']} leituras do git em 5 chamadas seguidas"


def test_o_kv_nunca_levanta(monkeypatch):
    """Vai de carona no payload do tempo real: se levantar, a tela inteira cai por um enfeite."""
    def explode(*a, **k):
        raise RuntimeError("qualquer coisa")
    monkeypatch.setattr(app, "_versao_plataforma", explode)
    kv = app._versao_kv()
    assert "versao" in kv and kv["versao_pendente"] is False


# ── o payload da tela ─────────────────────────────────────────────────────────
#   Sem rota e sem thread de propósito. A versão anterior deste teste batia na rota com o build
#   mockado, e o build instantâneo terminava ANTES de a rota ler o cache — o payload saía pelo ramo
#   cheio, que recalcula as strings ao vivo e desceu até o PostgreSQL de verdade (o faulthandler
#   mostrou `_pg_build_snapshot` na pilha). O código estava certo; o teste corria com a rede.

def test_o_payload_leva_a_versao_nos_DOIS_ramos(monkeypatch):
    monkeypatch.setitem(app._ENTRADA_TR_CACHE, "data", None)
    d = app._entrada_tr_payload()
    assert d.get("aquecendo") and d.get("versao") and d.get("versao_detalhe"), "ramo aquecendo sem versão"

    monkeypatch.setitem(app._ENTRADA_TR_CACHE, "data", {"grupos": [], "cache_ts": "13:49:59"})
    monkeypatch.setitem(app._ENTRADA_TR_CACHE, "ts", app.time.time())
    monkeypatch.setattr(app, "_entrada_tr_strings_ao_vivo", lambda data, ts: dict(data))
    d = app._entrada_tr_payload()
    assert not d.get("aquecendo") and d.get("versao") and "versao_pendente" in d, "ramo cheio sem versão"


def test_a_rota_entrega_a_versao_ao_navegador(monkeypatch):
    """O fio até o navegador, sem disparar construção nenhuma."""
    monkeypatch.setattr(app, "DASH_PASSWORD", "", raising=False)
    monkeypatch.setattr(app, "_entrada_tr_disparar", lambda *a, **k: False)
    monkeypatch.setitem(app._ENTRADA_TR_CACHE, "data", None)
    app.app.config["TESTING"] = True
    with app.app.test_client() as c:
        d = c.get("/api/entrada/tempo-real").get_json() or {}
    assert d.get("versao") and d.get("versao_detalhe")


# ── /versao: a conferência sem login ──────────────────────────────────────────

@pytest.fixture
def com_login(monkeypatch):
    """Login LIGADO, como no servidor. Sem isto o portão se abre sozinho e o teste não prova nada."""
    monkeypatch.setattr(app, "DASH_PASSWORD", "senha-de-teste", raising=False)
    app.app.config["TESTING"] = True
    with app.app.test_client() as c:
        yield c


def test_versao_e_PUBLICA(com_login):
    """Para conferir um deploy de qualquer lugar — do celular, da máquina do programador, daqui —
    sem precisar de sessão. O repositório é público, então o commit não revela nada novo."""
    r = com_login.get("/versao")
    assert r.status_code == 200, r.status_code
    d = r.get_json()
    assert d["versao"] and d["commit"] and "reiniciar_pendente" in d


def test_o_resto_da_api_CONTINUA_fechado(com_login):
    """O controle: a exceção é /versao e só ela. Se /api/tokens abrisse junto, o teste de cima
    estaria passando porque o portão caiu, não porque a exceção funciona."""
    assert com_login.get("/api/tokens").status_code == 401


def test_versao_publica_so_expoe_o_que_foi_escolhido(com_login):
    """Lista fechada de campos. Nada de caminho de disco, nome de máquina ou variável de ambiente —
    é a rota que qualquer um na internet consegue ler."""
    d = com_login.get("/versao").get_json()
    assert set(d) <= {"versao", "commit", "commit_em", "no_ar_desde", "commit_no_disco", "reiniciar_pendente"}, set(d)
    texto = json.dumps(d)
    assert ":\\\\" not in texto and "/home" not in texto and "Users" not in texto, texto


# ── o ícone, rodando no navegador (node) ──────────────────────────────────────

def _roda(expr):
    if not NODE:
        pytest.skip("node não instalado")
    i = ENTRADA.index("/* ini versao */")
    j = ENTRADA.index("/* fim versao */")
    js = ENTRADA[i:j] + "\nprocess.stdout.write(JSON.stringify(" + expr + "));"
    r = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_icone_normal_mostra_a_versao_sem_alarde():
    h = _roda('versaoHtml({versao:"2026.09.22", versao_detalhe:"Atualizada em 22/09", versao_pendente:false})')
    assert "versão 2026.09.22" in h and "reiniciar" not in h and "pend" not in h


def test_icone_acusa_codigo_baixado_sem_restart():
    """Estado 2: o disco já tem o commit novo."""
    h = _roda('versaoHtml({versao:"2026.09.22", versao_detalhe:"x", versao_pendente:true, versao_disco:"abc1234"})')
    assert "reiniciar" in h and "pend" in h and "abc1234" in h


def test_html_novo_com_payload_sem_versao_TAMBEM_acusa():
    """Estado 3. A primeira versão deste ícone devolvia "" aqui — e era exatamente o caso que o Levi
    precisa ver: o HTML só é novo se o `git pull` aconteceu; o payload só é velho se o processo não
    reiniciou. Esconder o ícone nesse caso faria parecer que o commit não subiu."""
    h = _roda('versaoHtml({grupos:[], cache_ts:"13:49:59"})')
    assert "reiniciar" in h and "pend" in h


def test_o_hover_e_escapado():
    """O texto vai num atributo title; aspas ou < ali quebrariam o cabeçalho inteiro."""
    h = _roda("""versaoHtml({versao:"2026.09.22", versao_detalhe:"a'b\\"c<d>", versao_pendente:false})""")
    assert "a'b" not in h and "<d>" not in h and "&#39;" in h and "&lt;d&gt;" in h
