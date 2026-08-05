"""main.py — entry point do app desktop "Criar OS — Fracttal".

Multiusuário: cada pessoa entra com o PRÓPRIO e-mail/senha do Fracttal (rpc/login_new) e a OS
é criada no nome dela. O app NÃO carrega segredo da empresa — leituras de pessoal/etiquetas vêm
da sessão do usuário e os ativos de um catálogo (assets_cache.json) atualizado pelo admin.

Uso:
    pip install -r requirements.txt
    python main.py
"""
import os
import sys
import urllib.parse
from PyQt6.QtCore import Qt, QTranslator, QLibraryInfo, QLocale, QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
from PyQt6.QtGui import QIcon
import api
from app import MainWindow, DARK_QSS, LoginDialog, _asset
from steps.updater import checar_atualizacao
from steps.splash import mostrar_splash
from workers import registrar_erro


# ── Deep link gridos:// da Plataforma de Performance (Levi 15/07) ────────────────────────────────
# A plataforma manda "gridos://performance?usina=..&ativo=Inversor 1.1&obs=String X sem corrente&
# template=recomposicao". O Windows abre este app com a URL em argv[1]. Instância única: se o app já
# está aberto, o link cai na janela existente (sem re-login). Tudo best-effort: se qualquer peça falhar,
# o app abre NORMAL, sem instância única — nunca conflita com o funcionamento atual.
_GRIDOS_SRV = "GridcoOSCreator.v1"
_holder = {"win": None}


def _parse_gridos(argv):
    """Extrai a sugestão de um argumento gridos://performance?... → dict {usina,ativo,obs,template,_acao}
    ou None. Puro/testável (aceita espaço como '+' ou %20)."""
    uri = next((a for a in (argv or []) if str(a).lower().startswith("gridos:")), None)
    if not uri:
        return None
    try:
        p = urllib.parse.urlparse(uri)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(p.query, keep_blank_values=True).items()}
        q["_acao"] = (p.netloc or p.path.lstrip("/")).lower()
        q["_uri"] = uri
        return q
    except Exception:
        return None


def _registrar_protocolo():
    """Registra gridos:// em HKCU (sem admin, não toca HKLM). Idempotente + best-effort: qualquer falha é
    ignorada. Assim toda instalação passa a atender o deep link no próximo boot, sem reinstalar."""
    try:
        import winreg
        exe = sys.executable
        cmd = (f'"{exe}" "{os.path.abspath(__file__)}" "%1"'
               if os.path.basename(exe).lower().startswith("python")
               else f'"{exe}" "%1"')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\gridos") as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, "URL:Grid OS Creator")
            winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\gridos\shell\open\command") as k:
            try:
                atual, _ = winreg.QueryValueEx(k, None)
            except OSError:
                atual = None
            if atual != cmd:
                winreg.SetValueEx(k, None, 0, winreg.REG_SZ, cmd)
    except Exception:
        pass


def _dispatch_uri(uri):
    """Aplica um gridos:// (do próprio arg ou vindo de outra instância) → abre a sugestão no OS Creator."""
    dados = _parse_gridos([uri])
    win = _holder.get("win")
    if not (dados and win):
        return
    try:
        win.showNormal(); win.raise_(); win.activateWindow()
        if hasattr(win, "abrir_sugestao_performance"):
            win.abrir_sugestao_performance(dados)
    except Exception as ei:
        registrar_erro((type(ei), ei, ei.__traceback__))


