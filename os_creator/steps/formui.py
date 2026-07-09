"""Rótulos padronizados dos formulários de criação (estilo da tela 'Criar Solicitação'): cabeçalho de
SEÇÃO em verde maiúsculo com linha divisória + RÓTULO de campo com '*' verde nos obrigatórios.
Usar em Criar OS, COS, PCM, Clonar… p/ manter TODAS as telas com o mesmo estilo de preenchimento."""
from PyQt6.QtWidgets import QLabel, QWidget, QVBoxLayout, QFrame

VERDE = "#98c838"
MUTED = "#8a90a2"
LINHA = "#2c3142"


def _divisor() -> QFrame:
    f = QFrame(); f.setFixedHeight(1); f.setStyleSheet(f"background:{LINHA}; border:none;")
    return f


def secao(texto: str) -> QWidget:
    """Cabeçalho de seção: verde, maiúsculo, pequeno + linha divisória (igual à Criar Solicitação)."""
    w = QWidget()
    v = QVBoxLayout(w); v.setContentsMargins(0, 6, 0, 2); v.setSpacing(3)
    v.addWidget(QLabel(f"<b style='color:{VERDE};font-size:12px;letter-spacing:.3px'>{texto.upper()}</b>"))
    v.addWidget(_divisor())
    return w


def rotulo(texto: str, obrig: bool = False, extra: str = "") -> QLabel:
    """Rótulo de campo (acima do campo). `obrig` → '*' verde; `extra` → dica em cinza."""
    s = f"<b>{texto}</b>"
    if obrig:
        s += f" <span style='color:{VERDE}'>*</span>"
    if extra:
        s += f" <span style='color:{MUTED}'>{extra}</span>"
    return QLabel(s)
