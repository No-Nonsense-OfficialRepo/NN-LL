"""Shutdown steps time out, are logged, and cannot keep the window open (audit A15)."""
import asyncio
import logging
import os
import sys
import time
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


class _Service:
    def __init__(self, hang=False, fail=False):
        self.hang, self.fail, self.stopped = hang, fail, False

    async def stop(self):
        self.stopped = True
        if self.hang:
            await asyncio.sleep(60)
        if self.fail:
            raise RuntimeError('stop failed')


def _core(runtime, **services):
    scheduled = []
    attrs = dict(
        _closing=False, busy=False, role='host', config_data={}, _close_finished=False, _close_step=None,
        tunnel=SimpleNamespace(settings=SimpleNamespace(uninstall_on_exit=False), cleanup=lambda uninstall=None: []),
        _network_session_recovered=False, room_controller=None, room=None, host_room=None,
        discovery_task=None, library_refresh_task=None, beacon_transport=None, host_conflict_transport=None,
        peer_file_server=None, process_watcher=None, presence_client=None, presence_server=None,
        file_sync_server=None, runtime=runtime, destroyed=0, scheduled=scheduled)
    attrs.update(services)
    fake = SimpleNamespace(**attrs)

    async def prewarm():
        return None
    fake._stop_file_sync_prewarm = prewarm
    fake.after = lambda delay, fn=None, *args: scheduled.append((delay, getattr(fn, '__name__', fn)))
    fake.destroy = lambda: setattr(fake, 'destroyed', fake.destroyed + 1)
    fake._finish_close = lambda force=False: core.LauncherCore._finish_close(fake, force)
    fake._close_deadline = lambda: core.LauncherCore._close_deadline(fake)
    return fake


def _close(fake):
    with patch.object(core, '_write_config'), patch.object(core, '_other_launcher_running', return_value=False), \
            patch.object(core, '_same_role_launcher_running', return_value=False), \
            patch.object(core, 'SHUTDOWN_STEP_TIMEOUT', 0.2):
        core.LauncherCore.close(fake)


def test_hanging_step_times_out_logs_and_later_steps_still_run(caplog):
    runtime = core.AsyncLoopThread()
    try:
        client, server = _Service(hang=True), _Service()
        fake = _core(runtime, presence_client=client, file_sync_server=server)
        started = time.monotonic()
        with caplog.at_level(logging.ERROR):
            _close(fake)
            future_done = False
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not server.stopped:
                time.sleep(0.01)
            future_done = server.stopped
        assert future_done, 'a step after the hung one never ran'
        assert time.monotonic() - started < 3
        assert client.stopped
        assert any('presence client' in r.getMessage() and 'timed out' in r.getMessage() for r in caplog.records)
        assert any(delay == int(core.CLOSE_DEADLINE * 1000) for delay, _name in fake.scheduled)
    finally:
        runtime.stop()


def test_failing_step_is_logged_and_shutdown_continues(caplog):
    runtime = core.AsyncLoopThread()
    try:
        client, server = _Service(fail=True), _Service()
        fake = _core(runtime, presence_client=client, file_sync_server=server)
        with caplog.at_level(logging.ERROR):
            _close(fake)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not server.stopped:
                time.sleep(0.01)
        assert server.stopped
        assert any('presence client' in r.getMessage() for r in caplog.records)
    finally:
        runtime.stop()


def test_deadline_closes_window_even_if_runtime_thread_is_stuck(caplog):
    stuck = SimpleNamespace(stop=lambda timeout=0: None, thread=SimpleNamespace(is_alive=lambda: True))
    fake = _core(stuck)
    fake._close_step = 'network cleanup'
    with caplog.at_level(logging.ERROR):
        core.LauncherCore._close_deadline(fake)
    assert fake.destroyed == 1
    assert any('network cleanup' in r.getMessage() for r in caplog.records)
    core.LauncherCore._close_deadline(fake)  # a second deadline firing is harmless
    assert fake.destroyed == 1


def test_normal_finish_still_waits_for_a_live_runtime_thread():
    stuck = SimpleNamespace(stop=lambda timeout=0: None, thread=SimpleNamespace(is_alive=lambda: True))
    fake = _core(stuck)
    core.LauncherCore._finish_close(fake)
    assert fake.destroyed == 0
    assert fake.scheduled and fake.scheduled[-1][0] == 50
