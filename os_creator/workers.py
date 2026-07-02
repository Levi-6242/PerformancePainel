"""workers.py — QThread genérico para rodar chamadas de API sem travar a UI."""
import datetime
import functools
import os
import sys
import tempfile
import traceback
from PyQt6.QtCore import QThread, QObject, pyqtSignal


# ── diagnóstico: log de erros (p/ descobrir por que o app "fecha sozinho") ──────────────────────
_LOG = os.path.join(tempfile.gettempdir(), "criaros_erros.log")


def registrar_erro(exc_info=None):
    """Grava o traceback (atual, ou o passado em `exc_info`) no log e no console."""
    ei = exc_info or sys.exc_info()
    if not ei or ei[0] is None:
        return
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 60 + "\n" + datetime.datetime.now().isoformat() + "\n")
            traceback.print_exception(ei[0], ei[1], ei[2], file=f)
    except Exception:
        pass
    try:
        traceback.print_exception(ei[0], ei[1], ei[2])
    except Exception:
        pass


def slot_seguro(fn):
    """Decora um slot p/ NUNCA deixar uma exceção escapar para o Qt/C++. No PyQt6 uma exceção não
    tratada dentro de um slot ENCERRA o app — era uma das causas de 'o app fecha sozinho'. Aqui a
    exceção é registrada no log e engolida, mantendo o app de pé."""
    @functools.wraps(fn)
    def _wrap(*a, **k):
        try:
            return fn(*a, **k)
        except Exception:
            registrar_erro()
    return _wrap


class _AuthBus(QObject):
    """Barramento global: avisa a janela quando a sessão do Fracttal morre, p/ forçar novo login
    (em vez de a UI ficar vazia em silêncio). Emitido de dentro do worker → slot na thread principal."""
    sessao_expirou = pyqtSignal(str)


auth_bus = _AuthBus()


# Mantém referências VIVAS das threads em andamento. Sem isso, quando o chamador zera a própria
# referência do worker dentro do slot ok/erro (ex.: `self._w = None`), o Python coleta o QThread
# enquanto o run() ainda pode não ter retornado → "QThread: Destroyed while thread is still running"
# → o app aborta (crash intermitente). A thread só sai daqui quando REALMENTE termina (finished).
_ALIVE = set()


class ApiWorker(QThread):
    """Executa fn(*args, **kwargs) numa thread separada.
    Emite `ok(resultado)` em sucesso ou `erro(mensagem)` em falha. Se a falha for sessão morta
    (exceção com .session_expired), também dispara auth_bus.sessao_expirou p/ a janela relogar."""
    ok = pyqtSignal(object)
    erro = pyqtSignal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def start(self, priority=QThread.Priority.InheritPriority):
        _ALIVE.add(self)                       # segura a ref até o fim de verdade
        self.finished.connect(self._despedir)  # finished roda na thread principal (afinidade do worker)
        super().start(priority)

    def _despedir(self):
        _ALIVE.discard(self)

    def run(self):
        try:
            self.ok.emit(self._fn(*self._args, **self._kwargs))
        except Exception as e:
            if getattr(e, "session_expired", False):     # token morto → avisa a janela
                auth_bus.sessao_expirou.emit(str(e))
            self.erro.emit(str(e))
