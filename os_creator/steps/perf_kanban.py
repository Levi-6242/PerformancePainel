"""Alocação de análises — o quadro de carga da equipe de Performance.

DUAS TELAS, no design "Chamados 1B" (docs/redesign/design_handoff_chamados_1b/):
  • board  — uma coluna por ANALISTA, cabeçalho centralizado e clicável;
  • drill  — clicou no nome: Pendente · Em processo · Concluída daquela pessoa.

A legenda de prioridade é FIXA na tela, não é decoração: o Roger Lélis condicionou o kanban a
ela na reunião de 16/07 ("precisa de uma legenda do que é prioritário, pra não ficar na cabeça
de todo mundo"). Ele estava certo por experiência própria — 8 das 8 OS que já foram atribuídas
a ele acabaram canceladas.

Marca (ponto, régua, barra) é PINTADA via `chamado_pecas`; caixa é QSS. Ver a regra em
`chamado_pecas.py` — raio fracionário em QSS é descartado e o ponto sai quadrado.
"""
import datetime as dt

from PyQt6.QtCore import Qt, QMimeData
from PyQt6.QtGui import QFont, QDrag
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
                             QScrollArea, QStackedWidget, QSizePolicy, QMessageBox, QComboBox,
                             QDialog, QLineEdit, QTextEdit, QApplication)

import api
import perf_spec as ps
import perf_equipe as pe
import perf_notas as pn
import chamado_tokens as T
import chamado_fontes as CF
from chamado_pecas import Ponto, Regua, BarraTempo, RotuloElidido
from workers import ApiWorker, slot_seguro
from steps.chamados import _folha, _texto_flex
import steps.perf_execucao as pex
from steps.searchcombo import tornar_pesquisavel

# Cor da PRIORIDADE. É a única coisa colorida do board — as colunas de analista ficam neutras
# de propósito: reusar o semáforo para identificar pessoa faria âmbar significar "Gabriela" no
# cabeçalho e "pedido de cliente" no card, na mesma tela.
COR_PRIO = {ps.MAXIMA: T.RED, ps.CLIENTE: T.AMBER, ps.ROTINA: T.DOT_IDLE}
COR_ESTADO = {ps.PENDENTE: T.RED, ps.EM_PROCESSO: T.BLUE, ps.CONCLUIDA: T.GREEN}
DIAS_JANELA = 90


def _tom(cor):
    return {T.RED: "red", T.AMBER: "amber", T.BLUE: "blue", T.GREEN: "green"}.get(cor, "blue")


def _rot_secao(txt):
    l = QLabel(txt.upper()); l.setObjectName("sectionLabel")
    CF.aplicar(l, T.TYPE["section"]["size"], QFont.Weight.DemiBold,
               tracking=T.TYPE["section"]["tracking"])
    return l


class _Legenda(QFrame):
    """A régua na tela, em UMA linha. O nome da ETIQUETA do Fracttal virou tooltip: quem precisa
    conferir lá dentro passa o mouse; quem só precisa da régua lê a linha e segue."""
    ITENS = [
        (T.RED,      "PRIORIDADE MÁXIMA", "PR muito impactado",
         "etiqueta “Dar prioridade”"),
        (T.AMBER,    "PEDIDO DE CLIENTE", "com prazo de retorno",
         "bloco [PERFORMANCE] na observação"),
        (T.BLUE,     "FAZENDO AGORA",     "a atividade do momento",
         "etiqueta “Atividade em execução”"),
        (T.DOT_IDLE, "ROTINA",            "ronda, verificação, o que a pessoa abriu para si",
         "sem marcação de prioridade"),
    ]

    def __init__(self):
        super().__init__()
        self.setObjectName("legenda")
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(9)
        v.addWidget(Regua(T.TEXT_BRIGHT, 0.09, esmaece="ambos"))
        h = QHBoxLayout(); h.setContentsMargins(2, 0, 2, 0); h.setSpacing(30)
        for cor, titulo, desc, etq in self.ITENS:
            bl = QWidget(); bl.setToolTip("No Fracttal: %s" % etq)
            lin = QHBoxLayout(bl); lin.setContentsMargins(0, 0, 0, 0)
            lin.setSpacing(8 - Ponto.BLEED)
            lin.addWidget(Ponto(cor, T.DOT["status"], glow=(cor != T.DOT_IDLE)))
            lt = QLabel(titulo); lt.setObjectName("colHeader")
            lt.setStyleSheet("color:%s;" % (T.TEXT_MUTED if cor == T.DOT_IDLE else cor))
            CF.aplicar(lt, T.TYPE["col_header"]["size"], QFont.Weight.Bold,
                       tracking=T.TYPE["col_header"]["tracking"])
            lin.addWidget(lt)
            ld = QLabel(desc); ld.setStyleSheet("color:%s;font-size:11px;" % T.TEXT_MUTED)
            lin.addWidget(ld)
            h.addWidget(bl)
        h.addStretch(1)
        v.addLayout(h)
        v.addWidget(Regua(T.TEXT_BRIGHT, 0.09, esmaece="ambos"))


