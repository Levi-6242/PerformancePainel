"""Histórico de OS — 'Histórico Geral' (por criador: default = usuário logado, pode trocar p/ outros
ou Todos) e 'Atribuídas a mim' (id_personnel do logado, INALTERADO). Filtro de data (BR), status
colorido, e clique no nº → Data do Evento/Notas/Subtarefas. Lê via api.list_minhas_os."""
from PyQt6.QtCore import Qt, QDate, QTimer
from PyQt6.QtGui import QColor, QBrush, QShortcut, QKeySequence, QIcon
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
                             QDateEdit, QComboBox, QLineEdit, QSizePolicy, QTableWidget,
                             QTableWidgetItem, QHeaderView, QAbstractItemView, QMessageBox)
import api
from workers import ApiWorker, slot_seguro
from steps.os_detalhe import abrir_os_detalhe
from steps.checkcombo import CheckableComboBox
from steps.spinner import Spinner
from steps.exportar import exportar_csv
from steps.ui import icone_pix, GREEN

# Teto de LINHAS renderizadas na tabela. Cada linha cria um cellWidget de status (QWidget); montar
# ~2000 de uma vez com o QSS global trava a UI ~15s (e pode derrubar o app) — só acontecia no filtro
# "Todos os usuários", que traz até HISTORICO_CAP OS. A EXPORTAÇÃO continua incluindo todas as casadas.
MAX_LINHAS = 500

# status → cor viva (cards arredondados)
_STATUS_COR = {
    "Em Processo":    "#F5A623",
    "Em Verificação": "#4A9EF5",
    "Concluída":      "#48D07A",
    "Cancelada":      "#F5766B",
}


def _rgb(hexc):
    h = hexc.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _status_widget(status):
    """Card arredondado de status (cor viva), centralizado — vira cellWidget da tabela."""
    w = QWidget(); w.setStyleSheet("background:transparent;")
    h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0)
    h.setAlignment(Qt.AlignmentFlag.AlignCenter)
    if not status:
        return w
    pill = QLabel(status)
    c = _STATUS_COR.get(status)
    if c:
        r, g, b = _rgb(c)
        pill.setStyleSheet(f"color:{c};background:rgba({r},{g},{b},0.16);"
                           f"border:1px solid rgba({r},{g},{b},0.42);border-radius:8px;"
                           "padding:4px 13px;font-size:12px;font-weight:700;")
    else:
        pill.setStyleSheet("color:#c4cbdb;background:#1A2337;border:1px solid #2A3550;"
                           "border-radius:8px;padding:4px 13px;font-size:12px;font-weight:600;")
    h.addWidget(pill)
    return w


def _data_br(iso):
    return api.fmt_data_br(iso)        # UTC do Fracttal → horário de Brasília


