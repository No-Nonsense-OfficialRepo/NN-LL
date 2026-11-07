"""A room beacon from a different Host must not replace the pinned Host key.

The join path used to overwrite trusted_host_pub with the beacon's key before
the join was verified. These checks pin the new behavior: a mismatched beacon
is refused before any network work, and the stored key is left untouched.
"""
import asyncio
import os
import sys
import pytest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

local_qt = Path(__file__).resolve().parents[1] / "build" / "qt-runtime"
if local_qt.is_dir():
    sys.path.insert(0, str(local_qt))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import lantool.qt  # noqa: F401,E402  (same eager Qt init as production)
from lantool import launcher as core  # noqa: E402

NET = "a" * 16
PINNED = "p" * 64
OTHER = "q" * 64


def _client(ensure_calls, failures):
    return SimpleNamespace(
        role="client", busy=False, room=None, room_controller=None,
        presence_client=None, peer_file_server=None, _beacon_joining=True,
        trusted_host_pub=PINNED,
        config_data={"trusted_host_pub": PINNED, "trusted_net_id": NET},
        tunnel=SimpleNamespace(ensure_ready=lambda: ensure_calls.append(1)),
        _recover_network_session=lambda: None,
        after=lambda delay, fn, *a: failures.append((fn, a)),
        _discovery_failed=lambda *a: None,
    )


def test_beacon_from_other_host_is_refused_and_pin_is_kept():
    ensure_calls, failures = [], []
    fake = _client(ensure_calls, failures)
    beacon = {"host_pub": OTHER, "host_zt": "10.9.8.7", "host": "10.9.8.7", "net_id": NET}

    with patch.object(core, "_write_config") as write:
        asyncio.run(core.LauncherCore._join_beacon_room(fake, beacon))

    assert fake.trusted_host_pub == PINNED
    assert fake.config_data["trusted_host_pub"] == PINNED
    write.assert_not_called()
    assert ensure_calls == []  # refused before any tunnel or network work
    assert failures and failures[0][0] is fake._discovery_failed
    assert "does not match the trusted host bundle" in failures[0][1][0]


def test_discovery_only_join_does_not_pin_host_when_join_fails():
    # No bundle imported: the beacon's key is not trusted until the join succeeds.
    ensure_calls, failures = [], []

    def broken_ready():
        ensure_calls.append(1)
        raise RuntimeError("VLA not ready")

    fake = _client(ensure_calls, failures)
    fake.trusted_host_pub = None
    fake.config_data = {}
    fake.tunnel = SimpleNamespace(ensure_ready=broken_ready)
    beacon = {"host_pub": OTHER, "host_zt": "10.9.8.7", "host": "10.9.8.7", "net_id": NET}

    with patch.object(core, "_write_config") as write:
        asyncio.run(core.LauncherCore._join_beacon_room(fake, beacon))

    assert ensure_calls == [1]  # the join was attempted
    assert fake.trusted_host_pub is None
    assert "trusted_host_pub" not in fake.config_data
    write.assert_not_called()
    assert failures and failures[0][0] is fake._discovery_failed


class _FakePresence:
    def __init__(self, *args, **kwargs):
        self.started = False

    def start(self):
        self.started = True

    async def publish_seeds(self, seeds, port):
        pass

    async def stop(self):
        pass


class _FakeRoomController:
    def __init__(self, *args, **kwargs):
        self.state = SimpleNamespace(value="idle")
        self.join_error = None
        self.room_ip = "10.9.8.8"

    async def on_beacon(self, beacon):
        self.state = SimpleNamespace(value="zerotier")

    async def leave(self):
        pass


class _FakePeerServer:
    port = 47900

    def __init__(self, *args, **kwargs):
        pass

    async def start(self):
        pass

    async def stop(self):
        pass


@pytest.mark.parametrize("switching_host", [False, True])
def test_discovery_only_join_success_pins_host_and_writes_config(switching_host):
    # No bundle imported: a join that completes pins the beacon's key and net id.
    ensure_calls, failures, scheduled = [], [], []

    async def idle(*_args):
        return None

    fake = _client(ensure_calls, failures)
    fake.trusted_host_pub = PINNED if switching_host else None
    fake.config_data = {"player_id": "player-1", "player_name": "Tester"}
    fake.client_bundle = {"host_pub": PINNED} if switching_host else None
    if switching_host:
        fake.config_data.update(trusted_host_pub=PINNED, trusted_bundle_path="old-bundle.json")
    fake.game_root = Path(".")
    fake._seeds_received = lambda *a: None
    fake._watch_host_library = idle
    fake._watch_host = idle
    fake._start_watcher = lambda: None
    fake._discovered_room_joined = lambda *a: None
    fake.after = lambda delay, fn, *a: scheduled.append((fn, a))
    beacon = {"host_pub": OTHER, "host_zt": "10.9.8.7", "host": "10.9.8.7", "net_id": NET}

    async def run():
        await core.LauncherCore._join_beacon_room(fake, beacon, allow_host_switch=switching_host)
        await asyncio.sleep(0)  # let the watcher tasks finish

    with patch.object(core, "PresenceClient", _FakePresence), \
         patch.object(core, "RoomController", _FakeRoomController), \
         patch.object(core, "PeerFileServer", _FakePeerServer), \
         patch.object(core, "SilentTunnelZT", lambda tunnel: tunnel), \
         patch.object(core, "AdapterSwitcher", lambda path: None), \
         patch.object(core, "_write_config") as write:
        asyncio.run(run())

    assert ensure_calls == [1]
    assert failures == []
    assert fake.trusted_host_pub == OTHER
    assert fake.config_data["trusted_host_pub"] == OTHER
    assert fake.config_data["trusted_net_id"] == NET
    assert "trusted_bundle_path" not in fake.config_data
    assert fake.client_bundle is None
    write.assert_called_once_with(fake.config_data)
    assert fake.room.network_id == NET and fake.room.discovered is True
    assert scheduled and scheduled[0][0] is fake._discovered_room_joined
