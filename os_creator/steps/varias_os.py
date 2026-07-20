"""COS reestruturado (F2) — 'Criar Várias OS' padronizado.
Fluxo: TIPO (Religamento da UFV / Inspeção e Normalização) → ATIVO(s) → CATEGORIA (A proteções /
B inversores / C comunicação) → AÇÃO/permissivo → EVENTO → RESPONSÁVEL. O título
'[Usina][Equipamento] - Motivo' e a observação-pipe 'UFV: … | Proteção: … | Ação: … | Falha: …' são
montados SOZINHOS (cos_spec) e mostrados ao vivo. Gera 1 OS por ativo marcado (mesmo evento), com
subtarefas OBRIGATÓRIAS. 'Já realizada' (religamento remoto resolvido) vem ligado; se houver
impedimento de segurança (86) o permissivo sugere abrir para equipe em campo."""
import datetime as _dt
from PyQt6.QtCore import Qt, QDateTime
from PyQt6.QtGui import QIcon, QBrush, QColor, QPainter
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
                             QLineEdit, QPushButton, QMessageBox, QDateTimeEdit, QWidget, QScrollArea,
                             QFrame, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
                             QSizePolicy, QCheckBox)
import api
import cos_spec as cs
from workers import ApiWorker, slot_seguro
from steps.step1 import ALLOWED_TIPOS
from steps.finalizar import FinalizarPanel
from steps.searchcombo import tornar_pesquisavel
from steps.ui import QSS_FORM, Card, campo, rotulo, Linha, Segmentado, icone_pix, GREEN, MUTED

_SEL = "— selecione —"
# Tipos de EQUIPAMENTO de planta — usados p/ decidir quais clientes/usinas são "reais" (o catálogo do
# Fracttal tem itens de inventário/material com cliente e usina próprios que não são plantas).
_CARTEIRA_EQUIP = frozenset({"Inversor", "Cabine", "Tracker", "Estrutura Trackers",
                             "Estação Meteorológica", "Skid"})   # tipos que SÓ plantas têm (inventário
                             # do Almoxarifado usa 'Usina'/'Disjuntor'/'Transformador' — ficam de fora)


def abrir_varias_os(parent):
    """Abre o COS como janela avulsa (embrulha o painel num QDialog)."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("COS")
    dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint)
    dlg.setMinimumSize(680, 640); dlg.setSizeGripEnabled(True)
    dlg.setStyleSheet(QSS_FORM)
    lay = QVBoxLayout(dlg); lay.setContentsMargins(0, 0, 0, 0)
    panel = VariasOSsDialog(on_voltar=dlg.accept)
    top = QHBoxLayout(); top.setContentsMargins(12, 10, 12, 0)
    top.addWidget(panel.modo_bar); top.addStretch(1)
    lay.addLayout(top); lay.addWidget(panel)
    dlg.exec()


class _Chip(QPushButton):
    """Botão-pill marcável (proteção ANSI)."""
    def __init__(self, texto, on_toggle=None):
        super().__init__(texto)
        self.setCheckable(True); self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("chip")
        self.setFixedHeight(30); self.setMinimumWidth(46)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)   # compacto (não estica)
        self.setStyleSheet(
            "QPushButton#chip{background:#1A2337;border:1px solid #2A3550;border-radius:8px;"
            "padding:3px 12px;color:#c4cbdb;font-family:Consolas,monospace;font-size:12px;}"
            "QPushButton#chip:checked{background:rgba(166,226,46,0.16);border-color:%s;color:#e6eaf2;}" % GREEN)
        if on_toggle:
            self.toggled.connect(lambda *_: on_toggle())


# Ativo genérico "Grid Co. - Emergências e outros pontos" (code GRID) — usado nas OS de usina de
# terceiros (planta que não é ativo cadastrado no Fracttal). id extraído de OSs reais (ex.: 9184).
GENERICO_ID = 49349933
GENERICO_DESC = "Grid Co. - Emergências e outros pontos      { GRID }"


class ToggleSwitch(QCheckBox):
    """Interruptor pílula (cinza→verde). Usa o toggled(bool) do QCheckBox."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(44, 24)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(GREEN) if on else QColor("#2b3550"))
        p.drawRoundedRect(0, 0, 44, 24, 12, 12)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(23 if on else 3, 3, 18, 18)
        p.end()


