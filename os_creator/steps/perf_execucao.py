"""Cronômetro da tarefa — iniciar, pausar, retomar e concluir, do jeito que o Fracttal registra.

POR QUE ISTO EXISTE: o "fazendo agora" do quadro dependia do analista LEMBRAR de colar a
etiqueta "Atividade em execução" no Fracttal web. Disciplina manual é exatamente o que fez 42
das 44 OS atribuídas a analistas terminarem canceladas. Aqui ele clica em Iniciar e o próprio
Fracttal cronometra.

E o tempo passa a ser REAL: a resposta traz os segmentos do ciclo com `duration_seconds` cada,
então dá para somar só o que foi trabalhado, sem as pausas. Conferido contra uma execução de
verdade (tarefa 55869196): 27 s trabalhados + 3 s pausados = 30 s, contra 31 s de relógio.
O tempo que o quadro mostrava antes era "fim menos criação", que conta noite e fim de semana.

A ASSINATURA do fluxo web (`work_orders_sign_update`) NÃO é chamada: o servidor não exige —
o `api.concluir_os` fecha OS sem ela desde sempre — e assinatura gerada pelo app seria registro
falso de que alguém assinou.
"""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
                             QComboBox, QLineEdit, QMessageBox, QWidget)

import api
import chamado_tokens as T
import chamado_fontes as CF
from chamado_pecas import Ponto, Regua
from workers import ApiWorker, slot_seguro
from steps.chamados import _folha, _texto_flex


COR_ESTADO = {"rodando": T.BLUE, "pausada": T.AMBER, "parada": T.DOT_IDLE}
ROTULO = {"rodando": "EM EXECUÇÃO", "pausada": "PAUSADA", "parada": "PARADA"}


def fmt_seg(s):
    """Segundos → '1h 12min' / '12min' / '45s'. Curto porque cabe num card."""
    s = int(s or 0)
    if s < 60:
        return "%ds" % s
    m, seg = divmod(s, 60)
    if m < 60:
        return "%dmin" % m
    h, m = divmod(m, 60)
    return "%dh %dmin" % (h, m) if m else "%dh" % h


