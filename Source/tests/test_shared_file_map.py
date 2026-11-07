"""Games with no verified file yet (empty file list) must never be advertised to peers."""
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

local_qt = Path(__file__).resolve().parents[1] / "build" / "qt-runtime"
if local_qt.is_dir():
    sys.path.insert(0, str(local_qt))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import lantool.qt  # noqa: F401,E402
from lantool import launcher as core  # noqa: E402


def _app():
    app = object.__new__(core.LauncherCore)
    app.seeded_games = set()
    app.seeded_files = {}
    app.peer_file_server = MagicMock()
    app.peer_file_server.port = 47803
    app.presence_client = MagicMock()
    app.presence_client.publish_seeds = AsyncMock()
    return app


def test_shared_file_map_skips_empty_lists():
    app = _app()
    app.seeded_files = {"g1": ["a.bin"], "g2": []}
    assert app._shared_file_map() == {"g1": ["a.bin"]}
    assert app._shared_file_map({"g1", "g2", "missing"}) == {"g1": ["a.bin"]}


async def test_partial_second_game_is_not_advertised_when_first_completes():
    app = _app()
    app.seeded_files["g2"] = []  # g2 started downloading, nothing verified yet
    await app._share_transfer_piece("g1", "dest", {"path": "a.bin", "pieces": [0]}, 0)
    app.peer_file_server.set_shared_files.assert_called_once_with({"g1": ["a.bin"]})
