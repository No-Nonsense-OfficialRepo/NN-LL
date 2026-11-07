"""Verify the project-local Qt Quick runtime without opening a window."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main():
    local_runtime = Path(__file__).resolve().parents[1] / "build" / "qt-runtime"
    if local_runtime.is_dir():
        sys.path.insert(0, str(local_runtime))
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6 import __version__
    from PySide6.QtCore import QObject, QUrl, Slot, qVersion
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine

    class Backend(QObject):
        @Slot(result=str)
        def status(self):
            return "Python connected"

    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    backend = Backend()
    engine.rootContext().setContextProperty("backend", backend)
    engine.loadData(b'''
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
ApplicationWindow {
    width: 1280; height: 820; visible: false
    property string backendStatus: backend.status()
    ColumnLayout {
        Label { text: "NN LAN Launcher" }
        Button { text: "Qt Quick ready" }
    }
}
''', QUrl("file:///qt-runtime-check.qml"))
    if not engine.rootObjects():
        raise RuntimeError("Qt Quick could not load the QML test window.")
    window = engine.rootObjects()[0]
    if window.property("backendStatus") != "Python connected":
        raise RuntimeError("The Python-to-QML connection failed.")
    app.processEvents()
    print(f"PySide6 {__version__}; Qt {qVersion()}")
    print("Qt Quick, Controls, Layouts and the Python bridge are ready.")
    engine.deleteLater()
    app.processEvents()


if __name__ == "__main__":
    main()
