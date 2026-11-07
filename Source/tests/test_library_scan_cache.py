"""Repeated library polls must not rescan the disk for every game (audit A03)."""
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

local_qt = Path(__file__).resolve().parents[1] / "build" / "qt-runtime"
if local_qt.is_dir():
    sys.path.insert(0, str(local_qt))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import lantool.qt  # noqa: F401,E402  (same eager Qt init as production)
from lantool import launcher as core  # noqa: E402
import lantool.filesync.index as index_mod  # noqa: E402

HOST_PUB = "p" * 64


def _game(sha="x"):
    return {"id": "g", "name": "G", "exe": "g.exe", "exe_size": 5, "exe_sha256": sha}


def _connection(games):
    body = json.dumps({"type": "library", "games": games}).encode()
    reader = MagicMock()
    reader.readuntil = AsyncMock(return_value=b"HTTP/1.0 200 OK\r\nContent-Length: %d\r\n\r\n" % len(body))
    reader.readexactly = AsyncMock(return_value=body)
    writer = MagicMock()
    writer.drain = AsyncMock()
    writer.wait_closed = AsyncMock()
    return reader, writer


def _poll(tmp_path, scan_results, games_per_poll):
    """Run one fetch per entry in games_per_poll, return how many times find_game_folder ran."""
    fake = object.__new__(core.LauncherCore)
    fake.library = {}
    fake.role = "client"
    fake.game_root = tmp_path
    fake.client_art_root = tmp_path / "art"
    fake.seeded_games = set()
    fake.seeded_files = {}
    fake.peer_file_server = None
    fake.after = MagicMock()
    scans = []

    def find_game_folder(*args, **kwargs):
        scans.append(args)
        return scan_results

    async def run_work(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    connections = iter([_connection(games) for games in games_per_poll])

    async def open_connection(*_args):
        return next(connections)

    async def fetch_all():
        for _ in games_per_poll:
            await core.LauncherCore._fetch_host_library(fake, "10.0.0.2", 47803, HOST_PUB)

    with patch.object(core, "APP_DIR", tmp_path), \
         patch.object(core.asyncio, "open_connection", side_effect=open_connection), \
         patch.object(core.signing, "verify_obj", return_value=True), \
         patch.object(core.FRESHNESS, "check"), \
         patch.object(core, "validate", side_effect=lambda manifest: manifest), \
         patch.object(core, "assign_client_folders", side_effect=lambda *a: {"g": tmp_path / "G"}), \
         patch.object(core, "find_game_folder", side_effect=find_game_folder), \
         patch.object(index_mod, "run_hash_work", new=run_work), \
         patch.object(core.LauncherCore, "_local_host_library", return_value={}), \
         patch.object(core.LauncherCore, "_reuse_local_host_source"), \
         patch.object(core.LauncherCore, "_local_host_source_matches", return_value=False):
        asyncio.run(fetch_all())
    return len(scans)


def test_unchanged_library_with_no_local_copy_scans_once(tmp_path):
    assert _poll(tmp_path, None, [[_game()]] * 4) == 1


def test_unchanged_library_with_local_copy_scans_once(tmp_path):
    found = tmp_path / "found"
    found.mkdir()
    assert _poll(tmp_path, found, [[_game()]] * 4) == 1


def test_changed_exe_fingerprint_scans_again(tmp_path):
    assert _poll(tmp_path, None, [[_game("x")], [_game("x")], [_game("y")]]) == 2


def test_executable_scan_does_not_reuse_other_games_downloads(tmp_path):
    installed = tmp_path / "Installed Game"
    nested = installed / "wrapper"
    nested.mkdir(parents=True)
    (installed / "game.exe").write_bytes(b"first")
    (nested / "game.exe").write_bytes(b"first")
    preferred = tmp_path / "Other Game"
    assert core.find_game_folder(tmp_path, "game.exe", 5, preferred=preferred, reserved={installed}) is None
    assert core.find_game_folder(tmp_path, "game.exe", 6, preferred=preferred) is None
    preferred.mkdir()
    (preferred / "game.exe").write_bytes(b"old")
    assert core.find_game_folder(tmp_path, "game.exe", 6, preferred=preferred, reserved={installed}) == preferred
