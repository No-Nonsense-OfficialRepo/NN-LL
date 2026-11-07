"""portable.flag: state beside the app instead of %LOCALAPPDATA% (paths with spaces included)."""
from pathlib import Path

from lantool import appdirs


def test_default_is_localappdata_without_flag(tmp_path):
    root = tmp_path / "My Launcher"
    root.mkdir()
    got = appdirs.default_app_dir(root, {"LOCALAPPDATA": str(tmp_path / "Local Data")})
    assert got == tmp_path / "Local Data" / "LanTool"
    assert not appdirs.is_portable(root)


def test_flag_moves_state_beside_app_even_with_spaces(tmp_path):
    root = tmp_path / "USB Stick (E)" / "LAN Launcher v2"
    root.mkdir(parents=True)
    (root / "portable.flag").write_text("")
    got = appdirs.default_app_dir(root, {"LOCALAPPDATA": str(tmp_path / "ignored")})
    assert got == root / "LanTool-data"
    assert appdirs.is_portable(root)


def test_flag_must_be_a_file_not_a_folder(tmp_path):
    (tmp_path / "portable.flag").mkdir()
    assert not appdirs.is_portable(tmp_path)


def test_missing_localappdata_falls_back_to_home(tmp_path):
    got = appdirs.default_app_dir(tmp_path, {})
    assert got == Path.home() / "AppData" / "Local" / "LanTool"


def test_app_root_frozen_uses_exe_folder(tmp_path, monkeypatch):
    exe = tmp_path / "Lan Launcher" / "Client.exe"
    exe.parent.mkdir()
    exe.write_text("")
    monkeypatch.setattr(appdirs.sys, "frozen", True, raising=False)
    monkeypatch.setattr(appdirs.sys, "executable", str(exe))
    assert appdirs.app_root() == exe.parent.resolve()


def test_silent_tunnel_store_follows_portable(tmp_path, monkeypatch):
    import os
    if os.name != "nt":
        return
    from silent_tunnel import store
    monkeypatch.delenv("SILENT_TUNNEL_HOME", raising=False)
    root = tmp_path / "Portable Copy"
    root.mkdir()
    (root / "portable.flag").write_text("")
    monkeypatch.setattr(appdirs, "app_root", lambda: root)
    assert store.data_dir() == root / "LanTool-data" / "vla-state" / "standalone"
