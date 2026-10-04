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


# Arquivos que a plataforma GRAVA (01/10/2026). Às 09:51 de 01/10 o test_os_tres_chamadores_pre_carregam_as_usinas_juntas
# chamou o _sunop_eventos_calc de verdade, e ele salva o acervo: o trk_eventos.json do PC (11,7 MB, 93 dias de
# eventos de tracker de todas as fontes) virou 388 bytes com as duas usinas falsas do teste, até o worker regravar da
# memória 4 min depois — um reinício nessa janela apagava o histórico. Num reinício de 30/09 o worker já tinha
# carregado o arquivo com a AAA100 e a BBB100 do teste. Cada teste grava agora num diretório só dele; a lista é
# conferida contra o app.py (tests/test_isolamento_estado.py), para arquivo novo não ficar de fora.
ARQUIVOS_DE_ESTADO = (
    # _p_dado / _p_cache
    "PV_RELOGIO_PATH", "_TRK_FIM_DIA_PATH", "_TRK_EV_PATH", "STATE_PATH", "SPV_NOTAS_PATH",
    "_PERSIST_PATH", "_FRAC_INDEX_FILE", "_FRAC_OSPERF_FILE", "_FRAC_DISP_FILE", "_FRAC_DISP_STATUS", "_FRAC_MTTA_FILE",
    "_FRAC_MTTA_BASE", "_FALHAS_STR_PATH", "_FALHAS_PV_DEV", "_FALHAS_IMPORTA_PATH", "_FALHAS_TRK_SEMCOM_PATH",
    "_FALHAS_OS_PATH", "_FALHAS_2C_PATH", "FALHAS_BF_ESTADO", "FALHAS_BF_PV_ESTADO", "FALHAS_DESC_PATH", "_WHATS_CFG_PATH",
    "_TRK_GARANTIA_PATH", "_TRK_GARANTIA_LOCAL", "_TRK_DEPARA_LOCAL", "_TRK_HIST_PATH", "_NOTAS_TRK_PATH",
    "_NOTAS_TRK_LOCAL", "_PERDAS_STR_PATH", "_PARADAS_PATH", "_REL_SEM_PATH",
    # gravados direto em plataforma/
    "_TOKENS_RT_PATH", "_ENTRADA_TRK_ULTIMO", "_SUNOP_PLANTS_ARQ", "_TUNNEL_URL_FILE", "_WHATS_SENT_PATH",
    "_WHATS_LOG_PATH",
)


@pytest.fixture(autouse=True)
def _estado_de_runtime_isolado(tmp_path, monkeypatch):
    """Nenhum teste grava estado de runtime DE VERDADE em plataforma/ (22/09/2026; todos os arquivos desde 01/10/2026).

    A montagem do tempo real passou a guardar a última contagem boa de trackers em
    `plataforma/entrada_trk_ultimo.json`, para sobreviver ao restart do deploy. Na primeira rodada, os
    testes da montagem — com fontes SIMULADAS — gravaram zeros falsos no arquivo real, e o teste seguinte,
    que espera "sem leitura anterior", achou o arquivo e reaproveitou a contagem. Além de vazar estado
    entre testes, sujava a plataforma local com dado inventado. Cada teste agora tem os seus arquivos — e o
    contador da SunOp não despeja (o padrão, 25 chamadas, gravava no `logs/sunop_uso_worker.json` do PC, o
    contador que mede a cota); quem testa o despejo liga e aponta o `_AQUI` para o tmp_path."""
    for nome in ARQUIVOS_DE_ESTADO:
        atual = getattr(app, nome, None)
        if isinstance(atual, str):
            monkeypatch.setattr(app, nome, str(tmp_path / os.path.basename(atual)))
    monkeypatch.setattr(app, "_SUNOP_USO_FLUSH", 10 ** 9, raising=False)


@pytest.fixture(autouse=True)
def _sunop_sem_pausa_por_padrao(monkeypatch):
    """A pausa da SunOp (domingo e teto do dia, 04/10/2026) depende do dia e do contador: rodada num domingo, a suíte
    inteira veria a SunOp fechada. Desligada por padrão; tests/test_sunop_teto_domingo.py liga."""
    monkeypatch.setattr(app, "SUNOP_PAUSA_LIGADA", False, raising=False)


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


@pytest.fixture(autouse=True)
def _sunop_coleta_completa_por_padrao(monkeypatch):
    """`SUNOP_COLETA` vem do tokens.txt da MÁQUINA (o PC do Levi roda em `ronda` desde 29/09/2026). Sem esta trava, a
    suíte testaria o modo da máquina de quem roda — foi assim que os testes do ciclo noturno e da Entrada quebraram no
    PC. Quem testa o modo ronda liga explicitamente (`monkeypatch.setattr(app, "SUNOP_COLETA", "ronda")`)."""
    monkeypatch.setattr(app, "SUNOP_COLETA", "completa", raising=False)
    if isinstance(getattr(app, "_sunop_trk_cache", None), dict):
        monkeypatch.setitem(app._sunop_trk_cache, "_ttl", app.SUNOP_TTL)
