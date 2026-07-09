"""Aba 'Criar Solicitação' — cria uma Solicitação de Serviço (work request) no Fracttal via
requests.requests_insert. Cascata cliente→usina→tipo→ativo (cliente e usina PESQUISÁVEIS; tipo
com os MESMOS filtros do Criar OS — ALLOWED_TIPOS), + comentários, data, urgência e classificações.
Layout redesenhado (08/07): 4 cards compactos (Descrição · Ativo · Detalhes · Classificação) no estilo
dark premium (steps/ui.py), cards 3 e 4 lado a lado. NENHUMA regra/validação/ID/API mudou."""
from PyQt6.QtCore import Qt, QDateTime, QSize
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
                             QTextEdit, QLineEdit, QDateTimeEdit, QCheckBox, QPushButton,
                             QMessageBox, QScrollArea)
import api
from workers import ApiWorker
from steps.step1 import ALLOWED_TIPOS          # mesmos tipos de equipamento do Criar OS
from steps.searchcombo import tornar_pesquisavel
from steps.ui import QSS_FORM, Card, Dica, campo, Linha, icone_pix, GREEN, GREEN_INK, MUTED

CLIENTES_OCULTOS = {"almoxarifado", "teste - pa"}
_SEL = "— selecione —"
_TODOS_TIPOS = "Todos os tipos"


