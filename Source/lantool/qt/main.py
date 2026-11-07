"""Start the Qt Quick frontend; --preview is isolated from real room state."""
from __future__ import annotations
import os
import sys
import tempfile
from pathlib import Path


def configure_font_directory():
    """Point Qt at the fonts we ship before it initializes its font database."""
    root = Path(__file__).resolve().parent
    if getattr(sys, "frozen", False):
        from ..launcher import _resource_path
        root = _resource_path("qt")
    os.environ.setdefault("QT_QPA_FONTDIR", str(root / "assets" / "fonts"))


def create_engine(bridge, *, startup=False):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QFont, QFontDatabase, QIcon
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtQuick import QQuickWindow
    from PySide6 import QtSvg  # Include SVG image support in the Windows package.
    from ..launcher import _resource_path
    root = Path(__file__).resolve().parent
    if getattr(sys, "frozen", False):
        root = _resource_path("qt")
    from PySide6.QtWidgets import QApplication
    QApplication.instance().setWindowIcon(QIcon(str(root / 'assets' / 'launcher-icon.ico')))
    for font in (root / "assets" / "fonts").glob("*.ttf"):
        if QFontDatabase.addApplicationFont(str(font)) < 0:
            raise RuntimeError(f"Couldn't load bundled font: {font.name}")
    # Raw QML Text and Qt controls inherit this when they do not set a family.
    bundled_families = QFontDatabase.families()
    for family in ("Cormorant Garamond", "Cinzel", "Inter"):
        if family not in bundled_families:
            raise RuntimeError(f"The bundled {family} font was not registered by Qt.")
    default_font = QFont(QApplication.instance().font())
    default_font.setFamily("Inter")
    if default_font.pixelSize() > 0:
        default_font.setPixelSize(max(1, round(default_font.pixelSize() * 0.72)))
    elif default_font.pointSizeF() > 0:
        default_font.setPointSizeF(default_font.pointSizeF() * 0.72)
    QApplication.instance().setFont(default_font)
    if QQuickStyle.name() != "Basic":
        QQuickStyle.setStyle("Basic")
    engine = QQmlApplicationEngine()
    qml_warnings = []
    engine.warnings.connect(lambda warnings: qml_warnings.extend(str(warning) for warning in warnings))
    from .desktop import DesktopArea
    engine.rootContext().setContextProperty("DesktopArea", DesktopArea(engine))
    engine.rootContext().setContextProperty("backend", bridge)
    engine.rootContext().setContextProperty("showStartupCurtain", startup)
    engine.rootContext().setContextProperty("termsOfService", (root / 'assets/terms-of-service.md').read_text(encoding='utf-8'))
    engine.load(QUrl.fromLocalFile(str(root / "qml" / "Main.qml")))
    if not engine.rootObjects() or not isinstance(engine.rootObjects()[0], QQuickWindow):
        detail = "\n".join(qml_warnings[-12:])
        raise RuntimeError("The Qt launcher interface could not be loaded." + ("\n" + detail if detail else ""))
    window = engine.rootObjects()[0]
    window.setIcon(QApplication.instance().windowIcon())
    from .taskbar import maintain_taskbar_entry
    maintain_taskbar_entry(window)
    return engine


def _run():
    configure_font_directory()
    capture = (Path(sys.argv[sys.argv.index("--capture-ui")+1]).resolve()
               if "--capture-ui" in sys.argv else None)
    preview = "--preview" in sys.argv or capture is not None
    if capture:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    if preview or "--software" in sys.argv:
        os.environ.setdefault("QT_QUICK_BACKEND", "software")
    # Qt Dialogs need QApplication for native file pickers, not a Tk interpreter.
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from .bridge import LauncherBridge
    from .. import launcher as core
    if sys.platform == 'win32':
        import ctypes
        role = 'Host' if core.HOST_ROLE == 'host' else 'Client'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('NNLANLauncher.' + role)
    app = QApplication(sys.argv)
    app.setApplicationName("NN LAN Launcher")
    app.setApplicationVersion(core.__version__)
    app.setOrganizationName("NN LAN Launcher")
    from PySide6.QtCore import QSettings
    old_settings = QSettings('Gamer Utility', 'Gamer Utility')
    new_settings = QSettings('NN LAN Launcher', 'NN LAN Launcher')
    for key in old_settings.allKeys():
        if not new_settings.contains(key):
            new_settings.setValue(key, old_settings.value(key))
    temp = None
    if preview:
        temp = tempfile.TemporaryDirectory(prefix="lan-qt-preview-")
        state = Path(temp.name)
        core.APP_DIR = state / "state"
        core.CONFIG_PATH = core.APP_DIR / "launcher.json"
        core.ZT_OWNERSHIP_FILE = state / "ownership"
        core.GAME_FILES_ROOT = state / "Game Directory"
        os.environ["SILENT_TUNNEL_HOME"] = str(state / "tunnel")
    bridge = LauncherBridge(start_services=not preview, preview=preview)
    if preview:
        titles = ["Age of Empires II", "Battlefield 3", "Battlefield: Bad Company 2",
                  "Call of Duty 4", "Counter-Strike 2", "Diablo II", "DOOM",
                  "Factorio", "FlatOut 2", "Left 4 Dead 2", "Minecraft", "Quake III Arena",
                  "Terraria", "TrackMania Nations", "Unreal Tournament", "Warcraft III"]
        bridge.config_data["setup_completed"] = True
        bridge.library = {f"g{i}": {"id": f"g{i}", "name": name, "exe": "game.exe",
                                  "install_dir": str(core.GAME_FILES_ROOT / str(i))}
                          for i, name in enumerate(titles)}
        bridge._page = "library"
        bridge._selected = "g3"
        if "--preview-page" in sys.argv:
            bridge._page = sys.argv[sys.argv.index("--preview-page")+1]
        if "--preview-settings-tab" in sys.argv:
            bridge._setting_tab = sys.argv[sys.argv.index("--preview-settings-tab")+1]
        bridge.publish()
    engine = create_engine(bridge, startup=not preview)
    bridge.quitReady.connect(app.quit)
    if capture:
        def save_capture():
            image = engine.rootObjects()[0].grabWindow()
            capture.parent.mkdir(parents=True, exist_ok=True)
            if image.isNull() or not image.save(str(capture)):
                app.exit(1)
            else:
                app.exit(0)
        QTimer.singleShot(800, save_capture)
    code = app.exec()
    # Normal close goes through LauncherCore's asynchronous cleanup.
    if not bridge._destroyed:
        bridge.runtime.stop()
    del engine
    if temp:
        temp.cleanup()
    return code


def main():
    from ..single_instance import RoleInstance, is_preview, launcher_role, show_existing, _existing_window
    if is_preview():
        return _run()
    role = launcher_role()
    with RoleInstance(role) as instance:
        if not instance.acquire() or _existing_window(role):
            show_existing(role)
            return 0
        return _run()


if __name__ == "__main__":
    raise SystemExit(main())

