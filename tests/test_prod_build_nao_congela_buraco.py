# -*- coding: utf-8 -*-
"""Build que morreu no meio não pode virar 'dado fresco' (varredura de 09/09/2026).

`_thopen_prod_build` e `_bdperf_prod_build` montam a produção do mês (as duas metades do Gerencial que
não vêm do PG). O `try` envolve o laço inteiro, e o carimbo do cache ficava FORA dele: banco fora do ar
ou planilha travada → `out` vazio, e mesmo assim `ts = agora`. O TTL é de 30 min: a carteira inteira
aparecia como "sem coleta" por meia hora por causa de uma falha de 2 segundos, e o `warming` já tinha
baixado — ninguém tentava de novo.

É a mesma lição que o `_cache_load` e o `_meta_snapshot_preservando` já carregam escrita: VAZIO NÃO
SOBRESCREVE CHEIO. Faltava aqui.
"""
import app


def test_thopen_falhando_mantem_o_ultimo_bom_e_deixa_tentar_de_novo(monkeypatch):
    import dashboard_thopen as dth

    def _explode():
        raise RuntimeError("PostgreSQL fora do ar")

    monkeypatch.setattr(dth, "_registro", _explode)
    bom = {"usina x": {"usina": "Usina X", "prod_mwh": 123.4}}
    monkeypatch.setattr(app, "_thopen_prod_cache",
                        {"ts": 1000.0, "ym": (2026, 9), "data": dict(bom), "warming": True})
    app._thopen_prod_build()
    c = app._thopen_prod_cache
    assert c["data"] == bom, "o buraco de 2 segundos apagou a carteira Thopen do Gerencial"
    assert c["ts"] == 1000.0, "carimbar ts fresco congela o buraco por um TTL inteiro (30 min)"
    assert c["warming"] is False, "sem baixar o warming, a próxima chamada nem tenta reconstruir"


def test_thopen_que_terminou_atualiza_normalmente(monkeypatch):
    """Régua intacta no caminho feliz: build completo com resultado instala e carimba."""
    import dashboard_thopen as dth
    from datetime import datetime as _dt
    hoje = _dt.now()
    monkeypatch.setattr(dth, "_registro", lambda: {"Usina Y": {"cliente": "Thopen", "pot_mwp": 1.0}})
    monkeypatch.setattr(dth, "_CARTEIRA_DE", {"Usina Y": "Thopen"})
    monkeypatch.setattr(dth, "_daily_records",
                        lambda u: [{"data": hoje, "ger": 1000.0, "ipoa": 5.0}])
    monkeypatch.setattr(app, "_thopen_prod_cache",
                        {"ts": 1000.0, "ym": None, "data": {"velho": {}}, "warming": True})
    app._thopen_prod_build()
    c = app._thopen_prod_cache
    assert app._nrm("Usina Y") in c["data"] and "velho" not in c["data"]
    assert c["ts"] > 1000.0 and c["warming"] is False


def test_thopen_vazio_nao_apaga_o_que_ja_havia(monkeypatch):
    """Universo que volta vazio (registro sem linhas) é degradação silenciosa, não notícia."""
    import dashboard_thopen as dth
    monkeypatch.setattr(dth, "_registro", lambda: {})
    monkeypatch.setattr(dth, "_CARTEIRA_DE", {})
    bom = {"usina x": {"usina": "Usina X", "prod_mwh": 123.4}}
    monkeypatch.setattr(app, "_thopen_prod_cache",
                        {"ts": 1000.0, "ym": (2026, 9), "data": dict(bom), "warming": True})
    app._thopen_prod_build()
    assert app._thopen_prod_cache["data"] == bom
    assert app._thopen_prod_cache["ts"] == 1000.0


def test_no_boot_o_cache_vazio_aceita_qualquer_resultado(monkeypatch):
    """Sem nada guardado, até o resultado vazio é instalado — senão o `ym` nunca fecha e o Gerencial
    ficaria pedindo build a cada chamada."""
    import dashboard_thopen as dth
    monkeypatch.setattr(dth, "_registro", lambda: {})
    monkeypatch.setattr(dth, "_CARTEIRA_DE", {})
    monkeypatch.setattr(app, "_thopen_prod_cache", {"ts": 0.0, "ym": None, "data": {}, "warming": True})
    app._thopen_prod_build()
    assert app._thopen_prod_cache["ts"] > 0.0 and app._thopen_prod_cache["ym"] is not None


def test_bdperf_falhando_mantem_o_ultimo_bom(monkeypatch):
    """Mesma régua na outra metade (abas do BD_Performance): planilha travada pelo OneDrive é o caso
    comum, e ela não pode zerar Athon/Axis/2C no Gerencial."""
    def _explode():
        raise RuntimeError("planilha em uso")

    monkeypatch.setattr(app, "_bd_readable", _explode)
    bom = {"usina z": {"usina": "Usina Z", "prod_mwh": 9.9}}
    monkeypatch.setattr(app, "_bdperf_prod_cache",
                        {"ts": 2000.0, "ym": (2026, 9), "data": dict(bom), "warming": True})
    app._bdperf_prod_build()
    c = app._bdperf_prod_cache
    assert c["data"] == bom and c["ts"] == 2000.0 and c["warming"] is False
