# -*- coding: utf-8 -*-
"""O worker devolve ao Linux a memória que já soltou (Desempenho, 20/10/2026).

Raio-X do Nexus no servidor: às 14:17 de 20/10 a máquina (7,1 GB) tinha 0,2 GB livres e 3,2 GB no swap; às 14:45 o
worker.py ocupava 3 GB, quase metade dela. Medido dentro do worker do PC às 15:18, os dados somavam ~3,1 GB dos 4,4 GB
privados: o resto é o próprio processo, inclusive a memória já liberada que o alocador guarda para si. No Linux (glibc,
o servidor): no máximo 2 arenas de malloc (sem limite, as ~30 threads do worker abrem até 8 por núcleo e a sobra fica
espalhada nelas) e, depois de cada passada do faxineiro, `malloc_trim(0)` devolve ao sistema o que está livre. Não muda
nenhum dado. Fora do Linux (o PC) nada acontece. A libc aqui é de mentira: o efeito se mede no servidor, pela seção
"Quem ocupa a memória da máquina" do Raio-X do Nexus."""
import time

import pytest

import app
import worker


class _LibcFalsa:
    def __init__(self):
        self.chamadas = []

    def mallopt(self, parametro, valor):
        self.chamadas.append(("mallopt", parametro, valor))
        return 1

    def malloc_trim(self, folga):
        self.chamadas.append(("malloc_trim", folga))
        return 1


class _Para(BaseException):
    """Tira o laço infinito do teste (não é Exception: o laço engole Exception)."""


def _relogio(voltas: int):
    """O módulo time de verdade, com um sleep que deixa passar `voltas` vezes e depois para o laço."""
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


def test_o_faxineiro_devolve_a_memoria_depois_de_cada_passada(monkeypatch):
    libc, passadas = _LibcFalsa(), []
    monkeypatch.setattr(app, "_libc_linux", lambda: libc)
    monkeypatch.setattr(app, "_janitor_passada", lambda: passadas.append(len(libc.chamadas)) or "")
    monkeypatch.setattr(app, "time", _relogio(2))
    with pytest.raises(_Para):
        app._janitor_loop(intervalo=0)
    assert passadas == [0, 1]                                       # a devolução vem DEPOIS de cada passada
    assert libc.chamadas == [("malloc_trim", 0), ("malloc_trim", 0)]


def test_o_worker_limita_as_arenas_antes_de_tudo(monkeypatch):
    ordem = []
    monkeypatch.setattr(app, "_limita_arenas", lambda *a, **k: ordem.append("arenas") or True)
    monkeypatch.setattr(app, "_carregar_estado_do_disco", lambda: ordem.append("estado"))
    monkeypatch.setattr(app, "_iniciar_loops_de_fundo", lambda: ordem.append("threads"))
    monkeypatch.setattr(worker, "time", _relogio(0))
    with pytest.raises(_Para):
        worker.main()
    assert ordem == ["arenas", "estado", "threads"]                 # o limite vale para as arenas que as threads abrem


def test_no_linux_pede_2_arenas_e_a_devolucao_a_glibc(monkeypatch):
    libc = _LibcFalsa()
    monkeypatch.setattr(app._sys, "platform", "linux")
    monkeypatch.setattr(app.ctypes, "CDLL", lambda nome: libc if nome == "libc.so.6" else None)
    assert app._limita_arenas() is True
    app._devolve_memoria()
    assert libc.chamadas == [("mallopt", -8, 2), ("malloc_trim", 0)]    # -8 = M_ARENA_MAX da glibc


def test_fora_do_linux_nada_muda(monkeypatch):
    monkeypatch.setattr(app._sys, "platform", "win32")
    monkeypatch.setattr(app.ctypes, "CDLL", lambda nome: pytest.fail("fora do Linux não carrega libc nenhuma"))
    assert app._libc_linux() is None and app._limita_arenas() is False
    app._devolve_memoria()                                          # não levanta


def test_libc_que_nao_carrega_nao_derruba_o_worker(monkeypatch):
    def sem_libc(nome):
        raise OSError("libc.so.6: cannot open shared object file")
    monkeypatch.setattr(app._sys, "platform", "linux")
    monkeypatch.setattr(app.ctypes, "CDLL", sem_libc)
    assert app._libc_linux() is None and app._limita_arenas() is False
    app._devolve_memoria()
