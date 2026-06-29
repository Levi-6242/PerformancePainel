"""Sugestões de OS (trackers) — lê a fila do dashboard (/api/trackers/os-sugeridas: trackers parados
>36h ou recorrentes) e, ao clicar em 'Criar OS', abre o wizard JÁ PREENCHIDO (ativo Estrutura
Trackers + descrição + tipo). Não cria nada sozinho — o PCM/técnico confirma no wizard."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
                             QTableWidgetItem, QHeaderView, QDialog, QLineEdit, QFormLayout)
import api
from workers import ApiWorker


class SugestoesTab(QWidget):
    criar_os = pyqtSignal(dict)            # clicar "Criar OS" → app abre o wizard preenchido

    def __init__(self):
        super().__init__()
        self._rows = []
        self._loaded = False
        self._w = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 12)
        lay.setSpacing(8)

        top = QHBoxLayout()
        top.addWidget(QLabel("<b>Sugestões de OS — trackers parados</b> "
                             "<span style='color:#8a90a2'>(parado &gt;36h ou recorrente · vem do dashboard)</span>"))
        top.addStretch(1)
        self.b_cfg = QPushButton("Configurar"); self.b_cfg.setObjectName("secondary")
        self.b_cfg.clicked.connect(self._configurar)
        self.b_upd = QPushButton("Atualizar"); self.b_upd.clicked.connect(self._atualizar)
        top.addWidget(self.b_cfg); top.addWidget(self.b_upd)
        lay.addLayout(top)

        self.hint = QLabel(""); self.hint.setObjectName("hint")
        lay.addWidget(self.hint)

        self.tbl = QTableWidget(0, 6)
        self.tbl.setHorizontalHeaderLabels(["Usina", "Tracker", "Cabine", "Motivo", "Aberto", "Ação"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.tbl, 1)

    def carregar_inicial(self):
        if not self._loaded:
            self._atualizar()

    def _atualizar(self):
        cfg = api.load_dash_config()
        if not api._dash_url(cfg):
            self.hint.setText("Configure a URL e a senha do dashboard (botão Configurar).")
            return
        self.hint.setText("Buscando sugestões no dashboard…")
        self.b_upd.setEnabled(False)
        self._w = ApiWorker(api.fetch_os_sugeridas, cfg)
        self._w.ok.connect(self._set_rows)
        self._w.erro.connect(self._err)
        self._w.finished.connect(lambda: setattr(self, "_w", None))
        self._w.start()

    def _set_rows(self, rows):
        self.b_upd.setEnabled(True)
        self._loaded = True
        self._rows = rows or []
        self.tbl.setRowCount(0)
        if not self._rows:
            self.hint.setText("Nenhuma sugestão no momento (nada parado >36h nem recorrente).")
            return
        self.hint.setText(f"{len(self._rows)} sugestão(ões) — clique em 'Criar OS' p/ abrir o wizard preenchido.")
        for sug in self._rows:
            r = self.tbl.rowCount(); self.tbl.insertRow(r)
            trk = sug.get("tracker_num") or sug.get("tracker") or ""
            cab = sug.get("cabine")
            vals = [sug.get("usina") or "",
                    (f"TRK{trk}" if str(trk).isdigit() else str(trk)),
                    (str(cab) if cab not in (None, "") else "—"),
                    sug.get("motivo_os") or "",
                    f"{round(sug.get('horas_aberto') or 0)}h"]
            for c, v in enumerate(vals):
                self.tbl.setItem(r, c, QTableWidgetItem(str(v)))
            b = QPushButton("Criar OS")
            b.clicked.connect(lambda _checked=False, s=sug: self.criar_os.emit(s))
            self.tbl.setCellWidget(r, 5, b)

    def _err(self, msg):
        self.b_upd.setEnabled(True)
        self.hint.setText("⚠ " + msg)

    def _configurar(self):
        if _ConfigDialog(self).exec() == QDialog.DialogCode.Accepted:
            self._atualizar()


class _ConfigDialog(QDialog):
    """URL + senha do dashboard (e, opcional, o caminho do tunnel_url.txt p/ pegar a URL sozinho)."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Configurar dashboard")
        self.setMinimumWidth(480)
        cfg = api.load_dash_config()
        form = QFormLayout(self)
        self.url = QLineEdit(cfg.get("url", ""))
        self.url.setPlaceholderText("https://....trycloudflare.com")
        self.senha = QLineEdit(cfg.get("senha", ""))
        self.senha.setEchoMode(QLineEdit.EchoMode.Password)
        self.tf = QLineEdit(cfg.get("tunnel_file", ""))
        self.tf.setPlaceholderText(r"...\Projeto API PV\tunnel_url.txt  (opcional)")
        form.addRow("URL do dashboard", self.url)
        form.addRow("Senha (DASH_PASSWORD)", self.senha)
        form.addRow("tunnel_url.txt (opcional)", self.tf)
        info = QLabel("Dica: preenchendo o caminho do tunnel_url.txt (no OneDrive), o app pega a URL "
                      "atual sozinho mesmo quando o túnel muda — não precisa colar a URL toda vez.")
        info.setWordWrap(True); info.setObjectName("hint")
        form.addRow(info)
        row = QHBoxLayout()
        b_x = QPushButton("Cancelar"); b_x.setObjectName("secondary"); b_x.clicked.connect(self.reject)
        b_ok = QPushButton("Salvar"); b_ok.clicked.connect(self._save)
        row.addWidget(b_x); row.addWidget(b_ok, 1)
        form.addRow(row)

    def _save(self):
        api.save_dash_config(self.url.text(), self.senha.text(), self.tf.text())
        self.accept()
