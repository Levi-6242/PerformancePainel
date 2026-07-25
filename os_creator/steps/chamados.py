"""Chamados — duas visões:
  • Novo chamado: cria uma OS de chamado a partir de UMA OS existente (mesmo ativo, aquela OS como
    OS PAI, etiqueta CHAMADOS, opção de concluir).
  • Acompanhar: board dinâmico com TODAS as OSs que têm a etiqueta CHAMADOS, cada uma num card
    clicável (abre o detalhe da OS).
(v1 — refino com a área: filtros por status, planilha de tickets, etc.)"""
import datetime as _dt
import json
import os
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit,
                             QPushButton, QMessageBox, QCheckBox, QScrollArea, QFrame,
                             QStackedWidget, QGridLayout)
import api
from workers import ApiWorker, slot_seguro
from steps.searchcombo import tornar_pesquisavel
from steps.os_detalhe import abrir_os_detalhe
from steps.ui import (QSS_FORM, Card, campo, rotulo, Linha, Segmentado, icone_pix,
                      GREEN, MUTED, TEXT, INPUT, BORDER)

_STATUS_COR = {"Em Processo": "#F5A623", "Em Verificação": "#4A9EF5", "Concluída": "#48D07A",
               "Cancelada": "#F5766B", "OS concluída": "#48D07A", "OS em verificação": "#4A9EF5",
               "Aberta": "#F0B341"}

# Listas-PADRÃO das subtarefas do chamado (tiradas da planilha Gestão de Chamados). São a base;
# a Syngrid pode digitar uma opção nova no campo → fica salva em chamados_listas.json e passa a
# aparecer pra todos (padroniza sem engessar).
_LISTAS_BASE = {
    "status": ["Aguardando Abertura de OS", "Aguardando retorno do Fabricante",
               "Aguardando retorno do Cliente", "Aguardando retorno do Supervisor",
               "Aguardando retorno Pré-Operação", "Aguardando coleta do equipamento",
               "Testes em campo", "Standby", "Pausado", "Concluído"],
    "motivo": ["Inversor desligado / sem operação", "Inversor com falha ou erro interno",
               "Inversor — ventoinha / exaustor", "Otimizador sem comunicação",
               "String sem corrente / sem comunicação", "Tracker parado / sem movimentação",
               "Tracker — motor / TCU", "Falha de comunicação / supervisório",
               "Módulo — dano / limpeza / vegetação", "Estação meteorológica / sensor",
               "Inject / precom / comissionamento"],
    "resolucao": ["Troca em garantia", "Substituição de peça/equipamento (fora de garantia)",
                  "Reparo em campo", "Reset / reconfiguração / normalização",
                  "Sem defeito encontrado", "Cancelado"],
    "fabricante": ["Huawei", "Brametal", "Sungrow", "Growatt", "Solplanet", "WEG"],
}


def _rgba(hexc, a):
    h = hexc.lstrip("#"); return f"rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{a})"


def _fmt_dur_solar(h):
    """Horas solares → texto compacto. <1h = min · <24h = 'Hh Mmin' · senão dias solares (12h/dia)."""
    m = int(round(h * 60))
    if m < 60:
        return f"{m} min"
    hh, mm = divmod(m, 60)
    if hh < 24:
        return f"{hh}h" + (f" {mm}min" if mm else "")
    return f"{hh / 12:.1f} dias".replace(".", ",")   # dia solar = 12h


def _status_cor(st):
    """Cor do status do CHAMADO (vocabulário da planilha) ou, no fallback, do status do Fracttal."""
    s = (st or "").lower()
    if "conclu" in s:
        return "#48D07A"
    if "cancel" in s or "rejeit" in s:
        return "#F5766B"
    if "aguard" in s:
        return "#F5A623"
    if "teste" in s:
        return "#4A9EF5"
    if "standby" in s or "paus" in s:
        return "#8891a6"
    return _STATUS_COR.get(st, MUTED)


