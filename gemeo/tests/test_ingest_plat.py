# gemeo/tests/test_ingest_plat.py
"""Fonte `plat`: trackers da 2C lidos da Plataforma de Performance (21/09/2026).

Substitui os testes da versao que batia direto na apiplataforma com token proprio. O motivo da
troca esta no cabecalho de `gemeo/ingest/plat.py`: aquela API NEGA as tres usinas para a conta
gridco — e devolve HTTP **200** com "Usuario nao possui permissao", que o codigo antigo nao tratava
(so olhava 401/403), entao a fonte morreu calada por dois dias.

Os dois riscos que estes testes seguram:
  1. o carimbo `Z` do acervo e FALSO (hora de Brasilia) — ler como UTC desloca tudo em 3 h;
  2. o de-para `Tracker g.n` -> `TRK<n>`, que na Tupi e uma suposicao de ordem entre os 3 grupos.
"""
import datetime as dt

import pytest

from gemeo.ingest import plat

UTC = dt.timezone.utc


def curva(nomes_e_pontos, alvo=None):
    """Payload no formato que /api/gemeo/trackers/<ref>/chart devolve."""
    return {"date": "2026-09-21",
            "trackers": [{"id": n, "x": [x for x, _ in pts], "y": [y for _, y in pts]} for n, pts in nomes_e_pontos],
            "alvo": {"x": [x for x, _ in (alvo or [])], "y": [y for _, y in (alvo or [])]}}


# ── carimbo ─────────────────────────────────────────────────────────────────────────────────────
def test_carimbo_Z_e_lido_como_hora_de_brasilia():
    """06:04:46Z no acervo = 09:04:46 UTC. Se fosse lido como UTC, a curva inteira andava 3 h — e a
    prova de que e Brasilia esta no meio-dia solar (cabecalho de plat.py)."""
    assert plat.ts_utc("2026-09-21T06:04:46Z") == dt.datetime(2026, 9, 21, 9, 4, 46, tzinfo=UTC)


def test_carimbo_fora_do_formato_grita():
    with pytest.raises(ValueError):
        plat.ts_utc("21/09/2026 06:04")


# ── de-para dos nomes ───────────────────────────────────────────────────────────────────────────
def test_de_para_de_um_grupo_so_e_direto():
    """Araputanga e Sete Lagoas: um grupo, 1..59. Aqui nao ha suposicao nenhuma."""
    d = plat.de_para_nomes([f"Tracker 1.{i}" for i in range(1, 60)])
    assert d["Tracker 1.1"] == "TRK1" and d["Tracker 1.59"] == "TRK59" and len(d) == 59


def test_de_para_da_tupi_segue_a_ordem_dos_grupos():
    """A SUPOSICAO (Levi, 21/09): 1.x -> 1..30, 2.x -> 31..60, 3.x -> 61..100."""
    nomes = ([f"Tracker 1.{i}" for i in range(1, 31)] + [f"Tracker 2.{i}" for i in range(1, 31)]
             + [f"Tracker 3.{i}" for i in range(1, 41)])
    d = plat.de_para_nomes(nomes)
    assert d["Tracker 1.30"] == "TRK30"
    assert d["Tracker 2.1"] == "TRK31" and d["Tracker 2.30"] == "TRK60"
    assert d["Tracker 3.1"] == "TRK61" and d["Tracker 3.40"] == "TRK100"


def test_de_para_nao_depende_da_ordem_em_que_o_acervo_manda():
    """O JSON nao promete ordem; a ordenacao e por (grupo, n), nao pela posicao na lista."""
    assert plat.de_para_nomes(["Tracker 2.1", "Tracker 1.2", "Tracker 1.1"]) == {
        "Tracker 1.1": "TRK1", "Tracker 1.2": "TRK2", "Tracker 2.1": "TRK3"}


def test_nome_fora_do_padrao_nao_desloca_os_outros():
    """Um rotulo estranho no acervo nao pode empurrar todo mundo uma casa e trocar o de-para."""
    d = plat.de_para_nomes(["Tracker 1.1", "Sensor X", "Tracker 1.2"])
    assert d == {"Tracker 1.1": "TRK1", "Tracker 1.2": "TRK2"}


# ── leituras ────────────────────────────────────────────────────────────────────────────────────
INI = dt.datetime(2026, 9, 21, 9, 0, tzinfo=UTC)     # 06:00 de Brasilia
FIM = dt.datetime(2026, 9, 21, 10, 0, tzinfo=UTC)    # 07:00 de Brasilia


def test_guarda_um_angulo_por_bloco_de_15_min():
    """5 min x 218 trackers seriam ~150 mil linhas/dia; o modelo trabalha em blocos de 15."""
    pts = [(f"2026-09-21T06:{m:02d}:00Z", -50.0 + m) for m in range(0, 60, 5)]
    ls, nao = plat.leituras_da_curva(curva([("Tracker 1.1", pts)]), {"TRK1": 7}, INI, FIM)
    assert nao == 0
    # guarda o carimbo REAL, nao a borda do bloco; e a janela e aberta em `ini`, entao 06:00 fica fora
    assert [t.strftime("%H:%M") for _, _, t, _ in ls] == ["09:05", "09:15", "09:30", "09:45"]
    assert all(m == "angulo" and e == 7 for e, m, _, _ in ls)


