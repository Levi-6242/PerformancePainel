"""O Painel NOC enxuto (13/10/2026, Levi: "Em painel NOC tire o botão de "Ao vivo" e remova o dashboard "Agrupamento"")."""
import pathlib
import re
import shutil
import subprocess

import pytest

HTML = (pathlib.Path(__file__).resolve().parents[1] / "plataforma" / "templates" / "painel_portfolio.html").read_text(
    encoding="utf-8")


def test_sem_a_pilula_ao_vivo_e_sem_o_agrupamento():
    assert 'id="livePill"' not in HTML and "AO VIVO</div>" not in HTML
    assert "<h3>Agrupamento" not in HTML and 'id="grpFilters"' not in HTML and 'id="region"' not in HTML
    assert "renderRegion" not in HTML                     # nada chama o desenho que saiu (o boot quebraria)
    assert 'id="modeToggle"' in HTML                       # o seletor Tempo real / Histórico fica


def test_o_script_do_painel_segue_valido():
    node = shutil.which("node")
    if not node:
        pytest.skip("node não instalado")
    for bloco in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", HTML, re.S):
        bloco = re.sub(r"\{%.*?%\}", "", re.sub(r"\{\{.*?\}\}", "0", bloco))
        p = subprocess.run([node, "--check", "-"], input=bloco, capture_output=True, text=True, encoding="utf-8")
        assert p.returncode == 0, p.stderr[:400]
