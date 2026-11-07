"""Verified pieces become available to peers while a file is still downloading."""
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

local_qt = Path(__file__).resolve().parents[1] / "build" / "qt-runtime"
if local_qt.is_dir():
    sys.path.insert(0, str(local_qt))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import lantool.qt  # noqa: F401,E402  (same eager Qt init as production)
from lantool import launcher as core  # noqa: E402

GID = "game1"


def _app():
    app = object.__new__(core.LauncherCore)
    app.seeded_games = set()
    app.seeded_files = {}
    app.peer_file_server = MagicMock()
    app.peer_file_server.port = 47803
    app.presence_client = MagicMock()
    app.presence_client.publish_seeds = AsyncMock()
    return app


def _entry(path, pieces):
    return {"path": path, "pieces": list(range(pieces))}


async def test_first_verified_piece_turns_seeding_on():
    app = _app()
    entry = _entry("a.bin", 3)
    await app._share_transfer_piece(GID, "dest", entry, 0)
    assert GID in app.seeded_games
    assert app.seeded_files[GID] == ["a.bin"]
    app.presence_client.publish_seeds.assert_awaited_once()


async def test_partial_files_become_available_without_duplicate_announcements():
    app = _app()
    first, second = _entry("a.bin", 2), _entry("b.bin", 2)
    await app._share_transfer_piece(GID, "dest", first, 0)
    assert GID in app.seeded_games
    assert app.seeded_files[GID] == ["a.bin"]
    app.presence_client.publish_seeds.assert_awaited_once()

    # Another file becomes shareable as soon as one of its pieces verifies.
    await app._share_transfer_piece(GID, "dest", second, 0)
    assert GID in app.seeded_games
    assert app.seeded_files[GID] == ["a.bin", "b.bin"]
    assert app.presence_client.publish_seeds.await_count == 2


async def test_repeated_piece_callbacks_do_not_duplicate_or_republish():
    app = _app()
    entry = _entry("a.bin", 1)
    await app._share_transfer_piece(GID, "dest", entry, 0)
    await app._share_transfer_piece(GID, "dest", entry, 0)
    assert app.seeded_files[GID] == ["a.bin"]
    app.presence_client.publish_seeds.assert_awaited_once()
