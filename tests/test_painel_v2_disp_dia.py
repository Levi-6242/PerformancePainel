# -*- coding: utf-8 -*-
"""A coluna "% disp" do Histórico do mês por inversor (Diagnóstico de usina v2) refaz no navegador a régua do Gerencial.
Desde 15/10/2026 a régua é só do Fracttal (Levi: "A disponibilidade será calculada somente pelo Fracttal a partir de
outubro"; "Será considerado OSs fechadas e abertas"; evento depois do fim usa a criação), e setembro para trás é a da
usina no BD_Thopen — por inversor não há, então o dia antes de outubro sai "—". Aqui a função roda no node, com o MESMO
código do template."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
TPL = Path(__file__).resolve().parents[1] / "plataforma" / "templates" / "painel_usina_v2.html"


def _roda(osall, ossite, dia, agora):
    if not NODE:
        pytest.skip("node não instalado")
    html = TPL.read_text(encoding="utf-8")
    fn = re.search(r"function _dispDia\(nome, dia\)\{.*?\n\}\n", html, re.S).group(0)
    js = f"""
const DISP_TIPOS = new Set(['religamento','religamento remoto','corretiva emergencial']);
const _hFmt = h => h.toFixed(2) + ' h';
const DISP_SO_FRACTTAL_DESDE = '2026-10-01';
let OSALL = {json.dumps(osall)}, OSSITE = {json.dumps(ossite)};
Date.now = () => new Date('{agora}').getTime();
{fn}
const r = _dispDia('Inversor 2.2', '{dia}');
console.log(JSON.stringify({{pct: r.pct, h: r.h, det: r.det, outras: r.outras}}));
"""
    p = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def _os(folio, evento, fim="", criada="", tipo="Religamento"):
    return {"folio": folio, "tipo": tipo, "evento_ts": evento, "fim_ts": fim, "criada_ts": criada}


def test_os_fechada_conta_as_horas_solares_do_dia():
    r = _roda({"Inversor 2.2": [_os(1, "2026-10-05T09:00:00", "2026-10-05T12:00:00")]}, [], "2026-10-05",
              "2026-10-14T10:00:00")
    assert r["h"] == pytest.approx(3.0) and r["pct"] == pytest.approx(75.0)


def test_os_aberta_conta_o_dia_inteiro_ate_agora():
    # a 16338 (Ipixuna 2, Inversor 2.2): Corretiva Emergencial aberta desde 16/09 — em 05/10 o dia todo conta
    r = _roda({"Inversor 2.2": [_os(16338, "2026-09-16T06:00:29", tipo="Corretiva Emergencial")]}, [], "2026-10-05",
              "2026-10-14T10:00:00")
    assert r["h"] == pytest.approx(12.0) and r["pct"] == pytest.approx(0.0)
    assert any("16338" in d for d in r["det"])


def test_os_aberta_no_dia_de_hoje_para_em_agora():
    r = _roda({"Inversor 2.2": [_os(2, "2026-10-14T06:00:00")]}, [], "2026-10-14", "2026-10-14T10:00:00")
    assert r["h"] == pytest.approx(4.0)


def test_evento_depois_do_fim_usa_a_criacao():
    r = _roda({"Inversor 2.2": [_os(3, "2026-10-05T15:00:00", "2026-10-05T12:00:00", "2026-10-05T10:00:00")]}, [],
              "2026-10-05", "2026-10-14T10:00:00")
    assert r["h"] == pytest.approx(2.0)


def test_fim_antes_ate_da_criacao_conta_zero():
    r = _roda({"Inversor 2.2": [_os(4, "2026-10-05T15:00:00", "2026-10-05T12:00:00", "2026-10-05T13:00:00")]}, [],
              "2026-10-05", "2026-10-14T10:00:00")
    assert r["h"] == 0 and r["pct"] == pytest.approx(100.0)


def test_falta_de_comunicacao_nao_tira_disponibilidade_do_dia():
    # Levi, 19/10/2026: "a falta de comunicação não deve entrar no cálculo de disponibilidade" — a OS de verificação de
    # comunicação (Religamento no Fracttal) fica só no título do dia, fora da conta
    os_com = {**_os(5, "2026-10-05T06:00:00", "2026-10-05T18:00:00"),
              "descricao": "[THPN-BWK100] - Verificação de comunicação do THPN-BWK100"}
    r = _roda({}, [os_com], "2026-10-05", "2026-10-14T10:00:00")
    assert r["h"] == 0 and r["pct"] == pytest.approx(100.0)
    assert any("falta de comunicação" in x for x in r["outras"])


def test_dia_antes_de_outubro_nao_tem_disponibilidade_por_inversor():
    r = _roda({"Inversor 2.2": [_os(16338, "2026-09-16T06:00:29", tipo="Corretiva Emergencial")]}, [], "2026-09-20",
              "2026-10-14T10:00:00")
    assert r["pct"] is None


def test_celula_do_dia_sem_disponibilidade_sai_traco_com_o_porque():
    # a célula também roda no node com o código do template: em 15/10 um "\n" virou quebra de linha DENTRO da string e a
    # página do Diagnóstico inteira deixou de carregar (SyntaxError) — só a suíte com a página toda pegou
    if not NODE:
        pytest.skip("node não instalado")
    html = TPL.read_text(encoding="utf-8")
    fn = re.search(r"function _dispTd\(dp\)\{.*?\n\}\n", html, re.S).group(0)
    js = ("const v2esc = s => String(s), nf = v => v.toFixed(1), _hFmt = h => h + ' h';\n" + fn
          + "console.log(JSON.stringify([_dispTd({pct: null, h: 0, det: [], outras: ['a', 'b']}),"
            " _dispTd({pct: 75, h: 3, det: ['OS 1'], outras: []})]));")
    p = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    sem, com = json.loads(p.stdout)
    assert ">—</td>" in sem and 'title="a\nb"' in sem
    assert "75.0%" in com and "3 h" in com
