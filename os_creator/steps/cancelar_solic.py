"""Diálogo de cancelamento de SOLICITAÇÃO de serviço — uma nota + confirmação. O status vai para
Cancelada (CANCEL_STATUS). A AUTORIZAÇÃO é a do usuário no Fracttal: se a conta não puder cancelar,
a API recusa e mostramos o erro."""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
                             QPushButton, QMessageBox)
import api
from workers import ApiWorker


def abrir_cancelar_solic(parent, id_request, id_code=None):
    """Abre o diálogo de cancelamento da solicitação. → True se foi cancelada."""
    dlg = CancelarSolicDialog(parent, id_request, id_code)
    dlg.exec()
    return dlg.cancelled


class CancelarSolicDialog(QDialog):
    def __init__(self, parent, id_request, id_code=None):
        super().__init__(parent)
        self._id = id_request
        self._code = id_code if id_code is not None else id_request
        self.cancelled = False
        self._wc = None
        self.setWindowTitle(f"Cancelar solicitação {self._code}")
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self); lay.setContentsMargins(16, 14, 16, 14); lay.setSpacing(8)

        lay.addWidget(QLabel(f"<b style='font-size:14px'>Cancelar a solicitação Nº {self._code}</b>"))
        lay.addWidget(QLabel("<span style='color:#8a90a2'>O status vai para <b>Cancelada</b> · a "
                             "autorização é a do seu usuário no Fracttal.</span>"))
        lay.addWidget(QLabel("<b>Nota</b> <span style='color:#8a90a2'>(opcional)</span>"))
        self.obs = QTextEdit(); self.obs.setFixedHeight(72)
        lay.addWidget(self.obs)
        self.hint = QLabel(""); self.hint.setObjectName("hint")
        lay.addWidget(self.hint)

        row = QHBoxLayout()
        b_back = QPushButton("Voltar"); b_back.setObjectName("secondary"); b_back.clicked.connect(self.reject)
        self.btn = QPushButton("Confirmar cancelamento"); self.btn.clicked.connect(self._confirmar)
        row.addWidget(b_back); row.addWidget(self.btn, 1)
        lay.addLayout(row)

    def _confirmar(self):
        if QMessageBox.question(self, "Cancelar solicitação",
                f"Confirma o cancelamento da solicitação Nº {self._code}?\n"
                "Isto muda o status dela no Fracttal.") != QMessageBox.StandardButton.Yes:
            return
        self.btn.setEnabled(False)
        self.hint.setText("cancelando no Fracttal…")
        self._wc = ApiWorker(api.cancelar_solicitacao, self._id, self.obs.toPlainText().strip())
        self._wc.ok.connect(self._ok)
        self._wc.erro.connect(self._err)
        self._wc.start()

    def _ok(self, _res):
        self._wc = None
        self.cancelled = True
        QMessageBox.information(self, "Solicitação cancelada",
                                f"Solicitação Nº {self._code} cancelada com sucesso.")
        self.accept()

    def _err(self, m):
        self._wc = None
        self.btn.setEnabled(True); self.hint.setText("")
        QMessageBox.critical(self, "Não foi possível cancelar", m)
