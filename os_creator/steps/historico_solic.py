"""Histórico de Solicitações — solicitações de serviço, com filtro por CRIADOR (default = usuário
logado, pode trocar p/ outros ou Todos), filtros multi-seleção (Cliente/Usina/Tipo de ativo/Status),
filtro de data (BR) e status colorido. Clique no Nº mostra a descrição; clique na OS ligada abre o
detalhe da OS. Lê via api.list_minhas_solicitacoes."""
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QColor, QBrush, QShortcut, QKeySequence
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
                             QDateEdit, QComboBox, QLineEdit, QSizePolicy, QMessageBox, QTableWidget,
                             QTableWidgetItem, QHeaderView, QAbstractItemView)
import api
from workers import ApiWorker
from steps.os_detalhe import abrir_os_detalhe
from steps.checkcombo import CheckableComboBox
from steps.cancelar_solic import abrir_cancelar_solic
from steps.exportar import exportar_csv
from steps.spinner import Spinner

# status em que a solicitação ainda pode ser cancelada (os demais já estão fechados)
_NAO_CANCELAVEL = {"Cancelada", "Rejeitada", "Concluída", "OS concluída", "Resolvida com OS",
                   "Resolvida sem OS"}

_STATUS_COR = {
    "Aberta":            ("#fef3c7", "#92400e"),
    "Aprovada":          ("#dbeafe", "#1d4ed8"),
    "OS em processo":    ("#dbeafe", "#1d4ed8"),
    "OS em verificação": ("#e0e7ff", "#4338ca"),
    "Concluída":         ("#dcfce7", "#166534"),
    "OS concluída":      ("#dcfce7", "#166534"),
    "Cancelada":         ("#fee2e2", "#b91c1c"),
    "Rejeitada":         ("#fee2e2", "#b91c1c"),
}


def _data_br(iso):
    return api.fmt_data_br(iso)        # UTC do Fracttal → horário de Brasília


