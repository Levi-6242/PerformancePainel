"""Step 3 — Sub tarefas (mínimo 1). Cada uma só mostra a Descrição.
Campos fixos invisíveis (tratados no api.py): Ordem sequencial, Tipo=Texto,
Grupo=Diagnóstico Inicial, Obrigatório=Sim."""
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QScrollArea, QFrame)
from steps.ui import Card, rotulo


class Step3(QWidget):
    concluir = pyqtSignal()
    voltar = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._rows = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 12, 18, 12)
        lay.setSpacing(12)

        self.cont = QWidget(); self.cont.setObjectName("uiGroup")
        self.cont_lay = QVBoxLayout(self.cont)
        self.cont_lay.setContentsMargins(0, 0, 0, 0)
        self.cont_lay.setSpacing(6)
        self.cont_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea(); scroll.setObjectName("uiFlat")
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.cont)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        b_add = QPushButton("+ Adicionar subtarefa")
        b_add.setObjectName("secondary")
        b_add.clicked.connect(lambda: self._add_row())

        card = Card("list", "Subtarefas")
        card.add(rotulo("Passos", obrig=True, extra="(mínimo 1)"))
        card.add(scroll, stretch=1)
        card.add(b_add)
        lay.addWidget(card, 1)

        row = QHBoxLayout()
        b_back = QPushButton("‹‹‹ Voltar")
        b_back.setObjectName("secondary")
        b_back.clicked.connect(self.voltar.emit)
        self.btn = QPushButton("Concluir e Gerar OS")
        self.btn.clicked.connect(self._done)
        row.addWidget(b_back)
        row.addWidget(self.btn, 1)
        lay.addLayout(row)

        self._add_row()       # começa com 1

    def _add_row(self, text=""):
        line = QLineEdit()
        line.setPlaceholderText(f"Descrição da sub tarefa {len(self._rows) + 1}")
        line.setText(text)
        line.textChanged.connect(self._upd)
        roww = QFrame()
        rl = QHBoxLayout(roww)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(line, 1)
        rm = QPushButton("✕")
        rm.setObjectName("secondary")
        rm.setFixedWidth(34)
        rm.clicked.connect(lambda: self._remove(line))
        rl.addWidget(rm)
        self.cont_lay.addWidget(roww)
        self._rows.append((roww, line))
        self._renum()
        self._upd()

    def _remove(self, line):
        if len(self._rows) <= 1:        # mantém o mínimo de 1
            return
        for w, l in list(self._rows):
            if l is line:
                self._rows.remove((w, l))
                w.setParent(None)
                break
        self._renum()
        self._upd()

    def _renum(self):
        for i, (_, l) in enumerate(self._rows):
            l.setPlaceholderText(f"Descrição da sub tarefa {i + 1}")

    def _upd(self):
        self.btn.setEnabled(any(l.text().strip() for _, l in self._rows))

    def _done(self):
        if any(l.text().strip() for _, l in self._rows):
            self.concluir.emit()

    # ── getter / reset ──
    def subtarefas(self):
        return [l.text().strip() for _, l in self._rows if l.text().strip()]

    def reset(self):
        for w, _ in list(self._rows):
            w.setParent(None)
        self._rows = []
        self._add_row()