def test_ponto_fora_da_janela_fica_de_fora():
    pts = [("2026-09-21T05:30:00Z", -55.0), ("2026-09-21T06:30:00Z", -40.0)]
    ls, _ = plat.leituras_da_curva(curva([("Tracker 1.1", pts)]), {"TRK1": 7}, INI, FIM)
    assert [v for *_, v in ls] == [-40.0]


def test_tracker_sem_par_no_cadastro_e_contado_nao_engolido():
    """Sumir com o que nao casa esconde cadastro desatualizado; o ciclo tem de dizer quantos foram."""
    pts = [("2026-09-21T06:05:00Z", -50.0)]
    ls, nao = plat.leituras_da_curva(curva([("Tracker 1.1", pts), ("Tracker 1.2", pts)]), {"TRK1": 7}, INI, FIM)
    assert len(ls) == 1 and nao == 1


def test_valor_nao_numerico_nao_vira_leitura():
    pts = [("2026-09-21T06:05:00Z", None), ("2026-09-21T06:20:00Z", -40.0)]
    ls, _ = plat.leituras_da_curva(curva([("Tracker 1.1", pts)]), {"TRK1": 7}, INI, FIM)
    assert [v for *_, v in ls] == [-40.0]


def test_resposta_sem_trackers_nao_explode():
    assert plat.leituras_da_curva({"error": "não autenticado"}, {"TRK1": 7}, INI, FIM) == ([], 0)
    assert plat.leituras_da_curva(None, {"TRK1": 7}, INI, FIM) == ([], 0)


# ── alvo ────────────────────────────────────────────────────────────────────────────────────────
def test_alvo_entra_uma_vez_por_tracker_no_ultimo_instante():
    """O alvo e UM so para a frota: grava-lo em todo bloco multiplicaria por 218 um valor identico.
    Fica o instante, que e o que a fonte antiga gravava — a troca muda a origem, nao a regua."""
    alvo = [("2026-09-21T06:05:00Z", -50.0), ("2026-09-21T06:50:00Z", -44.0)]
    ls = plat.leituras_do_alvo(curva([], alvo), {"TRK1": 7, "TRK2": 8}, INI, FIM)
    assert sorted(ls) == [(7, "angulo_alvo", dt.datetime(2026, 9, 21, 9, 50, tzinfo=UTC), -44.0),
                          (8, "angulo_alvo", dt.datetime(2026, 9, 21, 9, 50, tzinfo=UTC), -44.0)]


def test_sem_alvo_na_janela_nao_inventa():
    assert plat.leituras_do_alvo(curva([], [("2026-09-21T05:00:00Z", -55.0)]), {"TRK1": 7}, INI, FIM) == []


# ── a conferencia que fecha a suposicao da Tupi quando houver parado ────────────────────────────
def _sol(base):
    return [(f"2026-09-21T06:{m:02d}:00Z", base + m) for m in range(0, 60, 5)]


def _travado():
    return [(f"2026-09-21T06:{m:02d}:00Z", -12.0) for m in range(0, 60, 5)]


def test_conferencia_e_inconclusiva_em_dia_normal():
    """Medido em 18/09: com todos seguindo o sol, o melhor casamento erra por 0,2 grau. Dizer
    'confere' aqui seria dar por provado o que nao foi."""
    p = curva([("Tracker 1.1", _sol(-55)), ("Tracker 1.2", _sol(-54))])
    gem = {"TRK1": [-55.0 + m for m in range(0, 60, 5)], "TRK2": [-54.0 + m for m in range(0, 60, 5)]}
    assert plat.conferir_de_para(p, gem)["conclusivo"] is False


def test_um_parado_dos_dois_lados_confirma_a_ordem():
    p = curva([("Tracker 1.1", _sol(-55)), ("Tracker 1.2", _travado())])
    gem = {"TRK1": [-55.0 + m for m in range(0, 60, 5)], "TRK2": [-12.0] * 12}
    r = plat.conferir_de_para(p, gem)
    assert r["conclusivo"] is True and r["confere"] is True


def test_um_parado_em_posicao_trocada_acusa():
    """Se o parado do acervo for o 1.1 e o do gemeo o TRK2, a ordem assumida esta errada."""
    p = curva([("Tracker 1.1", _travado()), ("Tracker 1.2", _sol(-54))])
    gem = {"TRK1": [-55.0 + m for m in range(0, 60, 5)], "TRK2": [-12.0] * 12}
    r = plat.conferir_de_para(p, gem)
    assert r["conclusivo"] is True and r["confere"] is False


# ── a fonte nao cria equipamento ────────────────────────────────────────────────────────────────
def test_descobrir_nao_cria_tracker():
    """Este acervo nao sabe o inversor-pai; criar aqui produziria tracker orfao em cima dos 218 que
    ja existem. `descobrir` e no-op de proposito, e nao pode 'voltar a funcionar' sem querer."""
    ing = plat.IngestorPlatTrackers.__new__(plat.IngestorPlatTrackers)
    assert ing.descobrir(object()) is None