class HistoricoSolic(QWidget):
    def __init__(self):
        super().__init__()
        self._dados = []
        self._linhas = []
        self._w = None
        self._wp = None
        self._pessoas_loaded = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(8)

        # criador (default = logado) + limpar filtros + atualizar
        row = QHBoxLayout(); row.setSpacing(6)
        row.addWidget(QLabel("Criado por"))
        self.cb_pessoa = QComboBox(); self.cb_pessoa.setMinimumWidth(220)
        self.cb_pessoa.currentIndexChanged.connect(self._on_pessoa)
        row.addWidget(self.cb_pessoa)
        row.addStretch(1)
        row.addWidget(QLabel("Buscar"))
        self.busca = QLineEdit(); self.busca.setPlaceholderText("nº, ativo, descrição, status…")
        self.busca.setMaximumWidth(220); self.busca.setClearButtonEnabled(True)
        self.busca.setToolTip("Filtra por qualquer campo (nº, cliente, usina, ativo, descrição, "
                              "status).  [Ctrl+F]")
        self.busca.textChanged.connect(self._aplica)
        row.addWidget(self.busca)
        self.b_export = QPushButton("Exportar"); self.b_export.setObjectName("secondary")
        self.b_export.setToolTip("Exporta as solicitações exibidas p/ CSV (abre no Excel).  [Ctrl+E]")
        self.b_export.clicked.connect(self._exportar)
        row.addWidget(self.b_export)
        self.b_limpar = QPushButton("Limpar filtros"); self.b_limpar.setObjectName("secondary")
        self.b_limpar.setToolTip("Desmarca Cliente/Usina/Tipo/Status e limpa a busca")
        self.b_limpar.clicked.connect(self._limpar_filtros)
        row.addWidget(self.b_limpar)
        self.b_reload = QPushButton("↻"); self.b_reload.setObjectName("secondary")
        self.b_reload.setFixedWidth(38); self.b_reload.setToolTip("Atualizar  [F5]")
        self.b_reload.clicked.connect(self._carregar)
        row.addWidget(self.b_reload)
        lay.addLayout(row)

        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: (self.busca.setFocus(),
                                                                   self.busca.selectAll()))
        QShortcut(QKeySequence("Ctrl+E"), self, activated=self._exportar)
        QShortcut(QKeySequence(Qt.Key.Key_F5), self, activated=self._carregar)

        # filtros multi-seleção (client-side)
        self.cb_status  = CheckableComboBox("Todos os status",   on_change=self._aplica)
        self.cb_cliente = CheckableComboBox("Todos os clientes", on_change=self._on_cliente)
        self.cb_usina   = CheckableComboBox("Todas as usinas",   on_change=self._aplica)
        self.cb_tipo    = CheckableComboBox("Todos os tipos",    on_change=self._aplica)
        for _cb in (self.cb_status, self.cb_cliente, self.cb_usina, self.cb_tipo):
            _cb.setMinimumWidth(150)
            _cb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.d_de = QDateEdit(); self.d_de.setCalendarPopup(True); self.d_de.setMaximumWidth(120)
        self.d_de.setDisplayFormat("dd/MM/yyyy"); self.d_de.setDate(QDate.currentDate().addDays(-30))
        self.d_de.dateChanged.connect(self._aplica)
        self.d_ate = QDateEdit(); self.d_ate.setCalendarPopup(True); self.d_ate.setMaximumWidth(120)
        self.d_ate.setDisplayFormat("dd/MM/yyyy"); self.d_ate.setDate(QDate.currentDate())
        self.d_ate.dateChanged.connect(self._aplica)

        def _cell(titulo, *widgets):
            box = QWidget()
            v = QVBoxLayout(box); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(3)
            cap = QLabel(titulo); cap.setStyleSheet("color:#6b7280; font-size:11px;")
            v.addWidget(cap)
            if len(widgets) == 1:
                v.addWidget(widgets[0])
            else:
                h = QHBoxLayout(); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(6)
                for wdg in widgets:
                    h.addWidget(wdg)
                h.addStretch(1); v.addLayout(h)
            return box

        grid = QGridLayout(); grid.setHorizontalSpacing(22); grid.setVerticalSpacing(9)
        grid.addWidget(_cell("Cliente",        self.cb_cliente), 0, 0)
        grid.addWidget(_cell("Usina",          self.cb_usina),   0, 1)
        grid.addWidget(_cell("Tipo de ativo",  self.cb_tipo),    0, 2)
        grid.addWidget(_cell("Status",         self.cb_status),  1, 0)
        grid.addWidget(_cell("Período", self.d_de, QLabel("até"), self.d_ate), 1, 1, 1, 2)
        for _c in (0, 1, 2):
            grid.setColumnStretch(_c, 1)
        lay.addLayout(grid)

        self.tab = QTableWidget(0, 8)
        self.tab.setHorizontalHeaderLabels(
            ["Nº", "Cliente", "Usina", "Ativo", "Descrição", "Criada em", "Status", "OS ligada"])
        self.tab.verticalHeader().setVisible(False)
        self.tab.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tab.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tab.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tab.setWordWrap(False)
        h = self.tab.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        self.tab.setColumnWidth(1, 90)
        self.tab.setColumnWidth(2, 130)
        self.tab.setColumnWidth(3, 150)
        self.tab.cellClicked.connect(self._on_cell)
        lay.addWidget(self.tab, 1)

        hrow = QHBoxLayout(); hrow.setSpacing(8)
        self.spinner = Spinner(self)
        hrow.addWidget(self.spinner)
        self.hint = QLabel(""); self.hint.setObjectName("hint")
        hrow.addWidget(self.hint); hrow.addStretch(1)
        lay.addLayout(hrow)

    def carregar_inicial(self):
        """1ª abertura → carrega a lista de pessoas (e, ao selecionar o logado, a lista de solicitações)."""
        if not self._pessoas_loaded and self._wp is None:
            self.spinner.start()
            self.hint.setText("carregando usuários…")
            self._wp = ApiWorker(api.get_pessoas_contas)
            self._wp.ok.connect(self._set_pessoas)
            self._wp.erro.connect(lambda m: (self._set_pessoas(None), self._carregar()))
            self._wp.start()
        elif not self._dados and self._w is None:
            self._carregar()

    def _set_pessoas(self, r):
        self._wp = None
        self._pessoas_loaded = True
        pessoas = (r or {}).get("pessoas") or []
        eu = (r or {}).get("eu")
        self.cb_pessoa.blockSignals(True)
        self.cb_pessoa.clear()
        self.cb_pessoa.addItem("Todos os usuários", "TODOS")
        sel = 0
        for i, p in enumerate(pessoas, start=1):
            self.cb_pessoa.addItem(p["nome"], p["id_account"])
            if p["id_account"] == eu:
                sel = i
        self.cb_pessoa.setCurrentIndex(sel)         # default = usuário logado
        self.cb_pessoa.blockSignals(False)
        self._carregar()

    def _on_pessoa(self, _idx):
        self._carregar()

    # ── dados ──
    def _carregar(self):
        self.spinner.start()
        self.hint.setText("carregando solicitações…")
        self.tab.setRowCount(0)
        idacc = self.cb_pessoa.currentData() if self.cb_pessoa.count() else None
        self._w = ApiWorker(api.list_minhas_solicitacoes, idacc)
        self._w.ok.connect(self._set_dados)
        self._w.erro.connect(self._erro)
        self._w.start()

    def _set_dados(self, dados):
        self._w = None
        self.spinner.stop()
        self._dados = dados or []
        self._rebuild_status()
        self._rebuild_filtros_ativo()
        self._aplica()

    def _erro(self, m):
        self._w = None
        self.spinner.stop()
        self.hint.setText("⚠ " + m)

    def _rebuild_status(self):
        sts = sorted({d.get("status") for d in self._dados if d.get("status")})
        self.cb_status.set_items(sts)

    def _rebuild_filtros_ativo(self):
        """Repovoa Cliente/Tipo de ativo (multi; preserva marcados). Usina cascateia."""
        clientes = sorted({d.get("cliente") for d in self._dados
                           if d.get("cliente") and d.get("cliente") != "—"})
        tipos = sorted({d.get("tipo") for d in self._dados
                        if d.get("tipo") and d.get("tipo") != "—"})
        self.cb_cliente.set_items(clientes)
        self.cb_tipo.set_items(tipos)
        self._rebuild_usinas()

    def _rebuild_usinas(self):
        """Usinas dos clientes marcados (ou todas, se nenhum). Multi; preserva marcadas."""
        clis = self.cb_cliente.checked_values()
        usinas = sorted({d.get("usina") for d in self._dados
                         if d.get("usina") and d.get("usina") != "—"
                         and (not clis or d.get("cliente") in clis)})
        self.cb_usina.set_items(usinas)

    def _on_cliente(self):
        self._rebuild_usinas()
        self._aplica()

    def _limpar_filtros(self):
        for cb in (self.cb_status, self.cb_cliente, self.cb_usina, self.cb_tipo):
            cb.clear_checks()
        self.busca.blockSignals(True); self.busca.clear(); self.busca.blockSignals(False)
        self._aplica()

    def _exportar(self):
        """Exporta as solicitações exibidas (já filtradas) p/ CSV."""
        headers = ["Nº", "Cliente", "Usina", "Ativo", "Descrição", "Criada em", "Status",
                   "OS ligada", "Criado por"]
        rows = [[d.get("id_code") or "", d.get("cliente") or "", d.get("usina") or "",
                 d.get("ativo") or "", d.get("descricao_full") or d.get("descricao") or "",
                 _data_br(d.get("data")), d.get("status") or "", d.get("os_folio") or "",
                 d.get("criado_por") or ""]
                for d in self._linhas]
        de = self.d_de.date().toString("yyyy-MM-dd"); ate = self.d_ate.date().toString("yyyy-MM-dd")
        exportar_csv(self, headers, rows, sugestao=f"solicitacoes_{de}_a_{ate}.csv",
                     titulo="Exportar solicitações")

    def _aplica(self):
        de = self.d_de.date().toString("yyyy-MM-dd")
        ate = self.d_ate.date().toString("yyyy-MM-dd")
        sts  = self.cb_status.checked_values()
        clis = self.cb_cliente.checked_values()
        usis = self.cb_usina.checked_values()
        tips = self.cb_tipo.checked_values()
        no = self.busca.text().strip().lower()

        def _busca(d):                       # busca AMPLA por qualquer campo de texto
            if not no:
                return True
            campos = [str(d.get("id_code") or ""), d.get("cliente") or "", d.get("usina") or "",
                      d.get("ativo") or "", d.get("descricao_full") or d.get("descricao") or "",
                      d.get("status") or "", str(d.get("os_folio") or "")]
            return any(no in c.lower() for c in campos)
        self._linhas = [d for d in self._dados
                        if de <= (d.get("data") or "")[:10] <= ate
                        and (not sts  or d.get("status")  in sts)
                        and (not clis or d.get("cliente") in clis)
                        and (not usis or d.get("usina")   in usis)
                        and (not tips or d.get("tipo")    in tips)
                        and _busca(d)]
        self.tab.setRowCount(0)
        com_os = 0
        for d in self._linhas:
            r = self.tab.rowCount(); self.tab.insertRow(r)
            it_no = QTableWidgetItem(str(d.get("id_code") or "—"))
            it_no.setForeground(QBrush(QColor("#98c838")))
            f = it_no.font(); f.setBold(True); it_no.setFont(f)
            it_no.setToolTip("Clique para ver a descrição da solicitação")
            self.tab.setItem(r, 0, it_no)
            self.tab.setItem(r, 1, QTableWidgetItem(d.get("cliente") or "—"))
            self.tab.setItem(r, 2, QTableWidgetItem(d.get("usina") or "—"))
            self.tab.setItem(r, 3, QTableWidgetItem(d.get("ativo") or ""))
            self.tab.setItem(r, 4, QTableWidgetItem(d.get("descricao") or "—"))
            self.tab.setItem(r, 5, QTableWidgetItem(_data_br(d.get("data"))))
            it = QTableWidgetItem(d.get("status") or "")
            bg, fg = _STATUS_COR.get(d.get("status"), ("#e5e7eb", "#374151"))
            it.setBackground(QBrush(QColor(bg))); it.setForeground(QBrush(QColor(fg)))
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tab.setItem(r, 6, it)
            folio = d.get("os_folio")
            osi = QTableWidgetItem(str(folio) if folio else "—")
            osi.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if folio:
                osi.setForeground(QBrush(QColor("#98c838")))
                f = osi.font(); f.setBold(True); osi.setFont(f)
                osi.setToolTip("Clique para ver a OS (Data do Evento, Notas, Subtarefas)")
                com_os += 1
            self.tab.setItem(r, 7, osi)
        extra = f"  ·  {len(self._dados)} no total" if len(self._linhas) != len(self._dados) else ""
        self.hint.setText(f"{len(self._linhas)} solicitação(ões) no período · {com_os} com OS ligada{extra}")

    def _on_cell(self, row, col):
        if row >= len(self._linhas):
            return
        d = self._linhas[row]
        if col == 0:
            self._mostrar_descricao(d)
        elif col == 7 and d.get("id_work_order"):
            abrir_os_detalhe(self, d["id_work_order"], d.get("os_folio"))

    def _mostrar_descricao(self, d):
        box = QMessageBox(self)
        box.setWindowTitle(f"Solicitação Nº {d.get('id_code')}")
        box.setTextFormat(Qt.TextFormat.RichText)
        cab = (f"<b>{d.get('ativo') or '—'}</b><br>"
               f"<span style='color:#8a90a2'>{d.get('cliente') or '—'} · {d.get('usina') or '—'} · "
               f"{d.get('status') or '—'} · {_data_br(d.get('data'))}</span>")
        if d.get("criado_por"):
            cab += f"<br><span style='color:#8a90a2'>criado por {d['criado_por']}</span>"
        box.setText(cab)
        corpo = d.get("descricao_full") or d.get("descricao") or "(sem descrição)"
        if d.get("observacao"):
            corpo += "\n\n— Comentários —\n" + d["observacao"]
        box.setInformativeText(corpo)
        box.addButton("Fechar", QMessageBox.ButtonRole.RejectRole)
        b_cancel = None
        if (d.get("status") or "") not in _NAO_CANCELAVEL and d.get("id_code") is not None:
            b_cancel = box.addButton("Cancelar solicitação", QMessageBox.ButtonRole.DestructiveRole)
        box.exec()
        if b_cancel is not None and box.clickedButton() is b_cancel:
            if abrir_cancelar_solic(self, d.get("id_code"), d.get("id_code")):
                self._carregar()      # recarrega p/ refletir o status Cancelada
