"""Auto-atualização via GitHub Releases (repositório PÚBLICO só-releases). Ao abrir, o app lê o
versao.json da última release; se houver versão nova, pergunta e, aceitando, baixa o setup.exe e
roda o instalador em SILÊNCIO (/VERYSILENT) — o Inno fecha o app e o reabre já atualizado.
Sem token/credencial: as releases são públicas."""
import os
import subprocess
import sys
import tempfile
import requests
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox, QProgressDialog, QApplication

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
    notas = str(info.get("notas") or "").strip()
    msg = f"Versão {nova} disponível (você tem {APP_VERSAO})."
    if notas:
        msg += f"\n\nNovidades:\n{notas}"
    msg += "\n\nAtualizar agora? O app fecha, atualiza e reabre sozinho."
    if QMessageBox.question(parent, "Atualização disponível", msg) != QMessageBox.StandardButton.Yes:
        return
    _baixar_e_instalar(parent, url, nova)


def _baixar_e_instalar(parent, url, nova):
    dest = os.path.join(tempfile.gettempdir(), "CriarOS_Setup_%s.exe" % nova.replace(".", "_"))
    dlg = QProgressDialog("Baixando atualização…", "Cancelar", 0, 100, parent)
    dlg.setWindowTitle("Atualizando"); dlg.setWindowModality(Qt.WindowModality.WindowModal)
    dlg.setMinimumDuration(0); dlg.setValue(0)
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            got = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    if dlg.wasCanceled():
                        return
                    f.write(chunk); got += len(chunk)
                    if total:
                        dlg.setValue(int(got * 100 / total))
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
