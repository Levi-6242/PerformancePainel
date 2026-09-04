# gemeo/gemeo/app/server.py
"""`gemeo app`: Flask so-leitura sob o prefixo /gemeo (rotas e assets relativos a ele), servido por waitress em
127.0.0.1:<porta>. A plataforma faz proxy de /gemeo/* e manda a senha compartilhada no header X-Gemeo-Senha;
quem chega direto usa a tela de login (sessao). O app nao sabe que esta atras do proxy."""
from __future__ import annotations
import datetime as dt
import hashlib
import hmac
from pathlib import Path

from flask import Flask, g, jsonify, redirect, render_template, request, session

from gemeo.app import consultas, formato

PREFIXO = "/gemeo"
AQUI = Path(__file__).resolve().parent


def _agora() -> dt.datetime:
    """'agora' vem da query string quando pedido (viagem no tempo para testar e depurar); `dia=AAAA-MM-DD` congela no fim
    daquele dia (usinas do piloto: UTC-3, sem horario de verao); senao, UTC real."""
    d = request.args.get("dia")
    if d:
        try:
            return dt.datetime.combine(dt.date.fromisoformat(d), dt.time(23, 59, 59), tzinfo=dt.timezone(dt.timedelta(hours=-3)))
        except ValueError:
            pass
    q = request.args.get("agora")
    if q:
        try:
            t = dt.datetime.fromisoformat(q.replace("Z", "+00:00"))
            return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            pass
    return dt.datetime.now(dt.timezone.utc)


def criar_app(cfg, conectar=None) -> Flask:
    app = Flask(__name__, static_url_path=f"{PREFIXO}/static", static_folder=str(AQUI / "static"), template_folder=str(AQUI / "templates"))
    app.secret_key = hashlib.sha256(("gemeo-" + cfg.senha_app).encode()).hexdigest()
    app.config["CONECTAR"] = conectar
    app.config["FECHAR_CONEXAO"] = conectar is None     # conexao injetada (testes) nao e nossa para fechar
    app.jinja_env.filters.update(num=formato.num, mw=formato.mw, pct=formato.pct, brl=formato.brl)
    app.jinja_env.globals.update(PREFIXO=PREFIXO)

    def conn():
        if "conn" not in g:
            if app.config["CONECTAR"]:
                g.conn = app.config["CONECTAR"]()
            else:
                from gemeo.core import db
                g.conn = db.conectar(cfg.db_caminho)
        return g.conn

    @app.teardown_appcontext
    def _fecha(exc):
        c = g.pop("conn", None)
        if c is None:
            return
        try:
            c.rollback()                                    # so-leitura: nunca deixa transacao aberta
        except Exception:                                   # noqa: BLE001
            pass
        if app.config["FECHAR_CONEXAO"]:
            try:
                c.close()
            except Exception:                               # noqa: BLE001
                pass

    def autenticado() -> bool:
        cab = request.headers.get("X-Gemeo-Senha", "")
        return bool(session.get("ok")) or (bool(cab) and hmac.compare_digest(cab, cfg.senha_app))

    @app.before_request
    def _gate():
        p = request.path
        if p in (f"{PREFIXO}/login", f"{PREFIXO}/healthz") or p.startswith(f"{PREFIXO}/static/"):
            return None
        if not p.startswith(PREFIXO):
            return redirect(f"{PREFIXO}/")
        if autenticado():
            return None
        if p.startswith(f"{PREFIXO}/api/"):
            return jsonify({"erro": "não autenticado"}), 401
        return redirect(f"{PREFIXO}/login?next={p}")

    @app.route(f"{PREFIXO}/login", methods=["GET", "POST"])
    def login():
        erro = ""
        if request.method == "POST":
            if hmac.compare_digest((request.form.get("senha") or "").strip(), cfg.senha_app):
                session.permanent = True
                session["ok"] = True
                nxt = request.args.get("next") or f"{PREFIXO}/"
                return redirect(nxt if nxt.startswith(PREFIXO + "/") else f"{PREFIXO}/")
            erro = "Senha incorreta"
        return render_template("login.html", erro=erro), (401 if erro else 200)

    @app.route(f"{PREFIXO}/logout")
    def logout():
        session.clear()
        return redirect(f"{PREFIXO}/login")

    def _vivo() -> dict:
        """Sem dia/agora na URL a tela e ao vivo: auto-refresh de 5 min; com dia escolhido, fica parada nele."""
        return {"auto": "agora" not in request.args and "dia" not in request.args, "dia_sel": request.args.get("dia", "")}

    @app.route(f"{PREFIXO}/")
    def frota():
        agora = _agora()
        return render_template("frota.html", d=consultas.frota(conn(), agora), agora=agora, **_vivo())

    PERIODOS = {"dia": 1, "semana": 7, "mes": 30}

    def _usina(usina_id: int, agora: dt.datetime):
        dias = PERIODOS.get(request.args.get("periodo", "dia"), 1)
        return consultas.usina(conn(), usina_id, agora) if dias == 1 else consultas.usina_periodo(conn(), usina_id, agora, dias)

    @app.route(f"{PREFIXO}/usina/<int:usina_id>")
    def usina(usina_id: int):
        agora = _agora()
        d = _usina(usina_id, agora)
        if d is None:
            return "usina não encontrada", 404
        return render_template("usina.html", d=d, agora=agora, periodo=request.args.get("periodo", "dia"), **_vivo())

    @app.route(f"{PREFIXO}/api/frota")
    def api_frota():
        return jsonify(consultas.frota(conn(), _agora()))

    @app.route(f"{PREFIXO}/api/usina/<int:usina_id>")
    def api_usina(usina_id: int):
        d = _usina(usina_id, _agora())
        return (jsonify(d), 200) if d else (jsonify({"erro": "usina não encontrada"}), 404)

    @app.route(f"{PREFIXO}/healthz")
    def healthz():
        try:
            s = consultas.saude(conn(), cfg, _agora())
        except Exception as e:                              # noqa: BLE001 — sem banco a resposta e o diagnostico
            s = {"ok": False, "banco": False, "erro": f"{type(e).__name__}: {e}"[:200]}
        return jsonify(s), (200 if s.get("ok") else 503)

    return app


def servir() -> int:
    from waitress import serve
    from gemeo.core.config import carregar
    cfg = carregar()
    app = criar_app(cfg)
    print(f"gemeo app em http://127.0.0.1:{cfg.porta_app}{PREFIXO}/", flush=True)
    serve(app, host="127.0.0.1", port=cfg.porta_app, threads=4)
    return 0
