"""PCM — cria UMA OS com VÁRIAS tarefas a partir de PLANOS DE TAREFA (MPM/MPA/MPS/MPQ/MPW/MPT/
Handover). Fluxo: marca os ativos → escolhe a FAMÍLIA → 'Carregar planos' → a PRÓPRIA lista de
ativos passa a mostrar, por linha, o PLANO daquela família (combo) + o Nº DE SUBTAREFAS; os ativos
que não têm plano na família ficam destacados. 1 OS = cada ativo marcado vira uma tarefa."""
import datetime as _dt
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtCore import Qt, QDateTime, QDate, QTime
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
                             QLineEdit, QTextEdit, QPushButton, QMessageBox, QDateTimeEdit, QDateEdit,
                             QScrollArea, QDialog, QTableWidget, QTableWidgetItem, QHeaderView,
                             QAbstractItemView, QCheckBox)
import api
from workers import ApiWorker
from steps.searchcombo import tornar_pesquisavel

_SEL = "— selecione —"
_FAM_ORDER = ["Handover", "MPM", "MPA", "MPS", "MPQ", "MPW", "MPT"]
_TRACKER_TIPO = "Estrutura Trackers"   # nesse tipo só mostramos o ativo "generalizado" (nome c/ Estrutura Trackers)
_RED = QColor("#e06c6c")
_DIM = QColor("#8a90a2")
_FG = QColor("#e7e9ef")


