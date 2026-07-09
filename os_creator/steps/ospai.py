"""Seletor de OS PAI (opcional): campo pesquisável por número. Ao digitar o nº, busca no Fracttal
(work_orders_parents_list) e mostra os resultados; escolher um define o id_parent. Vazio = sem OS pai.
Usado em Criar OS, COS e PCM. Não é obrigatório."""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QComboBox
import api
from workers import ApiWorker, slot_seguro


class OsPaiPicker(QComboBox):
    """Combo pesquisável: digite o nº da OS pai → resultados; a seleção guarda o id_parent.
    `id_parent()` devolve o id escolhido ou None (campo opcional)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMinimumWidth(260)
        self.lineEdit().setPlaceholderText("Selecione a OS pai (nº) — opcional")
        self.setToolTip("Opcional: vincula esta OS a uma OS pai. Digite o número e escolha.")
        self._sel = None                        # id_parent selecionado
        self._w = None
        self._timer = QTimer(self); self._timer.setSingleShot(True); self._timer.setInterval(300)
        self._timer.timeout.connect(self._buscar)
        self.lineEdit().textEdited.connect(self._on_edit)
        self.activated.connect(self._on_pick)

    def id_parent(self):
        """id da OS pai escolhida, ou None se o campo estiver vazio/sem seleção."""
        return self._sel if self.currentText().strip() else None

    def _on_edit(self, *_):
        self._sel = None                        # digitou → cancela a seleção até escolher de novo
        self._timer.start()

    def _on_pick(self, i):
        self._sel = self.itemData(i)

    def _buscar(self):
        termo = self.currentText().strip()
        if not termo:
            return
        self._w = ApiWorker(api.buscar_os_pai, termo)
        self._w.ok.connect(self._preencher)
        self._w.erro.connect(lambda *_: None)
        self._w.start()

    @slot_seguro
    def _preencher(self, res):
        self._w = None
        digitado = self.currentText()
        self.blockSignals(True)
        self.clear()
        for r in (res or []):
            folio = r.get("folio") or ""
            desc = r.get("descricao") or ""
            self.addItem(f"{folio}" + (f" — {desc}" if desc else ""), r.get("id"))
        self.setEditText(digitado)              # preserva o que a pessoa digitou
        self.blockSignals(False)
        if self.count() and self.hasFocus():
            self.showPopup()
