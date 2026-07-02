"""Galeria de fotos de uma OS: grade de miniaturas PRÉ-CARREGADAS (baixa as imagens em paralelo, com
limite de concorrência) e, ao clicar, visualizador em tamanho cheio (instantâneo — usa o cache do
download da miniatura), com botão Salvar. Janela maximizável; as colunas se ajustam à largura."""
import base64
import os
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap, QIcon
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
                             QScrollArea, QWidget, QFileDialog, QMessageBox)
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


def abrir_galeria(parent, imagens):
    """Abre a galeria de fotos da OS (lista de {url, thumb, descricao})."""
    GaleriaDialog(parent, imagens).exec()


class GaleriaDialog(QDialog):
    def __init__(self, parent, imagens):
        super().__init__(parent)
        self._imgs = imagens or []
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

    # ── grade ──
    def _make_cell(self, img, idx):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(3)
        btn = QPushButton(f"foto {idx + 1}\n(carregando…)"); btn.setObjectName("secondary")
        btn.setFixedSize(_THUMB.width() + 6, _THUMB.height() + 6)
        btn.setToolTip(img.get("descricao") or "Ver foto em tamanho cheio")
        btn.clicked.connect(lambda _=False, i=idx: self._abrir(i))
        cap = QLabel(img.get("descricao") or ""); cap.setObjectName("hint")
        cap.setWordWrap(True); cap.setMaximumWidth(_THUMB.width() + 6)
        v.addWidget(btn); v.addWidget(cap)
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
        img = self._imgs[idx]
        ImagemViewer(self, img, self._cache.get(img.get("url"))).exec()


class ImagemViewer(QDialog):
    def __init__(self, parent, img, data=None):
        super().__init__(parent)
        self._img = img or {}
        self._bytes = bytes(data) if isinstance(data, (bytes, bytearray)) else None
        desc = self._img.get("descricao") or ""
        self.setWindowTitle("Foto" + (f" — {desc}" if desc else ""))
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint
                            | Qt.WindowType.WindowMinMaxButtonsHint)
        self.setMinimumSize(560, 460)
        self.setSizeGripEnabled(True)
        lay = QVBoxLayout(self); lay.setContentsMargins(8, 8, 8, 8)
        self.lbl = QLabel("baixando imagem…"); self.lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setWidget(self.lbl); lay.addWidget(sc, 1)
        row = QHBoxLayout()
        self.b_save = QPushButton("Salvar…"); self.b_save.setObjectName("secondary")
        self.b_save.setEnabled(False); self.b_save.clicked.connect(self._salvar)
        b_close = QPushButton("Fechar"); b_close.setObjectName("secondary"); b_close.clicked.connect(self.accept)
        row.addStretch(1); row.addWidget(self.b_save); row.addWidget(b_close)
        lay.addLayout(row)
        self._w = None
        if self._bytes:                              # já em cache → instantâneo
            self._set_bytes(self._bytes)
        elif self._img.get("url"):
            self._w = ApiWorker(api.baixar_imagem, self._img["url"])
            self._w.ok.connect(self._set_bytes)
            self._w.erro.connect(self._erro)
            self._w.start()
        else:
            data = _b64_bytes(self._img.get("thumb"))
            if data:
                self._set_bytes(data)
                self.lbl.setToolTip("Pré-visualização (sem imagem em alta para esta foto)")
            else:
                self.lbl.setText("(imagem indisponível)")

    @slot_seguro
    def _set_bytes(self, data):
        self._w = None
        if not isinstance(data, (bytes, bytearray)):
            self.lbl.setText("(imagem inválida)"); return
        self._bytes = bytes(data)
        pix = _pix(self._bytes)
        if not pix:
            self.lbl.setText("(não consegui exibir a imagem)"); return
        self.lbl.setPixmap(pix.scaledToWidth(min(pix.width(), 1100),
                                             Qt.TransformationMode.SmoothTransformation))
        self.b_save.setEnabled(True)

    @slot_seguro
    def _erro(self, m):
        self._w = None
        self.lbl.setText("⚠ " + str(m))

    def _salvar(self):
        if not self._bytes:
            return
        sug = (self._img.get("descricao") or "foto").strip().replace(" ", "_")[:40] or "foto"
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
