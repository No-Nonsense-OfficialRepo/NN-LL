"""The library poll backs off while nothing changes and snaps back on a change (audit A03)."""
import asyncio
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

HOST_PUB = "p" * 64


def _delays(results):
    fake = object.__new__(core.LauncherCore)
    fake.room_controller = object()
    fake.client_bundle = None
    fake.last_beacon = None
    fake.peer_file_server = None
    fake.presence_client = None
    fake.syncing_game = True  # skip the seed check
    fake.pages = {"room": MagicMock()}
    fake.after = MagicMock()
    fake._fetch_host_library = AsyncMock(side_effect=list(results))
    beacon = {"host": "10.0.0.2", "host_zt": "10.0.0.3", "host_pub": HOST_PUB, "sync_port": 47803}
    delays = []

    async def record(seconds):
        delays.append(seconds)
        if len(delays) == len(results):
            fake.room_controller = None  # end the loop

    with patch.object(core.asyncio, "sleep", new=AsyncMock(side_effect=record)):
        asyncio.run(core.LauncherCore._watch_host_library(fake, beacon))
    return delays


def test_unchanged_library_backs_off_and_caps():
    assert _delays([False] * 5) == [6, 12, 15, 15, 15]


def test_change_resets_the_interval():
    assert _delays([False, False, True, False]) == [6, 12, 3, 6]
