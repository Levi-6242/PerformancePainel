"""CheckableComboBox — combo compacto de SELEÇÃO MÚLTIPLA (itens com checkbox).

Visualmente é um QComboBox (não-editável; o resumo é pintado no paintEvent). Ao clicar, abre um
POPUP PRÓPRIO (QFrame) com: um campo de BUSCA + uma LISTA rolável de altura limitada. Assim:
- não colapsa com o tema (o popup nativo do combo colapsava p/ altura 0);
- não vira uma janela gigante quando há muitos itens (Usina ~150) — a lista rola e dá pra filtrar;
- clicar num item alterna o check SEM fechar o popup (marca vários de uma vez); clicar fora fecha.

API: set_items(valores) repovoa preservando marcados; checked_values() devolve o conjunto;
on_change é chamado a cada mudança.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (QComboBox, QStyle, QStylePainter, QStyleOptionComboBox, QFrame,
                             QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem)


class _CheckList(QListWidget):
    """Lista onde clicar em QUALQUER parte da linha alterna o check (não só no quadradinho)."""
    def mousePressEvent(self, e):
        it = self.itemAt(e.pos())
        if it is not None and (it.flags() & Qt.ItemFlag.ItemIsUserCheckable):
            it.setCheckState(Qt.CheckState.Unchecked if it.checkState() == Qt.CheckState.Checked
                             else Qt.CheckState.Checked)
            return                                        # consome (sem toggle nativo nem seleção)
        super().mousePressEvent(e)


class _MultiPopup(QFrame):
    """Popup do CheckableComboBox: busca + lista rolável de itens marcáveis."""
    def __init__(self, combo):
        super().__init__(combo, Qt.WindowType.Popup)
        self._combo = combo
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)   # não acumula popups
        self.setObjectName("multiPopup")
        self.setStyleSheet("QFrame#multiPopup{background:#1d2130;border:1px solid #3a4150;"
                           "border-radius:6px;}")
        v = QVBoxLayout(self); v.setContentsMargins(6, 6, 6, 6); v.setSpacing(4)
        self.busca = QLineEdit(); self.busca.setPlaceholderText("filtrar…")
        self.busca.setClearButtonEnabled(True)
        v.addWidget(self.busca)
        self.lst = _CheckList()
        v.addWidget(self.lst)
        m = combo.model()
        for i in range(m.rowCount()):
            it = m.item(i)
            li = QListWidgetItem(it.text())
            li.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            li.setCheckState(it.checkState())
            self.lst.addItem(li)
        self.lst.itemChanged.connect(self._sync)
        self.busca.textChanged.connect(self._filtrar)

    def _filtrar(self, txt):
        t = txt.strip().lower()
        for i in range(self.lst.count()):
            self.lst.item(i).setHidden(bool(t) and t not in self.lst.item(i).text().lower())

    def _sync(self, li):
        self._combo.model().item(self.lst.row(li)).setCheckState(li.checkState())

    def abrir(self):
        c = self._combo
        self.setFixedWidth(max(c.width(), 220))
        vis = min(self.lst.count(), 12) or 1            # mostra até 12 itens; o resto rola
        self.lst.setFixedHeight(vis * 24 + 6)
        self.adjustSize()
        self.move(c.mapToGlobal(c.rect().bottomLeft()))
        self.show()
        self.busca.setFocus()


class CheckableComboBox(QComboBox):
    def __init__(self, placeholder="Todos", on_change=None, parent=None):
        super().__init__(parent)
        self._placeholder = placeholder
        self._on_change = on_change
        self.setModel(QStandardItemModel(self))
        self.model().itemChanged.connect(self._on_item_changed)

    def showPopup(self):
        _MultiPopup(self).abrir()

    def hidePopup(self):
        pass

    def _on_item_changed(self, *_):
        self._refresh()
        if self._on_change:
            self._on_change()

    # ── resumo desenhado no lugar do "item atual" ──
    def paintEvent(self, event):
        p = QStylePainter(self)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        opt.currentText = self._summary()
        p.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, opt)
        p.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, opt)

    def _summary(self):
        sel = self.checked_values()
        if not sel:
            return self._placeholder
        if len(sel) == 1:
            return next(iter(sel))
        return f"{len(sel)} selecionados"

    def _refresh(self):
        sel = self.checked_values()
        self.setToolTip("\n".join(sorted(sel)) if sel else "")
        self.update()

    # ── API ──
    def _add(self, texto, checked):
        it = QStandardItem(str(texto))
        it.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        it.setData(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked,
                   Qt.ItemDataRole.CheckStateRole)
        self.model().appendRow(it)

    def set_items(self, valores):
        """Repovoa preservando os itens que estavam marcados (e ainda existem)."""
        marcados = self.checked_values()
        m = self.model()
        m.blockSignals(True)
        m.clear()
        for v in valores:
            self._add(v, v in marcados)
        m.blockSignals(False)
        self._refresh()

    def checked_values(self):
        m = self.model()
        return {m.item(i).text() for i in range(m.rowCount())
                if m.item(i).checkState() == Qt.CheckState.Checked}

    def clear_checks(self):
        m = self.model()
        m.blockSignals(True)
        for i in range(m.rowCount()):
            m.item(i).setCheckState(Qt.CheckState.Unchecked)
        m.blockSignals(False)
        self._refresh()
