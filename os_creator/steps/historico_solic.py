"""Histórico de Solicitações — solicitações de serviço, com filtro por CRIADOR (default = usuário
logado, pode trocar p/ outros ou Todos), filtros multi-seleção (Cliente/Usina/Tipo de ativo/Status),
filtro de data (BR) e status colorido. Clique no Nº mostra a descrição; clique na OS ligada abre o
detalhe da OS. Lê via api.list_minhas_solicitacoes."""
from PyQt6.QtCore import Qt, QDate, QSize, QTimer
from PyQt6.QtGui import QColor, QBrush, QShortcut, QKeySequence, QIcon
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
                             QDateEdit, QComboBox, QLineEdit, QSizePolicy, QMessageBox, QTableWidget,
                             QTableWidgetItem, QHeaderView, QAbstractItemView, QDialog, QFrame,
                             QScrollArea)
import api
from workers import ApiWorker, slot_seguro
from steps.os_detalhe import (abrir_os_detalhe, aplicar_geometria_card, _svg, _tile, _person,
                              _AnexoCard, _EXTRA_QSS, DESK)
from steps.checkcombo import CheckableComboBox
from steps.cancelar_solic import abrir_cancelar_solic
from steps.exportar import exportar_csv
from steps.galeria import abrir_galeria
from steps.spinner import Spinner
from steps.ui import QSS_FORM, icone_pix, GREEN, GREEN_INK, MUTED, TEXT, CARD, INPUT, BORDER


def _rgba(hexc, a):
    h = hexc.lstrip("#")
    return f"rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{a})"


# selo de status (tons escuros p/ o card premium) — sem lilás
_ST_DARK = {"Aberta": "#F0B341", "Aprovada": DESK, "OS em processo": DESK, "OS em verificação": DESK,
            "Concluída": GREEN, "OS concluída": GREEN, "Resolvida com OS": GREEN, "Resolvida sem OS": GREEN,
            "Cancelada": "#F5766B", "Rejeitada": "#F5766B"}

# cores vivas do card de status na TABELA (mesma paleta do histórico de OS)
_ST_VIVO = {"Aberta": "#F5A623", "Aprovada": "#4A9EF5", "OS em processo": "#4A9EF5",
            "OS em verificação": "#35C1B8", "Concluída": "#48D07A", "OS concluída": "#48D07A",
            "Resolvida com OS": "#48D07A", "Resolvida sem OS": "#48D07A",
            "Cancelada": "#F5766B", "Rejeitada": "#F5766B"}


def _status_solic_widget(status):
    """Card arredondado (8px) de status, cor viva, centralizado — cellWidget da tabela."""
    w = QWidget(); w.setStyleSheet("background:transparent;")
    h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.setAlignment(Qt.AlignmentFlag.AlignCenter)
    if not status:
        return w
    c = _ST_VIVO.get(status)
    pill = QLabel(status)
    if c:
        pill.setStyleSheet(f"color:{c};background:{_rgba(c, 0.16)};border:1px solid {_rgba(c, 0.42)};"
                           "border-radius:8px;padding:4px 12px;font-size:12px;font-weight:700;")
    else:
        pill.setStyleSheet("color:#c4cbdb;background:#1A2337;border:1px solid #2A3550;"
                           "border-radius:8px;padding:4px 12px;font-size:12px;font-weight:600;")
    h.addWidget(pill)
    return w


class _OsLigadaCard(QFrame):
    """Stat clicável 'OS ligada' (abre o detalhe da OS). Sem OS → cinza, não-clicável."""
    def __init__(self, folio, on_click):
        super().__init__()
        self._cb = on_click if folio else None
        self.setObjectName("card")
        if folio:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setStyleSheet(f"QFrame#card:hover{{border-color:{DESK};}}")
        v = QVBoxLayout(self); v.setContentsMargins(16, 14, 16, 14); v.setSpacing(5)
        top = QHBoxLayout(); top.setSpacing(9)
        top.addWidget(_tile("file", DESK, _rgba(DESK, 0.14), 26, 15))
        lab = QLabel("OS LIGADA"); lab.setStyleSheet(f"color:{MUTED};font-size:11px;font-weight:700;"
                                                     "letter-spacing:0.8px;background:transparent;")
        top.addWidget(lab); top.addStretch(1); v.addLayout(top)
        big = QLabel(f"OS {folio}" if folio else "—")
        big.setStyleSheet(f"color:{DESK if folio else MUTED};font-size:22px;font-weight:750;background:transparent;")
        note = QLabel("clique para abrir" if folio else "ainda sem OS gerada")
        note.setStyleSheet("color:#6a7488;font-size:11px;background:transparent;")
        v.addWidget(big); v.addWidget(note)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._cb:
            self._cb()
        super().mousePressEvent(e)

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


