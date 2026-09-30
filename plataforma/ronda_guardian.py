# ronda_guardian.py - mantem a plataforma no ar: o WORKER (trabalho pesado + RONDA de trackers)
# e o SERVIDOR web (porta 5050). Rodado pela Tarefa Agendada "GridCo Ronda Guardian" via
# pythonw.exe (SEM janela - nao pisca nada na tela). Idempotente: sobe so o que estiver faltando.
#
# Desde a separacao (25/07/2026) sao DOIS processos: worker.py reconstroi e publica o snapshot,
# app.py so le e serve. A ronda vive no WORKER - se so o app.py estiver de pe, o dashboard
# funciona mas a ronda NAO dispara. Por isso o guardiao vigia os dois.
import os
import re
import socket
import subprocess
import sys
from datetime import datetime

DIR = os.path.dirname(os.path.abspath(__file__))


def porta_aberta(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.5)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False
    finally:
        s.close()


def _linhas_de_comando_python():
    """Linha de comando de cada python vivo (pythonw.exe E python.exe: diagnostico as vezes roda com console)."""
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' } | "
          "ForEach-Object { [string]$_.CommandLine }")
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                         capture_output=True, text=True, timeout=15, encoding="utf-8", errors="replace",
                         creationflags=subprocess.CREATE_NO_WINDOW)
    if out.returncode != 0:
        raise RuntimeError(f"powershell saiu com {out.returncode}")
    return [l for l in out.stdout.splitlines() if l.strip()]


def _eh_da_plataforma(cmd, script):
    """True se a linha de comando roda o `script` DESTA pasta: pelo nome solto (como `sobe` o chama, com cwd aqui)
    ou pelo caminho completo dela. Ate 29/09/2026 bastava ter o texto do script em qualquer lugar da linha: o Nexus
    (outro projeto, `python -u "...\\temp\\Nexus\\app.py"`) contava como a plataforma, e depois do reinicio das 17:43
    a 5050 ficou fechada 20 minutos — o guardiao rodava de 5 em 5 e nunca subia o app.py."""
    for m in re.finditer(r'"([^"]*)"|(\S+)', cmd or ""):
        tok = m.group(1) if m.group(1) is not None else m.group(2)
        pasta, nome = os.path.split(tok.replace("/", os.sep))
        if nome.lower() != script.lower():
            continue
        if not pasta or os.path.normcase(os.path.abspath(pasta)) == os.path.normcase(DIR):
            return True
    return False


def ja_roda(script):
    """True se JA existe um python rodando esse script - mesmo que ainda BOOTANDO (o boot leva
    1-3min). Sem esta checagem o guardiao (a cada 5min) podia subir uma 2a instancia enquanto a
    1a carregava, e no Windows 2 processos co-escutam a 5050 = 2 loops de ronda = RONDA DOBRADA
    (Levi 20/07). So conta o script DESTA pasta (ver _eh_da_plataforma)."""
    try:
        return any(_eh_da_plataforma(c, script) for c in _linhas_de_comando_python())
    except Exception:
        return True   # na duvida, NAO sobe (duplicar a ronda e pior que ficar fora um ciclo)


def registra(msg):
    try:
        os.makedirs(os.path.join(DIR, "logs"), exist_ok=True)
        with open(os.path.join(DIR, "logs", "ronda_guardian.log"), "a", encoding="utf-8") as f:
            f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "  " + msg + "\n")
    except Exception:
        pass


pyw = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Python", "pythoncore-3.14-64", "pythonw.exe")
if not os.path.exists(pyw):
    pyw = "pythonw"


def sobe(script, motivo):
    try:
        subprocess.Popen([pyw, script], cwd=DIR,
                         creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)
        registra(f"{script} estava fora ({motivo}) - reiniciado pelo guardiao")
    except Exception as e:
        registra(f"FALHA ao subir {script}: {e}")


if __name__ == "__main__":
    # GRIDCO_SOLO=1 = modo antigo (um processo so faz tudo). Ai o worker NAO deve subir, senao a
    # ronda roda em dobro.
    solo = os.environ.get("GRIDCO_SOLO", "") == "1"

    if not solo and not ja_roda("worker.py"):
        sobe("worker.py", "worker fora - sem ele nao ha ronda nem reaquecimento")

    if not porta_aberta(5050) and not ja_roda("app.py"):
        sobe("app.py", "porta 5050 fechada")

    sys.exit(0)
