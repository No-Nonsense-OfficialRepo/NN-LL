"""room-errors.log is bounded (audit A23); register_game saves the catalog once (audit A24)."""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

local_qt = Path(__file__).resolve().parents[1] / "build" / "qt-runtime"
if local_qt.is_dir():
    sys.path.insert(0, str(local_qt))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import lantool.qt  # noqa: F401,E402  (same eager Qt init as production)
from lantool import launcher as core  # noqa: E402


def test_room_error_log_rotates_past_the_limit(tmp_path):
    log = tmp_path / "room-errors.log"
    log.write_bytes(b"x" * 3000)
    with patch.object(core, "APP_DIR", tmp_path), patch.object(core, "ROOM_ERROR_LOG_LIMIT", 2000):
        core.LauncherCore._log_room_error(ValueError("boom"))
    assert log.stat().st_size < 2000
    assert b"boom" in log.read_bytes()
    assert (tmp_path / "room-errors.log.1").stat().st_size == 3000


def test_room_error_log_stays_bounded_over_many_failures(tmp_path):
    with patch.object(core, "APP_DIR", tmp_path), patch.object(core, "ROOM_ERROR_LOG_LIMIT", 4000):
        for i in range(100):
            core.LauncherCore._log_room_error(ValueError(f"failure {i}"))
    assert (tmp_path / "room-errors.log").stat().st_size < 4000 + 2000  # at most one entry past the limit
    assert (tmp_path / "room-errors.log.1").stat().st_size < 4000 + 2000


def _host(tmp_path):
    fake = object.__new__(core.LauncherCore)
    fake.game_root = tmp_path
    fake.game_catalog = {}
    fake.host_art_root = tmp_path / "art"
    fake._save_host_catalog = MagicMock()
    fake._refresh_host_playlist = MagicMock()
    folder = tmp_path / "Game"
    folder.mkdir()
    exe = folder / "game.exe"
    exe.write_bytes(b"x")
    return fake, folder, exe


def test_register_game_saves_and_refreshes_once(tmp_path):
    fake, folder, exe = _host(tmp_path)
    with patch("lantool.exe_icon.extract_exe_icon", return_value=False):
        core.LauncherCore.register_game(fake, folder, exe, "Game")
    assert len(fake.game_catalog) == 1
    assert fake._save_host_catalog.call_count == 1
    assert fake._refresh_host_playlist.call_count == 1


def test_register_game_still_registers_when_icon_extraction_fails(tmp_path):
    fake, folder, exe = _host(tmp_path)
    with patch("lantool.exe_icon.extract_exe_icon", side_effect=RuntimeError("no icon")):
        core.LauncherCore.register_game(fake, folder, exe, "Game")
    assert len(fake.game_catalog) == 1
    assert fake._save_host_catalog.call_count == 1


def test_refresh_game_icon_alone_saves_once(tmp_path):
    fake, folder, exe = _host(tmp_path)
    with patch("lantool.exe_icon.extract_exe_icon", return_value=False):
        core.LauncherCore.register_game(fake, folder, exe, "Game")
        fake._save_host_catalog.reset_mock()
        fake._refresh_host_playlist.reset_mock()
        game_id = next(iter(fake.game_catalog))
        core.LauncherCore.refresh_game_icon(fake, game_id)
    assert fake._save_host_catalog.call_count == 1
    assert fake._refresh_host_playlist.call_count == 1