class SolicitacaoDialog(QDialog):
    """Card de detalhe de uma solicitação (redesign premium, igual ao card da OS): cabeçalho com Nº +
    selo de status, banner do ativo, metadados + card 'OS ligada' clicável, Título/Observação e anexos
    (Imagens × Documentos). Ações: Abrir OS ligada / Cancelar solicitação / Fechar."""
    def __init__(self, parent, d):
        super().__init__(parent)
        self._d = d
        self.cancelou = False
        self._wa = None
        self._anexos = []
        idc = d.get("id_code")
        status = (d.get("status") or "").strip()
        self.setWindowTitle(f"Solicitação Nº {idc}")
        self.setMinimumSize(560, 520)
        self.setStyleSheet(QSS_FORM + _EXTRA_QSS)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        # ── cabeçalho ──
        head = QHBoxLayout(); head.setContentsMargins(18, 15, 14, 13); head.setSpacing(11)
        head.addWidget(_tile("file", GREEN, _rgba(GREEN, 0.14), 34, 17))
        tw = QVBoxLayout(); tw.setSpacing(0)
        n1 = QLabel(f"Solicitação {idc}")
        n1.setStyleSheet(f"color:{TEXT};font-size:19px;font-weight:700;background:transparent;")
        n2 = QLabel("Requisição de serviço"); n2.setStyleSheet(f"color:{MUTED};font-size:12px;background:transparent;")
        tw.addWidget(n1); tw.addWidget(n2); head.addLayout(tw)
        if status:
            c = _ST_DARK.get(status, MUTED)
            bd = QLabel(status)
            bd.setStyleSheet(f"color:{c};background:{_rgba(c,0.14)};border:1px solid {_rgba(c,0.32)};"
                             "border-radius:999px;padding:3px 12px;font-size:12px;font-weight:600;")
            head.addSpacing(4); head.addWidget(bd)
        head.addStretch(1)
        bx = QPushButton(); bx.setObjectName("iconClose"); bx.setFixedSize(34, 34)
        bx.setIcon(QIcon(icone_pix("close", MUTED, 18))); bx.setIconSize(QSize(18, 18))
        bx.setCursor(Qt.CursorShape.PointingHandCursor); bx.clicked.connect(self.reject)
        head.addWidget(bx)
        lay.addLayout(head)
        sep = QFrame(); sep.setFixedHeight(1); sep.setStyleSheet("background:rgba(255,255,255,0.06);")
        lay.addWidget(sep)

        # ── corpo ──
        scroll = QScrollArea(); scroll.setObjectName("uiFlat"); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(); scroll.setWidget(body)
        bl = QVBoxLayout(body); bl.setContentsMargins(18, 16, 18, 14); bl.setSpacing(15)

        # ativo (banner)
        ac = QFrame(); ac.setObjectName("card")
        ah = QHBoxLayout(ac); ah.setContentsMargins(15, 13, 15, 13); ah.setSpacing(13)
        ah.addWidget(_tile("rack", GREEN, _rgba(GREEN, 0.10)))
        al = QLabel(d.get("ativo") or "—"); al.setWordWrap(True)
        al.setStyleSheet(f"color:{TEXT};font-size:16px;font-weight:650;background:transparent;")
        ah.addWidget(al, 1); bl.addWidget(ac)

        # meta + OS ligada
        row = QHBoxLayout(); row.setSpacing(14)
        mc = QFrame(); mc.setObjectName("card")
        mv = QVBoxLayout(mc); mv.setContentsMargins(16, 4, 16, 4); mv.setSpacing(0)
        self._meta(mv, "users", "Cliente", d.get("cliente") or "—")
        self._meta(mv, "grid", "Usina", d.get("usina") or "—")
        self._meta(mv, "cal", "Criada em", _data_br(d.get("data")))
        self._meta(mv, "user", "Criado por", _person(d.get("criado_por")))
        row.addWidget(mc, 3)
        folio = d.get("os_folio") or (d.get("id_work_order") if d.get("id_work_order") else None)
        row.addWidget(_OsLigadaCard(folio, self._abrir_os), 2)
        bl.addLayout(row)

        # título / observação
        bl.addWidget(self._lbl("TÍTULO"))
        tit = QLabel(d.get("descricao_full") or d.get("descricao") or "(sem título)")
        tit.setObjectName("readboxTitle"); tit.setWordWrap(True)
        tit.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bl.addWidget(tit)
        if (d.get("observacao") or "").strip():
            bl.addWidget(self._lbl("OBSERVAÇÃO"))
            obs = QLabel(d["observacao"]); obs.setObjectName("readbox"); obs.setWordWrap(True)
            obs.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            bl.addWidget(obs)

        # anexos (Imagens × Documentos)
        bl.addWidget(self._lbl("ANEXOS DA SOLICITAÇÃO"))
        arow = QHBoxLayout(); arow.setSpacing(12)
        self.card_img = _AnexoCard("image", "Imagens", "prints e fotos",
                                   GREEN, _rgba(GREEN, 0.14), self._abrir_imagens)
        self.card_doc = _AnexoCard("file", "Documentos", "PDF, planilhas",
                                   DESK, _rgba(DESK, 0.14), self._abrir_docs)
        arow.addWidget(self.card_img); arow.addWidget(self.card_doc)
        bl.addLayout(arow)
        bl.addStretch(1)
        lay.addWidget(scroll, 1)

        # ── rodapé ──
        sep2 = QFrame(); sep2.setFixedHeight(1); sep2.setStyleSheet("background:rgba(255,255,255,0.06);")
        lay.addWidget(sep2)
        foot = QHBoxLayout(); foot.setContentsMargins(18, 10, 18, 13); foot.setSpacing(9)
        if folio:
            b_os = QPushButton("Abrir OS ligada"); b_os.setObjectName("pClone")
            b_os.setIcon(QIcon(icone_pix("file", GREEN_INK, 15))); b_os.setIconSize(QSize(15, 15))
            b_os.setCursor(Qt.CursorShape.PointingHandCursor); b_os.clicked.connect(self._abrir_os)
            foot.addWidget(b_os)
        foot.addStretch(1)
        if status not in _NAO_CANCELAVEL and idc is not None:
            b_cancel = QPushButton("Cancelar solicitação"); b_cancel.setObjectName("pDanger")
            b_cancel.clicked.connect(self._cancelar)
            foot.addWidget(b_cancel)
        b_close = QPushButton("Fechar"); b_close.setObjectName("pGhost"); b_close.clicked.connect(self.reject)
        foot.addWidget(b_close)
        lay.addLayout(foot)
        aplicar_geometria_card(self, 726)          # +10% de largura, altura = tela cheia
        self._carregar_anexos(idc)

    # ── helpers de layout ──
    def _lbl(self, txt):
        l = QLabel(txt); l.setObjectName("secLab"); return l

    def _meta(self, mv, icone, rot, val):
        if mv.count():
            ln = QFrame(); ln.setFixedHeight(1); ln.setStyleSheet("background:rgba(255,255,255,0.055);")
            mv.addWidget(ln)
        r = QWidget(); r.setStyleSheet("background:transparent;")
        h = QHBoxLayout(r); h.setContentsMargins(0, 11, 0, 11); h.setSpacing(12)
        h.addWidget(_svg(icone, MUTED, 16))
        k = QLabel(rot); k.setStyleSheet(f"color:{MUTED};font-size:13px;background:transparent;")
        h.addWidget(k)
        if isinstance(val, str):
            v = QLabel(val or "—"); v.setWordWrap(True)
            v.setStyleSheet(f"color:{TEXT};font-weight:600;font-size:13px;background:transparent;")
            h.addStretch(1); h.addWidget(v)
        else:
            h.addWidget(val, 1)
        mv.addWidget(r)

    # ── anexos ──
    def _carregar_anexos(self, idc):
        self._wa = ApiWorker(api.get_solic_anexos, idc)
        self._wa.ok.connect(self._set_anexos); self._wa.erro.connect(lambda *_: None)
        self._wa.start()

    @slot_seguro
    def _set_anexos(self, anexos):
        self._wa = None
        self._anexos = anexos or []
        self.card_img.set_count(sum(1 for a in self._anexos if a.get("is_image")))
        self.card_doc.set_count(sum(1 for a in self._anexos if not a.get("is_image")))

    def _abrir_imagens(self):
        itens = [{"url": a.get("url"), "thumb": None,
                  "descricao": a.get("nome") or ""} for a in self._anexos
                 if a.get("is_image") and a.get("url")]
        if itens:
            abrir_galeria(self, itens, self._d.get("ativo") or "")

    def _abrir_docs(self):
        docs = [a.get("nome") or a.get("value") or "documento" for a in self._anexos if not a.get("is_image")]
        if docs:
            QMessageBox.information(self, "Documentos anexados",
                                    "Documentos desta solicitação:\n\n• " + "\n• ".join(docs))

    def _abrir_os(self):
        if self._d.get("id_work_order"):
            abrir_os_detalhe(self, self._d.get("id_work_order"), self._d.get("os_folio"))

    def _cancelar(self):
        if abrir_cancelar_solic(self, self._d.get("id_code"), self._d.get("id_code")):
            self.cancelou = True
            self.accept()


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
        self.cb_pessoa = QComboBox(); self.cb_pessoa.setMinimumWidth(200)
        self.cb_pessoa.currentIndexChanged.connect(self._on_pessoa)
        row.addWidget(self.cb_pessoa)
        # box 1: buscar solicitação direto pelo nº (ignora filtros)
        self.busca_sol = QLineEdit()
        self.busca_sol.setPlaceholderText("Buscar solicitação pelo nº — ignora filtros")
        self.busca_sol.setMinimumWidth(250); self.busca_sol.setClearButtonEnabled(True)
        self.busca_sol.setToolTip("Digite o número da solicitação e tecle Enter — abre direto.")
        self.busca_sol.addAction(QIcon(icone_pix("search", GREEN, 15)), QLineEdit.ActionPosition.LeadingPosition)
        self.busca_sol.setStyleSheet("QLineEdit{border:1px solid #5c7a2a;}")
        self.busca_sol.returnPressed.connect(self._buscar_sol)
        row.addSpacing(10); row.addWidget(self.busca_sol)
        row.addStretch(1)
        # box 2: aviso de atualização automática
        self.lbl_auto = QLabel("↻ Atualiza a cada 15 min"); self.lbl_auto.setObjectName("hint")
        self.lbl_auto.setToolTip("Com a aba aberta, atualiza sozinho a cada 15 minutos.")
        row.addWidget(self.lbl_auto)
        row.addWidget(QLabel("Buscar"))
        self.busca = QLineEdit(); self.busca.setPlaceholderText("nº, ativo, descrição, status…")
        self.busca.setMaximumWidth(200); self.busca.setClearButtonEnabled(True)
        self.busca.setToolTip("Filtra as solicitações já carregadas por qualquer campo.  [Ctrl+F]")
        # debounce: filtra ~260ms depois de parar de digitar (senão reconstrói a tabela a cada tecla = trava)
        self._busca_timer = QTimer(self); self._busca_timer.setSingleShot(True); self._busca_timer.setInterval(260)
        self._busca_timer.timeout.connect(self._aplica)
        self.busca.textChanged.connect(lambda *_: self._busca_timer.start())
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
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)   # Criada em
        h.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)             # Status (cellWidget)
        h.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)   # OS ligada
        self.tab.setColumnWidth(1, 90)
        self.tab.setColumnWidth(2, 130)
        self.tab.setColumnWidth(3, 150)
        self.tab.setColumnWidth(6, 150)
        self.tab.cellClicked.connect(self._on_cell)
        lay.addWidget(self.tab, 1)

        hrow = QHBoxLayout(); hrow.setSpacing(8)
        self.spinner = Spinner(self)
        hrow.addWidget(self.spinner)
        self.hint = QLabel(""); self.hint.setObjectName("hint")
        hrow.addWidget(self.hint); hrow.addStretch(1)
        lay.addLayout(hrow)
        # auto-atualização a cada 15 min (com a aba visível e sem carga em andamento)
        self._auto = QTimer(self); self._auto.setInterval(15 * 60 * 1000)
        self._auto.timeout.connect(self._auto_refresh)
        self._auto.start()

    def carregar_inicial(self):
        """Toda vez que a aba abre → recarrega (a menos que já haja carga em andamento)."""
        if not self._pessoas_loaded and self._wp is None:
            self.spinner.start()
            self.hint.setText("carregando usuários…")
            self._wp = ApiWorker(api.get_pessoas_contas)
            self._wp.ok.connect(self._set_pessoas)
            self._wp.erro.connect(lambda m: (self._set_pessoas(None), self._carregar()))
            self._wp.start()
        elif self._w is None and self._wp is None:
            self._carregar()

    def _auto_refresh(self):
        if self.isVisible() and self._w is None and self._wp is None:
            self._carregar()

    def _buscar_sol(self):
        """Busca DIRETA pelo nº da solicitação (ignora filtros) → abre o card. Procura nas carregadas."""
        no = (self.busca_sol.text() or "").strip()
        if not no:
            return
        d = next((x for x in self._dados if str(x.get("id_code") or "").strip() == no), None)
        if d:
            self.busca_sol.clear()
            self._mostrar_descricao(d)
        else:
            QMessageBox.information(self, "Solicitação não encontrada",
                f"Não achei a solicitação nº {no} entre as carregadas. Se for de outro criador, "
                "troque em 'Criado por' (ou 'Todos os usuários') e tente de novo.")

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
            self.tab.setCellWidget(r, 6, _status_solic_widget(d.get("status")))   # card de status vivo
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
        dlg = SolicitacaoDialog(self, d)
        dlg.exec()
        if dlg.cancelou:
            self._carregar()          # recarrega p/ refletir o status Cancelada