def _listas_path():
    try:
        return os.path.join(api._data_dir(), "chamados_listas.json")
    except Exception:
        return None


def _load_listas():
    """Base + opções que a Syngrid adicionou (persistidas). → {chave: [opções…]}."""
    add = {}
    p = _listas_path()
    if p and os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                add = json.load(f)
        except Exception:
            add = {}
    return {k: list(base) + [x for x in (add.get(k) or []) if x and x not in base]
            for k, base in _LISTAS_BASE.items()}


def _add_opcao(chave, valor):
    """Salva uma opção NOVA (digitada no campo) pra virar padrão. No-op se já existe/é base."""
    valor = (valor or "").strip()
    if not valor or valor in _LISTAS_BASE.get(chave, []):
        return
    p = _listas_path()
    if not p:
        return
    add = {}
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                add = json.load(f)
        except Exception:
            add = {}
    lst = add.setdefault(chave, [])
    if valor not in lst:
        lst.append(valor)
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(add, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


class _ChamadoCard(QFrame):
    """Card de uma OS de chamado — clicável, abre o detalhe da OS."""
    def __init__(self, d, on_click):
        super().__init__()
        self._d = d; self._on_click = on_click
        ch = api.parse_bloco_chamado(d.get("note"))          # bloco CHAMADO da observação (se houver)
        st = (ch.get("status") or d.get("status") or "").strip()   # status do CHAMADO; senão o do Fracttal
        cor = _status_cor(st)
        self.setObjectName("chamCard"); self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(176)
        self.setStyleSheet("QFrame#chamCard{background:#161d30;border:1px solid #232a3d;border-radius:12px;"
                           "border-left:3px solid %s;}"
                           "QFrame#chamCard:hover{border-color:%s;border-left-color:%s;}" % (cor, GREEN, GREEN))
        v = QVBoxLayout(self); v.setContentsMargins(14, 11, 14, 11); v.setSpacing(4)
        top = QHBoxLayout(); top.setSpacing(8)
        num = QLabel(f"OS {d.get('folio') or d.get('id') or '?'}")
        num.setStyleSheet(f"color:{TEXT};font-size:15px;font-weight:700;background:transparent;")
        top.addWidget(num); top.addStretch(1)
        chip = QLabel(st or "—")
        chip.setStyleSheet(f"color:{cor};background:{_rgba(cor,0.15)};border:1px solid {_rgba(cor,0.34)};"
                           "border-radius:999px;padding:2px 10px;font-size:10.5px;font-weight:600;")
        top.addWidget(chip)
        v.addLayout(top)
        ativo = QLabel(d.get("ativo") or "—"); ativo.setWordWrap(True)
        ativo.setStyleSheet(f"color:#dfe4ee;font-size:13px;font-weight:600;background:transparent;")
        v.addWidget(ativo)
        sub = QLabel(d.get("usina") or "—")
        sub.setStyleSheet(f"color:{MUTED};font-size:12px;background:transparent;")
        v.addWidget(sub)
        # specs do bloco: OS abertura · Ticket/RMA · Serial (só as que existem)
        specs = [(k, val) for k, val in (("OS abertura", ch.get("os_pai")),
                 ("Ticket/RMA", ch.get("ticket")), ("Serial", ch.get("serial"))) if val]
        if specs:
            wg = QWidget(); wg.setStyleSheet("background:transparent;")
            g = QGridLayout(wg); g.setContentsMargins(0, 3, 0, 0)
            g.setHorizontalSpacing(10); g.setVerticalSpacing(2)
            for i, (k, val) in enumerate(specs):
                kl = QLabel(k); kl.setStyleSheet(f"color:{MUTED};font-size:11px;background:transparent;")
                vl = QLabel(val); vl.setStyleSheet("color:#dfe4ee;font-size:11.5px;font-weight:600;background:transparent;")
                g.addWidget(kl, i, 0); g.addWidget(vl, i, 1)
            g.setColumnStretch(1, 1)
            v.addWidget(wg)
        v.addStretch(1)
        horas, aberto = api.duracao_solar(d.get("event_date"), d.get("data_fim"))
        if horas is not None:
            dcor = "#F5A623" if aberto else GREEN
            txt = ("aberto há " if aberto else "durou ") + _fmt_dur_solar(horas) + " solares"
            dur = QLabel(txt)
            dur.setStyleSheet(f"color:{dcor};font-size:11px;font-weight:600;background:transparent;")
            v.addWidget(dur)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._on_click:
            self._on_click(self._d)


class ChamadosTab(QWidget):
    def __init__(self, on_voltar=None):
        super().__init__()
        self._on_voltar = on_voltar
        self._parent = None                 # detalhe da OS pai buscada (aba Novo)
        self._wb = self._wc = self._wr = self._wl = None
        self._board_loaded = False
        self._listas = _load_listas()       # listas-padrão das subtarefas (base + adicionadas)
        self.setStyleSheet(QSS_FORM)
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        segrow = QHBoxLayout(); segrow.setContentsMargins(18, 10, 18, 4)
        self._seg = Segmentado(["Novo chamado", "Acompanhar chamados"], on_change=self._on_seg)
        segrow.addWidget(self._seg); segrow.addStretch(1)
        root.addLayout(segrow)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_form())      # página 0
        self.stack.addWidget(self._build_board())     # página 1
        root.addWidget(self.stack, 1)

    # ══════════════════════ NOVO CHAMADO (form) ══════════════════════
    def _build_form(self):
        page = QWidget()
        outer = QVBoxLayout(page); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(); scroll.setWidget(body); outer.addWidget(scroll, 1)
        lay = QVBoxLayout(body); lay.setContentsMargins(18, 10, 18, 14); lay.setSpacing(14)

        self.ed_os = QLineEdit(); self.ed_os.setPlaceholderText("nº da OS (ex.: 9184)")
        self.ed_os.setFixedWidth(150); self.ed_os.returnPressed.connect(self._buscar)
        self.b_busca = QPushButton("Buscar"); self.b_busca.setObjectName("secondary")
        self.b_busca.setCursor(Qt.CursorShape.PointingHandCursor); self.b_busca.clicked.connect(self._buscar)
        brow = QWidget(); brow.setStyleSheet("background:transparent;")
        bl = QHBoxLayout(brow); bl.setContentsMargins(0, 0, 0, 0); bl.setSpacing(8)
        bl.addWidget(self.ed_os); bl.addWidget(self.b_busca); bl.addStretch(1)
        self.card_prev = QFrame(); self.card_prev.setObjectName("chamPrev")
        self.card_prev.setStyleSheet("QFrame#chamPrev{background:%s;border:1px solid %s;border-radius:10px;}"
                                     % (INPUT, BORDER))
        pv = QVBoxLayout(self.card_prev); pv.setContentsMargins(14, 12, 14, 12); pv.setSpacing(4)
        self.lb_ativo = QLabel("—"); self.lb_ativo.setWordWrap(True)
        self.lb_ativo.setStyleSheet(f"color:{TEXT};font-size:14px;font-weight:650;background:transparent;")
        self.lb_sub = QLabel("Busque uma OS para ver o ativo e a usina que o chamado vai usar.")
        self.lb_sub.setWordWrap(True); self.lb_sub.setStyleSheet(f"color:{MUTED};font-size:12px;background:transparent;")
        pv.addWidget(self.lb_ativo); pv.addWidget(self.lb_sub)
        c1 = Card(1, "OS do chamado")
        c1.add(campo("Número da OS que vira o chamado", brow, obrig=True,
                     extra="(a nova OS herda o ativo e fica ligada a ela como OS pai)"))
        c1.add(self.card_prev)
        lay.addWidget(c1)

        # ── Card 2: Dados do chamado (viram subtarefas + bloco na observação) ──
        self.ed_ticket = QLineEdit(); self.ed_ticket.setPlaceholderText("ex.: 14696095 ou 00479/26")
        self.ed_serial = QLineEdit(); self.ed_serial.setPlaceholderText("nº de série do equipamento")
        self.cb_fab = QComboBox(); self.cb_status = QComboBox()
        self.cb_mot = QComboBox(); self.cb_res = QComboBox()
        c2 = Card(2, "Dados do chamado")
        c2.add(Linha(campo("Ticket / RMA", self.ed_ticket, obrig=True),
                     campo("Serial Number", self.ed_serial)))
        c2.add(Linha(campo("Status do chamado", self.cb_status, obrig=True),
                     campo("Fabricante", self.cb_fab, extra="(digite p/ adicionar)")))
        c2.add(campo("Motivo", self.cb_mot, extra="(digite p/ adicionar)"))
        c2.add(campo("Resolução", self.cb_res, extra="(preencher ao concluir · digite p/ adicionar)"))
        lay.addWidget(c2)

        self.cb_resp = QComboBox(); self.cb_resp.addItem("— carregando responsáveis… —", None)
        self.b_resp_reload = QPushButton("↻"); self.b_resp_reload.setObjectName("secondary")
        self.b_resp_reload.setFixedWidth(40); self.b_resp_reload.clicked.connect(self._carregar_resp)
        rrow = QWidget(); rrow.setStyleSheet("background:transparent;")
        rrl = QHBoxLayout(rrow); rrl.setContentsMargins(0, 0, 0, 0); rrl.setSpacing(8)
        rrl.addWidget(self.cb_resp, 1); rrl.addWidget(self.b_resp_reload)
        c2 = Card(2, "Responsável")
        c2.add(campo("Requerido por", rrow, obrig=True, extra="(digite p/ pesquisar)"))
        lay.addWidget(c2)

        self.chk_concluir = QCheckBox("Concluir a OS assim que criar")
        self.chk_concluir.setToolTip("Fecha a OS no Fracttal logo após criá-la (irreversível)")
        self.ed_obs = QLineEdit(); self.ed_obs.setPlaceholderText("observação do chamado (opcional)")
        c3 = Card(3, "Opções")
        c3.add(self.chk_concluir)
        c3.add(campo("Incluir alguma observação", self.ed_obs, extra="(opcional)"))
        lay.addWidget(c3)
        lay.addStretch(1)

        sep = QFrame(); sep.setFixedHeight(1); sep.setStyleSheet("background:rgba(255,255,255,0.06);")
        outer.addWidget(sep)
        foot = QHBoxLayout(); foot.setContentsMargins(18, 10, 18, 13); foot.setSpacing(10)
        self.hint = QLabel(""); self.hint.setObjectName("uiAjuda")
        foot.addWidget(self.hint); foot.addStretch(1)
        self.btn = QPushButton("Criar OS de chamado"); self.btn.setObjectName("btnPrimary")
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor); self.btn.setEnabled(False)
        self.btn.clicked.connect(self._criar)
        foot.addWidget(self.btn)
        outer.addLayout(foot)
        return page

    # ══════════════════════ ACOMPANHAR (board) ══════════════════════
    def _build_board(self):
        page = QWidget()
        outer = QVBoxLayout(page); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        bar = QHBoxLayout(); bar.setContentsMargins(18, 8, 18, 8); bar.setSpacing(10)
        self.board_hint = QLabel("—"); self.board_hint.setObjectName("uiAjuda")
        bar.addWidget(self.board_hint); bar.addStretch(1)
        self.b_reload = QPushButton("Atualizar"); self.b_reload.setObjectName("secondary")
        self.b_reload.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_reload.clicked.connect(lambda: self._carregar_board(force=True))
        bar.addWidget(self.b_reload)
        outer.addLayout(bar)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        scroll.viewport().setStyleSheet("background:transparent;")
        host = QWidget(); host.setStyleSheet("background:transparent;"); scroll.setWidget(host)
        self._grid = QGridLayout(host); self._grid.setContentsMargins(18, 4, 18, 16)
        self._grid.setSpacing(12); self._grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        outer.addWidget(scroll, 1)
        self.board_vazio = QLabel("Nenhuma OS com a etiqueta CHAMADOS por aqui ainda.")
        self.board_vazio.setObjectName("uiAjuda")
        self._grid.addWidget(self.board_vazio, 0, 0, 1, 3)
        return page

    # ── troca de aba ──
    @slot_seguro
    def _on_seg(self, i):
        self.stack.setCurrentIndex(i)
        if i == 1 and not self._board_loaded:
            self._carregar_board()

    # ══════════════════════ carga inicial ══════════════════════
    def carregar_inicial(self):
        self._popular_listas()
        tornar_pesquisavel(self.cb_resp)
        self._carregar_resp()

    def _popular_listas(self):
        self._listas = _load_listas()
        for cb, chave, ph in ((self.cb_fab, "fabricante", "— fabricante —"),
                              (self.cb_status, "status", "— selecione —"),
                              (self.cb_mot, "motivo", "— motivo —"),
                              (self.cb_res, "resolucao", "— (ao concluir) —")):
            cur = cb.currentText() if cb.count() else ""
            cb.blockSignals(True); cb.clear(); cb.addItem(ph); cb.addItems(self._listas.get(chave, []))
            cb.setCurrentIndex(0); cb.blockSignals(False)
            tornar_pesquisavel(cb)          # editável + busca; digitar opção nova é aceito (persiste ao criar)

    @staticmethod
    def _cbval(cb):
        t = (cb.currentText() or "").strip()
        return "" if t.startswith("—") else t

    def _subtarefas_chamado(self):
        """Subtarefas do chamado (Lista, com a lista-padrão completa em dropdown_options + valor escolhido
        → editáveis no Fracttal enquanto a OS está aberta)."""
        LST = 7
        def opts(chave, sel):
            base = list(self._listas.get(chave, []))
            if sel and sel not in base:
                base.append(sel)
            return [{"description": o} for o in base]
        subs = []
        tk = self.ed_ticket.text().strip()
        if tk:
            subs.append({"description": "Ticket / RMA", "id_task_form_item_type": 1,
                         "value": tk, "is_required": True})
        sn = self.ed_serial.text().strip()
        if sn:
            subs.append({"description": "Serial Number", "id_task_form_item_type": 1, "value": sn})
        # (desc, chave, combo, is_required, sempre_cria) — Status e Resolução SEMPRE viram subtarefa
        # (Resolução mesmo vazia, p/ a Syngrid preencher ao concluir); Fabricante/Motivo só se escolhidos.
        for desc, chave, cb, req, sempre in (
                ("Fabricante", "fabricante", self.cb_fab, False, False),
                ("Motivo do chamado", "motivo", self.cb_mot, False, False),
                ("Status do chamado", "status", self.cb_status, True, True),
                ("Resolução", "resolucao", self.cb_res, False, True)):
            v = self._cbval(cb)
            if v or sempre:
                item = {"description": desc, "id_task_form_item_type": LST,
                        "dropdown_options": opts(chave, v), "is_required": req}
                if v:
                    item["value"] = v
                subs.append(item)
        return subs

    def _dados_chamado(self):
        """Campos do chamado p/ o BLOCO na observação (o board lê daqui). os_pai = a OS pai."""
        return {"ticket": self.ed_ticket.text().strip(), "serial": self.ed_serial.text().strip(),
                "status": self._cbval(self.cb_status), "fabricante": self._cbval(self.cb_fab),
                "motivo": self._cbval(self.cb_mot), "resolucao": self._cbval(self.cb_res)}

    def _carregar_resp(self):
        self._wr = ApiWorker(api.get_responsaveis)
        self._wr.ok.connect(self._set_resp); self._wr.erro.connect(lambda *_: None)
        self._wr.start()

    @slot_seguro
    def _set_resp(self, pessoas):
        self._wr = None
        self.cb_resp.clear(); self.cb_resp.addItem("— selecione —", None)
        for p in (pessoas or []):
            self.cb_resp.addItem(p.get("name") or p.get("code") or "?", p)

    # ══════════════════════ board: carga + render ══════════════════════
    def _carregar_board(self, force=False):
        if self._wl is not None:
            return
        self._board_loaded = True
        self.board_hint.setText("carregando chamados…"); self.b_reload.setEnabled(False)
        hoje = _dt.date.today()
        de = (hoje - _dt.timedelta(days=180)).isoformat()
        self._wl = ApiWorker(api.list_chamados, de, hoje.isoformat(), None)
        self._wl.ok.connect(self._board_ok); self._wl.erro.connect(self._board_err)
        self._wl.start()

    @slot_seguro
    def _board_err(self, m):
        self._wl = None; self.b_reload.setEnabled(True)
        self.board_hint.setText("erro ao carregar")
        QMessageBox.critical(self, "Chamados", f"Erro ao carregar os chamados: {m}")

    @slot_seguro
    def _board_ok(self, itens):
        self._wl = None; self.b_reload.setEnabled(True)
        itens = itens if isinstance(itens, list) else []
        # limpa o grid
        while self._grid.count():
            it = self._grid.takeAt(0); w = it.widget()
            if w and w is not self.board_vazio:
                w.deleteLater()
        n = len(itens)
        self.board_hint.setText(f"{n} chamado(s) — clique num card para abrir a OS"
                                if n else "Nenhum chamado no período (últimos 180 dias).")
        if not itens:
            self.board_vazio.setVisible(True); self._grid.addWidget(self.board_vazio, 0, 0, 1, 3)
            return
        self.board_vazio.setVisible(False)
        COLS = 3
        for i, d in enumerate(itens):
            self._grid.addWidget(_ChamadoCard(d, self._abrir_os), i // COLS, i % COLS)
        self._grid.setColumnStretch(COLS, 0)
        for c in range(COLS):
            self._grid.setColumnStretch(c, 1)

    def _abrir_os(self, d):
        wid = d.get("id")
        if wid:
            abrir_os_detalhe(self, wid, d.get("folio"))

    # ══════════════════════ NOVO: buscar OS pai ══════════════════════
    @slot_seguro
    def _buscar(self, *_):
        num = (self.ed_os.text() or "").strip()
        if not num:
            QMessageBox.information(self, "Chamado", "Digite o número da OS."); return
        if self._wb is not None:
            return
        self.btn.setEnabled(False); self._parent = None
        self.b_busca.setEnabled(False); self.b_busca.setText("buscando…")
        self.lb_ativo.setText("—"); self.lb_sub.setText("Procurando a OS…")
        self._wb = ApiWorker(api.get_os_detalhes_por_folio, num)
        self._wb.ok.connect(self._achou); self._wb.erro.connect(self._busca_err)
        self._wb.start()

    @slot_seguro
    def _busca_err(self, m):
        self._wb = None; self.b_busca.setEnabled(True); self.b_busca.setText("Buscar")
        self.lb_sub.setText("Erro ao buscar a OS.")
        QMessageBox.critical(self, "Chamado", f"Erro ao buscar a OS: {m}")

    @slot_seguro
    def _achou(self, d):
        self._wb = None; self.b_busca.setEnabled(True); self.b_busca.setText("Buscar")
        if not isinstance(d, dict):
            self.lb_ativo.setText("—"); self.lb_sub.setText("Nenhuma OS com esse número.")
            QMessageBox.warning(self, "Chamado", "Não achei nenhuma OS com esse número."); return
        if not (d.get("code") or "").strip():
            self.lb_ativo.setText(d.get("ativo") or "—")
            self.lb_sub.setText("Essa OS não tem um ativo do catálogo — não dá para herdar o ativo. "
                                "Escolha outra OS.")
            self.btn.setEnabled(False); return
        self._parent = d
        self.lb_ativo.setText(d.get("ativo") or "—")
        self.lb_sub.setText(f"OS pai: Nº {d.get('folio') or self.ed_os.text().strip()}   ·   "
                            f"a nova OS entra neste ativo, com a etiqueta CHAMADOS.")
        self.btn.setEnabled(True)

    # ══════════════════════ NOVO: criar ══════════════════════
    @slot_seguro
    def _criar(self, *_):
        if not isinstance(self._parent, dict):
            QMessageBox.information(self, "Chamado", "Busque a OS antes de criar o chamado."); return
        p = self.cb_resp.currentData()
        if not isinstance(p, dict) or not p.get("id_personnel"):
            QMessageBox.warning(self, "Responsável", "Escolha o responsável (requerido por)."); return
        tk = self.ed_ticket.text().strip()
        if not tk:
            QMessageBox.warning(self, "Chamado", "Preencha o Ticket / RMA."); return
        st = self._cbval(self.cb_status)
        if not st:
            QMessageBox.warning(self, "Chamado", "Escolha o Status do chamado."); return
        if self.chk_concluir.isChecked():
            if QMessageBox.question(self, "Concluir OS",
                    "A OS de chamado será criada e CONCLUÍDA em seguida (ação irreversível). Continuar?"
                    ) != QMessageBox.StandardButton.Yes:
                return
        # opções digitadas (novas) viram padrão pra próxima
        _add_opcao("fabricante", self._cbval(self.cb_fab)); _add_opcao("motivo", self._cbval(self.cb_mot))
        _add_opcao("status", st); _add_opcao("resolucao", self._cbval(self.cb_res))
        self._listas = _load_listas()
        subs = self._subtarefas_chamado()
        folio = str(self._parent.get("folio") or self.ed_os.text().strip())
        self.btn.setEnabled(False); self.hint.setText("criando a OS de chamado…")
        self._wc = ApiWorker(api.create_os_chamado, folio, p.get("id_personnel"),
                             p.get("code") or "", p.get("name") or "",
                             self.chk_concluir.isChecked(), (self.ed_obs.text() or "").strip(),
                             tk, self._cbval(self.cb_mot), subs, self._dados_chamado())
        self._wc.ok.connect(self._ok); self._wc.erro.connect(self._criar_err)
        self._wc.start()

    @slot_seguro
    def _criar_err(self, m):
        self._wc = None; self.btn.setEnabled(True); self.hint.setText("")
        QMessageBox.critical(self, "Chamado", f"Erro ao criar a OS: {m}")

    @slot_seguro
    def _ok(self, res):
        self._wc = None; self.btn.setEnabled(True); self.hint.setText("")
        if not isinstance(res, dict) or not res.get("ok"):
            QMessageBox.critical(self, "Chamado", (isinstance(res, dict) and res.get("erro"))
                                 or "Não consegui criar a OS."); return
        partes = [f"OS de chamado criada — Nº {res.get('folio') or '?'}.",
                  f"Vinculada à OS pai {res.get('os_pai')} com a etiqueta CHAMADOS."]
        if res.get("concluida"):
            partes.append("A OS já foi concluída.")
        if res.get("aviso"):
            partes.append("\nAviso: " + res["aviso"])
        QMessageBox.information(self, "Chamado criado", "\n".join(partes))
        self.ed_os.clear(); self.ed_obs.clear(); self.chk_concluir.setChecked(False)
        self.ed_ticket.clear(); self.ed_serial.clear(); self._popular_listas()   # limpa os dados do chamado
        self._parent = None; self.btn.setEnabled(False)
        self.lb_ativo.setText("—")
        self.lb_sub.setText("Busque uma OS para ver o ativo e a usina que o chamado vai usar.")
        self._board_loaded = False          # próxima visita ao board recarrega (o novo chamado aparece)
