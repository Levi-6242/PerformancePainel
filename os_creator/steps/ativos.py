"""Aba Ativos — o catálogo do Fracttal para consulta (Levi, 05/08).

18.259 ativos em 405 usinas. A tela é de LEITURA: serve para achar o ativo e ver o que já
aconteceu nele. Criar OS e abrir chamado são atalhos que levam às telas que já existem — não se
cria nada aqui, para não haver dois caminhos divergindo para a mesma coisa.

O catálogo vem do `load_assets_cached()`, o mesmo que as outras telas usam, então abrir esta aba
não custa uma varredura nova. O filtro é todo local: 18 mil linhas em memória filtram em
milissegundos, e o servidor não tem filtro por tipo mesmo.
"""
import collections

from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QLineEdit,
                             QTableWidget, QTableWidgetItem, QHeaderView, QPushButton,
                             QAbstractItemView, QScrollArea, QSizePolicy)

import api
from steps.ui import BG, CARD, INPUT, BORDER, GREEN, GREEN_INK, TEXT, MUTED, icone_pix
from workers import ApiWorker, slot_seguro

COR_STATUS = {"Concluída": "#3fb27f", "Em Processo": "#4a9eff",
              "Em Verificação": "#eb8b57", "Cancelada": "#e05454"}
# tipos que valem um chip fixo — os que a operação realmente procura
TIPOS_CHIP = ("Inversor", "Estrutura Trackers", "Cabine", "Estação Meteorológica", "Skid")
LIMITE_TABELA = 400          # teto de linhas exibidas; ver `_aplica`


def _lbl(t, cor=TEXT, px=13, peso=400, ital=False, esp=None):
    q = QLabel(str(t))
    q.setStyleSheet("color:%s;font-size:%spx;font-weight:%s;background:transparent;border:none;%s%s"
                    % (cor, px, peso, "font-style:italic;" if ital else "",
                       "letter-spacing:%spx;" % esp if esp else ""))
    return q


def _norm(s):
    return api._norm_txt(s)


class _Painel(QFrame):
    def __init__(self, larg=None):
        super().__init__()
        self.setStyleSheet("QFrame{background:%s;border:1px solid %s;border-radius:14px;}"
                           % (CARD, BORDER))
        if larg:
            self.setFixedWidth(larg)
        self.v = QVBoxLayout(self); self.v.setContentsMargins(16, 15, 16, 15); self.v.setSpacing(11)


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
    def __init__(self, texto, n, nivel, ao_clicar, chave):
        super().__init__()
        self._cb, self._chave = ao_clicar, chave
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.nivel, self.texto, self.n = nivel, texto, n
        self.pintar(False)

    def pintar(self, sel):
        cor = GREEN if sel else (TEXT if self.nivel == 0 else MUTED)
        peso = 700 if (sel or self.nivel == 0) else 400
        pad = 18 if self.nivel else 0
        self.setText("%s<span style='color:%s'>  %d</span>" % (self.texto, MUTED, self.n))
        self.setStyleSheet("QLabel{color:%s;font-size:%spx;font-weight:%s;background:transparent;"
                           "border:none;padding:3px 0 3px %dpx;}" % (cor, 12.5 if self.nivel else 13,
                                                                     peso, pad))

    def mousePressEvent(self, e):
        if self._cb:
            self._cb(self._chave)


