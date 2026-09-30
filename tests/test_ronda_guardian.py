# Guardião da plataforma local (ronda_guardian.py): quem conta como "a plataforma já está rodando".
#
# Caso real (29/09/2026): a plataforma foi reiniciada às 17:43 com o Nexus (outro projeto, `python -u
# "...\temp\Nexus\app.py"`) no ar. O guardião perguntava "existe algum python com app.py na linha de comando?", o
# Nexus respondia que sim, e a 5050 ficou fechada por 20 minutos — o guardião rodou de 5 em 5 minutos e nunca subiu
# o app.py da plataforma. O teste só vale para o processo DESTA pasta: o nome solto (como o guardião sobe, com cwd
# nela) ou o caminho completo dela.
import os

import ronda_guardian as g

PYW = r'"C:\Users\Levi Maia\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"'
PY = r'"C:\Users\Levi Maia\AppData\Local\Python\pythoncore-3.14-64\python.exe"'


def test_o_nexus_nao_conta_como_a_plataforma():
    nexus = PY + r' -u "C:\Users\Levi Maia\OneDrive - GRID CO\Área de Trabalho\temp\Nexus\app.py"'
    assert not g._eh_da_plataforma(nexus, "app.py")


def test_o_app_py_que_o_guardiao_sobe_conta():
    assert g._eh_da_plataforma(PYW + " app.py", "app.py")
    assert g._eh_da_plataforma(PYW + "  app.py ", "app.py")          # espaços sobrando
    assert g._eh_da_plataforma("pythonw app.py", "app.py")          # subido à mão, da pasta
    assert g._eh_da_plataforma(PY + " -u app.py", "app.py")         # diagnóstico com console


def test_o_caminho_completo_desta_pasta_conta():
    cheio = os.path.join(g.DIR, "app.py")
    assert g._eh_da_plataforma(f'{PY} "{cheio}"', "app.py")
    assert g._eh_da_plataforma(f'{PY} "{cheio.replace(os.sep, "/")}"', "app.py")   # com espaço, só entre aspas


def test_outro_script_ou_outro_modulo_nao_conta():
    assert not g._eh_da_plataforma(PYW + " worker.py", "app.py")
    assert not g._eh_da_plataforma(PYW + " -m gemeo.cli app", "app.py")
    assert not g._eh_da_plataforma(PY + r" C:/Users/x/scratchpad/confere_app.py", "app.py")
    assert not g._eh_da_plataforma(PY + " -m pytest tests/test_app.py", "app.py")
    assert not g._eh_da_plataforma("", "app.py")


def test_ja_roda_usa_a_mesma_regua(monkeypatch):
    linhas = [PY + r' -u "C:\temp\Nexus\app.py"', PYW + " worker.py"]
    monkeypatch.setattr(g, "_linhas_de_comando_python", lambda: linhas)
    assert not g.ja_roda("app.py")                     # só o Nexus: a plataforma NÃO está rodando
    assert g.ja_roda("worker.py")
    linhas.append(PYW + " app.py")
    assert g.ja_roda("app.py")


def test_na_duvida_nao_sobe(monkeypatch):
    def _falha():
        raise RuntimeError("powershell fora")
    monkeypatch.setattr(g, "_linhas_de_comando_python", _falha)
    assert g.ja_roda("app.py")                         # duplicar a ronda é pior que ficar fora um ciclo
