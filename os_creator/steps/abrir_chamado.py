"""Diálogo "Abrir chamado" — nasce do card da OS (rodapé), não da aba de Chamados.

Combinado da reunião de 23/07 (Ana Patrícia + Singrid): quem aciona o chamado é o SUPERVISOR,
no momento em que constata que o equipamento não voltou — antes ele só colava a etiqueta CHAMADOS
e avisava num grupo de WhatsApp, e a informação chegava incompleta na equipe de chamados
("senão a gente vai ficar no loop de coleta de informação"). Aqui ele é obrigado a entregar o
pacote que o fabricante exige, e a OS de chamado nasce FILHA desta OS (OS pai), mantendo
uma linha só do começo ao fim.

Os campos mudam por fabricante — ver `chamado_spec.CAMPOS_EXTRA`. Canadian Solar e STI são os
extremos (vídeos de medição / MAC + Modbus da TCU); Trina e Sungrow pedem quase só o comum.

DESIGN (revisão 2 do Chamados 1B, §3): esta é **a tela mais usada do fluxo** — o supervisor abre
uma por chamado, todo dia, enquanto o board e o detalhe servem um punhado de pessoas da equipe de
chamados. Foi a última a ser portada e devia ter sido a primeira.
O que saiu do tema antigo: os círculos verdes numerados (viraram `sectionLabel` + `Regua` — a
ordem vertical já é a ordem), os quatro cards azul-marinho (viraram blocos num `QFrame#panel`
único; moldura por seção fragmenta a tela em caixas que competem entre si) e a grade 5x2 de
botões de fabricante (virou faixa de pílulas de contorno com largura de conteúdo).
NADA de `Card`/`campo` do `steps.ui` aqui — é o que fazia o azul-marinho sobreviver, porque o
`QSS_FORM` estiliza classes que a folha 1B nem menciona.
"""
from PyQt6.QtCore import Qt, QDateTime, QRect, QSize, QPoint
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QWidget, QFrame, QLayout,
                             QLabel, QLineEdit, QTextEdit, QComboBox, QDateTimeEdit, QCheckBox,
                             QPushButton, QMessageBox, QScrollArea, QSizePolicy)

import api
import chamado_spec as cs
import chamado_tokens as T
import chamado_fontes as CF
from chamado_pecas import Regua, Combo
from workers import ApiWorker, slot_seguro
from steps.searchcombo import tornar_pesquisavel


def abrir_chamado(parent, os_detalhe: dict):
    """Abre o diálogo para a OS do card. `os_detalhe` = dict do api.get_os_detalhes (precisa de
    folio/ativo/usina). → folio da OS de chamado criada, ou None se cancelou."""
    dlg = AbrirChamadoDialog(parent, os_detalhe)
    dlg.showMaximized()          # tela cheia: são muitos campos e o operador não deve rolar à toa
    dlg.exec()
    return dlg.folio_criado


def _folha():
    from steps.chamados import _folha as f
    return f()


def _texto_flex(lb):
    from steps.chamados import _texto_flex as f
    return f(lb)


def _secao(txt):
    """Rótulo de seção do 1B — o mesmo de "DADOS" e "ATUALIZAÇÕES" no detalhe."""
    l = QLabel(txt.upper()); l.setObjectName("sectionLabel")
    CF.aplicar(l, T.TYPE["section"]["size"], QFont.Weight.DemiBold,
               tracking=T.TYPE["section"]["tracking"])
    return l


def _rot(txt, obrig=False):
    l = QLabel(txt.upper() + (" *" if obrig else ""))
    l.setStyleSheet("color:%s;" % (T.ACCENT if obrig else T.TEXT_MUTED))
    CF.aplicar(l, 10.5, QFont.Weight.DemiBold, tracking=0.6)
    return l


def _campo(rotulo, widget, obrig=False, ajuda=""):
    w = QWidget()
    v = QVBoxLayout(w); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(6)
    v.addWidget(_rot(rotulo, obrig)); v.addWidget(widget)
    if ajuda:
        a = _texto_flex(QLabel(ajuda))
        a.setStyleSheet(f"color:{T.TEXT_LABEL};font-size:10.5px;")
        v.addWidget(a)
    return w


