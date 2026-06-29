"""Exportar uma lista (cabeçalho + linhas) para CSV que abre direto no Excel pt-BR.
UTF-8 com BOM (acentos certos no Excel) e separador ';' (Excel pt-BR já separa em colunas)."""
import csv
import os
from PyQt6.QtWidgets import QFileDialog, QMessageBox


def escrever_csv(path, headers, rows):
    """Escreve o CSV (sem UI). Levanta OSError em falha de disco."""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(headers)
        for row in rows:
            w.writerow(["" if c is None else str(c) for c in row])
    return path


def exportar_csv(parent, headers, rows, sugestao="export.csv", titulo="Exportar CSV"):
    """Pede o caminho (QFileDialog), grava e oferece abrir. → True se exportou."""
    if not rows:
        QMessageBox.information(parent, titulo, "Nada para exportar — a lista está vazia.")
        return False
    path, _ = QFileDialog.getSaveFileName(parent, titulo, sugestao, "Planilha CSV (*.csv)")
    if not path:
        return False
    if not path.lower().endswith(".csv"):
        path += ".csv"
    try:
        escrever_csv(path, headers, rows)
    except OSError as e:
        QMessageBox.critical(parent, titulo, f"Não consegui salvar o arquivo:\n{e}")
        return False
    if QMessageBox.question(parent, "Exportado",
            f"{len(rows)} linha(s) salvas em:\n{path}\n\nAbrir agora?"
            ) == QMessageBox.StandardButton.Yes:
        try:
            os.startfile(path)                 # Windows: abre no app padrão (Excel)
        except (OSError, AttributeError):
            pass
    return True
