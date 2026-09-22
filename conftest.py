# conftest.py — fixtures compartilhadas dos testes (Fase 1: funções puras de app.py).
#
# Fica na RAIZ do projeto de propósito: o pytest insere o diretório de cada
# conftest.py no sys.path, então `import app` funciona sem instalar nada.
#
# GOTCHA (ver memória testes-automatizados-plano): `import app` NÃO é limpo — no
# topo do módulo ele roda load_equipamentos()/load_metas()/load_tickets_trackers(),
# que leem BD_Performance.xlsx. Local funciona (o xlsx está na pasta). Para CI seria
# preciso esconder essas cargas atrás de função ou commitar um xlsx-fixture pequeno.
import os
import sys
from datetime import datetime as _real_datetime

import pytest

# o código da plataforma vive em plataforma/ desde a separação por projeto
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "plataforma"))

import app  # noqa: E402  (carga pesada única; roda as cargas do BD_Performance local)


@pytest.fixture
def freeze_now(monkeypatch):
    """Congela app.datetime.now() num instante fixo, sem mexer no resto da classe.

    Várias funções puras (curva ETM, acumulador de trackers, janela de sol) leem
    datetime.now(). Como app.py faz `from datetime import datetime`, basta trocar o
    nome `datetime` DO MÓDULO app por uma subclasse que sobrescreve só o now() —
    strptime/strftime continuam reais. Devolve o datetime congelado.
    """
    def _apply(when):
        if isinstance(when, str):
            when = _real_datetime.strptime(when, "%Y-%m-%d %H:%M:%S")

        class _Frozen(_real_datetime):
            @classmethod
            def now(cls, tz=None):
                return when

        monkeypatch.setattr(app, "datetime", _Frozen)
        return when

    return _apply


@pytest.fixture
def set_trancadas(monkeypatch):
    """Define o global app._trancadas (set de chaves "pid|inv|Ipv") só para o teste.

    _classifica_strings lê esse global por nome no momento da chamada, então trocar
    o atributo do módulo basta. O monkeypatch reverte ao fim de cada teste.
    """
    def _apply(keys):
        s = set(keys)
        monkeypatch.setattr(app, "_trancadas", s)
        return s

    return _apply


@pytest.fixture
def trk_accum(monkeypatch):
    """Zera o acumulador de trackers (app._trk_accum) num estado limpo e isolado."""
    state = {"date": "", "plants": {}}
    monkeypatch.setattr(app, "_trk_accum", state)
    return state


@pytest.fixture(autouse=True)
def _fase4_desligada_por_padrao(monkeypatch):
    """A Fase 4 (curva lida do acervo do gêmeo) fala pela REDE com o serviço em 127.0.0.1:5075.

    Sem esta trava, todo teste que passa por `_sunop_analog_history` passaria ou falharia conforme
    o gêmeo estivesse no ar na máquina de quem roda — e na CI ele nunca está. Quem testa a Fase 4
    liga explicitamente (`monkeypatch.setattr(app, "GEMEO_CURVA_ATIVO", True)`) e dubla o
    `_gemeo_curva`; todo o resto da suíte segue offline e determinístico.
    """
    monkeypatch.setattr(app, "GEMEO_CURVA_ATIVO", False, raising=False)
