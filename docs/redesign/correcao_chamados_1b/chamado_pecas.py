"""Peças PINTADAS do design 'Chamados 1B'.

POR QUE ESTE ARQUIVO EXISTE
---------------------------
Regra do projeto:

    caixa (card, botão, input)  ->  QSS
    marca (ponto, régua, barra) ->  paintEvent

Fazer marca com QSS falhou de três jeitos neste porte:

  1. `border-radius: 3.5px`  — o parser de QSS do Qt **recusa comprimento
     fracionário** e descarta a declaração inteira. Era por isso que TODOS os
     pontos das duas telas saíam quadrados: `f"{tam/2:.1f}px"` gera "3.5px".
  2. `background: rgba(...)` vindo da folha não compõe dentro de pai
     transparente — e as colunas do board e a lateral do detalhe são todas
     transparentes. O trilho e as divisórias simplesmente não existiam.
  3. `box-shadow` não existe em QSS, então o glow dos pontos sumiu.

O QPainter resolve os três: compõe sobre qualquer pai, aceita float, e o glow
é um QRadialGradient.
"""
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QPainter, QColor, QRadialGradient, QLinearGradient, QBrush
from PyQt6.QtWidgets import QWidget, QSizePolicy


def _cor(c, a=1.0):
    q = QColor(c)
    if a < 1.0:
        q.setAlphaF(max(0.0, min(1.0, a)))
    return q


class Ponto(QWidget):
    """O ponto de status — o único 'ícone' do design (README §3.7).

    `glow=True` reproduz o `box-shadow: 0 0 9px rgba(cor,.65)` do HTML.

    ATENÇÃO AO LAYOUT: a caixa cresce BLEED px de cada lado para caber o halo.
    O centro óptico NÃO se move — só a caixa. Onde o espaçamento importa,
    desconte:  layout.setSpacing(9 - Ponto.BLEED)
    """
    BLEED = 4

    def __init__(self, cor, tam=7, glow=True, parent=None):
        super().__init__(parent)
        self._c = cor
        self._tam = float(tam)
        self._glow = bool(glow)
        lado = int(round(self._tam)) + 2 * self.BLEED
        self.setFixedSize(lado, lado)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def cor(self):
        return self._c

    def setCor(self, cor):
        """Trocar a cor sem recriar o widget (o detalhe repinta a cada _render)."""
        if cor != self._c:
            self._c = cor
            self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        r = self._tam / 2.0
        if self._glow:
            raio = r + self.BLEED
            g = QRadialGradient(QPointF(cx, cy), raio)
            g.setColorAt(0.0, _cor(self._c, 0.50))
            g.setColorAt(r / raio, _cor(self._c, 0.30))
            g.setColorAt(1.0, _cor(self._c, 0.0))
            p.setBrush(QBrush(g))
            p.drawEllipse(QPointF(cx, cy), raio, raio)
        p.setBrush(_cor(self._c))
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.end()


class Regua(QWidget):
    """Régua de 1px. `esmaece=True` reproduz o fade-to-transparent do HTML
    (a divisória do card some para a direita)."""

    def __init__(self, cor="#FFFFFF", alpha=0.10, esmaece=False, parent=None):
        super().__init__(parent)
        self._c, self._a, self._fade = cor, alpha, bool(esmaece)
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, _ev):
        p = QPainter(self)
        r = QRectF(0, 0, self.width(), 1)
        if self._fade:
            g = QLinearGradient(0, 0, self.width(), 0)
            g.setColorAt(0.0, _cor(self._c, self._a))
            g.setColorAt(1.0, _cor(self._c, 0.0))
            p.fillRect(r, QBrush(g))
        else:
            p.fillRect(r, _cor(self._c, self._a))
        p.end()


class Trilho(QWidget):
    """Linha vertical de 1px da timeline. CONTÍNUA: some o fio, some a leitura
    vertical do histórico. `fim=True` para na altura do último ponto."""

    def __init__(self, cor="#FFFFFF", alpha=0.10, fim=False, parada=0, parent=None):
        super().__init__(parent)
        self._c, self._a, self._fim, self._parada = cor, alpha, bool(fim), parada
        self.setFixedWidth(1)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

    def paintEvent(self, _ev):
        p = QPainter(self)
        h = self._parada if (self._fim and self._parada) else self.height()
        p.fillRect(QRectF(0, 0, 1, h), _cor(self._c, self._a))
        p.end()


class BarraTempo(QWidget):
    """Barra do tempo parado — 26x3, gradiente da cor a 20% até a cor cheia,
    como no HTML."""

    def __init__(self, cor, largura=26, altura=3, parent=None):
        super().__init__(parent)
        self._c = cor
        self.setFixedSize(largura, altura)

    def setCor(self, cor):
        if cor != self._c:
            self._c = cor
            self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        g = QLinearGradient(0, 0, self.width(), 0)
        g.setColorAt(0.0, _cor(self._c, 0.20))
        g.setColorAt(1.0, _cor(self._c, 1.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()),
                          self.height() / 2.0, self.height() / 2.0)
        p.end()
