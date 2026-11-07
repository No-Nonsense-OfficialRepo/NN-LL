"""Usable monitor bounds, including taskbars on any edge and monitor offsets."""
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QGuiApplication


class DesktopArea(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        app = QGuiApplication.instance()
        for screen in app.screens():
            self._watch(screen)
        app.screenAdded.connect(self._watch)
        app.screenRemoved.connect(self.changed)

    def _watch(self, screen):
        screen.availableGeometryChanged.connect(self.changed)
        self.changed.emit()

    @Slot(QObject, result='QVariantMap')
    def availableGeometry(self, window):
        screen = window.screen() or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        return dict(x=area.x(), y=area.y(), width=area.width(), height=area.height())
