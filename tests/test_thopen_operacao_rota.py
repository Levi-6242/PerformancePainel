# -*- coding: utf-8 -*-
"""Rota da Operação no Mês (Dashboard Thopen, 08/10/2026): só agregados, parâmetro validado, chave que desliga, e o
import do dashboard continua sem rede e sem thread (a plataforma importa este módulo a cada deploy do servidor)."""
import importlib.util
import os
import re
import subprocess
import sys
import zipfile

import pytest

AQUI = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(AQUI, "..", "thopen"))
import dashboard_thopen as dth  # noqa: E402
import fonte_operacao  # noqa: E402
import operacao_mes  # noqa: E402

# rodada 2 (08/10, tarde): as strings vêm das OS de recomposição de string, pela data do evento
D = {"strings_episodios": [], "trackers_episodios": [], "cobertura": [],
     "atualizacao": [{"mes": "2026-10", "periodo_fim": "2026-10-08", "atualizado_em": "2026-10-08 10:05",
                      "strings_os": 1, "trackers_dia": 0}],
     "strings_os": [{"mes": "2026-10", "data_evento": "2026-10-02", "cliente": "Thopen", "usina": "Altair",
                     "plant_id": "1", "inversor": "Inversor 1.1", "os": "15221", "status": "Concluída",
                     "strings": "Ipv1", "qtd": 1, "origem": "texto"}],
     "trackers_dia": [], "rondas_com_os": [], "rondas_sem_os": [], "de_para": []}


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(fonte_operacao, "dados", lambda *a, **k: D)
    monkeypatch.delenv("THOPEN_OPERACAO", raising=False)
    return dth.app.test_client()


def test_responde_so_as_chaves_da_lista_branca(cli):
    r = cli.get("/api/t/operacao?usina=Altair&ano=2026&mes=10")
    assert r.status_code == 200
    # o Flask pode devolver as chaves ordenadas: o que importa é o CONJUNTO ser exatamente CHAVES
    assert set(r.get_json()) == set(operacao_mes.CHAVES)
    assert r.get_json()["strings"] == 1
    assert r.get_json()["por_dia"] == [{"dia": "02/10", "strings": 1, "trackers": None, "disp": None, "ronda": None,
                                        "os": []}]
    # o número da OS e o status ficam no servidor: o 5080 é público, sem senha
    assert b"15221" not in r.data and "Concluída".encode() not in r.data


@pytest.mark.parametrize("q", ["usina=Altair&ano=2026&mes=abc", "usina=Altair&ano=2026&mes=13", "ano=2026&mes=10",
                               "usina=Altair&ano=x&mes=10"])
def test_parametro_invalido_e_400_e_nao_500(cli, q):
    r = cli.get("/api/t/operacao?" + q)
    assert r.status_code == 400 and r.get_json()["erro"]


def test_chave_desliga(cli, monkeypatch):
    monkeypatch.setenv("THOPEN_OPERACAO", "0")
    r = cli.get("/api/t/operacao?usina=Altair&ano=2026&mes=10").get_json()
    assert r["disponivel"] is False and r["motivo"] == "desligado"


def test_import_do_dashboard_nao_abre_rede_nem_thread():
    codigo = ("import socket, sys, threading; "
              "socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError('rede no import')); "
              "sys.path.insert(0, %r); import dashboard_thopen; "
              "assert not [t for t in threading.enumerate() if t.name == 'thopen-operacao']"
              % os.path.join(AQUI, "..", "thopen"))
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]


# ── instalador por zip (thopen/deploy/_package_thopen.py) ──────────────────────────────────────────────────────────
RAIZ = os.path.join(AQUI, "..")
THOPEN = os.path.join(RAIZ, "thopen")


