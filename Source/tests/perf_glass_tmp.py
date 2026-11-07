"""Temporary measurement: glass paint time and banding of the Dark theme gradient."""
import json
import time
from pathlib import Path
from . import test_qt_ui as T
from PySide6.QtCore import QObject, QUrl
from PySide6.QtQml import QQmlComponent


def metrics(image, fy_list=(.3, .5, .7)):
    """Return (flat-window fraction, staircase score) over green-channel rows; smooth+dithered: low flat, ~.25."""
    flat = windows = 0
    stair = count = 0.0
    w, h = image.width(), image.height()
    for fy in fy_list:
        y = int(h * fy)
        line = [image.pixelColor(x, y).green() for x in range(int(w * .08), int(w * .92))]
        for i in range(0, len(line) - 15, 3):
            win = line[i:i + 9]
            flat += (max(win) == min(win))
            windows += 1
            mean = sum(line[i:i + 15]) / 15
            stair += abs(mean - round(mean))
            count += 1
    return flat / windows, stair / count


class Perf(T.QtLauncherTests):
    def run_theme(self, name):
        self.engine = T.create_engine(self.bridge)
        window = self.engine.rootObjects()[0]
        ini = json.dumps(QUrl.fromLocalFile(str(self.root / 'probe.ini')).toString())
        qml = ('import QtQuick\nimport "."\nItem { width: 1280; height: 720\n'
               'Component.onCompleted: { Theme.preferences.location = ' + ini + '; Theme.reload(); Theme.apply("' + name + '"); }\n'
               'GlassSurface { objectName: "probeGlass"; anchors.fill: parent }\n}').encode()
        base = Path(T.__file__).resolve().parents[1] / 'lantool/qt/qml/GlassProbeTmp.qml'
        component = QQmlComponent(self.engine)
        component.setData(qml, QUrl.fromLocalFile(str(base)))
        harness = component.create()
        self.assertIsNotNone(harness, [e.toString() for e in component.errors()])
        harness.setParentItem(window.contentItem())
        glass = harness.findChild(QObject, 'probeGlass')
        canvas = glass.childItems()[0]
        done = []
        t0 = time.monotonic()
        canvas.painted.connect(lambda: done.append(time.monotonic()))
        T.pump_until(lambda: len(done) >= 1, timeout=60)
        T.pump(3.0)  # image load, the real paint, and any repaint from the theme change
        elapsed = (done[-1] - t0) if done else -1
        result = glass.grabToImage()
        ready = []
        result.ready.connect(lambda: ready.append(True))
        T.pump_until(lambda: ready, timeout=10)
        image = result.image()
        flat, stair = metrics(image)
        y = int(image.height() * .5)
        sample = [image.pixelColor(x, y).green() for x in range(400, 460)]
        print(f"GLASS {name}: paint completions at {[round(t - t0, 2) for t in done]}s, flat-window fraction {flat:.2f}, "
              f"staircase score {stair:.3f} (smooth ~0.25), row sample {sample}")

    def test_glass_dark(self):
        self.run_theme("Dark")
