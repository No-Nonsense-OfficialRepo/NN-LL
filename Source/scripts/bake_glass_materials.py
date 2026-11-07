"""Render the launcher’s glass textures with Qt before packaging a release."""
from pathlib import Path
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QEventLoop, QMetaObject, QObject, Property, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickWindow
from PySide6 import QtSvg  # Load Qt's SVG support for the original artwork.


QT_ROOT = Path(__file__).resolve().parents[1] / "lantool" / "qt"
MATERIALS = {
    "No-Nonsense": "no-nonsense-glass.svg",
    "Pearl": "pearl-glass.svg",
    "Dark": "themes/dark/glass.svg",
    "Neon": "themes/neon/glass.svg",
}


class PreviewBackend(QObject):
    @Property("QVariantMap", constant=True)
    def state(self):
        return {"preview": True}


def bake():
    app = QGuiApplication([])
    app.setOrganizationName("LAN Launcher Build")
    app.setApplicationName("Glass Material Renderer")
    engine = QQmlEngine()
    backend = PreviewBackend()
    engine.rootContext().setContextProperty("backend", backend)
    component = QQmlComponent(engine)
    source = Path(__file__).with_name("GlassMaterialRenderer.qml").read_bytes()
    component.setData(source, QUrl.fromLocalFile(str(QT_ROOT / "qml" / "GlassMaterialRenderer.qml")))
    renderer = component.create()
    if renderer is None:
        raise RuntimeError(component.errorString())
    window = QQuickWindow()
    window.resize(1920, 1080)
    renderer.setSize(window.size())
    renderer.setParentItem(window.contentItem())
    window.show()

    loop = QEventLoop()
    timer = QTimer(singleShot=True, interval=30000)
    timer.timeout.connect(loop.quit)
    renderer.readyChanged.connect(loop.quit)
    for theme, asset in MATERIALS.items():
        svg = QT_ROOT / "assets" / asset
        QMetaObject.invokeMethod(renderer, "selectTheme", Q_ARG("QVariant", theme))
        renderer.setProperty("source", QUrl.fromLocalFile(str(svg)))
        if not renderer.property("ready"):
            timer.start()
            loop.exec()
            timer.stop()
        if not renderer.property("ready"):
            raise RuntimeError(f"Glass renderer did not finish {theme}.")
        png = svg.with_suffix(".png")
        saved = QMetaObject.invokeMethod(
            renderer, "saveMaterial", Q_RETURN_ARG("QVariant"), Q_ARG("QVariant", str(png))
        )
        if not saved:
            raise RuntimeError(f"Could not write {png}.")
        print(png.relative_to(QT_ROOT), flush=True)
    window.hide()


if __name__ == "__main__":
    bake()
