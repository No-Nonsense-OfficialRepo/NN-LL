"""A request dropped because room setup is busy shows a status message (audit A17)."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

local_qt = Path(__file__).resolve().parents[1] / "build" / "qt-runtime"
if local_qt.is_dir():
    sys.path.insert(0, str(local_qt))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import lantool.qt  # noqa: F401,E402  (same eager Qt init as production)
from lantool import launcher as core  # noqa: E402


def _fake(busy):
    room = MagicMock()
    return SimpleNamespace(busy=busy, pages={"room": room}, runtime=MagicMock()), room


def test_busy_request_is_dropped_with_a_status_message():
    fake, room = _fake(busy=True)
    work, done = MagicMock(), MagicMock()
    core.LauncherCore._run_background(fake, work, done)
    room.set_status.assert_called_once()
    assert "ignored" in room.set_status.call_args.args[0]
    fake.runtime.submit.assert_not_called()
    work.assert_not_called()
    assert fake.busy is True


def test_idle_request_starts_and_shows_its_label_only():
    fake, room = _fake(busy=False)
    core.LauncherCore._run_background(fake, MagicMock(), MagicMock(), "Joining…")
    room.set_status.assert_called_once_with("Joining…")
    fake.runtime.submit.assert_called_once()
    fake.runtime.submit.call_args.args[0].close()  # the mock runtime never runs it; avoid "never awaited"
    assert fake.busy is True
