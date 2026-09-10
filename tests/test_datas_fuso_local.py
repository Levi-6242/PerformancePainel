# -*- coding: utf-8 -*-
"""Data na tela é a data LOCAL — a frente de datas da varredura de 09/09/2026, verificada 3× por achado.

Dois padrões apareceram repetidos:

1. `new Date().toISOString()` para montar uma data que vai ser comparada com dado LOCAL. O Brasil é
   UTC−3 o ano todo (sem horário de verão desde 2019), então das 21h em diante o front pedia o dia (ou
   o mês) SEGUINTE. Três telas faziam isso: a vista PR do /monitoramento, o "Até" do Histórico→PR do
   /painel e o card de OS do Diagnóstico. Nas três, o backend não clampa nada — devolve vazio.

2. Filtro "do mês corrente E já fechado", que no dia 1º é um conjunto vazio por construção — o painel
   de ETM abria cego todo primeiro dia do mês.

E, no backend do Fracttal, os dois relógios no MESMO laço: `creation_date` cortado cru (UTC) enquanto
evento e fim passam por `_frac_dt_local`.
"""
import pathlib
from datetime import datetime, timedelta

import openpyxl

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]


# ── 1. o mês da OS do Fracttal é lido no mesmo relógio do resto do laço ────────────────────────────
def _wo(folio, criada_utc, status=3):
    return {"wo_folio": folio, "id_status_work_order": status, "creation_date": criada_utc,
            "tasks_log_task_type_main": "Corretiva", "event_date": criada_utc,
            "description": "teste", "id_item": "X"}


def test_os_criada_a_noite_no_ultimo_dia_do_mes_fica_no_mes_certo(monkeypatch):
    """22:30 de 31/08 no Brasil = 01:30Z de 01/09. Cortando a string crua, a OS sumia de agosto (e não
    aparecia em setembro, porque em setembro ela é 'concluída fora do mês' também)."""
    monkeypatch.setattr(app, "_frac_wos_raw", lambda i: [_wo("OS-1", "2026-09-01T01:30:00+00:00")])
    ago = app._frac_os_filtradas("X", "2026-08")
    assert [o["folio"] for o in ago] == ["OS-1"], "a OS da noite do dia 31 sumiu do mês em que foi criada"


def test_os_do_mes_seguinte_continua_fora(monkeypatch):
    """Controle: 01/09 às 10:00 local é setembro nos dois relógios e não pode vazar para agosto."""
    monkeypatch.setattr(app, "_frac_wos_raw", lambda i: [_wo("OS-2", "2026-09-01T13:00:00+00:00")])
    assert app._frac_os_filtradas("X", "2026-08") == []
    assert [o["folio"] for o in app._frac_os_filtradas("X", "2026-09")] == ["OS-2"]


def test_os_aberta_ignora_o_mes(monkeypatch):
    """Régua intacta: OS não encerrada aparece sempre, seja qual for a data."""
    monkeypatch.setattr(app, "_frac_wos_raw", lambda i: [_wo("OS-3", "2026-01-05T12:00:00+00:00", status=1)])
    assert [o["folio"] for o in app._frac_os_filtradas("X", "2026-08")] == ["OS-3"]


# ── 2. o painel de ETM enxerga no dia 1º ───────────────────────────────────────────────────────────
def _planilha_do_mes(tmp_path, ref, valores):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Usina Teste"
    ws.append(["Usina", "Data", "IPOA (kWh/m²) DEF", "GHI (kWh/m²)"])
    for i, v in enumerate(valores, start=1):
        ws.append(["Usina Teste", ref.replace(day=i), v, 5.0])
    p = tmp_path / "BD.xlsx"
    wb.save(p)
    return str(p)


def _relogio(monkeypatch, quando):
    """Relógio falso que NÃO quebra os `isinstance(x, datetime)` do app.

    Sem o `__instancecheck__`, trocar `app.datetime` por uma subclasse faz todo `isinstance(d, datetime)`
    do arquivo devolver False para as datas que vêm da planilha (elas são `datetime` puro, não a
    subclasse) — e o laço do painel descarta a planilha inteira em silêncio."""
    class _Meta(type):
        def __instancecheck__(cls, obj):
            return isinstance(obj, datetime)

    class _D(app.datetime, metaclass=_Meta):
        @classmethod
        def now(cls, tz=None):
            return quando
    monkeypatch.setattr(app, "datetime", _D)


def test_no_dia_primeiro_o_painel_olha_o_mes_que_fechou(tmp_path, monkeypatch):
    """01/10: o único dia de outubro é hoje, que o filtro exclui — antes o painel voltava vazio."""
    setembro = datetime(2026, 9, 1)
    caminho = _planilha_do_mes(tmp_path, setembro, [0.0, 0.0, 0.0])     # sensor morto em setembro
    _relogio(monkeypatch, datetime(2026, 10, 1, 9, 0))
    monkeypatch.setattr(app, "_bd_readable", lambda: caminho)
    monkeypatch.setattr(app, "INFO_GERAL", {app._nrm("Usina Teste"): {"usina": "Usina Teste", "cliente": "C"}})
    monkeypatch.setattr(app, "_gerencial_payload", lambda *a, **k: {"usinas": []})
    saida = app._etm_problemas_build()
    assert saida["mes"] == "09/2026", "no dia 1º o mês de referência tem de ser o que acabou de fechar"
    probs = [p for it in saida["itens"] for p in it["problemas"]]
    assert any("sem leitura" in p for p in probs), "sensor morto ficou invisível no primeiro dia do mês"


def test_no_meio_do_mes_nada_muda(tmp_path, monkeypatch):
    """Régua intacta no resto do mês: continua olhando o mês corrente."""
    outubro = datetime(2026, 10, 1)
    caminho = _planilha_do_mes(tmp_path, outubro, [0.0, 0.0, 0.0])
    _relogio(monkeypatch, datetime(2026, 10, 9, 9, 0))
    monkeypatch.setattr(app, "_bd_readable", lambda: caminho)
    monkeypatch.setattr(app, "INFO_GERAL", {app._nrm("Usina Teste"): {"usina": "Usina Teste", "cliente": "C"}})
    monkeypatch.setattr(app, "_gerencial_payload", lambda *a, **k: {"usinas": []})
    saida = app._etm_problemas_build()
    assert saida["mes"] == "10/2026"
    assert any("sem leitura" in p for it in saida["itens"] for p in it["problemas"])


# ── 3. as três telas que montavam data local com toISOString ───────────────────────────────────────
def test_nenhuma_das_tres_telas_monta_data_com_toISOString():
    """Guarda de regressão: `toISOString()` sobre o RELÓGIO é o padrão que a varredura achou 3×.

    O que continua permitido — e existe no Monitoramento — é `toISOString()` sobre uma data construída
    a partir de uma ISO local (`new Date(iso+'T00:00:00')`, no `_isoAdd`): meia-noite local vira 03:00Z
    do MESMO dia, então a fatia sai certa. O veneno é `new Date()` (agora) virando UTC."""
    alvos = [RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html",
             RAIZ / "plataforma" / "templates" / "painel_portfolio.html",
             RAIZ / "plataforma" / "templates" / "painel_usina_v2.html"]
    for f in alvos:
        src = f.read_text(encoding="utf-8")
        assert "new Date().toISOString(" not in src, f"{f.name} voltou a montar data local em UTC"
        assert "t.toISOString(" not in src, f"{f.name}: data do relógio convertida para UTC"


def test_a_vista_pr_do_monitoramento_pede_o_dia_local():
    src = (RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")
    assert "base+'?date='+_todayISO()" in src, "a vista PR deixou de usar a data local"
