"""A failed room join must clear self.room so the next beacon can retry (audit A01).

self.room is assigned before the config is written. If anything after that
fails, the except path has to reset it, or _beacon_seen (which checks
`not self.room`) never starts another join.
"""
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

local_qt = Path(__file__).resolve().parents[1] / "build" / "qt-runtime"
if local_qt.is_dir():
    sys.path.insert(0, str(local_qt))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import lantool.qt  # noqa: F401,E402  (same eager Qt init as production)
from lantool import launcher as core  # noqa: E402

NET = "a" * 16
PINNED = "p" * 64


def _client(failures):
    return SimpleNamespace(
        role="client", busy=False, room=None, room_controller=None,
        presence_client=None, peer_file_server=None, _beacon_joining=True,
        trusted_host_pub=PINNED, last_beacon=None, _discovery_listening_since=0.0,
        config_data={"trusted_host_pub": PINNED, "trusted_net_id": NET, "player_id": "pid"},
        tunnel=SimpleNamespace(ensure_ready=lambda: None),
        _recover_network_session=lambda: None,
        after=lambda delay, fn, *a: failures.append((fn, a)),
        _discovery_failed=lambda *a: None,
        _discovered_room_joined=lambda *a: None,
        _seeds_received=lambda *a: None,
        _join_beacon_room=AsyncMock(),
        _watch_host=AsyncMock(),
        _watch_host_library=AsyncMock(),
        _start_watcher=lambda: None,
    )


def _fake_services():
    room_controller = MagicMock()
    room_controller.on_beacon = AsyncMock()
    room_controller.state = SimpleNamespace(value="zerotier")
    room_controller.leave = AsyncMock()
    presence = MagicMock()
    presence.publish_seeds = AsyncMock()
    presence.stop = AsyncMock()
    peer_server = MagicMock()
    peer_server.start = AsyncMock()
    peer_server.stop = AsyncMock()
    peer_server.port = 47900
    return room_controller, presence, peer_server


def test_failed_join_after_room_assigned_clears_room_and_allows_retry():
    failures = []
    fake = _client(failures)
    fake.game_root = Path(".")
    fake._discovery_listening_since = 0.0
    beacon = {"host_pub": PINNED, "host_zt": "10.9.8.7", "host": "10.9.8.7", "net_id": NET}
    room_controller, presence, peer_server = _fake_services()

    with patch.object(core, "SilentTunnelZT"), patch.object(core, "AdapterSwitcher"), \
         patch.object(core, "RoomController", return_value=room_controller), \
         patch.object(core, "PresenceClient", return_value=presence), \
         patch.object(core, "PeerFileServer", return_value=peer_server), \
         patch.object(core, "_write_config", side_effect=RuntimeError("disk full")):
        asyncio.run(core.LauncherCore._join_beacon_room(fake, beacon))

    # The room was assigned, then the failure after it must have cleared it.
    assert fake.room is None
    assert fake._beacon_joining is False
    assert failures and failures[0][0] is fake._discovery_failed
    presence.stop.assert_awaited_once()
    assert fake.presence_client is None

    # The next beacon must start a new join instead of being ignored.
    with patch.object(core.asyncio, "create_task") as create_task:
        core.LauncherCore._beacon_seen(fake, beacon)
    create_task.assert_called_once()
    create_task.call_args[0][0].close()
    fake._join_beacon_room.assert_called_once_with(beacon)
    assert fake._beacon_joining is True
