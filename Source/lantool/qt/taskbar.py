"""Keep the frameless launcher eligible for the Windows taskbar."""
import ctypes
import logging
import sys


def taskbar_style(style):
    # APPWINDOW forces a taskbar entry even if Windows has assigned an owner.
    return (style | 0x00040000) & ~0x00000080  # WS_EX_APPWINDOW, WS_EX_TOOLWINDOW


def maintain_taskbar_entry(window):
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QGuiApplication
    if sys.platform != 'win32' or QGuiApplication.platformName() != 'windows':
        return
    user = ctypes.WinDLL('user32', use_last_error=True)
    from ctypes import wintypes
    get_style = user.GetWindowLongPtrW
    set_style = user.SetWindowLongPtrW
    get_style.argtypes = [wintypes.HWND, ctypes.c_int]
    get_style.restype = ctypes.c_ssize_t
    set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    set_style.restype = ctypes.c_ssize_t
    user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user.SetWindowPos.restype = wintypes.BOOL

    def refresh():
        if not window.isVisible():
            return
        hwnd = int(window.winId())
        style = get_style(hwnd, -20)
        desired = taskbar_style(style)
        if style != desired:
            ctypes.set_last_error(0)
            result = set_style(hwnd, -20, desired)
            if not result and ctypes.get_last_error():
                logging.getLogger(__name__).warning('Could not restore launcher taskbar style: %s', ctypes.get_last_error())
                return
            user.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0037)  # frame changed, no move/size/activation/z-order

    def schedule(*unused):
        QTimer.singleShot(0, refresh)
    window.visibleChanged.connect(schedule)
    window.visibilityChanged.connect(schedule)
    schedule()
