"""main.py — entry point do app desktop "Criar OS — Fracttal".

Multiusuário: cada pessoa entra com o PRÓPRIO e-mail/senha do Fracttal (rpc/login_new) e a OS
é criada no nome dela. O app NÃO carrega segredo da empresa — leituras de pessoal/etiquetas vêm
da sessão do usuário e os ativos de um catálogo (assets_cache.json) atualizado pelo admin.

Uso:
    pip install -r requirements.txt
    python main.py
"""
import sys
from PyQt6.QtCore import Qt, QTranslator, QLibraryInfo, QLocale, QTimer
from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6.QtGui import QIcon
import api
from app import MainWindow, DARK_QSS, LoginDialog, _asset
from steps.updater import checar_atualizacao
from steps.splash import mostrar_splash
from workers import registrar_erro


def main():
    # Rede de segurança: no PyQt6 uma exceção não tratada num slot ENCERRA o app. Aqui qualquer
    # exceção não capturada é gravada no log (%TEMP%\criaros_erros.log) em vez de fechar em silêncio.
    sys.excepthook = lambda *ei: registrar_erro(ei)
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
    from steps.nowheel import instalar as _instalar_nowheel
    _instalar_nowheel(app)                 # roda do mouse não muda combos/datas sem querer
    # Splash: símbolo da Grid (grande) surge e some antes do app aparecer.
    mostrar_splash(app, _asset("grid-icon.png"))
    # Gate de login: sem JWT de sessão válido, pede e-mail + senha.
    if not api.is_logged_in():
        if LoginDialog().exec() != QDialog.DialogCode.Accepted:
            sys.exit(0)
    win = MainWindow()
    win.show()
    # checa atualização (GitHub Releases) logo após abrir, sem travar o boot
    QTimer.singleShot(1500, lambda: checar_atualizacao(win, silencioso=True))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
