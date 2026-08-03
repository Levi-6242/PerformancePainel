"""Trava de release do design "Chamados 1B": recusa o build quando o pacote visual não está inteiro.

Checa DUAS coisas, e as duas já quebraram na prática:

1. **A folha `assets/chamados.qss`.** A v92 saiu sem ela: o arquivo morava solto em
   `os_creator/chamados.qss` e o `.spec` só empacota `assets` e o `assets_cache.json`, então
   ela não entrou no `.exe`. Do código-fonte a tela abria certa; no app instalado o
   `_folha()` caía calado no tema antigo e o redesign inteiro sumia. Hoje ela vive dentro de
   `assets/` — mas esta checagem existe para o caso de alguém mover de novo.

2. **As fontes Inter e JetBrains Mono.** Sem a Inter não existe o peso 500 do título do painel
   nem o tracking negativo do número da OS — e é isso que segura a hierarquia do design. Com a
   Segoe UI a tela "funciona" e parece um dashboard qualquer, que foi o problema que este
   pacote de design veio corrigir.

Uso (código de saída 1 quando falta alguma coisa):

    python verificar_fontes.py

Para ligar no release, rode antes do build:

    python "…\\os_creator\\verificar_fontes.py" && python release.py <versao> <notas>
"""
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
_APP = None          # segura o QApplication vivo (ver main)


def _checar_folha():
    """→ (ok, mensagens). A folha tem de estar ONDE O BUILD ENXERGA (dentro de assets/).

    CUIDADO com a ordem: importar `steps.chamados` puxa `steps.ui`/`os_detalhe`, que constroem
    QPixmap/QFont no import. Sem um QApplication vivo o Qt ABORTA o processo — sem traceback,
    sem mensagem, só um código de saída estranho. Por isso `main()` cria o app antes de chamar
    esta função."""
    msgs = []
    sys.path.insert(0, _AQUI)
    sys.path.insert(0, os.path.join(_AQUI, "steps"))
    from steps.chamados import folha_caminho
    cam = folha_caminho()
    if not cam:
        msgs.append("FOLHA AUSENTE — não achei chamados.qss em lugar nenhum.")
        return False, msgs
    msgs.append("folha       : " + cam)
    dentro = os.path.abspath(cam).startswith(os.path.join(_AQUI, "assets") + os.sep)
    if not dentro:
        msgs.append("A folha está FORA de os_creator/assets/ — o .spec não vai empacotá-la e o "
                    "app instalado abre com o tema antigo (foi o bug da v92).")
        return False, msgs
    # o .spec precisa continuar levando a pasta assets inteira
    spec = os.path.join(_AQUI, "Criar OS - Fracttal.spec")
    if os.path.exists(spec):
        with open(spec, encoding="utf-8") as f:
            txt = f.read()
        if "('assets', 'assets')" not in txt and '("assets", "assets")' not in txt:
            msgs.append("O .spec não empacota mais a pasta 'assets' — a folha e as fontes "
                        "não vão entrar no build.")
            return False, msgs
    return True, msgs


def _checar_fontes():
    import chamado_fontes as CF
    r = CF.registrar()
    msgs = ["família UI  : " + r["ui"], "família mono: " + r["mono"]]
    if r["arquivos"]:
        msgs.append("registradas de assets/fonts: " + ", ".join(r["arquivos"]))
    return (not CF.falta_fonte()), msgs


def main():
    # PRIMEIRA coisa: sem QApplication, qualquer import que crie QPixmap/QFont derruba o
    # processo em silêncio. Também roda offscreen — a trava é de build, não abre janela.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    # `global` de propósito: sem manter a referência viva o QApplication é coletado logo depois
    # de criado e o Qt derruba o processo mais adiante — sem traceback, saindo com 127.
    global _APP
    _APP = QApplication.instance() or QApplication([])

    ok_folha, m1 = _checar_folha()
    ok_fontes, m2 = _checar_fontes()
    for m in m1 + m2:
        print(m)
    if ok_folha and ok_fontes:
        print()
        print("OK — folha e fontes do design 1B estão no lugar.")
        return 0
    print()
    print("RELEASE BLOQUEADO — o app sairia sem parte do design.")
    if not ok_fontes:
        print("  Inter          -> https://rsms.me/inter")
        print("  JetBrains Mono -> https://jetbrains.com/lp/mono")
        print("  Coloque os .ttf em os_creator/assets/fonts/ (as duas são OFL).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
