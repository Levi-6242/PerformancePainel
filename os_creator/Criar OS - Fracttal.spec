# -*- mode: python ; coding: utf-8 -*-
# Build em PASTA (--onedir) — necessário p/ o navegador embutido (login Microsoft/SSO via QtWebEngine).
# Onefile re-extrai ~200MB a cada abertura (boot lento); onedir já fica descompactado.

import os
# O pacote `chamado_garantia` mora na RAIZ do repositório, não em os_creator/ — é compartilhado com
# o app de campo. O `chamado_insp_spec` chega nele por sys.path EM TEMPO DE EXECUÇÃO, e a análise
# estática do PyInstaller não segue isso: o .exe da v131 à v133 abria a "Inspeção de chamados" e
# morria com ModuleNotFoundError, sem nada na tela (o slot_seguro engole). Rodando como script
# funciona, então só aparece no build. pathex ensina o caminho; hiddenimports garante os módulos.
_RAIZ = os.path.dirname(os.path.abspath(SPECPATH))          # noqa: F821 (SPECPATH é do PyInstaller)

a = Analysis(
    ['main.py'],
    pathex=[_RAIZ],
    binaries=[],
    datas=[('assets', 'assets'), ('assets_cache.json', '.')],
    # O kanban de Performance é importado DENTRO de funções (import tardio, para não pesar a
    # abertura da aba). O PyInstaller normalmente acha isso, mas depois do sumiço da folha de
    # estilo na v92 estes ficam cravados — custa nada e fecha a porta.
    hiddenimports=['PyQt6.QtWebEngineWidgets', 'PyQt6.QtWebEngineCore',
                   'steps.perf_kanban', 'steps.perf_nova', 'perf_spec', 'perf_equipe', 'perf_notas',
                   'chamado_pecas', 'chamado_fontes', 'chamado_tokens',
                   'chamado_garantia', 'chamado_garantia.regras', 'chamado_garantia.spec'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['keyring'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,          # onedir: binários/dados vão no COLLECT, não no exe
    name='Criar OS - Fracttal',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                      # UPX pode corromper as DLLs grandes do WebEngine
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\grid-icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Criar OS - Fracttal',
)
