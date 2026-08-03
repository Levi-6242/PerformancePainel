"""Tokens do design 'Chamados 1B'. Não redigite valores — importe daqui."""

# --- fundo e superfície -------------------------------------------------
BG            = "#07090F"
SURFACE       = "#0C111C"
SURFACE_TOP   = "#111624"
CARD          = "#131928"
CARD_MUTED    = "#111726"
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
DOT_IDLE    = "#3B435C"

# --- semáforo ------------------------------------------------------------
RED    = "#F5766B";  RED_TEXT   = "#F79B92"
AMBER  = "#F5A623";  AMBER_TEXT = "#F5C46A"
BLUE   = "#4A9EF5";  BLUE_TEXT  = "#8AC0FA"
GREEN  = "#48D07A";  GREEN_TEXT = "#7FDCA2"
ACCENT = "#A6E22E";  ACCENT_HOVER = "#C4F154"
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
RADIUS_PANEL, RADIUS_CARD, RADIUS_CONTROL, RADIUS_PILL = 16, 14, 9, 999
PANEL_MARGINS   = (24, 22, 24, 26)   # l, t, r, b
CARD_MARGINS    = (16, 16, 16, 14)
CARD_SPACING    = 11
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
            f"stop:0 {rgba(group_color, 0.11)}, "
            f"stop:0.46 {CARD}, stop:1 {CARD})")
