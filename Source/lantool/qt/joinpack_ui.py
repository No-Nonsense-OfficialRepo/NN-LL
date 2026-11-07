"""Join pack dialogs for the Qt bridge.

Plain functions that take the bridge as their first argument. The QML-facing
Slot methods stay on LauncherBridge in bridge.py and delegate here.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox

from .. import launcher as core


def save_join_pack(bridge) -> None:
    """Host: write a signed join pack file for the open room."""
    if bridge._preview or not bridge.room:
        return
    try:
        from .. import joinpack
        from .._version import __version__ as _pack_version
        identity = json.loads((core.APP_DIR / "host_identity.json").read_text(encoding="utf-8"))
        exe = Path(sys.executable)
        exe_hash = hashlib.sha256(exe.read_bytes()).hexdigest()
        room_info = {
            "room_code": str(getattr(bridge.room, "room_code", "") or ""),
            "net_id": str(getattr(bridge.room, "network_id", "") or ""),
            "host_name": str(getattr(bridge.room, "host_name", "") or "") or "Host",
        }
        data = joinpack.build(room_info, _pack_version, {"exe": exe_hash}, priv_b64=identity["private"])
    except Exception as exc:
        QMessageBox.warning(None, "Save join pack", f"Couldn't make the join pack: {exc or type(exc).__name__}")
        return
    path, _ = QFileDialog.getSaveFileName(None, "Save join pack", "LanLauncher.joinpack", "Join pack (*.joinpack)")
    if not path:
        return
    Path(path).write_bytes(data)
    QMessageBox.information(None, "Save join pack", f"Saved {Path(path).name}. Send it to the Client PC and use Open join pack.")


def open_join_pack(bridge) -> None:
    """Client: read a join pack, check it, then offer to join the room it names."""
    if bridge._preview or bridge.busy or bridge.room or bridge._beacon_joining:
        return
    path, _ = QFileDialog.getOpenFileName(None, "Open join pack", "", "Join pack (*.joinpack)")
    if not path:
        return
    try:
        from .. import joinpack
        pack = joinpack.parse(Path(path).read_bytes())
    except Exception as exc:
        QMessageBox.warning(None, "Open join pack", f"This join pack can't be used: {exc or type(exc).__name__}")
        return
    notes = []
    try:
        local = hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
        if local != pack.exe_sha256:
            notes.append("Warning: this launcher is not the same build as the Host's (different exe hash).")
    except OSError:
        notes.append("Couldn't check this launcher's build.")
    answer = QMessageBox.question(
        None, "Join room?",
        f"Host: {pack.host_name}\nApp version: {pack.app_version}\n" + "\n".join(notes) + ("\n" if notes else "") + "Join this room now?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel)
    if answer == QMessageBox.StandardButton.Yes:
        bridge.joinRoomKey(pack.room_code)
