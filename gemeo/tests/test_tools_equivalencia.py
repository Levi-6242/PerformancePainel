# gemeo/tests/test_tools_equivalencia.py
"""A regua de mudanca: mesma fixture, mesmos parametros -> diferenca zero (dentro de 1e-6); parametro
diferente -> a diferenca aparece e o CLI sai 1. Igualdade exata de float nunca entra aqui."""
from pathlib import Path

from gemeo.modelar import gate
from tools import equivalencia

FX = Path(__file__).parent / "fixtures" / "golden" / "mro100_2026-08-31.json"


def test_mesmos_parametros_sao_equivalentes():
    res = equivalencia.rodar(FX, gate.ParamsGate(), gate.ParamsGate(), {}, {})
    assert set(res) >= {"esperado_kw", "gate_ok", "parado", "tracker", "string", "residuo", "cascata"}
    assert max(res.values()) <= 1e-6


def test_perdas_diferentes_nao_sao_equivalentes():
    res = equivalencia.rodar(FX, gate.ParamsGate(), gate.ParamsGate(), {}, {"perdas_fixas": 0.20})
    assert res["esperado_kw"] > 1.0 and res["cascata"] > 1.0 and res["gate_ok"] <= 1e-6


def test_cli_sai_0_quando_equivalente_e_1_quando_nao(capsys):
    assert equivalencia.main([str(FX)]) == 0
    assert equivalencia.main([str(FX), "--b-perdas", "0.20"]) == 1
    saida = capsys.readouterr().out
    assert '"equivalente": true' in saida and '"equivalente": false' in saida