class _CabecalhoColuna(QWidget):
    """Cabeçalho CENTRALIZADO (pedido do Levi).

    `enfeite=False` nas colunas de PESSOA: sem ponto. Ali a cor era neutra e o ponto não
    significava nada — enfeite ao lado de um nome só polui. Nas colunas de ESTADO o ponto fica,
    porque lá a cor É a informação (vermelho não iniciada, azul em processo, verde concluída).

    O CONTADOR SAIU (27/07): os cards já estão à vista, contá-los em cima da coluna era repetir
    o que os olhos leem sozinhos. Continua existindo como `self.cont` porque o `preencher` o
    alimenta — só não aparece.

    `on_remover`: botão direito no nome remove a pessoa do quadro (o + adiciona)."""
    def __init__(self, nome, cor, on_click=None, enfeite=True, on_remover=None, inicial=None,
                 cor_pessoa=None):
        super().__init__()
        self._on_click = on_click
        self._on_remover = on_remover
        self._nome = nome
        if on_click:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("Clique para ver as OS desta pessoa"
                            + (" · botão direito para tirar do quadro" if on_remover else ""))
        # PADDING SIMÉTRICO e o vão para a régua ZERADO (ver `_Coluna`): assim o nome fica no meio
        # exato entre o topo da faixa e a linha de baixo. Antes o cabeçalho tinha 5px de respiro e
        # havia mais 16px SOB ele até a régua — o nome saía 8px acima do centro (medido).
        h = QHBoxLayout(self); h.setContentsMargins(4, 9, 4, 9); h.setSpacing(8 - Ponto.BLEED)
        h.addStretch(1)
        if enfeite:
            h.addWidget(Ponto(cor, T.DOT["idle"], glow=(cor != T.DOT_IDLE)))
        if inicial:
            # 1B: a INICIAL é a identidade da pessoa. Fundo rgba INLINE — rgba vindo da folha não
            # pinta com pai transparente (medido); a forma e o tipo estão em QLabel#inicial.
            ini = QLabel(inicial); ini.setObjectName("inicial")
            ini.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ini.setStyleSheet("QLabel#inicial{background:%s;color:%s;}"
                              % (T.rgba(cor_pessoa or T.TEXT_MUTED, 0.16),
                                 cor_pessoa or T.TEXT_MUTED))
            h.addWidget(ini)
            h.addSpacing(2)
        lb = QLabel(nome.upper()); lb.setObjectName("colHeader")
        lb.setStyleSheet(f"color:{cor};")
        CF.aplicar(lb, T.TYPE["col_header"]["size"], QFont.Weight.Bold,
                   tracking=T.TYPE["col_header"]["tracking"])
        h.addWidget(lb)
        # o contador VOLTOU (1B), discreto: com 6 colunas e fila comprida, "quantas" deixou de
        # ser óbvio de bater o olho — que era o motivo de tê-lo tirado quando eram 4.
        self.cont = QLabel("00"); self.cont.setObjectName("counter")
        CF.aplicar(self.cont, 10, QFont.Weight.Bold, mono=True)
        self.cont.setStyleSheet("color:%s;" % T.TEXT_FAINT)
        h.addWidget(self.cont)
        h.addStretch(1)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._on_click:
            self._on_click()
        elif e.button() == Qt.MouseButton.RightButton and self._on_remover:
            self._on_remover(self._nome)


