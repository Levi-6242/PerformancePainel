"""Card de detalhe de uma OS (ao clicar no nº no histórico): layout estruturado igual ao card de
Solicitação — cabeçalho com Nº + selo, ativo, metadados em grade, blocos Título/Notas, subtarefas
(clique mostra a resposta), Fotos da OS e ações."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QListWidget,
                             QListWidgetItem, QPushButton, QScrollArea, QWidget)
import api
from workers import ApiWorker, slot_seguro
from steps.clonar import abrir_clonar_os
from steps.galeria import abrir_galeria
from steps import cardui


def _data_br(iso):
    return api.fmt_data_br(iso)        # UTC do Fracttal → horário de Brasília


_ABERTOS = []   # mantém referência aos detalhes abertos (não-modais) p/ não serem coletados pelo GC


def abrir_os_detalhe(parent, id_work_order, folio=None):
    """Abre o detalhe da OS em janela NÃO-modal — dá p/ abrir/comparar várias OSs ao mesmo tempo."""
    dlg = OsDetalheDialog(parent, id_work_order, folio)
    dlg.setModal(False)
    _ABERTOS.append(dlg)
    dlg.finished.connect(lambda *_: _ABERTOS.remove(dlg) if dlg in _ABERTOS else None)
    dlg.show(); dlg.raise_(); dlg.activateWindow()


class OsDetalheDialog(QDialog):
    def __init__(self, parent, id_work_order, folio=None):
        super().__init__(parent)
        self._wo = id_work_order
        self._folio = folio
        self._code = None
        self._w = None
        self._wi = None
        self._imagens = []
        self._ativo = ""
        self.setWindowTitle(f"OS {folio or id_work_order}")
        self.setMinimumSize(500, 560)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        # ── cabeçalho: Nº + selo (tipo/status) ──
        head = QHBoxLayout(); head.setContentsMargins(16, 14, 16, 12); head.setSpacing(10)
        self.titulo = QLabel(f"<b style='font-size:14px'>OS {folio or ''}</b>")
        head.addWidget(self.titulo)
        self.badge_box = QHBoxLayout(); self.badge_box.setSpacing(6)
        head.addLayout(self.badge_box)
        head.addStretch(1)
        lay.addLayout(head)
        lay.addWidget(cardui.hline())

        # ── corpo (scroll) ──
        body = QWidget(); bl = QVBoxLayout(body); bl.setContentsMargins(16, 14, 16, 8); bl.setSpacing(14)
        self.ativo_lbl = QLabel("—"); self.ativo_lbl.setWordWrap(True)
        self.ativo_lbl.setStyleSheet("font-size:15px; font-weight:600;")
        bl.addWidget(self.ativo_lbl)

        self.grid = QGridLayout(); self.grid.setHorizontalSpacing(10); self.grid.setVerticalSpacing(6)
        self.grid.setColumnStretch(1, 1)
        bl.addLayout(self.grid)

        self.titulo_sec, self.titulo_blk = cardui.secao("TÍTULO", "—")
        bl.addWidget(self.titulo_sec)
        self.notas_sec, self.notas_blk = cardui.secao("NOTAS", "—")
        bl.addWidget(self.notas_sec)

        sub_cab = QLabel("SUBTAREFAS  <span style='color:#8a90a2; font-weight:400; letter-spacing:0'>"
                         "· clique numa subtarefa p/ ver a resposta</span>")
        sub_cab.setTextFormat(Qt.TextFormat.RichText)
        sub_cab.setStyleSheet("color:#8a90a2; font-size:11px; font-weight:600; letter-spacing:0.4px;")
        bl.addWidget(sub_cab)
        self.subs = QListWidget(); self.subs.setWordWrap(True); self.subs.setMaximumHeight(150)
        self.subs.setStyleSheet("background:#1d2130; border:1px solid #2c3142; border-radius:8px;")
        self.subs.itemClicked.connect(self._mostrar_resposta)
        bl.addWidget(self.subs)
        self.resp = QLabel("—"); self.resp.setWordWrap(True); self.resp.setTextFormat(Qt.TextFormat.RichText)
        self.resp.setStyleSheet(cardui.BLOCO + " color:#e6e8ef;")
        self.resp.hide()                                  # aparece só ao clicar numa subtarefa
        bl.addWidget(self.resp)

        self.b_fotos = QPushButton("Fotos da OS"); self.b_fotos.setObjectName("secondary")
        self.b_fotos.setEnabled(False)
        self.b_fotos.setToolTip("Fotos anexadas pelos técnicos nas subtarefas")
        self.b_fotos.clicked.connect(lambda: abrir_galeria(self, self._imagens, self._ativo))
        frow = QHBoxLayout(); frow.addWidget(self.b_fotos); frow.addStretch(1)
        bl.addLayout(frow)
        bl.addStretch(1)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame); scroll.setWidget(body)
        lay.addWidget(scroll, 1)

        # ── rodapé: hint + ações ──
        lay.addWidget(cardui.hline())
        self.hint = QLabel("carregando detalhes…"); self.hint.setObjectName("hint")
        hrow = QHBoxLayout(); hrow.setContentsMargins(16, 6, 16, 0)
        hrow.addWidget(self.hint); hrow.addStretch(1)
        lay.addLayout(hrow)
        foot = QHBoxLayout(); foot.setContentsMargins(16, 8, 16, 12); foot.setSpacing(8)
        b_clone = QPushButton("Clonar esta OS"); b_clone.clicked.connect(self._clonar)
        self.b_solic = QPushButton("Criar solicitação"); self.b_solic.setObjectName("secondary")
        self.b_solic.setEnabled(False); self.b_solic.clicked.connect(self._criar_solic)
        self.b_cancel = QPushButton("Cancelar OS")
        self.b_cancel.setStyleSheet("QPushButton{color:#e0736e; background:#241a1a; border:1px solid "
                                    "#6e3a37; border-radius:6px; padding:6px 14px;}"
                                    "QPushButton:hover{background:#2e2020;}")
        self.b_cancel.setToolTip("Cancela a OS no Fracttal (precisa de permissão na sua conta)")
        self.b_cancel.clicked.connect(self._cancelar_os)
        b = QPushButton("Fechar"); b.setObjectName("secondary"); b.clicked.connect(self.accept)
        foot.addWidget(b_clone); foot.addStretch(1)
        foot.addWidget(self.b_solic); foot.addWidget(self.b_cancel); foot.addWidget(b)
        lay.addLayout(foot)
        self.resize(520, 620)
        self._carregar()

    def _clonar(self):
        """Abre o diálogo de clonagem desta OS (mesmo ativo + tarefas; observação editável)."""
        self.accept()                                  # fecha o detalhe
        abrir_clonar_os(self.parent(), self._wo, self._folio)

    def _cancelar_os(self):
        """Abre o diálogo de cancelamento; se cancelar, fecha o detalhe (status mudou no Fracttal)."""
        from steps.cancelar_os import abrir_cancelar_os
        if abrir_cancelar_os(self, self._wo, self._folio):
            self.accept()

    def _criar_solic(self):
        """Vai p/ a aba 'Criar Solicitação' com o ativo desta OS pré-preenchido."""
        code = self._code
        par = self.parent()
        mw = par.window() if par is not None else None
        self.accept()                                  # fecha o detalhe
        if code and mw is not None and hasattr(mw, "abrir_solicitacao_de"):
            mw.abrir_solicitacao_de(code)

    def _carregar(self):
        self._w = ApiWorker(api.get_os_detalhes, self._wo)
        self._w.ok.connect(self._set)
        self._w.erro.connect(lambda m: self.hint.setText("⚠ " + m))
        self._w.start()
        self._wi = ApiWorker(api.get_os_imagens, self._wo)   # fotos em paralelo
        self._wi.ok.connect(self._set_fotos)
        self._wi.erro.connect(lambda *_: None)
        self._wi.start()

    @slot_seguro
    def _set_fotos(self, imgs):
        self._wi = None
        self._imagens = imgs or []
        n = len(self._imagens)
        self.b_fotos.setText(f"Fotos da OS ({n})")
        self.b_fotos.setEnabled(n > 0)

    def _limpar_layout(self, lay):
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()

    @slot_seguro
    def _set(self, d):
        self._w = None
        d = d or {}
        self.hint.setText("")
        self.titulo.setText(f"<b style='font-size:14px'>OS {d.get('folio') or self._wo}</b>")

        self._limpar_layout(self.badge_box)
        tipo = (d.get("tipo") or "").strip()
        if tipo:
            self.badge_box.addWidget(cardui.badge(tipo))

        self.ativo_lbl.setText(d.get("ativo") or d.get("descricao") or "—")

        self._limpar_layout(self.grid)
        campos = [("Data do evento", _data_br(d.get("event_date"))),
                  ("Atribuído a", (d.get("responsavel") or "—")),
                  ("Criado por", (d.get("criado_por") or "—"))]
        r = 0
        for rot, val in campos:
            self.grid.addWidget(cardui.rotulo(rot, 118), r, 0, Qt.AlignmentFlag.AlignTop)
            v = QLabel(str(val).strip() or "—"); v.setWordWrap(True)
            self.grid.addWidget(v, r, 1); r += 1
        sol = (d.get("solicitacao") or "").strip()
        if sol:
            self.grid.addWidget(cardui.rotulo("Solicitação ligada", 118), r, 0, Qt.AlignmentFlag.AlignTop)
            sv = QLabel(f"Nº {sol}"); sv.setStyleSheet("color:#6db3f2;")
            self.grid.addWidget(sv, r, 1); r += 1

        self.titulo_blk.setText(d.get("descricao") or "—")
        self.notas_blk.setText((d.get("notas") or "").strip() or "—")

        self._code = d.get("code") or None
        self._ativo = str(d.get("ativo") or "").strip()
        self.b_solic.setEnabled(bool(self._code))
        self.b_solic.setToolTip(f"Ativo: {d.get('ativo') or self._code}" if self._code
                                else "OS sem ativo resolvido")

        self.subs.clear()
        self.resp.hide()
        subs = d.get("subtarefas") or []
        for s in subs:
            mark = "☑" if s.get("feito") else "☐"
            stipo = s.get("tipo") or ""
            txt = f"{mark}  {s.get('descricao')}"
            if stipo and stipo != "—":
                txt += f"    [{stipo}]"
            it = QListWidgetItem(txt)
            it.setData(Qt.ItemDataRole.UserRole, s)
            self.subs.addItem(it)
        if not subs:
            self.subs.addItem(QListWidgetItem("(sem subtarefas)"))
        self.hint.setText(f"{len(subs)} subtarefa(s)")

    def _mostrar_resposta(self, item):
        """Clique numa subtarefa → mostra o tipo e a resposta dada (abaixo da lista)."""
        s = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(s, dict):
            self.resp.hide(); return
        resp = s.get("resposta") or "<i>(sem resposta registrada)</i>"
        self.resp.setText(f"<b>{s.get('descricao') or ''}</b>  "
                          f"<span style='color:#8a90a2'>· {s.get('tipo') or '—'}</span>"
                          f"<br><b>Resposta:</b> {resp}")
        self.resp.show()
