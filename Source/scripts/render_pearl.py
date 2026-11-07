"""Render actual production controls for visual comparison, without networking."""
import os
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root / 'build/qt-runtime'), str(root)]
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QUICK_BACKEND'] = 'software'
os.environ.setdefault('QT_QPA_FONTDIR', str(root / 'lantool/qt/assets/fonts'))
import lantool.qt
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QUrl, QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
app=QApplication([])
QQuickStyle.setStyle('Basic')
for font in (root/'lantool/qt/assets/fonts').glob('*.ttf'):
    QFontDatabase.addApplicationFont(str(font))
engine=QQmlApplicationEngine()
warnings=[]
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
engine.load(QUrl.fromLocalFile(str(root/'lantool/qt/qml/ControlSpecimen.qml')))
if not engine.rootObjects(): raise RuntimeError('Control specimen failed to load')
def capture():
    out=root/'build/pearl-preview/controls.png'
    out.parent.mkdir(parents=True,exist_ok=True)
    ok=engine.rootObjects()[0].grabWindow().save(str(out))
    print(str(out))
    for warning in warnings: print(warning)
    app.exit(0 if ok and not warnings else 1)
QTimer.singleShot(700,capture)
raise SystemExit(app.exec())
