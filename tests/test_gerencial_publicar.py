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
    def __init__(self):
        self.linhas, self.fora, self.envios = None, False, 0

    def get(self, url, headers=None, params=None, timeout=None):
        if self.fora:
            raise ConnectionError("banco fora")
        if url.endswith("/api/sheets"):
            return _R([{"id": 7, "workbook_key": gp.LIVRO, "sheet_name": gp.ABA}] if self.linhas is not None else [])
        off, lim = params["offset"], params["limit"]
        return _R({"rows": [{"headers": gp.CAB, "values": lin} for lin in (self.linhas or [])[off:off + lim]]})

    def sincronizar(self, conteudo, **k):
        from io import BytesIO
        from openpyxl import load_workbook
        assert k["chave"] == gp.LIVRO
        ws = load_workbook(BytesIO(conteudo))[gp.ABA]
        self.linhas = [list(r) for r in ws.iter_rows(min_row=2, values_only=True)]
        self.envios += 1
        return {"inserted": len(self.linhas)}


def _ligar(monkeypatch, banco, gerencial):
    import falhas_publicar
    monkeypatch.setattr(app, "_ger_publicar_ligado", lambda: True)
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


def test_desligado_nao_publica(monkeypatch):
    banco = _Banco()
    _ligar(monkeypatch, banco, {"usinas": [U1]})
    monkeypatch.setattr(app, "_ger_publicar_ligado", lambda: False)
    assert app._ger_publicar(agora=datetime(2026, 10, 12, 10)) is None and banco.linhas is None
