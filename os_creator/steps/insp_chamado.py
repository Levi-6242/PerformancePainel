"""Inspeção de chamados — a OS de teste que fundamenta um chamado de garantia.

O supervisor/COS diz USINA → TIPO DE ATIVO → ATIVO → MARCA, e as subtarefas descem prontas no
padrão que aquele fabricante exige (`chamado_insp_spec`). É o conserto da dor da Singrid: hoje o
técnico anexa uma foto borrada da plaqueta e nada digitado, e ela garimpa serial e sintoma para
conseguir abrir o ticket.

Duas coisas que a tela faz sozinha, e por quê:
- a MARCA vem pré-selecionada da descrição do ativo (medido: 94% dos inversores e 85% das
  estruturas de tracker trazem a marca no texto; na ETM é 1%, então lá o campo nasce vazio mesmo);
- com OS PAI informada, a DATA DO INCIDENTE é herdada dela — foi decisão do Levi (29/07), e evita
  que a OS filha conte uma história com data diferente da OS que a originou.
"""
from datetime import timedelta, timezone

BRT = timezone(timedelta(hours=-3))     # o app manda em UTC; sem carimbar Brasília, 12:00 vira 09:00

from PyQt6.QtCore import Qt, QDate, QTime, QDateTime
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit,
                             QPushButton, QScrollArea, QMessageBox, QDateTimeEdit, QFrame,
                             QTextEdit, QSizePolicy)


def _amanha_8h() -> QDateTime:
    """Amanhã às 8h — o horário em que a equipe de campo efetivamente sai."""
    return QDateTime(QDate.currentDate().addDays(1), QTime(8, 0))


def _prog_apos(dt: QDateTime) -> QDateTime:
    """Ida a campo: AMANHÃ às 8h — amanhã em relação a HOJE, nunca ao incidente (Levi, 03/08).

    O `dt` do incidente só serve de piso: se ele for futuro (OS aberta com antecedência), a visita
    vai para o dia seguinte a ELE. Para trás nunca: incidente de 28/07 herdado de uma OS pai
    agendava a inspeção para 29/07, uma data que já passou — o Fracttal aceita e a OS nasce
    atrasada. A hora fixa em 8h porque falha às 3h da manhã não gera visita às 3h da manhã."""
    amanha = QDateTime(QDate.currentDate().addDays(1), QTime(8, 0))
    do_inc = QDateTime(dt.date().addDays(1), QTime(8, 0))
    return do_inc if do_inc > amanha else amanha


def _iso_para_brt(iso) -> QDateTime:
    """ISO do Fracttal (UTC) → QDateTime em horário de Brasília. Inválido → QDateTime() vazio.

    O Fracttal devolve `event_date` em UTC. Ler a string crua no widget punha a hora 3 h à frente:
    a OS 10391 tem incidente às 08:00 e o campo mostrava 11:00, enquanto o aviso ao lado — que
    passa pelo `api.fmt_data_br` — dizia 08:00. Mesma fonte, duas horas diferentes na mesma linha."""
    dt = api._parse_iso(iso)
    if dt is None:
        return QDateTime()
    dt = dt.replace(tzinfo=timezone.utc).astimezone(BRT)
    return QDateTime(QDate(dt.year, dt.month, dt.day), QTime(dt.hour, dt.minute))

import api
import chamado_insp_spec as ci
from workers import ApiWorker, slot_seguro
from steps.ui import (QSS_FORM, Card, campo, rotulo, Linha, GREEN, MUTED, TEXT, INPUT, BORDER,
                      CARD)
from steps.searchcombo import tornar_todos_pesquisaveis

SEM_CLI = "— Selecione o cliente —"
SEM_USI = "— Selecione a usina —"
SEM_TIPO = "— Selecione o tipo de ativo —"
SEM_ATIVO = "— Selecione o ativo —"
SEM_MARCA = "— Selecione a marca —"


COR_STATUS = {"Em Processo": "#d9a441", "Em Verificação": "#57b6f5",
              "Concluída": GREEN, "Cancelada": "#e0645f"}


