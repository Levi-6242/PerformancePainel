# -*- coding: utf-8 -*-
"""Rondas de Trackers: o QR de pareamento quando o WhatsApp da ronda cai (Levi, 11/10/2026: "quando o whatsapp ficar fora
aparecer o QR code para liberar por ele").

A tela já mostrava o QR desde 14/07, mas quase nunca dava para escanear: o watchdog contava "aguardando QR" como serviço
travado e reiniciava o node a cada ~6,5 min (cada reinício mata o QR), a tela rebaixava a imagem a cada 30 s com o QR
trocando a cada ~20 s, a rota servia o qr.png que o node não apaga ao conectar (em 11/10 era de 05/10), e o web mostrava
envios, log e watchdog lidos uma vez, no boot. O QR é só para administrador do Nexus: quem o escaneia liga a própria conta
ao serviço da ronda. Nada aqui fala com o WhatsApp: o serviço é de mentira.
"""
import json
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

import pytest

import app
import porta_nexus as pn
from test_porta_nexus import _sem_rede, cli, entrar, entrar_com_senha  # noqa: F401  (fixtures e passos da porta)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40 + b"\x00\x00\x00\x00IEND\xaeB`\x82"
TPL = Path(app.__file__).resolve().parent / "templates"


class _Resposta:
    def __init__(self, dados, status_code=200):
        self._dados, self.status_code = dados, status_code

    def json(self):
        return self._dados


class _Servico:
    """O wa_service.js de mentira: só o /status, com o estado que o teste escolhe."""

    def __init__(self):
        self.status = {"ok": True, "status": "conectado", "tem_qr": False}

    def get(self, url, headers=None, timeout=None):
        assert url.startswith("http://127.0.0.1:5099/")
        return _Resposta(self.status)


@pytest.fixture
def servico(monkeypatch, tmp_path):
    s = _Servico()
    monkeypatch.setattr(app, "_http", lambda: s)
    monkeypatch.setattr(app, "_whats_cfg", lambda: {"enabled": True, "service_url": "http://127.0.0.1:5099", "token": "t",
                                                    "grupos": {"Norte": "1@g.us", "Sul": "2@g.us"},
                                                    "horarios": ["08:25", "13:00"]})
    monkeypatch.setattr(app, "_WHATS_QR_PATH", str(tmp_path / "qr.png"))
    monkeypatch.setattr(app, "_WHATS_SENT_PATH", str(tmp_path / "whats_enviados.json"))
    monkeypatch.setattr(app, "_WHATS_LOG_PATH", str(tmp_path / "whats_log.json"))
    monkeypatch.setattr(app, "_WHATS_WD_PATH", str(tmp_path / "whats_watchdog.json"))
    return s


AGUARDANDO = {"ok": True, "status": "aguardando_qr", "tem_qr": True}


# ── o watchdog ───────────────────────────────────────────────────────────────────────────────────────────────────────
def test_aguardando_qr_nao_e_servico_travado():
    assert app._whats_quebrado(200, {"ok": True, "state": "CONNECTED", "status": "conectado"}) is False
    assert app._whats_quebrado(200, {"ok": False, "state": "UNPAIRED", "status": "aguardando_qr"}) is False
    assert app._whats_quebrado(200, {"ok": False, "state": "UNPAIRED_IDLE", "status": "iniciando"}) is False
    assert app._whats_quebrado(200, {"ok": False, "state": None, "status": "aguardando_codigo"}) is False
    # o que segue reiniciando: o getState() que lança (detached Frame), a sessão caída sem QR e a resposta vazia
    assert app._whats_quebrado(500, {"ok": False, "erro": "detached Frame"}) is True
    assert app._whats_quebrado(200, {"ok": False, "state": None, "status": "desconectado: LOGOUT"}) is True
    assert app._whats_quebrado(200, {}) is True


