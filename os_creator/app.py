"""app.py — janela principal: navegação entre steps, tema escuro, stay-on-top,
overlay de loading e Step 4 (atribuição de responsável)."""
import os
import datetime as _dt
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QIcon
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
                             QLabel, QProgressBar, QDialog, QLineEdit, QListWidget,
                             QListWidgetItem, QPushButton, QMessageBox, QTabWidget)
import api
from workers import ApiWorker, auth_bus
from steps.step1 import Step1
from steps.step2 import Step2
from steps.step3 import Step3
from steps.finalizar import FinalizarPanel
from steps.historico import HistoricoOS
from steps.historico_solic import HistoricoSolic
from steps.solicitacao import SolicitacaoTab
from steps.pcm import abrir_pcm
from steps.sugestoes import SugestoesTab

_ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
def _asset(name): return os.path.join(_ASSETS, name)
def _logo_label(width=150):
    lb = QLabel(); lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
    pm = QPixmap(_asset("grid-logo.png"))
    if not pm.isNull():
        lb.setPixmap(pm.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation))
    return lb

STEP_LABELS = ["Ativo + Data", "Detalhes da Tarefa", "Sub tarefas", "Responsável"]

DARK_QSS = """
QWidget { background:#14161f; color:#e6e8ef; font-family:'Segoe UI',Arial,sans-serif; font-size:13px; }
QLabel#steptitle { color:#9aa0b4; font-size:12px; }
QLabel#hint { color:#8a90a2; font-size:11px; }
QLineEdit,QTextEdit,QComboBox,QDateEdit,QListWidget {
  background:#1d2130; border:1px solid #2c3142; border-radius:6px; padding:6px; color:#e6e8ef; }
QLineEdit:focus,QTextEdit:focus,QComboBox:focus,QDateEdit:focus { border:1px solid #98c838; }
QComboBox QAbstractItemView { background:#1d2130; color:#e6e8ef; border:1px solid #2c3142;
  selection-background-color:#3a4a20; selection-color:#eaf3d6; outline:0; }
QComboBox QAbstractItemView::item { min-height:22px; padding:4px 6px; }
QListWidget::item { padding:5px; border-radius:4px; }
QListWidget::item:selected { background:#3a4a20; color:#eaf3d6; }
QPushButton { background:#98c838; color:#14161f; border:none; border-radius:7px; padding:9px 14px; font-weight:700; }
QPushButton:hover { background:#a8d64a; }
QPushButton:disabled { background:#2c3142; color:#6b7080; }
QPushButton#secondary { background:#262b3b; color:#cdd2e0; font-weight:500; }
QPushButton#secondary:hover { background:#2f3547; }
QProgressBar { background:#1d2130; border:none; border-radius:3px; }
QProgressBar::chunk { background:#98c838; border-radius:3px; }
QScrollBar:vertical { background:transparent; width:10px; margin:0; }
QScrollBar::handle:vertical { background:#2c3142; border-radius:5px; min-height:24px; }
QScrollBar::add-line,QScrollBar::sub-line { height:0; }
QTabWidget::pane { border:1px solid #2c3142; border-top:none; }
QTabBar::tab { background:#161a25; color:#9aa0b4; padding:8px 18px; border:1px solid #2c3142;
  border-bottom:none; border-top-left-radius:7px; border-top-right-radius:7px; margin-right:3px; font-weight:600; }
QTabBar::tab:selected { background:#1d2130; color:#98c838; }
QTabBar::tab:hover { color:#e6e8ef; }
QTableWidget { background:#1d2130; border:1px solid #2c3142; gridline-color:#262b3b; color:#e6e8ef; }
QHeaderView::section { background:#262b3b; color:#9aa0b4; padding:6px 8px; border:none;
  border-bottom:1px solid #2c3142; font-weight:600; }
QTableWidget::item:selected { background:#2f3a2a; color:#eaf3d6; }
QCheckBox::indicator, QRadioButton::indicator, QListView::indicator {
  width:15px; height:15px; border:2px solid #5a6072; background:#1d2130; }
QRadioButton::indicator { border-radius:8px; }
QCheckBox::indicator, QListView::indicator { border-radius:4px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked, QListView::indicator:checked {
  border:2px solid #ffffff; background:#98c838; }
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
        _u = api.current_user()
        self.setWindowTitle(f"Criar OS — Fracttal{(' · ' + _u) if _u else ''}")
        self.setWindowIcon(QIcon(_asset("grid-icon.png")))
        self.setMinimumSize(560, 640)
        self.resize(920, 720)          # cabe as colunas do histórico; redimensionável
        self.data = {}
        self._workers = []
        self._relogando = False
        auth_bus.sessao_expirou.connect(self._sessao_expirou)   # token morto → força novo login

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # logo Grid Co — sempre visível, acima das abas
        logo_wrap = QWidget()
        ll = QVBoxLayout(logo_wrap)
        ll.setContentsMargins(18, 10, 18, 4)
        ll.addWidget(_logo_label(140))
        root.addWidget(logo_wrap)

        # abas: Criar OS (wizard) + Históricos de OS
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        # ── aba 1: Criar OS (o wizard) ──
        criar = QWidget()
        cl = QVBoxLayout(criar)
        cl.setContentsMargins(0, 6, 0, 0)
        cl.setSpacing(6)
        # barra de clonagem: digitar o nº de uma OS existente e clonar (ativo + tarefas)
        crow = QHBoxLayout(); crow.setContentsMargins(8, 0, 8, 2); crow.setSpacing(6)
        crow.addWidget(QLabel("Clonar OS nº"))
        self.clone_in = QLineEdit(); self.clone_in.setPlaceholderText("ex.: 8125"); self.clone_in.setFixedWidth(110)
        self.clone_in.returnPressed.connect(self._clonar_por_numero)
        crow.addWidget(self.clone_in)
        self.b_clone = QPushButton("Clonar"); self.b_clone.setObjectName("secondary")
        self.b_clone.clicked.connect(self._clonar_por_numero)
        crow.addWidget(self.b_clone)
        self.b_varias = QPushButton("COS"); self.b_varias.setObjectName("secondary")
        self.b_varias.setToolTip("COS — várias OSs: 1 ativo × várias datas, OU vários ativos × 1 data")
        self.b_varias.clicked.connect(self._abrir_varias_os)
        crow.addWidget(self.b_varias)
        self.b_pcm = QPushButton("PCM"); self.b_pcm.setObjectName("secondary")
        self.b_pcm.setToolTip("PCM — OS por plano de tarefas (MPS/MPA/MPM/Handover) p/ vários ativos")
        self.b_pcm.clicked.connect(self._abrir_pcm)
        crow.addWidget(self.b_pcm); crow.addStretch(1)
        cl.addLayout(crow)
        self.steplbl = QLabel()
        self.steplbl.setObjectName("steptitle")
        self.steplbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prog = QProgressBar()
        self.prog.setRange(0, 4)
        self.prog.setTextVisible(False)
        self.prog.setFixedHeight(6)
        cl.addWidget(self.steplbl)
        cl.addWidget(self.prog)
        self.stack = QStackedWidget()
        self.s1, self.s2, self.s3 = Step1(), Step2(), Step3()
        for s in (self.s1, self.s2, self.s3):
            self.stack.addWidget(s)
        cl.addWidget(self.stack, 1)
        self.tabs.addTab(criar, "Criar OS")

        # ── aba 2: Criar Solicitação ──
        self.sol = SolicitacaoTab()
        self.tabs.addTab(self.sol, "Criar Solicitação")

        # ── aba 3: Históricos de OS ──
        self.hist = HistoricoOS()
        self.tabs.addTab(self.hist, "Históricos de OS")

        # ── aba 4: Histórico de Solicitação ──
        self.hsol = HistoricoSolic()
        self.tabs.addTab(self.hsol, "Histórico de Solicitação")

        # ── aba 5: Sugestões de OS (trackers parados, vindo do dashboard) ──
        # ESCONDIDA por ora (pedido do Levi). Pra reativar: descomente o addTab abaixo.
        self.sug = SugestoesTab()
        self.sug.criar_os.connect(self._criar_os_de_sugestao)
        # self.tabs.addTab(self.sug, "Sugestões de OS")

        self.tabs.currentChanged.connect(self._on_tab)

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
        self._carregar_labels()

    # ── navegação / overlay ──
    def _go(self, idx):
        self.stack.setCurrentIndex(idx)
        self.prog.setValue(idx + 1)
        self.steplbl.setText(f"Passo {idx + 1} de 4  ·  {STEP_LABELS[idx]}")

    def _on_tab(self, idx):
        txt = self.tabs.tabText(idx)                          # 1ª abertura → carrega
        if txt.startswith("Históricos"):
            self.hist.carregar_inicial()
        elif txt.startswith("Histórico de Solicitação"):
            self.hsol.carregar_inicial()
        elif txt.startswith("Criar Solicitação"):
            self.sol.carregar_inicial()
        elif txt.startswith("Sugestões"):
            self.sug.carregar_inicial()

    # ── sessão morta (token rotacionado/expirado) → forçar novo login ──
    def _sessao_expirou(self, msg):
        """Vários workers podem falhar juntos; o debounce (_relogando) abre o login UMA vez só.
        Após relogar, recarrega ativos/etiquetas e a aba atual."""
        if self._relogando:
            return
        self._relogando = True
        try:
            QMessageBox.warning(self, "Sessão expirada",
                "Sua sessão do Fracttal expirou (o app/web do Fracttal rotaciona o token quando fica "
                "aberto). Entre de novo para continuar.")
            if LoginDialog(self).exec() == QDialog.DialogCode.Accepted:
                self._carregar_ativos(force=True)
                self._carregar_labels()
                w = self.tabs.currentWidget()                 # recarrega a aba atual
                for m in ("recarregar", "carregar_inicial"):
                    if hasattr(w, m):
                        getattr(w, m)()
                        break
        finally:
            self._relogando = False

    # ── clonar OS (pelo nº digitado na aba Criar OS) ──
    def _clonar_por_numero(self):
        folio = (self.clone_in.text() or "").strip()
        if not folio:
            return

        def _achou(wid):
            if wid:
                self._abrir_clone(wid, folio)
            else:
                QMessageBox.information(self, "OS não encontrada", f"Não achei nenhuma OS com o nº {folio}.")
        self._run(api._wo_id_por_folio, _achou, f"Procurando a OS nº {folio}…", folio)

    def _abrir_clone(self, id_wo, folio=None):
        from steps.clonar import abrir_clonar_os
        abrir_clonar_os(self, id_wo, folio)

    def _abrir_varias_os(self):
        from steps.varias_os import abrir_varias_os
        abrir_varias_os(self)

    def _abrir_pcm(self):
        abrir_pcm(self)

    def abrir_solicitacao_de(self, code):
        """Vai p/ a aba 'Criar Solicitação' com cliente/usina/ativo pré-preenchidos pelo code do ativo
        (usado pelo detalhe da OS no histórico)."""
        self.tabs.setCurrentWidget(self.sol)
        self.sol.carregar_inicial()
        if not self.sol.prefill_por_code(code):
            QMessageBox.information(self, "Criar Solicitação",
                "Abri a aba de Solicitação, mas não consegui pré-selecionar o ativo automaticamente "
                "(ativo fora do catálogo ou tipo não habilitado). Selecione manualmente.")

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
            self.sol.set_assets(assets)

        def _err(m):
            self.overlay.hide()
            self.s1.set_loading_error(m)
            QMessageBox.critical(self, "Erro ao carregar ativos", m)

        w.ok.connect(_ok)
        w.erro.connect(_err)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        w.start()

    # ── catálogo de etiquetas (background; alimenta o Step 2) ──
    def _carregar_labels(self):
        w = ApiWorker(api.get_labels)
        self._workers.append(w)
        w.ok.connect(self.s2.set_labels)
        w.erro.connect(lambda _m: self.s2.set_labels([]))
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        w.start()

    # ── gerar OS (Step 3 → API) ──
    def _gerar_os(self):
        ativos = self.s1.selected_assets()
        if not ativos:
            QMessageBox.warning(self, "Ativo", "Marque ao menos um ativo no Passo 1.")
            self._go(0)
            return
        if not self.s2.tipo_ready():
            QMessageBox.warning(self, "Tipo de tarefa", "O tipo de tarefa ainda não carregou (ou a "
                                "sessão expirou). Aguarde um instante ou relogue antes de gerar.")
            self._go(1)
            return
        self.data = {"ativos": ativos, "desc": self.s2.descricao(), "obs": self.s2.observacao(),
                     "tipo": self.s2.tipo_tarefa(), "tipo_dict": self.s2.tipo_dict(),
                     "etiqueta": self.s2.etiqueta(), "etiqueta_ids": self.s2.etiqueta_ids(),
                     "subs": self.s3.subtarefas(),
                     "event_dt": self.s1.data_programada(),      # data programada (Passo 1) → event_date
                     "event_qdt": self.s1.dt_prog.dateTime()}    # idem, p/ default do painel 'já realizada'
        # A API exige o responsável JÁ na criação → escolhe primeiro, depois gera.
        ResponsavelDialog(self).exec()

    def nova_os(self):
        self.s1.reset()
        self.s2.reset()
        self.s3.reset()
        self._go(0)

    def _criar_os_de_sugestao(self, sug):
        """Vem da aba 'Sugestões de OS': abre o wizard 'Criar OS' já preenchido (Estrutura Trackers da
        usina + descrição + tipo). O usuário confere o ativo no Passo 1 e segue p/ criar (handoff B)."""
        self.tabs.setCurrentIndex(0)                      # aba 'Criar OS' (wizard) é sempre a 1ª
        self.nova_os()
        n = self.s1.prefill_tracker(sug.get("usina", ""))
        self.s2.prefill(sug.get("descricao", ""), sug.get("tipo_tarefa") or "Corretiva")
        self._go(0)
        if n:
            QMessageBox.information(self, "Sugestão carregada",
                f"Marquei {n} 'Estrutura Trackers' de {sug.get('usina')} e preenchi a descrição/tipo. "
                f"Confira o ativo no Passo 1 e siga para criar a OS.")
        else:
            QMessageBox.information(self, "Sugestão carregada",
                f"Preenchi a descrição/tipo, mas não achei 'Estrutura Trackers' de "
                f"'{sug.get('usina')}' no catálogo do Fracttal (nome diferente?). "
                f"Selecione o ativo manualmente no Passo 1.")


class ResponsavelDialog(QDialog):
    """Step 4 — escolhe o responsável e GERA as OS (a API exige o responsável na criação)."""
    def __init__(self, parent):
        super().__init__(parent)
        self._main = parent
        self._pessoas = []
        self.setWindowTitle("Responsável")
        self.setMinimumSize(440, 520)
        self.resize(460, 560)
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
        self.lista.setMinimumHeight(130)
        self.lista.itemSelectionChanged.connect(
            lambda: self.b_ok.setEnabled(self.lista.currentItem() is not None))
        self.lista.itemDoubleClicked.connect(lambda _: self._gerar())
        lay.addWidget(self.lista, 1)

        # "Esta tarefa já foi realizada?" → cria a OS concluída (datas + respostas das subtarefas)
        self.fin = FinalizarPanel(parent.data.get("subs", []), com_datas=True)
        _eqdt = parent.data.get("event_qdt")
        if _eqdt is not None:                                    # data inicial = data programada do Passo 1
            self.fin.dt_ini.setDateTime(_eqdt); self.fin.dt_fim.setDateTime(_eqdt)
        self.fin.toggled.connect(lambda *_: self.adjustSize())   # cresce p/ caber o painel (sem scroll aqui)
        lay.addWidget(self.fin)

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
        d = self._main.data
        ativos = d["ativos"]
        brt = _dt.timezone(_dt.timedelta(hours=-3))
        finalizar = None
        _edt = d.get("event_dt")
        event_date = _edt.replace(tzinfo=brt) if _edt is not None else None   # data programada do Passo 1
        if self.fin.is_finalizar():                       # OS já realizada → cria concluída
            ini, fim = self.fin.data_inicial(), self.fin.data_final()
            if fim < ini:
                QMessageBox.warning(self, "Datas", "A Data final não pode ser anterior à Data inicial.")
                return
            event_date = ini.replace(tzinfo=brt)          # finalizada usa a data inicial do painel
            finalizar = {"to_in_review": self.fin.to_in_review(),
                         "final_date": fim.replace(tzinfo=brt),
                         "id_assigned_user": p.get("id_personnel"), "name": p.get("name"),
                         "respostas": self.fin.respostas()}
        self.b_ok.setEnabled(False)
        self.b_cancel.setEnabled(False)
        self.busca.setPlaceholderText(f"Gerando {len(ativos)} OS (resp.: {p['name']})…")
        self._w2 = ApiWorker(api.create_work_orders_bulk, ativos, d["desc"], d["tipo"],
                             d["subs"], d["etiqueta"], p["code"], p["name"], p.get("id_personnel"),
                             d.get("etiqueta_ids"), d.get("obs", ""), tipo=d.get("tipo_dict"),
                             finalizar=finalizar, event_date=event_date)
        self._w2.ok.connect(self._pronto)
        self._w2.erro.connect(self._err)
        self._w2.start()

    def _pronto(self, res):
        ok   = [r for r in res if r.get("ok")]
        fail = [r for r in res if not r.get("ok")]
        if not ok:
            self._err("Nenhuma OS criada.\n" + "\n".join(f"• {r['code']}: {r['erro']}" for r in fail[:6]))
            return
        folios = ", ".join(str(r["os"].get("wo_folio") or r["os"].get("id_work_order")
                               or r["os"].get("id_task") or "?") for r in ok)
        msg = f"{len(ok)} OS criada(s) — Nº {folios}."
        avisos = [f"• {r['code']}: {r['os']['aviso']}" for r in ok if r['os'].get('aviso')]
        if avisos:
            msg += f"\n\n⚠ {len(avisos)} com ressalva:\n" + "\n".join(avisos[:4])
        if fail:
            msg += f"\n\n{len(fail)} falharam:\n" + "\n".join(f"• {r['code']}: {r['erro']}" for r in fail[:4])
        self._final(msg)

    def _err(self, m):
        self.b_ok.setEnabled(True)
        self.b_cancel.setEnabled(True)
        self.busca.setPlaceholderText("Filtrar responsável…")
        QMessageBox.critical(self, "Erro ao gerar OS", m)

    def _final(self, msg):
        # Notificação simples: NÃO fecha o app. Fecha só este diálogo e volta pronto p/ outra OS.
        self.accept()
        QMessageBox.information(self._main, "Sucesso", msg)
        self._main.nova_os()


class LoginDialog(QDialog):
    """Login no Fracttal (e-mail + senha → JWT de sessão). A senha NÃO é guardada — só o token,
    no cofre do SO (keyring) ou arquivo. A OS é criada no nome de quem loga."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Entrar — Fracttal")
        self.setWindowIcon(QIcon(_asset("grid-icon.png")))
        self.setFixedSize(380, 370)
        self.setStyleSheet(DARK_QSS)
        self._w = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(10)
        lay.addWidget(_logo_label(165))
        lay.addWidget(QLabel("<b>Entrar no Fracttal</b>"))
        lay.addWidget(QLabel("<span style='color:#8a90a2'>Seu e-mail e senha do Fracttal. "
                             "A OS é criada no seu nome; a senha não é armazenada.</span>"))
        self.email = QLineEdit()
        self.email.setPlaceholderText("e-mail")
        self.email.textChanged.connect(self._upd)
        lay.addWidget(self.email)
        self.senha = QLineEdit()
        self.senha.setPlaceholderText("senha")
        self.senha.setEchoMode(QLineEdit.EchoMode.Password)
        self.senha.textChanged.connect(self._upd)
        self.senha.returnPressed.connect(self._entrar)
        lay.addWidget(self.senha)
        self.msg = QLabel("")
        self.msg.setStyleSheet("color:#e05555;font-size:11px;")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        self.btn = QPushButton("Entrar")
        self.btn.setEnabled(False)
        self.btn.clicked.connect(self._entrar)
        lay.addWidget(self.btn)
        sep = QLabel("<span style='color:#6b7080'>— ou —</span>")
        sep.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(sep)
        self.btn_sso = QPushButton("Entrar com Microsoft / SSO")
        self.btn_sso.setObjectName("secondary")
        self.btn_sso.setToolTip("Pra quem entra no Fracttal pela Microsoft — abre o login num navegador")
        self.btn_sso.clicked.connect(self._entrar_sso)
        lay.addWidget(self.btn_sso)
        lay.addStretch(1)

    def _upd(self):
        self.btn.setEnabled(bool(self.email.text().strip() and self.senha.text()))

    def _entrar(self):
        if not (self.email.text().strip() and self.senha.text()):
            return
        self.btn.setEnabled(False)
        self.btn.setText("Entrando…")
        self.msg.setText("")
        self._w = ApiWorker(api.fracttal_login, self.email.text().strip(), self.senha.text())
        self._w.ok.connect(lambda _r: self.accept())
        self._w.erro.connect(self._err)
        self._w.start()

    def _err(self, m):
        self.btn.setEnabled(True)
        self.btn.setText("Entrar")
        self.msg.setText("⚠ " + m)

    def _entrar_sso(self):
        """Login Microsoft/SSO: abre o Fracttal num navegador embutido e captura o token de sessão."""
        from steps.sso_login import SsoLoginDialog
        self.msg.setText("")
        dlg = SsoLoginDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.token:
            api._save_jwt(dlg.token)
            if api.current_user():                 # token é um JWT válido c/ e-mail → segue
                self.accept()
            else:
                self.msg.setText("⚠ Token capturado, mas não identifiquei seu usuário no Fracttal.")
