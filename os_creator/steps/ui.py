"""Componentes de UI reutilizáveis do redesign (compacto, tema dark GridCo): Card de seção com badge
numerado, FormGroup (rótulo acima + "*" verde), Linha responsiva (2 col → 1), Dica, ícones Lucide (SVG)
e a folha `QSS_FORM` (escopo por subárvore — sobrepõe o DARK_QSS global só nas telas que a aplicam).
NÃO mexe em lógica/validações/API — é só apresentação."""
from PyQt6.QtCore import Qt, QByteArray, QSize, QRectF
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QPen
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

# checkmark (navy sobre verde) p/ o ::indicator:checked — gerado em disco (QSS só aceita url de arquivo)
import os as _os, tempfile as _tf
_CHK_URL = ""
try:
    _chk = _os.path.join(_tf.gettempdir(), "criaros_check.svg")
    with open(_chk, "w", encoding="utf-8") as _f:
        _f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="%s" '
                 'stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round">'
                 '<path d="M20 6 9 17l-5-5"/></svg>' % GREEN_INK)
    _CHK_URL = _chk.replace("\\", "/")
except Exception:
    _CHK_URL = ""

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
QFrame#uiBar {{ background:rgba(18,26,43,0.55); border:1px solid {BORDER}; border-radius:14px; }}
QFrame#uiVDiv {{ background:{BORDER}; border:none; }}
QLabel#uiInfoChip {{ background:rgba(166,226,46,0.12); border:1px solid rgba(166,226,46,0.25); border-radius:9px; }}
QTableWidget QComboBox, QTableWidget QDateTimeEdit, QTableWidget QLineEdit {{ min-height:30px; max-height:32px;
  border-radius:7px; padding:0 8px; }}
QFrame#uiPrefixBox {{ background:{INPUT}; border:1px solid {BORDER}; border-radius:10px; }}
QLabel#uiPrefixChip {{ background:rgba(166,226,46,0.16); color:{GREEN}; border-radius:7px;
  padding:3px 9px; font-size:12px; font-weight:700; }}
QLineEdit#uiFlatInput, QLineEdit#uiFlatInput:focus {{ background:transparent; border:none; min-height:34px;
  max-height:36px; padding:0 2px; }}
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
QCheckBox::indicator:checked, QListView::indicator:checked,
QTreeView::indicator:checked, QTableView::indicator:checked {{ background:{GREEN}; border:2px solid {GREEN};
  image: url("{_CHK_URL}"); }}
QRadioButton::indicator:checked {{ background:{GREEN}; border:2px solid {GREEN_INK}; }}
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
    "sliders": '<path d="M20 7h-9"/><path d="M14 17H5"/><circle cx="17" cy="17" r="3"/><circle cx="7" cy="7" r="3"/>',
    "info":   '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "activity": '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    "scan":   '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/><path d="m9 12 2 2 4-4"/>',
    "searchcheck": '<path d="m8 11 2 2 4-4"/><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>',
    "zap":    '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
    "image":  '<rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
    "trash":  '<path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m2 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>',
    "arrow":  '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
    "chevron":'<path d="m9 6 6 6-6 6"/>',
    "check":  '<path d="M20 6 9 17l-5-5"/>',
    "user":   '<circle cx="12" cy="8" r="3.4"/><path d="M5 20a7 7 0 0 1 14 0"/>',
    "userplus":'<path d="M16 20v-1a4 4 0 0 0-8 0v1"/><circle cx="12" cy="8" r="3.4"/><path d="M20 8v4M18 10h4"/>',
    "camera": '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="3.2"/>',
    "monitor":'<rect x="2" y="4" width="20" height="13" rx="2"/><path d="M8 21h8M12 17v4"/>',
    "calcheck":'<rect x="3" y="4" width="18" height="17" rx="2"/><path d="M3 9h18M8 2v4M16 2v4M9 15l2 2 4-4"/>',
    "rack":   '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 7h8M8 11h8M8 15h5"/>',
    "close":  '<path d="M18 6 6 18M6 6l12 12"/>',
    # chamado de garantia (mesmo desenho do card "Chamados" no app.py)
    "headset":'<path d="M4 14v-2a8 8 0 0 1 16 0v2"/><rect x="3" y="13" width="4" height="7" rx="1.5"/>'
              '<rect x="17" y="13" width="4" height="7" rx="1.5"/><path d="M20 18v1a3 3 0 0 1-3 3h-3"/>',
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


class Segmentado(QWidget):
    """Controle segmentado (pill) com indicador de rádio, desenhado à mão: a opção ativa ganha caixa
    com borda verde + preenchimento suave + ponto de rádio verde (anel + centro); as demais ficam planas.
    `on_change(i)` é chamado ao clicar. Mantém o índice em `index()`/`set_index()`."""
    def __init__(self, opcoes, on_change=None, parent=None):
        super().__init__(parent)
        self._ops = list(opcoes)
        self._idx = 0
        self._on_change = on_change
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(36)

    def index(self):
        return self._idx

    def set_index(self, i, emit=True):
        if 0 <= i < len(self._ops) and i != self._idx:
            self._idx = i
            self.update()
            if emit and self._on_change:      # emit=False: ajusta o visual sem disparar o callback
                self._on_change(i)

    def _rects(self):
        n = max(1, len(self._ops))
        w = self.width() / n
        return [QRectF(i * w, 0, w, self.height()) for i in range(len(self._ops))]

    def sizeHint(self):
        fm = self.fontMetrics()
        w = sum(fm.horizontalAdvance(o) + 58 for o in self._ops) + 14
        return QSize(int(w), 36)

    def mousePressEvent(self, e):
        pt = e.position()                      # QPointF — QRectF.contains NÃO aceita QPoint no PyQt6
        for i, r in enumerate(self._rects()):
            if r.contains(pt):
                self.set_index(i)
                break
        super().mousePressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = QFont(self.font()); f.setPixelSize(12); f.setWeight(QFont.Weight.DemiBold); p.setFont(f)
        fm = p.fontMetrics()
        # trilho externo
        p.setPen(QPen(QColor(BORDER), 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 11, 11)
        for i, r in enumerate(self._rects()):
            sel = (i == self._idx)
            if sel:
                p.setPen(QPen(QColor(GREEN), 1.5)); p.setBrush(QColor(166, 226, 46, 26))
                p.drawRoundedRect(r.adjusted(4, 4, -4, -4), 8, 8)
            txt = self._ops[i]
            tw = fm.horizontalAdvance(txt)
            dot, gap = 15, 9
            cx = r.center().x() - (dot + gap + tw) / 2
            cy = r.center().y()
            dr = QRectF(cx, cy - dot / 2, dot, dot)
            if sel:
                p.setPen(QPen(QColor(GREEN), 2)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawEllipse(dr)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(GREEN)); p.drawEllipse(dr.adjusted(5, 5, -5, -5))
            else:
                p.setPen(QPen(QColor("#4a5573"), 2)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawEllipse(dr)
            p.setPen(QColor(TEXT if sel else "#c4ccdb")); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawText(QRectF(cx + dot + gap, r.top(), tw + 6, r.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, txt)
        p.end()
