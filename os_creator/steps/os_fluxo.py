"""Fluxo da OS — o card que abre no ícone de ramificação.

MOSTRA A CADEIA, e só ela: OS de origem → OS gerada → ..., centralizada. A faixa "todas as OS
deste ativo" existiu até 06/08 e saiu a pedido do Levi — ela era a rede de segurança para quando
não há vínculo (o pai/filho formal só existe em 7 de 300 OS de julho), mas roubava a atenção do
que a tela veio dizer. Sem vínculo, a tela agora diz isso em uma linha.

A cadeia sobe pelo `id_parent_wo` E pelo pai que só existe no bloco [CHAMADO] da observação, e
desce pelos filhos. Ordem pelo NÚMERO da OS (Levi, 05/08): o folio é sequencial com a criação e
ainda funciona quando a data vem vazia — o que acontece. Ver `api.fluxo_da_os`.
"""
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPainter, QPen, QColor, QFont
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
                             QScrollArea, QWidget, QSizePolicy)

import api
from steps.ui import BG, CARD, BORDER, GREEN, TEXT, MUTED, QSS_FORM
from workers import ApiWorker, slot_seguro

# cor por status — mesma leitura do resto do app (semáforo), não a paleta da marca
COR_STATUS = {"Concluída": "#3fb27f", "Em Processo": "#4a9eff",
              "Em Verificação": "#eb8b57", "Cancelada": "#e05454"}


def _lbl(t, cor=TEXT, px=13, peso=400, ital=False, esp=None):
    q = QLabel(str(t))
    q.setStyleSheet("color:%s;font-size:%spx;font-weight:%s;background:transparent;border:none;%s%s"
                    % (cor, px, peso, "font-style:italic;" if ital else "",
                       "letter-spacing:%spx;" % esp if esp else ""))
    return q


def _dt(iso, curto=True):
    s = api.fmt_data_br(iso) or ""
    return s[:11] if curto and len(s) > 11 else s


class _No(QFrame):
    """Um nó da cadeia = uma OS. Clique abre o card dela."""
    def __init__(self, no, atual, ao_clicar):
        super().__init__()
        self._no, self._cb = no, ao_clicar
        cs = COR_STATUS.get(no.get("status"), MUTED)
        self.setFixedSize(226, 132)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QFrame{background:%s;border:%dpx solid %s;border-radius:14px;}"
                           % (CARD, 3 if atual else 1, GREEN if atual else BORDER))
        v = QVBoxLayout(self); v.setContentsMargins(15, 12, 15, 12); v.setSpacing(5)
        topo = QHBoxLayout(); topo.setSpacing(8)
        topo.addWidget(_lbl(no.get("folio") or "—", TEXT, 23, 800)); topo.addStretch(1)
        if atual:
            aq = _lbl("ATUAL", GREEN, 10, 800, esp=0.6)
            aq.setStyleSheet(aq.styleSheet() + "background:rgba(166,226,46,0.15);"
                             "border-radius:7px;padding:3px 8px;")
            topo.addWidget(aq)
        v.addLayout(topo)
        v.addWidget(_lbl((no.get("tipo_tarefa") or "—")[:26], TEXT, 13, 600))
        d = _lbl((no.get("descricao") or "")[:30], MUTED, 11)
        v.addWidget(d)
        v.addStretch(1)
        base = QHBoxLayout(); base.setSpacing(7)
        pt = QLabel(); pt.setFixedSize(8, 8)
        # `border:none` NÃO é decorativo: QLabel herda de QFrame, então a regra `QFrame{border:...}`
        # do card vaza para cá e pinta um ponto de 8px inteiro com a cor da BORDA do card — o
        # status virava verde em OS cancelada. Mesma armadilha do warnBox no os_detalhe.
        pt.setStyleSheet("background:%s;border:none;border-radius:4px;" % cs)
        base.addWidget(pt); base.addWidget(_lbl(no.get("status") or "—", cs, 11.5, 700))
        base.addStretch(1)
        base.addWidget(_lbl(_dt(no.get("event_date") or no.get("criacao")), MUTED, 11))
        v.addLayout(base)

    def mousePressEvent(self, e):
        if self._cb and self._no.get("id"):
            self._cb(self._no)


class _Seta(QWidget):
    """Conector entre dois nós da cadeia."""
    def __init__(self, rotulo=""):
        super().__init__()
        self.rot = rotulo
        self.setFixedSize(96, 132)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = 66
        p.setPen(QPen(QColor(BORDER), 2))
        p.drawLine(4, y, 78, y)
        p.setPen(QPen(QColor(GREEN), 2))
        for i in range(7):
            p.drawLine(78 - i, y - i, 78 - i, y + i)
        if self.rot:
            p.setPen(QColor(MUTED))
            f = QFont(); f.setPixelSize(10); f.setBold(True); p.setFont(f)
            p.drawText(QRectF(0, y - 30, 96, 18), Qt.AlignmentFlag.AlignCenter, self.rot)
        p.end()


