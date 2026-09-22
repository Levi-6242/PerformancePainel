# -*- coding: utf-8 -*-
"""As contas do Acompanhamento COS (mediana, P25/P75/P90, % em até 30 min, limite de outlier) rodam no
navegador, sobre as linhas do /api/cos/mtta. Aqui elas rodam no node com o MESMO código extraído da
tela, contra a conta feita à mão em Python — é o número que o coordenador do COS lê."""
import json
import math
import pathlib
import shutil
import subprocess

import pytest

import app

TELA = (pathlib.Path(app.__file__).resolve().parent / "templates" / "cos.html").read_text(encoding="utf-8")
NODE = shutil.which("node")


def _trecho(ini, fim):
    i = TELA.index(ini)
    return TELA[i:TELA.index(fim, i) + len(fim)]


def _roda(expr):
    if not NODE:
        pytest.skip("node não instalado")
    js = "\n".join([_trecho("function q(", "/* fim q */"), _trecho("function est(", "/* fim est */"),
                    _trecho("function cerca(", "/* fim cerca */"),
                    "process.stdout.write(JSON.stringify(" + expr + "));"])
    r = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _q(v, p):                       # percentil por interpolação linear (o mesmo do numpy padrão)
    v = sorted(v)
    k = (len(v) - 1) * p
    f, c = math.floor(k), math.ceil(k)
    return v[f] if f == c else v[f] + (v[c] - v[f]) * (k - f)


MINUTOS = [3, 8, 12, 15, 22, 30, 31, 45, 60, 95, 140, 600, 2900]
LINHAS = [{"m": m, "raj": 1 if m in (95, 140) else 0} for m in MINUTOS]


def test_mediana_e_percentis_da_tela_batem_com_a_conta_a_mao():
    s = _roda("est(%s)" % json.dumps(LINHAS))
    assert s["n"] == len(MINUTOS)
    for k, p in (("p25", .25), ("p50", .5), ("p75", .75), ("p90", .9)):
        assert s[k] == pytest.approx(_q(MINUTOS, p)), k
    assert s["a30"] == pytest.approx(6 / 13)          # 3, 8, 12, 15, 22 e 30 — o limite entra
    assert s["a15"] == pytest.approx(4 / 13)
    assert s["raj"] == pytest.approx(2 / 13)


def test_limite_de_outlier_e_tukey_na_escala_log():
    lg = [math.log10(max(m, .5)) for m in MINUTOS]
    q1, q3 = _q(lg, .25), _q(lg, .75)
    assert _roda("cerca(%s)" % json.dumps(LINHAS)) == pytest.approx(10 ** (q3 + 1.5 * (q3 - q1)))


def test_poucas_os_nao_tem_limite_de_outlier():
    # com menos de 8 OSs o quartil é ruído: a tela diz "poucas OSs" em vez de apontar outlier
    assert _roda("cerca(%s) === Infinity" % json.dumps(LINHAS[:7])) is True


def test_recorte_vazio_nao_quebra_a_conta():
    assert _roda("est([])") is None
