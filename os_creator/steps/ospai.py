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
        self._wf = None                         # worker do set_by_folio (deep link)
        self._pending_folio = ""
        self._timer = QTimer(self); self._timer.setSingleShot(True); self._timer.setInterval(300)
        self._timer.timeout.connect(self._buscar)
        self.lineEdit().textEdited.connect(self._on_edit)
        self.activated.connect(self._on_pick)

    def id_parent(self):
        """id da OS pai escolhida, ou None se o campo estiver vazio/sem seleção."""
        return self._sel if self.currentText().strip() else None

    def set_by_folio(self, folio):
        """Pré-seleciona a OS pai pelo NÚMERO (folio) — usado pelo deep link (OS atribuída vira OS pai).
        Busca no Fracttal e escolhe o match EXATO do folio (o id certo p/ id_parent)."""
        self._pending_folio = str(folio or "").strip()
        if not self._pending_folio:
            return
        self._wf = ApiWorker(api.buscar_os_pai, self._pending_folio)
        self._wf.ok.connect(self._auto_sel)
        self._wf.erro.connect(lambda *_: None)
        self._wf.start()

    @slot_seguro
    def _auto_sel(self, res):
        self._wf = None
        m = next((r for r in (res or []) if str(r.get("folio") or "").strip() == self._pending_folio), None)
        if not m:
            return
        self.blockSignals(True)
        self.clear()
        self.addItem(str(m.get("folio")) + (f" — {m.get('descricao')}" if m.get("descricao") else ""), m.get("id"))
        self.setCurrentIndex(0)
        self._sel = m.get("id")
        self.blockSignals(False)

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
