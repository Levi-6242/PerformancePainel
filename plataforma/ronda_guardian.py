# ronda_guardian.py - mantem a plataforma no ar: o WORKER (trabalho pesado + RONDA de trackers)
# e o SERVIDOR web (porta 5050). Rodado pela Tarefa Agendada "GridCo Ronda Guardian" via
# pythonw.exe (SEM janela - nao pisca nada na tela). Idempotente: sobe so o que estiver faltando.
#
# Desde a separacao (25/07/2026) sao DOIS processos: worker.py reconstroi e publica o snapshot,
# app.py so le e serve. A ronda vive no WORKER - se so o app.py estiver de pe, o dashboard
# funciona mas a ronda NAO dispara. Por isso o guardiao vigia os dois.
import os
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


def ja_roda(script):
    """True se JA existe um python rodando esse script - mesmo que ainda BOOTANDO (o boot leva
    1-3min). Sem esta checagem o guardiao (a cada 5min) podia subir uma 2a instancia enquanto a
    1a carregava, e no Windows 2 processos co-escutam a 5050 = 2 loops de ronda = RONDA DOBRADA
    (Levi 20/07). Olha pythonw.exe E python.exe (diagnostico as vezes roda com console)."""
    try:
        ps = ("@(Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and "
              "$_.CommandLine -like '*" + script + "*' }).Count")
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                             capture_output=True, text=True, timeout=15,
                             creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
        return int(out or "0") > 0
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


# GRIDCO_SOLO=1 = modo antigo (um processo so faz tudo). Ai o worker NAO deve subir, senao a
# ronda roda em dobro.
solo = os.environ.get("GRIDCO_SOLO", "") == "1"

if not solo and not ja_roda("worker.py"):
    sobe("worker.py", "worker fora - sem ele nao ha ronda nem reaquecimento")

if not porta_aberta(5050) and not ja_roda("app.py"):
    sobe("app.py", "porta 5050 fechada")

sys.exit(0)
