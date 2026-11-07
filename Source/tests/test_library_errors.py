"""A host-key mismatch must reach the room status and the log, not vanish (audit A05).

The library loop used to swallow every error and retry every 3 seconds with no feedback.
"""
import asyncio
import logging
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

PINNED = "p" * 64
OTHER = "q" * 64


def test_host_key_mismatch_is_logged_and_shown_in_room_status(caplog):
    fake = object.__new__(core.LauncherCore)
    fake.room_controller = object()
    fake.client_bundle = {"host_pub": PINNED}
    fake.last_beacon = None  # the loop follows the latest beacon (audit A07)
    fake.peer_file_server = None
    fake.presence_client = None
    fake.syncing_game = None
    fake.pages = {"room": MagicMock()}
    fake.after = MagicMock()
    fake._fetch_host_library = AsyncMock()
    beacon = {"host": "10.0.0.2", "host_zt": "10.0.0.3", "host_pub": OTHER, "sync_port": 47803}

    async def stop_after_one_pass(_seconds):
        fake.room_controller = None  # end the loop after the first pass

    caplog.set_level(logging.WARNING)
    with patch.object(core.asyncio, "sleep", new=AsyncMock(side_effect=stop_after_one_pass)):
        asyncio.run(core.LauncherCore._watch_host_library(fake, beacon))

    fake._fetch_host_library.assert_not_awaited()  # refused before any network work
    fake.after.assert_called_once()
    assert fake.after.call_args[0][1] == fake.pages["room"].set_status
    assert "Host key mismatch" in fake.after.call_args[0][2]
    assert "does not match the imported join bundle" in caplog.text
