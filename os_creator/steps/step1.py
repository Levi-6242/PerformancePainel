"""Step 1 — drill-down do Ativo: Cliente → Usina → Tipo → Ativo(s) + Data programada.
Seleção MÚLTIPLA por checkbox (1 OS por ativo marcado). A Data programada (default = agora,
horário de Brasília) vira o event_date da OS — ajustável, igual ao incidente do Várias OSs."""
import unicodedata
from PyQt6.QtCore import Qt, pyqtSignal, QDateTime
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit,
                             QListWidget, QListWidgetItem, QPushButton, QDateTimeEdit)
from steps.ui import Card, campo, rotulo, Linha, icone_pix, MUTED

TODOS_USINA = "— Selecione a usina —"
TODOS_TIPO  = "Todos os tipos"


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(s.split())

class _TodosOsTipos:
    """Sentinela 'todos os tipos de equipamento' — filtro por tipo REMOVIDO (pedido do Levi 01/07).
    `tipo in ALLOWED_TIPOS` é True p/ qualquer tipo não-vazio (mantém só a exclusão de tipo vazio),
    então todas as telas que faziam `in`/`not in ALLOWED_TIPOS` passam a mostrar TODOS os tipos."""
    def __contains__(self, tipo):
        return bool(tipo)


ALLOWED_TIPOS = _TodosOsTipos()

# Clientes que NÃO aparecem no drill-down (almoxarifado e ambiente de teste).
CLIENTES_OCULTOS = {"almoxarifado", "teste - pa"}


