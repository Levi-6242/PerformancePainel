"""Auto-atualização via GitHub Releases (repositório PÚBLICO só-releases). Ao abrir, o app lê o
versao.json da última release; se houver versão nova, pergunta e, aceitando, baixa o setup.exe e
roda o instalador em SILÊNCIO (/VERYSILENT) — o Inno fecha o app e o reabre já atualizado.
Sem token/credencial: as releases são públicas."""
import html
import os
import re
import subprocess
import sys
import tempfile
import requests
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QMessageBox, QApplication, QDialog, QVBoxLayout, QHBoxLayout,
                             QLabel, QProgressBar, QPushButton)

from versao import APP_VERSAO

# Repositório PÚBLICO de releases (só o instalador + versao.json; o código-fonte NÃO fica aqui).
RELEASE_REPO = "Levi-6242/os-creator-releases"
_VERSAO_URL = f"https://github.com/{RELEASE_REPO}/releases/latest/download/versao.json"


def _tupla(v):
    """'2026.7.1.2' → (2026,7,1,2) p/ comparar. Partes não-numéricas viram 0."""
    out = []
    for p in str(v or "").split("."):
        out.append(int(p) if p.isdigit() else 0)
    return tuple(out)


def _mais_nova(remota, atual):
    return _tupla(remota) > _tupla(atual)


def checar_atualizacao(parent, silencioso=True):
    """Checa a release mais nova. `silencioso`=True → não avisa se já está atualizado / se falhar
    (usado no boot). Se houver versão nova e o usuário aceitar, baixa e instala."""
    try:
        r = requests.get(_VERSAO_URL, timeout=8)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        info = r.json()
    except Exception as e:
        if not silencioso:
            QMessageBox.information(parent, "Atualização",
                                   f"Não consegui checar atualizações agora.\n({e})")
        return
    nova = str(info.get("versao") or "").strip()
    url = info.get("url") or f"https://github.com/{RELEASE_REPO}/releases/latest/download/CriarOS-Fracttal-Setup.exe"
    if not nova or not _mais_nova(nova, APP_VERSAO):
        if not silencioso:
            QMessageBox.information(parent, "Atualização",
                                   f"Você já está na versão mais recente ({APP_VERSAO}).")
        return
    if not _perguntar(parent, info, nova):
        return
    _baixar_e_instalar(parent, url, nova)


def _itens_notas(notas):
    """Normaliza as 'notas' da release numa lista de tópicos curtos (bullets). Aceita lista (ideal)
    ou string (quebra por linha; se vier tudo numa linha, por ';' ou '·')."""
    if isinstance(notas, (list, tuple)):
        itens = [str(x).strip() for x in notas]
    else:
        txt = str(notas or "").strip()
        if not txt:
            return []
        partes = re.split(r"[\r\n]+", txt)
        if len(partes) == 1:
            partes = re.split(r"\s*[;·]\s*", txt)
        itens = [p.strip(" -•\t") for p in partes]
    return [i for i in itens if i]


def _perguntar(parent, info, nova):
    """Caixa 'Atualização disponível' com o mini-changelog em tópicos. True = clicou em Atualizar."""
    box = QMessageBox(parent)
    box.setWindowTitle("Atualização disponível")
    box.setIcon(QMessageBox.Icon.Information)
    box.setTextFormat(Qt.TextFormat.RichText)
    box.setText(f"<b>Nova versão {html.escape(nova)} disponível</b><br>"
                f"<span style='color:#8a90a2'>Você tem a versão {html.escape(APP_VERSAO)}.</span>")
    corpo = ""
    itens = _itens_notas(info.get("notas"))
    if itens:
        lis = "".join(f"<li>{html.escape(i)}</li>" for i in itens)
        corpo += f"<b>O que mudou nesta versão:</b><ul style='margin:4px 0 8px 0; padding-left:18px'>{lis}</ul>"
    corpo += "Atualizar agora? O app fecha, atualiza e reabre sozinho."
    box.setInformativeText(corpo)
    b_sim = box.addButton("Atualizar agora", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Depois", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(b_sim)
    box.exec()
    return box.clickedButton() is b_sim


# Preenchimento verde; o número é um rótulo sobreposto (não o texto nativo, que o tema empurra p/ a esquerda).
_BAR_QSS = ("QProgressBar{border:1px solid #2c3142; border-radius:6px; background:#1d2130;}"
            "QProgressBar::chunk{background:#5fa030; border-radius:5px; margin:0.5px;}")


class _BarraCentral(QProgressBar):
    """Barra de progresso com o percentual SEMPRE centralizado. O texto NATIVO do QProgressBar é
    jogado p/ a esquerda pelo tema global do app; aqui ele é desligado e o % vira um QLabel
    sobreposto e centralizado — imune a QSS/tema."""
    def __init__(self):
        super().__init__()
        self.setRange(0, 100)
        self.setTextVisible(False)
        self.setStyleSheet(_BAR_QSS)
        self._lbl = QLabel("0%", self)
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl.setStyleSheet("background:transparent; color:#ffffff; font-weight:600;")
        self._lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def setValue(self, v):
        super().setValue(int(v))
        self._lbl.setText(f"{int(v)}%")
        self._lbl.setGeometry(self.rect())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._lbl.setGeometry(self.rect())


class _ProgressoDownload(QDialog):
    """Diálogo de download da atualização — barra com o percentual CENTRALIZADO nela."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Atualizando")
        self.setModal(True)
        self.setMinimumWidth(440)
        self._cancelado = False
        lay = QVBoxLayout(self); lay.setContentsMargins(20, 18, 20, 16); lay.setSpacing(14)
        lay.addWidget(QLabel("Baixando atualização…"))
        self.bar = _BarraCentral(); self.bar.setFixedHeight(26)
        lay.addWidget(self.bar)
        row = QHBoxLayout(); row.addStretch(1)
        self.b_cancel = QPushButton("Cancelar"); self.b_cancel.setObjectName("secondary")
        self.b_cancel.clicked.connect(self._cancelar)
        row.addWidget(self.b_cancel); lay.addLayout(row)

    def _cancelar(self):
        self._cancelado = True

    def wasCanceled(self):
        return self._cancelado

    def set_percent(self, v):
        self.bar.setValue(int(v))


def _baixar_e_instalar(parent, url, nova):
    dest = os.path.join(tempfile.gettempdir(), "CriarOS_Setup_%s.exe" % nova.replace(".", "_"))
    dlg = _ProgressoDownload(parent)
    dlg.show(); QApplication.processEvents()
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            got = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    if dlg.wasCanceled():
                        dlg.close(); return
                    f.write(chunk); got += len(chunk)
                    if total:
                        dlg.set_percent(got * 100 / total)
                    QApplication.processEvents()
    except Exception as e:
        dlg.close()
        QMessageBox.warning(parent, "Atualização", f"Falha ao baixar a atualização:\n{e}")
        return
    dlg.close()
    try:
        subprocess.Popen([dest, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                          "/FORCECLOSEAPPLICATIONS"], close_fds=True)
    except OSError as e:
        QMessageBox.warning(parent, "Atualização", f"Não consegui iniciar o instalador:\n{e}")
        return
    # libera os arquivos p/ o instalador substituir; o Inno reabre o app ao final (WizardSilent)
    QApplication.quit()
    sys.exit(0)