class HistoricoOS(QWidget):
    def __init__(self):
        super().__init__()
        self._dados = []
        self._linhas = []               # linhas atualmente exibidas (p/ exportar)
        self._modo = "criadas"          # criadas = "Histórico Geral"
        self._w = None
        self._wp = None
        self._wl = None
        self._pessoas_loaded = False
        self._labels_loaded = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(8)

        # visão (Histórico Geral / Atribuídas a mim) + atualizar
        row = QHBoxLayout(); row.setSpacing(6)
        self.b_criadas = QPushButton("Histórico Geral")
        self.b_atrib = QPushButton("Atribuídas a mim")
        self.b_criadas.clicked.connect(lambda: self._set_modo("criadas"))
        self.b_atrib.clicked.connect(lambda: self._set_modo("atribuidas"))
        row.addWidget(self.b_criadas); row.addWidget(self.b_atrib)
        # box 1: buscar OS direto pelo nº (ignora filtros)
        self.busca_os = QLineEdit()
        self.busca_os.setPlaceholderText("Buscar OS pelo nº — direto, ignora filtros")
        self.busca_os.setMinimumWidth(260); self.busca_os.setClearButtonEnabled(True)
        self.busca_os.setToolTip("Digite o número da OS e tecle Enter — abre a OS direto, "
                                 "em qualquer período/criador.")
        self.busca_os.addAction(QIcon(icone_pix("search", GREEN, 15)), QLineEdit.ActionPosition.LeadingPosition)
        self.busca_os.setStyleSheet("QLineEdit{border:1px solid #5c7a2a;}")
        self.busca_os.returnPressed.connect(self._buscar_os)
        row.addSpacing(10); row.addWidget(self.busca_os)
        row.addStretch(1)
        # box 2: aviso de atualização automática
        self.lbl_auto = QLabel("↻ Atualiza a cada 15 min"); self.lbl_auto.setObjectName("hint")
        self.lbl_auto.setToolTip("Com a aba aberta, o histórico se atualiza sozinho a cada 15 minutos.")
        row.addWidget(self.lbl_auto)
        row.addWidget(QLabel("Buscar"))
        self.busca_no = QLineEdit(); self.busca_no.setPlaceholderText("nº, ativo, descrição, status…")
        self.busca_no.setMaximumWidth(200); self.busca_no.setClearButtonEnabled(True)
        self.busca_no.setToolTip("Filtra as linhas já carregadas por qualquer campo (nº, cliente, usina, "
                                 "ativo, descrição, status, etiqueta).  [Ctrl+F]")
        # debounce: filtra ~260ms DEPOIS de parar de digitar (senão reconstrói a tabela a cada tecla = trava)
        self._busca_timer = QTimer(self); self._busca_timer.setSingleShot(True); self._busca_timer.setInterval(260)
        self._busca_timer.timeout.connect(self._aplica)
        self.busca_no.textChanged.connect(lambda *_: self._busca_timer.start())
        row.addWidget(self.busca_no)
        self.b_export = QPushButton("Exportar"); self.b_export.setObjectName("secondary")
        self.b_export.setToolTip("Exporta as OS exibidas p/ CSV (abre no Excel).  [Ctrl+E]")
        self.b_export.clicked.connect(self._exportar)
        row.addWidget(self.b_export)
        self.b_limpar = QPushButton("Limpar filtros"); self.b_limpar.setObjectName("secondary")
        self.b_limpar.setToolTip("Limpa Cliente/Usina/Status/Tipos, a busca e a Etiqueta")
        self.b_limpar.clicked.connect(self._limpar_filtros)
        row.addWidget(self.b_limpar)
        self.b_reload = QPushButton("↻"); self.b_reload.setObjectName("secondary")
        self.b_reload.setFixedWidth(38); self.b_reload.setToolTip("Atualizar  [F5]")
        self.b_reload.clicked.connect(self._carregar)
        row.addWidget(self.b_reload)
        lay.addLayout(row)

        # atalhos de teclado
        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: (self.busca_no.setFocus(),
                                                                   self.busca_no.selectAll()))
        QShortcut(QKeySequence("Ctrl+E"), self, activated=self._exportar)
        QShortcut(QKeySequence(Qt.Key.Key_F5), self, activated=self._carregar)

        # ── filtros em grade (3 por linha, rótulo em cima — evita o "amontoado") ──
        # Criado por / Etiqueta = server-side (1 valor, re-buscam). Os demais = MULTI-seleção (client-side).
        self.cb_pessoa = QComboBox()                         # Criado por (populado depois)
        self.cb_pessoa.currentIndexChanged.connect(self._on_pessoa)
        self.cb_etiqueta = QComboBox()                       # Etiqueta (populado depois)
        self.cb_etiqueta.currentIndexChanged.connect(self._on_etiqueta)
        self.cb_status = CheckableComboBox("Todos os status", on_change=self._on_status_change)
        self.cb_cliente = CheckableComboBox("Todos os clientes", on_change=self._on_cliente)
        self.cb_usina = CheckableComboBox("Todas as usinas", on_change=self._on_usina)
        self.cb_tipo = CheckableComboBox("Todos os tipos", on_change=self._aplica)
        self.cb_tarefa = CheckableComboBox("Todos os tipos de tarefa", on_change=self._aplica)
        for _cb in (self.cb_pessoa, self.cb_etiqueta, self.cb_status, self.cb_cliente,
                    self.cb_usina, self.cb_tipo, self.cb_tarefa):
            _cb.setMinimumWidth(150)
            _cb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # mudar a data RE-BUSCA no servidor (o período governa a busca) — com debounce p/ não spammar
        self._dt_timer = QTimer(self); self._dt_timer.setSingleShot(True); self._dt_timer.setInterval(450)
        self._dt_timer.timeout.connect(self._carregar)
        self.d_de = QDateEdit(); self.d_de.setCalendarPopup(True); self.d_de.setMaximumWidth(120)
        self.d_de.setDisplayFormat("dd/MM/yyyy"); self.d_de.setDate(QDate.currentDate().addDays(-30))
        self.d_de.dateChanged.connect(self._on_data_change)
        self.d_ate = QDateEdit(); self.d_ate.setCalendarPopup(True); self.d_ate.setMaximumWidth(120)
        self.d_ate.setDisplayFormat("dd/MM/yyyy"); self.d_ate.setDate(QDate.currentDate())
        self.d_ate.dateChanged.connect(self._on_data_change)

        def _cell(titulo, *widgets):
            """Célula de filtro: rótulo pequeno em cima, controle(s) embaixo."""
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

        self.pessoa_w = _cell("Criado por", self.cb_pessoa)   # some na visão 'Atribuídas a mim'

        grid = QGridLayout(); grid.setHorizontalSpacing(22); grid.setVerticalSpacing(9)
        grid.addWidget(self.pessoa_w,                                 0, 0)
        grid.addWidget(_cell("Etiqueta", self.cb_etiqueta),          0, 1)
        grid.addWidget(_cell("Status", self.cb_status),              0, 2)
        grid.addWidget(_cell("Cliente", self.cb_cliente),            1, 0)
        grid.addWidget(_cell("Usina", self.cb_usina),                1, 1)
        grid.addWidget(_cell("Tipo de ativo", self.cb_tipo),         1, 2)
        grid.addWidget(_cell("Tipo de tarefa", self.cb_tarefa),      2, 0)
        grid.addWidget(_cell("Período", self.d_de, QLabel("até"), self.d_ate), 2, 1, 1, 2)
        for _c in (0, 1, 2):
            grid.setColumnStretch(_c, 1)
        lay.addLayout(grid)

        # tabela
        self.tab = QTableWidget(0, 10)
        self.tab.setHorizontalHeaderLabels(
            ["Nº", "Cliente", "Usina", "Ativo", "Descrição", "Data de Criação", "Data do Evento",
             "Data Fim", "Status", "Etiqueta"])
        self.tab.verticalHeader().setVisible(False)
        self.tab.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tab.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tab.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tab.setWordWrap(False)
        h = self.tab.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # Nº
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)       # Cliente
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)       # Usina
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)       # Ativo
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)           # Descrição
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # Data de Criação
        h.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)  # Data do Evento
        h.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)  # Data Fim
        h.setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed)             # Status (cellWidget → largura fixa)
        h.setSectionResizeMode(9, QHeaderView.ResizeMode.Interactive)       # Etiqueta
        self.tab.setColumnWidth(1, 90)
        self.tab.setColumnWidth(2, 130)
        self.tab.setColumnWidth(3, 150)
        self.tab.setColumnWidth(8, 150)
        self.tab.setColumnWidth(9, 150)
        self.tab.cellClicked.connect(self._abrir_detalhe)   # clique no nº → detalhe da OS
        lay.addWidget(self.tab, 1)

        hrow = QHBoxLayout(); hrow.setSpacing(8)
        self.spinner = Spinner(self)
        hrow.addWidget(self.spinner)
        self.hint = QLabel(""); self.hint.setObjectName("hint")
        hrow.addWidget(self.hint); hrow.addStretch(1)
        lay.addLayout(hrow)
        # auto-atualização a cada 15 min (só recarrega com a aba visível e sem carga em andamento)
        self._auto = QTimer(self); self._auto.setInterval(15 * 60 * 1000)
        self._auto.timeout.connect(self._auto_refresh)
        self._auto.start()
        self._refresh_botoes()

    def carregar_inicial(self):
        """Toda vez que a aba abre → recarrega (a menos que já haja uma carga em andamento)."""
        if self._w is None and self._wp is None and self._wl is None:
            self._iniciar()

    def _auto_refresh(self):
        if self.isVisible() and self._w is None and self._wp is None and self._wl is None:
            self._carregar()

    def recarregar(self):
        """Recarga FORÇADA (ex.: após relogar) — reseta o estado e refaz etiquetas→pessoas→OS."""
        self._dados = []
        self._labels_loaded = False
        self._pessoas_loaded = False
        self._iniciar()

    def _iniciar(self):
        self.spinner.start()
        # 1ª vez: etiquetas → pessoas (no Histórico Geral) → lista de OS
        if not self._labels_loaded and self._wl is None:
            self._carregar_labels()
        elif self._modo == "criadas" and not self._pessoas_loaded and self._wp is None:
            self._carregar_pessoas()
        else:
            self._carregar()

    # ── visão ──
    def _set_modo(self, modo):
        if modo == self._modo and self._dados:
            return
        self._modo = modo
        self._refresh_botoes()
        self.pessoa_w.setVisible(modo == "criadas")
        self._iniciar()

    def _refresh_botoes(self):
        self.b_criadas.setObjectName("" if self._modo == "criadas" else "secondary")
        self.b_atrib.setObjectName("secondary" if self._modo == "criadas" else "")
        for b in (self.b_criadas, self.b_atrib):
            b.style().unpolish(b); b.style().polish(b)
        self.pessoa_w.setVisible(self._modo == "criadas")

    # ── etiquetas (filtro; uma OS pode ter várias) ──
    def _carregar_labels(self):
        self.hint.setText("carregando etiquetas…")
        self._wl = ApiWorker(api.get_labels)
        self._wl.ok.connect(self._set_labels)
        self._wl.erro.connect(lambda m: self._set_labels(None))
        self._wl.start()

    def _set_labels(self, labels):
        self._wl = None
        self._labels_loaded = True
        self.cb_etiqueta.blockSignals(True)
        self.cb_etiqueta.clear()
        self.cb_etiqueta.addItem("Todas as etiquetas", None)
        for l in sorted(labels or [], key=lambda x: (x.get("description") or "").lower()):
            self.cb_etiqueta.addItem(l.get("description") or "?", l.get("id"))
        self.cb_etiqueta.setCurrentIndex(0)
        self.cb_etiqueta.blockSignals(False)
        self._iniciar()                            # segue: pessoas → lista

    def _on_etiqueta(self, _idx):
        self._carregar()

    # ── pessoas (filtro de criador) ──
    def _carregar_pessoas(self):
        self.hint.setText("carregando usuários…")
        self._wp = ApiWorker(api.get_pessoas_contas)
        self._wp.ok.connect(self._set_pessoas)
        self._wp.erro.connect(lambda m: (self._set_pessoas(None), self._carregar()))
        self._wp.start()

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
        self.cb_pessoa.setCurrentIndex(sel)        # default = usuário logado
        self.cb_pessoa.blockSignals(False)
        self._carregar()

    def _on_pessoa(self, _idx):
        if self._modo == "criadas":
            self._carregar()

    # ── dados ──
    def _carregar(self):
        self._dt_timer.stop()                       # cancela re-busca pendente (já vamos buscar)
        self.spinner.start()
        self.hint.setText("carregando OS…")
        self.tab.setRowCount(0)
        id_label = self.cb_etiqueta.currentData() if self.cb_etiqueta.count() else None
        de = self.d_de.date().toString("yyyy-MM-dd")
        ate = self.d_ate.date().toString("yyyy-MM-dd")
        _n2i = {v: k for k, v in api.WO_STATUS.items()}      # status é server-side (re-busca por status)
        status_ids = [_n2i[n] for n in self.cb_status.checked_values() if n in _n2i] or None
        if self._modo == "criadas":
            idacc = self.cb_pessoa.currentData() if self.cb_pessoa.count() else None
            self._w = ApiWorker(api.list_minhas_os, "criadas", idacc, id_label, de, ate, status_ids)
        else:
            self._w = ApiWorker(api.list_minhas_os, "atribuidas", None, id_label, de, ate, status_ids)
        self._w.ok.connect(self._set_dados)
        self._w.erro.connect(self._erro)
        self._w.start()

    @slot_seguro
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
        """Status é SERVER-SIDE → lista fixa com todos os status possíveis (preserva marcados)."""
        self.cb_status.set_items(list(api.WO_STATUS.values()))

    def _rebuild_filtros_ativo(self):
        """Repovoa Cliente/Tipo de ativo/Tipo de tarefa (multi; preserva marcados). Usina cascateia."""
        clientes = sorted({d.get("cliente") for d in self._dados
                           if d.get("cliente") and d.get("cliente") != "—"})
        tipos = sorted({d.get("tipo") for d in self._dados
                        if d.get("tipo") and d.get("tipo") != "—"})
        tarefas = sorted({tt for d in self._dados                 # OS pode ter + de 1 tipo (join " / ")
                          for tt in (d.get("tipo_tarefa") or "").split(" / ") if tt})
        self.cb_cliente.set_items(clientes)
        self.cb_tipo.set_items(tipos)
        self.cb_tarefa.set_items(tarefas)
        self._rebuild_usinas()                        # usinas dependem dos clientes marcados

    def _rebuild_usinas(self):
        """Usinas dos clientes marcados (ou todas, se nenhum). Multi; preserva marcadas."""
        clis = self.cb_cliente.checked_values()
        usinas = sorted({d.get("usina") for d in self._dados
                         if d.get("usina") and d.get("usina") != "—"
                         and (not clis or d.get("cliente") in clis)})
        self.cb_usina.set_items(usinas)

    def _on_cliente(self, _idx=0):
        self._rebuild_usinas()
        self._aplica()

    def _on_usina(self, *_):
        # ao filtrar por usina, mostra OS de TODOS os criadores (não só o logado) — troca "Criado por"
        # p/ "Todos os usuários", o que dispara a re-busca (que por sua vez chama _aplica).
        if (self._modo == "criadas" and self.cb_usina.checked_values()
                and self.cb_pessoa.count() and self.cb_pessoa.currentData() != "TODOS"):
            self.cb_pessoa.setCurrentIndex(0)     # "Todos os usuários" (item 0) → _on_pessoa → _carregar
        else:
            self._aplica()

    def _on_data_change(self, *_):
        self._dt_timer.start()              # debounce → re-busca o período no servidor (_carregar)

    def _on_status_change(self, *_):
        self._aplica()                      # feedback IMEDIATO (filtra o que já está carregado)
        self._dt_timer.start()              # + re-busca server-side p/ completar sob o teto (debounced)

    def _buscar_os(self):
        """Busca DIRETA pelo nº da OS (ignora filtros/período) → abre o detalhe."""
        folio = (self.busca_os.text() or "").strip()
        if not folio:
            return
        self.spinner.start(); self.hint.setText(f"procurando OS nº {folio}…")
        self._wb = ApiWorker(api._wo_id_por_folio, folio)
        self._wb.ok.connect(lambda wid, f=folio: self._achou_os(wid, f))
        self._wb.erro.connect(lambda m: (self.spinner.stop(), self.hint.setText("⚠ " + str(m))))
        self._wb.start()

    def _achou_os(self, wid, folio):
        self.spinner.stop(); self.hint.setText("")
        if wid:
            self.busca_os.clear()                # limpa o buscador assim que abre o card
            abrir_os_detalhe(self, wid, folio)
        else:
            QMessageBox.information(self, "OS não encontrada", f"Não achei nenhuma OS com o nº {folio}.")

    def _limpar_filtros(self):
        """Limpa tudo (multi-seleção + busca + etiqueta) e re-busca do servidor (status/etiqueta são
        server-side)."""
        for cb in (self.cb_status, self.cb_cliente, self.cb_usina, self.cb_tipo, self.cb_tarefa):
            cb.clear_checks()
        self.busca_no.blockSignals(True); self.busca_no.clear(); self.busca_no.blockSignals(False)
        self.cb_etiqueta.blockSignals(True); self.cb_etiqueta.setCurrentIndex(0); self.cb_etiqueta.blockSignals(False)
        self._carregar()

    @slot_seguro
    def _aplica(self):
        stats = self.cb_status.checked_values()      # status TAMBÉM client-side → nunca mostra status desmarcado
        clis = self.cb_cliente.checked_values()      # (a re-busca server-side é só p/ completar sob o teto)
        usis = self.cb_usina.checked_values()
        tips = self.cb_tipo.checked_values()
        tars = self.cb_tarefa.checked_values()
        no = self.busca_no.text().strip().lower()

        def _busca(d):                       # busca AMPLA: nº + qualquer campo de texto
            if not no:
                return True
            campos = [str(d.get("folio") or ""), d.get("cliente") or "", d.get("usina") or "",
                      d.get("ativo") or "", d.get("descricao") or "", d.get("status") or "",
                      d.get("tipo_tarefa") or "",
                      ", ".join(e.get("nome") or "" for e in (d.get("etiquetas") or []))]
            return any(no in c.lower() for c in campos)
        linhas = [d for d in self._dados
                  if (not stats or d.get("status") in stats)
                  and (not clis or d.get("cliente") in clis)
                  and (not usis or d.get("usina") in usis)
                  and (not tips or d.get("tipo") in tips)
                  and (not tars or any(t in tars for t in (d.get("tipo_tarefa") or "").split(" / ")))
                  and _busca(d)]
        self._linhas = linhas                # guarda TODAS as casadas p/ exportar (não só as exibidas)
        self.tab.setRowCount(0)
        self.tab.setUpdatesEnabled(False)    # 1 repaint só no fim (não a cada linha) → menos travamento
        for d in linhas[:MAX_LINHAS]:        # teto de render — 2000 cellWidgets travam a UI (~15s)
            r = self.tab.rowCount(); self.tab.insertRow(r)
            it_no = QTableWidgetItem(str(d.get("folio") or "—"))
            it_no.setData(Qt.ItemDataRole.UserRole, d.get("id"))   # id_work_order p/ o detalhe
            it_no.setForeground(QBrush(QColor("#98c838")))   # verde-grid, sem sublinhado
            f = it_no.font(); f.setBold(True); it_no.setFont(f)
            it_no.setToolTip("Clique para ver Data do Evento, Notas e Subtarefas")
            self.tab.setItem(r, 0, it_no)
            self.tab.setItem(r, 1, QTableWidgetItem(d.get("cliente") or "—"))
            self.tab.setItem(r, 2, QTableWidgetItem(d.get("usina") or "—"))
            self.tab.setItem(r, 3, QTableWidgetItem(d.get("ativo") or ""))
            self.tab.setItem(r, 4, QTableWidgetItem(d.get("descricao") or "—"))
            self.tab.setItem(r, 5, QTableWidgetItem(_data_br(d.get("data"))))          # Data de Criação
            self.tab.setItem(r, 6, QTableWidgetItem(_data_br(d.get("event_date"))))    # Data do Evento
            self.tab.setItem(r, 7, QTableWidgetItem(_data_br(d.get("data_fim"))))      # Data Fim
            self.tab.setCellWidget(r, 8, _status_widget(d.get("status")))             # Status (card centralizado)
            etq = ", ".join(e.get("nome") or "" for e in (d.get("etiquetas") or []) if e.get("nome"))
            it_etq = QTableWidgetItem(etq)
            it_etq.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if etq:
                it_etq.setToolTip(etq)
            self.tab.setItem(r, 9, it_etq)
        self.tab.setUpdatesEnabled(True)
        n = len(linhas)
        if n > MAX_LINHAS:
            extra = (f"  ·  ⚠ exibindo {MAX_LINHAS} de {n} — estreite o filtro/criador "
                     "(a exportação inclui todas)")
        elif len(self._dados) >= api.HISTORICO_CAP:
            extra = f"  ·  ⚠ teto de {api.HISTORICO_CAP} atingido — estreite o período/criador"
        elif n != len(self._dados):
            extra = f"  ·  {len(self._dados)} no período"
        else:
            extra = ""
        self.hint.setText(f"{min(n, MAX_LINHAS)} OS exibidas{extra}")

    def _abrir_detalhe(self, row, col):
        """Clique no nº da OS (col 0) → dialog com Data do Evento, Notas e Subtarefas."""
        if col != 0:
            return
        it = self.tab.item(row, 0)
        wid = it.data(Qt.ItemDataRole.UserRole) if it else None
        if wid:
            abrir_os_detalhe(self, wid, it.text())

    def _exportar(self):
        """Exporta as OS exibidas (já filtradas) p/ CSV."""
        headers = ["Nº", "Cliente", "Usina", "Ativo", "Descrição", "Data de Criação", "Data do Evento",
                   "Data Fim", "Status", "Tipo de tarefa", "Etiquetas"]
        rows = [[d.get("folio") or "", d.get("cliente") or "", d.get("usina") or "",
                 d.get("ativo") or "", d.get("descricao") or "", _data_br(d.get("data")),
                 _data_br(d.get("event_date")), _data_br(d.get("data_fim")), d.get("status") or "",
                 d.get("tipo_tarefa") or "",
                 ", ".join(e.get("nome") or "" for e in (d.get("etiquetas") or []) if e.get("nome"))]
                for d in self._linhas]
        de = self.d_de.date().toString("yyyy-MM-dd"); ate = self.d_ate.date().toString("yyyy-MM-dd")
        exportar_csv(self, headers, rows, sugestao=f"historico_os_{de}_a_{ate}.csv",
                     titulo="Exportar histórico de OS")
