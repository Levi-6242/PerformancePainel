"""main.py — entry point do app desktop "Criar OS — Fracttal".

Multiusuário: cada pessoa entra com o PRÓPRIO e-mail/senha do Fracttal (rpc/login_new) e a OS
é criada no nome dela. O app NÃO carrega segredo da empresa — leituras de pessoal/etiquetas vêm
da sessão do usuário e os ativos de um catálogo (assets_cache.json) atualizado pelo admin.

Uso:
    pip install -r requirements.txt
    python main.py
"""
import sys
from PyQt6.QtCore import Qt, QTranslator, QLibraryInfo, QLocale
from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6.QtGui import QIcon
import api
from app import MainWindow, DARK_QSS, LoginDialog, _asset


def main():
    # Necessário p/ o navegador embutido (login Microsoft/SSO) ser carregado sob demanda depois.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    # botões padrão do Qt (QMessageBox Yes/No, OK, Cancel…) em pt-BR → Sim/Não
    app._tr = QTranslator()
    if app._tr.load(QLocale("pt_BR"), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(app._tr)
    app.setApplicationName("Criar OS — Fracttal")
    app.setWindowIcon(QIcon(_asset("grid-icon.png")))   # ícone Grid Co (barra de tarefas)
    app.setStyleSheet(DARK_QSS)            # tema escuro app-wide (inclui dialogs)
    # Gate de login: sem JWT de sessão válido, pede e-mail + senha.
    if not api.is_logged_in():
        if LoginDialog().exec() != QDialog.DialogCode.Accepted:
            sys.exit(0)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
