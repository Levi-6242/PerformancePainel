"""Card de detalhe de uma OS (ao clicar no nº no histórico) — redesign premium (tema navy GridCo):
cabeçalho com Nº + selo, banner do ativo, metadados em grade + duração total, blocos Título/Notas,
subtarefas em acordeão (clique abre a resposta), anexos SEPARADOS (das subtarefas × da OS) e ações."""
from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
                             QScrollArea, QWidget, QFrame, QProgressBar, QApplication, QMessageBox,
                             QLineEdit, QListWidget, QListWidgetItem, QComboBox)
import api
from workers import ApiWorker, slot_seguro
from steps.searchcombo import tornar_pesquisavel
from steps.clonar import abrir_clonar_os
from steps.galeria import abrir_galeria
from steps.documentos import abrir_documentos
from steps.ui import QSS_FORM, icone_pix, GREEN, GREEN_INK, MUTED, TEXT, CARD, INPUT, BORDER, BG

DESK = "#57B6F5"                      # azul dos anexos da OS (separa do verde das subtarefas)
_ABERTOS = []                         # mantém referência aos detalhes abertos (não-modais) p/ o GC


def _cor_hex(cor):
    """Normaliza a cor da etiqueta do Fracttal → '#rrggbb' (fallback cinza)."""
    c = str(cor or "").strip().lstrip("#")
    return "#" + c if len(c) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in c) else "#A6A6A6"


def _cor_rgb(cor):
    h = _cor_hex(cor).lstrip("#")
    return f"{int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)}"


def _swatch(cor, size=12):
    """Bolinha da cor da etiqueta (ícone da lista de seleção)."""
    pm = QPixmap(size, size); pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(_cor_hex(cor))); p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(1, 1, size - 2, size - 2); p.end()
    return pm

_EXTRA_QSS = f"""
QDialog {{ background:{BG}; }}
QFrame#osBar {{ background:transparent; }}
QLabel#osNum {{ font-size:19px; font-weight:700; color:{TEXT}; }}
QLabel#osSub {{ font-size:12px; color:{MUTED}; }}
QLabel#secLab {{ font-size:11px; font-weight:700; letter-spacing:1.3px; color:{MUTED}; }}
QFrame#card {{ background:{CARD}; border:1px solid #222c46; border-radius:13px; }}
QLabel#readbox {{ background:{INPUT}; border:1px solid {BORDER}; border-radius:12px;
  padding:12px 14px; color:#c4cbdb; font-size:14px; }}
QLabel#readboxTitle {{ background:{INPUT}; border:1px solid {BORDER}; border-radius:12px;
  padding:12px 14px; color:{TEXT}; font-size:14px; font-weight:600; }}
QFrame#subRow {{ background:{CARD}; border:1px solid #222c46; border-radius:12px; }}
QFrame#subRow[open="true"] {{ border-color:rgba(166,226,46,0.55); background:rgba(166,226,46,0.09); }}
QLabel#kind {{ background:{INPUT}; border:1px solid {BORDER}; border-radius:999px; color:{MUTED};
  font-size:11px; padding:2px 9px; }}
QLabel#ansBox {{ background:{CARD}; border:1px solid #222c46; border-radius:10px; padding:10px 13px;
  color:#c4cbdb; font-size:13px; }}
QPushButton#pClone {{ background:{GREEN}; color:{GREEN_INK}; border:none; border-radius:10px;
  min-height:40px; padding:0 16px; font-weight:700; }}
QPushButton#pClone:hover {{ background:#b6ee43; }}
QPushButton#pGhost {{ background:transparent; color:#c4cbdb; border:1px solid {BORDER};
  border-radius:10px; min-height:40px; padding:0 14px; font-weight:600; }}
QPushButton#pGhost:hover {{ border-color:#43547a; color:{TEXT}; }}
QPushButton#pDanger {{ background:transparent; color:#f5766b; border:1px solid rgba(245,118,107,0.4);
  border-radius:10px; min-height:40px; padding:0 14px; font-weight:600; }}
QPushButton#pDanger:hover {{ background:#f5766b; color:#fff; border-color:#f5766b; }}
QPushButton#pDone {{ background:transparent; color:{GREEN}; border:1px solid rgba(166,226,46,0.45);
  border-radius:10px; min-height:40px; padding:0 14px; font-weight:700; }}
QPushButton#pDone:hover {{ background:{GREEN}; color:{GREEN_INK}; border-color:{GREEN}; }}
QPushButton#pDone:disabled {{ color:#6a7488; border-color:{BORDER}; }}
/* Abrir/Ver chamado: âmbar — destaca sem competir com o verde do Concluir OS */
QPushButton#pChamado {{ background:rgba(224,166,58,0.14); color:#e0a63a;
  border:1px solid rgba(224,166,58,0.5); border-radius:10px; min-height:40px;
  padding:0 14px; font-weight:600; }}
QPushButton#pChamado:hover {{ background:#e0a63a; color:{GREEN_INK}; border-color:#e0a63a; }}
QPushButton#pChamado:disabled {{ color:#6a7488; background:transparent; border-color:{BORDER}; }}
QPushButton#iconClose {{ background:transparent; border:1px solid transparent; border-radius:9px; }}
QPushButton#iconClose:hover {{ background:{INPUT}; border-color:{BORDER}; }}
QProgressBar {{ background:{INPUT}; border:1px solid #222c46; border-radius:4px; max-height:6px; }}
QProgressBar::chunk {{ background:{GREEN}; border-radius:4px; }}
"""


def abrir_os_detalhe(parent, id_work_order, folio=None):
    """Abre o detalhe da OS em janela NÃO-modal — dá p/ abrir/comparar várias OSs ao mesmo tempo."""
    dlg = OsDetalheDialog(parent, id_work_order, folio)
    dlg.setModal(False)
    _ABERTOS.append(dlg)
    dlg.finished.connect(lambda *_: _ABERTOS.remove(dlg) if dlg in _ABERTOS else None)
    dlg.show(); dlg.raise_(); dlg.activateWindow()


# Largura do card de OS. Exportada porque outras telas se dimensionam EM RELAÇÃO a ela — o
# "Nova análise" da Performance pede o dobro, e cravar 1452 lá quebraria o vínculo.
LARGURA_CARD = 726


