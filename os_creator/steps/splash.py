"""Splash de abertura: o logo da Grid surge suavemente, segura um instante e some (fade-out) —
depois o app aparece. Usa o grid-logo.png (sem GIF); se um dia houver um .gif animado, dá p/ trocar
por QMovie aqui. Bloqueia ~1,4s no boot (via QEventLoop) e não deixa exceção escapar (não trava o app)."""
from PyQt6.QtCore import Qt, QTimer, QEventLoop, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QSplashScreen


def mostrar_splash(app, logo_path, fracao=0.6, dur_fade=380, dur_hold=650):
    """Mostra o símbolo da Grid GRANDE (fração da tela) com fade-in → hold → fade-out, bloqueando até
    terminar. Silencioso em erro. `fracao` = tamanho do logo como fração do menor lado da tela."""
    try:
        pix = QPixmap(str(logo_path))
        if pix.isNull():
            return
        scr = app.primaryScreen()
        if scr is not None:
            geo = scr.availableGeometry()
            alvo = max(240, min(int(min(geo.width(), geo.height()) * fracao), 900))
            pix = pix.scaled(alvo, alvo, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        splash = QSplashScreen(pix)
        splash.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        splash.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        splash.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        splash.setWindowOpacity(0.0)
        splash.show()
        app.processEvents()

        loop = QEventLoop()
        fade_in = QPropertyAnimation(splash, b"windowOpacity", splash)
        fade_in.setDuration(dur_fade); fade_in.setStartValue(0.0); fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.Type.InOutQuad)
        fade_out = QPropertyAnimation(splash, b"windowOpacity", splash)
        fade_out.setDuration(dur_fade); fade_out.setStartValue(1.0); fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.InOutQuad)
        fade_out.finished.connect(loop.quit)
        fade_in.finished.connect(lambda: QTimer.singleShot(dur_hold, fade_out.start))

        # trava de segurança: se algo travar a animação, o loop sai sozinho
        QTimer.singleShot(dur_fade * 2 + dur_hold + 800, loop.quit)
        fade_in.start()
        loop.exec()
        splash.close()
        splash.deleteLater()
    except Exception:
        pass
