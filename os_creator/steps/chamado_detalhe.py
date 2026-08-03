"""Tela do CHAMADO — design "Chamados 1B" (docs/redesign/design_handoff_chamados_1b/, §5.2).

Substitui a linha da planilha `Gestão de Chamados`: traz os dados que a equipe olhava lá e,
principalmente, a LINHA DO TEMPO das atualizações — a coluna "Observações", que na planilha
real guarda 4.334 entradas datadas (mediana de 7 por chamado).

Valores de cor/tipo/espaço vêm de `chamado_tokens`; nada é digitado à mão. O que o QSS não faz
(letter-spacing) sai por `chamado_fontes.aplicar`.
"""
from PyQt6.QtCore import Qt, QDateTime
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QWidget, QFrame,
                             QLabel, QTextEdit, QLineEdit, QPushButton, QScrollArea, QMessageBox,
                             QComboBox, QDateTimeEdit, QSizePolicy)

import api
import chamado_log as clog
import chamado_spec as cs
import chamado_tokens as T
import chamado_fontes as CF
from chamado_pecas import Ponto, Regua, Trilho, Combo   # marca se PINTA, caixa se estiliza
from workers import ApiWorker, slot_seguro
from steps.ui import campo, QSS_FORM


def abrir_chamado_detalhe(parent, d):
    """`d` = item do painel (dict do list_chamados + '_sub' das subtarefas)."""
    dlg = ChamadoDetalheDialog(parent, d)
    dlg.showMaximized()
    dlg.exec()
    return dlg.mudou


def _folha():
    from steps.chamados import _folha as f
    return f()


def _cor_status(st):
    from steps.chamados import _status_cor
    return _status_cor(st) if (st or "").strip() else T.TEXT_MUTED


def _secao(txt):
    """Rótulo de seção: 10.5/600, tracking +1, maiúsculas, TEXT_LABEL."""
    l = QLabel(txt.upper()); l.setObjectName("sectionLabel")
    CF.aplicar(l, T.TYPE["section"]["size"], QFont.Weight.DemiBold,
               tracking=T.TYPE["section"]["tracking"])
    return l


def _rot(txt):
    """Rótulo de campo: 10.5/600, tracking +0.6, maiúsculas, TEXT_MUTED."""
    l = QLabel(txt.upper())
    l.setStyleSheet(f"color:{T.TEXT_MUTED};background:transparent;")
    CF.aplicar(l, 10.5, QFont.Weight.DemiBold, tracking=0.6)
    return l


def _par(k, v, mono=True):
    """Linha de dado: rótulo 12 MUTED à esquerda, valor 12.5 à direita (mono nos códigos).
    Valor ausente sai em TEXT_FAINT — o "—" é informação, não decoração."""
    h = QHBoxLayout(); h.setSpacing(10)
    kl = QLabel(k); kl.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:12px;")
    vazio = str(v).strip() in ("", "—")
    vl = _texto_flex(QLabel(str(v)))
    vl.setStyleSheet("color:%s;" % (T.TEXT_FAINT if vazio else T.TEXT))
    CF.aplicar(vl, 12.5, QFont.Weight.Medium if mono and not vazio else QFont.Weight.DemiBold,
               mono=(mono and not vazio))
    vl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
    # SEM addStretch: o valor usa `Ignored` na horizontal ("não peço largura"), então uma mola
    # antes dele comeria tudo e o texto sumiria — foi o que apagou RMA/fabricante da lateral.
    # Quem empurra para a direita é o alinhamento do próprio rótulo, não a mola.
    h.addWidget(kl); h.addWidget(vl, 1)
    return h


def _regua():
    """Divisória de 1px, PINTADA (ver chamado_pecas)."""
    return Regua(T.TEXT_BRIGHT, 0.10)


def _texto_flex(lb):
    from steps.chamados import _texto_flex as f
    return f(lb)


# A `_Ponto` local foi APAGADA. Existia uma cópia aqui e outra em chamados.py; as duas geravam o
# raio com f"{tam/2:.1f}px" → "3.5px"/"4.5px", e o parser de QSS do Qt DESCARTA comprimento
# fracionário. Resultado medido no render: ponto de 9x9 com 81/81 pixels preenchidos, ou seja,
# QUADRADO — nas duas telas, desde sempre. Agora é `chamado_pecas.Ponto`, pintado.


