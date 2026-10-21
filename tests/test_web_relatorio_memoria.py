# -*- coding: utf-8 -*-
"""O web da plataforma também se mede (Desempenho, 21/10/2026).

Raio-X do Nexus às 14:55 de 21/10: o processo WEB da plataforma foi de 0,8 GB às 14:36 para 3,1 GB e 0,7 GB no swap,
com a máquina sem memória (0,2 GB livres, o disco ocupado 71% do tempo, um pedido do Nexus 3,5 min preso esperando a
memória voltar do disco). O relatório de memória e a devolução ao sistema só rodavam no worker: o que o web guarda ninguém
via. Agora o web grava o mesmo relatório, no arquivo dele, e devolve a memória livre a cada 10 min, com no máximo 2
arenas de malloc. Não descarta cache nenhum (o faxineiro segue só no worker). A libc e a pasta aqui são de mentira."""
import json
import pathlib
import time

import pytest

import app


class _Para(BaseException):
    """Tira o laço infinito do teste (não é Exception: o laço engole Exception)."""


def _relogio(voltas: int):
    conta = {"n": 0}

    class _Tempo:
        def __getattr__(self, nome):
            return getattr(time, nome)

        @staticmethod
        def sleep(_s):
            conta["n"] += 1
            if conta["n"] > voltas:
                raise _Para()
    return _Tempo()


def test_o_web_grava_no_arquivo_dele_e_nao_no_do_worker(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "_RELATORIO_MEMORIA", [])
    monkeypatch.setattr(app, "_ler_status_proprio", lambda: "VmRSS:\t 3214336 kB\nVmSwap:\t  761856 kB\n")
    app._relatorio_memoria_worker(pasta=str(tmp_path), arquivo=app.RELATORIO_MEMORIA_ARQ_WEB)
    assert [p.name for p in tmp_path.iterdir()] == [app.RELATORIO_MEMORIA_ARQ_WEB]
    assert app.RELATORIO_MEMORIA_ARQ_WEB != app.RELATORIO_MEMORIA_ARQ
    j = json.loads((tmp_path / app.RELATORIO_MEMORIA_ARQ_WEB).read_text(encoding="utf-8"))
    assert (j["rss_mb"], j["swap_mb"]) == (3139, 744)


def test_o_web_devolve_a_memoria_e_anota_a_cada_volta(monkeypatch):
    """E o relatório que falha não derruba o laço: a volta seguinte anota de novo."""
    ordem = []

    def relatorio(*a, **k):
        ordem.append(("relatorio", k.get("arquivo")))
        if len(ordem) == 2:
            raise OSError("disco cheio")
    monkeypatch.setattr(app, "_devolve_memoria", lambda: ordem.append("devolve"))
    monkeypatch.setattr(app, "_relatorio_memoria_worker", relatorio)
    monkeypatch.setattr(app, "time", _relogio(2))
    with pytest.raises(_Para):
        app._memoria_web_loop(intervalo=0)
    web = ("relatorio", app.RELATORIO_MEMORIA_ARQ_WEB)
    assert ordem == ["devolve", web, "devolve", web]


def test_o_web_limita_as_arenas_e_sobe_o_relatorio_junto_com_as_vigias():
    """A subida do web mora no `__main__` (não roda num teste): confere-se o trecho dele, como o teste das travas
    (tests/test_trancadas_recarga.py) já faz."""
    src = pathlib.Path(app.__file__).read_text(encoding="utf-8")
    web = src[src.index("_MODO_WEB = True"):]
    web = web[:web.index("from waitress import serve")]
    assert "target=_memoria_web_loop" in web
    assert web.index("_limita_arenas()") < web.index("threading.Thread(")      # antes de qualquer thread do web
    assert "_janitor_loop" not in web                                           # o web não descarta cache (trackers)
