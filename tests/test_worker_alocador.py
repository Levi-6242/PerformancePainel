# -*- coding: utf-8 -*-
"""O worker sobe com o alocador da glibc no Linux (auditoria do worker, 02/11/2026, achado 8).

O caso: o worker limita a glibc a 2 arenas e chama `malloc_trim` a cada 10 min (20/10/2026), mas objeto de até 512 B,
quase todo ponto de curva, vem do pymalloc, o alocador próprio do Python: blocos de 1 MiB que nem o limite nem o trim
tocam, e que só voltam ao sistema 100% vazios. No PC, em 20/10, ~1,3 GB dos 4,4 GB do worker eram essa sobra. Com
`PYTHONMALLOC=malloc` tudo passa pela glibc, onde o trim já devolve as páginas livres. O efeito se mede no Raio-X.
"""
import sys

import worker


def _chamadas():
    feitas = []
    return feitas, lambda exe, argv: feitas.append((exe, list(argv)))


def test_no_linux_o_worker_se_reinicia_com_o_malloc_da_glibc():
    env, (feitas, executar) = {}, _chamadas()
    worker._alocador_do_sistema(environ=env, plataforma="linux", executar=executar)
    assert env["PYTHONMALLOC"] == "malloc"
    assert len(feitas) == 1 and feitas[0][0] == sys.executable


def test_ja_reiniciado_nao_reinicia_de_novo():
    feitas, executar = _chamadas()
    worker._alocador_do_sistema(environ={"PYTHONMALLOC": "malloc"}, plataforma="linux", executar=executar)
    assert feitas == []


def test_fora_do_linux_e_com_a_volta_nada_muda():
    for env, plataforma in (({}, "win32"), ({"GRIDCO_PYMALLOC": "1"}, "linux")):
        feitas, executar = _chamadas()
        worker._alocador_do_sistema(environ=env, plataforma=plataforma, executar=executar)
        assert feitas == [] and "PYTHONMALLOC" not in env, plataforma
