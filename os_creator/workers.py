"""workers.py — QThread genérico para rodar chamadas de API sem travar a UI."""
from PyQt6.QtCore import QThread, QObject, pyqtSignal


class _AuthBus(QObject):
    """Barramento global: avisa a janela quando a sessão do Fracttal morre, p/ forçar novo login
    (em vez de a UI ficar vazia em silêncio). Emitido de dentro do worker → slot na thread principal."""
    sessao_expirou = pyqtSignal(str)


auth_bus = _AuthBus()


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

    def run(self):
        try:
            self.ok.emit(self._fn(*self._args, **self._kwargs))
        except Exception as e:
            if getattr(e, "session_expired", False):     # token morto → avisa a janela
                auth_bus.sessao_expirou.emit(str(e))
            self.erro.emit(str(e))
