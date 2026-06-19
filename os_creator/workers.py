"""workers.py — QThread genérico para rodar chamadas de API sem travar a UI."""
from PyQt6.QtCore import QThread, pyqtSignal


class ApiWorker(QThread):
    """Executa fn(*args, **kwargs) numa thread separada.
    Emite `ok(resultado)` em sucesso ou `erro(mensagem)` em falha."""
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
            self.erro.emit(str(e))