def _pacote():
    spec = importlib.util.spec_from_file_location("_package_thopen", os.path.join(THOPEN, "deploy", "_package_thopen.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                     # sem gerar o zip: o main() só roda chamado como script
    return mod


def _locais_importados(nome, vistos=None):
    """Os módulos de thopen/ que `nome` importa, de forma transitiva (o dashboard → fonte_operacao → operacao_mes)."""
    vistos = set() if vistos is None else vistos
    locais = {f[:-3] for f in os.listdir(THOPEN) if f.endswith(".py")}
    src = open(os.path.join(THOPEN, nome + ".py"), encoding="utf-8").read()
    for m in re.findall(r"^\s*(?:import|from)\s+(\w+)", src, re.M):
        if m in locais and m not in vistos:
            vistos.add(m)
            _locais_importados(m, vistos)
    return vistos


def test_instalador_por_zip_leva_todo_modulo_que_o_dashboard_importa():
    # rodada 1 (08/10): o zip ainda levava só 3 arquivos e o dashboard já importava fonte_operacao e operacao_mes —
    # instalado à mão, o app nem subia (ModuleNotFoundError no import)
    itens = {o for o, _ in _pacote().ITENS}
    precisa = {"thopen/%s.py" % m for m in _locais_importados("dashboard_thopen")}
    assert {"thopen/fonte_api.py", "thopen/fonte_operacao.py", "thopen/operacao_mes.py"} <= precisa
    assert precisa <= itens, precisa - itens


def test_zip_gerado_tem_os_oito_arquivos_e_as_variaveis_da_operacao(tmp_path, monkeypatch):
    mod = _pacote()
    monkeypatch.setattr(mod, "OUT", str(tmp_path / "thopen-app.zip"))
    mod.main()
    with zipfile.ZipFile(mod.OUT) as z:
        nomes = set(z.namelist())
        leiame = z.read("README.md").decode("utf-8")
    # rodada 3 (09/10): + rondas_cliente e fotos_ronda (a janela das rondas); rodada 4: + contestacao
    app = {"thopen/dashboard_thopen.py", "thopen/fonte_api.py", "thopen/fonte_operacao.py", "thopen/operacao_mes.py",
           "thopen/rondas_cliente.py", "thopen/fotos_ronda.py", "thopen/contestacao.py",
           "thopen/contestacao_banco.py", "thopen/acessos.py", "thopen/livro_banco.py", "thopen/geracao_possivel.py",
           "thopen/templates/dashboard_thopen.html", "thopen/templates/entrar.html"}
    assert app <= nomes and not any("cache" in n for n in nomes)
    assert "treze arquivos" in leiame and "doze arquivos" not in leiame
    for v in ("THOPEN_OPERACAO", "THOPEN_OPERACAO_TTL", "THOPEN_OPERACAO_CACHE", "THOPEN_RONDAS",
              "FRACTTAL_CLIENT_ID", "FRACTTAL_CLIENT_SECRET", "THOPEN_TEAMS_PERFORMANCE", "THOPEN_TEAMS_COS",
              "THOPEN_TEAMS_ZELADORIA", "THOPEN_CONTESTACAO_CHAVE_PUBLICA", "GRIDCO_SQL_TOKEN", "THOPEN_LOGIN",
              "THOPEN_PREFIXO", "THOPEN_ACESSOS_CHAVE_PRIVADA", "THOPEN_SESSAO_CHAVE", "THOPEN_COOKIE_SEGURO"):
        assert re.search(r"^\s*%s\s" % v, leiame, re.M), v


def test_comentarios_da_nuvem_dizem_oito_arquivos():
    for arq in ("railway.toml", "render.yaml"):
        txt = open(os.path.join(RAIZ, arq), encoding="utf-8").read()
        assert "12 arquivos" not in txt and "13 arquivos" in txt, arq
        for m in ("fonte_operacao", "operacao_mes", "rondas_cliente", "fotos_ronda", "contestacao", "contestacao_banco",
                  "acessos", "livro_banco", "geracao_possivel"):
            assert "thopen/%s.py" % m in txt, (arq, m)


def test_de_outubro_em_diante_o_diario_nao_manda_o_comentario_da_equipe(cli, monkeypatch):
    # 14/10/2026, noite (Levi: "A partir de outubro quero os comentários 100% OS Fracttal. Comentários e
    # disponibilidade! Antes deixe como estava!")
    import datetime as dt
    recs = [{"data": dt.date(2026, m, 2), "ger": 100.0, "ipoa": 5.0, "disp": 0.0, "com": "Desligamento usina - X"}
            for m in (9, 10)]
    monkeypatch.setattr(dth, "_daily_records", lambda u: list(recs))
    monkeypatch.setattr(dth, "_meta2026", lambda u: {})
    out = cli.get("/api/t/diario?usina=Altair&ano=2026&mes=10").get_json()
    assert out["pontos"][0]["com"] is None and out["comentarios"] == [] and out["kpis"]["disp"] is None
    set_ = cli.get("/api/t/diario?usina=Altair&ano=2026&mes=9").get_json()     # setembro: como estava
    assert set_["pontos"][0]["com"] == "Desligamento usina - X" and set_["comentarios"] and set_["kpis"]["disp"] == 0.0


def test_visao_geral_de_outubro_usa_a_disponibilidade_do_gerencial(cli, monkeypatch):
    # a Visão Geral de outubro mostrava a Altair com 0,0% (a disponibilidade do BD_Thopen ainda não preenchida)
    import datetime as dt
    recs = [{"data": dt.date(2026, m, 2), "ger": 100.0, "ipoa": 5.0, "disp": 0.0, "com": None} for m in (9, 10)]
    monkeypatch.setattr(dth, "_daily_records", lambda u: list(recs))
    monkeypatch.setattr(dth, "_meta2026", lambda u: {})
    monkeypatch.setattr(operacao_mes, "disp_por_dia", lambda d, u, a, m: {dt.date(a, m, 1): 90.0, dt.date(a, m, 2): 100.0})
    assert dth._resumo_usina("Altair", 2026, 10)["disp"] == pytest.approx(0.95)
    assert dth._resumo_usina("Altair", 2026, 9)["disp"] == 0.0                   # setembro: o BD, como estava
    monkeypatch.setenv("THOPEN_OPERACAO", "0")
    assert dth._resumo_usina("Altair", 2026, 10)["disp"] is None                 # sem a fonte: "—", nunca o 0 do BD
