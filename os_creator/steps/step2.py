"""Step 2 — Detalhes da tarefa: descrição + tipo (Corretiva/Inspeção) + etiquetas (catálogo
do Fracttal, multi-seleção). Campos fixos invisíveis: criticidade Alta."""
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QComboBox,
                             QLineEdit, QPushButton, QListWidget, QListWidgetItem, QScrollArea)
from steps.tipo_tarefa import TipoTarefaBox
from steps.ui import Card, campo, icone_pix, MUTED


class Step2(QWidget):
    avancar = pyqtSignal()
    voltar = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._labels = []           # catálogo [{'id','description','color'}]
        self._checked = set()       # ids marcados (persistem ao filtrar)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(); lay = QVBoxLayout(body)
        lay.setContentsMargins(18, 12, 18, 6); lay.setSpacing(12)
        scroll.setWidget(body); outer.addWidget(scroll, 1)

        self.desc = QTextEdit(); self.desc.setPlaceholderText("Somente uma ação")
        self.desc.setFixedHeight(60); self.desc.textChanged.connect(self._upd)
        self.obs = QTextEdit(); self.obs.setPlaceholderText("Observações da OS (opcional)")
        self.obs.setFixedHeight(60)
        self.etiq_busca = QLineEdit(); self.etiq_busca.setPlaceholderText("carregando etiquetas…")
        self.etiq_busca.addAction(QIcon(icone_pix("search", MUTED, 15)), QLineEdit.ActionPosition.LeadingPosition)
        self.etiq_busca.textChanged.connect(self._filtrar_etiq)
        self.etiq = QListWidget(); self.etiq.setMinimumHeight(120)
        self.etiq.itemChanged.connect(self._on_check)

        c1 = Card("file", "Detalhes da OS")
        c1.add(campo("Descrição da tarefa", self.desc, obrig=True))
        c1.add(campo("Observação", self.obs, extra="(opcional)"))
        c1.add(campo("Etiquetas", self.etiq_busca, extra="(opcional — marque as que quiser)"))
        c1.add(self.etiq)
        lay.addWidget(c1)

        self._tt = TipoTarefaBox()                 # tipo de tarefa + classif 1/2 + criticidade (ao vivo)
        c2 = Card("tag", "Classificação")
        c2.add(self._tt.grid)
        lay.addWidget(c2)
        lay.addStretch(1)

        row = QHBoxLayout(); row.setContentsMargins(18, 6, 18, 10)
        b_back = QPushButton("‹‹‹ Voltar")
        b_back.setObjectName("secondary")
        b_back.clicked.connect(self.voltar.emit)
        self.btn = QPushButton("Próximo ›››")
        self.btn.clicked.connect(self._next)
        row.addWidget(b_back)
        row.addWidget(self.btn, 1)
        outer.addLayout(row)
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
