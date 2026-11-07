"""_beacon_seen must not store a beacon from a host other than the pinned one (audit A06)."""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

local_qt = Path(__file__).resolve().parents[1] / "build" / "qt-runtime"
if local_qt.is_dir():
    sys.path.insert(0, str(local_qt))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import lantool.qt  # noqa: F401,E402  (same eager Qt init as production)
from lantool import launcher as core  # noqa: E402

PINNED = "p" * 64
OTHER = "q" * 64


def _client(pinned, last=None):
    fake = object.__new__(core.LauncherCore)
    fake.role = "client"
    fake.busy = False
    fake.room_controller = None
    fake.room = None
    fake._beacon_joining = True  # skips starting a join task; the join path is not under test
    fake.trusted_host_pub = pinned
    fake.last_beacon = last
    return fake


def _beacon(pub, ip="10.0.0.9"):
    return {"host": ip, "host_zt": ip, "host_pub": pub, "net_id": "net1", "sync_port": 47803}


def test_beacon_from_another_host_leaves_last_beacon_unchanged():
    original = _beacon(PINNED, "10.0.0.2")
    fake = _client(PINNED, last=original)
    fake._beacon_seen(_beacon(OTHER))
    assert fake.last_beacon is original


def test_beacon_from_another_host_is_not_stored_when_none_was_set():
    fake = _client(PINNED)
    fake._beacon_seen(_beacon(OTHER))
    assert fake.last_beacon is None


def test_beacon_from_the_pinned_host_is_stored():
    fake = _client(PINNED)
    beacon = _beacon(PINNED)
    fake._beacon_seen(beacon)
    assert fake.last_beacon is beacon


def test_without_a_pinned_key_discovery_still_stores_the_beacon():
    fake = _client(None)
    beacon = _beacon(OTHER)
    fake._beacon_seen(beacon)
    assert fake.last_beacon is beacon
