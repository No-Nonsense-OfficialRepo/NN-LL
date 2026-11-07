"""Keep one networking owner per role across Windows release copies."""
from __future__ import annotations
import ctypes
import os
from pathlib import Path
import sys


def launcher_role():
    from .role import detect_role
    return detect_role()


def is_preview():
    return '--preview' in sys.argv or '--capture-ui' in sys.argv


def _kernel():
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    api.CreateMutexW.restype = ctypes.c_void_p
    api.OpenMutexW.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_wchar_p]
    api.OpenMutexW.restype = ctypes.c_void_p
    api.CloseHandle.argtypes = [ctypes.c_void_p]
    api.CloseHandle.restype = ctypes.c_int
    return api


class RoleInstance:
    def __init__(self, role, *, namespace='Global\\GamerUtility.LANLauncher'):
        if role not in ('host', 'client'):
            raise ValueError('Invalid launcher role')
        self.name = namespace + '.' + role
        self.handle = None

    def acquire(self):
        if os.name != 'nt' or self.handle:
            return True
        api = _kernel()
        ctypes.set_last_error(0)
        handle = api.CreateMutexW(None, False, self.name)
        error = ctypes.get_last_error()
        if not handle:
            if error == 5:  # Another account owns the same computer-wide role.
                return False
            raise ctypes.WinError(error)
        if error == 183:
            api.CloseHandle(handle)
            return False
        self.handle = handle
        return True

    def close(self):
        if self.handle:
            _kernel().CloseHandle(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()


def already_running(role):
    """Read-only check before asking Windows to elevate another process."""
    if os.name != 'nt':
        return False
    api = _kernel()
    handle = api.OpenMutexW(0x00100000, False, RoleInstance(role).name)
    if handle:
        api.CloseHandle(handle)
        return True
    return ctypes.get_last_error() == 5 or bool(_existing_window(role))


def _existing_window(role):
    if os.name != 'nt':
        return None
    user = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    user.EnumWindows.argtypes = [callback_type, ctypes.c_void_p]
    user.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    found = []
    prefix = 'LAN ' + role.title() + ' '
    def visit(window, unused):
        title = ctypes.create_unicode_buffer(512)
        user.GetWindowTextW(window, title, len(title))
        if user.IsWindowVisible(window) and title.value.startswith(prefix) and 'DESIGN PREVIEW' not in title.value:
            found.append(window)
            return False
        return True
    user.EnumWindows(callback_type(visit), None)
    return found[0] if found else None


def show_existing(role):
    if os.name != 'nt':
        return
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    user.MessageBoxW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    window = _existing_window(role)
    if window:
        user.ShowWindow(window, 9)
        user.SetForegroundWindow(window)
    else:
        user.MessageBoxW(None, f'NN LAN Launcher {role.title()} is already open on this computer.', 'NN LAN Launcher', 0x40)
