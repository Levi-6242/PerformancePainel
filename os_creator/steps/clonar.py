"""Diálogo 'Clonar OS': lê uma OS de referência (TODAS as tarefas — ativos, tipos, descrições,
subtarefas e etiquetas) e cria uma nova OS igual, com TODAS as tarefas. Cada tarefa tem sua
PRÓPRIA data/hora programada; ao selecionar uma tarefa, suas subtarefas aparecem embaixo, com
checkbox (incluir/manter), texto editável e botão para excluir. Observação única, responsável
escolhido na hora. Usa os ativos direto do catálogo (qualquer tipo)."""
import datetime as _dt
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QTextEdit,
                             QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
                             QCheckBox, QPushButton, QMessageBox, QDateTimeEdit, QDateEdit,
                             QLineEdit, QScrollArea, QWidget, QCompleter)
from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtCore import QDate, QTime, QDateTime, Qt, QSize
import api
from workers import ApiWorker
from steps.searchcombo import tornar_pesquisavel
from steps.ui import QSS_FORM, Card, campo, rotulo, Linha, icone_pix, GREEN_INK

_SEL = "— selecione —"


def abrir_clonar_os(parent, id_work_order, folio=None):
    """Abre o clone como janela avulsa (embrulha o painel num QDialog)."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(f"Clonar OS {folio or id_work_order}")
    dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint)
    dlg.setMinimumSize(720, 800); dlg.setSizeGripEnabled(True)
    lay = QVBoxLayout(dlg); lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(ClonarOSDialog(dlg, id_work_order, folio, on_voltar=dlg.accept))
    dlg.exec()


class ClonarOSDialog(QWidget):
    """Painel de clonagem — embutível (aba Criar OS) ou dentro de um QDialog (janela avulsa).
    `on_voltar` é chamado ao Cancelar ou após criar o clone."""
    def __init__(self, parent, id_work_order, folio=None, on_voltar=None):
        super().__init__(parent)
        self._on_voltar = on_voltar
        self._wo = id_work_order
        self._dados = None
        self._editors = {}                 # índice da tarefa -> QDateTimeEdit (só p/ tarefas com ativo)
        self._building = False             # guarda p/ ignorar itemChanged durante a montagem da tabela
        self._catalogo = api.load_assets_cached() or []   # p/ trocar o ativo (mesmo cliente+usina)
        self._loading_edit = False         # guard ao popular os editores de ativo/descrição
        self._wread = self._wresp = self._wc = self._wupd = self._wall = None
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint)
        self.setMinimumWidth(560)          # SÓ largura — min de altura empurrava o rodapé p/ fora quando embutido
        self.setStyleSheet(QSS_FORM)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(); scroll.setWidget(body); outer.addWidget(scroll)
        lay = QVBoxLayout(body); lay.setContentsMargins(18, 14, 18, 6); lay.setSpacing(14)

        # ── Card 1: OS de referência (resumo + tabela de tarefas + data em massa) ──
        self.resumo = QLabel("Lendo a OS de referência…"); self.resumo.setObjectName("uiAjuda")
        self.resumo.setWordWrap(True)
        self.tbl = QTableWidget(0, 4)
        self.tbl.setHorizontalHeaderLabels(["Clonar ativo", "Tarefa", "Subt.", "Data/hora programada"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.verticalHeader().setDefaultSectionSize(46)   # cabe o editor de data de 40px sem estourar
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.itemSelectionChanged.connect(self._sel_changed)
        self.tbl.itemChanged.connect(self._task_check_changed)
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)   # ativo com largura fixa (elide) — não empurra a data
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)      # data em célula não mede em ResizeToContents
        self.tbl.setColumnWidth(0, 340); self.tbl.setColumnWidth(3, 200)
        self.tbl.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tbl.setMinimumHeight(180)
        self.bulk_date = QDateEdit(); self.bulk_date.setCalendarPopup(True)
        self.bulk_date.setDisplayFormat("dd/MM/yyyy"); self.bulk_date.setDate(QDate.currentDate())
        b_data = QPushButton("Aplicar data"); b_data.setObjectName("secondary")
        b_data.setToolTip("Define a DATA (dia/mês/ano) de todas as tarefas; mantém o horário de cada uma")
        b_data.clicked.connect(lambda: self._set_todas_data(self.bulk_date.date()))
        b_manha = QPushButton("Manhã (07:00)"); b_manha.setObjectName("secondary")
        b_manha.setToolTip("Define o horário de TODAS as tarefas para 07:00")
        b_manha.clicked.connect(lambda: self._set_todas_hora(7, 0))
        b_tarde = QPushButton("Tarde (13:00)"); b_tarde.setObjectName("secondary")
        b_tarde.setToolTip("Define o horário de TODAS as tarefas para 13:00")
        b_tarde.clicked.connect(lambda: self._set_todas_hora(13, 0))
        b_mes = QPushButton("Avançar 1 mês"); b_mes.setObjectName("secondary")
        b_mes.setToolTip("Adia a data de cada tarefa em 1 mês")
        b_mes.clicked.connect(self._avancar_mes)
        c_ref = Card("copy", f"OS de referência {folio}".rstrip() if folio else "OS de referência")
        c_ref.add(self.resumo)
        c_ref.add(rotulo("Tarefas / ativos que serão clonados",
                         extra="(desmarque um ativo p/ não clonar; clique na linha p/ editar as subtarefas)"))
        c_ref.add(self.tbl, stretch=1)
        drow = QHBoxLayout(); drow.setSpacing(8)
        for w in (self.bulk_date, b_data, b_manha, b_tarde, b_mes):
            drow.addWidget(w)
        drow.addStretch(1)
        c_ref.add(drow)
        lay.addWidget(c_ref)

        # ── Card 2: Tarefa selecionada (trocar ativo/descrição + subtarefas) ──
        self.ed_ativo = QComboBox(); self.ed_ativo.setEditable(True)
        self.ed_ativo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.ed_ativo.setToolTip("Trocar o ativo desta tarefa — mesmo cliente e usina (digite p/ filtrar)")
        comp = self.ed_ativo.completer()
        if comp is not None:
            comp.setFilterMode(Qt.MatchFlag.MatchContains)
            comp.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.ed_ativo.currentIndexChanged.connect(self._on_edit_ativo)
        self.ed_desc = QLineEdit(); self.ed_desc.setToolTip("Editar a descrição desta tarefa")
        self.ed_desc.textEdited.connect(self._on_edit_desc)
        self.sub_titulo = QLabel("Subtarefas"); self.sub_titulo.setObjectName("uiCampoLabel")
        self.b_upd = QPushButton("Atualizar do modelo"); self.b_upd.setObjectName("secondary")
        self.b_upd.setToolTip("Re-seleciona no Fracttal o modelo de tarefa do mesmo nome p/ este "
                              "ativo e substitui as subtarefas pela versão atual do modelo")
        self.b_upd.setEnabled(False); self.b_upd.clicked.connect(self._atualizar_modelo)
        self.b_upd_all = QPushButton("Atualizar todas do modelo"); self.b_upd_all.setObjectName("secondary")
        self.b_upd_all.setToolTip("Re-seleciona no Fracttal o modelo de cada ativo e substitui as "
                                  "subtarefas de TODAS as tarefas pela versão atual (sobrescreve edições)")
        self.b_upd_all.setEnabled(False); self.b_upd_all.clicked.connect(self._atualizar_todas)
        self.sub_box = QWidget(); self.sub_box.setObjectName("uiGroup")
        self.sub_layout = QVBoxLayout(self.sub_box)
        self.sub_layout.setContentsMargins(0, 0, 0, 0); self.sub_layout.setSpacing(6)
        self.sub_layout.addStretch(1)
        self.sub_scroll = QScrollArea(); self.sub_scroll.setObjectName("uiFlat")
        self.sub_scroll.setWidgetResizable(True)
        self.sub_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.sub_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sub_scroll.setWidget(self.sub_box)
        self.sub_scroll.setMinimumHeight(64); self.sub_scroll.setMaximumHeight(130)   # card mais baixo
        c_sel = Card("box", "Tarefa selecionada")
        c_sel.add(Linha(campo("Ativo", self.ed_ativo), campo("Descrição", self.ed_desc)))
        subhdr = QHBoxLayout(); subhdr.setSpacing(6)
        subhdr.addWidget(self.sub_titulo, 1); subhdr.addWidget(self.b_upd); subhdr.addWidget(self.b_upd_all)
        c_sel.add(subhdr)
        c_sel.add(self.sub_scroll)
        lay.addWidget(c_sel)

        # ── Card 3: Detalhes ──
        self.obs = QTextEdit(); self.obs.setFixedHeight(104)   # mais alto p/ ler a observação
        self.chk_etiq = QCheckBox("Clonar etiquetas"); self.chk_etiq.setEnabled(False)
        c_det = Card("file", "Detalhes")
        c_det.add(campo("Observação", self.obs, extra="(opcional — vale para todas as tarefas)"))
        c_det.add(self.chk_etiq)

        # ── Card 4: Responsável ──
        self.cb_resp = QComboBox(); self.cb_resp.addItem("carregando…", None)
        tornar_pesquisavel(self.cb_resp)
        c_resp = Card("users", "Responsável")
        c_resp.add(campo("Responsável", self.cb_resp, obrig=True, extra="(digite p/ pesquisar)"))
        lay.addWidget(Linha(c_det, c_resp, quebra=820))     # Detalhes | Responsável lado a lado

        # ── ações no FIM do conteúdo (rolando) — sem footer fixo escondendo os cards de baixo ──
        row = QHBoxLayout(); row.setContentsMargins(0, 6, 0, 2); row.setSpacing(10)
        b_cancel = QPushButton("Cancelar"); b_cancel.setObjectName("secondary"); b_cancel.clicked.connect(self.reject)
        self.btn = QPushButton("Criar clone"); self.btn.setObjectName("btnPrimary")
        self.btn.setIcon(QIcon(icone_pix("copy", GREEN_INK, 16))); self.btn.setIconSize(QSize(16, 16))
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.setEnabled(False); self.btn.clicked.connect(self._criar)
        row.addStretch(1); row.addWidget(b_cancel); row.addWidget(self.btn)
        lay.addLayout(row)
        self.hint = QLabel("carregando OS de referência…"); self.hint.setObjectName("uiAjuda")
        lay.addWidget(self.hint, 0, Qt.AlignmentFlag.AlignRight)

        self._carregar()
        self._carregar_resp()

    def _voltar(self):
        if self._on_voltar:
            self._on_voltar()

    def accept(self):        # compat: sucesso → volta / fecha
        self._voltar()

    def reject(self):        # compat: Cancelar → volta / fecha
        self._voltar()

    # ── carga ──
    def _carregar(self):
        self._wread = ApiWorker(api.get_os_para_clonar, self._wo)
        self._wread.ok.connect(self._set_dados)
        self._wread.erro.connect(lambda m: self.hint.setText("⚠ " + m))
        self._wread.start()

    def _carregar_resp(self):
        self._wresp = ApiWorker(api.get_responsaveis)
        self._wresp.ok.connect(self._set_resp)
        self._wresp.erro.connect(lambda m: self.cb_resp.setItemText(0, "⚠ falha ao listar"))
        self._wresp.start()

    def _set_resp(self, pessoas):
        self._wresp = None
        self.cb_resp.clear(); self.cb_resp.addItem(_SEL, None)
        for p in sorted(pessoas or [], key=lambda x: (x.get("name") or "").lower()):
            self.cb_resp.addItem(p.get("name") or p.get("code") or "?", p.get("id_personnel"))

    def _avancar_mes(self):
        """Atalho: avança a data/hora de cada tarefa 1 mês para frente (a partir da própria data)."""
        for de in self._editors.values():
            de.setDateTime(de.dateTime().addMonths(1))

    def _set_todas_hora(self, h, m):
        """Define o horário (h:m) de TODAS as tarefas em massa, mantendo a data de cada uma."""
        for de in self._editors.values():
            dt = de.dateTime(); dt.setTime(QTime(h, m)); de.setDateTime(dt)

    def _set_todas_data(self, qdate):
        """Define a DATA de TODAS as tarefas em massa, mantendo o horário de cada uma."""
        for de in self._editors.values():
            dt = de.dateTime(); dt.setDate(qdate); de.setDateTime(dt)

    @staticmethod
    def _iso_para_qdatetime(iso):
        """ISO UTC (event_date original) → QDateTime no fuso de Brasília (UTC-3), p/ exibir. None se vazio."""
        if not iso:
            return None
        try:
            d = _dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        except ValueError:
            return None
        if d.tzinfo is None:
            d = d.replace(tzinfo=_dt.timezone.utc)
        d = d.astimezone(_dt.timezone(_dt.timedelta(hours=-3)))
        return QDateTime(QDate(d.year, d.month, d.day), QTime(d.hour, d.minute))

    def _mk_item(self, txt, vermelho=False, center=False):
        it = QTableWidgetItem(txt)
        if vermelho:
            it.setForeground(QColor("#dc2626"))
        if center:
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return it

    def _set_dados(self, d):
        self._wread = None
        self._dados = d or {}
        tarefas = self._dados.get("tarefas") or []
        com_ativo = [t for t in tarefas if isinstance(t.get("asset"), dict) and t["asset"].get("id")]

        self._editors = {}
        self._building = True               # ignora itemChanged enquanto monta a tabela
        self.tbl.setRowCount(len(tarefas))
        for i, t in enumerate(tarefas):
            tem = isinstance(t.get("asset"), dict) and t["asset"].get("id")
            nome = (t.get("asset") or {}).get("label") or t.get("ativo_nome") or t.get("code") or "?"
            nsub = len([s for s in (t.get("subtarefas") or []) if s.get("_keep", True)])
            it0 = self._mk_item(nome if tem else ("⚠ " + nome), vermelho=not tem)
            if tem:                          # checkbox p/ incluir/desconsiderar o ativo
                it0.setFlags(it0.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it0.setCheckState(Qt.CheckState.Unchecked if t.get("_skip") else Qt.CheckState.Checked)
            self.tbl.setItem(i, 0, it0)
            self.tbl.setItem(i, 1, self._mk_item(f"{t.get('tipo') or 'Corretiva'} · {t.get('descricao') or '—'}",
                                                 vermelho=not tem))
            self.tbl.setItem(i, 2, self._mk_item(str(nsub), center=True))
            if tem:
                de = QDateTimeEdit(); de.setCalendarPopup(True)
                de.setDisplayFormat("dd/MM/yyyy HH:mm")
                qdt = self._iso_para_qdatetime(t.get("event_date_orig"))
                de.setDateTime(qdt or QDateTime(QDate.currentDate(), QTime(8, 0)))
                de.setEnabled(not t.get("_skip"))
                self.tbl.setCellWidget(i, 3, de)
                self._editors[i] = de
            else:
                self.tbl.setItem(i, 3, self._mk_item("ignorada", vermelho=True, center=True))
        hh2 = self.tbl.horizontalHeader()           # reaplica os modos (senão a coluna do ativo estica)
        hh2.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hh2.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh2.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh2.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.tbl.setColumnWidth(0, 340); self.tbl.setColumnWidth(3, 200)
        self._building = False

        self.obs.setPlainText(self._dados.get("notas") or "")
        n = len(self._dados.get("etiqueta_ids") or [])
        self.chk_etiq.setText(f"Clonar etiquetas ({n})")
        self.chk_etiq.setEnabled(n > 0); self.chk_etiq.setChecked(n > 0)

        self.b_upd_all.setEnabled(bool(com_ativo))
        if not com_ativo:
            self.resumo.setText("<span style='color:#dc2626'>Nenhuma tarefa desta OS tem ativo no "
                                "catálogo carregado — recarregue os ativos no Criar OS e tente de novo.</span>")
            self.btn.setEnabled(False); self.hint.setText("")
            return
        self._atualiza_resumo()
        self.hint.setText("desmarque um ativo p/ não clonar; clique na linha p/ editar as subtarefas")
        if self.tbl.rowCount():
            self.tbl.selectRow(0)

    def _atualiza_resumo(self):
        """Recalcula o resumo + habilita 'Criar' conforme os ativos marcados (não-_skip, com ativo)."""
        tarefas = (self._dados or {}).get("tarefas") or []
        def tem(t):
            return isinstance(t.get("asset"), dict) and t["asset"].get("id")
        incl = [t for t in tarefas if tem(t) and not t.get("_skip")]
        n_excl = sum(1 for t in tarefas if tem(t) and t.get("_skip"))
        n_sem = sum(1 for t in tarefas if not tem(t))
        if not incl:
            self.resumo.setText("<span style='color:#dc2626'>Nenhum ativo marcado para clonar.</span>")
            self.btn.setEnabled(False); return
        n_ativos = len({(t.get("asset") or {}).get("code") or t.get("code") for t in incl})
        total_sub = sum(len(t.get("subtarefas") or []) for t in incl)
        msg = (f"Serão clonadas <b>{len(incl)} tarefa(s)</b> em <b>{n_ativos} ativo(s)</b> "
               f"e <b>{total_sub} subtarefa(s)</b>, em <b>uma nova OS</b>.")
        extra = []
        if n_excl:
            extra.append(f"{n_excl} desmarcada(s)")
        if n_sem:
            extra.append(f"{n_sem} sem ativo")
        if extra:
            msg += f"<br><span style='color:#8a90a2'>{' · '.join(extra)} não entram.</span>"
        self.resumo.setText(msg)
        self.btn.setEnabled(True)

    def _task_check_changed(self, item):
        """Marcar/desmarcar o checkbox do ativo (col 0) inclui/desconsidera a tarefa no clone."""
        if self._building or item is None or item.column() != 0:
            return
        r = item.row()
        ts = (self._dados or {}).get("tarefas") or []
        if not (0 <= r < len(ts)):
            return
        checked = item.checkState() == Qt.CheckState.Checked
        ts[r]["_skip"] = not checked
        de = self._editors.get(r)
        if de is not None:
            de.setEnabled(checked)
        self._atualiza_resumo()

    # ── subtarefas da tarefa selecionada ──
    def _tarefa_sel(self):
        r = self.tbl.currentRow()
        ts = (self._dados or {}).get("tarefas") or []
        return ts[r] if 0 <= r < len(ts) else None

    def _sel_changed(self):
        self._montar_subtarefas(self._tarefa_sel())

    def _montar_subtarefas(self, t):
        while self.sub_layout.count():                  # limpa o painel
            item = self.sub_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        tem = bool(t and isinstance(t.get("asset"), dict) and t["asset"].get("id"))
        self.b_upd.setEnabled(tem)
        self._popular_editores(t, tem)
        if not t:
            self.sub_titulo.setText("<b>Subtarefas</b>")
            return
        nome = (t.get("asset") or {}).get("label") or t.get("ativo_nome") or t.get("code") or "?"
        self.sub_titulo.setText(f"<b>Subtarefas</b> <span style='color:#8a90a2'>· {nome} "
                                "(desmarque p/ não incluir, ou exclua)</span>")
        subs = t.get("subtarefas") or []
        if not subs:
            lbl = QLabel("(sem subtarefas — será criada com 'Procedimento')"); lbl.setObjectName("hint")
            self.sub_layout.addWidget(lbl)
        for s in subs:
            self.sub_layout.addWidget(self._sub_row(s))
        self.sub_layout.addStretch(1)

    # ── editar ativo (mesmo cliente/usina) + descrição da tarefa selecionada ──
    def _popular_editores(self, t, tem):
        """Preenche o combo de ativo (assets do mesmo cliente+usina) e a descrição da tarefa."""
        self._loading_edit = True
        self.ed_ativo.clear(); self.ed_desc.clear()
        if not t:
            self.ed_ativo.setEnabled(False); self.ed_desc.setEnabled(False)
            self._loading_edit = False
            return
        self.ed_desc.setEnabled(True); self.ed_desc.setText(t.get("descricao") or "")
        if tem:
            self.ed_ativo.setEnabled(True)
            cur = t.get("asset") or {}
            cli, usi = cur.get("cliente"), cur.get("usina")
            cands = sorted([a for a in self._catalogo
                            if a.get("cliente") == cli and a.get("usina") == usi],
                           key=lambda a: (a.get("label") or a.get("code") or "").lower())
            if cur.get("id") and not any(a.get("id") == cur.get("id") for a in cands):
                cands.insert(0, cur)
            sel = 0
            for i, a in enumerate(cands):
                self.ed_ativo.addItem(a.get("label") or a.get("code") or "?", a)
                if a.get("id") == cur.get("id"):
                    sel = i
            self.ed_ativo.setCurrentIndex(sel)
        else:
            self.ed_ativo.setEnabled(False)
            self.ed_ativo.addItem("(tarefa sem ativo — não clonável)", None)
        self._loading_edit = False

    def _on_edit_ativo(self, *_):
        if self._loading_edit:
            return
        t = self._tarefa_sel()
        a = self.ed_ativo.currentData()
        if not t or not isinstance(a, dict):
            return
        t["asset"] = a
        t["code"] = a.get("code") or t.get("code")
        t["ativo_nome"] = a.get("label") or a.get("code") or t.get("ativo_nome")
        it0 = self.tbl.item(self.tbl.currentRow(), 0)
        if it0:
            self._building = True
            it0.setText(a.get("label") or a.get("code") or "?")
            self._building = False
        self._atualiza_resumo()

    def _on_edit_desc(self, txt):
        if self._loading_edit:
            return
        t = self._tarefa_sel()
        if not t:
            return
        t["descricao"] = txt
        it1 = self.tbl.item(self.tbl.currentRow(), 1)
        if it1:
            self._building = True
            it1.setText(f"{t.get('tipo') or 'Corretiva'} · {txt or '—'}")
            self._building = False

    def _sub_row(self, s):
        row = QWidget(); h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0); h.setSpacing(6)
        chk = QCheckBox(); chk.setChecked(s.get("_keep", True))
        chk.setToolTip("Incluir esta subtarefa no clone")
        le = QLineEdit(s.get("description") or "")
        le.setEnabled(s.get("_keep", True))
        tipo = s.get("task_form_item_type_description") \
            or ("Texto" if (s.get("id_task_form_item_type") or 1) == 1 else "")
        if tipo:
            le.setToolTip(f"Tipo: {tipo}")
        le.textChanged.connect(lambda txt, s=s: s.__setitem__("description", txt))
        chk.toggled.connect(lambda v, s=s, le=le: self._on_keep(s, le, v))
        b_del = QPushButton("Excluir"); b_del.setObjectName("secondary"); b_del.setFixedWidth(70)
        b_del.setToolTip("Remover esta subtarefa do clone")
        b_del.clicked.connect(lambda _=False, s=s: self._del_sub(s))
        h.addWidget(chk); h.addWidget(le, 1); h.addWidget(b_del)
        return row

    def _on_keep(self, s, le, v):
        s["_keep"] = v
        le.setEnabled(v)
        self._refresh_count(self.tbl.currentRow(), self._tarefa_sel())

    def _del_sub(self, s):
        t = self._tarefa_sel()
        if t and s in (t.get("subtarefas") or []):
            t["subtarefas"].remove(s)
            self._montar_subtarefas(t)
            self._refresh_count(self.tbl.currentRow(), t)

    def _refresh_count(self, r, t):
        if t is None or r is None or r < 0:
            return
        it = self.tbl.item(r, 2)
        if it:
            it.setText(str(len([s for s in (t.get("subtarefas") or []) if s.get("_keep", True)])))

    # ── atualizar subtarefas a partir do modelo do ativo ──
    def _atualizar_modelo(self):
        t = self._tarefa_sel()
        if not (t and isinstance(t.get("asset"), dict) and t["asset"].get("id")):
            QMessageBox.warning(self, "Atualizar", "Selecione uma tarefa com ativo."); return
        self.b_upd.setEnabled(False)
        self.hint.setText("buscando as subtarefas do modelo no Fracttal…")
        self._wupd = ApiWorker(api.get_template_subtarefas, t["asset"], t.get("descricao") or "")
        self._wupd.ok.connect(lambda res, t=t: self._upd_ok(t, res))
        self._wupd.erro.connect(self._upd_err)
        self._wupd.start()

    def _upd_ok(self, t, res):
        self._wupd = None
        r = res or {}
        if r.get("achou"):
            subs = r.get("subtarefas") or []
            for s in subs:
                s["_keep"] = True
            t["subtarefas"] = subs
            if self._tarefa_sel() is t:
                self._montar_subtarefas(t)
            self._refresh_count(self.tbl.currentRow(), t)
            self.hint.setText(f"subtarefas atualizadas do modelo ({len(subs)}).")
        else:
            self.b_upd.setEnabled(True)
            QMessageBox.information(self, "Atualizar do modelo",
                                    r.get("erro") or "Não encontrei um modelo com esse nome para o ativo.")
            self.hint.setText("")

    def _upd_err(self, m):
        self._wupd = None
        self.b_upd.setEnabled(True); self.hint.setText("")
        QMessageBox.critical(self, "Atualizar do modelo", m)

    def _atualizar_todas(self):
        """Atualiza as subtarefas de TODAS as tarefas (com ativo) a partir dos modelos do Fracttal."""
        tarefas = (self._dados or {}).get("tarefas") or []
        com_ativo = [t for t in tarefas if isinstance(t.get("asset"), dict) and t["asset"].get("id")]
        if not com_ativo:
            return
        if QMessageBox.question(self, "Atualizar todas do modelo",
                f"Isso substitui as subtarefas de {len(com_ativo)} tarefa(s) pela versão atual do "
                "modelo de cada ativo — quaisquer edições/exclusões manuais serão perdidas.\n\nContinuar?"
                ) != QMessageBox.StandardButton.Yes:
            return
        self.b_upd_all.setEnabled(False); self.b_upd.setEnabled(False); self.btn.setEnabled(False)
        self.hint.setText(f"atualizando {len(com_ativo)} tarefa(s) do modelo… (pode levar alguns segundos)")
        self._wall = ApiWorker(api.atualizar_modelos_subtarefas, tarefas)
        self._wall.ok.connect(self._todas_ok)
        self._wall.erro.connect(self._todas_err)
        self._wall.start()

    def _todas_ok(self, resultados):
        self._wall = None
        tarefas = (self._dados or {}).get("tarefas") or []
        res = resultados if isinstance(resultados, list) else []
        n_ok = n_falha = 0
        falhas = []
        for i, t in enumerate(tarefas):
            r = res[i] if i < len(res) else None
            if not r:                                # tarefa sem ativo
                continue
            if r.get("achou"):
                subs = r.get("subtarefas") or []
                for s in subs:
                    s["_keep"] = True
                t["subtarefas"] = subs
                n_ok += 1
            else:
                n_falha += 1
                falhas.append(t.get("descricao") or t.get("code") or "?")
            it = self.tbl.item(i, 2)                 # atualiza a contagem "Subt." da linha
            if it:
                it.setText(str(len([s for s in (t.get("subtarefas") or []) if s.get("_keep", True)])))
        self._montar_subtarefas(self._tarefa_sel())  # reconstrói o painel da tarefa selecionada
        self._atualiza_resumo()
        self.b_upd_all.setEnabled(True)
        self.hint.setText(f"{n_ok} tarefa(s) atualizada(s) do modelo"
                          + (f"; {n_falha} sem modelo." if n_falha else "."))
        if falhas:
            QMessageBox.information(self, "Atualizar todas do modelo",
                f"{n_ok} atualizada(s). Sem modelo correspondente ({n_falha}):\n- "
                + "\n- ".join(falhas[:12]) + ("\n…" if len(falhas) > 12 else ""))

    def _todas_err(self, m):
        self._wall = None
        self.b_upd_all.setEnabled(True); self.hint.setText("")
        QMessageBox.critical(self, "Atualizar todas do modelo", m)

    # ── criar ──
    def _criar(self):
        tarefas = (self._dados or {}).get("tarefas") or []
        idp = self.cb_resp.currentData()
        brt = _dt.timezone(_dt.timedelta(hours=-3))     # horário escolhido é de Brasília; _iso_z converte p/ UTC
        for i, t in enumerate(tarefas):
            de = self._editors.get(i)
            if de is not None:
                p = de.dateTime().toPyDateTime()
                t["event_date"] = p.replace(tzinfo=brt)
            # só clona as subtarefas marcadas (mantém o texto editado e o tipo preservado)
            t["subtarefas"] = [s for s in (t.get("subtarefas") or []) if s.get("_keep", True)]
        # só os ativos MARCADOS (não-_skip) entram no clone
        clonar = [t for t in tarefas if not t.get("_skip")]
        com_ativo = [t for t in clonar if isinstance(t.get("asset"), dict) and t["asset"].get("id")]
        if not com_ativo:
            QMessageBox.warning(self, "Ativos", "Nenhum ativo marcado para clonar."); return
        if not idp:
            QMessageBox.warning(self, "Responsável", "Escolha o responsável."); return
        nome = self.cb_resp.currentText().strip()
        eids = (self._dados.get("etiqueta_ids") or None) if self.chk_etiq.isChecked() else None
        self.btn.setEnabled(False)
        self.hint.setText(f"criando clone com {len(com_ativo)} tarefa(s)… (pode levar alguns segundos)")
        self._wc = ApiWorker(api.clonar_os, clonar, idp, nome, eids, self.obs.toPlainText().strip())
        self._wc.ok.connect(self._ok)
        self._wc.erro.connect(self._err)
        self._wc.start()

    def _ok(self, res):
        self._wc = None
        self.btn.setEnabled(True)
        r = res or {}
        if r.get("ok"):
            os_ = r.get("os") or {}
            folio = os_.get("wo_folio")
            n = r.get("n_criadas")
            msg = f"OS clonada com sucesso{f' — Nº {folio}' if folio else ''}."
            if n:
                msg += f"\n{n} tarefa(s) recriada(s)."
            if r.get("aviso"):
                msg += f"\n\nObs.: {r['aviso']}"
            QMessageBox.information(self, "Clone criado", msg)
            self.accept()
        else:
            QMessageBox.critical(self, "Erro ao clonar", r.get("erro") or "Falha desconhecida ao clonar.")
            self.hint.setText("")

    def _err(self, m):
        self._wc = None
        self.btn.setEnabled(True); self.hint.setText("")
        QMessageBox.critical(self, "Erro ao clonar", m)