class _Card(QFrame):
    """Card de uma OS de análise. A moldura é a cor da PRIORIDADE — aqui a prioridade é o que
    manda na fila, diferente do board de Chamados onde a moldura é a coluna."""
    def __init__(self, d, on_click=None, mostrar_dono=False, on_exec=None):
        super().__init__()
        self._d = d; self._on_click = on_click
        self._inicio = None            # onde o botão foi pressionado (clique × arrasto)
        prio = ps.prioridade_de(d)
        estado = ps.estado_de(d)
        agora = ps.em_execucao(d)
        feito = estado == ps.CONCLUIDA
        cor = T.BLUE if agora else COR_PRIO.get(prio, T.DOT_IDLE)

        self.setObjectName("card")
        self.setProperty("group", _tom(cor))
        self.setProperty("done", "true" if feito else "false")
        if on_click:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(230)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        # TRILHO DE PRIORIDADE: é a border-left do card, não um widget. Widget de 3px não
        # acompanha o raio de 12; borda grossa o Qt desenha arredondada sozinho. O gradiente do
        # topo saiu — com o trilho, o degradê era um segundo sinal para a mesma informação.
        self.setStyleSheet("QFrame#card{background:%s;border-left:3px solid %s;}"
                           % (T.CARD_MUTED if feito else T.CARD,
                              T.rgba(cor, 0.55) if feito else cor))

        v = QVBoxLayout(self); v.setContentsMargins(*T.CARD_MARGINS); v.setSpacing(T.CARD_SPACING)

        # ── linha 1: número · tipo · estado ──
        l1 = QHBoxLayout(); l1.setSpacing(7)
        num = QLabel(str(d.get("folio") or "?")); num.setObjectName("osNumber")
        CF.aplicar(num, 15, QFont.Weight.Bold, mono=True, tracking=-0.6)
        if feito:
            num.setStyleSheet(f"color:{T.TEXT_DIM};")
        l1.addWidget(num)
        # o chip do TIPO virou texto simples: em 241px a pílula custava 20px de contorno para
        # dizer o que a palavra já diz. E ele é o ÚNICO ELÁSTICO da linha, elidindo — com QLabel
        # comum, "Estação Meteorológica" empurrava o estado para fora do card e o texto saía
        # cortado no meio da palavra, sem reticência (medido em 1560px/6 colunas).
        tp = (d.get("tipo") or "").strip()
        if tp and tp != "—":
            ch = RotuloElidido(tp); ch.setObjectName("meta")
            l1.addWidget(ch, 1)
        else:
            l1.addStretch(1)
        if agora:
            texto, tone = "fazendo agora", "blue"
        elif feito:
            h = ps.tempo_conclusao(d)
            texto = "concluída" + (" · " + ps.fmt_duracao(h) if h is not None else "")
            tone = "green"
        elif prio == ps.MAXIMA:
            texto, tone = "prioridade máxima", "red"
        elif prio == ps.CLIENTE:
            texto, tone = "pedido do cliente", "amber"
        else:
            texto, tone = "rotina", "blue"
        ls = QLabel(texto); ls.setObjectName("status"); ls.setProperty("tone", tone)
        if prio == ps.ROTINA and not agora and not feito:
            ls.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:11px;font-weight:600;")
        l1.addWidget(ls)
        v.addLayout(l1)

        # ── corpo: título + (local · dias) ── (a régua interna saiu: era o terceiro traço
        # horizontal em 90px de altura)
        bl = QVBoxLayout(); bl.setSpacing(4)
        tit = _texto_flex(QLabel(d.get("descricao") or "—")); tit.setObjectName("cardTitle")
        if feito:
            tit.setStyleSheet(f"color:{T.TEXT_DIM};")
        bl.addWidget(tit)
        loc = " · ".join(x for x in (d.get("usina"), d.get("cliente")) if x and x != "—")
        if mostrar_dono and d.get("criado_por"):
            loc += f" · aberta por {d['criado_por']}"
        lin = QHBoxLayout(); lin.setSpacing(8)
        ll = RotuloElidido(loc or "—"); ll.setObjectName("secondary")
        lin.addWidget(ll, 1)                      # ÚNICO elástico da linha
        dias = ps.dias_parado(d)
        if dias is not None:
            urg = ps.urgencia(dias)
            cd = {"critico": T.RED_TEXT, "atencao": T.AMBER_TEXT}.get(urg, T.TEXT_FAINT)
            if dias == 0:
                cd = T.GREEN
            # rótulo CURTO: "parada" era a palavra mais longa da linha e a que menos informava —
            # a coluna já é a fila de quem está parado, e a cor diz a gravidade.
            lt = QLabel("hoje" if dias == 0 else
                        ("1 dia" if dias == 1 else "%d dias" % dias))
            lt.setStyleSheet(f"color:{cd};font-family:'JetBrains Mono',Consolas,monospace;"
                             "font-size:10px;font-weight:700;")
            lin.addWidget(lt, 0)
        bl.addLayout(lin)
        v.addLayout(bl)

        # ── rodapé: só ação ──
        rod = QHBoxLayout(); rod.setSpacing(6)
        if not feito and on_exec:
            # controle DIRETO no card (ícone + cronômetro), no lugar de um botão que abria
            # diálogo: iniciar e concluir são o gesto do dia a dia e não merecem dois cliques.
            # Pausar continua pedindo o motivo, porque o Fracttal exige um.
            rod.addWidget(pex.ControleExec(d, on_mudou=on_exec, compacto=True))
            rod.addWidget(pex.BotaoConcluir(d, on_mudou=on_exec))
            rod.addStretch(1)
            v.addLayout(rod)
        obs = pn.resumo(d.get("folio"))
        if obs:                                  # observação escrita na conclusão (registro local)
            self.setToolTip(obs)

    # ── clique abre · arrastar reatribui ──
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._inicio = e.position().toPoint()

    def mouseMoveEvent(self, e):
        """Só vira ARRASTO depois da distância mínima do sistema. Sem esse limiar, qualquer
        tremida no clique começava um drag e a pessoa não conseguia mais abrir a OS."""
        if not (e.buttons() & Qt.MouseButton.LeftButton) or self._inicio is None:
            return
        if (e.position().toPoint() - self._inicio).manhattanLength() < QApplication.startDragDistance():
            return
        md = QMimeData()
        md.setText(str(self._d.get("id") or ""))
        arr = QDrag(self)
        arr.setMimeData(md)
        arr.setPixmap(self.grab().scaledToWidth(220, Qt.TransformationMode.SmoothTransformation))
        self._inicio = None
        arr.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, e):
        if (e.button() == Qt.MouseButton.LeftButton and self._inicio is not None
                and self._on_click):
            self._on_click(self._d)
        self._inicio = None


