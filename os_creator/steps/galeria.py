"""Galeria de fotos de uma OS: grade de miniaturas PRÉ-CARREGADAS (baixa as imagens em paralelo, com
limite de concorrência) e, ao clicar, visualizador em tamanho cheio (instantâneo — usa o cache do
download da miniatura), com botão Salvar. Janela maximizável; as colunas se ajustam à largura."""
import base64
import os
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap, QIcon
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
                             QScrollArea, QWidget, QFileDialog, QMessageBox, QSizePolicy)
import api
from workers import ApiWorker, slot_seguro

_MAX_CONC = 5                       # downloads simultâneos de miniatura
_THUMB = QSize(273, 205)            # miniatura (30% maior que o original 210×158)
_STEP = _THUMB.width() + 22         # largura de uma célula (p/ calcular colunas)


def _b64_bytes(b64):
    if not b64:
        return None
    try:
        if "," in b64 and "base64" in b64.split(",", 1)[0]:
            b64 = b64.split(",", 1)[1]
        return base64.b64decode(b64)
    except Exception:
        return None


def _pix(data):
    if not data:
        return None
    pix = QPixmap()
    return pix if pix.loadFromData(bytes(data)) else None


def abrir_galeria(parent, imagens, ativo_os=""):
    """Abre a galeria de fotos da OS (lista de {url, thumb, descricao, ativo}). `ativo_os` = nome do
    ativo da OS, usado como fallback quando a foto não traz o ativo próprio."""
    GaleriaDialog(parent, imagens, ativo_os).exec()


