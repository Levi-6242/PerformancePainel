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
from PyQt6.QtGui import QIcon, QFontMetrics, QFont, QBrush, QColor
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit,
                             QPushButton, QMessageBox, QCheckBox, QScrollArea, QFrame,
                             QStackedWidget, QGridLayout, QSizePolicy, QTableWidget,
                             QTableWidgetItem, QHeaderView, QAbstractItemView)
import api
from workers import ApiWorker, slot_seguro
import chamado_spec as cspec
import chamado_log as clog
import chamado_tokens as T
import chamado_fontes as CF
# Regra do projeto: CAIXA (card, botão, input) se estiliza com QSS; MARCA (ponto, régua, barra,
# trilho) se PINTA. Marca em QSS falhou de três jeitos aqui — raio fracionário descartado pelo
# parser (todo ponto saía QUADRADO), rgba que não compõe em pai transparente, e box-shadow que
# não existe. Ver chamado_pecas.py.
from chamado_pecas import Ponto, Regua, Trilho, BarraTempo, Combo, RotuloElidido


_FOLHA_CACHE = {}


def folha_caminho():
    """Onde está a folha do design 1B. → caminho existente ou "".

    MORA EM `assets/` DE PROPÓSITO: o `.spec` empacota `('assets','assets')` inteiro, então
    qualquer arquivo aí dentro viaja no build automaticamente. Quando a folha ficava solta em
    `os_creator/chamados.qss` ela NÃO ia para o `.exe` (o spec só levava `assets` e o
    `assets_cache.json`) — do código-fonte a tela saía certa e no app instalado caía no tema
    antigo, calada. Foi assim que a v92 chegou ao Levi com o design inteiro faltando.
    """
    import os as _os
    import sys as _sys
    aqui = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # …/os_creator
    raiz = getattr(_sys, "_MEIPASS", aqui)                                  # bundle → _internal
    for cam in (_os.path.join(raiz, "assets", "chamados.qss"),
                _os.path.join(aqui, "assets", "chamados.qss"),
                _os.path.join(raiz, "chamados.qss"),      # legado (builds antigas)
                _os.path.join(aqui, "chamados.qss")):
        if _os.path.exists(cam):
            return cam
    return ""


def _folha():
    """Folha do design 1B (docs/redesign/design_handoff_chamados_1b/chamados.qss).
    Lida de `assets/` — mexer no design é trocar o .qss, não o código."""
    if "s" in _FOLHA_CACHE:
        return _FOLHA_CACHE["s"]
    cam = folha_caminho()
    if cam:
        try:
            with open(cam, encoding="utf-8") as f:
                _FOLHA_CACHE["s"] = f.read()
                return _FOLHA_CACHE["s"]
        except OSError:
            pass
    # Cair no tema antigo não quebra a tela, mas DESTRÓI o design (foi o bug da v92). Grita:
    # `verificar_fontes.py` roda esta mesma checagem e barra o release.
    import sys as _sys
    print("[chamados] FOLHA NAO ENCONTRADA (assets/chamados.qss) — a tela vai sair com o tema "
          "antigo, sem o design 1B.", file=_sys.stderr)
    _FOLHA_CACHE["s"] = QSS_FORM
    return QSS_FORM
from steps.searchcombo import tornar_pesquisavel
from steps.os_detalhe import abrir_os_detalhe
from steps.ui import (QSS_FORM, Card, campo, rotulo, Linha, Segmentado, icone_pix,
                      GREEN, MUTED, TEXT, INPUT, BORDER)

_STATUS_COR = {"Em Processo": T.AMBER, "Em Verificação": T.BLUE, "Concluída": T.GREEN,
               "Cancelada": T.RED, "OS concluída": T.GREEN, "OS em verificação": T.BLUE,
               "Aberta": T.AMBER}

# Listas-PADRÃO das subtarefas do chamado (tiradas da planilha Gestão de Chamados). São a base;
# a Syngrid pode digitar uma opção nova no campo → fica salva em chamados_listas.json e passa a
# aparecer pra todos (padroniza sem engessar).
_LISTAS_BASE = {
    # Ciclo de vida do chamado — vem do chamado_spec (os 11 estados que os 9 processos por
    # fabricante descrevem). A lista antiga só tinha os "aguardando" e não cobria o desfecho:
    # faltavam garantia aprovada, garantia NEGADA (a Hukseflux tem esse ramo) e documentação/NF,
    # que é onde o processo mais trava.
    "status": list(cspec.STATUS),
    "motivo": ["Inversor desligado / sem operação", "Inversor com falha ou erro interno",
               "Inversor — ventoinha / exaustor", "Otimizador sem comunicação",
               "String sem corrente / sem comunicação", "Tracker parado / sem movimentação",
               "Tracker — motor / TCU", "Falha de comunicação / supervisório",
               "Módulo — dano / limpeza / vegetação", "Estação meteorológica / sensor",
               "Inject / precom / comissionamento"],
    "resolucao": ["Troca em garantia", "Substituição de peça/equipamento (fora de garantia)",
                  "Reparo em campo", "Reset / reconfiguração / normalização",
                  "Sem defeito encontrado", "Cancelado"],
    # Os 9 com processo documentado pela Singrid + os que já apareciam no app sem documento
    # (mantidos: existem OSs antigas com eles; entram no fim da lista).
    "fabricante": list(cspec.TODOS_FABRICANTES),
}


def _rgba(hexc, a):
    h = hexc.lstrip("#"); return f"rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{a})"


