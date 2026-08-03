"""Histórico de OS — 'Histórico Geral' (por criador: default = usuário logado, pode trocar p/ outros
ou Todos) e 'Atribuídas a mim' (id_personnel do logado, INALTERADO). Filtro de data (BR), status
colorido, e clique no nº → Data do Evento/Notas/Subtarefas. Lê via api.list_minhas_os."""
import time

from PyQt6.QtCore import Qt, QDate, QTimer

# De quanto em quanto a lista se atualiza sozinha, e por quanto tempo ela é
# considerada FRESCA ao reabrir a aba. Os dois são o mesmo número de propósito:
# se a lista vale por 10 min, reabrir a aba dentro desses 10 min não precisa buscar.
INTERVALO_MIN = 10
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
        # ── rolagem infinita (28/07) ── o histórico busca UMA página por vez e o scroll pede a
        # próxima, como no Fracttal web. Antes puxava até 2000 OS + enriquecimento antes da
        # primeira linha — era a demora e o travamento que a equipe reclamava.
        self._pagina = 0                # última página que chegou (0 = nada)
        self._pag_alvo = 1              # página em trânsito
        self._tem_mais = False          # o servidor tem mais além do carregado?
        self._total_srv = 0             # total no servidor para o filtro atual
        self._cadeia = 0                # auto-buscas seguidas p/ alimentar filtro client-side
        self._wv = None                 # worker da varredura do período (filtro client-side)
        self._varrido = None            # args já varridos — evita varrer o mesmo duas vezes
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
        # 3ª visão (28/07): espelha a que existia no Power BI — colunas de programação/equipe/
        # gatilho e só os tipos do COS. Por baixo é a MESMA busca paginada; o que muda é o
        # conjunto de colunas e o filtro de tipo que já vem marcado.
        self.b_cos = QPushButton("Visão COS")
        self.b_cos.setToolTip("Corretivas, emergenciais e religamentos — com programação, "
                              "equipe e gatilho, como no Power BI")
        self.b_criadas.clicked.connect(lambda: self._set_modo("criadas"))
        self.b_atrib.clicked.connect(lambda: self._set_modo("atribuidas"))
        self.b_cos.clicked.connect(lambda: self._set_modo("cos"))
        row.addWidget(self.b_criadas); row.addWidget(self.b_atrib); row.addWidget(self.b_cos)
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
        self.lbl_auto = QLabel("↻ Atualiza a cada 10 min"); self.lbl_auto.setObjectName("hint")
        self.lbl_auto.setToolTip("Com a aba aberta, o histórico se atualiza sozinho a cada 15 minutos.")
        row.addWidget(self.lbl_auto)
        row.addWidget(QLabel("Buscar"))
        self.busca_no = QLineEdit(); self.busca_no.setPlaceholderText("nº, ativo, descrição, status…")
        self.busca_no.setMaximumWidth(200); self.busca_no.setClearButtonEnabled(True)
        self.busca_no.setToolTip("Filtra as OS do período por nº, cliente, usina, ativo, descrição, "
                                 "status, tipo de tarefa e etiqueta. Para achar uma OS FORA do "
                                 "período, use a barra 'Buscar OS pelo nº'.  [Ctrl+F]")
        # debounce: filtra ~260ms DEPOIS de parar de digitar (senão reconstrói a tabela a cada tecla = trava)
        self._busca_timer = QTimer(self); self._busca_timer.setSingleShot(True); self._busca_timer.setInterval(260)
        self._busca_timer.timeout.connect(self._aplica)
        self.busca_no.textChanged.connect(self._on_busca_change)
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
        self.tab.verticalHeader().setVisible(False)
        self.tab.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tab.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tab.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tab.setWordWrap(False)
        self._montar_colunas()
        self.tab.cellClicked.connect(self._abrir_detalhe)   # clique no nº → detalhe da OS
        # chegou perto do fim → pede a próxima página (o coração da rolagem infinita)
        self.tab.verticalScrollBar().valueChanged.connect(self._rolagem)
        lay.addWidget(self.tab, 1)

        hrow = QHBoxLayout(); hrow.setSpacing(8)
        self.spinner = Spinner(self)
        hrow.addWidget(self.spinner)
        self.hint = QLabel(""); self.hint.setObjectName("hint")
        hrow.addWidget(self.hint); hrow.addStretch(1)
        lay.addLayout(hrow)
        # auto-atualização a cada 15 min (só recarrega com a aba visível e sem carga em andamento)
        self._carregado_em = 0.0        # quando a última lista chegou (epoch)
        self._auto = QTimer(self); self._auto.setInterval(INTERVALO_MIN * 60 * 1000)
        self._auto.timeout.connect(self._auto_refresh)
        self._auto.start()
        self._refresh_botoes()

    # Colunas que a LISTAGEM não sabe preencher — chegam no `meta_tarefas_por_os` (nível tarefa)
    # e são repintadas pelo `_meta_ok`. Manter esta lista alinhada com o dict que a api devolve.
    _PATCH_META = frozenset({"event_date", "data_fim", "tipo_tarefa", "inicio", "gatilho"})

    # ── colunas: cada visão tem o seu conjunto ──
    # (rótulo, chave do dado, modo de largura). "status" e "etiqueta" são especiais (widget/join).
    COLS_PADRAO = [
        ("Nº", "folio", "conteudo"), ("Cliente", "cliente", 90), ("Usina", "usina", 130),
        ("Ativo", "ativo", 150), ("Descrição", "descricao", "estica"),
        ("Data de Criação", "data", "conteudo"), ("Data do Evento", "event_date", "conteudo"),
        ("Data Fim", "data_fim", "conteudo"), ("Status", "status", 150),
        ("Etiqueta", "etiqueta", 150),
    ]
    # Espelha a visão do Power BI, na mesma ordem que o Levi mandou no print.
    COLS_COS = [
        ("Data da programação", "programada", "conteudo"),
        ("Tipo de tarefa", "tipo_tarefa", "conteudo"),
        ("Usina", "usina", 130), ("Cliente", "cliente", 90),
        ("Descrição", "descricao", "estica"),
        ("Equipe", "equipe", 130),
        ("Data Início da OS", "inicio", "conteudo"),
        ("Data Fim da OS", "data_fim", "conteudo"),
        ("Descrição gatilho", "gatilho", 130),
        ("Descrição EQP", "ativo", 150),
        ("Nº Da OS", "folio", "conteudo"),
        ("Criado por", "criado_por", 130),
    ]
    _DATAS = {"data", "event_date", "data_fim", "programada", "inicio"}

    def _cols(self):
        return self.COLS_COS if self._modo == "cos" else self.COLS_PADRAO

    def _montar_colunas(self):
        cols = self._cols()
        self.tab.setRowCount(0)
        self.tab.setColumnCount(len(cols))
        self.tab.setHorizontalHeaderLabels([c[0] for c in cols])
        h = self.tab.horizontalHeader()
        for i, (_rot, _chave, larg) in enumerate(cols):
            if larg == "estica":
                h.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
            elif larg == "conteudo":
                h.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
            else:
                h.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
                self.tab.setColumnWidth(i, int(larg))
        # o Nº é sempre a coluna clicável que abre o detalhe — onde quer que ele esteja
        self._col_folio = next((i for i, c in enumerate(cols) if c[1] == "folio"), 0)

    def carregar_inicial(self):
        """Abriu a aba: só recarrega se os dados estiverem VELHOS (mais de INTERVALO_MIN).

        Antes recarregava toda vez que a aba ganhava foco — e como sair do Histórico para criar
        uma OS e voltar é o movimento mais comum do app, a pessoa pagava a espera da busca a
        cada ida e volta, sem que nada tivesse mudado. O relógio de 10 min já cobre o frescor;
        para forçar antes disso existe o botão de atualizar.
        """
        if self._w is not None or self._wp is not None or self._wl is not None:
            return                                   # já tem carga em andamento
        if self._dados and (time.time() - self._carregado_em) < INTERVALO_MIN * 60:
            return                                   # ainda fresco: mantém o que está na tela
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
        elif self._modo != "atribuidas" and not self._pessoas_loaded and self._wp is None:
            self._carregar_pessoas()
        else:
            self._carregar()

    # ── visão ──
    def _set_modo(self, modo):
        if modo == self._modo and self._dados:
            return
        if self._modo == "cos" and modo != "cos":
            # a marcação de tipo foi a visão COS que pôs — levá-la para o Histórico Geral esconderia
            # OS ali sem que ninguém tivesse pedido esse filtro
            self.cb_tarefa.clear_checks()
        self._modo = modo
        self._refresh_botoes()
        self._montar_colunas()
        if modo == "cos":
            # a visão nasce com os tipos do COS marcados (Preventiva de fora) e com TODOS os
            # criadores: é visão de equipe, não pessoal.
            self.cb_tarefa.set_items(sorted(set(api.TIPOS_COS)))
            self.cb_tarefa.set_checked(api.TIPOS_COS)
            if self.cb_pessoa.count():
                self.cb_pessoa.blockSignals(True)
                self.cb_pessoa.setCurrentIndex(0)          # "Todos os usuários"
                self.cb_pessoa.blockSignals(False)
        self._iniciar()

    def _refresh_botoes(self):
        for b, chave in ((self.b_criadas, "criadas"), (self.b_atrib, "atribuidas"),
                         (self.b_cos, "cos")):
            b.setObjectName("" if self._modo == chave else "secondary")
            b.style().unpolish(b); b.style().polish(b)
        self.pessoa_w.setVisible(self._modo != "atribuidas")

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
        # a visão COS é de EQUIPE: se ela já estiver aberta quando a lista de pessoas chegar
        # (ela carrega assíncrona), o default "usuário logado" a transformaria numa visão pessoal
        self.cb_pessoa.setCurrentIndex(0 if self._modo == "cos" else sel)
        self.cb_pessoa.blockSignals(False)
        self._carregar()

    def _on_pessoa(self, _idx):
        if self._modo != "atribuidas":
            self._carregar()

    # ── dados (paginados — a rolagem pede o resto) ──
    PAGINA = 60          # ~0,7 s por página no servidor (medido 28/07)

    def _args_servidor(self):
        """Filtros que valem NO SERVIDOR — a assinatura do `list_minhas_os_pagina`, na ordem."""
        id_label = self.cb_etiqueta.currentData() if self.cb_etiqueta.count() else None
        de = self.d_de.date().toString("yyyy-MM-dd")
        ate = self.d_ate.date().toString("yyyy-MM-dd")
        _n2i = {v: k for k, v in api.WO_STATUS.items()}
        status_ids = [_n2i[n] for n in self.cb_status.checked_values() if n in _n2i] or None
        idacc = ((self.cb_pessoa.currentData() if self.cb_pessoa.count() else None)
                 if self._modo != "atribuidas" else None)
        # a visão COS busca como "criadas" (é visão de equipe); o que a distingue é o conjunto
        # de colunas e o filtro de tipo, não a consulta.
        modo_srv = "atribuidas" if self._modo == "atribuidas" else "criadas"
        # A BUSCA NÃO VAI MAIS AO SERVIDOR (Levi, 03/08). O RPC compõe os filtros com OU, não E:
        # mandar a busca junto do "Criado por" devolvia "minhas OS do período" ∪ "qualquer OS com o
        # termo". Medido: filtrando por mim num mês, 138 OS viravam 243 — 62 de outros criadores e
        # 131 sem o termo em lugar nenhum. E não dá para agrupar: as duas formas de aninhar
        # condições que testei foram ignoradas pelo RPC (devolveram o catálogo).
        # Agora ela é 100% local (`_busca` no `_aplica`), o que ainda melhora duas coisas: casa com
        # as COLUNAS QUE APARECEM na tela — o `description` do RPC é outro campo, dava 17 contra as
        # 7 certas — e procura também em cliente, usina, ativo, status e etiqueta.
        # Buscar OS fora do período continua existindo: é a barra "Buscar OS pelo nº", que faz
        # consulta direta e ignora os filtros de propósito.
        return (modo_srv, idacc, id_label, de, ate, status_ids, "")

    def _carregar(self):
        """Recomeça da página 1 (filtro server-side mudou, F5, auto-refresh…)."""
        self._dt_timer.stop()                       # cancela re-busca pendente (já vamos buscar)
        self._cadeia = 0
        self._varrido = None                        # período/usuário mudou → pode varrer de novo
        self._disparar_pagina(1)

    def _buscar_mais(self):
        if self._tem_mais and self._w is None:
            self._disparar_pagina(self._pagina + 1)

    def _disparar_pagina(self, p):
        if self._w is not None:
            return
        self.spinner.start()
        if p == 1:
            self.hint.setText("carregando OS…")
            self.tab.setRowCount(0)
        self._pag_alvo = p
        self._w = ApiWorker(api.list_minhas_os_pagina, *self._args_servidor(), p, self.PAGINA)
        self._w.ok.connect(self._chegou_pagina)
        self._w.erro.connect(self._erro)
        self._w.start()

    @slot_seguro
    def _chegou_pagina(self, res):
        self._w = None
        self.spinner.stop()
        res = res or {}
        if self._pag_alvo == 1:
            self._dados = []
        # dedup por id: OS criada entre uma página e outra desloca a janela e repetiria linha
        vistos = {d.get("id") for d in self._dados}
        self._dados.extend(d for d in (res.get("linhas") or []) if d.get("id") not in vistos)
        self._pagina = self._pag_alvo
        self._tem_mais = bool(res.get("tem_mais"))
        self._total_srv = int(res.get("total") or 0)
        self._carregado_em = time.time()      # marca o frescor (ver carregar_inicial)
        self._rebuild_status()
        self._rebuild_filtros_ativo()
        self._aplica()
        # enriquecimento DEPOIS de mostrar: tipo de tarefa + datas da tarefa custam 3,5 s por
        # página (medido) contra 0,7 s da lista — esperar por eles quintuplicava a primeira tela.
        self._patch_meta([d.get("id") for d in (res.get("linhas") or [])])

    def _patch_meta(self, ids):
        ids = [i for i in (ids or []) if i]
        if not ids:
            return
        w = ApiWorker(api.meta_tarefas_por_os, ids)
        w.ok.connect(self._meta_ok)
        w.erro.connect(lambda *_: None)         # best-effort: sem meta a linha fica com o fallback
        w.start()                               # o _ALIVE do workers.py segura a referência

    @slot_seguro
    def _meta_ok(self, meta):
        meta = meta or {}
        if not self._dados:
            return                              # a lista foi trocada enquanto a meta viajava
        indice = {d.get("id"): d for d in self._dados}
        tocou = False
        for wid, m in meta.items():
            d = indice.get(wid)
            if d is None:
                continue                        # página descartada por re-busca — só ignora
            d["tipo_tarefa"] = m.get("tipo_tarefa", d.get("tipo_tarefa", ""))
            d["event_date"] = m.get("event_date") or d.get("event_date", "")
            d["data_fim"] = m.get("data_fim") or d.get("data_fim", "")
            d["note"] = m.get("note", d.get("note", ""))
            # Início real e gatilho SÓ existem no nível tarefa (sondado em 28/07) — a listagem
            # não os traz, então a visão COS depende deste patch para preencher as duas colunas.
            d["inicio"] = m.get("inicio") or d.get("inicio", "")
            d["gatilho"] = m.get("gatilho") or d.get("gatilho", "")
            tocou = True
        if not tocou:
            return
        # repinta as células de data das linhas visíveis (por id, não por posição) e realimenta
        # o filtro de tipo de tarefa; re-filtra só se alguém já estiver filtrando por tarefa
        por_id = {}
        for r in range(self.tab.rowCount()):
            it = self.tab.item(r, self._col_folio)
            if it is not None:
                por_id[it.data(Qt.ItemDataRole.UserRole)] = r
        cols = self._cols()
        self.tab.setUpdatesEnabled(False)
        for wid, m in meta.items():
            r = por_id.get(wid)
            if r is None:
                continue
            d = indice.get(wid) or {}
            for c, (_rot, chave, _l) in enumerate(cols):
                if chave in self._PATCH_META and self.tab.item(r, c):
                    val = (_data_br(d.get(chave)) if chave in self._DATAS
                           else str(d.get(chave) or "—"))
                    self.tab.item(r, c).setText(val)
        self.tab.setUpdatesEnabled(True)
        self._rebuild_tarefas()
        if self.cb_tarefa.checked_values():
            self._aplica()

    def _rolagem(self, v):
        """Perto do fim da barra → próxima página. Gesto do usuário zera a cadeia de auto-busca."""
        sb = self.tab.verticalScrollBar()
        if sb.maximum() > 0 and v >= sb.maximum() - 3 * max(1, self.tab.rowHeight(0) if self.tab.rowCount() else 24):
            self._cadeia = 0
            self._buscar_mais()

    _FILTROS_LOCAIS = ("cb_status", "cb_cliente", "cb_usina", "cb_tipo", "cb_tarefa")

    def _tem_filtro_local(self) -> bool:
        """Algum filtro que o SERVIDOR não sabe aplicar está ligado?

        Cliente, usina, tipo de ativo e tipo de tarefa são casados aqui, no dado já baixado — o RPC
        do Fracttal ignora `like` em campo de item (medido 28/07) e não tem propriedade de usina
        (o `id_group_task` é família de PLANO, não planta: filtrar por ele devolveu OS de 20 usinas
        diferentes, medido 30/07)."""
        if self.busca_no.text().strip():
            return True                    # a busca também é local desde 03/08
        return any(getattr(self, n).checked_values() for n in self._FILTROS_LOCAIS)

    def _talvez_completar(self):
        """Completa a busca quando o filtro é client-side.

        BUG QUE ORIGINOU ISTO (Levi, 30/07): filtrando Athon · Matões 2 num mês, a tela mostrava
        **3 OS de 15**; filtrando Matões 1 em três meses, **2 de 91**. O filtro só enxergava as 420
        linhas já baixadas — de 1.771 no primeiro caso, de 5.523 no segundo — e o teto de 6 páginas
        parava a busca antes.

        Com filtro local ligado, varre o período INTEIRO de uma vez, em paralelo
        (`api.listar_periodo_completo`). Encadear página a página resolveria o número mas não o
        tempo: 5.523 OS de 60 em 60 são ~93 requisições e mais de um minuto; em paralelo, medido,
        são **6,4 s**. Sem filtro local nada muda: enche a tela e deixa o resto para a rolagem."""
        if self._w is not None or self._wv is not None or not self._dados:
            return
        if self._tem_filtro_local():
            if self._tem_mais:
                self._varrer_periodo()
            return
        if self._tem_mais and self._cadeia < 6 and self.tab.rowCount() < 40:
            self._cadeia += 1
            self._buscar_mais()

    def _varrer_periodo(self):
        """Lê o período inteiro em paralelo e substitui a lista carregada."""
        args = self._args_servidor()
        if self._varrido == args:          # já varrido com estes mesmos parâmetros
            return
        self._varrido = args
        self.spinner.start()
        self._wv = ApiWorker(api.listar_periodo_completo, *args)
        self._wv.ok.connect(self._varredura_ok)
        self._wv.erro.connect(self._varredura_erro)
        self._wv.start()

    @slot_seguro
    def _varredura_erro(self, m):
        self._wv = None
        self._varrido = None               # deixa tentar de novo
        self.spinner.stop()
        self.hint.setText("⚠ não consegui ler o período inteiro: %s" % m)

    @slot_seguro
    def _varredura_ok(self, res):
        self._wv = None
        self.spinner.stop()
        res = res or {}
        linhas = res.get("linhas") or []
        if not linhas:
            return
        # preserva o que a meta já enriqueceu: a varredura devolve a linha CRUA da listagem, e
        # sobrescrever apagaria tipo de tarefa e datas de tarefa já buscados
        antes = {d.get("id"): d for d in self._dados}
        for d in linhas:
            velho = antes.get(d.get("id"))
            if velho:
                for k in ("tipo_tarefa", "event_date", "data_fim", "note", "inicio", "gatilho"):
                    if velho.get(k):
                        d[k] = velho[k]
        self._dados = linhas
        self._tem_mais = not res.get("completo", True)
        self._total_srv = int(res.get("total") or 0)
        self._pagina = max(1, -(-len(linhas) // self.PAGINA))
        self._rebuild_status()
        self._rebuild_filtros_ativo()
        self._aplica()
        self._patch_meta([d.get("id") for d in self._linhas[:400]])   # só o que casou o filtro

    def _on_busca_change(self, *_):
        self._busca_timer.start()           # filtra o carregado; se faltar período, o `_aplica`
                                            # dispara a varredura (a busca é filtro local)

    def _erro(self, m):
        self._w = None
        self.spinner.stop()
        self.hint.setText("⚠ " + m)

    def _rebuild_status(self):
        """Status é SERVER-SIDE → lista fixa com todos os status possíveis (preserva marcados)."""
        self.cb_status.set_items(list(api.WO_STATUS.values()))

    def _catalogo_loc(self):
        """{cliente: {usinas}} do CATÁLOGO de ativos (offline, cacheado). Com a rolagem infinita
        os combos não podem depender só das páginas carregadas — a usina que a pessoa quer
        filtrar quase nunca está na primeira página.

        SÓ entra o par cujo tipo é de PLANTA (api.CARTEIRA_EQUIP): o catálogo tem materiais de
        inventário com "usina" própria ("0,3P75 - G2", "0,6/1 kV"…) e, sem o discriminador, o
        combo listava o almoxarifado inteiro como se fosse usina (print do Levi, 28/07)."""
        if getattr(self, "_cat_loc", None) is None:
            m = {}
            try:
                for cli, usi, tipo in api._code_to_loc().values():
                    if cli and usi and tipo in api.CARTEIRA_EQUIP:
                        m.setdefault(cli, set()).add(usi)
            except Exception:
                m = {}
            self._cat_loc = m
        return self._cat_loc

    def _rebuild_filtros_ativo(self):
        """Repovoa Cliente/Tipo de ativo/Tipo de tarefa (multi; preserva marcados). Usina cascateia.
        Cliente/Usina = catálogo ∪ carregado; Tipos = só do carregado (não há lista universal)."""
        cat = self._catalogo_loc()
        clientes = sorted(set(cat)
                          | {d.get("cliente") for d in self._dados
                             if d.get("cliente") and d.get("cliente") != "—"})
        tipos = sorted({d.get("tipo") for d in self._dados
                        if d.get("tipo") and d.get("tipo") != "—"})
        self.cb_cliente.set_items(clientes)
        self.cb_tipo.set_items(tipos)
        self._rebuild_tarefas()
        self._rebuild_usinas()                        # usinas dependem dos clientes marcados

    def _rebuild_tarefas(self):
        """Repovoa o filtro de Tipo de tarefa preservando o que está marcado.

        Dois cuidados que custaram um bug: (1) o tipo de tarefa só chega no `meta_tarefas_por_os`,
        então na hora em que a PÁGINA chega a lista é vazia — repovoar com vazio zerava a marcação
        (era o que apagava a pré-seleção da visão COS); (2) na visão COS os tipos de `TIPOS_COS`
        entram na lista mesmo sem aparecer na página carregada, senão `set_items` os descarta por
        "não existirem" e o filtro passa a esconder as OS desses tipos nas páginas seguintes."""
        tarefas = {tt for d in self._dados                        # OS pode ter + de 1 tipo (join " / ")
                   for tt in (d.get("tipo_tarefa") or "").split(" / ") if tt}
        if self._modo == "cos":
            tarefas |= set(api.TIPOS_COS)
        if tarefas:
            self.cb_tarefa.set_items(sorted(tarefas))

    def _rebuild_usinas(self):
        """Usinas dos clientes marcados (ou todas, se nenhum). Multi; preserva marcadas."""
        clis = self.cb_cliente.checked_values()
        cat = self._catalogo_loc()
        do_cat = {u for cli, us in cat.items() if not clis or cli in clis for u in us}
        usinas = sorted(do_cat
                        | {d.get("usina") for d in self._dados
                           if d.get("usina") and d.get("usina") != "—"
                           and (not clis or d.get("cliente") in clis)})
        self.cb_usina.set_items(usinas)

    def _on_cliente(self, _idx=0):
        self._rebuild_usinas()
        self._aplica()

    def _on_usina(self, *_):
        # ao filtrar por usina, mostra OS de TODOS os criadores (não só o logado) — troca "Criado por"
        # p/ "Todos os usuários", o que dispara a re-busca (que por sua vez chama _aplica).
        if (self._modo != "atribuidas" and self.cb_usina.checked_values()
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
        cols = self._cols()
        for d in linhas[:MAX_LINHAS]:        # teto de render — 2000 cellWidgets travam a UI (~15s)
            r = self.tab.rowCount(); self.tab.insertRow(r)
            for c, (_rot, chave, _larg) in enumerate(cols):
                if chave == "status":        # card colorido (cellWidget), não texto
                    self.tab.setCellWidget(r, c, _status_widget(d.get("status")))
                    continue
                if chave == "etiqueta":
                    txt = ", ".join(e.get("nome") or "" for e in (d.get("etiquetas") or [])
                                    if e.get("nome"))
                    it = QTableWidgetItem(txt)
                    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if txt:
                        it.setToolTip(txt)
                elif chave in self._DATAS:
                    it = QTableWidgetItem(_data_br(d.get(chave)))
                elif chave == "folio":
                    it = QTableWidgetItem(str(d.get("folio") or "—"))
                    it.setData(Qt.ItemDataRole.UserRole, d.get("id"))   # id_work_order p/ o detalhe
                    it.setForeground(QBrush(QColor("#98c838")))         # verde-grid, sem sublinhado
                    f = it.font(); f.setBold(True); it.setFont(f)
                    it.setToolTip("Clique para ver Data do Evento, Notas e Subtarefas")
                else:
                    txt = str(d.get(chave) or "—")
                    it = QTableWidgetItem(txt)
                    if len(txt) > 18:      # a visão COS tem 12 colunas: Descrição e Ativo cortam
                        it.setToolTip(txt)
                self.tab.setItem(r, c, it)
        self.tab.setUpdatesEnabled(True)
        n = len(linhas)
        partes = [f"{min(n, MAX_LINHAS)} OS exibidas"]
        if len(self._dados) != n:
            partes.append(f"{len(self._dados)} carregadas")
        if self._tem_mais:
            # com filtro local ligado, "3 OS exibidas" sobre lista parcial é uma MENTIRA silenciosa
            # (o caso Matões 2: 3 de 15). Enquanto a varredura do período não termina, o rodapé
            # avisa que a conta ainda não fechou.
            if self._tem_filtro_local():
                partes.append(f"⚠ filtro sobre lista parcial — lendo o período "
                              f"({len(self._dados)} de {self._total_srv})…")
            else:
                partes.append(f"{self._total_srv} no período — role até o fim para carregar mais")
        elif self._total_srv:
            partes.append("tudo carregado" if not self._tem_filtro_local()
                          else f"período inteiro lido · {self._total_srv} OS")
        if n > MAX_LINHAS:
            partes.append(f"⚠ exibindo {MAX_LINHAS} (a exportação inclui todas)")
        self.hint.setText("  ·  ".join(partes))
        self._talvez_completar()          # filtro magro + servidor com mais → busca sozinho

    def _abrir_detalhe(self, row, col):
        """Clique no nº da OS → dialog com Data do Evento, Notas e Subtarefas. A coluna do Nº
        muda de posição entre as visões, por isso `_col_folio` em vez de zero fixo."""
        if col != self._col_folio:
            return
        it = self.tab.item(row, self._col_folio)
        wid = it.data(Qt.ItemDataRole.UserRole) if it else None
        if wid:
            abrir_os_detalhe(self, wid, it.text())

    def _exportar(self):
        """Exporta as OS exibidas (já filtradas) p/ CSV, com as COLUNAS DA VISÃO ATUAL.

        Seguir a visão importa na COS: ela existe para substituir uma tela do Power BI, e sair para
        o Excel é justamente o que se faz com ela — exportar as colunas do Histórico Geral entregaria
        um arquivo sem programação, início, equipe nem gatilho."""
        def _val(d, chave):
            if chave == "etiqueta":
                return ", ".join(e.get("nome") or "" for e in (d.get("etiquetas") or []) if e.get("nome"))
            if chave in self._DATAS:
                v = _data_br(d.get(chave))
                return "" if v == "—" else v     # célula VAZIA no Excel; "—" viraria texto numa coluna de data
            return d.get(chave) or ""

        cols = list(self._cols())
        # o tipo de tarefa e as etiquetas não são colunas do Histórico Geral, mas todo mundo espera
        # achá-las na planilha — entram no fim quando a visão não as mostra
        for rot, chave in (("Tipo de tarefa", "tipo_tarefa"), ("Etiquetas", "etiqueta")):
            if not any(c[1] == chave for c in cols):
                cols.append((rot, chave, 0))
        headers = [c[0] for c in cols]
        rows = [[_val(d, chave) for _rot, chave, _l in cols] for d in self._linhas]
        de = self.d_de.date().toString("yyyy-MM-dd"); ate = self.d_ate.date().toString("yyyy-MM-dd")
        exportar_csv(self, headers, rows, sugestao=f"historico_os_{de}_a_{ate}.csv",
                     titulo="Exportar histórico de OS")
