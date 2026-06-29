"""Step 2 — Detalhes da tarefa: descrição + tipo (Corretiva/Inspeção) + etiquetas (catálogo
do Fracttal, multi-seleção). Campos fixos invisíveis: criticidade Alta."""
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
                             QComboBox, QLineEdit, QPushButton, QListWidget, QListWidgetItem)
from steps.tipo_tarefa import TipoTarefaBox


class Step2(QWidget):
    avancar = pyqtSignal()
    voltar = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._labels = []           # catálogo [{'id','description','color'}]
        self._checked = set()       # ids marcados (persistem ao filtrar)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)

        lay.addWidget(QLabel("<b>Descrição da tarefa</b>"))
        self.desc = QTextEdit()
        self.desc.setPlaceholderText("Somente uma ação")
        self.desc.textChanged.connect(self._upd)
        lay.addWidget(self.desc, 1)

        lay.addWidget(QLabel("<b>Observação</b> <span style='color:#8a90a2'>(opcional)</span>"))
        self.obs = QTextEdit()
        self.obs.setPlaceholderText("Observações da OS (opcional)")
        self.obs.setFixedHeight(72)
        lay.addWidget(self.obs)

        self._tt = TipoTarefaBox()                 # tipo de tarefa + classif 1/2 + criticidade (ao vivo)
        lay.addLayout(self._tt.grid)

        lay.addWidget(QLabel("<b>Etiquetas</b> <span style='color:#8a90a2'>(opcional — marque as que quiser)</span>"))
        self.etiq_busca = QLineEdit()
        self.etiq_busca.setPlaceholderText("carregando etiquetas…")
        self.etiq_busca.textChanged.connect(self._filtrar_etiq)
        lay.addWidget(self.etiq_busca)
        self.etiq = QListWidget()
        self.etiq.setFixedHeight(130)
        self.etiq.itemChanged.connect(self._on_check)
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

    # ── etiquetas ──
    def set_labels(self, labels):
        self._labels = labels or []
        self.etiq_busca.setPlaceholderText("Filtrar etiquetas…" if self._labels
                                           else "⚠ etiquetas não carregaram")
        self._filtrar_etiq("")

    def _on_check(self, it):
        lid = it.data(Qt.ItemDataRole.UserRole)
        if it.checkState() == Qt.CheckState.Checked:
            self._checked.add(lid)
        else:
            self._checked.discard(lid)

    def _filtrar_etiq(self, txt):
        txt = (txt or "").strip().lower()
        self.etiq.blockSignals(True)        # evita _on_check durante o rebuild
        self.etiq.clear()
        for l in self._labels:
            d = l.get("description") or ""
            if not txt or txt in d.lower():
                it = QListWidgetItem(d)
                it.setData(Qt.ItemDataRole.UserRole, l.get("id"))
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Checked if l.get("id") in self._checked
                                 else Qt.CheckState.Unchecked)
                self.etiq.addItem(it)
        self.etiq.blockSignals(False)

    def _upd(self):
        self.btn.setEnabled(bool(self.desc.toPlainText().strip()))

    def _next(self):
        if self.desc.toPlainText().strip():
            self.avancar.emit()

    def reset(self):
        self.desc.clear()
        self.obs.clear()
        self._tt.reset()
        self._checked.clear()
        self.etiq_busca.clear()
        self._filtrar_etiq("")

    def prefill(self, descricao, tipo_nome="Corretiva"):
        """Pré-preenche descrição + tipo de tarefa (vindo da fila de sugestões de OS)."""
        self.desc.setPlainText(descricao or "")
        if tipo_nome:
            self._tt.selecionar(tipo_nome)
        self._upd()

    # ── getters ──
    def descricao(self):
        return self.desc.toPlainText().strip()

    def observacao(self):
        return self.obs.toPlainText().strip()

    def tipo_tarefa(self):
        return self._tt.descricao_tipo()

    def tipo_dict(self):
        return self._tt.tipo_dict()

    def tipo_ready(self):
        return self._tt.is_ready()

    def etiqueta_ids(self):
        return list(self._checked)

    def etiqueta(self):
        """Compat: nomes das etiquetas marcadas (para exibição)."""
        nomes = [l.get("description") for l in self._labels if l.get("id") in self._checked]
        return ", ".join(n for n in nomes if n)
