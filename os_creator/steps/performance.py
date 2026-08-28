"""performance.py — aba PERFORMANCE (fluxo próprio, distinto do PCM).

Abre em 4 cards (um por plano de tarefa de Performance). Ao clicar num card, vai p/ a tela de criação:
cascata Cliente→Usina, tabela de ATIVOS (marcar + observação por ativo + anexar imagens), nome
automático '[Ativo] - <plano>' (base editável), resumo do plano (só leitura) e responsável.
O card 'Geração e ETM' abre em dois modos (segmentado no topo) — ver as constantes MODO_* abaixo.
Diferente do PCM: aqui cria-se N OS (UMA por ativo). Trackers: seleciona-se os trackers INDIVIDUAIS,
mas o conteúdo vem do plano do ativo generalizado 'Estrutura Trackers' (OS avulsas com subtarefas
copiadas). Anexo de imagem por ativo: arquivo OU colar captura (Ctrl+V)."""
import datetime as _dt
import html
from PyQt6.QtCore import Qt, QSize, QDateTime, QDate, QTime, QByteArray, QBuffer, QIODevice
from PyQt6.QtGui import QIcon, QImage, QPixmap, QGuiApplication, QKeySequence, QBrush, QColor
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QStackedWidget, QLabel,
                             QComboBox, QLineEdit, QTextEdit, QPushButton, QMessageBox, QTableWidget,
                             QTableWidgetItem, QHeaderView, QAbstractItemView, QScrollArea, QFrame,
                             QDialog, QDateTimeEdit, QFileDialog, QCheckBox)
import api
from workers import ApiWorker, slot_seguro
from steps.searchcombo import tornar_pesquisavel, tornar_todos_pesquisaveis
from steps.ui import (QSS_FORM, Card, campo, rotulo, Linha, Segmentado, icone_pix,
                      GREEN, GREEN_INK, MUTED, TEXT, CARD, INPUT, BORDER, BG,
                      travar_no_passado)

_SEL = "— selecione —"

# ── O card "Geração e ETM" abre em DOIS modos ────────────────────────────────────────────────────
# É o MESMO plano do Fracttal ("Coleta de dados de geração"), mas dois públicos diferentes: geração
# se pede por INVERSOR (vários por usina, nome e observação de cada um), e a ETM é a estação da
# usina — sempre o mesmo ativo, sempre o mesmo título, e leva ENGENHARIA junto com PERFORMANCE
# porque quem mexe na estação é a engenharia. Separar em dois cards duplicaria a tela inteira;
# o que muda entre eles cabe num segmentado.
FRASE_COLETA = "coleta de dados de geracao"
MODO_GERACAO, MODO_USINA, MODO_ETM = 0, 1, 2
ETM_TIPO = "Estação Meteorológica"
USINA_TIPO = "Usina"                                      # o item-usina, a planta como ativo
USINA_TITULO = "[Usina] - Coleta e análise de dados de geração"   # título LITERAL, como o ETM
ETM_TITULO = "[ETM] - Coleta e análise de dados"          # título LITERAL, sem o prefixo [Ativo]
ETM_ETIQUETAS = ("ENGENHARIA",)                           # somadas à PERFORMANCE, que já é padrão


def _centrar(w):
    """Embrulha um widget num holder que o centraliza — p/ centralizar um cell widget na coluna."""
    holder = QWidget(); holder.setStyleSheet("background:transparent;")
    h = QHBoxLayout(holder); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(0)
    h.addStretch(1); h.addWidget(w); h.addStretch(1)
    return holder


def _matar_celula(tbl, r, c):
    """Tira E DESTRÓI o widget de uma célula. `removeCellWidget` sozinho só desfaz o vínculo — o
    widget continua pendurado no viewport e VISÍVEL, e um deles ia parar em (0,0), por cima do nome
    do primeiro ativo. Medido: 5 marcar/desmarcar deixavam 9 órfãos pintando na tela."""
    w = tbl.cellWidget(r, c)
    if w is not None:
        tbl.removeCellWidget(r, c)
        w.setParent(None)
        w.deleteLater()


def _cell_campo(w):
    """Embrulha um campo de edição (QLineEdit) p/ ele CENTRALIZAR na altura da linha (o QSS limita a
    altura do campo, então setar direto como cell widget o encosta no topo = desalinhado) + respiro lateral."""
    holder = QWidget(); holder.setStyleSheet("background:transparent;")
    h = QHBoxLayout(holder); h.setContentsMargins(6, 0, 6, 0); h.setSpacing(0)
    h.addWidget(w)                       # HBox centra na vertical um widget de altura fixa
    return holder
_CRIT = {i: n for (n, i) in getattr(api, "CRITICIDADES", [])}
# Tipos de EQUIPAMENTO de planta — p/ decidir quais clientes/usinas são "reais" (o catálogo do Fracttal
# tem itens de inventário/material com cliente e usina próprios que não são plantas).
_CARTEIRA_EQUIP = frozenset({"Inversor", "Cabine", "Tracker", "Estrutura Trackers",
                             "Estação Meteorológica", "Skid"})   # tipos que SÓ plantas têm (inventário
                             # do Almoxarifado usa 'Usina'/'Disjuntor'/'Transformador' — ficam de fora)

# (título, frase p/ casar o plano, ícone, badge de categoria, subtítulo)
_PLANOS = [
    ("Geração e ETM", FRASE_COLETA, "activity", "Inversor · ETM",
     "Geração por inversor • ou coleta e análise da estação meteorológica"),
    ("Inspeção Geral do Inversor", "inspecao geral do inversor", "searchcheck", "Inversor",
     "Checklist completo • conexões • alarmes • temperatura • strings"),
    ("Recomposição de String", "recomposicao de string", "zap", "Inversor",
     "Diagnóstico e normalização de string sem corrente"),
    ("Verificação de Tracker Parado", "verificacao de tracker parado", "alert", "Trackers",
     "Tracker travado • fim de curso • alinhamento"),
]


def _contar_subtarefas(assets):
    """{frase: [nomes das subtarefas]} de cada plano de _PLANOS. Amostra: 1 ativo de cada tipo relevante
    (Inversor, Estação, tracker generalizado). Best-effort: plano não encontrado → não entra no dict."""
    inv = next((a for a in assets if a.get("tipo") == "Inversor"), None)
    est = next((a for a in assets if a.get("tipo") == "Estação Meteorológica"), None)
    trk = next((a for a in assets if api._eh_tracker_generalizado(a)), None)
    sample = [x for x in (inv, est, trk) if x]
    if not sample:
        return {}
    plans = api.get_plans_for_assets(sample)
    pares, frase_task = [], {}
    for entry in _PLANOS:
        frase = entry[1]; fn = api._norm_txt(frase)
        p = next((pl for pl in plans if fn in api._norm_txt(pl.get("description"))), None)
        if p and p.get("asset"):
            frase_task[frase] = p["id_task"]
            pares.append((p["id_task"], p["asset"]["id"]))
    nomes = api.get_subtask_names(pares)
    return {frase: nomes[tid] for frase, tid in frase_task.items() if nomes.get(tid) is not None}


def _png_bytes(img: QImage) -> bytes:
    ba = QByteArray(); buf = QBuffer(ba); buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG"); buf.close()
    return bytes(ba)


def _chip(icone, texto):
    """Mini info (ícone + texto) da linha de meta do card."""
    w = QWidget(); w.setStyleSheet("background:transparent;")
    h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(5)
    ic = QLabel(); ic.setPixmap(icone_pix(icone, MUTED, 13)); ic.setFixedSize(13, 13)
    ic.setStyleSheet("background:transparent;border:none;")
    t = QLabel(texto); t.setStyleSheet(f"font-size:11.5px;color:{MUTED};background:transparent;border:none;")
    h.addWidget(ic); h.addWidget(t)
    return w


class _ClickLabel(QLabel):
    """QLabel que responde ao clique (e NÃO propaga pro card pai) — p/ abrir a lista de subtarefas."""
    def __init__(self, on_click=None, texto=""):
        super().__init__(texto)
        self._on_click = on_click

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._on_click:
            self._on_click(); e.accept(); return
        super().mousePressEvent(e)


