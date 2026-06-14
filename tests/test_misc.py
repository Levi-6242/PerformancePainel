"""Utilitários puros de app.py: extração de número, normalização e potência por inversor."""
import app


def test_spv_stnum():
    assert app._spv_stnum("INV 12") == 12
    assert app._spv_stnum("Tracker 7B") == 7
    assert app._spv_stnum("12-34") == 1234
    assert app._spv_stnum("sem numero") == 999   # fallback
    assert app._spv_stnum(None) == 999


def test_pv_trk_num():
    assert app._pv_trk_num("TRK16") == 16
    assert app._pv_trk_num("Tracker 03") == 3
    assert app._pv_trk_num("") == 999
    assert app._pv_trk_num(None) == 999


def test_nrm():
    assert app._nrm("  INV 01 ") == "inv01"
    assert app._nrm("A B C") == "abc"
    assert app._nrm("Inversor10") == "inversor10"


def test_num():
    assert app._num("12.5") == 12.5
    assert app._num("1e3") == 1000.0
    assert app._num(7) == 7.0
    assert app._num("abc") is None
    assert app._num(None) is None
    assert app._num(float("nan")) is None   # descarta NaN


def test_pot_inv(monkeypatch):
    monkeypatch.setattr(app, "POWER_INV", {"Araputanga": {"inv01": 1100.0}})
    # casa pelo nome da API, normalizado (espaços/maiúsculas ignorados)
    assert app._pot_inv("Araputanga", "INV 01") == 1100.0
    # cai para o nome de exibição quando o da API não bate
    assert app._pot_inv("Araputanga", "INV-X", "INV01") == 1100.0
    # inversor inexistente -> None
    assert app._pot_inv("Araputanga", "INV 99") is None
    # usina inexistente -> None
    assert app._pot_inv("Outra Usina", "INV 01") is None


def test_pot_inv_strip_no_nome_da_usina(monkeypatch):
    # _pot_inv tolera espaços ao redor do nome da usina (POWER_INV.get(strip)).
    monkeypatch.setattr(app, "POWER_INV", {"Araputanga": {"inv01": 1100.0}})
    assert app._pot_inv("  Araputanga  ", "INV 01") == 1100.0