# Geometria do trilho, DERIVADA do HTML alvo (não chutada). Lá cada entrada é
#   [gutter 52] --gap 14--> <div border-left:1px; padding-left:16>  e o ponto fica em left:-4.5,
# ou seja, montado sobre a linha. O Qt não tem position:absolute nem coordenada negativa, então
# a linha vive numa FAIXA da largura do ponto (9px), centrada — o que a joga para x=4 dentro da
# faixa. Os dois espaçamentos abaixo descontam isso para a linha cair a 14px do gutter e o corpo
# a 16px da linha, iguais ao HTML.
_LANE = T.DOT["recent"]                     # 9 — largura da faixa do ponto
_LINHA_X = _LANE // 2                       # 4 — onde a linha cai dentro da faixa
_GAP_TRILHO = 14 - _LINHA_X                 # 10
_PAD_CORPO = 16 - (_LANE - _LINHA_X)        # 11


class _Entrada(QWidget):
    """Uma atualização. Gutter de 52px à direita (data mono + ano), trilho de 1px com o ponto
    POR CIMA (QGridLayout — o Qt não tem position:absolute) e o corpo.
    A cor vem da NATUREZA do evento (§5.2): ação nossa/recente = ACCENT com cartão;
    mudança de status = AMBER; histórico importado = DOT_IDLE.
    O trilho é CONTÍNUO do primeiro ao último ponto. O HTML alvo tinha `gap:14px` entre as
    entradas, o que picotava o fio em traços soltos e matava a leitura vertical do histórico —
    o design confirmou que ali o HTML é que estava errado. Em Qt: espaçamento ZERO entre as
    entradas e o respiro de 14px vai para a margem INFERIOR do corpo, dentro da entrada, para
    o trilho correr de ponta a ponta. `ultima=True` para o fio na altura do último ponto."""
    RESPIRO = 14

    def __init__(self, e, recente=False, ultima=False):
        super().__init__()
        # a entrada tem a altura do seu conteúdo e nada mais — ver o addStretch em _render
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        texto = str(e.get("texto") or "")
        planilha = e.get("origem") == "planilha"
        # §5.2 define TRÊS categorias e só três. O verde é exclusivo da entrada mais recente —
        # se qualquer registro do app virasse verde, a timeline inteira acenderia e o destaque
        # perderia o sentido.
        if recente and not planilha:
            cor, tam, cartao = T.ACCENT, T.DOT["recent"], True
        elif texto.lower().startswith("status:"):
            cor, tam, cartao = T.AMBER, T.DOT["status"], False
        else:
            cor, tam, cartao = T.DOT_IDLE, T.DOT["idle"], False

        h = QHBoxLayout(self); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(0)

        data = str(e.get("data") or "")
        gut = QWidget(); gut.setFixedWidth(T.TIMELINE_GUTTER)
        gut.setStyleSheet("background:transparent;")
        gv = QVBoxLayout(gut); gv.setContentsMargins(0, 0, 0, 0); gv.setSpacing(1)
        ld = QLabel((data[8:10] + "/" + data[5:7]) if len(data) >= 10 else "—")
        ld.setObjectName("date")
        # a data acompanha o PONTO, menos no cinza: ali o ponto é DOT_IDLE (quase o fundo) e a
        # data precisa continuar legível — por isso TEXT_MUTED, como manda a §5.2.
        ld.setStyleSheet("color:%s;background:transparent;"
                         % (cor if cor in (T.ACCENT, T.AMBER) else T.TEXT_MUTED))
        CF.aplicar(ld, T.TYPE["date"]["size"], QFont.Weight.Bold, mono=True)
        ld.setAlignment(Qt.AlignmentFlag.AlignRight)
        la = QLabel(data[:4] if len(data) >= 4 else "")
        la.setStyleSheet(f"color:{T.TEXT_LABEL};background:transparent;")
        CF.aplicar(la, T.TYPE["year"]["size"], QFont.Weight.Normal)
        la.setAlignment(Qt.AlignmentFlag.AlignRight)
        gv.addWidget(ld); gv.addWidget(la); gv.addStretch(1)
        h.addWidget(gut)
        h.addSpacing(_GAP_TRILHO)

        topo = 9 if cartao else 5              # onde o centro do ponto cai (top do HTML)
        trilho = QWidget(); trilho.setFixedWidth(_LANE)
        tg = QGridLayout(trilho); tg.setContentsMargins(0, 0, 0, 0); tg.setSpacing(0)
        # na ÚLTIMA entrada o fio para na altura do ponto — não sobra rabicho embaixo
        tg.addWidget(Trilho(T.TEXT_BRIGHT, 0.10, fim=ultima, parada=topo + tam // 2),
                     0, 0, Qt.AlignmentFlag.AlignHCenter)
        cx = QWidget()
        cv = QVBoxLayout(cx); cv.setContentsMargins(0, 0, 0, 0); cv.setSpacing(0)
        cv.addSpacing(topo - Ponto.BLEED)       # a caixa do ponto sangra BLEED p/ caber o halo
        # halo em tudo menos no cinza do histórico: acender o que é ruído tira o destaque de quem
        # importa
        cv.addWidget(Ponto(cor, tam, glow=(cor != T.DOT_IDLE)), 0, Qt.AlignmentFlag.AlignHCenter)
        cv.addStretch(1)
        tg.addWidget(cx, 0, 0)
        h.addWidget(trilho)
        h.addSpacing(_PAD_CORPO)

        corpo = QFrame(); corpo.setObjectName("chCorpo")
        # `QFrame#chCorpo`, NUNCA `QFrame` puro — a mesma armadilha do chLado, dez linhas acima:
        # QLabel HERDA de QFrame, então o rótulo do texto recebia a tinta verde DE NOVO e o
        # accent a 6% era aplicado duas vezes na altura de uma linha. Medido: (33,43,35) dentro
        # da caixa do rótulo contra (24,32,33) no resto do cartão — a banda clara era isso.
        if cartao:
            corpo.setStyleSheet("QFrame#chCorpo{background:%s;border:1px solid %s;"
                                "border-radius:10px;}"
                                % (T.rgba(T.ACCENT, 0.06), T.rgba(T.ACCENT, 0.18)))
            cvv = QVBoxLayout(corpo); cvv.setContentsMargins(13, 10, 13, 10)
        else:
            corpo.setStyleSheet("QFrame#chCorpo{background:transparent;border:none;}")
            cvv = QVBoxLayout(corpo); cvv.setContentsMargins(0, 2, 0, 2)
        cvv.setSpacing(5)
        tx = _texto_flex(QLabel(texto)); tx.setObjectName("body")
        tx.setStyleSheet(f"color:{T.TEXT_DIM};border:none;")
        tx.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cvv.addWidget(tx)
        quem = str(e.get("autor") or "").strip()
        if planilha:
            pl = QLabel("planilha")
            pl.setStyleSheet(f"color:{T.TEXT_LABEL};font-size:10px;font-style:italic;"
                             "background:transparent;border:none;")
            cvv.addWidget(pl)
        elif quem:
            ql = QLabel(quem)
            ql.setStyleSheet(f"color:{T.TEXT_FAINT};font-size:10.5px;background:transparent;"
                             "border:none;")
            cvv.addWidget(ql)
        # O respiro entre entradas mora FORA do cartão e DENTRO da coluna: se entrasse no `cvv`
        # o cartão verde cresceria com espaço morto; se entrasse na margem do `h` o trilho
        # encurtaria e o fio voltaria a ser picotado.
        env_corpo = QWidget()
        ev = QVBoxLayout(env_corpo)
        ev.setContentsMargins(0, 0, 0, 0 if ultima else self.RESPIRO); ev.setSpacing(0)
        ev.addWidget(corpo); ev.addStretch(1)
        h.addWidget(env_corpo, 1)


class _AberturaDialog(QDialog):
    """O que só existe DEPOIS de abrir o chamado no fabricante: o protocolo devolvido por ele e
    quando. O protocolo é obrigatório porque é a CHAVE do histórico — e é a coluna mais
    confiável da planilha (97% preenchida, contra 5% da 'OS de Abertura')."""
    def __init__(self, parent, ticket=""):
        super().__init__(parent)
        self.setWindowTitle("Marcar chamado como aberto")
        # QSS_FORM primeiro (dá o estilo dos rótulos que o `campo()` cria), folha 1B por cima —
        # em QSS de mesma especificidade a última regra vence. Sem isso este diálogo saía com o
        # tema antigo no meio da tela nova.
        self.setMinimumWidth(430)
        self.setStyleSheet(QSS_FORM + _folha() + f"QDialog{{background:{T.BG};}}")
        v = QVBoxLayout(self); v.setContentsMargins(18, 16, 18, 14); v.setSpacing(12)
        t = QLabel("Registre o retorno do fabricante. A OS passa para <b>Em Processo</b> e o "
                   "chamado sai da fila de abertura.")
        t.setWordWrap(True)
        t.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:12.5px;background:transparent;")
        v.addWidget(t)
        self.ed_tk = QLineEdit(ticket)
        self.ed_tk.setPlaceholderText("ex.: STI-44210, RMA-20614, SP4090368")
        self.ed_tk.textChanged.connect(self._upd)
        v.addWidget(campo("Nº do chamado / protocolo", self.ed_tk, obrig=True,
                          ajuda="é o número que o fabricante devolve — amarra todo o histórico"))
        self.dt = QDateTimeEdit(QDateTime.currentDateTime())
        self.dt.setDisplayFormat("dd/MM/yyyy HH:mm"); self.dt.setCalendarPopup(True)
        v.addWidget(campo("Data e hora da abertura", self.dt, obrig=True))
        lin = QHBoxLayout(); lin.setSpacing(9)
        b_c = QPushButton("Cancelar"); b_c.clicked.connect(self.reject)
        self.b_ok = QPushButton("Confirmar"); self.b_ok.setObjectName("primary")
        self.b_ok.clicked.connect(self.accept)
        lin.addStretch(1); lin.addWidget(b_c); lin.addWidget(self.b_ok)
        v.addLayout(lin)
        self._upd()

    def _upd(self, *_):
        self.b_ok.setEnabled(bool(self.ed_tk.text().strip()))

    def dados(self):
        return {"ticket": self.ed_tk.text().strip(),
                "quando": self.dt.dateTime().toPyDateTime()}


class ChamadoDetalheDialog(QDialog):
    def __init__(self, parent, d):
        super().__init__(parent)
        self._d = d if isinstance(d, dict) else {}
        self._sub = self._d.get("_sub") or {}
        self._bloco = api.parse_bloco_chamado(self._d.get("note"))
        self.mudou = False
        self._w = None
        # a chave sai do ticket da SUBTAREFA/bloco — não pode consultar o store do app aqui,
        # porque é ele que a chave endereça (o ticket gravado no app já vem migrado por
        # `migrar_chave` quando o chamado é marcado como aberto).
        self._ch = ""
        self._ch = clog.chave(self._sub.get("ticket") or self._bloco.get("ticket") or "",
                              self._d.get("folio"))

        self.setWindowTitle(f"Chamado — OS {self._d.get('folio') or ''}")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint)
        self.setMinimumSize(880, 620); self.setSizeGripEnabled(True)
        self.setStyleSheet(_folha() + f"QDialog{{background:{T.BG};}}")

        env = QVBoxLayout(self); env.setContentsMargins(14, 12, 14, 14); env.setSpacing(0)
        painel = QFrame(); painel.setObjectName("panel")
        env.addWidget(painel)
        lay = QVBoxLayout(painel); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        st0 = self._status(); cor0 = _cor_status(st0)

        # ══ header — gradiente da cor do estado a 10% → transparente ══
        self.cab = QFrame(); self.cab.setObjectName("chCab")
        ch = QHBoxLayout(self.cab); ch.setContentsMargins(26, 24, 26, 20); ch.setSpacing(18)
        esq = QVBoxLayout(); esq.setSpacing(8)

        l1 = QHBoxLayout(); l1.setSpacing(10 - Ponto.BLEED)   # desconta o sangramento do halo
        self.pt = Ponto(cor0, T.DOT["idle"]); l1.addWidget(self.pt)
        self.lb_st = QLabel(""); self.lb_st.setObjectName("colHeader")
        CF.aplicar(self.lb_st, T.TYPE["col_header"]["size"], QFont.Weight.Bold,
                   tracking=T.TYPE["col_header"]["tracking"])
        l1.addWidget(self.lb_st)
        self.lb_ctx = QLabel(""); self.lb_ctx.setTextFormat(Qt.TextFormat.RichText)
        self.lb_ctx.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:11.5px;background:transparent;")
        l1.addWidget(self.lb_ctx); l1.addStretch(1)
        esq.addLayout(l1)

        l2 = QHBoxLayout(); l2.setSpacing(12)
        n = QLabel(str(self._d.get("folio") or "?")); n.setObjectName("osNumberLarge")
        # (não precisa mais de `background:transparent` aqui: a folha nova declara
        #  `QLabel { background: transparent }`, então nenhum rótulo carimba fundo opaco.)
        CF.aplicar(n, T.TYPE["os_detail"]["size"], QFont.Weight.Bold, mono=True,
                   tracking=T.TYPE["os_detail"]["tracking"])
        n.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        l2.addWidget(n)
        at = _texto_flex(QLabel(self._d.get("ativo") or "—"))
        at.setStyleSheet(f"color:{T.TEXT};")
        CF.aplicar(at, T.TYPE["detail_title"]["size"], QFont.Weight.DemiBold)
        # AlignVCenter nos DOIS, não AlignBottom no ativo: o nº da OS é mono 24 e o ativo é 15,
        # então "encostar na base" alinhava as CAIXAS e deixava os textos em alturas diferentes.
        # Centro contra centro é o que faz os dois lerem como uma linha só.
        at.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        l2.addWidget(at, 1)
        esq.addLayout(l2)

        ctx = " · ".join([x for x in (self._d.get("usina"),
                          f"OS pai {self._bloco.get('os_pai')}" if self._bloco.get("os_pai") else "",
                          self._d.get("status")) if x])
        lc = _texto_flex(QLabel(ctx))
        lc.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:12.5px;")
        esq.addWidget(lc)
        ch.addLayout(esq, 1)

        # §3.8: o design não tem barra de rodapé — ação de janela mora no header. O rodapé era
        # uma faixa de 30px existindo só para um botão. O `hint` subiu junto, colado no
        # "Salvar situação", que é justamente a ação que ele comenta.
        acoes = QVBoxLayout(); acoes.setSpacing(8)
        self.b_sit = QPushButton("Salvar situação"); self.b_sit.setObjectName("primary")
        self.b_sit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_sit.clicked.connect(self._salvar_situacao)
        b_os = QPushButton("Abrir a OS no app")
        b_os.setCursor(Qt.CursorShape.PointingHandCursor); b_os.clicked.connect(self._abrir_os)
        b_f = QPushButton("Fechar"); b_f.setCursor(Qt.CursorShape.PointingHandCursor)
        b_f.clicked.connect(self.accept)
        self.hint = QLabel("")
        self.hint.setStyleSheet(f"color:{T.TEXT_FAINT};font-size:11.5px;")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignRight)
        # o hint vai DEPOIS dos botões: no meio deles, mesmo vazio, ele reservava a altura de uma
        # linha e abria um buraco entre "Salvar situação" e "Abrir a OS no app"
        acoes.addWidget(self.b_sit); acoes.addWidget(b_os); acoes.addWidget(b_f)
        acoes.addWidget(self.hint); acoes.addStretch(1)
        ch.addLayout(acoes)
        lay.addWidget(self.cab)

        # ══ corpo: 300px | stretch ══
        corpo = QWidget(); corpo.setStyleSheet("background:transparent;")
        cl = QHBoxLayout(corpo); cl.setContentsMargins(0, 0, 0, 0); cl.setSpacing(0)

        lado = QFrame(); lado.setObjectName("chLado")
        lado.setFixedWidth(T.DETAIL_SIDEBAR)
        # `QFrame#chLado`, NUNCA `QFrame` puro: QLabel HERDA de QFrame, então um seletor sem id
        # pinta o border-right em cada rótulo da coluna (saíam riscos verticais soltos ao lado
        # de DADOS / STATUS DO CHAMADO / AGUARDANDO).
        lado.setStyleSheet("QFrame#chLado{background:transparent;border:none;"
                           f"border-right:1px solid {T.BORDER};}}")
        lv = QVBoxLayout(lado); lv.setContentsMargins(22, 20, 22, 26); lv.setSpacing(16)
        dados = QVBoxLayout(); dados.setSpacing(11)
        dados.addWidget(_secao("Dados"))
        for k, v, mono in (("Ticket / RMA", self._ticket(), True),
                           ("Fabricante", self._val("fabricante"), False),
                           ("Serial", self._val("serial"), True),
                           ("Nº do RMA", self._val("rma"), True)):
            dados.addLayout(_par(k, v or "—", mono))
        lv.addLayout(dados)

        # QUEM ABRIU e QUEM ESTÁ COM ELE. Já vinham na listagem (`criado_por`/`atribuido_a`) e
        # não apareciam em lugar nenhum — quem abre o chamado precisava sair da tela para saber
        # a quem cobrar. Bloco próprio, separado dos dados do equipamento: é gente, não peça.
        lv.addWidget(_regua())
        pessoas = QVBoxLayout(); pessoas.setSpacing(11)
        pessoas.addWidget(_secao("Pessoas"))
        for k, v in (("Aberta por", (self._d.get("criado_por") or "").strip()),
                     ("Atribuída a", (self._d.get("atribuido_a") or "").strip())):
            pessoas.addLayout(_par(k, v or "—", mono=False))
        lv.addLayout(pessoas)
        lv.addWidget(_regua())
        b1 = QVBoxLayout(); b1.setSpacing(7)
        b1.addWidget(_rot("Status do chamado"))
        self.cb_status = Combo(); self.cb_status.addItem("—", "")
        for x in cs.STATUS:
            self.cb_status.addItem(x, x)
        b1.addWidget(self.cb_status); lv.addLayout(b1)
        b2 = QVBoxLayout(); b2.setSpacing(7)
        b2.addWidget(_rot("Aguardando"))
        self.cb_esp = Combo(); self.cb_esp.addItem("—", "")
        for x in cs.ESPERANDO:
            self.cb_esp.addItem(x, x)
        b2.addWidget(self.cb_esp); lv.addLayout(b2)
        self.b_aberto = QPushButton("Marcar como aberto")
        self.b_aberto.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_aberto.setToolTip("Registra o protocolo do fabricante e passa a OS para Em Processo")
        self.b_aberto.clicked.connect(self._marcar_aberto)
        lv.addWidget(self.b_aberto); lv.addStretch(1)
        cl.addWidget(lado)

        dir_ = QWidget(); dir_.setStyleSheet("background:transparent;")
        dv = QVBoxLayout(dir_); dv.setContentsMargins(26, 20, 26, 26); dv.setSpacing(0)
        cd = QHBoxLayout(); cd.setSpacing(10)
        cd.addWidget(_secao("Atualizações"))
        self.lb_n = QLabel("00"); self.lb_n.setObjectName("counter")
        CF.aplicar(self.lb_n, 10.5, QFont.Weight.Bold, mono=True)
        cd.addWidget(self.lb_n); cd.addStretch(1)
        dv.addLayout(cd); dv.addSpacing(12)

        comp = QHBoxLayout(); comp.setSpacing(10)
        self.ed_nova = QTextEdit(); self.ed_nova.setMinimumHeight(58)
        self.ed_nova.setMaximumHeight(58)
        self.ed_nova.setPlaceholderText("O que aconteceu? (a data entra sozinha)")
        comp.addWidget(self.ed_nova, 1)
        self.b_add = QPushButton("Adicionar"); self.b_add.setObjectName("primary")
        self.b_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_add.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.b_add.clicked.connect(self._adicionar)
        cbx = QVBoxLayout(); cbx.addStretch(1); cbx.addWidget(self.b_add)   # alinhado à base
        comp.addLayout(cbx)
        dv.addLayout(comp); dv.addSpacing(18)

        rolo = QScrollArea(); rolo.setWidgetResizable(True)
        rolo.setFrameShape(QScrollArea.Shape.NoFrame)
        rolo.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # AsNeeded: a barra estava desenhada mesmo sem nada para rolar
        rolo.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        rolo.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        rolo.viewport().setStyleSheet("background:transparent;")
        host = QWidget(); host.setStyleSheet("background:transparent;"); rolo.setWidget(host)
        self.box_log = QVBoxLayout(host); self.box_log.setContentsMargins(0, 0, 8, 0)
        # ZERO de propósito: o respiro vive dentro de cada _Entrada para o trilho não ter corte
        self.box_log.setSpacing(0)
        dv.addWidget(rolo, 1)
        cl.addWidget(dir_, 1)
        lay.addWidget(corpo, 1)

        # (rodapé removido — "Fechar" e o hint subiram para o header, §3.8)
        self._render()

    def _pintar_cab(self, cor):
        """Header recebe a tinta do estado a 10% (gradiente → transparente)."""
        self.cab.setStyleSheet(
            "QFrame#chCab{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 {T.rgba(cor, 0.10)}, stop:1 transparent);"
            f"border:none;border-bottom:1px solid {T.BORDER};}}")

    # ── dados ──
    def _val(self, k):
        """Precedência: o que a equipe gravou AQUI vence a subtarefa, que vence o bloco da
        observação (congelado na criação)."""
        return (clog.campos(self._ch).get(k)
                or self._sub.get(k) or self._bloco.get(k) or "").strip()

    def _ticket(self):
        return self._val("ticket")

    def _status(self):
        return self._val("status") or ""

    def _render(self):
        ents = clog.entradas(self._ch)
        self.lb_n.setText("%02d" % len(ents))
        while self.box_log.count():
            it = self.box_log.takeAt(0); w = it.widget()
            if w:
                w.deleteLater()
        if not ents:
            v = QLabel("nenhuma atualização registrada — use o campo acima para começar")
            v.setObjectName("meta"); v.setWordWrap(True)
            self.box_log.addWidget(v)
        for i, e in enumerate(ents):
            self.box_log.addWidget(_Entrada(e, recente=(i == 0),
                                            ultima=(i == len(ents) - 1)))
        # OBRIGATÓRIO. O QScrollArea é widgetResizable, então sem uma mola no fim as entradas
        # RACHAM a altura do viewport entre si: 3 atualizações de uma linha saíam com 178px cada,
        # o cartão verde virava um bloco vazio e o autor descia 130px abaixo do texto.
        # (`setAlignment(AlignTop)` no layout NÃO resolve — alinha o layout dentro do pai, não
        # os itens dentro do layout.)
        self.box_log.addStretch(1)

        st = self._status(); cor = _cor_status(st)
        self.lb_st.setText((st or "sem status").upper())
        self.lb_st.setStyleSheet(f"color:{cor};")
        self.pt.setCor(cor)          # nunca mais raio em QSS: fracionário é descartado
        self._pintar_cab(cor)
        dias = clog.dias_sem_atualizacao(self._ch)
        esp = self._val("esperando")
        p = []
        if esp:
            p.append("· aguardando %s" % esp)
        if dias is None:
            p.append("· sem atualização registrada")
        else:
            c = T.RED_TEXT if dias > 30 else (T.AMBER_TEXT if dias > 15 else T.TEXT_MUTED)
            p.append("· <span style='color:%s;font-weight:600'>%s</span>"
                     % (c, "hoje" if dias == 0 else "%d dias" % dias))
        self.lb_ctx.setText(" ".join(p))
        for cb, v in ((self.cb_status, st), (self.cb_esp, esp)):
            cb.blockSignals(True)
            i = cb.findData(v)
            cb.setCurrentIndex(i if i >= 0 else 0)
            cb.blockSignals(False)

    @slot_seguro
    def _salvar_situacao(self, *_):
        """Grava status/aguardando e REGISTRA a mudança na linha do tempo — é o que a equipe já
        fazia na planilha ('05/01 - Fabricante aprovou a garantia'), agora sem precisar escrever
        duas vezes."""
        if not self._ch:
            QMessageBox.warning(self, "Situação", "Chamado sem Ticket/RMA nem nº de OS."); return
        novo_st = self.cb_status.currentData() or ""
        novo_esp = self.cb_esp.currentData() or ""
        ant_st, ant_esp = self._status(), self._val("esperando")
        if novo_st == ant_st and novo_esp == ant_esp:
            self.hint.setText("nada mudou"); return
        clog.set_campos(self._ch, {"status": novo_st, "esperando": novo_esp})
        marcos = []
        if novo_st and novo_st != ant_st:
            marcos.append(f"Status: {ant_st or '—'} → {novo_st}")
        if novo_esp and novo_esp != ant_esp:
            marcos.append(f"Aguardando: {novo_esp}")
        if marcos:
            clog.adicionar(self._ch, " · ".join(marcos), autor=api.current_user_name())
        self.mudou = True
        self.hint.setText("situação salva")
        self._render()

    # ── ações ──
    @slot_seguro
    def _adicionar(self, *_):
        txt = self.ed_nova.toPlainText().strip()
        if not txt:
            return
        if not self._ch:
            QMessageBox.warning(self, "Atualização",
                                "Este chamado não tem Ticket/RMA nem número de OS — não consigo "
                                "identificar onde gravar o histórico."); return
        if clog.adicionar(self._ch, txt, autor=api.current_user_name()):
            self.ed_nova.clear(); self.mudou = True
            self._render()
            self.hint.setText("atualização registrada")
        else:
            QMessageBox.critical(self, "Atualização", "Não consegui gravar o histórico.")

    def _abrir_os(self):
        wid = self._d.get("id")
        if not wid:
            return
        from steps.os_detalhe import abrir_os_detalhe
        self.accept(); abrir_os_detalhe(self.parent(), wid, self._d.get("folio"))

    @slot_seguro
    def _marcar_aberto(self, *_):
        """Singrid, na reunião: 'quando eu abrir o chamado, eu não vou concluir ela, vou colocar
        como em progresso'. Antes de mudar o status, pede o que SÓ existe depois da abertura:
        o protocolo devolvido pelo fabricante e a data/hora. Na planilha esses são justamente
        'Ticket/RMA' (97% preenchido) e 'Data da abertura do chamado' (81%)."""
        wid = self._d.get("id")
        if not wid or self._w is not None:
            return
        dlg = _AberturaDialog(self, self._ticket())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._abertura = dlg.dados()
        tk = self._abertura["ticket"]
        # o ticket é a CHAVE do histórico: se o chamado começou sem ele, migra o que já existe
        if tk:
            nova = clog.chave(tk, self._d.get("folio"))
            if nova != self._ch:
                clog.migrar_chave(self._ch, nova)
                self._ch = nova
            self._sub = dict(self._sub); self._sub["ticket"] = tk
        self.b_aberto.setEnabled(False); self.hint.setText("mudando o status da OS…")
        self._w = ApiWorker(api.mudar_status_os, wid, 1)
        self._w.ok.connect(self._marcou); self._w.erro.connect(self._marcar_erro)
        self._w.start()

    @slot_seguro
    def _marcou(self, res):
        self._w = None; self.b_aberto.setEnabled(True)
        if not isinstance(res, dict) or not res.get("ok"):
            self.hint.setText("")
            QMessageBox.critical(self, "Status", str((res or {}).get("erro") or "não deu")); return
        self._d["status"] = "Em Processo"; self.mudou = True
        self.hint.setText("OS marcada como Em Processo")
        ab = getattr(self, "_abertura", {}) or {}
        tk = ab.get("ticket") or ""
        campos = {"status": cs.STATUS[1], "esperando": cs.ESPERANDO_PADRAO}
        if tk:
            campos["ticket"] = tk
        clog.set_campos(self._ch, campos)
        txt = "Chamado aberto no fabricante" + (f" — protocolo {tk}." if tk else ".")
        clog.adicionar(self._ch, txt, autor=api.current_user_name(), data=ab.get("quando"))
        self._render()

    @slot_seguro
    def _marcar_erro(self, m):
        self._w = None; self.b_aberto.setEnabled(True); self.hint.setText("")
        QMessageBox.critical(self, "Status", f"Não consegui mudar o status da OS:\n{m}")
