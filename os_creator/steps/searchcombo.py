"""Deixa um QComboBox pesquisável: digitar filtra as opções (contém, sem acento importa pouco), sem
permitir texto livre (NoInsert). Usado nos seletores de responsável (COS/PCM/Clonar)."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox, QCompleter


def tornar_pesquisavel(cb: QComboBox) -> QComboBox:
    """Torna o combo editável com filtro por 'contém'. Chamar UMA vez (após criar o combo);
    clear()/addItem posteriores continuam funcionando com o completer."""
    cb.setEditable(True)
    cb.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    cb.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    cb.completer().setFilterMode(Qt.MatchFlag.MatchContains)
    cb.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    return cb
