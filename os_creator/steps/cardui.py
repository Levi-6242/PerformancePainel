"""Componentes visuais compartilhados dos cards de detalhe (OS e Solicitação): selo de status,
rótulo apagado, linha divisória e bloco de seção rotulada. Mantém o MESMO estilo entre as telas."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QWidget, QVBoxLayout, QFrame

MUTED = "#8a90a2"
LINE = "#2c3142"
BLOCO = "background:#1d2130; border:1px solid #2c3142; border-radius:8px; padding:10px 12px;"

# cores de selo por status (mesmas da tabela de histórico de solicitações)
STATUS_COR = {
    "Aberta":            ("#fef3c7", "#92400e"),
    "Aprovada":          ("#dbeafe", "#1d4ed8"),
    "OS em processo":    ("#dbeafe", "#1d4ed8"),
    "OS em verificação": ("#e0e7ff", "#4338ca"),
    "Concluída":         ("#dcfce7", "#166534"),
    "OS concluída":      ("#dcfce7", "#166534"),
    "Cancelada":         ("#fee2e2", "#b91c1c"),
    "Rejeitada":         ("#fee2e2", "#b91c1c"),
}
_NEUTRO = ("#e5e7eb", "#374151")


def badge(texto, cores=None):
    """Selo (pílula). `cores`=(bg,fg); sem cores usa STATUS_COR ou um neutro (p/ tipo etc.)."""
    bg, fg = cores or STATUS_COR.get(texto, _NEUTRO)
    lb = QLabel(texto)
    lb.setStyleSheet(f"background:{bg}; color:{fg}; border-radius:10px; padding:2px 12px; "
                     "font-size:11px; font-weight:600;")
    return lb


def rotulo(texto, largura=88):
    l = QLabel(texto); l.setStyleSheet(f"color:{MUTED};"); l.setMinimumWidth(largura)
    return l


def hline():
    f = QFrame(); f.setFixedHeight(1); f.setStyleSheet(f"background:{LINE};")
    return f


def secao(titulo, texto, cor_texto=None):
    """Bloco rotulado (TÍTULO/NOTAS/OBSERVAÇÃO…). Devolve (widget, label_do_corpo) — o label é
    devolvido p/ quem precisa atualizar o texto depois."""
    w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(5)
    cab = QLabel(titulo)
    cab.setStyleSheet(f"color:{MUTED}; font-size:11px; font-weight:600; letter-spacing:0.4px;")
    v.addWidget(cab)
    blk = QLabel(str(texto)); blk.setWordWrap(True)
    blk.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    blk.setStyleSheet(BLOCO + (f" color:{cor_texto};" if cor_texto else ""))
    v.addWidget(blk)
    return w, blk
