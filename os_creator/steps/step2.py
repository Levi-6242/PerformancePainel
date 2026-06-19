"""Step 2 — Detalhes da tarefa: descrição + tipo (Corretiva/Inspeção).
Campos fixos invisíveis (tratados no api.py): criticidade Alta, enviar p/ tarefas pendentes."""
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
                             QComboBox, QLineEdit, QPushButton)


class Step2(QWidget):
    avancar = pyqtSignal()
    voltar = pyqtSignal()

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)

        lay.addWidget(QLabel("<b>Descrição da tarefa</b>"))
        self.desc = QTextEdit()
        self.desc.setPlaceholderText("Somente uma ação")
        self.desc.textChanged.connect(self._upd)
        lay.addWidget(self.desc, 1)

        lay.addWidget(QLabel("<b>Tipo de Tarefa</b>"))
        self.tipo = QComboBox()
        self.tipo.addItems(["Corretiva", "Inspeção"])
        lay.addWidget(self.tipo)

        lay.addWidget(QLabel("<b>Etiqueta</b> <span style='color:#8a90a2'>(opcional)</span>"))
        self.etiq = QLineEdit()
        self.etiq.setPlaceholderText("Etiqueta da OS — opcional")
        lay.addWidget(self.etiq)

        row = QHBoxLayout()
        b_back = QPushButton("‹‹‹ Voltar")
        b_back.setObjectName("secondary")
        b_back.clicked.connect(self.voltar.emit)
        self.btn = QPushButton("Próximo ›››")
        self.btn.clicked.connect(self._next)
        row.addWidget(b_back)
        row.addWidget(self.btn, 1)
        lay.addLayout(row)
        self._upd()

    def _upd(self):
        self.btn.setEnabled(bool(self.desc.toPlainText().strip()))

    def _next(self):
        if self.desc.toPlainText().strip():
            self.avancar.emit()

    # ── getters ──
    def descricao(self):
        return self.desc.toPlainText().strip()

    def tipo_tarefa(self):
        return self.tipo.currentText()

    def etiqueta(self):
        return self.etiq.text().strip()