class _Faixa(QLayout):
    """Layout que quebra a linha sozinho, respeitando a largura de CADA item.

    O Qt não traz um: com QGridLayout as pílulas voltariam a ter largura de coluna, que é
    exatamente o que a revisão mandou tirar ("largura pelo conteúdo, nunca fixa")."""
    def __init__(self, parent=None, espaco=8):
        super().__init__(parent)
        self._itens = []
        self._esp = espaco
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._itens.append(item)

    def count(self):
        return len(self._itens)

    def itemAt(self, i):
        return self._itens[i] if 0 <= i < len(self._itens) else None

    def takeAt(self, i):
        return self._itens.pop(i) if 0 <= i < len(self._itens) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._dispor(QRect(0, 0, w, 0), medir=True)

    def setGeometry(self, r):
        super().setGeometry(r)
        self._dispor(r, medir=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._itens:
            s = s.expandedTo(it.minimumSize())
        return s

    def _dispor(self, r, medir):
        x, y, alt_linha = r.x(), r.y(), 0
        for it in self._itens:
            larg = it.sizeHint().width()
            if x > r.x() and x + larg > r.right():
                x = r.x(); y += alt_linha + self._esp; alt_linha = 0
            if not medir:
                it.setGeometry(QRect(QPoint(x, y), it.sizeHint()))
            x += larg + self._esp
            alt_linha = max(alt_linha, it.sizeHint().height())
        return y + alt_linha - r.y()


class _Pilula(QPushButton):
    """Fabricante. Contorno puro, largura do conteúdo — mesma linguagem do chip do card."""
    def __init__(self, texto, on_click=None):
        super().__init__(texto)
        self.setCheckable(True)
        self.setObjectName("pill")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        if on_click:
            self.clicked.connect(lambda *_: on_click())


class AbrirChamadoDialog(QDialog):
    def __init__(self, parent, det: dict):
        super().__init__(parent)
        self._det = det if isinstance(det, dict) else {}
        self._fab = None
        self._campos = {}          # chave -> widget
        self._chips = {}
        self.folio_criado = None
        self._w = None

        folio = str(self._det.get("folio") or "")
        self.setWindowTitle(f"Abrir chamado — OS {folio}")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint)
        self.setMinimumSize(720, 680); self.setSizeGripEnabled(True)
        self.setStyleSheet(_folha() + "QDialog{background:%s;}" % T.BG)

        env = QVBoxLayout(self); env.setContentsMargins(14, 12, 14, 14)
        painel = QFrame(); painel.setObjectName("panel")
        env.addWidget(painel)
        lay = QVBoxLayout(painel); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        # ── cabeçalho: o alvo e o vínculo ──
        cab = QWidget()
        cv = QVBoxLayout(cab); cv.setContentsMargins(26, 22, 26, 18); cv.setSpacing(6)
        tit = QLabel("Abrir chamado"); tit.setObjectName("panelTitle")
        cv.addWidget(tit)
        alvo = _texto_flex(QLabel(self._det.get("ativo") or "—"))
        alvo.setStyleSheet(f"color:{T.TEXT};")
        CF.aplicar(alvo, T.TYPE["detail_title"]["size"], QFont.Weight.DemiBold)
        cv.addWidget(alvo)
        ctx = _texto_flex(QLabel(
            "%s · a OS de chamado nasce <b>filha da OS %s</b>, no mesmo ativo, "
            "com a etiqueta CHAMADOS." % (self._det.get("usina") or "—", folio)))
        ctx.setTextFormat(Qt.TextFormat.RichText)
        ctx.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:12px;")
        cv.addWidget(ctx)
        # aviso de que os campos vieram da inspeção — some quando o chamado não nasce de uma
        self.lb_prefill = _texto_flex(QLabel(""))
        self.lb_prefill.setStyleSheet("color:%s;font-size:12px;font-weight:600;" % T.GREEN)
        self.lb_prefill.setVisible(False)
        cv.addWidget(self.lb_prefill)
        lay.addWidget(cab)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        scroll.viewport().setStyleSheet("background:transparent;")
        body = QWidget(); scroll.setWidget(body)
        bl = QVBoxLayout(body); bl.setContentsMargins(26, 0, 26, 20); bl.setSpacing(0)

        # ── fabricante ──
        bl.addWidget(Regua(T.TEXT_BRIGHT, 0.10)); bl.addSpacing(20)
        bl.addWidget(_secao("Fabricante")); bl.addSpacing(11)
        faixa = QWidget()
        fl = _Faixa(faixa, espaco=8)
        for f in cs.FABRICANTES:
            ch = _Pilula(f, on_click=lambda ff=f: self._sel_fab(ff))
            self._chips[f] = ch
            fl.addWidget(ch)
        bl.addWidget(faixa)
        self.lbl_canal = _texto_flex(QLabel(""))
        self.lbl_canal.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:11.5px;")
        bl.addSpacing(9); bl.addWidget(self.lbl_canal)
        bl.addSpacing(22)

        # ── dados exigidos (dinâmico) ──
        bl.addWidget(Regua(T.TEXT_BRIGHT, 0.10)); bl.addSpacing(20)
        bl.addWidget(_secao("Dados exigidos pelo fabricante")); bl.addSpacing(11)
        self.box_campos = QVBoxLayout(); self.box_campos.setSpacing(14)
        bl.addLayout(self.box_campos)
        self.lbl_vazio = _texto_flex(QLabel("Escolha o fabricante acima para ver o que ele exige."))
        self.lbl_vazio.setStyleSheet(f"color:{T.TEXT_LABEL};font-size:12px;")
        self.box_campos.addWidget(self.lbl_vazio)
        bl.addSpacing(22)

        # ── equipe ──
        bl.addWidget(Regua(T.TEXT_BRIGHT, 0.10)); bl.addSpacing(20)
        bl.addWidget(_secao("Equipe de chamados")); bl.addSpacing(11)
        self.cb_resp = Combo(); self.cb_resp.addItem("— carregando responsáveis… —", None)
        self.cb_resp.currentIndexChanged.connect(self._upd)
        bl.addWidget(_campo("Responsável pelo chamado", self.cb_resp, obrig=True,
                            ajuda="quem vai abrir o chamado no fabricante e acompanhar"))
        bl.addSpacing(14)
        self.ed_obs = QLineEdit(); self.ed_obs.setPlaceholderText("observação livre (opcional)")
        bl.addWidget(_campo("Observação", self.ed_obs))
        bl.addStretch(1)
        lay.addWidget(scroll, 1)

        # ── rodapé: o aviso fica COLADO ao botão, não na outra ponta da tela ──
        rod = QHBoxLayout(); rod.setContentsMargins(26, 10, 26, 18); rod.setSpacing(12)
        b_can = QPushButton("Cancelar")
        b_can.setCursor(Qt.CursorShape.PointingHandCursor); b_can.clicked.connect(self.reject)
        rod.addWidget(b_can)
        self.hint = _texto_flex(QLabel(""))
        self.hint.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:11.5px;")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        # SEM addStretch antes: o hint usa `Ignored` na horizontal ("não peço largura"), então a
        # mola comeria tudo e o aviso sumiria — foi o que apagou os valores da lateral do detalhe.
        # Quem empurra para a direita é o alinhamento do próprio rótulo.
        rod.addWidget(self.hint, 1)
        self.btn = QPushButton("Abrir chamado"); self.btn.setObjectName("primary")
        self.btn.setEnabled(False)
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor); self.btn.clicked.connect(self._criar)
        rod.addWidget(self.btn)
        lay.addLayout(rod)

        tornar_pesquisavel(self.cb_resp)
        self._carregar_resp()
        self._upd()

    # ── fabricante ──
    def _sel_fab(self, fab):
        self._fab = fab
        for f, ch in self._chips.items():
            ch.setChecked(f == fab)          # exclusivo: só um fabricante por chamado
        self.lbl_canal.setText(f"Abertura: {cs.CANAL.get(fab, '—')}")
        self._montar_campos()
        self._upd()

    def _limpar_campos(self):
        self._campos.clear()
        while self.box_campos.count():
            it = self.box_campos.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)

    def _montar_campos(self):
        self._limpar_campos()
        for c in cs.campos(self._fab):
            w = self._widget_de(c)
            self._campos[c["chave"]] = w
            self.box_campos.addWidget(_campo(c["rotulo"], w, obrig=c["obrig"],
                                             ajuda=c.get("dica") or ""))
        self._preencher_da_inspecao()

    def _preencher_da_inspecao(self):
        """Semeia os campos com as respostas do técnico na OS de inspeção.

        É o ponto do fluxo em que o trabalho manual some: hoje a Singrid abre a OS, procura o
        serial numa foto e redigita tudo no formulário do fabricante. Quando o chamado nasce de uma
        OS de inspeção (`respostas` vem no `det`), serial, sintoma, ações, alarme, MAC, testes —
        tudo o que o técnico respondeu — já entra escrito. Continua editável: quem abre confere."""
        resp = self._det.get("respostas") or {}
        if not resp:
            return
        n = 0
        for chave, valor in resp.items():
            w = self._campos.get(chave)
            if w is None or not str(valor).strip():
                continue
            v = str(valor).strip()
            if isinstance(w, QTextEdit):
                if not w.toPlainText().strip():
                    w.setPlainText(v); n += 1
            elif isinstance(w, QComboBox):
                if not (w.currentText() or "").strip():
                    w.setCurrentText(v); n += 1
            elif isinstance(w, QLineEdit):
                if not w.text().strip():
                    w.setText(v); n += 1
            # data e 'evid' (lista de checkboxes) ficam de fora: a data já nasce da OS pai, e
            # casar texto livre com item de checklist erraria mais do que ajudaria
        if n:
            self._avisar_preenchido(n)

    def _avisar_preenchido(self, n):
        try:
            self.lb_prefill.setText(
                "%d campo(s) vieram preenchidos das subtarefas da OS de inspeção — confira antes "
                "de enviar." % n)
            self.lb_prefill.setVisible(True)
        except Exception:
            pass                       # aviso é cosmético; nunca impede a abertura do chamado

    def _widget_de(self, c):
        t = c["tipo"]
        if t == "longo":
            w = QTextEdit(); w.setFixedHeight(58); w.textChanged.connect(self._upd)
            return w
        if t == "data":
            # a falha é a MESMA ocorrência da OS pai → nasce com a data do evento dela, mas segue
            # editável (o supervisor pode ter constatado a falha em outro momento).
            ini = self._dt_evento() if c["chave"] == "data_falha" else None
            w = QDateTimeEdit(ini or QDateTime.currentDateTime())
            w.setDisplayFormat("dd/MM/yyyy HH:mm"); w.setCalendarPopup(True)
            w.dateTimeChanged.connect(lambda *_: self._upd())
            return w
        if t == "lista":
            w = Combo(); w.setEditable(True)          # editável: dá p/ digitar o que não está na lista
            w.addItem("")
            w.addItems(c.get("opcoes") or [])
            w.currentTextChanged.connect(lambda *_: self._upd())
            return w
        if t == "evid":
            w = QFrame(); w.setObjectName("uiGroup")
            v = QVBoxLayout(w); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(5)
            w._checks = []
            for o in (c.get("opcoes") or []):
                cb = QCheckBox(o)
                cb.toggled.connect(lambda *_: self._upd())
                v.addWidget(cb); w._checks.append(cb)
            return w
        w = QLineEdit(); w.textChanged.connect(self._upd)
        return w

    def _dt_evento(self):
        """Data/hora do incidente da OS pai como QDateTime (None se a OS não tiver)."""
        dt = api._parse_iso(self._det.get("event_date"))
        if not dt:
            return None
        return QDateTime(dt.year, dt.month, dt.day, dt.hour, dt.minute)

    def _valor(self, chave):
        w = self._campos.get(chave)
        if w is None:
            return ""
        if isinstance(w, QTextEdit):
            return w.toPlainText().strip()
        if isinstance(w, QDateTimeEdit):
            return w.dateTime().toString("dd/MM/yyyy HH:mm")
        if isinstance(w, QComboBox):
            return (w.currentText() or "").strip()
        if isinstance(w, QFrame) and hasattr(w, "_checks"):
            return [cb.text() for cb in w._checks if cb.isChecked()]
        if isinstance(w, QLineEdit):
            return w.text().strip()
        return ""

    def _dados(self):
        return {c["chave"]: self._valor(c["chave"]) for c in cs.campos(self._fab)}

    # ── responsável ──
    def _carregar_resp(self):
        self._wr = ApiWorker(api.get_responsaveis)
        self._wr.ok.connect(self._set_resp); self._wr.erro.connect(lambda *_: None)
        self._wr.start()

    @slot_seguro
    def _set_resp(self, pessoas):
        self._wr = None
        self.cb_resp.clear(); self.cb_resp.addItem("— selecione —", None)
        for p in (pessoas or []):
            self.cb_resp.addItem(p.get("name") or p.get("code") or "?", p)
        self._upd()

    # ── estado do botão ──
    @slot_seguro
    def _upd(self, *_):
        if not self._fab:
            self.btn.setEnabled(False); self.hint.setText("Escolha o fabricante."); return
        falta = cs.faltando(self._fab, self._dados())
        p = self.cb_resp.currentData()
        if not isinstance(p, dict):
            falta = falta + ["Responsável pelo chamado"]
        if falta:
            self.btn.setEnabled(False)
            self.hint.setText("Falta preencher: " + ", ".join(falta[:4])
                              + (f" e mais {len(falta) - 4}" if len(falta) > 4 else ""))
        else:
            self.btn.setEnabled(True)
            self.hint.setText("Tudo pronto — a OS nasce filha da OS "
                              f"{self._det.get('folio')}, com a etiqueta CHAMADOS.")

    # ── criar ──
    def _subs(self):
        """Subtarefas do spec → formato do Fracttal (1=Texto, 7=Lista)."""
        d = dict(self._dados()); d["status"] = cs.STATUS_INICIAL
        out = []
        for s in cs.subtarefas(self._fab, d):
            if s["tipo"] == "lista":
                out.append({"description": s["descricao"], "id_task_form_item_type": 7,
                            "dropdown_options": [{"description": o} for o in s.get("opcoes") or []],
                            "value": s.get("valor") or ""})
            else:
                out.append({"description": s["descricao"], "id_task_form_item_type": 1,
                            "value": s.get("valor") or ""})
        return out

    @slot_seguro
    def _criar(self, *_):
        p = self.cb_resp.currentData()
        if not isinstance(p, dict):
            QMessageBox.warning(self, "Chamado", "Escolha o responsável."); return
        d = self._dados()
        folio = str(self._det.get("folio") or "").strip()
        # a observação leva o texto pronto p/ o fabricante + o que o supervisor escrever
        nota = cs.texto_abertura(self._fab, d)
        extra = (self.ed_obs.text() or "").strip()
        if extra:
            nota += "\n\n" + extra
        dados = {"ticket": "", "serial": d.get("serial", ""), "status": cs.STATUS_INICIAL,
                 "fabricante": self._fab, "motivo": cs.motivo_titulo(self._fab, d), "resolucao": ""}
        self.btn.setEnabled(False); self.hint.setText("criando a OS de chamado…")
        self._w = ApiWorker(api.create_os_chamado, folio, p.get("id_personnel"),
                            p.get("code") or "", p.get("name") or "", False, nota,
                            "", cs.motivo_titulo(self._fab, d), self._subs(), dados)
        self._w.ok.connect(self._ok); self._w.erro.connect(self._erro)
        self._w.start()

    @slot_seguro
    def _erro(self, m):
        self._w = None; self.btn.setEnabled(True); self.hint.setText("")
        QMessageBox.critical(self, "Chamado", f"Não consegui criar a OS de chamado:\n{m}")

    @slot_seguro
    def _ok(self, res):
        self._w = None; self.btn.setEnabled(True); self.hint.setText("")
        if not isinstance(res, dict) or not res.get("ok"):
            QMessageBox.critical(self, "Chamado",
                                 str((res or {}).get("erro") or "não foi possível criar")); return
        self.folio_criado = res.get("folio")
        aviso = str(res.get("aviso") or "").strip()
        msg = f"OS de chamado {self.folio_criado} criada, filha da OS {self._det.get('folio')}."
        if not res.get("etiqueta_ok"):
            aviso = (aviso + " A etiqueta CHAMADOS não foi aplicada.").strip()
        QMessageBox.information(self, "Chamado", msg + (f"\n\n{aviso}" if aviso else ""))
        self.accept()
