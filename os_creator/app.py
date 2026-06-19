"""app.py — janela principal: navegação entre steps, tema escuro, stay-on-top,
overlay de loading e Step 4 (atribuição de responsável)."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
                             QLabel, QProgressBar, QDialog, QLineEdit, QListWidget,
                             QListWidgetItem, QPushButton, QMessageBox)
import api
from workers import ApiWorker
from steps.step1 import Step1
from steps.step2 import Step2
from steps.step3 import Step3

STEP_LABELS = ["Ativo + Data", "Detalhes da Tarefa", "Sub tarefas", "Responsável"]

DARK_QSS = """
QWidget { background:#14161f; color:#e6e8ef; font-family:'Segoe UI',Arial,sans-serif; font-size:13px; }
QLabel#steptitle { color:#9aa0b4; font-size:12px; }
QLabel#hint { color:#8a90a2; font-size:11px; }
QLineEdit,QTextEdit,QComboBox,QDateEdit,QListWidget {
  background:#1d2130; border:1px solid #2c3142; border-radius:6px; padding:6px; color:#e6e8ef; }
QLineEdit:focus,QTextEdit:focus,QComboBox:focus,QDateEdit:focus { border:1px solid #4f7cff; }
QListWidget::item { padding:5px; border-radius:4px; }
QListWidget::item:selected { background:#2f3a66; }
QPushButton { background:#4f7cff; color:#fff; border:none; border-radius:7px; padding:9px 14px; font-weight:600; }
QPushButton:hover { background:#5d87ff; }
QPushButton:disabled { background:#2c3142; color:#6b7080; }
QPushButton#secondary { background:#262b3b; color:#cdd2e0; font-weight:500; }
QPushButton#secondary:hover { background:#2f3547; }
QProgressBar { background:#1d2130; border:none; border-radius:3px; }
QProgressBar::chunk { background:#4f7cff; border-radius:3px; }
QScrollBar:vertical { background:transparent; width:10px; margin:0; }
QScrollBar::handle:vertical { background:#2c3142; border-radius:5px; min-height:24px; }
QScrollBar::add-line,QScrollBar::sub-line { height:0; }
"""


class LoadingOverlay(QWidget):
    """Overlay semi-transparente com spinner (barra indeterminada) sobre a janela."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setStyleSheet("background:rgba(10,12,20,0.80);")
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(12)
        self.lbl = QLabel("…")
        self.lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl.setStyleSheet("color:#fff;font-size:13px;background:transparent;")
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)            # indeterminado = spinner
        self.bar.setFixedWidth(220)
        self.bar.setTextVisible(False)
        lay.addWidget(self.lbl)
        lay.addWidget(self.bar, 0, Qt.AlignmentFlag.AlignCenter)
        self.hide()

    def show_msg(self, msg):
        self.lbl.setText(msg)
        if self.parent():
            self.resize(self.parent().size())
        self.raise_()
        self.show()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Criar OS — Fracttal")
        self.setFixedSize(500, 700)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.data = {}
        self._workers = []

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # cabeçalho: título do passo + barra de progresso
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(18, 12, 18, 8)
        tl.setSpacing(6)
        self.steplbl = QLabel()
        self.steplbl.setObjectName("steptitle")
        self.steplbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prog = QProgressBar()
        self.prog.setRange(0, 4)
        self.prog.setTextVisible(False)
        self.prog.setFixedHeight(6)
        tl.addWidget(self.steplbl)
        tl.addWidget(self.prog)
        root.addWidget(top)

        # steps
        self.stack = QStackedWidget()
        self.s1, self.s2, self.s3 = Step1(), Step2(), Step3()
        for s in (self.s1, self.s2, self.s3):
            self.stack.addWidget(s)
        root.addWidget(self.stack, 1)

        # navegação
        self.s1.avancar.connect(lambda: self._go(1))
        self.s2.voltar.connect(lambda: self._go(0))
        self.s2.avancar.connect(lambda: self._go(2))
        self.s3.voltar.connect(lambda: self._go(1))
        self.s3.concluir.connect(self._gerar_os)
        self.s1.recarregar.connect(lambda: self._carregar_ativos(force=True))

        self.overlay = LoadingOverlay(central)
        self._go(0)
        self._carregar_ativos()

    # ── navegação / overlay ──
    def _go(self, idx):
        self.stack.setCurrentIndex(idx)
        self.prog.setValue(idx + 1)
        self.steplbl.setText(f"Passo {idx + 1} de 4  ·  {STEP_LABELS[idx]}")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if getattr(self, "overlay", None):
            self.overlay.resize(self.centralWidget().size())

    def _run(self, fn, on_ok, msg, *args):
        """Roda fn em background com overlay; on_ok(res) em sucesso, QMessageBox em erro."""
        self.overlay.show_msg(msg)
        w = ApiWorker(fn, *args)
        self._workers.append(w)

        def _ok(res):
            self.overlay.hide()
            on_ok(res)

        def _err(m):
            self.overlay.hide()
            QMessageBox.critical(self, "Erro", m)

        w.ok.connect(_ok)
        w.erro.connect(_err)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        w.start()

    # ── carregamento inicial dos ativos (background) ──
    def _carregar_ativos(self, force=False):
        self.overlay.show_msg("Recarregando ativos do Fracttal…" if force
                              else "Carregando ativos do Fracttal…")
        w = ApiWorker(api.load_assets_cached, force)
        self._workers.append(w)

        def _ok(assets):
            self.overlay.hide()
            self.s1.set_assets(assets)

        def _err(m):
            self.overlay.hide()
            self.s1.set_loading_error(m)
            QMessageBox.critical(self, "Erro ao carregar ativos", m)

        w.ok.connect(_ok)
        w.erro.connect(_err)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        w.start()

    # ── gerar OS (Step 3 → API) ──
    def _gerar_os(self):
        ativos = self.s1.selected_assets()
        if not ativos:
            QMessageBox.warning(self, "Ativo", "Marque ao menos um ativo no Passo 1.")
            self._go(0)
            return
        self.data = {"ativos": ativos, "desc": self.s2.descricao(), "tipo": self.s2.tipo_tarefa(),
                     "etiqueta": self.s2.etiqueta(), "subs": self.s3.subtarefas()}
        # A API exige o responsável JÁ na criação → escolhe primeiro, depois gera.
        ResponsavelDialog(self).exec()

    def nova_os(self):
        self.s1.reset()
        self.s2.desc.clear()
        self.s2.tipo.setCurrentIndex(0)
        self.s2.etiq.clear()
        self.s3.reset()
        self._go(0)


class ResponsavelDialog(QDialog):
    """Step 4 — escolhe o responsável e GERA as OS (a API exige o responsável na criação)."""
    def __init__(self, parent):
        super().__init__(parent)
        self._main = parent
        self._pessoas = []
        self.setWindowTitle("Responsável")
        self.setFixedSize(440, 520)
        self.setStyleSheet(DARK_QSS)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(8)
        n = len(parent.data.get("ativos", []))
        lay.addWidget(QLabel(f"<b>{n} OS</b> a gerar — escolha o <b>responsável</b> "
                             f"<span style='color:#8a90a2'>(obrigatório na criação)</span>:"))
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Filtrar responsável…")
        self.busca.textChanged.connect(self._filtrar)
        lay.addWidget(self.busca)
        self.lista = QListWidget()
        self.lista.itemSelectionChanged.connect(
            lambda: self.b_ok.setEnabled(self.lista.currentItem() is not None))
        self.lista.itemDoubleClicked.connect(lambda _: self._gerar())
        lay.addWidget(self.lista, 1)

        row = QHBoxLayout()
        self.b_cancel = QPushButton("Cancelar")
        self.b_cancel.setObjectName("secondary")
        self.b_cancel.clicked.connect(self.reject)
        self.b_ok = QPushButton(f"Gerar {n} OS" if n > 1 else "Gerar OS")
        self.b_ok.setEnabled(False)
        self.b_ok.clicked.connect(self._gerar)
        row.addWidget(self.b_cancel)
        row.addWidget(self.b_ok, 1)
        lay.addLayout(row)

        self._carregar()

    def _carregar(self):
        self.busca.setPlaceholderText("carregando responsáveis…")
        self._w = ApiWorker(api.get_responsaveis)
        self._w.ok.connect(self._set_pessoas)
        self._w.erro.connect(lambda m: self.busca.setPlaceholderText("⚠ " + m))
        self._w.start()

    def _set_pessoas(self, pessoas):
        self._pessoas = pessoas or []
        self.busca.setPlaceholderText("Filtrar responsável…")
        self._filtrar("")

    def _filtrar(self, txt):
        txt = (txt or "").strip().lower()
        self.lista.clear()
        for p in self._pessoas:
            if not txt or txt in p["name"].lower():
                it = QListWidgetItem(p["name"])
                it.setData(Qt.ItemDataRole.UserRole, p)
                self.lista.addItem(it)

    def _gerar(self):
        it = self.lista.currentItem()
        if not it:
            return
        p = it.data(Qt.ItemDataRole.UserRole)
        self.b_ok.setEnabled(False)
        self.b_cancel.setEnabled(False)
        d = self._main.data
        codes = [a["code"] for a in d["ativos"]]
        self.busca.setPlaceholderText(f"Gerando {len(codes)} OS (resp.: {p['name']})…")
        self._w2 = ApiWorker(api.create_work_orders_bulk, codes, d["desc"], d["tipo"],
                             d["subs"], d["etiqueta"], p["code"])
        self._w2.ok.connect(self._pronto)
        self._w2.erro.connect(self._err)
        self._w2.start()

    def _pronto(self, res):
        ok   = [r for r in res if r.get("ok")]
        fail = [r for r in res if not r.get("ok")]
        if not ok:
            self._err("Nenhuma OS criada.\n" + "\n".join(f"• {r['code']}: {r['erro']}" for r in fail[:6]))
            return
        folios = ", ".join(str(r["os"].get("wo_folio") or r["os"].get("id_work_order") or "?") for r in ok)
        msg = f"{len(ok)} OS criada(s) e atribuída(s) — Nº {folios}."
        if fail:
            msg += f"\n\n{len(fail)} falharam:\n" + "\n".join(f"• {r['code']}: {r['erro']}" for r in fail[:4])
        self._final(msg)

    def _err(self, m):
        self.b_ok.setEnabled(True)
        self.b_cancel.setEnabled(True)
        self.busca.setPlaceholderText("Filtrar responsável…")
        QMessageBox.critical(self, "Erro ao gerar OS", m)

    def _final(self, msg):
        box = QMessageBox(self)
        box.setWindowTitle("Sucesso")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(msg)
        b_outra = box.addButton("Criar outra OS", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Fechar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        self.accept()
        if box.clickedButton() is b_outra:
            self._main.nova_os()
        else:
            self._main.close()
