"""Dialog de detalhe de uma OS (ao clicar no nº no histórico): Data do Evento, Notas, Subtarefas."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QListWidget,
                             QListWidgetItem, QPushButton)
import api
from workers import ApiWorker
from steps.clonar import abrir_clonar_os


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
        self.setWindowTitle(f"OS {folio or id_work_order}")
        self.setMinimumSize(540, 500)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        self.titulo = QLabel(f"<b style='font-size:15px'>OS {folio or ''}</b>")
        lay.addWidget(self.titulo)
        self.desc = QLabel(""); self.desc.setWordWrap(True)
        lay.addWidget(self.desc)
        self.data_ev = QLabel("")
        lay.addWidget(self.data_ev)
        self.atrib = QLabel("")
        lay.addWidget(self.atrib)

        lay.addWidget(QLabel("<b>Notas</b>"))
        self.notas = QTextEdit(); self.notas.setReadOnly(True); self.notas.setFixedHeight(120)
        lay.addWidget(self.notas)

        lay.addWidget(QLabel("<b>Subtarefas</b>  "
                             "<span style='color:#8a90a2'>· clique numa subtarefa p/ ver a resposta</span>"))
        self.subs = QListWidget(); self.subs.setWordWrap(True)
        self.subs.itemClicked.connect(self._mostrar_resposta)
        lay.addWidget(self.subs, 1)
        self.resp = QLabel("—"); self.resp.setWordWrap(True); self.resp.setTextFormat(Qt.TextFormat.RichText)
        self.resp.setStyleSheet("background:#1d2130; border:1px solid #2c3142; border-radius:4px; "
                                "padding:6px; color:#e6e8ef;")
        lay.addWidget(self.resp)

        self.hint = QLabel("carregando detalhes…"); self.hint.setObjectName("hint")
        lay.addWidget(self.hint)
        brow = QHBoxLayout()
        b_clone = QPushButton("⧉ Clonar esta OS"); b_clone.clicked.connect(self._clonar)
        self.b_solic = QPushButton("Criar Solicitação deste ativo"); self.b_solic.setObjectName("secondary")
        self.b_solic.setEnabled(False); self.b_solic.clicked.connect(self._criar_solic)
        b = QPushButton("Fechar"); b.setObjectName("secondary"); b.clicked.connect(self.accept)
        self.b_cancel = QPushButton("Cancelar OS"); self.b_cancel.setObjectName("secondary")
        self.b_cancel.setToolTip("Cancela a OS no Fracttal (precisa de permissão na sua conta)")
        self.b_cancel.clicked.connect(self._cancelar_os)
        brow.addWidget(b_clone, 1); brow.addWidget(self.b_solic, 1); brow.addWidget(self.b_cancel); brow.addWidget(b)
        lay.addLayout(brow)
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

    def _set(self, d):
        self._w = None
        d = d or {}
        self.hint.setText("")
        self.titulo.setText(f"<b style='font-size:15px'>OS {d.get('folio') or self._wo}</b>")
        tipo = d.get("tipo") or ""
        self.desc.setText(f"<b>{d.get('descricao') or '—'}</b>"
                          + (f"  <span style='color:#8a90a2'>· {tipo}</span>" if tipo else ""))
        self.data_ev.setText(f"<b>Data do Evento:</b> {_data_br(d.get('event_date'))}")
        atrib = (d.get("responsavel") or "").strip()
        self.atrib.setText(f"<b>Atribuído a:</b> {atrib}" if atrib
                           else "<b>Atribuído a:</b> <span style='color:#8a90a2'>—</span>")
        self._code = d.get("code") or None
        self.b_solic.setEnabled(bool(self._code))
        self.b_solic.setToolTip(f"Ativo: {d.get('ativo') or self._code}" if self._code
                                else "OS sem ativo resolvido")
        self.notas.setPlainText(d.get("notas") or "—")
        self.subs.clear()
        self.resp.setText("—")
        subs = d.get("subtarefas") or []
        for s in subs:
            mark = "☑" if s.get("feito") else "☐"
            tipo = s.get("tipo") or ""
            txt = f"{mark}  {s.get('descricao')}"
            if tipo and tipo != "—":
                txt += f"    [{tipo}]"
            it = QListWidgetItem(txt)
            it.setData(Qt.ItemDataRole.UserRole, s)
            self.subs.addItem(it)
        if not subs:
            self.subs.addItem(QListWidgetItem("(sem subtarefas)"))
        self.hint.setText(f"{len(subs)} subtarefa(s)")

    def _mostrar_resposta(self, item):
        """Clique numa subtarefa → mostra o tipo e a resposta dada."""
        s = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(s, dict):
            self.resp.setText("—"); return
        resp = s.get("resposta") or "<i>(sem resposta registrada)</i>"
        self.resp.setText(f"<b>{s.get('descricao') or ''}</b>  "
                          f"<span style='color:#8a90a2'>· {s.get('tipo') or '—'}</span>"
                          f"<br><b>Resposta:</b> {resp}")