class _Coluna(QWidget):
    """Coluna do board: cabeçalho + régua na cor + pilha de cards, sobre um véu na cor da coluna.

    O VÉU (pedido do Levi, 27/07): degradê levíssimo que começa no nome e some por volta da
    metade da altura — serve para o olho achar a própria coluna sem ler o nome. Fica no FUNDO
    da coluna, nunca no card: o card tem fundo opaco próprio e continua com a cor da prioridade.
    Inline e não pela folha porque `rgba()` vindo da folha não pinta quando o pai é transparente
    (medido); `qlineargradient` pinta nos dois."""
    def __init__(self, nome, cor, on_click=None, enfeite=True, on_remover=None, veu=None,
                 on_soltar=None, inicial=None, cor_pessoa=None):
        super().__init__()
        self._on_soltar = on_soltar
        if on_soltar:
            self.setAcceptDrops(True)
        # O VÉU SAIU no 1B: com 4 pessoas já competia com o semáforo e, com 6, matiz deixou de
        # identificar quem é quem. O parâmetro `veu` fica na assinatura para não quebrar chamada
        # antiga, mas o board passa veu=None — a cor da pessoa vive na inicial do cabeçalho.
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(T.COLUMN_SPACING)
        self.cab = _CabecalhoColuna(nome, cor, on_click, enfeite, on_remover, inicial, cor_pessoa)
        # cabeçalho e régua GRUDADOS num bloco só, com espaçamento zero: é esse bloco que define
        # "do topo até a linha de baixo", e o nome se centraliza nele pelo próprio padding.
        topo = QWidget()
        tv = QVBoxLayout(topo); tv.setContentsMargins(0, 0, 0, 0); tv.setSpacing(0)
        tv.addWidget(self.cab)
        # régua NEUTRA e esmaecida nas duas pontas: a cor dela era a da pessoa e virou ruído
        # repetido agora que a inicial já diz de quem é a coluna.
        tv.addWidget(Regua(T.TEXT_BRIGHT, 0.12, esmaece="ambos"))
        v.addWidget(topo)
        self.lista = QVBoxLayout(); self.lista.setSpacing(T.COLUMN_SPACING)
        v.addLayout(self.lista); v.addStretch(1)

    # ── soltar um card aqui = atribuir a OS a esta pessoa ──
    def dragEnterEvent(self, e):
        if self._on_soltar and e.mimeData().hasText():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if self._on_soltar and e.mimeData().hasText():
            e.acceptProposedAction()

    def dropEvent(self, e):
        oid = (e.mimeData().text() or "").strip()
        if self._on_soltar and oid:
            e.acceptProposedAction()
            self._on_soltar(oid)

    def limpar(self):
        while self.lista.count():
            it = self.lista.takeAt(0); w = it.widget()
            if w:
                w.deleteLater()

    def preencher(self, itens, on_card, vazio="Sem OS nesta fila", mostrar_dono=False,
                  on_exec=None):
        self.limpar()
        self.cab.cont.setText("%02d" % len(itens))
        for d in itens:
            self.lista.addWidget(_Card(d, on_card, mostrar_dono, on_exec))
        if not itens:
            lb = QLabel(vazio); lb.setObjectName("empty")
            lb.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.lista.addWidget(lb)