class _PlanoCard(QFrame):
    """Card clicável de plano (SaaS): tile do ícone + título + badge de categoria + subtítulo + linha de
    meta (duração/tipo/padrão) + seta em círculo (CTA). Baixo e alinhado. Hover: borda verde."""
    def __init__(self, icone, titulo, badge, sub, on_click):
        super().__init__()
        self._cb = on_click
        self.setObjectName("planoCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(92)
        self.setStyleSheet(
            "QFrame#planoCard{background:%s;border:1px solid %s;border-radius:14px;}"
            "QFrame#planoCard:hover{border:1px solid %s;}" % (CARD, BORDER, GREEN))
        row = QHBoxLayout(self); row.setContentsMargins(16, 14, 16, 14); row.setSpacing(13)

        tile = QLabel(); tile.setFixedSize(44, 44); tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tile.setStyleSheet("background:rgba(166,226,46,0.14);border-radius:11px;border:none;")
        tile.setPixmap(icone_pix(icone, GREEN, 22))
        row.addWidget(tile, 0, Qt.AlignmentFlag.AlignVCenter)

        mid = QVBoxLayout(); mid.setSpacing(5); mid.setContentsMargins(0, 0, 0, 0)
        # linha 1: título + badge de categoria
        l1 = QHBoxLayout(); l1.setSpacing(8)
        t = QLabel(titulo)
        t.setStyleSheet(f"font-size:15px;font-weight:600;color:{TEXT};background:transparent;border:none;")
        l1.addWidget(t)
        bd = QLabel(badge)
        bd.setStyleSheet("background:rgba(166,226,46,0.14);color:%s;border-radius:6px;padding:1px 8px;"
                         "font-size:11px;font-weight:600;border:none;" % GREEN)
        l1.addWidget(bd, 0, Qt.AlignmentFlag.AlignVCenter); l1.addStretch(1)
        mid.addLayout(l1)
        # subtítulo
        s = QLabel(sub); s.setWordWrap(True)
        s.setStyleSheet(f"font-size:12px;color:{MUTED};background:transparent;border:none;")
        mid.addWidget(s)
        # linha de meta: só a quantidade de subtarefas
        l3 = QHBoxLayout(); l3.setSpacing(6)
        _ic = QLabel(); _ic.setPixmap(icone_pix("list", MUTED, 13)); _ic.setFixedSize(13, 13)
        _ic.setStyleSheet("background:transparent;border:none;")
        self._nomes = []                        # nomes das subtarefas (carregados async)
        self._pop = None
        self.sub_lbl = _ClickLabel(self._abrir_subs, "… subtarefas")
        self.sub_lbl.setStyleSheet(f"font-size:11.5px;color:{MUTED};background:transparent;border:none;")
        l3.addWidget(_ic); l3.addWidget(self.sub_lbl); l3.addStretch(1)
        mid.addLayout(l3)
        row.addLayout(mid, 1)

        # seta em círculo (CTA)
        cta = QLabel(); cta.setFixedSize(34, 34); cta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cta.setStyleSheet(f"background:{INPUT};border:1px solid {BORDER};border-radius:17px;")
        cta.setPixmap(icone_pix("arrow", TEXT, 17))
        row.addWidget(cta, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_subtarefas(self, nomes):
        self._nomes = list(nomes) if isinstance(nomes, (list, tuple)) else []
        n = len(self._nomes)
        self.sub_lbl.setText((f"{n} subtarefa" + ("s" if n != 1 else "")) + ("  ·  ver lista" if n else ""))
        if n:
            self.sub_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            self.sub_lbl.setToolTip("Clique para ver as subtarefas")
            self.sub_lbl.setStyleSheet(f"font-size:11.5px;color:{GREEN};background:transparent;border:none;")

    def _abrir_subs(self):
        if not self._nomes:
            return
        pop = QFrame(self.window()); pop.setObjectName("subPop")
        pop.setWindowFlags(Qt.WindowType.Popup)
        pop.setStyleSheet("QFrame#subPop{background:%s;border:1px solid %s;border-radius:12px;}" % (CARD, BORDER))
        v = QVBoxLayout(pop); v.setContentsMargins(15, 13, 15, 13); v.setSpacing(7)
        tit = QLabel(f"Subtarefas ({len(self._nomes)})")
        tit.setStyleSheet(f"color:{MUTED};font-size:11px;font-weight:700;letter-spacing:.6px;"
                          "background:transparent;border:none;")
        v.addWidget(tit)
        for i, nome in enumerate(self._nomes, 1):
            r = QLabel(f"<span style='color:{GREEN}'>{i}.</span>&nbsp;&nbsp;{html.escape(nome)}")
            r.setWordWrap(True); r.setMaximumWidth(400)
            r.setStyleSheet(f"color:{TEXT};font-size:13px;background:transparent;border:none;")
            v.addWidget(r)
        pop.adjustSize()
        gp = self.sub_lbl.mapToGlobal(self.sub_lbl.rect().bottomLeft())
        pop.move(gp.x(), gp.y() + 6); pop.show()
        self._pop = pop

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._cb:
            self._cb()
        super().mousePressEvent(e)


class PerformanceTab(QWidget):
    """Container da aba Performance: página 0 = os 4 cards; página 1 = tela de criação (recriada
    a cada card). Mantém a mesma interface do PcmTab (`carregar_inicial`) p/ o wrap do app.py."""
    _selfnav = True                                       # faz a própria navegação (não usa o Voltar do wrap)

    def __init__(self, on_sair=None):
        super().__init__()
        self.setStyleSheet(QSS_FORM)
        self._assets = api.load_assets_cached() or []
        self._on_sair = on_sair
        self._cria = None
        self._wcont = None
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget(); outer.addWidget(self._stack)
        self._stack.addWidget(self._build_cards())        # página 0

    def carregar_inicial(self):
        pass                                              # nada pesado aqui; a tela de criação carrega sob demanda

    @slot_seguro
    def reiniciar(self):
        """Toda ENTRADA na aba volta aos 4 cards de plano e joga fora a tela de criação anterior.

        O painel é criado uma vez só e o app apenas troca a página do stack — sem isto, quem saía
        no meio de uma criação voltava com cliente, usina e ativos marcados do uso anterior, e a
        OS seguinte saía na usina errada."""
        self._stack.setCurrentIndex(0)
        if self._cria is not None:
            self._stack.removeWidget(self._cria)
            self._cria.deleteLater()
            self._cria = None

    def _build_cards(self):
        w = QWidget()
        scroll = QScrollArea(); scroll.setObjectName("uiFlat"); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(w)
        v = QVBoxLayout(w); v.setContentsMargins(22, 14, 22, 18); v.setSpacing(12)
        top = QHBoxLayout()
        b_sair = QPushButton("← Voltar"); b_sair.setObjectName("secondary"); b_sair.setFixedWidth(104)
        b_sair.clicked.connect(lambda: self._on_sair() if self._on_sair else None)
        top.addWidget(b_sair); top.addStretch(1)
        # Entrada do kanban de carga da equipe. Fica aqui, e não como um 5º card, porque os cards
        # são "tipo de atendimento" (criam OS por ativo) e isto é acompanhamento — misturar as
        # duas naturezas na mesma grade confundiria o que cada clique faz.
        b_carga = QPushButton("Alocação de análises"); b_carga.setObjectName("btnPrimary")
        b_carga.setCursor(Qt.CursorShape.PointingHandCursor)
        b_carga.setToolTip("Quadro de alocação: o que cada analista tem em mãos")
        b_carga.clicked.connect(self._abrir_carga)
        top.addWidget(b_carga)
        v.addLayout(top)
        intro = QLabel("Escolha o tipo de atendimento. Cada opção cria <b>uma OS por ativo</b> selecionado, "
                       "com tipo, classificação e criticidade já do plano.")
        intro.setObjectName("uiAjuda"); intro.setWordWrap(True)
        v.addWidget(intro)
        grid = QGridLayout(); grid.setSpacing(14)
        self._cards = {}
        for i, (titulo, frase, ic, badge, sub) in enumerate(_PLANOS):
            card = _PlanoCard(ic, titulo, badge, sub,
                              lambda t=titulo, f=frase, k=ic: self._abrir(t, f, k))
            self._cards[frase] = card
            grid.addWidget(card, i // 2, i % 2)
        grid.setColumnStretch(0, 1); grid.setColumnStretch(1, 1)
        v.addLayout(grid); v.addStretch(1)
        wrap = QWidget(); wl = QVBoxLayout(wrap); wl.setContentsMargins(0, 0, 0, 0); wl.addWidget(scroll)
        self._carregar_contagens()                       # busca "N subtarefas" de cada plano (async)
        return wrap

    def _abrir_carga(self):
        """Abre o kanban de carga como página do stack (import tardio: a tela puxa o board
        inteiro e não deve pesar a abertura da aba)."""
        if getattr(self, "_carga", None) is None:
            from steps.perf_kanban import PerfKanbanTab
            self._carga = PerfKanbanTab(on_voltar=lambda: self._stack.setCurrentIndex(0))
            self._stack.addWidget(self._carga)
        self._stack.setCurrentWidget(self._carga)
        self._carga.carregar_inicial()

    def _carregar_contagens(self):
        self._wcont = ApiWorker(_contar_subtarefas, self._assets)
        self._wcont.ok.connect(self._set_contagens)
        self._wcont.erro.connect(lambda m: setattr(self, "_wcont", None))
        self._wcont.start()

    @slot_seguro
    def _set_contagens(self, d):
        self._wcont = None
        for frase, nomes in (d or {}).items():
            c = self._cards.get(frase)
            if c is not None and nomes is not None:
                c.set_subtarefas(nomes)

    def _abrir(self, titulo, frase, icone):
        if self._cria is not None:
            self._stack.removeWidget(self._cria); self._cria.deleteLater()
        self._cria = PerfCriar(self._assets, titulo, frase, icone,
                               on_voltar=lambda: self._stack.setCurrentIndex(0))
        self._stack.addWidget(self._cria)
        self._stack.setCurrentWidget(self._cria)
        self._cria.carregar_inicial()

    def aplicar_sugestao(self, dados):
        """Deep link da Plataforma (gridos://performance): abre o plano do `template` e repassa a sugestão
        (usina/ativo/observação) à página de criação. Best-effort — nunca levanta exceção."""
        try:
            tmpl = api._norm_txt((dados or {}).get("template") or "")
            alvo = None
            for titulo, frase, ic, _badge, _sub in _PLANOS:
                if tmpl and tmpl in api._norm_txt(frase):
                    alvo = (titulo, frase, ic); break
            if alvo is None:                      # sem match → assume "Recomposição de String" (o caso das strings)
                t, f, ic, _b, _s = _PLANOS[2]; alvo = (t, f, ic)
            self._abrir(*alvo)
            if getattr(self, "_cria", None) is not None and hasattr(self._cria, "aplicar_sugestao"):
                self._cria.aplicar_sugestao(dados)
        except Exception:
            pass


class PerfCriar(QWidget):
    """Tela de criação de um plano de Performance: cascata + tabela de ativos + nome + responsável."""
    def __init__(self, assets, titulo, frase, icone, on_voltar):
        super().__init__()
        self._assets = assets
        self._titulo = titulo
        self._frase = frase
        self._icone = icone
        self._on_voltar = on_voltar
        self._alvos = []                 # [{asset, plano_id_task, plano_id_item, linkar}]
        self._alvo_by_id = {}
        self._checked = set()            # asset ids marcados
        self._agrup_tocado = False       # a pessoa já mexeu no "Agrupar"? (ver _auto_agrupar)
        self._clientes_reais = set()     # carteiras com equipamento (preenchido em _fill_clientes)
        self._obs = {}                   # asset id -> observação
        self._ospai = {}                 # asset id -> nº da OS pai (por ativo, na linha da tabela)
        self._imgs = {}                  # asset id -> [{'bytes','nome','thumb'}]
        self._is_tracker = "tracker" in frase
        self._tem_modos = api._norm_txt(frase) == FRASE_COLETA     # só o card "Geração e ETM"
        self._modo = MODO_GERACAO
        self._base = titulo
        self._wa = self._wd = self._wr = self._wc = None
        self._loaded = False
        self._sug = None                 # sugestão pendente do deep link (aplicada após carregar os ativos)
        self._resp_pendente = None       # responsável a pré-selecionar (deep link: mesmo da OS pai)
        self._prog_tocada = False        # a data programada já foi editada à mão?

        self.setStyleSheet(QSS_FORM)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setObjectName("uiFlat"); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(); scroll.setWidget(body); outer.addWidget(scroll)
        lay = QVBoxLayout(body); lay.setContentsMargins(18, 12, 18, 14); lay.setSpacing(14)

        # ── cabeçalho: voltar aos planos + título ──
        head = QHBoxLayout(); head.setSpacing(10)
        b_back = QPushButton("← Planos"); b_back.setObjectName("secondary"); b_back.setFixedWidth(104)
        b_back.clicked.connect(self._on_voltar)
        head.addWidget(b_back)
        ic = QLabel(); ic.setPixmap(icone_pix(icone, GREEN, 20)); ic.setStyleSheet("background:transparent;border:none;")
        head.addWidget(ic)
        t = QLabel(titulo)
        t.setStyleSheet("font-size:16px;font-weight:600;color:%s;background:transparent;border:none;" % TEXT)
        head.addWidget(t); head.addStretch(1)
        self.seg = None
        if self._tem_modos:
            self.seg = Segmentado(["Geração", "Usina", "ETM"], on_change=self._set_modo)
            head.addWidget(self.seg)
        lay.addLayout(head)

        # ── Card 1: Ativo (cascata) ──
        self.cb_cli = QComboBox(); self.cb_cli.currentIndexChanged.connect(self._on_cli)
        self.cb_usi = QComboBox(); self.cb_usi.currentIndexChanged.connect(self._on_usi)
        self.busca = QLineEdit(); self.busca.setPlaceholderText("Filtrar ativo por código ou nome…")
        self.busca.addAction(QIcon(icone_pix("search", MUTED, 15)), QLineEdit.ActionPosition.LeadingPosition)
        self.busca.textChanged.connect(self._repop)
        c_ativo = Card(1, "Ativo")
        c_ativo.add(Linha(campo("Cliente", self.cb_cli, obrig=True), campo("Usina", self.cb_usi, obrig=True)))
        self.w_filtro = campo("Filtrar", self.busca, extra="(opcional)")
        c_ativo.add(self.w_filtro)
        lay.addWidget(c_ativo)

        # ── Card 2: Ativos (tabela: marcar + observação + anexos) ──
        b_all = self.b_all = QPushButton("Selecionar todos"); b_all.setObjectName("secondary")
        b_all.clicked.connect(lambda: self._marcar_todos(True))
        b_none = self.b_none = QPushButton("Limpar"); b_none.setObjectName("secondary")
        b_none.clicked.connect(lambda: self._marcar_todos(False))
        self.tbl = QTableWidget(0, 4)
        self.tbl.setHorizontalHeaderLabels(["Ativo", "OS Pai", "Observação", "Imagens"])
        self.tbl.setWordWrap(False)                             # nome do ativo em 1 linha (sem quebrar)
        # padding-left:0 no item → o check cola na borda e some a faixa escura à esquerda dele (a margem
        # do indicador de um item de tabela não recebe o fundo do item; qualquer padding>0 reintroduz).
        self.tbl.setStyleSheet("QTableWidget::item{padding-left:0px;}")
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.verticalHeader().setDefaultSectionSize(46)     # cabe o campo de observação sem estourar a linha
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)     # Ativo
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)       # OS Pai
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)     # Observação
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)       # Imagens
        self.tbl.setColumnWidth(1, 130); self.tbl.setColumnWidth(3, 104)
        self.tbl.setMinimumHeight(240)
        self.tbl.itemChanged.connect(self._on_item)
        self.sel_lbl = QLabel("0 marcado(s)"); self.sel_lbl.setObjectName("uiAjuda")
        c_at = Card(2, "Ativos")
        albl = QHBoxLayout(); albl.setSpacing(6)
        self.lb_ativos = rotulo("Ativos", obrig=True,
                                extra="(marque um ou vários — cada um vira uma OS)")
        albl.addWidget(self.lb_ativos, 1)
        albl.addWidget(b_all); albl.addWidget(b_none)
        c_at.add(albl)
        c_at.add(self.tbl, stretch=1)
        c_at.add(self.sel_lbl)
        lay.addWidget(c_at)

        # ── Card 3: Nome da OS (prefixo [Ativo] embutido no campo) + resumo do plano ──
        self.ed_nome = QLineEdit(self._base); self.ed_nome.setObjectName("uiFlatInput")
        self.ed_nome.textChanged.connect(self._upd_preview)
        box = QFrame(); box.setObjectName("uiPrefixBox")
        bl = QHBoxLayout(box); bl.setContentsMargins(8, 3, 8, 3); bl.setSpacing(8)
        self.chip_prefixo = QLabel("[Ativo]  -"); self.chip_prefixo.setObjectName("uiPrefixChip")
        bl.addWidget(self.chip_prefixo); bl.addWidget(self.ed_nome, 1)
        self.preview = QLabel(""); self.preview.setObjectName("uiAjuda"); self.preview.setWordWrap(True)
        self.resumo = QLabel("Selecione a usina para carregar o plano."); self.resumo.setObjectName("uiAjuda")
        self.resumo.setWordWrap(True)
        c_nome = Card("tag", "Nome da OS")
        self.lb_nome = rotulo("Nome da tarefa", obrig=True,
                              extra="(editável; o prefixo [Ativo] entra automático por OS)")
        c_nome.add(self.lb_nome); c_nome.add(box)
        c_nome.add(self.preview)
        c_nome.add(rotulo("Resumo do plano (só leitura)"))
        c_nome.add(self.resumo)
        lay.addWidget(c_nome)

        # ── Card 4: Responsável + vínculo ──
        self.dt_prog = QDateTimeEdit(); self.dt_prog.setCalendarPopup(True)
        self.dt_prog.setDisplayFormat("dd/MM/yyyy HH:mm")
        self.dt_prog.setDateTime(QDateTime.currentDateTime())
        # DATA PROGRAMADA à parte da do incidente: até aqui o Fracttal recebia "incidente + 10 min"
        # como programação, o que impedia abrir hoje uma OS para a semana que vem. Começa igual à
        # do incidente (comportamento antigo) e o usuário empurra se quiser.
        travar_no_passado(self.dt_prog)   # incidente: nunca no futuro (Levi, 07/08). A data
        # PROGRAMADA (dt_exec, abaixo) segue livre — ela é futura por definição.
        self.dt_exec = QDateTimeEdit(); self.dt_exec.setCalendarPopup(True)
        self.dt_exec.setDisplayFormat("dd/MM/yyyy HH:mm")
        self.dt_exec.setDateTime(QDateTime.currentDateTime().addDays(1))   # ida a campo = amanhã
        self.dt_prog.dateTimeChanged.connect(self._sincronizar_prog)
        self.dt_exec.dateTimeChanged.connect(lambda *_: setattr(self, "_prog_tocada", True))
        self.cb_resp = QComboBox(); self.cb_resp.addItem("carregando…", None)
        tornar_pesquisavel(self.cb_resp)
        self.b_resp_reload = QPushButton("↻"); self.b_resp_reload.setObjectName("secondary")
        self.b_resp_reload.setFixedWidth(40); self.b_resp_reload.setToolTip("Recarregar responsáveis")
        self.b_resp_reload.clicked.connect(self._carregar_resp)
        rrow = QWidget(); rrow.setObjectName("uiGroup")
        rrl = QHBoxLayout(rrow); rrl.setContentsMargins(0, 0, 0, 0); rrl.setSpacing(8)
        rrl.addWidget(self.cb_resp, 1); rrl.addWidget(self.b_resp_reload)
        c_resp = Card(4, "Responsável")
        c_resp.add(Linha(campo("Data do incidente", self.dt_prog, extra="(aplica a todas)"),
                         campo("Data programada", self.dt_exec, extra="(quando executar)")))
        c_resp.add(campo("Responsável", rrow, obrig=True, extra="(digite p/ pesquisar)"))
        # AGRUPAR (Levi, 21/08). É MODO, não regra fixa: quem precisa fechar inversor a inversor
        # continua podendo. Fica desmarcado por padrão — mudar o comportamento de quem não pediu
        # seria trocar o volume de OS por uma surpresa.
        self.ck_agrupar = QCheckBox("Agrupar em UMA OS com várias tarefas")
        self.ck_agrupar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ck_agrupar.setToolTip("Em vez de uma OS por ativo, cria uma OS só em que cada ativo "
                                   "vira uma tarefa. A OS só fecha quando TODAS forem concluídas.")
        self.ck_agrupar.toggled.connect(self._on_agrupar)
        # `clicked` só dispara no CLIQUE humano; `toggled` dispara também quando o código marca.
        # É o que separa "a pessoa decidiu" de "o app sugeriu" — sem isso, o auto-ligar
        # remarcaria a caixa que ela acabou de desmarcar, e ela não conseguiria sair do modo.
        self.ck_agrupar.clicked.connect(lambda *_: setattr(self, "_agrup_tocado", True))
        c_resp.add(campo("Volume de OS", self.ck_agrupar,
                         extra="(a OS só fecha quando todas as tarefas forem concluídas)"))
        # OS PAI ÚNICA no modo agrupado (Levi, 26/08): a OS é uma só, então pedir o pai por ativo
        # na tabela não faz sentido — 14 campos para um valor que só pode ser um.
        self.ed_pai_os = QLineEdit(); self.ed_pai_os.setPlaceholderText("nº da OS que originou")
        self.ed_pai_os.setFixedWidth(220)
        self._campo_pai_os = campo("OS pai", self.ed_pai_os, extra="(uma só, para a OS inteira)")
        self._campo_pai_os.setVisible(False)
        c_resp.add(self._campo_pai_os)
        # OBSERVAÇÃO DA OS (Levi, 26/08): o recado que vale para o lote inteiro. Não substitui a
        # observação POR ATIVO da tabela — as duas convivem, e foi conferido que o Fracttal guarda
        # a da OS separada das tarefas (OS 12273). Sem este campo, quem quisesse dizer algo geral
        # tinha de repetir a mesma frase em todas as linhas.
        self.ed_obs_os = QTextEdit(); self.ed_obs_os.setFixedHeight(66)
        self.ed_obs_os.setPlaceholderText("vale para a OS inteira — a observação por ativo continua "
                                          "na tabela acima")
        self._campo_obs_os = campo("Observação da OS", self.ed_obs_os,
                                   extra="(uma só, separada das observações por ativo)")
        self._campo_obs_os.setVisible(False)
        c_resp.add(self._campo_obs_os)
        lay.addWidget(c_resp)     # OS pai agora é por ativo, na coluna "OS Pai" da tabela de Ativos

        # ── botão (no fim, rolando) ──
        self.btn = QPushButton("Criar OS"); self.btn.setObjectName("btnPrimary")
        self.btn.setIcon(QIcon(icone_pix("send", GREEN_INK, 16))); self.btn.setIconSize(QSize(16, 16))
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.clicked.connect(self._criar)
        brow = QHBoxLayout(); brow.setContentsMargins(0, 4, 0, 0); brow.addStretch(1); brow.addWidget(self.btn)
        lay.addLayout(brow)
        self.hint = QLabel(""); self.hint.setObjectName("uiAjuda")
        lay.addWidget(self.hint, 0, Qt.AlignmentFlag.AlignRight)

        self._fill_clientes()
        tornar_todos_pesquisaveis(self)          # cliente/usina/responsável pesquisáveis (criado sob demanda)

    def carregar_inicial(self):
        if not self._loaded:
            self._loaded = True
            self._carregar_resp()

    def _sincronizar_prog(self, dt):
        """Mantém a data programada em AMANHÃ enquanto ninguém a editar à mão.

        AMANHÃ EM RELAÇÃO A AGORA, não ao incidente (Levi, 03/08). Antes era incidente + 1 dia, e
        isso agendava no PASSADO sempre que a falha era antiga: incidente de 28/07 lançado hoje
        marcava a ida a campo para 29/07, que já passou. A data do incidente diz quando quebrou; a
        programada diz quando alguém vai lá — são independentes, e só a segunda tem de olhar o
        relógio. O `dt` continua na assinatura porque quem chama é o sinal do campo do incidente.

        O `_prog_tocada` é o que separa "eu movi" de "o usuário mexeu" — uma vez que a pessoa
        escolhe a data, esta função não encosta mais. O blockSignals evita o auto-disparo."""
        if self._prog_tocada:
            return
        self.dt_exec.blockSignals(True)
        self.dt_exec.setDateTime(QDateTime.currentDateTime().addDays(1))
        self.dt_exec.blockSignals(False)

    # ── modos do card "Geração e ETM" ──
    def _etm(self):
        return self._tem_modos and self._modo == MODO_ETM

    def _usina_inteira(self):
        """Modo Usina: UMA OS no ativo da planta, em vez de uma por inversor."""
        return self._tem_modos and self._modo == MODO_USINA

    def _set_modo(self, i):
        """Troca Geração ↔ ETM. Só muda o que É diferente entre os dois: quais ativos aparecem, o
        título e o tamanho do bloco de ativos. Plano, cascata e responsável seguem os mesmos."""
        self._modo = i if i in (MODO_GERACAO, MODO_USINA, MODO_ETM) else MODO_GERACAO
        etm, usi = self._etm(), self._usina_inteira()
        unico = etm or usi        # os dois modos escolhem UM ativo: mesma simplificação de tela
        # ETM = 1 estação por usina: não precisa de filtro, nem de 'selecionar todos', nem de tabela alta
        self.w_filtro.setVisible(not unico)
        self.b_all.setVisible(not unico); self.b_none.setVisible(not unico)
        self.lb_ativos.setText(
            rotulo("Estação meteorológica", obrig=True, extra="(a estação da usina)").text() if etm
            else rotulo("Usina", obrig=True, extra="(a planta inteira — UMA OS só)").text() if usi
            else rotulo("Ativos", obrig=True, extra="(marque um ou vários — cada um vira uma OS)").text())
        # título: em ETM é fixo, e o campo vira só leitura para deixar isso explícito
        self.chip_prefixo.setText("[ETM]  -" if etm else "[Usina]  -" if usi else "[Ativo]  -")
        self.ed_nome.setReadOnly(unico)
        self.lb_nome.setText(
            rotulo("Nome da tarefa", obrig=True,
                   extra="(fixo para ETM)" if etm else "(fixo para Usina)" if usi
                   else "(editável; o prefixo [Ativo] entra automático por OS)").text())
        _fixos = {ETM_TITULO.split(" - ", 1)[1], USINA_TITULO.split(" - ", 1)[1]}
        if etm:
            self.ed_nome.setText(ETM_TITULO.split(" - ", 1)[1])
        elif usi:
            self.ed_nome.setText(USINA_TITULO.split(" - ", 1)[1])
        elif self.ed_nome.text().strip() in _fixos:
            self.ed_nome.setText(self._base)
        self._checked = set()
        self._agrup_tocado = False       # tela nova = a sugestão automática volta a valer
        self._repop()
        self._marcar_etm()

    def _marcar_etm(self):
        """Em ETM e em Usina o ativo já vem marcado — é sempre ele; obrigar o clique seria só
        cerimônia, e nos dois modos a lista tem uma linha."""
        if not (self._etm() or self._usina_inteira()):
            return
        self.tbl.blockSignals(True)
        for r in range(self.tbl.rowCount()):
            it = self.tbl.item(r, 0)
            aid = it.data(Qt.ItemDataRole.UserRole)
            it.setCheckState(Qt.CheckState.Checked)
            self._checked.add(aid)
            self._render_cells(r, aid, True)
        self.tbl.blockSignals(False)
        self._upd_count()

    def _titulo_os(self, asset, base):
        """Título final de UMA OS. ETM tem título literal (pedido do Levi): sempre o mesmo texto,
        sem o nome do ativo — a estação é uma só e '[Estação Meteorológica]' só ocuparia espaço."""
        return ETM_TITULO if self._etm() else api.perf_os_nome(asset, base)

    # ── cascata ──
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

    def _carteiras_de(self, a):
        """TODAS as carteiras a que o ativo pode pertencer: o campo `cliente` E o prefixo da usina.

        O Fracttal diverge entre os dois. Caso real (Ana Barros, 19/08): cliente "Ultragaz" com as
        usinas "Utragaz - Ibirapuã 1 e 2 - BA" — falta o "l" no cadastro. Como o dropdown de Cliente
        é montado pelo campo `cliente` e o filtro de usinas casava só pelo PREFIXO, escolher
        "Ultragaz" não trazia usina nenhuma: as duas plantas do cliente, 359 ativos, sumiam.
        O COS já resolvia assim desde 28/07 (`varias_os._carteiras_de`); o Performance ficou de fora."""
        out = set()
        c = (a.get("cliente") or "").strip()
        if c:
            out.add(c)
        u = a.get("usina") or ""
        if " - " in u and self._carteira(u):
            out.add(self._carteira(u))
        return out

    def _cliente_da_usina(self, usi):
        """Cliente de uma usina pelo campo `cliente` de um ativo dela — que é a fonte do dropdown.
        Cai no prefixo só se nenhum ativo tiver o campo. É o que faz escolher "Utragaz - …"
        selecionar o cliente certo, "Ultragaz"."""
        for a in self._assets:
            if a.get("usina") == usi and (a.get("cliente") or "").strip():
                return a["cliente"].strip()
        return self._carteira(usi)

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
        return self.cb_cli.currentText() if self.cb_cli.currentIndex() > 0 else None

    def _usi(self):
        return self.cb_usi.currentText() if self.cb_usi.currentIndex() > 0 else None

    def _fill_usinas(self):
        """Usina filtrada pela carteira do cliente (ou TODAS se nenhum). Preserva a usina escolhida."""
        cli, cur = self._cli(), self._usi()
        # base = usinas de equipamento cuja CARTEIRA é um cliente real (exclui inventário/material)
        base = [a for a in self._assets if a.get("usina") and a.get("tipo") in _CARTEIRA_EQUIP
                and (self._carteiras_de(a) & self._clientes_reais)]
        if cli:
            usinas = sorted({a["usina"] for a in base if cli in self._carteiras_de(a)})
        else:                          # LIVRE: todas as usinas de planta (sem materiais)
            usinas = sorted({a["usina"] for a in base})
        self.cb_usi.blockSignals(True); self.cb_usi.clear()
        self.cb_usi.addItem("— Selecione a usina —"); self.cb_usi.addItems(usinas)
        if cur and cur in usinas:
            self.cb_usi.setCurrentIndex(self.cb_usi.findText(cur))
        self.cb_usi.setEnabled(True); self.cb_usi.blockSignals(False)

    def _on_cli(self, *_):
        self._fill_usinas()
        self._on_usi()

    def _on_usi(self, *_):
        usi = self._usi()
        if usi and " - " in usi:       # usina nomeada → auto-preenche o Cliente pela carteira (prefixo)
            cart = self._cliente_da_usina(usi)      # campo `cliente`, não o prefixo (pode ter typo)
            if cart and self.cb_cli.currentText() != cart and self.cb_cli.findText(cart) >= 0:
                self.cb_cli.blockSignals(True)
                self.cb_cli.setCurrentIndex(self.cb_cli.findText(cart))
                self.cb_cli.blockSignals(False)
                self._fill_usinas()    # re-filtra a usina p/ a carteira (mantém a seleção)
        self._alvos = []; self._alvo_by_id = {}
        self._checked = set(); self._obs = {}; self._ospai = {}; self._imgs = {}
        self.tbl.setRowCount(0); self._upd_count()
        self.resumo.setText("Selecione a usina para carregar o plano.")
        self.preview.setText("")
        usi = self._usi()
        if not usi:
            return
        # o item-usina (tipo 'Usina') NÃO está em PERF_TIPOS, mas o card de coleta precisa dele
        # para o modo Usina — sem isto ele nunca chegava ao `get_performance_alvos` e o modo abria
        # com a lista vazia, mesmo a função sabendo montá-lo.
        _tipos = tuple(api.PERF_TIPOS) + ((USINA_TIPO,) if self._tem_modos else ())
        ativos_usi = [a for a in self._assets
                      if a.get("usina") == usi and a.get("tipo") in _tipos]
        if not ativos_usi:
            self.hint.setText("Sem inversores/trackers/estação nesta usina."); return
        self.hint.setText("buscando ativos com o plano…")
        self._wa = ApiWorker(api.get_performance_alvos, ativos_usi, self._frase)
        self._wa.ok.connect(self._set_alvos)
        self._wa.erro.connect(self._alvos_err)
        self._wa.start()

    def _set_alvos(self, res):
        self._wa = None
        res = res or {}
        if res.get("erro"):
            self.hint.setText("⚠ " + res["erro"])
        self._is_tracker = res.get("is_tracker", self._is_tracker)
        self._base = res.get("base") or self._titulo
        if self.ed_nome.text().strip() in ("", self._titulo):
            self.ed_nome.setText(self._base)
        self._alvos = res.get("ativos") or []
        self._alvo_by_id = {al["asset"].get("id"): al for al in self._alvos}
        self._repop()
        self._marcar_etm()                    # ETM: a estação já entra marcada
        if self._alvos:
            # conta as LINHAS, não os alvos: em ETM a lista mostra só a estação
            self.hint.setText("%d ativo(s) com o plano." % self.tbl.rowCount())
            self._carregar_resumo(self._alvos[0])
        elif not res.get("erro"):
            self.hint.setText("Nenhum ativo desta usina tem esse plano.")
            self.resumo.setText("—")
        self._aplicar_sug_pendente()          # deep link: marca o inversor + obs (POR ÚLTIMO p/ o aviso do link não ser sobrescrito)

    def _alvos_err(self, m):
        self._wa = None
        self.hint.setText("⚠ ativos: " + str(m))

    def aplicar_sugestao(self, dados):
        """Deep link (gridos://performance): guarda a sugestão (ativo/obs) e pré-seleciona a usina na
        cascata → a carga async dispara e `_set_alvos` aplica o resto. Best-effort, tolerante a divergência."""
        try:
            d = dados or {}
            self._sug = {"ativo": (d.get("ativo") or "").strip(),
                         "obs": (d.get("obs") or "").strip(),
                         "usina": (d.get("usina") or "").strip(),
                         # OS atribuída ao inversor na plataforma → vira a OS PAI do ativo casado
                         "os_pai": (d.get("os_pai") or "").strip()}
            # Deep link de ETM (plataforma, 27/08): cai direto no modo ETM do segmentado — "Geração e
            # ETM > Seleciona ETM > Seleciona Usina, pronto" (Levi). Vale pelo `modo=etm` explícito OU
            # pelo ativo sugerido ser a estação; ANTES de casar a usina, porque trocar o modo repopula
            # a tabela e o _aplicar_sug_pendente precisa ver a lista do modo certo.
            if self._tem_modos and getattr(self, "seg", None) is not None:
                _modo = api._norm_txt(d.get("modo") or "")
                if _modo == "etm" or "estacao meteorologica" in api._norm_txt(d.get("ativo") or ""):
                    self.seg.set_index(MODO_ETM)
            if (d.get("resp") or "").strip():
                self._resp_pendente = str(d["resp"]).strip()
                self._aplicar_resp_pendente()          # tenta já; se o combo não carregou, o _set_resp reaplica
            usi = self._sug["usina"]
            if not usi:
                return
            nu = api._norm_txt(usi)
            cli = next((a.get("cliente") for a in self._assets
                        if a.get("usina") and (api._norm_txt(a["usina"]) == nu
                                               or nu in api._norm_txt(a["usina"])
                                               or api._norm_txt(a["usina"]) in nu)), None)
            if cli:
                self.cb_cli.setCurrentText(cli)          # dispara _on_cli → preenche as usinas
            casou = False
            for i in range(1, self.cb_usi.count()):      # casa a usina (exata ou aproximada, bidirecional)
                t = api._norm_txt(self.cb_usi.itemText(i))
                if t == nu or nu in t or t in nu:
                    self.cb_usi.setCurrentIndex(i); casou = True; break   # dispara _on_usi → carga → _set_alvos
            if not casou:
                self.hint.setText(f"⚠ Deep link: usina “{usi}” não encontrada no catálogo do Fracttal.")
        except Exception:
            self._sug = None

    def _aplicar_sug_pendente(self):
        """Chamado por `_set_alvos` após os ativos carregarem: marca o inversor da sugestão + preenche a
        observação, depois limpa a pendência. Casa o ativo pelo nome curto (ex.: 'Inversor 1.1') OU pelo
        número (1.1) — tolerante a 'Inversor'/'Inv'/código divergente entre plataforma e Fracttal.
        Deixa um aviso no hint dizendo o que bateu (ou os ativos disponíveis) p/ diagnóstico do deep link."""
        import re
        sug = self._sug
        if not sug or not sug.get("ativo"):
            return
        def _num(s):                                      # sequência numérica do ativo: "Inversor 1.1" → "1.1"
            m = re.search(r"\d+(?:[.\-]\d+)*", str(s or "")); return m.group(0).replace("-", ".") if m else ""
        try:
            alvo = api._norm_txt(sug["ativo"]); alvo_n = _num(sug["ativo"])
            achou = None
            # 1) match EXATO: nome normalizado igual OU número igual. O número é a chave confiável —
            #    "2.18" != "2.1", então NÃO confunde Inversor 2.1 com Inversor 2.18 (bug do 'in').
            for al in self._alvos:
                snome = api._asset_short_name(al["asset"]); nm = api._norm_txt(snome)
                if nm == alvo or (alvo_n and alvo_n == _num(snome)):
                    achou = al; break
            # 2) fallback tolerante a nome divergente (plataforma×Fracttal) — mas se AMBOS têm número e
            #    eles divergem, NÃO casa (impede "2.1" ⊂ "2.18").
            if not achou:
                for al in self._alvos:
                    snome = api._asset_short_name(al["asset"]); nm = api._norm_txt(snome); sn = _num(snome)
                    if alvo and (alvo in nm or nm in alvo):
                        if alvo_n and sn and alvo_n != sn:
                            continue
                        achou = al; break
            if achou:
                aid = achou["asset"].get("id")
                self._checked.add(aid)
                if sug.get("obs"):
                    self._obs[aid] = sug["obs"]
                if sug.get("os_pai"):                 # deep link → OS pai vai no campo do ativo casado
                    self._ospai[aid] = sug["os_pai"]
                self.hint.setText(f"✓ Deep link: ativo “{api._asset_short_name(achou['asset'])}” selecionado.")
            elif self._alvos:
                disp = ", ".join(api._asset_short_name(a["asset"]) for a in self._alvos[:8])
                self.hint.setText(f"⚠ Deep link: ativo “{sug['ativo']}” não bateu. Disponíveis: {disp}")
        except Exception:
            pass
        finally:
            self._sug = None
            try:
                self._repop()
            except Exception:
                pass

    def _repop(self, *_):
        txt = (self.busca.text() or "").strip().lower()
        self.tbl.blockSignals(True)
        self._limpar_celulas()
        self.tbl.setRowCount(0)
        etm, usi = self._etm(), self._usina_inteira()
        for al in self._alvos:
            a = al["asset"]; aid = a.get("id")
            # o plano é o mesmo para inversor, estação e planta; o MODO é que decide quem aparece
            if self._tem_modos:
                tp = a.get("tipo")
                alvo = ETM_TIPO if etm else USINA_TIPO if usi else None
                if alvo and tp != alvo:
                    continue
                if alvo is None and tp in (ETM_TIPO, USINA_TIPO):
                    continue                    # modo Geração = só os inversores
            full = a.get("label") or a.get("code") or "?"
            nome = api._asset_short_name(a)                     # compacto (ex.: "Inversor 1.1")
            if txt and txt not in full.lower() and txt not in nome.lower():
                continue
            r = self.tbl.rowCount(); self.tbl.insertRow(r)
            it = QTableWidgetItem(nome); it.setToolTip(full)    # nome completo no hover
            it.setData(Qt.ItemDataRole.UserRole, aid)
            it.setFlags((it.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsEditable)
            it.setCheckState(Qt.CheckState.Checked if aid in self._checked else Qt.CheckState.Unchecked)
            self.tbl.setItem(r, 0, it)
            self._render_cells(r, aid, aid in self._checked)
        self.tbl.blockSignals(False)
        # ETM = a estação da usina, quase sempre UMA linha: a tabela encolhe para o conteúdo em vez
        # de deixar meia tela de vazio. Continua certo se a usina tiver duas estações.
        if etm or usi:
            alt = self.tbl.horizontalHeader().height() + 46 * max(1, self.tbl.rowCount()) + 6
            self.tbl.setMinimumHeight(alt); self.tbl.setMaximumHeight(alt)
            # nem toda usina tem estação CADASTRADA no Fracttal (Linhares 1 e Tanabi 1, por ex.).
            # Sem este aviso a tela abria vazia e parecia quebrada — foi o que aconteceu.
            if self._alvos and not self.tbl.rowCount():
                self.hint.setText("⚠ esta usina não tem %s cadastrada no Fracttal."
                                  % ("Estação Meteorológica" if etm else "o item de usina"))
        else:
            self.tbl.setMinimumHeight(240); self.tbl.setMaximumHeight(16777215)
        self._upd_count()

    def _limpar_celulas(self):
        """Mata os widgets de célula ANTES de zerar as linhas — `setRowCount(0)` só desfaz o vínculo.
        A varredura do viewport pega também os órfãos de um `setRowCount(0)` que já rodou sem
        limpeza (é o que o `_on_usi` faz ao trocar de usina)."""
        for r in range(self.tbl.rowCount()):
            for c in range(self.tbl.columnCount()):
                _matar_celula(self.tbl, r, c)
        for w in list(self.tbl.viewport().children()):
            if isinstance(w, QWidget) and w.isVisible():
                w.setParent(None)
                w.deleteLater()

    def _render_cells(self, r, aid, checked):
        """Marcada: nome branco (fundo levemente verde) + campo de observação + anexo ativo. Desmarcada:
        nome apagado + '—' + anexo desabilitado — deixa nítido o que está selecionado."""
        it = self.tbl.item(r, 0)
        if it is not None:
            it.setForeground(QBrush(QColor(TEXT if checked else MUTED)))
            it.setBackground(QBrush(QColor(166, 226, 46, 22)) if checked else QBrush(Qt.GlobalColor.transparent))
        # a coluna 3 (Imagens) entra na limpeza: sobrescrever com setCellWidget não destrói o antigo
        for c in (1, 2, 3):
            _matar_celula(self.tbl, r, c)
        if checked:
            self.tbl.takeItem(r, 1); self.tbl.takeItem(r, 2)
            pai = QLineEdit(self._ospai.get(aid, ""))
            pai.setPlaceholderText("nº")               # cabeçalho já diz "OS Pai" — placeholder curto
            pai.textChanged.connect(lambda tx, k=aid: self._ospai.__setitem__(k, tx))
            self.tbl.setCellWidget(r, 1, _cell_campo(pai))
            obs = QLineEdit(self._obs.get(aid, ""))
            obs.setPlaceholderText("motivo / observação (opcional)")
            obs.textChanged.connect(lambda tx, k=aid: self._obs.__setitem__(k, tx))
            self.tbl.setCellWidget(r, 2, _cell_campo(obs))
        else:
            for col in (1, 2):
                dash = QTableWidgetItem("—"); dash.setForeground(QBrush(QColor(MUTED)))
                dash.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.tbl.setItem(r, col, dash)
        self.tbl.setCellWidget(r, 3, _centrar(self._attach_btn_for(aid, checked)))

    def _attach_btn_for(self, aid, checked=True):
        n = len(self._imgs.get(aid, []))
        tem = bool(n and checked)
        btn = QPushButton(str(n) if n else "")
        btn.setObjectName("secondary")
        btn.setIcon(QIcon(icone_pix("image", GREEN if tem else MUTED, 14)))
        btn.setFixedWidth(72)
        btn.setEnabled(bool(checked))
        btn.setToolTip("Anexar imagens (arquivo ou colar com Ctrl+V)")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # min/max-height inline sobrepõem o min-height:38 do QSS → botão baixo que cabe na linha (46px)
        _brd = GREEN if tem else BORDER
        _col = GREEN if tem else "#cdd2e0"
        _wt = "700" if tem else "500"
        btn.setStyleSheet("QPushButton#secondary{background:transparent;border:1px solid %s;border-radius:7px;"
                          "min-height:24px;max-height:24px;padding:0 8px;color:%s;font-weight:%s;font-size:12px;}"
                          % (_brd, _col, _wt))
        btn.clicked.connect(lambda _c, k=aid: self._anexar(k))
        return btn

    def _on_item(self, it):
        if it.column() != 0:
            return
        aid = it.data(Qt.ItemDataRole.UserRole)
        checked = it.checkState() == Qt.CheckState.Checked
        (self._checked.add if checked else self._checked.discard)(aid)
        self.tbl.blockSignals(True)
        self._render_cells(it.row(), aid, checked)
        self.tbl.blockSignals(False)
        self._upd_count()

    def _marcar_todos(self, marcar):
        self.tbl.blockSignals(True)
        for r in range(self.tbl.rowCount()):
            it = self.tbl.item(r, 0)
            aid = it.data(Qt.ItemDataRole.UserRole)
            it.setCheckState(Qt.CheckState.Checked if marcar else Qt.CheckState.Unchecked)
            (self._checked.add if marcar else self._checked.discard)(aid)
            self._render_cells(r, aid, marcar)
        self.tbl.blockSignals(False)
        self._upd_count()

    def _on_agrupar(self, *_):
        """Liga/desliga o que muda de FORMA no modo agrupado: título único (sem o prefixo [Ativo]),
        OS pai única e o texto do cabeçalho da tabela."""
        ag = bool(self.ck_agrupar.isChecked())
        self._campo_pai_os.setVisible(ag)
        self._campo_obs_os.setVisible(ag)
        self.tbl.setColumnHidden(1, ag)          # coluna "OS Pai" por ativo
        self.chip_prefixo.setVisible(not ag)
        self.lb_nome.setText(
            rotulo("Nome da tarefa", obrig=True,
                   extra="(vale para a OS e para TODAS as tarefas)" if ag
                   else "(editável; o prefixo [Ativo] entra automático por OS)").text())
        self.lb_ativos.setText(
            rotulo("Ativos", obrig=True,
                   extra="(marque um ou vários — todos numa OS só)" if ag
                   else "(marque um ou vários — cada um vira uma OS)").text())
        self._upd_count()

    def _agrupar(self):
        """Modo 'uma OS com N tarefas'. Só faz sentido com 2+ ativos — com 1 marcado o resultado
        é idêntico ao normal, e prometer 'agrupada' para uma tarefa só confunde."""
        return bool(getattr(self, "ck_agrupar", None)) and self.ck_agrupar.isChecked()             and len(self._checked) > 1

    def _auto_agrupar(self):
        """Mais de um ativo → agrupa por padrão (Levi, 26/08). Uma OS por ativo virou a exceção.

        Só age ENQUANTO a pessoa não tiver mexido na caixa: a partir do primeiro clique dela, a
        escolha é dela e o app não mexe mais. Também não desmarca ao voltar para 1 ativo — quem
        tirou um ativo da lista não pediu para mudar de modo."""
        if self._agrup_tocado or not hasattr(self, "ck_agrupar"):
            return
        if len(self._checked) > 1 and not self.ck_agrupar.isChecked():
            self.ck_agrupar.setChecked(True)      # dispara o _on_agrupar, que abre os campos

    def _upd_count(self, *_):
        self._auto_agrupar()
        n = len(self._checked)
        if self._agrupar():
            self.sel_lbl.setText("%d marcado(s)  ·  1 OS com %d tarefas" % (n, n))
        else:
            self.sel_lbl.setText("%d marcado(s)  ·  %d OS a criar" % (n, n))
        self._upd_preview()

    def _upd_preview(self, *_):
        base = self.ed_nome.text().strip() or self._base
        alvo = None
        for aid in self._checked:
            alvo = self._alvo_by_id.get(aid); break
        if alvo is None and self._alvos:
            alvo = self._alvos[0]
        if alvo is not None:
            self.preview.setText("Fica, por ex.: <b>%s</b>  ·  a observação de cada OS vem da tabela de ativos acima."
                                 % self._titulo_os(alvo["asset"], base))
        else:
            self.preview.setText("A observação de cada OS vem da tabela de ativos acima.")

    # ── resumo do plano (só leitura) ──
    def _carregar_resumo(self, alvo):
        self.resumo.setText("carregando o plano…")
        self._wd = ApiWorker(api.get_plan_details, alvo["plano_id_task"], alvo["plano_id_item"])
        self._wd.ok.connect(self._set_resumo)
        self._wd.erro.connect(lambda m: self.resumo.setText("⚠ plano: " + str(m)))
        self._wd.start()

    def _set_resumo(self, plan):
        self._wd = None
        plan = plan or {}
        partes = []
        tipo = (plan.get("tasks_types_main_description") or "").strip()
        c1 = (plan.get("tasks_types_description") or "").strip()
        c2 = (plan.get("tasks_types_2_description") or "").strip()
        crit = _CRIT.get(plan.get("id_priorities"))
        dur = int(plan.get("duration") or 0)
        if tipo: partes.append(f"<b>Tipo:</b> {tipo}")
        if c1:   partes.append(f"<b>Classif. 1:</b> {c1}")
        if c2:   partes.append(f"<b>Classif. 2:</b> {c2}")
        if crit: partes.append(f"<b>Criticidade:</b> {crit}")
        if dur:  partes.append(f"<b>Duração:</b> {round(dur / 60)} min")
        self.resumo.setText("  ·  ".join(partes) if partes
                            else "Plano sem detalhes (confira no Fracttal).")

    # ── anexo por ativo ──
    def _anexar(self, aid):
        a = (self._alvo_by_id.get(aid) or {}).get("asset") or {}
        dlg = PerfAnexoDialog(self, a.get("label") or a.get("code") or "ativo",
                              self._imgs.setdefault(aid, []))
        dlg.exec()
        self._repop()      # atualiza o rótulo do botão (N imagens)

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
        self._aplicar_resp_pendente()                  # deep link: pré-seleciona o responsável da OS pai

    def _aplicar_resp_pendente(self):
        """Pré-seleciona no combo o responsável pendente do deep link (mesmo da OS pai), casando pelo
        nome (tolerante a espaços duplos/caixa). Se o combo ainda não carregou, fica pendente e o
        _set_resp reaplica quando carregar."""
        import re
        alvo = re.sub(r"\s+", " ", (getattr(self, "_resp_pendente", None) or "")).strip().lower()
        if not alvo:
            return
        for i in range(self.cb_resp.count()):
            p = self.cb_resp.itemData(i)
            if isinstance(p, dict) and re.sub(r"\s+", " ", (p.get("name") or "")).strip().lower() == alvo:
                self.cb_resp.setCurrentIndex(i)
                self._resp_pendente = None
                return

    def _resp_err(self, m):
        self._wr = None
        self.cb_resp.clear(); self.cb_resp.addItem("⚠ falha — relogue e clique em ↻", None)
        self.hint.setText("⚠ responsável: " + str(m))

    # ── criar N OS ──
    def _criar(self):
        if not self._checked:
            QMessageBox.warning(self, "Ativos", "Marque ao menos um ativo."); return
        p = self.cb_resp.currentData()
        if not isinstance(p, dict) or not p.get("id_personnel"):
            QMessageBox.warning(self, "Responsável", "Escolha o responsável."); return
        base = self.ed_nome.text().strip() or self._base
        brt = _dt.timezone(_dt.timedelta(hours=-3))
        evt = self.dt_prog.dateTime().toPyDateTime().replace(tzinfo=brt)
        prog = self.dt_exec.dateTime().toPyDateTime().replace(tzinfo=brt)
        etm = self._etm()
        usina_toda = self._usina_inteira()
        ag_tit = ""      # título literal do modo agrupado (sem o prefixo [Ativo])
        ag_pai = ag_obs = ""
        if self._agrupar():
            # TÍTULO ÚNICO. O Fracttal NÃO aceita título próprio na OS — testei na 12188, ele
            # ignora o `description` do work_order_insert e copia o da PRIMEIRA tarefa. Então a
            # única forma de a OS se chamar "Inspeção Geral de Inversores" é as tarefas se
            # chamarem assim. Quem distingue passa a ser o ativo de cada tarefa, e o card do
            # histórico mostra o ativo no seletor justamente por isso.
            ag_tit = base
            ag_pai = self.ed_pai_os.text().strip()
            ag_obs = self.ed_obs_os.toPlainText().strip()
        itens = []
        for al in self._alvos:
            aid = al["asset"].get("id")
            if aid not in self._checked:
                continue
            itens.append({"asset": al["asset"], "plano_id_task": al["plano_id_task"],
                          "plano_id_item": al["plano_id_item"], "linkar": al.get("linkar", True),
                          "base": base, "note": self._obs.get(aid, ""),
                          # ETM e Usina usam título LITERAL, sem o prefixo [Ativo]
                          "titulo": ETM_TITULO if etm else (USINA_TITULO if usina_toda
                                                           else (ag_tit or "")),
                          # agrupado → a OS pai é UMA para a OS inteira; senão, a da linha do ativo
                          "os_pai": ag_pai or (self._ospai.get(aid, "") or "").strip(),
                          "imagens": self._imgs.get(aid, [])})
        n_img = sum(len(it["imagens"]) for it in itens)
        extra = f"\n{n_img} imagem(ns) serão anexadas." if n_img else ""
        aviso = ("\nTrackers individuais: as OS usam o plano da 'Estrutura Trackers' (subtarefas copiadas)."
                 if self._is_tracker else "")
        if etm:
            aviso += f"\nTítulo: {ETM_TITULO} · etiquetas: PERFORMANCE + ENGENHARIA."
        if usina_toda:
            aviso += (f"\nUMA OS na planta inteira, no lugar de uma por inversor."
                      f"\nTítulo: {USINA_TITULO}")
        aviso += "\nProgramada para %s." % self.dt_exec.dateTime().toString("dd/MM/yyyy HH:mm")
        agrupar = self._agrupar()
        if agrupar:
            # o que MUDA no modo agrupado, dito ANTES de criar — as duas perdas medidas em 21/08.
            aviso += ("\nUMA OS com %d tarefas, uma por ativo, no lugar de %d OS."
                      "\nA OS só fecha quando TODAS as tarefas forem concluídas."
                      "\nA OS pai por ativo não vai (a OS é uma só), e as tarefas"
                      " nascem sem data de início/fim — quem preenche é o cronômetro."
                      % (len(itens), len(itens)))
            cabecalho = ("Vou criar 1 OS com %d tarefas — uma por ativo — com o plano '%s'."
                         % (len(itens), self._titulo))
        else:
            cabecalho = ("Vou criar %d OS — uma por ativo — com o plano '%s'."
                         % (len(itens), self._titulo))
        if QMessageBox.question(self, "Criar OS de Performance",
                f"{cabecalho}{aviso}{extra}"
                f"\n\nContinuar?") != QMessageBox.StandardButton.Yes:
            return
        self.btn.setEnabled(False)
        if agrupar:
            self.hint.setText("criando 1 OS com %d tarefas… (pode levar alguns segundos)" % len(itens))
            self._wc = ApiWorker(api.create_performance_os_agrupada, itens, p.get("id_personnel"),
                                 p.get("name"), evt, prog_date=prog,
                                 etiquetas_extra=list(ETM_ETIQUETAS) if etm else None,
                                 note_os=ag_obs)
            self._wc.ok.connect(self._criou_agrupada)
            self._wc.erro.connect(self._err)
            self._wc.start()
            return
        self.hint.setText(f"criando {len(itens)} OS… (pode levar alguns segundos)")
        self._wc = ApiWorker(api.create_performance_os, itens, p.get("id_personnel"), p.get("name"), evt,
                             prog_date=prog, etiquetas_extra=list(ETM_ETIQUETAS) if etm else None)
        self._wc.ok.connect(self._criou)
        self._wc.erro.connect(self._err)
        self._wc.start()

    def _criou(self, res):
        self._wc = None
        self.btn.setEnabled(True); self.hint.setText("")
        res = res or []
        ok = [r for r in res if r.get("ok")]
        fail = [r for r in res if not r.get("ok")]
        erros_img = [e for r in ok for e in (r.get("img_erro") or [])]
        if not ok:
            QMessageBox.critical(self, "Erro", "Nenhuma OS criada.\n" +
                "\n".join(f"• {r.get('asset')}: {r.get('erro')}" for r in fail[:8]))
            return
        folios = ", ".join(str(r.get("folio") or "?") for r in ok[:12])
        msg = f"{len(ok)} OS criada(s) — Nº {folios}" + (" …" if len(ok) > 12 else "") + "."
        if fail:
            msg += (f"\n\n{len(fail)} falharam:\n" +
                    "\n".join(f"• {r.get('asset')}: {r.get('erro')}" for r in fail[:6]))
        box = QMessageBox(self)
        box.setWindowTitle("OS de Performance")
        box.setIcon(QMessageBox.Icon.Warning if erros_img else QMessageBox.Icon.Information)
        if erros_img:
            msg += (f"\n\n⚠ {len(erros_img)} imagem(ns) não anexaram. Clique em “Mostrar detalhes”, "
                    "copie o texto e me mande (é a resposta do upload que eu preciso pra ajustar).")
            box.setDetailedText("\n\n".join(erros_img))
        box.setText(msg)
        box.exec()
        for aid in list(self._checked):        # limpa marcações após criar
            self._checked.discard(aid)
        self._imgs = {}
        self._repop()

    @slot_seguro
    def _criou_agrupada(self, r):
        """Resultado do modo agrupado. Dict de UMA OS, não a lista de N — por isso não dá para
        reaproveitar o `_criou`: lá cada linha é uma OS, aqui as linhas são TAREFAS da mesma."""
        self._wc = None
        self.btn.setEnabled(True); self.hint.setText("")
        r = r or {}
        if not r.get("ok"):
            QMessageBox.critical(self, "Erro", str(r.get("erro") or "Nenhuma OS criada."))
            return
        folio = r.get("folio")
        if folio:
            msg = "OS %s criada com %d tarefa(s)." % (folio, r.get("n_criadas") or 0)
        else:
            # as tarefas existem mas a OS numerada não saiu — dizer isso é o que evita a pessoa
            # criar tudo de novo e duplicar o trabalho no Fracttal.
            msg = "%d tarefa(s) criadas, mas SEM número de OS." % (r.get("n_criadas") or 0)
        if r.get("n_img_ok"):
            msg += "  %d imagem(ns) anexada(s)." % r["n_img_ok"]
        if r.get("aviso"):
            msg += "\n\n" + r["aviso"]
        det = list(r.get("erros") or []) + list(r.get("img_erro") or [])
        box = QMessageBox(self)
        box.setWindowTitle("OS de Performance")
        box.setIcon(QMessageBox.Icon.Warning if det or not folio else QMessageBox.Icon.Information)
        box.setText(msg)
        if det:
            box.setDetailedText("\n".join(str(x) for x in det))
        box.exec()
        for aid in list(self._checked):
            self._checked.discard(aid)
        self._imgs = {}
        self._repop()

    def _err(self, m):
        self._wc = None
        self.btn.setEnabled(True); self.hint.setText("")
        QMessageBox.critical(self, "Erro", str(m))


class PerfAnexoDialog(QDialog):
    """Anexos de UM ativo: adicionar arquivo(s) OU colar captura (Ctrl+V). Miniaturas com remover.
    Muta a lista `imgs` recebida (cada item = {'bytes','nome','thumb'})."""
    def __init__(self, parent, nome_ativo, imgs):
        super().__init__(parent)
        self._imgs = imgs
        self.setWindowTitle(f"Imagens — {nome_ativo}")
        self.setMinimumSize(520, 460)
        self.setStyleSheet(QSS_FORM + "QDialog{background:%s;}" % CARD)
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 16, 18, 16); lay.setSpacing(12)
        top = QLabel(f"Anexar imagens à OS de <b>{nome_ativo}</b>")
        top.setStyleSheet("background:transparent;")
        lay.addWidget(top)
        dica = QLabel("Adicione arquivos ou cole uma captura de tela com <b>Ctrl+V</b>.")
        dica.setObjectName("uiAjuda"); lay.addWidget(dica)
        brow = QHBoxLayout(); brow.setSpacing(8)
        b_add = QPushButton("Adicionar arquivo…"); b_add.setObjectName("secondary")
        b_add.setIcon(QIcon(icone_pix("image", MUTED, 15))); b_add.clicked.connect(self._add_arquivo)
        b_paste = QPushButton("Colar (Ctrl+V)"); b_paste.setObjectName("secondary")
        b_paste.clicked.connect(self._colar)
        brow.addWidget(b_add); brow.addWidget(b_paste); brow.addStretch(1)
        lay.addLayout(brow)
        self.grid_scroll = QScrollArea(); self.grid_scroll.setObjectName("uiFlat")
        self.grid_scroll.setWidgetResizable(True); self.grid_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.grid_scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self.grid_scroll.viewport().setStyleSheet("background:transparent;")   # sem bloco escuro atrás dos cards
        self._grid_host = QWidget(); self._grid_host.setStyleSheet("background:transparent;")
        self.grid_scroll.setWidget(self._grid_host)
        self._grid = QGridLayout(self._grid_host); self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(10); self._grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self.grid_scroll, 1)
        self.vazio = QLabel("Nenhuma imagem ainda."); self.vazio.setObjectName("uiAjuda")
        lay.addWidget(self.vazio)
        row = QHBoxLayout(); row.addStretch(1)
        b_ok = QPushButton("Concluir"); b_ok.setObjectName("btnPrimary"); b_ok.clicked.connect(self.accept)
        row.addWidget(b_ok); lay.addLayout(row)
        self._render()

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.StandardKey.Paste):
            self._colar(); return
        super().keyPressEvent(e)

    def _colar(self):
        img = QGuiApplication.clipboard().image()
        if img is None or img.isNull():
            QMessageBox.information(self, "Colar", "Não há imagem na área de transferência "
                                    "(copie uma captura de tela primeiro).")
            return
        n = sum(1 for x in self._imgs if (x.get("nome") or "").startswith("captura"))
        self._add(_png_bytes(img), f"captura_{n + 1}.png", img)

    def _add_arquivo(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Escolher imagens", "",
                                                "Imagens (*.png *.jpg *.jpeg *.gif *.bmp *.webp)")
        for p in paths:
            try:
                with open(p, "rb") as f:
                    data = f.read()
                img = QImage(); img.loadFromData(data)
                import os as _os
                self._add(data, _os.path.basename(p), img)
            except Exception as e:
                QMessageBox.warning(self, "Arquivo", f"Não consegui ler '{p}':\n{e}")

    def _add(self, data, nome, img):
        thumb = QPixmap.fromImage(img).scaled(120, 96, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation) \
            if img is not None and not img.isNull() else QPixmap()
        self._imgs.append({"bytes": data, "nome": nome, "thumb": thumb})
        self._render()

    def _render(self):
        while self._grid.count():
            it = self._grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.vazio.setVisible(not self._imgs)
        COLS = 3
        for i, im in enumerate(self._imgs):
            cell = QFrame(); cell.setObjectName("anxCell"); cell.setFixedWidth(150)
            cell.setStyleSheet("QFrame#anxCell{background:%s;border:1px solid %s;border-radius:10px;}" % (INPUT, BORDER))
            cv = QVBoxLayout(cell); cv.setContentsMargins(8, 8, 8, 8); cv.setSpacing(7)
            th = QLabel(); th.setFixedSize(134, 100); th.setAlignment(Qt.AlignmentFlag.AlignCenter)
            th.setStyleSheet("background:%s;border:1px solid %s;border-radius:7px;" % (BG, BORDER))
            if not im["thumb"].isNull():
                th.setPixmap(im["thumb"])
            else:
                th.setText("sem prévia"); th.setStyleSheet("color:%s;background:%s;border:1px solid %s;"
                                                           "border-radius:7px;" % (MUTED, BG, BORDER))
            cv.addWidget(th, 0, Qt.AlignmentFlag.AlignCenter)
            nm = QLineEdit(im["nome"]); nm.setObjectName("anxName"); nm.setFixedWidth(134)
            nm.setToolTip("Clique para editar o nome do arquivo")
            nm.setStyleSheet("QLineEdit#anxName{background:%s;border:1px solid %s;border-radius:6px;"
                             "padding:4px 7px;color:%s;font-size:11.5px;}"
                             "QLineEdit#anxName:focus{border-color:%s;}" % (BG, BORDER, TEXT, GREEN))
            nm.editingFinished.connect(lambda k=i, w=nm: self._renomear(k, w.text()))
            cv.addWidget(nm, 0, Qt.AlignmentFlag.AlignCenter)
            b_rm = QPushButton("Remover"); b_rm.setObjectName("secondary"); b_rm.setFixedWidth(134)
            b_rm.setIcon(QIcon(icone_pix("trash", MUTED, 14)))
            b_rm.clicked.connect(lambda _c, k=i: self._remover(k))
            cv.addWidget(b_rm, 0, Qt.AlignmentFlag.AlignCenter)
            self._grid.addWidget(cell, i // COLS, i % COLS,
                                 Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._grid.setColumnStretch(COLS, 1)          # coluna-fantasma absorve o espaço (cards não esticam)

    def _renomear(self, k, novo):
        novo = (novo or "").strip()
        if 0 <= k < len(self._imgs) and novo:
            self._imgs[k]["nome"] = novo

    def _remover(self, k):
        if 0 <= k < len(self._imgs):
            self._imgs.pop(k)
        self._render()
