"""Diálogo 'Várias OSs' — cria várias OS de uma vez, em DOIS modos (escolha no topo):
  • Mesmo ativo:       1 ativo, VÁRIAS datas/horas de incidente (1 OS por data).
  • Ativos diferentes: VÁRIOS ativos marcados, 1 data/hora só (1 OS por ativo).
Em ambos, 'Esta tarefa já foi realizada?' cria as OS concluídas (data final + respostas)."""
import datetime as _dt
from PyQt6.QtCore import Qt, QDate, QTime, QDateTime
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
                             QLineEdit, QTextEdit, QPushButton, QMessageBox, QDateTimeEdit, QWidget,
                             QScrollArea, QRadioButton, QButtonGroup, QListWidget, QListWidgetItem)
import api
from workers import ApiWorker
from steps.step1 import ALLOWED_TIPOS
from steps.tipo_tarefa import TipoTarefaBox
from steps.finalizar import FinalizarPanel
from steps.searchcombo import tornar_pesquisavel

_SEL = "— selecione —"


def abrir_varias_os(parent):
    VariasOSsDialog(parent).exec()


class VariasOSsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._assets = api.load_assets_cached() or []
        self._wc = self._wr = None
        self._date_rows = []                 # [(row, de, de_fim, arrow, b_del)]
        self._checked = set()                # ids marcados (modo 'ativos diferentes')
        self.setWindowTitle("COS")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint)
        self.setMinimumSize(620, 600)
        self.setSizeGripEnabled(True)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        _body = QWidget(); scroll.setWidget(_body)
        outer.addWidget(scroll)
        lay = QVBoxLayout(_body); lay.setContentsMargins(16, 14, 16, 14); lay.setSpacing(8)

        lay.addWidget(QLabel("<b style='font-size:15px'>COS — várias OSs</b>"))

        # ── modo: mesmo ativo × ativos diferentes ──
        mrow = QHBoxLayout()
        self.rb_mesmo = QRadioButton("No mesmo ativo")
        self.rb_difer = QRadioButton("Em ativos diferentes")
        self.rb_mesmo.setChecked(True)
        self._grp_modo = QButtonGroup(self)
        self._grp_modo.addButton(self.rb_mesmo); self._grp_modo.addButton(self.rb_difer)
        self.rb_mesmo.toggled.connect(self._on_mode)
        mrow.addWidget(self.rb_mesmo); mrow.addWidget(self.rb_difer); mrow.addStretch(1)
        lay.addLayout(mrow)
        self.sub_lbl = QLabel(""); self.sub_lbl.setObjectName("hint"); self.sub_lbl.setWordWrap(True)
        lay.addWidget(self.sub_lbl)

        # ── ativo: cliente → usina → tipo ──
        grid = QGridLayout(); grid.setHorizontalSpacing(10); grid.setVerticalSpacing(3)
        self.cb_cli = QComboBox(); self.cb_cli.currentIndexChanged.connect(self._on_cli)
        self.cb_usi = QComboBox(); self.cb_usi.currentIndexChanged.connect(self._on_usi)
        self.cb_tipo = QComboBox(); self.cb_tipo.currentIndexChanged.connect(self._refresh_ativos)
        grid.addWidget(QLabel("Cliente"), 0, 0); grid.addWidget(self.cb_cli, 1, 0)
        grid.addWidget(QLabel("Usina"), 0, 1); grid.addWidget(self.cb_usi, 1, 1)
        grid.addWidget(QLabel("Tipo de equipamento"), 0, 2); grid.addWidget(self.cb_tipo, 1, 2)
        for c in (0, 1, 2):
            grid.setColumnStretch(c, 1)
        lay.addLayout(grid)
        self.busca = QLineEdit(); self.busca.setPlaceholderText("filtrar ativo por código/nome…")
        self.busca.textChanged.connect(self._refresh_ativos)
        lay.addWidget(self.busca)
        # seletor de ativo: dropdown (mesmo ativo) OU lista com checkbox (ativos diferentes)
        self.cb_ativo = QComboBox(); self.cb_ativo.currentIndexChanged.connect(self._upd)
        lay.addWidget(self.cb_ativo)
        self._sel_bar = QWidget()                    # botões só do modo 'ativos diferentes'
        sbl = QHBoxLayout(self._sel_bar); sbl.setContentsMargins(0, 0, 0, 0)
        b_all = QPushButton("Selecionar todos"); b_all.setObjectName("secondary")
        b_all.clicked.connect(lambda: self._marcar_todos(True))
        b_none = QPushButton("Limpar"); b_none.setObjectName("secondary")
        b_none.clicked.connect(lambda: self._marcar_todos(False))
        sbl.addStretch(1); sbl.addWidget(b_all); sbl.addWidget(b_none)
        self._sel_bar.setVisible(False)
        lay.addWidget(self._sel_bar)
        self.lista_multi = QListWidget(); self.lista_multi.setMinimumHeight(150)
        self.lista_multi.itemChanged.connect(self._on_check_multi)
        self.lista_multi.itemClicked.connect(self._toggle_multi)
        self.lista_multi.setVisible(False)
        lay.addWidget(self.lista_multi)
        self.sel_lbl = QLabel("0 marcado(s)"); self.sel_lbl.setObjectName("hint"); self.sel_lbl.setVisible(False)
        lay.addWidget(self.sel_lbl)

        # ── descrição + tipo de tarefa + classif 1/2 + criticidade ──
        lay.addWidget(QLabel("<b>Descrição da tarefa</b>"))
        self.desc = QLineEdit(); self.desc.setPlaceholderText("ex.: Religamento da usina")
        self.desc.textChanged.connect(self._upd)
        lay.addWidget(self.desc)
        self._tt = TipoTarefaBox()
        lay.addLayout(self._tt.grid)

        # ── observação ──
        lay.addWidget(QLabel("<b>Observação</b> <span style='color:#8a90a2'>(opcional — vale p/ todas)</span>"))
        self.obs = QTextEdit(); self.obs.setFixedHeight(44)
        lay.addWidget(self.obs)

        # ── datas/horas do incidente ──
        dhdr = QHBoxLayout()
        self._dhdr_lbl = QLabel("")
        dhdr.addWidget(self._dhdr_lbl, 1)
        self.b_add = QPushButton("+ Adicionar data"); self.b_add.setObjectName("secondary")
        self.b_add.clicked.connect(self._add_data)
        dhdr.addWidget(self.b_add)
        lay.addLayout(dhdr)
        self._datas_box = QWidget(); self._datas_lay = QVBoxLayout(self._datas_box)
        self._datas_lay.setContentsMargins(0, 0, 0, 0); self._datas_lay.setSpacing(3)
        self._datas_lay.addStretch(1)
        lay.addWidget(self._datas_box)

        # ── responsável ──
        lay.addWidget(QLabel("<b>Requerido por (responsável)</b> "
                             "<span style='color:#8a90a2'>(obrigatório · digite p/ pesquisar)</span>"))
        rrow = QHBoxLayout()
        self.cb_resp = QComboBox(); self.cb_resp.addItem("carregando…", None)
        tornar_pesquisavel(self.cb_resp)
        self.b_resp_reload = QPushButton("↻"); self.b_resp_reload.setObjectName("secondary")
        self.b_resp_reload.setFixedWidth(40)
        self.b_resp_reload.setToolTip("Recarregar responsáveis (use após relogar)")
        self.b_resp_reload.clicked.connect(self._carregar_resp)
        rrow.addWidget(self.cb_resp, 1); rrow.addWidget(self.b_resp_reload)
        lay.addLayout(rrow)

        # ── "Esta tarefa já foi realizada?" ──
        self._fin = FinalizarPanel(["Procedimento"], com_datas=False)
        self._fin.toggled.connect(self._sync_fin)
        lay.addWidget(self._fin)

        # rodapé FIXO (fora do scroll)
        row = QHBoxLayout(); row.setContentsMargins(16, 6, 16, 2)
        b_cancel = QPushButton("Cancelar"); b_cancel.setObjectName("secondary"); b_cancel.clicked.connect(self.reject)
        self.btn = QPushButton("Criar OSs"); self.btn.setEnabled(False); self.btn.clicked.connect(self._criar)
        row.addWidget(b_cancel); row.addWidget(self.btn, 1)
        outer.addLayout(row)
        self.hint = QLabel(""); self.hint.setObjectName("hint"); self.hint.setContentsMargins(16, 0, 16, 8)
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
        row = QWidget(); h = QHBoxLayout(row); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(6)
        de = QDateTimeEdit(); de.setCalendarPopup(True); de.setDisplayFormat("dd/MM/yyyy HH:mm")
        de.setDateTime(QDateTime(QDate.currentDate(), QTime(8, 0)))
        h.addWidget(de, 1)
        b_now = QPushButton("Agora"); b_now.setObjectName("secondary"); b_now.setFixedWidth(64)
        b_now.setToolTip("Preenche com a data/hora atual")
        b_now.clicked.connect(lambda: de.setDateTime(QDateTime.currentDateTime()))
        h.addWidget(b_now)
        arrow = QLabel("→")
        h.addWidget(arrow)
        de_fim = QDateTimeEdit(); de_fim.setCalendarPopup(True); de_fim.setDisplayFormat("dd/MM/yyyy HH:mm")
        de_fim.setDateTime(QDateTime(QDate.currentDate(), QTime(8, 10)))
        de_fim.setToolTip("Data final (OS já realizada)")
        h.addWidget(de_fim, 1)
        b_del = QPushButton("Remover"); b_del.setObjectName("secondary"); b_del.setFixedWidth(74)
        b_del.clicked.connect(lambda: self._del_data(row))
        h.addWidget(b_del)
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
                                 finalizar=finalizar)
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
                                 finalizar=finalizar, event_date=event_date)
        self._wc.ok.connect(self._ok)
        self._wc.erro.connect(self._err)
        self._wc.start()

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
