"""Bloco reutilizável: Tipo de tarefa + Classificação 1 + Classificação 2 + Criticidade.
Usado no wizard (Step2) e no diálogo 'Várias OSs'. As listas de Tipo/Classif vêm AO VIVO do
Fracttal (tasks_types_main/_list/_2_list) — assim aparecem Religamento etc., que o dropdown
estático não tinha. Criticidade é fixa (5 níveis), default Médio.

Não é um QWidget: você adiciona `.grid` (um QGridLayout) no seu layout e lê tipo_dict()/descricao_tipo()."""
from PyQt6.QtWidgets import QGridLayout, QLabel, QComboBox
import api
from workers import ApiWorker

_NENHUMA = "— nenhuma —"


class TipoTarefaBox:
    def __init__(self, crit_default=None):
        self._w = None
        self._pending_tipo = None     # tipo a selecionar quando as listas terminarem de carregar
        self._crit_default = api.CRITICIDADE_DEFAULT if crit_default is None else crit_default
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(6)

        self.cb_tipo = QComboBox()
        self.cb_tipo.addItem("carregando…", None)
        self.cb_c1 = QComboBox()
        self.cb_c1.addItem(_NENHUMA, None)
        self.cb_c2 = QComboBox()
        self.cb_c2.addItem(_NENHUMA, None)
        self.cb_crit = QComboBox()
        for nome, idp in api.CRITICIDADES:
            self.cb_crit.addItem(nome, idp)
        i = self.cb_crit.findData(self._crit_default)
        if i >= 0:
            self.cb_crit.setCurrentIndex(i)                # default Médio

        self.grid.addWidget(QLabel("<b>Tipo de tarefa</b>"), 0, 0)
        self.grid.addWidget(self.cb_tipo, 1, 0)
        self.grid.addWidget(QLabel("<b>Criticidade</b>"), 0, 1)
        self.grid.addWidget(self.cb_crit, 1, 1)
        self.grid.addWidget(QLabel("Classificação 1 <span style='color:#8a90a2'>(opcional)</span>"), 2, 0)
        self.grid.addWidget(self.cb_c1, 3, 0)
        self.grid.addWidget(QLabel("Classificação 2 <span style='color:#8a90a2'>(opcional)</span>"), 2, 1)
        self.grid.addWidget(self.cb_c2, 3, 1)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)

        self._carregar()

    # ── carga async das listas ──
    def _carregar(self):
        self._w = ApiWorker(api.get_tipos_classif)
        self._w.ok.connect(self._set)
        self._w.erro.connect(self._erro)
        self._w.start()

    def _set(self, d):
        self._w = None
        d = d or {}
        self._fill(self.cb_tipo, d.get("tipos") or [], com_nenhuma=False)
        self._fill(self.cb_c1, d.get("c1") or [], com_nenhuma=True)
        self._fill(self.cb_c2, d.get("c2") or [], com_nenhuma=True)
        if self._pending_tipo:                 # sugestão pediu um tipo antes de carregar → aplica agora
            self.selecionar(self._pending_tipo)

    def selecionar(self, nome):
        """Seleciona o tipo de tarefa por nome (ex.: 'Corretiva'). Se as listas ainda não carregaram,
        guarda como pendente e aplica em _set."""
        i = self.cb_tipo.findText(nome or "")
        if i >= 0:
            self.cb_tipo.setCurrentIndex(i)
            self._pending_tipo = None
        else:
            self._pending_tipo = nome

    def _erro(self, _m):
        self._w = None
        self.cb_tipo.clear()
        self.cb_tipo.addItem("⚠ falha ao carregar — relogue", None)

    @staticmethod
    def _fill(cb, itens, com_nenhuma):
        cb.blockSignals(True)
        cb.clear()
        if com_nenhuma:
            cb.addItem(_NENHUMA, None)
        for it in itens:
            cb.addItem(it.get("description") or "?", it.get("id"))
        cb.blockSignals(False)

    # ── getters ──
    def is_ready(self):
        """True se o Tipo de tarefa já carregou e está selecionado (id válido)."""
        return self.cb_tipo.currentData() is not None

    def descricao_tipo(self):
        """Texto do tipo (vai em tasks_types_main_description)."""
        return self.cb_tipo.currentText() if self.cb_tipo.currentData() is not None else ""

    def tipo_dict(self):
        """Dict consumido por create_os_rpc/bulk/datas (id_main + criticidade + classif 1/2)."""
        return {
            "id_main": self.cb_tipo.currentData(),
            "id_priorities": self.cb_crit.currentData(),
            "id_c1": self.cb_c1.currentData(),
            "desc_c1": self.cb_c1.currentText() if self.cb_c1.currentData() is not None else "",
            "id_c2": self.cb_c2.currentData(),
            "desc_c2": self.cb_c2.currentText() if self.cb_c2.currentData() is not None else "",
        }

    def reset(self):
        """Volta criticidade p/ Médio e classif p/ nenhuma (não recarrega as listas)."""
        i = self.cb_crit.findData(self._crit_default)
        if i >= 0:
            self.cb_crit.setCurrentIndex(i)
        if self.cb_c1.count():
            self.cb_c1.setCurrentIndex(0)
        if self.cb_c2.count():
            self.cb_c2.setCurrentIndex(0)
        if self.cb_tipo.count():
            self.cb_tipo.setCurrentIndex(0)
