"""Filtro global anti-scroll acidental: a roda do mouse NÃO muda mais o valor de QComboBox /
QDateTimeEdit / QDateEdit / QSpinBox (QAbstractSpinBox). Rolando a página com o cursor por cima de um
desses campos, o scroll é repassado para a área rolável (tabela/scroll) em vez de trocar o campo.
Evita, por ex., mudar o Plano de tarefa ou a Data sem querer e abrir uma OS errada.
(O dropdown aberto continua rolando normal — o popup é outro widget.)"""
from PyQt6.QtCore import QObject, QEvent, QPointF
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QComboBox, QAbstractSpinBox, QAbstractScrollArea, QApplication


class WheelGuard(QObject):
    _ALVOS = (QComboBox, QAbstractSpinBox)   # QDateTimeEdit/QDateEdit/QSpinBox herdam QAbstractSpinBox

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Wheel and isinstance(obj, self._ALVOS):
            try:
                area = self._scroll_ancestor(obj)
                if area is not None:                     # repassa o scroll p/ a área rolável
                    self._reenviar(area.viewport(), obj, ev)
            except Exception:
                pass
            return True                                  # bloqueia a mudança no campo
        return False

    @staticmethod
    def _scroll_ancestor(w):
        p = w.parentWidget()
        while p is not None:
            if isinstance(p, QAbstractScrollArea):
                return p
            p = p.parentWidget()
        return None

    @staticmethod
    def _reenviar(viewport, origem, ev):
        pos = viewport.mapFromGlobal(origem.mapToGlobal(ev.position().toPoint()))
        novo = QWheelEvent(QPointF(pos), ev.globalPosition(), ev.pixelDelta(), ev.angleDelta(),
                           ev.buttons(), ev.modifiers(), ev.phase(), ev.inverted(), ev.source())
        QApplication.sendEvent(viewport, novo)


_guard = None


def instalar(app):
    """Instala o filtro global uma vez (chamar no boot, após criar o QApplication)."""
    global _guard
    if _guard is None:
        _guard = WheelGuard()
        app.installEventFilter(_guard)
    return _guard
