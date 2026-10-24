# -*- coding: utf-8 -*-
"""O trip das OS no comentário do dia (Levi, 23/10/2026: "Desligamento Usina Trip 27/86 de 13/10 às 17:02h a 14/10 às
07:29h; religamento, OS 16249"). Primeiro a subtarefa "Categoria e proteção" da OS; sem código nela, a nota da OS
("Proteção: 27/86"). O Fracttal é falso aqui: nada de rede."""
import datetime as dt
import os
import sys

import pytest

AQUI = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(AQUI, "..", "thopen"))
import dashboard_thopen as dth  # noqa: E402
import fonte_operacao  # noqa: E402
import fotos_ronda  # noqa: E402
import operacao_mes as om  # noqa: E402
import trip_os  # noqa: E402

# a OS 16249 como o Fracttal devolveu em 23/10/2026 (a subtarefa sem código, o código na nota)
SUB_16249 = [{"description": "Categoria e proteção", "value": "Religamento "},
             {"description": "Onde atuou", "value": "Cabine "},
             {"description": "Foi necessário religamento?", "value": "Sim"},
             {"description": "Resultado", "value": "Normalizado"}]
NOTA_16249 = ("UFV: Altair 1 | Ativo: THPN-ALT100 | Proteção: 27/86 | Ação: Religamento Local | Falha: Disjuntor Geral "
              "desligado, relé com proteções 27/86 ativas.")


class Fracttal:
    """Responde como o `fotos_ronda._get`: {"data": [...]} por OS; conta os pedidos."""

    def __init__(self, subs=None, notas=None, cota_em=None):
        self.subs, self.notas, self.pedidos, self.cota_em = subs or {}, notas or {}, [], cota_em

    def __call__(self, ep, params):
        self.pedidos.append((ep, str(params["folio"])))
        if self.cota_em is not None and len(self.pedidos) >= self.cota_em:
            raise fotos_ronda.Ocupado("Fracttal recusou por cota (429)")
        n = str(params["folio"])
        if ep.startswith("work_orders_subtasks"):
            return {"data": self.subs.get(n, [])}
        return {"data": [{"task_note": self.notas[n]}] if n in self.notas else []}


@pytest.fixture
def frac(monkeypatch, tmp_path):
    monkeypatch.setattr(trip_os, "CACHE", str(tmp_path / "cache_trip_os.json"))
    monkeypatch.setattr(trip_os, "PAUSA", 0)
    trip_os._zerar()
    f = Fracttal({"16249": SUB_16249}, {"16249": NOTA_16249})
    monkeypatch.setattr(trip_os, "_get", f)
    yield f
    trip_os._zerar()


@pytest.mark.parametrize("txt,esperado", [
    ("Proteção atuou — 27 e 86", ["27", "86"]),                  # o que o COS do Nexus grava na subtarefa
    ("27/86", ["27", "86"]),
    ("51n, 50N e 27", ["51N", "50N", "27"]),
    ("Religamento ", []),
    ("THPN-ALT100 em 2026", []),                                 # número de ativo e ano não são código
    ("27/27", ["27"]),
])
def test_codigos_ansi_do_cos(txt, esperado):
    assert trip_os.codigos(txt) == esperado


def test_a_subtarefa_vence_a_nota():
    subs = [{"description": "Categoria e proteção", "value": "Proteção atuou — 51 e 86"}]
    assert trip_os.trip_de(subs, NOTA_16249) == "51/86"


def test_sem_codigo_na_subtarefa_vai_a_nota():
    assert trip_os.trip_de(SUB_16249, NOTA_16249) == "27/86"


@pytest.mark.parametrize("subs,nota", [
    ([{"description": "Categoria e proteção", "value": "Proteção atuou — Sem proteção/trip ativo"}], NOTA_16249),
    ([], "UFV: Altair 1 | Proteção: Sem proteção/trip ativo | Ação: Religamento Remoto | Falha: x"),
    ([], "UFV: Altair 1 | Proteção: --/-- | Ação: Religamento Remoto | Falha: relé com proteções 51 ativas."),
    ([{"description": "Categoria e proteção", "value": "Inversor desligado — Baixa irradiância"}], ""),
    ([], None),
])
def test_sem_trip_a_frase_fica_como_esta(subs, nota):
    # "Sem proteção/trip ativo" na subtarefa decide: a nota não é lida. Na nota, só o campo Proteção vale (o "51" da
    # Falha não é o trip)
    assert trip_os.trip_de(subs, nota) is None


