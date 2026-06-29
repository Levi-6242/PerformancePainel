"""Diálogo 'Várias Solicitações' — cria N Solicitações de Serviço de uma vez, uma por ativo MARCADO
(vários ativos), com a MESMA descrição/classificação/data. Espelha o 'Várias OSs', mas variando o
ATIVO (seleção múltipla por checkbox, como o Passo 1) em vez da data."""
from PyQt6.QtCore import Qt, QDateTime
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout, QLabel,
                             QComboBox, QLineEdit, QTextEdit, QPushButton, QMessageBox, QCheckBox,
                             QDateTimeEdit, QListWidget, QListWidgetItem)
import api
from workers import ApiWorker
from steps.step1 import ALLOWED_TIPOS, CLIENTES_OCULTOS

_SEL = "— selecione —"


def abrir_varias_solic(parent):
    VariasSolicitacoesDialog(parent).exec()


class VariasSolicitacoesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._assets = api.load_assets_cached() or []
        self._checked = set()                       # ids dos ativos marcados (persistem entre filtros)
        self._wc = self._wt = None
        self.setWindowTitle("Várias Solicitações — vários ativos")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint)
        self.setMinimumSize(640, 720)
        self.setSizeGripEnabled(True)
        lay = QVBoxLayout(self); lay.setContentsMargins(16, 14, 16, 14); lay.setSpacing(8)

        lay.addWidget(QLabel("<b style='font-size:15px'>Várias Solicitações de Serviço</b>"))
        lay.addWidget(QLabel("<span style='color:#8a90a2'>Marque vários ativos — cria uma solicitação por "
                             "ativo, com a mesma descrição e classificação.</span>"))

        # ── descrição ──
        lay.addWidget(QLabel("<b>Descrição</b> <span style='color:#8a90a2'>(vale p/ todas)</span>"))
        self.desc = QTextEdit(); self.desc.setFixedHeight(50)
        self.desc.setPlaceholderText("Descreva o problema / solicitação")
        self.desc.textChanged.connect(self._upd)
        lay.addWidget(self.desc)

        # ── ativo: cascata + lista multi-seleção ──
        grid = QGridLayout(); grid.setHorizontalSpacing(10); grid.setVerticalSpacing(3)
        self.cb_cli = QComboBox(); self.cb_cli.currentIndexChanged.connect(self._on_cli)
        self.cb_usi = QComboBox(); self.cb_usi.currentIndexChanged.connect(self._on_usi)
        self.cb_tipo = QComboBox(); self.cb_tipo.currentIndexChanged.connect(self._refresh)
        grid.addWidget(QLabel("Cliente"), 0, 0); grid.addWidget(self.cb_cli, 1, 0)
        grid.addWidget(QLabel("Usina"), 0, 1); grid.addWidget(self.cb_usi, 1, 1)
        grid.addWidget(QLabel("Tipo de equipamento"), 0, 2); grid.addWidget(self.cb_tipo, 1, 2)
        for c in (0, 1, 2):
            grid.setColumnStretch(c, 1)
        lay.addLayout(grid)
        self.busca = QLineEdit(); self.busca.setPlaceholderText("filtrar ativo por código/nome…")
        self.busca.textChanged.connect(self._refresh)
        lay.addWidget(self.busca)
        albl = QHBoxLayout()
        albl.addWidget(QLabel("<b>Ativos</b> <span style='color:#8a90a2'>(marque um ou vários)</span>"), 1)
        b_all = QPushButton("Selecionar todos"); b_all.setObjectName("secondary")
        b_all.clicked.connect(lambda: self._marcar_todos(True))
        b_none = QPushButton("Limpar"); b_none.setObjectName("secondary")
        b_none.clicked.connect(lambda: self._marcar_todos(False))
        albl.addWidget(b_all); albl.addWidget(b_none)
        lay.addLayout(albl)
        self.lista = QListWidget()
        self.lista.itemChanged.connect(self._on_check)
        self.lista.itemClicked.connect(self._toggle)
        lay.addWidget(self.lista, 1)
        self.sel_lbl = QLabel("0 marcado(s)"); self.sel_lbl.setObjectName("hint")
        lay.addWidget(self.sel_lbl)

        # ── data / urgência / comentários ──
        row = QHBoxLayout(); row.setSpacing(14)
        cd = QVBoxLayout(); cd.setSpacing(3); cd.addWidget(QLabel("Data do incidente"))
        self.data = QDateTimeEdit(QDateTime.currentDateTime())
        self.data.setDisplayFormat("dd/MM/yyyy HH:mm"); self.data.setCalendarPopup(True)
        cd.addWidget(self.data); row.addLayout(cd)
        cu = QVBoxLayout(); cu.setSpacing(3); cu.addWidget(QLabel(" "))
        self.urgente = QCheckBox("É urgente?"); cu.addWidget(self.urgente)
        row.addLayout(cu); row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(QLabel("Comentários <span style='color:#8a90a2'>(opcional)</span>"))
        self.coment = QTextEdit(); self.coment.setFixedHeight(40)
        lay.addWidget(self.coment)

        # ── classificação ──
        form = QFormLayout(); form.setSpacing(6)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.cb_grupo = QComboBox(); self.cb_grupo.addItem("carregando…", None)
        self.cb_c1 = QComboBox(); self.cb_c1.addItem("carregando…", None)
        self.cb_c2 = QComboBox(); self.cb_c2.addItem("carregando…", None)
        form.addRow("Grupo", self.cb_grupo)
        form.addRow(QLabel("Classificação 1 <span style='color:#8a90a2'>(obrigatória)</span>"), self.cb_c1)
        form.addRow("Classificação 2", self.cb_c2)
        lay.addLayout(form)

        row2 = QHBoxLayout()
        b_cancel = QPushButton("Cancelar"); b_cancel.setObjectName("secondary"); b_cancel.clicked.connect(self.reject)
        self.btn = QPushButton("Criar Solicitações"); self.btn.setEnabled(False); self.btn.clicked.connect(self._criar)
        row2.addWidget(b_cancel); row2.addWidget(self.btn, 1)
        lay.addLayout(row2)
        self.hint = QLabel(""); self.hint.setObjectName("hint")
        lay.addWidget(self.hint)

        self._fill_clientes()
        self._carregar_types()

    # ── cascata do ativo ──
    def _fill_clientes(self):
        clientes = sorted({a["cliente"] for a in self._assets
                           if a.get("cliente") and a["cliente"].strip().lower() not in CLIENTES_OCULTOS})
        self.cb_cli.blockSignals(True); self.cb_cli.clear()
        self.cb_cli.addItem("— Selecione o cliente —"); self.cb_cli.addItems(clientes)
        self.cb_cli.blockSignals(False)
        self._on_cli()

    def _cli(self):
        return self.cb_cli.currentText() if self.cb_cli.currentIndex() > 0 else None

    def _usi(self):
        return self.cb_usi.currentText() if self.cb_usi.currentIndex() > 0 else None

    def _on_cli(self, *_):
        cli = self._cli()
        usinas = sorted({a["usina"] for a in self._assets
                         if a.get("cliente") == cli and a.get("usina")}) if cli else []
        self.cb_usi.blockSignals(True); self.cb_usi.clear()
        self.cb_usi.addItem("— Selecione a usina —"); self.cb_usi.addItems(usinas)
        self.cb_usi.setEnabled(bool(usinas)); self.cb_usi.blockSignals(False)
        self._on_usi()

    def _on_usi(self, *_):
        cli, usi = self._cli(), self._usi()
        tipos = sorted({a["tipo"] for a in self._assets
                        if a.get("cliente") == cli and a.get("usina") == usi
                        and a.get("tipo") in ALLOWED_TIPOS}) if usi else []
        self.cb_tipo.blockSignals(True); self.cb_tipo.clear()
        self.cb_tipo.addItem("Todos os tipos"); self.cb_tipo.addItems(tipos)
        self.cb_tipo.setEnabled(bool(tipos)); self.cb_tipo.blockSignals(False)
        self._refresh()

    def _refresh(self, *_):
        cli, usi = self._cli(), self._usi()
        tipo = self.cb_tipo.currentText() if self.cb_tipo.currentIndex() > 0 else None
        txt = (self.busca.text() or "").strip().lower()
        self.lista.blockSignals(True); self.lista.clear()
        if usi:
            for a in sorted([x for x in self._assets if x.get("cliente") == cli and x.get("usina") == usi],
                            key=lambda x: x.get("label") or ""):
                if a.get("tipo") not in ALLOWED_TIPOS:
                    continue
                if tipo and a.get("tipo") != tipo:
                    continue
                if txt and txt not in (a.get("label") or "").lower():
                    continue
                it = QListWidgetItem(a.get("label") or a.get("code") or "?")
                it.setData(Qt.ItemDataRole.UserRole, a)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Checked if a["id"] in self._checked
                                 else Qt.CheckState.Unchecked)
                self.lista.addItem(it)
        self.lista.blockSignals(False)
        self._upd()

    # ── seleção múltipla ──
    def _toggle(self, it):
        it.setCheckState(Qt.CheckState.Unchecked if it.checkState() == Qt.CheckState.Checked
                         else Qt.CheckState.Checked)

    def _on_check(self, it):
        a = it.data(Qt.ItemDataRole.UserRole)
        if not isinstance(a, dict):
            return
        if it.checkState() == Qt.CheckState.Checked:
            self._checked.add(a["id"])
        else:
            self._checked.discard(a["id"])
        self._upd()

    def _marcar_todos(self, marcar=True):
        """Marca/desmarca todos os ativos VISÍVEIS (do filtro atual)."""
        self.lista.blockSignals(True)
        for i in range(self.lista.count()):
            it = self.lista.item(i)
            a = it.data(Qt.ItemDataRole.UserRole)
            it.setCheckState(Qt.CheckState.Checked if marcar else Qt.CheckState.Unchecked)
            if isinstance(a, dict):
                (self._checked.add if marcar else self._checked.discard)(a["id"])
        self.lista.blockSignals(False)
        self._upd()

    # ── classificações (listas) ──
    def _carregar_types(self):
        self.hint.setText("carregando listas de classificação…")
        self._wt = ApiWorker(api.get_request_types)
        self._wt.ok.connect(self._set_types)
        self._wt.erro.connect(lambda m: self.hint.setText("⚠ falha ao carregar classificações: " + m))
        self._wt.start()

    def _set_types(self, t):
        self._wt = None
        t = t or {}
        self.hint.setText("")

        def fill(cb, items):
            cb.clear(); cb.addItem(_SEL, None)
            for it in items:
                cb.addItem(it["description"], it["id"])
        fill(self.cb_grupo, t.get("grupo", []))
        fill(self.cb_c1, t.get("classif1", []))
        fill(self.cb_c2, t.get("classif2", []))

    def _txt(self, cb):
        return cb.currentText() if cb.currentIndex() > 0 else ""

    # ── habilita o botão ──
    def _upd(self, *_):
        if not hasattr(self, "btn"):
            return
        n = len(self._checked)
        self.sel_lbl.setText(f"{n} marcado(s)")
        self.btn.setText(f"Criar {n} Solicitações" if n != 1 else "Criar 1 Solicitação")
        self.btn.setEnabled(n > 0 and bool(self.desc.toPlainText().strip()))

    # ── criar ──
    def _criar(self):
        desc = self.desc.toPlainText().strip()
        if not desc:
            QMessageBox.warning(self, "Descrição", "A descrição não pode ficar em branco."); return
        assets = [a for a in self._assets if a["id"] in self._checked]
        if not assets:
            QMessageBox.warning(self, "Ativos", "Marque ao menos um ativo."); return
        c1 = self.cb_c1.currentData()
        if not c1:
            QMessageBox.warning(self, "Classificação 1", "A Classificação 1 é obrigatória."); return
        di = self.data.dateTime().toPyDateTime()       # local; create_solicitacao converte p/ UTC
        self.btn.setEnabled(False)
        self.hint.setText(f"criando {len(assets)} solicitações… (pode levar alguns segundos)")
        self._wc = ApiWorker(api.create_solicitacoes_bulk, assets, desc, c1,
                             self.cb_grupo.currentData(), self.cb_c2.currentData(),
                             self.coment.toPlainText().strip(), di, self.urgente.isChecked(),
                             self._txt(self.cb_c1), self._txt(self.cb_grupo), self._txt(self.cb_c2))
        self._wc.ok.connect(self._ok)
        self._wc.erro.connect(self._err)
        self._wc.start()

    def _ok(self, res):
        self._wc = None
        self.btn.setEnabled(True)
        res = res if isinstance(res, list) else []
        ok = [r for r in res if r.get("ok")]
        fail = [r for r in res if not r.get("ok")]
        nums = [str(r.get("id_code")) for r in ok if r.get("id_code")]
        msg = f"{len(ok)} solicitação(ões) criada(s)" + (f" — Nº {', '.join(nums)}" if nums else "") + "."
        if fail:
            msg += "\n\nFalhas:\n- " + "\n- ".join(f"{r.get('code')}: {r.get('erro')}" for r in fail[:8])
        if ok:
            QMessageBox.information(self, "Solicitações criadas", msg)
            self.accept()
        else:
            QMessageBox.critical(self, "Erro", msg or "Nenhuma solicitação criada.")
            self.hint.setText("")

    def _err(self, m):
        self._wc = None
        self.btn.setEnabled(True); self.hint.setText("")
        QMessageBox.critical(self, "Erro ao criar solicitações", m)
