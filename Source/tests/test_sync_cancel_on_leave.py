"""Leaving the room or losing the host must stop a running or paused game sync (audit 1)."""
import asyncio
import concurrent.futures
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
from lantool.filesync.control import TransferControl  # noqa: E402


def _app():
    return object.__new__(core.LauncherCore)


def test_cancel_sync_without_a_sync_is_a_noop():
    app = _app()  # no _sync_future attribute at all
    app._cancel_sync()
    app._sync_future = None
    app._cancel_sync()
    done = concurrent.futures.Future()
    done.set_result(1)
    app._sync_future = done
    app._cancel_sync()
    assert done.result() == 1


def test_cancel_sync_cancels_a_pending_future():
    app = _app()
    pending = concurrent.futures.Future()
    app._sync_future = pending
    app._cancel_sync()
    assert pending.cancelled()


async def test_cancel_sync_stops_a_paused_transfer():
    control = TransferControl()
    started, ended = asyncio.Event(), asyncio.Event()

    async def factory():
        started.set()
        await asyncio.sleep(3600)

    async def sync():
        try:
            return await control.run(factory)
        finally:
            ended.set()

    app = _app()
    app._sync_future = asyncio.run_coroutine_threadsafe(sync(), asyncio.get_running_loop())
    await asyncio.wait_for(started.wait(), 2)
    control.pause()
    await asyncio.sleep(0.05)  # the controller is now parked waiting for Resume
    assert not ended.is_set()
    app._cancel_sync()
    await asyncio.wait_for(ended.wait(), 2)  # the underlying task really stopped, not just the future
    assert app._sync_future.cancelled()


async def test_drained_submission_notifies_only_after_real_cleanup():
    started, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def work():
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
    future = core.submit_drained(asyncio.get_running_loop(), work())
    notified = []
    future.add_done_callback(lambda _: notified.append(True))
    await started.wait()
    future.cancel()
    await cleaning.wait()
    future.cancel()  # must not interrupt the cleanup await
    await asyncio.sleep(0)
    assert not future.done() and not notified
    release.set()
    for _ in range(10):
        if future.done():
            break
        await asyncio.sleep(0)
    assert future.cancelled() and notified == [True]


def _finish(error):
    app = _app()
    app.syncing_game = True
    app._sync_control = object()
    app._sync_future = object()
    app.peer_file_server = None
    app._close_sync_progress = MagicMock()
    app.pages = {"room": MagicMock()}
    errors = []
    original = core.messagebox.showerror
    core.messagebox.showerror = lambda *args, **kwargs: errors.append(args)
    try:
        app._sync_finished({"name": "G", "id": "g"}, {}, None, error, launch_after=False)
    finally:
        core.messagebox.showerror = original
    return app, errors


def test_cancelled_sync_releases_the_ui_without_an_error_popup():
    for error in (asyncio.CancelledError(), concurrent.futures.CancelledError()):
        app, errors = _finish(error)
        assert app.syncing_game is False
        assert app._sync_control is None and app._sync_future is None
        assert errors == []
        app._close_sync_progress.assert_called_once()
        app.pages["room"].set_status.assert_called_once_with("Download stopped.")


def test_failed_sync_still_shows_the_error_popup():
    app, errors = _finish(RuntimeError("boom"))
    assert app.syncing_game is False and app._sync_future is None
    assert len(errors) == 1