def abrir_pcm(parent):
    """Abre o PCM como diálogo (botão ao lado do COS)."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("PCM — OS por plano de tarefas")
    dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint)
    dlg.setMinimumSize(820, 720)
    dlg.setSizeGripEnabled(True)
    lay = QVBoxLayout(dlg); lay.setContentsMargins(0, 0, 0, 0)
    tab = PcmTab(); lay.addWidget(tab)
    tab.carregar_inicial()
    dlg.exec()


class PcmTab(QWidget):
    def __init__(self):
        super().__init__()
        self._assets = api.load_assets_cached() or []
        self._checked = set()                # ids dos ativos marcados
        self._planos_by_asset = {}           # asset_id -> [planos] (do Carregar)
        self._loaded_for = set()             # asset_ids p/ os quais já carreguei planos
        self._subt = {}                      # id_task -> nº de subtarefas (cache)
        self._editors = {}                   # row -> QDateTimeEdit (só linhas com plano)
        self._dt_by_asset = {}               # asset_id -> QDateTime (preserva a data ao trocar de família)
        self._wr = self._wp = self._wc = self._ws = None
        self._loaded = False
        self._filling = False                # guard contra reentrância no itemChanged
        self._sem_plano = False              # modo "Sem plano de tarefas" (subtarefa padrão Procedimento)

        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget(); scroll.setWidget(body); outer.addWidget(scroll)
        lay = QVBoxLayout(body); lay.setContentsMargins(20, 14, 20, 14); lay.setSpacing(8)

        lay.addWidget(QLabel("<b style='font-size:15px'>PCM — OS por plano de tarefas</b>"))
        lay.addWidget(QLabel("<span style='color:#8a90a2'>Marque os ativos, escolha a família e carregue "
                             "os planos. Cada ativo mostra seu plano e o nº de subtarefas — só conferir e "
                             "criar. 1 OS com cada ativo como tarefa.</span>"))

        # ── ativo: cliente → usina → tipo ──
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

        # ── sem plano de tarefas (subtarefa padrão "Procedimento") ──
        sprow = QHBoxLayout()
        self.cb_sem_plano = QCheckBox("Sem plano de tarefas")
        self.cb_sem_plano.setToolTip("Cria 1 OS com cada ativo marcado como tarefa, SEM plano — "
                                     "a subtarefa fica como 'Procedimento'.")
        self.cb_sem_plano.toggled.connect(self._on_sem_plano)
        sprow.addWidget(self.cb_sem_plano)
        self.desc_lbl = QLabel("Descrição da tarefa")
        self.ed_desc = QLineEdit()
        self.ed_desc.setPlaceholderText("opcional (vale p/ todas) — vazio = 'Procedimento'")
        self.desc_lbl.setVisible(False); self.ed_desc.setVisible(False)
        sprow.addWidget(self.desc_lbl); sprow.addWidget(self.ed_desc, 1)
        lay.addLayout(sprow)

        # ── família + carregar ──
        prow = QHBoxLayout()
        self.fam_lbl = QLabel("<b>Família do plano</b>")
        prow.addWidget(self.fam_lbl)
        self.cb_familia = QComboBox(); self.cb_familia.addItem("(carregue os planos)", None)
        self.cb_familia.currentIndexChanged.connect(self._refresh)   # re-ordena (com plano no topo) + re-preenche
        self.b_planos = QPushButton("Carregar planos"); self.b_planos.setObjectName("secondary")
        self.b_planos.clicked.connect(self._carregar_planos)
        prow.addWidget(self.cb_familia, 1); prow.addWidget(self.b_planos)
        lay.addLayout(prow)

        # ── tabela única: ativo + plano + nº subtarefas ──
        albl = QHBoxLayout()
        albl.addWidget(QLabel("<b>Ativos</b> <span style='color:#8a90a2'>(marque um ou vários — o plano "
                              "aparece após carregar)</span>"), 1)
        self.b_complano = QPushButton("Só com plano"); self.b_complano.setObjectName("secondary")
        self.b_complano.setToolTip("Marca apenas os ativos que têm plano nesta família (desmarca os demais)")
        self.b_complano.clicked.connect(self._marcar_com_plano)
        b_all = QPushButton("Selecionar todos"); b_all.setObjectName("secondary")
        b_all.clicked.connect(lambda: self._marcar_todos(True))
        b_none = QPushButton("Limpar"); b_none.setObjectName("secondary")
        b_none.clicked.connect(lambda: self._marcar_todos(False))
        albl.addWidget(self.b_complano); albl.addWidget(b_all); albl.addWidget(b_none)
        lay.addLayout(albl)
        self.tbl = QTableWidget(0, 4)
        self.tbl.setHorizontalHeaderLabels(["Ativo", "Plano de tarefa", "Subt.", "Data/hora programada"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl.setMinimumHeight(250)
        self.tbl.itemChanged.connect(self._on_item)
        lay.addWidget(self.tbl, 1)
        self.sel_lbl = QLabel("0 marcado(s)"); self.sel_lbl.setObjectName("hint")
        lay.addWidget(self.sel_lbl)

        # ── data/hora em massa (mesmos atalhos do Clonar OS) ──
        drow = QHBoxLayout()
        drow.addWidget(QLabel("<span style='color:#8a90a2'>Data/hora em massa:</span>"))
        self.bulk_date = QDateEdit(); self.bulk_date.setCalendarPopup(True)
        self.bulk_date.setDisplayFormat("dd/MM/yyyy"); self.bulk_date.setDate(QDate.currentDate())
        b_data = QPushButton("Aplicar data"); b_data.setObjectName("secondary")
        b_data.setToolTip("Define a DATA (dia/mês/ano) de todas as linhas; mantém o horário de cada uma")
        b_data.clicked.connect(lambda: self._set_todas_data(self.bulk_date.date()))
        b_manha = QPushButton("Manhã (07:00)"); b_manha.setObjectName("secondary")
        b_manha.setToolTip("Define o horário de TODAS as linhas para 07:00")
        b_manha.clicked.connect(lambda: self._set_todas_hora(7, 0))
        b_tarde = QPushButton("Tarde (13:00)"); b_tarde.setObjectName("secondary")
        b_tarde.setToolTip("Define o horário de TODAS as linhas para 13:00")
        b_tarde.clicked.connect(lambda: self._set_todas_hora(13, 0))
        b_mes = QPushButton("Avançar 1 mês"); b_mes.setObjectName("secondary")
        b_mes.setToolTip("Adia a data de cada linha em 1 mês")
        b_mes.clicked.connect(self._avancar_mes)
        for w in (self.bulk_date, b_data, b_manha, b_tarde, b_mes):
            drow.addWidget(w)
        drow.addStretch(1)
        lay.addLayout(drow)

        # ── observação ──
        lay.addWidget(QLabel("<b>Observação</b> <span style='color:#8a90a2'>(opcional)</span>"))
        self.obs = QTextEdit(); self.obs.setFixedHeight(44)
        lay.addWidget(self.obs)

        # ── responsável ──
        lay.addWidget(QLabel("<b>Requerido por (responsável)</b> "
                             "<span style='color:#8a90a2'>(obrigatório · digite p/ pesquisar)</span>"))
        rrow = QHBoxLayout()
        self.cb_resp = QComboBox(); self.cb_resp.addItem("carregando…", None)
        tornar_pesquisavel(self.cb_resp)
        self.b_resp_reload = QPushButton("↻"); self.b_resp_reload.setObjectName("secondary")
        self.b_resp_reload.setFixedWidth(40); self.b_resp_reload.setToolTip("Recarregar responsáveis")
        self.b_resp_reload.clicked.connect(self._carregar_resp)
        rrow.addWidget(self.cb_resp, 1); rrow.addWidget(self.b_resp_reload)
        lay.addLayout(rrow)

        self.btn = QPushButton("Criar OS (PCM)"); self.btn.clicked.connect(self._criar)
        lay.addWidget(self.btn)
        self.hint = QLabel(""); self.hint.setObjectName("hint")
        lay.addWidget(self.hint)

        self._fill_clientes()

    def carregar_inicial(self):
        if not self._loaded:
            self._loaded = True
            self._carregar_resp()

    # ── cascata ──
    def _fill_clientes(self):
        clientes = sorted({a["cliente"] for a in self._assets if a.get("cliente")})
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
        # PCM: SEM restrição de tipo (planos existem p/ muitos tipos) — todos os tipos da usina
        tipos = sorted({a["tipo"] for a in self._assets
                        if a.get("cliente") == cli and a.get("usina") == usi
                        and a.get("tipo")}) if usi else []
        self.cb_tipo.blockSignals(True); self.cb_tipo.clear()
        self.cb_tipo.addItem("Todos os tipos"); self.cb_tipo.addItems(tipos)
        self.cb_tipo.setEnabled(bool(tipos)); self.cb_tipo.blockSignals(False)
        self._refresh()

    # ── tabela ──
    def _has_plan(self, aid, fam=None):
        """True se o ativo (já carregado) tem ao menos um plano na família dada (None = qualquer)."""
        if aid is None or aid not in self._loaded_for:
            return False
        if fam is None:
            fam = self._fam()
        return any(fam is None or p.get("family") == fam
                   for p in self._planos_by_asset.get(aid, []))

    def _refresh(self, *_):
        cli, usi = self._cli(), self._usi()
        tipo = self.cb_tipo.currentText() if self.cb_tipo.currentIndex() > 0 else None
        txt = (self.busca.text() or "").strip().lower()
        fam = self._fam()
        ativos = []
        if usi:
            for a in self._assets:
                if a.get("cliente") != cli or a.get("usina") != usi or not a.get("tipo"):
                    continue
                if tipo and a.get("tipo") != tipo:
                    continue
                # trackers: nunca individualmente — só o ativo "generalizado" (nome c/ Estrutura Trackers)
                if a.get("tipo") == _TRACKER_TIPO and "estrutura trackers" not in (a.get("label") or "").lower():
                    continue
                if txt and txt not in (a.get("label") or "").lower():
                    continue
                ativos.append(a)
        # ordena: COM plano (na família atual) no topo, SEM plano embaixo; cada bloco por nome
        ativos.sort(key=lambda a: (0 if self._has_plan(a.get("id"), fam) else 1,
                                   (a.get("label") or a.get("code") or "").lower()))
        self.tbl.blockSignals(True)
        self.tbl.setRowCount(0)
        for a in ativos:
            r = self.tbl.rowCount(); self.tbl.insertRow(r)
            it = QTableWidgetItem(a.get("label") or a.get("code") or "?")
            it.setData(Qt.ItemDataRole.UserRole, a)
            it.setFlags((it.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsEditable)
            it.setCheckState(Qt.CheckState.Checked if a["id"] in self._checked
                             else Qt.CheckState.Unchecked)
            self.tbl.setItem(r, 0, it)
            self.tbl.setItem(r, 1, QTableWidgetItem("—"))
            self.tbl.setItem(r, 2, QTableWidgetItem(""))
            self.tbl.setItem(r, 3, QTableWidgetItem(""))
        self.tbl.blockSignals(False)
        self._fill_planos()

    def _on_item(self, it):
        if self._filling or it.column() != 0:
            return
        a = it.data(Qt.ItemDataRole.UserRole)
        if not isinstance(a, dict):
            return
        (self._checked.add if it.checkState() == Qt.CheckState.Checked else self._checked.discard)(a["id"])
        self._fill_row(it.row())
        self._fetch_counts_visiveis()
        self._upd_label()

    def _marcar_todos(self, marcar=True):
        self.tbl.blockSignals(True)
        for r in range(self.tbl.rowCount()):
            it = self.tbl.item(r, 0)
            a = it.data(Qt.ItemDataRole.UserRole)
            it.setCheckState(Qt.CheckState.Checked if marcar else Qt.CheckState.Unchecked)
            if isinstance(a, dict):
                (self._checked.add if marcar else self._checked.discard)(a["id"])
        self.tbl.blockSignals(False)
        self._fill_planos()

    def _marcar_com_plano(self):
        """Marca SÓ os ativos que têm plano na família atual (desmarca o resto)."""
        if not self._loaded_for:
            self.hint.setText("Carregue os planos primeiro (marque os ativos → Carregar planos).")
            return
        fam = self._fam()
        self.tbl.blockSignals(True)
        for r in range(self.tbl.rowCount()):
            it = self.tbl.item(r, 0)
            a = it.data(Qt.ItemDataRole.UserRole)
            has = self._has_plan((a or {}).get("id"), fam)
            it.setCheckState(Qt.CheckState.Checked if has else Qt.CheckState.Unchecked)
            if isinstance(a, dict):
                (self._checked.add if has else self._checked.discard)(a["id"])
        self.tbl.blockSignals(False)
        self._fill_planos()

    def _fam(self):
        return self.cb_familia.currentData()

    def _on_sem_plano(self, checked):
        """Liga/desliga o modo 'Sem plano de tarefas'. No modo sem-plano, família/Carregar/Só com plano
        ficam inativos e cada ativo marcado vira tarefa com a subtarefa padrão 'Procedimento'."""
        self._sem_plano = bool(checked)
        for w in (self.fam_lbl, self.cb_familia, self.b_planos, self.b_complano):
            w.setEnabled(not self._sem_plano)
        self.desc_lbl.setVisible(self._sem_plano); self.ed_desc.setVisible(self._sem_plano)
        self._refresh()        # re-ordena/preenche a tabela conforme o modo

    def _add_date_editor(self, r, aid):
        """Cria o QDateTimeEdit da linha (col 3), preservando a data por ativo."""
        de = QDateTimeEdit(); de.setCalendarPopup(True)
        de.setDisplayFormat("dd/MM/yyyy HH:mm")
        de.setDateTime(self._dt_by_asset.get(aid) or QDateTime(self.bulk_date.date(), QTime(8, 0)))
        de.dateTimeChanged.connect(lambda _v, k=aid, ed=de: self._dt_by_asset.__setitem__(k, ed.dateTime()))
        self._dt_by_asset.setdefault(aid, de.dateTime())
        self.tbl.setCellWidget(r, 3, de)
        self._editors[r] = de

    def _fill_planos(self, *_):
        """Preenche Plano/Subt./Data de todas as linhas e dispara a busca de contagens."""
        self._editors = {}
        for r in range(self.tbl.rowCount()):
            self._fill_row(r)
        self._fetch_counts_visiveis()
        self._upd_label()

    # ── data/hora em massa (operam nos editores das linhas com plano) ──
    def _avancar_mes(self):
        for de in self._editors.values():
            de.setDateTime(de.dateTime().addMonths(1))

    def _set_todas_hora(self, h, m):
        for de in self._editors.values():
            dt = de.dateTime(); dt.setTime(QTime(h, m)); de.setDateTime(dt)

    def _set_todas_data(self, qdate):
        for de in self._editors.values():
            dt = de.dateTime(); dt.setDate(qdate); de.setDateTime(dt)

    def _fill_row(self, r):
        """Plano (combo) + nº subtarefas de UMA linha, conforme a família e se o ativo está marcado."""
        it = self.tbl.item(r, 0)
        if it is None:
            return
        self._filling = True
        try:
            a = it.data(Qt.ItemDataRole.UserRole) or {}
            aid = a.get("id")
            self.tbl.removeCellWidget(r, 1)
            self.tbl.removeCellWidget(r, 3)
            self._editors.pop(r, None)
            c1 = QTableWidgetItem(); c2 = QTableWidgetItem(); c3 = QTableWidgetItem()
            c2.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            c3.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            marcado = it.checkState() == Qt.CheckState.Checked
            if not marcado:
                it.setForeground(QBrush(_FG))
                c1.setText("—"); c1.setForeground(QBrush(_DIM))
                c3.setText("—"); c3.setForeground(QBrush(_DIM))
                self.tbl.setItem(r, 1, c1); self.tbl.setItem(r, 2, c2); self.tbl.setItem(r, 3, c3)
                return
            if self._sem_plano:           # modo sem plano: ativo marcado = tarefa com 'Procedimento'
                it.setForeground(QBrush(_FG))
                c1.setText("Procedimento  (sem plano de tarefas)"); c1.setForeground(QBrush(_DIM))
                c2.setText("1")
                self.tbl.setItem(r, 1, c1); self.tbl.setItem(r, 2, c2)
                self._add_date_editor(r, aid)
                return
            if aid not in self._loaded_for:
                it.setForeground(QBrush(_FG))
                c1.setText("clique em “Carregar planos”"); c1.setForeground(QBrush(_DIM))
                c3.setText("—"); c3.setForeground(QBrush(_DIM))
                self.tbl.setItem(r, 1, c1); self.tbl.setItem(r, 2, c2); self.tbl.setItem(r, 3, c3)
                return
            fam = self._fam()
            plans = [p for p in self._planos_by_asset.get(aid, [])
                     if fam is None or p.get("family") == fam]
            if not plans:
                it.setForeground(QBrush(_RED))
                c1.setText("— sem plano nesta família —"); c1.setForeground(QBrush(_RED))
                c2.setText("—"); c2.setForeground(QBrush(_RED))
                c3.setText("—"); c3.setForeground(QBrush(_RED))
                self.tbl.setItem(r, 1, c1); self.tbl.setItem(r, 2, c2); self.tbl.setItem(r, 3, c3)
                return
            # tem plano(s): combo (default no [Grid Co.] se houver) + contagem + data por-linha
            it.setForeground(QBrush(_FG))
            plans = sorted(plans, key=lambda p: (p.get("description") or "").lower())
            combo = QComboBox()
            for p in plans:
                combo.addItem(p.get("description") or "?", p.get("id_task"))
            gi = next((i for i, p in enumerate(plans)
                       if "grid" in (p.get("description") or "").lower()), -1)
            combo.setCurrentIndex(gi if gi >= 0 else 0)
            combo.setProperty("row", r); combo.setProperty("id_item", aid)
            combo.currentIndexChanged.connect(lambda _i, rr=r: self._on_combo(rr))
            self.tbl.setCellWidget(r, 1, combo)
            self.tbl.setItem(r, 2, c2)
            self._set_count_cell(r, combo.currentData())
            self._add_date_editor(r, aid)
        finally:
            self._filling = False

    def _set_count_cell(self, r, id_task):
        c2 = self.tbl.item(r, 2)
        if c2 is None:
            c2 = QTableWidgetItem(); self.tbl.setItem(r, 2, c2)
        c2.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        n = self._subt.get(id_task)
        if n is None:
            c2.setText("…"); c2.setForeground(QBrush(_DIM))
        elif n == 0:
            c2.setText("0"); c2.setForeground(QBrush(_RED))
        else:
            c2.setText(str(n)); c2.setForeground(QBrush(_FG))

    def _on_combo(self, r):
        cb = self.tbl.cellWidget(r, 1)
        if isinstance(cb, QComboBox):
            self._set_count_cell(r, cb.currentData())
            self._fetch_counts_visiveis()

    def _fetch_counts_visiveis(self):
        """Busca (em paralelo) o nº de subtarefas dos planos atualmente selecionados que ainda não
        estão no cache."""
        pares = []
        for r in range(self.tbl.rowCount()):
            cb = self.tbl.cellWidget(r, 1)
            if isinstance(cb, QComboBox):
                idt = cb.currentData()
                if idt is not None and idt not in self._subt:
                    pares.append((idt, cb.property("id_item")))
        if not pares or self._ws is not None:
            return
        self._ws = ApiWorker(api.get_subtask_counts, pares)
        self._ws.ok.connect(self._set_counts)
        self._ws.erro.connect(self._counts_err)
        self._ws.start()

    def _set_counts(self, d):
        self._ws = None
        if isinstance(d, dict):
            self._subt.update(d)
        for r in range(self.tbl.rowCount()):
            cb = self.tbl.cellWidget(r, 1)
            if isinstance(cb, QComboBox):
                self._set_count_cell(r, cb.currentData())
        self._fetch_counts_visiveis()      # pega o que tiver sobrado

    def _counts_err(self, _m):
        self._ws = None

    def _upd_label(self):
        if self._sem_plano:
            self.sel_lbl.setText(f"{len(self._checked)} marcado(s) · sem plano "
                                 "(cada ativo = 1 tarefa, subtarefa 'Procedimento')")
            return
        com = sum(1 for r in range(self.tbl.rowCount())
                  if self.tbl.item(r, 0) is not None
                  and self.tbl.item(r, 0).checkState() == Qt.CheckState.Checked
                  and isinstance(self.tbl.cellWidget(r, 1), QComboBox))
        sem = len(self._sem_plano_rows())
        msg = f"{len(self._checked)} marcado(s)"
        if self._loaded_for:
            msg += f" · {com} com plano"
            if sem:
                msg += f" · <span style='color:#e06c6c'>{sem} SEM plano nesta família</span>"
        self.sel_lbl.setText(msg)

    def _sem_plano_rows(self):
        rows = set()
        if self._sem_plano:
            return rows
        fam = self._fam()
        for r in range(self.tbl.rowCount()):
            it = self.tbl.item(r, 0)
            if it is None or it.checkState() != Qt.CheckState.Checked:
                continue
            a = it.data(Qt.ItemDataRole.UserRole) or {}
            aid = a.get("id")
            if aid in self._loaded_for and not [p for p in self._planos_by_asset.get(aid, [])
                                                if fam is None or p.get("family") == fam]:
                rows.add(r)
        return rows

    # ── carregar planos ──
    def _carregar_planos(self):
        assets = [a for a in self._assets if a["id"] in self._checked]
        if not assets:
            QMessageBox.warning(self, "Ativos", "Marque ao menos um ativo primeiro."); return
        self.b_planos.setEnabled(False)
        self.hint.setText(f"buscando planos de {len(assets)} ativo(s)…")
        self._wp = ApiWorker(api.get_plans_for_assets, assets)
        self._wp.ok.connect(self._set_planos)
        self._wp.erro.connect(self._planos_err)
        self._wp.start()

    def _set_planos(self, planos):
        self._wp = None
        self.b_planos.setEnabled(True)
        planos = planos or []
        # indexa por ativo + marca quais ativos foram carregados
        self._loaded_for = set(self._checked)
        by_asset = {}
        for p in planos:
            aid = (p.get("asset") or {}).get("id")
            if aid is not None:
                by_asset.setdefault(aid, []).append(p)
        self._planos_by_asset = by_asset
        fams = {p.get("family") for p in planos if p.get("family")}
        ordenadas = [f for f in _FAM_ORDER if f in fams] + sorted(fams - set(_FAM_ORDER))
        self.cb_familia.blockSignals(True); self.cb_familia.clear()
        self.cb_familia.addItem("(todas)", None)
        for f in ordenadas:
            self.cb_familia.addItem(f, f)
        self.cb_familia.setCurrentIndex(1 if ordenadas else 0)
        self.cb_familia.blockSignals(False)
        if not planos:
            self.hint.setText("Nenhum plano encontrado p/ os ativos marcados.")
        else:
            self.hint.setText(f"{len(planos)} plano(s) em {len(fams)} família(s).")
        self._refresh()   # re-ordena com plano no topo + preenche

    def _planos_err(self, m):
        self._wp = None
        self.b_planos.setEnabled(True)
        self.hint.setText("⚠ planos: " + str(m))

    # ── responsável ──
    def _carregar_resp(self):
        self.cb_resp.clear(); self.cb_resp.addItem("carregando…", None)
        self._wr = ApiWorker(api.get_responsaveis)
        self._wr.ok.connect(self._set_resp)
        self._wr.erro.connect(self._resp_err)
        self._wr.start()

    def _set_resp(self, pessoas):
        self._wr = None
        self.cb_resp.clear(); self.cb_resp.addItem(_SEL, None)
        for p in sorted(pessoas or [], key=lambda x: (x.get("name") or "").lower()):
            self.cb_resp.addItem(p.get("name") or p.get("code") or "?", p)

    def _resp_err(self, m):
        self._wr = None
        self.cb_resp.clear(); self.cb_resp.addItem("⚠ falha — relogue e clique em ↻", None)
        self.hint.setText("⚠ responsável: " + str(m))

    # ── criar: 1 OS com cada ativo (com plano) como tarefa ──
    def _criar(self):
        brt = _dt.timezone(_dt.timedelta(hours=-3))   # data escolhida é Brasília; _iso_z converte p/ UTC
        if self._sem_plano:
            self._criar_sem_plano(brt)
            return
        sel, sem = [], []
        for r in range(self.tbl.rowCount()):
            it = self.tbl.item(r, 0)
            if it is None or it.checkState() != Qt.CheckState.Checked:
                continue
            a = it.data(Qt.ItemDataRole.UserRole) or {}
            cb = self.tbl.cellWidget(r, 1)
            if isinstance(cb, QComboBox) and cb.currentData():
                de = self._editors.get(r)
                evt = de.dateTime().toPyDateTime().replace(tzinfo=brt) if de is not None else None
                sel.append({"asset": a, "id_task": cb.currentData(), "event_date": evt})
            elif a.get("id") in self._loaded_for:
                sem.append(a.get("label") or a.get("code") or "?")
        if not sel:
            QMessageBox.warning(self, "Tarefas", "Carregue os planos e marque ao menos um ativo com plano.")
            return
        p = self.cb_resp.currentData()
        if not isinstance(p, dict) or not p.get("id_personnel"):
            QMessageBox.warning(self, "Responsável", "Escolha o responsável."); return
        aviso = ""
        if sem:
            aviso = ("\n\nFicam de FORA (sem plano nesta família):\n- " + "\n- ".join(sem[:10])
                     + ("\n- …" if len(sem) > 10 else ""))
        resp = QMessageBox.question(self, "Criar OS planejada",
                f"Vou criar UMA OS com {len(sel)} tarefa(s) — uma por ativo marcado.{aviso}\n\nContinuar?")
        if resp != QMessageBox.StandardButton.Yes:
            return
        self.btn.setEnabled(False)
        self.hint.setText(f"criando 1 OS com {len(sel)} tarefa(s)… (pode levar alguns segundos)")
        self._wc = ApiWorker(api.create_planned_os_multi, sel, p.get("id_personnel"), p.get("name"), None)
        self._wc.ok.connect(self._criou)
        self._wc.erro.connect(self._err)
        self._wc.start()

    def _criar_sem_plano(self, brt):
        """1 OS SEM plano: cada ativo marcado vira tarefa com a subtarefa padrão 'Procedimento'."""
        sel = []
        for r in range(self.tbl.rowCount()):
            it = self.tbl.item(r, 0)
            if it is None or it.checkState() != Qt.CheckState.Checked:
                continue
            a = it.data(Qt.ItemDataRole.UserRole) or {}
            de = self._editors.get(r)
            evt = de.dateTime().toPyDateTime().replace(tzinfo=brt) if de is not None else None
            sel.append({"asset": a, "event_date": evt})
        if not sel:
            QMessageBox.warning(self, "Tarefas", "Marque ao menos um ativo."); return
        p = self.cb_resp.currentData()
        if not isinstance(p, dict) or not p.get("id_personnel"):
            QMessageBox.warning(self, "Responsável", "Escolha o responsável."); return
        desc = self.ed_desc.text().strip()
        resp = QMessageBox.question(self, "Criar OS sem plano",
                f"Vou criar UMA OS com {len(sel)} tarefa(s) SEM plano — uma por ativo, "
                f"subtarefa 'Procedimento'{(' · descrição: ' + desc) if desc else ''}.\n\nContinuar?")
        if resp != QMessageBox.StandardButton.Yes:
            return
        self.btn.setEnabled(False)
        self.hint.setText(f"criando 1 OS com {len(sel)} tarefa(s)… (pode levar alguns segundos)")
        self._wc = ApiWorker(api.create_os_sem_plano, sel, p.get("id_personnel"), p.get("name"),
                             desc, self.obs.toPlainText().strip())
        self._wc.ok.connect(self._criou)
        self._wc.erro.connect(self._err)
        self._wc.start()

    def _criou(self, res):
        self._wc = None
        self.btn.setEnabled(True); self.hint.setText("")
        res = res if isinstance(res, dict) else {}
        if res.get("ok"):
            os_ = res.get("os") or {}
            folio = os_.get("wo_folio")
            msg = f"OS criada{f' — Nº {folio}' if folio else ''} com {res.get('n_criadas') or 0} tarefa(s)."
            if res.get("aviso"):
                msg += f"\n\nObs.: {res['aviso']}"
            if res.get("erros"):
                msg += "\n\nAlgumas tarefas falharam:\n- " + "\n- ".join(res["erros"][:8])
            QMessageBox.information(self, "OS planejada criada", msg)
        else:
            QMessageBox.critical(self, "Erro", res.get("erro") or "Falha ao criar a OS planejada.")

    def _err(self, m):
        self._wc = None
        self.btn.setEnabled(True); self.hint.setText("")
        QMessageBox.critical(self, "Erro", str(m))
