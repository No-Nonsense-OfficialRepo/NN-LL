"""Host-side extraction of a game executable's own icon (Windows only).

The sidebar shows the exe icon; the library shows the portrait cover. They are
separate images, so this module only ever produces the exe icon as a PNG.
Every failure returns False: a missing icon must never block adding a game.
"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

ICON_SIZE = 256


def extract_exe_icon(exe, dest, size: int = ICON_SIZE) -> bool:
    """Save the largest available icon of ``exe`` as a PNG at ``dest``."""
    if sys.platform != "win32":
        return False
    try:
        exe, dest = Path(exe), Path(dest)
        if not exe.is_file():
            return False
        image = _icon_image(exe, size)
        if image is None:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        image.save(tmp, format="PNG", optimize=True)
        os.replace(tmp, dest)
        return True
    except Exception:
        return False


class _ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP),
                ("hbmColor", wintypes.HBITMAP)]


class _BITMAP(ctypes.Structure):
    _fields_ = [("bmType", wintypes.LONG), ("bmWidth", wintypes.LONG),
                ("bmHeight", wintypes.LONG), ("bmWidthBytes", wintypes.LONG),
                ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                ("bmBits", wintypes.LPVOID)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def _icon_image(exe: Path, size: int):
    from PIL import Image
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    # Explicit prototypes: default int-sized handles truncate on 64-bit Python.
    user32.PrivateExtractIconsW.restype = wintypes.UINT
    user32.PrivateExtractIconsW.argtypes = [
        wintypes.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(wintypes.HICON), ctypes.POINTER(wintypes.UINT),
        wintypes.UINT, wintypes.UINT]
    user32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(_ICONINFO)]
    user32.DestroyIcon.argtypes = [wintypes.HICON]
    user32.GetDC.restype = wintypes.HDC
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                                ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    gdi32.DeleteObject.argtypes = [wintypes.HANDLE]

    hicon = wintypes.HICON()
    count = user32.PrivateExtractIconsW(str(exe), 0, size, size, ctypes.byref(hicon), None, 1, 0)
    if count in (0, 0xFFFFFFFF) or not hicon.value:
        return None
    info = _ICONINFO()
    hdc = None
    try:
        if not user32.GetIconInfo(hicon, ctypes.byref(info)) or not info.hbmColor:
            return None
        bitmap = _BITMAP()
        gdi32.GetObjectW(info.hbmColor, ctypes.sizeof(bitmap), ctypes.byref(bitmap))
        width, height = int(bitmap.bmWidth), int(bitmap.bmHeight)
        if width <= 0 or height <= 0 or width > 1024 or height > 1024:
            return None
        header = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), width, -height, 1, 32, 0)
        buffer = ctypes.create_string_buffer(width * height * 4)
        hdc = user32.GetDC(None)
        if gdi32.GetDIBits(hdc, info.hbmColor, 0, height, buffer, ctypes.byref(header), 0) == 0:
            return None
        image = Image.frombuffer("RGBA", (width, height), buffer.raw, "raw", "BGRA", 0, 1)
        # Icons without an alpha channel come back fully transparent.
        if image.getchannel("A").getextrema()[1] == 0:
            image.putalpha(255)
        return image.copy()
    finally:
        if hdc:
            user32.ReleaseDC(None, hdc)
        for handle in (info.hbmColor, info.hbmMask):
            if handle:
                gdi32.DeleteObject(handle)
        user32.DestroyIcon(hicon)