def test_le_a_subtarefa_e_so_depois_a_nota(frac):
    assert trip_os.buscar(["16249"]) == {"16249": "27/86"}
    assert [ep.split("/")[0] for ep, _ in frac.pedidos] == ["work_orders_subtasks", "work_orders"]


def test_com_codigo_na_subtarefa_nao_pede_a_nota(frac):
    frac.subs["16300"] = [{"description": "Categoria e proteção", "value": "Proteção atuou — 81"}]
    assert trip_os.buscar(["16300"]) == {"16300": "81"}
    assert len(frac.pedidos) == 1


def test_guardado_na_memoria_e_no_disco(frac):
    trip_os.buscar(["16249"])
    assert trip_os.guardados(["16249", "999"]) == ({"16249": "27/86"}, ["999"])
    trip_os._zerar(disco=False)                       # o processo reiniciou: a memória some, o disco fica
    assert trip_os.guardados(["16249"]) == ({"16249": "27/86"}, [])
    assert len(frac.pedidos) == 2                    # nenhum pedido a mais


def test_vencido_volta_a_faltar(frac, monkeypatch):
    trip_os.buscar(["16249"])
    agora = trip_os._agora()
    monkeypatch.setattr(trip_os, "_agora", lambda: agora + trip_os.TTL + 1)
    assert trip_os.guardados(["16249"]) == ({}, ["16249"])


def test_atualizar_busca_de_novo_mesmo_guardado(frac):
    trip_os.buscar(["16249"])
    frac.notas["16249"] = NOTA_16249.replace("27/86", "59")
    assert trip_os.buscar(["16249"]) == {"16249": "27/86"}          # guardado: não pede
    assert trip_os.buscar(["16249"], forcar=True) == {"16249": "59"}  # o Atualizar: pede de novo


def test_cota_do_fracttal_para_sem_erro_e_sem_guardar(frac):
    frac.subs["2"], frac.cota_em = [], 1
    assert trip_os.buscar(["16249", "2"]) == {}                    # 429 no 1º pedido: para, nada guardado
    assert len(frac.pedidos) == 1
    assert trip_os.guardados(["16249"]) == ({}, ["16249"])
    assert trip_os.buscar(["16249"]) == {}                         # na espera da cota não pede de novo
    assert len(frac.pedidos) == 1


def test_sem_credencial_nao_quebra(frac, monkeypatch):
    def sem(*a):
        raise fotos_ronda.SemCredencial("x")
    monkeypatch.setattr(trip_os, "_get", sem)
    assert trip_os.buscar(["16249"]) == {}


def test_tempo_limite_deixa_o_resto_para_depois(frac, monkeypatch):
    relogio = iter(range(0, 1000, 10))
    monkeypatch.setattr(trip_os, "_relogio", lambda: next(relogio))
    frac.subs.update({"1": SUB_16249, "2": SUB_16249})
    frac.notas.update({"1": NOTA_16249, "2": NOTA_16249})
    achou = trip_os.buscar(["16249", "1", "2"], limite_s=25)
    assert achou == {"16249": "27/86", "1": "27/86"} and trip_os.guardados(["2"]) == ({}, ["2"])


def test_import_nao_abre_thread_nem_le_o_disco():
    assert not [t for t in trip_os.threading.enumerate() if t.name == "thopen-trip"]


# ── a frase do comentário ───────────────────────────────────────────────────────────────────────────────────────────
PUB5 = [{"mes": "2026-10", "periodo_fim": "2026-10-14", "atualizado_em": "2026-10-14 10:05", "disponibilidade_dia": 0,
         "disponibilidade_os_dia": 0}]


def _osd(dia, trechos, escopo="Usina inteira", os="16249"):
    return {"mes": "2026-10", "dia": dia, "usina": "Altair", "usina_fracttal": None, "os": os, "tipo": "Religamento",
            "escopo": escopo, "kwp": None, "inicio": "2026-10-13T17:02:00", "fim": "2026-10-14T07:29:00",
            "aberta": "não", "trechos": trechos, "h_perdidas": None, "usina_ids": []}


def _dados(oss):
    ds = [{"mes": "2026-10", "dia": d, "usina": "Altair", "disp": 90.0, "pot_kwp": 6898.0, "usina_ids": []}
          for d in ("2026-10-13", "2026-10-14")]
    return {"atualizacao": PUB5, "disponibilidade_dia": ds, "disponibilidade_os_dia": oss, "de_para": [],
            "strings_episodios": [], "trackers_episodios": [], "cobertura": [], "strings_os": [], "trackers_dia": [],
            "rondas_com_os": [], "rondas_sem_os": []}


