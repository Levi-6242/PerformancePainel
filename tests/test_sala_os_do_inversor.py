# -*- coding: utf-8 -*-
"""A OS de performance no inversor da Sala de controle (25/11/2026).

Levi, na PEIII, com a OS 19786 aberta para o Inversor 1.7: "Esses inversores aqui, eles já tem o OS aberta, aqui não está
aparecendo o símbolo de manutenção de OS". A 19786 é UMA OS com três ativos (Inversores 1.1, 1.5 e 1.7) e a descrição
só "Recomposição de String"; a Sala casava o inversor apenas pelo "[Inversor N.M]" da descrição. No índice do Fracttal
de 25/11, 88 das 186 linhas de OS de performance abertas traziam o inversor só no ativo. As funções da tela rodam no node
com OS de mentira no formato de /api/os-performance."""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

NODE = shutil.which("node")
TPL = pathlib.Path(__file__).resolve().parents[1] / "plataforma" / "templates" / "sala_controle.html"


def _funcoes():
    s = TPL.read_text(encoding="utf-8")
    trechos = []
    for nome in ("invDaOs", "osAgrupadas"):
        m = re.search(r"^function " + nome + r"\(.*?^}\n", s, re.S | re.M)
        assert m, f"a função {nome} sumiu da Sala"
        trechos.append(m.group(0))
    rx = re.search(r"^const RX_INV_NOTA = .*?;\n", s, re.M)
    assert rx, "as regras do inversor na OS sumiram da Sala"
    return rx.group(0) + "".join(trechos)


def _roda(js):
    r = subprocess.run([NODE, "-e", _funcoes() + js], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


NOMES = 'new Set(["Inversor 1.1", "Inversor 1.2", "Inversor 1.5", "Inversor 1.7"])'


@pytest.mark.skipif(not NODE, reason="node não instalado")
def test_sem_o_inversor_na_descricao_vale_o_ativo_da_os():
    oss = [{"os": "19786", "nota": "Recomposição de String", "sub": "Inversor 1.7 Huawei SUN2000-250KTL-H1"},
           {"os": "19786", "nota": "Recomposição de String", "sub": "Inversor 1.5 Huawei SUN2000-250KTL-H1"},
           {"os": "20227", "nota": "[Inversor 1.2] - Recomposição de String", "sub": "Inversor 1.2 Huawei"},
           {"os": "19730", "nota": "[Estrutura Trackers] - Mapeamento", "sub": "Estrutura Trackers  Petrolina"},
           {"os": "15817", "nota": "[Inversor 1.1] - Corrente reversa", "sub": "Inversor 3.4 Huawei"},
           {"os": "17428", "nota": "Religamento", "sub": "Inversor 1.25 Huawei"}]
    r = _roda(f"const n = {NOMES}; console.log(JSON.stringify({json.dumps(oss)}.map(x => invDaOs(x, n))));")
    # a 19786 entra nos dois inversores; a descrição do OS Creator vence o ativo (como sempre foi); o tracker não é
    # inversor; o ativo que não é inversor desta usina (a Barretos numera 1.21-1.40 no Fracttal) fica sem inversor
    assert r == ["Inversor 1.7", "Inversor 1.5", "Inversor 1.2", None, "Inversor 1.1", None]


@pytest.mark.skipif(not NODE, reason="node não instalado")
def test_o_cabecalho_mostra_cada_os_uma_vez_com_os_inversores_dela():
    oss = [{"os": "20227", "inv": "Inversor 1.2"}, {"os": "19786", "inv": "Inversor 1.7"},
           {"os": "19786", "inv": "Inversor 1.5"}, {"os": "19786", "inv": "Inversor 1.10"},
           {"os": "19730", "inv": None}, {"os": "18771", "inv": None}]
    r = _roda(f"console.log(JSON.stringify(osAgrupadas({json.dumps(oss)})));")
    assert r == ["20227 (1.2)", "19786 (1.5, 1.7, 1.10)", "19730", "18771"]


def test_a_sala_usa_as_duas_regras():
    s = TPL.read_text(encoding="utf-8")
    assert "inv: invDaOs(x, nomes)" in s and "/\\[(Inversor \\d+\\.\\d+)/.exec(x.nota" not in s
    assert "osAgrupadas(oss)" in s
