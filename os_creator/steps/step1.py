"""Step 1 — drill-down do Ativo: Cliente → Usina → Tipo → Ativo(s).
Seleção MÚLTIPLA por checkbox (1 OS por ativo marcado). Sem data/hora — a OS usa
hoje 00:00 (incidente) + agora (manutenção) automaticamente."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit,
                             QListWidget, QListWidgetItem, QPushButton)

TODOS_USINA = "— Selecione a usina —"
TODOS_TIPO  = "Todos os tipos"

# Só estes tipos de equipamento podem ser escolhidos (pedido do Levi).
ALLOWED_TIPOS = ["Cabine", "Estação Meteorológica", "Estrutura Trackers", "Inversor", "NCU", "RSU"]


class Step1(QWidget):
    avancar = pyqtSignal()
    recarregar = pyqtSignal()      # botão "↻" → app recarrega ativos (force)

    def __init__(self):
        super().__init__()
        self._assets = []
        self._checked = set()       # ids dos ativos marcados (persistem entre filtros)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 12, 20, 12)
        lay.setSpacing(6)

        lay.addWidget(QLabel("<b>Cliente</b>"))
        self.cb_cliente = QComboBox()
        self.cb_cliente.currentIndexChanged.connect(self._on_cliente)
        lay.addWidget(self.cb_cliente)

        lay.addWidget(QLabel("<b>Usina</b>"))
        self.cb_usina = QComboBox()
        self.cb_usina.currentIndexChanged.connect(self._on_usina)
        lay.addWidget(self.cb_usina)

        lay.addWidget(QLabel("<b>Tipo de equipamento</b>"))
        self.cb_tipo = QComboBox()
        self.cb_tipo.currentIndexChanged.connect(self._refresh_ativos)
        lay.addWidget(self.cb_tipo)

        lay.addWidget(QLabel("<b>Ativos</b> <span style='color:#8a90a2'>(marque um ou vários)</span>"))
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Refinar por código ou nome…")
        self.busca.textChanged.connect(self._refresh_ativos)
        lay.addWidget(self.busca)
        self.lista = QListWidget()
        self.lista.itemChanged.connect(self._on_check)
        self.lista.itemClicked.connect(self._toggle)
        lay.addWidget(self.lista, 1)

        self.hint = QLabel("carregando ativos…")
        self.hint.setObjectName("hint")
        lay.addWidget(self.hint)

        row = QHBoxLayout()
        self.b_reload = QPushButton("↻")
        self.b_reload.setObjectName("secondary")
        self.b_reload.setFixedWidth(40)
        self.b_reload.setToolTip("Recarregar ativos do Fracttal")
        self.b_reload.clicked.connect(self.recarregar.emit)
        self.btn = QPushButton("Próximo ›››")
        self.btn.setEnabled(False)
        self.btn.clicked.connect(self.avancar.emit)
        row.addWidget(self.b_reload)
        row.addWidget(self.btn, 1)
        lay.addLayout(row)

    # ── carga de dados ──
    def set_assets(self, assets):
        self._assets = assets or []
        clientes = sorted({a["cliente"] for a in self._assets if a["cliente"]})
        self.cb_cliente.blockSignals(True)
        self.cb_cliente.clear()
        self.cb_cliente.addItem("— Selecione o cliente —")
        self.cb_cliente.addItems(clientes)
        self.cb_cliente.blockSignals(False)
        self._on_cliente()

    def set_loading_error(self, msg):
        self.hint.setText("⚠ " + msg)

    # ── cascata ──
    def _cliente_sel(self):
        return self.cb_cliente.currentText() if self.cb_cliente.currentIndex() > 0 else None

    def _usina_sel(self):
        return self.cb_usina.currentText() if self.cb_usina.currentIndex() > 0 else None

    def _on_cliente(self):
        cli = self._cliente_sel()
        usinas = sorted({a["usina"] for a in self._assets if a["cliente"] == cli and a["usina"]}) if cli else []
        self.cb_usina.blockSignals(True)
        self.cb_usina.clear()
        self.cb_usina.addItem(TODOS_USINA)
        self.cb_usina.addItems(usinas)
        self.cb_usina.setEnabled(bool(usinas))
        self.cb_usina.blockSignals(False)
        self._on_usina()

    def _on_usina(self):
        cli, usi = self._cliente_sel(), self._usina_sel()
        tipos = sorted({a["tipo"] for a in self._assets
                        if a["cliente"] == cli and a["usina"] == usi
                        and a["tipo"] in ALLOWED_TIPOS}) if usi else []
        self.cb_tipo.blockSignals(True)
        self.cb_tipo.clear()
        self.cb_tipo.addItem(TODOS_TIPO)
        self.cb_tipo.addItems(tipos)
        self.cb_tipo.setEnabled(bool(tipos))
        self.cb_tipo.blockSignals(False)
        self._refresh_ativos()

    def _refresh_ativos(self):
        cli, usi = self._cliente_sel(), self._usina_sel()
        tipo = self.cb_tipo.currentText() if self.cb_tipo.currentIndex() > 0 else None
        txt = (self.busca.text() or "").strip().lower()
        self.lista.blockSignals(True)        # evita disparar _on_check ao popular
        self.lista.clear()
        if not usi:
            self.lista.blockSignals(False)
            self._atualiza_hint("Selecione cliente e usina para ver os ativos.")
            return
        n = 0
        for a in self._assets:
            if a["cliente"] != cli or a["usina"] != usi:
                continue
            if a["tipo"] not in ALLOWED_TIPOS:
                continue
            if tipo and a["tipo"] != tipo:
                continue
            if txt and txt not in a["label"].lower():
                continue
            it = QListWidgetItem(a["label"])
            it.setData(Qt.ItemDataRole.UserRole, a)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if a["id"] in self._checked
                             else Qt.CheckState.Unchecked)
            self.lista.addItem(it)
            n += 1
        self.lista.blockSignals(False)
        self._atualiza_hint(f"{n} ativo(s) nesta seleção")

    # ── seleção múltipla ──
    def _toggle(self, it):
        it.setCheckState(Qt.CheckState.Unchecked if it.checkState() == Qt.CheckState.Checked
                         else Qt.CheckState.Checked)

    def _on_check(self, it):
        a = it.data(Qt.ItemDataRole.UserRole)
        if not a:
            return
        if it.checkState() == Qt.CheckState.Checked:
            self._checked.add(a["id"])
        else:
            self._checked.discard(a["id"])
        self._atualiza_hint(self.hint.text().split("  ·")[0])

    def _atualiza_hint(self, base):
        n = len(self._checked)
        self.hint.setText(f"{base}  ·  {n} marcado(s)" if n else base)
        self.btn.setText(f"Próximo ({n}) ›››" if n else "Próximo ›››")
        self.btn.setEnabled(n > 0)

    # ── getter / reset p/ o app ──
    def selected_assets(self):
        return [a for a in self._assets if a["id"] in self._checked]

    def reset(self):
        self._checked.clear()
        self.busca.blockSignals(True)
        self.busca.clear()
        self.busca.blockSignals(False)
        self.cb_cliente.setCurrentIndex(0)   # dispara a cascata → reseta usina/tipo/lista