def test_o_botao_reiniciar_conta_no_arquivo_que_o_watchdog_do_worker_le(cli, servico, monkeypatch, tmp_path):
    """O botão roda no web e o watchdog no worker: o reinício pelo botão vai ao arquivo, e o watchdog respeita o
    intervalo de 5 min a partir dele (antes, cada um só via o próprio, e o serviço podia levar dois reinícios seguidos)."""
    monkeypatch.setattr(app, "_whats_service_restart", lambda: True)
    entrar_com_senha(cli)
    r = cli.post("/api/ronda/whats/reiniciar")
    assert r.status_code == 200 and r.get_json()["ok"] is True and "o QR aparece aqui" in r.get_json()["msg"]
    wd = json.loads((tmp_path / "whats_watchdog.json").read_text(encoding="utf-8"))
    assert wd["restarts_hoje"] == 1 and wd["dia"] == datetime.now().strftime("%Y-%m-%d")
    assert time.time() - wd["ultimo_restart"] < 60
    assert app._whats_wd_carregar()["ultimo_restart"] == wd["ultimo_restart"]


# ── a rota do QR ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_o_qr_so_sai_vivo_e_inteiro(cli, servico, tmp_path):
    entrar_com_senha(cli)
    servico.status = dict(AGUARDANDO)
    (tmp_path / "qr.png").write_bytes(PNG)
    r = cli.get("/api/ronda/whats/qr?v=1")
    assert r.status_code == 200 and r.mimetype == "image/png" and r.data == PNG
    assert "no-store" in r.headers["Cache-Control"]
    (tmp_path / "qr.png").write_bytes(PNG[:30])                              # o node no meio da gravação
    assert cli.get("/api/ronda/whats/qr?v=2").status_code == 503
    (tmp_path / "qr.png").write_bytes(PNG)
    servico.status = {"ok": True, "status": "conectado", "tem_qr": False}    # conectou: o qr.png velho não sai
    assert cli.get("/api/ronda/whats/qr?v=3").status_code == 404
    servico.status = dict(AGUARDANDO)
    os.remove(tmp_path / "qr.png")
    assert cli.get("/api/ronda/whats/qr?v=4").status_code == 404


def test_o_qr_so_para_administrador_do_nexus(cli, servico, tmp_path):
    servico.status = dict(AGUARDANDO)
    (tmp_path / "qr.png").write_bytes(PNG)
    assert pn.so_admin("/api/ronda/whats/qr") and not pn.so_admin("/api/ronda/whats/status")
    entrar(cli, "analista@exemplo.com", destino="/ronda/monitor", admin=False)
    r = cli.get("/api/ronda/whats/qr?v=1")
    assert r.status_code == 403 and r.get_json()["error"] == "só administradores do Nexus"
    assert cli.get("/api/ronda/whats/status").status_code == 200              # o estado, todo mundo lê
    entrar(cli, "admin@exemplo.com", destino="/ronda/monitor", admin=True)
    assert cli.get("/api/ronda/whats/qr?v=1").status_code == 200


# ── a rota de estado ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_o_estado_vem_do_disco_e_traz_a_versao_do_qr(cli, servico, tmp_path):
    """Quem envia é o worker: o web lia envios, log e watchdog uma vez, no boot, e a tela dizia "Não enviada" para a ronda
    que tinha saído e "nenhum restart hoje" com o worker reiniciando o serviço."""
    entrar_com_senha(cli)
    hoje = datetime.now().strftime("%Y-%m-%d")
    (tmp_path / "whats_enviados.json").write_text(json.dumps({f"{hoje}|08:25": ["Norte", "Sul"]}), encoding="utf-8")
    (tmp_path / "whats_watchdog.json").write_text(json.dumps({"ultimo_restart": time.time(), "restarts_hoje": 3,
                                                              "dia": hoje}), encoding="utf-8")
    (tmp_path / "whats_log.json").write_text(json.dumps([{"ts": f"{hoje} 08:25:30", "slot": "08:25", "regiao": "Norte",
                                                          "ok": True}]), encoding="utf-8")
    d = cli.get("/api/ronda/whats/status").get_json()
    assert d["enviados_hoje"] == [f"{hoje}|08:25"] and d["watchdog"]["restarts_hoje"] == 3
    assert d["log"][-1]["regiao"] == "Norte" and d["qr_versao"] is None
    servico.status = dict(AGUARDANDO)
    (tmp_path / "qr.png").write_bytes(PNG)
    d = cli.get("/api/ronda/whats/status").get_json()
    assert d["qr_versao"] == int(os.path.getmtime(tmp_path / "qr.png") * 1000)


