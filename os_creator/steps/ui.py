"""Componentes de UI reutilizáveis do redesign (compacto, tema dark GridCo): Card de seção com badge
numerado, FormGroup (rótulo acima + "*" verde), Linha responsiva (2 col → 1), Dica, ícones Lucide (SVG)
e a folha `QSS_FORM` (escopo por subárvore — sobrepõe o DARK_QSS global só nas telas que a aplicam).
NÃO mexe em lógica/validações/API — é só apresentação."""
from PyQt6.QtCore import Qt, QByteArray, QSize
from PyQt6.QtGui import QPixmap, QPainter, QColor
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QGraphicsDropShadowEffect, QLayout)

# ── paleta (brief do Levi) ──
BG        = "#0B1020"
CARD      = "#121A2B"
INPUT     = "#1A2337"
BORDER    = "#2A3550"
GREEN     = "#A6E22E"
GREEN_INK = "#0B1020"
TEXT      = "#FFFFFF"
MUTED     = "#8A93A8"

# ── folha de estilo (aplicar no root da tela: `w.setStyleSheet(QSS_FORM)`) ──
# padding VERTICAL explícito 0 → anula o `padding:7px 9px` do DARK_QSS global (senão os campos incham).
QSS_FORM = f"""
QWidget#uiGroup, QWidget#uiRow {{ background:transparent; }}
QLabel {{ background:transparent; }}
QLineEdit,QComboBox,QDateEdit,QDateTimeEdit,QAbstractSpinBox {{
  background:{INPUT}; border:1px solid {BORDER}; border-radius:10px; color:{TEXT};
  min-height:40px; max-height:40px; padding:0 12px; font-size:13px; }}
QTextEdit {{ background:{INPUT}; border:1px solid {BORDER}; border-radius:10px; color:{TEXT};
  padding:8px 12px; font-size:13px; }}
QTableWidget {{ background:{INPUT}; border:1px solid {BORDER}; border-radius:10px; gridline-color:{BORDER};
  color:{TEXT}; font-size:12px; }}
QTableWidget::item {{ padding:4px 8px; }}
QTableWidget::item:selected {{ background:rgba(166,226,46,0.14); color:#eaf3d6; }}
QHeaderView::section {{ background:{CARD}; color:{MUTED}; padding:6px 9px; border:none;
  border-bottom:1px solid {BORDER}; font-weight:600; font-size:11px; }}
QScrollArea#uiFlat, QScrollArea#uiFlat > QWidget {{ background:transparent; border:none; }}
QTableWidget QComboBox, QTableWidget QDateTimeEdit {{ min-height:30px; max-height:32px; border-radius:7px;
  padding:0 8px; }}
QLineEdit:hover,QComboBox:hover,QDateEdit:hover,QDateTimeEdit:hover,QTextEdit:hover {{ border-color:#39456a; }}
QLineEdit:focus,QComboBox:focus,QDateEdit:focus,QDateTimeEdit:focus,QTextEdit:focus,QAbstractSpinBox:focus {{
  border:1px solid {GREEN}; }}
QComboBox:editable {{ padding-left:8px; }}
QComboBox QLineEdit,QComboBox QLineEdit:focus {{ background:transparent; border:none; min-height:0;
  max-height:none; padding:0 6px; color:{TEXT}; }}
QComboBox::drop-down {{ border:none; width:26px; }}
QComboBox QAbstractItemView {{ background:{CARD}; color:{TEXT}; border:1px solid {BORDER}; border-radius:8px;
  selection-background-color:rgba(166,226,46,0.18); selection-color:#eaf3d6; outline:0; padding:4px; }}
QComboBox QAbstractItemView::item {{ min-height:24px; padding:4px 8px; border-radius:6px; }}
QFrame#uiCard {{ background:{CARD}; border:1px solid {BORDER}; border-radius:14px; }}
QFrame#uiCard[hover="true"] {{ border-color:#3d4a6b; }}
QLabel#uiBadge {{ background:rgba(166,226,46,0.14); color:{GREEN}; border-radius:11px;
  font-size:12px; font-weight:700; }}
QFrame#uiDiv {{ background:{BORDER}; border:none; }}
QFrame#uiDica {{ background:rgba(166,226,46,0.09); border:1px solid rgba(166,226,46,0.20); border-radius:10px; }}
QLabel#uiCardTitle {{ background:transparent; color:{TEXT}; font-size:14px; font-weight:600; }}
QLabel#uiCampoLabel {{ background:transparent; color:#cfd6e4; font-size:12px; font-weight:600; }}
QLabel#uiAjuda {{ background:transparent; color:{MUTED}; font-size:11px; }}
QLabel#uiReqnote {{ background:transparent; color:{MUTED}; font-size:12px; }}
QLabel#uiDicaTxt {{ background:transparent; color:#cdd6bf; font-size:12px; }}
QCheckBox, QRadioButton {{ background:transparent; color:#cfd6e4; font-size:13px; spacing:8px; }}
QCheckBox::indicator, QRadioButton::indicator, QListView::indicator, QTreeView::indicator, QTableView::indicator {{
  width:18px; height:18px; border:1px solid {BORDER}; border-radius:5px; background:{INPUT}; }}
QRadioButton::indicator {{ border-radius:9px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color:#39456a; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked, QListView::indicator:checked,
QTreeView::indicator:checked, QTableView::indicator:checked {{ background:{GREEN}; border:2px solid {GREEN_INK}; }}
QPushButton#btnPrimary {{ background:{GREEN}; color:{GREEN_INK}; border:none; border-radius:10px;
  min-height:42px; padding:0 20px; font-size:13px; font-weight:700; }}
QPushButton#btnPrimary:hover {{ background:#b4ec42; }}
QPushButton#btnPrimary:disabled {{ background:#2c3142; color:#6b7080; }}
QPushButton#btnGhost {{ background:transparent; color:#d4dae6; border:1px solid {BORDER}; border-radius:10px;
  min-height:42px; padding:0 16px; font-size:13px; font-weight:600; }}
QPushButton#btnGhost:hover {{ border-color:#4a597e; color:{TEXT}; }}
QPushButton#secondary {{ background:transparent; color:#cdd2e0; border:1px solid {BORDER}; border-radius:9px;
  min-height:38px; padding:0 12px; font-size:13px; font-weight:500; }}
QPushButton#secondary:hover {{ border-color:#4a597e; color:{TEXT}; }}
QPushButton#secondary:disabled {{ color:#5a6072; border-color:#232a3d; }}
"""