def _mix(cor, base, a):
    """Mistura SÓLIDA de `cor` sobre `base` com opacidade `a`. No QSS o rgba não compõe com o
    widget de baixo quando o pai é transparente — o fundo vazava claro. Então a tinta da situação
    é calculada aqui e sai como hex opaco."""
    c = cor.lstrip("#"); b = base.lstrip("#")
    m = [round(int(c[i:i + 2], 16) * a + int(b[i:i + 2], 16) * (1 - a)) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(m)


def _gradiente(cor, concluido=False):
    """Gradiente do topo do card na cor do grupo.

    O `T.card_gradient` do handoff usa 11% e não prevê o card concluído — e aquele arquivo é
    cópia fiel da spec, não se edita. Aqui o concluído ganha a MESMA tinta a 5%: some do
    primeiro plano sem deixar a coluna sem cor, que era a queixa ("Concluídos não tem degradê,
    Com o fabricante não tem degradê")."""
    if not concluido:
        return T.card_gradient(cor)
    return ("qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 %s, stop:0.46 %s, stop:1 %s)"
            % (T.rgba(cor, 0.05), T.CARD_MUTED, T.CARD_MUTED))


def cor_linha(base=None):
    """Cor OPACA de uma linha de 1px (divisória, trilho da timeline).

    MEDIDO, não deduzido: um fundo `rgba()` que vem DA FOLHA não pinta quando o widget está
    dentro de um pai com `background:transparent` — e as colunas do board e a lateral do
    detalhe são todas transparentes. Prova (offscreen, mesma árvore):
        folha + pai normal        -> pinta (31,33,39)
        folha + pai transparente  -> NÃO pinta
        inline (rgba ou hex)      -> pinta
    Daí a regra: linha de 1px leva stylesheet PRÓPRIO, com a mistura já resolvida em hex.
    `T.DIVIDER` é branco a 10%, então é isso que a mistura reproduz."""
    return _mix(T.TEXT_BRIGHT, base or T.SURFACE, 0.10)


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
    """Cor do status do CHAMADO. A régua é O QUE PRECISA DE AÇÃO, não a idade: 'a abrir' é
    vermelho mesmo com 1 dia, e 'defeituoso coletado' é verde mesmo com 40 — foi o que o Levi
    aprovou no mockup ('a tarja segue o que precisa de ação, não a data')."""
    s = (st or "").lower()
    if "a abrir" in s:
        return T.RED                      # ninguém abriu ainda → o mais urgente
    if "conclu" in s or "coletado" in s or "recebido na usina" in s:
        return T.GREEN
    if "negada" in s or "cancel" in s or "rejeit" in s:
        return T.RED
    if "aprovada" in s or "a caminho" in s:
        return T.BLUE                      # andando bem, só acompanhar
    # "teste" é ÂMBAR, não azul: "Testes adicionais solicitados" quer dizer que o FABRICANTE
    # pediu e está esperando — a bola está com ele, é espera, não progresso.
    if ("aguard" in s or "pendente" in s or "análise" in s or "analise" in s
            or "teste" in s):
        return T.AMBER
    if "standby" in s or "paus" in s:
        return T.TEXT_MUTED
    return _STATUS_COR.get(st, T.TEXT_MUTED)


# ── As três colunas do board (redesign 25/07) ────────────────────────────────
# Agrupa por DE QUEM A BOLA ESTÁ, não pela etapa da garantia: é a pergunta que a equipe de
# chamados faz o dia inteiro. Dos 317 chamados abertos da planilha, 113 estavam travados do
# NOSSO lado — e era isso que ninguém enxergava.
COLUNAS = T.GROUPS      # os três grupos e suas cores vêm dos tokens
_NOSSO = {"ninguém — ação nossa", "ninguem — acao nossa", "pré-operação", "pre-operacao",
          "equipe de campo"}


def _coluna_de(status, esperando, status_os=""):
    """Grupo do chamado — §5.1 do README (é o coração da direção 1B):
       Ação nossa       = aguardando Grid / Pré-Operação / vazio, MAIS os "A abrir"
       Com o fabricante = aguardando Fabricante ou Cliente
       Em andamento     = garantia aprovada, em trânsito e concluídos recentes
     é o fallback dos chamados do MODELO ANTIGO (etiqueta numa OS, sem status
    de chamado): sem ele, os legados caíam todos numa coluna só."""
    st, esp = (status or "").strip().lower(), (esperando or "").strip().lower()
    # EM VERIFICAÇÃO é AÇÃO NOSSA (28/07): a OS foi executada e está esperando a NOSSA conferência
    # — a bola está aqui, não com o fabricante. Antes caía em "Em andamento" junto das concluídas,
    # onde ninguém ia procurar trabalho pendente.
    if "verific" in (status_os or "").lower():
        return "AÇÃO NOSSA"
    if _encerrado(status, status_os) or "aprovada" in st or "caminho" in st             or "recebido na usina" in st:
        return "EM ANDAMENTO"
    if "a abrir" in st:
        return "AÇÃO NOSSA"
    if not st:                               # legado: quem manda é o estado da OS
        so = (status_os or "").strip().lower()
        return "AÇÃO NOSSA" if ("processo" in so or not so) else "EM ANDAMENTO"
    if esp.startswith("fabricante") or esp.startswith("cliente"):
        return "COM O FABRICANTE"
    if esp in _NOSSO:
        return "AÇÃO NOSSA"
    return "COM O FABRICANTE" if not esp else "AÇÃO NOSSA"


def _encerrado(status, status_os=""):
    """Chamado ACABADO. 'Em Verificação' SAIU daqui em 28/07: a OS ainda espera a conferência da
    Grid, então é trabalho pendente — tratá-la como encerrada apagava o card e o tirava da conta
    de 'parados há mais de 15 dias', que é justamente onde ela precisa aparecer."""
    s = (status or "").lower()
    if s:
        return "conclu" in s or "coletado" in s
    so = (status_os or "").lower()
    return "conclu" in so or "cancel" in so


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


# Encurtamento do status para caber como texto no topo do card. O nome inteiro fica no tooltip
# e na tela do chamado — aqui o que importa é bater o olho.
_CURTO = {
    "Aberto — aguardando fabricante": "Aguardando fabricante",
    "Testes adicionais solicitados": "Testes adicionais",
    "Evidências enviadas — em análise": "Em análise",
    "Garantia negada — orçamento": "Garantia negada",
    "Documentação / NF pendente": "NF pendente",
    "Equipamento novo a caminho": "Novo a caminho",
    "Novo recebido na usina": "Novo na usina",
}


def _curto(st):
    return _CURTO.get((st or "").strip(), (st or "").strip())


# `_chip()` foi APAGADA (§3.6 da revisão): pintava pílula de status com fundo preenchido, o que a
# §3.2 do README proíbe e o que estourava a largura das colunas no design antigo. Já estava morta
# no board, mas era o primeiro helper que alguém reusaria. Status = texto colorido + ponto;
# chip de fabricante = QLabel#chip, contorno puro.


def _texto_flex(lb):
    """QLabel que quebra de verdade dentro da coluna.

    `Ignored` na horizontal = "não peça largura, use a que sobrar". Sem isso o QLabel com
    wordWrap EXIGE a largura do texto inteiro, o heightForWidth é calculado contra uma largura
    que ele nunca vai ter, e o card fica com ~30px de vazio embaixo (ou corta o título em vez
    de quebrar). Era o caso dos cards 8903/8904/8273.

    CUIDADO ao usar: `Ignored` significa "não peça largura". Num QHBoxLayout com `addStretch()`
    antes do rótulo, a mola come tudo e o texto COLAPSA (os valores da lateral do detalhe
    sumiram assim). Nesses casos dê fator de esticamento ao rótulo em vez da mola.
    O vertical é `Preferred`, não `MinimumExpanding`: com Expanding a caixa cresce e desalinha
    quem divide a linha (o título saiu de baixo do número da OS)."""
    lb.setWordWrap(True)
    sp = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    sp.setHeightForWidth(True)
    lb.setSizePolicy(sp)
    lb.setMinimumWidth(1)
    return lb


# ══════════════════════════════════════════════════════════════════════════════
# BOARD — design "Chamados 1B" (docs/redesign/design_handoff_chamados_1b/).
# Os valores vêm de `chamado_tokens`; nada de hex digitado à mão aqui.
# ══════════════════════════════════════════════════════════════════════════════
_TOM = {T.RED: "red", T.AMBER: "amber", T.BLUE: "blue", T.GREEN: "green"}

# Goteira da barra de rolagem. NÃO vem do handoff (é detalhe de Qt, não de design): a folha
# declara `QScrollBar:vertical { width: 10px }` e a barra é desenhada por cima do conteúdo,
# então a coluna precisa recuar essa largura + um respiro.
_SCROLL_GUTTER = 14


def _cor_grupo(nome):
    for rot, cor in T.GROUPS:
        if rot == nome:
            return cor
    return T.BLUE


def _pintar_filtro(cb):
    """Acende a borda do filtro quando ele está filtrando. Propriedade dinâmica só entra em
    vigor depois de unpolish/polish — o Qt não reavalia o seletor sozinho."""
    cb.setProperty("ativo", "true" if cb.currentData() else "false")
    cb.style().unpolish(cb); cb.style().polish(cb)


# As classes `_Ponto`, `_Barra` e o `_divisor()` viraram peças PINTADAS em `chamado_pecas.py`.
# Existiam DUAS `_Ponto` (uma aqui, outra no detalhe) e elas divergiram — por isso o mesmo bug do
# raio fracionário apareceu em dobro. Marca é uma só e mora num lugar só.


def _divisor(esmaece=False):
    """Divisória de 1px. `esmaece` = a do card, que some para a direita."""
    return Regua(T.TEXT_BRIGHT, 0.10, esmaece=esmaece)


class _CabecalhoClicavel(QLabel):
    """Nome da coluna que abre a visão EXPANDIDA dela. É a volta do layout antigo — vários cards
    lado a lado — sem desfazer o quadro: o quadro responde "como estamos?", a expansão responde
    "me mostra tudo desta fila"."""
    def __init__(self, texto, on_click):
        super().__init__(texto)
        self._on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Clique para abrir esta fila em tela cheia")

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._on_click:
            self._on_click(); e.accept(); return
        super().mousePressEvent(e)


class _ChamadoCard(QFrame):
    """Card do chamado. Altura LIVRE (§8: nunca setFixedHeight) e hover que muda só a borda."""
    def __init__(self, d, on_click, cor_grupo=None):
        super().__init__()
        self._d = d; self._on_click = on_click
        ch = api.parse_bloco_chamado(d.get("note"))
        sub = d.get("_sub") or {}
        ch = {**ch, **{k: v for k, v in sub.items() if v}}
        chave = clog.chave(ch.get("ticket") or "", d.get("folio"))
        ch = {**ch, **clog.campos(chave)}
        st = (ch.get("status") or "").strip()
        cor = _status_cor(st) if st else _STATUS_COR.get(d.get("status"), T.TEXT_MUTED)
        feito = _encerrado(st, d.get("status"))
        # DOIS EIXOS, e misturá-los quebra a leitura do board (§3.2 da revisão): a moldura
        # (borda + gradiente) é a cor da COLUNA e diz "onde eu estou"; a cor do STATUS fica só
        # no texto do canto e diz "em que etapa eu estou". Antes tudo usava a cor do status, e
        # a coluna azul aparecia com dois cards de borda verde e um neutro.
        grupo = cor_grupo or cor

        self.setObjectName("card")
        self.setProperty("group", _TOM.get(grupo, "blue"))
        self.setProperty("done", "true" if feito else "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(230)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        # ANATOMIA 1B (28/07), a mesma da Performance: TRILHO de 3px na borda esquerda com a cor
        # do grupo, no lugar do gradiente do topo — com o trilho, o degradê era um segundo sinal
        # para a mesma informação. É border-left e não widget: widget de 3px não acompanha o raio.
        self.setStyleSheet("QFrame#card{background:%s;border-left:3px solid %s;}"
                           % (T.CARD_MUTED if feito else T.CARD,
                              T.rgba(grupo, 0.55) if feito else grupo))

        v = QVBoxLayout(self)
        v.setContentsMargins(*T.CARD_MARGINS); v.setSpacing(T.CARD_SPACING)

        # ── linha 1: OS · pai · status ──
        l1 = QHBoxLayout(); l1.setSpacing(7)
        num = QLabel(str(d.get("folio") or d.get("id") or "?"))
        num.setObjectName("osNumber")
        # o tracking é o que dá caráter ao número — e QSS não tem letter-spacing
        CF.aplicar(num, 15, QFont.Weight.Bold, mono=True, tracking=-0.6)
        if feito:
            num.setStyleSheet(f"color:{T.TEXT_DIM};")
        l1.addWidget(num)
        # o "pai NNNN" é o único elástico da linha e ELIDE (regra 1B: um elástico por linha, o
        # resto fixo ou elidindo — QLabel comum empurra o vizinho para fora sem avisar).
        pai = (ch.get("os_pai") or "").strip()
        if pai:
            lp = RotuloElidido(f"pai {pai}"); lp.setObjectName("meta")
            l1.addWidget(lp, 1)
        else:
            l1.addStretch(1)
        ls = QLabel(_curto(st) or (d.get("status") or "—"))
        ls.setObjectName("status")
        ls.setProperty("tone", "green" if feito else _TOM.get(cor, "blue"))
        ls.setToolTip(st or "sem status de chamado — mostrando o estado da OS")
        l1.addWidget(ls)
        v.addLayout(l1)

        # ── corpo: ativo + (usina · dias) ── a régua interna saiu (terceiro traço em 90px)
        bl = QVBoxLayout(); bl.setSpacing(4)
        tit = _texto_flex(QLabel(d.get("ativo") or "—")); tit.setObjectName("cardTitle")
        if feito:
            tit.setStyleSheet(f"color:{T.TEXT_DIM};")
        bl.addWidget(tit)
        lin = QHBoxLayout(); lin.setSpacing(8)
        loc = RotuloElidido(d.get("usina") or "—"); loc.setObjectName("secondary")
        lin.addWidget(loc, 1)                     # ÚNICO elástico da linha
        dias = clog.dias_sem_atualizacao(chave) if chave else None
        if dias is None:
            lt = QLabel("sem histórico"); lt.setObjectName("meta")
        else:
            # "hoje" é notícia BOA e o card tem que dizer isso — antes saía no mesmo cinza de
            # "8 dias", que é justamente o oposto (§3.3 da revisão).
            if feito:
                urg = T.TEXT_FAINT
            elif dias > 30:
                urg = T.RED_TEXT
            elif dias > 15:
                urg = T.AMBER_TEXT
            elif dias == 0:
                urg = T.GREEN
            else:
                urg = T.TEXT_FAINT
            # rótulo CURTO, como na Performance: "parado" era a palavra mais longa da linha e a
            # que menos informava — a cor do número já diz a gravidade.
            lt = QLabel("hoje" if dias == 0 else
                        ("1 dia" if dias == 1 else "%d dias" % dias))
            lt.setStyleSheet(f"color:{urg};font-family:'JetBrains Mono',Consolas,monospace;"
                             "font-size:10px;font-weight:700;background:transparent;")
        lin.addWidget(lt, 0)
        bl.addLayout(lin)
        v.addLayout(bl)

        # ── rodapé: só o fabricante, e só quando existe ──
        fab = (ch.get("fabricante") or "").strip()
        if fab:
            rod = QHBoxLayout(); rod.setSpacing(6)
            lf = QLabel(fab); lf.setObjectName("meta")      # virou texto: a pílula custava 20px
            rod.addWidget(lf); rod.addStretch(1)
            v.addLayout(rod)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._on_click:
            self._on_click(self._d)


class ChamadosTab(QWidget):
    def __init__(self, on_voltar=None):
        super().__init__()
        self._on_voltar = on_voltar
        self._parent = None                 # detalhe da OS pai buscada (aba Novo)
        self._wb = self._wc = self._wr = self._wl = self._ws = None
        self._itens = []          # chamados carregados (com o '_sub' das subtarefas)

        self._board_loaded = False
        self._listas = _load_listas()       # listas-padrão das subtarefas (base + adicionadas)
        self.setStyleSheet(_folha())
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        # A aba é SÓ o acompanhamento. Criar chamado saiu daqui: nasce do botão "Abrir chamado"
        # no card da OS (inclusive p/ OS antiga — é só achá-la no Histórico). Sem o segmentado,
        # a tela abre já no que interessa pra equipe de chamados.
        self._por_col = {}        # {coluna: [chamados]} — a expansão lê daqui
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_board())        # 0
        self.stack.addWidget(self._build_expandido())    # 1 — uma fila em grade
        self.stack.addWidget(self._build_lista())        # 2 — tabela no formato da planilha
        root.addWidget(self.stack, 1)
        self._board_loaded = False
        self._carregar_board()

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
        # `chPage` é quem carrega o fundo da página na folha nova. A regra `QWidget{background}`
        # saiu da folha justamente para QLabel parar de carimbar retângulo opaco.
        page = QWidget(); page.setObjectName("chPage")
        env = QVBoxLayout(page); env.setContentsMargins(14, 12, 14, 14)
        painel = QFrame(); painel.setObjectName("panel")
        painel.setProperty("flat", "true")   # tela cheia, sem moldura de cartão
        # SEM teto de largura: o board PREENCHE a tela. O 1280 do handout deixava faixa vazia
        # dos dois lados e, com 55 chamados numa coluna, o espaço desperdiçado incomodava mais
        # que a linha de leitura longa.
        env.addWidget(painel)
        outer = QVBoxLayout(painel)
        outer.setContentsMargins(T.PANEL_MARGINS[0], T.PANEL_MARGINS[1],
                                 T.PANEL_MARGINS[2], T.PANEL_MARGINS[3])
        outer.setSpacing(T.SECTION_SPACING)

        # ── header: título + resumo · Atualizar ──
        cab = QHBoxLayout(); cab.setSpacing(16)
        tw = QVBoxLayout(); tw.setSpacing(5)
        tit = QLabel("Chamados"); tit.setObjectName("panelTitle")
        self.board_hint = QLabel(""); self.board_hint.setObjectName("secondary")
        self.board_hint.setTextFormat(Qt.TextFormat.RichText)
        self.board_hint.setVisible(False)          # só aparece vazio/filtrado
        tw.addWidget(tit); tw.addWidget(self.board_hint)
        cab.addLayout(tw)

        # RESUMO EM NÚMEROS — mesmo tratamento da Alocação de análises (1B): três células mono
        # lidas de canto de olho, no lugar de uma frase com números coloridos no meio.
        kp = QHBoxLayout(); kp.setSpacing(24)
        self.nums = {}
        for chave_, rot in (("nosso", "a abrir"),
                            ("fab", "na mão do fabricante"),
                            ("parados", "parados há mais de 15 dias")):
            bx = QVBoxLayout(); bx.setSpacing(1)
            val = QLabel("—"); val.setObjectName("osNumber")
            CF.aplicar(val, 18, QFont.Weight.Bold, mono=True, tracking=-1.0)
            rl = QLabel(rot); rl.setObjectName("meta")
            bx.addWidget(val); bx.addWidget(rl)
            self.nums[chave_] = val
            kp.addLayout(bx)
        cab.addLayout(kp)
        cab.addStretch(1)

        # LISTA: a visão que a equipe já tinha na planilha. O quadro responde "como estamos?";
        # a lista responde "cadê o chamado X" e deixa varrer 500 linhas de uma vez — que é o que
        # a planilha fazia bem e o quadro não faz.
        self.b_lista = QPushButton("Lista"); self.b_lista.setCheckable(True)
        self.b_lista.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_lista.setToolTip("Ver como tabela, no formato da planilha de chamados")
        self.b_lista.toggled.connect(self._ver_lista)
        cab.addWidget(self.b_lista)
        self.b_reload = QPushButton("Atualizar"); self.b_reload.setObjectName("primary")
        self.b_reload.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_reload.clicked.connect(lambda: self._carregar_board(force=True))
        cab.addWidget(self.b_reload)
        outer.addLayout(cab)

        # ── filtros ──
        # Filtro é CROMO, não conteúdo: discreto parado, aceso filtrando (§3.4 da revisão).
        # Antes eram dois blocos de 190x40 escritos "todos" — os segundos maiores da tela, sem
        # informar nada no estado padrão. O rótulo mudou para DENTRO do campo, que assim se
        # explica sozinho e encolhe.
        fbl = QHBoxLayout(); fbl.setSpacing(9)
        self.cb_fabf = Combo(); self.cb_fabf.setObjectName("filtro")
        # o prefixo fica SÓ no item padrão: repetido em cada opção da lista vira ruído
        # ("Fabricante: Huawei", "Fabricante: Soltec"…). Escolhido, o nome fala por si e a
        # borda verde já diz que há filtro ativo.
        self.cb_fabf.addItem("Fabricante: todos", None)
        for f in cspec.TODOS_FABRICANTES:
            self.cb_fabf.addItem(f, f)
        self.cb_espf = Combo(); self.cb_espf.setObjectName("filtro")
        self.cb_espf.addItem("Aguardando: todos", None)
        for e in cspec.ESPERANDO:
            self.cb_espf.addItem(e, e)
        for cb in (self.cb_fabf, self.cb_espf):
            cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
            cb.currentIndexChanged.connect(lambda *_: self._filtrou())
            _pintar_filtro(cb)
            fbl.addWidget(cb)
        # PROCESSO ATUAL × ANTERIOR (28/07). O que separa os dois é a OS PAI: o chamado aberto
        # pelo "Abrir chamado" no card do inversor nasce amarrado à OS que o originou; o do modelo
        # antigo (etiqueta numa OS solta) não tem pai. Misturar os dois fazia o quadro do processo
        # novo parecer parado, porque o legado é a maioria e domina as colunas.
        # Alternador, não filtro escondido: os dois contadores ficam à vista e o legado está a um
        # clique — some da conta, nunca da vista.
        self._proc = "atual"
        self.b_atual = QPushButton("Processo atual"); self.b_atual.setObjectName("pill")
        self.b_ant = QPushButton("Processo anterior"); self.b_ant.setObjectName("pill")
        for b, chave_ in ((self.b_atual, "atual"), (self.b_ant, "anterior")):
            b.setCheckable(True); b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, k=chave_: self._set_processo(k))
        self.b_atual.setChecked(True)
        self.b_atual.setToolTip("Chamados abertos pelo botão “Abrir chamado” do card da OS")
        self.b_ant.setToolTip("Chamados do modelo antigo — etiqueta numa OS, sem OS pai")
        fbl.addSpacing(6); fbl.addWidget(self.b_atual); fbl.addWidget(self.b_ant)
        fbl.addStretch(1)
        outer.addLayout(fbl)

        # ── board: três colunas ──
        rolo = QScrollArea(); rolo.setWidgetResizable(True)
        rolo.setFrameShape(QScrollArea.Shape.NoFrame)
        rolo.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rolo.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        rolo.viewport().setStyleSheet("background:transparent;")
        host = QWidget(); host.setStyleSheet("background:transparent;"); rolo.setWidget(host)
        cols = QHBoxLayout(host)
        # goteira à direita: sem ela a barra de rolagem senta EM CIMA do contador da 3ª coluna
        # (o "54" saiu cortado no print do Levi).
        cols.setContentsMargins(0, 0, _SCROLL_GUTTER, 0)
        cols.setSpacing(T.BOARD_SPACING); cols.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._colunas = {}
        for nome, cor in T.GROUPS:
            # O VÉU SAIU (1B, 28/07): a cor do grupo já está no ponto, no nome e no trilho do
            # card. Uma quarta superfície tingida era repetição — a regra do 1B é que a única
            # cor grande da tela seja a que carrega informação, e ela já aparece três vezes.
            box = QWidget()
            bv = QVBoxLayout(box); bv.setContentsMargins(0, 0, 0, 0)
            bv.setSpacing(T.COLUMN_SPACING)
            # cabeçalho CENTRALIZADO (pedido do Levi, 27/07) — molas dos dois lados. O Ponto cresce
            # BLEED de cada lado p/ caber o halo; o espaçamento desconta o sangramento.
            ch = QHBoxLayout(); ch.setSpacing(9 - Ponto.BLEED)
            # padding simétrico + vão zero até a régua = nome no meio EXATO da faixa de cor
            # (mesma correção da Alocação; lá o nome saía 8px acima do centro).
            ch.setContentsMargins(4, 11, 4, 11)
            ch.addStretch(1)
            ch.addWidget(Ponto(cor, T.DOT["idle"]))
            rot = _CabecalhoClicavel(nome, lambda n=nome: self._expandir(n))
            rot.setObjectName("colHeader")
            rot.setStyleSheet(f"color:{cor};")
            CF.aplicar(rot, T.TYPE["col_header"]["size"], QFont.Weight.Bold,
                       tracking=T.TYPE["col_header"]["tracking"])
            # contador DISCRETO ao lado do nome (1B): com fila comprida, "quantas" deixou de ser
            # óbvio de bater o olho.
            cnt = QLabel("00"); cnt.setObjectName("counter")
            CF.aplicar(cnt, 10, QFont.Weight.Bold, mono=True)
            cnt.setStyleSheet("color:%s;" % T.TEXT_FAINT)
            ch.addWidget(rot); ch.addWidget(cnt); ch.addStretch(1)
            # cabeçalho e régua num bloco de espaçamento ZERO — senão o COLUMN_SPACING entra
            # entre os dois e o nome deixa de estar no meio da faixa (medido: 6px acima).
            topo = QWidget()
            tv = QVBoxLayout(topo); tv.setContentsMargins(0, 0, 0, 0); tv.setSpacing(0)
            tv.addLayout(ch)
            # régua esmaecida nas DUAS pontas (1B): a borda dura de uma régua de 1px chamava mais
            # atenção que a régua. Aqui ela fica na cor do grupo — diferente da Performance, onde
            # virou neutra porque a inicial já dizia de quem era a coluna; aqui a cor É o dado.
            tv.addWidget(Regua(cor, 0.30, esmaece="ambos"))
            bv.addWidget(topo)
            lista = QVBoxLayout(); lista.setSpacing(T.COLUMN_SPACING)
            bv.addLayout(lista); bv.addStretch(1)
            cols.addWidget(box, 1)
            self._colunas[nome] = {"lista": lista, "cont": cnt}
        outer.addWidget(rolo, 1)
        return page

    # ══════════════════════ visão EXPANDIDA de uma coluna ══════════════════════
    def _build_expandido(self):
        """Uma fila só, em grade — vários cards lado a lado, ocupando a tela. É o layout antigo
        de volta, mas sob demanda: o quadro continua sendo a porta de entrada."""
        page = QWidget(); page.setObjectName("chPage")
        env = QVBoxLayout(page); env.setContentsMargins(14, 12, 14, 14)
        painel = QFrame(); painel.setObjectName("panel"); painel.setProperty("flat", "true")
        env.addWidget(painel)
        out = QVBoxLayout(painel)
        out.setContentsMargins(T.PANEL_MARGINS[0], T.PANEL_MARGINS[1],
                               T.PANEL_MARGINS[2], T.PANEL_MARGINS[3])
        out.setSpacing(T.SECTION_SPACING)
        cab = QHBoxLayout(); cab.setSpacing(12)
        b_volta = QPushButton("← Quadro")
        b_volta.setCursor(Qt.CursorShape.PointingHandCursor)
        b_volta.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        cab.addWidget(b_volta)
        self.exp_tit = QLabel("—"); self.exp_tit.setObjectName("panelTitle")
        cab.addWidget(self.exp_tit)
        self.exp_sub = QLabel(""); self.exp_sub.setObjectName("secondary")
        cab.addWidget(self.exp_sub); cab.addStretch(1)
        out.addLayout(cab)
        out.addWidget(Regua(T.TEXT_BRIGHT, 0.10))
        rolo = QScrollArea(); rolo.setWidgetResizable(True)
        rolo.setFrameShape(QScrollArea.Shape.NoFrame)
        rolo.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rolo.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        rolo.viewport().setStyleSheet("background:transparent;")
        host = QWidget(); rolo.setWidget(host)
        hv = QVBoxLayout(host); hv.setContentsMargins(0, 0, _SCROLL_GUTTER, 0)
        self.exp_grade = QGridLayout(); self.exp_grade.setSpacing(T.COLUMN_SPACING)
        hv.addLayout(self.exp_grade); hv.addStretch(1)   # sem isto os cards dividem a altura
        out.addWidget(rolo, 1)
        return page

    @slot_seguro
    def _expandir(self, nome):
        dados = self._por_col.get(nome, [])
        self.exp_tit.setText(nome.title())
        self.exp_sub.setText("%d chamado(s)" % len(dados))
        while self.exp_grade.count():
            it = self.exp_grade.takeAt(0); w = it.widget()
            if w:
                w.setParent(None); w.deleteLater()
        # nº de colunas pela largura real: card legível a partir de ~380px
        n = max(2, (self.width() - 60) // 380)
        cg = _cor_grupo(nome)
        for i, d in enumerate(dados):
            self.exp_grade.addWidget(_ChamadoCard(d, self._abrir_os, cg), i // n, i % n)
        for c in range(n):
            self.exp_grade.setColumnStretch(c, 1)
        if not dados:
            self.exp_grade.addWidget(QLabel("nada aqui"), 0, 0)
        self.stack.setCurrentIndex(1)

    # ══════════════════════ visão LISTA (formato da planilha) ══════════════════════
    COLS_LISTA = ["OS", "Ticket/RMA", "Fabricante", "Ativo", "Usina", "Situação",
                  "Esperando", "Dias", "Última atualização"]

    def _build_lista(self):
        page = QWidget(); page.setObjectName("chPage")
        env = QVBoxLayout(page); env.setContentsMargins(14, 12, 14, 14)
        painel = QFrame(); painel.setObjectName("panel"); painel.setProperty("flat", "true")
        env.addWidget(painel)
        out = QVBoxLayout(painel)
        out.setContentsMargins(T.PANEL_MARGINS[0], T.PANEL_MARGINS[1],
                               T.PANEL_MARGINS[2], T.PANEL_MARGINS[3])
        out.setSpacing(T.SECTION_SPACING)
        cab = QHBoxLayout(); cab.setSpacing(12)
        b_volta = QPushButton("← Quadro")
        b_volta.setCursor(Qt.CursorShape.PointingHandCursor)
        b_volta.clicked.connect(lambda: self.b_lista.setChecked(False))
        cab.addWidget(b_volta)
        t = QLabel("Chamados — lista"); t.setObjectName("panelTitle")
        cab.addWidget(t)
        self.lista_hint = QLabel(""); self.lista_hint.setObjectName("secondary")
        cab.addWidget(self.lista_hint); cab.addStretch(1)
        self.busca_lista = QLineEdit()
        self.busca_lista.setPlaceholderText("buscar por OS, ticket, ativo ou usina…")
        self.busca_lista.setFixedWidth(300)
        self.busca_lista.textChanged.connect(self._encher_lista)
        cab.addWidget(self.busca_lista)
        out.addLayout(cab)
        self.tbl_lista = QTableWidget(0, len(self.COLS_LISTA))
        self.tbl_lista.setHorizontalHeaderLabels(self.COLS_LISTA)
        self.tbl_lista.verticalHeader().setVisible(False)
        self.tbl_lista.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_lista.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_lista.setAlternatingRowColors(False)
        self.tbl_lista.setSortingEnabled(True)
        hh = self.tbl_lista.horizontalHeader()
        for i in range(len(self.COLS_LISTA)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)      # Ativo estica
        self.tbl_lista.cellDoubleClicked.connect(self._abrir_da_lista)
        out.addWidget(self.tbl_lista, 1)
        return page

    @slot_seguro
    def _set_processo(self, chave):
        """Alterna entre o processo novo e o legado. Os dois botões são exclusivos entre si —
        `setCheckable` sozinho não faz isso, e sem o par explícito dava para desmarcar os dois."""
        self._proc = chave
        self.b_atual.setChecked(chave == "atual")
        self.b_ant.setChecked(chave == "anterior")
        self._render_board()

    @slot_seguro
    def _ver_lista(self, on):
        if on:
            self._encher_lista()
            self.stack.setCurrentIndex(2)
        else:
            self.stack.setCurrentIndex(0)

    def _encher_lista(self, *_):
        alvo = (self.busca_lista.text() or "").strip().lower()
        t = self.tbl_lista
        t.setSortingEnabled(False)          # ordenar durante o preenchimento embaralha as linhas
        t.setRowCount(0)
        self._linhas_lista = []
        for d in self._itens:
            campos = [str(d.get("folio") or ""), self._campo_do(d, "ticket"),
                      self._campo_do(d, "fabricante"), d.get("ativo") or "",
                      d.get("usina") or "", self._status_do(d) or (d.get("status") or ""),
                      self._campo_do(d, "esperando"),
                      ("%d" % self._dias_do(d)) if self._dias_do(d) is not None else "",
                      (d.get("data_fim") or d.get("event_date") or "")[:10]]
            if alvo and alvo not in " ".join(campos).lower():
                continue
            r = t.rowCount(); t.insertRow(r)
            for c, v in enumerate(campos):
                it = QTableWidgetItem(v)
                if c == 5:
                    it.setForeground(QBrush(QColor(_status_cor(v))))
                t.setItem(r, c, it)
            self._linhas_lista.append(d)
        t.setSortingEnabled(True)
        self.lista_hint.setText("%d de %d" % (t.rowCount(), len(self._itens)))

    @slot_seguro
    def _abrir_da_lista(self, linha, _col):
        it = self.tbl_lista.item(linha, 0)
        folio = it.text() if it else ""
        d = next((x for x in self._itens if str(x.get("folio")) == folio), None)
        if d:
            self._abrir_os(d)

    # ══════════════════════ carga inicial ══════════════════════
    def carregar_inicial(self):
        """A aba só tem o acompanhamento — carrega o painel. (O formulário de criação saiu daqui:
        chamado nasce do botão 'Abrir chamado' no card da OS.)"""
        if not self._board_loaded:
            self._carregar_board()

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
        """1ª etapa: chegou a lista. Renderiza já (o usuário vê a tela) e sai buscando as
        subtarefas — é delas que vem o status VIVO do chamado."""
        self._wl = None; self.b_reload.setEnabled(True)
        self._itens = itens if isinstance(itens, list) else []
        self._render_board()
        ids = [d.get("id") for d in self._itens if d.get("id")]
        if ids:
            self.board_hint.setText(self.board_hint.text() + " · lendo o status dos chamados…")
            self._ws = ApiWorker(api.status_chamado_em_massa, ids)
            self._ws.ok.connect(self._subs_ok); self._ws.erro.connect(lambda *_: self._subs_ok({}))
            self._ws.start()

    @slot_seguro
    def _subs_ok(self, mapa):
        """2ª etapa: status vindo das subtarefas (o que a equipe edita no Fracttal)."""
        self._ws = None
        mapa = mapa if isinstance(mapa, dict) else {}
        for d in self._itens:
            d["_sub"] = mapa.get(d.get("id")) or {}
        self._render_board()

    def _status_do(self, d):
        return self._campo_do(d, "status")

    @staticmethod
    def _campo_do(d, k):
        """Valor do campo: subtarefa (vivo) vence o bloco da observação (congelado na criação)."""
        sub = d.get("_sub") or {}
        v = (sub.get(k) or "").strip()
        if v:
            return v
        return (api.parse_bloco_chamado(d.get("note")).get(k) or "").strip()

    def _dias_do(self, d):
        """Dias sem atualização — a régua da cobrança, vinda do histórico do chamado."""
        ch = clog.chave(self._campo_do(d, "ticket"), d.get("folio"))
        return clog.dias_sem_atualizacao(ch) if ch else None

    def _filtrou(self):
        """Mudou um filtro: acende/apaga a borda dos dois e redesenha."""
        for cb in (self.cb_fabf, self.cb_espf):
            _pintar_filtro(cb)
        self._render_board()

    def _render_board(self):
        """Distribui os chamados nas TRÊS colunas (quem tem a bola) e ordena cada uma por
        tempo parado — o que está encalhado há mais tempo sobe."""
        for c in self._colunas.values():
            lst = c["lista"]
            while lst.count():
                it = lst.takeAt(0); w = it.widget()
                if w:
                    w.deleteLater()
        itens = list(getattr(self, "_itens", []))
        # PROCESSO: separa antes de tudo, e os dois botões mostram quantos há de cada lado (nada
        # some sem aviso). Quem tem OS pai nasceu do "Abrir chamado"; o resto é o modelo antigo.
        atual = [d for d in itens if (self._campo_do(d, "os_pai") or "").strip()]
        anterior = [d for d in itens if not (self._campo_do(d, "os_pai") or "").strip()]
        if hasattr(self, "b_atual"):
            self.b_atual.setText("Processo atual  %d" % len(atual))
            self.b_ant.setText("Processo anterior  %d" % len(anterior))
        itens = atual if getattr(self, "_proc", "atual") == "atual" else anterior
        tot = len(itens)
        fab = self.cb_fabf.currentData() if hasattr(self, "cb_fabf") else None
        if fab:
            itens = [d for d in itens if self._campo_do(d, "fabricante") == fab]
        esp = self.cb_espf.currentData() if hasattr(self, "cb_espf") else None
        if esp:
            itens = [d for d in itens if self._campo_do(d, "esperando") == esp]
        if hasattr(self, "chk_fim") and not self.chk_fim.isChecked():
            itens = [d for d in itens if not _encerrado(self._status_do(d), d.get("status"))]

        def _dias(d):
            v = self._dias_do(d)
            if v is None:
                h, _ = api.duracao_solar(d.get("event_date"), d.get("data_fim"))
                v = (h or 0) / 12.0
            return v
        def _ordem_fim(d):
            """Dentro de EM ANDAMENTO: Em Verificação ANTES de Concluída (pedido do Levi, 27/07).
            Em Verificação ainda pede alguém — é trabalho; concluída é arquivo. Deixar a concluída
            em cima empurrava para baixo justamente o que ainda precisa de atenção."""
            if not _encerrado(self._status_do(d), d.get("status")):
                return 0
            so = (d.get("status") or "").lower()
            return 1 if "verific" in so else 2
        itens.sort(key=lambda d: (_ordem_fim(d), -_dias(d)))

        por_col = {nome: [] for nome, _ in COLUNAS}
        for d in itens:
            por_col[_coluna_de(self._status_do(d), self._campo_do(d, "esperando"),
                               d.get("status"))].append(d)
        self._por_col = por_col               # a visão expandida lê daqui
        for nome, dados in por_col.items():
            c = self._colunas[nome]
            c["cont"].setText("%02d" % len(dados))
            cg = _cor_grupo(nome)                 # a moldura do card é a cor da COLUNA
            for d in dados:
                c["lista"].addWidget(_ChamadoCard(d, self._abrir_os, cg))
            if not dados:
                vz = QLabel("nada aqui"); vz.setObjectName("empty")
                c["lista"].addWidget(vz)
        # resumo do cabeçalho, no lugar dos antigos cartões de KPI
        n_nosso = len(por_col["AÇÃO NOSSA"]); n_fab = len(por_col["COM O FABRICANTE"])
        parados = sum(1 for d in itens
                      if not _encerrado(self._status_do(d), d.get("status")) and (self._dias_do(d) or 0) > 15)
        for chave_, valor, cor_ in (("nosso", n_nosso, T.RED_TEXT),
                                    ("fab", n_fab, T.AMBER_TEXT),
                                    ("parados", parados, T.AMBER_TEXT)):
            lb = self.nums[chave_]
            lb.setText("%02d" % valor)
            # zero não merece cor de alarme: cinza para a cor só aparecer quando há o que ver
            lb.setStyleSheet("color:%s;" % (cor_ if valor else T.TEXT_FAINT))
        # a linha de texto só sobra para o que os números não dizem: nada no período, ou filtro ativo
        recado = ""
        if not itens:
            recado = ("nenhum chamado aberto pelo “Abrir chamado” ainda"
                      if getattr(self, "_proc", "atual") == "atual"
                      else "nenhum chamado do modelo antigo no período")
        elif len(itens) != tot:
            recado = "mostrando %d de %d (filtro ativo)" % (len(itens), tot)
        self.board_hint.setText(recado)
        self.board_hint.setVisible(bool(recado))

    def _abrir_os(self, d):
        """Clique no card → tela do CHAMADO (com a linha do tempo), não direto a OS. A OS fica
        a um botão de distância lá dentro."""
        from steps.chamado_detalhe import abrir_chamado_detalhe
        if abrir_chamado_detalhe(self, d):
            self._render_board()          # mudou status/histórico → o card reflete na hora

    # A importação do histórico da planilha saiu da tela (o botão poluía a barra de filtros).
    # A capacidade continua em `chamado_log.importar` / `chamado_log.ler_planilha` — é uma carga
    # única, feita fora da rotina da equipe.

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
        """Abre o MESMO formulário por fabricante do card da OS. O caminho normal é o supervisor
        clicar em "Abrir chamado" no card; esta aba fica para o RETROATIVO — abrir chamado de uma
        OS antiga, que a Singrid disse que faria na mão (reunião 23/07)."""
        if not isinstance(self._parent, dict):
            QMessageBox.information(self, "Chamado", "Busque a OS antes de criar o chamado."); return
        from steps.abrir_chamado import abrir_chamado
        d = self._parent
        novo = abrir_chamado(self, {"folio": d.get("folio") or self.ed_os.text().strip(),
                                    "ativo": d.get("ativo") or "", "usina": d.get("usina") or "",
                                    "id_work_order": d.get("id_work_order"),
                                    "event_date": d.get("event_date")})
        if novo:
            self._carregar_board(force=True)      # o novo chamado já aparece no painel
        return

    @slot_seguro
    def _criar_antigo(self, *_):
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
