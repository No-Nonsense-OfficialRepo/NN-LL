"""The library loop follows the host's latest beacon address, but only for the same host key and room (audit A07)."""
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
OTHER_PUB = "q" * 64


def _beacon(ip, pub=HOST_PUB, net="NET1"):
    return {"host": ip, "host_zt": ip, "host_pub": pub, "net_id": net, "sync_port": 47803}


def _fetched_hosts(next_beacons):
    """Run one pass per entry; before each pass after the first, last_beacon becomes that entry."""
    fake = object.__new__(core.LauncherCore)
    fake.room_controller = object()
    fake.client_bundle = None
    fake.last_beacon = None
    fake.peer_file_server = None
    fake.presence_client = None
    fake.syncing_game = True
    fake.pages = {"room": MagicMock()}
    fake.after = MagicMock()
    hosts = []

    async def fetch(host, _port, _pub):
        hosts.append(host)
        return True

    fake._fetch_host_library = fetch
    passes = [None] + list(next_beacons)

    async def sleep(_seconds):
        passes.pop(0)
        if not passes:
            fake.room_controller = None
        else:
            fake.last_beacon = passes[0]

    with patch.object(core.asyncio, "sleep", new=AsyncMock(side_effect=sleep)):
        asyncio.run(core.LauncherCore._watch_host_library(fake, _beacon("10.0.0.2")))
    return hosts


def test_next_pass_uses_the_new_address():
    assert _fetched_hosts([_beacon("10.0.0.9")]) == ["10.0.0.2", "10.0.0.9"]


def test_beacon_from_another_host_key_is_ignored():
    assert _fetched_hosts([_beacon("10.0.0.9", pub=OTHER_PUB)]) == ["10.0.0.2", "10.0.0.2"]


def test_beacon_from_another_room_is_ignored():
    assert _fetched_hosts([_beacon("10.0.0.9", net="NET2")]) == ["10.0.0.2", "10.0.0.2"]