class FluxoDialog(QDialog):
    """Card do fluxo. Carrega em worker — são até 3 rodadas de RPC e travaria a interface."""
    def __init__(self, parent, id_work_order, folio=""):
        super().__init__(parent)
        self._wo, self._folio = id_work_order, str(folio or "")
        self._w = None
        self.setWindowTitle("Fluxo da OS %s" % self._folio)
        self.setModal(True)
        # Altura: cabeçalho (~62) + faixa dos nós (150) + margens. Sem folga extra — a janela é
        # de um conteúdo só e não cresce (Levi, 06/08). Largura acompanha a cadeia de até 3 nós
        # (226 cada + 96 de seta); mais que isso a faixa rola na horizontal.
        self.setMinimumSize(760, 312)
        self.resize(1060, 330)
        self.setStyleSheet(QSS_FORM + "QDialog{background:%s;}" % BG)
        self.v = QVBoxLayout(self); self.v.setContentsMargins(24, 18, 24, 16); self.v.setSpacing(12)
        self._cab()
        self.corpo = QVBoxLayout(); self.corpo.setSpacing(16)
        self.v.addLayout(self.corpo)
        self.v.addStretch(1)
        self.hint = _lbl("carregando o fluxo…", MUTED, 12.5, 400, True)
        self.corpo.addWidget(self.hint)
        self._carregar()

    def _cab(self):
        cab = QHBoxLayout(); cab.setSpacing(14)
        cx = QVBoxLayout(); cx.setSpacing(3)
        self.tit = _lbl("Fluxo da OS %s" % self._folio, TEXT, 21, 800)
        self.sub = _lbl("—", MUTED, 13)
        cx.addWidget(self.tit); cx.addWidget(self.sub)
        cab.addLayout(cx); cab.addStretch(1)
        b = QPushButton("Fechar"); b.setObjectName("pGhost"); b.setFixedHeight(36)
        b.clicked.connect(self.reject)
        cab.addWidget(b)
        self.v.addLayout(cab)
        s = QFrame(); s.setFixedHeight(1); s.setStyleSheet("background:%s;border:none;" % BORDER)
        self.v.addWidget(s)

    def _carregar(self):
        self._w = ApiWorker(api.fluxo_da_os, self._wo, 0)   # 0 = sem histórico do ativo
        self._w.ok.connect(self._pronto); self._w.erro.connect(self._falhou)
        self._w.start()

    @slot_seguro
    def _falhou(self, m):
        self._w = None
        self.hint.setText("não consegui montar o fluxo: %s" % str(m)[:140])

    @slot_seguro
    def _pronto(self, fx):
        self._w = None
        while self.corpo.count():
            it = self.corpo.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
            elif it.layout():
                self._limpar(it.layout())
        ativo = fx.get("ativo") or {}
        # DEDUPLICA: no item-usina o nome do ativo JÁ é o nome da planta, e o subtítulo saía
        # "Axis - Marialva 1 - PR Marialva Paraná Brasil · Axis - Marialva 1 - PR · Axis".
        partes, vistos = [], set()
        for x in (ativo.get("nome"), ativo.get("usina"), ativo.get("cliente")):
            x = str(x or "").strip()
            n = x.lower()
            if x and not any(n in v or v in n for v in vistos):
                partes.append(x); vistos.add(n)
        self.sub.setText("  ·  ".join(partes) or "—")

        cadeia = fx.get("cadeia") or []
        atual_id = (fx.get("atual") or {}).get("id")
        # CENTRALIZADA: stretch dos DOIS lados (Levi, 06/08). Só à direita, a cadeia colava na
        # margem esquerda e o vazio ficava todo de um lado — com 2 ou 3 nós isso é a tela inteira.
        lin = QHBoxLayout(); lin.setSpacing(0)
        lin.addStretch(1)
        for i, no in enumerate(cadeia):
            lin.addWidget(_No(no, no.get("id") == atual_id, self._abrir))
            if i < len(cadeia) - 1:
                lin.addWidget(_Seta("gerou"))
        lin.addStretch(1)
        env = QWidget(); env.setLayout(lin)
        # o QWidget interno do QScrollArea pinta a cor de janela por padrão — era o retângulo mais
        # escuro atrás dos cards. O seletor filho pega o viewport E o `env`.
        env.setStyleSheet("background:transparent;")
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setWidget(env)
        sc.setFixedHeight(150)
        sc.setStyleSheet("QScrollArea{background:transparent;border:none;}"
                         "QScrollArea > QWidget > QWidget{background:transparent;}")
        sc.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.corpo.addWidget(sc)
        if len(cadeia) <= 1:
            aviso = _lbl("Esta OS não tem outra ligada a ela — nem como pai, nem como filha.",
                         MUTED, 12, 400, True)
            aviso.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.corpo.addWidget(aviso)

    def _limpar(self, lay):
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
            elif it.layout():
                self._limpar(it.layout())

    def _abrir(self, no):
        """Clique num nó → abre o card daquela OS. Fecha este para não empilhar janela sobre janela."""
        from steps.os_detalhe import abrir_os_detalhe
        self.accept()
        abrir_os_detalhe(self.parent(), no.get("id"), no.get("folio"))


def abrir_fluxo_os(parent, id_work_order, folio=""):
    return FluxoDialog(parent, id_work_order, folio).exec()
