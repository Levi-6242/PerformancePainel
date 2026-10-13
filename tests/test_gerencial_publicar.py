# -*- coding: utf-8 -*-
"""A meta do mês por usina no banco (12/10/2026): o Gerencial do worker publicado no livro `nexus_performance ·
fato_meta_usina_mes`, para a Visão do responsável do Nexus ler os MESMOS números da Visão gerencial."""
from datetime import datetime

import gerencial_publicar as gp

U1 = {"usina": "Altair 1", "cliente": "Thopen", "carteira": "Thopen", "prod": 812.4, "p50": 900.0, "atingimento": 90.3,
      "pr": 78.1, "pr_meta": 80.0, "ipoa": 150.2, "ipoa_prev": 160.0, "dias_cob": 11, "dias_mes": 31, "meta_dias": 11,
      "p50_src": "BD_Thopen", "src": "pg", "full_oem": True, "pr_motivo": "texto livre que não vai ao banco"}
U2 = {"usina": "Barretos 1", "cliente": "—", "carteira": "—", "prod": 300.0, "p50": None, "atingimento": None,
      "pr": None, "pr_meta": None, "ipoa": 0, "ipoa_prev": None, "dias_cob": None, "dias_mes": 31, "meta_dias": 0,
      "p50_src": None, "src": "bd", "full_oem": False}


def test_as_linhas_do_mes_sem_texto_livre_e_sem_o_traco():
    out = gp.linhas({"usinas": [U2, U1, {"usina": " "}]}, 202610)
    assert [r[1] for r in out] == ["Altair 1", "Barretos 1"]
    assert dict(zip(gp.CAB, out[0])) == {
        "mes_id": 202610, "usina": "Altair 1", "cliente": "Thopen", "carteira": "Thopen", "prod_kwh": 812400,
        "meta_kwh": 900000, "atingimento_pct": 90.3, "pr_pct": 78.1, "pr_meta_pct": 80.0, "ipoa_kwh_m2": 150.2,
        "ipoa_meta_kwh_m2": 160.0, "dias_cobertos_qtd": 11, "dias_mes_qtd": 31, "meta_dias_qtd": 11, "full_om": 1,
        "fonte": "pg", "meta_fonte": "BD_Thopen"}
    assert out[1][2] is None and out[1][14] == 0                       # "—" vira vazio; sem Full O&M = 0
    assert "texto livre" not in str(out)                               # o pr_motivo não vai (leitura aberta)


def test_mesclar_troca_so_os_meses_refeitos():
    antigas = [[202609, "Altair 1"] + [1] * 15, [202610, "Altair 1"] + [2] * 15, [202608, "Zeta"] + [3] * 15]
    novas = {202610: [[202610, "Altair 1"] + [9] * 15, [202610, "Barretos 1"] + [9] * 15]}
    out = gp.mesclar(antigas, novas)
    assert [(r[0], r[1], r[2]) for r in out] == [(202608, "Zeta", 3), (202609, "Altair 1", 1), (202610, "Altair 1", 9),
                                                  (202610, "Barretos 1", 9)]


SERIE = {"Altair 1": {"meta": 0.827, "pot": 3.5, "meta_ger": 18.57, "meta_poa": 7.4,
                      "pontos": [{"dia": 2, "realizado": 0.8491965, "geracao": 6.27, "poa": 2.09},
                                 {"dia": 1, "realizado": None, "geracao": 0.0, "poa": 0.1},
                                 {"dia": "x", "realizado": 1, "geracao": 1, "poa": 1}]}}


def test_a_serie_diaria_do_painel_noc_em_linhas():
    """A série do PR diário do Painel NOC (`/api/g/diario`): a meta do dia é a mesma todo dia; o PR em %; o dia vazio de
    PR fica vazio; ponto sem dia válido sai."""
    out = gp.linhas_dia(SERIE, 202610)
    assert [dict(zip(gp.CAB_DIA, r)) for r in out] == [
        {"mes_id": 202610, "usina": "Altair 1", "data_id": 20261001, "geracao_kwh": 0, "meta_kwh": 18570,
         "ipoa_kwh_m2": 0.1, "ipoa_meta_kwh_m2": 7.4, "pr_pct": None, "pr_meta_pct": 82.7},
        {"mes_id": 202610, "usina": "Altair 1", "data_id": 20261002, "geracao_kwh": 6270, "meta_kwh": 18570,
         "ipoa_kwh_m2": 2.09, "ipoa_meta_kwh_m2": 7.4, "pr_pct": 84.9, "pr_meta_pct": 82.7}]
    assert gp.linhas_dia({"X": None, " ": SERIE["Altair 1"]}, 202610) == []


def test_o_xlsx_leva_as_duas_abas_e_vazio_de_verdade():
    from io import BytesIO
    from openpyxl import load_workbook
    wb = load_workbook(BytesIO(gp.xlsx_bytes({gp.ABA: (gp.CAB, [[202610, "A"] + [""] * 15]),
                                              gp.ABA_DIA: (gp.CAB_DIA, gp.linhas_dia(SERIE, 202610))})))
    assert wb.sheetnames == [gp.ABA, gp.ABA_DIA]
    assert [c.value for c in wb[gp.ABA][1]] == gp.CAB and wb[gp.ABA]["C2"].value is None
    assert wb[gp.ABA_DIA].max_row == 3


