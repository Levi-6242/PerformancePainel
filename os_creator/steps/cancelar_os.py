"""Diálogo de cancelamento de OS — motivo (status custom) + observação. Tipo fixo 'Cancelar OS'.
A AUTORIZAÇÃO é a do usuário no Fracttal: se a conta não puder cancelar, a API recusa e mostramos o erro."""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QTextEdit,
                             QPushButton, QMessageBox)
import api
from workers import ApiWorker


def abrir_cancelar_os(parent, id_work_order, folio=None):
    """Abre o diálogo de cancelamento. → True se a OS foi cancelada."""
    dlg = CancelarOSDialog(parent, id_work_order, folio)
    dlg.exec()
    return dlg.cancelled


class CancelarOSDialog(QDialog):
    def __init__(self, parent, id_work_order, folio=None):
        super().__init__(parent)
        self._wo = id_work_order
        self._folio = folio
        self.cancelled = False
        self._wm = self._wc = None
        self.setWindowTitle(f"Cancelar OS {folio or id_work_order}")
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self); lay.setContentsMargins(16, 14, 16, 14); lay.setSpacing(8)

        lay.addWidget(QLabel(f"<b style='font-size:14px'>Cancelar a OS {folio or id_work_order}</b>"))
        lay.addWidget(QLabel("<span style='color:#8a90a2'>Tipo: <b>Cancelar OS</b> · a autorização é a "
                             "do seu usuário no Fracttal.</span>"))
        lay.addWidget(QLabel("<b>Motivo do cancelamento</b>"))
        self.cb_motivo = QComboBox(); self.cb_motivo.addItem("carregando motivos…", None)
        self.cb_motivo.currentIndexChanged.connect(self._upd)
        lay.addWidget(self.cb_motivo)
        lay.addWidget(QLabel("<b>Observação</b> <span style='color:#8a90a2'>(opcional)</span>"))
        self.obs = QTextEdit(); self.obs.setFixedHeight(64)
        lay.addWidget(self.obs)
        self.hint = QLabel(""); self.hint.setObjectName("hint")
        lay.addWidget(self.hint)

        row = QHBoxLayout()
        b_back = QPushButton("Voltar"); b_back.setObjectName("secondary"); b_back.clicked.connect(self.reject)
        self.btn = QPushButton("Confirmar cancelamento"); self.btn.setEnabled(False)
        self.btn.clicked.connect(self._confirmar)
        row.addWidget(b_back); row.addWidget(self.btn, 1)
        lay.addLayout(row)
        self._carregar_motivos()

    def _carregar_motivos(self):
        self.hint.setText("carregando motivos…")
        self._wm = ApiWorker(api.get_cancel_motivos)
        self._wm.ok.connect(self._set_motivos)
        self._wm.erro.connect(lambda m: self.hint.setText("⚠ " + m))
        self._wm.start()

    def _set_motivos(self, motivos):
        self._wm = None
        self.cb_motivo.clear()
        self.cb_motivo.addItem("— selecione o motivo —", None)
        for m in (motivos or []):
            self.cb_motivo.addItem(m.get("description") or "?", m.get("id"))
        self.hint.setText("" if motivos else "⚠ nenhum motivo retornado pelo Fracttal")
        self._upd()

    def _upd(self, *_):
        self.btn.setEnabled(self.cb_motivo.currentData() is not None)

    def _confirmar(self):
        idm = self.cb_motivo.currentData()
        if idm is None:
            QMessageBox.warning(self, "Motivo", "Escolha o motivo do cancelamento."); return
        if QMessageBox.question(self, "Cancelar OS",
                f"Confirma o cancelamento da OS {self._folio or self._wo}?\n"
                "Isto muda o status dela no Fracttal.") != QMessageBox.StandardButton.Yes:
            return
        self.btn.setEnabled(False)
        self.hint.setText("cancelando no Fracttal…")
        self._wc = ApiWorker(api.cancel_os, self._wo, idm, self.obs.toPlainText().strip())
        self._wc.ok.connect(self._ok)
        self._wc.erro.connect(self._err)
        self._wc.start()

    def _ok(self, _res):
        self._wc = None
        self.cancelled = True
        QMessageBox.information(self, "OS cancelada", f"OS {self._folio or self._wo} cancelada com sucesso.")
        self.accept()

    def _err(self, m):
        self._wc = None
        self.btn.setEnabled(True); self.hint.setText("")
        QMessageBox.critical(self, "Não foi possível cancelar", m)