# ── ícones Lucide (SVG inline; Qt não tem a fonte de ícones da web) ──
_LUCIDE = {
    "send":   '<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4Z"/>',
    "x":      '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "bulb":   '<path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.8.8 1.3 1.5 1.5 2.5"/><path d="M9 18h6"/><path d="M10 22h4"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "layers": '<path d="M12 2 2 7l10 5 10-5-10-5Z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
    "box":    '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
    "file":   '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z"/><path d="M14 2v5h5"/><path d="M9 13h6"/><path d="M9 17h6"/>',
    "tag":    '<path d="M12.6 2.6A2 2 0 0 0 11.2 2H4a2 2 0 0 0-2 2v7.2a2 2 0 0 0 .6 1.4l8.7 8.7a2.4 2.4 0 0 0 3.4 0l6.6-6.6a2.4 2.4 0 0 0 0-3.4z"/><circle cx="7.5" cy="7.5" r="1.1"/>',
    "list":   '<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/>',
    "users":  '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "cal":    '<rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/><path d="M8 2v4"/><path d="M16 2v4"/>',
    "alert":  '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "copy":   '<rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16V4a2 2 0 0 1 2-2h10"/>',
    "grid":   '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
    "clock":  '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
}
_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{c}" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{p}</svg>')


def icone_pix(nome: str, cor: str = GREEN, size: int = 16) -> QPixmap:
    pix = QPixmap(size, size); pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    QSvgRenderer(QByteArray(_SVG.format(c=cor, p=_LUCIDE[nome]).encode("utf-8"))).render(p)
    p.end()
    return pix


class Card(QFrame):
    """Superfície de seção compacta: badge (número OU ícone Lucide) + título + divisória fina + corpo.
    Sombra suave; no hover a borda clareia. `marca` = int/str-dígito → número; str → nome de ícone.
    Use `.add(widget_ou_layout)` p/ preencher o corpo; `.extra_head(w)` p/ pôr algo à direita do título."""
    def __init__(self, marca, titulo: str):
        super().__init__()
        self.setObjectName("uiCard")
        sombra = QGraphicsDropShadowEffect(self)
        sombra.setBlurRadius(16); sombra.setXOffset(0); sombra.setYOffset(3)
        sombra.setColor(QColor(0, 0, 0, 80))
        self.setGraphicsEffect(sombra)

        v = QVBoxLayout(self); v.setContentsMargins(18, 14, 18, 16); v.setSpacing(12)
        self._head = QHBoxLayout(); self._head.setSpacing(10)
        badge = QLabel(); badge.setObjectName("uiBadge"); badge.setFixedSize(22, 22)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if isinstance(marca, int) or (isinstance(marca, str) and marca.isdigit()):
            badge.setText(str(marca))
        else:
            badge.setPixmap(icone_pix(marca, GREEN, 14))
        self._head.addWidget(badge)
        t = QLabel(titulo); t.setObjectName("uiCardTitle")
        self._head.addWidget(t); self._head.addStretch(1)
        v.addLayout(self._head)
        div = QFrame(); div.setObjectName("uiDiv"); div.setFixedHeight(1); v.addWidget(div)
        self._body = QVBoxLayout(); self._body.setSpacing(12)
        v.addLayout(self._body)

    def add(self, item, stretch=0):
        if isinstance(item, QLayout):
            self._body.addLayout(item, stretch)
        else:
            self._body.addWidget(item, stretch)

    def extra_head(self, w):
        """Coloca um widget à direita do título (ex.: botão de ação da seção)."""
        self._head.addWidget(w)

    def enterEvent(self, e):
        self.setProperty("hover", True); self._repolir(); super().enterEvent(e)

    def leaveEvent(self, e):
        self.setProperty("hover", False); self._repolir(); super().leaveEvent(e)

    def _repolir(self):
        self.style().unpolish(self); self.style().polish(self)