class AtivosTab(QWidget):
    """Catálogo: árvore cliente→usina · tabela filtrável · painel do ativo."""

    def __init__(self, on_voltar=None, ao_criar_os=None, ao_abrir_chamado=None):
        super().__init__()
        self._on_voltar = on_voltar
        self._ao_criar, self._ao_chamado = ao_criar_os, ao_abrir_chamado
        self._todos, self._filtrados, self._sel = [], [], None
        self._cliente, self._usina, self._tipo = "", "", ""
        self._w = self._wos = None
        self._carregado = False
        self._monta()

    # ── layout ────────────────────────────────────────────────────────────────
    def _monta(self):
        raiz = QVBoxLayout(self); raiz.setContentsMargins(26, 22, 26, 22); raiz.setSpacing(16)

        cab = QHBoxLayout(); cab.setSpacing(14)
        if self._on_voltar:
            b = QPushButton("Voltar"); b.setObjectName("pGhost"); b.setFixedHeight(34)
            b.clicked.connect(self._on_voltar)
            cab.addWidget(b)
        cx = QVBoxLayout(); cx.setSpacing(3)
        cx.addWidget(_lbl("Ativos", TEXT, 21, 800))
        self.sub = _lbl("carregando o catálogo…", MUTED, 13)
        cx.addWidget(self.sub)
        cab.addLayout(cx); cab.addStretch(1)
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("código, nome, usina…   [Ctrl+F]")
        self.busca.setFixedSize(330, 38)
        self.busca.setStyleSheet("QLineEdit{background:%s;border:1px solid %s;border-radius:10px;"
                                 "padding:0 13px;color:%s;font-size:13px;}" % (INPUT, BORDER, TEXT))
        # debounce: 18 mil linhas refiltram rápido, mas reconstruir a tabela a cada tecla trava
        self._t = QTimer(self); self._t.setSingleShot(True); self._t.setInterval(220)
        self._t.timeout.connect(self._aplica)
        self.busca.textChanged.connect(lambda *_: self._t.start())
        cab.addWidget(self.busca)
        raiz.addLayout(cab)

        corpo = QHBoxLayout(); corpo.setSpacing(16)

        # esquerda — árvore
        self.p_arv = _Painel(272)
        self.p_arv.v.addWidget(_lbl("CLIENTE / USINA", MUTED, 10.5, 800, esp=1.1))
        self.arv_box = QVBoxLayout(); self.arv_box.setSpacing(0)
        env = QWidget(); env.setLayout(self.arv_box)
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setWidget(env)
        sc.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self.p_arv.v.addWidget(sc, 1)
        corpo.addWidget(self.p_arv)

        # centro — chips + tabela
        self.p_tab = _Painel()
        chips = QHBoxLayout(); chips.setSpacing(7)
        chips.addWidget(_lbl("TIPO", MUTED, 10.5, 800, esp=1.1))
        self._chips = []
        for nome in ("Todos",) + TIPOS_CHIP:
            c = _Chip(nome, self._chip)
            self._chips.append(c); chips.addWidget(c)
        self._chips[0].setChecked(True)
        chips.addStretch(1)
        self.p_tab.v.addLayout(chips)

        self.tab = QTableWidget(0, 4)
        self.tab.setHorizontalHeaderLabels(["Código", "Ativo", "Tipo", "Usina"])
        self.tab.verticalHeader().setVisible(False)
        self.tab.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tab.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tab.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tab.setShowGrid(False)
        self.tab.setStyleSheet(
            "QTableWidget{background:transparent;border:none;color:%s;font-size:12.5px;}"
            "QHeaderView::section{background:transparent;color:%s;border:none;"
            "border-bottom:1px solid %s;padding:7px 4px;font-size:10.5px;font-weight:800;}"
            "QTableWidget::item{padding:9px 4px;border-bottom:1px solid rgba(42,53,80,0.45);}"
            "QTableWidget::item:selected{background:rgba(166,226,46,0.13);color:%s;}"
            % (TEXT, MUTED, BORDER, TEXT))
        self.tab.itemSelectionChanged.connect(self._sel_mudou)
        self.p_tab.v.addWidget(self.tab, 1)
        self.rodape = _lbl("—", MUTED, 11.5)
        self.p_tab.v.addWidget(self.rodape)
        corpo.addWidget(self.p_tab, 1)

        # direita — ativo selecionado
        self.p_det = _Painel(324)
        self._monta_detalhe()
        corpo.addWidget(self.p_det)

        raiz.addLayout(corpo, 1)

    def _monta_detalhe(self):
        self.p_det.v.addWidget(_lbl("ATIVO SELECIONADO", MUTED, 10.5, 800, esp=1.1))
        self.d_nome = _lbl("—", TEXT, 16, 800); self.d_nome.setWordWrap(True)
        self.d_code = _lbl("", GREEN, 12.5, 700)
        self.p_det.v.addWidget(self.d_nome); self.p_det.v.addWidget(self.d_code)
        self.d_campos = {}
        for k in ("Tipo", "Usina", "Cliente"):
            l = QHBoxLayout()
            l.addWidget(_lbl(k, MUTED, 12)); l.addStretch(1)
            val = _lbl("—", TEXT, 12, 600)
            self.d_campos[k] = val; l.addWidget(val)
            self.p_det.v.addLayout(l)
        s = QFrame(); s.setFixedHeight(1); s.setStyleSheet("background:%s;border:none;" % BORDER)
        self.p_det.v.addWidget(s)
        self.p_det.v.addWidget(_lbl("ÚLTIMAS OS", MUTED, 10.5, 800, esp=1.1))
        self.os_box = QVBoxLayout(); self.os_box.setSpacing(7)
        self.p_det.v.addLayout(self.os_box)
        self.os_hint = _lbl("selecione um ativo", MUTED, 11.5, 400, True)
        self.p_det.v.addWidget(self.os_hint)
        self.p_det.v.addStretch(1)
        self.b_os = QPushButton("Criar OS neste ativo"); self.b_os.setFixedHeight(38)
        self.b_os.setEnabled(False)
        self.b_os.setStyleSheet("QPushButton{background:%s;color:%s;border:none;border-radius:10px;"
                                "font-size:13px;font-weight:800;}"
                                "QPushButton:disabled{background:%s;color:%s;}"
                                % (GREEN, GREEN_INK, INPUT, MUTED))
        self.b_os.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_os.clicked.connect(self._criar_os)
        self.b_ch = QPushButton("Abrir chamado de garantia"); self.b_ch.setFixedHeight(38)
        # estilo explícito: esta aba não está dentro do QSS_FORM, então `pGhost` não pega e os
        # dois botões saíam verdes — dois primários lado a lado não dizem qual é o principal
        self.b_ch.setStyleSheet("QPushButton{background:transparent;color:%s;border:1px solid %s;"
                                "border-radius:10px;font-size:13px;font-weight:700;}"
                                "QPushButton:hover{border-color:%s;}" % (TEXT, BORDER, GREEN))
        self.b_ch.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_ch.clicked.connect(self._abrir_chamado)
        self.p_det.v.addWidget(self.b_os); self.p_det.v.addWidget(self.b_ch)

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
        self.sub.setText("Catálogo do Fracttal — %s ativos em %d usinas"
                         % (f"{len(self._todos):,}".replace(",", "."),
                            len({a.get('usina') for a in self._todos})))
        self._arvore()
        self._aplica()

    def _arvore(self):
        # `deleteLater` sozinho NÃO basta: o widget sai do layout no `takeAt` mas continua filho e
        # segue desenhando na última posição até o event loop apagá-lo — a árvore reconstruída
        # ficava com cliente e usina sobrepostos no mesmo pixel. `setParent(None)` tira da tela na
        # hora. E o `takeAt` também devolve ESPAÇADOR (o addStretch), que não tem widget: sem
        # descartá-lo, cada reconstrução empilhava mais um.
        while self.arv_box.count():
            it = self.arv_box.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None); w.deleteLater()
        self._linhas = []
        por_cli = collections.Counter(a.get("cliente") or "—" for a in self._todos)
        for cli, n in sorted(por_cli.items(), key=lambda x: -x[1]):
            l = _LinhaUsina(cli, n, 0, self._clicou_arvore, ("cli", cli))
            self.arv_box.addWidget(l); self._linhas.append(l)
            if cli == self._cliente:
                us = collections.Counter(a.get("usina") or "—" for a in self._todos
                                         if (a.get("cliente") or "—") == cli)
                for u, m in sorted(us.items()):
                    lu = _LinhaUsina(u[:24], m, 1, self._clicou_arvore, ("usi", u))
                    self.arv_box.addWidget(lu); self._linhas.append(lu)
        self.arv_box.addStretch(1)
        for l in self._linhas:
            l.pintar(l._chave == ("cli", self._cliente) and not self._usina
                     or l._chave == ("usi", self._usina))

    def _clicou_arvore(self, chave):
        tipo, valor = chave
        if tipo == "cli":
            # clicar de novo no cliente aberto FECHA — senão a árvore vira uma via de mão única
            self._cliente = "" if self._cliente == valor else valor
            self._usina = ""
        else:
            self._usina = "" if self._usina == valor else valor
        self._arvore(); self._aplica()

    def _chip(self, nome):
        self._tipo = "" if nome == "Todos" else nome
        for c in self._chips:
            c.setChecked(c.text() == nome)
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
        self._pinta(out[:LIMITE_TABELA])
        # TETO EXPLÍCITO: cortar em silêncio faria a tela parecer completa quando não está.
        extra = len(out) - LIMITE_TABELA
        self.rodape.setText("%s ativos" % f"{len(out):,}".replace(",", ".")
                            + (" · mostrando os %d primeiros, refine a busca" % LIMITE_TABELA
                               if extra > 0 else ""))

    def _pinta(self, itens):
        self.tab.setRowCount(0)
        self.tab.setRowCount(len(itens))
        for r, a in enumerate(itens):
            nome = (str(a.get("description") or "").split("{")[0]).strip()
            for c, v in enumerate((a.get("code"), nome, a.get("tipo"), a.get("usina"))):
                self.tab.setItem(r, c, QTableWidgetItem(str(v or "")))
        h = self.tab.horizontalHeader()
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i in (0, 2, 3):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

    # ── seleção ───────────────────────────────────────────────────────────────
    @slot_seguro
    def _sel_mudou(self):
        r = self.tab.currentRow()
        if r < 0 or r >= len(self._filtrados):
            return
        a = self._filtrados[r]
        self._sel = a
        self.d_nome.setText((str(a.get("description") or "").split("{")[0]).strip() or "—")
        self.d_code.setText(a.get("code") or "")
        for k, v in (("Tipo", a.get("tipo")), ("Usina", a.get("usina")), ("Cliente", a.get("cliente"))):
            self.d_campos[k].setText(str(v or "—")[:26])
        self.b_os.setEnabled(True)
        # o chamado só existe para os tipos com modelo de subtarefa — botão some em vez de ficar
        # desabilitado: cinza sem explicação vira pergunta, ausência não.
        try:
            import chamado_insp_spec as ci
            pode = bool(ci.aceita(a.get("tipo")))
        except Exception:
            pode = False
        self.b_ch.setVisible(pode)
        self._carregar_os(a)

    def _carregar_os(self, a):
        while self.os_box.count():
            it = self.os_box.takeAt(0); w = it.widget()
            if w:
                w.deleteLater()
        self.os_hint.setText("buscando as OS…"); self.os_hint.setVisible(True)
        self._wos = ApiWorker(api.ultimas_os_do_ativo, a.get("id"), 5, True)
        self._wos.ok.connect(self._os_chegaram)
        self._wos.erro.connect(lambda *_: self.os_hint.setText("não consegui buscar as OS"))
        self._wos.start()

    @slot_seguro
    def _os_chegaram(self, lista):
        self._wos = None
        if not lista:
            self.os_hint.setText("nenhuma OS neste ativo"); return
        self.os_hint.setVisible(False)
        # ordena pelo NÚMERO da OS, como o card de fluxo (Levi, 05/08)
        for d in sorted(lista, key=api._ordem_os, reverse=True):
            cs = COR_STATUS.get(d.get("status"), MUTED)
            li = QFrame()
            li.setStyleSheet("QFrame{background:%s;border:1px solid %s;border-radius:9px;}"
                             % (INPUT, BORDER))
            lv = QVBoxLayout(li); lv.setContentsMargins(11, 8, 11, 8); lv.setSpacing(2)
            t = QHBoxLayout()
            t.addWidget(_lbl(d.get("folio") or "—", TEXT, 14, 800)); t.addStretch(1)
            t.addWidget(_lbl((api.fmt_data_br(d.get("event_date")) or "")[:5], MUTED, 11))
            lv.addLayout(t)
            b = QHBoxLayout(); b.setSpacing(6)
            b.addWidget(_lbl((d.get("tipo_tarefa") or "—")[:20], MUTED, 11)); b.addStretch(1)
            b.addWidget(_lbl(d.get("status") or "—", cs, 11, 700))
            lv.addLayout(b)
            self.os_box.addWidget(li)

    # ── ações (levam às telas que já existem) ─────────────────────────────────
    def _criar_os(self):
        if self._sel and self._ao_criar:
            self._ao_criar(self._sel)

    def _abrir_chamado(self):
        if self._sel and self._ao_chamado:
            self._ao_chamado(self._sel)

    def reiniciar(self):
        """Entrar de novo = busca limpa. Cliente/usina ficam — voltar para a mesma usina é o
        normal de quem está conferindo uma planta."""
        self.busca.clear()
