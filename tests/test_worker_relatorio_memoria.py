# -*- coding: utf-8 -*-
"""O relatório de memória do worker, que o Raio-X do Nexus mostra (Desempenho, 20/10/2026).

No servidor o worker foi de 3,7 para 5,0 GB (com o swap) em 26 min, entre 16:12 e 16:38 de 20/10, e o Nexus travou
esperando o disco. A medição de dentro (sys.remote_exec) só dá no PC, que não roda os backfills do servidor; quem cresce
lá ninguém via. Levi escolheu ver no Raio-X: a cada passada do faxineiro (10 min) o worker estima, por amostra e com
teto de tempo, quanto cada cache ocupa e grava um JSON pequeno em /dev/shm (a memória compartilhada da máquina: o Nexus
lê sem configuração), com o histórico das últimas 3 h. Não muda nenhum dado. Aqui a pasta é a do teste."""
import json

import app

ARQ = app.RELATORIO_MEMORIA_ARQ


def _limpo(monkeypatch, status="VmRSS:\t 3000000 kB\nVmSwap:\t  400000 kB\n"):
    monkeypatch.setattr(app, "_RELATORIO_MEMORIA", [])
    monkeypatch.setattr(app, "_ler_status_proprio", lambda: status)


def test_o_relatorio_aponta_o_cache_maior_e_a_memoria_do_processo(monkeypatch, tmp_path):
    _limpo(monkeypatch)
    monkeypatch.setattr(app, "_cache_de_teste_grande",
                        {i: [{"x": "10:%02d" % (j % 60), "y": float(j)} for j in range(2000)] for i in range(50)},
                        raising=False)
    app._relatorio_memoria_worker(pasta=str(tmp_path))
    j = json.loads((tmp_path / ARQ).read_text(encoding="utf-8"))
    assert (j["rss_mb"], j["swap_mb"]) == (2930, 391)
    maior = j["caches"][0]
    assert maior["nome"] == "app._cache_de_teste_grande" and maior["itens"] == 50
    assert 15 < maior["mb"] < 35                                    # ~24 MB de verdade (100 mil pontos {x, y})
    assert j["historico"][-1]["caches"]["app._cache_de_teste_grande"] == maior["mb"]


def test_o_historico_mostra_o_que_cresceu_e_tem_teto(monkeypatch, tmp_path):
    _limpo(monkeypatch)
    cache = {}
    monkeypatch.setattr(app, "_cache_de_teste_grande", cache, raising=False)
    for volta in range(app._RELATORIO_HISTORICO + 3):
        cache[volta] = [{"x": "10:00", "y": float(k)} for k in range(20000)]       # cresce a cada passada
        app._relatorio_memoria_worker(pasta=str(tmp_path))
    hist = json.loads((tmp_path / ARQ).read_text(encoding="utf-8"))["historico"]
    assert len(hist) == app._RELATORIO_HISTORICO                    # as últimas 3 h, não o dia inteiro
    serie = [h["caches"].get("app._cache_de_teste_grande", 0) for h in hist]
    assert serie == sorted(serie) and serie[-1] > serie[0] * 1.2


def test_o_relatorio_nao_percorre_o_cache_inteiro(monkeypatch, tmp_path):
    """Por amostra: o worker inchado está justamente onde percorrer tudo custaria segundos de processador (e, no swap,
    disco). Com 200 mil itens, o relatório olha só uma amostra e multiplica."""
    _limpo(monkeypatch)
    olhados = {"n": 0}

    class Ponto:
        __slots__ = ()

        def __sizeof__(self):
            olhados["n"] += 1
            return 1000

    monkeypatch.setattr(app, "_cache_de_teste_grande", [Ponto() for _ in range(200_000)], raising=False)
    app._relatorio_memoria_worker(pasta=str(tmp_path))
    j = json.loads((tmp_path / ARQ).read_text(encoding="utf-8"))
    assert olhados["n"] < 1000
    assert 180 < next(c["mb"] for c in j["caches"] if c["nome"] == "app._cache_de_teste_grande") < 210   # ~190 MB


def test_o_nexus_pode_ler_o_arquivo(monkeypatch, tmp_path):
    """O Nexus roda como outro usuário (`nexus`), e o mkstemp cria o arquivo só para o dono: 0644 antes de trocar."""
    _limpo(monkeypatch)
    modos = []
    monkeypatch.setattr(app.os, "fchmod", lambda fd, modo: modos.append(modo), raising=False)
    app._relatorio_memoria_worker(pasta=str(tmp_path))
    assert modos == [0o644] and [p.name for p in tmp_path.iterdir()] == [ARQ]


class _Morreu(BaseException):
    """O processo morto no meio da gravação (o reinício do deploy): nenhum `except` roda."""


def test_o_arquivo_so_aparece_inteiro(monkeypatch, tmp_path):
    """Gravado com outro nome e trocado de uma vez: a gravação que quebra no meio não deixa o relatório pela metade para
    o Raio-X ler. Com erro, o provisório sai; com o processo morto, o relatório anterior continua inteiro no lugar."""
    import pytest
    _limpo(monkeypatch)
    app._relatorio_memoria_worker(pasta=str(tmp_path))
    bom = (tmp_path / ARQ).read_text(encoding="utf-8")
    dump = app.json.dump

    def quebra(obj, f, **k):
        f.write('{"quando": "2026-10-20T16:')
        raise OSError("disco cheio")
    monkeypatch.setattr(app.json, "dump", quebra)
    with pytest.raises(OSError):
        app._relatorio_memoria_worker(pasta=str(tmp_path))
    assert [p.name for p in tmp_path.iterdir()] == [ARQ] and (tmp_path / ARQ).read_text(encoding="utf-8") == bom

    def morre(obj, f, **k):
        f.write('{"quando": "2026-10-20T16:')
        raise _Morreu()
    monkeypatch.setattr(app.json, "dump", morre)
    with pytest.raises(_Morreu):
        app._relatorio_memoria_worker(pasta=str(tmp_path))
    monkeypatch.setattr(app.json, "dump", dump)
    assert json.loads((tmp_path / ARQ).read_text(encoding="utf-8")) == json.loads(bom)   # o anterior, inteiro


def test_fora_do_linux_nao_grava(monkeypatch, tmp_path):
    _limpo(monkeypatch)
    monkeypatch.setattr(app._sys, "platform", "win32")
    assert app._pasta_relatorio() is None and app._relatorio_memoria_worker() is None


def test_o_faxineiro_anota_depois_de_devolver(monkeypatch):
    ordem = []

    class _Para(BaseException):
        pass
    voltas = {"n": 0}

    class _Tempo:
        def __getattr__(self, nome):
            import time
            return getattr(time, nome)

        @staticmethod
        def sleep(_s):
            voltas["n"] += 1
            if voltas["n"] > 1:
                raise _Para()
    monkeypatch.setattr(app, "_janitor_passada", lambda: ordem.append("passada") or "")
    monkeypatch.setattr(app, "_devolve_memoria", lambda: ordem.append("devolve"))
    monkeypatch.setattr(app, "_relatorio_memoria_worker", lambda *a, **k: ordem.append("relatorio"))
    monkeypatch.setattr(app, "time", _Tempo())
    try:
        app._janitor_loop(intervalo=0)
    except _Para:
        pass
    assert ordem == ["passada", "devolve", "relatorio"]
