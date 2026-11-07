"""Temporary probe: which ImageData write-back variant actually reaches the rendered canvas in this Qt?"""
import tempfile
from pathlib import Path
from . import test_qt_ui as T
from PySide6.QtCore import QObject, QUrl
from PySide6.QtQuick import QQuickView
from PySide6.QtWidgets import QApplication

QML = """
import QtQuick
Item { width: 32; height: 16
 property int paintedCount: 0
 component Probe: Canvas {
  id: pc
  property string mode: ""
  width: 32; height: 4
  onPaint: {
   var ctx = getContext("2d");
   ctx.fillStyle = "rgb(100,100,100)"; ctx.fillRect(0, 0, width, height);
   var img;
   if (mode === "create") img = ctx.createImageData(width, height);
   else img = ctx.getImageData(0, 0, width, height);
   var d = img.data;
   for (var p = 0; p < d.length; p += 4) { var v = (p / 4) % 2 ? 90 : 110; d[p] = v; d[p+1] = v; d[p+2] = v; d[p+3] = 255; }
   if (mode === "draw") ctx.drawImage(img, 0, 0);
   else if (mode === "dirty") ctx.putImageData(img, 0, 0, 0, 0, width, height);
   else ctx.putImageData(img, 0, 0);
   var root = parent; root.paintedCount = root.paintedCount + 1;
  }
 }
 Probe { objectName: "get"; mode: "get"; y: 0 }
 Probe { objectName: "create"; mode: "create"; y: 4 }
 Probe { objectName: "draw"; mode: "draw"; y: 8 }
 Probe { objectName: "dirty"; mode: "dirty"; y: 12 }
}
"""


def test_probe_variants():
    app = QApplication.instance() or QApplication([])
    path = Path(tempfile.mkdtemp()) / "probe3.qml"
    path.write_text(QML, encoding="utf-8")
    view = QQuickView()
    view.setSource(QUrl.fromLocalFile(str(path)))
    view.show()
    root = view.rootObject()
    T.pump_until(lambda: root.property("paintedCount") >= 4, timeout=10)
    T.pump(.3)
    for name in ("get", "create", "draw", "dirty"):
        item = root.findChild(QObject, name)
        result = item.grabToImage()
        ready = []
        result.ready.connect(lambda: ready.append(True))
        T.pump_until(lambda: ready, timeout=10)
        image = result.image()
        print(f"PROBE3 {name}:", [image.pixelColor(x, 0).red() for x in range(8)], "(110/90 alternating = works, 100 = ignored)")