def aplicar_geometria_card(dlg, largura=LARGURA_CARD):
    """Abre o card com largura fixa e altura ~cheia SEM cobrir a barra de tarefas: usa availableGeometry
    (já exclui a barra) e ainda desconta a moldura da janela (título/bordas). Centralizado + colado no
    topo. Usado pelo card da OS e da Solicitação."""
    scr = QApplication.primaryScreen().availableGeometry()
    w = min(largura, scr.width() - 40)
    h = max(560, scr.height() - 60)                 # -60 = folga p/ título + bordas (não invade a barra)
    dlg.resize(w, h)
    dlg.move(scr.left() + (scr.width() - w) // 2, scr.top() + 8)


def _fname(u):
    """Nome do arquivo a partir de uma URL/caminho (tira query, diretórios e decodifica %20 etc.)."""
    if not u:
        return ""
    import urllib.parse as _up
    return _up.unquote(str(u).split("?")[0].rstrip("/").rsplit("/", 1)[-1])


def _svg(nome, cor, size=18):
    lb = QLabel(); lb.setPixmap(icone_pix(nome, cor, size))
    lb.setStyleSheet("background:transparent;border:none;")
    lb.setFixedSize(size, size); lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lb


def _tile(nome, cor, dim, size=44, ic=21):
    w = QLabel(); w.setFixedSize(size, size); w.setAlignment(Qt.AlignmentFlag.AlignCenter)
    w.setStyleSheet(f"background:{dim};border:1px solid {BORDER};border-radius:12px;")
    w.setPixmap(icone_pix(nome, cor, ic))
    return w


def _person(nome):
    """Valor 'avatar (iniciais) + nome' p/ Atribuído a / Criado por."""
    w = QWidget(); w.setStyleSheet("background:transparent;")
    h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(8)
    nome = (nome or "—").strip() or "—"
    partes = [p for p in nome.split() if p]
    ini = ((partes[0][0] + (partes[-1][0] if len(partes) > 1 else "")).upper() if partes else "?")
    av = QLabel(ini); av.setFixedSize(22, 22); av.setAlignment(Qt.AlignmentFlag.AlignCenter)
    av.setStyleSheet(f"background:rgba(166,226,46,0.16);color:{GREEN};border-radius:11px;"
                     "font-size:10px;font-weight:700;")
    lb = QLabel(nome); lb.setStyleSheet(f"color:{TEXT};font-weight:600;font-size:13px;background:transparent;")
    h.addStretch(1); h.addWidget(av); h.addWidget(lb)
    w.lb = lb            # exposto p/ quem precisa reescrever o nome sem remontar a linha
    return w


_SETA_PNG = None


def _seta_baixo_png():
    """Caminho de um PNG com a seta ↓ (o chevron do projeto, girado) para o QSS.

    O `QSS_FORM` zera o `::drop-down`, e sem imagem o Qt não desenha seta nenhuma: o combo fica
    idêntico às caixas de leitura de Título/Notas e ninguém descobre que dá para clicar. O QSS só
    aceita `url(arquivo)` — daí gravar o ícone uma vez no TEMP em vez de usar o QPixmap direto."""
    global _SETA_PNG
    if _SETA_PNG is None:
        import os
        import tempfile
        from PyQt6.QtGui import QTransform
        alvo = os.path.join(tempfile.gettempdir(), "gridco_seta_combo.png")
        try:
            icone_pix("chevron", MUTED, 13).transformed(QTransform().rotate(90),
                                                        Qt.TransformationMode.SmoothTransformation).save(alvo)
            _SETA_PNG = alvo.replace("\\", "/")          # QSS não aceita barra invertida
        except Exception:
            _SETA_PNG = ""                               # sem seta é feio, mas não quebra a tela
    return _SETA_PNG


def _dur_seg(v):
    """Duração estimada da tarefa. O Fracttal manda em SEGUNDOS (3600 = 1h) — mostrar o número cru
    faria alguém ler "3600" como minutos."""
    try:
        s = int(float(str(v).strip()))
    except (TypeError, ValueError):
        return "—"
    if s <= 0:
        return "—"
    h, m = divmod(s // 60, 60)
    return f"{h}h{m:02d}" if h and m else (f"{h}h" if h else f"{m}min")


class _SubRow(QFrame):
    """Linha de subtarefa (acordeão): check + descrição + tipo + seta; clique mostra a resposta."""
    def __init__(self, sub):
        super().__init__()
        self._open = False
        feito = bool(sub.get("feito"))
        self.setObjectName("subRow")
        self.setProperty("open", "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        out = QVBoxLayout(self); out.setContentsMargins(13, 11, 13, 11); out.setSpacing(0)
        head = QHBoxLayout(); head.setSpacing(12)
        chk = QLabel(); chk.setFixedSize(22, 22); chk.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if feito:
            chk.setStyleSheet(f"background:{GREEN};border:2px solid {GREEN};border-radius:7px;")
            chk.setPixmap(icone_pix("check", GREEN_INK, 13))
        else:
            chk.setStyleSheet(f"background:{INPUT};border:1px solid {BORDER};border-radius:7px;")
        head.addWidget(chk)
        lb = QLabel(sub.get("descricao") or "—"); lb.setWordWrap(True)
        lb.setStyleSheet(f"color:{TEXT};font-size:14px;font-weight:500;background:transparent;border:none;")
        head.addWidget(lb, 1)
        tipo = (sub.get("tipo") or "").strip()
        if tipo and tipo != "—":
            k = QLabel(tipo); k.setObjectName("kind")
            head.addWidget(k, 0, Qt.AlignmentFlag.AlignVCenter)
        self._chev = _svg("chevron", MUTED, 16)
        head.addWidget(self._chev, 0, Qt.AlignmentFlag.AlignVCenter)
        out.addLayout(head)
        resp = sub.get("resposta")
        resp = str(resp).strip() if resp not in (None, "") else ""
        self._ans = QLabel(resp or "Sem resposta registrada."); self._ans.setObjectName("ansBox")
        self._ans.setWordWrap(True)
        self._ans.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                          | Qt.TextInteractionFlag.TextSelectableByKeyboard)  # selecionável p/ copiar
        self._ans.setCursor(Qt.CursorShape.IBeamCursor)
        if not resp:
            self._ans.setStyleSheet("color:#6a7488;font-style:italic;")
        self._ans_wrap = QWidget(); self._ans_wrap.setStyleSheet("background:transparent;")
        aw = QVBoxLayout(self._ans_wrap); aw.setContentsMargins(34, 9, 0, 0); aw.setSpacing(6)
        if resp:                                # botão "copiar" (copia a resposta inteira p/ a área de transferência)
            crow = QHBoxLayout(); crow.setContentsMargins(0, 0, 0, 0)
            b_copy = QPushButton("copiar"); b_copy.setCursor(Qt.CursorShape.PointingHandCursor)
            b_copy.setStyleSheet("QPushButton{background:transparent;border:none;color:%s;font-size:11.5px;}"
                                 "QPushButton:hover{text-decoration:underline;}" % GREEN)

            def _copiar(_=False, txt=resp, btn=b_copy):
                QApplication.clipboard().setText(txt); btn.setText("copiado!")
                QTimer.singleShot(1500, lambda: btn.setText("copiar"))
            b_copy.clicked.connect(_copiar)
            crow.addStretch(1); crow.addWidget(b_copy)
            aw.addLayout(crow)
        aw.addWidget(self._ans)
        self._ans_wrap.setVisible(False)
        out.addWidget(self._ans_wrap)

    def mousePressEvent(self, e):
        self._open = not self._open
        self._ans_wrap.setVisible(self._open)
        self.setProperty("open", "true" if self._open else "false")
        self._chev.setPixmap(icone_pix("chevron", GREEN if self._open else MUTED, 16))
        self.style().unpolish(self); self.style().polish(self)
        super().mousePressEvent(e)


class _AnexoCard(QFrame):
    """Card clicável de anexos (contagem). `cor`/`dim` definem o tom (verde=subtarefas, azul=OS)."""
    def __init__(self, icone, titulo, sub, cor, dim, on_click):
        super().__init__()
        self._cb = on_click
        self.setObjectName("card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"QFrame#card:hover{{border-color:{cor};}}")
        h = QHBoxLayout(self); h.setContentsMargins(15, 13, 16, 13); h.setSpacing(13)
        h.addWidget(_tile(icone, cor, dim))
        tx = QVBoxLayout(); tx.setSpacing(2)
        t = QLabel(titulo); t.setWordWrap(True)
        t.setStyleSheet(f"color:{TEXT};font-size:14px;font-weight:650;background:transparent;")
        self.sub_lbl = QLabel(sub); self.sub_lbl.setWordWrap(True)
        self.sub_lbl.setStyleSheet(f"color:{MUTED};font-size:12px;background:transparent;")
        tx.addWidget(t); tx.addWidget(self.sub_lbl)
        h.addLayout(tx, 1)
        self.num = QLabel("0"); self.num.setStyleSheet(f"color:{cor};font-size:24px;font-weight:750;background:transparent;")
        h.addWidget(self.num)

    def set_count(self, n):
        self.num.setText(str(n))

    def set_sub(self, txt):
        self.sub_lbl.setText(txt)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._cb:
            self._cb()
        super().mousePressEvent(e)


class TrocarResponsavelDialog(QDialog):
    """Escolhe a nova pessoa e grava. Público (sem `_`) porque o quadro da Performance usa o
    mesmo diálogo quando o arrastar-e-soltar precisa confirmar."""
    def __init__(self, parent, folio, atual="", id_work_order=None):
        super().__init__(parent)
        self._wo = id_work_order if id_work_order is not None else getattr(parent, "_wo", None)
        self.escolhido = None          # {'id_personnel','name'} da pessoa escolhida
        self.resultado = None          # resposta do api.mudar_responsavel
        self._w = self._ws = None
        self.setWindowTitle("Trocar responsável — OS %s" % (folio or ""))
        self.setMinimumWidth(400)
        self.setStyleSheet(QSS_FORM)
        lay = QVBoxLayout(self); lay.setContentsMargins(16, 14, 16, 14); lay.setSpacing(10)
        t = QLabel("Trocar o responsável da OS %s" % (folio or ""))
        t.setStyleSheet(f"color:{TEXT};font-size:15px;font-weight:600;background:transparent;")
        lay.addWidget(t)
        if atual and atual != "—":
            a = QLabel("Hoje está com <b>%s</b>." % atual)
            a.setStyleSheet(f"color:{MUTED};font-size:12px;background:transparent;")
            lay.addWidget(a)
        self.cb = QComboBox(); self.cb.addItem("carregando o pessoal…", None)
        tornar_pesquisavel(self.cb)
        lay.addWidget(self.cb)
        self.hint = QLabel(""); self.hint.setObjectName("hint"); lay.addWidget(self.hint)
        row = QHBoxLayout()
        b_c = QPushButton("Cancelar"); b_c.setObjectName("secondary"); b_c.clicked.connect(self.reject)
        self.b_ok = QPushButton("Atribuir"); self.b_ok.clicked.connect(self._salvar)
        self.b_ok.setEnabled(False)
        row.addWidget(b_c); row.addWidget(self.b_ok, 1)
        lay.addLayout(row)
        self._w = ApiWorker(api.get_responsaveis)
        self._w.ok.connect(self._set_pessoas)
        self._w.erro.connect(lambda m: self.hint.setText("não consegui buscar o pessoal: %s" % m))
        self._w.start()

    @slot_seguro
    def _set_pessoas(self, pessoas):
        self._w = None
        self.cb.clear(); self.cb.addItem("— escolha a pessoa —", None)
        for p in sorted(pessoas or [], key=lambda x: (x.get("name") or "").lower()):
            if p.get("id_personnel"):
                self.cb.addItem(p.get("name") or "?", p)
        tornar_pesquisavel(self.cb)
        self.b_ok.setEnabled(True)

    @slot_seguro
    def _salvar(self, *_):
        p = self.cb.currentData()
        if not isinstance(p, dict) or not p.get("id_personnel"):
            self.hint.setText("escolha a pessoa."); return
        self.b_ok.setEnabled(False); self.hint.setText("gravando no Fracttal…")
        self.escolhido = p
        self._ws = ApiWorker(api.mudar_responsavel, self._wo, p["id_personnel"])
        self._ws.ok.connect(self._gravou)
        self._ws.erro.connect(self._falhou)
        self._ws.start()

    @slot_seguro
    def _gravou(self, res):
        self._ws = None
        self.resultado = res if isinstance(res, dict) else {"ok": False, "erro": "resposta vazia"}
        if not self.resultado.get("ok"):
            self.b_ok.setEnabled(True)
            self.hint.setText(str(self.resultado.get("erro") or "não deu")); return
        self.accept()

    @slot_seguro
    def _falhou(self, m):
        self._ws = None
        self.b_ok.setEnabled(True); self.hint.setText(str(m))
        self.resultado = {"ok": False, "erro": str(m)}


class _EtiquetasDialog(QDialog):
    """Seletor de etiquetas de uma OS (catálogo marcável com a cor de cada uma) → grava via apply_labels."""
    def __init__(self, parent, id_work_order, folio, atuais):
        super().__init__(parent)
        self._wo = id_work_order
        self._checked = {e.get("id") for e in (atuais or []) if e.get("id") is not None}
        self._labels = []
        self.resultado = None                      # nova lista de etiquetas após salvar (None = cancelou)
        self._w = self._ws = None
        self.setWindowTitle(f"Etiquetas — OS {folio or id_work_order}")
        self.setMinimumWidth(380); self.setMinimumHeight(420)
        self.setStyleSheet(QSS_FORM)
        lay = QVBoxLayout(self); lay.setContentsMargins(16, 14, 16, 14); lay.setSpacing(10)
        tit = QLabel(f"Etiquetas da OS {folio or id_work_order}")
        tit.setStyleSheet(f"color:{TEXT};font-size:15px;font-weight:600;background:transparent;")
        lay.addWidget(tit)
        self.busca = QLineEdit(); self.busca.setPlaceholderText("carregando etiquetas…")
        self.busca.addAction(QIcon(icone_pix("search", MUTED, 15)), QLineEdit.ActionPosition.LeadingPosition)
        self.busca.textChanged.connect(self._filtrar)
        lay.addWidget(self.busca)
        self.lst = QListWidget(); self.lst.itemChanged.connect(self._on_check)
        lay.addWidget(self.lst, 1)
        self.hint = QLabel(""); self.hint.setObjectName("hint"); lay.addWidget(self.hint)
        row = QHBoxLayout()
        b_cancel = QPushButton("Cancelar"); b_cancel.setObjectName("secondary"); b_cancel.clicked.connect(self.reject)
        self.b_ok = QPushButton("Salvar"); self.b_ok.clicked.connect(self._salvar)
        row.addWidget(b_cancel); row.addWidget(self.b_ok, 1)
        lay.addLayout(row)
        self._w = ApiWorker(api.get_labels)
        self._w.ok.connect(self._set_labels)
        self._w.erro.connect(lambda *_: self.busca.setPlaceholderText("etiquetas não carregaram — relogue"))
        self._w.start()

    @slot_seguro
    def _set_labels(self, labels):
        self._w = None
        self._labels = labels or []
        self.busca.setPlaceholderText("Filtrar etiquetas…" if self._labels else "nenhuma etiqueta no catálogo")
        self._filtrar("")

    def _filtrar(self, txt):
        txt = (txt or "").strip().lower()
        self.lst.blockSignals(True); self.lst.clear()
        for l in self._labels:
            d = str(l.get("description") or "").strip()
            if not d or (txt and txt not in d.lower()):
                continue
            it = QListWidgetItem(QIcon(_swatch(l.get("color"))), d)
            it.setData(Qt.ItemDataRole.UserRole, l.get("id"))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if l.get("id") in self._checked else Qt.CheckState.Unchecked)
            self.lst.addItem(it)
        self.lst.blockSignals(False)

    @slot_seguro
    def _on_check(self, it):
        lid = it.data(Qt.ItemDataRole.UserRole)
        if it.checkState() == Qt.CheckState.Checked:
            self._checked.add(lid)
        else:
            self._checked.discard(lid)

    @slot_seguro
    def _salvar(self, *_):
        ids = [i for i in self._checked if i is not None]
        if not ids:
            self.hint.setText("Marque ao menos uma etiqueta (ou Cancelar)."); return
        self.b_ok.setEnabled(False); self.hint.setText("salvando…")
        self._ws = ApiWorker(api.apply_labels, self._wo, ids)
        self._ws.ok.connect(self._salvou); self._ws.erro.connect(self._erro_salvar)
        self._ws.start()

    @slot_seguro
    def _salvou(self, res):
        self._ws = None
        if isinstance(res, dict) and res.get("ok") is False:
            self.b_ok.setEnabled(True); self.hint.setText("⚠ " + str(res.get("erro") or "não foi possível salvar")); return
        self.resultado = [{"id": l.get("id"), "nome": l.get("description"), "cor": l.get("color")}
                          for l in self._labels if l.get("id") in self._checked]
        self.accept()

    @slot_seguro
    def _erro_salvar(self, m):
        self._ws = None; self.b_ok.setEnabled(True); self.hint.setText("⚠ " + str(m))


class _ConcluirDialog(QDialog):
    """Confirmação estilizada (tema navy do app) para concluir/fechar uma OS — no lugar do QMessageBox.
    Mostra o % de conclusão pelas subtarefas (feitas/total).

    `sem_fim` = títulos das tarefas SEM data de fim. Vem do que a tela já carregou (`_tarefas`),
    sem chamada extra. Quando tem, o diálogo ganha um segundo aviso — é o lado "antes" do double
    check pedido pelo Levi em 03/08: conclusão é irreversível, então a pessoa precisa saber ANTES
    que a OS vai fechar sem data de fim, não descobrir depois como na 10509."""
    def __init__(self, parent, folio, feitas=0, total=0, sem_fim=None):
        super().__init__(parent)
        self.setWindowTitle("Concluir OS")
        self.setModal(True); self.setMinimumWidth(480)
        self.setStyleSheet(QSS_FORM + _EXTRA_QSS)
        pct = round(100 * feitas / total) if total else 100
        cor_pct = GREEN if pct >= 100 else "#eb8b57"
        lay = QVBoxLayout(self); lay.setContentsMargins(24, 22, 24, 18); lay.setSpacing(0)

        # ── cabeçalho ──
        head = QHBoxLayout(); head.setSpacing(14)
        tile = QLabel(); tile.setFixedSize(46, 46); tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tile.setStyleSheet("background:rgba(166,226,46,0.14);border-radius:13px;")
        tile.setPixmap(icone_pix("check", GREEN, 25))
        col = QVBoxLayout(); col.setSpacing(3); col.setContentsMargins(0, 0, 0, 0)
        t = QLabel(f"Concluir a OS {folio}?")
        t.setStyleSheet(f"color:{TEXT};font-size:18.5px;font-weight:700;background:transparent;border:none;")
        s = QLabel("A OS será marcada como concluída e fechada no Fracttal.")
        s.setWordWrap(True); s.setStyleSheet(f"color:{MUTED};font-size:13.5px;background:transparent;border:none;")
        col.addWidget(t); col.addWidget(s)
        head.addWidget(tile, 0, Qt.AlignmentFlag.AlignTop); head.addLayout(col, 1)
        lay.addLayout(head); lay.addSpacing(16)

        # ── % de conclusão (subtarefas) ──
        pbox = QWidget(); pbox.setObjectName("pbox")
        pbox.setStyleSheet("QWidget#pbox{background:%s;border:1px solid %s;border-radius:11px;}" % (INPUT, BORDER))
        pv = QVBoxLayout(pbox); pv.setContentsMargins(14, 12, 14, 12); pv.setSpacing(8)
        prow = QHBoxLayout()
        pl = QLabel("Conclusão da OS"); pl.setStyleSheet(f"color:{MUTED};font-size:12.5px;background:transparent;border:none;")
        pp = QLabel(f"{pct}%"); pp.setStyleSheet(f"color:{cor_pct};font-size:20px;font-weight:800;background:transparent;border:none;")
        prow.addWidget(pl); prow.addStretch(1); prow.addWidget(pp)
        pv.addLayout(prow)
        bar = QProgressBar(); bar.setRange(0, 100); bar.setValue(pct); bar.setTextVisible(False); bar.setFixedHeight(7)
        bar.setStyleSheet("QProgressBar{background:%s;border:none;border-radius:4px;}"
                          "QProgressBar::chunk{background:%s;border-radius:4px;}" % (BG, cor_pct))
        pv.addWidget(bar)
        pc = QLabel(f"{feitas} de {total} subtarefas concluídas" if total else "OS sem subtarefas")
        pc.setStyleSheet(f"color:{MUTED};font-size:12px;background:transparent;border:none;")
        pv.addWidget(pc)
        lay.addWidget(pbox); lay.addSpacing(14)

        # ── aviso (borda ESCOPADA no #warnBox → não vaza pros filhos) ──
        warn = QWidget(); warn.setObjectName("warnBox")
        warn.setStyleSheet("QWidget#warnBox{background:rgba(240,138,93,0.10);"
                           "border:1px solid rgba(240,138,93,0.35);border-radius:11px;}")
        wl = QHBoxLayout(warn); wl.setContentsMargins(13, 12, 14, 12); wl.setSpacing(11)
        wi = QLabel(); wi.setFixedSize(20, 20); wi.setStyleSheet("background:transparent;border:none;")
        wi.setPixmap(icone_pix("alert", "#eb8b57", 19))
        wt = QLabel("As subtarefas que não foram concluídas ficarão registradas como <b>pendentes</b>. "
                    "Esta ação é <b>irreversível</b>!")
        wt.setWordWrap(True)
        wt.setStyleSheet("color:#e9b89e;font-size:13.5px;background:transparent;border:none;")
        wl.addWidget(wi, 0, Qt.AlignmentFlag.AlignTop); wl.addWidget(wt, 1)
        lay.addWidget(warn); lay.addSpacing(12)

        # ── data de fim da tarefa (só aparece quando FALTA) ──
        # Vermelho, e não o âmbar do aviso de cima: aquele é "ficou pendente" (recuperável, a OS
        # segue existindo); este é "vai fechar sem data e não tem volta". Severidades diferentes
        # com a mesma cor viram ruído e a pessoa para de ler as duas.
        faltando = [str(x) for x in (sem_fim or []) if str(x).strip()]
        if faltando:
            dbox = QWidget(); dbox.setObjectName("dtBox")
            dbox.setStyleSheet("QWidget#dtBox{background:rgba(224,84,84,0.11);"
                               "border:1px solid rgba(224,84,84,0.42);border-radius:11px;}")
            dl = QHBoxLayout(dbox); dl.setContentsMargins(13, 12, 14, 12); dl.setSpacing(11)
            di = QLabel(); di.setFixedSize(20, 20); di.setStyleSheet("background:transparent;border:none;")
            di.setPixmap(icone_pix("alert", "#e05454", 19))
            if len(faltando) == 1:
                msg = ("Esta OS vai fechar <b>sem data de fim da tarefa</b>. O campo fica vazio "
                       "para sempre — a conclusão não preenche depois.")
            else:
                msg = ("<b>%d tarefas</b> desta OS vão fechar <b>sem data de fim</b>. O campo fica "
                       "vazio para sempre — a conclusão não preenche depois.<br>%s"
                       % (len(faltando), "; ".join(faltando[:3])
                          + (" e mais %d" % (len(faltando) - 3) if len(faltando) > 3 else "")))
            dt = QLabel(msg); dt.setWordWrap(True)
            dt.setStyleSheet("color:#f0b4b4;font-size:13.5px;background:transparent;border:none;")
            dl.addWidget(di, 0, Qt.AlignmentFlag.AlignTop); dl.addWidget(dt, 1)
            lay.addWidget(dbox); lay.addSpacing(12)
        lay.addSpacing(8)

        # ── botões ──
        row = QHBoxLayout(); row.addStretch(1); row.setSpacing(10)
        b_no = QPushButton("Cancelar"); b_no.setObjectName("pGhost"); b_no.clicked.connect(self.reject)
        b_yes = QPushButton("Concluir OS"); b_yes.setObjectName("pDone")
        b_yes.setCursor(Qt.CursorShape.PointingHandCursor); b_yes.clicked.connect(self.accept)
        row.addWidget(b_no); row.addWidget(b_yes)
        lay.addLayout(row)


class _LinkLabel(QLabel):
    """QLabel que vira link ao receber um callback (cursor de mão + clique). set_click(None) = inerte."""
    def __init__(self, text=""):
        super().__init__(text)
        self._cb = None

    def set_click(self, cb):
        self._cb = cb
        self.setCursor(Qt.CursorShape.PointingHandCursor if cb else Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, e):
        if self._cb and e.button() == Qt.MouseButton.LeftButton:
            try:
                self._cb()
            except Exception:
                pass
        else:
            super().mousePressEvent(e)


class OsDetalheDialog(QDialog):
    def __init__(self, parent, id_work_order, folio=None):
        super().__init__(parent)
        self._wo = id_work_order
        self._folio = folio
        self._code = None
        self._w = self._wi = self._wa = self._wcc = None
        self._imagens = []          # anexos das SUBTAREFAS (form items) — get_os_subtarefa_anexos
        self._sub_imgs = []         # idem, exibidos no card das subtarefas
        self._anexos_os = []        # anexos no nível da TAREFA/OS (get_os_anexos)
        self._os_uniq = []          # anexos da OS TIRANDO os que já são de subtarefa (sem duplicar)
        self._etiquetas = []        # etiquetas da OS [{'id','nome','cor'}]
        self._sub_feitas = self._sub_total = 0   # subtarefas concluídas / total (p/ o % no Concluir)
        self._subs = []             # subtarefas da OS inteira (a lista exibida é um recorte destas)
        self._tarefas = []          # tarefas da OS — >1 liga o seletor entre Notas e Subtarefas
        self._anexos_loaded = False # os anexos da OS já voltaram? (p/ deduplicar antes de contar)
        self._ativo = ""
        self._os_pai_id = None; self._os_pai_folio = ""   # OS pai clicável
        self._wsol = None                                 # worker do fetch da solicitação (clique)
        self._chamado = None; self._wchm = None           # OS de chamado filha (se já existir)
        self._ativo_txt = ""; self._usina_txt = ""        # alimentam o diálogo de abrir chamado
        self._event_date = None                           # data do incidente → clonada no chamado
        self.setWindowTitle(f"OS {folio or id_work_order}")
        self.setMinimumSize(560, 560)
        self.setStyleSheet(QSS_FORM + _EXTRA_QSS)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        # ── cabeçalho ──
        head = QFrame(); head.setObjectName("osBar")
        hh = QHBoxLayout(head); hh.setContentsMargins(18, 15, 14, 13); hh.setSpacing(11)
        hh.addWidget(_tile("copy", GREEN, "rgba(166,226,46,0.14)", 34, 17))
        tw = QVBoxLayout(); tw.setSpacing(0)
        self.titulo = QLabel(f"OS {folio or ''}"); self.titulo.setObjectName("osNum")
        sub = QLabel("Ordem de serviço"); sub.setObjectName("osSub")
        tw.addWidget(self.titulo); tw.addWidget(sub)
        hh.addLayout(tw)
        self.badge_box = QHBoxLayout(); self.badge_box.setSpacing(6)
        hh.addSpacing(4); hh.addLayout(self.badge_box)
        hh.addStretch(1)
        # ── vínculos (OS pai / solicitação) — compacto, topo direito ──
        self.vinc_card = QFrame(); self.vinc_card.setObjectName("vincBox")
        self.vinc_card.setStyleSheet("QFrame#vincBox{background:rgba(255,255,255,0.035);"
                                     "border:1px solid rgba(255,255,255,0.07);border-radius:9px;}")
        vv = QVBoxLayout(self.vinc_card); vv.setContentsMargins(12, 6, 13, 6); vv.setSpacing(3)
        self.pai_row, self.pai_val = self._vinc_row("layers", "OS pai")
        self.sol_row, self.sol_val = self._vinc_row("file", "Solicitação")
        # chamado = OS FILHA desta (etiqueta CHAMADOS). Aparece junto dos outros vínculos p/ o
        # supervisor ver de cara que já foi acionado — e não abrir um segundo.
        self.chm_row, self.chm_val = self._vinc_row("headset", "Chamado")
        vv.addWidget(self.pai_row); vv.addWidget(self.sol_row); vv.addWidget(self.chm_row)
        self.chm_row.setVisible(False)
        hh.addWidget(self.vinc_card)              # X do cabeçalho removido — usa o X da janela
        lay.addWidget(head)
        sep = QFrame(); sep.setFixedHeight(1); sep.setStyleSheet("background:rgba(255,255,255,0.06);")
        lay.addWidget(sep)

        # ── corpo (scroll) ──
        scroll = QScrollArea(); scroll.setObjectName("uiFlat"); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(); scroll.setWidget(body)
        bl = QVBoxLayout(body); bl.setContentsMargins(18, 16, 18, 14); bl.setSpacing(15)

        # ativo (banner)
        self.asset_card = QFrame(); self.asset_card.setObjectName("card")
        ah = QHBoxLayout(self.asset_card); ah.setContentsMargins(15, 13, 15, 13); ah.setSpacing(13)
        ah.addWidget(_tile("rack", GREEN, "rgba(166,226,46,0.10)"))
        self.ativo_lbl = QLabel("—"); self.ativo_lbl.setWordWrap(True)
        self.ativo_lbl.setStyleSheet(f"color:{TEXT};font-size:16px;font-weight:650;background:transparent;")
        ah.addWidget(self.ativo_lbl, 1)
        bl.addWidget(self.asset_card)

        # meta (grade) + duração
        row = QHBoxLayout(); row.setSpacing(14)
        self.meta_card = QFrame(); self.meta_card.setObjectName("card")
        self.meta_v = QVBoxLayout(self.meta_card); self.meta_v.setContentsMargins(16, 4, 16, 4); self.meta_v.setSpacing(0)
        row.addWidget(self.meta_card, 3)
        self.dur_card = QFrame(); self.dur_card.setObjectName("card")
        dv = QVBoxLayout(self.dur_card); dv.setContentsMargins(16, 14, 16, 14); dv.setSpacing(5)
        dl = QHBoxLayout(); dl.setSpacing(9)
        dl.addWidget(_tile("clock", GREEN, "rgba(166,226,46,0.14)", 26, 15))
        dlab = QLabel("DURAÇÃO TOTAL"); dlab.setStyleSheet(f"color:{MUTED};font-size:11px;font-weight:700;"
                                                          "letter-spacing:0.8px;background:transparent;")
        dl.addWidget(dlab); dl.addStretch(1)
        dv.addLayout(dl)
        self.dur_big = QLabel("—"); self.dur_big.setStyleSheet(f"color:{TEXT};font-size:24px;font-weight:750;"
                                                              "background:transparent;")
        self.dur_note = QLabel("entre evento e fim"); self.dur_note.setStyleSheet("color:#6a7488;font-size:11px;"
                                                                                  "background:transparent;")
        dv.addWidget(self.dur_big); dv.addWidget(self.dur_note)
        # ── linha compacta de ETIQUETA (rodapé do mesmo card) ──
        dv.addStretch(1)
        er = QHBoxLayout(); er.setContentsMargins(0, 8, 0, 0); er.setSpacing(7)
        _et = QLabel("ETIQUETA"); _et.setStyleSheet(f"color:{MUTED};font-size:11px;font-weight:700;"
                                                    "letter-spacing:0.8px;background:transparent;")
        self._etiq_chips = QWidget(); self._etiq_chips.setStyleSheet("background:transparent;")
        self._etiq_chips_l = QHBoxLayout(self._etiq_chips)
        self._etiq_chips_l.setContentsMargins(0, 0, 0, 0); self._etiq_chips_l.setSpacing(5)
        _sep = QLabel("·"); _sep.setStyleSheet("color:#5f6b85;background:transparent;")
        self.b_etiq = QPushButton("editar"); self.b_etiq.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_etiq.setStyleSheet("QPushButton{background:transparent;border:none;color:%s;font-size:11.5px;}"
                                  "QPushButton:hover{text-decoration:underline;}" % GREEN)
        self.b_etiq.clicked.connect(self._editar_etiquetas)
        er.addWidget(_et); er.addWidget(self._etiq_chips); er.addWidget(_sep)
        er.addWidget(self.b_etiq); er.addStretch(1)
        dv.addLayout(er)
        row.addWidget(self.dur_card, 2)
        bl.addLayout(row)

        # título / notas
        bl.addWidget(self._sec_label("TÍTULO"))
        self.titulo_blk = QLabel("—"); self.titulo_blk.setObjectName("readboxTitle"); self.titulo_blk.setWordWrap(True)
        self.titulo_blk.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bl.addWidget(self.titulo_blk)
        bl.addWidget(self._sec_label("NOTAS"))
        self.notas_blk = QLabel("—"); self.notas_blk.setObjectName("readbox"); self.notas_blk.setWordWrap(True)
        self.notas_blk.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bl.addWidget(self.notas_blk)

        # ── seletor de TAREFA (só aparece em OS com mais de uma) ──
        # A preventiva mensal abre uma tarefa por sistema — a 8709 tem 13 tarefas e 45 subtarefas.
        # Numa lista corrida ninguém sabe qual subtarefa é de qual sistema; aqui escolhe-se a tarefa
        # e a lista abaixo passa a ser só dela.
        self.tarefa_wrap = QWidget(); self.tarefa_wrap.setStyleSheet("background:transparent;")
        tw2 = QVBoxLayout(self.tarefa_wrap); tw2.setContentsMargins(0, 0, 0, 0); tw2.setSpacing(8)
        th = QHBoxLayout(); th.setSpacing(10)
        th.addWidget(self._sec_label("TAREFA"))
        self.tarefa_cont = QLabel("")
        self.tarefa_cont.setStyleSheet(f"color:{MUTED};font-size:12px;background:transparent;")
        th.addWidget(self.tarefa_cont); th.addStretch(1)
        tw2.addLayout(th)
        self.cb_tarefa = QComboBox(); self.cb_tarefa.setObjectName("cbTarefa")
        _seta = _seta_baixo_png()
        if _seta:
            self.cb_tarefa.setStyleSheet(
                "QComboBox#cbTarefa::drop-down{subcontrol-origin:padding;subcontrol-position:center right;"
                "width:30px;border:none;}"
                f"QComboBox#cbTarefa::down-arrow{{image:url({_seta});width:13px;height:13px;}}")
        self.cb_tarefa.currentIndexChanged.connect(self._trocar_tarefa)
        tw2.addWidget(self.cb_tarefa)
        self.tarefa_info = QLabel(""); self.tarefa_info.setObjectName("readbox")
        self.tarefa_info.setWordWrap(True); self.tarefa_info.setTextFormat(Qt.TextFormat.RichText)
        tw2.addWidget(self.tarefa_info)
        self.tarefa_wrap.setVisible(False)
        bl.addWidget(self.tarefa_wrap)

        # subtarefas
        sh = QHBoxLayout(); sh.setSpacing(10)
        sh.addWidget(self._sec_label("SUBTAREFAS"))
        self.sub_hint = QLabel("clique para ver a resposta"); self.sub_hint.setStyleSheet("color:#6a7488;"
                                                                                          "font-size:12px;background:transparent;")
        sh.addWidget(self.sub_hint); sh.addStretch(1)
        self.sub_done = QLabel(""); self.sub_done.setStyleSheet(f"color:{GREEN};font-size:12px;font-weight:600;"
                                                               "background:rgba(166,226,46,0.14);border-radius:999px;padding:4px 11px;")
        sh.addWidget(self.sub_done)
        bl.addLayout(sh)
        from PyQt6.QtWidgets import QProgressBar
        self.prog = QProgressBar(); self.prog.setTextVisible(False); self.prog.setRange(0, 1); self.prog.setValue(0)
        bl.addWidget(self.prog)
        self.subs_box = QVBoxLayout(); self.subs_box.setSpacing(8)
        bl.addLayout(self.subs_box)

        # anexos (2 cards)
        bl.addWidget(self._sec_label("ANEXOS DA OS"))
        arow = QHBoxLayout(); arow.setSpacing(12)
        self.card_sub = _AnexoCard("camera", "Anexos das subtarefas", "do técnico",
                                   GREEN, "rgba(166,226,46,0.14)", self._abrir_anexos_sub)
        self.card_os = _AnexoCard("monitor", "Anexos da OS", "por usuário",
                                  DESK, "rgba(87,182,245,0.14)", self._abrir_anexos_os)
        arow.addWidget(self.card_sub); arow.addWidget(self.card_os)
        self.card_sub.set_count("…"); self.card_os.set_count("…")   # até carregar (evita "piscar")
        bl.addLayout(arow)
        # como a OS está registrada no Fracttal (tipo/classificação/criticidade — estilo COS)
        bl.addWidget(self._sec_label("REGISTRO NO FRACTTAL"))
        self.meta_reg = QLabel(""); self.meta_reg.setWordWrap(True)
        self.meta_reg.setTextFormat(Qt.TextFormat.RichText)
        self.meta_reg.setStyleSheet("color:#c4cbdb;font-size:12.5px;background:transparent;")
        bl.addWidget(self.meta_reg)
        bl.addStretch(1)
        lay.addWidget(scroll, 1)

        # ── rodapé ──
        sep2 = QFrame(); sep2.setFixedHeight(1); sep2.setStyleSheet("background:rgba(255,255,255,0.06);")
        lay.addWidget(sep2)
        self.hint = QLabel("carregando detalhes…"); self.hint.setObjectName("uiAjuda")
        hr = QHBoxLayout(); hr.setContentsMargins(18, 6, 18, 0); hr.addWidget(self.hint); hr.addStretch(1)
        lay.addLayout(hr)
        foot = QHBoxLayout(); foot.setContentsMargins(18, 8, 18, 13); foot.setSpacing(9)
        b_clone = QPushButton("Clonar esta OS"); b_clone.setObjectName("pClone")
        b_clone.setIcon(QIcon(icone_pix("copy", GREEN_INK, 15))); b_clone.setIconSize(QSize(15, 15))
        b_clone.setCursor(Qt.CursorShape.PointingHandCursor); b_clone.clicked.connect(self._clonar)
        # "Abrir chamado" ocupa o lugar do antigo "Criar solicitação" (decisão do Levi, 25/07):
        # no card da OS quem interessa é o chamado; solicitação segue na tela própria.
        self.b_chamado = QPushButton("Abrir chamado"); self.b_chamado.setObjectName("pChamado")
        self.b_chamado.setEnabled(False)
        self.b_chamado.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_chamado.clicked.connect(self._abrir_chamado)
        self.b_concluir = QPushButton("Concluir OS"); self.b_concluir.setObjectName("pDone")
        self.b_concluir.setToolTip("Fecha a OS no Fracttal (irreversível — precisa de permissão na sua conta)")
        self.b_concluir.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_concluir.clicked.connect(self._concluir_os)
        self.b_cancel = QPushButton("Cancelar OS"); self.b_cancel.setObjectName("pDanger")
        self.b_cancel.setToolTip("Cancela a OS no Fracttal (precisa de permissão na sua conta)")
        self.b_cancel.clicked.connect(self._cancelar_os)
        # FLUXO — o "ícone de raiz" (Levi, 05/08). Fica ao lado do Clonar, à esquerda, porque é
        # leitura e não ação sobre a OS; os botões da direita todos MUDAM alguma coisa no Fracttal.
        self.b_fluxo = QPushButton("Fluxo"); self.b_fluxo.setObjectName("pClone")
        self.b_fluxo.setIcon(QIcon(icone_pix("ramo", GREEN_INK, 15)))
        self.b_fluxo.setIconSize(QSize(15, 15))
        self.b_fluxo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_fluxo.setToolTip("Mostra esta OS encadeada com as outras — pais, filhas e todo o "
                                "histórico do ativo")
        self.b_fluxo.clicked.connect(self._abrir_fluxo)
        b = QPushButton("Fechar"); b.setObjectName("pGhost"); b.clicked.connect(self.accept)
        foot.addWidget(b_clone); foot.addWidget(self.b_fluxo); foot.addStretch(1)
        foot.addWidget(self.b_chamado); foot.addWidget(self.b_concluir)
        foot.addWidget(self.b_cancel); foot.addWidget(b)
        lay.addLayout(foot)
        aplicar_geometria_card(self, 726)          # +10% de largura, altura = tela cheia
        self._carregar()

    def _sec_label(self, txt):
        l = QLabel(txt); l.setObjectName("secLab"); return l

    def _vinc_row(self, icone, rot):
        """Mini-linha do bloco de vínculos no cabeçalho: [ícone] rótulo … valor. → (widget, label_valor)."""
        w = QWidget(); w.setStyleSheet("background:transparent;")
        h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(7)
        h.addWidget(_svg(icone, MUTED, 13))
        k = QLabel(rot); k.setMinimumWidth(66)
        k.setStyleSheet(f"color:{MUTED};font-size:11.5px;background:transparent;")
        v = _LinkLabel("—"); v.setStyleSheet(f"color:{TEXT};font-size:11.5px;font-weight:600;background:transparent;")
        h.addWidget(k); h.addWidget(v); h.addStretch(1)
        return w, v

    def _add_meta(self, icone, rot, val_widget):
        r = QWidget(); r.setStyleSheet("background:transparent;")
        h = QHBoxLayout(r); h.setContentsMargins(0, 11, 0, 11); h.setSpacing(12)
        h.addWidget(_svg(icone, MUTED, 16))
        k = QLabel(rot); k.setStyleSheet(f"color:{MUTED};font-size:13px;background:transparent;")
        h.addWidget(k)
        if isinstance(val_widget, str):
            v = QLabel(val_widget or "—"); v.setWordWrap(True)
            v.setStyleSheet(f"color:{TEXT};font-weight:600;font-size:13px;background:transparent;")
            h.addStretch(1); h.addWidget(v)
        else:
            h.addWidget(val_widget, 1)
        n = self.meta_v.count()
        if n:
            ln = QFrame(); ln.setFixedHeight(1); ln.setStyleSheet("background:rgba(255,255,255,0.055);")
            self.meta_v.addWidget(ln)
        self.meta_v.addWidget(r)

    # ── responsável (trocável) ──
    def _linha_responsavel(self, d):
        """Nome + link 'trocar'. A troca é a única edição de OS já criada que a API aceita além de
        status, etiqueta e anexo (`tasks.work_orders_update`, capturado do web em 28/07) — antes,
        repassar uma OS obrigava a sair do app e ir ao Fracttal."""
        w = QWidget(); w.setStyleSheet("background:transparent;")
        h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(10)
        h.addStretch(1)
        # `_person` devolve um WIDGET (avatar + nome), não texto. Escrever `QLabel(_person(...))`
        # cai na sobrecarga `QLabel(parent)` do PyQt: nasce um rótulo VAZIO filho de um widget
        # descartável, que o GC coleta em seguida — e o `setStyleSheet` seguinte estourava
        # "QLabel has been deleted". Como o `_set` é @slot_seguro, a exceção era engolida e TUDO
        # que vinha depois (título, notas, subtarefas, duração, OS pai) deixava de ser montado.
        self.resp_box = _person(d.get("responsavel"))
        h.addWidget(self.resp_box)
        b = QPushButton("trocar"); b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setToolTip("Atribuir esta OS a outra pessoa")
        b.setStyleSheet("QPushButton{background:transparent;border:1px solid rgba(255,255,255,0.14);"
                        "border-radius:7px;padding:2px 10px;color:%s;font-size:11.5px;min-height:0px;}"
                        "QPushButton:hover{border-color:%s;color:%s;}" % (MUTED, GREEN, GREEN))
        b.clicked.connect(self._trocar_responsavel)
        h.addWidget(b)
        return w

    @slot_seguro
    def _trocar_responsavel(self, *_):
        atual = self.resp_box.lb.text() if getattr(self, "resp_box", None) else ""
        dlg = TrocarResponsavelDialog(self, self._folio, atual)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.escolhido:
            return
        r = dlg.resultado or {}
        if not r.get("ok"):
            QMessageBox.critical(self, "Responsável", str(r.get("erro") or "não deu")); return
        self.resp_box.lb.setText(dlg.escolhido.get("name") or "—")
        QMessageBox.information(self, "Responsável",
                                "OS %s agora está com %s." % (self._folio, dlg.escolhido.get("name")))

    # ── ações ──
    def _clonar(self):
        self.accept(); abrir_clonar_os(self.parent(), self._wo, self._folio)

    @slot_seguro
    def _abrir_fluxo(self, *_):
        from steps.os_fluxo import abrir_fluxo_os
        abrir_fluxo_os(self, self._wo, self._folio)

    def _cancelar_os(self):
        from steps.cancelar_os import abrir_cancelar_os
        if abrir_cancelar_os(self, self._wo, self._folio):
            self.accept()

    @slot_seguro
    def _concluir_os(self, *_):
        # tarefas sem data de fim — sai do que o card JÁ carregou (`_tarefas` traz 'fim'), sem
        # ida extra ao servidor. A reconferência contra o servidor vem depois, no `_concluiu`.
        sem_fim = [t.get("titulo") or t.get("ativo") or "(tarefa sem título)"
                   for t in (self._tarefas or []) if not str(t.get("fim") or "").strip()]
        if _ConcluirDialog(self, self._folio or self._wo, self._sub_feitas,
                           self._sub_total, sem_fim).exec() != QDialog.DialogCode.Accepted:
            return
        self.b_concluir.setEnabled(False); self.b_concluir.setText("concluindo…")
        self._wcc = ApiWorker(api.concluir_os_checado, self._wo)
        self._wcc.ok.connect(self._concluiu); self._wcc.erro.connect(self._concluir_erro)
        self._wcc.start()

    @slot_seguro
    def _concluiu(self, res):
        self._wcc = None
        if isinstance(res, dict) and res.get("ok") is False:
            self.b_concluir.setEnabled(True); self.b_concluir.setText("Concluir OS")
            QMessageBox.critical(self, "Concluir OS", res.get("msg") or "Não foi possível concluir."); return
        self.b_concluir.setText("Concluir OS")
        # 2º lado do double check: o servidor confirma se a tarefa ficou mesmo com data de fim.
        # Sem isto o app anunciava "concluída" sem diferença nenhuma entre a OS que fechou
        # completa e a que fechou com o campo vazio — que é como a 10509 passou batida.
        chk = (res or {}).get("data_fim") if isinstance(res, dict) else None
        n = len((chk or {}).get("sem_fim") or [])
        if n:
            QMessageBox.warning(
                self, "OS concluída sem data de fim",
                "A OS %s foi concluída, mas %s ficou SEM data de fim.\n\n"
                "O campo não é preenchido depois: para registrar a data seria preciso ter usado "
                "o cronômetro de execução antes de fechar." %
                (self._folio or self._wo,
                 "a tarefa" if n == 1 else "%d das %d tarefas" % (n, (chk or {}).get("total") or n)))
        else:
            QMessageBox.information(self, "OS concluída",
                                    f"A OS {self._folio or self._wo} foi concluída.")
        self.accept()                                 # concluída → fecha o card

    @slot_seguro
    def _concluir_erro(self, m):
        self._wcc = None
        self.b_concluir.setEnabled(True); self.b_concluir.setText("Concluir OS")
        QMessageBox.critical(self, "Erro ao concluir OS", str(m))

    # ── chamado (OS filha, etiqueta CHAMADOS) ─────────────────────────────────
    def _buscar_chamado(self):
        """Procura a OS de chamado desta OS — define se o botão abre ou apenas leva ao existente."""
        self._wchm = ApiWorker(api.get_chamado_de_os, self._wo)
        self._wchm.ok.connect(self._achou_chamado)
        self._wchm.erro.connect(lambda *_: None)
        self._wchm.start()

    @slot_seguro
    def _achou_chamado(self, ch):
        self._wchm = None
        self._chamado = ch if isinstance(ch, dict) else None
        if self._chamado:
            folio = self._chamado.get("folio") or "?"
            self.chm_row.setVisible(True)
            self.chm_val.setText(str(folio))
            self.chm_val.set_click(self._ver_chamado)
            self.b_chamado.setText(f"Ver chamado {folio}")
            self.b_chamado.setToolTip(f"Chamado {folio} — {self._chamado.get('status') or ''}")
        else:
            self.chm_row.setVisible(False)
            self.b_chamado.setText("Abrir chamado")
            self.b_chamado.setToolTip("Cria a OS de chamado como filha desta, com a etiqueta CHAMADOS")
        self.b_chamado.setEnabled(bool(self._chamado) or bool(self._code))

    def _ver_chamado(self):
        """Abre o card do chamado, fechando o desta OS (mesmo padrão de OS pai/Solicitação)."""
        if not self._chamado:
            return
        par = self.parent(); cid = self._chamado.get("id"); folio = self._chamado.get("folio")
        self.accept()
        abrir_os_detalhe(par, cid, folio)

    @slot_seguro
    def _abrir_chamado(self, *_):
        if self._chamado:                     # já existe → só leva pra ele
            self._ver_chamado(); return
        if not self._code:
            QMessageBox.information(self, "Chamado",
                                    "Esta OS não tem um ativo resolvido — não dá pra abrir o chamado.")
            return
        from steps.abrir_chamado import abrir_chamado
        # respostas do técnico quando esta OS é uma INSPEÇÃO de chamado — o diálogo nasce
        # preenchido com elas. Best-effort: se a leitura falhar, o chamado abre em branco como antes.
        try:
            respostas = api.respostas_inspecao(self._wo)
        except Exception:
            respostas = {}
        novo = abrir_chamado(self, {"folio": self._folio, "ativo": self._ativo_txt,
                                    "usina": self._usina_txt, "id_work_order": self._wo,
                                    "event_date": self._event_date, "respostas": respostas})
        if novo:                              # criou → o vínculo aparece sem precisar reabrir o card
            self._buscar_chamado()

    # ── vínculos clicáveis (abre o card do respectivo valor, fechando o desta OS) ──
    def _abrir_os_pai(self):
        if not self._os_pai_id:
            return
        par = self.parent(); pid = self._os_pai_id; folio = self._os_pai_folio
        self.accept()
        abrir_os_detalhe(par, pid, folio)

    def _abrir_solic(self):
        if self._wsol is not None:
            return
        self.sol_val.setText(self.sol_val.text() + "  ·  abrindo…")
        self._wsol = ApiWorker(api.get_solicitacao_por_os, self._wo)
        self._wsol.ok.connect(self._abriu_solic); self._wsol.erro.connect(self._solic_erro)
        self._wsol.start()

    @slot_seguro
    def _abriu_solic(self, d):
        self._wsol = None
        if not isinstance(d, dict):
            QMessageBox.information(self, "Solicitação",
                                    "Não consegui abrir a solicitação (recarregue e tente de novo.)"); return
        from steps.historico_solic import SolicitacaoDialog      # tardio: evita import circular
        par = self.parent()
        self.accept()
        SolicitacaoDialog(par, d).exec()

    @slot_seguro
    def _solic_erro(self, m):
        self._wsol = None
        QMessageBox.critical(self, "Solicitação", f"Erro ao abrir a solicitação: {m}")

    def _abrir_anexos_sub(self):
        # UMA janela só: foto e nota de texto saem da MESMA subtarefa, então ver as duas juntas
        # é o que reconstitui o que o técnico registrou. A nota vira uma célula clicável da grade.
        imgs = [a for a in self._sub_imgs if a.get("url")]
        notas = [{"nota": (a.get("descricao") or a.get("nome") or "").strip(),
                  "descricao": a.get("descricao") or a.get("nome") or "nota"}
                 for a in self._sub_imgs if not a.get("url")]
        if imgs or notas:
            abrir_galeria(self, imgs + notas, "")   # legenda = a descrição da subtarefa
        outros = []
        if outros:
            # mesma tela dos anexos da OS: aqui costumam ser notas de texto, mas se um dia vier
            # documento pela subtarefa ele já abre e baixa, sem precisar de outro caminho
            abrir_documentos(self, [{"nome": (a.get("descricao") or a.get("nome") or "nota"),
                                     "url": a.get("url"), "user": a.get("user") or "",
                                     "desc": a.get("descricao") or ""} for a in outros],
                             "Anexos das subtarefas")
        if not imgs and not outros:
            QMessageBox.information(self, "Anexos das subtarefas", "Sem anexos nas subtarefas.")

    def _abrir_anexos_os(self):
        imgs = [{"url": a.get("url"), "thumb": None,
                 "descricao": f"{a.get('nome') or 'anexo'}  ·  {a.get('user') or '—'}"}
                for a in self._os_uniq if a.get("is_image") and a.get("url")]
        # com URL = arquivo p/ baixar (tela de documentos); sem URL = nota de texto, que vai
        # junto das fotos na galeria
        outros = [a for a in self._os_uniq if not (a.get("is_image") and a.get("url"))
                  and a.get("url")]
        notas = [{"nota": (a.get("desc") or a.get("nome") or "").strip(),
                  "descricao": a.get("nome") or "nota"}
                 for a in self._os_uniq if not a.get("url")]
        if imgs or notas:
            abrir_galeria(self, imgs + notas, self._ativo)
        if outros:
            linhas = []
            for a in outros:
                nome = a.get("nome") or "anexo"
                cont = (a.get("desc") or "").strip()
                if a.get("is_image"):                        # imagem cuja prévia não resolveu
                    linhas.append(f"• {nome}   (prévia indisponível)")
                else:                                        # nota de texto / documento
                    linhas.append(f"• {nome}" + (f"\n   {cont}" if cont and cont != nome else ""))
            QMessageBox.information(self, "Anexos da OS · texto e documentos", "\n".join(linhas))
        if not imgs and not outros:
            QMessageBox.information(self, "Anexos da OS", "Sem anexos nesta OS.")

    # ── etiquetas ──
    def _chip_etiq(self, nome, cor):
        lbl = QLabel(nome or "—")
        lbl.setStyleSheet(f"background:rgba({_cor_rgb(cor)},0.16);color:{_cor_hex(cor)};"
                          f"border:1px solid rgba({_cor_rgb(cor)},0.45);border-radius:999px;"
                          "padding:1px 9px;font-size:11px;font-weight:600;")
        return lbl

    def _set_etiquetas(self, etiquetas):
        self._etiquetas = [e for e in (etiquetas or []) if isinstance(e, dict)]
        while self._etiq_chips_l.count():
            it = self._etiq_chips_l.takeAt(0); w = it.widget()
            if w:
                w.deleteLater()
        if self._etiquetas:
            for e in self._etiquetas:
                self._etiq_chips_l.addWidget(self._chip_etiq(e.get("nome"), e.get("cor")))
            self.b_etiq.setText("editar")
        else:
            nen = QLabel("nenhuma"); nen.setStyleSheet("color:#5f6b85;font-size:11.5px;background:transparent;")
            self._etiq_chips_l.addWidget(nen)
            self.b_etiq.setText("definir")

    @slot_seguro
    def _editar_etiquetas(self, *_):
        dlg = _EtiquetasDialog(self, self._wo, self._folio, self._etiquetas)
        if dlg.exec() and dlg.resultado is not None:
            self._set_etiquetas(dlg.resultado)

    # ── carga ──
    def _carregar(self):
        self._w = ApiWorker(api.get_os_detalhes, self._wo)
        self._w.ok.connect(self._set); self._w.erro.connect(lambda m: self.hint.setText("⚠ " + m))
        self._w.start()
        self._wi = ApiWorker(api.get_os_subtarefa_anexos, self._wo)
        self._wi.ok.connect(self._set_fotos); self._wi.erro.connect(lambda *_: None)
        self._wi.start()
        self._wa = ApiWorker(api.get_os_anexos, self._wo)
        self._wa.ok.connect(self._set_anexos_os); self._wa.erro.connect(self._anexos_err)
        self._wa.start()

    @slot_seguro
    def _anexos_err(self, *_):
        self._wa = None
        self._anexos_loaded = True          # falhou → sem dedupe, mas destrava a contagem das subtarefas
        self._recount()

    @slot_seguro
    def _set_fotos(self, imgs):
        self._wi = None
        self._imagens = imgs or []
        self._recount()

    @slot_seguro
    def _set_anexos_os(self, anexos):
        self._wa = None
        self._anexos_os = anexos or []
        self._anexos_loaded = True
        uniq = list(dict.fromkeys(a.get("user") for a in self._anexos_os if a.get("user")))
        if uniq:
            self.card_os.set_sub("por " + (", ".join(uniq[:2]) + (" +" if len(uniq) > 2 else "")))
        self._recount()

    def _recount(self):
        """Subtarefas = fonte precisa por form item (mostra TODAS). Do card da OS tira o que já é anexo
        de subtarefa (evita o mesmo arquivo nos 2 cards). Só conta depois que os anexos da OS voltam."""
        if not self._anexos_loaded:
            return
        self._sub_imgs = list(self._imagens)                 # anexos das subtarefas: todos
        sub_nomes = set()
        for im in self._imagens:
            for k in (im.get("nome"), _fname(im.get("value")), _fname(im.get("url"))):
                if k:
                    sub_nomes.add(k.lower())
        self._os_uniq = [a for a in self._anexos_os
                         if (_fname(a.get("value")) or _fname(a.get("url"))
                             or (a.get("nome") or "")).lower() not in sub_nomes]
        self.card_sub.set_count(len(self._sub_imgs))
        self.card_os.set_count(len(self._os_uniq))

    @slot_seguro
    def _set(self, d):
        self._w = None
        d = d or {}
        self.hint.setText("")
        self.titulo.setText(f"OS {d.get('folio') or self._wo}")
        while self.badge_box.count():
            it = self.badge_box.takeAt(0); w = it.widget()
            if w:
                w.deleteLater()
        tipo = (d.get("tipo") or "").strip()
        if tipo:
            bd = QLabel(tipo)
            bd.setStyleSheet(f"color:{GREEN};background:rgba(166,226,46,0.14);border:1px solid "
                             "rgba(166,226,46,0.3);border-radius:999px;padding:3px 11px;font-size:12px;font-weight:600;")
            self.badge_box.addWidget(bd)
        self.ativo_lbl.setText(d.get("ativo") or d.get("descricao") or "—")

        # meta
        while self.meta_v.count():
            it = self.meta_v.takeAt(0); w = it.widget()
            if w:
                w.deleteLater()
        self._add_meta("cal", "Data do evento", api.fmt_data_br(d.get("event_date")))
        self._add_meta("calcheck", "Data fim", api.fmt_data_br(d.get("data_fim")) if d.get("data_fim") else "—")
        self._add_meta("user", "Atribuído a", self._linha_responsavel(d))
        self._add_meta("userplus", "Criado por", _person(d.get("criado_por")))
        # OS cancelada: o motivo é a informação que a pessoa vem procurar aqui. Não existe "quem
        # cancelou" no Fracttal — nenhum dos campos de pessoa do registro é isso (ver
        # `api.cancelamento_da_os`), então nem prometo a coluna.
        mot = (d.get("cancel_motivo") or "").strip()
        nota = (d.get("cancel_nota") or "").strip()
        if mot or nota:
            txt = mot or "—"
            if nota and nota.lower() != mot.lower():
                txt += " · %s" % (nota[:70] + ("…" if len(nota) > 70 else ""))
            self._add_meta("alert", "Cancelamento", txt)
        # vínculos no cabeçalho (OS pai só quando existe; Solicitação sempre) — Nº clicável abre o card
        _link = (f"color:{DESK};font-size:11.5px;font-weight:600;background:transparent;"
                 "text-decoration:underline;")
        pai = (d.get("os_pai") or "").strip()
        self._os_pai_id = d.get("os_pai_id"); self._os_pai_folio = pai
        self.pai_row.setVisible(bool(pai))
        if pai:
            self.pai_val.setText(f"Nº {pai}"); self.pai_val.setStyleSheet(_link)
            self.pai_val.set_click(self._abrir_os_pai if self._os_pai_id else None)
        sol = (d.get("solicitacao") or "").strip()
        if sol:
            self.sol_val.setText(f"Nº {sol}"); self.sol_val.setStyleSheet(_link)
            self.sol_val.set_click(self._abrir_solic)
        else:
            self.sol_val.setText("criada sem solicitação")
            self.sol_val.setStyleSheet("color:#6a7488;font-size:11.5px;font-style:italic;background:transparent;")
            self.sol_val.set_click(None)
        self.chm_val.setStyleSheet(_link)          # o Nº do chamado usa o mesmo estilo clicável

        # duração
        dur = api.duracao_os(d.get("event_date"), d.get("data_fim"))
        self.dur_big.setText(dur or "—")
        self.dur_note.setText("aproximada · entre evento e fim" if dur else "OS ainda sem data de fim")
        self._set_etiquetas(d.get("etiquetas"))

        # registro no Fracttal (tipo / classificação / criticidade) — estilo COS
        _g = "color:#A6E22E;font-weight:700"
        _sep = " &nbsp;&nbsp;·&nbsp;&nbsp; "
        self.meta_reg.setText(
            f"Tipo de tarefa <span style='{_g}'>{d.get('tipo') or '—'}</span>{_sep}"
            f"Classificação <span style='{_g}'>{d.get('classif') or '—'}</span>{_sep}"
            f"Criticidade <span style='{_g}'>{d.get('criticidade') or '—'}</span>")

        self.titulo_blk.setText(d.get("descricao") or "—")
        self.notas_blk.setText((d.get("notas") or "").strip() or "—")

        self._code = d.get("code") or None
        self._ativo = str(d.get("ativo") or "").strip()
        self._ativo_txt = self._ativo or (self._code or "")
        self._usina_txt = str(d.get("usina") or "").strip()
        self._event_date = d.get("event_date")
        self.b_chamado.setEnabled(bool(self._code))
        self._buscar_chamado()     # define se o botão é "Abrir chamado" ou "Ver chamado N"

        # subtarefas (acordeão) — filtradas pela tarefa escolhida quando a OS tem mais de uma
        subs = d.get("subtarefas") or []
        self._subs = subs
        self._tarefas = d.get("tarefas") or []
        # o % que o diálogo de Concluir mostra é o da OS INTEIRA: concluir fecha tudo, não a
        # tarefa que estiver na tela
        self._sub_feitas = sum(1 for s in subs if s.get("feito"))
        self._sub_total = len(subs)
        self._montar_seletor_tarefa()
        self._render_subs()
        self.hint.setText(f"{len(subs)} subtarefa(s)"
                          + (f" em {len(self._tarefas)} tarefas" if len(self._tarefas) > 1 else ""))

    # ── tarefas da OS ──
    def _montar_seletor_tarefa(self):
        """Povoa o combo de tarefa. Some quando a OS tem 0 ou 1 tarefa — que é a esmagadora maioria
        (corretiva de tracker, religamento): ali um seletor de um item só seria ruído."""
        tarefas = self._tarefas
        self.cb_tarefa.blockSignals(True)
        self.cb_tarefa.clear()
        if len(tarefas) > 1:
            feitas_por = {}
            for s in self._subs:
                k = s.get("id_tarefa")
                feitas_por.setdefault(k, [0, 0])
                feitas_por[k][1] += 1
                if s.get("feito"):
                    feitas_por[k][0] += 1
            self.cb_tarefa.addItem(f"Todas as tarefas  ·  {len(self._subs)} subtarefas", None)
            for i, t in enumerate(tarefas, start=1):
                f, tot = feitas_por.get(t.get("id"), [0, 0])
                rot = t.get("titulo") or t.get("ativo") or f"Tarefa {i}"
                self.cb_tarefa.addItem(f"{i}. {rot}  ·  {f}/{tot} subtarefas", t.get("id"))
            # nasce na 1ª tarefa, não em "Todas": a lista corrida de 45 subtarefas é justamente o
            # que não dá para ler — quem quiser o apanhado geral escolhe "Todas"
            self.cb_tarefa.setCurrentIndex(1)
            self.tarefa_cont.setText(f"{len(tarefas)} nesta OS")
        self.cb_tarefa.blockSignals(False)
        self.tarefa_wrap.setVisible(len(tarefas) > 1)
        self._pintar_info_tarefa()

    def _tarefa_sel(self):
        """Tarefa escolhida no combo, ou None quando é 'Todas' / a OS tem uma só."""
        tid = self.cb_tarefa.currentData() if self.cb_tarefa.count() else None
        return next((t for t in self._tarefas if t.get("id") == tid), None) if tid else None

    def _pintar_info_tarefa(self):
        t = self._tarefa_sel()
        if t is None:
            self.tarefa_info.setVisible(False)
            return
        _g = "color:#A6E22E;font-weight:700"
        _sep = " &nbsp;&nbsp;·&nbsp;&nbsp; "
        partes = [f"Ativo <span style='{_g}'>{t.get('ativo') or '—'}</span>",
                  f"Tipo <span style='{_g}'>{t.get('tipo') or '—'}</span>",
                  f"Programada <span style='{_g}'>{api.fmt_data_br(t.get('programada')) or '—'}</span>",
                  f"Estimada <span style='{_g}'>{_dur_seg(t.get('duracao'))}</span>"]
        if t.get("inicio") or t.get("fim"):
            partes.append("Execução <span style='%s'>%s → %s</span>"
                          % (_g, api.fmt_data_br(t.get("inicio")) or "—",
                             api.fmt_data_br(t.get("fim")) or "em aberto"))
        self.tarefa_info.setText(_sep.join(partes))
        self.tarefa_info.setVisible(True)

    @slot_seguro
    def _trocar_tarefa(self, _idx):
        self._pintar_info_tarefa()
        self._render_subs()

    def _render_subs(self):
        """Redesenha a lista do acordeão com as subtarefas da tarefa escolhida (ou todas)."""
        while self.subs_box.count():
            it = self.subs_box.takeAt(0); w = it.widget()
            if w:
                w.setParent(None); w.deleteLater()     # takeAt sozinho NÃO destrói o widget
        t = self._tarefa_sel()
        subs = ([s for s in self._subs if s.get("id_tarefa") == t.get("id")] if t is not None
                else self._subs)
        feitas = sum(1 for s in subs if s.get("feito"))
        for s in subs:
            self.subs_box.addWidget(_SubRow(s))
        if not subs:
            vazio = QLabel("(sem subtarefas)"); vazio.setObjectName("readbox")
            self.subs_box.addWidget(vazio)
        self.prog.setRange(0, max(1, len(subs))); self.prog.setValue(feitas)
        self.sub_done.setText(f"{feitas} de {len(subs)} concluídas" if subs else "sem subtarefas")
        self.sub_done.setVisible(bool(subs)); self.prog.setVisible(bool(subs))