def test_o_log_nao_apaga_a_linha_do_outro_processo(servico, tmp_path):
    (tmp_path / "whats_log.json").write_text(json.dumps([{"ts": "x", "slot": "08:25", "regiao": "Sul", "ok": True}]),
                                             encoding="utf-8")
    app._whats_log_add(slot="manual", regiao=None, ok=True, trackers=None, info="botão")
    log = json.loads((tmp_path / "whats_log.json").read_text(encoding="utf-8"))
    assert [linha["slot"] for linha in log] == ["08:25", "manual"]


# ── a tela (o JavaScript dela, no node) ──────────────────────────────────────────────────────────────────────────────
def _func(texto: str, nome: str) -> str:
    i = texto.index("function " + nome + "(")
    return texto[i:texto.index("\n}\n", i) + 3]


_NAVEGADOR = r"""
const ELS = {}; let atribuicoes = 0;
function E(id) { if (!ELS[id]) { const el = { id, textContent: "", innerHTML: "", className: "", style: {}, dataset: {}, attrs: {} };
  Object.defineProperty(el, "src", { get() { return el.attrs.src || ""; }, set(v) { atribuicoes++; el.attrs.src = v; } });
  el.removeAttribute = n => { delete el.attrs[n]; }; ELS[id] = el; } return ELS[id]; }
const document = { getElementById: E, visibilityState: "visible" };
const window = { gcSessaoDaPlataforma: { semAdmin: false } };
const timers = []; globalThis.setTimeout = (f, ms) => { timers.push(ms); return timers.length; }; globalThis.clearTimeout = () => {};
let SVC_RAPIDO = null;
"""
_ROTEIRO = r"""
const passos = [];
function foto() { return { src: E("svcQr").attrs.src || null, caixa: E("svcQrBox").style.display, botao: E("btnReiniciar").style.display,
  soAdm: E("svcQrSoAdmin").style.display, sub: E("svcSub").textContent, atribuicoes }; }
svcBadge({ servico: { status: "aguardando_qr", tem_qr: true }, qr_versao: 111 }); passos.push(foto());
svcBadge({ servico: { status: "aguardando_qr", tem_qr: true }, qr_versao: 111 }); passos.push(foto());
svcBadge({ servico: { status: "aguardando_qr", tem_qr: true }, qr_versao: 222 }); passos.push(foto());
svcBadge({ servico: { status: "conectado" } }); passos.push(foto());
window.gcSessaoDaPlataforma.semAdmin = true;
svcBadge({ servico: { status: "aguardando_qr", tem_qr: true }, qr_versao: 333 }); passos.push(foto());
process.stdout.write(JSON.stringify({ passos, timers }));
"""


def test_a_tela_troca_o_qr_so_quando_ele_muda_e_esconde_de_quem_nao_e_admin(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node não instalado")
    h = (TPL / "ronda_monitor.html").read_text(encoding="utf-8")
    js = _NAVEGADOR + "".join(_func(h, n) for n in ("semAdminQr", "urlQr", "qrFalhou", "svcRapido", "svcBadge")) + _ROTEIRO
    arq = tmp_path / "tela.js"
    arq.write_text(js, encoding="utf-8")
    r = subprocess.run([node, str(arq)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    p = d["passos"]
    assert p[0]["src"] == "/api/ronda/whats/qr?v=111" and p[0]["caixa"] == "" and p[0]["atribuicoes"] == 1
    assert p[0]["botao"] == "none" and "escaneie o QR abaixo" in p[0]["sub"]       # reiniciar mataria o QR à vista
    assert p[1]["atribuicoes"] == 1                                                # o mesmo QR não é baixado de novo
    assert p[2]["src"] == "/api/ronda/whats/qr?v=222" and p[2]["atribuicoes"] == 2
    assert p[3]["src"] is None and p[3]["caixa"] == "none" and p[3]["botao"] == "none"
    assert p[4]["src"] is None and p[4]["caixa"] == "none" and p[4]["soAdm"] == ""   # quem não é admin: o aviso
    assert p[4]["botao"] == "inline-block" and "escaneie" not in p[4]["sub"]
    assert d["timers"] and set(d["timers"]) == {5000}                             # relê a cada 5 s enquanto não conecta
