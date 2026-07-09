"""Deixa um QComboBox pesquisável: digitar filtra as opções (contém), sem texto livre (NoInsert).
Melhorias de praticidade:
- o item "placeholder" (— selecione —, Todos os…, (carregue…)) aparece como DICA CINZA (campo vazio),
  não como texto preenchido — some ao digitar;
- ao FOCAR, seleciona todo o texto (a 1ª tecla já limpa e você digita o filtro);
- ao DESFOCAR, valida: nome válido confirma a opção; texto inválido some sozinho.
Usado nos filtros de todas as telas."""
from PyQt6.QtCore import Qt, QObject, QEvent, QTimer
from PyQt6.QtWidgets import QComboBox, QCompleter


def _eh_placeholder(txt) -> bool:
    """True se o texto é um item 'sem seleção' (dica), não um valor real."""
    t = (txt or "").strip().lower()
    return (not t) or t.startswith("—") or t.startswith("(") or "selecione" in t \
        or t.startswith("todos") or t.startswith("carregando")


def _sync_placeholder(cb: QComboBox) -> None:
    """Se o item atual é um placeholder, mostra o campo VAZIO com a dica em cinza (fora do foco)."""
    le = cb.lineEdit()
    if le is None:
        return
    i = cb.currentIndex()
    itxt = cb.itemText(i) if i >= 0 else ""
    if _eh_placeholder(itxt):
        le.setPlaceholderText(itxt.strip() or "selecione")
        if not le.hasFocus() and le.text():
            le.setText("")


class _BuscaCombo(QObject):
    def eventFilter(self, le, ev):
        cb = le.parent()
        if not isinstance(cb, QComboBox):
            return False
        t = ev.type()
        if t == QEvent.Type.FocusIn:
            QTimer.singleShot(0, lambda: self._focar(cb, le))     # seleciona tudo + abre a lista cheia
        elif t == QEvent.Type.MouseButtonPress:
            QTimer.singleShot(0, lambda: self._todas(cb))         # re-clicar reabre a lista completa
        elif t == QEvent.Type.FocusOut:
            i = cb.findText(le.text(), Qt.MatchFlag.MatchFixedString)
            if i >= 0:
                cb.setCurrentIndex(i)                             # confirma a opção digitada
            cur = cb.itemText(cb.currentIndex())                  # placeholder → vazio; senão o valor
            le.setText("" if _eh_placeholder(cur) else cur)
        return False

    @staticmethod
    def _focar(cb, le):
        le.selectAll()                                           # 1ª tecla limpa e você digita
        _BuscaCombo._todas(cb)

    @staticmethod
    def _todas(cb):
        """Mostra TODAS as opções (prefixo vazio) ao clicar/focar — não precisa digitar antes."""
        comp = cb.completer()
        if comp is not None:
            comp.setCompletionPrefix("")
            comp.complete()


_busca = None


def tornar_pesquisavel(cb: QComboBox) -> QComboBox:
    """Torna o combo editável com filtro por 'contém' + placeholder cinza. Chamar UMA vez."""
    global _busca
    if _busca is None:
        _busca = _BuscaCombo()
    cb.setEditable(True)
    cb.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    cb.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    cb.completer().setFilterMode(Qt.MatchFlag.MatchContains)
    cb.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    cb.lineEdit().installEventFilter(_busca)
    # sync ADIADO (QTimer 0): roda DEPOIS que o combo assenta o lineEdit ao popular/mudar índice —
    # senão o rowsInserted dispara antes do combo preencher o texto e o placeholder não limpa.
    cb.currentIndexChanged.connect(lambda *_: QTimer.singleShot(0, lambda: _sync_placeholder(cb)))
    cb.model().rowsInserted.connect(lambda *_: QTimer.singleShot(0, lambda: _sync_placeholder(cb)))
    QTimer.singleShot(0, lambda: _sync_placeholder(cb))
    return cb


def tornar_todos_pesquisaveis(root) -> None:
    """Liga a busca em TODOS os QComboBox de seleção única de `root` (recursivo). Pula os já-editáveis
    (OsPaiPicker, responsável) e o CheckableComboBox de multi-seleção. Idempotente."""
    for cb in root.findChildren(QComboBox):
        if cb.isEditable():
            continue
        if type(cb).__name__ == "CheckableComboBox":
            continue
        tornar_pesquisavel(cb)
