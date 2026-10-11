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


NEXUS = r"C:\Users\Levi Maia\OneDrive - GRID CO\Área de Trabalho\temp\Nexus"


def test_o_nexus_pelo_nome_solto_nao_conta_como_a_plataforma():
    """Caso real (11/10/2026, reinício do PC): o Nexus subiu como `pythonw app.py`, com a pasta dele. O nome solto
    contava sem olhar a pasta: o guardião subiu só o worker e a 5050 (a ponte do OS Creator) ficou fechada."""
    assert not g._eh_da_plataforma(PYW + " app.py", "app.py", cwd=NEXUS)
    assert g._eh_da_plataforma(PYW + " app.py", "app.py", cwd=g.DIR)
    assert g._eh_da_plataforma(PYW + " app.py", "app.py", cwd=g.DIR + os.sep)       # barra no fim
    assert g._eh_da_plataforma(PYW + " app.py", "app.py")                           # pasta desconhecida: conta


def test_ja_roda_usa_a_mesma_regua(monkeypatch):
    procs = [(PY + r' -u "C:\temp\Nexus\app.py"', NEXUS), (PYW + " app.py", NEXUS), (PYW + " worker.py", g.DIR)]
    monkeypatch.setattr(g, "_processos_python", lambda: procs)
    assert not g.ja_roda("app.py")                     # só o Nexus (com e sem pasta): a plataforma NÃO está rodando
    assert g.ja_roda("worker.py")
    procs.append((PYW + " app.py", g.DIR))
    assert g.ja_roda("app.py")


def test_sem_psutil_cai_nas_linhas_de_comando(monkeypatch):
    import builtins
    original = builtins.__import__

    def _sem_psutil(nome, *a, **k):
        if nome == "psutil":
            raise ImportError("sem psutil")
        return original(nome, *a, **k)
    monkeypatch.setattr(builtins, "__import__", _sem_psutil)
    monkeypatch.setattr(g, "_linhas_de_comando_python", lambda: [PYW + " app.py"])
    assert g._processos_python() == [(PYW + " app.py", None)]
    assert g.ja_roda("app.py")                         # pasta desconhecida: na dúvida, conta


def test_o_processo_deste_teste_aparece_com_a_pasta():
    """O psutil de verdade: o python deste teste está na lista, com a pasta de trabalho dele."""
    assert any(cwd and g._mesma_pasta(cwd, os.getcwd()) for _c, cwd in g._processos_python())


def test_na_duvida_nao_sobe(monkeypatch):
    def _falha():
        raise RuntimeError("powershell fora")
    monkeypatch.setattr(g, "_processos_python", _falha)
    assert g.ja_roda("app.py")                         # duplicar a ronda é pior que ficar fora um ciclo
