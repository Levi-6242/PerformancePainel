# -*- coding: utf-8 -*-
"""A aba de Falhas segue o tema do Nexus (Levi, 12/10/2026: "em Falhas de strings e trackers falta o tema claro"). Dentro
da moldura a tela era sempre navy (`html.modo-nexus`); agora o navy vale só com o Nexus no escuro, e o claro usa as cores
da identidade do site, as mesmas da tela aberta direto. O tema vem do cookie `nexus_tema` (ou do localStorage
`nexus.tema`) antes da 1ª pintura, e o botão do Nexus troca a tela na hora pelo evento `storage`."""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

HTML = (pathlib.Path(__file__).resolve().parents[1] / "plataforma" / "templates" / "falhas.html").read_text(encoding="utf-8")


def test_o_navy_so_vale_com_o_nexus_no_escuro():
    assert 'html.modo-nexus:not([data-tema="claro"]){color-scheme:dark;' in HTML
    soltas = [l for l in HTML.splitlines() if re.search(r"html\.modo-nexus(?!:not\(\[data-tema=\"claro\"\]\))[ {.,]", l)
              and not l.strip().startswith(("/*", "*", "modo-nexus"))]
    assert soltas == [], f"regra do modo Nexus sem o tema: {soltas}"


def _cabeca():
    i = HTML.index("<script>")
    return HTML[i + len("<script>"):HTML.index("</script>", i)]


def _roda(cookie, local, depois=None):
    node = shutil.which("node")
    if not node:
        pytest.skip("node não instalado")
    js = ("const attrs={}; const ouvintes={};"
          "global.document={cookie:%s, documentElement:{setAttribute:(k,v)=>{attrs[k]=v;}}};"
          "global.localStorage={getItem:k=>(%s)[k]||null};"
          "global.window={addEventListener:(t,f)=>{ouvintes[t]=f;}};"
          % (json.dumps(cookie), json.dumps(local)) + _cabeca() +
          (";ouvintes.storage(%s);" % json.dumps(depois) if depois else "") +
          "process.stdout.write(JSON.stringify(attrs));")
    p = subprocess.run([node, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_o_tema_vem_do_cookie_do_nexus_e_troca_na_hora():
    assert _roda("a=1; nexus_tema=claro", {}) == {"data-tema": "claro"}
    assert _roda("", {"nexus.tema": "escuro"}) == {"data-tema": "escuro"}               # sem o cookie, o localStorage
    assert _roda("", {}) == {}                                                          # aberta direto: nada muda
    assert _roda("nexus_tema=escuro", {}, {"key": "nexus.tema", "newValue": "claro"}) == {"data-tema": "claro"}
    assert _roda("nexus_tema=escuro", {}, {"key": "outra", "newValue": "claro"}) == {"data-tema": "escuro"}