class PerfKanbanTab(QWidget):
    """A tela. Página 0 = board por pessoa; página 1 = drill de uma pessoa."""
    _selfnav = True

    def __init__(self, on_voltar=None):
        super().__init__()
        self._on_voltar = on_voltar
        self._w = None
        self._wt = None          # worker do tempo trabalhado (drill)
        self._wr = None          # worker da troca de responsável (arrastar-e-soltar)
        self._itens = []            # OS visíveis (sem canceladas)
        self._alvo = None           # pessoa aberta no drill

        self.setStyleSheet(_folha())
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_board())
        self.stack.addWidget(self._build_drill())
        root.addWidget(self.stack)

    def carregar_inicial(self):
        if not self._itens:
            self._carregar()

    # ══════════════════════ board ══════════════════════
    def _build_board(self):
        page = QWidget(); page.setObjectName("chPage")
        page.setProperty("tela", "perf")   # fundo roxo, só desta tela
        env = QVBoxLayout(page); env.setContentsMargins(14, 12, 14, 14)
        painel = QFrame(); painel.setObjectName("panel")
        painel.setProperty("flat", "true")   # tela cheia, sem moldura de cartão
        painel.setMaximumWidth(1560)
        # molas dos dois lados: AlignHCenter entregaria o sizeHint e o painel murcharia
        cen = QHBoxLayout(); cen.setContentsMargins(0, 0, 0, 0); cen.setSpacing(0)
        cen.addStretch(1); cen.addWidget(painel, 100); cen.addStretch(1)
        env.addLayout(cen)
        out = QVBoxLayout(painel)
        out.setContentsMargins(T.PANEL_MARGINS[0], T.PANEL_MARGINS[1],
                               T.PANEL_MARGINS[2], T.PANEL_MARGINS[3])
        out.setSpacing(T.SECTION_SPACING)

        cab = QHBoxLayout(); cab.setSpacing(16)
        tw = QVBoxLayout(); tw.setSpacing(5)
        tit = QLabel("Alocação de análises"); tit.setObjectName("panelTitle")
        self.hint = QLabel(""); self.hint.setObjectName("secondary")
        self.hint.setTextFormat(Qt.TextFormat.RichText)
        self.hint.setVisible(False)          # só aparece carregando ou em erro
        tw.addWidget(tit); tw.addWidget(self.hint)
        cab.addLayout(tw)

        # RESUMO EM NÚMEROS — quatro células mono, entre o título e os botões. Era uma frase com
        # números em <span> colorido; virar célula é o que faz a linha valer o espaço que ocupa.
        kp = QHBoxLayout(); kp.setSpacing(24)
        self.nums = {}
        for chave, rot in (("maxima", "em prioridade máxima"),
                           ("cliente", "pedidos de cliente"),
                           ("velhas", "paradas há mais de 7 dias"),
                           ("fora", "com o campo")):
            bx = QVBoxLayout(); bx.setSpacing(1)
            val = QLabel("—"); val.setObjectName("osNumber")
            CF.aplicar(val, 18, QFont.Weight.Bold, mono=True, tracking=-1.0)
            rl = QLabel(rot); rl.setObjectName("meta")
            bx.addWidget(val); bx.addWidget(rl)
            self.nums[chave] = val
            kp.addLayout(bx)
        cab.addLayout(kp)
        cab.addStretch(1)
        self.b_equipe = QPushButton("Gerenciar analistas")
        self.b_equipe.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_equipe.setToolTip("Escolher quem aparece como coluna no quadro")
        self.b_equipe.clicked.connect(self._gerenciar)
        self.b_nova = QPushButton("+ Nova análise"); self.b_nova.setObjectName("primary")
        self.b_nova.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_nova.clicked.connect(self._nova_analise)
        self.b_rec = QPushButton("Atualizar")
        self.b_rec.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_rec.clicked.connect(lambda: self._carregar(force=True))
        if self._on_voltar:
            b_v = QPushButton("← Voltar"); b_v.setCursor(Qt.CursorShape.PointingHandCursor)
            b_v.clicked.connect(lambda: self._on_voltar())
            cab.addWidget(b_v)
        for b in (self.b_rec, self.b_equipe, self.b_nova):
            cab.addWidget(b)
        out.addLayout(cab)
        out.addWidget(_Legenda())

        rolo = QScrollArea(); rolo.setWidgetResizable(True)
        rolo.setFrameShape(QScrollArea.Shape.NoFrame)
        rolo.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rolo.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        rolo.viewport().setStyleSheet("background:transparent;")
        host = QWidget(); rolo.setWidget(host)
        self.cols = QHBoxLayout(host)
        self.cols.setContentsMargins(0, 0, 14, 0)      # goteira da barra de rolagem
        self.cols.setSpacing(T.BOARD_SPACING)
        self.cols.setAlignment(Qt.AlignmentFlag.AlignTop)
        out.addWidget(rolo, 1)
        self._colunas = {}
        return page

    def _montar_colunas(self, nomes):
        """Recria as colunas (a lista de pessoas muda: analistas ↔ campo, e o + adiciona)."""
        while self.cols.count():
            it = self.cols.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        self._colunas = {}
        cores = {d["nome"]: pe.cor_de(d) for d in pe.carregar()}
        for nome in nomes:
            ini = "".join(p[0] for p in nome.split()[:2]).upper()
            c = _Coluna(nome, T.TEXT_DIM, on_click=(lambda n=nome: self._abrir_drill(n)),
                        enfeite=False, inicial=ini, cor_pessoa=cores.get(nome),
                        on_soltar=(lambda oid, n=nome: self._reatribuir(oid, n)))
            self._colunas[nome] = c
            self.cols.addWidget(c, 1)
        # (o "+" gigante da lateral saiu: quem inclui/tira analista é o "Gerenciar analistas"
        #  do cabeçalho — o Levi não achou nem o + nem o botão direito, e tinha razão)

    # ══════════════════════ reatribuir arrastando ══════════════════════
    @slot_seguro
    def _reatribuir(self, id_os, nome):
        """Card solto na coluna de outra pessoa = a OS passa a ser dela, no Fracttal.
        Confirma antes: é escrita em OS de produção, e um arrasto sem querer é fácil."""
        if self._wr is not None:
            return
        try:
            id_os = int(id_os)
        except (TypeError, ValueError):
            return
        d = next((x for x in self._itens if x.get("id") == id_os), None)
        if d is None:
            return
        if pe._norm(d.get("atribuido_a")) == pe._norm(nome):
            return                                        # soltou na mesma coluna: nada a fazer
        pessoa = next((p for p in pe.carregar() if pe._norm(p["nome"]) == pe._norm(nome)), None)
        if not pessoa or not pessoa.get("id_personnel"):
            QMessageBox.warning(self, "Responsável",
                                "Não sei o cadastro de %s no Fracttal. Clique em Atualizar "
                                "para sincronizar e tente de novo." % nome)
            return
        if QMessageBox.question(self, "Trocar responsável",
                                "Passar a OS %s de %s para %s?"
                                % (d.get("folio") or id_os, d.get("atribuido_a") or "—", nome)
                                ) != QMessageBox.StandardButton.Yes:
            return
        self.hint.setVisible(True)
        self.hint.setText("passando a OS %s para %s…" % (d.get("folio") or id_os, nome))
        self._wr = ApiWorker(api.mudar_responsavel, id_os, pessoa["id_personnel"])
        self._wr.ok.connect(self._reatribuiu)
        self._wr.erro.connect(self._reatribuir_erro)
        self._wr.start()

    @slot_seguro
    def _reatribuiu(self, res):
        self._wr = None
        if isinstance(res, dict) and not res.get("ok"):
            QMessageBox.critical(self, "Responsável", str(res.get("erro") or "não deu"))
            self.hint.setText(""); return
        self._carregar(force=True)          # relê do Fracttal em vez de mover o card na mão

    @slot_seguro
    def _reatribuir_erro(self, m):
        self._wr = None
        self.hint.setText("")
        QMessageBox.critical(self, "Responsável", str(m))

    # ══════════════════════ carga ══════════════════════
    def _carregar(self, force=False):
        if self._w is not None:
            return
        self.hint.setVisible(True); self.hint.setText("carregando as OS de Performance…")
        for b in (self.b_rec,):
            b.setEnabled(False)
        hoje = dt.date.today()
        de = (hoje - dt.timedelta(days=DIAS_JANELA)).isoformat()
        self._w = ApiWorker(api.list_performance, de, hoje.isoformat())
        self._w.ok.connect(self._ok)
        self._w.erro.connect(self._err)
        self._w.start()

    @slot_seguro
    def _err(self, m):
        self._w = None
        for b in (self.b_rec,):
            b.setEnabled(True)
        self.hint.setVisible(True); self.hint.setText("erro ao carregar")
        QMessageBox.critical(self, "Performance", "Não consegui carregar as OS: %s" % m)

    @slot_seguro
    def _ok(self, itens):
        self._w = None
        for b in (self.b_rec,):
            b.setEnabled(True)
        self._itens = [d for d in (itens or []) if ps.visivel(d)]
        try:
            pe.sincronizar_ids()
        except Exception:
            pass
        self._render()
        # o `_render` só redesenha o QUADRO. Quem deu play estando no drill precisa ver o card
        # pular para "Em processo" ali mesmo — sem isto teria de sair do próprio nome e voltar.
        if self.stack.currentIndex() == 1 and getattr(self, "_alvo", None):
            self._abrir_drill(self._alvo)

    def _pessoas(self):
        return [d["nome"] for d in pe.carregar()]

    def _render(self):
        nomes = self._pessoas()
        if set(nomes) != set(self._colunas):
            self._montar_colunas(nomes)
        idx = {pe._norm(n): n for n in nomes}
        por = {n: [] for n in nomes}
        for d in self._itens:
            n = idx.get(pe._norm(d.get("atribuido_a")))
            if n:
                por[n].append(d)
        ordem = {ps.PENDENTE: 0, ps.EM_PROCESSO: 0, ps.CONCLUIDA: 1}
        for n, l in por.items():
            l.sort(key=lambda d: (ordem[ps.estado_de(d)],
                                  ps.ORDEM.get(ps.prioridade_de(d), 9),
                                  -(ps.dias_parado(d) or 0)))
            # cronômetro TAMBÉM no quadro geral. Eu tinha deixado só no drill achando que aqui
            # seria ruído — mas é no quadro que a pessoa bate o olho e começa a trabalhar;
            # obrigar a entrar no próprio nome antes de dar play é atrito à toa.
            self._colunas[n].preencher(
                l, self._abrir_os,
                vazio="Sem OS nesta fila",
                on_exec=lambda: self._carregar(force=True))
        self._resumo(por)

    def _resumo(self, por):
        vis = [d for l in por.values() for d in l]
        aberto = [d for d in vis if ps.estado_de(d) != ps.CONCLUIDA]
        maxima = sum(1 for d in aberto if ps.prioridade_de(d) == ps.MAXIMA)
        cli = sum(1 for d in aberto if ps.prioridade_de(d) == ps.CLIENTE)
        velhas = sum(1 for d in vis if (ps.dias_parado(d) or 0) > 7)
        fora = len(self._itens) - len(vis)

        for chave, valor, cor in (("maxima", maxima, T.RED_TEXT),
                                  ("cliente", cli, T.AMBER_TEXT),
                                  ("velhas", velhas, T.AMBER_TEXT),
                                  ("fora", fora, T.TEXT_DIM)):
            lb = self.nums[chave]
            lb.setText("%02d" % valor)
            # zero não merece cor de alarme: fica cinza para a cor só aparecer quando há o que ver
            lb.setStyleSheet("color:%s;" % (cor if valor else T.TEXT_FAINT))
        self.hint.setVisible(not vis)
        if not vis:
            self.hint.setText("nenhuma OS de Performance nesta visão (últimos %d dias)"
                              % DIAS_JANELA)

    # ══════════════════════ ações ══════════════════════
    def _gerenciar(self):
        from steps.perf_nova import gerenciar_analistas
        if gerenciar_analistas(self):
            self._montar_colunas(self._pessoas())
            self._render()

    def _abrir_os(self, d):
        from steps.os_detalhe import abrir_os_detalhe
        abrir_os_detalhe(self, d.get("id"), d.get("folio"))

    def _nova_analise(self):
        from steps.perf_nova import nova_analise
        if nova_analise(self):
            self._carregar(force=True)

    # ══════════════════════ drill ══════════════════════
    def _build_drill(self):
        page = QWidget(); page.setObjectName("chPage")
        page.setProperty("tela", "perf")   # fundo roxo, só desta tela
        env = QVBoxLayout(page); env.setContentsMargins(14, 12, 14, 14)
        painel = QFrame(); painel.setObjectName("panel")
        painel.setProperty("flat", "true")   # tela cheia, sem moldura de cartão
        env.addWidget(painel)
        out = QVBoxLayout(painel)
        out.setContentsMargins(T.PANEL_MARGINS[0], T.PANEL_MARGINS[1],
                               T.PANEL_MARGINS[2], T.PANEL_MARGINS[3])
        out.setSpacing(T.SECTION_SPACING)

        b_volta = QPushButton("← Todos"); b_volta.setObjectName("link")
        b_volta.setCursor(Qt.CursorShape.PointingHandCursor)
        b_volta.setStyleSheet("QPushButton#link{border:none;background:transparent;padding:0;"
                              "color:%s;font-size:12px;text-align:left;}"
                              "QPushButton#link:hover{color:%s;}" % (T.TEXT_MUTED, T.ACCENT))
        b_volta.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        lv = QHBoxLayout(); lv.addWidget(b_volta); lv.addStretch(1)
        out.addLayout(lv)

        cab = QHBoxLayout(); cab.setSpacing(16)
        tw = QVBoxLayout(); tw.setSpacing(5)
        self.d_nome = QLabel("—"); self.d_nome.setObjectName("panelTitle")
        self.d_sub = QLabel(""); self.d_sub.setObjectName("secondary")
        tw.addWidget(self.d_nome); tw.addWidget(self.d_sub)
        cab.addLayout(tw); cab.addStretch(1)
        b_nova = QPushButton("+ Nova análise"); b_nova.setObjectName("primary")
        b_nova.setCursor(Qt.CursorShape.PointingHandCursor)
        b_nova.clicked.connect(self._nova_analise)
        cab.addWidget(b_nova)
        out.addLayout(cab)

        kp = QHBoxLayout(); kp.setSpacing(26)
        self.kpis = {}
        for chave, rot in (("abertas", "abertas no nome"), ("agora", "fazendo agora"),
                           ("tempo", "tempo médio de conclusão"),
                           ("feitas", "concluídas em 7 dias")):
            bx = QVBoxLayout(); bx.setSpacing(2)
            val = QLabel("—"); val.setObjectName("osNumberLarge")
            CF.aplicar(val, 22, QFont.Weight.Bold, mono=True, tracking=-1.0)
            rl = QLabel(rot); rl.setObjectName("secondary")
            bx.addWidget(val); bx.addWidget(rl)
            self.kpis[chave] = val
            kp.addLayout(bx)
        kp.addStretch(1)
        out.addLayout(kp)

        linha = QHBoxLayout(); linha.setSpacing(T.BOARD_SPACING)
        linha.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.d_cols = {}
        for est in ps.ESTADOS:
            c = _Coluna(est, COR_ESTADO[est])
            self.d_cols[est] = c
            linha.addWidget(c, 1)
        rolo = QScrollArea(); rolo.setWidgetResizable(True)
        rolo.setFrameShape(QScrollArea.Shape.NoFrame)
        rolo.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rolo.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        rolo.viewport().setStyleSheet("background:transparent;")
        hostd = QWidget(); rolo.setWidget(hostd)
        hl = QVBoxLayout(hostd); hl.setContentsMargins(0, 0, 14, 0)
        hl.addLayout(linha); hl.addStretch(1)
        out.addWidget(rolo, 1)
        return page

    def _abrir_drill(self, nome):
        self._alvo = nome
        self.d_nome.setText(nome)
        idx = pe._norm(nome)
        meus = [d for d in self._itens if pe._norm(d.get("atribuido_a")) == idx]
        self.d_sub.setText("OS com a etiqueta PERFORMANCE atribuídas a esta pessoa · "
                           "últimos %d dias" % DIAS_JANELA)
        for est in ps.ESTADOS:
            l = [d for d in meus if ps.estado_de(d) == est]
            l.sort(key=lambda d: (ps.ORDEM.get(ps.prioridade_de(d), 9),
                                  -(ps.dias_parado(d) or 0)))
            self.d_cols[est].preencher(l, self._abrir_os, vazio="nada aqui", mostrar_dono=True,
                                       on_exec=lambda: self._carregar(force=True))
        abertas = [d for d in meus if ps.estado_de(d) != ps.CONCLUIDA]
        feitas = [d for d in meus if ps.estado_de(d) == ps.CONCLUIDA]
        corte = (dt.date.today() - dt.timedelta(days=7)).isoformat()
        rec = sum(1 for d in feitas if (d.get("data_fim") or "")[:10] >= corte)
        self.kpis["abertas"].setText("%02d" % len(abertas))
        self.kpis["agora"].setText("%02d" % sum(1 for d in meus if ps.em_execucao(d)))
        self.kpis["feitas"].setText("%02d" % rec)
        # tempo TRABALHADO, não "fim menos criação": este vem do cronômetro do Fracttal e é
        # buscado à parte (2 chamadas por OS) porque só faz sentido na tela de UMA pessoa.
        self.kpis["tempo"].setText("…")
        self._carregar_tempos([d.get("id") for d in feitas])
        self.stack.setCurrentIndex(1)

    def _carregar_tempos(self, ids):
        """Média do tempo TRABALHADO das OS concluídas desta pessoa."""
        if not ids or self._wt is not None:
            self.kpis["tempo"].setText("—")
            return
        self._wt = ApiWorker(api.tempo_trabalhado_em_massa, ids)
        self._wt.ok.connect(self._tempos_ok)
        self._wt.erro.connect(lambda *_: self._tempos_ok({}))
        self._wt.start()

    @slot_seguro
    def _tempos_ok(self, mapa):
        self._wt = None
        segs = [s for s in (mapa or {}).values() if s]
        if not segs:
            # nenhuma OS concluída foi cronometrada — o normal HOJE, porque o cronômetro é
            # novo. Melhor dizer isso do que exibir um número vindo de subtração de datas,
            # que contaria noite e fim de semana como trabalho.
            self.kpis["tempo"].setText("—")
            self.kpis["tempo"].setToolTip("nenhuma OS concluída desta pessoa foi cronometrada")
            return
        media = sum(segs) / len(segs)
        self.kpis["tempo"].setText(pex.fmt_seg(media))
        self.kpis["tempo"].setToolTip("média de %d OS cronometrada(s)" % len(segs))