class _LinhaOS(QFrame):
    """Uma OS no painel de histórico do ativo. A linha INTEIRA é o botão — clicar preenche a OS
    pai. Antes só dava para ler o número e digitar, que é onde entra erro de dígito."""
    def __init__(self, d, on_click):
        super().__init__()
        self._on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("linhaOS")
        self.setStyleSheet(
            "QFrame#linhaOS{background:transparent;border:none;border-left:2px solid transparent;}"
            "QFrame#linhaOS:hover{background:rgba(143,206,63,0.08);border-left-color:%s;}" % GREEN)
        h = QHBoxLayout(self); h.setContentsMargins(13, 9, 14, 9); h.setSpacing(13)
        n = QLabel(str(d.get("folio") or "—"))
        n.setStyleSheet("color:%s;font-family:Consolas,monospace;font-size:13px;font-weight:700;"
                        "background:transparent;border:none;" % GREEN)
        n.setMinimumWidth(52)
        h.addWidget(n, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout(); col.setSpacing(1)
        t = QLabel(str(d.get("descricao") or "—")); t.setWordWrap(False)
        t.setStyleSheet("color:%s;font-size:12.5px;background:transparent;border:none;" % TEXT)
        t.setToolTip(str(d.get("descricao") or ""))
        col.addWidget(t)
        sub = " · ".join(x for x in (d.get("tipo_tarefa") or "",
                                     api.fmt_data_br(d.get("event_date")) or "") if x)
        s = QLabel(sub)
        s.setStyleSheet("color:%s;font-size:11px;background:transparent;border:none;" % MUTED)
        col.addWidget(s)
        h.addLayout(col, 1)
        st = str(d.get("status") or "—")
        chip = QLabel(st)
        cor = COR_STATUS.get(st, MUTED)
        chip.setStyleSheet("color:%s;background:rgba(255,255,255,0.05);border:1px solid %s66;"
                           "border-radius:9px;padding:2px 9px;font-size:11px;font-weight:600;"
                           % (cor, cor))
        h.addWidget(chip, 0, Qt.AlignmentFlag.AlignTop)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._on_click:
            self._on_click()
        super().mousePressEvent(e)


class _PainelOS(QFrame):
    """Popup com as últimas OS do ativo. Popup próprio (e não tooltip) porque o tooltip fecha ao
    mover o mouse — com 10 OS não dá para percorrer a lista, e nele nada é clicável."""
    def __init__(self, ancora, ativo, linhas, on_escolher):
        super().__init__(ancora, Qt.WindowType.Popup)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setObjectName("painelOS")
        self.setStyleSheet("QFrame#painelOS{background:%s;border:1px solid %s;border-radius:12px;}"
                           % (CARD, BORDER))
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
        cab = QWidget(); cab.setStyleSheet("background:transparent;")
        cv = QVBoxLayout(cab); cv.setContentsMargins(15, 12, 15, 10); cv.setSpacing(2)
        lin = QHBoxLayout(); lin.setSpacing(8)
        tit = QLabel("ÚLTIMAS OS DESTE ATIVO")
        tit.setStyleSheet("color:%s;font-size:10.5px;font-weight:700;letter-spacing:.8px;"
                          "background:transparent;" % MUTED)
        lin.addWidget(tit); lin.addStretch(1)
        if linhas:
            dica = QLabel("clique para usar como OS pai")
            dica.setStyleSheet("color:%s;font-size:11px;font-weight:600;background:transparent;"
                               % GREEN)
            lin.addWidget(dica)
        cv.addLayout(lin)
        nome = QLabel(ativo or "—")
        nome.setStyleSheet("color:%s;font-size:12.5px;font-weight:600;background:transparent;" % TEXT)
        cv.addWidget(nome)
        v.addWidget(cab)
        sep = QFrame(); sep.setFixedHeight(1); sep.setStyleSheet("background:%s;" % BORDER)
        v.addWidget(sep)
        if not linhas:
            vazio = QLabel("Este ativo ainda não tem OS registrada.")
            vazio.setStyleSheet("color:%s;font-size:12.5px;background:transparent;padding:14px 15px;"
                                % MUTED)
            v.addWidget(vazio)
        for i, d in enumerate(linhas):
            v.addWidget(_LinhaOS(d, lambda dd=d: (on_escolher(dd), self.close())))
            if i < len(linhas) - 1:
                s2 = QFrame(); s2.setFixedHeight(1)
                s2.setStyleSheet("background:rgba(255,255,255,0.04);")
                v.addWidget(s2)
        if linhas:
            rod = QLabel("%d OS registradas neste ativo" % len(linhas))
            rod.setStyleSheet("color:%s;font-size:11px;background:transparent;padding:9px 15px 11px;"
                              % MUTED)
            v.addWidget(rod)
        self.setFixedWidth(min(680, max(420, ancora.window().width() - 120)))

    def abrir(self, ancora):
        self.adjustSize()
        p = ancora.mapToGlobal(ancora.rect().bottomLeft())
        self.move(p.x() - 8, p.y() + 6)
        self.show()


class InspChamadoTab(QWidget):
    def __init__(self, on_voltar=None):
        super().__init__()
        self._on_voltar = on_voltar
        self._assets = []
        self._pessoas = []
        self._pai = None                 # detalhe da OS pai (quando o nº for encontrado)
        self._pai_data = None            # data que o painel mostrou (fallback do event_date)
        self._w = self._wp = self._wr = self._wh = None
        self.setStyleSheet(QSS_FORM)

        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(); scroll.setWidget(body); root.addWidget(scroll, 1)
        lay = QVBoxLayout(body); lay.setContentsMargins(18, 12, 18, 14); lay.setSpacing(14)

        # ── Card 1: o equipamento ──
        self.cb_cli = QComboBox(); self.cb_usi = QComboBox()
        self.cb_tipo = QComboBox(); self.cb_ativo = QComboBox(); self.cb_marca = QComboBox()
        for cb in (self.cb_cli, self.cb_usi, self.cb_tipo, self.cb_ativo, self.cb_marca):
            cb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.cb_cli.currentIndexChanged.connect(self._on_cli)
        self.cb_usi.currentIndexChanged.connect(self._on_usi)
        self.cb_tipo.currentIndexChanged.connect(self._on_tipo)
        self.cb_ativo.currentIndexChanged.connect(self._on_ativo)
        self.cb_marca.currentIndexChanged.connect(self._preview)

        c1 = Card(1, "Equipamento com falha")
        c1.add(Linha(campo("Cliente", self.cb_cli, obrig=True),
                     campo("Usina", self.cb_usi, obrig=True)))
        c1.add(Linha(campo("Tipo de ativo", self.cb_tipo, obrig=True),
                     campo("Ativo", self.cb_ativo, obrig=True)))
        c1.add(campo("Marca do ativo", self.cb_marca, obrig=True,
                     extra="(vem preenchida quando o cadastro do ativo diz a marca)"))
        lay.addWidget(c1)

        # ── Card 2: origem e quando ──
        self.ed_pai = QLineEdit(); self.ed_pai.setPlaceholderText("nº da OS que originou (opcional)")
        self.ed_pai.setFixedWidth(210)
        self.ed_pai.editingFinished.connect(self._buscar_pai)
        self.lb_pai = QLabel("Sem OS pai: a data do incidente é a que você escolher abaixo.")
        self.lb_pai.setWordWrap(True)
        self.lb_pai.setStyleSheet(f"color:{MUTED};font-size:12px;background:transparent;")
        # dica com as últimas 10 OS do ativo: o número da OS pai ninguém decora, e sem isso a
        # pessoa sai da tela para procurar no histórico (pedido do Levi, 30/07)
        self.lb_hist = QPushButton("Últimas OS")
        self.lb_hist.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lb_hist.setStyleSheet(
            "QPushButton{background:rgba(143,206,63,0.12);color:%s;border:1px solid %s55;"
            "border-radius:8px;padding:5px 11px;font-size:12px;font-weight:600;min-height:0;}"
            "QPushButton:hover{background:rgba(143,206,63,0.20);border-color:%s;}" % (GREEN, GREEN, GREEN))
        self.lb_hist.setToolTip("Escolha o ativo para ver as últimas OS dele.")
        self.lb_hist.clicked.connect(self._abrir_painel_os)
        self.lb_hist.setVisible(False)
        self._hist = []                # últimas OS do ativo (alimenta a dica e o painel)
        pai_w = QWidget(); pai_w.setStyleSheet("background:transparent;")
        pl = QHBoxLayout(pai_w); pl.setContentsMargins(0, 0, 0, 0); pl.setSpacing(9)
        pl.addWidget(self.ed_pai); pl.addWidget(self.lb_hist); pl.addStretch(1)

        # DATA E HORA nos dois (Levi, 30/07). Só a data não bastava: a OS pai traz a hora do
        # incidente, o Fracttal guarda hora, e "quando o técnico vai a campo" é uma hora do dia,
        # não um dia inteiro. A ida a campo nasce AMANHÃ às 8h — nunca no instante do incidente.
        self.dt_inc = QDateTimeEdit(QDateTime.currentDateTime()); self.dt_inc.setCalendarPopup(True)
        self.dt_inc.setDisplayFormat("dd/MM/yyyy HH:mm")
        self.dt_prog = QDateTimeEdit(_amanha_8h()); self.dt_prog.setCalendarPopup(True)
        self.dt_prog.setDisplayFormat("dd/MM/yyyy HH:mm")

        c2 = Card(2, "Origem e datas")
        c2.add(campo("OS pai", pai_w, extra="(a data do incidente passa a ser a dela)"))
        c2.add(self.lb_pai)
        c2.add(Linha(campo("Data do incidente", self.dt_inc, obrig=True),
                     campo("Data programada", self.dt_prog, obrig=True,
                           extra="(quando o técnico vai a campo)")))
        lay.addWidget(c2)

        # ── Card 3: quem executa + observação ──
        self.cb_resp = QComboBox()
        self.cb_resp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.ed_obs = QTextEdit(); self.ed_obs.setFixedHeight(74)
        self.ed_obs.setPlaceholderText("contexto para o técnico (opcional)")
        c3 = Card(3, "Execução")
        c3.add(campo("Responsável em campo", self.cb_resp, obrig=True))
        c3.add(campo("Observação", self.ed_obs))
        lay.addWidget(c3)

        # ── Card 4: o que a OS vai levar ──
        self.lb_resumo = QLabel("Escolha o ativo e a marca para ver as subtarefas.")
        self.lb_resumo.setStyleSheet(f"color:{GREEN};font-size:13px;font-weight:600;"
                                     "background:transparent;")
        self.lb_subs = QLabel("—"); self.lb_subs.setWordWrap(True)
        self.lb_subs.setObjectName("readboxSubs")
        self.lb_subs.setStyleSheet("background:%s;border:1px solid %s;border-radius:10px;"
                                   "padding:11px 13px;color:#c4cbdb;font-size:12.5px;"
                                   % (INPUT, BORDER))
        c4 = Card(4, "Subtarefas que a OS vai levar")
        c4.add(self.lb_resumo)
        c4.add(self.lb_subs)
        lay.addWidget(c4)
        lay.addStretch(1)

        # ── rodapé ──
        sep = QFrame(); sep.setFixedHeight(1)
        sep.setStyleSheet("background:rgba(255,255,255,0.06);")
        root.addWidget(sep)
        rod = QHBoxLayout(); rod.setContentsMargins(18, 10, 18, 12); rod.setSpacing(9)
        self.b_voltar = QPushButton("← Voltar"); self.b_voltar.setObjectName("secondary")
        self.b_voltar.clicked.connect(lambda: self._on_voltar and self._on_voltar())
        self.hint = QLabel(""); self.hint.setObjectName("uiAjuda")
        self.b_criar = QPushButton("Criar OS de inspeção"); self.b_criar.setObjectName("primary")
        self.b_criar.clicked.connect(self._criar)
        for b in (self.b_voltar, self.b_criar):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        rod.addWidget(self.b_voltar); rod.addWidget(self.hint, 1); rod.addWidget(self.b_criar)
        root.addLayout(rod)

        tornar_todos_pesquisaveis(self)
        self._carregar()

    # ── carga ──
    def _carregar(self):
        self.hint.setText("carregando ativos…")
        self._w = ApiWorker(api.load_assets_cached)
        self._w.ok.connect(self._set_assets)
        self._w.erro.connect(lambda m: self.hint.setText("não consegui carregar os ativos: %s" % m))
        self._w.start()
        self._wr = ApiWorker(api.get_responsaveis)
        self._wr.ok.connect(self._set_resp)
        self._wr.erro.connect(lambda *_: None)
        self._wr.start()

    @slot_seguro
    def _set_assets(self, assets):
        self._w = None
        # `ci.aceita` e não `in POR_TIPO`: piranômetro, sensor de temperatura e fieldlogger são
        # tipos próprios no Fracttal e usam o bloco da Estação Meteorológica pelo ALIAS_TIPO.
        self._assets = [a for a in (assets or []) if ci.aceita(a.get("tipo")) and a.get("usina")]
        self.hint.setText("")
        clientes = sorted({a.get("cliente") for a in self._assets if a.get("cliente")})
        self.cb_cli.blockSignals(True); self.cb_cli.clear()
        self.cb_cli.addItem(SEM_CLI); self.cb_cli.addItems(clientes)
        self.cb_cli.blockSignals(False)
        self._fill_usinas()

    @slot_seguro
    def _set_resp(self, pessoas):
        self._wr = None
        self._pessoas = pessoas or []
        self.cb_resp.blockSignals(True); self.cb_resp.clear()
        self.cb_resp.addItem("— Selecione o responsável —", None)
        for p in self._pessoas:
            self.cb_resp.addItem(p.get("name") or "", p.get("id_personnel"))
        self.cb_resp.blockSignals(False)

    # ── cascata ──
    def _sel(self, cb, vazio):
        t = cb.currentText()
        return None if (cb.currentIndex() <= 0 or t == vazio) else t

    def _fill_usinas(self):
        cli = self._sel(self.cb_cli, SEM_CLI)
        base = [a for a in self._assets if not cli or a.get("cliente") == cli]
        usinas = sorted({a["usina"] for a in base})
        self.cb_usi.blockSignals(True); self.cb_usi.clear()
        self.cb_usi.addItem(SEM_USI); self.cb_usi.addItems(usinas)
        self.cb_usi.blockSignals(False)
        self._fill_tipos()

    def _fill_tipos(self):
        usi = self._sel(self.cb_usi, SEM_USI)
        tipos = sorted({a["tipo"] for a in self._assets if not usi or a.get("usina") == usi})
        self.cb_tipo.blockSignals(True); self.cb_tipo.clear()
        self.cb_tipo.addItem(SEM_TIPO); self.cb_tipo.addItems(tipos)
        self.cb_tipo.blockSignals(False)
        self._fill_ativos()

    def _fill_ativos(self):
        usi, tp = self._sel(self.cb_usi, SEM_USI), self._sel(self.cb_tipo, SEM_TIPO)
        itens = [a for a in self._assets
                 if (not usi or a.get("usina") == usi) and (not tp or a.get("tipo") == tp)]
        itens.sort(key=lambda a: str(a.get("description") or ""))
        self.cb_ativo.blockSignals(True); self.cb_ativo.clear()
        self.cb_ativo.addItem(SEM_ATIVO, None)
        for a in itens[:2000]:            # teto de render; usina real tem ~150 do mesmo tipo
            self.cb_ativo.addItem((str(a.get("description") or "").split("{")[0]).strip()[:70], a)
        self.cb_ativo.blockSignals(False)
        self._fill_marcas()

    def _fill_marcas(self):
        """Marcas do TIPO escolhido, com a do cadastro do ativo já selecionada."""
        tp = self._sel(self.cb_tipo, SEM_TIPO)
        a = self.cb_ativo.currentData()
        marcas = ci.marcas_para(tp or "")
        sugerida = ci.marca_do_ativo(a) if isinstance(a, dict) else ""
        if not sugerida and isinstance(a, dict):
            sugerida = self._marca_pelos_irmaos(a, marcas)
        self.cb_marca.blockSignals(True); self.cb_marca.clear()
        self.cb_marca.addItem(SEM_MARCA); self.cb_marca.addItems(marcas)
        if sugerida and sugerida in marcas:
            self.cb_marca.setCurrentIndex(self.cb_marca.findText(sugerida))
        self.cb_marca.blockSignals(False)
        # marca reconhecida no ativo mas SEM processo de chamado escrito (SolarEdge, Growatt…):
        # avisa, senão a pessoa fica procurando o nome na lista sem entender por que não está lá
        if sugerida and sugerida not in marcas:
            self.hint.setText("O ativo é %s, que ainda não tem processo de chamado documentado — "
                              "escolha a marca correta ou fale com a Singrid." % sugerida)
        self._preview()

    def _marca_pelos_irmaos(self, a, marcas):
        """Marca inferida dos ATIVOS IRMÃOS da mesma usina, quando o próprio não a diz.

        NCU, RSU e os sensores da estação se chamam só 'NCU 1', 'Piranômetro 1' — não há marca no
        texto. Mas os trackers da mesma planta dizem ('Tracker 1.100 STI …'), e a NCU de uma planta
        de trackers STI é STI. Só sugere quando os irmãos apontam para UMA marca válida: duas
        marcas na mesma usina viram campo vazio, que é a resposta honesta."""
        usi = a.get("usina")
        if not usi or not marcas:
            return ""
        validas = set(marcas)
        achadas = set()
        for x in self._assets:
            if x.get("usina") != usi or x is a:
                continue
            m = ci.marca_do_ativo(x)
            if m in validas:
                achadas.add(m)
                if len(achadas) > 1:
                    return ""
        return next(iter(achadas), "")

    @slot_seguro
    def _on_cli(self, *_):
        self._fill_usinas()

    @slot_seguro
    def _on_usi(self, *_):
        self._fill_tipos()

    @slot_seguro
    def _on_tipo(self, *_):
        self._fill_ativos()

    @slot_seguro
    def _on_ativo(self, *_):
        self._fill_marcas()
        self._carregar_historico()

    # ── últimas OS do ativo (dica do campo OS pai) ──
    def _carregar_historico(self):
        a = self.cb_ativo.currentData()
        if not isinstance(a, dict) or not a.get("id"):
            self.lb_hist.setVisible(False)
            return
        self.lb_hist.setVisible(True)
        self.lb_hist.setToolTip("buscando as últimas OS deste ativo…")
        if self._wh is not None:
            return
        self._wh = ApiWorker(api.ultimas_os_do_ativo, a["id"], 10)
        self._wh.ok.connect(self._set_historico)
        self._wh.erro.connect(self._historico_falhou)
        self._wh.start()

    @slot_seguro
    def _historico_falhou(self, m):
        self._wh = None
        self.lb_hist.setToolTip("não consegui ler o histórico deste ativo: %s" % m)

    @slot_seguro
    def _set_historico(self, linhas):
        self._wh = None
        self._hist = linhas or []
        if not self._hist:
            self.lb_hist.setToolTip("Este ativo ainda não tem OS registrada.")
            return
        # a dica do mouse continua (mostra sem precisar clicar); o clique abre o painel, onde dá
        # para percorrer com calma e escolher. Tooltip só quebra linha com HTML.
        itens = "".join(
            "<tr><td style='padding-right:12px'><b>%s</b></td>"
            "<td style='padding-right:12px'>%s</td>"
            "<td style='padding-right:12px'>%s</td>"
            "<td style='padding-right:12px'>%s</td><td>%s</td></tr>"
            % (l.get("folio") or "—", l.get("tipo_tarefa") or "—",
               api.fmt_data_br(l.get("event_date")) or "—", (l.get("status") or "—"),
               (l.get("descricao") or "—")[:46])
            for l in self._hist)
        self.lb_hist.setToolTip(
            "<b>Últimas %d OS deste ativo</b> &nbsp;<span style='color:#8fce3f'>clique para "
            "escolher</span><br><span style='color:#8a90a2'>nº · tipo de tarefa · incidente · "
            "status · título</span><table cellspacing='0'>%s</table>" % (len(self._hist), itens))

    @slot_seguro
    def _abrir_painel_os(self, *_):
        a = self.cb_ativo.currentData()
        if not isinstance(a, dict):
            return
        nome = (str(a.get("description") or "").split("{")[0]).strip()[:70]
        _PainelOS(self, nome, self._hist, self._escolher_os).abrir(self.lb_hist)

    @slot_seguro
    def _escolher_os(self, d):
        """Clique numa linha do painel → vira a OS pai (e dispara a herança de data e responsável).

        Guarda a data que o PAINEL mostrou: nem toda OS tem `event_date` no detalhe (a 6647 não
        tem), e a listagem cai na data programada. Sem isto, o usuário clicava numa linha que
        exibia 20/05 e o campo continuava em hoje — a tela se contradizendo."""
        self._pai_data = d.get("event_date")
        self._pai_folio_click = str(d.get("folio") or "")
        self.ed_pai.setText(str(d.get("folio") or ""))
        self._buscar_pai()

    # ── OS pai ──
    @slot_seguro
    def _buscar_pai(self, *_):
        folio = self.ed_pai.text().strip()
        if folio != getattr(self, '_pai_folio_click', None):
            self._pai_data = None        # digitado à mão → sem palpite do painel
        if not folio:
            self._pai = None
            self.lb_pai.setText("Sem OS pai: a data do incidente é a que você escolher abaixo.")
            return
        if self._wp is not None:
            return
        self.lb_pai.setText("procurando a OS %s…" % folio)
        self._wp = ApiWorker(api.get_os_detalhes_por_folio, folio)
        self._wp.ok.connect(self._set_pai)
        self._wp.erro.connect(self._pai_falhou)
        self._wp.start()

    @slot_seguro
    def _pai_falhou(self, m):
        self._wp = None
        self._pai = None
        self.lb_pai.setText("não consegui ler essa OS: %s" % m)

    @slot_seguro
    def _set_pai(self, d):
        self._wp = None
        self._pai = d or None
        if not self._pai:
            self.lb_pai.setText("OS não encontrada — confira o número.")
            return
        # herda DATA DO INCIDENTE e RESPONSÁVEL da OS pai (Levi, 30/07): a inspeção é a mesma
        # ocorrência, tocada por quem já está com ela — redigitar os dois só criava divergência.
        # A data programada NÃO é herdada: ela nasce um dia depois do incidente.
        herdado = []
        iso = self._pai.get("event_date") or self._pai_data
        dt = _iso_para_brt(iso)
        if dt.isValid():
            self.dt_inc.setDateTime(dt)                # herda a HORA do incidente, não só o dia
            self.dt_prog.setDateTime(_prog_apos(dt))
            herdado.append("incidente %s" % api.fmt_data_br(iso))
        resp = (self._pai.get("responsavel") or "").strip()
        if resp:
            i = self.cb_resp.findText(resp)
            if i < 0:                            # nome com espaço duplo/sobrenome: tenta o 1º nome
                alvo = resp.split()[0].lower()
                i = next((k for k in range(1, self.cb_resp.count())
                          if self.cb_resp.itemText(k).lower().startswith(alvo)), -1)
            if i > 0:
                self.cb_resp.setCurrentIndex(i)
                herdado.append("responsável %s" % self.cb_resp.currentText().strip())
            else:
                herdado.append("responsável da OS pai é %s, que não está na lista" % resp)
        self.lb_pai.setText("OS %s · %s%s" % (
            self._pai.get("folio"), (self._pai.get("descricao") or "—")[:60],
            ("  ·  herdado: " + ", ".join(herdado)) if herdado else ""))

    # ── prévia das subtarefas ──
    def _preview(self, *_):
        tp = self._sel(self.cb_tipo, SEM_TIPO)
        mk = self._sel(self.cb_marca, SEM_MARCA)
        if not tp or not mk:
            self.lb_resumo.setText("Escolha o ativo e a marca para ver as subtarefas.")
            self.lb_subs.setText("—")
            return
        subs = ci.subtarefas(tp, mk)
        self.lb_resumo.setText(ci.resumo(tp, mk))
        linhas = []
        for i, s in enumerate(subs, 1):
            marca = []
            if s.get("is_required"):
                marca.append("obrigatória")
            if s.get("attachments_required"):
                marca.append("anexo")
            suf = "  (%s)" % ", ".join(marca) if marca else ""
            linhas.append("%2d. %s%s" % (i, s["description"], suf))
        self.lb_subs.setText("\n".join(linhas))

    # ── criar ──
    @slot_seguro
    def _criar(self, *_):
        a = self.cb_ativo.currentData()
        mk = self._sel(self.cb_marca, SEM_MARCA)
        resp_id = self.cb_resp.currentData()
        if not isinstance(a, dict):
            QMessageBox.warning(self, "Inspeção de chamados", "Escolha o ativo."); return
        if not mk:
            QMessageBox.warning(self, "Inspeção de chamados", "Escolha a marca do ativo."); return
        if not resp_id:
            QMessageBox.warning(self, "Inspeção de chamados", "Escolha o responsável em campo."); return
        if self._w is not None:
            return
        subs = ci.subtarefas(a.get("tipo"), mk)
        if QMessageBox.question(
                self, "Criar OS de inspeção",
                "Criar a OS de inspeção com %d subtarefas?\n\nAtivo: %s\nMarca: %s\nEtiqueta: %s\n\n"
                "Quando o técnico terminar, abra o card desta OS e use \"Abrir chamado\" — "
                "as respostas dele vão preenchidas."
                % (len(subs), (str(a.get("description") or "").split("{")[0]).strip()[:60], mk,
                   api.LABEL_INSPECAO)) != QMessageBox.StandardButton.Yes:
            return
        self.b_criar.setEnabled(False); self.hint.setText("criando no Fracttal…")
        # A hora vem do campo, não é mais convenção. Carimbar BRT é obrigatório: o `_iso_z`
        # converte para UTC, e datetime ingênuo seria lido como se já fosse UTC (a OS 10400 de
        # teste nasceu com 12:00 virando 09:00).
        inc = self.dt_inc.dateTime().toPyDateTime().replace(tzinfo=BRT)
        prog = self.dt_prog.dateTime().toPyDateTime().replace(tzinfo=BRT)
        self._w = ApiWorker(
            api.create_inspecao_chamado, a, mk, resp_id, self.cb_resp.currentText(),
            inc, prog, (self._pai or {}).get("id_work_order"),
            self.ed_obs.toPlainText().strip())
        self._w.ok.connect(self._criou)
        self._w.erro.connect(self._falhou)
        self._w.start()

    @slot_seguro
    def _falhou(self, m):
        self._w = None
        self.b_criar.setEnabled(True); self.hint.setText("")
        QMessageBox.critical(self, "Inspeção de chamados", "Não consegui criar a OS:\n%s" % m)

    @slot_seguro
    def _criou(self, r):
        self._w = None
        self.b_criar.setEnabled(True); self.hint.setText("")
        r = r or {}
        msg = "OS %s criada com %s subtarefas." % (r.get("wo_folio") or "?", r.get("n_subtarefas"))
        if r.get("etiqueta_erro"):
            msg += "\n\nA OS existe, mas a etiqueta %s não foi aplicada:\n%s" % (
                api.LABEL_INSPECAO, r["etiqueta_erro"])
            QMessageBox.warning(self, "Inspeção de chamados", msg)
        else:
            QMessageBox.information(self, "Inspeção de chamados", msg)
        self.reiniciar()

    def aplicar_ativo(self, asset):
        """Pré-seleciona a cascata a partir de UM ativo — atalho da aba Ativos (Levi, 05/08).

        Desce na ordem cliente → usina → tipo → ativo deixando cada `currentIndexChanged` disparar,
        porque é ele que repopula o combo seguinte. Mexer nos quatro de uma vez com os sinais
        bloqueados deixaria os três de baixo com a lista do ativo anterior. Best-effort: nome que
        não estiver na lista simplesmente não seleciona, e a pessoa escolhe à mão."""
        if not isinstance(asset, dict):
            return
        for cb, valor in ((self.cb_cli, asset.get("cliente")), (self.cb_usi, asset.get("usina")),
                          (self.cb_tipo, asset.get("tipo"))):
            i = cb.findText(str(valor or ""))
            if i >= 0:
                cb.setCurrentIndex(i)
        code = str(asset.get("code") or "")
        for i in range(self.cb_ativo.count()):
            if code and code in self.cb_ativo.itemText(i):
                self.cb_ativo.setCurrentIndex(i); break

    # ── voltar à tela limpa (o app chama ao reentrar no modo) ──
    def reiniciar(self):
        self.ed_pai.clear(); self.ed_obs.clear()
        self._pai = None
        self.lb_pai.setText("Sem OS pai: a data do incidente é a que você escolher abaixo.")
        self.dt_inc.setDateTime(QDateTime.currentDateTime())
        self.dt_prog.setDateTime(_amanha_8h())      # o reset zerava a programada no MESMO dia
        for cb in (self.cb_cli, self.cb_usi, self.cb_tipo, self.cb_ativo, self.cb_marca,
                   self.cb_resp):
            cb.blockSignals(True); cb.setCurrentIndex(0); cb.blockSignals(False)
        self._fill_usinas()
        self.hint.setText("")
