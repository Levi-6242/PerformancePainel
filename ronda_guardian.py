# ronda_guardian.py - mantem o SERVIDOR da plataforma (porta 5050) no ar, para a RONDA de trackers
# disparar sozinha (08:25 e 13:15). Rodado pela Tarefa Agendada "GridCo Ronda Guardian" via
# pythonw.exe (SEM janela - nao pisca nada na tela). Idempotente: se a 5050 ja responde, sai.
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


if porta_aberta(5050):
    sys.exit(0)   # servidor ja no ar - nada a fazer

# sobe o servidor com o pythonw REAL, sem janela e destacado
pyw = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Python", "pythoncore-3.14-64", "pythonw.exe")
if not os.path.exists(pyw):
    pyw = "pythonw"
try:
    subprocess.Popen([pyw, "app.py"], cwd=DIR,
                     creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)
    with open(os.path.join(DIR, "ronda_guardian.log"), "a", encoding="utf-8") as f:
        f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S") +
                "  servidor 5050 estava fora - reiniciado pelo guardiao\n")
except Exception:
    pass
