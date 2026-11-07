"""leave_room must clear busy and reset room state even when stopping services hangs or fails (audit A02).

The stop step runs on the Qt runtime loop. If it never finishes, or raises, the
network teardown still has to run and the room state still has to be reset.
"""
import asyncio
import concurrent.futures
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

local_qt = Path(__file__).resolve().parents[1] / "build" / "qt-runtime"
if local_qt.is_dir():
    sys.path.insert(0, str(local_qt))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import lantool.qt  # noqa: F401,E402  (same eager Qt init as production)
from lantool import launcher as core  # noqa: E402


class _Runtime:
    loop = None

    def submit(self, coro):
        future = concurrent.futures.Future()
        try:
            future.set_result(asyncio.run(coro))
        except Exception as exc:
            future.set_exception(exc)
        return future


def _client_in_room():
    fake = object.__new__(core.LauncherCore)
    fake.busy = False
    fake.role = "client"
    fake.room = SimpleNamespace(network_id="a" * 16, code="ROOM", host_ip="10.0.0.2")
    fake.last_beacon = {"host": "10.0.0.2"}
    fake._beacon_joining = True
    fake.library = {"g": 1}
    fake.seeded_games = set()
    fake.seeded_files = set()
    fake.peer_sources = []
    fake.pages = {"room": MagicMock(), "library": MagicMock()}
    fake.room_nav_status = MagicMock()
    fake.runtime = _Runtime()
    fake.tunnel = MagicMock()
    fake.after = lambda delay, fn, *a: fn(*a)
    for name in ("discovery_task", "library_refresh_task", "beacon_transport",
                 "host_conflict_transport", "room_controller", "peer_file_server",
                 "process_watcher", "presence_client", "presence_server", "host_room",
                 "file_sync_server"):
        setattr(fake, name, None)
    return fake


def _run_leave(stop_future, timeout):
    def fake_run_coroutine_threadsafe(coro, loop):
        coro.close()  # the stop step never runs in these tests
        return stop_future

    with patch.object(core.asyncio, "run_coroutine_threadsafe", side_effect=fake_run_coroutine_threadsafe), \
         patch.object(core, "AdapterSwitcher"), \
         patch.object(core.LauncherCore, "_log_room_error") as log_error:
        fake = _client_in_room()
        fake.leave_room(timeout=timeout)
    return fake, log_error


def _assert_torn_down(fake, log_error):
    assert fake.busy is False
    assert fake.room is None
    assert fake.last_beacon is None
    assert fake._beacon_joining is False
    fake.tunnel.leave.assert_called_once()  # network teardown still ran
    log_error.assert_called_once()
    fake.pages["room"].set_status.assert_called_with(
        "Left the room, but some services didn't stop cleanly. See room-errors.log.")


def test_hanging_stop_times_out_and_still_tears_down_network():
    hanging = concurrent.futures.Future()  # never completes
    fake, log_error = _run_leave(hanging, timeout=0.05)
    _assert_torn_down(fake, log_error)
    assert hanging.cancelled()


def test_failing_stop_still_tears_down_network():
    failing = concurrent.futures.Future()
    failing.set_exception(RuntimeError("stop failed"))
    fake, log_error = _run_leave(failing, timeout=5)
    _assert_torn_down(fake, log_error)
    assert str(log_error.call_args[0][0]) == "stop failed"