def _single_instance(app, uri):
    """True = JÁ existe uma instância (mandamos o uri e o chamador sai). Senão, viramos a primária e
    passamos a escutar deep links. Best-effort: qualquer erro → segue como app normal (sem inst. única)."""
    try:
        from PyQt6.QtNetwork import QLocalServer, QLocalSocket
    except Exception:
        return False
    try:
        sock = QLocalSocket(); sock.connectToServer(_GRIDOS_SRV)
        if sock.waitForConnected(350):
            sock.write((uri or "gridos://focus").encode("utf-8")); sock.flush()
            sock.waitForBytesWritten(600); sock.disconnectFromServer()
            return True
        QLocalServer.removeServer(_GRIDOS_SRV)      # limpa socket órfão de um crash anterior
        srv = QLocalServer()
        if not srv.listen(_GRIDOS_SRV):
            return False

        def _on_conn():
            c = srv.nextPendingConnection()
            if c and c.waitForReadyRead(600):
                _dispatch_uri(bytes(c.readAll()).decode("utf-8", "ignore").strip())
            if c:
                c.disconnectFromServer()
        srv.newConnection.connect(_on_conn)
        app._gridos_srv = srv                       # segura a ref (senão o GC fecha o servidor)
        return False
    except Exception:
        return False


def main():
    # Rede de segurança: no PyQt6 uma exceção não tratada num slot ENCERRA o app. Aqui qualquer
    # exceção não capturada é gravada no log (%TEMP%\criaros_erros.log) em vez de fechar em silêncio.
    sys.excepthook = lambda *ei: registrar_erro(ei)
    # Necessário p/ o navegador embutido (login Microsoft/SSO) ser carregado sob demanda depois.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    _registrar_protocolo()
    uri = next((a for a in sys.argv[1:] if str(a).lower().startswith("gridos:")), None)
    if _single_instance(app, uri):
        sys.exit(0)            # o app já aberto vai tratar o link — não abre 2ª janela (nem re-login)
    # botões padrão do Qt (QMessageBox Yes/No, OK, Cancel…) em pt-BR → Sim/Não
    app._tr = QTranslator()
    if app._tr.load(QLocale("pt_BR"), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(app._tr)
    app.setApplicationName("Criar OS — Fracttal")
    app.setWindowIcon(QIcon(_asset("grid-icon.png")))   # ícone Grid Co (barra de tarefas)
    app.setStyleSheet(DARK_QSS)            # tema escuro app-wide (inclui dialogs)
    from steps.nowheel import instalar as _instalar_nowheel
    _instalar_nowheel(app)                 # roda do mouse não muda combos/datas sem querer
    # Splash: símbolo da Grid (grande) surge e some antes do app aparecer.
    mostrar_splash(app, _asset("grid-icon.png"))
    # Gate de login: sem JWT de sessão válido, pede e-mail + senha.
    if not api.is_logged_in():
        if LoginDialog().exec() != QDialog.DialogCode.Accepted:
            sys.exit(0)
    # A JANELA PRINCIPAL PODE FALHAR — e se falhar, a pessoa NÃO PODE FICAR PRESA na versão
    # quebrada. O `checar_atualizacao` rodava só depois daqui, então um erro no __init__ da
    # MainWindow trancava tudo: o app morria antes de checar se já existia correção publicada.
    # Aconteceu na v135 (KeyError de um ícone) e o Levi ficou sem caminho pelo próprio app —
    # teve de reinstalar à mão. Agora o updater é oferecido JUSTAMENTE quando a janela não nasce.
    try:
        win = MainWindow(); _holder["win"] = win
        win.showMaximized()      # abre em tela cheia p/ aproveitar o espaço (padrão pedido pelo Levi)
    except Exception as exc:
        try:
            from workers import registrar_erro
            registrar_erro((type(exc), exc, exc.__traceback__))
        except Exception:
            pass
        QMessageBox.critical(None, "Criar OS — Fracttal",
                             "O app não conseguiu abrir a janela principal:\n\n%s\n\n"
                             "Vou procurar uma atualização — quase sempre a correção já está "
                             "publicada." % str(exc)[:300])
        checar_atualizacao(None, silencioso=False)     # não-silencioso: aqui o aviso É o ponto
        sys.exit(1)
    # checa atualização (GitHub Releases) logo após abrir, sem travar o boot
    QTimer.singleShot(1500, lambda: checar_atualizacao(win, silencioso=True))
    if uri:
        QTimer.singleShot(500, lambda: _dispatch_uri(uri))   # aplica a sugestão após a janela montar
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
