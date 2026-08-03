"""Tokens do design 'Chamados 1B' — REVISÃO 1B da Alocação de análises (28/07/2026).

O que mudou nesta revisão (e só isto): o semáforo, o acento, as duas superfícies de card,
o raio e as margens do card, e o alpha do gradiente. Fundo, texto e tipografia estão intactos.
Motivo: os quatro hexes do semáforo tinham luminosidade percebida diferente (o âmbar saltava,
o cinza da rotina afundava) e croma alto demais para uma cor que é INFORMAÇÃO. Agora os quatro
estão na mesma luminosidade e com croma baixo — continuam distinguíveis entre si e fora da
paleta de identificação de pessoa.


Cópia fiel de  (spec normativa).
Se o design mudar, troque o arquivo do handoff e recopie — não edite os valores aqui.
"""

# --- fundo e superfície -------------------------------------------------
BG            = "#07090F"
SURFACE       = "#0C111C"
SURFACE_TOP   = "#111624"
CARD          = "#121927"
CARD_MUTED    = "#0E1320"
BORDER        = "rgba(255,255,255,0.07)"
BORDER_STRONG = "rgba(255,255,255,0.12)"
DIVIDER       = "rgba(255,255,255,0.10)"
HOVER_WASH    = "rgba(255,255,255,0.035)"

# --- texto ---------------------------------------------------------------
TEXT        = "#E7EAF2"
TEXT_BRIGHT = "#FFFFFF"
TEXT_DIM    = "#C9CFDE"
TEXT_MUTED  = "#7A85A0"
TEXT_FAINT  = "#5B6479"
TEXT_LABEL  = "#4E576D"
TEXT_CHIP   = "#96A0B8"
DOT_IDLE    = "#454E68"   # subiu um passo: a rotina existia de menos no card

# --- semáforo ------------------------------------------------------------
RED    = "#E4635B";  RED_TEXT   = "#EE968F"
AMBER  = "#D89A3F";  AMBER_TEXT = "#E6BE7E"
BLUE   = "#5A93DC";  BLUE_TEXT  = "#97BCEB"
GREEN  = "#46B87C";  GREEN_TEXT = "#82CFA4"
ACCENT = "#A3CF3C";  ACCENT_HOVER = "#B9E05B"
ON_ACCENT = "#0B1020"   # texto sobre fundo verde (só no toggle ativo)

# grupos do board: (rótulo, cor)
GROUPS = [
    ("AÇÃO NOSSA",       RED),
    ("COM O FABRICANTE", AMBER),
    ("EM ANDAMENTO",     BLUE),
]

# --- tipografia (px) -----------------------------------------------------
FONT_UI   = "Inter"          # fallback: Segoe UI
FONT_MONO = "JetBrains Mono" # fallback: Consolas

TYPE = {
    "os_card":      dict(family=FONT_MONO, size=19,   weight=700, tracking=-1.1),
    "os_detail":    dict(family=FONT_MONO, size=24,   weight=700, tracking=-1.3),
    "panel_title":  dict(family=FONT_UI,   size=20,   weight=500, tracking=-0.3),
    "card_title":   dict(family=FONT_UI,   size=13.5, weight=600, tracking=0),
    "detail_title": dict(family=FONT_UI,   size=15,   weight=600, tracking=0),
    "secondary":    dict(family=FONT_UI,   size=11.5, weight=400, tracking=0),
    "status":       dict(family=FONT_UI,   size=11,   weight=600, tracking=0),
    "col_header":   dict(family=FONT_UI,   size=11.5, weight=700, tracking=0.9, upper=True),
    "section":      dict(family=FONT_UI,   size=10.5, weight=600, tracking=1.0, upper=True),
    "chip":         dict(family=FONT_UI,   size=10.5, weight=600, tracking=0),
    "meta":         dict(family=FONT_UI,   size=10.5, weight=400, tracking=0),
    "date":         dict(family=FONT_MONO, size=12,   weight=700, tracking=0),
    "year":         dict(family=FONT_UI,   size=10,   weight=400, tracking=0),
    "body":         dict(family=FONT_UI,   size=12.5, weight=400, line_height=1.55),
    "button":       dict(family=FONT_UI,   size=12.5, weight=600, tracking=0),
}

# --- forma e espaço (px) -------------------------------------------------
RADIUS_PANEL, RADIUS_CARD, RADIUS_CONTROL, RADIUS_PILL = 16, 12, 9, 999
PANEL_MARGINS   = (24, 22, 24, 26)   # l, t, r, b
CARD_MARGINS    = (13, 12, 13, 11)   # 1B: card mais apertado; o trilho ocupa 3px à esquerda
CARD_SPACING    = 9
COLUMN_SPACING  = 12                 # entre cards
BOARD_SPACING   = 16                 # entre colunas
SECTION_SPACING = 20
BOARD_MAX_WIDTH = 1280
DETAIL_SIDEBAR  = 300
TIMELINE_GUTTER = 52
DOT             = dict(recent=9, status=8, idle=7)
TIME_BAR        = (26, 3)

def rgba(hex_color: str, alpha: float) -> str:
    """'#F5A623', .11 -> 'rgba(245,166,35,0.11)'"""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"

def card_gradient(group_color: str) -> str:
    """Gradiente do topo do card, na cor do grupo."""
    return (f"qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            f"stop:0 {rgba(group_color, 0.085)}, "
            f"stop:0.46 {CARD}, stop:1 {CARD})")
