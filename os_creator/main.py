"""main.py — entry point do app desktop "Criar OS — Fracttal".

Uso:
    pip install -r requirements.txt
    # preencha o .env (FRACTTAL_CLIENT_ID / FRACTTAL_CLIENT_SECRET)
    python main.py
"""
import sys
from PyQt6.QtWidgets import QApplication
from app import MainWindow, DARK_QSS


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Criar OS — Fracttal")
    app.setStyleSheet(DARK_QSS)        # tema escuro aplicado app-wide (inclui dialogs)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
