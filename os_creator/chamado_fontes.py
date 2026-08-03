"""Fontes do design 'Chamados 1B' — registro e `letter-spacing`.

DUAS COISAS QUE O QSS NÃO FAZ e por isso moram aqui:

1. **Registrar família.** Inter (UI) e JetBrains Mono (números) não vêm no Windows. Ambas são
   OFL, então podem ser embarcadas: baixe em rsms.me/inter e jetbrains.com/lp/mono e ponha os
   `.ttf` em `assets/fonts/`. `registrar()` varre a pasta e registra o que achar.
   Sem os arquivos o app cai em Segoe UI / Consolas — aceitável em desenvolvimento, mas o
   README do handoff é explícito: **não serve para release**, porque a Segoe UI não reproduz
   o peso 500 nem o tracking negativo do número da OS.

2. **letter-spacing.** Não existe em QSS. O −1.1 do número da OS no card e o −1.3 no detalhe
   só saem por `QFont.setLetterSpacing` — é o que dá o caráter do design.
"""
import os
import sys

from PyQt6.QtGui import QFont, QFontDatabase

PASTA = "assets/fonts"
UI_PREF, UI_FALL = "Inter", "Segoe UI"
MONO_PREF, MONO_FALL = "JetBrains Mono", "Consolas"

_estado = {"registrado": False, "familias": set()}


def _raiz():
    """Pasta do app — funciona no script e dentro do bundle do PyInstaller."""
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def registrar() -> dict:
    """Registra as .ttf de `assets/fonts/`. Idempotente. → {'ui','mono','arquivos'}."""
    if not _estado["registrado"]:
        _estado["registrado"] = True
        pasta = os.path.join(_raiz(), *PASTA.split("/"))
        if os.path.isdir(pasta):
            for nome in sorted(os.listdir(pasta)):
                if not nome.lower().endswith((".ttf", ".otf")):
                    continue
                fid = QFontDatabase.addApplicationFont(os.path.join(pasta, nome))
                if fid != -1:
                    _estado["familias"].update(QFontDatabase.applicationFontFamilies(fid))
    disp = set(QFontDatabase.families()) | _estado["familias"]
    return {"ui": UI_PREF if UI_PREF in disp else UI_FALL,
            "mono": MONO_PREF if MONO_PREF in disp else MONO_FALL,
            "arquivos": sorted(_estado["familias"])}


def familia(mono=False) -> str:
    r = registrar()
    return r["mono"] if mono else r["ui"]


def aplicar(widget, tamanho, peso=QFont.Weight.Normal, mono=False, tracking=0.0):
    """Fonte + tracking num QLabel/QWidget. `tracking` em px (negativo aperta).
    Usar SEMPRE que o design pedir letter-spacing — o QSS ignora a propriedade."""
    f = QFont(familia(mono=mono))
    f.setPixelSize(int(round(tamanho)))
    f.setWeight(peso)
    if tracking:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, tracking)
    widget.setFont(f)
    return widget


def falta_fonte() -> bool:
    """True quando está rodando nos fallbacks — para avisar no build/release."""
    r = registrar()
    return r["ui"] != UI_PREF or r["mono"] != MONO_PREF