class ExecucaoDialog(QDialog):
    def __init__(self, parent, d):
        super().__init__(parent)
        self._d = d or {}
        self._tid = None
        self._est = {"estado": "parada", "trabalhado_s": 0, "pausado_s": 0, "motivo": ""}
        self._w = None
        self.mudou = False

        self.setWindowTitle("Execução — OS %s" % (self._d.get("folio") or ""))
        self.setMinimumWidth(520)
        self.setStyleSheet(_folha() + "QDialog{background:%s;}" % T.BG)
        env = QVBoxLayout(self); env.setContentsMargins(14, 12, 14, 14)
        painel = QFrame(); painel.setObjectName("panel"); env.addWidget(painel)
        v = QVBoxLayout(painel); v.setContentsMargins(24, 20, 24, 18); v.setSpacing(12)

        lin = QHBoxLayout(); lin.setSpacing(9 - Ponto.BLEED)
        self.pt = Ponto(T.DOT_IDLE, T.DOT["status"])
        lin.addWidget(self.pt)
        self.lb_est = QLabel("—"); self.lb_est.setObjectName("colHeader")
        CF.aplicar(self.lb_est, T.TYPE["col_header"]["size"], QFont.Weight.Bold,
                   tracking=T.TYPE["col_header"]["tracking"])
        lin.addWidget(self.lb_est); lin.addStretch(1)
        v.addLayout(lin)

        tit = _texto_flex(QLabel(self._d.get("descricao") or "—"))
        tit.setObjectName("cardTitle")
        v.addWidget(tit)
        loc = _texto_flex(QLabel(" · ".join(x for x in (self._d.get("usina"),
                                                        self._d.get("cliente")) if x and x != "—")))
        loc.setObjectName("secondary")
        v.addWidget(loc)
        v.addWidget(Regua(T.TEXT_BRIGHT, 0.10))

        kp = QHBoxLayout(); kp.setSpacing(26)
        self.kpis = {}
        for chave, rot in (("trab", "trabalhado"), ("paus", "pausado")):
            bx = QVBoxLayout(); bx.setSpacing(2)
            val = QLabel("—")
            CF.aplicar(val, 20, QFont.Weight.Bold, mono=True, tracking=-0.8)
            rl = QLabel(rot); rl.setObjectName("secondary")
            bx.addWidget(val); bx.addWidget(rl)
            self.kpis[chave] = val
            kp.addLayout(bx)
        kp.addStretch(1)
        v.addLayout(kp)

        self.lb_motivo = _texto_flex(QLabel(""))
        self.lb_motivo.setStyleSheet(f"color:{T.AMBER_TEXT};font-size:11.5px;")
        v.addWidget(self.lb_motivo)
        v.addWidget(Regua(T.TEXT_BRIGHT, 0.10))

        self.hint = QLabel("lendo o cronômetro…")
        self.hint.setStyleSheet(f"color:{T.TEXT_FAINT};font-size:11.5px;")
        rod = QHBoxLayout(); rod.setSpacing(9)
        # "Fechar" na MESMA linha, à esquerda: numa linha própria ele comia uma faixa inteira
        # do diálogo sem dizer nada
        b_f = QPushButton("Fechar"); b_f.clicked.connect(self.accept)
        b_f.setCursor(Qt.CursorShape.PointingHandCursor)
        rod.addWidget(b_f)
        rod.addWidget(self.hint, 1)
        self.b_pausar = QPushButton("Pausar")
        self.b_pausar.clicked.connect(self._pausar)
        self.b_principal = QPushButton("Iniciar"); self.b_principal.setObjectName("primary")
        self.b_principal.clicked.connect(self._principal)
        self.b_concluir = QPushButton("Concluir")
        self.b_concluir.clicked.connect(self._concluir)
        for b in (self.b_pausar, self.b_concluir, self.b_principal):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setEnabled(False)
            rod.addWidget(b)
        v.addLayout(rod)
        self._carregar()

    # ── leitura ──
    def _carregar(self):
        if self._w is not None:
            return
        self.hint.setText("lendo o cronômetro…")
        for b in (self.b_pausar, self.b_concluir, self.b_principal):
            b.setEnabled(False)
        self._w = ApiWorker(self._ler)
        self._w.ok.connect(self._chegou); self._w.erro.connect(self._falhou)
        self._w.start()

    def _ler(self):
        """A execução é da TAREFA, não da OS — resolve o id da tarefa antes."""
        tid = self._tid or api.id_tarefa_da_os(self._d.get("id"))
        return {"tid": tid, "est": api.execucao_atual(tid)}

    @slot_seguro
    def _falhou(self, m):
        self._w = None
        self.hint.setText("")
        QMessageBox.critical(self, "Execução", "Não consegui ler o cronômetro:\n%s" % m)

    @slot_seguro
    def _chegou(self, r):
        self._w = None
        self._tid = (r or {}).get("tid")
        self._est = (r or {}).get("est") or self._est
        self._pintar()

    def _pintar(self):
        e = self._est.get("estado", "parada")
        cor = COR_ESTADO.get(e, T.DOT_IDLE)
        self.lb_est.setText(ROTULO.get(e, "—"))
        self.lb_est.setStyleSheet("color:%s;" % (T.TEXT_MUTED if e == "parada" else cor))
        self.pt.setCor(cor)          # `Ponto` já troca a cor sem recriar o widget
        self.kpis["trab"].setText(fmt_seg(self._est.get("trabalhado_s")))
        self.kpis["paus"].setText(fmt_seg(self._est.get("pausado_s")))
        mot = self._est.get("motivo") or ""
        self.lb_motivo.setText(("pausada: " + mot) if mot else "")
        self.hint.setText("" if self._tid else "esta OS não tem tarefa — não dá para cronometrar")

        tem = bool(self._tid)
        if e == "rodando":
            self.b_principal.setText("Retomar"); self.b_principal.setEnabled(False)
            self.b_pausar.setEnabled(tem); self.b_concluir.setEnabled(tem)
        elif e == "pausada":
            self.b_principal.setText("Retomar"); self.b_principal.setEnabled(tem)
            self.b_pausar.setEnabled(False); self.b_concluir.setEnabled(tem)
        else:
            self.b_principal.setText("Iniciar"); self.b_principal.setEnabled(tem)
            self.b_pausar.setEnabled(False); self.b_concluir.setEnabled(False)

    # ── ações ──
    def _acao(self, fn, *a):
        if self._w is not None:
            return
        for b in (self.b_pausar, self.b_concluir, self.b_principal):
            b.setEnabled(False)
        self.hint.setText("gravando no Fracttal…")
        self._w = ApiWorker(fn, *a)
        self._w.ok.connect(self._acao_ok); self._w.erro.connect(self._falhou)
        self._w.start()

    @slot_seguro
    def _acao_ok(self, res):
        self._w = None
        if isinstance(res, dict) and res.get("ok") is False:
            self.hint.setText("")
            QMessageBox.critical(self, "Execução", str(res.get("erro") or "não deu"))
            self._pintar(); return
        # o cronômetro vale; só a etiqueta falhou → o card não muda de coluna. Melhor dizer.
        if isinstance(res, dict) and res.get("etiqueta_erro"):
            QMessageBox.warning(self, "Execução", "O cronômetro rodou, mas não consegui mudar a "
                                "coluna do card:\n%s" % res["etiqueta_erro"])
        self.mudou = True
        self._carregar()               # relê o estado em vez de supor o que aconteceu

    @slot_seguro
    def _principal(self, *_):
        if self._est.get("estado") == "pausada":
            self._acao(api.retomar_execucao, self._tid)
        else:
            self._acao(api.iniciar_execucao_os, self._d.get("id"), self._tid)

    @slot_seguro
    def _pausar(self, *_):
        dlg = _MotivoPausa(self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.id_motivo:
            return
        self._acao(api.pausar_execucao, self._tid, dlg.id_motivo, dlg.nota)

    @slot_seguro
    def _concluir(self, *_):
        if QMessageBox.question(self, "Concluir execução",
                                "Parar o cronômetro desta tarefa?\n\nIsso NÃO conclui a OS — só "
                                "encerra o tempo de trabalho."
                                ) != QMessageBox.StandardButton.Yes:
            return
        self._acao(api.finalizar_execucao_os, self._d.get("id"), self._tid)


class _MotivoPausa(QDialog):
    """O Fracttal exige um motivo para pausar — são 11 cadastrados. A nota é livre."""
    def __init__(self, parent):
        super().__init__(parent)
        self.id_motivo = None
        self.nota = ""
        self._w = None
        self.setWindowTitle("Pausar")
        self.setMinimumWidth(440)
        self.setStyleSheet(_folha() + "QDialog{background:%s;}" % T.BG)
        env = QVBoxLayout(self); env.setContentsMargins(14, 12, 14, 14)
        painel = QFrame(); painel.setObjectName("panel"); env.addWidget(painel)
        v = QVBoxLayout(painel); v.setContentsMargins(24, 20, 24, 18); v.setSpacing(12)
        t = QLabel("Por que está pausando?"); t.setObjectName("panelTitle")
        v.addWidget(t)
        self.cb = QComboBox(); self.cb.addItem("— carregando motivos… —", None)
        v.addWidget(self.cb)
        self.ed = QLineEdit(); self.ed.setPlaceholderText("observação (opcional)")
        v.addWidget(self.ed)
        rod = QHBoxLayout(); rod.addStretch(1)
        b_c = QPushButton("Cancelar"); b_c.clicked.connect(self.reject)
        self.b_ok = QPushButton("Pausar"); self.b_ok.setObjectName("primary")
        self.b_ok.setEnabled(False); self.b_ok.clicked.connect(self._ok)
        rod.addWidget(b_c); rod.addWidget(self.b_ok)
        v.addLayout(rod)
        self._w = ApiWorker(api.motivos_pausa)
        self._w.ok.connect(self._chegou); self._w.erro.connect(lambda *_: self.reject())
        self._w.start()

    @slot_seguro
    def _chegou(self, motivos):
        self._w = None
        self.cb.clear()
        for m in (motivos or []):
            self.cb.addItem(m.get("descricao") or "?", m.get("id"))
        self.b_ok.setEnabled(self.cb.count() > 0)

    def _ok(self):
        self.id_motivo = self.cb.currentData()
        self.nota = self.ed.text().strip()
        if not self.id_motivo:
            QMessageBox.information(self, "Pausar", "Escolha o motivo."); return
        self.accept()


def abrir_execucao(parent, d):
    """→ True se algo mudou (para o quadro recarregar)."""
    dlg = ExecucaoDialog(parent, d)
    dlg.exec()
    return dlg.mudou


# ══════════════════════════════════════════════════════════════════════════════
# CONTROLE NO CARD — ícone + cronômetro correndo
#
# Pedido do Levi: "nesse card já venha a opção de iniciar e terminar a atividade, pode ser por
# ícone e um cronômetro". O diálogo continua existindo para PAUSAR (que exige escolher motivo);
# aqui ficam as duas ações do dia a dia.
#
# Os ícones são PINTADOS, não SVG do `steps.ui`: o conjunto do app não tem play/pause/stop, e
# triângulo/barras/quadrado são três linhas de QPainter. Segue a regra do projeto — caixa se
# estiliza com QSS, marca se pinta.
# ══════════════════════════════════════════════════════════════════════════════
from PyQt6.QtCore import QRectF, QPointF
from PyQt6.QtGui import QPainter, QColor, QPolygonF
from PyQt6.QtWidgets import QAbstractButton


class IconeExec(QAbstractButton):
    """Botão redondo com o símbolo pintado. forma: 'play' | 'pause' | 'stop'."""
    LADO = 26

    def __init__(self, forma, cor, dica="", parent=None):
        super().__init__(parent)
        self._forma = forma
        self._cor = cor
        self.setFixedSize(self.LADO, self.LADO)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if dica:
            self.setToolTip(dica)

    def definir(self, forma, cor, dica=""):
        self._forma, self._cor = forma, cor
        if dica:
            self.setToolTip(dica)
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cor = QColor(self._cor)
        if not self.isEnabled():
            cor.setAlpha(70)
        # anel de fundo — dá alvo de clique sem precisar de moldura em QSS
        p.setPen(Qt.PenStyle.NoPen)
        fundo = QColor(cor); fundo.setAlpha(38 if self.underMouse() else 22)
        p.setBrush(fundo)
        p.drawEllipse(QRectF(0, 0, self.LADO, self.LADO))
        p.setBrush(cor)
        c = self.LADO / 2.0
        if self._forma == "play":
            # triângulo levemente deslocado à direita: centrado pela ÁREA, o play parece torto
            t = QPolygonF([QPointF(c - 3.2, c - 5.2), QPointF(c - 3.2, c + 5.2),
                           QPointF(c + 5.4, c)])
            p.drawPolygon(t)
        elif self._forma == "pause":
            p.drawRoundedRect(QRectF(c - 4.6, c - 5.0, 3.4, 10.0), 1.2, 1.2)
            p.drawRoundedRect(QRectF(c + 1.2, c - 5.0, 3.4, 10.0), 1.2, 1.2)
        else:                                    # stop
            p.drawRoundedRect(QRectF(c - 4.4, c - 4.4, 8.8, 8.8), 1.6, 1.6)
        p.end()


class _ObsConclusao(QDialog):
    """Pergunta a observação antes de FECHAR a OS. É a última chance de registrar o que foi feito,
    e o texto do aviso é forte de propósito: concluir OS no Fracttal é irreversível."""
    def __init__(self, parent, folio):
        super().__init__(parent)
        self.texto = ""
        self.setWindowTitle("Concluir OS %s" % (folio or ""))
        self.setMinimumWidth(430)
        self.setStyleSheet(_folha())
        v = QVBoxLayout(self); v.setContentsMargins(20, 18, 20, 16); v.setSpacing(11)
        t = QLabel("Concluir a OS %s" % (folio or "")); CF.aplicar(t, 15, QFont.Weight.Bold)
        v.addWidget(t)
        av = QLabel("Fecha a OS no Fracttal. <b>Não dá para reabrir.</b>")
        av.setWordWrap(True); av.setStyleSheet("color:%s;font-size:12px;" % T.AMBER_TEXT)
        v.addWidget(av); v.addWidget(Regua(T.TEXT_BRIGHT, 0.10))
        lb = QLabel("O que foi feito"); lb.setStyleSheet("color:%s;font-size:12px;" % T.TEXT_LABEL)
        v.addWidget(lb)
        self.ed = QLineEdit(); self.ed.setPlaceholderText("observação da conclusão (opcional)")
        v.addWidget(self.ed)
        nota = QLabel("A observação fica registrada no app, nesta máquina — a API do Fracttal "
                      "não tem método para escrever na observação de uma OS já criada.")
        nota.setWordWrap(True); nota.setStyleSheet("color:%s;font-size:11px;" % T.TEXT_MUTED)
        v.addWidget(nota)
        lin = QHBoxLayout(); lin.addStretch(1)
        b_nao = QPushButton("Cancelar"); b_nao.clicked.connect(self.reject)
        b_sim = QPushButton("Concluir OS"); b_sim.setObjectName("primary")
        b_sim.clicked.connect(self._ok)
        lin.addWidget(b_nao); lin.addWidget(b_sim)
        v.addLayout(lin)

    @slot_seguro
    def _ok(self, *_):
        self.texto = self.ed.text().strip()
        self.accept()


class BotaoConcluir(QPushButton):
    """Fecha a OS direto do card, com observação. Fica ao lado do cronômetro porque é o fim do
    mesmo gesto: comecei, trabalhei, acabou. Sem ele a pessoa tinha de ir ao Fracttal web."""
    def __init__(self, d, on_mudou=None, parent=None):
        super().__init__("Concluir", parent)
        self._d = d or {}
        self._on_mudou = on_mudou
        self._w = None
        self._obs = ""
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # deixa explícito que NÃO precisa pausar antes: concluir já encerra o cronômetro
        self.setToolTip("Concluir a OS no Fracttal (irreversível).\n"
                        "Encerra o cronômetro sozinho — não precisa pausar antes.")
        CF.aplicar(self, 10.5, QFont.Weight.DemiBold)     # 1B: cabe ao lado do relógio em 208px
        # inline e não por objectName: o botão do card é BAIXO (cabe ao lado do cronômetro de 26px),
        # e a regra geral de QPushButton da folha é de botão de diálogo.
        self.setStyleSheet("QPushButton{background:transparent;border:1px solid %s;"
                           "border-radius:7px;padding:3px 8px;color:%s;min-height:0px;}"
                           "QPushButton:hover{border-color:%s;color:%s;}"
                           % (T.BORDER, T.TEXT_MUTED, T.GREEN, T.GREEN))
        self.clicked.connect(self._clicou)

    @slot_seguro
    def _clicou(self, *_):
        if self._w is not None:
            return
        dlg = _ObsConclusao(self, self._d.get("folio"))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        # a observação só entra no log DEPOIS que o Fracttal confirmar. Gravar antes gerava um
        # "Feito" por tentativa: o Levi tentou 4× na OS 10215, viu 4 linhas no histórico e a OS
        # continuava aberta — o log parecia dizer que tinha concluído.
        self._obs = dlg.texto
        self.setEnabled(False); self.setText("concluindo…")
        # a tarefa é resolvida DENTRO do worker: `id_tarefa_da_os` é chamada de rede e travaria
        # a interface se rodasse aqui.
        self._w = ApiWorker(api.concluir_os_analise, self._d.get("id"), None, self._obs)
        self._w.ok.connect(self._pronto)
        self._w.erro.connect(self._falhou)
        self._w.start()

    @slot_seguro
    def _pronto(self, res):
        self._w = None
        self.setText("Concluir"); self.setEnabled(True)
        if isinstance(res, dict) and res.get("ok") is False:
            QMessageBox.critical(self, "Concluir OS", str(res.get("erro") or "não deu"))
            return
        import perf_notas as pn
        try:
            autor = api.current_user_name() or ""
        except Exception:
            autor = ""
        pn.adicionar(self._d.get("folio"), self._obs, autor)
        if self._on_mudou:
            self._on_mudou()

    @slot_seguro
    def _falhou(self, m):
        self._w = None
        self.setText("Concluir"); self.setEnabled(True)
        QMessageBox.critical(self, "Concluir OS", str(m))


def fmt_relogio(s):
    """Segundos → 'HH:MM:SS' se passar de uma hora, senão 'MM:SS'. Formato de cronômetro:
    largura estável, para o card não pular a cada segundo."""
    s = max(0, int(s or 0))
    h, r = divmod(s, 3600)
    m, seg = divmod(r, 60)
    return "%d:%02d:%02d" % (h, m, seg) if h else "%02d:%02d" % (m, seg)


class ControleExec(QWidget):
    """Ícone + cronômetro no card. Lê o estado sozinho e conta em tempo real quando roda.

    O tempo mostrado é o TRABALHADO: parte do que o Fracttal já acumulou e soma os segundos
    desde a última retomada. Pausa não conta."""
    def __init__(self, d, on_mudou=None, compacto=False, parent=None):
        super().__init__(parent)
        self._d = d or {}
        self._on_mudou = on_mudou
        self._tid = None
        self._est = None
        self._base = 0            # segundos já acumulados quando a leitura chegou
        self._t0 = None           # quando começou a contar localmente
        self._w = None

        h = QHBoxLayout(self); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(7)
        self.b_play = IconeExec("play", T.TEXT_MUTED, "Iniciar")
        self.b_play.clicked.connect(self._play)
        self.b_stop = IconeExec("stop", T.TEXT_MUTED, "Concluir a atividade")
        self.b_stop.clicked.connect(self._stop)
        self.lb = QLabel("--:--")
        CF.aplicar(self.lb, 12.5, QFont.Weight.Bold, mono=True)
        self.lb.setStyleSheet(f"color:{T.TEXT_FAINT};")
        h.addWidget(self.b_play); h.addWidget(self.lb)
        if not compacto:
            h.addWidget(self.b_stop)
        else:
            # 1B: em 241px de coluna o rodapé com play+relógio+parar+Concluir pede 289px e estoura.
            # Parar o cronômetro volta a viver no ExecucaoDialog; no card ficam iniciar/pausar e
            # concluir a OS. O botão continua EXISTINDO porque o `_pintar` mexe nele.
            self.b_stop.hide()
        for b in (self.b_play, self.b_stop):
            b.setEnabled(False)

        self._tick = QTimer(self); self._tick.setInterval(1000)
        self._tick.timeout.connect(self._pintar_relogio)
        self._carregar()

    # ── leitura ──
    def _carregar(self):
        if self._w is not None:
            return
        self._w = ApiWorker(self._ler)
        self._w.ok.connect(self._chegou)
        self._w.erro.connect(lambda *_: setattr(self, "_w", None))
        self._w.start()

    def _ler(self):
        tid = self._tid or api.id_tarefa_da_os(self._d.get("id"))
        return {"tid": tid, "est": api.execucao_atual(tid)}

    @slot_seguro
    def _chegou(self, r):
        self._w = None
        self._tid = (r or {}).get("tid")
        self._est = (r or {}).get("est") or {}
        self._base = int(self._est.get("trabalhado_s") or 0)
        import time as _t
        self._t0 = _t.monotonic() if self._est.get("estado") == "rodando" else None
        self._pintar()

    def _pintar(self):
        e = (self._est or {}).get("estado", "parada")
        tem = bool(self._tid)
        if e == "rodando":
            self.b_play.definir("pause", T.BLUE, "Pausar (pede o motivo)")
            self.b_play.setEnabled(tem); self.b_stop.setEnabled(tem)
            self.b_stop.definir("stop", T.TEXT_MUTED, "Concluir a atividade")
            self._tick.start()
        elif e == "pausada":
            self.b_play.definir("play", T.AMBER, "Retomar")
            self.b_play.setEnabled(tem); self.b_stop.setEnabled(tem)
            self.b_stop.definir("stop", T.TEXT_MUTED, "Concluir a atividade")
            self._tick.stop()
        else:
            self.b_play.definir("play", T.ACCENT, "Iniciar" if tem else "esta OS não tem tarefa")
            self.b_play.setEnabled(tem)
            self.b_stop.definir("stop", T.TEXT_LABEL, "nada em andamento")
            self.b_stop.setEnabled(False)
            self._tick.stop()
        self._pintar_relogio()

    def _pintar_relogio(self):
        e = (self._est or {}).get("estado", "parada")
        seg = self._base
        if e == "rodando" and self._t0 is not None:
            import time as _t
            seg += int(_t.monotonic() - self._t0)
        if e == "parada" and not seg:
            self.lb.setText("--:--")
            self.lb.setStyleSheet(f"color:{T.TEXT_LABEL};")
            return
        self.lb.setText(fmt_relogio(seg))
        cor = {"rodando": T.BLUE_TEXT, "pausada": T.AMBER_TEXT}.get(e, T.TEXT_MUTED)
        self.lb.setStyleSheet(f"color:{cor};")

    # ── ações ──
    def _acao(self, fn, *a):
        if self._w is not None:
            return
        for b in (self.b_play, self.b_stop):
            b.setEnabled(False)
        self._tick.stop()
        self._w = ApiWorker(fn, *a)
        self._w.ok.connect(self._acao_ok)
        self._w.erro.connect(self._acao_erro)
        self._w.start()

    @slot_seguro
    def _acao_erro(self, m):
        self._w = None
        QMessageBox.critical(self, "Execução", "Não consegui falar com o Fracttal:\n%s" % m)
        self._pintar()

    @slot_seguro
    def _acao_ok(self, res):
        self._w = None
        if isinstance(res, dict) and res.get("ok") is False:
            QMessageBox.critical(self, "Execução", str(res.get("erro") or "não deu"))
            self._pintar(); return
        if isinstance(res, dict) and res.get("etiqueta_erro"):
            QMessageBox.warning(self, "Execução", "O cronômetro rodou, mas não consegui mudar a "
                                "coluna do card:\n%s" % res["etiqueta_erro"])
        if self._on_mudou:
            self._on_mudou()
        self._carregar()          # relê em vez de supor o novo estado

    @slot_seguro
    def _play(self, *_):
        e = (self._est or {}).get("estado", "parada")
        if e == "rodando":                       # virou botão de PAUSAR
            dlg = _MotivoPausa(self)
            if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.id_motivo:
                self._pintar(); return
            self._acao(api.pausar_execucao, self._tid, dlg.id_motivo, dlg.nota)
        elif e == "pausada":
            self._acao(api.retomar_execucao, self._tid)
        else:
            # dar play MOVE o card para "Em processo" (é a etiqueta que manda na coluna).
            # Pausar não devolve para "Pendente": quem começou está com a OS em mãos.
            self._acao(api.iniciar_execucao_os, self._d.get("id"), self._tid)

    @slot_seguro
    def _stop(self, *_):
        if QMessageBox.question(self, "Concluir atividade",
                                "Parar o cronômetro desta tarefa?\n\nIsso NÃO conclui a OS — só "
                                "encerra o tempo de trabalho."
                                ) != QMessageBox.StandardButton.Yes:
            return
        self._acao(api.finalizar_execucao_os, self._d.get("id"), self._tid)
