"""
Process listing with Windows icon extraction.

GET /api/processes  → list of running processes with name, pid, exe path
GET /api/processes/{pid}/icon  → 32x32 PNG icon for the process executable
"""

from __future__ import annotations

import base64
import io
import logging
import os
import sys
from functools import lru_cache
from typing import Any

import psutil

log = logging.getLogger("intruder.processes")

_IS_WINDOWS = sys.platform == "win32"


def list_processes() -> list[dict[str, Any]]:
    """Return a list of running processes visible to the current user."""
    result: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name", "exe", "username"]):
        try:
            info = proc.info
            result.append({
                "pid": info["pid"],
                "name": info["name"] or "",
                "exe": info["exe"] or "",
                "username": info["username"] or "",
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    result.sort(key=lambda p: p["name"].lower())
    return result


# ---------------------------------------------------------------------------
# Windows icon extraction via ctypes
# ---------------------------------------------------------------------------

_icon_cache: dict[str, bytes | None] = {}


def get_icon_png(exe_path: str) -> bytes | None:
    """
    Extract the primary icon from an executable and return it as PNG bytes.
    Returns None on non-Windows or if extraction fails.
    """
    if not _IS_WINDOWS or not exe_path:
        return None

    norm = os.path.normcase(exe_path)
    if norm in _icon_cache:
        return _icon_cache[norm]

    try:
        png = _extract_icon_windows(exe_path)
    except Exception:
        log.debug("Icon extraction failed for %s", exe_path, exc_info=True)
        png = None

    _icon_cache[norm] = png
    return png


def _extract_icon_windows(exe_path: str) -> bytes | None:
    import ctypes
    from ctypes import wintypes

    shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    gdi32 = ctypes.windll.gdi32  # type: ignore[attr-defined]

    class ICONINFO(ctypes.Structure):
        _fields_ = [
            ("fIcon", wintypes.BOOL),
            ("xHotspot", wintypes.DWORD),
            ("yHotspot", wintypes.DWORD),
            ("hbmMask", wintypes.HBITMAP),
            ("hbmColor", wintypes.HBITMAP),
        ]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    large_icon = ctypes.c_void_p()
    small_icon = ctypes.c_void_p()
    count = shell32.ExtractIconExW(exe_path, 0, ctypes.byref(large_icon), ctypes.byref(small_icon), 1)

    if count == 0:
        return None

    hicon = large_icon.value or small_icon.value
    if not hicon:
        return None

    try:
        icon_info = ICONINFO()
        if not user32.GetIconInfo(hicon, ctypes.byref(icon_info)):
            return None

        hdc = user32.GetDC(None)
        try:
            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            gdi32.GetDIBits(hdc, icon_info.hbmColor, 0, 0, None, ctypes.byref(bmi), 0)

            w = bmi.biWidth
            h = abs(bmi.biHeight)
            if w == 0 or h == 0:
                return None

            bmi.biBitCount = 32
            bmi.biCompression = 0
            bmi.biHeight = -h
            bmi.biSizeImage = w * h * 4

            buf = ctypes.create_string_buffer(bmi.biSizeImage)
            gdi32.GetDIBits(hdc, icon_info.hbmColor, 0, h, buf, ctypes.byref(bmi), 0)
        finally:
            user32.ReleaseDC(None, hdc)
            gdi32.DeleteObject(icon_info.hbmMask)
            gdi32.DeleteObject(icon_info.hbmColor)

        from PIL import Image

        img = Image.frombuffer("RGBA", (w, h), buf.raw, "raw", "BGRA", 0, 1)
        if img.size != (32, 32):
            img = img.resize((32, 32), Image.LANCZOS)

        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()
    finally:
        user32.DestroyIcon(hicon)
        if small_icon.value and small_icon.value != hicon:
            user32.DestroyIcon(small_icon.value)
        if large_icon.value and large_icon.value != hicon:
            user32.DestroyIcon(large_icon.value)
