"""Documentos anexados à OS — PDF, Excel, ZIP e afins, com ABRIR e BAIXAR.

POR QUE ISTO EXISTE: antes o app listava esses anexos numa caixa de mensagem, só com o nome.
Dava para saber que o arquivo existia e nada além disso — não abria, não baixava. E pior: o
`api.get_os_anexos` classificava como IMAGEM tudo que tivesse URL (`is_image = bool(url) or …`),
e como PDF/Excel/ZIP do S3 também vêm com URL pré-assinada, eles iam para a galeria, a prévia
falhava e o arquivo sumia da tela. A classificação virou por EXTENSÃO; esta tela é o destino
de quem não é imagem.

Notas de TEXTO (anexo sem arquivo) continuam aqui, mas sem botão — não há o que baixar.
"""
import os
import subprocess
import sys
import tempfile

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
                             QScrollArea, QWidget, QFileDialog, QMessageBox)

from workers import ApiWorker, slot_seguro

# Ícone por família de arquivo. Texto puro, sem emoji (convenção do projeto): a extensão em
# maiúscula já é o identificador mais rápido de ler numa lista.
def _ext(nome):
    return (os.path.splitext(str(nome or ""))[1] or "").lstrip(".").upper() or "ARQ"


def _baixar_bytes(url):
    """Baixa o conteúdo da URL pré-assinada. Roda em worker — nunca na thread da interface."""
    import requests
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.content