class Step1(QWidget):
    avancar = pyqtSignal()
    recarregar = pyqtSignal()      # botão "↻" → app recarrega ativos (force)

    def __init__(self):
        super().__init__()
        self._assets = []
        self._checked = set()       # ids dos ativos marcados (persistem entre filtros)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 12, 18, 12)
        lay.setSpacing(12)

        # widgets (mesmos de sempre; só a organização muda p/ cards)
        self.cb_cliente = QComboBox()
        self.cb_cliente.currentIndexChanged.connect(self._on_cliente)
        self.cb_usina = QComboBox()
        self.cb_usina.currentIndexChanged.connect(self._on_usina)
        self.cb_tipo = QComboBox()
        self.cb_tipo.currentIndexChanged.connect(self._refresh_ativos)
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Refinar por código ou nome…")
        self.busca.addAction(QIcon(icone_pix("search", MUTED, 15)), QLineEdit.ActionPosition.LeadingPosition)
        self.busca.textChanged.connect(self._refresh_ativos)
        self.lista = QListWidget(); self.lista.setMinimumHeight(190)
        self.lista.itemChanged.connect(self._on_check)
        self.lista.itemClicked.connect(self._toggle)
        self.hint = QLabel("carregando ativos…"); self.hint.setObjectName("hint")
        self.dt_prog = QDateTimeEdit(QDateTime.currentDateTime())
        self.dt_prog.setDisplayFormat("dd/MM/yyyy HH:mm"); self.dt_prog.setCalendarPopup(True)
        b_agora = QPushButton("Agora"); b_agora.setObjectName("secondary"); b_agora.setFixedWidth(64)
        b_agora.clicked.connect(lambda: self.dt_prog.setDateTime(QDateTime.currentDateTime()))
        dtw = QWidget(); dtw.setObjectName("uiGroup")
        dth = QHBoxLayout(dtw); dth.setContentsMargins(0, 0, 0, 0); dth.setSpacing(8)
        dth.addWidget(self.dt_prog, 1); dth.addWidget(b_agora)

        card = Card("box", "Ativo")
        card.add(Linha(campo("Cliente", self.cb_cliente, obrig=True),
                       campo("Usina", self.cb_usina, obrig=True)))
        card.add(Linha(campo("Tipo de equipamento", self.cb_tipo), campo(" ", self.busca)))
        card.add(rotulo("Ativos", obrig=True, extra="(marque um ou vários)"))
        card.add(self.lista, stretch=1)
        card.add(self.hint)
        card.add(campo("Data programada", dtw, extra="(Brasília)"))
        lay.addWidget(card, 1)

        row = QHBoxLayout()
        self.b_reload = QPushButton("↻")
        self.b_reload.setObjectName("secondary")
        self.b_reload.setFixedWidth(40)
        self.b_reload.setToolTip("Recarregar ativos do Fracttal")
        self.b_reload.clicked.connect(self.recarregar.emit)
        self.btn = QPushButton("Próximo ›››")
        self.btn.setEnabled(False)
        self.btn.clicked.connect(self.avancar.emit)
        row.addWidget(self.b_reload)
        row.addWidget(self.btn, 1)
        lay.addLayout(row)

    # ── carga de dados ──
    def set_assets(self, assets):
        self._assets = assets or []
        clientes = sorted({a["cliente"] for a in self._assets
                           if a["cliente"] and a["cliente"].strip().lower() not in CLIENTES_OCULTOS})
        self.cb_cliente.blockSignals(True)
        self.cb_cliente.clear()
        self.cb_cliente.addItem("— Selecione o cliente —")
        self.cb_cliente.addItems(clientes)
        self.cb_cliente.blockSignals(False)
        self._on_cliente()

    def set_loading_error(self, msg):
        self.hint.setText("⚠ " + msg)

    # ── cascata ──
    def _cliente_sel(self):
        return self.cb_cliente.currentText() if self.cb_cliente.currentIndex() > 0 else None

    def _usina_sel(self):
        return self.cb_usina.currentText() if self.cb_usina.currentIndex() > 0 else None

    def _on_cliente(self):
        cli = self._cliente_sel()
        usinas = sorted({a["usina"] for a in self._assets if a["cliente"] == cli and a["usina"]}) if cli else []
        self.cb_usina.blockSignals(True)
        self.cb_usina.clear()
        self.cb_usina.addItem(TODOS_USINA)
        self.cb_usina.addItems(usinas)
        self.cb_usina.setEnabled(bool(usinas))
        self.cb_usina.blockSignals(False)
        self._on_usina()

    def _on_usina(self):
        cli, usi = self._cliente_sel(), self._usina_sel()
        tipos = sorted({a["tipo"] for a in self._assets
                        if a["cliente"] == cli and a["usina"] == usi
                        and a["tipo"] in ALLOWED_TIPOS}) if usi else []
        self.cb_tipo.blockSignals(True)
        self.cb_tipo.clear()
        self.cb_tipo.addItem(TODOS_TIPO)
        self.cb_tipo.addItems(tipos)
        self.cb_tipo.setEnabled(bool(tipos))
        self.cb_tipo.blockSignals(False)
        self._refresh_ativos()

    def _refresh_ativos(self):
        cli, usi = self._cliente_sel(), self._usina_sel()
        tipo = self.cb_tipo.currentText() if self.cb_tipo.currentIndex() > 0 else None
        txt = (self.busca.text() or "").strip().lower()
        self.lista.blockSignals(True)        # evita disparar _on_check ao popular
        self.lista.clear()
        if not usi:
            self.lista.blockSignals(False)
            self._atualiza_hint("Selecione cliente e usina para ver os ativos.")
            return
        n = 0
        for a in self._assets:
            if a["cliente"] != cli or a["usina"] != usi:
                continue
            if a["tipo"] not in ALLOWED_TIPOS:
                continue
            if tipo and a["tipo"] != tipo:
                continue
            if txt and txt not in a["label"].lower():
                continue
            it = QListWidgetItem(a["label"])
            it.setData(Qt.ItemDataRole.UserRole, a)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if a["id"] in self._checked
                             else Qt.CheckState.Unchecked)
            self.lista.addItem(it)
            n += 1
        self.lista.blockSignals(False)
        self._atualiza_hint(f"{n} ativo(s) nesta seleção")

    # ── seleção múltipla ──
    def _toggle(self, it):
        it.setCheckState(Qt.CheckState.Unchecked if it.checkState() == Qt.CheckState.Checked
                         else Qt.CheckState.Checked)

    def _on_check(self, it):
        a = it.data(Qt.ItemDataRole.UserRole)
        if not a:
            return
        if it.checkState() == Qt.CheckState.Checked:
            self._checked.add(a["id"])
        else:
            self._checked.discard(a["id"])
        self._atualiza_hint(self.hint.text().split("  ·")[0])

    def _atualiza_hint(self, base):
        n = len(self._checked)
        self.hint.setText(f"{base}  ·  {n} marcado(s)" if n else base)
        self.btn.setText(f"Próximo ({n}) ›››" if n else "Próximo ›››")
        self.btn.setEnabled(n > 0)

    # ── pré-seleção vinda da fila de sugestões (trackers parados) ──
    def prefill_tracker(self, usina):
        """Marca a(s) 'Estrutura Trackers' da usina (nome vindo do dashboard) e posiciona os filtros.
        Casa por nome NORMALIZADO (o nome do Fracttal pode diferir do BD). Devolve nº de ativos marcados.
        Usa cliente/usina do PRÓPRIO ativo encontrado → cascata exata, sem depender do nome do dashboard."""
        alvo = _norm(usina)
        cands = [a for a in self._assets
                 if a.get("tipo") == "Estrutura Trackers" and alvo
                 and (alvo == _norm(a.get("usina")) or alvo in _norm(a.get("usina"))
                      or _norm(a.get("usina")) in alvo)]
        if not cands:
            return 0
        a0 = cands[0]
        self._checked = {a["id"] for a in cands}
        ic = self.cb_cliente.findText(a0.get("cliente") or "")
        if ic > 0:
            self.cb_cliente.setCurrentIndex(ic)        # cascata → usinas
        iu = self.cb_usina.findText(a0.get("usina") or "")
        if iu > 0:
            self.cb_usina.setCurrentIndex(iu)          # cascata → tipos + ativos
        it = self.cb_tipo.findText("Estrutura Trackers")
        if it > 0:
            self.cb_tipo.setCurrentIndex(it)
        self._refresh_ativos()
        self._atualiza_hint(f"{len(cands)} Estrutura(s) Trackers de {a0.get('usina')}")
        return len(cands)

    # ── getter / reset p/ o app ──
    def selected_assets(self):
        return [a for a in self._assets if a["id"] in self._checked]

    def data_programada(self):
        """Data/hora programada escolhida (naive = Brasília; o app anexa o fuso → event_date)."""
        return self.dt_prog.dateTime().toPyDateTime()

    def reset(self):
        self._checked.clear()
        self.dt_prog.setDateTime(QDateTime.currentDateTime())
        self.busca.blockSignals(True)
        self.busca.clear()
        self.busca.blockSignals(False)
        self.cb_cliente.setCurrentIndex(0)   # dispara a cascata → reseta usina/tipo/lista
