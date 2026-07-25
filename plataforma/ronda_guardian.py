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


def app_py_ja_roda():
    """True se JA existe um pythonw rodando app.py — mesmo que ainda BOOTANDO (porta 5050 fechada). O
    boot leva 1-3min; sem esta checagem o guardiao (a cada 5min) podia subir uma 2a instancia enquanto a
    1a carregava, e no Windows 2 app.py co-escutam a 5050 = 2 loops de ronda = RONDA DOBRADA (Levi 20/07)."""
    try:
        ps = ("@(Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | "
              "Where-Object { $_.CommandLine -like '*app.py*' }).Count")
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                             capture_output=True, text=True, timeout=12,
                             creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
        return int(out or "0") > 0
    except Exception:
        return False   # na duvida, deixa subir (comportamento antigo)


if porta_aberta(5050) or app_py_ja_roda():
    sys.exit(0)   # servidor no ar OU ainda subindo - nao sobe uma 2a instancia

# sobe o servidor com o pythonw REAL, sem janela e destacado
pyw = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Python", "pythoncore-3.14-64", "pythonw.exe")
if not os.path.exists(pyw):
    pyw = "pythonw"
try:
    subprocess.Popen([pyw, "app.py"], cwd=DIR,
                     creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)
    os.makedirs(os.path.join(DIR, "logs"), exist_ok=True)
    with open(os.path.join(DIR, "logs", "ronda_guardian.log"), "a", encoding="utf-8") as f:
        f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S") +
                "  servidor 5050 estava fora - reiniciado pelo guardiao\n")
except Exception:
    pass