class DocumentosDialog(QDialog):
    def __init__(self, parent, itens, titulo="Documentos da OS"):
        super().__init__(parent)
        from steps.ui import QSS_FORM, MUTED, TEXT, CARD, BORDER
        self._itens = [d for d in (itens or []) if isinstance(d, dict)]
        self._w = None
        self.setWindowTitle(titulo)
        self.setMinimumSize(620, 420)
        self.setStyleSheet(QSS_FORM)
        v = QVBoxLayout(self); v.setContentsMargins(18, 16, 18, 14); v.setSpacing(12)

        t = QLabel(titulo)
        t.setStyleSheet(f"color:{TEXT};font-size:15px;font-weight:600;background:transparent;")
        v.addWidget(t)
        n_arq = sum(1 for d in self._itens if d.get("url"))
        sub = QLabel("%d arquivo(s) · %d nota(s) de texto"
                     % (n_arq, len(self._itens) - n_arq))
        sub.setStyleSheet(f"color:{MUTED};font-size:12px;background:transparent;")
        v.addWidget(sub)

        rolo = QScrollArea(); rolo.setWidgetResizable(True)
        rolo.setFrameShape(QScrollArea.Shape.NoFrame)
        rolo.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget(); rolo.setWidget(host)
        lista = QVBoxLayout(host); lista.setContentsMargins(0, 0, 6, 0); lista.setSpacing(8)
        for d in self._itens:
            lista.addWidget(self._linha(d, CARD, BORDER, TEXT, MUTED))
        lista.addStretch(1)
        v.addWidget(rolo, 1)

        self.hint = QLabel("")
        self.hint.setStyleSheet(f"color:{MUTED};font-size:11.5px;background:transparent;")
        rod = QHBoxLayout(); rod.addWidget(self.hint); rod.addStretch(1)
        b = QPushButton("Fechar"); b.setObjectName("secondary"); b.clicked.connect(self.accept)
        rod.addWidget(b)
        v.addLayout(rod)

    def _linha(self, d, CARD, BORDER, TEXT, MUTED):
        f = QFrame(); f.setObjectName("docRow")
        f.setStyleSheet("QFrame#docRow{background:%s;border:1px solid %s;border-radius:10px;}"
                        % (CARD, BORDER))
        h = QHBoxLayout(f); h.setContentsMargins(13, 10, 13, 10); h.setSpacing(11)
        nome = d.get("nome") or "anexo"
        tag = QLabel(_ext(nome))
        tag.setFixedWidth(46); tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tag.setStyleSheet("background:rgba(166,226,46,0.12);color:#a3d900;border-radius:6px;"
                          "padding:3px 0;font-size:10.5px;font-weight:700;")
        h.addWidget(tag)
        cx = QVBoxLayout(); cx.setSpacing(2)
        ln = QLabel(nome); ln.setWordWrap(True)
        ln.setStyleSheet(f"color:{TEXT};font-size:12.5px;background:transparent;")
        cx.addWidget(ln)
        quem = (d.get("user") or "").strip()
        desc = (d.get("desc") or "").strip()
        sub = " · ".join(x for x in (quem, desc if desc != nome else "") if x)
        if sub:
            ls = QLabel(sub); ls.setWordWrap(True)
            ls.setStyleSheet(f"color:{MUTED};font-size:11px;background:transparent;")
            cx.addWidget(ls)
        h.addLayout(cx, 1)
        if d.get("url"):
            b_abrir = QPushButton("Abrir"); b_abrir.setObjectName("secondary")
            b_abrir.setCursor(Qt.CursorShape.PointingHandCursor)
            b_abrir.clicked.connect(lambda *_, dd=d: self._acao(dd, salvar=False))
            b_baixar = QPushButton("Baixar"); b_baixar.setObjectName("secondary")
            b_baixar.setCursor(Qt.CursorShape.PointingHandCursor)
            b_baixar.clicked.connect(lambda *_, dd=d: self._acao(dd, salvar=True))
            h.addWidget(b_abrir); h.addWidget(b_baixar)
        else:
            nada = QLabel("nota de texto")
            nada.setStyleSheet(f"color:{MUTED};font-size:11px;background:transparent;")
            h.addWidget(nada)
        return f

    @slot_seguro
    def _acao(self, d, salvar):
        if self._w is not None:
            return
        nome = d.get("nome") or "anexo"
        destino = None
        if salvar:
            destino, _ = QFileDialog.getSaveFileName(self, "Salvar anexo", nome)
            if not destino:
                return
        self._pend = (nome, destino)
        self.hint.setText("baixando %s…" % nome)
        self._w = ApiWorker(_baixar_bytes, d["url"])
        self._w.ok.connect(self._chegou); self._w.erro.connect(self._falhou)
        self._w.start()

    @slot_seguro
    def _falhou(self, m):
        self._w = None; self.hint.setText("")
        QMessageBox.critical(self, "Anexo", "Não consegui baixar o arquivo:\n%s" % m)

    @slot_seguro
    def _chegou(self, dados):
        self._w = None; self.hint.setText("")
        nome, destino = getattr(self, "_pend", ("anexo", None))
        try:
            if destino:
                with open(destino, "wb") as f:
                    f.write(dados)
                self.hint.setText("salvo em %s" % os.path.basename(destino))
                return
            # ABRIR: grava numa temporária e entrega ao programa padrão do sistema. Não tentamos
            # renderizar PDF/Excel aqui — o Excel do usuário abre melhor que qualquer visualizador
            # que a gente escrevesse, e ZIP nem faz sentido pré-visualizar.
            pasta = tempfile.mkdtemp(prefix="oscreator_")
            cam = os.path.join(pasta, nome)
            with open(cam, "wb") as f:
                f.write(dados)
            if sys.platform.startswith("win"):
                os.startfile(cam)                                  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", cam])
            else:
                subprocess.Popen(["xdg-open", cam])
            self.hint.setText("aberto no programa padrão")
        except OSError as e:
            QMessageBox.critical(self, "Anexo", "Não consegui gravar o arquivo:\n%s" % e)


def abrir_documentos(parent, itens, titulo="Documentos da OS"):
    if not itens:
        QMessageBox.information(parent, titulo, "Nenhum documento nesta OS.")
        return
    DocumentosDialog(parent, itens, titulo).exec()
