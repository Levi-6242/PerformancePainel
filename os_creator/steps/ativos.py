"""Aba Ativos — o catálogo do Fracttal para consulta (Levi, 05/08; revisão de 18 itens em 06/08).

18.259 ativos em 405 usinas. A tela é de LEITURA: serve para achar o ativo e ver o que já
aconteceu nele. "Criar OS" é um atalho que leva às telas que já existem — e abre um MENU de
destinos, porque mandar direto para um plano fixo criava OS de recomposição sem ninguém escolher.

O catálogo vem do `load_assets_cached()` (o mesmo das outras telas); o filtro é todo local.
A visão Hierarquia usa o `id_parent` que cada ativo já traz — é o drill-down do Fracttal,
reconstruído do próprio catálogo, por usina.
"""
import collections

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QLineEdit,
                             QTableWidget, QTableWidgetItem, QHeaderView, QPushButton,
                             QAbstractItemView, QScrollArea, QTreeWidget, QTreeWidgetItem,
                             QMenu, QStackedWidget, QSizePolicy)

import api
from steps.ui import BG, CARD, INPUT, BORDER, GREEN, GREEN_INK, TEXT, MUTED
from workers import ApiWorker, slot_seguro

COR_STATUS = {"Concluída": "#3fb27f", "Em Processo": "#4a9eff",
              "Em Verificação": "#eb8b57", "Cancelada": "#e05454"}
# (rótulo curto p/ caber, valor EXATO do tipo p/ o filtro) — o rótulo cheio era cortado na tela
TIPOS_CHIP = (("Inversor", "Inversor"), ("Trackers", "Estrutura Trackers"), ("Cabine", "Cabine"),
              ("Estação Met.", "Estação Meteorológica"), ("Skid", "Skid"))
LIMITE_TABELA = 400
# tinta dos ativos com OS criada nos últimos 30 dias (item 11) — sutil de propósito
COR_RECENTE = QColor(166, 226, 46, 34)
# menu do "Criar OS": (rótulo, template do deep link). Os templates são as frases dos planos de
# Performance (api._PERF_PLANOS) — o `aplicar_sugestao` casa por trecho, então a frase inteira
# sempre acerta. SEM template ele caía fixo em Recomposição de String (item 17).
DESTINOS_OS = [
    ("Performance · Coleta e análise de dados", "coleta de dados de geracao"),
    ("Performance · Inspeção geral do inversor", "inspecao geral do inversor"),
    ("Performance · Recomposição de string", "recomposicao de string"),
    ("Performance · Verificação de tracker parado", "verificacao de tracker parado"),
]


def _lbl(t, cor=TEXT, px=13, peso=400, ital=False, esp=None):
    q = QLabel(str(t))
    q.setStyleSheet("color:%s;font-size:%spx;font-weight:%s;background:transparent;border:none;%s%s"
                    % (cor, px, peso, "font-style:italic;" if ital else "",
                       "letter-spacing:%spx;" % esp if esp else ""))
    return q


def _norm(s):
    return api._norm_txt(s)


def _usina_exibe(usina, cliente):
    """'2C - Araputanga 1 - MT' com cliente '2C' → 'Araputanga 1 - MT' (item 7). O nome do cliente
    na frente só repetia a coluna/linha ao lado."""
    u, c = str(usina or "").strip(), str(cliente or "").strip()
    if c and _norm(u).startswith(_norm(c) + " - "):
        return u[len(c) + 3:].strip() or u
    return u


class _Painel(QFrame):
    def __init__(self, larg=None):
        super().__init__()
        self.setStyleSheet("QFrame{background:%s;border:1px solid %s;border-radius:14px;}"
                           % (CARD, BORDER))
        if larg:
            self.setFixedWidth(larg)
        self.v = QVBoxLayout(self); self.v.setContentsMargins(16, 15, 16, 15); self.v.setSpacing(11)