class SolicitacaoTab(QWidget):
    def __init__(self):
        super().__init__()
        self._assets = []
        self._types = None
        self._wt = None
        self._wc = None
        self.setStyleSheet(QSS_FORM)              # visual novo só nesta tela (sobrepõe o DARK_QSS global)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)   # nunca rola de lado
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(20, 14, 20, 18)
        lay.setSpacing(14)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        # ── topo: ação secundária (várias) + nota de obrigatórios ──
        top = QHBoxLayout()
        b_varias = QPushButton("Várias solicitações")
        b_varias.setObjectName("btnGhost")
        b_varias.setIcon(QIcon(icone_pix("layers", "#d4dae6", 15))); b_varias.setIconSize(QSize(15, 15))
        b_varias.setToolTip("Criar uma solicitação para CADA ativo marcado, de uma só vez")
        b_varias.setCursor(Qt.CursorShape.PointingHandCursor)
        b_varias.clicked.connect(self._abrir_varias)
        top.addWidget(b_varias)
        top.addStretch(1)
        req = QLabel(f"<span style='color:{GREEN};font-weight:700'>*</span> Campos obrigatórios")
        req.setObjectName("uiReqnote")
        top.addWidget(req)
        lay.addLayout(top)

        # ── Card 1 — Descrição ──
        self.desc = QTextEdit()
        self.desc.setPlaceholderText("Título do problema / solicitação")
        self.desc.setFixedHeight(44)
        c1 = Card(1, "Descrição da Solicitação")
        c1.add(Linha(
            campo("Título", self.desc, obrig=True),
            Dica("Seja claro e objetivo no título para facilitar a identificação da solicitação."),
            pesos=(3, 2),
        ))
        lay.addWidget(c1)

        # ── Card 2 — Ativo (cascata) ──
        self.cb_cliente = QComboBox(); tornar_pesquisavel(self.cb_cliente)   # busca + placeholder cinza
        self.cb_cliente.currentIndexChanged.connect(self._on_cli)
        self.cb_usina = QComboBox(); tornar_pesquisavel(self.cb_usina)
        self.cb_usina.currentIndexChanged.connect(self._on_usi)
        self.cb_tipo = QComboBox(); self.cb_tipo.currentIndexChanged.connect(self._refresh_ativos)
        self.busca = QLineEdit(); self.busca.setPlaceholderText("Pesquisar ativo por código ou nome…")
        self.busca.addAction(QIcon(icone_pix("search", MUTED, 15)), QLineEdit.ActionPosition.LeadingPosition)
        self.busca.textChanged.connect(self._refresh_ativos)
        self.cb_ativo = QComboBox()
        c2 = Card(2, "Ativo relacionado")
        c2.add(Linha(campo("Cliente", self.cb_cliente, obrig=True),
                     campo("Usina", self.cb_usina, obrig=True)))
        c2.add(Linha(campo("Tipo de equipamento", self.cb_tipo, obrig=True),
                     campo(" ", self.busca)))                       # rótulo em branco alinha a busca
        c2.add(campo("Ativo", self.cb_ativo, obrig=True))
        lay.addWidget(c2)

        # ── Card 3 — Detalhes do incidente ──
        self.data = QDateTimeEdit(QDateTime.currentDateTime())
        self.data.setDisplayFormat("dd/MM/yyyy HH:mm"); self.data.setCalendarPopup(True)
        self.urgente = QCheckBox("É urgente?")
        self.urgente.setCursor(Qt.CursorShape.PointingHandCursor)
        urg = QWidget(); urg.setObjectName("uiGroup"); urg.setMinimumHeight(40)
        uh = QHBoxLayout(urg); uh.setContentsMargins(0, 0, 0, 0); uh.addWidget(self.urgente); uh.addStretch(1)
        self.coment = QTextEdit(); self.coment.setFixedHeight(92)
        self.coment.setPlaceholderText("Informações adicionais sobre o incidente…")
        c3 = Card(3, "Detalhes do incidente")
        c3.add(Linha(campo("Data do incidente", self.data, obrig=True),
                     campo(" ", urg), quebra=300, pesos=(3, 2)))
        c3.add(campo("Observação", self.coment))

        # ── Card 4 — Classificação ──
        self.cb_grupo = QComboBox()
        self.cb_c1 = QComboBox()
        self.cb_c2 = QComboBox()
        c4 = Card(4, "Classificação")
        c4.add(campo("Grupo", self.cb_grupo, obrig=True))
        c4.add(campo("Classificação 1", self.cb_c1, obrig=True))
        c4.add(campo("Classificação 2", self.cb_c2))

        # cards 3 e 4 lado a lado (empilham quando estreito)
        lay.addWidget(Linha(c3, c4, quebra=720))

        # ── ações ──
        acts = QHBoxLayout(); acts.setContentsMargins(0, 2, 0, 0); acts.setSpacing(10); acts.addStretch(1)
        b_limpar = QPushButton("Limpar"); b_limpar.setObjectName("btnGhost")
        b_limpar.setIcon(QIcon(icone_pix("x", "#d4dae6", 15))); b_limpar.setIconSize(QSize(15, 15))
        b_limpar.setCursor(Qt.CursorShape.PointingHandCursor)
        b_limpar.setToolTip("Limpar os campos do formulário")
        b_limpar.clicked.connect(self.reset)
        self.btn = QPushButton("Criar Solicitação"); self.btn.setObjectName("btnPrimary")
        self.btn.setIcon(QIcon(icone_pix("send", GREEN_INK, 16))); self.btn.setIconSize(QSize(16, 16))
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.clicked.connect(self._criar)
        acts.addWidget(b_limpar); acts.addWidget(self.btn)
        lay.addLayout(acts)
        self.hint = QLabel(""); self.hint.setObjectName("hint")
        lay.addWidget(self.hint, 0, Qt.AlignmentFlag.AlignRight)
        lay.addStretch(1)

    # ── dados ──
    def set_assets(self, assets):
        self._assets = assets or []
        cls = sorted({a["cliente"] for a in self._assets
                      if a.get("cliente") and a["cliente"].strip().lower() not in CLIENTES_OCULTOS})
        self.cb_cliente.blockSignals(True)
        self.cb_cliente.clear(); self.cb_cliente.addItem(_SEL); self.cb_cliente.addItems(cls)
        self.cb_cliente.setCurrentIndex(0)
        self.cb_cliente.blockSignals(False)
        self._on_cli()

    def prefill_por_code(self, code):
        """Pré-seleciona cliente → usina → ativo a partir do code de um ativo (ex.: vindo de uma OS).
        Devolve True se conseguiu selecionar o ativo. Os tipos da classificação não são tocados."""
        code = (code or "").strip()
        asset = next((a for a in self._assets if a.get("code") == code), None)
        if not asset:
            return False
        cli, usi = asset.get("cliente"), asset.get("usina")
        ic = self.cb_cliente.findText(cli) if cli else -1
        if ic > 0:
            self.cb_cliente.setCurrentIndex(ic)        # dispara _on_cli → popula usinas
        iu = self.cb_usina.findText(usi) if usi else -1
        if iu > 0:
            self.cb_usina.setCurrentIndex(iu)          # dispara _on_usi → popula tipo + ativos
        if self.cb_tipo.count():
            self.cb_tipo.setCurrentIndex(0)            # "Todos os tipos" p/ não esconder o ativo
        self._refresh_ativos()
        for k in range(self.cb_ativo.count()):
            a = self.cb_ativo.itemData(k)
            if isinstance(a, dict) and a.get("code") == code:
                self.cb_ativo.setCurrentIndex(k)
                return True
        return False

    def _abrir_varias(self):
        """Abre o diálogo 'Várias Solicitações' (uma por ativo marcado)."""
        from steps.varias_solic import abrir_varias_solic
        abrir_varias_solic(self.window())

    def carregar_inicial(self):
        """1ª abertura da aba → busca as listas (grupo/classificações)."""
        if self._types is None and self._wt is None:
            self.hint.setText("carregando listas…")
            self._wt = ApiWorker(api.get_request_types)
            self._wt.ok.connect(self._set_types)
            self._wt.erro.connect(lambda m: self.hint.setText("Erro ao carregar as listas: " + m))
            self._wt.start()

    def _set_types(self, t):
        self._wt = None
        self._types = t or {}
        self.hint.setText("")

        def fill(cb, items):
            cb.clear()
            cb.addItem(_SEL, None)
            for it in items:
                cb.addItem(it["description"], it["id"])
        fill(self.cb_grupo, self._types.get("grupo", []))
        fill(self.cb_c1, self._types.get("classif1", []))
        fill(self.cb_c2, self._types.get("classif2", []))

    # ── cascata do ativo (cliente/usina resolvidos por texto — robusto ao combo editável) ──
    def _cli(self):
        t = self.cb_cliente.currentText().strip()
        return t if (t and t != _SEL and self.cb_cliente.findText(t) > 0) else None

    def _usi(self):
        t = self.cb_usina.currentText().strip()
        return t if (t and t != _SEL and self.cb_usina.findText(t) > 0) else None

    def _on_cli(self):
        cli = self._cli()
        us = sorted({a["usina"] for a in self._assets if a.get("cliente") == cli and a.get("usina")}) if cli else []
        self.cb_usina.blockSignals(True)
        self.cb_usina.clear(); self.cb_usina.addItem(_SEL); self.cb_usina.addItems(us)
        self.cb_usina.setCurrentIndex(0)
        self.cb_usina.setEnabled(bool(us))
        self.cb_usina.blockSignals(False)
        self._on_usi()

    def _on_usi(self):
        cli, usi = self._cli(), self._usi()
        # tipos com a MESMA régua do Criar OS (só ALLOWED_TIPOS presentes na usina)
        tipos = sorted({a.get("tipo") for a in self._assets
                        if a.get("cliente") == cli and a.get("usina") == usi
                        and a.get("tipo") in ALLOWED_TIPOS}) if usi else []
        self.cb_tipo.blockSignals(True)
        self.cb_tipo.clear(); self.cb_tipo.addItem(_TODOS_TIPOS); self.cb_tipo.addItems(tipos)
        self.cb_tipo.setEnabled(bool(tipos))
        self.cb_tipo.blockSignals(False)
        self._refresh_ativos()

    def _refresh_ativos(self):
        """Popula o Ativo — só ALLOWED_TIPOS (igual ao Criar OS) + filtro de tipo + busca textual."""
        cli, usi = self._cli(), self._usi()
        tipo = self.cb_tipo.currentText() if self.cb_tipo.currentIndex() > 0 else None
        txt = (self.busca.text() or "").strip().lower()
        self.cb_ativo.clear(); self.cb_ativo.addItem(_SEL, None)
        if not usi:
            return
        for a in sorted([x for x in self._assets if x.get("cliente") == cli and x.get("usina") == usi],
                        key=lambda x: x["label"]):
            if a.get("tipo") not in ALLOWED_TIPOS:
                continue
            if tipo and a.get("tipo") != tipo:
                continue
            if txt and txt not in a["label"].lower():
                continue
            self.cb_ativo.addItem(a["label"], a)

    # ── criar ──
    def _criar(self):
        asset = self.cb_ativo.currentData()
        desc = self.desc.toPlainText().strip()
        c1 = self.cb_c1.currentData()
        if not desc:
            QMessageBox.warning(self, "Título", "O título não pode ficar em branco."); return
        if not asset:
            QMessageBox.warning(self, "Ativo", "Selecione o ativo (cliente → usina → ativo)."); return
        if not c1:
            QMessageBox.warning(self, "Classificação 1", "A Classificação 1 é obrigatória."); return
        self.btn.setEnabled(False); self.hint.setText("criando solicitação…")
        di = self.data.dateTime().toPyDateTime()   # local; create_solicitacao converte p/ UTC
        self._wc = ApiWorker(api.create_solicitacao, asset, desc, c1, self.cb_grupo.currentData(),
                             self.cb_c2.currentData(), self.coment.toPlainText().strip(), di,
                             self.urgente.isChecked(),
                             desc_type_1=self._txt(self.cb_c1),
                             desc_type=self._txt(self.cb_grupo),
                             desc_type_2=self._txt(self.cb_c2))
        self._wc.ok.connect(self._ok)
        self._wc.erro.connect(self._err)
        self._wc.start()

    def _txt(self, cb):
        """Texto do dropdown se houver opção real escolhida (índice 0 = '— selecione —')."""
        return cb.currentText() if cb.currentIndex() > 0 else ""

    def _ok(self, r):
        self._wc = None
        self.btn.setEnabled(True); self.hint.setText("")
        num = (r or {}).get("id_code") or "criada"
        QMessageBox.information(self, "Sucesso", f"Solicitação criada — Nº {num}.")
        self.reset()

    def _err(self, m):
        self._wc = None
        self.btn.setEnabled(True); self.hint.setText("")
        QMessageBox.critical(self, "Erro ao criar solicitação", m)

    def reset(self):
        self.desc.clear(); self.coment.clear(); self.urgente.setChecked(False)
        self.busca.blockSignals(True); self.busca.clear(); self.busca.blockSignals(False)
        self.cb_cliente.setCurrentIndex(0)
        for cb in (self.cb_grupo, self.cb_c1, self.cb_c2):
            if cb.count():
                cb.setCurrentIndex(0)
        self.data.setDateTime(QDateTime.currentDateTime())
