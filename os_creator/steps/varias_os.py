"""Diálogo 'Várias OSs' — cria várias OS de uma vez, em DOIS modos (escolha no topo):
  • Mesmo ativo:       1 ativo, VÁRIAS datas/horas de incidente (1 OS por data).
  • Ativos diferentes: VÁRIOS ativos marcados, 1 data/hora só (1 OS por ativo).
Em ambos, 'Esta tarefa já foi realizada?' cria as OS concluídas (data final + respostas)."""
import datetime as _dt
from PyQt6.QtCore import Qt, QDate, QTime, QDateTime
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
                             QLineEdit, QTextEdit, QPushButton, QMessageBox, QDateTimeEdit, QWidget,
                             QScrollArea, QRadioButton, QButtonGroup, QListWidget, QListWidgetItem)
import api
from workers import ApiWorker
from steps.step1 import ALLOWED_TIPOS
from steps.tipo_tarefa import TipoTarefaBox
from steps.finalizar import FinalizarPanel
from steps.searchcombo import tornar_pesquisavel
from steps.ospai import OsPaiPicker
from steps.ui import QSS_FORM, Card, campo, rotulo, Linha, icone_pix, MUTED

_SEL = "— selecione —"


def abrir_varias_os(parent):
    """Abre o COS como janela avulsa (embrulha o painel num QDialog). Inline (aba Criar OS) usa
    VariasOSsDialog direto com on_voltar."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("COS")
    dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint)
    dlg.setMinimumSize(640, 620); dlg.setSizeGripEnabled(True)
    lay = QVBoxLayout(dlg); lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(VariasOSsDialog(on_voltar=dlg.accept))
    dlg.exec()


class VariasOSsDialog(QWidget):
    """Painel COS — embutível na aba Criar OS ou dentro de um QDialog (janela avulsa). `on_voltar` é
    chamado ao Cancelar ou após criar (inline volta ao launcher; na janela fecha o diálogo)."""
    def __init__(self, parent=None, on_voltar=None):
        super().__init__(parent)
        self._on_voltar = on_voltar
        self._assets = api.load_assets_cached() or []
        self._wc = self._wr = None
        self._date_rows = []                 # [(row, de, de_fim, arrow, b_del)]
        self._checked = set()                # ids marcados (modo 'ativos diferentes')
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint)
        self.setMinimumSize(620, 600)
        self.setStyleSheet(QSS_FORM)                 # visual novo (inline no criar_stack não tem o global)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        _body = QWidget(); scroll.setWidget(_body)
        outer.addWidget(scroll)
        lay = QVBoxLayout(_body); lay.setContentsMargins(18, 14, 18, 14); lay.setSpacing(14)

        # ── topo: modo (compacto, sem card — suspenso no topo) ──
        self.rb_mesmo = QRadioButton("No mesmo ativo")
        self.rb_difer = QRadioButton("Em ativos diferentes")
        self.rb_mesmo.setChecked(True)
        self._grp_modo = QButtonGroup(self)
        self._grp_modo.addButton(self.rb_mesmo); self._grp_modo.addButton(self.rb_difer)
        self.rb_mesmo.toggled.connect(self._on_mode)
        self.sub_lbl = QLabel(""); self.sub_lbl.setObjectName("uiAjuda"); self.sub_lbl.setWordWrap(True)
        modo_row = QHBoxLayout(); modo_row.setSpacing(14)
        _ml = QLabel("Modo:"); _ml.setObjectName("uiCampoLabel")
        modo_row.addWidget(_ml); modo_row.addWidget(self.rb_mesmo); modo_row.addWidget(self.rb_difer)
        modo_row.addSpacing(10); modo_row.addWidget(self.sub_lbl, 1)
        lay.addLayout(modo_row)

        # ── Card 1: Ativo (cliente → usina → tipo → ativo/lista) ──
        self.cb_cli = QComboBox(); self.cb_cli.currentIndexChanged.connect(self._on_cli)
        self.cb_usi = QComboBox(); self.cb_usi.currentIndexChanged.connect(self._on_usi)
        self.cb_tipo = QComboBox(); self.cb_tipo.currentIndexChanged.connect(self._refresh_ativos)
        self.busca = QLineEdit(); self.busca.setPlaceholderText("Filtrar ativo por código ou nome…")
        self.busca.addAction(QIcon(icone_pix("search", MUTED, 15)), QLineEdit.ActionPosition.LeadingPosition)
        self.busca.textChanged.connect(self._refresh_ativos)
        self.cb_ativo = QComboBox(); self.cb_ativo.currentIndexChanged.connect(self._upd)
        self._sel_bar = QWidget(); self._sel_bar.setObjectName("uiGroup")     # botões do modo 'ativos diferentes'
        sbl = QHBoxLayout(self._sel_bar); sbl.setContentsMargins(0, 0, 0, 0)
        b_all = QPushButton("Selecionar todos"); b_all.setObjectName("secondary")
        b_all.clicked.connect(lambda: self._marcar_todos(True))
        b_none = QPushButton("Limpar"); b_none.setObjectName("secondary")
        b_none.clicked.connect(lambda: self._marcar_todos(False))
        sbl.addStretch(1); sbl.addWidget(b_all); sbl.addWidget(b_none)
        self._sel_bar.setVisible(False)
        self.lista_multi = QListWidget(); self.lista_multi.setMinimumHeight(150)
        self.lista_multi.itemChanged.connect(self._on_check_multi)
        self.lista_multi.itemClicked.connect(self._toggle_multi)
        self.lista_multi.setVisible(False)
        self.sel_lbl = QLabel("0 marcado(s)"); self.sel_lbl.setObjectName("uiAjuda"); self.sel_lbl.setVisible(False)
        c_ativo = Card(1, "Ativo")
        c_ativo.add(Linha(campo("Cliente", self.cb_cli, obrig=True), campo("Usina", self.cb_usi, obrig=True)))
        c_ativo.add(Linha(campo("Tipo de equipamento", self.cb_tipo), campo(" ", self.busca)))
        c_ativo.add(rotulo("Ativo", obrig=True))
        c_ativo.add(self.cb_ativo)
        c_ativo.add(self._sel_bar)
        c_ativo.add(self.lista_multi)
        c_ativo.add(self.sel_lbl)
        lay.addWidget(c_ativo)

        # ── Card 3: Detalhes da OS ──
        self.desc = QLineEdit(); self.desc.setPlaceholderText("ex.: Religamento da usina")
        self.desc.textChanged.connect(self._upd)
        self.obs = QTextEdit(); self.obs.setFixedHeight(56)
        c_det = Card(2, "Detalhes da OS")
        c_det.add(campo("Descrição da tarefa", self.desc, obrig=True))
        c_det.add(campo("Observação", self.obs, extra="(opcional — vale p/ todas)"))

        # ── Card 4: Classificação ──
        self._tt = TipoTarefaBox()
        c_cls = Card(3, "Classificação")
        c_cls.add(self._tt.grid)
        lay.addWidget(Linha(c_det, c_cls, quebra=820))       # Detalhes | Classificação lado a lado

        # ── Card 5: Datas do incidente ──
        self._dhdr_lbl = QLabel(""); self._dhdr_lbl.setObjectName("uiCampoLabel")
        self.b_add = QPushButton("+ Adicionar data"); self.b_add.setObjectName("secondary")
        self.b_add.clicked.connect(self._add_data)
        self._datas_box = QWidget(); self._datas_box.setObjectName("uiGroup")
        self._datas_lay = QVBoxLayout(self._datas_box)
        self._datas_lay.setContentsMargins(0, 0, 0, 0); self._datas_lay.setSpacing(6)
        self._datas_lay.addStretch(1)
        c_datas = Card(4, "Datas do incidente")
        c_datas.extra_head(self.b_add)
        c_datas.add(self._dhdr_lbl)
        c_datas.add(self._datas_box)

        # ── Card 6: Responsável ──
        self.cb_resp = QComboBox(); self.cb_resp.addItem("carregando…", None)
        tornar_pesquisavel(self.cb_resp)
        self.b_resp_reload = QPushButton("↻"); self.b_resp_reload.setObjectName("secondary")
        self.b_resp_reload.setFixedWidth(40)
        self.b_resp_reload.setToolTip("Recarregar responsáveis (use após relogar)")
        self.b_resp_reload.clicked.connect(self._carregar_resp)
        rrow = QWidget(); rrow.setObjectName("uiGroup")
        rrl = QHBoxLayout(rrow); rrl.setContentsMargins(0, 0, 0, 0); rrl.setSpacing(8)
        rrl.addWidget(self.cb_resp, 1); rrl.addWidget(self.b_resp_reload)
        self.os_pai = OsPaiPicker()
        self._fin = FinalizarPanel(["Procedimento"], com_datas=False)
        self._fin.toggled.connect(self._sync_fin)
        c_resp = Card(5, "Responsável")
        c_resp.add(campo("Requerido por", rrow, obrig=True, extra="(digite p/ pesquisar)"))
        c_resp.add(campo("Ela depende de outra OS?", self.os_pai, extra="(opcional — OS pai)"))
        c_resp.add(self._fin)
        lay.addWidget(Linha(c_datas, c_resp, quebra=820))    # Datas do incidente | Responsável lado a lado
        lay.addStretch(1)

        # rodapé FIXO (fora do scroll)
        row = QHBoxLayout(); row.setContentsMargins(18, 6, 18, 2)
        b_cancel = QPushButton("Cancelar"); b_cancel.setObjectName("secondary"); b_cancel.clicked.connect(self.reject)
        self.btn = QPushButton("Criar OSs"); self.btn.setEnabled(False); self.btn.clicked.connect(self._criar)
        row.addWidget(b_cancel); row.addWidget(self.btn, 1)
        outer.addLayout(row)
        self.hint = QLabel(""); self.hint.setObjectName("uiAjuda"); self.hint.setContentsMargins(18, 0, 18, 8)
        outer.addWidget(self.hint)

        self._add_data(); self._add_data()          # 2 linhas (modo mesmo ativo)
        self._fill_clientes()
        self._carregar_resp()
        self._on_mode()                              # ajusta visibilidade + labels iniciais

    # ── modo ──
    def _on_mode(self, *_):
        mesmo = self.rb_mesmo.isChecked()
        self.cb_ativo.setVisible(mesmo)
        self.lista_multi.setVisible(not mesmo)
        self._sel_bar.setVisible(not mesmo)
        self.sel_lbl.setVisible(not mesmo)
        self.b_add.setVisible(mesmo)
        self.sub_lbl.setText("1 ativo · várias datas/horas (uma OS por data)." if mesmo
                             else "Vários ativos marcados · uma data/hora só (uma OS por ativo).")
        if not mesmo:                                # ativos diferentes → 1 data só, sem remover
            while len(self._date_rows) > 1:
                self._del_data(self._date_rows[-1][0])
            if not self._date_rows:
                self._add_data()
        for (_r, _de, _df, _a, b_del) in self._date_rows:
            b_del.setVisible(mesmo)
        self._upd_dhdr()
        self._refresh_ativos()
        self._upd()

    def _upd_dhdr(self):
        fin = self._fin.is_finalizar()
        mesmo = self.rb_mesmo.isChecked()
        base = ("Datas/horas (inicial → final)" if fin else "Datas/horas do incidente") if mesmo \
               else ("Data/hora (inicial → final)" if fin else "Data/hora do incidente")
        sub = "Brasília — uma OS por linha" if mesmo else "Brasília — vale p/ todos os marcados"
        self._dhdr_lbl.setText(f"<b>{base}</b> <span style='color:#8a90a2'>({sub})</span>")

    # ── cascata do ativo ──
    def _fill_clientes(self):
        clientes = sorted({a["cliente"] for a in self._assets if a.get("cliente")})   # sem filtro: todos
        self.cb_cli.blockSignals(True); self.cb_cli.clear()
        self.cb_cli.addItem("— Selecione o cliente —"); self.cb_cli.addItems(clientes)
        self.cb_cli.blockSignals(False)
        self._on_cli()

    def _cli(self):
        return self.cb_cli.currentText() if self.cb_cli.currentIndex() > 0 else None

    def _usi(self):
        return self.cb_usi.currentText() if self.cb_usi.currentIndex() > 0 else None

    def _on_cli(self, *_):
        cli = self._cli()
        usinas = sorted({a["usina"] for a in self._assets
                         if a.get("cliente") == cli and a.get("usina")}) if cli else []
        self.cb_usi.blockSignals(True); self.cb_usi.clear()
        self.cb_usi.addItem("— Selecione a usina —"); self.cb_usi.addItems(usinas)
        self.cb_usi.setEnabled(bool(usinas)); self.cb_usi.blockSignals(False)
        self._on_usi()

    def _on_usi(self, *_):
        cli, usi = self._cli(), self._usi()
        tipos = sorted({a["tipo"] for a in self._assets
                        if a.get("cliente") == cli and a.get("usina") == usi
                        and a.get("tipo") in ALLOWED_TIPOS}) if usi else []
        self.cb_tipo.blockSignals(True); self.cb_tipo.clear()
        self.cb_tipo.addItem("Todos os tipos"); self.cb_tipo.addItems(tipos)
        self.cb_tipo.setEnabled(bool(tipos)); self.cb_tipo.blockSignals(False)
        self._refresh_ativos()

    def _cands(self):
        """Ativos que passam no filtro cascata + busca (lista p/ os dois modos)."""
        cli, usi = self._cli(), self._usi()
        if not usi:
            return []
        tipo = self.cb_tipo.currentText() if self.cb_tipo.currentIndex() > 0 else None
        txt = (self.busca.text() or "").strip().lower()
        out = []
        for a in self._assets:
            if a.get("cliente") != cli or a.get("usina") != usi:
                continue
            if a.get("tipo") not in ALLOWED_TIPOS:
                continue
            if tipo and a.get("tipo") != tipo:
                continue
            if txt and txt not in (a.get("label") or "").lower():
                continue
            out.append(a)
        return sorted(out, key=lambda x: x.get("label") or "")

    def _refresh_ativos(self, *_):
        cands = self._cands()
        if self.rb_mesmo.isChecked():                # dropdown (1 ativo)
            self.cb_ativo.blockSignals(True); self.cb_ativo.clear(); self.cb_ativo.addItem(_SEL, None)
            for a in cands:
                self.cb_ativo.addItem(a.get("label") or a.get("code") or "?", a)
            self.cb_ativo.blockSignals(False)
        else:                                        # lista com checkbox (vários ativos)
            self.lista_multi.blockSignals(True); self.lista_multi.clear()
            for a in cands:
                it = QListWidgetItem(a.get("label") or a.get("code") or "?")
                it.setData(Qt.ItemDataRole.UserRole, a)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Checked if a["id"] in self._checked
                                 else Qt.CheckState.Unchecked)
                self.lista_multi.addItem(it)
            self.lista_multi.blockSignals(False)
        self._upd()

    # ── multi-seleção (modo ativos diferentes) ──
    def _toggle_multi(self, it):
        it.setCheckState(Qt.CheckState.Unchecked if it.checkState() == Qt.CheckState.Checked
                         else Qt.CheckState.Checked)

    def _on_check_multi(self, it):
        a = it.data(Qt.ItemDataRole.UserRole)
        if not isinstance(a, dict):
            return
        if it.checkState() == Qt.CheckState.Checked:
            self._checked.add(a["id"])
        else:
            self._checked.discard(a["id"])
        self._upd()

    def _marcar_todos(self, marcar=True):
        """Marca/desmarca todos os ativos VISÍVEIS (do filtro atual)."""
        self.lista_multi.blockSignals(True)
        for i in range(self.lista_multi.count()):
            it = self.lista_multi.item(i)
            a = it.data(Qt.ItemDataRole.UserRole)
            it.setCheckState(Qt.CheckState.Checked if marcar else Qt.CheckState.Unchecked)
            if isinstance(a, dict):
                (self._checked.add if marcar else self._checked.discard)(a["id"])
        self.lista_multi.blockSignals(False)
        self._upd()

    # ── datas ──
    def _add_data(self, *_):
        row = QWidget(); row.setObjectName("uiGroup")
        h = QHBoxLayout(row); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(8)
        de = QDateTimeEdit(); de.setCalendarPopup(True); de.setDisplayFormat("dd/MM/yyyy HH:mm")
        de.setDateTime(QDateTime(QDate.currentDate(), QTime(8, 0)))
        de.setMinimumWidth(170)                          # tamanho da data, sem esticar p/ a linha toda
        h.addWidget(de)
        b_now = QPushButton("Agora"); b_now.setObjectName("secondary")
        b_now.setToolTip("Preenche com a data/hora atual")
        b_now.clicked.connect(lambda: de.setDateTime(QDateTime.currentDateTime()))
        h.addWidget(b_now)
        arrow = QLabel("→")
        h.addWidget(arrow)
        de_fim = QDateTimeEdit(); de_fim.setCalendarPopup(True); de_fim.setDisplayFormat("dd/MM/yyyy HH:mm")
        de_fim.setDateTime(QDateTime(QDate.currentDate(), QTime(8, 10)))
        de_fim.setToolTip("Data final (OS já realizada)"); de_fim.setMinimumWidth(170)
        h.addWidget(de_fim)
        b_del = QPushButton("Remover"); b_del.setObjectName("secondary")   # sem largura fixa → cresce com o texto
        b_del.clicked.connect(lambda: self._del_data(row))
        h.addWidget(b_del)
        h.addStretch(1)                                  # o espaço que sobra vai p/ o fim da linha
        fin = bool(getattr(self, "_fin", None) and self._fin.is_finalizar())
        arrow.setVisible(fin); de_fim.setVisible(fin)
        b_del.setVisible(self.rb_mesmo.isChecked() if hasattr(self, "rb_mesmo") else True)
        self._datas_lay.insertWidget(self._datas_lay.count() - 1, row)   # antes do stretch
        self._date_rows.append((row, de, de_fim, arrow, b_del))
        self._upd()

    def _del_data(self, row):
        self._date_rows = [t for t in self._date_rows if t[0] is not row]
        row.setParent(None); row.deleteLater()
        self._upd()

    def _sync_fin(self, on):
        """Mostra/esconde a Data final em cada linha conforme 'Esta tarefa já foi realizada?'."""
        for (_r, _de, de_fim, arrow, _b) in self._date_rows:
            arrow.setVisible(on); de_fim.setVisible(on)
        self._upd_dhdr()

    # ── responsável ──
    def _carregar_resp(self):
        self.cb_resp.clear(); self.cb_resp.addItem("carregando…", None)
        self.hint.setText("carregando responsáveis…")
        self._wr = ApiWorker(api.get_responsaveis)
        self._wr.ok.connect(self._set_resp)
        self._wr.erro.connect(self._resp_err)
        self._wr.start()

    def _resp_err(self, m):
        self._wr = None
        self.cb_resp.clear(); self.cb_resp.addItem("⚠ falha — relogue e clique em ↻", None)
        self.hint.setText("⚠ responsável: " + str(m))     # mostra o erro REAL (ex.: sessão expirada)

    def _set_resp(self, pessoas):
        self._wr = None
        self.hint.setText("")
        self.cb_resp.clear(); self.cb_resp.addItem(_SEL, None)
        for p in sorted(pessoas or [], key=lambda x: (x.get("name") or "").lower()):
            self.cb_resp.addItem(p.get("name") or p.get("code") or "?", p)
        self._upd()

    # ── habilita o botão ──
    def _upd(self, *_):
        if not hasattr(self, "btn"):
            return
        desc_ok = bool(self.desc.text().strip())
        if self.rb_mesmo.isChecked():
            ok = desc_ok and bool(self.cb_ativo.currentData()) and len(self._date_rows) > 0
        else:
            n = len(self._checked)
            self.sel_lbl.setText(f"{n} ativo(s) marcado(s)")
            ok = desc_ok and n > 0 and len(self._date_rows) > 0
        self.btn.setEnabled(ok)

    # ── criar ──
    def _criar(self):
        desc = self.desc.text().strip()
        if not desc:
            QMessageBox.warning(self, "Descrição", "Informe a descrição da tarefa."); return
        p = self.cb_resp.currentData()
        if not isinstance(p, dict) or not p.get("id_personnel"):
            QMessageBox.warning(self, "Responsável", "Escolha o responsável (requerido por)."); return
        if not self._tt.is_ready():
            QMessageBox.warning(self, "Tipo de tarefa", "O tipo de tarefa ainda não carregou (ou a "
                                "sessão expirou). Aguarde um instante ou relogue."); return
        if not self._date_rows:
            QMessageBox.warning(self, "Datas", "Informe a data/hora."); return
        brt = _dt.timezone(_dt.timedelta(hours=-3))     # data/hora escolhida é de Brasília
        fin_on = self._fin.is_finalizar()
        finalizar = None

        if self.rb_mesmo.isChecked():
            # ── 1 ativo, várias datas ──
            ativo = self.cb_ativo.currentData()
            if not isinstance(ativo, dict):
                QMessageBox.warning(self, "Ativo", "Selecione um ativo."); return
            if fin_on:
                datas = []
                for (_r, de, de_fim, _a, _b) in self._date_rows:
                    ini = de.dateTime().toPyDateTime().replace(tzinfo=brt)
                    fim = de_fim.dateTime().toPyDateTime().replace(tzinfo=brt)
                    if fim < ini:
                        QMessageBox.warning(self, "Datas", "A Data final não pode ser anterior à inicial "
                                            f"(linha {ini:%d/%m %H:%M})."); return
                    datas.append((ini, fim))
                finalizar = {"to_in_review": self._fin.to_in_review(), "id_assigned_user": p.get("id_personnel"),
                             "name": p.get("name"), "respostas": self._fin.respostas()}
            else:
                datas = [de.dateTime().toPyDateTime().replace(tzinfo=brt) for (_r, de, _f, _a, _b) in self._date_rows]
            self.btn.setEnabled(False)
            self.hint.setText(f"criando {len(datas)} OS… (pode levar alguns segundos)")
            self._wc = ApiWorker(api.create_work_orders_datas, ativo, desc, self._tt.descricao_tipo(),
                                 [], datas, p.get("code"), p.get("name"), p.get("id_personnel"),
                                 None, self.obs.toPlainText().strip(), tipo=self._tt.tipo_dict(),
                                 finalizar=finalizar, id_parent=self.os_pai.id_parent())
        else:
            # ── vários ativos, 1 data ──
            assets = [a for a in self._assets if a["id"] in self._checked]
            if not assets:
                QMessageBox.warning(self, "Ativos", "Marque ao menos um ativo."); return
            (_r, de, de_fim, _a, _b) = self._date_rows[0]
            event_date = de.dateTime().toPyDateTime().replace(tzinfo=brt)
            if fin_on:
                fim = de_fim.dateTime().toPyDateTime().replace(tzinfo=brt)
                if fim < event_date:
                    QMessageBox.warning(self, "Datas", "A Data final não pode ser anterior à inicial."); return
                finalizar = {"to_in_review": self._fin.to_in_review(), "final_date": fim,
                             "id_assigned_user": p.get("id_personnel"), "name": p.get("name"),
                             "respostas": self._fin.respostas()}
            self.btn.setEnabled(False)
            self.hint.setText(f"criando {len(assets)} OS… (pode levar alguns segundos)")
            self._wc = ApiWorker(api.create_work_orders_bulk, assets, desc, self._tt.descricao_tipo(),
                                 [], "", p.get("code"), p.get("name"), p.get("id_personnel"),
                                 None, self.obs.toPlainText().strip(), tipo=self._tt.tipo_dict(),
                                 finalizar=finalizar, event_date=event_date,
                                 id_parent=self.os_pai.id_parent())
        self._wc.ok.connect(self._ok)
        self._wc.erro.connect(self._err)
        self._wc.start()

    def _voltar(self):
        if self._on_voltar:
            self._on_voltar()

    def accept(self):        # compat: sucesso → volta (inline) / fecha (janela)
        self._voltar()

    def reject(self):        # compat: Cancelar → volta / fecha
        self._voltar()

    def _ok(self, res):
        self._wc = None
        self.btn.setEnabled(True)
        res = res if isinstance(res, list) else []
        ok = [r for r in res if r.get("ok")]
        fail = [r for r in res if not r.get("ok")]
        folios = [str(r["os"].get("wo_folio")) for r in ok if r.get("os", {}).get("wo_folio")]
        msg = f"{len(ok)} OS criada(s)" + (f" — Nº {', '.join(folios)}" if folios else "") + "."
        avisos = [r["os"]["aviso"] for r in ok if r.get("os", {}).get("aviso")]
        if avisos:
            msg += "\n\nAvisos:\n- " + "\n- ".join(avisos[:6])
        if fail:
            msg += "\n\nFalhas:\n- " + "\n- ".join(
                f"{r.get('data') or r.get('code')}: {r.get('erro')}" for r in fail[:8])
        if ok:
            QMessageBox.information(self, "OSs criadas", msg)
            self.accept()
        else:
            QMessageBox.critical(self, "Erro", msg or "Nenhuma OS criada.")
            self.hint.setText("")

    def _err(self, m):
        self._wc = None
        self.btn.setEnabled(True); self.hint.setText("")
        QMessageBox.critical(self, "Erro ao criar OSs", m)