# scroll transparente (item 14): o QWidget interno do QScrollArea pinta a cor de janela por
# padrão — era o "quadradão seco" dentro do painel. O seletor filho cobre o viewport E o env.
_QSS_SCROLL = ("QScrollArea{background:transparent;border:none;}"
               "QScrollArea > QWidget > QWidget{background:transparent;}")


class _Chip(QPushButton):
    def __init__(self, texto, ao_clicar):
        super().__init__(texto)
        self.setCheckable(True); self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(lambda: ao_clicar(texto))
        self.setStyleSheet(
            "QPushButton{color:%s;background:transparent;border:1px solid %s;border-radius:999px;"
            "padding:5px 13px;font-size:11.5px;font-weight:700;}"
            "QPushButton:checked{color:%s;background:%s;border-color:%s;}"
            % (MUTED, BORDER, GREEN_INK, GREEN, GREEN))


class _LinhaUsina(QLabel):
    """Item clicável da árvore (cliente ou usina)."""
    def __init__(self, texto, sufixo, nivel, ao_clicar, chave):
        super().__init__()
        self._cb, self._chave = ao_clicar, chave
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.nivel, self.texto, self.sufixo = nivel, texto, sufixo
        self.pintar(False)

    def pintar(self, sel):
        cor = GREEN if sel else (TEXT if self.nivel == 0 else MUTED)
        peso = 700 if (sel or self.nivel == 0) else 400
        pad = 18 if self.nivel else 0
        suf = "<span style='color:%s;font-weight:400'>  %s</span>" % (MUTED, self.sufixo) \
            if self.sufixo else ""
        self.setText(self.texto + suf)
        self.setStyleSheet("QLabel{color:%s;font-size:%spx;font-weight:%s;background:transparent;"
                           "border:none;padding:4px 0 4px %dpx;}"
                           % (cor, 12.5 if self.nivel else 13, peso, pad))

    def mousePressEvent(self, e):
        if self._cb:
            self._cb(self._chave)


