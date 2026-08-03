"""Nova análise de performance — o diálogo que cria a OS atribuída a um analista.

CLIENTE → USINA → ATIVO em CASCATA, a partir do catálogo (16.931 ativos). O Levi foi explícito:
"o ativo e usina tem que ser reais e não digitado". Campo livre aqui geraria OS órfã, sem `code`,
que não casa com nada no Fracttal nem no board.

A PRIORIDADE é escolhida aqui e vira duas coisas: o bloco `[PERFORMANCE]` na observação (que o
board lê) e, na Máxima, a etiqueta "Dar prioridade" (que quem abrir a OS direto no Fracttal vê).
Ela não é enfeite — 42 das 44 OS já atribuídas a analistas terminaram canceladas, e a régua da
fila é o que o Roger Lélis condicionou para topar o processo.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
                             QLineEdit, QTextEdit, QPushButton, QFrame, QWidget, QMessageBox,
                             QCheckBox, QScrollArea, QSizePolicy)

import api
import perf_spec as ps
import perf_equipe as pe
import chamado_tokens as T
import chamado_fontes as CF
from chamado_pecas import Ponto, Regua
from workers import ApiWorker, slot_seguro
from steps.chamados import _folha, _texto_flex
from steps.searchcombo import tornar_pesquisavel


# Primeiro item de cada combo: um PEDIDO, não um valor. Dado `None` → o `_criar` recusa.
VAZIO_ANALISTA = "Analista"
VAZIO_CLIENTE  = "Preencher Cliente"
VAZIO_USINA    = "Preencher Usina"
VAZIO_ATIVO    = "Selecionar ativo"
AJUDA_ATIVO = ("Do catálogo do Fracttal — digite para buscar. "
               "“Usina” quando não é de um equipamento.")
AJUDA_ATIVO_TERC = "Usina de terceiros não tem ativo no Fracttal — vai no genérico da Grid Co."


def _rot(txt):
    l = QLabel(txt.upper())
    l.setStyleSheet(f"color:{T.TEXT_MUTED};")
    CF.aplicar(l, 10.5, QFont.Weight.DemiBold, tracking=0.6)
    return l


def _campo(rotulo, widget, ajuda=""):
    w = QWidget()
    v = QVBoxLayout(w); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(6)
    v.addWidget(_rot(rotulo)); v.addWidget(widget)
    w.ajuda = None                     # exposto p/ quem precisa TROCAR a ajuda depois
    if ajuda:
        a = _texto_flex(QLabel(ajuda))
        a.setStyleSheet(f"color:{T.TEXT_LABEL};font-size:10.5px;")
        v.addWidget(a); w.ajuda = a
    return w


class _OpcaoPrio(QFrame):
    """Uma das três opções de prioridade. Clicável, com o ponto na cor da faixa."""
    def __init__(self, chave, titulo, sub, cor, on_click):
        super().__init__()
        self._chave = chave; self._cor = cor; self._on_click = on_click
        self.setObjectName("opc")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        v = QVBoxLayout(self); v.setContentsMargins(11, 9, 11, 9); v.setSpacing(3)
        lin = QHBoxLayout(); lin.setSpacing(7 - Ponto.BLEED)
        lin.addWidget(Ponto(cor, T.DOT["status"], glow=(cor != T.DOT_IDLE)))
        lt = QLabel(titulo)
        lt.setStyleSheet(f"color:{T.TEXT};font-size:11.5px;font-weight:600;")
        lin.addWidget(lt); lin.addStretch(1)
        v.addLayout(lin)
        ls = QLabel(sub); ls.setStyleSheet(f"color:{T.TEXT_LABEL};font-size:10px;")
        v.addWidget(ls)
        self.marcar(False)

    def marcar(self, on):
        if on:
            self.setStyleSheet("QFrame#opc{background:%s;border:1px solid %s;border-radius:10px;}"
                               % (T.rgba(self._cor, 0.10), T.rgba(self._cor, 0.55)))
        else:
            self.setStyleSheet("QFrame#opc{background:transparent;border:1px solid %s;"
                               "border-radius:10px;}" % T.BORDER_STRONG)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._on_click(self._chave)


class NovaAnaliseDialog(QDialog):
    def __init__(self, parent=None, analista_padrao=""):
        super().__init__(parent)
        self.criada = None
        self._w = None
        self._assets = api.load_assets_cached() or []
        self._prio = ps.PRIORIDADE_PADRAO
        self._terceiros = False        # usina que não é ativo cadastrado (mesmo modo do COS)

        self.setWindowTitle("Nova análise de performance")
        self.setMinimumWidth(660)
        self.setStyleSheet(_folha() + "QDialog{background:%s;}" % T.BG)
        env = QVBoxLayout(self); env.setContentsMargins(14, 12, 14, 14)
        painel = QFrame(); painel.setObjectName("panel")
        # a janela abre cheia, mas o formulário fica na largura combinada (o dobro do card de OS)
        # e centralizado — molas dos dois lados, nunca AlignHCenter, que entrega o sizeHint
        from steps.os_detalhe import LARGURA_CARD
        painel.setMaximumWidth(LARGURA_CARD * 2)
        cen = QHBoxLayout(); cen.setContentsMargins(0, 0, 0, 0); cen.setSpacing(0)
        cen.addStretch(1); cen.addWidget(painel, 100); cen.addStretch(1)
        env.addLayout(cen)

        # ESTRUTURA: cabeçalho fixo · FORMULÁRIO QUE ROLA · rodapé fixo.
        # O formulário é mais alto que a janela (9 campos + prioridade + rodapé). Sem área de
        # rolagem o Qt tem que escolher entre COMPRIMIR (o combo de ativo saía com 26px, texto
        # cortado) e SOBREPOR (os campos entraram uns por cima dos outros quando travei a altura).
        # As duas coisas aconteceram, nessa ordem. O certo é deixar rolar.
        painel_v = QVBoxLayout(painel)
        painel_v.setContentsMargins(0, 0, 0, 0); painel_v.setSpacing(0)

        topo = QWidget()
        tv = QVBoxLayout(topo); tv.setContentsMargins(24, 22, 24, 0); tv.setSpacing(6)
        # título à esquerda, OS pai no canto oposto: é campo opcional e raro, não merece uma
        # linha do formulário — e no cabeçalho ele fica onde o olho já passa ao abrir a tela
        lin1 = QHBoxLayout(); lin1.setSpacing(16)
        cx_tit = QVBoxLayout(); cx_tit.setSpacing(6)
        tit = QLabel("Nova análise de performance"); tit.setObjectName("panelTitle")
        sub = _texto_flex(QLabel("Cria uma OS no Fracttal, atribuída ao analista, com a etiqueta "
                                 "PERFORMANCE, tipo %s e classificação %s / %s."
                                 % (api.TIPO_ANALISE, api.ANALISE_CLASSIF_1, api.ANALISE_CLASSIF_2)))
        sub.setObjectName("secondary")
        cx_tit.addWidget(tit); cx_tit.addWidget(sub)
        lin1.addLayout(cx_tit, 1)
        self.ed_pai = QLineEdit(); self.ed_pai.setPlaceholderText("nº da OS que originou")
        self.ed_pai.setFixedWidth(220)
        cx_pai = _campo("OS pai (opcional)", self.ed_pai)
        cx_pai.setFixedWidth(220)
        lin1.addWidget(cx_pai, 0, Qt.AlignmentFlag.AlignTop)
        tv.addLayout(lin1)
        tv.addSpacing(14); tv.addWidget(Regua(T.TEXT_BRIGHT, 0.10))
        painel_v.addWidget(topo)

        rolo = QScrollArea(); rolo.setWidgetResizable(True)
        rolo.setFrameShape(QScrollArea.Shape.NoFrame)
        rolo.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rolo.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        rolo.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        rolo.viewport().setStyleSheet("background:transparent;")
        corpo = QWidget(); rolo.setWidget(corpo)
        painel_v.addWidget(rolo, 1)
        v = QVBoxLayout(corpo); v.setContentsMargins(24, 16, 24, 8); v.setSpacing(14)

        # ── quem + o quê, em DUAS linhas de dois ──
        # Era: [Atribuir a] / [Cliente | Usina] / [Ativo] = três linhas, e o formulário passava
        # da altura da janela. Nenhum desses campos precisa de largura cheia — emparelhar mata
        # uma linha e tira a rolagem.
        # NENHUM combo abre escolhido. Antes o Qt selecionava o primeiro item de cada um, e a tela
        # nascia com "Ana Barros / 2C / Araputanga 1" — quem não reparasse criava a OS no nome e na
        # usina errados. O 1º item agora é um pedido, com `None` de dado, e o `_criar` recusa.
        self.cb_analista = QComboBox()
        self.cb_analista.addItem(VAZIO_ANALISTA, None)
        for d in pe.carregar():
            self.cb_analista.addItem(d["nome"], d)
        if analista_padrao:
            i = self.cb_analista.findText(analista_padrao)
            if i >= 0:
                self.cb_analista.setCurrentIndex(i)
        self.cb_cli = QComboBox(); self.cb_usi = QComboBox(); self.cb_ativo = QComboBox()

        g = QGridLayout(); g.setHorizontalSpacing(12); g.setVerticalSpacing(14)
        # AlignTop nas quatro células: sem isso o QGridLayout CENTRALIZA cada uma na altura da
        # linha, e como o campo Ativo é mais alto (tem texto de ajuda embaixo), Usina descia uns
        # 14px — dois campos lado a lado com os rótulos em alturas diferentes.
        topo_ = Qt.AlignmentFlag.AlignTop
        g.addWidget(_campo("Atribuir a", self.cb_analista), 0, 0, topo_)
        g.addWidget(_campo("Cliente", self.cb_cli), 0, 1, topo_)
        g.addWidget(_campo("Usina", self.cb_usi), 1, 0, topo_)
        self.w_ativo = _campo("Ativo", self.cb_ativo, AJUDA_ATIVO)
        g.addWidget(self.w_ativo, 1, 1, topo_)
        g.setColumnStretch(0, 1); g.setColumnStretch(1, 1)
        v.addLayout(g)
        v.addWidget(self._build_terceiros())
        for cb in (self.cb_analista, self.cb_cli, self.cb_usi, self.cb_ativo):
            cb.setMinimumWidth(180)
            # Fixed na VERTICAL: quando o formulário fica mais alto que a janela, o Qt comprime
            # o que pode encolher — e escolhia justamente o combo de ativo (o que tem texto de
            # ajuda embaixo), que saía com 26px contra 38 dos vizinhos, com o texto cortado.
            cb.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.cb_cli.currentIndexChanged.connect(self._cli_mudou)
        self.cb_usi.currentIndexChanged.connect(self._usi_mudou)
        # o pedido ("Preencher Cliente") tem de PARECER vazio. Com a cor de texto normal ele lê
        # como valor escolhido — que é exatamente a confusão que a tela veio corrigir.
        for cb in (self.cb_analista, self.cb_cli, self.cb_usi, self.cb_ativo):
            cb.currentIndexChanged.connect(lambda _i, c=cb: self._pintar_vazio(c))
            self._pintar_vazio(cb)

        # ── prioridade ──
        cores = {ps.MAXIMA: T.RED, ps.CLIENTE: T.AMBER, ps.ROTINA: T.DOT_IDLE}
        subs = {ps.MAXIMA: "PR muito impactado", ps.CLIENTE: "pedido direto",
                ps.ROTINA: "ronda / verificação"}
        linha = QHBoxLayout(); linha.setSpacing(9)
        self._opcoes = {}
        for chave, _, _ in ps.PRIORIDADES:
            o = _OpcaoPrio(chave, chave, subs[chave], cores[chave], self._set_prio)
            self._opcoes[chave] = o
            linha.addWidget(o, 1)
        cx = QWidget(); QVBoxLayout(cx).addLayout(linha)
        cx.layout().setContentsMargins(0, 0, 0, 0)
        v.addWidget(_campo("Prioridade", cx))
        # o _set_prio inicial vai no FIM do __init__: ele chama _atualizar_etiquetas, que escreve
        # em self.lb_etq — que só nasce mais abaixo. Chamar aqui derrubava o diálogo inteiro.

        # ── texto ──
        self.ed_motivo = QLineEdit()
        self.ed_motivo.setPlaceholderText("vira o título da OS — ex.: PR 41% abaixo da meta")
        v.addWidget(_campo("Motivo", self.ed_motivo))
        self.ed_desc = QTextEdit(); self.ed_desc.setMinimumHeight(70); self.ed_desc.setMaximumHeight(90)
        self.ed_desc.setPlaceholderText("O que precisa ser verificado?")
        v.addWidget(_campo("Detalhes", self.ed_desc))

        # "Pedido por" SAIU (pedido do Levi): quem pediu já sai de quem criou a OS + do
        # motivo escrito, e o campo custava uma linha inteira para quase nunca ser preenchido.
        # A "OS pai" subiu para o cabeçalho.
        v.addStretch(1)          # o formulário termina aqui; o rodapé é fixo, fora da rolagem

        # ── rodapé FIXO: os botões não podem sumir por rolagem ──
        pe_ = QWidget()
        pv = QVBoxLayout(pe_); pv.setContentsMargins(24, 0, 24, 18); pv.setSpacing(10)
        pv.addWidget(Regua(T.TEXT_BRIGHT, 0.10))
        self.lb_etq = _texto_flex(QLabel(""))
        self.lb_etq.setStyleSheet(f"color:{T.TEXT_FAINT};font-size:10.5px;")
        pv.addWidget(self.lb_etq)
        rod = QHBoxLayout(); rod.setSpacing(9)
        self.hint = QLabel("")
        self.hint.setStyleSheet(f"color:{T.TEXT_FAINT};font-size:11.5px;")
        rod.addWidget(self.hint); rod.addStretch(1)
        b_c = QPushButton("Cancelar"); b_c.clicked.connect(self.reject)
        self.b_ok = QPushButton("Criar OS de análise"); self.b_ok.setObjectName("primary")
        self.b_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_ok.clicked.connect(self._criar)
        rod.addWidget(b_c); rod.addWidget(self.b_ok)
        pv.addLayout(rod)
        painel_v.addWidget(pe_)

        self._set_prio(ps.PRIORIDADE_PADRAO)     # agora lb_etq já existe
        self._popular_clientes()
        # Altura travada DEPOIS de popular: o `tornar_pesquisavel` troca o combo para editável a
        # cada recarga da cascata e desfaz a política de tamanho, então o combo de ativo (o único
        # com texto de ajuda embaixo) era o eleito para encolher quando o formulário passava da
        # altura da janela — saía com 26px contra 38, texto cortado ao meio.
        # A altura vem de um IRMÃO, não de um número cravado: se o padding da folha mudar, os
        # quatro acompanham juntos.
        alt = max(cb.sizeHint().height() for cb in (self.cb_analista, self.cb_cli, self.cb_usi))
        for cb in (self.cb_analista, self.cb_cli, self.cb_usi, self.cb_ativo):
            cb.setFixedHeight(alt)

    # ── cascata ──
    def _popular_clientes(self):
        cls = sorted({a.get("cliente") for a in self._assets if a.get("cliente")})
        self.cb_cli.blockSignals(True)
        self.cb_cli.clear(); self.cb_cli.addItem(VAZIO_CLIENTE, None)
        for c in cls:
            self.cb_cli.addItem(c, c)
        self.cb_cli.blockSignals(False)
        tornar_pesquisavel(self.cb_cli)
        self._cli_mudou()

    def _cli(self):
        """Cliente escolhido, ou None enquanto for o pedido. No modo terceiros é texto livre."""
        if self._terceiros:
            return (self.cb_cli.currentText() or "").strip() or None
        return self.cb_cli.currentData()

    def _usi(self):
        if self._terceiros:
            return (self.cb_usi.currentText() or "").strip() or None
        return self.cb_usi.currentData()

    def _cli_mudou(self, *_):
        cli = self._cli()
        us = sorted({a.get("usina") for a in self._assets
                     if cli and a.get("cliente") == cli and a.get("usina")})
        self.cb_usi.blockSignals(True)
        self.cb_usi.clear(); self.cb_usi.addItem(VAZIO_USINA, None)
        for u in us:
            self.cb_usi.addItem(u, u)
        self.cb_usi.blockSignals(False)
        tornar_pesquisavel(self.cb_usi)
        self._usi_mudou()

    def _usi_mudou(self, *_):
        usi = self._usi()
        # o ativo do tipo Usina = a análise é da planta, não de um equipamento. O rótulo é só
        # "Usina" (era "— a usina inteira —", que o Levi achou ridículo, com razão).
        da_usina = [a for a in self._assets if usi and a.get("usina") == usi]
        planta = next((a for a in da_usina if (a.get("tipo") or "").lower() == "usina"), None)
        self.cb_ativo.blockSignals(True)
        self.cb_ativo.clear(); self.cb_ativo.addItem(VAZIO_ATIVO, None)
        if planta:
            self.cb_ativo.addItem("Usina", planta)
        for a in sorted(da_usina, key=lambda x: ((x.get("tipo") or ""), (x.get("description") or ""))):
            if a is planta:
                continue
            nome = (a.get("description") or "").split("{")[0].strip()[:64]
            self.cb_ativo.addItem("%s · %s" % (a.get("tipo") or "?", nome), a)
        self.cb_ativo.blockSignals(False)
        tornar_pesquisavel(self.cb_ativo)
        self._atualizar_etiquetas()

    def _pintar_vazio(self, cb):
        """Cinza no pedido, cor de texto no valor. Só a propriedade `color` — o resto (borda,
        raio, padding) continua vindo da folha; a folha de widget só sobrepõe o que declara."""
        vazio = cb.currentData() is None and not self._terceiros
        cb.setStyleSheet("color:%s;" % (T.TEXT_LABEL if vazio else T.TEXT))

    # ── usina de terceiros ────────────────────────────────────────────────────
    def _build_terceiros(self):
        """Mesmo recurso que o COS já tem: O&M de usina que não é ativo do Fracttal. Cliente e
        Usina viram texto livre e a OS vai no ativo genérico 'Grid Co. - Emergências e outros
        pontos'. Sem isso, análise de usina de terceiro simplesmente não podia ser aberta aqui."""
        self.ck_terc = QCheckBox("Usina de terceiros")
        self.ck_terc.toggled.connect(self._tog_terceiros)
        cx = QWidget()
        h = QHBoxLayout(cx); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(9)
        h.addWidget(self.ck_terc)
        exp = QLabel("Cliente e usina digitados · a OS vai no ativo genérico da Grid Co.")
        exp.setStyleSheet(f"color:{T.TEXT_LABEL};font-size:10.5px;")
        h.addWidget(exp); h.addStretch(1)
        return cx

    @slot_seguro
    def _tog_terceiros(self, on=False):
        self._terceiros = bool(on)
        for cb, dica in ((self.cb_cli, "Digite o cliente…"), (self.cb_usi, "Digite a usina…")):
            cb.blockSignals(True)
            cb.setEditable(self._terceiros)
            if self._terceiros:
                cb.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
                cb.clear(); cb.setCurrentText("")
                cb.lineEdit().setPlaceholderText(dica)
            cb.blockSignals(False)
        self.cb_ativo.setEnabled(not self._terceiros)
        if self._terceiros:
            self.cb_ativo.blockSignals(True)
            self.cb_ativo.clear()
            self.cb_ativo.addItem("Grid Co. — Emergências e outros pontos", None)
            self.cb_ativo.blockSignals(False)
        else:
            self.cb_ativo.setEnabled(True)
            self._popular_clientes()
        if self.w_ativo.ajuda is not None:
            self.w_ativo.ajuda.setText(AJUDA_ATIVO_TERC if self._terceiros else AJUDA_ATIVO)
        for cb in (self.cb_cli, self.cb_usi, self.cb_ativo):
            self._pintar_vazio(cb)
        self._atualizar_etiquetas()

    def _generico(self):
        """Asset sintético do genérico com o cliente/usina digitados. Os ids vêm do COS, que já
        usa esse ativo — uma fonte só para não divergirem."""
        from steps.varias_os import GENERICO_ID, GENERICO_DESC
        return {"id": GENERICO_ID, "code": "GRID", "id_type_item": 2, "id_parent": None,
                "id_group_task": None, "tipo": "Usina", "description": GENERICO_DESC,
                "label": "Grid Co. - Emergências e outros pontos",
                "usina": self._usi() or "", "cliente": self._cli() or ""}

    def _set_prio(self, chave):
        self._prio = chave
        for k, o in self._opcoes.items():
            o.marcar(k == chave)
        self._atualizar_etiquetas()

    def _atualizar_etiquetas(self):
        etq = ["PERFORMANCE"]
        if self._prio == ps.MAXIMA:
            etq.append("Dar prioridade")
        self.lb_etq.setText("Vai gravar no Fracttal: <b>%s</b>. O bloco [PERFORMANCE] com a "
                            "prioridade entra na observação — a API não edita OS já criada, "
                            "então o que não for gravado agora só muda no Fracttal web."
                            % " + ".join(etq))
        self.lb_etq.setTextFormat(Qt.TextFormat.RichText)

    # ── criar ──
    @slot_seguro
    def _criar(self, *_):
        if self._w is not None:
            return
        analista = self.cb_analista.currentData()
        if self._terceiros:
            if not self._cli() or not self._usi():
                QMessageBox.warning(self, "Análise", "Escreva o cliente e a usina."); return
            asset = self._generico()
        else:
            asset = self.cb_ativo.currentData()
            if not isinstance(asset, dict):
                # cobre os três pedidos da cascata: sem cliente não há usina, sem usina não há ativo
                QMessageBox.warning(self, "Análise", "Escolha cliente, usina e ativo."); return
        if not isinstance(analista, dict) or not analista.get("id_personnel"):
            QMessageBox.warning(self, "Análise",
                                "Não achei o cadastro deste analista no Fracttal — clique em "
                                "Atualizar no board para sincronizar e tente de novo."); return
        motivo = self.ed_motivo.text().strip()
        if not motivo:
            QMessageBox.warning(self, "Análise", "Escreva o motivo — ele vira o título da OS."); return
        bloco = ps.bloco({"prioridade": self._prio, "motivo": motivo,
                          "pedido_por": ""})    # campo removido da tela
        self.b_ok.setEnabled(False); self.hint.setText("criando a OS…")
        self._w = ApiWorker(api.create_os_analise, asset, analista["id_personnel"], "",
                            analista.get("nome") or "", self._prio, motivo,
                            self.ed_desc.toPlainText().strip(), "",
                            self.ed_pai.text().strip(), api.TIPO_ANALISE, bloco)
        self._w.ok.connect(self._ok); self._w.erro.connect(self._err)
        self._w.start()

    @slot_seguro
    def _err(self, m):
        self._w = None; self.b_ok.setEnabled(True); self.hint.setText("")
        QMessageBox.critical(self, "Análise", "Não consegui criar a OS:\n%s" % m)

    @slot_seguro
    def _ok(self, res):
        self._w = None; self.b_ok.setEnabled(True); self.hint.setText("")
        if not isinstance(res, dict) or not res.get("ok"):
            QMessageBox.critical(self, "Análise",
                                 (isinstance(res, dict) and res.get("erro")) or "não deu."); return
        self.criada = res
        partes = ["OS de análise criada — Nº %s." % (res.get("folio") or "?")]
        if not res.get("etiqueta_ok"):
            partes.append("Atenção: a OS foi criada mas a etiqueta PERFORMANCE não pegou — "
                          "sem ela o board não enxerga a OS.")
        if res.get("os_pai"):
            partes.append("Vinculada à OS pai %s." % res["os_pai"])
        if res.get("aviso"):
            partes.append("\nAviso: %s" % res["aviso"])
        QMessageBox.information(self, "Análise criada", "\n".join(partes))
        self.accept()