class GaleriaDialog(QDialog):
    def __init__(self, parent, imagens, ativo_os=""):
        super().__init__(parent)
        self._imgs = imagens or []
        self._ativo_os = (ativo_os or "").strip()
        self._cache = {}                # url -> bytes (full)
        self._workers = {}              # idx -> ApiWorker
        self._queue = list(range(len(self._imgs)))
        self._cells = []                # idx -> {'w','btn','done'}
        self._cols = 0
        self.setWindowTitle(f"Fotos da OS ({len(self._imgs)})")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint
                            | Qt.WindowType.WindowMinMaxButtonsHint)
        self.setMinimumSize(720, 560)
        self.setSizeGripEnabled(True)
        lay = QVBoxLayout(self); lay.setContentsMargins(12, 12, 12, 12)
        self.hint = QLabel("carregando miniaturas…"); self.hint.setObjectName("hint")
        lay.addWidget(self.hint)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._box = QWidget(); self.grid = QGridLayout(self._box)
        self.grid.setSpacing(10); self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll.setWidget(self._box); lay.addWidget(scroll, 1)

        for i, img in enumerate(self._imgs):
            self._cells.append(self._make_cell(img, i))
        if not self._imgs:
            self.hint.setText("Nenhuma foto nesta OS.")
        self._relayout(force=True)
        for _ in range(min(_MAX_CONC, len(self._queue))):   # dispara os 1ºs downloads
            self._next()
        self._upd_hint()

    def _rotulo(self, idx):
        """Rótulo da foto no formato 'Ativo — Tarefa' (cai p/ um só quando falta o outro)."""
        img = self._imgs[idx] if 0 <= idx < len(self._imgs) else {}
        tarefa = (img.get("descricao") or "").strip() or f"Foto {idx + 1}"
        ativo = (img.get("ativo") or self._ativo_os or "").strip()
        return f"{ativo} — {tarefa}" if ativo else tarefa

    # ── grade ──
    def _make_cell(self, img, idx):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(4)
        nome = self._rotulo(idx)                                 # 'Ativo — Tarefa' ACIMA do card
        cap = QLabel(nome); cap.setObjectName("hint")
        cap.setWordWrap(True); cap.setFixedWidth(_THUMB.width() + 6); cap.setFixedHeight(36)
        cap.setToolTip(nome)
        btn = QPushButton(f"foto {idx + 1}\n(carregando…)"); btn.setObjectName("secondary")
        btn.setFixedSize(_THUMB.width() + 6, _THUMB.height() + 6)
        btn.setToolTip(nome)
        btn.clicked.connect(lambda _=False, i=idx: self._abrir(i))
        v.addWidget(cap); v.addWidget(btn)
        return {"w": w, "btn": btn, "done": False}

    def _relayout(self, force=False):
        cols = max(1, (self.width() - 36) // _STEP)
        if cols == self._cols and not force:
            return
        self._cols = cols
        while self.grid.count():
            self.grid.takeAt(0)
        for i, cell in enumerate(self._cells):
            self.grid.addWidget(cell["w"], i // cols, i % cols)

    @slot_seguro
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout()

    # ── downloads em paralelo (limitados) ──
    @slot_seguro
    def _next(self):
        if not self._queue:
            return
        idx = self._queue.pop(0)
        img = self._imgs[idx]
        thumb = _b64_bytes(img.get("thumb"))
        if thumb:                                   # já veio base64 → usa direto
            self._apply(idx, thumb, cache=False)
            self._next(); return
        url = img.get("url")
        if not url:
            self._fail(idx); self._next(); return
        w = ApiWorker(api.baixar_imagem, url)
        self._workers[idx] = w
        w.ok.connect(lambda data, i=idx: self._got(i, data))
        w.erro.connect(lambda _m, i=idx: self._got(i, None))
        w.start()

    @slot_seguro
    def _got(self, idx, data):
        self._workers.pop(idx, None)
        if isinstance(data, (bytes, bytearray)):
            self._apply(idx, bytes(data), cache=True)
        else:
            self._fail(idx)
        self._next()
        self._upd_hint()

    def _apply(self, idx, data, cache):
        cell = self._cells[idx]
        pix = _pix(data)
        if pix:
            if cache:
                self._cache[self._imgs[idx].get("url")] = data
            cell["btn"].setIcon(QIcon(pix))
            cell["btn"].setIconSize(_THUMB)
            cell["btn"].setText("")
            cell["done"] = True
        else:
            self._fail(idx)

    def _fail(self, idx):
        self._cells[idx]["btn"].setText(f"foto {idx + 1}\n(toque p/ baixar)")
        self._cells[idx]["done"] = True

    def _upd_hint(self):
        feito = sum(1 for c in self._cells if c["done"])
        tot = len(self._cells)
        if not tot:
            return
        self.hint.setText("Clique numa foto para ver em tamanho cheio e salvar." if feito >= tot
                          else f"carregando miniaturas… ({feito}/{tot})")

    @slot_seguro
    def _abrir(self, idx):
        ImagemViewer(self, idx).exec()


class _ImagemLabel(QLabel):
    """QLabel que mantém a imagem SEMPRE ajustada ao seu tamanho (proporção preservada, sem ampliar
    além do nativo). Reescala sozinho no resize — a imagem se adapta à janela/tela."""
    def __init__(self, texto=""):
        super().__init__(texto)
        self._orig = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(1, 1)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    def set_imagem(self, pix):
        self._orig = pix
        self._aplicar()

    def mostrar_texto(self, texto):
        self._orig = None
        self.setText(texto)

    @slot_seguro
    def _aplicar(self):
        if self._orig is None:
            return
        area = self.size()
        w = min(self._orig.width(), max(1, area.width()))
        h = min(self._orig.height(), max(1, area.height()))
        super().setPixmap(self._orig.scaled(QSize(w, h), Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))

    @slot_seguro
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._aplicar()


class ImagemViewer(QDialog):
    """Visualiza uma foto da OS ajustada à janela, com o nome da tarefa abaixo e navegação
    ‹ Anterior / Próxima › (setas do teclado também). Reaproveita o cache de bytes da galeria."""
    def __init__(self, galeria, idx):
        super().__init__(galeria)
        self._galeria = galeria
        self._imgs = galeria._imgs
        self._idx = idx
        self._bytes = None
        self._w = None
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint
                            | Qt.WindowType.WindowMinMaxButtonsHint)
        self.setMinimumSize(640, 520)
        self.setSizeGripEnabled(True)
        lay = QVBoxLayout(self); lay.setContentsMargins(8, 8, 8, 8); lay.setSpacing(6)

        self.lbl = _ImagemLabel("baixando imagem…")
        lay.addWidget(self.lbl, 1)
        self.cap = QLabel(""); self.cap.setWordWrap(True)                # nome da tarefa ABAIXO
        self.cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cap.setStyleSheet("font-weight:500; padding:2px 6px;")
        lay.addWidget(self.cap)

        row = QHBoxLayout()
        self.b_prev = QPushButton("‹ Anterior"); self.b_prev.setObjectName("secondary")
        self.b_prev.setAutoDefault(False); self.b_prev.clicked.connect(lambda: self._ir(-1))
        self.pos = QLabel(""); self.pos.setObjectName("hint")
        self.pos.setAlignment(Qt.AlignmentFlag.AlignCenter); self.pos.setMinimumWidth(80)
        self.b_next = QPushButton("Próxima ›"); self.b_next.setObjectName("secondary")
        self.b_next.setAutoDefault(False); self.b_next.clicked.connect(lambda: self._ir(1))
        self.b_save = QPushButton("Salvar…"); self.b_save.setObjectName("secondary")
        self.b_save.setEnabled(False); self.b_save.setAutoDefault(False); self.b_save.clicked.connect(self._salvar)
        b_close = QPushButton("Fechar"); b_close.setObjectName("secondary")
        b_close.setAutoDefault(False); b_close.clicked.connect(self.accept)
        row.addWidget(self.b_prev); row.addWidget(self.pos); row.addWidget(self.b_next)
        row.addStretch(1); row.addWidget(self.b_save); row.addWidget(b_close)
        lay.addLayout(row)
        self._carregar()

    def _img(self):
        return self._imgs[self._idx] if 0 <= self._idx < len(self._imgs) else {}

    def _ir(self, delta):
        novo = self._idx + delta
        if 0 <= novo < len(self._imgs):
            self._idx = novo
            self._carregar()

    @slot_seguro
    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Left:
            self._ir(-1)
        elif e.key() == Qt.Key.Key_Right:
            self._ir(1)
        else:
            super().keyPressEvent(e)

    @slot_seguro
    def _carregar(self):
        img = self._img()
        n = len(self._imgs)
        desc = self._galeria._rotulo(self._idx)      # 'Ativo — Tarefa'
        self.setWindowTitle(f"Foto {self._idx + 1} de {n} — {desc}")
        self.cap.setText(desc)
        self.pos.setText(f"{self._idx + 1} de {n}")
        self.b_prev.setEnabled(self._idx > 0)
        self.b_next.setEnabled(self._idx < n - 1)
        self._bytes = None
        self.b_save.setEnabled(False)
        data = self._galeria._cache.get(img.get("url"))     # já baixada pela grade → instantâneo
        if data:
            self._set_bytes(bytes(data)); return
        self.lbl.mostrar_texto("baixando imagem…")
        url = img.get("url")
        if url:
            i = self._idx
            self._w = ApiWorker(api.baixar_imagem, url)
            self._w.ok.connect(lambda d, i=i: self._got(i, d))
            self._w.erro.connect(lambda m, i=i: self._erro(i, m))
            self._w.start()
        else:
            data = _b64_bytes(img.get("thumb"))
            if data:
                self._set_bytes(data)
                self.lbl.setToolTip("Pré-visualização (sem imagem em alta para esta foto)")
            else:
                self.lbl.mostrar_texto("(imagem indisponível)")

    @slot_seguro
    def _got(self, i, data):
        if isinstance(data, (bytes, bytearray)):
            self._galeria._cache.setdefault(self._imgs[i].get("url"), bytes(data))
        if i != self._idx:                       # resultado de uma foto que já saiu da tela
            return
        if isinstance(data, (bytes, bytearray)):
            self._set_bytes(bytes(data))
        else:
            self.lbl.mostrar_texto("(não consegui baixar a imagem)")

    @slot_seguro
    def _erro(self, i, m):
        if i == self._idx:
            self.lbl.mostrar_texto("⚠ " + str(m))

    def _set_bytes(self, data):
        pix = _pix(data)
        if not pix:
            self.lbl.mostrar_texto("(não consegui exibir a imagem)"); return
        self._bytes = bytes(data)
        self.lbl.set_imagem(pix)
        self.b_save.setEnabled(True)

    def _salvar(self):
        if not self._bytes:
            return
        sug = self._galeria._rotulo(self._idx).replace(" — ", "_").replace(" ", "_")[:60] or "foto"
        path, _ = QFileDialog.getSaveFileName(self, "Salvar foto", sug + ".jpg",
                                              "Imagem (*.jpg *.jpeg *.png)")
        if not path:
            return
        try:
            with open(path, "wb") as f:
                f.write(self._bytes)
        except OSError as e:
            QMessageBox.critical(self, "Salvar", f"Não consegui salvar:\n{e}"); return
        if QMessageBox.question(self, "Salvo", f"Foto salva em:\n{path}\n\nAbrir agora?"
                                ) == QMessageBox.StandardButton.Yes:
            try:
                os.startfile(path)
            except (OSError, AttributeError):
                pass