def test_frase_com_o_trip_depois_do_escopo():
    d = _dados([_osd("2026-10-13", "17:02-18:00"), _osd("2026-10-14", "06:00-07:29")])
    out = om.os_por_dia(d, "Altair", 2026, 10, trips={"16249": "27/86"})
    assert out[dt.date(2026, 10, 13)] == [
        "Desligamento Usina Trip 27/86 de 13/10 às 17:02h a 14/10 às 07:29h; religamento, OS 16249"]
    cab = om.os_por_dia(_dados([_osd("2026-10-13", "17:02-18:00", escopo="Cabine 2")]), "Altair", 2026, 10,
                        trips={"16249": "51"})
    assert cab[dt.date(2026, 10, 13)][0].startswith("Desligamento Cabine 2 Trip 51 de 13/10")


def test_sem_trip_a_frase_e_a_de_sempre():
    d = _dados([_osd("2026-10-13", "17:02-18:00")])
    assert om.os_por_dia(d, "Altair", 2026, 10) == om.os_por_dia(d, "Altair", 2026, 10, trips={"16249": None}) == {
        dt.date(2026, 10, 13): ["Desligamento Usina de 13/10 às 17:02h a 14/10 às 07:29h; religamento, OS 16249"]}


def test_numeros_das_os_da_usina_no_mes():
    d = _dados([_osd("2026-10-13", "17:02-18:00"), _osd("2026-10-14", "06:00-07:29"),
                dict(_osd("2026-10-14", "08:00-09:00", os="16300"), usina="Assis")])
    assert om.os_desligamento_do_mes(d, "Altair", 2026, 10) == ["16249"]


# ── a rota e o botão Atualizar ──────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def cli(monkeypatch, frac):
    d = _dados([_osd("2026-10-13", "17:02-18:00")])
    monkeypatch.setattr(fonte_operacao, "dados", lambda *a, **k: d)
    monkeypatch.delenv("THOPEN_OPERACAO", raising=False)
    monkeypatch.delenv("THOPEN_LOGIN", raising=False)
    monkeypatch.delenv("THOPEN_TRIP", raising=False)
    monkeypatch.setattr(trip_os, "em_segundo_plano", lambda oss: bool(trip_os.guardados(oss)[1]))
    return dth.app.test_client()


def _frase(r):
    return next(p for p in r["por_dia"] if p["dia"] == "13/10")["os"]


def test_rota_sem_o_trip_guardado_avisa_que_esta_buscando(cli, frac):
    r = cli.get("/api/t/operacao?usina=Altair&ano=2026&mes=10").get_json()
    assert r["trip_pendente"] is True and "Trip" not in _frase(r)[0]
    assert frac.pedidos == []                                     # a rota não espera o Fracttal


def test_atualizar_busca_o_trip_das_os_da_usina_na_tela(cli, frac, monkeypatch):
    monkeypatch.setattr(dth, "_wb", lambda: None)
    assert cli.get("/api/t/reload?usina=Altair&ano=2026&mes=10").status_code == 200
    assert {n for _ep, n in frac.pedidos} == {"16249"}
    r = cli.get("/api/t/operacao?usina=Altair&ano=2026&mes=10").get_json()
    assert r["trip_pendente"] is False
    assert _frase(r) == ["Desligamento Usina Trip 27/86 de 13/10 às 17:02h a 14/10 às 07:29h; religamento, OS 16249"]


def test_chave_desliga_o_trip(cli, frac, monkeypatch):
    monkeypatch.setenv("THOPEN_TRIP", "0")
    monkeypatch.setattr(dth, "_wb", lambda: None)
    cli.get("/api/t/reload?usina=Altair&ano=2026&mes=10")
    r = cli.get("/api/t/operacao?usina=Altair&ano=2026&mes=10").get_json()
    assert frac.pedidos == [] and r["trip_pendente"] is False


def test_tela_rele_enquanto_o_trip_chega_e_o_atualizar_manda_a_usina():
    html = open(os.path.join(AQUI, "..", "thopen", "templates", "dashboard_thopen.html"), encoding="utf-8").read()
    assert "d.trip_pendente" in html
    assert "/api/t/reload?usina=" in html