class AtivosTab(QWidget):
    """Catálogo: árvore cliente→usina · lista/hierarquia · painel do ativo."""
    _selfnav = True          # o wrapper do app NÃO põe a barra de Voltar — o daqui é o único (item 6)

    def __init__(self, on_voltar=None, ao_criar_os=None, ao_abrir_chamado=None):
        super().__init__()
        self._on_voltar = on_voltar
        self._ao_criar, self._ao_chamado = ao_criar_os, ao_abrir_chamado
        self._todos, self._filtrados, self._sel = [], [], None
        self._cliente, self._usina, self._tipo = "", "", ""
        self._recentes = set()           # codes com OS nos últimos 30 dias (item 11)
        self._por_id = {}                # id → asset (hierarquia)
        self._w = self._wos = self._wrec = None
        self._carregado = False
        self._visao = "lista"
        self._monta()

    # ── layout ────────────────────────────────────────────────────────────────
    def _monta(self):
        raiz = QVBoxLayout(self); raiz.setContentsMargins(26, 16, 26, 22); raiz.setSpacing(14)

        # cabeçalho em UMA linha (itens 6 e 13): Voltar + título juntos, busca à direita.
        cab = QHBoxLayout(); cab.setSpacing(16)
        if self._on_voltar:
            b = QPushButton("← Voltar"); b.setFixedHeight(36)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet("QPushButton{background:transparent;color:%s;border:1px solid %s;"
                            "border-radius:10px;padding:0 16px;font-size:13px;font-weight:600;}"
                            "QPushButton:hover{border-color:%s;}" % (TEXT, BORDER, GREEN))
            b.clicked.connect(self._on_voltar)
            cab.addWidget(b)
        cx = QVBoxLayout(); cx.setSpacing(2)
        cx.addWidget(_lbl("Ativos", TEXT, 20, 800))
        self.sub = _lbl("carregando o catálogo…", MUTED, 12.5)
        # `Minimum` na horizontal: o subtítulo fica do tamanho do texto e NÃO cresce além dele.
        # Com `Ignored` ele era espremido a nada ("18.456 ativ…"); com o padrão, o texto longo
        # empurrava o botão "Atualizar" para fora da janela. Encurtar o texto foi metade do
        # conserto — o título ao lado já diz "Ativos", não precisa repetir "Catálogo do Fracttal".
        self.sub.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        cx.addWidget(self.sub)
        cab.addLayout(cx); cab.addStretch(1)
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("código, nome, usina…   [Ctrl+F]")
        self.busca.setFixedSize(324, 38)         # mesma largura do painel da direita (item 12)
        self.busca.setStyleSheet("QLineEdit{background:%s;border:1px solid %s;border-radius:10px;"
                                 "padding:0 13px;color:%s;font-size:13px;}" % (INPUT, BORDER, TEXT))
        self._t = QTimer(self); self._t.setSingleShot(True); self._t.setInterval(220)
        self._t.timeout.connect(self._aplica)
        self.busca.textChanged.connect(lambda *_: self._t.start())
        # ATUALIZAR CATÁLOGO (Levi, 07/08). O cache dura 24 h e recarrega sozinho depois disso —
        # mas quem acabou de cadastrar um ativo no Fracttal precisa dele AGORA, e sem este botão a
        # única saída era apagar o assets_cache.json à mão. Ativo fora do catálogo nem aparece na
        # cascata, então "esperar 24 h" significa não conseguir abrir OS nele.
        self.b_reload = QPushButton("Atualizar")
        self.b_reload.setFixedHeight(38)
        self.b_reload.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_reload.setToolTip("Busca o catálogo de ativos no Fracttal agora, ignorando o cache "
                                 "de 24 h. Use quando um ativo novo ainda não aparece.")
        self.b_reload.setStyleSheet("QPushButton{background:transparent;color:%s;border:1px solid %s;"
                                    "border-radius:10px;padding:0 15px;font-size:13px;font-weight:600;}"
                                    "QPushButton:hover{border-color:%s;}"
                                    "QPushButton:disabled{color:%s;border-color:%s;}"
                                    % (TEXT, BORDER, GREEN, MUTED, BORDER))
        self.b_reload.clicked.connect(self._atualizar_catalogo)
        # ANTES da busca: a busca é a âncora da direita (largura casada com o painel do ativo,
        # pedido do Levi) e não pode sair do lugar. O botão fica à esquerda dela.
        cab.addWidget(self.b_reload)
        cab.addWidget(self.busca)
        raiz.addLayout(cab)

        corpo = QHBoxLayout(); corpo.setSpacing(16)

        # ── esquerda: árvore cliente → usina, com busca própria (item 10) ──
        self.p_arv = _Painel(272)
        self.p_arv.v.addWidget(_lbl("CLIENTE / USINA", MUTED, 10.5, 800, esp=1.1))
        self.busca_usina = QLineEdit(); self.busca_usina.setPlaceholderText("buscar usina…")
        self.busca_usina.setFixedHeight(32)
        self.busca_usina.setStyleSheet("QLineEdit{background:%s;border:1px solid %s;"
                                       "border-radius:9px;padding:0 10px;color:%s;font-size:12px;}"
                                       % (INPUT, BORDER, TEXT))
        self._tu = QTimer(self); self._tu.setSingleShot(True); self._tu.setInterval(200)
        self._tu.timeout.connect(self._arvore)
        self.busca_usina.textChanged.connect(lambda *_: self._tu.start())
        self.p_arv.v.addWidget(self.busca_usina)
        self.arv_box = QVBoxLayout(); self.arv_box.setSpacing(0)
        env = QWidget(); env.setLayout(self.arv_box)
        env.setStyleSheet("background:transparent;")
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setWidget(env)
        sc.setStyleSheet(_QSS_SCROLL)
        self.p_arv.v.addWidget(sc, 1)
        corpo.addWidget(self.p_arv)

        # ── centro: visão + chips + (tabela | hierarquia) ──
        self.p_tab = _Painel()
        topo = QHBoxLayout(); topo.setSpacing(7)
        topo.addWidget(_lbl("VISÃO", MUTED, 10.5, 800, esp=1.1))
        self.ch_lista = _Chip("Lista", lambda *_: self._muda_visao("lista"))
        self.ch_hier = _Chip("Hierarquia", lambda *_: self._muda_visao("hier"))
        self.ch_lista.setChecked(True)
        topo.addWidget(self.ch_lista); topo.addWidget(self.ch_hier)
        topo.addSpacing(14)
        topo.addWidget(_lbl("TIPO", MUTED, 10.5, 800, esp=1.1))
        self._chips = []
        for rotulo, valor in (("Todos", ""),) + TIPOS_CHIP:
            c = _Chip(rotulo, lambda _r, v=valor: self._chip(v))
            self._chips.append(c); topo.addWidget(c)
        self._chips[0].setChecked(True)
        topo.addStretch(1)
        self.p_tab.v.addLayout(topo)

        self.tab = QTableWidget(0, 4)
        self.tab.setHorizontalHeaderLabels(["Código", "Ativo", "Tipo", "Usina"])
        self.tab.verticalHeader().setVisible(False)
        self.tab.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tab.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tab.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tab.setShowGrid(False)
        # `outline:0` + `item:focus` (item 2): o retângulo de foco da célula clicada desenhava uma
        # borda branca POR DENTRO do item e espremia o texto.
        self.tab.setStyleSheet(
            "QTableWidget{background:transparent;border:none;color:%s;font-size:12.5px;outline:0;}"
            "QHeaderView::section{background:transparent;color:%s;border:none;"
            "border-bottom:1px solid %s;padding:7px 4px;font-size:10.5px;font-weight:800;}"
            "QTableWidget::item{padding:9px 4px;border-bottom:1px solid rgba(42,53,80,0.45);}"
            "QTableWidget::item:focus{border:none;outline:none;}"
            "QTableWidget::item:selected{background:rgba(166,226,46,0.13);color:%s;}"
            % (TEXT, MUTED, BORDER, TEXT))
        self.tab.itemSelectionChanged.connect(self._sel_tabela)

        # hierarquia (item 15): drill-down id_parent → filhos, por usina
        self.arv_ativos = QTreeWidget()
        self.arv_ativos.setColumnCount(3)
        self.arv_ativos.setHeaderLabels(["Ativo", "Código", "Tipo"])
        self.arv_ativos.setStyleSheet(
            "QTreeWidget{background:transparent;border:none;color:%s;font-size:12.5px;outline:0;}"
            "QHeaderView::section{background:transparent;color:%s;border:none;"
            "border-bottom:1px solid %s;padding:7px 4px;font-size:10.5px;font-weight:800;}"
            "QTreeWidget::item{padding:5px 4px;}"
            "QTreeWidget::item:focus{border:none;outline:none;}"
            "QTreeWidget::item:selected{background:rgba(166,226,46,0.13);color:%s;}"
            % (TEXT, MUTED, BORDER, TEXT))
        self.arv_ativos.itemSelectionChanged.connect(self._sel_hier)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.tab)          # 0 = lista
        self.stack.addWidget(self.arv_ativos)   # 1 = hierarquia
        self.p_tab.v.addWidget(self.stack, 1)
        self.rodape = _lbl("—", MUTED, 11.5)
        self.p_tab.v.addWidget(self.rodape)
        corpo.addWidget(self.p_tab, 1)

        # ── direita: ativo selecionado ──
        self.p_det = _Painel(324)
        self._monta_detalhe()
        corpo.addWidget(self.p_det)

        raiz.addLayout(corpo, 1)

    def _monta_detalhe(self):
        self.p_det.v.addWidget(_lbl("ATIVO SELECIONADO", MUTED, 10.5, 800, esp=1.1))
        # nome/código centralizados (item 3) e selecionáveis p/ copiar (item 8)
        self.d_nome = _lbl("—", TEXT, 16, 800); self.d_nome.setWordWrap(True)
        self.d_nome.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.d_code = _lbl("", GREEN, 12.5, 700)
        self.d_code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for l in (self.d_nome, self.d_code):
            l.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.p_det.v.addWidget(self.d_nome); self.p_det.v.addWidget(self.d_code)
        self.d_campos = {}
        for k in ("Tipo", "Marca", "Usina", "Cliente"):      # Marca = item 9
            l = QHBoxLayout()
            l.addWidget(_lbl(k, MUTED, 12)); l.addStretch(1)
            val = _lbl("—", TEXT, 12, 600)
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.d_campos[k] = val; l.addWidget(val)
            self.p_det.v.addLayout(l)
        s = QFrame(); s.setFixedHeight(1); s.setStyleSheet("background:%s;border:none;" % BORDER)
        self.p_det.v.addWidget(s)
        self.p_det.v.addWidget(_lbl("ÚLTIMAS 4 OS", MUTED, 10.5, 800, esp=1.1))     # 3→4 (Levi, 06/08)
        self.os_box = QVBoxLayout(); self.os_box.setSpacing(7)
        self.p_det.v.addLayout(self.os_box)
        self.os_hint = _lbl("selecione um ativo", MUTED, 11.5, 400, True)
        self.p_det.v.addWidget(self.os_hint)
        self.p_det.v.addStretch(1)
        # SÓ o Criar OS (item 16) — e ele abre um MENU de destinos (item 17)
        self.b_os = QPushButton("Criar OS neste ativo  ▾"); self.b_os.setFixedHeight(38)
        self.b_os.setEnabled(False)
        self.b_os.setStyleSheet("QPushButton{background:%s;color:%s;border:none;border-radius:10px;"
                                "font-size:13px;font-weight:800;}"
                                "QPushButton:disabled{background:%s;color:%s;}"
                                % (GREEN, GREEN_INK, INPUT, MUTED))
        self.b_os.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_os.clicked.connect(self._menu_criar)
        self.p_det.v.addWidget(self.b_os)

    # ── dados ─────────────────────────────────────────────────────────────────
    def carregar_inicial(self):
        if self._carregado:
            return
        self._carregado = True
        self._w = ApiWorker(api.load_assets_cached)
        self._w.ok.connect(self._chegou); self._w.erro.connect(self._falhou)
        self._w.start()

    @slot_seguro
    def _falhou(self, m):
        self._w = None
        self.sub.setText("não consegui carregar o catálogo: %s" % str(m)[:110])

    @slot_seguro
    def _chegou(self, ats):
        self._w = None
        self._todos = [a for a in (ats or []) if isinstance(a, dict) and a.get("code")]
        self._por_id = {a.get("id"): a for a in self._todos if a.get("id")}
        self.sub.setText("%s ativos  ·  %d usinas%s"
                         % (f"{len(self._todos):,}".replace(",", "."),
                            len({a.get('usina') for a in self._todos}), self._idade_txt()))
        self._arvore()
        self._aplica()
        # OS dos últimos 30 dias, em 2º plano (item 11) — a tela já está usável sem isso
        self._wrec = ApiWorker(api.codigos_os_recentes, 30)
        self._wrec.ok.connect(self._rec_chegou)
        self._wrec.erro.connect(lambda *_: None)
        self._wrec.start()

    def _idade_txt(self):
        """'· lista de 07/08 14:30' — e avisa quando está velha. Dizer só o total esconde a idade:
        18.259 parece número de agora quando é de dez dias atrás (o caso do Levi em 07/08)."""
        try:
            info = api.assets_cache_info()
        except Exception:
            return ""
        if not info.get("ts"):
            return ""
        import datetime as _dt
        quando = _dt.datetime.fromtimestamp(info["ts"]).strftime("%d/%m %H:%M")
        return "  ·  lista de %s%s" % (quando, "  (desatualizada)" if info.get("expirado") else "")

    @slot_seguro
    def _atualizar_catalogo(self):
        """Recarrega do Fracttal ignorando o cache. Em worker: são ~100 páginas de 200 ativos e
        travaria a interface."""
        self.b_reload.setEnabled(False); self.b_reload.setText("atualizando…")
        self.sub.setText("buscando o catálogo no Fracttal…")
        self._w = ApiWorker(api.load_assets_cached, True)
        self._w.ok.connect(self._recarregou); self._w.erro.connect(self._recarga_falhou)
        self._w.start()

    @slot_seguro
    def _recarregou(self, ats):
        antes = len(self._todos)
        self.b_reload.setEnabled(True); self.b_reload.setText("Atualizar")
        self._chegou(ats)                      # repopula tudo (árvore, tabela, contadores)
        d = len(self._todos) - antes
        if d:
            self.rodape.setText("catálogo atualizado — %+d ativo(s) em relação à lista anterior" % d)

    @slot_seguro
    def _recarga_falhou(self, m):
        self._w = None
        self.b_reload.setEnabled(True); self.b_reload.setText("Atualizar")
        self.sub.setText("não consegui atualizar: %s" % str(m)[:90])

    @slot_seguro
    def _rec_chegou(self, codes):
        self._wrec = None
        self._recentes = set(codes or [])
        self._aplica()                       # repinta com a tinta

    # ── árvore cliente/usina ──────────────────────────────────────────────────
    def _arvore(self):
        # setParent(None) + descartar o espaçador — sem isso a reconstrução sobrepunha linhas
        while self.arv_box.count():
            it = self.arv_box.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None); w.deleteLater()
        self._linhas = []
        termo = _norm(self.busca_usina.text())
        usinas_por_cli = collections.defaultdict(set)
        for a in self._todos:
            usinas_por_cli[a.get("cliente") or "—"].add(a.get("usina") or "—")
        n_ativos = collections.Counter(a.get("cliente") or "—" for a in self._todos)
        for cli in sorted(usinas_por_cli, key=lambda c: -n_ativos[c]):
            usinas = sorted(usinas_por_cli[cli])
            if termo:
                usinas = [u for u in usinas if termo in _norm(u) or termo in _norm(cli)]
                if not usinas:
                    continue
            # contagem de USINAS, não de OS/ativos (item 4)
            l = _LinhaUsina(cli, "(%d usinas)" % len(usinas_por_cli[cli]), 0,
                            self._clicou_arvore, ("cli", cli))
            self.arv_box.addWidget(l); self._linhas.append(l)
            # com busca, a árvore abre sozinha nos que casaram; sem busca, abre só o selecionado
            if termo or cli == self._cliente:
                for u in usinas:
                    lu = _LinhaUsina(_usina_exibe(u, cli)[:26], "", 1,
                                     self._clicou_arvore, ("usi", u))
                    self.arv_box.addWidget(lu); self._linhas.append(lu)
        self.arv_box.addStretch(1)
        for l in self._linhas:
            l.pintar(l._chave == ("cli", self._cliente) and not self._usina
                     or l._chave == ("usi", self._usina))

    def _clicou_arvore(self, chave):
        tipo, valor = chave
        if tipo == "cli":
            self._cliente = "" if self._cliente == valor else valor
            self._usina = ""
        else:
            self._usina = "" if self._usina == valor else valor
            if self._usina:                 # escolher usina define o cliente dela
                cli = next((a.get("cliente") for a in self._todos
                            if (a.get("usina") or "—") == self._usina), self._cliente)
                self._cliente = cli or self._cliente
        self._arvore(); self._aplica()

    def _chip(self, valor):
        self._tipo = valor
        rotulos = {"": "Todos", **{v: r for r, v in TIPOS_CHIP}}
        for c in self._chips:
            c.setChecked(c.text() == rotulos.get(valor, valor))
        self._aplica()

    # ── lista / hierarquia ────────────────────────────────────────────────────
    def _muda_visao(self, v):
        self._visao = v
        self.ch_lista.setChecked(v == "lista")
        self.ch_hier.setChecked(v == "hier")
        self.stack.setCurrentIndex(0 if v == "lista" else 1)
        self._aplica()

    def _aplica(self):
        termo = _norm(self.busca.text())
        out = []
        for a in self._todos:
            if self._cliente and (a.get("cliente") or "—") != self._cliente:
                continue
            if self._usina and (a.get("usina") or "—") != self._usina:
                continue
            if self._tipo and a.get("tipo") != self._tipo:
                continue
            if termo and termo not in _norm("%s %s %s %s" % (a.get("code"), a.get("description"),
                                                             a.get("usina"), a.get("tipo"))):
                continue
            out.append(a)
        self._filtrados = out
        if self._visao == "hier":
            self._pinta_hier()
            return
        self._pinta(out[:LIMITE_TABELA])
        extra = len(out) - LIMITE_TABELA
        rec = " · linha verde = OS nos últimos 30 dias" if self._recentes else ""
        self.rodape.setText("%s ativos" % f"{len(out):,}".replace(",", ".")
                            + (" · mostrando os %d primeiros, refine a busca" % LIMITE_TABELA
                               if extra > 0 else "") + rec)

    def _pinta(self, itens):
        self.tab.setRowCount(0)
        self.tab.setRowCount(len(itens))
        tinta = QBrush(COR_RECENTE)
        for r, a in enumerate(itens):
            nome = (str(a.get("description") or "").split("{")[0]).strip()
            recente = a.get("code") in self._recentes
            for c, v in enumerate((a.get("code"), nome, a.get("tipo"),
                                   _usina_exibe(a.get("usina"), a.get("cliente")))):
                it = QTableWidgetItem(str(v or ""))
                if recente:
                    it.setBackground(tinta)
                self.tab.setItem(r, c, it)
        h = self.tab.horizontalHeader()
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i in (0, 2, 3):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

    def _pinta_hier(self):
        """Drill-down real: filhos pendurados no `id_parent`, dentro da usina escolhida. Sem usina
        a árvore seria o catálogo inteiro (18 mil nós) — então pede para escolher uma."""
        self.arv_ativos.clear()
        if not self._usina:
            self.rodape.setText("escolha uma USINA na árvore da esquerda para ver a hierarquia")
            return
        escopo = [a for a in self._todos if (a.get("usina") or "—") == self._usina]
        ids = {a.get("id") for a in escopo}
        filhos = collections.defaultdict(list)
        raizes = []
        for a in escopo:
            if a.get("id_parent") in ids:
                filhos[a["id_parent"]].append(a)
            else:
                raizes.append(a)

        def _no(a):
            it = QTreeWidgetItem([(str(a.get("description") or "").split("{")[0]).strip(),
                                  a.get("code") or "", a.get("tipo") or ""])
            it.setData(0, Qt.ItemDataRole.UserRole, a.get("id"))
            if a.get("code") in self._recentes:
                for c in range(3):
                    it.setBackground(c, QBrush(COR_RECENTE))
            for f in sorted(filhos.get(a.get("id"), []), key=lambda x: str(x.get("code"))):
                it.addChild(_no(f))
            return it

        # usina primeiro, depois o resto por código
        raizes.sort(key=lambda a: (a.get("tipo") != "Usina", str(a.get("code"))))
        for a in raizes:
            self.arv_ativos.addTopLevelItem(_no(a))
        self.arv_ativos.expandAll()
        self.arv_ativos.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in (1, 2):
            self.arv_ativos.header().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.rodape.setText("%d ativos na hierarquia de %s"
                            % (len(escopo), _usina_exibe(self._usina, self._cliente)))

    # ── seleção (as duas visões caem aqui) ────────────────────────────────────
    @slot_seguro
    def _sel_tabela(self):
        r = self.tab.currentRow()
        if 0 <= r < len(self._filtrados):
            self._selecionar(self._filtrados[r])

    @slot_seguro
    def _sel_hier(self):
        it = self.arv_ativos.currentItem()
        if it is None:
            return
        a = self._por_id.get(it.data(0, Qt.ItemDataRole.UserRole))
        if a:
            self._selecionar(a)

    def _selecionar(self, a):
        self._sel = a
        self.d_nome.setText((str(a.get("description") or "").split("{")[0]).strip() or "—")
        self.d_code.setText(a.get("code") or "")
        # marca deduzida do nome / dos irmãos — mesma regra do chamado (item 9)
        marca = ""
        try:
            import chamado_insp_spec as ci
            marca = ci.descobrir_marca(a, self._todos) or ""
        except Exception:
            marca = ""
        for k, v in (("Tipo", a.get("tipo")), ("Marca", marca or "—"),
                     ("Usina", _usina_exibe(a.get("usina"), a.get("cliente"))),
                     ("Cliente", a.get("cliente"))):
            self.d_campos[k].setText(str(v or "—")[:26])
        self.b_os.setEnabled(True)
        self._carregar_os(a)

    def _carregar_os(self, a):
        while self.os_box.count():
            it = self.os_box.takeAt(0); w = it.widget()
            if w:
                w.setParent(None); w.deleteLater()
        self.os_hint.setText("buscando as OS…"); self.os_hint.setVisible(True)
        self._wos = ApiWorker(api.ultimas_os_do_ativo, a.get("id"), 4, True)      # 4 (Levi, 06/08)
        self._wos.ok.connect(self._os_chegaram)
        self._wos.erro.connect(lambda *_: self.os_hint.setText("não consegui buscar as OS"))
        self._wos.start()

    @slot_seguro
    def _os_chegaram(self, lista):
        self._wos = None
        if not lista:
            self.os_hint.setText("nenhuma OS neste ativo"); return
        self.os_hint.setVisible(False)
        # da MAIOR para a menor (item 5)
        for d in sorted(lista, key=api._ordem_os, reverse=True)[:4]:
            cs = COR_STATUS.get(d.get("status"), MUTED)
            li = QFrame()
            li.setStyleSheet("QFrame{background:%s;border:1px solid %s;border-radius:9px;}"
                             % (INPUT, BORDER))
            lv = QVBoxLayout(li); lv.setContentsMargins(11, 10, 11, 10); lv.setSpacing(3)
            t = QHBoxLayout()
            t.addWidget(_lbl(d.get("folio") or "—", TEXT, 14, 800)); t.addStretch(1)
            t.addWidget(_lbl((api.fmt_data_br(d.get("event_date")) or "")[:5], MUTED, 11))
            lv.addLayout(t)
            b = QHBoxLayout(); b.setSpacing(6)
            b.addWidget(_lbl((d.get("tipo_tarefa") or "—")[:20], MUTED, 11)); b.addStretch(1)
            b.addWidget(_lbl(d.get("status") or "—", cs, 11, 700))
            lv.addLayout(b)
            self.os_box.addWidget(li)

    # ── Criar OS: menu de destinos (item 17) ──────────────────────────────────
    def _menu_criar(self):
        if not self._sel:
            return
        m = QMenu(self)
        m.setStyleSheet("QMenu{background:%s;color:%s;border:1px solid %s;border-radius:10px;"
                        "padding:6px;}QMenu::item{padding:8px 18px;border-radius:7px;font-size:13px;}"
                        "QMenu::item:selected{background:rgba(166,226,46,0.14);color:%s;}"
                        % (CARD, TEXT, BORDER, TEXT))
        for rotulo, tmpl in DESTINOS_OS:
            m.addAction(rotulo, lambda t=tmpl: self._ir_performance(t))
        # a inspeção de chamado é um destino também — só para quem tem modelo
        try:
            import chamado_insp_spec as ci
            if ci.aceita(self._sel.get("tipo")) and self._ao_chamado:
                m.addSeparator()
                m.addAction("Inspeção de chamado (garantia)",
                            lambda: self._ao_chamado(self._sel))
        except Exception:
            pass
        m.exec(self.b_os.mapToGlobal(self.b_os.rect().topLeft()))

    def _ir_performance(self, template):
        if self._sel and self._ao_criar:
            self._ao_criar(self._sel, template)

    def reiniciar(self):
        """Entrar de novo = buscas limpas. Cliente/usina ficam — voltar à mesma usina é o normal
        de quem está conferindo uma planta."""
        self.busca.clear()
        self.busca_usina.clear()