class VariasOSsDialog(QWidget):
    def __init__(self, parent=None, on_voltar=None):
        super().__init__(parent)
        self._on_voltar = on_voltar
        self._assets = api.load_assets_cached() or []
        self._wc = self._wr = self._wt = self._wf = None
        self._checked = set()
        self._terceiros = False        # modo "usina de terceiros" (Cliente/Usina livres + ativo genérico)
        self._terc_wired = False       # os textEdited do Cliente/Usina já foram ligados ao preview?
        self._clientes_reais = set()   # carteiras com equipamento (preenchido em _fill_clientes)
        self._classif = None            # {tipos:[...], c1:[...], c2:[...]} (carrega async)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint)
        self.setMinimumWidth(600)
        self.setStyleSheet(QSS_FORM)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        _body = QWidget(); scroll.setWidget(_body)
        outer.addWidget(scroll)
        lay = QVBoxLayout(_body); lay.setContentsMargins(18, 14, 18, 14); lay.setSpacing(14)

        # ── barra de TIPO (fica ao lado do "Voltar" via _wrap_modo) ──
        self._seg_tipo = Segmentado([cs.TIPO_RELIGAMENTO, cs.TIPO_INSPECAO], on_change=self._on_tipo)
        barra = QFrame(); barra.setObjectName("uiBar")
        bl = QHBoxLayout(barra); bl.setContentsMargins(14, 5, 14, 5); bl.setSpacing(9)
        _tl = QLabel("Tipo:"); _tl.setObjectName("uiCampoLabel")
        bl.addWidget(_tl); bl.addSpacing(3); bl.addWidget(self._seg_tipo)
        self.modo_bar = barra

        # ── Card 1: Ativo ──
        self.cb_cli = QComboBox(); self.cb_cli.currentIndexChanged.connect(self._on_cli)
        self.cb_usi = QComboBox(); self.cb_usi.currentIndexChanged.connect(self._on_usi)
        tornar_pesquisavel(self.cb_usi)
        self.cb_tipo = QComboBox(); self.cb_tipo.currentIndexChanged.connect(self._refresh_ativos)
        self.busca = QLineEdit(); self.busca.setPlaceholderText("Filtrar ativo por código ou nome…")
        self.busca.addAction(QIcon(icone_pix("search", MUTED, 15)), QLineEdit.ActionPosition.LeadingPosition)
        self.busca.textChanged.connect(self._refresh_ativos)
        sel_bar = QWidget(); sel_bar.setObjectName("uiGroup")
        sbl = QHBoxLayout(sel_bar); sbl.setContentsMargins(0, 0, 0, 0)
        b_all = QPushButton("Selecionar todos"); b_all.setObjectName("secondary")
        b_all.clicked.connect(lambda: self._marcar_todos(True))
        b_none = QPushButton("Limpar"); b_none.setObjectName("secondary")
        b_none.clicked.connect(lambda: self._marcar_todos(False))
        sbl.addStretch(1); sbl.addWidget(b_all); sbl.addWidget(b_none)
        self.tbl = QTableWidget(0, 1); self.tbl.setHorizontalHeaderLabels(["Ativo"])
        self.tbl.setWordWrap(False)
        self.tbl.setStyleSheet("QTableWidget::item{padding-left:0px;}")
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.verticalHeader().setDefaultSectionSize(40)
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tbl.setMinimumHeight(200)
        self.tbl.itemChanged.connect(self._on_check_multi)
        self.sel_lbl = QLabel("0 ativo(s) marcado(s)"); self.sel_lbl.setObjectName("uiAjuda")
        self._seg_modo = Segmentado(["Vários ativos · 1 data", "Mesmo ativo · várias datas"],
                                    on_change=self._on_modo)
        self._modo = 0                         # 0 = 1 OS por ativo · 1 = N OS p/ o mesmo ativo (várias datas)
        self._date_rows = []
        self._terc_row = self._build_terc_row()          # toggle "Usina de terceiros"
        self._lin_tipo = Linha(campo("Tipo de equipamento", self.cb_tipo), campo(" ", self.busca))
        self._lbl_ativos = rotulo("Ativos", obrig=True)
        self._sel_bar = sel_bar
        self.gen_note = self._build_gen_note()           # nota do ativo genérico (só no modo terceiros)
        c_ativo = Card(1, "Ativo")
        c_ativo.add(self._terc_row)
        c_ativo.add(self._seg_modo)
        c_ativo.add(Linha(campo("Cliente", self.cb_cli, obrig=True), campo("Usina", self.cb_usi, obrig=True)))
        c_ativo.add(self._lin_tipo)
        c_ativo.add(self._lbl_ativos); c_ativo.add(self._sel_bar)
        c_ativo.add(self.tbl, stretch=1); c_ativo.add(self.sel_lbl)
        c_ativo.add(self.gen_note)
        self.gen_note.setVisible(False)
        lay.addWidget(c_ativo)

        # ── Card 2: Categoria da ocorrência ──
        self._seg_cat = Segmentado(["A · Proteções", "B · Inversores", "C · Comunicação"],
                                    on_change=self._on_cat)
        self._cat = cs.CAT_A
        self._chips = {}                       # code -> _Chip
        chips_wrap = QWidget(); chips_wrap.setStyleSheet("background:transparent;")
        cw = QGridLayout(chips_wrap); cw.setContentsMargins(0, 0, 0, 0)
        cw.setHorizontalSpacing(6); cw.setVerticalSpacing(6)
        for idx, cod in enumerate(cs.PROTECOES):        # grade 5×2, chips compactos à esquerda
            ch = _Chip(cod, on_toggle=self._preview); self._chips[cod] = ch
            cw.addWidget(ch, idx // 5, idx % 5, Qt.AlignmentFlag.AlignLeft)
        cw.setColumnStretch(5, 1)                        # coluna extra absorve o espaço (chips não esticam)
        self.cb_onde = QComboBox(); self.cb_onde.addItems(cs.ONDE); self.cb_onde.currentIndexChanged.connect(self._preview)
        self._page_a = QWidget(); self._page_a.setStyleSheet("background:transparent;")
        pa = QVBoxLayout(self._page_a); pa.setContentsMargins(0, 0, 0, 0)
        pa.addWidget(Linha(campo("Proteção(ões) que atuaram", chips_wrap, obrig=True),
                           campo("Onde atuou", self.cb_onde, obrig=True), pesos=(3, 2)))
        self.cb_falha_b = QComboBox(); self.cb_falha_b.addItems(cs.FALHAS_B); self.cb_falha_b.currentIndexChanged.connect(self._preview)
        self._page_b = QWidget(); self._page_b.setStyleSheet("background:transparent;")
        pb = QVBoxLayout(self._page_b); pb.setContentsMargins(0, 0, 0, 0)
        pb.addWidget(campo("Falha do equipamento", self.cb_falha_b, obrig=True,
                           extra="(o equipamento é o próprio ativo marcado — inversor, cabine, etc.)"))
        self.cb_causa_c = QComboBox(); self.cb_causa_c.addItems(cs.CAUSAS_C); self.cb_causa_c.currentIndexChanged.connect(self._preview)
        self._page_c = QWidget(); self._page_c.setStyleSheet("background:transparent;")
        pc = QVBoxLayout(self._page_c); pc.setContentsMargins(0, 0, 0, 0)
        pc.addWidget(campo("Causa da comunicação", self.cb_causa_c, obrig=True))
        c_cat = Card(2, "Categoria da ocorrência")
        self.info_ansi = QLabel("!"); self.info_ansi.setFixedSize(22, 22)
        self.info_ansi.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_ansi.setToolTip(cs.ansi_tooltip())
        self.info_ansi.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.info_ansi.setStyleSheet("QLabel{background:rgba(166,226,46,0.14);color:%s;"
                                     "border:1px solid rgba(166,226,46,0.55);border-radius:11px;"
                                     "font-weight:800;font-size:13px;}" % GREEN)
        c_cat.extra_head(self.info_ansi)          # "!" no canto sup. direito → tooltip com a tabela ANSI (só cat. A)
        c_cat.add(self._seg_cat)
        c_cat.add(self._page_a); c_cat.add(self._page_b); c_cat.add(self._page_c)
        lay.addWidget(c_cat)

        # ── Card 3: Ação + permissivo ──
        self._seg_acao = Segmentado(["Remoto — resolvo agora", "Local — equipe em campo"],
                                    on_change=self._on_acao)
        self.lbl_perm = QLabel(""); self.lbl_perm.setObjectName("uiAjuda"); self.lbl_perm.setWordWrap(True)
        c_acao = Card(3, "Ação e permissivo de segurança")
        c_acao.add(self._seg_acao); c_acao.add(self.lbl_perm)

        # ── Card 4: Evento + finalização ──
        self.de = QDateTimeEdit(); self.de.setCalendarPopup(True); self.de.setDisplayFormat("dd/MM/yyyy HH:mm")
        self.de.setDateTime(QDateTime.currentDateTime().addSecs(-600)); self.de.dateTimeChanged.connect(self._preview)
        b_now = QPushButton("Agora"); b_now.setObjectName("secondary")
        b_now.clicked.connect(lambda: self.de.setDateTime(QDateTime.currentDateTime().addSecs(-600)))
        erow = QWidget(); erow.setStyleSheet("background:transparent;")   # sem faixa escura atrás do "Fora de Serviço"
        erl = QHBoxLayout(erow); erl.setContentsMargins(0, 0, 0, 0); erl.setSpacing(8)
        self.lbl_oos_ev = QLabel(); self.lbl_oos_ev.setStyleSheet("background:transparent;")
        erl.addWidget(self.de, 1); erl.addWidget(b_now); erl.addWidget(self.lbl_oos_ev)
        self.de_fim = QDateTimeEdit(); self.de_fim.setCalendarPopup(True); self.de_fim.setDisplayFormat("dd/MM/yyyy HH:mm")
        self.de_fim.setDateTime(QDateTime.currentDateTime())
        self.de.dateTimeChanged.connect(                       # conclusão acompanha o evento (+10min)
            lambda: self.de_fim.setDateTime(self.de.dateTime().addSecs(600)))
        self._fin = FinalizarPanel(["Procedimento"], com_datas=False)
        self._fin.toggled.connect(self._sync_fin)
        c_evt = Card(5, "Evento")
        self._campo_ev = campo("Data/hora do evento", erow, obrig=True)
        self._campo_fim = campo("Data/hora da conclusão", self.de_fim, extra="(quando resolvido)")
        # modo "mesmo ativo": N linhas de data (evento → conclusão), cada uma vira uma OS
        self._datas_multi = QWidget(); self._datas_multi.setStyleSheet("background:transparent;")
        _dmv = QVBoxLayout(self._datas_multi); _dmv.setContentsMargins(0, 0, 0, 0); _dmv.setSpacing(8)
        _dhead = QHBoxLayout(); _dhead.setContentsMargins(0, 0, 0, 0)
        _dl = QLabel("Datas/horas do evento (uma OS por linha)"); _dl.setObjectName("uiCampoLabel")
        self.b_add_data = QPushButton("+ Adicionar data"); self.b_add_data.setObjectName("secondary")
        self.b_add_data.clicked.connect(self._add_data)
        _dhead.addWidget(_dl); _dhead.addStretch(1); _dhead.addWidget(self.b_add_data)
        _dmv.addLayout(_dhead)
        self._datas_lay = QVBoxLayout(); self._datas_lay.setContentsMargins(0, 0, 0, 0); self._datas_lay.setSpacing(6)
        self._datas_lay.addStretch(1)
        _dmv.addLayout(self._datas_lay)
        self._datas_multi.setVisible(False)
        # ── 2 colunas: ESQ = datas + "já realizada"; DIR = respostas das subtarefas (aparecem ao marcar) ──
        self._fin.panel.setStyleSheet("QFrame#finpanel{background:#161d30;border:1px solid #2c3142;"
                                      "border-radius:6px;} QRadioButton, QLabel { background: transparent; }")
        _evt2 = QWidget(); _evt2.setStyleSheet("background:transparent;")
        _evt2l = QHBoxLayout(_evt2); _evt2l.setContentsMargins(0, 0, 0, 0); _evt2l.setSpacing(18)
        _esq = QWidget(); _esq.setStyleSheet("background:transparent;")
        _esql = QVBoxLayout(_esq); _esql.setContentsMargins(0, 0, 0, 0); _esql.setSpacing(10)
        _esql.addWidget(self._campo_ev); _esql.addWidget(self._campo_fim)
        _esql.addWidget(self._datas_multi); _esql.addWidget(self._fin); _esql.addStretch(1)
        _dir = QWidget(); _dir.setStyleSheet("background:transparent;")
        _dirl = QVBoxLayout(_dir); _dirl.setContentsMargins(0, 0, 0, 0); _dirl.setSpacing(0)
        _dirl.addWidget(self._fin.panel); _dirl.addStretch(1)   # respostas reparentadas p/ a direita
        _evt2l.addWidget(_esq, 1); _evt2l.addWidget(_dir, 1)
        c_evt.add(_evt2)

        # ── Card 5: Responsável ──
        self.cb_resp = QComboBox(); self.cb_resp.addItem("carregando…", None)
        tornar_pesquisavel(self.cb_resp)
        self.cb_resp.currentIndexChanged.connect(self._upd)
        self.b_resp_reload = QPushButton("↻"); self.b_resp_reload.setObjectName("secondary")
        self.b_resp_reload.setFixedWidth(40); self.b_resp_reload.setToolTip("Recarregar responsáveis")
        self.b_resp_reload.clicked.connect(self._carregar_resp)
        rrow = QWidget(); rrow.setObjectName("uiGroup")
        rrl = QHBoxLayout(rrow); rrl.setContentsMargins(0, 0, 0, 0); rrl.setSpacing(8)
        rrl.addWidget(self.cb_resp, 1); rrl.addWidget(self.b_resp_reload)
        c_resp = Card(4, "Responsável")
        c_resp.add(campo("Requerido por", rrow, obrig=True, extra="(digite p/ pesquisar)"))
        lay.addWidget(Linha(c_acao, c_resp, quebra=860))
        lay.addWidget(c_evt)

        # ── Card 6: O ativo falhou? (F4 — bloco de falha p/ a verificação) ──
        self.chk_falha = QCheckBox("O ativo falhou?"); self.chk_falha.toggled.connect(self._on_falha)
        self.cb_ftipo = QComboBox(); self.cb_fcausa = QComboBox(); self.cb_fdetec = QComboBox()
        for cb in (self.cb_ftipo, self.cb_fcausa, self.cb_fdetec):
            cb.addItem("carregando…", None); tornar_pesquisavel(cb)
        self.cb_fsev = QComboBox()
        for nome, idp in api.FALHA_SEVERIDADES:
            self.cb_fsev.addItem(nome, idp)
        self.cb_fdano = QComboBox()
        for nome, idp in api.FALHA_DANOS:
            self.cb_fdano.addItem(nome, idp)
        self.lbl_oos = QLabel("—")            # derivado (read-only): fora de serviço = OS sem data de conclusão
        self.lbl_oos.setStyleSheet(f"color:{MUTED};font-size:12px;background:transparent;")
        oos_row = QWidget(); oos_row.setStyleSheet("background:transparent;")
        orl = QHBoxLayout(oos_row); orl.setContentsMargins(0, 0, 0, 0); orl.setSpacing(8)
        orl.addWidget(self.lbl_oos); orl.addStretch(1)
        self._falha_box = QWidget(); self._falha_box.setStyleSheet("background:transparent;")
        fb = QVBoxLayout(self._falha_box); fb.setContentsMargins(0, 8, 0, 0); fb.setSpacing(10)
        _r1 = QWidget(); _r1.setStyleSheet("background:transparent;")
        _r1l = QHBoxLayout(_r1); _r1l.setContentsMargins(0, 0, 0, 0); _r1l.setSpacing(12)
        _r1l.addWidget(campo("Tipo de falha", self.cb_ftipo), 1)
        _r1l.addWidget(campo("Causa da falha", self.cb_fcausa), 1)
        _r1l.addWidget(campo("Método de detecção", self.cb_fdetec), 1)
        _r2 = QWidget(); _r2.setStyleSheet("background:transparent;")
        _r2l = QHBoxLayout(_r2); _r2l.setContentsMargins(0, 0, 0, 0); _r2l.setSpacing(12)
        _r2l.addWidget(campo("Severidade", self.cb_fsev), 1)
        _r2l.addWidget(campo("Tipo de dano", self.cb_fdano), 1)
        _r2l.addWidget(campo("Fora de serviço", oos_row), 1)
        fb.addWidget(_r1); fb.addWidget(_r2)
        self._falha_box.setVisible(False)
        c_falha = Card(6, "O ativo falhou?")
        c_falha.add(self.chk_falha); c_falha.add(self._falha_box)
        lay.addWidget(c_falha)

        # ── Preview (título + observação) ──
        self.prev_tit = QLabel("—"); self.prev_tit.setObjectName("uiMono"); self.prev_tit.setWordWrap(True)
        self.prev_obs = QLabel("—"); self.prev_obs.setObjectName("uiMono"); self.prev_obs.setWordWrap(True)
        self.prev_tit.setStyleSheet("font-family:Consolas,monospace;font-size:12px;color:#e6eaf2;")
        self.prev_obs.setStyleSheet("font-family:Consolas,monospace;font-size:12px;color:#c4cbdb;")
        self.prev_meta = QLabel("—"); self.prev_meta.setWordWrap(True)
        self.prev_meta.setStyleSheet("font-size:12px;color:#c4cbdb;background:#141b2e;"
                                     "border:1px solid #24304d;border-radius:8px;padding:8px 10px;")
        self.ed_obs = QLineEdit()
        self.ed_obs.setPlaceholderText("comentário do operador — entra numa nova linha no fim da observação")
        self.ed_obs.textChanged.connect(self._preview)
        c_prev = Card(7, "Como vai ficar (montado sozinho)")
        c_prev.add(campo("Incluir alguma observação", self.ed_obs, extra="(opcional)"))
        c_prev.add(rotulo("Título")); c_prev.add(self.prev_tit)
        c_prev.add(rotulo("Observação")); c_prev.add(self.prev_obs)
        c_prev.add(rotulo("Registrada no Fracttal como")); c_prev.add(self.prev_meta)
        lay.addWidget(c_prev)
        lay.addStretch(1)

        # rodapé fixo
        row = QHBoxLayout(); row.setContentsMargins(18, 6, 18, 2)
        b_cancel = QPushButton("Cancelar"); b_cancel.setObjectName("secondary"); b_cancel.clicked.connect(self.reject)
        self.btn = QPushButton("Criar OSs"); self.btn.setEnabled(False); self.btn.clicked.connect(self._criar)
        row.addWidget(b_cancel); row.addWidget(self.btn, 1)
        outer.addLayout(row)
        self.hint = QLabel(""); self.hint.setObjectName("uiAjuda"); self.hint.setContentsMargins(18, 0, 18, 8)
        outer.addWidget(self.hint)

        self._fill_clientes()
        self._carregar_resp()
        self._carregar_classif()
        self._carregar_falha_listas()
        self._fin.chk.setChecked(True)          # remoto resolvido = default
        self._on_tipo(0); self._on_cat(0); self._seg_acao.set_index(0, emit=False); self._on_acao(0)

    # ── carga async de tipos/classif ──
    def _carregar_classif(self):
        self._wt = ApiWorker(api.get_tipos_classif)
        self._wt.ok.connect(self._set_classif); self._wt.erro.connect(self._classif_err)
        self._wt.start()

    @slot_seguro
    def _classif_err(self, m):
        self._wt = None
        self.hint.setText("⚠ tipos de tarefa não carregaram (sessão expirada?). Relogue e reabra o COS.")
        self._upd()

    # ── bloco "O ativo falhou?" (F4) ──
    def _carregar_falha_listas(self):
        self._wf = ApiWorker(api.get_falha_listas)
        self._wf.ok.connect(self._set_falha_listas); self._wf.erro.connect(lambda m: setattr(self, "_wf", None))
        self._wf.start()

    @slot_seguro
    def _set_falha_listas(self, d):
        self._wf = None
        d = d or {}
        def fill(cb, itens):
            cb.blockSignals(True); cb.clear(); cb.addItem("— selecione —", None)
            for it in itens:
                cb.addItem(it.get("description") or "?", it.get("id"))
            cb.blockSignals(False)
        fill(self.cb_ftipo, d.get("tipos") or [])
        fill(self.cb_fcausa, d.get("causas") or [])
        fill(self.cb_fdetec, d.get("metodos") or [])
        if self.chk_falha.isChecked():
            self._sugerir_falha()

    @slot_seguro
    def _on_falha(self, on):
        self._falha_box.setVisible(on)
        if on:
            self._sugerir_falha()

    def _sel_desc(self, cb, desc):
        alvo = (desc or "").strip().lower()
        i = cb.findText(desc)
        if i < 0:                                   # 1) igual sem diferença de caixa
            for j in range(cb.count()):
                if (cb.itemText(j) or "").strip().lower() == alvo:
                    i = j; break
        if i < 0 and alvo:                          # 2) prefixo (tolera sufixos tipo " (MCO)")
            for j in range(cb.count()):
                t = (cb.itemText(j) or "").strip().lower()
                if t and (t.startswith(alvo) or alvo.startswith(t)):
                    i = j; break
        if i >= 0:
            cb.setCurrentIndex(i)

    def _sugerir_falha(self):
        """Sugere Tipo/Causa (editáveis). Detecção é SEMPRE Monitoramento (Levi 14/07).
        Inspeção tem Tipo/Causa próprios; senão, pela categoria da ocorrência."""
        if self._tipo_os() == cs.TIPO_INSPECAO:
            self._sel_desc(self.cb_ftipo, "Desligamento Inversor")
            self._sel_desc(self.cb_fcausa, "Perda de sinal em redes de comunicação")
        elif self._cat == cs.CAT_C:
            self._sel_desc(self.cb_ftipo, "Conectividade/Comunicação")
            self._sel_desc(self.cb_fcausa, "Perda de sinal em redes de comunicação")
        elif self._cat == cs.CAT_B:
            self._sel_desc(self.cb_ftipo, "Desligamento Inversor")
        else:
            self._sel_desc(self.cb_ftipo, "Oscilações de Tensão")
            self._sel_desc(self.cb_fcausa, "Queda de energia")
        self._sel_desc(self.cb_fdetec, "Monitoramento de Condição Online (MCO)")

    @slot_seguro
    def _set_classif(self, d):
        self._wt = None
        self._classif = d or {}
        self._upd()

    def _by_desc(self, chave, desc):
        for it in (self._classif or {}).get(chave, []):
            if (it.get("description") or "").strip().lower() == desc.strip().lower():
                return it.get("id")
        return None

    # ── tipo / categoria / ação ──
    @slot_seguro
    def _on_tipo(self, i):
        insp = (self._seg_tipo.index() == 1)
        # Inspeção começa na categoria C (comunicação) e nasce ABERTA p/ o técnico; Religamento na A, concluída.
        if insp:
            self._seg_cat.set_index(2)
        elif self._seg_cat.index() == 2:
            self._seg_cat.set_index(0)
        if hasattr(self, "_fin"):
            self._fin.chk.setChecked(not insp)
        if hasattr(self, "chk_falha"):        # "ativo falhou" SEMPRE marcado (editável)
            self.chk_falha.setChecked(True)   # Inspeção também nasce c/ o bloco marcado — técnico ajusta depois
        self._preview()

    @slot_seguro
    def _on_cat(self, i):
        self._cat = [cs.CAT_A, cs.CAT_B, cs.CAT_C][i]
        self._page_a.setVisible(i == 0)      # mostra só a página da categoria ativa (card encolhe)
        self._page_b.setVisible(i == 1)
        self._page_c.setVisible(i == 2)
        if hasattr(self, "info_ansi"):
            self.info_ansi.setVisible(i == 0)     # "!" da tabela ANSI só faz sentido na categoria A
        self._preview()

    @slot_seguro
    def _on_acao(self, i):
        self._preview()

    def _remoto(self):
        return self._seg_acao.index() == 0

    def _codigos(self):
        if self._cat != cs.CAT_A:          # proteção só existe na categoria A; B/C = --/--
            return []
        return [c for c, ch in self._chips.items() if ch.isChecked()]

    def _equip_nome(self, asset):
        return api._asset_short_name(asset) if asset else (self.cb_onde.currentText() if self._cat == cs.CAT_A else "Equipamento")

    def _acao_txt(self):
        if self._cat == cs.CAT_A:
            return cs.ACAO_REMOTO if self._remoto() else cs.ACAO_LOCAL
        return cs.ACAO_DEFAULT_CAT[self._cat]

    def _tipo_os(self):
        return cs.TIPO_INSPECAO if self._seg_tipo.index() == 1 else cs.TIPO_RELIGAMENTO

    def _falha(self, equip=""):
        """Texto 'Falha:' por categoria (A=onde genérico; B=equipamento marcado; C=fixo)."""
        if self._cat == cs.CAT_A:
            return cs.falha_texto(cs.CAT_A, self.cb_onde.currentText(), self._codigos())
        if self._cat == cs.CAT_B:
            return cs.falha_texto(cs.CAT_B, equip or "Equipamento", motivo_b=self.cb_falha_b.currentText())
        return cs.falha_texto(cs.CAT_C, causa_c=self.cb_causa_c.currentText())

    def _obs_final(self, obs_pipe):
        """Observação = padrão pipe + (se houver) comentário livre do operador em nova linha."""
        extra = self.ed_obs.text().strip()
        return obs_pipe + ("\n" + extra if extra else "")

    def _meta_html(self):
        """Linha read-only p/ o operador saber com que Tipo/Classificação/Criticidade a OS será criada."""
        g = "color:#A6E22E;font-weight:700"
        tipo = self._tarefa_nome()
        classif = "Emergencial / Elétrica" if self._tipo_os() == cs.TIPO_INSPECAO else "Religamento / Elétrica"
        sep = " &nbsp;&nbsp;·&nbsp;&nbsp; "
        return (f"Tipo de tarefa <span style='{g}'>{tipo}</span>{sep}"
                f"Classificação <span style='{g}'>{classif}</span>{sep}"
                f"Criticidade <span style='{g}'>Muito alto</span>")

    # ── preview + permissivo ──
    @slot_seguro
    def _preview(self, *_):
        if self._terceiros:
            asset = self._generic_asset() if self._usi() else None
        else:
            asset = next((a for a in self._assets if a["id"] in self._checked), None)
        equip = self._equip_nome(asset)
        usina = api._usina_short(asset.get("usina")) if asset else (self._usi() or "{usina}")
        acao = self._acao_txt()
        falha = self._falha(equip)
        motivo = cs.motivo_titulo(self._tipo_os(), equip, acao)
        tit = api.perf_os_nome(asset, motivo) if asset else f"[{usina}][{equip}] - {motivo}"
        self.prev_tit.setText(tit + ("   (cada OS usa o seu ativo)" if len(self._checked) > 1 else ""))
        self.prev_obs.setText(self._obs_final(cs.observacao(usina, self._codigos(), acao, falha)))
        self.prev_meta.setText(self._meta_html())
        # permissivo 86
        if self._cat == cs.CAT_A and cs.exige_equipe_campo(self._codigos()):
            self.lbl_perm.setText("⚠ Impedimento ativo (86) — religamento remoto não autorizado. "
                                  "Abra para equipe em campo (Ação: Local).")
        elif self._cat == cs.CAT_C:
            self.lbl_perm.setText("Falha de comunicação — técnico faz inspeção local; sem religamento remoto.")
        else:
            self.lbl_perm.setText("Sem impedimento — religamento pode ser remoto." if self._remoto()
                                  else "Local — a OS abre para a equipe em campo resolver.")
        self._seg_acao.setEnabled(self._cat == cs.CAT_A)     # B/C têm ação fixa
        self._upd_oos()
        self._upd()

    def _sync_fin(self, on):
        self._campo_fim.setVisible(on and self._modo == 0)
        for (_r, _de, de_fim, arrow, _l) in self._date_rows:  # modo multi-data: mostra a conclusão por linha
            arrow.setVisible(on); de_fim.setVisible(on)
        self._preview()

    def _oos_ativo(self):
        """Fora de serviço = a OS NÃO tem data de conclusão (nasce aberta). Se já foi realizada
        (tem fim), o ativo já voltou → não está fora de serviço."""
        return not self._fin.is_finalizar()

    def _fmt_oos_lbl(self, lbl):
        lbl.setText("Fora de Serviço: Sim" if self._oos_ativo() else "Fora de Serviço: Não")
        lbl.setStyleSheet(f"background:transparent;font-size:11.5px;color:{MUTED};")   # cinza suave, baixo contraste

    def _upd_oos(self):
        if not hasattr(self, "lbl_oos"):
            return
        if self._oos_ativo():
            self.lbl_oos.setText("Sim — ativo segue fora de serviço (desde a data do evento)")
        else:
            self.lbl_oos.setText("Não — OS já tem conclusão, o ativo voltou")
        if hasattr(self, "lbl_oos_ev"):
            self._fmt_oos_lbl(self.lbl_oos_ev)
        for t in self._date_rows:
            self._fmt_oos_lbl(t[4])

    @slot_seguro
    def _on_modo(self, i):
        self._modo = i
        mesmo = (i == 1)
        self._campo_ev.setVisible(not mesmo)
        self._campo_fim.setVisible((not mesmo) and self._fin.is_finalizar())
        self._datas_multi.setVisible(mesmo)
        if mesmo and not self._date_rows:
            self._add_data()
        if mesmo and len(self._checked) > 1:                  # mesmo ativo → mantém só 1 marcado
            self._checked = {next(iter(self._checked))}
            self._refresh_ativos()
        self._preview(); self._upd()

    def _add_data(self, *_):
        row = QWidget(); row.setStyleSheet("background:transparent;")
        h = QHBoxLayout(row); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(8)
        de = QDateTimeEdit(); de.setCalendarPopup(True); de.setDisplayFormat("dd/MM/yyyy HH:mm")
        de.setDateTime(QDateTime.currentDateTime().addSecs(-600)); de.setMinimumWidth(155)
        b_now = QPushButton("Agora"); b_now.setObjectName("secondary")
        b_now.clicked.connect(lambda _=0, d=de: d.setDateTime(QDateTime.currentDateTime().addSecs(-600)))
        arrow = QLabel("→")
        de_fim = QDateTimeEdit(); de_fim.setCalendarPopup(True); de_fim.setDisplayFormat("dd/MM/yyyy HH:mm")
        de_fim.setDateTime(QDateTime.currentDateTime()); de_fim.setMinimumWidth(155)
        de.dateTimeChanged.connect(lambda _=0, d=de, f=de_fim: f.setDateTime(d.dateTime().addSecs(600)))
        de.dateTimeChanged.connect(self._preview)
        lbl_oos = QLabel(); lbl_oos.setStyleSheet("background:transparent;")   # "Fora de Serviço: Sim/Não" por OS
        b_del = QPushButton("Remover"); b_del.setObjectName("secondary")
        b_del.clicked.connect(lambda _=0, r=row: self._del_data(r))
        h.addWidget(de); h.addWidget(b_now); h.addWidget(arrow); h.addWidget(de_fim)
        h.addWidget(b_del); h.addWidget(lbl_oos); h.addStretch(1)   # "Fora de Serviço" à direita do Remover
        fin = self._fin.is_finalizar()
        arrow.setVisible(fin); de_fim.setVisible(fin)
        self._fmt_oos_lbl(lbl_oos)
        self._datas_lay.insertWidget(self._datas_lay.count() - 1, row)   # antes do stretch
        self._date_rows.append((row, de, de_fim, arrow, lbl_oos))
        self._upd()

    def _del_data(self, row):
        self._date_rows = [t for t in self._date_rows if t[0] is not row]
        row.setParent(None); row.deleteLater()
        self._upd()

    # ── usina de terceiros (ativo genérico) ──
    def _build_terc_row(self):
        """Linha com o interruptor 'Usina de terceiros' + rótulo/explicação."""
        self.sw_terc = ToggleSwitch()
        self.sw_terc.toggled.connect(self._tog_terceiros)
        row = QFrame(); row.setObjectName("tercRow")
        row.setStyleSheet("QFrame#tercRow{background:#0F1526;border:1px solid rgba(255,255,255,0.07);"
                          "border-radius:10px;}")
        h = QHBoxLayout(row); h.setContentsMargins(13, 9, 14, 9); h.setSpacing(12)
        h.addWidget(self.sw_terc)
        tw = QVBoxLayout(); tw.setSpacing(1)
        t1 = QLabel("Usina de terceiros")
        t1.setStyleSheet("background:transparent;font-size:13.5px;font-weight:600;color:#E6EAF2;")
        t2 = QLabel("O&M de usina que não é ativo cadastrado — Cliente/Usina livres + ativo genérico")
        t2.setStyleSheet(f"background:transparent;font-size:11.5px;color:{MUTED};")
        tw.addWidget(t1); tw.addWidget(t2)
        h.addLayout(tw); h.addStretch(1)
        return row

    def _build_gen_note(self):
        """Cartão do ativo genérico — aparece no lugar da tabela quando 'usina de terceiros' está ligado."""
        f = QFrame(); f.setObjectName("genNote")
        f.setStyleSheet("QFrame#genNote{background:#0F1526;border:1px dashed rgba(239,177,60,0.55);"
                        "border-radius:10px;}")
        h = QHBoxLayout(f); h.setContentsMargins(14, 12, 14, 12); h.setSpacing(12)
        ic = QLabel(); ic.setPixmap(icone_pix("layers", "#EFB13C", 20)); ic.setFixedWidth(20)
        ic.setStyleSheet("background:transparent;"); h.addWidget(ic)
        tw = QVBoxLayout(); tw.setSpacing(2)
        t1 = QLabel("Grid Co. — Emergências e outros pontos")
        t1.setStyleSheet("background:transparent;font-size:13.5px;font-weight:600;color:#E6EAF2;")
        t2 = QLabel("ativo genérico · usado quando a usina não é cadastrada no Fracttal")
        t2.setStyleSheet(f"background:transparent;font-size:11.5px;color:{MUTED};")
        tw.addWidget(t1); tw.addWidget(t2)
        h.addLayout(tw); h.addStretch(1)
        pin = QLabel("automático")
        pin.setStyleSheet("background:rgba(239,177,60,0.14);color:#EFB13C;font-size:10px;"
                          "font-weight:700;border-radius:5px;padding:4px 9px;")
        h.addWidget(pin)
        return f

    def _generic_asset(self):
        """Asset sintético do genérico com a usina/cliente digitados → alimenta título e criação."""
        return {"id": GENERICO_ID, "code": "GRID", "id_type_item": 2, "id_parent": None,
                "id_group_task": None, "tipo": "Usina", "description": GENERICO_DESC,
                "label": "Grid Co. - Emergências e outros pontos",
                "usina": (self._usi() or "").strip(), "cliente": (self._cli() or "").strip()}

    @slot_seguro
    def _tog_terceiros(self, on=False):
        self._terceiros = bool(on)
        on = self._terceiros
        if on:
            for cb, ph in ((self.cb_cli, "Digite o cliente…"), (self.cb_usi, "Digite a usina…")):
                cb.blockSignals(True); cb.clear(); cb.setEditable(True)
                cb.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
                cb.setCurrentText(""); cb.lineEdit().setPlaceholderText(ph); cb.blockSignals(False)
            self.cb_cli.lineEdit().textEdited.connect(self._preview)   # lineEdit é novo a cada setEditable
            if not self._terc_wired:                                   # cb_usi fica editável sempre → liga 1x
                self.cb_usi.lineEdit().textEdited.connect(self._preview)
                self._terc_wired = True
            self._checked = set()
        else:
            self.cb_cli.setEditable(False)
            self._fill_clientes()                                      # restaura os dropdowns
        for w in (self._lin_tipo, self._lbl_ativos, self._sel_bar, self.tbl, self.sel_lbl):
            w.setVisible(not on)
        self.gen_note.setVisible(on)
        if not on:
            self._refresh_ativos()
        self._preview()

    # ── cascata do ativo ──
    @staticmethod
    def _carteira(usina):
        """Carteira = prefixo do label da usina ('Thopen - Altair 1 - SP' → 'Thopen'). Fonte de verdade:
        o campo 'cliente' do ativo às vezes diverge do prefixo (dado inconsistente do Fracttal)."""
        return (usina or "").split(" - ", 1)[0].strip()

    def _carteira_de(self, a):
        """Carteira 'de verdade' do ativo: prefixo da usina se for nomeada ('X - Usina - UF'), senão o
        campo cliente (materiais/inventário e o plano TESTE não têm o prefixo → usam o cliente)."""
        u = a.get("usina") or ""
        return self._carteira(u) if " - " in u else (a.get("cliente") or "").strip()

    def _fill_clientes(self):
        # clientes REAIS = os que têm ativo de equipamento (o catálogo tem material/inventário à parte,
        # às vezes com tipo de equipamento mas usina/carteira própria — por isso usa-se o campo cliente).
        self._clientes_reais = {a.get("cliente") for a in self._assets
                                if a.get("tipo") in _CARTEIRA_EQUIP and a.get("cliente")}
        clientes = sorted(self._clientes_reais)
        self.cb_cli.blockSignals(True); self.cb_cli.clear()
        self.cb_cli.addItem("— Selecione o cliente —"); self.cb_cli.addItems(clientes)
        self.cb_cli.blockSignals(False)
        self._fill_usinas()            # usina LIVRE desde o início (lista todas)

    def _cli(self):
        if self._terceiros:
            return (self.cb_cli.currentText() or "").strip() or None
        return self.cb_cli.currentText() if self.cb_cli.currentIndex() > 0 else None

    def _usi(self):
        if self._terceiros:
            return (self.cb_usi.currentText() or "").strip() or None
        return self.cb_usi.currentText() if self.cb_usi.currentIndex() > 0 else None

    def _fill_usinas(self):
        """Popula a usina: filtrada pela carteira do cliente selecionado, ou TODAS se nenhum. Preserva
        a usina escolhida se ainda válida."""
        cli, cur = self._cli(), self._usi()
        # base = usinas de equipamento cuja CARTEIRA é um cliente real (exclui inventário/material)
        base = [a for a in self._assets if a.get("usina") and a.get("tipo") in _CARTEIRA_EQUIP
                and self._carteira_de(a) in self._clientes_reais]
        if cli:
            usinas = sorted({a["usina"] for a in base if self._carteira_de(a) == cli})
        else:                          # LIVRE: todas as usinas de planta (sem materiais)
            usinas = sorted({a["usina"] for a in base})
        self.cb_usi.blockSignals(True); self.cb_usi.clear()
        self.cb_usi.addItem("— Selecione a usina —"); self.cb_usi.addItems(usinas)
        if cur and cur in usinas:
            self.cb_usi.setCurrentIndex(self.cb_usi.findText(cur))
        self.cb_usi.setEnabled(True); self.cb_usi.blockSignals(False)

    @slot_seguro
    def _on_cli(self, *_):
        if self._terceiros:
            return
        self._fill_usinas()
        self._on_usi()

    @slot_seguro
    def _on_usi(self, *_):
        if self._terceiros:
            return
        usi = self._usi()
        if usi and " - " in usi:       # usina nomeada → auto-preenche o Cliente pela carteira (prefixo)
            cart = self._carteira(usi)
            if cart and self.cb_cli.currentText() != cart and self.cb_cli.findText(cart) >= 0:
                self.cb_cli.blockSignals(True)
                self.cb_cli.setCurrentIndex(self.cb_cli.findText(cart))
                self.cb_cli.blockSignals(False)
                self._fill_usinas()    # re-filtra a usina p/ a carteira (mantém a seleção)
        self._checked.clear()          # troca de usina zera a seleção (não misturar ativos de usinas)
        usi = self._usi()
        tipos = sorted({a["tipo"] for a in self._assets
                        if a.get("usina") == usi and a.get("tipo") in cs.COS_EQUIP}) if usi else []
        self.cb_tipo.blockSignals(True); self.cb_tipo.clear()
        self.cb_tipo.addItem("Todos os tipos"); self.cb_tipo.addItems(tipos)
        self.cb_tipo.setEnabled(bool(tipos)); self.cb_tipo.blockSignals(False)
        self._refresh_ativos()

    def _cands(self):
        usi = self._usi()              # a usina (label único) é a chave — cliente é derivado dela
        if not usi:
            return []
        tipo = self.cb_tipo.currentText() if self.cb_tipo.currentIndex() > 0 else None
        txt = (self.busca.text() or "").strip().lower()
        out = []
        for a in self._assets:
            if a.get("usina") != usi or a.get("tipo") not in ALLOWED_TIPOS:
                continue
            if tipo and a.get("tipo") != tipo:
                continue
            if txt and txt not in (a.get("label") or "").lower():
                continue
            out.append(a)
        return sorted(out, key=lambda x: x.get("label") or "")

    def _paint_row(self, it, chk):
        it.setForeground(QBrush(QColor("#E6EAF2") if chk else QColor(MUTED)))
        it.setBackground(QBrush(QColor(166, 226, 46, 22)) if chk else QBrush(Qt.GlobalColor.transparent))

    @slot_seguro
    def _refresh_ativos(self, *_):
        self.tbl.blockSignals(True); self.tbl.setRowCount(0)
        for a in self._cands():
            r = self.tbl.rowCount(); self.tbl.insertRow(r)
            it = QTableWidgetItem(a.get("label") or a.get("code") or "?")
            it.setToolTip(a.get("label") or "")
            it.setData(Qt.ItemDataRole.UserRole, a)
            it.setFlags((it.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsEditable)
            chk = a["id"] in self._checked
            it.setCheckState(Qt.CheckState.Checked if chk else Qt.CheckState.Unchecked)
            self._paint_row(it, chk)
            self.tbl.setItem(r, 0, it)
        self.tbl.blockSignals(False)
        self._preview()

    @slot_seguro
    def _on_check_multi(self, it):
        a = it.data(Qt.ItemDataRole.UserRole)
        if not isinstance(a, dict):
            return
        chk = it.checkState() == Qt.CheckState.Checked
        if chk and self._modo == 1:            # mesmo ativo → só 1 marcado por vez
            self._checked.clear()
            self.tbl.blockSignals(True)
            for r in range(self.tbl.rowCount()):
                o = self.tbl.item(r, 0)
                if o is not None and o is not it:
                    o.setCheckState(Qt.CheckState.Unchecked); self._paint_row(o, False)
            self.tbl.blockSignals(False)
        (self._checked.add if chk else self._checked.discard)(a["id"])
        self._paint_row(it, chk)
        self._preview()

    def _marcar_todos(self, marcar=True):
        self.tbl.blockSignals(True)
        for r in range(self.tbl.rowCount()):
            it = self.tbl.item(r, 0); a = it.data(Qt.ItemDataRole.UserRole)
            it.setCheckState(Qt.CheckState.Checked if marcar else Qt.CheckState.Unchecked)
            self._paint_row(it, marcar)
            if isinstance(a, dict):
                (self._checked.add if marcar else self._checked.discard)(a["id"])
        self.tbl.blockSignals(False)
        self._preview()

    # ── responsável ──
    def _carregar_resp(self):
        self.cb_resp.clear(); self.cb_resp.addItem("carregando…", None)
        self.hint.setText("carregando responsáveis…")
        self._wr = ApiWorker(api.get_responsaveis)
        self._wr.ok.connect(self._set_resp); self._wr.erro.connect(self._resp_err)
        self._wr.start()

    @slot_seguro
    def _resp_err(self, m):
        self._wr = None
        self.cb_resp.clear(); self.cb_resp.addItem("⚠ falha — relogue e clique em ↻", None)
        self.hint.setText("⚠ responsável: " + str(m))

    @slot_seguro
    def _set_resp(self, pessoas):
        self._wr = None; self.hint.setText("")
        self.cb_resp.clear(); self.cb_resp.addItem(_SEL, None)
        for p in sorted(pessoas or [], key=lambda x: (x.get("name") or "").lower()):
            self.cb_resp.addItem(p.get("name") or p.get("code") or "?", p)
        self._upd()

    # ── habilita botão ──
    def _upd(self, *_):
        if not hasattr(self, "btn"):
            return
        if self._terceiros:            # 1 ativo genérico → habilita pelo Cliente+Usina digitados
            ok = bool(self._cli() and self._usi())
            if self._modo == 1:
                self.btn.setEnabled(ok and bool(self._date_rows))
            else:
                self.btn.setEnabled(ok)
            return
        n = len(self._checked)
        # Proteção/responsável/tipo são checados NO CLIQUE (com mensagem) — o botão NUNCA fica travado em silêncio.
        if self._modo == 1:
            nd = len(self._date_rows)
            self.sel_lbl.setText(f"{n} ativo · {nd} data(s) → {nd if n else 0} OS")
            self.btn.setEnabled(bool(n and nd))
        else:
            self.sel_lbl.setText(f"{n} ativo(s) marcado(s)")
            self.btn.setEnabled(bool(n))

    # ── mapeia a ação → nome do tipo de tarefa do Fracttal ──
    def _tarefa_nome(self):
        if self._tipo_os() == cs.TIPO_INSPECAO:
            return "Corretiva Emergencial"
        if self._acao_txt() == cs.ACAO_REMOTO:
            return "Religamento Remoto"
        return "Religamento"

    def _tipo_dict(self):
        nome = self._tarefa_nome()
        d = {"id_main": self._by_desc("tipos", nome), "id_priorities": api.CRITICIDADE_MUITO_ALTO}
        c1nome = "Emergencial" if self._tipo_os() == cs.TIPO_INSPECAO else "Religamento"
        c1 = self._by_desc("c1", c1nome)
        if c1:
            d["id_c1"] = c1; d["desc_c1"] = c1nome
            c2 = self._by_desc("c2", "Elétrica")
            if c2:
                d["id_c2"] = c2; d["desc_c2"] = "Elétrica"
        return d

    @staticmethod
    def _opts(*opcoes):
        return [{"description": o} for o in opcoes]

    def _subtarefas(self, remoto, dados):
        """Subtarefas OBRIGATÓRIAS por tipo. Escolhas viram tipo Lista (menu, id 7). Remoto → já
        respondidas (value); campo → em branco p/ o técnico responder no Fracttal."""
        LST = 7   # tipo Lista (DROPDOWN)
        if self._tipo_os() == cs.TIPO_INSPECAO:
            subs = [
                {"description": "Equipamento e sintoma", "id_task_form_item_type": 1},
                {"description": "Diagnóstico", "id_task_form_item_type": LST,
                 "dropdown_options": self._opts("Desligado", "Só sem comunicação (segue gerando)")},
                {"description": "Ação", "id_task_form_item_type": LST,
                 "dropdown_options": self._opts("Religamento local", "Operador avisado")},
                {"description": "Normalizado?", "id_task_form_item_type": LST,
                 "dropdown_options": self._opts("Sim", "Não", "Parcial")},
            ]
            vals = [dados["falha"], "", "", ""]        # técnico preenche diagnóstico/ação/resultado
        else:
            subs = [
                {"description": "Categoria e proteção", "id_task_form_item_type": 1},
                {"description": "Onde atuou", "id_task_form_item_type": 1},
                {"description": "Foi necessário religamento?", "id_task_form_item_type": LST,
                 "dropdown_options": self._opts("Sim", "Não — já normalizado")},
                {"description": "Resultado", "id_task_form_item_type": LST,
                 "dropdown_options": self._opts("Normalizado", "Persistiu", "Parcial")},
            ]
            vals = [dados["cat_prot"], dados["onde"],
                    ("Sim" if remoto else ""), ("Normalizado" if remoto else "")]
        for s in subs:
            s["is_required"] = True
        return subs, (vals if remoto else None)

    # ── criar ──
    @slot_seguro
    def _criar(self, *_):            # o sinal clicked passa 'checked' (bool) → absorve p/ não dar TypeError
        if self._terceiros:
            if not (self._cli() and self._usi()):
                QMessageBox.warning(self, "Usina de terceiros",
                                    "Preencha o Cliente e a Usina (texto livre)."); return
            assets = [self._generic_asset()]
        else:
            assets = [a for a in self._assets if a["id"] in self._checked]
            if not assets:
                QMessageBox.warning(self, "Ativos", "Marque ao menos um ativo."); return
        p = self.cb_resp.currentData()
        if not isinstance(p, dict) or not p.get("id_personnel"):
            QMessageBox.warning(self, "Responsável", "Escolha o responsável (requerido por)."); return
        tipo = self._tipo_dict()
        if not tipo.get("id_main"):
            QMessageBox.warning(self, "Tipo de tarefa", "Os tipos ainda não carregaram (ou a sessão "
                                "expirou). Aguarde um instante ou relogue e tente de novo."); return
        if self._cat == cs.CAT_A and not self._codigos():
            QMessageBox.warning(self, "Proteção", "Marque ao menos uma proteção que atuou "
                                "(categoria A · Proteções)."); return
        if self.chk_falha.isChecked() and not (self.cb_ftipo.currentData() and self.cb_fcausa.currentData()
                                                and self.cb_fdetec.currentData()):
            QMessageBox.warning(self, "O ativo falhou?", "Preencha Tipo de falha, Causa e Método de detecção "
                                "(ou desmarque 'O ativo falhou?')."); return
        brt = _dt.timezone(_dt.timedelta(hours=-3))
        remoto = self._fin.is_finalizar()
        acao = self._acao_txt()
        codigos = self._codigos()
        cat_prot = f"{cs.CATEGORIAS[self._cat]} — {cs.juntar_codigos(codigos)}" if self._cat == cs.CAT_A \
                   else (f"{cs.CATEGORIAS[self._cat]} — {self.cb_falha_b.currentText()}" if self._cat == cs.CAT_B
                         else self.cb_causa_c.currentText())
        onde_val = self.cb_onde.currentText() if self._cat == cs.CAT_A else "—"
        subs_ref, resp_ref = self._subtarefas(remoto, {
            "falha": self._falha(self._equip_nome(assets[0])), "cat_prot": cat_prot, "onde": onde_val})
        falha_dict = None
        if self.chk_falha.isChecked():
            falha_dict = {"id_type": self.cb_ftipo.currentData(), "type_desc": self.cb_ftipo.currentText(),
                          "id_cause": self.cb_fcausa.currentData(), "cause_desc": self.cb_fcausa.currentText(),
                          "id_detection": self.cb_fdetec.currentData(), "detection_desc": self.cb_fdetec.currentText(),
                          "id_severity": self.cb_fsev.currentData(), "severity_desc": self.cb_fsev.currentText(),
                          "id_damage": self.cb_fdano.currentData(), "damage_desc": self.cb_fdano.currentText(),
                          "out_of_service": self._oos_ativo()}   # derivado: sem data de conclusão → fora de serviço

        # ── modo "Mesmo ativo · várias datas" → N OS (1 por data) para o MESMO ativo ──
        if self._modo == 1:
            if not self._date_rows:
                QMessageBox.warning(self, "Datas", "Adicione ao menos uma data."); return
            a = assets[0]; equip = self._equip_nome(a); usina = api._usina_short(a.get("usina"))
            titulo = api.perf_os_nome(a, cs.motivo_titulo(self._tipo_os(), equip, acao))
            obs = self._obs_final(cs.observacao(usina, codigos, acao, self._falha(equip)))
            datas = []
            for (_r, de, de_fim, _a, _l) in self._date_rows:
                ini = de.dateTime().toPyDateTime().replace(tzinfo=brt)
                if remoto:
                    fim = de_fim.dateTime().toPyDateTime().replace(tzinfo=brt)
                    if fim < ini:
                        QMessageBox.warning(self, "Datas", f"Conclusão anterior ao evento (linha {ini:%d/%m %H:%M})."); return
                    datas.append((ini, fim))
                else:
                    datas.append(ini)
            finalizar = ({"to_in_review": self._fin.to_in_review(), "id_assigned_user": p.get("id_personnel"),
                          "name": p.get("name"), "respostas": resp_ref} if remoto else None)
            self.btn.setEnabled(False)
            self.hint.setText(f"criando {len(datas)} OS… (pode levar alguns segundos)")
            self._wc = ApiWorker(api.create_work_orders_datas, a, titulo, self._tarefa_nome(), subs_ref,
                                 datas, p.get("code"), p.get("name"), p.get("id_personnel"),
                                 None, obs, tipo, finalizar, None, falha_dict)
            self._wc.ok.connect(self._ok); self._wc.erro.connect(self._err)
            self._wc.start()
            return

        # ── modo "Vários ativos · 1 data" → 1 OS por ativo ──
        event_date = self.de.dateTime().toPyDateTime().replace(tzinfo=brt)
        finalizar = None
        if remoto:
            fim = self.de_fim.dateTime().toPyDateTime().replace(tzinfo=brt)
            if fim < event_date:
                QMessageBox.warning(self, "Datas", "A conclusão não pode ser anterior ao evento."); return
            finalizar = {"to_in_review": self._fin.to_in_review(), "final_date": fim,
                         "id_assigned_user": p.get("id_personnel"), "name": p.get("name"), "respostas": resp_ref}
        por_ativo = {}
        for a in assets:
            equip = self._equip_nome(a); usina = api._usina_short(a.get("usina"))
            motivo = cs.motivo_titulo(self._tipo_os(), equip, acao)
            obs = self._obs_final(cs.observacao(usina, codigos, acao, self._falha(equip)))
            por_ativo[a["code"]] = {"description": api.perf_os_nome(a, motivo), "note": obs}
        self.btn.setEnabled(False)
        self.hint.setText(f"criando {len(assets)} OS… (pode levar alguns segundos)")
        self._wc = ApiWorker(api.create_work_orders_bulk, assets, "Religamento", self._tarefa_nome(),
                             subs_ref, "", p.get("code"), p.get("name"), p.get("id_personnel"),
                             None, "", tipo, finalizar, event_date, None, None, por_ativo, falha_dict)
        self._wc.ok.connect(self._ok); self._wc.erro.connect(self._err)
        self._wc.start()

    def _voltar(self):
        if self._on_voltar:
            self._on_voltar()

    def accept(self):
        self._voltar()

    def reject(self):
        self._voltar()

    @slot_seguro
    def _ok(self, res):
        self._wc = None; self.btn.setEnabled(True)
        res = res if isinstance(res, list) else []
        ok = [r for r in res if r.get("ok")]; fail = [r for r in res if not r.get("ok")]
        folios = [str(r["os"].get("wo_folio")) for r in ok if r.get("os", {}).get("wo_folio")]
        msg = f"{len(ok)} OS criada(s)" + (f" — Nº {', '.join(folios)}" if folios else "") + "."
        avisos = [r["os"]["aviso"] for r in ok if r.get("os", {}).get("aviso")]
        if avisos:
            msg += "\n\nAvisos:\n- " + "\n- ".join(avisos[:6])
        if fail:
            msg += "\n\nFalhas:\n- " + "\n- ".join(
                f"{r.get('code') or r.get('data')}: {r.get('erro')}" for r in fail[:8])
        if ok:
            QMessageBox.information(self, "OSs criadas", msg); self._reset()
        else:
            QMessageBox.critical(self, "Erro", msg or "Nenhuma OS criada."); self.hint.setText("")

    @slot_seguro
    def _err(self, m):
        self._wc = None; self.btn.setEnabled(True); self.hint.setText("")
        QMessageBox.critical(self, "Erro ao criar OSs", m)

    def _reset(self):
        """Limpa TODOS os campos e volta ao estado inicial (após criar as OSs) — espelha o __init__.
        Mantém só o Responsável selecionado (mesmo analista costuma criar em sequência)."""
        while self._date_rows:                              # datas do modo "várias datas"
            self._del_data(self._date_rows[0][0])
        self._checked = set()                               # ativos marcados
        if self._terceiros:                                 # sai do modo terceiros → restaura dropdowns
            self.sw_terc.setChecked(False)                  # dispara _tog_terceiros(False) + _fill_clientes
        self.busca.blockSignals(True); self.busca.clear(); self.busca.blockSignals(False)
        if self.cb_cli.count():
            self.cb_cli.setCurrentIndex(0)                  # → _on_cli limpa usina/tipo/ativos
        self.de.setDateTime(QDateTime.currentDateTime().addSecs(-600))
        self.de_fim.setDateTime(QDateTime.currentDateTime())
        self.ed_obs.blockSignals(True); self.ed_obs.clear(); self.ed_obs.blockSignals(False)
        for ch in self._chips.values():                     # proteções
            ch.blockSignals(True); ch.setChecked(False); ch.blockSignals(False)
        for cb in (self.cb_onde, self.cb_falha_b, self.cb_causa_c):
            if cb.count():
                cb.setCurrentIndex(0)
        # segmentados de volta ao início: Tipo=Religamento · Categoria=A · Modo=Vários ativos · Ação=Remoto
        self._seg_tipo.set_index(0, emit=False)
        self._seg_cat.set_index(0, emit=False)
        self._seg_modo.set_index(0, emit=False); self._modo = 0
        self._on_modo(0)
        self._fin.chk.setChecked(True)                      # remoto resolvido = default
        self._on_tipo(0); self._on_cat(0)
        self._seg_acao.set_index(0, emit=False); self._on_acao(0)
        self._refresh_ativos()
        self._preview(); self._upd()
        self.hint.setText("")