class Dica(QFrame):
    """Caixa de dica discreta (lâmpada verde + texto), estilo 'ajuda de preenchimento'."""
    def __init__(self, texto: str):
        super().__init__()
        self.setObjectName("uiDica")
        h = QHBoxLayout(self); h.setContentsMargins(12, 11, 12, 11); h.setSpacing(9)
        ic = QLabel(); ic.setPixmap(icone_pix("bulb", GREEN, 16)); ic.setFixedWidth(16)
        ic.setAlignment(Qt.AlignmentFlag.AlignTop)
        h.addWidget(ic)
        t = QLabel(texto); t.setObjectName("uiDicaTxt"); t.setWordWrap(True)
        h.addWidget(t, 1)


def rotulo(label: str, obrig: bool = False, extra: str = "") -> QLabel:
    """Só o rótulo de um campo (com '*' verde se obrigatório + dica cinza inline). Útil quando o campo
    precisa ESTICAR dentro do card (ex.: lista/tabela) — aí adiciona-se rótulo + widget separados."""
    txt = label
    if obrig:
        txt += f" <span style='color:{GREEN};font-weight:700'>*</span>"
    if extra:
        txt += f" <span style='color:{MUTED};font-weight:400'>{extra}</span>"
    lb = QLabel(txt); lb.setObjectName("uiCampoLabel")
    return lb


def campo(label: str, widget: QWidget, obrig: bool = False, extra: str = "", ajuda: str = "") -> QWidget:
    """FormGroup: rótulo acima (+ '*' verde se obrigatório, + dica `extra` inline) + campo + `ajuda`
    opcional embaixo."""
    w = QWidget(); w.setObjectName("uiGroup")            # fundo transparente (senão o global pinta faixa)
    v = QVBoxLayout(w); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(5)
    v.addWidget(rotulo(label, obrig, extra))
    v.addWidget(widget)
    if ajuda:
        a = QLabel(ajuda); a.setObjectName("uiAjuda"); a.setWordWrap(True); v.addWidget(a)
    return w


class Linha(QWidget):
    """Duas colunas no desktop; empilha em 1 coluna quando estreito (< quebra). `b=None` = coluna única.
    `pesos` define a proporção das colunas (ex.: (3,2) = coluna A mais larga)."""
    def __init__(self, a: QWidget, b: QWidget = None, quebra: int = 560, pesos=(1, 1)):
        super().__init__()
        self.setObjectName("uiRow")                      # fundo transparente
        self._a, self._b, self._quebra, self._pesos, self._cols = a, b, quebra, pesos, 0
        self._g = QGridLayout(self); self._g.setContentsMargins(0, 0, 0, 0)
        self._g.setHorizontalSpacing(14); self._g.setVerticalSpacing(12)
        self._montar(1 if b is None else 2)

    def _montar(self, cols):
        if cols == self._cols:
            return
        self._cols = cols
        self._g.removeWidget(self._a)
        if self._b is not None:
            self._g.removeWidget(self._b)
        self._g.addWidget(self._a, 0, 0)
        if self._b is not None:
            if cols == 2:
                self._g.addWidget(self._b, 0, 1)
            else:
                self._g.addWidget(self._b, 1, 0)
        self._g.setColumnStretch(0, self._pesos[0])
        self._g.setColumnStretch(1, self._pesos[1] if cols == 2 else 0)

    def minimumSizeHint(self):
        # largura mínima 0 → o widget PODE encolher (senão o mínimo das 2 colunas trava o reflow)
        return QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, e):
        if self._b is not None:
            self._montar(2 if self.width() >= self._quebra else 1)
        super().resizeEvent(e)
