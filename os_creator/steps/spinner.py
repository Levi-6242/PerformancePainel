"""Spinner — pequeno círculo giratório (verde-grid) p/ indicar que os dados estão carregando.

Uso: s = Spinner(parent); s.start() ao começar a carregar; s.stop() quando chegar (ou der erro).
Esconde-se sozinho quando parado.
"""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QPen, QColor
from PyQt6.QtWidgets import QWidget


class Spinner(QWidget):
    def __init__(self, parent=None, diametro=18, espessura=3, cor="#98c838"):
        super().__init__(parent)
        self._ang = 0
        self._esp = espessura
        self._cor = QColor(cor)
        self.setFixedSize(diametro, diametro)
        self.setStyleSheet("background:transparent;")
        self.setToolTip("Carregando…")
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def _tick(self):
        self._ang = (self._ang + 30) % 360
        self.update()

    def start(self):
        if not self._timer.isActive():
            self._timer.start(70)
        self.show()

    def stop(self):
        self._timer.stop()
        self.hide()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = self._esp
        rect = self.rect().adjusted(m, m, -m, -m)
        pen = QPen(self._cor, self._esp)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, -self._ang * 16, 300 * 16)        # arco de 300° girando