def test_o_mes_anterior_se_refaz_ate_o_dia_5():
    assert gp.meses_a_refazer(2026, 10, 3) == [(2026, 10), (2026, 9)]
    assert gp.meses_a_refazer(2026, 10, 6) == [(2026, 10)]
    assert gp.meses_a_refazer(2027, 1, 2) == [(2027, 1), (2026, 12)]


# ── o laço no app ─────────────────────────────────────────────────────────────────────────────────────────────────────
import app  # noqa: E402


class _R:
    def __init__(self, d):
        self._d, self.status_code = d, 200

    def json(self):
        return self._d

    def raise_for_status(self):
        pass


class _Banco:
    """O livro `nexus_performance` com as duas abas (a do mês e a diária), lidas pelo `cobertura.Decisoes`."""

    def __init__(self):
        self.linhas, self.dia, self.fora, self.envios = None, None, False, 0

    def get(self, url, headers=None, params=None, timeout=None):
        if self.fora:
            raise ConnectionError("banco fora")
        if url.endswith("/api/sheets"):
            abas = [(7, gp.ABA, self.linhas), (8, gp.ABA_DIA, self.dia)]
            return _R([{"id": i, "workbook_key": gp.LIVRO, "sheet_name": a} for i, a, lin in abas if lin is not None])
        off, lim = params["offset"], params["limit"]
        cab, lin = (gp.CAB, self.linhas) if "/7/" in url else (gp.CAB_DIA, self.dia)
        return _R({"rows": [{"headers": cab, "values": x} for x in (lin or [])[off:off + lim]]})

    def sincronizar(self, conteudo, **k):
        from io import BytesIO
        from openpyxl import load_workbook
        assert k["chave"] == gp.LIVRO
        wb = load_workbook(BytesIO(conteudo))
        self.linhas = [list(r) for r in wb[gp.ABA].iter_rows(min_row=2, values_only=True)]
        self.dia = [list(r) for r in wb[gp.ABA_DIA].iter_rows(min_row=2, values_only=True)]
        self.envios += 1
        return {"inserted": len(self.linhas) + len(self.dia)}


def _ligar(monkeypatch, banco, gerencial, series=None):
    import falhas_publicar
    monkeypatch.setattr(app, "_ger_publicar_ligado", lambda: True)
    monkeypatch.setattr(app, "_ger_series_diarias", lambda g, a, m: series if series is not None else SERIE)
    monkeypatch.setenv("GRIDCO_SQL_TOKEN", "tok")
    monkeypatch.setattr(app, "_ger_pub", {"ts": 0.0, "marca": None})
    monkeypatch.setattr(app, "_ger_cache", {"ts": 1.0, "data": gerencial})
    original = app._cob.Decisoes
    monkeypatch.setattr(app._cob, "Decisoes", lambda *a, **k: original(*a, **dict(k, sessao=banco)))
    monkeypatch.setattr(falhas_publicar, "sincronizar", banco.sincronizar)


def test_publica_o_mes_do_cache_e_so_quando_muda(monkeypatch):
    banco = _Banco()
    banco.linhas = [[202609, "Altair 1"] + [None] * 15]                 # setembro já publicado fica
    _ligar(monkeypatch, banco, {"usinas": [U1, U2]})
    assert app._ger_publicar(agora=datetime(2026, 10, 12, 10)) == 3
    assert sorted((r[0], r[1]) for r in banco.linhas) == [(202609, "Altair 1"), (202610, "Altair 1"), (202610, "Barretos 1")]
    # a série diária do Painel NOC vai junto, na aba própria
    assert [(r[1], r[2], r[3]) for r in banco.dia] == [("Altair 1", 20261001, 0), ("Altair 1", 20261002, 6270)]
    assert app._ger_publicar(agora=datetime(2026, 10, 12, 10)) is None  # a hora não passou
    app._ger_pub["ts"] = 0.0
    assert app._ger_publicar(agora=datetime(2026, 10, 12, 11)) is None and banco.envios == 1   # nada mudou: não regrava


def test_gerencial_que_falhou_nao_apaga_o_mes_e_banco_fora_nao_grava(monkeypatch):
    banco = _Banco()
    banco.linhas = [[202610, "Altair 1"] + [5] * 15]
    _ligar(monkeypatch, banco, {"erro": "PG fora", "usinas": []})
    assert app._ger_publicar(agora=datetime(2026, 10, 12, 10)) is None and banco.envios == 0
    _ligar(monkeypatch, banco, {"usinas": [U1]})
    banco.fora = True
    assert app._ger_publicar(agora=datetime(2026, 10, 12, 10)) is None and banco.envios == 0


def test_mes_sem_serie_diaria_nao_apaga_a_do_banco(monkeypatch):
    banco = _Banco()
    banco.linhas = []
    banco.dia = [[202610, "Altair 1", 20261001] + [1] * 6]
    _ligar(monkeypatch, banco, {"usinas": [U1]}, series={})
    assert app._ger_publicar(agora=datetime(2026, 10, 12, 10)) == 1 and banco.dia == [[202610, "Altair 1", 20261001] + [1] * 6]


def test_desligado_nao_publica(monkeypatch):
    banco = _Banco()
    _ligar(monkeypatch, banco, {"usinas": [U1]})
    monkeypatch.setattr(app, "_ger_publicar_ligado", lambda: False)
    assert app._ger_publicar(agora=datetime(2026, 10, 12, 10)) is None and banco.linhas is None