def nova_analise(parent, analista_padrao=""):
    """→ dict da OS criada, ou None.

    TELA CHEIA. A geometria em janela (altura do card de OS, dobro da largura) não pegou na
    máquina do Levi, e maximizar é o mesmo caminho do "Abrir chamado" — que já funciona. O
    CONTEÚDO continua com a largura combinada (o dobro do card), centralizado: janela cheia com
    campo de 1900px de largura não se lê."""
    dlg = NovaAnaliseDialog(parent, analista_padrao)
    dlg.showMaximized()
    dlg.exec()
    return dlg.criada


class _Amostra(QPushButton):
    """Bolinha na cor da coluna do analista. Clicar abre a paleta."""
    LADO = 20

    def __init__(self, cor, on_click, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.LADO, self.LADO)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Cor da coluna desta pessoa no quadro")
        self.clicked.connect(lambda *_: on_click())
        self.definir(cor)

    def definir(self, cor):
        self._cor = cor
        self.setStyleSheet("QPushButton{background:%s;border:1px solid %s;border-radius:%dpx;"
                           "min-height:0px;padding:0px;}"
                           % (cor, T.rgba(T.TEXT_BRIGHT, 0.25), self.LADO // 2))


class _PaletaDialog(QDialog):
    """Seis cores prontas + 'outra…'. As seis evitam o vermelho e o âmbar do semáforo, que nesta
    tela já significam prioridade máxima e pedido de cliente."""
    def __init__(self, parent, atual=""):
        super().__init__(parent)
        self.cor = ""
        self.setWindowTitle("Cor da coluna")
        self.setStyleSheet(_folha() + "QDialog{background:%s;}" % T.BG)
        v = QVBoxLayout(self); v.setContentsMargins(18, 16, 18, 14); v.setSpacing(11)
        t = QLabel("Cor da coluna"); t.setObjectName("panelTitle")
        v.addWidget(t)
        grade = QHBoxLayout(); grade.setSpacing(9)
        for c in pe.CORES + [pe.COR_PADRAO]:
            b = _Amostra(c, lambda cc=c: self._pegar(cc))
            b.setFixedSize(30, 30)
            b.setStyleSheet(b.styleSheet().replace("border-radius:10px", "border-radius:15px"))
            if c == atual:
                b.setStyleSheet("QPushButton{background:%s;border:2px solid %s;border-radius:15px;"
                                "min-height:0px;padding:0px;}" % (c, T.TEXT_BRIGHT))
            grade.addWidget(b)
        grade.addStretch(1)
        v.addLayout(grade)
        rod = QHBoxLayout(); rod.addStretch(1)
        b_out = QPushButton("Outra cor…"); b_out.clicked.connect(self._sistema)
        b_can = QPushButton("Cancelar"); b_can.clicked.connect(self.reject)
        rod.addWidget(b_out); rod.addWidget(b_can)
        v.addLayout(rod)

    @slot_seguro
    def _pegar(self, c):
        self.cor = c
        self.accept()

    @slot_seguro
    def _sistema(self, *_):
        from PyQt6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(parent=self)
        if c.isValid():
            self.cor = c.name()
            self.accept()


class GerenciarAnalistas(QDialog):
    """Quem aparece como coluna no quadro. Substitui o "+" gigante da lateral e o botão direito
    escondido — o Levi não achou nenhum dos dois, e ele estava certo: afordância que só existe
    no clique secundário não existe.

    Lista de marcar/desmarcar com os JÁ ESCOLHIDOS NO TOPO, porque a pergunta que se faz ao abrir
    é "quem está no quadro?", não "quem existe no Fracttal"."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.mudou = False
        self._w = None
        self._checks = {}
        self.setWindowTitle("Gerenciar analistas")
        self.setMinimumSize(460, 560)
        self.setStyleSheet(_folha() + "QDialog{background:%s;}" % T.BG)
        env = QVBoxLayout(self); env.setContentsMargins(14, 12, 14, 14)
        painel = QFrame(); painel.setObjectName("panel"); env.addWidget(painel)
        v = QVBoxLayout(painel); v.setContentsMargins(24, 20, 24, 18); v.setSpacing(12)
        t = QLabel("Gerenciar analistas"); t.setObjectName("panelTitle")
        s2 = _texto_flex(QLabel("Marque quem deve aparecer como coluna. Desmarcar NÃO mexe em OS "
                                "nenhuma — as OS da pessoa continuam no Fracttal, atribuídas "
                                "normalmente; só some a coluna."))
        s2.setObjectName("secondary")
        v.addWidget(t); v.addWidget(s2)
        v.addWidget(Regua(T.TEXT_BRIGHT, 0.10))

        self.busca = QLineEdit(); self.busca.setPlaceholderText("buscar pessoa…")
        self.busca.textChanged.connect(self._filtrar)
        v.addWidget(self.busca)

        rolo = QScrollArea(); rolo.setWidgetResizable(True)
        rolo.setFrameShape(QScrollArea.Shape.NoFrame)
        rolo.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rolo.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        rolo.viewport().setStyleSheet("background:transparent;")
        host = QWidget(); rolo.setWidget(host)
        self.lista = QVBoxLayout(host); self.lista.setContentsMargins(0, 0, 8, 0)
        self.lista.setSpacing(2)
        self.lb_carreg = QLabel("carregando o pessoal do Fracttal…"); self.lb_carreg.setObjectName("empty")
        self.lista.addWidget(self.lb_carreg); self.lista.addStretch(1)
        v.addWidget(rolo, 1)

        rod = QHBoxLayout(); rod.setSpacing(9); rod.addStretch(1)
        b_f = QPushButton("Fechar"); b_f.clicked.connect(self.accept)
        rod.addWidget(b_f)
        v.addLayout(rod)

        self._w = ApiWorker(api.get_responsaveis)
        self._w.ok.connect(self._chegou); self._w.erro.connect(self._falhou)
        self._w.start()

    @slot_seguro
    def _falhou(self, m):
        self._w = None
        self.lb_carreg.setText("não consegui buscar o pessoal do Fracttal")

    @slot_seguro
    def _chegou(self, pessoas):
        self._w = None
        equipe = pe.carregar()
        marcados = {pe._norm(d["nome"]): d for d in equipe}
        todos = []
        for p in (pessoas or []):
            nome = (p.get("name") or "").strip()
            if nome:
                todos.append({"nome": nome, "id_personnel": p.get("id_personnel")})
        # quem já está no quadro mas não voltou na lista do Fracttal continua aparecendo:
        # sumir com a coluna de alguém por causa de uma busca seria pior que mostrar a mais
        vistos = {pe._norm(d["nome"]) for d in todos}
        for d in equipe:
            if pe._norm(d["nome"]) not in vistos:
                todos.append(dict(d))
        # MARCADOS PRIMEIRO, na ordem do quadro; o resto alfabético
        ordem = {pe._norm(d["nome"]): i for i, d in enumerate(equipe)}
        todos.sort(key=lambda d: (ordem.get(pe._norm(d["nome"]), 10_000), d["nome"].lower()))

        while self.lista.count():
            it = self.lista.takeAt(0); w = it.widget()
            if w:
                w.deleteLater()
        self._cores = {}
        for d in todos:
            marcado = pe._norm(d["nome"]) in marcados
            lin = QWidget()
            h = QHBoxLayout(lin); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(8)
            cb = QCheckBox(d["nome"])
            cb.setChecked(marcado)
            cb.setCursor(Qt.CursorShape.PointingHandCursor)
            cb.setStyleSheet("QCheckBox{padding:6px 2px;font-size:12.5px;color:%s;}" % T.TEXT_DIM)
            cb.toggled.connect(lambda on, dd=d: self._alternar(dd, on))
            h.addWidget(cb, 1)
            # a cor só faz sentido para quem É coluna — para os demais fica escondida
            sw = _Amostra(pe.cor_de(marcados.get(pe._norm(d["nome"]), d)),
                          lambda dd=d: self._escolher_cor(dd))
            sw.setVisible(marcado)
            h.addWidget(sw)
            self._checks[d["nome"]] = cb
            self._cores[d["nome"]] = sw
            self.lista.addWidget(lin)
        self.lista.addStretch(1)

    def _alternar(self, d, ligado):
        if ligado:
            pe.adicionar(d["nome"], d.get("id_personnel"))
        else:
            pe.remover(d["nome"])
        sw = self._cores.get(d["nome"])
        if sw is not None:
            sw.setVisible(ligado)
            if ligado:                      # o `adicionar` escolhe a próxima cor livre da paleta
                atual = next((x for x in pe.carregar() if pe._norm(x["nome"]) == pe._norm(d["nome"])), None)
                sw.definir(pe.cor_de(atual))
        self.mudou = True

    @slot_seguro
    def _escolher_cor(self, d):
        """Paleta fixa + 'outra…' pelo seletor do sistema. Paleta primeiro porque o que se quer
        aqui é DISTINGUIR colunas, não achar um tom exato — e seis opções resolvem isso em um
        clique, sem abrir diálogo."""
        atual = next((x for x in pe.carregar() if pe._norm(x["nome"]) == pe._norm(d["nome"])), None)
        dlg = _PaletaDialog(self, pe.cor_de(atual))
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.cor:
            return
        pe.set_cor(d["nome"], dlg.cor)
        sw = self._cores.get(d["nome"])
        if sw is not None:
            sw.definir(dlg.cor)
        self.mudou = True

    def _filtrar(self, txt):
        alvo = pe._norm(txt)
        for nome, cb in self._checks.items():
            vis = not alvo or alvo in pe._norm(nome)
            pai = cb.parentWidget()
            (pai or cb).setVisible(vis)


def gerenciar_analistas(parent):
    dlg = GerenciarAnalistas(parent)
    dlg.exec()
    return dlg.mudou
